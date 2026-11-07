"""正規化（raw IR → normalized IR）の段階の組み立て。設計草案（docs/dev-notes/phase3-design-draft.md）の 4.1 の段階:

  0 読み込み（view.Index）→ 1 仮分類（classify.classify）→ 2 ノード（nodes.build_nodes）→ 確定（classify.finalize）

**いまは段階 0〜2 だけ（フェーズ 3 の手順 3a）。** 辺（段階 3）・入れ子（段階 4）・合成ノードはまだ作らないので、出力は
`edges` が空、ノードの `parent` が None、R-* の分類が仮（`into` が空）で、`validate_ir.py` の検査はまだ通らない（R-* の `into` は
1 つ以上が要る）。形は normalized IR と同じ（`nodes`・`edges`・`sources.<形式>.resources`・`evaluation`・`diagnostics`）なので、
正解 IR との比較（`aws-iac-diagram-workspace/tools/compare_ir.py`）には使える。

決定論（C5）: 出力の配列は `core/ir_norm.sort_lists` で決まった順にする（書き出しは `canonical_dump`）。集合の走査順に頼らない。
ここは標準ライブラリと core と normalize の各段階だけを使う。
"""
from __future__ import annotations

import re

from aws_iac_diagram.core import ir_norm
from aws_iac_diagram.core import rules as rules_mod
from aws_iac_diagram.core.rules import Rules
from aws_iac_diagram.normalize import classify, nodes as nodes_mod
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


def normalize(raw: dict, rules: Rules | None = None, name: str | None = None) -> dict:
    """raw IR（検査済み。`stage: "raw"`）を normalized IR にする（いまは段階 0〜2。上の説明）。`rules` を省略すると SKILL の規則表。"""
    rules = rules or rules_mod.default()
    index = Index(raw)
    decisions = classify.classify(index, rules)
    node_by_address, diags = nodes_mod.build_nodes(index, decisions, rules)
    fin = classify.finalize(decisions, index, node_by_address, rules, edges=None)
    diags += fin.diagnostics
    resources = []
    for res in index.resources:
        d = fin.decisions[res.address]
        entry = {"address": res.address, "type": res.type, "file": res.file, **d.entry()}
        if d.cls == "drawn":
            entry["node"] = node_by_address[res.address]["id"]
        if res.via in ("module_summary", "module_blackbox"):
            entry["via"] = res.via
        resources.append(entry)
    unique_nodes = {n["id"]: n for n in node_by_address.values()}
    ir = {
        "ir_version": IR_VERSION,
        "stage": "normalized",
        "name": name or default_name(index.root),
        "evaluation": evaluation_of(raw),
        "nodes": list(unique_nodes.values()),
        "edges": [],
        "sources": {index.fmt: {"root": index.root, "resources": resources, "edges": []}},
        "diagnostics": sorted(diags, key=lambda x: (x.get("address", ""), x["code"], x["message"])),
    }
    return ir_norm.sort_lists(ir)
