"""正規化の段階 3（辺）: 関係リソース（R-*）のハンドラを呼び、辺の候補を 1 組 1 本にまとめる（E-MERGE。ir-schema の 3 章）。

- 作る辺: 関係リソースの規則（`HANDLED`。手順 4a）、属性の参照から作る E-*（attr_edges.py）、E-IAM と E-IAM-SUPPRESS（iam.py）、
  合成ノード N-BEDROCK-MODEL（手順 4b）。R-SG・N-EXT-INTERNET はまだ（手順 5）。
- 端点が黒箱のモジュール（型 `module`）の候補は、どの規則でも `inferred`・`request` にする（ir-schema の 2 章。中身が分からない）。
- まとめ方（edges.toml の `[[merge_priority]]` と `confidence_order`）: 同じ順序付きの組の候補は 1 本にし、`rules` はすべての規則、
  `evidence` はすべての根拠。`kind` は優先順の高い規則の候補のもの（R-LAMBDA-PERMISSION などの「既存の辺に従う」候補は、ほかの
  候補が無いときだけ自分の kind）。同じ規則の中で kind が違えば `[[iam_action_kind]]` の行の順（E-IAM の first_row_wins）。
  `label` は、優先順の高い規則から見て最初の空でないもの（同じ規則から複数のラベルが出たら辞書順に `, ` でつなぐ）。`confidence` は
  強い方。自己ループは作らない。
- 結果: 辺（canonical 部）、辺の根拠（`sources.<形式>.edges`）、関係リソースの address → 統合された辺の id（分類の確定に使う）、
  辺の根拠に使った参照（参照の会計に使う）、サブネットの `access`。

ここは標準ライブラリと core と normalize の view・classify・relations_* だけを使う。
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, replace

from aws_iac_diagram.core.rules import Rules
from aws_iac_diagram.normalize import attr_edges, iam, relations_api, relations_events, relations_lb, relations_route
from aws_iac_diagram.normalize.relations_base import Candidate, Context

MODULE = "module"

# この手順でハンドラを持つ関係リソースの規則（ここに無い R-* は、分類を仮のまま残す）
HANDLED = frozenset({
    "R-ROUTE", "R-VPCE-GATEWAY", "R-LB-LISTENER", "R-LB-TG", "R-APIGW-HTTP", "R-APIGW-REST", "R-LAMBDA-PERMISSION",
    "R-LAMBDA-ESM", "R-SNS-SUBSCRIPTION", "R-SQS-QUEUE-POLICY", "R-S3-NOTIFICATION", "R-BEDROCK-DATA-SOURCE",
    "R-EVENTS-TARGET", "R-SNS-TOPIC-POLICY", "R-GLUE-TRIGGER",
})


@dataclass(frozen=True)
class EdgeResult:
    edges: list[dict]
    evidence: list[dict]
    into: dict[str, list[str]]  # 関係リソースの address → 辺の id
    used_refs: frozenset  # 辺の根拠に使った参照 (from, path, to)
    access: dict[str, str]  # サブネットのノード → public／private
    synthetic_nodes: list[dict]  # 辺の段階で作った合成ノード（N-BEDROCK-MODEL）


def _rank(rules: Rules, rule: str) -> int:
    for row in rules.merge_priority:
        if any(fnmatch.fnmatchcase(rule, p) for p in row.rules):
            return row.rank
    return len(rules.merge_priority) + 1


def _kind_order(rules: Rules, kind: str) -> int:
    """同じ規則の中で kind が違うときの順: `[[iam_action_kind]]` の行の順（上が先。first_row_wins）。表に無い kind は後ろ。"""
    order = [r.kind for r in rules.iam_action_kinds]
    return order.index(kind) if kind in order else len(order)


def blackbox(cands: list[Candidate], nodes_type) -> list[Candidate]:
    """端点が黒箱のモジュールの候補は inferred・request にする（ir-schema の 2 章）。"""
    out = []
    for c in cands:
        if MODULE in (nodes_type(c.frm), nodes_type(c.to)):
            c = replace(c, kind="request" if c.kind else None, weak_kind="request" if c.weak_kind else None, confidence="inferred")
        out.append(c)
    return out


def merge(cands: list[Candidate], rules: Rules) -> EdgeResult:
    """候補を 1 組 1 本にまとめる。"""
    order = list(rules.edges_options.get("confidence_order", ("confirmed", "derived", "inferred")))
    groups: dict[tuple[str, str], list[Candidate]] = {}
    for c in cands:
        if c.frm != c.to:
            groups.setdefault((c.frm, c.to), []).append(c)
    edges, evidence, into, used = [], [], {}, set()
    for (frm, to), cs in sorted(groups.items()):
        eid = f"{frm}->{to}"
        strong = sorted((_rank(rules, c.rule), c.rule, _kind_order(rules, c.kind), c.kind) for c in cs if c.kind)
        weak = sorted((_rank(rules, c.rule), c.rule, _kind_order(rules, c.weak_kind), c.weak_kind) for c in cs if c.weak_kind)
        kind = (strong or weak)[0][3]
        # ラベル: 優先順の高い規則から見て最初の空でないもの。同じ規則から複数のラベルが出たら、重複を除いて辞書順に `, ` でつなぐ
        labelled = sorted((_rank(rules, c.rule), c.rule, c.label) for c in cs if c.label)
        best = labelled[0][:2] if labelled else None
        label = ", ".join(sorted({lab for r, rule, lab in labelled if (r, rule) == best}))
        confidence = min((c.confidence for c in cs), key=order.index)
        edges.append({"id": eid, "from": frm, "to": to, "kind": kind, "label": label, "confidence": confidence})
        evidence.append({"edge": eid, "rules": sorted({c.rule for c in cs}), "evidence": sorted({e for c in cs for e in c.evidence})})
        for c in cs:
            used.update(c.refs)
            for m in c.members:
                into.setdefault(m, set()).add(eid)
    return EdgeResult(edges, evidence, {a: sorted(v) for a, v in sorted(into.items())}, frozenset(used), {}, [])


def build_edges(ctx: Context) -> EdgeResult:
    """関係リソースのハンドラをすべて呼んで、辺をまとめる。"""
    route, access = relations_route.route_candidates(ctx)
    models: dict[str, dict] = {}
    cands = route + relations_lb.lb_candidates(ctx) + relations_api.api_candidates(ctx) + relations_events.event_candidates(ctx)
    cands += attr_edges.attr_candidates(ctx, models) + iam.iam_candidates(ctx, models)
    cands = blackbox(iam.suppress(cands), ctx.node_type)
    r = merge(cands, ctx.rules)
    used_models = {e["to"] for e in r.edges} | {e["from"] for e in r.edges}
    return EdgeResult(r.edges, r.evidence, r.into, r.used_refs, access, [models[m] for m in sorted(models) if m in used_models])
