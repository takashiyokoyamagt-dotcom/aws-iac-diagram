# フェーズ 3（正規化）設計案（草案。ユーザーの確認前）

- ユーザーが推奨案での進行を了承（2026-10-26）。手順1 の実装済みの点は WORKLOG を見ること
- 作成日: 2026-10-26。状態: **草案（未承認・未実装）**。コード・規則表・正解 IR・CRITERIA は何も変えていない。確定文書（PLAN.md、CRITERIA.md、ir-schema）と食い違う点は、変えずに 8 章に書いた
- 印の使い方: 「（実測）」はこの調査で実際に raw IR を作って数えた値（スクラッチの使い捨てスクリプトによる概算。リポジトリには入っていない）。「（仮定）」は文書に書かれておらず、この案で置いた前提
- 読んだもの: PLAN.md（1.4、4 章 A1〜A6・B3、フェーズ表）、CRITERIA.md（0〜7 章）、`docs/spec/ir-schema/` 全章、`references/` の規則表 3 つ、`data/schemas/*.json`、`validate_ir.py`、`expected/*.ir.json`、SELECTION.md、`docs/architecture.md`、HANDOFF・WORKLOG、`tools/check_coverage.py`・`golden.py`

## 9. 要約（先頭に置く）

1. 正規化は「データ（`data/rules/` の表）」と「コード（`normalize/` の段階）」を分ける。型の扱い・属性名の集合・単純な関係リソースは**表の行を足すだけ**で増やせるようにし、SG・ルート・LB・API Gateway・IAM のような手続きは**規則 ID で束ねたハンドラ**に置く（PLAN 1.4 の 5「型の扱いは `data/rules/` に行を足す」の約束を守る形）。
2. パイプラインは 6 段階（分類 → ノード → 辺 → 入れ子 → ラベル → 検証）。**分類は型の表を 1 回引いただけでは決まらない**（M-* の統合先、R-* が辺を生んだか、H-SG-NOEDGE などは辺ができた後に確定する）ので、「型による仮分類 → 辺の後に確定」の 2 パスにする。
3. 規則データの形式は **TOML（領域別のファイル。標準ライブラリ `tomllib` だけで読める）** を推奨。説明の文章は `docs/spec/` に分け（PLAN 1.4 の 2 のとおり）、表の描画は道具で生成して二重管理を避ける。
4. 草案の表は足りない（実測）: 主セットの非 data リソース 231 件のうち 67 件（29%）、公開サンプル 72 入力の 3,290 件のうち 1,196 件（36%、191 型）が、草案の表に型が無い。主セットの `unknown` 0 件（CRITERIA 1.2）のため、**表の拡張（約 40 型）が最大の作業**になる。
5. 手順は 7 つ。最初の手順は「規則データ化」（動きを変えない。golden 101/101・正解 IR の検査・`validate_ir.py` の結果が前後で同じ）。
6. **ユーザーに確認したい点（上位 5。詳細は 8 章）:** ① 規則データの形式（TOML 推奨）、② 主セットの正解 IR を書く手順（CRITERIA 1.2 の「ツールの出力」の解釈と、規則表を先に凍結する順序）、③ 既存インフラを指す `data`（T09 の `data.aws_s3_bucket`）を描く規則、④ IAM だけのモジュール（H-IAM）の判定を `core` へ移す小さな改修の許可、⑤ B3 の省略規則・日本語ラベルと 1.3（大きいサンプル）・1.7（変異テスト）をフェーズ 3 に含めるか後回しにするか。

---

## 1. 目的と完了基準

### 1.1 目的

PLAN 3 の ②（正規化）を作る: **raw IR（アダプタの出力。ir-schema 7 章）から、図に描く内容と網羅分類と辺の根拠を持つ normalized IR（同 1〜6 章）を、決定論的に作る**。PLAN 4 の A1（関係リソース → 辺）、A2（向き）、A3（確信度）、A6（網羅）、B3（名前）と、AZ の挿入、SG → 辺をここで実現する（PLAN.md 379 行のフェーズ表）。

### 1.2 完了基準（PLAN のフェーズ 3 行 + CRITERIA）

| # | 対象の入力 | 指標 | 基準 | 出典 |
|---|---|---|---|---|
| a | 自作 5 構成 × TF／CFN（10 入力） | N・E・P の再現率・適合率、名前の一致率 | すべて 1.0 | CRITERIA 1.1 |
| b | 同上 | C（網羅分類）の一致率、辺の確信度・辺のラベル・ノードのラベルの一致率 | 1.0 | 1.1 |
| c | 同上 | 同じ構成の TF 版と CFN 版の canonical 部（`note` を除く `nodes`・`edges`） | バイト単位で一致 | 1.1、PLAN 379 行 |
| d | 主セット（T03、T06、T06s、T07、T07s、T09、T11、T11s、T12、T16、C01、C02 の 12 入力） | N の再現率・適合率 | 全体 0.95 以上／入力ごと 0.90 以上 | 1.2 |
| e | 同上 | 名前の一致率 | 全体 0.90 以上 | 1.2 |
| f | 同上 | E の再現率 | 全体 0.90 以上／入力ごと 0.80 以上 | 1.2 |
| g | 同上 | E の適合率（確定・導出）／（推定） | 全体 0.95／0.80 以上、入力ごと（確定・導出）0.90 以上 | 1.2 |
| h | 同上 | P の再現率・適合率 | 全体 0.95 以上／入力ごと 0.90 以上 | 1.2 |
| i | 同上 | C の一致率／一致した辺の確信度の一致率 | 全体 0.95／0.90 以上（C は入力ごと 0.90 以上） | 1.2 |
| j | 同上 | `unknown`（型が分からないリソース） | 0 件（入力ごとも 0 件） | 1.2 |
| k | 上の 22 入力すべて | 重大な誤り X1（internet 到達）・X2（正解に無い関係を確定／導出で描く）・X3（逆向き）・X4（網羅の漏れ・重複） | 各 0 件 | 1.5 |
| l | **すべての入力**（自作 10、主セット 12、補助セット 15、大きいサンプル 3、ほか公開サンプルの全 raw IR） | raw IR の `active` の参照（DependsOn を除く）で、4 つの分類（辺の根拠／入れ子／`E-NOEDGE-*`・`E-REF-NONODE`／`NORM-UNUSED-REF`）のどれにも入らないもの | 0 件。`NORM-UNUSED-REF` の件数と属性名の内訳を完了の確認で必ず見る | 1.8 |
| m | 補助セット 15 入力 | X4、`unknown` の件数と型の一覧の出力、`validate_ir.py` が通る、実行エラー（終了コード 2）にならない | 満たす（件数の基準なし） | 6 章 |
| n | TF／SAM の対（T06・T07・T11） | ノードの型の多重集合（許す違いの一覧を除いて一致）、辺の (from の型, to の型, kind) の多重集合の一致率 | 一致／0.90 以上。許す違いの一覧は出力を見る前に対ごとに作る（半自動） | 1.4、PLAN 379 行 |
| o | すべての入力 | 同じ入力を 2 回・Windows と Ubuntu で実行した IR | バイト単位で一致 | 3 章（C5） |

入力ごとの下限は、母数が 10 未満なら「誤り 1 件以内」（CRITERIA 1.0）。割合の基準を満たしても X1〜X4 が 1 件あれば不合格（0 の 2）。

### 1.3 未決の点（この案で決めていないもの）

- **1.3（大きいサンプル T17・T19・C05 の抜き取り・点検表）と 1.7（変異テスト C4）、5 章（目視の採点）をフェーズ 3 の完了基準に含めるか。** PLAN のフェーズ 3 行には 1.1・1.2・1.8・X4・TF／CFN の一致しか無く、1.3・1.7 は PLAN のフェーズ 6 の評価（C3、C4、C6）に見える。→ 8 章の 7。
- 完了の確認で CRITERIA 4 章（実行時間 30 分以内）を測る。HANDOFF の「次の作業」にある。正規化そのものは小さい（最大の raw IR は 198 リソース・2,564 参照〈T19〉。golden の 101 ケースの合計は 3,880 リソース・10,779 参照〈実測〉）ので、時間の大半は後のフェーズの描画になる見込み。
- 正規化後の `evaluation` の中身（4 章に書いた不一致）。
- 8 章（ir-schema）の「決めなかったこと」のうち、フェーズ 3 で決めると書かれたもの（`cidr` の式の評価、ノード ID の重なりを解いたときの TF／CFN の対応表、`NORM-…` の一覧）。→ 8 章の末尾で扱いを提案。

---

## 2. 入力と出力

### 2.1 形

```
raw IR（stage: "raw"）                 normalized IR（stage: "normalized"）
  adapt_tf.py / adapt_cfn.py の出力        normalize_ir.py の出力（案）。1 入力 = 1 形式 = sources に tf か cfn の 1 つ
  resources / references / diagnostics     nodes / edges（canonical 部）+ sources（由来部）+ evaluation + diagnostics（NORM-）
        │                                              ▲
        └── data/rules/（表）+ normalize/（段階） ─────┘
```

- 入力は 1 つの raw IR（TF か CFN の一方）。出力の `sources` はその形式の 1 つだけ。正解 IR（`expected/*.ir.json`）は 1 ファイルに `sources.tf` と `sources.cfn` を持つ（`three-tier.ir.json` は tf 39・cfn 38 件〈実測の raw も同数〉）ので、**比較ツールは正解 IR を形式ごとに射影して比べる**（7 章）。TF 版と CFN 版が同じかは `validate_ir.py --same-canonical`（既存）で比べる。
- 参照されない raw の部分: `diagnostics`（`TF-…`・`CFN-…`）は normalized IR に写さない（スキーマの `diagnostics` は `NORM-` だけを許す。ir.schema.json の pattern）。raw の診断は raw のファイルに残り、`result.json`（フェーズ 6）が raw を直接読む（PLAN 1.3 の 4）。写すのは、ユーザーが知るべきものだけを `NORM-RAW-ERROR` にまとめる（4 章）。
- **`evaluation` の食い違い（仕様の穴）:** raw の `evaluation.tf.vars` は `{名前: {"source": …}}`（値は書かない。2026-10-17 のユーザーの決定。07-raw-output.md の 7.1）だが、normalized の `evaluation.tf.vars` は値（スカラーか配列）を持つ形（ir.schema.json）。正解 IR は `vars: {}`。**案:** `tf.var_files` は raw のまま写し、`tf.vars` は `{}`（値を持たない）、`cfn.parameters` は最上位テンプレートのスカラー値だけ（ネストスタックの `AlbStack/…` や `$res` を持つ値は除く。正解 IR の `three-tier-modules` が `{}` なのと合う）、`cfn.conditions` は写す、`assumptions` は raw のものを写し、正規化で足した前提を後ろに足す。`name`（`^[a-z0-9][a-z0-9-]*$`）は入口の `--name` か、`root` の最後の要素を小文字化・`-` 置換したもの（仮定）。

### 2.2 canonical 部と由来部

| 部 | 中身 | 形式（TF／CFN）による違い |
|---|---|---|
| canonical（`nodes`・`edges`） | 図に描く内容。ノードの id・型・category・name・label・parent・spans・attrs・synthetic・multiplicity、辺の id・from・to・kind・label・confidence | **なし**（同じ構成なら同じ。フェーズ 3 の基準 c） |
| 由来部（`sources.<形式>`） | `resources`: 入力の全リソース 1 件ずつの分類（drawn／merged_into／hidden／unknown と node／into／rule／via／file）。`edges`: 辺ごとの規則と根拠 | あってよい（TF の `aws_s3_bucket_versioning` と CFN のプロパティ、CFN の `VPCGatewayAttachment` など） |
| `note`（ノード・辺・分類） | 判断理由。比較には使わない | — |

### 2.3 例: three-tier の ALB のリスナー（実データ）

raw（TF と CFN。形が違う。`path` の書き方、キーの綴り、ブロックのリスト化）:

```json
{"address":"aws_lb_listener.http","type":"aws_lb_listener","file":"alb.tf","enabled":true,
 "props":{"load_balancer_arn":{"$res":"aws_lb.app","attr":"arn"},"port":80,"protocol":"HTTP",
          "default_action":[{"type":"forward","target_group_arn":{"$res":"aws_lb_target_group.app","attr":"arn"}}]}}
{"from":"aws_lb_listener.http","path":"default_action[0].target_group_arn","to":"aws_lb_target_group.app","attr":"arn","fn":"ref","state":"active"}

{"address":"HttpListener","type":"AWS::ElasticLoadBalancingV2::Listener","file":"template.yaml","enabled":true,
 "props":{"LoadBalancerArn":{"$res":"Alb","attr":null},"Port":80,"Protocol":"HTTP",
          "DefaultActions":[{"Type":"forward","TargetGroupArn":{"$res":"AppTargetGroup","attr":null}}]}}
{"from":"HttpListener","path":"Properties.DefaultActions[0].TargetGroupArn","to":"AppTargetGroup","attr":null,"fn":"Ref","state":"active"}
```

normalized（正解 IR `three-tier.ir.json` から。canonical 部は TF／CFN で同じ。**ノード 15・辺 7**）:

```json
{"id":"alb/demo-alb","type":"alb","category":"resource","name":"demo-alb","label":"demo-alb","parent":"vpc/demo",
 "spans":["subnet/demo-public-ap-northeast-1a","subnet/demo-public-ap-northeast-1c"]}
{"id":"external/internet->alb/demo-alb","from":"external/internet","to":"alb/demo-alb","kind":"request","label":"HTTP 80","confidence":"derived"}
```

由来部（TF 側。リスナーは辺 2 本に統合された。**正規化（ツール）が出す根拠は `<raw の from>.<raw の path>` で始める**ので、ツールの出力は下のようにインデックス付きになる。正解 IR の手書きの根拠は `aws_lb_listener.http.default_action.target_group_arn` のように短い。比較には使わない）:

```json
{"address":"aws_lb_listener.http","type":"aws_lb_listener","file":"alb.tf","class":"merged_into","rule":"R-LB-LISTENER",
 "into":["alb/demo-alb->ecs_service/demo-app","external/internet->alb/demo-alb"]}
{"edge":"alb/demo-alb->ecs_service/demo-app","rules":["R-LB-LISTENER","R-LB-TG","R-SG"],
 "evidence":["aws_lb_listener.http.default_action[0].target_group_arn","aws_ecs_service.app.load_balancer[0].target_group_arn", "…"]}
```

### 2.4 決定論の保証（C5。ir-schema 6 章）

| 要因 | 保証のしかた |
|---|---|
| 出力の順 | ir-schema 6 章のとおり: `nodes`・`edges` は id 順、`sources.*.resources` は address 順、`sources.*.edges` は edge 順、`spans`・`into`・`rules`・`evidence` は文字列順、キーは辞書順、インデント 2、末尾に改行 1 つ、LF。**書き出しは `validate_ir.py` の `canonical_dump` と同じ関数を使う**（いまは `validate_ir.py` の中。70 行目。`core/ir_norm.py` へ移して両方が使う） |
| 集合の走査順 | `set` を走査して出力に影響させない（`sorted()` を通す）。Python の文字列ハッシュは起動ごとに変わるので、**`PYTHONHASHSEED` を 3 通りに変えて出力が同じことをテストで確かめる** |
| 規則データの読み順 | `data/rules/` のファイルを名前の昇順で読む（OS の列挙順に頼らない。`summaries.py` が要約表でしているのと同じ決まり） |
| ID の重なり | ir-schema 2 章の K-NAME のとおり、重なったリソースを address（TF）／論理 ID（CFN）の辞書順に並べ、2 つ目以降に `.<論理名の key>` を付ける。診断 `NORM-KEY-COLLISION` に残す |
| 環境 | パスは `/` 区切り、ロケール・時刻・乱数・環境変数を読まない。Windows と Ubuntu で同じ（CI の両 OS で確かめる） |
| 入力のキー | ノードの id の key は `name` から作る（`label` からは作らない。省略や日本語化で id が変わらないように） |

---

## 3. 規則データの設計（フェーズ 3 の最初の手順で決める中心）

### 3.1 現在の草案 3 表と問題点

| 表 | 行数 | 中身 | 機械が読んでいるもの |
|---|---|---|---|
| `resource-catalog.md`（81 行） | 描く型 22 行（合成の AZ・external・bedrock_model と `module` を含む）、統合 M-* 9、非表示 H-* 12、入れ子の規則 5（N-AZ・P-*） | 型 ↔ 正規の型名・category・TF／CFN の型・名前属性・アイコン候補 | `validate_ir.py` の `drawable_types()`（91 行目）が「1. 描く型」の表の TF／CFN の列を正規表現で読む。`defined_rules()`（83 行目）が全表の 1 列目の規則 ID を読む（`RULE_ROW`、40 行目） |
| `relation-resources.md`（30 行） | R-* 13 行、補足 5 項目 | 関係リソース → 辺（from → to、kind、ラベル） | 規則 ID だけ |
| `edge-rules.md`（101 行） | E-* 7（E-REF-NONODE は別に 1）、E-NOEDGE-* 7、N-* 2、確信度の表、まとめ方（E-MERGE）、ラベルの書式、E-ENV-REF の kind 表、E-IAM のアクション → kind 表 | 辺の規則・辺にしない参照・合成ノード | 規則 ID だけ |

問題点（根拠つき）:

1. **機械が読むのは規則 ID と「描く型」の型名だけ。** 型の扱い（M-*・H-* の対象型）、E-NOEDGE の属性名、kind の表、R-* の対象型は、すべて散文の中。正規化は、これらを自前で読む必要がある。
2. **範囲が足りない（実測）。** 草案は自作 5 構成の型だけ（resource-catalog.md 3 行目「フェーズ 0 の自作 fixture 5 種に出てくる型だけ」）。主セットの非 data リソース 231 件のうち **67 件（29%）、39 型**が表に無い（CloudFront、Cognito、WAF、EKS、Step Functions、Glue、CloudWatch、EventBridge のルール、API Gateway のレスポンス類、`aws_iam_policy`、`aws_s3_object` など）。公開サンプル 72 入力では 3,290 件のうち 1,196 件（36%）、191 型。主セットは `unknown` 0 件（CRITERIA 1.2 の j）が基準なので、**型の行を約 40 足すのが前提**。
3. **型の判定に条件がある。** `aws_lb`（`load_balancer_type` が application か）、`aws_apigatewayv2_api`（`protocol_type = "HTTP"`）、`aws_security_group_rule`（`type = "egress"` なら H-SG-EGRESS）、`AWS::CloudFormation::Stack`（展開できたら H-NESTED-STACK、黒箱なら `module`）など。表に条件の書き方が無い。
4. **同じ ID を指す説明が 3 か所にまたがる。** 規則 ID は expected IR・validate_ir・文書の 3 者が使う。いまは表の 1 列目が唯一の定義だが、列の構造が無いので「ID はあるが中身は人が読む」状態。
5. **TF と CFN の属性名の違いが散文。** E-NOEDGE の表は「TF と CFN の書き方の両方で照合」と書くだけで、どう揃えるかは未定義。
6. **`validate_ir.py` が規則表を読む場所は `core/paths.py` の `RULE_DOCS`・`RESOURCE_CATALOG`（36・37 行目）。** `doctor.py` の必須ファイル、`tests/architecture/test_skill_entry.py`（77〜82 行）も `references/` の 3 表に依存している。移すとこれらも直す。

### 3.2 設計の原則（案）

- **データ = 何を、コード = どうやって。** 表に置くのは、型 → 扱い、属性名の集合、kind の対応表、2 つの参照を結ぶだけの関係リソース。手続き（SG の組合せ、ルートテーブルの関連付け、リスナー + ターゲットグループ、API Gateway の統合、IAM のポリシー読み）は `normalize/` のハンドラで、**表の行から ID で呼ぶ**。ID ↔ ハンドラの対応をテストで強制する（診断コードの一覧の決まりと同じ。`tests/architecture/test_diagnostics_registry.py` の形）。
- **TF／CFN の属性名は「中立キー」で揃える**（案）: 小文字にして `_` を除く（`cidr_block` と `CidrBlock` は `cidrblock`）。表には TF の snake_case を書けば CFN の CamelCase にも当たる。揃わないもの（CFN の RDS の `VPCSecurityGroups` と TF の `vpc_security_group_ids`、LB の `Type` と `load_balancer_type`）は表に両方を書く（既存の edge-rules.md の E-NOEDGE-SG がすでにそうしている）。
- **表の 1 行 = 1 つの規則 ID（描く型は正規の型名が ID）。** 既存の ID（`R-LB-LISTENER`、`E-NOEDGE-SG`、`H-IAM`…）は、**名前も意味も変えずに引き継ぐ**。足す ID は同じ接頭辞（`H-`・`M-`・`R-`・`E-`・`N-`・`P-`）の命名に従う。使われた ID は、正解 IR・golden・文書が参照するので、**消さない・別の意味に使い回さない**（廃止は `deprecated = true`）。
- **条件は小さく:** `when` は「プロパティの値が集合に入るか」「`via` の値」「`enabled`」だけ（仮定）。これで足りない判定は、`selector` としてコードに出し、ID で束ねる。

### 3.3 配置の案の比較

| 案 | 内容 |
|---|---|
| **A** | 種類別の表を TOML で（`types/<領域>.toml`、`relations.toml`、`edges.toml`、`refs.toml`）。1 行 = 1 つの `[[…]]` ブロック。標準ライブラリ `tomllib`（Python 3.12）だけで読む。領域別に分けて 1 ファイルを 400 行以下に |
| **A′** | A の YAML 版（PyYAML を使う） |
| **B** | 型ごとに 1 ファイル（`types/alb.toml` …。数百ファイルになる） |
| **C** | Markdown の表を今のまま、パーサで読む（`validate_ir.py` が 1 列目だけ読んでいるのを広げる） |

| 評価軸 | A（TOML・種類別） | A′（YAML） | B（型ごと） | C（Markdown の表） |
|---|---|---|---|---|
| レビューしやすさ | ○ コメントが書ける。1 行 1 フィールドで差分が行単位。ブロックが長くなる | ○ 一覧性は最も高い | △ 型の横断（TF／CFN の対応の確認）がしにくい。関係リソース・辺の規則は型をまたぐので置き場が無い | ○ GitHub でそのまま読める。ただし条件・統合先の指定のような構造が表のセルに入りにくい |
| PEP 723 の依存 | ○ なし（`dependencies = []`）。PEP 723 を固定する対象が増えない | △ `PyYAML==6.0.3`（`adapt_cfn.py` と同じ版）。入口が 1 つ依存を持つ | ○ なし | ○ なし |
| 落とし穴 | 少ない。文字列は引用符が要る | **YAML 1.1 の真偽値（`on`・`yes`・`no` が bool になる）**。CFN の読み込みで実際に対策を入れた問題（07-raw-output.md の A4（CFN）の記述）と同じものを、規則データに持ち込む | 少ない | セルの区切り `|` や `` ` `` の扱いが壊れやすい（既存の正規表現 `RULE_ROW` は 1 列目だけ） |
| 差分（git） | ○ 1 規則の追加は 1 ブロックの追加 | ○ | ○ | △ 表の幅が変わると行全体が変わる |
| ID の安定 | ○ `id` が必須キー。重複・形式をローダーで検査 | ○ | ○（ファイル名 = 型名） | △ 1 列目の約束だけ（今と同じ） |
| `validate_ir.py` との整合 | ○ `core/rules.py` が読み、`validate_ir.py`・`normalize/` が同じ関数を使う（表を 2 か所で読まない）。`drawable_types()` と `defined_rules()` を置き換える | ○ 同じ | ○ | △ 今の正規表現を広げ続ける |
| `docs/spec` との二重管理 | ○ データは表のみ、説明は `docs/spec/rules/*.md`。**表の一覧は `tools/render_rules.py` で生成し、生成物と一致することをテストする**。ID は両方にあることをテストで確かめる | ○ 同じ | ○ 同じ | ◎ 表と説明が 1 つ（ただし機械向けの構造を足すほど散文が減る） |
| 複雑な規則の表現 | ○ `shape = "pair"`（データだけ）と `handler`（コード）を 1 行で選べる | ○ | △ | × 手続きは別途コード |
| 移行コスト | 中（3 表 → TOML の機械的な変換 + 検証） | 中 | 大 | 小 |

**推奨: A（TOML、領域別のファイル）。** 理由: ① PLAN 1.4 の 2 が「規則表の説明は `docs/spec/` へ、データは `data/rules/` へ」と決めている（122 行）。説明と表を別のものにする方針に素直。② `tomllib` が標準なので PEP 723 の固定対象が増えず、YAML 1.1 の真偽値の罠が無い。③ 領域別のファイルは「1 ファイル 1 単位」（PLAN 1.4 の 2）と、要約表（`module-summaries/<モジュール>/v<major>.md`）の置き方に合う。④ 複雑な規則を `handler` で束ねられるので、データで書けるところは行を足すだけで済む（PLAN 1.4 の 5）。YAML（A′）でも成り立つが、真偽値の罠への対策が要る。Markdown（C）は小さい移行で済むが、フェーズ 3 で足す約 40 型の条件や統合先を表のセルに書くと、パーサの方が先に壊れる。

TOML の欠点: 配列の入れ子が冗長（1 行に収める書き方なら差分は読みやすい）。TOML 1.0 の inline table は 1 行にしか書けない（長くなる行は `[[type]]` の通常のテーブルに戻す）。

### 3.4 ファイル構成（案）

```
skills/aws-iac-diagram/data/rules/
├── README.md                # 読み方（SKILL の中。短く）
├── types/                   # 型 → 扱い（描く／統合／非表示）。TF と CFN の型を 1 行に並べる
│   ├── network.toml  compute.toml  data-stores.toml  integration.toml  edge-web.toml  ai-analytics.toml
│   └── merged-and-hidden.toml   # M-*・H-*
├── relations.toml           # R-*（関係リソース → 辺）
├── edges.toml               # E-ENV-*・E-IAM・E-KB・E-BEDROCK・E-MERGE の優先順・kind の表・ラベルの書式・N-*（合成ノード）
├── refs.toml                # E-NOEDGE-*・E-REF-NONODE（属性名の集合）
└── placement.toml           # N-AZ・P-*（入れ子）、attrs の取り方
docs/spec/rules/             # 説明（SKILL の外）。規則 ID ごとの「なぜ」。表は tools/render_rules.py が生成（rules-table.md）
```

`core/paths.py` に定数を足し、`doctor.py` の `REQUIRED_FILES` と `tests/architecture/test_doctor_required_files.py` の `RUNTIME_DATA` に足す（拡張のしかた「同梱のデータを足す・動かす」の決まり）。移し終えたら `references/` の 3 表と `RULE_DOCS` を消す。

### 3.5 規則の ID 体系と列

ID は既存のまま（接頭辞が `class` を決める。ローダーが検査）: `H-`（hidden）、`M-`（merged_into。into はノード）、`R-`（merged_into。into は辺）、`E-`（辺の規則）、`N-`（合成ノード）、`P-`（入れ子）。描く型の ID は正規の型名（`alb`、`subnet`。ノードの id の接頭辞と同じ）。

| 表 | 列（案） | 草案の列との対応 |
|---|---|---|
| `[[type]]` 描く | `id`、`class = "drawn"`、`category`（resource／group／external）、`tf`・`cfn`（入力の型の配列）、`when`（条件。省略可）、`name_attr`（B3 の 2 番目。TF／CFN の属性名）、`icon`（アイコンのキー。フェーズ 4 で使う）、`parent`（`P-VPC`／`P-SUBNET`／`P-SPANS`／`P-REGIONAL`／`N-AZ`）、`attrs`（`cidr`・`access`・`endpoint_type`・`service` の取り方） | 「1. 描く型」の表の全列 |
| `[[type]]` 統合・非表示 | `id`（規則 ID）、`class`（`merged_into`／`hidden`）、`tf`・`cfn`、`when`、`into`（M-* だけ。統合先の選び方）、`refs_as_target`（統合したリソースの中の参照を統合先の参照として扱う。M-ECS-TASKDEF）、`module_source_prefix`（H-IAM だけ）、`evidence_source`（E-IAM の材料にする。H-IAM）、`reason`（1 行） | 「2. 統合」「3. 非表示」の表 |
| `[[relation]]` | `id`、`shape`（`pair` = データだけで辺を作る／`handler` = コード）、`tf`・`cfn`、`from`・`to`（参照の属性名。`pair` のとき）、`direction`（A2）、`kind`、`label`、`confidence`（`derived` が基本）、`handler`、`sam`（SAM の `Events` の型。リソースではないので網羅分類には出ない） | relation-resources.md の列 |
| `[[noedge]]` | `id`、`attrs`（中立キーに揃う属性名）、`use`（代わりに使うところ） | edge-rules.md の E-NOEDGE-* の表 |
| `[[ref_rule]]`（E-ENV-REF・E-KB-STORAGE・E-BEDROCK-EMBEDDING のような、属性の参照から辺を作る規則） | `id`、`from_types`、`path`（位置の指定。`environment` など。下の注）、`to_types`、`kind_by_target`（参照先の型 → kind）、`confidence` | edge-rules.md の 2 章の表と kind の表 |
| `[kind_by_target]`、`[iam_action_kind]`、`[merge_priority]`、`[label_format]` | 対応表 | edge-rules.md の各表 |

注（実データから）: E-ENV-REF は「環境変数の値」だが、raw の位置は TF の ECS で `container_definitions[0].environment[0].value`（`$json` の中。変数名 `DB_HOST` は位置に入らず、兄弟の `name` に入る）、Lambda で `environment[0].variables.TABLE_NAME`（実測）、CFN で `Properties.Environment.Variables.KEY` など形が違う。**`path` は「中立キーの並びにマッチするパターン」（`*` と `**` 付き）で書く**（仮定。`environment/variables/**`、`containerdefinitions/environment/value`）。

### 3.6 サンプル行（案。TOML として構文を確かめた）

```toml
# types/network.toml ─ 描く型（入れ子は N-AZ。access はルートから決める）
[[type]]
id = "subnet"
class = "drawn"
category = "group"
tf = ["aws_subnet"]
cfn = ["AWS::EC2::Subnet"]
name_attr = {}                                  # タグのみ
icon = "group:public_subnet"                    # attrs.access が private なら group:private_subnet
parent = "N-AZ"
attrs = { cidr = "cidr_block", access = "@route" }   # @route = R-ROUTE の結果から決める

# types/network.toml ─ 条件つき（aws_lb は application だけ。省略時も application）
[[type]]
id = "alb"
class = "drawn"
category = "resource"
tf = ["aws_lb", "aws_alb"]
cfn = ["AWS::ElasticLoadBalancingV2::LoadBalancer"]
when = { prop = { tf = "load_balancer_type", cfn = "Type" }, in = ["application"], default = "application" }
name_attr = { tf = "name", cfn = "Name" }
icon = "shape:application_load_balancer"
parent = "P-SPANS"

# types/edge-web.toml ─ 草案に無い型を足す例（C01・C02 に出る。アイコンのキーは辞書で確かめる）
[[type]]
id = "cloudfront_distribution"
class = "drawn"
category = "resource"
tf = ["aws_cloudfront_distribution"]
cfn = ["AWS::CloudFront::Distribution"]
name_attr = {}
icon = "resource_icon:cloudfront"
parent = "P-REGIONAL"

# types/merged-and-hidden.toml ─ 統合（into が統合先の選び方。タスク定義を参照するサービスへ）
[[type]]
id = "M-ECS-TASKDEF"
class = "merged_into"
tf = ["aws_ecs_task_definition"]
cfn = ["AWS::ECS::TaskDefinition"]
into = { by = "referenced_by", attr = ["task_definition", "TaskDefinition"], node_type = "ecs_service" }
refs_as_target = true                           # 中の参照は統合先のサービスの参照として扱う

# 統合（TF だけの設定リソース。自分が参照するバケットへ）
[[type]]
id = "M-S3-CONFIG"
class = "merged_into"
tf = ["aws_s3_bucket_versioning", "aws_s3_bucket_public_access_block", "aws_s3_bucket_policy"]
cfn = []
into = { by = "ref", attr = ["bucket"], node_type = "s3_bucket" }

# 非表示（IAM。モジュールの source の前方一致も同じ ID。E-IAM の材料にする）
[[type]]
id = "H-IAM"
class = "hidden"
tf = ["aws_iam_role", "aws_iam_role_policy", "aws_iam_policy", "aws_iam_openid_connect_provider"]
cfn = ["AWS::IAM::Role", "AWS::IAM::Policy"]
module_source_prefix = ["terraform-aws-modules/iam/aws"]
evidence_source = true

# relations.toml ─ データだけの関係リソース（2 つの参照を結ぶ。A2: 向きはデータの流れ）
[[relation]]
id = "R-LAMBDA-ESM"
shape = "pair"
tf = ["aws_lambda_event_source_mapping"]
cfn = ["AWS::Lambda::EventSourceMapping"]
from = ["event_source_arn", "EventSourceArn"]    # ポーリングされる側が from（関数がポーリングするが、向きはデータの流れ）
to = ["function_name", "FunctionName"]
kind = "event"
label = ""
confidence = "derived"

# relations.toml ─ 手続きは handler（normalize/sg.py）。表には対象の型と kind だけ
[[relation]]
id = "R-SG"
shape = "handler"
handler = "sg"
tf = ["aws_security_group", "aws_security_group_rule", "aws_vpc_security_group_ingress_rule"]
cfn = ["AWS::EC2::SecurityGroup", "AWS::EC2::SecurityGroupIngress"]
kind = "network"
confidence = "derived"

# refs.toml ─ 辺にしない参照（属性名は中立キーに揃う。vpc_id は VpcId にも当たる）
[[noedge]]
id = "E-NOEDGE-PLACEMENT"
attrs = ["vpc_id", "subnet_id", "subnet_ids", "subnets", "availability_zone", "db_subnet_group_name"]
use = "P-*"
```

---

## 4. 正規化のパイプライン

### 4.1 段階

| 段階 | 入力 | 出力 | 使う規則表 | 要点 |
|---|---|---|---|---|
| 0 読み込み | raw IR（スキーマと `ir_raw.semantic_errors` で検査済み）、規則データ | 中立キーに揃えたリソースの一覧、参照の索引（from 別・to 別）、型の索引 | 全部（ローダー） | 規則データ自体の検査（ID の重複、型の重複、`class` と接頭辞、ハンドラの有無） |
| 1 仮分類（A6／X4） | リソース | 各リソースに「仮の class・規則」を 1 つだけ付ける（漏れ 0・重複 0 が構造上保証される） | `types/*.toml`、`relations.toml` | ① `enabled: false` → `hidden`／`H-COND-FALSE`（型に先立つ。three-tier の `aws_instance.bastion`）。② 黒箱（`via: module_blackbox`）→ IAM だけのモジュールなら `hidden`／`H-IAM`、それ以外は `drawn`（型 `module`）。③ 型の表を `when` つきで引く（0 行 → `unknown`、2 行以上 → ローダーが拒否）。④ TF の `data` は `H-DATA`（既存インフラを描く規則は 8 章の 3） |
| 2 ノード化（N） | `drawn` と仮分類されたもの | ノード（id・type・category・name・label・attrs・multiplicity）。ID の重なりの解決 | `types/*.toml`（`name_attr`、`attrs`） | B3: `Name` タグ → 型ごとの名前属性 → 論理名（K-NAME）。評価できない値（`$unknown`・`$concat` に `$res` を含む）は次の候補に落とす（`NORM-NAME-FALLBACK`）。×N は `multiplicity: "N"` |
| 3 辺（E） | 参照の索引、仮分類、ノード | 辺の候補 → E-MERGE で 1 組 1 本に → 辺。**ここで M-*・R-*・H-SG-NOEDGE・H-RT-NOROUTE の分類を確定**する（辺ができたかで決まるため）。辺の根拠（rules・evidence） | `relations.toml`、`edges.toml`、`refs.toml` | 3a 参照の会計（1.8）: 全 `active` 参照（DependsOn を除く）に 4 つの分類のどれか。3b R-*。3c E-ENV-REF・E-KB-STORAGE・E-BEDROCK-EMBEDDING。3d R-SG・N-EXT-INTERNET。3e E-IAM・E-ENV-STR（推定）と E-IAM-SUPPRESS。3f 黒箱の入力・出力の辺。3g E-MERGE（確信度は強い方、kind は優先順、ラベルの結合） |
| 4 入れ子（P） | ノード、参照（`vpc_id`・`subnet_id(s)`・`availability_zone`・Lambda の VPC 設定、黒箱の入力） | parent・spans、AZ ノード（N-AZ）、サブネットの `attrs.access`（R-ROUTE の結果から） | `placement.toml` | P-VPC／P-SUBNET／P-SPANS／P-REGIONAL。`spans` の `parent` は最も近い共通の祖先。AZ が静的に決まらなければ `az<N>`、`"*"` は AZ ノードを作らない（ir-schema 2 章） |
| 5 ラベル（B3） | ノード・辺 | `label`（いまはノードの `label` = `name`、合成ノードは固定。辺のラベルは段階 3 で規則の書式から作る） | `edges.toml` の `label_format` | 省略規則・日本語は 8 章の 5 |
| 6 検証 | normalized IR | OK／エラー | — | `validate_ir.py`（スキーマ + 参照の整合 + 出力の形）+ 正規化自身の検査（入力の全リソースが `sources` にちょうど 1 回、全 `active` 参照が 4 分類のどれか）。X4 は別に `tools/check_coverage.py`（入力を独立に数える）で照合（CRITERIA 1.5） |

**仮分類と確定の分離（設計の中心）:** `M-*` は統合先のノードが決まって初めて確定し、統合先が見つからなければ `hidden`（案: 新しい ID `H-NO-TARGET`。診断 `NORM-MERGE-TARGET`）に落とす。`R-*` は辺ができて初めて `merged_into`、できなければ規則どおりの `hidden`（`R-SG` → `H-SG-NOEDGE`、`R-ROUTE` → `H-RT-NOROUTE`、`R-LAMBDA-PERMISSION` で相手が見つからなければ `H-IAM`）。この確定を 1 か所（`classify.finalize()`）に集める。

### 4.2 既存のデータの扱い

| raw の情報 | 扱い |
|---|---|
| `state` | `active` だけを辺・入れ子・会計の対象にする。`pruned`（`Fn::If` の選ばれなかった側）と `unevaluated`（`$unknown` の中、plan 由来）は使わず、リソースごとに件数を `NORM-INACTIVE-REF`（info）に残す（案。8 章の 7 で扱いを確認） |
| `through`（モジュールの出力・変数、ネストスタックの出力・パラメータ） | `to` は元のリソースへ解決済みなので辺の計算には使わない。根拠の説明（` (via module.app.output.security_group_id)`）にだけ使う。`confirmed` のまま（edge-rules.md の確信度の表） |
| `enabled: null`（count・条件が決まらない） | 描く（ir-schema 7.2）。`NORM-COND-UNKNOWN`（warn）。×N は `multiplicity: "N"`、address は `[*]` |
| `$unknown`（props の中） | その属性を持たない値として扱う（名前の候補から落とす、条件に使わない）。`TF-UNEVALUATED` などの raw の診断は raw に残る。例: three-tier の CFN の `Bastion.ImageId`（SSM パラメータ）、rag の `aws_api_gateway_deployment.api.triggers.redeployment`（`sha1()`）— どちらも図に影響しない |
| `$pseudo`・`$az` | `$az` は AZ ノードの `az<N>`（ir-schema 2 章）。`$pseudo` は ARN の照合（N-BEDROCK-MODEL の `arn:aws:bedrock:<region>::foundation-model/<id>`）にだけ使う |
| `via: module_summary` | 通常のリソース。`sources.resources` の `via` に写す。ノードにはしない特別扱いは無い（要約表が展開した結果なので、`aws_vpc.this[0]` はふつうの VPC） |
| `via: module_blackbox` | 4.3 |
| `via: nested_stack`（CFN の子） | 通常のリソース。親の `AWS::CloudFormation::Stack` は H-NESTED-STACK で hidden |
| `implicit: true`（SAM の暗黙の API） | 通常のリソース（`AWS::Serverless::Api` 扱い） |
| `multiplicity`／count・for_each | 決まる値はインスタンスごとに別ノード（address の `[0]`・`["ssm"]`）。決まらないものは ×N（ir-schema 2 章の置き場の規則）。K-NAME のインデックスは名前の `-0` |
| `provider`・`region` | 別リージョンの扱い（`region` の値で見分ける）は 8 章の末尾（フェーズ 3 では描き分けない案） |
| `lifecycle.replace_triggered_by`・`provisioner` | 辺にしない（raw に出ていない。WORKLOG 714 行の持ち越しを「しない」で閉じる案） |

### 4.3 モジュール

| 入力 | 扱い（ir-schema 2 章・4 章） |
|---|---|
| 要約表で展開したレジストリモジュール（`via: module_summary`） | 通常のリソースとして段階 1〜4 に流す。K-NAME の論理名は `<モジュールのパス>.<リソース名>`（`vpc.this`） |
| ローカルモジュール | 同上（`module` フィールドが前につく）。count が 0 の呼び出しの中は `enabled: false` → `H-COND-FALSE` |
| 黒箱（`terraform-aws-modules/kms/aws`、`aws-ia/*`、`git::`、読めない子テンプレート） | `drawn`／`via: module_blackbox`、ノード `module/<名前>`。`attrs.module_source`・`module_version`。入力（`props`）が指すサブネット・VPC から入れ子（P-SUBNET／P-SPANS／VPC）、辺は `inferred`（モジュール → 入力に渡したノード、参照した側 → モジュール）。**T16 の `module.eks.module.kms` と `module.irsa-ebs-csi` を実測した**（`module.irsa-ebs-csi` の source は `terraform-aws-modules/iam/aws//modules/iam-assumable-role-with-oidc`） |
| **H-IAM（IAM だけのモジュール）** | raw は黒箱の呼び出しのまま出す（中身を読まないため）。正規化の段階 1 で `hidden`／`H-IAM`。判定 `iam_only()`（`adapters/terraform/modules/summaries.py` の 214 行目。`data/module-summaries/iam-only-sources.md` を読む）は adapters の中にあり、**`normalize` は `core` しか import できない**（PLAN 1.4 の 4、architecture.md の 3）。→ `iam_only()` を `core/module_sources.py` へ移し、アダプタ（診断の文言に使う）と正規化の両方が使う。出力は変わらない（golden 101/101 で確かめる）。8 章の 4 |
| `AWS::CloudFormation::Stack`（CFN） | 子を展開できたら H-NESTED-STACK（hidden）、できなければ `module`（黒箱）。**同じ入力の型が `via` で扱いが変わる**ので、`when` は `via` を見られるようにする |
| `create = false` の黒箱 | アダプタが `enabled: false` にする → H-COND-FALSE |

### 4.4 TF と CFN の差を吸収する箇所

| 差 | 吸収する箇所 |
|---|---|
| 入力の型の名前 | 型の表の `tf`／`cfn`（段階 1）。SAM の `AWS::Serverless::Function` は `lambda_function` と同じ行、`AWS::Serverless::SimpleTable` は `dynamodb_table` |
| 属性名（snake_case／CamelCase）、`Tags`（TF は map、CFN は `Key`／`Value` のリスト） | 中立キーのビュー（`normalize/view.py`）。`Name` タグの読み出しは 1 つの関数 |
| 設定が別リソースか、プロパティか（S3 の設定、ルート、SG のルール） | M-S3-CONFIG は TF だけに行がある。R-ROUTE・R-SG のハンドラは両方の形（独立リソースとインラインのブロック）を読む |
| 関係がプロパティになる（SAM の `Events`、`AWS::S3::Bucket.NotificationConfiguration`） | `relation` の `sam` と CFN 用の分岐（網羅分類には出ず、辺の根拠にだけ出る。relation-resources.md の冒頭） |
| IGW の接続（CFN の `VPCGatewayAttachment` ↔ TF の `aws_internet_gateway.vpc_id`） | M-IGW-ATTACH（CFN だけ）。入れ子は `P-VPC` が両方から VPC を決める |
| ネストスタックとモジュール | どちらも raw で解決済み（`through`）。差はノード id の論理名だけ |
| 論理名と TF の名前 | K-NAME の 3 番目は TF と CFN で違う。**Name タグ・名前属性が付いたものは一致する**（fixture は描くものすべてに名前を付けてある） |

---

## 5. パッケージ構成案

### 5.1 `aws_iac_diagram/normalize/`（`core` だけを import）

行数は目安（1 ファイル 800 行以下、`tests/architecture/test_file_size.py` は 1,500 行超で失敗）。

| ファイル | 役割 | 行数の見込み |
|---|---|---|
| `build.py` | `normalize(raw, rules, name) -> dict`。段階の順序の組み立て | 200 |
| `view.py` | 中立キーのビュー（props、`Tags`、`Name`、参照のパスの正規化と、パターンのマッチ） | 250 |
| `classify.py` | 段階 1 の仮分類、`finalize()`、`unknown` | 300 |
| `names.py` | B3・K-NAME・ID の重なりの解決 | 250 |
| `nodes.py` | ノード（attrs、×N、黒箱） | 350 |
| `refs.py` | 参照の会計（1.8）、E-NOEDGE-*、E-REF-NONODE、根拠の文字列 | 300 |
| `edges.py` | 辺の候補の集約、E-MERGE、A2・A3、`pair` の関係 | 350 |
| `relations_lb.py`・`relations_api.py`・`relations_route.py`・`relations_events.py` | R-LB-*、R-APIGW-*、R-ROUTE・R-VPCE-GATEWAY、R-LAMBDA-*・R-SNS・R-S3・R-SQS・R-BEDROCK（ハンドラ） | 各 200〜350 |
| `sg.py` | R-SG（SG → 付いたリソース、internet への公開） | 300 |
| `iam.py` | E-IAM・E-ENV-STR・E-IAM-SUPPRESS（ポリシー文書の `$json` を歩く） | 400 |
| `synthetic.py` | N-EXT-INTERNET・N-BEDROCK-MODEL | 150 |
| `nesting.py` | P-*・N-AZ・`access` | 300 |
| `output.py` | `evaluation`・`sources`・`diagnostics` の組み立て | 250 |
| `registry.py` | 規則 ID → ハンドラ（デコレータ） | 60 |

合計 4,000 行前後の見込み（仮定）。層の中の順序は、アダプタの `TERRAFORM_GROUPS`・`INTRA_TERRAFORM`（`tests/support/arch_layers.py`）と同じ決まりで `NORMALIZE_GROUPS` を足す（`view` → `classify`・`names` → `nodes`・`refs` → `relations_*`・`sg`・`iam`・`synthetic` → `edges` → `nesting` → `output` → `build`。後の段階が前を import し、逆は不可）。

`core` に足すもの: `core/rules.py`（ローダー、中立キー、型・ID の索引、検査。標準ライブラリだけ。`validate_ir.py` も使う）、`core/ir_norm.py`（`canonical_dump`・`canonical_part` を `validate_ir.py` から移す）、`core/module_sources.py`（`iam_only()`）。依存の表（`ALLOWED`）は変えない（`normalize` → `core`）。

### 5.2 入口（案）

`scripts/normalize_ir.py`（PEP 723: `dependencies = []`。TOML を標準で読むので依存なし）。

```
uv run "<SKILL>/scripts/normalize_ir.py" --input <raw IR の JSON> --out <normalized IR の JSON> [--name <名前>]
```

PLAN 1.3 の決まりどおり、結果はファイル、標準出力に頼らない。終了コードは（手順 3b で実装したもの）0 = 書けて、網羅分類（入力の全リソースが `sources` に 1 回ずつ）に問題が無く、仮の分類（`into` が空の R-*・統合先の見つからない M-*）も無い、1 = 書けたが、そのどちらかがある（辺の段階〈手順 4〉までは、関係リソースのある入力は必ず 1）、2 = 書けなかった（入力を読めない・raw IR でない・raw IR の検査に通らない・**規則表の検査の失敗**・出力を書けない・想定外の失敗）。0 は `validate_ir.py` に通ることまでは意味しない（スキーマと参照の整合の全部は `validate_ir.py` が見る）。`SKILL.md` の「動くスクリプト」に 1 行足す（`test_skill_entry.py` が書き忘れを失敗にする）。フェーズ 6 の `diagram.py` は、同じ関数（`normalize.build.normalize`）を直接呼ぶ。

### 5.3 診断コード（`NORM-`）

`core/diagnostics.py` の表（`PREFIXES`・`ALLOWED_PREFIXES` に `NORM` を足す）と、ir-schema の新しい章に書く（章・節の番号は変えないので、**10 章を最後に足す**。8 章の「`NORM-…` の一覧はフェーズ 3 で決める」の行は、10 章を指すように書き換える）。`tests/architecture/test_diagnostics_registry.py`・`test_diagnostics.py` の範囲を `normalize/` と `normalize_ir.py` に広げる（コメントにすでに予告がある）。

| code | level | 内容 |
|---|---|---|
| `NORM-UNUSED-REF` | info | 使わなかった参照（1.8 の 4。address = from、path = raw の path、message に to と attr）。edge-rules.md の記述どおり |
| `NORM-COND-UNKNOWN` | warn | `enabled: null` のリソースを描いた（ir-schema 7.2） |
| `NORM-MERGE-TARGET` | warn | M-* の統合先が見つからず `H-NO-TARGET` にした |
| `NORM-NAME-FALLBACK` | info | 名前が論理名に落ちた（B3 の 3 番目） |
| `NORM-KEY-COLLISION` | info | ノード id の重なりを解いた（K-NAME） |
| `NORM-PLACEMENT` | warn | サブネット・VPC が決まらず parent を VPC／null にした（×N のサブネットなど） |
| `NORM-AZ-UNKNOWN` | info | AZ が静的に決まらず（`"*"`）AZ ノードを作らなかった |
| `NORM-INACTIVE-REF` | info | `pruned`・`unevaluated` の参照を使わなかった（リソースごとに件数） |
| `NORM-RAW-ERROR` | warn | raw に `error` の診断があり、読めなかった入力がある |

`unknown` のリソースは診断にしない（`sources.resources` の `class: unknown` から件数と型が分かるので重複する。ir-schema 4 章のとおり件数と型は `result.json`・`coverage.md` に出す）。

### 5.4 ほかの更新

| 対象 | 更新 |
|---|---|
| `doctor.py` の `REQUIRED_FILES`、`test_doctor_required_files.py` の `RUNTIME_DATA` | `data/rules/**`、`normalize_ir.py`、`normalize/*.py` を足し、`references/` の 3 表を外す |
| `core/paths.py` | `RULES_DIR` などを足し、`RULE_DOCS`・`RESOURCE_CATALOG` を消す |
| `references/` | 規則表を移した後は README だけ。`test_skill_entry.py` の 77〜82 行（references/ の中身の検査）を直す。README は、フェーズ 6 の手順書（`workflow/`）ができるまで短い案内にする |
| `docs/architecture.md` | 層の表の `normalize` を埋め、拡張のしかた「型の扱いを足す」を `data/rules/` に書き換え、`normalize` の中の順序の表（`NORMALIZE_GROUPS`）を足す |
| `docs/spec/` | `rules/`（規則 ID ごとの説明）を足す。ir-schema の 8 章の「決めなかったこと」を更新し、10 章を足す |
| PLAN・HANDOFF・WORKLOG | 完了のたびに更新（既存の運用） |

### 5.5 golden への追加方針

既存の golden は **raw IR のバイト固定**（101 ケース）で、アダプタを動かさない変更（正規化の追加）では変わらない。足すもの:

- `tests/golden/manifest_normalized.json`（新規）。ケース = 既存のアダプタのケースの raw IR を入力に、`normalize_ir.py` を通した出力の SHA-256。**入力の対応:** 自作の fixture（TF・CFN、10 ケース。dev／prod の変数違いの TF 2 つを含む）、主セット 12、TF の公開サンプルのルート 52、CFN の公開サンプル 20 など、合計 90 前後。raw と normalized の両方を同じ道具（`golden.py --stage normalized`）で扱い、**規則表を変えたら normalized の hash が変わるのは正しい**（意図した変更なので `--update --accept-changes`、理由をコミットに書く。既存の決まり）。
- 規則表の変更で何が変わったかを見るための意味の差（ノード・辺の追加と削除）を出す `golden.py --diff <名前>`（案）。hash だけでは review できないため。
- `tests/golden/test_golden.py` の既存のテスト（raw の 101）は変えない。

---

## 6. 手順分割案

各手順は Phase 1・2 と同じ: **実装 → 動作確認 → 第三者レビュー → 指摘の修正 → main**。規模は相対（S < M < L < XL。XL は 1 手順の中で大きい）。

| # | 範囲 | 成果物 | 完了条件 | 主なリスク | 規模 |
|---|---|---|---|---|---|
| 1 | **規則データ化（動きを変えない）** | `data/rules/**`（草案 3 表を機械的に移したもの。ID・型・意味は同じ）、`core/rules.py`・`core/ir_norm.py`・`core/module_sources.py`、`validate_ir.py` の付け替え、`docs/spec/rules/`、`tools/render_rules.py`、パス・doctor・テストの更新 | 6.1 に詳細 | 移行での取りこぼし、`references/` を前提にしたテスト・文書の更新漏れ | M |
| 2 | **規則表の拡張（主セットの型）と凍結** | 主セットで `unknown` が 0 になる型の行（約 40 型）。8 章の 3・4 の決定を規則にする（既存インフラの `data`、黒箱の描き方）。規則表のバージョンを凍結（コミット）し、**ここから主セットの正解 IR の作成（別のサブエージェント）を始める** | 主セット 12 入力の raw IR の全リソースが型の表のどれかに入る（実測で `unknown` 0）。`render_rules.py` の生成物が一致。各行に TF／CFN の型の重複が無い | 型の扱いの判断が多い（描く／統合／非表示）。**ここを決める前に正解 IR を書かせると、規則に無い判断が `note` だらけになる**（CRITERIA 1.2 の書き方） | M |
| 3 | **骨組み・分類・ノード・入れ子（段階 0・1・2・4・5・6）と比較ツール** | `normalize/`（`build`・`view`・`classify`・`names`・`nodes`・`nesting`・`output`）、`normalize_ir.py`、`tools/compare_ir.py`（7 章）、`check_coverage.py` の対象を生成した IR に広げる | 自作 10 入力で N・P・C・名前が 1.0（辺以外）。X4 が 0。`validate_ir.py` が通る | K-NAME と TF／CFN の揃え、AZ の挿入、`access`（R-ROUTE に依存するので辺と同じ手順の前後関係に注意） | L |
| 4 | **辺 その 1（直接の参照と関係リソース）** | `refs`・`edges`・`relations_*`（R-LB・R-APIGW・R-ROUTE・R-VPCE・R-LAMBDA・R-SNS・R-S3・R-BEDROCK・R-SQS）、E-ENV-REF・E-KB-STORAGE・E-BEDROCK-EMBEDDING、E-MERGE、1.8 の会計 | 自作 10 入力で辺のうち、SG・internet・IAM 以外が 1.0。`NORM-UNUSED-REF` が自作で 0（または一覧化した理由つきの数） | 向き（A2）、ラベルの結合（E-MERGE）、SAM の `Events` とプロパティの関係、根拠の文字列が `<from>.<path>` で始まること | L |
| 5 | **辺 その 2（SG・internet・推定）= 自作 5 構成の完了** | `sg`・`synthetic`・`iam`、E-IAM・E-ENV-STR・E-IAM-SUPPRESS、黒箱の辺 | **CRITERIA 1.1 のすべて**（a・b・c）。TF／CFN の canonical のバイト一致。X1〜X4 が 0 | 推定の辺の精度（IAM の Resource の ARN の解釈）、SG の組合せ爆発、`N-EXT-INTERNET` の条件 | L |
| 6 | **公開サンプル: 主セットの測定、対の比較、補助セット** | 主セットの正解 IR（手順 2 以降に別のサブエージェントが作成・別のサブエージェントがレビュー済み）の比較、「許す違いの一覧」（対ごと）、補助セットと全公開サンプルの X4・1.8・`unknown` の一覧 | CRITERIA 1.2（d〜k）、1.4（n）、6 章（m）、1.8（l） | 正解 IR の誤りと規則の誤りの切り分け、規則表の調整が「結果を見てから緩める」にならないようにする（記録を残す） | L |
| 7 | **仕上げ** | `golden`（normalized）、文書（ir-schema 8・10 章、architecture.md、PLAN、HANDOFF、WORKLOG、SKILL.md）、CI の確認（両 OS）、実行時間の測定、`NORM-UNUSED-REF` の内訳の確認 | 完了基準（1 章）を満たす。両 OS の CI が通る。レビューを受けて main | 文書とコードの食い違い | S〜M |

並行できるもの: 手順 2 の凍結後は、**正解 IR の作成・レビュー（サブエージェント）**を手順 3〜5 の実装と並行して進められる。`compare_ir.py` は手順 1 の後からでも作れる（正解 IR は自作 5 つが既にある）。

### 6.1 手順 1（規則データ化）の詳細

**狙い:** 規則を機械が読む形にし、`validate_ir.py` の規則の読み方を置き換える。**動きを変えない**ことを前後で確かめられる形にする（フェーズ 2b と同じ進め方）。

**やること**

1. 形式をユーザーが決める（3.3 の推奨は A。TOML）。
2. `data/rules/` のファイルと、`core/rules.py`（読み込み・索引・検査）。検査: ID の形式と重複、`class` と ID の接頭辞（`H-`↔hidden、`M-`／`R-`↔merged_into、描く型は接頭辞なし）、入力の型が複数の行に当たらない（`when` を考えて）、`into`・`handler`・`module_source_prefix` などの値の形、読む順序が名前順、中立キーの重複（`E-NOEDGE-*` の中で同じキーが 2 回）。
3. 草案 3 表の移行。**検証用の同値テスト:** 移行の前後で次が同じ — `validate_ir.defined_rules()` の ID の集合、`drawable_types()` の入力の型 → 正規の型名の対応、M-*・H-*・R-* の対象の型の集合（古い表を正規表現で読む検査用の関数をテストにだけ残し、移行後に消す）。表の内容は人が読み替えず、変換スクリプト（1 回限り。リポジトリには残さない）で作り、差分を目で確かめる。
4. `validate_ir.py` を `core/rules.py` に付け替える（`defined_rules`・`drawable_types`）。`canonical_dump`・`canonical_part`・`_sort_lists` を `core/ir_norm.py` へ移す（`--same-canonical` の動きは同じ）。
5. `iam_only()` を `core/module_sources.py` へ移し、アダプタ（`modules/resolve.py`）が使う。**raw の出力は 1 バイトも変わらない**（golden 101/101）。
6. `core/paths.py`・`doctor.py`・`RUNTIME_DATA`・`test_skill_entry.py` を直し、`references/` の 3 表と `RULE_DOCS` を消す。`docs/spec/rules/` に説明を移し、`tools/render_rules.py` と生成物の一致のテストを足す。
7. 文書（architecture.md の層・拡張のしかた、PLAN の構成図、README、HANDOFF、WORKLOG）。

**完了条件:** ① 既存のテストがすべて通る（437 件 + 新しいテスト）。② `golden.py` が 101/101（raw が変わらない）。③ 5 つの正解 IR が `validate_ir.py` を通る（同じ結果）。④ 同値テストが通る。⑤ ID の重複・型の重複・接頭辞の不整合をわざと作ると落ちる（変異で確かめる）。⑥ 両 OS の CI。⑦ 第三者レビュー。

**リスク:** ① 移行で規則 ID や型が欠ける → 同値テストで検出。② `references/` を前提にしたテストと文書の更新漏れ（`test_skill_entry.py`、`test_markdown_links.py`、`test_documented_paths.py`、doctor の 3 か所）。③ 文書（`docs/spec/ir-schema/` の 4 章が `resource-catalog.md` を指している行など）のリンク切れ → リンクのテストが拾う。④ 説明の文章（補足、判断の理由）をどこに置くか迷って情報が落ちる → `docs/spec/rules/` に原文のまま移す。

---

## 7. テスト戦略

### 7.1 正解 IR との比較ツール（`aws-iac-diagram-workspace/tools/compare_ir.py`。案）

CRITERIA 1.0 と ir-schema 5 章の式のとおり:

- 入力: 正解 IR（G）、出力（O）、形式（`tf`／`cfn`。G の `sources` を形式ごとに射影）。
- **id の対応づけ:** `sources.<形式>.resources` の `drawn` の address で O の id を G の id に置き換える（複数のノードが同じ G に対応づくときは O の id 順で最初の 1 つ、address で対応づかないノード〈合成ノード〉は id のまま）。
- 指標: N = `(id, type)`、E = `(from, to, kind)`、P = `(id, parent)` と `(id, span)`、C = 形式ごとの `(address, class, node／into／rule)`（`into` は置換後の id）、付随（確信度・ラベル。一致した辺・ノードの中で）、名前の一致率、`unknown` の件数、E の向きを無視した一致率（参考）。再現率・適合率、**マイクロ平均**（件数を合算してから割る）、入力ごとの下限（母数 10 以上は割合、未満は誤り 1 件以内）。E の適合率は確定・導出と推定に分ける。
- 重大な誤り X1〜X3（1.5 の定義）。X4 は別の道具（`check_coverage.py`）に任せる（ツールが自分の出力を検算しないため）。
- 出力: JSON（機械用）と表（人用）。基準値は 1 か所の辞書に集め、「CRITERIA.md の数字と同じ」ことを単体テストで確かめる（CRITERIA を勝手に変えない）。
- 道具自身のテスト: 小さな G と O の組を作り、誤りの種類ごとに期待の数値が出ること（id の対応づけ、向きの違い、X2 と X3 の排他、母数 10 未満の扱い）。

### 7.2 自作 5 構成 × TF／CFN

- `tests/integration/normalize/test_expected_ir.py`: 10 入力を正規化し、`compare_ir` の結果が基準 1.0。
- canonical の一致: TF と CFN の出力を `canonical_part` で比べてバイト一致（`--same-canonical`）。
- 変数・パラメータ違い（three-tier の dev／prod）、plan JSON と合わせた入力（`fixtures/tf-plan/`）でも同じ canonical になること（plan と .tf を合わせた raw は .tf だけと同じと確かめてある。HANDOFF）。

### 7.3 主セットの正解 IR（CRITERIA 1.2 のルールを守る手順）

CRITERIA 1.2: 「正解 IR は、ツールの出力を見る前に、別のサブエージェントが書く。書いた正解 IR は、さらに別のサブエージェントがレビューする」。この案の運用:

1. **「ツールの出力」の解釈（要確認。8 章の 2）:** 正規化ツール（フェーズ 3）の出力を指すと解釈する。アダプタ（フェーズ 2。完了済み）の raw IR は、正規化の「入力」であり、正解 IR の `sources.*.resources` の address の一覧（特にモジュールの展開 `module.vpc.aws_subnet.private[0]`）を人が正しく書くには要る。**raw IR から機械的に作った雛形**（address・type・file だけ。class・node・rule は空）を渡す。ノード・辺・入れ子・分類は書き手が入力のソースと規則表（手順 2 で凍結した版）から決める。
2. 書き手は入力のソース（TF／CFN／SAM）、凍結した規則表、`docs/spec/ir-schema/`、雛形だけを見る。**正規化の出力、`normalize/` のコード、サンプルの正解 IR 以外の中間物は見せない。**
3. 書いた IR を `validate_ir.py` と `check_coverage.py`（入力を独立に数える）で検査し、別のサブエージェントがレビューする（根拠は入力のファイル・行と規則 ID）。規則表で決まらない判断は `note` に残し、規則表の改訂候補にする（SELECTION.md の 3 の 1）。
4. 凍結後の変更は理由つきで WORKLOG に記録し、**出力を見た後の訂正の件数を完了の確認で報告する**（透明性。基準を緩めることにはならない）。
5. 置き場: `aws-iac-diagram-workspace/expected/public/<ID>.ir.json`（12 ファイル。T06 と T06s は別ファイル。CRITERIA 1.0 の最後の項目）。書き手は 9 構成 + レビュー（コストは大きい。8 章の 2）。
6. 規模: T12（29 リソース・202 参照・ローカルモジュール 3）と T16（65 リソース・黒箱 2）と C02（42）が大きい。

### 7.4 mutation と golden の使い方

- **変異（CRITERIA 1.7、C4）はフェーズ 6 の評価**（PLAN 5 のフェーズ 6）。フェーズ 3 では、テストの品質の確認として、規則表の 1 行・ハンドラの 1 か所を壊して該当のテストが落ちることを一度確かめる（architecture.md の「テストを足す」の決まり）。変異テストの道具そのもの（1.7）は後回し（8 章の 7）。ただし**局所性**（変更したリソースの address に関係する差分だけが出る）は、設計の性質として正規化が壊さないようにする（段階が全体のグローバルな状態に依らない）。
- golden: 5.5 のとおり。raw の golden（101）と normalized の golden を別にし、規則表の変更の影響が normalized だけに出る。
- 追加するテストの置き場（architecture.md の 7）: `unit/normalize/`（段階ごと。`classify`・`names`・`nodes`・`edges`・各 `relations_*`・`sg`・`iam`・`nesting`・`output`）、`unit/core/`（`rules.py` のローダー）、`integration/normalize/`（自作・主セット・対）、`golden/`、`architecture/`（規則 ID ↔ ハンドラ、`normalize` の依存の向き・順序、`NORM-` のコード一覧、`render_rules` の生成物の一致）。

### 7.5 TF／SAM の対（1.4）

`tools/tf_public_check.py` の `PAIR_EXPECTED`（raw の型の多重集合の理由つきの表）の延長として、**「許す違いの一覧」を出力を見る前に、対（T06・T07・T11）ごとにファイルで作る**（半自動の基準。判定するのは別のサブエージェント）。比較は、ノードの型の多重集合と、辺の (from の型, to の型, kind) の多重集合（一致率 = 共通部分 ÷ 大きい方）。ツールは `compare_ir.py --pair`。

### 7.6 そのほか

- 決定論: 同じ入力の 2 回の実行、`PYTHONHASHSEED` を変えた実行、Windows／Ubuntu（CI）のバイト一致（基準 o）。
- 1.8 の独立な照合: `tools/check_refs.py`（案）が raw IR と normalized IR だけから、各 `active` の参照を 4 つの分類のどれかに当てる（正規化のコードを import しない）。`NORM-UNUSED-REF` の件数と内訳をレポートに出す。**運用の歯止め（CRITERIA の変更ではない）:** 自作 10 入力では `NORM-UNUSED-REF` を一覧化した件数に固定する（理由つき）。主セットは上限を決めず報告する。
- 性能: 正規化の時間を入力ごとに記録（CI の Ubuntu で 3 回の中央値。CRITERIA 4 章の測り方）。見込みは入力ごとに 1 秒未満（仮定）。全体の 30 分はフェーズ 5・6 で決まる。
- Windows 特有: 日本語・スペースを含むパス、PowerShell 5.1（`normalize_ir.py` も `tests/integration/test_cli_paths.py` に足す）。

---

## 8. リスクと未決事項（ユーザーへの質問として。重要度順）

**2026-11-07: ユーザーの指示（「判断が必要な個所は推奨で進めてください」）で、下の 1〜8 をすべて推奨の選択肢で決定。** 1 は A（TOML。手順 1 で実施済み）、2 は (a)（凍結してから正解 IR。E の再現率の既知の制約は測るまで判断しない）、3 は (c)（`data = true` の描く型。手順 2 で H-DATA の文言に反映）、4 は (a)（手順 1 で実施済み）、5 は (a)、6 は (a)、7 と 8 は推奨どおり。

**1. 規則データの形式。** 選択肢: A TOML（領域別）／A′ YAML／C Markdown の表のまま。推奨: **A（TOML）**。理由は 3.3。YAML にするなら、真偽値の罠への対策（引用符の強制のローダー検査）を手順 1 に足す。

**2. 主セットの正解 IR を書く手順とコスト。** 論点: ① CRITERIA 1.2 の「ツールの出力を見る前」を、正規化ツールの出力のことと読む（raw IR の雛形を渡す。7.3）。② 規則表の拡張と凍結（手順 2）を、正解 IR より先に行う（約 40 型の判断を先にしないと、`note` だらけの正解 IR になる）。③ サブエージェントのコスト（書き手 9 + レビュー、T12・T16・C02 が大きい）。選択肢: (a) 7.3 のとおり（推奨）／(b) 規則表を凍結せず書き手に任せる（規則と正解 IR が同時に動いて、基準を満たしたかの判定が弱くなる）／(c) 主セットを減らす（CRITERIA の変更になるのでユーザーの了承が要る）。**CRITERIA 上の懸念（変えない）:** 1.2 の E の再現率 0.90 は推定の辺を含む。T11・T11s の外部ファイル（Step Functions の ASL、OpenAPI の `AWS::Include`）は raw に載らず（実測: T11 の `aws_sfn_state_machine.definition` は `file() is not evaluated`、T11s の `Api` は `Fn::Transform is not evaluated`）、**SFN → DynamoDB の辺は E-IAM（推定）でしか得られず、T11s の API → SFN の辺は raw に根拠が無い**。正解 IR の書き手が真の関係を書けば再現率が下がる。選択肢: (a) 正解 IR は真の関係を書き、足りなければ基準を満たせない（結果を見てから緩めない。0 の 4）→ ユーザーに既知の制約として確かめる／(b) アダプタに「ルート内の JSON・YAML のファイルを読む `file()`」を足す（フェーズ 2 の持ち越し。範囲が広がる）。推奨: (a)。測るまで判断しない。

**3. 既存インフラを指す `data` を描く規則（T09 は主セット）。** T09 は `data.aws_s3_bucket` で既存バケットを参照する（SELECTION.md の T09）。ir-schema 7.4 は「描く型の `data` が描くリソースから参照されていれば既存のノードとして描く（規則 ID と描き方はフェーズ 3 で決める）」とだけ書いた。決めないと T09 の正解 IR が書けない。選択肢: (a) 描く（`drawn`、ノードの名前はバケット名、`H-DATA` はそれ以外の `data` だけ）／(b) すべて `H-DATA`（既存のバケットは描かない）／(c) 描く対象を `data.aws_vpc`・`data.aws_subnet`・`data.aws_s3_bucket` などの表で決める。推奨: **(c)**（表の行に `data = true` を付け、参照されていなければ H-DATA）。T20 の `terraform_remote_state` は H-DATA のまま（4.2）。

**4. IAM だけのモジュール（H-IAM）の判定を `core` へ移す改修の許可。** 正規化は `core` しか import できないので、`iam_only()` をアダプタの中から `core/module_sources.py` へ移す（出力は変わらない。golden 101/101 で確かめる）。選択肢: (a) 移す（推奨。アダプタの診断の文言と正規化が同じ判定を使う）／(b) 一覧を `data/rules/` の H-IAM の行（`module_source_prefix`）にも写す（二重管理になる）／(c) アダプタが raw に `iam_only` の印を足す（raw の仕様の変更）。黒箱モジュール（T16 の kms）の描き方は ir-schema 2 章どおり（`module` ノード、辺は推定）で変えない。

**5. B3 の省略規則・日本語ラベルのフェーズ 3 での扱い。** PLAN のフェーズ 3 行に B3 があり、CRITERIA 2.3 に「B3 のラベル: 省略規則（最大の文字数）と日本語のラベルを、自作の fixture の単体テストで縛る」がある（見やすさの章）。ir-schema は `label` だけが変わり、`name` と `id` は変わらないと決めている。選択肢: (a) フェーズ 3 は `name` の決め方（K-NAME）と `label = name`（合成ノードの固定ラベル）まで。省略の最大文字数・日本語はフェーズ 4（描画の幅が決まるとき）に回す（推奨）／(b) フェーズ 3 で `label` の関数と単体テストまで作る（最大文字数を決める必要がある）。

**6. SG → 辺の粒度と推定辺の既定の表示。** R-SG は「SG Y を付けた各リソース → SG X を付けた各リソース」の辺（resource-catalog の補足）で、同じ SG を付けたリソースが多いと組合せが増える。実測は主セットでは小さい（T16 の `aws_security_group` は 2 つ、ルールは 11 件。T12 は 0）が、T19・T20 は未測。選択肢: (a) 仕様のまま（リソース間の辺。増えたらフェーズ 4 の B2 で扱う）／(b) フェーズ 3 で上限を設ける。推奨: (a)、**T19・T20 の辺の数を手順 6 で測って報告**。推定辺（`inferred`）は IR に常に出し、既定で非表示にするかは**フェーズ 4（描画）の判断**（IR は表示の都合で変えない。ir-schema 8 章の B2 と同じ）。

**7. フェーズ 3 に含めるか後回しにするか。**
- 含める: 1.1・1.2・1.4（対）・1.8・X1〜X4・6 章の X4／`unknown`／検証、C5（決定論）、診断コード、golden。
- 後回し（推奨。PLAN のフェーズ 3 行に無い）: **1.3（大きいサンプルの抜き取りと点検表。T17・T19・C05）、1.7（変異テストの道具）、5 章（目視の採点）、`coverage.md`・`result.json`（フェーズ 5・6）**。ただしフェーズ 3 の中で大きいサンプルの X4 と `unknown` の件数、辺の数は報告する。
- `pruned`・`unevaluated` の参照: フェーズ 3 は使わず件数だけを残す（4.2）。`unevaluated` に実際の関係が入る例（plan JSON の `after_unknown`、`TF-PLAN-EXTRA-REF`）を主セットで測り、辺の再現率が足りなければ、推定の辺として使うことを手順 6 で再検討。

**8. T18 の eks 19.x の要約表の要否ほか。**
- eks 19.x の要約表: **不要**（推奨）。T18 は補助セットで、基準は X4 と件数の報告だけ（CRITERIA 6 章）。黒箱（`module`）で描く（ir-schema 2 章・CRITERIA 2.3 の A5）。
- `cidr` の式の評価（8 章）: 不要。`attrs` は X1 の `access` 以外はどの指標にも入らない（CRITERIA 1.0 と 1.5）。リテラルだけを書き、評価できなければ付けない。
- ノード id の重なりを解いたときの TF／CFN の対応表（8 章）: フェーズ 3 では作らない（自作に重なりが無い。比較は address の対応づけでできる）。重なりは `NORM-KEY-COLLISION` に残す。
- 別リージョン（`provider`・`region`）の描き分け: フェーズ 3 では描き分けない（`region` は `sources` にも出さない）。主セットに別リージョンのリソース（C01 の ACM が us-east-1 など）が出るかを手順 2 で確かめ、正解 IR の判断にする。

### 8.1 そのほか気づいたこと（確定文書は変えない）

- **`NORM-UNUSED-REF` による 1.8 の骨抜き。** 4 番目の分類があるので、どの参照も 4 に入れれば 1.8 は形式上満たせる。CRITERIA も件数を必ず見ると書いている。**自作 10 入力での一覧固定と、独立の `check_refs.py`（7.6）で防ぐ**（CRITERIA の変更ではなく運用）。
- **概算（実測。草案の表 + 属性名の集合だけで、参照の会計をしたときの見込み）:** 自作 10 入力の `active` の参照 479 件のうち、`E-NOEDGE-FROM-RULE` 295、`E-REF-NONODE` 55、`E-NOEDGE-*` 106、E-ENV-REF 8、残り 15（SAM の `Events`・S3 の通知・ナレッジベースのストレージなど、R-*・E-KB-STORAGE が扱うもの）。主セット 12 入力は 352 件のうち、型が表に無いものが起点の 67 件と、表のどれにも当たらない 18 件が残る（表の拡張で減る）。異なる属性名は自作 82、主セット 103。**会計の骨組みは草案の規則でほぼ成り立つが、主セットの型の行を足さないと 1.8 の 4 番目に多く入る**。
- **1.2 の `unknown` 0 件**は型の行（約 40）が前提と SELECTION.md の 4 の 4 に書かれている。CloudFront・Cognito・WAF・EKS・Glue・Step Functions などの扱い（描く／統合／非表示）は、手順 2 で決めて、機械的なものとユーザーの確認が要るものに分けて報告する。
- **正規化の入口と `validate_ir.py` の分離:** `validate_ir.py`（353 行）に規則表の読み込み・正準化・検査が同居している。フェーズ 3 では最小限（`core/rules.py`・`core/ir_norm.py`）だけ移し、検査の本体を `validate/` の層へ移すのはフェーズ 4・5（architecture.md の「いまは入口と本体が 1 ファイル」）。

### 8.2 この調査で決められなかったこと

- 実装していないので、`NORM-UNUSED-REF` の件数、E の再現率・適合率の実際の値は未測（上の概算は草案の規則を単純に当てたもの）。
- 主セットの正解 IR が無いので、主セットの N・E・P の見込みは出せない。
- T20（26 ルート）の raw IR は測っていない（golden に入っているのは `sample-multi-source-cdc-iceberg-lakehouse` の各ルート。辺の組合せ爆発は未測）。
- 型の表に足す約 40 型の扱い（描く／統合／非表示）の個別の判断は、手順 2 で行う。数（67 件・39 型・1,196 件・191 型）は、草案の表から型名を取る簡易の読み取りによるので、数件の誤差がありうる。
