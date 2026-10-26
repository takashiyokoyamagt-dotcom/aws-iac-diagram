"""Terraform アダプタ: 式の評価（locals・テンプレート・条件・for 式・関数）と、値の扱い（unknown・jsonencode・heredoc・path.*）。
評価の本体は aws_iac_diagram/adapters/terraform/（module_expr.py・evaluator/）。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs
from support.paths import SCRIPTS, WS
from support.terraform import build, codes, res, write_files
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
