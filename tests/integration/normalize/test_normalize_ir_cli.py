"""正規化の入口 scripts/normalize_ir.py を別プロセスとして動かすテスト（終了コード、出力のファイル、日本語とスペースを含むパス）。"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.custom_inputs import custom_raw
from support.paths import SCRIPTS
from support.raw_builders import raw_ir, reference, resource
from aws_iac_diagram.core import ir_norm  # noqa: E402
from aws_iac_diagram.normalize import build  # noqa: E402

ENTRY = SCRIPTS / "normalize_ir.py"


def call(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ENTRY), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300, check=False)


class NormalizeIrCliTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "日本語 パス" / "出力 先"
        self.dir.mkdir(parents=True)

    def write(self, name: str, doc) -> Path:
        p = self.dir / name
        p.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return p

    def test_provisional_relations_exit_1_but_the_file_is_written(self):
        raw = custom_raw("three-tier", "tf")
        src = self.write("three-tier.raw.json", raw)
        out = self.dir / "three-tier.ir.json"
        res = call("--input", str(src), "--out", str(out), "--name", "three-tier")
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("仮のままの分類が 4 件", res.stderr)  # R-SG（SG のハンドラは手順 5）
        self.assertIn("provisional=4", res.stdout)
        # 書いたものは、同じ入力をパッケージで正規化した正規の文字列と同じ
        self.assertEqual(out.read_text(encoding="utf-8"), ir_norm.canonical_dump(build.normalize(raw, None, "three-tier")))
        # 仮の分類を許すオプションは無い（スキーマに通らない IR を 0 で返さない）
        res = call("--input", str(src), "--out", str(out), "--allow-provisional")
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        res = call("--input", str(src), "--out", str(out))
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["name"], "three-tier")  # 名前は root から

    def test_clean_input_exits_0(self):
        # raw IR の検査（core/ir_raw.semantic_errors）に通る形: 参照は props の $res と対応し、resources は address の順
        raw = raw_ir("tf", [resource("aws_subnet.a", "aws_subnet", {"tags": {"Name": "a"}, "availability_zone": "x-1a",
                                                                    "vpc_id": {"$res": "aws_vpc.v", "attr": "id"}}),
                            resource("aws_vpc.v", "aws_vpc", {"tags": {"Name": "net"}})],
                     [reference("aws_subnet.a", "vpc_id", "aws_vpc.v", "id")], root="fixtures/tf/net")
        out = self.dir / "sub" / "net.ir.json"
        res = call("--input", str(self.write("net.raw.json", raw)), "--out", str(out))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        ir = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([n["id"] for n in ir["nodes"]], ["availability_zone/net.x-1a", "subnet/a", "vpc/net"])
        self.assertEqual(res.stderr, "")

    def test_unreadable_inputs_exit_2(self):
        out = self.dir / "x.ir.json"
        cases = {
            "無いファイル": (str(self.dir / "nothing.json"), "読めない"),
            "JSON でない": (str(self.write("bad.json", "{")), "JSON として読めない"),
            "raw IR でない": (str(self.write("norm.json", {"stage": "normalized", "nodes": []})), "raw IR"),
            "raw IR の検査": (str(self.write("dup.json", raw_ir("tf", [resource("a.b", "a"), resource("a.b", "a")]))), "検査に通らない"),
        }
        for label, (path, words) in cases.items():
            with self.subTest(label):
                res = call("--input", path, "--out", str(out))
                self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
                self.assertIn(words, res.stderr)
                self.assertFalse(out.exists())
        res = call("--input", str(self.write("ok.json", raw_ir("tf", []))), "--out", str(out), "--name", "Bad Name")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--name", res.stderr)

    def test_unwritable_output_exits_2(self):
        # --out が既にあるフォルダを指す（書けない）。トレースバックではなく、文と終了コード 2
        folder = self.dir / "既にあるフォルダ"
        folder.mkdir()
        res = call("--input", str(self.write("ok.json", raw_ir("tf", []))), "--out", str(folder))
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("normalized IR を書けませんでした", res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertTrue(folder.is_dir())


class CheckTest(unittest.TestCase):
    def test_check_reports_coverage_problems_and_provisional_entries(self):
        raw = raw_ir("tf", [resource("aws_vpc.v", "aws_vpc"), resource("aws_security_group.s", "aws_security_group")])
        ir = build.normalize(raw, None, "t")
        self.assertEqual(build.check(raw, ir), ([], ["aws_security_group.s（R-SG）"]))
        broken = json.loads(json.dumps(ir))
        res = broken["sources"]["tf"]["resources"]
        res.append(dict(res[0]))
        res.append({"address": "extra.x", "type": "x", "file": "main.tf", "class": "unknown"})
        raw["resources"].append(resource("aws_s3_bucket.gone", "aws_s3_bucket"))
        problems, _ = build.check(raw, broken)
        self.assertEqual([p.split(":")[0] for p in problems],
                         ["網羅分類に無い入力のリソース", "入力に無いリソースが網羅分類にある", "網羅分類に 2 回以上あるリソース"])


if __name__ == "__main__":
    unittest.main()
