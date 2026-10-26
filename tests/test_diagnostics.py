"""診断コードの一覧（core/diagnostics.py）のテスト。

- 一覧の形（コードの形、接頭辞、level、説明、並び順）。
- 一覧と references/ir-schema.md の 7.5 が、TF と CFN の両方で同じ（コードが足りない・余っていると失敗）。
- アダプタを実際に動かして出た (code, level) が、一覧にある（level の組み合わせも）。
- アダプタのコードにある文字列と一覧の照合（足りない・余っている）は tests/test_architecture.py の DiagnosticRegistryRuleTest。
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "aws-iac-diagram" / "scripts"
WS = ROOT / "aws-iac-diagram-workspace"
sys.path.insert(0, str(SCRIPTS))
from aws_iac_diagram.adapters.cloudformation import build as cfn_build  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402
from aws_iac_diagram.core import diagnostics as D  # noqa: E402

SCHEMA_DOC = SCRIPTS.parent / "references" / "ir-schema.md"


def doc_section() -> str:
    doc = SCHEMA_DOC.read_text(encoding="utf-8")
    a = doc.index("### 7.5 診断")
    b = doc.index("\n## 8.", a)
    return doc[a:b]


class RegistryShapeTest(unittest.TestCase):
    def test_every_row_is_well_formed(self):
        self.assertTrue(D.DIAGNOSTICS)
        for code, d in D.DIAGNOSTICS.items():
            with self.subTest(code):
                self.assertEqual(code, d.code)
                self.assertRegex(code, D.CODE_PATTERN)
                self.assertIn(code.split("-", 1)[0], D.PREFIXES)
                self.assertEqual(code, code.upper())
                self.assertTrue(d.levels)
                self.assertTrue(set(d.levels) <= set(D.LEVELS))
                self.assertEqual(list(d.levels), sorted(set(d.levels), key=D.LEVELS.index), "levels は重い順（error＞warn＞info）で重複なし")
                self.assertTrue(d.description.strip())
                self.assertIn(d.adapter, ("terraform", "cloudformation"))

    def test_counts_and_order(self):
        # 数は文書（ir-schema.md の 7.5）と一緒に直す。CFN は接頭辞 CFN-、TF は TF-。それぞれアルファベット順
        self.assertEqual((len(D.codes("cloudformation")), len(D.codes("terraform")), len(D.DIAGNOSTICS)), (19, 43, 62))
        self.assertEqual(D.codes(), D.codes("cloudformation") + D.codes("terraform"))
        for adapter in ("cloudformation", "terraform"):
            self.assertEqual(D.codes(adapter), sorted(D.codes(adapter)))
        self.assertTrue(all(c.startswith("CFN-") for c in D.codes("cloudformation")))
        self.assertTrue(all(c.startswith("TF-") for c in D.codes("terraform")))

    def test_lookup(self):
        self.assertEqual(D.lookup("TF-UNEVALUATED").levels, ("warn", "info"))
        self.assertEqual(D.lookup("CFN-CONDITION-CYCLE").levels, ("error",))
        self.assertIsNone(D.lookup("TF-NOT-A-CODE"))

    def test_core_has_no_imports_of_other_layers(self):
        # core は静的な import の検査（tests/test_architecture.py）の対象。ここでは標準ライブラリだけを使うことも確かめる
        text = (SCRIPTS / "aws_iac_diagram" / "core" / "diagnostics.py").read_text(encoding="utf-8")
        imports = set(re.findall(r"^(?:from|import)\s+([A-Za-z_][\w.]*)", text, flags=re.M))
        self.assertEqual(imports, {"__future__", "re", "dataclasses"})


class DiagnosticCodesTest(unittest.TestCase):
    """一覧と ir-schema.md の 7.5 の診断コードの一覧が、TF と CFN の両方で食い違わない。"""

    def test_registry_matches_the_schema_doc(self):
        section = doc_section()
        for prefix, adapter in D.PREFIXES.items():
            with self.subTest(prefix):
                in_doc = set(re.findall(rf"`({prefix}-[A-Z0-9]+(?:-[A-Z0-9]+)*)`", section))
                in_registry = set(D.codes(adapter))
                self.assertEqual(sorted(in_registry - in_doc), [], "一覧にあって ir-schema.md の 7.5 に無いコード")
                self.assertEqual(sorted(in_doc - in_registry), [], "ir-schema.md の 7.5 にあって一覧に無いコード")
        # 見出しの 7.6 は無い（フェーズ2 の間だけの注記だった）
        self.assertNotIn("### 7.6", SCHEMA_DOC.read_text(encoding="utf-8"))

    def test_the_doc_states_the_counts(self):
        section = doc_section()
        self.assertIn("TF アダプタの `code` の一覧（43 個", section)
        self.assertIn("CFN アダプタの `code` の一覧（19 個", section)

    def test_doc_names_the_levels_of_cfn_codes(self):
        # CFN の一覧は「`CODE`（level。説明）」の形で level を書く。一覧の levels（のどれか）が書いてある
        section = doc_section()
        for code in D.codes("cloudformation"):
            m = re.search(rf"`{code}`（([^）]*)）", section)
            self.assertIsNotNone(m, code)
            words = set(re.findall(r"\b(error|warn|info)\b", m.group(1)))
            self.assertEqual(words, set(D.lookup(code).levels), code)


class EmittedLevelsTest(unittest.TestCase):
    """アダプタを実際に動かして出た (code, level) は、すべて一覧にある（コードと、その level の組み合わせ）。"""

    def assert_known(self, raw: dict, where: str) -> set[tuple[str, str]]:
        seen = set()
        for d in raw["diagnostics"]:
            entry = D.lookup(d["code"])
            self.assertIsNotNone(entry, f"{where}: {d['code']} が一覧に無い")
            self.assertIn(d["level"], entry.levels, f"{where}: {d['code']} を {d['level']} で出した（一覧は {entry.levels}）")
            self.assertEqual(entry.adapter, "terraform" if raw["format"] == "tf" else "cloudformation", where)
            seen.add((d["code"], d["level"]))
        return seen

    def test_fixtures(self):
        seen: set[tuple[str, str]] = set()
        tf = WS / "fixtures" / "tf"
        for d in sorted(p for p in tf.iterdir() if p.is_dir()):
            seen |= self.assert_known(tf_build.build_raw(d, WS), f"tf/{d.name}")
        plans = WS / "fixtures" / "tf-plan"
        for f in sorted(plans.glob("*.json")):
            folder = plans / "edge" if f.stem == "edge" else tf / f.stem.split(".")[0]
            seen |= self.assert_known(tf_build.build_from_plan(f, WS), f"plan/{f.name}")
            seen |= self.assert_known(tf_build.build_raw(folder, WS, plan=f), f"combined/{f.name}")
        cfn = WS / "fixtures" / "cfn"
        for t in ("three-tier/template.yaml", "rag/template.yaml", "serverless-api/template.yaml", "three-tier-modules/root.yaml",
                  "vpc-endpoints/template.json"):
            seen |= self.assert_known(cfn_build.build_raw(cfn / t, WS), f"cfn/{t}")
        # 空振りの防止: 実際に診断が出ていて、TF と CFN の両方を見ている
        self.assertTrue(any(c.startswith("TF-") for c, _ in seen))
        self.assertTrue(any(c.startswith("CFN-") for c, _ in seen))
        self.assertGreater(len(seen), 8)

    def test_levels_that_the_fixtures_do_not_reach(self):
        # error など、fixture では出ない (code, level) を、小さな入力で出す
        want = {
            ("CFN-CONDITION-CYCLE", "error"): """\
                Conditions:
                  A: !Condition B
                  B: !Condition A
                Resources:
                  Q:
                    Type: AWS::SQS::Queue
                    Condition: A
                """,
            ("CFN-MALFORMED-RESOURCE", "error"): """\
                Resources:
                  Q: not-an-object
                """,
            ("CFN-UNDEFINED-CONDITION", "warn"): """\
                Resources:
                  Q:
                    Type: AWS::SQS::Queue
                    Condition: Nope
                """,
            ("CFN-DYNAMIC-REF", "warn"): """\
                Resources:
                  Q:
                    Type: AWS::SQS::Queue
                    Properties:
                      QueueName: '{{resolve:ssm:/a/b}}'
                """,
            ("CFN-UNDEFINED-REF", "warn"): """\
                Resources:
                  Q:
                    Type: AWS::SQS::Queue
                    Properties:
                      QueueName: !Ref Nowhere
                """,
        }
        with tempfile.TemporaryDirectory() as tmp:
            for (code, level), text in want.items():
                p = Path(tmp) / f"{code}.yaml"
                p.write_text(textwrap.dedent(text), encoding="utf-8")
                seen = self.assert_known(cfn_build.build_raw(p, Path(tmp)), code)
                self.assertIn((code, level), seen)
            tfdir = Path(tmp) / "bad"
            tfdir.mkdir()
            (tfdir / "main.tf").write_text('resource "aws_s3_bucket" "b" {\n  bucket = \n', encoding="utf-8")
            seen = self.assert_known(tf_build.build_raw(tfdir, Path(tmp)), "tf-parse")
            self.assertIn(("TF-PARSE-ERROR", "error"), seen)

    def test_registry_levels_are_written_to_the_json(self):
        # 出力のバイト列が一覧の表記（"warn"・"info"・"error"）を使っている（スキーマの列挙と同じ）
        schema = json.loads((SCRIPTS.parent / "references" / "ir-raw.schema.json").read_text(encoding="utf-8"))
        text = json.dumps(schema)
        for level in D.LEVELS:
            self.assertIn(f'"{level}"', text)


if __name__ == "__main__":
    unittest.main()
