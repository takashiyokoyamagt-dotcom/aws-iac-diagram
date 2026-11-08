"""`.drawio` の見やすさの検査（CRITERIA の 2.1 の近似モデル）。出力の XML だけを読み、配置のコードに依らない。

判定するもの: 重なり（overlap）、はみ出し（overflow）、貫通（pierce）、ラベルの重なり（label）。
座標はすべて絶対座標にしてから比べる。経路は L 字 2 通りと Z 字 2 通りで、**4 通りのすべてで問題が出るときだけ**誤りにする
（draw.io がどれかを選べるため）。背景のレイヤ（`BACKGROUND_LAYER`）のセルは対象外。
"""
from __future__ import annotations

import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

BACKGROUND_LAYER = "layer-background"
DEFAULT_FONT_SIZE = 12
LINE_HEIGHT = 1.2
FULL_WIDTH = 1.0
HALF_WIDTH = 0.6

Point = tuple[float, float]
Rect = tuple[float, float, float, float]  # 左, 上, 右, 下


@dataclass
class Vertex:
    id: str
    rect: Rect
    parent: str | None  # 親のノードの id（レイヤの直下なら None）
    label: str
    font_size: int
    children: list[str] = field(default_factory=list)

    @property
    def is_container(self) -> bool:
        return bool(self.children)


@dataclass
class Edge:
    id: str
    source: str
    target: str
    label: str
    font_size: int


@dataclass
class Diagram:
    vertices: dict[str, Vertex]
    edges: list[Edge]


@dataclass(frozen=True, order=True)
class Problem:
    kind: str
    subject: str
    other: str = ""


def _style(s: str) -> dict[str, str]:
    return dict((kv.split("=", 1) + [""])[:2] for kv in s.split(";") if kv)


def _font(style: dict[str, str]) -> int:
    v = style.get("fontSize", "")
    return int(v) if v.isdigit() else DEFAULT_FONT_SIZE


def parse(xml_text: str) -> Diagram:
    """最初の diagram を読む。親をたどって絶対座標にする。"""
    root = ET.fromstring(xml_text)
    cells = {c.get("id"): c for c in root.iter("mxCell")}

    def is_vertex(c: ET.Element) -> bool:
        return c.get("vertex") == "1"

    def in_background(c: ET.Element) -> bool:
        while c is not None:
            if c.get("id") == BACKGROUND_LAYER:
                return True
            c = cells.get(c.get("parent"))
        return False

    def absolute(c: ET.Element) -> tuple[float, float]:
        x = y = 0.0
        while c is not None and is_vertex(c):
            g = c.find("mxGeometry")
            x += float(g.get("x", 0))
            y += float(g.get("y", 0))
            c = cells.get(c.get("parent"))
        return x, y

    vertices: dict[str, Vertex] = {}
    for cid, c in cells.items():
        if not is_vertex(c) or in_background(c):
            continue
        g = c.find("mxGeometry")
        x, y = absolute(c)
        parent = cells.get(c.get("parent"))
        vertices[cid] = Vertex(cid, (x, y, x + float(g.get("width", 0)), y + float(g.get("height", 0))),
                               c.get("parent") if parent is not None and is_vertex(parent) else None,
                               c.get("value", ""), _font(_style(c.get("style", ""))))
    for v in vertices.values():
        if v.parent in vertices:
            vertices[v.parent].children.append(v.id)
    edges = [Edge(cid, c.get("source", ""), c.get("target", ""), c.get("value", ""), _font(_style(c.get("style", ""))))
             for cid, c in cells.items() if c.get("edge") == "1"]
    return Diagram(vertices, edges)


def _area_overlap(a: Rect, b: Rect) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _ancestors(d: Diagram, vid: str) -> set[str]:
    out: set[str] = set()
    p = d.vertices[vid].parent
    while p is not None:
        out.add(p)
        p = d.vertices[p].parent
    return out


def _descendants(d: Diagram, vid: str) -> set[str]:
    out: set[str] = set()
    stack = list(d.vertices[vid].children)
    while stack:
        c = stack.pop()
        out.add(c)
        stack.extend(d.vertices[c].children)
    return out


def _center(r: Rect) -> Point:
    return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)


def endpoint(d: Diagram, vid: str, other: Point) -> Point:
    """アイコンは中心、枠は相手に最も近い辺の中点（CRITERIA の 2.1）。"""
    v = d.vertices[vid]
    if not v.is_container:
        return _center(v.rect)
    cx, cy = _center(v.rect)
    mids = [(v.rect[0], cy), (v.rect[2], cy), (cx, v.rect[1]), (cx, v.rect[3])]
    return min(mids, key=lambda m: ((m[0] - other[0]) ** 2 + (m[1] - other[1]) ** 2, m))


def routes(a: Point, b: Point) -> list[list[Point]]:
    """L 字の 2 通りと Z 字の 2 通り。"""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    return [[a, (b[0], a[1]), b], [a, (a[0], b[1]), b], [a, (mx, a[1]), (mx, b[1]), b], [a, (a[0], my), (b[0], my), b]]


def _segment_hits(p: Point, q: Point, r: Rect) -> bool:
    """軸に平行な線分が矩形の内部を通るか（境界に沿うだけなら通らない）。"""
    x1, x2 = sorted((p[0], q[0]))
    y1, y2 = sorted((p[1], q[1]))
    if x1 == x2:
        return r[0] < x1 < r[2] and y2 > r[1] and y1 < r[3]
    return r[1] < y1 < r[3] and x2 > r[0] and x1 < r[2]


def _route_hits(route: list[Point], r: Rect) -> bool:
    return any(_segment_hits(p, q, r) for p, q in zip(route, route[1:]))


def _midpoint(route: list[Point]) -> Point:
    lengths = [abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(route, route[1:])]
    rest = sum(lengths) / 2
    for (p, q), n in zip(zip(route, route[1:]), lengths):
        if rest <= n and n > 0:
            t = rest / n
            return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
        rest -= n
    return route[-1]


def _label_size(text: str, font: int) -> tuple[float, float]:
    lines = text.replace("<br>", "\n").split("\n")
    def width(s: str) -> float:
        return sum((FULL_WIDTH if unicodedata.east_asian_width(c) in "WFA" else HALF_WIDTH) * font for c in s)
    return max(width(s) for s in lines), len(lines) * font * LINE_HEIGHT


def node_label_rect(v: Vertex) -> Rect | None:
    """アイコンの真下の中央。枠のラベルは枠の中に描くので対象外。"""
    if v.is_container or not v.label:
        return None
    w, h = _label_size(v.label, v.font_size)
    cx = (v.rect[0] + v.rect[2]) / 2
    return (cx - w / 2, v.rect[3], cx + w / 2, v.rect[3] + h)


def edge_routes(d: Diagram, e: Edge) -> list[list[Point]]:
    sc, tc = _center(d.vertices[e.source].rect), _center(d.vertices[e.target].rect)
    return routes(endpoint(d, e.source, tc), endpoint(d, e.target, sc))


def _edge_label_rects(d: Diagram, e: Edge) -> list[Rect]:
    if not e.label:
        return []
    w, h = _label_size(e.label, e.font_size)
    return [(m[0] - w / 2, m[1] - h / 2, m[0] + w / 2, m[1] + h / 2) for m in map(_midpoint, edge_routes(d, e))]


def check_overlap(d: Diagram) -> list[Problem]:
    ids = sorted(d.vertices)
    out = []
    for i, a in enumerate(ids):
        anc = _ancestors(d, a)
        for b in ids[i + 1:]:
            if b not in anc and a not in _ancestors(d, b) and _area_overlap(d.vertices[a].rect, d.vertices[b].rect):
                out.append(Problem("overlap", a, b))
    return out


def check_overflow(d: Diagram) -> list[Problem]:
    out = []
    for v in d.vertices.values():
        if v.parent in d.vertices:
            p = d.vertices[v.parent].rect
            if v.rect[0] < p[0] or v.rect[1] < p[1] or v.rect[2] > p[2] or v.rect[3] > p[3]:
                out.append(Problem("overflow", v.id, v.parent))
    return sorted(out)


def piercing_vertices(d: Diagram, e: Edge) -> list[str]:
    """4 通りのすべてが何かを貫通するとき、最初の経路が貫通するノードを返す（1 通りでも通れるなら空）。"""
    allowed = {e.source, e.target} | _ancestors(d, e.source) | _ancestors(d, e.target)
    for end in (e.source, e.target):
        if d.vertices[end].is_container:
            allowed |= _descendants(d, end)
    others = [v for v in sorted(d.vertices) if v not in allowed]
    hits = [[v for v in others if _route_hits(r, d.vertices[v].rect)] for r in edge_routes(d, e)]
    return hits[0] if all(hits) else []


def check_pierce(d: Diagram) -> list[Problem]:
    return sorted(Problem("pierce", e.id, ",".join(hit)) for e in d.edges if (hit := piercing_vertices(d, e)))


def check_labels(d: Diagram) -> list[Problem]:
    out: list[Problem] = []
    node_rects = {v.id: r for v in d.vertices.values() if (r := node_label_rect(v)) is not None}
    icons = {v.id: v.rect for v in d.vertices.values() if not v.is_container}
    fixed = [(f"label:{i}", r) for i, r in sorted(node_rects.items())] + [(f"icon:{i}", r) for i, r in sorted(icons.items())]
    for i, (a, ra) in enumerate(fixed):
        for b, rb in fixed[i + 1:]:
            if a.split(":", 1)[1] != b.split(":", 1)[1] and "label" in a + b and _area_overlap(ra, rb):
                out.append(Problem("label", a, b))
    placed = [(e, _edge_label_rects(d, e)) for e in sorted(d.edges, key=lambda x: x.id)]
    placed = [(e, rs) for e, rs in placed if rs]
    for e, rs in placed:
        for name, r in fixed:
            if all(_area_overlap(x, r) for x in rs):
                out.append(Problem("label", f"edge:{e.id}", name))
    for i, (e, rs) in enumerate(placed):
        for f, qs in placed[i + 1:]:
            if all(_area_overlap(x, y) for x in rs for y in qs):
                out.append(Problem("label", f"edge:{e.id}", f"edge:{f.id}"))
    return out


def check(xml_text: str) -> list[Problem]:
    """すべての検査。空なら合格。L4 の貫通の割合は呼ぶ側が `kind == "pierce"` を数える。"""
    d = parse(xml_text)
    return check_overlap(d) + check_overflow(d) + check_pierce(d) + check_labels(d)


def _crossings(a: list[Point], b: list[Point]) -> int:
    n = 0
    for p, q in zip(a, a[1:]):
        for r, s in zip(b, b[1:]):
            if (p[0] == q[0]) != (r[0] == s[0]):  # 縦と横の組だけ数える
                v, h = ((p, q), (r, s)) if p[0] == q[0] else ((r, s), (p, q))
                x, y = v[0][0], h[0][1]
                if min(h[0][0], h[1][0]) < x < max(h[0][0], h[1][0]) and min(v[0][1], v[1][1]) < y < max(v[0][1], v[1][1]):
                    n += 1
    return n


def _length(r: list[Point]) -> float:
    return sum(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(r, r[1:]))


def score(xml_text: str) -> int:
    """配置の候補のスコア（小さいほど良い）。重なり・はみ出し > 貫通 > ラベル > 交差 > 折れ > 総延長 > 縦横比。"""
    d = parse(xml_text)
    best_routes = [min(edge_routes(d, e), key=lambda r: (len(set(r)), _length(r))) for e in d.edges]
    crossings = sum(_crossings(a, b) for i, a in enumerate(best_routes) for b in best_routes[i + 1:])
    bends = sum(len(set(r)) - 2 for r in best_routes)
    length = sum(_length(r) for r in best_routes)
    xs = [v.rect[2] for v in d.vertices.values()] or [1]
    ys = [v.rect[3] for v in d.vertices.values()] or [1]
    aspect = abs(max(xs) / max(max(ys), 1) - 16 / 9)
    bad = len(check_overlap(d)) + len(check_overflow(d))
    return (bad * 100000 + len(check_pierce(d)) * 10000 + len(check_labels(d)) * 1000 + crossings * 100 + bends * 10
            + int(length / 10) + int(aspect * 10))
