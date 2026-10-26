"""日本語とスペースを含むパスで、SKILL のスクリプトを別プロセスとして動かすテスト。

Windows（cp932 のコンソール）で文字コードやパスの扱いが崩れないかを確かめる。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import EXPECTED, ROOT, SCRIPTS


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300, check=False)


class JapanesePathTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "日本語 パス" / "出力 先"

    def test_doctor_writes_json(self):
        out = self.dir / "doctor.json"
        res = run(str(SCRIPTS / "doctor.py"), "--out", str(out))
        # draw.io や mmdc が無い環境では 1（warn）になる
        self.assertIn(res.returncode, (0, 1), res.stdout + res.stderr)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn(report["status"], ("ok", "warn"))
        self.assertEqual(report["skill"]["missing_files"], [])

    def test_doctor_stdout_is_ascii(self):
        res = run(str(SCRIPTS / "doctor.py"))
        self.assertIn(res.returncode, (0, 1), res.stderr)
        self.assertTrue(res.stdout.isascii())
        self.assertIn("status", json.loads(res.stdout))

    def test_doctor_incomplete_skill_is_error(self):
        # aws_iac_diagram/ が欠けた取り込みは warn（1）ではなく error（2）で、JSON も出す
        skill = self.dir / "aws-iac-diagram"
        shutil.copytree(SCRIPTS.parent, skill, ignore=shutil.ignore_patterns("aws_iac_diagram", "__pycache__"))
        out = self.dir / "doctor.json"
        res = run(str(skill / "scripts" / "doctor.py"), "--out", str(out))
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "error")
        self.assertIn("scripts/aws_iac_diagram/platform/drawio_cli.py", report["skill"]["missing_files"])
        self.assertTrue(any(i["level"] == "error" for i in report["issues"]))

    def test_doctor_unwritable_out_falls_back_to_stdout(self):
        self.dir.mkdir(parents=True)
        res = run(str(SCRIPTS / "doctor.py"), "--out", str(self.dir))  # 既存のフォルダ
        self.assertEqual(res.returncode, 2, res.stderr)
        report = json.loads(res.stdout)
        self.assertEqual(report["status"], "error")
        self.assertTrue(report["issues"])

    def test_validate_ir_on_japanese_path(self):
        self.dir.mkdir(parents=True)
        src = self.dir / "three-tier.ir.json"
        shutil.copyfile(EXPECTED / "three-tier.ir.json", src)
        res = run(str(SCRIPTS / "validate_ir.py"), str(src))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_adapt_tf_from_a_copy_of_the_skill_alone(self):
        # SKILL のフォルダだけを日本語とスペースを含む場所にコピーして動かす（リポジトリの tests・fixture・ツールに頼らない）。
        # 入口 adapt_tf.py は自分の場所から scripts/ を sys.path に入れるので、cwd にも元の場所にも依らない
        skill = self.dir / "aws-iac-diagram"
        shutil.copytree(SCRIPTS.parent, skill, ignore=shutil.ignore_patterns("__pycache__"))
        fixtures = ROOT / "aws-iac-diagram-workspace" / "fixtures" / "tf"
        want = self.dir / "from-repo.json"
        got = self.dir / "from-copy.json"
        res = run(str(SCRIPTS / "adapt_tf.py"), "--input", str(fixtures / "three-tier"), "--out", str(want),
                  "--root-base", str(fixtures.parent), "--var-file", "env/dev.tfvars")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        res = subprocess.run([sys.executable, str(skill / "scripts" / "adapt_tf.py"), "--input", str(fixtures / "three-tier"),
                              "--out", str(got), "--root-base", str(fixtures.parent), "--var-file", "env/dev.tfvars"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, check=False,
                             cwd=str(self.dir))  # 作業フォルダも別の場所
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertTrue(res.stdout.startswith("raw: resources="), res.stdout)
        self.assertEqual(got.read_bytes(), want.read_bytes())

    def test_adapt_tf_usage_errors_exit_2(self):
        self.dir.mkdir(parents=True)
        res = run(str(SCRIPTS / "adapt_tf.py"), "--input", str(self.dir), "--out", str(self.dir / "x.json"), "--var", "novalue")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("KEY=VALUE", res.stderr)
        res = run(str(SCRIPTS / "adapt_tf.py"), "--out", str(self.dir / "x.json"))  # --input が無い（argparse）
        self.assertEqual(res.returncode, 2, res.stderr)


    def test_adapt_cfn_from_a_copy_of_the_skill_alone(self):
        # adapt_tf と同じ。入口 adapt_cfn.py は自分の場所から scripts/ を sys.path に入れるので、cwd にも元の場所にも依らない
        skill = self.dir / "aws-iac-diagram"
        shutil.copytree(SCRIPTS.parent, skill, ignore=shutil.ignore_patterns("__pycache__"))
        fixtures = ROOT / "aws-iac-diagram-workspace" / "fixtures" / "cfn"
        want = self.dir / "from-repo.json"
        got = self.dir / "from-copy.json"
        args = ["--input", str(fixtures / "three-tier" / "template.yaml"), "--root-base", str(fixtures.parent),
                "--param", "EnvType=prod"]
        res = run(str(SCRIPTS / "adapt_cfn.py"), *args, "--out", str(want))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        res = subprocess.run([sys.executable, str(skill / "scripts" / "adapt_cfn.py"), *args, "--out", str(got)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, check=False,
                             cwd=str(self.dir))  # 作業フォルダも別の場所
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertTrue(res.stdout.startswith("raw: resources="), res.stdout)
        self.assertEqual(got.read_bytes(), want.read_bytes())

    def test_adapt_cfn_usage_errors_exit_2(self):
        self.dir.mkdir(parents=True)
        res = run(str(SCRIPTS / "adapt_cfn.py"), "--input", str(self.dir), "--out", str(self.dir / "x.json"), "--param", "noequal")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("KEY=VALUE", res.stderr)
        res = run(str(SCRIPTS / "adapt_cfn.py"), "--out", str(self.dir / "x.json"))  # --input が無い（argparse）
        self.assertEqual(res.returncode, 2, res.stderr)
        res = run(str(SCRIPTS / "adapt_cfn.py"), "--input", str(self.dir / "none.yaml"), "--out", str(self.dir / "x.json"))
        self.assertEqual(res.returncode, 2, res.stderr)  # 読めない入力
        self.assertIn("テンプレートを読めませんでした", res.stderr)


if __name__ == "__main__":
    unittest.main()
