"""M-*（統合）の統合先の探し方の部品。`classify.finalize` が使う（段階 1 の確定）。

統合先は規則の `into.node_types` の描くノード。手がかりの強い順に使う（設計草案の 4.1。第三者レビューの指摘で決めた順）:

1. 主の属性の参照（`PRIMARY_ATTRS`。親を名指す属性: バケットの設定の `bucket`／`Bucket`、ステージの `api_id`・`RestApiId` など）。
   主の属性を持つ規則は統合先が 1 つの規則（親は 1 つ）なので、2 つ以上に当たれば決まった順の最初の 1 つにし、warn を出す。
2. DependsOn 以外の参照（どちら向きでも）。
3. 規則 ID ごとの名前の一致（`NAME_SELECTORS`。規則表の select の文のとおり）: M-AOSS-POLICY はポリシーの
   `collection/<名前>`、M-S3-CONFIG はバケットポリシーの `Bucket` の値がバケットの名前属性の値と同じもの（`$concat` と
   `$pseudo` の印の値は、印の形のまま比べる。C02 は `!Sub` の文字列でバケットを指す）。
4. 統合済みの M-* を 1 段たどる（幅優先。前の段で確定したものだけを見る。起動テンプレート → ノードグループ → クラスタ）。
5. 統合されるもの自身が宣言した DependsOn（外向き）で、候補がちょうど 1 つのときだけ（info を出す）。TF の
   `opensearch_index` は provider の `url` でしかコレクションを指さないため。

参照をたどるとき、H-UTILITY のリソース（`time_sleep` など。クラウド上の実体が無い）を 1 つだけ素通りする（T16 の
`aws_eks_node_group.cluster_name` → `time_sleep.this` → クラスタ）。

ここは標準ライブラリと core と normalize の view だけを使う。
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from aws_iac_diagram.core.rules import Rules, neutral_key
from aws_iac_diagram.normalize import view
from aws_iac_diagram.normalize.view import Index, is_depends_on

UTILITY = "H-UTILITY"

# 規則 ID → 親を名指す属性（中立キー）。ここにある規則は統合先が 1 つ
PRIMARY_ATTRS: dict[str, frozenset[str]] = {
    "M-S3-CONFIG": frozenset({"bucket"}),
    "M-S3-OBJECT": frozenset({"bucket"}),
    "M-APIGW-STAGE": frozenset({"apiid", "restapiid"}),
    "M-APIGW-RESPONSE": frozenset({"restapiid"}),
    "M-APIGW-AUTHORIZER": frozenset({"apiid", "restapiid"}),
    "M-IGW-ATTACH": frozenset({"internetgatewayid"}),
    "M-COGNITO-CONFIG": frozenset({"userpoolid"}),
    "M-EKS-PARTS": frozenset({"clustername"}),
    "M-AOSS-INDEX": frozenset({"collectionendpoint"}),
}


def ref_attr(ref: dict) -> str:
    """参照の位置の最初の属性名（中立キー）。CFN の `Properties.Bucket` → `bucket`、TF の `launch_template[0].id` → `launchtemplate`。"""
    path = ref.get("path", "")
    if path.startswith("Properties."):
        path = path[len("Properties."):]
    head = path.split(".", 1)[0].split("[", 1)[0]
    return neutral_key(head)


@dataclass(frozen=True)
class Context:
    index: Index
    decisions: dict  # address → Decision（classify の）
    node_of: dict[str, str]  # 描くリソースの address → ノードの id
    nodes: dict[str, dict]  # 描くリソースの address → ノード
    rules: Rules

    def node_type(self, address: str) -> str | None:
        nid = self.node_of.get(address)
        return nid.split("/", 1)[0] if nid else None

    def is_utility(self, address: str) -> bool:
        d = self.decisions.get(address)
        return d is not None and d.cls == "hidden" and d.rule == UTILITY

    def outgoing(self, address: str, attrs: frozenset[str] | None = None) -> set[str]:
        """address が参照する先（DependsOn を除く。`attrs` があればその属性の参照だけ）。H-UTILITY は 1 つだけ素通りする。"""
        out: set[str] = set()
        for ref in self.index.refs_from.get(address, ()):
            if is_depends_on(ref) or (attrs is not None and ref_attr(ref) not in attrs):
                continue
            to = ref["to"]
            out.add(to)
            if self.is_utility(to):
                out |= {r["to"] for r in self.index.refs_from.get(to, ()) if not is_depends_on(r)}
        out.discard(address)
        return out

    def incoming(self, address: str) -> set[str]:
        return set(self.index.referrers(address))

    def depends_on(self, address: str) -> set[str]:
        """address 自身が宣言した DependsOn の先。"""
        return {ref["to"] for ref in self.index.refs_from.get(address, ()) if is_depends_on(ref)} - {address}

    def drawn_of(self, addresses, node_types: tuple[str, ...]) -> set[str]:
        return {self.node_of[a] for a in addresses if self.node_type(a) in node_types}


# ------------------------------------------------------------------ 名前の一致

def _aoss_collection_names(res) -> set[str]:
    """OpenSearch Serverless のポリシーが指すコレクションの名前（`Rules[].Resource` の `collection/<名前>`・`index/<名前>/…`）。"""
    out: set[str] = set()
    for s in view.strings_in(dict(res.props)):
        for prefix in ("collection/", "index/"):
            if s.startswith(prefix):
                name = s[len(prefix):].split("/", 1)[0]
                if name and "*" not in name:
                    out.add(name)
    return out


def _by_aoss_name(ctx: Context, address: str, node_types: tuple[str, ...]) -> set[str]:
    names = _aoss_collection_names(ctx.index.by_address[address])
    return {n["id"] for n in ctx.nodes.values() if n["type"] in node_types and n["name"] in names}


def _canon(value) -> str | None:
    """名前の値の比べ方: 印の無い文字列はそのまま、`$concat`（文字列と `$pseudo` だけ）は印の形の JSON。ほかは比べない。"""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict) and set(value) == {"$concat"} and all(
            isinstance(p, str) or (isinstance(p, dict) and set(p) == {"$pseudo"}) for p in value["$concat"]):
        return json.dumps(value, sort_keys=True)
    return None


def _by_bucket_name(ctx: Context, address: str, node_types: tuple[str, ...]) -> set[str]:
    """バケットポリシーの `Bucket` の値と、バケットの名前属性（`bucket`／`BucketName`）の値が同じバケット。"""
    want = _canon(ctx.index.by_address[address].get("bucket"))
    if want is None:
        return set()
    out = set()
    for a, nid in ctx.node_of.items():
        t = nid.split("/", 1)[0]
        if t not in node_types:
            continue
        res = ctx.index.by_address[a]
        attr = ctx.rules.row(t).get("name_attr", {}).get(res.fmt)
        if attr and _canon(res.get(attr)) == want:
            out.add(nid)
    return out


# 規則 ID → 名前の一致で統合先を探す関数（参照ではなく名前で結ぶ統合。規則表の select の文のとおり）
NAME_SELECTORS = {"M-AOSS-POLICY": _by_aoss_name, "M-S3-CONFIG": _by_bucket_name}


def direct_targets(ctx: Context, address: str, rule: str, node_types: tuple[str, ...]) -> set[str]:
    """手がかりの 1〜3（主の属性の参照、DependsOn 以外の参照、名前の一致）で見つかる統合先。"""
    primary = PRIMARY_ATTRS.get(rule)
    if primary:
        found = ctx.drawn_of(ctx.outgoing(address, primary), node_types)
        if found:
            return found
    found = ctx.drawn_of(ctx.outgoing(address) | ctx.incoming(address), node_types)
    if not found and rule in NAME_SELECTORS:
        found = NAME_SELECTORS[rule](ctx, address, node_types)
    return found
