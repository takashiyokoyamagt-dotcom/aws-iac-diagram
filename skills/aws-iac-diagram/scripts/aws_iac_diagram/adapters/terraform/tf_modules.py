"""Terraform のモジュールの source の見分けと、A5 の要約表（references/module-summaries.md）の読み込み。

scripts/adapters/tf.py（モジュールの展開）と、フェーズ3 の正規化（IAM だけのモジュールの H-IAM）が使う。

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

# SKILL のフォルダ（このファイルの 4 つ上: terraform → adapters → aws_iac_diagram → scripts → SKILL）。R4 で data/ に移す
SUMMARY_FILE = Path(__file__).resolve().parents[4] / "references" / "module-summaries.md"

_MARK = re.compile(r'<!--\s*module-summary\s+source="([^"]+)"\s+majors="([0-9, ]+)"\s*-->')
_IAM_MARK = re.compile(r"<!--\s*iam-only-sources\s*-->")
_FENCE = re.compile(r"^```[a-z]*\s*$")
_REGISTRY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_-]*$")
_CONSTRAINT = re.compile(r"^\s*(~>|>=|<=|!=|=|>|<)?\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+][0-9A-Za-z.-]+)?\s*$")


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


# ------------------------------------------------------------------ source の見分け

def is_local(source: str) -> bool:
    """ローカルのパス（./・../ で始まる。Terraform と同じ）か。"""
    return source.startswith(("./", "../")) or source in (".", "..")


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


def join_summary_source(parent: str, local: str) -> str | None:
    """要約表の中の module ブロックのローカルの source（"./modules/x"）を、要約表の source にする。"""
    base, _, sub = parent.partition("//")
    parts = [p for p in sub.split("/") if p]
    for p in local.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(p)
    return base + ("//" + "/".join(parts) if parts else "")


def iam_only(source: str, path: Path | None = None) -> bool:
    """IAM のリソースだけを作るモジュールか（正規化の H-IAM。ir-schema.md の 2章）。"""
    key = registry_key(source)
    if key is None:
        return False
    for s in load(path)[1]:
        if key == s or key.startswith(s + "//") or (s.endswith("//") and key.startswith(s)):
            return True
    return False


# ------------------------------------------------------------------ 版の選び方

def _bounds(constraint: str):
    """版の制約を、使える major の (下限, 上限（含まない）) にする。読めなければ None。

    "6.7.3"・"= 6.7.3"・"~> 6.7"・"~> 6" は major 6 だけ。">= 5.0" は 5 以上、"< 7.0" は 7 未満、"<= 7.1" は 7 以下。
    """
    lo, hi = 0, None
    for part in constraint.split(","):
        if not part.strip():
            continue
        m = _CONSTRAINT.match(part)
        if not m:
            return None
        op, major = m.group(1) or "=", int(m.group(2))
        rest_zero = not any(int(x) for x in (m.group(3) or "0", m.group(4) or "0"))
        if op in ("=", "~>"):
            lo, hi = max(lo, major), major + 1 if hi is None else min(hi, major + 1)
        elif op in (">=", ">"):
            lo = max(lo, major)
        elif op == "<":
            top = major if rest_zero else major + 1
            hi = top if hi is None else min(hi, top)
        elif op == "<=":
            hi = major + 1 if hi is None else min(hi, major + 1)
        # != は major を決めない
    return lo, hi


def choose(source: str, version: str | None, path: Path | None = None):
    """source と version に合う要約表を選ぶ。(Summary か None, 理由, 前提)。

    要約表に無い・版が合わないときは None と、診断に書く理由。版の指定が無い・上限が無いときは、
    要約表の中で最も新しい major を使い、そのことを前提（evaluation.assumptions）に書く。
    """
    key = registry_key(source)
    cands = load(path)[0].get(key or "", [])
    if not cands:
        return None, "not in the summary table (references/module-summaries.md)", None
    majors = sorted({mj for s in cands for mj in s.majors})
    if version is None:
        pick = majors[-1]
        note = f"version is not pinned; the summary for {pick}.x is used"
    else:
        b = _bounds(version)
        if b is None:
            return None, f"version constraint {version!r} cannot be read", None
        lo, hi = b
        ok = [mj for mj in majors if mj >= lo and (hi is None or mj < hi)]
        if not ok:
            have = ", ".join(f"{mj}.x" for mj in majors)
            return None, f"version {version} is not in the summary table (it has {have})", None
        pick = ok[-1]
        if hi is None:
            note = f"version {version} has no upper major; the summary for {pick}.x is used"
        elif hi - lo > 1:
            note = f"version {version} allows majors {lo} to {hi - 1}; the summary for {pick}.x is used"
        else:
            note = None
    summary = next(s for s in cands if pick in s.majors)
    return summary, "", note
