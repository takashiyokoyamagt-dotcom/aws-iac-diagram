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

---

## 2026-10-15（続き）自作テスト構成5種・正解 IR・公開サンプルの選定（HANDOFF の表の 4）

### やったこと
1. **IR スキーマ草案 v0.1**: `references/ir-schema.md`（説明）と `references/ir.schema.json`（JSON Schema 2020-12）。正規化後の IR だけを定義。canonical 部（`nodes`・`edges`）と由来部（`sources.tf`／`sources.cfn`: 網羅分類 A6 と辺の根拠）を分けた。評価の単位（ノード・辺・入れ子・網羅）と出力の規則（C5）も書いた。
2. **規則表の草案**: `references/resource-catalog.md`（型ごとの扱い M-*／H-*、入れ子 N-AZ／P-*、アイコン候補）、`relation-resources.md`（A1 の R-*）、`edge-rules.md`（A2・A3 の E-*、合成ノード N-EXT-INTERNET／N-BEDROCK-MODEL、まとめ方 E-MERGE、ラベルの書式）。正解 IR の `rule` はすべてこの表の ID。
3. **自作の構成5種**（`fixtures/tf/<名前>/`、`fixtures/cfn/<名前>/`、各 README に「何を試すか」「期待される扱い」「判断に迷ったところ」）:
   - three-tier（CFN は YAML。Parameters・Mappings・Conditions、dev／prod の tfvars、踏み台は prod だけ）
   - serverless-api（CFN は SAM。Events、ポリシーテンプレート）
   - vpc-endpoints（CFN は JSON と parameters.json。terraform.tfvars が既定値を上書き）
   - three-tier-modules（TF は terraform-aws-modules の vpc／alb／rds とローカルモジュール、CFN はネストスタック5本）
   - rag（S3、Bedrock KB、OpenSearch Serverless、Lambda×2、REST API）
4. **正解 IR** `expected/*.ir.json`（5ファイル。ノード 15／8／15／15／9、辺 7／7／9／7／9）。
5. **検証スクリプト**: `aws-iac-diagram/scripts/validate_ir.py`（スキーマ・参照の整合・規則ID の定義・C5 の形。`--write`、`--same-canonical`）とテスト `scripts/tests/test_validate_ir.py`（12件）。`aws-iac-diagram-workspace/tools/check_coverage.py`（入力の全ブロックが網羅分類にあるか、網羅分類に入力に無いアドレスが無いか、アドレスの重複が無いか。この時点ではインスタンス数は照合していなかった（下の「レビューで直したこと」R3 で追加）。`--lint` で cfn-lint と python-hcl2）と `tools/iac_inventory.py`（入力の列挙）。
6. **公開サンプルの調査と選定**: `tools/survey_public.py` で規模と機能を数え、`fixtures/public/SELECTION.md` に主セット12・補助セット・使わないもの・評価のしかたの提案・見つかった問題をまとめた。
7. `requirements-dev.txt`（cfn-lint 1.57.2、jsonschema 4.26.0）を追加し、README に検証の手順を足した。

### 結果
- `validate_ir.py`: 5ファイルとも OK。three-tier と three-tier-modules の canonical 部が一致。
- `check_coverage.py --lint`: 10 の網羅分類（5構成×2形式）がすべて入力と一致。CFN テンプレート10本が cfn-lint（us-east-1 と ap-northeast-1）でエラー・警告 0。全 .tf／.tfvars を python-hcl2 で読めた。
- 単体テスト 43 件（既存 31＋新規 12）すべて通過。

### 決めたこと
| 決定 | 理由 |
|---|---|
| ノード ID は `<正規の型名>/<名前>`。名前は B3 の順（Name タグ → 名前属性 → 論理名）で、評価後の値を使う | TF の名前ラベルと CFN の論理ID は書き方が違い、正規化しても一致しない。実際の名前なら同じ構成で同じになる。ARN は使わない（失敗知見17） |
| 正解 IR は TF・CFN で1ファイル。違いは `sources` に分ける | canonical 部の一致がフェーズ2 の完了基準そのものになる。網羅分類は形式ごとにリソースが違うので分けるしかない |
| 関係リソースは `merged_into` で `into` に辺の id を書く | A6 の4分類（描画／統合先／非表示／未知）を増やさずに済む |
| 順序付きの組ごとに辺は1本（E-MERGE）。確信度は最も強い根拠、kind とラベルは規則の優先順 | ALB → サービスにリスナーと SG の2本、サービス → DB に環境変数と SG の2本が重なるため |
| IAM から推定した辺は、逆向きの辺が既にあれば作らない（E-IAM-SUPPRESS） | ESM・S3 データソースで、読み手の権限（受け手 → 送り手）とデータの流れが逆になる |
| SG の egress、IGW と internet の間は辺にしない | 相手が決まらない／経路は IGW で終わることで表せる |
| 複数サブネットのリソースは `parent` を共通の祖先、`spans` にサブネット | 1つの親しか持てない。複製するかまたがる箱にするかは配置（フェーズ4）で決める |
| ECS クラスタはサービスに統合し、枠にしない | サービスが AZ をまたぐので、クラスタの枠とサブネットの枠が交差する |
| 基盤モデルは合成ノードにする。KB の埋め込みは derived、Lambda の生成モデルは inferred | RAG の図にモデルが無いと意味が伝わらない。属性の意味が型で決まるか、名前から推測するかで分けた |
| three-tier-modules は three-tier と canonical 部を同じにした | モジュール展開の正しさだけを比べられる |
| レジストリモジュールの中身は `via: module_summary`。作られる managed リソースだけを載せる | ソースを読まない前提（A5）。plan の planned_values と同じ範囲 |

### つまずいたこと（次回のための知見）
- **Claude のスクラッチパッドに Write ツールで書いたファイルが、Bash からも PowerShell からも見えなかった。** Read ツールでは読めるので、ファイルツールとシェルで見えている場所が違う（アプリの仮想化）。シェルで使う一時ファイルはリポジトリ内に置き、使い終わったら消した。
- **python-hcl2 8.1.4 はラベルや文字列を引用符付きで返す**（`"\"aws_vpc\""`）。外す処理が要る。
- **python-hcl2 は heredoc の終端の識別子の後ろに空白があると読めない**（公開サンプル T06）。terraform は受け付ける。アダプタで前処理が要る。
- **cfn-lint は RDS の古いエンジンバージョンを警告する**（W3691）。cfn-lint 1.57.2 のデータでは、postgres の `16.1`〜`16.8` と、マイナーを省いた `16`・`17`、および `17.1`〜`17.4` が非推奨（新規作成不可）の一覧に入っていた。一覧に無い `17.9` にした。`AWS::OpenSearchServerless::Index` の `IndexName` は GetAtt できない（E1010）ので、KB の `VectorIndexName` は文字列で渡した。
- ネストスタックの `TemplateURL` をローカルパスにすると W3002（package 前提）が出る。意図どおりなので各リソースの `Metadata.cfn-lint` で無効にした。
- CFN のネストスタックはスタック単位で依存するので、TF のモジュールと同じ分け方（app の SG がサービス側、DB の SG がルート）だと循環する。SG を1つのスタックにまとめた。
- CFN の rag では、S3 通知 → 関数 → データソース → バケットが循環するので、関数の環境変数にデータソース ID を渡すのをやめ、S3 の権限の `SourceArn` も文字列で組み立てた（よくある回避）。

### 残っていること
- 正解 IR と規則表の第三者レビュー（HANDOFF の次にやること 1）。
- （レビュー対応で解消）three-tier-modules の alb・rds の中身のアドレスは、当初は記憶に基づいていた。
- terraform 本体での検証（`terraform validate`）はしていない。
- 自作 fixture に無いもの: ×N、`!GetAZs`、`unknown` の型、既存インフラの `data`、CloudFront・EventBridge・Step Functions・EKS（公開サンプルの主セットで補う）。

### レビューで直したこと（第三者レビュー: 判定「修正後コミット」、正解 IR 自体の誤りは無し）
- **M1** rag の TF 版の `DATA_SOURCE_ID = aws_bedrockagent_data_source.docs.data_source_id` の扱いが規則表から決まらなかった → edge-rules.md に `E-REF-NONODE`（参照先が R-* で辺になったもの・H-* のものなら辺を作らない、M-* は統合先ノードへの参照）を追加。rag の ingest → KB の辺の TF の根拠にこの参照を追記。
- **R1** ID の key を表示名（label）から作っていた → ノードに必須の `name`（B3 の採用順で決めた名前）を追加し、key は `name` から、`label` は表示専用にした（全正解 IR に `name` を追加）。key が重なったときの付け方（アドレス／論理ID の辞書順で2つ目以降に `.<論理名>`）と、そのときは canonical 部が TF／CFN で一致しないことを ir-schema.md に明記。
- **R2** E-IAM の対象を、ロールを引き受けるリソース全般（KB などのサービスロール）に広げ、アクション → kind の表（`bedrock:StartIngestionJob`、`aoss:APIAccessAll` などを含む）を追加。
- **R3** check_coverage.py がインスタンスの欠落を検出できなかった → `iac_inventory.py` に変数の評価（default → terraform.tfvars → *.auto.tfvars → var_files）と単純な式（整数、`length(var.X)`、`var.X`、`toset(var.X)`）の評価を足し、インスタンスのキーを照合するようにした。`aws_route_table_association.public[1]` を消すと検出される。評価できない式（three-tier の踏み台の `local.env.enable_bastion ? 1 : 0` の2件）は (注) と表示する。このため three-tier の踏み台で試したい H-COND-FALSE は、まだツールでは照合できていない（未照合。locals の map 参照と三項演算子の評価はフェーズ2 の A4 で入れる）。修正後の単体テストは 50 件（既存 31＋validate_ir 19）で、すべて通過。
- **R4** validate_ir.py に検査を追加: class と規則の接頭辞、M-* の into はノード・R-* の into は辺、R-* で辺にしたリソースの規則がその辺の根拠にあること、drawn の入力の型 → ノードの型（resource-catalog.md の表を読む）、id の key と `name` の対応。テストを 7 件追加（計 19 件）。
- **R5** デプロイの妥当性: `nginx:1.27` は 80 番で待つので 8080・`/health` と合わない → `nginx-unprivileged:1.27`（8080 番）にし、ヘルスチェックのパスを `/` に（ラベル `HTTP 8080` は変わらない）。three-tier-modules の `module "app"` に `depends_on = [module.alb]`、serverless-api の ESM に `depends_on = [aws_iam_role_policy.stream_processor]`。
- **R6** alb・rds のソースを GitHub で確認（WebFetch）。alb の `target_groups` は `protocol`／`port` で正しかった。rds は ~> 7.0 に変更（aws >= 6.28、Terraform >= 1.11.1 なので fixture の `required_version` も変更）、`port` は string 型なので `"5432"` に。中身のアドレスは照合の結果どれも正しかった。
- **R7** `multiplicity` は値が決まらないときだけ。値が決まる count／for_each はインスタンスごとにノードにする、と明記。
- 軽微: ir-schema.md の由来部の例、H-RT-NOROUTE の条件（Gateway 型エンドポイントも関連付いていない）、R-LAMBDA-PERMISSION／R-SQS-QUEUE-POLICY で他の辺が無いときの kind、R-SG の「公開」の判定と外部 CIDR（prod の踏み台の SSH）の扱い、E-MERGE で同じ規則からラベルが複数出たときの結合、CFN 版 README の SG egress の差（TF は egress を書かないと egress なし、CFN は既定の全許可）、S3 バケット名の一意性（デプロイしない前提、するなら接尾辞）、.gitignore に `build/`・`.terraform/`・`*.tfstate*`・`.terraform.lock.hcl`、cfn-lint の非推奨バージョンの記述を具体化、一時ファイルは `%TEMP%` 下の専用フォルダにシェルで書く。

---

## 2026-10-15（続き）実行環境の方針（Windows・GitHub Web UI・WSL）

### 概要
HANDOFF の表の 4 は、2回目の第三者レビューで「コミット可」となり、`46ae7c3` にコミットした。続いて、Windows に加えて GitHub の Web UI（Claude Code on the web、Actions の `@claude`。どちらも Linux コンテナ）でも動かす方針をユーザーと合意し、PLAN.md に「1.2 実行環境」を追加した。フェーズ5 の手前にスパイク 5a を入れ、フェーズ5・6 の作業と完了基準を更新した。文書の第三者レビュー（「修正後コミット」）の指摘も反映した。

### 決めたこと
| 決定 | 理由 |
|---|---|
| 1. 中心部分（解析 → IR → 正規化 → 配置 → `.drawio`／`.mmd` → 検証）は Python と pip パッケージだけで動かし、外部アプリを呼ばない。外部アプリは中心部分の後の PNG の書き出し（draw.io）と `.mmd` の描画確認（mmdc）だけに使う | どの環境でも正本の `.drawio` を必ず出せるように |
| 2. PNG は環境で切り替える。Windows／Mac は draw.io Desktop、Linux は `xvfb-run`＋`--no-sandbox`（`drawio_cli.py` に画面判定と xvfb を使う指定を追加）。draw.io が使えなければ（見つからない・起動できない・タイムアウト・無出力か 0 バイト）PNG だけスキップして報告し、全体は失敗にしない。mmdc も Linux では Chromium＋`--no-sandbox` で、使えなければ描画確認だけスキップ | Linux コンテナには画面が無く、Electron／Chromium はサンドボックスで落ちやすい。PNG が出せないことで正本まで失敗にしないため |
| 3. GitHub の画面で使う場合、PNG は GitHub Actions で作る（コミットか artifact）。draw.io の版・ランナーのイメージ・フォントを固定する。同じ GitHub Actions で（ワークフローは別）Windows と Ubuntu のテストを流す。手元の PNG と CI の PNG のどちらをコミットするかは未決（ユーザーが決める） | クラウドのセッションで draw.io が動く保証が無い。固定は C5 のため（バイト一致になるかは 5a で試す） |
| 4. SKILL はプラグインとして配る（このリポジトリをマーケットプレイスにし、使う側の `.claude/settings.json` で有効化する案）。置き方は `plugins/` の下に作る案とルート自体をプラグインにする案の2つを候補にし、フェーズ6 で決める | ジャンクションは手元でしか効かない。非公開リポジトリをクラウドから読めるか、キャッシュにコピーされてディレクトリの外を参照できなくなるかは未確認 |
| 5. WSL（Ubuntu）は Linux での動作確認用。普段の開発と SKILL の利用は Windows ネイティブのまま。確認用のリポジトリは WSL 側へ clone する。WSLg の `DISPLAY`／`WAYLAND_DISPLAY` を外すか xvfb を使う指定をして、画面なしの経路を試す | push の前に Linux の動きを試せるように。`/mnt/c` 越しのファイル I/O は遅い。WSLg のままでは xvfb の経路を通らない |
| 採らない: IR → SVG → resvg の自前描画（最後の予備として残す）、Docker イメージ（drawio-export など） | 自前描画は正本の `.drawio` と見た目がずれ、C6 の採点対象が二重になる。Docker はクラウドのセッションで使えるとは限らない |
| WSL と CI に入れる物（draw.io の deb、xvfb、Chromium）は、入れる前にユーザーの許可を得る | 1 の要件表の「インストール（許可済み）」に入っていないため |

---

## 2026-10-16 共通 Agent Skill への移行（ガイドの方針の反映と土台づくり）

### 概要
ユーザーが示したガイド（`docs/skill-cross-platform-guide.md`）に合わせ、1つの SKILL を Claude Code・VS Code + Copilot（Windows）・gh-aw で共通に使う方針にした。PLAN.md に 1.3 を追加し、フォルダ構成・実行基盤・CI を整えた。図を作る処理はまだ無い。

### やったこと
1. `aws-iac-diagram/` を `skills/aws-iac-diagram/` に、`scripts/tests/` をルートの `tests/` に `git mv` した。ジャンクションを張り直し、`~/.copilot/skills/aws-iac-diagram` も作った。
2. uv 0.13.1 を winget で入れた。各スクリプトの先頭に PEP 723 の依存（`==` で固定）を書き、`requirements*.txt` をやめて `pyproject.toml`・`uv.lock`・`.python-version` にした。既存の `.venv` は `uv sync` がそのまま使った。
3. `SKILL.md` の骨組み（frontmatter は name と description だけ、1行のコマンドの書き方、doctor の手順、`GITHUB_ACTIONS` による分岐。図はまだ作れないと明記）。
4. `scripts/doctor.py`: OS、Python・uv、文字コード、SKILL の同梱ファイル、draw.io（版と起動コマンド）、Linux の画面と `xvfb-run`、node・mmdc、`GITHUB_ACTIONS`・`CLAUDECODE` を JSON にする。終了コードは 0 ok／1 warn（draw.io か mmdc が無い）／2 error。`--out` が無いときは ASCII だけの JSON を標準出力に書く。
5. `lib/drawio_cli.py`: `needs_xvfb()` と `drawio_command()` を追加。Linux では `--no-sandbox`、画面が無いか `AWS_IAC_DIAGRAM_XVFB=1` なら `xvfb-run -a` を前に付ける。`xvfb-run` が無ければ `DrawioError`。
6. `.github/workflows/ci.yml`: ubuntu-24.04 と windows-2025、uv 0.13.1。単体テスト、正解 IR と fixture の検証、SKILL をリポジトリの外の日本語とスペースを含むパスにコピーして doctor を `uv run` で起動（Windows は `shell: powershell` で 5.1）。
7. テスト追加: `test_drawio_cli.py`（8件）、`test_cli_paths.py`（3件。日本語とスペースを含むパスで doctor と validate_ir を別プロセスで動かす）。計 61 件が通過。
8. README を利用者向け（必要なもの、取り込み方、doctor）と開発者向けに書き直した。HANDOFF・fixtures の README・ツールの説明文のコマンドを `uv run` に直した。

### 結果
- 単体テスト 61 件 OK。`validate_ir.py`（`uv run` で PEP 723 の環境）で正解 IR 5 件 OK。`check_coverage.py --lint`（開発用の環境）OK。
- `build_icon_catalog.py` と `check_icons.py` を `uv run` で再実行し、`references/` に差分なし（C5 を維持）。壊れたもの 0 件、対照 9 件は期待どおり。
- CI の PowerShell 5.1 の手順を手元で再現し（`RUNNER_TEMP` を `%TEMP%` 下にして）、doctor が `ok` で日本語のパスに JSON を書けた。GitHub 上ではまだ動かしていない。

### 決めたこと
| 決定 | 理由 |
|---|---|
| 配布はタグ付きの Skill リポジトリ。プラグイン案はやめる | Copilot と gh-aw はプラグインを読めない。ユーザーが選んだ |
| 単体テストは SKILL のフォルダの外（ルートの `tests/`）に出す | 配布するフォルダに実行に要るものだけを置く（ガイド 3） |
| 辞書の保守用スクリプト（build_icon_catalog・check_icons）は当面 `scripts/` に残す | 生成先が SKILL のフォルダの中で、`lib/drawio_cli.py` を共有しているため。SKILL.md からは呼ばない |
| 開発用の環境は `pyproject.toml`＋`uv.lock`、SKILL のスクリプトは PEP 723 | 使う側にはリポジトリが無いので、スクリプト単体で `uv run` できる必要がある。テストは複数のスクリプトの依存をまとめて使う |
| doctor の標準出力は ASCII だけの JSON（`--out` があればファイルに UTF-8） | PowerShell 5.1 で標準出力を受けると文字コードが変わることがある |
| `diagram.py` の終了コードは 0 成功（PNG のスキップは 0 のまま）／1 検証で問題／2 実行エラー | 1.2 の 2（PNG が出せなくても全体は失敗にしない）とガイド 4 を両立させる |

### つまずいたこと（次回のための知見）
- **`uv run check_coverage.py --lint` が Windows で落ちた。** uv のキャッシュ（このアプリでは `AppData\Local\Packages\Claude_...\LocalCache\Local\uv\cache` に置き換えられる）の中の cfn-lint のデータのパスが 260 文字を超えた。開発用の環境（`uv run python ...`）なら通る。SKILL のスクリプトの依存は、パスの深いパッケージを避けるか、使う側でも同じ問題が起きうることを覚えておく。
- シェルの作業ディレクトリが `aws-iac-diagram/scripts` のままだと、`git mv aws-iac-diagram ...` が Permission denied になった。
- `check_icons.py` がリポジトリのルートを「SKILL のフォルダの1つ上」としていたため、移動後に `skills/aws-iac-diagram-workspace/` を作ってしまった。2つ上に直した。
- `python -m unittest discover -s tests -t <ルート>` は、`tests/` がパッケージでないため使えない。`-t` を付けない。

### レビューで直したこと（第三者レビュー: 判定「修正後コミット」）
- **M1** doctor が壊れた取り込み（`lib/` 抜き）や `--out` にフォルダを渡したときに、未処理の例外で終了コード 1（warn と同じ）になり JSON も出さなかった → `lib/drawio_cli.py` の読み込みを `diagnose()` の中に移して error にし、`REQUIRED_FILES` にも加えた。失敗時の JSON にも `issues` を入れ、`--out` に書けなければ ASCII の JSON を標準出力に出して 2 で終える。テスト 2 件を追加（計 63 件）。
- **M2** ci.yml の PowerShell 5.1 の手順に日本語の文字列があった。BOM の無いスクリプトは ANSI（cp1252）として読まれ、「ん」の 3 バイト目 0x93 が `“`（引用符扱い）になって構文エラーになる → コードの文字列を ASCII だけにした（コメントは日本語のまま）。
- **R1** doctor の `encoding.stdout` が reconfigure 後の値（常に utf-8）だった → 切り替え前の値と、`locale.getencoding()`、`PYTHONUTF8`／`PYTHONIOENCODING`、Windows のコンソールのコードページを出す。
- **R3** fixtures の README の `requirements-dev.txt` の残り。PowerShell はネイティブコマンドの引数の `*` を展開しないので、`validate_ir.py` の中で展開するようにした。
- **R5** CI でリポジトリの外から PEP 723 の依存を入れる経路を通していなかった → 日本語のパスにコピーした SKILL で `validate_ir.py` も `uv run` する。
- **R6** `xvfb-run` の既定の画面は 8bit → `-s "-screen 0 1920x1080x24"` を付ける。
- 軽微: スクリプトの使い方を `uv run` に、doctor の終了コードの意味を PLAN 1.3 の 7 に、SKILL.md の出力先（gh-aw では `RUNNER_TEMP`）と uv のインストールはユーザーの了承を得てから、CI に `timeout-minutes` と `workflow_dispatch`、check_icons は開発リポジトリの中でだけ使うと明記。
- 見送り（HANDOFF の次にやること 0b）: R2（パス長の診断）、R4（間接依存の固定）、CI の action の版の更新と SHA での固定。

---

## 2026-10-16（続き）評価基準値の確定（HANDOFF の表の 5）とフェーズ0 の完了

### やったこと
1. `aws-iac-diagram-workspace/evals/CRITERIA.md` に評価基準の案を書いた。もとにしたのは SELECTION.md の 3 と ir-schema.md の 5。内容は、図の正しさ（自作 fixture・主セット・大きいサンプル・TF／SAM の対）、重大な誤り X1〜X4、C1、変異テスト（C4）、見やすさ、IR と出力の突き合わせ、安定性（C5、3回実行）、実行時間、目視の採点（C6）、補助セット、環境と終了コード。
2. 第三者レビューを2回受けた（1回目・2回目とも「修正後に提示」。2回目の必須の指摘は差分だけを直す範囲）。指摘を反映し、ユーザーが了承して確定した（`606ffb4`）。
3. 8章の申し送りを反映した:
   - `unknown` を検証エラーにしない（ir-schema.md の 4、resource-catalog.md）
   - id の対応づけと名前の一致率（ir-schema.md の 5）
   - PLAN の LLM の役割からラベル付けを外す（2.3、3 の ⑥）
   - 半自動の基準も正式な判定に使う（1.3 の 9）
   残りの2項目はフェーズ1 に持ち越した。HANDOFF の表の 5 を済にし、フェーズ0 を完了とした。

### 決めたこと
| 決定 | 理由 |
|---|---|
| 基準は機械的に測れる「自動の基準」が中心。機械で判定できないもの（大きいサンプルの抜き取りと点検表、TF／SAM の許す違いの一覧、C6）は「半自動の基準」とし、別のサブエージェントか人が判定して根拠を記録する | どの環境でも同じ判定にするため（PLAN 1.3 の 9） |
| 比べる前に、`drawn` の address でノードの id を対応づける。名前の誤りは「名前の一致率」で別に数える | 名前を1つ間違えただけで、N・E・P が連鎖して外れるのを防ぐ |
| 母数が 10 未満の入力は、割合の下限ではなく「誤り 1 件以内」で判定する | 辺が 3 本の入力では、1本の誤りで割合が 0.67 になる |
| E の適合率を、確定・導出（0.95）と推定（0.80）で分ける。X2 は「正解に (from, to) の組が向きを問わず無い辺を、確定か導出で描く」に限る | 推定の辺は、破線と凡例で区別して描くので、誤りをある程度許す |
| 重なり・貫通は、Python だけで計算する近似のモデルで判定する（端点、L 字と Z 字の4通りの経路、すべての経路で貫通したときだけ誤り）。draw.io の実際の経路は参考値として出す | `.drawio` には辺の経路が無い（draw.io が決める。失敗知見 5） |
| ラベルと名前はスクリプトが B3 の規則で決める。エージェントが変えてよいのは、説明の文章と確認の質問だけ | 3回実行と TF／CFN で IR が一致することと矛盾しないように |
| `unknown` は分類として正しいので、終了コードは 0 のまま。主セットで 0 件にするのは評価の基準にする | 補助セット（T15 の awscc など）では多く出るのが正常 |
| L4 の辺の貫通は緩める。上限の値はフェーズ4 の前にユーザーの了承を得て決める | 数百のリソースで 0 件は厳しすぎる見込み。結果を見てから決めない |
