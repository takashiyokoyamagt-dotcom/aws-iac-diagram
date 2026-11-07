"""正規化（raw IR → normalized IR）の段階の組み立て。設計草案（docs/dev-notes/phase3-design-draft.md）の 4.1 の段階:

  0 読み込み（view.Index）→ 1 仮分類（classify.classify）→ 2 ノード（nodes.build_nodes）→ 確定（classify.finalize）
  → 4 入れ子（nesting.place。AZ のノードを含む）

**いまは段階 0〜2 と 4（フェーズ 3 の手順 3a・3b）。** 辺（段階 3）と、辺で決まる合成ノード（`external/internet`・`bedrock_model`）・
サブネットの `attrs.access` はまだ作らないので、出力は `edges` が空、R-* の分類が仮（`into` が空）で、`validate_ir.py` の検査はまだ
通らない（R-* の `into` は 1 つ以上が要る）。形は normalized IR と同じ（`nodes`・`edges`・`sources.<形式>.resources`・`evaluation`・
`diagnostics`）なので、正解 IR との比較（`aws-iac-diagram-workspace/tools/compare_ir.py`）には使える。

決定論（C5）: 出力の配列は `core/ir_norm.sort_lists` で決まった順にする（書き出しは `canonical_dump`）。集合の走査順に頼らない。
ここは標準ライブラリと core と normalize の各段階だけを使う。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from aws_iac_diagram.core import ir_norm
from aws_iac_diagram.core import rules as rules_mod
from aws_iac_diagram.core.rules import Rules
from aws_iac_diagram.normalize import classify, edges as edges_mod, nesting, nodes as nodes_mod, refs as refs_mod
from aws_iac_diagram.normalize.relations_base import Context
from aws_iac_diagram.normalize.view import Index

IR_VERSION = "1.0"
_NAME_BAD = re.compile(r"[^a-z0-9-]+")


def default_name(root: str) -> str:
    """`--name` が無いときの IR の名前: root の最後の要素（拡張子を除く）を小文字にし、英数字と `-` 以外を `-` にしたもの。"""
    last = [p for p in root.replace("\\", "/").split("/") if p]
    stem = last[-1].rsplit(".", 1)[0] if last else ""
    if stem in ("template", "root", "main") and len(last) > 1:  # CFN のテンプレートのファイル名は構成の名前でないことが多い
        stem = last[-2]
    name = _NAME_BAD.sub("-", stem.lower()).strip("-")
    return name or "ir"


def evaluation_of(raw: dict) -> dict:
    """normalized IR の `evaluation`（設計草案の 2.1）: TF は `var_files` だけを写し `vars` は `{}`（raw は値を持たない）。
    CFN は最上位のテンプレートのパラメータのうち値がスカラー（かスカラーの配列）のものと、条件。前提はそのまま写す。"""
    ev = raw.get("evaluation") or {}
    out: dict = {}
    if raw.get("format") == "tf":
        out["tf"] = {"var_files": list(ev.get("var_files") or []), "vars": {}}
    else:
        def scalar(v):
            return isinstance(v, (str, int, float, bool))
        params = {k: v for k, v in (ev.get("parameters") or {}).items()
                  if "/" not in k and "::" not in k and (scalar(v) or (isinstance(v, list) and all(scalar(x) for x in v)))}
        out["cfn"] = {"parameters": params, "conditions": {k: v for k, v in (ev.get("conditions") or {}).items()
                                                           if v is None or isinstance(v, bool)}}
    out["assumptions"] = list(ev.get("assumptions") or [])
    return out


@dataclass(frozen=True)
class Result:
    """正規化の結果: normalized IR と、参照の会計（refs.Entry の並び。CRITERIA の 1.8 を確かめるため）。"""
    ir: dict
    accounting: list


def run(raw: dict, rules: Rules | None = None, name: str | None = None) -> Result:
    """raw IR（検査済み。`stage: "raw"`）を正規化する（いまの段階は上の説明）。`rules` を省略すると SKILL の規則表。"""
    rules = rules or rules_mod.default()
    index = Index(raw)
    decisions = classify.classify(index, rules)
    node_by_address, diags = nodes_mod.build_nodes(index, decisions, rules)
    fin = classify.finalize(decisions, index, node_by_address, rules, edges=None)
    diags += fin.diagnostics
    er = edges_mod.build_edges(Context(index, fin.decisions, node_by_address, rules))
    final, more = classify.apply_edges(fin.decisions, rules, er.into, edges_mod.HANDLED)
    diags += more
    placed, place_diags = nesting.place(index, final, node_by_address, rules)
    placed += er.synthetic_nodes  # 基盤モデル（N-BEDROCK-MODEL。parent は null）
    diags += place_diags
    for n in placed:
        if n["id"] in er.access:
            n.setdefault("attrs", {})["access"] = er.access[n["id"]]
    accounting = refs_mod.account(index, final, rules, er.used_refs, {x: n["id"] for x, n in node_by_address.items()})
    diags += refs_mod.diagnostics(accounting)
    resources = []
    for res in index.resources:
        d = final[res.address]
        entry = {"address": res.address, "type": res.type, "file": res.file, **d.entry()}
        if d.cls == "drawn":
            entry["node"] = node_by_address[res.address]["id"]
        if res.via in ("module_summary", "module_blackbox"):
            entry["via"] = res.via
        resources.append(entry)
    ir = {
        "ir_version": IR_VERSION,
        "stage": "normalized",
        "name": name or default_name(index.root),
        "evaluation": evaluation_of(raw),
        "nodes": placed,
        "edges": er.edges,
        "sources": {index.fmt: {"root": index.root, "resources": resources, "edges": er.evidence}},
        "diagnostics": sorted(diags, key=lambda x: (x.get("address", ""), x["code"], x.get("path", ""), x["message"])),
    }
    return Result(ir_norm.sort_lists(ir), accounting)


def normalize(raw: dict, rules: Rules | None = None, name: str | None = None) -> dict:
    """raw IR を normalized IR にする（`run` の IR だけ）。"""
    return run(raw, rules, name).ir


def check(raw: dict, ir: dict) -> tuple[list[str], list[str]]:
    """正規化の出力の自分での検査（設計草案の 4.1 の段階 6 の一部）。(問題, 仮のままの分類) を返す。

    問題: 入力の全リソースが `sources.<形式>.resources` にちょうど 1 回ずつ現れない（網羅分類の漏れ・重複。X4）。
    仮のままの分類: `merged_into` で `into` が空のもの（R-* は辺の段階まで仮。統合先の見つからない M-* も）。スキーマ
    （`into` は 1 つ以上）に合わないので、検査に通る IR ではない。"""
    fmt = raw["format"]
    want = [r["address"] for r in raw.get("resources", [])]
    got = [r["address"] for r in ir["sources"][fmt]["resources"]]
    problems = []
    missing = sorted(set(want) - set(got))
    extra = sorted(set(got) - set(want))
    dup = sorted({a for a in got if got.count(a) > 1})
    if missing:
        problems.append(f"網羅分類に無い入力のリソース: {', '.join(missing)}")
    if extra:
        problems.append(f"入力に無いリソースが網羅分類にある: {', '.join(extra)}")
    if dup:
        problems.append(f"網羅分類に 2 回以上あるリソース: {', '.join(dup)}")
    provisional = [f"{r['address']}（{r['rule']}）" for r in ir["sources"][fmt]["resources"]
                   if r["class"] == "merged_into" and not r.get("into")]
    return problems, provisional
