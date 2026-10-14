# HANDOFF（再開用）

## 現状（2026-10-14）
- 計画は確定しています。詳細は [PLAN.md](PLAN.md) にあります。
- 実装にはまだ手を付けていません。
- ツールのインストール、アイコンのダウンロード、symlink の作成もまだ行っていません（いずれもユーザーの許可は取得済みです）。

## 次にやること（フェーズ0）
1. venv を作成し、`python-hcl2` と `defusedxml` を入れる。続けて draw.io Desktop（`brew install --cask drawio`）と `@mermaid-js/mermaid-cli`（npm）を入れる。
2. `aws-iac-diagram/` ディレクトリを作成し、`~/.claude/skills/aws-iac-diagram` から symlink を張る。
3. `Sidebar-AWS4.js` と、Mermaid 用の AWS アイコン JSON を取得する。取得先の版は記録しておく。
4. テスト用の構成を5種類、Terraform 版と CloudFormation 版の両方で作る。あわせて正解 IR を作り、第三者レビューにかける。
5. フェーズ6で使う評価基準の値（再現率や適合率の目標など）を決め、ユーザーの了承を得る。
