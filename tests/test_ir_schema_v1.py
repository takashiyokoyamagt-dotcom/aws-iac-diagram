"""IR v1.0 のテスト。raw（ir-raw.schema.json と lib/ir_raw.py の決まり）と、正規化後の attrs・黒箱のモジュール。"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "aws-iac-diagram" / "scripts"
REFS = ROOT / "skills" / "aws-iac-diagram" / "references"
EXPECTED = ROOT / "aws-iac-diagram-workspace" / "expected"
sys.path.insert(0, str(SCRIPTS))
import validate_ir as v  # noqa: E402
from lib import ir_raw  # noqa: E402

RAW = jsonschema.Draft202012Validator(json.loads((REFS / "ir-raw.schema.json").read_text(encoding="utf-8")))


def res(address, attr=None):
    return {"$res": address, "attr": attr}


def ref(frm, path, to, attr=None, fn="Ref", state="active", **kw):
    return {"from": frm, "path": path, "to": to, "attr": attr, "fn": fn, "state": state, **kw}


def resource(address, type_, props=None, **kw):
    return {"address": address, "type": type_, "file": "template.yaml", "enabled": True, "props": props or {}, **kw}


# ir-schema.md の 7章の例をまとめたもの（決まりをすべて守っている）
RAW_EXAMPLE = {
    "ir_version": "1.0",
    "stage": "raw",
    "format": "cfn",
    "root": "fixtures/cfn/three-tier/template.yaml",
    "evaluation": {"parameters": {"EnvType": "dev", "PublicSubnetIds": ["a", "b"]},
                   "conditions": {"IsProd": False, "NetworkStack/HasNat": None},
                   "assumptions": ["TemplateURL を手元のファイルに読み替えた"]},
    "resources": [
        resource("AppService", "AWS::ECS::Service", {
            "ServiceName": "demo-app", "Cluster": res("Cluster"),
            "LoadBalancers": [{"TargetGroupArn": res("AppTargetGroup"), "ContainerPort": 8080}],
            "Subnets": [res("NetworkStack/PrivateSubnet1"), res("NetworkStack/PrivateSubnet2")]}),
        resource("AppTargetGroup", "AWS::ElasticLoadBalancingV2::TargetGroup"),
        resource("Bastion", "AWS::EC2::Instance", {
            "KeyName": {"$unknown": "parameter KeyName has no value"},
            "AvailabilityZone": {"$az": 0},
            "Tags": [{"Key": "Region", "Value": {"$pseudo": "AWS::Region"}}]}, enabled=False),
        resource("Cluster", "AWS::ECS::Cluster"),
        resource("Docs", "AWS::S3::Bucket"),
        resource("HttpListener", "AWS::ElasticLoadBalancingV2::Listener"),
        resource("Model", "AWS::ApiGateway::Model", {"Schema": {"$$schema": "http://json-schema.org/draft-04/schema#"}}),
        resource("NetworkStack", "AWS::CloudFormation::Stack"),
        resource("NetworkStack/PrivateSubnet1", "AWS::EC2::Subnet", via="nested_stack"),
        resource("NetworkStack/PrivateSubnet2", "AWS::EC2::Subnet", via="nested_stack"),
        resource("Policy", "AWS::IAM::Policy", {
            "Resource": {"$concat": ["arn:aws:s3:::", res("Docs"), "/*"]},
            "Doc": {"$json": {"Statement": [{"Resource": res("Docs", "Arn")}]}},
            "Shared": {"$import": "shared-vpc-id"},
            "Zones": {"$az": "*"}}),
    ],
    "references": [
        ref("AppService", "DependsOn", "HttpListener", fn="DependsOn"),
        ref("AppService", "Properties.Cluster", "Cluster"),
        ref("AppService", "Properties.LoadBalancers[0].TargetGroupArn", "AppTargetGroup"),
        ref("AppService", "Properties.Subnets[0]", "NetworkStack/PrivateSubnet1", fn="Ref",
            through=["NetworkStack.Outputs.PrivateSubnetIds"]),
        ref("AppService", "Properties.Subnets[1]", "NetworkStack/PrivateSubnet2", fn="Ref",
            through=["NetworkStack.Outputs.PrivateSubnetIds"]),
        ref("Policy", "Properties.Doc.Statement[0].Resource", "Docs", "Arn", fn="GetAtt"),
        ref("Policy", "Properties.Other", "Docs", fn="Ref", state="pruned"),
        ref("Policy", "Properties.Resource", "Docs", fn="Sub"),
    ],
    "diagnostics": [
        {"level": "warn", "code": "CFN-UNRESOLVED-PARAM", "address": "Bastion", "path": "Properties.KeyName",
         "message": "parameter KeyName has no value"},
    ],
}


def raw_errors(doc):
    return [e.message for e in RAW.iter_errors(doc)]


def raw_all_errors(doc):
    return raw_errors(doc) or ir_raw.semantic_errors(doc)


class RawSchemaTest(unittest.TestCase):
    def test_example_is_valid(self):
        self.assertEqual(raw_all_errors(RAW_EXAMPLE), [])

    def assertSchemaRejects(self, mutate):
        doc = copy.deepcopy(RAW_EXAMPLE)
        mutate(doc)
        self.assertTrue(raw_errors(doc))

    def test_rejects(self):
        props = lambda d: d["resources"][0]["props"]  # noqa: E731
        cases = {
            "未知の印": lambda d: props(d).update(X={"$foo": "bar"}),
            "印の余分なキー": lambda d: props(d).update(X={"$res": "Cluster", "attr": None, "extra": 1}),
            "$res の attr が無い": lambda d: props(d).update(X={"$res": "Cluster"}),
            "逃がしていない $ のキー": lambda d: props(d).update(X={"$schema": "x"}),
            "負の $az": lambda d: props(d).update(X={"$az": -1}),
            "$az の文字列": lambda d: props(d).update(X={"$az": "a"}),
            "未知の $pseudo": lambda d: props(d).update(X={"$pseudo": "AWS::Foo"}),
            "$concat の入れ子": lambda d: props(d).update(X={"$concat": ["a", {"$concat": ["b", res("Cluster")]}]}),
            "$concat が文字列だけ": lambda d: props(d).update(X={"$concat": ["a", "b"]}),
            "$concat の空文字": lambda d: props(d).update(X={"$concat": ["", res("Cluster")]}),
            "$concat の中の配列": lambda d: props(d).update(X={"$concat": [["a"], res("Cluster")]}),
            "enabled が無い": lambda d: d["resources"][0].pop("enabled"),
            "CFN に module": lambda d: d["resources"][0].update(module="module.x"),
            "CFN に provider": lambda d: d["resources"][0].update(provider="aws.x", region="us-east-1"),
            "CFN に vars": lambda d: d["evaluation"].update(vars={}),
            "診断の code": lambda d: d["diagnostics"][0].update(code="unresolved"),
            "CFN の診断に TF-": lambda d: d["diagnostics"][0].update(code="TF-X"),
            "CFN の参照に ref": lambda d: d["references"][1].update(fn="ref"),
            "Ref に attr": lambda d: d["references"][1].update(attr="Arn"),
            "GetAtt に attr が無い": lambda d: d["references"][5].update(attr=None),
            "state が無い": lambda d: d["references"][1].pop("state"),
            "DependsOn が pruned": lambda d: d["references"][0].update(state="pruned"),
            "through の形": lambda d: d["references"][3].update(through=["NetworkStack.VpcId"]),
            "through の空文字": lambda d: d["references"][3].update(through=[""]),
            "root の \\": lambda d: d.update(root="fixtures\\cfn\\x.yaml"),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                self.assertSchemaRejects(mutate)

    def test_concat_cannot_contain_json(self):
        self.assertSchemaRejects(lambda d: d["resources"][0]["props"].update(
            X={"$concat": ["a", {"$json": {"k": res("Cluster")}}]}))

    def test_accepts_hyphenated_stack_name(self):
        doc = copy.deepcopy(RAW_EXAMPLE)
        doc["references"][3]["through"] = ["My-App::NetworkStack.Outputs.PrivateSubnetIds"]
        self.assertEqual(raw_errors(doc), [])

    def test_metadata_reference_is_not_in_props(self):
        # Properties の外（Metadata など）の参照は references にだけ出る（7.3）
        doc = copy.deepcopy(RAW_EXAMPLE)
        doc["references"].append(ref("AppService", "Metadata.AWS::CloudFormation::Init.config", "Cluster"))
        doc = ir_raw.canonical_raw(doc)
        self.assertEqual(raw_all_errors(doc), [])

    def test_accepts_resolved_importvalue(self):
        doc = copy.deepcopy(RAW_EXAMPLE)
        doc["references"][1].update(fn="ImportValue", through=["Export:shared-cluster"])
        self.assertEqual(raw_errors(doc), [])

    def test_tf_format(self):
        doc = {"ir_version": "1.0", "stage": "raw", "format": "tf", "root": "fixtures/tf/three-tier",
               "evaluation": {"var_files": ["env/dev.tfvars"], "vars": {"env": {"source": "env/dev.tfvars"},
                                                                         "pw": {"source": None, "hidden": "sensitive"}}},
               "resources": [
                   {"address": "aws_subnet.private[*]", "type": "aws_subnet", "file": "network.tf", "enabled": None,
                    "multiplicity": "N", "props": {"vpc_id": res("aws_vpc.main", "id")}},
                   {"address": "aws_vpc.main", "type": "aws_vpc", "file": "network.tf", "enabled": True, "props": {},
                    "provider": "aws.us_east_1", "region": "us-east-1"},
                   {"address": "module.iam", "type": "module", "file": "main.tf", "enabled": True, "props": {},
                    "via": "module_blackbox", "source": "aws-ia/x/aws", "version": "1.0.0"}],
               "references": [ref("aws_subnet.private[*]", "vpc_id", "aws_vpc.main", "id", fn="ref",
                                  through=["module.network.var.vpc_id"])],
               "diagnostics": []}
        self.assertEqual(raw_all_errors(doc), [])
        bad = copy.deepcopy(doc)
        bad["references"][0]["fn"] = "Ref"
        self.assertTrue(raw_errors(bad))
        bad = copy.deepcopy(doc)
        bad["resources"][0]["implicit"] = True
        self.assertTrue(raw_errors(bad))
        # region はリソースの引数 region からも決まるので、provider が無くてもよい。provider は alias のあるものだけ（7.2）
        ok = copy.deepcopy(doc)
        ok["resources"][1].pop("provider")
        self.assertEqual(raw_errors(ok), [])
        bad = copy.deepcopy(doc)
        bad["resources"][1]["provider"] = "aws"
        self.assertTrue(raw_errors(bad))


class RawSemanticTest(unittest.TestCase):
    def errs(self, mutate):
        doc = copy.deepcopy(RAW_EXAMPLE)
        mutate(doc)
        self.assertEqual(raw_errors(doc), [], "Schema は通る前提")
        return ir_raw.semantic_errors(doc)

    def test_missing_reference_for_res(self):
        self.assertTrue(self.errs(lambda d: d["references"].pop(2)))  # TargetGroupArn

    def test_active_reference_without_res(self):
        self.assertTrue(self.errs(lambda d: d["references"][6].update(state="active")))

    def test_res_target_missing(self):
        self.assertTrue(self.errs(lambda d: d["resources"].pop(1)))  # AppTargetGroup

    def test_duplicate_address(self):
        self.assertTrue(self.errs(lambda d: d["resources"].insert(1, copy.deepcopy(d["resources"][1]))))

    def test_order(self):
        self.assertTrue(self.errs(lambda d: d["references"].reverse()))

    def test_concat_adjacent_strings(self):
        def m(d):
            d["resources"][-1]["props"]["Resource"] = {"$concat": ["arn:", "aws:s3:::", res("Docs")]}
        self.assertTrue(self.errs(m))

    def test_escaped_key_path(self):
        # $$ で逃がしたキーは、path では元のキーで書く
        self.assertEqual(ir_raw.join_path("Properties", ir_raw.unescape_key("$$schema")), 'Properties["$schema"]')
        self.assertEqual(ir_raw.join_path("Properties.Tags", 0), "Properties.Tags[0]")
        self.assertEqual(ir_raw.join_path("", "vpc_id"), "vpc_id")

    def test_normalize_concat(self):
        self.assertEqual(ir_raw.normalize_concat(["a", "", "b", res("X"), "c", "d"]),
                         {"$concat": ["ab", res("X"), "cd"]})
        self.assertEqual(ir_raw.normalize_concat(["a", {"$concat": ["b", res("X")]}]), {"$concat": ["ab", res("X")]})
        self.assertEqual(ir_raw.normalize_concat(["a", "b"]), "ab")

    def test_validate_file_and_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.raw.json"
            doc = copy.deepcopy(RAW_EXAMPLE)
            doc["references"].reverse()
            p.write_text(json.dumps(doc), encoding="utf-8")
            v.DRAWABLE = v.drawable_types()
            errs = v.validate_file(p, write=True, rules=v.defined_rules())
            self.assertEqual(errs, [])
            self.assertEqual(v.validate_file(p, write=False, rules=v.defined_rules()), [])


def load(name="three-tier"):
    return json.loads((EXPECTED / f"{name}.ir.json").read_text(encoding="utf-8"))


def add_blackbox(ir, tf_type="module", cfn_type="AWS::CloudFormation::Stack", via=True, node_type="module"):
    ir["nodes"].append({"id": "module/iam_extra", "type": node_type, "category": "resource",
                        "name": "iam_extra", "label": "iam_extra", "parent": None,
                        "attrs": {"module_source": "aws-ia/example/aws", "module_version": "1.0.0"}})
    extra = {"via": "module_blackbox"} if via else {}
    ir["sources"]["tf"]["resources"].append({"address": "module.iam_extra", "type": tf_type, "file": "main.tf",
                                             "class": "drawn", "node": "module/iam_extra", **extra})
    # CFN では、読めないネストスタックが同じ黒箱のノードになる
    ir["sources"]["cfn"]["resources"].append({"address": "IamExtraStack", "type": cfn_type, "file": "template.yaml",
                                              "class": "drawn", "node": "module/iam_extra", **extra})
    return ir


class NormalizedV1Test(unittest.TestCase):
    def test_expected_are_v1(self):
        for p in sorted(EXPECTED.glob("*.ir.json")):
            self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["ir_version"], "1.0", p.name)

    def test_unlisted_attr_is_rejected(self):
        ir = load()
        ir["nodes"][0].setdefault("attrs", {})["engine"] = "postgres"
        self.assertTrue(v.schema_errors(ir))

    def test_diagnostics_allowed(self):
        ir = load()
        ir["diagnostics"] = [{"level": "info", "code": "NORM-UNUSED-REF", "message": "x"}]
        self.assertEqual(v.schema_errors(ir), [])
        ir["diagnostics"][0]["code"] = "CFN-X"
        self.assertTrue(v.schema_errors(ir))

    def test_blackbox_module_is_valid(self):
        ir = add_blackbox(load())
        errs = v.schema_errors(ir) + v.semantic_errors(ir, v.defined_rules())
        self.assertEqual([e for e in errs if "module" in e or "IamExtra" in e], [], errs)

    def test_module_without_blackbox_is_rejected(self):
        errs = v.semantic_errors(add_blackbox(load(), via=False), v.defined_rules())
        self.assertTrue([e for e in errs if "module.iam_extra" in e], errs)
        self.assertTrue([e for e in errs if "IamExtraStack" in e], errs)

    def test_blackbox_with_wrong_input_type_is_rejected(self):
        errs = v.semantic_errors(add_blackbox(load(), tf_type="aws_vpc"), v.defined_rules())
        self.assertTrue([e for e in errs if "module.iam_extra" in e and "黒箱" in e], errs)


if __name__ == "__main__":
    unittest.main()
