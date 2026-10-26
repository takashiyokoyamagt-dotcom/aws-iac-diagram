# IR スキーマ（v1.0）

- 状態: **v1.0 確定**（2026-10-17）。正規化後の形（1〜6章）はフェーズ1 の手順1 で、アダプタの出力（7章）は CFN アダプタの実装（手順2〜4）で確かめて手順5 で確定した。TF アダプタ（フェーズ2）の実装で足りなかったものは、7章に足して確定した（2026-10-26。リソースの `provider`・`region`、TF の props・参照・値の書き方、モジュールの展開・A5 の要約表・`terraform_remote_state`・モジュールに渡した provider、plan JSON の入力）。v0.1 草案（フェーズ0）からの変更点は 9章
- 機械可読な定義: 正規化後は [ir.schema.json](../../../skills/aws-iac-diagram/data/schemas/ir.schema.json)、アダプタの出力は [ir-raw.schema.json](../../../skills/aws-iac-diagram/data/schemas/ir-raw.schema.json)（どちらも JSON Schema 2020-12）
- 検証: `scripts/validate_ir.py`（スキーマ＋参照の整合＋出力形式）
- 関連する規則表: [resource-catalog.md](../../../skills/aws-iac-diagram/references/resource-catalog.md)（型ごとの扱い・入れ子）、[relation-resources.md](../../../skills/aws-iac-diagram/references/relation-resources.md)（A1）、[edge-rules.md](../../../skills/aws-iac-diagram/references/edge-rules.md)（A2・A3・SG・IAM・合成ノード・辺にしない参照）

IR には2つの段階がある。

| 段階（`stage`） | 作るもの | 内容 | 章 |
|---|---|---|---|
| `raw` | アダプタ（PLAN 3 の ①。CFN はフェーズ1、TF はフェーズ2） | 入力のリソースを、評価（A4）した後のプロパティと参照の一覧にしたもの。図の形にはまだしない | 7章 |
| `normalized` | 正規化（PLAN 3 の ②。フェーズ3） | 図に描く内容（ノード・辺・入れ子）と、網羅分類・辺の根拠 | 1〜6章 |

正解 IR（`aws-iac-diagram-workspace/expected/*.ir.json`）は `normalized` の形で書く。

## 目次

この仕様は章ごとのファイルに分けてあります（もとは 1 つの `ir-schema.md` で、SKILL の `references/` にあった。開発者向けの文書なので、2026-10-26 に SKILL の外のここへ移し、章ごとに分けた）。見出しと章・節の番号は、分ける前と同じです。

| 章 | ファイル | 内容 |
|---|---|---|
| [1. 全体の構造](01-overview.md) | `01-overview.md` | 全体の構造（`nodes`・`edges`・`sources`・`evaluation`。canonical 部と由来部） |
| [2. ノード](02-nodes.md) | `02-nodes.md` | ノード（フィールド、黒箱のモジュール、×N の出し方、ID の作り方 K-NAME） |
| [3. 辺](03-edges.md) | `03-edges.md` | 辺（`from`・`to`・`kind`・`label`・確信度） |
| [4. 由来部（sources）](04-sources.md) | `04-sources.md` | 由来部（網羅分類 A6、辺の根拠） |
| [5. 評価の単位（再現率・適合率）](05-evaluation-units.md) | `05-evaluation-units.md` | 評価の単位（再現率・適合率。基準値は評価基準 CRITERIA.md） |
| [6. 出力の規則（C5）](06-output-rules.md) | `06-output-rules.md` | 出力の規則（C5。同じ入力は同じバイト列） |
| [7. アダプタの出力（`stage: "raw"`）](07-raw-output.md) | `07-raw-output.md` | アダプタの出力 raw IR（`stage: "raw"`）: 7.1 全体の構造、7.2 リソース、7.3 参照、7.4 入力ごとの扱い、7.5 診断（コードの一覧） |
| [8. 決めなかったこと（後のフェーズで決める）](08-undecided.md) | `08-undecided.md` | 決めなかったこと（後のフェーズで決める） |
| [9. v0.1 からの変更点（2026-10-17）](09-changes-from-v0.1.md) | `09-changes-from-v0.1.md` | v0.1 草案からの変更点（2026-10-17） |

## 章・節の番号は変わらない識別子です

コードのコメント・docstring、テスト、文書が「ir-schema の 7.2」「7.5」「2章」のように、**章・節の番号で**この仕様を指しています（診断コードの一覧との照合は、`07-raw-output.md` の `### 7.5 診断` の見出しを探します。`tests/architecture/test_diagnostics.py`）。そのため:

- 番号を詰めない・振り直さない。章や節を足すときは、最後に足す。
- 章のファイルの名前は `NN-<名前>.md`（`NN` は章の番号）。ファイルを分け直すときも、見出しの番号は変えない。
- 文書やコードに書く場所は、`docs/spec/ir-schema/` の下の該当の章のファイル（例: `docs/spec/ir-schema/07-raw-output.md` の 7.2）。「ir-schema.md の 7.2」と書いてある所は、この仕様の 7.2 のこと。
