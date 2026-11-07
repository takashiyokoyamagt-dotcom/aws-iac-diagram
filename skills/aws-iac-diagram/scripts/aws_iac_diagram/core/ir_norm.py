"""正規化後の IR（stage "normalized"）の出力の形（C5）と、TF 版・CFN 版の比較に使う部分。

`validate_ir.py`（出力の形の検査と `--same-canonical`）が使い、フェーズ 3 の `normalize/` の書き出しも同じ関数を使う（書き方を 2 か所に持たない）。
形は docs/spec/ir-schema/ の 6 章: `nodes` は id 順、`sources.*.resources` は address 順、`sources.*.edges` は edge 順、
`spans`・`into`・`rules`・`evidence` は文字列順、キーは辞書順、インデント 2、末尾に改行 1 つ。

ノードの id の key（K-NAME。ir-schema の 2 章）の作り方（`key_of`・`logical_name`・`split_tf_address`）もここに置く。正規化（normalize/names.py）が
id を作り、`validate_ir.py` が id を確かめるときに、同じ関数を使う（作り方を 2 か所に持たない）。

標準ライブラリだけを使う（core の決まり）。
"""
from __future__ import annotations

import json
import re

_KEY_BAD = re.compile(r"[^a-z0-9._-]")
_KEY_HEAD = re.compile(r"^[^a-z0-9]+")
_INDEX = re.compile(r'\[(?:"((?:[^"\\]|\\.)*)"|([^\]]*))\]')


def key_of(name: str) -> str:
    """名前 → id の key（小文字にして `[a-z0-9._-]` 以外を `-`）。ir.schema.json の id の形（先頭は英数字）に合わないときは、
    先頭の記号を除く（`.hidden` → `hidden`）。全部が記号なら `-` を返す（呼ぶ側が次の候補に落とす）。"""
    head = _KEY_HEAD.sub("", _KEY_BAD.sub("-", name.lower()))
    return head or "-"


def split_tf_address(address: str) -> list[str]:
    """TF の address を `.` で分ける（`["…"]` の中の `.` では分けない）。"""
    parts, buf, depth, quoted = [], "", 0, False
    for ch in address:
        if ch == '"' and depth:
            quoted = not quoted
        elif ch == "[" and not quoted:
            depth += 1
        elif ch == "]" and not quoted:
            depth -= 1
        if ch == "." and not depth and not quoted:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return parts


def _index_suffix(segment: str) -> str:
    """`private[0]` → `private-0`、`interface["ssm"]` → `interface-ssm`、`x[*]` → `x`（×N はインデックスを付けない）。"""
    def sub(m: re.Match) -> str:
        v = m.group(1) if m.group(1) is not None else m.group(2)
        return "" if v == "*" else f"-{v}"
    return _INDEX.sub(sub, segment)


def logical_name(address: str, fmt: str) -> str:
    """論理名（B3 の 3 番目。K-NAME）。TF: モジュールのパスを `.` でつないだもの + リソース名（黒箱のモジュールの呼び出しは
    モジュールのパス。`module.eks.module.kms` → `eks.kms`）。CFN: `Stack::Parent/Child` → `Stack.Parent.Child`（Fn::ForEach の
    決まらないひな形の `*` は除く）。"""
    if fmt == "tf":
        parts = split_tf_address(address)
        mods: list[str] = []
        i = 0
        while i + 1 < len(parts) and parts[i] == "module":
            mods.append(_index_suffix(parts[i + 1]))
            i += 2
        rest = parts[i:]
        if rest and rest[0] == "data":
            rest = rest[1:]
        if not rest:
            return ".".join(mods)
        return ".".join([*mods, _index_suffix(rest[-1])])
    return ".".join(p.replace("*", "") for p in address.replace("::", "/").split("/") if p.replace("*", ""))


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
