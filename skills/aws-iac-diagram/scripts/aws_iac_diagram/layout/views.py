"""B2: 1 つの normalized IR から、全体図・ネットワーク図・詳細図のノードと辺を決め、40 を超えたら分割する。

- overview: 描くノードと辺のすべて（CRITERIA の 2.3）。
- network: 枠のすべてと、ネットワークの型のノード、その間の辺。
- detail: アプリの流れの図。ルート・ネットワークの辺を除き、中身の無い枠を除く。
分割は親の無いノードの部分木を単位に詰める。1 つの部分木が上限を超えるときは、その子を単位にする。
シートをまたぐ辺は `from` のあるシートに置き、`to` のノードを（祖先の枠ごと）そのシートに複製する。
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_ICONS = 40
RESERVE = 8  # 辺の相手を複製する分の余裕
NETWORK_TYPES = frozenset({"internet_gateway", "nat_gateway", "vpc_endpoint", "alb", "external"})  # 規則表の types/network.toml の枠以外
APP_HIDDEN_KINDS = frozenset({"route", "network"})


@dataclass
class View:
    name: str  # overview／network／detail、分割のときは overview-1 など
    nodes: list[dict]
    edges: list[dict]


def icon_count(nodes: list[dict]) -> int:
    return sum(1 for n in nodes if n["category"] != "group" and n["type"] != "external")


def _with_ancestors(ids: set[str], by_id: dict[str, dict]) -> set[str]:
    out = set(ids)
    for i in ids:
        p = by_id[i]["parent"]
        while p is not None and p not in out:
            out.add(p)
            p = by_id[p]["parent"]
    return out


def _subtree(root: str, kids: dict[str, list[str]]) -> list[str]:
    out, stack = [], [root]
    while stack:
        i = stack.pop()
        out.append(i)
        stack.extend(kids.get(i, []))
    return sorted(out)


def _units(ids: list[str], by_id: dict[str, dict], kids: dict[str, list[str]], limit: int) -> list[list[str]]:
    out: list[list[str]] = []
    for i in sorted(ids):
        tree = _subtree(i, kids)
        if icon_count([by_id[x] for x in tree]) <= limit or not kids.get(i):
            out.append(tree)
        else:
            out.extend(_units(kids[i], by_id, kids, limit))
    return out


def split(view: View) -> list[View]:
    if icon_count(view.nodes) <= MAX_ICONS:
        return [view]
    by_id = {n["id"]: n for n in view.nodes}
    kids: dict[str, list[str]] = {}
    for n in view.nodes:
        if n["parent"] is not None:
            kids.setdefault(n["parent"], []).append(n["id"])
    limit = MAX_ICONS - RESERVE
    sheets: list[set[str]] = []
    count = 0
    for unit in _units([n["id"] for n in view.nodes if n["parent"] is None], by_id, kids, limit):
        c = icon_count([by_id[x] for x in unit])
        if not sheets or count + c > limit:
            sheets.append(set())
            count = 0
        sheets[-1] |= set(unit)
        count += c
    sheets = [_with_ancestors(s, by_id) for s in sheets]
    home = {}
    for i, s in enumerate(sheets):
        for nid in s:
            if by_id[nid]["category"] != "group":
                home.setdefault(nid, i)
    edges: list[list[dict]] = [[] for _ in sheets]
    for e in sorted(view.edges, key=lambda x: x["id"]):
        i = home.get(e["from"], next(k for k, s in enumerate(sheets) if e["from"] in s))
        sheets[i] |= _with_ancestors({e["from"], e["to"]}, by_id)
        edges[i].append(e)
    return [View(f"{view.name}-{i + 1}", [n for n in view.nodes if n["id"] in s], edges[i]) for i, s in enumerate(sheets)]


def build(ir: dict) -> list[View]:
    by_id = {n["id"]: n for n in ir["nodes"]}
    groups = {n["id"] for n in ir["nodes"] if n["category"] == "group"}

    net_ids = _with_ancestors(groups | {n["id"] for n in ir["nodes"] if n["type"] in NETWORK_TYPES}, by_id)
    network = View("network", [n for n in ir["nodes"] if n["id"] in net_ids],
                   [e for e in ir["edges"] if e["from"] in net_ids and e["to"] in net_ids])

    app_edges = [e for e in ir["edges"] if e["kind"] not in APP_HIDDEN_KINDS]
    leaves = {n["id"] for n in ir["nodes"] if n["category"] != "group"}
    ends = {x for e in app_edges for x in (e["from"], e["to"])}
    app_ids = _with_ancestors(leaves | (ends & groups), by_id)
    detail = View("detail", [n for n in ir["nodes"] if n["id"] in app_ids], app_edges)

    views = [View("overview", list(ir["nodes"]), list(ir["edges"])), network, detail]
    return [sheet for v in views for sheet in split(v)]
