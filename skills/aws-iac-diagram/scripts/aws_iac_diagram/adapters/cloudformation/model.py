"""定数（印・関数の名前の集合・正規表現）と、1 回の読み込み全体で共有する Context。"""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aws_iac_diagram.adapters.cloudformation.stack import StackEval


PSEUDO = {"AWS::Region", "AWS::AccountId", "AWS::Partition", "AWS::StackName", "AWS::StackId",
          "AWS::URLSuffix", "AWS::NotificationARNs"}

NO_VALUE = object()  # AWS::NoValue（プロパティやリストの要素ごと消す）

# 条件関数（Conditions の中と、プロパティの中の両方で評価する）
CONDITION_FNS = {"Fn::Equals", "Fn::And", "Fn::Or", "Fn::Not"}

# 評価しない関数（値は $unknown。中の参照は unevaluated で残す）。Fn::Transform は AWS::Include の手元のファイルだけ
# 展開し（include.py）、ほか（マクロ、読めないファイル）は同じく評価しない
UNEVALUATED = {"Fn::Base64", "Fn::Cidr", "Fn::ForEach"}

UNKNOWN = object()  # 条件の評価で、値が決まらないもの

OUTSIDE_PROPS = ("Metadata", "CreationPolicy", "UpdatePolicy")

SUB_VAR = re.compile(r"\$\{([^}]*)\}")

TEMPLATE_SUFFIXES = (".yaml", ".yml", ".json", ".template")

IN_PROGRESS = object()  # 子のスタックを展開している途中（循環の検出）

STACK_NAME = re.compile(r"[A-Za-z][-A-Za-z0-9]*")

SKIP_DIRS = {"node_modules", ".git", "cdk.out", ".aws-sam", "__pycache__", ".venv"}


def inside_root(root_dir: Path, base: Path, rel: str) -> Path | None:
    """base からの相対パス rel を、root のフォルダの中のパス（resolve 済み）にする。root の外なら None（ir-schema の 7.4）。

    ファイルシステムに触る前に、文字列で絶対パス・ドライブ（`C:`）・UNC（`//host/…` と、逆スラッシュで書いた同じ形）を弾く（ネットワークに
    触らない）。そのあと resolve し（`..`・シンボリックリンク・ジャンクションをたどる）、root の中かを確かめる。ファイルの有無は見ない。
    ネストスタックの TemplateURL・CDK の aws:asset:path と manifest.json の templateFile・directoryName、AWS::Include の
    Location（相対パスと、URL を読み替えたもの）が使う。"""
    if not isinstance(rel, str) or not rel or "\0" in rel:
        return None
    if (PureWindowsPath(rel).anchor or PurePosixPath(rel).anchor or rel.startswith(("/", "\\"))
            or rel.startswith("~")):
        return None
    try:
        path = (base / rel).resolve()
        root = root_dir.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    return path if path.is_relative_to(root) else None


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

    def match_url(self, url: str) -> str | None:
        """URL（S3 の URL など）のパスを、root の下のファイルの相対パスと末尾から / 区切りの要素ごとに比べ、一致する要素が
        最も多いファイル（root からの相対パス）を返す（ir-schema の 7.4）。最も多いものが 2 つ以上か、1 要素も一致しなければ None。"""
        tail = [s for s in re.sub(r"^[a-z0-9]+://[^/]*", "", url).split("?")[0].split("/") if s]
        best, hits = 0, []
        for f in self.local_files():
            segs = f.split("/")
            n = 0
            while n < min(len(segs), len(tail)) and segs[-1 - n] == tail[-1 - n]:
                n += 1
            if n > best:
                best, hits = n, [f]
            elif n == best and n:
                hits.append(f)
        return hits[0] if best and len(hits) == 1 else None

    def inside_root(self, base: Path, rel: str) -> Path | None:
        """base からの相対パス rel を、root のフォルダの中のパス（resolve 済み）にする。root の外なら None（関数 inside_root）。"""
        return inside_root(self.root_dir, base, rel)
