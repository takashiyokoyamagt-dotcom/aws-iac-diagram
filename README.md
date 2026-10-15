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
