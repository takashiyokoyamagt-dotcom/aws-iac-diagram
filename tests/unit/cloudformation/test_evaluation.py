"""CloudFormation アダプタ: 評価（A4。Parameters・Conditions・Mappings・Fn::ForEach。params.py・conditions.py・foreach.py・evaluator.py）。
第三者レビュー（2026-10-17）で見つかったものを含む。
"""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props
from support.cloudformation import BASE, build, write_files
from support.paths import FIXTURES_CFN as FIXTURES, ROOT
import adapt_cfn  # noqa: E402
from aws_iac_diagram.adapters.cloudformation import build as cfn_build, params as cfn_params  # noqa: E402


class EvaluationTest(unittest.TestCase):
    """フェーズ1 の手順4: A4（CloudFormation 側の評価）。"""

    def three_tier(self, env: str | None = None) -> dict:
        params = {"EnvType": env} if env else None
        return cfn_build.build_raw(FIXTURES / "three-tier" / "template.yaml", ROOT / "aws-iac-diagram-workspace", params)

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
        params = cfn_params.load_parameter_file(FIXTURES / "vpc-endpoints" / "parameters.json")
        self.assertEqual(params, {"Project": "net"})
        raw = cfn_build.build_raw(FIXTURES / "vpc-endpoints" / "template.json", ROOT / "aws-iac-diagram-workspace", params)
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
            code = adapt_cfn.main(["--input", str(FIXTURES / "three-tier" / "template.yaml"), "--out", str(out),
                             "--param-file", str(tmp / "p.json"), "--param", "ProjectName=x", "--param", "Nope=1"])
            self.assertEqual(code, 0)
            raw = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(raw["evaluation"]["conditions"], {"IsProd": True})
            self.assertEqual(raw["evaluation"]["parameters"]["ProjectName"], "x")
            self.assertIn("CFN-PARAM-UNUSED", [d["code"] for d in raw["diagnostics"]])
            self.assertEqual(adapt_cfn.main(["--input", "x", "--out", str(out), "--param", "noequal"]), 2)

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
            raw = cfn_build.build_raw(p, Path(tmp), {"AWS::Region": "ap-northeast-1"})
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
            return cfn_build.build_raw(p, Path(tmp), params)

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
            self.assertEqual(cfn_params.load_parameter_file(f), {"L": "x,y"})

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
            raw = cfn_build.build_raw(tmp, tmp.parent)
        fn = next(r for r in raw["resources"] if r["address"] == "B::Fn")
        self.assertEqual(fn["props"]["X"], {"$import": "x"})


if __name__ == "__main__":
    unittest.main()
