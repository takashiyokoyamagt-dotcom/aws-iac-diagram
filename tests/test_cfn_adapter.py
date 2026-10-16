"""CloudFormation アダプタ（scripts/adapters/cfn.py）のテスト。フェーズ1 の手順2（土台）の範囲。"""
from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "aws-iac-diagram" / "scripts"
FIXTURES = ROOT / "aws-iac-diagram-workspace" / "fixtures" / "cfn"
sys.path.insert(0, str(SCRIPTS))
import validate_ir as v  # noqa: E402
from adapters import cfn  # noqa: E402
from lib import ir_raw  # noqa: E402


def build(yaml_text: str, name: str = "template.yaml") -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / name
        p.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
        return cfn.build_raw(p, Path(tmp))


def props(raw: dict, address: str) -> dict:
    return next(r for r in raw["resources"] if r["address"] == address)["props"]


def refs(raw: dict, frm: str | None = None) -> list[tuple]:
    return [(r["from"], r["path"], r["to"], r["attr"], r["fn"], r["state"]) for r in raw["references"]
            if frm is None or r["from"] == frm]


def assert_valid(test: unittest.TestCase, raw: dict) -> None:
    test.assertEqual(v.schema_errors(raw), [])
    test.assertEqual(ir_raw.semantic_errors(raw), [])


BASE = """
AWSTemplateFormatVersion: '2010-09-09'
Parameters:
  Env:
    Type: String
    Default: dev
  Subnets:
    Type: CommaDelimitedList
    Default: subnet-a,subnet-b
  KeyName:
    Type: String
Resources:
  Bucket:
    Type: AWS::S3::Bucket
  Topic:
    Type: AWS::SNS::Topic
"""


class ShortTagTest(unittest.TestCase):
    def test_short_and_long_forms_are_the_same(self):
        short = build(BASE + """
  Fn:
    Type: AWS::Lambda::Function
    Properties:
      A: !Ref Bucket
      B: !GetAtt Bucket.Arn
      C: !GetAtt [Topic, TopicName]
      D: !Sub "${Bucket}/x"
""")
        long_ = build(BASE + """
  Fn:
    Type: AWS::Lambda::Function
    Properties:
      A: {Ref: Bucket}
      B: {"Fn::GetAtt": [Bucket, Arn]}
      C: {"Fn::GetAtt": [Topic, TopicName]}
      D: {"Fn::Sub": "${Bucket}/x"}
""")
        self.assertEqual(props(short, "Fn"), props(long_, "Fn"))
        self.assertEqual(refs(short), refs(long_))
        assert_valid(self, short)

    def test_version_stays_a_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.yaml"
            p.write_text(BASE, encoding="utf-8")
            self.assertEqual(cfn.load_template(p)["AWSTemplateFormatVersion"], "2010-09-09")

    def test_json_template(self):
        raw = build(json.dumps({"Resources": {"Bucket": {"Type": "AWS::S3::Bucket"},
                                              "Fn": {"Type": "AWS::Lambda::Function",
                                                     "Properties": {"A": {"Ref": "Bucket"}}}}}), "t.json")
        self.assertEqual(props(raw, "Fn"), {"A": {"$res": "Bucket", "attr": None}})
        assert_valid(self, raw)


class IntrinsicTest(unittest.TestCase):
    def test_values(self):
        raw = build(BASE + """
  Fn:
    Type: AWS::Lambda::Function
    Properties:
      GetAttNested: !GetAtt Bucket.Foo.Bar
      Env: !Ref Env
      Key: !Ref KeyName
      Region: !Ref AWS::Region
      Gone: !Ref AWS::NoValue
      List: [a, !Ref AWS::NoValue, b]
      SubLiteral: !Sub "${!Literal}-${Env}"
      SubVars: !Sub ["${X}-${AWS::AccountId}", {X: !GetAtt Topic.TopicName}]
      SubAttr: !Sub "arn:${Bucket.Arn}/*"
      JoinAll: !Join ["-", [a, b, !Ref Env]]
      JoinRef: !Join [",", [!Ref Bucket, !Ref Topic]]
      Az0: !Select [1, !GetAZs ""]
      AzAll: !GetAZs ""
      Pick: !Select [1, [!Ref Bucket, !Ref Topic]]
      Split: !Split [",", !Join [",", [!Ref Bucket, !Ref Topic]]]
      ParamList: !Ref Subnets
      Import: !ImportValue shared-vpc
      Json: !Sub '{"Rules": [{"Resource": ["collection/${Bucket}"]}], "Arn": "${Topic}"}'
      Dollar: {"$schema": "x"}
      Number: 8080
""")
        p = props(raw, "Fn")
        self.assertEqual(p["GetAttNested"], {"$res": "Bucket", "attr": "Foo.Bar"})
        self.assertEqual(p["Env"], "dev")
        self.assertEqual(p["Key"], {"$unknown": "parameter KeyName has no value"})
        self.assertEqual(p["Region"], {"$pseudo": "AWS::Region"})
        self.assertNotIn("Gone", p)
        self.assertEqual(p["List"], ["a", "b"])
        self.assertEqual(p["SubLiteral"], "${Literal}-dev")
        self.assertEqual(p["SubVars"], {"$concat": [{"$res": "Topic", "attr": "TopicName"}, "-",
                                                    {"$pseudo": "AWS::AccountId"}]})
        self.assertEqual(p["SubAttr"], {"$concat": ["arn:", {"$res": "Bucket", "attr": "Arn"}, "/*"]})
        self.assertEqual(p["JoinAll"], "a-b-dev")
        self.assertEqual(p["Az0"], {"$az": 1})
        self.assertEqual(p["AzAll"], {"$az": "*"})
        self.assertEqual(p["Pick"], {"$res": "Topic", "attr": None})
        self.assertEqual(p["Split"], [{"$res": "Bucket", "attr": None}, {"$res": "Topic", "attr": None}])
        self.assertEqual(p["ParamList"], ["subnet-a", "subnet-b"])
        self.assertEqual(p["Import"], {"$import": "shared-vpc"})
        self.assertEqual(p["Json"], {"$json": {"Rules": [{"Resource": [{"$concat": ["collection/", {"$res": "Bucket", "attr": None}]}]}],
                                               "Arn": {"$res": "Topic", "attr": None}}})
        self.assertEqual(p["Dollar"], {"$$schema": "x"})
        self.assertEqual(p["Number"], 8080)
        r = refs(raw, "Fn")
        self.assertIn(("Fn", "Properties.SubAttr", "Bucket", "Arn", "Sub", "active"), r)
        self.assertIn(("Fn", "Properties.SubVars", "Topic", "TopicName", "GetAtt", "active"), r)
        # Select で選ばれなかった要素の参照は pruned
        self.assertIn(("Fn", "Properties.Pick", "Bucket", None, "Ref", "pruned"), r)
        # $json の中は位置を続ける
        self.assertIn(("Fn", "Properties.Json.Rules[0].Resource[0]", "Bucket", None, "Sub", "active"), r)
        self.assertIn(("Fn", "Properties.Json.Arn", "Topic", None, "Sub", "active"), r)
        self.assertEqual(raw["evaluation"]["parameters"]["Env"], "dev")
        assert_valid(self, raw)

    def test_undecidable_and_unevaluated_keep_references(self):
        # KeyName には値が無いので、HasKey は決まらない（None）
        raw = build("""
Conditions:
  HasKey: !Not [!Equals [!Ref KeyName, ""]]
""" + BASE + """
  Fn:
    Type: AWS::Lambda::Function
    Condition: HasKey
    Properties:
      If: !If [HasKey, !Ref Bucket, !Ref Topic]
      Code:
        ZipFile: !Base64 {"Fn::Sub": "${Topic}"}
      Policy:
        Condition: {StringEquals: {"aws:SourceArn": !Ref Topic}}
""")
        res = next(r for r in raw["resources"] if r["address"] == "Fn")
        self.assertIsNone(res["enabled"])
        p = res["props"]
        self.assertIn("$unknown", p["If"])
        self.assertIn("$unknown", p["Code"]["ZipFile"])
        # IAM の Condition はふつうのプロパティ
        self.assertEqual(p["Policy"]["Condition"], {"StringEquals": {"aws:SourceArn": {"$res": "Topic", "attr": None}}})
        r = refs(raw, "Fn")
        self.assertIn(("Fn", "Properties.If", "Bucket", None, "Ref", "unevaluated"), r)
        self.assertIn(("Fn", "Properties.If", "Topic", None, "Ref", "unevaluated"), r)
        self.assertIn(("Fn", "Properties.Code.ZipFile", "Topic", None, "Sub", "unevaluated"), r)
        self.assertIn(("Fn", 'Properties.Policy.Condition.StringEquals["aws:SourceArn"]', "Topic", None, "Ref", "active"), r)
        codes = {d["code"] for d in raw["diagnostics"]}
        self.assertIn("CFN-CONDITION-UNKNOWN", codes)
        self.assertIsNone(raw["evaluation"]["conditions"]["HasKey"])
        assert_valid(self, raw)

    def test_depends_on_and_metadata(self):
        raw = build(BASE + """
  Fn:
    Type: AWS::Lambda::Function
    DependsOn: [Bucket, Topic]
    Metadata:
      Init: !Sub "aws sns publish ${Topic}"
  Fn2:
    Type: AWS::Lambda::Function
    DependsOn: Bucket
""")
        r = refs(raw)
        self.assertIn(("Fn", "DependsOn", "Bucket", None, "DependsOn", "active"), r)
        self.assertIn(("Fn", "DependsOn", "Topic", None, "DependsOn", "active"), r)
        self.assertIn(("Fn2", "DependsOn", "Bucket", None, "DependsOn", "active"), r)
        self.assertIn(("Fn", "Metadata.Init", "Topic", None, "Sub", "active"), r)
        self.assertEqual(props(raw, "Fn"), {})
        assert_valid(self, raw)

    def test_output_is_deterministic(self):
        a = cfn.dump(build(BASE))
        b = cfn.dump(build(BASE))
        self.assertEqual(a, b)


class RobustnessTest(unittest.TestCase):
    """第三者レビュー（2026-10-17）で見つかった入力。"""

    def test_long_form_getatt_string(self):
        raw = build(BASE + """
  Fn:
    Type: AWS::Lambda::Function
    Properties:
      A: {"Fn::GetAtt": "Topic.TopicName"}
      B: {"Fn::If": [X, {"Fn::GetAtt": "Bucket.Arn"}, x]}
""")
        self.assertEqual(props(raw, "Fn")["A"], {"$res": "Topic", "attr": "TopicName"})
        r = refs(raw, "Fn")
        self.assertIn(("Fn", "Properties.A", "Topic", "TopicName", "GetAtt", "active"), r)
        self.assertIn(("Fn", "Properties.B", "Bucket", "Arn", "GetAtt", "unevaluated"), r)
        assert_valid(self, raw)

    def test_malformed_inputs_become_diagnostics(self):
        raw = build("""
Transform: AWS::LanguageExtensions
Resources:
  Bucket:
    Type: AWS::S3::Bucket
  Broken: hello
  NoType:
    Properties: {}
  "Fn::ForEach::Queues":
    - Name
    - [a, b]
    - "Queue${Name}":
        Type: AWS::SQS::Queue
  Fn:
    Type: AWS::Lambda::Function
    Properties:
      NoValueInSub: !Sub ["${V}-x", {V: !Ref AWS::NoValue}]
      Bool: !Join ["", ["a", true]]
      Resolve: !Sub "x-{{resolve:ssm:/p}}-${Bucket}"
      Import: !ImportValue {"Fn::Sub": "${AWS::StackName}-Vpc"}
""")
        self.assertEqual(sorted(r["address"] for r in raw["resources"]), ["Bucket", "Fn", "Queuea", "Queueb"])
        codes = [(d["address"], d["code"]) for d in raw["diagnostics"]]
        self.assertIn(("Broken", "CFN-MALFORMED-RESOURCE"), codes)
        self.assertIn(("NoType", "CFN-MALFORMED-RESOURCE"), codes)
        p = props(raw, "Fn")
        self.assertIn("$unknown", p["NoValueInSub"])
        self.assertEqual(p["Bool"], "atrue")
        self.assertIn("$unknown", p["Resolve"])
        self.assertIn("$unknown", p["Import"])
        assert_valid(self, raw)

    def test_plain_json_string_becomes_json(self):
        raw = build(BASE + """
  Policy:
    Type: AWS::OpenSearchServerless::SecurityPolicy
    Properties:
      Policy: '{"Rules": [{"ResourceType": "collection", "$x": 1}]}'
      NotJson: '{not json'
""")
        p = props(raw, "Policy")
        self.assertEqual(p["Policy"], {"$json": {"Rules": [{"ResourceType": "collection", "$$x": 1}]}})
        self.assertEqual(p["NotJson"], "{not json")
        assert_valid(self, raw)

    def test_tab_indented_json_with_template_extension(self):
        raw = build('{\n\t"Resources": {\n\t\t"Bucket": {"Type": "AWS::S3::Bucket"}\n\t}\n}\n', "x.template")
        self.assertEqual([r["address"] for r in raw["resources"]], ["Bucket"])

    def test_duplicate_diagnostics_are_merged(self):
        raw = build(BASE + """
  Fn:
    Type: AWS::Lambda::Function
    Properties:
      A: !Sub "${KeyName}-${KeyName}"
""")
        same = [d for d in raw["diagnostics"] if d["address"] == "Fn" and d["code"] == "CFN-UNRESOLVED-PARAM"]
        self.assertEqual(len(same), 1)


class CfnLintGraphTest(unittest.TestCase):
    """CRITERIA の 1.6（C1）の回帰テスト。照合は aws-iac-diagram-workspace/tools/c1_check.py（フェーズ1 の手順5）。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "aws-iac-diagram-workspace" / "tools"))
        import c1_check
        cls.c1 = c1_check

    def test_fixture_templates(self):
        # 自作 fixture の5構成（three-tier-modules は root から子5つを展開して照合する）
        tops = ["three-tier/template.yaml", "serverless-api/template.yaml", "vpc-endpoints/template.json",
                "rag/template.yaml", "three-tier-modules/root.yaml"]
        edges = {}
        for t in tops:
            r = self.c1.check_input(FIXTURES / t)
            with self.subTest(t):
                self.assertEqual(r["unmatched"], [])
            edges[t] = r["edges"]
        self.assertEqual(edges["three-tier-modules/root.yaml"], 53)  # 第三者レビューで数えた辺（root と子5つ）
        self.assertEqual(sum(edges.values()), 214)

    def test_each_child_template_alone(self):
        # 子テンプレートを単独で読んでも、対応の無い辺は無い
        for t in sorted((FIXTURES / "three-tier-modules").glob("*.yaml")):
            with self.subTest(t.name):
                self.assertEqual(self.c1.check_input(t)["unmatched"], [])

    def test_public_nested_stacks(self):
        public = ROOT / "aws-iac-diagram-workspace" / "fixtures" / "public"
        vpcp = public / "aws-cloudformation-templates" / "Solutions" / "VPCPeering" / "templates"
        cases = {  # 第三者レビュー（2026-10-17）で数えた辺の数
            public / "ecs-refarch-cloudformation" / "master.yaml": 90,
            public / "amazon-cloudfront-secure-static-site" / "templates" / "main.yaml": 18,
            vpcp / "VPCPeering-Requester.main.cfn.yaml": 1,
            vpcp / "VPCPeering-Requester.main.cfn.json": 1,
            vpcp / "VPCPeering-Accepter.main.cfn.yaml": 5,
        }
        for top, n in cases.items():
            with self.subTest(top.name):
                r = self.c1.check_input(top)
                self.assertEqual(r["unmatched"], [])
                self.assertEqual(r["edges"], n)

    def test_after_transform_globals_and_foreach(self):
        # cfn-lint --build-graph と同じく、変換（SAM の Globals、Fn::ForEach）の後のグラフで照合する（レビューの M1）
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_files(tmp, {
                "sam.yaml": """
                    Transform: AWS::Serverless-2016-10-31
                    Globals:
                      Function:
                        Environment:
                          Variables: {T: !Ref Topic}
                    Resources:
                      Topic: {Type: AWS::SNS::Topic}
                      F:
                        Type: AWS::Serverless::Function
                        Properties: {Runtime: python3.13, Handler: app.handler, InlineCode: x}
                    """,
                "foreach.yaml": """
                    Transform: AWS::LanguageExtensions
                    Resources:
                      T: {Type: AWS::SNS::Topic}
                      "Fn::ForEach::Q":
                        - N
                        - [a, b]
                        - "Q${N}":
                            Type: AWS::SQS::Queue
                            Properties: {Tags: [{Key: t, Value: !Ref T}]}
                    """,
            })
            sam = self.c1.check_input(tmp / "sam.yaml")
            fe = self.c1.check_input(tmp / "foreach.yaml")
        self.assertEqual((sam["edges"], sam["unmatched"]), (1, []))
        self.assertEqual((fe["edges"], fe["unmatched"]), (2, []))

    def test_discover_includes_all_required_inputs(self):
        # CRITERIA の 1.6 の対象（C01〜C05、SAM 版、自作 fixture）が、探した入力にすべて含まれる（レビューの R1）
        self.assertEqual(self.c1.missing_required(self.c1.discover()), [])

    def test_fixture_edge_counts(self):
        # cfn-lint の挙動が変わったら気づけるように、辺の数を固定する
        counts = {"three-tier/template.yaml": 60, "serverless-api/template.yaml": 14,
                  "vpc-endpoints/template.json": 56, "rag/template.yaml": 31}
        for t, n in counts.items():
            with self.subTest(t):
                self.assertEqual(self.c1.check_input(FIXTURES / t)["edges"], n)

    def test_address_prefix(self):
        ap = self.c1.address_prefix
        self.assertEqual(ap("Vpc"), "")
        self.assertEqual(ap("NetworkStack/Vpc"), "NetworkStack/")
        self.assertEqual(ap("A/B/Vpc"), "A/B/")
        self.assertEqual(ap("App::Vpc"), "App::")
        self.assertEqual(ap("App::Child/Queue"), "App::Child/")
        self.assertEqual(ap("Queue*"), "")

    def test_prefix_match(self):
        pm = self.c1.prefix_match
        self.assertTrue(pm("Properties.Policy", "Properties.Policy.Statement[0]"))
        self.assertTrue(pm("Properties.A[0]", "Properties.A"))
        self.assertFalse(pm("Properties.Ab", "Properties.A"))



def write_files(tmp: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8")


def ref_by(raw: dict, frm: str, path: str) -> list[dict]:
    return [r for r in raw["references"] if r["from"] == frm and r["path"] == path]


class NestedStackTest(unittest.TestCase):
    """フェーズ1 の手順3: ネストスタック（ir-schema.md の 7.2〜7.4）。"""

    def test_three_tier_modules(self):
        raw = cfn.build_raw(FIXTURES / "three-tier-modules" / "root.yaml", ROOT / "aws-iac-diagram-workspace")
        assert_valid(self, raw)
        self.assertEqual(raw["diagnostics"], [])
        lb = next(r for r in raw["resources"] if r["address"] == "AlbStack/LoadBalancer")
        self.assertEqual(lb["via"], "nested_stack")
        self.assertEqual(lb["file"], "alb.yaml")
        # 親の !Join で渡したサブネットの一覧を、子の List 型のパラメータで分ける
        self.assertEqual(lb["props"]["Subnets"], [{"$res": "NetworkStack/PublicSubnet1", "attr": None},
                                                  {"$res": "NetworkStack/PublicSubnet2", "attr": None}])
        r = ref_by(raw, "AlbStack/LoadBalancer", "Properties.Subnets[0]")[0]
        self.assertEqual(r["through"], ["AlbStack.Parameters.PublicSubnetIds", "NetworkStack.Outputs.PublicSubnetIds"])
        # スタックのリソース自身は、Parameters を分けずに持つ
        stack = next(x for x in raw["resources"] if x["address"] == "AlbStack")
        self.assertIn("$concat", stack["props"]["Parameters"]["PublicSubnetIds"])
        self.assertNotIn("via", stack)
        self.assertEqual(raw["evaluation"]["parameters"]["AlbStack/AppPort"], 8080)

    def test_unreadable_child_is_blackbox_and_url_is_remapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_files(tmp, {
                "main.yaml": """
                    Resources:
                      Net:
                        Type: AWS::CloudFormation::Stack
                        Properties:
                          TemplateURL: https://s3.amazonaws.com/bucket/infra/vpc.yaml
                      Gone:
                        Type: AWS::CloudFormation::Stack
                        Properties:
                          TemplateURL: https://s3.amazonaws.com/bucket/missing.yaml
                      Twice:
                        Type: AWS::CloudFormation::Stack
                        Properties:
                          TemplateURL: https://s3.amazonaws.com/bucket/x/sg.yaml
                      Fn:
                        Type: AWS::Lambda::Function
                        Properties:
                          Vpc: !GetAtt Net.Outputs.VpcId
                          Other: !GetAtt Gone.Outputs.Id
                    """,
                "infra/vpc.yaml": """
                    Resources:
                      Vpc: {Type: AWS::EC2::VPC}
                    Outputs:
                      VpcId: {Value: !Ref Vpc}
                    """,
                "vpc.yaml": "Resources: {Other: {Type: AWS::EC2::VPC}}\n",
                "a/sg.yaml": "Resources: {A: {Type: AWS::EC2::SecurityGroup}}\n",
                "b/sg.yaml": "Resources: {B: {Type: AWS::EC2::SecurityGroup}}\n",
            })
            raw = cfn.build_raw(tmp / "main.yaml", tmp)
        assert_valid(self, raw)
        res = {r["address"]: r for r in raw["resources"]}
        # 末尾から最も多く一致する infra/vpc.yaml を読む（vpc.yaml ではない）
        self.assertIn("Net/Vpc", res)
        self.assertNotIn("Net/Other", res)
        self.assertTrue(any("infra/vpc.yaml" in a for a in raw["evaluation"]["assumptions"]))
        # 見つからない・2つ以上一致する子は黒箱
        self.assertEqual(res["Gone"]["via"], "module_blackbox")
        self.assertEqual(res["Twice"]["via"], "module_blackbox")
        self.assertEqual(res["Fn"]["props"]["Vpc"], {"$res": "Net/Vpc", "attr": None})
        self.assertEqual(res["Fn"]["props"]["Other"], {"$res": "Gone", "attr": "Outputs.Id"})
        codes = [(d["address"], d["code"]) for d in raw["diagnostics"]]
        self.assertIn(("Gone", "CFN-NESTED-UNREADABLE"), codes)
        self.assertIn(("Twice", "CFN-NESTED-UNREADABLE"), codes)

    def nested(self, files: dict[str, str]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_files(tmp, files)
            raw = cfn.build_raw(tmp / "main.yaml", tmp)
        assert_valid(self, raw)
        return raw

    def test_output_that_cannot_be_evaluated_keeps_references(self):
        # 第三者レビューの M1: 出力が Fn::If（手順4 まで評価しない）や文字列でも、参照を失わない
        raw = self.nested({
            "main.yaml": """
                Resources:
                  Kid:
                    Type: AWS::CloudFormation::Stack
                    Properties: {TemplateURL: kid.yaml}
                  Fn:
                    Type: AWS::Lambda::Function
                    Properties:
                      A: !GetAtt Kid.Outputs.Arn
                      B: !GetAtt Kid.Outputs.Literal
                """,
            "kid.yaml": """
                Parameters:
                  Mode: {Type: String}
                Conditions:
                  C: !Equals [!Ref Mode, x]
                Resources:
                  Q: {Type: AWS::SQS::Queue}
                  T: {Type: AWS::SNS::Topic}
                Outputs:
                  Arn: {Value: !If [C, !GetAtt Q.Arn, !Ref T]}
                  Literal: {Value: fixed}
                """})
        r = refs(raw, "Fn")
        self.assertIn(("Fn", "Properties.A", "Kid/Q", "Arn", "GetAtt", "unevaluated"), r)
        self.assertIn(("Fn", "Properties.A", "Kid/T", None, "Ref", "unevaluated"), r)
        self.assertIn(("Fn", "Properties.A", "Kid", "Outputs.Arn", "GetAtt", "unevaluated"), r)
        self.assertIn(("Fn", "Properties.B", "Kid", "Outputs.Literal", "GetAtt", "unevaluated"), r)
        moved = [x for x in raw["references"] if x["from"] == "Fn" and x["to"] == "Kid/Q"][0]
        self.assertEqual(moved["through"], ["Kid.Outputs.Arn"])
        self.assertTrue(any(d["address"] == "Kid" and d["path"] == "Outputs.Arn" for d in raw["diagnostics"]))

    def test_condition_on_parent_stack_is_inherited(self):
        raw = self.nested({
            "main.yaml": """
                Parameters:
                  Mode: {Type: String}
                Conditions:
                  Maybe: !Equals [!Ref Mode, on]
                  Never: !Equals [a, b]
                Resources:
                  Kid:
                    Type: AWS::CloudFormation::Stack
                    Condition: Maybe
                    Properties: {TemplateURL: kid.yaml}
                  Off:
                    Type: AWS::CloudFormation::Stack
                    Condition: Never
                    Properties: {TemplateURL: kid.yaml}
                """,
            "kid.yaml": "Resources: {Q: {Type: AWS::SQS::Queue}}\n"})
        res = {r["address"]: r for r in raw["resources"]}
        self.assertIsNone(res["Kid"]["enabled"])
        self.assertIsNone(res["Kid/Q"]["enabled"])
        self.assertFalse(res["Off"]["enabled"])
        self.assertFalse(res["Off/Q"]["enabled"])

    def test_single_item_join_into_list_parameter(self):
        raw = self.nested({
            "main.yaml": """
                Resources:
                  Sub1: {Type: AWS::EC2::Subnet}
                  Kid:
                    Type: AWS::CloudFormation::Stack
                    Properties:
                      TemplateURL: kid.yaml
                      Parameters:
                        S: !Join [",", [!Ref Sub1]]
                """,
            "kid.yaml": """
                Parameters:
                  S: {Type: "List<AWS::EC2::Subnet::Id>"}
                Resources:
                  I:
                    Type: AWS::EC2::Instance
                    Properties: {SubnetId: !Select [0, !Ref S]}
                """})
        self.assertEqual(props(raw, "Kid/I")["SubnetId"], {"$res": "Sub1", "attr": None})

    def test_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_files(tmp, {"loop.yaml": """
                Resources:
                  Self:
                    Type: AWS::CloudFormation::Stack
                    Properties: {TemplateURL: loop.yaml}
                """})
            raw = cfn.build_raw(tmp / "loop.yaml", tmp)
        self.assertIn("CFN-NESTED-CYCLE", [d["code"] for d in raw["diagnostics"]])
        assert_valid(self, raw)


class SamTest(unittest.TestCase):
    def test_globals_and_implicit_apis(self):
        raw = build("""
Transform: AWS::Serverless-2016-10-31
Globals:
  Function:
    Runtime: python3.13
    Environment:
      Variables: {STAGE: dev}
    Layers: [arn:aws:lambda:::layer:a]
Resources:
  Table:
    Type: AWS::Serverless::SimpleTable
  Fn:
    Type: AWS::Serverless::Function
    Properties:
      Runtime: python3.12
      Environment:
        Variables: {TABLE: !Ref Table}
      Layers: [arn:aws:lambda:::layer:b]
      Events:
        Rest: {Type: Api, Properties: {Path: /x, Method: get}}
        Http: {Type: HttpApi}
""")
        p = props(raw, "Fn")
        self.assertEqual(p["Runtime"], "python3.12")  # 値はリソースの方
        self.assertEqual(p["Environment"]["Variables"], {"STAGE": "dev", "TABLE": {"$res": "Table", "attr": None}})
        self.assertEqual(p["Layers"], ["arn:aws:lambda:::layer:a", "arn:aws:lambda:::layer:b"])
        implicit = {r["address"]: r for r in raw["resources"] if r.get("implicit")}
        self.assertEqual(implicit["ServerlessRestApi"]["type"], "AWS::Serverless::Api")
        self.assertEqual(implicit["ServerlessHttpApi"]["type"], "AWS::Serverless::HttpApi")
        assert_valid(self, raw)

    def test_globals_do_not_merge_into_intrinsics_and_apply_to_implicit_api(self):
        # 第三者レビューの M4
        raw = build("""
Transform: AWS::Serverless-2016-10-31
Conditions:
  C: !Equals [a, b]
Globals:
  Function:
    Environment:
      Variables: {STAGE: dev}
  Api:
    EndpointConfiguration: PRIVATE
Resources:
  Q: {Type: AWS::SQS::Queue}
  Fn:
    Type: AWS::Serverless::Function
    Properties:
      Environment: !If [C, {Variables: {X: !Ref Q}}, !Ref AWS::NoValue]
      Events:
        Rest: {Type: Api, Properties: {Path: /x, Method: get}}
  Sm:
    Type: AWS::Serverless::StateMachine
    Properties:
      Events:
        Rest: {Type: Api, Properties: {Path: /y, Method: post}}
""")
        p = props(raw, "Fn")
        # !If は1つの値として扱い Globals を混ぜない。条件 C は偽なので AWS::NoValue が選ばれ、Environment ごと消える
        self.assertNotIn("Environment", p)
        self.assertIn(("Fn", "Properties.Environment", "Q", None, "Ref", "pruned"), refs(raw, "Fn"))
        api = next(r for r in raw["resources"] if r["address"] == "ServerlessRestApi")
        self.assertEqual(api["props"], {"EndpointConfiguration": "PRIVATE"})
        self.assertEqual(len([r for r in raw["resources"] if r.get("implicit")]), 1)
        assert_valid(self, raw)

    def test_explicit_api_has_no_implicit(self):
        raw = cfn.build_raw(FIXTURES / "serverless-api" / "template.yaml", ROOT / "aws-iac-diagram-workspace")
        self.assertFalse([r for r in raw["resources"] if r.get("implicit")])


class CdkOutTest(unittest.TestCase):
    def test_multiple_stacks_exports_and_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp) / "cdk.out"
            files = {
                "manifest.json": json.dumps({"version": "36.0.0", "artifacts": {
                    "Tree": {"type": "cdk:tree"},
                    "NetStack": {"type": "aws:cloudformation:stack",
                                 "properties": {"templateFile": "NetStack.template.json", "stackName": "Net-Stack"}},
                    "AppStack": {"type": "aws:cloudformation:stack",
                                 "properties": {"templateFile": "AppStack.template.json"}}}}),
                "NetStack.template.json": json.dumps({
                    "Resources": {"Vpc": {"Type": "AWS::EC2::VPC"}},
                    "Outputs": {"VpcId": {"Value": {"Ref": "Vpc"}, "Export": {"Name": "net-vpc-id"}}}}),
                "AppStack.template.json": json.dumps({"Resources": {
                    "Sg": {"Type": "AWS::EC2::SecurityGroup",
                           "Properties": {"VpcId": {"Fn::ImportValue": "net-vpc-id"},
                                          "Other": {"Fn::ImportValue": "not-exported"}}},
                    "Child": {"Type": "AWS::CloudFormation::Stack",
                              "Metadata": {"aws:asset:path": "AppStackChild1234.nested.template.json"},
                              "Properties": {"TemplateURL": {"Fn::Join": ["", ["https://s3.", {"Ref": "AWS::URLSuffix"}, "/x/abc.json"]]}}},
                    "Fn": {"Type": "AWS::Lambda::Function",
                           "Properties": {"Q": {"Fn::GetAtt": ["Child", "Outputs.QueueUrl"]}}}}}),
                "AppStackChild1234.nested.template.json": json.dumps({
                    "Resources": {"Queue": {"Type": "AWS::SQS::Queue"}},
                    "Outputs": {"QueueUrl": {"Value": {"Ref": "Queue"}}}}),
            }
            write_files(tmp, files)
            raw = cfn.build_raw(tmp, tmp.parent)
        assert_valid(self, raw)
        self.assertEqual(raw["root"], "cdk.out")
        res = {r["address"]: r for r in raw["resources"]}
        self.assertEqual(set(res), {"Net-Stack::Vpc", "AppStack::Sg", "AppStack::Child", "AppStack::Child/Queue",
                                    "AppStack::Fn"})
        self.assertEqual(res["AppStack::Sg"]["file"], "AppStack.template.json")
        self.assertEqual(res["AppStack::Child/Queue"]["via"], "nested_stack")
        # 入力の中で解決できた ImportValue（7.2・7.3）
        self.assertEqual(res["AppStack::Sg"]["props"]["VpcId"], {"$res": "Net-Stack::Vpc", "attr": None})
        self.assertEqual(res["AppStack::Sg"]["props"]["Other"], {"$import": "not-exported"})
        r = ref_by(raw, "AppStack::Sg", "Properties.VpcId")[0]
        self.assertEqual((r["fn"], r["through"]), ("ImportValue", ["Export:net-vpc-id"]))
        r = ref_by(raw, "AppStack::Fn", "Properties.Q")[0]
        self.assertEqual((r["to"], r["through"]), ("AppStack::Child/Queue", ["AppStack::Child.Outputs.QueueUrl"]))

    def test_stage_duplicate_names_and_exports(self):
        # 第三者レビューの R1: Stage（入れ子のアセンブリ）、同じ stackName、Export の衝突と AWS::StackName
        def stack(resources, outputs=None):
            return json.dumps({"Resources": resources, "Outputs": outputs or {}})
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp) / "cdk.out"
            write_files(tmp, {
                "manifest.json": json.dumps({"artifacts": {
                    "assembly-Prod": {"type": "cdk:cloud-assembly", "properties": {"directoryName": "assembly-Prod"}},
                    "Top": {"type": "aws:cloudformation:stack", "properties": {"templateFile": "Top.template.json"}}}}),
                "Top.template.json": stack(
                    {"Fn": {"Type": "AWS::Lambda::Function",
                            "Properties": {"A": {"Fn::ImportValue": "Prod-Net-VpcId"},
                                           "B": {"Fn::ImportValue": "dup"}}}},
                    {"X": {"Value": "x", "Export": {"Name": "dup"}}}),
                "assembly-Prod/manifest.json": json.dumps({"artifacts": {
                    "ProdNet": {"type": "aws:cloudformation:stack",
                                "properties": {"templateFile": "ProdNet.template.json", "stackName": "Net"}},
                    "ProdNet2": {"type": "aws:cloudformation:stack",
                                 "properties": {"templateFile": "ProdNet2.template.json", "stackName": "Net"}}}}),
                "assembly-Prod/ProdNet.template.json": stack(
                    {"Vpc": {"Type": "AWS::EC2::VPC"}},
                    {"VpcId": {"Value": {"Ref": "Vpc"}, "Export": {"Name": {"Fn::Sub": "Prod-${AWS::StackName}-VpcId"}}}}),
                "assembly-Prod/ProdNet2.template.json": stack(
                    {"Vpc": {"Type": "AWS::EC2::VPC"}}, {"Y": {"Value": "y", "Export": {"Name": "dup"}}}),
            })
            raw = cfn.build_raw(tmp, tmp.parent)
        assert_valid(self, raw)
        res = {r["address"]: r for r in raw["resources"]}
        # 同じ stackName（Net）が2つあるので artifact の ID を使う
        self.assertEqual(set(res), {"Top::Fn", "ProdNet::Vpc", "ProdNet2::Vpc"})
        self.assertEqual(res["ProdNet::Vpc"]["file"], "assembly-Prod/ProdNet.template.json")
        # Export の名前の AWS::StackName は、address の名前（ProdNet）ではなく本当の stackName（Net）で解く
        self.assertEqual(res["Top::Fn"]["props"]["A"], {"$res": "ProdNet::Vpc", "attr": None})
        # 衝突した Export（dup）は最初に登録したもの（スタックを名前の順に登録するので ProdNet2 の y）を使い、診断を出す
        self.assertEqual(res["Top::Fn"]["props"]["B"], "y")
        codes = {d["code"] for d in raw["diagnostics"]}
        self.assertIn("CFN-CDK-STACKNAME-DUPLICATE", codes)
        self.assertIn("CFN-EXPORT-CONFLICT", codes)

    def test_export_name_with_stack_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp) / "cdk.out"
            write_files(tmp, {
                "manifest.json": json.dumps({"artifacts": {
                    "Net": {"type": "aws:cloudformation:stack", "properties": {"templateFile": "Net.json"}},
                    "App": {"type": "aws:cloudformation:stack", "properties": {"templateFile": "App.json"}}}}),
                "Net.json": json.dumps({"Resources": {"Vpc": {"Type": "AWS::EC2::VPC"}}, "Outputs": {
                    "VpcId": {"Value": {"Ref": "Vpc"}, "Export": {"Name": {"Fn::Sub": "${AWS::StackName}-VpcId"}}}}}),
                "App.json": json.dumps({"Resources": {"Sg": {"Type": "AWS::EC2::SecurityGroup",
                                                             "Properties": {"VpcId": {"Fn::ImportValue": "Net-VpcId"}}}}}),
            })
            raw = cfn.build_raw(tmp, tmp.parent)
        sg = next(r for r in raw["resources"] if r["address"] == "App::Sg")
        self.assertEqual(sg["props"]["VpcId"], {"$res": "Net::Vpc", "attr": None})
        assert_valid(self, raw)


class EvaluationTest(unittest.TestCase):
    """フェーズ1 の手順4: A4（CloudFormation 側の評価）。"""

    def three_tier(self, env: str | None = None) -> dict:
        params = {"EnvType": env} if env else None
        return cfn.build_raw(FIXTURES / "three-tier" / "template.yaml", ROOT / "aws-iac-diagram-workspace", params)

    def test_three_tier_dev_and_prod(self):
        dev, prod = self.three_tier(), self.three_tier("prod")
        for raw in (dev, prod):
            assert_valid(self, raw)
            self.assertFalse([d for d in raw["diagnostics"] if d["level"] in ("warn", "error")
                              and d["code"] != "CFN-SSM-PARAM"], raw["diagnostics"])
        self.assertEqual(dev["evaluation"]["conditions"], {"IsProd": False})
        self.assertEqual(prod["evaluation"]["conditions"], {"IsProd": True})
        d, p = ({r["address"]: r for r in raw["resources"]} for raw in (dev, prod))
        conditional = sorted(a for a, r in d.items() if r["enabled"] is False)
        self.assertTrue(conditional)  # 踏み台など、IsProd のときだけ作るもの
        for a in conditional:
            self.assertTrue(p[a]["enabled"], a)
        self.assertEqual(d["Vpc"]["props"]["CidrBlock"], "10.0.0.0/16")  # FindInMap
        db = next(a for a, r in d.items() if r["type"] == "AWS::RDS::DBInstance")
        self.assertEqual((d[db]["props"]["MultiAZ"], p[db]["props"]["MultiAZ"]), (False, True))  # Fn::If
        self.assertNotEqual(d[db]["props"]["DBInstanceClass"], p[db]["props"]["DBInstanceClass"])

    def test_vpc_endpoints_parameters_file(self):
        params = cfn.load_parameter_file(FIXTURES / "vpc-endpoints" / "parameters.json")
        self.assertEqual(params, {"Project": "net"})
        raw = cfn.build_raw(FIXTURES / "vpc-endpoints" / "template.json", ROOT / "aws-iac-diagram-workspace", params)
        assert_valid(self, raw)
        self.assertEqual(raw["evaluation"]["parameters"]["Project"], "net")
        vpc = next(r for r in raw["resources"] if r["type"] == "AWS::EC2::VPC")
        names = [t["Value"] for t in vpc["props"].get("Tags", []) if t.get("Key") == "Name"]
        expected = json.loads((ROOT / "aws-iac-diagram-workspace" / "expected" / "vpc-endpoints.ir.json")
                              .read_text(encoding="utf-8"))
        vpc_names = [n["name"] for n in expected["nodes"] if n["type"] == "vpc"]
        self.assertEqual(names, vpc_names)  # 名前が正解 IR と合う（手順2 からの既知の差の解消）

    def test_cli_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "p.json").write_text(json.dumps({"Parameters": {"EnvType": "prod"}}), encoding="utf-8")
            out = tmp / "raw.json"
            code = cfn.main(["--input", str(FIXTURES / "three-tier" / "template.yaml"), "--out", str(out),
                             "--param-file", str(tmp / "p.json"), "--param", "ProjectName=x", "--param", "Nope=1"])
            self.assertEqual(code, 0)
            raw = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(raw["evaluation"]["conditions"], {"IsProd": True})
            self.assertEqual(raw["evaluation"]["parameters"]["ProjectName"], "x")
            self.assertIn("CFN-PARAM-UNUSED", [d["code"] for d in raw["diagnostics"]])
            self.assertEqual(cfn.main(["--input", "x", "--out", str(out), "--param", "noequal"]), 2)

    def test_allowed_values(self):
        raw = self.three_tier("staging")
        self.assertIn("CFN-PARAM-NOT-ALLOWED", [d["code"] for d in raw["diagnostics"]])

    def test_logic_and_pseudo(self):
        text = """
Parameters:
  Mode: {Type: String}
  Count: {Type: Number, Default: 3}
Conditions:
  Unknown: !Equals [!Ref Mode, x]
  T: !Equals [!Ref Count, "3"]
  F: !Not [{Condition: T}]
  AndF: !And [{Condition: Unknown}, {Condition: F}]
  AndU: !And [{Condition: Unknown}, {Condition: T}]
  OrT: !Or [{Condition: Unknown}, {Condition: T}]
  OrU: !Or [{Condition: Unknown}, {Condition: F}]
  NotU: !Not [{Condition: Unknown}]
  InTokyo: !Equals [!Ref AWS::Region, ap-northeast-1]
  On: !Equals [a, a]
Resources:
  Q:
    Type: AWS::SQS::Queue
    Properties:
      Region: !Ref AWS::Region
"""
        raw = build(text)
        c = raw["evaluation"]["conditions"]
        self.assertEqual((c["T"], c["F"], c["AndF"], c["AndU"], c["OrT"], c["OrU"], c["NotU"]),
                         (True, False, False, None, True, None, None))
        self.assertIsNone(c["InTokyo"])
        self.assertTrue(c["On"])  # YAML 1.1 の On は文字列のまま（条件の名前を失わない）
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.yaml"
            p.write_text(textwrap.dedent(text), encoding="utf-8")
            raw = cfn.build_raw(p, Path(tmp), {"AWS::Region": "ap-northeast-1"})
        self.assertTrue(raw["evaluation"]["conditions"]["InTokyo"])
        # 擬似パラメータの値は条件の評価にだけ使い、props は $pseudo のまま
        self.assertEqual(props(raw, "Q")["Region"], {"$pseudo": "AWS::Region"})

    def test_condition_cycle(self):
        raw = build("""
Conditions:
  A: !Not [{Condition: B}]
  B: !Not [{Condition: A}]
Resources:
  Q: {Type: AWS::SQS::Queue, Condition: A}
""")
        self.assertIn("CFN-CONDITION-CYCLE", [d["code"] for d in raw["diagnostics"]])
        assert_valid(self, raw)

    def test_find_in_map_default_length_tojsonstring(self):
        raw = build(BASE + """
  Fn:
    Type: AWS::Lambda::Function
    Properties:
      Missing: !FindInMap [M, a, b]
      WithDefault: !FindInMap [M, a, b, {DefaultValue: d}]
      Length: {"Fn::Length": [1, 2, 3]}
      Json: {"Fn::ToJsonString": {"k": !Ref Bucket}}
""")
        p = props(raw, "Fn")
        self.assertIn("$unknown", p["Missing"])
        self.assertEqual(p["WithDefault"], "d")
        self.assertEqual(p["Length"], 3)
        self.assertEqual(p["Json"], {"$json": {"k": {"$res": "Bucket", "attr": None}}})
        self.assertIn("CFN-MAPPING-MISSING", [d["code"] for d in raw["diagnostics"]])
        assert_valid(self, raw)

    def test_foreach_unresolved_is_xn(self):
        raw = build("""
Transform: AWS::LanguageExtensions
Parameters:
  Names: {Type: CommaDelimitedList}
Resources:
  "Fn::ForEach::Queues":
    - Name
    - !Ref Names
    - "Queue${Name}":
        Type: AWS::SQS::Queue
""")
        q = next(r for r in raw["resources"] if r["address"] == "Queue*")
        self.assertEqual(q["multiplicity"], "N")
        self.assertIn("CFN-FOREACH-UNRESOLVED", [d["code"] for d in raw["diagnostics"]])
        assert_valid(self, raw)

    def test_foreach_with_ampersand_and_ref(self):
        raw = build("""
Transform: AWS::LanguageExtensions
Resources:
  "Fn::ForEach::Topics":
    - Name
    - [a-b, c]
    - "Topic&{Name}":
        Type: AWS::SNS::Topic
        Properties:
          TopicName: !Ref Name
          Display: !Sub "t-${Name}"
""")
        res = {r["address"]: r for r in raw["resources"]}
        self.assertEqual(set(res), {"Topicab", "Topicc"})
        self.assertEqual(res["Topicab"]["props"], {"TopicName": "a-b", "Display": "t-a-b"})


class EvaluationReviewTest(unittest.TestCase):
    """手順4 の第三者レビュー（2026-10-17）で見つかった入力。"""

    def build_with(self, text: str, params: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "t.yaml"
            p.write_text(textwrap.dedent(text), encoding="utf-8")
            return cfn.build_raw(p, Path(tmp), params)

    def test_given_parameter_values(self):
        text = """
Parameters:
  L: {Type: CommaDelimitedList}
  S: {Type: String, Default: d}
  Ami: {Type: "AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>"}
Resources:
  Q:
    Type: AWS::SQS::Queue
    Properties: {A: !Ref L, B: !Ref S, C: !Ref Ami}
"""
        raw = self.build_with(text, {"L": ["a", "b"], "S": None, "Ami": "/aws/service/x"})
        p = props(raw, "Q")
        self.assertEqual(p["A"], ["a", "b"])
        self.assertEqual(p["B"], "d")  # null は渡されていないものとして Default
        self.assertIn("$unknown", p["C"])  # SSM のパラメータの名前は値ではない
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "p.json"
            f.write_text(json.dumps([{"ParameterKey": "S", "UsePreviousValue": True},
                                     {"ParameterKey": "L", "ParameterValue": "x,y"}]), encoding="utf-8")
            self.assertEqual(cfn.load_parameter_file(f), {"L": "x,y"})

    def test_foreach_collisions_inline_and_outputs(self):
        raw = build("""
Transform: AWS::LanguageExtensions
Parameters:
  A: {Type: CommaDelimitedList}
  B: {Type: CommaDelimitedList}
Resources:
  T: {Type: AWS::SNS::Topic}
  "Fn::ForEach::X":
    - I
    - !Ref A
    - "Q${I}":
        Type: AWS::SQS::Queue
        Properties: {Name: !Ref I}
  "Fn::ForEach::Y":
    - J
    - !Ref B
    - "Q${J}":
        Type: AWS::SQS::Queue
  Tagged:
    Type: AWS::SQS::Queue
    Properties:
      Name: q
      "Fn::ForEach::Tags":
        - K
        - [a, b]
        - "${K}": !Ref T
Outputs:
  "Fn::ForEach::Out":
    - N
    - [x]
    - "Out${N}": {Value: !Ref T}
""")
        res = {r["address"]: r for r in raw["resources"]}
        self.assertIn("Q*", res)
        self.assertIn("Q*.Y", res)  # ×N の名前が重なっても落とさない
        self.assertEqual(res["Q*"]["props"], {"Name": "*"})  # 識別子は *（未定義の Ref の警告にしない）
        self.assertEqual(res["Tagged"]["props"], {"Name": "q", "a": {"$res": "T", "attr": None},
                                                  "b": {"$res": "T", "attr": None}})
        self.assertNotIn("CFN-UNDEFINED-REF", [d["code"] for d in raw["diagnostics"]])
        assert_valid(self, raw)

    def test_yaml11_booleans_and_name_positions(self):
        raw = build("""
Conditions:
  Yes: !Equals [on, "true"]
Resources:
  On:
    Type: AWS::SQS::Queue
    Condition: Yes
    Properties:
      Flag: yes
  Q:
    Type: AWS::SQS::Queue
    Properties:
      R: {Ref: On}
""")
        self.assertEqual(raw["evaluation"]["conditions"], {"Yes": True})  # 値の on は YAML 1.1 で真偽値（cfn-lint と同じ）
        res = {r["address"]: r for r in raw["resources"]}
        self.assertIn("On", res)  # キーは元の文字のまま
        self.assertTrue(res["On"]["enabled"])  # Condition: Yes（真偽値）を名前に戻して引く
        self.assertIs(res["On"]["props"]["Flag"], True)
        self.assertEqual(res["Q"]["props"]["R"], {"$res": "On", "attr": None})

    def test_find_in_map_numeric_keys_and_region(self):
        text = """
Mappings:
  Num: {1: {2: x}}
  Ami: {ap-northeast-1: {Id: ami-tokyo}}
Resources:
  I:
    Type: AWS::EC2::Instance
    Properties:
      N: !FindInMap [Num, 1, 2]
      Ami: !FindInMap [Ami, !Ref AWS::Region, Id]
"""
        p = props(self.build_with(text, {"AWS::Region": "ap-northeast-1"}), "I")
        self.assertEqual((p["N"], p["Ami"]), ("x", "ami-tokyo"))

    def test_disabled_function_and_output(self):
        raw = build("""
Transform: AWS::Serverless-2016-10-31
Conditions:
  Never: !Equals [a, b]
Resources:
  Q: {Type: AWS::SQS::Queue}
  Fn:
    Type: AWS::Serverless::Function
    Condition: Never
    Properties:
      Events:
        Rest: {Type: Api, Properties: {Path: /x, Method: get}}
Outputs:
  QArn:
    Condition: Never
    Value: !GetAtt Q.Arn
    Export: {Name: q-arn}
""")
        api = next(r for r in raw["resources"] if r["address"] == "ServerlessRestApi")
        self.assertFalse(api["enabled"])

    def test_disabled_output_is_not_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp) / "cdk.out"
            write_files(tmp, {
                "manifest.json": json.dumps({"artifacts": {
                    "A": {"type": "aws:cloudformation:stack", "properties": {"templateFile": "A.json"}},
                    "B": {"type": "aws:cloudformation:stack", "properties": {"templateFile": "B.json"}}}}),
                "A.json": json.dumps({"Conditions": {"Never": {"Fn::Equals": ["a", "b"]}},
                                      "Resources": {"Q": {"Type": "AWS::SQS::Queue"}},
                                      "Outputs": {"X": {"Condition": "Never", "Value": {"Ref": "Q"},
                                                        "Export": {"Name": "x"}}}}),
                "B.json": json.dumps({"Resources": {"Fn": {"Type": "AWS::Lambda::Function",
                                                           "Properties": {"X": {"Fn::ImportValue": "x"}}}}}),
            })
            raw = cfn.build_raw(tmp, tmp.parent)
        fn = next(r for r in raw["resources"] if r["address"] == "B::Fn")
        self.assertEqual(fn["props"]["X"], {"$import": "x"})


class ExpectedIrTest(unittest.TestCase):
    """正解 IR（expected）の CFN 側の網羅分類と、raw IR の address・type・file・enabled が一致する（第三者レビューの R4）。"""

    def test_addresses_and_enabled_match_expected(self):
        ws = ROOT / "aws-iac-diagram-workspace"
        cases = {
            "three-tier": ("three-tier/template.yaml", None),
            "serverless-api": ("serverless-api/template.yaml", None),
            "vpc-endpoints": ("vpc-endpoints/template.json", "vpc-endpoints/parameters.json"),
            "rag": ("rag/template.yaml", None),
            "three-tier-modules": ("three-tier-modules/root.yaml", None),
        }
        for name, (tpl, pfile) in cases.items():
            with self.subTest(name):
                expected = json.loads((ws / "expected" / f"{name}.ir.json").read_text(encoding="utf-8"))
                params = dict(expected.get("evaluation", {}).get("cfn", {}).get("parameters", {}))
                if pfile:
                    params.update(cfn.load_parameter_file(FIXTURES / pfile))
                raw = cfn.build_raw(FIXTURES / tpl, ws, params)
                got = {r["address"]: (r["type"], r["file"], r["enabled"]) for r in raw["resources"]}
                want = {r["address"]: (r["type"], r["file"], r.get("rule") != "H-COND-FALSE")
                        for r in expected["sources"]["cfn"]["resources"]}
                self.assertEqual(got, want)


class SplitConcatTest(unittest.TestCase):
    def test_split(self):
        A, B = {"$res": "A", "attr": None}, {"$res": "B", "attr": None}
        self.assertEqual(cfn.split_concat([A, ",", B], ","), [A, B])
        self.assertEqual(cfn.split_concat(["x-", A, ",y"], ","), [{"$concat": ["x-", A]}, "y"])


def count_resources(template: Path) -> int:
    """テンプレートのリソースの数。手元のファイルを指すネストスタックは中身も数える。"""
    n = 0
    for body in (cfn.load_template(template).get("Resources") or {}).values():
        n += 1
        url = (body.get("Properties") or {}).get("TemplateURL")
        if body.get("Type") == "AWS::CloudFormation::Stack" and isinstance(url, str) and "://" not in url:
            n += count_resources(template.parent / url)
    return n


class FixtureTest(unittest.TestCase):
    def test_all_fixture_templates_produce_valid_raw(self):
        # parameters.json（パラメータの値のファイル）はテンプレートではないので除く
        templates = sorted(p for p in FIXTURES.rglob("*") if p.suffix in (".yaml", ".json")
                           and p.name != "parameters.json")
        self.assertGreaterEqual(len(templates), 10)
        for t in templates:
            with self.subTest(t.relative_to(FIXTURES).as_posix()):
                raw = cfn.build_raw(t, ROOT / "aws-iac-diagram-workspace")
                assert_valid(self, raw)
                self.assertFalse([d for d in raw["diagnostics"] if d["level"] == "error"])
                self.assertEqual(len(raw["resources"]), count_resources(t))


if __name__ == "__main__":
    unittest.main()
