# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4", "PyYAML==6.0.3", "jsonschema==4.26.0"]
# ///
"""全入力の図の確認と、図の固定（フェーズ 4）。

1. `--all`: golden.py の 101 ケースを raw → normalized → `.drawio` まで動かし、CRITERIA 2.2 の問題と 1 枚のアイコンの数を数える（数分かかる）。
2. 既定（`--check`）／`--update`: 正解 IR 17 個の `.drawio` の SHA-256 を `tests/golden/manifest-drawio.json` と比べる（C5。CI の両 OS）。

終了コード: 0 = 問題なし、1 = 問題あり
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import golden_normalized as gn  # noqa: E402

golden = gn.golden
DIAGRAM = golden.SCRIPTS / "diagram.py"
MANIFEST = golden.ROOT / "tests" / "golden" / "manifest-drawio.json"
EXPECTED = golden.WS / "expected"


def expected_files() -> list[Path]:
    return sorted(EXPECTED.glob("*.ir.json")) + sorted((EXPECTED / "public").glob("*.ir.json"))


def run_diagram(ir: Path, out: Path) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(DIAGRAM), "--input", str(ir), "--out-dir", str(out), "--no-external"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stderr[-400:]


def hashes(jobs: int) -> dict[str, str]:
    with tempfile.TemporaryDirectory(prefix="drawio-") as t:
        def one(f: Path) -> dict[str, str]:
            out = Path(t) / f.name
            code, err = run_diagram(f, out)
            if code != 0:
                return {f"FAILED/{f.name}": f"{code}: {err}"}
            return {f"{f.name}/{x.name}": hashlib.sha256(x.read_bytes()).hexdigest() for x in sorted(out.iterdir())}
        with ThreadPoolExecutor(jobs) as ex:
            return {k: v for d in ex.map(one, expected_files()) for k, v in d.items()}


def check(jobs: int | None = None) -> list[str]:
    now, exp = hashes(jobs or golden.default_jobs()), json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [f"{k}: {exp.get(k)} -> {now.get(k)}" for k in sorted(set(now) | set(exp)) if now.get(k) != exp.get(k)]


def run_all(jobs: int) -> int:
    cases = golden.enumerate_cases()
    with tempfile.TemporaryDirectory(prefix="diagram-all-") as t:
        tmp = Path(t)
        def one(args):
            i, (name, case) = args
            golden.run_case(case, tmp, i)
            ir = tmp / f"{i}.ir.json"
            subprocess.run([sys.executable, str(gn.NORMALIZE), "--input", str(tmp / f"{i}.json"), "--out", str(ir),
                            "--name", gn.ir_name(name)], capture_output=True)
            out = tmp / f"o{i}"
            code, err = run_diagram(ir, out)
            return name, code, err, json.loads((out / "result.json").read_text(encoding="utf-8")) if (out / "result.json").is_file() else None
        with ThreadPoolExecutor(jobs) as ex:
            rows = list(ex.map(one, enumerate(cases.items())))
    total: Counter = Counter()
    for name, code, err, res in rows:
        if res is None:
            total["failed"] += 1
            print(f"FAILED {name}: {err}")
            continue
        for v, d in res["views"].items():
            total["views"] += 1
            total.update(p[0] for p in d["problems"])
            total["over40"] += d["icons"] > 40
            if d["problems"]:
                print(name, v, d["problems"][:2])
    print(dict(total))
    return 1 if any(k not in ("views", "over40") and n for k, n in total.items()) or total["over40"] else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--jobs", type=int)
    a = ap.parse_args()
    if a.all:
        return run_all(a.jobs or golden.default_jobs())
    if a.update:
        now = hashes(a.jobs or golden.default_jobs())
        if any(k.startswith("FAILED/") for k in now):
            print(now)
            return 1
        MANIFEST.write_text(json.dumps(now, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {MANIFEST.name}: {len(now)} files")
        return 0
    problems = check(a.jobs)
    print("\n".join(problems) or "diagram: OK")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
