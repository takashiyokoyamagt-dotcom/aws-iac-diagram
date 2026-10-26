"""core の import の決まりのテスト（フェーズ 3 の手順 1。docs/architecture.md の層の表）。

`core/` は、標準ライブラリ（`tomllib` を含む）と core 自身のモジュールだけを import する（サードパーティ・ほかの層・入口は不可）。
`tests/architecture/test_dependency_direction.py` は「層どうしの向き」を見るが、ここは core が**サードパーティにも**頼らないことを見る
（PEP 723 の依存を持たない入口 `doctor.py` が `core` を import できる、規則表の読み込みが追加の依存なしで動く、の前提）。
あわせて、手順 1 で足した `core/rules.py`・`core/ir_norm.py`・`core/module_sources.py` が存在し、この検査の対象に入っていること。
"""
from __future__ import annotations

import ast
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.arch_layers import PACKAGE
from support.paths import SCRIPTS

STDLIB = set(sys.stdlib_module_names)


def violations_in_core(core: Path) -> list[str]:
    """core の各ファイルの import のうち、標準ライブラリでも core 自身でもないもの。"""
    problems: list[str] = []
    for path in sorted(core.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    problems.append(f"{path.name}:{node.lineno}: 相対 import（core の中も絶対名で書く）")
                    continue
                mod = node.module or ""
                if mod == PACKAGE:  # `from aws_iac_diagram import x` は core 以外の層の可能性がある
                    problems.append(f"{path.name}:{node.lineno}: from {PACKAGE} import …（core.<名前> と書く）")
                    continue
                names = [mod]
                if mod == f"{PACKAGE}.core":
                    continue
            for n in names:
                top = n.split(".")[0]
                if top == PACKAGE:
                    if not (n == f"{PACKAGE}.core" or n.startswith(f"{PACKAGE}.core.")):
                        problems.append(f"{path.name}:{node.lineno}: core が {n} を import している（core は core 以外の層を読めない）")
                elif top not in STDLIB:
                    problems.append(f"{path.name}:{node.lineno}: core が標準ライブラリでない {n} を import している")
    return problems


class CoreIsolationTest(unittest.TestCase):
    CORE = SCRIPTS / PACKAGE / "core"

    def test_real_core_imports_only_the_stdlib_and_core(self):
        self.assertEqual(violations_in_core(self.CORE), [])

    def test_the_new_core_modules_are_inside_the_check(self):
        names = {p.stem for p in self.CORE.glob("*.py")}
        self.assertTrue({"rules", "ir_norm", "module_sources", "paths", "diagnostics", "ir_raw"} <= names, names)
        text = (self.CORE / "rules.py").read_text(encoding="utf-8")
        self.assertIn("import tomllib", text)  # 規則表は標準ライブラリの tomllib だけで読む（PyYAML などを使わない）

    def test_mutations_are_found(self):
        cases = {
            "import yaml": "標準ライブラリでない yaml",
            "import jsonschema": "標準ライブラリでない jsonschema",
            "from aws_iac_diagram.adapters.terraform import build": "core 以外の層",
            "from aws_iac_diagram.validate import x": "core 以外の層",
            "from aws_iac_diagram import adapters": "from aws_iac_diagram import",
            "from . import paths": "相対 import",
            "import hcl2": "標準ライブラリでない hcl2",
        }
        for line, want in cases.items():
            with self.subTest(line), tempfile.TemporaryDirectory() as t:
                core = Path(t) / "core"
                shutil.copytree(self.CORE, core, ignore=shutil.ignore_patterns("__pycache__"))
                f = core / "rules.py"
                f.write_text(f.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8", newline="\n")
                problems = violations_in_core(core)
                self.assertTrue(any(want in p and p.startswith("rules.py:") for p in problems), (line, problems))
        # 許すもの: 標準ライブラリ（tomllib・fnmatch）と core 自身
        with tempfile.TemporaryDirectory() as t:
            core = Path(t) / "core"
            shutil.copytree(self.CORE, core, ignore=shutil.ignore_patterns("__pycache__"))
            f = core / "ir_norm.py"
            f.write_text(f.read_text(encoding="utf-8") + "\nimport tomllib, fnmatch\nfrom aws_iac_diagram.core import paths\n", encoding="utf-8", newline="\n")
            self.assertEqual(violations_in_core(core), [])


if __name__ == "__main__":
    unittest.main()
