"""`.drawio`・coverage.md の出力の固定（フェーズ 4。C5）: 正解 IR 17 個の出力が manifest とバイト単位で一致する。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.tools import load_tool  # noqa: E402

tool = load_tool("diagram_public_check")


class GoldenDrawioTest(unittest.TestCase):
    def test_outputs_match_the_manifest(self):
        self.assertEqual(tool.check(), [])


if __name__ == "__main__":
    unittest.main()
