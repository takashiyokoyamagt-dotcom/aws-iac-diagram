"""plan JSON: sensitive の位置の値を書かない（B1・B2・M1。plan/masking.py・combine.py・values.py）。
.tf と合わせるとき、plan だけのとき、第三者レビューの2周目（destroy・count 0・root の true・フラグの合流）。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import res_of
from support.paths import PLANS, WS
from support.tf_plan import (
    CASES,
    SECRET,
    SECRET2,
    TempTestCase,
    assert_valid_no_errors as assert_valid,
    cfg,
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
from aws_iac_diagram.adapters.terraform.plan import (  # noqa: E402
    combine as PC,
    masking as PM,
    reader as PD,
    values as PV,
)


class CombinedSensitiveTest(TempTestCase):
    """B1・B2: .tf と合わせるとき、plan が sensitive とした位置の値は、.tf の評価で出ても書かない。"""

    TF = '''
variable "db_password" { type = string }
variable "cfg" { type = map(string) }
resource "aws_db_instance" "main" {
  identifier = "x"
  password   = var.db_password
  tags       = var.cfg
}
resource "aws_secretsmanager_secret_version" "v" {
  secret_id     = "s"
  secret_string = jsonencode({ pw = var.db_password })
}
resource "aws_x" "c" {
  note     = "pw-${var.db_password}"
  list     = [var.db_password, "ok"]
  settings {
    token = var.db_password
    keep  = "visible"
  }
}
'''

    def plan(self):
        pw = {"password": SECRET}
        return mkplan(
            [rc("aws_db_instance.main", {"identifier": "x", "password": SECRET, "tags": {"token": SECRET2, "e": "env"}},
                {"password": True, "tags": {"token": True}}),
             rc("aws_secretsmanager_secret_version.v", {"secret_id": "s", "secret_string": json.dumps({"pw": SECRET})},
                {"secret_string": True}),
             rc("aws_x.c", {"note": "pw-" + SECRET, "list": [SECRET, "ok"],
                            "settings": [{"token": SECRET, "keep": "visible"}]},
                {"note": True, "list": [True, False], "settings": [{"token": True}]})],
            [cfg("aws_db_instance.main", {"identifier": const("x"), "password": refs("var.db_password"),
                                          "tags": refs("var.cfg")}),
             cfg("aws_secretsmanager_secret_version.v", {"secret_id": const("s"),
                                                         "secret_string": refs("var.db_password")}),
             cfg("aws_x.c", {"note": refs("var.db_password"), "list": refs("var.db_password"),
                             "settings": [{"token": refs("var.db_password"), "keep": const("visible")}]})],
            variables={"db_password": {"value": SECRET}, "cfg": {"value": {"token": SECRET2, "e": "env"}}})

    def test_variable_not_declared_sensitive_does_not_leak(self):
        folder = write_files(self.tmp / "tf", {"main.tf": self.TF})
        plan = write_json(self.tmp / "plan.json", self.plan())
        raw = tf_build.build_raw(folder, self.tmp, plan=plan)
        assert_valid(self, raw)
        text = tf_build.dump(raw)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(SECRET2, text)
        main = props_of(raw, "aws_db_instance.main")
        self.assertEqual(main["identifier"], "x")
        self.assertEqual(main["password"], unk())
        self.assertEqual(main["tags"], {"token": unk(), "e": "env"})  # sensitive の位置だけ伏せる
        self.assertEqual(props_of(raw, "aws_secretsmanager_secret_version.v")["secret_string"], unk())  # $json 全体
        c = props_of(raw, "aws_x.c")
        self.assertEqual(c["note"], unk())  # $concat も全体
        self.assertEqual(c["list"], [unk(), "ok"])
        self.assertEqual(c["settings"], [{"token": unk(), "keep": "visible"}])
        self.assertEqual(sorted(p for a, p, _ in diag_codes(raw, "TF-PLAN-SENSITIVE")),
                         ["list[0]", "note", "password", "secret_string", "settings[0].token", "tags.token"])
        # plan だけのときと同じ値
        only = plan_only(self.tmp, self.plan())
        for a in ("aws_db_instance.main", "aws_secretsmanager_secret_version.v", "aws_x.c"):
            self.assertEqual(props_of(raw, a), props_of(only, a), a)
        # --input の plan JSON だけでも CLI の結果は同じ（ファイルにも書かない）
        out = self.tmp / "raw.json"
        self.assertEqual(self.run_main(["--input", str(folder), "--plan", str(plan), "--out", str(out),
                                        "--root-base", str(self.tmp)])[0], 0)
        self.assertNotIn(SECRET, out.read_text(encoding="utf-8"))

    def test_reference_at_sensitive_position_is_kept(self):
        # 値を持たない $res は、sensitive の位置でも消さない（参照は図に要る）
        folder = write_files(self.tmp / "tf", {"main.tf": '''
resource "aws_sqs_queue" "q" { name = "q" }
resource "aws_db_instance" "main" { password = aws_sqs_queue.q.arn }
'''})
        plan = mkplan(
            [rc("aws_sqs_queue.q", {"name": "q"}, unknown={"arn": True}),
             rc("aws_db_instance.main", {"password": None}, {"password": True}, {"password": True})],
            [cfg("aws_sqs_queue.q", {"name": const("q")}),
             cfg("aws_db_instance.main", {"password": refs("aws_sqs_queue.q.arn", "aws_sqs_queue.q")})])
        raw = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "p.json", plan))
        self.assertEqual(props_of(raw, "aws_db_instance.main")["password"], {"$res": "aws_sqs_queue.q", "attr": "arn"})

    def test_json_fill_under_sensitive_attribute(self):
        # B2: .tf では file() の値が決まらない。sensitive の属性の JSON の中を、plan の値で埋めない
        folder = write_files(self.tmp / "tf", {"main.tf": '''
resource "aws_db_instance" "main" {
  identifier = "x"
  password   = file("s.txt")
}
resource "aws_secretsmanager_secret_version" "v" {
  secret_id     = "s"
  secret_string = jsonencode({ pw = file("s.txt") })
}
resource "aws_secretsmanager_secret_version" "w" {
  secret_id     = "s"
  secret_string = jsonencode({ pw = file("s.txt"), other = file("t.txt") })
}
''', "s.txt": "x", "t.txt": "y"})
        plan = mkplan(
            [rc("aws_db_instance.main", {"identifier": "x", "password": "FILE-SECRET-LEAK"}, {"password": True}),
             rc("aws_secretsmanager_secret_version.v", {"secret_id": "s",
                                                         "secret_string": json.dumps({"pw": "FILE-SECRET-LEAK"})},
                {"secret_string": True}),
             rc("aws_secretsmanager_secret_version.w", {"secret_id": "s",
                                                         "secret_string": json.dumps({"pw": "FILE-SECRET-LEAK",
                                                                                      "other": "ok-value"})},
                {"secret_string": True}, {"secret_string": True})],
            [cfg("aws_db_instance.main", {"identifier": const("x"), "password": {}}),
             cfg("aws_secretsmanager_secret_version.v", {"secret_id": const("s"), "secret_string": {}}),
             cfg("aws_secretsmanager_secret_version.w", {"secret_id": const("s"), "secret_string": {}})])
        raw = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "p.json", plan))
        self.assertNotIn("FILE-SECRET-LEAK", tf_build.dump(raw))
        self.assertNotIn("ok-value", tf_build.dump(raw))  # sensitive + unknown の位置も、JSON の中は埋めない
        self.assertEqual(props_of(raw, "aws_secretsmanager_secret_version.v")["secret_string"], unk())
        # 比べるために: sensitive でなければ、同じ形の JSON の中を plan の値で埋める
        plan["resource_changes"][1]["change"]["after_sensitive"] = {}
        raw = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "p2.json", plan))
        self.assertEqual(props_of(raw, "aws_secretsmanager_secret_version.v")["secret_string"],
                         {"$json": {"pw": "FILE-SECRET-LEAK"}})

    def test_walk_fill_json_directly(self):
        tv = {"$json": {"pw": unk("file() is not evaluated")}}
        pv = json.dumps({"pw": "FAKE-FILL"})
        fill = {"secret_string.pw"}
        filled: list = []
        self.assertEqual(PC._walk_fill(tv, pv, None, None, "secret_string", fill, filled),
                         {"$json": {"pw": "FAKE-FILL"}})
        for pu, ps in ((None, True), (None, [True]), (True, None)):
            filled = []
            self.assertEqual(PC._walk_fill(tv, pv, pu, ps, "secret_string", fill, filled), tv)
            self.assertEqual(filled, [])

    def test_mask_sensitive_shapes(self):
        found: list = []
        # 形が合わない印（値は dict なのに印は list など）は全体を伏せる。ブロックの数が違うときも
        self.assertEqual(PM.mask_sensitive({"a": "x"}, [True], "o", found), unk())
        self.assertEqual(PM.mask_sensitive([{"k": "x"}], [{}, {"k": True}], "b", found), unk())
        self.assertEqual(PM.mask_sensitive("x", {"a": True}, "s", found), unk())
        self.assertEqual(found, ["o", "b", "s"])
        # 印が無い・すべて false のときは何もしない
        self.assertEqual(PM.mask_sensitive({"a": "x"}, {"a": False}, "", []), {"a": "x"})
        self.assertEqual(PM.mask_sensitive({"a": "x"}, None, "", []), {"a": "x"})


class SensitivePlanOnlyTest(TempTestCase):
    """plan JSON だけのとき、sensitive の位置の値は、どんな形でも書かない（M1）。"""

    def one(self, after, sens, exprs, unknown=None, **kw):
        plan = mkplan([rc("aws_x.a", after, sens, unknown)], [cfg("aws_x.a", exprs)], **kw)
        raw = plan_only(self.tmp, plan)
        self.assertNotIn(SECRET, tf_build.dump(raw))
        assert_valid(self, raw)
        return props_of(raw, "aws_x.a"), raw

    def test_partially_sensitive_map_list_object(self):
        p, raw = self.one({"m": {"a": SECRET, "b": "ok"}, "o": {"l": [SECRET, "x"]}, "l": [SECRET, "y"]},
                          {"m": {"a": True}, "o": {"l": [True, False]}, "l": [True, False]},
                          {"m": const({"a": SECRET, "b": "ok"}), "o": const({"l": [SECRET, "x"]}),
                           "l": const([SECRET, "y"])})
        self.assertEqual(p["m"], {"a": unk(), "b": "ok"})
        self.assertEqual(p["o"], {"l": [unk(), "x"]})
        self.assertEqual(p["l"], [unk(), "y"])
        self.assertEqual(sorted(x[1] for x in diag_codes(raw, "TF-PLAN-SENSITIVE")), ["l[0]", "m.a", "o.l[0]"])

    def test_sensitive_and_unknown_at_the_same_position(self):
        # 両方の印がある位置は sensitive（値が分からなくても、sensitive の印が先）
        p, raw = self.one({"o": None}, {"o": True}, {"o": refs("aws_x.a")}, {"o": True})
        self.assertEqual(p["o"], unk())
        self.assertIn(("aws_x.a", "o", "info"), diag_codes(raw, "TF-PLAN-SENSITIVE"))
        self.assertEqual(diag_codes(raw, "TF-PLAN-UNKNOWN"), [])

    def test_shape_mismatched_sensitivity(self):
        # m3: 値は dict で印は list（や、値は文字列で印は dict）でも伏せる
        p, _ = self.one({"o": {"a": SECRET}, "s": SECRET}, {"o": [True], "s": {"a": True}},
                        {"o": const({"a": SECRET}), "s": const(SECRET)})
        self.assertEqual(p, {"o": unk(), "s": unk()})
        self.assertEqual(PV.conv({"a": SECRET}, None, [True]), PV.SENS)
        self.assertEqual(PV.conv([SECRET], None, {"0": True}), PV.SENS)
        self.assertEqual(PV.conv({"a": SECRET, "b": "ok"}, None, {"a": True}), {"a": PV.SENS, "b": "ok"})

    def test_whole_static_block_marked_sensitive(self):
        # m2: 入れ子のブロックの全体が after_sensitive: true（configuration にある静的なブロック）
        p, raw = self.one({"blk": [{"k": SECRET}], "ok": "v"}, {"blk": True},
                          {"blk": [{"k": const(SECRET)}], "ok": const("v")})
        self.assertEqual(p, {"blk": unk(), "ok": "v"})
        self.assertIn(("aws_x.a", "blk", "info"), diag_codes(raw, "TF-PLAN-SENSITIVE"))
        # ブロックの一部の項目だけ: 印のある項目だけを伏せる
        p, _ = self.one({"blk": [{"k": SECRET}, {"k": "shown"}]}, {"blk": [{"k": True}, {}]},
                        {"blk": [{"k": const(SECRET)}, {"k": const("shown")}]})
        self.assertEqual(p["blk"], [{"k": unk()}, {"k": "shown"}])

    def test_dynamic_block_sensitive(self):
        p, _ = self.one({"ingress": [{"cidr": SECRET}]}, {"ingress": True}, {})
        self.assertEqual(p["ingress"], unk())

    def test_json_string_attribute(self):
        p, _ = self.one({"o": json.dumps({"p": SECRET})}, {"o": True}, {"o": const("x")})
        self.assertEqual(p["o"], unk())

    def test_sensitive_in_prior_state_data(self):
        # data は prior_state の values（と sensitive_values）から。sensitive_values の位置は使わない
        prior = {"format_version": "1.0", "values": {"root_module": {"resources": [
            {"address": "data.aws_ssm_parameter.p", "mode": "data", "type": "aws_ssm_parameter", "name": "p",
             "values": {"name": "/n", "value": SECRET, "tags": {"k": SECRET2, "j": "v"}},
             "sensitive_values": {"value": True, "tags": {"k": True}}}]}}}
        plan = mkplan([], [cfg("data.aws_ssm_parameter.p", {"name": const("/n"), "value": const(SECRET),
                                                              "tags": const({"k": SECRET2, "j": "v"})})],
                      prior=prior)
        raw = plan_only(self.tmp, plan)
        self.assertNotIn(SECRET, tf_build.dump(raw))
        self.assertNotIn(SECRET2, tf_build.dump(raw))
        self.assertEqual(props_of(raw, "data.aws_ssm_parameter.p"),
                         {"name": "/n", "value": unk(), "tags": {"k": unk(), "j": "v"}})

    def test_sensitive_in_planned_values_only_resource(self):
        planned = {"root_module": {"resources": [
            {"address": "aws_y.b", "mode": "managed", "type": "aws_y", "name": "b", "values": {"k": SECRET},
             "sensitive_values": {"k": True}}]}}
        raw = plan_only(self.tmp, mkplan([], [cfg("aws_y.b", {"k": const(SECRET)})], planned=planned))
        self.assertNotIn(SECRET, tf_build.dump(raw))
        self.assertEqual(props_of(raw, "aws_y.b"), {"k": unk()})

    def test_sensitive_target_is_not_used_to_build_references(self):
        # 先の属性が sensitive のときは、その値と同じ（や、含む）値を $res・$concat にしない（値を比べに使わない）
        plan = mkplan(
            [rc("aws_x.src", {"pw": "fake-pw-1234"}, {"pw": True}),
             rc("aws_x.use", {"same": "fake-pw-1234", "part": "a-fake-pw-1234-b"})],
            [cfg("aws_x.src", {"pw": const("fake-pw-1234")}),
             cfg("aws_x.use", {"same": refs("aws_x.src.pw"), "part": refs("aws_x.src.pw")})])
        raw = plan_only(self.tmp, plan)
        use = props_of(raw, "aws_x.use")
        self.assertEqual(use, {"same": "fake-pw-1234", "part": "a-fake-pw-1234-b"})  # $res・$concat にならない
        self.assertEqual(props_of(raw, "aws_x.src"), {"pw": unk()})
        self.assertEqual({(r["from"], r["to"], r["state"]) for r in raw["references"]},
                         {("aws_x.use", "aws_x.src", "unevaluated")})
        inst = PD.Inst("aws_x.src", "managed", "aws_x", {"pw": "v", "n": "w", "m": {"a": "x"}}, {},
                      {"pw": True, "m": {"a": True}})
        self.assertIs(inst.value_of("pw"), PV.ABSENT)
        self.assertIs(inst.value_of("m"), PV.ABSENT)
        self.assertEqual(inst.value_of("n"), "w")

    def test_no_pseudo_in_plan_only_output(self):
        for name in list(CASES) + ["edge"]:
            with self.subTest(name):
                text = tf_build.dump(tf_build.build_from_plan(PLANS / f"{name}.json", WS))
                self.assertNotIn("$pseudo", text)
                self.assertNotIn('"$az"', text)


class SensitiveEdgeCasesTest(TempTestCase):
    """レビューの2回目: destroy・count 0・root の true・印の合わせ方・評価の誤りの文に値が入る場合。"""

    LEAK = "ZZ-LEAK-1"
    LEAK2 = "ZZ-LEAK-2"

    def assert_clean(self, raw):
        assert_valid(self, raw)
        text = tf_build.dump(raw)
        self.assertNotIn(self.LEAK, text)
        self.assertNotIn(self.LEAK2, text)

    def destroy_plan(self, in_change: bool, in_prior: bool):
        deleted = rc("aws_x.s", None, actions=("delete",))
        deleted["change"]["before"] = {"value": self.LEAK, "name": "n"}
        deleted["change"]["after_sensitive"] = False
        deleted["change"]["before_sensitive"] = {"value": True} if in_change else {}
        lit = rc("aws_x.lit", None, actions=("delete",))
        lit["change"]["before"] = {"value": self.LEAK2}
        lit["change"]["before_sensitive"] = {"value": True} if in_change else {}
        flags = {"value": True} if in_prior else {}
        prior = {"format_version": "1.0", "values": {"root_module": {"resources": [
            {"address": "aws_x.s", "mode": "managed", "type": "aws_x", "name": "s",
             "values": {"value": self.LEAK, "name": "n"}, "sensitive_values": flags},
            {"address": "aws_x.lit", "mode": "managed", "type": "aws_x", "name": "lit",
             "values": {"value": self.LEAK2}, "sensitive_values": flags}]}}}
        return mkplan([deleted, lit],
                      [cfg("aws_x.s", {"value": refs("var.pw"), "name": const("n")}),
                       cfg("aws_x.lit", {"value": const(self.LEAK2)})],
                      prior=prior, variables={"pw": {"value": self.LEAK}})

    def test_destroy_plan_keeps_sensitivity_plan_only_and_combined(self):
        folder = write_files(self.tmp / "tf", {"main.tf": '''
variable "pw" { type = string }
resource "aws_x" "s" {
  value = var.pw
  name  = "n"
}
resource "aws_x" "lit" { value = "ZZ-LEAK-2" }
'''})
        for in_change, in_prior in ((True, True), (True, False), (False, True)):
            with self.subTest(change=in_change, prior=in_prior):
                plan = self.destroy_plan(in_change, in_prior)
                only = plan_only(self.tmp, plan)
                self.assert_clean(only)
                self.assertEqual(props_of(only, "aws_x.lit"), {"value": unk()})
                comb = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "d.json", plan))
                self.assert_clean(comb)
                self.assertEqual([(r["address"], r["enabled"]) for r in comb["resources"]],
                                 [("aws_x.lit", False), ("aws_x.s", False)])
                self.assertEqual(props_of(comb, "aws_x.lit"), {"value": unk()})
                s = props_of(comb, "aws_x.s")
                self.assertEqual(s["value"], unk())
                self.assertEqual(s["name"], "n")
                self.assertIn(("aws_x.lit", "value", "info"), diag_codes(comb, "TF-PLAN-SENSITIVE"))

    def test_count_zero_resource_does_not_take_plan_variables(self):
        # MINOR-4: インスタンスが無い（count 0）と sensitive の印が無い。plan の変数から来た値は使わず、リテラルだけ残す
        folder = write_files(self.tmp / "tf", {"main.tf": '''
variable "pw" { type = string }
resource "aws_x" "off" {
  count = 0
  value = var.pw
  text  = "pw=${var.pw}"
  other = "lit"
  blk {
    k = var.pw
    j = 7
  }
}
'''})
        plan = mkplan([], [cfg("aws_x.off", {"value": refs("var.pw"), "text": refs("var.pw"), "other": const("lit"),
                                             "blk": [{"k": refs("var.pw"), "j": const(7)}]},
                           count_expression=refs("local.zero"))],
                      variables={"pw": {"value": self.LEAK}})
        only = plan_only(self.tmp, plan)
        self.assertNotIn(self.LEAK, tf_build.dump(only))
        comb = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "o.json", plan))
        self.assert_clean(comb)
        r = res_of(comb, "aws_x.off")
        self.assertFalse(r["enabled"])
        why = {"$unknown": PM.NOT_CREATED_REASON}
        self.assertEqual(r["props"], {"value": why, "text": why, "other": "lit", "blk": [{"k": why, "j": 7}]})
        self.assertEqual(sorted(p for _, p, _ in diag_codes(comb, "TF-PLAN-LITERAL-ONLY")),
                         ["blk[0].k", "text", "value"])

    def test_evaluation_error_text_with_a_value_is_dropped(self):
        # MINOR-2: lookup()・parseint() の誤りの文に値が入る。sensitive の位置の診断は消し、$unknown も sensitive の理由にする
        folder = write_files(self.tmp / "tf", {"main.tf": '''
variable "m" { type = map(string) }
variable "pw" { type = string }
resource "aws_x" "a" { value = lookup(var.m, var.pw) }
resource "aws_x" "b" { value = parseint(var.pw, 10) }
'''})
        alone = tf_build.build_raw(folder, self.tmp, var_args=[("var", f"pw={self.LEAK}"), ("var", 'm={k="v"}')])
        self.assertIn(self.LEAK, tf_build.dump(alone))  # 前提: .tf だけだと誤りの文に値が入る
        plan = mkplan([rc("aws_x.a", {"value": "q"}, {"value": True}), rc("aws_x.b", {"value": 3}, {"value": True})],
                      [cfg("aws_x.a", {"value": refs("var.m", "var.pw")}), cfg("aws_x.b", {"value": refs("var.pw")})],
                      variables={"m": {"value": {"k": "v"}}, "pw": {"value": self.LEAK}})
        comb = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "p.json", plan))
        self.assert_clean(comb)
        self.assertEqual([props_of(comb, a) for a in ("aws_x.a", "aws_x.b")], [{"value": unk()}] * 2)
        self.assertEqual(diag_codes(comb, "TF-EVAL-ERROR"), [])
        # $unknown（理由の文に値が入りうる）も、sensitive の位置では sensitive の理由に置き換える
        found: list = []
        self.assertEqual(PM.mask_sensitive({"$unknown": f"bad '{self.LEAK}'"}, True, "v", found), unk())
        self.assertEqual(found, ["v"])
        self.assertEqual(PM.mask_sensitive({"$res": "aws_x.a", "attr": "id"}, True, "v", []),
                         {"$res": "aws_x.a", "attr": "id"})

    def test_root_after_sensitive_true(self):
        # MINOR-3A: change.after_sensitive が true（すべて sensitive）。どちらのモードでもスキーマに合う
        folder = write_files(self.tmp / "tf", {"main.tf": '''
variable "pw" { type = string }
resource "aws_x" "a" {
  value = var.pw
  name  = "n"
  blk {
    k = var.pw
  }
}
'''})
        plan = mkplan([rc("aws_x.a", {"value": self.LEAK, "name": "n", "blk": [{"k": self.LEAK}]}, True)],
                      [cfg("aws_x.a", {"value": const(self.LEAK), "name": const("n"),
                                       "blk": [{"k": const(self.LEAK)}]})],
                      variables={"pw": {"value": self.LEAK}})
        only = plan_only(self.tmp, plan)
        self.assert_clean(only)
        self.assertEqual(props_of(only, "aws_x.a"), {"value": unk(), "name": unk(), "blk": unk()})
        comb = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "t.json", plan))
        self.assert_clean(comb)
        self.assertEqual(props_of(comb, "aws_x.a"), {"value": unk(), "name": unk(), "blk": unk()})
        self.assertIs(PD.Inst("a.b", "managed", "a", {"k": "v"}, {}, True).value_of("k"), PV.ABSENT)

    def test_flags_are_merged_across_sources(self):
        # MINOR-3B: resource_changes の after_sensitive が空でも、planned_values・prior_state・before_sensitive の印は使う
        for where in ("planned", "prior", "before"):
            with self.subTest(where=where):
                change = rc("aws_x.a", {"value": self.LEAK, "tags": {"t": self.LEAK2, "u": "ok"}}, {})
                flag = {"value": True, "tags": {"t": True}}
                res = {"address": "aws_x.a", "mode": "managed", "type": "aws_x", "name": "a",
                       "values": {"value": self.LEAK, "tags": {"t": self.LEAK2, "u": "ok"}}, "sensitive_values": flag}
                kw = {}
                if where == "planned":
                    kw["planned"] = {"root_module": {"resources": [res]}}
                elif where == "prior":
                    kw["prior"] = {"format_version": "1.0", "values": {"root_module": {"resources": [res]}}}
                else:
                    change["change"]["before_sensitive"] = flag
                plan = mkplan([change], [cfg("aws_x.a", {"value": const(self.LEAK), "tags": const(
                    {"t": self.LEAK2, "u": "ok"})})], **kw)
                raw = plan_only(self.tmp, plan)
                self.assert_clean(raw)
                self.assertEqual(props_of(raw, "aws_x.a"), {"value": unk(), "tags": {"t": unk(), "u": "ok"}})
        self.assertEqual(PV.merge_flags({"a": True}, {"b": [False, True]}), {"a": True, "b": [False, True]})
        self.assertEqual(PV.merge_flags({}, None), {})
        self.assertIs(PV.merge_flags(False, True), True)
        self.assertIs(PV.merge_flags({"a": True}, [True]), True)  # 形が違う: 全体
        self.assertEqual(PV.merge_flags([True], [False, False, True]), [True, False, True])

    def test_empty_strings_in_names_are_exit_2(self):
        # MINOR-6: type・address が空の文字列は、スキーマに合わない IR になるので PlanError
        base = mkplan([], [cfg("aws_x.a", {"k": const(1)})])
        for field, path, value in (("type", "configuration.root_module.resources[0].type", ""),
                                   ("type", "configuration.root_module.resources[0].type", None),
                                   ("address", "configuration.root_module.resources[0].address", "")):
            with self.subTest(field=field, value=value):
                bad = json.loads(json.dumps(base))
                bad["configuration"]["root_module"]["resources"][0][field] = value
                f = write_json(self.tmp / f"{field}.json", bad)
                code, _, err = self.run_main(["--input", str(f), "--out", str(self.tmp / "o.json"),
                                              "--root-base", str(self.tmp)])
                self.assertEqual(code, 2)
                self.assertIn("unexpected structure at " + path, err)


class LiteralOnlyTest(TempTestCase):
    """作られない（count 0）リソースは、.tf の値のうち plan の constant_value と同じリテラルだけを残す（masking.literal_only）。

    SensitiveEdgeCasesTest.test_count_zero_resource_does_not_take_plan_variables は「同じ値は残る」だけを確かめていた。
    .tf と plan の値が食い違うもの（値が違う、型が違う）を残さないことは、ここで確かめる（R5 のレビューの指摘）。
    """

    def test_literal_that_differs_from_the_plan_constant_is_not_kept(self):
        folder = write_files(self.tmp / "tf", {"main.tf": '''
resource "aws_x" "off" {
  count = 0
  same  = "lit"
  diff  = "tf-side"
  num   = 7
  flag  = 1
}
'''})
        plan = mkplan([], [cfg("aws_x.off", {"same": const("lit"), "diff": const("plan-side"), "num": const(7),
                                             "flag": const(True)},
                           count_expression=refs("local.zero"))])
        comb = tf_build.build_raw(folder, self.tmp, plan=write_json(self.tmp / "o.json", plan))
        r = res_of(comb, "aws_x.off")
        self.assertFalse(r["enabled"])
        why = {"$unknown": PM.NOT_CREATED_REASON}
        # 同じ値と同じ型は残る。値が違うもの、型が違うもの（1 と True は == だが別の型）は残さない
        self.assertEqual(r["props"], {"same": "lit", "diff": why, "num": 7, "flag": why})
        self.assertEqual(sorted(p for _, p, _ in diag_codes(comb, "TF-PLAN-LITERAL-ONLY")), ["diff", "flag"])

    def test_literal_only_directly(self):
        found: list = []
        out = PM.literal_only({"a": "x", "b": "y", "c": [1, 2], "d": {"k": "v"}},
                              {"a": "x", "b": "z", "c": [1, 3], "d": {"k": "v"}}, "", found)
        why = {"$unknown": PM.NOT_CREATED_REASON}
        self.assertEqual(out, {"a": "x", "b": why, "c": [1, why], "d": {"k": "v"}})
        self.assertEqual(sorted(found), ["b", "c[1]"])


if __name__ == "__main__":
    unittest.main()
