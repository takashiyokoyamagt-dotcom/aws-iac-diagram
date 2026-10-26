"""Terraform アダプタ: 変数の値の決め方（A4）。Terraform と同じ読み順で、後のものが優先する。本体は module_vars.py。"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props
from support.terraform import build, codes, write_files
import adapt_tf  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
