# 辺の規則（A2・A3、草案）

- 状態: **草案**。自作 fixture 5種の正解 IR を書くのに必要な分だけ
- 関係リソースから作る辺は [relation-resources.md](relation-resources.md)（R-*）。ここは **直接の参照・環境変数・IAM・合成ノード** から作る辺と、辺どうしをまとめる規則

## 1. 確信度（A3）

| 確信度 | 根拠 | 規則 | 描き方（フェーズ4 以降） |
|---|---|---|---|
| `confirmed` | 設定の属性からの直接の参照（`aws_dynamodb_table.orders.name`、`!Ref OrdersTable`、`!GetAtt Database.Endpoint.Address`）。モジュールの出力・変数、ネストスタックの出力・パラメータを通っても、元が参照なら確定 | E-ENV-REF、E-KB-STORAGE | 実線 |
| `derived` | 関係リソースの変換（R-*）、SG からの導出（R-SG）、型の定義で意味が決まっている属性の文字列（KB の `embedding_model_arn`）、合成ノードへの辺 | R-*、E-BEDROCK-EMBEDDING、N-EXT-INTERNET | 実線＋ラベル |
| `inferred` | IAM の Resource ARN、環境変数などの文字列が名前・ARN と一致するだけのもの | E-IAM、E-ENV-STR | 破線＋凡例。既定で非表示にもできる。根拠を説明 .md に一覧で載せる |

## 2. 規則

| 規則ID | 入力 | 辺（from → to） | kind | 確信度 |
|---|---|---|---|---|
| `E-ENV-REF` | 計算リソース（Lambda、ECS サービス＝タスク定義を含む）の環境変数の値が、ほかのリソースの属性への参照 | 計算リソース → 参照先 | 参照先の型で決める（下の表） | `confirmed` |
| `E-ENV-STR` | 環境変数の値が文字列で、ほかのリソースの名前・ARN と一致する | 計算リソース → 一致したリソース | 同上 | `inferred` |
| `E-IAM` | ロールを引き受けるリソース（Lambda・ECS タスクの実行ロール／タスクロール、EC2 のインスタンスプロファイル、Bedrock KB・Step Functions などの `role_arn`／`RoleArn` で指定するサービスロール）に付いたポリシーの `Resource` が、ほかのリソースの ARN（参照、または文字列の一致）。v0.1 はリソース部分にワイルドカードの無い ARN と、S3 の `<bucket>/*` だけを照合する | ロールを引き受けるリソース → そのリソース | 下の「E-IAM のアクション → kind」 | `inferred` |
| `E-IAM-SUPPRESS` | E-IAM の辺と **逆向き** の辺が、ほかの規則で同じ組にできている | E-IAM の辺を作らない（例: ESM で テーブル → 関数 があるとき、ストリームを読む権限から 関数 → テーブル を作らない） | | |
| `E-KB-STORAGE` | ナレッジベースの `storage_configuration`（`collection_arn`／`CollectionArn`） | KB → ベクトルストア | `data` | `confirmed` |
| `E-BEDROCK-EMBEDDING` | ナレッジベースの `embedding_model_arn`／`EmbeddingModelArn` | KB → `bedrock_model`（N-BEDROCK-MODEL） | `request` | `derived` |
| `E-MERGE` | 同じ順序付きの組に、複数の規則から辺ができた | 1本にまとめる | 下の「まとめ方」 | 強い方 |

**E-ENV-REF／E-ENV-STR の kind（参照先の型 → kind）**

| 参照先の型 | kind |
|---|---|
| `dynamodb_table`、`s3_bucket`、`db_instance`、`opensearchserverless_collection` | `data` |
| `sns_topic`、`sqs_queue` | `event` |
| `lambda_function`、`apigw_*`、`bedrock_knowledge_base`、`bedrock_model` | `request` |

**E-IAM のアクション → kind**（1つのステートメントに複数のアクションがあれば、この表の上にあるものを優先）

| アクション | kind |
|---|---|
| `lambda:InvokeFunction`、`states:StartExecution`、`bedrock:InvokeModel*`、`bedrock:Retrieve`、`bedrock:RetrieveAndGenerate`、`bedrock:StartIngestionJob`、`execute-api:Invoke` | `request` |
| `sns:Publish`、`sqs:SendMessage`、`events:PutEvents`、`kinesis:PutRecord*`、`firehose:PutRecord*` | `event` |
| `dynamodb:*`（読み書き・ストリームの読み取り）、`s3:GetObject`・`s3:PutObject`・`s3:ListBucket` など、`rds-data:*`、`aoss:APIAccessAll`、`sqs:ReceiveMessage` | `data` |
| それ以外 | 辺を作らない（v0.1） |

**参照先にノードが無いときの参照**（`E-REF-NONODE`。E-ENV-REF・E-KB-STORAGE などの直接の参照に適用）

| 規則ID | 参照先 | 扱い |
|---|---|---|
| `E-REF-NONODE` | R-* で辺に変換された関係リソース（例: rag の `DATA_SOURCE_ID = aws_bedrockagent_data_source.docs.data_source_id`）、または H-* で非表示のリソース（ロググループ、IAM など） | 辺を作らない。根拠（`sources.*.edges[].evidence`）には、同じ計算リソースから出るほかの辺があればそこに「辺にしなかった参照」として書く。M-* で統合されたリソースへの参照は、**統合先のノードへの参照** として扱う（例: タスク定義 → サービス、DB サブネットグループ → DB） |

**参照でも辺にしないもの**（入れ子・統合・権限のための参照）: `vpc_id`、`subnet_id(s)`、`security_group_ids`（R-SG で別に扱う）、`role`／`execution_role_arn`（E-IAM で別に扱う）、ロググループ、`cluster`、`task_definition`、`db_subnet_group_name`、`allocation_id`、`depends_on`／`DependsOn`。

## 3. 合成ノード

| 規則ID | いつ作るか | ノード | 辺 |
|---|---|---|---|
| `N-EXT-INTERNET` | (a) インターネット向けの LB（`internal = false`／`Scheme: internet-facing`）で、SG が `0.0.0.0/0` からの ingress を許す、(b) パブリックな API Gateway（REST の `REGIONAL`／`EDGE`、HTTP API） | `external/internet`（label `Internet`、`parent: null`、`synthetic: true`）。構成ごとに1つ | internet → LB（`request`、リスナーの `<PROTOCOL> <port>`）、internet → API（`request`、`HTTPS`）。`derived` |
| `N-BEDROCK-MODEL` | 基盤モデルの ARN（`arn:aws:bedrock:<region>::foundation-model/<model id>`）が、KB の埋め込み設定、IAM の `Resource`、環境変数のどれかに現れる | `bedrock_model/<model id の key>`（label はモデルID、`parent: null`、`synthetic: true`） | E-BEDROCK-EMBEDDING、E-IAM、E-ENV-STR で作る |

- インターネットゲートウェイと `external/internet` は結ばない（ルートの辺がサブネット → IGW で止まる）。経路の終点が IGW であることで外に出られることを表す。

## 4. まとめ方（E-MERGE）

1. 確信度は `confirmed` > `derived` > `inferred` で強い方。
2. `kind` は優先順の高い規則のもの。優先順: R-LB-*・R-APIGW-*・R-ROUTE・R-VPCE-GATEWAY > R-LAMBDA-ESM・R-SNS-SUBSCRIPTION・R-S3-NOTIFICATION・R-BEDROCK-DATA-SOURCE > E-ENV-REF・E-KB-STORAGE・E-BEDROCK-EMBEDDING > E-ENV-STR > R-SG > E-IAM。
   - 例: ECS サービス → RDS は、E-ENV-REF（`data`）と R-SG（`network`）から `data`。
3. `label` は優先順の高い規則から順に見て、最初の空でないもの。ただし **同じ規則から同じ組に複数のラベルが出たとき**（同じサブネットから同じ宛先へのルートが複数ある、SG のルールが複数のポートを許す、API のルートが複数ある）は、重複を除いて辞書順に `, ` でつなぐ（例: `0.0.0.0/0, 10.20.0.0/16`、`TCP 443, TCP 80`、`GET /orders, POST /orders`）。
   - 例: 同じ ECS サービス → RDS は、E-ENV-REF にラベルが無いので R-SG の `TCP 5432`。
4. 根拠（`sources.*.edges[]`）には、まとめた規則と根拠をすべて並べる。

## 5. ラベル

| 種類 | 書式 | 例 |
|---|---|---|
| LB のリスナー・ターゲットグループ | `<PROTOCOL> <port>` | `HTTP 80`、`HTTP 8080` |
| SG | `TCP <port>`／`TCP <from>-<to>`／`UDP …`／`ALL` | `TCP 5432` |
| ルート | 宛先 CIDR、または `<サービス> prefix list` | `0.0.0.0/0`、`s3 prefix list` |
| API Gateway | ルートキー（HTTP API）／`<METHOD> <path>`（REST）を辞書順に `, ` でつなぐ | `GET /orders, POST /orders` |
| internet → API | `HTTPS` | |
| それ以外 | 空文字 | |

## 6. 判断の理由

- **環境変数の参照は確定、IAM は推定。** 環境変数に参照先を渡すのは「そこに接続する」ためなので、通信の向きと一致する。IAM は「してもよい」だけで、実際に通信するとは限らない。
- **E-IAM-SUPPRESS を入れる理由。** ESM や S3 通知のように、受け手が読みに行く（ポーリングする、取得する）関係では、IAM の向き（受け手 → 送り手）とデータの向き（送り手 → 受け手）が逆になる。両方を描くと、同じ組に逆向きの矢印が2本出る。
- **KB → 埋め込みモデルを derived にする理由。** モデルはリソースではなく文字列の ARN だが、`embedding_model_arn` という属性の意味は型の定義で決まっていて、推測ではない。逆に、Lambda の環境変数 `MODEL_ARN` は名前から意味を推測しているだけなので inferred にする。
