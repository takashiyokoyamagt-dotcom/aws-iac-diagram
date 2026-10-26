"""CloudFormation アダプタ: SAM（Transform の Globals と暗黙の API。sam.py）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs
from support.cloudformation import build
from support.paths import FIXTURES_CFN as FIXTURES, ROOT
from aws_iac_diagram.adapters.cloudformation import build as cfn_build  # noqa: E402


class SamTest(unittest.TestCase):
    def test_globals_and_implicit_apis(self):
        raw = build("""
Transform: AWS::Serverless-2016-10-31
Globals:
  Function:
    Runtime: python3.13
    Environment:
      Variables: {STAGE: dev}
    Layers: [arn:aws:lambda:::layer:a]
Resources:
  Table:
    Type: AWS::Serverless::SimpleTable
  Fn:
    Type: AWS::Serverless::Function
    Properties:
      Runtime: python3.12
      Environment:
        Variables: {TABLE: !Ref Table}
      Layers: [arn:aws:lambda:::layer:b]
      Events:
        Rest: {Type: Api, Properties: {Path: /x, Method: get}}
        Http: {Type: HttpApi}
""")
        p = props(raw, "Fn")
        self.assertEqual(p["Runtime"], "python3.12")  # 値はリソースの方
        self.assertEqual(p["Environment"]["Variables"], {"STAGE": "dev", "TABLE": {"$res": "Table", "attr": None}})
        self.assertEqual(p["Layers"], ["arn:aws:lambda:::layer:a", "arn:aws:lambda:::layer:b"])
        implicit = {r["address"]: r for r in raw["resources"] if r.get("implicit")}
        self.assertEqual(implicit["ServerlessRestApi"]["type"], "AWS::Serverless::Api")
        self.assertEqual(implicit["ServerlessHttpApi"]["type"], "AWS::Serverless::HttpApi")
        assert_valid(self, raw)

    def test_globals_do_not_merge_into_intrinsics_and_apply_to_implicit_api(self):
        # 第三者レビューの M4
        raw = build("""
Transform: AWS::Serverless-2016-10-31
Conditions:
  C: !Equals [a, b]
Globals:
  Function:
    Environment:
      Variables: {STAGE: dev}
  Api:
    EndpointConfiguration: PRIVATE
Resources:
  Q: {Type: AWS::SQS::Queue}
  Fn:
    Type: AWS::Serverless::Function
    Properties:
      Environment: !If [C, {Variables: {X: !Ref Q}}, !Ref AWS::NoValue]
      Events:
        Rest: {Type: Api, Properties: {Path: /x, Method: get}}
  Sm:
    Type: AWS::Serverless::StateMachine
    Properties:
      Events:
        Rest: {Type: Api, Properties: {Path: /y, Method: post}}
""")
        p = props(raw, "Fn")
        # !If は1つの値として扱い Globals を混ぜない。条件 C は偽なので AWS::NoValue が選ばれ、Environment ごと消える
        self.assertNotIn("Environment", p)
        self.assertIn(("Fn", "Properties.Environment", "Q", None, "Ref", "pruned"), refs(raw, "Fn"))
        api = next(r for r in raw["resources"] if r["address"] == "ServerlessRestApi")
        self.assertEqual(api["props"], {"EndpointConfiguration": "PRIVATE"})
        self.assertEqual(len([r for r in raw["resources"] if r.get("implicit")]), 1)
        assert_valid(self, raw)

    def test_explicit_api_has_no_implicit(self):
        raw = cfn_build.build_raw(FIXTURES / "serverless-api" / "template.yaml", ROOT / "aws-iac-diagram-workspace")
        self.assertFalse([r for r in raw["resources"] if r.get("implicit")])


if __name__ == "__main__":
    unittest.main()
