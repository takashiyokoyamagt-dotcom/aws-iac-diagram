"""Terraform アダプタ（scripts/adapt_tf.py と scripts/aws_iac_diagram/adapters/terraform/）と評価器（evaluator/）のテスト。

フェーズ2 の手順1（土台）、手順2（A4: 変数・locals・式・count／for_each の展開）、手順3（モジュール: ローカル
モジュールの再帰、A5 の要約表、黒箱、H-IAM、terraform_remote_state、provider の受け渡し）の範囲。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "aws-iac-diagram" / "scripts"
WS = ROOT / "aws-iac-diagram-workspace"
FIXTURES = WS / "fixtures" / "tf"
PUBLIC = WS / "fixtures" / "public"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(WS / "tools"))
import validate_ir as v  # noqa: E402
import adapt_tf  # noqa: E402
from aws_iac_diagram.adapters.terraform import (  # noqa: E402
    build as tf_build, hcl, model, module_emit, module_eval, module_expand, module_load,
)
from aws_iac_diagram.adapters.terraform.evaluator import values as V  # noqa: E402
from aws_iac_diagram.adapters.terraform.evaluator import functions as F  # noqa: E402
from aws_iac_diagram.adapters.terraform.modules.sources import is_local, join_summary_source, registry_key  # noqa: E402
from aws_iac_diagram.adapters.terraform.modules import resolve as MR  # noqa: E402
from aws_iac_diagram.adapters.terraform.modules import summaries as MS  # noqa: E402
from aws_iac_diagram.core import ir_raw  # noqa: E402


def write_files(tmp: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8", newline="\n")


def build(files: dict[str, str] | str) -> dict:
    if isinstance(files, str):
        files = {"main.tf": files}
    with tempfile.TemporaryDirectory() as tmp:
        write_files(Path(tmp), files)
        return tf_build.build_raw(Path(tmp), Path(tmp))


def res_of(raw: dict, address: str) -> dict:
    return next(r for r in raw["resources"] if r["address"] == address)


def props(raw: dict, address: str) -> dict:
    return res_of(raw, address)["props"]


def refs(raw: dict, frm: str | None = None) -> list[tuple]:
    return [(r["from"], r["path"], r["to"], r["attr"], r["fn"], r["state"]) for r in raw["references"]
            if frm is None or r["from"] == frm]


def codes(raw: dict, address: str | None = None) -> list[str]:
    return [d["code"] for d in raw["diagnostics"] if address is None or d.get("address") == address]


def assert_valid(test: unittest.TestCase, raw: dict) -> None:
    test.assertEqual(v.schema_errors(raw), [])
    test.assertEqual(ir_raw.semantic_errors(raw), [])


def res(address: str, attr: str | None = None) -> dict:
    return {"$res": address, "attr": attr}


NETWORK = """
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "public" {
  count  = length(var.azs)
  vpc_id = aws_vpc.main.id
}
"""


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


class ValueTest(unittest.TestCase):
    def test_templates_and_escapes(self):
        raw = build(r'''
        variable "project" {}
        resource "aws_s3_bucket" "b" {
          bucket  = "${var.project}-docs"
          single  = "${aws_vpc.main.id}"
          literal = "$${not_a_ref} 100%%{x}"
          escaped = "a\tb\"cé"
          number  = "port-${80}"
          empty   = null
          list    = [1, -2, 3.5, true, null]
          flag    = !true
        }
        resource "aws_vpc" "main" {}
        ''')
        assert_valid(self, raw)
        p = props(raw, "aws_s3_bucket.b")
        self.assertEqual(p["bucket"]["$concat"][1], "-docs")
        self.assertIn("$unknown", p["bucket"]["$concat"][0])
        self.assertEqual(p["single"], res("aws_vpc.main", "id"))  # ${…} が1つだけなら、その値のまま
        self.assertEqual(p["literal"], "${not_a_ref} 100%{x}")
        self.assertEqual(p["escaped"], 'a\tb"cé')
        self.assertEqual(p["number"], "port-80")
        self.assertNotIn("empty", p)  # null は書かない
        self.assertEqual(p["list"], [1, -2, 3.5, True, None])
        self.assertFalse(p["flag"])
        self.assertEqual(codes(raw, "aws_s3_bucket.b"), ["TF-UNRESOLVED-VAR"])  # 値の無い変数

    def test_jsonencode_and_heredoc_json(self):
        raw = build('''
        resource "aws_s3_bucket" "docs" {}
        resource "aws_iam_policy" "p" {
          policy = jsonencode({
            Version = "2012-10-17"
            Statement = [{
              Effect   = "Allow"
              Resource = "${aws_s3_bucket.docs.arn}/*"
            }]
          })
          model = jsonencode({ "$schema" = "http://json-schema.org/draft-04/schema#", "a.b" = aws_s3_bucket.docs.id })
          doc = <<-EOT
            {"Statement": [{"Resource": "${aws_s3_bucket.docs.arn}"}]}
            EOT
          text = <<EOT
        hello ${aws_s3_bucket.docs.id}
        EOT
        }
        ''')
        assert_valid(self, raw)
        p = props(raw, "aws_iam_policy.p")
        self.assertEqual(p["policy"], {"$json": {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Resource": {"$concat": [res("aws_s3_bucket.docs", "arn"), "/*"]}}]}})
        self.assertEqual(p["model"], {"$json": {"$$schema": "http://json-schema.org/draft-04/schema#",
                                                "a.b": res("aws_s3_bucket.docs", "id")}})
        self.assertEqual(p["doc"], {"$json": {"Statement": [{"Resource": res("aws_s3_bucket.docs", "arn")}]}})
        self.assertEqual(p["text"], {"$concat": ["hello ", res("aws_s3_bucket.docs", "id"), "\n"]})
        paths = {r[1] for r in refs(raw, "aws_iam_policy.p")}
        # $json は位置に数えない。$$ で逃がしたキーと識別子でないキーは元のキーで書く（7.3）
        self.assertEqual(paths, {"policy.Statement[0].Resource", 'model["a.b"]', "doc.Statement[0].Resource", "text"})

    def test_path_workspace_and_file_functions(self):
        raw = build('''
        data "archive_file" "fn" {
          type        = "zip"
          source_dir  = "${path.module}/src"
          output_path = "${path.root}/build/fn.zip"
        }
        resource "aws_db_instance" "db" {}
        resource "aws_instance" "app" {
          tags      = { Env = terraform.workspace }
          user_data = templatefile("${path.module}/init.sh", { db = aws_db_instance.db.address })
          script    = file("init.sh")
        }
        ''')
        assert_valid(self, raw)
        self.assertEqual(props(raw, "data.archive_file.fn")["source_dir"], "./src")
        self.assertEqual(props(raw, "data.archive_file.fn")["output_path"], "./build/fn.zip")
        p = props(raw, "aws_instance.app")
        self.assertEqual(p["tags"], {"Env": "default"})
        self.assertEqual(raw["evaluation"]["assumptions"], ['terraform.workspace is evaluated as "default"'])
        self.assertIn("$unknown", p["user_data"])
        self.assertIn("$unknown", p["script"])
        # templatefile の変数に渡した参照は unevaluated で残す
        self.assertEqual(refs(raw, "aws_instance.app"),
                         [("aws_instance.app", "user_data", "aws_db_instance.db", "address", "ref", "unevaluated")])
        self.assertEqual(codes(raw, "aws_instance.app").count("TF-UNEVALUATED"), 2)

    def test_workspace_option(self):
        # --workspace（フェーズ2 の手順5）: terraform.workspace の値。既定は "default"。使ったときだけ前提に書く
        files = {"main.tf": '''
        locals { size = { default = 1, prod = 3 } }
        resource "aws_instance" "app" {
          count = local.size[terraform.workspace]
          tags  = { Env = terraform.workspace }
        }
        resource "aws_vpc" "plain" {}
        '''}
        with tempfile.TemporaryDirectory() as tmp:
            write_files(Path(tmp), files)
            dflt = tf_build.build_raw(Path(tmp), Path(tmp))
            prod = tf_build.build_raw(Path(tmp), Path(tmp), workspace="prod")
            out = Path(tmp) / "out" / "raw.json"
            cli = subprocess.run([sys.executable, str(SCRIPTS / "adapt_tf.py"), "--input", tmp, "--out", str(out),
                                  "--root-base", tmp, "--workspace", "prod"], capture_output=True)
            self.assertEqual(cli.returncode, 0, cli.stderr)
            self.assertEqual(out.read_text(encoding="utf-8"), tf_build.dump(prod))
            plan_only = subprocess.run([sys.executable, str(SCRIPTS / "adapt_tf.py"), "--input",
                                        str(WS / "fixtures" / "tf-plan" / "three-tier.dev.json"), "--out",
                                        str(Path(tmp) / "x.json"), "--workspace", "prod"], capture_output=True)
            self.assertEqual(plan_only.returncode, 2)
            self.assertIn("--workspace", plan_only.stderr.decode("utf-8", "replace"))
            for bad in ("", "a b", 'a"b', "a;b", "../x"):  # Terraform のワークスペース名として使えない名前は exit 2
                with self.subTest(workspace=bad):
                    r = subprocess.run([sys.executable, str(SCRIPTS / "adapt_tf.py"), "--input", tmp, "--out",
                                        str(Path(tmp) / "bad.json"), "--root-base", tmp, "--workspace", bad],
                                       capture_output=True)
                    self.assertEqual(r.returncode, 2, bad)
                    self.assertNotIn(b"Traceback", r.stderr)
        for raw in (dflt, prod):
            assert_valid(self, raw)
        self.assertEqual([r["address"] for r in dflt["resources"] if r["type"] == "aws_instance"],
                         ["aws_instance.app[0]"])
        self.assertEqual(props(dflt, "aws_instance.app[0]")["tags"], {"Env": "default"})
        self.assertEqual(dflt["evaluation"]["assumptions"], ['terraform.workspace is evaluated as "default"'])
        self.assertEqual(len([r for r in prod["resources"] if r["type"] == "aws_instance"]), 3)
        self.assertEqual(props(prod, "aws_instance.app[2]")["tags"], {"Env": "prod"})
        self.assertEqual(prod["evaluation"]["assumptions"], ['terraform.workspace is evaluated as "prod" (--workspace)'])
        # terraform.workspace を使わない構成では前提を書かない
        plain = build('resource "aws_vpc" "a" {}')
        self.assertEqual(plain["evaluation"]["assumptions"], [])

    def test_lifecycle_and_provisioner_references_are_not_emitted(self):
        # 見送った項目の固定（フェーズ2 の手順5）: lifecycle の replace_triggered_by と provisioner・connection の中の
        # 参照は、辺にならない参照として出さない（図の辺は属性の参照から作る。要るかはフェーズ3 で決める）
        raw = build('''
        resource "aws_vpc" "main" {}
        resource "aws_instance" "app" {
          ami = "ami-0"
          lifecycle {
            replace_triggered_by = [aws_vpc.main.id]
          }
          connection {
            host = aws_vpc.main.id
          }
          provisioner "local-exec" {
            command = "echo ${aws_vpc.main.id}"
          }
        }
        ''')
        assert_valid(self, raw)
        self.assertEqual(refs(raw, "aws_instance.app"), [])
        self.assertEqual(props(raw, "aws_instance.app"), {"ami": "ami-0"})

    def test_unknown_values_keep_references(self):
        raw = build('''
        variable "public" {}
        variable "logs" {}
        locals {
          name    = "demo"
          subnets = aws_subnet.a[*].id
          all     = concat(local.subnets, [aws_subnet.b.id])
        }
        resource "aws_subnet" "a" {}
        resource "aws_subnet" "b" {}
        resource "aws_security_group" "sg" {}
        resource "aws_lb" "app" {
          name    = local.name
          subnets = local.all
          sg      = var.public ? [aws_security_group.sg.id] : []
          ids     = [for s in aws_subnet.a : s.id]
          dynamic "access_logs" {
            for_each = var.logs
            content {
              bucket = aws_subnet.b.arn
            }
          }
        }
        ''')
        assert_valid(self, raw)
        p = props(raw, "aws_lb.app")
        self.assertEqual(p["name"], "demo")
        # local をたどって評価する（local.all → local.subnets → aws_subnet.a。count の無いスプラットは要素1つのリスト）
        self.assertEqual(p["subnets"], [res("aws_subnet.a", "id"), res("aws_subnet.b", "id")])
        for key in ("sg", "ids"):
            self.assertIn("$unknown", p[key], key)
        self.assertEqual(len(p["access_logs"]), 1)
        self.assertIn("$unknown", p["access_logs"][0])
        got = set(refs(raw, "aws_lb.app"))
        # 評価できなかった値の中の参照は unevaluated で残す
        self.assertEqual(got, {
            ("aws_lb.app", "subnets[0]", "aws_subnet.a", "id", "ref", "active"),
            ("aws_lb.app", "subnets[1]", "aws_subnet.b", "id", "ref", "active"),
            ("aws_lb.app", "sg", "aws_security_group.sg", "id", "ref", "unevaluated"),
            ("aws_lb.app", "ids", "aws_subnet.a", None, "ref", "unevaluated"),
            ("aws_lb.app", "access_logs[0]", "aws_subnet.b", "arn", "ref", "unevaluated"),
        })
        by_path = {d["path"]: d["code"] for d in raw["diagnostics"] if d["address"] == "aws_lb.app"}
        self.assertEqual(by_path, {"sg": "TF-UNRESOLVED-VAR", "access_logs[0]": "TF-UNRESOLVED-VAR",
                                   "ids": "TF-UNEVALUATED"})


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


def build_module_call(source: str, body: str, version: str | None = None) -> dict:
    """モジュールの呼び出し1つのルートを作って読む（source はルートからの相対パスかレジストリの source）。"""
    local = not registry_key(source) and not source.startswith(".")
    # ルートからの相対パスで書くので、一時フォルダは source と同じドライブに置く
    # （Windows の CI はリポジトリが D:、既定の一時フォルダが C: で、相対パスが作れない）
    with tempfile.TemporaryDirectory(dir=WS if local else None, prefix="tmp-") as tmp:
        if local:
            source = os.path.relpath(source, tmp).replace("\\", "/")
        ver = f'  version = "{version}"\n' if version else ""
        Path(tmp, "main.tf").write_text(f'module "m" {{\n  source = "{source}"\n{ver}{body}\n}}\n'
                                        'data "aws_availability_zones" "available" {}\n', encoding="utf-8")
        return tf_build.build_raw(Path(tmp), Path(tmp))


class SummaryTest(unittest.TestCase):
    """手順3: A5 の要約表（data/module-summaries/）、版の選び方、黒箱、H-IAM。"""

    def test_summary_file(self):
        summaries, iam = MS.load()
        self.assertEqual(sorted(summaries), sorted([
            "terraform-aws-modules/vpc/aws", "terraform-aws-modules/alb/aws", "terraform-aws-modules/rds/aws",
            "terraform-aws-modules/rds/aws//modules/db_instance", "terraform-aws-modules/rds/aws//modules/db_subnet_group",
            "terraform-aws-modules/rds/aws//modules/db_parameter_group",
            "terraform-aws-modules/rds/aws//modules/db_option_group",
            "terraform-aws-modules/rds/aws//modules/db_instance_role_association", "terraform-aws-modules/eks/aws",
            "terraform-aws-modules/eks/aws//modules/eks-managed-node-group",
            "terraform-aws-modules/eks/aws//modules/fargate-profile",
            "terraform-aws-modules/eks/aws//modules/self-managed-node-group"]))
        self.assertEqual(iam, ("terraform-aws-modules/iam/aws",))
        for key, items in summaries.items():
            for s in items:
                with self.subTest(key):
                    tree = module_load.summary_tree(s)  # HCL として読める
                    mod = module_eval.ModuleEval(model.Context(Path(".")), None)
                    mod.summary = s
                    mod.collect(tree, "main.tf")
                    self.assertTrue(mod.outputs)
                    # 表の中の data は擬似パラメータに使うもの（引数の無い aws_partition など）だけ
                    for blk in mod.blocks.values():
                        if blk.kind == "data":
                            self.assertTrue(blk.plain and not blk.attrs, blk.base)
        self.assertIn("enable_flow_log", summaries["terraform-aws-modules/vpc/aws"][0].uncovered)
        self.assertIn("listeners.*.authenticate_cognito", summaries["terraform-aws-modules/alb/aws"][0].uncovered)

    def test_choose_version(self):
        def pick(source, version):
            s, why, note = MR.choose(source, version)
            return (s.majors if s else None), why, note
        vpc = "terraform-aws-modules/vpc/aws"
        self.assertEqual(pick(vpc, "~> 6.7")[0], (6,))
        self.assertEqual(pick(vpc, "6.6.0")[:3], ((6,), "", None))
        self.assertEqual(pick(vpc, ">= 6.0, < 7.0")[:3], ((6,), "", None))
        self.assertIn("allows majors 5 to 6", pick(vpc, ">= 5.0, < 7.0")[2])  # 2つの major にまたがる
        self.assertEqual(pick("registry.terraform.io/" + vpc, "~> 6.0")[0], (6,))
        got = pick(vpc, None)
        self.assertEqual(got[0], (6,))
        self.assertIn("not pinned", got[2])
        self.assertIn("no upper major", pick(vpc, ">= 5.0")[2])
        for v in ("~> 5.0", "5.8.1", "2.77.0", "< 6.0"):
            with self.subTest(v):
                majors, why, _ = pick(vpc, v)
                self.assertIsNone(majors)
                self.assertIn("it has 6.x", why)
        self.assertEqual(pick("terraform-aws-modules/eks/aws", "~> 21.0")[0], (21,))
        self.assertIsNone(pick("terraform-aws-modules/eks/aws", "20.8.5")[0])
        self.assertEqual(pick("terraform-aws-modules/rds/aws//modules/db_instance", "~> 7.0")[0], (7,))
        self.assertIsNone(pick("terraform-aws-modules/s3-bucket/aws", "~> 4.0")[0])
        self.assertIsNone(pick(vpc, "~> foo")[0])

    def test_source_kinds_and_iam_only(self):
        self.assertTrue(is_local("./modules/x") and is_local("../../") and not is_local("modules/x"))
        self.assertEqual(registry_key("terraform-aws-modules/iam/aws//modules/iam-role/"),
                         "terraform-aws-modules/iam/aws//modules/iam-role")
        for src in ("git::https://example.com/x.git", "github.com/org/repo", "s3::https://b/x.zip",
                    "https://example.com/x.zip", "hashicorp/consul/aws?ref=1"):
            self.assertIsNone(registry_key(src), src)
        self.assertEqual(join_summary_source("terraform-aws-modules/rds/aws", "./modules/db_instance"),
                         "terraform-aws-modules/rds/aws//modules/db_instance")
        self.assertEqual(join_summary_source("a/b/c//modules/x", "../y"), "a/b/c//modules/y")
        self.assertTrue(MS.iam_only("terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"))
        self.assertTrue(MS.iam_only("registry.terraform.io/terraform-aws-modules/iam/aws"))
        self.assertFalse(MS.iam_only("terraform-aws-modules/iam-foo/aws"))
        self.assertFalse(MS.iam_only("terraform-aws-modules/vpc/aws"))
        # IAM だけのモジュールは黒箱の呼び出し（正規化が H-IAM にする）。理由に H-IAM と書く
        raw = build("""
        module "irsa" {
          source  = "terraform-aws-modules/iam/aws//modules/iam-assumable-role-with-oidc"
          version = "5.39.0"
          role_name = "x"
        }
        """)
        assert_valid(self, raw)
        r = res_of(raw, "module.irsa")
        self.assertEqual((r["type"], r["via"], r["version"]), ("module", "module_blackbox", "5.39.0"))
        msg = next(d["message"] for d in raw["diagnostics"] if d["code"] == "TF-MODULE-BLACKBOX")
        self.assertIn("H-IAM", msg)

    def test_summary_expansion_diagnostics(self):
        raw = build("""
        module "vpc" {
          source  = "terraform-aws-modules/vpc/aws"
          version = "~> 6.0"
          name    = "n"
          azs     = ["ap-northeast-1a"]
          public_subnets  = ["10.0.0.0/24"]
          enable_flow_log = true
          not_a_variable  = 1
          region          = "us-west-2"
        }
        module "old" {
          source  = "terraform-aws-modules/vpc/aws"
          version = "5.8.1"
          name    = "old"
        }
        resource "aws_instance" "x" {
          subnet_id = module.vpc.public_subnets[0]
          acl       = module.vpc.public_network_acl_id
        }
        """)
        assert_valid(self, raw)
        sub = res_of(raw, "module.vpc.aws_subnet.public[0]")
        self.assertEqual((sub["via"], sub["file"], sub["module"], sub["region"]),
                         ("module_summary", "main.tf", "module.vpc", "us-west-2"))
        self.assertEqual(sub["props"]["tags"], {"Name": "n-public-ap-northeast-1a"})
        self.assertNotIn("module.vpc.aws_nat_gateway.this", [r["address"] for r in raw["resources"]])  # count 0 は載せない
        diags = {d["code"]: d for d in raw["diagnostics"] if d.get("address") == "module.vpc"}
        self.assertIn("TF-MODULE-SUMMARY", diags)
        self.assertIn("enable_flow_log, not_a_variable", diags["TF-MODULE-SUMMARY-INPUT"]["message"])
        old = res_of(raw, "module.old")
        self.assertEqual((old["via"], old["version"]), ("module_blackbox", "5.8.1"))
        self.assertIn("it has 6.x", next(d["message"] for d in raw["diagnostics"] if d["address"] == "module.old"))
        p = props(raw, "aws_instance.x")
        self.assertEqual(p["subnet_id"], res("module.vpc.aws_subnet.public[0]", "id"))
        self.assertIn("$unknown", p["acl"])  # 要約表に無い出力
        self.assertIn("TF-MODULE-SUMMARY-OUTPUT", codes(raw, "aws_instance.x"))
        self.assertFalse([k for k in raw["evaluation"]["vars"] if k.startswith("module.")])  # 要約表の変数は書かない

    def compare_with_source(self, real_dir: Path, source: str, version: str, body: str, allowed: set):
        """同じ入力で、手元の本物のソースと要約表を展開し、address と、要約表のリソースの間の参照を比べる。"""
        real = build_module_call(str(real_dir), body)
        summ = build_module_call(source, body, version)
        for raw in (real, summ):
            assert_valid(self, raw)

        def made(raw):
            return {r["address"]: r for r in raw["resources"] if r["enabled"] is not False
                    and not r["address"].startswith("data.") and ".data." not in r["address"]}
        a, b = made(real), made(summ)
        self.assertEqual(set(a) ^ set(b), allowed)
        def act(raw, keep):
            return {(r["from"], r["path"], r["to"], r["attr"]) for r in raw["references"]
                    if r["state"] == "active" and r["from"] in keep and r["to"] in keep}
        common = set(a) & set(b)
        self.assertEqual(act(real, common), act(summ, common))
        for addr in sorted(common):
            for k in ("tags", "name", "cluster_name", "node_group_name", "fargate_profile_name"):
                self.assertEqual(a[addr]["props"].get(k), b[addr]["props"].get(k), (addr, k))
        self.assertFalse([d for d in summ["diagnostics"] if d["level"] != "info"])
        return b

    def test_alb_summary_matches_source(self):
        src = PUBLIC / "terraform-aws-alb"  # v10.5.1（2026-10-17 に取得）
        three_tier = '''
  name               = "demo-alb"
  load_balancer_type = "application"
  vpc_id             = "vpc-1"
  subnets            = ["subnet-a", "subnet-b"]
  enable_deletion_protection = false
  security_group_ingress_rules = {
    all_http = { from_port = 80, to_port = 80, ip_protocol = "tcp", cidr_ipv4 = "0.0.0.0/0" }
  }
  security_group_egress_rules = { all = { ip_protocol = "-1", cidr_ipv4 = "10.0.0.0/16" } }
  listeners = {
    http = { port = 80, protocol = "HTTP", forward = { target_group_key = "app" } }
  }
  target_groups = {
    app = { name = "demo-app", protocol = "HTTP", port = 8080, target_type = "ip", create_attachment = false,
            health_check = { path = "/" } }
  }
  tags = { Project = "demo" }'''
        got = self.compare_with_source(src, "terraform-aws-modules/alb/aws", "~> 10.0", three_tier, set())
        self.assertEqual(len(got), 6)
        rules = '''
  name    = "ex"
  vpc_id  = "vpc-1"
  subnets = ["subnet-a", "subnet-b"]
  listeners = {
    ex-http = {
      port = 80
      protocol = "HTTP"
      fixed_response = { content_type = "text/plain", message_body = "404", status_code = "404" }
      rules = {
        production = {
          priority = 1
          actions = [{ weighted_forward = { target_groups = [{ target_group_key = "ex-ecs", weight = 100 },
                                                             { target_group_key = "ex-alt", weight = 0 }] } }]
          conditions = [{ path_pattern = { values = ["/*"] } }]
        }
        fwd = {
          priority = 2
          actions = [{ forward = { target_group_key = "ex-alt" } }]
          conditions = [{ host_header = { values = ["a.example.com"] } }]
        }
      }
    }
    https = {
      port = 443
      protocol = "HTTPS"
      certificate_arn = "arn:aws:acm:us-east-1:111122223333:certificate/a"
      additional_certificate_arns = ["arn:aws:acm:us-east-1:111122223333:certificate/b"]
      weighted_forward = { target_groups = [{ target_group_key = "ex-ecs", weight = 1 }] }
    }
    redirect = {
      port = 8080
      redirect = { port = "443", protocol = "HTTPS", status_code = "HTTP_301" }
    }
  }
  target_groups = {
    ex-ecs = { protocol = "HTTP", port = 80, target_type = "ip", create_attachment = false }
    ex-alt = { protocol = "HTTP", port = 80, target_type = "ip", create_attachment = false }
    lambda = { target_type = "lambda", target_id = "arn:aws:lambda:us-east-1:111122223333:function:fn",
               attach_lambda_permission = true }
  }
  route53_records = { a = { zone_id = "Z1", type = "A" } }'''
        got = self.compare_with_source(src, "terraform-aws-modules/alb/aws", "~> 10.0", rules, set())
        self.assertEqual(len(got), 14)
        for a in ('module.m.aws_lb_listener_rule.this["ex-http/production"]', 'module.m.aws_lambda_permission.this["lambda"]',
                  'module.m.aws_lb_listener_certificate.this["https/0"]', 'module.m.aws_route53_record.this["a"]'):
            self.assertIn(a, got)

    def test_rds_summary_matches_source(self):
        src = PUBLIC / "terraform-aws-rds"  # v7.2.2（2026-10-17 に取得）
        fixture = '''
  identifier = "demo-db"
  engine = "postgres"
  engine_version = "17.9"
  family = "postgres17"
  major_engine_version = "17"
  instance_class = "db.t4g.micro"
  allocated_storage = 20
  db_name = "app"
  username = "app_admin"
  port = "5432"
  manage_master_user_password = true
  db_subnet_group_name = "grp"
  vpc_security_group_ids = ["sg-1"]
  create_db_subnet_group = false
  create_db_parameter_group = false
  create_db_option_group = false
  create_monitoring_role = false
  skip_final_snapshot = true
  tags = { Project = "demo" }'''
        got = self.compare_with_source(src, "terraform-aws-modules/rds/aws", "~> 7.0", fixture, set())
        self.assertEqual(list(got), ["module.m.module.db_instance.aws_db_instance.this[0]"])
        mysql = '''
  identifier = "my"
  engine = "mysql"
  engine_version = "8.0"
  family = "mysql8.0"
  major_engine_version = "8.0"
  instance_class = "db.t4g.large"
  allocated_storage = 20
  db_name = "app"
  username = "u"
  port = 3306
  subnet_ids = ["subnet-a", "subnet-b"]
  create_db_subnet_group = true
  vpc_security_group_ids = ["sg-1"]
  monitoring_interval = 30
  create_monitoring_role = true
  enabled_cloudwatch_logs_exports = ["general"]
  create_cloudwatch_log_group = true
  multi_az = true'''
        got = self.compare_with_source(src, "terraform-aws-modules/rds/aws", "~> 7.0", mysql, set())
        self.assertEqual(len(got), 8)
        self.assertIn('module.m.module.db_instance.aws_cloudwatch_log_group.this["general"]', got)

    def test_summary_nested_uncovered_inputs(self):
        # レビュー M1: 写していない入力が入れ子のキー（listeners の中の認証など）でも、渡されたら診断に書く。
        # weighted_forward とルールの forward は写したので、リスナー・ルール → TG の参照が出る
        raw = build("""
        module "alb" {
          source  = "terraform-aws-modules/alb/aws"
          version = "~> 10.0"
          name    = "x"
          listeners = {
            http = {
              port             = 80
              weighted_forward = { target_groups = [{ target_group_key = "a" }] }
              rules = {
                r1 = {
                  actions = [{ forward = { target_group_key = "a" } }]
                  conditions = [{ path_pattern = { values = ["/"] } }]
                }
                auth = {
                  actions = [{ authenticate_oidc = { authorization_endpoint = "https://e", client_id = "c",
                                                     client_secret = "s", issuer = "i", token_endpoint = "t",
                                                     user_info_endpoint = "u" } },
                             { forward = { target_group_key = "a" } }]
                  conditions = [{ path_pattern = { values = ["/a"] } }]
                }
              }
            }
            https = {
              port                 = 443
              protocol             = "HTTPS"
              authenticate_cognito = { user_pool_arn = "arn", user_pool_client_id = "c", user_pool_domain = "d" }
              forward              = { target_group_key = "a" }
            }
          }
          target_groups = {
            a = { protocol = "HTTP", port = 80, target_type = "ip", create_attachment = false }
          }
        }
        """)
        assert_valid(self, raw)
        got = refs(raw)
        tg = 'module.alb.aws_lb_target_group.this["a"]'
        self.assertIn(('module.alb.aws_lb_listener.this["http"]', "default_action[0].forward[0].target_group[0].arn",
                       tg, "arn", "ref", "active"), got)
        self.assertIn(('module.alb.aws_lb_listener_rule.this["http/r1"]', "action[0].target_group_arn", tg, "arn",
                       "ref", "active"), got)
        msg = next(d["message"] for d in raw["diagnostics"] if d["code"] == "TF-MODULE-SUMMARY-INPUT")
        self.assertIn("listeners.*.authenticate_cognito", msg)
        self.assertIn("listeners.*.rules.*.actions.*.authenticate_oidc", msg)
        self.assertNotIn("jwt_validation", msg)  # 渡していないもの（null）は書かない
        raw2 = build("""
        variable "ls" {}
        module "alb" {
          source    = "terraform-aws-modules/alb/aws"
          version   = "~> 10.0"
          listeners = var.ls
        }
        """)
        assert_valid(self, raw2)
        unknown = [d for d in raw2["diagnostics"] if d["code"] == "TF-MODULE-SUMMARY-INPUT" and d["path"] == "unknown"]
        self.assertEqual([d["level"] for d in unknown], ["info"])
        self.assertIn("could not be checked", unknown[0]["message"])
        self.assertNotIn("TF-MODULE-SUMMARY-INPUT", codes(build("""
        module "alb" {
          source  = "terraform-aws-modules/alb/aws"
          version = "~> 10.0"
          listeners = { http = { port = 80, forward = { target_group_key = "a" } } }
          target_groups = { a = { target_type = "ip", create_attachment = false } }
        }
        """)))

    def test_path_present(self):
        p = module_emit.path_present
        v = {"a": {"rules": {"r": {"actions": [{"x": None}, {"y": 1}]}}}, "b": {"rules": {}}}
        self.assertTrue(p(v, ["*", "rules", "*", "actions", "*", "y"]))
        self.assertFalse(p(v, ["*", "rules", "*", "actions", "*", "x"]))
        self.assertFalse(p(v, ["*", "nothing"]))
        self.assertIsNone(p(V.Unknown("u"), ["*"]))  # 決まらず調べられない
        self.assertIsNone(p({"a": V.Unknown("u")}, ["*", "rules"]))
        self.assertTrue(p({"a": V.Unknown("u"), "b": {"rules": 1}}, ["*", "rules"]))
        self.assertFalse(p({"a": {"rules": {}}, "b": {"rules": []}}, ["*", "rules"]))  # 空の {}・[] は当てない
        self.assertTrue(p({"a": {"rules": V.Res("aws_x.y", "arn")}}, ["*", "rules"]))

    def test_vpc_summary_matches_source(self):
        src = PUBLIC / "terraform-aws-vpc"  # v6.7.3（P01）
        cases = [
            ("~> 6.7", '''
  name = "demo"
  cidr = "10.0.0.0/16"
  azs  = ["ap-northeast-1a", "ap-northeast-1c"]
  public_subnets   = ["10.0.0.0/24", "10.0.1.0/24"]
  private_subnets  = ["10.0.10.0/24", "10.0.11.0/24"]
  database_subnets = ["10.0.20.0/24", "10.0.21.0/24"]
  enable_nat_gateway = true
  single_nat_gateway = true
  create_database_subnet_group       = true
  create_database_subnet_route_table = true
  tags = { Project = "demo" }''', 25),
            ("~> 6.0", '''
  name = "ex"
  cidr = "10.0.0.0/16"
  azs  = slice(data.aws_availability_zones.available.names, 0, 3)
  public_subnets  = ["10.0.0.0/20", "10.0.16.0/20", "10.0.32.0/20"]
  private_subnets = ["10.0.48.0/20", "10.0.64.0/20", "10.0.80.0/20"]
  intra_subnets   = ["10.0.96.0/20", "10.0.112.0/20", "10.0.128.0/20"]
  enable_nat_gateway     = true
  one_nat_gateway_per_az = true
  enable_vpn_gateway     = true
  public_subnet_tags = { "kubernetes.io/role/elb" = 1 }''', 39),
            ("6.6.0", '''
  name = "rds"
  cidr = "10.1.0.0/16"
  azs  = ["us-east-1a", "us-east-1b"]
  public_subnets   = ["10.1.0.0/24", "10.1.1.0/24"]
  database_subnets = ["10.1.20.0/24", "10.1.21.0/24"]
  create_database_internet_gateway_route = true
  create_database_subnet_route_table     = true
  manage_default_security_group          = false''', 17),
        ]
        for version, body, n in cases:
            with self.subTest(version):
                got = self.compare_with_source(src, "terraform-aws-modules/vpc/aws", version, body, set())
                self.assertEqual(len(got), n)
        got = self.compare_with_source(src, "terraform-aws-modules/vpc/aws", "~> 6.0", cases[1][1], set())
        self.assertEqual(got["module.m.aws_subnet.public[2]"]["props"]["availability_zone"], {"$az": 2})

    def test_eks_summary_matches_source(self):
        src = PUBLIC / "terraform-aws-eks"  # v21.29.0（P03）
        body = '''
  name               = "ex-eks"
  kubernetes_version = "1.33"
  endpoint_public_access = true
  enable_cluster_creator_admin_permissions = true
  addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni    = { before_compute = true }
  }
  vpc_id     = "vpc-123"
  subnet_ids = ["subnet-1", "subnet-2"]
  eks_managed_node_groups = {
    example = {
      instance_types = ["m6i.large"]
      min_size     = 2
      desired_size = 2
    }
  }
  fargate_profiles = {
    kube-system = {
      selectors = [{ namespace = "kube-system" }]
    }
  }
  self_managed_node_groups = {
    smng = { instance_type = "m6i.large" }
  }
  access_entries = {
    ex = {
      principal_arn = "arn:aws:iam::111122223333:role/ex"
      policy_associations = {
        view = {
          policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"
          access_scope = { type = "cluster" }
        }
      }
    }
  }'''
        # 意図した違い: ユーザーデータのサブモジュールの null_resource（表に写していない）
        allowed = {'module.m.module.eks_managed_node_group["example"].module.user_data.null_resource.validate_cluster_service_cidr',
                   'module.m.module.self_managed_node_group["smng"].module.user_data.null_resource.validate_cluster_service_cidr'}
        got = self.compare_with_source(src, "terraform-aws-modules/eks/aws", "~> 21.0", body, allowed)
        self.assertEqual(len(got), 48)
        kms = got["module.m.module.kms"]  # 表の中の黒箱の呼び出し（本物と同じ address）
        self.assertEqual((kms["via"], kms["enabled"], kms["version"]), ("module_blackbox", True, "4.0.0"))
        # 暗号化しない（create = false）と、黒箱の呼び出しは enabled: false
        off = build_module_call("terraform-aws-modules/eks/aws", '\n  name = "x"\n  encryption_config = null', "~> 21.0")
        assert_valid(self, off)
        self.assertFalse(res_of(off, "module.m.module.kms")["enabled"])
        ng = got['module.m.module.eks_managed_node_group["example"].aws_eks_node_group.this[0]']
        self.assertEqual(ng["props"]["scaling_config"], [{"min_size": 2, "max_size": 3, "desired_size": 2}])


class ProviderTest(unittest.TestCase):
    def test_provider_alias_and_region(self):
        raw = build("""
        provider "aws" {
          region = var.region
        }
        provider "aws" {
          alias  = "us_east_1"
          region = "us-east-1"
        }
        provider "aws" {
          alias  = "dr"
          region = var.dr_region
        }
        resource "aws_acm_certificate" "cert" {
          provider    = aws.us_east_1
          domain_name = "example.com"
        }
        resource "aws_s3_bucket" "dr" {
          provider = aws.dr
        }
        resource "aws_s3_bucket" "main" {
          provider = aws
        }
        resource "aws_s3_bucket" "lost" {
          provider = aws.nowhere
        }
        """)
        assert_valid(self, raw)
        cert = res_of(raw, "aws_acm_certificate.cert")
        self.assertEqual((cert["provider"], cert["region"]), ("aws.us_east_1", "us-east-1"))
        self.assertNotIn("provider", cert["props"])
        dr = res_of(raw, "aws_s3_bucket.dr")
        self.assertEqual(dr["provider"], "aws.dr")
        self.assertNotIn("region", dr)  # region が決まらない（手順2）
        self.assertNotIn("provider", res_of(raw, "aws_s3_bucket.main"))  # 既定の provider は書かない
        self.assertIn("TF-PROVIDER-UNCONFIGURED", codes(raw, "aws_s3_bucket.lost"))

    def test_resource_region_argument_and_quoted_provider(self):
        raw = build("""
        provider "aws" {
          alias  = "w"
          region = "us-west-2"
        }
        resource "aws_s3_bucket" "regional" {
          region = "eu-west-1"
        }
        resource "aws_s3_bucket" "both" {
          provider = aws.w
          region   = "eu-west-1"
        }
        resource "aws_s3_bucket" "quoted" {
          provider = "aws.w"
        }
        resource "random_id" "x" {
          region = "not-a-region"
        }
        """)
        assert_valid(self, raw)
        # リソースの引数 region（AWS provider v6）は provider の region より優先する（Terraform と同じ）
        regional = res_of(raw, "aws_s3_bucket.regional")
        self.assertEqual((regional.get("provider"), regional["region"]), (None, "eu-west-1"))
        self.assertEqual(regional["props"]["region"], "eu-west-1")
        both = res_of(raw, "aws_s3_bucket.both")
        self.assertEqual((both["provider"], both["region"]), ("aws.w", "eu-west-1"))
        quoted = res_of(raw, "aws_s3_bucket.quoted")  # 古い書き方の文字列も読む
        self.assertEqual((quoted["provider"], quoted["region"]), ("aws.w", "us-west-2"))
        self.assertNotIn("region", res_of(raw, "random_id.x"))  # AWS の型だけ



class VariableTest(unittest.TestCase):
    """変数の値の決め方（A4）。Terraform と同じ読み順で、後のものが優先する。"""

    MAIN = """
    variable "a" { default = "default" }
    variable "b" { default = "default" }
    variable "c" { default = "default" }
    variable "d" { default = "default" }
    variable "e" { default = "default" }
    variable "f" { default = "default" }
    resource "aws_s3_bucket" "x" {
      tags = { a = var.a, b = var.b, c = var.c, d = var.d, e = var.e, f = var.f }
    }
    """

    def test_precedence(self):
        files = {"main.tf": self.MAIN,
                 "terraform.tfvars": 'a = "tfvars"\nb = "tfvars"\nc = "tfvars"\nd = "tfvars"\ne = "tfvars"\n',
                 "terraform.tfvars.json": '{"b": "tfvars.json", "c": "tfvars.json", "d": "tfvars.json", "e": "tfvars.json"}',
                 "b.auto.tfvars": 'c = "b.auto"\nd = "b.auto"\n',
                 "a.auto.tfvars.json": '{"c": "a.auto.json", "d": "a.auto.json"}',
                 "extra.tfvars": 'd = "var-file"\ne = "var-file"\n'}
        with tempfile.TemporaryDirectory() as tmp:
            write_files(Path(tmp), files)
            raw = tf_build.build_raw(Path(tmp), Path(tmp), var_args=[("file", str(Path(tmp) / "extra.tfvars")),
                                                               ("var", "e=cli")])
        assert_valid(self, raw)
        self.assertEqual(props(raw, "aws_s3_bucket.x")["tags"],
                         {"a": "tfvars", "b": "tfvars.json", "c": "b.auto", "d": "var-file", "e": "cli", "f": "default"})
        # *.auto.tfvars(.json) はファイル名の順（a.auto.tfvars.json → b.auto.tfvars）
        self.assertEqual(raw["evaluation"]["var_files"], ["terraform.tfvars", "terraform.tfvars.json",
                                                          "a.auto.tfvars.json", "b.auto.tfvars", "extra.tfvars"])
        # evaluation.vars には値を書かず、値の出どころだけを書く（第三者レビューの R1）
        self.assertEqual(raw["evaluation"]["vars"], {
            "a": {"source": "terraform.tfvars"}, "b": {"source": "terraform.tfvars.json"},
            "c": {"source": "b.auto.tfvars"}, "d": {"source": "extra.tfvars"}, "e": {"source": "--var"},
            "f": {"source": "default"}})

    def test_cli_order_and_var_file_relative_to_input(self):
        files = {"main.tf": self.MAIN, "env/one.tfvars": 'a = "one"\n', "env/two.tfvars": 'a = "two"\n'}
        with tempfile.TemporaryDirectory() as tmp:
            write_files(Path(tmp), files)
            out = Path(tmp) / "out.json"
            # --var-file と --var は指定した順に後のものが優先する。相対パスは作業中のフォルダ、無ければ --input から
            code = adapt_tf.main(["--input", tmp, "--out", str(out), "--var", "a=cli", "--var-file", "env/one.tfvars",
                            "--var-file", "env/two.tfvars", "--root-base", tmp])
            self.assertEqual(code, 0)
            raw = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(props(raw, "aws_s3_bucket.x")["tags"]["a"], "two")
            self.assertEqual(raw["evaluation"]["vars"]["a"], {"source": "env/two.tfvars"})
            self.assertEqual(raw["evaluation"]["var_files"], ["env/one.tfvars", "env/two.tfvars"])
            adapt_tf.main(["--input", tmp, "--out", str(out), "--var-file", "env/one.tfvars", "--var", "a=cli"])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["evaluation"]["vars"]["a"], {"source": "--var"})
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(adapt_tf.main(["--input", tmp, "--out", str(out), "--var-file", "env/none.tfvars"]), 2)
                self.assertEqual(adapt_tf.main(["--input", tmp, "--out", str(out), "--var", "novalue"]), 2)
            self.assertIn("none.tfvars", err.getvalue())

    def test_types_and_unknown_values(self):
        raw = build({"main.tf": """
        variable "n" { type = number }
        variable "flag" { type = bool }
        variable "names" { type = list(string) }
        variable "cfg" {
          type    = object({ name = string, size = optional(number, 3), note = optional(string) })
          default = { name = "x", ignored = 1 }
        }
        variable "nothing" {}
        variable "secret" {
          default   = "p@ss"
          sensitive = true
        }
        variable "nul" { default = null }
        resource "aws_s3_bucket" "x" {
          count = var.n
          tags  = { flag = var.flag, names = join(",", var.names), cfg = var.cfg, nothing = var.nothing }
          pw    = var.secret
          nul   = var.nul
        }
        """, "terraform.tfvars": 'n = "2"\nflag = "true"\nnames = ["b", 1]\nundeclared = 1\n'})
        assert_valid(self, raw)
        # tfvars の文字列は type に合わせて変換する。object の optional は既定値で埋め、型に無い属性は落とす
        self.assertEqual([r["address"] for r in raw["resources"]], ["aws_s3_bucket.x[0]", "aws_s3_bucket.x[1]"])
        p = props(raw, "aws_s3_bucket.x[0]")
        self.assertEqual({k: p["tags"][k] for k in ("flag", "names", "cfg")},
                         {"flag": True, "names": "b,1", "cfg": {"name": "x", "size": 3, "note": None}})
        self.assertEqual(p["tags"]["nothing"], {"$unknown": "variable nothing has no value"})
        # sensitive の変数の値は使わず、evaluation.vars にも書かない
        self.assertIn("$unknown", p["pw"])
        self.assertNotIn("nul", p)
        self.assertEqual(raw["evaluation"]["vars"], {
            "cfg": {"source": "default"}, "flag": {"source": "terraform.tfvars"}, "n": {"source": "terraform.tfvars"},
            "names": {"source": "terraform.tfvars"}, "nothing": {"source": None}, "nul": {"source": "default"},
            "secret": {"source": "default", "hidden": "sensitive"}})
        self.assertNotIn("p@ss", json.dumps(raw))
        levels = {(d["path"], d["code"]): d["level"] for d in raw["diagnostics"] if d["address"] == "aws_s3_bucket.x[0]"}
        self.assertEqual(levels, {("tags.nothing", "TF-UNRESOLVED-VAR"): "warn", ("pw", "TF-SENSITIVE-VAR"): "info"})
        self.assertIn("TF-VAR-UNDECLARED", codes(raw, ""))

    def test_cli_var_complex_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_files(Path(tmp), {"main.tf": """
            variable "azs" { type = list(string) }
            variable "name" { type = string }
            resource "aws_subnet" "s" {
              count = length(var.azs)
              availability_zone = var.azs[count.index]
              tags = { Name = var.name }
            }
            """})
            raw = tf_build.build_raw(Path(tmp), Path(tmp), vars={}, var_args=[("var", 'azs=["a", "b", "c"]'),
                                                                        ("var", "name=a=b")])
        assert_valid(self, raw)
        self.assertEqual(len(raw["resources"]), 3)
        self.assertEqual(props(raw, "aws_subnet.s[2]")["availability_zone"], "c")
        # 文字列の型の変数は、値をそのまま文字列として使う（最初の = で分ける。Terraform の -var と同じ）
        self.assertEqual(props(raw, "aws_subnet.s[0]")["tags"]["Name"], "a=b")


class ReviewFixTest(unittest.TestCase):
    """手順2 の第三者レビュー（判定「修正後コミット」）で直したものの再現ケース。"""

    def test_sensitive_function_and_ephemeral_variable(self):
        # M1: sensitive() の値と ephemeral = true の変数の値を、props と evaluation.vars に書かない
        raw = build({"main.tf": '''
        variable "pw" { default = "pw-123" }
        variable "eph" {
          ephemeral = true
          default   = "eph-456"
        }
        resource "aws_secretsmanager_secret" "s" {}
        locals { token = sensitive("tok-123") }
        resource "aws_db_instance" "db" {
          password = sensitive(var.pw)
          token    = local.token
          eph      = var.eph
          ref      = sensitive(aws_secretsmanager_secret.s.arn)
          name     = nonsensitive("db")
        }
        '''})
        assert_valid(self, raw)
        text = json.dumps(raw, ensure_ascii=False)
        for secret in ("tok-123", "eph-456"):
            self.assertNotIn(secret, text)
        p = props(raw, "aws_db_instance.db")
        for key in ("password", "token", "eph", "ref"):
            self.assertIn("$unknown", p[key], key)
        self.assertEqual(p["name"], "db")
        self.assertEqual(raw["evaluation"]["vars"], {"pw": {"source": "default"},
                                                     "eph": {"source": "default", "hidden": "ephemeral"}})
        levels = {(d["path"], d["code"], d["level"]) for d in raw["diagnostics"] if d["address"] == "aws_db_instance.db"}
        self.assertEqual(levels, {(k, "TF-SENSITIVE-VAR", "info") for k in ("password", "token", "eph", "ref")})
        # 中の参照は引き継ぐ
        self.assertIn(("aws_db_instance.db", "ref", "aws_secretsmanager_secret.s", "arn", "ref", "unevaluated"),
                      refs(raw))

    def test_redact_var(self):
        # R1: --redact-var で指定した変数の値を props から伏せる（sensitive = true と同じ扱い。中の参照は保つ）
        with tempfile.TemporaryDirectory() as tmp:
            write_files(Path(tmp), {"main.tf": '''
            variable "token" { default = "tok-789" }
            variable "name" { default = "app" }
            resource "aws_s3_bucket" "a" {}
            resource "aws_ssm_parameter" "p" {
              name  = var.name
              value = "${var.token}-${aws_s3_bucket.a.id}"
            }
            '''})
            out = Path(tmp) / "out.json"
            self.assertEqual(adapt_tf.main(["--input", tmp, "--out", str(out), "--redact-var", "token",
                                      "--redact-var", "nothing"]), 0)
            raw = json.loads(out.read_text(encoding="utf-8"))
        assert_valid(self, raw)
        self.assertNotIn("tok-789", json.dumps(raw))
        p = props(raw, "aws_ssm_parameter.p")
        self.assertEqual(p["name"], "app")  # 伏せていない変数の値は props に入る
        self.assertIn("$unknown", p["value"]["$concat"][0])
        self.assertIn(("aws_ssm_parameter.p", "value", "aws_s3_bucket.a", "id", "ref", "active"), refs(raw))
        self.assertEqual(raw["evaluation"]["vars"]["token"], {"source": "default", "hidden": "redact-var"})
        levels = {(d["code"], d["level"]) for d in raw["diagnostics"]}
        self.assertIn(("TF-SENSITIVE-VAR", "info"), levels)
        self.assertIn(("TF-VAR-UNDECLARED", "warn"), levels)  # 宣言に無い名前

    def test_disabled_block_keeps_reference_errors(self):
        # R2: 作られないブロックで info に下げるのは値が決まらないことによる code だけ（参照の誤り・循環は warn）
        raw = build('''
        variable "nothing" {}
        locals {
          a = local.b
          b = local.a
        }
        resource "aws_instance" "off" {
          count   = 0
          missing = aws_vpc.nowhere.id
          cycle   = local.a
          novalue = var.nothing
          index   = [1][3]
        }
        ''')
        assert_valid(self, raw)
        levels = {d["path"]: (d["code"], d["level"]) for d in raw["diagnostics"] if d["address"] == "aws_instance.off"}
        self.assertEqual(levels, {"missing": ("TF-UNDEFINED-REF", "warn"), "cycle": ("TF-CYCLE", "warn"),
                                  "novalue": ("TF-UNRESOLVED-VAR", "info"), "index": ("TF-EVAL-ERROR", "info")})

    def test_count_from_string(self):
        # R3: count が文字列の数（型の無い変数に --var で渡した値、count = "2"）なら数に変換する
        with tempfile.TemporaryDirectory() as tmp:
            write_files(Path(tmp), {"main.tf": '''
            variable "n" {}
            resource "aws_instance" "a" { count = var.n }
            resource "aws_instance" "b" { count = "2" }
            resource "aws_instance" "c" { count = "x" }
            '''})
            raw = tf_build.build_raw(Path(tmp), Path(tmp), var_args=[("var", "n=3")])
        assert_valid(self, raw)
        addrs = [r["address"] for r in raw["resources"]]
        self.assertEqual(addrs, ["aws_instance.a[0]", "aws_instance.a[1]", "aws_instance.a[2]", "aws_instance.b[0]",
                                 "aws_instance.b[1]", "aws_instance.c[*]"])
        self.assertEqual(raw["evaluation"]["vars"], {"n": {"source": "--var"}})

    def test_numbers_range_urlencode_and_can(self):
        raw = build('''
        resource "aws_s3_bucket" "a" {}
        resource "aws_s3_bucket" "b" {
          sum   = 0.1 + 0.2
          mul   = 1.1 * 3
          div   = 1 / 4
          mod   = -7 % 3
          big   = range(2000)
          small = length(range(0, 1, 0.25))
          url   = urlencode("a b&c~")
          can   = can(aws_s3_bucket.a.id)
          can2  = can(1 + 1)
        }
        ''')
        assert_valid(self, raw)
        p = props(raw, "aws_s3_bucket.b")
        # Terraform の数は10進で正確（0.1 + 0.2 は 0.3）
        self.assertEqual((p["sum"], p["mul"], p["div"], p["mod"], p["small"]), (0.3, 3.3, 0.25, -1, 4))
        self.assertIn("$unknown", p["big"])  # 1024 個を超える range は黙って打ち切らず誤り
        self.assertEqual(p["url"], "a+b%26c~")  # Go の QueryEscape と同じ
        self.assertIn("$unknown", p["can"])  # 値が決まらなければ、誤りになるかも決まらない
        self.assertIs(p["can2"], True)
        by_path = {d["path"]: d["code"] for d in raw["diagnostics"] if d["address"] == "aws_s3_bucket.b"}
        self.assertEqual(by_path, {"big": "TF-EVAL-ERROR", "can": "TF-UNEVALUATED"})

    def test_var_file_errors_do_not_show_values(self):
        # 任意 6: 変数のファイルを読めないときは、位置だけを書く（値の一部を出さない）
        with tempfile.TemporaryDirectory() as tmp:
            write_files(Path(tmp), {"main.tf": 'variable "pw" {}\n', "bad.tfvars": 'pw = "s3cret" "x"\n'})
            with self.assertRaises(ValueError) as cm:
                tf_build.build_raw(Path(tmp), Path(tmp), var_files=[Path(tmp) / "bad.tfvars"])
        self.assertNotIn("s3cret", str(cm.exception))
        self.assertIn("line 1", str(cm.exception))

    def test_var_file_on_another_drive(self):
        # 任意 4: 別のドライブの変数のファイルは、evaluation.var_files にファイル名だけを書く
        with tempfile.TemporaryDirectory() as tmp:
            write_files(Path(tmp), {"main.tf": 'variable "a" {}\n', "x.tfvars": 'a = "1"\n'})
            mod = module_eval.ModuleEval(model.Context(Path(tmp)), Path(tmp))
            mod.load()
            real = os.path.relpath

            def other_drive(path, start=None):
                if str(path).endswith("x.tfvars"):
                    raise ValueError("path is on mount 'D:', start on mount 'C:'")
                return real(path, start)

            os.path.relpath = other_drive
            try:
                mod.setup_variables([("file", Path(tmp) / "x.tfvars")])
            finally:
                os.path.relpath = real
        self.assertEqual(mod.var_files, ["x.tfvars"])
        self.assertEqual((mod.var_values, mod.var_sources), ({"a": "1"}, {"a": {"source": "x.tfvars"}}))
        self.assertIn("TF-VARFILE-OTHER-DRIVE", [d["code"] for d in mod.ctx.diagnostics])


class ExpressionTest(unittest.TestCase):
    """locals・テンプレート・条件式・for 式・関数の評価と、評価で残らなかった参照（pruned）。"""

    def test_locals_templates_and_for(self):
        raw = build(r'''
        variable "env" { default = "prod" }
        locals {
          prod    = var.env == "prod"
          subnets = { a = "10.0.1.0/24", b = "10.0.2.0/24" }
          names   = [for k, v in local.subnets : "${k}=${v}" if k != "b"]
          upper   = { for k, v in local.subnets : upper(k) => cidrsubnet(v, 4, 1) }
          grouped = { for s in ["x1", "x2", "y1"] : substr(s, 0, 1) => s... }
          tpl     = "%{ if local.prod }P%{ else }D%{ endif }:%{ for s in ["x", "y"] ~} [${s}] %{~ endfor }"
        }
        resource "aws_s3_bucket" "b" {
          names   = local.names
          upper   = local.upper
          grouped = local.grouped
          tpl     = local.tpl
          doc     = <<-EOT
            %{ for k, v in local.subnets ~}
            ${k}: ${v}
            %{ endfor ~}
            EOT
          math    = [1 + 2 * 3, 7 / 2, 7 % 3, -5 % 3, 2 > 1 && !false, "1" + 1]
          fmt     = format("%s-%03d-%.1f-%v-%q", "a", 7, 2.25, true, "x")
        }
        ''')
        assert_valid(self, raw)
        p = props(raw, "aws_s3_bucket.b")
        self.assertEqual(p["names"], ["a=10.0.1.0/24"])
        self.assertEqual(p["upper"], {"A": "10.0.1.16/28", "B": "10.0.2.16/28"})
        self.assertEqual(p["grouped"], {"x": ["x1", "x2"], "y": ["y1"]})
        self.assertEqual(p["tpl"], "P:[x][y]")
        self.assertEqual(p["doc"], "a: 10.0.1.0/24\nb: 10.0.2.0/24\n")
        self.assertEqual(p["math"], [7, 3.5, 1, -2, True, 2])
        self.assertEqual(p["fmt"], 'a-007-2.2-true-"x"')
        self.assertEqual(codes(raw), [])

    def test_conditional_prunes_the_other_side(self):
        raw = build('''
        variable "use_a" { default = true }
        variable "unknown" {}
        resource "aws_s3_bucket" "a" {}
        resource "aws_s3_bucket" "b" {}
        locals {
          pick = var.use_a ? aws_s3_bucket.a.id : aws_s3_bucket.b.id
          ids  = { a = aws_s3_bucket.a.arn, b = aws_s3_bucket.b.arn }
          list = [aws_s3_bucket.a.arn, aws_s3_bucket.b.arn]
        }
        resource "aws_sns_topic" "t" {
          chosen  = local.pick
          looked  = local.ids["b"]
          picked  = local.list[1]
          filtered = [for i, b in local.list : b if i == 0]
          coal    = coalesce("", aws_s3_bucket.a.id, aws_s3_bucket.b.id)
          undecided = var.unknown ? aws_s3_bucket.a.id : aws_s3_bucket.b.id
          tried   = try(local.ids.c, aws_s3_bucket.b.bucket)
          can     = can(local.ids.c)
        }
        ''')
        assert_valid(self, raw)
        p = props(raw, "aws_sns_topic.t")
        self.assertEqual(p["chosen"], res("aws_s3_bucket.a", "id"))
        self.assertEqual(p["looked"], res("aws_s3_bucket.b", "arn"))
        self.assertEqual(p["picked"], res("aws_s3_bucket.b", "arn"))
        self.assertEqual(p["filtered"], [res("aws_s3_bucket.a", "arn")])
        self.assertEqual(p["coal"], res("aws_s3_bucket.a", "id"))
        self.assertIn("$unknown", p["undecided"])
        self.assertEqual(p["tried"], res("aws_s3_bucket.b", "bucket"))
        self.assertIs(p["can"], False)
        got = {r for r in refs(raw, "aws_sns_topic.t") if r[5] != "active"}
        self.assertEqual(got, {
            # 条件式の選ばれなかった側、リストの添字で選ばなかった要素、関数が捨てた値は pruned。
            # マップのキーで引かなかった値（looked）は pruned にしない
            ("aws_sns_topic.t", "chosen", "aws_s3_bucket.b", "id", "ref", "pruned"),
            ("aws_sns_topic.t", "picked", "aws_s3_bucket.a", "arn", "ref", "pruned"),
            ("aws_sns_topic.t", "filtered", "aws_s3_bucket.b", "arn", "ref", "pruned"),  # for 式の if で除いた要素
            ("aws_sns_topic.t", "coal", "aws_s3_bucket.b", "id", "ref", "pruned"),
            ("aws_sns_topic.t", "tried", "aws_s3_bucket.a", "arn", "ref", "pruned"),
            # 条件が決まらなければ、両方の側の参照が unevaluated
            ("aws_sns_topic.t", "undecided", "aws_s3_bucket.a", "id", "ref", "unevaluated"),
            ("aws_sns_topic.t", "undecided", "aws_s3_bucket.b", "id", "ref", "unevaluated"),
        })

    def test_errors_and_unsupported(self):
        raw = build('''
        locals { m = { a = 1 } }
        resource "aws_s3_bucket" "a" {}
        resource "aws_s3_bucket" "b" {
          missing = local.m.b
          range   = [1, 2][5]
          func    = provider::aws::arn_parse(aws_s3_bucket.a.arn)
          stamp   = timestamp()
          len     = length(aws_s3_bucket.a.tags)
          lst     = ["${aws_s3_bucket.a.id}", [1]]
          tpl     = "x${[1, 2]}"
        }
        ''')
        assert_valid(self, raw)
        p = props(raw, "aws_s3_bucket.b")
        for key in ("missing", "range", "func", "stamp", "len"):
            self.assertIn("$unknown", p[key], key)
        self.assertIn("$unknown", p["tpl"]["$concat"][1])  # テンプレートの中のリストは入れられない
        self.assertEqual(p["lst"], [res("aws_s3_bucket.a", "id"), [1]])
        by_path = {d["path"]: d["code"] for d in raw["diagnostics"] if d["address"] == "aws_s3_bucket.b"}
        self.assertEqual(by_path, {"missing": "TF-EVAL-ERROR", "range": "TF-EVAL-ERROR",
                                   "func": "TF-UNSUPPORTED-FUNCTION", "stamp": "TF-UNEVALUATED",
                                   "len": "TF-UNEVALUATED", "tpl": "TF-UNEVALUATED"})
        # 評価できなかった関数の引数の中の参照は unevaluated で残す
        self.assertIn(("aws_s3_bucket.b", "func", "aws_s3_bucket.a", "arn", "ref", "unevaluated"), refs(raw))
        self.assertIn(("aws_s3_bucket.b", "len", "aws_s3_bucket.a", "tags", "ref", "unevaluated"), refs(raw))

    def test_cycle(self):
        raw = build('locals {\n  a = local.b\n  b = local.a\n}\nresource "aws_s3_bucket" "x" {\n  v = local.a\n}\n')
        assert_valid(self, raw)
        self.assertEqual(codes(raw, "aws_s3_bucket.x"), ["TF-CYCLE"])


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


class BlockKindTest(unittest.TestCase):
    """手順1 から回したもの: ephemeral、check の中の data、override のファイル。"""

    def test_ephemeral_and_check(self):
        raw = build('''
        resource "aws_secretsmanager_secret" "s" {}
        ephemeral "aws_secretsmanager_secret_version" "v" {
          secret_id = aws_secretsmanager_secret.s.id
        }
        resource "aws_db_instance" "db" {
          password_wo = ephemeral.aws_secretsmanager_secret_version.v.secret_string
          depends_on  = [ephemeral.aws_secretsmanager_secret_version.v]
        }
        check "health" {
          data "http" "probe" {
            url = "https://${aws_db_instance.db.address}"
          }
          assert {
            condition     = data.http.probe.status_code == 200
            error_message = "down"
          }
        }
        ''')
        assert_valid(self, raw)
        # ephemeral は state に残らないので resources に載せない。参照は TF-UNDEFINED-REF にせず、中の参照を残す
        self.assertNotIn("ephemeral", " ".join(r["address"] for r in raw["resources"]))
        self.assertIn("$unknown", props(raw, "aws_db_instance.db")["password_wo"])
        self.assertEqual(codes(raw, "aws_db_instance.db"), ["TF-EPHEMERAL"])
        self.assertEqual([d["level"] for d in raw["diagnostics"] if d["address"] == "aws_db_instance.db"], ["info"])
        self.assertIn(("aws_db_instance.db", "password_wo", "aws_secretsmanager_secret.s", "id", "ref", "unevaluated"),
                      refs(raw))
        # check ブロックの中の data は data として読む（assert は読まない）
        self.assertEqual(props(raw, "data.http.probe")["url"],
                         {"$concat": ["https://", res("aws_db_instance.db", "address")]})

    def test_override_files(self):
        raw = build({"main.tf": '''
        variable "size" { default = 1 }
        locals { name = "base" }
        resource "aws_instance" "a" {
          instance_type = "t3.micro"
          ami           = "ami-1"
          ebs_block_device { device_name = "/dev/a" }
          ebs_block_device { device_name = "/dev/b" }
          tags = { Name = local.name }
        }
        ''', "override.tf": '''
        variable "size" { default = 3 }
        locals { name = "over" }
        resource "aws_instance" "a" {
          count         = var.size
          instance_type = "t3.large"
          ebs_block_device { device_name = "/dev/c" }
        }
        resource "aws_instance" "nothing" {}
        '''})
        assert_valid(self, raw)
        # 属性は置き換え、同じ種類の入れ子のブロックはすべて置き換える（Terraform の override の規則）
        self.assertEqual(len([r for r in raw["resources"] if r["address"].startswith("aws_instance.a[")]), 3)
        self.assertEqual(props(raw, "aws_instance.a[2]"), {"instance_type": "t3.large", "ami": "ami-1",
                                                           "ebs_block_device": [{"device_name": "/dev/c"}],
                                                           "tags": {"Name": "over"}})
        self.assertIn("TF-OVERRIDE-UNMATCHED", codes(raw, ""))
        self.assertIn("override file override.tf is merged into aws_instance.a", raw["evaluation"]["assumptions"])


class EvaluatorTest(unittest.TestCase):
    """adapters/terraform/evaluator/ の組み込み関数と型の変換（印を含む値の扱い）。"""

    def test_functions_on_known_values(self):
        call = F.call_function
        self.assertEqual(call("cidrsubnet", ["10.0.0.0/16", 8, 2]), "10.0.2.0/24")
        self.assertEqual(call("cidrsubnets", ["10.0.0.0/16", 4, 8, 4]), ["10.0.0.0/20", "10.0.16.0/24", "10.0.32.0/20"])
        self.assertEqual(call("cidrhost", ["10.0.1.0/24", 5]), "10.0.1.5")
        self.assertEqual(call("cidrnetmask", ["10.0.0.0/12"]), "255.240.0.0")
        self.assertEqual(call("lookup", [{"a": 1}, "b", 2]), 2)
        self.assertEqual(call("element", [["a", "b"], 3]), "b")
        self.assertEqual(call("merge", [{"a": 1, "b": 1}, None, {"b": 2}]), {"a": 1, "b": 2})
        self.assertEqual(call("toset", [["b", "a", "b"]]), ["a", "b"])
        self.assertEqual(call("flatten", [[["a"], [["b"]], "c"]]), ["a", "b", "c"])
        self.assertEqual(call("coalesce", [None, "", "x"]), "x")
        self.assertEqual(call("compact", [["a", "", None, "b"]]), ["a", "b"])
        self.assertEqual(call("keys", [{"b": 1, "a": 2}]), ["a", "b"])
        self.assertEqual(call("values", [{"b": 1, "a": 2}]), [2, 1])
        self.assertEqual(call("replace", ["a-b-c", "/-(\\w)/", "_$1"]), "a_b_c")
        self.assertEqual(call("regex", ["^(\\w+)-(\\d+)$", "app-12"]), ["app", "12"])
        self.assertEqual(call("regexall", ["\\d", "a1b2"]), ["1", "2"])
        self.assertEqual(call("split", [",", "a,b"]), ["a", "b"])
        self.assertEqual(call("join", ["-", ["a", "b"], ["c"]]), "a-b-c")
        self.assertEqual(call("format", ["%s/%d", "x", 3]), "x/3")
        self.assertEqual(call("formatlist", ["%s-%s", ["a", "b"], "z"]), ["a-z", "b-z"])
        self.assertEqual(call("zipmap", [["a", "b"], [1, 2]]), {"a": 1, "b": 2})
        self.assertEqual(call("range", [3]), [0, 1, 2])
        self.assertEqual(call("max", [1, 5, 3]), 5)
        self.assertEqual(call("contains", [["a"], "a"]), True)
        self.assertEqual(call("contains", [[1], True]), False)  # 型を区別する
        self.assertEqual(call("jsondecode", ['{"a": [1]}']), {"a": [1]})
        self.assertEqual(call("base64decode", [call("base64encode", ["hé"])]), "hé")
        self.assertEqual(call("trimsuffix", ["a.tf", ".tf"]), "a")
        self.assertEqual(call("one", [[]]), None)
        self.assertEqual(call("tostring", [1.5]), "1.5")
        for name, args in (("lookup", [{"a": 1}, "b"]), ("element", [[], 0]), ("cidrsubnet", ["10.0.0.0/30", 8, 0]),
                           ("coalesce", [None, ""]), ("slice", [[1], 0, 3]), ("one", [[1, 2]])):
            with self.subTest(name):
                with self.assertRaises(V.EvalError):
                    call(name, args)

    def test_functions_with_markers(self):
        call, R = F.call_function, V.Res
        a, b = R("aws_s3_bucket.a", "id"), R("aws_s3_bucket.b", "arn")
        # 構造だけで決まる関数は、印をそのまま残す
        self.assertEqual(call("concat", [[a], [b]]), [a, b])
        self.assertEqual(call("length", [[a, b]]), 2)
        self.assertEqual(call("lookup", [{"x": a}, "x"]), a)
        self.assertEqual(call("join", [",", [a, "z"]]), V.Concat((a, ",z")))
        self.assertEqual(call("format", ["arn:%s:x", a]), V.Concat(("arn:", a, ":x")))
        self.assertEqual(call("jsonencode", [{"r": a}]), V.Json({"r": a}))
        self.assertEqual(call("slice", [V.Az("*"), 0, 2]), [V.Az(0), V.Az(1)])
        self.assertEqual(call("element", [V.Az("*"), 2]), V.Az(2))
        # 値が要る関数は Unknown（中の参照を持ち歩く）
        for name, args in (("upper", [a]), ("length", [a]), ("split", [",", a]), ("cidrsubnet", [a, 8, 1]),
                           ("contains", [[a], "x"])):
            with self.subTest(name):
                u = call(name, args)
                self.assertIsInstance(u, V.Unknown)
                self.assertIn(("aws_s3_bucket.a", "id", ()), u.refs)
        u = call("upper", [V.Unknown("variable x has no value", "TF-UNRESOLVED-VAR")])
        self.assertEqual((u.reason, u.code), ("variable x has no value", "TF-UNRESOLVED-VAR"))  # 元の理由を引き継ぐ

    def test_convert(self):
        spec = ("object", {"n": (("number",), False, V.NODEFAULT), "l": (("set", ("string",)), True, ["b", "a"]),
                           "o": (("map", ("bool",)), True, V.NODEFAULT)})
        self.assertEqual(V.convert({"n": "5", "extra": 1}, spec), {"n": 5, "l": ["a", "b"], "o": None})
        self.assertEqual(V.convert({"n": 1, "o": {"x": "true"}}, spec)["o"], {"x": True})
        self.assertEqual(V.convert("abc", ("number",)), "abc")  # 変換できなければそのまま
        self.assertEqual(V.convert(3, ("string",)), "3")


class RobustnessTest(unittest.TestCase):
    def test_heredoc_trailing_spaces(self):
        # 公開サンプル T06 の形: 終端の識別子の後ろに空白（python-hcl2 8.1.4 はそのままでは読めない）
        text = ('resource "aws_sns_topic_policy" "p" {\n  arn    = aws_sns_topic.t.arn\n'
                '  policy = <<POLICY  \n{"Statement": [{"Resource": "${aws_sns_topic.t.arn}"}]}\nPOLICY  \n}\n'
                'resource "aws_sns_topic" "t" {}\n')
        raw = build(text)
        assert_valid(self, raw)
        self.assertEqual(props(raw, "aws_sns_topic_policy.p")["policy"],
                         {"$json": {"Statement": [{"Resource": res("aws_sns_topic.t", "arn")}]}})
        d = [x for x in raw["diagnostics"] if x["code"] == "TF-HEREDOC-TRAILING-SPACE"]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["level"], "info")
        self.assertIn("2 heredoc marker line", d[0]["message"])

    def test_heredoc_after_commented_heredoc(self):
        # コメントの中の heredoc（終端もコメント）の後ろでも、終端に空白のある heredoc を直す（第三者レビューの M1）
        text = ('resource "aws_sns_topic" "t" {}\n'
                '# resource "aws_sns_topic_policy" "old" {\n#   policy = <<EOF\n#   {}\n#   EOF\n# }\n'
                '// x = <<NOPE\n'
                'resource "aws_sns_topic_policy" "p" {\n  arn    = aws_sns_topic.t.arn\n'
                '  policy = <<POLICY\n{"Statement": [{"Resource": "${aws_sns_topic.t.arn}"}]}\nPOLICY  \n}\n')
        raw = build(text)
        assert_valid(self, raw)
        self.assertNotIn("TF-PARSE-ERROR", codes(raw))
        self.assertIn("$json", props(raw, "aws_sns_topic_policy.p")["policy"])
        # 終端の無い開始（文字列の中の << など）は飛ばして、次の行から調べ直す
        fixed, n = hcl.fix_heredocs('a = "<<X"\nb = <<EOT\nhi\nEOT \n')
        self.assertEqual((fixed, n), ('a = "<<X"\nb = <<EOT\nhi\nEOT\n', 1))
        fixed, n = hcl.fix_heredocs("a = <<NEVER\nb = <<EOT\nhi\nEOT \n")
        self.assertEqual(n, 1)
        self.assertTrue(fixed.endswith("EOT\n"))

    def test_ignored_file_names(self):
        raw = build({"main.tf": 'resource "aws_vpc" "a" {}\n', ".hidden.tf": 'resource "aws_vpc" "b" {}\n'})
        self.assertEqual([r["address"] for r in raw["resources"]], ["aws_vpc.a"])

    def test_cli_cannot_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file"
            blocker.write_text("x", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = adapt_tf.main(["--input", str(FIXTURES / "three-tier"), "--out", str(blocker / "out.json")])
            self.assertEqual(code, 2)
            self.assertIn("書けませんでした", err.getvalue())

    def test_crlf(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "main.tf").write_bytes(b'resource "aws_vpc" "a" {\r\n  x = <<EOT\r\nhi\r\nEOT\r\n}\r\n')
            raw = tf_build.build_raw(Path(tmp), Path(tmp))
        assert_valid(self, raw)
        self.assertEqual(props(raw, "aws_vpc.a")["x"], "hi\n")

    def test_unreadable_file_is_reported_and_others_are_read(self):
        raw = build({"good.tf": 'resource "aws_vpc" "a" {}\n', "bad.tf": 'resource "aws_vpc" "b" {\n  x = \n',
                     "dup.tf": 'resource "aws_vpc" "a" {}\n', "x.tf.json": "{}"})
        assert_valid(self, raw)
        self.assertEqual([r["address"] for r in raw["resources"]], ["aws_vpc.a"])
        by_code = {d["code"]: d for d in raw["diagnostics"]}
        self.assertEqual(by_code["TF-PARSE-ERROR"]["level"], "error")
        self.assertIn("bad.tf", by_code["TF-PARSE-ERROR"]["message"])
        self.assertIn("TF-DUPLICATE-BLOCK", by_code)
        self.assertIn("TF-TFJSON-UNSUPPORTED", by_code)

    def test_tf_json_is_not_read_without_a_plan(self):
        # .tf.json を .tf だけで読むか（フェーズ2 の手順5 で「読まない」と決めた）。JSON の書き方では入れ子のブロックと
        # 属性（オブジェクトの値）を区別できない（provider のスキーマが要る）ので、リソースは載せず warn を出す。
        # ほかの .tf は読む。plan JSON と一緒のときの扱いは tests/test_tf_plan.py
        tfjson = json.dumps({"resource": {"aws_security_group": {"web": {
            "name": "web", "ingress": {"from_port": 80, "to_port": 80}, "tags": {"Name": "web"}}}}})
        raw = build({"main.tf": 'resource "aws_vpc" "a" {}', "extra.tf.json": tfjson,
                     "sub/not_root.tf.json": tfjson})
        assert_valid(self, raw)
        self.assertEqual([r["address"] for r in raw["resources"]], ["aws_vpc.a"])
        found = [d for d in raw["diagnostics"] if d["code"] == "TF-TFJSON-UNSUPPORTED"]
        self.assertEqual([(d["level"], d["address"]) for d in found], [("warn", "")])  # ルートの1ファイルだけ
        self.assertIn("extra.tf.json", found[0]["message"])
        self.assertIn("--plan", found[0]["message"])
        # .tf.json だけのフォルダは、.tf が無いので読めない（終了コード 2）
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "only.tf.json").write_text(tfjson, encoding="utf-8")
            with self.assertRaises(ValueError):
                tf_build.build_raw(Path(tmp), Path(tmp))

    def test_no_tf_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                tf_build.build_raw(Path(tmp), Path(tmp))
            out = Path(tmp) / "out.json"
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(adapt_tf.main(["--input", tmp, "--out", str(out)]), 2)
            self.assertIn(".tf", err.getvalue())
            self.assertFalse(out.exists())

    def test_cli_writes_canonical_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "raw.json"
            self.assertEqual(subprocess.run(
                [sys.executable, str(SCRIPTS / "adapt_tf.py"), "--input", str(FIXTURES / "three-tier"),
                 "--out", str(out), "--root-base", str(WS)], capture_output=True).returncode, 0)
            text = out.read_text(encoding="utf-8")
            self.assertEqual(text, tf_build.dump(tf_build.build_raw(FIXTURES / "three-tier", WS)))  # 毎回同じ
            self.assertEqual(v.validate_file(out, False, set()), [])
            self.assertEqual(json.loads(text)["root"], "fixtures/tf/three-tier")


def expected_addresses(expected: dict) -> dict:
    """正解 IR の TF 側の網羅分類（address → (type, file, enabled)）。count が 0 のブロック（H-COND-FALSE）は enabled: false。"""
    return {r["address"]: (r["type"], r["file"], r.get("rule") != "H-COND-FALSE")
            for r in expected["sources"]["tf"]["resources"]}


# 正解 IR を書いたときの変数の値（three-tier は dev。vpc-endpoints は terraform.tfvars を自動で読む）
EXPECTED_VAR_FILES = {"three-tier": ["env/dev.tfvars"]}


def build_expected_input(name: str) -> dict:
    root = FIXTURES / name
    return tf_build.build_raw(root, WS, var_files=[root / f for f in EXPECTED_VAR_FILES.get(name, [])])


class ExpectedIrTest(unittest.TestCase):
    """正解 IR（expected）の TF 側の網羅分類と、raw IR の address・type・file・enabled を突き合わせる。

    count・for_each はインスタンス単位で、count が 0 のブロック（H-COND-FALSE）は enabled: false で一致する。
    モジュールの中身（ローカルモジュールの再帰と、要約表の展開。via: module_summary）も含めて、読み替えずに比べる。
    """

    def test_addresses_match_expected(self):
        for name in ("three-tier", "serverless-api", "vpc-endpoints", "rag", "three-tier-modules"):
            with self.subTest(name):
                expected = json.loads((WS / "expected" / f"{name}.ir.json").read_text(encoding="utf-8"))
                self.assertEqual(expected["sources"]["tf"]["root"], f"fixtures/tf/{name}")
                raw = build_expected_input(name)
                self.assertEqual(raw["root"], expected["sources"]["tf"]["root"])
                got = {r["address"]: (r["type"], r["file"], r["enabled"]) for r in raw["resources"]}
                self.assertEqual(got, expected_addresses(expected))
                want_via = {r["address"]: r.get("via") for r in expected["sources"]["tf"]["resources"]}
                for r in raw["resources"]:
                    self.assertNotIn("multiplicity", r, r["address"])  # 5構成とも count・for_each が決まる
                    self.assertEqual(r.get("via"), want_via[r["address"]], r["address"])
                    if r["address"].startswith("module."):
                        self.assertEqual(r["module"], r["address"].rsplit(".", 2)[0] if ".data." not in r["address"]
                                         else r["address"].split(".data.")[0], r["address"])
                # 正解 IR の構成では、評価できない値は rag の sha1()（デプロイの再作成の引き金）だけ
                warns = [(d["address"], d["path"], d["code"]) for d in raw["diagnostics"] if d["level"] != "info"]
                self.assertEqual(warns, [("aws_api_gateway_deployment.api", "triggers.redeployment", "TF-UNEVALUATED")]
                                 if name == "rag" else [])

    def test_known_references(self):
        # 正解 IR の辺の根拠のうち、モジュールの境界をまたがないもの（count・for_each はインスタンスごと）
        cases = {
            "three-tier": [
                ("aws_lb_listener.http", "default_action[0].target_group_arn", "aws_lb_target_group.app", "arn"),
                ("aws_ecs_service.app", "load_balancer[0].target_group_arn", "aws_lb_target_group.app", "arn"),
                ("aws_ecs_task_definition.app", "container_definitions[0].environment[0].value",
                 "aws_db_instance.main", "address"),
                ("aws_route_table.private", "route[0].nat_gateway_id", "aws_nat_gateway.main", "id"),
                ("aws_lb.app", "subnets[0]", "aws_subnet.public[0]", "id"),
                ("aws_lb.app", "subnets[1]", "aws_subnet.public[1]", "id"),
                ("aws_route_table_association.private[1]", "subnet_id", "aws_subnet.private[1]", "id"),
                ("aws_nat_gateway.main", "subnet_id", "aws_subnet.public[0]", "id"),
                # 作られない（dev で count が 0）リソースの参照も残す。先も作られないブロック（添字なし）
                ("aws_instance.bastion", "vpc_security_group_ids[0]", "aws_security_group.bastion", "id"),
            ],
            "serverless-api": [
                ("aws_lambda_event_source_mapping.orders_stream", "event_source_arn", "aws_dynamodb_table.orders",
                 "stream_arn"),
                ("aws_lambda_event_source_mapping.orders_stream", "function_name",
                 "aws_lambda_function.stream_processor", "arn"),
                ("aws_sns_topic_subscription.order_events_queue", "endpoint", "aws_sqs_queue.order_events", "arn"),
            ],
            "vpc-endpoints": [
                ("aws_security_group.endpoints", "ingress[0].security_groups[0]", "aws_security_group.app", "id"),
                ("aws_vpc_endpoint.s3", "route_table_ids[0]", "aws_route_table.private[0]", "id"),
                ("aws_vpc_endpoint.s3", "route_table_ids[1]", "aws_route_table.private[1]", "id"),
                ("aws_route.private_nat[1]", "nat_gateway_id", "aws_nat_gateway.main[1]", "id"),
                ("aws_route.private_nat[1]", "route_table_id", "aws_route_table.private[1]", "id"),
                ("aws_nat_gateway.main[0]", "allocation_id", "aws_eip.nat[0]", "id"),
                ('aws_vpc_endpoint.interface["ssm"]', "security_group_ids[0]", "aws_security_group.endpoints", "id"),
                ('aws_vpc_endpoint.interface["ssm"]', "subnet_ids[1]", "aws_subnet.private[1]", "id"),
            ],
            "rag": [
                ("aws_bedrockagent_data_source.docs", "data_source_configuration[0].s3_configuration[0].bucket_arn",
                 "aws_s3_bucket.docs", "arn"),
                ("aws_s3_bucket_notification.docs", "lambda_function[0].lambda_function_arn",
                 "aws_lambda_function.ingest", "arn"),
                ("aws_api_gateway_integration.query_post", "uri", "aws_lambda_function.query", "invoke_arn"),
            ],
        }
        cases["serverless-api"].append(('aws_apigatewayv2_route.this["get_orders"]', "target",
                                        "aws_apigatewayv2_integration.api_handler", "id"))
        # モジュールの境界をまたぐもの（手順3。出力・変数をたどって元のリソースへ。正解 IR の three-tier-modules の根拠）
        cases["three-tier-modules"] = [
            ('module.alb.aws_lb_listener.this["http"]', "default_action[0].target_group_arn",
             'module.alb.aws_lb_target_group.this["app"]', "arn"),
            ("module.app.aws_ecs_service.this", "load_balancer[0].target_group_arn",
             'module.alb.aws_lb_target_group.this["app"]', "arn"),
            ("module.app.aws_vpc_security_group_ingress_rule.from_alb", "referenced_security_group_id",
             "module.alb.aws_security_group.this[0]", "id"),
            ("module.app.aws_ecs_task_definition.this", "container_definitions[0].environment[0].value",
             "module.db.module.db_instance.aws_db_instance.this[0]", "address"),
            ("aws_security_group.db", "ingress[0].security_groups[0]", "module.app.aws_security_group.this", "id"),
            ("module.db.module.db_instance.aws_db_instance.this[0]", "vpc_security_group_ids[0]",
             "aws_security_group.db", "id"),
            ("module.vpc.aws_route.private_nat_gateway[0]", "nat_gateway_id", "module.vpc.aws_nat_gateway.this[0]", "id"),
            ("module.vpc.aws_route_table_association.private[1]", "subnet_id", "module.vpc.aws_subnet.private[1]", "id"),
            ("module.vpc.aws_route.public_internet_gateway[0]", "gateway_id", "module.vpc.aws_internet_gateway.this[0]",
             "id"),
            ("module.alb.aws_lb.this[0]", "subnets[1]", "module.vpc.aws_subnet.public[1]", "id"),
        ]
        for name, wants in cases.items():
            got = refs(build_expected_input(name))
            for want in wants:
                with self.subTest(name=name, ref=want[:2]):
                    self.assertIn(want + ("ref", "active"), got)

    def test_values_from_tfvars(self):
        # three-tier: env/dev.tfvars と env/prod.tfvars で、踏み台（count）と DB の設定（local の表）が変わる
        root = FIXTURES / "three-tier"
        dev = tf_build.build_raw(root, WS, var_files=[root / "env" / "dev.tfvars"])
        prod = tf_build.build_raw(root, WS, var_files=[root / "env" / "prod.tfvars"])
        none = tf_build.build_raw(root, WS)
        self.assertEqual(dev["evaluation"]["var_files"], ["env/dev.tfvars"])
        self.assertEqual(dev["evaluation"]["vars"]["environment"], {"source": "env/dev.tfvars"})
        self.assertEqual(prod["evaluation"]["vars"]["admin_cidr"], {"source": "env/prod.tfvars"})  # prod.tfvars が上書き
        self.assertEqual(dev["evaluation"]["vars"]["admin_cidr"], {"source": "default"})
        self.assertFalse(res_of(dev, "aws_instance.bastion")["enabled"])
        self.assertTrue(res_of(prod, "aws_instance.bastion[0]")["enabled"])
        self.assertNotIn("aws_instance.bastion", [r["address"] for r in prod["resources"]])
        self.assertEqual(props(prod, "aws_security_group.bastion[0]")["ingress"][0]["cidr_blocks"], ["198.51.100.0/24"])
        self.assertEqual(props(prod, "aws_instance.bastion[0]")["vpc_security_group_ids"],
                         [res("aws_security_group.bastion[0]", "id")])
        self.assertEqual((props(dev, "aws_db_instance.main")["instance_class"],
                          props(prod, "aws_db_instance.main")["instance_class"]), ("db.t4g.micro", "db.m7g.large"))
        self.assertEqual((props(dev, "aws_db_instance.main")["multi_az"],
                          props(prod, "aws_db_instance.main")["multi_az"]), (False, True))
        self.assertNotIn("final_snapshot_identifier", props(dev, "aws_db_instance.main"))  # null は書かない
        self.assertEqual(props(prod, "aws_db_instance.main")["final_snapshot_identifier"], "demo-db-final")
        self.assertEqual(props(dev, "aws_ecs_service.app")["desired_count"], 1)
        # 値の無い environment では、踏み台は ×N（count が決まらない）
        self.assertIsNone(res_of(none, "aws_instance.bastion[*]")["enabled"])
        self.assertIn("TF-UNRESOLVED-VAR", codes(none, "aws_db_instance.main"))
        # 値の無い変数と、自動では読まれない変数のファイルの候補を1つの診断にまとめる（どの環境かを確かめるため）
        summary = [d for d in none["diagnostics"] if d["code"] == "TF-UNRESOLVED-VARS"]
        self.assertEqual([(d["level"], d["message"]) for d in summary], [(
            "info", "variables without a value: environment; var files that are not read automatically "
                    "(pass one with --var-file): env/dev.tfvars, env/prod.tfvars")])
        self.assertNotIn("TF-UNRESOLVED-VARS", codes(dev))
        # vpc-endpoints: terraform.tfvars（自動で読む）の project が既定値を上書きし、名前が正解 IR と一致する
        vpce = tf_build.build_raw(FIXTURES / "vpc-endpoints", WS)
        self.assertEqual(vpce["evaluation"]["var_files"], ["terraform.tfvars"])
        self.assertEqual(props(vpce, "aws_vpc.main")["tags"], {"Name": "net"})
        self.assertEqual(props(vpce, 'aws_vpc_endpoint.interface["ssm"]')["service_name"],
                         "com.amazonaws.ap-northeast-1.ssm")
        self.assertEqual(props(vpce, "aws_subnet.private[1]")["tags"], {"Name": "net-private-ap-northeast-1c"})
        override = tf_build.build_raw(FIXTURES / "vpc-endpoints", WS, vars={"project": "x"})
        self.assertEqual(props(override, "aws_vpc.main")["tags"], {"Name": "x"})

    def test_names_match_expected_nodes(self):
        # 正解 IR のノードの名前（Name タグ・名前の属性）が、評価した props に現れる（ノード ID の元。K-NAME）
        cases = {"three-tier": [("aws_subnet.private[1]", "tags", {"Name": "demo-private-ap-northeast-1c"}),
                                ("aws_lb.app", "name", "demo-alb"), ("aws_ecs_service.app", "name", "demo-app")],
                 "serverless-api": [("aws_lambda_function.api_handler", "function_name", "shop-api-handler"),
                                    ('aws_apigatewayv2_route.this["post_orders"]', "route_key", "POST /orders")],
                 "rag": [("aws_s3_bucket.docs", "bucket", "rag-docs")]}
        for name, wants in cases.items():
            raw = build_expected_input(name)
            for address, key, value in wants:
                with self.subTest(name=name, address=address):
                    self.assertEqual(props(raw, address)[key], value)


class FixtureTest(unittest.TestCase):
    def test_all_fixtures_produce_valid_raw(self):
        from iac_inventory import tf_inventory
        for d in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
            with self.subTest(d.name):
                raw = tf_build.build_raw(d, WS)
                assert_valid(self, raw)
                self.assertFalse([x for x in raw["diagnostics"] if x["level"] == "error"])
                blocks = {b.address for b in tf_inventory(d) if b.module_path == ""}
                # インスタンスの添字を除けば、ルートのブロックの一覧と同じ。モジュールの呼び出しは、中身の
                # リソース（module.x.…）か黒箱の呼び出し1件になる
                got = {re.sub(r"\[[^\]]*\]$", "", r["address"]) for r in raw["resources"]}
                self.assertEqual({a for a in got if not a.startswith("module.")},
                                 {b for b in blocks if not b.startswith("module.")})
                for b in (b for b in blocks if b.startswith("module.")):
                    self.assertTrue(any(a == b or a.startswith(b + ".") or a.startswith(b + "[") for a in got), b)


class SummaryTableFileTest(unittest.TestCase):
    """要約表（data/module-summaries/）が無い・読めないことを、黙って通さない（フェーズ 2b の R1 のレビュー）。"""

    CALL = 'module "vpc" {\n  source = "terraform-aws-modules/vpc/aws"\n  version = "~> 6.0"\n  cidr = "10.0.0.0/16"\n}\n'

    def test_summary_dir_exists_and_is_loaded(self):
        self.assertTrue(MS.SUMMARY_DIR.is_dir(), MS.SUMMARY_DIR)
        self.assertEqual(MS.SUMMARY_DIR.relative_to(SCRIPTS.parent).as_posix(), "data/module-summaries")
        summaries, iam = MS.load()
        self.assertIn("terraform-aws-modules/vpc/aws", summaries)
        self.assertTrue(iam)

    def test_doctor_requires_every_summary_file(self):
        import doctor
        on_disk = sorted(p.relative_to(SCRIPTS.parent).as_posix() for p in MS.SUMMARY_DIR.rglob("*.md"))
        self.assertEqual(on_disk, sorted(f for f in doctor.REQUIRED_FILES if f.startswith("data/module-summaries/")))
        self.assertIn("data/module-summaries/terraform-aws-vpc/v6.md", doctor.REQUIRED_FILES)
        for rel in doctor.REQUIRED_FILES:
            self.assertTrue((SCRIPTS.parent / rel).is_file(), rel)

    def test_missing_table_warns_for_registry_modules(self):
        from unittest import mock
        raw = build(self.CALL)
        codes = [d["code"] for d in raw["diagnostics"] if d["code"].startswith("TF-MODULE")]
        self.assertEqual(codes, ["TF-MODULE-SUMMARY"])
        self.assertGreater(len(raw["resources"]), 1)  # 要約表で展開される
        with tempfile.TemporaryDirectory() as t, mock.patch.object(MS, "SUMMARY_DIR", Path(t) / "nope"):
            raw = build(self.CALL)
        codes = [(d["level"], d["code"]) for d in raw["diagnostics"] if d["code"].startswith("TF-MODULE")]
        self.assertEqual(codes, [("warn", "TF-MODULE-SUMMARY-TABLE-MISSING")])
        self.assertEqual([r["address"] for r in raw["resources"]], ["module.vpc"])  # 黒箱

    def test_missing_table_does_not_warn_without_registry_modules(self):
        from unittest import mock
        files = {"main.tf": 'module "a" {\n  source = "./mod"\n}\nmodule "g" {\n  source = "git::https://example.com/x.git"\n}\n',
                 "mod/main.tf": 'resource "aws_sqs_queue" "q" {\n  name = "q"\n}\n'}
        with tempfile.TemporaryDirectory() as t, mock.patch.object(MS, "SUMMARY_DIR", Path(t) / "nope"):
            raw = build(files)
        self.assertNotIn("TF-MODULE-SUMMARY-TABLE-MISSING", [d["code"] for d in raw["diagnostics"]])

    def copy_tables(self, skip: tuple = ()) -> Path:
        import shutil
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name) / "ms"
        shutil.copytree(MS.SUMMARY_DIR, root, ignore=lambda d, names: [n for n in names if n in skip])
        return root

    def test_a_whole_module_folder_missing_warns_like_a_missing_table(self):
        # vpc のフォルダごと無い（取り込みの不備）。ほかのモジュールの表はある。TF-MODULE-SUMMARY-TABLE-MISSING の warn
        from unittest import mock
        root = self.copy_tables(skip=("terraform-aws-vpc",))
        self.assertIn("terraform-aws-modules/alb/aws", MS.load(root)[0])
        with mock.patch.object(MS, "SUMMARY_DIR", root):
            raw = build(self.CALL)
            alb = build('module "lb" {\n  source = "terraform-aws-modules/alb/aws"\n  version = "~> 10.0"\n}\n')
            sub = build('module "s" {\n  source = "terraform-aws-modules/vpc/aws//modules/x"\n  version = "~> 6.0"\n}\n')
        codes = [(d["level"], d["code"]) for d in raw["diagnostics"] if d["code"].startswith("TF-MODULE")]
        self.assertEqual(codes, [("warn", "TF-MODULE-SUMMARY-TABLE-MISSING")])
        self.assertEqual([r["address"] for r in raw["resources"]], ["module.vpc"])
        self.assertIn("TF-MODULE-SUMMARY", [d["code"] for d in alb["diagnostics"]])  # alb の表はある
        self.assertIn("TF-MODULE-SUMMARY-TABLE-MISSING", [d["code"] for d in sub["diagnostics"]])  # サブモジュールも親のフォルダが無い

    def test_missing_major_of_a_present_module_stays_a_blackbox_info(self):
        # 限界: モジュールの表はあるが、呼び出しの major のファイルが無いときは、表に無いときと同じ info（欠けは doctor の一覧が知らせる）
        from unittest import mock
        root = self.copy_tables(skip=("v6.md",))
        (root / "terraform-aws-vpc").mkdir(exist_ok=True)
        (root / "terraform-aws-vpc" / "v5.md").write_text(
            '<!-- module-summary source="terraform-aws-modules/vpc/aws" majors="5" -->\n```hcl\nvariable "a" {}\n```\n',
            encoding="utf-8", newline="\n")
        with mock.patch.object(MS, "SUMMARY_DIR", root):
            raw = build(self.CALL)  # ~> 6.0 だが 6 のファイルが無い
        codes = [(d["level"], d["code"]) for d in raw["diagnostics"] if d["code"].startswith("TF-MODULE")]
        self.assertEqual(codes, [("info", "TF-MODULE-BLACKBOX")])


if __name__ == "__main__":
    unittest.main()
