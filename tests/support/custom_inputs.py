"""自作の構成 5 種（aws-iac-diagram-workspace/fixtures/tf・cfn）の raw IR を、正解 IR を書いたときの変数・パラメータで作る。

正規化のテスト（tests/integration/normalize/）が、10 入力（5 構成 × TF／CFN）を同じ作り方で読むための 1 か所。値の決め方は
アダプタの正解 IR のテスト（tests/integration/terraform/test_expected_ir.py・cloudformation/test_expected_ir.py）と同じ:
three-tier の TF は `env/dev.tfvars`、vpc-endpoints の CFN は `parameters.json`、ほかは正解 IR の `evaluation.cfn.parameters` と既定値。
"""
from __future__ import annotations

import json

from support.paths import EXPECTED, FIXTURES_CFN, FIXTURES_TF, WS
from aws_iac_diagram.adapters.cloudformation import build as cfn_build, params as cfn_params  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402

NAMES = ("three-tier", "three-tier-modules", "serverless-api", "rag", "vpc-endpoints")
TF_VAR_FILES = {"three-tier": ["env/dev.tfvars"]}
CFN_INPUTS = {
    "three-tier": ("three-tier/template.yaml", None),
    "serverless-api": ("serverless-api/template.yaml", None),
    "vpc-endpoints": ("vpc-endpoints/template.json", "vpc-endpoints/parameters.json"),
    "rag": ("rag/template.yaml", None),
    "three-tier-modules": ("three-tier-modules/root.yaml", None),
}


def expected_ir(name: str) -> dict:
    return json.loads((EXPECTED / f"{name}.ir.json").read_text(encoding="utf-8"))


def custom_raw(name: str, fmt: str) -> dict:
    """自作の構成 name の、形式 fmt（tf／cfn）の raw IR。"""
    if fmt == "tf":
        root = FIXTURES_TF / name
        return tf_build.build_raw(root, WS, var_files=[root / f for f in TF_VAR_FILES.get(name, [])])
    tpl, pfile = CFN_INPUTS[name]
    params = dict(expected_ir(name).get("evaluation", {}).get("cfn", {}).get("parameters", {}))
    if pfile:
        params.update(cfn_params.load_parameter_file(FIXTURES_CFN / pfile))
    return cfn_build.build_raw(FIXTURES_CFN / tpl, WS, params)
