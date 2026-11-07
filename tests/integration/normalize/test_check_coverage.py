"""網羅分類の独立の照合（aws-iac-diagram-workspace/tools/check_coverage.py。X4）を、正規化の出力に当てる（設計草案の 6 章の手順 3）。

check_coverage.py は入力（fixture の .tf・テンプレート）を正規化を通さずに数え、IR の `sources` と突き合わせる。正規化の出力
（自作の構成 5 種 × TF／CFN）が通ること、網羅分類の漏れ・重複・余りをわざと作ると落ちることを確かめる。
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.custom_inputs import NAMES, custom_raw
from support.tools import load_tool  # noqa: E402
from aws_iac_diagram.normalize import build  # noqa: E402

cov = load_tool("check_coverage")


class CheckCoverageOnNormalizedTest(unittest.TestCase):
    def test_normalized_outputs_pass(self):
        for name in NAMES:
            for fmt in ("tf", "cfn"):
                with self.subTest(name, fmt=fmt):
                    ir = build.normalize(custom_raw(name, fmt), None, name)
                    results = cov.check_ir(ir)
                    self.assertEqual([f for f, *_ in results], [fmt])
                    self.assertEqual(results[0][2], [], results[0][2])

    def test_mutations_fail(self):
        ir = build.normalize(custom_raw("three-tier", "tf"), None, "three-tier")
        res = ir["sources"]["tf"]["resources"]
        cases = {
            "重複": lambda r: r.append(copy.deepcopy(r[0])),
            "漏れ": lambda r: r.pop(0),
            "余り": lambda r: r.append({"address": "aws_s3_bucket.nowhere", "type": "aws_s3_bucket", "file": "main.tf", "class": "unknown"}),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                bad = copy.deepcopy(ir)
                mutate(bad["sources"]["tf"]["resources"])
                errs = cov.check_ir(bad)[0][2]
                self.assertTrue(errs, label)
        self.assertTrue(res)


if __name__ == "__main__":
    unittest.main()
