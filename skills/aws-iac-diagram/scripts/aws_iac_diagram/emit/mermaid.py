"""`.mmd`（flowchart＋入れ子の subgraph）。ノードの数によらず同じ形（PLAN の失敗知見 14・16・18・19）。

- ノードの id は n0, n1, …（ビューのノードの id の辞書順の番号。ARN を使わない。失敗知見 17）。
- 推定の辺は破線 `-.->`。ラベルは引用符の中に書き、`#`・`"` は文字参照にする。
- アイコンパックは使わない（同梱できず、GitHub では効かない）。
"""
from __future__ import annotations


def escape(text: str) -> str:
    return text.replace("#", "#35;").replace('"', "#quot;").replace("\r", " ").replace("\n", " ")


def node_ids(nodes: list[dict]) -> dict[str, str]:
    return {nid: f"n{i}" for i, nid in enumerate(sorted(n["id"] for n in nodes))}


def flowchart(nodes: list[dict], edges: list[dict]) -> str:
    ids = node_ids(nodes)
    kids: dict[str | None, list[dict]] = {}
    for n in nodes:
        kids.setdefault(n["parent"], []).append(n)
    lines = ["flowchart LR"]

    def walk(parent: str | None, depth: int) -> None:
        pad = "  " * depth
        for n in sorted(kids.get(parent, []), key=lambda x: x["id"]):
            if n["category"] == "group":
                lines.append(f'{pad}subgraph {ids[n["id"]]}["{escape(n["label"])}"]')
                walk(n["id"], depth + 1)
                lines.append(f"{pad}end")
            else:
                lines.append(f'{pad}{ids[n["id"]]}["{escape(n["label"])}"]')

    walk(None, 1)
    for e in sorted(edges, key=lambda x: x["id"]):
        arrow = "-.->" if e["confidence"] == "inferred" else "-->"
        label = f'|"{escape(e["label"])}"|' if e.get("label") else ""
        lines.append(f'  {ids[e["from"]]} {arrow}{label} {ids[e["to"]]}')
    return "\n".join(lines) + "\n"
