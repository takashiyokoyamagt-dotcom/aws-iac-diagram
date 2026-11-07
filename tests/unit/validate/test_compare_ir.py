"""正解 IR との比較ツール（aws-iac-diagram-workspace/tools/compare_ir.py。設計草案の 7.1）のテスト。

誤りの種類ごとに、期待の件数が出ること（id の対応づけ、名前の一致率、向きの違い、X2 と X3 の排他、母数 10 未満の扱い）と、
基準値が CRITERIA.md の表と同じであること。
"""
from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import WS
from support.tools import load_tool  # noqa: E402

cmp = load_tool("compare_ir")
EXPECTED = WS / "expected"


def load(name: str) -> dict:
    return json.loads((EXPECTED / f"{name}.ir.json").read_text(encoding="utf-8"))


def rename(ir: dict, old: str, new: str) -> dict:
    """ノードの id を、辺・入れ子・由来部まで含めて置き換えた写し（名前を 1 つ間違えた出力）。"""
    text = json.dumps(ir, ensure_ascii=False)
    return json.loads(text.replace(json.dumps(old)[1:-1], json.dumps(new)[1:-1]))


class IdentityTest(unittest.TestCase):
    def test_expected_irs_match_themselves(self):
        for p in sorted(EXPECTED.glob("*.ir.json")):
            g = json.loads(p.read_text(encoding="utf-8"))
            for fmt in ("tf", "cfn"):
                with self.subTest(p.name, fmt=fmt):
                    r = cmp.compare(g, copy.deepcopy(g), fmt)
                    self.assertEqual({k: v for k, v in r["counts"].items() if v[0] != v[1]}, {})
                    self.assertEqual(r["critical"], {"X1": [], "X2": [], "X3": []})
                    self.assertEqual(cmp.aggregate({p.name: r}, "custom")["failures"], [])


class MappingTest(unittest.TestCase):
    def setUp(self):
        self.g = load("serverless-api")

    def test_a_wrong_name_only_lowers_the_name_rate(self):
        o = rename(self.g, "dynamodb_table/shop-orders", "dynamodb_table/shop-orderz")
        r = cmp.compare(self.g, o, "tf")
        c = r["counts"]
        for k in ("N.recall", "N.precision", "E.recall", "P.recall", "C"):
            self.assertEqual(c[k][0], c[k][1], k)
        self.assertEqual(c["name"][1] - c["name"][0], 1)

    def test_unmapped_nodes_compare_by_id(self):
        # 由来部の address を消すと対応づかず、名前違いはノードの欠けと余りになる
        o = rename(self.g, "dynamodb_table/shop-orders", "dynamodb_table/shop-orderz")
        for fmt in ("tf", "cfn"):
            o["sources"][fmt]["resources"] = [r for r in o["sources"][fmt]["resources"] if r.get("node") != "dynamodb_table/shop-orderz"]
        r = cmp.compare(self.g, o, "tf")
        self.assertEqual(r["missing"]["N"], [("dynamodb_table/shop-orders", "dynamodb_table")])
        self.assertEqual(r["extra"]["N"], [("dynamodb_table/shop-orderz", "dynamodb_table")])

    def test_two_output_nodes_on_one_expected_node(self):
        # O の 2 つのノードが同じ address を持つときは、id 順で最初の 1 つだけを対応づける
        o = copy.deepcopy(self.g)
        src = next(n for n in o["nodes"] if n["id"] == "dynamodb_table/shop-orders")
        o["nodes"].append({**src, "id": "dynamodb_table/a-copy"})
        res = o["sources"]["tf"]["resources"]
        res.append({**next(r for r in res if r.get("node") == "dynamodb_table/shop-orders"), "node": "dynamodb_table/a-copy"})
        m, pairs = cmp.id_map(self.g, o, "tf")
        self.assertEqual(m["dynamodb_table/a-copy"], "dynamodb_table/shop-orders")
        self.assertNotIn("dynamodb_table/shop-orders", m)  # 2 つ目は id のまま
        r = cmp.compare(self.g, o, "tf")
        self.assertEqual(r["counts"]["N.precision"], (len(self.g["nodes"]), len(self.g["nodes"]) + 1))


class EdgeErrorsTest(unittest.TestCase):
    def setUp(self):
        self.g = load("serverless-api")
        self.strong = next(e for e in self.g["edges"] if e["confidence"] in ("confirmed", "derived"))

    def test_reversed_edge_is_x3_not_x2(self):
        o = copy.deepcopy(self.g)
        e = next(x for x in o["edges"] if x["id"] == self.strong["id"])
        e["from"], e["to"] = e["to"], e["from"]
        r = cmp.compare(self.g, o, "tf")
        self.assertEqual(r["critical"]["X3"], [[self.strong["to"], self.strong["from"]]])
        self.assertEqual(r["critical"]["X2"], [])
        self.assertEqual(r["counts"]["E.recall"][1] - r["counts"]["E.recall"][0], 1)
        self.assertEqual(r["counts"]["E.undirected"][0], r["counts"]["E.undirected"][1])  # 向きを無視すれば一致

    def test_edge_without_any_basis_is_x2(self):
        o = copy.deepcopy(self.g)
        a, b = "apigw_http_api/shop-api", "sqs_queue/shop-order-events"
        self.assertFalse(any({e["from"], e["to"]} == {a, b} for e in self.g["edges"]))
        o["edges"].append({"from": a, "to": b, "kind": "event", "confidence": "derived", "id": f"{a}->{b}"})
        r = cmp.compare(self.g, o, "tf")
        self.assertEqual(r["critical"]["X2"], [[a, b]])
        # 推定の辺なら重大な誤りではなく、推定の適合率だけが下がる
        o["edges"][-1]["confidence"] = "inferred"
        r = cmp.compare(self.g, o, "tf")
        self.assertEqual(r["critical"]["X2"], [])
        self.assertEqual(r["counts"]["E.precision.inferred"][1] - r["counts"]["E.precision.inferred"][0], 1)

    def test_kind_only_difference_is_not_critical(self):
        o = copy.deepcopy(self.g)
        next(x for x in o["edges"] if x["id"] == self.strong["id"])["kind"] = "network"
        r = cmp.compare(self.g, o, "tf")
        self.assertEqual(r["critical"], {"X1": [], "X2": [], "X3": []})
        self.assertEqual(r["counts"]["E.recall"][1] - r["counts"]["E.recall"][0], 1)

    def test_internet_and_access_are_x1(self):
        g = load("three-tier")
        o = copy.deepcopy(g)
        sub = next(n for n in o["nodes"] if n.get("type") == "subnet" and (n.get("attrs") or {}).get("access") == "private")
        sub["attrs"]["access"] = "public"
        o["edges"] = [e for e in o["edges"] if cmp.INTERNET not in (e["from"], e["to"])]
        x1 = cmp.compare(g, o, "tf")["critical"]["X1"]
        self.assertTrue(any("access" in x and sub["id"] in x for x in x1))
        self.assertTrue(any(x.startswith("internet の辺: 正解だけ") for x in x1))


class JudgeTest(unittest.TestCase):
    def fake(self, counts: dict) -> dict:
        return {"counts": counts, "unknown": 0, "critical": {"X1": [], "X2": [], "X3": []}}

    def test_small_denominator_allows_one_error(self):
        one = self.fake({"E.recall": (4, 5)})
        two = self.fake({"E.recall": (3, 5)})
        big = {"E.recall": (99, 100)}
        # 全体の基準（0.90）は満たすように、大きい入力を足す
        self.assertEqual(cmp.aggregate({"a": one, "big": self.fake(big)}, "main")["failures"], [])
        fails = cmp.aggregate({"a": two, "big": self.fake(big)}, "main")["failures"]
        self.assertEqual(len(fails), 1)
        self.assertIn("a: E.recall の誤り 2 件", fails[0])
        # 母数 10 以上は割合（0.80）
        self.assertTrue(cmp.aggregate({"a": self.fake({"E.recall": (7, 10)}), "big": self.fake(big)}, "main")["failures"])
        self.assertEqual(cmp.aggregate({"a": self.fake({"E.recall": (8, 10)}), "big": self.fake(big)}, "main")["failures"], [])

    def test_micro_average(self):
        s = cmp.aggregate({"a": self.fake({"N.recall": (1, 2)}), "b": self.fake({"N.recall": (9, 9)})}, "custom")
        self.assertAlmostEqual(s["ratios"]["N.recall"], 10 / 11)

    def test_unknown_and_critical_fail(self):
        r = self.fake({})
        r["unknown"] = 1
        self.assertIn("a: unknown 1 件", cmp.aggregate({"a": r}, "main")["failures"])

    def test_bad_input_is_a_usage_error(self):
        with self.assertRaises(cmp.UsageError):
            cmp.compare({}, {}, "yaml")
        with self.assertRaises(cmp.UsageError):
            cmp.aggregate({}, "nope")
        self.assertEqual(cmp.main(["--pair", "no-such.json", "no-such.json", "tf"]), 2)


class MoreErrorsTest(unittest.TestCase):
    """レビュー（2026-11-07）の変異テストで見逃した退行を捕まえる。"""

    def setUp(self):
        self.g = load("three-tier")

    def test_route_to_igw_is_x1(self):
        types = {n["id"]: n["type"] for n in self.g["nodes"]}
        route = next(e for e in self.g["edges"] if types.get(e["from"]) == "subnet" and types.get(e["to"]) == "internet_gateway")
        o = copy.deepcopy(self.g)
        o["edges"] = [e for e in o["edges"] if e["id"] != route["id"]]
        x1 = cmp.compare(self.g, o, "tf")["critical"]["X1"]
        self.assertEqual(x1, [f"サブネット → IGW: 正解だけ {(route['from'], route['to'])}"])

    def test_attached_metrics(self):
        o = copy.deepcopy(self.g)
        o["edges"][0]["confidence"] = "inferred" if o["edges"][0]["confidence"] != "inferred" else "confirmed"
        o["edges"][1]["label"] = "wrong"
        o["nodes"][0]["label"] = "wrong"
        c = cmp.compare(self.g, o, "tf")["counts"]
        for k in ("edge.confidence", "edge.label", "node.label"):
            self.assertEqual(c[k][1] - c[k][0], 1, k)

    def test_placement_is_remapped_and_counts_parents_and_spans(self):
        sub = next(n["id"] for n in self.g["nodes"] if n["type"] == "subnet"
                   and any(sub_ in (m.get("spans") or ()) for m in self.g["nodes"] for sub_ in [n["id"]]))
        o = rename(self.g, sub, sub + "-x")
        c = cmp.compare(self.g, o, "tf")["counts"]
        self.assertEqual(c["P.recall"][0], c["P.recall"][1])  # 名前違いでも置き換えて入れ子は一致
        self.assertEqual(c["name"][1] - c["name"][0], 1)
        # 親を変えると、再現率と適合率が 1 件ずつ下がる（最上位の None も 1 組として数える）
        o = copy.deepcopy(self.g)
        top = next(n for n in o["nodes"] if n.get("parent") is None and n["type"] != "vpc")
        top["parent"] = next(n["id"] for n in o["nodes"] if n["type"] == "vpc")
        c = cmp.compare(self.g, o, "tf")["counts"]
        self.assertEqual((c["P.recall"][1] - c["P.recall"][0], c["P.precision"][1] - c["P.precision"][0]), (1, 1))

    def test_class_and_rule_errors_count_in_c(self):
        for change in ("class", "rule"):
            o = copy.deepcopy(self.g)
            r = next(x for x in o["sources"]["tf"]["resources"] if x["class"] == "merged_into")
            if change == "class":
                r["class"] = "hidden"
            else:
                r["rule"] = "M-WRONG"
            c = cmp.compare(self.g, o, "tf")["counts"]["C"]
            self.assertEqual(c[1] - c[0], 1, change)

    def test_inferred_precision_only_counts_inferred_edges(self):
        g = load("serverless-api")
        n_inf = sum(1 for e in g["edges"] if e["confidence"] == "inferred")
        self.assertGreater(n_inf, 0)
        c = cmp.compare(g, copy.deepcopy(g), "tf")["counts"]
        self.assertEqual(c["E.precision.inferred"], (n_inf, n_inf))
        self.assertEqual(c["E.precision.confirmed_derived"], (len(g["edges"]) - n_inf,) * 2)

    def test_reversed_edge_also_present_is_not_x3(self):
        g = load("serverless-api")
        e = next(x for x in g["edges"] if x["confidence"] in ("confirmed", "derived"))
        o = copy.deepcopy(g)
        o["edges"].append({**e, "from": e["to"], "to": e["from"], "id": f"{e['to']}->{e['from']}"})
        crit = cmp.compare(g, o, "tf")["critical"]
        self.assertEqual(crit["X3"], [[e["to"], e["from"]]])  # 正解に (b, a) だけがあり、(a, b) が無い
        o2 = copy.deepcopy(o)
        g2 = copy.deepcopy(g)
        g2["edges"].append(o["edges"][-1])  # 正解にも逆向きがあれば X3 ではない
        self.assertEqual(cmp.compare(g2, o2, "tf")["critical"]["X3"], [])

    def test_aggregate_fails_on_critical_and_overall_floor(self):
        r = cmp.compare(self.g, copy.deepcopy(self.g), "tf")
        r["critical"]["X2"] = [["a", "b"]]
        self.assertTrue(any("X2" in f for f in cmp.aggregate({"a": r}, "main")["failures"]))
        # 入力ごとには下限（母数 10 未満で誤り 1 件）を満たすが、全体の 0.95 を下回る
        many = {f"i{k}": {"counts": {"N.recall": (8, 9)}, "unknown": 0, "critical": {"X1": [], "X2": [], "X3": []}} for k in range(5)}
        self.assertEqual(cmp.aggregate(many, "main")["failures"], ["N.recall: 全体 0.889 < 0.95"])

    def test_first_hit_only(self):
        # O のノード a（G1・G2 の address）と b（G1 の address）: a は G1 に、b は使用済みなので id のまま（G2 には回さない）
        g = {"nodes": [{"id": "t/g1", "type": "t"}, {"id": "t/g2", "type": "t"}], "edges": [],
             "sources": {"tf": {"resources": [{"address": "x.1", "class": "drawn", "node": "t/g1"},
                                              {"address": "x.2", "class": "drawn", "node": "t/g2"}]}}}
        o = {"nodes": [{"id": "t/a", "type": "t"}, {"id": "t/b", "type": "t"}], "edges": [],
             "sources": {"tf": {"resources": [{"address": "x.1", "class": "drawn", "node": "t/a"},
                                              {"address": "x.2", "class": "drawn", "node": "t/a"},
                                              {"address": "x.1", "class": "drawn", "node": "t/b"}]}}}
        self.assertEqual(cmp.id_map(g, o, "tf")[0], {"t/a": "t/g1"})


class CliTest(unittest.TestCase):
    def run_cli(self, *args) -> tuple[int, str]:
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            return cmp.main(list(args)), out.getvalue()

    def test_same_output_name_is_not_overwritten(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            g = load("rag")
            bad = copy.deepcopy(g)
            bad["nodes"] = bad["nodes"][:3]
            for d, ir in (("a", load("three-tier")), ("b", bad)):
                (Path(t) / d).mkdir()
                (Path(t) / d / "out.json").write_text(json.dumps(ir), encoding="utf-8")
            code, out = self.run_cli("--json", "--pair", str(EXPECTED / "rag.ir.json"), str(Path(t) / "b" / "out.json"), "tf",
                                     "--pair", str(EXPECTED / "three-tier.ir.json"), str(Path(t) / "a" / "out.json"), "tf")
            self.assertEqual(code, 1)
            self.assertEqual(len(json.loads(out)["inputs"]), 2)

    def test_not_an_ir_is_a_usage_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            for text in ("[]", '{"nodes": [{"type": "x"}]}'):
                (Path(t) / "x.json").write_text(text, encoding="utf-8")
                code, _ = self.run_cli("--pair", str(EXPECTED / "rag.ir.json"), str(Path(t) / "x.json"), "tf")
                self.assertEqual(code, 2, text)


class ThresholdsTest(unittest.TestCase):
    def test_main_set_thresholds_match_criteria(self):
        # CRITERIA.md の 1.2 の表の数字と同じ（ツールが基準を勝手に変えない）
        text = (WS / "evals" / "CRITERIA.md").read_text(encoding="utf-8")
        sec = text.split("### 1.2 ", 1)[1].split("\n### ", 1)[0]
        rows = {}
        for line in sec.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 3 and re.search(r"\*\*[0-9.]+", cells[1]):
                overall = float(re.search(r"\*\*([0-9.]+)", cells[1]).group(1))
                floor = re.search(r"([0-9.]+) 以上", cells[2])
                rows[cells[0]] = (overall, float(floor.group(1)) if floor else None)
        names = {"N の再現率・適合率": ["N.recall", "N.precision"], "名前の一致率": ["name"], "E の再現率": ["E.recall"],
                 "E の適合率（確定・導出の辺）": ["E.precision.confirmed_derived"], "E の適合率（推定の辺）": ["E.precision.inferred"],
                 "P の再現率・適合率": ["P.recall", "P.precision"], "C の一致率": ["C"], "一致した辺の中での確信度の一致率": ["edge.confidence"]}
        unknown = next(k for k in rows if k.startswith("`unknown`"))
        self.assertEqual(rows.pop(unknown)[0], 0.0)  # 0 件（件数の基準。aggregate が unknown を不合格にする）
        self.assertEqual(set(names), set(rows))
        for label, keys in names.items():
            for k in keys:
                self.assertEqual(cmp.THRESHOLDS["main"][k], rows[label], k)

    def test_custom_thresholds_are_all_one(self):
        # 1.1 の表: N・E・P・名前・C・付随（確信度・辺のラベル・ノードのラベル）がすべて 1.0。キーが抜けていないこと
        self.assertTrue(all(v == (1.0, 1.0) for v in cmp.THRESHOLDS["custom"].values()))
        self.assertEqual(set(cmp.THRESHOLDS["custom"]), set(cmp.THRESHOLDS["main"]) | {"edge.label", "node.label"})


if __name__ == "__main__":
    unittest.main()
