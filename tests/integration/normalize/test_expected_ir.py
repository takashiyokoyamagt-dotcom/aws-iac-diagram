"""正規化（段階 0〜2 と 4。フェーズ 3 の手順 3a・3b）× 自作の構成 5 種 × TF／CFN: 正解 IR（expected）と比べる。

比べ方は `aws-iac-diagram-workspace/tools/compare_ir.py` の `compare`（CRITERIA.md の 1.0 の数え方）。辺（段階 3）はまだ作らないので、
**辺に依らないもの**を基準 1.0（CRITERIA の 1.1）で縛る:

- N（再現率・適合率）、名前の一致率、ノードの label: 1.0。AZ のノード（N-AZ。入れ子の段階 4）も含める。合成ノードのうち
  `external/internet`（N-EXT-INTERNET。R-SG・R-LB-LISTENER の辺の段階）と `bedrock_model`（N-BEDROCK-MODEL。E-BEDROCK-* の辺の段階）
  だけは正解 IR から除いて比べる（手順 3b の範囲の外）。
- P（入れ子の再現率・適合率。`(id, parent)` と `(id, span)`）: 1.0（同じく internet と基盤モデルは除く）。
- C（網羅分類）: 辺で決まる分類（`PROVISIONAL`）を除いて 1.0。辺で決まる分類は、**どの address が・なぜ違うか**を固定する:
  正解の規則が R-*（into が辺の id）なら、出力は同じ規則の仮の分類（`merged_into`、into が空）。正解が H-SG-NOEDGE・H-RT-NOROUTE
  （辺を 1 本も生まなかった SG・ルートテーブル）なら、出力はその fallback の元の R-SG・R-ROUTE の仮の分類。件数も入力ごとに固定する
  （`PROVISIONAL_COUNTS`。辺の段階を作ったら 0 になり、この許しは消す）。
- E はまだ数えない（出力の辺は 0）。X2・X3（正解に無い辺・逆向きの辺）は出力に辺が無いので 0 であること。
- attrs: `access` 以外（`cidr`・`endpoint_type`・`service`）は正解と同じ。`access` はルート（R-ROUTE。辺の段階）で決まる。
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.custom_inputs import NAMES, custom_raw, expected_ir
from support.tools import load_tool  # noqa: E402
from aws_iac_diagram.core import ir_norm, rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import build  # noqa: E402

cmp = load_tool("compare_ir")

# 合成ノードの型 → 作る段階。手順 3b で作るのは AZ だけ（EDGE_SYNTHETIC は正解 IR から除いて比べる）
SYNTHETIC_TYPES = {"availability_zone": "N-AZ（入れ子の段階 4。手順 3b で作る）", "external": "N-EXT-INTERNET（辺の段階 3）",
                   "bedrock_model": "N-BEDROCK-MODEL（辺の段階 3）"}
EDGE_SYNTHETIC = {"external", "bedrock_model"}

# 入力ごとの AZ のノードの数（正解 IR と同じ。three-tier・three-tier-modules・vpc-endpoints は 2 つの AZ）
AZ_COUNTS = {"three-tier": 2, "three-tier-modules": 2, "serverless-api": 0, "rag": 0, "vpc-endpoints": 2}

# 正解 IR の規則 → 手順 3a の出力の仮の規則（辺ができたかで決まる分類。設計草案の 4.1 の「仮分類と確定の分離」）
PROVISIONAL = {"H-SG-NOEDGE": "R-SG", "H-RT-NOROUTE": "R-ROUTE"}  # ほかに R-* はそのままの規則

# 入力ごとの、辺で決まる分類の件数（R-* と H-SG-NOEDGE・H-RT-NOROUTE。正解 IR の sources から数えたもの）
PROVISIONAL_COUNTS = {
    ("three-tier", "tf"): 16, ("three-tier", "cfn"): 17,
    ("three-tier-modules", "tf"): 18, ("three-tier-modules", "cfn"): 17,
    ("serverless-api", "tf"): 7, ("serverless-api", "cfn"): 2,
    ("rag", "tf"): 7, ("rag", "cfn"): 5,
    ("vpc-endpoints", "tf"): 12, ("vpc-endpoints", "cfn"): 12,
}


def without_edge_synthetic(g: dict) -> dict:
    """辺の段階で作る合成ノード（internet・基盤モデル）を除いた写し（AZ は残す）。"""
    g = copy.deepcopy(g)
    g["nodes"] = [n for n in g["nodes"] if n["type"] not in EDGE_SYNTHETIC]
    return g


class ExpectedIrTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = rules_mod.default()
        cls.out: dict[tuple[str, str], dict] = {}
        for name in NAMES:
            for fmt in ("tf", "cfn"):
                cls.out[(name, fmt)] = build.normalize(custom_raw(name, fmt), cls.rules, name)

    def test_provisional_table_matches_the_rules(self):
        # 表の対応は規則表の fallback と同じ（R-SG の fallback が H-SG-NOEDGE、R-ROUTE が H-RT-NOROUTE）
        for hidden, relation in PROVISIONAL.items():
            self.assertEqual(self.rules.row(relation).get("fallback"), hidden)
        self.assertEqual(set(PROVISIONAL_COUNTS), {(n, f) for n in NAMES for f in ("tf", "cfn")})

    def test_nodes_names_labels_and_placement_are_exact(self):
        for (name, fmt), o in self.out.items():
            with self.subTest(name, fmt=fmt):
                g = expected_ir(name)
                for n in g["nodes"]:
                    if n.get("synthetic"):
                        self.assertIn(n["type"], SYNTHETIC_TYPES, n["id"])
                self.assertFalse([n for n in o["nodes"] if n["type"] in EDGE_SYNTHETIC])
                self.assertEqual(len([n for n in o["nodes"] if n["type"] == "availability_zone"]), AZ_COUNTS[name])
                r = cmp.compare(without_edge_synthetic(g), o, fmt)
                c = r["counts"]
                for k in ("N.recall", "N.precision", "name", "node.label", "P.recall", "P.precision"):
                    hit, den = c[k]
                    self.assertGreater(den, 0, k)
                    self.assertEqual(hit, den, (k, r["missing"]["N"], r["extra"]["N"]))
                # 名前の一致は、正解の（合成でない）ノードのすべてで数えている
                self.assertEqual(c["name"][1], len([n for n in g["nodes"] if not n.get("synthetic")]))
                # AZ のノードの形（合成、group、親は VPC）も正解と同じ
                want = sorted((n["id"], n["name"], n["label"], n["parent"]) for n in g["nodes"] if n["type"] == "availability_zone")
                got = sorted((n["id"], n["name"], n["label"], n["parent"]) for n in o["nodes"] if n["type"] == "availability_zone")
                self.assertEqual(got, want)
                self.assertTrue(all(n.get("synthetic") and n["category"] == "group" for n in o["nodes"] if n["type"] == "availability_zone"))
                self.assertEqual([d for d in o["diagnostics"] if d["code"] in ("NORM-PLACEMENT", "NORM-AZ-UNKNOWN")], [])

    def test_classification_is_exact_except_edge_dependent_ones(self):
        for (name, fmt), o in self.out.items():
            with self.subTest(name, fmt=fmt):
                g = expected_ir(name)
                r = cmp.compare(g, o, fmt)
                self.assertEqual(r["unknown"], 0)
                m, _ = cmp.id_map(g, o, fmt)
                gc, oc = cmp.class_map(g, fmt, {}), cmp.class_map(o, fmt, m)
                self.assertEqual(set(gc), set(oc), "網羅分類の address が正解と同じ（漏れ・余りが無い）")
                differ = sorted(a for a in gc if gc[a] != oc[a])
                for a in differ:
                    g_cls, _, g_rule = gc[a]
                    want_rule = PROVISIONAL.get(g_rule, g_rule)
                    self.assertTrue((g_rule or "").startswith("R-") or g_rule in PROVISIONAL, (a, gc[a], oc[a]))
                    self.assertEqual(oc[a], ("merged_into", (), want_rule), a)
                # 逆に、辺で決まる分類はすべて仮（正解の R-* の into は辺なので、手順 3a では一致しない）
                edge_dependent = sorted(a for a, v in gc.items() if v[2] and (v[2].startswith("R-") or v[2] in PROVISIONAL))
                self.assertEqual(differ, edge_dependent)
                self.assertEqual(len(differ), PROVISIONAL_COUNTS[(name, fmt)])
                hit, den = r["counts"]["C"]
                self.assertEqual((hit, den - hit), (den - len(differ), len(differ)))

    def test_no_wrong_edges_and_no_edges_yet(self):
        for (name, fmt), o in self.out.items():
            with self.subTest(name, fmt=fmt):
                self.assertEqual(o["edges"], [])
                self.assertEqual(o["sources"][fmt]["edges"], [])
                crit = cmp.compare(expected_ir(name), o, fmt)["critical"]
                self.assertEqual((crit["X2"], crit["X3"]), ([], []))

    def test_tf_and_cfn_nodes_are_the_same(self):
        # canonical 部のノード（いまは internet・基盤モデルと attrs.access が無い）が TF 版と CFN 版で一致する（CRITERIA の 1.1 の c）
        for name in NAMES:
            with self.subTest(name):
                tf, cfn = (ir_norm.canonical_part(self.out[(name, f)]) for f in ("tf", "cfn"))
                self.assertEqual(tf["nodes"], cfn["nodes"])

    def test_attrs_match_the_expected_ones_that_do_not_need_edges(self):
        # attrs の cidr・endpoint_type・service は正解と同じ（access はルート R-ROUTE で決まるので、辺の段階の後）
        for (name, fmt), o in self.out.items():
            with self.subTest(name, fmt=fmt):
                g = expected_ir(name)
                m, _ = cmp.id_map(g, o, fmt)
                want = {n["id"]: {k: v for k, v in (n.get("attrs") or {}).items() if k != "access"}
                        for n in g["nodes"] if n["type"] not in EDGE_SYNTHETIC}
                got = {m.get(n["id"], n["id"]): n.get("attrs", {}) for n in o["nodes"]}
                self.assertEqual(got, want)

    def test_output_is_deterministic(self):
        # 同じ入力から同じ文字列。リソースと参照の順を逆にしても同じ（集合・入力の順に頼らない。C5）
        for name in ("three-tier", "vpc-endpoints"):
            for fmt in ("tf", "cfn"):
                with self.subTest(name, fmt=fmt):
                    raw = custom_raw(name, fmt)
                    first = ir_norm.canonical_dump(build.normalize(raw, self.rules, name))
                    self.assertEqual(first, ir_norm.canonical_dump(self.out[(name, fmt)]))
                    raw["resources"].reverse()
                    raw["references"].reverse()
                    self.assertEqual(ir_norm.canonical_dump(build.normalize(raw, self.rules, name)), first)


if __name__ == "__main__":
    unittest.main()
