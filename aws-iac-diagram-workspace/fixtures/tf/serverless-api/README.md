# serverless-api（HTTP API → Lambda → DynamoDB → ストリーム → Lambda → SNS → SQS）

- CFN 版: [../../cfn/serverless-api/](../../cfn/serverless-api/README.md)（**SAM**）
- 正解 IR: [expected/serverless-api.ir.json](../../../expected/serverless-api.ir.json)
- `src/` は Lambda のコード（図には関係しない。`archive_file` の入力として置いてある）

## 構成

HTTP API（`GET /orders`、`POST /orders`）→ `shop-api-handler` → DynamoDB `shop-orders`。テーブルのストリーム → `shop-stream-processor` → SNS `shop-order-events` → SQS `shop-order-events`。ストリーム処理の関数は S3 `shop-orders-archive` にも書く（ただし設定上はバケットを参照していない）。

## 何を試すための構成か

| 観点 | 入力の要素 | 期待される扱い |
|---|---|---|
| A1 | `aws_apigatewayv2_integration`、`aws_apigatewayv2_route`（for_each で2つ）、`aws_lambda_permission`、`aws_lambda_event_source_mapping`、`aws_sns_topic_subscription`、`aws_sqs_queue_policy` | すべて辺に変換。API → 関数は1本で、ラベルにルートキーを並べる（`GET /orders, POST /orders`） |
| A2 | ESM は テーブル（のストリーム）と 関数 の両方を参照する | 辺は **テーブル → 関数**（データの流れ） |
| A2（逆向きの IAM） | ストリーム処理の関数の IAM がテーブルのストリームを読む（関数 → テーブル） | ESM の辺と逆向きなので作らない（E-IAM-SUPPRESS） |
| A3 confirmed | 環境変数 `TABLE_NAME = aws_dynamodb_table.orders.name`、`TOPIC_ARN = aws_sns_topic.order_events.arn` | 関数 → テーブル、関数 → トピックは `confirmed`。同じ向きの IAM は根拠に加わるだけ |
| A3 inferred | IAM の `Resource = "arn:aws:s3:::${local.archive_bucket}/*"`（文字列）と環境変数 `ARCHIVE_BUCKET = local.archive_bucket`（文字列） | 関数 → バケットは `inferred`（E-IAM、E-ENV-STR）。破線で描き、説明 .md の推定一覧に載る |
| for_each | `aws_apigatewayv2_route.this`（`var.routes` のマップ） | `this["get_orders"]`、`this["post_orders"]` の2件 |
| 合成ノード | パブリックな HTTP API | `external/internet` → API（`HTTPS`） |
| 統合・非表示 | ステージ、S3 のパブリックアクセスブロック、ロググループ、IAM、`archive_file` | M-APIGW-STAGE、M-S3-CONFIG、H-LOGS、H-IAM、H-DATA |

## 判断に迷ったところ

- **SQS の先は描かない。** キューの消費者はこの構成に無い。消費者が別スタックにある、という前提のまま、キューで辺が終わる。
- **SNS と SQS が同じ名前。** `sns_topic/shop-order-events` と `sqs_queue/shop-order-events` は型が違うので ID は重ならない（ID は `<型>/<名前>`）。
- **環境変数の文字列一致と IAM の文字列一致を両方 inferred にする。** どちらも参照ではないので、強めない。両方あっても inferred のまま（確信度は最も強い根拠で決まり、根拠の数では上がらない）。
