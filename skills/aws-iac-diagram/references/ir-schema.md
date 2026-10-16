# IR スキーマ（v1.0）

- 状態: **v1.0 確定**（2026-10-17）。正規化後の形（1〜6章）はフェーズ1 の手順1 で、アダプタの出力（7章）は CFN アダプタの実装（手順2〜4）で確かめて手順5 で確定した。TF アダプタ（フェーズ2）で足りないものが見つかれば、7章に追記する。v0.1 草案（フェーズ0）からの変更点は 9章
- 機械可読な定義: 正規化後は [ir.schema.json](ir.schema.json)、アダプタの出力は [ir-raw.schema.json](ir-raw.schema.json)（どちらも JSON Schema 2020-12）
- 検証: `scripts/validate_ir.py`（スキーマ＋参照の整合＋出力形式）
- 関連する規則表: [resource-catalog.md](resource-catalog.md)（型ごとの扱い・入れ子）、[relation-resources.md](relation-resources.md)（A1）、[edge-rules.md](edge-rules.md)（A2・A3・SG・IAM・合成ノード・辺にしない参照）

IR には2つの段階がある。

| 段階（`stage`） | 作るもの | 内容 | 章 |
|---|---|---|---|
| `raw` | アダプタ（PLAN 3 の ①。CFN はフェーズ1、TF はフェーズ2） | 入力のリソースを、評価（A4）した後のプロパティと参照の一覧にしたもの。図の形にはまだしない | 7章 |
| `normalized` | 正規化（PLAN 3 の ②。フェーズ3） | 図に描く内容（ノード・辺・入れ子）と、網羅分類・辺の根拠 | 1〜6章 |

正解 IR（`aws-iac-diagram-workspace/expected/*.ir.json`）は `normalized` の形で書く。

## 1. 全体の構造

```json
{
  "ir_version": "1.0",
  "stage": "normalized",
  "name": "three-tier",
  "description": "…",
  "notes": ["判断の記録（比較には使わない）"],
  "evaluation": {"tf": {"var_files": ["env/dev.tfvars"], "vars": {}}, "cfn": {"parameters": {"EnvType": "dev"}}, "assumptions": []},
  "nodes": [ … ],
  "edges": [ … ],
  "sources": {"tf": { … }, "cfn": { … }}
}
```

| キー | 部 | 内容 |
|---|---|---|
| `nodes`, `edges` | **canonical 部** | 図に描く内容。入力の形式（TF／CFN）によらない。TF 版と CFN 版の比較はここだけで行う |
| `sources.tf`, `sources.cfn` | **由来部** | 入力の各リソースがどう扱われたか（網羅分類 A6）と、各辺の根拠。形式ごとに1つ |
| `evaluation` | 前提 | 変数・パラメータの評価（A4）に使った値。tfvars のどれを選んだか、など |
| `name`, `description`, `notes` | 説明 | `notes` は判断理由。比較には使わない |
| `diagnostics` | 記録 | 省略可。正規化で残した記録（「使わなかった参照」など。形は 7.5、code は `NORM-…`）。比較には使わない |

**同じ構成の TF 版と CFN 版は canonical 部が一致する**（フェーズ2 の完了基準）。由来部は形式ごとに違ってよい（例: TF には `aws_s3_bucket_versioning` のような設定だけのリソースがあり、CFN ではそれが `AWS::S3::Bucket` のプロパティになる。逆に CFN には `AWS::EC2::VPCGatewayAttachment` があり、TF では `aws_internet_gateway.vpc_id` で表す）。

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
  - TF: レジストリモジュールのうち、A5 の要約表に無いもの（aws-ia のモジュールなど）。`git::` などのリモートのソースも同じ
  - CFN: ネストスタックのうち、子テンプレートを読めないもの（`TemplateURL` を手元のファイルに読み替えられない。7.4）。`AWS::Serverless::Application`（SAR）
- **対象から外すもの:** source が IAM だけを作るモジュール（`terraform-aws-modules/iam/aws` とその下のサブモジュール）は、黒箱のノードにせず `hidden`（規則 `H-IAM`。IAM のリソースを描かないのと同じ）
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

## 3. 辺

```json
{"id": "alb/demo-alb->ecs_service/demo-app", "from": "alb/demo-alb", "to": "ecs_service/demo-app",
 "kind": "request", "label": "HTTP 8080", "confidence": "derived"}
```

| フィールド | 必須 | 内容 |
|---|---|---|
| `id` | ○ | `<from>-><to>` |
| `from`, `to` | ○ | ノードの id。**向きはデータ（要求）の流れ**で、参照の向きではない（A2） |
| `kind` | ○ | `request`（同期の呼び出し・HTTP）／`event`（非同期の通知・イベント・ストリーム・発行）／`data`（データストアの読み書き）／`route`（ルートテーブルによる経路）／`network`（SG で通信が許されているだけで、他の根拠が無いもの） |
| `label` | ○ | 空文字ならラベルなし。書式は `edge-rules.md` の「ラベル」 |
| `confidence` | ○ | `confirmed`（直接の参照）／`derived`（関係リソースの変換 A1、SG からの導出、型の定義から決まる値）／`inferred`（IAM の Resource ARN、文字列の一致）。A3 |
| `note` | | 判断理由 |

- 順序付きの組（from, to）ごとに辺は1本（E-MERGE）。根拠が複数あるときは、確信度は強い方、`kind` と `label` は規則の優先順で決める。
- 自己ループは作らない。
- 入れ子（parent）は辺にしない。

## 4. 由来部（sources）

```json
"sources": {
  "tf": {
    "root": "fixtures/tf/three-tier",
    "resources": [
      {"address": "aws_lb.app", "type": "aws_lb", "file": "alb.tf", "class": "drawn", "node": "alb/demo-alb"},
      {"address": "aws_lb_listener.http", "type": "aws_lb_listener", "file": "alb.tf", "class": "merged_into",
       "into": ["alb/demo-alb->ecs_service/demo-app", "external/internet->alb/demo-alb"], "rule": "R-LB-LISTENER"},
      {"address": "aws_iam_role.task_execution", "type": "aws_iam_role", "file": "ecs.tf", "class": "hidden", "rule": "H-IAM"}
    ],
    "edges": [
      {"edge": "alb/demo-alb->ecs_service/demo-app", "rules": ["R-LB-LISTENER", "R-LB-TG", "R-SG"],
       "evidence": ["aws_lb_listener.http.default_action.target_group_arn", "aws_ecs_service.app.load_balancer.target_group_arn"]}
    ]
  }
}
```

### 網羅分類（A6）

入力の **すべてのリソース**（TF は `resource` と `data`、CFN は `Resources` の全エントリ）が `resources` にちょうど1回ずつ現れる。

| `class` | 必須の項目 | 意味 |
|---|---|---|
| `drawn` | `node` | そのリソースがノードになった |
| `merged_into` | `into`、`rule` | ほかのノードに統合された（M-*）か、辺に変換された（R-*。このとき `into` は辺の id） |
| `hidden` | `rule` | 図に描かない（H-*）。count が 0・Condition が偽のものも `H-COND-FALSE` でここに入る |
| `unknown` | （なし） | 型が `resource-catalog.md` に無い。分類としては正しく、検証エラーにはしない（終了コードは 0 のまま）。件数と型を `result.json` と `coverage.md` に出す。検証エラー（終了コード 1）になるのは、分類の漏れと重複。主セットで 0 件にするのは評価の基準（[CRITERIA.md](../../../aws-iac-diagram-workspace/evals/CRITERIA.md) の 1.2） |

- `address`: TF は plan と同じ形のインスタンスアドレス（`aws_subnet.public[0]`、`module.vpc.aws_vpc.this[0]`、`data.aws_iam_policy_document.x`、for_each は `aws_vpc_endpoint.interface["ssm"]`）。count が 0 に評価されたブロックはインデックスなし（`aws_instance.bastion`）で1件。CFN は論理ID で、ネストスタックの中は `<親の論理ID>/<論理ID>`（`NetworkStack/Vpc`）。
- `type`: 入力のままの型（`aws_vpc`、`AWS::EC2::VPC`）。
- `file`: `root` からの相対パス。
- `via`（省略可）: 入力の読み方が通常と違うもの。
  - `module_summary`: レジストリモジュール（`terraform-aws-modules/vpc/aws` など）の中身で、ソースを読まずに A5 の要約表から展開したもの。`file` はモジュール呼び出しのあるファイル。要約表から展開するのは、その入力で作られる managed リソースだけ（モジュール内部の `data` と、count が 0 になるリソースは載せない）。
  - `module_blackbox`: 黒箱のモジュールの呼び出し（2章）。
- `file` がルートの外にあるとき（ローカルモジュールの source が `../../` など）は、ルートからの `../` 付きの相対パス（`/` 区切り、`..` 以外の `.` は除く）で書く。
- ノードを作る1つのリソースが、同時にほかのノードの配置を決めることがある（例: `aws_db_subnet_group` は統合されるが、DB の `spans` を決める）。分類は1つだけ書き、ほかの役割は `edges` の根拠や `note` に書く。

### 辺の根拠（edges）

canonical 部の **すべての辺** について、形式ごとに1件ずつ、使った規則（`rules`）と根拠（`evidence`。`アドレス.属性` の形の短い文字列）を書く。**正規化（ツール）が出す根拠は、`<raw の参照の from>.<raw の参照の path>` で始める**（後ろに ` (説明)` を付けてよい）。CRITERIA の 1.8 は、この前方一致で raw の参照と照合する。正解 IR の根拠は人が書いた短い形のままでよい（比較には使わない）。推定（inferred）の辺は、ここが説明 .md の「推定した辺の一覧」の元になる（A3）。

## 5. 評価の単位（再現率・適合率）

正解 IR（G）とツールの出力（O）を、次の集合ごとに比べる。再現率 = |G ∩ O| / |G|、適合率 = |G ∩ O| / |O|。

**比べる前に、ノードの id を対応づける。** O と G のノードを、網羅分類が `drawn` のリソースの address で突き合わせ、O の id を G の id に置き換えてから N・E・P を比べる（名前を1つ間違えただけで、そのノードの辺と入れ子まで外れるのを防ぐため）。

- 1つのノードに `drawn` の address が複数あるときは、どれか1つでも一致すれば対応づける。`merged_into`・`hidden` の address は使わない。
- address で対応づけられないノード（合成ノードなど）は、id のまま比べる。
- O の複数のノードが同じ G のノードに対応づくとき（1つのリソースを2つのノードに分けたときなど）は、O の id 順で最初の1つだけを対応づけ、残りは id のまま比べる（フェーズ1 の確定のときに見直す）。
- 名前の誤りは、別の指標「名前の一致率」（address で対応づけたノードの組のうち、O のもとの id と G の id が一致する組の割合）で数える。

| 単位 | 集合の要素 | 備考 |
|---|---|---|
| N（ノード） | `(id, type)` | |
| E（辺） | `(from, to, kind)` | 向きを区別する。逆向きは不一致。参考値として向きを無視した一致率も出す |
| P（入れ子） | `(id, parent)` と `(id, span)` の組 | `spans` の各要素を1組として数える |
| C（網羅） | 形式ごとの `(address, class, node／into／rule)` | 一致率（= 同じ分類になった割合）。`unknown` の件数は別に数える |
| 付随 | 辺の `confidence`、`label`、ノードの `label` | E で一致した辺・N で一致したノードの中での一致率 |
| 名前 | address で対応づけたノードの組 | 上の「名前の一致率」 |

- TF 版と CFN 版の一致（フェーズ2）: 両方の出力の canonical 部（`note` を除く `nodes` と `edges`）がバイト単位で一致すること。
- 基準値（どこまでを合格とするか）は [CRITERIA.md](../../../aws-iac-diagram-workspace/evals/CRITERIA.md)（2026-10-16 に確定）にある。

## 6. 出力の規則（C5）

- UTF-8、改行は LF、末尾に改行1つ。インデントは2スペース、キーは辞書順。
- 配列の順: `nodes` は `id` 順、`edges` は `id` 順、`sources.*.resources` は `address` 順、`sources.*.edges` は `edge` 順、`spans`・`into`・`rules`・`evidence` は文字列順。`notes` と `assumptions` は書いた順のまま。
- raw（7章）の配列の順: `resources` は `address` 順、`references` は `from`・`path`・`to`・`attr`・`fn` の順、`diagnostics` は `address`・`path`・`code` の順（address の無いものは先頭）。`assumptions` は書いた順のまま。
- `validate_ir.py --write` でこの形に整形できる（正規化後と raw の両方。`stage` で見分ける）。`validate_ir.py` は形がずれていればエラーにする。

## 7. アダプタの出力（`stage: "raw"`）

アダプタは、入力（CFN のテンプレート、cdk.out、TF の .tf／plan JSON）を読み、A4 の評価を済ませた後のリソースと参照の一覧を出す。**図の形（ノード・辺・入れ子・網羅分類）にはしない。** それは正規化（フェーズ3）の仕事で、規則表（resource-catalog.md・relation-resources.md・edge-rules.md）を使うのも正規化だけにする。ただし、A5 の要約表（読まないレジストリモジュールの中身を作る表）はアダプタが使う（中身のリソースを `resources` に載せるため）。CFN と TF で同じ形にし、正規化を1つにする。

この章の形は、CFN アダプタ（`scripts/adapters/cfn.py`。フェーズ1 の手順2〜4）の実装で確かめ、手順5 で確定した（2026-10-17）。CFN では、自作 fixture と公開サンプルの CFN（入力 25、cfn-lint の辺 513 本）で、cfn-lint のグラフの辺のすべてに参照が対応した（CRITERIA の 1.6）。TF アダプタ（フェーズ2）で足りないものが見つかれば追記する。

### 7.1 全体の構造

```json
{
  "ir_version": "1.0",
  "stage": "raw",
  "format": "cfn",
  "root": "fixtures/cfn/three-tier/template.yaml",
  "evaluation": {"parameters": {"EnvType": "dev"}, "conditions": {"IsProd": false}, "assumptions": ["…"]},
  "resources": [ … ],
  "references": [ … ],
  "diagnostics": [ … ]
}
```

| キー | 内容 |
|---|---|
| `format` | `cfn`／`tf` |
| `root` | 入力のパス。`aws-iac-diagram-workspace/` からの相対パス（ツールとして使うときは、作業中のフォルダからの相対パス）で、`/` 区切り（C5。OS によらず同じにする）。CFN は最上位のテンプレートか cdk.out のディレクトリ、TF はルートモジュールのディレクトリ |
| `evaluation` | 評価に使った値。CFN は `parameters`（使った値。外から渡した値か Default）と `conditions`（すべての条件の評価の結果。決まらなければ `null`）、TF は `var_files` と `vars`。`assumptions` は読み替えや既定値の採用などの前提（書いた順）。ネストスタックと cdk.out の複数スタックでは、名前の前にスタックのパスを付ける（7.2 の address と同じ形。`NetworkStack/HasNat`、`App::IsProd`）。最上位のテンプレートの名前には付けない |
| `resources` | 入力の**すべての**リソース（7.2）。網羅分類（A6）の元になる |
| `references` | リソースからリソースへの参照の一覧（7.3） |
| `diagnostics` | 読めなかった・評価できなかったものの記録（7.5） |

### 7.2 リソース

```json
{"address": "AppService", "type": "AWS::ECS::Service", "file": "template.yaml", "enabled": true,
 "props": {"ServiceName": "demo-app", "Cluster": {"$res": "Cluster", "attr": null},
           "LoadBalancers": [{"TargetGroupArn": {"$res": "AppTargetGroup", "attr": null}, "ContainerPort": 8080}]}}
```

| フィールド | 必須 | 内容 |
|---|---|---|
| `address` | ○ | 網羅分類と同じ形（4章）。CFN のネストスタックの中は `<親の論理ID>/<論理ID>`。cdk.out など**複数のスタック**を読むときは、先頭に `<スタック名>::` を付ける（`App::Vpc`、`My-App::NetworkStack/Vpc`。スタック名は英字で始まり、英数字とハイフンだけ）。スタック名は manifest の `stackName`（無ければ artifact の ID）で、同じ `stackName` が2つ以上あるときは artifact の ID を使う。CDK の Stage（入れ子のアセンブリ）の中のスタックも読む。TF はインスタンスアドレス（値が決まらない count は `[*]`） |
| `type` | ○ | 入力のままの型。TF の黒箱のモジュールの呼び出しは `module` |
| `file` | ○ | ファイルのパス。`root` がディレクトリならそこからの相対、ファイルならそのファイルのあるディレクトリからの相対（`/` 区切り。ルートの外は `../` 付き。4章） |
| `enabled` | ○ | 作られるか。`true`／`false`（CFN の `Condition` が偽、TF の count が 0）／`null`（決まらない）。`false` のリソースも一覧に残し、`props` と参照も同じように出す（網羅分類で `H-COND-FALSE` にし、C1 で参照を照合するため）。正規化は `null` のリソースを描き、`diagnostics` に「条件が決まらない」と残す。ネストスタックの子のリソースは、親のスタックのリソースの値を引き継ぎ、自分の値との弱い方（`false` > `null` > `true`）にする |
| `props` | ○ | 評価した後のプロパティ（CFN は `Properties`、TF は属性とブロック）。値の書き方は下の表 |
| `multiplicity` | | count／for_each の値が決まらないときだけ `"N"` |
| `via` | | `nested_stack`（ネストスタックの子テンプレートから読んだ）、`module_summary`、`module_blackbox`（4章） |
| `implicit` | | SAM が暗黙に作るリソース（`Events` に `RestApiId`／`ApiId` が無いときの `ServerlessRestApi`／`ServerlessHttpApi` など）なら `true`。address は SAM が付ける論理ID。網羅分類にも載せる |
| `module` | | TF だけ。モジュールの中のリソースなら、モジュールのパス（`module.vpc`） |
| `source`, `version` | | TF の黒箱のモジュールの呼び出しだけ。モジュールの source と version（`props` はモジュールの入力） |

**`props` の値の書き方**

評価できたものはふつうの JSON の値にし、できなかった部分だけ、`$` で始まるキーを持つオブジェクト（印）にする。入力にもともと `$` で始まるキーがあるとき（API Gateway のモデルの `$schema`、EventBridge のパターンの `$or` など）は、`$` をもう1つ付けて書く（`$schema` → `$$schema`）。読む側は、`$$` で始まるキーの先頭の `$` を1つ外して元に戻す。

| 印 | 意味 | 例 |
|---|---|---|
| `{"$res": "<address>", "attr": <属性名か null>}` | 入力の中のリソースへの参照。CFN の `Ref` は `attr: null`、`Fn::GetAtt` は属性名（`!GetAtt A.B.C` は `B.C`）。TF は参照した属性名（`id`、`arn` など） | `{"$res": "OrdersTable", "attr": "Arn"}` |
| `{"$pseudo": "<名前>"}` | 擬似パラメータ。CFN の `AWS::Region`、`AWS::AccountId`、`AWS::Partition`、`AWS::StackName`、`AWS::StackId`、`AWS::URLSuffix`、`AWS::NotificationARNs`。TF の `data.aws_region`、`data.aws_caller_identity`、`data.aws_partition` の値も、同じ CFN の名前（`AWS::Region` など）で書く（ARN の照合を TF と CFN で揃えるため）。`AWS::NoValue` はプロパティ（リストなら要素）ごと消す | `{"$pseudo": "AWS::Region"}` |
| `{"$concat": [ … ]}` | 文字列と印をつないだもの（`Fn::Sub`、`Fn::Join`、TF の `"${…}"`）。正規形: 隣り合う文字列は1つにつなぐ、空文字は消す、印を1つ以上含む（印が無くなればただの文字列にする）、`$concat` を入れ子にしない。要素は文字列と、`$concat`・`$json` 以外の印だけ | `{"$concat": ["arn:aws:s3:::", {"$res": "Docs", "attr": null}, "/*"]}` |
| `{"$json": <値>}` | JSON の文字列として渡す値（TF の `jsonencode(...)`、CFN で JSON を文字列で書く `!Sub '{"Rules": …}'` など）。中身は構造のまま、印を使って書く。CFN の文字列は、`${…}` を置き換えた上で JSON として読めたときだけ `$json` にし、読めなければ `$concat` のまま。**印の無いふつうの文字列も、`{` か `[` で始まり JSON のオブジェクトか配列として読めれば `$json` にする**（同じプロパティが、値によって文字列になったり `$json` になったりしないように。TF の `jsonencode` も、値が全部決まるときを含めて同じ）。文字列の途中に入る JSON（`$concat` の要素）は `$unknown` | `{"$json": {"Statement": [{"Resource": {"$res": "Docs", "attr": "Arn"}}]}}` |
| `{"$az": <0 始まりの番号か "*">}` | 静的に決まらない AZ。`!Select [0, !GetAZs '']`、`data.aws_availability_zones.x.names[0]` は番号（整数で書く）。`!GetAZs ''` だけ、`names` 全体は `"*"`（すべての AZ）。2章の `az1` の元 | `{"$az": 0}` |
| `{"$import": "<エクスポート名>"}` | 入力の中で解決できなかった `Fn::ImportValue`。解決できたもの（cdk.out の別のスタックが Export しているなど）は、エクスポートした値（`$res` など）に置き換え、参照の `fn` を `ImportValue` にする（7.3） | `{"$import": "shared-vpc-id"}` |
| `{"$unknown": "<理由>"}` | 評価できなかった値（値の無いパラメータ、`AWS::SSM::Parameter::Value<…>` 型のパラメータ、`{{resolve:…}}`、未対応の関数、plan JSON の「known after apply」など）。中にあった参照は `references` に `state: "unevaluated"` で残す（7.3）。同じ理由を `diagnostics` にも書く | `{"$unknown": "parameter KeyName has no value"}` |

- **A4（CFN）:** パラメータの値は、外から渡した値（アダプタの `--param`・`--param-file`）→ `Default` の順に使う。`AllowedValues` に無い値は診断に出す。擬似パラメータ（`AWS::Region` など）に渡した値は、条件の評価にだけ使い、`props` は `$pseudo` のままにする（TF と ARN の照合を揃えるため）。条件（`Fn::Equals`・`Fn::And`・`Fn::Or`・`Fn::Not`・`Condition`）は、真・偽・決まらない（`null`）の3つの値で評価する（`And` は偽が1つでもあれば偽、`Or` は真が1つでもあれば真、それ以外で決まらないものがあれば決まらない）。`Fn::Equals` は値を文字列にして比べる。`Fn::ForEach` は、コレクションが決まれば展開し（`${Id}`・`&{Id}`・`Ref Id` を置き換える）、決まらなければテンプレートの1つだけを `multiplicity: "N"` で出す（address は 2章の `Bucket*` の形）。値の真偽値は YAML 1.1 のとおり読む（`yes`・`on` なども真偽値。cfn-lint と同じ）。マップのキーは元の文字のまま読む（`Yes:`・`On:`・`1:` も文字列の名前として残す）。名前の位置（`Condition:` の値、`Ref`）に真偽値として読まれた値は、同じ文字の名前（`Yes`・`On` など）が1つだけあればそれに戻す。パラメータの値が `null`（CLI の `UsePreviousValue`）のときは渡されていないものとして `Default` を使う。SSM の型（`AWS::SSM::Parameter::Value<…>`）のパラメータは、値を渡されても `$unknown`。`Fn::FindInMap` のキーは文字列で引き、キーの評価には擬似パラメータの値も使う（リージョンごとの表を引くため。マップの値は参照を含まない）。`Fn::ForEach` はプロパティの中と `Outputs` の中でも展開する。展開した名前が重なったら後のものを診断を出して飛ばし、×N の名前が重なったら後ろに `.<ForEach の名前>` を付けて両方残す。
- `Fn::If`、`Fn::FindInMap`、`Fn::Select`、`Fn::Split`、`Fn::Equals` などは、値が決まれば評価して結果だけを残す。条件が決まらない `Fn::If` は `$unknown`。評価で選ばれなかった値（`Fn::If` の選ばれなかった側、`Fn::Select` で選ばれなかった要素、`Fn::FindInMap` で引かなかったキーなど）の中にあった参照は、`references` に `state: "pruned"` で残す（cfn-lint は条件を評価せず、これらも辺にするため）。
- **リストの分割:** `Fn::Split` と、`List<…>`／`CommaDelimitedList` 型のパラメータに文字列を渡したとき（ネストスタックの出力 `!Join [",", [!Ref A, !Ref B]]` を受けるなど）は、`$concat` の文字列の部分を区切り文字の位置で分け、印は分けずにリストにする（`{"$concat": [A の印, ",", B の印]}` → `[A の印, B の印]`）。
- ネストスタックの出力（`!GetAtt NetworkStack.Outputs.VpcId`）と、子テンプレートの `Parameters` に渡した値は、たどって元のリソースへの `$res` にする（TF のモジュールの出力・変数も同じ）。たどった経路は 7.3 の `through` に書く。`AWS::CloudFormation::Stack` のリソース自身の `props` の `Parameters` は、リストの分割をしない（分割は子テンプレートの側で、パラメータの型を見て行う）。
- TF のスプラット（`aws_subnet.private[*].id`）は、インスタンスの数が決まればインスタンスごとの `$res` のリストにし、決まらなければ `{"$res": "aws_subnet.private[*]", "attr": "id"}` の1つにする。
- **SAM:** `Globals` は各リソースに混ぜてから `props` にする（cfn-lint と同じ。マップは中まで、リストは Globals の後ろにつなぐ、値はリソースの方。組み込み関数は1つの値として扱い、中に混ぜない）。暗黙の API（`implicit`）にも `Globals.Api`／`Globals.HttpApi` を混ぜる。暗黙の API は、`AWS::Serverless::Function` と `AWS::Serverless::StateMachine` の `Events` から作る。`Events`、`Policies`（ポリシーテンプレート）はプロパティのまま `props` に残し、SAM の変換（Transform）はしない（変換に当たることは、正規化の規則で扱う。relation-resources.md）。

### 7.3 参照

```json
{"from": "AppService", "path": "Properties.LoadBalancers[0].TargetGroupArn", "to": "AppTargetGroup", "attr": null, "fn": "Ref", "state": "active"}
```

| フィールド | 必須 | 内容 |
|---|---|---|
| `from`, `to` | ○ | リソースの address。`to` は入力の中のリソースだけ（`$import` などの解決できないものは参照にしない） |
| `path` | ○ | `from` のどこから参照したか。**評価した後の `props` の上の位置**で、印の中（`$concat` の何番目か）は含めない。CFN は `Properties.…`（`DependsOn` は `DependsOn`。`Properties` の外の `Metadata`、`CreationPolicy`、`UpdatePolicy` の中の参照も出し、`Metadata.…` のように書く。cfn-lint はこれらも辺にするため）、TF は属性のパス（`load_balancer[0].target_group_arn`、`depends_on`）。リストの位置は `[0]`、識別子（`[A-Za-z_][A-Za-z0-9_-]*`）として書けないキー（`.` や空白を含むなど）は `["key"]`、`$$` で逃がしたキーは元のキーで書く。`$json` は位置に数えず、中の位置をそのまま続ける。同じ `$concat` の中に同じ参照（`to`・`attr` が同じ）が2回あっても1件。`state` が `pruned`／`unevaluated` の参照は、その参照を含んでいたプロパティの位置 |
| `attr` | ○ | 参照した属性（CFN の `Ref` は `null`） |
| `fn` | ○ | CFN: `Ref`／`GetAtt`／`Sub`（`${X}` は `attr: null`、`${X.Attr}` は `attr` に属性名）／`ImportValue`（入力の中で解決できたもの）／`DependsOn`。TF: `ref`／`depends_on` |
| `state` | ○ | `active`（評価した後の `props` にある）／`pruned`（`Fn::If` の選ばれなかった側にあった）／`unevaluated`（評価できなかった値の中にあった。`$unknown` になったところ） |
| `through` | | たどった経路を、`from` の側から順に並べる。CFN: `NetworkStack.Outputs.VpcId`、`AlbStack.Parameters.PublicSubnetIds`、`Export:<エクスポート名>`。TF: `module.network.output.vpc_id`、`module.app.var.subnet_ids` |

- **一意のキーと並び順:** `(from, path, to, attr, fn)` で1件に決まり、この順で並べる（`!Sub "${Bucket}/${Bucket.Arn}"` のように、同じ位置から同じリソースへ別の属性で参照するものは別の件になる）。
- **`props` との対応:** `props` の中のすべての `$res` は、`state: "active"` の参照に1件ずつ対応する（`from`、`path`、`to`、`attr` が同じ）。逆に、`references` にあって `props` に無いのは、`DependsOn`／`depends_on`、CFN の `Properties` の外（`Metadata` など）の参照、`state` が `pruned`・`unevaluated` のものだけ。
- `AWS::CloudFormation::Stack` のリソース自身も、`Parameters` に渡した値の参照を出す（`from` はスタックの論理ID）。子テンプレートの中の参照は、子のリソースを `from` にして別に出す。
- ネストスタックの出力をたどった値に参照が残らないとき（出力が文字列だった、評価できなかった）は、スタックのリソースへの参照（`to` はスタック、`attr` は `Outputs.<名前>`、`state: "unevaluated"`）を残す。出力の中にあった `pruned`／`unevaluated` の参照も、使った側の参照として、`through` に出力を足して残す（cfn-lint は使った側 → スタックを辺にするため）。
- 同じ子テンプレートを2つのスタックから使うときは、スタックごとに別々に読み、address の先頭（親の論理ID）で区別する。
- `AWS::NoValue` でリストの要素が消えると、後ろの要素の位置（`[n]`）がずれる。C1 の照合では、この位置のずれを考えて対応づける（CRITERIA の 1.6）。

### 7.4 入力ごとの扱い（公開サンプルで見つかった問題。SELECTION.md の 4）

| 問題 | 扱い |
|---|---|
| CFN の `TemplateURL` が S3 の URL（C04、C05） | URL のパスと、`root` のディレクトリの下のファイルの相対パスを、末尾から `/` 区切りの要素ごとに比べ、一致する要素が最も多いファイルを子テンプレートとして読む（`infrastructure/vpc.yaml` と `vpc.yaml` があり、URL が `…/infrastructure/vpc.yaml` なら前者）。最も多いものが2つ以上あるか、1要素も一致しないときは黒箱のモジュール（2章）にし、`diagnostics` に書く。読み替えたことは `evaluation.assumptions` に書く |
| TF のローカルモジュールがルートの外（T04、T14、T15 の `../../`） | そのまま読む。`file` は `../` 付きの相対パス（4章） |
| AWS 以外のプロバイダの型（T15 の awscc、T18 の kubernetes、T09 の opensearch など） | アダプタはそのまま `resources` に載せる。扱いは正規化の規則表（resource-catalog.md）で決める。方針: awscc の型は同じ名前の CFN の型（`awscc_ec2_vpc` → `AWS::EC2::VPC`）として扱う。random、null、time などクラウド上の実体が無いものは既存の `H-UTILITY`。それ以外のプロバイダ（kubernetes、helm、tls、local など）は非表示（規則 `H-NONAWS`）。opensearch の index のように AWS のリソースの中身を作る型は、そのリソースに統合する（既存の `M-AOSS-INDEX`）。個々の型の行は、フェーズ3 で公開サンプルの型を足すときに書く |
| 既存のインフラを指す TF の `data`（T20 は 413 件） | `data` も `resources` に載せる（address は `data.` 付き）。描くか非表示にするかは正規化で決める。方針: 描く型の `data`（`data.aws_vpc`、`data.aws_subnet` など）が、描くリソースから参照されていれば、既存のノードとして描く。それ以外は `H-DATA`。`terraform_remote_state` はフェーズ2 で決める |
| python-hcl2 が heredoc の終端の空白で読めない（T06） | TF アダプタ（フェーズ2）で、heredoc の終端の行の末尾の空白を取ってから読む。取ったことを `diagnostics`（level `info`）に書く |

### 7.5 診断

```json
{"level": "warn", "code": "CFN-UNRESOLVED-PARAM", "address": "Bastion", "path": "Properties.KeyName", "message": "parameter KeyName has no value"}
```

- `level` は `info`（読み替えなど、結果に影響しない）／`warn`（評価できなかった値があり、図が不完全になりうる）／`error`（そのリソースか、ファイルを読めなかった）。
- `code` は大文字で、raw では `CFN-…`／`TF-…`。正規化後の IR にも同じ形の `diagnostics` を持たせ、そこでは `NORM-…`（「使わなかった参照」、「条件が決まらない」など。edge-rules.md）。一覧は各段階の実装と一緒に決める。
- `diagnostics` は `result.json` にそのまま載せる。`error` があっても、読めた分の IR は出す（終了コードは PLAN 1.3 の 4 に従う）。

## 8. 決めなかったこと（後のフェーズで決める）

- **複数ビュー（B2）の詳細度:** IR には持たせない。どのノードをどのビューに出すかは、型ごとに resource-catalog.md の列で決める（フェーズ4。IR を表示の都合で変えないため）。
- **`terraform_remote_state`** の扱い（フェーズ2）。
- **診断の `code` の一覧**（各アダプタの実装と一緒に）。
- **ノード ID の重なり**（2章）を解いたときの、TF／CFN の対応表の形（フェーズ2）。

## 9. v0.1 からの変更点（2026-10-17）

- `ir_version` を `1.0` にした。正規化後の形は v0.1 と互換（正解 IR は `ir_version` を直しただけ）。
- `attrs` のキーを表で固定した（2章）。v0.1 の正解 IR が使っていた `cidr`、`access`、`endpoint_type`、`service` に、黒箱のモジュール用の `module_source`、`module_version` を足した。
- 黒箱のモジュール（型 `module`、`via: "module_blackbox"`）を足した（2章、4章）。辺は `inferred` にした。
- ×N の出し方と、AZ が静的に決まらないときの key を決めた（2章）。
- 正規化後の IR に、省略可の `diagnostics` を足した（1章）。
- アダプタの出力（`stage: "raw"`）を定義した（7章）。第三者レビュー（2026-10-17）の指摘で、印の名前を `$res` にし（JSON Schema の `$ref` との取り違えを避ける）、`$$` の逃がし方、`$json`、`$concat` の正規形、リストの分割、参照の `state`・一意のキー、複数スタックの address、解決できた ImportValue、SAM の Globals と暗黙のリソース、TF の `$pseudo`・スプラット・`through` の書き方を決めた。
- 網羅分類の `file` に、ルートの外の `../` 付きのパスを認めた（4章）。
