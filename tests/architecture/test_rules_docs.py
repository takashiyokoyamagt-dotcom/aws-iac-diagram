"""規則表の文書（docs/spec/rules/）とデータ（skills/aws-iac-diagram/data/rules/）が食い違わないことのテスト（フェーズ 3 の手順 1）。

文書の表は `aws-iac-diagram-workspace/tools/render_rules.py` がデータから作る生成物で、説明の文章は手で書く。
`--check` と同じ関数を呼び、生成部分がデータと一致すること、データか文書を壊すと失敗することを確かめる。
規則 ID は、データにあれば文書にもある（表に出る）こと。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import DATA, ROOT, TOOLS
from support.rules_data import copy_rules, edit
from support.tools import load_tool
from aws_iac_diagram.core import rules as rule_data  # noqa: E402

R = load_tool("render_rules")
DOCS = ROOT / "docs" / "spec" / "rules"


class RulesDocsTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name) / "日本語 パス"
        self.rules_dir = copy_rules(self.tmp)
        self.docs = self.tmp / "docs"
        shutil.copytree(DOCS, self.docs)

    def test_shipped_docs_equal_the_generated_tables(self):
        self.assertEqual(R.process(DATA / "rules", DOCS, write=False), [])

    def test_the_cli_check_passes_and_exits_0(self):
        res = subprocess.run([sys.executable, str(TOOLS / "render_rules.py"), "--check"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("OK", res.stdout)

    def test_the_documents_and_blocks_are_the_ones_the_tool_knows(self):
        self.assertEqual(sorted(p.name for p in DOCS.glob("*.md")), sorted(R.DOC_BLOCKS))
        blocks = [b for bs in R.DOC_BLOCKS.values() for b, _ in bs]
        self.assertEqual(len(blocks), len(set(blocks)))  # マーカーの名前は全体で一意
        self.assertGreaterEqual(len(blocks), 17)

    def test_every_rule_id_and_drawn_type_is_in_the_docs(self):
        r = rule_data.load()
        text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(DOCS.glob("*.md")))
        missing = sorted(i for i in (*r.rule_ids, *r.drawn_ids) if f"`{i}`" not in text)
        self.assertEqual(missing, [])

    def test_data_change_without_regenerating_is_found(self):
        edit(self.rules_dir, "types/merged-and-hidden.toml", 'reason = "クラウド上の実体が無い"', 'reason = "実体が無い"')
        problems = R.process(self.rules_dir, self.docs, write=False)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("types.md: 生成部分がデータ（data/rules/）と食い違う", problems[0])
        # --write で直り、もう一度 --check すると一致する
        self.assertEqual(R.process(self.rules_dir, self.docs, write=True), [])
        self.assertEqual(R.process(self.rules_dir, self.docs, write=False), [])
        self.assertIn("実体が無い", (self.docs / "types.md").read_text(encoding="utf-8"))

    def test_a_new_rule_row_must_appear_in_the_docs(self):
        text = (self.rules_dir / "types" / "merged-and-hidden.toml").read_text(encoding="utf-8")
        (self.rules_dir / "types" / "merged-and-hidden.toml").write_text(
            text + '\n[[type]]\nid = "H-NEW"\nclass = "hidden"\ntf = ["aws_new_thing"]\ncfn = []\napplies = "新しい型"\nreason = "テスト"\n',
            encoding="utf-8", newline="\n")
        self.assertTrue(R.process(self.rules_dir, self.docs, write=False))
        R.process(self.rules_dir, self.docs, write=True)
        self.assertIn("`H-NEW`", (self.docs / "types.md").read_text(encoding="utf-8"))
        self.assertEqual(R.process(self.rules_dir, self.docs, write=False), [])

    def test_hand_edit_of_a_generated_table_is_found_and_prose_is_kept(self):
        p = self.docs / "relations.md"
        text = p.read_text(encoding="utf-8")
        self.assertIn("`R-SG`", text)
        p.write_text(text.replace("`R-SG`", "`R-SGX`", 1), encoding="utf-8", newline="\n")
        self.assertIn("relations.md: 生成部分がデータ", R.process(self.rules_dir, self.docs, write=False)[0])
        # 手で書いた説明（生成部分の外）を直しても、生成の結果とは無関係
        p.write_text(text.replace("## 補足（判断の理由）", "## 補足（判断の理由。直した）"), encoding="utf-8", newline="\n")
        self.assertEqual(R.process(self.rules_dir, self.docs, write=False), [])
        R.process(self.rules_dir, self.docs, write=True)
        self.assertIn("直した", p.read_text(encoding="utf-8"))  # --write は説明を消さない

    def test_marker_problems_are_found(self):
        p = self.docs / "types.md"
        text = p.read_text(encoding="utf-8")
        cases = {
            "開始マーカーが無い": text.replace("<!-- rules-table: types-merged -->\n", "", 1),
            "終了マーカーが無い": text.replace("<!-- /rules-table -->\n", "", 1),
            "未知の名前": text.replace("types-merged", "types-nothing", 1),
            "並びが違う": text.replace("types-drawn", "types-tmp", 1).replace("types-merged", "types-drawn", 1).replace("types-tmp", "types-merged", 1),
        }
        for label, new in cases.items():
            with self.subTest(label):
                self.assertNotEqual(new, text, label)
                p.write_text(new, encoding="utf-8", newline="\n")
                problems = R.process(self.rules_dir, self.docs, write=False)
                self.assertTrue(problems, label)
                self.assertTrue(all(x.startswith(("types.md", "NG")) or "types.md" in x for x in problems), problems)
        p.write_text(text, encoding="utf-8", newline="\n")
        # 文書が欠ける・余る
        (self.docs / "edges.md").unlink()
        self.assertIn("edges.md: 文書が無い", R.process(self.rules_dir, self.docs, write=False))
        (self.docs / "extra.md").write_text("# x\n", encoding="utf-8")
        self.assertTrue(any("extra.md" in x for x in R.process(self.rules_dir, self.docs, write=False)))

    def test_every_column_has_a_description(self):
        # core/rules.py に列を足して COLUMN_DOC に書き忘れると、--check が KeyError で落ちる
        import unittest.mock as mock
        with mock.patch.dict(rule_data.TYPE_COMMON, {"newcol": ("str", False)}):
            with self.assertRaises(KeyError) as cm:
                R.process(self.rules_dir, self.docs, write=False)
            self.assertIn("newcol", str(cm.exception))
        columns = {(t, c) for t, spec in [("type", rule_data.TYPE_COMMON), ("relation", rule_data.RELATION),
                                           *rule_data.OTHER_TABLES.items(), *(("type", d) for d in rule_data.TYPE_BY_CLASS.values())]
                   for c in spec}
        self.assertEqual(sorted(columns - set(R.COLUMN_DOC)), [])
        self.assertEqual(sorted(set(R.COLUMN_DOC) - columns - {("type", "when"), ("relation", "when")}), [])  # 余った説明も残さない

    def test_a_broken_rules_dir_is_exit_2(self):
        (self.rules_dir / "relations.toml").unlink()
        res = subprocess.run([sys.executable, str(TOOLS / "render_rules.py"), "--check", "--rules-dir", str(self.rules_dir),
                              "--docs-dir", str(self.docs)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("relations.toml: 無い", res.stderr)

    def test_the_cli_reports_differences_with_exit_1_and_write_fixes_them(self):
        edit(self.rules_dir, "edges.toml", 'draw = "実線"', 'draw = "太い実線"')
        args = ["--rules-dir", str(self.rules_dir), "--docs-dir", str(self.docs)]
        res = subprocess.run([sys.executable, str(TOOLS / "render_rules.py"), "--check", *args], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("edges.md", res.stdout)
        res = subprocess.run([sys.executable, str(TOOLS / "render_rules.py"), "--write", *args], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("太い実線", (self.docs / "edges.md").read_text(encoding="utf-8"))
        res = subprocess.run([sys.executable, str(TOOLS / "render_rules.py"), *args], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_generated_files_use_lf_and_end_with_one_newline(self):
        for p in sorted(DOCS.glob("*.md")):
            data = p.read_bytes()
            self.assertNotIn(b"\r", data, p.name)
            self.assertTrue(data.endswith(b"\n") and not data.endswith(b"\n\n"), p.name)
        self.assertRegex((DOCS / "types.md").read_text(encoding="utf-8"), re.compile(r"<!-- rules-table: types-drawn -->"))


if __name__ == "__main__":
    unittest.main()
