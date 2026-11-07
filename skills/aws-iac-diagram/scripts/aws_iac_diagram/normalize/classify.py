"""正規化の段階 1: 網羅分類（A6）の仮分類と、辺・ノードが決まった後の確定（`finalize`）。

入力のリソース 1 件に、分類を 1 つだけ付ける（漏れ 0・重複 0 が構造で決まる。CRITERIA の X4）。順序（設計草案の 4.1）:

1. `enabled: false`（count が 0、CFN の `Condition` が偽）→ `hidden`／`H-COND-FALSE`（型より先）。
2. 黒箱のモジュール（`via: module_blackbox`）→ source が IAM だけのモジュール（`core/module_sources.iam_only`）なら
   `hidden`／`H-IAM`、それ以外は描く（型 `module`。ir-schema の 2 章）。
3. TF の `data` → H-IAM の `tf_data` の型なら `H-IAM`。`data = true` の描く型で、図に出るもの（描くリソース・描く data・
   関係リソース R-*・描くノードに統合される M-*）から参照されていれば描く（既存のノード。ir-schema の 7.4、設計草案 8 章の 3 の (c)）。
   それ以外は `H-DATA`。data かは address で決める（`view.Resource.is_data`）。
4. 型の表（`data/rules/types/`・`relations.toml`）を `when` つきで引く。描く型 → `drawn`、M-* → `merged_into`（仮）、
   R-* → `merged_into`（仮）、H-* → `hidden`。
5. どの行にも当たらない: TF の awscc の型は同じ名前の CFN の型として引き直す。AWS 以外のプロバイダの型は `H-NONAWS`。
   それでも無ければ `unknown`。

**仮分類と確定の分離（設計草案の 4.1）:** M-* は統合先のノード、R-* は辺ができたかで決まるので、段階 1 では「仮」
（`provisional`）にしておき、`finalize` の 1 か所で確定する。

- M-*: 統合先（`into.node_types` の描くノード）を、主の属性の参照、DependsOn 以外の参照、規則 ID ごとの名前の一致、
  統合済みの M-* を 1 段ずつ（幅優先）、自分が宣言した DependsOn（候補が 1 つのときだけ。`NORM-MERGE-DEPENDS-ON`、info）の順で
  探す（詳しくは merge.py）。見つからなければ `hidden`／`H-NO-TARGET` にし、`NORM-MERGE-TARGET`（warn）も出す（見落としに
  気づけるように）。
- R-*: `edges`（関係リソースの address → それが作った辺の id）を渡されたときだけ確定する。辺があれば `merged_into`（into は辺）、
  無ければ規則の `fallback`（`R-SG` → `H-SG-NOEDGE`、`R-ROUTE` → `H-RT-NOROUTE` など）。fallback の無い規則は
  `H-RELATION-NOEDGE` にし、`NORM-RELATION-NOEDGE`（warn）も出す。`edges=None` で呼ぶと R-* は仮のまま（into は空）で、
  辺の段階の後に `apply_edges` で確定する（build.py）。

ここは標準ライブラリと core と normalize の view・merge だけを使う。
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from aws_iac_diagram.core import module_sources
from aws_iac_diagram.core.rules import Row, Rules
from aws_iac_diagram.normalize import merge, view
from aws_iac_diagram.normalize.view import Index, Resource

COND_FALSE = "H-COND-FALSE"
IAM = "H-IAM"
NONAWS = "H-NONAWS"
NO_TARGET = "H-NO-TARGET"
RELATION_NOEDGE = "H-RELATION-NOEDGE"
MODULE_TYPE = "module"
BLACKBOX = "module_blackbox"
AWS_PROVIDERS = ("aws", "awscc")


@dataclass(frozen=True)
class Decision:
    """1 件のリソースの分類。`cls` は drawn／merged_into／hidden／unknown。描くものは `type_id`（正規の型名）、統合・非表示は
    `rule`（規則 ID）。`into` は統合先（ノードの id か辺の id）。`provisional` は段階 1 の仮のもの（finalize で確定する）。"""
    cls: str
    rule: str | None = None
    type_id: str | None = None
    into: tuple[str, ...] = ()
    provisional: bool = False

    def entry(self) -> dict:
        """`sources.<形式>.resources` の分類の部分（address・type・file・via は呼ぶ側が足す。drawn の node も呼ぶ側）。"""
        if self.cls == "merged_into":
            return {"class": self.cls, "rule": self.rule, "into": sorted(self.into)}
        if self.cls == "hidden":
            return {"class": self.cls, "rule": self.rule}
        return {"class": self.cls}


# ------------------------------------------------------------------ when

def when_holds(row: Row, res: Resource, as_type: str | None = None) -> bool:
    """行の `when` が、このリソースで成り立つか（`when` の無い行は常に成り立つ）。`as_type` は引いた入力の型（awscc を CFN の型として
    引いたときはその CFN の型）。属性の値が無い・印（`$unknown` など）なら `default` を使い、`default` も無ければ成り立たない。"""
    when = row.get("when")
    if when is None:
        return True
    t = as_type or res.type
    if "types" in when and t not in when["types"]:
        return True  # 条件が効かない型（行のほかの型）
    fmt = "cfn" if t.startswith("AWS::") else "tf"
    if "via" in when and res.via not in when["via"]:
        return False
    if "via_not" in when and res.via in when["via_not"]:
        return False
    if "prop" in when:
        name = when["prop"].get(fmt)
        if name is None:
            return False  # この形式の属性名が書かれていない
        v = view.plain(res.get(name))
        if v is None or isinstance(v, (dict, list)):
            v = when.get("default")
        if v is None or str(v) not in when["in"]:
            return False
    return True


def _rows(rules: Rules, res: Resource, as_type: str) -> list[Row]:
    return [r for r in rules.rows_for_input_type(as_type) if when_holds(r, res, as_type)]


def _from_row(row: Row) -> Decision:
    if row.table == "relation":
        return Decision("merged_into", rule=row.id, provisional=True)
    if row.cls == "drawn":
        return Decision("drawn", type_id=row.id)
    if row.cls == "merged_into":
        return Decision("merged_into", rule=row.id, provisional=True)
    return Decision("hidden", rule=row.id)


# ------------------------------------------------------------------ 段階 1

def _hidden_rule(rules: Rules, flag: str) -> str:
    return next(r.id for r in rules.hidden if r.get(flag))


def _data_iam_rule(rules: Rules, tf_type: str) -> str | None:
    return next((r.id for r in rules.hidden if tf_type in r.get("tf_data", ())), None)


def classify_one(rules: Rules, res: Resource) -> tuple[Decision, bool]:
    """1 件の仮分類と、「`data = true` の描く型の data で、参照されていれば描く」候補か。"""
    if res.enabled is False:
        return Decision("hidden", rule=COND_FALSE), False
    if res.via == BLACKBOX:
        if res.fmt == "tf" and res.source and module_sources.iam_only(res.source):
            return Decision("hidden", rule=IAM), False
        return Decision("drawn", type_id=MODULE_TYPE), False
    if res.is_data:
        iam = _data_iam_rule(rules, res.type)
        if iam:
            return Decision("hidden", rule=iam), False
        drawn = [r for r in _rows(rules, res, res.type) if r.table == "type" and r.cls == "drawn" and r.get("data")]
        if drawn:
            return Decision("drawn", type_id=drawn[0].id), True
        return Decision("hidden", rule=_hidden_rule(rules, "data_block")), False
    rows = _rows(rules, res, res.type)
    if not rows and res.fmt == "tf":
        cfn_type = rules.awscc_as_cfn(res.type)
        if cfn_type:
            rows = _rows(rules, res, cfn_type)
        elif res.type.split("_", 1)[0] not in AWS_PROVIDERS:
            return Decision("hidden", rule=NONAWS), False
    if not rows:
        return Decision("unknown"), False
    # 規則表の検査（core/rules.py）が、同時に成り立つ行が 2 つ以上無いことを保証している
    return _from_row(rows[0]), False


def classify(index: Index, rules: Rules) -> dict[str, Decision]:
    """段階 1: すべてのリソースの仮分類（address → Decision。raw の順）。"""
    out: dict[str, Decision] = {}
    data_candidates: list[str] = []
    for res in index.resources:
        d, candidate = classify_one(rules, res)
        out[res.address] = d
        if candidate:
            data_candidates.append(res.address)
    # 既存のインフラを指す data: 図に出るものから参照されていれば描く。されていなければ H-DATA
    drawn_data = _used_data(index, rules, out, data_candidates)
    h_data = _hidden_rule(rules, "data_block") if data_candidates else ""
    for a in data_candidates:
        if a not in drawn_data:
            out[a] = Decision("hidden", rule=h_data)
    return out


def _used_data(index: Index, rules: Rules, out: dict[str, Decision], candidates: list[str]) -> set[str]:
    """描く data（`data = true` の型の data のうち、図に出るものから DependsOn 以外で参照されるもの）。参照した側に数えるのは:
    描くリソース（data でないもの、または描くと決まった data。data.aws_subnet → data.aws_vpc のように、変わらなくなるまで広げる）、
    関係リソース（R-*。辺の材料になる。T09 の `aws_bedrockagent_data_source`）、描くノードに統合される M-*（統合先の型の描くリソースを
    DependsOn 以外で参照し合うもの）。IAM などの非表示のリソースからの参照は数えない。"""
    cand = set(candidates)
    used: set[str] = set()

    def is_drawn(a: str) -> bool:
        return out[a].cls == "drawn" and (a not in cand or a in used)

    def counts(f: str, target: str) -> bool:
        d = out.get(f)
        if d is None:
            return False
        if d.cls == "drawn":
            return is_drawn(f)
        if d.cls == "merged_into" and d.rule.startswith("R-"):
            return True
        if d.cls == "merged_into" and d.rule.startswith("M-"):
            node_types = rules.row(d.rule).into["node_types"]
            return any(n != target and is_drawn(n) and out[n].type_id in node_types for n in index.neighbors(f))
        return False

    changed = True
    while changed:
        changed = False
        for a in candidates:
            if a not in used and any(counts(f, a) for f in index.referrers(a)):
                used.add(a)
                changed = True
    return used


# ------------------------------------------------------------------ 確定

@dataclass(frozen=True)
class Finalized:
    decisions: dict[str, Decision]
    diagnostics: list[dict]


def _resolve_merges(out: dict[str, Decision], ctx: merge.Context, diags: list[dict]) -> None:
    """M-* の統合先を探して、out を確定した Decision に書き換える（探し方の順は merge.py の説明）。"""
    pending: dict[str, tuple[str, ...]] = {}
    found_by: dict[str, set[str]] = {}
    for a in sorted(out):
        d = out[a]
        if d.cls != "merged_into" or not d.provisional or not d.rule.startswith("M-"):
            continue
        node_types = tuple(ctx.rules.row(d.rule).into["node_types"])
        found = merge.direct_targets(ctx, a, d.rule, node_types)
        if found:
            found_by[a] = found
        else:
            pending[a] = node_types
    for a, found in found_by.items():
        out[a] = _confirmed(out[a], found, a, diags)
    # 統合済みの M-* を 1 段ずつたどる（幅優先。各段は前の段までに確定したものだけを見るので、address の順に依らない）
    while pending:
        confirmed = {b: d for b, d in out.items() if d.cls == "merged_into" and d.rule.startswith("M-") and not d.provisional}
        step: dict[str, set[str]] = {}
        for a in sorted(pending):
            found: set[str] = set()
            for b in sorted(ctx.outgoing(a) | ctx.incoming(a)):
                if b in confirmed:
                    found |= {x for x in confirmed[b].into if x.split("/", 1)[0] in pending[a]}
            if found:
                step[a] = found
        if not step:
            break
        for a, found in step.items():
            out[a] = _confirmed(out[a], found, a, diags)
            del pending[a]
    # 最後の手: 統合されるもの自身が宣言した DependsOn の先で、候補がちょうど 1 つのときだけ
    for a in sorted(pending):
        found = ctx.drawn_of(ctx.depends_on(a), pending[a])
        if len(found) == 1:
            out[a] = replace(out[a], into=tuple(found), provisional=False)
            diags.append({"level": "info", "code": "NORM-MERGE-DEPENDS-ON", "address": a,
                          "message": f"{out[a].rule} の統合先を、参照が無いので DependsOn の先 {next(iter(found))} にした"})
        else:
            diags.append({"level": "warn", "code": "NORM-MERGE-TARGET", "address": a,
                          "message": f"{out[a].rule} の統合先（{'・'.join(pending[a])}）が見つからないので、{NO_TARGET} にした"})
            out[a] = Decision("hidden", rule=NO_TARGET)


def _confirmed(d: Decision, found: set[str], address: str, diags: list[dict]) -> Decision:
    """統合先を決めた Decision。親が 1 つの規則（merge.PRIMARY_ATTRS）で 2 つ以上に当たれば、決まった順の最初の 1 つにして warn。"""
    targets = sorted(found)
    if d.rule in merge.PRIMARY_ATTRS and len(targets) > 1:
        diags.append({"level": "warn", "code": "NORM-MERGE-AMBIGUOUS", "address": address,
                      "message": f"{d.rule} の統合先の候補が {len(targets)} つある（{'・'.join(targets)}）。{targets[0]} にした"})
        targets = targets[:1]
    return replace(d, into=tuple(targets), provisional=False)


def finalize(decisions: dict[str, Decision], index: Index, nodes: dict[str, dict], rules: Rules,
             edges: dict[str, list[str]] | None = None) -> Finalized:
    """仮分類を確定する。`nodes` は描くリソースの address → ノード（段階 2 の結果）。`edges` は関係リソースの address → それが
    作った辺の id（段階 3 の結果。None なら R-* は仮のまま）。"""
    out = dict(decisions)
    diags: list[dict] = []
    ctx = merge.Context(index=index, decisions=decisions, node_of={a: n["id"] for a, n in nodes.items()}, nodes=nodes, rules=rules)
    _resolve_merges(out, ctx, diags)
    if edges is not None:
        out, more = apply_edges(out, rules, edges)
        diags += more
    return Finalized(out, diags)


def apply_edges(decisions: dict[str, Decision], rules: Rules, edges: dict[str, list[str]],
                handled: frozenset[str] | None = None) -> tuple[dict[str, Decision], list[dict]]:
    """関係リソース（R-*）の分類を、辺の段階の結果で確定する。`edges` は関係リソースの address → 統合された辺の id、`handled` は
    辺の段階がハンドラを持つ規則（None ならすべて。ほかの R-* は仮のまま残す）。

    辺があれば `merged_into`（into は辺）。無ければ規則の `fallback`（H-SG-NOEDGE・H-RT-NOROUTE・H-IAM）。fallback の無い規則
    （R-LB-LISTENER・R-GLUE-TRIGGER など）は `H-RELATION-NOEDGE` にし、`NORM-RELATION-NOEDGE`（warn）も出す（ir-schema の 10 章）。"""
    out = dict(decisions)
    diags: list[dict] = []
    for a in sorted(out):
        d = out[a]
        if not (d.cls == "merged_into" and d.provisional and d.rule.startswith("R-")) or (handled is not None and d.rule not in handled):
            continue
        got = edges.get(a) or []
        fallback = rules.row(d.rule).get("fallback")
        if got:
            out[a] = replace(d, into=tuple(sorted(set(got))), provisional=False)
        elif fallback:
            out[a] = Decision("hidden", rule=fallback)
        else:
            out[a] = Decision("hidden", rule=RELATION_NOEDGE)
            diags.append({"level": "warn", "code": "NORM-RELATION-NOEDGE", "address": a,
                          "message": f"{d.rule} の関係リソースから辺ができず、規則に fallback も無いので、{RELATION_NOEDGE} にした"})
    return out, diags
