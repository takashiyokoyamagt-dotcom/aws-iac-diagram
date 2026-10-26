"""Terraform アダプタ × 自作 fixture（aws-iac-diagram-workspace/fixtures/tf）: 正解 IR（expected）の TF 側の網羅分類と、
raw IR の address・type・file・enabled が一致する。fixture 5 構成がすべて検査を通る raw IR になる。
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs, res_of
from support.paths import FIXTURES_TF as FIXTURES, WS
from support.terraform import codes, res
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402


def expected_addresses(expected: dict) -> dict:
    """正解 IR の TF 側の網羅分類（address → (type, file, enabled)）。count が 0 のブロック（H-COND-FALSE）は enabled: false。"""
    return {r["address"]: (r["type"], r["file"], r.get("rule") != "H-COND-FALSE")
            for r in expected["sources"]["tf"]["resources"]}


# 正解 IR を書いたときの変数の値（three-tier は dev。vpc-endpoints は terraform.tfvars を自動で読む）
EXPECTED_VAR_FILES = {"three-tier": ["env/dev.tfvars"]}


def build_expected_input(name: str) -> dict:
    root = FIXTURES / name
    return tf_build.build_raw(root, WS, var_files=[root / f for f in EXPECTED_VAR_FILES.get(name, [])])


class ExpectedIrTest(unittest.TestCase):
    """正解 IR（expected）の TF 側の網羅分類と、raw IR の address・type・file・enabled を突き合わせる。

    count・for_each はインスタンス単位で、count が 0 のブロック（H-COND-FALSE）は enabled: false で一致する。
    モジュールの中身（ローカルモジュールの再帰と、要約表の展開。via: module_summary）も含めて、読み替えずに比べる。
    """

    def test_addresses_match_expected(self):
        for name in ("three-tier", "serverless-api", "vpc-endpoints", "rag", "three-tier-modules"):
            with self.subTest(name):
                expected = json.loads((WS / "expected" / f"{name}.ir.json").read_text(encoding="utf-8"))
                self.assertEqual(expected["sources"]["tf"]["root"], f"fixtures/tf/{name}")
                raw = build_expected_input(name)
                self.assertEqual(raw["root"], expected["sources"]["tf"]["root"])
                got = {r["address"]: (r["type"], r["file"], r["enabled"]) for r in raw["resources"]}
                self.assertEqual(got, expected_addresses(expected))
                want_via = {r["address"]: r.get("via") for r in expected["sources"]["tf"]["resources"]}
                for r in raw["resources"]:
                    self.assertNotIn("multiplicity", r, r["address"])  # 5構成とも count・for_each が決まる
                    self.assertEqual(r.get("via"), want_via[r["address"]], r["address"])
                    if r["address"].startswith("module."):
                        self.assertEqual(r["module"], r["address"].rsplit(".", 2)[0] if ".data." not in r["address"]
                                         else r["address"].split(".data.")[0], r["address"])
                # 正解 IR の構成では、評価できない値は rag の sha1()（デプロイの再作成の引き金）だけ
                warns = [(d["address"], d["path"], d["code"]) for d in raw["diagnostics"] if d["level"] != "info"]
                self.assertEqual(warns, [("aws_api_gateway_deployment.api", "triggers.redeployment", "TF-UNEVALUATED")]
                                 if name == "rag" else [])

    def test_known_references(self):
        # 正解 IR の辺の根拠のうち、モジュールの境界をまたがないもの（count・for_each はインスタンスごと）
        cases = {
            "three-tier": [
                ("aws_lb_listener.http", "default_action[0].target_group_arn", "aws_lb_target_group.app", "arn"),
                ("aws_ecs_service.app", "load_balancer[0].target_group_arn", "aws_lb_target_group.app", "arn"),
                ("aws_ecs_task_definition.app", "container_definitions[0].environment[0].value",
                 "aws_db_instance.main", "address"),
                ("aws_route_table.private", "route[0].nat_gateway_id", "aws_nat_gateway.main", "id"),
                ("aws_lb.app", "subnets[0]", "aws_subnet.public[0]", "id"),
                ("aws_lb.app", "subnets[1]", "aws_subnet.public[1]", "id"),
                ("aws_route_table_association.private[1]", "subnet_id", "aws_subnet.private[1]", "id"),
                ("aws_nat_gateway.main", "subnet_id", "aws_subnet.public[0]", "id"),
                # 作られない（dev で count が 0）リソースの参照も残す。先も作られないブロック（添字なし）
                ("aws_instance.bastion", "vpc_security_group_ids[0]", "aws_security_group.bastion", "id"),
            ],
            "serverless-api": [
                ("aws_lambda_event_source_mapping.orders_stream", "event_source_arn", "aws_dynamodb_table.orders",
                 "stream_arn"),
                ("aws_lambda_event_source_mapping.orders_stream", "function_name",
                 "aws_lambda_function.stream_processor", "arn"),
                ("aws_sns_topic_subscription.order_events_queue", "endpoint", "aws_sqs_queue.order_events", "arn"),
            ],
            "vpc-endpoints": [
                ("aws_security_group.endpoints", "ingress[0].security_groups[0]", "aws_security_group.app", "id"),
                ("aws_vpc_endpoint.s3", "route_table_ids[0]", "aws_route_table.private[0]", "id"),
                ("aws_vpc_endpoint.s3", "route_table_ids[1]", "aws_route_table.private[1]", "id"),
                ("aws_route.private_nat[1]", "nat_gateway_id", "aws_nat_gateway.main[1]", "id"),
                ("aws_route.private_nat[1]", "route_table_id", "aws_route_table.private[1]", "id"),
                ("aws_nat_gateway.main[0]", "allocation_id", "aws_eip.nat[0]", "id"),
                ('aws_vpc_endpoint.interface["ssm"]', "security_group_ids[0]", "aws_security_group.endpoints", "id"),
                ('aws_vpc_endpoint.interface["ssm"]', "subnet_ids[1]", "aws_subnet.private[1]", "id"),
            ],
            "rag": [
                ("aws_bedrockagent_data_source.docs", "data_source_configuration[0].s3_configuration[0].bucket_arn",
                 "aws_s3_bucket.docs", "arn"),
                ("aws_s3_bucket_notification.docs", "lambda_function[0].lambda_function_arn",
                 "aws_lambda_function.ingest", "arn"),
                ("aws_api_gateway_integration.query_post", "uri", "aws_lambda_function.query", "invoke_arn"),
            ],
        }
        cases["serverless-api"].append(('aws_apigatewayv2_route.this["get_orders"]', "target",
                                        "aws_apigatewayv2_integration.api_handler", "id"))
        # モジュールの境界をまたぐもの（手順3。出力・変数をたどって元のリソースへ。正解 IR の three-tier-modules の根拠）
        cases["three-tier-modules"] = [
            ('module.alb.aws_lb_listener.this["http"]', "default_action[0].target_group_arn",
             'module.alb.aws_lb_target_group.this["app"]', "arn"),
            ("module.app.aws_ecs_service.this", "load_balancer[0].target_group_arn",
             'module.alb.aws_lb_target_group.this["app"]', "arn"),
            ("module.app.aws_vpc_security_group_ingress_rule.from_alb", "referenced_security_group_id",
             "module.alb.aws_security_group.this[0]", "id"),
            ("module.app.aws_ecs_task_definition.this", "container_definitions[0].environment[0].value",
             "module.db.module.db_instance.aws_db_instance.this[0]", "address"),
            ("aws_security_group.db", "ingress[0].security_groups[0]", "module.app.aws_security_group.this", "id"),
            ("module.db.module.db_instance.aws_db_instance.this[0]", "vpc_security_group_ids[0]",
             "aws_security_group.db", "id"),
            ("module.vpc.aws_route.private_nat_gateway[0]", "nat_gateway_id", "module.vpc.aws_nat_gateway.this[0]", "id"),
            ("module.vpc.aws_route_table_association.private[1]", "subnet_id", "module.vpc.aws_subnet.private[1]", "id"),
            ("module.vpc.aws_route.public_internet_gateway[0]", "gateway_id", "module.vpc.aws_internet_gateway.this[0]",
             "id"),
            ("module.alb.aws_lb.this[0]", "subnets[1]", "module.vpc.aws_subnet.public[1]", "id"),
        ]
        for name, wants in cases.items():
            got = refs(build_expected_input(name))
            for want in wants:
                with self.subTest(name=name, ref=want[:2]):
                    self.assertIn(want + ("ref", "active"), got)

    def test_values_from_tfvars(self):
        # three-tier: env/dev.tfvars と env/prod.tfvars で、踏み台（count）と DB の設定（local の表）が変わる
        root = FIXTURES / "three-tier"
        dev = tf_build.build_raw(root, WS, var_files=[root / "env" / "dev.tfvars"])
        prod = tf_build.build_raw(root, WS, var_files=[root / "env" / "prod.tfvars"])
        none = tf_build.build_raw(root, WS)
        self.assertEqual(dev["evaluation"]["var_files"], ["env/dev.tfvars"])
        self.assertEqual(dev["evaluation"]["vars"]["environment"], {"source": "env/dev.tfvars"})
        self.assertEqual(prod["evaluation"]["vars"]["admin_cidr"], {"source": "env/prod.tfvars"})  # prod.tfvars が上書き
        self.assertEqual(dev["evaluation"]["vars"]["admin_cidr"], {"source": "default"})
        self.assertFalse(res_of(dev, "aws_instance.bastion")["enabled"])
        self.assertTrue(res_of(prod, "aws_instance.bastion[0]")["enabled"])
        self.assertNotIn("aws_instance.bastion", [r["address"] for r in prod["resources"]])
        self.assertEqual(props(prod, "aws_security_group.bastion[0]")["ingress"][0]["cidr_blocks"], ["198.51.100.0/24"])
        self.assertEqual(props(prod, "aws_instance.bastion[0]")["vpc_security_group_ids"],
                         [res("aws_security_group.bastion[0]", "id")])
        self.assertEqual((props(dev, "aws_db_instance.main")["instance_class"],
                          props(prod, "aws_db_instance.main")["instance_class"]), ("db.t4g.micro", "db.m7g.large"))
        self.assertEqual((props(dev, "aws_db_instance.main")["multi_az"],
                          props(prod, "aws_db_instance.main")["multi_az"]), (False, True))
        self.assertNotIn("final_snapshot_identifier", props(dev, "aws_db_instance.main"))  # null は書かない
        self.assertEqual(props(prod, "aws_db_instance.main")["final_snapshot_identifier"], "demo-db-final")
        self.assertEqual(props(dev, "aws_ecs_service.app")["desired_count"], 1)
        # 値の無い environment では、踏み台は ×N（count が決まらない）
        self.assertIsNone(res_of(none, "aws_instance.bastion[*]")["enabled"])
        self.assertIn("TF-UNRESOLVED-VAR", codes(none, "aws_db_instance.main"))
        # 値の無い変数と、自動では読まれない変数のファイルの候補を1つの診断にまとめる（どの環境かを確かめるため）
        summary = [d for d in none["diagnostics"] if d["code"] == "TF-UNRESOLVED-VARS"]
        self.assertEqual([(d["level"], d["message"]) for d in summary], [(
            "info", "variables without a value: environment; var files that are not read automatically "
                    "(pass one with --var-file): env/dev.tfvars, env/prod.tfvars")])
        self.assertNotIn("TF-UNRESOLVED-VARS", codes(dev))
        # vpc-endpoints: terraform.tfvars（自動で読む）の project が既定値を上書きし、名前が正解 IR と一致する
        vpce = tf_build.build_raw(FIXTURES / "vpc-endpoints", WS)
        self.assertEqual(vpce["evaluation"]["var_files"], ["terraform.tfvars"])
        self.assertEqual(props(vpce, "aws_vpc.main")["tags"], {"Name": "net"})
        self.assertEqual(props(vpce, 'aws_vpc_endpoint.interface["ssm"]')["service_name"],
                         "com.amazonaws.ap-northeast-1.ssm")
        self.assertEqual(props(vpce, "aws_subnet.private[1]")["tags"], {"Name": "net-private-ap-northeast-1c"})
        override = tf_build.build_raw(FIXTURES / "vpc-endpoints", WS, vars={"project": "x"})
        self.assertEqual(props(override, "aws_vpc.main")["tags"], {"Name": "x"})

    def test_names_match_expected_nodes(self):
        # 正解 IR のノードの名前（Name タグ・名前の属性）が、評価した props に現れる（ノード ID の元。K-NAME）
        cases = {"three-tier": [("aws_subnet.private[1]", "tags", {"Name": "demo-private-ap-northeast-1c"}),
                                ("aws_lb.app", "name", "demo-alb"), ("aws_ecs_service.app", "name", "demo-app")],
                 "serverless-api": [("aws_lambda_function.api_handler", "function_name", "shop-api-handler"),
                                    ('aws_apigatewayv2_route.this["post_orders"]', "route_key", "POST /orders")],
                 "rag": [("aws_s3_bucket.docs", "bucket", "rag-docs")]}
        for name, wants in cases.items():
            raw = build_expected_input(name)
            for address, key, value in wants:
                with self.subTest(name=name, address=address):
                    self.assertEqual(props(raw, address)[key], value)


class FixtureTest(unittest.TestCase):
    def test_all_fixtures_produce_valid_raw(self):
        from iac_inventory import tf_inventory
        for d in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
            with self.subTest(d.name):
                raw = tf_build.build_raw(d, WS)
                assert_valid(self, raw)
                self.assertFalse([x for x in raw["diagnostics"] if x["level"] == "error"])
                blocks = {b.address for b in tf_inventory(d) if b.module_path == ""}
                # インスタンスの添字を除けば、ルートのブロックの一覧と同じ。モジュールの呼び出しは、中身の
                # リソース（module.x.…）か黒箱の呼び出し1件になる
                got = {re.sub(r"\[[^\]]*\]$", "", r["address"]) for r in raw["resources"]}
                self.assertEqual({a for a in got if not a.startswith("module.")},
                                 {b for b in blocks if not b.startswith("module.")})
                for b in (b for b in blocks if b.startswith("module.")):
                    self.assertTrue(any(a == b or a.startswith(b + ".") or a.startswith(b + "[") for a in got), b)


if __name__ == "__main__":
    unittest.main()
