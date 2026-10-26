"""CloudFormation アダプタ: 短い形のタグ（!Ref など）、組み込み関数（Ref・GetAtt・Sub・Join …）、marks の split_concat。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs
from support.cloudformation import BASE, build
from aws_iac_diagram.adapters.cloudformation import (  # noqa: E402
    build as cfn_build,
    loader as cfn_loader,
    marks as cfn_marks,
)


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
            self.assertEqual(cfn_loader.load_template(p)["AWSTemplateFormatVersion"], "2010-09-09")

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
        a = cfn_build.dump(build(BASE))
        b = cfn_build.dump(build(BASE))
        self.assertEqual(a, b)


class SplitConcatTest(unittest.TestCase):
    def test_split(self):
        A, B = {"$res": "A", "attr": None}, {"$res": "B", "attr": None}
        self.assertEqual(cfn_marks.split_concat([A, ",", B], ","), [A, B])
        self.assertEqual(cfn_marks.split_concat(["x-", A, ",y"], ","), [{"$concat": ["x-", A]}, "y"])


if __name__ == "__main__":
    unittest.main()
