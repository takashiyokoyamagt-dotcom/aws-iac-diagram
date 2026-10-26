---
name: aws-iac-diagram
description: Terraform（.tf、plan JSON）や CloudFormation（YAML／JSON、SAM、cdk.out）を読み込み、AWS 構成図を draw.io・Mermaid・PNG で出力する（現在は準備中で、図の出力はまだできない。本文の「状態」を見ること）。「この IaC から構成図を作って」「Terraform／CloudFormation を図にして」「AWS のアーキテクチャ図がほしい」と言われたら使う。
---

# 状態

**準備中です。図を作る処理（`diagram.py`）と、draw.io・Mermaid・PNG の出力はまだありません。** 動くのは次の5つの入口スクリプトだけです（使い方は下の「動くスクリプト」）。

- `doctor.py`: 環境の確認
- `adapt_tf.py`・`adapt_cfn.py`: Terraform・CloudFormation を読み、中間表現（IR）の途中の形（raw IR。JSON）にする。**これは図ではありません**（リソースと参照の一覧です）。型ごとの統合・非表示・辺への変換（正規化）と配置は、まだありません
- `validate_ir.py`: IR の検査
- `find_aws_icon.py`: AWS アイコンの辞書の検索

図を頼まれたら、まだ作れないことをユーザーに伝えます。そのうえで、下の「環境の確認」を行って結果を報告するか、ユーザーが望めば raw IR を作って見せます。

# コマンドの書き方（必ず守る）

- `scripts/` はこの SKILL.md と同じフォルダの下にあります。コマンドでは、このフォルダの**絶対パス**を使ってください（以下では `<SKILL>` と書きます）。パスにスペースや日本語が含まれる場合は、パスを `"` で囲みます。
- コマンドは**そのまま1行で**実行します。シェルの種類（PowerShell、bash など）は問いません。
- `&&`、`;`、`|`、`>`、`grep`、`sed`、`$(...)`、`$VAR` などのシェルの機能で処理を組み立てないでください。必要な処理はスクリプトのオプションで指定します。
- 結果は、`--out` で指定したファイル（JSON、UTF-8）から読みます。`--out` を持たない `validate_ir.py` と `find_aws_icon.py` だけは、結果を標準出力に書きます（終了コードも使います）。

# 環境の確認

1. 次のコマンドを実行します。`<出力先>` は、`GITHUB_ACTIONS` が `true` のときは環境変数 `RUNNER_TEMP` の値（リポジトリの外。PR に混ざらないように）、それ以外は作業中のフォルダの `aws-iac-diagram-out` です（無ければ作られます。リポジトリの中なら、.gitignore に入れるかユーザーに確かめてください）。
   `uv run "<SKILL>/scripts/doctor.py" --out "<出力先>/doctor.json"`
2. 出力した JSON を読み、`status` と `issues` を報告します。
   - 終了コード 0（`ok`）: 必要なものはすべてそろっています。
   - 終了コード 1（`warn`）: draw.io や mmdc が使えません。今ある処理には影響しません（図の出力ができるようになったときは、PNG の書き出しと `.mmd` の描画確認がスキップされます）。
   - 終了コード 2（`error`）: SKILL のファイルが足りないか、doctor 自体が失敗しました。`issues` の内容をそのまま伝えます。
3. `uv` が見つからないときは、インストールの方法を案内します（Windows: `winget install --id=astral-sh.uv -e`、Linux／macOS: https://docs.astral.sh/uv/ の手順）。自分でインストールするのは、ユーザーの了承を得てからにします。`GITHUB_ACTIONS` が `true` のときはインストールせず、uv が無いことを失敗として報告します（ワークフロー側の設定の問題です）。

# 動くスクリプト

| 目的 | コマンド（1行） | 終了コード |
|---|---|---|
| Terraform を読む | `uv run "<SKILL>/scripts/adapt_tf.py" --input "<.tf のフォルダ>" --out "<出力先>/tf.raw.json"` | 0 = 書けた、2 = 読めなかった |
| CloudFormation を読む | `uv run "<SKILL>/scripts/adapt_cfn.py" --input "<テンプレートか cdk.out のフォルダ>" --out "<出力先>/cfn.raw.json"` | 同上 |
| raw IR を検査する | `uv run "<SKILL>/scripts/validate_ir.py" "<出力先>/tf.raw.json"` | 0 = 問題なし、1 = 問題あり（検査に通らない IR。ファイルが無い・読めないときも、エラーの表示つきで 1）、2 = パスを渡していない。**1 だけでは「IR の問題」とは決めつけず、表示を読むこと** |
| アイコンを探す | `uv run "<SKILL>/scripts/find_aws_icon.py" lambda` | 標準出力に1行1件 |

- アダプタの終了コードは、`diagnostics` に warn や error があっても 0 です。出力の JSON の `diagnostics` を読んで報告してください。`level` の意味は、`error` = そのリソースかファイルを読めなかった、`warn` = 評価できなかった値があり図が不完全になりうる、`info` = 結果に影響しない読み替え、です。
- Terraform: 変数の値は `--var-file <ファイル>`（`.tfvars`。何回でも）と `--var KEY=VALUE` で渡します。plan JSON（`terraform show -json` の出力）は、`--input` に plan JSON を渡すか、`--input` のフォルダと一緒に `--plan <plan JSON>` で渡します。`terraform.workspace` は `--workspace <名前>`。
- CloudFormation: パラメータは `--param KEY=VALUE`（何回でも）か `--param-file <ファイル>` で渡します。
- 環境が複数ある（dev・prod など）ときは、どれにするかユーザーに確かめてから値を渡します。
- `validate_ir.py` の `--write` は、渡したファイルを書き換えるので使いません。

# 参照できるもの

- `<SKILL>/data/`: スクリプトが読むデータ（`schemas/` の IR のスキーマ、`icons/` のアイコンの辞書、`module-summaries/` の公開モジュールの要約表）。エージェントが直接読む必要はありません。
- `<SKILL>/references/`: 規則表（`resource-catalog.md`・`relation-resources.md`・`edge-rules.md`）。`validate_ir.py` が読みます。正規化の草案で、まだ変わります。
- IR の仕様（章ごとの文書）は、SKILL に含まれません。このリポジトリの `docs/spec/ir-schema/` にあります（SKILL だけを取り込んだ環境には無い）。

# 実行環境ごとの違い

- 環境変数 `GITHUB_ACTIONS` が `true` のとき（GitHub Agentic Workflows、GitHub Actions）: ユーザーへの確認はしません。
- それ以外のとき（VS Code、Claude Code など）: 結果をユーザーに見せます。ファイルを変更する前に確認を取ります。

# 変数の値についての注意（Terraform）

- `sensitive` を付けていない変数の値は、出力（raw IR の `props`。将来は図のラベルなど）に入りえます。パスワードやトークンなど伏せたい変数があれば、`sensitive = true` を付けるか、`adapt_tf.py` の `--redact-var <名前>`（何回でも指定できる）で伏せます。伏せた値は使われず、出力に現れません。
- plan JSON そのものには、`sensitive` の変数の値も平文で入っています。出力の raw IR には書きませんが、plan JSON のファイルの扱いには気をつけてください。
