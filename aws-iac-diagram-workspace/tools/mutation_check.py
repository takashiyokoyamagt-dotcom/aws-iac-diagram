# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4", "PyYAML==6.0.3", "jsonschema==4.26.0"]
# ///
"""変異テスト（CRITERIA 1.7、C4）: Terraform の入力に機械的な変更を加え、正規化した IR が変更に追従し、ほかが変わらないことを確かめる。

変更の種類（Terraform のみ。CloudFormation は未対応。WORKLOG に記録）:
- add: 参照を生まない単独の SNS トピックを足す → ノードが 1 つ増え、ほかのノード・辺・入れ子は同じ
- delete: 描くリソースで、ほかのブロックから参照されず、枠でも合成ノードの根拠でもないものを消す → そのノードが消え、
  消えた辺はすべてそのノードに付いていたもの、増えたノード・辺は無い
- disable: 同じ条件のリソースに `count = 0` を足す → delete と同じ性質（対象は H-COND-FALSE になる）
共通の性質（局所性）: 差分は上のものに限る。`external/internet` は、その辺がすべて消えたときだけ消えてよい。

対象と変更は決定論で選ぶ（入力ごとに、条件に合うリソースを address の名前順に並べ、`random.Random(SEED)` で 1 つ選ぶ）。

使い方: uv run python aws-iac-diagram-workspace/tools/mutation_check.py [--json <出力>]
終了コード: 0 = すべての変更で性質を満たす、1 = 満たさないものがある
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WS = ROOT / "aws-iac-diagram-workspace"
sys.path.insert(0, str(ROOT / "skills" / "aws-iac-diagram" / "scripts"))
sys.path.insert(0, str(WS / "tools"))

import survey_public  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402
from aws_iac_diagram.core import rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import build as norm_build  # noqa: E402

SEED = 20261125
CUSTOM = {f"tf-{c}": (WS / "fixtures" / "tf" / c, ["env/dev.tfvars"] if c == "three-tier" else [])
          for c in ("rag", "serverless-api", "three-tier", "three-tier-modules", "vpc-endpoints")}
MAIN_TF = ("T03", "T06", "T07", "T09", "T11", "T12", "T16")
RESOURCE = re.compile(r'^resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', re.M)
ADDED = '\nresource "aws_sns_topic" "c4_added" {\n  name = "c4-added-topic"\n}\n'


def inputs() -> dict[str, tuple[Path, list[str]]]:
    out = dict(CUSTOM)
    for sid in MAIN_TF:
        out[sid] = (WS / "fixtures" / "public" / survey_public.SAMPLES[sid][1][0], [])
    return out


def normalize(folder: Path, var_files: list[str], rules) -> dict:
    raw = tf_build.build_raw(folder, folder.parent, var_files=[folder / v for v in var_files])
    return norm_build.normalize(raw, rules, "c4")


def blocks(folder: Path) -> list[tuple[Path, str, str, int, int]]:
    """(ファイル, 型, 名前, 開始, 終了) の resource ブロック（波括弧の対応で終わりを探す。文字列の中の括弧は考えない）。"""
    out = []
    for f in sorted(folder.glob("*.tf")):
        text = f.read_text(encoding="utf-8")
        for m in RESOURCE.finditer(text):
            depth, i = 0, m.end() - 1
            while i < len(text):
                depth += {"{": 1, "}": -1}.get(text[i], 0)
                if depth == 0:
                    break
                i += 1
            out.append((f, m[1], m[2], m.start(), i + 1))
    return out


def candidates(folder: Path, ir: dict) -> list[tuple[Path, str, str, int, int, str]]:
    """消してよい描くリソース（ノード id つき）。"""
    drawn = {r["address"]: r["node"] for s in ir["sources"].values() for r in s["resources"] if r["class"] == "drawn" and r.get("node")}
    nodes = {n["id"]: n for n in ir["nodes"]}
    text = "\n".join(f.read_text(encoding="utf-8") for f in sorted(folder.glob("*.tf")))
    out = []
    for f, t, n, a, b in blocks(folder):
        addr = f"{t}.{n}"
        node = drawn.get(addr)
        if node is None or nodes[node]["category"] == "group" or nodes[node].get("synthetic"):
            continue
        if len(re.findall(rf"\b{re.escape(addr)}\b", text)) > 1:  # ほかから参照されている
            continue
        if any(x.get("parent") == node for x in ir["nodes"]):
            continue
        out.append((f, t, n, a, b, node))
    return out


def diff(before: dict, after: dict) -> dict:
    nb, na = {n["id"]: n for n in before["nodes"]}, {n["id"]: n for n in after["nodes"]}
    eb, ea = {e["id"] for e in before["edges"]}, {e["id"] for e in after["edges"]}
    changed = sorted(i for i in nb.keys() & na.keys() if nb[i] != na[i])
    return {"nodes_removed": sorted(nb.keys() - na.keys()), "nodes_added": sorted(na.keys() - nb.keys()),
            "edges_removed": sorted(eb - ea), "edges_added": sorted(ea - eb), "nodes_changed": changed}


def check_removed(d: dict, node: str, before: dict) -> list[str]:
    problems = []
    internet_edges = [e for e in before["edges"] if "external/internet" in (e["from"], e["to"])]
    allowed = {node} | ({"external/internet"} if internet_edges and all(node in (e["from"], e["to"]) for e in internet_edges) else set())
    if node not in d["nodes_removed"]:
        problems.append(f"ノード {node} が消えない")
    if set(d["nodes_removed"]) - allowed:
        problems.append(f"ほかのノードも消えた: {sorted(set(d['nodes_removed']) - allowed)}")
    bad = [e for e in d["edges_removed"] if not any(x in e.split("->") for x in allowed)]
    if bad:
        problems.append(f"そのノードに付いていない辺が消えた: {bad}")
    if d["nodes_added"] or d["edges_added"] or d["nodes_changed"]:
        problems.append(f"増えた・変わったものがある: {d['nodes_added'] + d['edges_added'] + d['nodes_changed']}")
    return problems


def run_case(name: str, folder: Path, var_files: list[str], rules) -> list[dict]:
    results = []
    with tempfile.TemporaryDirectory(prefix="c4-") as t:
        work = Path(t) / folder.name
        shutil.copytree(folder, work, ignore=shutil.ignore_patterns(".terraform", "*.tfstate*"))
        before = normalize(work, var_files, rules)
        # add
        main = sorted(work.glob("*.tf"))[0]
        original = main.read_text(encoding="utf-8")
        main.write_text(original + ADDED, encoding="utf-8")
        d = diff(before, normalize(work, var_files, rules))
        main.write_text(original, encoding="utf-8")
        p = [] if (len(d["nodes_added"]) == 1 and d["nodes_added"][0].startswith("sns_topic/") and not d["nodes_removed"]
                   and not d["edges_removed"] and not d["nodes_changed"]) else [f"差分が SNS トピック 1 つでない: {d}"]
        results.append({"input": name, "kind": "add", "target": "aws_sns_topic.c4_added", "problems": p})
        cands = candidates(work, before)
        if not cands:
            results.append({"input": name, "kind": "delete", "target": None, "problems": [], "note": "適用できない（条件に合うリソースが無い）"})
            return results
        f, typ, nm, a, b, node = random.Random(SEED).choice(sorted(cands, key=lambda c: (c[1], c[2])))
        for kind in ("delete", "disable"):
            text = f.read_text(encoding="utf-8")
            if kind == "delete":
                mutated = text[:a] + text[b:]
            else:
                head = text[a:b]
                if re.search(r"^\s*(count|for_each)\s*=", head, re.M):
                    results.append({"input": name, "kind": kind, "target": f"{typ}.{nm}", "problems": [], "note": "適用できない（count／for_each がある）"})
                    continue
                brace = text.index("{", a) + 1
                mutated = text[:brace] + "\n  count = 0\n" + text[brace:]
            f.write_text(mutated, encoding="utf-8")
            d = diff(before, normalize(work, var_files, rules))
            f.write_text(text, encoding="utf-8")
            results.append({"input": name, "kind": kind, "target": f"{typ}.{nm}", "problems": check_removed(d, node, before)})
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rules = rules_mod.default()
    rows = []
    for name, (folder, var_files) in inputs().items():
        rows += run_case(name, folder, var_files, rules)
    applied = [r for r in rows if "note" not in r]
    bad = [r for r in applied if r["problems"]]
    for r in rows:
        mark = "SKIP" if "note" in r else ("NG  " if r["problems"] else "OK  ")
        print(f"{mark}{r['input']} {r['kind']} {r['target']} {r.get('note', '')}{r['problems'] or ''}")
    print(f"適用 {len(applied)}、満たす {len(applied) - len(bad)}、満たさない {len(bad)}（{len(rows) - len(applied)} は適用できない）")
    if a.json:
        a.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
