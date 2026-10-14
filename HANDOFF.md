# HANDOFF（再開用）

## 現状（2026-10-14）
- 計画は確定しています。詳細は [PLAN.md](PLAN.md) にあります。
- 実装にはまだ手を付けていません。
- ツールのインストール、アイコンのダウンロード、symlink の作成もまだ行っていません（いずれもユーザーの許可は取得済みです）。
- **公開サンプルは取得済みです（2026-10-14）。** 置き場所は `aws-iac-diagram-workspace/fixtures/public/` です。
  - 内容: 推奨セット T01〜T20、予備候補 P01〜P04、CloudFormation の参考 C01〜C05
  - 出典、コミット、ライセンスは同じフォルダの [SOURCES.md](aws-iac-diagram-workspace/fixtures/public/SOURCES.md) にまとめてあります。
  - 公開モジュールの中身（`terraform init` で取得されるもの）は取得していません。

## 次にやること（フェーズ0）
1. venv を作成し、`python-hcl2` と `defusedxml` を入れる。続けて draw.io Desktop（`brew install --cask drawio`）と `@mermaid-js/mermaid-cli`（npm）を入れる。
2. `aws-iac-diagram/` ディレクトリを作成し、`~/.claude/skills/aws-iac-diagram` から symlink を張る。
3. `Sidebar-AWS4.js` と、Mermaid 用の AWS アイコン JSON を取得する。取得先の版は記録しておく。
4. 自作のテスト用構成を5種類（公開サンプルで足りない部分を補うもの。dev と prod で tfvars を分けた複数環境構成と、3層 L3 を必ず含める）、Terraform 版と CloudFormation 版の両方で作る。あわせて、公開サンプルからフェーズ1〜3の評価に使うものを選び、正解 IR を作って第三者レビューにかける。
5. フェーズ6で使う評価基準の値（再現率や適合率の目標など）を決め、ユーザーの了承を得る。
