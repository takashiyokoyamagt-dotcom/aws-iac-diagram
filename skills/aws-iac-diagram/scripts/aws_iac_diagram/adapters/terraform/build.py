"""ルートモジュールのフォルダ（と、あれば plan JSON）から raw IR を作る（build_raw・build_from_plan）。変数のファイルの探し方。
"""
from __future__ import annotations

import json
from pathlib import Path

from aws_iac_diagram.adapters.terraform.evaluator.functions import Unknown
from aws_iac_diagram.adapters.terraform.model import Context
from aws_iac_diagram.adapters.terraform.module_eval import ModuleEval
from aws_iac_diagram.adapters.terraform.plan import reader as P
from aws_iac_diagram.adapters.terraform.refs import dedupe_refs
from aws_iac_diagram.core import ir_raw


def auto_var_files(input_dir: Path) -> list[Path]:
    """Terraform が自動で読む変数のファイル（terraform.tfvars、terraform.tfvars.json、*.auto.tfvars(.json) の名前順）。"""
    out = [input_dir / n for n in ("terraform.tfvars", "terraform.tfvars.json") if (input_dir / n).is_file()]
    autos = sorted(p for p in input_dir.iterdir() if p.is_file()
                   and (p.name.endswith(".auto.tfvars") or p.name.endswith(".auto.tfvars.json")))
    return out + autos


def var_file_candidates(input_dir: Path) -> list[Path]:
    """自動では読まれない変数のファイル（ルートとその1つ下のフォルダの *.tfvars・*.tfvars.json）。"""
    out = []
    dirs = [input_dir] + sorted(p for p in input_dir.iterdir() if p.is_dir() and not p.name.startswith("."))
    for d in dirs:
        for p in sorted(d.iterdir()):
            name = p.name
            if not p.is_file() or name.startswith("."):
                continue
            if not (name.endswith(".tfvars") or name.endswith(".tfvars.json")):
                continue
            if d == input_dir and (name in ("terraform.tfvars", "terraform.tfvars.json")
                                   or name.endswith((".auto.tfvars", ".auto.tfvars.json"))):
                continue
            out.append(p)
    return out


def resolve_var_file(path: Path, input_dir: Path) -> Path:
    """--var-file のパス。相対パスは作業中のフォルダから、無ければ --input のフォルダから。"""
    if path.is_absolute() or path.is_file():
        return path
    alt = input_dir / path
    return alt if alt.is_file() else path


def build_raw(input_dir: Path, root_base: Path | None = None, var_files: list | None = None,
              vars: dict | None = None, var_args: list | None = None, redact_vars=(),
              plan: Path | None = None, workspace: str = "default") -> dict:
    """ルートモジュールのフォルダから raw IR を作る。

    workspace: terraform.workspace の値（--workspace。既定は "default"）。

    var_files・vars: 外から渡す変数の値（--var-file、--var）。この順に（vars が後で）重ねる。
    var_args: コマンドラインの順のまま渡すとき。("file", パス) と ("var", "K=V") の並び（var_files・vars より後）。
    plan: 同じ構成の plan JSON（--plan）。変数の値は plan の variables を使い（var_files・vars・var_args はその後に
    重ねる）、address と作られるかは plan に合わせる（adapters/terraform/tf_plan.py の combine。ir-schema.md の 7.2）。
    """
    plan_doc = P.load_plan(plan) if plan is not None else None
    ctx = Context(input_dir, workspace)
    mod = ModuleEval(ctx, input_dir)
    mod.chain = (input_dir.resolve(),)
    mod.load()
    sources: list = [("file", p) for p in auto_var_files(input_dir)]
    if plan_doc is not None:
        sources += [("plan", (k, v)) for k, v in sorted(P.plan_variables(plan_doc).items())]
    sources += [("file", resolve_var_file(Path(p), input_dir)) for p in (var_files or [])]
    sources += [("value", (k, v)) for k, v in (vars or {}).items()]
    for kind, item in var_args or []:
        sources.append(("file", resolve_var_file(Path(item), input_dir)) if kind == "file" else ("var", item))
    for kind, item in sources:
        if kind == "file" and not Path(item).is_file():
            raise ValueError(f"変数のファイルがありません: {item}")
    mod.setup_variables(sources, redact_vars)
    missing = sorted(n for n, v in mod.var_values.items() if isinstance(v, Unknown) and v.code == "TF-UNRESOLVED-VAR")
    if missing:
        # 環境ごとの変数のファイル（env/dev.tfvars など）があれば、どれを渡すかを確かめられるように候補を書く（A4）
        read = {Path(item).resolve() for kind, item in sources if kind == "file"}
        cands = sorted(ctx.rel(p) for p in var_file_candidates(input_dir) if p.resolve() not in read)
        message = f"variables without a value: {', '.join(missing)}"
        if cands:
            message += f"; var files that are not read automatically (pass one with --var-file): {', '.join(cands)}"
        ctx.diagnostics.append({"level": "info", "code": "TF-UNRESOLVED-VARS", "address": "", "path": "",
                                "message": message})
    mod.run()
    # Windows でドライブが違うと相対パスにできない: フォルダの名前だけを書く（絶対パスは書かない。plan JSON だけの
    # ときと同じ規則）
    root, relative = P.root_text(input_dir, root_base or Path.cwd())
    if not relative:
        ctx.diagnostics.append({"level": "info", "code": "TF-ROOT-OTHER-DRIVE", "address": "", "path": "",
                                "message": P.ROOT_OTHER_DRIVE_MESSAGE})
    diagnostics = list({(d.get("address", ""), d.get("path", ""), d["code"], d["message"]): d
                        for d in ctx.diagnostics}.values())
    # 変数の値は書かない（名前と値の出どころだけ。秘密の値を IR に残さないため）。手元のモジュールの変数は
    # module.x.<名前> の形で足す（要約表の変数は書かない）
    used = dict(mod.var_sources)
    for child in ctx.modules:
        if child.via is None:
            used.update({child.prefix + n: e for n, e in child.var_sources.items()})
    used = dict(sorted(used.items()))
    raw = {
        "ir_version": "1.0",
        "stage": "raw",
        "format": "tf",
        "root": root,
        "evaluation": {"var_files": mod.var_files, "vars": used, "assumptions": ctx.assumptions},
        "resources": ctx.resources,
        "references": dedupe_refs(ctx.refs),
        "diagnostics": diagnostics,
    }
    if plan is not None:
        return P.combine(raw, plan, input_dir, root_base, plan_doc)
    return ir_raw.canonical_raw(raw)


def build_from_plan(plan: Path, root_base: Path | None = None) -> dict:
    """plan JSON だけから raw IR を作る（--input に plan JSON を渡したとき。adapters/terraform/tf_plan.py）。"""
    return P.build_plan_raw(plan, root_base)


def dump(raw: dict) -> str:
    return json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
