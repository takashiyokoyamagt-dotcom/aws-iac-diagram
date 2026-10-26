## 2. ノード

```json
{"id": "alb/demo-alb", "type": "alb", "category": "resource", "name": "demo-alb", "label": "demo-alb",
 "parent": "vpc/demo", "spans": ["subnet/demo-public-ap-northeast-1a", "subnet/demo-public-ap-northeast-1c"]}
```

| フィールド | 必須 | 内容 |
|---|---|---|
| `id` | ○ | `<type>/<key>`。下の「ID の作り方」 |
| `type` | ○ | 正規の型名（`resource-catalog.md`）。TF の `aws_lb`（application）も CFN の `AWS::ElasticLoadBalancingV2::LoadBalancer`（Type: application）も `alb` |
| `category` | ○ | `group`（枠: vpc・availability_zone・subnet）／`resource`／`external`（AWS の外: internet）。黒箱のモジュール（下の「黒箱のモジュール」）は `resource` |
| `name` | ○ | B3 の採用順（`Name` タグ → 型ごとの名前属性 → 論理名）で決めた **名前**。評価後の値で、省略や言い換えをしない。`id` の key はここから作る |
| `label` | ○ | **表示名**。いまは `name` と同じ（合成ノードを除く）。B3 の省略規則・日本語ラベルは `label` だけを変え、`name` と `id` は変えない |
| `parent` | ○ | 直接の親（group のノード）。リージョン直下は `null` |
| `spans` | | 複数のサブネットに置かれるリソースの、置き場所のサブネット（2つ以上）。このとき `parent` はそれらの最も近い共通の祖先（P-SPANS） |
| `synthetic` | | 入力に対応するリソースが無い、正規化で作ったノードは `true`（AZ、`external/internet`、`bedrock_model`） |
| `multiplicity` | | 値が決まらない count／for_each を1つにまとめたときだけ `"N"`（×N）。**値が決まる count／for_each はまとめず、インスタンスごとに別のノードにする**（例: `aws_subnet.public[0]` と `[1]` は2ノード）。省略は 1。下の「×N の出し方」 |
| `attrs` | | 表示・アイコン・枠の種類・重大な誤りの判定（CRITERIA の X1）に使う少数の値。**使えるキーは下の表のものだけ**（ほかのキーは validate_ir.py でエラー。足すときはこの表を直す） |
| `note` | | 判断理由（比較に使わない） |

**`attrs` のキー**

| キー | 付ける型 | 値 | 使い道 |
|---|---|---|---|
| `cidr` | `vpc`、`subnet` | CIDR の文字列（評価できなければ付けない） | 表示 |
| `access` | `subnet` | `public`（ルートテーブルにインターネットゲートウェイへの経路がある）／`private` | 枠のアイコン、CRITERIA の X1 |
| `endpoint_type` | `vpc_endpoint` | `Gateway`／`Interface` | アイコン、入れ子（P-VPC／P-SPANS） |
| `service` | `vpc_endpoint` | サービス名の末尾（`s3`、`ssm`、`ecr.api` など） | 表示 |
| `module_source` | `module` | モジュールの source（TF）か `TemplateURL`（CFN） | 表示 |
| `module_version` | `module` | モジュールの version（TF。無ければ付けない） | 表示 |

### 黒箱のモジュール（`module`）

中身を読まない・読めないまとまりは、1つのノード（型 `module`、category `resource`）として描く。中身を推測して描かない（CRITERIA の 2.3 の A5）。

- **対象:**
  - TF: レジストリモジュールのうち、A5 の要約表（[data/module-summaries/](../../../skills/aws-iac-diagram/data/module-summaries/)）に無いもの（aws-ia のモジュールなど）と、要約表はあるが版（major）が合わないもの（vpc の 5.x など）。`git::` などのリモートのソースも同じ。ローカルモジュールのうち、フォルダに `.tf` が無くて読めないもの・自分を呼ぶもの（循環）・入れ子が深すぎるもの（7.2）
  - CFN: ネストスタックのうち、子テンプレートを読めないもの（`TemplateURL` を手元のファイルに読み替えられない。7.4）。`AWS::Serverless::Application`（SAR）
- **対象から外すもの:** source が IAM だけを作るモジュール（`terraform-aws-modules/iam/aws` とその下のサブモジュール。一覧は `data/module-summaries/iam-only-sources.md`（説明は docs/spec/module-summaries.md の 4章）、判定は `scripts/aws_iac_diagram/adapters/terraform/modules/summaries.py` の `iam_only()`。source の前方一致）は、黒箱のノードにせず `hidden`（規則 `H-IAM`。IAM のリソースを描かないのと同じ）。raw IR では黒箱の呼び出しのまま出す（中身を読まないので、IAM だけかは source で決める）。中身を読むローカルモジュールには使わない（中のリソースが型ごとに `H-IAM` になる）
- **id と名前:** `name` はモジュール呼び出しの名前（TF: モジュールのパスを `.` でつないだもの。CFN: ネストスタックの論理ID を `.` でつないだもの）。id は `module/<key>`
- **入れ子:** モジュールの入力（TF の引数、CFN の `Parameters`）が、ほかのノードのサブネットを指していれば `spans`／`parent` を P-SUBNET・P-SPANS で、VPC だけを指していれば `parent` を VPC にする。どちらも無ければ `parent: null`
- **辺:** 中身が分からないので、確信度はどれも `inferred`（破線。CRITERIA の X2・X3 の対象にならない）。
  - モジュールの出力（TF の `module.x.<output>`、CFN の `!GetAtt Stack.Outputs.X`）への参照: 参照した側 → モジュールの辺。E-ENV-REF などの規則に当たるときだけ作り、kind は `request`（型が分からないため）。
  - モジュールの入力に渡したノード: モジュール → そのノードの辺。kind は参照先の型で決める（E-ENV-REF の表）。参照先が枠（category `group`）、SG、IAM、非表示・統合されたリソースなら作らない（入れ子や権限のための入力のため。入力の名前はモジュールごとに違うので、E-NOEDGE の属性名では判定しない）
- **網羅分類:** モジュール呼び出し1つを1件（address は TF が `module.<名前>`、CFN はネストスタックの論理ID で type は入力のまま（`AWS::CloudFormation::Stack`、`AWS::Serverless::Application`）。TF の type は `module`）、class `drawn`、`via: "module_blackbox"` で載せる。中身のリソースは載せない（読んでいないため）

### ×N の出し方

- count／for_each（CFN は `Fn::ForEach`）の値が決まらないブロックは、ノードを1つだけ作り、`multiplicity: "N"` を付ける。
- `name` はインデックスを付けない名前（B3 の順で決める。名前に `count.index` などが入って評価できないときは、その部分を除いた論理名）。
- 網羅分類は1件で、address はインデックスの代わりに `[*]` を付ける（`aws_subnet.private[*]`）。
- 辺と入れ子は、ほかのノードと同じ規則で作る（インスタンスごとの区別はしない）。
- ×N のノードの置き場所:
  - サブネットが1つに決まる → `parent` をそのサブネットにする（`spans` は付けない。`spans` は2つ以上のときだけ）
  - サブネットが2つ以上に決まる → P-SPANS のとおり
  - サブネットが決まらない（サブネットの側も ×N など）→ `parent` を共通の祖先（決まらなければ VPC）にして、`spans` を付けない
- ×N のサブネットは、AZ が決まらなければ AZ のノードを作らず、`parent` を VPC にする。
- CFN の `Fn::ForEach` で値が決まらないときの address は、論理ID のひな形の `${…}` を `*` にしたもの（`Bucket${Name}` → `Bucket*`）。

### ID の作り方（K-NAME）

- `key` = `name` を小文字にし、`[a-z0-9._-]` 以外の文字を `-` にしたもの（表示用の `label` からは作らない。省略や日本語化で ID が変わると C5 と採点が壊れるため）。`name` は B3 の順で決める:
  1. `Name` タグ（TF の `tags.Name`、CFN の `Tags` の `Key: Name`）
  2. 型ごとの名前属性（`function_name`／`FunctionName`、`bucket`／`BucketName`、`identifier`／`DBInstanceIdentifier`、`name`／`Name` など。`resource-catalog.md` の「名前属性」列）
  3. 論理名（TF: モジュールのパスを `.` でつないだもの＋リソース名、CFN: ネストスタックの論理ID を `.` でつないだもの＋論理ID）。インデックスは `-0` のように付ける
- 名前は A4 で評価した後の値を使う（`"${local.name}-alb"` → `demo-alb`）。評価できなければ 3 に落ちる。
- 同じ型で key が重なったら、重なったリソースを入力のアドレス（TF）／論理ID（CFN）の辞書順に並べ、2つ目以降の key の末尾に `.<論理名の key>`（論理名は上の 3 の形）を付ける。論理名は TF と CFN で違うので、**この場合は canonical 部が TF 版と CFN 版で一致しない**（フェーズ2 の比較では、重なりを解いたノードを対応表で突き合わせる）。自作の fixture には重なりは無い。
- **ARN や AWS が払い出す ID は使わない**（失敗知見17）。名前が決まらないリソースは論理名に落ちるので、TF 版と CFN 版で ID が一致するのは「名前が付いているもの」だけになる。fixture は描くリソースすべてに名前を付けてある。
- 合成ノード（`name` から key を作らない）: AZ は `availability_zone/<VPC の key>.<AZ 名>`（`name` は AZ 名）。**AZ 名が静的に決まらないとき**（CFN の `!Select [0, !GetAZs '']`、TF の `data.aws_availability_zones.x.names[0]`）は、選んだ位置の番号を1始まりで使い、`availability_zone/<VPC の key>.az1`（`name` は `az1`、`label` は `AZ 1`）にする。番号は `Select`／インデックスの値で、AZ 名の順ではない（raw の `$az` が `"*"`、つまりすべての AZ のときは、サブネットの AZ には使えないので AZ のノードを作らない）。一方の形式だけ AZ 名を書いているときは canonical 部が TF／CFN で一致しないので、fixture では両方とも同じ書き方にする。インターネットは `external/internet`（`name` は `internet`、`label` は `Internet`）、Bedrock の基盤モデルは `bedrock_model/<モデルID の key>`（`name` はモデルID。例 `bedrock_model/amazon.titan-embed-text-v2-0`）。
