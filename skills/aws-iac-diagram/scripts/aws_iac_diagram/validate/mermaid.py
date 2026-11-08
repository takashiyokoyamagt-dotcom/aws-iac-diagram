"""`.mmd` の検査（CRITERIA 2.3）: 同じビューのノード・辺と一致する。出力の文字列だけを読み、emit を import しない。"""
from __future__ import annotations

import re

_SUBGRAPH = re.compile(r'^\s*subgraph (n\d+)\["(.*)"\]$')
_NODE = re.compile(r'^\s*(n\d+)\["(.*)"\]$')
_EDGE = re.compile(r'^\s*(n\d+) (-->|-\.->)(?:\|"(.*)"\|)? (n\d+)$')


def _unescape(s: str) -> str:
    return s.replace("#quot;", '"').replace("#96;", "`").replace("#35;", "#")


def _plain(s: str) -> str:
    """改行にあたる文字は 1 つの空白に置き換えて出力するので、比べる側も同じにする。"""
    return re.sub(r"[\r\n\x0b\x0c\x85\u2028\u2029]", " ", s)


def check(text: str, nodes: list[dict], edges: list[dict]) -> list[str]:
    """問題の一覧（空なら合格）。"""
    ids = {nid: f"n{i}" for i, nid in enumerate(sorted(n["id"] for n in nodes))}
    lines = text.rstrip("\n").split("\n")
    if not lines or lines[0] != "flowchart LR":
        return ["先頭が flowchart LR でない"]
    got_nodes: dict[str, str] = {}
    got_edges: list[tuple[str, str, str, str]] = []
    stack: list[str] = []
    got_parent: dict[str, str | None] = {}
    problems: list[str] = []
    for line in lines[1:]:
        if line.strip() == "end":
            if stack:
                stack.pop()
            else:
                problems.append("end が多い")
        elif m := _SUBGRAPH.match(line):
            got_nodes[m[1]] = _unescape(m[2])
            got_parent[m[1]] = stack[-1] if stack else None
            stack.append(m[1])
        elif m := _NODE.match(line):
            got_nodes[m[1]] = _unescape(m[2])
            got_parent[m[1]] = stack[-1] if stack else None
        elif m := _EDGE.match(line):
            got_edges.append((m[1], m[2], _unescape(m[3] or ""), m[4]))
        else:
            problems.append(f"読めない行: {line}")
    if stack:
        problems.append("subgraph と end の数が合わない")
    want_nodes = {ids[n["id"]]: _plain(n["label"]) for n in nodes}
    if got_nodes != want_nodes:
        problems.append("ノードが同じビューと違う")
    elif got_parent != {ids[n["id"]]: ids.get(n["parent"]) for n in nodes}:
        problems.append("入れ子が同じビューと違う")
    want_edges = sorted((ids[e["from"]], "-.->" if e["confidence"] == "inferred" else "-->",
                         _plain(e.get("label") or ""), ids[e["to"]]) for e in edges)
    if sorted(got_edges) != want_edges:
        problems.append("辺が同じビューと違う")
    return problems
