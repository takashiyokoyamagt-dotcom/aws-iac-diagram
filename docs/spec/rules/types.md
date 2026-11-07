# 型の表（`data/rules/types/*.toml`）

- **これは開発者向けの説明です（SKILL の外。配りません）。** 表そのもの（スクリプトが実行時に読むデータ）は `skills/aws-iac-diagram/data/rules/`（TOML）にあります。下の表は、そのデータから `aws-iac-diagram-workspace/tools/render_rules.py` が作った生成物です（`<!-- rules-table: … -->` の間は直接直さない。直すのはデータ）。全体は [README.md](README.md)

- 状態: フェーズ 3 の手順 2 で、公開サンプルの主セット（CRITERIA の 1.2。12 入力）の型まで広げて凍結した（2026-11-07。主セットで規則表に当たらない型は 0。`tests/integration/test_main_set_types.py`）。補助セットや大きいサンプルの型は、出たときに足す
- 用途: 正規化（PLAN 3 の ②）で、入力の型ごとに「描く／統合する／辺にする／非表示」を決める。正解 IR の網羅分類（A6）の `rule` はこの表と [relations.md](relations.md)・[edges.md](edges.md) の規則ID を指す
- ここに無い型は `unknown`（検証エラーにはしない。件数と型を `result.json` と `coverage.md` に出す。docs/spec/ir-schema/ の 4）
- 1 行 = 1 つの `[[type]]`。ファイルは領域別（`network`・`compute`・`data-stores`・`integration`・`ai-analytics`・`edge-web` が描く型、`merged-and-hidden` が M-*・H-*）。表の拡張（手順 2）で、行を足すだけで増やせる。

## 列

<!-- rules-table: fields-type -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 列 | 型 | 必須 | class（空は共通） | 意味 |
|---|---|---|---|---|
| `id` | 文字列 | 必須 |  | 規則 ID。描く型は正規の型名（ノードの id の接頭辞と同じ）。M-*・H-* は接頭辞が class を決める |
| `class` | 文字列 | 必須 |  | `drawn`（ノードになる）／`merged_into`（M-*。別のノードに統合）／`hidden`（H-*。描かない） |
| `tf` | 文字列の配列 | 必須 |  | 入力の Terraform の型の一覧（末尾が `*` なら前方一致。空もある） |
| `cfn` | 文字列の配列 | 必須 |  | 入力の CloudFormation／SAM の型の一覧 |
| `tf_note` | 文字列 | 省略可 |  | `tf` の一覧に書けない補足（原文の言い回し） |
| `cfn_note` | 文字列 | 省略可 |  | `cfn` の一覧に書けない補足（原文の言い回し） |
| `when` | 表（下の when） | 省略可 |  | この行を使う条件（下の「when」） |
| `category` | 文字列 | 必須 | drawn | ノードの category（`resource`／`group`／`external`） |
| `name_attr` | 表 { tf, cfn } | 必須 | drawn | 名前の属性（B3 の 2 番目）。`{ tf = "name", cfn = "Name" }`。タグだけなら `{}` |
| `icon` | 文字列の配列（1 つ以上） | 必須 | drawn | アイコンの辞書（`find_aws_icon.py --id`）のキーの候補 |
| `synthetic` | 文字列 | 省略可 | drawn | 合成ノードを作る規則 ID（N-*）。合成ノードは入力の型（`tf`・`cfn`）を持たない |
| `name_from` | 文字列 | 省略可 | drawn | 名前を属性から取らないものの取り方（合成ノードなど） |
| `icon_note` | 文字列 | 省略可 | drawn | アイコンの選び方の補足 |
| `data` | 真偽 | 省略可 | drawn | `true` なら、TF の `data` ブロックでも描く（描くリソースから参照されたとき。それ以外は H-DATA。範囲は手順 2 で決める） |
| `into` | 表 { node_types, select } | 必須 | merged_into | 統合先。`node_types` は統合先の描く型、`select` は統合先の選び方（原文） |
| `reason` | 文字列 | 必須 | merged_into・hidden | 理由 |
| `refs_as_target` | 真偽 | 省略可 | merged_into | `true` なら、統合したリソースの中の参照を、統合先からの参照として扱う |
| `applies` | 文字列 | 必須 | hidden | 対象（原文。型では決まらないものの説明を含む） |
| `tf_data` | 文字列の配列 | 省略可 | hidden | 対象の TF の `data` ブロックの型 |
| `data_block` | 真偽 | 省略可 | hidden | `true` なら、ほかの行に当たらない TF の `data` ブロックすべて |
| `evidence_source` | 真偽 | 省略可 | hidden | `true` なら、E-IAM（推定の辺）の材料にしてから非表示にする |
| `module_sources_file` | 文字列 | 省略可 | hidden | モジュールの source の前方一致で同じ規則にする一覧のファイル（SKILL からの相対パス。読むのは core/module_sources.py） |

<!-- /rules-table -->

**`when`（条件。省略可）** は、同じ入力の型でも `via` や属性の値で行が変わるときに使う。キーは次のものだけ。

| キー | 意味 |
|---|---|
| `types` | 条件が効く入力の型（省略すると、その行の `tf`・`cfn` の全部）。例: `aws_security_group_rule` だけが `type` で ingress と egress に分かれる |
| `prop`・`in`・`default` | 属性の値の集合。`prop = { tf = "load_balancer_type", cfn = "Type" }`、`in = ["application"]`、省略時の値 `default`。TF・CFN の属性名を別々に書く |
| `via` ／ `via_not` | raw IR の `via`（`module_blackbox`・`module_summary`・`nested_stack`）。同じ入力の型（`AWS::CloudFormation::Stack`）が、展開できたか（H-NESTED-STACK）、黒箱か（型 `module`）で変わる |

同じ入力の型が複数の行に当たるのは、条件が同時に成り立たないときだけ（`core/rules.py` が検査する）。

## 1. 描く型（ノードになる）

<!-- rules-table: types-drawn -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 正規の型名 | ファイル | category | Terraform | CloudFormation／SAM | 名前属性（B3 の2番目） | アイコン候補（`find_aws_icon.py --id`） | 既存の `data` も描く |
|---|---|---|---|---|---|---|---|
| `bedrock_knowledge_base` | ai-analytics | resource | `aws_bedrockagent_knowledge_base` | `AWS::Bedrock::KnowledgeBase` | `name` ／ `Name` | `resource_icon:bedrock` |  |
| `opensearchserverless_collection` | ai-analytics | resource | `aws_opensearchserverless_collection` | `AWS::OpenSearchServerless::Collection` | `name` ／ `Name` | `resource_icon:elasticsearch_service` |  |
| `bedrock_model` | ai-analytics | resource | （合成: N-BEDROCK-MODEL） | （合成: N-BEDROCK-MODEL） | モデルID | `resource_icon:bedrock` |  |
| `glue_job` | ai-analytics | resource | `aws_glue_job` | `AWS::Glue::Job` | `name` ／ `Name` | `resource_icon:glue` |  |
| `glue_crawler` | ai-analytics | resource | `aws_glue_crawler` | `AWS::Glue::Crawler` | `name` ／ `Name` | `shape:glue_crawlers` |  |
| `glue_catalog_database` | ai-analytics | resource | `aws_glue_catalog_database` | `AWS::Glue::Database` （名前は `DatabaseInput.Name`（入れ子なので name_attr には書かない。`Name` タグか論理名）） | `name` | `shape:glue_data_catalog` |  |
| `ecs_service` | compute | resource | `aws_ecs_service` | `AWS::ECS::Service` | `name` ／ `ServiceName` | `resource_icon:fargate`／`shape:ecs_service` （resource_icon:fargate は Fargate のとき） |  |
| `ec2_instance` | compute | resource | `aws_instance` | `AWS::EC2::Instance` | （タグのみ） | `resource_icon:ec2` |  |
| `lambda_function` | compute | resource | `aws_lambda_function` | `AWS::Lambda::Function`、`AWS::Serverless::Function` | `function_name` ／ `FunctionName` | `resource_icon:lambda` |  |
| `module` | compute | resource | 黒箱のモジュールの呼び出し（A5 の要約表に無いレジストリモジュール、`git::` などのリモートのソース）。IAM だけのモジュールは H-IAM ［条件: raw の via が `module_blackbox` のとき］ | `AWS::CloudFormation::Stack`、`AWS::Serverless::Application` （読めないネストスタックと、SAM のアプリケーション） | モジュール呼び出しの名前 | `group:group_aws_cloud_alt` （仮。フェーズ4 で決める） |  |
| `eks_cluster` | compute | resource | `aws_eks_cluster` | `AWS::EKS::Cluster` | `name` ／ `Name` | `resource_icon:eks` |  |
| `db_instance` | data-stores | resource | `aws_db_instance` | `AWS::RDS::DBInstance` | `identifier` ／ `DBInstanceIdentifier` | `shape:rds_instance` |  |
| `dynamodb_table` | data-stores | resource | `aws_dynamodb_table` | `AWS::DynamoDB::Table`、`AWS::Serverless::SimpleTable` | `name` ／ `TableName` | `resource_icon:dynamodb` |  |
| `s3_bucket` | data-stores | resource | `aws_s3_bucket` | `AWS::S3::Bucket` | `bucket` ／ `BucketName` | `resource_icon:s3` | ○ |
| `cloudfront_distribution` | edge-web | resource | `aws_cloudfront_distribution` （名前の属性が無い（`Name` タグか論理名。K-NAME）） | `AWS::CloudFront::Distribution` | （タグのみ） | `resource_icon:cloudfront` |  |
| `route53_record` | edge-web | resource | `aws_route53_record` | `AWS::Route53::RecordSet`、`AWS::Route53::RecordSetGroup` （`RecordSetGroup` は複数のレコードをまとめて 1 ノードにする（名前は `RecordSets[].Name` の中なので、`Name` タグか論理名）） | `name` ／ `Name` | `resource_icon:route_53` （ホストゾーンは描かない（多くは既存のゾーンを ID で指すだけ）） |  |
| `cognito_user_pool` | edge-web | resource | `aws_cognito_user_pool` | `AWS::Cognito::UserPool` | `name` ／ `UserPoolName` | `resource_icon:cognito` |  |
| `waf_web_acl` | edge-web | resource | `aws_wafv2_web_acl` | `AWS::WAFv2::WebACL` | `name` ／ `Name` | `resource_icon:waf` |  |
| `apigw_http_api` | integration | resource | `aws_apigatewayv2_api` ［条件: 対象の型: `aws_apigatewayv2_api`、`AWS::ApiGatewayV2::Api`。`protocol_type`／`ProtocolType` が `HTTP` のとき］ | `AWS::ApiGatewayV2::Api`、`AWS::Serverless::HttpApi` | `name` ／ `Name` | `resource_icon:api_gateway` |  |
| `apigw_rest_api` | integration | resource | `aws_api_gateway_rest_api` | `AWS::ApiGateway::RestApi`、`AWS::Serverless::Api` | `name` ／ `Name` | `resource_icon:api_gateway` |  |
| `sns_topic` | integration | resource | `aws_sns_topic` | `AWS::SNS::Topic` | `name` ／ `TopicName` | `resource_icon:sns` |  |
| `sqs_queue` | integration | resource | `aws_sqs_queue` | `AWS::SQS::Queue` | `name` ／ `QueueName` | `resource_icon:sqs` |  |
| `eventbridge_rule` | integration | resource | `aws_cloudwatch_event_rule` | `AWS::Events::Rule` | `name` ／ `Name` | `resource_icon:eventbridge` |  |
| `sfn_state_machine` | integration | resource | `aws_sfn_state_machine` | `AWS::StepFunctions::StateMachine`、`AWS::Serverless::StateMachine` （SAM の `AWS::Serverless::StateMachine` の名前は `Name`（name_attr の 1 つの列には書けないので、`Name` タグか論理名）） | `name` ／ `StateMachineName` | `resource_icon:step_functions` |  |
| `vpc` | network | group | `aws_vpc` | `AWS::EC2::VPC` | （タグのみ） | `group:group_vpc2` | ○ |
| `availability_zone` | network | group | （合成: N-AZ） | （合成: N-AZ） | AZ 名 | `plain_group:availability_zone` |  |
| `subnet` | network | group | `aws_subnet` | `AWS::EC2::Subnet` | （タグのみ） | `group:public_subnet`／`group:private_subnet` （`attrs.access` で選ぶ（`public` なら group:public_subnet、`private` なら group:private_subnet）） | ○ |
| `internet_gateway` | network | resource | `aws_internet_gateway` | `AWS::EC2::InternetGateway` | （タグのみ） | `shape:internet_gateway` |  |
| `nat_gateway` | network | resource | `aws_nat_gateway` | `AWS::EC2::NatGateway` | （タグのみ） | `shape:nat_gateway` |  |
| `vpc_endpoint` | network | resource | `aws_vpc_endpoint` | `AWS::EC2::VPCEndpoint` | （タグのみ） | `shape:endpoints` |  |
| `alb` | network | resource | `aws_lb`、`aws_alb` ［条件: `load_balancer_type`／`Type` が `application` のとき（省略時は `application`）］ | `AWS::ElasticLoadBalancingV2::LoadBalancer` | `name` ／ `Name` | `shape:application_load_balancer` |  |
| `external` | network | external | （合成: N-EXT-INTERNET） | （合成: N-EXT-INTERNET） | Internet | `shape:internet_alt2` |  |

<!-- /rules-table -->

- `module`: TF は黒箱のモジュールの呼び出し（A5 の要約表に無いレジストリモジュール、`git::` などのリモートのソース。IAM だけのモジュールは H-IAM）。TF の入力の型は raw IR の `module` で、規則表の `tf` には書かない（黒箱は入力の型によらず `module` のノードになる。`validate_ir.py` の `BLACKBOX_TYPES`）。
- `subnet` の `attrs.access` の決め方は [placement.md](placement.md)。
- **既存の `data` を描く（`data = true`）:** `data` ブロックは H-DATA（描かない）が既定だが、描く型の `data`（`data.aws_vpc`・`data.aws_subnet`・`data.aws_s3_bucket` など）が描くリソースから参照されていれば、既存のノードとして描く（ir-schema の 7.4。T09 の `data.aws_s3_bucket`）。手順 1 では**方針をデータに持たせただけ**で、動きは変えていない（`validate_ir.py` は使わない）。どの型を描くかは手順 2 で決めた: 設計案（`docs/dev-notes/phase3-design-draft.md` の 8 章の 3）の推奨 (c) のとおり、`data = true` の 3 つ（`vpc`・`subnet`・`s3_bucket`）だけ。参照されていない `data` は H-DATA。
- **統合の 2 段:** 統合先がさらに統合される行（M-LAUNCH-TEMPLATE → ノードグループ（M-EKS-PARTS）→ クラスタ）は、描く型に着くまで統合をたどる。

## 2. 統合する型（M-*。`class: merged_into`、`into` はノード）

<!-- rules-table: types-merged -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 規則ID | Terraform | CloudFormation | 統合先（原文 → ノードの型） | 理由 |
|---|---|---|---|---|
| `M-EIP-NAT` | `aws_eip` （NAT が `allocation_id` で参照） | `AWS::EC2::EIP` （NAT が `AllocationId` で参照） | その NAT ゲートウェイ → `nat_gateway` | NAT の付属品で、単独で描く意味が無い |
| `M-IGW-ATTACH` | 該当なし | `AWS::EC2::VPCGatewayAttachment` | そのインターネットゲートウェイ → `internet_gateway` | CFN だけにある接続の型。TF は `aws_internet_gateway.vpc_id` で表す |
| `M-ECS-CLUSTER` | `aws_ecs_cluster` | `AWS::ECS::Cluster` | そのクラスタのサービスすべて → `ecs_service` | クラスタは論理的な入れ物で通信経路を持たない。サービスがサブネットをまたぐので枠にもできない（クラスタ名は将来 `attrs` に残す） |
| `M-ECS-TASKDEF` | `aws_ecs_task_definition` | `AWS::ECS::TaskDefinition` | それを使うサービス → `ecs_service` （中の参照は統合先の参照） | タスク定義の中の参照（環境変数など）は、サービスからの参照として扱う |
| `M-DB-SUBNET-GROUP` | `aws_db_subnet_group` | `AWS::RDS::DBSubnetGroup` | それを使う DB インスタンス → `db_instance` | DB の置き場所（`spans`）を決めるためだけにある |
| `M-S3-CONFIG` | `aws_s3_bucket_versioning`、`aws_s3_bucket_public_access_block`、`aws_s3_bucket_server_side_encryption_configuration`、`aws_s3_bucket_ownership_controls`、`aws_s3_bucket_lifecycle_configuration`、`aws_s3_bucket_policy` | `AWS::S3::BucketPolicy` （バケットポリシーのほかはプロパティ） | そのバケット（参照、またはバケットポリシーの `Bucket` の値がバケットの名前と一致するもの。C02 は `!Sub` の文字列で指す） → `s3_bucket` | TF の provider v4 以降でバケットの設定が別リソースになっただけ。CFN では `AWS::S3::Bucket` のプロパティ |
| `M-APIGW-STAGE` | `aws_apigatewayv2_stage`、`aws_api_gateway_stage`、`aws_api_gateway_deployment` | `AWS::ApiGatewayV2::Stage`、`AWS::ApiGateway::Stage`、`AWS::ApiGateway::Deployment` | その API → `apigw_http_api`・`apigw_rest_api` | デプロイの単位で、構成図では API と同じもの |
| `M-AOSS-POLICY` | `aws_opensearchserverless_security_policy`、`aws_opensearchserverless_access_policy` | `AWS::OpenSearchServerless::SecurityPolicy`、`AWS::OpenSearchServerless::AccessPolicy` | ポリシーの `Rules[].Resource` の `collection/<名前>` が一致するコレクション → `opensearchserverless_collection` | コレクションの設定。参照ではなく名前の一致で結ぶ |
| `M-AOSS-INDEX` | `opensearch_index` （opensearch-project/opensearch プロバイダ） | `AWS::OpenSearchServerless::Index` | プロバイダの `url`／`CollectionEndpoint` が指すコレクション → `opensearchserverless_collection` | コレクションの中身。KB の `vector_index_name` が名前で指す |
| `M-DB-PARAMETER-GROUP` | `aws_db_parameter_group`、`aws_db_option_group` | `AWS::RDS::DBParameterGroup`、`AWS::RDS::OptionGroup` | それを使う DB インスタンス → `db_instance` | DB の設定で、通信経路を持たない |
| `M-S3-OBJECT` | `aws_s3_object` | 該当なし | そのバケット → `s3_bucket` | バケットの中身（Lambda の zip、Glue のスクリプトなど）。置く処理はデプロイ時のもので、構成上の通信ではない |
| `M-APIGW-RESPONSE` | `aws_api_gateway_method_response`、`aws_api_gateway_integration_response` | プロパティ（`AWS::ApiGateway::Method` の `MethodResponses`・`Integration.IntegrationResponses`） | その API → `apigw_rest_api` | 応答の形の設定。辺は R-APIGW-REST（メソッドと統合）が作る |
| `M-APIGW-AUTHORIZER` | `aws_api_gateway_authorizer`、`aws_apigatewayv2_authorizer` | `AWS::ApiGateway::Authorizer`、`AWS::ApiGatewayV2::Authorizer` | その API → `apigw_http_api`・`apigw_rest_api` （中の参照は統合先の参照） | API の付属品。中の参照（Cognito のユーザープール、オーソライザーの Lambda）は API からの参照として扱う（E-AUTHORIZER）。統合先の API そのものへの参照は捨てる |
| `M-LAMBDA-LAYER` | `aws_lambda_layer_version` | `AWS::Lambda::LayerVersion`、`AWS::Serverless::LayerVersion` | それを使う関数すべて → `lambda_function` | 関数のコードの一部 |
| `M-CLOUDFRONT-CONFIG` | `aws_cloudfront_origin_access_control`、`aws_cloudfront_origin_access_identity`、`aws_cloudfront_response_headers_policy`、`aws_cloudfront_cache_policy`、`aws_cloudfront_origin_request_policy` | `AWS::CloudFront::OriginAccessControl`、`AWS::CloudFront::CloudFrontOriginAccessIdentity`、`AWS::CloudFront::ResponseHeadersPolicy`、`AWS::CloudFront::CachePolicy`、`AWS::CloudFront::OriginRequestPolicy` | それを使うディストリビューション → `cloudfront_distribution` | ディストリビューションの設定で、通信経路を持たない |
| `M-ACM-CERT` | `aws_acm_certificate`、`aws_acm_certificate_validation` | `AWS::CertificateManager::Certificate` | それを使うリソース（CloudFront、ALB のリスナー、API のカスタムドメイン） → `cloudfront_distribution`・`alb`・`apigw_http_api`・`apigw_rest_api` | TLS の設定。通信経路を持たない |
| `M-COGNITO-CONFIG` | `aws_cognito_user_pool_client`、`aws_cognito_user_pool_domain` | `AWS::Cognito::UserPoolClient`、`AWS::Cognito::UserPoolDomain` | そのユーザープール → `cognito_user_pool` | ユーザープールの設定 |
| `M-EKS-PARTS` | `aws_eks_node_group`、`aws_eks_addon`、`aws_eks_access_entry`、`aws_eks_access_policy_association`、`aws_eks_fargate_profile` | `AWS::EKS::Nodegroup`、`AWS::EKS::Addon`、`AWS::EKS::AccessEntry`、`AWS::EKS::FargateProfile` | そのクラスタ → `eks_cluster` | クラスタの部品。ノードグループもクラスタの中の計算資源として 1 つのノードにまとめる（ノードグループごとに描くかはフェーズ 4 の B2 の詳細図で決める） |
| `M-LAUNCH-TEMPLATE` | `aws_launch_template` | `AWS::EC2::LaunchTemplate` | それを使うインスタンス、またはそれを使うノードグループのクラスタ（ノードグループは M-EKS-PARTS でクラスタに統合されるので、統合を 2 段たどる） → `eks_cluster`・`ec2_instance` | 起動の設定で、通信経路を持たない。中の SG（`vpc_security_group_ids`）は R-SG の辺の起点を統合先に移すときに使う（手順 5） |

<!-- /rules-table -->

## 3. 非表示にする型（H-*。`class: hidden`）

<!-- rules-table: types-hidden -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 規則ID | 対象（原文） | 機械が読む型・条件 | 理由・補足 |
|---|---|---|---|
| `H-IAM` | `aws_iam_role`、`aws_iam_role_policy`、`aws_iam_role_policy_attachment`、`aws_iam_instance_profile`、`aws_iam_policy`、`aws_iam_openid_connect_provider`、`data.aws_iam_policy_document`、`data.aws_iam_policy`、`AWS::IAM::Role`、`AWS::IAM::Policy`、`AWS::IAM::InstanceProfile`、`AWS::IAM::ManagedPolicy`、`AWS::IAM::RolePolicy`、`AWS::IAM::OIDCProvider` | TF: `aws_iam_role`、`aws_iam_role_policy`、`aws_iam_role_policy_attachment`、`aws_iam_instance_profile`、`aws_iam_policy`、`aws_iam_openid_connect_provider`；CFN: `AWS::IAM::Role`、`AWS::IAM::Policy`、`AWS::IAM::InstanceProfile`、`AWS::IAM::ManagedPolicy`、`AWS::IAM::RolePolicy`、`AWS::IAM::OIDCProvider`；TF の data: `aws_iam_policy_document`、`aws_iam_policy`；E-IAM の材料にしてから非表示（モジュールは `data/module-summaries/iam-only-sources.md` の source の前方一致） | 権限は図に描かない。ただし非表示にする前に E-IAM（推定の辺）の材料として使う |
| `H-LOGS` | `aws_cloudwatch_log_group`、`AWS::Logs::LogGroup` | TF: `aws_cloudwatch_log_group`；CFN: `AWS::Logs::LogGroup` | 運用の付属品。全体図には出さない（B2 の詳細図で出す余地はある） |
| `H-OBSERVABILITY` | `aws_flow_log`、`aws_cloudwatch_metric_alarm`、`aws_cloudwatch_dashboard`、`AWS::EC2::FlowLog`、`AWS::CloudWatch::Alarm`、`AWS::CloudWatch::Dashboard` | TF: `aws_flow_log`、`aws_cloudwatch_metric_alarm`、`aws_cloudwatch_dashboard`；CFN: `AWS::EC2::FlowLog`、`AWS::CloudWatch::Alarm`、`AWS::CloudWatch::Dashboard` | 同上。フローログの送り先のロググループも H-LOGS で非表示になる |
| `H-DATA` | IAM 以外の TF の `data` ブロック（`aws_ssm_parameter`、`aws_caller_identity`、`archive_file` など） | ほかの行に当たらない TF の data ブロックすべて | 値を引くためのもの。ただし `data = true` の描く型（`data.aws_vpc`・`data.aws_subnet`・`data.aws_s3_bucket`）の data が描くリソースから参照されていれば、既存のノードとして描く（ir-schema の 7.4。2026-11-07 に設計草案 8 章の 3 の推奨 (c) で決定。参照されていなければ H-DATA。主セットの T09 が該当） |
| `H-COND-FALSE` | count／for_each が 0 件、または CFN の `Condition` が偽に評価されたリソース | （型では決まらない。辺・条件のあとで決まる） | 作られないもの。TF はインデックスなしのアドレスで1件として数える |
| `H-RT-NOROUTE` | `local` 以外のルートを持たず、**Gateway 型の VPC エンドポイントも関連付いていない** ルートテーブルと、その関連付け | （型では決まらない。辺・条件のあとで決まる） | 辺が1本もできない。サブネットが隔離されていることは辺が無いことで分かる |
| `H-SG-NOEDGE` | 辺を1本も生まないセキュリティグループ | （型では決まらない。辺・条件のあとで決まる） | 辺を生む SG は R-SG で `merged_into` になる |
| `H-SG-EGRESS` | 別リソースの egress ルール（`aws_vpc_security_group_egress_rule`、`aws_security_group_rule`（`type = "egress"`）、`AWS::EC2::SecurityGroupEgress`） | TF: `aws_vpc_security_group_egress_rule`、`aws_security_group_rule`；CFN: `AWS::EC2::SecurityGroupEgress`；条件: 対象の型: `aws_security_group_rule`。`type` が `egress` のとき | v0.1 は egress から辺を作らない（docs/spec/rules/relations.md の補足）。インラインの egress は SG 本体の一部なので個別には数えない |
| `H-UTILITY` | `time_sleep`、`random_*`、`null_resource`、`terraform_data` | TF: `time_sleep`、`random_*`、`null_resource`、`terraform_data` | クラウド上の実体が無い |
| `H-NESTED-STACK` | `AWS::CloudFormation::Stack`（子テンプレートを展開できたもの） | CFN: `AWS::CloudFormation::Stack`；条件: raw の via が `module_blackbox` でないとき | 中身を展開して描く。展開できないもの（`TemplateURL` を手元のファイルに読み替えられない。ir-schema の 7.4）は、黒箱のモジュール（型 `module`、`via: "module_blackbox"`）として描く |
| `H-NONAWS` | AWS 以外のプロバイダの型のうち、H-UTILITY・M-AOSS-INDEX に当たらないもの（kubernetes、helm、tls、local など）。awscc の型は同じ名前の CFN の型として扱うので、ここには入らない | （型では決まらない。辺・条件のあとで決まる） | AWS の構成図の対象外（ir-schema の 7.4） |
| `H-VPC-DEFAULTS` | `aws_default_security_group`、`aws_default_network_acl`、`aws_default_route_table` | TF: `aws_default_security_group`、`aws_default_network_acl`、`aws_default_route_table` | 既定のリソースを管理下に置くためのもので、構成上の役割が無い（terraform-aws-modules/vpc が既定で作る） |
| `H-CFN-CUSTOM` | `AWS::CloudFormation::CustomResource`（カスタムリソース） | CFN: `AWS::CloudFormation::CustomResource` | デプロイの時に 1 回だけ動く処理。裏の Lambda は描く型として描かれる |

<!-- /rules-table -->

- IAM だけを作るモジュールの H-IAM は、`module_sources_file` の一覧（`data/module-summaries/iam-only-sources.md`。説明は [module-summaries.md](../module-summaries.md) の 4章）の source の前方一致で判定する（`core/module_sources.py` の `iam_only()`。アダプタの診断の文言と正規化が同じ判定を使う）。

## 4. 関係リソース（辺に変換する型）

[relations.md](relations.md) を参照（R-*。`class: merged_into`、`into` は辺）。

## 5. 入れ子の規則

[placement.md](placement.md) を参照（N-AZ・P-*）。
