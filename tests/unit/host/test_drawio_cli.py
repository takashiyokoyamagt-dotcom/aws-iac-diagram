"""aws_iac_diagram/platform/drawio_cli.py（draw.io の探索と呼び出し）のテスト。

フォルダの名前が `host` なのは、標準ライブラリの `platform` を隠さないため（tests/ の下に `platform` のフォルダを置かない決まり。
docs/architecture.md の「テストの置き場」）。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
import support  # noqa: E402
support.ensure_paths()  # scripts/ と tools/ を sys.path に入れる（import だけでも入る。明示する）
from aws_iac_diagram.platform import drawio_cli as dc  # noqa: E402


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


class ExportPngArgsTest(unittest.TestCase):
    """export_png が draw.io に渡す引数を固定する（PLAN 2.2 の 12）。subprocess は呼ばない。"""

    def run_export(self, **kw) -> list[str]:
        calls: list[list[str]] = []

        def fake_run(cmd, **_):
            calls.append(cmd)
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"png")
            return mock.Mock(returncode=0, stderr="")

        # OS によらず、画面のある Linux の起動コマンド（--no-sandbox 付き）で組み立てる
        linux_command = dc.drawio_command
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(dc, "drawio_command", lambda exe: linux_command(exe, "linux", {"DISPLAY": ":0"})), \
                mock.patch.object(dc.subprocess, "run", fake_run):
            dc.export_png(Path(tmp, "in.drawio"), Path(tmp, "out.png"), exe=EXE, **kw)
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_forbidden_options_are_not_passed(self):
        # -e（XML の埋め込み）は PNG の末尾が欠ける、-w は引数の解析を黙って壊す、--scale はハングする報告がある
        for cmd in (self.run_export(), self.run_export(page_index=2, border=10)):
            tail = cmd[cmd.index("-x"):]  # xvfb-run の -s は -x より前にあるので除く
            for opt in ("-e", "--embed-diagram", "-w", "--width", "--scale", "-s"):
                self.assertFalse([a for a in tail if a == opt or a.startswith(opt + "=")], opt)

    def test_no_sandbox_before_export_and_input_last(self):
        # この並び（--no-sandbox は実行ファイルの直後、入力は最後）を draw.io 32.4.1（WSL、xvfb）で確かめた
        cmd = self.run_export(page_index=1)
        self.assertLess(cmd.index("--no-sandbox"), cmd.index("-x"))
        self.assertTrue(cmd[-1].endswith("in.drawio"))


if __name__ == "__main__":
    unittest.main()
