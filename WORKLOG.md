# 作業記録

日付ごとに、やったこと・つまずいたこと・決めたことを残す。現在の状態と次の作業は [HANDOFF.md](HANDOFF.md) を見ること。

---

## 2026-10-15（Windows 11）

### 概要
Mac で確定した計画（PLAN.md）を引き継ぎ、開発環境を Windows に移した。フェーズ0 の手順1〜3（環境整備、SKILL の登録、アイコン辞書の生成）を完了し、`e732f90` で main に反映した。

### やったこと
1. **ツールの導入（winget）**: Git 2.55、Node.js 24.20（LTS）、Python 3.12.10、GitHub CLI、draw.io Desktop 32.4.1。npm で `@mermaid-js/mermaid-cli` 12.0.0。
2. **リポジトリの取得**: `gh auth login --web` で認証し、`gh repo clone` で `<clone先のフォルダ>` に取得。
3. **Python 環境**: `.venv` を作り、python-hcl2 8.1.4・defusedxml 0.7.1・PyYAML 6.0.3 を導入。`requirements.txt` に固定。
4. **SKILL の登録**: `mklink /J` で `~/.claude/skills/aws-iac-diagram` → `aws-iac-diagram/` のジャンクションを作成。
5. **動作確認**: draw.io の `-x -f png --disable-gpu` と `mmdc` で、テスト用の図が PNG に書き出せることを確認（Lambda アイコンが正しく描画された）。
6. **アイコン素材の取得**: `Sidebar-AWS4.js`（jgraph/drawio v32.4.1）と `aws-icons-mermaid.json`（awslabs/aws-icons-for-plantuml v23.1）。版と SHA-256 を `aws-iac-diagram/assets/SOURCES.md` に記録。
7. **アイコン辞書**: `build_icon_catalog.py` と `lib/sidebar_harness.js` を作成し、`references/icons/`（catalog.json と31カテゴリの .md、計1045件）を生成。検索用に `find_aws_icon.py` を作成。2回実行して出力のハッシュが一致することを確認。
8. **文書**: PLAN.md に「1.1 Windows への移行」を追加。README にセットアップ手順、`.gitattributes`（LF 固定）を追加。HANDOFF を更新。

### 決めたこと
| 決定 | 理由 |
|---|---|
| symlink の代わりにジャンクションを使う | Windows の symlink は管理者権限か開発者モードが必要。ジャンクションは不要 |
| `export_png.sh` をやめて `export_png.py` にする | Mac と Windows で同じスクリプトを使うため |
| `.gitattributes` で改行を LF に固定する | Git for Windows の自動改行変換で、C5（同じ入力からバイト単位で同じ出力）が崩れるのを防ぐため |
| `Sidebar-AWS4.js` は Node 上でスタブ実行して読む | 正規表現での解析は壊れやすい。draw.io が実際に登録するエントリだけを辞書にできる |
| grIcon を共有するグループは title から id を作る | Private subnet と Public subnet が同じ grIcon を使っていて、id が区別できなかったため |

### つまずいたこと（次回のための知見）
- **最初はツールが何も入っていなかった。** winget で入れたあと、すでに開いているシェルでは PATH が古いままなので、`$env:Path` をレジストリから読み直す必要があった。
- **非公開リポジトリのため、clone に認証が必要だった。**
  - Claude のシェルは対話できないので、`git clone` は「terminal prompts disabled」で失敗する。
  - ターミナルパネルで Git Credential Manager のブラウザ認証を試したが、タイムアウトして取り消された。
  - `gh auth login --web`（デバイスコード方式）で認証できた。以後の push も gh の資格情報で通る。
- **gh のインストールが UAC の確認待ちで止まっていた。** 管理者の確認ダイアログが他のウィンドウの裏に隠れることがある。
- **`Sidebar-AWS4.js` の想定外の形**:
  - `getTagsForStencil(...).join(' ')` のため、タグは配列ではなく文字列で渡ってくる。
  - Illustrations のエントリは title が null で、名前を value に持っている。
- **Windows PowerShell 5.1 での git commit**:
  - here-string を `-F -` で渡すと、メッセージがパス指定として解釈されて失敗した。
  - Claude のスクラッチパッドのパスは長すぎて git が読めず（Filename too long）、さらにアプリの仮想化で実体の場所も違った。
  - 結局、`.git/` の中にメッセージファイルを置いて `git commit -F` で通した。
- PowerShell の `Get-Content` は既定で UTF-8 を正しく表示しないので、生成した .md が文字化けして見えるが、ファイル自体は UTF-8 で正しい。

### 次回
HANDOFF.md の「次にやること」から再開する（C2 の `check_icons.py` から）。

---

## 2026-10-15（続き）C2 壊れたアイコンの自動検出

### やったこと
1. `scripts/check_icons.py` を作成。辞書の shape・resource_icon・group（1032件）を辞書のスタイルのまま並べ、各アイコンの右隣に「参照」（ステンシル名 `resIcon=`／`grIcon=`／`shape=` だけを存在しない名前にしたもの）を描く。20列×10行で11ページの `.drawio` にし、draw.io Desktop でページごとに PNG に書き出して判定する。
2. `scripts/lib/drawio_cli.py` を作成。draw.io の実行ファイルの探索（環境変数 `DRAWIO` → PATH → OS ごとの既定の場所）と、`-x -f png --disable-gpu --theme light --timeout N -b 0 [-p N]` での書き出し（`--scale` は使わない、0 バイトや無出力・起動失敗・タイムアウトは `DrawioError`）。将来の `export_png.py` と共有する。
3. `build_icon_catalog.py` を分割（`apply_broken()`・`strip_broken()`・`write_outputs()`）し、`references/icons/broken.json` を辞書にマージするようにした。カテゴリ別 .md に note 列を追加（broken のときだけ理由を書く）。
4. `find_aws_icon.py` に `--include-broken` を追加。既定では broken を除外し、`--id` で引いた場合は警告を出す。
5. テスト `scripts/tests/`（unittest、31件）: 合成画像で 空箱・黒塗り・単色・ステンシル欠落（グラデーション正方形）・正常、参照スタイルの作り方、group の差分、マーカーからの倍率とオフセット、PNG の大きさの検査、ページ分割、broken のマージ（一時ディレクトリにだけ書くこと）と検索の除外。
6. 全件で実行し、PNG を目視した。結果は **壊れたもの 0 件**、対照 9 件（壊れ 6・正常 3）はすべて期待どおり。2回実行と `build_icon_catalog.py` の再実行で `references/icons/` の全ファイルのハッシュが一致することを確認（C5）。broken.json に仮の1件を入れて build を再実行し、catalog.json・.md・検索に反映され、元に戻せることも確認した。
7. Pillow 12.3.0 を `.venv` に入れて `requirements.txt` に固定。作業ディレクトリ `aws-iac-diagram-workspace/icon-check/` を `.gitignore` に追加。
8. 第三者レビューの指摘を反映（下の「レビューで直したこと」）。

### 決めたこと
| 決定 | 理由 |
|---|---|
| 画像処理は Pillow を使う | 3000x1700 程度の PNG を11枚デコードする。標準ライブラリだけで PNG のフィルタを戻すと遅く、実装の誤りも入りやすい。Pillow は wheel で入り Mac と Windows で同じ |
| セル位置は背景の左上・右下に置いた緑のマーカー（8x8）の重心から実測する | draw.io の PNG は 1280x160 の図に対して 1282x162 になり、約0.5画素ずれる（アンチエイリアス）。推定ではなく実測する。背景矩形を最背面・(0,0) に置いて外接矩形を固定し、PNG の大きさが背景と 4px 以上違えばエラーにする |
| 判定領域はアイコンの geometry から縁を 2px 縮めた矩形。ラベルは領域の外（スロット下の 30px）で `overflow=hidden` | 縁のアンチエイリアスで指標が揺れないように。長い id のラベルが外接矩形を広げて右下のマーカーがずれないように |
| 画素の指標（空箱・黒・単色）に加えて、全アイコンを「ステンシル名だけ存在しない名前にした参照」と比べる | グラデーション付きの resourceIcon は resIcon が無くてもグラデーションの正方形になり、単色の判定をすり抜ける（レビューで指摘）。参照との差分なら塗り方によらず検出できる |
| group は参照との差分だけで判定する | group は枠と隅の小さなアイコンだけで中が空なのが正常。画素の指標を使うと全件「空箱」になった |
| edge・plain_group は描画しない | edge はステンシルを参照しない。plain_group は中が空なのが正常 |
| 対照（壊れ 6 種・正常 3 種）を毎回同じ図に描き、期待と違えば異常終了して辞書を更新しない | 辞書の中に壊れたものが 0 件でも、検出器が動いていることを毎回確かめられる。壊れの対照は参照とは別の存在しない名前（`dynamodb_table` など）を使い、参照と同じスタイルになるトートロジーを避ける |
| 結果の正本は `broken.json`（壊れたものと理由・閾値・draw.io の版・Sidebar の SHA-256。時刻や指標の値は入れない） | 辞書の再生成で消えないように。描画の微小な揺れで差分が出ないよう、浮動小数の指標は git 管理外の `report.json` にだけ書く |

### 閾値の根拠（draw.io 32.4.1 での実測）
- 対照で確かめた壊れ方: 存在しないシェイプ名（`dynamodb_table`）と、gradientColor=none の resourceIcon の存在しない resIcon は **fillColor の単色の正方形**。gradientColor 付きの resourceIcon の存在しない resIcon は **グラデーションの正方形**（単色率 0.56）。fillColor の欠落は **何も描かれない**。存在しない grIcon は **枠だけ**。
- **空箱** `empty_max = 0.05`（非背景率）: 正常の最小は 0.081（`shape:stack2`）、壊れた対照は 0.0。
- **単色** `solid_min = 0.97`（白以外の最頻色の画素率。白は数えない）: 正常の最大は 0.916（`resource_icon:fsx_for_lustre`）、壊れた対照は 1.0。白を最頻色に数えないので、ほとんど白い領域は単色ではなく空箱になる。
- **黒塗り** `black_max = 24`、`black_min = 0.9`: 黒の画素の上限を 48 にすると、濃紺の塗り（`#1E262E`、General resources の resourceIcon）を黒と判定したため 24 に下げた。正常の黒率の最大は 0.002。
- **ステンシル欠落** `stencil_diff_max = 0.002`（参照との差分画素率）: 正常の最小は group で 0.032（`group:group_aws_cloud_alt`）、shape・resource_icon で 0.080（`resource_icon:fsx_for_lustre`）。壊れた対照は 0.0。レビュアーが挙げたグラデーション付きの6件（customer_engagement、connect#3、pinpoint#3、simple_email_service#2、sumerian、ar_vr）は 0.13〜0.24 で正常。

### つまずいたこと（次回のための知見）
- **最初は「内側（各辺 20% 縮めた領域）が空なら空箱」としたら、5件を誤検出した。** `shape:hosted_zone`（盾の線画）、`shape:object`（円）、`shape:stack2`（正方形の枠）、`shape:non_cached_volume`、`shape:instance2` は中が中空の線画で正常。領域全体の非背景率で判定するように変えた。
- 対照の resourceIcon に辞書の先頭（`resource_icon:marketplace`、塗りが濃紺 `#1E262E`）を使ったため、単色ではなく黒塗りと判定されて自己検査が落ちた（上の `black_max` の件）。
- 差分方式を入れた直後、group にも画素の指標を当てたため、正常な group 14件が「空箱」になった（縁を 2px 縮めると枠線が消え、中は空のため）。group は差分だけで判定するようにした。
- サンドボックス内でも draw.io の書き出しは成功した（失敗知見12は今回は起きなかった）。11ページで約30秒。
- Windows のコンソール（cp932）だと日本語の出力が化けるので、3つのスクリプトとも stdout／stderr を UTF-8 にした（PowerShell で読むなら `[Console]::OutputEncoding = [Text.Encoding]::UTF8`）。
- `vidanov` の `dynamodb_table` は draw.io 32.4.1 にも存在せず、塗りの正方形になることを確認した。辞書は Sidebar の実在エントリから作っているので、もともと辞書には入っていない。

### レビューで直したこと
- M1: グラデーション付き resourceIcon の壊れを見逃す → 参照との差分方式を全アイコンに適用し、グラデーション付きの壊れの対照を追加。
- R1: group の対照が参照と同じスタイルのトートロジー → 別の存在しない名前にし、正常な group・shape・グラデーション resourceIcon の対照を追加。
- R2: 検出できない壊れ方と対象外の kind を README と HANDOFF に明記。
- R3: draw.io の起動失敗（OSError）とタイムアウトを `DrawioError` に包み、draw.io 自身の `--timeout` も併用。マーカーが見つからない等の `RuntimeError` も main で捕まえて終了コード 2。
- R4: `build_icon_catalog.py` の既定引数を呼び出し時に解決し、`write_outputs()` に `broken_path` を追加。テストは一時ディレクトリにだけ書く（`TemporaryDirectory` と `addCleanup`）。
- 軽微: 閾値の数値の訂正、単色の定義（白を数えない）、ラベルの `overflow=hidden` と PNG の大きさの検査、stdout の UTF-8 化。
