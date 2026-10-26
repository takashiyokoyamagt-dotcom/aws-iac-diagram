# /// script
# requires-python = ">=3.12"
# dependencies = ["jsonschema==4.26.0"]
# ///
"""IR（スキーマは data/schemas/、v1.0。正規化後の形）を検証する。

検証すること:
  1. JSON Schema（data/schemas/ir.schema.json）に合っているか（jsonschema を使う）
  2. 参照の整合: ID の一意性、id と type の対応、id の key と name の対応（K-NAME）、parent・spans・辺の端点・網羅分類の node／into が存在するか、
     入れ子が循環しないか、spans の共通の祖先が parent か、合成でないノードが各形式で drawn になっているか、
     すべての辺に各形式の根拠があるか、使っている規則ID が references/ の規則表に定義されているか、
     class と規則の接頭辞（hidden → H-*、merged_into → M-*／R-*）、M-* の into はノード・R-* の into は辺、
     R-* で辺に統合したリソースの規則がその辺の根拠の rules にあるか、
     drawn の入力の型から resource-catalog.md の「描く型」の表でそのノードの型が描けるか
  3. 出力の形（C5）: キーの順・配列の順・インデント・末尾の改行がずれていないか（--write で整形する）

使い方:
  uv run scripts/validate_ir.py <ir.json>...            # 検証
  uv run scripts/validate_ir.py --write <ir.json>...    # 整形して書き戻してから検証
  uv run scripts/validate_ir.py --same-canonical A.json B.json   # 2つの canonical 部が一致するか

終了コード: 0 = すべて通過、1 = エラーあり、2 = 使い方の誤り・jsonschema が無い
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aws_iac_diagram.core import ir_raw, paths  # noqa: E402

SKILL = paths.SKILL_DIR
SCHEMA_PATH = paths.IR_SCHEMA
RAW_SCHEMA_PATH = paths.IR_RAW_SCHEMA
RULE_DOCS = list(paths.RULE_DOCS)
RULE_ROW = re.compile(r"^\|\s*`([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)`\s*\|", re.M)
SYNTHETIC_TYPES = {"availability_zone", "external", "bedrock_model"}
CATALOG = paths.RESOURCE_CATALOG
INPUT_TYPE = re.compile(r"`((?:aws|awscc|opensearch)_[a-z0-9_]+|AWS::[A-Za-z0-9]+::[A-Za-z0-9]+)`")
CLASS_PREFIX = {"hidden": ("H-",), "merged_into": ("M-", "R-")}
# 黒箱のモジュールになれる入力の型（ir-schema の 2章）
BLACKBOX_TYPES = {"module", "AWS::CloudFormation::Stack", "AWS::Serverless::Application"}


# ------------------------------------------------------------------ 形式（C5）

def _sort_lists(ir: dict) -> dict:
    ir = json.loads(json.dumps(ir))  # 深いコピー
    ir["nodes"] = sorted(ir.get("nodes", []), key=lambda n: n.get("id", ""))
    for n in ir["nodes"]:
        if "spans" in n:
            n["spans"] = sorted(n["spans"])
    ir["edges"] = sorted(ir.get("edges", []), key=lambda e: e.get("id", ""))
    for src in (ir.get("sources") or {}).values():
        src["resources"] = sorted(src.get("resources", []), key=lambda r: r.get("address", ""))
        for r in src["resources"]:
            if "into" in r:
                r["into"] = sorted(r["into"])
        src["edges"] = sorted(src.get("edges", []), key=lambda e: e.get("edge", ""))
        for e in src["edges"]:
            e["rules"] = sorted(e.get("rules", []))
            e["evidence"] = sorted(e.get("evidence", []))
    return ir


def canonical_dump(ir: dict) -> str:
    return json.dumps(_sort_lists(ir), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def canonical_part(ir: dict) -> dict:
    """TF 版と CFN 版の比較に使う部分（note を除く nodes と edges）。"""
    ir = _sort_lists(ir)
    strip = lambda d: {k: v for k, v in d.items() if k != "note"}  # noqa: E731
    return {"nodes": [strip(n) for n in ir["nodes"]], "edges": [strip(e) for e in ir["edges"]]}


# ------------------------------------------------------------------ 検証

def defined_rules() -> set[str]:
    rules: set[str] = set()
    for p in RULE_DOCS:
        if p.exists():
            rules.update(RULE_ROW.findall(p.read_text(encoding="utf-8")))
    return rules


def drawable_types() -> dict[str, set[str]]:
    """resource-catalog.md の「1. 描く型」の表から、入力の型 → 正規の型名 の対応を作る。"""
    out: dict[str, set[str]] = {}
    if not CATALOG.exists():
        return out
    text = CATALOG.read_text(encoding="utf-8")
    sec = text.split("## 1.", 1)[1].split("\n## ", 1)[0] if "## 1." in text else ""
    for line in sec.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].startswith("`"):
            continue
        canon = cells[0].strip("`")
        for col in cells[2:4]:
            for t in INPUT_TYPE.findall(col):
                out.setdefault(t, set()).add(canon)
    return out


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9._-]", "-", name.lower())


def schema_errors(ir: dict) -> list[str]:
    """stage が raw なら ir-raw.schema.json、それ以外は ir.schema.json で調べる。"""
    try:
        import jsonschema
    except ImportError:
        print("jsonschema がありません。uv run で起動してください（依存はスクリプト先頭の PEP 723 の宣言にあります）。", file=sys.stderr)
        sys.exit(2)
    schema_path = RAW_SCHEMA_PATH if ir.get("stage") == "raw" else SCHEMA_PATH
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    out = []
    for e in sorted(v.iter_errors(ir), key=lambda e: list(map(str, e.absolute_path))):
        loc = "/".join(map(str, e.absolute_path)) or "(root)"
        out.append(f"schema: {loc}: {e.message}")
    return out


def semantic_errors(ir: dict, rules: set[str], drawable: dict[str, set[str]] | None = None) -> list[str]:
    errs: list[str] = []
    drawable = drawable_types() if drawable is None else drawable
    nodes = {}
    for n in ir["nodes"]:
        if n["id"] in nodes:
            errs.append(f"node: id が重複: {n['id']}")
        nodes[n["id"]] = n
        if n["id"].split("/", 1)[0] != n["type"]:
            errs.append(f"node {n['id']}: id の型の部分と type（{n['type']}）が違う")
        if (n["type"] in SYNTHETIC_TYPES) != bool(n.get("synthetic")):
            errs.append(f"node {n['id']}: 型 {n['type']} の synthetic の値が規則と違う")
        if not n.get("synthetic") and n["id"].split("/", 1)[1] != slug(n["name"]):
            errs.append(f"node {n['id']}: id の key が name（{n['name']}）から作ったもの（{slug(n['name'])}）と違う（K-NAME）")
        if n["type"] == "external" and n["category"] != "external":
            errs.append(f"node {n['id']}: external の category は external")

    def ancestors(nid: str) -> list[str]:
        chain, cur, seen = [], nodes[nid].get("parent"), {nid}
        while cur is not None:
            if cur in seen:
                errs.append(f"node {nid}: 入れ子が循環している")
                break
            if cur not in nodes:
                break
            seen.add(cur)
            chain.append(cur)
            cur = nodes[cur].get("parent")
        return chain

    for nid, n in nodes.items():
        p = n.get("parent")
        if p is not None:
            if p not in nodes:
                errs.append(f"node {nid}: parent {p} が無い")
                continue
            if nodes[p]["category"] != "group":
                errs.append(f"node {nid}: parent {p} が group でない")
        if n["type"] == "availability_zone" and (p is None or nodes.get(p, {}).get("type") != "vpc"):
            errs.append(f"node {nid}: AZ の parent は vpc（N-AZ）")
        if n["type"] == "subnet" and (p is None or nodes.get(p, {}).get("type") != "availability_zone"):
            errs.append(f"node {nid}: subnet の parent は availability_zone（N-AZ）")
        spans = n.get("spans", [])
        if spans:
            if len(spans) < 2:
                errs.append(f"node {nid}: spans は2つ以上（1つなら parent をそのサブネットにする。P-SUBNET）")
            bad = [s for s in spans if s not in nodes or nodes[s]["type"] != "subnet"]
            if bad:
                errs.append(f"node {nid}: spans に subnet でないもの: {bad}")
            else:
                chains = [[s] + ancestors(s) for s in spans]
                common = [a for a in chains[0] if all(a in c for c in chains[1:])]
                lca = common[0] if common else None
                if lca != p:
                    errs.append(f"node {nid}: parent {p} が spans の最も近い共通の祖先 {lca} と違う（P-SPANS）")
        ancestors(nid)

    edges = {}
    for e in ir["edges"]:
        if e["id"] in edges:
            errs.append(f"edge: id が重複（順序付きの組ごとに1本。E-MERGE）: {e['id']}")
        edges[e["id"]] = e
        if e["id"] != f"{e['from']}->{e['to']}":
            errs.append(f"edge {e['id']}: id が from->to と違う")
        if e["from"] == e["to"]:
            errs.append(f"edge {e['id']}: 自己ループ")
        for end in ("from", "to"):
            if e[end] not in nodes:
                errs.append(f"edge {e['id']}: {end} のノード {e[end]} が無い")

    for fmt, src in (ir.get("sources") or {}).items():
        seen_addr = set()
        drawn = set()
        for r in src["resources"]:
            a = r["address"]
            if a in seen_addr:
                errs.append(f"sources.{fmt}: address が重複: {a}")
            seen_addr.add(a)
            pre = CLASS_PREFIX.get(r["class"])
            if pre and not r["rule"].startswith(pre):
                errs.append(f"sources.{fmt} {a}: class {r['class']} の規則は {'／'.join(p + '*' for p in pre)}（{r['rule']}）")
            if r["class"] == "merged_into":
                if r["rule"].startswith("M-") and any(t not in nodes for t in r["into"]):
                    errs.append(f"sources.{fmt} {a}: M-* の into はノード")
                if r["rule"].startswith("R-"):
                    if any(t not in edges for t in r["into"]):
                        errs.append(f"sources.{fmt} {a}: R-* の into は辺")
                    for t in r["into"]:
                        evr = next((x["rules"] for x in src["edges"] if x["edge"] == t), [])
                        if t in edges and r["rule"] not in evr:
                            errs.append(f"sources.{fmt} {a}: 辺 {t} の根拠の rules に {r['rule']} が無い")
            if r["class"] == "drawn":
                # 黒箱のモジュール（ir-schema の 2章）は入力の型によらず module のノードになり、
                # module のノードになれるのは黒箱のモジュールだけ（両方向）
                if r.get("via") == "module_blackbox":
                    allowed = {"module"}
                    if r["type"] not in BLACKBOX_TYPES:
                        errs.append(f"sources.{fmt} {a}: 入力の型 {r['type']} は黒箱のモジュールにできない（{sorted(BLACKBOX_TYPES)} だけ）")
                else:
                    allowed = drawable.get(r["type"])
                    if allowed is not None:
                        allowed = allowed - {"module"}
                if allowed is None:
                    errs.append(f"sources.{fmt} {a}: 入力の型 {r['type']} が resource-catalog.md の「描く型」に無い")
                elif r["node"] in nodes and nodes[r["node"]]["type"] not in allowed:
                    errs.append(f"sources.{fmt} {a}: 入力の型 {r['type']} から描けるのは {sorted(allowed)}（{nodes[r['node']]['type']} ではない）")
                if r["node"] not in nodes:
                    errs.append(f"sources.{fmt} {a}: node {r['node']} が無い")
                elif nodes[r["node"]].get("synthetic"):
                    errs.append(f"sources.{fmt} {a}: 合成ノード {r['node']} を drawn にしている")
                drawn.add(r["node"])
            for t in r.get("into", []):
                if t not in nodes and t not in edges:
                    errs.append(f"sources.{fmt} {a}: into {t} がノードにも辺にも無い")
            if "rule" in r and r["rule"] not in rules:
                errs.append(f"sources.{fmt} {a}: 規則 {r['rule']} が references/ の規則表に無い")
        for nid, n in nodes.items():
            if not n.get("synthetic") and nid not in drawn:
                errs.append(f"sources.{fmt}: ノード {nid} を drawn にしたリソースが無い")
        ev = {}
        for x in src["edges"]:
            if x["edge"] in ev:
                errs.append(f"sources.{fmt}: edges の edge が重複: {x['edge']}")
            ev[x["edge"]] = x
            if x["edge"] not in edges:
                errs.append(f"sources.{fmt}: 根拠の辺 {x['edge']} が edges に無い")
            for rid in x["rules"]:
                if rid not in rules:
                    errs.append(f"sources.{fmt} 辺 {x['edge']}: 規則 {rid} が references/ の規則表に無い")
        for eid in edges:
            if eid not in ev:
                errs.append(f"sources.{fmt}: 辺 {eid} の根拠が無い")
    return errs


DRAWABLE: dict[str, set[str]] | None = None


def validate_file(path: Path, write: bool, rules: set[str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    try:
        ir = json.loads(text)
    except json.JSONDecodeError as e:
        return [f"JSON として読めない: {e}"]
    errs = schema_errors(ir)
    if errs:
        return errs  # 形が違うと以降の検査が意味を持たない
    if ir.get("stage") == "raw":
        if write:  # 書き戻すなら、並び順の誤りは直るので先に並べ替えてから調べる
            ir = ir_raw.canonical_raw(ir)
        errs = ir_raw.semantic_errors(ir)
        want = json.dumps(ir_raw.canonical_raw(ir), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    else:
        errs = semantic_errors(ir, rules, DRAWABLE)
        want = canonical_dump(ir)
    if write and text != want:
        path.write_bytes(want.encode("utf-8"))
        text = want
    if text != want or b"\r" in path.read_bytes():
        errs.append("format: 出力の形（C5）が正規形と違う。--write で整形できる")
    return errs


def expand_globs(paths: list[Path]) -> list[Path]:
    """PowerShell はネイティブコマンドの引数の `*` を展開しないので、存在しないパスに `*`／`?` があればここで展開する。"""
    out: list[Path] = []
    for p in paths:
        if not p.exists() and any(c in p.name for c in "*?"):
            hits = sorted(p.parent.glob(p.name))
            out += hits or [p]  # 一致しなければそのまま渡し、読めないエラーとして報告させる
        else:
            out.append(p)
    return out


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--write", action="store_true", help="正規の形に整形して書き戻す")
    ap.add_argument("--same-canonical", nargs=2, type=Path, metavar=("A", "B"),
                    help="2つの IR の canonical 部（nodes と edges）が一致するかを調べる")
    a = ap.parse_args()
    if not a.paths and not a.same_canonical:
        ap.print_usage(sys.stderr)
        return 2
    global DRAWABLE
    rules = defined_rules()
    DRAWABLE = drawable_types()
    failed = False
    for p in expand_globs(a.paths):
        errs = validate_file(p, a.write, rules)
        if errs:
            failed = True
            print(f"NG {p}")
            for e in errs:
                print(f"  - {e}")
        else:
            ir = json.loads(p.read_text(encoding="utf-8"))
            if ir.get("stage") == "raw":
                print(f"OK {p}  raw {ir['format']} resources={len(ir['resources'])} references={len(ir['references'])}")
                continue
            print(f"OK {p}  nodes={len(ir['nodes'])} edges={len(ir['edges'])} "
                  + " ".join(f"{k}.resources={len(v['resources'])}" for k, v in sorted(ir["sources"].items())))
    if a.same_canonical:
        x, y = (canonical_part(json.loads(p.read_text(encoding="utf-8"))) for p in a.same_canonical)
        if x == y:
            print(f"SAME {a.same_canonical[0]} == {a.same_canonical[1]}（canonical 部が一致）")
        else:
            failed = True
            print(f"DIFF {a.same_canonical[0]} != {a.same_canonical[1]}")
            for part in ("nodes", "edges"):
                ix = {d["id"]: d for d in x[part]}
                iy = {d["id"]: d for d in y[part]}
                for k in sorted(set(ix) | set(iy)):
                    if ix.get(k) != iy.get(k):
                        print(f"  - {part} {k}: {ix.get(k)} != {iy.get(k)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
