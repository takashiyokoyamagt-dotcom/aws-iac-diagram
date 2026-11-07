"""属性の参照から作る辺（normalize/attr_edges.py）、E-IAM（iam.py）、基盤モデルの合成ノード（synthetic.py）、E-MERGE のラベル。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.raw_builders import raw_ir, ref, resource
from aws_iac_diagram.core import rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import build, edges, synthetic  # noqa: E402
from aws_iac_diagram.normalize.relations_base import Candidate  # noqa: E402

RULES = rules_mod.default()


def norm(fmt, resources, references):
    """正規化して (辺 id → (kind, label, confidence), 辺 id → rules, ノード id → ノード)。internet からの辺（N-EXT-INTERNET。
    パブリックな API Gateway に付く）は test_sg.py で確かめるので、辺から除く。"""
    ir = build.normalize(raw_ir(fmt, resources, references), RULES, "t")
    e = {x["id"]: (x["kind"], x["label"], x["confidence"]) for x in ir["edges"] if x["from"] != "external/internet"}
    r = {x["edge"]: x["rules"] for x in ir["sources"][fmt]["edges"]}
    return e, r, {n["id"]: n for n in ir["nodes"]}


def fn(addr, name, **props):
    return resource(addr, "aws_lambda_function", {"function_name": name, **props})


class SyntheticTest(unittest.TestCase):
    def test_arns(self):
        self.assertEqual(synthetic.parse_arn("arn:aws:s3:::b/*"), ("s3", "b/*"))
        self.assertEqual(synthetic.parse_arn({"$concat": ["arn:", {"$pseudo": "AWS::Partition"}, ":sns:", {"$pseudo": "AWS::Region"}, ":1:t"]}),
                         ("sns", "t"))
        self.assertIsNone(synthetic.parse_arn({"$concat": ["arn:aws:s3:::", {"$pseudo": "AWS::AccountId"}]}))  # リソースの部分に印
        self.assertIsNone(synthetic.parse_arn("not-an-arn"))
        self.assertEqual(synthetic.model_id("arn:aws:bedrock:x::foundation-model/amazon.titan-embed-text-v2:0"), "amazon.titan-embed-text-v2:0")
        self.assertIsNone(synthetic.model_id("arn:aws:bedrock:x::foundation-model/*"))
        self.assertEqual(synthetic.model_node(RULES, "a.b:0"), {"id": "bedrock_model/a.b-0", "type": "bedrock_model", "category": "resource",
                                                                "name": "a.b:0", "label": "a.b:0", "parent": None, "synthetic": True})


class EnvTest(unittest.TestCase):
    def test_env_ref_and_str(self):
        e, r, n = norm("tf", [
            fn("aws_lambda_function.f", "f", environment=[{"variables": {"T": {"$res": "aws_dynamodb_table.t", "attr": "name"},
                                                                         "B": "bucket-1", "M": "arn:aws:bedrock:r::foundation-model/m:1",
                                                                         "SAME": "dup", "V": {"$res": "aws_vpc.v", "attr": "id"}}}]),
            resource("aws_dynamodb_table.t", "aws_dynamodb_table", {"name": "t"}),
            resource("aws_s3_bucket.b", "aws_s3_bucket", {"bucket": "bucket-1"}),
            resource("aws_sqs_queue.q1", "aws_sqs_queue", {"name": "dup"}), resource("aws_sns_topic.t2", "aws_sns_topic", {"name": "dup"}),
            resource("aws_vpc.v", "aws_vpc", {"tags": {"Name": "v"}}),
        ], [ref("aws_lambda_function.f", "environment[0].variables.T", "aws_dynamodb_table.t", "name"),
            ref("aws_lambda_function.f", "environment[0].variables.V", "aws_vpc.v", "id")])
        self.assertEqual(e, {
            "lambda_function/f->dynamodb_table/t": ("data", "", "confirmed"),  # E-ENV-REF
            "lambda_function/f->s3_bucket/bucket-1": ("data", "", "inferred"),  # E-ENV-STR（名前の一致）
            "lambda_function/f->bedrock_model/m-1": ("request", "", "inferred"),  # E-ENV-STR（基盤モデルの ARN）
        })  # VPC は kind の表に無いので辺にしない。2 つのリソースに当たる文字列（dup）も辺にしない
        self.assertTrue(n["bedrock_model/m-1"]["synthetic"])

    def test_ecs_task_definition_and_blackbox_module(self):
        e, r, _ = norm("tf", [
            resource("aws_ecs_service.s", "aws_ecs_service", {"name": "svc"}),
            resource("aws_ecs_task_definition.td", "aws_ecs_task_definition"),
            resource("aws_db_instance.db", "aws_db_instance", {"identifier": "db"}),
            resource("module.m", "module", via="module_blackbox", source="git::https://x/y.git"),
            fn("aws_lambda_function.f", "f"),
        ], [ref("aws_ecs_service.s", "task_definition", "aws_ecs_task_definition.td", "arn"),
            ref("aws_ecs_task_definition.td", "container_definitions[0].environment[0].value", "aws_db_instance.db", "address"),
            ref("aws_lambda_function.f", "environment[0].variables.X", "module.m", "endpoint")])
        self.assertEqual(e, {"ecs_service/svc->db_instance/db": ("data", "", "confirmed"),  # タスク定義はサービスの参照
                             "lambda_function/f->module/m": ("request", "", "inferred")})  # 黒箱のモジュールの出力は推定


class OtherAttrTest(unittest.TestCase):
    def test_kb_storage_and_embedding(self):
        e, r, n = norm("cfn", [
            resource("Kb", "AWS::Bedrock::KnowledgeBase", {"Name": "kb", "KnowledgeBaseConfiguration": {"VectorKnowledgeBaseConfiguration": {
                "EmbeddingModelArn": {"$concat": ["arn:", {"$pseudo": "AWS::Partition"}, ":bedrock:", {"$pseudo": "AWS::Region"},
                                                  "::foundation-model/amazon.titan-embed-text-v2:0"]}}}}, fmt="cfn"),
            resource("Col", "AWS::OpenSearchServerless::Collection", {"Name": "col"}, fmt="cfn"),
        ], [ref("Kb", "Properties.StorageConfiguration.OpensearchServerlessConfiguration.CollectionArn", "Col", "Arn")])
        self.assertEqual(e, {"bedrock_knowledge_base/kb->opensearchserverless_collection/col": ("data", "", "confirmed"),
                             "bedrock_knowledge_base/kb->bedrock_model/amazon.titan-embed-text-v2-0": ("request", "", "derived")})
        self.assertEqual(n["bedrock_model/amazon.titan-embed-text-v2-0"]["parent"], None)

    def test_cdn_waf_dns_glue_authorizer(self):
        e, r, _ = norm("cfn", [
            resource("Cdn", "AWS::CloudFront::Distribution", {"Tags": [{"Key": "Name", "Value": "cdn"}]}, fmt="cfn"),
            resource("B", "AWS::S3::Bucket", {"BucketName": "b"}, fmt="cfn"),
            resource("Waf", "AWS::WAFv2::WebACL", {"Name": "waf"}, fmt="cfn"),
            resource("Rec", "AWS::Route53::RecordSet", {"Name": "www"}, fmt="cfn"),
            resource("Cr", "AWS::Glue::Crawler", {"Name": "cr"}, fmt="cfn"), resource("Db", "AWS::Glue::Database", fmt="cfn"),
            resource("Api", "AWS::ApiGateway::RestApi", {"Name": "api"}, fmt="cfn"),
            resource("Auth", "AWS::ApiGateway::Authorizer", fmt="cfn"),
            resource("Pool", "AWS::Cognito::UserPool", {"UserPoolName": "pool"}, fmt="cfn"),
        ], [ref("Cdn", "Properties.DistributionConfig.Origins[0].DomainName", "B", "RegionalDomainName"),
            ref("Cdn", "Properties.DistributionConfig.WebACLId", "Waf", "Arn"),
            ref("Rec", "Properties.AliasTarget.DNSName", "Cdn", "DomainName"),
            ref("Cr", "Properties.DatabaseName", "Db"), ref("Cr", "Properties.Targets.S3Targets[0].Path", "B"),
            ref("Auth", "Properties.RestApiId", "Api"), ref("Auth", "Properties.ProviderARNs[0]", "Pool", "Arn")])
        self.assertEqual(e, {
            "cloudfront_distribution/cdn->s3_bucket/b": ("request", "", "confirmed"),
            "waf_web_acl/waf->cloudfront_distribution/cdn": ("request", "", "confirmed"),  # 通信は WAF を通ってから
            "route53_record/www->cloudfront_distribution/cdn": ("request", "", "confirmed"),
            "glue_crawler/cr->glue_catalog_database/db": ("data", "", "confirmed"),
            "glue_crawler/cr->s3_bucket/b": ("data", "", "confirmed"),
            "apigw_rest_api/api->cognito_user_pool/pool": ("request", "", "confirmed"),  # API 自身への参照は捨てる
        })


class IamTest(unittest.TestCase):
    def _tf(self, statements, extra_res=(), extra_refs=()):
        return norm("tf", [
            fn("aws_lambda_function.f", "f"), resource("aws_iam_role.r", "aws_iam_role"),
            resource("aws_iam_role_policy.p", "aws_iam_role_policy", {"role": {"$res": "aws_iam_role.r", "attr": "id"},
                                                                      "policy": {"$res": "data.aws_iam_policy_document.d", "attr": "json"}}),
            resource("data.aws_iam_policy_document.d", "aws_iam_policy_document", {"statement": statements}),
            resource("aws_dynamodb_table.t", "aws_dynamodb_table", {"name": "t"}), resource("aws_s3_bucket.b", "aws_s3_bucket", {"bucket": "b"}),
            resource("aws_sns_topic.s", "aws_sns_topic", {"name": "s"}), *extra_res,
        ], [ref("aws_lambda_function.f", "role", "aws_iam_role.r", "arn"), ref("aws_iam_role_policy.p", "role", "aws_iam_role.r", "id"),
            ref("aws_iam_role_policy.p", "policy", "data.aws_iam_policy_document.d", "json"), *extra_refs])

    def test_tf_policy_document(self):
        st = [{"actions": ["dynamodb:GetItem"], "resources": [{"$res": "aws_dynamodb_table.t", "attr": "arn"}]},
              {"actions": ["s3:PutObject"], "resources": ["arn:aws:s3:::b/*"]},
              {"actions": ["sns:Publish", "dynamodb:GetItem"], "resources": ["arn:aws:sns:r:1:s"]},  # 上の行（request→event→data）が優先
              {"actions": ["logs:PutLogEvents"], "resources": ["arn:aws:sns:r:1:s"]},  # 表に無いアクション: 辺にしない
              {"effect": "Deny", "actions": ["s3:GetObject"], "resources": ["arn:aws:s3:::b"]},
              {"actions": ["dynamodb:*"], "resources": ["arn:aws:dynamodb:r:1:table/*"]}]  # ワイルドカード: 照合しない
        e, r, _ = self._tf(st, extra_refs=[ref("data.aws_iam_policy_document.d", "statement[0].resources[0]", "aws_dynamodb_table.t", "arn")])
        self.assertEqual(e, {"lambda_function/f->dynamodb_table/t": ("data", "", "inferred"),
                             "lambda_function/f->s3_bucket/b": ("data", "", "inferred"),
                             "lambda_function/f->sns_topic/s": ("event", "", "inferred")})
        self.assertEqual(r["lambda_function/f->dynamodb_table/t"], ["E-IAM"])

    def test_suppress_and_merge_with_env(self):
        st = [{"actions": ["dynamodb:GetRecords"], "resources": [{"$res": "aws_dynamodb_table.t", "attr": "stream_arn"}]},
              {"actions": ["sns:Publish"], "resources": [{"$res": "aws_sns_topic.s", "attr": "arn"}]}]
        e, r, _ = self._tf(st, [resource("aws_lambda_event_source_mapping.m", "aws_lambda_event_source_mapping")], [
            ref("data.aws_iam_policy_document.d", "statement[0].resources[0]", "aws_dynamodb_table.t", "stream_arn"),
            ref("data.aws_iam_policy_document.d", "statement[1].resources[0]", "aws_sns_topic.s", "arn"),
            ref("aws_lambda_event_source_mapping.m", "event_source_arn", "aws_dynamodb_table.t", "stream_arn"),
            ref("aws_lambda_event_source_mapping.m", "function_name", "aws_lambda_function.f", "arn"),
            ref("aws_lambda_function.f", "environment[0].variables.TOPIC", "aws_sns_topic.s", "arn")])
        # ストリームを読む権限（関数 → テーブル）は、ESM（テーブル → 関数）と逆向きなので作らず、ESM の辺の根拠に E-IAM-SUPPRESS
        self.assertEqual(e, {"dynamodb_table/t->lambda_function/f": ("event", "", "derived"),
                             "lambda_function/f->sns_topic/s": ("event", "", "confirmed")})  # E-MERGE: 確信度は強い方
        self.assertEqual(r["dynamodb_table/t->lambda_function/f"], ["E-IAM-SUPPRESS", "R-LAMBDA-ESM"])
        self.assertEqual(r["lambda_function/f->sns_topic/s"], ["E-ENV-REF", "E-IAM"])

    def test_cfn_role_policies_and_sam_templates(self):
        e, r, _ = norm("cfn", [
            resource("Fn", "AWS::Lambda::Function", {"FunctionName": "fn"}, fmt="cfn"),
            resource("Role", "AWS::IAM::Role", {"Policies": [{"PolicyDocument": {"Statement": [
                {"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": {"$res": "Sam", "attr": "Arn"}},
                {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": {"$concat": [{"$res": "B", "attr": "Arn"}, "/*"]}},
                {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": {"$concat": [{"$res": "T", "attr": "Arn"}, "/index/*"]}}]}}]},
                     fmt="cfn"),
            resource("Sam", "AWS::Serverless::Function", {"FunctionName": "sam", "Policies": [
                {"DynamoDBCrudPolicy": {"TableName": {"$res": "T", "attr": None}}}, "AWSLambdaBasicExecutionRole"]}, fmt="cfn"),
            resource("T", "AWS::DynamoDB::Table", {"TableName": "t"}, fmt="cfn"), resource("B", "AWS::S3::Bucket", {"BucketName": "b"}, fmt="cfn"),
        ], [ref("Fn", "Properties.Role", "Role", "Arn"),
            ref("Role", "Properties.Policies[0].PolicyDocument.Statement[0].Resource", "Sam", "Arn"),
            ref("Role", "Properties.Policies[0].PolicyDocument.Statement[1].Resource", "B", "Arn"),
            ref("Role", "Properties.Policies[0].PolicyDocument.Statement[2].Resource", "T", "Arn"),
            ref("Sam", "Properties.Policies[0].DynamoDBCrudPolicy.TableName", "T")])
        self.assertEqual(e, {"lambda_function/fn->lambda_function/sam": ("request", "", "inferred"),
                             "lambda_function/fn->s3_bucket/b": ("data", "", "inferred"),  # <bucket の ARN>/* は S3 だけ
                             "lambda_function/sam->dynamodb_table/t": ("data", "", "inferred")})  # SAM のポリシーテンプレート


class ReviewFixesTest(unittest.TestCase):
    def test_sam_policies_as_one_mapping(self):
        # SAM の Policies は 1 つの mapping でもよい（T07s の形）。位置は `Properties.Policies`（添字なし）
        e, r, _ = norm("cfn", [
            resource("Fn", "AWS::Serverless::Function",
                     {"FunctionName": "fn", "Policies": {"DynamoDBCrudPolicy": {"TableName": {"$res": "T", "attr": None}}}}, fmt="cfn"),
            resource("T", "AWS::DynamoDB::Table", {"TableName": "t"}, fmt="cfn"),
        ], [ref("Fn", "Properties.Policies.DynamoDBCrudPolicy.TableName", "T")])
        self.assertEqual(e, {"lambda_function/fn->dynamodb_table/t": ("data", "", "inferred")})

    def test_sam_state_machine_policies(self):
        # SAM のステートマシンも Policies を書ける（T11s の形）。ステートマシン自身が引き受ける
        e, r, _ = norm("cfn", [
            resource("Sm", "AWS::Serverless::StateMachine",
                     {"Name": "sm", "Policies": [{"DynamoDBCrudPolicy": {"TableName": {"$res": "T", "attr": None}}}]}, fmt="cfn"),
            resource("T", "AWS::DynamoDB::Table", {"TableName": "t"}, fmt="cfn"),
        ], [ref("Sm", "Properties.Policies[0].DynamoDBCrudPolicy.TableName", "T")])
        self.assertEqual(e, {"sfn_state_machine/sm->dynamodb_table/t": ("data", "", "inferred")})

    def test_blackbox_endpoints_are_inferred_requests(self):
        e, r, _ = norm("tf", [
            resource("aws_route53_record.r", "aws_route53_record", {"name": "www"}),
            resource("aws_cloudfront_distribution.d", "aws_cloudfront_distribution", {"tags": {"Name": "cdn"}}),
            resource("module.site", "module", via="module_blackbox", source="git::https://x/y.git"),
        ], [ref("aws_route53_record.r", "alias[0].name", "module.site", "domain"),
            ref("aws_cloudfront_distribution.d", "origin[0].domain_name", "module.site", "bucket_domain")])
        self.assertEqual(e, {"route53_record/www->module/site": ("request", "", "inferred"),
                             "cloudfront_distribution/cdn->module/site": ("request", "", "inferred")})

    def test_action_wildcards_and_kind_order(self):
        from aws_iac_diagram.normalize import iam
        from aws_iac_diagram.normalize.relations_base import Context
        ctx = Context(None, {}, {}, RULES)
        self.assertEqual(iam.action_kind(ctx, ["s3:*"]), "data")  # 文の側のワイルドカード（同じサービスの中）
        self.assertEqual(iam.action_kind(ctx, ["s3:Get*"]), "data")
        self.assertEqual(iam.action_kind(ctx, ["sqs:*"]), "event")  # sqs:SendMessage（event）の行が sqs:ReceiveMessage（data）より上
        self.assertIsNone(iam.action_kind(ctx, ["*"]))  # `*` だけは当てない
        self.assertIsNone(iam.action_kind(ctx, ["ec2:*"]))
        # 別の文に分かれても、同じ組の kind は [[iam_action_kind]] の行の順（event が data より先）
        st = [{"actions": ["sqs:ReceiveMessage"], "resources": [{"$res": "aws_sqs_queue.q", "attr": "arn"}]},
              {"actions": ["sqs:SendMessage"], "resources": [{"$res": "aws_sqs_queue.q", "attr": "arn"}]}]
        e, r, _ = IamTest._tf(None, st, [resource("aws_sqs_queue.q", "aws_sqs_queue", {"name": "q"})],
                              [ref("data.aws_iam_policy_document.d", "statement[0].resources[0]", "aws_sqs_queue.q", "arn"),
                               ref("data.aws_iam_policy_document.d", "statement[1].resources[0]", "aws_sqs_queue.q", "arn")])
        self.assertEqual(e["lambda_function/f->sqs_queue/q"], ("event", "", "inferred"))

    def test_concat_arn_with_one_reference(self):
        st = [{"actions": ["s3:GetObject"], "resources": [{"$concat": ["arn:aws:s3:::", {"$res": "aws_s3_bucket.b", "attr": "bucket"}, "/*"]}]},
              {"actions": ["sns:Publish"], "resources": [{"$concat": ["arn:aws:sqs:", {"$pseudo": "AWS::Region"}, ":1:",
                                                                        {"$res": "aws_sns_topic.s", "attr": "name"}]}]},  # サービスが違う
              {"actions": ["dynamodb:GetItem"], "resources": [{"$concat": ["arn:aws:dynamodb:r:1:table/",
                                                                           {"$res": "aws_dynamodb_table.t", "attr": "name"}, "/index/*"]}]}]
        e, r, _ = IamTest._tf(None, st, extra_refs=[
            ref("data.aws_iam_policy_document.d", "statement[0].resources[0]", "aws_s3_bucket.b", "bucket"),
            ref("data.aws_iam_policy_document.d", "statement[1].resources[0]", "aws_sns_topic.s", "name"),
            ref("data.aws_iam_policy_document.d", "statement[2].resources[0]", "aws_dynamodb_table.t", "name")])
        self.assertEqual(e, {"lambda_function/f->s3_bucket/b": ("data", "", "inferred")})  # 後ろが /* 以外・サービス違いは照合しない
        # CFN の !Sub（パーティション・リージョン・アカウントの $pseudo と参照 1 つ）
        sub_s3 = {"$concat": ["arn:", {"$pseudo": "AWS::Partition"}, ":s3:::", {"$res": "B", "attr": None}, "/*"]}
        sub_sqs = {"$concat": ["arn:", {"$pseudo": "AWS::Partition"}, ":sqs:", {"$pseudo": "AWS::Region"}, ":", {"$pseudo": "AWS::AccountId"},
                               ":", {"$res": "Q", "attr": "QueueName"}]}
        e, r, _ = norm("cfn", [
            resource("Fn", "AWS::Lambda::Function", {"FunctionName": "fn"}, fmt="cfn"),
            resource("Role", "AWS::IAM::Role", {"Policies": [{"PolicyDocument": {"Statement": [
                {"Effect": "Allow", "Action": "s3:GetObject", "Resource": sub_s3},
                {"Effect": "Allow", "Action": "sqs:SendMessage", "Resource": sub_sqs}]}}]}, fmt="cfn"),
            resource("B", "AWS::S3::Bucket", {"BucketName": "b"}, fmt="cfn"), resource("Q", "AWS::SQS::Queue", {"QueueName": "q"}, fmt="cfn"),
        ], [ref("Fn", "Properties.Role", "Role", "Arn"),
            ref("Role", "Properties.Policies[0].PolicyDocument.Statement[0].Resource", "B"),
            ref("Role", "Properties.Policies[0].PolicyDocument.Statement[1].Resource", "Q", "QueueName")])
        self.assertEqual(e, {"lambda_function/fn->s3_bucket/b": ("data", "", "inferred"),
                             "lambda_function/fn->sqs_queue/q": ("event", "", "inferred")})

    def test_arn_strings_match_exactly_one_and_the_same_region(self):
        st = [{"actions": ["sqs:SendMessage"], "resources": ["arn:aws:sqs:us-east-1:1:dup-q"]},
              {"actions": ["sns:Publish"], "resources": ["arn:aws:sns:ap-northeast-1:1:topic-1"]},
              {"actions": ["sns:Publish"], "resources": ["arn:aws:sns:ap-northeast-1:1:topic-2"]}]
        e, r, _ = IamTest._tf(None, st, [
            resource("aws_sqs_queue.a", "aws_sqs_queue", {"name": "dup-q"}), resource("module.m.aws_sqs_queue.b", "aws_sqs_queue", {"name": "dup-q"}),
            resource("aws_sns_topic.t1", "aws_sns_topic", {"name": "topic-1"}, region="us-west-2"),
            resource("aws_sns_topic.t2", "aws_sns_topic", {"name": "topic-2"})])
        self.assertEqual(set(e) - {"lambda_function/f->dynamodb_table/t"}, {"lambda_function/f->sns_topic/topic-2"})
        # dup-q は 2 つに当たるので作らない。topic-1 はリージョンが違う

    def test_env_str_ignores_short_alphabetic_values(self):
        e, r, _ = norm("tf", [
            fn("aws_lambda_function.f", "f", environment=[{"variables": {"STAGE": "prod", "OUT": "out-bucket"}}]),
            resource("aws_s3_bucket.p", "aws_s3_bucket", {"bucket": "prod"}), resource("aws_s3_bucket.o", "aws_s3_bucket", {"bucket": "out-bucket"}),
        ], [])
        self.assertEqual(set(e), {"lambda_function/f->s3_bucket/out-bucket"})  # STAGE=prod は名前 prod のバケットと結ばない


class MergeLabelTest(unittest.TestCase):
    def test_label_from_the_highest_rule_and_same_rule_joined(self):
        cands = [Candidate("a/x", "b/y", "E-ENV-REF", "data", "", ("e",)),
                 Candidate("a/x", "b/y", "R-SG", "network", "TCP 5432", ("s",)),
                 Candidate("a/x", "b/y", "R-SG", "network", "TCP 443", ("t",)),
                 Candidate("c/z", "d/w", "R-ROUTE", "route", "0.0.0.0/0", ("r",)),
                 Candidate("c/z", "d/w", "R-VPCE-GATEWAY", "route", "s3 prefix list", ("v",))]
        r = edges.merge(cands, RULES)
        got = {x["id"]: (x["kind"], x["label"]) for x in r.edges}
        # kind は優先順の高い E-ENV-REF、ラベルは空でない最初の規則（R-SG）の、同じ規則のラベルをつなぐ。同じ順位なら規則 ID の順
        self.assertEqual(got, {"a/x->b/y": ("data", "TCP 443, TCP 5432"), "c/z->d/w": ("route", "0.0.0.0/0")})


if __name__ == "__main__":
    unittest.main()
