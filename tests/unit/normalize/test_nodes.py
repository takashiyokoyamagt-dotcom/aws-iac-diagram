"""正規化の段階 2（normalize/nodes.py）と、段階の組み立て（normalize/build.py）の出力の形。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.raw_builders import raw_ir, reference, resource
from aws_iac_diagram.core import ir_norm, rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import build, classify, nodes  # noqa: E402
from aws_iac_diagram.normalize.view import Index  # noqa: E402

RULES = rules_mod.default()


def node_map(fmt: str, resources: list[dict], references: list[dict] | None = None) -> tuple[dict, list]:
    idx = Index(raw_ir(fmt, resources, references))
    return nodes.build_nodes(idx, classify.classify(idx, RULES), RULES)


class NodesTest(unittest.TestCase):
    def test_fields(self):
        got, diags = node_map("tf", [
            resource("aws_vpc.main", "aws_vpc", {"cidr_block": "10.0.0.0/16", "tags": {"Name": "demo"}}),
            resource("aws_iam_role.r", "aws_iam_role"),
            resource("aws_sqs_queue.q[*]", "aws_sqs_queue", {"name": "jobs"}, enabled=None, multiplicity="N"),
        ])
        self.assertEqual(sorted(got), ["aws_sqs_queue.q[*]", "aws_vpc.main"])  # 描くものだけ
        self.assertEqual(got["aws_vpc.main"], {"id": "vpc/demo", "type": "vpc", "category": "group", "name": "demo", "label": "demo",
                                               "parent": None, "attrs": {"cidr": "10.0.0.0/16"}})
        self.assertEqual(got["aws_sqs_queue.q[*]"], {"id": "sqs_queue/jobs", "type": "sqs_queue", "category": "resource",
                                                     "name": "jobs", "label": "jobs", "parent": None, "multiplicity": "N"})
        self.assertEqual([(d["code"], d["level"], d["address"]) for d in diags], [("NORM-COND-UNKNOWN", "warn", "aws_sqs_queue.q[*]")])

    def test_attrs(self):
        got, _ = node_map("cfn", [
            resource("S3", "AWS::EC2::VPCEndpoint", {"ServiceName": {"$concat": ["com.amazonaws.", {"$pseudo": "AWS::Region"}, ".s3"]},
                                                     "Tags": [{"Key": "Name", "Value": "s3"}]}, fmt="cfn"),
            resource("Ecr", "AWS::EC2::VPCEndpoint", {"ServiceName": "com.amazonaws.ap-northeast-1.ecr.api", "VpcEndpointType": "Interface",
                                                      "Tags": [{"Key": "Name", "Value": "ecr"}]}, fmt="cfn"),
            resource("Odd", "AWS::EC2::VPCEndpoint", {"ServiceName": {"$concat": [{"$res": "X", "attr": None}, ".s3"]},
                                                      "Tags": [{"Key": "Name", "Value": "odd"}]}, fmt="cfn"),
            resource("Sub", "AWS::EC2::Subnet", {"CidrBlock": {"$unknown": "Fn::Cidr"}, "Tags": [{"Key": "Name", "Value": "sub"}]}, fmt="cfn"),
            resource("Lost", "AWS::CloudFormation::Stack", {"TemplateURL": "https://example.com/x.yaml"}, fmt="cfn", via="module_blackbox"),
        ])
        self.assertEqual(got["S3"]["attrs"], {"endpoint_type": "Gateway", "service": "s3"})  # 省略時は Gateway
        self.assertEqual(got["Ecr"]["attrs"], {"endpoint_type": "Interface", "service": "ecr.api"})
        self.assertEqual(got["Odd"]["attrs"], {"endpoint_type": "Gateway"})  # 決まらないサービス名は付けない
        self.assertNotIn("attrs", got["Sub"])  # 評価できない CIDR は付けない
        self.assertEqual(got["Lost"]["attrs"], {"module_source": "https://example.com/x.yaml"})
        self.assertEqual((got["Lost"]["id"], got["Lost"]["name"]), ("module/lost", "Lost"))
        sar, _ = node_map("cfn", [
            resource("Sar", "AWS::Serverless::Application", {"Location": {"ApplicationId": "arn:aws:serverlessrepo:us-east-1:1:applications/x",
                                                                          "SemanticVersion": "1.2.3"}}, fmt="cfn", via="module_blackbox"),
            resource("Local", "AWS::Serverless::Application", {"Location": "./app/template.yaml"}, fmt="cfn", via="module_blackbox"),
            resource("Unknown", "AWS::Serverless::Application", {"Location": {"$unknown": "x"}}, fmt="cfn", via="module_blackbox"),
        ])
        self.assertEqual(sar["Sar"]["attrs"], {"module_source": "arn:aws:serverlessrepo:us-east-1:1:applications/x", "module_version": "1.2.3"})
        self.assertEqual(sar["Local"]["attrs"], {"module_source": "./app/template.yaml"})
        self.assertNotIn("attrs", sar["Unknown"])
        tf, _ = node_map("tf", [resource("module.kms", "module", {"description": "k"}, source="terraform-aws-modules/kms/aws",
                                         version="~> 3.0", via="module_blackbox")])
        self.assertEqual(tf["module.kms"]["attrs"], {"module_source": "terraform-aws-modules/kms/aws", "module_version": "~> 3.0"})


class BuildTest(unittest.TestCase):
    def test_output_shape(self):
        raw = raw_ir("tf", [
            resource("aws_nat_gateway.n", "aws_nat_gateway", {"tags": {"Name": "nat"}}),
            resource("aws_eip.e", "aws_eip"),
            resource("aws_iam_role.r", "aws_iam_role"),
            resource("aws_route_table.r", "aws_route_table"),
            resource("module.vpc.aws_vpc.this[0]", "aws_vpc", {"tags": {"Name": "v"}}, via="module_summary", module="module.vpc"),
            resource("aws_unheard_of.x", "aws_unheard_of"),
        ], [reference("aws_nat_gateway.n", "allocation_id", "aws_eip.e", "id")], root="fixtures/tf/my-net")
        out = build.normalize(raw, RULES)
        self.assertEqual((out["ir_version"], out["stage"], out["name"]), ("1.0", "normalized", "my-net"))
        self.assertEqual(out["edges"], [])
        self.assertEqual([n["id"] for n in out["nodes"]], ["nat_gateway/nat", "vpc/v"])
        src = out["sources"]["tf"]
        self.assertEqual((src["root"], src["edges"]), ("fixtures/tf/my-net", []))
        self.assertEqual(src["resources"], [
            {"address": "aws_eip.e", "type": "aws_eip", "file": "main.tf", "class": "merged_into", "rule": "M-EIP-NAT",
             "into": ["nat_gateway/nat"]},
            {"address": "aws_iam_role.r", "type": "aws_iam_role", "file": "main.tf", "class": "hidden", "rule": "H-IAM"},
            {"address": "aws_nat_gateway.n", "type": "aws_nat_gateway", "file": "main.tf", "class": "drawn", "node": "nat_gateway/nat"},
            # R-* は辺の段階まで仮（into が空）
            {"address": "aws_route_table.r", "type": "aws_route_table", "file": "main.tf", "class": "merged_into", "rule": "R-ROUTE",
             "into": []},
            {"address": "aws_unheard_of.x", "type": "aws_unheard_of", "file": "main.tf", "class": "unknown"},
            {"address": "module.vpc.aws_vpc.this[0]", "type": "aws_vpc", "file": "main.tf", "class": "drawn", "node": "vpc/v",
             "via": "module_summary"},
        ])
        self.assertEqual(out["evaluation"], {"tf": {"var_files": [], "vars": {}}, "assumptions": []})
        self.assertEqual(out, ir_norm.sort_lists(out))  # 決まった順

    def test_names_and_evaluation(self):
        self.assertEqual(build.default_name("fixtures/cfn/three-tier/template.yaml"), "three-tier")
        self.assertEqual(build.default_name("fixtures/tf/Three_Tier"), "three-tier")
        self.assertEqual(build.default_name("plan.json"), "plan")
        self.assertEqual(build.default_name(""), "ir")
        raw = raw_ir("cfn", [])
        raw["evaluation"] = {"parameters": {"Env": "dev", "Port": 80, "Azs": ["a", "b"], "Ssm": {"$unknown": "x"},
                                            "Net/VpcId": {"$res": "Net/Vpc", "attr": None}, "App::X": "y"},
                             "conditions": {"IsProd": False, "Maybe": None}, "assumptions": ["a"]}
        self.assertEqual(build.evaluation_of(raw), {"cfn": {"parameters": {"Env": "dev", "Port": 80, "Azs": ["a", "b"]},
                                                            "conditions": {"IsProd": False, "Maybe": None}}, "assumptions": ["a"]})
        out = build.normalize(raw, RULES, "given")
        self.assertEqual((out["name"], out["sources"]["cfn"]["resources"], out["nodes"]), ("given", [], []))


if __name__ == "__main__":
    unittest.main()
