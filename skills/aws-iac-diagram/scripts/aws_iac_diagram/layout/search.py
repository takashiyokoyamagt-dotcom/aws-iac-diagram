"""B1: 配置の候補を列挙して、スコアの最小のものを選ぶ（設計案 phase4-design-draft の 4 章）。

スコアは呼ぶ側が渡す（出力の検査と同じモデルで採点するため。layout は validate を import しない）。
同点は候補の名前の辞書順で最初のもの。
"""
from __future__ import annotations

from collections.abc import Callable

from aws_iac_diagram.layout.grid import Layout, Params, place

COLUMNS = (1, 2, 3, 4, 6)
BAND_COLUMNS = (1, 2, 3)
ORDERS = ("degree", "id", "layer")
GUTTERS = (48, 96, 144)


def candidates() -> dict[str, Params]:
    """候補の名前 → パラメータ（辞書順）。"""
    out = {f"{o}-c{c}-b{b}-g{g:03d}-f{int(f)}": Params(columns=c, band_columns=b, order=o, gutter=g, flip=f)
           for o in ORDERS for c in COLUMNS for b in BAND_COLUMNS for g in GUTTERS for f in (False, True)}
    return dict(sorted(out.items()))


def best(nodes: list[dict], edges: list[dict], score: Callable[[Layout], int]) -> tuple[str, Layout, int]:
    """(候補の名前, 配置, スコア)。"""
    chosen: tuple[str, Layout, int] | None = None
    for name, params in candidates().items():
        layout = place(nodes, params, edges)
        s = score(layout)
        if chosen is None or s < chosen[2]:
            chosen = (name, layout, s)
    assert chosen is not None
    return chosen
