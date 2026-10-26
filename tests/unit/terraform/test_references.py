"""Terraform アダプタ: 参照（resource・module の出力・instance の添字）と、擬似変数（data.aws_region などの擬似リソース）。
アダプタの本体は aws_iac_diagram/adapters/terraform/（refs.py・module_*.py）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs, res_of
from support.terraform import NETWORK, build, codes, res


class ReferenceTest(unittest.TestCase):
    def test_res_and_block_paths(self):
        raw = build(NETWORK + """
        resource "aws_lb" "app" {
          subnets         = aws_subnet.public[*].id
          security_groups = [aws_security_group.alb.id]
        }
        resource "aws_security_group" "alb" {
          vpc_id = aws_vpc.main.id
        }
        resource "aws_ecs_service" "app" {
          load_balancer {
            target_group_arn = aws_lb_target_group.app.arn
          }
          load_balancer {
            target_group_arn = aws_lb_target_group.app.arn_suffix
          }
          depends_on = [aws_lb.app]
        }
        resource "aws_lb_target_group" "app" {}
        """)
        assert_valid(self, raw)
        lb = props(raw, "aws_lb.app")
        # 値が決まらない count のスプラットは [*] への1つの $res（7.2）
        self.assertEqual(lb["subnets"], res("aws_subnet.public[*]", "id"))
        self.assertEqual(lb["security_groups"], [res("aws_security_group.alb", "id")])
        svc = props(raw, "aws_ecs_service.app")
        self.assertEqual(svc["load_balancer"], [{"target_group_arn": res("aws_lb_target_group.app", "arn")},
                                                {"target_group_arn": res("aws_lb_target_group.app", "arn_suffix")}])
        self.assertNotIn("depends_on", svc)
        self.assertEqual(refs(raw, "aws_ecs_service.app"), [
            ("aws_ecs_service.app", "depends_on", "aws_lb.app", None, "depends_on", "active"),
            ("aws_ecs_service.app", "load_balancer[0].target_group_arn", "aws_lb_target_group.app", "arn", "ref",
             "active"),
            ("aws_ecs_service.app", "load_balancer[1].target_group_arn", "aws_lb_target_group.app", "arn_suffix",
             "ref", "active"),
        ])
        self.assertIn(("aws_lb.app", "security_groups[0]", "aws_security_group.alb", "id", "ref", "active"), refs(raw))

    def test_instance_index_and_attr(self):
        raw = build(NETWORK + """
        resource "aws_nat_gateway" "main" {
          subnet_id = aws_subnet.public[0].id
          whole     = aws_subnet.public
          legacy    = aws_subnet.public.*.id
          nested    = aws_vpc.main.ipv6_association[0].id
          single    = aws_vpc.main[*].id
        }
        """)
        assert_valid(self, raw)
        p = props(raw, "aws_nat_gateway.main")
        self.assertEqual(p["subnet_id"], res("aws_subnet.public[*]", "id"))  # 手順1 はインスタンスを区別しない
        self.assertEqual(p["whole"], res("aws_subnet.public[*]"))
        self.assertEqual(p["legacy"], res("aws_subnet.public[*]", "id"))
        self.assertEqual(p["nested"], res("aws_vpc.main", "ipv6_association"))  # 最初の属性名
        self.assertEqual(p["single"], [res("aws_vpc.main", "id")])  # count の無いリソースのスプラットはリスト

    def test_module_output_and_undefined(self):
        raw = build("""
        module "vpc" {
          source  = "cloudposse/vpc/aws"
          version = "~> 2.0"
          name    = "demo"
        }
        resource "aws_security_group" "db" {
          vpc_id  = module.vpc.vpc_id
          missing = aws_vpc.nothing.id
          depends_on = [module.vpc, var.x]
        }
        """)
        assert_valid(self, raw)
        p = props(raw, "aws_security_group.db")
        self.assertEqual(p["vpc_id"], res("module.vpc", "vpc_id"))
        self.assertIn("$unknown", p["missing"])
        self.assertIn(("aws_security_group.db", "depends_on", "module.vpc", None, "depends_on", "active"), refs(raw))
        self.assertEqual(codes(raw, "aws_security_group.db").count("TF-UNDEFINED-REF"), 2)  # missing と var.x


class PseudoTest(unittest.TestCase):
    def test_pseudo_and_az(self):
        raw = build("""
        data "aws_region" "current" {}
        data "aws_caller_identity" "current" {}
        data "aws_partition" "current" {}
        data "aws_availability_zones" "available" {
          state = "available"
        }
        data "aws_region" "other" {
          provider = aws.use1
        }
        provider "aws" {
          alias  = "use1"
          region = "us-east-1"
        }
        resource "aws_s3_bucket" "b" {
          bucket  = "logs-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.name}"
          region2 = data.aws_region.current.region
          arn     = "arn:${data.aws_partition.current.partition}:s3:::x.${data.aws_partition.current.dns_suffix}"
          who     = data.aws_caller_identity.current.arn
          other   = data.aws_region.other.name
          az0     = data.aws_availability_zones.available.names[0]
          azs     = data.aws_availability_zones.available.names
          zone_id = data.aws_availability_zones.available.zone_ids[0]
        }
        """)
        assert_valid(self, raw)
        p = props(raw, "aws_s3_bucket.b")
        self.assertEqual(p["bucket"], {"$concat": ["logs-", {"$pseudo": "AWS::AccountId"}, "-",
                                                   {"$pseudo": "AWS::Region"}]})
        self.assertEqual(p["region2"], {"$pseudo": "AWS::Region"})
        self.assertEqual(p["arn"], {"$concat": ["arn:", {"$pseudo": "AWS::Partition"}, ":s3:::x.",
                                                {"$pseudo": "AWS::URLSuffix"}]})
        self.assertEqual(p["who"], res("data.aws_caller_identity.current", "arn"))
        self.assertEqual(p["other"], res("data.aws_region.other", "name"))  # provider の付いた data は $res
        self.assertEqual(p["az0"], {"$az": 0})
        self.assertEqual(p["azs"], {"$az": "*"})
        self.assertEqual(p["zone_id"], res("data.aws_availability_zones.available", "zone_ids"))
        # $pseudo と $az は参照にしない（CFN の擬似パラメータと同じ）
        self.assertEqual(sorted(r[2] for r in refs(raw, "aws_s3_bucket.b")),
                         ["data.aws_availability_zones.available", "data.aws_caller_identity.current",
                          "data.aws_region.other"])
        other = res_of(raw, "data.aws_region.other")
        self.assertEqual((other["provider"], other["region"]), ("aws.use1", "us-east-1"))


if __name__ == "__main__":
    unittest.main()
