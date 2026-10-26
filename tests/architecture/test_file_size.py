"""1ファイルの行数のテスト（PLAN の 1.4 の 4）。

800 行を超えたら注意を印字するだけ、1,500 行を超えたら失敗。超えているファイルは、日付と理由を付けた EXEMPT
（support/arch_size.py）に書く。EXEMPT は増やさない（行数の上限を超えて増えたら失敗）、1,500 行以内に減ったら、
免除を消さないと失敗する。一時フォルダにコピーした構成に、わざと長いファイルを入れて、検査が失敗することも確かめる。
テストのファイルの行数は tests/architecture/test_test_layout.py。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.arch_layers import PACKAGE
from support.arch_size import EXEMPT, MAX_LINES, WARN_LINES, violations_in_size
from support.paths import SCRIPTS


class FileSizeTest(unittest.TestCase):
    def test_real_tree(self):
        warn: list[str] = []
        problems = violations_in_size(SCRIPTS, warn=warn)
        for w in warn:
            print(f"\n[note] {w}", file=sys.stderr)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_no_exemptions_remain(self):
        # R2 で空にした。免除を足すなら、この検査を理由付きで直す
        self.assertEqual(EXEMPT, {})

    def test_exemptions_are_dated_and_justified(self):
        for rel, ex in EXEMPT.items():
            self.assertRegex(ex["since"], r"^\d{4}-\d\d-\d\d$", rel)
            self.assertGreater(ex["ceiling"], MAX_LINES, rel)
            self.assertTrue(ex["reason"].strip(), rel)
            self.assertRegex(ex["remove_in"], r"^R\d$", rel)
            self.assertTrue((SCRIPTS / rel).is_file(), rel)

    def make(self, lines: int) -> tuple[Path, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        scripts = Path(tmp.name) / "scripts"
        (scripts / PACKAGE / "core").mkdir(parents=True)
        f = scripts / PACKAGE / "core" / "big.py"
        f.write_text("x = 1\n" * lines, encoding="utf-8", newline="\n")
        return scripts, f

    def test_mutation_long_file_fails(self):
        scripts, _ = self.make(MAX_LINES + 1)
        problems = violations_in_size(scripts, exempt={})
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("aws_iac_diagram/core/big.py", problems[0])

    def test_boundary_and_warning(self):
        scripts, _ = self.make(MAX_LINES)
        self.assertEqual(violations_in_size(scripts, exempt={}), [])
        warn: list[str] = []
        scripts, _ = self.make(WARN_LINES + 1)
        self.assertEqual(violations_in_size(scripts, exempt={}, warn=warn), [])
        self.assertEqual(len(warn), 1)
        scripts, _ = self.make(WARN_LINES)
        warn = []
        violations_in_size(scripts, exempt={}, warn=warn)
        self.assertEqual(warn, [])

    def test_exemption_must_be_removed_when_file_shrinks(self):
        scripts, _ = self.make(MAX_LINES - 10)
        ex = {"aws_iac_diagram/core/big.py": {"since": "2026-10-26", "ceiling": 1600, "remove_in": "R2", "reason": "x"}}
        problems = violations_in_size(scripts, exempt=ex)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("免除を消す", problems[0])

    def test_exempt_file_cannot_grow_past_its_ceiling(self):
        scripts, _ = self.make(1601)
        ex = {"aws_iac_diagram/core/big.py": {"since": "2026-10-26", "ceiling": 1600, "remove_in": "R2", "reason": "x"}}
        problems = violations_in_size(scripts, exempt=ex)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("超えて増えた", problems[0])
        scripts, _ = self.make(1600)
        self.assertEqual(violations_in_size(scripts, exempt=ex), [])

    def test_stale_or_malformed_exemption_fails(self):
        scripts, _ = self.make(10)
        self.assertTrue(any("存在しない" in p for p in violations_in_size(
            scripts, exempt={"nope.py": {"since": "2026-10-26", "ceiling": 2000, "remove_in": "R2", "reason": "x"}})))
        self.assertTrue(any("since" in p for p in violations_in_size(
            scripts, exempt={"aws_iac_diagram/core/big.py": {"ceiling": 2000}})))


if __name__ == "__main__":
    unittest.main()
