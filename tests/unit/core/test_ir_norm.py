"""core/ir_norm.py（出力の形 C5 と canonical 部）のテスト。手順 1 で validate_ir.py から移した（動きは同じ）。"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.ir import load
from support.paths import EXPECTED
import validate_ir as v  # noqa: E402
from aws_iac_diagram.core import ir_norm  # noqa: E402


class IrNormTest(unittest.TestCase):
    def test_validate_ir_uses_the_core_functions(self):
        self.assertIs(v.canonical_dump, ir_norm.canonical_dump)
        self.assertIs(v.canonical_part, ir_norm.canonical_part)

    def test_expected_irs_are_their_own_canonical_form(self):
        files = sorted(EXPECTED.glob("*.ir.json"))
        self.assertEqual(len(files), 5)
        for p in files:
            with self.subTest(p.name):
                self.assertEqual(p.read_text(encoding="utf-8"), ir_norm.canonical_dump(json.loads(p.read_text(encoding="utf-8"))))

    def test_lists_are_sorted_and_the_input_is_not_changed(self):
        ir = load()
        shuffled = copy.deepcopy(ir)
        shuffled["nodes"].reverse()
        shuffled["edges"].reverse()
        for n in shuffled["nodes"]:
            if "spans" in n:
                n["spans"].reverse()
        for src in shuffled["sources"].values():
            src["resources"].reverse()
            src["edges"].reverse()
            for r in src["resources"]:
                if "into" in r:
                    r["into"].reverse()
            for e in src["edges"]:
                e["rules"].reverse()
                e["evidence"].reverse()
        before = copy.deepcopy(shuffled)
        self.assertEqual(ir_norm.canonical_dump(shuffled), ir_norm.canonical_dump(ir))
        self.assertEqual(shuffled, before)  # 元は変えない
        self.assertEqual(ir_norm.sort_lists(shuffled), ir_norm.sort_lists(ir))
        self.assertTrue(any("spans" in n for n in ir["nodes"]))  # 空振りの防止

    def test_dump_shape(self):
        text = ir_norm.canonical_dump({"nodes": [], "edges": [], "b": "日本語", "a": 1})
        self.assertEqual(text, '{\n  "a": 1,\n  "b": "日本語",\n  "edges": [],\n  "nodes": []\n}\n')  # キーは辞書順、ensure_ascii なし、末尾の改行 1 つ

    def test_canonical_part_drops_notes_and_the_source_part(self):
        ir = load()
        part = ir_norm.canonical_part(ir)
        self.assertEqual(sorted(part), ["edges", "nodes"])
        self.assertFalse(any("note" in x for x in part["nodes"] + part["edges"]))
        self.assertTrue(any("note" in x for x in ir["nodes"] + ir["edges"]))  # 空振りの防止
        self.assertEqual(part, ir_norm.canonical_part(load("three-tier")))


if __name__ == "__main__":
    unittest.main()
