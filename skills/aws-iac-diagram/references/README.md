# references/

ここにあるのは、正規化（フェーズ 3）で使う規則表の草案 3 つだけです。`scripts/validate_ir.py` が、規則の ID の照合のために読みます（場所は `scripts/aws_iac_diagram/core/paths.py` の `RULE_DOCS`）。フェーズ 3 で表にして `data/rules/` に移します。それまで、動かしたり消したりしないでください（`doctor.py` の必須ファイルの一覧にも入っています）。

| ファイル | 内容 |
|---|---|
| [resource-catalog.md](resource-catalog.md) | 型ごとの扱い（描く・統合する・辺にする・非表示）と入れ子 |
| [relation-resources.md](relation-resources.md) | 関係リソースを辺に変える規則（A1） |
| [edge-rules.md](edge-rules.md) | 辺の向き・確信度（A2・A3）、SG・IAM・合成ノード、辺にしない参照 |

IR の仕様（スキーマの説明）と、モジュールの要約表の説明は、開発者向けの文書なので SKILL に含めていません。このリポジトリの `docs/spec/`（`ir-schema/` と `module-summaries.md`）にあります。
