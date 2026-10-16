"""draw.io Desktop の CLI を探して呼び出す小さな共通部品。

check_icons.py（C2）と、今後作る export_png.py が共有する。
PLAN 2.2 の 12 に従い、`--scale` は使わない（ハングする issue #1774）、`--disable-gpu` を付ける、
出力サイズが 0 のときは失敗として扱う。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class DrawioError(RuntimeError):
    pass


# 1 にすると、Linux で画面があっても xvfb-run を使う（WSLg 上で CI と同じ経路を試すため。PLAN 1.2 の 2）
XVFB_ENV = "AWS_IAC_DIAGRAM_XVFB"
XVFB_SCREEN = "-screen 0 1920x1080x24"


def needs_xvfb(platform: str | None = None, environ: dict[str, str] | None = None) -> bool:
    """Linux で画面が無い（DISPLAY も WAYLAND_DISPLAY も無い）か、XVFB_ENV=1 なら True。"""
    platform = platform or sys.platform
    env = os.environ if environ is None else environ
    if not platform.startswith("linux"):
        return False
    if env.get(XVFB_ENV) == "1":
        return True
    return not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def drawio_command(exe: Path, platform: str | None = None,
                   environ: dict[str, str] | None = None) -> list[str]:
    """draw.io を起動するコマンドの先頭部分。

    Linux では Electron のサンドボックスがコンテナで落ちるので `--no-sandbox` を付け、
    画面が無ければ `xvfb-run -a` の上で動かす。Windows／macOS は実行ファイルだけ。
    """
    platform = platform or sys.platform
    if not platform.startswith("linux"):
        return [str(exe)]
    cmd = [str(exe), "--no-sandbox"]
    if needs_xvfb(platform, environ):
        xvfb = shutil.which("xvfb-run")
        if not xvfb:
            raise DrawioError("画面が無い Linux ですが、xvfb-run が見つかりません。"
                              "Ubuntu では apt install xvfb で入れてください。")
        # 既定の画面は 8bit なので、Electron が前提にする 24bit にする（PNG の再現性のため）
        cmd = [xvfb, "-a", "-s", XVFB_SCREEN, *cmd]
    return cmd


def _candidates() -> list[Path]:
    """OS ごとの既定のインストール先（存在するかは問わない）。"""
    out: list[Path] = []
    if sys.platform == "win32":
        for env in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if base:
                sub = ("Programs", "draw.io") if env == "LOCALAPPDATA" else ("draw.io",)
                out.append(Path(base, *sub, "draw.io.exe"))
    elif sys.platform == "darwin":
        out.append(Path("/Applications/draw.io.app/Contents/MacOS/draw.io"))
        out.append(Path.home() / "Applications/draw.io.app/Contents/MacOS/draw.io")
    else:
        out += [Path("/usr/bin/drawio"), Path("/opt/drawio/drawio"), Path("/snap/bin/drawio")]
    return out


def find_drawio() -> Path:
    """draw.io の実行ファイルを返す。環境変数 DRAWIO が最優先、次に PATH、最後に既定の場所。"""
    env = os.environ.get("DRAWIO")
    if env:
        p = Path(env)
        if p.is_file():
            return p
        raise DrawioError(f"環境変数 DRAWIO のパスがありません: {env}")
    for name in ("drawio", "draw.io"):
        hit = shutil.which(name)
        if hit:
            return Path(hit)
    for p in _candidates():
        if p.is_file():
            return p
    raise DrawioError(
        "draw.io Desktop が見つかりません。Windows: winget install -e --id JGraph.Draw / "
        "macOS: brew install --cask drawio。別の場所に入れた場合は環境変数 DRAWIO に実行ファイルのパスを設定してください。"
    )


def drawio_version(exe: Path | None = None) -> str:
    exe = exe or find_drawio()
    try:
        res = subprocess.run([*drawio_command(exe), "--version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DrawioError(f"draw.io --version を実行できませんでした: {e}") from e
    ver = res.stdout.strip().splitlines()[-1].strip() if res.stdout.strip() else ""
    if res.returncode != 0 or not ver:
        raise DrawioError(f"draw.io --version が失敗しました (rc={res.returncode}): {res.stderr.strip()}")
    return ver


def export_png(src: Path, dst: Path, *, page_index: int | None = None, border: int = 0,
               timeout: int = 300, exe: Path | None = None) -> Path:
    """src（.drawio）を PNG に書き出す。page_index は 1 始まり。

    倍率は常に 1（`--scale` は付けない）。テーマは light に固定して出力を決定論的にする。
    draw.io 自身の `--timeout`（v31.5.2 以降）と subprocess のタイムアウトを併用する。
    出力が無いか 0 バイトなら DrawioError。
    """
    exe = exe or find_drawio()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    cmd = [*drawio_command(exe), "-x", "-f", "png", "--disable-gpu", "--theme", "light",
           "--timeout", str(timeout), "-b", str(border), "-o", str(dst)]
    if page_index is not None:
        cmd += ["-p", str(page_index)]
    cmd.append(str(src))
    try:
        # draw.io の --timeout が先に効くよう、外側は少し長めに待つ
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout + 60, check=False)
    except subprocess.TimeoutExpired as e:
        raise DrawioError(f"draw.io の書き出しが {timeout + 60} 秒で終わりませんでした: {src}") from e
    except OSError as e:
        raise DrawioError(f"draw.io を起動できませんでした: {exe}: {e}") from e
    if res.returncode != 0 or not dst.is_file() or dst.stat().st_size == 0:
        raise DrawioError(
            f"draw.io の書き出しに失敗しました (rc={res.returncode}, 出力={'なし' if not dst.is_file() else str(dst.stat().st_size) + ' bytes'})。"
            "サンドボックス内では何も出力せずに終わることがあります（PLAN 2.2 の 12）。\n"
            f"cmd: {' '.join(cmd)}\nstderr: {res.stderr.strip()[-2000:]}"
        )
    return dst
