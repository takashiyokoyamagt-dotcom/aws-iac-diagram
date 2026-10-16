"""アダプタの出力（raw IR。references/ir-schema.md の 7章）の共通部品。

validate_ir.py（検査）と、各アダプタ（正規形での書き出し）が使う。
Schema（ir-raw.schema.json）では調べられない決まりをここで調べる:
  - props の中の $res と references（state: active）の1対1の対応（7.3）
  - $res・references の先のリソースがあること、address の重なり
  - $concat の正規形（隣り合う文字列をつなぐ。7.2）
  - 配列の並び順（6章）
"""
from __future__ import annotations

import json
import re

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
MARKERS = ("$res", "$pseudo", "$concat", "$json", "$az", "$import", "$unknown")


def join_path(base: str, key: str | int) -> str:
    """props の上の位置をつなぐ。リストの位置は [n]、識別子として書けないキーは ["key"]（7.3）。"""
    if isinstance(key, int):
        return f"{base}[{key}]"
    if IDENT.fullmatch(key):
        return f"{base}.{key}" if base else key
    return f"{base}[{json.dumps(key, ensure_ascii=False)}]"


def unescape_key(key: str) -> str:
    """$$ で逃がした入力のキーを元に戻す（7.2）。"""
    return key[1:] if key.startswith("$$") else key


def is_marker(v) -> bool:
    return isinstance(v, dict) and len(v) >= 1 and any(k in v for k in MARKERS)


def iter_res(value, path: str):
    """value の中の $res を (path, to, attr) で返す。$concat の中は位置に数えず、$json は透過する（7.3）。"""
    if isinstance(value, list):
        for i, item in enumerate(value):
            yield from iter_res(item, join_path(path, i))
    elif isinstance(value, dict):
        if "$res" in value:
            yield path, value["$res"], value.get("attr")
        elif "$concat" in value:
            for part in value["$concat"]:
                if isinstance(part, dict):
                    yield from iter_res(part, path)
        elif "$json" in value:
            yield from iter_res(value["$json"], path)
        elif not is_marker(value):
            for k, v in value.items():
                yield from iter_res(v, join_path(path, unescape_key(k)))


def props_base(fmt: str) -> str:
    return "Properties" if fmt == "cfn" else ""


def ref_key(r: dict) -> tuple:
    return (r.get("from", ""), r.get("path", ""), r.get("to", ""), r.get("attr") or "", r.get("fn", ""))


def diag_key(d: dict) -> tuple:
    return (d.get("address", ""), d.get("path", ""), d.get("code", ""))


def normalize_concat(parts: list):
    """$concat の正規形（隣り合う文字列をつなぐ、空文字を消す、印が無ければ文字列にする）。"""
    out: list = []
    for p in parts:
        if isinstance(p, dict) and "$concat" in p:  # 入れ子は平らにする
            inner = normalize_concat(p["$concat"])
            items = inner["$concat"] if isinstance(inner, dict) else [inner]
        else:
            items = [p]
        for it in items:
            if it == "":
                continue
            if isinstance(it, str) and out and isinstance(out[-1], str):
                out[-1] += it
            else:
                out.append(it)
    if all(isinstance(p, str) for p in out):
        return "".join(out)
    if len(out) == 1:  # 印が1つだけなら、その印そのもの
        return out[0]
    return {"$concat": out}


def canonical_raw(ir: dict) -> dict:
    """配列を 6章の順に並べ替えたコピーを返す。"""
    ir = json.loads(json.dumps(ir))
    ir["resources"] = sorted(ir.get("resources", []), key=lambda r: r.get("address", ""))
    ir["references"] = sorted(ir.get("references", []), key=ref_key)
    ir["diagnostics"] = sorted(ir.get("diagnostics", []), key=diag_key)
    return ir


def _concat_errors(value, where: str) -> list[str]:
    errs: list[str] = []
    if isinstance(value, list):
        for i, v in enumerate(value):
            errs += _concat_errors(v, f"{where}[{i}]")
    elif isinstance(value, dict):
        if "$concat" in value:
            parts = value["$concat"]
            if any(isinstance(a, str) and isinstance(b, str) for a, b in zip(parts, parts[1:])):
                errs.append(f"{where}: $concat の隣り合う文字列がつながっていない（7.2 の正規形）")
            for p in parts:
                if isinstance(p, dict):
                    errs += _concat_errors(p, where)
        elif "$json" in value:
            errs += _concat_errors(value["$json"], where)
        elif not is_marker(value):
            for k, v in value.items():
                errs += _concat_errors(v, f"{where}.{k}")
    return errs


def semantic_errors(ir: dict) -> list[str]:
    errs: list[str] = []
    fmt = ir.get("format", "")
    base = props_base(fmt)
    addresses = [r["address"] for r in ir.get("resources", [])]
    known = set(addresses)
    if len(known) != len(addresses):
        dup = sorted({a for a in addresses if addresses.count(a) > 1})
        errs.append(f"resources: address が重なっている: {dup}")

    # props の $res
    from_props: set[tuple] = set()
    for r in ir.get("resources", []):
        a = r["address"]
        for path, to, attr in iter_res(r.get("props", {}), base):
            if to not in known:
                errs.append(f"{a} {path}: $res の先 {to} が resources に無い")
            from_props.add((a, path, to, attr))
        errs += _concat_errors(r.get("props", {}), f"{a} props")

    # references
    refs = ir.get("references", [])
    keys = [ref_key(x) for x in refs]
    if len(set(keys)) != len(keys):
        errs.append("references: (from, path, to, attr, fn) が重なっている件がある")
    active: set[tuple] = set()
    for x in refs:
        for end in ("from", "to"):
            if x[end] not in known:
                errs.append(f"references: {x['from']} {x['path']} の {end} {x[end]} が resources に無い")
        if x["fn"] in ("DependsOn", "depends_on"):
            continue
        if fmt == "cfn" and not x["path"].startswith("Properties"):
            continue  # Metadata などの Properties の外の参照は props に現れない（7.3）
        if x["state"] == "active":
            active.add((x["from"], x["path"], x["to"], x["attr"]))
    for k in sorted(from_props - active, key=str):
        errs.append(f"{k[0]} {k[1]}: props の $res（→ {k[2]}）に対応する active の参照が references に無い")
    for k in sorted(active - from_props, key=str):
        errs.append(f"references: {k[0]} {k[1]} → {k[2]} は active なのに props に $res が無い")

    # 並び順（6章）
    want = canonical_raw(ir)
    for key in ("resources", "references", "diagnostics"):
        if ir.get(key, []) != want[key]:
            errs.append(f"{key}: 並び順が 6章の順になっていない（--write で整形できる）")
    return errs
