---
name: aws-iac-diagram
description: Terraform（.tf、plan JSON）や CloudFormation（YAML／JSON、SAM、cdk.out）を読み込み、AWS 構成図を draw.io・Mermaid・PNG で出力する。「この IaC から構成図を作って」「Terraform／CloudFormation を図にして」「AWS のアーキテクチャ図がほしい」と言われたら使う。
---

# 図の作り方（基本はこれだけ）

1. 下の「環境の確認」を行います（初回だけでよい）。
2. 次のコマンドを実行します。`<入力>` は `.tf` のフォルダ、plan JSON、テンプレート（YAML／JSON）、cdk.out のフォルダのどれかです。
   `uv run "<SKILL>/scripts/make_diagram.py" --input "<入力>" --out-dir "<出力先>/<名前>"`
3. `<出力先>/<名前>/result.json` を読みます。
   - `questions` が空でないとき（環境が複数ある Terraform など）: 図は作られていません。`choices` をユーザーに見せて選んでもらい、`--var-file "<選んだファイル>"` を足して再実行します。`GITHUB_ACTIONS` が `true` のときは確かめず、質問の内容を報告して終わります。
   - `diagram.views` のビュー（`overview` = 全体図、`network` = ネットワーク図、`detail` = 詳細図。大きいときは `-1`・`-2` に分かれる）ごとに、`<出力先>/<名前>/diagram/` に `.drawio`・`.mmd`・`.png` があります。`png`・`mermaid` の `status` が `skipped` なら、その理由（draw.io や mmdc が無いなど）を伝えます。
   - `diagram/coverage.md` は、入力の全リソースを「描いた・統合した・描かなかった・型が分からない」に分けた表です。描かなかったものがあることを、必ずユーザーに伝えます。
4. 図をユーザーに見せ、破線の辺は「推定（IAM の権限などからの推測）」であることを添えます。

終了コード: 0 = 成功（スキップや確認の質問があっても）、1 = 図は書けたが検証で問題がある（`result.json` の `problems` を伝える）、2 = 実行エラー（`steps` の `stderr` を伝える）。

スクリプトで作れないとき（失敗したとき）に、図を自分で描いて（Mermaid や draw.io の XML を書いて）代わりにしないでください。スクリプトの出力したファイルも、手で書き換えないでください。この SKILL の図は、同じ入力から同じ図が出ることを前提にしています。ユーザーがそれでも手で描いた図を求めたときは、この SKILL の出力ではなく、IaC との対応を確かめていない図だと伝えてから描きます。

# コマンドの書き方（必ず守る）

- `scripts/` はこの SKILL.md と同じフォルダの下にあります。コマンドでは、このフォルダの**絶対パス**を使ってください（以下では `<SKILL>` と書きます）。パスにスペースや日本語が含まれる場合は、パスを `"` で囲みます。
- コマンドは**そのまま1行で**実行します。シェルの種類（PowerShell、bash など）は問いません。
- `&&`、`;`、`|`、`>`、`grep`、`sed`、`$(...)`、`$VAR` などのシェルの機能で処理を組み立てないでください。必要な処理はスクリプトのオプションで指定します。
- 結果は、`--out`・`--out-dir` で指定した場所のファイル（JSON、UTF-8）から読みます。`--out` を持たない `validate_ir.py` と `find_aws_icon.py` だけは、結果を標準出力に書きます。
- `<出力先>` は、`GITHUB_ACTIONS` が `true` のときは環境変数 `RUNNER_TEMP` の値（リポジトリの外。PR に混ざらないように）、それ以外は作業中のフォルダの `aws-iac-diagram-out` です（リポジトリの中なら、.gitignore に入れるかユーザーに確かめてください）。

# 環境の確認

1. `uv run "<SKILL>/scripts/doctor.py" --out "<出力先>/doctor.json"` を実行し、`status` と `issues` を報告します。
   - 終了コード 0（`ok`）: 必要なものはすべてそろっています。
   - 終了コード 1（`warn`）: draw.io や mmdc が使えないか、Linux で環境変数 `HOME` が無く draw.io の PNG の書き出しが失敗扱いになります（`issues` の `item` が `home`。HOME を設定するよう伝えます）。図は作れますが、PNG の書き出しと `.mmd` の描画確認がスキップされます。
   - 終了コード 2（`error`）: SKILL のファイルが足りないか、doctor 自体が失敗しました。`issues` の内容をそのまま伝えます。
2. `uv` が見つからないときは、インストールの方法を案内します（Windows: `winget install --id=astral-sh.uv -e`、Linux／macOS: https://docs.astral.sh/uv/ の手順）。自分でインストールするのは、ユーザーの了承を得てからにします。`GITHUB_ACTIONS` が `true` のときはインストールせず、uv が無いことを失敗として報告します。

# 入力の値の渡し方（make_diagram.py にそのまま付ける）

- Terraform: 変数は `--var-file <ファイル>`（`.tfvars`。何回でも）と `--var KEY=VALUE`。plan JSON は `--input` に渡すか、`.tf` のフォルダと一緒に `--plan <plan JSON>`。`terraform.workspace` は `--workspace <名前>`。
- CloudFormation: パラメータは `--param KEY=VALUE`（何回でも）か `--param-file <ファイル>`。値を渡さないパラメータは既定値を使います。
- 環境が複数ある（dev・prod など）ときは、どれにするかユーザーに確かめてから値を渡します。

# 個別のスクリプト（途中の段階を見たいとき）

| 目的 | コマンド（1行） | 終了コード |
|---|---|---|
| Terraform を読む | `uv run "<SKILL>/scripts/adapt_tf.py" --input "<.tf のフォルダ>" --out "<出力先>/tf.raw.json"` | 0 = 書けた、2 = 読めなかった |
| CloudFormation を読む | `uv run "<SKILL>/scripts/adapt_cfn.py" --input "<テンプレートか cdk.out のフォルダ>" --out "<出力先>/cfn.raw.json"` | 同上 |
| raw IR を正規化する | `uv run "<SKILL>/scripts/normalize_ir.py" --input "<出力先>/tf.raw.json" --out "<出力先>/tf.ir.json"` | 0 = 問題なし、1 = 書けたが網羅分類の検査に通らない、2 = 書けなかった |
| normalized IR から図を書く | `uv run "<SKILL>/scripts/diagram.py" --input "<出力先>/tf.ir.json" --out-dir "<出力先>/diagram"` | 0 = 問題なし、1 = 書けたが見やすさの問題がある、2 = 書けなかった |
| IR を検査する | `uv run "<SKILL>/scripts/validate_ir.py" "<出力先>/tf.raw.json"` | 0 = 問題なし、1 = 問題あり（表示を読む）、2 = パスが無い・規則表が壊れている |
| アイコンを探す | `uv run "<SKILL>/scripts/find_aws_icon.py" lambda` | 標準出力に1行1件 |

- アダプタの出力の `diagnostics` の `level` は、`error` = そのリソースかファイルを読めなかった、`warn` = 評価できなかった値があり図が不完全になりうる、`info` = 結果に影響しない読み替え、です。warn 以上があれば伝えてください。
- `validate_ir.py` の `--write` は、渡したファイルを書き換えるので使いません。`make_diagram.py` と `diagram.py` の `--no-external` は PNG と描画確認を省きます（比較用）。

# 参照できるもの

- `<SKILL>/data/`: スクリプトが読むデータ（IR のスキーマ、アイコンの辞書、公開モジュールの要約表、規則表）。エージェントが直接読む必要はありません。
- `<SKILL>/references/`: エージェントが読む手順書の置き場です（いまは README.md だけ）。
- IR と規則の仕様は SKILL に含まれません。このリポジトリの `docs/spec/` にあります（SKILL だけを取り込んだ環境には無い）。

# 実行環境ごとの違い

- 環境変数 `GITHUB_ACTIONS` が `true` のとき（GitHub Agentic Workflows、GitHub Actions）: ユーザーへの確認はしません。
- それ以外のとき（VS Code、Claude Code など）: 結果をユーザーに見せます。ファイルを変更する前に確認を取ります。

# 変数の値についての注意（Terraform）

- `sensitive` を付けていない変数の値は、出力（raw IR の `props`、図のラベル）に入りえます。伏せたい変数があれば、`sensitive = true` を付けるか、`--redact-var <名前>`（何回でも）で伏せます。
- plan JSON そのものには、`sensitive` の変数の値も平文で入っています。出力には書きませんが、plan JSON のファイルの扱いには気をつけてください。
