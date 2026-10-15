# rag（CloudFormation 版）

構成・試すこと・判断の理由は [TF 版の README](../../tf/rag/README.md)。正解 IR は [expected/rag.ir.json](../../../expected/rag.ir.json)。

CFN 版で追加で試すこと:

| 入力の要素 | 期待される扱い |
|---|---|
| `AWS::S3::Bucket.NotificationConfiguration`（プロパティ。TF は別リソース） | S3 → ingest の辺（R-S3-NOTIFICATION）。網羅分類には出ず、辺の根拠にだけ出る |
| `AWS::ApiGateway::Method` の中の `Integration`（TF は別リソース） | メソッドを API → query の辺に統合 |
| `AWS::OpenSearchServerless::Index`（TF は opensearch プロバイダ） | コレクションに統合（M-AOSS-INDEX） |
| 循環を避けるため ARN を文字列で組み立てる（`IngestS3Permission.SourceArn`、KB ロールの S3・コレクションのリソース） | 参照ではないが、関係リソースの辺（S3 → ingest）は通知から決まる。ワイルドカード（`collection/*`、`knowledge-base/*`）の IAM は v0.1 では照合しない |
| インラインの Lambda コード（`Code.ZipFile`） | IR には影響しない |

TF 版との違い:
- ingest 関数はデータソース ID を環境変数で受け取らない（Bucket → 関数 → データソース → Bucket の循環を避けるため）。KB は参照しているので、辺は TF 版と同じ。
- 網羅分類は TF 41 件、CFN 22 件。canonical 部は同じ。
- SG を使わない構成なので、SG の egress の書き方の差は無い。
- S3 バケット名 `rag-docs` は全世界で一意なので、デプロイするなら接尾辞を足す（fixtures/README.md の「共通の約束」）。
