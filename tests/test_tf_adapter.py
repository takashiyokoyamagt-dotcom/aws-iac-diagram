"""Terraform アダプタ（scripts/adapters/tf.py）のテスト。フェーズ2 の手順1（土台）の範囲。"""
from __future__ import annotations

import contextlib
import io
import json
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
from adapters import tf  # noqa: E402
from lib import ir_raw  # noqa: E402


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
        return tf.build_raw(Path(tmp), Path(tmp))


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
          source  = "terraform-aws-modules/vpc/aws"
          version = "~> 6.7"
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
        self.assertIn("TF-DEFERRED", codes(raw, "aws_s3_bucket.b"))

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

    def test_deferred_values_keep_references(self):
        raw = build('''
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
        for key in ("name", "subnets", "sg", "ids"):
            self.assertIn("$unknown", p[key], key)
        self.assertEqual(len(p["access_logs"]), 1)
        self.assertIn("$unknown", p["access_logs"][0])
        got = set(refs(raw, "aws_lb.app"))
        # local は中の式をたどる（local.all → local.subnets → aws_subnet.a）
        self.assertEqual(got, {
            ("aws_lb.app", "subnets", "aws_subnet.a", "id", "ref", "unevaluated"),
            ("aws_lb.app", "subnets", "aws_subnet.b", "id", "ref", "unevaluated"),
            ("aws_lb.app", "sg", "aws_security_group.sg", "id", "ref", "unevaluated"),
            ("aws_lb.app", "ids", "aws_subnet.a", None, "ref", "unevaluated"),
            ("aws_lb.app", "access_logs[0]", "aws_subnet.b", "arn", "ref", "unevaluated"),
        })
        self.assertEqual(set(codes(raw, "aws_lb.app")), {"TF-DEFERRED"})


class CountAndModuleTest(unittest.TestCase):
    def test_count_and_for_each_are_n(self):
        raw = build(NETWORK + """
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
        self.assertIn("TF-COUNT-DEFERRED", codes(raw, "aws_vpc_endpoint.interface[*]"))
        self.assertEqual(refs(raw, "aws_route_table_association.public[*]"), [
            ("aws_route_table_association.public[*]", "count", "aws_subnet.public[*]", None, "ref", "unevaluated"),
            ("aws_route_table_association.public[*]", "subnet_id", "aws_subnet.public[*]", "id", "ref", "active"),
        ])

    def test_module_call_is_recorded(self):
        raw = build({"main.tf": """
        module "app" {
          source     = "./modules/app"
          name       = "demo-app"
          subnet_ids = module.vpc.private_subnets
          providers  = { aws = aws.use1 }
          depends_on = [module.vpc]
        }
        module "vpc" {
          source  = "terraform-aws-modules/vpc/aws"
          version = "~> 6.7"
          count   = var.create ? 1 : 0
        }
        """, "modules/app/main.tf": 'resource "aws_ecs_service" "this" {}\n'})
        assert_valid(self, raw)
        app = res_of(raw, "module.app")
        self.assertEqual({k: app[k] for k in ("type", "file", "enabled", "via", "source")},
                         {"type": "module", "file": "main.tf", "enabled": True, "via": "module_blackbox",
                          "source": "./modules/app"})
        self.assertNotIn("version", app)
        self.assertEqual(app["props"]["name"], "demo-app")
        self.assertEqual(app["props"]["subnet_ids"], res("module.vpc[*]", "private_subnets"))
        for meta in ("source", "providers", "depends_on"):
            self.assertNotIn(meta, app["props"])
        vpc = res_of(raw, "module.vpc[*]")
        self.assertEqual((vpc["version"], vpc["multiplicity"], vpc["enabled"]), ("~> 6.7", "N", None))
        # 手順1 はモジュールの中を読まない（手順3）
        self.assertNotIn("module.app.aws_ecs_service.this", [r["address"] for r in raw["resources"]])
        self.assertIn("TF-MODULE-DEFERRED", codes(raw, "module.app"))


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
        fixed, n = tf.fix_heredocs('a = "<<X"\nb = <<EOT\nhi\nEOT \n')
        self.assertEqual((fixed, n), ('a = "<<X"\nb = <<EOT\nhi\nEOT\n', 1))
        fixed, n = tf.fix_heredocs("a = <<NEVER\nb = <<EOT\nhi\nEOT \n")
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
                code = tf.main(["--input", str(FIXTURES / "three-tier"), "--out", str(blocker / "out.json")])
            self.assertEqual(code, 2)
            self.assertIn("書けませんでした", err.getvalue())

    def test_crlf(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "main.tf").write_bytes(b'resource "aws_vpc" "a" {\r\n  x = <<EOT\r\nhi\r\nEOT\r\n}\r\n')
            raw = tf.build_raw(Path(tmp), Path(tmp))
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

    def test_no_tf_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                tf.build_raw(Path(tmp), Path(tmp))
            out = Path(tmp) / "out.json"
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(tf.main(["--input", tmp, "--out", str(out)]), 2)
            self.assertIn(".tf", err.getvalue())
            self.assertFalse(out.exists())

    def test_cli_writes_canonical_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "raw.json"
            self.assertEqual(subprocess.run(
                [sys.executable, str(SCRIPTS / "adapters" / "tf.py"), "--input", str(FIXTURES / "three-tier"),
                 "--out", str(out), "--root-base", str(WS)], capture_output=True).returncode, 0)
            text = out.read_text(encoding="utf-8")
            self.assertEqual(text, tf.dump(tf.build_raw(FIXTURES / "three-tier", WS)))  # 毎回同じ
            self.assertEqual(v.validate_file(out, False, set()), [])
            self.assertEqual(json.loads(text)["root"], "fixtures/tf/three-tier")


def step1_expected(expected: dict, module_files: dict[str, str]) -> dict:
    """正解 IR の TF 側の網羅分類を、手順1 の出力の形に読み替える。

    - count・for_each を展開したインスタンス（[0]、["ssm"]）と、count が 0 のブロック（H-COND-FALSE）は、
      手順1 では評価しないので ×N の [*] の1件（enabled: null）。手順2（A4）で正解 IR と同じ形になる
    - モジュールの中身（module.x. で始まるもの。要約表と、ローカルモジュールの再帰）は、手順1 では
      モジュールの呼び出し1件（type: module、ファイルは呼び出しのあるファイル）。手順3 で正解 IR と同じ形になる
    """
    want: dict = {}
    for r in expected["sources"]["tf"]["resources"]:
        a = r["address"]
        if a.startswith("module."):
            call = "module." + a.split(".")[1]
            want[call] = ("module", module_files[call], True)
            continue
        if a != re.sub(r"\[[^\]]*\]", "", a) or r.get("rule") == "H-COND-FALSE":
            want[re.sub(r"\[[^\]]*\]$", "", a) + "[*]"] = (r["type"], r["file"], None)
        else:
            want[a] = (r["type"], r["file"], True)
    return want


class ExpectedIrTest(unittest.TestCase):
    """正解 IR（expected）の TF 側の網羅分類と、raw IR の address・type・file・enabled を突き合わせる。

    手順1 の範囲で一致しないもの（count・for_each の展開と count が 0 のブロック → 手順2、モジュールの中身 → 手順3）は、
    step1_expected() で手順1 の形に読み替えて比べる（何も飛ばさない）。
    """

    MODULE_FILES = {"three-tier-modules": {"module.vpc": "main.tf", "module.alb": "main.tf", "module.app": "main.tf",
                                           "module.db": "main.tf"}}

    def test_addresses_match_expected(self):
        for name in ("three-tier", "serverless-api", "vpc-endpoints", "rag", "three-tier-modules"):
            with self.subTest(name):
                expected = json.loads((WS / "expected" / f"{name}.ir.json").read_text(encoding="utf-8"))
                root = WS / expected["sources"]["tf"]["root"]
                raw = tf.build_raw(root, WS)
                self.assertEqual(raw["root"], expected["sources"]["tf"]["root"])
                got = {r["address"]: (r["type"], r["file"], r["enabled"]) for r in raw["resources"]}
                self.assertEqual(got, step1_expected(expected, self.MODULE_FILES.get(name, {})))
                for r in raw["resources"]:
                    self.assertEqual(r.get("multiplicity") == "N", r["address"].endswith("[*]"), r["address"])
                    self.assertEqual(r.get("via") == "module_blackbox", r["type"] == "module", r["address"])

    def test_known_references(self):
        # 正解 IR の辺の根拠のうち、手順1 で取れるもの（モジュールの境界・count のインスタンスをまたがないもの）
        cases = {
            "three-tier": [
                ("aws_lb_listener.http", "default_action[0].target_group_arn", "aws_lb_target_group.app", "arn"),
                ("aws_ecs_service.app", "load_balancer[0].target_group_arn", "aws_lb_target_group.app", "arn"),
                ("aws_ecs_task_definition.app", "container_definitions[0].environment[0].value",
                 "aws_db_instance.main", "address"),
                ("aws_route_table.private", "route[0].nat_gateway_id", "aws_nat_gateway.main", "id"),
                ("aws_lb.app", "subnets", "aws_subnet.public[*]", "id"),
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
                ("aws_vpc_endpoint.s3", "route_table_ids", "aws_route_table.private[*]", "id"),
            ],
            "rag": [
                ("aws_bedrockagent_data_source.docs", "data_source_configuration[0].s3_configuration[0].bucket_arn",
                 "aws_s3_bucket.docs", "arn"),
                ("aws_s3_bucket_notification.docs", "lambda_function[0].lambda_function_arn",
                 "aws_lambda_function.ingest", "arn"),
                ("aws_api_gateway_integration.query_post", "uri", "aws_lambda_function.query", "invoke_arn"),
            ],
        }
        for name, wants in cases.items():
            got = refs(tf.build_raw(FIXTURES / name, WS))
            for want in wants:
                with self.subTest(name=name, ref=want[:2]):
                    self.assertIn(want + ("ref", "active"), got)


class FixtureTest(unittest.TestCase):
    def test_all_fixtures_produce_valid_raw(self):
        from iac_inventory import tf_inventory
        for d in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
            with self.subTest(d.name):
                raw = tf.build_raw(d, WS)
                assert_valid(self, raw)
                self.assertFalse([x for x in raw["diagnostics"] if x["level"] == "error"])
                blocks = [b for b in tf_inventory(d) if b.module_path == ""]
                self.assertEqual(len(raw["resources"]), len(blocks))

    def test_public_samples(self):
        # 公開サンプルの TF（T01〜T20、P01〜P04）のルートがすべて読め、raw IR の検査を通る
        import survey_public
        roots = [r for fmt, rs in survey_public.SAMPLES.values() if fmt == "tf" for r in rs]
        roots += survey_public.t20_roots()
        self.assertGreaterEqual(len(roots), 50)
        for r in roots:
            with self.subTest(r):
                raw = tf.build_raw(PUBLIC / r, WS)
                assert_valid(self, raw)
                self.assertFalse([x for x in raw["diagnostics"] if x["level"] == "error"])
        t06 = tf.build_raw(PUBLIC / "serverless-patterns" / "eventbridge-sns-lambda-terraform", WS)
        self.assertIn("TF-HEREDOC-TRAILING-SPACE", codes(t06))
        self.assertIn("$json", props(t06, "aws_sns_topic_policy.default")["policy"])


if __name__ == "__main__":
    unittest.main()
