"""Terraform のモジュールの source の見分け: レジストリの source の形と、IAM だけを作るモジュール（規則 H-IAM）の一覧。

TF アダプタ（診断の文言）とフェーズ 3 の正規化（IAM だけのモジュールを `hidden`／`H-IAM` にする。ir-schema の 2章）が同じ判定を使うので、
アダプタの中ではなく core に置く（`normalize` は core だけを import できる）。出力は移す前と同じ。

IAM だけを作るモジュールの source は、`data/module-summaries/iam-only-sources.md` の
  <!-- iam-only-sources -->
の直後のコードブロックに 1 行に 1 つ書く（サブモジュール "//…" も含む。`#` で始まる行は読まない）。要約表（`<モジュール>/v<数字>.md`）の
読み込みはアダプタの `modules/summaries.py` にあり、そこも同じマーカーの読み方（`IAM_MARK`・`fenced_after`・`iam_entries`）をここから使う。
ここは `iam-only-sources.md` だけを読む（要約表の中のマーカーは読まない。そこに書いた誤りは `summaries.problems()` が知らせる）。

標準ライブラリと core 自身（paths）だけを使う（core の決まり）。
"""
from __future__ import annotations

import re
from pathlib import Path

from aws_iac_diagram.core import paths

IAM_FILE = "iam-only-sources.md"  # 要約表のフォルダの直下
IAM_MARK = re.compile(r"<!--\s*iam-only-sources\s*-->")
FENCE = re.compile(r"^```[a-z]*\s*$")

_REGISTRY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_-]*$")


def registry_key(source: str) -> str | None:
    """レジストリの source なら、ホスト名を除いた形（namespace/name/provider、サブモジュールは //path 付き）。"""
    s = source.strip()
    for host in ("registry.terraform.io/", "registry.opentofu.org/"):
        if s.startswith(host):
            s = s[len(host):]
    if "::" in s or "://" in s or "?" in s or s.startswith(("github.com/", "bitbucket.org/", "git@")):
        return None
    base, _, sub = s.partition("//")
    if not _REGISTRY.match(base):
        return None
    sub = "/".join(p for p in sub.split("/") if p and p != ".")
    return base + (f"//{sub}" if sub else "")


def fenced_after(lines: list[str], i: int) -> tuple[str, int] | None:
    """lines[i] の後ろの最初のコードブロックの中身と、その最初の行の番号（0 始まり）。マーカーの直後に空行を挟んでよい。"""
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines) or not FENCE.match(lines[j].strip()):
        return None
    k = j + 1
    while k < len(lines) and lines[k].strip() != "```":
        k += 1
    return "\n".join(lines[j + 1:k]) + "\n", j + 1


def iam_entries(block: str) -> list[str]:
    """コードブロックの中身から source の並びを取る（空行と `#` の行は読まない）。"""
    return [x.strip() for x in block.splitlines() if x.strip() and not x.strip().startswith("#")]


_CACHE: dict = {}


def load_iam_sources(path: Path | None = None) -> tuple[str, ...]:
    """IAM だけを作るモジュールの source の並び（`path` は要約表のフォルダ、省略すると SKILL の data/module-summaries/。
    ファイルを渡すと、そのファイルだけを読む）。読めなければ空。"""
    path = path or paths.MODULE_SUMMARIES_DIR
    key = str(path)
    if key in _CACHE:
        return _CACHE[key]
    out: list[str] = []
    try:
        f = path if path.is_file() else path / IAM_FILE
        lines = f.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n") if f.is_file() else []
    except OSError:
        lines = []
    for i, line in enumerate(lines):
        if IAM_MARK.search(line):
            got = fenced_after(lines, i)
            if got is not None:
                out += iam_entries(got[0])
    _CACHE[key] = tuple(out)
    return _CACHE[key]


def iam_only(source: str, path: Path | None = None) -> bool:
    """IAM のリソースだけを作るモジュールか（正規化の H-IAM。ir-schema の 2章）。source の前方一致（ホスト名は除く）。"""
    key = registry_key(source)
    if key is None:
        return False
    for s in load_iam_sources(path):
        if key == s or key.startswith(s + "//") or (s.endswith("//") and key.startswith(s)):
            return True
    return False
