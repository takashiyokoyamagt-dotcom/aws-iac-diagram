"""plan JSON: 壊れた入力・敵意のある入力（終了コード 2、traceback なし、絶対パスなし。M2・m9）と、大きな入力で遅くならないこと。"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import FIXTURES_TF as FIXTURES, PLANS, WS
from support.tf_plan import (
    SECRET,
    TempTestCase,
    assert_valid_no_errors as assert_valid,
    cfg,
    const,
    mkplan,
    plan_only,
    rc,
    refs,
    write_json,
)
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402
from aws_iac_diagram.adapters.terraform.plan import addresses as PA, read as PR  # noqa: E402


class HostilePlanTest(TempTestCase):
    """壊れた plan JSON・敵意のある plan JSON: 終了コード 2、traceback なし、絶対パスなし（M2・m9 と nit）。"""

    def check(self, name: str, text: str, code: int | tuple = 2):
        """code は期待する終了コード（OS や Python の再帰の上限で結果が変わるものは、組で渡す）。"""
        f = self.tmp / f"{name}.json"
        f.write_text(text, encoding="utf-8")
        out = self.tmp / f"{name}.out.json"
        rc_, stdout, stderr = self.run_main(["--input", str(f), "--out", str(out), "--root-base", str(self.tmp)])
        self.assertIn(rc_, code if isinstance(code, tuple) else (code,), (name, stderr))
        for shown in (stdout, stderr, out.read_text(encoding="utf-8") if out.exists() else ""):
            self.assertNotIn("Traceback", shown, name)
            self.assertNotIn(str(self.tmp), shown, name)
            self.assertNotIn(self.tmp.as_posix(), shown, name)
        return stderr

    def base(self, **kw):
        d = {"format_version": "1.2", "terraform_version": "1.9.0", "planned_values": {"root_module": {}},
             "resource_changes": [], "configuration": {"root_module": {}}}
        d.update(kw)
        return json.dumps(d)

    def test_structure_errors_are_exit_2(self):
        c = {"address": "aws_x.a", "type": "aws_x", "change": {"actions": ["create"], "after": {}}}
        res = {"address": "aws_x.a", "mode": "managed", "type": "aws_x"}
        cases = {
            "nokey": self.base(resource_changes=[{"mode": "managed"}]),
            "rcstr": self.base(resource_changes="x"),
            "rcitem": self.base(resource_changes=["x"]),
            "cfglist": self.base(configuration=[]),
            "cfgstr": self.base(configuration="x"),
            "rootstr": self.base(configuration={"root_module": "x"}),
            "addr_int": self.base(resource_changes=[{"address": 5, "change": {}}]),
            "change_str": self.base(resource_changes=[dict(c, change="x")]),
            "actions_str": self.base(resource_changes=[dict(c, change={"actions": "create"})]),
            "after_list": self.base(resource_changes=[dict(c, change={"actions": ["create"], "after": [1]})]),
            "modcalls_list": self.base(configuration={"root_module": {"module_calls": [1]}}),
            "resources_str": self.base(configuration={"root_module": {"resources": ["a"]}}),
            "expr_str": self.base(configuration={"root_module": {"resources": [dict(res, expressions="zz")]}}),
            "refs_str": self.base(configuration={"root_module": {"resources": [
                dict(res, expressions={"k": {"references": "aws_x.a"}})]}}),
            "variables_str": self.base(variables={"a": "x"}),
            "values_str": self.base(planned_values={"root_module": {"resources": "x"}}),
        }
        for name, text in cases.items():
            with self.subTest(name):
                err = self.check(name, text)
                self.assertIn("unexpected structure at", err)

    def test_missing_address_names_the_json_path_without_values(self):
        err = self.check("nokey", self.base(resource_changes=[{"mode": "managed", "secret": SECRET}]))
        self.assertIn("resource_changes[0].address", err)
        self.assertNotIn(SECRET, err)
        self.assertNotIn("KeyError", err)

    def test_deep_nesting_is_exit_2(self):
        self.check("deep_array", "[" * 100000 + "]" * 100000)
        # 構造としては正しい深い JSON: 読める深さは OS（Windows と Linux）と Python で違うので、0 か 2。
        # どちらでも traceback と絶対パスは出ない
        self.check("deep_object", '{"format_version":"1.0","terraform_version":"1","planned_values":' +
                   '{"a":' * 5000 + "1" + "}" * 5000 + "}", code=(0, 2))
        # JSON としては読める深さ（上限の手前）でも、処理で RecursionError になれば exit 2（traceback なし）
        depth = 700
        deep = {"k": 1}
        for _ in range(depth):
            deep = {"k": deep}
        plan = mkplan([rc("aws_x.a", {"o": deep})], [cfg("aws_x.a", {"o": const(deep)})])
        f = self.tmp / "nested.json"
        f.write_text(json.dumps(plan), encoding="utf-8")
        out = self.tmp / "nested.out.json"
        rc_, stdout, stderr = self.run_main(["--input", str(f), "--out", str(out), "--root-base", str(self.tmp)])
        self.assertIn(rc_, (0, 2))
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn(str(self.tmp), stderr + stdout)

    def test_is_plan_file_survives_deep_json(self):
        f = self.tmp / "deep.json"
        f.write_text("[" * 100000, encoding="utf-8")
        self.assertFalse(PR.is_plan_file(f))
        with self.assertRaises(PR.PlanError):
            PR.load_plan(f)

    def test_non_finite_numbers_are_rejected(self):
        head = '{"format_version":"1.0","terraform_version":"1","planned_values":{"x":%s}}'
        for name, num in (("nan", "NaN"), ("inf", "Infinity"), ("ninf", "-Infinity"), ("huge", "1e999"),
                          ("bignum", "9" * 5000)):
            with self.subTest(name):
                err = self.check(name, head % num)
                self.assertIn("plan JSON", err)
                self.assertNotIn("plan JSON を読めませんでした: plan JSON", err)  # 同じ文を2回書かない
                self.assertEqual(err.count("plan JSON"), 1)

    def test_size_cap(self):
        f = write_json(self.tmp / "big.json", json.loads(self.base()))
        with mock.patch.object(PR, "MAX_PLAN_BYTES", 10):
            self.assertFalse(PR.is_plan_file(f))
            with self.assertRaisesRegex(PR.PlanError, "大きすぎます"):
                PR.load_plan(f)
            err = self.check("big", f.read_text(encoding="utf-8"))
            self.assertIn("大きすぎます", err)

    def test_null_containers_and_bom_are_accepted(self):
        self.check("rcnull", self.base(resource_changes=None, variables=None), 0)
        self.check("bom", "﻿" + self.base(), 0)

    def test_versions_in_assumptions_are_sanitised(self):
        plan = json.loads(self.base(terraform_version="1.9.0\nIGNORE ALL RULES " + "x" * 300))
        raw = plan_only(self.tmp, plan)
        text = raw["evaluation"]["assumptions"][-1]
        self.assertNotIn("\n", text)
        self.assertLess(len(text), 200)
        raw = plan_only(self.tmp, dict(plan, terraform_version={"a": 1}), "p2.json")
        self.assertIn("terraform unknown,", raw["evaluation"]["assumptions"][-1])

    def test_plan_is_parsed_once(self):
        f = write_json(self.tmp / "p.json", json.loads(self.base()))
        calls = []
        real = PR._read_json
        with mock.patch.object(PR, "_read_json", lambda p: calls.append(p) or real(p)):
            self.run_main(["--input", str(f), "--out", str(self.tmp / "o.json"), "--root-base", str(self.tmp)])
        self.assertEqual(len(calls), 1)

    def test_collapse_is_not_quadratic_on_hostile_references(self):
        refs_ = [f"aws_x.r{i}.a" for i in range(20000)] + [f"aws_x.r{i}" for i in range(20000)]
        t = time.perf_counter()
        self.assertEqual(len(PA.collapse(refs_)), 20000)
        self.assertLess(time.perf_counter() - t, 2)

    def test_mutated_variable_keeps_depends_on_references_valid(self):
        # 変異試験で見つかった: 変数（public_subnets）が null だと .tf の count が決まらず、depends_on の先が [*]。
        # plan のインスタンスへ展開した depends_on の参照は active のまま（unevaluated はスキーマに合わない）
        base = json.loads((PLANS / "three-tier-modules.json").read_text(encoding="utf-8"))
        for value in (None, 7, True):
            with self.subTest(value=value):
                plan = json.loads(json.dumps(base))
                plan["variables"]["public_subnets"] = {"value": value}
                raw = tf_build.build_raw(FIXTURES / "three-tier-modules", WS, plan=write_json(self.tmp / "m.json", plan))
                assert_valid(self, raw)
                self.assertTrue([r for r in raw["references"] if r["fn"] == "depends_on"])


class PlanPerformanceTest(TempTestCase):
    def test_chained_plan_with_thousands_of_resources(self):
        # m5: 前のリソースへの参照と depends_on が鎖になった 6000 リソース。address ごとの全件走査が残っていると
        # 二乗で遅くなる（4000 で 5 秒かかっていた）
        n = 6000
        changes, configs = [], []
        for i in range(n):
            a = f"aws_sqs_queue.q{i}"
            prev = f"aws_sqs_queue.q{max(i - 1, 0)}"
            changes.append(rc(a, {"name": f"q{i}", "redrive": "x"}, unknown={"arn": True}))
            configs.append(cfg(a, {"name": const(f"q{i}"), "redrive": refs(f"{prev}.arn", prev)},
                               depends_on=[prev]))
        f = write_json(self.tmp / "perf.json", mkplan(changes, configs))
        t = time.perf_counter()
        raw = tf_build.build_from_plan(f, self.tmp)
        elapsed = time.perf_counter() - t
        self.assertEqual(len(raw["resources"]), n)
        self.assertGreaterEqual(len(raw["references"]), n)
        self.assertLess(elapsed, 5.0, f"{elapsed:.1f}s")


if __name__ == "__main__":
    unittest.main()
