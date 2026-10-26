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
# 足し忘れは、下の test_data_paths_in_scripts_are_listed が、core/paths.py の定数（場所の決め方の唯一の置き場）から見つける
RUNTIME_DATA = {
    "data/icons/catalog.json",                          # find_aws_icon.py
    "data/schemas/ir.schema.json",                      # validate_ir.py
    "data/schemas/ir-raw.schema.json",                  # validate_ir.py
    "data/module-summaries/iam-only-sources.md",        # TF アダプタ（modules/summaries.py）。H-IAM の source の一覧
    "data/module-summaries/terraform-aws-alb/v10.md",   # 同上。モジュールの要約表
    "data/module-summaries/terraform-aws-eks/v21.md",
    "data/module-summaries/terraform-aws-rds/v7.md",
    "data/module-summaries/terraform-aws-vpc/v6.md",
    "references/resource-catalog.md",                   # validate_ir.py（規則の ID の照合）。フェーズ 3 で data/rules/ へ
    "references/relation-resources.md",                 # validate_ir.py
    "references/edge-rules.md",                         # validate_ir.py
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
        # 場所の決め方は core/paths.py だけにある。そこにある Path の定数が指すファイル（ディレクトリは中の .md と .json）が、
        # 一覧にある実行時のデータの中にあることを確かめる。あわせて、ほかのスクリプトが SKILL の下のフォルダ名を直接書いていない
        from aws_iac_diagram.core import paths
        pointed: set[str] = set()
        for name, val in vars(paths).items():
            if name.startswith("_"):
                continue
            for q in (val if isinstance(val, tuple) else (val,)):
                if not isinstance(q, Path):
                    continue
                if q.is_dir():
                    if q.name in ("module-summaries", "schemas"):
                        pointed |= {f.relative_to(SKILL).as_posix() for f in q.rglob("*") if f.is_file()}
                elif q.suffix:
                    pointed.add(q.relative_to(SKILL).as_posix())
        pointed -= {"data/icons/broken.json"}  # 保守用（check_icons.py の出力。実行時には読まない）
        self.assertTrue(pointed, "paths.py から 1 つも拾えない")
        self.assertEqual(sorted(pointed - RUNTIME_DATA), [], "paths.py のデータが RUNTIME_DATA に無い")
        self.assertEqual(sorted(RUNTIME_DATA - pointed), [], "RUNTIME_DATA にあるが paths.py が指さない")
        # SKILL のフォルダ名（"references"・"data"）を Path の連なりで直接書いているスクリプトが無い（paths.py を使う）
        chain = re.compile(r'"(?:references|data)"\s*/\s*"')
        for p in runtime_python_files():
            if p.endswith(("doctor.py", "core/paths.py")):
                continue
            self.assertIsNone(chain.search((SKILL / p).read_text(encoding="utf-8")), f"{p} が SKILL の下のパスを直接書いている")

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
