"""CloudFormation アダプタ × cfn-lint のグラフ（CRITERIA の 1.6、C1）の回帰テスト。
照合は aws-iac-diagram-workspace/tools/c1_check.py（フェーズ1 の手順5）。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.cloudformation import write_files
from support.paths import FIXTURES_CFN as FIXTURES, ROOT


class CfnLintGraphTest(unittest.TestCase):
    """CRITERIA の 1.6（C1）の回帰テスト。照合は aws-iac-diagram-workspace/tools/c1_check.py（フェーズ1 の手順5）。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "aws-iac-diagram-workspace" / "tools"))
        import c1_check
        cls.c1 = c1_check

    def test_fixture_templates(self):
        # 自作 fixture の5構成（three-tier-modules は root から子5つを展開して照合する）
        tops = ["three-tier/template.yaml", "serverless-api/template.yaml", "vpc-endpoints/template.json",
                "rag/template.yaml", "three-tier-modules/root.yaml"]
        edges = {}
        for t in tops:
            r = self.c1.check_input(FIXTURES / t)
            with self.subTest(t):
                self.assertEqual(r["unmatched"], [])
            edges[t] = r["edges"]
        self.assertEqual(edges["three-tier-modules/root.yaml"], 53)  # 第三者レビューで数えた辺（root と子5つ）
        self.assertEqual(sum(edges.values()), 214)

    def test_each_child_template_alone(self):
        # 子テンプレートを単独で読んでも、対応の無い辺は無い
        for t in sorted((FIXTURES / "three-tier-modules").glob("*.yaml")):
            with self.subTest(t.name):
                self.assertEqual(self.c1.check_input(t)["unmatched"], [])

    def test_public_nested_stacks(self):
        public = ROOT / "aws-iac-diagram-workspace" / "fixtures" / "public"
        vpcp = public / "aws-cloudformation-templates" / "Solutions" / "VPCPeering" / "templates"
        cases = {  # 第三者レビュー（2026-10-17）で数えた辺の数
            public / "ecs-refarch-cloudformation" / "master.yaml": 90,
            public / "amazon-cloudfront-secure-static-site" / "templates" / "main.yaml": 18,
            vpcp / "VPCPeering-Requester.main.cfn.yaml": 1,
            vpcp / "VPCPeering-Requester.main.cfn.json": 1,
            vpcp / "VPCPeering-Accepter.main.cfn.yaml": 5,
        }
        for top, n in cases.items():
            with self.subTest(top.name):
                r = self.c1.check_input(top)
                self.assertEqual(r["unmatched"], [])
                self.assertEqual(r["edges"], n)

    def test_after_transform_globals_and_foreach(self):
        # cfn-lint --build-graph と同じく、変換（SAM の Globals、Fn::ForEach）の後のグラフで照合する（レビューの M1）
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_files(tmp, {
                "sam.yaml": """
                    Transform: AWS::Serverless-2016-10-31
                    Globals:
                      Function:
                        Environment:
                          Variables: {T: !Ref Topic}
                    Resources:
                      Topic: {Type: AWS::SNS::Topic}
                      F:
                        Type: AWS::Serverless::Function
                        Properties: {Runtime: python3.13, Handler: app.handler, InlineCode: x}
                    """,
                "foreach.yaml": """
                    Transform: AWS::LanguageExtensions
                    Resources:
                      T: {Type: AWS::SNS::Topic}
                      "Fn::ForEach::Q":
                        - N
                        - [a, b]
                        - "Q${N}":
                            Type: AWS::SQS::Queue
                            Properties: {Tags: [{Key: t, Value: !Ref T}]}
                    """,
            })
            sam = self.c1.check_input(tmp / "sam.yaml")
            fe = self.c1.check_input(tmp / "foreach.yaml")
        self.assertEqual((sam["edges"], sam["unmatched"]), (1, []))
        self.assertEqual((fe["edges"], fe["unmatched"]), (2, []))

    def test_discover_includes_all_required_inputs(self):
        # CRITERIA の 1.6 の対象（C01〜C05、SAM 版、自作 fixture）が、探した入力にすべて含まれる（レビューの R1）
        self.assertEqual(self.c1.missing_required(self.c1.discover()), [])

    def test_fixture_edge_counts(self):
        # cfn-lint の挙動が変わったら気づけるように、辺の数を固定する
        counts = {"three-tier/template.yaml": 60, "serverless-api/template.yaml": 14,
                  "vpc-endpoints/template.json": 56, "rag/template.yaml": 31}
        for t, n in counts.items():
            with self.subTest(t):
                self.assertEqual(self.c1.check_input(FIXTURES / t)["edges"], n)

    def test_address_prefix(self):
        ap = self.c1.address_prefix
        self.assertEqual(ap("Vpc"), "")
        self.assertEqual(ap("NetworkStack/Vpc"), "NetworkStack/")
        self.assertEqual(ap("A/B/Vpc"), "A/B/")
        self.assertEqual(ap("App::Vpc"), "App::")
        self.assertEqual(ap("App::Child/Queue"), "App::Child/")
        self.assertEqual(ap("Queue*"), "")

    def test_prefix_match(self):
        pm = self.c1.prefix_match
        self.assertTrue(pm("Properties.Policy", "Properties.Policy.Statement[0]"))
        self.assertTrue(pm("Properties.A[0]", "Properties.A"))
        self.assertFalse(pm("Properties.Ab", "Properties.A"))


if __name__ == "__main__":
    unittest.main()
