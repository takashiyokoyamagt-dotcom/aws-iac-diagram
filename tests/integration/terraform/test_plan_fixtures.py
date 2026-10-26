"""plan JSON × コミットした fixture（aws-iac-diagram-workspace/fixtures/tf-plan）: plan だけ・.tf と合わせた raw IR が、.tf だけの
raw IR と一致する（既知の差を除く）、edge の plan、入口 adapt_tf.py の plan JSON の入力（CLI）。
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import res_of
from support.paths import FIXTURES_TF as FIXTURES, PLANS, WS
from support.tf_plan import CASES, EDGE, EDGE_PLAN, assert_valid_no_errors as assert_valid, combined_raw
import adapt_tf  # noqa: E402
import validate_ir as v  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402
from aws_iac_diagram.adapters.terraform.plan import combine as PC, masking as PM, values as PV  # noqa: E402
from aws_iac_diagram.core import ir_raw  # noqa: E402


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


def pairs(raw: dict, state: str | None = None) -> set:
    return {(r["from"], r["to"]) for r in raw["references"]
            if r["fn"] == "ref" and (state is None or r["state"] == state)}


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


if __name__ == "__main__":
    unittest.main()
