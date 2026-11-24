# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""CI で 3 形式（.drawio・.mmd・.png）を生成して検証する（PLAN のフェーズ 6 の完了基準「Windows と Ubuntu の CI で3形式が生成でき、検証が通る」）。

自作 5 構成の TF（three-tier は dev）と CFN を make_diagram.py で図にし、すべてのビューで PNG と mmdc の描画確認が ok（スキップを許さない）、
見やすさの問題が 0、終了コード 0 であることを確かめる。draw.io と mmdc が入った環境で動かす。

使い方: uv run python aws-iac-diagram-workspace/tools/ci_render_check.py --out-dir <フォルダ>
終了コード: 0 = すべて通った、1 = 通らないものがある
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "aws-iac-diagram-workspace" / "fixtures"
MAKE = ROOT / "skills" / "aws-iac-diagram" / "scripts" / "make_diagram.py"
CONFIGS = ("rag", "serverless-api", "three-tier", "three-tier-modules", "vpc-endpoints")


def inputs() -> list[tuple[str, list[str]]]:
    out = []
    for c in CONFIGS:
        extra = ["--var-file", str(FX / "tf" / c / "env" / "dev.tfvars")] if c == "three-tier" else []
        out.append((f"tf-{c}", ["--input", str(FX / "tf" / c), *extra]))
        cfn = FX / "cfn" / c
        if c == "three-tier-modules":  # ネストスタックの親
            out.append((f"cfn-{c}", ["--input", str(cfn / "root.yaml")]))
        elif c == "vpc-endpoints":  # JSON のテンプレートとパラメータのファイル
            out.append((f"cfn-{c}", ["--input", str(cfn / "template.json"), "--param-file", str(cfn / "parameters.json")]))
        else:
            out.append((f"cfn-{c}", ["--input", str(cfn / "template.yaml")]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    bad = 0
    for name, args in inputs():
        out = a.out_dir / name
        p = subprocess.run(["uv", "run", str(MAKE), *args, "--out-dir", str(out)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        res = json.loads((out / "result.json").read_text(encoding="utf-8")) if (out / "result.json").is_file() else {}
        views = (res.get("diagram") or {}).get("views", {})
        problems = [f"exit {p.returncode}: {p.stderr[-600:]}"] if p.returncode != 0 else []
        if not views:
            problems.append("ビューが無い")
        for v, d in sorted(views.items()):
            for k in ("png", "mermaid"):
                if d.get(k, {}).get("status") != "ok":
                    problems.append(f"{v} {k}: {d.get(k)}")
            if d.get("problems"):
                problems.append(f"{v}: {d['problems'][:3]}")
        print(("OK  " if not problems else "NG  ") + f"{name}: {len(views)} views")
        for x in problems:
            print("    " + x)
        bad += bool(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
