"""出力の固定（フェーズ 2b の R1。PLAN の 1.4 の 6）のテスト。道具は aws-iac-diagram-workspace/tools/golden.py。

- 固定した manifest（tests/golden/manifest.json）と、アダプタの CLI の今の出力（raw IR）が、全ケースでバイト単位で一致する。
  ケースは、自作 fixture（TF／CFN）、コミットした plan JSON（plan だけ、.tf と合わせたもの）、公開サンプルの TF のルート 52、
  c1_check の CFN の入力。
- 道具が失敗を見逃さないこと（hash の不一致、欠け、余り、絶対パスの混入、`--update` の歯止め）。

このテストが落ちたら、構成の移動・分割が出力を変えたということ。`golden.py --update` で通さずに、コードを直す。
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.tools import load_tool  # noqa: E402

golden = load_tool("golden", alias="golden_tool")  # tests/golden/ のパッケージ名と衝突するので、別名で読む


class GoldenOutputsTest(unittest.TestCase):
    def test_all_outputs_are_byte_identical_to_the_manifest(self):
        problems = golden.check()
        self.assertEqual(problems, [], "固定した raw IR と違う（--update で通さず、コードを直す）:\n" + "\n".join(problems))

    def test_manifest_shape(self):
        m = golden.load_manifest()
        self.assertEqual(m["version"], golden.MANIFEST_VERSION)
        names = list(m["cases"])
        self.assertEqual(names, sorted(names))
        # 固定する範囲（PLAN の 1.4 の 6）: 自作 TF 5、plan JSON 7（plan だけと合わせたもの）、公開サンプルの TF のルート 52、CFN 25
        self.assertEqual(len([n for n in names if n.startswith("tf/plan-only/")]), 7)
        self.assertEqual(len([n for n in names if n.startswith("tf/combined/")]), 7)
        self.assertEqual(len([n for n in names if n.startswith("tf/public/")]), 52)
        self.assertGreaterEqual(len([n for n in names if n.startswith("tf/custom/")]), 5)
        # CFN は c1_check の入力 25（自作 5＋公開サンプル 20）。自作に --param／--param-file を渡した 2 つが別にある
        self.assertEqual(len([n for n in names if n.startswith("cfn/public/")]), 20)
        self.assertEqual(len([n for n in names if n.startswith("cfn/custom/") and "." not in n]), 5)
        for n, e in m["cases"].items():
            self.assertRegex(e["sha256"], r"^[0-9a-f]{64}$", n)
            self.assertIn("--root-base", e["args"], n)
            # 引数に絶対パスは入れない（どこに clone しても同じ出力にするため）
            for arg in e["args"]:
                self.assertFalse(Path(arg).is_absolute(), f"{n}: {arg}")

    def test_manifest_file_is_canonical(self):
        # sorted keys・LF・末尾の改行。golden.py --update が書く形そのもの
        text = golden.MANIFEST.read_bytes().decode("utf-8")
        self.assertNotIn("\r", text)
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(text, json.dumps(json.loads(text), ensure_ascii=False, indent=1, sort_keys=True) + "\n")


class GoldenToolTest(unittest.TestCase):
    """道具が不一致を見逃さないこと（空振りのテストにしない）。"""

    @classmethod
    def setUpClass(cls):
        cls.cases = {n: c for n, c in golden.enumerate_cases().items()
                     if n in ("tf/custom/vpc-endpoints", "cfn/custom/vpc-endpoints")}
        cls.results = golden.run_all(cls.cases, 2)
        cls.manifest = golden.load_manifest()

    def test_baseline_has_no_problems(self):
        self.assertEqual(len(self.cases), 2)
        self.assertEqual(golden.compare(self.cases, self.results, self.manifest, partial=True), [])

    def test_changed_hash_is_reported(self):
        m = copy.deepcopy(self.manifest)
        m["cases"]["tf/custom/vpc-endpoints"]["sha256"] = "0" * 64
        problems = golden.compare(self.cases, self.results, m, partial=True)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("CHANGED  tf/custom/vpc-endpoints"), problems)

    def test_missing_and_new_cases_are_reported(self):
        m = copy.deepcopy(self.manifest)
        del m["cases"]["cfn/custom/vpc-endpoints"]
        m["cases"]["tf/custom/gone"] = m["cases"]["tf/custom/vpc-endpoints"]
        problems = golden.compare(self.cases, self.results, m, partial=False)
        self.assertTrue(any(p.startswith("NEW      cfn/custom/vpc-endpoints") for p in problems), problems)
        self.assertTrue(any(p.startswith("MISSING  tf/custom/gone") for p in problems), problems)
        # 一部のケースだけ動かしたとき（--only）は、manifest の余りを咎めない
        self.assertFalse(any(p.startswith("MISSING") for p in golden.compare(self.cases, self.results, m, partial=True)))

    def test_failed_run_and_changed_args_are_reported(self):
        bad = {"tf/custom/vpc-endpoints": {"adapter": "tf", "args": ["--input", "no/such/dir", "--root-base", "x"]}}
        r = golden.run_all(bad, 1)
        self.assertNotEqual(r["tf/custom/vpc-endpoints"]["code"], 0)
        problems = golden.compare(bad, r, self.manifest, partial=True)
        self.assertTrue(problems and problems[0].startswith("FAILED"), problems)
        other = {"tf/custom/vpc-endpoints": dict(self.cases["tf/custom/vpc-endpoints"], args=["--root-base", "x"])}
        res = {"tf/custom/vpc-endpoints": dict(self.results["tf/custom/vpc-endpoints"])}
        self.assertTrue(any(p.startswith("ARGS") for p in golden.compare(other, res, self.manifest, partial=True)))

    def test_absolute_paths_are_detected(self):
        self.assertEqual(golden.absolute_path_hits('{"root": "fixtures/tf/a"}'), [])
        self.assertTrue(golden.absolute_path_hits(json.dumps({"root": str(golden.ROOT / "x")})))
        self.assertTrue(golden.absolute_path_hits(json.dumps({"root": golden.ROOT.as_posix() + "/x"})))
        self.assertTrue(golden.absolute_path_hits("see /tmp/golden-abc/1.json", ("/tmp/golden-abc",)))
        for name, r in self.results.items():
            self.assertEqual(r["abs_paths"], [], name)

    def test_dump_writes_the_current_output(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "x" / "dump.json"
            code = golden.main(["--dump", "tf/custom/vpc-endpoints", "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(out.read_bytes(), self.results["tf/custom/vpc-endpoints"]["bytes"])
            self.assertEqual(golden.main(["--dump", "no/such/case", "--out", str(out)]), 2)
            self.assertEqual(golden.main(["--dump", "tf/custom/rag"]), 2)

    def test_only_without_a_matching_case_fails(self):
        # 打ち間違いの --only が「0 件で OK」にならない
        problems = golden.check(only="tf/custom/no-such-prefix")
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith("NOMATCH"), problems)
        self.assertEqual(golden.main(["--only", "tf/custom/no-such-prefix"]), 1)

    def test_update_refuses_to_remove_cases_without_accept(self):
        with tempfile.TemporaryDirectory() as t:
            manifest = Path(t) / "manifest.json"
            both = self.cases
            one = {"tf/custom/vpc-endpoints": self.cases["tf/custom/vpc-endpoints"]}
            with mock.patch.object(golden, "MANIFEST", manifest):
                with mock.patch.object(golden, "enumerate_cases", return_value=both):
                    self.assertEqual(golden.main(["--update"]), 0)
                with mock.patch.object(golden, "enumerate_cases", return_value=one):
                    self.assertEqual(golden.main(["--update"]), 1)  # ケースが減る
                    self.assertEqual(sorted(json.loads(manifest.read_text(encoding="utf-8"))["cases"]), sorted(both))
                    self.assertEqual(golden.main(["--update", "--accept-changes"]), 0)
                    self.assertEqual(sorted(json.loads(manifest.read_text(encoding="utf-8"))["cases"]), sorted(one))

    def test_update_refuses_to_change_existing_hashes_without_accept(self):
        # --update をリファクタの「修正」に使えない歯止め。manifest は一時ファイルに向ける
        with tempfile.TemporaryDirectory() as t:
            manifest = Path(t) / "manifest.json"
            with mock.patch.object(golden, "MANIFEST", manifest), \
                 mock.patch.object(golden, "enumerate_cases", return_value=self.cases):
                self.assertEqual(golden.main(["--update"]), 0)
                doc = json.loads(manifest.read_text(encoding="utf-8"))
                self.assertEqual(sorted(doc["cases"]), sorted(self.cases))
                doc["cases"]["tf/custom/vpc-endpoints"]["sha256"] = "f" * 64
                manifest.write_text(json.dumps(doc), encoding="utf-8")
                self.assertEqual(golden.main(["--update"]), 1)  # 認めない
                self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["cases"]["tf/custom/vpc-endpoints"]["sha256"],
                                 "f" * 64)
                self.assertEqual(golden.main(["--update", "--accept-changes"]), 0)
                self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["cases"]["tf/custom/vpc-endpoints"]["sha256"],
                                 self.results["tf/custom/vpc-endpoints"]["sha256"])


class GoldenAbsolutePathTest(unittest.TestCase):
    """hash が一致していても、出力に絶対パスが入っていれば compare が失敗にする（R5 のレビューの指摘）。

    GoldenToolTest.test_absolute_paths_are_detected は検出関数 absolute_path_hits だけを見ていて、compare が
    その結果（abs_paths）を使っていることは確かめていなかった。ここは、実行せずに作った結果で compare を直接呼ぶ。
    """

    SHA = "ab" * 32

    def compare(self, abs_paths: list):
        cases = {"tf/custom/x": {"adapter": "tf", "args": ["--input", "a", "--root-base", "b"]}}
        manifest = {"cases": {"tf/custom/x": {"adapter": "tf", "args": ["--input", "a", "--root-base", "b"],
                                              "sha256": self.SHA, "bytes": 3, "resources": 1, "references": 0,
                                              "diagnostics": 0}}}
        results = {"tf/custom/x": {"code": 0, "stderr": "", "sha256": self.SHA, "bytes": b"{}",
                                   "summary": {"resources": 1, "references": 0, "diagnostics": 0},
                                   "abs_paths": abs_paths}}
        return golden.compare(cases, results, manifest, partial=False)

    def test_matching_hash_with_an_absolute_path_fails(self):
        self.assertEqual(self.compare([]), [])  # 前提: 絶対パスが無く hash が一致すれば問題なし
        for path in (str(golden.ROOT), str(Path.home()), tempfile.gettempdir()):
            with self.subTest(path):
                problems = self.compare([path])
                self.assertEqual(len(problems), 1, problems)
                self.assertTrue(problems[0].startswith("ABSPATH  tf/custom/x"), problems)


if __name__ == "__main__":
    unittest.main()
