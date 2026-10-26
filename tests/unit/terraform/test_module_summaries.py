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


def build_module_call(source: str, body: str, version: str | None = None, extra: str = "") -> dict:
    """モジュールの呼び出し1つのルートを作って読む（source はルートからの相対パスかレジストリの source）。

    extra は呼び出しの後ろに足す HCL（モジュールの出力を読むリソースなど）。"""
    local = not registry_key(source) and not source.startswith(".")
    # ルートからの相対パスで書くので、一時フォルダは source と同じドライブに置く
    # （Windows の CI はリポジトリが D:、既定の一時フォルダが C: で、相対パスが作れない）
    with tempfile.TemporaryDirectory(dir=WS if local else None, prefix="tmp-") as tmp:
        if local:
            source = os.path.relpath(source, tmp).replace("\\", "/")
        ver = f'  version = "{version}"\n' if version else ""
        Path(tmp, "main.tf").write_text(f'module "m" {{\n  source = "{source}"\n{ver}{body}\n}}\n'
                                        'data "aws_availability_zones" "available" {}\n' + extra, encoding="utf-8")
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
        # 1 つの source に major ごとの表がある（ファイル名の major と majors が合う。置き方の検査は MS.problems()）
        majors = {k: [s.majors for s in v] for k, v in summaries.items()}
        self.assertEqual(majors["terraform-aws-modules/vpc/aws"], [(5,), (6,)])
        self.assertEqual(majors["terraform-aws-modules/eks/aws"], [(20,), (21,)])
        self.assertEqual(majors["terraform-aws-modules/alb/aws"], [(10,)])
        self.assertEqual(majors["terraform-aws-modules/rds/aws"], [(7,)])
        for source in ("terraform-aws-modules/eks/aws//modules/eks-managed-node-group",
                       "terraform-aws-modules/eks/aws//modules/fargate-profile",
                       "terraform-aws-modules/eks/aws//modules/self-managed-node-group"):
            self.assertEqual(majors[source], [(20,), (21,)], source)  # サブモジュールの表も、親と同じ major ごと
        self.assertEqual(MS.problems(), [])
        for items in summaries.values():
            for s in items:  # ファイル名（<モジュール>/v<major>.md）と majors が合う（置き方の検査 problems() と同じことを、読んだ表で確かめる）
                self.assertRegex(s.file, r"^terraform-aws-[a-z]+/v[0-9]+\.md$")
                self.assertEqual(len(s.majors), 1)
                self.assertTrue(s.file.endswith(f"/v{s.majors[0]}.md"), (s.source, s.file, s.majors))
        by_major = {s.majors[0]: s for s in summaries["terraform-aws-modules/vpc/aws"]}
        self.assertEqual(by_major[5].file, "terraform-aws-vpc/v5.md")
        self.assertEqual(by_major[6].file, "terraform-aws-vpc/v6.md")
        for s in summaries["terraform-aws-modules/vpc/aws"]:
            self.assertIn("enable_flow_log", s.uncovered)
        self.assertIn("outpost_subnets", by_major[5].uncovered)
        eks = {s.majors[0]: s for s in summaries["terraform-aws-modules/eks/aws"]}
        self.assertIn("cluster_identity_providers", eks[20].uncovered)
        self.assertIn("eks_managed_node_groups.*.schedules", eks[20].uncovered)
        self.assertIn("identity_providers", eks[21].uncovered)
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
        # vpc: 5.x の表ができた。5.x の制約は 5、6.x の制約は 6（これまでの選び方は変わらない）
        for v in ("~> 5.0", "5.8.1", "= 5.8.1", "~> 5.21", ">= 5, < 6", ">= 5.0, < 6.0", "~> 5"):
            with self.subTest(v):
                majors, why, note = pick(vpc, v)
                self.assertEqual((majors, why, note), ((5,), "", None))
        for v in ("< 6.0", "<= 5.99"):  # 下限が無い: 5 を選び、前提に書く
            with self.subTest(v):
                majors, why, note = pick(vpc, v)
                self.assertEqual((majors, why), ((5,), ""))
                self.assertIn("allows majors 0 to 5", note)
        self.assertEqual(pick(vpc, ">= 5.0")[0], (6,))  # 上限が無い: 最も新しい major
        self.assertIn("allows majors 5 to 6", pick(vpc, ">= 5.0, < 7.0")[2])
        self.assertEqual(pick(vpc, ">= 5.0, < 7.0")[0], (6,))
        self.assertEqual(pick(vpc, "~> 6.0")[0], (6,))
        for v in ("2.77.0", "4.0.0", "~> 3.0", "7.0.0", "~> 7.0", ">= 7"):
            with self.subTest(v):
                majors, why, _ = pick(vpc, v)
                self.assertIsNone(majors)
                self.assertIn("is not in the summary table (it has 5.x, 6.x)", why)
        eks = "terraform-aws-modules/eks/aws"
        for v, want in (("20.8.5", 20), ("~> 20.0", 20), ("= 20.8.5", 20), (">= 20, < 21", 20), ("~> 20.8", 20),
                        ("~> 21.0", 21), ("21.29.0", 21), (">= 21", 21), ("< 21.0", 20), (">= 20.0", 21), (None, 21)):
            with self.subTest(v):
                self.assertEqual(pick(eks, v)[0], (want,))
        for v in ("~> 19.15.2", "19.0.0", "~> 18.0", "22.0.0"):
            with self.subTest(v):
                majors, why, _ = pick(eks, v)
                self.assertIsNone(majors)
                self.assertIn("is not in the summary table (it has 20.x, 21.x)", why)
        # サブモジュールも major で選ぶ
        for sub in ("eks-managed-node-group", "fargate-profile", "self-managed-node-group"):
            self.assertEqual(pick(f"{eks}//modules/{sub}", "~> 20.0")[0], (20,), sub)
            self.assertEqual(pick(f"{eks}//modules/{sub}", "~> 21.0")[0], (21,), sub)
        self.assertIsNone(pick(f"{eks}//modules/karpenter", "~> 20.0")[0])  # 表の無いサブモジュール
        self.assertEqual(pick("terraform-aws-modules/rds/aws//modules/db_instance", "~> 7.0")[0], (7,))
        self.assertIsNone(pick("terraform-aws-modules/s3-bucket/aws", "~> 4.0")[0])
        self.assertIsNone(pick(vpc, "~> foo")[0])

    def test_choose_is_unchanged_for_every_previous_pair(self):
        # 5.x・20.x の表を足す前の表（vpc の 6、eks の 21、alb の 10、rds の 7 だけ）で選んだ結果と、今の表で選んだ結果が、
        # 前に表が選ばれた（source, version）のすべてで同じ。前に「表に無い major」だった組だけが、5・20 の表を選ぶように変わる
        import shutil
        with tempfile.TemporaryDirectory() as t:
            old = Path(t) / "old"
            shutil.copytree(MS.SUMMARY_DIR, old)
            for gone in ("terraform-aws-vpc/v5.md", "terraform-aws-eks/v20.md"):
                (old / gone).unlink()
            MS._CACHE.pop(str(old), None)
            sources = ["terraform-aws-modules/vpc/aws", "terraform-aws-modules/alb/aws", "terraform-aws-modules/rds/aws",
                       "terraform-aws-modules/eks/aws", "terraform-aws-modules/eks/aws//modules/fargate-profile",
                       "terraform-aws-modules/rds/aws//modules/db_instance", "terraform-aws-modules/kms/aws",
                       "registry.terraform.io/terraform-aws-modules/vpc/aws", "foo/bar/aws"]
            versions = [None, "", "~> foo"] + [f"{op}{m}{rest}" for op in ("", "= ", "~> ", ">= ", "> ", "< ", "<= ", "!= ")
                                                for m in (0, 2, 4, 5, 6, 7, 10, 11, 19, 20, 21, 22)
                                                for rest in ("", ".0", ".8.1", ".7.3")]
            versions += [f">= {a}, < {b}" for a in (4, 5, 6, 7, 10, 19, 20, 21) for b in (6, 7, 8, 11, 21, 22)]
            versions += ["~> 6.7", "6.6.0", "~> 21.0", "21.29.0", "~> 10.0", "~> 7.0", ">= 5.0, < 7.0", ">= 20.0, < 22.0"]
            none_both, same, newly = 0, 0, []
            for src in sources:
                for ver in versions:
                    a = MR.choose(src, ver, old)
                    b = MR.choose(src, ver)
                    if a[0] is not None:  # 前に表が選ばれた組: 同じ表（同じファイル）、同じ前提の文
                        self.assertEqual((b[0], b[2]), (a[0], a[2]), (src, ver))
                        same += 1
                    elif b[0] is not None:  # 前は「表に無い」。今は 5 か 20 の表だけが当たる
                        self.assertIn(b[0].file, ("terraform-aws-vpc/v5.md", "terraform-aws-eks/v20.md"), (src, ver))
                        newly.append((src, ver))
                    else:  # 前も今も表が無い（理由の文は、持っている major の列挙だけが変わる）
                        self.assertEqual((a[2], b[2]), (None, None))
                        none_both += 1
            self.assertGreater(same, 1000)
            self.assertGreater(len(newly), 50)
            self.assertGreater(none_both, 100)
            MS._CACHE.pop(str(old), None)

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
          version = "4.0.2"
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
        self.assertEqual((old["via"], old["version"]), ("module_blackbox", "4.0.2"))
        self.assertIn("it has 5.x, 6.x", next(d["message"] for d in raw["diagnostics"] if d["address"] == "module.old"))
        p = props(raw, "aws_instance.x")
        self.assertEqual(p["subnet_id"], res("module.vpc.aws_subnet.public[0]", "id"))
        self.assertIn("$unknown", p["acl"])  # 要約表に無い出力
        self.assertIn("TF-MODULE-SUMMARY-OUTPUT", codes(raw, "aws_instance.x"))
        self.assertFalse([k for k in raw["evaluation"]["vars"] if k.startswith("module.")])  # 要約表の変数は書かない

    def compare_with_source(self, real_dir: Path, source: str, version: str, body: str, allowed: set,
                            extra: str = "", ignore: str = ""):
        """同じ入力で、手元の本物のソースと要約表を展開し、address と、要約表のリソースの間の参照を比べる。

        extra は呼び出しの後ろに足す HCL。ignore は、その文字列で終わる address を両方から除く（本物にだけある検査用の
        `null_resource` など、入力に依って有る・無いが変わるものを、`allowed` に 1 つずつ書かずに済ませる）。"""
        real = build_module_call(str(real_dir), body, extra=extra)
        summ = build_module_call(source, body, version, extra=extra)
        for raw in (real, summ):
            assert_valid(self, raw)

        def made(raw):
            return {r["address"]: r for r in raw["resources"] if r["enabled"] is not False
                    and not r["address"].startswith("data.") and ".data." not in r["address"]
                    and not (ignore and r["address"].endswith(ignore))}
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

    # --- vpc 5.x（v5.8.1 = T16、v5.21.0 = 5.x の最新 = T18 の `~> 5.0`）

    VPC5_CASES = [
        ("a", '''
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
        ("b", '''
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
        ("c", '''
  name = "rds"
  cidr = "10.1.0.0/16"
  azs  = ["us-east-1a", "us-east-1b"]
  public_subnets   = ["10.1.0.0/24", "10.1.1.0/24"]
  database_subnets = ["10.1.20.0/24", "10.1.21.0/24"]
  create_database_internet_gateway_route = true
  create_database_subnet_route_table     = true
  manage_default_security_group          = false''', 17),
        # T16 と同じ入力（education-vpc）
        ("t16", '''
  name = "education-vpc"
  cidr = "10.0.0.0/16"
  azs  = slice(data.aws_availability_zones.available.names, 0, 3)
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.4.0/24", "10.0.5.0/24", "10.0.6.0/24"]
  enable_nat_gateway   = true
  single_nat_gateway   = true
  enable_dns_hostnames = true
  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1 }''', 23),
    ]

    def test_vpc5_summary_matches_source(self):
        for tag, constraint in (("v5.8.1", "5.8.1"), ("v5.21.0", "~> 5.0"), ("v5.21.0", ">= 5, < 6")):
            src = PUBLIC / f"terraform-aws-vpc-{tag}"
            for name, body, n in self.VPC5_CASES:
                with self.subTest(f"{tag} {constraint} {name}"):
                    got = self.compare_with_source(src, "terraform-aws-modules/vpc/aws", constraint, body, set())
                    self.assertEqual(len(got), n)
        got = self.compare_with_source(PUBLIC / "terraform-aws-vpc-v5.8.1", "terraform-aws-modules/vpc/aws", "5.8.1",
                                       self.VPC5_CASES[1][1], set())
        self.assertEqual(got["module.m.aws_subnet.public[2]"]["props"]["availability_zone"], {"$az": 2})

    def test_vpc5_differences_between_5_8_1_and_5_21_0(self):
        # 表は 5.21.0 に合わせてある。5.8.1 との違いは次の 3 つだけ（docs/spec/module-summaries.md の 3）。どれも、本物の 2 つの版を
        # 同じ入力で展開した結果の違いと一致することを確かめる
        multi = '''
  name = "multi"
  azs  = ["us-east-1a", "us-east-1b", "us-east-1c"]
  public_subnets  = ["10.2.0.0/24", "10.2.1.0/24", "10.2.2.0/24"]
  private_subnets = ["10.2.10.0/24", "10.2.11.0/24", "10.2.12.0/24"]
  enable_nat_gateway = true
  create_multiple_public_route_tables = true'''
        old, new = PUBLIC / "terraform-aws-vpc-v5.8.1", PUBLIC / "terraform-aws-vpc-v5.21.0"
        # (1) public のルートテーブルを複数作るとき、IGW への経路は 5.8.1 が 1 つ、5.21.0 がテーブルごと。表は 5.21.0 と一致
        got = self.compare_with_source(new, "terraform-aws-modules/vpc/aws", "~> 5.0", multi, set())
        self.assertEqual([a for a in got if "public_internet_gateway" in a],
                         [f"module.m.aws_route.public_internet_gateway[{i}]" for i in range(3)])
        got = self.compare_with_source(old, "terraform-aws-modules/vpc/aws", "5.8.1", multi,
                                       {f"module.m.aws_route.public_internet_gateway[{i}]" for i in (1, 2)})
        self.assertIn("module.m.aws_route.public_internet_gateway[2]", got)  # 表は 3 つ作る（5.8.1 の本物は 1 つ）
        # (2) IPv6 を有効にして NAT を使うとき、NAT64 の経路（private_dns64_nat_gateway。どちらの版も作る）は表に写していない。
        #     5.8.1 は IPv6 の IGW 経路も 1 つ（上の (1) と同じ違い）
        v6 = multi + "\n  enable_ipv6 = true"
        dns64 = {f"module.m.aws_route.private_dns64_nat_gateway[{i}]" for i in range(3)}
        self.compare_with_source(new, "terraform-aws-modules/vpc/aws", "~> 5.0", v6, dns64)
        self.compare_with_source(old, "terraform-aws-modules/vpc/aws", "5.8.1", v6, dns64 | {
            f"module.m.aws_route.public_internet_gateway[{i}]" for i in (1, 2)} | {
            f"module.m.aws_route.public_internet_gateway_ipv6[{i}]" for i in (1, 2)})
        # (3) create_private_nat_gateway_route は 5.21.0 で足された入力（5.8.1 には無い）。false なら private の NAT 経路を作らない
        nat = '''
  name = "x"
  azs  = ["us-east-1a", "us-east-1b"]
  public_subnets  = ["10.0.0.0/24", "10.0.1.0/24"]
  private_subnets = ["10.0.10.0/24", "10.0.11.0/24"]
  enable_nat_gateway = true
  create_private_nat_gateway_route = false'''
        got = self.compare_with_source(new, "terraform-aws-modules/vpc/aws", "~> 5.0", nat, set())
        self.assertFalse([a for a in got if "private_nat_gateway" in a])
        self.assertIn("module.m.aws_nat_gateway.this[1]", got)

    def test_vpc5_not_covered_inputs_are_reported(self):
        raw = build_module_call("terraform-aws-modules/vpc/aws", '''
  name = "n"
  azs  = ["us-east-1a"]
  public_subnets = ["10.0.0.0/24"]
  elasticache_subnets = ["10.0.9.0/24"]
  vpc_block_public_access_options = { internet_gateway_block_mode = "block-bidirectional" }''', "~> 5.0")
        assert_valid(self, raw)
        msg = next(d["message"] for d in raw["diagnostics"] if d["code"] == "TF-MODULE-SUMMARY-INPUT")
        self.assertIn("elasticache_subnets", msg)
        self.assertIn("vpc_block_public_access_options", msg)
        self.assertIn("5.x", next(d["message"] for d in raw["diagnostics"] if d["code"] == "TF-MODULE-SUMMARY"))

    # --- eks 20.x（v20.8.5 = T16）

    EKS20_BODY = '''
  cluster_name    = "ex-eks"
  cluster_version = "1.29"
  cluster_endpoint_public_access           = true
  enable_cluster_creator_admin_permissions = true
  tags = { Env = "dev", Name = "skipped" }
  cluster_addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni    = { before_compute = true }
  }
  vpc_id     = "vpc-123"
  subnet_ids = ["subnet-1", "subnet-2"]
  eks_managed_node_group_defaults = {
    ami_type = "AL2023_x86_64_STANDARD"
    iam_role_additional_policies = { ssm = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore" }
  }
  eks_managed_node_groups = {
    example = {
      instance_types = ["m6i.large"]
      min_size     = 2
      desired_size = 2
    }
    second = {
      name                                  = "second-ng"
      use_name_prefix                       = false
      launch_template_name                  = "lt-second"
      launch_template_use_name_prefix       = false
      attach_cluster_primary_security_group = true
      create_iam_role                       = false
      iam_role_arn                          = "arn:aws:iam::111122223333:role/ng"
    }
  }
  fargate_profiles = {
    kube-system = {
      selectors = [{ namespace = "kube-system" }]
    }
  }
  self_managed_node_groups = {
    smng  = { instance_type = "m6i.large" }
    other = {
      create_access_entry         = false
      create_iam_instance_profile = false
      iam_role_arn                = "arn:aws:iam::111122223333:role/x"
    }
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
    # 意図した違い: ユーザーデータのサブモジュールの null_resource（入力の検査だけ。表に写していない）
    EKS20_ALLOWED = {
        'module.m.module.eks_managed_node_group["example"].module.user_data.null_resource.validate_cluster_service_cidr',
        'module.m.module.eks_managed_node_group["second"].module.user_data.null_resource.validate_cluster_service_cidr',
        'module.m.module.self_managed_node_group["smng"].module.user_data.null_resource.validate_cluster_service_cidr',
        'module.m.module.self_managed_node_group["other"].module.user_data.null_resource.validate_cluster_service_cidr',
    }

    def test_eks20_summary_matches_source(self):
        src = PUBLIC / "terraform-aws-eks-v20.8.5"  # v20.8.5（T16 の版）
        for constraint in ("20.8.5", "~> 20.0", ">= 20, < 21"):
            with self.subTest(constraint):
                got = self.compare_with_source(src, "terraform-aws-modules/eks/aws", constraint, self.EKS20_BODY,
                                               self.EKS20_ALLOWED)
                self.assertEqual(len(got), 54)
        kms = got["module.m.module.kms"]  # 表の中の黒箱の呼び出し（本物と同じ address。20.8.5 の版は 2.1.0）
        self.assertEqual((kms["via"], kms["enabled"], kms["version"]), ("module_blackbox", True, "2.1.0"))
        self.assertIn('module.m.aws_ec2_tag.cluster_primary_security_group["Env"]', got)  # tags（Name 以外）ごと
        self.assertNotIn('module.m.aws_ec2_tag.cluster_primary_security_group["Name"]', got)
        ng = got['module.m.module.eks_managed_node_group["example"].aws_eks_node_group.this[0]']
        self.assertEqual(ng["props"]["scaling_config"], [{"min_size": 2, "max_size": 3, "desired_size": 2}])
        self.assertEqual(ng["props"]["ami_type"], "AL2023_x86_64_STANDARD")  # *_defaults の値が渡る
        # 暗号化しない（cluster_encryption_config = {}）と、黒箱の呼び出しは enabled: false、暗号化のポリシーも作らない
        off = build_module_call("terraform-aws-modules/eks/aws", '\n  cluster_name = "x"\n  cluster_encryption_config = {}', "~> 20.0")
        assert_valid(self, off)
        self.assertFalse(res_of(off, "module.m.module.kms")["enabled"])
        self.assertNotIn("module.m.aws_iam_policy.cluster_encryption[0]", [r["address"] for r in off["resources"]])
        # 最小の入力（本物と同じ address、すべて）
        got = self.compare_with_source(src, "terraform-aws-modules/eks/aws", "~> 20.0",
                                       '\n  cluster_name = "min"\n  vpc_id = "vpc-1"\n  subnet_ids = ["s-1", "s-2"]', set())
        self.assertEqual(len(got), 23)

    def test_eks20_references_between_summarised_resources(self):
        # 表のリソースの間の参照が、期待する形でできている（本物との一致は上のテスト）
        raw = build_module_call("terraform-aws-modules/eks/aws", self.EKS20_BODY, "20.8.5")
        assert_valid(self, raw)
        pairs = {(r["from"], r["to"]) for r in raw["references"] if r["state"] == "active"}
        ng = 'module.m.module.eks_managed_node_group["example"]'
        for want in [
            ("module.m.aws_eks_cluster.this[0]", "module.m.aws_iam_role.this[0]"),
            ("module.m.aws_eks_cluster.this[0]", "module.m.module.kms"),
            ("module.m.aws_eks_cluster.this[0]", "module.m.aws_security_group.cluster[0]"),
            ("module.m.aws_security_group_rule.node[\"ingress_cluster_443\"]", "module.m.aws_security_group.cluster[0]"),
            ("module.m.aws_eks_addon.this[\"coredns\"]", "module.m.aws_eks_cluster.this[0]"),
            (ng + ".aws_eks_node_group.this[0]", ng + ".aws_iam_role.this[0]"),
            (ng + ".aws_eks_node_group.this[0]", ng + ".aws_launch_template.this[0]"),
            (ng + ".aws_launch_template.this[0]", "module.m.aws_security_group.node[0]"),
            ("module.m.module.fargate_profile[\"kube-system\"].aws_eks_fargate_profile.this[0]",
             "module.m.module.fargate_profile[\"kube-system\"].aws_iam_role.this[0]"),
            ("module.m.module.self_managed_node_group[\"smng\"].aws_autoscaling_group.this[0]",
             "module.m.module.self_managed_node_group[\"smng\"].aws_launch_template.this[0]"),
        ]:
            self.assertIn(want, pairs, want)

    def test_eks20_not_covered_inputs_are_reported(self):
        raw = build_module_call("terraform-aws-modules/eks/aws", '''
  cluster_name = "n"
  cluster_identity_providers = { oidc = { client_id = "x" } }
  create_cni_ipv6_iam_policy = true
  not_a_variable = 1
  eks_managed_node_groups = {
    a = { enable_efa_support = true, schedules = { s = { min_size = 1 } } }
    b = {}
  }
  self_managed_node_group_defaults = { schedules = { s = {} } }''', "20.8.5")
        assert_valid(self, raw)
        diags = {d["code"]: d["message"] for d in raw["diagnostics"] if d.get("address") == "module.m"}
        msg = diags["TF-MODULE-SUMMARY-INPUT"]
        for name in ("cluster_identity_providers", "create_cni_ipv6_iam_policy", "not_a_variable",
                     "eks_managed_node_groups.*.enable_efa_support", "eks_managed_node_groups.*.schedules",
                     "self_managed_node_group_defaults.schedules"):
            self.assertIn(name, msg)
        self.assertIn("20.x", diags["TF-MODULE-SUMMARY"])

    # --- T16・T18: vpc 5.x・eks 20.x の黒箱が無くなった

    def blackboxes(self, folder: str) -> tuple:
        raw = tf_build.build_raw(PUBLIC / folder, WS)
        assert_valid(self, raw)
        return {r["address"]: r for r in raw["resources"] if r["type"] == "module" and r.get("via") == "module_blackbox"}, raw

    def test_t16_and_t18_have_no_blackbox_for_the_summarised_modules(self):
        # T16: vpc 5.8.1 と eks 20.8.5 が要約表で展開される。黒箱に残るのは、要約表の 4 モジュールの外（表の中の kms と iam）だけ
        bb, raw = self.blackboxes("learn-terraform-provision-eks-cluster")
        self.assertEqual(sorted(bb), ["module.eks.module.kms", "module.irsa-ebs-csi"])
        self.assertEqual(bb["module.eks.module.kms"]["version"], "2.1.0")
        self.assertEqual(bb["module.irsa-ebs-csi"]["source"], "terraform-aws-modules/iam/aws//modules/iam-assumable-role-with-oidc")
        summ = {r["address"].split(".")[1] for r in raw["resources"] if r.get("via") == "module_summary"}
        self.assertEqual(summ, {"vpc", "eks"})
        for mod in ("module.vpc", "module.eks"):
            self.assertNotIn(mod, bb)
            self.assertIn("TF-MODULE-SUMMARY", [d["code"] for d in raw["diagnostics"] if d.get("address") == mod])
        self.assertEqual(len([r for r in raw["resources"] if r["address"].startswith("module.eks.module.eks_managed_node_group[")
                              and r["type"] == "aws_eks_node_group"]), 2)
        self.assertIn("module.vpc.aws_nat_gateway.this[0]", [r["address"] for r in raw["resources"]])
        # eks のクラスタは、vpc のサブネットと node のグループへの参照を持つ（module の呼び出しの引数を通して）
        refs = {(r["from"], r["to"]) for r in raw["references"] if r["state"] == "active"}
        self.assertIn(("module.eks.aws_eks_cluster.this[0]", "module.vpc.aws_subnet.private[0]"), refs)
        self.assertIn(("module.eks.aws_security_group.node[0]", "module.vpc.aws_vpc.this[0]"), refs)
        # T18: environment は vpc `~> 5.0` が展開される。acm は表の外
        bb, raw = self.blackboxes("terraform-aws-eks-blueprints/patterns/blue-green-upgrade/environment")
        self.assertEqual(sorted(bb), ["module.acm"])
        self.assertIn("5.x", next(d["message"] for d in raw["diagnostics"] if d["code"] == "TF-MODULE-SUMMARY"
                                  and d["address"] == "module.vpc"))
        self.assertIn("module.vpc.aws_vpc.this[0]", [r["address"] for r in raw["resources"]])
        # T18 の eks-blue・eks-green の eks は `~> 19.15.2`（19.x の表は作らない）なので黒箱のまま。ほかは表の外のモジュール
        for env in ("eks-blue", "eks-green"):
            bb, raw = self.blackboxes(f"terraform-aws-eks-blueprints/patterns/blue-green-upgrade/{env}")
            self.assertEqual(sorted(bb), sorted([
                "module.eks_cluster.module.ebs_csi_driver_irsa", "module.eks_cluster.module.eks",
                "module.eks_cluster.module.eks_blueprints_addons",
                'module.eks_cluster.module.eks_blueprints_dev_teams["burnham"]',
                'module.eks_cluster.module.eks_blueprints_dev_teams["riker"]',
                'module.eks_cluster.module.eks_blueprints_ecsdemo_teams["ecsdemo-crystal"]',
                'module.eks_cluster.module.eks_blueprints_ecsdemo_teams["ecsdemo-frontend"]',
                'module.eks_cluster.module.eks_blueprints_ecsdemo_teams["ecsdemo-nodejs"]',
                "module.eks_cluster.module.eks_blueprints_platform_teams",
                "module.eks_cluster.module.gitops_bridge_bootstrap", "module.eks_cluster.module.vpc_cni_irsa"]), env)
            self.assertEqual(bb["module.eks_cluster.module.eks"]["version"], "~> 19.15.2")
            why = next(d["message"] for d in raw["diagnostics"] if d.get("address") == "module.eks_cluster.module.eks")
            self.assertIn("it has 20.x, 21.x", why)

    # --- レビュー対応: 入力で有る・無いが変わるリソースと、出力の値（変異を殺す）

    EKS20_PROBES = """
resource "aws_ssm_parameter" "probe_oidc_arn" {
  name  = "a"
  type  = "String"
  value = module.m.oidc_provider_arn
}
resource "aws_ssm_parameter" "probe_cluster_name" {
  name  = "b"
  type  = "String"
  value = module.m.cluster_name
}
"""

    EKS_SWITCH_BASE = '''
  cluster_name = "c"
  vpc_id       = "vpc-1"
  subnet_ids   = ["s-1", "s-2"]
  cluster_addons = { coredns = {} }
  eks_managed_node_groups  = { a = {} }
  self_managed_node_groups = { s = {} }
  fargate_profiles         = { f = { selectors = [{ namespace = "x" }] } }'''

    # (名前, 足す入力)。create・create_iam_role・enable_irsa・ログ・SG・KMS の切り替えと、その組み合わせ
    EKS_SWITCHES = [
        ("default", ""),
        ("create=false", "\n  create = false"),
        ("create_iam_role=false", '\n  create_iam_role = false\n  iam_role_arn = "arn:aws:iam::111122223333:role/c"'),
        ("enable_irsa=false", "\n  enable_irsa = false"),
        ("log group off", "\n  create_cloudwatch_log_group = false"),
        ("cluster SG off", '\n  create_cluster_security_group = false\n  cluster_security_group_id = "sg-c"'),
        ("node SG off", '\n  create_node_security_group = false\n  node_security_group_id = "sg-n"'),
        ("own kms key", '\n  create_kms_key = false\n  cluster_encryption_config = { resources = ["secrets"], provider_key_arn = "arn:aws:kms:us-east-1:111122223333:key/k" }'),
        ("encryption policy off", "\n  attach_cluster_encryption_policy = false"),
        ("iam off + irsa off + log off", '\n  create_iam_role = false\n  iam_role_arn = "arn:aws:iam::111122223333:role/c"\n  enable_irsa = false\n  create_cloudwatch_log_group = false'),
        ("everything off", '\n  create_iam_role = false\n  iam_role_arn = "arn:aws:iam::111122223333:role/c"\n  enable_irsa = false\n  create_cloudwatch_log_group = false\n  create_node_security_group = false\n  node_security_group_id = "sg-n"\n  create_cluster_security_group = false\n  cluster_security_group_id = "sg-c"'),
    ]

    def probe_values(self, raw) -> dict:
        return {r["address"]: r["props"].get("value") for r in raw["resources"]
                if r["address"].startswith("aws_ssm_parameter.")}

    def test_eks20_switches_match_source(self):
        # create・create_iam_role・enable_irsa・ログ・SG の切り替えで、作られるリソースが本物と同じ（count が 0 になるものを含む）。
        # あわせて、出力（oidc_provider_arn・cluster_name）を読む probe の値が本物と同じ（出力の名前や式が変わると、$unknown になって落ちる）
        src = PUBLIC / "terraform-aws-eks-v20.8.5"
        suffix = ".module.user_data.null_resource.validate_cluster_service_cidr"
        sizes = {}
        for name, extra_input in self.EKS_SWITCHES:
            with self.subTest(name):
                body = self.EKS_SWITCH_BASE + extra_input
                got = self.compare_with_source(src, "terraform-aws-modules/eks/aws", "20.8.5", body, set(),
                                               extra=self.EKS20_PROBES, ignore=suffix)
                sizes[name] = len(got)
                real = build_module_call(str(src), body, extra=self.EKS20_PROBES)
                summ = build_module_call("terraform-aws-modules/eks/aws", body, "20.8.5", extra=self.EKS20_PROBES)
                self.assertEqual(self.probe_values(summ), self.probe_values(real))
                self.assertNotIn("TF-MODULE-SUMMARY-OUTPUT", codes(summ, "aws_ssm_parameter.probe_oidc_arn"))
                self.assertNotIn("TF-MODULE-SUMMARY-OUTPUT", codes(summ, "aws_ssm_parameter.probe_cluster_name"))
        # スイッチが効いている（件数が変わる）ことの確認
        self.assertEqual(sizes["create=false"], 2)  # 何も作らない。残るのは probe の 2 件だけ
        self.assertGreater(sizes["default"], sizes["enable_irsa=false"])
        self.assertGreater(sizes["default"], sizes["log group off"])
        self.assertGreater(sizes["default"], sizes["create_iam_role=false"])
        self.assertGreater(sizes["default"], sizes["everything off"])
        # probe の値の形（既定では出力は実在のリソースへの参照。enable_irsa=false では null）
        summ = build_module_call("terraform-aws-modules/eks/aws", self.EKS_SWITCH_BASE, "20.8.5", extra=self.EKS20_PROBES)
        v = self.probe_values(summ)
        self.assertEqual(v["aws_ssm_parameter.probe_oidc_arn"], res("module.m.aws_iam_openid_connect_provider.oidc_provider[0]", "arn"))
        self.assertEqual(v["aws_ssm_parameter.probe_cluster_name"], res("module.m.aws_eks_cluster.this[0]", "name"))
        off = build_module_call("terraform-aws-modules/eks/aws", self.EKS_SWITCH_BASE + "\n  enable_irsa = false", "20.8.5",
                                extra=self.EKS20_PROBES)
        self.assertIsNone(self.probe_values(off)["aws_ssm_parameter.probe_oidc_arn"])

    def test_eks21_switches_match_source(self):
        # v21 の表にも同じ確認（既存の表。変更は無い。切り替えの組み合わせと、出力の probe が本物と同じ）
        src = PUBLIC / "terraform-aws-eks"
        base = '''
  name       = "c"
  vpc_id     = "vpc-1"
  subnet_ids = ["s-1", "s-2"]
  addons = { coredns = {} }
  eks_managed_node_groups  = { a = {} }
  self_managed_node_groups = { s = {} }
  fargate_profiles         = { f = { selectors = [{ namespace = "x" }] } }'''
        role = '\n  create_iam_role = false\n  iam_role_arn = "arn:aws:iam::111122223333:role/c"'
        cases = {"default": "", "create=false": "\n  create = false", "iam off": role, "irsa off": "\n  enable_irsa = false",
                 "log off": "\n  create_cloudwatch_log_group = false",
                 "all": role + "\n  enable_irsa = false\n  create_cloudwatch_log_group = false"}
        for name, extra_input in cases.items():
            with self.subTest(name):
                self.compare_with_source(src, "terraform-aws-modules/eks/aws", "~> 21.0", base + extra_input, set(),
                                         extra=self.EKS20_PROBES,
                                         ignore=".module.user_data.null_resource.validate_cluster_service_cidr")
                real = build_module_call(str(src), base + extra_input, extra=self.EKS20_PROBES)
                summ = build_module_call("terraform-aws-modules/eks/aws", base + extra_input, "~> 21.0", extra=self.EKS20_PROBES)
                self.assertEqual(self.probe_values(summ), self.probe_values(real))

    # --- vpc 5.x・6.x の切り替え

    VPC_SWITCH_CASES = [
        # database のサブネットグループを作らない（create_database_subnet_group = false）
        ("db subnet group off", """
  name = "db"
  azs  = ["us-east-1a", "us-east-1b"]
  database_subnets = ["10.0.20.0/24", "10.0.21.0/24"]
  create_database_subnet_route_table = true
  create_database_subnet_group = false""", True),
        # one_nat_gateway_per_az は既定のまま（false）。NAT の数は AZ の数ではなく、サブネットの数（2）
        ("nat default one_nat_gateway_per_az", """
  name = "nat"
  azs  = ["us-east-1a", "us-east-1b", "us-east-1c"]
  public_subnets  = ["10.0.0.0/24", "10.0.1.0/24"]
  private_subnets = ["10.0.10.0/24", "10.0.11.0/24"]
  enable_nat_gateway = true""", True),
        ("create_vpc off", """
  name = "off"
  azs  = ["us-east-1a"]
  public_subnets = ["10.0.0.0/24"]
  create_vpc = false""", False),
        ("igw off", """
  name = "noigw"
  azs  = ["us-east-1a", "us-east-1b"]
  public_subnets  = ["10.0.0.0/24", "10.0.1.0/24"]
  private_subnets = ["10.0.10.0/24", "10.0.11.0/24"]
  create_igw = false
  enable_nat_gateway = true
  single_nat_gateway = true""", False),
    ]

    def test_vpc_switches_match_source(self):
        trees = [("5.8.1", "terraform-aws-vpc-v5.8.1"), ("~> 5.0", "terraform-aws-vpc-v5.21.0"), ("~> 6.0", "terraform-aws-vpc")]
        for version, folder in trees:
            for name, body, _ in self.VPC_SWITCH_CASES:
                with self.subTest(f"{folder} {name}"):
                    got = self.compare_with_source(PUBLIC / folder, "terraform-aws-modules/vpc/aws", version, body, set())
                    if name == "db subnet group off":
                        self.assertFalse([a for a in got if "aws_db_subnet_group" in a])
                        self.assertEqual(len([a for a in got if "aws_subnet.database" in a]), 2)
                    if name == "nat default one_nat_gateway_per_az":
                        self.assertEqual(len([a for a in got if "aws_nat_gateway.this" in a]), 2)  # AZ は 3 つだが NAT は 2 つ
                    if name == "create_vpc off":
                        self.assertEqual(got, {})
                    if name == "igw off":
                        self.assertFalse([a for a in got if "internet_gateway" in a or "public_internet_gateway" in a])

    # --- 親が子のモジュールに渡す入力が、子の表で宣言されている（宣言が無いと、使っていない入力が「表に無い入力」と通知される）

    def test_every_input_a_table_passes_to_a_submodule_is_declared_there(self):
        import re
        summaries, _ = MS.load()
        checked = 0
        for source, items in summaries.items():
            if "//" in source:
                continue
            for s in items:
                parent = module_eval.ModuleEval(model.Context(Path(".")), None)
                parent.summary = s
                parent.collect(module_load.summary_tree(s), "main.tf")
                for blk in parent.blocks.values():
                    if blk.kind != "module":
                        continue
                    m = re.search(r'module\s+"%s"\s*\{\s*source\s*=\s*"([^"]+)"' % re.escape(blk.name), s.text)
                    if not m or not is_local(m.group(1)):
                        continue  # 表の外のモジュール（kms）は黒箱。宣言を持たない
                    sub_source = join_summary_source(s.source, m.group(1))
                    sub = next(x for x in summaries[sub_source] if x.majors == s.majors)
                    child = module_eval.ModuleEval(model.Context(Path(".")), None)
                    child.summary = sub
                    child.collect(module_load.summary_tree(sub), "main.tf")
                    passed = set(blk.attrs) - {"source", "version", "for_each", "count", "depends_on", "providers"}
                    with self.subTest(f"{s.file} {blk.name}"):
                        self.assertEqual(sorted(passed - set(child.variables)), [])
                    checked += 1
        self.assertGreaterEqual(checked, 11)  # eks 20・21 の 3 つずつ、rds 5

    def test_eks20_empty_node_groups_report_no_uncovered_inputs(self):
        # 子の表に launch_template_tags の宣言が無く、セルフマネージドのグループごとに TF-MODULE-SUMMARY-INPUT が出ていた（回帰）
        for version in ("20.8.5", "~> 21.0"):
            body = {"20.8.5": '''
  cluster_name = "c"
  vpc_id       = "vpc-1"
  subnet_ids   = ["s-1"]
  self_managed_node_groups = { s = {} }
  eks_managed_node_groups  = { m = {} }
  fargate_profiles         = { f = { selectors = [{ namespace = "x" }] } }''',
                    "~> 21.0": '''
  name       = "c"
  vpc_id     = "vpc-1"
  subnet_ids = ["s-1"]
  self_managed_node_groups = { s = {} }
  eks_managed_node_groups  = { m = {} }
  fargate_profiles         = { f = { selectors = [{ namespace = "x" }] } }'''}[version]
            with self.subTest(version):
                raw = build_module_call("terraform-aws-modules/eks/aws", body, version)
                assert_valid(self, raw)
                self.assertEqual([d["message"] for d in raw["diagnostics"] if d["code"] == "TF-MODULE-SUMMARY-INPUT"], [])


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
