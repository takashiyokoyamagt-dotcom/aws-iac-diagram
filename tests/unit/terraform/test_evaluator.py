"""Terraform アダプタ: aws_iac_diagram/adapters/terraform/evaluator/ の組み込み関数と型の変換（unknown を含む値の扱い）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
import support  # noqa: E402
support.ensure_paths()  # scripts/ と tools/ を sys.path に入れる（import だけでも入る。明示する）
from aws_iac_diagram.adapters.terraform.evaluator import functions as F, values as V  # noqa: E402


class EvaluatorTest(unittest.TestCase):
    """adapters/terraform/evaluator/ の組み込み関数と型の変換（印を含む値の扱い）。"""

    def test_functions_on_known_values(self):
        call = F.call_function
        self.assertEqual(call("cidrsubnet", ["10.0.0.0/16", 8, 2]), "10.0.2.0/24")
        self.assertEqual(call("cidrsubnets", ["10.0.0.0/16", 4, 8, 4]), ["10.0.0.0/20", "10.0.16.0/24", "10.0.32.0/20"])
        self.assertEqual(call("cidrhost", ["10.0.1.0/24", 5]), "10.0.1.5")
        self.assertEqual(call("cidrnetmask", ["10.0.0.0/12"]), "255.240.0.0")
        self.assertEqual(call("lookup", [{"a": 1}, "b", 2]), 2)
        self.assertEqual(call("element", [["a", "b"], 3]), "b")
        self.assertEqual(call("merge", [{"a": 1, "b": 1}, None, {"b": 2}]), {"a": 1, "b": 2})
        self.assertEqual(call("toset", [["b", "a", "b"]]), ["a", "b"])
        self.assertEqual(call("flatten", [[["a"], [["b"]], "c"]]), ["a", "b", "c"])
        self.assertEqual(call("coalesce", [None, "", "x"]), "x")
        self.assertEqual(call("compact", [["a", "", None, "b"]]), ["a", "b"])
        self.assertEqual(call("keys", [{"b": 1, "a": 2}]), ["a", "b"])
        self.assertEqual(call("values", [{"b": 1, "a": 2}]), [2, 1])
        self.assertEqual(call("replace", ["a-b-c", "/-(\\w)/", "_$1"]), "a_b_c")
        self.assertEqual(call("regex", ["^(\\w+)-(\\d+)$", "app-12"]), ["app", "12"])
        self.assertEqual(call("regexall", ["\\d", "a1b2"]), ["1", "2"])
        self.assertEqual(call("split", [",", "a,b"]), ["a", "b"])
        self.assertEqual(call("join", ["-", ["a", "b"], ["c"]]), "a-b-c")
        self.assertEqual(call("format", ["%s/%d", "x", 3]), "x/3")
        self.assertEqual(call("formatlist", ["%s-%s", ["a", "b"], "z"]), ["a-z", "b-z"])
        self.assertEqual(call("zipmap", [["a", "b"], [1, 2]]), {"a": 1, "b": 2})
        self.assertEqual(call("range", [3]), [0, 1, 2])
        self.assertEqual(call("max", [1, 5, 3]), 5)
        self.assertEqual(call("contains", [["a"], "a"]), True)
        self.assertEqual(call("contains", [[1], True]), False)  # 型を区別する
        self.assertEqual(call("jsondecode", ['{"a": [1]}']), {"a": [1]})
        self.assertEqual(call("base64decode", [call("base64encode", ["hé"])]), "hé")
        self.assertEqual(call("trimsuffix", ["a.tf", ".tf"]), "a")
        self.assertEqual(call("one", [[]]), None)
        self.assertEqual(call("tostring", [1.5]), "1.5")
        for name, args in (("lookup", [{"a": 1}, "b"]), ("element", [[], 0]), ("cidrsubnet", ["10.0.0.0/30", 8, 0]),
                           ("coalesce", [None, ""]), ("slice", [[1], 0, 3]), ("one", [[1, 2]])):
            with self.subTest(name):
                with self.assertRaises(V.EvalError):
                    call(name, args)

    def test_functions_with_markers(self):
        call, R = F.call_function, V.Res
        a, b = R("aws_s3_bucket.a", "id"), R("aws_s3_bucket.b", "arn")
        # 構造だけで決まる関数は、印をそのまま残す
        self.assertEqual(call("concat", [[a], [b]]), [a, b])
        self.assertEqual(call("length", [[a, b]]), 2)
        self.assertEqual(call("lookup", [{"x": a}, "x"]), a)
        self.assertEqual(call("join", [",", [a, "z"]]), V.Concat((a, ",z")))
        self.assertEqual(call("format", ["arn:%s:x", a]), V.Concat(("arn:", a, ":x")))
        self.assertEqual(call("jsonencode", [{"r": a}]), V.Json({"r": a}))
        self.assertEqual(call("slice", [V.Az("*"), 0, 2]), [V.Az(0), V.Az(1)])
        self.assertEqual(call("element", [V.Az("*"), 2]), V.Az(2))
        # 値が要る関数は Unknown（中の参照を持ち歩く）
        for name, args in (("upper", [a]), ("length", [a]), ("split", [",", a]), ("cidrsubnet", [a, 8, 1]),
                           ("contains", [[a], "x"])):
            with self.subTest(name):
                u = call(name, args)
                self.assertIsInstance(u, V.Unknown)
                self.assertIn(("aws_s3_bucket.a", "id", ()), u.refs)
        u = call("upper", [V.Unknown("variable x has no value", "TF-UNRESOLVED-VAR")])
        self.assertEqual((u.reason, u.code), ("variable x has no value", "TF-UNRESOLVED-VAR"))  # 元の理由を引き継ぐ

    def test_convert(self):
        spec = ("object", {"n": (("number",), False, V.NODEFAULT), "l": (("set", ("string",)), True, ["b", "a"]),
                           "o": (("map", ("bool",)), True, V.NODEFAULT)})
        self.assertEqual(V.convert({"n": "5", "extra": 1}, spec), {"n": 5, "l": ["a", "b"], "o": None})
        self.assertEqual(V.convert({"n": 1, "o": {"x": "true"}}, spec)["o"], {"x": True})
        self.assertEqual(V.convert("abc", ("number",)), "abc")  # 変換できなければそのまま
        self.assertEqual(V.convert(3, ("string",)), "3")


class CidrSubnetBoundaryTest(unittest.TestCase):
    """cidrsubnet の netnum と newbits の境目（R5 のレビューの指摘: netnum の上限が 1 ずれても落ちるテストが無かった）。"""

    def call(self, *args):
        return F.call_function("cidrsubnet", list(args))

    def test_netnum_range_is_zero_to_two_pow_newbits_minus_one(self):
        self.assertEqual(self.call("10.0.0.0/16", 8, 0), "10.0.0.0/24")
        self.assertEqual(self.call("10.0.0.0/16", 8, 255), "10.0.255.0/24")  # 2**8 - 1 は最後のサブネット
        self.assertEqual(self.call("10.0.0.0/24", 1, 1), "10.0.0.128/25")
        self.assertEqual(self.call("10.0.0.0/24", 0, 0), "10.0.0.0/24")      # newbits 0 の netnum は 0 だけ
        for netnum in (256, 257, -1):
            with self.subTest(netnum), self.assertRaises(V.EvalError):
                self.call("10.0.0.0/16", 8, netnum)
        for newbits, netnum in ((1, 2), (0, 1), (4, 16)):
            with self.subTest((newbits, netnum)), self.assertRaises(V.EvalError):
                self.call("10.0.0.0/16", newbits, netnum)

    def test_newbits_limit(self):
        self.assertEqual(self.call("10.0.0.0/24", 8, 255), "10.0.0.255/32")  # ちょうど /32
        for newbits in (9, -1):
            with self.subTest(newbits), self.assertRaises(V.EvalError):
                self.call("10.0.0.0/24", newbits, 0)


if __name__ == "__main__":
    unittest.main()
