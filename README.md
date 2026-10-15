# aws-iac-diagram

Terraform（`.tf` と plan JSON）や CloudFormation（YAML／JSON、SAM、CDK の出力）を読み込み、AWS 構成図を作る Claude Code 用の SKILL です。構成図は draw.io・Mermaid・PNG の3つの形式で出力します。

現在は実装の初期段階（フェーズ0）です。計画は [PLAN.md](PLAN.md)、作業を再開するときの手順は [HANDOFF.md](HANDOFF.md) にまとめています。

## セットアップ

必要なもの: Python 3.12 以上、Node.js、draw.io Desktop、`@mermaid-js/mermaid-cli`

### Windows

```powershell
winget install -e --id JGraph.Draw
npm install -g @mermaid-js/mermaid-cli
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# SKILL の登録（ジャンクション。管理者権限は不要）
cmd /c mklink /J "$HOME\.claude\skills\aws-iac-diagram" "$PWD\aws-iac-diagram"
```

### macOS

```bash
brew install --cask drawio
npm install -g @mermaid-js/mermaid-cli
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ln -s "$PWD/aws-iac-diagram" ~/.claude/skills/aws-iac-diagram
```

### アイコン辞書の再生成

```powershell
.\.venv\Scripts\python.exe aws-iac-diagram\scripts\build_icon_catalog.py
.\.venv\Scripts\python.exe aws-iac-diagram\scripts\find_aws_icon.py lambda
```

### 壊れたアイコンの検出（C2）

draw.io Desktop を更新したとき、または `Sidebar-AWS4.js` を取り直したときに実行します。

```powershell
.\.venv\Scripts\python.exe aws-iac-diagram\scripts\check_icons.py
```

- 辞書の全アイコン（shape・resource_icon・group）を draw.io で PNG にし、セルごとに「空箱」「黒塗り」「単色」を判定します。さらに、ステンシル名（`resIcon`／`grIcon`／`shape`）だけを存在しない名前にした参照を隣に描いて比べ、画素がほぼ同じもの（グラデーションの正方形だけになる resourceIcon、アイコンの無い group 枠など）を「ステンシル欠落」とします。
- 判定しないもの: edge（矢印でステンシルを参照しない）と plain_group（AZ・SG などの枠で、中が空なのが正常）。
- 検出できないもの: 一部だけ欠ける・崩れる壊れ方と、別の実在アイコンに置き換わる壊れ方。気になるときは作業ディレクトリの PNG を目で見てください。
- 結果は `references/icons/broken.json` に書き、`catalog.json` とカテゴリ別 `.md` に `broken`（と `broken_reason`）として反映します。`build_icon_catalog.py` も `broken.json` を読んでマージするので、辞書を再生成しても消えません。
- `find_aws_icon.py` は既定で broken を除外します。表示するには `--include-broken` を付けます。
- 壊れ方が分かっている対照（存在しないシェイプ名 `dynamodb_table` など）と正常な対照を同じ図に描き、期待どおりに判定されなければ異常終了します（辞書は更新しません）。
- 作業ファイル（`.drawio`、ページごとの PNG、全件の指標 `report.json`）は `aws-iac-diagram-workspace/icon-check/` に出ます（git 管理外）。
- draw.io の場所は自動で探します。見つからないときは環境変数 `DRAWIO` に実行ファイルのパスを設定してください。

### テスト

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s aws-iac-diagram\scripts\tests -v
```
