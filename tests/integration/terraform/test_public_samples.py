"""TF アダプタの公開サンプルでの確認（フェーズ2 の手順5）。道具は aws-iac-diagram-workspace/tools/tf_public_check.py。

- 公開サンプルの TF のルート 52 フォルダ（T01〜T20、P01〜P04）がすべて読め、raw IR の検査を通り、error の診断が 0。
  `.tf` のあるフォルダすべて（205）は、時間がかかる（直列で約 70 秒）ので CI の手順で流す（`tf_public_check.py --all`）。
- TF／SAM の対（T01、T05、T06、T07、T11）のリソースの型の多重集合の違いが、PAIR_EXPECTED（理由つき）と一致する。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.paths import PUBLIC, ROOT, WS
import tf_public_check as chk  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402


class PublicFoldersTest(unittest.TestCase):
    def test_roots_are_all_read_and_valid(self):
        # T01〜T20、P01〜P04 のルート。例外なし・raw IR の検査を通る・error の診断 0
        roots = chk.root_folders()
        self.assertEqual(len(roots), 52)
        self.assertEqual(len(set(roots)), 52)
        res = chk.run_folders(roots)
        self.assertEqual(res["failures"], [])
        self.assertEqual(res["folders"], 52)
        self.assertEqual(res["diagnostics"]["error"], 0)
        # 数の目安（アダプタを変えて大きく動いたら気づけるように。ぴったりの固定ではない）
        self.assertGreater(res["resources"], 2000)
        self.assertGreater(res["diagnostics"]["warn"], 0)
        # T06 は heredoc の終端の空白の前処理で読める（SELECTION.md の 4 の 1）
        t06 = tf_build.build_raw(PUBLIC / "serverless-patterns" / "eventbridge-sns-lambda-terraform", WS)
        self.assertIn("TF-HEREDOC-TRAILING-SPACE", [d["code"] for d in t06["diagnostics"]])
        policy = next(r for r in t06["resources"] if r["address"] == "aws_sns_topic_policy.default")
        self.assertIn("$json", policy["props"]["policy"])

    def test_folder_lists(self):
        roots, folders = chk.root_folders(), chk.all_folders()
        self.assertTrue(set(roots) <= set(folders))
        self.assertGreaterEqual(len(folders), 200)
        # すべてのフォルダを読む確認（--all）の対象に、モジュールの中身（要約表の元になったソース）も入っている
        self.assertIn("terraform-aws-vpc/modules/vpc-endpoints", folders)

    def test_a_failing_folder_is_reported(self):
        # 道具が失敗を見逃さないこと: 読めないフォルダ（.tf が無い）は例外として報告される
        r = chk.check_folder("serverless-patterns/does-not-exist")
        self.assertEqual(len(r["problems"]), 1)
        self.assertIn("exception", r["problems"][0])
        res = chk.run_folders(["serverless-patterns/does-not-exist"])
        self.assertEqual([f["folder"] for f in res["failures"]], ["serverless-patterns/does-not-exist"])

    def test_main_exit_codes(self):
        # 道具の終了コード: 全部通れば 0、読めないフォルダ・対の違いがあれば 1
        good = ["serverless-patterns/eventbridge-sqs-terraform"]
        with mock.patch.object(chk, "root_folders", return_value=good):
            self.assertEqual(chk.main([]), 0)
        with mock.patch.object(chk, "root_folders", return_value=["serverless-patterns/does-not-exist"]):
            self.assertEqual(chk.main([]), 1)
        pairs_ng = {"pairs": [], "problems": ["T99: example"]}
        with mock.patch.object(chk, "root_folders", return_value=good), \
                mock.patch.object(chk, "run_pairs", return_value=pairs_ng):
            self.assertEqual(chk.main([]), 1)

    def test_output_is_byte_identical_for_any_hash_seed(self):
        # C5（SELECTION.md の 3 の 4）: 同じ入力は、PYTHONHASHSEED が違っても同じバイト列になる（代表のフォルダ）
        tf_py = ROOT / "skills" / "aws-iac-diagram" / "scripts" / "adapt_tf.py"
        samples = ["serverless-patterns/eventbridge-sqs-terraform", "terraform-aws-vpc/examples/complete"]
        with tempfile.TemporaryDirectory() as tmp:
            for folder in samples:
                outs = []
                for seed in ("1", "777"):
                    out = Path(tmp) / f"{seed}.json"
                    env = dict(os.environ, PYTHONHASHSEED=seed)
                    r = subprocess.run([sys.executable, str(tf_py), "--input", str(PUBLIC / folder), "--out", str(out),
                                        "--root-base", str(PUBLIC)], capture_output=True, env=env)
                    self.assertEqual(r.returncode, 0, (folder, r.stderr[-300:]))
                    outs.append(out.read_bytes())
                self.assertEqual(outs[0], outs[1], folder)

    def test_a_sample_of_module_folders(self):
        # --all の一部（ローカルモジュールの中身・examples）。全部は CI の手順で流す
        res = chk.run_folders(["terraform-aws-vpc/modules/vpc-endpoints", "terraform-aws-vpc/examples/complete",
                               "terraform-aws-alb/modules/lb_trust_store", "terraform-aws-rds/modules/db_instance"])
        self.assertEqual(res["failures"], [])
        self.assertEqual(res["folders"], 4)


# 診断コードの一覧と ir-schema.md の照合（TF と CFN）は tests/test_diagnostics.py の DiagnosticCodesTest（R3 で移した）


# 対の比較で、正規化のあとに TF と SAM の両方にある型（件数つき）。違いだけでなく、一致した側も固定する
PAIR_COMMON = {
    "T01": {"AWS::Events::Rule": 1, "AWS::SQS::Queue": 1, "AWS::SQS::QueuePolicy": 1},
    "T05": {"AWS::Lambda::Function": 1, "AWS::SQS::Queue": 1},
    "T06": {"AWS::Events::Rule": 1, "AWS::Lambda::Function": 1, "AWS::SNS::Topic": 1, "AWS::SNS::TopicPolicy": 1},
    "T07": {"AWS::DynamoDB::Table": 1, "AWS::Lambda::Function": 1},
    "T11": {"AWS::ApiGateway::RestApi": 1, "AWS::DynamoDB::Table": 1, "AWS::IAM::Role": 1, "AWS::Logs::LogGroup": 2,
            "AWS::StepFunctions::StateMachine": 1},
}

# 対の診断（評価できなかった値。どれもファイルを読む関数か Fn::Transform で、アダプタの不具合ではない）
PAIR_CODES = {
    "T01": ([], []), "T05": ([], []),
    "T06": (["TF-HEREDOC-TRAILING-SPACE"], []),
    "T07": (["TF-UNEVALUATED"], []),  # filemd5()
    "T11": (["TF-UNEVALUATED"], ["CFN-UNEVALUATED"]),  # file()、Fn::Transform（OpenAPI の AWS::Include）
}


class PairTest(unittest.TestCase):
    def test_pairs_cover_the_required_ones(self):
        # SELECTION.md の 3 の 3 と HANDOFF の手順5: T06、T07、T11（と、煙試験の T01、T05）
        self.assertEqual(set(chk.PAIRS), {"T01", "T05", "T06", "T07", "T11"})
        self.assertEqual(set(chk.PAIR_EXPECTED), set(chk.PAIRS))
        self.assertEqual(set(PAIR_COMMON), set(chk.PAIRS))

    def test_pair_differences_match_the_expected_table(self):
        for pid in chk.PAIRS:
            with self.subTest(pid):
                r = chk.compare_pair(pid)
                self.assertEqual(chk.pair_problems(pid, r), [])
                self.assertEqual(r["common"], PAIR_COMMON[pid])
                # 型の多重集合は、共通 + 片方だけ で過不足なく説明される
                for side, total in (("only_tf", r["tf"]), ("only_cfn", r["cfn"])):
                    merged = dict(r["common"])
                    for t, n in r[side].items():
                        merged[t] = merged.get(t, 0) + n
                    self.assertEqual(dict(sorted(merged.items())), total)

    def test_pair_diagnostics_are_the_known_ones(self):
        from aws_iac_diagram.adapters.cloudformation import build as cfn_build
        for pid in chk.PAIRS:
            with self.subTest(pid):
                tf_raw = tf_build.build_raw(PUBLIC / chk.survey_public.SAMPLES[pid][1][0], WS)
                cfn_raw = cfn_build.build_raw(PUBLIC / chk.survey_public.SAMPLES[chk.PAIRS[pid]][1][0], WS)
                want_tf, want_cfn = PAIR_CODES[pid]
                self.assertEqual(sorted(d["code"] for d in tf_raw["diagnostics"]), want_tf)
                self.assertEqual(sorted(d["code"] for d in cfn_raw["diagnostics"]), want_cfn)
                self.assertFalse([d for d in tf_raw["diagnostics"] + cfn_raw["diagnostics"] if d["level"] == "error"])

    def test_every_expected_difference_has_a_reason(self):
        for pid, exp in chk.PAIR_EXPECTED.items():
            for side, items in exp.items():
                for t, (n, why) in items.items():
                    with self.subTest(pid=pid, side=side, type=t):
                        self.assertGreater(n, 0)
                        self.assertGreater(len(why), 5)

    def test_unexpected_difference_is_a_failure(self):
        # 表と合わなければ失敗する（ゆるい許容ではない）
        r = chk.compare_pair("T06")
        r["only_tf"] = dict(r["only_tf"])
        r["only_tf"]["AWS::SNS::Subscription"] = 2
        self.assertEqual(len(chk.pair_problems("T06", r)), 1)
        r["only_cfn"] = {"AWS::SQS::Queue": 1}
        self.assertEqual(len(chk.pair_problems("T06", r)), 2)

    def test_normalisation(self):
        def raw(*items):
            return {"resources": [{"address": a, "type": t, **({"enabled": e} if e is not None else {})}
                                  for a, t, e in items]}
        got = chk.tf_types(raw(
            ("aws_sqs_queue.a", "aws_sqs_queue", True),
            ("aws_sqs_queue.b", "aws_sqs_queue", True),
            ("aws_sqs_queue.off", "aws_sqs_queue", False),          # 作られないものは数えない
            ("data.aws_caller_identity.current", "aws_caller_identity", True),  # data は CFN に対応が無い
            ("random_string.r", "random_string", True),             # aws 以外のプロバイダ
            ("aws_cloudwatch_event_target.t", "aws_cloudwatch_event_target", True),
        ))
        self.assertEqual(dict(got), {"AWS::SQS::Queue": 2, "AWS::Events::Rule#Targets": 1})
        with self.assertRaises(KeyError):  # 表に無い型は黙って捨てない
            chk.tf_types(raw(("aws_new.x", "aws_new_thing", True)))
        got = chk.cfn_types(raw(("F", "AWS::Serverless::Function", True), ("Q", "AWS::SQS::Queue", True),
                                ("Off", "AWS::SQS::Queue", False)))
        self.assertEqual(dict(got), {"AWS::Lambda::Function": 1, "AWS::SQS::Queue": 1})


if __name__ == "__main__":
    unittest.main()
