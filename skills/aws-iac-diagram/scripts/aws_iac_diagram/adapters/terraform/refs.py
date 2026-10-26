"""参照（references）の道具: 経路 through の足し方、参照の並べ方、props の中の $res を参照の一覧にする処理、重なりの除去。
"""
from __future__ import annotations

from dataclasses import replace

from aws_iac_diagram.adapters.terraform.evaluator.functions import Concat, Json, Res, Unknown, ZeroColl
from aws_iac_diagram.core import ir_raw


def ref_order(r: tuple) -> tuple:
    """参照 (to, attr, through) の並べ方。"""
    return (r[0], r[1] or "", r[2])


def through_refs(refs, hop: str) -> set:
    return {(to, attr, (hop,) + th) for to, attr, th in refs}


def prepend_through(v, hop: str):
    """値の中の参照に、モジュールの出力・変数をたどった経路（hop）を先頭に足す（7.3 の through）。"""
    if isinstance(v, Res):
        return replace(v, through=(hop,) + v.through)
    if isinstance(v, Unknown):
        return Unknown(v.reason, v.code, v.level, through_refs(v.refs, hop))
    if isinstance(v, Concat):
        return Concat(tuple(prepend_through(p, hop) for p in v.parts))
    if isinstance(v, Json):
        return Json(prepend_through(v.value, hop))
    if isinstance(v, ZeroColl):
        return ZeroColl(prepend_through(v.res, hop))
    if isinstance(v, list):
        return type(v)(prepend_through(e, hop) for e in v)
    if isinstance(v, dict):
        return type(v)((k, prepend_through(e, hop)) for k, e in v.items())
    return v


def collect_active(props, frm: str, out: list[dict]):
    """props の中の $res を active の参照にし、一時的な __through を references の through に移した props を返す。"""
    def strip(v, path):
        if isinstance(v, list):
            return [strip(x, ir_raw.join_path(path, i)) for i, x in enumerate(v)]
        if isinstance(v, dict):
            if "$res" in v:
                ref = {"from": frm, "path": path, "to": v["$res"], "attr": v.get("attr"), "fn": "ref",
                       "state": "active"}
                if v.get("__through"):
                    ref["through"] = list(v["__through"])
                out.append(ref)
                return {"$res": v["$res"], "attr": v.get("attr")}
            if "$concat" in v:
                return {"$concat": [strip(x, path) if isinstance(x, dict) else x for x in v["$concat"]]}
            if "$json" in v:
                return {"$json": strip(v["$json"], path)}
            if ir_raw.is_marker(v):
                return v
            return {k: strip(x, ir_raw.join_path(path, ir_raw.unescape_key(k))) for k, x in v.items()}
        return v
    return strip(props, "")


def dedupe_refs(refs: list[dict]) -> list[dict]:
    rank = {"active": 2, "unevaluated": 1, "pruned": 0}
    seen: dict[tuple, dict] = {}
    for r in refs:
        key = ir_raw.ref_key(r)
        if key not in seen or rank[r["state"]] > rank[seen[key]["state"]]:
            seen[key] = r
    return list(seen.values())
