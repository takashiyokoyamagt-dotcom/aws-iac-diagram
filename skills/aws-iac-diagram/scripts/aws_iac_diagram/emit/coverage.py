"""`coverage.md`（A6）: 入力の全リソースを、描いた・統合した・描かなかった・分からない、に分けた表。正本は IR の `sources`。"""
from __future__ import annotations

from collections import Counter

CLASS_NAMES = {"drawn": "描いた", "merged_into": "統合した", "hidden": "描かない", "unknown": "型が分からない（図に出ない）"}
ORDER = ("drawn", "merged_into", "hidden", "unknown")


def _cell(v: str) -> str:
    return v.replace("|", "\\|").replace("\n", " ")


def render(ir: dict) -> str:
    lines = [f"# 網羅の一覧: {ir['name']}", ""]
    for key in sorted(ir["sources"]):
        src = ir["sources"][key]
        rs = src.get("resources", [])
        c = Counter(r["class"] for r in rs)
        lines += [f"## {key}（{len(rs)} 件）", "", "| 分類 | 件数 |", "|---|---|"]
        lines += [f"| {CLASS_NAMES[k]} | {c.get(k, 0)} |" for k in ORDER]
        lines += ["", "| address | 型 | 分類 | 規則 | 統合先 |", "|---|---|---|---|---|"]
        for r in sorted(rs, key=lambda x: x["address"]):
            lines.append(f"| {_cell(r['address'])} | {_cell(r['type'])} | {r['class']} | {r.get('rule') or ''} | "
                         f"{_cell(', '.join(r.get('into') or []))} |")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
