"""CloudFormation アダプタ: cdk.out（複数スタック・export・ネスト。cdk.py）。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid
from support.cloudformation import ref_by, write_files
from aws_iac_diagram.adapters.cloudformation import build as cfn_build  # noqa: E402


class CdkOutTest(unittest.TestCase):
    def test_multiple_stacks_exports_and_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp) / "cdk.out"
            files = {
                "manifest.json": json.dumps({"version": "36.0.0", "artifacts": {
                    "Tree": {"type": "cdk:tree"},
                    "NetStack": {"type": "aws:cloudformation:stack",
                                 "properties": {"templateFile": "NetStack.template.json", "stackName": "Net-Stack"}},
                    "AppStack": {"type": "aws:cloudformation:stack",
                                 "properties": {"templateFile": "AppStack.template.json"}}}}),
                "NetStack.template.json": json.dumps({
                    "Resources": {"Vpc": {"Type": "AWS::EC2::VPC"}},
                    "Outputs": {"VpcId": {"Value": {"Ref": "Vpc"}, "Export": {"Name": "net-vpc-id"}}}}),
                "AppStack.template.json": json.dumps({"Resources": {
                    "Sg": {"Type": "AWS::EC2::SecurityGroup",
                           "Properties": {"VpcId": {"Fn::ImportValue": "net-vpc-id"},
                                          "Other": {"Fn::ImportValue": "not-exported"}}},
                    "Child": {"Type": "AWS::CloudFormation::Stack",
                              "Metadata": {"aws:asset:path": "AppStackChild1234.nested.template.json"},
                              "Properties": {"TemplateURL": {"Fn::Join": ["", ["https://s3.", {"Ref": "AWS::URLSuffix"}, "/x/abc.json"]]}}},
                    "Fn": {"Type": "AWS::Lambda::Function",
                           "Properties": {"Q": {"Fn::GetAtt": ["Child", "Outputs.QueueUrl"]}}}}}),
                "AppStackChild1234.nested.template.json": json.dumps({
                    "Resources": {"Queue": {"Type": "AWS::SQS::Queue"}},
                    "Outputs": {"QueueUrl": {"Value": {"Ref": "Queue"}}}}),
            }
            write_files(tmp, files)
            raw = cfn_build.build_raw(tmp, tmp.parent)
        assert_valid(self, raw)
        self.assertEqual(raw["root"], "cdk.out")
        res = {r["address"]: r for r in raw["resources"]}
        self.assertEqual(set(res), {"Net-Stack::Vpc", "AppStack::Sg", "AppStack::Child", "AppStack::Child/Queue",
                                    "AppStack::Fn"})
        self.assertEqual(res["AppStack::Sg"]["file"], "AppStack.template.json")
        self.assertEqual(res["AppStack::Child/Queue"]["via"], "nested_stack")
        # 入力の中で解決できた ImportValue（7.2・7.3）
        self.assertEqual(res["AppStack::Sg"]["props"]["VpcId"], {"$res": "Net-Stack::Vpc", "attr": None})
        self.assertEqual(res["AppStack::Sg"]["props"]["Other"], {"$import": "not-exported"})
        r = ref_by(raw, "AppStack::Sg", "Properties.VpcId")[0]
        self.assertEqual((r["fn"], r["through"]), ("ImportValue", ["Export:net-vpc-id"]))
        r = ref_by(raw, "AppStack::Fn", "Properties.Q")[0]
        self.assertEqual((r["to"], r["through"]), ("AppStack::Child/Queue", ["AppStack::Child.Outputs.QueueUrl"]))

    def test_stage_duplicate_names_and_exports(self):
        # 第三者レビューの R1: Stage（入れ子のアセンブリ）、同じ stackName、Export の衝突と AWS::StackName
        def stack(resources, outputs=None):
            return json.dumps({"Resources": resources, "Outputs": outputs or {}})
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp) / "cdk.out"
            write_files(tmp, {
                "manifest.json": json.dumps({"artifacts": {
                    "assembly-Prod": {"type": "cdk:cloud-assembly", "properties": {"directoryName": "assembly-Prod"}},
                    "Top": {"type": "aws:cloudformation:stack", "properties": {"templateFile": "Top.template.json"}}}}),
                "Top.template.json": stack(
                    {"Fn": {"Type": "AWS::Lambda::Function",
                            "Properties": {"A": {"Fn::ImportValue": "Prod-Net-VpcId"},
                                           "B": {"Fn::ImportValue": "dup"}}}},
                    {"X": {"Value": "x", "Export": {"Name": "dup"}}}),
                "assembly-Prod/manifest.json": json.dumps({"artifacts": {
                    "ProdNet": {"type": "aws:cloudformation:stack",
                                "properties": {"templateFile": "ProdNet.template.json", "stackName": "Net"}},
                    "ProdNet2": {"type": "aws:cloudformation:stack",
                                 "properties": {"templateFile": "ProdNet2.template.json", "stackName": "Net"}}}}),
                "assembly-Prod/ProdNet.template.json": stack(
                    {"Vpc": {"Type": "AWS::EC2::VPC"}},
                    {"VpcId": {"Value": {"Ref": "Vpc"}, "Export": {"Name": {"Fn::Sub": "Prod-${AWS::StackName}-VpcId"}}}}),
                "assembly-Prod/ProdNet2.template.json": stack(
                    {"Vpc": {"Type": "AWS::EC2::VPC"}}, {"Y": {"Value": "y", "Export": {"Name": "dup"}}}),
            })
            raw = cfn_build.build_raw(tmp, tmp.parent)
        assert_valid(self, raw)
        res = {r["address"]: r for r in raw["resources"]}
        # 同じ stackName（Net）が2つあるので artifact の ID を使う
        self.assertEqual(set(res), {"Top::Fn", "ProdNet::Vpc", "ProdNet2::Vpc"})
        self.assertEqual(res["ProdNet::Vpc"]["file"], "assembly-Prod/ProdNet.template.json")
        # Export の名前の AWS::StackName は、address の名前（ProdNet）ではなく本当の stackName（Net）で解く
        self.assertEqual(res["Top::Fn"]["props"]["A"], {"$res": "ProdNet::Vpc", "attr": None})
        # 衝突した Export（dup）は最初に登録したもの（スタックを名前の順に登録するので ProdNet2 の y）を使い、診断を出す
        self.assertEqual(res["Top::Fn"]["props"]["B"], "y")
        codes = {d["code"] for d in raw["diagnostics"]}
        self.assertIn("CFN-CDK-STACKNAME-DUPLICATE", codes)
        self.assertIn("CFN-EXPORT-CONFLICT", codes)

    def test_export_name_with_stack_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp) / "cdk.out"
            write_files(tmp, {
                "manifest.json": json.dumps({"artifacts": {
                    "Net": {"type": "aws:cloudformation:stack", "properties": {"templateFile": "Net.json"}},
                    "App": {"type": "aws:cloudformation:stack", "properties": {"templateFile": "App.json"}}}}),
                "Net.json": json.dumps({"Resources": {"Vpc": {"Type": "AWS::EC2::VPC"}}, "Outputs": {
                    "VpcId": {"Value": {"Ref": "Vpc"}, "Export": {"Name": {"Fn::Sub": "${AWS::StackName}-VpcId"}}}}}),
                "App.json": json.dumps({"Resources": {"Sg": {"Type": "AWS::EC2::SecurityGroup",
                                                             "Properties": {"VpcId": {"Fn::ImportValue": "Net-VpcId"}}}}}),
            })
            raw = cfn_build.build_raw(tmp, tmp.parent)
        sg = next(r for r in raw["resources"] if r["address"] == "App::Sg")
        self.assertEqual(sg["props"]["VpcId"], {"$res": "Net::Vpc", "attr": None})
        assert_valid(self, raw)


if __name__ == "__main__":
    unittest.main()
