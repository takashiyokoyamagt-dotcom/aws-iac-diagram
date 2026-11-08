"""`.mmd` の出力と検査、mmdc・draw.io が無いときのスキップ、PNG の検査（フェーズ 5）。"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
import support  # noqa: E402,F401
from aws_iac_diagram.emit import mermaid  # noqa: E402
from aws_iac_diagram.layout import views  # noqa: E402
from aws_iac_diagram.platform import external  # noqa: E402
from aws_iac_diagram.validate import mermaid as check_mermaid  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
EXPECTED = ROOT / "aws-iac-diagram-workspace" / "expected"
FILES = sorted(EXPECTED.glob("*.ir.json")) + sorted((EXPECTED / "public").glob("*.ir.json"))
DIAGRAM = ROOT / "skills" / "aws-iac-diagram" / "scripts" / "diagram.py"


def node(i, parent=None, category="resource", label=None):
    return {"id": i, "type": "x", "category": category, "name": i, "label": label or i, "parent": parent}


def edge(a, b, confidence="confirmed", label=None):
    return {"id": f"{a}->{b}", "from": a, "to": b, "kind": "request", "confidence": confidence, "label": label}


def png(pixel: bytes, color: int) -> bytes:
    def chunk(k, b):
        return struct.pack(">I", len(b)) + k + b + struct.pack(">I", zlib.crc32(k + b))
    raw = (b"\x00" + pixel * 2) * 2
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, color, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class MermaidTest(unittest.TestCase):
    def test_every_view_of_every_expected_ir(self):
        for f in FILES:
            ir = json.loads(f.read_text(encoding="utf-8"))
            for v in views.build(ir):
                text = mermaid.flowchart(v.nodes, v.edges)
                self.assertEqual(check_mermaid.check(text, v.nodes, v.edges), [], f"{f.name} {v.name}")
                self.assertNotIn("arn:", "\n".join(l.split("[")[0] for l in text.splitlines()), f.name)

    def test_shape_and_escape(self):
        nodes = [node("v", category="group", label='V"#1'), node("a", "v"), node("b")]
        text = mermaid.flowchart(nodes, [edge("a", "b", "inferred", "HTTP")])
        self.assertEqual(text, 'flowchart LR\n  n1["b"]\n  subgraph n2["V#quot;#35;1"]\n    n0["a"]\n  end\n  n0 -.->|"HTTP"| n1\n')

    def test_check_finds_differences(self):
        nodes, edges = [node("a"), node("b")], [edge("a", "b")]
        text = mermaid.flowchart(nodes, edges)
        self.assertEqual(check_mermaid.check(text, nodes[:1] + [node("b", label="z")], edges), ["ノードが同じビューと違う"])
        self.assertEqual(check_mermaid.check(text, nodes, []), ["辺が同じビューと違う"])
        self.assertEqual(check_mermaid.check("graph TD\n", nodes, edges), ["先頭が flowchart LR でない"])


class PngTest(unittest.TestCase):
    def check(self, data):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.png"
            p.write_bytes(data)
            return external.png_problem(p)

    def test_cases(self):
        self.assertEqual(self.check(png(b"\xff\xff\xff", 2)), "")
        self.assertEqual(self.check(png(b"\x00\x00\x00", 2)), "四隅が黒い")
        self.assertEqual(self.check(png(b"\x00\x00\x00\x00", 6)), "")  # 透明
        self.assertEqual(self.check(b""), "0 バイト")
        self.assertEqual(self.check(b"nope"), "PNG でない")


class SkipTest(unittest.TestCase):
    def test_missing_tools_are_skipped_with_exit_0(self):
        with tempfile.TemporaryDirectory() as t:
            env = dict(os.environ, DRAWIO=str(Path(t) / "none.exe"), MMDC=str(Path(t) / "none.exe"), PYTHONUTF8="1")
            out = Path(t) / "o"
            p = subprocess.run([sys.executable, str(DIAGRAM), "--input", str(EXPECTED / "serverless-api.ir.json"), "--out-dir", str(out)],
                               env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(p.returncode, 0, p.stderr)
            res = json.loads((out / "result.json").read_text(encoding="utf-8"))
            for v in res["views"].values():
                self.assertEqual((v["png"]["status"], v["mermaid"]["status"]), ("skipped", "skipped"))
            self.assertTrue(list(out.glob("*.drawio")) and list(out.glob("*.mmd")))

    def test_mmdc_parse_error_is_failed_and_browser_error_is_skipped(self):
        with tempfile.TemporaryDirectory() as t:
            m = Path(t) / "x.mmd"
            m.write_text("flowchart LR\n", encoding="utf-8")
            for err, want in (("Parse error on line 1", "failed"), ("Could not find Chrome", "skipped")):
                with mock.patch.object(external.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", err)):
                    self.assertEqual(external.check_mermaid(m, "mmdc")[0], want)


if __name__ == "__main__":
    unittest.main()
