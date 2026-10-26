"""plan JSON: 診断（unknown・errored・不完全・planned でない・.tf のフォルダと合わない・destroy・別ドライブ・.tf.json の範囲）。"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import res_of
from support.paths import WS
from support.tf_plan import (
    CASES,
    EDGE,
    EDGE_PLAN,
    TempTestCase,
    assert_valid_no_errors as assert_valid,
    cfg,
    combined_raw,
    const,
    diag_codes,
    mkplan,
    plan_only,
    props_of,
    rc,
    refs,
    unk,
    write_files,
    write_json,
)
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402
from aws_iac_diagram.adapters.terraform.plan import consistency as PK, values as PV  # noqa: E402


class PlanDiagnosticsTest(TempTestCase):
    def test_unknown(self):
        plan = mkplan([rc("aws_x.a", {"name": None, "ok": "v"}, unknown={"name": True})],
                      [cfg("aws_x.a", {"name": {}, "ok": const("v")})])
        raw = plan_only(self.tmp, plan)
        self.assertEqual(props_of(raw, "aws_x.a")["name"], unk(PV.UNKNOWN_REASON))
        d = [d for d in raw["diagnostics"] if d["code"] == "TF-PLAN-UNKNOWN"]
        self.assertEqual([(x["address"], x["path"], x["level"], x["message"]) for x in d],
                         [("aws_x.a", "name", "info", "value is known only after apply")])

    def test_errored_and_incomplete(self):
        base = mkplan([rc("aws_x.a", {"n": "v"})], [cfg("aws_x.a", {"n": const("v")})])
        raw = plan_only(self.tmp, dict(base, errored=True))
        self.assertEqual(diag_codes(raw, "TF-PLAN-ERRORED"), [("", "", "warn")])
        self.assertEqual(diag_codes(raw, "TF-PLAN-INCOMPLETE"), [])
        raw = plan_only(self.tmp, dict(base, complete=False))
        self.assertEqual(diag_codes(raw, "TF-PLAN-INCOMPLETE"), [("", "", "warn")])
        raw = plan_only(self.tmp, dict(base, deferred_changes=[{"reason": "x"}, {"reason": "y"}]))
        incomplete = [d for d in raw["diagnostics"] if d["code"] == "TF-PLAN-INCOMPLETE"]
        self.assertEqual([(d["level"], d["path"]) for d in incomplete], [("warn", "deferred_changes")])
        self.assertIn("2 change(s)", incomplete[0]["message"])

    def test_not_planned_and_extra_ref_when_combined(self):
        folder = write_files(self.tmp / "tf", {"main.tf": '''
resource "aws_sqs_queue" "a" { name = "a" }
resource "aws_sqs_queue" "b" { name = "b" }
resource "aws_sqs_queue" "gone" { name = "gone" }
'''})
        plan = mkplan(
            [rc("aws_sqs_queue.a", {"name": "a"}), rc("aws_sqs_queue.b", {"name": "b"})],
            [cfg("aws_sqs_queue.a", {"name": const("a")}),
             cfg("aws_sqs_queue.b", {"name": refs("aws_sqs_queue.a")})])  # .tf には b から a への参照が無い
        raw = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "p.json", plan))
        self.assertEqual([r["address"] for r in raw["resources"]], ["aws_sqs_queue.a", "aws_sqs_queue.b"])
        np = [d for d in raw["diagnostics"] if d["code"] == "TF-PLAN-NOT-PLANNED"]
        self.assertEqual([(d["level"], d["address"]) for d in np], [("info", "")])
        self.assertIn("aws_sqs_queue.gone", np[0]["message"])
        self.assertEqual(diag_codes(raw, "TF-PLAN-EXTRA-REF"), [("aws_sqs_queue.b", "name", "info")])
        self.assertIn(("aws_sqs_queue.b", "aws_sqs_queue.a", "unevaluated"),
                      {(r["from"], r["to"], r["state"]) for r in raw["references"]})

    def test_mismatching_folder_warns(self):
        folder = write_files(self.tmp / "tf", {"main.tf": '''
resource "aws_sqs_queue" "other1" { name = "o1" }
resource "aws_sqs_queue" "other2" { name = "o2" }
resource "aws_sqs_queue" "other3" { name = "o3" }
'''})
        plan = mkplan([rc(f"aws_sns_topic.t{i}", {"name": f"t{i}"}) for i in range(3)],
                      [cfg(f"aws_sns_topic.t{i}", {"name": const(f"t{i}")}) for i in range(3)])
        raw = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "p.json", plan))
        d = [d for d in raw["diagnostics"] if d["code"] == "TF-PLAN-MISMATCH"]
        self.assertEqual([x["level"] for x in d], ["warn"])
        self.assertIn("3 of 3", d[0]["message"])
        self.assertIn("probably do not match", d[0]["message"])
        self.assertEqual({r["address"] for r in raw["resources"]}, {f"aws_sns_topic.t{i}" for i in range(3)})

    def test_matching_fixtures_do_not_warn(self):
        for name in list(CASES) + ["edge"]:
            with self.subTest(name):
                if name == "edge":
                    raw = tf_build.build_raw(EDGE, WS, plan=EDGE_PLAN)
                else:
                    raw = combined_raw(name)
                self.assertEqual(diag_codes(raw, "TF-PLAN-MISMATCH"), [])
        # 3割以下の違いは warn にしない（.tf.json など plan だけにあるブロック）
        self.assertEqual(PK.block_mismatch([{"type": "aws_x", "address": f"aws_x.r{i}"} for i in range(10)],
                                     {**{f"aws_x.r{i}": {} for i in range(10)}, "aws_x.extra": {}}), "")

    def test_destroy_plan(self):
        # m1: terraform plan -destroy。prior_state の値から、生きているものとして足さない
        deleted = rc("aws_sqs_queue.q", None, actions=("delete",))
        deleted["change"]["before"] = {"name": "q"}
        prior = {"format_version": "1.0", "values": {"root_module": {"resources": [
            {"address": "aws_sqs_queue.q", "mode": "managed", "type": "aws_sqs_queue", "name": "q",
             "values": {"name": "q"}, "sensitive_values": {}}]}}}
        plan = mkplan([deleted], [cfg("aws_sqs_queue.q", {"name": const("q")})], prior=prior)
        raw = plan_only(self.tmp, plan)
        self.assertEqual([(r["address"], r["enabled"]) for r in raw["resources"]], [("aws_sqs_queue.q", False)])
        self.assertEqual([(d["level"], d["address"]) for d in raw["diagnostics"] if d["code"] == "TF-PLAN-DESTROY"],
                         [("warn", "")])
        # .tf と合わせても同じ
        folder = write_files(self.tmp / "tf", {"main.tf": 'resource "aws_sqs_queue" "q" { name = "q" }\n'})
        comb = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "d.json", plan))
        self.assertEqual([(r["address"], r["enabled"]) for r in comb["resources"]], [("aws_sqs_queue.q", False)])
        self.assertEqual(len(diag_codes(comb, "TF-PLAN-DESTROY")), 1)

    def test_partly_destroyed_plan_is_info(self):
        gone = rc("aws_sqs_queue.gone", None, actions=("delete",))
        forgotten = rc("aws_sqs_queue.forgotten", None, actions=("forget",))
        deposed = rc("aws_sqs_queue.keep", None, actions=("delete",), deposed="abc123")
        plan = mkplan([rc("aws_sqs_queue.keep", {"name": "k"}), gone, forgotten, deposed],
                      [cfg("aws_sqs_queue.keep", {"name": const("k")})])
        raw = plan_only(self.tmp, plan)
        self.assertEqual([(r["address"], r["enabled"]) for r in raw["resources"]], [("aws_sqs_queue.keep", True)])
        self.assertEqual(diag_codes(raw, "TF-PLAN-DESTROY"), [("", "", "info")])
        self.assertIn("2 resource(s)", [d for d in raw["diagnostics"] if d["code"] == "TF-PLAN-DESTROY"][0]["message"])

    def test_root_on_another_drive_is_the_name_only_in_both_modes(self):
        # m4: ドライブが違うと相対パスにできない。plan だけでも .tf と合わせても、名前だけ（絶対パスは書かない）
        base = self.tmp / "base"
        base.mkdir()
        folder = write_files(self.tmp / "tf-folder", {"main.tf": 'resource "aws_sqs_queue" "q" { name = "q" }\n'})
        plan = write_json(self.tmp / "p.json", mkplan([rc("aws_sqs_queue.q", {"name": "q"})],
                                                       [cfg("aws_sqs_queue.q", {"name": const("q")})]))
        real = os.path.relpath
        start = str(base.resolve())

        def other_drive(path, start_=None):
            if start_ is not None and str(start_) == start:
                raise ValueError("path is on mount 'D:', start on mount 'C:'")
            return real(path, start_)

        with mock.patch.object(os.path, "relpath", other_drive):
            only = tf_build.build_from_plan(plan, base)
            comb = tf_build.build_raw(folder, base, plan=plan)
            tf_only = tf_build.build_raw(folder, base)
        self.assertEqual((only["root"], comb["root"], tf_only["root"]), ("p.json", "tf-folder", "tf-folder"))
        for raw in (only, comb, tf_only):
            self.assertEqual(diag_codes(raw, "TF-ROOT-OTHER-DRIVE"), [("", "", "info")])
            self.assertNotIn(str(self.tmp), tf_build.dump(raw))
            self.assertNotIn(self.tmp.as_posix(), tf_build.dump(raw))
            assert_valid(self, raw)

    def test_tfjson_outside_the_input_folder_is_not_read(self):
        outer = self.tmp / "outer"
        write_files(outer, {"x.tf.json": json.dumps({"resource": {"aws_sqs_queue": {"hidden": {"name": "h"}}}})})
        folder = write_files(self.tmp / "tf", {"main.tf": 'module "m" {\n  source = "../outer"\n}\n'})
        plan = mkplan([rc("module.m.aws_sqs_queue.hidden", {"name": "h"}, module_address="module.m")],
                      [], root_extra={"module_calls": {"m": {"source": "../outer", "module": {"resources": [
                          cfg("aws_sqs_queue.hidden", {"name": const("h")})]}}}})
        raw = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "p.json", plan))
        hidden = res_of(raw, "module.m.aws_sqs_queue.hidden")
        self.assertNotEqual(hidden["file"], "../outer/x.tf.json")
        self.assertNotIn("..", hidden["file"])
        self.assertEqual(len(diag_codes(raw, "TF-PLAN-PATH-OUTSIDE")), 1)


if __name__ == "__main__":
    unittest.main()
