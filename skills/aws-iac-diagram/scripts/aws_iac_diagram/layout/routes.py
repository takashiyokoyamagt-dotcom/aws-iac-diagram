"""辺の出入りの辺（ポート）を決める（フェーズ 6。目視の採点 C6 で、draw.io の選ぶ経路が検査の 4 通りと違い、線がアイコンを横切っていたため）。

4 通りの形（hv = 横 → 縦、vh = 縦 → 横、hh = 横 → 縦 → 横、vv = 縦 → 横 → 縦）のうち、ほかのノードの矩形を通らないものを選び、
draw.io には `exitX`・`exitY`・`entryX`・`entryY` で出入りの辺を指定する。経路の折れ目は置かない（waypoint は使わない。失敗知見 5）。
draw.io の `orthogonalEdgeStyle` は、出入りの辺が決まると、この形の経路を引く（Z 字の折れ目は中央）。
"""
from __future__ import annotations

import threading

from aws_iac_diagram.layout.grid import LABEL_H, Layout

LABEL_GAP = LABEL_H + 5 # アイコンの下から出入りする線は、名前（真下のラベル）の下から始める（exitDy・entryDy）

Rect = tuple[float, float, float, float]
Point = tuple[float, float]
SHAPES = ("hv", "vh", "hh", "vv")
SOFT_MARGIN = 6  # 線が名前のすぐそばを通らないように（C6 の指摘。検査より広く避ける）


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


def path(src: Rect, dst: Rect, exit_: tuple[float, float], entry: tuple[float, float], sdy: float = 0, tdy: float = 0) -> list[Point]:
    """出入りの辺から決まる経路（検査 validate/drawio.py と同じ定義）。"""
    p, q = point(src, exit_), point(dst, entry)
    p, q = (p[0], p[1] + sdy), (q[0], q[1] + tdy)
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


_LOCAL = threading.local()  # 下ごしらえはスレッドごと（並列で呼ばれても混ざらない）


def _context(layout: Layout, rects: dict[str, Rect], soft: dict[str, Rect] | None) -> dict:
    """配置ごとの下ごしらえ（直前の配置の分だけ覚える。結果は覚えない計算と同じ）。"""
    key = (id(layout), id(rects), id(soft))
    ctx = getattr(_LOCAL, "ctx", None)
    if ctx is not None and ctx["key"] == key and ctx["refs"][0] is layout and ctx["refs"][1] is rects and ctx["refs"][2] is soft:
        return ctx
    kids: dict[str, list[str]] = {}
    for i, p in layout.placed.items():
        if p.parent is not None:
            kids.setdefault(p.parent, []).append(i)
    ancestors: dict[str, set[str]] = {}
    for i in layout.placed:
        out, p = set(), layout.placed[i].parent
        while p is not None:
            out.add(p)
            p = layout.placed[p].parent
        ancestors[i] = out
    descendants: dict[str, set[str]] = {}
    for i in layout.placed:
        out, stack = set(), list(kids.get(i, []))
        while stack:
            c = stack.pop()
            out.add(c)
            stack.extend(kids.get(c, []))
        descendants[i] = out
    m = SOFT_MARGIN
    ctx = dict(key=key, kids=kids, ancestors=ancestors, descendants=descendants,
                rects=[(i, rects[i]) for i in sorted(rects)],
                soft=[(r[0] - m, r[1] - m, r[2] + m, r[3] + m) for _, r in sorted((soft or {}).items())],
                icons=[r for i, r in rects.items() if not kids.get(i)],
                refs=(layout, rects, soft))  # id が使い回されないよう、元の物を持っておく
    _LOCAL.ctx = ctx
    return ctx


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


def label_offset(route: list[Point], w: float, h: float) -> tuple[float, float]:
    """辺のラベルを線の脇に置くずれ（draw.io は線をラベルの背景の上に描くので、線の上に置くと文字を貫く）。
    横の線分なら上（右向き）か下（左向き）、縦の線分なら右（下向き）か左（上向き）。往復の辺は反対の側になる。"""
    lengths = [abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(route, route[1:])]
    rest = sum(lengths) / 2
    for (p, q), n in zip(zip(route, route[1:]), lengths):
        if rest <= n and n > 0:
            if p[1] == q[1]:
                return (0.0, -(h / 2 + 4) if q[0] > p[0] else h / 2 + 4)
            return (w / 2 + 4 if q[1] > p[1] else -(w / 2 + 4), 0.0)
        rest -= n
    return (0.0, -(h / 2 + 4))


def _backwards(route: list[Point], ex: tuple[float, float], en: tuple[float, float]) -> bool:
    """出入りの辺の向きと、線の進む向きが逆か（下の辺から入るのに上から下りてくる、など）。そうした線は名前や
    アイコンの上を通るので、ほかの形が無いときだけ使う。"""
    (p, p1), (q0, q) = (route[0], route[1]), (route[-2], route[-1])

    def wrong(f: tuple[float, float], a: Point, b: Point) -> bool:  # a → b が、辺 f から外へ向かう向きでない
        if f[1] == 1.0:
            return b[1] < a[1]
        if f[1] == 0.0:
            return b[1] > a[1]
        if f[0] == 1.0:
            return b[0] < a[0]
        if f[0] == 0.0:
            return b[0] > a[0]
        return False
    return wrong(ex, p, p1) or wrong(en, q, q0)


def _hits(a: Point, b: Point, r: Rect) -> bool:
    x1, x2 = sorted((a[0], b[0]))
    y1, y2 = sorted((a[1], b[1]))
    if x1 == x2:
        return r[0] < x1 < r[2] and y2 > r[1] and y1 < r[3]
    return r[1] < y1 < r[3] and x2 > r[0] and x1 < r[2]


def choose(layout: Layout, rects: dict[str, Rect], src: str, dst: str,
           soft: dict[str, Rect] | None = None, label: tuple[float, float] | None = None) -> tuple:
    """(exit, entry, exit の dy, entry の dy)。ほかのノードを通らない形のうち、ラベル（soft。ノード id → ラベルの矩形）を
    通らず、折れが少なく短いもの。1 つの配置の中で同じ計算を繰り返さないよう、木の形と矩形の並びは配置ごとに 1 回だけ作る。"""
    ctx = _context(layout, rects, soft)
    kids, ancestors, descendants = ctx["kids"], ctx["ancestors"], ctx["descendants"]
    allowed = {src, dst} | ancestors[src] | ancestors[dst] | descendants[src] | descendants[dst]
    others = [r for i, r in ctx["rects"] if i not in allowed]
    soft_boxes = ctx["soft"]
    icon_rects = ctx["icons"]
    best = None
    for n, shape in enumerate(SHAPES):
        ex, en = ports(rects[src], rects[dst], shape)
        sdy = LABEL_GAP if ex[1] == 1.0 and not kids.get(src) else 0
        tdy = LABEL_GAP if en[1] == 1.0 and not kids.get(dst) else 0
        route = path(rects[src], rects[dst], ex, en, sdy, tdy)
        hits = sum(1 for r in others if any(_hits(a, b, r) for a, b in zip(route, route[1:])))
        length = sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(route, route[1:]))
        soft_hits = sum(1 for r in soft_boxes  # 端のアイコン自身のラベルも避ける。すぐそばも避ける（余白 SOFT_MARGIN）
                        if any(_hits(a, b, r) for a, b in zip(route, route[1:])))
        if label is not None:  # 辺のラベル（経路の中点）が、端も含めてアイコンに重ならないように
            m = _midpoint(route)
            dx, dy = label_offset(route, label[0], label[1])
            m = (m[0] + dx, m[1] + dy)
            box = (m[0] - label[0] / 2, m[1] - label[1] / 2, m[0] + label[0] / 2, m[1] + label[1] / 2)
            soft_hits += sum(1 for r in icon_rects
                             if min(r[2], box[2]) > max(r[0], box[0]) and min(r[3], box[3]) > max(r[1], box[1]))
        key = (hits + (100 if _backwards(route, ex, en) else 0), soft_hits, len(set(route)), length, n)
        if best is None or key < best[0]:
            best = (key, ex, en, sdy, tdy)
    return best[1:]
