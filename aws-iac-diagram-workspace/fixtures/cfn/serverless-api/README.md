# serverless-api（SAM 版）

構成・試すこと・判断の理由は [TF 版の README](../../tf/serverless-api/README.md)。正解 IR は [expected/serverless-api.ir.json](../../../expected/serverless-api.ir.json)。

SAM 版で追加で試すこと:

| 入力の要素 | 期待される扱い |
|---|---|
| `Transform: AWS::Serverless-2016-10-31`、`AWS::Serverless::Function`、`AWS::Serverless::HttpApi` | 変換前のテンプレートを読む。`Serverless::Function` は `lambda_function`、`Serverless::HttpApi` は `apigw_http_api` |
| `Events`（`Type: HttpApi` ×2、`Type: DynamoDB`） | プロパティなので網羅分類には出ない。API → 関数、テーブル → 関数の辺の根拠になる（R-APIGW-HTTP、R-LAMBDA-ESM） |
| ポリシーテンプレート（`DynamoDBCrudPolicy`、`SNSPublishMessagePolicy`）と、ARN を文字列で書いた `Statement` | E-IAM の材料。S3 は文字列だけなので inferred |
| `Globals` | 関数の既定値。IR には影響しない |
| SAM が暗黙に作るリソース（ロール、権限、ステージ、ESM） | テンプレートに無いので網羅分類の対象外 |

TF 版との違い: 網羅分類は TF 30 件、SAM 11 件（IAM・統合・ルート・権限・ESM が SAM では Events やポリシーテンプレートになる）。canonical 部は同じ。SG を使わない構成なので、SG の egress の書き方の差（three-tier の README）は無い。

S3 バケット名 `shop-orders-archive` は全世界で一意なので、デプロイするなら接尾辞を足す（fixtures/README.md の「共通の約束」）。
