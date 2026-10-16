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

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "aws-iac-diagram" / "scripts"
EXPECTED = ROOT / "aws-iac-diagram-workspace" / "expected"


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
        # lib/ が欠けた取り込みは warn（1）ではなく error（2）で、JSON も出す
        skill = self.dir / "aws-iac-diagram"
        shutil.copytree(SCRIPTS.parent, skill, ignore=shutil.ignore_patterns("lib", "__pycache__"))
        out = self.dir / "doctor.json"
        res = run(str(skill / "scripts" / "doctor.py"), "--out", str(out))
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "error")
        self.assertIn("scripts/lib/drawio_cli.py", report["skill"]["missing_files"])
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


if __name__ == "__main__":
    unittest.main()
