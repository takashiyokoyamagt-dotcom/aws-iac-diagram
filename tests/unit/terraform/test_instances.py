"""Terraform アダプタ: count・for_each の展開（インスタンス単位）と、インスタンスへの参照。
個数が決まらない count・for_each（N）と、中身の見えない module 呼び出し（黒箱）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs, res_of
from support.terraform import NETWORK, build, codes, res


class CountAndModuleTest(unittest.TestCase):
    def test_unknown_count_and_for_each_are_n(self):
        # count・for_each の値が決まらない（値の無い変数）ときは ×N（[*]、enabled: null）
        raw = build(NETWORK + """
        variable "azs" {}
        variable "services" {}
        resource "aws_vpc_endpoint" "interface" {
          for_each = toset(var.services)
          vpc_id   = aws_vpc.main.id
        }
        resource "aws_route_table_association" "public" {
          count     = length(aws_subnet.public)
          subnet_id = aws_subnet.public[count.index].id
        }
        """)
        assert_valid(self, raw)
        for a in ("aws_subnet.public[*]", "aws_vpc_endpoint.interface[*]", "aws_route_table_association.public[*]"):
            r = res_of(raw, a)
            self.assertEqual((r["multiplicity"], r["enabled"]), ("N", None), a)
            self.assertNotIn("count", r["props"])
            self.assertNotIn("for_each", r["props"])
        self.assertIn("TF-COUNT-UNRESOLVED", codes(raw, "aws_vpc_endpoint.interface[*]"))
        self.assertEqual(refs(raw, "aws_route_table_association.public[*]"), [
            ("aws_route_table_association.public[*]", "count", "aws_subnet.public[*]", None, "ref", "unevaluated"),
            ("aws_route_table_association.public[*]", "subnet_id", "aws_subnet.public[*]", "id", "ref", "active"),
        ])

    def test_blackbox_module_call_is_recorded(self):
        # 要約表に無いレジストリ・git のモジュールは、呼び出し1件の黒箱（2章）。count・for_each は展開する
        raw = build({"main.tf": """
        provider "aws" {
          alias  = "use1"
          region = "us-east-1"
        }
        module "app" {
          source     = "git::https://example.com/app.git?ref=v1"
          name       = "demo-app"
          subnet_ids = module.vpc.private_subnets
          providers  = { aws = aws.use1 }
          depends_on = [module.vpc]
        }
        module "vpc" {
          source  = "cloudposse/vpc/aws"
          version = "~> 2.0"
          count   = var.create ? 1 : 0
        }
        variable "create" {}
        """})
        assert_valid(self, raw)
        app = res_of(raw, "module.app")
        self.assertEqual({k: app.get(k) for k in ("type", "file", "enabled", "via", "source", "provider", "region")},
                         {"type": "module", "file": "main.tf", "enabled": True, "via": "module_blackbox",
                          "source": "git::https://example.com/app.git?ref=v1", "provider": "aws.use1",
                          "region": "us-east-1"})
        self.assertNotIn("version", app)
        self.assertEqual(app["props"]["name"], "demo-app")
        self.assertEqual(app["props"]["subnet_ids"], res("module.vpc[*]", "private_subnets"))
        for meta in ("source", "providers", "depends_on"):
            self.assertNotIn(meta, app["props"])
        vpc = res_of(raw, "module.vpc[*]")
        self.assertEqual((vpc["version"], vpc["multiplicity"], vpc["enabled"]), ("~> 2.0", "N", None))
        self.assertIn("TF-MODULE-BLACKBOX", codes(raw, "module.app"))
        self.assertIn(("module.app", "depends_on", "module.vpc[*]", None, "depends_on", "active"), refs(raw))


class InstanceTest(unittest.TestCase):
    """count・for_each の展開と、インスタンスへの参照。"""

    def test_count_and_for_each(self):
        raw = build('''
        variable "azs" { default = ["a", "c"] }
        variable "routes" { default = { get = "GET /", post = "POST /" } }
        data "aws_availability_zones" "all" {}
        resource "aws_vpc" "main" {}
        resource "aws_subnet" "s" {
          count             = length(var.azs)
          vpc_id            = aws_vpc.main.id
          availability_zone = data.aws_availability_zones.all.names[count.index]
          tags              = { Name = "s-${var.azs[count.index]}", I = count.index }
        }
        resource "aws_route" "r" {
          for_each  = var.routes
          route_key = each.value
          name      = each.key
          subnet    = aws_subnet.s[1].id
        }
        resource "aws_lb" "lb" {
          subnets = aws_subnet.s[*].id
          legacy  = aws_subnet.s.*.arn
          first   = element(aws_subnet.s[*].id, 0)
          routes  = [for k, r in aws_route.r : r.id]
          one     = aws_route.r["get"].id
          azs     = slice(data.aws_availability_zones.all.names, 0, 2)
          depends_on = [aws_subnet.s]
        }
        resource "aws_eip" "none" {
          count = 0
          vpc   = aws_vpc.main.id
        }
        resource "aws_eip" "empty" {
          for_each = toset([])
        }
        resource "aws_nat_gateway" "n" {
          allocation_id = aws_eip.none[0].id
          all           = aws_eip.none[*].id
        }
        ''')
        assert_valid(self, raw)
        addrs = [r["address"] for r in raw["resources"]]
        for a in ("aws_subnet.s[0]", "aws_subnet.s[1]", 'aws_route.r["get"]', 'aws_route.r["post"]', "aws_eip.none",
                  "aws_eip.empty"):
            self.assertIn(a, addrs)
        self.assertEqual(props(raw, "aws_subnet.s[1]")["availability_zone"], {"$az": 1})
        self.assertEqual(props(raw, "aws_subnet.s[1]")["tags"], {"Name": "s-c", "I": 1})
        self.assertEqual(props(raw, 'aws_route.r["post"]'), {"route_key": "POST /", "name": "post",
                                                             "subnet": res("aws_subnet.s[1]", "id")})
        lb = props(raw, "aws_lb.lb")
        self.assertEqual(lb["subnets"], [res("aws_subnet.s[0]", "id"), res("aws_subnet.s[1]", "id")])
        self.assertEqual(lb["legacy"], [res("aws_subnet.s[0]", "arn"), res("aws_subnet.s[1]", "arn")])
        self.assertEqual(lb["first"], res("aws_subnet.s[0]", "id"))
        self.assertEqual(lb["routes"], [res('aws_route.r["get"]', "id"), res('aws_route.r["post"]', "id")])
        self.assertEqual(lb["one"], res('aws_route.r["get"]', "id"))
        self.assertEqual(lb["azs"], [{"$az": 0}, {"$az": 1}])
        # depends_on はすべてのインスタンスへ
        self.assertEqual([r[2] for r in refs(raw, "aws_lb.lb") if r[4] == "depends_on"],
                         ["aws_subnet.s[0]", "aws_subnet.s[1]"])
        # element で選ばなかったのが同じブロックの別のインスタンスなら、pruned にしない（N×(N−1) 件にならないように。
        # 第三者レビューの任意 1）
        self.assertNotIn(("aws_lb.lb", "first", "aws_subnet.s[1]", "id", "ref", "pruned"), refs(raw))
        # count が 0・for_each が空のブロックは、添字なしの1件で enabled: false（H-COND-FALSE）
        none = res_of(raw, "aws_eip.none")
        self.assertEqual((none["enabled"], none.get("multiplicity")), (False, None))
        self.assertEqual(none["props"], {"vpc": res("aws_vpc.main", "id")})  # props と参照は残す
        self.assertFalse(res_of(raw, "aws_eip.empty")["enabled"])
        nat = props(raw, "aws_nat_gateway.n")
        self.assertEqual(nat["allocation_id"], res("aws_eip.none", "id"))  # 作られないブロックへの参照
        self.assertEqual(nat["all"], [])
        self.assertEqual([d for d in raw["diagnostics"] if d["level"] != "info"], [])

    def test_count_from_resources_and_unknown_index(self):
        raw = build('''
        variable "i" {}
        resource "aws_subnet" "s" {
          count = 2
        }
        resource "aws_route_table_association" "a" {
          count     = length(aws_subnet.s)
          subnet_id = aws_subnet.s[count.index].id
        }
        resource "aws_lb" "x" {
          sub = aws_subnet.s[var.i].id
        }
        resource "aws_instance" "n" {
          count = length(aws_subnet.s[0].ids)
          name  = "n-${count.index}"
        }
        ''')
        assert_valid(self, raw)
        self.assertEqual(props(raw, "aws_route_table_association.a[1]")["subnet_id"], res("aws_subnet.s[1]", "id"))
        # 決まった count の式の参照は残さない（CFN の Fn::ForEach と同じ。値は props の参照に現れる）
        self.assertEqual([r for r in refs(raw, "aws_route_table_association.a[0]") if r[1] == "count"], [])
        # 決まらない添字は、すべてのインスタンスへの参照（unevaluated）
        self.assertEqual({r[2] for r in refs(raw, "aws_lb.x")}, {"aws_subnet.s[0]", "aws_subnet.s[1]"})
        n = res_of(raw, "aws_instance.n[*]")
        self.assertEqual((n["enabled"], n["multiplicity"]), (None, "N"))
        self.assertIn(("aws_instance.n[*]", "count", "aws_subnet.s[0]", "ids", "ref", "unevaluated"), refs(raw))
        self.assertEqual(n["props"]["name"]["$concat"][0], "n-")
        # ×N の warn は count の位置の1つだけ。count.index を使ったところは別の code の info（第三者レビューの任意 2）
        self.assertEqual(codes(raw, "aws_instance.n[*]"), ["TF-COUNT-UNRESOLVED", "TF-COUNT-INDEX"])
        self.assertEqual([d["level"] for d in raw["diagnostics"] if d["address"] == "aws_instance.n[*]"],
                         ["warn", "info"])

    def test_dynamic_blocks(self):
        raw = build('''
        variable "ports" { default = [80, 443] }
        variable "unknown" {}
        resource "aws_security_group" "src" {}
        resource "aws_security_group" "sg" {
          dynamic "ingress" {
            for_each = var.ports
            content {
              from_port       = ingress.value
              security_groups = [aws_security_group.src.id]
              description     = "rule ${ingress.key}"
            }
          }
          dynamic "egress" {
            for_each = { all = "-1" }
            iterator = rule
            content {
              protocol = rule.value
              dynamic "nested" {
                for_each = [rule.key]
                content { name = nested.value }
              }
            }
          }
          dynamic "tag" {
            for_each = var.unknown
            content { v = aws_security_group.src.arn }
          }
        }
        ''')
        assert_valid(self, raw)
        p = props(raw, "aws_security_group.sg")
        self.assertEqual(p["ingress"], [
            {"from_port": 80, "security_groups": [res("aws_security_group.src", "id")], "description": "rule 0"},
            {"from_port": 443, "security_groups": [res("aws_security_group.src", "id")], "description": "rule 1"}])
        self.assertEqual(p["egress"], [{"protocol": "-1", "nested": [{"name": "all"}]}])
        self.assertIn("$unknown", p["tag"][0])
        self.assertIn(("aws_security_group.sg", "ingress[1].security_groups[0]", "aws_security_group.src", "id", "ref",
                       "active"), refs(raw))
        self.assertIn(("aws_security_group.sg", "tag[0]", "aws_security_group.src", "arn", "ref", "unevaluated"),
                      refs(raw))

    def test_module_instances(self):
        raw = build('''
        module "m" {
          source   = "./m"
          for_each = toset(["x", "y"])
          name     = each.key
        }
        resource "aws_s3_bucket" "b" {
          v = module.m["x"].out
        }
        ''')
        assert_valid(self, raw)
        self.assertEqual(props(raw, 'module.m["y"]'), {"name": "y"})
        self.assertEqual(res_of(raw, 'module.m["x"]')["via"], "module_blackbox")
        self.assertEqual(props(raw, "aws_s3_bucket.b")["v"], res('module.m["x"]', "out"))


if __name__ == "__main__":
    unittest.main()
