"""モジュールの呼び出しの扱いの決め方: source と version に合う要約表の選択、展開しないレジストリモジュールの扱い（黒箱）。

ir-schema.md の 7.2「TF のモジュール」。要約表の読み込みは summaries.py、source の見分けは sources.py。
"""
from __future__ import annotations

import re
from pathlib import Path

from aws_iac_diagram.adapters.terraform.modules.sources import registry_key
from aws_iac_diagram.adapters.terraform.modules.summaries import iam_only, load

_CONSTRAINT = re.compile(r"^\s*(~>|>=|<=|!=|=|>|<)?\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+][0-9A-Za-z.-]+)?\s*$")


def blackbox_plan(source: str, why: str) -> tuple:
    """要約表で展開しないレジストリモジュールの扱い。("blackbox", level, code, 理由)。

    要約表のファイル自体が無い・読めない（取り込みの不備）ときは、「表に無い」(info) とは別の warn にする。"""
    if registry_key(source) and not load()[0]:
        return ("blackbox", "warn", "TF-MODULE-SUMMARY-TABLE-MISSING",
                f"module {source} is not read: the summary table (references/module-summaries.md) is missing or empty")
    iam = " (it makes IAM resources only: H-IAM)" if iam_only(source) else ""
    return ("blackbox", "info", "TF-MODULE-BLACKBOX", f"module {source} is not read: {why}{iam}")


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
