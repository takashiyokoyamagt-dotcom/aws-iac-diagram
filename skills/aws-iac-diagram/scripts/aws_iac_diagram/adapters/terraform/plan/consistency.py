"""plan から作った props・参照の整合: 存在しないリソースへの参照を props から外し、参照の位置を props と合わせる。
"""
from __future__ import annotations

import re

from aws_iac_diagram.core import ir_raw


_INSTANCE_KEYS = re.compile(r'\[(?:\d+|\*|"(?:[^"\\]|\\.)*")\]')


def block_mismatch(tf_resources: list[dict], p_res: dict) -> str:
    """plan のブロックと .tf のブロックの食い違いが大きいとき（3割を超える）、その説明。無ければ ""。

    添字は無視して、ブロックで比べる。.tf の黒箱のモジュールの中のブロックは、.tf に無くて当然なので数えない。
    """
    blackbox = [_INSTANCE_KEYS.sub("", r["address"]) for r in tf_resources if r["type"] == "module"]
    tk = {_INSTANCE_KEYS.sub("", r["address"]) for r in tf_resources if r["type"] != "module"}
    pk = {_INSTANCE_KEYS.sub("", a) for a in p_res}
    pk = {x for x in pk if not any(x.startswith(b + ".") for b in blackbox)}
    only_plan, only_tf = pk - tk, tk - pk
    parts = []
    if pk and len(only_plan) * 10 > len(pk) * 3:
        parts.append(f"{len(only_plan)} of {len(pk)} resource block(s) in the plan are not in the .tf folder")
    if tk and len(only_tf) * 10 > len(tk) * 3:
        parts.append(f"{len(only_tf)} of {len(tk)} resource block(s) in the .tf folder are not in the plan")
    return "; ".join(parts)


def drop_missing(v, final: set):
    if isinstance(v, list):
        return [drop_missing(x, final) for x in v]
    if isinstance(v, dict):
        if "$res" in v:
            return v if v["$res"] in final else {"$unknown": f"{v['$res']} is not in the plan"}
        if "$concat" in v:
            return ir_raw.normalize_concat([drop_missing(x, final) if isinstance(x, dict) else x
                                            for x in v["$concat"]])
        if "$json" in v:
            return {"$json": drop_missing(v["$json"], final)}
        if ir_raw.is_marker(v):
            return v
        return {k: drop_missing(x, final) for k, x in v.items()}
    return v


def props_consistent(resources: list[dict], refs: list[dict]) -> list[dict]:
    """active の参照を props の $res と1対1にそろえる（props に無い active は unevaluated にする）。"""
    have = set()
    for r in resources:
        for path, to, attr in ir_raw.iter_res(r["props"], ""):
            have.add((r["address"], path, to, attr))
    out = []
    for r in refs:
        if r["state"] == "active" and r["fn"] == "ref" and (r["from"], r["path"], r["to"], r["attr"]) not in have:
            r = dict(r, state="unevaluated")
        out.append(r)
    return out
