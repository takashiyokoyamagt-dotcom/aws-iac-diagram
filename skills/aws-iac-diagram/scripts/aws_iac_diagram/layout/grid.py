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


def _leaf_grid(leaves: list[dict], columns: int, parent: str | None, ox: int, oy: int, out: Layout) -> tuple[int, int]:
    """アイコンを格子に置く。返すのは占めた幅と高さ（空なら 0, 0）。"""
    if not leaves:
        return 0, 0
    cell_w = max(max(ICON, label_width(n["label"])) for n in leaves) + GUTTER
    cell_h = ICON + LABEL_H + GUTTER
    for i, n in enumerate(leaves):
        col, row = i % columns, i // columns
        out.placed[n["id"]] = Placed(n["id"], ox + col * cell_w + (cell_w - ICON) // 2, oy + row * cell_h + GUTTER // 2,
                                     ICON, ICON, parent)
    rows = math.ceil(len(leaves) / columns)
    return min(len(leaves), columns) * cell_w, rows * cell_h


def _place_group(n: dict, kids: dict, p: Params, out: Layout) -> tuple[int, int]:
    """枠 n の中身を置き、枠の大きさを返す（枠自身の座標は呼ぶ側が決める）。"""
    children = kids.get(n["id"], [])
    leaves = sorted((c for c in children if c["category"] != "group"), key=lambda c: c["id"])
    groups = sorted((c for c in children if c["category"] == "group"), key=_group_order)
    lw, lh = _leaf_grid(leaves, p.columns, n["id"], PAD, TITLE, out)
    y = TITLE + lh
    x, width, height = PAD, lw, y
    vertical = n["type"] == "availability_zone"
    for g in groups:
        w, h = _place_group(g, kids, p, out)
        out.placed[g["id"]] = Placed(g["id"], x, y, w, h, n["id"])
        if vertical:
            y += h + PAD
            width, height = max(width, w), y - PAD
        else:
            x += w + PAD
            width, height = max(width, x - PAD - PAD), max(height, y + h)
    width = max(width, label_width(n["label"]) + PAD)
    return width + 2 * PAD, max(height, TITLE) + PAD


def place(nodes: list[dict], params: Params = Params()) -> Layout:
    out = Layout()
    kids: dict[str, list[dict]] = {}
    for n in nodes:
        if n["parent"] is not None:
            kids.setdefault(n["parent"], []).append(n)
    roots = [n for n in nodes if n["parent"] is None]
    left = sorted((n for n in roots if n["category"] == "external"), key=lambda n: n["id"])
    groups = sorted((n for n in roots if n["category"] == "group"), key=_group_order)
    right = sorted((n for n in roots if n["category"] == "resource"), key=lambda n: n["id"])

    x, height = 0, 0
    w, h = _leaf_grid(left, 1, None, x, 0, out)
    if w:
        x += w + BAND_GAP
        height = h
    for g in groups:
        w, h = _place_group(g, kids, params, out)
        out.placed[g["id"]] = Placed(g["id"], x, 0, w, h, None)
        x += w + BAND_GAP
        height = max(height, h)
    w, h = _leaf_grid(right, params.band_columns, None, x, 0, out)
    if w:
        x += w + BAND_GAP
        height = max(height, h)
    out.width, out.height = max(x - BAND_GAP, 0), height
    return out
