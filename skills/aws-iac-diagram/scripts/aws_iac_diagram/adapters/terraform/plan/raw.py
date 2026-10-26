"""plan JSON だけから raw IR を作る（read_plan・build_plan_raw）。.tf と合わせるときの入口で使う plan の変数と root の書き方。
"""
from __future__ import annotations

import os
from pathlib import Path

from aws_iac_diagram.adapters.terraform.plan.consistency import drop_missing, props_consistent
from aws_iac_diagram.adapters.terraform.plan.diagnostics import ROOT_OTHER_DRIVE_MESSAGE
from aws_iac_diagram.adapters.terraform.plan.read import PlanError, load_plan, version_text
from aws_iac_diagram.adapters.terraform.plan.reader import PlanReader
from aws_iac_diagram.adapters.terraform.refs import dedupe_refs
from aws_iac_diagram.core import ir_raw


def assumption(plan: dict) -> str:
    return (f"read from a terraform plan JSON (terraform {version_text(plan.get('terraform_version'))}, format "
            f"{version_text(plan.get('format_version'))}); addresses, count/for_each and values are Terraform's")


def root_text(path: Path, root_base: Path) -> tuple[str, bool]:
    """raw IR の root（root_base からの相対パス）。ドライブが違うときは相対パスにできないので、名前だけ
    （絶対パスは書かない）。plan だけのときも .tf と合わせるときも同じ規則。2つ目は相対パスにできたか。"""
    try:
        return Path(os.path.relpath(path.resolve(), root_base.resolve())).as_posix(), True
    except ValueError:  # Windows でドライブが違う
        return path.resolve().name or ".", False


def read_plan(plan: dict, file_name: str) -> "PlanReader":
    """PlanReader を作って読み込む。想定外の形は PlanError にする（値や絶対パスは書かない）。"""
    try:
        reader = PlanReader(plan, file_name)
        reader.run()
        return reader
    except PlanError:
        raise
    except RecursionError as e:
        raise PlanError("入れ子が深すぎます") from e
    except (KeyError, TypeError, AttributeError, IndexError, ValueError) as e:
        raise PlanError(f"unexpected structure in the plan JSON ({type(e).__name__})") from e


def build_plan_raw(plan_path: Path, root_base: Path | None = None) -> dict:
    """plan JSON だけから raw IR を作る（--input <plan JSON>）。"""
    plan = load_plan(plan_path)
    reader = read_plan(plan, plan_path.name)
    root, relative = root_text(plan_path, root_base or Path.cwd())
    if not relative:
        reader.diag("info", "TF-ROOT-OTHER-DRIVE", "", "", ROOT_OTHER_DRIVE_MESSAGE)
    root_cfg = (plan.get("configuration") or {}).get("root_module") or {}
    vars_ = {}
    for name, spec in sorted((root_cfg.get("variables") or {}).items()):
        spec = spec or {}
        e = {"source": "plan" if name in reader.root_vars else ("default" if "default" in spec else None)}
        if spec.get("sensitive"):
            e["hidden"] = "sensitive"
        elif spec.get("ephemeral"):
            e["hidden"] = "ephemeral"
        vars_[name] = e
    vars_.update(reader.module_vars())
    diagnostics = list({ir_raw.diag_key(d) + (d["message"],): d for d in reader.diagnostics}.values())
    known = {r["address"] for r in reader.resources}
    for r in reader.resources:
        r["props"] = drop_missing(r["props"], known)
    raw = {
        "ir_version": "1.0", "stage": "raw", "format": "tf", "root": root,
        "evaluation": {"var_files": [], "vars": dict(sorted(vars_.items())), "assumptions": [assumption(plan)]},
        "resources": reader.resources,
        "references": dedupe_refs(props_consistent(reader.resources, reader.refs)),
        "diagnostics": diagnostics,
    }
    return ir_raw.canonical_raw(raw)


def plan_variables(plan: dict) -> dict:
    """ルートの変数の値（plan の variables）。.tf と合わせるときに --var の代わりに渡す。"""
    return {k: (v or {}).get("value") for k, v in (plan.get("variables") or {}).items()}
