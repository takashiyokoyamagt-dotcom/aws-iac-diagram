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

    def test_format_detects_unsorted(self):
        ir = load()
        ir["nodes"].reverse()
        self.assertNotEqual(json.dumps(ir, ensure_ascii=False, indent=2, sort_keys=True) + "\n", v.canonical_dump(ir))


if __name__ == "__main__":
    unittest.main()
