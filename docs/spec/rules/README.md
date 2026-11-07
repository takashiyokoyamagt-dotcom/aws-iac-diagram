# 規則表（`data/rules/`）の説明

- **これは開発者向けの説明です（SKILL の外。配りません）。** 表そのもの（スクリプトが実行時に読むデータ）は `skills/aws-iac-diagram/data/rules/`（TOML）にあります。下の表は、そのデータから `aws-iac-diagram-workspace/tools/render_rules.py` が作った生成物です（`<!-- rules-table: … -->` の間は直接直さない。直すのはデータ）。

- 経緯: フェーズ 3 の手順 1（2026-10-26）で、`skills/aws-iac-diagram/references/` にあった草案の 3 つの Markdown の表（`resource-catalog.md`・`relation-resources.md`・`edge-rules.md`）を、**意味を変えずに**データ（TOML）にした。規則 ID・型・文はそのまま。表の説明（理由・補足）はこの `docs/spec/rules/` に移した。表の拡張（主セットの型、約 40）と凍結は手順 2。
- 規則表の使い手: `validate_ir.py`（規則 ID の存在、描く型の入力の型 → 正規の型名、`class` と接頭辞）と、フェーズ 3 の `normalize/`（これから作る）。どちらも `scripts/aws_iac_diagram/core/rules.py` の同じ読み込み・検査を使い、表を 2 か所で読まない。
- 文書の使い分け: 規則の「なぜ」はこのフォルダ。型・ID・属性名の「何」はデータ。IR の形は [ir-schema](../ir-schema/README.md)。

## ファイル

<!-- rules-table: layout -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| ファイル | 表 | 行数 |
|---|---|---|
| `types/*.toml`（7 ファイル。名前の昇順） | `[[type]]` | 描く型 32、統合 M-* 19、非表示 H-* 15 |
| `relations.toml` | `[[relation]]` | R-* 16 |
| `edges.toml` | `[[confidence]]` `[[edge]]` `[[kind_by_target]]` `[[iam_action_kind]]` `[[merge_priority]]` `[[synthetic]]` `[[label_format]]` | 確信度 3、辺の規則 E-* 12、kind の対応 3、IAM のアクション 3、優先順 6、合成ノード N-* 2、ラベルの書式 6 |
| `refs.toml` | `[[noedge]]` `[[nonode]]` | E-NOEDGE-* 7、E-REF-NONODE 1 |
| `placement.toml` | `[[placement]]` `[[attr]]` | 入れ子 N-AZ・P-* 5、attrs 1 |

規則 ID は全部で 77（描く型の正規の型名 32 は別）。

<!-- /rules-table -->

| 説明の文書 | 内容 |
|---|---|
| [types.md](types.md) | 型の扱い: 描く型・統合（M-*）・非表示（H-*） |
| [relations.md](relations.md) | 関係リソース（R-*）。A1 |
| [edges.md](edges.md) | 確信度（A3）、辺の規則（E-*）、kind の対応表、まとめ方（E-MERGE）、合成ノード（N-*）、ラベルの書式 |
| [refs.md](refs.md) | 辺にしない参照（E-NOEDGE-*）、参照先にノードが無い参照（E-REF-NONODE）。1.8 |
| [placement.md](placement.md) | 入れ子（N-AZ・P-*）と attrs の取り方 |

## 規則 ID

- 既存の ID は、名前も意味も変えずに引き継ぐ。**使われた ID は、正解 IR・golden・文書が参照するので、消さない・別の意味に使い回さない**。
- 接頭辞が、表と `class` を決める（読み込みのときに検査する）:

| 接頭辞 | 表 | `class` ／ 意味 |
|---|---|---|
| なし（`alb`・`subnet` のような正規の型名） | `[[type]]` | `drawn`。ノードの id の接頭辞と同じ |
| `M-` | `[[type]]` | `merged_into`。`into` はノード |
| `H-` | `[[type]]` | `hidden`。描かない |
| `R-` | `[[relation]]` | `merged_into`。`into` は辺 |
| `E-` | `[[edge]]`・`[[noedge]]`・`[[nonode]]` | 辺を作る規則・辺にしない参照 |
| `N-` | `[[synthetic]]`・`[[placement]]` | 合成ノード（`N-AZ` は入れ子の規則でもある） |
| `P-` | `[[placement]]` | 入れ子 |

## 読み込みの検査（`core/rules.py`）

データを読むとき、次を検査し、問題はすべて集めて `RulesError` にする（`validate_ir.py` は終了コード 2）。

- ファイル: 決まった名前だけ（`types/*.toml`・`relations.toml`・`edges.toml`・`refs.toml`・`placement.toml`・`README.md`）。余りのファイルや `.toml` でないものは、読まれないまま残さずエラー。読む順は名前の昇順（OS の列挙順に依らない）。
- 構造: TOML として読める、ファイルに置いてよい表だけ、未知の列が無い、必須の列がある、列の型（文字列・配列・真偽・表）が合う。
- ID: 形式、全体で重複なし、接頭辞と表・`class` が合う。
- 型: 同じ入力の型が複数の行に当たるのは、`when`（同じ属性の `in` が重ならない、`via` と `via_not`）で同時に成り立たないときだけ。TF／CFN の型の形、合成ノードは入力の型を持たない。
- 参照: `into.node_types`・`placement.types`・`kind_by_target.types` は描く型、`fallback` は H-*、`confidence` の表と各規則の確信度が合う、`use`・`except_rules`・優先順の規則 ID が実在する、辺にしない参照の中立キーが重ならない。

## 中立キー

TF の属性名（snake_case）と CFN のプロパティ名（CamelCase）を同じ名前にそろえる: 小文字にして `_` を除く（`cidr_block` と `CidrBlock` は `cidrblock`）。`[[noedge]]` の `attrs` は TF の書き方で書けば CFN にも当たる。中立キーが同じにならない名前（CFN の RDS の `VPCSecurityGroups` と TF の `vpc_security_group_ids` など）だけ、両方を書く。同じ中立キーを 2 回書くと読み込みが落ちる。

## 規則を足すには

1. データ（`skills/aws-iac-diagram/data/rules/` の該当のファイル）に行を足す。ID は上の接頭辞の決まりに従い、既存の ID は変えない。
2. `uv run python aws-iac-diagram-workspace/tools/render_rules.py --write` で、このフォルダの表を作り直す。
3. 理由・補足は、該当の文書（`types.md` など）に書く。列を足したら `core/rules.py` の列の定義と、`render_rules.py` の `COLUMN_DOC`（列の説明）を直す（足し忘れは `--check` が落ちる）。
4. `uv run python -m unittest discover -s tests` を流す（`tests/unit/core/test_rules.py`・`tests/architecture/test_rules_docs.py`）。

## 草案からの対応（旧 → 新）

| 旧（`references/`。手順 1 で消した） | 新 |
|---|---|
| `resource-catalog.md` の 1・2・3（描く型・M-*・H-*） | `data/rules/types/*.toml`、説明は [types.md](types.md) |
| 同 5（入れ子）と `attrs.access` | `data/rules/placement.toml`、説明は [placement.md](placement.md) |
| `relation-resources.md` | `data/rules/relations.toml`、説明は [relations.md](relations.md) |
| `edge-rules.md` の 1・2・3・4・5・6 | `data/rules/edges.toml`、説明は [edges.md](edges.md) |
| `edge-rules.md` の「辺にしない参照」「参照先にノードが無いときの参照」 | `data/rules/refs.toml`、説明は [refs.md](refs.md) |
