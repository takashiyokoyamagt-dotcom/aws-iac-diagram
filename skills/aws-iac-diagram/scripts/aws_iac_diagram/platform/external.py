"""外部のツールの出力の確認: mmdc での `.mmd` の描画確認と、PNG の検査（0 バイトでない、四隅が黒くない。失敗知見 11）。

無い・動かないときは例外でなく (status, reason) で返す。呼ぶ側は `result.json` に書いて続ける（PLAN 1.2、CRITERIA 6.5）。
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

MMDC_ENV = "MMDC"


def find_mmdc() -> str | None:
    env = os.environ.get(MMDC_ENV)
    if env:
        return env if Path(env).is_file() else shutil.which(env)
    return shutil.which("mmdc")


def check_mermaid(mmd: Path, exe: str | None = None, timeout: int = 120) -> tuple[str, str]:
    """("ok"|"skipped"|"failed", 理由)。"""
    exe = exe or find_mmdc()
    if exe is None:
        return "skipped", "mmdc が見つからない"
    try:
        return _run_mmdc(mmd, exe, timeout)
    except OSError as e:  # 一時フォルダや設定を書けない・起動できない
        return "skipped", f"mmdc を動かせない: {e}"


def _run_mmdc(mmd: Path, exe: str, timeout: int) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="mmdc-") as t:
        out = Path(t) / "out.svg"
        cmd = [exe, "-i", str(mmd), "-o", str(out), "-q"]
        if sys.platform.startswith("linux"):
            cfg = Path(t) / "puppeteer.json"
            cfg.write_text(json.dumps({"args": ["--no-sandbox"]}), encoding="utf-8")
            cmd += ["-p", str(cfg)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return "skipped", f"mmdc が {timeout} 秒で終わらない"
        if res.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
            err = (res.stderr or res.stdout).strip()
            # 構文の誤りは出力の問題。文言の後にスタックトレースが続くので、切る前の全文で判定する。それ以外（ブラウザが起動できないなど）は環境の問題
            if any(w in err for w in ("Parse error", "Syntax error", "Lexical error", "UnknownDiagramError")):
                return "failed", err[:300]
            return "skipped", f"mmdc が動かない: {err[-300:]}"
    return "ok", ""


def _rows(data: bytes, width: int, height: int, channels: int) -> list[bytes]:
    stride = width * channels
    rows: list[bytes] = []
    prev = bytes(stride)
    pos = 0
    for _ in range(height):
        kind = data[pos]
        raw = bytearray(data[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        for i in range(stride):
            a = raw[i - channels] if i >= channels else 0
            b = prev[i]
            c = prev[i - channels] if i >= channels else 0
            if kind == 1:
                raw[i] = (raw[i] + a) & 255
            elif kind == 2:
                raw[i] = (raw[i] + b) & 255
            elif kind == 3:
                raw[i] = (raw[i] + (a + b) // 2) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                raw[i] = (raw[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = bytes(raw)
        rows.append(prev)
    return rows


def png_problem(path: Path) -> str:
    """問題があれば説明を返す（無ければ空文字）。8 ビットの RGB／RGBA の PNG の四隅が黒くないことを見る。"""
    try:
        return _png_problem(path)
    except (zlib.error, struct.error, IndexError, ValueError):
        return "PNG が壊れている"


def _png_problem(path: Path) -> str:
    data = path.read_bytes() if path.is_file() else b""
    if not data:
        return "0 バイト"
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return "PNG でない"
    pos, idat, width, height, depth, color = 8, b"", 0, 0, 0, 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", body[:10])
            if body[12] != 0:
                return ""  # インターレースは調べない
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    channels = {2: 3, 6: 4}.get(color)
    if depth != 8 or channels is None:
        return ""  # この形は調べない
    rows = _rows(zlib.decompress(idat), width, height, channels)
    for row, x in ((rows[0], 0), (rows[0], width - 1), (rows[-1], 0), (rows[-1], width - 1)):
        px = row[x * channels:x * channels + channels]
        if channels == 4 and px[3] == 0:
            continue  # 透明は黒ではない
        if px[:3] == b"\x00\x00\x00":
            return "四隅が黒い"
    return ""
