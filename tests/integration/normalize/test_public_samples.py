"""正規化 × 公開サンプルのすべて（フェーズ 3 の手順 6 の後半）。道具は aws-iac-diagram-workspace/tools/normalize_public_check.py。

1. 全公開サンプルの 64 入力（survey_public.py の SAMPLES のすべてのルート。T20 は 26 ルート、T18 は 3、P01 は 2、C04 は 3 テンプレート。
   主セット・補助セット（CRITERIA の 6 章）・大きいサンプル T17・T19・C05・P01〜P04 を含む）で、例外が出ない・網羅分類の漏れと
   重複が無い（`build.check` と、入力を独立に数える check_coverage の X4）・validate_ir の検査を通る（CRITERIA の 6 章の m）。
   数（リソース・ノード・辺・R-SG の辺・`unknown`・`NORM-UNUSED-REF`）を入力ごとに固定する（6 章の m と 1.8 の l。`unknown` と
   `NORM-UNUSED-REF` は件数の基準が無いので、増減に気づくための固定）。数が変わったら、意図した変更か確かめて表を直す（型の行を
   足して `unknown` が減るのは意図した変化）。直列で約 40 秒かかるので、プロセスを並列にして流す。
2. TF／SAM の対（CRITERIA の 1.4 の n。T06・T07・T11。参考に T01・T05）: ノードの型の多重集合が「許す違いの一覧」（道具の
   PAIR_ALLOWED。正規化の出力を見る前に書いた）を除いて一致し、辺の (from の型, to の型, kind) の多重集合の一致率が 0.90 以上。
   T06・T07 は満たす。T11 は満たさない（SAM 版の API → ステートマシンが、CFN アダプタが AWS::Include を展開しないので出ない。
   道具の KNOWN_LIMITATIONS）。「NG（既知の制約・ユーザーの確認待ち）」として、違いがその 1 件だけであることを固定する。
"""

from __future__ import annotations

import contextlib
import copy
import io
import os
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.main_set import MAIN_SET
import normalize_public_check as chk  # noqa: E402
import survey_public  # noqa: E402

# 入力 → (リソース, ノード, 辺, R-SG の辺, unknown, NORM-UNUSED-REF)（2026-11-08 の測定。規則表は手順 2 で凍結したもの）。
# `unknown` の型と NORM-UNUSED-REF の属性名の内訳は、道具の表（`normalize_public_check.py` を引数なしで）で出す
PINNED = {
    "T01": (5, 2, 1, 0, 0, 0),
    "T02": (14, 5, 0, 0, 0, 2),
    "T03": (18, 9, 3, 0, 0, 0),
    "T04": (17, 5, 2, 0, 0, 0),
    "T05": (9, 2, 1, 0, 0, 0),
    "T06": (12, 3, 2, 0, 0, 0),
    "T07": (17, 5, 3, 0, 0, 2),
    "T08": (11, 4, 2, 0, 0, 4),
    "T09": (17, 4, 3, 0, 0, 0),
    "T10": (11, 3, 1, 1, 3, 3),
    "T11": (29, 4, 3, 0, 0, 0),
    "T12": (29, 5, 4, 0, 0, 6),
    "T13": (46, 16, 5, 0, 14, 21),
    "T14": (55, 19, 8, 0, 9, 15),
    "T15": (90, 3, 2, 0, 1, 1),
    "T16": (65, 14, 6, 0, 0, 1),
    "T17": (139, 19, 8, 2, 21, 49),
    "T18:environment": (23, 7, 0, 0, 3, 3),
    "T18:eks-blue": (26, 10, 0, 0, 2, 19),
    "T18:eks-green": (26, 10, 0, 0, 2, 19),
    "T19": (198, 59, 17, 0, 57, 58),
    "T20:datasources/aurora": (44, 2, 0, 0, 12, 13),
    "T20:datasources/cockroach": (41, 4, 6, 6, 5, 7),
    "T20:datasources/data-generator": (38, 1, 0, 0, 1, 1),
    "T20:datasources/msk": (33, 1, 0, 0, 9, 7),
    "T20:datasources/oracle": (37, 1, 0, 0, 13, 7),
    "T20:flink": (48, 0, 0, 0, 21, 4),
    "T20:foundation/athena": (4, 0, 0, 0, 1, 0),
    "T20:foundation/buckets": (31, 4, 0, 0, 8, 8),
    "T20:foundation/glue-databases": (51, 8, 0, 0, 24, 32),
    "T20:foundation/iam-roles": (34, 0, 0, 0, 6, 0),
    "T20:foundation/kms-keys": (22, 0, 0, 0, 20, 10),
    "T20:foundation/network": (31, 6, 3, 0, 6, 2),
    "T20:foundation/s3-tables": (39, 0, 0, 0, 29, 43),
    "T20:ingestion-layer/debezium-aurora": (21, 0, 0, 0, 3, 4),
    "T20:ingestion-layer/debezium-oracle": (23, 0, 0, 0, 3, 4),
    "T20:ingestion-layer/dms-aurora": (23, 0, 0, 0, 5, 4),
    "T20:ingestion-layer/dms-oracle": (25, 0, 0, 0, 5, 4),
    "T20:ingestion-layer/firehose-streams/aurora-brokerage-msk-firehose-stream": (54, 1, 0, 0, 11, 4),
    "T20:ingestion-layer/firehose-streams/aurora-financial-msk-firehose-stream": (54, 1, 0, 0, 11, 4),
    "T20:ingestion-layer/firehose-streams/cockroach-brokerage-msk-firehose-stream": (50, 1, 0, 0, 11, 4),
    "T20:ingestion-layer/firehose-streams/cockroach-financial-msk-firehose-stream": (50, 1, 0, 0, 11, 4),
    "T20:ingestion-layer/firehose-streams/msk-brokerage-firehose-stream": (43, 0, 0, 0, 11, 2),
    "T20:ingestion-layer/firehose-streams/msk-financial-firehose-stream": (43, 0, 0, 0, 11, 2),
    "T20:ingestion-layer/firehose-streams/oracle-brokerage-msk-firehose-stream": (54, 1, 0, 0, 11, 4),
    "T20:ingestion-layer/firehose-streams/oracle-financial-msk-firehose-stream": (54, 1, 0, 0, 11, 4),
    "T20:ingestion-layer/msk-ingest": (55, 2, 0, 0, 25, 15),
    "P01:simple": (175, 7, 0, 0, 0, 0),
    "P01:complete": (220, 32, 15, 0, 8, 2),
    "P02": (145, 17, 7, 1, 7, 13),
    "P03": (97, 19, 6, 0, 0, 2),
    "P04": (57, 15, 3, 0, 8, 8),
    "C01": (16, 5, 3, 0, 0, 2),
    "C02": (42, 14, 8, 0, 0, 6),
    "C03": (26, 10, 4, 0, 5, 4),
    "C04:VPCPeering-Requester": (15, 0, 0, 0, 1, 0),
    "C04:VPCPeering-Accepter": (18, 1, 0, 0, 1, 1),
    "C04:VPCPeering-Updates": (12, 0, 0, 0, 0, 0),
    "C05": (63, 16, 6, 1, 9, 14),
    "T01s": (3, 2, 1, 0, 0, 0),
    "T05s": (2, 2, 1, 0, 0, 0),
    "T06s": (4, 3, 2, 0, 0, 0),
    "T07s": (3, 4, 3, 0, 0, 0),
    "T11s": (6, 4, 2, 0, 0, 1),
}

# CRITERIA の 6 章の補助セット（15 入力。T18・T20・C04 は複数のルート）
SUPPLEMENTARY = ("T01", "T01s", "T05", "T05s", "T02", "T04", "T08", "T10", "T13", "T14", "T15", "T18", "T20", "C03", "C04")


def jobs() -> int:
    return max(1, min(4, os.cpu_count() or 1))


class PublicSamplesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {r["id"]: r for r in chk.run_inputs(list(chk.INPUTS), jobs())}

    def test_inputs_are_every_public_root(self):
        self.assertEqual(len(chk.INPUTS), 64)
        self.assertEqual(len([i for i in chk.INPUTS if i.startswith("T20:")]), 26)
        self.assertEqual(set(PINNED), set(chk.INPUTS))
        for sid in (*survey_public.SAMPLES, *SUPPLEMENTARY, *MAIN_SET, "T17", "T19", "C05"):
            self.assertTrue(chk.select([sid]), sid)
        with self.assertRaises(KeyError):
            chk.select(["T99"])

    def test_no_crash_no_x4_and_valid(self):
        # CRITERIA の 6 章（例外で止まらない、X4 が 0、validate_ir が通る）と、網羅分類の自分での検査・仮の分類が残らないこと
        for iid, r in self.results.items():
            with self.subTest(iid):
                self.assertEqual(r["problems"], [])

    def test_counts_are_pinned(self):
        for iid, r in self.results.items():
            with self.subTest(iid):
                got = (r["resources"], r["nodes"], r["edges"], r["edges_r_sg"], sum(r["unknown"].values()), r["unused_refs"])
                self.assertEqual(got, PINNED[iid])
                self.assertLessEqual(r["unused_refs"], r["references_active"])

    def test_main_set_has_no_unknown(self):
        # CRITERIA の 1.2 の j。補助セット・大きいサンプルは件数を出すだけ（6 章。大きいサンプルの 1.3 はフェーズ 6）
        for sid in MAIN_SET:
            self.assertEqual(self.results[sid]["unknown"], {}, sid)

    def test_t19_and_t20_edges(self):
        # 設計草案の 8 章の 6: R-SG の辺の組合せは T19・T20 で増えない（T19 は R-SG の辺 0、T20 は 26 ルートで 6）
        t19 = self.results["T19"]
        self.assertEqual((t19["edges"], t19["edges_r_sg"], t19["edges_by_kind"]), (17, 0, {"request": 11, "route": 6}))
        t20 = [r for i, r in self.results.items() if i.startswith("T20:")]
        self.assertEqual((sum(r["edges"] for r in t20), sum(r["edges_r_sg"] for r in t20)), (9, 6))

    def test_a_failing_input_is_reported(self):
        with mock.patch.dict(chk.INPUTS, {"X99": ("tf", "serverless-patterns/does-not-exist")}):
            r = chk.check_input("X99")
        self.assertEqual(len(r["problems"]), 1)
        self.assertIn("adapter exception", r["problems"][0])

    def test_main_exit_codes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(chk.main(["--only", "T01", "T05s"]), 0)
            bad = [{"id": "T01", "format": "tf", "problems": ["normalize exception X"]}]
            with mock.patch.object(chk, "run_inputs", return_value=bad):
                self.assertEqual(chk.main(["--only", "T01"]), 1)
        self.assertIn("NG T01: normalize exception X", out.getvalue())


class PairTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs = {r["pair"].split("+")[0]: r for r in chk.run_pairs()}

    def test_pairs(self):
        self.assertEqual(chk.CRITERIA_PAIRS, ("T06", "T07", "T11"))
        self.assertEqual(set(chk.PAIRS), {"T01", "T05", "T06", "T07", "T11"})
        self.assertEqual(set(chk.PAIR_ALLOWED), set(chk.PAIRS))

    def test_criteria_1_4(self):
        # T06・T07 は 1.4 を満たす（T07 は許す違い 2 件）。T11 は満たさない: 違いは既知の制約 1 件だけで、
        # 「NG（既知の制約・ユーザーの確認待ち）」と出す（許す違いではない。2026-11-08 の第三者レビュー）
        status = {p: (r["status"], r["criteria_1_4"], r["problems"]) for p, r in self.pairs.items()}
        self.assertEqual(status, {"T06": ("OK", True, []), "T07": ("OK", True, []),
                                  "T11": (chk.LIMITATION_NG, False, []),
                                  "T01": ("OK", True, []), "T05": ("OK", True, [])})
        self.assertEqual(chk.LIMITATION_NG, "NG（既知の制約・ユーザーの確認待ち）")
        t11 = self.pairs["T11"]
        self.assertEqual(t11["criteria_failures"], ["辺の一致率 0.667 < 0.9"])
        self.assertEqual(len(t11["known_limitations"]), 1)
        self.assertEqual(t11["edges"]["only_tf"], [[["apigw_rest_api", "sfn_state_machine", "request"], 1]])
        self.assertEqual(t11["edge_match"], {"raw": 2 / 3, "allowed_removed": 2 / 3, "limitations_removed": 1.0})
        self.assertEqual(set(chk.KNOWN_LIMITATIONS), {"T11"})
        self.assertEqual(chk.PAIR_ALLOWED["T11"]["edges"], {"only_tf": {}, "only_sam": {}})  # 既知の制約は許す違いに入れない
        # T07 の型の置き換え（HTTP API → REST API）は 1 件で、出力にも件数を出す
        self.assertEqual(self.pairs["T07"]["same_type"], [["apigw_http_api", "apigw_rest_api", 1]])
        self.assertEqual({p: r["edge_match"]["allowed_removed"] for p, r in self.pairs.items() if p != "T11"},
                         {"T06": 1.0, "T07": 1.0, "T01": 1.0, "T05": 1.0})

    def test_every_allowed_difference_has_a_reason(self):
        for pid, allow in chk.PAIR_ALLOWED.items():
            for tf_type, (sam_type, n, why) in allow["same_type"].items():
                self.assertNotEqual(tf_type, sam_type)
                self.assertGreater(n, 0)
                self.assertGreater(len(why), 10, (pid, tf_type))
        for table in (chk.PAIR_ALLOWED, chk.KNOWN_LIMITATIONS):
            for pid, allow in table.items():
                for what in ("nodes", "edges"):
                    self.assertEqual(set(allow[what]), {"only_tf", "only_sam"})
                    for side, items in allow[what].items():
                        for k, (n, why) in items.items():
                            with self.subTest(pid=pid, what=what, side=side, key=k):
                                self.assertGreater(n, 0)
                                self.assertGreater(len(why), 10)

    def test_unlisted_or_unused_differences_fail(self):
        tf_ir, sam_ir = (chk.build.normalize(chk.raw_of(i), name=i.lower()) for i in ("T06", "T06s"))
        self.assertEqual(chk.compare_pair_irs("T06", tf_ir, sam_ir)["status"], "OK")
        # 辺を 1 本消すと、一覧に無い違い（1.4 の辺の一致率も 0.5 で下回る）。既知の制約の無い対なので、ただの NG
        bad = copy.deepcopy(sam_ir)
        bad["edges"] = bad["edges"][:1]
        r = chk.compare_pair_irs("T06", tf_ir, bad)
        self.assertEqual((r["status"], r["criteria_1_4"]), ("NG", False))
        self.assertTrue(any("edges only_tf" in p for p in r["problems"]), r["problems"])
        # ノードの型が一覧を超えて違えば NG（1.4 のノードの基準も満たさない）
        extra = copy.deepcopy(sam_ir)
        extra["nodes"].append({"id": "sqs_queue/x", "type": "sqs_queue"})
        r = chk.compare_pair_irs("T06", tf_ir, extra)
        self.assertEqual(r["status"], "NG")
        self.assertIn("ノードの型の多重集合が、許す違いを除いて一致しない", r["criteria_failures"])
        # 既知の制約が起きなくなった（T11 の API → ステートマシンが SAM 版にも出た）ら、表が古いので NG
        t11, t11s = (chk.build.normalize(chk.raw_of(i), name=i.lower()) for i in ("T11", "T11s"))
        api = next(n["id"] for n in t11s["nodes"] if n["type"] == "apigw_rest_api")
        sfn = next(n["id"] for n in t11s["nodes"] if n["type"] == "sfn_state_machine")
        t11s["edges"].append({"id": f"{api}->{sfn}", "from": api, "to": sfn, "kind": "request"})
        r = chk.compare_pair_irs("T11", t11, t11s)
        self.assertEqual(r["status"], "NG")
        self.assertTrue(r["criteria_1_4"])
        self.assertTrue(any("edges only_tf" in p for p in r["problems"]), r["problems"])
        # 型の置き換え（same_type）の件数が一覧と合わなければ NG
        t07, t07s = (chk.build.normalize(chk.raw_of(i), name=i.lower()) for i in ("T07", "T07s"))
        two = copy.deepcopy(t07)
        two["nodes"].append({"id": "apigw_http_api/second", "type": "apigw_http_api"})
        two_s = copy.deepcopy(t07s)
        two_s["nodes"].append({"id": "apigw_rest_api/second", "type": "apigw_rest_api"})
        r = chk.compare_pair_irs("T07", two, two_s)
        self.assertEqual(r["same_type"], [["apigw_http_api", "apigw_rest_api", 2]])
        self.assertEqual(r["status"], "NG")
        self.assertTrue(any("same_type" in p for p in r["problems"]), r["problems"])

    def test_main_reports_the_known_limitation(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(chk.main(["--pairs"]), 1)  # ユーザーが決めるまで失敗として返す
        self.assertIn("NG（既知の制約・ユーザーの確認待ち） T11+T11s", out.getvalue())
        self.assertIn("same_type apigw_http_api → apigw_rest_api x1", out.getvalue())

    def test_match_ratio(self):
        self.assertEqual(chk.match_ratio(Counter(a=2, b=1), Counter(a=1, b=1, c=2)), 2 / 4)
        self.assertIsNone(chk.match_ratio(Counter(), Counter()))


if __name__ == "__main__":
    unittest.main()
