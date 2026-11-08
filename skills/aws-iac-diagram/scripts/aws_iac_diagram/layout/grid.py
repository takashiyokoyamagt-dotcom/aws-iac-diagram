"""配置の 1 候補の座標（設計案 phase4-design-draft の 3 章）。入れ子の内側から大きさを積み上げる。座標はすべて整数で、親からの相対。

ノードは normalized IR の `nodes` の dict。図の上の左側の帯に external、中央に親の無い枠、右側の帯に親の無いアイコンを置く。
"""
from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field

ICON = 48
GUTTER = 48    # アイコンのマスの間の通路（辺が通る）
PAD = 24       # 枠の内側の余白
TITLE = 32     # 枠の上のラベルの高さ
BAND_GAP = 96  # 帯の間
FONT = 12
LABEL_H = math.ceil(FONT * 1.2)


@dataclass(frozen=True)
class Params:
    columns: int = 4  # 枠の中のアイコンの 1 行の個数
    band_columns: int = 2  # 右の帯の 1 行の個数
    order: str = "id"  # 同じ枠の中の並び: id／layer（上流からの層の順）／degree（辺の多い順）／layered（層を列にする）
    gutter: int = GUTTER  # アイコンのマスの間の通路
    merge_external: bool = False  # True: external を左の帯でなく、親の無いアイコンの格子に混ぜる
    public_last: bool = False  # True: 同じ枠の中で public のサブネットを後ろに置く
    leaves_pos: str = "top"  # 枠の中のアイコンの位置: top／side／center
    hub: bool = False  # 中身の辺が多い枠を真ん中に置く
    flip: bool = False  # True: AZ を縦に、AZ の中のサブネットを横に並べる


@dataclass
class Placed:
    id: str
    x: int
    y: int
    w: int
    h: int
    parent: str | None


@dataclass
class Layout:
    placed: dict[str, Placed] = field(default_factory=dict)
    width: int = 0
    height: int = 0


def label_width(text: str, font: int = FONT) -> int:
    return math.ceil(sum((1.0 if unicodedata.east_asian_width(c) in "WFA" else 0.6) * font for c in text))


def _group_order(n: dict) -> tuple:
    """サブネットは public → そのほか、同じ順の中は id。"""
    return (0 if (n.get("attrs") or {}).get("access") == "public" else 1, n["id"])


def layers(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """入口のないノードを 0 として、辺をたどった最長の深さ（閉路があっても回数で止まる）。"""
    ids = {n["id"] for n in nodes}
    pairs = sorted((e["from"], e["to"]) for e in edges if e["from"] in ids and e["to"] in ids and e["from"] != e["to"])
    depth = dict.fromkeys(ids, 0)
    for _ in range(len(ids)):
        changed = False
        for a, b in pairs:
            if depth[b] < depth[a] + 1 <= len(ids):
                depth[b] = depth[a] + 1
                changed = True
        if not changed:
            break
    return depth


def degrees(edges: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in edges:
        out[e["from"]] = out.get(e["from"], 0) + 1
        out[e["to"]] = out.get(e["to"], 0) + 1
    return out


def _sort_key(p: Params, rank: dict[str, int]):
    def key(n: dict) -> tuple:
        if p.order in ("layer", "layered"):
            return (rank.get(n["id"], 0), n["id"])
        if p.order == "degree":
            return (-rank.get(n["id"], 0), n["id"])
        return (0, n["id"])
    return key


def _leaf_grid(leaves: list[dict], columns: int, parent: str | None, ox: int, oy: int, out: Layout, gutter: int = GUTTER,
               layered: dict[str, int] | None = None) -> tuple[int, int]:
    """アイコンを格子に置く。layered があれば層の番号を列にする。返すのは占めた幅と高さ（空なら 0, 0）。"""
    if not leaves:
        return 0, 0
    cell_w = max(max(ICON, label_width(n["label"])) for n in leaves) + gutter
    cell_h = ICON + LABEL_H + gutter
    used: dict[int, int] = {}
    base = min(layered[n["id"]] for n in leaves) if layered else 0
    max_col = max_row = 0
    for i, n in enumerate(leaves):
        if layered:
            col = layered[n["id"]] - base
            row = used.get(col, 0)
            used[col] = row + 1
        else:
            col, row = i % columns, i // columns
        max_col, max_row = max(max_col, col), max(max_row, row)
        out.placed[n["id"]] = Placed(n["id"], ox + col * cell_w + (cell_w - ICON) // 2, oy + row * cell_h + gutter // 2,
                                     ICON, ICON, parent)
    return (max_col + 1) * cell_w, (max_row + 1) * cell_h


def _hub_score(n: dict, kids: dict, deg: dict[str, int]) -> int:
    """枠 n の中のノードに付く辺の数。"""
    return deg.get(n["id"], 0) + sum(_hub_score(c, kids, deg) for c in kids.get(n["id"], []))


def _center_hub(groups: list[dict], kids: dict, deg: dict[str, int]) -> list[dict]:
    """中身の辺が多い枠ほど真ん中に置く（端の枠どうしの辺が、間の枠を横切らないように）。"""
    ranked = sorted(groups, key=lambda g: (-_hub_score(g, kids, deg), g["id"]))
    front: list[dict] = []
    back: list[dict] = []
    for i, g in enumerate(ranked):
        (front if i % 2 else back).append(g)
    return list(reversed(front)) + back


def _place_group(n: dict, kids: dict, p: Params, rank: dict[str, int], deg: dict[str, int], out: Layout) -> tuple[int, int]:
    """枠 n の中身を置き、枠の大きさを返す（枠自身の座標は呼ぶ側が決める）。

    枠の中のアイコンの位置: top（子の枠の上）／side（子の枠の右）／center（子の枠の真ん中の列。横に並ぶときだけ。縦なら side）。
    """
    children = kids.get(n["id"], [])
    leaves = sorted((c for c in children if c["category"] != "group"), key=_sort_key(p, rank))
    groups = sorted((c for c in children if c["category"] == "group"),
                    key=lambda c: (_group_order(c)[0] * (-1 if p.public_last else 1), *_sort_key(p, rank)(c)))
    vertical = (n["type"] == "availability_zone") != p.flip
    if p.hub and n["type"] != "availability_zone":
        groups = _center_hub(groups, kids, deg)
    sizes = {g["id"]: _place_group(g, kids, p, rank, deg, out) for g in groups}
    layered = rank if p.order == "layered" else None
    # アイコンの格子は幅を知るために一度計算し、位置が決まってから置き直す
    lw, lh = _leaf_grid(leaves, p.columns, n["id"], 0, 0, out, p.gutter, layered)
    pos = p.leaves_pos if groups and leaves else "top"
    if pos == "center" and (vertical or len(groups) < 2):
        pos = "side"
    x, y = PAD, TITLE + (lh if pos == "top" else 0)
    split = len(groups) // 2 if pos == "center" else -1
    leaf_x = PAD
    width = lw if pos == "top" else 0
    bottom = y
    for i, g in enumerate(groups):
        if i == split:
            leaf_x = x
            x += lw + PAD
        w, h = sizes[g["id"]]
        out.placed[g["id"]] = Placed(g["id"], x, y, w, h, n["id"])
        if vertical:
            y += h + PAD
            width, bottom = max(width, w), y - PAD
        else:
            x += w + PAD
            width, bottom = max(width, x - 2 * PAD), max(bottom, y + h)
    if pos == "side":
        leaf_x = PAD + width + PAD
        width = leaf_x - PAD + lw
    if pos != "top" and not vertical:
        bottom = max(bottom, TITLE + lh)
    if pos == "side":
        bottom = max(bottom, TITLE + lh)
    if leaves:
        for c in leaves:
            q = out.placed[c["id"]]
            q.x += leaf_x
            q.y += TITLE
    width = max(width, label_width(n["label"]) + PAD)
    return width + 2 * PAD, max(bottom, TITLE) + PAD


def place(nodes: list[dict], params: Params = Params(), edges: list[dict] | tuple = ()) -> Layout:
    out = Layout()
    deg = degrees(list(edges))
    rank = layers(nodes, list(edges)) if params.order in ("layer", "layered") else deg
    key = _sort_key(params, rank)
    kids: dict[str, list[dict]] = {}
    for n in nodes:
        if n["parent"] is not None:
            kids.setdefault(n["parent"], []).append(n)
    roots = [n for n in nodes if n["parent"] is None]
    left = sorted((n for n in roots if n["category"] == "external" and not params.merge_external), key=key)
    groups = sorted((n for n in roots if n["category"] == "group"), key=lambda n: (_group_order(n)[0], *key(n)))
    if params.hub:
        groups = _center_hub(groups, kids, deg)
    right = sorted((n for n in roots if n["category"] != "group" and n["id"] not in {x["id"] for x in left}), key=key)

    x, height = 0, 0
    w, h = _leaf_grid(left, 1, None, x, 0, out, params.gutter)
    if w:
        x += w + BAND_GAP
        height = h
    for g in groups:
        w, h = _place_group(g, kids, params, rank, deg, out)
        out.placed[g["id"]] = Placed(g["id"], x, 0, w, h, None)
        x += w + BAND_GAP
        height = max(height, h)
    w, h = _leaf_grid(right, params.band_columns, None, x, 0, out, params.gutter, rank if params.order == "layered" else None)
    if w:
        x += w + BAND_GAP
        height = max(height, h)
    out.width, out.height = max(x - BAND_GAP, 0), height
    return out
