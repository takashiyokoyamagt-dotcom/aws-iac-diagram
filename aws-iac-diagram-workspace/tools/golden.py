# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4", "PyYAML==6.0.3", "jsonschema==4.26.0"]
# ///
"""出力の固定（フェーズ 2b の R1。PLAN の 1.4 の 6）: アダプタの raw IR を、バイト単位で固定した値と比べる。

構成の階層化（ファイルの移動・分割）の前後で「中身の動きが変わっていない」ことを確かめる道具。
アダプタの CLI（`--out` に書く raw IR。`dump()` の出力そのもの）を子プロセスで動かし、書かれたファイルの
SHA-256 を `tests/golden/manifest.json` と比べる。固定する物:

  - tf/custom/…      自作 TF 構成 5 つ（fixtures/tf）と、変数の渡し方を変えたもの
  - tf/plan-only/…   コミットした plan JSON 7 つを --input に渡したもの（fixtures/tf-plan）
  - tf/combined/…    同じ plan JSON を .tf のフォルダと合わせたもの（--plan）
  - tf/public/…      公開サンプルの TF のルート 52（tf_public_check.root_folders()）
  - cfn/custom/…     自作 CFN 構成 5 つ（と --param-file を渡したもの）
  - cfn/public/…     c1_check.discover() の入力のうち、自作でない公開サンプルのもの

引数は CI と同じ（リポジトリのルートを作業フォルダにし、相対パスと `--root-base aws-iac-diagram-workspace`）。
出力に絶対パスが入らないことも確かめる（入っていれば hash が一致しても失敗にする）。

使い方（リポジトリのルートで）:
  uv run python aws-iac-diagram-workspace/tools/golden.py              # --check と同じ
  uv run python aws-iac-diagram-workspace/tools/golden.py --check [--only <名前の接頭辞>] [--jobs N]
  uv run python aws-iac-diagram-workspace/tools/golden.py --list
  uv run python aws-iac-diagram-workspace/tools/golden.py --dump <名前> --out <ファイル>   # 今の出力を1件書く（不一致の調査用）
  uv run python aws-iac-diagram-workspace/tools/golden.py --update       # manifest を書き換える（下の注意）

注意: **`--update` を、リファクタ（構成の階層化 R1〜R6 など、動きを変えないはずの変更）を「通す」ために使ってはいけない。**
`--check` が落ちたら、リファクタが出力を変えたということなので、コードを直す（`--dump` で出力を書き、移す前のコミットの
出力と比べる）。`--update` は、アダプタの動きを意図して変えたとき（フェーズ 3 以降の仕様変更、fixture の追加）に、
変えた理由をコミットメッセージに書いたうえで使う。既存のケースの hash が変わるとき・ケースが減るときは `--accept-changes` を付けないと
書き換えない（変わる・減るケースの一覧を出して止まる）。

終了コード: 0 = すべて一致、1 = 不一致・欠け・余り・絶対パスの混入、2 = 使い方の誤り
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
WS = TOOLS.parent
ROOT = WS.parent
MANIFEST = ROOT / "tests" / "golden" / "manifest.json"
SCRIPTS = ROOT / "skills" / "aws-iac-diagram" / "scripts"
MANIFEST_VERSION = 1

# アダプタの入口（R2・R3 で入口を分けたら、ここだけ直す）
ENTRY = {
    "tf": SCRIPTS / "adapters" / "tf.py",
    "cfn": SCRIPTS / "adapters" / "cfn.py",
}

WSREL = "aws-iac-diagram-workspace"  # --root-base の値。CI と同じ
FIXTURES = f"{WSREL}/fixtures"

for _p in (str(TOOLS),):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# --------------------------------------------------------------------------------------------------------------
# ケースの一覧
# --------------------------------------------------------------------------------------------------------------

def enumerate_cases() -> dict[str, dict]:
    """名前 → {"adapter", "args"}。args は --out を除く CLI の引数（リポジトリのルートが作業フォルダ）。"""
    import c1_check
    import tf_public_check

    cases: dict[str, dict] = {}

    def add(name: str, adapter: str, args: list[str]) -> None:
        assert name not in cases, name
        cases[name] = {"adapter": adapter, "args": args}

    # --- TF: 自作 5 構成（CI の「TF アダプタ」の手順と同じ引数）
    tf_dir = WS / "fixtures" / "tf"
    customs = sorted(p.name for p in tf_dir.iterdir() if p.is_dir())
    for n in customs:
        add(f"tf/custom/{n}", "tf", ["--input", f"{FIXTURES}/tf/{n}", "--root-base", WSREL])
    # 変数の渡し方（--var-file の相対パス、--var、--redact-var、--workspace）。CI の PowerShell の手順と同じもの＋α
    t = f"{FIXTURES}/tf/three-tier"
    add("tf/custom/three-tier.var-file-dev", "tf",
        ["--input", t, "--root-base", WSREL, "--var-file", "env/dev.tfvars", "--var", "project=demo"])
    add("tf/custom/three-tier.var-file-prod", "tf",
        ["--input", t, "--root-base", WSREL, "--var-file", "env/prod.tfvars"])
    add("tf/custom/three-tier.redact-workspace", "tf",
        ["--input", t, "--root-base", WSREL, "--var-file", "env/dev.tfvars", "--redact-var", "project",
         "--workspace", "staging"])

    # --- TF: plan JSON（CI と同じ対応: <名前>.json の .tf のフォルダは、最初の「.」までの名前。edge だけ tf-plan/edge）
    plan_dir = WS / "fixtures" / "tf-plan"
    for f in sorted(plan_dir.glob("*.json")):
        n = f.stem
        folder = f"{FIXTURES}/tf/{n.split('.')[0]}"
        if n == "edge":
            folder = f"{FIXTURES}/tf-plan/edge"
        plan = f"{FIXTURES}/tf-plan/{f.name}"
        add(f"tf/plan-only/{n}", "tf", ["--input", plan, "--root-base", WSREL])
        add(f"tf/combined/{n}", "tf", ["--input", folder, "--plan", plan, "--root-base", WSREL])

    # --- TF: 公開サンプルのルート 52
    for rel in tf_public_check.root_folders():
        add(f"tf/public/{rel}", "tf", ["--input", f"{FIXTURES}/public/{rel}", "--root-base", WSREL])

    # --- CFN: c1_check の入力（自作 5＋公開サンプル）。自作は fixtures/cfn の下
    for p in c1_check.discover():
        rel = p.resolve().relative_to((WS / "fixtures").resolve()).as_posix()
        if rel.startswith("cfn/"):
            add(f"cfn/custom/{rel.split('/')[1]}", "cfn", ["--input", f"{FIXTURES}/{rel}", "--root-base", WSREL])
        else:
            add(f"cfn/public/{rel[len('public/'):]}", "cfn", ["--input", f"{FIXTURES}/{rel}", "--root-base", WSREL])
    # パラメータのファイル（--param-file）と --param
    add("cfn/custom/vpc-endpoints.param-file", "cfn",
        ["--input", f"{FIXTURES}/cfn/vpc-endpoints/template.json", "--root-base", WSREL,
         "--param-file", f"{FIXTURES}/cfn/vpc-endpoints/parameters.json"])
    add("cfn/custom/three-tier.param", "cfn",
        ["--input", f"{FIXTURES}/cfn/three-tier/template.yaml", "--root-base", WSREL,
         "--param", "AWS::Region=ap-northeast-1"])
    return dict(sorted(cases.items()))


# --------------------------------------------------------------------------------------------------------------
# 実行
# --------------------------------------------------------------------------------------------------------------

def _path_forms(p: str) -> set[str]:
    """パスの書き方の揺れ（区切りの種類、JSON の中で二重になったバックスラッシュ）。"""
    return {p, p.replace("\\", "/"), p.replace("\\", "\\\\")}


def absolute_path_hits(text: str, extra: tuple[str, ...] = ()) -> list[str]:
    """出力にリポジトリの絶対パス・ホームのフォルダ・一時フォルダが混ざっていれば、その断片を返す。

    ドライブ名とコロンと区切りの形の一般的な検索はしない（公開サンプルの Lambda のコードなどの文字列に偶然現れて誤検出するため）。
    出力に入りうる絶対パスは、入力のパス（リポジトリの下）から作られるものだけ。
    """
    hits = []
    home = Path.home()
    bases = [str(ROOT), *extra] + ([str(home)] if len(home.parts) >= 3 else [])  # "/root" などは公開サンプルにも出る
    for base in bases:
        for needle in _path_forms(base):
            if needle and needle in text:
                hits.append(needle)
    return hits


def run_case(case: dict, tmp: Path, index: int) -> dict:
    """1 ケースの CLI を子プロセスで動かし、書かれたファイルのバイト列を返す。"""
    out = tmp / f"{index}.json"
    cmd = [sys.executable, str(ENTRY[case["adapter"]]), *case["args"], "--out", str(out)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    t0 = time.time()
    p = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    res: dict = {"code": p.returncode, "stderr": p.stderr.strip()[-400:], "seconds": time.time() - t0}
    if p.returncode == 0 and out.is_file():
        data = out.read_bytes()
        res["bytes"] = data
        res["sha256"] = hashlib.sha256(data).hexdigest()
        try:
            doc = json.loads(data.decode("utf-8"))
            res["summary"] = {"resources": len(doc["resources"]), "references": len(doc["references"]),
                              "diagnostics": len(doc["diagnostics"])}
        except Exception:  # noqa: BLE001  壊れた出力は hash の不一致として出る
            res["summary"] = {}
        res["abs_paths"] = absolute_path_hits(data.decode("utf-8", errors="replace"), (str(tmp),))
    return res


def run_all(cases: dict[str, dict], jobs: int) -> dict[str, dict]:
    names = list(cases)
    with tempfile.TemporaryDirectory(prefix="golden-") as t:
        tmp = Path(t)
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            futs = {n: ex.submit(run_case, cases[n], tmp, i) for i, n in enumerate(names)}
            return {n: f.result() for n, f in futs.items()}


# --------------------------------------------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------------------------------------------

def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def write_manifest(doc: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")


def entry_of(case: dict, res: dict) -> dict:
    s = res.get("summary", {})
    return {"adapter": case["adapter"], "args": case["args"], "sha256": res["sha256"], "bytes": len(res["bytes"]),
            "resources": s.get("resources"), "references": s.get("references"), "diagnostics": s.get("diagnostics")}


def compare(cases: dict[str, dict], results: dict[str, dict], manifest: dict, partial: bool) -> list[str]:
    """読みやすい差分の一覧（空なら一致）。partial = 一部のケースだけ動かしたので、manifest の余りは調べない。"""
    problems: list[str] = []
    mc = manifest["cases"]
    for name in sorted(cases):
        r, exp = results[name], mc.get(name)
        if exp is None:
            problems.append(f"NEW      {name}: manifest に無いケース（fixture を足したなら --update。リファクタなら不要な足し込み）")
            continue
        if r["code"] != 0:
            problems.append(f"FAILED   {name}: 終了コード {r['code']}: {r['stderr']}")
            continue
        if r["abs_paths"]:
            problems.append(f"ABSPATH  {name}: 出力に絶対パスが入っている: {r['abs_paths'][:2]}")
        if cases[name]["args"] != exp["args"] or cases[name]["adapter"] != exp["adapter"]:
            problems.append(f"ARGS     {name}: 引数が manifest と違う: {cases[name]['args']} != {exp['args']}")
        if r["sha256"] != exp["sha256"]:
            s = r.get("summary", {})
            delta = ", ".join(f"{k} {exp[k]}->{s.get(k)}" for k in ("resources", "references", "diagnostics")
                              if exp.get(k) != s.get(k)) or "件数は同じ"
            problems.append(f"CHANGED  {name}: sha256 {exp['sha256'][:12]} -> {r['sha256'][:12]} "
                            f"(bytes {exp['bytes']} -> {len(r['bytes'])}; {delta})")
    if not partial:
        for name in sorted(set(mc) - set(cases)):
            problems.append(f"MISSING  {name}: manifest にあるが、ケースの一覧に無い（fixture や入力を消した／名前を変えた）")
    return problems


# --------------------------------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------------------------------

def default_jobs() -> int:
    return max(1, min(4, os.cpu_count() or 1))


def check(only: str | None = None, jobs: int | None = None, verbose: bool = False) -> list[str]:
    """manifest と今の出力を比べ、差分の一覧を返す（unittest からも使う）。"""
    manifest = load_manifest()
    cases = enumerate_cases()
    if only:
        cases = {n: c for n, c in cases.items() if n.startswith(only)}
        if not cases:  # 打ち間違いで「0 件で OK」にしない
            return [f"NOMATCH --only {only!r} に合うケースが無い（golden.py --list で名前を確かめる）"]
    results = run_all(cases, jobs or default_jobs())
    if verbose:
        print(f"golden: {len(cases)} cases, {sum(r['seconds'] for r in results.values()):.1f} s of CPU-ish time")
    return compare(cases, results, manifest, partial=bool(only))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="raw IR をバイト単位で固定した値と比べる（フェーズ 2b の R1）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="比べる（既定）")
    g.add_argument("--update", action="store_true", help="manifest を書き換える。リファクタを通すために使わない（docstring）")
    g.add_argument("--dump", metavar="NAME", help="今の出力を 1 ケース書く（--out が要る）")
    g.add_argument("--list", action="store_true", help="ケースの名前と引数を出す")
    ap.add_argument("--out", type=Path, help="--dump の書き先")
    ap.add_argument("--only", metavar="PREFIX", help="名前がこの接頭辞のケースだけ（例: tf/custom/）")
    ap.add_argument("--jobs", type=int, default=None, help=f"並列数（既定 {default_jobs()}）")
    ap.add_argument("--accept-changes", action="store_true", help="--update で、既存のケースの hash が変わるのを認める")
    a = ap.parse_args(argv)

    if a.list:
        for n, c in enumerate_cases().items():
            print(f"{n}\t{c['adapter']}\t{' '.join(c['args'])}")
        return 0

    if a.dump:
        if not a.out:
            print("--dump には --out が要ります", file=sys.stderr)
            return 2
        cases = enumerate_cases()
        if a.dump not in cases:
            print(f"ケースがありません: {a.dump}（--list で一覧）", file=sys.stderr)
            return 2
        r = run_all({a.dump: cases[a.dump]}, 1)[a.dump]
        if r["code"] != 0:
            print(f"FAILED {a.dump}: 終了コード {r['code']}: {r['stderr']}", file=sys.stderr)
            return 1
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_bytes(r["bytes"])
        exp = load_manifest()["cases"].get(a.dump, {}).get("sha256")
        state = "一致" if exp == r["sha256"] else f"manifest と違う（manifest は {str(exp)[:12]}）"
        print(f"{a.dump}: sha256 {r['sha256'][:12]} ({len(r['bytes'])} bytes) -> {a.out}  [{state}]")
        return 0

    if a.update:
        if a.only:
            print("--update は全ケースを書き換えます（--only とは併用しません）", file=sys.stderr)
            return 2
        print("警告: --update は固定した出力を書き換える。リファクタを通すために使ってはいけない（動きを変えない変更で"
              "--check が落ちたら、コードを直す）。", file=sys.stderr)
        cases = enumerate_cases()
        results = run_all(cases, a.jobs or default_jobs())
        bad = [f"{n}: 終了コード {r['code']}: {r['stderr']}" for n, r in results.items() if r["code"] != 0]
        bad += [f"{n}: 出力に絶対パス {r['abs_paths'][:2]}" for n, r in results.items() if r.get("abs_paths")]
        if bad:
            print("書き換えません。次のケースが失敗しました:\n  " + "\n  ".join(bad), file=sys.stderr)
            return 1
        old = load_manifest()["cases"] if MANIFEST.is_file() else {}
        changed = sorted(n for n in cases if n in old and old[n]["sha256"] != results[n]["sha256"])
        removed = sorted(set(old) - set(cases))
        if (changed or removed) and not a.accept_changes:
            if changed:
                print("既存のケースの出力が変わります。意図した変更（アダプタの仕様変更）だけ --accept-changes で認めてください:\n  "
                      + "\n  ".join(changed), file=sys.stderr)
            if removed:
                print("固定していたケースが無くなります（fixture や入力を消した・名前を変えた）。意図した変更だけ "
                      "--accept-changes で認めてください:\n  " + "\n  ".join(removed), file=sys.stderr)
            return 1
        doc = {"version": MANIFEST_VERSION,
               "note": "tests/golden/manifest.json は golden.py --update だけが書く。手で直さない。リファクタを通すために更新しない"
                       "（PLAN の 1.4 の 6）",
               "cases": {n: entry_of(cases[n], results[n]) for n in cases}}
        write_manifest(doc)
        added = sorted(set(cases) - set(old))
        shown = MANIFEST.relative_to(ROOT).as_posix() if MANIFEST.is_relative_to(ROOT) else MANIFEST.name
        print(f"wrote {shown}: {len(cases)} cases "
              f"(added {len(added)}, removed {len(removed)}, changed {len(changed)})")
        return 0

    problems = check(a.only, a.jobs, verbose=True)
    if problems:
        print(f"golden: NG ({len(problems)} 件)")
        for p in problems:
            print("  " + p)
        print("リファクタで出たなら、コードを直す。調べるには: golden.py --dump <名前> --out <ファイル> と、移す前のコミットの "
              "同じ出力を比べる。--update で通してはいけない。")
        return 1
    n = len(load_manifest()["cases"]) if not a.only else len([c for c in enumerate_cases() if c.startswith(a.only)])
    print(f"golden: OK ({n} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
