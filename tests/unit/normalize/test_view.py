"""正規化の段階 0（normalize/view.py）: 中立キーで属性を引く、印の扱い、タグ、参照の索引。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.raw_builders import raw_ir, reference, resource
from aws_iac_diagram.normalize import view  # noqa: E402


class MarksTest(unittest.TestCase):
    def test_marks_and_plain_values(self):
        for m in ({"$res": "a", "attr": None}, {"$unknown": "x"}, {"$concat": ["a", {"$pseudo": "AWS::Region"}]},
                  {"$json": {}}, {"$az": 0}, {"$import": "x"}, {"$pseudo": "AWS::Region"}):
            self.assertTrue(view.is_mark(m), m)
            self.assertIsNone(view.plain(m))
        # 入力にもともとあった `$` のキー（raw では `$$`）は印ではない
        self.assertFalse(view.is_mark({"$$schema": "x"}))
        self.assertEqual(view.plain({"$$schema": "x"}), {"$$schema": "x"})
        self.assertEqual(view.plain("a"), "a")
        self.assertEqual(view.plain_str("a"), "a")
        self.assertIsNone(view.plain_str("  "))
        self.assertIsNone(view.plain_str(3))

    def test_get_uses_the_neutral_key_and_drops_unknown(self):
        props = {"cidr_block": "10.0.0.0/16", "VpcId": {"$res": "v", "attr": None}, "Name": {"$unknown": "x"}}
        self.assertEqual(view.get(props, "CidrBlock"), "10.0.0.0/16")
        self.assertEqual(view.get(props, "cidr_block"), "10.0.0.0/16")
        self.assertEqual(view.get(props, "vpc_id"), {"$res": "v", "attr": None})
        self.assertIsNone(view.get(props, "name"))  # $unknown は「その属性を持たない」
        self.assertIsNone(view.get(props, "nothing"))
        self.assertIsNone(view.get("not a dict", "x"))
        # 綴りが完全に一致するものを先に使う
        self.assertEqual(view.get({"Type": "a", "type": "b"}, "type"), "b")

    def test_strings_in_walks_json_but_not_concat(self):
        v = {"policy": {"$json": {"Rules": [{"Resource": ["collection/a"]}]}}, "x": {"$concat": ["arn:", {"$res": "r", "attr": None}]},
             "n": 1, "s": "plain"}
        self.assertEqual(list(view.strings_in(v)), ["collection/a", "plain"])


class TagsTest(unittest.TestCase):
    def test_tf_map(self):
        self.assertEqual(view.name_tag({"tags": {"Name": "demo", "Project": "x"}}), "demo")

    def test_cfn_key_value_list(self):
        props = {"Tags": [{"Key": "Project", "Value": "x"}, {"Key": "Name", "Value": "demo"}]}
        self.assertEqual(view.tags(props), {"Project": "x", "Name": "demo"})
        self.assertEqual(view.name_tag(props), "demo")

    def test_cfn_map_form(self):
        self.assertEqual(view.name_tag({"Tags": {"Name": "fn"}}), "fn")  # SAM の Tags は map

    def test_marks_are_not_names(self):
        self.assertIsNone(view.name_tag({"tags": {"Name": {"$concat": [{"$res": "x", "attr": "id"}, "-a"]}}}))
        self.assertIsNone(view.name_tag({"Tags": [{"Key": "Name", "Value": {"$unknown": "x"}}]}))
        self.assertIsNone(view.name_tag({"tags": {"$unknown": "x"}}))
        self.assertIsNone(view.name_tag({"Tags": [{"Key": {"$res": "k", "attr": None}, "Value": "v"}]}))
        self.assertIsNone(view.name_tag({}))
        self.assertEqual(view.tags({"tags": {"$$odd": "v"}}), {"$odd": "v"})


class IndexTest(unittest.TestCase):
    def test_resources_and_references(self):
        raw = raw_ir("tf", [
            resource("aws_vpc.main", "aws_vpc"),
            resource("aws_subnet.a", "aws_subnet"),
            resource("data.aws_ami.x", "aws_ami"),
            resource("module.m.data.aws_vpc.x", "aws_vpc", module="module.m"),
            resource("module.m.aws_vpc.data", "aws_vpc", module="module.m"),
        ], [
            reference("aws_subnet.a", "vpc_id", "aws_vpc.main", "id"),
            reference("aws_subnet.a", "depends_on", "aws_vpc.main", fn="depends_on"),
            reference("aws_subnet.a", "cidr_block", "aws_vpc.main", "cidr_block", state="pruned"),
        ])
        idx = view.Index(raw)
        self.assertEqual(idx.fmt, "tf")
        self.assertEqual([r.address for r in idx.resources][:2], ["aws_vpc.main", "aws_subnet.a"])
        self.assertEqual([r.is_data for r in idx.resources], [False, False, True, True, False])
        self.assertEqual(len(idx.refs_from["aws_subnet.a"]), 2)  # active の参照だけ（pruned は入れない）
        self.assertEqual(idx.neighbors("aws_vpc.main"), ["aws_subnet.a"])
        self.assertEqual(idx.neighbors("aws_subnet.a"), ["aws_vpc.main"])
        self.assertEqual(idx.neighbors("aws_subnet.a", depends_on=True), ["aws_vpc.main"])
        self.assertEqual(idx.referrers("aws_vpc.main"), ["aws_subnet.a"])
        self.assertEqual(idx.referrers("aws_subnet.a"), [])

    def test_is_data_is_decided_from_the_address(self):
        # raw の module フィールドに頼らない（無くても、食い違っていても、address で決める）
        cases = {"data.aws_vpc.x": True, "module.m.data.aws_vpc.x": True, 'module.m["a.b"].data.aws_vpc.x': True,
                 "module.a.module.b[0].data.aws_ami.x": True, "aws_vpc.data": False, "module.data.aws_vpc.x": False,
                 "module.m.aws_vpc.data": False, "module.data": False}
        for address, want in cases.items():
            with self.subTest(address):
                r = view.Index(raw_ir("tf", [resource(address, "aws_vpc", module="module.wrong")])).resources[0]
                self.assertEqual(r.is_data, want)
        self.assertEqual(view.split_tf_address('module.m["a.b"].aws_x.y[0]'), ["module", 'm["a.b"]', "aws_x", "y[0]"])

    def test_cfn_depends_on_and_data(self):
        raw = raw_ir("cfn", [resource("A", "AWS::S3::Bucket", fmt="cfn"), resource("data.B", "AWS::S3::Bucket", fmt="cfn")],
                     [reference("A", "DependsOn", "data.B", fn="DependsOn")])
        idx = view.Index(raw)
        self.assertFalse(any(r.is_data for r in idx.resources))  # CFN に data は無い
        self.assertEqual(idx.neighbors("A"), [])
        self.assertEqual(idx.neighbors("A", depends_on=True), ["data.B"])
        self.assertTrue(view.is_depends_on({"fn": "DependsOn", "path": "DependsOn"}))
        self.assertFalse(view.is_depends_on({"fn": "Ref", "path": "Properties.X"}))


if __name__ == "__main__":
    unittest.main()
