"""plan JSON のテスト（tests/unit/terraform/plan/ と tests/integration/terraform/）が共有する道具。

コミットした plan JSON の読み出し（CASES、EDGE、combined_raw）と、小さな plan JSON を組み立てる関数（rc・cfg・mkplan …）。
値はすべて偽（"hunter2-LEAK" など。漏れたら文字列で見つかるように、目立つ形にしてある）。
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from support.builders import res_of
from support.paths import FIXTURES_TF as FIXTURES, PLANS, WS
import adapt_tf
import validate_ir as v
from aws_iac_diagram.adapters.terraform import build as tf_build
from aws_iac_diagram.adapters.terraform.plan import values as PV
from aws_iac_diagram.core import ir_raw


# plan JSON → (.tf のフォルダ, 正解 IR, plan を作ったときの変数のファイル)
CASES = {
    "three-tier.dev": ("three-tier", "three-tier", ["env/dev.tfvars"]),
    "three-tier.prod": ("three-tier", None, ["env/prod.tfvars"]),
    "serverless-api": ("serverless-api", "serverless-api", []),
    "vpc-endpoints": ("vpc-endpoints", "vpc-endpoints", []),
    "rag": ("rag", "rag", []),
    "three-tier-modules": ("three-tier-modules", "three-tier-modules", []),
}

EDGE = PLANS / "edge"

EDGE_PLAN = PLANS / "edge.json"


def combined_raw(name: str) -> dict:
    return tf_build.build_raw(FIXTURES / CASES[name][0], WS, plan=PLANS / f"{name}.json")


def assert_valid_no_errors(test: unittest.TestCase, raw: dict) -> None:
    test.assertEqual(v.schema_errors(raw), [])
    test.assertEqual(ir_raw.semantic_errors(raw), [])
    test.assertFalse([d for d in raw["diagnostics"] if d["level"] == "error"])


# ------------------------------------------------------------------ 小さな plan JSON を組み立てる（以降のテスト用）
# 値はすべて偽（"hunter2-LEAK" など。漏れたら文字列で見つかるように、目立つ形にしてある）
SECRET = "hunter2-LEAK"

SECRET2 = "tok-LEAK2"

AWS_PROVIDER = {"aws": {"name": "aws", "expressions": {"region": {"constant_value": "ap-northeast-1"}}}}


def rc(address, after, sens=None, unknown=None, actions=("create",), mode="managed", **extra):
    typ = address.split(".")[-2] if mode == "data" else address.split(".")[0]
    d = {"address": address, "mode": mode, "type": typ, "name": address.split(".")[-1],
         "provider_config_key": "aws",
         "change": {"actions": list(actions), "before": None, "after": after, "after_unknown": unknown or {},
                    "after_sensitive": sens if sens is not None else {}}}
    d.update(extra)
    return d


def cfg(address, exprs, **extra):
    mode = "data" if address.startswith("data.") else "managed"
    parts = address.split(".")
    d = {"address": address, "mode": mode, "type": parts[1] if mode == "data" else parts[0], "name": parts[-1],
         "provider_config_key": "aws", "expressions": exprs}
    d.update(extra)
    return d


def const(v):
    return {"constant_value": v}


def refs(*r):
    return {"references": list(r)}


def mkplan(changes=(), configs=(), variables=None, prior=None, planned=None, root_extra=None, **top):
    d = {"format_version": "1.2", "terraform_version": "1.9.0", "variables": variables or {},
         "planned_values": planned or {"root_module": {}}, "resource_changes": list(changes),
         "configuration": {"provider_config": AWS_PROVIDER,
                           "root_module": dict({"resources": list(configs)}, **(root_extra or {}))}}
    if prior is not None:
        d["prior_state"] = prior
    d.update(top)
    return d


def write_json(path: Path, doc) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def write_files(folder: Path, files: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def plan_only(tmp: Path, plan: dict, name="plan.json") -> dict:
    return tf_build.build_from_plan(write_json(tmp / name, plan), tmp)


def props_of(raw: dict, address: str) -> dict:
    return res_of(raw, address)["props"]


def diag_codes(raw: dict, code: str) -> list:
    return [(d["address"], d["path"], d["level"]) for d in raw["diagnostics"] if d["code"] == code]


def unk(reason=PV.SENSITIVE_REASON) -> dict:
    return {"$unknown": reason}


class TempTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def run_main(self, args: list) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = adapt_tf.main(args)
        return code, out.getvalue(), err.getvalue()
