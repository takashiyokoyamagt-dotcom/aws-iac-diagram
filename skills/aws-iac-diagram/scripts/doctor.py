# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""SKILL の実行環境を調べて JSON で報告する。失敗したときの切り分けに使う。

使い方（どのシェルからでも同じ1行）:
  uv run <この SKILL のフォルダ>/scripts/doctor.py --out <出力先>.json

--out を省くと、JSON を ASCII だけ（日本語は \\uXXXX）で標準出力に書く（PowerShell 5.1 で受けても化けない）。

終了コード:
  0  必要なものがそろっている
  1  任意の外部ツールが足りない（PNG の書き出しや .mmd の描画確認がスキップされる）
  2  SKILL の実行に必要なものが足りない、または doctor 自体が失敗した
"""
from __future__ import annotations

import argparse
import json
import locale
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

# main() で UTF-8 に切り替える前の値（cp932 などの切り分けに使う）
ORIGINAL_STDOUT_ENCODING = getattr(sys.stdout, "encoding", None)

# SKILL が読む同梱ファイル（無ければ配布の取り込み方が誤っている）
REQUIRED_FILES = [
    "SKILL.md",
    "scripts/aws_iac_diagram/platform/drawio_cli.py",
    "references/icons/catalog.json",
    "references/ir.schema.json",
]


def _tool_version(cmd: list[str]) -> str | None:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (res.stdout or res.stderr).strip()
    return out.splitlines()[0].strip() if res.returncode == 0 and out else None


def check_skill(issues: list[dict]) -> dict:
    missing = [f for f in REQUIRED_FILES if not (SKILL_DIR / f).is_file()]
    for f in missing:
        issues.append({"level": "error", "item": "skill",
                       "message": f"SKILL のファイルがありません: {f}。SKILL のフォルダを丸ごと取り込み直してください。"})
    return {"dir": str(SKILL_DIR), "non_ascii_path": not str(SKILL_DIR).isascii(),
            "missing_files": missing}


def check_uv() -> dict:
    # uv run は子プロセスに環境変数 UV（uv の実行ファイル）を渡す
    exe = os.environ.get("UV") or shutil.which("uv")
    return {"path": exe, "version": _tool_version([exe, "--version"]) if exe else None,
            "launched_by_uv": bool(os.environ.get("UV"))}


def load_drawio_cli(issues: list[dict]):
    """aws_iac_diagram/platform/drawio_cli.py を読む。取り込みが不完全で読めなければ error にして None を返す。"""
    try:
        from aws_iac_diagram.platform import drawio_cli
    except Exception as e:  # noqa: BLE001  ファイルの欠落も構文エラーも同じく error にする
        issues.append({"level": "error", "item": "skill",
                       "message": f"scripts/aws_iac_diagram/platform/drawio_cli.py を読み込めません（{type(e).__name__}: {e}）。"
                                  "SKILL のフォルダを丸ごと取り込み直してください。"})
        return None
    return drawio_cli


def check_drawio(dc, issues: list[dict]) -> dict:
    info: dict = {"path": None, "version": None, "command": None, "error": None}
    try:
        exe = dc.find_drawio()
        info["path"] = str(exe)
        info["command"] = dc.drawio_command(exe)
        info["version"] = dc.drawio_version(exe)
    except dc.DrawioError as e:
        info["error"] = str(e)
        issues.append({"level": "warn", "item": "drawio",
                       "message": f"draw.io を使えないため PNG の書き出しはスキップされます（.drawio と .mmd は出せます）: {e}"})
    return info


def check_linux(dc) -> dict | None:
    if not sys.platform.startswith("linux"):
        return None
    return {"DISPLAY": os.environ.get("DISPLAY"), "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY"),
            dc.XVFB_ENV: os.environ.get(dc.XVFB_ENV), "xvfb_run": shutil.which("xvfb-run"),
            "needs_xvfb": dc.needs_xvfb()}


def check_mermaid(issues: list[dict]) -> dict:
    node, mmdc = shutil.which("node"), shutil.which("mmdc")
    if not mmdc:
        issues.append({"level": "warn", "item": "mmdc",
                       "message": "mmdc（@mermaid-js/mermaid-cli）が無いため、.mmd の描画確認はスキップされます（.mmd 自体は出せます）。"})
    return {"node": node, "mmdc": mmdc}


def check_encoding() -> dict:
    info = {"stdout_original": ORIGINAL_STDOUT_ENCODING, "preferred": locale.getpreferredencoding(False),
            "locale": locale.getencoding(), "filesystem": sys.getfilesystemencoding(),
            "PYTHONUTF8": os.environ.get("PYTHONUTF8"), "PYTHONIOENCODING": os.environ.get("PYTHONIOENCODING")}
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        info["console_cp"], info["console_output_cp"] = k32.GetConsoleCP(), k32.GetConsoleOutputCP()
    return info


def diagnose() -> dict:
    issues: list[dict] = []
    dc = load_drawio_cli(issues)
    report = {
        "os": {"system": platform.system(), "release": platform.release(),
               "sys_platform": sys.platform, "machine": platform.machine()},
        "python": {"version": platform.python_version(), "executable": sys.executable},
        "uv": check_uv(),
        "encoding": check_encoding(),
        "environment": {"GITHUB_ACTIONS": os.environ.get("GITHUB_ACTIONS"),
                        "CLAUDECODE": os.environ.get("CLAUDECODE")},
        "skill": check_skill(issues),
        "drawio": check_drawio(dc, issues) if dc else None,
        "linux": check_linux(dc) if dc else None,
        "mermaid": check_mermaid(issues),
    }
    levels = {i["level"] for i in issues}
    report["status"] = "error" if "error" in levels else "warn" if "warn" in levels else "ok"
    report["issues"] = issues
    return report


def failure(e: BaseException) -> dict:
    msg = f"doctor 自体が失敗しました: {type(e).__name__}: {e}"
    return {"status": "error", "error": msg, "issues": [{"level": "error", "item": "doctor", "message": msg}]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SKILL の実行環境を調べて JSON で報告する")
    ap.add_argument("--out", help="結果の JSON を書くファイル（UTF-8）")
    args = ap.parse_args(argv)  # 引数の誤りは argparse が終了コード 2 で終える
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        report = diagnose()
        code = {"ok": 0, "warn": 1, "error": 2}[report["status"]]
    except Exception as e:  # doctor 自体の失敗も JSON で返し、終了コード 1（warn）と取り違えないよう 2 にする
        report, code = failure(e), 2
    if args.out:
        try:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            print(f"doctor: {report['status']}")
            return code
        except Exception as e:  # 書けなければ標準出力に出す
            report, code = failure(e), 2
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
