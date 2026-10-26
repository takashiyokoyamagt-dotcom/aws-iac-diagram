"""raw IR の組み立て: テンプレート（か cdk.out）を読んで StackEval を走らせ、references・diagnostics をまとめる。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from aws_iac_diagram.adapters.cloudformation.cdk import cdk_stacks
from aws_iac_diagram.adapters.cloudformation.loader import load_template
from aws_iac_diagram.adapters.cloudformation.marks import strip_internal
from aws_iac_diagram.adapters.cloudformation.model import Context
from aws_iac_diagram.adapters.cloudformation.refs import dedupe_refs
from aws_iac_diagram.adapters.cloudformation.stack import StackEval
from aws_iac_diagram.core import ir_raw


def build_raw(input_path: Path, root_base: Path | None = None, parameters: dict | None = None) -> dict:
    """テンプレート1つ（ネストスタックを含む）か、cdk.out（ディレクトリか manifest.json）から raw IR を作る。

    parameters: 外から渡すパラメータの値（--param、--param-file）。最上位のスタックに渡す。
    AWS:: で始まる名前（AWS::Region など）は、条件の評価にだけ使う（props は $pseudo のまま）。
    """
    parameters = dict(parameters or {})
    pseudo = {k: v for k, v in parameters.items() if k.startswith("AWS::")}
    given = {k: v for k, v in parameters.items() if not k.startswith("AWS::")}
    if input_path.is_dir() or input_path.name == "manifest.json":
        cdk_dir = input_path if input_path.is_dir() else input_path.parent
        ctx = Context(cdk_dir)
        ctx.pseudo_values = pseudo
        # Export の名前の AWS::StackName は、address に使う名前ではなく本当の stackName で解く
        tops = [StackEval(ctx, load_template(p), p, prefix=f"{name}::", asset_dir=asm, stack_name=real, given=given)
                for name, p, asm, real in cdk_stacks(cdk_dir, ctx.diagnostics)]
        root_path = cdk_dir
    else:
        ctx = Context(input_path.parent)
        ctx.pseudo_values = pseudo
        tops = [StackEval(ctx, load_template(input_path), input_path, given=given)]
        root_path = input_path
    unused = sorted(set(given) - {k for s in tops for k in s.parameters})
    for k in unused:
        ctx.diagnostics.append({"level": "info", "code": "CFN-PARAM-UNUSED", "address": "", "path": "",
                                "message": f"parameter {k} is given but not defined in the template"})
    for s in tops:
        s.register_exports()
    # 子のスタックの Export も使えるように、最上位のリソースを読む前に子をすべて展開する
    for s in tops:
        ctx.active_files.append(s.path.resolve())
        for logical_id in list(s.resources):
            if s.is_stack(logical_id):
                s.child(logical_id)
        ctx.active_files.pop()
    for s in tops:
        s.run()
    conditions = {}
    for s in ctx.stacks:
        for name in s.conditions:
            s.current = s.where()
            conditions[s.prefix + str(name)] = s.condition(name, f"Conditions.{name}")
    refs = dedupe_refs(ctx.refs + [r for s in ctx.stacks for r in s.extra_refs])
    root_base = root_base or Path.cwd()
    try:
        root = Path(os.path.relpath(root_path.resolve(), root_base.resolve())).as_posix()
    except ValueError:  # Windows でドライブが違うと相対パスにできない
        root = root_path.resolve().as_posix()
        ctx.diagnostics.append({"level": "info", "code": "CFN-ABSOLUTE-ROOT", "address": "", "path": "",
                                "message": "root is on another drive; written as an absolute path"})
    # 同じ診断（同じ場所・同じ内容）は1つにまとめる
    diagnostics = list({(d.get("address", ""), d.get("path", ""), d["code"], d["message"]): d
                        for d in ctx.diagnostics}.values())
    used = {}
    for s in ctx.stacks:
        for k, v in s.param_values.items():
            used[s.prefix + k] = strip_internal(v)
    raw = {
        "ir_version": "1.0",
        "stage": "raw",
        "format": "cfn",
        "root": root,
        "evaluation": {"parameters": dict(sorted(used.items())), "conditions": dict(sorted(conditions.items())),
                       "assumptions": ctx.assumptions},
        "resources": ctx.resources,
        "references": refs,
        "diagnostics": diagnostics,
    }
    return ir_raw.canonical_raw(raw)

def dump(raw: dict) -> str:
    return json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
