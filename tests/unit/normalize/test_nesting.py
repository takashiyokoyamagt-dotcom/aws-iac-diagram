"""正規化の段階 4（normalize/nesting.py）: 入れ子（P-VPC・P-SUBNET・P-SPANS・P-REGIONAL）と AZ のノード（N-AZ）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.raw_builders import raw_ir, reference, resource
from aws_iac_diagram.core import rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import build, nesting  # noqa: E402

RULES = rules_mod.default()


def tagged(name: str, **props) -> dict:
    return {"tags": {"Name": name}, **props}


def run(fmt: str, resources: list[dict], references: list[dict]) -> tuple[dict, list[tuple]]:
    """正規化して、ノード（id → (parent, spans)）と、入れ子の診断 (code, level, address) を返す。"""
    out = build.normalize(raw_ir(fmt, resources, references), RULES, "t")
    nodes = {n["id"]: (n["parent"], n.get("spans")) for n in out["nodes"]}
    diags = [(d["code"], d["level"], d["address"]) for d in out["diagnostics"] if d["code"] in ("NORM-PLACEMENT", "NORM-AZ-UNKNOWN")]
    return {"out": out, **nodes}, diags


def vpc_and_subnets(azs: dict[str, object]) -> tuple[list[dict], list[dict]]:
    res = [resource("aws_vpc.v", "aws_vpc", tagged("net"))]
    refs = []
    for name, az in azs.items():
        props = tagged(name) if az is None else tagged(name, availability_zone=az)
        res.append(resource(f"aws_subnet.{name}", "aws_subnet", props))
        refs.append(reference(f"aws_subnet.{name}", "vpc_id", "aws_vpc.v", "id"))
    return res, refs


class AzTest(unittest.TestCase):
    def test_az_of(self):
        self.assertEqual(nesting.az_of("ap-northeast-1a"), ("ap-northeast-1a", "ap-northeast-1a"))
        self.assertEqual(nesting.az_of({"$az": 0}), ("az1", "AZ 1"))
        self.assertEqual(nesting.az_of({"$az": 2}), ("az3", "AZ 3"))
        for v in ({"$az": "*"}, None, {"$unknown": "x"}, {"$res": "x", "attr": "y"}, "", {"$az": True}):
            self.assertIsNone(nesting.az_of(v), v)

    def test_az_nodes_under_the_vpc(self):
        res, refs = vpc_and_subnets({"a": "ap-northeast-1a", "b": "ap-northeast-1a", "c": {"$az": 1}, "d": {"$az": "*"}, "e": None})
        got, diags = run("tf", res, refs)
        out = got.pop("out")
        az = {n["id"]: n for n in out["nodes"] if n["type"] == "availability_zone"}
        self.assertEqual(az["availability_zone/net.ap-northeast-1a"], {
            "id": "availability_zone/net.ap-northeast-1a", "type": "availability_zone", "category": "group", "name": "ap-northeast-1a",
            "label": "ap-northeast-1a", "parent": "vpc/net", "synthetic": True})
        self.assertEqual((az["availability_zone/net.az2"]["name"], az["availability_zone/net.az2"]["label"]), ("az2", "AZ 2"))
        self.assertEqual(len(az), 2)
        self.assertEqual(got["subnet/a"], ("availability_zone/net.ap-northeast-1a", None))
        self.assertEqual(got["subnet/b"], ("availability_zone/net.ap-northeast-1a", None))
        self.assertEqual(got["subnet/c"], ("availability_zone/net.az2", None))
        self.assertEqual(got["subnet/d"], ("vpc/net", None))  # すべての AZ（"*"）は AZ のノードを作らない
        self.assertEqual(got["subnet/e"], ("vpc/net", None))
        self.assertEqual(got["vpc/net"], (None, None))
        self.assertEqual(diags, [("NORM-AZ-UNKNOWN", "info", "aws_subnet.d"), ("NORM-AZ-UNKNOWN", "info", "aws_subnet.e")])

    def test_subnet_without_a_vpc(self):
        got, diags = run("tf", [resource("aws_subnet.s", "aws_subnet", tagged("s", availability_zone="x-1a"))], [])
        self.assertEqual(got["subnet/s"], (None, None))
        self.assertEqual(diags, [("NORM-PLACEMENT", "warn", "aws_subnet.s")])


class PlacementTest(unittest.TestCase):
    def test_subnet_spans_and_vpc(self):
        res, refs = vpc_and_subnets({"a": "x-1a", "a2": "x-1a", "c": "x-1c"})
        res += [
            resource("aws_nat_gateway.n", "aws_nat_gateway", tagged("nat")),
            resource("aws_lb.alb", "aws_lb", {"name": "alb"}),
            resource("aws_ecs_service.same_az", "aws_ecs_service", {"name": "svc"}),
            resource("aws_internet_gateway.igw", "aws_internet_gateway", tagged("igw")),
            resource("aws_vpc_endpoint.s3", "aws_vpc_endpoint", tagged("s3", vpc_endpoint_type="Gateway")),
            resource("aws_s3_bucket.b", "aws_s3_bucket", {"bucket": "b"}),
            resource("aws_lambda_function.in_vpc", "aws_lambda_function", {"function_name": "in-vpc"}),
            resource("aws_lambda_function.plain", "aws_lambda_function", {"function_name": "plain"}),
            resource("aws_instance.only_cidr", "aws_instance", tagged("only-cidr")),
        ]
        refs += [
            reference("aws_nat_gateway.n", "subnet_id", "aws_subnet.a", "id"),
            reference("aws_lb.alb", "subnets[0]", "aws_subnet.a", "id"),
            reference("aws_lb.alb", "subnets[1]", "aws_subnet.c", "id"),
            reference("aws_ecs_service.same_az", "network_configuration[0].subnets[0]", "aws_subnet.a", "id"),
            reference("aws_ecs_service.same_az", "network_configuration[0].subnets[1]", "aws_subnet.a2", "id"),
            reference("aws_internet_gateway.igw", "vpc_id", "aws_vpc.v", "id"),
            reference("aws_vpc_endpoint.s3", "vpc_id", "aws_vpc.v", "id"),
            reference("aws_s3_bucket.b", "tags.Subnet", "aws_subnet.a", "id"),  # P-REGIONAL は参照があっても VPC に入れない
            reference("aws_lambda_function.in_vpc", "vpc_config[0].subnet_ids[0]", "aws_subnet.a", "id"),
            reference("aws_lambda_function.in_vpc", "vpc_config[0].subnet_ids[1]", "aws_subnet.c", "id"),
            reference("aws_instance.only_cidr", "user_data", "aws_subnet.a", "cidr_block"),  # CIDR を取るだけの参照は数えない
            reference("aws_instance.only_cidr", "depends_on", "aws_subnet.c", fn="depends_on"),  # DependsOn も数えない
        ]
        got, diags = run("tf", res, refs)
        self.assertEqual(got["nat_gateway/nat"], ("subnet/a", None))  # P-SUBNET
        self.assertEqual(got["alb/alb"], ("vpc/net", ["subnet/a", "subnet/c"]))  # P-SPANS（AZ が違えば VPC）
        self.assertEqual(got["ecs_service/svc"], ("availability_zone/net.x-1a", ["subnet/a", "subnet/a2"]))  # 同じ AZ なら AZ
        self.assertEqual(got["internet_gateway/igw"], ("vpc/net", None))  # P-VPC
        self.assertEqual(got["vpc_endpoint/s3"], ("vpc/net", None))
        self.assertEqual(got["s3_bucket/b"], (None, None))  # P-REGIONAL
        self.assertEqual(got["lambda_function/in-vpc"], ("vpc/net", ["subnet/a", "subnet/c"]))  # vpc_config のある Lambda
        self.assertEqual(got["lambda_function/plain"], (None, None))
        self.assertEqual(got["ec2_instance/only-cidr"], (None, None))
        self.assertEqual(diags, [("NORM-PLACEMENT", "warn", "aws_instance.only_cidr")])  # VPC の中に置く型で決まらない

    def test_merged_resources_are_clues(self):
        # DB はサブネットグループ（M-DB-SUBNET-GROUP）経由、CFN の IGW は VPCGatewayAttachment（M-IGW-ATTACH）経由
        res = [resource("Vpc", "AWS::EC2::VPC", tagged("net"), fmt="cfn"),
               resource("A", "AWS::EC2::Subnet", {"AvailabilityZone": "x-1a", "Tags": [{"Key": "Name", "Value": "a"}]}, fmt="cfn"),
               resource("C", "AWS::EC2::Subnet", {"AvailabilityZone": "x-1c", "Tags": [{"Key": "Name", "Value": "c"}]}, fmt="cfn"),
               resource("Group", "AWS::RDS::DBSubnetGroup", fmt="cfn"),
               resource("Db", "AWS::RDS::DBInstance", {"DBInstanceIdentifier": "db"}, fmt="cfn"),
               resource("Igw", "AWS::EC2::InternetGateway", {"Tags": [{"Key": "Name", "Value": "igw"}]}, fmt="cfn"),
               resource("Attach", "AWS::EC2::VPCGatewayAttachment", fmt="cfn")]
        refs = [reference("A", "Properties.VpcId", "Vpc", None, fn="Ref"), reference("C", "Properties.VpcId", "Vpc", None, fn="Ref"),
                reference("Group", "Properties.SubnetIds[0]", "A", None, fn="Ref"), reference("Group", "Properties.SubnetIds[1]", "C", None, fn="Ref"),
                reference("Db", "Properties.DBSubnetGroupName", "Group", None, fn="Ref"),
                reference("Attach", "Properties.VpcId", "Vpc", None, fn="Ref"),
                reference("Attach", "Properties.InternetGatewayId", "Igw", None, fn="Ref")]
        got, diags = run("cfn", res, refs)
        self.assertEqual(got["db_instance/db"], ("vpc/net", ["subnet/a", "subnet/c"]))
        self.assertEqual(got["internet_gateway/igw"], ("vpc/net", None))
        self.assertEqual(got["subnet/a"], ("availability_zone/net.x-1a", None))
        self.assertEqual(diags, [])

    def test_multiplied_subnets_and_black_boxes(self):
        res, refs = vpc_and_subnets({"a": "x-1a"})
        res += [
            resource("aws_subnet.p[*]", "aws_subnet", tagged("p"), enabled=None, multiplicity="N"),
            resource("aws_ecs_service.s", "aws_ecs_service", {"name": "svc"}),
            resource("module.vpc_only", "module", {"vpc_id": {"$res": "aws_vpc.v", "attr": "id"}}, via="module_blackbox",
                     source="git::https://example.com/x.git"),
            resource("module.nothing", "module", {}, via="module_blackbox", source="git::https://example.com/y.git"),
            resource("module.subnets", "module", {}, via="module_blackbox", source="git::https://example.com/z.git"),
        ]
        refs += [
            reference("aws_subnet.p[*]", "vpc_id", "aws_vpc.v", "id"),
            reference("aws_ecs_service.s", "network_configuration[0].subnets", "aws_subnet.p[*]", "id"),
            reference("module.vpc_only", "vpc_id", "aws_vpc.v", "id"),
            reference("module.subnets", "private_subnets[0]", "aws_subnet.a", "id"),
        ]
        got, diags = run("tf", res, refs)
        # ×N のサブネット: AZ が決まらないので VPC の下。それを指すサービスは spans を付けず、parent は共通の祖先（VPC）
        self.assertEqual(got["subnet/p"], ("vpc/net", None))
        self.assertEqual(got["ecs_service/svc"], ("vpc/net", None))
        self.assertEqual(got["module/vpc_only"], ("vpc/net", None))
        self.assertEqual(got["module/nothing"], (None, None))  # 黒箱は決まらなくても診断なし
        self.assertEqual(got["module/subnets"], ("subnet/a", None))
        self.assertEqual(diags, [("NORM-PLACEMENT", "warn", "aws_ecs_service.s"), ("NORM-AZ-UNKNOWN", "info", "aws_subnet.p[*]")])

    def test_lambda_uses_only_its_vpc_config(self):
        res, refs = vpc_and_subnets({"a": "x-1a", "c": "x-1c"})
        res += [resource("aws_lambda_function.env", "aws_lambda_function", {"function_name": "env"})]
        # 環境変数にサブネットの id を渡しても VPC には入らない（vpc_config の位置の参照だけを使う）
        refs += [reference("aws_lambda_function.env", "environment[0].variables.SUBNET", "aws_subnet.a", "id")]
        got, diags = run("tf", res, refs)
        self.assertEqual(got["lambda_function/env"], (None, None))
        self.assertEqual(diags, [])
        # SAM: Environment の Ref は使わず、VpcConfig の Ref だけを使う
        res = [resource("Vpc", "AWS::EC2::VPC", tagged("net"), fmt="cfn"),
               resource("A", "AWS::EC2::Subnet", {"AvailabilityZone": "x-1a", "Tags": [{"Key": "Name", "Value": "a"}]}, fmt="cfn"),
               resource("C", "AWS::EC2::Subnet", {"AvailabilityZone": "x-1c", "Tags": [{"Key": "Name", "Value": "c"}]}, fmt="cfn"),
               resource("EnvFn", "AWS::Serverless::Function", {"FunctionName": "env"}, fmt="cfn"),
               resource("VpcFn", "AWS::Serverless::Function", {"FunctionName": "vpc"}, fmt="cfn")]
        refs = [reference("A", "Properties.VpcId", "Vpc", None, fn="Ref"), reference("C", "Properties.VpcId", "Vpc", None, fn="Ref"),
                reference("EnvFn", "Properties.Environment.Variables.SUBNET", "A", None, fn="Ref"),
                reference("VpcFn", "Properties.VpcConfig.SubnetIds[0]", "A", None, fn="Ref"),
                reference("VpcFn", "Properties.VpcConfig.SubnetIds[1]", "C", None, fn="Ref")]
        got, diags = run("cfn", res, refs)
        self.assertEqual(got["lambda_function/env"], (None, None))
        self.assertEqual(got["lambda_function/vpc"], ("vpc/net", ["subnet/a", "subnet/c"]))
        self.assertEqual(diags, [])

    def test_eks_cluster_uses_only_its_own_vpc_config(self):
        res, refs = vpc_and_subnets({"a": "x-1a", "c": "x-1c", "n": "x-1a"})
        res += [resource("aws_eks_cluster.k", "aws_eks_cluster", {"name": "k"}),
                resource("aws_eks_node_group.g", "aws_eks_node_group")]
        refs += [reference("aws_eks_cluster.k", "vpc_config[0].subnet_ids[0]", "aws_subnet.a", "id"),
                 reference("aws_eks_cluster.k", "vpc_config[0].subnet_ids[1]", "aws_subnet.c", "id"),
                 reference("aws_eks_node_group.g", "cluster_name", "aws_eks_cluster.k", "name"),
                 reference("aws_eks_node_group.g", "subnet_ids[0]", "aws_subnet.n", "id")]  # 統合したノードグループのサブネットは使わない
        got, diags = run("tf", res, refs)
        self.assertEqual(got["eks_cluster/k"], ("vpc/net", ["subnet/a", "subnet/c"]))
        self.assertEqual(diags, [])

    def test_shared_subnet_group_places_every_db(self):
        res, refs = vpc_and_subnets({"a": "x-1a", "c": "x-1c"})
        res += [resource("aws_db_subnet_group.g", "aws_db_subnet_group"),
                resource("aws_db_instance.d1", "aws_db_instance", {"identifier": "d1"}),
                resource("aws_db_instance.d2", "aws_db_instance", {"identifier": "d2"})]
        refs += [reference("aws_db_subnet_group.g", "subnet_ids[0]", "aws_subnet.a", "id"),
                 reference("aws_db_subnet_group.g", "subnet_ids[1]", "aws_subnet.c", "id"),
                 reference("aws_db_instance.d1", "db_subnet_group_name", "aws_db_subnet_group.g", "name"),
                 reference("aws_db_instance.d2", "db_subnet_group_name", "aws_db_subnet_group.g", "name")]
        got, diags = run("tf", res, refs)
        out = got["out"]
        group = next(r for r in out["sources"]["tf"]["resources"] if r["address"] == "aws_db_subnet_group.g")
        self.assertEqual(group["into"], ["db_instance/d1", "db_instance/d2"])  # 統合先が 2 つ
        self.assertEqual(got["db_instance/d1"], ("vpc/net", ["subnet/a", "subnet/c"]))
        self.assertEqual(got["db_instance/d2"], ("vpc/net", ["subnet/a", "subnet/c"]))
        self.assertEqual(diags, [])

    def test_no_common_ancestor_and_two_vpcs(self):
        res = [resource("aws_vpc.v1", "aws_vpc", tagged("one")), resource("aws_vpc.v2", "aws_vpc", tagged("two")),
               resource("aws_subnet.a", "aws_subnet", tagged("a", availability_zone="x-1a")),
               resource("aws_subnet.b", "aws_subnet", tagged("b", availability_zone="x-1a")),
               resource("aws_subnet.both", "aws_subnet", tagged("both", availability_zone="x-1a")),
               resource("aws_lb.alb", "aws_lb", {"name": "alb"})]
        refs = [reference("aws_subnet.a", "vpc_id", "aws_vpc.v1", "id"), reference("aws_subnet.b", "vpc_id", "aws_vpc.v2", "id"),
                reference("aws_subnet.both", "vpc_id", "aws_vpc.v1", "id"), reference("aws_subnet.both", "tags.Other", "aws_vpc.v2", "id"),
                reference("aws_lb.alb", "subnets[0]", "aws_subnet.a", "id"), reference("aws_lb.alb", "subnets[1]", "aws_subnet.b", "id")]
        got, diags = run("tf", res, refs)
        # VPC の違うサブネットにまたがる: spans は付けて parent は null
        self.assertEqual(got["alb/alb"], (None, ["subnet/a", "subnet/b"]))
        # VPC を 2 つ指すサブネット: どちらとも決めず parent は null（AZ のノードも作らない）
        self.assertEqual(got["subnet/both"], (None, None))
        self.assertEqual(diags, [("NORM-PLACEMENT", "warn", "aws_lb.alb"), ("NORM-PLACEMENT", "warn", "aws_subnet.both")])
        msgs = [d["message"] for d in got["out"]["diagnostics"] if d["code"] == "NORM-PLACEMENT"]
        self.assertTrue(all("None" not in m and "null" in m for m in msgs), msgs)

    def test_order_does_not_matter(self):
        res, refs = vpc_and_subnets({"a": "x-1a", "c": "x-1c"})
        res.append(resource("aws_lb.alb", "aws_lb", {"name": "alb"}))
        refs += [reference("aws_lb.alb", "subnets[0]", "aws_subnet.c", "id"), reference("aws_lb.alb", "subnets[1]", "aws_subnet.a", "id")]
        one = build.normalize(raw_ir("tf", res, refs), RULES, "t")
        two = build.normalize(raw_ir("tf", list(reversed(res)), list(reversed(refs))), RULES, "t")
        self.assertEqual(one, two)


if __name__ == "__main__":
    unittest.main()
