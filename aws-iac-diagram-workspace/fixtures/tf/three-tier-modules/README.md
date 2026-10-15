# three-tier-modules（公開モジュール＋ローカルモジュール）

- CFN 版: [../../cfn/three-tier-modules/](../../cfn/three-tier-modules/README.md)（ネストスタック5本）
- 正解 IR: [expected/three-tier-modules.ir.json](../../../expected/three-tier-modules.ir.json)

## 構成

[three-tier](../three-tier/README.md)（dev）と同じ構成を、公開モジュール `terraform-aws-modules/vpc/aws`（~> 6.7）、`terraform-aws-modules/alb/aws`（~> 10.0）、`terraform-aws-modules/rds/aws`（~> 7.0）と、ローカルモジュール `./modules/ecs-service`（ECS クラスタ・タスク定義・サービス・SG）で書いたもの。DB の SG だけはルートにある。踏み台は無い。

**正解 IR の canonical 部（nodes と edges）は three-tier と同じ。** モジュールで書いても同じ図になることを確かめる（`validate_ir.py --same-canonical`）。

## 何を試すための構成か

| 観点 | 入力の要素 | 期待される扱い |
|---|---|---|
| A5 公開モジュール | 3つのレジストリモジュール（中身はリポジトリに無い） | 要約表から中身を展開する。網羅分類は `via: "module_summary"`、`file` は `main.tf` |
| ローカルモジュール | `./modules/ecs-service` | 再帰的に読む。アドレスは `module.app.aws_ecs_service.this` |
| 境界をまたぐ参照 | `module.db.db_instance_address` → `module.app` の変数 `environment` → タスク定義の環境変数 `DB_HOST` | サービス → DB は `confirmed`（モジュールの出力・変数を通っても元が参照なら確定） |
| 境界をまたぐ A2 | `module.alb.target_groups["app"].arn` → `module.app` の `target_group_arn` → サービスの `load_balancer` | 辺は ALB → サービス |
| 境界をまたぐ SG | ALB の SG（モジュールの中）→ app の SG のルール（ローカルモジュールの中）→ DB の SG（ルート） | three-tier と同じ3本の辺 |
| 既定で作られるもの | vpc モジュールの `aws_default_security_group`・`aws_default_network_acl`・`aws_default_route_table`（`manage_default_*` が既定で true） | H-VPC-DEFAULTS |
| 別リソースの egress | alb モジュールの `aws_vpc_security_group_egress_rule.this["all"]` | H-SG-EGRESS |

## 公開モジュールの展開（要約表が出すべきもの）

正解 IR の `via: "module_summary"` のエントリがそのまま一覧。入力に対して作られる managed リソースだけを載せ、モジュール内部の `data` と count が 0 のものは載せない。

- vpc（25件）: `aws_vpc.this[0]`、`aws_subnet.{public,private,database}[0..1]`、`aws_internet_gateway.this[0]`、`aws_eip.nat[0]`、`aws_nat_gateway.this[0]`、`aws_route_table.{public,private,database}[0]`、`aws_route.public_internet_gateway[0]`、`aws_route.private_nat_gateway[0]`、`aws_route_table_association.{public,private,database}[0..1]`、`aws_db_subnet_group.database[0]`、`aws_default_{security_group.this,network_acl.this,route_table.default}[0]`。名前（`demo-public-ap-northeast-1a` など）も含め、**v6.7.3 のソース（`fixtures/public/terraform-aws-vpc`、P01）で確認した。**
- alb（6件）: `aws_lb.this[0]`、`aws_lb_listener.this["http"]`、`aws_lb_target_group.this["app"]`、`aws_security_group.this[0]`、`aws_vpc_security_group_ingress_rule.this["all_http"]`、`aws_vpc_security_group_egress_rule.this["all"]`。`create_attachment = false` なので `aws_lb_target_group_attachment` は無い。
- rds（1件）: `module.db.module.db_instance.aws_db_instance.this[0]`。サブネットグループ・パラメータグループ・オプショングループ・監視ロールは作らない設定にし、`skip_final_snapshot = true` で `random_id` も作られないようにした。

**ソースでの確認（2026-10-15）:** alb と rds はこのリポジトリに取得していないので、GitHub の既定ブランチのソースを WebFetch で読んで照合した（alb は最新リリース v10.5.1 の時点、rds は v7.2.2 の時点。コミットは記録していない）。
- alb: `main.tf` のリソースと for_each／count（`aws_lb.this` は `count`、リスナー・ターゲットグループ・SG ルールは入力のマップで `for_each`、`aws_lb_target_group_attachment.this` は `create_attachment` が true のものだけ）、`target_groups` の属性は **`protocol`／`port`**（`backend_protocol`／`backend_port` ではない）、`listeners[].forward.target_group_key`、出力 `security_group_id`・`target_groups`、`versions.tf` は aws >= 6.28。
- rds: ルートの `main.tf` は `db_subnet_group`・`db_parameter_group`・`db_option_group`・`db_instance`・`db_instance_role_association` のサブモジュールだけでリソースを持たない。`modules/db_instance/main.tf` は `aws_db_instance.this`（`count = var.create ? 1 : 0`）のほか、`random_id.snapshot_identifier`（`skip_final_snapshot` が false のとき）、`aws_cloudwatch_log_group.this`（ログのエクスポートと `create_cloudwatch_log_group`）、監視ロール（`create_monitoring_role`）、`aws_secretsmanager_secret_rotation.this`（ローテーション有効時）で、今回の入力ではどれも 0 件。`create_db_option_group` は既定 true だが postgres では作られない（`var.engine != "postgres"`）。変数はすべて実在し、`port` は string 型。
- **rds の版を ~> 6.10 から ~> 7.0 に変えた。** v6.13.1 の `versions.tf` は aws >= 5.92 で aws v6 とも組めるが、v7 は aws >= 6.28（vpc ~> 6.7・alb ~> 10.0 と同じ系列）で、2025-12 以降の現行版。v7 は Terraform >= 1.11.1 を要求するので、この fixture の `required_version` を `>= 1.11.1` にした。v7 の破壊的変更（`password` の廃止など）はこの入力には関係しない。
- 中身のアドレスはこれで照合したが、`terraform init`／`plan` での確認はしていない。

## 判断に迷ったところ

- **three-tier と完全に同じ canonical 部にした。** 違いを入れると「モジュールの展開が正しいか」と「構成の違い」が混ざって評価しにくい。違う構成は他の fixture で試す。
- **vpc モジュールの DB サブネット用のルートテーブル。** `create_database_subnet_route_table = true` にしないと、DB サブネットがプライベートのルートテーブル（NAT 行き）に関連付けられ、three-tier と図が変わる。three-tier に合わせて true にした。
