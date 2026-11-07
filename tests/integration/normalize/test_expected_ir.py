"""正規化（段階 0〜4。フェーズ 3 の手順 3a・3b・4a）× 自作の構成 5 種 × TF／CFN: 正解 IR（expected）と比べる。

比べ方は `aws-iac-diagram-workspace/tools/compare_ir.py` の `compare`（CRITERIA.md の 1.0 の数え方）。辺は関係リソース（R-*）の
もの（R-SG を除く。手順 4a）だけを作るので、次を基準 1.0（CRITERIA の 1.1）で縛る:

- N（再現率・適合率）、名前の一致率、ノードの label、P（入れ子）: 1.0。合成ノードのうち `external/internet`（N-EXT-INTERNET。
  R-SG と一緒に手順 5）と `bedrock_model`（N-BEDROCK-MODEL。E-BEDROCK-* と一緒に手順 4b）は正解 IR から除いて比べる。
- E: 正解の辺のうち、根拠の規則に手順 4a のハンドラの規則（`edges.HANDLED`）を含むもの（`r_edges`）の再現率と、出力の辺の適合率
  （出力の辺はすべてそこに入る）、一致した辺の kind・label・confidence: 1.0。ほかの辺（E-ENV-REF・E-KB-STORAGE・E-IAM・E-ENV-STR・
  R-SG・N-*）は手順 4b・5。
- C（網羅分類）: 次の許しだけを除いて 1.0。許しは address と理由を固定する（`ALLOWED_C`）:
  ① R-SG（正解は into が辺の merged_into、H-SG-NOEDGE）→ 出力は仮の R-SG（into が空）。R-SG のハンドラは手順 5。
  ② R-LB-LISTENER → 出力の into は、正解の into から internet の辺（N-EXT-INTERNET。手順 5）を除いたもの。
- attrs（`access` を含む）: 正解と同じ。X1 のうち ② サブネットの access と ③ サブネット → IGW の辺は 0（internet の辺の ① は手順 5）。
- 参照の会計（CRITERIA の 1.8）: `NORM-UNUSED-REF` の件数を入力ごとに固定する（`UNUSED_REFS`。どれも手順 4b の E-* の材料）。
"""

from __future__ import annotations

import copy
import re
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.custom_inputs import NAMES, custom_raw, expected_ir
from support.tools import load_tool  # noqa: E402
from aws_iac_diagram.core import ir_norm, rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import build, edges as edges_mod  # noqa: E402

cmp = load_tool("compare_ir")

# 合成ノードの型 → 作る段階。手順 3b で作るのは AZ だけ（EDGE_SYNTHETIC は正解 IR から除いて比べる）
SYNTHETIC_TYPES = {"availability_zone": "N-AZ（入れ子の段階 4。手順 3b で作る）", "external": "N-EXT-INTERNET（辺の段階 3）",
                   "bedrock_model": "N-BEDROCK-MODEL（辺の段階 3）"}
EDGE_SYNTHETIC = {"external", "bedrock_model"}

# 入力ごとの AZ のノードの数（正解 IR と同じ。three-tier・three-tier-modules・vpc-endpoints は 2 つの AZ）
AZ_COUNTS = {"three-tier": 2, "three-tier-modules": 2, "serverless-api": 0, "rag": 0, "vpc-endpoints": 2}

# 正解 IR の規則 → 手順 4a の出力の仮の規則（R-SG のハンドラは手順 5）
PROVISIONAL = {"H-SG-NOEDGE": "R-SG", "R-SG": "R-SG"}
INTERNET = "external/internet"

# 入力ごとの、R-SG の仮の分類の件数（正解 IR の sources から数えたもの）と、internet の辺を除いた R-LB-LISTENER の件数
ALLOWED_C = {
    ("three-tier", "tf"): (4, 1), ("three-tier", "cfn"): (4, 1),
    ("three-tier-modules", "tf"): (5, 1), ("three-tier-modules", "cfn"): (4, 1),
    ("serverless-api", "tf"): (0, 0), ("serverless-api", "cfn"): (0, 0),
    ("rag", "tf"): (0, 0), ("rag", "cfn"): (0, 0),
    ("vpc-endpoints", "tf"): (2, 0), ("vpc-endpoints", "cfn"): (2, 0),
}

# 入力ごとの NORM-UNUSED-REF の件数（手順 4b の E-* が使う参照: タスク定義・Lambda の環境変数（E-ENV-REF）、
# KB の storage_configuration（E-KB-STORAGE）と vector_index_name）
UNUSED_REFS = {
    ("three-tier", "tf"): 1, ("three-tier", "cfn"): 1, ("three-tier-modules", "tf"): 1, ("three-tier-modules", "cfn"): 1,
    ("serverless-api", "tf"): 2, ("serverless-api", "cfn"): 2, ("rag", "tf"): 4, ("rag", "cfn"): 3,
    ("vpc-endpoints", "tf"): 0, ("vpc-endpoints", "cfn"): 0,
}


def r_edges(g: dict, fmt: str) -> set[tuple]:
    """正解の辺のうち、形式 fmt の根拠の規則に手順 4a のハンドラの規則を含むもの (from, to, kind)。internet からの辺
    （N-EXT-INTERNET。R-LB-LISTENER が根拠に入るが、合成ノードと一緒に手順 5 で作る）は除く。"""
    rules_of = {e["edge"]: set(e["rules"]) for e in g["sources"][fmt]["edges"]}
    return {(e["from"], e["to"], e["kind"]) for e in g["edges"]
            if rules_of.get(e["id"], set()) & edges_mod.HANDLED and e["from"] != INTERNET}


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
        self.assertEqual(self.rules.row("R-SG").get("fallback"), "H-SG-NOEDGE")
        self.assertNotIn("R-SG", edges_mod.HANDLED)
        self.assertEqual(set(ALLOWED_C), {(n, f) for n in NAMES for f in ("tf", "cfn")})
        self.assertEqual(set(UNUSED_REFS), set(ALLOWED_C))

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

    def test_classification_is_exact_except_the_allowed_ones(self):
        for (name, fmt), o in self.out.items():
            with self.subTest(name, fmt=fmt):
                g = expected_ir(name)
                r = cmp.compare(g, o, fmt)
                self.assertEqual(r["unknown"], 0)
                m, _ = cmp.id_map(g, o, fmt)
                gc, oc = cmp.class_map(g, fmt, {}), cmp.class_map(o, fmt, m)
                self.assertEqual(set(gc), set(oc), "網羅分類の address が正解と同じ（漏れ・余りが無い）")
                sg, listener = [], []
                for a in sorted(a for a in gc if gc[a] != oc[a]):
                    g_cls, g_into, g_rule = gc[a]
                    if g_rule in PROVISIONAL:  # ① R-SG（手順 5）
                        self.assertEqual(oc[a], ("merged_into", (), "R-SG"), a)
                        sg.append(a)
                    elif g_rule == "R-LB-LISTENER":  # ② internet の辺（手順 5）を除いたもの
                        self.assertEqual(oc[a], ("merged_into", tuple(x for x in g_into if not x.startswith(INTERNET + "->")), g_rule), a)
                        self.assertTrue(any(x.startswith(INTERNET + "->") for x in g_into), a)
                        listener.append(a)
                    else:
                        self.fail(f"許していない網羅分類の違い: {a} 正解 {gc[a]}、出力 {oc[a]}")
                self.assertEqual((len(sg), len(listener)), ALLOWED_C[(name, fmt)])
                hit, den = r["counts"]["C"]
                self.assertEqual(den - hit, len(sg) + len(listener))
                # 仮のまま残るのは R-SG だけ（ほかの R-* は辺か fallback に確定。辺ができず fallback も無いものは無い）
                self.assertEqual(sorted(a for a, v in oc.items() if v[0] == "merged_into" and not v[1]), sorted(sg))
                self.assertEqual([d for d in o["diagnostics"] if d["code"] in ("NORM-RELATION-NOEDGE", "NORM-MERGE-TARGET")], [])

    def test_relation_edges_match(self):
        for (name, fmt), o in self.out.items():
            with self.subTest(name, fmt=fmt):
                g = expected_ir(name)
                m, _ = cmp.id_map(g, o, fmt)
                want = r_edges(g, fmt)
                got = set(cmp.edge_list(o, m))
                self.assertTrue(want)
                self.assertEqual(got, want)  # 再現率・適合率（R-* の辺の範囲で）とも 1.0
                g_by = {(e["from"], e["to"]): e for e in g["edges"]}
                for e in o["edges"]:
                    ge = g_by[(m.get(e["from"], e["from"]), m.get(e["to"], e["to"]))]
                    self.assertEqual((e["kind"], e["label"], e["confidence"]), (ge["kind"], ge["label"], ge["confidence"]), e["id"])
                # 辺の根拠: すべての辺に 1 件、規則は正解の規則の中、根拠は空でない
                ev = {x["edge"]: x for x in o["sources"][fmt]["edges"]}
                g_ev = {x["edge"]: x for x in g["sources"][fmt]["edges"]}
                self.assertEqual(set(ev), {e["id"] for e in o["edges"]})
                for e in o["edges"]:
                    gid = f"{m.get(e['from'], e['from'])}->{m.get(e['to'], e['to'])}"
                    self.assertTrue(set(ev[e["id"]]["rules"]) <= set(g_ev[gid]["rules"]), (e["id"], ev[e["id"]]["rules"]))
                    self.assertTrue(ev[e["id"]]["evidence"])
                crit = cmp.compare(g, o, fmt)["critical"]
                self.assertEqual((crit["X2"], crit["X3"]), ([], []))
                # X1: サブネットの access（②）とサブネット → IGW（③）は 0。internet の辺（①）だけが手順 5 を待つ
                self.assertEqual([x for x in crit["X1"] if not x.startswith("internet の辺: 正解だけ")], [])

    def test_reference_accounting(self):
        for name in NAMES:
            for fmt in ("tf", "cfn"):
                with self.subTest(name, fmt=fmt):
                    raw = custom_raw(name, fmt)
                    res = build.run(raw, self.rules, name)
                    # active の参照すべてが、ちょうど 1 つの分類に入る
                    active = [r for r in raw["references"] if r["state"] == "active"]
                    self.assertEqual(len(res.accounting), len(active))
                    self.assertTrue(all(e.cls in ("edge", "noedge", "nonode", "unused") for e in res.accounting))
                    unused = [d for d in res.ir["diagnostics"] if d["code"] == "NORM-UNUSED-REF"]
                    self.assertEqual(len(unused), UNUSED_REFS[(name, fmt)], [(d["address"], d["path"]) for d in unused])
                    self.assertEqual(len(unused), sum(1 for e in res.accounting if e.cls == "unused"))
                    # 辺の根拠はすべて raw の参照の `<from>.<path>` で始まる（CRITERIA の 1.8 の照合）。例外は参照の無い根拠の 2 つの形
                    # （ir-schema の 4 章: SAM の暗黙の API のイベント、S3 の ARN の名前の一致）だけ
                    prefixes = {f"{r['from']}.{r['path']}" for r in active}
                    addresses = {r["address"] for r in raw["resources"]}
                    for x in res.ir["sources"][fmt]["edges"]:
                        for ev in x["evidence"]:
                            if any(ev == p or ev.startswith(p + " ") for p in prefixes):
                                continue
                            m = re.match(r"^(.+?)\.(Properties\.Events\.[^ ]+ \(Type: |source_arn \(S3 |SourceArn \(S3 )", ev)
                            self.assertTrue(m and m.group(1) in addresses, (x["edge"], ev))

    def test_tf_and_cfn_nodes_and_edges_are_the_same(self):
        # canonical 部（いまは internet・基盤モデルと E-*・R-SG の辺が無い）が TF 版と CFN 版で一致する（CRITERIA の 1.1 の c）
        for name in NAMES:
            with self.subTest(name):
                tf, cfn = (ir_norm.canonical_part(self.out[(name, f)]) for f in ("tf", "cfn"))
                self.assertEqual(tf, cfn)

    def test_attrs_match(self):
        # attrs（cidr・endpoint_type・service と、R-ROUTE で決まる access）は正解と同じ
        for (name, fmt), o in self.out.items():
            with self.subTest(name, fmt=fmt):
                g = expected_ir(name)
                m, _ = cmp.id_map(g, o, fmt)
                want = {n["id"]: n.get("attrs", {}) for n in g["nodes"] if n["type"] not in EDGE_SYNTHETIC}
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
