"""参照（references）の集め方: 評価しない値の中の静的な参照、評価した値からの active の参照、重なりの除去。"""
from __future__ import annotations

from aws_iac_diagram.adapters.cloudformation.model import SUB_VAR
from aws_iac_diagram.core import ir_raw


def static_refs(value, resources: set[str]):
    """評価しない値の中の Ref・GetAtt・Sub の参照を探す（(to, attr, fn) を返す）。"""
    if isinstance(value, list):
        for v in value:
            yield from static_refs(v, resources)
    elif isinstance(value, dict):
        if len(value) == 1:
            (k, arg), = value.items()
            if k == "Ref" and isinstance(arg, str) and arg in resources:
                yield arg, None, "Ref"
                return
            if k == "Fn::GetAtt":
                if isinstance(arg, str) and "." in arg:
                    arg = arg.split(".", 1)
                if isinstance(arg, list) and arg and isinstance(arg[0], str) and arg[0] in resources:
                    yield arg[0], arg[1] if len(arg) > 1 and isinstance(arg[1], str) else None, "GetAtt"
                    return
            if k == "Fn::Sub":
                tmpl = arg if isinstance(arg, str) else (arg[0] if isinstance(arg, list) and arg else "")
                variables = arg[1] if isinstance(arg, list) and len(arg) > 1 and isinstance(arg[1], dict) else {}
                for m in SUB_VAR.finditer(tmpl if isinstance(tmpl, str) else ""):
                    var = m.group(1).strip()
                    if var in variables or var.startswith("!"):
                        continue
                    if var in resources:
                        yield var, None, "Sub"
                    elif "." in var and var.split(".", 1)[0] in resources:
                        r, a = var.split(".", 1)
                        yield r, a, "Sub"
                yield from static_refs(variables, resources)
                return
        for v in value.values():
            yield from static_refs(v, resources)

def collect_active(value, base: str, frm: str, out: list[dict]):
    """評価した後の値から $res を集めて active の参照にし、一時的な印を取り除いた値を返す。"""
    found: list[tuple] = []

    def strip(v, path):
        if isinstance(v, list):
            return [strip(x, ir_raw.join_path(path, i)) for i, x in enumerate(v)]
        if isinstance(v, dict):
            if "$res" in v:
                found.append((path, v["$res"], v.get("attr"), v.get("__fn", "Ref"), v.get("__through")))
                return {"$res": v["$res"], "attr": v.get("attr")}
            if "$concat" in v:
                return {"$concat": [strip(x, path) if isinstance(x, dict) else x for x in v["$concat"]]}
            if "$json" in v:
                return {"$json": strip(v["$json"], path)}
            if ir_raw.is_marker(v):
                return v
            return {k: strip(x, ir_raw.join_path(path, ir_raw.unescape_key(k))) for k, x in v.items()}
        return v

    cleaned = strip(value, base)
    for path, to, attr, fn, through in found:
        ref = {"from": frm, "path": path, "to": to, "attr": attr, "fn": fn, "state": "active"}
        if through:
            ref["through"] = through
        out.append(ref)
    return cleaned

def dedupe_refs(refs: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for r in refs:
        key = ir_raw.ref_key(r)
        # 同じキーなら active を優先する
        if key not in seen or (seen[key]["state"] != "active" and r["state"] == "active"):
            seen[key] = r
    return list(seen.values())
