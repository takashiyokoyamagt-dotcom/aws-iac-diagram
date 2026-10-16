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

    def test_deferred_and_unevaluated_keep_references(self):
        raw = build("""
Conditions:
  IsProd: !Equals [!Ref Env, prod]
""" + BASE + """
  Fn:
    Type: AWS::Lambda::Function
    Condition: IsProd
    Properties:
      If: !If [IsProd, !Ref Bucket, !Ref Topic]
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
        self.assertIn("CFN-DEFERRED", codes)
        self.assertIn("CFN-CONDITION-DEFERRED", codes)
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
        self.assertEqual(sorted(r["address"] for r in raw["resources"]), ["Bucket", "Fn"])
        codes = [(d["address"], d["code"]) for d in raw["diagnostics"]]
        self.assertIn(("Broken", "CFN-MALFORMED-RESOURCE"), codes)
        self.assertIn(("NoType", "CFN-MALFORMED-RESOURCE"), codes)
        self.assertIn(("Fn::ForEach::Queues", "CFN-DEFERRED"), codes)
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
    """CRITERIA の 1.6（C1）の回帰テスト。cfn-lint のグラフの辺のすべてに、raw IR の参照が対応する。

    照合: (from, to) が一致し、cfn-lint の属性の場所を最初の Ref／Fn::* で止めたものと raw の path が、
    要素の区切りで前方一致する（どちら向きでも）。ネストスタックをまたぐ辺は手順3 で足す。
    """

    @staticmethod
    def lint_edges(path: Path):
        from cfnlint.decode import decode
        from cfnlint.template import Template
        tpl, _ = decode(str(path))
        g = Template(str(path), tpl, ["us-east-1"]).graph.graph
        res = {n for n, d in g.nodes.items() if d["type"] == "Resource"}
        for a, b, d in g.edges(data=True):
            if a in res and b in res:
                p = ""
                for el in d["source_paths"]:
                    if isinstance(el, str) and (el == "Ref" or el.startswith("Fn::")):
                        break
                    p = ir_raw.join_path(p, el)
                yield a, b, p

    @staticmethod
    def prefix(a: str, b: str) -> bool:
        s, l = sorted((a, b), key=len)  # noqa: E741
        return l == s or l.startswith(s + ".") or l.startswith(s + "[")

    def test_fixture_templates(self):
        templates = sorted(p for p in FIXTURES.rglob("*") if p.suffix in (".yaml", ".json")
                           and p.name != "parameters.json")
        total = 0
        for t in templates:
            raw = cfn.build_raw(t, ROOT / "aws-iac-diagram-workspace")
            pairs = {}
            for r in raw["references"]:
                pairs.setdefault((r["from"], r["to"]), []).append(r["path"])
            for a, b, p in self.lint_edges(t):
                total += 1
                with self.subTest(f"{t.name}: {a} -> {b} {p}"):
                    self.assertTrue(any(self.prefix(p, q) for q in pairs.get((a, b), [])))
        self.assertGreaterEqual(total, 200)


class SplitConcatTest(unittest.TestCase):
    def test_split(self):
        A, B = {"$res": "A", "attr": None}, {"$res": "B", "attr": None}
        self.assertEqual(cfn.split_concat([A, ",", B], ","), [A, B])
        self.assertEqual(cfn.split_concat(["x-", A, ",y"], ","), [{"$concat": ["x-", A]}, "y"])


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
                self.assertEqual(len(raw["resources"]),
                                 len(cfn.load_template(t).get("Resources") or {}))


if __name__ == "__main__":
    unittest.main()
