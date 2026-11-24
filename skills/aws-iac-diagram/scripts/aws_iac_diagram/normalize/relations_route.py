"""R-ROUTE（ルートテーブル・ルート・関連付け → サブネット → 宛先の辺）と R-VPCE-GATEWAY（Gateway 型の VPC エンドポイント）、
サブネットの `attrs.access`（placement.toml の `[[attr]]`。R-ROUTE の結果から決める）。

- ルートテーブルごとに、関連付け（`aws_route_table_association`／`AWS::EC2::SubnetRouteTableAssociation`）のサブネットと、
  ルートの宛先（TF のインラインの `route` ブロック、`aws_route`／`AWS::EC2::Route`）の描くノードを集め、サブネット × 宛先の辺を作る。
  ラベルは宛先の CIDR（同じ組に 2 つ以上あれば辞書順に `, ` でつなぐ）。宛先が描くノードでない（ピアリング、TGW など表に無い型）
  ルートは辺にしない。
- Gateway 型の VPC エンドポイントの `route_table_ids`／`RouteTableIds` のルートテーブルに関連付いたサブネット → エンドポイントの辺。
  R-ROUTE（関連付け）と R-VPCE-GATEWAY（エンドポイントの属性）の両方の根拠を持つ。ラベルは `<サービス> prefix list`。
- 辺の候補の `members`（その辺に統合される関係リソース）: ルートテーブル、その関連付け（自分のサブネットの辺だけ）、ルート（自分の宛先の辺）。
  辺が 1 本も無いルートテーブル・関連付け・ルートは、分類の確定で fallback の H-RT-NOROUTE になる。
- `access`: `0.0.0.0/0` → インターネットゲートウェイのルートの辺があれば `public`、無ければ `private`（関連付けの無いサブネットも private）。
- R-TGW-ATTACH（`tgw_candidates`）: Transit Gateway の VPC アタッチメントごとに、`vpc_id`／`VpcId` の VPC → `transit_gateway_id`／
  `TransitGatewayId` の TGW（`network`、ラベルなし）。アタッチメントを `transit_gateway_attachment_id` で指す TGW のルートテーブルへの
  関連付け・伝播も、その辺の `members` にする。
- R-TGW-ROUTE: TGW のルートの宛先のアタッチメント（`transit_gateway_attachment_id`）の TGW → その VPC（`route`、ラベルは宛先の CIDR）。
  宛先の無いルート（blackhole）は辺を作らない。アタッチメントの VPC か TGW が 1 つに決まらなければ、どちらの規則も辺を作らない
  （推測で全部の VPC へ出さない）。同じ (TGW, VPC) のルートは E-MERGE で 1 本にまとまる（ラベルは CIDR を辞書順に `, ` でつなぐ）。

ここは標準ライブラリと core と normalize の view・classify・relations_base だけを使う。
"""
from __future__ import annotations

import re

from aws_iac_diagram.normalize import view
from aws_iac_diagram.normalize.relations_base import Candidate, Context, make, path_keys

RULE = "R-ROUTE"
VPCE_RULE = "R-VPCE-GATEWAY"
TABLE = ("aws_route_table", "AWS::EC2::RouteTable")
ROUTE = ("aws_route", "AWS::EC2::Route")
ASSOC = ("aws_route_table_association", "AWS::EC2::SubnetRouteTableAssociation")
CIDR_KEYS = ("cidr_block", "ipv6_cidr_block", "destination_cidr_block", "destination_ipv6_cidr_block")
_ROUTE_INDEX = re.compile(r"^route\[(\d+)\]")
PUBLIC_CIDRS = ("0.0.0.0/0",)
TGW_ATTACH_RULE = "R-TGW-ATTACH"
TGW_ROUTE_RULE = "R-TGW-ROUTE"
TGW_ATTACHMENT = ("aws_ec2_transit_gateway_vpc_attachment", "AWS::EC2::TransitGatewayVpcAttachment", "AWS::EC2::TransitGatewayAttachment")


def _cidr(props) -> str:
    for k in CIDR_KEYS:
        v = view.plain_str(view.get(props, k))
        if v:
            return v
    return ""


def route_candidates(ctx: Context) -> tuple[list[Candidate], dict[str, str]]:
    """R-ROUTE と R-VPCE-GATEWAY の辺の候補と、サブネットのノード → access。"""
    tables = [r.address for r in ctx.resources(RULE, TABLE)]
    # ルートテーブル → [(宛先のノード, CIDR, 参照, ルートの address か None, ルートからテーブルへの参照)]
    routes: dict[str, list[tuple[str, str, list[dict], str | None]]] = {t: [] for t in tables}
    for t in tables:
        blocks = view.get(dict(ctx.index.by_address[t].props), "route")
        for ref in ctx.refs(t, ("route",)):
            m = _ROUTE_INDEX.match(ref["path"])
            if not m:
                continue
            i = int(m.group(1))
            cidr = _cidr(blocks[i]) if isinstance(blocks, list) and i < len(blocks) and isinstance(blocks[i], dict) else ""
            for nid in ctx.nodes_of(ref["to"]):
                routes[t].append((nid, cidr, [ref], None))
    for r in ctx.resources(RULE, ROUTE):
        cidr = _cidr(dict(r.props))
        to_table = ctx.refs(r.address, ("routetableid",))
        for t in sorted({x["to"] for x in to_table}):
            if t not in routes:
                continue
            for ref in ctx.refs(r.address):
                if path_keys(ref["path"])[:1] == ("routetableid",):
                    continue
                for nid in ctx.nodes_of(ref["to"]):
                    routes[t].append((nid, cidr, [ref] + [x for x in to_table if x["to"] == t], r.address))
    # ルートテーブル → [(サブネットのノード, 参照, 関連付けの address)]
    subnets: dict[str, list[tuple[str, list[dict], str]]] = {t: [] for t in tables}
    for a in ctx.resources(RULE, ASSOC):
        to_table = ctx.refs(a.address, ("routetableid",))
        for t in sorted({x["to"] for x in to_table}):
            if t not in subnets:
                continue
            for nid, ref in ctx.targets(ctx.refs(a.address, ("subnetid",)), ("subnet",)):
                subnets[t].append((nid, [ref] + [x for x in to_table if x["to"] == t], a.address))
    # Gateway 型の VPC エンドポイント: ルートテーブル → [(エンドポイントのノード, ラベル, 参照)]
    vpce: dict[str, list[tuple[str, str, dict]]] = {t: [] for t in tables}
    for res in ctx.drawn("vpc_endpoint"):
        node = ctx.nodes[res.address]
        if (node.get("attrs") or {}).get("endpoint_type") != "Gateway":
            continue
        svc = (node.get("attrs") or {}).get("service")
        for ref in ctx.refs(res.address, ("routetableids",)):
            if ref["to"] in vpce:
                vpce[ref["to"]].append((node["id"], f"{svc} prefix list" if svc else "", ref))
    out: list[Candidate] = []
    for t in tables:
        for sub, sub_refs, assoc in subnets[t]:
            for dest, cidr, refs, route in routes[t]:
                out.append(make(sub, dest, RULE, "route", cidr, refs + sub_refs, (t, assoc) + ((route,) if route else ())))
            for dest, label, ref in vpce[t]:
                out.append(make(sub, dest, RULE, "route", "", sub_refs, (t, assoc)))
                out.append(make(sub, dest, VPCE_RULE, "route", label, [ref]))
    access = {}
    for res in ctx.drawn("subnet"):
        nid = ctx.nodes[res.address]["id"]
        public = any(c.frm == nid and c.rule == RULE and c.label in PUBLIC_CIDRS and ctx.node_type(c.to) == "internet_gateway"
                     for c in out)
        access[nid] = "public" if public else "private"
    return out, access


def _attachment_ends(ctx: Context, att: str) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """アタッチメントの (VPC, 参照) と (TGW, 参照)。"""
    return (ctx.targets(ctx.refs(att, ("vpcid",)), ("vpc",)),
            ctx.targets(ctx.refs(att, ("transitgatewayid",)), ("transit_gateway",)))


def tgw_candidates(ctx: Context) -> list[Candidate]:
    """R-TGW-ATTACH（VPC → TGW）と R-TGW-ROUTE（TGW → 宛先のアタッチメントの VPC）の辺の候補。"""
    out: list[Candidate] = []
    attachments = [r.address for r in ctx.resources(TGW_ATTACH_RULE, TGW_ATTACHMENT)]
    parts = [r.address for r in ctx.resources(TGW_ATTACH_RULE) if r.address not in attachments]
    for att in attachments:
        vpcs, tgws = _attachment_ends(ctx, att)
        if len(vpcs) != 1 or len(tgws) != 1:
            continue  # VPC か TGW が 1 つに決まらないアタッチメントは、推測で全部へ辺を出さない
        members = (att,) + tuple(p for p in parts if any(r["to"] == att for r in ctx.refs(p, ("transitgatewayattachmentid",))))
        for vpc, vref in vpcs:
            for tgw, tref in tgws:
                out.append(make(vpc, tgw, TGW_ATTACH_RULE, "network", "", [vref, tref], members))
    for r in ctx.resources(TGW_ROUTE_RULE):
        cidr = _cidr(dict(r.props))
        for aref in ctx.refs(r.address, ("transitgatewayattachmentid",)):
            if aref["to"] not in attachments:
                continue
            vpcs, tgws = _attachment_ends(ctx, aref["to"])
            if len(vpcs) != 1 or len(tgws) != 1:
                continue
            (vpc, vref), (tgw, tref) = vpcs[0], tgws[0]
            # 同じ (TGW, VPC) のルート（ルートテーブル・宛先 CIDR ごと）は E-MERGE で 1 本になり、CIDR は `, ` でつながる
            out.append(make(tgw, vpc, TGW_ROUTE_RULE, "route", cidr, [aref, tref, vref], (r.address,)))
    return out
