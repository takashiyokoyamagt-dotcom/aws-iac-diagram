"""ノードの名前（B3）と id（K-NAME）、id の重なりの解決（normalize/names.py）。ir-schema の 2 章「ID の作り方（K-NAME）」。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.raw_builders import raw_ir, resource
from aws_iac_diagram.core import rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import names  # noqa: E402
from aws_iac_diagram.normalize.view import Index  # noqa: E402

RULES = rules_mod.default()


def one(fmt: str, r: dict):
    return Index(raw_ir(fmt, [r])).resources[0]


class KeyTest(unittest.TestCase):
    def test_key_of(self):
        self.assertEqual(names.key_of("demo-alb"), "demo-alb")
        self.assertEqual(names.key_of("Demo ALB"), "demo-alb")
        self.assertEqual(names.key_of("amazon.titan-embed-text-v2:0"), "amazon.titan-embed-text-v2-0")
        self.assertEqual(names.key_of("日本語の名前"), "-")  # 英数字以外は -。全部が記号なら "-"（呼ぶ側が次の候補に落とす）
        self.assertEqual(names.key_of("名前-a"), "a")
        self.assertEqual(names.key_of("_x"), "x")  # id の key は英数字で始める（ir.schema.json の形）
        self.assertEqual(names.key_of("ab_c.D"), "ab_c.d")


class LogicalNameTest(unittest.TestCase):
    def test_tf(self):
        cases = {
            "aws_vpc.main": "main",
            "aws_subnet.private[0]": "private-0",
            'aws_vpc_endpoint.interface["ssm"]': "interface-ssm",
            'aws_vpc_endpoint.interface["ecr.api"]': "interface-ecr.api",
            "aws_subnet.private[*]": "private",
            "module.vpc.aws_vpc.this[0]": "vpc.this-0",
            "module.db.module.db_instance.aws_db_instance.this[0]": "db.db_instance.this-0",
            'module.m["a"].aws_sqs_queue.q': "m-a.q",
            "data.aws_vpc.shared": "shared",
            "module.app.data.aws_vpc.x": "app.x",
            "module.eks.module.kms": "eks.kms",  # 黒箱のモジュールの呼び出し
        }
        for address, want in cases.items():
            with self.subTest(address):
                r = one("tf", resource(address, "module" if address.endswith("kms") else "aws_x"))
                self.assertEqual(names.logical_name(r), want)

    def test_cfn(self):
        for address, want in {"Vpc": "Vpc", "NetworkStack/Vpc": "NetworkStack.Vpc", "App::Net/Vpc": "App.Net.Vpc",
                              "Bucket*": "Bucket"}.items():
            with self.subTest(address):
                self.assertEqual(names.logical_name(one("cfn", resource(address, "AWS::S3::Bucket", fmt="cfn"))), want)


class ChooseNameTest(unittest.TestCase):
    def test_b3_order(self):
        row = RULES.row("s3_bucket")
        both = one("tf", resource("aws_s3_bucket.b", "aws_s3_bucket", {"bucket": "by-attr", "tags": {"Name": "by-tag"}}))
        self.assertEqual(names.choose_name(both, row), names.Name("by-tag", "tag"))
        attr = one("tf", resource("aws_s3_bucket.b", "aws_s3_bucket", {"bucket": "by-attr"}))
        self.assertEqual(names.choose_name(attr, row), names.Name("by-attr", "attr"))
        cfn = one("cfn", resource("Docs", "AWS::S3::Bucket", {"BucketName": "docs"}, fmt="cfn"))
        self.assertEqual(names.choose_name(cfn, row), names.Name("docs", "attr"))
        # TF の属性名を CFN に使わない（name_attr は形式ごと）
        wrong = one("cfn", resource("Docs", "AWS::S3::Bucket", {"bucket": "x"}, fmt="cfn"))
        self.assertEqual(names.choose_name(wrong, row), names.Name("Docs", "logical"))

    def test_unevaluated_values_fall_through(self):
        row = RULES.row("lambda_function")
        r = one("tf", resource("aws_lambda_function.f[0]", "aws_lambda_function",
                               {"function_name": {"$concat": [{"$res": "random_id.x", "attr": "hex"}, "-fn"]},
                                "tags": {"Name": {"$unknown": "x"}}}))
        self.assertEqual(names.choose_name(r, row), names.Name("f-0", "logical"))
        r = one("cfn", resource("Fn", "AWS::Lambda::Function", {"FunctionName": {"$concat": [{"$pseudo": "AWS::StackName"}, "-fn"]},
                                                                "Tags": [{"Key": "Name", "Value": "tagged"}]}, fmt="cfn"))
        self.assertEqual(names.choose_name(r, row), names.Name("tagged", "tag"))
        # 型に名前属性が無い（タグだけ）
        r = one("tf", resource("aws_vpc.main", "aws_vpc", {"name": "not-used"}))
        self.assertEqual(names.choose_name(r, RULES.row("vpc")), names.Name("main", "logical"))

    def test_awscc_uses_the_cfn_name_attribute(self):
        # awscc の型は同じ名前の CFN の型として扱う。名前属性も CFN の属性名（中立キー: BucketName → bucket_name）
        r = one("tf", resource("awscc_s3_bucket.b", "awscc_s3_bucket", {"bucket_name": "docs"}))
        self.assertEqual(names.choose_name(r, RULES.row("s3_bucket")), names.Name("docs", "attr"))
        r = one("tf", resource("awscc_lambda_function.f", "awscc_lambda_function", {"function_name": "fn"}))
        self.assertEqual(names.choose_name(r, RULES.row("lambda_function")), names.Name("fn", "attr"))

    def test_symbol_only_name_keeps_the_name_and_takes_the_key_from_the_next_candidate(self):
        r = one("tf", resource("aws_vpc.main", "aws_vpc", {"tags": {"Name": "本番"}}))
        nm = names.choose_name(r, RULES.row("vpc"))
        self.assertEqual((nm.name, nm.source, nm.key), ("本番", "tag", "main"))  # 名前・label は「本番」、key は論理名から
        ids, diags = names.assign_ids([(r, "vpc", nm)])
        self.assertEqual(ids, {"aws_vpc.main": "vpc/main"})
        self.assertEqual([d["code"] for d in diags], ["NORM-NAME-FALLBACK"])
        # 次の候補が名前属性なら、key はそこから（論理名に落ちたことにはしない）
        r = one("tf", resource("aws_s3_bucket.b", "aws_s3_bucket", {"bucket": "docs", "tags": {"Name": "文書"}}))
        nm = names.choose_name(r, RULES.row("s3_bucket"))
        self.assertEqual((nm.name, nm.key), ("文書", "docs"))
        self.assertEqual(names.assign_ids([(r, "s3_bucket", nm)])[1], [])

    def test_module_uses_the_call_name(self):
        r = one("tf", resource("module.eks.module.kms", "module", {"tags": {"Name": "x"}}, via="module_blackbox"))
        self.assertEqual(names.choose_name(r, RULES.row("module")), names.Name("eks.kms", "module"))


class AssignIdsTest(unittest.TestCase):
    def test_ids_and_fallback_diagnostics(self):
        a = one("tf", resource("aws_vpc.main", "aws_vpc"))
        b = one("tf", resource("aws_s3_bucket.b", "aws_s3_bucket", {"bucket": "Docs Bucket"}))
        ids, diags = names.assign_ids([(a, "vpc", names.Name("main", "logical")), (b, "s3_bucket", names.Name("Docs Bucket", "attr"))])
        self.assertEqual(ids, {"aws_vpc.main": "vpc/main", "aws_s3_bucket.b": "s3_bucket/docs-bucket"})
        self.assertEqual([(d["code"], d["level"], d["address"]) for d in diags], [("NORM-NAME-FALLBACK", "info", "aws_vpc.main")])

    def test_collision_is_resolved_in_address_order(self):
        rs = [one("tf", resource(a, "aws_s3_bucket")) for a in ("module.z.aws_s3_bucket.logs", "aws_s3_bucket.b", "aws_s3_bucket.a")]
        items = [(r, "s3_bucket", names.Name("Shared", "tag")) for r in rs]
        ids, diags = names.assign_ids(items)
        # address の辞書順に並べ、2 つ目以降に `.<論理名の key>`
        self.assertEqual(ids, {"aws_s3_bucket.a": "s3_bucket/shared", "aws_s3_bucket.b": "s3_bucket/shared.b",
                               "module.z.aws_s3_bucket.logs": "s3_bucket/shared.z.logs"})
        self.assertEqual([d["code"] for d in diags], ["NORM-KEY-COLLISION"] * 2)
        # 入力の順に依らない
        self.assertEqual(names.assign_ids(list(reversed(items)))[0], ids)
        # 同じ型でなければ重ならない
        ids, diags = names.assign_ids([(rs[0], "s3_bucket", names.Name("x", "tag")), (rs[1], "sqs_queue", names.Name("x", "tag"))])
        self.assertEqual(sorted(ids.values()), ["s3_bucket/x", "sqs_queue/x"])
        self.assertEqual(diags, [])

    def test_collision_with_the_same_logical_name(self):
        # data と resource で論理名まで同じ（`x`）。2 つ目は `.x`、それでも重なる 3 つ目は address 全体の key で分ける
        rs = [one("tf", resource(a, "aws_vpc")) for a in ("aws_vpc.a", "aws_vpc.x", "data.aws_vpc.x")]
        ids, _ = names.assign_ids([(r, "vpc", names.Name("n", "tag")) for r in rs])
        self.assertEqual(ids, {"aws_vpc.a": "vpc/n", "aws_vpc.x": "vpc/n.x", "data.aws_vpc.x": "vpc/n.data.aws_vpc.x"})
        self.assertEqual(len(set(ids.values())), 3)

if __name__ == "__main__":
    unittest.main()
