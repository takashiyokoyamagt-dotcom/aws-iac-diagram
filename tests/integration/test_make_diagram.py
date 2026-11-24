"""入力から図まで一度に進める入口 make_diagram.py（フェーズ 6）: 形式の見分け、環境の確認の質問、3 形式までの通し。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import SCRIPTS  # noqa: E402

ROOT = SCRIPTS.parents[2]
FX = ROOT / "aws-iac-diagram-workspace" / "fixtures"
MAKE = SCRIPTS / "make_diagram.py"


def run(*args: str, env: dict | None = None) -> tuple[int, dict]:
    with tempfile.TemporaryDirectory() as t:
        out = Path(t) / "out"
        p = subprocess.run([sys.executable, str(MAKE), "--out-dir", str(out), *args], capture_output=True, text=True,
                           encoding="utf-8", env=dict(os.environ, PYTHONUTF8="1", **(env or {})))
        res = json.loads((out / "result.json").read_text(encoding="utf-8")) if (out / "result.json").is_file() else {}
        res["_files"] = sorted(x.name for x in (out / "diagram").glob("*")) if (out / "diagram").is_dir() else []
        return p.returncode, res


class MakeDiagramTest(unittest.TestCase):
    def test_terraform_with_several_environments_asks_first(self):
        code, res = run("--input", str(FX / "tf" / "three-tier"), "--no-external")
        self.assertEqual(code, 0)
        self.assertEqual(res["questions"][0]["choices"], ["env/dev.tfvars", "env/prod.tfvars"])
        self.assertEqual(res["_files"], [])  # どの環境の図か決まらないので書かない

    def test_terraform_with_a_var_file(self):
        code, res = run("--input", str(FX / "tf" / "three-tier"), "--var-file", str(FX / "tf" / "three-tier" / "env" / "dev.tfvars"), "--no-external")
        self.assertEqual(code, 0, res.get("steps"))
        self.assertEqual(res["questions"], [])
        self.assertEqual(sorted(res["diagram"]["views"]), ["detail", "network", "overview"])  # VPC があり、ルートの辺がある
        self.assertIn("three-tier.overview.drawio", res["_files"])
        self.assertIn("three-tier.overview.mmd", res["_files"])
        self.assertIn("coverage.md", res["_files"])

    def test_cloudformation_and_plan_json(self):
        code, res = run("--input", str(FX / "cfn" / "rag" / "template.yaml"), "--no-external")
        self.assertEqual((code, res["format"], res["diagram"]["name"]), (0, "cfn", "rag"))
        code, res = run("--input", str(FX / "tf-plan" / "rag.json"), "--no-external")
        self.assertEqual((code, res["format"]), (0, "tf-plan"))

    def test_missing_tools_are_skipped(self):
        code, res = run("--input", str(FX / "cfn" / "serverless-api" / "template.yaml"),
                        env={"DRAWIO": str(ROOT / "none.exe"), "MMDC": str(ROOT / "none.exe")})
        self.assertEqual(code, 0)
        for v in res["diagram"]["views"].values():
            self.assertEqual((v["png"]["status"], v["mermaid"]["status"]), ("skipped", "skipped"))

    def test_unknown_input_is_exit_2(self):
        code, res = run("--input", str(FX / "README.md") if (FX / "README.md").is_file() else str(ROOT / "README.md"))
        self.assertEqual(code, 2)
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
