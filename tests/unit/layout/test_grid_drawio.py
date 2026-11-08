"""配置と .drawio の出力のテスト（フェーズ 4 の手順 2）: 正解 IR を配置して、重なり・はみ出しが無く、XML の形が決まりどおり。"""

from __future__ import annotations

import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
import support  # noqa: E402,F401
from aws_iac_diagram.core import rules  # noqa: E402
from aws_iac_diagram.emit import drawio as emit_drawio  # noqa: E402
from aws_iac_diagram.layout import grid  # noqa: E402
from aws_iac_diagram.validate import drawio as check_drawio  # noqa: E402

EXPECTED = Path(__file__).resolve().parents[3] / "aws-iac-diagram-workspace" / "expected"
FILES = sorted(EXPECTED.glob("*.ir.json")) + sorted((EXPECTED / "public").glob("*.ir.json"))


class GridDrawioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = rules.default()
        cls.catalog = emit_drawio.load_catalog()
        cls.out = {}
        for f in FILES:
            ir = json.loads(f.read_text(encoding="utf-8"))
            cls.out[f.name] = (ir, emit_drawio.emit(ir, grid.place(ir["nodes"]), cls.rules, cls.catalog))

    def test_no_overlap_or_overflow(self):
        self.assertEqual(len(self.out), 17)
        for name, (_, xml) in self.out.items():
            d = check_drawio.parse(xml)
            self.assertEqual(check_drawio.check_overlap(d) + check_drawio.check_overflow(d), [], name)

    def test_same_input_same_bytes(self):
        for name, (ir, xml) in self.out.items():
            self.assertEqual(emit_drawio.emit(ir, grid.place(ir["nodes"]), self.rules, self.catalog), xml, name)

    def test_xml_shape(self):
        for name, (ir, xml) in self.out.items():
            root = ET.fromstring(xml).find("diagram/mxGraphModel/root")
            cells = root.findall("mxCell")
            self.assertEqual([c.get("id") for c in cells[:4]], ["0", "layer-background", "1", "layer-edges"], name)
            self.assertEqual(cells[4].get("id"), "background", name)
            self.assertNotIn("background=", xml.split("<root>")[0], name)
            for c in cells:
                if c.get("edge") == "1":
                    self.assertEqual(c.get("parent"), "layer-edges", name)
                    self.assertEqual(c.find("mxGeometry").findall("*"), [], name)  # waypoint を置かない
            seen = set()
            for c in cells:
                self.assertTrue(c.get("parent") is None or c.get("parent") in seen, f"{name}: 親が先に無い {c.get('id')}")
                seen.add(c.get("id"))

    def test_inferred_edges_are_dashed_and_have_a_legend(self):
        for name, (ir, xml) in self.out.items():
            cells = {c.get("id"): c for c in ET.fromstring(xml).iter("mxCell")}
            for e in ir["edges"]:
                self.assertEqual("dashed=1" in cells[e["id"]].get("style"), e["confidence"] == "inferred", name)
            self.assertEqual("legend" in cells, any(e["confidence"] == "inferred" for e in ir["edges"]), name)

    def test_integer_coordinates(self):
        for name, (_, xml) in self.out.items():
            for g in ET.fromstring(xml).iter("mxGeometry"):
                for k in ("x", "y", "width", "height"):
                    if g.get(k) is not None:
                        self.assertRegex(g.get(k), r"^-?\d+$", name)


if __name__ == "__main__":
    unittest.main()
