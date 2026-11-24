"""B1 の候補選び（フェーズ 4 の手順 3）: 候補の名前が決まっていて、最小のスコアを選び、同点は名前の辞書順。"""

from __future__ import annotations

import json
import sys
import unittest
from collections import Counter
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
import support  # noqa: E402,F401
from aws_iac_diagram.core import rules  # noqa: E402
from aws_iac_diagram.emit import drawio as emit_drawio  # noqa: E402
from aws_iac_diagram.layout import search, views  # noqa: E402
from aws_iac_diagram.validate import drawio as check_drawio  # noqa: E402

EXPECTED = Path(__file__).resolve().parents[3] / "aws-iac-diagram-workspace" / "expected"
FILES = sorted(EXPECTED.glob("*.ir.json")) + sorted((EXPECTED / "public").glob("*.ir.json"))
NODE = {"id": "a", "type": "lambda_function", "category": "resource", "name": "a", "label": "a", "parent": None}


class SearchTest(unittest.TestCase):
    def test_tie_goes_to_the_first_name(self):
        name, _, score = search.best([NODE], [], lambda layout: 7)
        self.assertEqual((name, score), (sorted(search.candidates())[0], 7))

    def test_lowest_score_wins(self):
        nodes = [NODE, {**NODE, "id": "b", "name": "b", "label": "b"}]
        widths = {search.place(nodes, c).width for c in search.candidates().values()}
        self.assertEqual(search.best(nodes, [], lambda layout: -layout.width)[1].width, max(widths))

    def test_remaining_problems_do_not_grow(self):
        """正解 IR の 17 入力のすべてのビュー（diagram.py と同じ分け方）で、見やすさの問題が 0 件。"""
        r, catalog, total = rules.default(), emit_drawio.load_catalog(), Counter()
        for f in FILES:
            ir = json.loads(f.read_text(encoding="utf-8"))
            for v in views.build(ir):
                sub = {"name": ir["name"], "nodes": v.nodes, "edges": v.edges}
                _, layout, _ = search.best(v.nodes, v.edges, lambda c: check_drawio.score(emit_drawio.emit(sub, c, r, catalog)))
                total.update(p.kind for p in check_drawio.check(emit_drawio.emit(sub, layout, r, catalog)))
        self.assertEqual(dict(total), {})


if __name__ == "__main__":
    unittest.main()
