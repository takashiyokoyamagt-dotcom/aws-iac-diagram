"""Terraform アダプタ: .tf の読み込み（hcl.py・module_load.py）。block の種類（ephemeral・check の中の data・override のファイル）、
heredoc、CRLF、読めないファイル、無視するファイル名、出力の書き込み。
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs
from support.paths import FIXTURES_TF as FIXTURES, SCRIPTS, WS
from support.terraform import build, codes, res
import adapt_tf  # noqa: E402
import validate_ir as v  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build, hcl  # noqa: E402


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
        # ほかの .tf は読む。plan JSON と一緒のときの扱いは tests/unit/terraform/plan/test_plan_diagnostics.py
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


if __name__ == "__main__":
    unittest.main()
