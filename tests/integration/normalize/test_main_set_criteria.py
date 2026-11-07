"""公開サンプルの主セット（CRITERIA の 1.2。12 入力）で、正規化の出力が正解 IR（expected/public/）と比べて基準を満たすこと（フェーズ 3 の手順 6）。

正解 IR は、正規化の出力を見る前に別のサブエージェントが書き、さらに別のサブエージェントがレビューした（設計草案の 7.3。
WORKLOG の「手順6」）。足りない辺は既知の限界だけであることも、件数と中身で固定する（後退に気づくため）。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.main_set import MAIN_SET, main_set_raw
from support.paths import WS
from support.tools import load_tool  # noqa: E402
from aws_iac_diagram.normalize import build  # noqa: E402

cmp = load_tool("compare_ir")
EXPECTED = WS / "expected" / "public"

# 正解にあって出力に無い辺（既知の限界。WORKLOG の「手順6」）
KNOWN_MISSING = {
    # API → ステートマシンの統合は OpenAPI（AWS::Include）の中にしか無く、raw に載らない（ir-schema の 8 章）
    "T11s": [("apigw_rest_api/api", "sfn_state_machine/statemachine", "request")],
    # Glue ジョブの引数の文字列（--DATABASE_NAME）は、どの辺の規則の対象でもない
    "T12": [("glue_job/data-quality-pipeline-catalog", "glue_catalog_database/sample_data_catalog", "data")],
}


class MainSetCriteriaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {}
        for sid, (fmt, _) in MAIN_SET.items():
            g = json.loads((EXPECTED / f"{sid}.ir.json").read_text(encoding="utf-8"))
            cls.results[sid] = cmp.compare(g, build.normalize(main_set_raw(sid), name=sid.lower()), fmt)

    def test_criteria_1_2_hold(self):
        summary = cmp.aggregate(self.results, "main")
        self.assertEqual(summary["failures"], [])

    def test_only_known_edges_are_missing_and_nothing_is_extra(self):
        for sid, r in self.results.items():
            with self.subTest(sid):
                self.assertEqual([tuple(e) for e in r["missing"]["E"]], KNOWN_MISSING.get(sid, []))
                self.assertEqual(r["extra"]["E"], [])
                self.assertEqual(r["missing"]["N"], [])
                self.assertEqual(r["extra"]["N"], [])
                self.assertEqual(r["critical"], {"X1": [], "X2": [], "X3": []})
                self.assertEqual(r["unknown"], 0)


if __name__ == "__main__":
    unittest.main()
