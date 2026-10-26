"""Terraform アダプタ: 手順2 の第三者レビュー（「修正コミット」）で見つかったものの再現ケース。
sensitive 関数・ephemeral な変数、redact、無効な block の参照エラー、count の文字列、変数のファイルの誤り。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs
from support.terraform import build, write_files
import adapt_tf  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build, model, module_eval  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
