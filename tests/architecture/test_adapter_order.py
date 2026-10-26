"""アダプタの中の順序のテスト（R2 の Terraform、R3 の CloudFormation）。

adapters/terraform と adapters/cloudformation の中のファイルを、グループに分ける。下のグループは上のグループを import
しない。表（support/arch_layers.py の TERRAFORM_GROUPS・INTRA_TERRAFORM など）は docs/architecture.md の表と同じ
（食い違えば失敗）。一時フォルダにコピーした構成に、わざと逆向きの import を入れて、検査が失敗することも確かめる。
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
    CLOUDFORMATION_GROUPS,
    INTRA_CLOUDFORMATION,
    INTRA_TERRAFORM,
    PACKAGE,
    TERRAFORM_GROUPS,
    check_allowed_table,
    violations_in_cloudformation_order,
    violations_in_dependencies,
    violations_in_terraform_order,
)
from support.paths import ARCH_DOC, SCRIPTS


class TerraformOrderTest(unittest.TestCase):
    """adapters/terraform の中の下の層 → 上の層の import を禁じる決まり（docs/architecture.md の「Terraform アダプタの中身」）。"""

    def copy_tree(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dst = Path(tmp.name) / "scripts"
        shutil.copytree(SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__"))
        return dst

    def inject(self, scripts: Path, relpath: str, line: str) -> list[str]:
        f = scripts / PACKAGE / "adapters" / "terraform" / relpath
        f.write_text(f.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8", newline="\n")
        problems, _ = violations_in_terraform_order(scripts)
        return problems

    def test_real_tree_follows_the_order(self):
        problems, edges = violations_in_terraform_order(SCRIPTS)
        self.assertEqual(problems, [], "\n".join(problems))
        # 空振りの防止: 実在する辺を見つけている。表にある辺はすべて実際に使われている（古い許可を残さない）
        for edge in (("mixins", "base"), ("mixins", "evaluator"), ("mixins", "modules"), ("module_eval", "mixins"),
                     ("build", "module_eval"), ("build", "plan"), ("plan", "base"), ("base", "evaluator")):
            self.assertIn(edge, edges)
        self.assertEqual(edges, {(a, b) for a, bs in INTRA_TERRAFORM.items() for b in bs})

    def test_table_is_consistent(self):
        self.assertEqual(set(INTRA_TERRAFORM), set(TERRAFORM_GROUPS))
        self.assertEqual(check_allowed_table(INTRA_TERRAFORM), [])
        members = [m for ms in TERRAFORM_GROUPS.values() for m in ms]
        self.assertEqual(len(members), len(set(members)))
        # 実在する最上位のファイル・フォルダがすべてどこかのグループに入っている
        base = SCRIPTS / PACKAGE / "adapters" / "terraform"
        tops = {p.stem if p.is_file() else p.name for p in base.iterdir()
                if (p.suffix == ".py" or p.is_dir()) and p.name not in ("__init__.py", "__pycache__")}
        self.assertEqual(sorted(tops - set(members)), [])
        self.assertEqual(sorted(set(members) - tops), [])

    def test_docs_table_matches(self):
        text = ARCH_DOC.read_text(encoding="utf-8")
        start = text.index("<!-- terraform-order:begin -->")
        end = text.index("<!-- terraform-order:end -->")
        groups, allowed = {}, {}
        for line in text[start:end].splitlines():
            m = re.match(r"^\|\s*`([a-z_]+)`\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", line)
            if m:
                groups[m.group(1)] = set(re.findall(r"`([a-z_]+)/?`", m.group(2)))
                allowed[m.group(1)] = frozenset(re.findall(r"`([a-z_]+)`", m.group(3)))
        self.assertEqual(groups, {g: set(ms) for g, ms in TERRAFORM_GROUPS.items()},
                         "docs/architecture.md のグループの表と TERRAFORM_GROUPS が食い違う")
        self.assertEqual(allowed, INTRA_TERRAFORM, "docs/architecture.md の表と INTRA_TERRAFORM が食い違う")

    def test_mutation_lower_layers_importing_upper_layers_fail(self):
        tf = "from aws_iac_diagram.adapters.terraform"
        cases = (
            ("evaluator/values.py", f"{tf}.module_eval import ModuleEval", "グループ evaluator はグループ module_eval"),
            ("plan/values.py", f"{tf}.module_expr import ExpressionMixin", "グループ plan はグループ mixins"),
            ("hcl.py", f"{tf} import build", "グループ base はグループ build"),
            ("plan/reader.py", f"{tf}.evaluator import functions", "グループ plan はグループ evaluator"),
            ("modules/resolve.py", f"{tf}.hcl import sig", "グループ modules はグループ base"),
            ("module_expr.py", f"{tf}.module_eval import ModuleEval", "グループ mixins はグループ module_eval"),
            ("module_eval.py", f"{tf}.build import dump", "グループ module_eval はグループ build"),
            ("model.py", "import aws_iac_diagram.adapters.terraform.module_vars as mv", "グループ base はグループ mixins"),
        )
        for relpath, line, expect in cases:
            s = self.copy_tree()
            problems = self.inject(s, relpath, line)
            self.assertTrue(any(expect in p and p.startswith("aws_iac_diagram/adapters/terraform/" + relpath + ":") for p in problems),
                            (relpath, problems))

    def test_mutation_relative_imports_are_resolved(self):
        s = self.copy_tree()
        problems = self.inject(s, "hcl.py", "from . import build")
        self.assertTrue(any("グループ base はグループ build" in p for p in problems), problems)
        s = self.copy_tree()
        problems = self.inject(s, "plan/combine.py", "from .. import module_eval")
        self.assertTrue(any("グループ plan はグループ module_eval" in p for p in problems), problems)

    def test_type_checking_imports_are_not_counted(self):
        line = "from aws_iac_diagram.adapters.terraform.module_eval import ModuleEval"
        s = self.copy_tree()
        self.assertEqual(self.inject(s, "hcl.py", "if TYPE_CHECKING:\n    " + line), [])
        # TYPE_CHECKING の外の import は数える
        s = self.copy_tree()
        problems = self.inject(s, "hcl.py", "if True:\n    " + line)
        self.assertTrue(any("グループ base はグループ module_eval" in p for p in problems), problems)

    def test_mutation_new_file_outside_the_groups_fails(self):
        s = self.copy_tree()
        (s / PACKAGE / "adapters" / "terraform" / "newthing.py").write_text("X = 1\n", encoding="utf-8")
        problems, _ = violations_in_terraform_order(s)
        self.assertTrue(any("newthing.py" in p and "グループに無い" in p for p in problems), problems)


class CloudFormationOrderTest(unittest.TestCase):
    """adapters/cloudformation の中の下の層 → 上の層の import を禁じる決まり（docs/architecture.md の「CloudFormation アダプタの中身」）。"""

    def copy_tree(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dst = Path(tmp.name) / "scripts"
        shutil.copytree(SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__"))
        return dst

    def inject(self, scripts: Path, relpath: str, line: str) -> list[str]:
        f = scripts / PACKAGE / "adapters" / "cloudformation" / relpath
        f.write_text(f.read_text(encoding="utf-8") + "\n" + line + "\n", encoding="utf-8", newline="\n")
        problems, _ = violations_in_cloudformation_order(scripts)
        return problems

    def test_real_tree_follows_the_order(self):
        problems, edges = violations_in_cloudformation_order(SCRIPTS)
        self.assertEqual(problems, [], "\n".join(problems))
        # 空振りの防止: 表にある辺はすべて実際に使われている（古い許可を残さない）
        self.assertEqual(edges, {(a, b) for a, bs in INTRA_CLOUDFORMATION.items() for b in bs})

    def test_table_is_consistent(self):
        self.assertEqual(set(INTRA_CLOUDFORMATION), set(CLOUDFORMATION_GROUPS))
        self.assertEqual(check_allowed_table(INTRA_CLOUDFORMATION), [])
        members = [m for ms in CLOUDFORMATION_GROUPS.values() for m in ms]
        self.assertEqual(len(members), len(set(members)))
        # 実在する最上位のファイルがすべてどこかのグループに入っている
        base = SCRIPTS / PACKAGE / "adapters" / "cloudformation"
        tops = {p.stem if p.is_file() else p.name for p in base.iterdir()
                if (p.suffix == ".py" or p.is_dir()) and p.name not in ("__init__.py", "__pycache__")}
        self.assertEqual(sorted(tops - set(members)), [])
        self.assertEqual(sorted(set(members) - tops), [])

    def test_docs_table_matches(self):
        text = ARCH_DOC.read_text(encoding="utf-8")
        start = text.index("<!-- cloudformation-order:begin -->")
        end = text.index("<!-- cloudformation-order:end -->")
        groups, allowed = {}, {}
        for line in text[start:end].splitlines():
            m = re.match(r"^\|\s*`([a-z_]+)`\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$", line)
            if m:
                groups[m.group(1)] = set(re.findall(r"`([a-z_]+)`", m.group(2)))
                allowed[m.group(1)] = frozenset(re.findall(r"`([a-z_]+)`", m.group(3)))
        self.assertEqual(groups, {g: set(ms) for g, ms in CLOUDFORMATION_GROUPS.items()},
                         "docs/architecture.md のグループの表と CLOUDFORMATION_GROUPS が食い違う")
        self.assertEqual(allowed, INTRA_CLOUDFORMATION, "docs/architecture.md の表と INTRA_CLOUDFORMATION が食い違う")

    def test_mutation_lower_layers_importing_upper_layers_fail(self):
        cf = "from aws_iac_diagram.adapters.cloudformation"
        cases = (
            ("loader.py", f"{cf}.build import dump", "グループ base はグループ build"),
            ("marks.py", f"{cf}.conditions import weaker", "グループ base はグループ mixins"),
            ("refs.py", f"{cf}.evaluator import Evaluator", "グループ base はグループ evaluator"),
            ("model.py", f"{cf}.stack import StackEval", "グループ base はグループ stack"),
            ("cdk.py", f"{cf}.stack import StackEval", "グループ base はグループ stack"),
            ("conditions.py", f"{cf}.evaluator import Evaluator", "グループ mixins はグループ evaluator"),
            ("nested.py", f"{cf}.stack import StackEval", "グループ mixins はグループ stack"),
            ("intrinsics.py", f"{cf}.build import build_raw", "グループ mixins はグループ build"),
            ("evaluator.py", f"{cf}.stack import StackEval", "グループ evaluator はグループ stack"),
            ("evaluator.py", f"{cf}.build import dump", "グループ evaluator はグループ build"),
            ("stack.py", f"{cf}.build import dump", "グループ stack はグループ build"),
        )
        for relpath, line, expect in cases:
            s = self.copy_tree()
            problems = self.inject(s, relpath, line)
            self.assertTrue(any(expect in p and p.startswith("aws_iac_diagram/adapters/cloudformation/" + relpath + ":") for p in problems),
                            (relpath, line, problems))

    def test_mutation_relative_imports_are_resolved(self):
        s = self.copy_tree()
        problems = self.inject(s, "loader.py", "from . import build")
        self.assertTrue(any("グループ base はグループ build" in p for p in problems), problems)
        s = self.copy_tree()
        problems = self.inject(s, "marks.py", "from .conditions import weaker")
        self.assertTrue(any("グループ base はグループ mixins" in p for p in problems), problems)

    def test_type_checking_imports_are_not_counted(self):
        # model.py は StackEval を型の注釈のためだけに TYPE_CHECKING の中で import している（実行時は import しない）
        self.assertIn("TYPE_CHECKING", (SCRIPTS / PACKAGE / "adapters" / "cloudformation" / "model.py").read_text(encoding="utf-8"))
        line = "from aws_iac_diagram.adapters.cloudformation.build import dump"
        s = self.copy_tree()
        self.assertEqual(self.inject(s, "loader.py", "if TYPE_CHECKING:\n    " + line), [])
        s = self.copy_tree()
        problems = self.inject(s, "loader.py", "if True:\n    " + line)
        self.assertTrue(any("グループ base はグループ build" in p for p in problems), problems)

    def test_mutation_new_file_outside_the_groups_fails(self):
        s = self.copy_tree()
        (s / PACKAGE / "adapters" / "cloudformation" / "newthing.py").write_text("X = 1\n", encoding="utf-8")
        problems, _ = violations_in_cloudformation_order(s)
        self.assertTrue(any("newthing.py" in p and "グループに無い" in p for p in problems), problems)

    def test_adapters_do_not_import_each_other(self):
        # アダプタどうし（terraform ⇄ cloudformation）は読み合わない。ここでは cloudformation の側を実ファイルで確かめる
        problems, edges = violations_in_dependencies(SCRIPTS)
        self.assertEqual(problems, [])
        self.assertIn(("adapters/cloudformation", "core"), edges)
        self.assertNotIn(("adapters/cloudformation", "adapters/terraform"), edges)
        self.assertNotIn(("adapters/terraform", "adapters/cloudformation"), edges)
        s = self.copy_tree()
        f = s / PACKAGE / "adapters" / "cloudformation" / "build.py"
        f.write_text(f.read_text(encoding="utf-8") + "\nfrom aws_iac_diagram.adapters.terraform import build as tf_build\n", encoding="utf-8", newline="\n")
        problems, _ = violations_in_dependencies(s)
        self.assertTrue(any("層 adapters/cloudformation は層 adapters/terraform" in p for p in problems), problems)
        f.write_text(f.read_text(encoding="utf-8") + "\nfrom aws_iac_diagram.adapters import registry\n", encoding="utf-8", newline="\n")
        problems, _ = violations_in_dependencies(s)
        self.assertTrue(any("層 adapters/cloudformation は層 adapters" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
