"""正規化（段階 0〜4。フェーズ 3 の手順 3a〜5）× 自作の構成 5 種 × TF／CFN: 正解 IR（expected）と比べる（CRITERIA の 1.1）。

比べ方は `aws-iac-diagram-workspace/tools/compare_ir.py` の `compare`（CRITERIA.md の 1.0 の数え方）。手順 5（R-SG と
N-EXT-INTERNET）で自作の 5 構成が完了したので、許可リストは無く、次をすべて 1.0／0 で縛る:

- a: N（再現率・適合率。合成ノードの AZ・`external/internet`・`bedrock_model` を含む）、E（再現率、確定・導出と推定の適合率）、
  P（入れ子）、名前の一致率、C（網羅分類）、一致した辺の confidence・label・kind、ノードの label。`unknown` は 0。
- b: 重大な誤り X1〜X3（compare の critical）が 0、X4（`check_coverage.check_ir`。入力から独立に数えた網羅分類との照合）が 0。
- c: TF 版と CFN 版の canonical 部（`core/ir_norm.canonical_part`）がバイト列で一致。
- ほか: attrs（`access` を含む）が正解と同じ、辺の根拠の規則が正解の規則の中、参照の会計（CRITERIA の 1.8）で `NORM-UNUSED-REF` 0、
  仮のままの分類・`NORM-RELATION-NOEDGE`・`NORM-MERGE-TARGET` が 0、`build.check` が問題なし、出力が決定論的。
"""

from __future__ import annotations

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
cov = load_tool("check_coverage")

# 合成ノードの型 → 作る段階
SYNTHETIC_TYPES = {"availability_zone": "N-AZ（入れ子の段階 4。手順 3b）", "external": "N-EXT-INTERNET（辺の段階 3。手順 5）",
                   "bedrock_model": "N-BEDROCK-MODEL（辺の段階 3。手順 4b）"}

# 入力ごとの AZ のノードの数（正解 IR と同じ。three-tier・three-tier-modules・vpc-endpoints は 2 つの AZ）
AZ_COUNTS = {"three-tier": 2, "three-tier-modules": 2, "serverless-api": 0, "rag": 0, "vpc-endpoints": 2}
INTERNET = "external/internet"
# 1.0 で縛る数（CRITERIA の 1.1 の a）
EXACT = ("N.recall", "N.precision", "name", "E.recall", "E.precision.confirmed_derived", "E.precision.inferred", "P.recall",
         "P.precision", "C", "edge.confidence", "edge.label", "node.label")


class ExpectedIrTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = rules_mod.default()
        cls.raw: dict[tuple[str, str], dict] = {}
        cls.out: dict[tuple[str, str], dict] = {}
        for name in NAMES:
            for fmt in ("tf", "cfn"):
                cls.raw[(name, fmt)] = custom_raw(name, fmt)
                cls.out[(name, fmt)] = build.normalize(cls.raw[(name, fmt)], cls.rules, name)

    def test_all_relation_rules_have_handlers(self):
        self.assertEqual(self.rules.row("R-SG").get("fallback"), "H-SG-NOEDGE")
        self.assertIn("R-SG", edges_mod.HANDLED)

    def test_criteria_1_1_a_and_b_are_exact(self):
        for (name, fmt), o in self.out.items():
            with self.subTest(name, fmt=fmt):
                g = expected_ir(name)
                r = cmp.compare(g, o, fmt)
                self.assertEqual(r["unknown"], 0)
                for k in EXACT:
                    hit, den = r["counts"][k]
                    self.assertEqual(hit, den, (k, r["missing"], r["extra"]))
                for k in ("N.recall", "E.recall", "P.recall", "C", "name", "node.label"):
                    self.assertGreater(r["counts"][k][1], 0, k)
                # 名前の一致は、正解の（合成でない）ノードのすべてで数えている
                self.assertEqual(r["counts"]["name"][1], len([n for n in g["nodes"] if not n.get("synthetic")]))
                self.assertEqual({k: v for k, v in r["critical"].items() if v}, {})  # X1〜X3
                self.assertEqual([e for _, _, es, _ in cov.check_ir(o) for e in es], [])  # X4
                self.assertEqual(build.check(self.raw[(name, fmt)], o), ([], []))
                self.assertEqual([d for d in o["diagnostics"] if d["code"] in ("NORM-RELATION-NOEDGE", "NORM-MERGE-TARGET",
                                                                              "NORM-PLACEMENT", "NORM-AZ-UNKNOWN")], [])

    def test_edge_kinds_match(self):
        # compare は辺を (from, to, kind) で数えるが、kind の取り違えを直接も確かめる
        for (name, fmt), o in self.out.items():
            with self.subTest(name, fmt=fmt):
                g = expected_ir(name)
                m, _ = cmp.id_map(g, o, fmt)
                want = {(e["from"], e["to"]): (e["kind"], e["label"], e["confidence"]) for e in g["edges"]}
                got = {(m.get(e["from"], e["from"]), m.get(e["to"], e["to"])): (e["kind"], e["label"], e["confidence"]) for e in o["edges"]}
                self.assertEqual(got, want)
                # 辺の根拠: すべての辺に 1 件、規則は正解の規則の中（正解は N-BEDROCK-MODEL・E-REF-NONODE も書くことがある）、根拠は空でない
                ev = {x["edge"]: x for x in o["sources"][fmt]["edges"]}
                g_ev = {x["edge"]: x for x in g["sources"][fmt]["edges"]}
                self.assertEqual(set(ev), {e["id"] for e in o["edges"]})
                for e in o["edges"]:
                    gid = f"{m.get(e['from'], e['from'])}->{m.get(e['to'], e['to'])}"
                    self.assertTrue(set(ev[e["id"]]["rules"]) <= set(g_ev[gid]["rules"]), (e["id"], ev[e["id"]]["rules"]))
                    if INTERNET in (e["from"], e["to"]) or "R-SG" in g_ev[gid]["rules"]:  # 手順 5 の辺は根拠の規則まで正解と同じ
                        self.assertEqual(ev[e["id"]]["rules"], g_ev[gid]["rules"], e["id"])
                    self.assertTrue(ev[e["id"]]["evidence"])

    def test_synthetic_nodes(self):
        for (name, fmt), o in self.out.items():
            with self.subTest(name, fmt=fmt):
                g = expected_ir(name)
                for n in g["nodes"]:
                    if n.get("synthetic"):
                        self.assertIn(n["type"], SYNTHETIC_TYPES, n["id"])
                self.assertEqual(len([n for n in o["nodes"] if n["type"] == "availability_zone"]), AZ_COUNTS[name])
                keys = ("id", "type", "category", "name", "label", "parent", "synthetic")
                want = sorted(tuple(n.get(k) for k in keys) for n in g["nodes"] if n.get("synthetic"))
                got = sorted(tuple(n.get(k) for k in keys) for n in o["nodes"] if n.get("synthetic"))
                self.assertEqual(got, want)
                # internet のノードは、そこからの辺があるときだけ（構成ごとに 1 つ）
                self.assertEqual(any(n["id"] == INTERNET for n in o["nodes"]), any(e["from"] == INTERNET for e in o["edges"]))

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
                    self.assertEqual(unused, [])
                    self.assertEqual(len(unused), sum(1 for e in res.accounting if e.cls == "unused"))
                    # 辺の根拠はすべて raw の参照の `<from>.<path>` で始まる（CRITERIA の 1.8 の照合）。例外は参照の無い根拠
                    # （ir-schema の 4 章: `<address>.<位置> (<説明>)`。文字列の一致、SAM の暗黙の API のイベントなど）だけ
                    prefixes = {f"{r['from']}.{r['path']}" for r in active}
                    addresses = {r["address"] for r in raw["resources"]}
                    for x in res.ir["sources"][fmt]["edges"]:
                        for ev in x["evidence"]:
                            if any(ev == p or ev.startswith(p + " ") for p in prefixes):
                                continue
                            head = ev.split(" (", 1)[0]
                            self.assertIn(" (", ev, (x["edge"], ev))
                            self.assertTrue(any(head.startswith(a + ".") for a in addresses), (x["edge"], ev))

    def test_tf_and_cfn_nodes_and_edges_are_the_same(self):
        # canonical 部（合成ノード・R-SG・internet の辺を含む）が TF 版と CFN 版でバイト列で一致する（CRITERIA の 1.1 の c）
        for name in NAMES:
            with self.subTest(name):
                tf, cfn = (ir_norm.canonical_part(self.out[(name, f)]) for f in ("tf", "cfn"))
                self.assertEqual(tf, cfn)
                self.assertEqual(ir_norm.canonical_dump(tf).encode("utf-8"), ir_norm.canonical_dump(cfn).encode("utf-8"))

    def test_attrs_match(self):
        # attrs（cidr・endpoint_type・service と、R-ROUTE で決まる access）は正解と同じ（X1 の ② も 0）
        for (name, fmt), o in self.out.items():
            with self.subTest(name, fmt=fmt):
                g = expected_ir(name)
                m, _ = cmp.id_map(g, o, fmt)
                want = {n["id"]: n.get("attrs", {}) for n in g["nodes"]}
                got = {m.get(n["id"], n["id"]): n.get("attrs", {}) for n in o["nodes"]}
                self.assertEqual(got, want)

    def test_output_is_deterministic(self):
        # 同じ入力から同じ文字列。リソースと参照の順を逆にしても同じ（集合・入力の順に頼らない。C5）
        for name in NAMES:
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
