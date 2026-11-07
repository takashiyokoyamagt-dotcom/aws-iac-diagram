"""網羅分類の独立の照合（aws-iac-diagram-workspace/tools/check_coverage.py。X4）を、正規化の出力に当てる（設計草案の 6 章の手順 3）。

check_coverage.py は入力（fixture の .tf・テンプレート）を正規化を通さずに数え、IR の `sources` と突き合わせる。正規化の出力
（自作の構成 5 種 × TF／CFN）が通ること、網羅分類の漏れ・重複・余りをわざと作ると落ちることを確かめる。
"""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.custom_inputs import NAMES, custom_raw
from support.paths import PUBLIC
from support.tools import load_tool  # noqa: E402
from aws_iac_diagram.normalize import build  # noqa: E402

cov = load_tool("check_coverage")


class CheckCoverageOnNormalizedTest(unittest.TestCase):
    def test_normalized_outputs_pass(self):
        for name in NAMES:
            for fmt in ("tf", "cfn"):
                with self.subTest(name, fmt=fmt):
                    ir = build.normalize(custom_raw(name, fmt), None, name)
                    results = cov.check_ir(ir)
                    self.assertEqual([f for f, *_ in results], [fmt])
                    self.assertEqual(results[0][2], [], results[0][2])

    def test_mutations_fail(self):
        ir = build.normalize(custom_raw("three-tier", "tf"), None, "three-tier")
        res = ir["sources"]["tf"]["resources"]
        cases = {
            "重複": lambda r: r.append(copy.deepcopy(r[0])),
            "漏れ": lambda r: r.pop(0),
            "余り": lambda r: r.append({"address": "aws_s3_bucket.nowhere", "type": "aws_s3_bucket", "file": "main.tf", "class": "unknown"}),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                bad = copy.deepcopy(ir)
                mutate(bad["sources"]["tf"]["resources"])
                errs = cov.check_ir(bad)[0][2]
                self.assertTrue(errs, label)
        self.assertTrue(res)


class InventoryOfPublicSamplesTest(unittest.TestCase):
    """公開サンプルの一巡（手順 6）で見つかった、独立の数え方の不足（直したもの）。"""

    def test_url_template_urls_are_followed_only_for_x4(self):
        # C05・C04 のネストスタックの TemplateURL は S3 の URL。X4 の照合（follow_urls=True）では CFN アダプタと同じく
        # 「URL のパスの末尾が一致する手元のファイル」を読む（SELECTION.md の 4 の 2）。survey_public.py の数（SELECTION.md の表）は変えない
        inv = load_tool("iac_inventory")
        top = PUBLIC / "ecs-refarch-cloudformation" / "master.yaml"
        plain = {r.logical_id for r in inv.cfn_inventory(top)}
        followed = {r.logical_id: r for r in inv.cfn_inventory(top, follow_urls=True)}
        self.assertEqual(len(plain), 7)
        self.assertEqual(len(followed), 63)
        self.assertEqual(followed["VPC/VPC"].file, "infrastructure/vpc.yaml")
        self.assertEqual(followed["ProductService/Service"].file, "services/product-service/service.yaml")
        # Fn::Sub の URL（`${S3KeyPrefix}templates/…`）は `}` より後ろで比べる
        acc = PUBLIC / "aws-cloudformation-templates/Solutions/VPCPeering/templates/VPCPeering-Accepter.main.cfn.yaml"
        self.assertIn("VPCPeeringAccepterTagStack/TagVpcPeeringConnectionsResource",
                      {r.logical_id for r in inv.cfn_inventory(acc, follow_urls=True)})

    def test_cyclic_nested_stacks_stop(self):
        # A → B → A（URL の読み替えでも、ローカルのパスでも）は、2 回目を読まずにスタックのリソースとして数える（無限に再帰しない）
        inv = load_tool("iac_inventory")
        stack = "Type: AWS::CloudFormation::Stack\n    Properties:\n      TemplateURL: "
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.yaml").write_text(f"Resources:\n  ToB:\n    {stack}https://bucket.s3.amazonaws.com/x/b.yaml\n"
                                         "  Q:\n    Type: AWS::SQS::Queue\n", encoding="utf-8")
            (root / "b.yaml").write_text(f"Resources:\n  ToA:\n    {stack}a.yaml\n", encoding="utf-8")
            got = [(r.logical_id, r.file, r.nested_template) for r in inv.cfn_inventory(root / "a.yaml", follow_urls=True)]
        self.assertEqual(got, [("ToB", "a.yaml", "b.yaml"), ("ToB/ToA", "b.yaml", None), ("Q", "a.yaml", None)])

    def test_module_instance_index_is_not_the_block_index(self):
        # count／for_each のモジュールの中のブロック（`module.m[0].aws_x.y`）は、ブロック自身にインデックスが無くてよい。
        # for_each のモジュールの別のインスタンスでは、0 件（H-COND-FALSE）と 1 件以上が混ざってよい（P02・T20 の aurora）
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod").mkdir()
            (root / "main.tf").write_text('module "c" {\n  source = "./mod"\n  for_each = toset(["a", "b"])\n}\n'
                                          'module "one" {\n  source = "./plain"\n  count = 1\n}\n', encoding="utf-8")
            (root / "mod" / "main.tf").write_text('resource "aws_cloudwatch_log_group" "this" {\n  count = 1\n}\n', encoding="utf-8")
            (root / "plain").mkdir()
            (root / "plain" / "main.tf").write_text('resource "aws_s3_bucket" "b" {}\n', encoding="utf-8")

            def entry(addr, typ, file, cls, rule=None):
                return {"address": addr, "type": typ, "file": file, "class": cls, **({"rule": rule} if rule else {})}
            good = [entry('module.c["a"].aws_cloudwatch_log_group.this', "aws_cloudwatch_log_group", "mod/main.tf", "hidden", "H-COND-FALSE"),
                    entry('module.c["b"].aws_cloudwatch_log_group.this[0]', "aws_cloudwatch_log_group", "mod/main.tf", "hidden", "H-LOGS"),
                    entry("module.one[0].aws_s3_bucket.b", "aws_s3_bucket", "plain/main.tf", "hidden", "H-X")]
            self.assertEqual(cov.check_tf({"root": str(root), "resources": good}), [])
            # 同じモジュールのインスタンスの中で 0 件とインスタンスが混ざる・count の無いブロックにインデックスがあるのは誤りのまま
            mixed = good + [entry('module.c["a"].aws_cloudwatch_log_group.this[0]', "aws_cloudwatch_log_group", "mod/main.tf", "hidden", "H-LOGS")]
            self.assertTrue(any("混ざっている" in e for e in cov.check_tf({"root": str(root), "resources": mixed})))
            indexed = good[:2] + [entry("module.one[0].aws_s3_bucket.b[0]", "aws_s3_bucket", "plain/main.tf", "hidden", "H-X")]
            self.assertTrue(any("インデックスが付いている" in e for e in cov.check_tf({"root": str(root), "resources": indexed})))


if __name__ == "__main__":
    unittest.main()
