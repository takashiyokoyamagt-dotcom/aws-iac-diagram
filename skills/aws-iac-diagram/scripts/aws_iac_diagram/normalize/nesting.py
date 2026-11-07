"""正規化の段階 4: 入れ子（P）。ノードの `parent`・`spans` と、AZ のノード（N-AZ）を作る。規則は `data/rules/placement.toml`
（説明は docs/spec/rules/placement.md）と ir-schema の 2 章（×N の置き場所、AZ のノードの id）。

置き場所の手がかりは、ノードのリソース（と、そのノードに統合された M-*。DB サブネットグループ経由の DB、
CFN の VPCGatewayAttachment 経由のインターネットゲートウェイ）から、描くサブネット・VPC への参照（DependsOn を除く `active` の参照で、
指す属性がリソースそのもの: TF の `id`、CFN の `Ref` と `SubnetId`・`VpcId`）。CIDR や AZ を取るだけの参照は数えない。

- **N-AZ:** サブネットは、自分の VPC の下に AZ ごとのノード `availability_zone/<VPC の key>.<AZ 名>` を作ってその下に入れる。
  AZ が `{"$az": n}`（静的に決まらない n 番目）なら AZ 名の代わりに `az<n+1>`（label は `AZ <n+1>`）。`{"$az": "*"}`・値が無い・
  評価できないときは AZ のノードを作らず、サブネットの `parent` を VPC にする（`NORM-AZ-UNKNOWN`、info）。
- **P-REGIONAL:** VPC に入らない型は `parent: null`。ただし Lambda は VPC の設定（`vpc_config`・`VpcConfig`。この位置の参照だけ）で
  サブネットを指していれば下の規則に従う（placement.md の注）。EKS のクラスタも、自分の `vpc_config`・`ResourcesVpcConfig` の参照だけ。
- **P-SUBNET／P-SPANS:** サブネットを 1 つ指せば `parent` はそのサブネット。2 つ以上なら `spans` に並べ、`parent` はそれらの最も近い
  共通の祖先（AZ が違えば VPC。VPC も違えば `parent: null` で `NORM-PLACEMENT`）。指したサブネットに ×N のものがあれば（サブネットが決まらない）`spans` を付けず、`parent` は共通の祖先
  （`NORM-PLACEMENT`、warn）。
- **P-VPC:** サブネットを指さず VPC を指すもの（インターネットゲートウェイ、Gateway 型の VPC エンドポイント、VPC だけを入力に渡した
  黒箱のモジュール）は `parent` が VPC。
- 規則が VPC の中に置く型（P-VPC・P-SUBNET・P-SPANS の `types`、サブネット）で置き場所が決まらなければ `parent: null` にして
  `NORM-PLACEMENT`（warn）。黒箱のモジュール（型 `module`）と VPC は、決まらなければ `parent: null`（診断なし）。

ここは標準ライブラリと core と normalize の view・classify・names だけを使う。
"""
from __future__ import annotations

from aws_iac_diagram.core.rules import Rules
from aws_iac_diagram.normalize.classify import Decision
from aws_iac_diagram.normalize.names import key_of
from aws_iac_diagram.normalize.view import Index, is_depends_on

# 参照の属性のうち「リソースそのもの」を指すもの（入れ子の手がかりにする）
IDENTITY_ATTRS = frozenset({None, "id", "SubnetId", "VpcId"})
AZ_TYPE = "availability_zone"
LAMBDA = "lambda_function"

# 型 → 置き場所の手がかりにする参照の位置（この型は、自分のこの位置の参照だけを使い、統合された M-* の参照は使わない）。
# Lambda は VPC の設定だけ（環境変数にサブネットの id を渡しても VPC には入らない）、EKS のクラスタは規則の文のとおり
# クラスタ自身の `vpc_config.subnet_ids`／`ResourcesVpcConfig.SubnetIds` だけ（統合したノードグループのサブネットは使わない）
OWN_PATHS: dict[str, tuple[str, ...]] = {
    LAMBDA: ("vpc_config", "Properties.VpcConfig"),
    "eks_cluster": ("vpc_config", "Properties.ResourcesVpcConfig"),
}


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == p or path.startswith((p + ".", p + "[")) for p in prefixes)


def _placement_types(rules: Rules, rule_id: str) -> frozenset[str]:
    return frozenset(rules.row(rule_id).types)


def az_of(value) -> tuple[str, str] | None:
    """サブネットの AZ の値 → (name, label)。AZ 名の文字列はそのまま、`{"$az": n}` は `az<n+1>`／`AZ <n+1>`。決まらなければ None。"""
    if isinstance(value, str) and value.strip():
        return value, value
    if isinstance(value, dict) and set(value) == {"$az"} and isinstance(value["$az"], int) and not isinstance(value["$az"], bool):
        n = value["$az"] + 1
        return f"az{n}", f"AZ {n}"
    return None


class _Placer:
    def __init__(self, index: Index, decisions: dict[str, Decision], node_by_address: dict[str, dict], rules: Rules):
        self.index = index
        self.rules = rules
        self.nodes: dict[str, dict] = {n["id"]: n for n in node_by_address.values()}
        self.address_of = {n["id"]: a for a, n in node_by_address.items()}
        # ノード → 手がかりを取るリソース（自分と、そのノードに統合された M-*。共有の DB サブネットグループのように統合先が
        # 2 つ以上ある M-* は、統合先のすべての手がかりになる。OWN_PATHS の型は自分だけ）
        self.sources: dict[str, list[str]] = {nid: [a] for nid, a in self.address_of.items()}
        for a in sorted(decisions):
            d = decisions[a]
            if d.cls == "merged_into" and not d.provisional and d.rule.startswith("M-"):
                for target in d.into:
                    if target in self.sources and self.nodes[target]["type"] not in OWN_PATHS:
                        self.sources[target].append(a)
        self.node_of = {a: n["id"] for a, n in node_by_address.items()}
        self.diags: list[dict] = []
        self.regional = _placement_types(rules, "P-REGIONAL") - {LAMBDA}
        self.in_vpc = (_placement_types(rules, "P-VPC") | _placement_types(rules, "P-SUBNET") | _placement_types(rules, "P-SPANS")
                       | {"subnet"})

    def referenced(self, nid: str, type_id: str) -> list[str]:
        """ノード nid の手がかりのリソースが、リソースそのものとして参照する、型 type_id の描くノード（id の順）。"""
        out = set()
        own = OWN_PATHS.get(self.nodes[nid]["type"])
        for a in self.sources[nid]:
            for ref in self.index.refs_from.get(a, ()):
                if is_depends_on(ref) or ref.get("attr") not in IDENTITY_ATTRS:
                    continue
                if own is not None and not _under(ref.get("path", ""), own):
                    continue
                to = self.node_of.get(ref["to"])
                if to and to != nid and self.nodes[to]["type"] == type_id:
                    out.add(to)
        return sorted(out)

    def diag(self, level: str, code: str, nid: str, message: str) -> None:
        self.diags.append({"level": level, "code": code, "address": self.address_of.get(nid, nid), "message": message})

    def chain(self, nid: str) -> list[str]:
        out = []
        while nid is not None and nid not in out:
            out.append(nid)
            nid = self.nodes[nid]["parent"]
        return out

    def common_ancestor(self, ids: list[str]) -> str | None:
        """ids の最も近い共通の祖先（ids 自身は含めない。無ければ None）。"""
        chains = [self.chain(i)[1:] for i in ids]
        for c in chains[0]:
            if all(c in other for other in chains[1:]):
                return c
        return None

    def place_subnet(self, nid: str) -> None:
        node = self.nodes[nid]
        vpcs = self.referenced(nid, "vpc")
        if len(vpcs) != 1:
            self.diag("warn", "NORM-PLACEMENT", nid, f"サブネットの VPC が {'決まらない' if not vpcs else '1 つに決まらない（' + '・'.join(vpcs) + '）'}ので、parent を null にした")
            return
        vpc = vpcs[0]
        az = az_of(self.index.by_address[self.address_of[nid]].get("availability_zone"))
        if az is None:
            node["parent"] = vpc
            self.diag("info", "NORM-AZ-UNKNOWN", nid, "AZ が静的に決まらないので、AZ のノードを作らずサブネットを VPC の下に置いた")
            return
        name, label = az
        az_id = f"{AZ_TYPE}/{vpc.split('/', 1)[1]}.{key_of(name)}"
        if az_id not in self.nodes:
            self.nodes[az_id] = {"id": az_id, "type": AZ_TYPE, "category": "group", "name": name, "label": label, "parent": vpc,
                                 "synthetic": True}
        node["parent"] = az_id

    def place_other(self, nid: str) -> None:
        node = self.nodes[nid]
        t = node["type"]
        if t in self.regional:
            return
        subnets = self.referenced(nid, "subnet")
        if subnets:
            if any(self.nodes[s].get("multiplicity") == "N" for s in subnets):
                node["parent"] = self.common_ancestor(subnets) if len(subnets) > 1 else self.nodes[subnets[0]]["parent"]
                self.diag("warn", "NORM-PLACEMENT", nid, f"指すサブネットに ×N のもの（{'・'.join(subnets)}）があり、置き場所のサブネットが決まらないので、"
                               f"parent を {node['parent'] or 'null'} にした（spans は付けない）")
            elif len(subnets) == 1:
                node["parent"] = subnets[0]
            else:
                node["spans"] = subnets
                node["parent"] = self.common_ancestor(subnets)
                if node["parent"] is None:
                    self.diag("warn", "NORM-PLACEMENT", nid, f"指すサブネット（{'・'.join(subnets)}）に共通の祖先が無い（VPC が違う）ので、"
                                   "spans は付けて parent を null にした")
            return
        vpcs = self.referenced(nid, "vpc")
        if len(vpcs) == 1:
            node["parent"] = vpcs[0]
        elif t in self.in_vpc or len(vpcs) > 1:
            self.diag("warn", "NORM-PLACEMENT", nid, "置き場所のサブネット・VPC が決まらないので、parent を null にした"
                      + (f"（VPC が 2 つ以上: {'・'.join(vpcs)}）" if vpcs else ""))

    def run(self) -> list[dict]:
        ids = sorted(self.nodes)
        for nid in ids:
            if self.nodes[nid]["type"] == "subnet":
                self.place_subnet(nid)
        for nid in ids:
            if self.nodes[nid]["type"] not in ("subnet", "vpc"):
                self.place_other(nid)
        return [self.nodes[i] for i in sorted(self.nodes)]


def place(index: Index, decisions: dict[str, Decision], node_by_address: dict[str, dict], rules: Rules) -> tuple[list[dict], list[dict]]:
    """段階 4: ノードに `parent`・`spans` を付け、AZ のノードを足した一覧（id の順）と、診断。`decisions` は確定した分類
    （統合先の決まった M-* を手がかりに使う）。`node_by_address` のノードは書き換える。"""
    p = _Placer(index, decisions, node_by_address, rules)
    return p.run(), p.diags
