"""Terraform アダプタ: レジストリの module の要約表（data/module-summaries/）。版の選び方、展開、診断、H-IAM、要約表のフォルダが
欠けたときの警告。本体は aws_iac_diagram/adapters/terraform/modules/（summaries.py・resolve.py・sources.py）。
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# tests/ を import の道に入れる（`python tests/.../test_x.py` で直接動かすときのため。discover では要らないが害は無い）
sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "support").is_dir())))
from support.builders import assert_valid, props, refs, res_of
from support.paths import PUBLIC, SCRIPTS, WS
from support.terraform import build, codes, res
from aws_iac_diagram.adapters.terraform import (  # noqa: E402
    build as tf_build,
    model,
    module_emit,
    module_eval,
    module_load,
)
from aws_iac_diagram.adapters.terraform.evaluator import values as V  # noqa: E402
from aws_iac_diagram.adapters.terraform.modules import resolve as MR, summaries as MS  # noqa: E402
from aws_iac_diagram.adapters.terraform.modules.sources import is_local, join_summary_source, registry_key  # noqa: E402


def build_module_call(source: str, body: str, version: str | None = None) -> dict:
    """モジュールの呼び出し1つのルートを作って読む（source はルートからの相対パスかレジストリの source）。"""
    local = not registry_key(source) and not source.startswith(".")
    # ルートからの相対パスで書くので、一時フォルダは source と同じドライブに置く
    # （Windows の CI はリポジトリが D:、既定の一時フォルダが C: で、相対パスが作れない）
    with tempfile.TemporaryDirectory(dir=WS if local else None, prefix="tmp-") as tmp:
        if local:
            source = os.path.relpath(source, tmp).replace("\\", "/")
        ver = f'  version = "{version}"\n' if version else ""
        Path(tmp, "main.tf").write_text(f'module "m" {{\n  source = "{source}"\n{ver}{body}\n}}\n'
                                        'data "aws_availability_zones" "available" {}\n', encoding="utf-8")
        return tf_build.build_raw(Path(tmp), Path(tmp))


class SummaryTest(unittest.TestCase):
    """手順3: A5 の要約表（data/module-summaries/）、版の選び方、黒箱、H-IAM。"""

    def test_summary_file(self):
        summaries, iam = MS.load()
        self.assertEqual(sorted(summaries), sorted([
            "terraform-aws-modules/vpc/aws", "terraform-aws-modules/alb/aws", "terraform-aws-modules/rds/aws",
            "terraform-aws-modules/rds/aws//modules/db_instance", "terraform-aws-modules/rds/aws//modules/db_subnet_group",
            "terraform-aws-modules/rds/aws//modules/db_parameter_group",
            "terraform-aws-modules/rds/aws//modules/db_option_group",
            "terraform-aws-modules/rds/aws//modules/db_instance_role_association", "terraform-aws-modules/eks/aws",
            "terraform-aws-modules/eks/aws//modules/eks-managed-node-group",
            "terraform-aws-modules/eks/aws//modules/fargate-profile",
            "terraform-aws-modules/eks/aws//modules/self-managed-node-group"]))
        self.assertEqual(iam, ("terraform-aws-modules/iam/aws",))
        for key, items in summaries.items():
            for s in items:
                with self.subTest(key):
                    tree = module_load.summary_tree(s)  # HCL として読める
                    mod = module_eval.ModuleEval(model.Context(Path(".")), None)
                    mod.summary = s
                    mod.collect(tree, "main.tf")
                    self.assertTrue(mod.outputs)
                    # 表の中の data は擬似パラメータに使うもの（引数の無い aws_partition など）だけ
                    for blk in mod.blocks.values():
                        if blk.kind == "data":
                            self.assertTrue(blk.plain and not blk.attrs, blk.base)
        self.assertIn("enable_flow_log", summaries["terraform-aws-modules/vpc/aws"][0].uncovered)
        self.assertIn("listeners.*.authenticate_cognito", summaries["terraform-aws-modules/alb/aws"][0].uncovered)

    def test_choose_version(self):
        def pick(source, version):
            s, why, note = MR.choose(source, version)
            return (s.majors if s else None), why, note
        vpc = "terraform-aws-modules/vpc/aws"
        self.assertEqual(pick(vpc, "~> 6.7")[0], (6,))
        self.assertEqual(pick(vpc, "6.6.0")[:3], ((6,), "", None))
        self.assertEqual(pick(vpc, ">= 6.0, < 7.0")[:3], ((6,), "", None))
        self.assertIn("allows majors 5 to 6", pick(vpc, ">= 5.0, < 7.0")[2])  # 2つの major にまたがる
        self.assertEqual(pick("registry.terraform.io/" + vpc, "~> 6.0")[0], (6,))
        got = pick(vpc, None)
        self.assertEqual(got[0], (6,))
        self.assertIn("not pinned", got[2])
        self.assertIn("no upper major", pick(vpc, ">= 5.0")[2])
        for v in ("~> 5.0", "5.8.1", "2.77.0", "< 6.0"):
            with self.subTest(v):
                majors, why, _ = pick(vpc, v)
                self.assertIsNone(majors)
                self.assertIn("it has 6.x", why)
        self.assertEqual(pick("terraform-aws-modules/eks/aws", "~> 21.0")[0], (21,))
        self.assertIsNone(pick("terraform-aws-modules/eks/aws", "20.8.5")[0])
        self.assertEqual(pick("terraform-aws-modules/rds/aws//modules/db_instance", "~> 7.0")[0], (7,))
        self.assertIsNone(pick("terraform-aws-modules/s3-bucket/aws", "~> 4.0")[0])
        self.assertIsNone(pick(vpc, "~> foo")[0])

    def test_source_kinds_and_iam_only(self):
        self.assertTrue(is_local("./modules/x") and is_local("../../") and not is_local("modules/x"))
        self.assertEqual(registry_key("terraform-aws-modules/iam/aws//modules/iam-role/"),
                         "terraform-aws-modules/iam/aws//modules/iam-role")
        for src in ("git::https://example.com/x.git", "github.com/org/repo", "s3::https://b/x.zip",
                    "https://example.com/x.zip", "hashicorp/consul/aws?ref=1"):
            self.assertIsNone(registry_key(src), src)
        self.assertEqual(join_summary_source("terraform-aws-modules/rds/aws", "./modules/db_instance"),
                         "terraform-aws-modules/rds/aws//modules/db_instance")
        self.assertEqual(join_summary_source("a/b/c//modules/x", "../y"), "a/b/c//modules/y")
        self.assertTrue(MS.iam_only("terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"))
        self.assertTrue(MS.iam_only("registry.terraform.io/terraform-aws-modules/iam/aws"))
        self.assertFalse(MS.iam_only("terraform-aws-modules/iam-foo/aws"))
        self.assertFalse(MS.iam_only("terraform-aws-modules/vpc/aws"))
        # IAM だけのモジュールは黒箱の呼び出し（正規化が H-IAM にする）。理由に H-IAM と書く
        raw = build("""
        module "irsa" {
          source  = "terraform-aws-modules/iam/aws//modules/iam-assumable-role-with-oidc"
          version = "5.39.0"
          role_name = "x"
        }
        """)
        assert_valid(self, raw)
        r = res_of(raw, "module.irsa")
        self.assertEqual((r["type"], r["via"], r["version"]), ("module", "module_blackbox", "5.39.0"))
        msg = next(d["message"] for d in raw["diagnostics"] if d["code"] == "TF-MODULE-BLACKBOX")
        self.assertIn("H-IAM", msg)

    def test_summary_expansion_diagnostics(self):
        raw = build("""
        module "vpc" {
          source  = "terraform-aws-modules/vpc/aws"
          version = "~> 6.0"
          name    = "n"
          azs     = ["ap-northeast-1a"]
          public_subnets  = ["10.0.0.0/24"]
          enable_flow_log = true
          not_a_variable  = 1
          region          = "us-west-2"
        }
        module "old" {
          source  = "terraform-aws-modules/vpc/aws"
          version = "5.8.1"
          name    = "old"
        }
        resource "aws_instance" "x" {
          subnet_id = module.vpc.public_subnets[0]
          acl       = module.vpc.public_network_acl_id
        }
        """)
        assert_valid(self, raw)
        sub = res_of(raw, "module.vpc.aws_subnet.public[0]")
        self.assertEqual((sub["via"], sub["file"], sub["module"], sub["region"]),
                         ("module_summary", "main.tf", "module.vpc", "us-west-2"))
        self.assertEqual(sub["props"]["tags"], {"Name": "n-public-ap-northeast-1a"})
        self.assertNotIn("module.vpc.aws_nat_gateway.this", [r["address"] for r in raw["resources"]])  # count 0 は載せない
        diags = {d["code"]: d for d in raw["diagnostics"] if d.get("address") == "module.vpc"}
        self.assertIn("TF-MODULE-SUMMARY", diags)
        self.assertIn("enable_flow_log, not_a_variable", diags["TF-MODULE-SUMMARY-INPUT"]["message"])
        old = res_of(raw, "module.old")
        self.assertEqual((old["via"], old["version"]), ("module_blackbox", "5.8.1"))
        self.assertIn("it has 6.x", next(d["message"] for d in raw["diagnostics"] if d["address"] == "module.old"))
        p = props(raw, "aws_instance.x")
        self.assertEqual(p["subnet_id"], res("module.vpc.aws_subnet.public[0]", "id"))
        self.assertIn("$unknown", p["acl"])  # 要約表に無い出力
        self.assertIn("TF-MODULE-SUMMARY-OUTPUT", codes(raw, "aws_instance.x"))
        self.assertFalse([k for k in raw["evaluation"]["vars"] if k.startswith("module.")])  # 要約表の変数は書かない

    def compare_with_source(self, real_dir: Path, source: str, version: str, body: str, allowed: set):
        """同じ入力で、手元の本物のソースと要約表を展開し、address と、要約表のリソースの間の参照を比べる。"""
        real = build_module_call(str(real_dir), body)
        summ = build_module_call(source, body, version)
        for raw in (real, summ):
            assert_valid(self, raw)

        def made(raw):
            return {r["address"]: r for r in raw["resources"] if r["enabled"] is not False
                    and not r["address"].startswith("data.") and ".data." not in r["address"]}
        a, b = made(real), made(summ)
        self.assertEqual(set(a) ^ set(b), allowed)
        def act(raw, keep):
            return {(r["from"], r["path"], r["to"], r["attr"]) for r in raw["references"]
                    if r["state"] == "active" and r["from"] in keep and r["to"] in keep}
        common = set(a) & set(b)
        self.assertEqual(act(real, common), act(summ, common))
        for addr in sorted(common):
            for k in ("tags", "name", "cluster_name", "node_group_name", "fargate_profile_name"):
                self.assertEqual(a[addr]["props"].get(k), b[addr]["props"].get(k), (addr, k))
        self.assertFalse([d for d in summ["diagnostics"] if d["level"] != "info"])
        return b

    def test_alb_summary_matches_source(self):
        src = PUBLIC / "terraform-aws-alb"  # v10.5.1（2026-10-17 に取得）
        three_tier = '''
  name               = "demo-alb"
  load_balancer_type = "application"
  vpc_id             = "vpc-1"
  subnets            = ["subnet-a", "subnet-b"]
  enable_deletion_protection = false
  security_group_ingress_rules = {
    all_http = { from_port = 80, to_port = 80, ip_protocol = "tcp", cidr_ipv4 = "0.0.0.0/0" }
  }
  security_group_egress_rules = { all = { ip_protocol = "-1", cidr_ipv4 = "10.0.0.0/16" } }
  listeners = {
    http = { port = 80, protocol = "HTTP", forward = { target_group_key = "app" } }
  }
  target_groups = {
    app = { name = "demo-app", protocol = "HTTP", port = 8080, target_type = "ip", create_attachment = false,
            health_check = { path = "/" } }
  }
  tags = { Project = "demo" }'''
        got = self.compare_with_source(src, "terraform-aws-modules/alb/aws", "~> 10.0", three_tier, set())
        self.assertEqual(len(got), 6)
        rules = '''
  name    = "ex"
  vpc_id  = "vpc-1"
  subnets = ["subnet-a", "subnet-b"]
  listeners = {
    ex-http = {
      port = 80
      protocol = "HTTP"
      fixed_response = { content_type = "text/plain", message_body = "404", status_code = "404" }
      rules = {
        production = {
          priority = 1
          actions = [{ weighted_forward = { target_groups = [{ target_group_key = "ex-ecs", weight = 100 },
                                                             { target_group_key = "ex-alt", weight = 0 }] } }]
          conditions = [{ path_pattern = { values = ["/*"] } }]
        }
        fwd = {
          priority = 2
          actions = [{ forward = { target_group_key = "ex-alt" } }]
          conditions = [{ host_header = { values = ["a.example.com"] } }]
        }
      }
    }
    https = {
      port = 443
      protocol = "HTTPS"
      certificate_arn = "arn:aws:acm:us-east-1:111122223333:certificate/a"
      additional_certificate_arns = ["arn:aws:acm:us-east-1:111122223333:certificate/b"]
      weighted_forward = { target_groups = [{ target_group_key = "ex-ecs", weight = 1 }] }
    }
    redirect = {
      port = 8080
      redirect = { port = "443", protocol = "HTTPS", status_code = "HTTP_301" }
    }
  }
  target_groups = {
    ex-ecs = { protocol = "HTTP", port = 80, target_type = "ip", create_attachment = false }
    ex-alt = { protocol = "HTTP", port = 80, target_type = "ip", create_attachment = false }
    lambda = { target_type = "lambda", target_id = "arn:aws:lambda:us-east-1:111122223333:function:fn",
               attach_lambda_permission = true }
  }
  route53_records = { a = { zone_id = "Z1", type = "A" } }'''
        got = self.compare_with_source(src, "terraform-aws-modules/alb/aws", "~> 10.0", rules, set())
        self.assertEqual(len(got), 14)
        for a in ('module.m.aws_lb_listener_rule.this["ex-http/production"]', 'module.m.aws_lambda_permission.this["lambda"]',
                  'module.m.aws_lb_listener_certificate.this["https/0"]', 'module.m.aws_route53_record.this["a"]'):
            self.assertIn(a, got)

    def test_rds_summary_matches_source(self):
        src = PUBLIC / "terraform-aws-rds"  # v7.2.2（2026-10-17 に取得）
        fixture = '''
  identifier = "demo-db"
  engine = "postgres"
  engine_version = "17.9"
  family = "postgres17"
  major_engine_version = "17"
  instance_class = "db.t4g.micro"
  allocated_storage = 20
  db_name = "app"
  username = "app_admin"
  port = "5432"
  manage_master_user_password = true
  db_subnet_group_name = "grp"
  vpc_security_group_ids = ["sg-1"]
  create_db_subnet_group = false
  create_db_parameter_group = false
  create_db_option_group = false
  create_monitoring_role = false
  skip_final_snapshot = true
  tags = { Project = "demo" }'''
        got = self.compare_with_source(src, "terraform-aws-modules/rds/aws", "~> 7.0", fixture, set())
        self.assertEqual(list(got), ["module.m.module.db_instance.aws_db_instance.this[0]"])
        mysql = '''
  identifier = "my"
  engine = "mysql"
  engine_version = "8.0"
  family = "mysql8.0"
  major_engine_version = "8.0"
  instance_class = "db.t4g.large"
  allocated_storage = 20
  db_name = "app"
  username = "u"
  port = 3306
  subnet_ids = ["subnet-a", "subnet-b"]
  create_db_subnet_group = true
  vpc_security_group_ids = ["sg-1"]
  monitoring_interval = 30
  create_monitoring_role = true
  enabled_cloudwatch_logs_exports = ["general"]
  create_cloudwatch_log_group = true
  multi_az = true'''
        got = self.compare_with_source(src, "terraform-aws-modules/rds/aws", "~> 7.0", mysql, set())
        self.assertEqual(len(got), 8)
        self.assertIn('module.m.module.db_instance.aws_cloudwatch_log_group.this["general"]', got)

    def test_summary_nested_uncovered_inputs(self):
        # レビュー M1: 写していない入力が入れ子のキー（listeners の中の認証など）でも、渡されたら診断に書く。
        # weighted_forward とルールの forward は写したので、リスナー・ルール → TG の参照が出る
        raw = build("""
        module "alb" {
          source  = "terraform-aws-modules/alb/aws"
          version = "~> 10.0"
          name    = "x"
          listeners = {
            http = {
              port             = 80
              weighted_forward = { target_groups = [{ target_group_key = "a" }] }
              rules = {
                r1 = {
                  actions = [{ forward = { target_group_key = "a" } }]
                  conditions = [{ path_pattern = { values = ["/"] } }]
                }
                auth = {
                  actions = [{ authenticate_oidc = { authorization_endpoint = "https://e", client_id = "c",
                                                     client_secret = "s", issuer = "i", token_endpoint = "t",
                                                     user_info_endpoint = "u" } },
                             { forward = { target_group_key = "a" } }]
                  conditions = [{ path_pattern = { values = ["/a"] } }]
                }
              }
            }
            https = {
              port                 = 443
              protocol             = "HTTPS"
              authenticate_cognito = { user_pool_arn = "arn", user_pool_client_id = "c", user_pool_domain = "d" }
              forward              = { target_group_key = "a" }
            }
          }
          target_groups = {
            a = { protocol = "HTTP", port = 80, target_type = "ip", create_attachment = false }
          }
        }
        """)
        assert_valid(self, raw)
        got = refs(raw)
        tg = 'module.alb.aws_lb_target_group.this["a"]'
        self.assertIn(('module.alb.aws_lb_listener.this["http"]', "default_action[0].forward[0].target_group[0].arn",
                       tg, "arn", "ref", "active"), got)
        self.assertIn(('module.alb.aws_lb_listener_rule.this["http/r1"]', "action[0].target_group_arn", tg, "arn",
                       "ref", "active"), got)
        msg = next(d["message"] for d in raw["diagnostics"] if d["code"] == "TF-MODULE-SUMMARY-INPUT")
        self.assertIn("listeners.*.authenticate_cognito", msg)
        self.assertIn("listeners.*.rules.*.actions.*.authenticate_oidc", msg)
        self.assertNotIn("jwt_validation", msg)  # 渡していないもの（null）は書かない
        raw2 = build("""
        variable "ls" {}
        module "alb" {
          source    = "terraform-aws-modules/alb/aws"
          version   = "~> 10.0"
          listeners = var.ls
        }
        """)
        assert_valid(self, raw2)
        unknown = [d for d in raw2["diagnostics"] if d["code"] == "TF-MODULE-SUMMARY-INPUT" and d["path"] == "unknown"]
        self.assertEqual([d["level"] for d in unknown], ["info"])
        self.assertIn("could not be checked", unknown[0]["message"])
        self.assertNotIn("TF-MODULE-SUMMARY-INPUT", codes(build("""
        module "alb" {
          source  = "terraform-aws-modules/alb/aws"
          version = "~> 10.0"
          listeners = { http = { port = 80, forward = { target_group_key = "a" } } }
          target_groups = { a = { target_type = "ip", create_attachment = false } }
        }
        """)))

    def test_path_present(self):
        p = module_emit.path_present
        v = {"a": {"rules": {"r": {"actions": [{"x": None}, {"y": 1}]}}}, "b": {"rules": {}}}
        self.assertTrue(p(v, ["*", "rules", "*", "actions", "*", "y"]))
        self.assertFalse(p(v, ["*", "rules", "*", "actions", "*", "x"]))
        self.assertFalse(p(v, ["*", "nothing"]))
        self.assertIsNone(p(V.Unknown("u"), ["*"]))  # 決まらず調べられない
        self.assertIsNone(p({"a": V.Unknown("u")}, ["*", "rules"]))
        self.assertTrue(p({"a": V.Unknown("u"), "b": {"rules": 1}}, ["*", "rules"]))
        self.assertFalse(p({"a": {"rules": {}}, "b": {"rules": []}}, ["*", "rules"]))  # 空の {}・[] は当てない
        self.assertTrue(p({"a": {"rules": V.Res("aws_x.y", "arn")}}, ["*", "rules"]))

    def test_vpc_summary_matches_source(self):
        src = PUBLIC / "terraform-aws-vpc"  # v6.7.3（P01）
        cases = [
            ("~> 6.7", '''
  name = "demo"
  cidr = "10.0.0.0/16"
  azs  = ["ap-northeast-1a", "ap-northeast-1c"]
  public_subnets   = ["10.0.0.0/24", "10.0.1.0/24"]
  private_subnets  = ["10.0.10.0/24", "10.0.11.0/24"]
  database_subnets = ["10.0.20.0/24", "10.0.21.0/24"]
  enable_nat_gateway = true
  single_nat_gateway = true
  create_database_subnet_group       = true
  create_database_subnet_route_table = true
  tags = { Project = "demo" }''', 25),
            ("~> 6.0", '''
  name = "ex"
  cidr = "10.0.0.0/16"
  azs  = slice(data.aws_availability_zones.available.names, 0, 3)
  public_subnets  = ["10.0.0.0/20", "10.0.16.0/20", "10.0.32.0/20"]
  private_subnets = ["10.0.48.0/20", "10.0.64.0/20", "10.0.80.0/20"]
  intra_subnets   = ["10.0.96.0/20", "10.0.112.0/20", "10.0.128.0/20"]
  enable_nat_gateway     = true
  one_nat_gateway_per_az = true
  enable_vpn_gateway     = true
  public_subnet_tags = { "kubernetes.io/role/elb" = 1 }''', 39),
            ("6.6.0", '''
  name = "rds"
  cidr = "10.1.0.0/16"
  azs  = ["us-east-1a", "us-east-1b"]
  public_subnets   = ["10.1.0.0/24", "10.1.1.0/24"]
  database_subnets = ["10.1.20.0/24", "10.1.21.0/24"]
  create_database_internet_gateway_route = true
  create_database_subnet_route_table     = true
  manage_default_security_group          = false''', 17),
        ]
        for version, body, n in cases:
            with self.subTest(version):
                got = self.compare_with_source(src, "terraform-aws-modules/vpc/aws", version, body, set())
                self.assertEqual(len(got), n)
        got = self.compare_with_source(src, "terraform-aws-modules/vpc/aws", "~> 6.0", cases[1][1], set())
        self.assertEqual(got["module.m.aws_subnet.public[2]"]["props"]["availability_zone"], {"$az": 2})

    def test_eks_summary_matches_source(self):
        src = PUBLIC / "terraform-aws-eks"  # v21.29.0（P03）
        body = '''
  name               = "ex-eks"
  kubernetes_version = "1.33"
  endpoint_public_access = true
  enable_cluster_creator_admin_permissions = true
  addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni    = { before_compute = true }
  }
  vpc_id     = "vpc-123"
  subnet_ids = ["subnet-1", "subnet-2"]
  eks_managed_node_groups = {
    example = {
      instance_types = ["m6i.large"]
      min_size     = 2
      desired_size = 2
    }
  }
  fargate_profiles = {
    kube-system = {
      selectors = [{ namespace = "kube-system" }]
    }
  }
  self_managed_node_groups = {
    smng = { instance_type = "m6i.large" }
  }
  access_entries = {
    ex = {
      principal_arn = "arn:aws:iam::111122223333:role/ex"
      policy_associations = {
        view = {
          policy_arn   = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy"
          access_scope = { type = "cluster" }
        }
      }
    }
  }'''
        # 意図した違い: ユーザーデータのサブモジュールの null_resource（表に写していない）
        allowed = {'module.m.module.eks_managed_node_group["example"].module.user_data.null_resource.validate_cluster_service_cidr',
                   'module.m.module.self_managed_node_group["smng"].module.user_data.null_resource.validate_cluster_service_cidr'}
        got = self.compare_with_source(src, "terraform-aws-modules/eks/aws", "~> 21.0", body, allowed)
        self.assertEqual(len(got), 48)
        kms = got["module.m.module.kms"]  # 表の中の黒箱の呼び出し（本物と同じ address）
        self.assertEqual((kms["via"], kms["enabled"], kms["version"]), ("module_blackbox", True, "4.0.0"))
        # 暗号化しない（create = false）と、黒箱の呼び出しは enabled: false
        off = build_module_call("terraform-aws-modules/eks/aws", '\n  name = "x"\n  encryption_config = null', "~> 21.0")
        assert_valid(self, off)
        self.assertFalse(res_of(off, "module.m.module.kms")["enabled"])
        ng = got['module.m.module.eks_managed_node_group["example"].aws_eks_node_group.this[0]']
        self.assertEqual(ng["props"]["scaling_config"], [{"min_size": 2, "max_size": 3, "desired_size": 2}])


class SummaryTableFileTest(unittest.TestCase):
    """要約表（data/module-summaries/）が無い・読めないことを、黙って通さない（フェーズ 2b の R1 のレビュー）。"""

    CALL = 'module "vpc" {\n  source = "terraform-aws-modules/vpc/aws"\n  version = "~> 6.0"\n  cidr = "10.0.0.0/16"\n}\n'

    def test_summary_dir_exists_and_is_loaded(self):
        self.assertTrue(MS.SUMMARY_DIR.is_dir(), MS.SUMMARY_DIR)
        self.assertEqual(MS.SUMMARY_DIR.relative_to(SCRIPTS.parent).as_posix(), "data/module-summaries")
        summaries, iam = MS.load()
        self.assertIn("terraform-aws-modules/vpc/aws", summaries)
        self.assertTrue(iam)

    def test_doctor_requires_every_summary_file(self):
        import doctor
        on_disk = sorted(p.relative_to(SCRIPTS.parent).as_posix() for p in MS.SUMMARY_DIR.rglob("*.md"))
        self.assertEqual(on_disk, sorted(f for f in doctor.REQUIRED_FILES if f.startswith("data/module-summaries/")))
        self.assertIn("data/module-summaries/terraform-aws-vpc/v6.md", doctor.REQUIRED_FILES)
        for rel in doctor.REQUIRED_FILES:
            self.assertTrue((SCRIPTS.parent / rel).is_file(), rel)

    def test_missing_table_warns_for_registry_modules(self):
        from unittest import mock
        raw = build(self.CALL)
        codes = [d["code"] for d in raw["diagnostics"] if d["code"].startswith("TF-MODULE")]
        self.assertEqual(codes, ["TF-MODULE-SUMMARY"])
        self.assertGreater(len(raw["resources"]), 1)  # 要約表で展開される
        with tempfile.TemporaryDirectory() as t, mock.patch.object(MS, "SUMMARY_DIR", Path(t) / "nope"):
            raw = build(self.CALL)
        codes = [(d["level"], d["code"]) for d in raw["diagnostics"] if d["code"].startswith("TF-MODULE")]
        self.assertEqual(codes, [("warn", "TF-MODULE-SUMMARY-TABLE-MISSING")])
        self.assertEqual([r["address"] for r in raw["resources"]], ["module.vpc"])  # 黒箱

    def test_missing_table_does_not_warn_without_registry_modules(self):
        from unittest import mock
        files = {"main.tf": 'module "a" {\n  source = "./mod"\n}\nmodule "g" {\n  source = "git::https://example.com/x.git"\n}\n',
                 "mod/main.tf": 'resource "aws_sqs_queue" "q" {\n  name = "q"\n}\n'}
        with tempfile.TemporaryDirectory() as t, mock.patch.object(MS, "SUMMARY_DIR", Path(t) / "nope"):
            raw = build(files)
        self.assertNotIn("TF-MODULE-SUMMARY-TABLE-MISSING", [d["code"] for d in raw["diagnostics"]])

    def copy_tables(self, skip: tuple = ()) -> Path:
        import shutil
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name) / "ms"
        shutil.copytree(MS.SUMMARY_DIR, root, ignore=lambda d, names: [n for n in names if n in skip])
        return root

    def test_a_whole_module_folder_missing_warns_like_a_missing_table(self):
        # vpc のフォルダごと無い（取り込みの不備）。ほかのモジュールの表はある。TF-MODULE-SUMMARY-TABLE-MISSING の warn
        from unittest import mock
        root = self.copy_tables(skip=("terraform-aws-vpc",))
        self.assertIn("terraform-aws-modules/alb/aws", MS.load(root)[0])
        with mock.patch.object(MS, "SUMMARY_DIR", root):
            raw = build(self.CALL)
            alb = build('module "lb" {\n  source = "terraform-aws-modules/alb/aws"\n  version = "~> 10.0"\n}\n')
            sub = build('module "s" {\n  source = "terraform-aws-modules/vpc/aws//modules/x"\n  version = "~> 6.0"\n}\n')
        codes = [(d["level"], d["code"]) for d in raw["diagnostics"] if d["code"].startswith("TF-MODULE")]
        self.assertEqual(codes, [("warn", "TF-MODULE-SUMMARY-TABLE-MISSING")])
        self.assertEqual([r["address"] for r in raw["resources"]], ["module.vpc"])
        self.assertIn("TF-MODULE-SUMMARY", [d["code"] for d in alb["diagnostics"]])  # alb の表はある
        self.assertIn("TF-MODULE-SUMMARY-TABLE-MISSING", [d["code"] for d in sub["diagnostics"]])  # サブモジュールも親のフォルダが無い

    def test_missing_major_of_a_present_module_stays_a_blackbox_info(self):
        # 限界: モジュールの表はあるが、呼び出しの major のファイルが無いときは、表に無いときと同じ info（欠けは doctor の一覧が知らせる）
        from unittest import mock
        root = self.copy_tables(skip=("v6.md",))
        (root / "terraform-aws-vpc").mkdir(exist_ok=True)
        (root / "terraform-aws-vpc" / "v5.md").write_text(
            '<!-- module-summary source="terraform-aws-modules/vpc/aws" majors="5" -->\n```hcl\nvariable "a" {}\n```\n',
            encoding="utf-8", newline="\n")
        with mock.patch.object(MS, "SUMMARY_DIR", root):
            raw = build(self.CALL)  # ~> 6.0 だが 6 のファイルが無い
        codes = [(d["level"], d["code"]) for d in raw["diagnostics"] if d["code"].startswith("TF-MODULE")]
        self.assertEqual(codes, [("info", "TF-MODULE-BLACKBOX")])


if __name__ == "__main__":
    unittest.main()
