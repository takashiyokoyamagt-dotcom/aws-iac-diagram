"""doctor.py の REQUIRED_FILES（SKILL が実行時に使う同梱ファイルの一覧）が、実際のファイルとずれないことのテスト。

doctor は PEP 723 の依存を持たず、パッケージを import できない取り込みでも動かすので、ファイルの有無だけを見る。
そのため一覧は手で持つ。モジュールを足して一覧に足し忘れる／消したファイルを一覧に残す、を失敗にする。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "aws-iac-diagram"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))
import doctor  # noqa: E402

# 実行時に読むデータ（スクリプトが開くもの）。scripts/ の .py と SKILL.md 以外はここに書く。
# 足し忘れは、下の test_data_paths_in_scripts_are_listed が、スクリプトの中の "references" / "…" の連なりから見つける
RUNTIME_DATA = {
    "references/icons/catalog.json",       # find_aws_icon.py
    "references/ir.schema.json",           # validate_ir.py
    "references/ir-raw.schema.json",       # validate_ir.py
    "references/resource-catalog.md",      # validate_ir.py（規則の ID の照合）
    "references/relation-resources.md",    # validate_ir.py
    "references/edge-rules.md",            # validate_ir.py
    "references/module-summaries.md",      # TF アダプタ（modules/summaries.py）
}


def runtime_python_files() -> set[str]:
    return {p.relative_to(SKILL).as_posix() for p in SCRIPTS.rglob("*.py")
            if "__pycache__" not in p.parts and "maintenance" not in p.parts}


class RequiredFilesTest(unittest.TestCase):
    def test_list_equals_the_runtime_files_on_disk(self):
        want = runtime_python_files() | RUNTIME_DATA | {"SKILL.md"}
        got = doctor.REQUIRED_FILES
        self.assertEqual(len(got), len(set(got)), "REQUIRED_FILES に重複がある")
        self.assertEqual(sorted(set(got) - want), [], "REQUIRED_FILES にあるが、実行時のファイルでない（消した／名前が違う）")
        self.assertEqual(sorted(want - set(got)), [], "実行時のファイルなのに REQUIRED_FILES に無い（足し忘れ）")
        for rel in got:
            self.assertTrue((SKILL / rel).is_file(), rel)

    def test_maintenance_scripts_are_not_required(self):
        self.assertFalse([f for f in doctor.REQUIRED_FILES if "maintenance" in f])
        self.assertTrue(any(SCRIPTS.joinpath("maintenance").glob("*.py")))  # 除いた対象が実在する

    def test_data_paths_in_scripts_are_listed(self):
        # "references" / "icons" / "catalog.json" の形（Path の連なり）で書かれたデータを、スクリプトから拾う
        chain = re.compile(r'"references"((?:\s*/\s*"[^"]+")+)')
        found: set[str] = set()
        for p in runtime_python_files():
            if p.endswith("doctor.py"):
                continue
            for m in chain.finditer((SKILL / p).read_text(encoding="utf-8")):
                found.add("references/" + "/".join(re.findall(r'"([^"]+)"', m.group(1))))
        self.assertTrue(found, "スクリプトから 1 つも拾えない（正規表現が古い）")
        self.assertEqual(sorted(found - RUNTIME_DATA), [], "スクリプトが開くデータが RUNTIME_DATA に無い")

    def test_each_missing_file_is_reported(self):
        # 一覧の全ファイルを 1 つずつ消して、doctor の確認（check_skill）が必ずそのファイルを欠けとして報告する
        with tempfile.TemporaryDirectory() as t:
            fake = Path(t) / "日本語 パス" / "skill"
            for rel in doctor.REQUIRED_FILES:
                (fake / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(SKILL / rel, fake / rel)
            old = doctor.SKILL_DIR
            doctor.SKILL_DIR = fake
            try:
                issues: list[dict] = []
                self.assertEqual(doctor.check_skill(issues)["missing_files"], [])
                self.assertEqual(issues, [])
                for rel in doctor.REQUIRED_FILES:
                    gone = fake / rel
                    saved = gone.read_bytes()
                    gone.unlink()
                    try:
                        issues = []
                        report = doctor.check_skill(issues)
                        self.assertEqual(report["missing_files"], [rel], rel)
                        self.assertEqual([i["level"] for i in issues], ["error"], rel)
                        self.assertIn(rel, issues[0]["message"])
                    finally:
                        gone.write_bytes(saved)
            finally:
                doctor.SKILL_DIR = old

    def test_deleting_one_package_module_makes_doctor_exit_2(self):
        # 部分的な取り込み（TF アダプタのモジュールが 1 つ欠けた）は、実行前に doctor が error（終了コード 2）で見つける
        with tempfile.TemporaryDirectory() as t:
            skill = Path(t) / "日本語 パス" / "aws-iac-diagram"
            shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns("__pycache__"))
            victim = "scripts/aws_iac_diagram/adapters/terraform/hcl.py"
            (skill / victim).unlink()
            out = Path(t) / "doctor.json"
            res = subprocess.run([sys.executable, str(skill / "scripts" / "doctor.py"), "--out", str(out)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
            self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
            import json
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "error")
            self.assertEqual(report["skill"]["missing_files"], [victim])


if __name__ == "__main__":
    unittest.main()
