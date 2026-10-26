"""plan JSON: アドレスの読み方（plan/addresses.py）、インスタンスのたたみ込み、入力が plan JSON かどうかの判定とエラー。"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import FIXTURES_TF as FIXTURES, PLANS
import adapt_tf  # noqa: E402
from aws_iac_diagram.adapters.terraform.addresses import block_address  # noqa: E402
from aws_iac_diagram.adapters.terraform.plan import addresses as PA, read as PR  # noqa: E402


class AddressAndCollapseTest(unittest.TestCase):
    def test_collapse_keeps_the_most_specific(self):
        self.assertEqual(PA.collapse(["aws_subnet.private[0].id", "aws_subnet.private[0]", "aws_subnet.private"]),
                         ["aws_subnet.private[0].id"])
        self.assertEqual(PA.collapse(['module.alb.target_groups["app"].arn', 'module.alb.target_groups["app"]',
                                     "module.alb.target_groups", "module.alb"]), ['module.alb.target_groups["app"].arn'])
        # 別のリソースと、前の部分ではないもの（aws_x.ab は aws_x.a の後ろではない）は残す
        self.assertEqual(PA.collapse(["aws_x.a", "aws_x.ab", "var.v", "aws_x.ab", "count.index"]),
                         ["aws_x.a", "aws_x.ab", "var.v", "count.index"])

    def test_steps_and_module_path(self):
        self.assertEqual(PA.parse_steps('module.a["k.1"].aws_x.y[0].id'),
                         [("attr", "module"), ("attr", "a"), ("index", "k.1"), ("attr", "aws_x"), ("attr", "y"),
                          ("index", 0), ("attr", "id")])
        self.assertEqual(PA.module_path('module.a["k"].module.b[0].aws_x.y["z"]'), "module.a.module.b")
        self.assertEqual(PA.module_path("aws_x.y"), "")
        self.assertEqual(block_address('aws_x.y["a[0]"]'), "aws_x.y")

    def test_input_detection_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            state = t / "state.json"
            state.write_text(json.dumps({"format_version": "1.0", "terraform_version": "1.16.5", "values": {}}),
                             encoding="utf-8")
            other = t / "other.json"
            other.write_text("{}", encoding="utf-8")
            future = t / "future.json"
            future.write_text(json.dumps({"format_version": "2.0", "terraform_version": "9.0.0",
                                          "planned_values": {}}), encoding="utf-8")
            self.assertTrue(PR.is_plan_file(PLANS / "rag.json"))
            self.assertFalse(PR.is_plan_file(state))
            self.assertFalse(PR.is_plan_file(FIXTURES / "rag"))
            with self.assertRaisesRegex(PR.PlanError, "state"):
                PR.load_plan(state)
            with self.assertRaisesRegex(PR.PlanError, "plan"):
                PR.load_plan(other)
            with self.assertRaisesRegex(PR.PlanError, "format_version"):
                PR.load_plan(future)
            out = t / "raw.json"
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(adapt_tf.main(["--input", str(other), "--out", str(out)]), 2)
                self.assertEqual(adapt_tf.main(["--input", str(PLANS / "rag.json"), "--out", str(out), "--var", "a=b"]), 2)
                self.assertEqual(adapt_tf.main(["--input", str(PLANS / "rag.json"), "--out", str(out), "--redact-var",
                                          "a"]), 2)
                self.assertEqual(adapt_tf.main(["--input", str(FIXTURES / "rag"), "--plan", str(state), "--out",
                                          str(out)]), 2)
            self.assertIn("state", err.getvalue())


if __name__ == "__main__":
    unittest.main()
