"""R-SG（normalize/relations_sg.py）と N-EXT-INTERNET（normalize/synthetic.py の internet の部分）。TF と CFN の形をそれぞれ
小さな raw IR で確かめる。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.raw_builders import raw_ir, ref, resource
from aws_iac_diagram.core import rules as rules_mod  # noqa: E402
from aws_iac_diagram.normalize import build  # noqa: E402
from aws_iac_diagram.normalize.relations_sg import label_and_ports  # noqa: E402

RULES = rules_mod.default()
INTERNET = "external/internet"


def R(addr, type_, props=None):
    """TF のリソース。"""
    return resource(addr, type_, props)


def C(addr, type_, props=None):
    """CFN のリソース。"""
    return resource(addr, type_, props, fmt="cfn")


def tag(name, **props):
    """`Name` タグとほかの属性（TF）。"""
    return {"tags": {"Name": name}, **props}


class Out:
    def __init__(self, fmt, resources, references):
        self.ir = build.normalize(raw_ir(fmt, resources, references), RULES, "t")
        self.edges = {e["id"]: (e["kind"], e["label"], e["confidence"]) for e in self.ir["edges"]}
        self.ev = {e["edge"]: e for e in self.ir["sources"][fmt]["edges"]}
        self.cls = {r["address"]: (r["class"], r.get("rule"), tuple(r.get("into", ()))) for r in self.ir["sources"][fmt]["resources"]}
        self.nodes = {n["id"]: n for n in self.ir["nodes"]}
        self.codes = [d["code"] for d in self.ir["diagnostics"]]


class LabelTest(unittest.TestCase):
    def test_labels(self):
        cases = [
            ({"protocol": "tcp", "from_port": 5432, "to_port": 5432}, ("TCP 5432", (5432, 5432))),
            ({"protocol": "tcp", "from_port": "1024", "to_port": "65535"}, ("TCP 1024-65535", (1024, 65535))),
            # 2 つ目は LB のリスナーに当たる TCP の範囲: 全プロトコルは全ポート、UDP・ICMP・決まらないものは None
            ({"protocol": "-1", "from_port": 0, "to_port": 0}, ("ALL", (0, 65535))),
            ({"IpProtocol": -1}, ("ALL", (0, 65535))),
            ({"ip_protocol": "udp", "from_port": 53, "to_port": 53}, ("UDP 53", None)),
            ({"protocol": {"$unknown": "x"}, "from_port": 80, "to_port": 80}, ("", None)),
            ({"IpProtocol": "6", "FromPort": 443, "ToPort": 443}, ("TCP 443", (443, 443))),
            ({"protocol": "icmp", "from_port": -1, "to_port": -1}, ("ICMP", None)),
            ({"protocol": "tcp", "from_port": {"$unknown": "x"}, "to_port": 80}, ("TCP", None)),
            ({}, ("", None)),
        ]
        for props, want in cases:
            with self.subTest(props):
                self.assertEqual(label_and_ports(props), want)


class TfSgTest(unittest.TestCase):
    def test_inline_and_separate_rules_internet_and_merge(self):
        o = Out("tf", [
            R("aws_lb.alb", "aws_lb", {"name": "alb", "internal": False}),
            R("aws_lb_listener.http", "aws_lb_listener", {"port": 80, "protocol": "HTTP"}),
            R("aws_lb_listener.admin", "aws_lb_listener", {"port": 8443, "protocol": "HTTPS"}),  # SG が 0.0.0.0/0 を許さないポート
            R("aws_lb_target_group.tg", "aws_lb_target_group", {"protocol": "HTTP", "port": 8080}),
            R("aws_ecs_service.svc", "aws_ecs_service", {"name": "svc"}),
            R("aws_db_instance.db", "aws_db_instance", {"identifier": "db"}),
            R("aws_security_group.alb", "aws_security_group", {
                "ingress": [{"from_port": 80, "to_port": 80, "protocol": "tcp", "cidr_blocks": ["0.0.0.0/0"]}],
                "egress": [{"from_port": 0, "to_port": 0, "protocol": "-1", "cidr_blocks": ["0.0.0.0/0"]}]}),
            R("aws_security_group.app", "aws_security_group"),
            R("aws_security_group.db", "aws_security_group", {"ingress": [
                {"from_port": 5432, "to_port": 5432, "protocol": "tcp", "security_groups": [{"$res": "aws_security_group.app"}]},
                {"from_port": 6432, "to_port": 6432, "protocol": "tcp", "security_groups": [{"$res": "aws_security_group.app"}]},
                {"from_port": 22, "to_port": 22, "protocol": "tcp", "cidr_blocks": ["203.0.113.0/24"]}]}),
            R("aws_vpc_security_group_ingress_rule.app_from_alb", "aws_vpc_security_group_ingress_rule",
              {"from_port": 8080, "to_port": 8080, "ip_protocol": "tcp"}),
            R("aws_vpc_security_group_egress_rule.out", "aws_vpc_security_group_egress_rule", {"ip_protocol": "-1"}),
            R("aws_security_group_rule.db_egress", "aws_security_group_rule", {"type": "egress", "protocol": "-1",
                                                                              "from_port": 0, "to_port": 0}),
        ], [
            ref("aws_lb.alb", "security_groups[0]", "aws_security_group.alb", "id"),
            ref("aws_lb_listener.http", "load_balancer_arn", "aws_lb.alb", "arn"),
            ref("aws_lb_listener.http", "default_action[0].target_group_arn", "aws_lb_target_group.tg", "arn"),
            ref("aws_lb_listener.admin", "load_balancer_arn", "aws_lb.alb", "arn"),
            ref("aws_ecs_service.svc", "load_balancer[0].target_group_arn", "aws_lb_target_group.tg", "arn"),
            ref("aws_ecs_service.svc", "network_configuration[0].security_groups[0]", "aws_security_group.app", "id"),
            ref("aws_db_instance.db", "vpc_security_group_ids[0]", "aws_security_group.db", "id"),
            ref("aws_security_group.db", "ingress[0].security_groups[0]", "aws_security_group.app", "id"),
            ref("aws_security_group.db", "ingress[1].security_groups[0]", "aws_security_group.app", "id"),
            ref("aws_vpc_security_group_ingress_rule.app_from_alb", "security_group_id", "aws_security_group.app", "id"),
            ref("aws_vpc_security_group_ingress_rule.app_from_alb", "referenced_security_group_id", "aws_security_group.alb", "id"),
            ref("aws_vpc_security_group_egress_rule.out", "security_group_id", "aws_security_group.app", "id"),
            ref("aws_security_group_rule.db_egress", "security_group_id", "aws_security_group.db", "id"),
        ])
        self.assertEqual(o.edges, {
            "alb/alb->ecs_service/svc": ("request", "HTTP 8080", "derived"),  # R-LB-TG が優先（R-SG の TCP 8080 より上）
            "ecs_service/svc->db_instance/db": ("network", "TCP 5432, TCP 6432", "derived"),  # 同じ規則の 2 つのラベルをつなぐ
            "external/internet->alb/alb": ("request", "HTTP 80", "derived"),  # 8443 のリスナーは SG が許さないので入れない
        })
        self.assertEqual(o.ev["external/internet->alb/alb"]["rules"], ["N-EXT-INTERNET", "R-LB-LISTENER", "R-SG"])
        self.assertEqual(o.ev["alb/alb->ecs_service/svc"]["rules"], ["R-LB-LISTENER", "R-LB-TG", "R-SG"])
        self.assertEqual(o.nodes[INTERNET], {"id": INTERNET, "type": "external", "category": "external", "name": "internet",
                                             "label": "Internet", "parent": None, "synthetic": True})
        # SG は送信先としても送信元としても、生んだ辺を into に並べる
        self.assertEqual(o.cls["aws_security_group.alb"], ("merged_into", "R-SG", ("alb/alb->ecs_service/svc", "external/internet->alb/alb")))
        self.assertEqual(o.cls["aws_security_group.app"], ("merged_into", "R-SG", ("alb/alb->ecs_service/svc", "ecs_service/svc->db_instance/db")))
        self.assertEqual(o.cls["aws_security_group.db"], ("merged_into", "R-SG", ("ecs_service/svc->db_instance/db",)))
        self.assertEqual(o.cls["aws_vpc_security_group_ingress_rule.app_from_alb"], ("merged_into", "R-SG", ("alb/alb->ecs_service/svc",)))
        self.assertEqual(o.cls["aws_lb_listener.http"][2], ("alb/alb->ecs_service/svc", "external/internet->alb/alb"))
        # egress は辺にしない（別リソースは H-SG-EGRESS）。転送も internet の辺も無いリスナーは H-RELATION-NOEDGE
        self.assertEqual(o.cls["aws_vpc_security_group_egress_rule.out"], ("hidden", "H-SG-EGRESS", ()))
        self.assertEqual(o.cls["aws_security_group_rule.db_egress"], ("hidden", "H-SG-EGRESS", ()))
        self.assertEqual(o.cls["aws_lb_listener.admin"], ("hidden", "H-RELATION-NOEDGE", ()))
        # 根拠は参照の `<from>.<path>` と、参照の無いもの（CIDR・internal）の `<address>.<位置> (<説明>)`
        ev = o.ev["external/internet->alb/alb"]["evidence"]
        self.assertIn("aws_security_group.alb.ingress[0].cidr_blocks (0.0.0.0/0)", ev)
        self.assertIn("aws_lb.alb.internal (false)", ev)
        self.assertIn("aws_lb_listener.http.port (80)", ev)
        self.assertNotIn("NORM-UNUSED-REF", o.codes)

    def test_self_reference_multiple_sgs_and_no_edge(self):
        o = Out("tf", [
            R("aws_instance.a", "aws_instance", tag("a")), R("aws_instance.b", "aws_instance", tag("b")),
            R("aws_instance.c", "aws_instance", tag("c")),
            R("aws_security_group.peer", "aws_security_group"), R("aws_security_group.mgmt", "aws_security_group"),
            R("aws_security_group.lonely", "aws_security_group", {"ingress": [{"protocol": "tcp", "from_port": 22, "to_port": 22,
                                                                             "self": True}]}),
            R("aws_security_group_rule.peer_self", "aws_security_group_rule", {"type": "ingress", "protocol": "-1",
                                                                              "from_port": 0, "to_port": 0, "self": True}),
            R("aws_security_group_rule.mgmt", "aws_security_group_rule", {"type": "ingress", "protocol": "tcp", "from_port": 22,
                                                                         "to_port": 22}),
            R("aws_security_group.unused", "aws_security_group", {"ingress": [{"protocol": "tcp", "from_port": 1, "to_port": 1,
                                                                             "cidr_blocks": ["0.0.0.0/0"]}]}),
        ], [
            ref("aws_instance.a", "vpc_security_group_ids[0]", "aws_security_group.peer", "id"),
            ref("aws_instance.b", "vpc_security_group_ids[0]", "aws_security_group.peer", "id"),
            ref("aws_instance.c", "vpc_security_group_ids[0]", "aws_security_group.mgmt", "id"),
            ref("aws_instance.c", "vpc_security_group_ids[1]", "aws_security_group.lonely", "id"),
            ref("aws_security_group_rule.peer_self", "security_group_id", "aws_security_group.peer", "id"),
            ref("aws_security_group_rule.mgmt", "security_group_id", "aws_security_group.peer", "id"),
            ref("aws_security_group_rule.mgmt", "source_security_group_id", "aws_security_group.mgmt", "id"),
        ])
        self.assertEqual(o.edges, {
            "ec2_instance/a->ec2_instance/b": ("network", "ALL", "derived"),  # self: 同じ SG を付けた異なるリソースの両向き
            "ec2_instance/b->ec2_instance/a": ("network", "ALL", "derived"),
            "ec2_instance/c->ec2_instance/a": ("network", "TCP 22", "derived"),  # 2 つ目の SG（mgmt）から
            "ec2_instance/c->ec2_instance/b": ("network", "TCP 22", "derived"),
        })
        self.assertEqual(o.cls["aws_security_group_rule.peer_self"][2], ("ec2_instance/a->ec2_instance/b", "ec2_instance/b->ec2_instance/a"))
        # 自分だけの self（自己ループ）、どこにも付いていない SG は辺を生まない → H-SG-NOEDGE
        self.assertEqual(o.cls["aws_security_group.lonely"], ("hidden", "H-SG-NOEDGE", ()))
        self.assertEqual(o.cls["aws_security_group.unused"], ("hidden", "H-SG-NOEDGE", ()))
        self.assertNotIn(INTERNET, o.nodes)

    def test_cidr_sources_and_public_ec2(self):
        o = Out("tf", [
            R("aws_instance.pub", "aws_instance", tag("pub", associate_public_ip_address=True)),
            R("aws_instance.priv", "aws_instance", tag("priv")),
            R("aws_security_group.ssh", "aws_security_group", {"ingress": [
                {"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr_blocks": ["0.0.0.0/0"]},
                {"protocol": "tcp", "from_port": 443, "to_port": 443, "ipv6_cidr_blocks": ["::/0"]},
                {"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr_blocks": ["10.0.0.0/16"]}]}),  # VPC の中の CIDR は辺にしない
        ], [
            ref("aws_instance.pub", "vpc_security_group_ids[0]", "aws_security_group.ssh", "id"),
            ref("aws_instance.priv", "vpc_security_group_ids[0]", "aws_security_group.ssh", "id"),
        ])
        # パブリック IP を持つ EC2 だけ internet から（R-SG だけの辺なので kind は network）
        self.assertEqual(o.edges, {"external/internet->ec2_instance/pub": ("network", "TCP 22, TCP 443", "derived")})
        self.assertEqual(o.ev["external/internet->ec2_instance/pub"]["rules"], ["R-SG"])
        self.assertIn(INTERNET, o.nodes)

    def test_public_subnet_ec2_and_launch_template(self):
        # map_public_ip_on_launch のパブリックサブネットの EC2、起動テンプレート（M-LAUNCH-TEMPLATE → それを使う EC2）の SG
        o = Out("tf", [
            R("aws_vpc.v", "aws_vpc", tag("v")), R("aws_internet_gateway.igw", "aws_internet_gateway", tag("igw")),
            R("aws_subnet.pub", "aws_subnet", tag("pub", map_public_ip_on_launch=True)),
            R("aws_route_table.rt", "aws_route_table", {"route": [{"cidr_block": "0.0.0.0/0"}]}),
            R("aws_route_table_association.a", "aws_route_table_association"),
            R("aws_instance.web", "aws_instance", tag("web")),
            R("aws_launch_template.lt", "aws_launch_template", {"name": "lt"}),
            R("aws_instance.worker", "aws_instance", tag("worker")),
            R("aws_security_group.web", "aws_security_group", {"ingress": [
                {"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr_blocks": ["0.0.0.0/0"]}]}),
            R("aws_security_group.workers", "aws_security_group", {"ingress": [
                {"protocol": "tcp", "from_port": 9000, "to_port": 9000, "security_groups": [{"$res": "aws_security_group.web"}]}]}),
        ], [
            ref("aws_internet_gateway.igw", "vpc_id", "aws_vpc.v", "id"), ref("aws_subnet.pub", "vpc_id", "aws_vpc.v", "id"),
            ref("aws_route_table.rt", "route[0].gateway_id", "aws_internet_gateway.igw", "id"),
            ref("aws_route_table_association.a", "route_table_id", "aws_route_table.rt", "id"),
            ref("aws_route_table_association.a", "subnet_id", "aws_subnet.pub", "id"),
            ref("aws_instance.web", "subnet_id", "aws_subnet.pub", "id"),
            ref("aws_instance.web", "vpc_security_group_ids[0]", "aws_security_group.web", "id"),
            ref("aws_instance.worker", "launch_template[0].id", "aws_launch_template.lt", "id"),
            ref("aws_launch_template.lt", "vpc_security_group_ids[0]", "aws_security_group.workers", "id"),
            ref("aws_security_group.workers", "ingress[0].security_groups[0]", "aws_security_group.web", "id"),
        ])
        self.assertEqual(o.cls["aws_launch_template.lt"], ("merged_into", "M-LAUNCH-TEMPLATE", ("ec2_instance/worker",)))
        self.assertEqual(o.edges["external/internet->ec2_instance/web"], ("network", "TCP 80", "derived"))
        self.assertEqual(o.edges["ec2_instance/web->ec2_instance/worker"], ("network", "TCP 9000", "derived"))
        self.assertIn("aws_instance.web.subnet_id (map_public_ip_on_launch のパブリックサブネット)",
                      o.ev["external/internet->ec2_instance/web"]["evidence"])

    def test_public_subnet_with_explicit_no_public_ip(self):
        # associate_public_ip_address が偽・決まらない値なら、map_public_ip_on_launch のパブリックサブネットでも公開しない
        for value in (False, {"$unknown": "x"}):
            with self.subTest(value):
                o = Out("tf", [
                    R("aws_vpc.v", "aws_vpc", tag("v")), R("aws_internet_gateway.igw", "aws_internet_gateway", tag("igw")),
                    R("aws_subnet.pub", "aws_subnet", tag("pub", map_public_ip_on_launch=True)),
                    R("aws_route_table.rt", "aws_route_table", {"route": [{"cidr_block": "0.0.0.0/0"}]}),
                    R("aws_route_table_association.a", "aws_route_table_association"),
                    R("aws_instance.web", "aws_instance", tag("web", associate_public_ip_address=value)),
                    R("aws_security_group.web", "aws_security_group", {"ingress": [
                        {"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr_blocks": ["0.0.0.0/0"]}]}),
                ], [
                    ref("aws_internet_gateway.igw", "vpc_id", "aws_vpc.v", "id"), ref("aws_subnet.pub", "vpc_id", "aws_vpc.v", "id"),
                    ref("aws_route_table.rt", "route[0].gateway_id", "aws_internet_gateway.igw", "id"),
                    ref("aws_route_table_association.a", "route_table_id", "aws_route_table.rt", "id"),
                    ref("aws_route_table_association.a", "subnet_id", "aws_subnet.pub", "id"),
                    ref("aws_instance.web", "subnet_id", "aws_subnet.pub", "id"),
                    ref("aws_instance.web", "vpc_security_group_ids[0]", "aws_security_group.web", "id"),
                ])
                self.assertNotIn("external/internet->ec2_instance/web", o.edges)
                self.assertEqual(o.cls["aws_security_group.web"], ("hidden", "H-SG-NOEDGE", ()))
                self.assertNotIn(INTERNET, o.nodes)

    def test_inline_self_between_two_instances(self):
        # インラインの self = true: 同じ SG を付けた 2 つのインスタンスの両向き。ラベルはポートの範囲
        o = Out("tf", [
            R("aws_instance.a", "aws_instance", tag("a")), R("aws_instance.b", "aws_instance", tag("b")),
            R("aws_security_group.cluster", "aws_security_group", {"ingress": [
                {"protocol": "tcp", "from_port": 7000, "to_port": 7100, "self": True}]}),
        ], [
            ref("aws_instance.a", "vpc_security_group_ids[0]", "aws_security_group.cluster", "id"),
            ref("aws_instance.b", "vpc_security_group_ids[0]", "aws_security_group.cluster", "id"),
        ])
        self.assertEqual(o.edges, {"ec2_instance/a->ec2_instance/b": ("network", "TCP 7000-7100", "derived"),
                                   "ec2_instance/b->ec2_instance/a": ("network", "TCP 7000-7100", "derived")})
        self.assertIn("aws_security_group.cluster.ingress[0].self (true)", o.ev["ec2_instance/a->ec2_instance/b"]["evidence"])
        self.assertEqual(o.cls["aws_security_group.cluster"][2], ("ec2_instance/a->ec2_instance/b", "ec2_instance/b->ec2_instance/a"))

    def test_lb_other_than_alb_gets_no_internet_edge(self):
        # NLB（load_balancer_type = network）と CLB（aws_elb）は N-EXT-INTERNET・R-SG の公開の対象（alb）に入らない
        for lb in (R("aws_lb.n", "aws_lb", {"name": "n", "load_balancer_type": "network"}), R("aws_elb.n", "aws_elb", {"name": "n"})):
            with self.subTest(lb["type"]):
                o = Out("tf", [
                    lb, R("aws_lb_listener.l", "aws_lb_listener", {"port": 80, "protocol": "TCP"}),
                    R("aws_security_group.s", "aws_security_group", {"ingress": [
                        {"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr_blocks": ["0.0.0.0/0"]}]}),
                ], [ref(lb["address"], "security_groups[0]", "aws_security_group.s", "id"),
                    ref("aws_lb_listener.l", "load_balancer_arn", lb["address"], "arn")])
                self.assertEqual([e for e in o.edges if e.startswith(INTERNET)], [])
                self.assertNotIn(INTERNET, o.nodes)
                self.assertEqual(o.cls["aws_security_group.s"], ("hidden", "H-SG-NOEDGE", ()))


class CfnSgTest(unittest.TestCase):
    def test_inline_separate_lambda_and_scheme(self):
        o = Out("cfn", [
            C("Alb", "AWS::ElasticLoadBalancingV2::LoadBalancer", {"Name": "alb"}),  # Scheme が無ければ internet-facing
            C("Listener", "AWS::ElasticLoadBalancingV2::Listener", {"Port": 443, "Protocol": "HTTPS"}),
            C("Fn", "AWS::Lambda::Function", {"FunctionName": "fn"}),
            C("Db", "AWS::RDS::DBInstance", {"DBInstanceIdentifier": "db"}),
            C("AlbSg", "AWS::EC2::SecurityGroup", {"SecurityGroupIngress": [
                {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "CidrIpv6": "::/0"}]}),
            C("FnSg", "AWS::EC2::SecurityGroup", {"SecurityGroupEgress": [{"IpProtocol": "-1", "CidrIp": "0.0.0.0/0"}]}),
            C("DbSg", "AWS::EC2::SecurityGroup", {"SecurityGroupIngress": [
                {"IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432, "SourceSecurityGroupId": {"$res": "FnSg"}}]}),
            C("DbFromAlb", "AWS::EC2::SecurityGroupIngress", {"IpProtocol": "-1"}),
            C("Egress", "AWS::EC2::SecurityGroupEgress", {"IpProtocol": "-1"}),
        ], [
            ref("Listener", "Properties.LoadBalancerArn", "Alb"),
            ref("Alb", "Properties.SecurityGroups[0]", "AlbSg"),
            ref("Fn", "Properties.VpcConfig.SecurityGroupIds[0]", "FnSg"),
            ref("Db", "Properties.VPCSecurityGroups[0]", "DbSg"),
            ref("DbSg", "Properties.SecurityGroupIngress[0].SourceSecurityGroupId", "FnSg"),
            ref("DbFromAlb", "Properties.GroupId", "DbSg"), ref("DbFromAlb", "Properties.SourceSecurityGroupId", "AlbSg"),
            ref("Egress", "Properties.GroupId", "FnSg"),
        ])
        self.assertEqual(o.edges, {
            "lambda_function/fn->db_instance/db": ("network", "TCP 5432", "derived"),
            "alb/alb->db_instance/db": ("network", "ALL", "derived"),
            "external/internet->alb/alb": ("request", "HTTPS 443", "derived"),  # ::/0 も 0.0.0.0/0 と同じに扱う
        })
        self.assertEqual(o.cls["DbFromAlb"], ("merged_into", "R-SG", ("alb/alb->db_instance/db",)))
        self.assertEqual(o.cls["Egress"], ("hidden", "H-SG-EGRESS", ()))
        self.assertIn("Alb.Properties.Scheme (既定値 internet-facing)", o.ev["external/internet->alb/alb"]["evidence"])
        self.assertIn("AlbSg.Properties.SecurityGroupIngress[0].CidrIpv6 (::/0)", o.ev["external/internet->alb/alb"]["evidence"])

    def test_network_interfaces_public_ip(self):
        # CFN の NetworkInterfaces[].AssociatePublicIpAddress が真なら公開。偽ならサブネットに依らず公開しない
        for value, want in ((True, True), (False, False)):
            with self.subTest(value):
                o = Out("cfn", [
                    C("Web", "AWS::EC2::Instance", {"Tags": [{"Key": "Name", "Value": "web"}], "NetworkInterfaces": [
                        {"DeviceIndex": "0", "AssociatePublicIpAddress": value}]}),
                    C("Sg", "AWS::EC2::SecurityGroup", {"SecurityGroupIngress": [
                        {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "CidrIp": "0.0.0.0/0"}]}),
                ], [ref("Web", "Properties.SecurityGroupIds[0]", "Sg")])
                eid = "external/internet->ec2_instance/web"
                self.assertEqual(eid in o.edges, want)
                if want:
                    self.assertEqual(o.edges[eid], ("network", "TCP 22", "derived"))
                    self.assertIn("Web.Properties.NetworkInterfaces[0].AssociatePublicIpAddress (true)", o.ev[eid]["evidence"])


class InternetTest(unittest.TestCase):
    def lb(self, fmt, lb_props, ingress):
        rules = ingress if isinstance(ingress, list) else [ingress]
        if fmt == "tf":
            return Out("tf", [
                R("aws_lb.alb", "aws_lb", {"name": "alb", **lb_props}),
                R("aws_lb_listener.l", "aws_lb_listener", {"port": 80, "protocol": "HTTP"}),
                R("aws_security_group.s", "aws_security_group", {"ingress": rules}),
            ], [ref("aws_lb.alb", "security_groups[0]", "aws_security_group.s", "id"),
                ref("aws_lb_listener.l", "load_balancer_arn", "aws_lb.alb", "arn")])
        return Out("cfn", [
            C("Alb", "AWS::ElasticLoadBalancingV2::LoadBalancer", {"Name": "alb", **lb_props}),
            C("L", "AWS::ElasticLoadBalancingV2::Listener", {"Port": 80, "Protocol": "HTTP"}),
            C("S", "AWS::EC2::SecurityGroup", {"SecurityGroupIngress": rules}),
        ], [ref("Alb", "Properties.SecurityGroups[0]", "S"), ref("L", "Properties.LoadBalancerArn", "Alb")])

    def test_lb_conditions(self):
        open_tf = {"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr_blocks": ["0.0.0.0/0"]}
        open_cfn = {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "CidrIp": "0.0.0.0/0"}
        cases = [
            ("インターネット向け（TF の既定）", "tf", {}, open_tf, True),
            ("internal = true", "tf", {"internal": True}, open_tf, False),
            ("internal が決まらない", "tf", {"internal": {"$unknown": "x"}}, open_tf, False),
            ("0.0.0.0/0 を許さない", "tf", {}, {**open_tf, "cidr_blocks": ["10.0.0.0/8"]}, False),
            ("リスナーのポートを許さない", "tf", {}, {**open_tf, "from_port": 443, "to_port": 443}, False),
            ("全ポート", "tf", {}, {"protocol": "-1", "from_port": 0, "to_port": 0, "cidr_blocks": ["0.0.0.0/0"]}, True),
            ("Scheme: internet-facing", "cfn", {"Scheme": "internet-facing"}, open_cfn, True),
            ("Scheme: internal", "cfn", {"Scheme": "internal"}, open_cfn, False),
            # TCP のポートが決まるルールだけがリスナーに当たる（決まらない internal を公開としないのと同じ）
            ("ICMP", "tf", {}, {"protocol": "icmp", "from_port": -1, "to_port": -1, "cidr_blocks": ["0.0.0.0/0"]}, False),
            ("UDP 80", "tf", {}, {**open_tf, "protocol": "udp"}, False),
            ("ポートが決まらない", "tf", {}, {**open_tf, "from_port": {"$unknown": "x"}}, False),
            ("プロトコルが決まらない", "tf", {}, {**open_tf, "protocol": {"$unknown": "x"}}, False),
            ("CFN の UDP 80", "cfn", {}, {**open_cfn, "IpProtocol": "udp"}, False),
        ]
        for label, fmt, lb_props, ingress, want in cases:
            with self.subTest(label):
                o = self.lb(fmt, lb_props, ingress)
                self.assertEqual("external/internet->alb/alb" in o.edges, want, o.edges)
                self.assertEqual(INTERNET in o.nodes, want)
                if not want:  # 辺を生まない SG は H-SG-NOEDGE、リスナーは（転送も無いので）H-RELATION-NOEDGE
                    self.assertEqual(o.cls["aws_security_group.s" if fmt == "tf" else "S"][1], "H-SG-NOEDGE")
                    self.assertIn("NORM-RELATION-NOEDGE", o.codes)

    def test_only_rules_for_emitted_listeners_join_the_edge(self):
        # TCP 22 の 0.0.0.0/0 は 80 のリスナーに当たらないので、internet → LB の根拠に入れない
        o = self.lb("tf", {}, [{"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr_blocks": ["0.0.0.0/0"]},
                               {"protocol": "tcp", "from_port": 22, "to_port": 22, "ipv6_cidr_blocks": ["::/0"]}])
        eid = "external/internet->alb/alb"
        self.assertEqual(o.edges, {eid: ("request", "HTTP 80", "derived")})
        ev = o.ev[eid]["evidence"]
        self.assertIn("aws_security_group.s.ingress[0].cidr_blocks (0.0.0.0/0)", ev)
        self.assertFalse([x for x in ev if "ingress[1]" in x], ev)
        # 別リソースのルールなら、当たらないルールは H-SG-NOEDGE
        o = Out("tf", [
            R("aws_lb.alb", "aws_lb", {"name": "alb"}),
            R("aws_lb_listener.l", "aws_lb_listener", {"port": 80, "protocol": "HTTP"}),
            R("aws_security_group.s", "aws_security_group"),
            R("aws_vpc_security_group_ingress_rule.http", "aws_vpc_security_group_ingress_rule",
              {"cidr_ipv4": "0.0.0.0/0", "ip_protocol": "tcp", "from_port": 80, "to_port": 80}),
            R("aws_vpc_security_group_ingress_rule.ssh", "aws_vpc_security_group_ingress_rule",
              {"cidr_ipv4": "0.0.0.0/0", "ip_protocol": "tcp", "from_port": 22, "to_port": 22}),
        ], [ref("aws_lb.alb", "security_groups[0]", "aws_security_group.s", "id"),
            ref("aws_lb_listener.l", "load_balancer_arn", "aws_lb.alb", "arn"),
            ref("aws_vpc_security_group_ingress_rule.http", "security_group_id", "aws_security_group.s", "id"),
            ref("aws_vpc_security_group_ingress_rule.ssh", "security_group_id", "aws_security_group.s", "id")])
        self.assertEqual(o.cls["aws_vpc_security_group_ingress_rule.http"], ("merged_into", "R-SG", (eid,)))
        self.assertEqual(o.cls["aws_vpc_security_group_ingress_rule.ssh"], ("hidden", "H-SG-NOEDGE", ()))
        self.assertFalse([x for x in o.ev[eid]["evidence"] if ".ssh." in x])

    def test_api_gateway(self):
        cases = [
            ("HTTP API", "tf", R("aws_apigatewayv2_api.a", "aws_apigatewayv2_api", {"name": "a", "protocol_type": "HTTP"}),
             "apigw_http_api/a", True),
            ("REST の既定（EDGE）", "tf", R("aws_api_gateway_rest_api.a", "aws_api_gateway_rest_api", {"name": "a"}),
             "apigw_rest_api/a", True),
            ("REST の REGIONAL", "tf", R("aws_api_gateway_rest_api.a", "aws_api_gateway_rest_api",
                                         {"name": "a", "endpoint_configuration": [{"types": ["REGIONAL"]}]}), "apigw_rest_api/a", True),
            ("REST の PRIVATE", "tf", R("aws_api_gateway_rest_api.a", "aws_api_gateway_rest_api",
                                        {"name": "a", "endpoint_configuration": [{"types": ["PRIVATE"]}]}), "apigw_rest_api/a", False),
            ("CFN の PRIVATE", "cfn", C("A", "AWS::ApiGateway::RestApi", {"Name": "a", "EndpointConfiguration": {"Types": ["PRIVATE"]}}),
             "apigw_rest_api/a", False),
            ("SAM の短い形 PRIVATE", "cfn", C("A", "AWS::Serverless::Api", {"Name": "a", "EndpointConfiguration": "PRIVATE"}),
             "apigw_rest_api/a", False),
            ("SAM の Type: REGIONAL", "cfn", C("A", "AWS::Serverless::Api", {"Name": "a", "EndpointConfiguration": {"Type": "REGIONAL"}}),
             "apigw_rest_api/a", True),
            ("種類が決まらない", "tf", R("aws_api_gateway_rest_api.a", "aws_api_gateway_rest_api",
                                         {"name": "a", "endpoint_configuration": [{"types": {"$unknown": "x"}}]}), "apigw_rest_api/a", False),
            ("SAM の HttpApi", "cfn", C("A", "AWS::Serverless::HttpApi", {"Name": "a"}), "apigw_http_api/a", True),
            # WebSocket の API は HTTPS の入口として描かない（描く型にもならない）
            ("WebSocket", "tf", R("aws_apigatewayv2_api.a", "aws_apigatewayv2_api", {"name": "a", "protocol_type": "WEBSOCKET"}),
             "apigw_http_api/a", False),
            ("CFN の WebSocket", "cfn", C("A", "AWS::ApiGatewayV2::Api", {"Name": "a", "ProtocolType": "WEBSOCKET"}),
             "apigw_http_api/a", False),
        ]
        for label, fmt, res, node, want in cases:
            with self.subTest(label):
                o = Out(fmt, [res], [])
                eid = f"{INTERNET}->{node}"
                self.assertEqual(o.edges, {eid: ("request", "HTTPS", "derived")} if want else {})
                self.assertEqual(INTERNET in o.nodes, want)
                if want:
                    self.assertEqual(o.ev[eid]["rules"], ["N-EXT-INTERNET"])


if __name__ == "__main__":
    unittest.main()
