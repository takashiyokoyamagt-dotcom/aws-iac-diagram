# HANDOFF（再開用）

## 現状（2026-10-15）
- 計画は確定しています。詳細は [PLAN.md](PLAN.md) にあります。
- 日ごとの作業の経緯とつまずいた点は [WORKLOG.md](WORKLOG.md) にあります。
- **開発環境を Mac から Windows 11 に移しました。** 違いは PLAN.md の「1.1 Windows への移行」を参照してください。
- 公開サンプルは取得済みです（2026-10-14）。置き場所は `aws-iac-diagram-workspace/fixtures/public/` です。
  - 内容: 推奨セット T01〜T20、予備候補 P01〜P04、CloudFormation の参考 C01〜C05
  - 出典、コミット、ライセンスは同じフォルダの [SOURCES.md](aws-iac-diagram-workspace/fixtures/public/SOURCES.md) にまとめてあります。
  - 公開モジュールの中身（`terraform init` で取得されるもの）は取得していません。

## フェーズ0 の進み具合

| # | 内容 | 状態 |
|---|---|---|
| 1 | ツールのインストール | **済（Windows）**: Git 2.55、Node 24.20、Python 3.12.10、gh、draw.io Desktop 32.4.1、mmdc 12.0.0。`.venv` に `requirements.txt`（python-hcl2・defusedxml・PyYAML）を導入 |
| 2 | `aws-iac-diagram/` の作成と SKILL の登録 | **済**: `~/.claude/skills/aws-iac-diagram` → リポジトリの `aws-iac-diagram/` をジャンクションで登録 |
| 3 | アイコン素材の取得と辞書の生成 | **済**: 版と SHA-256 は [assets/SOURCES.md](aws-iac-diagram/assets/SOURCES.md)。`scripts/build_icon_catalog.py` で `references/icons/`（1045件、31カテゴリ）を生成。検索は `scripts/find_aws_icon.py`。再実行してもバイト単位で同じ出力になることを確認済み |
| 3b | C2（壊れたアイコンの自動検出 `check_icons.py`） | 未着手 |
| 4 | 自作テスト構成5種（TF 版と CFN 版）と正解 IR、公開サンプルからの選定、第三者レビュー | 未着手 |
| 5 | フェーズ6の評価基準値を決めてユーザーの了承を得る | 未着手 |

## 次にやること
1. `check_icons.py`（C2）: `catalog.json` の全アイコンを1枚の `.drawio` に並べて draw.io で PNG にし、セルごとの画素のばらつきから空箱・黒・単色を判定する。結果は辞書に `broken: true` として反映する。
2. 上の表の 4 と 5。

## 辞書について（実装で分かったこと）
- `Sidebar-AWS4.js` は正規表現で読まず、`scripts/lib/sidebar_harness.js` で Sidebar をスタブ化して Node 上で実行し、登録されたエントリを記録している。
- id の形式は `<kind>:<name>`。kind は `resource_icon`（78x78、resIcon）、`shape`（直接シェイプ）、`group`（grIcon）、`plain_group`（AZ・SG など AWS ステンシルを使わない枠）、`edge`。
- 同じ名前が複数あるときは `#2` などが付く（例: `shape:lambda_function#2` は IoT カテゴリの 78x78 版）。grIcon を共有するグループ（Private／Public subnet）は title から名前を作る。
- Illustrations は title が null で、名前を value に持っている。
- 退役アイコン（`retired: true`）は既定では検索に出ない。
