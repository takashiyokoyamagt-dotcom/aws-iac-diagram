"""core/paths.py（SKILL の同梱ファイルの場所）のテスト。

- 定数がすべて実在するファイル／フォルダを指す（データを移したのに定数を直し忘れた、を失敗にする）。
- SKILL のフォルダを日本語・スペースを含む別の深さに置いても、定数が複製の中を指す（`parents[N]` の深さの誤りを見つける）。
- 要約表のフォルダの並べ方（v6 は v10 の前）と、複数のファイルにまたがる読み込み。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "aws-iac-diagram"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aws_iac_diagram.adapters.terraform.modules import summaries as MS  # noqa: E402
from aws_iac_diagram.core import paths  # noqa: E402


def constants() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for name, val in vars(paths).items():
        if name.startswith("_"):
            continue
        if isinstance(val, Path):
            out[name] = val
        elif isinstance(val, tuple) and val and all(isinstance(x, Path) for x in val):
            out.update({f"{name}[{i}]": x for i, x in enumerate(val)})
    return out


class PathsTest(unittest.TestCase):
    def test_skill_dir_is_this_skill(self):
        self.assertEqual(paths.SKILL_DIR, SKILL.resolve())
        self.assertTrue((paths.SKILL_DIR / "SKILL.md").is_file())

    def test_every_constant_exists(self):
        got = constants()
        self.assertGreaterEqual(len(got), 12)
        for name, p in got.items():
            with self.subTest(name):
                self.assertTrue(p.exists(), f"{name} = {p} が無い（データを移したときは core/paths.py を直す）")
                self.assertTrue(p.is_relative_to(paths.SKILL_DIR), name)
                self.assertTrue(p.is_dir() if name.endswith("_DIR") else p.is_file(), name)

    def test_data_layout(self):
        rel = {n: p.relative_to(paths.SKILL_DIR).as_posix() for n, p in constants().items()}
        self.assertEqual(rel["IR_SCHEMA"], "data/schemas/ir.schema.json")
        self.assertEqual(rel["IR_RAW_SCHEMA"], "data/schemas/ir-raw.schema.json")
        self.assertEqual(rel["ICON_CATALOG"], "data/icons/catalog.json")
        self.assertEqual(rel["MODULE_SUMMARIES_DIR"], "data/module-summaries")

    def test_constants_follow_a_copy_of_the_skill_at_another_depth(self):
        # SKILL のフォルダだけを、日本語・スペースを含む別の深さにコピーして、定数がコピーの中を指すことを別のプロセスで確かめる
        import shutil
        with tempfile.TemporaryDirectory() as t:
            copy = Path(t) / "日本語 パス" / "a" / "b" / "c" / "別の 名前"
            shutil.copytree(SKILL, copy, ignore=shutil.ignore_patterns("__pycache__"))
            code = ("import sys; sys.path.insert(0, sys.argv[1]);"
                    "from aws_iac_diagram.core import paths as p; import json;"
                    "print(json.dumps([str(p.SKILL_DIR), str(p.IR_SCHEMA), str(p.ICON_CATALOG), str(p.MODULE_SUMMARIES_DIR)]))")
            res = subprocess.run([sys.executable, "-c", code, str(copy / "scripts")], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(res.returncode, 0, res.stderr)
            import json
            skill_dir, schema, catalog, summaries = json.loads(res.stdout)
            self.assertEqual(Path(skill_dir).resolve(), copy.resolve())
            self.assertTrue(Path(schema).is_file() and Path(catalog).is_file() and Path(summaries).is_dir())
            for p in (schema, catalog, summaries):
                self.assertTrue(Path(p).resolve().is_relative_to(copy.resolve()), p)


class SummaryDirectoryTest(unittest.TestCase):
    """要約表のフォルダの読み方（summaries.load）。"""

    @staticmethod
    def table(source: str, major: int, marker: str = "x") -> str:
        return (f'# {source}\n\n<!-- module-summary source="{source}" majors="{major}" -->\n```hcl\n'
                f'# not-covered: {marker}\nvariable "a" {{}}\n```\n')

    def make(self, files: dict[str, str]) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name) / "ms"
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8", newline="\n")
        return root

    def test_files_are_read_in_a_fixed_natural_order(self):
        src = "terraform-aws-modules/vpc/aws"
        root = self.make({"terraform-aws-vpc/v10.md": self.table(src, 10), "terraform-aws-vpc/v6.md": self.table(src, 6),
                          "terraform-aws-vpc/v5.md": self.table(src, 5)})
        got = MS.load(root)[0][src]
        self.assertEqual([(s.majors, s.file) for s in got],
                         [((5,), "terraform-aws-vpc/v5.md"), ((6,), "terraform-aws-vpc/v6.md"),
                          ((10,), "terraform-aws-vpc/v10.md")])

    def test_a_directory_equals_the_same_text_in_one_file(self):
        src = "terraform-aws-modules/vpc/aws"
        root = self.make({"m/v5.md": self.table(src, 5), "m/v6.md": self.table(src, 6)})
        one = self.make({"all.md": self.table(src, 5) + "\n" + self.table(src, 6)})
        a = MS.load(root)[0][src]
        b = MS.load(one / "all.md")[0][src]
        self.assertEqual([(s.majors, s.text, s.uncovered) for s in a], [(s.majors, s.text, s.uncovered) for s in b])

    def test_missing_or_empty_directory_reads_as_empty(self):
        root = self.make({"readme.txt": "not markdown"})
        self.assertEqual(MS.load(root), ({}, ()))
        self.assertEqual(MS.load(root / "nope"), ({}, ()))

    def test_iam_only_list_is_read_from_any_file(self):
        root = self.make({"iam-only-sources.md": "<!-- iam-only-sources -->\n```text\nterraform-aws-modules/iam/aws\n```\n"})
        self.assertEqual(MS.load(root), ({}, ("terraform-aws-modules/iam/aws",)))
        self.assertTrue(MS.iam_only("terraform-aws-modules/iam/aws//modules/x", root))

    def test_real_tables_are_one_file_per_module_and_major(self):
        for key, items in MS.load()[0].items():
            for s in items:
                with self.subTest(key):
                    mod = key.split("/")[1]  # terraform-aws-modules/<name>/aws
                    self.assertEqual(s.file, f"terraform-aws-{mod}/v{s.majors[0]}.md")
                    self.assertEqual(len(s.majors), 1)


if __name__ == "__main__":
    unittest.main()
