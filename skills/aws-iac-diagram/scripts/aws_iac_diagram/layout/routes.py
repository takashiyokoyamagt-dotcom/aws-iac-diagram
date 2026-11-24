"""辺の出入りの辺（ポート）を決める（フェーズ 6。目視の採点 C6 で、draw.io の選ぶ経路が検査の 4 通りと違い、線がアイコンを横切っていたため）。

4 通りの形（hv = 横 → 縦、vh = 縦 → 横、hh = 横 → 縦 → 横、vv = 縦 → 横 → 縦）のうち、ほかのノードの矩形を通らないものを選び、
draw.io には `exitX`・`exitY`・`entryX`・`entryY` で出入りの辺を指定する。経路の折れ目は置かない（waypoint は使わない。失敗知見 5）。
draw.io の `orthogonalEdgeStyle` は、出入りの辺が決まると、この形の経路を引く（Z 字の折れ目は中央）。
"""
from __future__ import annotations

from aws_iac_diagram.layout.grid import Layout

Rect = tuple[float, float, float, float]
Point = tuple[float, float]
SHAPES = ("hv", "vh", "hh", "vv")


def absolute(layout: Layout) -> dict[str, Rect]:
    out: dict[str, Rect] = {}

    def rect(i: str) -> Rect:
        if i not in out:
            p = layout.placed[i]
            ox, oy = (0, 0) if p.parent is None else rect(p.parent)[:2]
            out[i] = (ox + p.x, oy + p.y, ox + p.x + p.w, oy + p.y + p.h)
        return out[i]

    for i in layout.placed:
        rect(i)
    return out


def ports(src: Rect, dst: Rect, shape: str) -> tuple[tuple[float, float], tuple[float, float]]:
    """(exit の (x, y), entry の (x, y))。値は 0・0.5・1（矩形の中の割合）。"""
    sx, sy = (src[0] + src[2]) / 2, (src[1] + src[3]) / 2
    tx, ty = (dst[0] + dst[2]) / 2, (dst[1] + dst[3]) / 2
    right, down = tx >= sx, ty >= sy
    h_out = (1.0 if right else 0.0, 0.5)
    v_out = (0.5, 1.0 if down else 0.0)
    h_in = (0.0 if right else 1.0, 0.5)
    v_in = (0.5, 0.0 if down else 1.0)
    return {"hv": (h_out, v_in), "vh": (v_out, h_in), "hh": (h_out, h_in), "vv": (v_out, v_in)}[shape]


def point(r: Rect, f: tuple[float, float]) -> Point:
    return (r[0] + (r[2] - r[0]) * f[0], r[1] + (r[3] - r[1]) * f[1])


def path(src: Rect, dst: Rect, exit_: tuple[float, float], entry: tuple[float, float]) -> list[Point]:
    """出入りの辺から決まる経路（検査 validate/drawio.py と同じ定義）。"""
    p, q = point(src, exit_), point(dst, entry)
    first_h, last_h = exit_[1] == 0.5 and exit_[0] in (0.0, 1.0), entry[1] == 0.5 and entry[0] in (0.0, 1.0)
    if first_h and not last_h:
        return [p, (q[0], p[1]), q]
    if not first_h and last_h:
        return [p, (p[0], q[1]), q]
    if first_h:
        mx = (p[0] + q[0]) / 2
        return [p, (mx, p[1]), (mx, q[1]), q]
    my = (p[1] + q[1]) / 2
    return [p, (p[0], my), (q[0], my), q]


def layout_is_group(layout: Layout, kids: dict[str, list[str]], i: str) -> bool:
    return bool(kids.get(i))


def _midpoint(route: list[Point]) -> Point:
    lengths = [abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(route, route[1:])]
    rest = sum(lengths) / 2
    for (p, q), n in zip(zip(route, route[1:]), lengths):
        if rest <= n and n > 0:
            t = rest / n
            return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
        rest -= n
    return route[-1]


def _hits(a: Point, b: Point, r: Rect) -> bool:
    x1, x2 = sorted((a[0], b[0]))
    y1, y2 = sorted((a[1], b[1]))
    if x1 == x2:
        return r[0] < x1 < r[2] and y2 > r[1] and y1 < r[3]
    return r[1] < y1 < r[3] and x2 > r[0] and x1 < r[2]


def choose(layout: Layout, rects: dict[str, Rect], src: str, dst: str,
           soft: dict[str, Rect] | None = None, label: tuple[float, float] | None = None) -> tuple[tuple[float, float], tuple[float, float]]:
    """ほかのノードを通らない形のうち、ラベル（soft。ノード id → ラベルの矩形）を通らず、折れが少なく短いもの。"""
    def ancestors(i: str) -> set[str]:
        out, p = set(), layout.placed[i].parent
        while p is not None:
            out.add(p)
            p = layout.placed[p].parent
        return out
    kids: dict[str, list[str]] = {}
    for i, p in layout.placed.items():
        if p.parent is not None:
            kids.setdefault(p.parent, []).append(i)

    def descendants(i: str) -> set[str]:
        out, stack = set(), list(kids.get(i, []))
        while stack:
            c = stack.pop()
            out.add(c)
            stack.extend(kids.get(c, []))
        return out
    allowed = {src, dst} | ancestors(src) | ancestors(dst) | descendants(src) | descendants(dst)
    others = [rects[i] for i in sorted(rects) if i not in allowed]
    best = None
    for n, shape in enumerate(SHAPES):
        ex, en = ports(rects[src], rects[dst], shape)
        route = path(rects[src], rects[dst], ex, en)
        hits = sum(1 for r in others if any(_hits(a, b, r) for a, b in zip(route, route[1:])))
        length = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(route, route[1:]))
        soft_hits = sum(1 for i, r in sorted((soft or {}).items()) if i not in (src, dst)
                        and any(_hits(a, b, r) for a, b in zip(route, route[1:])))
        if label is not None:  # 辺のラベル（経路の中点）が、端も含めてアイコンに重ならないように
            m = _midpoint(route)
            box = (m[0] - label[0] / 2, m[1] - label[1] / 2, m[0] + label[0] / 2, m[1] + label[1] / 2)
            soft_hits += sum(1 for i, r in rects.items() if not layout_is_group(layout, kids, i)
                             and min(r[2], box[2]) > max(r[0], box[0]) and min(r[3], box[3]) > max(r[1], box[1]))
        key = (hits, soft_hits, len(set(route)), length, n)
        if best is None or key < best[0]:
            best = (key, ex, en)
    return best[1], best[2]
