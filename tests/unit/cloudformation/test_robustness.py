"""CloudFormation アダプタ: 第三者レビュー（2026-10-17）で見つかった入力（長い形の GetAtt、壊れた入力、JSON の文字列、重複する診断）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs
from support.cloudformation import BASE, build


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


if __name__ == "__main__":
    unittest.main()
