"""B2 のビューと分割、coverage.md のテスト（フェーズ 4 の手順 4）。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
import support  # noqa: E402,F401
from aws_iac_diagram.emit import coverage  # noqa: E402
from aws_iac_diagram.layout import views  # noqa: E402

EXPECTED = Path(__file__).resolve().parents[3] / "aws-iac-diagram-workspace" / "expected"
FILES = sorted(EXPECTED.glob("*.ir.json")) + sorted((EXPECTED / "public").glob("*.ir.json"))


def node(i, parent=None, category="resource", type_="lambda_function"):
    return {"id": i, "type": type_, "category": category, "name": i, "label": i, "parent": parent}


def edge(a, b, kind="request"):
    return {"id": f"{a}->{b}", "from": a, "to": b, "kind": kind, "confidence": "confirmed"}


class ViewsTest(unittest.TestCase):
    def test_contents_for_every_expected_ir(self):
        for f in FILES:
            ir = json.loads(f.read_text(encoding="utf-8"))
            got = {v.name: v for v in views.build(ir)}
            self.assertEqual(sorted(got), ["detail", "network", "overview"], f.name)
            self.assertEqual({n["id"] for n in got["overview"].nodes}, {n["id"] for n in ir["nodes"]}, f.name)
            self.assertEqual({e["id"] for e in got["overview"].edges}, {e["id"] for e in ir["edges"]}, f.name)
            groups = {n["id"] for n in ir["nodes"] if n["category"] == "group"}
            self.assertLessEqual(groups, {n["id"] for n in got["network"].nodes}, f.name)
            ids = {n["id"] for n in ir["nodes"]}
            for v in got.values():
                have = {n["id"] for n in v.nodes}
                self.assertLessEqual(have, ids, f.name)
                for e in v.edges:
                    self.assertLessEqual({e["from"], e["to"]}, have, f.name)
                for n in v.nodes:
                    self.assertTrue(n["parent"] is None or n["parent"] in have, f.name)

    def test_detail_hides_route_edges(self):
        ir = {"nodes": [node("a"), node("b")], "edges": [edge("a", "b", "route")]}
        detail = next(v for v in views.build(ir) if v.name == "detail")
        self.assertEqual(detail.edges, [])

    def test_split_keeps_every_edge_and_the_limit(self):
        nodes = [node("v", category="group", type_="vpc"), node("w", category="group", type_="vpc")]
        nodes += [node(f"a{i:02d}", "v") for i in range(30)] + [node(f"b{i:02d}", "w") for i in range(30)]
        edges = [edge(f"a{i:02d}", f"b{i:02d}") for i in range(5)]
        sheets = views.split(views.View("overview", nodes, edges))
        self.assertGreater(len(sheets), 1)
        self.assertEqual(sorted(e["id"] for s in sheets for e in s.edges), sorted(e["id"] for e in edges))
        for s in sheets:
            self.assertLessEqual(views.icon_count(s.nodes), views.MAX_ICONS)
            have = {n["id"] for n in s.nodes}
            for e in s.edges:
                self.assertLessEqual({e["from"], e["to"]}, have)

    def test_split_by_root(self):
        v1, v2 = node("v", category="group", type_="vpc"), node("w", category="group", type_="vpc")
        nodes = [v1, v2, node("a", "v"), node("b", "w"), node("c")]
        sheets = views.split_by_root(views.View("overview", nodes, [edge("c", "a")]))
        self.assertEqual([s.name for s in sheets], ["overview-1", "overview-2", "overview-3"])
        self.assertIn("v", {n["id"] for n in sheets[2].nodes})  # c の辺の相手の枠を複製する
        self.assertEqual(len(views.split_by_root(views.View("x", [v1, node("a", "v")], []))), 1)


class CoverageTest(unittest.TestCase):
    def test_matches_sources(self):
        for f in FILES:
            ir = json.loads(f.read_text(encoding="utf-8"))
            md = coverage.render(ir)
            for src in ir["sources"].values():
                for r in src.get("resources", []):
                    self.assertIn(f"| {r['address'].replace('|', chr(92) + '|')} |", md, f.name)
            self.assertTrue(md.endswith("\n") and not md.endswith("\n\n"))


if __name__ == "__main__":
    unittest.main()
