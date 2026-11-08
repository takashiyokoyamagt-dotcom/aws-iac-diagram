"""正規化の出力の固定（フェーズ 3 の手順 7）のテスト。道具は aws-iac-diagram-workspace/tools/golden_normalized.py。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.tools import load_tool  # noqa: E402

gn = load_tool("golden_normalized")


def heads(problems: list[str]) -> list[str]:
    return [p.split()[0] for p in problems]


class GoldenNormalizedTest(unittest.TestCase):
    def test_all_outputs_are_byte_identical_to_the_manifest(self):
        problems = gn.check()
        self.assertEqual(problems, [], "固定した normalized IR と違う（意図した変更でなければコードを直す）:\n" + "\n".join(problems))

    def test_every_case_is_written(self):
        cases = gn.load_manifest()["cases"]
        self.assertEqual(len(cases), 101)
        self.assertEqual({e["exit"] for e in cases.values()} - {0, 1}, set())

    def test_compare_reports_each_kind_of_difference(self):
        exp = {"a": {"sha256": "0" * 64, "exit": 0, "bytes": 1, "nodes": 1, "edges": 0}, "gone": {}}
        same = {"code": 0, "sha256": "0" * 64, "bytes": 1, "nodes": 1, "edges": 0, "abs_paths": []}
        self.assertEqual(gn.compare({"a": same}, {"a": exp["a"]}, partial=False), [])
        self.assertEqual(heads(gn.compare({"a": same | {"sha256": "1" * 64}}, exp, partial=True)), ["CHANGED"])
        self.assertEqual(heads(gn.compare({"a": same | {"code": 1}}, exp, partial=True)), ["CHANGED"])
        self.assertEqual(heads(gn.compare({"a": same | {"abs_paths": ["C:/x"]}}, exp, partial=True)), ["ABSPATH"])
        self.assertEqual(heads(gn.compare({"a": {"code": None, "stderr": "x"}}, exp, partial=True)), ["FAILED"])
        self.assertEqual(heads(gn.compare({"b": same}, {}, partial=True)), ["NEW"])
        self.assertEqual(heads(gn.compare({"a": same}, exp, partial=False)), ["MISSING"])


if __name__ == "__main__":
    unittest.main()
