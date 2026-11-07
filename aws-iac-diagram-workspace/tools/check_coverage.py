# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4", "PyYAML==6.0.3", "cfn-lint==1.57.2"]
# ///
"""正解 IR（expected/*.ir.json）か正規化の出力（normalized IR）の網羅分類（A6）と、入力のリソースを突き合わせる（X4。CRITERIA の 1.5）。

入力は IR の `sources.<形式>.root`（aws-iac-diagram-workspace/ からの相対パス）を、正規化を通さずに独立に読む（iac_inventory.py）。
正規化の出力を検査するとき（--ir）も同じ数え方で、正規化のコードは import しない（ツールが自分の出力を検算しないため）。

各 IR の sources.tf／sources.cfn について:
  - 入力の全ブロック（TF: resource と data。ローカルモジュールの中も含む。CFN: Resources。ネストスタックの中も含む）が、
    網羅分類に少なくとも1件あるか（インスタンスのインデックスを外したアドレスで照合）
  - 網羅分類の各アドレスが入力に実在するか（TF のレジストリモジュールの中身は via: module_summary で、
    そのモジュール呼び出しが入力にあれば可）
  - アドレスの重複が無いか（同じ address が 2 回あれば誤り）、type と file が入力と一致するか
  - count／for_each の無いブロックにインデックス付きのアドレスが無いか、ある場合はインデックス付きか
    （0 件に評価されたものはインデックスなしで H-COND-FALSE）
  - count／for_each が単純な式（整数、length(var.X)、var.X、toset(var.X)）なら、ルートの変数
    （default → terraform.tfvars → *.auto.tfvars → 正解 IR の evaluation.tf.var_files）で評価し、
    インスタンスのキーが網羅分類と一致するか。評価できない式（locals・条件式・モジュールの中）は (注) として表示し、照合しない
  - CFN で Condition の付いていないリソースを H-COND-FALSE にしていないか
さらに --lint で fixture の全 CFN テンプレートを cfn-lint にかけ、全 .tf／.tfvars を python-hcl2 で読む。

使い方:
  uv run python aws-iac-diagram-workspace\\tools\\check_coverage.py [--lint]
  uv run python aws-iac-diagram-workspace\\tools\\check_coverage.py --ir <normalized IR の JSON> [--ir …]   # 正規化の出力を検査
  （`uv run check_coverage.py` でも動くが、Windows では uv のキャッシュの中の cfn-lint のパスが
  260 文字を超えて --lint が落ちることがあるので、リポジトリの開発用の環境で動かす）
終了コード: 0 = 問題なし、1 = 不一致あり
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from iac_inventory import cfn_inventory, eval_instances, tf_inventory, tf_variables  # noqa: E402

WS = Path(__file__).resolve().parent.parent
EXPECTED = WS / "expected"
INDEX = re.compile(r"\[[^\]]*\]")
LAST_INDEX = re.compile(r"\[([^\]]*)\]$")


def index_key(addr: str):
    """末尾のインスタンスキー（[0] → 0、["ssm"] → "ssm"）。無ければ None。"""
    m = LAST_INDEX.search(addr)
    if not m:
        return None
    k = m.group(1)
    return int(k) if k.isdigit() else k.strip('"')


def base(addr: str) -> str:
    return INDEX.sub("", addr)


def check_tf(src: dict, var_files: list[str] = (), notes: list[str] | None = None) -> list[str]:
    errs = []
    notes = [] if notes is None else notes
    root = WS / src["root"]
    variables = tf_variables(root, var_files)
    blocks = {b.address: b for b in tf_inventory(root) if b.kind in ("resource", "data")}
    modules = {b.address: b for b in tf_inventory(root) if b.kind == "module"}
    covered: dict[str, list[dict]] = {}
    for r in src["resources"]:
        covered.setdefault(base(r["address"]), []).append(r)
    for addr, b in blocks.items():
        entries = covered.get(addr)
        if not entries:
            errs.append(f"入力 {addr}（{b.file}）が網羅分類に無い")
            continue
        for r in entries:
            if r["type"] != b.type:
                errs.append(f"{r['address']}: type {r['type']} が入力の {b.type} と違う")
            if r["file"] != b.file:
                errs.append(f"{r['address']}: file {r['file']} が入力の {b.file} と違う")
            indexed = index_key(r["address"]) is not None  # ブロック自身のインデックス（count／for_each のモジュールの `[0]` は数えない）
            multi = b.count or b.for_each
            if multi and not indexed and not (r["class"] == "hidden" and r.get("rule") == "H-COND-FALSE"):
                errs.append(f"{r['address']}: count/for_each のあるブロックはインデックス付き（0 件なら H-COND-FALSE）")
            # 同じモジュールのインスタンスの中で（for_each のモジュールの別のインスタンスでは 0 件と 1 件以上が混ざってよい）
            if multi and not indexed and any(LAST_INDEX.sub("", x["address"]) == r["address"] for x in entries if x is not r):
                errs.append(f"{r['address']}: 0 件（インデックスなし）とインスタンスが混ざっている")
            if not multi and indexed:
                errs.append(f"{r['address']}: count/for_each の無いブロックにインデックスが付いている")
        if b.count or b.for_each:
            want = eval_instances(b.count_expr, variables, b.for_each) if not b.module_path else None
            if want is None:
                where = f"モジュール {b.module_path} の中" if b.module_path else "ルート"
                notes.append(f"{addr}: {'for_each' if b.for_each else 'count'} の式 {b.count_expr!r} は評価できない（{where}）。インスタンス数は照合していない")
                continue
            got = sorted((index_key(r["address"]) for r in entries if r["address"] != addr), key=str)
            if not want:
                if got or len(entries) != 1 or entries[0].get("rule") != "H-COND-FALSE":
                    errs.append(f"{addr}: 評価すると 0 件なので、インデックスなしの H-COND-FALSE 1件にする")
            elif sorted(want, key=str) != got:
                errs.append(f"{addr}: インスタンスが評価結果 {want} と違う（網羅分類は {got}）")
    for b_addr, entries in covered.items():
        if b_addr in blocks:
            continue
        for r in entries:
            if r.get("via") == "module_blackbox":
                # 黒箱のモジュールの呼び出し（ir-schema の 2 章）: 入力のモジュールの呼び出しそのものか、レジストリモジュール（要約表で展開）の中の呼び出し
                if b_addr in modules or any(b_addr.startswith(m + ".") and not modules[m].local for m in modules):
                    continue
                errs.append(f"{r['address']}: module_blackbox だが、そのモジュールの呼び出しが入力に無い")
            elif r.get("via") == "module_summary":
                owner = next((m for m in modules if b_addr.startswith(m + ".")), None)
                if owner is None or modules[owner].local:
                    errs.append(f"{r['address']}: module_summary だが、レジストリモジュールの呼び出しが入力に無い")
                elif r["file"] != modules[owner].file:
                    errs.append(f"{r['address']}: file はモジュール呼び出しのあるファイル（{modules[owner].file}）")
            else:
                errs.append(f"{r['address']}: 入力に無いアドレス")
    for m, b in modules.items():
        if not b.local and not any(base(r["address"]).startswith(m + ".") or base(r["address"]) == m for r in src["resources"]):
            errs.append(f"レジストリモジュール {m}（{b.source}）の中身が網羅分類に1件も無い")
    return errs


def duplicates(src: dict) -> list[str]:
    """同じ address が網羅分類に 2 回以上ある（ちょうど 1 回の決まり。X4 の重複）。"""
    seen: dict[str, int] = {}
    for r in src["resources"]:
        seen[r["address"]] = seen.get(r["address"], 0) + 1
    return [f"{a}: 網羅分類に {n} 回ある（ちょうど 1 回）" for a, n in sorted(seen.items()) if n > 1]


def check_ir(ir: dict) -> list[tuple[str, dict, list[str], list[str]]]:
    """IR の各形式の (形式, sources, 誤り, 注)。"""
    out = []
    for fmt, src in sorted(ir["sources"].items()):
        notes: list[str] = []
        var_files = ((ir.get("evaluation") or {}).get("tf") or {}).get("var_files", [])
        errs = duplicates(src) + (check_tf(src, var_files, notes) if fmt == "tf" else check_cfn(src))
        out.append((fmt, src, errs, notes))
    return out


# SAM が暗黙に作る API（ir-schema の 7.2 の implicit。テンプレートに無いが網羅分類に載る）の論理ID → 型
SAM_IMPLICIT = {"ServerlessRestApi": "AWS::Serverless::Api", "ServerlessHttpApi": "AWS::Serverless::HttpApi"}


def check_cfn(src: dict) -> list[str]:
    errs = []
    top = WS / src["root"]
    inv = {r.logical_id: r for r in cfn_inventory(top, follow_urls=True)}  # URL の TemplateURL も読み替える（SELECTION.md の 4 の 2）
    covered = {r["address"]: r for r in src["resources"]}
    for lid, r in inv.items():
        e = covered.get(lid)
        if e is None:
            errs.append(f"入力 {lid}（{r.file}）が網羅分類に無い")
            continue
        if e["type"] != r.type:
            errs.append(f"{lid}: type {e['type']} が入力の {r.type} と違う")
        if e["file"] != r.file:
            errs.append(f"{lid}: file {e['file']} が入力の {r.file} と違う")
        if e.get("rule") == "H-COND-FALSE" and r.condition is None:
            errs.append(f"{lid}: Condition が無いのに H-COND-FALSE")
    sam = any(r.type == "AWS::Serverless::Function" for r in inv.values())
    for lid, e in covered.items():
        if lid not in inv and not (sam and SAM_IMPLICIT.get(lid.rsplit("/", 1)[-1]) == e["type"]):
            errs.append(f"{lid}: 入力に無い論理ID")
    return errs


def lint() -> list[str]:
    import hcl2
    errs = []
    for f in sorted((WS / "fixtures" / "tf").rglob("*")):
        if f.suffix in (".tf", ".tfvars"):
            try:
                with f.open(encoding="utf-8") as fh:
                    hcl2.load(fh)
            except Exception as e:  # noqa: BLE001
                errs.append(f"hcl2: {f.relative_to(WS)}: {type(e).__name__}: {e}")
    exe = shutil.which("cfn-lint") or str(Path(sys.executable).parent / "cfn-lint")
    tpls = sorted(p for p in (WS / "fixtures" / "cfn").rglob("*")
                  if p.suffix in (".yaml", ".yml", ".json") and p.name != "parameters.json")
    p = subprocess.run([exe, "--regions", "ap-northeast-1", "--", *map(str, tpls)], capture_output=True, text=True)
    if p.returncode != 0:
        errs.append("cfn-lint:\n" + p.stdout + p.stderr)
    print(f"lint: .tf/.tfvars を python-hcl2 で読んだ。CFN テンプレート {len(tpls)} 本を cfn-lint にかけた（終了コード {p.returncode}）")
    return errs


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lint", action="store_true", help="cfn-lint と python-hcl2 で fixture の構文も確かめる")
    ap.add_argument("--ir", action="append", type=Path, default=[], help="正規化の出力（normalized IR）を検査する（何回でも。省略すると正解 IR）")
    a = ap.parse_args()
    failed = False
    for path in a.ir or sorted(EXPECTED.glob("*.ir.json")):
        ir = json.loads(path.read_text(encoding="utf-8"))
        for fmt, src, errs, notes in check_ir(ir):
            status = "OK" if not errs else "NG"
            print(f"{status} {path.name} [{fmt}] {src['root']}: {len(src['resources'])} 件")
            for e in errs:
                print(f"  - {e}")
            for n in notes:
                print(f"  (注) {n}")
            failed |= bool(errs)
    if a.lint:
        errs = lint()
        for e in errs:
            print(f"  - {e}")
        failed |= bool(errs)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
