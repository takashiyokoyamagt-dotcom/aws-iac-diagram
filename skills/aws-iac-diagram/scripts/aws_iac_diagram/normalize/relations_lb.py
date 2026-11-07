"""R-LB-TG と R-LB-LISTENER（LB → ターゲットの辺）。

- ターゲットグループ（`aws_lb_target_group`／`AWS::ElasticLoadBalancingV2::TargetGroup`）ごとに、
  ① そのグループに転送するリスナー（グループへの参照を持つ R-LB-LISTENER のリソース）の LB（`load_balancer_arn`／`LoadBalancerArn`）と、
  ② ターゲット（ECS サービスの `load_balancer[].target_group_arn`／`LoadBalancers[].TargetGroupArn`、
  `aws_lb_target_group_attachment` の `target_id`、CFN のグループの `Targets[].Id`）を集め、LB × ターゲットの辺を作る。
  **参照はターゲット → グループだが、向きは LB → ターゲット**（A2）。
- ラベルはターゲットグループの `<PROTOCOL> <port>`（`HTTP 8080`）。リスナーのラベル（`HTTP 80`）は internet → LB の辺のもので、
  その辺（N-EXT-INTERNET）は SG の手順（手順 5）で作る。
- `members`: グループと attachment（R-LB-TG）、転送するリスナー（R-LB-LISTENER）。

ここは標準ライブラリと core と normalize の view・classify・relations_base だけを使う。
"""
from __future__ import annotations

from aws_iac_diagram.normalize.relations_base import Candidate, Context, label_protocol_port, make

TG_RULE = "R-LB-TG"
LISTENER_RULE = "R-LB-LISTENER"
TG = ("aws_lb_target_group", "AWS::ElasticLoadBalancingV2::TargetGroup")
ATTACHMENT = ("aws_lb_target_group_attachment",)


def lb_candidates(ctx: Context) -> list[Candidate]:
    out: list[Candidate] = []
    listeners = ctx.resources(LISTENER_RULE)
    attachments = ctx.resources(TG_RULE, ATTACHMENT)
    for g in [x.address for x in ctx.resources(TG_RULE, TG)]:
        label = label_protocol_port(ctx.value(g, "protocol"), ctx.value(g, "port"))
        # 転送するリスナーと、その LB: (LB のノード, 参照, リスナーの address)
        lbs: list[tuple[str, list[dict], str]] = []
        for lst in listeners:
            to_group = [r for r in ctx.refs(lst.address) if r["to"] == g]
            if to_group:
                for lb, lb_ref in ctx.targets(ctx.refs(lst.address, ("loadbalancerarn",)), ("alb",)):
                    lbs.append((lb, to_group + [lb_ref], lst.address))
        # ターゲット: (ノード, 参照, attachment の address か None)
        targets: list[tuple[str, list[dict], str | None]] = []
        for a in sorted(ctx.nodes):
            for ref in ctx.refs(a, ("loadbalancer", "targetgrouparn"), ("loadbalancers", "targetgrouparn")):
                if ref["to"] == g:
                    targets.append((ctx.nodes[a]["id"], [ref], None))
        for t, ref in ctx.targets(ctx.refs(g, ("targets", "id"))):
            targets.append((t, [ref], None))
        for att in attachments:
            to_group = [r for r in ctx.refs(att.address, ("targetgrouparn",)) if r["to"] == g]
            if to_group:
                for t, ref in ctx.targets(ctx.refs(att.address, ("targetid",))):
                    targets.append((t, [ref] + to_group, att.address))
        for lb, lst_refs, lst in lbs:
            for t, t_refs, att in targets:
                out.append(make(lb, t, TG_RULE, "request", label, t_refs, (g,) + ((att,) if att else ())))
                out.append(make(lb, t, LISTENER_RULE, "request", "", lst_refs, (lst,)))
    return out
