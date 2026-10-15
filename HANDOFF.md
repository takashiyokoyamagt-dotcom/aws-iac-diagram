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
| 3b | C2（壊れたアイコンの自動検出 `check_icons.py`） | **済**: draw.io 32.4.1 で 1032 件（shape・resource_icon・group）を判定し、**壊れたものは 0 件**。対照 9 件（壊れ 6 種・正常 3 種）はすべて期待どおり。結果は `references/icons/broken.json` → 辞書の `broken`。テストは `scripts/tests/`（31件） |
| 4 | 自作テスト構成5種（TF 版と CFN 版）と正解 IR、公開サンプルからの選定、第三者レビュー | 未着手 |
| 5 | フェーズ6の評価基準値を決めてユーザーの了承を得る | 未着手 |

## 次にやること
1. 上の表の 4 と 5。
2. フェーズ5 の `export_png.py` は `scripts/lib/drawio_cli.py`（draw.io の探索と `-x -f png --disable-gpu` の呼び出し、0 バイトの失敗扱い）を使って作る。

## 辞書について（実装で分かったこと）
- `Sidebar-AWS4.js` は正規表現で読まず、`scripts/lib/sidebar_harness.js` で Sidebar をスタブ化して Node 上で実行し、登録されたエントリを記録している。
- id の形式は `<kind>:<name>`。kind は `resource_icon`（78x78、resIcon）、`shape`（直接シェイプ）、`group`（grIcon）、`plain_group`（AZ・SG など AWS ステンシルを使わない枠）、`edge`。
- 同じ名前が複数あるときは `#2` などが付く（例: `shape:lambda_function#2` は IoT カテゴリの 78x78 版）。grIcon を共有するグループ（Private／Public subnet）は title から名前を作る。
- Illustrations は title が null で、名前を value に持っている。
- 退役アイコン（`retired: true`）は既定では検索に出ない。

## 壊れたアイコンの検出（C2）について
- 実行: `.venv\Scripts\python.exe aws-iac-diagram\scripts\check_icons.py`（約30秒、11ページ）。draw.io Desktop か `Sidebar-AWS4.js` を更新したら再実行する。
- 判定: 空箱・黒塗り・単色（画素の指標）と、ステンシル名だけ存在しない名前にした参照との差分（stencil_missing）。group は差分だけで判定する。閾値の根拠は WORKLOG.md。
- 検出できないもの: 一部だけ欠ける・崩れる壊れ方、別の実在アイコンに置き換わる壊れ方。対象外の kind: edge（ステンシルを参照しない）、plain_group（中が空なのが正常）。辞書ではこれらも `broken: false` だが、「判定していない」という意味である。
- 自己検査: 対照 9 件（壊れ 6 種・正常 3 種。一覧は `check_icons.py` の `controls()`）が期待どおりでなければ終了コード 3 で止まり、辞書を更新しない。draw.io の失敗やマーカーのずれは終了コード 2。
- `broken.json` が正本で、`build_icon_catalog.py` も `check_icons.py` も同じ `write_outputs()` で辞書に反映する。辞書を再生成しても `broken` は消えない。`sidebar_sha256` が今の `Sidebar-AWS4.js` と違えば、build 時に再実行を促す警告が出る。
- 辞書は Sidebar に実在するエントリだけから作っているので、vidanov の言う `dynamodb_table` のような壊れ名はそもそも辞書に無い。今回 0 件だったのはそのため。`check_icons.py` は辞書の元を変えたり draw.io を更新したりしたときの回帰検知として使う。
- 作業ファイル（`.drawio`・PNG・`report.json`）は `aws-iac-diagram-workspace/icon-check/`（git 管理外）。PNG を目で見るとよい。
