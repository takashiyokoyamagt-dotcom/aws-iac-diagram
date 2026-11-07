# 入れ子の規則と attrs（`data/rules/placement.toml`）

- **これは開発者向けの説明です（SKILL の外。配りません）。** 表そのもの（スクリプトが実行時に読むデータ）は `skills/aws-iac-diagram/data/rules/`（TOML）にあります。下の表は、そのデータから `aws-iac-diagram-workspace/tools/render_rules.py` が作った生成物です（`<!-- rules-table: … -->` の間は直接直さない。直すのはデータ）。全体は [README.md](README.md)

- 状態: **草案**（手順 1 でデータにした。内容は変えていない）。元は resource-catalog.md の 5 章と、`subnet` の `attrs.access` の文
- 型ごとの `parent` は、手順 3（入れ子の実装）でこの表の `types` から決める。型の行（[types.md](types.md)）には `parent` の列を持たせていない

## 列

<!-- rules-table: fields-placement -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

**`[[placement]]`**

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `id` | 文字列 | 必須 | 規則 ID（`N-AZ` または `P-` で始まる） |
| `types` | 文字列の配列（1 つ以上） | 必須 | この規則で parent が決まる（または作られる）描く型 |
| `content` | 文字列 | 必須 | 内容（原文） |

**`[[attr]]`**

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `type` | 文字列 | 必須 | 描く型 |
| `name` | 文字列 | 必須 | `attrs` のキー |
| `values` | 文字列の配列（1 つ以上） | 必須 | 値 |
| `source` | 文字列 | 必須 | 材料にする規則 ID |
| `rule` | 文字列 | 必須 | 決め方（原文） |

<!-- /rules-table -->

## 入れ子の規則（N-AZ・P-*）

<!-- rules-table: placement -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 規則ID | 内容 | 対象の型 |
|---|---|---|
| `N-AZ` | サブネットの AZ ごとに `availability_zone` のノードを VPC の下に作り、サブネットをその下に入れる（TerraVision と同じ考え方）。key は `<VPC の key>.<AZ 名>` | `availability_zone`、`subnet` |
| `P-VPC` | インターネットゲートウェイ、Gateway 型の VPC エンドポイント、複数の AZ にまたがるリソースの `parent` は VPC | `internet_gateway`、`vpc_endpoint` |
| `P-SUBNET` | サブネットを1つだけ指定するリソース（NAT ゲートウェイ、EC2 インスタンス）の `parent` はそのサブネット | `nat_gateway`、`ec2_instance` |
| `P-SPANS` | サブネットを2つ以上指定するリソース（ALB、ECS サービス、Interface 型の VPC エンドポイント、DB サブネットグループ経由の DB、`vpc_config.subnet_ids`／`ResourcesVpcConfig.SubnetIds` の EKS クラスタ）は、`spans` にそのサブネットを並べ、`parent` はそれらの最も近い共通の祖先（AZ が違えば VPC）にする。描き方（サブネットごとに複製するか、またがる箱にするか）は配置（フェーズ4）で決める | `alb`、`ecs_service`、`vpc_endpoint`、`db_instance`、`eks_cluster` |
| `P-REGIONAL` | VPC に入らないリソース（Lambda、DynamoDB、S3、SNS、SQS、API Gateway、Bedrock、OpenSearch Serverless、EventBridge、Step Functions、Glue、Cognito）、グローバルなもの（CloudFront、Route 53 のレコード、CloudFront 用の WAF）と `external` は `parent: null`。「AWS Cloud」やリージョンの枠は配置の段階で描き、IR には入れない | `lambda_function`、`dynamodb_table`、`s3_bucket`、`sns_topic`、`sqs_queue`、`apigw_http_api`、`apigw_rest_api`、`bedrock_knowledge_base`、`bedrock_model`、`opensearchserverless_collection`、`cloudfront_distribution`、`route53_record`、`waf_web_acl`、`cognito_user_pool`、`eventbridge_rule`、`sfn_state_machine`、`glue_job`、`glue_crawler`、`glue_catalog_database`、`external` |

<!-- /rules-table -->

- Lambda を VPC に入れる設定（`vpc_config`）があれば `P-SUBNET`／`P-SPANS` に従う（fixture には無い）。
- 実装（フェーズ 3 の手順 3b。`scripts/aws_iac_diagram/normalize/nesting.py`）の決め方: 置き場所の手がかりは、ノードのリソースと、そのノードだけに統合された M-*（DB サブネットグループ、CFN の `VPCGatewayAttachment`）から、描くサブネット・VPC への参照（DependsOn を除く `active` の参照で、リソースそのものを指すもの: TF の `id`、CFN の `Ref`・`SubnetId`・`VpcId`。CIDR や AZ を取るだけの参照は数えない）。属性名では選ばない（黒箱のモジュールの入力の名前はモジュールごとに違うため。ir-schema の 2 章）。`P-REGIONAL` の型（Lambda を除く）は参照があっても `parent: null`。Lambda は VPC の設定（TF の `vpc_config`、CFN・SAM の `Properties.VpcConfig`）の位置の参照だけを使う（環境変数にサブネットの id を渡しても VPC には入らない）。EKS のクラスタは、`P-SPANS` の文のとおりクラスタ自身の `vpc_config.subnet_ids`／`ResourcesVpcConfig.SubnetIds` の位置の参照だけを使い、統合したノードグループ（M-EKS-PARTS）のサブネットは使わない。統合先が 2 つ以上ある M-*（共有の DB サブネットグループなど）は、統合先のすべての手がかりになる。spans のサブネットに共通の祖先が無い（VPC が違う）ときは、spans を付けて `parent: null`（`NORM-PLACEMENT`）。サブネットが VPC を 2 つ以上指すときも `parent: null`（`NORM-PLACEMENT`）。サブネットを指さず VPC だけを指すものは `parent` を VPC（`P-VPC`）。決まらないときの診断は ir-schema の 10 章（`NORM-PLACEMENT`・`NORM-AZ-UNKNOWN`）。
- サブネットの `attrs.access` は、まだ付けない（ルートテーブル・関連付け・ルートを読む R-ROUTE の処理が要るので、辺の段階（手順 4）で R-ROUTE と一緒に作る）。

## attrs の取り方

<!-- rules-table: attrs -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 型 | attrs のキー | 値 | 決め方 | 材料にする規則 |
|---|---|---|---|---|
| `subnet` | `attrs.access` | `public`・`private` | 関連付いたルートテーブルに `0.0.0.0/0 → インターネットゲートウェイ` のルートがあれば `public`、無ければ `private`。 | `R-ROUTE` |

<!-- /rules-table -->
