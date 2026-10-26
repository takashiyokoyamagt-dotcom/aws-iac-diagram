"""評価した値の中の $res の印と、一時的な印（__fn・__through）の扱い。"""
from __future__ import annotations

from aws_iac_diagram.core import ir_raw


def res_with_fn(value):
    """評価した後の値の中の $res を (to, attr, fn) で返す（fn は評価中に付けた一時的な __fn）。"""
    if isinstance(value, list):
        for v in value:
            yield from res_with_fn(v)
    elif isinstance(value, dict):
        if "$res" in value:
            yield value["$res"], value.get("attr"), value.get("__fn", "Ref")
        elif "$concat" in value:
            for v in value["$concat"]:
                yield from res_with_fn(v)
        elif "$json" in value:
            yield from res_with_fn(value["$json"])
        elif not ir_raw.is_marker(value):
            for v in value.values():
                yield from res_with_fn(v)

def split_concat(parts: list, delim: str) -> list:
    """$concat を区切り文字の位置で分ける。印は分けない（7.2 のリストの分割）。"""
    out: list = []
    cur: list = []
    for p in parts:
        if isinstance(p, str):
            pieces = p.split(delim)
            for i, piece in enumerate(pieces):
                if i:
                    out.append(cur)
                    cur = []
                cur.append(piece)
        else:
            cur.append(p)
    out.append(cur)
    return [ir_raw.normalize_concat(c) for c in out]

def _walk_res(value, fn):
    """値の中の $res の印のそれぞれに fn(印) を当てたコピーを返す。"""
    if isinstance(value, list):
        return [_walk_res(v, fn) for v in value]
    if isinstance(value, dict):
        if "$res" in value:
            return fn(dict(value))
        if "$concat" in value:
            return {"$concat": [_walk_res(v, fn) for v in value["$concat"]]}
        if "$json" in value:
            return {"$json": _walk_res(value["$json"], fn)}
        if ir_raw.is_marker(value):
            return value
        return {k: _walk_res(v, fn) for k, v in value.items()}
    return value

def prepend_through(value, hop: str):
    """ネストスタックの出力・パラメータ、Export をたどったとき、経路を through の先頭に足す（7.3）。"""
    def f(m):
        m["__through"] = [hop] + m.get("__through", [])
        return m
    return _walk_res(value, f)

def set_fn(value, fn_name: str):
    def f(m):
        m["__fn"] = fn_name
        return m
    return _walk_res(value, f)

def strip_internal(value):
    """出力する前に、一時的な __fn・__through を取り除く。"""
    def f(m):
        return {"$res": m["$res"], "attr": m.get("attr")}
    return _walk_res(value, f)
