"""正規化の段階 1（normalize/classify.py）: 仮分類の順序と、確定（finalize）。規則表は SKILL のもの（凍結した版）を使う。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.raw_builders import raw_ir, reference, resource
from aws_iac_diagram.core import rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import classify, nodes  # noqa: E402
from aws_iac_diagram.normalize.classify import Decision  # noqa: E402
from aws_iac_diagram.normalize.view import Index  # noqa: E402

RULES = rules_mod.default()


def decide(fmt: str, resources: list[dict], references: list[dict] | None = None) -> dict[str, Decision]:
    return classify.classify(Index(raw_ir(fmt, resources, references)), RULES)


def short(d: Decision) -> tuple:
    return (d.cls, d.rule or d.type_id, d.provisional)


class ProvisionalTest(unittest.TestCase):
    def test_disabled_comes_before_the_type(self):
        got = decide("tf", [resource("aws_instance.bastion", "aws_instance", enabled=False),
                            resource("aws_iam_role.r", "aws_iam_role", enabled=False),
                            resource("aws_instance.n[*]", "aws_instance", enabled=None, multiplicity="N")])
        self.assertEqual(short(got["aws_instance.bastion"]), ("hidden", "H-COND-FALSE", False))
        self.assertEqual(short(got["aws_iam_role.r"]), ("hidden", "H-COND-FALSE", False))
        self.assertEqual(short(got["aws_instance.n[*]"]), ("drawn", "ec2_instance", False))  # 決まらないものは描く

    def test_type_table(self):
        got = decide("tf", [
            resource("aws_vpc.a", "aws_vpc"),
            resource("aws_eip.e", "aws_eip"),
            resource("aws_route_table.r", "aws_route_table"),
            resource("aws_iam_role.r", "aws_iam_role"),
            resource("random_id.x", "random_id"),
            resource("aws_lb_listener.l", "aws_lb_listener"),
        ])
        self.assertEqual(short(got["aws_vpc.a"]), ("drawn", "vpc", False))
        self.assertEqual(short(got["aws_eip.e"]), ("merged_into", "M-EIP-NAT", True))
        self.assertEqual(short(got["aws_route_table.r"]), ("merged_into", "R-ROUTE", True))
        self.assertEqual(short(got["aws_iam_role.r"]), ("hidden", "H-IAM", False))
        self.assertEqual(short(got["random_id.x"]), ("hidden", "H-UTILITY", False))  # `random_*`
        self.assertEqual(short(got["aws_lb_listener.l"]), ("merged_into", "R-LB-LISTENER", True))

    def test_when_prop_in_and_default(self):
        got = decide("tf", [
            resource("aws_lb.a", "aws_lb", {"load_balancer_type": "application"}),
            resource("aws_lb.d", "aws_lb", {}),  # 省略時は application（default）
            resource("aws_lb.u", "aws_lb", {"load_balancer_type": {"$unknown": "x"}}),  # 評価できない値も default
            resource("aws_lb.n", "aws_lb", {"load_balancer_type": "network"}),  # 表に無い（NLB）
            resource("aws_security_group_rule.i", "aws_security_group_rule", {"type": "ingress"}),
            resource("aws_security_group_rule.e", "aws_security_group_rule", {"type": "egress"}),
            resource("aws_security_group_rule.x", "aws_security_group_rule", {}),  # default が無い → どちらでもない
            resource("aws_apigatewayv2_api.h", "aws_apigatewayv2_api", {"protocol_type": "HTTP"}),
            resource("aws_apigatewayv2_api.w", "aws_apigatewayv2_api", {"protocol_type": "WEBSOCKET"}),
        ])
        self.assertEqual(short(got["aws_lb.a"]), ("drawn", "alb", False))
        self.assertEqual(short(got["aws_lb.d"]), ("drawn", "alb", False))
        self.assertEqual(short(got["aws_lb.u"]), ("drawn", "alb", False))
        self.assertEqual(got["aws_lb.n"].cls, "unknown")
        self.assertEqual(short(got["aws_security_group_rule.i"]), ("merged_into", "R-SG", True))
        self.assertEqual(short(got["aws_security_group_rule.e"]), ("hidden", "H-SG-EGRESS", False))
        self.assertEqual(got["aws_security_group_rule.x"].cls, "unknown")
        self.assertEqual(short(got["aws_apigatewayv2_api.h"]), ("drawn", "apigw_http_api", False))
        self.assertEqual(got["aws_apigatewayv2_api.w"].cls, "unknown")
        # when.types の外の型には条件が効かない（R-SG の aws_security_group）
        self.assertEqual(short(decide("tf", [resource("aws_security_group.s", "aws_security_group")])["aws_security_group.s"]),
                         ("merged_into", "R-SG", True))

    def test_cfn_when_and_via(self):
        got = decide("cfn", [
            resource("Alb", "AWS::ElasticLoadBalancingV2::LoadBalancer", {"Type": "application"}, fmt="cfn"),
            resource("Nlb", "AWS::ElasticLoadBalancingV2::LoadBalancer", {"Type": "network"}, fmt="cfn"),
            resource("Net", "AWS::CloudFormation::Stack", {"TemplateURL": "./net.yaml"}, fmt="cfn"),
            resource("Lost", "AWS::CloudFormation::Stack", {"TemplateURL": "https://x/y.yaml"}, fmt="cfn", via="module_blackbox"),
            resource("Net/Vpc", "AWS::EC2::VPC", fmt="cfn", via="nested_stack"),
            resource("Fn", "AWS::Serverless::Function", fmt="cfn"),
            resource("Custom", "Custom::Thing", fmt="cfn"),
        ])
        self.assertEqual(short(got["Alb"]), ("drawn", "alb", False))
        self.assertEqual(got["Nlb"].cls, "unknown")
        self.assertEqual(short(got["Net"]), ("hidden", "H-NESTED-STACK", False))
        self.assertEqual(short(got["Lost"]), ("drawn", "module", False))
        self.assertEqual(short(got["Net/Vpc"]), ("drawn", "vpc", False))
        self.assertEqual(short(got["Fn"]), ("drawn", "lambda_function", False))
        self.assertEqual(got["Custom"].cls, "unknown")

    def test_blackbox_modules(self):
        got = decide("tf", [
            resource("module.kms", "module", source="terraform-aws-modules/kms/aws", via="module_blackbox"),
            resource("module.irsa", "module", source="terraform-aws-modules/iam/aws//modules/iam-assumable-role-with-oidc",
                     via="module_blackbox"),
            resource("module.gone", "module", source="terraform-aws-modules/kms/aws", via="module_blackbox", enabled=False),
        ])
        self.assertEqual(short(got["module.kms"]), ("drawn", "module", False))
        self.assertEqual(short(got["module.irsa"]), ("hidden", "H-IAM", False))
        self.assertEqual(short(got["module.gone"]), ("hidden", "H-COND-FALSE", False))

    def test_tf_data(self):
        got = decide("tf", [
            resource("data.aws_iam_policy_document.p", "aws_iam_policy_document"),
            resource("data.aws_iam_policy.p", "aws_iam_policy"),
            resource("data.aws_ssm_parameter.ami", "aws_ssm_parameter"),
            resource("data.archive_file.zip", "archive_file"),
            resource("data.aws_vpc.used", "aws_vpc"),
            resource("data.aws_vpc.unused", "aws_vpc"),
            resource("data.aws_s3_bucket.only_by_hidden", "aws_s3_bucket"),
            resource("data.aws_lb.not_data_type", "aws_lb"),
            resource("aws_subnet.a", "aws_subnet"),
            resource("aws_iam_role_policy.r", "aws_iam_role_policy"),
        ], [
            reference("aws_subnet.a", "vpc_id", "data.aws_vpc.used", "id"),
            reference("aws_iam_role_policy.r", "policy", "data.aws_s3_bucket.only_by_hidden", "arn"),
            reference("aws_subnet.a", "depends_on", "data.aws_vpc.unused", fn="depends_on"),  # DependsOn は「参照」に数えない
        ])
        self.assertEqual(short(got["data.aws_iam_policy_document.p"]), ("hidden", "H-IAM", False))
        self.assertEqual(short(got["data.aws_iam_policy.p"]), ("hidden", "H-IAM", False))
        self.assertEqual(short(got["data.aws_ssm_parameter.ami"]), ("hidden", "H-DATA", False))
        self.assertEqual(short(got["data.archive_file.zip"]), ("hidden", "H-DATA", False))  # AWS 以外でも data が先
        self.assertEqual(short(got["data.aws_vpc.used"]), ("drawn", "vpc", False))
        self.assertEqual(short(got["data.aws_vpc.unused"]), ("hidden", "H-DATA", False))
        self.assertEqual(short(got["data.aws_s3_bucket.only_by_hidden"]), ("hidden", "H-DATA", False))
        self.assertEqual(short(got["data.aws_lb.not_data_type"]), ("hidden", "H-DATA", False))

    def test_data_used_by_relations_merges_and_other_data(self):
        # T09 の形: 既存のバケット（data）を参照するのは、関係リソース（R-BEDROCK-DATA-SOURCE）と IAM のポリシーだけ → 描く
        got = decide("tf", [
            resource("module.kb.data.aws_s3_bucket.docs", "aws_s3_bucket"),
            resource("module.kb.aws_bedrockagent_data_source.ds", "aws_bedrockagent_data_source"),
            resource("module.kb.aws_iam_role_policy.p", "aws_iam_role_policy"),
            resource("data.aws_s3_bucket.only_iam", "aws_s3_bucket"),
        ], [
            reference("module.kb.aws_bedrockagent_data_source.ds", "data_source_configuration[0].s3_configuration[0].bucket_arn",
                      "module.kb.data.aws_s3_bucket.docs", "arn"),
            reference("module.kb.aws_iam_role_policy.p", "policy.Statement[0].Resource", "module.kb.data.aws_s3_bucket.docs", "arn"),
            reference("module.kb.aws_iam_role_policy.p", "policy.Statement[1].Resource", "data.aws_s3_bucket.only_iam", "arn"),
        ])
        self.assertEqual(short(got["module.kb.data.aws_s3_bucket.docs"]), ("drawn", "s3_bucket", False))
        self.assertEqual(short(got["data.aws_s3_bucket.only_iam"]), ("hidden", "H-DATA", False))
        # 描く data から参照される data も描く（data.aws_subnet → data.aws_vpc）。描くノードに統合される M-* からの参照も数える
        got = decide("tf", [
            resource("aws_instance.app", "aws_instance"),
            resource("data.aws_subnet.s", "aws_subnet"),
            resource("data.aws_vpc.v", "aws_vpc"),
            resource("aws_s3_bucket.b", "aws_s3_bucket"),
            resource("data.aws_s3_bucket.logs", "aws_s3_bucket"),
            resource("aws_s3_bucket_versioning.l", "aws_s3_bucket_versioning"),
        ], [
            reference("aws_instance.app", "subnet_id", "data.aws_subnet.s", "id"),
            reference("data.aws_subnet.s", "vpc_id", "data.aws_vpc.v", "id"),
            reference("aws_s3_bucket_versioning.l", "bucket", "aws_s3_bucket.b", "id"),
            reference("aws_s3_bucket_versioning.l", "expected_bucket_owner", "data.aws_s3_bucket.logs", "id"),
        ])
        self.assertEqual(short(got["data.aws_subnet.s"]), ("drawn", "subnet", False))
        self.assertEqual(short(got["data.aws_vpc.v"]), ("drawn", "vpc", False))
        self.assertEqual(short(got["data.aws_s3_bucket.logs"]), ("drawn", "s3_bucket", False))
        # 描かない data からの参照は数えない
        got = decide("tf", [resource("data.aws_subnet.s", "aws_subnet"), resource("data.aws_vpc.v", "aws_vpc")],
                     [reference("data.aws_subnet.s", "vpc_id", "data.aws_vpc.v", "id")])
        self.assertEqual({a: d.rule for a, d in got.items()}, {"data.aws_subnet.s": "H-DATA", "data.aws_vpc.v": "H-DATA"})

    def test_other_providers(self):
        got = decide("tf", [
            resource("kubernetes_namespace.n", "kubernetes_namespace"),
            resource("opensearch_index.i", "opensearch_index"),
            resource("awscc_ec2_vpc.v", "awscc_ec2_vpc"),
            resource("awscc_bedrock_knowledge_base.k", "awscc_bedrock_knowledge_base"),
            resource("awscc_ec2_unheard_of.x", "awscc_ec2_unheard_of"),
            resource("aws_unheard_of.x", "aws_unheard_of"),
        ])
        self.assertEqual(short(got["kubernetes_namespace.n"]), ("hidden", "H-NONAWS", False))
        self.assertEqual(short(got["opensearch_index.i"]), ("merged_into", "M-AOSS-INDEX", True))  # 型の行が先
        self.assertEqual(short(got["awscc_ec2_vpc.v"]), ("drawn", "vpc", False))  # 同じ名前の CFN の型（AWS::EC2::VPC）
        self.assertEqual(short(got["awscc_bedrock_knowledge_base.k"]), ("drawn", "bedrock_knowledge_base", False))
        self.assertEqual(got["awscc_ec2_unheard_of.x"].cls, "unknown")  # awscc は AWS のプロバイダ
        self.assertEqual(got["aws_unheard_of.x"].cls, "unknown")

    def test_entry_shape(self):
        self.assertEqual(Decision("hidden", rule="H-IAM").entry(), {"class": "hidden", "rule": "H-IAM"})
        self.assertEqual(Decision("merged_into", rule="M-EIP-NAT", into=("b/x", "a/y")).entry(),
                         {"class": "merged_into", "rule": "M-EIP-NAT", "into": ["a/y", "b/x"]})
        self.assertEqual(Decision("drawn", type_id="vpc").entry(), {"class": "drawn"})
        self.assertEqual(Decision("unknown").entry(), {"class": "unknown"})


class FinalizeTest(unittest.TestCase):
    def run_all(self, fmt, resources, references=(), edges=None):
        idx = Index(raw_ir(fmt, resources, list(references)))
        dec = classify.classify(idx, RULES)
        node_by_address, _ = nodes.build_nodes(idx, dec, RULES)
        return classify.finalize(dec, idx, node_by_address, RULES, edges=edges)

    def test_merge_by_reference_either_direction(self):
        fin = self.run_all("tf", [
            resource("aws_nat_gateway.n", "aws_nat_gateway", {"tags": {"Name": "nat"}}),
            resource("aws_eip.e", "aws_eip"),
            resource("aws_ecs_cluster.c", "aws_ecs_cluster"),
            resource("aws_ecs_service.a", "aws_ecs_service", {"name": "a"}),
            resource("aws_ecs_service.b", "aws_ecs_service", {"name": "b"}),
            resource("aws_s3_bucket.b", "aws_s3_bucket", {"bucket": "bk"}),
            resource("aws_s3_bucket_versioning.v", "aws_s3_bucket_versioning"),
        ], [
            reference("aws_nat_gateway.n", "allocation_id", "aws_eip.e", "id"),        # 統合先 → 統合されるもの
            reference("aws_ecs_service.a", "cluster", "aws_ecs_cluster.c", "id"),
            reference("aws_ecs_service.b", "cluster", "aws_ecs_cluster.c", "id"),
            reference("aws_s3_bucket_versioning.v", "bucket", "aws_s3_bucket.b", "id"),  # 統合されるもの → 統合先
        ])
        d = fin.decisions
        self.assertEqual((d["aws_eip.e"].into, d["aws_eip.e"].provisional), (("nat_gateway/nat",),False))
        self.assertEqual(d["aws_ecs_cluster.c"].into, ("ecs_service/a", "ecs_service/b"))  # そのクラスタのサービスすべて
        self.assertEqual(d["aws_s3_bucket_versioning.v"].into, ("s3_bucket/bk",))
        self.assertEqual(fin.diagnostics, [])

    def test_merge_ignores_other_node_types_and_uses_depends_on_last(self):
        fin = self.run_all("tf", [
            resource("aws_ecs_task_definition.t", "aws_ecs_task_definition"),
            resource("aws_db_instance.d", "aws_db_instance", {"identifier": "db"}),
            resource("aws_opensearchserverless_collection.c", "aws_opensearchserverless_collection", {"name": "kb"}),
            resource("opensearch_index.i", "opensearch_index"),
        ], [
            reference("aws_ecs_task_definition.t", "container_definitions", "aws_db_instance.d", "address"),
            reference("opensearch_index.i", "depends_on", "aws_opensearchserverless_collection.c", fn="depends_on"),
        ])
        d = fin.decisions
        # タスク定義が参照する DB は統合先の型（ecs_service）でないので使わない。統合先が無ければ H-NO-TARGET（非表示）、診断も出す
        self.assertEqual(short(d["aws_ecs_task_definition.t"]), ("hidden", "H-NO-TARGET", False))
        self.assertEqual(d["aws_ecs_task_definition.t"].entry(), {"class": "hidden", "rule": "H-NO-TARGET"})
        self.assertEqual([(x["code"], x["level"], x["address"]) for x in fin.diagnostics],
                         [("NORM-MERGE-TARGET", "warn", "aws_ecs_task_definition.t"),
                          ("NORM-MERGE-DEPENDS-ON", "info", "opensearch_index.i")])
        self.assertEqual(d["opensearch_index.i"].into, ("opensearchserverless_collection/kb",))  # DependsOn しか手がかりが無い

    def test_merge_by_name_for_aoss_policies(self):
        fin = self.run_all("cfn", [
            resource("Collection", "AWS::OpenSearchServerless::Collection", {"Name": "rag-kb"}, fmt="cfn"),
            resource("Other", "AWS::OpenSearchServerless::Collection", {"Name": "other"}, fmt="cfn"),
            resource("Enc", "AWS::OpenSearchServerless::SecurityPolicy",
                     {"Policy": {"$json": {"Rules": [{"ResourceType": "collection", "Resource": ["collection/rag-kb"]}]}}}, fmt="cfn"),
            resource("Data", "AWS::OpenSearchServerless::AccessPolicy",
                     {"Policy": {"$json": [{"Rules": [{"Resource": ["index/other/*"]}, {"Resource": ["collection/*"]}]}]}}, fmt="cfn"),
        ], [reference("Collection", "DependsOn", "Enc", fn="DependsOn")])
        d = fin.decisions
        self.assertEqual(d["Enc"].into, ("opensearchserverless_collection/rag-kb",))
        self.assertEqual(d["Data"].into, ("opensearchserverless_collection/other",))  # ワイルドカードは名前にしない

    def test_merge_through_another_merge(self):
        # 起動テンプレート → ノードグループ（M-EKS-PARTS でクラスタに統合）→ クラスタ
        fin = self.run_all("tf", [
            resource("aws_eks_cluster.c", "aws_eks_cluster", {"name": "eks"}),
            resource("aws_eks_node_group.g", "aws_eks_node_group"),
            resource("aws_launch_template.t", "aws_launch_template"),
        ], [
            reference("aws_eks_node_group.g", "cluster_name", "aws_eks_cluster.c", "name"),
            reference("aws_eks_node_group.g", "launch_template[0].id", "aws_launch_template.t", "id"),
        ])
        self.assertEqual(fin.decisions["aws_launch_template.t"].into, ("eks_cluster/eks",))
        self.assertFalse(fin.decisions["aws_launch_template.t"].provisional)

    def test_depends_on_is_only_the_merged_resources_own_and_unique(self):
        # 反例（レビュー）: バケットポリシーの bucket はリテラルの "a"（入力に無いバケット）。ほかのバケットがポリシーに
        # DependsOn しているだけ → そのバケットに統合しない
        fin = self.run_all("tf", [
            resource("aws_s3_bucket_policy.p", "aws_s3_bucket_policy", {"bucket": "a"}),
            resource("aws_s3_bucket.other", "aws_s3_bucket", {"bucket": "other"}),
        ], [reference("aws_s3_bucket.other", "depends_on", "aws_s3_bucket_policy.p", fn="depends_on")])
        self.assertEqual(short(fin.decisions["aws_s3_bucket_policy.p"]), ("hidden", "H-NO-TARGET", False))
        self.assertEqual([x["code"] for x in fin.diagnostics], ["NORM-MERGE-TARGET"])
        # 自分の DependsOn でも、候補が 2 つなら使わない
        fin = self.run_all("tf", [
            resource("opensearch_index.i", "opensearch_index"),
            resource("aws_opensearchserverless_collection.a", "aws_opensearchserverless_collection", {"name": "a"}),
            resource("aws_opensearchserverless_collection.b", "aws_opensearchserverless_collection", {"name": "b"}),
        ], [reference("opensearch_index.i", "depends_on", "aws_opensearchserverless_collection.a", fn="depends_on"),
            reference("opensearch_index.i", "depends_on", "aws_opensearchserverless_collection.b", fn="depends_on")])
        self.assertEqual(short(fin.decisions["opensearch_index.i"]), ("hidden", "H-NO-TARGET", False))
        self.assertEqual([x["code"] for x in fin.diagnostics], ["NORM-MERGE-TARGET"])

    def test_primary_attribute_wins_and_ambiguity_is_reported(self):
        buckets = [resource("aws_s3_bucket.a", "aws_s3_bucket", {"bucket": "a"}),
                   resource("aws_s3_bucket.b", "aws_s3_bucket", {"bucket": "b"}),
                   resource("aws_s3_bucket_policy.p", "aws_s3_bucket_policy")]
        # バケットポリシーの policy が別のバケットの ARN を参照していても、統合先は bucket の参照先だけ
        fin = self.run_all("tf", buckets, [reference("aws_s3_bucket_policy.p", "bucket", "aws_s3_bucket.a", "id"),
                                           reference("aws_s3_bucket_policy.p", "policy.Statement[0].Resource", "aws_s3_bucket.b", "arn")])
        self.assertEqual(fin.decisions["aws_s3_bucket_policy.p"].into, ("s3_bucket/a",))
        self.assertEqual(fin.diagnostics, [])
        # 主の属性の参照が無く、ほかの参照で 2 つに当たる（親が 1 つの規則）→ 決まった順の最初の 1 つと warn
        fin = self.run_all("tf", buckets, [reference("aws_s3_bucket_policy.p", "policy.Statement[0].Resource", "aws_s3_bucket.b", "arn"),
                                           reference("aws_s3_bucket_policy.p", "policy.Statement[1].Resource", "aws_s3_bucket.a", "arn")])
        self.assertEqual(fin.decisions["aws_s3_bucket_policy.p"].into, ("s3_bucket/a",))
        self.assertEqual([(x["code"], x["level"]) for x in fin.diagnostics], [("NORM-MERGE-AMBIGUOUS", "warn")])

    def test_bucket_policy_matches_the_bucket_name(self):
        # C02 の形: バケットポリシーの Bucket は !Sub の文字列（$concat と $pseudo）で、バケットの BucketName と同じ形
        def name(prefix):
            return {"$concat": [prefix, {"$pseudo": "AWS::Region"}, "-", {"$pseudo": "AWS::AccountId"}]}
        fin = self.run_all("cfn", [
            resource("Content", "AWS::S3::Bucket", {"BucketName": name("site-content-")}, fmt="cfn"),
            resource("Logs", "AWS::S3::Bucket", {"BucketName": name("site-content-logs-")}, fmt="cfn"),
            resource("Plain", "AWS::S3::Bucket", {"BucketName": "plain"}, fmt="cfn"),
            resource("ContentPolicy", "AWS::S3::BucketPolicy", {"Bucket": name("site-content-")}, fmt="cfn"),
            resource("LogsPolicy", "AWS::S3::BucketPolicy", {"Bucket": name("site-content-logs-")}, fmt="cfn"),
            resource("PlainPolicy", "AWS::S3::BucketPolicy", {"Bucket": "plain"}, fmt="cfn"),
            resource("Lost", "AWS::S3::BucketPolicy", {"Bucket": {"$concat": [{"$res": "X", "attr": None}, "-x"]}}, fmt="cfn"),
        ])
        d = fin.decisions
        got = {a: d[a].into for a in ("ContentPolicy", "LogsPolicy", "PlainPolicy")}
        # 名前が印のバケットは論理名が名前（id の key）になる
        self.assertEqual(got, {"ContentPolicy": ("s3_bucket/content",), "LogsPolicy": ("s3_bucket/logs",),
                               "PlainPolicy": ("s3_bucket/plain",)})
        self.assertEqual(short(d["Lost"]), ("hidden", "H-NO-TARGET", False))  # $res を含む値は名前として比べない

    def test_references_pass_through_one_utility_resource(self):
        # T16 の形: ノードグループの cluster_name → time_sleep → クラスタ。起動テンプレートはノードグループを通して決まる
        fin = self.run_all("tf", [
            resource("aws_eks_cluster.c", "aws_eks_cluster", {"name": "eks"}),
            resource("time_sleep.wait", "time_sleep"),
            resource("aws_eks_node_group.g", "aws_eks_node_group"),
            resource("aws_launch_template.t", "aws_launch_template"),
        ], [
            reference("time_sleep.wait", "triggers.cluster_name", "aws_eks_cluster.c", "name"),
            reference("aws_eks_node_group.g", "cluster_name", "time_sleep.wait", "triggers"),
            reference("aws_eks_node_group.g", "launch_template[0].id", "aws_launch_template.t", "id"),
        ])
        self.assertEqual(fin.decisions["aws_eks_node_group.g"].into, ("eks_cluster/eks",))
        self.assertEqual(fin.decisions["aws_launch_template.t"].into, ("eks_cluster/eks",))
        self.assertEqual(fin.diagnostics, [])

    def test_two_step_merges_do_not_depend_on_the_order(self):
        res = [resource("aws_eks_cluster.c", "aws_eks_cluster", {"name": "eks"}),
               resource("aws_eks_node_group.a", "aws_eks_node_group"), resource("aws_eks_node_group.z", "aws_eks_node_group"),
               resource("aws_launch_template.m", "aws_launch_template")]
        refs = [reference("aws_eks_node_group.a", "cluster_name", "aws_eks_cluster.c", "name"),
                reference("aws_eks_node_group.a", "launch_template[0].id", "aws_launch_template.m", "id"),
                reference("aws_eks_node_group.z", "launch_template[0].id", "aws_launch_template.m", "id")]
        one = self.run_all("tf", res, refs)
        two = self.run_all("tf", list(reversed(res)), list(reversed(refs)))
        self.assertEqual(one, two)
        # 起動テンプレートは 1 段目（ノードグループ a を通して）、ノードグループ z は 2 段目（起動テンプレートを通して）で決まる
        self.assertEqual(one.decisions["aws_launch_template.m"].into, ("eks_cluster/eks",))
        self.assertEqual(one.decisions["aws_eks_node_group.z"].into, ("eks_cluster/eks",))

    def test_relations_wait_for_edges(self):
        res = [resource("aws_security_group.used", "aws_security_group"), resource("aws_security_group.idle", "aws_security_group"),
               resource("aws_route_table.r", "aws_route_table"), resource("aws_lb_listener.l", "aws_lb_listener")]
        fin = self.run_all("tf", res)
        for a in ("aws_security_group.used", "aws_security_group.idle", "aws_route_table.r", "aws_lb_listener.l"):
            self.assertEqual((fin.decisions[a].cls, fin.decisions[a].into, fin.decisions[a].provisional), ("merged_into", (), True), a)
        # 辺の段階の結果を渡すと確定する: 辺があれば into は辺、無ければ fallback（fallback の無い規則は H-RELATION-NOEDGE）
        fin = self.run_all("tf", res, edges={"aws_security_group.used": ["b/y->c/z", "a/x->b/y", "a/x->b/y"]})
        d = fin.decisions
        self.assertEqual(short(d["aws_security_group.used"]), ("merged_into", "R-SG", False))
        self.assertEqual(d["aws_security_group.used"].into, ("a/x->b/y", "b/y->c/z"))
        self.assertEqual(short(d["aws_security_group.idle"]), ("hidden", "H-SG-NOEDGE", False))
        self.assertEqual(short(d["aws_route_table.r"]), ("hidden", "H-RT-NOROUTE", False))
        self.assertEqual(short(d["aws_lb_listener.l"]), ("hidden", "H-RELATION-NOEDGE", False))
        self.assertEqual([(x["code"], x["level"], x["address"]) for x in fin.diagnostics],
                         [("NORM-RELATION-NOEDGE", "warn", "aws_lb_listener.l")])


if __name__ == "__main__":
    unittest.main()
