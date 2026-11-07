"""参照の会計（CRITERIA の 1.8。docs/spec/rules/refs.md）。raw IR の `active` の参照を 1 本ずつ、次の 4 つの分類のどれか 1 つに入れる:

  1. `edge`    辺の根拠に使った（関係リソースのハンドラなどが、辺の候補の根拠にした参照）
  2. `nonode`  参照先にノードが無い（E-REF-NONODE。参照先が非表示 H-*、または辺に変換した（仮でない）関係リソース R-*）。
               refs.md のとおり、E-NOEDGE の表より先に当てる
  3. `noedge`  辺にしない参照（refs.toml の `[[noedge]]` を上から当てはめる。最初は E-NOEDGE-FROM-RULE（参照する側が R-*・M-*・H-* に
               分類された。M-ECS-TASKDEF・M-APIGW-AUTHORIZER を除く）、次から属性名で当てる: path の最後の要素の中立キー、当たらなければ
               最初の要素（SAM の `Policies` の中の参照は E-NOEDGE-ROLE、`vpc_config` の中は E-NOEDGE-PLACEMENT）。`["aws:SourceArn"]` の
               ような引用符つきの添字と、map の属性（環境変数・タグなど）の中のキーは属性名にしない。M-* から自分の統合先への
               参照（除外の規則 M-APIGW-AUTHORIZER を含む）も E-NOEDGE-FROM-RULE。DependsOn は、ほかより先に E-NOEDGE-DEPENDS
               （1.8 の数える対象の外）
  4. `unused`  どれにも当たらない（`NORM-UNUSED-REF`、info。address は参照の from、path は raw の path、message に to と attr）

分類は `Entry` の並び（raw の参照の順）で返すので、件数と内訳を確かめられる（`summary`）。辺の段階が育つ（手順 4b の E-*）と
`unused` は減る。

ここは標準ライブラリと core と normalize の view・classify・relations_base だけを使う。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from aws_iac_diagram.core.rules import Rules, neutral_key
from aws_iac_diagram.normalize.classify import Decision
from aws_iac_diagram.normalize.relations_base import path_keys, ref_key
from aws_iac_diagram.normalize.view import Index, is_depends_on

FROM_RULE = "E-NOEDGE-FROM-RULE"
DEPENDS = "E-NOEDGE-DEPENDS"
NONODE = "E-REF-NONODE"


@dataclass(frozen=True)
class Entry:
    ref: dict
    cls: str  # edge／noedge／nonode／unused
    rule: str | None  # noedge・nonode の規則 ID


# 値が map（キーを利用者が決める）の属性（中立キー）。その中のキー（環境変数の名前、タグの名前など）は属性名ではないので、
# E-NOEDGE の表の属性名と照合しない（環境変数 `SUBNET_ID` の参照は E-NOEDGE-PLACEMENT ではない。辺の規則 E-ENV-REF の材料）
MAP_ATTRS = frozenset({"variables", "tags", "tagsall", "defaultarguments", "requesttemplates", "requestparameters",
                       "environmentvariables", "parameters"})


def _keys(path: str) -> tuple[str, ...]:
    """属性名で当てるときに見る中立キー: path の最後の要素、次に最初の要素（属性の中の参照も、その属性の参照として扱う。
    SAM の `Policies[0].DynamoDBCrudPolicy.TableName`、`vpc_config[0].subnet_ids[0]`）。最後の要素が map の属性（`MAP_ATTRS`）の
    中のキーなら、最後の要素は使わない。"""
    keys = path_keys(path, quoted=False)
    if not keys:
        return ()
    last_is_map_key = len(keys) >= 2 and keys[-2] in MAP_ATTRS
    return (keys[0],) if last_is_map_key else (keys[-1], keys[0])


def account(index: Index, decisions: dict[str, Decision], rules: Rules, used: frozenset,
            node_of: dict[str, str] | None = None) -> list[Entry]:
    """raw IR の `active` の参照すべての分類（raw の順）。`decisions` は確定した分類、`used` は辺の根拠に使った参照、`node_of` は
    描くリソースの address → ノードの id（M-* から自分の統合先への参照を見分けるため）。"""
    node_of = node_of or {}
    attr_rules = [(r, {neutral_key(a) for a in r.attrs}) for r in rules.noedge if r.attrs]
    from_rule = next((r for r in rules.noedge if r.id == FROM_RULE), None)
    out = []
    for ref in [r for refs in index.refs_from.values() for r in refs]:
        out.append(_classify(ref, decisions, used, attr_rules, from_rule, node_of))
    order = {ref_key(r): i for i, r in enumerate(x for refs in index.refs_from.values() for x in refs)}
    return sorted(out, key=lambda e: (e.ref["from"], order[ref_key(e.ref)]))


def _nodes_of(address: str, decisions, node_of) -> set[str]:
    if address in node_of:
        return {node_of[address]}
    d = decisions.get(address)
    if d is not None and d.cls == "merged_into" and (d.rule or "").startswith("M-"):
        return set(d.into)
    return set()


def _classify(ref: dict, decisions, used, attr_rules, from_rule, node_of) -> Entry:
    if ref_key(ref) in used:
        return Entry(ref, "edge", None)
    if is_depends_on(ref):
        return Entry(ref, "noedge", DEPENDS)
    t = decisions.get(ref["to"])
    converted = t is not None and t.cls == "merged_into" and (t.rule or "").startswith("R-") and not t.provisional
    if t is not None and (t.cls == "hidden" or converted):
        return Entry(ref, "nonode", NONODE)  # refs.md: E-NOEDGE の表より先に当てる。R-* は辺に変換したものだけ
    d = decisions.get(ref["from"])
    if (from_rule is not None and d is not None and d.cls in from_rule.from_class
            and (d.rule or "") not in from_rule.except_rules):
        return Entry(ref, "noedge", FROM_RULE)
    # M-* から自分の統合先への参照（オーソライザー → その API など）は、統合先そのものへの参照。辺にしない（自分への辺になる。
    # edges.toml の E-AUTHORIZER の文）ので、参照する側が統合されたものとして E-NOEDGE-FROM-RULE
    if (from_rule is not None and d is not None and d.cls == "merged_into" and (d.rule or "").startswith("M-")
            and _nodes_of(ref["to"], decisions, node_of) & set(d.into)):
        return Entry(ref, "noedge", FROM_RULE)
    for key in _keys(ref["path"]):
        for row, keys in attr_rules:
            if key in keys:
                return Entry(ref, "noedge", row.id)
    return Entry(ref, "unused", None)


def diagnostics(entries: list[Entry]) -> list[dict]:
    """`unused` の参照の診断（`NORM-UNUSED-REF`、info）。"""
    return [{"level": "info", "code": "NORM-UNUSED-REF", "address": e.ref["from"], "path": e.ref["path"],
             "message": f"辺にも入れ子にも使わなかった参照（to: {e.ref['to']}、attr: {e.ref.get('attr')}）"}
            for e in entries if e.cls == "unused"]


def summary(entries: list[Entry]) -> dict[str, int]:
    """分類ごとの件数（`noedge`・`nonode` は規則 ID ごと）。"""
    c = Counter(e.cls if e.cls in ("edge", "unused") else e.rule for e in entries)
    return dict(sorted(c.items()))
