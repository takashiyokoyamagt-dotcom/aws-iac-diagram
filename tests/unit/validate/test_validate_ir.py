"""validate_ir.py のテスト。正解 IR（aws-iac-diagram-workspace/expected）が通ることと、壊した IR を検出すること。"""

import copy
import json
import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.ir import load
from support.paths import EXPECTED
import validate_ir as v  # noqa: E402


def errors(ir):
    return v.schema_errors(ir) or v.semantic_errors(ir, v.defined_rules())


class ExpectedTest(unittest.TestCase):
    def test_all_expected_valid_and_canonical(self):
        files = sorted(EXPECTED.glob("*.ir.json"))
        self.assertEqual(len(files), 5)
        for p in files:
            with self.subTest(p.name):
                text = p.read_text(encoding="utf-8")
                ir = json.loads(text)
                self.assertEqual(errors(ir), [])
                self.assertEqual(text, v.canonical_dump(ir))
                self.assertNotIn(b"\r", p.read_bytes())

    def test_three_tier_and_modules_same_canonical(self):
        self.assertEqual(v.canonical_part(load("three-tier")), v.canonical_part(load("three-tier-modules")))

    def test_rules_defined(self):
        rules = v.defined_rules()
        for r in ("H-IAM", "R-SG", "E-MERGE", "N-AZ", "P-SPANS", "M-EIP-NAT"):
            self.assertIn(r, rules)


class BrokenTest(unittest.TestCase):
    def assertError(self, ir, fragment):
        errs = errors(ir)
        self.assertTrue(any(fragment in e for e in errs), errs)

    def test_missing_parent(self):
        ir = load()
        ir["nodes"][0]["parent"] = "vpc/nope"
        self.assertError(ir, "parent vpc/nope が無い")

    def test_spans_lca(self):
        ir = load()
        alb = next(n for n in ir["nodes"] if n["id"] == "alb/demo-alb")
        alb["parent"] = "availability_zone/demo.ap-northeast-1a"
        self.assertError(ir, "最も近い共通の祖先")

    def test_edge_id_and_endpoint(self):
        ir = load()
        ir["edges"][0]["to"] = "alb/other"
        self.assertError(ir, "id が from->to と違う")

    def test_unknown_rule(self):
        ir = load()
        r = next(r for r in ir["sources"]["tf"]["resources"] if r["class"] == "hidden")
        r["rule"] = "H-NOT-DEFINED"
        self.assertError(ir, "規則 H-NOT-DEFINED")

    def test_node_not_drawn(self):
        ir = load()
        ir["sources"]["cfn"]["resources"] = [r for r in ir["sources"]["cfn"]["resources"] if r["address"] != "Alb"]
        self.assertError(ir, "ノード alb/demo-alb を drawn にしたリソースが無い")

    def test_missing_edge_evidence(self):
        ir = load()
        ir["sources"]["tf"]["edges"] = ir["sources"]["tf"]["edges"][1:]
        self.assertError(ir, "の根拠が無い")

    def test_schema_class_requirements(self):
        ir = load()
        r = next(r for r in ir["sources"]["tf"]["resources"] if r["class"] == "merged_into")
        del r["into"]
        self.assertTrue(v.schema_errors(ir))

    def test_duplicate_pair(self):
        ir = load()
        ir["edges"].append(copy.deepcopy(ir["edges"][0]))
        self.assertError(ir, "id が重複")

    def test_class_rule_prefix(self):
        ir = load()
        r = next(r for r in ir["sources"]["tf"]["resources"] if r["address"] == "aws_iam_role.task_execution")
        r["rule"] = "M-ECS-CLUSTER"
        self.assertError(ir, "class hidden の規則は H-*")

    def test_m_rule_into_must_be_node(self):
        ir = load()
        r = next(r for r in ir["sources"]["tf"]["resources"] if r["address"] == "aws_ecs_cluster.main")
        r["into"] = ["alb/demo-alb->ecs_service/demo-app"]
        self.assertError(ir, "M-* の into はノード")

    def test_r_rule_into_must_be_edge(self):
        ir = load()
        r = next(r for r in ir["sources"]["tf"]["resources"] if r["address"] == "aws_lb_target_group.app")
        r["into"] = ["ecs_service/demo-app"]
        self.assertError(ir, "R-* の into は辺")

    def test_r_rule_in_edge_evidence(self):
        ir = load()
        x = next(x for x in ir["sources"]["cfn"]["edges"] if x["edge"] == "alb/demo-alb->ecs_service/demo-app")
        x["rules"].remove("R-LB-TG")
        self.assertError(ir, "の根拠の rules に R-LB-TG が無い")

    def test_drawn_type_must_match_catalog(self):
        ir = load()
        r = next(r for r in ir["sources"]["tf"]["resources"] if r["address"] == "aws_lb.app")
        r["node"] = "ecs_service/demo-app"
        self.assertError(ir, "から描けるのは ['alb']")

    def test_drawn_unknown_input_type(self):
        ir = load()
        r = next(r for r in ir["sources"]["tf"]["resources"] if r["address"] == "aws_lb.app")
        r["type"] = "aws_imaginary_thing"
        self.assertError(ir, "「描く型」に無い")

    def test_key_from_name(self):
        ir = load()
        n = next(n for n in ir["nodes"] if n["id"] == "alb/demo-alb")
        n["name"] = "demo-alb-v2"
        self.assertError(ir, "K-NAME")
        n["name"] = "demo-alb"
        n["label"] = "デモ用 ALB"  # 表示名だけを変えても id は壊れない
        self.assertEqual(errors(ir), [])

    def test_key_from_name_follows_k_name(self):
        # ir-schema の 2 章の K-NAME（公開サンプルの T20・T13・P02 で見つかった）: 先頭の英数字でない文字は除く。英数字の無い名前の
        # key は、NORM-NAME-FALLBACK があれば論理名から作る（無ければ名前属性からで、値が IR に無いので key は確かめない）。
        # `.<論理名の key>`（論理名まで重なれば `.<address の key>`）は、その address に NORM-KEY-COLLISION があるときだけ
        tf = [("tf", 'module.vpc.aws_subnet.private[1]')]
        rec = [("tf", 'module.endpoint_record["s3"].aws_route53_record.this')]
        none: dict = {}
        coll = {tf[0][1]: {"NORM-KEY-COLLISION"}}
        cases = (
            ("###APP###-bucket", "app----bucket", tf, none, True),
            ("ex-.", "ex-.", tf, none, True),
            ("ex-.", "ex-..vpc.private-1", tf, coll, True),
            ("ex-.", "ex-..vpc.private-1", tf, none, False),        # 診断の無い `.<…>` は誤り
            ("ex-.", "ex-..vpc.private-2", tf, coll, False),        # 論理名の key と違う
            ("ex-.", "ex-.." + v.slug(tf[0][1]), tf, coll, True),  # 論理名まで重なったときの address の key
            ("*", "endpoint_record-s3.this", rec, {rec[0][1]: {"NORM-NAME-FALLBACK"}}, True),
            ("*", "something-else", rec, {rec[0][1]: {"NORM-NAME-FALLBACK"}}, False),
            ("*", "from-the-name-attr", rec, none, True),          # 名前属性から作った key は確かめられない
            ("demo", "demo-alb", tf, none, False),
            ("_x", "_x", tf, none, False),
        )
        for name, key, addrs, codes, ok in cases:
            with self.subTest(name=name, key=key, codes=codes):
                self.assertEqual(v.key_matches(key, name, addrs, codes), ok)
        self.assertEqual(v.slug("###APP_NAME###-vpc"), "app_name----vpc")
        self.assertEqual(v.slug("本番"), "")
        # IR の中で: 重なりを解いた id は NORM-KEY-COLLISION があれば通り、無ければ K-NAME の誤り
        ir = load()
        n = next(n for n in ir["nodes"] if n["id"] == "alb/demo-alb")
        n["id"] = "alb/demo-alb.app"
        for e in ir["edges"]:
            for end in ("from", "to"):
                if e[end] == "alb/demo-alb":
                    e[end] = n["id"]
            e["id"] = f"{e['from']}->{e['to']}"
        for src in ir["sources"].values():
            for r in src["resources"]:
                if r.get("node") == "alb/demo-alb":
                    r["node"] = n["id"]
                r["into"] = [x.replace("alb/demo-alb", n["id"]) for x in r["into"]] if "into" in r else r.get("into")
                if r.get("into") is None:
                    r.pop("into", None)
            for x in src["edges"]:
                x["edge"] = x["edge"].replace("alb/demo-alb", n["id"])
        self.assertTrue(any("K-NAME" in e for e in errors(ir)))
        ir["diagnostics"] = [{"level": "info", "code": "NORM-KEY-COLLISION", "address": "aws_lb.app", "message": "m"}]
        self.assertFalse([e for e in errors(ir) if "K-NAME" in e], errors(ir))

    def test_subnet_without_az_needs_the_diagnostic(self):
        # AZ が決まらない（NORM-AZ-UNKNOWN）サブネットは VPC の下、VPC が決まらない（NORM-PLACEMENT）ものは最上位
        # （ir-schema の 8 章・10 章。公開サンプルの T02・T18・T20・P02）。ほかの組合せと、診断の無いものは誤り
        def diag(code):
            return {"level": "info", "code": code, "address": "aws_subnet.database[0]", "message": "m"}
        for parent, codes, ok in (("vpc/demo", [], False), ("vpc/demo", ["NORM-AZ-UNKNOWN"], True),
                                  ("vpc/demo", ["NORM-PLACEMENT"], False), (None, ["NORM-AZ-UNKNOWN"], False),
                                  (None, ["NORM-PLACEMENT"], True)):
            with self.subTest(parent=parent, codes=codes):
                ir = load()
                n = next(n for n in ir["nodes"] if n["id"] == "subnet/demo-db-ap-northeast-1a")
                n["parent"] = parent
                ir["diagnostics"] = [diag(c) for c in codes]
                errs = [e for e in errors(ir) if "subnet の parent" in e]
                self.assertEqual(errs == [], ok, errs)

    def test_awscc_type_is_drawn_as_the_cfn_type(self):
        # TF の awscc の型は同じ名前の CFN の型として描く（ir-schema の 2 章。T15 の awscc_s3_bucket など）
        ir = load()
        r = next(r for r in ir["sources"]["tf"]["resources"] if r.get("node") == "vpc/demo")
        r["type"] = "awscc_ec2_vpc"
        self.assertEqual(errors(ir), [])
        r["type"] = "awscc_ec2_imaginary"
        self.assertError(ir, "「描く型」に無い")

    def test_format_detects_unsorted(self):
        ir = load()
        ir["nodes"].reverse()
        self.assertNotEqual(json.dumps(ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n", v.canonical_dump(ir))


class SelfLoopTest(unittest.TestCase):
    """自己ループの辺は検査で落ちる（validate_ir.semantic_errors。R5 のレビューの指摘: この検査を外しても落ちるテストが無かった）。"""

    def test_self_referencing_edge_is_rejected(self):
        ir = load()
        self.assertEqual(errors(ir), [])
        edge = ir["edges"][0]
        edge["to"] = edge["from"]
        edge["id"] = f"{edge['from']}->{edge['to']}"  # id は from->to と合わせる（id の誤りでなく、自己ループだけを見る）
        errs = errors(ir)
        self.assertTrue(any(e == f"edge {edge['id']}: 自己ループ" for e in errs), errs)
        self.assertFalse(any("id が from->to と違う" in e for e in errs), errs)


class RulesFromDataTest(unittest.TestCase):
    """validate_ir.py は規則表（data/rules/）を core/rules.py から読む（草案の Markdown の表は読まない。フェーズ 3 の手順 1）。"""

    def test_sets_come_from_core_rules(self):
        from aws_iac_diagram.core import rules as rule_data
        r = rule_data.default()
        self.assertEqual(v.defined_rules(), set(r.rule_ids))
        self.assertEqual(v.drawable_types(), {k: set(x) for k, x in r.drawable_types().items()})
        self.assertIsInstance(v.defined_rules(), set)
        self.assertEqual(v.CLASS_PREFIX, rule_data.CLASS_PREFIX)
        for name in ("RULE_DOCS", "RULE_ROW", "CATALOG", "INPUT_TYPE", "SYNTHETIC_TYPES"):
            self.assertFalse(hasattr(v, name), name)  # 旧い読み方（正規表現で表を読む）は残していない

    def test_synthetic_node_types_come_from_the_data(self):
        ir = load()
        ir["nodes"][0]["synthetic"] = True  # 合成でない型を合成にする
        self.assertTrue(any("synthetic の値が規則と違う" in e for e in errors(ir)))
        ir = load()
        ext = next(n for n in ir["nodes"] if n["type"] == "external")
        ext["synthetic"] = False  # 合成の型（データの synthetic を持つ型）を合成でなくす
        self.assertTrue(any("synthetic の値が規則と違う" in e for e in errors(ir)))

    def test_messages_name_the_new_location(self):
        ir = load()
        r = next(r for r in ir["sources"]["tf"]["resources"] if r["class"] == "hidden")
        r["rule"] = "H-NOT-DEFINED"
        ir["sources"]["tf"]["edges"][0]["rules"] = ir["sources"]["tf"]["edges"][0]["rules"] + ["R-NOT-DEFINED"]
        errs = errors(ir)
        self.assertTrue(any(e.endswith("規則 H-NOT-DEFINED が規則表（data/rules/）に無い") for e in errs), errs)
        self.assertTrue(any("規則 R-NOT-DEFINED が規則表（data/rules/）に無い" in e for e in errs), errs)
        ir = load()
        d = next(r for r in ir["sources"]["tf"]["resources"] if r["class"] == "drawn")
        d["type"] = "aws_not_drawable"
        errs = errors(ir)
        self.assertTrue(any(e.endswith("入力の型 aws_not_drawable が規則表（data/rules/types/）の「描く型」に無い") for e in errs), errs)
        self.assertFalse(any("references/" in e or "resource-catalog" in e for e in errs), errs)


if __name__ == "__main__":
    unittest.main()
