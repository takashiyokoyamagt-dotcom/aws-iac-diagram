"""B1: 配置の候補を列挙して、スコアの最小のものを選ぶ（設計案 phase4-design-draft の 4 章）。

スコアは呼ぶ側が渡す（出力の検査と同じモデルで採点するため。layout は validate を import しない）。
同点は候補の名前の辞書順で最初のもの。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from aws_iac_diagram.layout.grid import Layout, Params, place

COLUMNS = (1, 2, 3, 4)
BAND_COLUMNS = (1, 2, 3)
ORDERS = ("degree", "id", "layer", "layered")
LEAVES_POS = ("center", "side", "top")
HUBS = ("center", "last", "none")
GUTTERS = (48, 96, 144)
PROBLEM = 1000  # これ以上のスコアは、貫通かラベルの重なりが残っている


def candidates() -> dict[str, Params]:
    """候補の名前 → パラメータ（辞書順）。"""
    flags = (False, True)
    out = {f"{o}-c{c}-b{b}-g{g:03d}-f{int(f)}-m{int(m)}-p{int(pl)}-{lp}-h{h}":
           Params(columns=c, band_columns=b, order=o, gutter=g, flip=f, merge_external=m, public_last=pl, leaves_pos=lp, hub=h)
           for o in ORDERS for c in COLUMNS for b in BAND_COLUMNS for g in GUTTERS for f in flags for m in flags for pl in flags
           for lp in LEAVES_POS for h in HUBS}
    return dict(sorted(out.items()))


def best(nodes: list[dict], edges: list[dict], score: Callable[[Layout], int]) -> tuple[str, Layout, int]:
    """(候補の名前, 配置, スコア)。基本の候補で問題（スコア PROBLEM 以上）が残るときだけ、互い違いの候補も見る。"""
    chosen: tuple[str, Layout, int] | None = None
    seen: set[tuple] = set()
    base = candidates()
    def run(items: dict[str, Params]) -> None:
        nonlocal chosen
        for name, params in items.items():
            layout = place(nodes, params, edges)
            shape = tuple(sorted((q.id, q.x, q.y, q.w, q.h) for q in layout.placed.values()))
            if shape in seen:  # 同じ配置なら同じスコア。辞書順で先の候補が既に見ている
                continue
            seen.add(shape)
            s = score(layout)
            if chosen is None or s < chosen[2]:
                chosen = (name, layout, s)
    run(base)
    assert chosen is not None
    if chosen[2] >= PROBLEM:
        run({f"{n}-s": replace(p, stagger=True) for n, p in base.items()})
    return chosen
