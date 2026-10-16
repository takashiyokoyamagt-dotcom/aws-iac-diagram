# IR スキーマ（v0.1 草案）

- 状態: **草案**（フェーズ0 で正解 IR を書くために作った。フェーズ1 で確定させる）
- 機械可読な定義: [ir.schema.json](ir.schema.json)（JSON Schema 2020-12）
- 検証: `scripts/validate_ir.py`（スキーマ＋参照の整合＋出力形式）
- 関連する規則表: [resource-catalog.md](resource-catalog.md)（型ごとの扱い・入れ子）、[relation-resources.md](relation-resources.md)（A1）、[edge-rules.md](edge-rules.md)（A2・A3・SG・IAM・合成ノード）

v0.1 が定義するのは **正規化後の IR**（PLAN 3 の ② の出力、フェーズ3 の出力に当たる）だけである。アダプタの出力（① の、正規化前の IR）はフェーズ1 で別に決める。正解 IR（`aws-iac-diagram-workspace/expected/*.ir.json`）はこの形で書く。

## 1. 全体の構造

```json
{
  "ir_version": "0.1",
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
| `category` | ○ | `group`（枠: vpc・availability_zone・subnet）／`resource`／`external`（AWS の外: internet） |
| `name` | ○ | B3 の採用順（`Name` タグ → 型ごとの名前属性 → 論理名）で決めた **名前**。評価後の値で、省略や言い換えをしない。`id` の key はここから作る |
| `label` | ○ | **表示名**。v0.1 は `name` と同じ（合成ノードを除く）。B3 の省略規則・日本語ラベルは `label` だけを変え、`name` と `id` は変えない |
| `parent` | ○ | 直接の親（group のノード）。リージョン直下は `null` |
| `spans` | | 複数のサブネットに置かれるリソースの、置き場所のサブネット（2つ以上）。このとき `parent` はそれらの最も近い共通の祖先（P-SPANS） |
| `synthetic` | | 入力に対応するリソースが無い、正規化で作ったノードは `true`（AZ、`external/internet`、`bedrock_model`） |
| `multiplicity` | | 値が決まらない count／for_each を1つにまとめたときだけ `"N"`（×N）。**v0.1 では、値が決まる count／for_each はまとめず、インスタンスごとに別のノードにする**（例: `aws_subnet.public[0]` と `[1]` は2ノード）。整数の値はまとめる規則を入れたときのために予約しておく。省略は 1 |
| `attrs` | | 表示や枠の種類に使う少数の値（`cidr`、サブネットの `access`: public／private など） |
| `note` | | 判断理由（比較に使わない） |

### ID の作り方（K-NAME）

- `key` = `name` を小文字にし、`[a-z0-9._-]` 以外の文字を `-` にしたもの（表示用の `label` からは作らない。省略や日本語化で ID が変わると C5 と採点が壊れるため）。`name` は B3 の順で決める:
  1. `Name` タグ（TF の `tags.Name`、CFN の `Tags` の `Key: Name`）
  2. 型ごとの名前属性（`function_name`／`FunctionName`、`bucket`／`BucketName`、`identifier`／`DBInstanceIdentifier`、`name`／`Name` など。`resource-catalog.md` の「名前属性」列）
  3. 論理名（TF: モジュールのパスを `.` でつないだもの＋リソース名、CFN: ネストスタックの論理ID を `.` でつないだもの＋論理ID）。インデックスは `-0` のように付ける
- 名前は A4 で評価した後の値を使う（`"${local.name}-alb"` → `demo-alb`）。評価できなければ 3 に落ちる。
- 同じ型で key が重なったら、重なったリソースを入力のアドレス（TF）／論理ID（CFN）の辞書順に並べ、2つ目以降の key の末尾に `.<論理名の key>`（論理名は上の 3 の形）を付ける。論理名は TF と CFN で違うので、**この場合は canonical 部が TF 版と CFN 版で一致しない**（フェーズ2 の比較では、重なりを解いたノードを対応表で突き合わせる）。v0.1 の fixture には重なりは無い。
- **ARN や AWS が払い出す ID は使わない**（失敗知見17）。名前が決まらないリソースは論理名に落ちるので、TF 版と CFN 版で ID が一致するのは「名前が付いているもの」だけになる。fixture は描くリソースすべてに名前を付けてある。
- 合成ノード（`name` から key を作らない）: AZ は `availability_zone/<VPC の key>.<AZ 名>`（`name` は AZ 名）、インターネットは `external/internet`（`name` は `internet`、`label` は `Internet`）、Bedrock の基盤モデルは `bedrock_model/<モデルID の key>`（`name` はモデルID。例 `bedrock_model/amazon.titan-embed-text-v2-0`）。

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
- `via: "module_summary"`: レジストリモジュール（`terraform-aws-modules/vpc/aws` など）の中身で、ソースを読まずに A5 の要約表から展開したもの。`file` はモジュール呼び出しのあるファイル。要約表から展開するのは、その入力で作られる managed リソースだけ（モジュール内部の `data` と、count が 0 になるリソースは載せない）。
- ノードを作る1つのリソースが、同時にほかのノードの配置を決めることがある（例: `aws_db_subnet_group` は統合されるが、DB の `spans` を決める）。分類は1つだけ書き、ほかの役割は `edges` の根拠や `note` に書く。

### 辺の根拠（edges）

canonical 部の **すべての辺** について、形式ごとに1件ずつ、使った規則（`rules`）と根拠（`evidence`。`アドレス.属性` の形の短い文字列）を書く。推定（inferred）の辺は、ここが説明 .md の「推定した辺の一覧」の元になる（A3）。

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
- `validate_ir.py --write` でこの形に整形できる。`validate_ir.py` は形がずれていればエラーにする。

## 7. 未決事項（フェーズ1 で決める）

- アダプタ出力（正規化前）の IR の形。参照（どの属性からどの属性へ）の表し方。
- AZ が静的に決まらない場合（CFN の `!GetAZs`、TF の `data.aws_availability_zones`）の AZ ノードの key（`<vpc>.az1` のような番号にする案）。
- ×N（`multiplicity: "N"`）の具体的な出し方。fixture にはまだ例が無い。
- 複数ビュー（B2）のための、ノード・辺の「詳細度」の属性。
- `attrs` に何を入れるか（いまは `cidr`、`access`、`endpoint_type`、`service` だけ）。
