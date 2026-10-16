# テスト用構成（fixtures）

| ディレクトリ | 内容 |
|---|---|
| `public/` | 公開サンプル（T01〜T20、P01〜P04、C01〜C05）。出典は [public/SOURCES.md](public/SOURCES.md)、C3 で使うものの選定は [public/SELECTION.md](public/SELECTION.md) |
| `tf/<名前>/`、`cfn/<名前>/` | 自作の構成5種。同じ構成の Terraform 版と CloudFormation 版 |

正解 IR は `../expected/<名前>.ir.json`（TF 版・CFN 版で共通の1ファイル。形式ごとの違いは `sources.tf`／`sources.cfn` に書く）。IR の形は [references/ir-schema.md](../../skills/aws-iac-diagram/references/ir-schema.md)。

## 自作の構成5種

| 名前 | 構成 | TF | CFN の形式 | ノード | 辺 | 網羅分類（TF／CFN） | 主に試すこと |
|---|---|---|---|---|---|---|---|
| [three-tier](tf/three-tier/README.md) | ALB → ECS Fargate → RDS | 31 resource、2 data | YAML（Parameters・Mappings・Conditions） | 15 | 7 | 39／38 | A1（リスナー・TG・ルート・SG）、A2（サービス → TG の逆向き）、A4（dev／prod の tfvars、`Condition`）、count、H-COND-FALSE |
| [serverless-api](tf/serverless-api/README.md) | HTTP API → Lambda → DynamoDB、ストリーム → Lambda → SNS → SQS、S3 | 23 resource、6 data | **SAM**（Events、ポリシーテンプレート） | 8 | 7 | 30／11 | A1（ESM・統合・サブスクリプション）、A2（ESM の向き）、A3（推定の辺: IAM の ARN 文字列）、for_each |
| [vpc-endpoints](tf/vpc-endpoints/README.md) | VPC、AZ ごとの NAT、S3 Gateway・SSM Interface エンドポイント、EC2 | 24 resource、4 data | **JSON**（`parameters.json`） | 15 | 9 | 38／33 | ルートの辺、Gateway 型エンドポイント、SG の1ルール → 3本の辺、for_each、terraform.tfvars |
| [three-tier-modules](tf/three-tier-modules/README.md) | three-tier をモジュールで書いたもの | 9 resource、1 data、module 4（公開3、ローカル1） | YAML の**ネストスタック**5本 | 15 | 7 | 42／41 | A5（公開モジュールの要約表）、ローカルモジュールの再帰、モジュール境界をまたぐ参照、ネストスタック。canonical 部は three-tier と同じ |
| [rag](tf/rag/README.md) | S3 → Bedrock KB（OpenSearch Serverless）、REST API → Lambda、S3 → Lambda → 取り込み | 33 resource、8 data | YAML | 9 | 9 | 41／22 | A1（データソース・S3 通知・REST の統合）、合成ノード（基盤モデル）、AWS 以外のプロバイダの型、A3 の3段階すべて |

ノード数と辺数は正解 IR の canonical 部（合成ノードを含む）。網羅分類の件数は、count／for_each を展開したインスタンス単位。

## 共通の約束

- リージョンは `ap-northeast-1`、AZ は `ap-northeast-1a` と `ap-northeast-1c` を変数・パラメータで明示している（CFN の `!GetAZs` は静的に AZ 名が決まらないので使っていない。ir-schema.md の未決事項）。
- 描くリソースにはすべて名前（`Name` タグか名前属性）を付けている。ノード ID は名前から作る（K-NAME）ので、TF 版と CFN 版で名前が同じなら ID も同じになる。
- **デプロイはしない前提。** S3 バケット名（`shop-orders-archive`、`rag-docs`）は全世界で一意なので、そのままでは取れない可能性が高い。実際にデプロイするときは、名前に変数で接尾辞（アカウントID など）を足すこと。ただし名前を変えるとノード ID も変わる（K-NAME）ので、正解 IR とは別に評価する。
- デプロイはしない。構文と型・属性の正しさは次で確かめた。terraform は入れていない（`terraform validate` はしていない）。
  - CFN: `cfn-lint`（1.57.2、`pyproject.toml`）で全テンプレートがエラー・警告 0。ネストスタックの `TemplateURL` はローカルパス（`aws cloudformation package` 前提）で、その警告 W3002 だけはテンプレート内で無効にしている。
  - TF: 全 `.tf`／`.tfvars` を python-hcl2 で読めること。

## 検証のしかた

```powershell
# 正解 IR がスキーマと参照の整合・出力の形（C5）に合うか。three-tier と three-tier-modules の canonical 部が同じか
uv run python skills\aws-iac-diagram\scripts\validate_ir.py aws-iac-diagram-workspace\expected\*.ir.json `
  --same-canonical aws-iac-diagram-workspace\expected\three-tier.ir.json aws-iac-diagram-workspace\expected\three-tier-modules.ir.json
# 入力の全ブロックが網羅分類にあり、網羅分類に入力に無いものが無いか。count／for_each は単純な式
# （length(var.X)、toset(var.X)、var.X）だけ評価してインスタンス数も照合する（locals・条件式・モジュールの中は (注) と表示して照合しない）。
# --lint で cfn-lint と python-hcl2 も
uv run python aws-iac-diagram-workspace\tools\check_coverage.py --lint
```

`tools/iac_inventory.py` は入力リソースを列挙するだけの小さなライブラリで、本番のアダプタではない（評価できるのは上の単純な count／for_each の式と変数の値だけ）。

## 自作の構成ではまだ試していないこと

- 値が決まらない count／for_each（×N）、`!GetAZs`、CFN の `Fn::ForEach`（LanguageExtensions）
- 型が表に無いリソース（`unknown`）。C4 の変異テストで、架空の型を足して確かめる予定
- 既存のインフラを指す `data`（`data.aws_vpc` など）、CloudFront、EventBridge、Step Functions、EKS
- terraform の plan JSON 入力、cdk.out
