"""R-SG（セキュリティグループ → 辺）。docs/spec/rules/relations.md の R-SG の行と補足。

- SG X の ingress ルールの送信元が SG Y なら、Y を付けた各リソース → X を付けた各リソース（kind `network`、確信度 `derived`。
  ほかの根拠があれば E-MERGE でそちらの kind）。ラベルは edges.toml の `[[label_format]]` の SG（`TCP <port>`・`TCP <from>-<to>`・
  `UDP …`・`ALL`）。同じ組に複数のルールがあれば、まとめる段階（edges.py）が辞書順に `, ` でつなぐ。
- ingress ルールの形: TF のインラインの `ingress` ブロック（`security_groups`・`self`・`cidr_blocks`・`ipv6_cidr_blocks`）、
  `aws_security_group_rule`（`type = "ingress"`。egress は分類の段階で H-SG-EGRESS）、`aws_vpc_security_group_ingress_rule`
  （`referenced_security_group_id`・`cidr_ipv4`・`cidr_ipv6`）、CFN のインラインの `SecurityGroupIngress`、
  `AWS::EC2::SecurityGroupIngress`（`GroupId`／`GroupName`、`SourceSecurityGroupId`／`SourceSecurityGroupName`、`CidrIp`・`CidrIpv6`）。
  egress（インラインの `egress`／`SecurityGroupEgress`）は読まない（v0.1。H-SG-EGRESS の理由）。
- 「SG を付けたリソース」: SG への active な参照（DependsOn を除く）のうち、位置の最後の要素が refs.toml の E-NOEDGE-SG の属性
  （`security_groups`・`security_group_ids`・`vpc_security_group_ids`・`VPCSecurityGroups`。中立キー）のもの。参照する側のノード
  （M-* で統合されたものは統合先。起動テンプレート → ASG など）を端点にする。ECS サービスの `network_configuration`、Lambda の
  `vpc_config`、RDS、LB、VPC エンドポイントもこの形。SG 自身・ルールからの参照（`ingress[].security_groups`）は数えない。
- 送信元が `0.0.0.0/0`／`::/0` のとき: X を付けたリソースがインターネットに公開されていれば `external/internet` → そのリソース。
  公開は、インターネット向けの LB（`internal = false`／`Scheme: internet-facing`。無ければ既定で公開。値が決まらなければ公開としない）と、
  パブリック IP を持つ EC2（`associate_public_ip_address`／`NetworkInterfaces[].AssociatePublicIpAddress` が真。書かれていなければ、
  `map_public_ip_on_launch` が真で `access` が public のサブネットに置いたもの）。**LB への辺は、ここでは候補を返すだけ**（`SgResult.open_lbs`）で、リスナーと
  合わせて N-EXT-INTERNET が作る（synthetic.py。relations.md の補足「internet → ALB はリスナーと SG の両方から導く」）。
  ほかの外部の CIDR・VPC の中の CIDR は辺にしない（相手のノードが無い）。
- `members`（辺に統合される関係リソース）: 送信先の SG X、送信元の SG Y、別リソースのルール。SG は送信先としても送信元としても、
  生んだ辺を `into` に並べる。辺を 1 本も生まない SG・ルールは、分類の確定で fallback の H-SG-NOEDGE になる。
- 組合せ: 同じ SG を付けたリソースが多いと辺が増える（設計草案 8 章の 6。上限は設けない）。自己ループは作らない（同じ SG を
  付けたリソースどうしの `self` は、異なる 2 つのリソースの間の両向きの辺）。

ここは標準ライブラリと core と normalize の view・classify・relations_base だけを使う。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from aws_iac_diagram.core.rules import neutral_key
from aws_iac_diagram.normalize import view
from aws_iac_diagram.normalize.relations_base import Candidate, Context, make, path_keys

RULE = "R-SG"
ATTACH_RULE = "E-NOEDGE-SG"
INTERNET = "external/internet"
SG = ("aws_security_group", "AWS::EC2::SecurityGroup")
SEPARATE = ("aws_security_group_rule", "aws_vpc_security_group_ingress_rule", "AWS::EC2::SecurityGroupIngress")
INLINE = {"tf": ("ingress", "ingress"), "cfn": ("SecurityGroupIngress", "Properties.SecurityGroupIngress")}  # 属性名, raw の path
OPEN_V4, OPEN_V6 = "0.0.0.0/0", "::/0"
# ルールの中の参照の位置（中立キー）: 送信先の SG（別リソースのルールだけ）と送信元の SG
TARGET_KEYS = frozenset({"securitygroupid", "groupid", "groupname"})
SOURCE_KEYS = frozenset({"securitygroups", "sourcesecuritygroupid", "sourcesecuritygroupname", "referencedsecuritygroupid"})
CIDR_V4 = ("cidr_blocks", "cidr_ip", "cidr_ipv4")
CIDR_V6 = ("ipv6_cidr_blocks", "cidr_ipv6")
PROTOCOLS = {"tcp": "TCP", "6": "TCP", "udp": "UDP", "17": "UDP", "icmp": "ICMP", "1": "ICMP", "icmpv6": "ICMPV6", "58": "ICMPV6"}
ALL = ("-1", "all")
ALL_TCP = (0, 65535)
LB_TYPES = ("alb",)
EC2_TYPES = ("ec2_instance",)


@dataclass(frozen=True)
class Ingress:
    """ingress ルール 1 つ（の送信元 1 つ）。`source` は送信元の SG の address（CIDR のものは None で `open` が真）。
    `ports` は許す TCP のポートの範囲（全プロトコルは `ALL_TCP`。UDP・ICMP と、プロトコルかポートが決まらないものは None）。"""
    group: str
    label: str
    ports: tuple[int, int] | None
    source: str | None = None
    open: bool = False
    member: str | None = None
    refs: tuple[dict, ...] = ()
    texts: tuple[str, ...] = ()


@dataclass
class SgResult:
    candidates: list[Candidate]
    # インターネット向けの LB の address → [(0.0.0.0/0 を許すルールの R-SG の候補, その TCP の範囲)]。N-EXT-INTERNET が使う
    open_lbs: dict[str, list[tuple[Candidate, tuple[int, int] | None]]] = field(default_factory=dict)


def _port(v) -> int | None:
    v = view.plain(v)
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.lstrip("-").isdigit():
        return int(v)
    return None


def label_and_ports(props) -> tuple[str, tuple[int, int] | None]:
    """ルールのプロトコルとポート → (ラベル, 許す TCP のポートの範囲)。ラベルは `TCP 5432`／`TCP 1024-65535`／`UDP 53`／`ALL`。
    ポートが決まらなければプロトコルだけ（`TCP`）、プロトコルが決まらなければ空文字。範囲は、全プロトコル（`-1`）なら `ALL_TCP`、
    TCP でポートが決まればその範囲、ほか（UDP・ICMP・決まらないもの）は None（LB のリスナーには当たらない）。"""
    proto = view.plain(view.get(props, "protocol") if view.get(props, "protocol") is not None else view.get(props, "ip_protocol"))
    proto = str(proto).lower() if isinstance(proto, (str, int)) and not isinstance(proto, bool) else None
    if proto in ALL:
        return "ALL", ALL_TCP
    lo, hi = _port(view.get(props, "from_port")), _port(view.get(props, "to_port"))
    name = PROTOCOLS.get(proto, proto.upper() if proto else "")
    if not name:
        return "", None
    if name.startswith("ICMP") or lo is None or hi is None or lo < 0 or hi < 0:
        return name, None
    return (f"{name} {lo}" if lo == hi else f"{name} {lo}-{hi}"), ((lo, hi) if name == "TCP" else None)


def _open_text(address: str, prefix: str, props) -> str | None:
    """送信元が `0.0.0.0/0`／`::/0` なら根拠の文字列（`<address>.<位置> (0.0.0.0/0)`。位置は入力の綴りの属性名）。"""
    hits = []
    for names, want in ((CIDR_V4, OPEN_V4), (CIDR_V6, OPEN_V6)):
        keys = {neutral_key(n) for n in names}
        for k in sorted(k for k in props if isinstance(k, str) and neutral_key(k) in keys):
            v = view.plain(props[k])
            if want in [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str)]:
                hits.append(f"{address}.{prefix}{k} ({want})")
    return "; ".join(hits) or None


def _rule_ingress(ctx: Context, address: str, group: str, props, raw_prefix: str, refs: list[dict], member: str | None,
                  target_refs: list[dict], sgs: set[str]) -> list[Ingress]:
    """1 つのルール（インラインのブロックか、別リソース）の Ingress。refs は送信元の参照の候補、target_refs は送信先の参照。"""
    label, ports = label_and_ports(props)
    out = []
    for r in refs:
        keys = path_keys(r["path"])
        if r["to"] in sgs and any(k in SOURCE_KEYS for k in keys[-1:]):
            out.append(Ingress(group, label, ports, source=r["to"], member=member, refs=tuple(target_refs + [r])))
    if view.plain(view.get(props, "self")) is True:
        out.append(Ingress(group, label, ports, source=group, member=member, refs=tuple(target_refs),
                           texts=(f"{address}.{raw_prefix}self (true)",)))
    text = _open_text(address, raw_prefix, props)
    if text:
        out.append(Ingress(group, label, ports, open=True, member=member, refs=tuple(target_refs), texts=(text,)))
    return out


def ingress_rules(ctx: Context) -> list[Ingress]:
    """R-SG の SG（仮分類のもの）にかかる ingress ルールすべて（SG の address の順、インライン → 別リソースの順）。"""
    sgs = {r.address for r in ctx.resources(RULE, SG)}
    out: list[Ingress] = []
    for g in sorted(sgs):
        name, raw_path = INLINE[ctx.index.by_address[g].fmt]
        blocks = view.get(dict(ctx.index.by_address[g].props), name)
        if not isinstance(blocks, list):
            continue
        for i, b in enumerate(blocks):
            if not isinstance(b, dict) or view.is_mark(b):
                continue
            prefix = f"{raw_path}[{i}]"
            out += _rule_ingress(ctx, g, g, b, prefix + ".", ctx.refs_under(g, prefix), None, [], sgs)
    for rule in ctx.resources(RULE, SEPARATE):
        props = dict(rule.props)
        targets = [r for r in ctx.refs(rule.address) if path_keys(r["path"])[:1] and path_keys(r["path"])[0] in TARGET_KEYS
                   and r["to"] in sgs]
        prefix = "Properties." if rule.fmt == "cfn" else ""
        for g in sorted({r["to"] for r in targets}):
            t_refs = [r for r in targets if r["to"] == g]
            out += _rule_ingress(ctx, rule.address, g, props, prefix, ctx.refs(rule.address), rule.address, t_refs, sgs)
    return out


def attachments(ctx: Context, sgs: set[str]) -> dict[str, list[tuple[str, dict, str]]]:
    """SG の address → [(SG を付けたノード, その参照, 参照する側の address)]（ノード・path の順）。"""
    row = next((r for r in ctx.rules.noedge if r.id == ATTACH_RULE), None)
    keys = {neutral_key(a) for a in (row.attrs if row is not None else ())}
    out: dict[str, list[tuple[str, dict, str]]] = {g: [] for g in sgs}
    for frm in sorted(ctx.index.refs_from):
        d = ctx.decisions.get(frm)
        if d is not None and d.rule == RULE:
            continue
        for r in ctx.refs(frm):
            pk = path_keys(r["path"])
            if r["to"] in out and pk and pk[-1] in keys:
                for nid in ctx.nodes_of(frm):
                    out[r["to"]].append((nid, r, frm))
    return {g: sorted(v, key=lambda x: (x[0], x[1]["from"], x[1]["path"])) for g, v in out.items()}


def internet_facing(ctx: Context, address: str) -> str | None:
    """インターネット向けの LB なら根拠の文字列（`<address>.internal (false)` など）、そうでなければ None。属性が無ければ既定
    （TF の `internal` は false、CFN の `Scheme` は internet-facing）で公開。値が決まらない（`$unknown` など）ものは公開としない。"""
    res = ctx.index.by_address[address]
    if res.fmt == "tf":
        raw = dict(res.props).get("internal")
        if raw is None:
            return f"{address}.internal (既定値 false)"
        return f"{address}.internal (false)" if view.plain(raw) is False else None
    raw = dict(res.props).get("Scheme")
    if raw is None:
        return f"{address}.Properties.Scheme (既定値 internet-facing)"
    return f"{address}.Properties.Scheme (internet-facing)" if view.plain(raw) == "internet-facing" else None


def _key(props, name: str) -> str | None:
    """props の中で、中立キーが name と同じ属性名（入力の綴り）。無ければ None。"""
    if not isinstance(props, dict):
        return None
    return next((k for k in sorted(props) if isinstance(k, str) and neutral_key(k) == neutral_key(name)), None)


def public_ec2(ctx: Context, address: str, access: dict[str, str]) -> str | None:
    """パブリック IP を持つ EC2 なら根拠の文字列、そうでなければ None。`associate_public_ip_address`（TF の `network_interface[]`、
    CFN の `NetworkInterfaces[]` の中のものも）が書かれていれば、その値が真のときだけ公開（偽・決まらない値なら、
    `map_public_ip_on_launch` のサブネットでも公開としない）。書かれていなければサブネットで決める。"""
    res = ctx.index.by_address[address]
    props = dict(res.props)
    pre = "Properties." if res.fmt == "cfn" else ""
    k = _key(props, "associate_public_ip_address")
    if k is not None:
        return f"{address}.{pre}{k} (true)" if view.plain(props[k]) is True else None
    nk = _key(props, "network_interface" if res.fmt == "tf" else "NetworkInterfaces")
    nis = view.plain(props[nk]) if nk else None
    written = False
    for i, ni in enumerate(nis if isinstance(nis, list) else []):
        ak = _key(ni, "associate_public_ip_address")
        if ak is None:
            continue
        written = True
        if view.plain(ni[ak]) is True:
            return f"{address}.{pre}{nk}[{i}].{ak} (true)"
    if written:
        return None
    for sub, ref in ctx.targets(ctx.refs(address, ("subnetid",)), ("subnet",)):
        if access.get(sub) == "public" and view.plain(ctx.index.by_address[ref["to"]].get("map_public_ip_on_launch")) is True:
            return f"{ref['from']}.{ref['path']} (map_public_ip_on_launch のパブリックサブネット)"
    return None


def sg_candidates(ctx: Context, access: dict[str, str]) -> SgResult:
    """R-SG の辺の候補と、0.0.0.0/0 を許すインターネット向けの LB（N-EXT-INTERNET の材料）。"""
    sgs = {r.address for r in ctx.resources(RULE, SG)}
    attached = attachments(ctx, sgs)
    result = SgResult([])
    for ing in ingress_rules(ctx):
        members = (ing.group,) + ((ing.source,) if ing.source else ()) + ((ing.member,) if ing.member else ())
        dst = attached.get(ing.group, [])
        if ing.source:
            for a, a_ref, _ in attached.get(ing.source, []):
                for b, b_ref, _ in dst:
                    result.candidates.append(make(a, b, RULE, "network", ing.label, list(ing.refs) + [a_ref, b_ref], members,
                                                  texts=ing.texts))
        if ing.open:
            for b, b_ref, frm in dst:
                if frm not in ctx.nodes:
                    continue
                c = None
                if ctx.node_type(b) in LB_TYPES and internet_facing(ctx, frm):
                    c = make(INTERNET, b, RULE, "network", ing.label, list(ing.refs) + [b_ref], members, texts=ing.texts)
                    result.open_lbs.setdefault(frm, []).append((c, ing.ports))
                elif ctx.node_type(b) in EC2_TYPES:
                    why = public_ec2(ctx, frm, access)
                    if why:
                        result.candidates.append(make(INTERNET, b, RULE, "network", ing.label, list(ing.refs) + [b_ref], members,
                                                      texts=ing.texts + (why,)))
    return result
