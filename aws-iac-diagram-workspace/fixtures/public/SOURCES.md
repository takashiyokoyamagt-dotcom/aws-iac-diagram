# 公開サンプルの出典一覧（fixtures/public）

> **このフォルダの内容は、リポジトリのルートの MIT License（LICENSE）の対象外です。** 各フォルダの LICENSE・NOTICE に従います（Apache-2.0、MIT-0、MIT、MPL-2.0）。全体の一覧は、ルートの NOTICE の 3 にあります。

- 取得日: 2026-10-14
- 取得方法:
  - `git clone --depth 1 --filter=blob:none --sparse` でクローンし、sparse-checkout で必要なパスと LICENSE・NOTICE だけを取り出した。
  - 画像・PDF・zip・.drawio は除外した。
  - 取得後に `.git` を削除した。
- 扱い:
  - **試験用の入力データとしてだけ使う**（読むだけ）。`terraform init`、plan、apply は行わない。
  - 公開モジュールの中身は取得していない。
- 各ディレクトリの LICENSE・NOTICE は、取得元のものをそのまま保持している。
- 削除したファイル: `sample-build-aws-glue-data-quality-pipeline-using-terraform/examples/data/sample-data.parquet`（1.9MB のサンプルデータ。図には関係しない）
- 「最終コミット」は、取得した HEAD のコミット日。

規模（リソース数は概算）:

| 規模 | リソース数 |
|---|---|
| L1 | 1〜5 |
| L2 | 6〜20 |
| L3 | 21〜50 |
| L4 | 50超、または複数モジュール・複数環境 |

## 推奨セット（Terraform）

| ID | 規模 | 種類 | ディレクトリ（このフォルダ配下） | 取得元 | コミット | 最終コミット | ライセンス | SAM/CFn 版 |
|---|---|---|---|---|---|---|---|---|
| T01 | L1 | サーバーレス（EventBridge→SQS） | `serverless-patterns/eventbridge-sqs-terraform/` | aws-samples/serverless-patterns | b44005c | 2026-10-13 | MIT-0（LICENSE 本文で確認） | `serverless-patterns/eventbridge-sqs/` |
| T02 | L1（展開すると L3） | ネットワーク（TGW、VPC×2、count 付き module） | `aws-transit-gateway-vpc-terraform/` | aws-samples/aws-transit-gateway-vpc-terraform | 115826f | 2023-01-23 | MIT-0系（Amazon、本文は MIT 形式）、archived | なし |
| T03 | L1〜L2 | 3層の DB 部分（VPC module＋RDS） | `learn-terraform-rds/` | hashicorp-education/learn-terraform-rds | 8681725 | 2026-03-16 | MPL-2.0 | なし |
| T04 | L2 | 静的サイト（S3、CloudFront、R53、ACM、dynamic、for_each） | `terraform-aws-static-website-s3-cloudfront-acm/` | joshuamkite/terraform-aws-static-website-s3-cloudfront-acm | 24d5a64 | 2025-11-03 | MIT | 作者は別だが同じ構成のものあり → C01 |
| T05 | L2 | サーバーレス（Lambda→SQS） | `serverless-patterns/lambda-sqs-terraform/` | aws-samples/serverless-patterns | b44005c | 2026-10-13 | MIT-0（LICENSE 本文で確認） | `serverless-patterns/lambda-sqs/` |
| T06 | L2 | サーバーレス（EventBridge→SNS→Lambda） | `serverless-patterns/eventbridge-sns-lambda-terraform/` | 同上 | b44005c | 2026-10-13 | MIT-0（LICENSE 本文で確認） | `serverless-patterns/eventbridge-sns-lambda/` |
| T07 | L2 | サーバーレス（API GW HTTP→Lambda→DynamoDB） | `serverless-patterns/apigw-lambda-dynamodb-terraform/` | 同上 | b44005c | 2026-10-13 | MIT-0（LICENSE 本文で確認） | `serverless-patterns/apigw-lambda-dynamodb/` |
| T08 | L2 | データ（DynamoDB→Glue→S3） | `serverless-patterns/dynamodb-glue-s3-terraform/` | 同上 | b44005c | 2026-10-13 | MIT-0（LICENSE 本文で確認） | 不明 |
| T09 | L2 | RAG（Bedrock KB、OpenSearch Serverless） | `sample-bedrock-knowledge-base-terraform/` | aws-samples/sample-bedrock-knowledge-base-terraform | 425e5ec | 2025-08-19 | MIT-0 | なし |
| T10 | L2 | 3層（VPC、ALB、ASG）。**旧構文（aws ~>3.38、launch_configuration）** | `learn-terraform-aws-asg/` | hashicorp-education/learn-terraform-aws-asg | e619fbb | 2025-05-01 | MPL-2.0 | なし |
| T11 | L3 | サーバーレス（API GW REST→Step Functions→DynamoDB） | `serverless-patterns/apigw-sfn-crud-terraform/` | aws-samples/serverless-patterns | b44005c | 2026-10-13 | MIT-0（LICENSE 本文で確認） | `serverless-patterns/apigw-sfn-crud/` |
| T12 | L3 | データ（Glue Data Quality、ローカル module×3） | `sample-build-aws-glue-data-quality-pipeline-using-terraform/` | aws-samples/sample-build-aws-glue-data-quality-pipeline-using-terraform | 6e7eb56 | 2026-02-22 | MIT-0 | なし |
| T13 | L3（展開すると L4） | ネットワーク（TGW hub-and-spoke、VPCE、R53 Resolver） | `hub-and-spoke-with-shared-services-vpc-terraform/` | aws-samples/hub-and-spoke-with-shared-services-vpc-terraform | b752014 | 2023-03-21 | MIT-0 | なし |
| T14 | L3 | 静的サイトの上級版（Lambda@Edge、VPC オリジン） | `terraform-aws-cloudfront/examples/complete/`（`../../` を参照） | terraform-aws-modules/terraform-aws-cloudfront | 5b9a0a4 | 2026-08-26 | Apache-2.0 | なし |
| T15 | L3 | 生成AI（Bedrock Agent＋KB、count による条件分岐が多い） | `terraform-aws-bedrock/examples/agent-with-knowledge-base/` | aws-ia/terraform-aws-bedrock | 4b74b7d | 2025-12-30 | Apache-2.0 | なし |
| T16 | L3〜L4 | コンテナ（EKS、VPC、IRSA） | `learn-terraform-provision-eks-cluster/` | hashicorp/learn-terraform-provision-eks-cluster | 20816e4 | 2026-09-03 | MPL-2.0 | なし |
| T17 | L4 | 3層／コンテナ（ECS Fargate、ALB×2、CI/CD、module 34個） | `amazon-ecs-fullstack-app-terraform/Infrastructure/` | aws-samples/amazon-ecs-fullstack-app-terraform | 98ee8e6 | 2023-04-25 | MIT-0 | なし |
| T18 | L4 | EKS blue/green（ルート3つ＋ローカル module、`git::` ソース） | `terraform-aws-eks-blueprints/patterns/blue-green-upgrade/` | aws-ia/terraform-aws-eks-blueprints | fc40e64 | 2026-09-24 | Apache-2.0 | なし |
| T19 | L4 | ネットワーク（TGW、Network Firewall、IPAM、集約 VPCE） | `aws-network-hub-for-terraform/` | aws-samples/aws-network-hub-for-terraform | e95366a | 2024-06-11 | MIT-0 | なし |
| T20 | L4 | データ（MSK、DMS、Firehose、Glue、Athena、Lake Formation など。独立ルート20以上） | `sample-multi-source-cdc-iceberg-lakehouse/iac/` | aws-samples/sample-multi-source-cdc-iceberg-lakehouse | 1c3b7d5 | 2026-08-24 | MIT-0 | 一部のみ（`iac/bootstrap/tf-backend-cf-stack.yml`） |

## 予備候補（Terraform）

| ID | 規模 | 種類 | ディレクトリ | 取得元 | コミット | ライセンス |
|---|---|---|---|---|---|---|
| P01 | L1／L2 | VPC（`examples/simple/`、VPCE 7個を含む `examples/complete/`） | `terraform-aws-vpc/` | terraform-aws-modules/terraform-aws-vpc | b3abd6d | Apache-2.0 |
| P02 | L3 | ECS Fargate、ALB、Cloud Map（`examples/fargate/`） | `terraform-aws-ecs/` | terraform-aws-modules/terraform-aws-ecs | 135c225 | Apache-2.0 |
| P03 | L3 | EKS マネージドノードグループ（`examples/eks-managed-node-group/`） | `terraform-aws-eks/` | terraform-aws-modules/terraform-aws-eks | 91b8a8d | Apache-2.0 |
| P04 | L2〜L3 | Aurora PostgreSQL（`examples/postgresql/`） | `terraform-aws-rds-aurora/` | terraform-aws-modules/terraform-aws-rds-aurora | d72cba2 | Apache-2.0 |

P01〜P04 は、公開モジュールの「中身の要約表」（PLAN.md の A5）を作るときに参照元としても使う。

## A5 の要約表の照合用（2026-10-17 に追加。ユーザーの許可を得て取得）

| ID | 内容 | ディレクトリ | 取得元 | タグ | コミット | タグのコミット日 | ライセンス |
|---|---|---|---|---|---|---|---|
| M01 | terraform-aws-modules/alb の 10.x の最新（要約表 `terraform-aws-modules/alb/aws` の照合） | `terraform-aws-alb/` | https://github.com/terraform-aws-modules/terraform-aws-alb | v10.5.1 | 6c6e48c10d450d01cf6715346e926df0b858efc2 | 2026-08-26 | Apache-2.0 |
| M02 | terraform-aws-modules/rds の 7.x の最新（要約表 `terraform-aws-modules/rds/aws` とサブモジュールの照合） | `terraform-aws-rds/` | https://github.com/terraform-aws-modules/terraform-aws-rds | v7.2.2 | 175da043429cbbe41c512f976105719f6d0e538c | 2026-09-18 | Apache-2.0 |

- 取得日: 2026-10-17。取得方法: `git ls-remote --tags` で major の最新のタグを選び、`git clone --depth 1 --branch <タグ>` で一時フォルダに取り、`.git` を削除してこのフォルダに置いた（terraform-aws-vpc・terraform-aws-eks と同じく、リポジトリの中身をそのまま。LICENSE は取得元のものを保持）。削除したファイル: `terraform-aws-rds/examples/s3-import-mysql/backup.zip`（zip は除外の決まり）。
- 読むだけ（`tests/test_tf_adapter.py` の `SummaryTest` が、TF アダプタで手元のモジュールとして読む）。`terraform init`・plan・apply は行わない。

### vpc の 5.x・eks の 20.x（2026-10-26 に追加。ユーザーの 2026-10-24 の決定で取得）

要約表 `terraform-aws-modules/vpc/aws` の 5.x（`data/module-summaries/terraform-aws-vpc/v5.md`）と `terraform-aws-modules/eks/aws` の 20.x（`terraform-aws-eks/v20.md`）の照合用。既存の `terraform-aws-vpc/`（6.7.3）・`terraform-aws-eks/`（21.29.0）とは別のフォルダに、版の名前を付けて置いた。

| ID | 内容 | ディレクトリ | 取得元 | タグ | コミット | タグのコミット日 | ライセンス |
|---|---|---|---|---|---|---|---|
| M03 | terraform-aws-modules/vpc の 5.x の T16 の版（`version = "5.8.1"`） | `terraform-aws-vpc-v5.8.1/` | https://github.com/terraform-aws-modules/terraform-aws-vpc | v5.8.1 | 25322b6b6be69db6cca7f167d7b0e5327156a595 | 2024-04-26 | Apache-2.0 |
| M04 | terraform-aws-modules/vpc の 5.x の最新（T18 の `~> 5.0` が選ぶ版。`git ls-remote --tags` で v5.x.y の最大） | `terraform-aws-vpc-v5.21.0/` | 同上 | v5.21.0 | 7c1f791efd61f326ed6102d564d1a65d1eceedf0 | 2025-04-21 | Apache-2.0 |
| M05 | terraform-aws-modules/eks の 20.x の T16 の版（`version = "20.8.5"`） | `terraform-aws-eks-v20.8.5/` | https://github.com/terraform-aws-modules/terraform-aws-eks | v20.8.5 | afadb14e44d1cdbd852dbae815be377c4034e82a | 2024-04-08 | Apache-2.0 |

- 取得方法は M01・M02 と同じ（`git ls-remote --tags` でタグを確かめ、`git clone --depth 1 --branch <タグ>` で一時フォルダに取り、`.git` を削除してこのフォルダに置いた。LICENSE は取得元のものを保持）。タグは軽量タグなので、コミットはタグが指すコミット。取得元はこの 2 つのリポジトリだけ。
- 削除したファイル: `terraform-aws-eks-v20.8.5/.github/images/security_groups.svg`・`user_data.svg`（画像は除外の決まり）。そのほかはリポジトリの中身のまま。
- 版を選んだ理由: T16（`learn-terraform-provision-eks-cluster/main.tf`）が vpc `5.8.1`・eks `20.8.5` を固定している。T18（`terraform-aws-eks-blueprints/patterns/blue-green-upgrade/environment/main.tf`）の vpc は `~> 5.0` で、5.x の最新 v5.21.0 が当たる（T18 の eks は `~> 19.15.2` で、要約表は作らない）。eks の 20.x の最新（v20.37.2）は取り込んでいない。
- 読むだけ（`tests/unit/terraform/test_module_summaries.py` の `SummaryTest` が、TF アダプタで手元のモジュールとして読む）。`terraform init`・plan・apply は行わない。`tf_public_check.py --all` の対象に、これらの中の `.tf` のあるフォルダ（43）が加わる。


## CloudFormation のみの参考

| ID | 内容 | ディレクトリ | 取得元 | コミット | ライセンス |
|---|---|---|---|---|---|
| C01 | 静的サイト（ネストスタック4本、カスタムリソース） | `amazon-cloudfront-secure-static-site/templates/` | aws-samples/amazon-cloudfront-secure-static-site | e893f7b | Apache-2.0 |
| C02 | WebApp（42リソース：CloudFront、WAF、Cognito、API GW、Lambda、DynamoDB） | `aws-cloudformation-templates/Solutions/WebApp/` | aws-cloudformation/aws-cloudformation-templates | a0f43bc | Apache-2.0 |
| C03 | VPC、マネージド NAT、プライベートサブネット | `aws-cloudformation-templates/VPC/VPC_With_Managed_NAT_And_Private_Subnet.yaml` | 同上 | a0f43bc | Apache-2.0 |
| C04 | VPC Peering（複数テンプレート、クロスアカウント） | `aws-cloudformation-templates/Solutions/VPCPeering/` | 同上 | a0f43bc | Apache-2.0 |
| C05 | VPC、ALB、ECS（ネストスタック）。archived | `ecs-refarch-cloudformation/` | aws-samples/ecs-refarch-cloudformation | a257e22 | Apache-2.0 |

## 公開サンプルでは足りない部分（自作の fixture で補う）

- **dev と prod で tfvars を分けた、典型的な複数環境構成**: ライセンスに問題のない良い例が見つからなかった。フェーズ0の自作 fixture で用意する。
- **3層 L3（ALB、ECS、Aurora の組み合わせ）**: P02 と P04 を組み合わせるか、自作 fixture で用意する。
- **静的サイト、サーバーレス、RAG の L4**: 該当なし。必要かどうかは評価フェーズで判断する。
