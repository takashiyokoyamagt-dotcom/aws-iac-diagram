"""Terraform アダプタ: ローカル module の再帰・count／for_each の module・出力と変数のたどり方・module をまたぐ参照・provider。
本体は aws_iac_diagram/adapters/terraform/（module_load・module_expand・module_emit・module_eval・modules/）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs, res_of
from support.terraform import build, codes, res
from aws_iac_diagram.adapters.terraform import build as tf_build, module_expand  # noqa: E402


class ModuleTest(unittest.TestCase):
    """手順3: ローカルモジュールの再帰・count／for_each の module・出力と変数のたどり・境界をまたぐ参照・provider。"""

    def test_local_module_recursion_and_through(self):
        raw = build({"main.tf": """
        module "net" {
          source = "./modules/net"
          name   = "demo"
        }
        resource "aws_security_group" "app" {
          vpc_id    = module.net.vpc_id
          subnet_id = module.net.subnet_ids[1]
          bucket    = module.net.inner_bucket
        }
        """, "modules/net/main.tf": """
        variable "name" { type = string }
        resource "aws_vpc" "this" {
          cidr_block = "10.0.0.0/16"
          tags       = { Name = var.name, Dir = path.module }
        }
        resource "aws_subnet" "s" {
          count  = 2
          vpc_id = aws_vpc.this.id
        }
        module "inner" {
          source = "./inner"
          vpc    = aws_vpc.this.id
        }
        output "vpc_id" { value = aws_vpc.this.id }
        output "subnet_ids" { value = aws_subnet.s[*].id }
        output "inner_bucket" { value = module.inner.bucket }
        """, "modules/net/inner/main.tf": """
        variable "vpc" {}
        resource "aws_s3_bucket" "b" { bucket = "b-${var.vpc}" }
        output "bucket" { value = aws_s3_bucket.b.arn }
        """})
        assert_valid(self, raw)
        vpc = res_of(raw, "module.net.aws_vpc.this")
        self.assertEqual((vpc["file"], vpc["module"], vpc["props"]["tags"]),
                         ("modules/net/main.tf", "module.net", {"Name": "demo", "Dir": "modules/net"}))
        b = res_of(raw, "module.net.module.inner.aws_s3_bucket.b")
        self.assertEqual((b["file"], b["module"]), ("modules/net/inner/main.tf", "module.net.module.inner"))
        self.assertNotIn("via", b)
        self.assertNotIn("module.net", [r["address"] for r in raw["resources"]])  # 呼び出しは載せない
        through = {(r["from"], r["path"]): (r["to"], r["attr"], r.get("through")) for r in raw["references"]}
        self.assertEqual(through[("aws_security_group.app", "vpc_id")],
                         ("module.net.aws_vpc.this", "id", ["module.net.output.vpc_id"]))
        self.assertEqual(through[("aws_security_group.app", "subnet_id")],
                         ("module.net.aws_subnet.s[1]", "id", ["module.net.output.subnet_ids"]))
        # 出力をたどって孫のモジュールまで（from の側から順に）
        self.assertEqual(through[("aws_security_group.app", "bucket")],
                         ("module.net.module.inner.aws_s3_bucket.b", "arn",
                          ["module.net.output.inner_bucket", "module.net.module.inner.output.bucket"]))
        # 変数をたどった参照（呼び出し側のリソースへ）
        self.assertEqual(through[("module.net.module.inner.aws_s3_bucket.b", "bucket")],
                         ("module.net.aws_vpc.this", "id", ["module.net.module.inner.var.vpc"]))
        self.assertEqual(raw["evaluation"]["vars"]["module.net.name"], {"source": "argument"})
        self.assertEqual(raw["evaluation"]["vars"]["module.net.module.inner.vpc"], {"source": "argument"})

    def test_module_count_and_for_each(self):
        raw = build({"main.tf": """
        module "m" {
          source = "./m"
          count  = 2
          idx    = count.index
        }
        module "e" {
          source   = "./m"
          for_each = { a = 10, b = 20 }
          idx      = each.value
        }
        module "z" {
          source = "./m"
          count  = 0
          idx    = 1
        }
        module "n" {
          source = "./m"
          count  = var.n
          idx    = 1
        }
        variable "n" {}
        resource "aws_s3_bucket" "x" {
          one  = module.m[1].arn
          all  = module.m[*].arn
          each = module.e["b"].arn
          zero = module.z[0].arn
          many = module.n[0].arn
        }
        """, "m/main.tf": """
        variable "idx" { type = number }
        resource "aws_sqs_queue" "q" { name = "q-${var.idx}" }
        output "arn" { value = aws_sqs_queue.q.arn }
        """})
        assert_valid(self, raw)
        self.assertEqual(props(raw, "module.m[1].aws_sqs_queue.q")["name"], "q-1")
        self.assertEqual(props(raw, 'module.e["a"].aws_sqs_queue.q')["name"], "q-10")
        self.assertEqual(res_of(raw, 'module.e["b"].aws_sqs_queue.q')["module"], 'module.e["b"]')
        zero = res_of(raw, "module.z.aws_sqs_queue.q")  # count 0 のモジュール: 添字なし、作られない
        self.assertFalse(zero["enabled"])
        many = res_of(raw, "module.n[*].aws_sqs_queue.q")  # 決まらない count: ×N
        self.assertEqual((many["enabled"], many["multiplicity"]), (None, "N"))
        self.assertIn("TF-COUNT-UNRESOLVED", codes(raw, "module.n[*]"))
        p = props(raw, "aws_s3_bucket.x")
        self.assertEqual(p["one"], res("module.m[1].aws_sqs_queue.q", "arn"))
        self.assertEqual(p["all"], [res("module.m[0].aws_sqs_queue.q", "arn"), res("module.m[1].aws_sqs_queue.q", "arn")])
        self.assertEqual(p["each"], res('module.e["b"].aws_sqs_queue.q', "arn"))
        self.assertEqual(p["zero"], res("module.z.aws_sqs_queue.q", "arn"))
        self.assertEqual(p["many"], res("module.n[*].aws_sqs_queue.q", "arn"))

    def test_output_object_attribute(self):
        # 手順1 の懸念: module.alb.target_groups["app"].arn の attr が target_groups になっていた
        raw = build({"main.tf": """
        module "alb" {
          source = "./alb"
        }
        resource "aws_ecs_service" "s" {
          load_balancer {
            target_group_arn = module.alb.target_groups["app"].arn
          }
          whole = module.alb
        }
        """, "alb/main.tf": """
        resource "aws_lb_target_group" "this" {
          for_each = toset(["app", "api"])
          name     = each.key
        }
        output "target_groups" { value = aws_lb_target_group.this }
        output "name" { value = "x" }
        """})
        assert_valid(self, raw)
        p = props(raw, "aws_ecs_service.s")
        self.assertEqual(p["load_balancer"][0]["target_group_arn"], res('module.alb.aws_lb_target_group.this["app"]', "arn"))
        # module.alb そのものは、出力の名前をキーにしたオブジェクト
        self.assertEqual(p["whole"]["name"], "x")
        self.assertEqual(p["whole"]["target_groups"]["api"], res('module.alb.aws_lb_target_group.this["api"]'))

    def test_cross_module_reference_and_depends_on(self):
        raw = build({"main.tf": """
        module "db" {
          source = "./db"
        }
        module "app" {
          source     = "./app"
          db_host    = module.db.address
          depends_on = [module.db]
        }
        resource "aws_sns_topic" "t" {
          depends_on = [module.app]
        }
        """, "db/main.tf": """
        resource "aws_db_instance" "this" { identifier = "db" }
        resource "aws_db_subnet_group" "this" { name = "g" }
        output "address" { value = aws_db_instance.this.address }
        """, "app/main.tf": """
        variable "db_host" {}
        resource "aws_ecs_task_definition" "this" {
          container_definitions = jsonencode([{ environment = [{ name = "DB_HOST", value = var.db_host }] }])
        }
        """})
        assert_valid(self, raw)
        got = {(r["from"], r["path"], r["to"], r["attr"], tuple(r.get("through", []))) for r in raw["references"]}
        self.assertIn(("module.app.aws_ecs_task_definition.this", "container_definitions[0].environment[0].value",
                       "module.db.aws_db_instance.this", "address",
                       ("module.app.var.db_host", "module.db.output.address")), got)
        # モジュールの depends_on は、中のすべてのリソースから、先のモジュールのすべてのリソースへ
        for to in ("module.db.aws_db_instance.this", "module.db.aws_db_subnet_group.this"):
            self.assertIn(("module.app.aws_ecs_task_definition.this", "depends_on", to, None, ()), got)
        self.assertIn(("aws_sns_topic.t", "depends_on", "module.app.aws_ecs_task_definition.this", None, ()), got)

    def test_secret_inputs_and_outputs(self):
        files = {"main.tf": """
        variable "pw" {
          sensitive = true
          default   = "root-secret-1"
        }
        module "db" {
          source   = "./db"
          password = "child-secret-2"
          root_pw  = var.pw
        }
        resource "aws_ssm_parameter" "p" {
          value = module.db.secret
          arn   = module.db.arn
        }
        """, "db/main.tf": """
        variable "password" { sensitive = true }
        variable "root_pw" {}
        resource "aws_db_instance" "this" {
          password = var.password
          other    = var.root_pw
        }
        output "secret" {
          value     = "${aws_db_instance.this.id}-output-secret-3"
          sensitive = true
        }
        output "arn" { value = aws_db_instance.this.arn }
        """}
        raw = build(files)
        assert_valid(self, raw)
        text = tf_build.dump(raw)
        for secret in ("root-secret-1", "child-secret-2", "output-secret-3"):
            self.assertNotIn(secret, text)
        db = props(raw, "module.db.aws_db_instance.this")
        self.assertIn("$unknown", db["password"])
        self.assertIn("$unknown", db["other"])
        self.assertEqual(raw["evaluation"]["vars"]["module.db.password"], {"source": "argument", "hidden": "sensitive"})
        p = props(raw, "aws_ssm_parameter.p")
        self.assertIn("$unknown", p["value"])
        self.assertEqual(p["arn"], res("module.db.aws_db_instance.this", "arn"))
        # sensitive の出力の中の参照は unevaluated（through 付き）で残す
        self.assertIn(("aws_ssm_parameter.p", "value", "module.db.aws_db_instance.this", "id", "ref", "unevaluated"),
                      refs(raw))
        self.assertIn("TF-SENSITIVE-VAR", codes(raw, "aws_ssm_parameter.p"))

    def test_cycle_depth_unreadable_and_inputs(self):
        files = {"main.tf": """
        module "self" {
          source = "./"
        }
        module "missing" {
          source = "./nothing"
        }
        module "a" {
          source = "./a"
          extra  = 1
        }
        """, "a/main.tf": """
        variable "need" {}
        resource "aws_s3_bucket" "b" { bucket = var.need }
        module "back" {
          source = "../a"
        }
        """}
        raw = build(files)
        assert_valid(self, raw)
        self.assertIn("TF-MODULE-CYCLE", codes(raw, "module.self"))
        self.assertEqual(res_of(raw, "module.self")["via"], "module_blackbox")
        self.assertIn("TF-MODULE-UNREADABLE", codes(raw, "module.missing"))
        self.assertIn("TF-MODULE-CYCLE", codes(raw, "module.a.module.back"))
        self.assertIn("TF-VAR-UNDECLARED", codes(raw, "module.a"))  # extra は a に無い
        self.assertIn("TF-UNRESOLVED-VAR", codes(raw, "module.a.aws_s3_bucket.b"))  # need が渡されていない
        self.assertEqual(raw["evaluation"]["vars"]["module.a.need"], {"source": None})
        # 深さの上限
        deep = {"main.tf": 'module "m" {\n  source = "./m"\n}\n'}
        path = "m"
        for _ in range(module_expand.MAX_MODULE_DEPTH + 1):
            deep[f"{path}/main.tf"] = 'resource "aws_sqs_queue" "q" {}\nmodule "m" {\n  source = "./m"\n}\n'
            path += "/m"
        deep[f"{path}/main.tf"] = 'resource "aws_sqs_queue" "q" {}\n'
        raw = build(deep)
        assert_valid(self, raw)
        self.assertEqual(sum(1 for r in raw["resources"] if r["type"] == "aws_sqs_queue"), module_expand.MAX_MODULE_DEPTH)
        self.assertEqual([d["code"] for d in raw["diagnostics"] if d["code"].startswith("TF-MODULE")], ["TF-MODULE-DEPTH"])

    def test_providers_and_region_in_modules(self):
        raw = build({"main.tf": """
        provider "aws" {
          region = "ap-northeast-1"
        }
        provider "aws" {
          alias  = "use1"
          region = var.edge_region
        }
        variable "edge_region" { default = "us-east-1" }
        module "plain" {
          source = "./m"
        }
        module "edge" {
          source    = "./m"
          providers = { aws = aws.use1, aws.east = aws.use1 }
        }
        module "v6" {
          source = "./m"
          region = "eu-west-1"
        }
        """, "m/main.tf": """
        terraform {
          required_providers {
            aws = {
              source                = "hashicorp/aws"
              configuration_aliases = [aws.east]
            }
          }
        }
        variable "region" { default = null }
        resource "aws_s3_bucket" "b" { region = var.region }
        resource "aws_acm_certificate" "c" { provider = aws.east }
        resource "random_id" "r" {}
        """})
        assert_valid(self, raw)
        def pr(a):
            r = res_of(raw, a)
            return r.get("provider"), r.get("region")
        self.assertEqual(pr("module.plain.aws_s3_bucket.b"), (None, None))  # ルートの既定の provider
        self.assertEqual(pr("module.edge.aws_s3_bucket.b"), ("aws.use1", "us-east-1"))
        self.assertEqual(pr("module.edge.aws_acm_certificate.c"), ("aws.use1", "us-east-1"))
        self.assertEqual(pr("module.edge.random_id.r"), (None, None))
        self.assertEqual(pr("module.v6.aws_s3_bucket.b"), (None, "eu-west-1"))  # リソースの引数 region（v6）
        # 渡されていない alias は、設定が無い（info）
        self.assertEqual(pr("module.plain.aws_acm_certificate.c"), ("aws.east", None))
        self.assertIn("TF-PROVIDER-UNCONFIGURED", codes(raw, "module.plain.aws_acm_certificate.c"))

    def test_blackbox_create_false(self):
        # レビュー R1・R1': 黒箱の呼び出しで create 引数が false と決まるものは作られない。terraform-aws-modules の
        # 慣習なので、その source（と要約表の中の呼び出し）だけ。決まらなければ null
        raw = build("""
        variable "x" {}
        module "off" {
          source = "terraform-aws-modules/kms/aws"
          create = false
        }
        module "maybe" {
          source = "terraform-aws-modules/kms/aws"
          create = var.x
        }
        module "on" {
          source = "terraform-aws-modules/kms/aws"
          create = true
        }
        module "other" {
          source = "cloudposse/label/null"
          create = false
        }
        """)
        assert_valid(self, raw)
        self.assertFalse(res_of(raw, "module.off")["enabled"])
        self.assertIsNone(res_of(raw, "module.maybe")["enabled"])
        self.assertTrue(res_of(raw, "module.on")["enabled"])
        self.assertTrue(res_of(raw, "module.other")["enabled"])  # 別の source の create は読まない
        for a in ("module.off", "module.maybe"):
            self.assertIn("TF-MODULE-NOT-CREATED", codes(raw, a))
        for a in ("module.on", "module.other"):
            self.assertNotIn("TF-MODULE-NOT-CREATED", codes(raw, a))

    def test_null_comparison_and_az_regex(self):
        raw = build("""
        data "aws_availability_zones" "a" {}
        resource "aws_vpc" "v" {}
        locals {
          m = { k = aws_vpc.v.id }
        }
        resource "aws_s3_bucket" "b" {
          count  = local.m != null ? 1 : 0
          maybe  = aws_vpc.v.arn != null
          whole  = aws_vpc.v != null
          name   = length(regexall("^[a-z]+-", data.aws_availability_zones.a.names[0])) > 0 ? "name" : "id"
          region = length(regexall("^us-", data.aws_availability_zones.a.names[0]))
        }
        """)
        assert_valid(self, raw)
        p = props(raw, "aws_s3_bucket.b[0]")  # マップは null ではないので count が決まる
        self.assertIs(p["whole"], True)  # リソースそのもの（属性なし）は null ではない
        self.assertIn("$unknown", p["maybe"])  # リソースの属性は null かもしれない
        self.assertEqual(p["name"], "name")  # どの AZ 名でもマッチが1つ
        self.assertIn("$unknown", p["region"])  # リージョンによって違う

    def test_terraform_remote_state(self):
        raw = build("""
        data "terraform_remote_state" "network" {
          backend = "s3"
          config = {
            bucket = "tfstate"
            key    = "network/terraform.tfstate"
          }
        }
        resource "aws_instance" "web" {
          subnet_id = data.terraform_remote_state.network.outputs.subnet_ids[0]
          vpc_id    = data.terraform_remote_state.network.outputs["vpc_id"]
          whole     = data.terraform_remote_state.network.outputs
        }
        """)
        assert_valid(self, raw)
        rs = res_of(raw, "data.terraform_remote_state.network")
        self.assertEqual(rs["type"], "terraform_remote_state")
        p = props(raw, "aws_instance.web")
        self.assertEqual(p["subnet_id"], res("data.terraform_remote_state.network", "outputs.subnet_ids"))
        self.assertEqual(p["vpc_id"], res("data.terraform_remote_state.network", "outputs.vpc_id"))
        self.assertEqual(p["whole"], res("data.terraform_remote_state.network", "outputs"))


if __name__ == "__main__":
    unittest.main()
