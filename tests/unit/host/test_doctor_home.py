"""doctor.py の check_linux（Linux の画面と HOME の確認）のテスト。

HOME が無いと draw.io は PNG を出しても終了コード 1 を返すので、draw.io を使えるときだけ warn にする（PLAN 2.2 の 12）。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
import support  # noqa: E402
support.ensure_paths()  # scripts/ と tools/ を sys.path に入れる（import だけでも入る。明示する）
import doctor  # noqa: E402
from aws_iac_diagram.platform import drawio_cli as dc  # noqa: E402

FOUND = {"path": "/usr/bin/drawio"}


class CheckLinuxHomeTest(unittest.TestCase):
    def check(self, env: dict[str, str], drawio: dict | None, platform: str = "linux"):
        issues: list[dict] = []
        with mock.patch.object(doctor.sys, "platform", platform), mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(dc, "needs_xvfb", return_value=False):
            info = doctor.check_linux(dc, drawio, issues)
        return info, issues

    def test_home_missing_with_drawio_warns(self):
        info, issues = self.check({}, FOUND)
        self.assertIsNone(info["HOME"])
        self.assertEqual([(i["level"], i["item"]) for i in issues], [("warn", "home")])

    def test_home_empty_is_missing(self):
        _, issues = self.check({"HOME": ""}, FOUND)
        self.assertEqual([i["item"] for i in issues], ["home"])

    def test_home_set_is_quiet(self):
        info, issues = self.check({"HOME": "/home/u"}, FOUND)
        self.assertEqual(info["HOME"], "/home/u")
        self.assertEqual(issues, [])

    def test_home_missing_without_drawio_is_quiet(self):
        # draw.io が無ければ PNG はもともとスキップされ、drawio の warn が出ている。重ねて知らせない
        for drawio in (None, {"path": None}):
            _, issues = self.check({}, drawio)
            self.assertEqual(issues, [])

    def test_not_linux(self):
        info, issues = self.check({}, FOUND, platform="win32")
        self.assertIsNone(info)
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
