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
    order: str = "id"  # 同じ枠の中の並び: id／layer（上流からの層の順）／degree（辺の多い順）
    gutter: int = GUTTER  # アイコンのマスの間の通路
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
        if p.order == "layer":
            return (rank.get(n["id"], 0), n["id"])
        if p.order == "degree":
            return (-rank.get(n["id"], 0), n["id"])
        return (0, n["id"])
    return key


def _leaf_grid(leaves: list[dict], columns: int, parent: str | None, ox: int, oy: int, out: Layout, gutter: int = GUTTER) -> tuple[int, int]:
    """アイコンを格子に置く。返すのは占めた幅と高さ（空なら 0, 0）。"""
    if not leaves:
        return 0, 0
    cell_w = max(max(ICON, label_width(n["label"])) for n in leaves) + gutter
    cell_h = ICON + LABEL_H + gutter
    for i, n in enumerate(leaves):
        col, row = i % columns, i // columns
        out.placed[n["id"]] = Placed(n["id"], ox + col * cell_w + (cell_w - ICON) // 2, oy + row * cell_h + gutter // 2,
                                     ICON, ICON, parent)
    rows = math.ceil(len(leaves) / columns)
    return min(len(leaves), columns) * cell_w, rows * cell_h


def _place_group(n: dict, kids: dict, p: Params, rank: dict[str, int], out: Layout) -> tuple[int, int]:
    """枠 n の中身を置き、枠の大きさを返す（枠自身の座標は呼ぶ側が決める）。"""
    children = kids.get(n["id"], [])
    leaves = sorted((c for c in children if c["category"] != "group"), key=_sort_key(p, rank))
    groups = sorted((c for c in children if c["category"] == "group"),
                    key=lambda c: (_group_order(c)[0], *_sort_key(p, rank)(c)))
    lw, lh = _leaf_grid(leaves, p.columns, n["id"], PAD, TITLE, out, p.gutter)
    y = TITLE + lh
    x, width, height = PAD, lw, y
    vertical = (n["type"] == "availability_zone") != p.flip
    for g in groups:
        w, h = _place_group(g, kids, p, rank, out)
        out.placed[g["id"]] = Placed(g["id"], x, y, w, h, n["id"])
        if vertical:
            y += h + PAD
            width, height = max(width, w), y - PAD
        else:
            x += w + PAD
            width, height = max(width, x - PAD - PAD), max(height, y + h)
    width = max(width, label_width(n["label"]) + PAD)
    return width + 2 * PAD, max(height, TITLE) + PAD


def place(nodes: list[dict], params: Params = Params(), edges: list[dict] | tuple = ()) -> Layout:
    out = Layout()
    rank = layers(nodes, list(edges)) if params.order == "layer" else degrees(list(edges))
    key = _sort_key(params, rank)
    kids: dict[str, list[dict]] = {}
    for n in nodes:
        if n["parent"] is not None:
            kids.setdefault(n["parent"], []).append(n)
    roots = [n for n in nodes if n["parent"] is None]
    left = sorted((n for n in roots if n["category"] == "external"), key=key)
    groups = sorted((n for n in roots if n["category"] == "group"), key=lambda n: (_group_order(n)[0], *key(n)))
    right = sorted((n for n in roots if n["category"] == "resource"), key=key)

    x, height = 0, 0
    w, h = _leaf_grid(left, 1, None, x, 0, out, params.gutter)
    if w:
        x += w + BAND_GAP
        height = h
    for g in groups:
        w, h = _place_group(g, kids, params, rank, out)
        out.placed[g["id"]] = Placed(g["id"], x, 0, w, h, None)
        x += w + BAND_GAP
        height = max(height, h)
    w, h = _leaf_grid(right, params.band_columns, None, x, 0, out, params.gutter)
    if w:
        x += w + BAND_GAP
        height = max(height, h)
    out.width, out.height = max(x - BAND_GAP, 0), height
    return out
