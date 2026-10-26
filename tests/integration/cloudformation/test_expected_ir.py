"""CloudFormation アダプタ × 自作 fixture（aws-iac-diagram-workspace/fixtures/cfn）: 正解 IR（expected）の CFN 側の網羅分類と、
raw IR の address・type・file・enabled が一致する（第三者レビューの R4）。fixture のテンプレートがすべて検査を通る raw IR になる。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid
from support.paths import FIXTURES_CFN as FIXTURES, ROOT
from aws_iac_diagram.adapters.cloudformation import (  # noqa: E402
    build as cfn_build,
    loader as cfn_loader,
    params as cfn_params,
)


class ExpectedIrTest(unittest.TestCase):
    """正解 IR（expected）の CFN 側の網羅分類と、raw IR の address・type・file・enabled が一致する（第三者レビューの R4）。"""

    def test_addresses_and_enabled_match_expected(self):
        ws = ROOT / "aws-iac-diagram-workspace"
        cases = {
            "three-tier": ("three-tier/template.yaml", None),
            "serverless-api": ("serverless-api/template.yaml", None),
            "vpc-endpoints": ("vpc-endpoints/template.json", "vpc-endpoints/parameters.json"),
            "rag": ("rag/template.yaml", None),
            "three-tier-modules": ("three-tier-modules/root.yaml", None),
        }
        for name, (tpl, pfile) in cases.items():
            with self.subTest(name):
                expected = json.loads((ws / "expected" / f"{name}.ir.json").read_text(encoding="utf-8"))
                params = dict(expected.get("evaluation", {}).get("cfn", {}).get("parameters", {}))
                if pfile:
                    params.update(cfn_params.load_parameter_file(FIXTURES / pfile))
                raw = cfn_build.build_raw(FIXTURES / tpl, ws, params)
                got = {r["address"]: (r["type"], r["file"], r["enabled"]) for r in raw["resources"]}
                want = {r["address"]: (r["type"], r["file"], r.get("rule") != "H-COND-FALSE")
                        for r in expected["sources"]["cfn"]["resources"]}
                self.assertEqual(got, want)


def count_resources(template: Path) -> int:
    """テンプレートのリソースの数。手元のファイルを指すネストスタックは中身も数える。"""
    n = 0
    for body in (cfn_loader.load_template(template).get("Resources") or {}).values():
        n += 1
        url = (body.get("Properties") or {}).get("TemplateURL")
        if body.get("Type") == "AWS::CloudFormation::Stack" and isinstance(url, str) and "://" not in url:
            n += count_resources(template.parent / url)
    return n


class FixtureTest(unittest.TestCase):
    def test_all_fixture_templates_produce_valid_raw(self):
        # parameters.json（パラメータの値のファイル）はテンプレートではないので除く
        templates = sorted(p for p in FIXTURES.rglob("*") if p.suffix in (".yaml", ".json")
                           and p.name != "parameters.json")
        self.assertGreaterEqual(len(templates), 10)
        for t in templates:
            with self.subTest(t.relative_to(FIXTURES).as_posix()):
                raw = cfn_build.build_raw(t, ROOT / "aws-iac-diagram-workspace")
                assert_valid(self, raw)
                self.assertFalse([d for d in raw["diagnostics"] if d["level"] == "error"])
                self.assertEqual(len(raw["resources"]), count_resources(t))


if __name__ == "__main__":
    unittest.main()
