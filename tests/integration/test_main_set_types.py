"""公開サンプルの主セット（CRITERIA の 1.2。12 入力）のリソースの型が、規則表（data/rules/）のどれかの行に入ること（フェーズ 3 の手順 2）。

主セットの `unknown` 0 件（CRITERIA の 1.2）の前提を、正規化を作る前に raw IR の段階で縛る。`when` の条件までは見ない
（行の選び方は正規化の分類のテストで見る）。TF の `data` は H-DATA か `data = true` の描く型、AWS 以外のプロバイダの型は
H-NONAWS（規則表のどの型にも当たらなくてよい）なので数えない。CFN の入力は `Custom::<名前>` などもすべて数える。
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.main_set import MAIN_SET
from support.paths import PUBLIC, WS
from aws_iac_diagram.adapters.cloudformation import build as cfn_build  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402
from aws_iac_diagram.core import rules  # noqa: E402

def is_data(r: dict) -> bool:
    return r["address"].startswith("data.") or ".data." in r["address"]


def unknown_types(raw: dict, table: rules.Rules) -> list[str]:
    out = []
    for r in raw["resources"]:
        t = r["type"]
        if is_data(r) or table.rows_for_input_type(t):
            continue
        if t.startswith("aws_") or raw["format"] == "cfn":  # CFN は Custom::<名前> なども数える
            out.append(f'{r["address"]}: {t}')
    return out


class MainSetTypesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = rules.load()
        cls.raws = {}
        for sid, (fmt, rel) in MAIN_SET.items():
            build = tf_build.build_raw if fmt == "tf" else cfn_build.build_raw
            cls.raws[sid] = build(PUBLIC / rel, WS)

    def test_every_resource_type_has_a_row(self):
        for sid, raw in self.raws.items():
            with self.subTest(sid):
                self.assertTrue(raw["resources"])
                self.assertEqual(unknown_types(raw, self.rules), [])

    def test_existing_bucket_data_is_drawable(self):
        # 設計草案 8 章の 3 (c): T09 の既存バケット（data.aws_s3_bucket）は data = true の描く型 s3_bucket に当たる
        r = next(r for r in self.raws["T09"]["resources"] if is_data(r) and r["type"] == "aws_s3_bucket")
        rows = self.rules.rows_for_input_type(r["type"])
        self.assertEqual([(x.id, x.get("data")) for x in rows], [("s3_bucket", True)])

    def test_detects_a_missing_row(self):
        # 検査そのものが働くこと: 型の行を 1 つ外すと、その型のリソースが報告される
        good = self.rules
        bad = dataclasses.replace(good, types=tuple(x for x in good.types if x.id != "glue_job"))
        self.assertEqual(unknown_types(self.raws["T12"], good), [])
        self.assertTrue(any(s.endswith(": aws_glue_job") for s in unknown_types(self.raws["T12"], bad)))


if __name__ == "__main__":
    unittest.main()
