"""正規化 × 公開サンプルの主セット（CRITERIA の 1.2。12 入力）の回帰テスト（フェーズ 3 の手順 4b の時点）。

主セットの正解 IR はまだ無いので、出力の形の数を入力ごとに固定する: 辺の数、`NORM-UNUSED-REF`（使わなかった参照）、
`NORM-RELATION-NOEDGE`（辺ができず fallback の無い関係リソース）、仮のままの分類の数。数が変わったら、意図した変更か確かめて
この表を直す（辺の規則が増えて辺が増え、使わなかった参照が減るのは意図した変化）。あわせて、網羅分類を入力から独立に数える
`check_coverage.py` の照合（X4）が 0 件であること。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.main_set import MAIN_SET, main_set_raw
from support.tools import load_tool  # noqa: E402
from aws_iac_diagram.normalize import build  # noqa: E402

cov = load_tool("check_coverage")

# 入力 → (辺, NORM-UNUSED-REF, NORM-RELATION-NOEDGE, 仮のままの分類)。仮の分類は R-SG（手順 5）と NORM-RELATION-NOEDGE のもの
EXPECTED = {
    "T03": (3, 0, 0, 1),
    "T06": (2, 0, 0, 0),
    "T06s": (2, 0, 0, 0),
    "T07": (2, 2, 0, 0),   # 使わなかった参照: Lambda のコードの置き場所（s3_bucket・s3_key）。関数 → テーブルは E-IAM だけ
                           # （環境変数の "Movies" は英字だけなので E-ENV-STR にしない）
    "T07s": (2, 0, 0, 0),  # 関数 → テーブル（SAM の Policies が 1 つの mapping の形。E-IAM）
    "T09": (3, 0, 0, 0),   # KB → 基盤モデル（N-BEDROCK-MODEL）・ベクトルストア、バケット → KB
    "T11": (2, 0, 0, 0),   # REST API → Step Functions（request_templates の中の参照）、Step Functions → テーブル（E-IAM の $concat の ARN）
    "T11s": (0, 1, 0, 0),  # API は OpenAPI（AWS::Include）の中で raw に載らない（既知の制約）。DefinitionSubstitutions は辺の規則が無い
    "T12": (4, 6, 1, 1),   # Glue のクローラ（E-GLUE-TARGET）と E-IAM。ジョブの script_location・default_arguments は辺の規則が無い。
                           # 条件の無い Glue のトリガー（辺を作らない。fallback が無い）
    "T16": (6, 1, 0, 12),  # 仮の 12 件は R-SG。使わなかった参照は KMS の黒箱のモジュールの出力（暗号化の設定）
    "C01": (3, 2, 0, 0),   # CloudFront → オリジン、Route 53 → CloudFront、関数 → バケット。使わなかった参照はログのバケット
    "C02": (7, 6, 0, 0),   # 使わなかった参照はログ・レプリケーションのバケットと、環境変数の CloudFront のドメイン名（kind の表に無い型）
}


class MainSetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = {}
        for sid in MAIN_SET:
            raw = main_set_raw(sid)
            cls.out[sid] = (raw, build.normalize(raw, None, sid.lower()))

    def test_counts_are_pinned(self):
        self.assertEqual(set(EXPECTED), set(MAIN_SET))
        for sid, (raw, ir) in self.out.items():
            with self.subTest(sid):
                codes = [d["code"] for d in ir["diagnostics"]]
                problems, provisional = build.check(raw, ir)
                self.assertEqual(problems, [])
                got = (len(ir["edges"]), codes.count("NORM-UNUSED-REF"), codes.count("NORM-RELATION-NOEDGE"), len(provisional))
                self.assertEqual(got, EXPECTED[sid])
                fmt = raw["format"]
                self.assertEqual([r for r in ir["sources"][fmt]["resources"] if r["class"] == "unknown"], [])  # CRITERIA 1.2 の j

    def test_t11_api_to_step_functions(self):
        _, ir = self.out["T11"]
        self.assertEqual([(e["from"].split("/")[0], e["to"].split("/")[0], e["kind"], e["label"], e["confidence"]) for e in ir["edges"]],
                         [("apigw_rest_api", "sfn_state_machine", "request", "ANY /, ANY /{id}", "derived"),
                          ("sfn_state_machine", "dynamodb_table", "data", "", "inferred")])

    def test_independent_coverage_check(self):
        for sid, (_, ir) in self.out.items():
            with self.subTest(sid):
                errs = [e for _, _, es, _ in cov.check_ir(ir) for e in es]
                self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()
