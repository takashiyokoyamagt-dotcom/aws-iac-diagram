# 公開サンプルの選定（C3: 実在の構成での試験）

- 作成日: 2026-10-15
- 対象: このフォルダの T01〜T20、P01〜P04、C01〜C05（出典は [SOURCES.md](SOURCES.md)）
- 数の出し方: `aws-iac-diagram-workspace/tools/survey_public.py`（`--json` で全項目）。式を評価しないので **ブロック単位**（count／for_each で増える分は数えない）。ローカルモジュールの中は再帰的に数え、レジストリ／git のモジュールは呼び出しの数だけ数える
- 公開サンプルの正解 IR はまだ作らない（評価のしかたの提案は最後の節）

## 1. 各サンプルの特徴

列: res = resource ブロック、data = data ブロック、mod L／R = ローカル／レジストリ（git を含む）のモジュール呼び出し、型 = resource の型の種類数。

### Terraform

| ID | 構成 | ルート | res | data | mod L／R | 型 | count | for_each | dynamic | tfvars | レジストリモジュール（A5 の対象は **太字**） | 目立つ点 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| T01 | EventBridge → SQS | 1 | 4 | 1 | 0／0 | 4 | 0 | 0 | 0 | 0 | | SAM 版あり（3リソース） |
| T02 | TGW＋VPC×2 | 1 | 1 | 0 | 0／2 | 1 | 2 | 0 | 0 | 1 | **vpc**、transit-gateway | **module に count**（VPC が2つに展開）。中身はほぼ全部モジュール |
| T03 | VPC module＋RDS | 1 | 4 | 1 | 0／1 | 4 | 0 | 0 | 0 | 0 | **vpc** | 3層の DB 部分。小さく A5 の vpc を試せる |
| T04 | 静的サイト（S3、CloudFront、R53、ACM） | 1 | 14 | 3 | 1／0 | 10 | 4 | 1 | 0 | 0 | | ルートは examples/custom-error-response-and-bucket、本体は `../../` のローカルモジュール |
| T05 | Lambda → SQS | 1 | 6 | 3 | 0／0 | 5 | 0 | 0 | 0 | 0 | | SAM 版あり（2リソース） |
| T06 | EventBridge → SNS → Lambda | 1 | — | — | — | — | — | — | — | — | | **python-hcl2 8.1.4 で読めない**（下の「見つかった問題」1）。SAM 版あり（4リソース） |
| T07 | HTTP API → Lambda → DynamoDB | 1 | 16 | 1 | 0／0 | 15 | 0 | 0 | 0 | 0 | | SAM 版あり（2リソース）。`random_string` |
| T08 | DynamoDB → Glue → S3 | 1 | 10 | 1 | 0／0 | 10 | 0 | 0 | 0 | 0 | | Glue zero-ETL |
| T09 | RAG（Bedrock KB、OpenSearch Serverless） | 1 | 12 | 5 | 1／0 | 9 | 0 | 0 | 4 | 0 | | `opensearch_index`・`time_sleep`（AWS 以外）、**既存バケットを `data.aws_s3_bucket` で参照**、`dynamic` が4 |
| T10 | VPC＋ALB＋ASG | 1 | 8 | 2 | 0／1 | 7 | 0 | 0 | 0 | 0 | **vpc**（2.77.0） | **旧構文**（aws ~> 3.38、`aws_launch_configuration`、vpc モジュール v2） |
| T11 | REST API → Step Functions → DynamoDB | 1 | 27 | 2 | 0／0 | 14 | 0 | 0 | 0 | 0 | | SAM 版あり（6リソース、OpenAPI 定義）。REST の method／integration が多い |
| T12 | Glue Data Quality | 1 | 22 | 7 | 3／0 | 15 | 9 | 0 | 0 | 1 | | ローカルモジュール3、`terraform.tfvars` |
| T13 | TGW hub-and-spoke、VPCE、R53 Resolver | 1 | 18 | 6 | 2／2 | 14 | 1 | 10 | 8 | 0 | aws-ia/vpc、aws-ia/network-hubandspoke | A5 の対象外のモジュールが中心。`dynamic` が8 |
| T14 | CloudFront 上級（Lambda@Edge、VPC オリジン） | 1 | 14 | 8 | 1／7 | 13 | 6 | 6 | 0 | 0 | **vpc**、acm、ec2-instance、lambda、route53、s3-bucket | 本体は `../../`（モジュールのソースそのもの）。`null_resource` |
| T15 | Bedrock Agent＋KB | 1 | 79 | 10 | 1／1 | 34 | 79 | 0 | 0 | 0 | aws-ia/opensearch-serverless | 本体は `../..`。**awscc プロバイダの型が多数**（`awscc_bedrock_*` など21種）。ほぼ全リソースが count で条件分岐 |
| T16 | EKS＋VPC＋IRSA | 1 | 1 | 2 | 0／3 | 1 | 0 | 0 | 0 | 0 | **eks**、**vpc**、iam（サブモジュール） | 中身はほぼ全部 A5 のモジュール |
| T17 | ECS Fargate フルスタック＋CI/CD | 1 | 121 | 12 | 34／0 | 31 | 80 | 0 | 1 | 0 | | **ローカルモジュール呼び出し 34**。ALB×2、CodePipeline、CodeDeploy |
| T18 | EKS blue/green | 3 | 13 | 22 | 2／18 | 8 | 0 | 10 | 0 | 0 | **eks**、**vpc**、acm、iam、eks-blueprints-addons／teams、**`git::` ソース** | ルートが3つ。`kubernetes_*` の型 |
| T19 | ネットワークハブ（TGW、NFW、IPAM、集約 VPCE） | 1 | 106 | 5 | 5／0 | 45 | 0 | 39 | 4 | 1 | | for_each が39、`config.auto.tfvars` |
| T20 | CDC レイクハウス（MSK、DMS、Firehose、Glue、Athena、LF） | 26 | 566 | 413 | 65／0 | 70 | 122 | 4 | 16 | 26 | | 独立ルート26（remote state で結ぶ）、ルートごとに tfvars |
| P01 | terraform-aws-vpc（examples/simple、complete） | 2 | 325* | 27 | 7／1 | 35 | 311 | 14 | 0 | 0 | security-group | *`../../` でモジュール本体を数えているので、実際に作られる数ではない |
| P02 | terraform-aws-ecs（examples/fargate） | 1 | 75* | 35 | 5／2 | 19 | 57 | 19 | 0 | 0 | **alb**、**vpc** | 同上（本体のサブモジュールを数えている） |
| P03 | terraform-aws-eks（examples/eks-managed-node-group） | 1 | 0 | 1 | 0／3 | 0 | 0 | 0 | 0 | 0 | **eks**、**vpc** | example は本体を `../..` ではなくレジストリで呼ぶ（手元の本体は読まれない） |
| P04 | terraform-aws-rds-aurora（examples/postgresql） | 1 | 18* | 4 | 1／2 | 18 | 12 | 6 | 0 | 0 | **vpc**、kms | 同上 |

### CloudFormation

| ID | 構成 | テンプレート | リソース | 型 | ネストスタック | Condition 付き | Parameters | Conditions | Mappings | Transform | 目立つ点 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C01 | 静的サイト（CloudFront、ACM、カスタムリソース） | main.yaml＋子3 | 16 | 12 | 3（ローカルパス、展開できる） | 1 | 4 | 0 | 1 | | カスタムリソース（Lambda バックエンド） |
| C02 | WebApp（CloudFront、WAF、Cognito、API GW、Lambda、DynamoDB） | 1 | 42 | 19 | 0 | 0 | 3 | 0 | 0 | | 単一テンプレートで中規模。C1（cfn-lint のグラフ）の突き合わせに向く |
| C03 | VPC、マネージド NAT、プライベートサブネット | 1 | 26 | 12 | 0 | 0 | 1 | 0 | 1 | | 自作の vpc-endpoints に近い |
| C04 | VPC Peering（クロスアカウント） | 3 | 16 | 3 | 4 | 10 | 35 | 10 | 0 | | Conditions が多い。ネストスタックの `TemplateURL` は `!Sub` で組み立てた S3 の URL（パラメータでバケット名を受け取る） |
| C05 | VPC、ALB、ECS（ネストスタック） | master.yaml＋子7 | 7（親のみ） | 1 | 7（**S3 の URL**） | 0 | 0 | 0 | 0 | | 子テンプレートは手元にあるが、`TemplateURL` が `https://s3.amazonaws.com/ecs-refarch-cloudformation/...` なので、そのままでは展開できない（子は合計約55リソース） |
| T01s／T05s／T06s／T07s／T11s | serverless-patterns の SAM 版 | 各1 | 3／2／4／2／6 | | 0 | 0 | 0 | 0 | 0 | SAM | TF 版と同じ構成の SAM。TF と CFN の一致（フェーズ2）を実在のコードで確かめられる唯一の組 |

## 2. 選定

### 2.1 主セット（正解 IR を作り、再現率・適合率を測る）

| ID | 選ぶ理由 |
|---|---|
| **T07＋T07s** | API GW → Lambda → DynamoDB を TF と SAM の両方で。自作の serverless-api と同じ種類の実在コード。TF／CFN の対の比較 |
| **T06＋T06s** | EventBridge → SNS → Lambda の対。EventBridge の target（A1）。hcl2 の問題（下の1）の回帰試験 |
| **T11＋T11s** | REST API → Step Functions → DynamoDB の対（L3）。REST の関係リソースが多く、SAM 側は OpenAPI 定義（`DefinitionBody` の `AWS::Include`）と ASL（`DefinitionUri`）を外部ファイルで読む |
| **T03** | 3層の DB 部分を A5 の vpc モジュールで。小さいので正解 IR を独立に書きやすい |
| **T09** | RAG。自作の rag と同じ種類で、既存バケットの `data` 参照・`dynamic`・AWS 以外の型がある |
| **T12** | データ系。ローカルモジュール3と tfvars、count が多い |
| **T16** | EKS。中身がほぼ A5 のモジュール（eks・vpc）なので、要約表の出来がそのまま出る |
| **T17** | L4。ローカルモジュール 34 の再帰、ALB×2、CI/CD。大規模の網羅（A6）と分割（B2）の試験 |
| **T19** | L4 のネットワーク。for_each 39、`dynamic`、TGW・NFW・IPAM、`config.auto.tfvars` |
| **C01** | ローカルパスのネストスタック、カスタムリソース、CloudFront |
| **C02** | 単一テンプレートの中規模（42）。C1（cfn-lint のグラフ）との突き合わせの基準にする |
| **C05** | S3 URL のネストスタック（手元の子テンプレートへの読み替えが要る）。ECS の3層で自作の three-tier と比べられる |

合計 12 件（対は1件と数える）。5種類の構成（3層・サーバーレス・ネットワーク・モジュール・RAG）、L1〜L4、TF／SAM／CFN／ネストスタックをすべて含む。

### 2.2 補助セット（正解 IR は作らず、自動の検査だけ）

| ID | 確かめること |
|---|---|
| T01＋T01s、T05＋T05s | 最小構成で落ちない・網羅が漏れない（煙試験） |
| T02 | module への count（VPC が2つに展開）。transit-gateway モジュールは A5 の対象外 → 未知のモジュールの扱い |
| T04 | ルートが example で、本体が `../../` のローカルモジュール。for_each |
| T08 | Glue zero-ETL（型の表の拡張が要る） |
| T10 | 旧構文（aws provider v3、`aws_launch_configuration`、vpc モジュール v2）。A5 の要約表が版で変わること |
| T13 | A5 の対象外のレジストリモジュール（aws-ia）が中心。ブラックボックスとしての描き方 |
| T14 | レジストリモジュール 7（うち A5 は vpc だけ）。Lambda@Edge |
| T15 | awscc プロバイダの型（`unknown` の件数が多く出るはず）。条件分岐の count 79 |
| T18 | `git::` ソース、ルート3つ、kubernetes プロバイダ |
| T20 | 規模の上限（26 ルート、566 resource、413 data）。実行時間、B2 の分割、remote state |
| C03 | VPC＋NAT の単一テンプレート（自作の vpc-endpoints と同じ種類） |
| C04 | Conditions が多いクロスアカウント構成、S3 URL のネストスタック |

### 2.3 C3 では使わないもの

- **P01〜P04**: モジュールのソースそのもので、examples は `../../` で本体を読む（P03 はレジストリ）。構成図の試験としては規模の数え方が実態と違う。**A5 の要約表を作るときの参照元**として使う（SOURCES.md の方針どおり）。P02（ECS fargate、alb＋vpc）は A5 ができた後に補助セットに加えてもよい。

## 3. 評価のしかた（提案）

1. **主セットの正解 IR は、ツールの出力を見る前に別のサブエージェントが書く**（C6 と同じ第三者の考え方）。ツールの出力を見てから直すと、ツールの誤りに引きずられる。書き方は自作の fixture と同じ（`references/ir-schema.md`、規則表に従う）。規則表で決まらない判断は IR の `note` に残し、規則表の改訂候補にする。
2. **大きいもの（T17、T19、C05）は全体の正解 IR を作らない。** 代わりに、
   - 適合率: ツールの出力からノード・辺を 30 件ずつ無作為に抜き、入力のコードで正しいかを確かめる。
   - 再現率: README の説明から「必ず描かれるべきもの」の点検表（主要なノード 10〜20 と主要な辺）を先に作り、出力に含まれるかを確かめる。
3. **TF／SAM の対（T06、T07、T11）は、作者が別なので名前が違う。** canonical 部のバイト一致ではなく、ノードの型の多重集合と、辺の (from の型, to の型, kind) の多重集合が一致するかで比べる。
4. **補助セットは自動の検査だけ**: 例外で止まらないこと、網羅分類の漏れが 0 で `unknown` の件数と型の一覧を出すこと、2回実行してバイト単位で同じ（C5）、`validate_ir.py` が通ること、実行時間。CFN は C1（cfn-lint のグラフとの差分）も。
5. 基準値（再現率・適合率をどこまで求めるか）は [evals/CRITERIA.md](../../evals/CRITERIA.md)（2026-10-16 確定）にある。以下はもとにした目安の案: 自作 fixture は N・E・P とも 1.0、主セットは N 0.95 以上・E 0.9 以上・確信度の一致 0.9 以上、`unknown` は主セットで 0。

## 4. 見つかった問題（フェーズ1〜2 への申し送り）

1. **T06 が python-hcl2 8.1.4 で読めない。** `policy = <<POLICY … POLICY␣␣`（終端の識別子の後ろに空白）で `UnexpectedToken`。terraform は受け付ける書き方なので、TF アダプタで heredoc の終端行の末尾の空白を取ってから読むなどの前処理が要る。
2. **C05 の `TemplateURL` が S3 の URL。** 手元の子テンプレートと同じパス（`infrastructure/vpc.yaml` など）なので、「URL のパスの末尾が手元のファイルと一致すれば読む」読み替えを CFN アダプタに入れるか、ユーザーに対応を確認する。C04 も同様。
3. **T14・T15・T04 のルートは example で、本体が `../../`。** ローカルモジュールのパスがルートの外に出る。網羅分類の `file` をどう書くか（ルートからの `../` 付きの相対パス）を決める。
4. **T15 の awscc、T18 の kubernetes、T09 の opensearch** など AWS 以外のプロバイダの型が出る。resource-catalog.md に「AWS 以外の型」の扱い（awscc は aws の同等の型に対応づける、kubernetes は描かない等）を足す。
5. **T20 は data が 413**（remote state、ロール・バケットの参照）。H-DATA で一括して非表示にすると、別ルートのリソースへの参照が全部消える。既存インフラを指す data を外部ノードにする規則（resource-catalog.md の H-DATA の補足）が必要。
