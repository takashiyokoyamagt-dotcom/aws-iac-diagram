"""`.drawio` の見やすさの検査（CRITERIA の 2.1）のテスト。手で組んだ小さな XML で、正負の例を確かめる。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
import support  # noqa: E402,F401
from aws_iac_diagram.validate import drawio  # noqa: E402


def v(cid, x, y, w=40, h=40, parent="1", value="", style=""):
    return (f'<mxCell id="{cid}" value="{value}" style="{style}" vertex="1" parent="{parent}">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')


def e(cid, s, t, value=""):
    return f'<mxCell id="{cid}" value="{value}" edge="1" parent="1" source="{s}" target="{t}"><mxGeometry relative="1" as="geometry"/></mxCell>'


def doc(*cells):
    return ('<mxfile><diagram><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
            '<mxCell id="layer-background" parent="0"/>' + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>")


def kinds(*cells):
    return sorted(p.kind for p in drawio.check(doc(*cells)))


class CheckTest(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(kinds(v("a", 0, 0), v("b", 200, 0), e("e", "a", "b")), [])

    def test_overlap_and_touching(self):
        self.assertEqual(kinds(v("a", 0, 0), v("b", 20, 20)), ["overlap"])
        self.assertEqual(kinds(v("a", 0, 0), v("b", 40, 0)), [])

    def test_overlap_uses_absolute_coordinates(self):
        cells = [v("f", 100, 100, 100, 100), v("a", 10, 10, parent="f"), v("b", 120, 120)]
        self.assertEqual(kinds(*cells), ["overlap", "overlap"])  # a と b、枠 f と b

    def test_parent_and_child_are_not_an_overlap(self):
        self.assertEqual(kinds(v("f", 0, 0, 100, 100), v("a", 10, 10, parent="f")), [])

    def test_overflow(self):
        self.assertEqual(kinds(v("f", 0, 0, 50, 50), v("a", 30, 0, parent="f")), ["overflow"])

    def test_background_layer_is_ignored(self):
        self.assertEqual(kinds(v("bg", 0, 0, 500, 500, parent="layer-background"), v("a", 0, 0)), [])

    def test_pierce_only_when_all_four_routes_are_blocked(self):
        # 同じ行で真ん中を塞ぐ: 始点と終点の y が同じなので 4 通りとも一直線になり、貫通する
        self.assertEqual(kinds(v("a", 0, 0), v("b", 300, 0), v("x", 150, 0), e("e", "a", "b")), ["pierce"])
        # 斜めの位置なら、L 字のどれかが避けられる
        self.assertEqual(kinds(v("a", 0, 0), v("b", 300, 300), v("x", 280, 0, 60, 60), e("e", "a", "b")), [])

    def test_ancestors_and_container_descendants_are_not_pierced(self):
        f = v("f", 0, 0, 400, 100)
        self.assertEqual(kinds(f, v("a", 10, 10, parent="f"), v("b", 500, 10), e("e", "a", "b")), [])
        cells = [v("f", 0, 0, 100, 100), v("c", 30, 30, parent="f"), v("b", 300, 30), e("e", "f", "b")]
        self.assertEqual(kinds(*cells), [])

    def test_node_label_overlaps_icon_below(self):
        self.assertEqual(kinds(v("a", 0, 0, value="name"), v("b", 0, 45)), ["label"])
        self.assertEqual(kinds(v("a", 0, 0, value="name"), v("b", 0, 80)), [])

    def test_label_width_counts_full_width_characters(self):
        d = drawio.parse(doc(v("a", 0, 0, value="ああ"), v("b", 0, 100, value="ab")))
        self.assertEqual(drawio.node_label_rect(d.vertices["a"])[2] - drawio.node_label_rect(d.vertices["a"])[0], 24)
        self.assertAlmostEqual(drawio.node_label_rect(d.vertices["b"])[2] - drawio.node_label_rect(d.vertices["b"])[0], 14.4)

    def test_edge_label_collides_with_an_icon_on_every_route(self):
        cells = [v("a", 0, 0), v("b", 300, 0), e("e", "a", "b", value="HTTPS"), v("x", 140, -80, 40, 40, value="")]
        self.assertEqual(kinds(*cells), [])
        cells[-1] = v("x", 150, 26, 40, 40)  # 経路（y=20）には当たらないが、経路の中点のラベル（y=13〜27）には当たる
        self.assertEqual(kinds(*cells), ["label"])

    def test_routes_are_the_four_models(self):
        rs = drawio.routes((0, 0), (10, 20))
        self.assertEqual(rs[0], [(0, 0), (10, 0), (10, 20)])
        self.assertEqual(rs[3], [(0, 0), (0, 10), (10, 10), (10, 20)])

    def test_container_endpoint_is_nearest_side_midpoint(self):
        d = drawio.parse(doc(v("f", 0, 0, 100, 100), v("c", 10, 10, parent="f")))
        self.assertEqual(drawio.endpoint(d, "f", (500, 50)), (100, 50))


if __name__ == "__main__":
    unittest.main()
