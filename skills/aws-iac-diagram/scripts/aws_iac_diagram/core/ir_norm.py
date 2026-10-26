"""正規化後の IR（stage "normalized"）の出力の形（C5）と、TF 版・CFN 版の比較に使う部分。

`validate_ir.py`（出力の形の検査と `--same-canonical`）が使い、フェーズ 3 の `normalize/` の書き出しも同じ関数を使う（書き方を 2 か所に持たない）。
形は docs/spec/ir-schema/ の 6 章: `nodes` は id 順、`sources.*.resources` は address 順、`sources.*.edges` は edge 順、
`spans`・`into`・`rules`・`evidence` は文字列順、キーは辞書順、インデント 2、末尾に改行 1 つ。

標準ライブラリだけを使う（core の決まり）。
"""
from __future__ import annotations

import json


def sort_lists(ir: dict) -> dict:
    """配列を決まった順に並べたコピーを返す（元の ir は変えない）。"""
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
    """出力の正規の文字列（キーの辞書順、インデント 2、末尾の改行 1 つ）。"""
    return json.dumps(sort_lists(ir), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def canonical_part(ir: dict) -> dict:
    """TF 版と CFN 版の比較に使う部分（note を除く nodes と edges）。"""
    ir = sort_lists(ir)
    strip = lambda d: {k: v for k, v in d.items() if k != "note"}  # noqa: E731
    return {"nodes": [strip(n) for n in ir["nodes"]], "edges": [strip(e) for e in ir["edges"]]}
