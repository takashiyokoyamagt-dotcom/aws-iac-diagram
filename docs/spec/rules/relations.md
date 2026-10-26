# 関係リソースの表（`data/rules/relations.toml`）

- **これは開発者向けの説明です（SKILL の外。配りません）。** 表そのもの（スクリプトが実行時に読むデータ）は `skills/aws-iac-diagram/data/rules/`（TOML）にあります。下の表は、そのデータから `aws-iac-diagram-workspace/tools/render_rules.py` が作った生成物です（`<!-- rules-table: … -->` の間は直接直さない。直すのはデータ）。全体は [README.md](README.md)

- 状態: **草案**（手順 1 でデータにした。内容は変えていない）。自作 fixture 5種に出てくるものと、PLAN 4 の A1 に挙がっているものだけ
- 関係リソース = 2つのリソースを結ぶためだけにある型（またはプロパティ）。ノードにせず **辺に変換** する。網羅分類は `class: merged_into`、`into` は変換先の辺の id（複数可）、`rule` はこの表の規則ID
- 変換した辺の確信度は `derived`（A3）。向き・種類・ラベルはこの表で決め、参照の向きには従わない（A2）
- SAM の `Events` のように **プロパティ** で表される関係は、網羅分類には現れない（リソースではないため）。辺の根拠（`sources.*.edges[].evidence`）にだけ現れる

## 列

<!-- rules-table: fields-relation -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `id` | 文字列 | 必須 | 規則 ID（`R-` で始まる） |
| `class` | 文字列 | 必須 | `merged_into` 固定（関係リソースは辺に統合される。網羅分類の `into` は辺） |
| `tf` | 文字列の配列 | 必須 | 網羅分類に出る Terraform のリソースの型 |
| `cfn` | 文字列の配列 | 必須 | 網羅分類に出る CloudFormation／SAM のリソースの型 |
| `tf_props` | 文字列の配列 | 省略可 | 親リソースのプロパティ（ブロック）で表される関係（`型.属性`）。リソースではないので網羅分類には出ない |
| `cfn_props` | 文字列の配列 | 省略可 | 同上（CFN） |
| `sam` | 文字列の配列 | 省略可 | SAM の `Events` の Type（リソースではないので網羅分類には出ない） |
| `tf_note` | 文字列 | 省略可 | 補足 |
| `cfn_note` | 文字列 | 省略可 | 補足 |
| `edge` | 文字列 | 必須 | 辺（from → to）の説明（原文） |
| `kind` | 文字列（空も可） | 必須 | 辺の kind（`request`／`event`／`data`／`route`／`network`）。空は「既存の辺に従う」（`kind_note` が要る） |
| `kind_note` | 文字列 | 省略可 | kind の補足 |
| `label` | 文字列（空も可） | 必須 | ラベルの説明（原文） |
| `confidence` | 文字列 | 必須 | 確信度。関係リソースの辺は `derived`（A3） |
| `fallback` | 文字列 | 省略可 | 辺ができなかったときの H-* の規則 ID |
| `when` | 表（下の when） | 省略可 | この行を使う条件（`types` で対象の型を絞れる） |

<!-- /rules-table -->

## 表（R-*）

<!-- rules-table: relations -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 規則ID | Terraform | CloudFormation／SAM | 辺（from → to） | kind | ラベル | 確信度・辺ができなかったとき |
|---|---|---|---|---|---|---|
| `R-ROUTE` | `aws_route_table`、`aws_route`、`aws_route_table_association`、プロパティ: `aws_route_table.route` | `AWS::EC2::RouteTable`、`AWS::EC2::Route`、`AWS::EC2::SubnetRouteTableAssociation` | ルートテーブルに関連付いた各サブネット → ルートの宛先（インターネットゲートウェイ、NAT ゲートウェイ、TGW など） | `route` | 宛先の CIDR（`0.0.0.0/0`） | 確信度 `derived` 辺ができなければ `H-RT-NOROUTE` |
| `R-VPCE-GATEWAY` | プロパティ: `aws_vpc_endpoint.route_table_ids` ［条件: 対象の型: `aws_vpc_endpoint`、`AWS::EC2::VPCEndpoint`。`vpc_endpoint_type`／`VpcEndpointType` が `Gateway` のとき］ | プロパティ: `AWS::EC2::VPCEndpoint.RouteTableIds` | そのルートテーブルに関連付いた各サブネット → エンドポイント | `route` | `<サービス> prefix list`（`s3 prefix list`） | 確信度 `derived` |
| `R-LB-LISTENER` | `aws_lb_listener` | `AWS::ElasticLoadBalancingV2::Listener` | （インターネット向けの LB なら）`external/internet` → LB と、LB → 転送先のターゲット | `request` | internet → LB はリスナーの `<PROTOCOL> <port>`（`HTTP 80`） | 確信度 `derived` |
| `R-LB-TG` | `aws_lb_target_group`、`aws_lb_target_group_attachment`、プロパティ: `aws_ecs_service.load_balancer` | `AWS::ElasticLoadBalancingV2::TargetGroup`、プロパティ: `AWS::ECS::Service.LoadBalancers` | LB → ターゲット（ECS サービス、EC2、Lambda）。**参照はサービス → ターゲットグループだが、向きは LB → サービス** | `request` | ターゲットグループの `<PROTOCOL> <port>`（`HTTP 8080`） | 確信度 `derived` |
| `R-SG` | `aws_security_group`、`aws_security_group_rule`、`aws_vpc_security_group_ingress_rule`、プロパティ: `aws_security_group.ingress` ［条件: 対象の型: `aws_security_group_rule`。`type` が `ingress` のとき］ | `AWS::EC2::SecurityGroup`、`AWS::EC2::SecurityGroupIngress`、プロパティ: `AWS::EC2::SecurityGroup.SecurityGroupIngress` | SG X の ingress ルールの送信元が SG Y なら、Y を付けた各リソース → X を付けた各リソース。送信元が `0.0.0.0/0`／`::/0` で、X を付けたリソースがインターネットに公開されていれば `external/internet` → そのリソース。「公開されている」は、インターネット向けの LB（`internal = false`／`Scheme: internet-facing`）、パブリック IP を持つ EC2（`associate_public_ip_address`、パブリックサブネットの `map_public_ip_on_launch`）。**それ以外の外部の CIDR**（管理用ネットワークからの SSH など。three-tier の prod の踏み台）は v0.1 では辺にしない（相手のノードが無い）。VPC の CIDR 内からの許可も辺にしない（相手が特定できない） | `network` ほかの根拠があればそちらの kind（E-MERGE） | `TCP <port>`（範囲は `TCP 1024-65535`、全プロトコルは `ALL`） | 確信度 `derived` 辺ができなければ `H-SG-NOEDGE` |
| `R-APIGW-HTTP` | `aws_apigatewayv2_integration`、`aws_apigatewayv2_route` | `AWS::ApiGatewayV2::Integration`、`AWS::ApiGatewayV2::Route` SAM の Events の Type: `HttpApi` | API → 統合先（Lambda など） | `request` | ルートキーを辞書順に `, ` でつなぐ（`GET /orders, POST /orders`） | 確信度 `derived` |
| `R-APIGW-REST` | `aws_api_gateway_resource`、`aws_api_gateway_method`、`aws_api_gateway_integration` | `AWS::ApiGateway::Resource`、`AWS::ApiGateway::Method` （`Integration` を含む） SAM の Events の Type: `Api` | API → 統合先 | `request` | `<METHOD> <path>` を辞書順に `, ` でつなぐ（`POST /query`） | 確信度 `derived` |
| `R-LAMBDA-PERMISSION` | `aws_lambda_permission` | `AWS::Lambda::Permission` | 呼び出し元（`source_arn`／`SourceArn` のリソース）→ 関数。同じ組の辺がほかの規則でできていれば、その辺の根拠に加えるだけ。ほかの規則の辺が無いときは、`principal` で kind を決めて辺を作る（`apigateway`・`elasticloadbalancing` → `request`、`s3`・`sns`・`events`・`logs` など → `event`）。`source_arn` のリソースが入力に無いとき（ワイルドカードや別スタック）は辺を作らず `H-IAM` | 既存の辺に従う／無ければ左の規則 | 既存の辺に従う／無ければ空 | 確信度 `derived` 辺ができなければ `H-IAM` |
| `R-LAMBDA-ESM` | `aws_lambda_event_source_mapping` | `AWS::Lambda::EventSourceMapping` SAM の Events の Type: `DynamoDB`、`Kinesis`、`SQS` | イベントソース（DynamoDB テーブル、Kinesis、SQS）→ 関数。**関数がポーリングするが、向きはデータの流れ** | `event` | （なし） | 確信度 `derived` |
| `R-SNS-SUBSCRIPTION` | `aws_sns_topic_subscription` | `AWS::SNS::Subscription`、プロパティ: `AWS::SNS::Topic.Subscription` SAM の Events の Type: `SNS` | トピック → 購読先（SQS、Lambda など） | `event` | （なし） | 確信度 `derived` |
| `R-SQS-QUEUE-POLICY` | `aws_sqs_queue_policy` | `AWS::SQS::QueuePolicy` | 許可された送信元（`aws:SourceArn`）→ キュー。同じ組の辺があればその根拠に加えるだけ。ほかの規則の辺が無く、送信元が入力のリソースなら `event` の辺を作る。送信元が入力に無い・条件が無いときは辺を作らず `H-IAM` | 既存の辺に従う／無ければ `event` | 既存の辺に従う／無ければ空 | 確信度 `derived` 辺ができなければ `H-IAM` |
| `R-S3-NOTIFICATION` | `aws_s3_bucket_notification` | プロパティ: `AWS::S3::Bucket.NotificationConfiguration` | バケット → 通知先（Lambda、SQS、SNS） | `event` | （なし） | 確信度 `derived` |
| `R-BEDROCK-DATA-SOURCE` | `aws_bedrockagent_data_source` | `AWS::Bedrock::DataSource` | データソースのバケット → ナレッジベース（取り込み） | `data` | （なし） | 確信度 `derived` |

<!-- /rules-table -->

## 補足（判断の理由）

- **SG は辺にする（R-SG）。** SG を枠として描く方法もあるが、PLAN 3 の ② で「SG を辺に変換」と決めている。SG の資源そのものは、生んだ辺（送信先としても送信元としても）を `into` に並べる。辺を生まない SG は `H-SG-NOEDGE`。
- **egress ルールからは辺を作らない（v0.1）。** 送信元・送信先の両方の SG を見れば ingress だけで通信の組が決まり、egress まで見ると同じ組が重複する。`0.0.0.0/0` への egress は「どこへでも出られる」だけで、相手が決まらない。
- **ルートの辺の始点はサブネット（グループ）にする。** ルートテーブルはサブネットに関連付くので、ノードからではなく枠から辺を出す。NAT や IGW への経路が AZ ごとに違う構成（vpc-endpoints）を区別するため。
- **ALB への入口の辺（internet → ALB）は、リスナーと SG の両方から導く。** リスナーだけでは公開されているか分からず（`internal` 属性と SG で決まる）、SG だけではプロトコルが分からないため。
- **API Gateway の統合とルート、メソッドは1本の辺にまとめる。** ルートごとに辺を分けると、同じ API → Lambda の組に辺が何本もでき E-MERGE と矛盾するので、ルートはラベルに並べる。
