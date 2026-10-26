"""CloudFormation アダプタ: ネストスタック（ir-schema.md の 7.2〜7.4。nested.py・stack.py）。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs
from support.cloudformation import ref_by, write_files
from support.paths import FIXTURES_CFN as FIXTURES, ROOT
from aws_iac_diagram.adapters.cloudformation import build as cfn_build  # noqa: E402


class NestedStackTest(unittest.TestCase):
    """フェーズ1 の手順3: ネストスタック（ir-schema.md の 7.2〜7.4）。"""

    def test_three_tier_modules(self):
        raw = cfn_build.build_raw(FIXTURES / "three-tier-modules" / "root.yaml", ROOT / "aws-iac-diagram-workspace")
        assert_valid(self, raw)
        self.assertEqual(raw["diagnostics"], [])
        lb = next(r for r in raw["resources"] if r["address"] == "AlbStack/LoadBalancer")
        self.assertEqual(lb["via"], "nested_stack")
        self.assertEqual(lb["file"], "alb.yaml")
        # 親の !Join で渡したサブネットの一覧を、子の List 型のパラメータで分ける
        self.assertEqual(lb["props"]["Subnets"], [{"$res": "NetworkStack/PublicSubnet1", "attr": None},
                                                  {"$res": "NetworkStack/PublicSubnet2", "attr": None}])
        r = ref_by(raw, "AlbStack/LoadBalancer", "Properties.Subnets[0]")[0]
        self.assertEqual(r["through"], ["AlbStack.Parameters.PublicSubnetIds", "NetworkStack.Outputs.PublicSubnetIds"])
        # スタックのリソース自身は、Parameters を分けずに持つ
        stack = next(x for x in raw["resources"] if x["address"] == "AlbStack")
        self.assertIn("$concat", stack["props"]["Parameters"]["PublicSubnetIds"])
        self.assertNotIn("via", stack)
        self.assertEqual(raw["evaluation"]["parameters"]["AlbStack/AppPort"], 8080)

    def test_unreadable_child_is_blackbox_and_url_is_remapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_files(tmp, {
                "main.yaml": """
                    Resources:
                      Net:
                        Type: AWS::CloudFormation::Stack
                        Properties:
                          TemplateURL: https://s3.amazonaws.com/bucket/infra/vpc.yaml
                      Gone:
                        Type: AWS::CloudFormation::Stack
                        Properties:
                          TemplateURL: https://s3.amazonaws.com/bucket/missing.yaml
                      Twice:
                        Type: AWS::CloudFormation::Stack
                        Properties:
                          TemplateURL: https://s3.amazonaws.com/bucket/x/sg.yaml
                      Fn:
                        Type: AWS::Lambda::Function
                        Properties:
                          Vpc: !GetAtt Net.Outputs.VpcId
                          Other: !GetAtt Gone.Outputs.Id
                    """,
                "infra/vpc.yaml": """
                    Resources:
                      Vpc: {Type: AWS::EC2::VPC}
                    Outputs:
                      VpcId: {Value: !Ref Vpc}
                    """,
                "vpc.yaml": "Resources: {Other: {Type: AWS::EC2::VPC}}\n",
                "a/sg.yaml": "Resources: {A: {Type: AWS::EC2::SecurityGroup}}\n",
                "b/sg.yaml": "Resources: {B: {Type: AWS::EC2::SecurityGroup}}\n",
            })
            raw = cfn_build.build_raw(tmp / "main.yaml", tmp)
        assert_valid(self, raw)
        res = {r["address"]: r for r in raw["resources"]}
        # 末尾から最も多く一致する infra/vpc.yaml を読む（vpc.yaml ではない）
        self.assertIn("Net/Vpc", res)
        self.assertNotIn("Net/Other", res)
        self.assertTrue(any("infra/vpc.yaml" in a for a in raw["evaluation"]["assumptions"]))
        # 見つからない・2つ以上一致する子は黒箱
        self.assertEqual(res["Gone"]["via"], "module_blackbox")
        self.assertEqual(res["Twice"]["via"], "module_blackbox")
        self.assertEqual(res["Fn"]["props"]["Vpc"], {"$res": "Net/Vpc", "attr": None})
        self.assertEqual(res["Fn"]["props"]["Other"], {"$res": "Gone", "attr": "Outputs.Id"})
        codes = [(d["address"], d["code"]) for d in raw["diagnostics"]]
        self.assertIn(("Gone", "CFN-NESTED-UNREADABLE"), codes)
        self.assertIn(("Twice", "CFN-NESTED-UNREADABLE"), codes)

    def nested(self, files: dict[str, str]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_files(tmp, files)
            raw = cfn_build.build_raw(tmp / "main.yaml", tmp)
        assert_valid(self, raw)
        return raw

    def test_output_that_cannot_be_evaluated_keeps_references(self):
        # 第三者レビューの M1: 出力が Fn::If（手順4 まで評価しない）や文字列でも、参照を失わない
        raw = self.nested({
            "main.yaml": """
                Resources:
                  Kid:
                    Type: AWS::CloudFormation::Stack
                    Properties: {TemplateURL: kid.yaml}
                  Fn:
                    Type: AWS::Lambda::Function
                    Properties:
                      A: !GetAtt Kid.Outputs.Arn
                      B: !GetAtt Kid.Outputs.Literal
                """,
            "kid.yaml": """
                Parameters:
                  Mode: {Type: String}
                Conditions:
                  C: !Equals [!Ref Mode, x]
                Resources:
                  Q: {Type: AWS::SQS::Queue}
                  T: {Type: AWS::SNS::Topic}
                Outputs:
                  Arn: {Value: !If [C, !GetAtt Q.Arn, !Ref T]}
                  Literal: {Value: fixed}
                """})
        r = refs(raw, "Fn")
        self.assertIn(("Fn", "Properties.A", "Kid/Q", "Arn", "GetAtt", "unevaluated"), r)
        self.assertIn(("Fn", "Properties.A", "Kid/T", None, "Ref", "unevaluated"), r)
        self.assertIn(("Fn", "Properties.A", "Kid", "Outputs.Arn", "GetAtt", "unevaluated"), r)
        self.assertIn(("Fn", "Properties.B", "Kid", "Outputs.Literal", "GetAtt", "unevaluated"), r)
        moved = [x for x in raw["references"] if x["from"] == "Fn" and x["to"] == "Kid/Q"][0]
        self.assertEqual(moved["through"], ["Kid.Outputs.Arn"])
        self.assertTrue(any(d["address"] == "Kid" and d["path"] == "Outputs.Arn" for d in raw["diagnostics"]))

    def test_condition_on_parent_stack_is_inherited(self):
        raw = self.nested({
            "main.yaml": """
                Parameters:
                  Mode: {Type: String}
                Conditions:
                  Maybe: !Equals [!Ref Mode, on]
                  Never: !Equals [a, b]
                Resources:
                  Kid:
                    Type: AWS::CloudFormation::Stack
                    Condition: Maybe
                    Properties: {TemplateURL: kid.yaml}
                  Off:
                    Type: AWS::CloudFormation::Stack
                    Condition: Never
                    Properties: {TemplateURL: kid.yaml}
                """,
            "kid.yaml": "Resources: {Q: {Type: AWS::SQS::Queue}}\n"})
        res = {r["address"]: r for r in raw["resources"]}
        self.assertIsNone(res["Kid"]["enabled"])
        self.assertIsNone(res["Kid/Q"]["enabled"])
        self.assertFalse(res["Off"]["enabled"])
        self.assertFalse(res["Off/Q"]["enabled"])

    def test_single_item_join_into_list_parameter(self):
        raw = self.nested({
            "main.yaml": """
                Resources:
                  Sub1: {Type: AWS::EC2::Subnet}
                  Kid:
                    Type: AWS::CloudFormation::Stack
                    Properties:
                      TemplateURL: kid.yaml
                      Parameters:
                        S: !Join [",", [!Ref Sub1]]
                """,
            "kid.yaml": """
                Parameters:
                  S: {Type: "List<AWS::EC2::Subnet::Id>"}
                Resources:
                  I:
                    Type: AWS::EC2::Instance
                    Properties: {SubnetId: !Select [0, !Ref S]}
                """})
        self.assertEqual(props(raw, "Kid/I")["SubnetId"], {"$res": "Sub1", "attr": None})

    def test_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_files(tmp, {"loop.yaml": """
                Resources:
                  Self:
                    Type: AWS::CloudFormation::Stack
                    Properties: {TemplateURL: loop.yaml}
                """})
            raw = cfn_build.build_raw(tmp / "loop.yaml", tmp)
        self.assertIn("CFN-NESTED-CYCLE", [d["code"] for d in raw["diagnostics"]])
        assert_valid(self, raw)


if __name__ == "__main__":
    unittest.main()
