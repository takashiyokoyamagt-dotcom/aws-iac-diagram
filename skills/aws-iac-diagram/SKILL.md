---
name: aws-iac-diagram
description: Terraform（.tf、plan JSON）や CloudFormation（YAML／JSON、SAM、cdk.out）を読み込み、AWS 構成図を draw.io・Mermaid・PNG で出力する。「この IaC から構成図を作って」「Terraform／CloudFormation を図にして」「AWS のアーキテクチャ図がほしい」と言われたら使う。
---

# 状態

**準備中です。** 図を作る処理（`diagram.py`）はまだありません。図を頼まれたら、まだ作れないことをユーザーに伝え、下の「環境の確認」だけを行って結果を報告してください。

# コマンドの書き方（必ず守る）

- `scripts/` はこの SKILL.md と同じフォルダの下にあります。コマンドでは、このフォルダの**絶対パス**を使ってください（以下では `<SKILL>` と書きます）。パスにスペースや日本語が含まれる場合は、パスを `"` で囲みます。
- コマンドは**そのまま1行で**実行します。シェルの種類（PowerShell、bash など）は問いません。
- `&&`、`;`、`|`、`>`、`grep`、`sed`、`$(...)`、`$VAR` などのシェルの機能で処理を組み立てないでください。必要な処理はスクリプトのオプションで指定します。
- 結果は標準出力ではなく、`--out` で指定したファイル（JSON、UTF-8）から読みます。

# 環境の確認

1. 次のコマンドを実行します。`<出力先>` は、`GITHUB_ACTIONS` が `true` のときは環境変数 `RUNNER_TEMP` の値（リポジトリの外。PR に混ざらないように）、それ以外は作業中のフォルダの `aws-iac-diagram-out` です。
   `uv run "<SKILL>/scripts/doctor.py" --out "<出力先>/doctor.json"`
2. 出力した JSON を読み、`status` と `issues` を報告します。
   - 終了コード 0（`ok`）: 必要なものはすべてそろっています。
   - 終了コード 1（`warn`）: draw.io や mmdc が使えません。PNG の書き出しや `.mmd` の描画確認はスキップされますが、`.drawio` と `.mmd` は出せます。
   - 終了コード 2（`error`）: SKILL のファイルが足りないか、doctor 自体が失敗しました。`issues` の内容をそのまま伝えます。
3. `uv` が見つからないときは、インストールの方法を案内します（Windows: `winget install --id=astral-sh.uv -e`、Linux／macOS: https://docs.astral.sh/uv/ の手順）。自分でインストールするのは、ユーザーの了承を得てからにします。`GITHUB_ACTIONS` が `true` のときはインストールせず、uv が無いことを失敗として報告します（ワークフロー側の設定の問題です）。

# 実行環境ごとの違い

- 環境変数 `GITHUB_ACTIONS` が `true` のとき（GitHub Agentic Workflows、GitHub Actions）: ユーザーへの確認はしません。PNG はワークフロー側で作るので、作れなくても失敗として扱わないでください。
- それ以外のとき（VS Code、Claude Code など）: 結果をユーザーに見せます。ファイルを変更する前に確認を取ります。

# 変数の値についての注意（Terraform）

- `sensitive` を付けていない変数の値は、出力（図のラベルなど）に入りえます。パスワードやトークンなど伏せたい変数があれば、`sensitive = true` を付けるか、アダプタの `--redact-var <名前>`（何回でも指定できる）で伏せます。伏せた値は使われず、図には現れません。
