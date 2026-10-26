""".tf の raw IR と plan JSON を合わせる（combine）。address と作られるかは plan、file・props・参照の位置は .tf、決まらなかった値は plan の値で埋める。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from aws_iac_diagram.adapters.terraform.addresses import block_address
from aws_iac_diagram.adapters.terraform.plan.consistency import block_mismatch, drop_missing, props_consistent
from aws_iac_diagram.adapters.terraform.plan.diagnostics import diag
from aws_iac_diagram.adapters.terraform.plan.masking import literal_only, mask_props, under_any
from aws_iac_diagram.adapters.terraform.plan.raw import assumption, read_plan
from aws_iac_diagram.adapters.terraform.plan.read import load_plan
from aws_iac_diagram.adapters.terraform.plan.reader import PlanReader
from aws_iac_diagram.adapters.terraform.plan.values import conv, finish, has_true
from aws_iac_diagram.adapters.terraform.refs import dedupe_refs
from aws_iac_diagram.core import ir_raw


# .tf の診断のうち、plan の値で埋めてよい $unknown の理由（秘密の値 TF-SENSITIVE-VAR などは埋めない）
FILLABLE = {"TF-UNRESOLVED-VAR", "TF-UNEVALUATED", "TF-EVAL-ERROR", "TF-UNSUPPORTED-FUNCTION", "TF-COUNT-INDEX",
            "TF-MODULE-SUMMARY-OUTPUT", "TF-UNDEFINED-REF"}


def _walk_fill(tv, pv, pu, ps, path: str, fill_paths: set, filled: list):
    """.tf の値 tv の $unknown のうち、fill_paths にある位置を plan の値で埋める。"""
    if isinstance(tv, dict) and set(tv) == {"$unknown"}:
        if path in fill_paths and pu is not True and ps is not True and not has_true(ps) and not has_true(pu) \
                and pv is not None:
            filled.append(path)
            return finish(conv(pv))
        return tv
    if isinstance(tv, dict) and "$json" in tv and len(tv) == 1:
        if ps is True or has_true(ps) or pu is True or has_true(pu):
            return tv  # JSON の文字列の全体が sensitive・known after apply: 中の位置も plan の値で埋めない
        if isinstance(pv, str):
            try:
                inner = json.loads(pv)
            except (ValueError, RecursionError):
                return tv
            return {"$json": _walk_fill(tv["$json"], inner, None, None, path, fill_paths, filled)}
        return tv
    if isinstance(tv, dict) and "$concat" in tv:
        if path in fill_paths and isinstance(pv, str) and pu is not True and ps is not True \
                and not has_true(ps) and not any(isinstance(x, dict) and "$res" in x for x in tv["$concat"]):
            filled.append(path)
            return ir_raw.maybe_json(pv)
        return tv
    if isinstance(tv, list):
        pl = pv if isinstance(pv, list) else []
        ul = pu if isinstance(pu, list) else []
        sl = ps if isinstance(ps, list) else []
        return [_walk_fill(x, pl[i] if i < len(pl) else None, ul[i] if i < len(ul) else None,
                           True if ps is True else sl[i] if i < len(sl) else None, ir_raw.join_path(path, i),
                           fill_paths, filled)
                for i, x in enumerate(tv)]
    if isinstance(tv, dict) and not ir_raw.is_marker(tv):
        pd = pv if isinstance(pv, dict) else {}
        ud = pu if isinstance(pu, dict) else {}
        sd = ps if isinstance(ps, dict) else {}
        out = {}
        for k, x in tv.items():
            uk = ir_raw.unescape_key(k)
            out[k] = _walk_fill(x, pd.get(uk), ud.get(uk), True if ps is True else sd.get(uk),
                                ir_raw.join_path(path, uk), fill_paths, filled)
        return out
    return tv


def _tfjson_files(reader: PlanReader, input_dir: Path) -> dict:
    """.tf.json に書かれたブロックの address（インスタンスの添字なし）→ file（ルートとローカルモジュール）。

    plan の source で決まるフォルダのうち、--input のフォルダの外にあるものは読まない。
    """
    out = {}
    try:
        top = input_dir.resolve()
    except OSError:
        return out
    outside = 0
    for mod in reader.all_mods():
        if mod.remote or mod.dir is None:
            continue
        d = (input_dir / mod.dir)
        try:
            if not d.is_dir():
                continue
            if not d.resolve().is_relative_to(top):
                outside += 1
                continue
        except (OSError, ValueError):
            continue
        for f in sorted(d.glob("*.tf.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, ValueError, RecursionError):
                continue
            rel = Path(os.path.relpath(f, input_dir)).as_posix()
            for kind, prefix in (("resource", ""), ("data", "data.")):
                blocks = doc.get(kind) if isinstance(doc, dict) else None
                items = blocks if isinstance(blocks, list) else [blocks] if isinstance(blocks, dict) else []
                for it in items:
                    for typ, names in (it or {}).items():
                        for nm in (names if isinstance(names, dict) else {}):
                            out[f"{mod.prefix}{prefix}{typ}.{nm}"] = rel
    if outside:
        reader.diag("info", "TF-PLAN-PATH-OUTSIDE", "", "",
                    f"{outside} local module folder(s) are outside the --input folder; their .tf.json files are "
                    "not looked up")
    return out


def combine(tf_raw: dict, plan_path: Path, input_dir: Path, root_base: Path | None = None,
            plan: dict | None = None) -> dict:
    """.tf の raw IR（tf_raw）と plan JSON を合わせる（7.2 の「TF の plan JSON」の .tf と合わせるとき）。

    plan: 読み込み済みの plan JSON（build_raw が変数の値のために読んだもの。無ければ plan_path から読む）。
    """
    plan = plan if plan is not None else load_plan(plan_path)
    reader = read_plan(plan, plan_path.name)
    p_res = {r["address"]: r for r in reader.resources}
    t_res = {r["address"]: r for r in tf_raw["resources"]}
    t_file_by_block: dict = {}
    for r in tf_raw["resources"]:
        t_file_by_block.setdefault(block_address(r["address"]).replace("[*]", ""), r["file"])
    t_file_by_module: dict = {}
    for r in tf_raw["resources"]:
        if r.get("module"):
            t_file_by_module.setdefault(r["module"], r["file"])
        if r["type"] == "module":
            t_file_by_module.setdefault(r["address"], r["file"])
    tfjson = _tfjson_files(reader, input_dir)
    diags_t = [d for d in tf_raw["diagnostics"]]
    fillable: dict = {}  # address → 値が決まらないことによる診断の位置（plan の値で埋めてよい位置）
    for d in diags_t:
        if d.get("address") and d["code"] in FILLABLE:
            fillable.setdefault(d["address"], set()).add(d.get("path", ""))
    out_res: list[dict] = []
    from_tf: set = set()
    filled_paths: dict = {}
    sens_diags: list[dict] = []
    masked_paths: dict = {}  # address → 伏せた位置（.tf の診断の文に値が入りうるので、その下の診断は消す）
    for a, pr in sorted(p_res.items()):
        tr = t_res.get(a)
        if tr is not None and tr["type"] == pr["type"]:
            e = json.loads(json.dumps(tr))
            e["enabled"] = pr["enabled"]
            e.pop("multiplicity", None)
            inst = reader.insts.get(a)
            masked: list = []
            if inst is not None:
                if pr["enabled"]:
                    filled: list = []
                    e["props"] = _walk_fill(e["props"], inst.after, inst.unknown, inst.sens, "",
                                            fillable.get(a, set()), filled)
                    filled_paths[a] = set(filled)
                # .tf の評価は plan の変数の値を使うので、sensitive と宣言していない変数が provider の sensitive の
                # 属性に入っていることがある。plan が sensitive とした位置は、.tf の値も必ず伏せる
                found: list = []
                e["props"] = mask_props(e["props"], inst.sens, found)
                masked += found
                sens_diags += [diag("TF-PLAN-SENSITIVE", a, path, "sensitive value in the plan; not used")
                               for path in found]
            if not pr["enabled"]:
                # 作られないリソース（count 0・destroy の plan）: 消す前の sensitive の印があれば伏せ、そのうえで、
                # plan の変数から来た値は使わない（リテラルの値だけ残す）
                lit: list = []
                e["props"] = literal_only(e["props"], pr["props"], "", lit)
                found = []
                flags = reader.deleted_sens.get(block_address(a))
                if flags is not None:
                    e["props"] = mask_props(e["props"], flags, found)
                masked += lit + found
                sens_diags += [diag("TF-PLAN-SENSITIVE", a, path, "sensitive value in the plan; not used")
                               for path in found]
                sens_diags += [diag("TF-PLAN-LITERAL-ONLY", a, path,
                                     "the resource is not created; a value that is not a literal is not taken from "
                                     "the plan variables") for path in lit if path not in found]
            if masked:
                masked_paths[a] = masked
            out_res.append(e)
            from_tf.add(a)
            continue
        e = json.loads(json.dumps(pr))
        b = block_address(a)
        mod_file = None
        m = pr.get("module")
        while m:  # モジュールの中なら、そのモジュール（無ければ外側の呼び出し）の .tf のファイル
            if m in t_file_by_module:
                mod_file = t_file_by_module[m]
                break
            m = m.rsplit(".module.", 1)[0] if ".module." in m else None
        e["file"] = tfjson.get(b) or t_file_by_block.get(b) or mod_file or reader.file
        out_res.append(e)
    final = {r["address"] for r in out_res}
    final_by_block: dict = {}
    for x in sorted(final):
        final_by_block.setdefault(block_address(x), []).append(x)

    def expand(to: str) -> list[str]:
        if to in final:
            return [to]
        if to.endswith("[*]"):
            return final_by_block.get(to[:-3], [])
        return []

    refs: list[dict] = []
    t_pairs: dict = {}
    for r in tf_raw["references"]:
        if r["from"] not in from_tf:
            continue
        for to in expand(r["to"]):
            n = dict(r, to=to)
            if to != r["to"] and n["state"] == "active" and n["fn"] == "ref":  # depends_on は active のまま
                n["state"] = "unevaluated"
            refs.append(n)
            t_pairs.setdefault(r["from"], set()).add(block_address(to))
    # .tf の props の $res の先が無くなったもの（×N の [*] や黒箱の呼び出し）は $unknown にする
    for e in out_res:
        if e["address"] not in from_tf:
            continue
        e["props"] = drop_missing(e["props"], final)
    for r in reader.refs:
        if r["from"] in from_tf:
            # configuration の参照を優先する: .tf の参照に無い組（from とブロック）は足す
            if block_address(r["to"]) in t_pairs.get(r["from"], set()):
                continue
            n = dict(r)
            if n["state"] == "active" and n["fn"] == "ref":
                n["state"] = "unevaluated"
            refs.append(n)
            reader.diag("info", "TF-PLAN-EXTRA-REF", r["from"], r["path"],
                        f"reference to {r['to']} is in the plan's configuration but not found in the .tf; "
                        "added as unevaluated")
            continue
        refs.append(r)
    diagnostics = []
    for d in diags_t:
        a = d.get("address", "")
        if a and a not in final:
            continue
        if a in filled_paths and d.get("path", "") in filled_paths[a] and d["code"] in FILLABLE:
            continue
        if d["code"] == "TF-TFJSON-UNSUPPORTED":
            d = dict(d, level="info", message=d["message"] + "; its blocks are taken from the plan JSON")
        if d["code"] == "TF-UNRESOLVED-VARS":
            continue
        if a in masked_paths and under_any(masked_paths[a], d.get("path", "")):
            continue
        diagnostics.append(d)
    for d in reader.diagnostics:
        if d["code"] == "TF-PLAN-LOCALS":
            continue  # locals は .tf で読んでいる
        a = d.get("address", "")
        if a and a in from_tf and d["code"] in ("TF-PLAN-UNKNOWN", "TF-PLAN-DYNAMIC-BLOCK", "TF-PLAN-SENSITIVE"):
            continue  # 値と参照の位置は .tf のもの
        diagnostics.append(d)
    diagnostics += sens_diags
    mismatch = block_mismatch(tf_raw["resources"], p_res)
    if mismatch:
        diagnostics.append({"level": "warn", "code": "TF-PLAN-MISMATCH", "address": "", "path": "",
                            "message": mismatch + "; the plan and the .tf folder probably do not match"})
    dropped = sorted(a for a in t_res if a not in final)
    if dropped:
        diagnostics.append({"level": "info", "code": "TF-PLAN-NOT-PLANNED", "address": "", "path": "",
                            "message": f"{len(dropped)} resource(s) read from the .tf are not in the plan and are "
                                       f"not written: {', '.join(dropped[:20])}" + (" …" if len(dropped) > 20 else "")})
    ev = json.loads(json.dumps(tf_raw["evaluation"]))
    ev.setdefault("assumptions", []).append(assumption(plan) + "; file, props and reference positions are from the .tf")
    raw = dict(tf_raw, evaluation=ev, resources=out_res, references=dedupe_refs(props_consistent(out_res, refs)),
               diagnostics=list({ir_raw.diag_key(d) + (d["message"],): d for d in diagnostics}.values()))
    return ir_raw.canonical_raw(raw)
