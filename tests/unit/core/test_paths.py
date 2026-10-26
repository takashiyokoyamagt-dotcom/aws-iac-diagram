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

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import SKILL
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

    def test_iam_only_list_is_read_from_its_file(self):
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

    # --- 読むファイルは名前で決まる（レビュー対応）

    def test_only_exact_names_are_read(self):
        src = "terraform-aws-modules/vpc/aws"
        marker = self.table(src, 6)
        iam = "<!-- iam-only-sources -->\n```text\nterraform-aws-modules/iam/aws\n```\n"
        stray = {"NOTICE.md": marker + iam, "terraform-aws-vpc/NOTICE.md": marker, "terraform-aws-vpc/V6.md": marker,
                 "terraform-aws-vpc/v6.MD": marker, "terraform-aws-vpc/v1\u00b22.md": marker, "terraform-aws-vpc/v6.md.bak": marker,
                 "terraform-aws-vpc/notes.md": marker, "terraform-aws-vpc/deep/v6.md": marker, "v6.md": marker,
                 "x/v6.md": self.table("terraform-aws-modules/x/aws", 6)}
        root = self.make(stray)
        got = MS.load(root)
        self.assertEqual(sorted(got[0]), ["terraform-aws-modules/x/aws"])  # x/v6.md だけが読まれる
        self.assertEqual(got[1], ())  # NOTICE.md の中の iam-only は読まれない
        read = [rel for _, rel, _ in MS._listing(root)[0]]
        self.assertEqual(read, ["x/v6.md"])

    def test_stray_notice_in_the_real_directory_is_ignored(self):
        # 本物のフォルダに NOTICE.md がある。マーカーを書いても読まれない
        self.assertTrue((MS.SUMMARY_DIR / "NOTICE.md").is_file())
        import shutil
        root = self.make({})
        shutil.copytree(MS.SUMMARY_DIR, root, dirs_exist_ok=True)
        before = MS.load(root)
        extra = self.table("terraform-aws-modules/zzz/aws", 1) + "<!-- iam-only-sources -->\n```text\nzzz\n```\n"
        (root / "NOTICE.md").write_text(extra, encoding="utf-8", newline="\n")
        MS._CACHE.pop(str(root), None)
        after = MS.load(root)
        self.assertEqual(after, before)
        self.assertEqual(MS.problems(root), [])  # NOTICE.md は「読まれない .md」の誤りに数えない

    def test_order_does_not_depend_on_directory_listing_order(self):
        from unittest import mock
        src = "terraform-aws-modules/vpc/aws"
        root = self.make({"terraform-aws-vpc/v10.md": self.table(src, 10), "terraform-aws-vpc/v6.md": self.table(src, 6),
                          "terraform-aws-alb/v10.md": self.table("terraform-aws-modules/alb/aws", 10),
                          "iam-only-sources.md": "<!-- iam-only-sources -->\n```text\nterraform-aws-modules/iam/aws\n```\n"})
        want = [rel for _, rel, _ in MS._listing(root)[0]]
        self.assertEqual(want, ["iam-only-sources.md", "terraform-aws-alb/v10.md", "terraform-aws-vpc/v6.md",
                                "terraform-aws-vpc/v10.md"])
        real = Path.iterdir
        for name, fn in (("reversed", lambda self_: iter(reversed(list(real(self_))))),
                         ("shuffled", lambda self_: iter(sorted(real(self_), key=lambda p: hash(p.name) % 7)))):
            with self.subTest(name), mock.patch.object(Path, "iterdir", fn):
                self.assertEqual([rel for _, rel, _ in MS._listing(root)[0]], want)

    def test_zero_padded_names_do_not_raise_and_are_ordered_by_path(self):
        src = "terraform-aws-modules/vpc/aws"
        root = self.make({"terraform-aws-vpc/v06.md": self.table(src, 6), "terraform-aws-vpc/v6.md": self.table(src, 6),
                          "terraform-aws-vpc/v" + "9" * 100 + ".md": self.table(src, 6)})
        self.assertIsNone(MS.TABLE_FILE.fullmatch("v" + "9" * 5000 + ".md"))  # int() の桁数の上限に当たる名前も読まない
        read = [rel for _, rel, _ in MS._listing(root)[0]]
        self.assertEqual(read, ["terraform-aws-vpc/v06.md", "terraform-aws-vpc/v6.md"])  # (major, パス) の順。100 桁の名前は読まない
        self.assertTrue(any("正規でない名前" in p and "v06.md" in p for p in MS.problems(root)))

    # --- problems()（置き方の誤り）

    def test_shipped_tables_have_no_problems(self):
        self.assertEqual(MS.problems(), [])

    def test_known_modules_equal_the_shipped_top_level_modules(self):
        tops = {k for k in MS.load()[0] if "//" not in k}
        self.assertEqual(set(MS.KNOWN_MODULES), tops)

    def test_problems_are_reported(self):
        src = "terraform-aws-modules/vpc/aws"
        cases = {
            "名前の綴り": ({"terraform-aws-vpc/V6.md": self.table(src, 6)}, "ローダーが読まない"),
            "深さ": ({"terraform-aws-vpc/sub/v6.md": self.table(src, 6)}, "ローダーが読まない"),
            "空のファイル": ({"terraform-aws-vpc/v6.md": ""}, "要約表（<!-- module-summary … -->）が 1 つも無い"),
            "コードブロックの無いマーカー": ({"terraform-aws-vpc/v6.md": f'<!-- module-summary source="{src}" majors="6" -->\n'},
                                  "コードブロックが無い"),
            "ファイル名と majors": ({"terraform-aws-vpc/v6.md": self.table(src, 7)}, "ファイル名の major 6 と合わない"),
            "フォルダ名と source": ({"terraform-aws-alb/v6.md": self.table(src, 6)}, "フォルダ terraform-aws-vpc に置く"),
            "iam の一覧が空": ({"iam-only-sources.md": "# x\n"}, "source が 1 つも無い"),
        }
        for name, (files, want) in cases.items():
            with self.subTest(name):
                got = MS.problems(self.make(files))
                self.assertTrue(any(want in g for g in got), got)
        dup = self.make({"terraform-aws-vpc/v6.md": self.table(src, 6), "terraform-aws-vpc/v06.md": self.table(src, 6)})
        self.assertTrue(any("複数ある" in g for g in MS.problems(dup)), MS.problems(dup))
        self.assertEqual(MS.problems(self.make({"terraform-aws-vpc/v6.md": self.table(src, 6)})), [])
        self.assertEqual(MS.problems(Path("nope-does-not-exist")), [])  # 無いフォルダは調べない（欠けは doctor の一覧）


if __name__ == "__main__":
    unittest.main()
