"""規則表（data/rules/）が指すアイコンが、アイコンの辞書（data/icons/catalog.json）に実在し、使えることのテスト。

辞書は draw.io の Sidebar-AWS4.js から作り、`check_icons.py` が壊れたもの（broken）に印を付ける。規則表の `icon` は手で書くので、
名前の書き違い（vidanov の言う `dynamodb_table` のような実在しない名前）や、draw.io の更新で壊れたアイコンをここで捕まえる。
読み込み（core/rules.py）の検査には入れない（辞書が壊れても validate_ir.py は動かしたいので、実行時に辞書に依存させない）。
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import DATA
from aws_iac_diagram.core import paths, rules  # noqa: E402

# 辞書の id の形（kind:name）。規則表の文章（icon_note など）に書いた id も拾う
ICON_ID = re.compile(r"(?<![A-Za-z0-9_])((?:shape|resource_icon|group|plain_group|edge):[a-z0-9_]+)")


class RuleIconsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = {e["id"]: e for e in json.loads(paths.ICON_CATALOG.read_text(encoding="utf-8"))}
        cls.rules = rules.load()

    def problems(self, ids) -> list[str]:
        out = []
        for i in sorted(set(ids)):
            e = self.catalog.get(i)
            if e is None:
                out.append(f"{i}: 辞書に無い")
            elif e.get("broken"):
                out.append(f"{i}: broken（{e.get('broken_reason', '')}）")
            elif e.get("retired"):
                out.append(f"{i}: retired")
        return out

    def test_icon_column_resolves(self):
        ids = [i for r in self.rules.types for i in (r.get("icon") or ())]
        self.assertTrue(ids)
        bad = [i for i in ids if not ICON_ID.fullmatch(i)]
        self.assertEqual(bad, [], "icon の列は kind:name の形で書く")
        self.assertEqual(self.problems(ids), [])

    def test_ids_in_text_resolve(self):
        # icon の列のほか、注記などに書いた id も辞書に実在すること
        ids = [m for p in sorted((DATA / "rules").rglob("*.toml"))
               for m in ICON_ID.findall(p.read_text(encoding="utf-8"))]
        self.assertTrue(ids)
        self.assertEqual(self.problems(ids), [])

    def test_detects_missing_and_broken(self):
        # 検査そのものが働くこと（辞書に無い名前と broken を見分ける）
        # いまの辞書には broken が 0 件なので、broken と retired は作った項目で確かめる
        saved = self.catalog
        self.catalog = {**saved, "shape:x_broken": {"broken": True, "broken_reason": "solid"},
                        "shape:x_retired": {"retired": True}}
        try:
            probs = self.problems(["shape:dynamodb_table", "resource_icon:lambda", "shape:x_broken", "shape:x_retired"])
        finally:
            self.catalog = saved
        self.assertEqual(probs, ["shape:dynamodb_table: 辞書に無い", "shape:x_broken: broken（solid）",
                                 "shape:x_retired: retired"])


if __name__ == "__main__":
    unittest.main()
