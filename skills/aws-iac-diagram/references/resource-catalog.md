# リソースの型の表（草案）

- 状態: **草案**。フェーズ0 の自作 fixture 5種に出てくる型だけを載せている。フェーズ3 で公開サンプル（C3）の型まで広げる
- 用途: 正規化（PLAN 3 の ②）で、入力の型ごとに「描く／統合する／辺にする／非表示」を決める。正解 IR の網羅分類（A6）の `rule` はこの表と [relation-resources.md](relation-resources.md)・[edge-rules.md](edge-rules.md) の規則ID を指す
- ここに無い型は `unknown`（検証エラーにはしない。件数と型を `result.json` と `coverage.md` に出す。ir-schema.md の 4）

## 1. 描く型（ノードになる）

| 正規の型名 | category | Terraform | CloudFormation／SAM | 名前属性（B3 の2番目） | アイコン候補（`find_aws_icon.py --id`） |
|---|---|---|---|---|---|
| `vpc` | group | `aws_vpc` | `AWS::EC2::VPC` | （タグのみ） | `group:group_vpc2` |
| `availability_zone` | group | （合成: N-AZ） | （合成: N-AZ） | AZ 名 | `plain_group:availability_zone` |
| `subnet` | group | `aws_subnet` | `AWS::EC2::Subnet` | （タグのみ） | `group:public_subnet`／`group:private_subnet`（`attrs.access`） |
| `internet_gateway` | resource | `aws_internet_gateway` | `AWS::EC2::InternetGateway` | （タグのみ） | `shape:internet_gateway` |
| `nat_gateway` | resource | `aws_nat_gateway` | `AWS::EC2::NatGateway` | （タグのみ） | `shape:nat_gateway` |
| `vpc_endpoint` | resource | `aws_vpc_endpoint` | `AWS::EC2::VPCEndpoint` | （タグのみ） | `shape:endpoints` |
| `alb` | resource | `aws_lb`（`load_balancer_type = "application"`、省略時も application）、`aws_alb` | `AWS::ElasticLoadBalancingV2::LoadBalancer`（`Type: application`、省略時も） | `name`／`Name` | `shape:application_load_balancer` |
| `ecs_service` | resource | `aws_ecs_service` | `AWS::ECS::Service` | `name`／`ServiceName` | `resource_icon:fargate`（Fargate）／`shape:ecs_service` |
| `db_instance` | resource | `aws_db_instance` | `AWS::RDS::DBInstance` | `identifier`／`DBInstanceIdentifier` | `shape:rds_instance` |
| `ec2_instance` | resource | `aws_instance` | `AWS::EC2::Instance` | （タグのみ） | `resource_icon:ec2` |
| `lambda_function` | resource | `aws_lambda_function` | `AWS::Lambda::Function`、`AWS::Serverless::Function` | `function_name`／`FunctionName` | `resource_icon:lambda` |
| `dynamodb_table` | resource | `aws_dynamodb_table` | `AWS::DynamoDB::Table`、`AWS::Serverless::SimpleTable` | `name`／`TableName` | `resource_icon:dynamodb` |
| `apigw_http_api` | resource | `aws_apigatewayv2_api`（`protocol_type = "HTTP"`） | `AWS::ApiGatewayV2::Api`（`ProtocolType: HTTP`）、`AWS::Serverless::HttpApi` | `name`／`Name` | `resource_icon:api_gateway` |
| `apigw_rest_api` | resource | `aws_api_gateway_rest_api` | `AWS::ApiGateway::RestApi`、`AWS::Serverless::Api` | `name`／`Name` | `resource_icon:api_gateway` |
| `sns_topic` | resource | `aws_sns_topic` | `AWS::SNS::Topic` | `name`／`TopicName` | `resource_icon:sns` |
| `sqs_queue` | resource | `aws_sqs_queue` | `AWS::SQS::Queue` | `name`／`QueueName` | `resource_icon:sqs` |
| `s3_bucket` | resource | `aws_s3_bucket` | `AWS::S3::Bucket` | `bucket`／`BucketName` | `resource_icon:s3` |
| `bedrock_knowledge_base` | resource | `aws_bedrockagent_knowledge_base` | `AWS::Bedrock::KnowledgeBase` | `name`／`Name` | `resource_icon:bedrock` |
| `opensearchserverless_collection` | resource | `aws_opensearchserverless_collection` | `AWS::OpenSearchServerless::Collection` | `name`／`Name` | `resource_icon:elasticsearch_service` |
| `bedrock_model` | resource | （合成: N-BEDROCK-MODEL） | （合成: N-BEDROCK-MODEL） | モデルID | `resource_icon:bedrock` |
| `external` | external | （合成: N-EXT-INTERNET） | （合成: N-EXT-INTERNET） | `Internet` | `shape:internet_alt2` |

`subnet` の `attrs.access`: 関連付いたルートテーブルに `0.0.0.0/0 → インターネットゲートウェイ` のルートがあれば `public`、無ければ `private`。

## 2. 統合する型（M-*。`class: merged_into`、`into` はノード）

| 規則ID | Terraform | CloudFormation | 統合先 | 理由 |
|---|---|---|---|---|
| `M-EIP-NAT` | `aws_eip`（NAT が `allocation_id` で参照） | `AWS::EC2::EIP`（NAT が `AllocationId` で参照） | その NAT ゲートウェイ | NAT の付属品で、単独で描く意味が無い |
| `M-IGW-ATTACH` | （該当なし） | `AWS::EC2::VPCGatewayAttachment` | そのインターネットゲートウェイ | CFN だけにある接続の型。TF は `aws_internet_gateway.vpc_id` で表す |
| `M-ECS-CLUSTER` | `aws_ecs_cluster` | `AWS::ECS::Cluster` | そのクラスタのサービスすべて | クラスタは論理的な入れ物で通信経路を持たない。サービスがサブネットをまたぐので枠にもできない（クラスタ名は将来 `attrs` に残す） |
| `M-ECS-TASKDEF` | `aws_ecs_task_definition` | `AWS::ECS::TaskDefinition` | それを使うサービス | タスク定義の中の参照（環境変数など）は、サービスからの参照として扱う |
| `M-DB-SUBNET-GROUP` | `aws_db_subnet_group` | `AWS::RDS::DBSubnetGroup` | それを使う DB インスタンス | DB の置き場所（`spans`）を決めるためだけにある |
| `M-S3-CONFIG` | `aws_s3_bucket_versioning`、`aws_s3_bucket_public_access_block`、`aws_s3_bucket_server_side_encryption_configuration`、`aws_s3_bucket_ownership_controls`、`aws_s3_bucket_lifecycle_configuration`、`aws_s3_bucket_policy` | （プロパティ） | そのバケット | TF の provider v4 以降でバケットの設定が別リソースになっただけ。CFN では `AWS::S3::Bucket` のプロパティ |
| `M-APIGW-STAGE` | `aws_apigatewayv2_stage`、`aws_api_gateway_stage`、`aws_api_gateway_deployment` | `AWS::ApiGatewayV2::Stage`、`AWS::ApiGateway::Stage`、`AWS::ApiGateway::Deployment` | その API | デプロイの単位で、構成図では API と同じもの |
| `M-AOSS-POLICY` | `aws_opensearchserverless_security_policy`、`aws_opensearchserverless_access_policy` | `AWS::OpenSearchServerless::SecurityPolicy`、`AWS::OpenSearchServerless::AccessPolicy` | ポリシーの `Rules[].Resource` の `collection/<名前>` が一致するコレクション | コレクションの設定。参照ではなく名前の一致で結ぶ |
| `M-AOSS-INDEX` | `opensearch_index`（opensearch-project/opensearch プロバイダ） | `AWS::OpenSearchServerless::Index` | プロバイダの `url`／`CollectionEndpoint` が指すコレクション | コレクションの中身。KB の `vector_index_name` が名前で指す |

## 3. 非表示にする型（H-*。`class: hidden`）

| 規則ID | 対象 | 理由・補足 |
|---|---|---|
| `H-IAM` | `aws_iam_role`、`aws_iam_role_policy`、`aws_iam_role_policy_attachment`、`aws_iam_instance_profile`、`data.aws_iam_policy_document`、`AWS::IAM::Role`、`AWS::IAM::Policy`、`AWS::IAM::InstanceProfile`、`AWS::IAM::ManagedPolicy` | 権限は図に描かない。ただし非表示にする前に E-IAM（推定の辺）の材料として使う |
| `H-LOGS` | `aws_cloudwatch_log_group`、`AWS::Logs::LogGroup` | 運用の付属品。全体図には出さない（B2 の詳細図で出す余地はある） |
| `H-OBSERVABILITY` | `aws_flow_log`、`AWS::EC2::FlowLog` | 同上。フローログの送り先のロググループも H-LOGS で非表示になる |
| `H-DATA` | IAM 以外の TF の `data` ブロック（`aws_ssm_parameter`、`aws_caller_identity`、`archive_file` など） | 値を引くためのもの。既存のインフラを指す data（`data.aws_vpc` など）を外部ノードとして描くかはフェーズ3 で決める（fixture には無い） |
| `H-COND-FALSE` | count／for_each が 0 件、または CFN の `Condition` が偽に評価されたリソース | 作られないもの。TF はインデックスなしのアドレスで1件として数える |
| `H-RT-NOROUTE` | `local` 以外のルートを持たず、**Gateway 型の VPC エンドポイントも関連付いていない** ルートテーブルと、その関連付け | 辺が1本もできない。サブネットが隔離されていることは辺が無いことで分かる |
| `H-SG-NOEDGE` | 辺を1本も生まないセキュリティグループ | 辺を生む SG は R-SG で `merged_into` になる |
| `H-SG-EGRESS` | 別リソースの egress ルール（`aws_vpc_security_group_egress_rule`、`aws_security_group_rule`（`type = "egress"`）、`AWS::EC2::SecurityGroupEgress`） | v0.1 は egress から辺を作らない（relation-resources.md の補足）。インラインの egress は SG 本体の一部なので個別には数えない |
| `H-UTILITY` | `time_sleep`、`random_*`、`null_resource`、`terraform_data` | クラウド上の実体が無い |
| `H-NESTED-STACK` | `AWS::CloudFormation::Stack`（子テンプレートを展開できたもの） | 中身を展開して描く。展開できないときの扱いはフェーズ1 で決める |
| `H-VPC-DEFAULTS` | `aws_default_security_group`、`aws_default_network_acl`、`aws_default_route_table` | 既定のリソースを管理下に置くためのもので、構成上の役割が無い（terraform-aws-modules/vpc が既定で作る） |

## 4. 関係リソース（辺に変換する型）

[relation-resources.md](relation-resources.md) を参照（R-*。`class: merged_into`、`into` は辺）。

## 5. 入れ子の規則

| 規則ID | 内容 |
|---|---|
| `N-AZ` | サブネットの AZ ごとに `availability_zone` のノードを VPC の下に作り、サブネットをその下に入れる（TerraVision と同じ考え方）。key は `<VPC の key>.<AZ 名>` |
| `P-VPC` | インターネットゲートウェイ、Gateway 型の VPC エンドポイント、複数の AZ にまたがるリソースの `parent` は VPC |
| `P-SUBNET` | サブネットを1つだけ指定するリソース（NAT ゲートウェイ、EC2 インスタンス）の `parent` はそのサブネット |
| `P-SPANS` | サブネットを2つ以上指定するリソース（ALB、ECS サービス、Interface 型の VPC エンドポイント、DB サブネットグループ経由の DB）は、`spans` にそのサブネットを並べ、`parent` はそれらの最も近い共通の祖先（AZ が違えば VPC）にする。描き方（サブネットごとに複製するか、またがる箱にするか）は配置（フェーズ4）で決める |
| `P-REGIONAL` | VPC に入らないリソース（Lambda、DynamoDB、S3、SNS、SQS、API Gateway、Bedrock、OpenSearch Serverless）と `external` は `parent: null`。「AWS Cloud」やリージョンの枠は配置の段階で描き、IR には入れない |

- Lambda を VPC に入れる設定（`vpc_config`）があれば `P-SUBNET`／`P-SPANS` に従う（fixture には無い）。
