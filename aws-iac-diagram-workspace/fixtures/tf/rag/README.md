# rag（S3 + Bedrock Knowledge Base + OpenSearch Serverless + Lambda + API Gateway）

- CFN 版: [../../cfn/rag/](../../cfn/rag/README.md)（YAML）
- 正解 IR: [expected/rag.ir.json](../../../expected/rag.ir.json)
- `src/` は Lambda のコード（図には関係しない）

## 構成

- 取り込み: S3 `rag-docs`（`docs/` 配下）→ Bedrock ナレッジベース `rag-kb`（データソース）。ベクトルストアは OpenSearch Serverless のコレクション `rag-kb`（インデックスは opensearch プロバイダで作る）。埋め込みは Titan Embeddings v2。
- 自動取り込み: S3 への追加 → `rag-ingest`（S3 通知）→ `StartIngestionJob`。
- 問い合わせ: REST API `rag-api`（`POST /query`）→ `rag-query` → `RetrieveAndGenerate`（生成モデルは Claude 3 Haiku）。

## 何を試すための構成か

| 観点 | 入力の要素 | 期待される扱い |
|---|---|---|
| A1 | `aws_bedrockagent_data_source`、`aws_s3_bucket_notification`、`aws_lambda_permission` ×2、REST の `resource`・`method`・`integration` | S3 → KB、S3 → ingest、API → query の辺に変換 |
| A2 | データソースは KB とバケットを参照し、KB のロールは S3 を読む（KB → S3） | 辺は **S3 → KB**（取り込みの流れ）。IAM の逆向きは作らない（E-IAM-SUPPRESS） |
| A3 の3段階 | KB → コレクション（`storage_configuration` の参照）、KB → 埋め込みモデル（`embedding_model_arn` の文字列）、query → 生成モデル（IAM の ARN と環境変数の文字列だけ） | それぞれ `confirmed`、`derived`、`inferred` |
| 合成ノード | 基盤モデルの ARN（リソースではない） | `bedrock_model/amazon.titan-embed-text-v2-0`、`bedrock_model/anthropic.claude-3-haiku-20240307-v1-0`（N-BEDROCK-MODEL） |
| AWS 以外のプロバイダ | `opensearch_index`（opensearch-project/opensearch）、`time_sleep`（hashicorp/time）、`archive_file` | コレクションに統合（M-AOSS-INDEX）、H-UTILITY、H-DATA |
| 名前で結ぶ統合 | OpenSearch Serverless のセキュリティポリシー2つとアクセスポリシー（`collection/rag-kb` という名前で指す） | コレクションに統合（M-AOSS-POLICY） |
| S3 の設定リソース | versioning、public access block、SSE | バケットに統合（M-S3-CONFIG） |
| REST API | デプロイとステージ | API に統合（M-APIGW-STAGE） |

## 判断に迷ったところ

- **基盤モデルをノードにする。** RAG の図ではモデルが主役の1つで、描かないと「何で埋め込み・生成しているか」が分からない。ただしリソースではないので合成ノード（`synthetic: true`）とし、ID はモデルID から作る（ARN は使わない）。
- **KB → 埋め込みモデルは derived、query → 生成モデルは inferred。** 前者は型の定義で意味が決まった属性、後者は環境変数の名前と IAM からの推測。
- **データソースはノードにしない。** KB とバケットを結ぶだけの関係リソースとして扱う。取り込みの設定（チャンク分割など）は将来 `attrs` か辺のラベルに出す。
- **KB とコレクションが同じ名前 `rag-kb`。** 型が違うので ID は重ならない。
