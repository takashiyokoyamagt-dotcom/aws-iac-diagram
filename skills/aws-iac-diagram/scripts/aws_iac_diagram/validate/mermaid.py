"""`.mmd` の検査（CRITERIA 2.3）: 同じビューのノード・辺と一致する。出力の文字列だけを読み、emit を import しない。"""
from __future__ import annotations

import re

_SUBGRAPH = re.compile(r'^\s*subgraph (n\d+)\["(.*)"\]$')
_NODE = re.compile(r'^\s*(n\d+)\["(.*)"\]$')
_EDGE = re.compile(r'^\s*(n\d+) (-->|-\.->)(?:\|"(.*)"\|)? (n\d+)$')


def _unescape(s: str) -> str:
    return s.replace("#quot;", '"').replace("#35;", "#")


def check(text: str, nodes: list[dict], edges: list[dict]) -> list[str]:
    """問題の一覧（空なら合格）。"""
    ids = {nid: f"n{i}" for i, nid in enumerate(sorted(n["id"] for n in nodes))}
    lines = text.splitlines()
    if not lines or lines[0] != "flowchart LR":
        return ["先頭が flowchart LR でない"]
    got_nodes: dict[str, str] = {}
    got_edges: list[tuple[str, str, str, str]] = []
    depth = 0
    problems: list[str] = []
    for line in lines[1:]:
        if line.strip() == "end":
            depth -= 1
        elif m := _SUBGRAPH.match(line):
            depth += 1
            got_nodes[m[1]] = _unescape(m[2])
        elif m := _NODE.match(line):
            got_nodes[m[1]] = _unescape(m[2])
        elif m := _EDGE.match(line):
            got_edges.append((m[1], m[2], _unescape(m[3] or ""), m[4]))
        else:
            problems.append(f"読めない行: {line}")
    if depth != 0:
        problems.append("subgraph と end の数が合わない")
    want_nodes = {ids[n["id"]]: n["label"].replace("\n", " ") for n in nodes}
    if got_nodes != want_nodes:
        problems.append("ノードが同じビューと違う")
    want_edges = sorted((ids[e["from"]], "-.->" if e["confidence"] == "inferred" else "-->",
                         (e.get("label") or "").replace("\n", " "), ids[e["to"]]) for e in edges)
    if sorted(got_edges) != want_edges:
        problems.append("辺が同じビューと違う")
    return problems
