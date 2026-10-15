# three-tier（ALB → ECS Fargate → RDS）

- CFN 版: [../../cfn/three-tier/](../../cfn/three-tier/README.md)（YAML 1本）
- 正解 IR: [expected/three-tier.ir.json](../../../expected/three-tier.ir.json)（環境 dev）

## 構成

VPC（10.0.0.0/16、2AZ）にパブリック・プライベート・DB のサブネットを各2つ。NAT は1つ（1a のパブリック）。インターネット向け ALB（HTTP 80）→ ECS Fargate サービス（8080）→ RDS PostgreSQL。踏み台 EC2 は prod だけ。

## 何を試すための構成か

| 観点 | 入力の要素 | 期待される扱い |
|---|---|---|
| A1 関係リソース | `aws_lb_listener`、`aws_lb_target_group`、ルートテーブル・ルート・関連付け、SG とルール | すべて辺に変換（`merged_into` の `into` は辺）。リスナーは internet → ALB と ALB → サービスの両方の根拠 |
| A2 向き | `aws_ecs_service.load_balancer.target_group_arn`（サービス → TG の参照） | 辺は **ALB → サービス** |
| A3 確信度 | タスク定義の環境変数 `DB_HOST = aws_db_instance.main.address` | サービス → DB は `confirmed`。ラベルは SG の `TCP 5432`（E-MERGE） |
| A4 変数 | `environment` に既定値が無く、`env/dev.tfvars` と `env/prod.tfvars` がある。`local.env_config[var.environment]` の参照、`count = local.env.enable_bastion ? 1 : 0` | 複数環境なので最初に1回だけ確認する。正解 IR は dev。踏み台の count は今の check_coverage.py では評価できず未照合（(注) と表示される） |
| count | サブネット・関連付けは `count = length(var.azs)`、踏み台は 0 件 | インスタンス単位で分類。0 件のものはインデックスなしで `H-COND-FALSE` |
| SG の書き方 | インラインの ingress（alb、db）、別リソースの `aws_vpc_security_group_ingress_rule`（app） | どれも R-SG で同じ辺になる |
| ルートの書き方 | パブリックは別リソースの `aws_route`、プライベートはインラインの `route` ブロック、DB はルートなし | サブネット → IGW／NAT の辺。DB サブネットのルートテーブルは `H-RT-NOROUTE` |
| 統合 | EIP、ECS クラスタ、タスク定義、DB サブネットグループ | それぞれ NAT、サービス、DB に統合 |
| AZ の挿入 | サブネットの `availability_zone` | VPC → AZ → サブネットの入れ子（N-AZ） |
| 複数サブネット | ALB・サービス・DB（サブネットグループ経由）は2つの AZ にまたがる | `parent` は VPC、`spans` にサブネット2つ（P-SPANS） |

## 判断に迷ったところ

- **ECS クラスタを枠にしない。** サービスがサブネット（AZ）をまたぐので、クラスタの枠とサブネットの枠が交差してしまう。クラスタはサービスに統合する（M-ECS-CLUSTER）。
- **単一 AZ の RDS も2つのサブネットに `spans` する。** どちらの AZ に置かれるかは静的には決まらない（`availability_zone` を指定していない）。
- **internet ノードを作る。** IGW だけでは「どこから入ってくるか」が図に出ないため。インターネット向け ALB と SG の `0.0.0.0/0` が揃ったときだけ作る（N-EXT-INTERNET）。IGW と internet は結ばない。
- **ルートの辺はサブネットから出す。** 通信の主体（ECS など）から NAT へ辺を引く方法もあるが、それは「経路」ではなく推測になる。

## prod で評価したとき（正解 IR には無い。参考）

- ノード `ec2_instance/demo-bastion`（parent はサブネット `demo-public-ap-northeast-1a`）が増える。
- 踏み台の SG は `admin_cidr`（prod では 198.51.100.0/24）からの SSH だけを許す。`0.0.0.0/0` ではないので internet からの辺は作らず、SG は `H-SG-NOEDGE`。
- RDS の `multi_az`、サービスの `desired_count`、DB のインスタンスクラスが変わるが、IR は変わらない。
