"""CloudFormation アダプタ: Conditions の3値（True／False／None）の論理（adapters/cloudformation/conditions.py）。

R5 の第三者レビューの指摘で足したもの。`EvaluationTest.test_logic_and_pseudo` は 2 つの被演算子の And／Or だけを見ていた。
ここでは、決まらない（None）被演算子が混ざる And／Or・3 つ以上の被演算子・全部が決まるときの結果と、`enabled` を
合わせる `stronger`（どれか 1 つでも作られるなら作られる）・`weaker`（親の Condition を子に引き継ぐ）の真理値表を確かめる。
"""

from __future__ import annotations

import itertools
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.cloudformation import build
from aws_iac_diagram.adapters.cloudformation.conditions import stronger, weaker  # noqa: E402


class ConditionLogicTest(unittest.TestCase):
    TEMPLATE = """
Parameters:
  Mode: {Type: String}
  Other: {Type: String}
Conditions:
  U: !Equals [!Ref Mode, x]
  V: !Equals [!Ref Other, y]
  T: !Equals [a, a]
  F: !Equals [a, b]
  AndTT: !And [{Condition: T}, {Condition: T}]
  AndTU: !And [{Condition: T}, {Condition: U}]
  AndUU: !And [{Condition: U}, {Condition: V}]
  AndUF: !And [{Condition: U}, {Condition: F}]
  AndTTU: !And [{Condition: T}, {Condition: T}, {Condition: U}]
  AndUTF: !And [{Condition: U}, {Condition: T}, {Condition: F}]
  OrFF: !Or [{Condition: F}, {Condition: F}]
  OrFU: !Or [{Condition: F}, {Condition: U}]
  OrUU: !Or [{Condition: U}, {Condition: V}]
  OrUT: !Or [{Condition: U}, {Condition: T}]
  OrFFU: !Or [{Condition: F}, {Condition: F}, {Condition: U}]
  OrUFT: !Or [{Condition: U}, {Condition: F}, {Condition: T}]
  NotT: !Not [{Condition: T}]
  NotF: !Not [{Condition: F}]
  NotU: !Not [{Condition: U}]
  Nested: !And [!Or [{Condition: U}, {Condition: T}], !Not [{Condition: F}]]
  NestedU: !And [!Or [{Condition: U}, {Condition: F}], !Not [{Condition: F}]]
Resources:
  Q:
    Type: AWS::SQS::Queue
"""

    def test_and_or_not_over_known_and_unknown_operands(self):
        c = build(self.TEMPLATE)["evaluation"]["conditions"]
        expected = {
            "T": True, "F": False, "U": None, "V": None,
            # And: False が 1 つでもあれば False、なければ決まらないものがあれば None、全部 True なら True
            "AndTT": True, "AndTU": None, "AndUU": None, "AndUF": False, "AndTTU": None, "AndUTF": False,
            # Or: True が 1 つでもあれば True、なければ決まらないものがあれば None、全部 False なら False
            "OrFF": False, "OrFU": None, "OrUU": None, "OrUT": True, "OrFFU": None, "OrUFT": True,
            "NotT": False, "NotF": True, "NotU": None,
            "Nested": True, "NestedU": None,
        }
        self.assertEqual({k: c[k] for k in expected}, expected)

    def test_resource_enabled_follows_the_condition(self):
        text = self.TEMPLATE.rstrip("\n") + "\n" + "".join(
            f"  R{name}:\n    Type: AWS::SQS::Queue\n    Condition: {name}\n" for name in ("AndTT", "AndTU", "AndUF", "OrFF", "OrFU", "OrUT"))
        raw = build(text)
        enabled = {r["address"]: r["enabled"] for r in raw["resources"]}
        self.assertEqual({k: enabled[k] for k in ("RAndTT", "RAndTU", "RAndUF", "ROrFF", "ROrFU", "ROrUT")},
                         {"RAndTT": True, "RAndTU": None, "RAndUF": False, "ROrFF": False, "ROrFU": None, "ROrUT": True})
        self.assertTrue(enabled["Q"])

    def test_stronger_truth_table(self):
        # true > null > false: どれか 1 つでも作られるなら作られる。決まらないものがあって true が無ければ決まらない
        for a, b in itertools.product((True, None, False), repeat=2):
            want = True if (a is True or b is True) else None if (a is None or b is None) else False
            with self.subTest((a, b)):
                self.assertIs(stronger(a, b), want)

    def test_weaker_truth_table(self):
        # false > null > true: 親の Condition が偽なら子も偽。決まらないものがあって false が無ければ決まらない
        for a, b in itertools.product((True, None, False), repeat=2):
            want = False if (a is False or b is False) else None if (a is None or b is None) else True
            with self.subTest((a, b)):
                self.assertIs(weaker(a, b), want)

    def test_implicit_api_is_enabled_if_any_function_is(self):
        # SAM の暗黙の API は、それを使う関数のどれか 1 つでも作られるなら作られる（stronger）
        def api_enabled(conds: str) -> object:
            fns = "".join(
                f"  Fn{i}:\n    Type: AWS::Serverless::Function\n"
                f"    Condition: {c}\n    Properties:\n      Events:\n        E: {{Type: Api, Properties: {{Path: /x, Method: get}}}}\n"
                for i, c in enumerate(conds.split(",")))
            raw = build("""
Transform: AWS::Serverless-2016-10-31
Parameters:
  Mode: {Type: String}
Conditions:
  U: !Equals [!Ref Mode, x]
  T: !Equals [a, a]
  F: !Equals [a, b]
Resources:
""" + fns)
            return next(r["enabled"] for r in raw["resources"] if r["address"] == "ServerlessRestApi")

        self.assertIs(api_enabled("F,F"), False)
        self.assertIs(api_enabled("F,U"), None)
        self.assertIs(api_enabled("U,F"), None)
        self.assertIs(api_enabled("F,T"), True)
        self.assertIs(api_enabled("U,T"), True)
        self.assertIs(api_enabled("T,U"), True)


if __name__ == "__main__":
    unittest.main()
