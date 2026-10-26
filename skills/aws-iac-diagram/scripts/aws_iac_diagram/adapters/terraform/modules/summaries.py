"""A5 の要約表（data/module-summaries/）の読み込みと、IAM だけを作るモジュールの見分け。

モジュールの展開（module_expand.py）と、フェーズ3 の正規化（IAM だけのモジュールの H-IAM）が使う。

要約表は `data/module-summaries/<モジュール>/v<メジャー>.md`（1 モジュールの 1 major につき 1 ファイル。サブモジュールの
表は親と同じファイルに入れる）。Markdown の中の HCL のコードブロックで、直前の行に
  <!-- module-summary source="terraform-aws-modules/vpc/aws" majors="6" -->
と書く（source はレジストリの source。サブモジュールは "//modules/x" を付ける。majors は対象の版の major）。
中身は、本物のモジュールの主要なリソース（count・for_each の条件と、名前・参照の属性）と出力だけを
同じ書き方で写したもの。アダプタは、手元のモジュールと同じように評価する（ir-schema.md の 7.2）。
コードブロックの中の "# not-covered: a, b" の行に書いた変数（要約表に写していないリソースを作る入力）は、
呼び出しで渡されたら、宣言の無い入力と同じく診断（TF-MODULE-SUMMARY-INPUT）に書く。

IAM だけを作るモジュールの source は、`data/module-summaries/iam-only-sources.md` の
  <!-- iam-only-sources -->
の直後のコードブロックに1行に1つ書く（サブモジュール "//…" も含む）。

ディレクトリの下の .md をすべて読む。順序は決まっている（パスの文字と数を分けて比べる。v6 は v10 の前）ので、
同じ source の表が複数あっても、選ばれる表は読む場所に依らない。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from aws_iac_diagram.adapters.terraform.modules.sources import registry_key
from aws_iac_diagram.core.paths import MODULE_SUMMARIES_DIR

# 要約表のディレクトリ（テストは、無い場所や空の場所に差し替えて、表が無いときの扱いを確かめる）
SUMMARY_DIR = MODULE_SUMMARIES_DIR

_MARK = re.compile(r'<!--\s*module-summary\s+source="([^"]+)"\s+majors="([0-9, ]+)"\s*-->')
_IAM_MARK = re.compile(r"<!--\s*iam-only-sources\s*-->")
_FENCE = re.compile(r"^```[a-z]*\s*$")
_DIGITS = re.compile(r"(\d+)")


@dataclass(frozen=True)
class Summary:
    source: str  # 要約表の source（レジストリの source。サブモジュールは //modules/x 付き）
    majors: tuple  # 対象の版の major
    text: str  # HCL
    line: int  # file の中の行（1 始まり。コードブロックの最初の行）
    uncovered: tuple = ()  # 要約表に写していないリソースを作る入力（# not-covered: の行）
    file: str = ""  # 読んだファイル（SUMMARY_DIR からの相対パス。/ 区切り）


_CACHE: dict = {}


def _fenced_after(lines: list[str], i: int) -> tuple[str, int] | None:
    """lines[i] の後ろの最初のコードブロックの中身と、その最初の行の番号（0 始まり）。"""
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines) or not _FENCE.match(lines[j].strip()):
        return None
    k = j + 1
    while k < len(lines) and lines[k].strip() != "```":
        k += 1
    return "\n".join(lines[j + 1:k]) + "\n", j + 1


def _order(rel: str) -> list:
    """パスの並べ方: 文字と数を分けて比べる（v6 は v10 の前。OS やロケールに依らない）。"""
    return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in _DIGITS.split(rel)]


def _files(path: Path) -> list[tuple[str, Path]]:
    """読むファイル（相対パスと実体）を決まった順序で。path がファイルならそれ 1 つ。無い・読めなければ空。"""
    try:
        if path.is_file():
            return [(path.name, path)]
        if not path.is_dir():
            return []
        found = [(p.relative_to(path).as_posix(), p) for p in path.rglob("*.md") if p.is_file()]
    except OSError:
        return []
    return sorted(found, key=lambda x: _order(x[0]))


def _read(f: Path, rel: str, summaries: dict, iam: list) -> None:
    try:
        lines = f.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    except OSError:
        return
    for i, line in enumerate(lines):
        m = _MARK.search(line)
        if m:
            got = _fenced_after(lines, i)
            if got is not None:
                majors = tuple(sorted({int(x) for x in m.group(2).replace(" ", "").split(",") if x}))
                uncovered = tuple(sorted({x.strip() for ln in got[0].splitlines()
                                          if ln.strip().startswith("# not-covered:")
                                          for x in ln.split(":", 1)[1].split(",") if x.strip()}))
                summaries.setdefault(m.group(1), []).append(Summary(m.group(1), majors, got[0], got[1] + 1,
                                                                    uncovered, rel))
        elif _IAM_MARK.search(line):
            got = _fenced_after(lines, i)
            if got is not None:
                iam += [x.strip() for x in got[0].splitlines() if x.strip() and not x.strip().startswith("#")]


def load(path: Path | None = None) -> tuple[dict, tuple]:
    """要約表を読む。({source: [Summary]}, IAM だけのモジュールの source の並び)。読めなければ空。

    path は要約表のディレクトリ（省略すると SUMMARY_DIR）。ファイルを渡すと、そのファイルだけを読む。"""
    path = path or SUMMARY_DIR
    key = str(path)
    if key in _CACHE:
        return _CACHE[key]
    summaries: dict = {}
    iam: list = []
    for rel, f in _files(path):
        _read(f, rel, summaries, iam)
    _CACHE[key] = (summaries, tuple(iam))
    return _CACHE[key]


def iam_only(source: str, path: Path | None = None) -> bool:
    """IAM のリソースだけを作るモジュールか（正規化の H-IAM。ir-schema.md の 2章）。"""
    key = registry_key(source)
    if key is None:
        return False
    for s in load(path)[1]:
        if key == s or key.startswith(s + "//") or (s.endswith("//") and key.startswith(s)):
            return True
    return False
