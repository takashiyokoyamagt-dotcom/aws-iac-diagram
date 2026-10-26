"""broken.json の辞書へのマージ（build_icon_catalog）と、find_aws_icon の既定の除外のテスト。

実行: uv run python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
import support  # noqa: E402
support.ensure_paths()  # scripts/ と tools/ を sys.path に入れる（import だけでも入る。明示する）
import find_aws_icon as fai  # noqa: E402
from maintenance import build_icon_catalog as bic  # noqa: E402


def entry(icon_id, title):
    kind, name = icon_id.split(":")
    return {"id": icon_id, "kind": kind, "name": name, "title": title, "category": "database",
            "palette_title": "AWS / Databases", "retired": False, "width": 78, "height": 78,
            "value": "", "style": "", "tags": []}


class MergeTest(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.broken = self.tmp / "broken.json"
        self.broken.write_text(json.dumps({"broken": [
            {"id": "shape:dynamodb_table", "reason": "solid", "detail": "単色"}]}), encoding="utf-8")
        self.catalog = [entry("shape:dynamodb_table", "Table"), entry("resource_icon:dynamodb", "DynamoDB")]

    def test_apply_marks_only_listed(self):
        out = bic.apply_broken(self.catalog, broken_path=self.broken)
        self.assertEqual([c["broken"] for c in out], [True, False])
        self.assertEqual(out[0]["broken_reason"], "単色")
        self.assertNotIn("broken_reason", out[1])

    def test_missing_file_means_not_broken(self):
        out = bic.apply_broken(self.catalog, broken_path=self.tmp / "none.json")
        self.assertFalse(any(c["broken"] for c in out))

    def test_reapply_is_idempotent(self):
        once = bic.apply_broken(self.catalog, broken_path=self.broken)
        empty = self.tmp / "empty.json"
        empty.write_text('{"broken": []}', encoding="utf-8")
        again = bic.apply_broken(bic.strip_broken(once), broken_path=empty)
        self.assertFalse(any(c["broken"] for c in again))
        self.assertFalse(any("broken_reason" in c for c in again))

    def test_write_outputs_stays_in_out_dir(self):
        """out_dir を渡せば本物の data/icons には書かない。broken.json も out_dir から読む。"""
        real = bic.OUT_DIR / "catalog.json"
        before = real.read_bytes() if real.exists() else None
        (self.tmp / "broken.json").write_text(self.broken.read_text(encoding="utf-8"), encoding="utf-8")
        bic.write_outputs([dict(c) for c in self.catalog], out_dir=self.tmp, sidebar=None)
        out = json.loads((self.tmp / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual([c["broken"] for c in out], [True, False])
        self.assertEqual(real.read_bytes() if real.exists() else None, before)

    def test_markdown_note(self):
        cat = bic.apply_broken(self.catalog, broken_path=self.broken)
        bic.write_markdown(cat, self.tmp)
        md = (self.tmp / "database.md").read_text(encoding="utf-8")
        self.assertIn("| `shape:dynamodb_table` | Table | shape | 78x78 | **broken**: 単色 |", md)
        self.assertIn("| `resource_icon:dynamodb` | DynamoDB | resource_icon | 78x78 |  |", md)


class FindTest(unittest.TestCase):
    def run_find(self, *argv):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        tmp = Path(td.name) / "catalog.json"
        cat = [entry("shape:dynamodb_table", "DynamoDB Table"), entry("resource_icon:dynamodb", "DynamoDB")]
        cat[0]["broken"], cat[0]["broken_reason"] = True, "単色"
        cat[1]["broken"] = False
        tmp.write_text(json.dumps(cat), encoding="utf-8")
        out = io.StringIO()
        with mock.patch.object(fai, "CATALOG", tmp), mock.patch.object(sys, "argv", ["find", *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                fai.main()
            except SystemExit:
                pass
        return out.getvalue()

    def test_broken_excluded_by_default(self):
        out = self.run_find("dynamodb")
        self.assertIn("resource_icon:dynamodb", out)
        self.assertNotIn("shape:dynamodb_table", out)

    def test_include_broken(self):
        out = self.run_find("dynamodb", "--include-broken")
        self.assertIn("shape:dynamodb_table", out)
        self.assertIn("BROKEN", out)


if __name__ == "__main__":
    unittest.main()
