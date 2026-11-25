"""B2: 1 つの normalized IR から、全体図・ネットワーク図・詳細図のノードと辺を決め、40 を超えたら分割する。

- overview: 描くノードと辺のすべて（CRITERIA の 2.3）。
- network: 枠のすべてと、ネットワークの型のノード、その間の辺。
- detail: アプリの流れの図。ルート・ネットワークの辺を除き、中身の無い枠を除く。
分割は親の無いノードの部分木を単位に詰める。1 つの部分木が上限を超えるときは、その子を単位にする。
シートをまたぐ辺は `from` のあるシートに置き、`to` のノードを（祖先の枠ごと）そのシートに複製する。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_ICONS = 40
RESERVE = 8  # 辺の相手を複製する分の余裕
NETWORK_TYPES = frozenset({"internet_gateway", "nat_gateway", "vpc_endpoint", "alb", "external", "egress_only_internet_gateway",
                           "transit_gateway", "network_firewall", "route53_resolver_endpoint"})  # 規則表の types/network.toml の枠以外
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


def split_by_root(view: View) -> list[View]:
    """親の無い枠ごとに 1 枚にする。親の無いアイコンは 1 枚にまとめる（枠が 1 つでも、親の無いアイコンがあれば、枠と
    アイコンの 2 枚に分ける。T17 の VPC と CI/CD）。1 枚にしかならないなら分けない。貫通が残る図の最後の手。"""
    by_id = {n["id"]: n for n in view.nodes}
    kids: dict[str, list[str]] = {}
    for n in view.nodes:
        if n["parent"] is not None:
            kids.setdefault(n["parent"], []).append(n["id"])
    roots = sorted(n["id"] for n in view.nodes if n["parent"] is None and n["category"] == "group")
    rest = {n["id"] for n in view.nodes if n["parent"] is None and n["category"] != "group"}
    if len(roots) + (1 if rest else 0) < 2:
        return [view]
    sheets = [set(_subtree(r, kids)) for r in roots]
    if rest:
        sheets.append(rest)
    return _assemble(view, sheets, by_id)


def _assemble(view: View, sheets: list[set[str]], by_id: dict[str, dict]) -> list[View]:
    home: dict[str, int] = {}
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
    return _assemble(view, sheets, by_id)


def distinct_labels(nodes: list[dict]) -> list[dict]:
    """同じ名前のノードが 2 つ以上あれば、名前の後に型を添える（C6 の指摘。SNS と SQS がどちらも shop-order-events など）。
    IR の label は変えず、図に描く名前だけを変える（.drawio と .mmd は同じ名前になる）。"""
    count: dict[str, int] = {}
    for n in nodes:
        count[n["label"]] = count.get(n["label"], 0) + 1
    return [n if count[n["label"]] < 2 else {**n, "label": f"{n['label']} ({n['type']})"} for n in nodes]


# サブネットの名前の、AZ を表す末尾（`-eu-west-2a`・`-ap-northeast-1c`・`-az2a`・`_az1`）。これを除いた名前が同じなら同じ役割
_AZ_SUFFIX = re.compile(r"[-_.]?(?:[a-z]{2}(?:-[a-z]+)+-\d[a-z]|az\d*[a-z]?)$")


def _role(n: dict) -> str:
    return _AZ_SUFFIX.sub("", n["label"])


def bundle_az(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """AZ ごとに同じ役割のサブネット（名前から AZ の部分を除くと同じ）から、AZ の外の同じノードへ、同じ kind・ラベル・確信度で
    出る辺を、図の上で 1 本にまとめる（network-hub の 3 AZ のルート。2026-11-25）。残す辺は名前の順で最初のサブネットのもので、
    ラベルに `（3 AZ）` を添える。2 つ以上の AZ にそろって出るときだけまとめる。IR の辺は変えない（図に描く辺だけ）。"""
    by_id = {n["id"]: n for n in nodes}

    def az_of(nid: str) -> str | None:
        p = by_id[nid]["parent"]
        while p is not None:
            if by_id[p]["type"] == "availability_zone":
                return p
            p = by_id[p]["parent"]
        return None

    groups: dict[tuple, list[dict]] = {}
    for e in edges:
        src = by_id.get(e["from"])
        if src is None or src["type"] != "subnet" or e["to"] not in by_id:
            continue
        az = az_of(e["from"])
        if az is None or az_of(e["to"]) is not None:
            continue
        key = (by_id[az]["parent"], _role(src), e["to"], e["kind"], e["label"], e["confidence"])
        groups.setdefault(key, []).append(e)
    drop: set[str] = set()
    keep_as: dict[str, dict] = {}
    for es in groups.values():
        azs = {az_of(e["from"]) for e in es}
        if len(azs) < 2 or len(azs) != len(es):
            continue  # 1 つの AZ に同じ役割が 2 つある（名前から役割が決まらない）なら、まとめない
        keep, *rest = sorted(es, key=lambda x: x["from"])
        drop |= {e["id"] for e in rest}
        label = f"{keep['label']}（{len(azs)} AZ）" if keep["label"] else f"（{len(azs)} AZ）"
        keep_as[keep["id"]] = {"label": label, "bundled": sorted(e["id"] for e in rest)}
    return [{**e, **keep_as[e["id"]]} if e["id"] in keep_as else e for e in edges if e["id"] not in drop]


def build(ir: dict) -> list[View]:
    ir = {**ir, "nodes": distinct_labels(ir["nodes"])}
    ir = {**ir, "edges": bundle_az(ir["nodes"], ir["edges"])}
    by_id = {n["id"]: n for n in ir["nodes"]}
    groups = {n["id"] for n in ir["nodes"] if n["category"] == "group"}

    net_ids = _with_ancestors(groups | {n["id"] for n in ir["nodes"] if n["type"] in NETWORK_TYPES}, by_id)
    network = View("network", [n for n in ir["nodes"] if n["id"] in net_ids],
                   [e for e in ir["edges"] if e["from"] in net_ids and e["to"] in net_ids])

    app_edges = [e for e in ir["edges"] if e["kind"] not in APP_HIDDEN_KINDS]
    ends = {x for e in app_edges for x in (e["from"], e["to"])}
    app_ids = _with_ancestors(ends, by_id)  # 詳細図は流れの図なので、辺の無いノードは出さない（C6 の指摘。全体図には出る）
    detail = View("detail", [n for n in ir["nodes"] if n["id"] in app_ids], app_edges)

    overview = View("overview", list(ir["nodes"]), list(ir["edges"]))
    views = [overview]
    if groups:  # 枠が無ければネットワーク図は空に近いので出さない（C6 の指摘）
        views.append(network)
    if app_edges and ({n["id"] for n in detail.nodes}, {e["id"] for e in detail.edges}) != ({n["id"] for n in ir["nodes"]}, {e["id"] for e in ir["edges"]}):
        views.append(detail)  # 流れの辺が無いか、全体図と同じなら出さない
    return [sheet for v in views for sheet in split(v)]
