"""モジュールの評価で共有するデータの型: ブロック、count・for_each の評価結果、読み込み全体の入れ物、展開したモジュール。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from lark import Tree

from aws_iac_diagram.adapters.terraform.evaluator.functions import Unknown
from aws_iac_diagram.adapters.terraform.hcl import sig

if TYPE_CHECKING:
    from aws_iac_diagram.adapters.terraform.module_eval import ModuleEval


# ブロックの最上位のメタ引数（props に入れない）
RESOURCE_META = {"count", "for_each", "provider", "depends_on", "lifecycle", "provisioner", "connection"}
DATA_META = {"count", "for_each", "provider", "depends_on", "lifecycle"}
MODULE_META = {"source", "version", "count", "for_each", "providers", "depends_on"}


def weakest(a, b):
    """enabled の弱い方（false > null > true）。モジュールの中のリソースは、呼び出しの値を引き継ぐ。"""
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


class ModObj:
    """展開したモジュールの呼び出しのインスタンス1つ（module.x、module.x[0]）。属性で引くと、子の出力の値。"""

    __slots__ = ("child",)

    def __init__(self, child: "ModuleEval"):
        self.child = child


@dataclass
class Block:
    kind: str  # resource／data／module／ephemeral
    type: str  # module のときは "module"
    name: str
    file: str
    body: Tree
    attrs: dict = field(default_factory=dict)  # 最上位の属性 → 式の木

    @property
    def base(self) -> str:
        if self.kind == "data":
            return f"data.{self.type}.{self.name}"
        if self.kind == "module":
            return f"module.{self.name}"
        if self.kind == "ephemeral":
            return f"ephemeral.{self.type}.{self.name}"
        return f"{self.type}.{self.name}"

    @property
    def plain(self) -> bool:
        """引数の無い data（data.aws_region.current など）。擬似パラメータとして扱えるもの。"""
        return set(self.attrs) <= {"depends_on"} and not any(
            isinstance(c, Tree) and c.data == "block" for c in sig(self.body))


@dataclass
class Instances:
    """count・for_each を評価した結果。mode は single／count／each／zero／unknown。"""
    mode: str
    meta: str = ""  # "count"・"for_each"（single では空）
    keys: list = field(default_factory=list)  # count は番号、for_each はキー
    values: dict = field(default_factory=dict)  # for_each のキー → each.value
    unknown: Unknown | None = None  # mode が unknown のときの値


class ResList(list):
    """count のリソースのまとまり（インスタンスごとの Res のリスト）。添字で引いても他のインスタンスを pruned にしない。"""


class ResMap(dict):
    """for_each のリソースのまとまり（キー → Res）。"""


class Context:
    """1回の読み込み全体で共有するもの（リソースと参照の集まり、診断、前提）。"""

    def __init__(self, root_dir: Path, workspace: str = "default"):
        self.root_dir = root_dir
        self.workspace = workspace  # terraform.workspace の値（--workspace）
        self.diagnostics: list[dict] = []
        self.resources: list[dict] = []
        self.refs: list[dict] = []
        self.assumptions: list[str] = []
        self.modules: list["ModuleEval"] = []  # 展開したモジュール（evaluation.vars を書くため）

    def rel(self, path: Path) -> str:
        # 両方を resolve してから比べる（Windows の 8.3 の短い名前 `RUNNER~1` と実際の名前が混ざると、`../..` だらけになる）
        try:
            return Path(os.path.relpath(Path(path).resolve(), Path(self.root_dir).resolve())).as_posix()
        except ValueError:  # Windows でドライブが違う
            return Path(path).resolve().as_posix()

    def assume(self, text: str) -> None:
        if text not in self.assumptions:
            self.assumptions.append(text)
