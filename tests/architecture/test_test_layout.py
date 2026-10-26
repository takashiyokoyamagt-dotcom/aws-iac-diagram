"""tests/ 自体の置き場の決まりのテスト（フェーズ 2b の R5。docs/architecture.md の「テストの置き場」）。

テストを分けると、「どれかが discover に見つけられずに黙って走らない」「フォルダの名前が標準ライブラリや入口のスクリプトを
隠す」「同じ道具があちこちに写される」が起きやすい。それを次の決まりで防ぐ。

1. `test_*.py` は `unit/`・`integration/`・`golden/`・`architecture/` のどれかの下にある。そこまでのフォルダのすべてに
   `__init__.py` がある（`unittest discover -s tests` は `__init__.py` の無いフォルダを見ない）。
2. `support/`（共有の道具）にはテストを置かない。
3. tests/ の下のフォルダの名前と、フォルダの直下のテストでない `.py` の名前（`__init__.py` を除く）は、標準ライブラリのモジュール・
   インストール済みのパッケージ（`yaml`・`jsonschema`・`hcl2` など）・`scripts/` や `tools/` の最上位の名前と同じにしない
   （`python tests/…/test_x.py` や `discover -s tests/unit` で動かすと、そのフォルダが import の先頭に来て `import platform`・
   `import yaml`・`import doctor` を隠す。`unit/core/json.py` のような補助のファイルも同じ）。
   例外は `golden/`（tools/golden.py と同じ名前。PLAN の置き場の名前。テストは support.tools.load_tool で別名で読み、
   `import golden` と書かない）。
4. テストのファイルは、先頭で tests/ を sys.path に入れる同じ 2 行を持つ（直接実行と `python -m unittest tests.…` のため）。
5. tests/ の下の `.py` は 1,500 行以下（800 行を超えたら注意を印字）。
6. 同じ名前で同じ中身の関数が、複数のファイルにない（道具は support/ に 1 つだけ置く）。
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.arch_size import MAX_LINES, violations_in_size  # noqa: E402
from support.paths import SCRIPTS, TOOLS  # noqa: E402

TESTS = Path(__file__).resolve().parent.parent
AREAS = ("unit", "integration", "golden", "architecture")
BOOTSTRAP = ("# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）\n"
             'sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))')
# フォルダの名前が、入口や道具の名前と同じでもよいもの（理由）
SHADOW_ALLOW = {
    "golden": "PLAN の置き場の名前。tools/golden.py は support.tools.load_tool で別名（golden_tool）で読む",
}


def py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_files(root: Path = TESTS) -> list[Path]:
    return [p for p in py_files(root) if p.name.startswith("test_")]


def directories(root: Path = TESTS) -> list[Path]:
    return sorted(d for d in root.rglob("*") if d.is_dir() and "__pycache__" not in d.parts)


def top_level_names() -> set[str]:
    """scripts/ と tools/ の直下にある、import の最上位の名前（モジュールとパッケージ）。"""
    names: set[str] = set()
    for base in (SCRIPTS, TOOLS):
        for p in base.iterdir():
            if p.suffix == ".py":
                names.add(p.stem)
            elif p.is_dir() and p.name != "__pycache__":
                names.add(p.name)
    return names


# 開発用の環境の依存（pyproject.toml）の最上位の名前。環境に入っていなくても、隠してはいけない名前として数える
THIRD_PARTY_FLOOR = {"PIL", "hcl2", "yaml", "jsonschema", "lark", "cfnlint", "defusedxml", "moto"}


def third_party_names() -> set[str]:
    """インストール済みの配布物（依存の依存も）が持ち込む import の最上位の名前。"""
    return set(importlib.metadata.packages_distributions()) | THIRD_PARTY_FLOOR


def violations_in_layout(root: Path, shadow: set[str]) -> list[str]:
    problems: list[str] = []
    for f in test_files(root):
        rel = f.relative_to(root)
        if len(rel.parts) < 2 or rel.parts[0] not in AREAS:
            problems.append(f"{rel.as_posix()}: unit/・integration/・golden/・architecture/ のどれかの下に置く")
            continue
        d = f.parent
        while d != root:
            if not (d / "__init__.py").is_file():
                problems.append(f"{d.relative_to(root).as_posix()}/: __init__.py が無い（discover が見つけない）")
            d = d.parent
    for d in [root, *directories(root)]:
        for p in sorted(d.iterdir()):
            if p.name.startswith(("test_", "__")):
                continue
            rel = p.relative_to(root).as_posix()
            if p.is_dir() and p.name in shadow and p.name not in SHADOW_ALLOW:
                problems.append(f"{rel}/: フォルダの名前 {p.name} が標準ライブラリ・インストール済みのパッケージ・scripts/・tools/ の名前と同じ（import を隠す）")
            elif p.is_file() and p.suffix == ".py" and p.stem in shadow and p.stem not in SHADOW_ALLOW:
                problems.append(f"{rel}: モジュールの名前 {p.stem} が標準ライブラリ・インストール済みのパッケージ・scripts/・tools/ の名前と同じ（import を隠す）")
    support = root / "support"
    if support.is_dir():
        problems += [f"support/ にテスト: {p.relative_to(root).as_posix()}" for p in test_files(support)]
    return problems


def module_functions(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: hashlib.sha1(ast.dump(n).encode()).hexdigest()
            for n in tree.body if isinstance(n, ast.FunctionDef)}


def copied_functions(root: Path) -> dict[str, list[str]]:
    """同じ名前・同じ中身のモジュール直下の関数が、2 つ以上のファイルにあるもの（名前 → ファイル）。"""
    seen: dict[tuple[str, str], list[str]] = defaultdict(list)
    for f in py_files(root):
        for name, digest in module_functions(f).items():
            seen[(name, digest)].append(f.relative_to(root).as_posix())
    return {k[0]: v for k, v in seen.items() if len(v) > 1}


class TestLayoutTest(unittest.TestCase):
    def test_real_tree(self):
        shadow = set(sys.stdlib_module_names) | third_party_names() | top_level_names() | {"tests"}
        problems = violations_in_layout(TESTS, shadow)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_checks_see_something(self):
        # 空振りの防止: 実際のファイルとフォルダを見つけている
        self.assertGreaterEqual(len(test_files()), 30)
        self.assertTrue({"unit", "integration", "golden", "architecture", "support"} <= {d.name for d in directories()})
        names = top_level_names()
        self.assertTrue({"doctor", "validate_ir", "adapt_tf", "aws_iac_diagram", "maintenance", "golden"} <= names)
        self.assertIn("platform", sys.stdlib_module_names)
        self.assertTrue({"PIL", "hcl2", "yaml", "jsonschema", "lark", "cfnlint"} <= third_party_names())

    def test_mutations_are_found(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for rel in ("unit/a", "unit/platform", "unit/yaml", "unit/core", "support", "stray"):
                (root / rel).mkdir(parents=True)
            (root / "unit" / "__init__.py").write_text("", encoding="utf-8")
            (root / "unit" / "a" / "test_x.py").write_text("", encoding="utf-8")        # a/ に __init__.py が無い
            (root / "unit" / "platform" / "__init__.py").write_text("", encoding="utf-8")
            (root / "unit" / "platform" / "test_y.py").write_text("", encoding="utf-8")  # 標準ライブラリを隠す名前
            (root / "unit" / "yaml" / "__init__.py").write_text("", encoding="utf-8")    # インストール済みのパッケージを隠す名前
            (root / "unit" / "core" / "__init__.py").write_text("", encoding="utf-8")
            (root / "unit" / "core" / "json.py").write_text("", encoding="utf-8")        # 補助のファイルが標準ライブラリを隠す
            (root / "unit" / "core" / "hcl2.py").write_text("", encoding="utf-8")        # 補助のファイルがインストール済みのパッケージを隠す
            (root / "support" / "test_z.py").write_text("", encoding="utf-8")            # support/ にテスト
            (root / "stray" / "test_w.py").write_text("", encoding="utf-8")              # 置き場の外
            problems = violations_in_layout(root, set(sys.stdlib_module_names) | third_party_names())
            text = "\n".join(problems)
            for expect in ("unit/a/: __init__.py が無い", "フォルダの名前 platform", "フォルダの名前 yaml",
                           "モジュールの名前 json", "モジュールの名前 hcl2", "support/ にテスト", "stray/test_w.py"):
                self.assertIn(expect, text)
            self.assertEqual(len(problems), 8, problems)  # 上の 7 つ + support/test_z.py の置き場。unit/core/ のフォルダ自体などは咎めない

    def test_every_test_file_bootstraps_the_tests_directory(self):
        for f in test_files():
            with self.subTest(f.relative_to(TESTS).as_posix()):
                self.assertIn(BOOTSTRAP, f.read_text(encoding="utf-8").replace("\r\n", "\n"))

    def test_no_test_imports_golden_by_name(self):
        # tests/golden/ のパッケージと tools/golden.py は同じ名前。import golden は前者を読んでしまう
        offenders = []
        for f in py_files(TESTS):
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Import):
                    mods = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.level == 0:
                    mods = [n.module or ""]
                else:
                    continue
                if "golden" in [m.split(".")[0] for m in mods]:
                    offenders.append(f"{f.relative_to(TESTS).as_posix()}:{n.lineno}")
        self.assertEqual(offenders, [], "tools/golden.py は support.tools.load_tool(\"golden\", alias=\"golden_tool\") で読む")

    def test_file_sizes(self):
        warn: list[str] = []
        problems = violations_in_size(TESTS, exempt={}, warn=warn)
        for w in warn:
            print(f"\n[note] tests/{w}", file=sys.stderr)
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertLessEqual(max(len(p.read_text(encoding="utf-8").splitlines()) for p in py_files(TESTS)), MAX_LINES)

    def test_no_helper_is_copied_between_files(self):
        self.assertEqual(copied_functions(TESTS), {}, "同じ関数が複数のファイルにある。support/ に 1 つだけ置く")
        with tempfile.TemporaryDirectory() as t:  # 空振りの防止: 写しを見つける。名前が同じでも中身が違えば写しではない
            root = Path(t)
            (root / "a.py").write_text("def f(x):\n    return x\n\n\ndef g():\n    return 1\n", encoding="utf-8")
            (root / "b.py").write_text("def f(x):\n    return x\n\n\ndef g():\n    return 2\n", encoding="utf-8")
            self.assertEqual(copied_functions(root), {"f": ["a.py", "b.py"]})


if __name__ == "__main__":
    unittest.main()
