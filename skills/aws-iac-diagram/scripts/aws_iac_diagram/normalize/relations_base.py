"""関係リソース（R-*）のハンドラが共有する部品: 辺の候補（`Candidate`）と、参照・ノードを引く文脈（`Context`）。

ハンドラ（`relations_route.py`・`relations_lb.py`・`relations_api.py`・`relations_events.py`）は、確定した分類（M-* の統合先が
決まったもの）とノードを見て、辺の候補を返すだけ。候補を 1 組 1 本にまとめるのは `edges.py`（E-MERGE）。

- 辺の向きはデータ（要求）の流れ（A2）。端点はノードの id。参照先が M-* で統合されたリソースなら、統合先のノードにする
  （E-REF-NONODE の表の「統合先のノードへの参照として扱う」）。
- 根拠（`evidence`）は `<raw の参照の from>.<raw の参照の path>` で始める（ir-schema の 4 章。CRITERIA の 1.8 の照合に使う）。
  参照の無い根拠（SAM の暗黙の API など）は `<address>.<位置>` の形にする。
- 根拠に使った参照は候補の `refs` に入れる（辺として残った候補の参照を、参照の会計 `refs.py` が「辺の根拠」に数える）。
- 参照の位置は中立キーの並び（`path_keys`。CFN の先頭の `Properties.` と添字を除き、小文字にして `_` を除く）で探す。

ここは標準ライブラリと core と normalize の view・classify だけを使う。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from aws_iac_diagram.core.rules import Rules, neutral_key
from aws_iac_diagram.normalize import view
from aws_iac_diagram.normalize.classify import Decision
from aws_iac_diagram.normalize.view import Index, is_depends_on

# path の要素: 名前（`a`）、引用符つきの添字（`["aws:SourceArn"]`。名前として扱う）、ほかの添字（`[0]`。読まない）
_TOKEN = re.compile(r'([^.\[\]]+)|\["((?:[^"\\]|\\.)*)"\]|\[[^\]]*\]')


def path_keys(path: str, quoted: bool = True) -> tuple[str, ...]:
    """raw の参照の path → 中立キーの並び（`Properties.DefaultActions[0].TargetGroupArn` → (`defaultactions`, `targetgrouparn`)、
    `Condition.ArnEquals["aws:SourceArn"]` → (…, `arnequals`, `aws:sourcearn`)）。quoted が偽なら引用符つきの添字は読まない
    （refs.md: 属性名は識別子の要素で、`["aws:SourceArn"]` のときは 1 つ手前の `ArnEquals`）。"""
    if path.startswith("Properties."):
        path = path[len("Properties."):]
    out = []
    for m in _TOKEN.finditer(path):
        name = m.group(1) if m.group(1) is not None else (m.group(2) if quoted else None)
        if name:
            out.append(neutral_key(name))
    return tuple(out)


def ref_key(ref: dict) -> tuple[str, str, str]:
    return (ref["from"], ref["path"], ref["to"])


@dataclass(frozen=True)
class Candidate:
    """辺の候補 1 つ。`kind` が None で `weak_kind` があるものは「同じ組にほかの規則の辺があればそれに従う、無ければこの kind」
    （R-LAMBDA-PERMISSION・R-SQS-QUEUE-POLICY・R-SNS-TOPIC-POLICY）。`members` はこの辺に統合される関係リソースの address。"""
    frm: str
    to: str
    rule: str
    kind: str | None
    label: str = ""
    evidence: tuple[str, ...] = ()
    members: tuple[str, ...] = ()
    weak_kind: str | None = None
    confidence: str = "derived"
    refs: tuple[tuple[str, str, str], ...] = ()


def make(frm: str, to: str, rule: str, kind: str | None, label: str, refs: list[dict], members=(), weak_kind: str | None = None,
         notes: dict | None = None, texts: tuple[str, ...] = (), confidence: str = "derived") -> Candidate:
    """参照の並びから候補を作る（根拠の文字列は `<from>.<path>`、notes で参照ごとに説明を足せる。参照の無い根拠は texts）。"""
    notes = notes or {}
    ev = tuple(sorted({f"{r['from']}.{r['path']}" + (f" ({notes[ref_key(r)]})" if ref_key(r) in notes else "") for r in refs}
                      | set(texts)))
    return Candidate(frm, to, rule, kind, label, ev, tuple(sorted(set(members))), weak_kind, confidence,
                     refs=tuple(sorted({ref_key(r) for r in refs})))


@dataclass
class Context:
    index: Index
    decisions: dict[str, Decision]
    nodes: dict[str, dict]  # 描くリソースの address → ノード
    rules: Rules

    @property
    def fmt(self) -> str:
        return self.index.fmt

    def resources(self, rule: str, types: tuple[str, ...] | None = None) -> list:
        """分類が仮の R-*（rule）のリソース（address の順）。types があればその入力の型だけ。"""
        out = []
        for a in sorted(self.decisions):
            d = self.decisions[a]
            if d.cls == "merged_into" and d.rule == rule and (types is None or self.index.by_address[a].type in types):
                out.append(self.index.by_address[a])
        return out

    def drawn(self, *type_ids: str) -> list:
        """描くリソースのうち、正規の型が type_ids のもの（address の順）。"""
        return [self.index.by_address[a] for a in sorted(self.nodes) if self.nodes[a]["type"] in type_ids]

    def nodes_of(self, address: str) -> list[str]:
        """address のノード: 描くリソースならそのノード、統合済みの M-* なら統合先のノード。ほかは無し。"""
        if address in self.nodes:
            return [self.nodes[address]["id"]]
        d = self.decisions.get(address)
        if d is not None and d.cls == "merged_into" and d.rule.startswith("M-") and not d.provisional:
            return sorted(x for x in d.into if "->" not in x)
        return []

    def node_type(self, node_id: str) -> str:
        return node_id.split("/", 1)[0]

    def refs(self, address: str, *keypaths: tuple[str, ...]) -> list[dict]:
        """address から出る active な参照（DependsOn を除く）のうち、位置が keypaths のどれかで始まるもの（keypaths が無ければ全部）。"""
        out = []
        for ref in self.index.refs_from.get(address, ()):
            if is_depends_on(ref):
                continue
            keys = path_keys(ref["path"])
            if not keypaths or any(keys[:len(k)] == k for k in keypaths):
                out.append(ref)
        return out

    def refs_under(self, address: str, prefix: str) -> list[dict]:
        """address から出る active な参照（DependsOn を除く）のうち、raw の path が prefix（そのものか、その下）のもの。"""
        return [r for r in self.index.refs_from.get(address, ()) if not is_depends_on(r)
                and (r["path"] == prefix or r["path"].startswith((prefix + ".", prefix + "[")))]

    def targets(self, refs: list[dict], types: tuple[str, ...] | None = None) -> list[tuple[str, dict]]:
        """参照 → (参照先のノード, 参照)。types があればそのノードの型だけ。順は (ノード, path)。"""
        out = []
        for ref in refs:
            for nid in self.nodes_of(ref["to"]):
                if types is None or self.node_type(nid) in types:
                    out.append((nid, ref))
        return sorted(out, key=lambda x: (x[0], x[1]["path"]))

    def value(self, address: str, *names: str):
        """リソースの属性の値（中立キーで引く。最初に見つかった名前）。"""
        res = self.index.by_address[address]
        for n in names:
            v = res.get(n)
            if v is not None:
                return v
        return None


def value_at(props, path: str):
    """raw の path（`Properties.PolicyDocument.Statement[0]`・`policy.Statement[1]`）が指す props の中の値。`$json` は中身をたどる。
    たどれなければ None。"""
    if path.startswith("Properties."):
        path = path[len("Properties."):]
    cur = props
    for m in re.finditer(r'([^.\[\]]+)|\["((?:[^"\\]|\\.)*)"\]|\[(\d+)\]', path):
        while isinstance(cur, dict) and set(cur) == {"$json"}:
            cur = cur["$json"]
        if m.group(3) is not None:
            i = int(m.group(3))
            cur = cur[i] if isinstance(cur, list) and i < len(cur) else None
        else:
            key = m.group(1) if m.group(1) is not None else m.group(2)
            cur = cur.get(key) if isinstance(cur, dict) else None
        if cur is None:
            return None
    while isinstance(cur, dict) and set(cur) == {"$json"}:
        cur = cur["$json"]
    return cur


def label_protocol_port(protocol, port) -> str:
    """`<PROTOCOL> <port>`（LB のリスナー・ターゲットグループ）。決まらない部分は書かない。"""
    p = view.plain_str(protocol)
    n = port if isinstance(port, int) and not isinstance(port, bool) else (port if isinstance(port, str) and port.isdigit() else None)
    parts = [p.upper()] if p else []
    if n is not None:
        parts.append(str(n))
    return " ".join(parts)
