"""参照の会計（normalize/refs.py。CRITERIA の 1.8）: active の参照が 4 つの分類のちょうど 1 つに入る。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.raw_builders import raw_ir, reference, resource
from aws_iac_diagram.core import rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import build, refs  # noqa: E402

RULES = rules_mod.default()


class AccountingTest(unittest.TestCase):
    def test_every_active_reference_gets_exactly_one_class(self):
        res = [
            resource("aws_vpc.v", "aws_vpc", {"tags": {"Name": "v"}}),
            resource("aws_subnet.s", "aws_subnet", {"tags": {"Name": "s"}}),
            resource("aws_dynamodb_table.t", "aws_dynamodb_table", {"name": "t"}),
            resource("aws_lambda_function.fn", "aws_lambda_function", {"function_name": "fn"}),
            resource("aws_cloudwatch_log_group.lg", "aws_cloudwatch_log_group"),
            resource("aws_iam_role.r", "aws_iam_role"),
            resource("aws_lambda_event_source_mapping.m", "aws_lambda_event_source_mapping"),
        ]
        refs_in = [
            reference("aws_lambda_event_source_mapping.m", "event_source_arn", "aws_dynamodb_table.t", "stream_arn"),  # 辺の根拠
            reference("aws_lambda_event_source_mapping.m", "function_name", "aws_lambda_function.fn", "arn"),  # 辺の根拠
            reference("aws_iam_role.r", "inline_policy[0].policy", "aws_dynamodb_table.t", "arn"),  # 参照する側が H-*
            reference("aws_subnet.s", "vpc_id", "aws_vpc.v", "id"),  # E-NOEDGE-PLACEMENT（属性名）
            reference("aws_lambda_function.fn", "role", "aws_iam_role.r", "arn"),  # 参照先が非表示: E-NOEDGE の表より先に E-REF-NONODE
            reference("aws_lambda_function.fn", "vpc_config[0].security_group_ids[0]", "aws_vpc.v", "id"),  # 最後の要素で E-NOEDGE-SG
            reference("aws_lambda_function.fn", "depends_on", "aws_cloudwatch_log_group.lg", fn="depends_on"),  # E-NOEDGE-DEPENDS
            reference("aws_lambda_function.fn", "environment[0].variables.LOGS", "aws_cloudwatch_log_group.lg", "name"),  # E-REF-NONODE
            reference("aws_lambda_function.fn", "environment[0].variables.TABLE", "aws_dynamodb_table.t", "name"),  # 辺の根拠（E-ENV-REF）
            reference("aws_lambda_function.fn", "environment[0].variables.VPC", "aws_vpc.v", "id"),  # NORM-UNUSED-REF（VPC は kind の表に無い）
            reference("aws_lambda_function.fn", "environment[0].variables.OLD", "aws_dynamodb_table.t", "name", state="pruned"),  # 数えない
        ]
        r = build.run(raw_ir("tf", res, refs_in), RULES, "t")
        got = {(e.ref["from"], e.ref["path"]): (e.cls, e.rule) for e in r.accounting}
        self.assertEqual(len(r.accounting), 10)  # active だけ
        self.assertEqual(got, {
            ("aws_lambda_event_source_mapping.m", "event_source_arn"): ("edge", None),
            ("aws_lambda_event_source_mapping.m", "function_name"): ("edge", None),
            ("aws_iam_role.r", "inline_policy[0].policy"): ("noedge", "E-NOEDGE-FROM-RULE"),
            ("aws_subnet.s", "vpc_id"): ("noedge", "E-NOEDGE-PLACEMENT"),
            ("aws_lambda_function.fn", "role"): ("nonode", "E-REF-NONODE"),
            ("aws_lambda_function.fn", "vpc_config[0].security_group_ids[0]"): ("noedge", "E-NOEDGE-SG"),
            ("aws_lambda_function.fn", "depends_on"): ("noedge", "E-NOEDGE-DEPENDS"),
            ("aws_lambda_function.fn", "environment[0].variables.LOGS"): ("nonode", "E-REF-NONODE"),
            ("aws_lambda_function.fn", "environment[0].variables.TABLE"): ("edge", None),
            ("aws_lambda_function.fn", "environment[0].variables.VPC"): ("unused", None),
        })
        unused = [d for d in r.ir["diagnostics"] if d["code"] == "NORM-UNUSED-REF"]
        self.assertEqual([(d["level"], d["address"], d["path"]) for d in unused],
                         [("info", "aws_lambda_function.fn", "environment[0].variables.VPC")])
        self.assertIn("aws_vpc.v", unused[0]["message"])
        self.assertEqual(refs.summary(r.accounting), {"E-NOEDGE-DEPENDS": 1, "E-NOEDGE-FROM-RULE": 1, "E-NOEDGE-PLACEMENT": 1,
                                                      "E-NOEDGE-SG": 1, "E-REF-NONODE": 2, "edge": 3, "unused": 1})

    def test_first_key_and_except_rules(self):
        # SAM の Policies のテンプレートの参照は E-IAM の根拠。タスク定義（M-ECS-TASKDEF）の中の参照は FROM-RULE に当てず、E-ENV-REF の根拠
        res = [resource("Fn", "AWS::Serverless::Function", {"FunctionName": "fn", "Policies": [
                   {"DynamoDBCrudPolicy": {"TableName": {"$res": "T", "attr": None}}}]}, fmt="cfn"),
               resource("T", "AWS::DynamoDB::Table", {"TableName": "t"}, fmt="cfn"),
               resource("Svc", "AWS::ECS::Service", {"ServiceName": "svc"}, fmt="cfn"),
               resource("Td", "AWS::ECS::TaskDefinition", fmt="cfn")]
        refs_in = [reference("Fn", "Properties.Policies[0].DynamoDBCrudPolicy.TableName", "T", None, fn="Ref"),
                   reference("Svc", "Properties.TaskDefinition", "Td", None, fn="Ref"),
                   reference("Td", "Properties.ContainerDefinitions[0].Environment[0].Value", "T", None, fn="Ref")]
        r = build.run(raw_ir("cfn", res, refs_in), RULES, "t")
        got = {(e.ref["from"], e.ref["path"]): (e.cls, e.rule) for e in r.accounting}
        self.assertEqual(got[("Fn", "Properties.Policies[0].DynamoDBCrudPolicy.TableName")], ("edge", None))
        self.assertEqual(got[("Svc", "Properties.TaskDefinition")], ("noedge", "E-NOEDGE-MERGE"))
        self.assertEqual(got[("Td", "Properties.ContainerDefinitions[0].Environment[0].Value")], ("edge", None))  # E-ENV-REF


    def test_map_keys_provisional_relations_and_self_merge(self):
        res = [resource("aws_subnet.s", "aws_subnet", {"tags": {"Name": "s"}}),
               resource("aws_lambda_function.fn", "aws_lambda_function", {"function_name": "fn"}),
               resource("aws_instance.i", "aws_instance", {"tags": {"Name": "i"}}),
               resource("aws_security_group.sg", "aws_security_group"),
               resource("aws_api_gateway_rest_api.api", "aws_api_gateway_rest_api", {"name": "api"}),
               resource("aws_api_gateway_authorizer.a", "aws_api_gateway_authorizer")]
        refs_in = [
            # 環境変数（map）の名前は属性名ではない: SUBNET_ID でも E-NOEDGE-PLACEMENT にしない（E-ENV-REF の材料。手順 4b）
            reference("aws_lambda_function.fn", "environment[0].variables.SUBNET_ID", "aws_subnet.s", "id"),
            reference("aws_lambda_function.fn", "tags.vpc_id", "aws_subnet.s", "id"),
            # 参照先が仮の R-SG（まだ辺に変換していない）なら E-REF-NONODE ではなく、属性名の E-NOEDGE-SG
            reference("aws_instance.i", "vpc_security_group_ids[0]", "aws_security_group.sg", "id"),
            # M-* から自分の統合先への参照（オーソライザー → その API）は E-NOEDGE-FROM-RULE（M-APIGW-AUTHORIZER は除外の規則でも）
            reference("aws_api_gateway_authorizer.a", "rest_api_id", "aws_api_gateway_rest_api.api", "id"),
        ]
        r = build.run(raw_ir("tf", res, refs_in), RULES, "t")
        got = {(e.ref["from"], e.ref["path"]): (e.cls, e.rule) for e in r.accounting}
        self.assertEqual(got, {
            ("aws_lambda_function.fn", "environment[0].variables.SUBNET_ID"): ("unused", None),
            ("aws_lambda_function.fn", "tags.vpc_id"): ("unused", None),
            ("aws_instance.i", "vpc_security_group_ids[0]"): ("noedge", "E-NOEDGE-SG"),
            ("aws_api_gateway_authorizer.a", "rest_api_id"): ("noedge", "E-NOEDGE-FROM-RULE"),
        })

    def test_reference_to_own_merged_resource(self):
        # 描くリソースから、自分に統合された M-* への参照（CloudFront → オリジンアクセス制御）は E-NOEDGE-MERGE
        res = [resource("Cdn", "AWS::CloudFront::Distribution", {"Tags": [{"Key": "Name", "Value": "cdn"}]}, fmt="cfn"),
               resource("Oac", "AWS::CloudFront::OriginAccessControl", fmt="cfn")]
        refs_in = [reference("Cdn", "Properties.DistributionConfig.Origins[0].OriginAccessControlId", "Oac", "Id", fn="GetAtt")]
        r = build.run(raw_ir("cfn", res, refs_in), RULES, "t")
        self.assertEqual([(e.cls, e.rule) for e in r.accounting], [("noedge", "E-NOEDGE-MERGE")])

    def test_sam_policies_are_pinned(self):
        # SAM の Policies の中の参照は、E-IAM（手順 4b）が辺の根拠に取る（E-NOEDGE-ROLE より先）。テンプレートと文の両方。
        # E-IAM が取らない参照（kind の決まらないテンプレート）だけが E-NOEDGE-ROLE に落ちる
        policies = [{"DynamoDBCrudPolicy": {"TableName": {"$res": "T", "attr": None}}},
                    {"SNSPublishMessagePolicy": {"TopicName": {"$res": "Top", "attr": "TopicName"}}},
                    {"Statement": [{"Effect": "Allow", "Action": "dynamodb:GetItem", "Resource": {"$res": "T", "attr": "Arn"}}]},
                    {"AWSSecretsManagerGetSecretValuePolicy": {"SecretArn": {"$res": "T", "attr": "Arn"}}}]
        res = [resource("Fn", "AWS::Serverless::Function", {"FunctionName": "fn", "Policies": policies}, fmt="cfn"),
               resource("T", "AWS::DynamoDB::Table", {"TableName": "t"}, fmt="cfn"),
               resource("Top", "AWS::SNS::Topic", {"TopicName": "top"}, fmt="cfn")]
        refs_in = [reference("Fn", "Properties.Policies[0].DynamoDBCrudPolicy.TableName", "T", None, fn="Ref"),
                   reference("Fn", "Properties.Policies[1].SNSPublishMessagePolicy.TopicName", "Top", "TopicName", fn="GetAtt"),
                   reference("Fn", "Properties.Policies[2].Statement[0].Resource", "T", "Arn", fn="GetAtt"),
                   reference("Fn", "Properties.Policies[3].AWSSecretsManagerGetSecretValuePolicy.SecretArn", "T", "Arn", fn="GetAtt")]
        r = build.run(raw_ir("cfn", res, refs_in), RULES, "t")
        got = {e.ref["path"]: (e.cls, e.rule) for e in r.accounting}
        self.assertEqual(got, {**{x["path"]: ("edge", None) for x in refs_in[:3]},
                               refs_in[3]["path"]: ("noedge", "E-NOEDGE-ROLE")})


if __name__ == "__main__":
    unittest.main()
