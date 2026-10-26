"""定数（印・関数の名前の集合・正規表現）と、1 回の読み込み全体で共有する Context。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aws_iac_diagram.adapters.cloudformation.stack import StackEval


PSEUDO = {"AWS::Region", "AWS::AccountId", "AWS::Partition", "AWS::StackName", "AWS::StackId",
          "AWS::URLSuffix", "AWS::NotificationARNs"}

NO_VALUE = object()  # AWS::NoValue（プロパティやリストの要素ごと消す）

# 条件関数（Conditions の中と、プロパティの中の両方で評価する）
CONDITION_FNS = {"Fn::Equals", "Fn::And", "Fn::Or", "Fn::Not"}

# 評価しない関数（値は $unknown。中の参照は unevaluated で残す）
UNEVALUATED = {"Fn::Base64", "Fn::Cidr", "Fn::Transform", "Fn::ForEach"}

UNKNOWN = object()  # 条件の評価で、値が決まらないもの

OUTSIDE_PROPS = ("Metadata", "CreationPolicy", "UpdatePolicy")

SUB_VAR = re.compile(r"\$\{([^}]*)\}")

TEMPLATE_SUFFIXES = (".yaml", ".yml", ".json", ".template")

IN_PROGRESS = object()  # 子のスタックを展開している途中（循環の検出）

STACK_NAME = re.compile(r"[A-Za-z][-A-Za-z0-9]*")

SKIP_DIRS = {"node_modules", ".git", "cdk.out", ".aws-sam", "__pycache__", ".venv"}


class Context:
    """1回の読み込み全体で共有するもの（リソースと参照の集まり、診断、Export の表）。"""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.diagnostics: list[dict] = []
        self.resources: list[dict] = []
        self.refs: list[dict] = []
        self.stacks: list[StackEval] = []
        self.assumptions: list[str] = []
        self.exports: dict[str, tuple[StackEval, str]] = {}
        self.active_files: list[Path] = []
        self._files: list[str] | None = None
        self.pseudo_values: dict = {}

    def rel(self, path: Path) -> str:
        return Path(os.path.relpath(path.resolve(), self.root_dir.resolve())).as_posix()

    def local_files(self) -> list[str]:
        """URL を読み替える候補のファイル。node_modules・.git などの下は除く。"""
        if self._files is None:
            self._files = sorted(
                self.rel(p) for p in self.root_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in TEMPLATE_SUFFIXES
                and not SKIP_DIRS.intersection(p.relative_to(self.root_dir).parts[:-1]))
        return self._files
