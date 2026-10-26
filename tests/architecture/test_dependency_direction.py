"""依存の向きのテスト（PLAN の 1.4 の 4。フェーズ 2b の R1）。

`skills/aws-iac-diagram/scripts/aws_iac_diagram/` の各層が、どの層を import してよいか。import を `ast` で読んで確かめる（実行はしない）。
許す向きの表は support/arch_layers.py の ALLOWED（docs/architecture.md の表と同じ。食い違えば失敗）。入口のスクリプト
（scripts/ の直下と scripts/maintenance/）だけが、どの層でも import してよい。パッケージの中から入口のスクリプトを import
してはいけない。入口どうしも import し合わない。

空振りにしない: 一時フォルダにコピーした構成に、わざと悪い import を入れて、検査が失敗することを確かめる。
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.arch_layers import (
    ALLOWED,
    ENTRY_IMPORT_ALLOW,
    PACKAGE,
    STDLIB_ALLOW,
    SUBPACKAGE_PARENTS,
    check_allowed_table,
    entry_names,
    source_layer,
    stdlib_collisions,
    violations_in_dependencies,
    violations_in_dynamic_imports,
)
from support.paths import ARCH_DOC, SCRIPTS


# --------------------------------------------------------------------------------------------------------------
# テスト
# --------------------------------------------------------------------------------------------------------------
class DependencyDirectionTest(unittest.TestCase):
    def test_real_tree_has_no_violations(self):
        problems, edges = violations_in_dependencies(SCRIPTS)
        self.assertEqual(problems, [], "\n".join(problems))
        # 空振りの防止: 実在する辺を見つけている
        self.assertIn(("adapters/terraform", "core"), edges)
        self.assertIn(("entry", "adapters/terraform"), edges)
        self.assertIn(("adapters/cloudformation", "core"), edges)
        self.assertIn(("entry", "adapters/cloudformation"), edges)
        self.assertIn(("entry", "core"), edges)
        self.assertIn(("entry", "platform"), edges)
        self.assertEqual(violations_in_dynamic_imports(SCRIPTS), [])

    def test_real_tree_names_do_not_collide_with_the_stdlib(self):
        self.assertEqual(stdlib_collisions(SCRIPTS), [])
        self.assertEqual(list(STDLIB_ALLOW), ["platform"])  # 許可はこの 1 つだけ

    def test_mutation_new_stdlib_name_fails(self):
        for name in ("json", "types", "logging"):
            s = self.copy_tree()
            (s / PACKAGE / "core" / f"{name}.py").write_text("X = 1\n", encoding="utf-8")
            problems = stdlib_collisions(s)
            self.assertEqual(len(problems), 1, (name, problems))
            self.assertIn(name, problems[0])
        s = self.copy_tree()
        (s / PACKAGE / "enum").mkdir()
        self.assertTrue(any("enum" in p for p in stdlib_collisions(s)))
        # 許可の表が古くなったら咎める
        s = self.copy_tree()
        shutil.rmtree(s / PACKAGE / "platform")
        self.assertTrue(any("STDLIB_ALLOW の platform" in p for p in stdlib_collisions(s)))

    def test_mutation_dynamic_imports_fail(self):
        cases = {
            "import importlib": "importlib を import",
            "import importlib.util": "importlib を import",
            "from importlib import import_module": "importlib から import",
            "mod = __import__('aws_iac_diagram.emit')": "__import__()",
            "exec('import os')": "exec()",
            "x = eval('1 + 1')": "eval()",
        }
        for line, expect in cases.items():
            s = self.copy_tree()
            f = s / PACKAGE / "adapters" / "terraform" / "modules" / "summaries.py"
            f.write_text(f.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8", newline="\n")
            problems = violations_in_dynamic_imports(s)
            self.assertTrue(any(expect in p for p in problems), (line, problems))
        # メソッドの eval（self.eval(...)）は動的な実行ではない
        s = self.copy_tree()
        f = s / PACKAGE / "core" / "ir_raw.py"
        f.write_text(f.read_text(encoding="utf-8") + "\nclass _X:\n    def go(self):\n        return self.eval(1)\n",
                     encoding="utf-8", newline="\n")
        self.assertEqual(violations_in_dynamic_imports(s), [])

    def test_entry_import_allowlist_is_used_and_narrow(self):
        # 許可の表を空にすると、表にあるものだけが違反として出る（古い許可が残っていない）
        problems, _ = violations_in_dependencies(SCRIPTS, entry_allow={})
        self.assertEqual(len(problems), len(ENTRY_IMPORT_ALLOW), problems)
        for (rel, top), why in ENTRY_IMPORT_ALLOW.items():
            self.assertTrue(any(p.startswith(rel + ":") and f"入口のスクリプト {top} " in p for p in problems), (rel, top))
            self.assertTrue(why.strip())
        self.assertEqual(list(ENTRY_IMPORT_ALLOW), [("maintenance/check_icons.py", "build_icon_catalog")])

    def test_mutation_sibling_entry_imports_fail(self):
        for relpath, line, expect in (("adapt_cfn.py", "import adapt_tf", "入口のスクリプト adapt_tf"),
                                      ("adapt_tf.py", "from adapt_cfn import main", "入口のスクリプト adapt_cfn"),
                                      ("maintenance/build_icon_catalog.py", "import check_icons",
                                       "入口のスクリプト check_icons"),
                                      ("maintenance/check_icons.py", "import doctor",
                                       "入口のスクリプト doctor")):
            s = self.copy_tree()
            problems = self.inject(s, relpath, line)
            self.assertTrue(any(expect in p and p.startswith(relpath) for p in problems), (relpath, problems))
        self.assertTrue({"adapt_tf", "adapt_cfn", "check_icons", "build_icon_catalog", "doctor"} <= entry_names(SCRIPTS))

    def test_every_package_directory_is_a_known_layer(self):
        pkg = SCRIPTS / PACKAGE
        dirs = {p.parent.relative_to(pkg).as_posix() for p in pkg.rglob("__init__.py") if p.parent != pkg}
        known = set(ALLOWED) | {"adapters/terraform", "adapters/cloudformation"}
        # アダプタのパッケージの下のサブパッケージ（adapters/terraform/evaluator など）は、アダプタの層の一部
        subpackages = {d for d in dirs - known if d.rsplit("/", 1)[0] in SUBPACKAGE_PARENTS}
        self.assertEqual(sorted(dirs - known - subpackages), [], "表に無い層のフォルダがある")
        self.assertEqual(sorted(known - dirs), [], "表にあるが無い層（空でも __init__.py を置く）")
        self.assertTrue({"adapters/terraform/evaluator", "adapters/terraform/modules", "adapters/terraform/plan"} <= subpackages)
        for p in pkg.rglob("*.py"):
            self.assertNotEqual(source_layer(p, SCRIPTS)[:1], "?", p)

    def test_table_is_consistent(self):
        self.assertEqual(check_allowed_table(ALLOWED), [])
        self.assertEqual(ALLOWED["core"], frozenset())
        # 決まりの要点（PLAN の 1.4 の 4）
        for a, b in (("adapters/terraform", "adapters/cloudformation"), ("adapters/cloudformation", "adapters/terraform")):
            self.assertNotIn(b, ALLOWED[a])
        for adapter in ("adapters", "adapters/terraform", "adapters/cloudformation"):
            self.assertTrue(ALLOWED[adapter] <= {"core"}, adapter)
        for lower in ("platform", "icons"):
            self.assertFalse({a for a in ALLOWED[lower] if a.startswith("adapters")}, lower)
        for layer, dsts in ALLOWED.items():
            if layer != "emit":
                self.assertNotIn("emit", dsts, layer)

    def test_docs_table_matches(self):
        text = ARCH_DOC.read_text(encoding="utf-8")
        start = text.index("<!-- allowed-edges:begin -->")
        end = text.index("<!-- allowed-edges:end -->")
        rows = {}
        for line in text[start:end].splitlines():
            m = re.match(r"^\|\s*`([a-z/]+)`\s*\|\s*(.*?)\s*\|\s*$", line)
            if m:
                cell = m.group(2)
                rows[m.group(1)] = frozenset(re.findall(r"`([a-z/]+)`", cell))
        self.assertEqual(rows, ALLOWED, "docs/architecture.md の表と ALLOWED が食い違う")

    # --- 空振りの防止: 一時フォルダにコピーして、わざと悪い import を入れる

    def copy_tree(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dst = Path(tmp.name) / "scripts"
        shutil.copytree(SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__"))
        return dst

    def inject(self, scripts: Path, relpath: str, line: str) -> list[str]:
        f = scripts / relpath
        f.write_text(f.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8", newline="\n")
        problems, _ = violations_in_dependencies(scripts)
        return problems

    def test_copy_is_clean_before_mutation(self):
        problems, _ = violations_in_dependencies(self.copy_tree())
        self.assertEqual(problems, [])

    def test_mutation_core_importing_another_layer_fails(self):
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/core/ir_raw.py", "from aws_iac_diagram.platform import drawio_cli")
        self.assertTrue(any("層 core は層 platform" in p for p in problems), problems)

    def test_mutation_adapters_importing_each_other_fails(self):
        s = self.copy_tree()
        (s / "aws_iac_diagram/adapters/cloudformation/x.py").write_text("X = 1\n", encoding="utf-8")
        problems = self.inject(s, "aws_iac_diagram/adapters/terraform/evaluator/functions.py",
                               "from aws_iac_diagram.adapters.cloudformation import x")
        self.assertTrue(any("層 adapters/terraform は層 adapters/cloudformation" in p for p in problems), problems)

    def test_mutation_relative_import_is_resolved(self):
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/adapters/terraform/refs.py", "from ...emit import something")
        self.assertTrue(any("層 adapters/terraform は層 emit" in p for p in problems), problems)
        s2 = self.copy_tree()
        problems = self.inject(s2, "aws_iac_diagram/adapters/terraform/refs.py", "from .. import cloudformation")
        self.assertTrue(any("層 adapters/terraform は層 adapters/cloudformation" in p for p in problems), problems)

    def test_mutation_adapters_importing_emit_layout_normalize_validate_fails(self):
        for layer in ("emit", "layout", "normalize", "validate"):
            s = self.copy_tree()
            problems = self.inject(s, "aws_iac_diagram/adapters/terraform/evaluator/functions.py", f"import aws_iac_diagram.{layer}")
            self.assertTrue(any(f"層 adapters/terraform は層 {layer}" in p for p in problems), (layer, problems))

    def test_mutation_platform_and_icons_importing_adapters_fails(self):
        for layer in ("platform", "icons"):
            s = self.copy_tree()
            problems = self.inject(s, f"aws_iac_diagram/{layer}/__init__.py", "from aws_iac_diagram.adapters.terraform.evaluator import functions")
            self.assertTrue(any(f"層 {layer} は層 adapters/terraform" in p for p in problems), (layer, problems))

    def test_mutation_package_importing_an_entry_script_fails(self):
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/core/ir_raw.py", "import validate_ir")
        self.assertTrue(any("入口のスクリプト validate_ir" in p for p in problems), problems)
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/adapters/terraform/plan/reader.py", "from adapters import cfn")
        self.assertTrue(any("入口のスクリプト adapters" in p for p in problems), problems)
        s = self.copy_tree()
        problems = self.inject(s, "aws_iac_diagram/adapters/terraform/model.py", "import adapt_tf")
        self.assertTrue(any("入口のスクリプト adapt_tf" in p for p in problems), problems)

    def test_mutation_entry_importing_entry_fails_but_entry_importing_layers_is_fine(self):
        s = self.copy_tree()
        self.assertEqual(self.inject(s, "doctor.py", "from aws_iac_diagram.adapters.terraform.evaluator import functions"), [])
        s = self.copy_tree()
        problems = self.inject(s, "doctor.py", "import validate_ir")
        self.assertTrue(any("入口のスクリプト validate_ir" in p for p in problems), problems)

    def test_mutation_unknown_layer_fails(self):
        s = self.copy_tree()
        (s / PACKAGE / "misc").mkdir()
        (s / PACKAGE / "misc" / "__init__.py").write_text('"""x"""\n', encoding="utf-8")
        problems, _ = violations_in_dependencies(s)
        self.assertTrue(any("未知の層 misc" in p for p in problems), problems)

    def test_table_checker_rejects_bad_tables(self):
        self.assertTrue(check_allowed_table({**ALLOWED, "core": frozenset({"icons"})}))
        self.assertTrue(check_allowed_table({"core": frozenset(), "icons": frozenset({"core", "nowhere"})}))
        self.assertTrue(check_allowed_table({"core": frozenset(), "a": frozenset({"b"}), "b": frozenset({"a"})}))


if __name__ == "__main__":
    unittest.main()
