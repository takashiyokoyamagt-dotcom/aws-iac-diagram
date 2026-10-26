"""Terraform アダプタの plan JSON の入力（scripts/aws_iac_diagram/adapters/terraform/plan/ と adapt_tf.py の --plan。フェーズ2 の手順4）のテスト。

plan JSON の fixture（aws-iac-diagram-workspace/fixtures/tf-plan/）は、tools/make_plan_json.py で本物の terraform と
moto（ローカルの AWS モック）から作ったもの。テストは terraform を動かさず、コミットした plan JSON を読むだけ。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "aws-iac-diagram" / "scripts"
WS = ROOT / "aws-iac-diagram-workspace"
FIXTURES = WS / "fixtures" / "tf"
PLANS = WS / "fixtures" / "tf-plan"
sys.path.insert(0, str(SCRIPTS))
import validate_ir as v  # noqa: E402
import adapt_tf  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402
from aws_iac_diagram.adapters.terraform.addresses import block_address  # noqa: E402
from aws_iac_diagram.adapters.terraform.plan import (  # noqa: E402
    addresses as PA,
    combine as PC,
    consistency as PK,
    masking as PM,
    read as PR,
    reader as PD,
    values as PV,
)
from aws_iac_diagram.core import ir_raw  # noqa: E402

# plan JSON → (.tf のフォルダ, 正解 IR, plan を作ったときの変数のファイル)
CASES = {
    "three-tier.dev": ("three-tier", "three-tier", ["env/dev.tfvars"]),
    "three-tier.prod": ("three-tier", None, ["env/prod.tfvars"]),
    "serverless-api": ("serverless-api", "serverless-api", []),
    "vpc-endpoints": ("vpc-endpoints", "vpc-endpoints", []),
    "rag": ("rag", "rag", []),
    "three-tier-modules": ("three-tier-modules", "three-tier-modules", []),
}
EDGE = PLANS / "edge"
EDGE_PLAN = PLANS / "edge.json"

# plan JSON だけでは出ない参照（.tf の active の参照の (from, to) の組のうち、plan だけの IR に無いもの）と理由。
# どれも plan JSON の configuration に式の形が無いことによる（ir-schema.md の 7.3「plan JSON の参照」）
LOST_IN_PLAN_ONLY = {
    "three-tier-modules": {
        # dynamic ブロック（alb モジュールのリスナーの default_action）は configuration に出ない
        ('module.alb.aws_lb_listener.this["http"]', 'module.alb.aws_lb_target_group.this["app"]'),
        # locals を通した値（vpc モジュールの local.vpc_id、local.nat_gateway_ips、alb の local.vpc_id、
        # rds の local.db_subnet_group_name）は、plan JSON に locals の式が無いのでたどれない
        ('module.alb.aws_vpc_security_group_egress_rule.this["all"]', "module.vpc.aws_vpc.this[0]"),
        ("module.db.module.db_instance.aws_db_instance.this[0]", "module.vpc.aws_db_subnet_group.database[0]"),
        ("module.vpc.aws_internet_gateway.this[0]", "module.vpc.aws_vpc.this[0]"),
        ("module.vpc.aws_nat_gateway.this[0]", "module.vpc.aws_eip.nat[0]"),
        ("module.vpc.aws_route_table.database[0]", "module.vpc.aws_vpc.this[0]"),
        ("module.vpc.aws_route_table.private[0]", "module.vpc.aws_vpc.this[0]"),
        ("module.vpc.aws_route_table.public[0]", "module.vpc.aws_vpc.this[0]"),
    },
}


def tf_raw(name: str) -> dict:
    folder, _, var_files = CASES[name]
    root = FIXTURES / folder
    return tf_build.build_raw(root, WS, var_files=[root / f for f in var_files])


def plan_raw(name: str) -> dict:
    return tf_build.build_from_plan(PLANS / f"{name}.json", WS)


def combined_raw(name: str) -> dict:
    return tf_build.build_raw(FIXTURES / CASES[name][0], WS, plan=PLANS / f"{name}.json")


def assert_valid(test: unittest.TestCase, raw: dict) -> None:
    test.assertEqual(v.schema_errors(raw), [])
    test.assertEqual(ir_raw.semantic_errors(raw), [])
    test.assertFalse([d for d in raw["diagnostics"] if d["level"] == "error"])


def pairs(raw: dict, state: str | None = None) -> set:
    return {(r["from"], r["to"]) for r in raw["references"]
            if r["fn"] == "ref" and (state is None or r["state"] == state)}


def res_of(raw: dict, address: str) -> dict:
    return next(r for r in raw["resources"] if r["address"] == address)


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


class PlanFixtureTest(unittest.TestCase):
    def test_fixtures_have_no_local_or_secret_strings(self):
        # 偽の認証情報・moto の URL・作業用のフォルダの絶対パス・ユーザー名が入っていない（make_plan_json.py でも調べる）
        for f in sorted(PLANS.glob("*.json")):
            text = f.read_text(encoding="utf-8")
            with self.subTest(f.name):
                for bad in ("127.0.0.1", "localhost", "AWS_ACCESS_KEY", '"testing"', ":\\\\", "/Users/", "AppData"):
                    self.assertNotIn(bad, text)
                self.assertNotIn("endpoints", json.dumps(json.loads(text)["configuration"]["provider_config"]))

    def test_all_plans_produce_valid_raw(self):
        for name in list(CASES) + ["edge"]:
            with self.subTest(name):
                raw = tf_build.build_from_plan(PLANS / f"{name}.json", WS)
                assert_valid(self, raw)
                self.assertEqual(raw["root"], f"fixtures/tf-plan/{name}.json")
                self.assertEqual({r["file"] for r in raw["resources"]}, {f"{name}.json"})
                folder = EDGE if name == "edge" else FIXTURES / CASES[name][0]
                comb = tf_build.build_raw(folder, WS, plan=PLANS / f"{name}.json")
                assert_valid(self, comb)
                self.assertEqual(comb["root"], folder.relative_to(WS).as_posix())

    def test_plan_only_matches_tf(self):
        # plan JSON だけから作った raw IR と .tf から作った raw IR: address・型・enabled・module・provider・region が
        # 一致し、file は plan JSON の名前（plan JSON は .tf のファイル名を持たない）。.tf の active の参照の組
        # （from, to）は、LOST_IN_PLAN_ONLY を除いて plan の IR にもある（state・attr・path は違いうる）
        for name in CASES:
            with self.subTest(name):
                t, p = tf_raw(name), plan_raw(name)
                key = lambda r: (r["type"], r["enabled"], r.get("module"), r.get("provider"), r.get("region"))  # noqa: E731
                self.assertEqual({r["address"]: key(r) for r in p["resources"]},
                                 {r["address"]: key(r) for r in t["resources"]})
                lost = pairs(t, "active") - pairs(p)
                self.assertEqual(lost, LOST_IN_PLAN_ONLY.get(name, set()))
                # plan にだけある組は、count.index・each.* で選ぶ参照（添字が分からないので、すべてのインスタンスへの
                # unevaluated）だけ
                for r in p["references"]:
                    if (r["from"], r["to"]) not in pairs(t) and r["fn"] == "ref":
                        self.assertEqual(r["state"], "unevaluated", r)
                        self.assertRegex(r["from"], r"\[\d+\]$")
                self.assertIn("TF-PLAN-LOCALS", [d["code"] for d in p["diagnostics"]])
                self.assertFalse([d for d in p["diagnostics"] if d["level"] != "info"])

    def assert_same_or_not_created(self, c, t):
        if isinstance(c, dict) and isinstance(t, dict) and not ir_raw.is_marker(c) and not ir_raw.is_marker(t):
            self.assertEqual(list(c), list(t))
            for k in c:
                self.assert_same_or_not_created(c[k], t[k])
        elif isinstance(c, list) and isinstance(t, list):
            self.assertEqual(len(c), len(t))
            for x, y in zip(c, t):
                self.assert_same_or_not_created(x, y)
        elif c != t:
            self.assertEqual(c, {"$unknown": PM.NOT_CREATED_REASON})

    def test_combined_matches_tf(self):
        # .tf と plan JSON を合わせると、5構成では .tf の結果と resources・references が同じになる（plan の値で
        # 埋めるものも、plan だけにあるリソースも無い）。変数の値の出どころは plan
        for name in CASES:
            with self.subTest(name):
                t, c = tf_raw(name), combined_raw(name)
                # 作られない（enabled: false）リソースは、変数から来た値を使わない（リテラルの値だけ残す）ので、props の
                # 値は .tf だけのときと同じか $unknown（PM.NOT_CREATED_REASON）
                self.assertEqual([r for r in c["resources"] if r["enabled"]], [r for r in t["resources"] if r["enabled"]])
                self.assertEqual([{k: v for k, v in r.items() if k != "props"} for r in c["resources"]],
                                 [{k: v for k, v in r.items() if k != "props"} for r in t["resources"]])
                for cr, tr in zip(c["resources"], t["resources"]):
                    if not cr["enabled"]:
                        self.assert_same_or_not_created(cr["props"], tr["props"])
                self.assertEqual(c["references"], t["references"])
                self.assertEqual({k: e["source"] for k, e in c["evaluation"]["vars"].items() if "." not in k},
                                 {k: "plan" for k, e in t["evaluation"]["vars"].items() if "." not in k})
                self.assertIn("terraform plan JSON", c["evaluation"]["assumptions"][-1])
                warns = [(d["address"], d["code"]) for d in c["diagnostics"] if d["level"] != "info"]
                self.assertEqual(warns, [("aws_api_gateway_deployment.api", "TF-UNEVALUATED")] if name == "rag" else [])

    def test_expected_ir_with_plan_input(self):
        # 正解 IR の TF 側の網羅分類との突き合わせ（ExpectedIrTest）を plan JSON の入力でも行う。plan だけでは file
        # が plan JSON の名前で via が無い（要約表を使わず、Terraform が読んだ本物のモジュール）ので、型と enabled を
        # 比べる。.tf と合わせたものは file・via まで一致する
        for name, (folder, expected_name, _) in CASES.items():
            if expected_name is None:
                continue
            with self.subTest(name):
                expected = json.loads((WS / "expected" / f"{expected_name}.ir.json").read_text(encoding="utf-8"))
                want = {r["address"]: (r["type"], r["file"], r.get("rule") != "H-COND-FALSE", r.get("via"))
                        for r in expected["sources"]["tf"]["resources"]}
                p = plan_raw(name)
                self.assertEqual({r["address"]: (r["type"], r["enabled"]) for r in p["resources"]},
                                 {a: (w[0], w[2]) for a, w in want.items()})
                self.assertFalse([r for r in p["resources"] if "via" in r or "multiplicity" in r])
                c = combined_raw(name)
                self.assertEqual({r["address"]: (r["type"], r["file"], r["enabled"], r.get("via"))
                                  for r in c["resources"]}, want)

    def test_dev_and_prod(self):
        # three-tier の dev／prod の plan: 踏み台（count）が作られない／[0]
        dev, prod = plan_raw("three-tier.dev"), plan_raw("three-tier.prod")
        self.assertFalse(res_of(dev, "aws_instance.bastion")["enabled"])
        self.assertTrue(res_of(prod, "aws_instance.bastion[0]")["enabled"])
        self.assertEqual(res_of(prod, "aws_db_instance.main")["props"]["instance_class"], "db.m7g.large")
        self.assertEqual(res_of(dev, "aws_db_instance.main")["props"]["instance_class"], "db.t4g.micro")
        # 作られないブロックへの参照は、.tf と同じく添字なしの address へ
        self.assertIn(("aws_instance.bastion", "aws_security_group.bastion"), pairs(dev, "active"))

    def test_reference_placement(self):
        raw = plan_raw("three-tier.dev")
        refs = {(r["from"], r["path"], r["to"], r["attr"], r["state"]) for r in raw["references"]}
        # 値の全体が known after apply で、参照が1つ → $res（active）
        self.assertIn(("aws_lb_listener.http", "default_action[0].target_group_arn", "aws_lb_target_group.app", "arn",
                       "active"), refs)
        # スプラット（aws_subnet.public[*].id。configuration には aws_subnet.public だけ）→ インスタンスごとの $res。
        # 属性の名前は plan JSON に無いので null
        self.assertEqual(res_of(raw, "aws_lb.app")["props"]["subnets"],
                         [{"$res": "aws_subnet.public[0]", "attr": None}, {"$res": "aws_subnet.public[1]", "attr": None}])
        # count.index で選ぶ参照は、すべてのインスタンスへの unevaluated
        self.assertIn(("aws_route_table_association.private[1]", "subnet_id", "aws_subnet.private[0]", None,
                       "unevaluated"), refs)
        self.assertIn(("aws_route_table_association.private[1]", "subnet_id", "aws_subnet.private[1]", None,
                       "unevaluated"), refs)
        # 決まっている値が先の属性の値と同じ（data の JSON は $json どうしで比べる）→ $res
        self.assertIn(("aws_iam_role.task_execution", "assume_role_policy", "data.aws_iam_policy_document.ecs_tasks_assume",
                       "json", "active"), refs)

    def test_modules_from_plan(self):
        raw = plan_raw("three-tier-modules")
        refs = {(r["from"], r["path"], r["to"], r["attr"], tuple(r.get("through", ()))) for r in raw["references"]
                if r["state"] == "active"}
        # モジュールの変数・出力をたどる（through）
        self.assertIn(("module.app.aws_ecs_service.this", "load_balancer[0].target_group_arn",
                       'module.alb.aws_lb_target_group.this["app"]', "arn",
                       ("module.app.var.target_group_arn", "module.alb.output.target_groups")), refs)
        # レジストリモジュールの中の作られないブロックと data は載せない（要約表と同じ）
        self.assertFalse([r for r in raw["resources"] if r["address"].startswith("module.vpc.") and not r["enabled"]])
        self.assertFalse([r for r in raw["resources"] if ".data." in r["address"] and not
                          r["address"].startswith("module.app.")])
        # ローカルモジュールの変数の出どころ（値は書かない）
        self.assertEqual(raw["evaluation"]["vars"]["module.app.desired_count"], {"source": "default"})
        self.assertEqual(raw["evaluation"]["vars"]["module.app.vpc_id"], {"source": "argument"})
        # sensitive の値（RDS のパスワード）は使わない
        db = res_of(raw, "module.db.module.db_instance.aws_db_instance.this[0]")
        self.assertNotIn("password", db["props"])


class EdgeCaseTest(unittest.TestCase):
    """plan JSON の読み方の試験用の構成（fixtures/tf-plan/edge）。"""

    @classmethod
    def setUpClass(cls):
        cls.plan = tf_build.build_from_plan(EDGE_PLAN, WS)
        cls.comb = tf_build.build_raw(EDGE, WS, plan=EDGE_PLAN)

    def test_sensitive_values_are_not_written(self):
        # plan JSON の variables と configuration には sensitive の変数の値が平文で入るが、raw IR には出さない
        self.assertIn("not-a-real-password", EDGE_PLAN.read_text(encoding="utf-8"))
        for raw in (self.plan, self.comb):
            self.assertNotIn("not-a-real-password", tf_build.dump(raw))
            self.assertEqual(raw["evaluation"]["vars"]["db_password"], {"source": "plan", "hidden": "sensitive"})
        self.assertEqual(res_of(self.plan, "aws_ssm_parameter.p")["props"]["value"], {"$unknown": PV.SENSITIVE_REASON})
        self.assertIn(("aws_ssm_parameter.p", "TF-PLAN-SENSITIVE"),
                      [(d["address"], d["code"]) for d in self.plan["diagnostics"]])

    def test_count_for_each_modules_and_depends_on(self):
        raw = self.plan
        addrs = {r["address"]: r["enabled"] for r in raw["resources"]}
        self.assertEqual({a: e for a, e in addrs.items() if a.startswith("aws_sqs_queue.q")},
                         {'aws_sqs_queue.q["a"]': True, 'aws_sqs_queue.q["b"]': True})
        self.assertFalse(addrs["aws_sqs_queue.extra"])  # count が 0 は添字なしで enabled: false
        self.assertTrue(addrs["module.m[1].aws_sqs_queue.this"])
        self.assertFalse(addrs["module.off.aws_sqs_queue.this"])  # count が 0 の呼び出しの中も添字なし
        r = {(x["from"], x["path"], x["to"], x["state"]) for x in raw["references"]}
        self.assertIn(("aws_sqs_queue.dep", "depends_on", "module.m[1].aws_sqs_queue.this", "active"), r)
        # 条件で選ばれなかった（値が null）の参照は pruned。先は作られないブロック（添字なし）
        self.assertIn(("aws_sqs_queue.uses_extra", "kms_master_key_id", "aws_sqs_queue.extra", "pruned"), r)
        sub = [x for x in raw["references"] if x["from"] == "module.m[0].aws_sns_topic_subscription.this"
               and x["path"] == "topic_arn"]
        self.assertEqual([(x["to"], x.get("through")) for x in sub], [("aws_sns_topic.t", ["module.m[0].var.topic_arn"])])

    def test_provider_alias_region(self):
        for raw in (self.plan, self.comb):
            cert = res_of(raw, "aws_acm_certificate.cert")
            self.assertEqual((cert["provider"], cert["region"]), ("aws.use1", "us-east-1"))
            self.assertNotIn("region", res_of(raw, "aws_sns_topic.t"))

    def test_limits_of_plan_only_and_combined(self):
        p, c = self.plan, self.comb
        # locals を通した参照・each.value を通した参照・dynamic ブロックは、plan だけでは分からない（.tf と合わせると出る）
        self.assertNotIn(("aws_sns_topic_policy.pol", "aws_sns_topic.t"), {(x["from"], x["to"]) for x in p["references"]
                                                                            if x["path"] == "arn"})
        self.assertIn(("aws_sns_topic_policy.pol", "arn", "aws_sns_topic.t"),
                      {(x["from"], x["path"], x["to"]) for x in c["references"]})
        self.assertNotIn(('aws_sns_topic_subscription.s["a"]', 'aws_sqs_queue.q["a"]'), pairs(p))
        self.assertIn(('aws_sns_topic_subscription.s["a"]', 'aws_sqs_queue.q["a"]'), pairs(c, "active"))
        self.assertIn(("aws_security_group.sg", "TF-PLAN-DYNAMIC-BLOCK"), [(d["address"], d["code"])
                                                                          for d in p["diagnostics"]])
        self.assertEqual([x["from_port"] for x in res_of(p, "aws_security_group.sg")["props"]["ingress"]], [443, 80])
        # 引数の無い aws_caller_identity の account_id: plan だけでは plan の値（moto の偽のアカウント）、合わせると
        # .tf と同じ $pseudo
        self.assertEqual(res_of(p, "aws_sqs_queue.acct")["props"]["name"], "edge-123456789012")
        self.assertEqual(res_of(c, "aws_sqs_queue.acct")["props"]["name"],
                         {"$concat": ["edge-", {"$pseudo": "AWS::AccountId"}]})

    def test_combined_fills_and_tfjson(self):
        c = self.comb
        # .tf で読まない関数（file()）の値は plan の値で埋め、その診断を消す
        self.assertEqual(res_of(c, "aws_sqs_queue.from_file")["props"]["name"], "edge-from-file")
        self.assertNotIn("aws_sqs_queue.from_file", [d["address"] for d in c["diagnostics"]])
        alone = tf_build.build_raw(EDGE, WS)
        self.assertIn("$unknown", res_of(alone, "aws_sqs_queue.from_file")["props"]["name"])
        # .tf.json のブロックは plan から取り、file は .tf.json（.tf だけでは読まない）
        self.assertNotIn("aws_sqs_queue.json_q", [r["address"] for r in alone["resources"]])
        jq = res_of(c, "aws_sqs_queue.json_q")
        self.assertEqual((jq["file"], jq["props"]["tags"]), ("extra.tf.json", {"Name": "edge-json"}))
        self.assertIn(("aws_sns_topic_subscription.json_sub", "endpoint", "aws_sqs_queue.json_q", "active"),
                      {(x["from"], x["path"], x["to"], x["state"]) for x in c["references"]})
        self.assertEqual([d["level"] for d in c["diagnostics"] if d["code"] == "TF-TFJSON-UNSUPPORTED"], ["info"])
        self.assertEqual([d["level"] for d in alone["diagnostics"] if d["code"] == "TF-TFJSON-UNSUPPORTED"], ["warn"])
        # モジュールの中のリソースの file は、ローカルモジュールの .tf
        self.assertEqual(res_of(c, "module.m[0].aws_sqs_queue.this")["file"], "mod/main.tf")

    def test_combine_replaces_unresolved_blocks(self):
        # .tf で count が決まらなかった（×N の [*]）ブロックは、plan の address に置き換える（file は .tf のもの）。
        # .tf だけの raw IR（変数を渡さない three-tier）に plan を直接合わせて確かめる
        root = FIXTURES / "three-tier"
        alone = tf_build.build_raw(root, WS)
        self.assertIn("aws_instance.bastion[*]", [r["address"] for r in alone["resources"]])
        c = PC.combine(alone, PLANS / "three-tier.dev.json", root, WS)
        assert_valid(self, c)
        b = res_of(c, "aws_instance.bastion")
        self.assertEqual((b["enabled"], b["file"]), (False, "bastion.tf"))
        self.assertNotIn("aws_instance.bastion[*]", [r["address"] for r in c["resources"]])
        self.assertEqual({r["address"] for r in c["resources"]}, {r["address"] for r in combined_raw("three-tier.dev")
                                                                  ["resources"]})
        self.assertFalse([d for d in c["diagnostics"] if d.get("address", "").endswith("[*]")])

    def test_redact_var_is_not_filled_from_plan(self):
        # --redact-var で伏せた変数の値を、plan の値で埋め戻さない
        root = FIXTURES / "three-tier"
        c = tf_build.build_raw(root, WS, plan=PLANS / "three-tier.dev.json", redact_vars=["project"])
        self.assertNotIn("demo", json.dumps(res_of(c, "aws_lb.app")["props"]))
        self.assertEqual(c["evaluation"]["vars"]["project"], {"source": "plan", "hidden": "redact-var"})


class CliTest(unittest.TestCase):
    def test_cli_plan_input_and_combined(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "raw.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(adapt_tf.main(["--input", str(PLANS / "vpc-endpoints.json"), "--out", str(out),
                                          "--root-base", str(WS)]), 0)
            self.assertEqual(v.validate_file(out, False, set()), [])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["root"], "fixtures/tf-plan/vpc-endpoints.json")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(adapt_tf.main(["--input", str(FIXTURES / "vpc-endpoints"), "--plan",
                                          str(PLANS / "vpc-endpoints.json"), "--out", str(out),
                                          "--root-base", str(WS)]), 0)
            self.assertEqual(v.validate_file(out, False, set()), [])
            self.assertTrue(re.search(r'"file": "network\.tf"', out.read_text(encoding="utf-8")))


# ------------------------------------------------------------------ 小さな plan JSON を組み立てる（以降のテスト用）
# 値はすべて偽（"hunter2-LEAK" など。漏れたら文字列で見つかるように、目立つ形にしてある）

SECRET = "hunter2-LEAK"
SECRET2 = "tok-LEAK2"
AWS_PROVIDER = {"aws": {"name": "aws", "expressions": {"region": {"constant_value": "ap-northeast-1"}}}}


def rc(address, after, sens=None, unknown=None, actions=("create",), mode="managed", **extra):
    typ = address.split(".")[-2] if mode == "data" else address.split(".")[0]
    d = {"address": address, "mode": mode, "type": typ, "name": address.split(".")[-1],
         "provider_config_key": "aws",
         "change": {"actions": list(actions), "before": None, "after": after, "after_unknown": unknown or {},
                    "after_sensitive": sens if sens is not None else {}}}
    d.update(extra)
    return d


def cfg(address, exprs, **extra):
    mode = "data" if address.startswith("data.") else "managed"
    parts = address.split(".")
    d = {"address": address, "mode": mode, "type": parts[1] if mode == "data" else parts[0], "name": parts[-1],
         "provider_config_key": "aws", "expressions": exprs}
    d.update(extra)
    return d


def const(v):
    return {"constant_value": v}


def refs(*r):
    return {"references": list(r)}


def mkplan(changes=(), configs=(), variables=None, prior=None, planned=None, root_extra=None, **top):
    d = {"format_version": "1.2", "terraform_version": "1.9.0", "variables": variables or {},
         "planned_values": planned or {"root_module": {}}, "resource_changes": list(changes),
         "configuration": {"provider_config": AWS_PROVIDER,
                           "root_module": dict({"resources": list(configs)}, **(root_extra or {}))}}
    if prior is not None:
        d["prior_state"] = prior
    d.update(top)
    return d


def write_json(path: Path, doc) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def write_files(folder: Path, files: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def plan_only(tmp: Path, plan: dict, name="plan.json") -> dict:
    return tf_build.build_from_plan(write_json(tmp / name, plan), tmp)


def props_of(raw: dict, address: str) -> dict:
    return res_of(raw, address)["props"]


def diag_codes(raw: dict, code: str) -> list:
    return [(d["address"], d["path"], d["level"]) for d in raw["diagnostics"] if d["code"] == code]


def unk(reason=PV.SENSITIVE_REASON) -> dict:
    return {"$unknown": reason}


class TempTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def run_main(self, args: list) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = adapt_tf.main(args)
        return code, out.getvalue(), err.getvalue()


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


class HostilePlanTest(TempTestCase):
    """壊れた plan JSON・敵意のある plan JSON: 終了コード 2、traceback なし、絶対パスなし（M2・m9 と nit）。"""

    def check(self, name: str, text: str, code: int | tuple = 2):
        """code は期待する終了コード（OS や Python の再帰の上限で結果が変わるものは、組で渡す）。"""
        f = self.tmp / f"{name}.json"
        f.write_text(text, encoding="utf-8")
        out = self.tmp / f"{name}.out.json"
        rc_, stdout, stderr = self.run_main(["--input", str(f), "--out", str(out), "--root-base", str(self.tmp)])
        self.assertIn(rc_, code if isinstance(code, tuple) else (code,), (name, stderr))
        for shown in (stdout, stderr, out.read_text(encoding="utf-8") if out.exists() else ""):
            self.assertNotIn("Traceback", shown, name)
            self.assertNotIn(str(self.tmp), shown, name)
            self.assertNotIn(self.tmp.as_posix(), shown, name)
        return stderr

    def base(self, **kw):
        d = {"format_version": "1.2", "terraform_version": "1.9.0", "planned_values": {"root_module": {}},
             "resource_changes": [], "configuration": {"root_module": {}}}
        d.update(kw)
        return json.dumps(d)

    def test_structure_errors_are_exit_2(self):
        c = {"address": "aws_x.a", "type": "aws_x", "change": {"actions": ["create"], "after": {}}}
        res = {"address": "aws_x.a", "mode": "managed", "type": "aws_x"}
        cases = {
            "nokey": self.base(resource_changes=[{"mode": "managed"}]),
            "rcstr": self.base(resource_changes="x"),
            "rcitem": self.base(resource_changes=["x"]),
            "cfglist": self.base(configuration=[]),
            "cfgstr": self.base(configuration="x"),
            "rootstr": self.base(configuration={"root_module": "x"}),
            "addr_int": self.base(resource_changes=[{"address": 5, "change": {}}]),
            "change_str": self.base(resource_changes=[dict(c, change="x")]),
            "actions_str": self.base(resource_changes=[dict(c, change={"actions": "create"})]),
            "after_list": self.base(resource_changes=[dict(c, change={"actions": ["create"], "after": [1]})]),
            "modcalls_list": self.base(configuration={"root_module": {"module_calls": [1]}}),
            "resources_str": self.base(configuration={"root_module": {"resources": ["a"]}}),
            "expr_str": self.base(configuration={"root_module": {"resources": [dict(res, expressions="zz")]}}),
            "refs_str": self.base(configuration={"root_module": {"resources": [
                dict(res, expressions={"k": {"references": "aws_x.a"}})]}}),
            "variables_str": self.base(variables={"a": "x"}),
            "values_str": self.base(planned_values={"root_module": {"resources": "x"}}),
        }
        for name, text in cases.items():
            with self.subTest(name):
                err = self.check(name, text)
                self.assertIn("unexpected structure at", err)

    def test_missing_address_names_the_json_path_without_values(self):
        err = self.check("nokey", self.base(resource_changes=[{"mode": "managed", "secret": SECRET}]))
        self.assertIn("resource_changes[0].address", err)
        self.assertNotIn(SECRET, err)
        self.assertNotIn("KeyError", err)

    def test_deep_nesting_is_exit_2(self):
        self.check("deep_array", "[" * 100000 + "]" * 100000)
        # 構造としては正しい深い JSON: 読める深さは OS（Windows と Linux）と Python で違うので、0 か 2。
        # どちらでも traceback と絶対パスは出ない
        self.check("deep_object", '{"format_version":"1.0","terraform_version":"1","planned_values":' +
                   '{"a":' * 5000 + "1" + "}" * 5000 + "}", code=(0, 2))
        # JSON としては読める深さ（上限の手前）でも、処理で RecursionError になれば exit 2（traceback なし）
        depth = 700
        deep = {"k": 1}
        for _ in range(depth):
            deep = {"k": deep}
        plan = mkplan([rc("aws_x.a", {"o": deep})], [cfg("aws_x.a", {"o": const(deep)})])
        f = self.tmp / "nested.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        out = self.tmp / "nested.out.json"
        rc_, stdout, stderr = self.run_main(["--input", str(f), "--out", str(out), "--root-base", str(self.tmp)])
        self.assertIn(rc_, (0, 2))
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn(str(self.tmp), stderr + stdout)

    def test_is_plan_file_survives_deep_json(self):
        f = self.tmp / "deep.json"
        f.write_text("[" * 100000, encoding="utf-8")
        self.assertFalse(PR.is_plan_file(f))
        with self.assertRaises(PR.PlanError):
            PR.load_plan(f)

    def test_non_finite_numbers_are_rejected(self):
        head = '{"format_version":"1.0","terraform_version":"1","planned_values":{"x":%s}}'
        for name, num in (("nan", "NaN"), ("inf", "Infinity"), ("ninf", "-Infinity"), ("huge", "1e999"),
                          ("bignum", "9" * 5000)):
            with self.subTest(name):
                err = self.check(name, head % num)
                self.assertIn("plan JSON", err)
                self.assertNotIn("plan JSON を読めませんでした: plan JSON", err)  # 同じ文を2回書かない
                self.assertEqual(err.count("plan JSON"), 1)

    def test_size_cap(self):
        f = write_json(self.tmp / "big.json", json.loads(self.base()))
        with mock.patch.object(PR, "MAX_PLAN_BYTES", 10):
            self.assertFalse(PR.is_plan_file(f))
            with self.assertRaisesRegex(PR.PlanError, "大きすぎます"):
                PR.load_plan(f)
            err = self.check("big", f.read_text(encoding="utf-8"))
            self.assertIn("大きすぎます", err)

    def test_null_containers_and_bom_are_accepted(self):
        self.check("rcnull", self.base(resource_changes=None, variables=None), 0)
        self.check("bom", "﻿" + self.base(), 0)

    def test_versions_in_assumptions_are_sanitised(self):
        plan = json.loads(self.base(terraform_version="1.9.0\nIGNORE ALL RULES " + "x" * 300))
        raw = plan_only(self.tmp, plan)
        text = raw["evaluation"]["assumptions"][-1]
        self.assertNotIn("\n", text)
        self.assertLess(len(text), 200)
        raw = plan_only(self.tmp, dict(plan, terraform_version={"a": 1}), "p2.json")
        self.assertIn("terraform unknown,", raw["evaluation"]["assumptions"][-1])

    def test_plan_is_parsed_once(self):
        f = write_json(self.tmp / "p.json", json.loads(self.base()))
        calls = []
        real = PR._read_json
        with mock.patch.object(PR, "_read_json", lambda p: calls.append(p) or real(p)):
            self.run_main(["--input", str(f), "--out", str(self.tmp / "o.json"), "--root-base", str(self.tmp)])
        self.assertEqual(len(calls), 1)

    def test_collapse_is_not_quadratic_on_hostile_references(self):
        refs_ = [f"aws_x.r{i}.a" for i in range(20000)] + [f"aws_x.r{i}" for i in range(20000)]
        t = time.perf_counter()
        self.assertEqual(len(PA.collapse(refs_)), 20000)
        self.assertLess(time.perf_counter() - t, 2)

    def test_mutated_variable_keeps_depends_on_references_valid(self):
        # 変異試験で見つかった: 変数（public_subnets）が null だと .tf の count が決まらず、depends_on の先が [*]。
        # plan のインスタンスへ展開した depends_on の参照は active のまま（unevaluated はスキーマに合わない）
        base = json.loads((PLANS / "three-tier-modules.json").read_text(encoding="utf-8"))
        for value in (None, 7, True):
            with self.subTest(value=value):
                plan = json.loads(json.dumps(base))
                plan["variables"]["public_subnets"] = {"value": value}
                raw = tf_build.build_raw(FIXTURES / "three-tier-modules", WS, plan=write_json(self.tmp / "m.json", plan))
                assert_valid(self, raw)
                self.assertTrue([r for r in raw["references"] if r["fn"] == "depends_on"])


class PlanPerformanceTest(TempTestCase):
    def test_chained_plan_with_thousands_of_resources(self):
        # m5: 前のリソースへの参照と depends_on が鎖になった 6000 リソース。address ごとの全件走査が残っていると
        # 二乗で遅くなる（4000 で 5 秒かかっていた）
        n = 6000
        changes, configs = [], []
        for i in range(n):
            a = f"aws_sqs_queue.q{i}"
            prev = f"aws_sqs_queue.q{max(i - 1, 0)}"
            changes.append(rc(a, {"name": f"q{i}", "redrive": "x"}, unknown={"arn": True}))
            configs.append(cfg(a, {"name": const(f"q{i}"), "redrive": refs(f"{prev}.arn", prev)},
                               depends_on=[prev]))
        f = write_json(self.tmp / "perf.json", mkplan(changes, configs))
        t = time.perf_counter()
        raw = tf_build.build_from_plan(f, self.tmp)
        elapsed = time.perf_counter() - t
        self.assertEqual(len(raw["resources"]), n)
        self.assertGreaterEqual(len(raw["references"]), n)
        self.assertLess(elapsed, 5.0, f"{elapsed:.1f}s")


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


if __name__ == "__main__":
    unittest.main()
