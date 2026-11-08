"""関係リソース（R-*）のハンドラ（normalize/relations_*.py）と、辺のまとめ方（edges.py）・分類の確定（classify.apply_edges）。
TF と CFN（SAM を含む）の形をそれぞれ小さな raw IR で確かめる。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.raw_builders import raw_ir, ref, resource
from aws_iac_diagram.core import rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import build, edges  # noqa: E402
from aws_iac_diagram.normalize.relations_base import Candidate, path_keys  # noqa: E402

RULES = rules_mod.default()


def R(addr, type_, props=None, **kw):
    return resource(addr, type_, props, **kw)


def C(addr, type_, props=None, **kw):
    return resource(addr, type_, props, fmt="cfn", **kw)


def tag(name):
    return {"tags": {"Name": name}}


def ctag(name, **props):
    return {"Tags": [{"Key": "Name", "Value": name}], **props}


class Out:
    def __init__(self, fmt, resources, references):
        self.ir = build.normalize(raw_ir(fmt, resources, references), RULES, "t")
        self.fmt = fmt
        # internet からの辺（N-EXT-INTERNET。パブリックな API Gateway に付く）は test_sg.py で確かめるので除く
        self.edges = {e["id"]: (e["kind"], e["label"], e["confidence"]) for e in self.ir["edges"] if e["from"] != "external/internet"}
        self.ev = {e["edge"]: e for e in self.ir["sources"][fmt]["edges"]}
        self.cls = {r["address"]: (r["class"], r.get("rule"), tuple(r.get("into", ()))) for r in self.ir["sources"][fmt]["resources"]}
        self.diags = [(d["code"], d["address"]) for d in self.ir["diagnostics"] if d["code"] != "NORM-NAME-FALLBACK"]
        self.attrs = {n["id"]: n.get("attrs", {}) for n in self.ir["nodes"]}


class PathKeysTest(unittest.TestCase):
    def test_path_keys(self):
        self.assertEqual(path_keys("Properties.DefaultActions[0].TargetGroupArn"), ("defaultactions", "targetgrouparn"))
        self.assertEqual(path_keys("default_action[0].target_group_arn"), ("defaultaction", "targetgrouparn"))
        self.assertEqual(path_keys('Properties.PolicyDocument.Statement[0].Condition.ArnEquals["aws:SourceArn"]')[-1], "aws:sourcearn")
        self.assertEqual(path_keys('x["a.b"].y'), ("x", "a.b", "y"))


class RouteTest(unittest.TestCase):
    def test_tf_routes_access_and_noroute(self):
        o = Out("tf", [
            R("aws_vpc.v", "aws_vpc", tag("net")), R("aws_internet_gateway.igw", "aws_internet_gateway", tag("igw")),
            R("aws_nat_gateway.nat", "aws_nat_gateway", tag("nat")),
            R("aws_subnet.pub", "aws_subnet", tag("pub")), R("aws_subnet.priv", "aws_subnet", tag("priv")), R("aws_subnet.db", "aws_subnet", tag("db")),
            R("aws_route_table.public", "aws_route_table"),
            R("aws_route.internet", "aws_route", {"destination_cidr_block": "0.0.0.0/0"}),
            R("aws_route_table.private", "aws_route_table", {"route": [{"cidr_block": "0.0.0.0/0"}, {"cidr_block": "10.9.0.0/16"}]}),
            R("aws_route_table.database", "aws_route_table"),
            R("aws_route_table_association.pub", "aws_route_table_association"),
            R("aws_route_table_association.priv", "aws_route_table_association"),
            R("aws_route_table_association.db", "aws_route_table_association"),
        ], [
            ref("aws_route.internet", "route_table_id", "aws_route_table.public", "id"),
            ref("aws_route.internet", "gateway_id", "aws_internet_gateway.igw", "id"),
            ref("aws_route_table.private", "route[0].nat_gateway_id", "aws_nat_gateway.nat", "id"),
            ref("aws_route_table.private", "route[1].nat_gateway_id", "aws_nat_gateway.nat", "id"),
            ref("aws_route_table_association.pub", "route_table_id", "aws_route_table.public", "id"),
            ref("aws_route_table_association.pub", "subnet_id", "aws_subnet.pub", "id"),
            ref("aws_route_table_association.priv", "route_table_id", "aws_route_table.private", "id"),
            ref("aws_route_table_association.priv", "subnet_id", "aws_subnet.priv", "id"),
            ref("aws_route_table_association.db", "route_table_id", "aws_route_table.database", "id"),
            ref("aws_route_table_association.db", "subnet_id", "aws_subnet.db", "id"),
        ])
        self.assertEqual(o.edges, {
            "subnet/pub->internet_gateway/igw": ("route", "0.0.0.0/0", "derived"),
            "subnet/priv->nat_gateway/nat": ("route", "0.0.0.0/0, 10.9.0.0/16", "derived"),  # 同じ組の 2 つのルートの CIDR
        })
        self.assertEqual(o.ev["subnet/pub->internet_gateway/igw"]["evidence"],
                         ["aws_route.internet.gateway_id", "aws_route.internet.route_table_id", "aws_route_table_association.pub.route_table_id",
                          "aws_route_table_association.pub.subnet_id"])
        self.assertEqual(o.cls["aws_route.internet"], ("merged_into", "R-ROUTE", ("subnet/pub->internet_gateway/igw",)))
        self.assertEqual(o.cls["aws_route_table.private"], ("merged_into", "R-ROUTE", ("subnet/priv->nat_gateway/nat",)))
        self.assertEqual(o.cls["aws_route_table.database"], ("hidden", "H-RT-NOROUTE", ()))
        self.assertEqual(o.cls["aws_route_table_association.db"], ("hidden", "H-RT-NOROUTE", ()))
        self.assertEqual((o.attrs["subnet/pub"]["access"], o.attrs["subnet/priv"]["access"], o.attrs["subnet/db"]["access"]),
                         ("public", "private", "private"))

    def test_cfn_routes_and_gateway_endpoint(self):
        o = Out("cfn", [
            C("Vpc", "AWS::EC2::VPC", ctag("net")), C("Sub", "AWS::EC2::Subnet", ctag("sub")),
            C("Rt", "AWS::EC2::RouteTable"), C("Assoc", "AWS::EC2::SubnetRouteTableAssociation"),
            C("S3", "AWS::EC2::VPCEndpoint", ctag("s3", ServiceName="com.amazonaws.ap-northeast-1.s3", VpcEndpointType="Gateway")),
        ], [
            ref("Assoc", "Properties.RouteTableId", "Rt"), ref("Assoc", "Properties.SubnetId", "Sub"),
            ref("S3", "Properties.RouteTableIds[0]", "Rt"),
        ])
        self.assertEqual(o.edges, {"subnet/sub->vpc_endpoint/s3": ("route", "s3 prefix list", "derived")})
        self.assertEqual(o.ev["subnet/sub->vpc_endpoint/s3"]["rules"], ["R-ROUTE", "R-VPCE-GATEWAY"])
        self.assertEqual(o.cls["Rt"], ("merged_into", "R-ROUTE", ("subnet/sub->vpc_endpoint/s3",)))
        self.assertEqual(o.attrs["subnet/sub"]["access"], "private")


class LbTest(unittest.TestCase):
    def test_tf_listener_target_group_service_and_attachment(self):
        o = Out("tf", [
            R("aws_lb.alb", "aws_lb", {"name": "alb"}), R("aws_lb_listener.l", "aws_lb_listener"),
            R("aws_lb_target_group.tg", "aws_lb_target_group", {"protocol": "HTTP", "port": 8080}),
            R("aws_ecs_service.svc", "aws_ecs_service", {"name": "svc"}),
            R("aws_instance.ec2", "aws_instance", tag("ec2")), R("aws_lb_target_group_attachment.a", "aws_lb_target_group_attachment"),
        ], [
            ref("aws_lb_listener.l", "load_balancer_arn", "aws_lb.alb", "arn"),
            ref("aws_lb_listener.l", "default_action[0].target_group_arn", "aws_lb_target_group.tg", "arn"),
            ref("aws_ecs_service.svc", "load_balancer[0].target_group_arn", "aws_lb_target_group.tg", "arn"),
            ref("aws_lb_target_group_attachment.a", "target_group_arn", "aws_lb_target_group.tg", "arn"),
            ref("aws_lb_target_group_attachment.a", "target_id", "aws_instance.ec2", "id"),
        ])
        self.assertEqual(o.edges, {"alb/alb->ecs_service/svc": ("request", "HTTP 8080", "derived"),
                                   "alb/alb->ec2_instance/ec2": ("request", "HTTP 8080", "derived")})
        self.assertEqual(o.ev["alb/alb->ecs_service/svc"]["rules"], ["R-LB-LISTENER", "R-LB-TG"])
        self.assertEqual(o.cls["aws_lb_listener.l"][2], ("alb/alb->ec2_instance/ec2", "alb/alb->ecs_service/svc"))
        self.assertEqual(o.cls["aws_lb_target_group_attachment.a"][2], ("alb/alb->ec2_instance/ec2",))

    def test_cfn_target_group_targets_and_redirect_only_listener(self):
        o = Out("cfn", [
            C("Alb", "AWS::ElasticLoadBalancingV2::LoadBalancer", {"Name": "alb"}),
            C("Https", "AWS::ElasticLoadBalancingV2::Listener"), C("Redirect", "AWS::ElasticLoadBalancingV2::Listener"),
            C("Tg", "AWS::ElasticLoadBalancingV2::TargetGroup", {"Protocol": "HTTPS", "Port": 443}),
            C("Ec2", "AWS::EC2::Instance", ctag("ec2")),
        ], [
            ref("Https", "Properties.LoadBalancerArn", "Alb"), ref("Https", "Properties.DefaultActions[0].TargetGroupArn", "Tg"),
            ref("Redirect", "Properties.LoadBalancerArn", "Alb"), ref("Tg", "Properties.Targets[0].Id", "Ec2"),
        ])
        self.assertEqual(o.edges, {"alb/alb->ec2_instance/ec2": ("request", "HTTPS 443", "derived")})
        # 転送の無いリスナー（リダイレクトだけ）は辺ができず、fallback も無いので H-RELATION-NOEDGE（warn の診断も出す）
        self.assertEqual(o.cls["Redirect"], ("hidden", "H-RELATION-NOEDGE", ()))
        self.assertIn(("NORM-RELATION-NOEDGE", "Redirect"), o.diags)


class ApiTest(unittest.TestCase):
    def test_tf_http_api(self):
        o = Out("tf", [
            R("aws_apigatewayv2_api.api", "aws_apigatewayv2_api", {"name": "api", "protocol_type": "HTTP"}),
            R("aws_lambda_function.fn", "aws_lambda_function", {"function_name": "fn"}),
            R("aws_apigatewayv2_integration.i", "aws_apigatewayv2_integration"),
            R('aws_apigatewayv2_route.r["b"]', "aws_apigatewayv2_route", {"route_key": "POST /orders"}),
            R('aws_apigatewayv2_route.r["a"]', "aws_apigatewayv2_route", {"route_key": "GET /orders"}),
        ], [
            ref("aws_apigatewayv2_integration.i", "api_id", "aws_apigatewayv2_api.api", "id"),
            ref("aws_apigatewayv2_integration.i", "integration_uri", "aws_lambda_function.fn", "invoke_arn"),
            ref('aws_apigatewayv2_route.r["a"]', "target", "aws_apigatewayv2_integration.i", "id"),
            ref('aws_apigatewayv2_route.r["b"]', "target", "aws_apigatewayv2_integration.i", "id"),
        ])
        self.assertEqual(o.edges, {"apigw_http_api/api->lambda_function/fn": ("request", "GET /orders, POST /orders", "derived")})
        self.assertEqual(o.cls['aws_apigatewayv2_route.r["a"]'][0], "merged_into")

    def test_sam_http_api_events_explicit_and_implicit(self):
        events = {"Get": {"Type": "HttpApi", "Properties": {"ApiId": {"$res": "Api", "attr": None}, "Method": "get", "Path": "/x"}},
                  "Post": {"Type": "HttpApi", "Properties": {"ApiId": {"$res": "Api", "attr": None}, "Method": "POST", "Path": "/x"}}}
        o = Out("cfn", [
            C("Api", "AWS::Serverless::HttpApi", {"Name": "api"}),
            C("Fn", "AWS::Serverless::Function", {"FunctionName": "fn", "Events": events}),
            C("ServerlessHttpApi", "AWS::Serverless::HttpApi", implicit=True),
            C("Fn2", "AWS::Serverless::Function", {"FunctionName": "fn2", "Events": {"Any": {"Type": "HttpApi"}}}),
        ], [
            ref("Fn", "Properties.Events.Get.Properties.ApiId", "Api"), ref("Fn", "Properties.Events.Post.Properties.ApiId", "Api"),
        ])
        self.assertEqual(o.edges, {"apigw_http_api/api->lambda_function/fn": ("request", "GET /x, POST /x", "derived"),
                                   "apigw_http_api/serverlesshttpapi->lambda_function/fn2": ("request", "$default", "derived")})
        self.assertTrue(o.ev["apigw_http_api/serverlesshttpapi->lambda_function/fn2"]["evidence"][0].startswith("Fn2.Properties.Events.Any"))

    def test_tf_rest_api_nested_path(self):
        o = Out("tf", [
            R("aws_api_gateway_rest_api.api", "aws_api_gateway_rest_api", {"name": "api"}),
            R("aws_lambda_function.fn", "aws_lambda_function", {"function_name": "fn"}),
            R("aws_api_gateway_resource.a", "aws_api_gateway_resource", {"path_part": "a"}),
            R("aws_api_gateway_resource.b", "aws_api_gateway_resource", {"path_part": "{id}"}),
            R("aws_api_gateway_method.m", "aws_api_gateway_method", {"http_method": "GET"}),
            R("aws_api_gateway_integration.i", "aws_api_gateway_integration"),
            R("aws_api_gateway_method.mock", "aws_api_gateway_method", {"http_method": "OPTIONS"}),
        ], [
            ref("aws_api_gateway_resource.a", "parent_id", "aws_api_gateway_rest_api.api", "root_resource_id"),
            ref("aws_api_gateway_resource.b", "parent_id", "aws_api_gateway_resource.a", "id"),
            ref("aws_api_gateway_method.m", "resource_id", "aws_api_gateway_resource.b", "id"),
            ref("aws_api_gateway_integration.i", "rest_api_id", "aws_api_gateway_rest_api.api", "id"),
            ref("aws_api_gateway_integration.i", "resource_id", "aws_api_gateway_resource.b", "id"),
            ref("aws_api_gateway_integration.i", "http_method", "aws_api_gateway_method.m", "http_method"),
            ref("aws_api_gateway_integration.i", "uri", "aws_lambda_function.fn", "invoke_arn"),
            ref("aws_api_gateway_method.mock", "resource_id", "aws_api_gateway_resource.b", "id"),
        ])
        # 統合の http_method は aws_api_gateway_method への参照（値はそのメソッドの http_method）。path は親のリソースをたどる
        edge = "apigw_rest_api/api->lambda_function/fn"
        self.assertEqual(o.edges.get(edge), ("request", "GET /a/{id}", "derived"))
        for a in ("aws_api_gateway_resource.a", "aws_api_gateway_resource.b", "aws_api_gateway_method.m", "aws_api_gateway_integration.i"):
            self.assertEqual(o.cls[a], ("merged_into", "R-APIGW-REST", (edge,)), a)
        self.assertEqual(o.cls["aws_api_gateway_method.mock"], ("hidden", "H-RELATION-NOEDGE", ()))  # 統合の無いメソッド

    def test_cfn_rest_method_and_sam_api(self):
        o = Out("cfn", [
            C("Api", "AWS::ApiGateway::RestApi", {"Name": "api"}), C("Fn", "AWS::Lambda::Function", {"FunctionName": "fn"}),
            C("Res", "AWS::ApiGateway::Resource", {"PathPart": "query"}),
            C("Post", "AWS::ApiGateway::Method", {"HttpMethod": "POST", "Integration": {"Uri": {"$concat": ["arn:", {"$res": "Fn", "attr": "Arn"}]}}}),
            C("ServerlessRestApi", "AWS::Serverless::Api", implicit=True),
            C("Sam", "AWS::Serverless::Function", {"FunctionName": "sam", "Events": {"E": {"Type": "Api", "Properties": {"Method": "post", "Path": "/"}}}}),
        ], [
            ref("Res", "Properties.ParentId", "Api", "RootResourceId"), ref("Post", "Properties.RestApiId", "Api"),
            ref("Post", "Properties.ResourceId", "Res"), ref("Post", "Properties.Integration.Uri", "Fn", "Arn"),
        ])
        self.assertEqual(o.edges, {"apigw_rest_api/api->lambda_function/fn": ("request", "POST /query", "derived"),
                                   "apigw_rest_api/serverlessrestapi->lambda_function/sam": ("request", "POST /", "derived")})
        self.assertEqual(o.cls["Res"], ("merged_into", "R-APIGW-REST", ("apigw_rest_api/api->lambda_function/fn",)))

    def test_cfn_openapi_definition(self):
        # SAM の DefinitionBody・RestApi の Body（AWS::Include で差し込んだものを含む）の x-amazon-apigateway-integration。
        # 統合先は uri の中の参照、無ければ requestTemplates の中の参照（T11s）。操作ごとのラベルは E-MERGE が辞書順にまとめる
        def integ(**kw):
            return {"x-amazon-apigateway-integration": {"type": "aws", **kw}}
        sam_paths = "Properties.DefinitionBody.paths"
        o = Out("cfn", [
            C("Fn", "AWS::Lambda::Function", {"FunctionName": "fn"}), C("Sm", "AWS::StepFunctions::StateMachine", {"StateMachineName": "sm"}),
            C("Api", "AWS::Serverless::Api", {"Name": "api", "DefinitionBody": {"paths": {
                "/items": {"get": integ(uri={"$concat": ["arn:", {"$res": "Fn", "attr": "Arn"}, "/invocations"]}),
                           "x-amazon-apigateway-any-method": integ(uri={"$concat": ["arn:", {"$res": "Fn", "attr": "Arn"}]}),
                           "parameters": [], "options": integ(type="mock")},
                "/": {"x-amazon-apigateway-any-method": integ(uri="arn:aws:apigateway:us-west-2:states:action/StartSyncExecution",
                                                              requestTemplates={"application/json": {"$concat": ["{", {"$res": "Sm", "attr": None}, "}"]}})},
                # MOCK は参照があっても辺を作らない。統合先が API 自身（自己ループ）は E-MERGE が捨てる
                "/mock": {"post": integ(type="MOCK", requestTemplates={"application/json": {"$res": "Sm", "attr": None}})},
                "/self": {"get": integ(uri={"$concat": ["https://", {"$res": "Api", "attr": None}]})},
            }}}),
            C("Rest", "AWS::ApiGateway::RestApi", {"Name": "rest", "Body": {"$json": {"paths": {"/q": {"post": integ(
                uri={"$concat": ["arn:", {"$res": "Fn", "attr": "Arn"}]})}}}}}),
        ], [
            ref("Api", f'{sam_paths}["/items"].get.x-amazon-apigateway-integration.uri', "Fn", "Arn"),
            ref("Api", f'{sam_paths}["/items"].x-amazon-apigateway-any-method.x-amazon-apigateway-integration.uri', "Fn", "Arn"),
            ref("Api", f'{sam_paths}["/"].x-amazon-apigateway-any-method.x-amazon-apigateway-integration.requestTemplates["application/json"]', "Sm"),
            ref("Rest", 'Properties.Body.paths["/q"].post.x-amazon-apigateway-integration.uri', "Fn", "Arn"),
            ref("Api", f'{sam_paths}["/mock"].post.x-amazon-apigateway-integration.requestTemplates["application/json"]', "Sm"),
            ref("Api", f'{sam_paths}["/self"].get.x-amazon-apigateway-integration.uri', "Api"),
        ])
        self.assertEqual(o.edges, {"apigw_rest_api/api->lambda_function/fn": ("request", "ANY /items, GET /items", "derived"),
                                   "apigw_rest_api/api->sfn_state_machine/sm": ("request", "ANY /", "derived"),
                                   "apigw_rest_api/rest->lambda_function/fn": ("request", "POST /q", "derived")})
        self.assertEqual(o.ev["apigw_rest_api/api->sfn_state_machine/sm"]["rules"], ["R-APIGW-REST"])
        self.assertEqual(o.ev["apigw_rest_api/api->sfn_state_machine/sm"]["evidence"],
                         [f'Api.{sam_paths}["/"].x-amazon-apigateway-any-method.x-amazon-apigateway-integration.requestTemplates["application/json"]'])
        # 辺にしなかった MOCK と自己ループの参照だけが、使わなかった参照に残る
        self.assertEqual([a for c, a in o.diags if c == "NORM-UNUSED-REF"], ["Api", "Api"])


class EventsTest(unittest.TestCase):
    def test_esm_subscription_notification_data_source_targets(self):
        o = Out("tf", [
            R("aws_dynamodb_table.t", "aws_dynamodb_table", {"name": "t"}), R("aws_lambda_function.fn", "aws_lambda_function", {"function_name": "fn"}),
            R("aws_lambda_event_source_mapping.m", "aws_lambda_event_source_mapping"),
            R("aws_sns_topic.top", "aws_sns_topic", {"name": "top"}), R("aws_sqs_queue.q", "aws_sqs_queue", {"name": "q"}),
            R("aws_sns_topic_subscription.s", "aws_sns_topic_subscription"),
            R("aws_s3_bucket.b", "aws_s3_bucket", {"bucket": "b"}), R("aws_s3_bucket_notification.n", "aws_s3_bucket_notification"),
            R("aws_bedrockagent_knowledge_base.kb", "aws_bedrockagent_knowledge_base", {"name": "kb"}),
            R("aws_bedrockagent_data_source.ds", "aws_bedrockagent_data_source"),
            R("aws_cloudwatch_event_rule.r", "aws_cloudwatch_event_rule", {"name": "r"}), R("aws_cloudwatch_event_target.t", "aws_cloudwatch_event_target"),
        ], [
            ref("aws_lambda_event_source_mapping.m", "event_source_arn", "aws_dynamodb_table.t", "stream_arn"),
            ref("aws_lambda_event_source_mapping.m", "function_name", "aws_lambda_function.fn", "arn"),
            ref("aws_sns_topic_subscription.s", "topic_arn", "aws_sns_topic.top", "arn"),
            ref("aws_sns_topic_subscription.s", "endpoint", "aws_sqs_queue.q", "arn"),
            ref("aws_s3_bucket_notification.n", "bucket", "aws_s3_bucket.b", "id"),
            ref("aws_s3_bucket_notification.n", "queue[0].queue_arn", "aws_sqs_queue.q", "arn"),
            ref("aws_bedrockagent_data_source.ds", "knowledge_base_id", "aws_bedrockagent_knowledge_base.kb", "id"),
            ref("aws_bedrockagent_data_source.ds", "data_source_configuration[0].s3_configuration[0].bucket_arn", "aws_s3_bucket.b", "arn"),
            ref("aws_cloudwatch_event_target.t", "rule", "aws_cloudwatch_event_rule.r", "name"),
            ref("aws_cloudwatch_event_target.t", "arn", "aws_sns_topic.top", "arn"),
        ])
        self.assertEqual(o.edges, {
            "dynamodb_table/t->lambda_function/fn": ("event", "", "derived"),  # 向きはデータの流れ
            "sns_topic/top->sqs_queue/q": ("event", "", "derived"),
            "s3_bucket/b->sqs_queue/q": ("event", "", "derived"),
            "s3_bucket/b->bedrock_knowledge_base/kb": ("data", "", "derived"),
            "eventbridge_rule/r->sns_topic/top": ("event", "", "derived"),
        })

    def test_cfn_and_sam_property_forms(self):
        o = Out("cfn", [
            C("Top", "AWS::SNS::Topic", {"TopicName": "top"}), C("Q", "AWS::SQS::Queue", {"QueueName": "q"}),
            C("B", "AWS::S3::Bucket", {"BucketName": "b"}), C("Fn", "AWS::Lambda::Function", {"FunctionName": "fn"}),
            C("Rule", "AWS::Events::Rule", {"Name": "rule"}), C("T", "AWS::DynamoDB::Table", {"TableName": "t"}),
            C("Sam", "AWS::Serverless::Function", {"FunctionName": "sam", "Events": {
                "S": {"Type": "DynamoDB", "Properties": {"Stream": {"$res": "T", "attr": "StreamArn"}}},
                "N": {"Type": "SNS", "Properties": {"Topic": {"$res": "Top", "attr": None}}}}}),
        ], [
            ref("Top", "Properties.Subscription[0].Endpoint", "Q", "Arn"),
            ref("B", "Properties.NotificationConfiguration.LambdaConfigurations[0].Function", "Fn", "Arn"),
            ref("Rule", "Properties.Targets[0].Arn", "Fn", "Arn"),
            ref("Sam", "Properties.Events.S.Properties.Stream", "T", "StreamArn"), ref("Sam", "Properties.Events.N.Properties.Topic", "Top"),
        ])
        self.assertEqual(set(o.edges), {"sns_topic/top->sqs_queue/q", "s3_bucket/b->lambda_function/fn", "eventbridge_rule/rule->lambda_function/fn",
                                        "dynamodb_table/t->lambda_function/sam", "sns_topic/top->lambda_function/sam"})

    def test_glue_trigger(self):
        o = Out("tf", [
            R("aws_glue_job.a", "aws_glue_job", {"name": "a"}), R("aws_glue_crawler.c", "aws_glue_crawler", {"name": "c"}),
            R("aws_glue_trigger.cond", "aws_glue_trigger"), R("aws_glue_trigger.schedule", "aws_glue_trigger"),
        ], [
            ref("aws_glue_trigger.cond", "predicate[0].conditions[0].job_name", "aws_glue_job.a", "name"),
            ref("aws_glue_trigger.cond", "actions[0].crawler_name", "aws_glue_crawler.c", "name"),
            ref("aws_glue_trigger.schedule", "actions[0].job_name", "aws_glue_job.a", "name"),
        ])
        self.assertEqual(o.edges, {"glue_job/a->glue_crawler/c": ("event", "", "derived")})
        # 条件の無いトリガーは辺を作らない（規則の文）。fallback が無いので H-RELATION-NOEDGE（warn の診断も出す）
        self.assertEqual(o.cls["aws_glue_trigger.schedule"], ("hidden", "H-RELATION-NOEDGE", ()))
        self.assertIn(("NORM-RELATION-NOEDGE", "aws_glue_trigger.schedule"), o.diags)


class PermissionTest(unittest.TestCase):
    def test_lambda_permission(self):
        o = Out("tf", [
            R("aws_s3_bucket.b", "aws_s3_bucket", {"bucket": "b"}), R("aws_lambda_function.fn", "aws_lambda_function", {"function_name": "fn"}),
            R("aws_sns_topic.t", "aws_sns_topic", {"name": "t"}),
            R("aws_s3_bucket_notification.n", "aws_s3_bucket_notification"),
            R("aws_lambda_permission.from_s3", "aws_lambda_permission", {"principal": "s3.amazonaws.com"}),
            R("aws_lambda_permission.from_sns", "aws_lambda_permission", {"principal": "sns.amazonaws.com"}),
            R("aws_lambda_permission.unknown", "aws_lambda_permission", {"principal": "events.amazonaws.com", "source_arn": "arn:aws:events:x"}),
        ], [
            ref("aws_s3_bucket_notification.n", "bucket", "aws_s3_bucket.b", "id"),
            ref("aws_s3_bucket_notification.n", "lambda_function[0].lambda_function_arn", "aws_lambda_function.fn", "arn"),
            ref("aws_lambda_permission.from_s3", "function_name", "aws_lambda_function.fn", "function_name"),
            ref("aws_lambda_permission.from_s3", "source_arn", "aws_s3_bucket.b", "arn"),
            ref("aws_lambda_permission.from_sns", "function_name", "aws_lambda_function.fn", "function_name"),
            ref("aws_lambda_permission.from_sns", "source_arn", "aws_sns_topic.t", "arn"),
            ref("aws_lambda_permission.unknown", "function_name", "aws_lambda_function.fn", "function_name"),
        ])
        # 既存の辺（S3 通知）に根拠として加わる。ほかの規則の辺が無ければ、principal の kind で辺を作る
        self.assertEqual(o.edges, {"s3_bucket/b->lambda_function/fn": ("event", "", "derived"),
                                   "sns_topic/t->lambda_function/fn": ("event", "", "derived")})
        self.assertEqual(o.ev["s3_bucket/b->lambda_function/fn"]["rules"], ["R-LAMBDA-PERMISSION", "R-S3-NOTIFICATION"])
        self.assertEqual(o.cls["aws_lambda_permission.unknown"], ("hidden", "H-IAM", ()))  # 送信元が入力に無い

    def test_cfn_permission_by_s3_arn_string(self):
        o = Out("cfn", [
            C("Docs", "AWS::S3::Bucket", {"BucketName": "rag-docs"}), C("Fn", "AWS::Lambda::Function", {"FunctionName": "fn"}),
            C("Api", "AWS::ApiGateway::RestApi", {"Name": "api"}),
            C("P", "AWS::Lambda::Permission", {"Principal": "s3.amazonaws.com",
                                               "SourceArn": {"$concat": ["arn:", {"$pseudo": "AWS::Partition"}, ":s3:::rag-docs"]}}),
            C("PApi", "AWS::Lambda::Permission", {"Principal": "apigateway.amazonaws.com"}),
        ], [
            ref("P", "Properties.FunctionName", "Fn"),
            ref("PApi", "Properties.FunctionName", "Fn"), ref("PApi", "Properties.SourceArn", "Api"),
        ])
        self.assertEqual(o.edges, {"s3_bucket/rag-docs->lambda_function/fn": ("event", "", "derived"),
                                   "apigw_rest_api/api->lambda_function/fn": ("request", "", "derived")})

    def test_queue_and_topic_policies(self):
        o = Out("tf", [
            R("aws_sns_topic.t", "aws_sns_topic", {"name": "t"}), R("aws_sqs_queue.q", "aws_sqs_queue", {"name": "q"}),
            R("aws_sqs_queue_policy.p", "aws_sqs_queue_policy"),
            R("data.aws_iam_policy_document.d", "aws_iam_policy_document", {"statement": [{"condition": [
                {"test": "ArnEquals", "variable": "aws:SourceArn", "values": [{"$res": "aws_sns_topic.t", "attr": "arn"}]}]}]}),
            R("aws_sqs_queue_policy.nocond", "aws_sqs_queue_policy"),
        ], [
            ref("aws_sqs_queue_policy.p", "queue_url", "aws_sqs_queue.q", "id"),
            ref("aws_sqs_queue_policy.p", "policy", "data.aws_iam_policy_document.d", "json"),
            ref("data.aws_iam_policy_document.d", "statement[0].condition[0].values[0]", "aws_sns_topic.t", "arn"),
            ref("aws_sqs_queue_policy.nocond", "queue_url", "aws_sqs_queue.q", "id"),
        ])
        self.assertEqual(o.edges, {"sns_topic/t->sqs_queue/q": ("event", "", "derived")})
        self.assertIn("aws_sqs_queue_policy.p.policy (aws:SourceArn の条件を持つポリシー文書)", o.ev["sns_topic/t->sqs_queue/q"]["evidence"])
        self.assertEqual(o.cls["aws_sqs_queue_policy.nocond"], ("hidden", "H-IAM", ()))
        o = Out("cfn", [
            C("T", "AWS::SNS::Topic", {"TopicName": "t"}), C("Rule", "AWS::Events::Rule", {"Name": "r"}),
            C("Tp", "AWS::SNS::TopicPolicy", {"PolicyDocument": {"Statement": [
                {"Effect": "Allow", "Condition": {"ArnEquals": {"aws:SourceArn": {"$res": "Rule", "attr": "Arn"}}}}]}}),
        ], [
            ref("Tp", "Properties.Topics[0]", "T"),
            ref("Tp", 'Properties.PolicyDocument.Statement[0].Condition.ArnEquals["aws:SourceArn"]', "Rule", "Arn"),
        ])
        self.assertEqual(o.edges, {"eventbridge_rule/r->sns_topic/t": ("event", "", "derived")})
        self.assertEqual(o.cls["Tp"], ("merged_into", "R-SNS-TOPIC-POLICY", ("eventbridge_rule/r->sns_topic/t",)))


class PolicyConditionTest(unittest.TestCase):
    def test_deny_and_negative_operators_are_not_senders(self):
        # レビューの反例: Deny の文の ArnEquals は送信元ではない。ArnNotEquals も使わない。TF の文書は effect と test を見る
        doc = {"Statement": [{"Effect": "Deny", "Condition": {"ArnEquals": {"aws:SourceArn": {"$res": "T", "attr": None}}}},
                             {"Effect": "Allow", "Condition": {"ArnNotEquals": {"aws:SourceArn": {"$res": "T", "attr": None}}}}]}
        o = Out("cfn", [C("T", "AWS::SNS::Topic", {"TopicName": "t"}), C("Q", "AWS::SQS::Queue", {"QueueName": "q"}),
                        C("Qp", "AWS::SQS::QueuePolicy", {"PolicyDocument": doc})], [
            ref("Qp", "Properties.Queues[0]", "Q"),
            ref("Qp", 'Properties.PolicyDocument.Statement[0].Condition.ArnEquals["aws:SourceArn"]', "T"),
            ref("Qp", 'Properties.PolicyDocument.Statement[1].Condition.ArnNotEquals["aws:SourceArn"]', "T")])
        self.assertEqual(o.edges, {})
        self.assertEqual(o.cls["Qp"], ("hidden", "H-IAM", ()))
        o = Out("tf", [
            R("aws_sns_topic.t", "aws_sns_topic", {"name": "t"}), R("aws_sqs_queue.q", "aws_sqs_queue", {"name": "q"}),
            R("aws_sqs_queue_policy.p", "aws_sqs_queue_policy"),
            R("data.aws_iam_policy_document.d", "aws_iam_policy_document", {"statement": [
                {"effect": "Deny", "condition": [{"test": "ArnEquals", "variable": "aws:SourceArn", "values": [{"$res": "aws_sns_topic.t", "attr": "arn"}]}]},
                {"condition": [{"test": "ArnNotLike", "variable": "aws:SourceArn", "values": [{"$res": "aws_sns_topic.t", "attr": "arn"}]}]}]}),
        ], [
            ref("aws_sqs_queue_policy.p", "queue_url", "aws_sqs_queue.q", "id"),
            ref("aws_sqs_queue_policy.p", "policy", "data.aws_iam_policy_document.d", "json"),
            ref("data.aws_iam_policy_document.d", "statement[0].condition[0].values[0]", "aws_sns_topic.t", "arn"),
            ref("data.aws_iam_policy_document.d", "statement[1].condition[0].values[0]", "aws_sns_topic.t", "arn"),
        ])
        self.assertEqual(o.edges, {})
        # jsonencode のポリシー（$json）でも、Allow と ArnLike なら送信元
        o = Out("tf", [
            R("aws_sns_topic.t", "aws_sns_topic", {"name": "t"}), R("aws_sqs_queue.q", "aws_sqs_queue", {"name": "q"}),
            R("aws_sqs_queue_policy.p", "aws_sqs_queue_policy", {"policy": {"$json": {"Statement": [
                {"Effect": "Allow", "Condition": {"ArnLike": {"aws:SourceArn": {"$res": "aws_sns_topic.t", "attr": "arn"}}}}]}}}),
        ], [
            ref("aws_sqs_queue_policy.p", "queue_url", "aws_sqs_queue.q", "id"),
            ref("aws_sqs_queue_policy.p", 'policy.Statement[0].Condition.ArnLike["aws:SourceArn"]', "aws_sns_topic.t", "arn"),
        ])
        self.assertEqual(o.edges, {"sns_topic/t->sqs_queue/q": ("event", "", "derived")})


class StepFunctionsIntegrationTest(unittest.TestCase):
    def test_rest_and_http_integrations_with_service_targets(self):
        # T11 の形: REST の統合の uri は Step Functions のアクションの文字列で、ステートマシンは request_templates の中の参照
        o = Out("tf", [
            R("aws_api_gateway_rest_api.api", "aws_api_gateway_rest_api", {"name": "api"}),
            R("aws_sfn_state_machine.sm", "aws_sfn_state_machine", {"name": "sm"}),
            R("aws_iam_role.r", "aws_iam_role"),
            R("aws_api_gateway_method.m", "aws_api_gateway_method", {"http_method": "ANY"}),
            R("aws_api_gateway_integration.i", "aws_api_gateway_integration",
              {"uri": {"$concat": ["arn:aws:apigateway:", {"$pseudo": "AWS::Region"}, ":states:action/StartExecution"]}}),
            R("aws_apigatewayv2_api.h", "aws_apigatewayv2_api", {"name": "h", "protocol_type": "HTTP"}),
            R("aws_apigatewayv2_integration.hi", "aws_apigatewayv2_integration"),
        ], [
            ref("aws_api_gateway_method.m", "resource_id", "aws_api_gateway_rest_api.api", "root_resource_id"),
            ref("aws_api_gateway_integration.i", "rest_api_id", "aws_api_gateway_rest_api.api", "id"),
            ref("aws_api_gateway_integration.i", "resource_id", "aws_api_gateway_rest_api.api", "root_resource_id"),
            ref("aws_api_gateway_integration.i", "http_method", "aws_api_gateway_method.m", "http_method"),
            ref("aws_api_gateway_integration.i", "credentials", "aws_iam_role.r", "arn"),
            ref("aws_api_gateway_integration.i", 'request_templates["application/json"]', "aws_sfn_state_machine.sm", "name"),
            ref("aws_apigatewayv2_integration.hi", "api_id", "aws_apigatewayv2_api.h", "id"),
            ref("aws_apigatewayv2_integration.hi", 'request_parameters["StateMachineArn"]', "aws_sfn_state_machine.sm", "arn"),
        ])
        self.assertEqual(o.edges, {"apigw_rest_api/api->sfn_state_machine/sm": ("request", "ANY /", "derived"),
                                   "apigw_http_api/h->sfn_state_machine/sm": ("request", "", "derived")})
        self.assertEqual(o.cls["aws_api_gateway_integration.i"][0], "merged_into")


class MergeTest(unittest.TestCase):
    def test_merge_priority_labels_and_self_loops(self):
        cands = [Candidate("a/x", "b/y", "R-LAMBDA-PERMISSION", None, "", ("p.e",), ("p",), weak_kind="event"),
                 Candidate("a/x", "b/y", "R-APIGW-HTTP", "request", "GET /", ("i.e",), ("i",)),
                 Candidate("a/x", "b/y", "R-APIGW-HTTP", "request", "POST /", ("j.e",), ("j",)),
                 Candidate("a/x", "a/x", "R-ROUTE", "route", "", ("s.e",), ("s",)),
                 Candidate("c/z", "b/y", "R-SQS-QUEUE-POLICY", None, "", ("q.e",), ("q",), weak_kind="event")]
        r = edges.merge(cands, RULES)
        self.assertEqual(r.edges, [{"id": "a/x->b/y", "from": "a/x", "to": "b/y", "kind": "request", "label": "GET /, POST /", "confidence": "derived"},
                                   {"id": "c/z->b/y", "from": "c/z", "to": "b/y", "kind": "event", "label": "", "confidence": "derived"}])
        self.assertEqual(r.evidence[0]["rules"], ["R-APIGW-HTTP", "R-LAMBDA-PERMISSION"])
        self.assertEqual(r.into, {"i": ["a/x->b/y"], "j": ["a/x->b/y"], "p": ["a/x->b/y"], "q": ["c/z->b/y"]})  # 自己ループは辺にしない


if __name__ == "__main__":
    unittest.main()
