"""core/module_sources.py（レジストリの source の形と、IAM だけを作るモジュールの一覧 = H-IAM の判定）のテスト。

手順 1 で `iam_only()` を TF アダプタから core へ移した。移した後も、アダプタの出力（診断の文言）は 1 バイトも変わらない
（golden 101/101 が確かめる）。ここでは、移した関数そのものの動きと、アダプタとの接続を調べる。
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
from support.paths import SKILL
from aws_iac_diagram.adapters.terraform.modules import resolve, sources, summaries  # noqa: E402
from aws_iac_diagram.core import module_sources as ms  # noqa: E402


class ModuleSourcesTest(unittest.TestCase):
    def make(self, text: str | None, name: str = ms.IAM_FILE) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name) / "要約表"
        root.mkdir()
        if text is not None:
            (root / name).write_text(text, encoding="utf-8", newline="\n")
        return root

    def test_registry_key_is_one_function_shared_with_the_adapter(self):
        self.assertIs(sources.registry_key, ms.registry_key)
        self.assertEqual(ms.registry_key("registry.terraform.io/terraform-aws-modules/iam/aws//modules/x/"),
                         "terraform-aws-modules/iam/aws//modules/x")
        self.assertEqual(ms.registry_key("registry.opentofu.org/a/b/c"), "a/b/c")
        for s in ("./local", "git::https://x/y.git", "github.com/a/b", "a/b", "a/b/c?ref=1", "git@github.com:a/b/c.git"):
            self.assertIsNone(ms.registry_key(s), s)

    def test_the_shipped_list_matches_the_prefix_rule(self):
        self.assertTrue((SKILL / "data" / "module-summaries" / ms.IAM_FILE).is_file())
        got = ms.load_iam_sources()
        self.assertEqual(got, ("terraform-aws-modules/iam/aws",))
        self.assertTrue(ms.iam_only("terraform-aws-modules/iam/aws"))
        self.assertTrue(ms.iam_only("terraform-aws-modules/iam/aws//modules/iam-assumable-role-with-oidc"))
        self.assertTrue(ms.iam_only("registry.terraform.io/terraform-aws-modules/iam/aws//modules/x"))
        self.assertFalse(ms.iam_only("terraform-aws-modules/iam-foo/aws"))  # 前方一致は区切りまで（iam と iam-foo は別）
        self.assertFalse(ms.iam_only("terraform-aws-modules/vpc/aws"))
        self.assertFalse(ms.iam_only("./modules/iam"))  # レジストリでない source
        self.assertFalse(ms.iam_only(""))

    def test_list_parsing_rules(self):
        root = self.make("# 説明\n<!-- iam-only-sources -->\n\n```text\n# コメント行は読まない\na/b/c\n\n  d/e/f//  \n```\n")
        self.assertEqual(ms.load_iam_sources(root), ("a/b/c", "d/e/f//"))
        self.assertTrue(ms.iam_only("a/b/c//modules/x", root))
        self.assertTrue(ms.iam_only("d/e/f//modules/y", root))  # 末尾が // の一覧は、サブモジュールだけの前方一致
        self.assertFalse(ms.iam_only("d/e/f", root))
        self.assertFalse(ms.iam_only("a/b/cc", root))

    def test_missing_or_empty_list_reads_as_empty(self):
        self.assertEqual(ms.load_iam_sources(self.make(None)), ())
        self.assertEqual(ms.load_iam_sources(self.make("# マーカーが無い\na/b/c\n")), ())
        self.assertEqual(ms.load_iam_sources(self.make("<!-- iam-only-sources -->\nコードブロックが無い\n")), ())
        self.assertEqual(ms.load_iam_sources(Path("nowhere-at-all")), ())
        self.assertFalse(ms.iam_only("a/b/c", self.make(None)))

    def test_only_the_iam_file_is_read(self):
        # 要約表のフォルダの別のファイル（NOTICE.md など）の中の iam-only-sources は読まない
        root = self.make("<!-- iam-only-sources -->\n```text\nx/y/z\n```\n", name="NOTICE.md")
        self.assertEqual(ms.load_iam_sources(root), ())

    def test_blackbox_message_uses_the_core_judgement(self):
        # アダプタの黒箱の診断（TF-MODULE-BLACKBOX）の message の末尾の判定は、core の iam_only() と同じ
        src = "terraform-aws-modules/iam/aws//modules/iam-role"
        plan = resolve.blackbox_plan(src, "no table")
        self.assertEqual(plan[:3], ("blackbox", "info", "TF-MODULE-BLACKBOX"))
        self.assertTrue(plan[3].endswith("(it makes IAM resources only: H-IAM)"), plan[3])
        plan = resolve.blackbox_plan("aws-ia/vpc/aws", "no table")
        self.assertEqual(plan[3], "module aws-ia/vpc/aws is not read: no table")
        # 要約表のフォルダを差し替えると（テストが表の欠けを作るやり方）、IAM の一覧も差し替えた先を読む（移す前と同じ）
        root = self.make("<!-- iam-only-sources -->\n```text\naws-ia/vpc/aws\n```\n")
        for f in summaries.SUMMARY_DIR.iterdir():  # 要約表（v<数字>.md）は本物のまま。IAM の一覧だけ差し替える
            if f.is_dir():
                shutil.copytree(f, root / f.name)
        with mock.patch.object(summaries, "SUMMARY_DIR", root):
            self.assertTrue(resolve.blackbox_plan("aws-ia/vpc/aws", "no table")[3].endswith("H-IAM)"))
            self.assertFalse(resolve.blackbox_plan(src, "no table")[3].endswith("H-IAM)"))

    def test_the_adapter_no_longer_defines_iam_only(self):
        self.assertFalse(hasattr(summaries, "iam_only"))
        self.assertFalse(hasattr(sources, "iam_only"))


if __name__ == "__main__":
    unittest.main()
