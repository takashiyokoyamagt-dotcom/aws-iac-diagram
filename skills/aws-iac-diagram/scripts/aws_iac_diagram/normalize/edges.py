"""正規化の段階 3（辺）: 関係リソース（R-*）のハンドラを呼び、辺の候補を 1 組 1 本にまとめる（E-MERGE。ir-schema の 3 章）。

- いま作る辺は、関係リソースの規則（`HANDLED`）からのものだけ（フェーズ 3 の手順 4a）。R-SG・N-EXT-INTERNET（手順 5）と、
  属性の参照から作る E-*（E-ENV-REF・E-KB-STORAGE など）・E-IAM（手順 4b）はまだ。
- まとめ方（edges.toml の `[[merge_priority]]` と `confidence_order`）: 同じ順序付きの組の候補は 1 本にし、`rules` はすべての規則、
  `evidence` はすべての根拠。`kind` は優先順の高い規則の候補のもの（R-LAMBDA-PERMISSION などの「既存の辺に従う」候補は、ほかの
  候補が無いときだけ自分の kind）。`label` は、ラベルを持つ候補のうち優先順のいちばん高いものたち（同じ順位が複数なら、異なる
  ラベルを辞書順に `, ` でつなぐ）。`confidence` は強い方。自己ループは作らない。
- 結果: 辺（canonical 部）、辺の根拠（`sources.<形式>.edges`）、関係リソースの address → 統合された辺の id（分類の確定に使う）、
  辺の根拠に使った参照（参照の会計に使う）、サブネットの `access`。

ここは標準ライブラリと core と normalize の view・classify・relations_* だけを使う。
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from aws_iac_diagram.core.rules import Rules
from aws_iac_diagram.normalize import relations_api, relations_events, relations_lb, relations_route
from aws_iac_diagram.normalize.relations_base import Candidate, Context

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


def _rank(rules: Rules, rule: str) -> int:
    for row in rules.merge_priority:
        if any(fnmatch.fnmatchcase(rule, p) for p in row.rules):
            return row.rank
    return len(rules.merge_priority) + 1


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
        strong = sorted((_rank(rules, c.rule), c.rule, c.kind) for c in cs if c.kind)
        weak = sorted((_rank(rules, c.rule), c.rule, c.weak_kind) for c in cs if c.weak_kind)
        kind = (strong or weak)[0][2]
        labelled = [(_rank(rules, c.rule), c.label) for c in cs if c.label]
        best = min((r for r, _ in labelled), default=None)
        label = ", ".join(sorted({lab for r, lab in labelled if r == best}))
        confidence = min((c.confidence for c in cs), key=order.index)
        edges.append({"id": eid, "from": frm, "to": to, "kind": kind, "label": label, "confidence": confidence})
        evidence.append({"edge": eid, "rules": sorted({c.rule for c in cs}), "evidence": sorted({e for c in cs for e in c.evidence})})
        for c in cs:
            used.update(c.refs)
            for m in c.members:
                into.setdefault(m, set()).add(eid)
    return EdgeResult(edges, evidence, {a: sorted(v) for a, v in sorted(into.items())}, frozenset(used), {})


def build_edges(ctx: Context) -> EdgeResult:
    """関係リソースのハンドラをすべて呼んで、辺をまとめる。"""
    route, access = relations_route.route_candidates(ctx)
    cands = route + relations_lb.lb_candidates(ctx) + relations_api.api_candidates(ctx) + relations_events.event_candidates(ctx)
    r = merge(cands, ctx.rules)
    return EdgeResult(r.edges, r.evidence, r.into, r.used_refs, access)
