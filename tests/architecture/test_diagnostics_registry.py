"""診断コードの一覧の規則のテスト（R3。PLAN の 1.4 の 4）。

アダプタのコードにある診断コードの文字列（`diag(...)` などの位置のもの）と core/diagnostics.py の一覧を照合する。
一覧に無いコードを使ったら失敗、一覧にあって使われていないコードも失敗（UNUSED_ALLOW に理由を付けたものを除く）。
一覧そのものの形と、ir-schema.md の 7.5 との一致は tests/architecture/test_diagnostics.py。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.arch_diagnostics import (
    UNUSED_ALLOW,
    diagnostic_scan_files,
    scan_diagnostic_codes,
    violations_in_diagnostics,
)
from support.paths import SCRIPTS
from aws_iac_diagram.core import diagnostics  # noqa: E402


class DiagnosticRegistryRuleTest(unittest.TestCase):
    """アダプタが出す診断コードは、すべて core/diagnostics.py の一覧にある（逆も）。PLAN の 1.4 の 4。"""

    REGISTRY = {c: d.levels for c, d in diagnostics.DIAGNOSTICS.items()}

    def copy_tree(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dst = Path(tmp.name) / "scripts"
        shutil.copytree(SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__"))
        return dst

    def append(self, scripts: Path, relpath: str, text: str) -> None:
        f = scripts / relpath
        f.write_text(f.read_text(encoding="utf-8") + "\n" + text + "\n", encoding="utf-8", newline="\n")

    def problems(self, scripts: Path, registry=None, unused_allow=None) -> list[str]:
        return violations_in_diagnostics(scripts, self.REGISTRY if registry is None else registry,
                                         UNUSED_ALLOW if unused_allow is None else unused_allow)

    def test_real_tree_matches_the_registry(self):
        self.assertEqual(self.problems(SCRIPTS), [])
        sites, bad = scan_diagnostic_codes(SCRIPTS)
        self.assertEqual(bad, [])
        # 空振りの防止: 実際のコードの文字列を見つけている。TF と CFN の両方、集合・比較の位置と、level を書いた位置も
        self.assertEqual({s.code for s in sites}, set(self.REGISTRY))
        self.assertTrue(any(s.code.startswith("TF-") and s.use for s in sites))
        self.assertTrue(any(s.code.startswith("CFN-") and s.use for s in sites))
        self.assertTrue(any(not s.use for s in sites))
        self.assertTrue(any(s.levels for s in sites))
        # 入口の adapt_cfn.py・adapt_tf.py も範囲に入っている
        files = {p.name for p in diagnostic_scan_files(SCRIPTS)}
        self.assertTrue({"adapt_cfn.py", "adapt_tf.py", "build.py", "stack.py", "module_expr.py"} <= files)

    def test_unused_allowlist_is_empty(self):
        self.assertEqual(UNUSED_ALLOW, {})

    def test_scan_copy_is_clean_before_mutation(self):
        self.assertEqual(self.problems(self.copy_tree()), [])

    def test_mutation_unregistered_code_fails(self):
        cases = (
            ("aws_iac_diagram/adapters/terraform/module_load.py", 'self.diag("warn", "TF-NEW-THING", "", "x", "")'),
            ("aws_iac_diagram/adapters/cloudformation/build.py", 'X = {"level": "info", "code": "CFN-NEW-THING"}'),
            ("aws_iac_diagram/adapters/cloudformation/params.py", 'def f(self, code="CFN-NEW-DEFAULT"):\n    return code'),
            ("aws_iac_diagram/adapters/terraform/plan/combine.py", 'Y = ("blackbox", "warn", "TF-NEW-TUPLE", "m")'),
            ("aws_iac_diagram/adapters/terraform/evaluator/values.py", 'Z = {"TF-NEW-IN-SET"}'),
            ("adapt_cfn.py", 'W = "CFN-NEW-IN-ENTRY"'),
            ("adapt_tf.py", 'W = "TF-NEW-IN-ENTRY"'),
        )
        for relpath, text in cases:
            s = self.copy_tree()
            self.append(s, relpath, text)
            problems = self.problems(s)
            self.assertTrue(any("が core/diagnostics.py の一覧に無い" in p and p.startswith(relpath + ":") for p in problems),
                            (relpath, text, problems))

    def test_mutation_typo_in_a_real_code_fails(self):
        for rel, old, new in (("aws_iac_diagram/adapters/cloudformation/build.py", '"CFN-PARAM-UNUSED"', '"CFN-PARAM-UNUSD"'),
                              ("aws_iac_diagram/adapters/terraform/build.py", '"TF-ROOT-OTHER-DRIVE"', '"TF-ROOT-OTHER-DRIV"')):
            s = self.copy_tree()
            f = s / rel
            text = f.read_text(encoding="utf-8")
            self.assertEqual(text.count(old), 1)
            f.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
            problems = self.problems(s)
            self.assertTrue(any(new.strip('"') in p and "一覧に無い" in p for p in problems), problems)
            # 打ち間違えると、元のコードを出すところが（ほかに無ければ）無くなるので、一覧のコードは使われていない扱いにもなる
            if rel.endswith("cloudformation/build.py"):
                self.assertTrue(any(old.strip('"') in p and "どこでも出していない" in p for p in problems), problems)

    def test_mutation_built_codes_fail(self):
        for text in ('name = "x"\ncode = "TF-" + name', 'name = "x"\ncode = f"TF-{name}"', 'name = "x"\ncode = "TF-%s" % name',
                     'code = "TF-unevaluated"'):
            s = self.copy_tree()
            self.append(s, "aws_iac_diagram/adapters/terraform/refs.py", text)
            problems = self.problems(s)
            self.assertTrue(any("診断コードの形でないのに" in p for p in problems), (text, problems))

    def test_mutation_unused_registry_code_fails(self):
        # 一覧にだけあるコード
        registry = {**self.REGISTRY, "TF-NEVER-USED": ("warn",)}
        problems = self.problems(SCRIPTS, registry=registry)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("TF-NEVER-USED は一覧にあるが", problems[0])
        # コードの集合・比較にだけ書いてあるものは、出していない扱い
        s = self.copy_tree()
        self.append(s, "aws_iac_diagram/adapters/terraform/refs.py",
                    'ONLY_SET = {"TF-NEVER-USED"}\nONLY_CMP = ("a" == "TF-NEVER-USED")\nONLY_IN = ("a" in ("TF-NEVER-USED", "TF-UNEVALUATED"))')
        problems = self.problems(s, registry=registry)
        self.assertTrue(any("TF-NEVER-USED は一覧にあるが" in p for p in problems), problems)
        # 本物のコードを使っている全部の位置から消すと、そのコードは使われていない扱い
        s = self.copy_tree()
        f = s / "aws_iac_diagram/adapters/cloudformation/build.py"
        f.write_text(f.read_text(encoding="utf-8").replace('"CFN-ABSOLUTE-ROOT"', '"CFN-PARAM-UNUSED"'), encoding="utf-8", newline="\n")
        problems = self.problems(s)
        self.assertEqual(len([p for p in problems if "CFN-ABSOLUTE-ROOT" in p]), 1, problems)
        self.assertEqual(len([p for p in problems if "どこでも出していない" in p]), 1, problems)

    def test_unused_allowlist_is_checked(self):
        registry = {**self.REGISTRY, "TF-NEVER-USED": ("warn",)}
        self.assertEqual(self.problems(SCRIPTS, registry=registry, unused_allow={"TF-NEVER-USED": "理由"}), [])
        # 理由が無い・一覧に無い・使われているコードの許可は、古い許可として失敗する
        self.assertTrue(self.problems(SCRIPTS, registry=registry, unused_allow={"TF-NEVER-USED": " "}))
        self.assertTrue(any("が一覧に無い" in p for p in self.problems(SCRIPTS, unused_allow={"TF-NOT-IN-REGISTRY": "x"})))
        self.assertTrue(any("使われている" in p for p in self.problems(SCRIPTS, unused_allow={"TF-UNEVALUATED": "x"})))

    def test_mutation_level_not_in_the_registry_fails(self):
        for code, level, call in (("TF-COUNT-INDEX", "error", 'self.diag("error", "TF-COUNT-INDEX", "", "x", "")'),
                                  ("CFN-ABSOLUTE-ROOT", "warn", 'D = {"level": "warn", "code": "CFN-ABSOLUTE-ROOT"}'),
                                  ("TF-PARSE-ERROR", "info", 'T = ("a", "info", "TF-PARSE-ERROR")')):
            s = self.copy_tree()
            self.append(s, "aws_iac_diagram/adapters/terraform/refs.py", call)
            problems = self.problems(s)
            self.assertTrue(any(f"{code} を level {level} で出している" in p for p in problems), (call, problems))
        # 一覧にある level なら、問題にならない
        s = self.copy_tree()
        self.append(s, "aws_iac_diagram/adapters/terraform/refs.py", 'self.diag("info", "TF-UNEVALUATED", "", "x", "")')
        self.assertEqual(self.problems(s), [])

    def test_code_looking_strings_with_other_prefixes_are_ignored_outside_emit_positions(self):
        # "UTF-8"・"GET-OBJECT" のような、コードの形で接頭辞が違う文字列は、診断を出す位置の外なら数えない
        for text in ('ENC = "UTF-8"', 'open("x", encoding="UTF-8")', 'ACTION = "GET-OBJECT"', 'IS = ("a" == "GET-OBJECT")',
                     'SET = {"UTF-8", "GET-OBJECT"}', 'D = {"encoding": "UTF-8", "name": "GET-OBJECT"}',
                     'foo("a", "GET-OBJECT")', 'T = ("a", "GET-OBJECT")'):
            s = self.copy_tree()
            self.append(s, "aws_iac_diagram/adapters/terraform/refs.py", text)
            self.assertEqual(self.problems(s), [], text)
            sites, _ = scan_diagnostic_codes(s)
            self.assertFalse({x.code for x in sites} & {"UTF-8", "GET-OBJECT"}, text)

    def test_mutation_unknown_prefix_in_an_emit_position_fails(self):
        cases = (
            'self.diag("warn", "NORM-NEW-THING", "", "x", "")',
            'self.diag("warn", "GET-OBJECT", "", "x", "")',
            'D = {"level": "info", "code": "FOO-BAR"}',
            'U = Unknown("m", "XYZ-ABC")',
            'U = unknown_from([], "m", "XYZ-ABC")',
            'T = ("blackbox", "warn", "QQ-RR", "m")',
            'self.diag(level="info", code="ZZ-TOP", path="", message="m")',
        )
        for text in cases:
            s = self.copy_tree()
            self.append(s, "aws_iac_diagram/adapters/cloudformation/build.py", text)
            problems = self.problems(s)
            self.assertTrue(any("ALLOWED_PREFIXES に無い" in p and p.startswith("aws_iac_diagram/adapters/cloudformation/build.py:")
                                for p in problems), (text, problems))
        # 接頭辞を ALLOWED_PREFIXES に足す（意図して）と、今度は「一覧に無いコード」として失敗する
        s = self.copy_tree()
        self.append(s, "aws_iac_diagram/adapters/cloudformation/build.py", 'self.diag("warn", "NORM-NEW-THING", "", "x", "")')
        with mock.patch.object(diagnostics, "ALLOWED_PREFIXES", (*diagnostics.ALLOWED_PREFIXES, "NORM")):
            problems = self.problems(s)
        self.assertTrue(any("NORM-NEW-THING が core/diagnostics.py の一覧に無い" in p for p in problems), problems)
        self.assertFalse(any("ALLOWED_PREFIXES に無い" in p for p in problems), problems)
        self.assertEqual(diagnostics.ALLOWED_PREFIXES, tuple(diagnostics.PREFIXES))

    def test_scanner_does_not_look_outside_the_adapters(self):
        # 範囲は入口のアダプタと adapters/ の下だけ（NORM-… などほかの層のコードは、その層が育つとき範囲に足す）
        s = self.copy_tree()
        self.append(s, "aws_iac_diagram/core/ir_raw.py", 'X = "E-NOEDGE-SOMETHING"')
        self.assertEqual(self.problems(s), [])


if __name__ == "__main__":
    unittest.main()
