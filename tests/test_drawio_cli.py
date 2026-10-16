"""drawio_cli の起動コマンドの組み立て（Linux の --no-sandbox と xvfb-run）のテスト。draw.io は不要。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "aws-iac-diagram" / "scripts"))

from lib import drawio_cli as dc  # noqa: E402

EXE = Path("drawio")


class NeedsXvfbTest(unittest.TestCase):
    def test_not_linux(self):
        for plat in ("win32", "darwin"):
            self.assertFalse(dc.needs_xvfb(plat, {}))
            self.assertFalse(dc.needs_xvfb(plat, {dc.XVFB_ENV: "1"}))

    def test_linux_without_display(self):
        self.assertTrue(dc.needs_xvfb("linux", {}))

    def test_linux_with_display(self):
        self.assertFalse(dc.needs_xvfb("linux", {"DISPLAY": ":0"}))
        self.assertFalse(dc.needs_xvfb("linux", {"WAYLAND_DISPLAY": "wayland-0"}))

    def test_force_xvfb(self):
        self.assertTrue(dc.needs_xvfb("linux", {"DISPLAY": ":0", dc.XVFB_ENV: "1"}))
        self.assertFalse(dc.needs_xvfb("linux", {"DISPLAY": ":0", dc.XVFB_ENV: "0"}))


class DrawioCommandTest(unittest.TestCase):
    def test_windows_and_mac_are_plain(self):
        self.assertEqual(dc.drawio_command(EXE, "win32", {}), [str(EXE)])
        self.assertEqual(dc.drawio_command(EXE, "darwin", {}), [str(EXE)])

    def test_linux_with_display(self):
        self.assertEqual(dc.drawio_command(EXE, "linux", {"DISPLAY": ":0"}), [str(EXE), "--no-sandbox"])

    def test_linux_headless_uses_xvfb(self):
        with mock.patch.object(dc.shutil, "which", return_value="/usr/bin/xvfb-run"):
            self.assertEqual(dc.drawio_command(EXE, "linux", {}),
                             ["/usr/bin/xvfb-run", "-a", "-s", dc.XVFB_SCREEN, str(EXE), "--no-sandbox"])

    def test_linux_headless_without_xvfb_fails(self):
        with mock.patch.object(dc.shutil, "which", return_value=None):
            with self.assertRaises(dc.DrawioError):
                dc.drawio_command(EXE, "linux", {})


if __name__ == "__main__":
    unittest.main()
