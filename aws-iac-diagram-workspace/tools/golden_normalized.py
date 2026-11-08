# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4", "PyYAML==6.0.3", "jsonschema==4.26.0"]
# ///
"""正規化の出力の固定（フェーズ 3 の手順 7）: normalized IR を、バイト単位で固定した値と比べる。

golden.py の 101 ケースのそれぞれで、アダプタの CLI の raw IR を normalize_ir.py の CLI に渡し、書かれたファイルの
SHA-256 と終了コードを `tests/golden/manifest-normalized.json` と比べる。raw の固定は golden.py（manifest.json）のまま。
同じ入力を 2 回・Windows と Ubuntu で動かして一致すること（設計草案 1.2 の o）は、CI の両 OS でこの比較が通ることで確かめる。

使い方（リポジトリのルートで）:
  uv run python aws-iac-diagram-workspace/tools/golden_normalized.py [--check] [--only <名前の接頭辞>] [--jobs N]
  uv run python aws-iac-diagram-workspace/tools/golden_normalized.py --update [--accept-changes]

注意: `--update` は、規則表や正規化の動きを意図して変えたときだけ使う（変えた理由は WORKLOG に書く）。リファクタで落ちたら
コードを直す。既存のケースの hash が変わる更新は `--accept-changes` が要る。

終了コード: 0 = 一致（または書いた）、1 = 不一致・失敗、2 = 引数の誤り
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

# tests/golden/ のパッケージと名前が衝突するので、ファイルの場所から別名で読む（tests/support/tools.py の load_tool と同じ別名）
if "golden_tool" not in sys.modules:
    _spec = importlib.util.spec_from_file_location("golden_tool", TOOLS / "golden.py")
    sys.modules["golden_tool"] = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(sys.modules["golden_tool"])
golden = sys.modules["golden_tool"]

MANIFEST = golden.ROOT / "tests" / "golden" / "manifest-normalized.json"
NORMALIZE = golden.SCRIPTS / "normalize_ir.py"
MANIFEST_VERSION = 1


def ir_name(case_name: str) -> str:
    """ケースの名前から IR の名前（小文字・数字・`-`）を作る。一時フォルダの名前に左右されないよう必ず渡す。"""
    return re.sub(r"[^a-z0-9]+", "-", case_name.lower()).strip("-")


def run_case(name: str, case: dict, tmp: Path, index: int) -> dict:
    raw = golden.run_case(case, tmp, index)
    if raw["code"] != 0 or "bytes" not in raw:
        return {"code": None, "stderr": f"アダプタの失敗（終了コード {raw['code']}）: {raw['stderr']}"}
    out = tmp / f"{index}.ir.json"
    cmd = [sys.executable, str(NORMALIZE), "--input", str(tmp / f"{index}.json"), "--out", str(out), "--name", ir_name(name)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    p = subprocess.run(cmd, cwd=str(golden.ROOT), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    res: dict = {"code": p.returncode, "stderr": p.stderr.strip()[-400:]}
    if out.is_file():
        data = out.read_bytes()
        doc = json.loads(data.decode("utf-8"))
        res.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), nodes=len(doc["nodes"]), edges=len(doc["edges"]),
                   abs_paths=golden.absolute_path_hits(data.decode("utf-8", errors="replace"), (str(tmp),)))
    return res


def run_all(cases: dict[str, dict], jobs: int) -> dict[str, dict]:
    with tempfile.TemporaryDirectory(prefix="golden-norm-") as t:
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            futs = {n: ex.submit(run_case, n, c, Path(t), i) for i, (n, c) in enumerate(cases.items())}
            return {n: f.result() for n, f in futs.items()}


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def write_manifest(cases: dict[str, dict]) -> None:
    doc = {"version": MANIFEST_VERSION,
           "note": "golden_normalized.py --update だけが書く。手で直さない。リファクタを通すために更新しない",
           "cases": cases}
    MANIFEST.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def entry_of(res: dict) -> dict:
    return {k: res[k] for k in ("sha256", "bytes", "nodes", "edges")} | {"exit": res["code"]}


def compare(results: dict[str, dict], expected: dict[str, dict], partial: bool) -> list[str]:
    problems: list[str] = []
    for name in sorted(results):
        r, exp = results[name], expected.get(name)
        if exp is None:
            problems.append(f"NEW      {name}: manifest に無いケース")
        elif "sha256" not in r:
            problems.append(f"FAILED   {name}: 終了コード {r['code']}: {r['stderr']}")
        elif r["abs_paths"]:
            problems.append(f"ABSPATH  {name}: 出力に絶対パスが入っている: {r['abs_paths'][:2]}")
        elif r["code"] != exp["exit"] or r["sha256"] != exp["sha256"]:
            problems.append(f"CHANGED  {name}: exit {exp['exit']} -> {r['code']}, sha256 {exp['sha256'][:12]} -> {r['sha256'][:12]}, "
                            f"bytes {exp['bytes']} -> {r['bytes']}, nodes {exp['nodes']} -> {r['nodes']}, edges {exp['edges']} -> {r['edges']}")
    if not partial:
        problems += [f"MISSING  {n}: manifest にあるが、ケースの一覧に無い" for n in sorted(set(expected) - set(results))]
    return problems


def selected(only: str | None) -> dict[str, dict]:
    cases = golden.enumerate_cases()
    return {n: c for n, c in cases.items() if not only or n.startswith(only)}


def check(only: str | None = None, jobs: int | None = None) -> list[str]:
    results = run_all(selected(only), jobs or golden.default_jobs())
    return compare(results, load_manifest()["cases"], partial=bool(only))


def update(jobs: int | None, accept_changes: bool) -> int:
    results = run_all(selected(None), jobs or golden.default_jobs())
    bad = [f"{n}: {r['code']}: {r['stderr']}" for n, r in results.items() if "sha256" not in r or r["code"] == 2]
    bad += [f"{n}: 出力に絶対パス" for n, r in results.items() if r.get("abs_paths")]
    if bad:
        print("書き換えません:\n  " + "\n  ".join(bad), file=sys.stderr)
        return 1
    old = load_manifest()["cases"] if MANIFEST.is_file() else {}
    new = {n: entry_of(r) for n, r in sorted(results.items())}
    changed = sorted(n for n in old if old[n] != new.get(n))
    if changed and not accept_changes:
        print("既存のケースが変わります。意図した変更だけ --accept-changes で認めてください:\n  " + "\n  ".join(changed), file=sys.stderr)
        return 1
    write_manifest(new)
    print(f"wrote {MANIFEST.name}: {len(new)} cases (changed {len(changed)})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="normalized IR をバイト単位で固定した値と比べる")
    ap.add_argument("--check", action="store_true", help="比べる（既定）")
    ap.add_argument("--update", action="store_true", help="manifest を書き換える")
    ap.add_argument("--accept-changes", action="store_true", help="--update で既存のケースが変わるのを認める")
    ap.add_argument("--only", metavar="PREFIX")
    ap.add_argument("--jobs", type=int)
    a = ap.parse_args(argv)
    if a.update:
        if a.only:
            print("--update は --only と併用しません", file=sys.stderr)
            return 2
        return update(a.jobs, a.accept_changes)
    problems = check(a.only, a.jobs)
    if problems:
        print(f"golden_normalized: NG ({len(problems)} 件)")
        print("\n".join("  " + p for p in problems))
        return 1
    print("golden_normalized: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
