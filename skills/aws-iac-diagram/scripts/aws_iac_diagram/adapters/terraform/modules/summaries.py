"""A5 の要約表（references/module-summaries.md）の読み込みと、IAM だけを作るモジュールの見分け。

モジュールの展開（module_expand.py）と、フェーズ3 の正規化（IAM だけのモジュールの H-IAM）が使う。

要約表は Markdown の中の HCL のコードブロックで、直前の行に
  <!-- module-summary source="terraform-aws-modules/vpc/aws" majors="6" -->
と書く（source はレジストリの source。サブモジュールは "//modules/x" を付ける。majors は対象の版の major）。
中身は、本物のモジュールの主要なリソース（count・for_each の条件と、名前・参照の属性）と出力だけを
同じ書き方で写したもの。アダプタは、手元のモジュールと同じように評価する（ir-schema.md の 7.2）。
コードブロックの中の "# not-covered: a, b" の行に書いた変数（要約表に写していないリソースを作る入力）は、
呼び出しで渡されたら、宣言の無い入力と同じく診断（TF-MODULE-SUMMARY-INPUT）に書く。

IAM だけを作るモジュールの source は、
  <!-- iam-only-sources -->
の直後のコードブロックに1行に1つ書く（サブモジュール "//…" も含む）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from aws_iac_diagram.adapters.terraform.modules.sources import registry_key

# SKILL のフォルダ（このファイルの 5 つ上: modules → terraform → adapters → aws_iac_diagram → scripts → SKILL）。R4 で data/ に移す
SUMMARY_FILE = Path(__file__).resolve().parents[5] / "references" / "module-summaries.md"

_MARK = re.compile(r'<!--\s*module-summary\s+source="([^"]+)"\s+majors="([0-9, ]+)"\s*-->')
_IAM_MARK = re.compile(r"<!--\s*iam-only-sources\s*-->")
_FENCE = re.compile(r"^```[a-z]*\s*$")


@dataclass(frozen=True)
class Summary:
    source: str  # 要約表の source（レジストリの source。サブモジュールは //modules/x 付き）
    majors: tuple  # 対象の版の major
    text: str  # HCL
    line: int  # module-summaries.md の中の行（1 始まり。コードブロックの最初の行）
    uncovered: tuple = ()  # 要約表に写していないリソースを作る入力（# not-covered: の行）


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


def load(path: Path | None = None) -> tuple[dict, tuple]:
    """要約表を読む。({source: [Summary]}, IAM だけのモジュールの source の並び)。読めなければ空。"""
    path = path or SUMMARY_FILE
    key = str(path)
    if key in _CACHE:
        return _CACHE[key]
    summaries: dict = {}
    iam: list = []
    try:
        lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    except OSError:
        lines = []
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
                                                                    uncovered))
        elif _IAM_MARK.search(line):
            got = _fenced_after(lines, i)
            if got is not None:
                iam += [x.strip() for x in got[0].splitlines() if x.strip() and not x.strip().startswith("#")]
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
