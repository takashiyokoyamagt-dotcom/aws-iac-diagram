"""変異テスト（CRITERIA 1.7、C4）: 道具 aws-iac-diagram-workspace/tools/mutation_check.py のすべての変更で性質を満たす。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.tools import load_tool  # noqa: E402

tool = load_tool("mutation_check")


class MutationTest(unittest.TestCase):
    def test_every_mutation_keeps_the_properties(self):
        rules = tool.rules_mod.default()
        rows = [r for name, (folder, var_files) in tool.inputs().items() for r in tool.run_case(name, folder, var_files, rules)]
        applied = [r for r in rows if "note" not in r]
        self.assertEqual([r for r in applied if r["problems"]], [])
        self.assertGreaterEqual(len(applied), 20)  # 空振りの防止（2026-11-25 は 20）


if __name__ == "__main__":
    unittest.main()
