# 辺の規則（`data/rules/edges.toml`）

- **これは開発者向けの説明です（SKILL の外。配りません）。** 表そのもの（スクリプトが実行時に読むデータ）は `skills/aws-iac-diagram/data/rules/`（TOML）にあります。下の表は、そのデータから `aws-iac-diagram-workspace/tools/render_rules.py` が作った生成物です（`<!-- rules-table: … -->` の間は直接直さない。直すのはデータ）。全体は [README.md](README.md)

- 状態: **草案**（手順 1 でデータにした。内容は変えていない）。自作 fixture 5種の正解 IR を書くのに必要な分だけ。2026-10-17 に「辺にしない参照」（`E-NOEDGE-*`）を規則 ID 付きの表にした（フェーズ1 の手順1）
- 関係リソースから作る辺は [relations.md](relations.md)（R-*）。ここは **直接の参照・環境変数・IAM・合成ノード** から作る辺と、辺どうしをまとめる規則
- 辺にしない参照（`E-NOEDGE-*`）と参照先にノードが無いときの参照（`E-REF-NONODE`）は [refs.md](refs.md)

## 列

<!-- rules-table: fields-edges -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

**`[[confidence]]`**

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `level` | 文字列 | 必須 | `confirmed`／`derived`／`inferred` |
| `basis` | 文字列 | 必須 | 根拠（原文） |
| `rules` | 文字列の配列（1 つ以上） | 必須 | この確信度になる規則（末尾が `*` なら前方一致）。辺の規則と関係リソースの `confidence` と食い違わない |
| `draw` | 文字列 | 必須 | 描き方（フェーズ 4 以降） |

**`[[edge]]`**

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `id` | 文字列 | 必須 | 規則 ID（`E-` で始まる） |
| `input` | 文字列 | 必須 | 入力（原文） |
| `edge` | 文字列 | 必須 | 辺（from → to）の説明（原文） |
| `kind` | 文字列（空も可） | 必須 | 辺の kind。空は、`kind_by` の表で決める（または辺を作らない） |
| `kind_by` | 文字列 | 省略可 | kind を決める表（`kind_by_target`／`iam_action_kind`／`merge_priority`） |
| `kind_note` | 文字列 | 省略可 | kind の補足（原文） |
| `confidence` | 文字列（空も可） | 必須 | 確信度。空は、規則が決めない（E-IAM-SUPPRESS）か、強い方を取る（E-MERGE） |
| `confidence_note` | 文字列 | 省略可 | 確信度の補足 |

**`[[kind_by_target]]`**

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `kind` | 文字列 | 必須 | kind |
| `types` | 文字列の配列（1 つ以上） | 必須 | 参照先の型（描く型。`apigw_*` のような前方一致も書ける） |

**`[[iam_action_kind]]`**

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `kind` | 文字列 | 必須 | kind。行の順が優先順（1 つのステートメントに複数のアクションがあれば上の行） |
| `actions` | 文字列の配列（1 つ以上） | 必須 | IAM のアクション（末尾が `*` なら前方一致） |
| `actions_note` | 文字列 | 省略可 | アクションの補足（原文） |

**`[[merge_priority]]`**

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `rank` | 整数 | 必須 | 優先順（1 が最も強い。1 から順に 1 つずつ） |
| `rules` | 文字列の配列（1 つ以上） | 必須 | その順位の規則（末尾が `*` なら前方一致） |

**`[[synthetic]]`**

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `id` | 文字列 | 必須 | 規則 ID（`N-` で始まる） |
| `trigger` | 文字列 | 必須 | いつ作るか（原文） |
| `node` | 文字列 | 必須 | 作るノード（原文） |
| `edges` | 文字列 | 必須 | 作る辺（原文） |

**`[[label_format]]`**

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `subject` | 文字列 | 必須 | ラベルの種類 |
| `format` | 文字列 | 必須 | 書式（原文） |
| `example` | 文字列（空も可） | 必須 | 例 |

**`edges.toml` の最上位のキー**

| キー | 値 | 意味 |
|---|---|---|
| `confidence_order` | `["confirmed", "derived", "inferred"]` | E-MERGE: 確信度は強い方（左が強い） |
| `iam_action_priority` | `"first_row_wins"` | `[[iam_action_kind]]` は、1 つのステートメントに複数のアクションがあれば上の行を優先 |
| `iam_action_default` | `"none"` | どの行にも当たらないアクションは辺を作らない（v0.1） |

<!-- /rules-table -->

## 1. 確信度（A3）

<!-- rules-table: confidence -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 確信度 | 根拠 | 規則 | 描き方（フェーズ4 以降） |
|---|---|---|---|
| `confirmed` | 設定の属性からの直接の参照（`aws_dynamodb_table.orders.name`、`!Ref OrdersTable`、`!GetAtt Database.Endpoint.Address`）。モジュールの出力・変数、ネストスタックの出力・パラメータを通っても、元が参照なら確定 | `E-ENV-REF`、`E-KB-STORAGE`、`E-CDN-ORIGIN`、`E-CDN-WAF`、`E-DNS-ALIAS`、`E-GLUE-TARGET`、`E-AUTHORIZER` | 実線 |
| `derived` | 関係リソースの変換（R-*）、SG からの導出（R-SG）、型の定義で意味が決まっている属性の文字列（KB の `embedding_model_arn`）、合成ノードへの辺 | `R-*`、`E-BEDROCK-EMBEDDING`、`N-EXT-INTERNET` | 実線＋ラベル |
| `inferred` | IAM の Resource ARN、環境変数などの文字列が名前・ARN と一致するだけのもの | `E-IAM`、`E-ENV-STR` | 破線＋凡例。既定で非表示にもできる。根拠を説明 .md に一覧で載せる |

<!-- /rules-table -->

## 2. 規則

<!-- rules-table: edge-rules -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 規則ID | 入力 | 辺（from → to） | kind | 確信度 |
|---|---|---|---|---|
| `E-ENV-REF` | 計算リソース（Lambda、ECS サービス＝タスク定義を含む）の環境変数の値が、ほかのリソースの属性への参照 | 計算リソース → 参照先 | 参照先の型で決める（下の表） | `confirmed` |
| `E-ENV-STR` | 環境変数の値が文字列で、ほかのリソースの名前・ARN と一致する | 計算リソース → 一致したリソース | 同上 | `inferred` |
| `E-IAM` | ロールを引き受けるリソース（Lambda・ECS タスクの実行ロール／タスクロール、EC2 のインスタンスプロファイル、Bedrock KB・Step Functions などの `role_arn`／`RoleArn` で指定するサービスロール）に付いたポリシーの `Resource` が、ほかのリソースの ARN（参照、または文字列の一致）。v0.1 はリソース部分にワイルドカードの無い ARN と、S3 の `<bucket>/*` だけを照合する | ロールを引き受けるリソース → そのリソース | 下の「E-IAM のアクション → kind」 | `inferred` |
| `E-IAM-SUPPRESS` | E-IAM の辺と **逆向き** の辺が、ほかの規則で同じ組にできている | E-IAM の辺を作らない（例: ESM で テーブル → 関数 があるとき、ストリームを読む権限から 関数 → テーブル を作らない） |  |  |
| `E-KB-STORAGE` | ナレッジベースの `storage_configuration`（`collection_arn`／`CollectionArn`） | KB → ベクトルストア | `data` | `confirmed` |
| `E-BEDROCK-EMBEDDING` | ナレッジベースの `embedding_model_arn`／`EmbeddingModelArn` | KB → `bedrock_model`（N-BEDROCK-MODEL） | `request` | `derived` |
| `E-CDN-ORIGIN` | CloudFront のオリジン（`origin[].domain_name`／`Origins[].DomainName`）が、ほかのリソース（S3 バケット、ALB、API Gateway）の属性への参照 | ディストリビューション → オリジン | `request` | `confirmed` |
| `E-CDN-WAF` | CloudFront の `web_acl_id`／`WebACLId` が Web ACL への参照 | Web ACL → ディストリビューション（利用者からの通信は WAF を通ってからディストリビューションに届く） | `request` | `confirmed` |
| `E-DNS-ALIAS` | Route 53 のレコードのエイリアス（`alias[].name`／`AliasTarget.DNSName`。`RecordSetGroup` は `RecordSets[].AliasTarget.DNSName`）が、ほかのリソースの属性への参照 | レコード → エイリアス先（CloudFront、ALB、API Gateway） | `request` | `confirmed` |
| `E-GLUE-TARGET` | Glue のクローラの `database_name`／`DatabaseName` と、ターゲット（`s3_target[].path`／`Targets.S3Targets[].Path`、`jdbc_target`・`dynamodb_target` など）が、ほかのリソースの属性への参照 | クローラ → 読むデータストア、クローラ → 書くカタログのデータベース | `data` | `confirmed` |
| `E-AUTHORIZER` | M-APIGW-AUTHORIZER で統合したオーソライザーの `provider_arns`／`ProviderARNs`（Cognito のユーザープール）と `authorizer_uri`／`AuthorizerUri`（Lambda）が、ほかのリソースへの参照。統合先の API そのものへの参照（`rest_api_id`／`RestApiId`）は辺にしない（自分への辺になる） | API → ユーザープール、API → オーソライザーの関数 | `request` | `confirmed` |
| `E-MERGE` | 同じ順序付きの組に、複数の規則から辺ができた | 1本にまとめる | 下の「まとめ方」 | 強い方 |

<!-- /rules-table -->

**E-ENV-REF／E-ENV-STR の kind（参照先の型 → kind）**

<!-- rules-table: kind-by-target -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 参照先の型 | kind |
|---|---|
| `dynamodb_table`、`s3_bucket`、`db_instance`、`opensearchserverless_collection`、`glue_catalog_database` | `data` |
| `sns_topic`、`sqs_queue`、`eventbridge_rule` | `event` |
| `lambda_function`、`apigw_*`、`bedrock_knowledge_base`、`bedrock_model`、`sfn_state_machine`、`glue_job`、`glue_crawler`、`cognito_user_pool`、`eks_cluster` | `request` |

<!-- /rules-table -->

**E-IAM のアクション → kind**（1つのステートメントに複数のアクションがあれば、この表の上にあるものを優先）

<!-- rules-table: iam-action-kind -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| アクション | kind |
|---|---|
| `lambda:InvokeFunction`、`states:StartExecution`、`bedrock:InvokeModel*`、`bedrock:Retrieve`、`bedrock:RetrieveAndGenerate`、`bedrock:StartIngestionJob`、`execute-api:Invoke` | `request` |
| `sns:Publish`、`sqs:SendMessage`、`events:PutEvents`、`kinesis:PutRecord*`、`firehose:PutRecord*` | `event` |
| `dynamodb:*`（読み書き・ストリームの読み取り）、`s3:GetObject`・`s3:PutObject`・`s3:ListBucket` など、`rds-data:*`、`aoss:APIAccessAll`、`sqs:ReceiveMessage` | `data` |
| それ以外 | 辺を作らない（v0.1） |

<!-- /rules-table -->

## 3. 合成ノード

<!-- rules-table: synthetic -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 規則ID | いつ作るか | ノード | 辺 |
|---|---|---|---|
| `N-EXT-INTERNET` | (a) インターネット向けの LB（`internal = false`／`Scheme: internet-facing`）で、SG が `0.0.0.0/0` からの ingress を許す、(b) パブリックな API Gateway（REST の `REGIONAL`／`EDGE`、HTTP API） | `external/internet`（label `Internet`、`parent: null`、`synthetic: true`）。構成ごとに1つ | internet → LB（`request`、リスナーの `<PROTOCOL> <port>`）、internet → API（`request`、`HTTPS`）。`derived` |
| `N-BEDROCK-MODEL` | 基盤モデルの ARN（`arn:aws:bedrock:<region>::foundation-model/<model id>`）が、KB の埋め込み設定、IAM の `Resource`、環境変数のどれかに現れる | `bedrock_model/<model id の key>`（label はモデルID、`parent: null`、`synthetic: true`） | E-BEDROCK-EMBEDDING、E-IAM、E-ENV-STR で作る |

<!-- /rules-table -->

- インターネットゲートウェイと `external/internet` は結ばない（ルートの辺がサブネット → IGW で止まる）。経路の終点が IGW であることで外に出られることを表す。

## 4. まとめ方（E-MERGE）

1. 確信度は `confirmed` > `derived` > `inferred` で強い方。
2. `kind` は優先順の高い規則のもの。優先順: R-LB-*・R-APIGW-*・R-ROUTE・R-VPCE-GATEWAY > R-LAMBDA-ESM・R-SNS-SUBSCRIPTION・R-S3-NOTIFICATION・R-BEDROCK-DATA-SOURCE > E-ENV-REF・E-KB-STORAGE・E-BEDROCK-EMBEDDING > E-ENV-STR > R-SG > E-IAM。
   - 例: ECS サービス → RDS は、E-ENV-REF（`data`）と R-SG（`network`）から `data`。
3. `label` は優先順の高い規則から順に見て、最初の空でないもの。ただし **同じ規則から同じ組に複数のラベルが出たとき**（同じサブネットから同じ宛先へのルートが複数ある、SG のルールが複数のポートを許す、API のルートが複数ある）は、重複を除いて辞書順に `, ` でつなぐ（例: `0.0.0.0/0, 10.20.0.0/16`、`TCP 443, TCP 80`、`GET /orders, POST /orders`）。
   - 例: 同じ ECS サービス → RDS は、E-ENV-REF にラベルが無いので R-SG の `TCP 5432`。
4. 根拠（`sources.*.edges[]`）には、まとめた規則と根拠をすべて並べる。


**E-MERGE の 2 の優先順**（`[[merge_priority]]`。上ほど強い。ここに無い R-LAMBDA-PERMISSION・R-SQS-QUEUE-POLICY は、既存の辺に従う）

<!-- rules-table: merge-priority -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 優先順（上ほど強い） | 規則 |
|---|---|
| 1 | `R-LB-*`、`R-APIGW-*`、`R-ROUTE`、`R-VPCE-GATEWAY` |
| 2 | `R-LAMBDA-ESM`、`R-SNS-SUBSCRIPTION`、`R-S3-NOTIFICATION`、`R-BEDROCK-DATA-SOURCE` |
| 3 | `E-ENV-REF`、`E-KB-STORAGE`、`E-BEDROCK-EMBEDDING`、`E-CDN-ORIGIN`、`E-CDN-WAF`、`E-DNS-ALIAS`、`E-GLUE-TARGET`、`E-AUTHORIZER` |
| 4 | `E-ENV-STR` |
| 5 | `R-SG` |
| 6 | `E-IAM` |

<!-- /rules-table -->

## 5. ラベル

<!-- rules-table: label-format -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 種類 | 書式 | 例 |
|---|---|---|
| LB のリスナー・ターゲットグループ | `<PROTOCOL> <port>` | `HTTP 80`、`HTTP 8080` |
| SG | `TCP <port>`／`TCP <from>-<to>`／`UDP …`／`ALL` | `TCP 5432` |
| ルート | 宛先 CIDR、または `<サービス> prefix list` | `0.0.0.0/0`、`s3 prefix list` |
| API Gateway | ルートキー（HTTP API）／`<METHOD> <path>`（REST）を辞書順に `, ` でつなぐ | `GET /orders, POST /orders` |
| internet → API | `HTTPS` |  |
| それ以外 | 空文字 |  |

<!-- /rules-table -->

## 6. 判断の理由

- **環境変数の参照は確定、IAM は推定。** 環境変数に参照先を渡すのは「そこに接続する」ためなので、通信の向きと一致する。IAM は「してもよい」だけで、実際に通信するとは限らない。
- **E-IAM-SUPPRESS を入れる理由。** ESM や S3 通知のように、受け手が読みに行く（ポーリングする、取得する）関係では、IAM の向き（受け手 → 送り手）とデータの向き（送り手 → 受け手）が逆になる。両方を描くと、同じ組に逆向きの矢印が2本出る。
- **KB → 埋め込みモデルを derived にする理由。** モデルはリソースではなく文字列の ARN だが、`embedding_model_arn` という属性の意味は型の定義で決まっていて、推測ではない。逆に、Lambda の環境変数 `MODEL_ARN` は名前から意味を推測しているだけなので inferred にする。
- **実装（フェーズ 3 の手順 4b。`scripts/aws_iac_diagram/normalize/attr_edges.py`・`iam.py`・`synthetic.py`）で決めたこと:** ① E-ENV-REF の参照先の型が kind の表に無いとき（VPC など）は辺にしない。② E-ENV-STR は、文字列が 1 つのリソースの名前（型の名前属性の値）か ARN にだけ当たるときに作る。③ E-IAM のロールを引き受けるリソースは、`role`・`role_arn`・`execution_role_arn`・`task_role_arn` でロールを指すもの（タスク定義は統合先のサービス）と、インスタンスプロファイル経由の EC2。SAM のポリシーテンプレートは、テンプレートごとの代表のアクション（`DynamoDBCrudPolicy` → `dynamodb:PutItem` など）で kind を決める（表に無いテンプレートは辺にしない）。④ `Resource` の `<参照>/*` は S3 のバケットだけ、ほかの接尾辞（`/index/*` など）は照合しない。⑤ E-IAM-SUPPRESS で作らなかった E-IAM の根拠は、逆向きの辺の根拠に「(逆向きなので辺にしない)」を付けて書く。⑥ ラベル（4 の 3）は、優先順の順位が同じ規則が 2 つあれば規則 ID の辞書順で先のもの。⑦ E-ENV-STR の名前の一致は、値が 3 文字以上で英字だけでないときだけ（`STAGE=prod` のようなありふれた語を、`prod` という名前のバケットと結ばない。ARN の文字列は別に照合する）。E-IAM の ARN の文字列も、名前で当たるリソースがちょうど 1 つのときだけで、ARN のリージョンとリソースのリージョン（raw の `region`）がどちらも文字列で決まっていて違えば当てない（アカウントは IR に持たないので比べない）。⑧ `Resource` の `$concat` は、文字列・`$pseudo`・参照 1 つだけで、参照の後ろが何も無いか S3 の `/*` のとき、その参照として扱う（`!Sub arn:${AWS::Partition}:s3:::${Bucket}/*`、`arn:…:sqs:${AWS::Region}:${AWS::AccountId}:${Queue.QueueName}`）。前の文字列が ARN なら、サービスと参照先の型が合うときだけ。⑨ 文のアクションのワイルドカード（`s3:*`・`s3:Get*`）は、同じサービスの中で表のアクションに当てる（`*` だけは当てない）。同じ組の E-IAM の kind が文によって違えば、`[[iam_action_kind]]` の行の順（first_row_wins）で決める。⑩ 端点が黒箱のモジュール（型 `module`）の辺は、どの規則でも `inferred`・`request`（ir-schema の 2 章）。
