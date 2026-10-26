# 作業記録

日付ごとに、やったこと・つまずいたこと・決めたことを残す。現在の状態と次の作業は [HANDOFF.md](HANDOFF.md) を見ること。

---

## 2026-10-15（Windows 11）

### 概要
Mac で確定した計画（PLAN.md）を引き継ぎ、開発環境を Windows に移した。フェーズ0 の手順1〜3（環境整備、SKILL の登録、アイコン辞書の生成）を完了し、`a75da3d` で main に反映した。

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
- **当時は非公開のリポジトリだったため、clone に認証が必要だった。**
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
HANDOFF の表の 4 は、2回目の第三者レビューで「コミット可」となり、`c24951f` にコミットした。続いて、Windows に加えて GitHub の Web UI（Claude Code on the web、Actions の `@claude`。どちらも Linux コンテナ）でも動かす方針をユーザーと合意し、PLAN.md に「1.2 実行環境」を追加した。フェーズ5 の手前にスパイク 5a を入れ、フェーズ5・6 の作業と完了基準を更新した。文書の第三者レビュー（「修正後コミット」）の指摘も反映した。

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
2. 第三者レビューを2回受けた（1回目・2回目とも「修正後に提示」。2回目の必須の指摘は差分だけを直す範囲）。指摘を反映し、ユーザーが了承して確定した（`07dbb5f`）。
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

---

## 2026-10-17 フェーズ1 の手順1: IR スキーマの確定（v1.0）

### 概要
フェーズ1 を5つの手順（スキーマの確定 → CFN アダプタの土台 → SAM・ネストスタック・cdk.out → A4 → C1）に分けて進めることにした。手順1 として、ir-schema.md の未決事項と、評価基準から持ち越した2件を決めて v1.0 にした。

### やったこと
1. **ir-schema.md を v1.0 にした。**
   - 正規化後の形は v0.1 と互換。`attrs` のキーを表で固定した（`cidr`、`access`、`endpoint_type`、`service`、`module_source`、`module_version`）
   - 黒箱のモジュール（型 `module`、`via: "module_blackbox"`）を足した
   - ×N の出し方と、AZ が静的に決まらないときの key（`<vpc>.az1`）を決めた
   - アダプタの出力（`stage: "raw"`）を7章に定義した: リソース（`enabled`、評価後の `props`）、`$ref`・`$pseudo`・`$concat`・`$az`・`$import`・`$unknown` の印、参照（`path`・`fn`・`through`）、診断
   - 公開サンプルで見つかった問題の扱いを 7.4 に決めた
2. **`ir-raw.schema.json` を新しく作った。** `ir.schema.json` は 1.0 にし、`attrs` のキーと `via` を制限した。正解 IR 5件の `ir_version` を 1.0 にした。
3. **edge-rules.md:** 「参照でも辺にしないもの」を、規則 ID 付きの表（`E-NOEDGE-PLACEMENT`・`-SG`・`-ROLE`・`-LOG`・`-MERGE`・`-ROUTE`・`-DEPENDS`、`E-REF-NONODE`）にした。CRITERIA の 1.6（C1）で使う。
4. **resource-catalog.md:** `module` の行、`H-NONAWS` を足した。`H-NESTED-STACK`（読めないときは黒箱）と `H-DATA`（既存のインフラの方針）の補足を更新した。
5. **validate_ir.py:** `via: "module_blackbox"` の網羅分類は、型によらず `module` のノードにしてよいようにした。
6. **テスト:** `tests/test_ir_schema_v1.py`（12件。raw の例が通ること、未知の印・余分なキー・負の `$az` などを弾くこと、`attrs` の制限、黒箱のモジュール）。計 75 件が通過。正解 IR 5件の検証と、three-tier・three-tier-modules の canonical 部の一致も通った。

### 決めたこと
| 決定 | 理由 |
|---|---|
| アダプタは図の形にしない。評価した後のプロパティと参照の一覧（raw）だけを出し、規則表を使うのは正規化だけにする | CFN と TF で正規化を1つにするため。規則の誤りを1か所で直せる |
| 評価できた値はふつうの JSON にし、できなかった部分だけ `$` で始まるキーの印にする | 正規化が値をそのまま読める。印の種類を Schema で固定し、未知の印を弾ける |
| 参照は `props` の中の `$ref` と、`references` の一覧の両方に持つ（`path` で対応させる）。`DependsOn` は `references` にだけ | 正規化はプロパティの意味（環境変数か、サブネットか）で参照を扱い、C1 は参照の一覧と cfn-lint のグラフを突き合わせる |
| 黒箱のモジュールは型 `module` の1ノード。IAM だけのモジュールは H-IAM | 中身を推測しない（CRITERIA の 2.3）。T16 の iam サブモジュールのように、IAM を描かない方針と揃える |
| 複数ビューの詳細度は IR に持たせず、型ごとに catalog の列で決める（フェーズ4） | 表示の都合で IR（canonical 部）を変えないため |
| AZ が決まらないときは、`Select` の位置の番号（1始まり）で `az1` | AZ 名を推測しない。TF の `names[0]` と CFN の `!Select [0, !GetAZs '']` が同じ key になる |

### 第三者レビュー1回目（判定「要再レビュー」）と対応
レビュアーが cfn-lint 1.57.2 のグラフを実際に取り出し、自作 fixture と突き合わせて指摘した。

- **M1** 評価基準の 1.6（C1）が、正規化ができる前のフェーズ1 では測れず、正解 IR の根拠の書き方とも合わない（試算で説明できない辺が 4 構成で 39 本）→ **ユーザーの了承を得て** 1.6 を「cfn-lint の辺のすべてに raw IR の参照が対応する」に変え、正規化が参照を捨てていないかを見る 1.8 を足した。PLAN のフェーズ1・3 の完了基準も合わせた。
- **M2** 評価で消える参照（`Fn::If` の選ばれなかった側、条件が偽のリソース、評価できない関数の中）の置き場所が無い → 参照に `state`（`active`／`pruned`／`unevaluated`）を足し、`enabled: false` のリソースも props と参照を出すことにした。
- **M3** 参照の一意性・`$concat` の正規形が決まらない → キーを `(from, path, to, attr, fn)` にし、`path` は評価後の props の上の位置（`$concat` の中は数えず、`$json` は透過）、`$concat` は隣の文字列をつなぐ・空文字を消す・入れ子にしない、と決めた。
- **M4** `!Join` でつないだサブネットの一覧を List 型のパラメータで受ける形を表せない → `$concat` を区切り文字で分けて印のリストにする規則を足した。
- **M5** `jsonencode(...)` などの中の参照を表せない → `$json` の印を足した。
- **M6** 入力の `$schema`・`$or` などとぶつかる → `$$` で逃がす決まりにし、印の名前を `$ref` から `$res` に変えた（R1 の JSON Schema の `$ref` との取り違えも避ける）。
- **M7** cdk.out の複数スタック、解決できた ImportValue → address を `<スタック名>::…`、`fn: ImportValue` と `through: ["Export:…"]` にした。
- 推奨: Schema の穴（`$concat` の中身、形式ごとの `fn`・`evaluation`、`Ref` の `attr`、`through` の形）を塞いだ。raw IR の決まり（props の `$res` と参照の1対1、先のリソースの有無、並び順、`$concat` の正規形）を調べる `scripts/lib/ir_raw.py` を作り、`validate_ir.py` は `stage` で正規化後と raw を切り替えるようにした。`E-NOEDGE` の表を直し（関係リソースの中の参照の行を外して `E-NOEDGE-FROM-RULE` にまとめた。タスク定義は除く。SAM の `Policies` は E-IAM）、TF の `$pseudo`・スプラット・`through`、SAM の Globals・暗黙のリソース、ネストスタックの条件の名前、S3 URL の読み替え（末尾からの最長一致）、黒箱のモジュールの辺（`inferred`、枠・SG・IAM には作らない）、×N の置き場所を決めた。正規化後の IR に `diagnostics`（`NORM-…`）を足した。`module` のノードと `via: module_blackbox` の対応を両方向で調べ、黒箱になれる入力の型を絞った。
- ir-schema.md の状態を「正規化後の形は確定、raw の形はアダプタの実装で確かめて手順5 で確定」にした（ユーザーの了承）。
- テストは計 82 件（test_ir_schema_v1.py を書き直して 22 件）。

### つまずいたこと
- Bash のヒアドキュメントで日本語と `'` を多く含む長い文書を渡すと、解析に失敗した（「unexpected EOF」）。長い文書は Write ツールで `.git/` の下に書き、Python で差し替えた。
- Python のコードを Bash 経由で書き込むと、文字列の `\n` が本物の改行に化けた（HANDOFF の注意と同じ）。コードの書き換えは Edit ツールで行う。

### 第三者レビュー2回目（判定「修正後コミット」）と対応
- レビュアーが、新しい 1.6 の照合を自作 fixture の CFN（cfn-lint の辺 214 本）に机上で当てた。対応の無い辺は rag の1本（`DataAccessPolicy -> KnowledgeBaseRole`）だけで、原因は path の完全一致（cfn-lint は `Fn::Sub` の位置で止まり、raw は `$json` の中まで続ける）。
- **M1** → ユーザーの了承を得て、1.6 の照合を前方一致にした。Stack リソースの `Parameters` は分割しない、`pruned` を `Fn::Select` などの選ばれなかった値にも広げた（ir-schema.md の 7.2）。
- **M2** cfn-lint は `Metadata` などの中の参照も辺にする（公開サンプルの ecs-refarch-cloudformation）→ raw に `Metadata.…` の参照も出す。ir_raw.py の1対1の検査はこれを除く。
- **R1** 1.8 の「根拠に出てくる」を機械で照合できない → ツールが出す根拠は `<from>.<path>` で始める（ir-schema.md の 4章）と決め、1.8 は前方一致で照合する（ユーザーの了承）。「使わなかった参照」の件数と内訳を、フェーズ3 の完了の確認で必ず見る。
- **R2** CDK のスタック名のハイフンを `through` で認めた。軽微: `E-REF-NONODE` の重複、`$concat` の中の `$json` を禁止、`$az: "*"` は AZ のノードを作らない、`["k"]` を除いたときの属性名の注。
- テストは計 85 件。

---

## 2026-10-17（続き）フェーズ1 の手順2: CloudFormation アダプタの土台

### やったこと
1. `skills/aws-iac-diagram/scripts/adapters/cfn.py` を作った（PEP 723 で PyYAML）。`uv run scripts/adapters/cfn.py --input <テンプレート> --out <raw.json> [--root-base <フォルダ>]`。終了コードは 0（書けた）／2（読めない）。
   - **短縮タグ:** YAML の `!Ref` などを、awscli の yamlhelper と同じ考え方で `Fn::*` の長い形にする（失敗知見 13）。`!GetAtt A.B.C` は最初の `.` で分ける。YAML の日付の暗黙の型変換を外した（`'2010-09-09'` を文字列のまま読む）。JSON のテンプレートも読む。
   - **評価する関数:** `Ref`（リソース・パラメータの Default・擬似パラメータ・`AWS::NoValue`）、`Fn::GetAtt`、`Fn::Sub`（文字列と変数の表の2形式、`${!Literal}`、`${X.Attr}`）、`Fn::Join`、`Fn::Select`（`!GetAZs` からは `$az`、選ばれなかった要素の参照は `pruned`）、`Fn::Split`（`$concat` の分割）、`Fn::GetAZs`、`Fn::ImportValue`（`$import`）、`{{resolve:…}}`・SSM の型のパラメータ（`$unknown`）。
   - **手順4 に回したもの:** `Fn::If`・`Fn::FindInMap`・`Fn::Equals` などと、リソースの `Condition`。それまでは `$unknown`（診断 `CFN-DEFERRED`）にし、中の参照は `unevaluated` で残す。`Condition` のあるリソースは `enabled: null`。
   - `Fn::Sub` で組み立てた JSON の文字列は、`${…}` を目印に置き換えて JSON として読めれば `$json` にする。
   - 参照は、評価中は印に一時的な `__fn` を付けて運び、最後に props から集めて active の参照にする（`path` の作り方を ir_raw.py の `join_path` に一本化）。`Metadata`・`CreationPolicy`・`UpdatePolicy` の中の参照と `DependsOn` も出す。入力の `$` で始まるキーは `$$` で逃がす。
2. `lib/ir_raw.py` の `normalize_concat` を直した（印が1つだけ残ったときは印そのものにする）。Schema の `$concat` の要素は2つ以上にした。
3. テスト `tests/test_cfn_adapter.py`（9件。短縮タグと長い形が同じ結果になる、各関数の値、`$json`、`$$`、`pruned`・`unevaluated`、IAM の `Condition` をふつうのプロパティとして読む、`DependsOn` と `Metadata`、出力が毎回同じ、fixture の全テンプレートで raw IR が検査を通る）。計 94 件が通過。

### 確かめたこと
- 自作 fixture の CFN テンプレート 10 本（three-tier、serverless-api、vpc-endpoints、rag、three-tier-modules の root と子5本）で raw IR を作り、`validate_ir.py` が通った。
- cfn-lint 1.57.2 のグラフの辺 214 本と、raw IR の参照を、CRITERIA の 1.6 の照合（関数の位置で止めて前方一致）の仮の版で突き合わせ、**対応の無い辺は 0 件**だった（テンプレートごと。ネストスタックをまたぐ辺は手順3）。仮の照合のスクリプトは手順5 で正式な道具にする。
- PowerShell 5.1 から `uv run` で起動でき、日本語とスペースを含むパスに書けた。

### つまずいたこと
- cfn-lint のグラフの `source_paths` は「パスの一覧」ではなく、1本のパス（要素のリスト）だった。
- 仮の照合で、`aws:SourceArn` のような識別子として書けないキーのつなぎ方が raw IR と違い、1本だけ外れた。照合の側も `join_path` を使うことにした（手順5 の道具でも同じにする）。
- `Fn::Sub` の JSON を読むときの目印に `\u0000` を使ったら、JSON の文字列の中では許されず読めなかった。`json.loads(..., strict=False)` で読む。

### 第三者レビュー（判定「修正後コミット」）と対応
- レビュアーの確認: 自作 fixture の CFN 10 本（cfn-lint の辺 214 本）と、公開サンプルの CFN 33 本（辺 295 本。C01〜C05、serverless-patterns の SAM）で、CRITERIA の 1.6 の照合で**対応の無い辺は 0 件**。公開サンプルで落ちたテンプレートは無し（読めなかったのはテンプレートではない `event.json`・`parameters.json` だけ）。
- **M1** 長い形の文字列 `Fn::GetAtt: A.B` を読めず、参照を取りこぼしていた → 文字列なら最初の `.` で分ける（`getatt` と、評価しない値の中の参照を探す `_static_refs` の両方）。
- **M2** `Fn::ForEach::*`、本体がオブジェクトでないリソース、`!Sub` の変数に `AWS::NoValue` で例外のまま落ちていた → `Fn::ForEach` は `CFN-DEFERRED`（手順4）、形の崩れたリソースと `Type` の無いリソースは `CFN-MALFORMED-RESOURCE`（error）にして飛ばす。文字列の中の `AWS::NoValue` は `$unknown`。想定外の例外も終了コード 2 で返す。
- **R1** `$concat` に真偽値・null が残っていた → 真偽値は `true`／`false`、null は `$unknown`。
- **R2** タブで字下げした JSON（拡張子 `.template`）を読めなかった → `{` で始まれば先に JSON として読む。
- **R3** JSON の文字列が、印があれば `$json`、無ければ文字列になり、同じプロパティで形が揺れた → 印の無い JSON の文字列も `$json` にする（ir-schema.md の 7.2）。文字列の途中の JSON は `$unknown`。
- **R4** cfn-lint のグラフとの照合を回帰テスト（`CfnLintGraphTest`）にした。境界の入力のテストも足した。
- **R5** 文字列の途中の `{{resolve:…}}` を見つける、名前が計算になる `Fn::ImportValue` の診断に名前のひな形を残す、同じ診断を1つにまとめる、ドライブが違うときは root を絶対パスにして診断を出す。
- 軽微: `split_concat` の不要な条件を外した。
- テストは計 100 件。

---

## 2026-10-17（続き）フェーズ1 の手順3: SAM・ネストスタック・cdk.out

### やったこと
1. `adapters/cfn.py` を、スタックごとに評価する形（`Context` と `StackEval`）に組み直した。`Evaluator` に、address の前に付ける接頭辞、親から渡されたパラメータの値、子スタックの出力と Export の解決の入口を足した。
2. **ネストスタック:** 子テンプレートは、出力を使うときか、スタックのリソースを読むときに展開する（同じ子は1回だけ）。
   - 親の `Parameters` の値を評価して子に渡す。子の `List<…>`／`CommaDelimitedList` 型のパラメータでは `$concat` を区切り文字で分ける。
   - `!GetAtt Stack.Outputs.X` と `${Stack.Outputs.X}` は、子の出力を評価して元のリソースへの `$res` にする。たどった経路は `through` に、`from` の側から順に入れる（`AlbStack.Parameters.PublicSubnetIds` → `NetworkStack.Outputs.PublicSubnetIds`）。経路は印に一時的な `__through` を付けて運ぶ。
   - 子のリソースは address が `<親の論理ID>/<論理ID>`、`via: "nested_stack"`。evaluation のパラメータの名前にも同じ接頭辞を付ける。
   - `TemplateURL` は、手元のパスならそのまま読む。URL（`$concat` で組み立てたものは最後の文字列）なら、末尾から一致する要素が最も多い手元のファイルに読み替え、`evaluation.assumptions` に書く。CDK のネストスタックは `Metadata` の `aws:asset:path` で読む。読めない・2つ以上一致する子は黒箱（`via: "module_blackbox"`、診断 `CFN-NESTED-UNREADABLE`）。自分自身を読む子は `CFN-NESTED-CYCLE`。
3. **SAM:** `Globals` を、対応する型（Function、Api、HttpApi、SimpleTable、StateMachine、LayerVersion）のリソースに混ぜる（マップは中まで、リストは Globals の後ろにつなぐ、値はリソースの方）。`Events` の `Api`／`HttpApi` に API の指定が無ければ、暗黙の `ServerlessRestApi`／`ServerlessHttpApi`（`implicit: true`）を足す。
4. **cdk.out:** フォルダか `manifest.json` を受け取り、`aws:cloudformation:stack` のスタックをすべて読む。address は `<スタック名>::<論理ID>`（スタック名は `stackName`、無ければ artifact の ID）。各スタックの Export を先に登録し、`Fn::ImportValue` は Export した出力の値に置き換える（参照の `fn: "ImportValue"`、`through: ["Export:<名前>"]`）。
5. テスト: ネストスタック（three-tier-modules、URL の読み替えと黒箱、循環）、SAM（Globals、暗黙の API）、cdk.out（複数スタック、Export、ネストスタック）、cfn-lint のグラフとの照合を子テンプレートまで広げた（three-tier-modules の 53 本）。計 107 件が通過。

### 確かめたこと
- three-tier-modules（CFN）を root から読むと 41 リソース（正解 IR の CFN 側と同じ数）で、診断は 0 件（手順2 では、子のパラメータに値が無いという診断が 27 件出ていた）。ALB のサブネットは `NetworkStack/PublicSubnet1`・`2` への参照になり、サービスのタスク定義の環境変数の DB の接続先は、2つのスタックの出力をまたいで `DatabaseStack/DbInstance` の `Endpoint.Address` になった。
- 公開サンプル: ecs-refarch は S3 URL の子 7 つを読み替えて 63 リソース、VPCPeering は `!Sub` で組み立てた URL を読み替え、amazon-cloudfront-secure-static-site はローカルパスの子を展開。どれも raw IR の決まりを満たした。
- serverless-api の関数に、`Globals` の Runtime・Handler が混ざった。

### 第三者レビュー（判定「修正後コミット」）と対応
- レビュアーの確認: 親子をまたいだ C1 の照合で、three-tier-modules（辺 53）、ecs-refarch の master.yaml（C05。辺 90、S3 URL の子 7 つを読み替え）、amazon-cloudfront-secure-static-site（C01。辺 18）、VPCPeering の Requester（yaml・json。辺 1）と Accepter（C04。辺 5）の**すべてで対応の無い辺が 0 件**。同じ子を2回使う場合と2段のネストスタックの address・through も 7章どおり。
- **M1** 子の出力を評価できない（`Fn::If` など）と参照が消えていた → 出力の中の `pruned`／`unevaluated` の参照を、使った側の参照として `through` 付きで残す。出力の値に参照が残らないときは、スタックへの参照を `unevaluated` で残す。出力の診断の address をスタックにした。
- **M2** 親のスタックに `Condition` があっても子が `enabled: true` だった → 子は親の `enabled` を引き継ぎ、弱い方にする。
- **M3** 要素1つの `!Join` を List 型のパラメータに渡すとリストにならなかった → リストに包む。
- **M4** `Globals` を組み込み関数の中に混ぜて壊れた値を作っていた → 組み込み関数は1つの値として扱う。暗黙の API に `Globals.Api`／`Globals.HttpApi` を混ぜる（`EndpointConfiguration: PRIVATE` が消えて、プライベートな API を公開と誤るのを防ぐ）。`AWS::Serverless::StateMachine` の `Events` からも暗黙の API を作る。
- **R1（cdk.out）** Stage（入れ子のアセンブリ、`cdk:cloud-assembly`）を再帰で読む（asset のパスはそのアセンブリのフォルダから）。同じ `stackName` が2つ以上あるときは address に artifact の ID を使う（診断 `CFN-CDK-STACKNAME-DUPLICATE`）。Export の衝突は診断 `CFN-EXPORT-CONFLICT`（名前の順で最初のものを使う）。最上位を読む前に子のスタックをすべて展開し、子の Export も使えるようにした。Export の名前の中の `AWS::StackName` は、本当の `stackName` で解く（address の名前ではない。直すときに自分で見つけた誤り）。
- **R2** レビューの再現ケースと、公開サンプルのネストスタック5種の親子をまたいだ cfn-lint の照合を回帰テストにした。
- **R3** URL を読み替える候補から `node_modules`・`.git`・`cdk.out` などの下を除いた。
- 軽微: 循環の診断の address をスタックにした。YAML 1.1 の `On`／`Yes` などが真偽値になる件は、手順4 で条件の名前を引くときに気をつける（HANDOFF）。
- テストは計 114 件。

---

## 2026-10-17（続き）フェーズ1 の手順4: CloudFormation 側の評価（A4）

### やったこと
1. **条件:** `Conditions` を、真・偽・決まらない（`null`）の3つの値で評価する（`Fn::Equals`・`And`・`Or`・`Not`・`Condition`）。`Fn::Equals` は値を文字列にして比べる。条件の循環は `CFN-CONDITION-CYCLE`。評価したすべての条件を `evaluation.conditions` に書く（ネストスタックは `<スタック>/<名前>`）。
2. **リソースの `Condition`:** `enabled` を決める。ネストスタックの子は、親のスタックのリソースの値を引き継ぐ（弱い方）。決まらないときは `CFN-CONDITION-UNKNOWN`（info）。
3. **関数:** `Fn::If`（決まれば選んだ側を評価し、選ばれなかった側の参照は `pruned`。決まらなければ `$unknown` で中の参照は `unevaluated`）、`Fn::FindInMap`（`DefaultValue` を含む。無ければ `CFN-MAPPING-MISSING`）、`Fn::Length`、`Fn::ToJsonString`（`$json`）。
4. **パラメータの値:** アダプタに `--param KEY=VALUE` と `--param-file` を足した（CLI の `parameters.json` の形、`{"Parameters": {...}}`、`{キー: 値}`）。外から渡した値 → Default の順。`AllowedValues` に無い値は `CFN-PARAM-NOT-ALLOWED`、テンプレートに無い名前は `CFN-PARAM-UNUSED`。擬似パラメータ（`AWS::Region` など）に渡した値は、条件の評価にだけ使う（props は `$pseudo` のまま）。
5. **`Fn::ForEach`:** コレクションが決まれば展開する（`${Id}`・`&{Id}`・`Ref Id`）。決まらなければ1つだけを `multiplicity: "N"`、address は `Queue*` の形（`CFN-FOREACH-UNRESOLVED`）。
6. **YAML の真偽値:** `true`／`false` の書き方だけにした（YAML 1.1 の `On`・`Yes` などは文字列のまま）。
7. テスト: 条件の評価に合わせて、手順2・3 のテスト5件の期待を直した（決まらない条件で試したいものは、値の無いパラメータを使う形に）。A4 のテスト 9 件を足した。計 123 件が通過。

### 確かめたこと
- three-tier（CFN）を `EnvType=dev` と `prod` で読むと、`IsProd` が偽・真になり、IsProd のときだけ作るリソース（踏み台など）の `enabled` が切り替わる。DB の `MultiAZ`（`Fn::If`）と `DBInstanceClass`（`FindInMap`）も変わる。VPC の CIDR は `FindInMap` から `10.0.0.0/16`。警告・エラーの診断は0件（SSM の型のパラメータを除く）。
- vpc-endpoints（CFN）を `parameters.json`（`Project=net`）で読むと、VPC の名前が正解 IR と一致した（手順2 からの既知の差の解消）。
- cfn-lint のグラフとの照合（自作 fixture、three-tier-modules の親子、公開サンプルのネストスタック5種）は、条件を評価した後も対応の無い辺が 0 件。

### 第三者レビュー（判定「修正後コミット」）と対応
- レビュアーの確認: 正解 IR の CFN 側の網羅分類と raw IR を5構成で突き合わせ、address の集合・type・file・enabled（H-COND-FALSE は false、それ以外は true）が**すべて一致**（three-tier の dev 38、serverless-api 11、vpc-endpoints 33、rag 22、three-tier-modules 41）。公開サンプルの 33 本は落ちたものも不正な出力も無く、親子をまたいだ C1 の照合は 0 件のまま。手順2・3 のテスト5件の期待の直し方は妥当（元の意図を保ち、親の Condition の件は偽の場合も足して強くなった）。
- **M1** 外から渡すパラメータの値: List 型にリストを渡すと壊れた、`null`（`UsePreviousValue`）で Default を使わなかった、SSM の型でパラメータの名前を値にしていた → リストはそのまま、`null` は Default に進む、SSM の型は値を渡されても `$unknown`。CLI の形の `ParameterValue` の無い行は読まない。
- **M2** `Fn::ForEach`: 決まらない ForEach の ×N の名前が重なると1件消えた → 後ろに `.<ForEach の名前>` を付けて両方残す。展開した名前の重なりは `CFN-FOREACH-DUPLICATE`。プロパティの中と `Outputs` の中の ForEach も展開する。×N のひな形の識別子は `*` にする（未定義の Ref の警告にしない）。
- **R1** YAML の真偽値を true／false だけにしたのは、cfn-lint（YAML 1.1）と食い違い、`!Equals [yes, "true"]` などの評価が変わる → 値は YAML 1.1 に戻し、マップのキーだけ元の文字のまま読む。名前の位置の真偽値（`Condition: Yes`、`Ref: On`）は、同じ文字の名前が1つだけなら戻す。
- **R2** `Fn::FindInMap` の数字のキーと、`!Ref AWS::Region` で引く表 → キーは文字列で引き、キーの評価に擬似パラメータの値を使う。
- **R3** 条件が偽の関数から作る暗黙の API が `enabled: true` だった → 作る関数の enabled の強い方。条件が偽の出力の Export は登録しない（決まらなければ登録して診断）。
- **R4** 正解 IR との address・type・file・enabled の全件の突き合わせを回帰テスト（`ExpectedIrTest`）にした。レビューの再現ケースもテストにした。
- 軽微: 未定義の条件で診断が2つ出ていたのを1つにした。
- テストは計 130 件。

---

## 2026-10-17（続き）フェーズ1 の手順5: C1 の道具と、フェーズ1 の完了

### やったこと
1. `aws-iac-diagram-workspace/tools/c1_check.py` を作った（CRITERIA の 1.6 の照合を1か所にまとめた）。入力（テンプレートか cdk.out）を CFN アダプタで読み、展開した各ファイルを cfn-lint 1.57.2 にかけて、ファイルの address の接頭辞を付けて照合する。同じファイルを2つのスタックから使うときは接頭辞ごとに照合する。入力を省くと、`fixtures/cfn` と `fixtures/public` の CFN のテンプレートをすべて探し、ほかのテンプレートの子として読まれるものは親の側で照合する。結果は `--out` で JSON にも書ける。終了コードは 0（すべて対応）／1（対応の無い辺がある）／2（読めない）。
2. テストの中の照合の処理を、この道具を使う形にまとめ直した（`CfnLintGraphTest`）。
3. CI（`ci.yml`）の検証の手順に、`c1_check.py` を足した。
4. ir-schema.md の 7章（raw IR の形）を確定にした。README にアダプタと C1 の使い方を書いた。PLAN の状態を「フェーズ1 完了」にした。

### 結果
- `c1_check.py` を引数なしで流し、入力 25（自作 fixture の5構成、公開サンプルの CFN 20。C01〜C05 と SAM 版の T01s・T05s・T06s・T07s・T11s を含む）、cfn-lint の辺 **513 本のすべてに raw IR の参照が対応した**（対応の無い辺 0）。
- `raw_only`（raw IR にあって cfn-lint に無い参照）が出たのは、ネストスタックを持つ入力だけ（three-tier-modules 28、C01 11、VPCPeering の Requester 7、C05 41）。親から子の出力をたどった参照は raw IR では元のリソースを指すが、cfn-lint は同じものをスタックへの辺として数えるため。参考値。
- 単体テスト 131 件が通過。
- **フェーズ1 の完了基準**（テストが通る、cfn-lint のグラフの辺のすべてに raw IR の参照が対応する）を満たした。

### 第三者レビュー（判定「修正後コミット」）と対応
- レビュアーが手元で `c1_check.py` を引数なしで流し、入力 25・辺 513 本で対応の無い辺 0 を確かめた（約3秒）。
- **M1** 道具が cfn-lint の変換（`Transform`）の前のグラフを見ていた。`cfn-lint --build-graph` は、SAM の Globals を混ぜ Fn::ForEach を展開した後のグラフを出すので、Globals の中の参照と ForEach で作るリソースの辺が照合から漏れていた → `template.transform()` を呼ぶ（失敗したら終了コード 2）。いまの 25 入力では変換の前後で結果は同じ（513／0）。SAM の Globals と ForEach の入力をテストに足した。
- **M2** CRITERIA の 1.6 の文（「`Fn::*` の要素を除いてから前方一致」）と、道具の照合（「最初の `Ref`／`Fn::*` の位置で止めて前方一致」）が違う。正しく動くのは道具の方（除く方式では `Fn::If` の中の要素の位置がずれて外れる）→ **ユーザーの了承を得て**、CRITERIA の文を道具に合わせた。
- **R1** 探した入力が減っても気づけなかった → CRITERIA の 1.6 の対象（C01〜C05、SAM 版、自作 fixture）の一覧を道具に持たせ、引数なしのときに1つでも欠ければ終了コード 2。テストでも確かめる。
- **R2** 接頭辞を「論理ID の集合と address の末尾の一致」で求めていたので、Fn::ForEach で作る ID のファイルを黙って照合しなかった → address の最後の `/` か `::` までを接頭辞にする。
- **R3・R4** 既知の制約（cdk.out は実物で未確認、raw_only の理由）と、TF アダプタで raw IR に足しそうなものを HANDOFF に書いた。
- 軽微: 自作 fixture の辺の数を構成ごとに固定した（cfn-lint の挙動の変化に気づけるように）。`root_dir()` を簡単にした。
- テストは計 135 件。

---

## 2026-10-17（続き）フェーズ2 の手順1: Terraform アダプタの土台

### 概要
フェーズ2 を5つの手順に分けて進めることにした: 1=土台、2=A4（変数・locals・count／for_each・×N）、3=モジュールの再帰・A5・黒箱・H-IAM・`terraform_remote_state`、4=plan JSON、5=公開サンプルでの確認と完了。手順1 として、.tf を読んで raw IR（ir-schema.md の 7章）を出す土台を作った。

### やったこと
1. `skills/aws-iac-diagram/scripts/adapters/tf.py` を作った（PEP 723 で python-hcl2 8.1.4）。`uv run scripts/adapters/tf.py --input <ルートモジュールのフォルダ> --out <raw.json> [--root-base <フォルダ>]`。終了コードは 0（書けた）／2（読めない。フォルダでない、.tf が無いなど）。
   - フォルダ直下の `*.tf` を python-hcl2 の構文木（`parses_to_tree`）で読み、resource・data・module・locals・provider のブロックを集める。属性とブロックを props にし（ブロックは同じ名前のものをリスト）、メタ引数は props に入れない。`null` の属性は書かない。
   - 参照: resource・data・module への参照は `$res`（`attr` は最初の属性名）、`depends_on` は references にだけ。引数の無い `data.aws_region`・`aws_caller_identity`・`aws_partition` は `$pseudo`、`data.aws_availability_zones` の `names[n]`／`names` は `$az`。`jsonencode(...)` は `$json`。`"${…}"` と heredoc は `$concat`（JSON として読めれば `$json`。CFN と同じ規則）。入力の `$` で始まるキーは `$$` で逃がす。
   - `path.module`・`path.root`・`path.cwd` はルートからの相対パス（`"."`）、`terraform.workspace` は `"default"`（`evaluation.assumptions` に書く）。`file()`・`templatefile()` などはファイルを読まずに `$unknown`（`TF-UNEVALUATED`）で、引数の中の参照は `unevaluated`。
   - `provider = aws.<alias>` のリソースは `provider` と、その provider の `region`（文字列で決まるときだけ）を書く。
   - heredoc の開始と終端の行の末尾の空白を取ってから読む（T06。診断 `TF-HEREDOC-TRAILING-SPACE`、info）。読めないファイルは `TF-PARSE-ERROR`（error）にして、ほかのファイルは読む。`.tf.json` と override のファイルは、まだ読まない（warn）。
   - **後の手順に回したもの（評価していないと分かる形で出す）:** `var.*`・`local.*`・`count.index`・`each.*`・関数（`jsonencode` 以外）・条件式・演算・for 式・`%{…}`・`dynamic` は `$unknown`（`TF-DEFERRED`。中の参照は `unevaluated`。local は中の式をたどって参照を探す）。count・for_each のあるブロックは ×N（address は `[*]`、`multiplicity: "N"`、`enabled: null`、`TF-COUNT-DEFERRED`）で、インスタンスへの参照とスプラットも `[*]` への1つの `$res`。module はすべて黒箱の呼び出し1件（`type: module`、`via: module_blackbox`、source・version、props は入力。`TF-MODULE-DEFERRED`）で、`module.x.out` は `{"$res": "module.x", "attr": "out"}`。
2. CFN アダプタの、JSON の文字列を `$json` にする処理（`_maybe_json`）と `$` のキーの逃がし方を `lib/ir_raw.py`（`maybe_json`・`escape_keys`）に移し、2つのアダプタで共通にした。CFN の動きは変えていない（CFN のテストと C1 はそのまま通る）。
3. スキーマ: `ir-raw.schema.json` のリソースに、TF だけの任意のフィールド `provider`（`<名前>.<alias>`）と `region`（`provider` があるときだけ）を足した。ir-schema.md の 7.2 に TF の props・参照の `attr`・擬似パラメータと AZ・そのほかの値の書き方を、7.4 に heredoc の開始の行を、7.6 にフェーズ2 の進み具合の表（フェーズ2 の間だけ）を、8章に手順3・4 で決めること（`terraform_remote_state`、plan JSON の参照の重なり、モジュールに渡した provider の region）を書いた。
4. テスト `tests/test_tf_adapter.py`（20件。参照と props の位置、インスタンスとスプラット、モジュールの出力、擬似パラメータと AZ、テンプレートと逃がし方、`jsonencode` と heredoc の JSON、`path`・`terraform.workspace`・ファイルの関数、評価しない値の中の参照、×N、module の呼び出し、provider と region、heredoc の空白、CRLF、読めないファイル、CLI、正解 IR との突き合わせ（`ExpectedIrTest`）、fixture と公開サンプル）。`test_ir_schema_v1.py` に `provider`・`region` の検査を足した。計 155 件が通過（レビューの対応の後は 159 件）。
5. CI（`ci.yml`）の検証の手順に、自作 fixture の5構成を `uv run`（PEP 723 の依存だけ）で TF アダプタにかけ、`validate_ir.py` で調べる手順を足した。README に使い方を書いた。

### 決めたこと
| 決定 | 理由 |
|---|---|
| python-hcl2 の `load()` の辞書ではなく、構文木（`parses_to_tree`）を直接読む | 8.x の `load()` は式を `"${…}"` の文字列に戻し、`jsonencode` の中も HCL の文字列のまま返すので、参照の位置と `$json` の中身を取れない |
| ×N（count・for_each が決まらない）は `enabled: null` | 0 個かもしれない（`count = var.x ? 1 : 0` が多い）。正規化は `null` を描いて診断を残す（7.2） |
| `$res` の `attr` は最初の属性名 | `!GetAtt` の `B.C` と違い、TF の後ろの位置はリストの中や出力の中まで続くので、辺の判定に要る最初の名前だけにする |
| 擬似パラメータ・AZ にした参照は references に出さない | CFN の擬似パラメータ・`Fn::GetAZs` と同じ。provider の付いた data（別のリージョン・アカウント）は `$res` のまま |
| `path.module` は相対パス、`terraform.workspace` は `"default"`（前提に書く） | どちらも値が決まり、名前（K-NAME）に使われうる。`$pseudo` を増やさない |
| `file()`・`templatefile()` はファイルを読まない | 図に要るのは引数の中の参照（`unevaluated` で残る）で、ファイルの中身ではない |
| `provider`・`region` を任意のフィールドにする（既定の provider には書かない） | CloudFront の証明書（us-east-1）など、別のリージョンのリソースを正規化で見分けるため。既定のリージョンは CFN のスタックと同じく IR に持たない |
| 手順1 ではすべての module を黒箱の呼び出しにする | 黒箱は最終の形でもあるので、手順3 でローカル・要約表のものだけを中身に置き換えればよい |

### 確かめたこと
- 自作 fixture の5構成（TF）で raw IR を作り、`validate_ir.py` が通った。診断は warn・info だけ（error 0）。リソース・参照・診断の数: three-tier 33・49・58、serverless-api 29・38・15、vpc-endpoints 28・39・40、three-tier-modules 5・13・23、rag 41・65・25。
- 正解 IR の TF 側の網羅分類と、address・type・file・enabled が、手順1 の形に読み替えて5構成すべてで一致した（`ExpectedIrTest`。読み替えは count・for_each のインスタンスと count が 0 のブロック → `[*]`、モジュールの中身 → 呼び出し1件。それぞれ手順2・3 で正解 IR と同じ形になる）。three-tier の辺の根拠のうちモジュールと count をまたがないもの（リスナー → TG、サービス → TG、タスク定義の環境変数 → DB、ルート → NAT など）が active の参照として出ることも確かめた。
- 公開サンプルの TF のルート（T01〜T20、P01〜P04。survey_public.py の一覧で 52 フォルダ、815 リソース）で例外なく動き、すべて raw IR の検査を通った（約2秒）。error の診断は 0、T06 は heredoc の前処理の info が1件出て読めた。モジュールのフォルダも含めて `.tf` のあるフォルダをすべて読む確認（172 フォルダ、1969 リソース）でも失敗 0。
- 読めないファイル（構文の誤り）は `TF-PARSE-ERROR`（error）になり、同じフォルダのほかのファイルは読めることをテストで確かめた。
- `uv run`（PEP 723）で起動でき、CI に足した手順を、バックスラッシュを含む `RUNNER_TEMP` を与えて手元の bash で流して通った。

### つまずいたこと
- python-hcl2 8.1.4 の `load()` は式を文字列に戻すので使えなかった（上の「決めたこと」）。heredoc は1つの字句で、中の `${…}` は解析されないので、自分で分けてから式を読む。
- heredoc の終端の後ろだけでなく、開始の `<<EOF` の後ろに空白があっても読めない（文法の正規表現が直後の改行を求める）。両方を取るようにした。
- Bash のヒアドキュメントに `\n` を含む HCL を渡すと化けた（既知）。サンプルは Write ツールで書いた。
- `main()` の `sys.stdout.reconfigure` が、テストで標準エラーを `StringIO` に差し替えると落ちた。`reconfigure` があるときだけ呼ぶ。
- モジュールのフォルダを単独で読むと、呼び出し側から渡される provider の alias が「設定が無い」ように見える。warn ではなく info（`TF-PROVIDER-UNCONFIGURED`）にした。

### 第三者レビュー（判定「修正後コミット」）と対応
- **M1** heredoc の前処理（`fix_heredocs`）で、終端が見つからない開始の行があると、そこからファイルの末尾まで飛ばして後ろの heredoc を調べなかった。コメントにした heredoc（`#   policy = <<EOF` … `#   EOF`）の後ろに、終端に空白のある heredoc があると直らず、ファイル全体が `TF-PARSE-ERROR` になった → 終端が無ければ次の行から調べ直す。`<<` より前に `#` か `//` がある行は開始として扱わない。この入力をテストにした。
- **R1** AWS provider v6 のリソースの引数 `region`（文字列）を、provider の設定の region より優先してリソースの `region` に書く（Terraform と同じ。AWS の型だけ）。Schema の「`region` には `provider` が要る」を外した。ir-schema.md の 7.2 に、モジュールの中の既定のリージョンは手順3 で決めること、同じリージョンを指す alias（`aws.primary` など）を alias の名前だけで別のリージョンとして扱わないことを書いた。
- **R2** 出力を書けない（`--out` の親がファイルなど）ときに例外のまま落ちていた → 終了コード 2 と日本語のメッセージにした。
- 任意: CFN アダプタの使っていない `_escape_keys` を消した。古い書き方の `provider = "aws.w"`（文字列）も読む（読めない形は `TF-MALFORMED-BLOCK` の warn）。7.2 にスカラーの `$json`（`jsonencode("x")`）もあると書いた。Terraform が読まないファイル（`.` で始まる、`~` で終わる、`#…#`）を読まないようにした。`test_known_references` に serverless-api（ESM → DynamoDB のストリーム、サブスクリプション → SQS）・vpc-endpoints（SG のルール → SG、Gateway エンドポイント → ルートテーブル）・rag（データソース → S3、S3 通知 → Lambda、REST の統合 → Lambda）を足した。CI の Windows PowerShell 5.1 の手順で、日本語のパスに置いた SKILL の `tf.py` を1回 `uv run` する（手元の PowerShell 5.1 で同じ手順を流して通った）。
- 見送り（HANDOFF の 3a に書いた）: `ephemeral` ブロック（`ephemeral.*` への参照はいまは `TF-UNDEFINED-REF`）と `check` ブロックの中の `data` は手順2、`.tf.json` と override のファイルは手順2・3 で扱う。
- 確かめたこと: テスト 159 件が通過。自作 fixture の5構成の raw IR が `validate_ir.py` を通る（数は変わらず）。`c1_check.py` は入力 25・辺 513 本・対応の無い辺 0。公開サンプルの TF のルート 52 フォルダと、`.tf` のあるフォルダすべて（172）で失敗 0、error の診断 0。

---

## 2026-10-17（続き）フェーズ2 の手順2: Terraform 側の評価（A4）

### 概要
TF アダプタ（`scripts/adapters/tf.py`）で、変数・locals・式を評価し、count・for_each をインスタンスごとに展開するようにした。手順1 で `$unknown`（`TF-DEFERRED`）・×N（`TF-COUNT-DEFERRED`）にしていたものを置き換えた。第三者レビューの前（未コミット）。

### やったこと
1. **評価器** `scripts/lib/tf_eval.py`（標準ライブラリだけ）を作った。評価の中の値の型（`Res`・`Pseudo`・`Az`・`Concat`・`Json`・`Unknown`・`ZeroColl`）と、組み込み関数、variable の type による変換（`convert`）。`Unknown` は中にあった参照を持ち歩き、tf.py が書き出すとき（`materialize`）に `$unknown` にして、参照を `unevaluated` で残し、診断を書く（評価の途中では診断を書かないので、locals の値をキャッシュできる）。
   - 関数（81。`try`・`can` を含む）: 数（`abs`・`ceil`・`floor`・`max`・`min`・`pow`・`signum`・`parseint`・`sum`）、文字列（`chomp`・`format`・`formatlist`・`indent`・`join`・`lower`・`upper`・`title`・`replace`（`/正規表現/`）・`split`・`strrev`・`substr`・`trim`・`trimprefix`・`trimsuffix`・`trimspace`・`startswith`・`endswith`・`strcontains`・`regex`・`regexall`）、コレクション（`alltrue`・`anytrue`・`chunklist`・`coalesce`・`coalescelist`・`compact`・`concat`・`contains`・`distinct`・`element`・`flatten`・`index`・`keys`・`length`・`lookup`・`matchkeys`・`merge`・`one`・`range`・`reverse`・`setintersection`・`setproduct`・`setsubtract`・`setunion`・`slice`・`sort`・`transpose`・`values`・`zipmap`）、変換（`tobool`・`tolist`・`tomap`・`tonumber`・`toset`・`tostring`・`nonsensitive`・`sensitive`・`ephemeralasnull`）、符号化（`jsonencode`・`jsondecode`・`base64encode`・`base64decode`・`urlencode`・`basename`・`dirname`）、ネットワーク（`cidrsubnet`・`cidrsubnets`・`cidrhost`・`cidrnetmask`）、`try`・`can`。公開サンプル（746 ファイル）で使われている関数を数えて選んだ（`try` 1413、`coalesce` 212、`merge` 190、`cidrsubnet` 173、`length` 155、`lookup` 139、`element` 120 など）。ファイル・時刻・乱数・ハッシュの関数（`file`・`templatefile`・`timestamp`・`uuid`・`md5`・`yamlencode` など）は評価しない（`TF-UNEVALUATED`）。
2. **変数**: `variable` の default → `terraform.tfvars` → `terraform.tfvars.json` → `*.auto.tfvars(.json)`（名前順）→ `--var-file`・`--var`（指定した順。argparse の Action で1つのリストに入れる）。`build_raw(..., var_files=, vars=, var_args=)`。`--var-file` の相対パスは作業中のフォルダ、無ければ `--input` から（`--var-file env\dev.tfvars` で three-tier の dev を読める）。`--var` は type が複合の型なら HCL の式として読む。type に合わせて変換（`optional` の既定値を含む）。`sensitive = true` の変数の値は使わない。`evaluation.var_files`・`vars` を書く。値の無い変数があれば、自動では読まれない `*.tfvars` の候補を `TF-UNRESOLVED-VARS`（info）に書く（CRITERIA の 6 の「環境が複数ある入力」で、どれを渡すかを確かめるため）。
3. **式**: locals（遅延評価とキャッシュ、循環は `TF-CYCLE`）、テンプレート（クォートした文字列と heredoc を同じ字句の並びにして、`%{if}`・`%{for}`・`~` を評価）、条件式、演算（`&&`・`||` は片方で決まれば決める）、for 式（`if`、`...`）、オブジェクトの計算したキー、関数の `...`、`try`・`can`。Terraform なら誤りになる式は `$unknown`（`TF-EVAL-ERROR`）。
4. **count・for_each**: 値が決まればインスタンスごと（`[0]`・`["key"]`）に出し、`count.index`・`each.key`・`each.value` を評価する。0 個なら添字なしの1件を `enabled: false`（H-COND-FALSE）。決まらなければ ×N（`TF-COUNT-UNRESOLVED`）。インスタンスへの参照（`aws_subnet.private[0].id`）とスプラット（インスタンスごとの `$res` のリスト）、for_each のリソースのマップ（`aws_route.r["get"]`、`values(aws_x.y)`）、作られないブロックへの参照（添字なしの address）、決まらない添字（すべてのインスタンスへの `unevaluated`）。`depends_on` はすべてのインスタンスへ。`data.aws_availability_zones.x.names[count.index]` は `$az`（番号）、`slice(names, 0, 2)`・`element(names, i)` も `$az` のリスト・番号。`dynamic` ブロックを展開する（`iterator`、入れ子）。module の呼び出しも count・for_each で展開する（中身は手順3 まで黒箱）。provider の `region` が変数で決まるものも書く。
5. **手順1 から回したもの**: `ephemeral` ブロック（`resources` に載せず、参照は `$unknown`（`TF-EPHEMERAL`、info）で、ブロックの中の参照を残す）、`check` ブロックの中の `data`、override のファイル（Terraform の規則で重ねる）。`.tf.json` は手順3 以降に回した（下の「決めたこと」）。
6. **テスト**: `tests/test_tf_adapter.py` を 24 件から 43 件にした（計 178 件）。`ExpectedIrTest` の count・for_each と H-COND-FALSE の読み替えを外し（`step3_expected()` はモジュールの中身だけを読み替える）、5構成でインスタンス単位の網羅分類と一致させた（three-tier は `env/dev.tfvars`）。three-tier の dev／prod／変数なし、vpc-endpoints の `terraform.tfvars` で結果が変わること、正解 IR のノードの名前が props に出ること、変数の優先順位・CLI の順・型の変換・sensitive、式・pruned・誤り、インスタンス・dynamic・module の展開、ephemeral・check・override、評価器の関数（値が決まるもの・印を含むもの）と型の変換のテストを足した。手順1 のテストのうち、評価しないことを前提にしていたもの（`TF-DEFERRED` を期待するもの）は、値の無い変数で同じことを試す形に直した。
7. **文書**: ir-schema.md の 7.1（`var_files`・`vars`）、7.2（A4（TF）、count・for_each、そのほかのブロック、作られないブロックの診断）、7.3（TF の `pruned`）、7.5（TF の診断の code の一覧）、7.6（手順2 を済に）、8章（リソースの属性の値を設定から決めるか）。README の使い方、CI の Windows PowerShell 5.1 の手順に `--var-file`・`--var` を足した。ir-raw.schema.json は変えていない（`var_files`・`vars` は手順1 から Schema にある）。

### 決めたこと
| 決定 | 理由 |
|---|---|
| 評価の中の値を、raw IR の印（dict）ではなく専用の型で持ち、書き出すときに印にする | `$unknown` の中の参照と診断を、値が使われた位置で書くため（locals は1回だけ評価して、使ったところごとに書ける）。入力の `$` のキーと印を取り違えない |
| 環境変数 `TF_VAR_*` は読まない | 同じ入力から同じ IR を出すため（C5）。要るときは `--var` で渡す |
| `sensitive = true` の変数の値は使わない（`$unknown`、info。`evaluation.vars` にも書かない） | パスワードなどを IR と `result.json` に書かないため。count や条件に使うことは Terraform でも禁止されている |
| count が 0・for_each が空のブロックも props と参照を出し、そこへの参照は添字なしの address にする | CFN の `Condition` が偽のリソースと同じ扱い（網羅分類の H-COND-FALSE、参照の照合）。props の中の評価できない値の診断は info（Terraform もそのブロックを評価しない） |
| `pruned` は、条件式の選ばれなかった側・`try` の使わなかった式・選ぶ関数（`coalesce`・`element`・`slice` など）とリストの添字・for 式の `if` で除いた要素だけ。マップ・オブジェクトのキーや属性で引かなかった値、決まった count・for_each の式の参照は残さない | 最初はすべての「値に残らなかった参照」を `pruned` にしたが、公開サンプルの flink（T20）で `each.value.x` のたびに他のキーの参照が出て、active 86 に対して pruned 224 になった。CFN の `Fn::If`・`Fn::Select` に当たるものに絞った（CFN の `Fn::FindInMap` のマップは参照を含まない。`Fn::ForEach` のコレクションの参照も残していない）。同じリソースへの参照が値に残っていれば、属性が違っても `pruned` にしない |
| 決まらない値を含む関数は、構造だけで決まるもの（`length`・`concat`・`merge`・`lookup`・`element`・`join`・`format` など）は印を残したまま評価する | `concat(aws_subnet.a[*].id, …)`、`format("arn:%s", aws_x.arn)` のような参照を、`$unknown` にせず辺の根拠として残すため |
| 文字列（変数の値を含む）が JSON のオブジェクト・配列として読めれば `$json` にする | 7.2 の規則（同じプロパティが値によって文字列になったり `$json` になったりしないように）を、評価した値にも当てる。`evaluation.vars` は入力のままの値（`$json` にしない） |
| `.tf.json` は手順3 以降に回す | JSON の書き方では、入れ子のブロックと属性（オブジェクトの値）の区別に provider のスキーマが要る（props の形が plan JSON と揃わない）。公開サンプルにも無い |
| ×N のブロックの `count.index`・`each.*` の診断は info（×N の warn は1つだけ。レビューの後、code を `TF-COUNT-INDEX` に分けた） | ×N の原因は count・for_each の位置の warn（`TF-COUNT-UNRESOLVED`）に書いてあり、使ったところごとの warn は増えるだけになるため |

### 確かめたこと
- 自作 fixture の5構成: 正解 IR の TF 側の網羅分類と、address・type・file・enabled がインスタンス単位で一致（モジュールの中身だけ手順3 の読み替え）。three-tier（dev）39・serverless-api 30・vpc-endpoints 38・rag 41・three-tier-modules 5 リソース。warn の診断は rag の `sha1()`（API のデプロイの再作成の引き金）の1件だけ。three-tier は dev／prod で踏み台（`aws_instance.bastion`・`aws_security_group.bastion`）が `enabled: false`／`[0]` に、DB の `instance_class`・`multi_az`・`final_snapshot_identifier`、サービスの `desired_count` が変わる。変数を渡さないと `environment` が決まらず、踏み台は ×N、`TF-UNRESOLVED-VARS` に `env/dev.tfvars, env/prod.tfvars` が出る。vpc-endpoints は `terraform.tfvars` の `project = "net"` で名前が正解 IR のノード（`net-private-ap-northeast-1c` など）と一致。
- 診断の数（手順1 → 手順2）:

  | 対象 | warn | info | 主な変化 |
  |---|---|---|---|
  | 自作 fixture 5構成（変数のファイルなし） | 139 → 8 | 22 → 5 | `TF-DEFERRED` 139 → 0、`TF-COUNT-DEFERRED` 18 → 0。残りは three-tier の `environment`（5）と踏み台の ×N（2）と rag の `sha1()`。three-tier に `env/dev.tfvars` を渡すと warn 1 |
  | 公開サンプルの TF のルート 52 | 2054 → 130 | 179 → 164 | `TF-DEFERRED` 2045 → 0。×N のブロック 35 → 7。残りは値の無い変数（`TF-UNRESOLVED-VAR` 61。ルートにも default の無い変数がある）、data・モジュールの出力に依る値（`TF-UNEVALUATED` 60）など |
  | `.tf` のあるフォルダすべて 172 | 7156 → 821 | 992 → 2293 | ×N のブロック 616 → 53（ほかに 357 件が count 0 で `enabled: false`）。info が増えたのは、×N の `count.index` の info（1778。モジュールのフォルダを単独で読むと変数に値が無いため） |

  リソースはルート 52 で 815 → 854、すべてのフォルダで 1969 → 2076（インスタンスの展開）。例外 0、error 0、すべて raw IR の検査を通った（ルート 52 で約 2.6 秒、172 フォルダで約 8 秒）。
- テスト 178 件が通過。`c1_check.py` は入力 25・辺 513 本・対応の無い辺 0（CFN は変えていない）。`uv run`（PEP 723）で `--var-file env\dev.tfvars --var project=demo` を PowerShell 5.1 から流し、`validate_ir.py` を通った（CI に足した手順と同じ）。

### つまずいたこと
- python-hcl2 の構文木では、オブジェクトのキーの `(k)`（式として評価する）と `k`（名前）が、括弧の字句を見ないと区別できない（`sig()` が括弧を落とす）。`identifier_name()` で括弧の有無を見る。
- クォートした文字列の `%{if}`・`%{for}` は、python-hcl2 では入れ子にならず、開始・終了の平らな規則（`template_if_start` など）で並ぶ。heredoc は1つの字句のまま。どちらも同じ字句の並び（`string_tokens`・`text_tokens`）にしてから入れ子を組み立てた。
- 「値に残らなかった参照をすべて pruned」にしたら、`aws_subnet.s[0]` のようなインスタンスの添字でも他のインスタンスが pruned になり、for 式の `s.arn` でも属性が変わったことで元の参照が pruned になった。リソースのまとまり（`ResList`・`ResMap`）の添字は除き、同じリソースが値に残れば pruned にしない形にした。最後は上の「決めたこと」のとおり、CFN に当たるものだけに絞った。
- `try(local.m.c, …)` の最初の式が誤りになると、その中の参照が消えた。誤りになった式の参照を、式からたどって `pruned` にする。
- Bash のヒアドキュメントで渡した Python の文字列の `\\` が `\` に化けた（既知）。README と CI の Windows のパスを含む書き換えは Edit ツールで行った。
- 作られない（count が 0）ブロックの props を評価すると、モジュールのフォルダ（変数に値が無い）で `TF-EVAL-ERROR` が 61 件出た（null の属性など）。Terraform も評価しないので info にした。

### 第三者レビュー（判定「修正後コミット」）と対応
- **M1** `sensitive()` が値をそのまま返し、変数は `sensitive = true` しか見ていなかった。`password = sensitive(var.pw)`、`locals { token = sensitive("tok-123") }`、`variable "eph" { ephemeral = true }` の値が props と `evaluation.vars` に出た → `sensitive()` は `$unknown`（`TF-SENSITIVE-VAR`、info。中の参照は引き継ぐ）を返す。`ephemeral = true` の変数は `sensitive = true` と同じ扱い（値を使わず、`evaluation.vars` にも書かない）。7.2 に書いた。
- **R2** 作られないブロックの中で、`TF-UNDEFINED-REF`・`TF-CYCLE` まで info に下がっていた → 下げるのは値が決まらないことによる code（`TF-UNRESOLVED-VAR`・`TF-EVAL-ERROR`・`TF-UNEVALUATED`・`TF-UNSUPPORTED-FUNCTION`）だけにし、参照の誤りと循環は warn のまま。
- **R3** count が文字列の数（型の無い変数に `--var n=2` で渡した値、`count = "2"`）だと ×N になっていた → 文字列なら数に変換する（変換できなければ `TF-EVAL-ERROR` の ×N）。for_each（マップか文字列の集合）と dynamic の for_each には同じ問題は無い。
- **R1** `sensitive` の印の無い秘密の値（tfvars のパスワードなど）が `evaluation.vars` と props に出る → ユーザーに確認し、「両方」に決まった（2026-10-17）:
  - (a) `evaluation.vars` には値を書かず、宣言したすべての変数の値の出どころだけを書く（`{"source": "env/dev.tfvars" | "--var" | "default" | null}`、値を使わない変数は `"hidden": "sensitive" | "ephemeral" | "redact-var"`）。ir-raw.schema.json の `vars` の形を変え、ir-schema.md の 7.1、`test_ir_schema_v1.py` の例を合わせた（`validate_ir.py` は Schema で調べるので変更なし）。props は今のまま評価した値を入れる。
  - (b) `--redact-var <名前>`（何回でも指定できる。`build_raw(redact_vars=...)`）で指定した変数の値を伏せる（`sensitive = true` と同じ扱い。`$unknown`、中の参照は保つ、診断は info）。宣言に無い名前は `TF-VAR-UNDECLARED`（warn）。
  - (c) README と SKILL.md に「`sensitive` を付けていない変数の値は props（図のラベルなど）に入りうる。伏せたいものは `sensitive` を付けるか `--redact-var` を使う」と書いた。
  - 「決めたこと」の表の「`evaluation.vars` は入力のままの値」は、この対応で「値を書かない」に変わった。
- 任意（すべて対応）:
  1. `element(aws_subnet.p[*].id, count.index)` で、選ばなかった同じブロックの別のインスタンスが N×(N−1) 件 `pruned` になっていた → `pruned` にするかの比較を、インスタンスの添字を除いたブロックの address（`block_address()`）で行う。
  2. ×N と作られないブロックの `count.index`・`each.*` の info を `TF-COUNT-INDEX` に分けた（`TF-COUNT-UNRESOLVED` は count・for_each の位置の warn だけ）。
  3. `urlencode` を Go の `QueryEscape` と同じに（空白は `+`）。数の演算を Decimal（34桁）で行い、`0.1 + 0.2` が `0.3` になる。`range()` の 1024 個での打ち切りを `TF-EVAL-ERROR` に。`can(x)` は `x` の値の全体が決まらなければ `$unknown`。
  4. 別のドライブの `--var-file` は、`evaluation.var_files` にファイル名だけを書き、`TF-VARFILE-OTHER-DRIVE`（info）を出す（ユーザー名を含む絶対パスを書かない）。
  5. tf.py の docstring の `pruned` の説明を実装（決まった count・for_each の式の参照は残さない）に合わせた。
  6. 変数のファイルを読めないときの誤りの文に lark の字句（値の一部）が入っていた → パスと行・列だけにする。
- テストを7件足した（`ReviewFixTest`。M1・R1 の `--redact-var`・R2・R3・数と range・urlencode・can・変数のファイルの誤りの文・別のドライブ）。既存のテストの期待を直した（element の pruned、`TF-COUNT-INDEX`、`evaluation.vars` の形）。
- 確かめたこと: テスト 185 件が通過。5構成（three-tier は変数なし・dev・prod）の raw IR を `uv run` で作り、`validate_ir.py` が通った（dev・prod は診断 0）。`c1_check.py` は入力 25・辺 513 本・対応の無い辺 0。公開サンプルの TF のルート 52 で例外 0・error 0・検査を通る（warn 130、info 164 は変わらず。info の内訳で `TF-COUNT-UNRESOLVED` の一部が `TF-COUNT-INDEX` 6 に移った）。172 フォルダすべても失敗 0（warn 821）。

---

## 2026-10-17（続き）フェーズ2 の手順3: モジュール

### 概要
TF アダプタで、モジュールの呼び出しを展開するようにした。ローカルモジュールは中身を再帰的に読み、terraform-aws-modules の vpc・alb・rds・eks は A5 の要約表（`references/module-summaries.md`）で展開し、それ以外は黒箱の呼び出しにする。手順2 まで `TF-MODULE-DEFERRED` で黒箱にしていたものを置き換えた。第三者レビューの前（未コミット）。

### やったこと
1. **ローカルモジュールの再帰**（`scripts/adapters/tf.py`）: `ModuleEval` を呼び出しのインスタンスごとに作る（親・呼び出しの引数・`count.index`／`each` の環境・`enabled`・×N・経路・深さ・provider の対応を持つ）。子の address は呼び出しの address を前に付け（`module.app.…`、`module.m[0].…`、`module.db.module.db_instance.…`）、`module` フィールドに書く。子の変数は、呼び出しの引数を親の中で遅延評価し、type の変換・default・`nullable = false`・sensitive／ephemeral はルートと同じ。親から見た `module.x.y` は子の出力 `y` の値（`ModObj`）。どちらもたどった経路を `through`（`module.x.var.y`・`module.x.output.y`、`from` の側から順）に足す。評価の中の参照は `(to, attr, through)` の3つ組にし（`Res` に `through` を足した）、書き出すときに一時的な `__through` で運んで references に移す（CFN の `__through` と同じ考え方）。count が 0 の呼び出しの中は添字なしで `enabled: false`、決まらない呼び出しの中は `module.n[*].…` で ×N。呼び出しの `depends_on` は中のすべてのリソースに付け、`depends_on = [module.x]` は中のすべてのリソースへ。循環（経路にあるフォルダ）・深さ（16 段）・読めないフォルダは黒箱（`TF-MODULE-CYCLE`・`TF-MODULE-DEPTH`・`TF-MODULE-UNREADABLE`）。手順1 の懸念だった `module.alb.target_groups["app"].arn` は、出力 `target_groups`（`aws_lb_target_group.this`）をたどって `module.alb.aws_lb_target_group.this["app"]` の `arn` になった。
2. **A5 の要約表**（`references/module-summaries.md`、読み込みは `scripts/lib/tf_modules.py`）: 本物のモジュールの主要なリソース・出力を、count・for_each の式と名前・参照の属性ごと HCL で写し、ローカルモジュールと同じ評価器で展開する（`via: module_summary`、`file` は呼び出しのあるファイル）。対象は vpc 6.x、alb 10.x、rds 7.x（サブモジュール `db_instance`・`db_subnet_group`・`db_parameter_group`・`db_option_group`）、eks 21.x（サブモジュール `eks-managed-node-group`・`fargate-profile`・`self-managed-node-group`）。表の中の `data` と count が 0 のリソースは載せない（`try(aws_x.y[0].id, null)` は `null`）。版は `version` の制約が許す major の表を使う（無い・上限が無いときは前提に書く）。写していないリソースを作る入力は `TF-MODULE-SUMMARY-INPUT`、表に無い出力は `TF-MODULE-SUMMARY-OUTPUT`。
3. **黒箱と H-IAM:** 要約表に無い・版が合わないレジストリモジュール、`git::` などは黒箱（`TF-MODULE-BLACKBOX`、理由を message に）。IAM だけのモジュールは source の一覧（module-summaries.md の 4章、`tf_modules.iam_only()`）で判定し、raw IR では黒箱のまま（正規化が `H-IAM`）。
4. **provider と region:** リソースの provider の名前を、呼び出しの `providers` 引数と既定の provider の引き継ぎでたどり、設定のあるモジュールの名前にする（alias なら `provider` と、その設定の `region`）。黒箱の呼び出しも `providers` の `aws` から書く。リソースの引数 `region`（vpc モジュールの `region = var.region`）が優先。
5. **`terraform_remote_state`:** state を読まず data のまま載せ、`outputs.vpc_id` への参照は `attr: "outputs.vpc_id"`。
6. **評価器の小さな直し**（公開サンプルのモジュールを展開して見つけたもの）: `try()`・`can()` の中では、count が 0 のブロックの添字を誤りにして次の式に進む（vpc モジュールの `try(aws_vpc_ipv4_cidr_block_association.this[0].vpc_id, aws_vpc.this[0].id, "")` が、作られない関連付けを指していた）。`regexall()` の文字列が `$az` のときはマッチの数だけを決める（vpc モジュールの AZ 名・AZ ID の判定で、サブネットの `availability_zone` が `$unknown` になっていた）。`lookup()` の空のマップは既定値を返す（`*_tags_per_az` で `Name` タグが消えていた）。
7. **テスト**（`tests/test_tf_adapter.py`、50 → 64 件。計 199 件）: `ExpectedIrTest` の `step3_expected()` の読み替えを外し、5構成でモジュールの中身（`via`・`module` を含む）まで正解 IR の TF 側の網羅分類と一致させた。three-tier-modules の境界をまたぐ参照（リスナー → TG、サービス → TG、SG ルール → ALB の SG、タスク定義の `DB_HOST` → DB、DB の SG → app の SG、ルート → NAT など 10 件）を `test_known_references` に足した。`ModuleTest`（再帰と through、count／for_each／0／×N の呼び出し、出力のオブジェクトの属性、境界をまたぐ参照と depends_on、秘密の値、循環・深さ・読めない・宣言の無い引数、provider と region、`terraform_remote_state`）と `SummaryTest`（表のファイル、版の選び方、source の見分けと H-IAM、展開の診断、**vpc・eks の要約表と手元の本物のソースの展開の突き合わせ**）を足した。
8. **文書:** ir-schema.md の 2章（黒箱の対象・H-IAM の判定）、4章（`module_summary`・ローカルモジュールの `file`）、7.1（モジュールの変数の `evaluation.vars`）、7.2（「TF のモジュール」を新設。region・`$res` の `attr`・`.tf.json` の行を直した）、7.4（`terraform_remote_state`）、7.5（code）、7.6（手順3 を済に）、8章（決めた2項目を7章へ移し、`.tf.json` を足した）。README の使い方。ir-raw.schema.json は変えていない（`module`・`via`・`through` は手順1 から Schema にある。`evaluation.vars` の `source` の `"argument"` も今の形で通る）。

### 決めたこと
| 決定 | 理由 |
|---|---|
| 要約表は Markdown の表ではなく、本物と同じ書き方の HCL（主要なリソース・出力だけ）にし、ローカルモジュールと同じ評価器で展開する | NAT の数（`single_nat_gateway`・`one_nat_gateway_per_az`）、ルートテーブルの数と関連付け、for_each のキーなど、入力で変わる中身を本物と同じ式で決めるため。表の形を別に作ると、条件の書き方を独自に決めることになり、本物との突き合わせもできない |
| 要約表の置き場は PLAN のとおり `references/module-summaries.md`。`<!-- module-summary source="…" majors="…" -->` の直後のコードブロック | 1ファイルで人も読め、版ごとの表を並べられる。サブモジュールは `//modules/x` を付けた source の表にし、表の中の `./modules/x` も同じ版の表で展開する |
| 対象の版: vpc 6.x、alb 10.x、rds 7.x、eks 21.x。ほかの major は黒箱 | 手元にソースがあるのは vpc v6.7.3 と eks v21.29.0（P01・P03）。alb・rds は fixture を作ったときに読んだ v10.5.1・v7.2.2 の記録に合わせた。版が違うと変数名やリソースが変わる（eks の 20.x と 21.x など）ので、推測しない（CRITERIA の 2.3 の A5） |
| rds-aurora は要約表にしない | 公開サンプルにレジストリから呼ぶものが無く、P04 は `source = "../../"` で手元のソースを読む（ローカルモジュールとして展開される） |
| 要約表の中の `data` と count が 0 のリソースは載せない。表の中では count が 0 のブロックの添字は誤り | 正解 IR の `module_summary` の決まり（4章）。載せないブロックへの参照が残らないように、Terraform と同じく `try` で `null` にする |
| 写していないリソースを作る入力は info の診断（`TF-MODULE-SUMMARY-INPUT`）にし、表に無い出力の参照は warn（`TF-MODULE-SUMMARY-OUTPUT`） | 図に出ないリソースがあることを結果に残す（推測して描かない）。出力の参照が消えると辺の根拠が欠けるので warn |
| IAM だけのモジュールは、source の一覧（`terraform-aws-modules/iam/aws` とそのサブモジュール）で判定する。raw IR では黒箱のまま | 中身を読まないので、IAM だけかは source でしか分からない。分類（H-IAM）は正規化の仕事（7章）。ローカルモジュールは中身を読むので型ごとの H-IAM で足りる |
| `terraform_remote_state` は state を読まず、出力への参照を `attr: "outputs.<名前>"` にする | 別の構成の state は手元に無く、秘密の値も入りうる。CFN のネストスタックの `Outputs.<名前>` と同じ形にし、正規化が「別の構成の値」と見分けられるようにする |
| モジュールの中の provider は、`providers` 引数と既定の provider の引き継ぎでたどり、設定のあるモジュールの alias の名前と region を書く | 手順1 で決めた「region の値で別のリージョンを見分ける」をモジュールの中にも当てる。子の中の alias の名前（`aws.east`）は呼び出しごとに違う設定を指すので、設定の側の名前にする |
| `.tf.json` は手順4・5 に回す | 入れ子のブロックと属性の区別に provider のスキーマが要る事情は変わらない。plan JSON の `configuration` で同じ区別ができるかを見てから決める。公開サンプルにも無い |
| 手元のローカルモジュールの変数は `evaluation.vars` に `module.x.<名前>` で書く（値は書かない、出どころは `"argument"`・`"default"`・`null`） | どの変数が呼び出しで渡され、どれが既定値・値なしかを確かめるため。要約表の変数は既定値ばかりで量が多いので書かない |

### 確かめたこと
- 自作 fixture の5構成: 正解 IR の TF 側の網羅分類と、address・type・file・enabled・`via` がすべて一致（three-tier-modules は 5 → 42 リソース。vpc 25・alb 6・rds 1 が `module_summary`、app 9 がローカルモジュールの中）。three-tier-modules の診断は info の `TF-MODULE-SUMMARY` 3件だけ（warn 0）。タスク定義の `DB_HOST` は `module.db.module.db_instance.aws_db_instance.this[0]` の `address` への active の参照になり、`through` は `module.app.var.environment` → `module.db.output.db_instance_address` → `module.db.module.db_instance.output.db_instance_address`。サービスの TG は `module.alb.aws_lb_target_group.this["app"]` の `arn`（through `module.app.var.target_group_arn` → `module.alb.output.target_groups`）。
- **要約表と本物のソースの突き合わせ**（`SummaryTest`）: vpc（`fixtures/public/terraform-aws-vpc`、v6.7.3）を3通りの入力で、手元のソースをローカルモジュールとして読んだ結果と要約表の結果を比べ、作られるリソースの address（25・39・17）、表のリソースの間の active の参照、名前とタグが一致した。eks（v21.29.0）は、ノードグループ3種・アドオン・アクセスエントリを渡した入力で、意図した違い（KMS の呼び出しの形と、ユーザーデータの `null_resource`）を除いて 48 件が一致した。最初の突き合わせで見つかった違い（type の無い変数で `"1"` と `1` がずれる、起動テンプレートの `version` と `depends_on`、`time_sleep` の `service_cidr`、アクセスエントリの `tags`）は要約表を直した。
- 診断とリソースの数（手順2 → 手順3。変数のファイルを渡さない）:

  | 対象 | リソース | warn | info | 主な変化 |
  |---|---|---|---|---|
  | 自作 fixture 5構成 | 153 → 190 | 8 → 8 | 5 → 4 | `TF-MODULE-DEFERRED` 4 → 0、`TF-MODULE-SUMMARY` 3 |
  | 公開サンプルの TF のルート 52 | 854 → 2474 | 130 → 391 | 164 → 1058 | `TF-MODULE-DEFERRED` 148 → 0（黒箱は `TF-MODULE-BLACKBOX` 43、`module_summary` のリソース 201）。warn の増分は展開したモジュールの中の値（ルートで値の無い変数 `TF-UNRESOLVED-VAR` 61 → 127、リソースの属性に依る条件など `TF-UNEVALUATED` 60 → 191、×N 7 → 64）。info の増分は本物のモジュールのソースの count が 0 のブロックの `TF-COUNT-INDEX`（6 → 895） |
  | `.tf` のあるフォルダすべて 172 | 2076 → 10255 | 821 → 2231 | 2293 → 12945 | 同上（`TF-MODULE-DEFERRED` 365 → 0、黒箱 103） |

  リソースの増え方の大きいもの: terraform-aws-vpc/examples/complete 9 → 220、examples/simple 3 → 175（`source = "../../"` で本物を読み、count が 0 のブロックも `enabled: false` で載る）、terraform-aws-ecs/examples/fargate 8 → 143、aws-network-hub 16 → 198、eks-managed-node-group の例 4 → 97。T16（learn-terraform-provision-eks-cluster）は vpc 5.8.1・eks 20.8.5 が版の合わない黒箱、iam 5.39.0 が IAM だけの黒箱のまま（6 リソース）。例外 0、error 0、すべて raw IR の検査を通った。時間はルート 52 で 2.6 → 約 7 秒（最も遅い ecs の fargate で 0.9 秒）、172 フォルダで約 50 秒（検査を含む）。
- テスト 199 件が通過。`c1_check.py` は入力 25・辺 513 本・対応の無い辺 0（CFN は変えていない）。5構成を `uv run`（PEP 723）で PowerShell 5.1 から `tf.py` にかけ、`validate_ir.py` が通った（要約表は SKILL のフォルダの `references/` から読む）。

### つまずいたこと
- 最初は子の変数を呼び出しの時点で評価しようとしたが、モジュールの間で出力と変数が行き来する（`module.app` の引数が `module.db` の出力を、`module.db` の引数がルートの SG を、その SG が `module.app` の出力を使う）ので、locals と同じく使うときに評価してキャッシュする形にした（本当の循環は `TF-CYCLE`）。
- `try()` の中の作られないブロックの扱い: 手順2 の決まり（添字で引くと作られないブロックへの参照）のままだと、本物の vpc モジュールのサブネットの `vpc_id` が、作られない `aws_vpc_ipv4_cidr_block_association` を指した。要約表との突き合わせで見つかった。
- 要約表の中で count が 0 のサブモジュール（eks の `fargate_profile` を渡さないとき）を飛ばしたのに、`depends_on` と参照がその中のリソースを指して、raw IR の検査（参照の先が無い）に落ちた。表の中の作られない呼び出しは、リソースと同じく空のまとまりにした。
- 要約表の変数の宣言から `type` を省いたら、`public_subnet_tags = { "kubernetes.io/role/elb" = 1 }` が `map(string)` に変換されず `1` のままになり、本物（`"1"`）とずれた。変数は本物の `type`・`default`・`nullable` を写す。
- Bash のヒアドキュメントで日本語を含む Python を渡すと文字化けして置き換えに失敗した（既知）。長い書き換えは `%TEMP%` の下に Write で書いた Python で当てた。

### 第三者レビュー（判定「修正後コミット」）と対応
- **M1** alb の要約表で、写していない入力が `listeners` の中のキー（`weighted_forward`・`rules`・認証のアクションなど）だと、診断なしに落ちていた（`# not-covered:` に変数名しか書けず、`setup_child` は最上位の引数名しか見ていなかった）→ `# not-covered:` に入れ子の経路（`listeners.*.authenticate_cognito`、`listeners.*.rules.*.actions.*.authenticate_oidc` など。`*` はどのキー・要素でも）を書けるようにし、渡した値のその位置に `null` 以外の値があれば `TF-MODULE-SUMMARY-INPUT` に書く（`path_present()`。子の変数の値を見るので、展開する直前（`run()`）に調べる）。辺に効く `weighted_forward`（リスナーの `default_action[0].forward[0].target_group[*].arn`）と `aws_lb_listener_rule`（forward・weighted_forward・redirect・fixed-response と条件）は表に写した。terraform-aws-ecs の fargate の例の `TF-MODULE-SUMMARY-OUTPUT`（`listener_rules`）4件は 0 件になった。
- **R1** eks の KMS を `count` にしたので address が本物と違った → 黒箱の呼び出しで `create` 引数が false と決まるものは `enabled: false` にする一般規則を ir-schema.md の 7.2 に書いて実装し、要約表は本物どおり `create` 引数の `module "kms"` に戻した（address は `module.eks.module.kms`。表の中の黒箱の呼び出しは、参照の先を残すため、作られなくても載せる）。
- **R2** `regexall()` を `$az` に当てる方法が代表の名前1つだけだった → 形の違う8つの代表（`us-east-1a`・`ap-northeast-1c`・`eu-central-1b`・`cn-north-1a`・`us-gov-west-1a`・`il-central-1a`・`ap-southeast-3b`・`me-central-1a`）でマッチの数を数え、すべて同じときだけ決める（違えば `$unknown`）。
- **R3** alb・rds の要約表が本物と未照合だった → ユーザーの許可を得て、terraform-aws-alb v10.5.1（6c6e48c）と terraform-aws-rds v7.2.2（175da04）を GitHub から取り、`fixtures/public/terraform-aws-alb`・`terraform-aws-rds` に置いた（vpc・eks と同じ置き方。`.git` を削除、rds の `examples/s3-import-mysql/backup.zip` を削除。SOURCES.md の M01・M02）。要約表を本物から写し直し（変数は本物の宣言をそのまま、リソースのブロックは図に要る属性だけ）、`SummaryTest` に突き合わせのテストを足した。module-summaries.md の 3章の「確かめたソース」を更新した。
  - 写し直す前の表と本物の違い（見つかったもの）: alb は、`aws_lb` のタグに `terraform-aws-modules = "alb"` を足していた（v10 には無い）、`security_groups` の並びが逆（本物は作った SG が先）、SG ルールのタグ（`Name`）と `to_port` の既定（`from_port`）が無かった、リスナーの `port`・`protocol` を `try()` で決めていた（本物は型付きの変数と `coalesce`）、リスナーのルール・`weighted_forward`・追加の証明書・Lambda の `aws_lambda_permission`・`additional` の登録・Route 53・WAF が無かった。rds は、ロググループ（`enabled_cloudwatch_logs_exports`）・ローテーション・IAM ロールの関連付けを写していなかった、拡張モニタリングのロールの名前（`monitoring_role_use_name_prefix`）と `Name` タグ、`random_id` の `keepers` の `snapshot_identifier`、ルートの `option_group_name`（postgres なら `null`）が本物と違った。three-tier-modules の展開の結果（address 42 件）は変わらない。
  - 突き合わせの結果: alb は2通りの入力（6・14 件）、rds は2通りの入力（1・8 件）で、作られるリソースの address・表のリソースの間の参照・名前とタグが一致した。props の違いは alb の weighted_forward の空の `stickiness` と、表で `data.aws_partition` を擬似パラメータにした `principal` だけ。eks は KMS を戻したので、違いは `null_resource` 2件だけになった（48 件）。
  - 表の変数を本物から写すとき、`description` を消す処理がオブジェクトの型の中の `description = optional(string)` まで消して、SG ルールの `each.value.description` が誤りになった（`TF-EVAL-ERROR`）。トップレベルの `description`（heredoc を含む）だけを消すようにした。
  - 型付きの変数（`map(object(...))`、既定 `null`）で、`for_each = var.rules != null ? var.rules : {}` が、リソースの属性を含むマップを渡すと決まらなかった → `null` との比較は、もう片方が `null` になりえない値（マップ・リスト・`$concat` など）なら決める（`$res`・`$unknown` は決めない。7.2）。
- 任意1 `>= 5.0, < 7.0` の前提の文を「allows majors 5 to 6」に分けた。任意2 `try(local.x, "")` の中の作られないブロック: locals・子の変数・出力は `try` の外として1回だけ評価するので直さず、制約として 7.2 に書いた（Terraform ではその local 自体が誤りになる設定のときだけ起きる）。任意3 module-summaries.md の 1章に、要約表では count 0 を載せず、手元のソースを読むと `enabled: false` で載ることを並べて書いた。
- vpc 5.x・eks 20.x の要約表は作らない（ユーザーの決定。フェーズ6 の前に改めて決める。HANDOFF の判断待ち）。
- 確かめたこと: テスト 205 件が通過（TF アダプタは 70 件）。5構成を `uv run` で作り `validate_ir.py` が通った（数は変わらず）。`c1_check.py` は入力 25・辺 513 本・対応の無い辺 0。公開サンプルの TF のルート 52 で例外 0・error 0・検査を通る（リソース 2474 → 2480、warn 391 → 381、`TF-MODULE-SUMMARY-OUTPUT` 4 → 0、×N 64 → 59）。`.tf` のあるフォルダは、取り込んだ alb・rds の 33 フォルダが増えて 205（もとの 172 フォルダはリソース 10620、warn 2161）。どれも失敗 0。

### 再確認（判定「コミット可」）と対応
- R1' `create = false` を `enabled: false` にする規則を、source が `terraform-aws-modules/` の黒箱の呼び出し（と要約表の中の呼び出し）に限り、当てたときは `TF-MODULE-NOT-CREATED`（info）を書く（ほかの source の `create` は読まない）。任意: `create` が決まらなければ `enabled: null`（count が決まらないときと同じ）、`path_present()` は空の `{}`・`[]` を当てず、途中の値が決まらず調べられなかった経路は `TF-MODULE-SUMMARY-INPUT` の info（`path: "unknown"`）に書く、`null` との比較で属性の無いリソース・モジュールの呼び出しそのもの（`aws_x.y`・`module.x`）も null にならない値とした。7.2・module-summaries.md の 1章を合わせ、テストを直した。テスト 205 件・`c1_check.py`（対応の無い辺 0）・公開サンプルのルート 52（例外 0・error 0、リソース 2480・warn 381 は変わらず）が通った。

---

## 2026-10-17（続き）フェーズ2 の手順4: plan JSON

### 概要
TF アダプタで、`terraform show -json` の plan JSON を読めるようにした（`scripts/lib/tf_plan.py`、tf.py の `--plan` と `--input` の判定）。plan JSON の fixture は、ユーザーの決定（「手元で本物の plan JSON を作る」）で、本物の terraform と moto（ローカルの AWS モック）から作った。第三者レビューの前（未コミット）。

### 入れたツールと版
| もの | 版 | 入れ方 |
|---|---|---|
| terraform | 1.16.5（windows_amd64。2026-10-17 の時点で 1.16.6 が出ている） | `winget install --id Hashicorp.Terraform -e`（HashiCorp 公式。winget がハッシュを確認）。入れた後に `$env:Path` をレジストリから読み直した |
| moto[server] | 5.2.4 | `pyproject.toml` の開発用の依存（`uv add` の後に `==` で固定。**2026-10-26: `[dependency-groups] fixtures` に移した。既定の `uv sync` には入らず、`uv run --group fixtures …` で使う**）、`uv sync`（uv.lock を更新。boto3・flask・werkzeug・pywin32 などの間接依存を含む） |
| terraform の provider・モジュール（`%TEMP%\tfp` の中だけ） | hashicorp/aws 6.x・archive 2.x・time 0.13.x・random、opensearch-project/opensearch 2.x、terraform-aws-modules の vpc ~> 6.7・alb ~> 10.0・rds ~> 7.0 | `terraform init` がレジストリから取得（`TF_PLUGIN_CACHE_DIR` を `%TEMP%\tfp\.plugin-cache` に） |

### やったこと
1. **plan JSON の fixture**（`aws-iac-diagram-workspace/fixtures/tf-plan/`）: 自作の5構成の TF 版から7つ（three-tier は dev と prod の2つ）と、試験用の小さな構成 `tf-plan/edge`（sensitive の変数、count 0、for_each、count 2・0 のローカルモジュール、`depends_on = [module.m]`、alias の provider（us-east-1）、dynamic ブロック、locals・`each.value` を通した参照、`file()`、`.tf.json`）の plan。作り方は道具 `aws-iac-diagram-workspace/tools/make_plan_json.py` にした（fixtures/README.md の「plan JSON」）。
   - moto のサーバーを 127.0.0.1:5555 で起動し、`%TEMP%\tfp\<名前>\cfg` に構成をコピーして `moto_override.tf`（AWS provider の endpoints 27 サービスを moto に向け、`skip_credentials_validation`・`skip_requesting_account_id`・`skip_metadata_api_check`・`skip_region_validation`・`s3_use_path_style`）を置く。fixture の .tf は変えていない。ほかのサービスは `AWS_ENDPOINT_URL` で同じ先へ。
   - 本物の AWS に接続しないように、環境変数は必要なもの（PATH・SYSTEMROOT・TEMP など）だけから作り直し、偽の認証情報（`testing`）を渡し、`USERPROFILE`・`HOME`・`APPDATA`・`LOCALAPPDATA`・`AWS_CONFIG_FILE`・`AWS_SHARED_CREDENTIALS_FILE`・`TF_CLI_CONFIG_FILE` を作業用のフォルダに向けた（手元の `~/.aws` と Terraform の CLI の設定を読ませない）。`AWS_EC2_METADATA_DISABLED=true`。
   - `terraform init`・`plan -input=false -lock=false -out=plan.tfplan [-var-file=…]`・`show -json`。出来た JSON から override で足した provider の設定（`configuration.provider_config` の endpoints・skip_* など）を取り除き、偽の認証情報・`127.0.0.1`・`localhost`・作業用のフォルダの絶対パス・ホームのパス・ユーザー名が残っていないか調べてから書く（残っていれば失敗）。7つとも1回で作れた（作れなかった構成は無い）。合わせて約 1.4 MB（three-tier-modules が 620 KB）。
2. **tf.py の入力**: `--input` が `.json` のファイルで plan JSON の形（`format_version`・`terraform_version` と `planned_values` か `resource_changes`）なら plan JSON だけから作る。`--input <フォルダ> --plan <plan JSON>` なら .tf と合わせる。plan JSON でない JSON・state の JSON・`format_version` 2.x・plan JSON だけのときの `--var-file`・`--var`・`--redact-var` は終了コード 2。
3. **plan JSON だけから作る**（`tf_plan.PlanReader`、`build_plan_raw`）: address と enabled は `resource_changes`（delete・forget だけのものは除く）・`prior_state`（plan のときに読んだ data）・`planned_values`。`configuration` のモジュールの木（`module_calls`）をインスタンスごとに作り（count・for_each の呼び出しは、インスタンスの address から添字を集める。無ければ count 0）、インスタンスの無いブロックは添字なしで `enabled: false`。リモートのモジュールの中の作られないブロックと data は載せない。props は `expressions` にあるものだけ、値は after（known after apply は `$unknown`、sensitive は使わない）。dynamic ブロック（`configuration` に出ない）は値だけ入れて `TF-PLAN-DYNAMIC-BLOCK`。provider・region（alias とモジュールの中の provider は plan の `region`、既定の provider は引数 `region` が定数か既定と違うときだけ）。変数は `evaluation.vars` に出どころ `"plan"`（値は書かない）、ローカルモジュールの変数は `"argument"`／`"default"`。
4. **参照の重なりと置き方**（ir-schema.md の 7.3「plan JSON の参照」）: `references` の重なり（`aws_subnet.private[0].id`・`aws_subnet.private[0]`・`aws_subnet.private`）を、ほかの文字列の前の部分を除いて最も細かいもの1つにする（`collapse()`）。`var.*` は呼び出しの式へ、`module.x.y` は子の出力の式へたどって `through` を書き、出力の後ろの `["app"].arn` を先に続ける。置き方は、値の全体が known after apply で先が1つなら `$res`、スプラットならインスタンスごとの `$res` のリスト、known after apply の位置の数と先の数が同じなら順に、決まった値が先の属性の値と同じ（JSON は `$json` どうし）なら `$res`、文字列の一部なら `$concat`、値が null なら `pruned`、それ以外は `unevaluated`。
5. **.tf と合わせる**（`tf_plan.combine`、`build_raw(plan=…)`）: plan の `variables` を変数の値として .tf を読み（出どころ `"plan"`。`setup_variables` に `"plan"` の種類を足した）、plan の address の一覧を正として、同じ address・型の .tf のリソースを使う（`enabled` は plan）。.tf の `$unknown` のうち値が決まらないことによる診断のある位置を plan の値で埋め、その診断を消す（`--redact-var`・sensitive の位置は埋めない）。.tf に無いもの（×N・黒箱の中身・要約表に無いもの・`.tf.json`）は plan から作り、file は `.tf.json`・同じブロック・モジュールの .tf の順。plan の `configuration` にあって .tf に無い参照の組は `unevaluated` で足す（`TF-PLAN-EXTRA-REF`）。
6. **`.tf.json`**（手順2・3 から回したもの）: plan JSON と一緒なら、そのブロックは plan から取り（`configuration` は provider のスキーマで読んだ後の形なので、ブロックと属性が分かれている）、file は `.tf.json`。`TF-TFJSON-UNSUPPORTED` は info にする。**.tf だけで `.tf.json` を読むことは手順5 に回した**（ir-schema.md の 8章）。
7. **テスト** `tests/test_tf_plan.py`（19 件。計 224 件）: 重なりのまとめ方・address の分け方・入力の判定と誤り（state・ほかの JSON・2.x・CLI の組み合わせ）、fixture に残してはいけない文字列、7つの plan の raw IR が検査を通る（plan だけと合わせたもの）、**plan だけと .tf の比較**、**合わせたものと .tf の比較**、**正解 IR の TF 側の網羅分類との突き合わせ（plan の入力）**、dev／prod、参照の置き方、モジュール（through、リモートのモジュールの中の作られないブロックと data、変数の出どころ、sensitive）、edge（sensitive の値が出ない、count・for_each・モジュール・depends_on・pruned、alias の region、plan だけの限界と合わせたときの違い、`file()` の値を埋める、`.tf.json`）、×N を plan の address に置き換える、`--redact-var` の値を埋め戻さない、CLI。
8. **CI**（`ci.yml`）: terraform を動かさず、コミットした plan JSON を plan だけと `--plan` の両方で `uv run tf.py` にかけ、`validate_ir.py` で調べる手順を足した。Windows PowerShell 5.1 の手順にも、日本語のパスに置いた SKILL で `--plan` を1回流す手順を足した。
9. **文書**: ir-schema.md の 7.1（`root`、変数の出どころ `"plan"`）、7.2（「TF の plan JSON」を新設、`.tf.json`）、7.3（「plan JSON の参照」）、7.5（`TF-PLAN-*`）、7.6（手順4 を済に）、8章（重なりの規則を 7.3 へ移し、`.tf.json` を手順5 の項目にした）。README の使い方と plan JSON の注意、fixtures/README.md、tf.py の docstring。ir-raw.schema.json は変えていない（`vars` の `source` は文字列なので `"plan"` も通る。`TF-PLAN-*` も code の形に合う）。

### 決めたこと
| 決定 | 理由 |
|---|---|
| 入力は `--input <plan JSON>`（.json のファイルで、中身が plan JSON の形なら）と `--input <フォルダ> --plan <plan JSON>` の2つ | ファイルかフォルダかで分かれ、`.json` の CFN のテンプレートと取り違えない（TF のアダプタはフォルダを読むので、ファイルは plan JSON だけ）。中身で判定するので、state の JSON などには理由を出せる |
| **.tf と合わせるのを推奨の形にし、address と enabled は plan、file・props・参照の位置は .tf** | plan JSON の `configuration` は属性ごとの参照の一覧だけで、式の形・locals・dynamic ブロック・ファイル名を持たない。plan だけでは参照の位置と `$concat`・`$json` の中が分からない。一方で count・for_each・モジュールの展開と、.tf で決まらない値（data、`file()` など）は plan が正しい。PLAN の「plan JSON があれば優先」は、address と値は plan を正とし、`configuration` の参照の組は必ず出す（.tf に無ければ足す）ことで満たす |
| plan JSON の `variables` を、.tf を読むときの変数の値にする（出どころ `"plan"`） | plan を作ったときの tfvars を利用者が渡し直さなくても、.tf の評価が plan と揃う |
| 重なりのまとめ方: ほかの文字列の前の部分（`.` か `[` が続く）になっている文字列を除く | Terraform は参照の各段（`a.b[0].c`・`a.b[0]`・`a.b`）を並べて出す。最も細かいものが、.tf の `$res` の address と `attr` に当たる |
| 参照の置き方は、値の形と先のリソースの値で決める（推測を含むことを 7.3 に書く） | 式の形が無いので、`x = aws_y.z.id` を確かめる方法が値しかない。値の全体が known after apply で参照が1つなら、多くは直接の参照（`vpc_id = aws_vpc.main.id` など）。外れるもの（`jsonencode` の中など）は、合わせたときに .tf の位置になる |
| count.index・each.* で選ぶ参照は、すべてのインスタンスへの `unevaluated` | `aws_subnet.private[count.index].id` も `element(aws_subnet.private[*].id, count.index)` も、configuration では `aws_subnet.private`・`count.index` になり、添字が分からない。推測で active にしない |
| リモートのモジュールの中の作られないブロックと data は載せない。`via` は付けない | 要約表の展開（4章の `module_summary`）と同じ一覧にして、正解 IR と .tf の結果と比べられるようにする。中身は Terraform が読んだ本物なので、`module_summary` とは書かない |
| sensitive の値は使わない（null のものは書かない） | ユーザーの決定（秘密の値を IR に書かない）。plan JSON の `variables`・`configuration` には sensitive の変数の値が平文で入るので、そこから値を取らない |
| plan だけのときは、引数の無い `aws_caller_identity` などの値も plan の値のまま（`$pseudo` にしない） | plan の値は Terraform が決めた値で、式の形が無いので `$pseudo` の位置が分からない。合わせると .tf の `$pseudo` になる |
| three-tier の plan は dev と prod の両方 | 正解 IR は dev。prod は踏み台（count 1）と sensitive の値（SSM の AMI のパラメータ）の確認に使う |

### 確かめたこと
- **plan だけと .tf の比較**（5構成と three-tier の prod）: address・型・enabled・module・provider・region がすべて一致（file は plan JSON の名前）。.tf の active の参照の (from, to) の組は、three-tier-modules の 8 組（dynamic ブロックのリスナー → TG の1組、vpc・alb・rds モジュールの locals を通した 7 組）を除いてすべて plan の IR にある。plan だけにある組は、count.index で選ぶ参照の他のインスタンスへの `unevaluated` だけ。(from, to, attr, path) まで同じ active の参照は、three-tier 42/61、serverless-api 39/40、vpc-endpoints 34/62、rag 55/62、three-tier-modules 74/117（違いはスプラットの `attr: null`、集合の属性の位置、count.index の `unevaluated`、JSON の中の参照）。診断は info だけ。
- **合わせたものと .tf の比較**: 5構成と prod で `resources`・`references` が .tf の結果と同じ（plan だけにあるリソース 0、足した参照 0）。three-tier-modules の vpc モジュールの plan のリソース（25 件。`aws_default_*` を含む）は要約表の展開と同じ address だった。warn は rag の `sha1()`（plan でも known after apply）の1件だけ。
- **正解 IR の TF 側の網羅分類**: plan だけは型と enabled が5構成で一致（file・via は上の理由で違う）、合わせたものは file・via まで一致。
- edge: sensitive の値（`not-a-real-password`。plan JSON には平文で入っている）が raw IR に出ない、`file()` の値を plan で埋める、`.tf.json` の2ブロックを plan から取って file が `extra.tf.json`、×N（変数を渡さない three-tier の .tf に plan を合わせる）を plan の address に置き換える。
- テスト 224 件が通過。CI に足した手順（plan だけ7＋合わせたもの7 を `uv run` で作り `validate_ir.py`）を手元の bash で流して通った。PowerShell 5.1 から `--plan` を流して `validate_ir.py` が通った。`c1_check.py` は入力 25・辺 513 本・対応の無い辺 0。公開サンプルの TF のルート 52 は、変更の前後で同じ（リソース 2480、warn 381、info 1027、error 0、検査を通る）。`check_coverage.py --lint`・正解 IR の検査も通る。

### つまずいたこと
- plan JSON の `configuration` には dynamic ブロックが出ない（alb モジュールのリスナーの `default_action`）。locals の式も無い。どちらも plan だけでは参照が欠けるので、合わせる形を推奨にした。
- スプラット（`aws_subnet.public[*].id`）の `references` は `aws_subnet.public` だけで、属性の名前が無い。
- AWS provider v6 は、すべてのリソースの after に `region` を入れる。モジュールの `region = var.region`（null）でも既定のリージョンが入るので、既定と同じなら書かないようにした（.tf と揃う）。
- sensitive の印は、値が null の属性（rds の `password_wo`）にも付く。null は書かないようにした。
- SSM のパラメータの data の `value` は sensitive なので、それを使う `ami` も sensitive になる（`TF-PLAN-SENSITIVE`）。
- moto の偽のアカウント ID（123456789012）と ARN の `user/moto` が plan に入る（URL ではないので残した。fixtures/README.md に書いた）。
- `git stash` で変更前の公開サンプルの数を測ったとき、追跡していない新しいファイルは残るので、tf.py が新しいライブラリを読まない状態で比べた（問題なし）。

## 2026-10-26 フェーズ2 の手順5: 公開サンプルでの確認と完了

### 概要
TF アダプタを公開サンプルの TF すべてにかけて確かめ、TF／SAM の対の型を比べ、ir-schema.md の 7.6（フェーズ2 の間だけの注記）を消して 7章を確定し、フェーズ2 を完了にした（完了基準の分け方は、下の決めたことの表のとおり、ユーザーが決めた）。アダプタの不具合は見つからなかった。第三者レビューの前（未コミット）。

### やったこと
1. **公開サンプルでの確認の道具** `aws-iac-diagram-workspace/tools/tf_public_check.py`（新規）: 公開サンプルの TF を TF アダプタで読み、`validate_ir.py <ファイル>` と同じ検査（スキーマ、参照の整合、出力の形 C5）を、書き出したファイルにかける。例外・検査の失敗・error の診断があれば終了コード 1。既定は T01〜T20、P01〜P04 のルート 52 フォルダ（`survey_public.py` の一覧）、`--all` は `.tf` のあるフォルダすべて、`--jobs N` で並列、`--pairs` で対の表、`--out` で JSON。
   - 手順3 までは、52 ルートが `test_tf_adapter.py` の `FixtureTest.test_public_samples`、「172 フォルダ」は手元の一回限りのスクリプトだった。前者を `tests/test_tf_public.py`（`PublicFoldersTest`）に移して道具の関数を使うようにし、後者を `--all` にして CI の手順（両 OS）に入れた。
2. **TF／SAM の対の比較**（同じ道具、`tests/test_tf_public.py` の `PairTest`）: T01、T05、T06、T07、T11（SELECTION.md は T06・T07・T11 を主セット、T01・T05 を煙試験とする。同じ表で済むので5つとも）の TF 版と SAM 版を TF アダプタと CFN アダプタで読み、**リソースの型の多重集合**を比べる。
   - 正規化（最小限。道具の docstring に書いた）: TF は `data` と aws 以外のプロバイダのリソースと `enabled: false` を除き、型を CFN の型名にする（`TF_TO_CFN`。表に無い型は `KeyError` で失敗にして足し忘れを防ぐ。CFN ではプロパティとして埋め込まれるものは `AWS::Events::Rule#Targets` のように `#` を付ける）。CFN は SAM の型を変換の後の型にする（`SAM_TO_CFN`。`AWS::Serverless::Function` → `AWS::Lambda::Function` など5つ）。
   - 違いは `PAIR_EXPECTED` に型と件数と理由を1つずつ書き、増えても減っても失敗する（ゆるい許容ではない）。一致した側（`PAIR_COMMON`）も固定した。
   - SELECTION.md の 3 の 3（HANDOFF が「4 の 3」と書いていたのは、節の番号の誤り）が求めているのは「ノードの型の多重集合と、辺の (from の型, to の型, kind) の多重集合」だが、ノードと辺は正規化の後の IR のもの。フェーズ2 の raw IR の段階では**リソースの型の多重集合だけ**を比べ、辺と「同じ IR」はフェーズ3 に回した（PLAN のフェーズ3 の完了基準に足した）。
3. **ir-schema.md**: 7.6 を消し、冒頭の状態と7章の前置きを「確定（2026-10-26）」にし、7.5 の TF の `code` を手順3 の時点のものから、読み込み・変数と評価・count・for_each・モジュールとプロバイダ・plan JSON に分けた42個の一覧にした（テスト `DiagnosticCodesTest` が、コードに出てくる `TF-…` と一覧の食い違いを調べる）。8章は `.tf.json` の決定と `code` の一覧の確定を反映した。ほかの文書に 7.6 への参照は無かった（HANDOFF は手順5 の項目に残っていたのを直した。過去の WORKLOG の記述は、当時の事実なので直していない）。スキーマの JSON は変えていない（TF の `code` の形は `^TF-`）。
4. **`.tf.json`**: 決定は下の表。メッセージを「plan JSON なしでは読まない。`--plan` で plan から取る」と分かる文にした。テスト `test_tf_json_is_not_read_without_a_plan`。
5. **手順1〜3 で見送った小さなこと**: 下の表。`--workspace` を足した。

### 決めたこと
| 決定 | 理由 |
|---|---|
| **`.tf.json` は .tf だけでは読まない（`TF-TFJSON-UNSUPPORTED` の warn のまま）** | HCL の JSON の書き方では、`"ingress": {…}`（または `[{…}]`）が入れ子のブロックか、オブジェクトの値の属性かが書き方から決まらず、決めるには provider のスキーマが要る。ブロックと属性を取り違えると props の形が .tf と plan JSON で変わる（リスト化されるか否か）。公開サンプルに `.tf.json` は無い（`fixtures/` 全体を探した。あるのは自作の `tf-plan/edge/extra.tf.json` だけ）。plan JSON と一緒なら plan の `configuration` から正しく読める。「安く、正しく」できる方法が無いので保守的に残した。provider のスキーマ（`terraform providers schema -json`）を入力に取れば読めるので、要るなら後で足す（ir-schema.md の 8章） |
| `--workspace <名前>` を足した（`terraform.workspace` の値。既定は `default`。plan JSON だけのときは終了コード 2） | `terraform.workspace` を `lookup` や count に使う構成は実在する（公開サンプルの fixtures には無いが、TF の定番の書き方）。`default` 固定だと別の環境の図が作れない。`Context` に値を持たせるだけの小さな変更で、前提（`evaluation.assumptions`）には使ったときだけ書く。テスト `test_workspace_option` |
| 対の比較は raw IR のリソースの型だけ。「同じ IR」「辺の多重集合」はフェーズ3 | 比べる対象のノード・辺は正規化の後のもの。SAM が暗黙に作る IAM ロール・Subscription・Permission は CFN アダプタが展開せず（暗黙の API を除く。7.2）、TF 側は分けて書く |
| PLAN のフェーズ2 の完了基準「同じ構成の TF 版と CFN 版が同じ IR になる」をフェーズ3 の完了基準に移した | 上と同じ。HANDOFF の 3a は、元からフェーズ2 では `ExpectedIrTest` で確かめると書いていた。**CRITERIA.md の 1.1 の「TF 版と CFN 版の canonical 部 … バイト単位で一致（フェーズ2 の完了基準）」は、確定済みの文書なので、実装役は書き換えなかった**。そのあと（2026-10-26）ユーザーが「C: フェーズ2 は raw IR の確認、フェーズ3 は canonical 部の一致に分ける」と決め、CRITERIA.md の 1.1 を2行に分けた |

### 手順1〜3 で見送った小さなこと（それぞれの結論）
| 項目 | 結論 |
|---|---|
| `.tf.json` を .tf だけで読む | 見送り（上の表）。テストで固定 |
| ワークスペースを選ぶ引数 | **済**（`--workspace`） |
| `lifecycle` の `replace_triggered_by`、`provisioner`・`connection` の中の参照 | 見送り（フェーズ3 で辺にするかを決める）。図の辺は属性の参照から作るため、いまは出さない。出さないことをテスト `test_lifecycle_and_provisioner_references_are_not_emitted` で固定し、ir-schema.md の 7.2 に書いた。公開サンプルに `replace_triggered_by` は無く、`provisioner` は 7 ファイル（T14 の例や T20 の s3-tables など。`local-exec`）にある |
| リソースの属性の値を設定に書いた値から決める（`cidrsubnet(aws_vpc.main.cidr_block, …)`） | 見送り（フェーズ3 で図の `cidr` に要るかを見てから。ir-schema.md の 8章のとおり） |
| alb の認証のアクション（`authenticate_*`・`jwt_validation`、`TF-MODULE-SUMMARY-INPUT`） | 見送り（要約表の追加。実際に描くものではなく、info の診断で残る） |
| vpc 5.x・eks 20.x の要約表、kms などほかの terraform-aws-modules、`terraform init` 済みの `.terraform/modules` を読むこと | 見送り（vpc 5.x・eks 20.x は 2b の後の別の手順。残りは必要になってから） |
| HANDOFF の 0b（CI の action の更新、doctor のパス長、PEP 723 の間接依存の固定） | フェーズ2 とは別の項目なので触れていない |

### 確かめたこと
- **公開サンプル**: T01〜T20、P01〜P04 のルート **52 フォルダ**で、リソース 2480、診断 error 0・warn 381・info 1027（手順3 から変わらない）、例外 0、すべて `validate_ir.py` と同じ検査を通る。`.tf` のあるフォルダすべては **205 フォルダ**（手順3 の「172」は、手順3 のレビューで terraform-aws-alb・rds のソースを取り込む前の数）で、リソース 11621、error 0・warn 2224・info 13336、検査の失敗 0。実行時間は直列で約 70 秒、`--jobs 4` で 28〜34 秒（20 コアの手元。CI の 4 コアでは長くなる）。ルート 52 は約 6 秒（並列）／約 12 秒（直列）。
- **対**（型の数は正規化の後。共通 / TF だけ / SAM だけ）:
  | 対 | 共通 | TF だけ | SAM だけ | 違いの中身 |
  |---|---|---|---|---|
  | T01 | 3 | 1 | 0 | `aws_cloudwatch_event_target`（CFN では Rule の Targets） |
  | T05 | 2 | 4 | 0 | SAM の暗黙のロール、管理ポリシー（Policies の SQSSendMessagePolicy）、ロールへの付与2 |
  | T06 | 4 | 5 | 0 | Rule の Targets、SAM の暗黙のロールと付与、SNS の Events が暗黙に作る Subscription と Lambda Permission |
  | T07 | 2 | 13 | 1 | **構成の違い**: TF 版は HTTP API（ApiGatewayV2 の4種）、SAM 版は REST API（暗黙の `ServerlessRestApi`）。TF だけのログ2・コードの置き場の S3 3種。SAM の暗黙のロール・Permission |
  | T11 | 6 | 21 | 0 | REST API のメソッド・統合・応答（SAM では OpenAPI の外部ファイル）、SAM が暗黙に作る Deployment とステージ2、ステートマシンのロール、ロールの Policies・付与3 |
  どれも入力のコードで確かめた固有の差で、アダプタの不具合ではなかった（TF 側のリソースの数は `survey_public.py` のブロック数と、SAM 側はテンプレートのリソース数と一致）。診断はファイルを読む関数（`filemd5()`・`file()`）と `Fn::Transform`（OpenAPI の `AWS::Include`）の warn だけ。
- **正解 IR**: `ExpectedIrTest` は変更なしで通る（自作5構成の TF 側の網羅分類）。
- テスト **279 件**が通過（266 → 279。`tests/test_tf_public.py` 11 件、`test_tf_adapter.py` は公開サンプルのテストを移して 3 件を足した）。`uv lock --check` も通る。

### つまずいたこと
- Bash のヒアドキュメントで `\n`・`\t`・`\n` が改行・タブに化けた（HANDOFF の注意のとおり）。Python のコードには `chr(10)` などを使うか Edit ツールで直した。README のパスのバックスラッシュがタブになったのも同じ。

## 2026-10-26 フェーズ2b の R1: 出力の固定、骨組み、`lib/` の移動、依存の向きのテスト

### 概要
構成の階層化（PLAN の 1.4）の最初の手順。**中身の動きは変えずに**、(a) アダプタの出力を移す前に固定し、(b) パッケージ `scripts/aws_iac_diagram/` の骨組みを作って `lib/` などを `git mv` し、(c) 依存の向きと行数をテストで守り、(d) 旧パスの参照を直した。ローカルのブランチ `phase2b-r1`（main の `6587691` から。コミット 3 つ（出力の固定、移動とテスト、HANDOFF・WORKLOG）。push はしていない）。第三者レビューは別。

### やったこと
1. **出力の固定（コミット 1）**: `aws-iac-diagram-workspace/tools/golden.py` と `tests/golden/manifest.json`（1 ファイル、キーを並べ替え、LF）。アダプタの CLI を子プロセスで動かし（引数は CI と同じ。リポジトリのルートを作業フォルダにし、相対パスと `--root-base aws-iac-diagram-workspace`）、`--out` に書かれたバイト列の SHA-256 を比べる。ケースは **101**: 自作 TF 5＋変数の渡し方 3（`--var-file`・`--var`・`--redact-var`・`--workspace`）、plan JSON 7 の plan だけ 7 と `--plan` の合わせたもの 7、公開サンプルの TF のルート 52（`tf_public_check.root_folders()`）、CFN は `c1_check.discover()` の入力 25（自作 5＋公開 20）に `--param-file`・`--param` を渡したもの 2。
   - `--check`（既定。差分を `CHANGED`・`NEW`・`MISSING`・`ARGS`・`FAILED`・`ABSPATH` で一覧にして終了コード 1）、`--update`（リファクタを通すために使わない。docstring と警告に書いた。既存のケースの hash が変わるときは `--accept-changes` が無いと書かない）、`--dump NAME --out FILE`（今の出力を 1 件書く。不一致の調査用）、`--list`、`--only <接頭辞>`、`--jobs`。
   - 出力に絶対パス（リポジトリのルート、ホーム、一時フォルダ）が入っていたら、hash が合っていても失敗にする。「ドライブ名:\」の一般的な形は調べない（公開サンプルの Lambda のコードの文字列 `e:\n` が当たったため）。
   - `tests/test_golden.py`（10 件）: 全ケースの一致（約 20 秒）、manifest の形、道具が不一致・欠け・余り・失敗・引数違い・絶対パス・`--update` の歯止めを見逃さないこと。
2. **骨組みと移動（コミット 2）**: `aws_iac_diagram/{core, adapters/{terraform,cloudformation}, normalize, layout, emit, validate, icons, platform}`。空の層は `__init__.py` に「どのフェーズで埋めるか」の 1 行。`adapters/registry.py` は形式 → アダプタのパッケージ名の表だけ。
   | 元 | 先 |
   |---|---|
   | `scripts/lib/ir_raw.py` | `scripts/aws_iac_diagram/core/ir_raw.py` |
   | `scripts/lib/drawio_cli.py` | `scripts/aws_iac_diagram/platform/drawio_cli.py` |
   | `scripts/lib/tf_eval.py`・`tf_modules.py`・`tf_plan.py` | `scripts/aws_iac_diagram/adapters/terraform/`（R2 で分ける） |
   | `scripts/lib/sidebar_harness.js` | `scripts/maintenance/sidebar_harness.js` |
   | `scripts/build_icon_catalog.py`・`check_icons.py` | `scripts/maintenance/` |
   | `scripts/adapters/tf.py`・`cfn.py`、`doctor.py`、`validate_ir.py`、`find_aws_icon.py` | そのまま（入口。tf.py・cfn.py は R2・R3 まで入口と本体を兼ねる） |
3. **構成を守るテスト**: `tests/test_architecture.py`（21 件）と `docs/architecture.md`。
4. **参照の更新**: README（テストの節に golden と architecture を追記、辞書の保守用の起動パス）、PLAN（状態、1.4 の状況、フェーズ表の 2b。構成の図と 1.4 の本文は予定のまま）、HANDOFF（現在地、新しい配置、数字、再開の手順に golden）、ir-schema.md・module-summaries.md・assets/SOURCES.md のパス、辞書の生成物（`references/icons/*.md` と `broken.json` のヘッダのスクリプトのパス。`build_icon_catalog.py` を再実行して手で直した結果と同一だと確かめた）。**WORKLOG の過去の記録のパスは直していない**（その時点の事実）。

### 決めたこと
| 決めたこと | 理由 |
|---|---|
| 入口がパッケージを見つける方法は、各入口の先頭の `sys.path.insert(0, str(Path(__file__).resolve().parent[.parent]))` の 1 パターン（`scripts/` の直下は `.parent`、`adapters/`・`maintenance/` は `.parent.parent`）。ヘルパー・`PYTHONPATH`・インストールは使わない | 今までのやり方と同じで、`uv run <パス>` の 1 行がどのフォルダからでも、日本語とスペースを含むパスでも動く（確かめた）。ヘルパーを置くと、それ自身を見つけるのに同じ 1 行が要る |
| パッケージの中の import は絶対名（`from aws_iac_diagram.core import ir_raw`） | アーキテクチャのテストが読みやすく、移動しても書き換えが少ない（相対 import もテストは解決できる） |
| テストは `tests/` の直下に平らに置いた（`test_golden.py`、`test_architecture.py`）。PLAN の図の `tests/architecture/`・`tests/golden/` の形は R5 | `unittest discover -s tests` は `__init__.py` の無いサブフォルダを探さない。CI の 1 行を変えずに済む最も簡単な形。`tests/golden/` には今は manifest だけ |
| golden はアダプタの CLI を子プロセスで動かす | CLI の引数の処理、書き出し、入口の `sys.path` の 1 行まで含めて固定できる。入口の場所は `golden.py` の `ENTRY` の 1 か所（R2・R3 で直す） |
| 依存の向きの表（`ALLOWED`）: `core` → なし、アダプタ 3 つ → `core`、`normalize`・`layout`・`icons`・`platform` → `core`、`validate` → `core`・`icons`、`emit` → `core`・`layout`・`icons`・`platform`。入口はすべて可 | PLAN の 1.4 の 4 と図から。後の層は必要になったときに、表と docs/architecture.md の表（テストが照合する）を同じコミットで直す |
| 入口どうし・パッケージから入口の import は禁止 | 共通の処理は必ずパッケージに置かせるため |
| 行数の免除 2 つ（2026-10-26）: `adapters/tf.py`（2613 行）、`aws_iac_diagram/adapters/terraform/tf_plan.py`（1558 行）。どちらも R2 で外す。上限を超えて増えたら失敗、1,500 行以内に減ったら免除を消さないと失敗 | PLAN の 1.4 の 4。免除を口実に大きくしない／消し忘れない |
| `doctor.py`・`validate_ir.py`・`find_aws_icon.py` の本体のロジックは動かさなかった | 入口と本体が 1 ファイルのままで、`validate`・`icons`・`platform` の層に移すのはそれが育つフェーズ（4・5）。R1 は動きを変えない |
| `SKILL_DIR` の求め方は、移した 2 つのスクリプトで 1 段上げた。`tf_modules.py` の `SUMMARY_FILE` は `parents[4]`（R4 で `data/` に移すときに直す） | ファイルの深さが変わったため。それ以外のコードの変更は import とパスだけ |

### 確かめたこと
- **golden**: 移す前のコミット（`6587691`）の `git archive` を別の場所に展開し、manifest と `golden.py` だけを足して `--check` → **101 ケースすべて一致**（manifest が正しいこと、場所に依らないこと）。最後の木でも一致。Windows・WSL（Ubuntu 26.04）で同じ hash。`PYTHONHASHSEED` を変えても同じ。作業の途中で `tf_modules.py` の `SUMMARY_FILE` の深さを直し忘れたときは golden のほかに 25 件の単体テストが落ちた。`cfn.py` の `dump()` に空白を 1 文字足すと、27 ケースが `CHANGED`（バイト数 +1）で、終了コード 1。
- **単体テスト 312 件**（281 + golden 10 + architecture 21）が通る。Windows（通常の TEMP、別のドライブの TEMP `subst Y:`、8.3 の短い名前の TEMP）と WSL（`git archive HEAD` を `/tmp` に展開して `uv sync --locked` → `uv run python -m unittest discover -s tests`）。所要は Windows で約 60 秒、WSL で約 36 秒。
- `uv lock --check`・`uv sync --locked` が通る。CI の手順を手元で（Git Bash）: `validate_ir.py` で正解 IR、`check_coverage.py --lint`、`c1_check.py`（入力 25・辺 513・対応の無い辺 0）、TF アダプタの自作 5 構成と plan JSON 7 の `uv run`（PEP 723）と `validate_ir.py`、`tf_public_check.py --all --jobs 4`（205 フォルダ、リソース 11621、error 0。Windows 約 28 秒、WSL 約 18 秒）。
- PowerShell 5.1 の「日本語とスペースを含むパスから SKILL を起動」を、CI の手順と同じ文で手元で通した（`doctor.py`・`validate_ir.py`・`tf.py`（`--var-file`・`--plan`）。さらに `cfn.py`・`maintenance/build_icon_catalog.py`・`find_aws_icon.py` も）。WSL の bash の同じ手順も通った（doctor は warn。mmdc が無いだけ）。
- アーキテクチャのテストが空振りでないこと: 一時フォルダにコピーした構成に、`core` → `platform`、`terraform` ⇄ `cloudformation`、アダプタ → `emit`・`layout`・`normalize`・`validate`、`platform`・`icons` → アダプタ、パッケージ → 入口、入口 → 入口、相対 import、未知の層のフォルダ、1,501 行のファイル、免除の期限切れ・上限超えを入れ、どれも失敗する。

### R2 以降に残したこと
- **R2**: `adapters/tf.py` を入口 `adapt_tf.py` と `adapters/terraform/` の本体に分け、`tf_plan.py`（1558 行）を `plan/` に分ける。`tests/test_architecture.py` の `EXEMPT` を空にする。`golden.py` の `ENTRY` の `tf` を直す。`tf_public_check.py`・`test_tf_*.py` の `from adapters import tf` を直す。
- **R3**: `cfn.py`（1327 行。免除は要らないが 800 行を超えている）を同様に分ける。診断コードの一覧（`core/diagnostics.py`）と、一覧に無いコードを使ったら失敗するテスト。`ENTRY` の `cfn` を直す。
- **R4**: `SUMMARY_FILE`（`tf_modules.py`）、スキーマ、辞書、規則表を `data/` に移す。パスの深さは `parents[4]` から変わる。
- **R5**: テストを `unit/`・`integration/`・`golden/`・`architecture/` に分ける（`__init__.py` か discover の指定が要る）。
- **R6**: SKILL.md・references・`docs/spec/`・`docs/architecture.md` の印（R2〜R6 と書いた所）・PLAN の図。
- `doctor.py` の中身（`platform`）、`validate_ir.py` の検査（`validate`）、`find_aws_icon.py` の検索（`icons`）は、入口と本体を分けていない。

### つまずいたこと
- Bash のヒアドキュメントで `\n`・`\t` が化けて、置換が空振りした（HANDOFF の注意のとおり）。Python のコードは `chr(92)` で組んだ。Git Bash の `/tmp` と Windows の Python の `/tmp` は別のものを指す（ファイルは `%TEMP%` で開く）。
- `tf_modules.py` の `SUMMARY_FILE` が相対の深さ（`parent.parent.parent`）で書かれていて、移動で要約表を読めなくなった（`load()` は読めなければ空を返すので、エラーにならず要約表なしの扱いに変わる。R4 で読めないときに大きな声で失敗させるかを決める）。golden と単体テストが落ちて気づいた。**ファイルの位置に依る相対パスは、移動のたびに golden で確かめること。**

### レビューの指摘への対応（R1 の第三者レビュー: APPROVE WITH CHANGES）
- **要約表の欠落を黙って通さない（MAJOR）**: `references/module-summaries.md` が無いと、`tf.py` は終了コード 0 のまま three-tier-modules が 42 でなく 13 リソースになり、`doctor.py` も ok だった。`doctor.py` の必須ファイルに足し（無ければ error・終了コード 2）、TF アダプタは要約表が空・読めないのにレジストリモジュールの呼び出しがあるとき `TF-MODULE-SUMMARY-TABLE-MISSING`（warn。ir-schema.md の TF の code の一覧は 43 個）を出す（`tf_modules.blackbox_plan`。`tf.py` の行数は増やしていない）。golden は 101/101 のまま。`SummaryTableFileTest` 4 件。
- **構成のテストの穴**: `platform` が標準ライブラリを隠す危険（`aws_iac_diagram/` 自体を `sys.path` に入れない決まりを architecture.md に書き、標準ライブラリと同じ名前の新規のフォルダ・モジュールを失敗に。許可は `platform` の 1 つ）、入口どうしの import（`adapters/`・`maintenance/` の入口も対象。実在した `check_icons.py` → `build_icon_catalog`（辞書の書き出しの共有）は理由付きの許可表 `ENTRY_IMPORT_ALLOW` に 1 件だけ書き、外す時期を記した）、`importlib`・`__import__`・`exec`・`eval` の禁止。それぞれ一時フォルダのコピーで失敗を確かめる。
- **golden.py**: `--only` に合うケースが無ければ失敗、`--update` はケースが減るときも `--accept-changes` が要る。`find_aws_icon.py` のメッセージのパスを直した。テストは 323 件（312 + 11）。

## 2026-10-26 フェーズ2b の R2: Terraform の分割

### 概要
構成の階層化（PLAN の 1.4）の 2 番目。**中身の動きは変えずに**、`scripts/adapters/tf.py`（2,612 行。CLI と、1 クラス 1,700 行の `ModuleEval` を含む）を入口 `scripts/adapt_tf.py` と `scripts/aws_iac_diagram/adapters/terraform/` の 26 ファイルに分け、`tf_plan.py`（1,558 行）・`tf_eval.py`・`tf_modules.py` もサブパッケージ `plan/`・`evaluator/`・`modules/` に分けた。行数の免除（`EXEMPT`）は空。ローカルのブランチ `phase2b-r2`（main の `26dca6b` から。コミット 6 つと、レビュー対応の 1 つ。push はしていない）。第三者レビューは別。

### コミット
| # | 内容 |
|---|---|
| 1 `b2735ff` | `git mv`: `tf_eval.py` → `evaluator/functions.py`、`tf_modules.py` → `modules/summaries.py`、`tf_plan.py` → `plan/reader.py`。import・`SUMMARY_FILE`（`parents[5]`）・テストのパスを直しただけ |
| 2 `81003bd` | `adapters/tf.py` を分ける（本体は `git mv` で `module_expr.py` へ）。入口 `adapt_tf.py`、`hcl`・`addresses`・`refs`・`model`・`build`・`module_*` 7 ファイル |
| 3 `3848347` | `evaluator/`・`modules/`・`plan/` を責務ごとに分ける。`EXEMPT` を空に |
| 4 `ab3dacf` | CI（bash・PowerShell）・README・ir-schema.md・module-summaries.md・PLAN・architecture.md の参照と説明 |
| 5 `edab37f` | HANDOFF・WORKLOG（この節） |
| 6 `3eb043b` | PLAN の取り残しの path |
| 7 | レビュー対応（下の「レビューの指摘への対応」） |

golden は 4 つのコミットのそれぞれで 101/101 一致、単体テストは 323 → 325 → 326 → 326 件が通った。

### 何がどこへ移ったか（行数は移した直後）
| 元 | 先 | 行 |
|---|---|---|
| `adapters/tf.py` の docstring・`main`・`_OrderedVar` | `scripts/adapt_tf.py`（PEP 723 の宣言は変えていない） | 167 |
| 〃 構文木の道具・heredoc・テンプレートの字句・`merge_body` | `adapters/terraform/hcl.py` | 395 |
| 〃 `Block`・`Instances`・`ResList`・`ResMap`・`Context`・`ModObj`・`weakest`・メタ引数の集合 | `model.py` | 108 |
| 〃 `block_address`・`inst_address`（plan の側と共通にした） | `addresses.py` | 22 |
| 〃 `ref_order`・`through_refs`・`prepend_through`・`collect_active`・`_dedupe`（→ `dedupe_refs`）（plan の側と共通にした） | `refs.py` | 70 |
| 〃 `build_raw`・`build_from_plan`・`dump`・変数のファイルの探し方 | `build.py` | 128 |
| 〃 `ModuleEval` の `__init__`・`diag`・`add_ref` | `module_eval.py`（6 つのミックスインを束ねる） | 85 |
| 〃 `ModuleEval` の読み込み（load・read_tf・collect・add_block）と `summary_tree` | `module_load.py` | 151 |
| 〃 変数・local・output・子の変数と出力 | `module_vars.py` | 358 |
| 〃 `count`・`for_each`・子のモジュールの作成 | `module_expand.py` | 272 |
| 〃 式の評価・pruned の参照の集め方（`git mv` の本体） | `module_expr.py` | 662 |
| 〃 値 → props（materialize・body_props・dynamic_block） | `module_props.py` | 136 |
| 〃 リソースの出力・provider・depends_on・`path_present` | `module_emit.py` | 281 |
| `tf_eval.py`（1,152 行） | `evaluator/values.py`（型・変換・`format()` の本体）、`evaluator/functions.py`（組み込み関数） | 404・763 |
| `tf_modules.py`（209 行） | `modules/sources.py`（source の見分け）・`summaries.py`（要約表の読み込み）・`resolve.py`（版の選択・黒箱） | 46・97・85 |
| `tf_plan.py`（1,558 行） | `plan/read.py`・`reader.py`（PlanReader）・`values.py`・`addresses.py`・`masking.py`・`consistency.py`・`diagnostics.py`・`raw.py`・`combine.py` | 215・601・183・65・72・59・10・78・273 |

1,500 行を超えるファイルは無い。800 行を超えるのは **`adapters/cfn.py`（1,327 行。R3）だけ**。Terraform の側の最大は `evaluator/functions.py` の 763 行（`format_string` を `values.py` に移す前は 822 行だった）。

### 決めたこと
| 決めたこと | 理由 |
|---|---|
| `ModuleEval`（1 クラス 1,700 行。それだけで上限 1,500 行を超える）は、**責務ごとのミックスイン 6 つ**に分け、`module_eval.py` で束ねる。状態はすべて `ModuleEval.__init__` に残し、ミックスインは持たない | 動きを変えずに分ける最も安全な方法。メソッドは `self.xxx` で呼び合うまま。関数に直すと引数の受け渡しの書き換えが大きく、golden で守りきれない恐れがある |
| ミックスインは `module_eval.py` を実行時には import しない。`child()` は `ModuleEval(...)` でなく `type(self)(...)` で子を作る（型の注釈は `TYPE_CHECKING` の import） | 循環 import を避けるため。`ModuleEval` の子クラスは無いので動きは同じ。**ただし `ModuleEval` を継承するクラスを作ると、子もそのクラスになる**（意図しない場合は `child()` を直す） |
| `.tf` の側と plan の側で同じだった `collect`（`collect_active`）・`_dedupe`（`dedupe_refs`）・`block_address`・`INSTANCE_KEY` は 1 つにし、`inst_address` は plan の側（`key is None` を許す方）に揃えた | 分けると重複が目立つ。`.tf` の側の `inst_address` は `None` を渡されることが無い（呼び出しの前で分けている）ので、動きは同じ。golden で確かめた |
| 別のモジュールから使う `_unescape`・`_dedupe`・`_version`・`_diag`・`_drop_missing`・`_props_consistent`・`_mismatch` は、先頭の `_` を外した（`unescape`・`dedupe_refs`・`version_text`・`diag`・`drop_missing`・`props_consistent`・`block_mismatch`）。そのモジュールの中だけで使うものは `_` のまま | 他のモジュールから使うものを「非公開」の名前にしない |
| 入口 `adapt_tf.py` は `main()`・`_OrderedVar`・終了コード・エラーの文言を持つ（PLAN の 1.4 の 1。入口は引数の処理と呼び出し）。`build_raw` などの呼び出しは `build.py` | CLI の挙動（文言・終了コード）を入口の 1 か所に置く。テストは `adapt_tf.main` を呼ぶ |
| 旧パス `adapters/tf.py` の互換（薄い shim）は置かない | 配布したタグが無い。参照はすべて直した |
| 構成のテスト: `adapters/terraform` の直下のサブパッケージ（`evaluator`・`modules`・`plan`）は層の一部として許す（`SUBPACKAGE_PARENTS`）。層の表の外に新しい層が増えるのは、これまでどおり失敗 | サブフォルダが「表に無い層」と数えられて落ちたため |
| `EXEMPT` は空にし、`test_no_exemptions_remain` で空であることを確かめる | PLAN の 1.4。免除を足すときは、この検査も理由付きで直す |
| `doctor.py` の必須ファイルに `scripts/adapt_tf.py` と `scripts/aws_iac_diagram/adapters/terraform/build.py` を足した | SKILL の取り込みが一部欠けると、TF アダプタを動かしてから落ちる。`doctor` で先に見つける。診断の文言は変えていない |
| `DiagnosticCodesTest`（`tests/test_tf_public.py`）は terraform の下の全 `.py` を読む（`glob("tf_*.py")` → `rglob("*.py")`） | 元の `glob("tf_*.py")` のままだと、新しいファイル名に当たらず、コードの診断コードを黙って読まなくなる |
| `adapters/terraform/hcl.py` は `evaluator/values.py` を import する（`const()` の `is_number`）。逆は無い | 向きは evaluator ← hcl。evaluator は構文木を知らない |

### 想定外だったこと・つまずいたこと
- `ModuleEval` だけで 1,720 行あり、ファイルを分けるだけでは 1,500 行以下にならなかった。クラスの分割（ミックスイン）が必要だった。
- 名前の付け替えで `plan/combine.py` に **ローカル変数 `mismatch` が関数 `mismatch` を隠す**バグを作った（`mismatch = mismatch(...)` で `UnboundLocalError`）。43 件のテストが落ちて気づいた。未定義の名前を調べる自作の確認（pyflakes 相当）は、ローカルの代入で隠れる名前を見つけられない。関数は `block_mismatch` にした。**名前を付け替えたら、同じ名前のローカル変数を grep すること。**
- 分割用の自作スクリプトが、最初の plan の分割でデコレータ（`@dataclass`）を落とした。生成したファイルに `dataclass` の import が出ないことで気づいた。
- `tf.os.path.relpath = other_drive` のようにモジュールの属性を直接書き換えるテストは、`os` は共有のオブジェクトなので、どのファイルに移しても効く。`mock.patch.object(P, "MAX_PLAN_BYTES")`・`_read_json`・`M.SUMMARY_FILE` は、その名前が定義されているファイル（`plan/read.py`・`modules/summaries.py`）に当て直した。
- argparse の usage の行は、プログラム名が `tf.py` → `adapt_tf.py` になり、折り返し位置だけが変わる。ほかの文言は同じ。

### 確かめたこと
- **golden**: 101/101 一致（`b2735ff`・`81003bd`・`3848347`・`ab3dacf` の各コミットで。Windows の通常の TEMP）。Linux（WSL、`git archive` した `ab3dacf`）でも 101/101（約 27 秒の CPU 時間）。
- **単体テスト 326 件**（323 + `test_no_exemptions_remain` + `adapt_tf.py` の CLI の 2 件（SKILL だけのコピーを日本語とスペースを含むパスで動かす、使い方の誤りは終了コード 2））: Windows の通常の TEMP、別のドライブの TEMP（`subst Y:`）、8.3 の短い名前の TEMP（`...\Temp\R2_LON~1`）のそれぞれで OK（約 91〜108 秒）。WSL（`git archive HEAD` を `/tmp` に展開し `uv sync --locked`）で OK（53 秒）。
- `uv lock --check` OK（66 パッケージ）。`uv sync --locked` OK。
- **CI の手順を手元で**（Git Bash）: `validate_ir.py` で正解 IR、`check_coverage.py --lint`、`c1_check.py`（入力 25・辺 513・対応の無い辺 0）、`adapt_tf.py` の自作 5 構成と plan JSON（plan だけ 7・`--plan` 7）と `validate_ir.py`、`tf_public_check.py --all --jobs 4`（205 フォルダ、リソース 11,621、error 0。Windows 約 40 秒、WSL 約 28 秒）。PowerShell 5.1 の「日本語とスペースを含むパスに SKILL を丸ごとコピーして起動」の文を CI と同じ文で通した（`doctor.py`・`validate_ir.py`・`adapt_tf.py` の `--var-file`・`--var`・`--plan`）。WSL でも SKILL だけのコピー（日本語とスペース）から `doctor.py`・`adapt_tf.py`・`validate_ir.py` を動かし、別のフォルダのシンボリックリンク経由（作業フォルダも別）で動かした出力が、直接動かした出力とバイト単位で同じ（同じ `--root-base` のとき）。
- **旧 `tf.py`（`26dca6b` を `git archive` で別の場所に展開）との比較**: 23 の呼び出し（`--help`・引数なし・`--input` なし・`--out` なし・不正な `--workspace`・`=` の無い `--var`・plan だけのときの `--plan`／`--var`／`--redact-var`／`--workspace`／`--var-file`・plan でない JSON・state の JSON・壊れた JSON・無いフォルダ・.tf の無いフォルダ・無い `--var-file`・`--out` がフォルダ・成功 4 通り・壊れた `--plan`）で、終了コード・標準出力・標準エラーが同じ（プログラム名と空白の折り返しは正規化）。成功 4 通りの出力ファイルはバイト単位で同じ（32,084・34,870・34,864・43,218 バイト）。
- **変異で、モンキーパッチが本当に効いていること**: ① `module_vars.var_file_name` の `except ValueError` を `KeyError` にする、② 同じ関数が `os.path.relpath` を使わなくする → `test_var_file_on_another_drive` が落ちる。③ `read.py` の `MAX_PLAN_BYTES` を直書きにする → `test_size_cap` が落ちる。④ `is_plan_file` が別名の `_RJ`（`_read_json` のコピー）を呼ぶ、⑤ `load_plan` が読み直す → `test_plan_is_parsed_once` が落ちる。⑥ `summaries.load` が別名 `_SF`（`SUMMARY_FILE` のコピー）を使う → `test_missing_table_warns_for_registry_modules` が落ちる。⑦ `Context.rel` が `relpath` を使わなくする → TF のテスト 4 件が落ちる。**⑥ と同じ変異は `test_missing_table_does_not_warn_without_registry_modules` を落とさない**（このテストは「警告が出ない」ことだけを見るので、パッチが効かなくても通る。R1 から持っている弱さで、警告が出る側のテストが守っている）。
- 構成のテスト 27 件（`EXEMPT` が空、サブパッケージの許可、アダプタの入口の import の禁止、相対 import など）が通る。

### 残したこと・リスク
- **R3**: `cfn.py`（1,327 行）の分割、入口 `adapt_cfn.py`、診断コードの一覧。`golden.py` の `ENTRY` の `cfn`、`test_architecture.py` の `adapters/cfn.py` を使う変異、`ENTRY_DIRS` の `adapters`。
- `ModuleEval` のミックスインは「状態を持たない」という約束をテストで守っていない（ミックスインのメソッドが `self.新しい属性 = …` と書いても、構成のテストは落ちない）。
- `type(self)(...)` による子の作成。`ModuleEval` を継承する新しいクラスを作るときは注意。
- `modules/summaries.py` の `SUMMARY_FILE` の相対の深さ（`parents[5]`）は R4（`data/` への移動）でまた直す。
- `.tf` の側と plan の側で重複していた `collect`／`dedupe`／`block_address`／`inst_address` は 1 つにした。`PSEUDO_DATA` は両方にあるが形が違う（`.tf` は属性 → 擬似パラメータ、plan は型 → 属性）ので残した。
- コミットのメッセージの番号は (1/4)〜(3/4) の後に (4/5) と書いた（途中で 5 つ目が増えたため）。

### レビューの指摘への対応（R2 の第三者レビュー: APPROVE WITH CHANGES）
動きの差は見つからなかった（約 110 万回の比較）。次の 5 点を 1 つのコミットで直した。
1. **古い参照**: `references/module-summaries.md` の 4 行目が `tf_modules.py` のままだったのを `modules/summaries.py` に直した。`git grep "tf_modules|tf_eval|tf_plan\.py|adapters/tf\.py"`（skills・README・SKILL.md・NOTICE・architecture.md・.github）の残りは、`ir-schema.md` の `tests/test_tf_plan.py`（実在するテスト）と architecture.md の「R2 で免除を外した」という履歴の記述だけ。
2. **`doctor.py` の `REQUIRED_FILES`**: 実行時に使うファイルをすべて並べた（48 の `.py`（`scripts/` の下。`maintenance/` を除く。`__init__.py` も）と、実行時に読むデータ 7 つ（アイコン辞書、2 つのスキーマ、3 つの規則表、TF の要約表）と `SKILL.md`。56 件）。新しいテスト `tests/test_doctor_required_files.py`（5 件）が、一覧とディスクの実行時ファイルが同じであること（足し忘れも、消したファイルの残しも失敗）、スクリプトが開く `references/…` のデータが `RUNTIME_DATA` にあること、一覧の全ファイルを 1 つずつ消すと `check_skill` が必ずそのファイルを error で報告すること、TF のモジュール 1 つを消した SKILL のコピーで `doctor.py` が終了コード 2 になることを確かめる。手でも、日本語とスペースを含むパスの完全なコピーで 56 ファイルを 1 つずつ消して `doctor.py` を動かした: 完全なコピーは終了コード 0（status ok）、55 ファイルは終了コード 2 で、欠けたファイルだけを報告。残りの 1 つは `scripts/doctor.py` 自身で、消すと doctor が動かない（Python が「ファイルが無い」で終了コード 2 になるだけで、doctor の報告ではない）。
3. **`adapters/terraform` の中の順序を守るテスト**: `TERRAFORM_GROUPS`・`INTRA_TERRAFORM`（evaluator ・ base ・ modules ・ mixins ・ module_eval ・ build ・ plan の 7 グループ。今の実行時の import と同じ最小の辺。`if TYPE_CHECKING:` の中は数えない）を `tests/test_architecture.py` に足し、docs/architecture.md の表（`terraform-order` の印）と照合する。`evaluator/values.py` → `module_eval`、`plan/values.py` → `module_expr`、`hcl.py` → `build` のほか、modules → base、mixins → `module_eval`、`module_eval` → `build`、`model.py` の `import … as`、相対 import、グループに無い新しいファイルを一時フォルダのコピーに入れ、どれも失敗する。TYPE_CHECKING の中の import が通ることも確かめる。architecture のテストは 27 → 34 件。
4. **使われていない `TYPE_CHECKING` の import**: `module_load`・`module_props`・`module_expr`・`module_vars` の 4 つから、`ModuleEval` の import と `TYPE_CHECKING` の import を外した。`pyflakes`（`skills`・`tests`・`aws-iac-diagram-workspace/tools`）は、この変更の前からある 3 件（`test_tf_adapter.py` の `v`、`test_tf_plan.py` の `pw`、`make_plan_json.py` の `moto`）だけ。
5. 小さな直し: `test_architecture.py` の docstring（`import tf` → `import adapt_tf`）、この節の「コミット 5 つ」。

単体テストは 338 件（326 + doctor 5 + architecture 7）。

## 2026-10-26 フェーズ2b の R3: CloudFormation の分割、診断コードの一覧

### 概要
構成の階層化（PLAN の 1.4）の 3 番目。**中身の動きは変えずに**、`scripts/adapters/cfn.py`（1,327 行。CLI、`_Loader`、650 行の `Evaluator`、`StackEval`、約 25 の関数）を入口 `scripts/adapt_cfn.py` と `scripts/aws_iac_diagram/adapters/cloudformation/` の 15 ファイル（最大 191 行）に分け、診断コードの一覧 `core/diagnostics.py` を作って、アダプタのコードとの照合をテストにした。旧パス `adapters/cfn.py` と `scripts/adapters/` は無くした（shim なし）。ローカルのブランチ `phase2b-r3`（main の `ed45a31` から。push はしていない）。第三者レビューは別。

### コミット
| # | 内容 |
|---|---|
| 1 `df13268` | `git mv adapters/cfn.py → cloudformation/evaluator.py`（本体をそのまま）。CLI・PEP 723 の宣言を入口 `adapt_cfn.py` へ。golden の `ENTRY`、doctor の `REQUIRED_FILES`、テスト、README、ir-schema.md、CI の参照を直し、CI に `adapt_cfn.py` の起動の手順（bash の 5 構成、PowerShell 5.1 の日本語パス）を足した |
| 2 `232d3dd` | `evaluator.py` を 15 ファイルに分ける（`evaluator.py` は `Evaluator` を持つファイルとして残る）。`tests/test_architecture.py` に `CLOUDFORMATION_GROUPS`・`INTRA_CLOUDFORMATION` と変異のテスト、architecture.md の表 |
| 3 `2ff41e7` | `core/diagnostics.py`、`DiagnosticRegistryRuleTest`、`tests/test_diagnostics.py`、ir-schema.md の 7.5 に CFN の一覧 |
| 4 | HANDOFF・WORKLOG（この節）・PLAN の状態、architecture.md の仕上げ |

依頼の順（1 git mv、2 分割、3 入口と参照と旧パスの削除、4 診断コード、5 文書）のうち、1 と 3 は 1 つのコミットにまとめた。理由: 旧パスを残す shim を作らない方針なので、本体を動かした時点で入口と参照も直さないと、そのコミットで golden が動かない（各コミットで golden 101/101 を守るため）。golden は 3 つのコード上のコミットのそれぞれで 101/101 一致、単体テストは 340 → 348 → 367 件が通った。

### 何がどこへ移ったか（行数は移した直後）
| 元（`adapters/cfn.py`） | 先（`aws_iac_diagram/adapters/cloudformation/`） | 行 |
|---|---|---|
| docstring・`main`（argparse、`--param`、終了コード、文言）・PEP 723 の宣言 | `scripts/adapt_cfn.py`（入口。宣言は変えていない） | 86 |
| `_Loader`（短縮タグ）・`_intrinsic`・`load_template`・`_bool_name`（→ `bool_name`） | `loader.py` | 82 |
| 定数（`PSEUDO`・`NO_VALUE`・`UNKNOWN`・`SUB_VAR` など）・`Context` | `model.py` | 64 |
| `_res_with_fn`・`_walk_res`・`_prepend_through`・`_set_fn`・`_strip_internal`・`split_concat` | `marks.py` | 74 |
| `_static_refs`・`_collect_active`・`_dedupe`（→ `dedupe_refs`） | `refs.py` | 77 |
| `Evaluator` の `__init__`・`diag`・`scan_refs`・`unknown`・`eval`・`addr`（と `StackEval` の `where`） | `evaluator.py`（`git mv` の本体。4 つのミックスインを束ねる） | 136 |
| `Evaluator.ref`・`getatt`・`sub`・`concat`・`join`・`select`・`split`・`find_in_map`・`pseudo`・`is_stack` | `intrinsics.py`（`IntrinsicsMixin`） | 191 |
| `Evaluator.condition`・`cond_eval`・`cond_value`・`fn_if`・`_cfn_str`・`_stronger`・`_weaker` | `conditions.py`（`ConditionsMixin`） | 102 |
| `Evaluator.parameter`・`load_parameter_file` | `params.py`（`ParametersMixin`） | 78 |
| `Evaluator.expand_inline_foreach`・`StackEval.expand_foreach`・`_foreach_subst` | `foreach.py`（`ForEachMixin`） | 92 |
| `StackEval.output`・`register_exports`・`import_value` | `outputs.py`（`OutputsMixin`） | 61 |
| `StackEval.stack_output`・`locate`（TemplateURL の読み替え）・`child` | `nested.py`（`NestedMixin`） | 117 |
| `StackEval.__init__`・`run`（リソースの評価、Condition → enabled、Globals、暗黙の API、DependsOn） | `stack.py` | 116 |
| `GLOBALS`・`_merge_globals`・`_is_intrinsic`・`_implicit_apis` | `sam.py` | 41 |
| `_cdk_artifacts`・`_cdk_stacks` | `cdk.py` | 57 |
| `build_raw`・`dump` | `build.py` | 88 |
| （新規） | `core/diagnostics.py` | 124 |

800 行を超えるファイルは `scripts/` に無くなった（最大は Terraform 側の `evaluator/functions.py` の 763 行）。1,500 行を超えるものも無い。

### 決めたこと
| 決めたこと | 理由 |
|---|---|
| `Evaluator`（650 行）と `StackEval`（300 行）は、責務ごとのミックスイン（`params`・`conditions`・`intrinsics`・`foreach`・`outputs`・`nested`）に分け、状態は `Evaluator.__init__`（テンプレート 1 つ分）と `StackEval.__init__`（スタックの入れ物）に残す | R2 と同じ方式。メソッドは `self.xxx` で呼び合うまま、動きを変えない。クラスを関数に直すと引数の受け渡しの書き換えが大きい |
| `StackEval(NestedMixin, OutputsMixin, Evaluator)` の継承の順に意味を持たせた（`Evaluator` の `stack_output`・`import_value` を上書きする）。`NestedMixin.stack_output` の `super()` は MRO で `Evaluator.stack_output` に届く | 元は `StackEval(Evaluator)` の `super()`。順序を入れ替えると黒箱の子の出力が変わる |
| 子のスタックは `StackEval(…)` でなく `type(self)(…)` で作る | ミックスインから `stack.py` を実行時に import しない（循環を避ける）。`StackEval` を継承するクラスは無いので動きは同じ |
| `multiplicity`（×N のリソースの印）を `StackEval.__init__` から `Evaluator.__init__` へ移した。どこからも読まれていなかった `foreach_origin` は無くした | `ForEachMixin` が使うので、ミックスインの使う属性は基底の `__init__` に集める。`foreach_origin` は定義だけで読まれていない（grep で確認）。どちらも出力に影響しない |
| 他のファイルから使う `_` 付きの名前は `_` を外した（`dedupe_refs`・`weaker`・`stronger`・`bool_name` など）。ファイルの中だけのもの（`_walk_res`・`_is_intrinsic`・`_cdk_artifacts`・`_Loader`・`_intrinsic`）は `_` のまま。`_maybe_json`（`= ir_raw.maybe_json` の別名）は使う側が `ir_raw.maybe_json` を直接呼ぶ | R2 と同じ |
| `where()` は `Evaluator` に置いた（`StackEval` にあったが、`prefix`・`stack_address` だけで決まるため） | `ForEachMixin.expand_foreach` が呼ぶ |
| 旧パス `adapters/cfn.py`・`scripts/adapters/` の互換は置かない。`tests/test_architecture.py` の `ENTRY_DIRS` には `adapters` を残す（戻さない印。`from adapters import …` は入口の import と数えて失敗する） | 配布したタグが無い。`entry_names` は `scripts/` の直下と `maintenance/` だけを見る |
| 診断コードの一覧は**データだけ**で、アダプタは実行時に読まない（検査のための表）。level は 1 コードにつき複数を持てる（`levels` は重い順のタプル） | 出力のバイト列を変えないため。実行時の検査（不明なコードで例外）は本番の経路を落としうるので入れない |
| 検査の範囲は `scripts/adapt_*.py` と `aws_iac_diagram/adapters/` の下。正規化の `NORM-…`（フェーズ 3 以降）は、その層ができるとき範囲を広げる | いまのコードにあるのは TF・CFN だけ。ほかの層に `E-NOEDGE-…` のような規則 ID が出ても誤検出しない |
| 旧 `DiagnosticCodesTest`（`tests/test_tf_public.py`）は `tests/test_diagnostics.py` に移し、TF と CFN の両方で一覧と ir-schema.md の 7.5 を照合する。ソースの文字列と一覧の照合は `DiagnosticRegistryRuleTest` が受け持つ（ソース ⇄ 一覧 ⇄ 文書で、推移的に同じ）。旧テストの「ソースの TF- の数 43」の固定は、一覧の数の固定（43 + 19 = 62）に変わった | 照合の相手が「ソース」から「一覧」に変わるため |
| ir-schema.md の 7.5 に CFN の一覧（19 個）を足した。「`コード`（level。説明）」の形にし、level が一覧と同じであることもテストする | それまで CFN のコードは文書に例が 1 つあるだけだった |

### 想定外だったこと・つまずいたこと
- Bash ツールのヒアドキュメントがバックスラッシュを壊す（`\n` が改行になる、`\c` が消える）。テストの文字列や CI の PowerShell の行（`\scripts\…`）の編集は Edit ツールで行い、テストの SyntaxError で気づいたものは直した。
- 診断コードの level は、コードの書かれた場所だけでは決まらない（`Unknown(…)` の既定の level は warn、作られないリソースの中では info に下がる、plan JSON と一緒のときは info に上書きされる）。そのため、一覧の `levels` は呼び出しの近くの文字列（静的）と、動かして出た (code, level)（golden の 101 ケースの出力の集計と、fixture と小さな入力で動かすテスト）の両方で確かめた。複数の level で出るコード（一覧の `warn/info` など）: `TF-EVAL-ERROR`・`TF-UNEVALUATED`・`TF-UNRESOLVED-VAR`・`TF-UNSUPPORTED-FUNCTION`・`TF-TFJSON-UNSUPPORTED`・`TF-PLAN-DESTROY`・`CFN-CONDITION-UNKNOWN`・`CFN-NESTED-CYCLE`・`CFN-NESTED-UNREADABLE`（9 個）。
- ir-schema.md の「43 個」は、旧テストが `"(TF-…)"` の正規表現でソースを数えていた。固定の数の意味は、ソースの文字列を足すたびに変わるので弱かった。

### 確かめたこと
- **golden**: 101/101 一致（`df13268`・`232d3dd`・`2ff41e7` の各コミット。Windows の通常の TEMP）。
- **単体テスト 367 件**（338 + `adapt_cfn.py` の CLI 2 + `CloudFormationOrderTest` 8 + `DiagnosticRegistryRuleTest` 10 + `tests/test_diagnostics.py` 10 − 旧 `DiagnosticCodesTest` 1）: Windows の通常の TEMP、別のドライブの TEMP（`subst Y:`）、8.3 の短い名前の TEMP（`...\Temp\R3_LON~1`）のそれぞれで OK（約 84 秒）。
- `uv lock --check` OK（66 パッケージ）。pyflakes は、この変更の前からある 3 件（`test_tf_adapter.py` の `v`、`test_tf_plan.py` の `pw`、`make_plan_json.py` の `moto`）だけ。
- **CI の手順を手元で**（Git Bash）: `validate_ir.py` で正解 IR、`check_coverage.py --lint`、`c1_check.py`（入力 25・辺 513・対応の無い辺 0）、TF の 5 構成と plan JSON、足した CFN の 5 構成（`adapt_cfn.py` を `uv run`。PyYAML は PEP 723 の宣言で入る）と `validate_ir.py`、`tf_public_check.py --all --jobs 4`（205 フォルダ、リソース 11,621、error 0。28 秒）。PowerShell 5.1 の「日本語とスペースを含むパスに SKILL を丸ごとコピーして起動」の文（`doctor.py`・`validate_ir.py`・`adapt_tf.py`・`adapt_cfn.py`）を CI と同じ文で通し、コピーからの CFN の出力がリポジトリのものと同じ hash であることを確かめた。
- **旧 `cfn.py`（`ed45a31` を `git archive` で別の場所に展開）との比較**: ① CLI を 80 通りで動かし、終了コード・標準出力・標準エラー（プログラム名と空白を正規化）・書かれたファイルのバイト列が同じ（`--help`・引数なし・`--input`／`--out` なし・未知のオプション・無い入力・manifest の無いフォルダ・空・リスト・壊れた YAML／JSON・タブの `.template`・自分を指すアンカー（RecursionError → 終了コード 2）・`--param` の誤り・`--param-file` の無い／壊れた／形の違う／正しい／辞書の形・擬似パラメータ・ネストスタック・SAM・JSON・cdk.out（入れ子のアセンブリと Export／ImportValue）・manifest.json を直接・スタックの無い cdk.out・`--out` の親が無い・`--root-base ..`・C1 の 25 入力を `--param` なしと 3 つの `--param` ありで）。② 変異: C1 の 25 入力に、行の削除・ブロックの削除・行の複製・入れ替え・引数の並べ替え・組み込み関数の取り替え（`!Ref`→`!GetAtt` など）・値の差し替え（null・[]・{}・未定義の名前・引数不足の `!If` など）・Condition の差し替え・Conditions への不正な条件（自分を指す、引数の数が違う）・不正な Fn::ForEach（引数の数、入れ子、集まりが決まらない）・`!If` の入れ子（深さ 6 まで）・字下げの崩しを 1〜3 個入れた入力 1,000 通りを、`--param` なし／ありで、計 2,000 回の `main()` を旧・新で比べ、終了コード・標準出力・標準エラー・出力のバイト列が全部同じ（成功 1,420 回、終了コード 2 が 580 回。出力に現れた CFN の診断コードは 13 種）。
- 構成のテスト（`CloudFormationOrderTest` など）の変異: `loader`／`marks`／`refs`／`model`／`cdk`（base）から上のグループを、ミックスインから `evaluator`／`stack`／`build` を、`evaluator` から `stack`／`build` を、`stack` から `build` を import させると失敗する。相対 import、`TYPE_CHECKING` の中の import（数えない）、表に無い新しいファイル、cloudformation → terraform／registry の import も失敗する。
- 診断コードの変異（`DiagnosticRegistryRuleTest`）: 一覧に無いコード（`self.diag(…)`・辞書・タプル・既定の引数・集合・入口のスクリプトの中）、打ち間違い、`"TF-" + 名前`・`f"TF-{x}"`・`"TF-%s" % x` の組み立て、一覧にだけあるコード（集合・比較・`in (…)` にだけ書いてあるものも含む）、一覧に無い level で出す、が失敗する。`UNUSED_ALLOW` は空で、古い許可は失敗する。

### 残したこと・リスク
- **R4**: `data/` への分割。`modules/summaries.py` の `SUMMARY_FILE` の相対の深さ。R5: テストの分け直し（`test_cfn_adapter.py` は 1,100 行を超える）。R6: SKILL.md・references・docs/spec・architecture.md の「R」の印を全部消す。
- ミックスインが「状態を持たない」ことはテストで守っていない（R2 と同じ）。`StackEval` の継承の順（`NestedMixin`・`OutputsMixin` が `Evaluator` の前）を入れ替えると、`super()` の行き先が変わる。コメントと docs/architecture.md に書いたが、テストは黒箱の子の出力を見る既存のものに頼っている。
- `type(self)(…)` による子の作成（`StackEval` を継承する新しいクラスを作るときは注意）。
- 診断コードの検査の限界: 接頭辞が単独の文字列になっていない組み立て（`"TF" + "-X"`）、範囲の外（`adapters/` と `adapt_*.py` 以外）のコード、level を変数で渡すところの level は静的には見られない。level は動かして出たものの確認（`EmittedLevelsTest`）で補っているが、fixture が通らない経路の level は、呼び出しの近くの文字列と読んだ結果に頼っている。`levels` が実際に出うる level より多い（出ない level を書いている）ことは検出できない。
- `adapt_cfn.py` は `yaml` を入口で import する（`yaml.YAMLError` を捕まえるため）。元の `cfn.py` と同じ。
- CI に足した `adapt_cfn.py` の手順は、手元の Git Bash と PowerShell 5.1 で通したが、GitHub の Actions ではまだ動かしていない。

### レビューの指摘への対応（R3 の第三者レビュー: APPROVE。約 6,400 ケースの比較で差 0。小さな追加 5 点を 1 つのコミットで直した）
単体テストは 367 → 372 件（architecture +2、`tests/test_diagnostics.py` +3）。golden は 101/101。
1. **m2: ir-schema.md の level を TF でも照合。** 7.5 の TF の一覧を CFN と同じ「`コード`（level。説明）」の形に書き直し（説明は一覧の説明と同じ）、`DiagnosticCodesTest.doc_level_problems` が TF・CFN の全 62 コードについて、文書に書いた level と一覧の `levels` が同じことを確かめる（level の語は先頭の「（…。」の部分だけを読む。説明の中の warn・info の語に引きずられない）。変異: 文書の `TF-COUNT-INDEX（info` を warn に変える、`TF-UNEVALUATED（warn／info` を warn に変える、など 5 通りと、項目を消す場合が失敗する（実ファイルでも `TF-COUNT-INDEX` を warn に変えて失敗を確かめ、戻した）。`test_levels_that_the_fixtures_do_not_reach` に、`CFN-NESTED-UNREADABLE` の error（子テンプレートが YAML として読めない。見つからない子は warn）と、`TF-UNSUPPORTED-FUNCTION` の info（`count = 0` のリソースで未知の関数。`count = 1` なら warn）を足した。変異: 一覧の `_row("TF-UNSUPPORTED-FUNCTION", "warn/info"` を `"warn"` にする、`CFN-NESTED-UNREADABLE` の `"error/warn"` を `"warn"` にする、のどちらも失敗する（動かして出た level のテストと、文書との照合の両方で）。
2. **m3: コードの走査を既知の接頭辞に限った。** `core/diagnostics.py` に `ALLOWED_PREFIXES`（`("TF", "CFN")`。`PREFIXES` と同じ。`NORM-` などは意図して足す）。走査は接頭辞が `ALLOWED_PREFIXES` のコードの形の文字列だけを数える。`"UTF-8"`・`"GET-OBJECT"` のような別の接頭辞の文字列は、診断を出す位置の外（代入、比較、集合、`open(..., encoding="UTF-8")` などの呼び出し、`diag` 以外の関数の引数、level の無いタプル）なら無視する。診断を出す位置（`diag`・`unknown`・`Unknown`・`unknown_from` の引数、辞書の `"code"` の値、level の文字列つきのタプル）にあるのに接頭辞が未登録なら、「接頭辞 X が core/diagnostics.py の ALLOWED_PREFIXES に無い（新しい接頭辞なら、そこと PREFIXES に意図して足す）」で失敗する。変異のテスト: 7 通りの出す位置（`self.diag("warn", "NORM-…")`、`"GET-OBJECT"`、辞書、`Unknown`、`unknown_from`、タプル、キーワード引数）が失敗し、8 通りの出す位置の外が通り、`ALLOWED_PREFIXES` に足すと「一覧に無いコード」の失敗に変わる。
3. **m1: 静的な検査は最善の努力であることを書いた。** `diagnostic_scan_files` の docstring と docs/architecture.md に、すり抜けるもの（接頭辞が単独の文字列になっていない組み立て、変数・既定の引数で渡す level、範囲の外で診断を出すコード、接頭辞が未登録で出す位置の外のコードの形の文字列）と、動的な安全網（`EmittedLevelsTest`、旧コードとの差分比較、golden）を書いた。
4. **n2: `DIAGNOSTICS` を読み取り専用にした**（`types.MappingProxyType`。書き換えている呼び出しは無いことを grep で確かめた: `lookup`・`codes`・テストの読み取りだけ）。代入と削除が `TypeError` になることをテストする。
5. **n3: CI の Linux の「日本語とスペースを含むパス」の手順に、`adapt_tf.py`（`--var-file env/dev.tfvars --var project=demo`）と `adapt_cfn.py`（`--param EnvType=prod`）と、それぞれの `validate_ir.py` を足した**（PowerShell の手順と同じ fixture）。手順の `run:` をそのまま取り出して Git Bash（`bash -e`）で通し、WSL でも通した。GitHub の Actions ではまだ動かしていない。

## 2026-10-26 フェーズ2b の R4: スクリプトが読むデータを `data/` へ

### 概要
構成の階層化（PLAN の 1.4）の 4 番目。**スクリプトが実行時に読むファイルを `references/` から `skills/aws-iac-diagram/data/` に移した**（1 ファイル 1 単位）。R1〜R3 と違い、**出力のバイト列が変わる手順**: 診断の文言に入っていた要約表のパスが変わるため（golden の 14 ケース）。それ以外の動きは変えていない。ブランチ `phase2b-r4`（main の `6a6839c` から）。

### コミット
| # | 内容 |
|---|---|
| 1 `9fbcd1f` | ファイルの移動と、ローダー・doctor・テストの直し。golden 101/101（診断の文言はまだ旧パス）。`core/paths.py`、要約表のフォルダ読み込み、`tests/test_paths.py` |
| 2 `f0a1bbe` | 診断の文言 3 つのパスを直し、golden の 14 ケースを `--update --accept-changes` で更新（理由と証明はコミットメッセージと下の「golden の更新」） |
| 3 `c14a8f8` | README・NOTICE・ir-schema.md・architecture.md の直し |
| 4 | HANDOFF・WORKLOG（この節）・PLAN の状態 |

### 何がどこへ移ったか
| 元（`skills/aws-iac-diagram/`） | 先 | 方法 |
|---|---|---|
| `references/ir.schema.json`・`ir-raw.schema.json` | `data/schemas/` | `git mv` |
| `references/icons/`（`catalog.json`・`broken.json`・カテゴリ別 `.md` 31 個） | `data/icons/` | `git mv`（中身は同じ。再生成してもバイト単位で同じ） |
| `references/module-summaries.md`（4,826 行） | `data/module-summaries/terraform-aws-vpc/v6.md`（1,057 行）・`terraform-aws-alb/v10.md`（997）・`terraform-aws-rds/v7.md`（1,421。本体 + サブモジュール 5）・`terraform-aws-eks/v21.md`（1,302。本体 + サブモジュール 3）・`iam-only-sources.md`（H-IAM の一覧）。説明の部分は `docs/spec/module-summaries.md` | 分割（一回限りの Python。`git mv` では履歴は付かない） |
| （新規） | `scripts/aws_iac_diagram/core/paths.py`、`tests/test_paths.py`、`docs/spec/` | |
| 動かさないもの | `references/ir-schema.md`・`resource-catalog.md`・`relation-resources.md`・`edge-rules.md`（R6・フェーズ 3） | |

### ローダーの変更
- `core/paths.py`: `SKILL_DIR = Path(__file__).resolve().parents[3]`（core → aws_iac_diagram → scripts → SKILL）と、`IR_SCHEMA`・`IR_RAW_SCHEMA`・`ICON_CATALOG`・`ICON_BROKEN`・`MODULE_SUMMARIES_DIR`・`ASSETS_DIR`・`RULE_DOCS`・`RESOURCE_CATALOG`。標準ライブラリだけ。`validate_ir.py`・`find_aws_icon.py`（`sys.path` への 1 行を足して import）・`maintenance/` の 2 つ・`summaries.py` が使う。`doctor.py` だけは自分で `SKILL_DIR` を決める（パッケージが欠けていても動くため）。
- `modules/summaries.py`: `SUMMARY_FILE`（`parents[5]`）→ `SUMMARY_DIR`（`paths.MODULE_SUMMARIES_DIR`）。`load(path)` はフォルダの下の `.md` を「文字と数を分けた順序」（`v6` は `v10` の前）で読む。ファイルを渡すとそのファイル 1 つ。パースの規則（マーカー、コードブロック、`# not-covered:`、H-IAM）はそのまま。`Summary` に `file` を足した（`module_load.summary_tree` のキャッシュのキーに入れる。`line` はファイル内の行になったため、別ファイルの同じ行と衝突しない）。
- doctor の `REQUIRED_FILES`: `data/` の 8 ファイル（`catalog.json`、スキーマ 2、要約表 4 + `iam-only-sources.md`）と `core/paths.py` を足し、旧 `references/` の 3 つ（`icons/catalog.json`・スキーマ 2・`module-summaries.md`）を外した。ディレクトリのパターンにはしなかった（下の「決めたこと」）。

### golden の更新（意図した変更）
診断の文言 3 つの `references/module-summaries.md` を `data/module-summaries/` にした: `TF-MODULE-BLACKBOX`（"not in the summary table (…)"）、`TF-MODULE-SUMMARY-TABLE-MISSING`（"the summary table (…) is missing or empty"）、`TF-MODULE-SUMMARY`（"expanded from the summary table (…; …)"）。他の文言（`TF-MODULE-SUMMARY-INPUT` など）にパスは入っていない。

変わった 14 ケース（件数は同じで、hash と bytes だけ）: `tf/custom/three-tier-modules`、`tf/public/` の `aws-transit-gateway-vpc-terraform`・`hub-and-spoke-with-shared-services-vpc-terraform`・`learn-terraform-provision-eks-cluster`・`learn-terraform-rds`・`terraform-aws-bedrock/examples/agent-with-knowledge-base`・`terraform-aws-cloudfront/examples/complete`・`terraform-aws-ecs/examples/fargate`・`terraform-aws-eks-blueprints/patterns/blue-green-upgrade/{eks-blue,eks-green,environment}`・`terraform-aws-eks/examples/eks-managed-node-group`・`terraform-aws-rds-aurora/examples/postgresql`・`terraform-aws-vpc/examples/complete`。

**機械的な証明**（`golden.py --dump` で 1/4 のコミットの 101 件を書き、文言を直した後の 101 件と比べた）: 14 件は、旧い出力の `references/module-summaries.md` を `data/module-summaries/` に置換すると新しい出力とバイト単位で一致する（置換は全部で 49 か所）。残りの 87 件は置換前から新しい出力と同じで、旧パスを含まない。ほかの差は無い。更新は `golden.py --update --accept-changes`（manifest の差分は 14 ケースの `sha256`・`bytes` の 28 行だけ）。

### 決めたこと
| 決めたこと | 理由 |
|---|---|
| 要約表は「1 モジュールの 1 major につき 1 ファイル」。サブモジュールの表は親と同じファイル（rds v7 に 6 つ、eks v21 に 4 つ） | サブモジュールの版は親と一緒に上がる。`module_expand` が親の `majors` でサブモジュールの表を選ぶので、ファイルを分けると選び方が変わる |
| H-IAM の一覧は `data/module-summaries/iam-only-sources.md`（フォルダの直下） | 版を持たない。ローダーはフォルダの下の `.md` をすべて同じ規則で読むので、置き場所でコードを分けない |
| ローダーは「フォルダの下の `.md` をすべて」読む。doctor の一覧は明示のファイル名のまま | doctor は「足りないファイル名を出す」ために明示の一覧を持つ（パッケージが欠けても動かす。一覧と実際のファイルの一致は `test_doctor_required_files` が確かめる）。パターンにすると、ファイルが 1 つ欠けても気づけない |
| ファイルを足したときの doctor と `RUNTIME_DATA` の更新は手作業のまま（テストが落ちて気づく） | 同上 |
| `SUMMARY_FILE` の名前は残さず `SUMMARY_DIR` にした。ファイルを渡す `load(path)` は残した | 互換の shim を置かない方針（R2・R3）。テストは無い・空のフォルダに差し替える |
| 文言のパスは、実際に読んだファイル名でなく静的に `data/module-summaries/` にした | 変える範囲を「パスの文字列」だけに絞る（機械的に証明できる）。ファイル名を入れると文言が表ごとに変わる |
| ファイル先頭の見出しと説明の行（`# …`・`> …`）、表ごとの見出し（`### …`）は残す | パースは `<!-- module-summary … -->` の行と直後のコードブロックしか見ない（旧ローダーで読んだ結果が同じことで確認） |
| 説明（考え方・版の選び方・直し方・本物と突き合わせた結果）は `docs/spec/module-summaries.md`。表の置き場所の節を足した | 説明は開発者向け（SKILL の外）。R6 で `docs/spec/` の残りを作る |
| `find_aws_icon.py` は `core/paths.py` を import する（`sys.path` に `scripts/` を入れる 1 行を足した） | 場所の決め方を 1 か所にするため。パッケージが欠けた取り込みでは import で落ちるが、その前に doctor が欠けを報告する。`maintenance/` の 2 つも同様 |
| `data/icons/broken.json` は doctor の一覧に入れない | 実行時には読まない（保守用の出力。`catalog.json` に `broken` として反映済み） |
| PLAN は状態の行・2b の行・1.4 の「状況」に R4 を足しただけ（構成図は元から `data/` を書いてあった） | |

### 確かめたこと
- **golden**: 1/4 のコミットで 101/101。2/4 で 14 ケースを意図して更新し、その後 101/101（Windows と WSL）。
- **単体テスト 381 件**（372 + `tests/test_paths.py` の 9）: Windows の通常の TEMP、別のドライブの TEMP（`subst Y:`）、8.3 の短い名前の TEMP（`...\Temp\R4-LON~1`）のそれぞれで OK（約 90 秒）。WSL（Ubuntu、`git archive HEAD` の複製を `/tmp` に展開、`uv sync --locked`）でも OK（47 秒）。
- `uv lock --check` OK（66 パッケージ）。pyflakes は、この変更の前からある `test_tf_adapter.py` の `v` の 1 件だけ（ほかの触ったファイルは 0）。
- **アイコン辞書の再生成**: `build_icon_catalog.py` と `check_icons.py`（draw.io 32.4.1 で 1032 件を判定、壊れ 0、対照 9 件）を実行しても、`data/icons/` のファイルに差が無い（生成されるヘッダにパスの文字列は入っていないので、差はゼロ）。
- **要約表の分割の照合**: 旧ファイルを旧ローダー（`6a6839c`）で読んだ結果と、フォルダを新ローダーで読んだ結果で、12 の source の `(source, majors, text, uncovered)` と H-IAM の一覧が同じ。違うのは `dict` の並び順だけ（並び順に依存する所は無い。`load()[0]` は `.get` と真偽値でしか使わない）。
- **旧コード（`6a6839c` の `git archive`）との CLI の比較 665 通り**（終了コード・標準出力・標準エラー・書かれたファイルのバイト列。許した差は `references/module-summaries.md` → `data/module-summaries/`、SKILL・出力先のパスの読み替え、トレースバックの行番号だけ）:
  - golden の 101 ケース: 差 0（14 ケース 49 か所が置換）。
  - `fixtures/public` の `.tf` のあるフォルダ 205: 差 0（60 件 178 か所が置換）。
  - モジュールの source × 版の制約の合成 285: 差 0（117 件 126 か所が置換）。vpc・alb・rds・eks・rds の db_instance・eks の fargate-profile・ホスト名つき vpc に `None`・`~> 5.0`・`6.6.0`・`>= 6`・`>= 6.0, < 7.0`・`< 6`・`!= 6.0`・`garbage`・`>= 100`・`~> 10.0`・`~> 21.0`・`~> 20.0`・`v6.7.3`・空文字など 32 通り、IAM・aws-ia・git・存在しないローカル・kms に 4 通り、`fixtures/public` にある terraform-aws-modules の (source, version) 34 組。出力は 285 通りすべて違い、`module_summary` のリソースが 436、`module_blackbox` が 217。
  - ツール 74: 差 0。`validate_ir.py`（正解 IR、golden の出力 34 件、改変した入力、存在しないファイル、引数なし）48、`find_aws_icon.py` 20、`doctor.py` 2、入口の誤用 4。許した差は、存在しないファイルを渡したときの未捕捉の例外のトレースバックの行番号だけ（元からの動き）。
  - **要約表が無いとき**（旧は `references/module-summaries.md` を、新は `data/module-summaries/` を消した複製）の `TF-MODULE-SUMMARY-TABLE-MISSING` の出力は、パスの文字列だけが違う。同じ条件で `find_aws_icon.py` の「辞書がありません」の文もパスだけが違い、doctor はどちらも error（終了コード 2）で欠けたファイルの名前を挙げる。
- **自己完結**: SKILL のフォルダだけを `%TEMP%\日本語 パス\深い\a\b\スキル copy\aws-iac-diagram` に複製（深さも名前も変えた）し、上の golden 101・ツール 74・合成 285 を複製に対して動かして、旧コードと比べた（差は、doctor の `skill.dir` と `non_ascii_path` だけ）。`uv run`（PEP 723）で `adapt_tf.py`（three-tier-modules。要約表が要る）・`adapt_cfn.py`・`validate_ir.py`（スキーマが要る）・`find_aws_icon.py`・`doctor.py`（missing_files が空）を動かし、リポジトリの中の出力とバイト単位で同じ。WSL（`/tmp/r4wsl/日本語 パス/深い/a/b/`）でも同じ。
- **CI の手順を手元で**: Git Bash — `validate_ir.py`（正解 IR 5）、`check_coverage.py --lint`、`c1_check.py`（入力 25・辺 513・対応の無い辺 0）、TF 5 構成・CFN 5 構成・plan JSON 14 の起動と `validate_ir.py`（すべて OK）、`tf_public_check.py --all --jobs 4`（205 フォルダ、リソース 11,621、error 0）。PowerShell 5.1 — CI の Windows の手順（日本語のパスに SKILL を複製）を取り出して実行（doctor ok、`adapt_tf`・`--plan`・`adapt_cfn` と `validate_ir.py` が通る）。WSL — `unittest`・golden・`tf_public_check.py --all`・`c1_check.py`・`validate_ir.py`・`check_coverage.py --lint`（Windows と同じ数字）。
- 変異で検査が落ちること: `paths.py` の `parents[3]` を `[2]` に（18 件失敗）、`summaries.py` が `SUMMARY_DIR` を無視する（`SummaryTableFileTest` が失敗）、要約表のファイルを 1 つ消す（`SummaryTest`・doctor・`test_paths` が失敗）、ファイルの並べ方を自然順から外す（`test_paths` が失敗）。

### 残したこと・リスク
- **R5**: テストの分け直し。**R6**: `references/`（`ir-schema.md` と規則表 3 つ）の整理、`docs/spec/` の残り。`data/rules/` はフェーズ 3。`validate_ir.py` は規則表 3 つを今も `references/` から読む（`paths.RULE_DOCS`）。
- 要約表のファイルが**1 つだけ**欠けたとき（例: `terraform-aws-rds/v7.md`）、アダプタは黙ってそのモジュールを黒箱にする（info の `TF-MODULE-BLACKBOX`）。旧は 1 ファイルなので全部が欠けるか全部あるかだった。`TF-MODULE-SUMMARY-TABLE-MISSING`（warn）はフォルダが空のときだけ。欠けは doctor が名前を挙げる（`REQUIRED_FILES`）。ローダーは読めないファイル（`OSError`）を黙って飛ばす（旧と同じ）。
- 要約表のファイル名と `majors` の整合（`v6.md` に `majors="7"` を書く、など）は、テスト（`test_real_tables_are_one_file_per_module_and_major`）が今ある表について確かめるだけで、ローダーは検査しない。
- `find_aws_icon.py` は、パッケージ `aws_iac_diagram` が欠けた取り込みでは import で落ちる（以前は単独で動いた）。doctor の一覧にパッケージが入っているので、その場合は doctor が error にする。
- 差分比較は Windows の venv の Python で行った（`uv run` の経路は複製の 5 本と CI の手順だけ）。Linux は golden と `tf_public_check` と単体テストで同じ結果を確かめたが、旧コードとの CLI 比較は Windows だけ。
- 分割は `git mv` でないので、`git log --follow` で要約表の履歴は追えない（`references/module-summaries.md` の履歴はそのまま残る）。

### レビューの指摘への対応（R4 の第三者レビュー: APPROVE WITH CHANGES。1 つのコミットで直した）
単体テストは 381 → 391 件（`tests/test_paths.py` +7、`test_doctor_required_files.py` +1、`test_tf_adapter.py` +2）。golden は 101/101（文言は直した後のまま）。
1. **MAJOR（ライセンス表示）。** 元の `references/module-summaries.md` にあった「terraform-aws-modules（Apache-2.0）のソースを写して短くしたもの（改変あり）、出典は NOTICE の 2(b)」が、分けた後のデータのファイルに無かった（先頭は SKILL の外の `docs/spec/` へのリンクだけ）。`data/module-summaries/` の**すべてのファイル**（`v*.md` 4 つと `iam-only-sources.md`）の先頭の引用に、上流のリポジトリ名・Apache License 2.0・改変あり・出典はリポジトリ直下の NOTICE の 2(b) と `NOTICE.md` と上流の LICENSE、を書いた（`iam-only-sources.md` はソースコードの写しではなく source 名の一覧だと書いた）。`docs/spec/module-summaries.md` への死んだ相対リンクは「リポジトリの docs/spec/module-summaries.md（SKILL の外）」の文にした。**`data/module-summaries/NOTICE.md`**（SKILL だけを配っても残る）: 4 つのファイルの上流の URL、写した版とコミット、ライセンスの URL（https://www.apache.org/licenses/LICENSE-2.0）、改変の内容、全文は `assets/vendor/LICENSE-drawio-Apache-2.0.txt`（標準の Apache-2.0 の本文）と同じ、実行時には読まないこと。ルートの NOTICE の 2(b) にも `NOTICE.md` を書いた。
   - **doctor との整合は「一覧に入れる」にした**: `NOTICE.md` は実行時に読まないが、ライセンス表示なので配布に必須（欠けたら取り込みの不備）。`REQUIRED_FILES` と `RUNTIME_DATA` に入れ、規則を `tests/test_doctor_required_files.py` の `RUNTIME_DATA` の上に書いた（配る同梱ファイルのうち、実行時に読むものと、配布に必須の表示。読まれない .md を許すのは `NOTICE.md` だけ）。「`NOTICE.md` を除く」例外を等式のテストに入れるより、一覧とファイルの等式をそのまま保つほうが単純。
   - **ローダーは `NOTICE.md` を読まない。** 読むファイルを名前で決めた（下の 4）。中にマーカーを書いた `NOTICE.md`（フォルダ直下・モジュールのフォルダの中）でも読まれないこと、本物のフォルダに偽の `NOTICE.md` を足しても結果が同じことをテストした。
   - ヘッダの文はパースに影響しない（読むのはマーカーの行と直後のコードブロックだけ）。旧ローダー（`6a6839c`）と新ローダーの照合を取り直した: 12 の source の表（`source`・`majors`・`text`・`uncovered`）、H-IAM の一覧、`choose()` を 19 の source（12 の表、ホスト名つき、iam、aws-ia、git、ローカル、kms、サブモジュールの表なし）× 35 の版の制約（665 通り）、`iam_only()` が、すべて同じ（違いは診断の文言のパスだけで、比べる前に読み替えた）。
2. **MINOR（1 ファイルの欠けで黙って劣化する）。** `summaries.KNOWN_MODULES`（vpc・alb・rds・eks の最上位の source）を足した。`resolve.blackbox_plan` は、表が 1 つも読めないときに加えて、呼び出しの source（`//…` を除く）が `KNOWN_MODULES` にあり、読んだ表に無い（モジュールのフォルダごと欠けた）ときも、既存の `TF-MODULE-SUMMARY-TABLE-MISSING`（warn。文言は同じ）にする。`KNOWN_MODULES` が出荷した表の最上位の source と同じことをテストが確かめる。**限界（文書に書いた）:** モジュールの表はあるが、呼び出しの major のファイルだけが無いときは、これまでどおり黒箱の info（`TF-MODULE-BLACKBOX`）。そのファイルは doctor の `REQUIRED_FILES` が名前で知らせる（テスト `test_missing_major_of_a_present_module_stays_a_blackbox_info`）。`core/diagnostics.py` と ir-schema.md の説明に「フォルダごと無いとき」を足した。
3. **MINOR（`problems()`）。** `summaries.problems(path)` が、読まれない .md（綴り・大文字小文字・深さ）、空のファイル、コードブロックの無いマーカー、ファイル名の major と `majors` のずれ、フォルダ名と source のずれ（`terraform-aws-modules/vpc/aws` は `terraform-aws-vpc/`）、同じ (source, major) の表の重複、`v06.md` のような正規でない名前、`iam-only-sources.md` に source が無い、を文で返す。欠け（ファイルが無いこと）は調べない（doctor の一覧の役目で、二重に報告しない）。出荷した表で空であることをテストが確かめる。**doctor からも呼ぶ**（`summaries` は標準ライブラリだけで、`aws_iac_diagram` の `__init__` はどれも docstring だけなので、doctor の `dependencies = []` のまま import できる。import できなければ調べない: パッケージの欠けは `missing_files` が知らせる）。結果は `skill.table_problems`（リスト）に出し、1 件ごとに error にする。このキーは doctor の JSON に増えた唯一の変更。
4. **NIT。** 読むファイルを `<モジュール>/v[0-9]{1,9}.md`（1 階層下）と直下の `iam-only-sources.md` の**完全一致**にした（大文字小文字を区別するので、Windows と Linux で同じ。`V6.md`・`v6.MD`・`v6.md.bak`・`v1²2.md`・深い階層・直下の `v6.md` は読まれず、`problems()` が `.md` のものを知らせる）。並べ方のキーを (モジュールのフォルダ名, major の数, 相対パス) にして、`iterdir` の順に依らない（逆順・並べ替えた順の `iterdir` でも同じことをテスト）。`int()` は桁数を `{1,9}` に絞った名前にしか使わないので、例外にならない（100 桁の名前のファイルと、5,000 桁の文字列での正規表現のテスト）。`v06.md` と `v6.md` が並ぶときはパスの順で決まり、`problems()` が知らせる。
- **確かめたこと（レビュー対応）**: 単体テスト 391 件が Windows の通常の TEMP と別のドライブの TEMP（`subst Y:`）で OK、WSL（`git archive` のツリー）でも OK。golden 101/101（Windows・WSL）。`uv lock --check` OK、pyflakes は既存の 1 件だけ。旧コードとの CLI の比較をやり直した: golden 101・合成 285 は差 0（許した差は旧パスの置換だけ）、ツール 74 は doctor の JSON に `skill.table_problems: []` が増えた 2 件以外は差 0。変異で落ちること: ファイル名を大文字小文字無視で照合する、`KNOWN_MODULES` の分岐を外す、`KNOWN_MODULES` から eks を外す、`NOTICE.md` を例外にしない、のそれぞれでテストが落ちる。SKILL だけを日本語とスペースを含む別の深さに複製（WSL）: `adapt_tf.py` の three-tier-modules が複製とリポジトリでバイト単位で同じ、doctor はファイルを 1 つ消すと終了コード 2（`missing_files` に名前）、`NOTICE.md` を消しても 2、`terraform-aws-vpc/` をフォルダごと消すと `adapt_tf.py` が `TF-MODULE-SUMMARY-TABLE-MISSING`（warn）を出して doctor も 2、綴りの違う `V7.md` を足すと doctor が 2 で `table_problems` に出る。
- **残るリスク**: 要約表のファイルの中身の整合（HCL として読めること）は `problems()` でなく既存の `SummaryTest` が確かめる（doctor は hcl2 を使わない）。`KNOWN_MODULES` は手で持つ（別のモジュールの表を足したら足す。文書に書いた）。`NOTICE.md` の「ファイル名は別の Apache-2.0 の成果物のものだが本文は標準」という書き方は、全文を別に置くより簡潔にしたもの（ライセンス全文を各所に複製しない）。

## 2026-10-26 フェーズ2b の R5: テストを `unit/`・`integration/`・`golden/`・`architecture/` に分ける

### 概要
構成の階層化（PLAN の 1.4）の 5 番目。**`tests/` の直下に平らに置いた 15 ファイル（391 件）を、`tests/unit/`・`integration/`・`golden/`・`architecture/` の 39 ファイルと、共有の道具 `tests/support/` に分けた。** 何を確かめるか（テストの本文）は 1 文字も変えていない。足したのは `tests/architecture/test_test_layout.py`（7 件。置き場の決まりを守る）だけで、計 398 件。アダプタの出力は変わらない（golden 101/101）。

### コミット
| # | 内容 |
|---|---|
| 1 `6762917` | `tests/support/`（paths・tools・arch_*・ir）を作り、architecture／golden／validate／core／icons／host／integration の小さいテスト 12 ファイルを移す |
| 2 `4b271b9` | tf_adapter・tf_plan・cfn_adapter の 3 ファイルを unit/ と integration/ に分け、共有の道具を support/ に出す |
| 3 `9bdc4a4` | `test_test_layout.py`（7 件）、文書・コメントのテストのパスを新しい場所に直す、architecture.md の 7 |
| 4 | HANDOFF・WORKLOG（この節）・PLAN の状態 |

### 旧ファイル → 新ファイル（件数は静的に数えたテストの数。合計 391 + 新規 7 = 398）
| 元（行数・件数） | 先 | 件数 | 行数 | クラス |
|---|---|---|---|---|
| `tests/test_tf_adapter.py`（2465 行・78 件） | `tests/unit/terraform/test_references.py` | 4 | 143 | PseudoTest・ReferenceTest |
|  | `tests/unit/terraform/test_expressions.py` | 10 | 343 | ExpressionTest・ValueTest |
|  | `tests/unit/terraform/test_evaluator.py` | 3 | 89 | EvaluatorTest |
|  | `tests/unit/terraform/test_instances.py` | 6 | 250 | CountAndModuleTest・InstanceTest |
|  | `tests/unit/terraform/test_modules.py` | 10 | 400 | ModuleTest |
|  | `tests/unit/terraform/test_module_summaries.py` | 16 | 565 | SummaryTableFileTest・SummaryTest |
|  | `tests/unit/terraform/test_providers.py` | 2 | 86 | ProviderTest |
|  | `tests/unit/terraform/test_module_vars.py` | 4 | 141 | VariableTest |
|  | `tests/unit/terraform/test_hcl.py` | 11 | 199 | BlockKindTest・RobustnessTest |
|  | `tests/unit/terraform/test_review_fixes.py` | 7 | 182 | ReviewFixTest |
|  | `tests/integration/terraform/test_expected_ir.py` | 5 | 207 | ExpectedIrTest・FixtureTest |
| `tests/test_tf_plan.py`（1227 行・61 件） | `tests/unit/terraform/plan/test_addresses.py` | 3 | 72 | AddressAndCollapseTest |
|  | `tests/unit/terraform/plan/test_masking.py` | 21 | 473 | CombinedSensitiveTest・SensitiveEdgeCasesTest・SensitivePlanOnlyTest |
|  | `tests/unit/terraform/plan/test_plan_diagnostics.py` | 9 | 177 | PlanDiagnosticsTest |
|  | `tests/unit/terraform/plan/test_hostile.py` | 12 | 194 | HostilePlanTest・PlanPerformanceTest |
|  | `tests/integration/terraform/test_plan_fixtures.py` | 16 | 323 | CliTest・EdgeCaseTest・PlanFixtureTest |
| `tests/test_cfn_adapter.py`（1131 行・50 件） | `tests/unit/cloudformation/test_intrinsics.py` | 8 | 186 | IntrinsicTest・ShortTagTest・SplitConcatTest |
|  | `tests/unit/cloudformation/test_robustness.py` | 5 | 94 | RobustnessTest |
|  | `tests/unit/cloudformation/test_nested_stacks.py` | 6 | 194 | NestedStackTest |
|  | `tests/unit/cloudformation/test_sam.py` | 3 | 91 | SamTest |
|  | `tests/unit/cloudformation/test_cdk_out.py` | 3 | 121 | CdkOutTest |
|  | `tests/unit/cloudformation/test_evaluation.py` | 15 | 331 | EvaluationReviewTest・EvaluationTest |
|  | `tests/integration/cloudformation/test_cfn_lint_graph.py` | 8 | 125 | CfnLintGraphTest |
|  | `tests/integration/cloudformation/test_expected_ir.py` | 2 | 74 | ExpectedIrTest・FixtureTest |
| `tests/test_architecture.py`（1124 行・54 件） | `tests/architecture/test_dependency_direction.py` | 19 | 237 | DependencyDirectionTest |
|  | `tests/architecture/test_adapter_order.py` | 15 | 237 | CloudFormationOrderTest・TerraformOrderTest |
|  | `tests/architecture/test_diagnostics_registry.py` | 12 | 193 | DiagnosticRegistryRuleTest |
|  | `tests/architecture/test_file_size.py` | 8 | 95 | FileSizeTest |
| `tests/test_diagnostics.py`（265 行・13 件） | `tests/architecture/test_diagnostics.py` | 13 | 268 | DiagnosticCodesTest・EmittedLevelsTest・RegistryShapeTest |
| `tests/test_doctor_required_files.py`（158 行・6 件） | `tests/architecture/test_doctor_required_files.py` | 6 | 159 | RequiredFilesTest |
| `tests/test_golden.py`（157 行・12 件） | `tests/golden/test_golden.py` | 12 | 160 | GoldenOutputsTest・GoldenToolTest |
| `tests/test_paths.py`（216 行・16 件） | `tests/unit/core/test_paths.py` | 16 | 215 | PathsTest・SummaryDirectoryTest |
| `tests/test_validate_ir.py`（145 行・19 件） | `tests/unit/validate/test_validate_ir.py` | 19 | 141 | BrokenTest・ExpectedTest |
| `tests/test_ir_schema_v1.py`（289 行・22 件） | `tests/unit/validate/test_ir_schema_v1.py` | 22 | 286 | NormalizedV1Test・RawSchemaTest・RawSemanticTest |
| `tests/test_check_icons.py`（206 行・24 件） | `tests/unit/icons/test_check_icons.py` | 24 | 212 | ClassifyTest・GeometryTest・GroupDiffTest・LayoutTest・StencilTest |
| `tests/test_broken_merge.py`（105 行・7 件） | `tests/unit/icons/test_broken_merge.py` | 7 | 108 | FindTest・MergeTest |
| `tests/test_drawio_cli.py`（54 行・8 件） | `tests/unit/host/test_drawio_cli.py` | 8 | 62 | DrawioCommandTest・NeedsXvfbTest |
| `tests/test_cli_paths.py`（132 行・9 件） | `tests/integration/test_cli_paths.py` | 9 | 133 | JapanesePathTest |
| `tests/test_tf_public.py`（187 行・12 件） | `tests/integration/terraform/test_public_samples.py` | 12 | 186 | PairTest・PublicFoldersTest |
| （新規） | `tests/architecture/test_test_layout.py` | 7 | 171 | TestLayoutTest |

`tests/` の下の `.py` は最大 565 行（`unit/terraform/test_module_summaries.py`）。800 行を超えるものも、免除も無い。support/ は 11 ファイル（`paths.py` 34 行、`tf_plan.py` 135、`arch_layers.py` 299 など）。

### 共有の道具（`tests/support/`）に出したもの
| 道具 | 元 | 備考 |
|---|---|---|
| `paths.py`（`ROOT`・`SCRIPTS`・`WS`・`TOOLS`・`EXPECTED`・`FIXTURES_TF`・`FIXTURES_CFN`・`PLANS`・`PUBLIC`・`DATA`・`SKILL`・`ARCH_DOC`） | 12 ファイルが書いていた `ROOT = Path(__file__).resolve().parent.parent` 以下 | import すると `scripts/` と `tools/` を `sys.path` の先頭に入れる。`sys.path` をいじるのはここだけ（以前は 14 ファイルが `sys.path.insert` を書いていた） |
| `tools.py`（`load_tool`） | （新規） | `tools/golden.py` を別名 `golden_tool` で読む（下の「決めたこと」） |
| `builders.py`（`refs`・`res_of`・`props`・`assert_valid`） | tf_adapter | cfn_adapter の `refs`・`assert_valid`、tf_plan の `res_of` は AST が同じ（検査した）ので写しをやめた。cfn の `props` は `res_of` を展開した書き方だったが、結果は同じなので tf の `props` に揃えた |
| `terraform.py`（`write_files`・`build`・`codes`・`res`・`NETWORK`） | tf_adapter | |
| `cloudformation.py`（`build`・`BASE`・`write_files`・`ref_by`） | cfn_adapter | |
| `tf_plan.py`（`CASES`・`EDGE`・`EDGE_PLAN`・`combined_raw`・`assert_valid_no_errors`・`rc`・`cfg`・`mkplan`・`TempTestCase` ほか） | tf_plan | tf_plan の `assert_valid` は「error の診断が無い」検査が 1 行多いので、別の名前（`assert_valid_no_errors`）にした。テストのファイルでは `assert_valid_no_errors as assert_valid` で読むので、本文は変わらない |
| `ir.py`（`load`） | validate_ir・ir_schema_v1 | AST が同じ（検査した） |
| `arch_layers.py`・`arch_size.py`・`arch_diagnostics.py` | test_architecture の表と関数 | 検査の「やり方」と許す向きの表。テストのクラスは `architecture/` に残した |

### 決めたこと
| 決めたこと | 理由 |
|---|---|
| クラスは分けない。1 つのクラスは 1 つのファイルに丸ごと移す | 「テストの本文が同じ」を AST の hash で証明できるようにする。大きなクラスも 441 行（`SummaryTest`）で、ファイルは最大 565 行 |
| `unit/` は領域ごと、`integration/` は「コミットした fixture・公開サンプル・正解 IR が主役」か「入口のスクリプトを動かす」もの | PLAN の 1.4。`ExpectedIrTest`・`FixtureTest`（TF・CFN）、`CfnLintGraphTest`、`PlanFixtureTest`・`EdgeCaseTest`・`CliTest`、`PublicFoldersTest`・`PairTest`、`JapanesePathTest` が `integration/`。主役が混ざるクラス（`SummaryTest` は公開サンプルと突き合わせる 4 件を含む、`EvaluationTest` は fixture を使う）は割合の多い方 |
| フォルダの名前は標準ライブラリ・`scripts/`・`tools/` の最上位の名前にしない。`platform` 層の単体テストは `unit/host/`（`tests/unit/platform/` にしない） | `discover -s tests` は `tests/` を、`python tests/…/test_x.py` はそのファイルのフォルダを `sys.path` の先頭に入れる。そこに `platform/` や `doctor/` の（`__init__.py` つきの）フォルダがあると `import platform`・`import doctor` を隠す。`-s tests/unit` と指定した場合も同じ。`test_test_layout.py` が、標準ライブラリ（`sys.stdlib_module_names`）と `scripts/`・`tools/` の名前との重なりを失敗にする |
| 例外は `tests/golden/`。`tools/golden.py` は `support.tools.load_tool("golden", alias="golden_tool")` で別名で読む | `golden/` は PLAN の置き場の名前。`import golden` と書くと `discover -s tests` では最上位の `golden`（テストのパッケージ）を読んでしまう。`import golden` を書くとテストが失敗にする。`golden.py` の中身は変えず、`mock.patch.object(golden, …)` の本文も同じ |
| `tools/` を `sys.path` に入れるのは `support/paths.py` だけ。すべてのテストで `scripts/` と `tools/` の両方が入る | 以前は tf_adapter・tf_public・golden だけが `tools/` を入れた。`tools/` に `golden.py`・`c1_check.py` などがあるが、テストが `import` する名前（`tf_public_check`）と重ならず、`golden` は上の別名で避けた |
| 各テストのファイルの先頭に、`tests/` を `sys.path` に入れる同じ 2 行を書く（`test_test_layout.py` が全ファイルで確かめる） | `python tests/…/test_x.py` と `python -m unittest tests.…`（`tests/` が最上位にならない）で `from support… import` が通るため。`discover -s tests` では要らないが害は無い |
| `support` の道具を使わず `import support` だけのファイル（4 ファイル）は `support.ensure_paths()` を呼ぶ | pyflakes は `# noqa` を見ないので、使っていない import にならないようにした |
| `tests/__init__.py` と各フォルダの `__init__.py` を置いた。`test_test_layout.py` が置き忘れを失敗にする | `unittest discover` は `__init__.py` の無いフォルダを見ない（テストが黙って走らない）ので、これが一番怖い |
| `test_architecture.py` は検査の「やり方」（表と関数）を `support/arch_*.py` に、テストのクラスを `architecture/` の 4 ファイルに分けた。`test_diagnostics.py`・`test_doctor_required_files.py` は `architecture/` | PLAN の「依存の向き・行数・診断コードの一覧の検査」。`test_paths.py` は `unit/core/`（定数の検査と要約表のフォルダの読み込みで、構成の決まりではない） |
| 旧 `test_tf_public.py` は `integration/terraform/test_public_samples.py` に改名した | 公開サンプルの確認（`tf_public_check.py`）を通すので。クラス名は同じ |
| 新しいテスト 7 件（`TestLayoutTest`）は、置き場の決まりの検査と、わざと崩した入力で失敗することの確認 | 分けたことで起きやすい失敗（見つからない、名前が隠す、道具が写される）を防ぐ |

### 同一性の証明（テストを弱めていない）
道具は WORKLOG に載せない一時のスクリプト（`ast` で `tests/` を読む）。移す前の `cc58446` の 15 ファイルと、各コミットの後の `tests/` を同じ方法で数えて比べた。
- **テストの数・本文**: 391 件。（クラス名、メソッド名、`self.assert*` の呼び出しの数、`subTest` の数、`mock.patch` の対象、デコレータ、**メソッド全体の AST の hash**）の組の多重集合が、移す前と**完全に同じ**（足りない 0、余り 0）。`self.assert*` の呼び出し 1,400、`subTest` 40 も同じ。
- **クラス**: クラス名、基底クラス、クラスのデコレータ、クラス直下の代入の hash、`setUp`・`tearDown` などテストでないメソッドの hash が、移す前の全クラス（`TempTestCase`・`CodeSite`・`_DropTypeChecking` を含む）と同じ。
- **モジュール直下の関数・定数**: 移す前の（名前, hash）がすべて、新しい `tests/` にある。違うのは次の説明のつくものだけ: 場所の定数（`ROOT`・`SCRIPTS`・`WS`・`SKILL`・`DATA`・`EXPECTED`・`FIXTURES`）は `support/paths.py` の式になった、tf_plan の `assert_valid` は `assert_valid_no_errors`、cfn の `props` は tf の `props` に統合。
- **`unittest` の発見**: `discover -s tests` が見つけた id 391 件が、すべて異なり、（クラス, メソッド）の多重集合が移す前と同じ。足した 7 件を除くと 398 − 7 = 391。
- 各テストのファイルに `if __name__ == "__main__": unittest.main()` が 1 つ。`@unittest.skip`・`expectedFailure` は無い（`-v` の出力に skipped 0）。
- 各コミットの後も同じ表で確かめた（1/4 の後と 2/4 の後は 391、3/4 の後は 398）。

### 確かめたこと
- **単体テスト 398 件**が、Windows の通常の TEMP（約 90〜96 秒。移す前の同じ環境の 391 件は約 90 秒）、別のドライブの TEMP（`subst Y:`。93 秒）、8.3 の短い名前の TEMP（`...\Temp\R5-LON~1`。91 秒）のそれぞれで OK。CI と同じ `uv sync --locked` → `uv run python -m unittest discover -s tests -v` も OK（398 件、skipped 0）。`python -m unittest discover tests` と `python -m unittest discover`（引数なし）も 398 件 OK。
- **起動のしかた**: 1 件（`python -m unittest tests.unit.terraform.test_hcl.RobustnessTest.test_crlf`）、1 ファイル（`python -m unittest tests.unit.validate.test_ir_schema_v1`）、領域（`discover -s tests/unit/host -t tests`、`-t` なしでも）、直接（`python tests/unit/terraform/test_hcl.py`、`tests/golden/test_golden.py`、別の作業フォルダから `…/tests/unit/icons/test_broken_merge.py`）がすべて通る。
- **golden** 101/101（Windows と WSL）。`uv lock --check` OK（66 パッケージ）。
- **WSL（Ubuntu、`git archive 9bdc4a4` を `/tmp` に展開、`uv sync --locked`）**: `uv run python -m unittest discover -s tests -v` 398 件 OK（約 49 秒）、golden OK。
- **pyflakes**（`uv run --with pyflakes python -m pyflakes tests`）: `unit/terraform/plan/test_masking.py:69` の `pw`（未使用の変数。移す前の `test_tf_plan.py:524` と同じもの）の 1 件だけ。移す前にあった `test_tf_adapter.py:924` の「`v` が for 文の変数に隠される」は、`SummaryTest` が入るファイルが `validate_ir as v` を import しなくなった（`v` はそのクラスの中のループ変数だった）ので消えた。新しい警告は 0。
- **処理時間**: 移す前 89.6 秒・90.6 秒（2 回）、移した後 90.7 秒・95.6 秒（2 回。398 件）。差は +1〜5%（上限の +10% 以内。2 回目は同じ環境でも揺れる）。
- **変異（本番のコードを 1 か所だけ壊して、全体を移す前と移した後で動かした。壊れるテストの名前の集合を比べた）**: 14 通りのうち 13 通りが 1 件以上のテストを落とし、**落ちたテストの（クラス, メソッド）の集合は 14 通りすべてで移す前と同じ**（移した後は `TestLayoutTest` を除く）。コントロール（変異なし）は両方 0 件。移した後の側は `4b271b9`（2/4）の `git archive` で、移す前は `cc58446`（短いパスに展開）。

| 変異 | 落ちたテスト（移す前＝移した後） |
|---|---|
| M01 `plan/masking.py` の `mask_props`: すべて sensitive のとき `True` → `False` | 1 件: `SensitiveEdgeCasesTest.test_root_after_sensitive_true` |
| M02 `plan/masking.py` の `literal_only`: `tv == pv` の比較を外す | **0 件（生き残った）**。現在のテストでは見つからない変異（移す前も同じ）。今回の範囲外 |
| M03 `hcl.py`: `HEREDOC` から `heredoc_template_trim` を外す | 3 件: `ExpressionTest.test_locals_templates_and_for`、`ValueTest.test_jsonencode_and_heredoc_json`、`GoldenOutputsTest.test_all_outputs_are_byte_identical_to_the_manifest` |
| M04 `cloudformation/conditions.py`: `Fn::Or` と `Fn::And` の入れ替え | 1 件: `EvaluationTest.test_logic_and_pseudo` |
| M05 `doctor.py`: `REQUIRED_FILES` から `data/icons/catalog.json` を消す | 1 件: `RequiredFilesTest.test_list_equals_the_runtime_files_on_disk` |
| M06 `core/paths.py`: `IR_RAW_SCHEMA` のファイル名を変える | 112 件（スキーマを読むテストのほぼすべて） |
| M07 `core/paths.py`: `parents[3]` → `[2]`（SKILL の場所） | 157 件 |
| M08 `core/ir_raw.py`: 重なった address の検査を反転 | 113 件 |
| M09 `tools/golden.py`: sha256 の比較を反転 | 3 件: `GoldenOutputsTest.test_all_outputs_are_byte_identical_to_the_manifest`、`GoldenToolTest.test_baseline_has_no_problems`、`test_changed_hash_is_reported` |
| M10 `core/ir_raw.py` が `platform` 層を import | 5 件（`DependencyDirectionTest` 4、`CloudFormationOrderTest` 1） |
| M11 `cloudformation/conditions.py` の診断コードを一覧に無い綴りに | 8 件（`DiagnosticRegistryRuleTest` 7、`EmittedLevelsTest` 1） |
| M12 `cloudformation/intrinsics.py`: `Fn::Join` の区切りの入る位置 | 4 件（`IntrinsicTest`、`NestedStackTest` 2、`GoldenOutputsTest`） |
| M13 `terraform/evaluator/functions.py`: `lower` → `upper` | 1 件: `GoldenOutputsTest.test_all_outputs_are_byte_identical_to_the_manifest`（単体テストは見つけない。golden が拾う） |
| M14 `terraform/module_vars.py`: 変数の出どころの名前の入れ替え | 4 件（`EdgeCaseTest` 2、`PlanFixtureTest`、`GoldenOutputsTest`） |

### 残したこと・リスク
- **R6**: SKILL.md・references・`docs/spec/`・architecture.md の「R〜」の印を消す。PLAN の構成図の `tests/` は今回の形のまま（`support/` が足されている）。
- 分け方はクラス単位で、`unit/` と `integration/` の境目はクラスの主役で決めたもの。主役が混ざるクラスがある（上の「決めたこと」）。テストの本文を変えない方針を優先した。
- 各テストのファイルの先頭の 2 行（`sys.path` の設定）は 40 ファイルに写されている。直接実行と `python -m unittest tests.…` を通すために必要で、`test_test_layout.py` が同じであることを確かめる。
- `tests/` が最上位の名前として `unit`・`integration`・`golden`・`architecture`・`support` を `sys.path` に持ち込む。同じ名前の pip のパッケージが将来入ると隠し合う（今の依存には無い）。`golden` だけは `tools/golden.py` と重なるので別名で読んでいる。
- 同一性の証明は AST の比較（本文が同じ）と全体の実行で、import の解決の食い違いは全体の実行で確かめている。変異は 14 通りで、網羅ではない。M02 のように現在のテストが拾わない変異がある。
- 変異の比較は（クラス名, メソッド名）で行った。名前が同じクラスが 2 つのファイルにある（`RobustnessTest`・`ExpectedIrTest`・`FixtureTest`）ので、片方が落ちてもう片方が落ちないという差は見分けられない（落ちた件数の合計は一致した）。
- Windows で長いパスに `git archive` を展開すると、公開サンプルの深いパスのファイルが欠けて `tf_public_check` 系のテストが落ちる（`tests/` の構成とは無関係。変異の比較では、短いパス `%TEMP%\r5` に展開して避けた）。リポジトリを深い場所に clone する人は MAX_PATH に注意。
- CI（GitHub Actions）は実行していない（push していない）。

### レビューの指摘への対応（R5 の第三者レビュー: APPROVE WITH CHANGES。1 つのコミットで直した）
単体テストは 398 → 412 件（新規 14: `DocumentedPathsTest` 3、`LiteralOnlyTest` 2、`SelfLoopTest` 1、`GoldenAbsolutePathTest` 1、`ConditionLogicTest` 5、`CidrSubnetBoundaryTest` 2）。移す前の 391 件の本文は変えていない（同じ AST の表で、足りない 0・変わったもの 0）。アダプタの出力は変わらない（golden 101/101）。
1. **MINOR-1（フォルダの名前が隠すもの）。** `test_test_layout.py` の検査に、インストール済みのパッケージ（`importlib.metadata.packages_distributions()` の最上位の名前。環境に無くても隠してはいけない `yaml`・`jsonschema`・`hcl2`・`PIL`・`lark`・`cfnlint`・`defusedxml`・`moto` を下限に足した）を足した。対象はフォルダの名前に加えて、フォルダの直下のテストでない `.py`（`unit/core/json.py` のような補助のファイル。`__init__.py` を除く）。一時フォルダの複製に `unit/yaml/`・`unit/core/json.py`・`unit/core/hcl2.py` を置くと失敗することを `test_mutations_are_found` が確かめる（本物のツリーに置いても失敗することも手で確かめた）。docs/architecture.md の 7 に決まりを書いた。
2. **MINOR-2/3（古いパス）。** `docs/spec/module-summaries.md` の `tests/test_paths.py` と PLAN の R1 の段落の `tests/test_architecture.py` を直した（`docs/dev-notes/` 以外の `tests/test_` は 0）。`architecture/test_documented_paths.py`（3 件）が、README・PLAN・docs（`dev-notes/` を除く）・ir-schema.md・ci.yml・fixtures/README.md・`scripts/` と `tools/` の `.py` に書いた `tests/….py|json` のパスの実在を確かめる（古いパスを戻すと失敗することを確かめた）。
3. **移す前も生き残っていた変異を殺すテスト。** 次の変異は、移す前と移した後の既存のテストのどちらでも見つからなかった（全体 398 件が OK）。新しいテストは、それぞれの変異で失敗し、変異なしでは通る（`git archive` の複製に変異を入れて確かめた）。

| 変異 | 既存の 398 件 | 新しいテスト（変異で落ちたもの） |
|---|---|---|
| A1 `plan/masking.py` の `literal_only`: 値の比較（`tv == pv`）を外す（M02） | 生き残る | `LiteralOnlyTest`（2 件。count 0 のリソースで .tf のリテラルが plan の constant と違えば残さない、同じなら残す） |
| A2 同: 型の比較を外す（`1` と `True` は `==`） | 生き残る | `LiteralOnlyTest.test_literal_that_differs_from_the_plan_constant_is_not_kept` |
| B `validate_ir.py`: 自己ループの検査を `if False:` に（M18） | 生き残る | `SelfLoopTest`（自己参照の辺の IR が「自己ループ」で落ちる） |
| C `golden.py`: `compare` の絶対パスの検査を `if False:` に（M27） | 生き残る | `GoldenAbsolutePathTest`（hash が一致していても `ABSPATH` を返す） |
| D2 `cloudformation/conditions.py` の `stronger`: 決まらない（None）を false に | 生き残る | `ConditionLogicTest`（`stronger` の真理値表、SAM の暗黙の API の enabled） |
| E1 `cidrsubnet`: netnum の上限が 1 ずれる（`<=`）（M07） | 生き残る | `CidrSubnetBoundaryTest.test_netnum_range_…` |
| E2 同: 下限が無い | 生き残る | 同上（netnum = -1） |
| E3 同: `/32` の上限が 1 ずれる | 生き残る | `CidrSubnetBoundaryTest.test_newbits_limit` |
| E4 同: 負の newbits を許す | 生き残る | 同上 |

- M27 が生き残った理由: 既存の `test_absolute_paths_are_detected` は検出関数 `absolute_path_hits` だけを見て、実際の出力は絶対パスが無い（`abs_paths` が空）ので、`compare` がその結果を使っているかは誰も確かめていなかった。
- M10（レビューの番号。Conditions の And／Or）: 本物の生き残りは `stronger`／`weaker`（`enabled` の合わせ方）の決まらない値の扱いだった。`cond_eval` の And／Or の変異（D1「決まらないものを決まったことにする」、D3 `weaker` の None → True、D4 「最初の被演算子で止める」）は、既存の `test_logic_and_pseudo`・golden・`IntrinsicTest`・`NestedStackTest` が見つけていた（確認した）ので、`ConditionLogicTest` は And／Or の3つ以上の被演算子・全部が決まる場合も足した。D1・D3・D4 でも新しいテストは落ちる。
- 同値な変異は無かった（A1〜E4 はすべて新しいテストが落とせた）。
- 新しいテストは、元のテストの本文を変えずに、同じ領域のファイルの末尾に新しいクラスとして足した（`test_masking.py`・`test_validate_ir.py`・`test_golden.py`・`test_evaluator.py`）か、新しいファイルにした（`unit/cloudformation/test_conditions.py`・`architecture/test_documented_paths.py`）。
- **確かめたこと（レビュー対応）**: 単体テスト 412 件が Windows の通常の TEMP と別のドライブの TEMP（`subst Y:`）で OK、`uv run python -m unittest discover -s tests -v` も OK。WSL（`git archive` のツリー）でも OK。golden 101/101、`uv lock --check` OK、pyflakes は既存の 1 件（`pw`）だけ。

## 2026-10-26 フェーズ2b の R6: SKILL.md・references・`docs/spec/`・architecture.md・PLAN の構成図

### 概要
構成の階層化（PLAN の 1.4）の最後の手順。**文書と置き場だけを直し、動きは変えていない**（golden 101/101、アダプタの出力はバイト単位で同じ）。やったこと: ① 開発者向けの仕様 `ir-schema.md`（387 行）を SKILL の `references/` から SKILL の外の `docs/spec/ir-schema/` に移し、章ごとの 9 ファイルと目次に分けた、② `SKILL.md` を入口だけの文書に直した（今の実物と食い違わないことをテストで守る）、③ `references/` を、`validate_ir.py` が実行時に読む規則表 3 つ（フェーズ 3 で `data/rules/` へ）と README だけにした、④ `docs/architecture.md` から「R2〜R6」の印と未来形を消し、今の構成に書き直した、⑤ PLAN の「リポジトリ構成（予定）」を実際の木に置き換え、フェーズ 2b を完了にした、⑥ README を直した、⑦ Markdown の相対リンクと文書に書いた `docs/…` のパスの実在、SKILL.md の内容を、テストで守るようにした。

### コミット
| # | 内容 |
|---|---|
| 1 `bcfe81f` | `references/ir-schema.md` → `docs/spec/ir-schema/07-raw-output.md` を `git mv`（中身は同じ。履歴が追えるよう、分割の前に 100% の名前変更だけを 1 つのコミットにした）。ir-schema を読む 2 つのテストの場所を直す |
| 2 `aa0cd8b` | ir-schema を章ごとに分け（7 章は 1 のファイルに残し、ほかの章を新しいファイルに出した）、コード・テスト・仕様の「`references/ir-schema.md`」を新しい場所に直す |
| 3 `632fcc8` | SKILL.md・`references/README.md`・architecture.md・README・PLAN と、新しいテスト 2 つ（リンク・SKILL.md） |
| 4 | HANDOFF・WORKLOG（この節）の状態 |

（1 のコミットメッセージの「(1/5)」は、途中で 4 つに数え直したときの直し忘れ。内容に影響しない。）

### 何がどこへ移ったか（旧 → 新）
| 旧 | 新 | 行数 |
|---|---|---|
| `skills/aws-iac-diagram/references/ir-schema.md`（前書き、1〜9 章） | `docs/spec/ir-schema/README.md`（前書き＋目次＋番号の決まり）、`01-overview.md`（1 章）、`02-nodes.md`（2）、`03-edges.md`（3）、`04-sources.md`（4）、`05-evaluation-units.md`（5）、`06-output-rules.md`（6）、`07-raw-output.md`（7。7.1〜7.5）、`08-undecided.md`（8）、`09-changes-from-v0.1.md`（9） | 387 → 39・25・70・19・43・22・6・162・7・9 |
| `references/` の中身 | `edge-rules.md`・`relation-resources.md`・`resource-catalog.md`（そのまま）＋ `README.md`（新規） | — |
| `SKILL.md`（34 行。状態、コマンドの書き方、環境の確認、環境ごとの違い、変数の注意） | `SKILL.md`（63 行。状態の節で動く 5 つの入口とまだ無いものを分け、「動くスクリプト」と「参照できるもの」を足した） | 34 → 63 |

章の見出し・節の見出し・本文は 1 文字も変えていない（分ける前の文書と、章のファイルを連結したものを、リンクの書き換え以外は同一であることを差分で確かめた）。リンクだけを、新しい場所からの相対パスに直した（`../data/schemas/…` → `../../../skills/aws-iac-diagram/data/schemas/…`、規則表へのリンクも同様）。

### 決めたこと
- **章・節の番号は変わらない識別子。** コード・テスト・診断の説明は「ir-schema の 7.2」「7.5」「2章」のように番号で仕様を指す。そのため章ごとのファイル名は `NN-<名前>.md`（`NN` は章の番号）にし、番号を詰めない・振り直さない・足すなら最後に、を `docs/spec/ir-schema/README.md` に書いた。診断コードの一覧との照合（`tests/architecture/test_diagnostics.py`）は `07-raw-output.md` の `### 7.5 診断` の見出しを探す。
- **文書への参照の書き方。** 「`references/ir-schema.md`」と書いていた所は `docs/spec/ir-schema/` に直した。1 つのファイルに何度も出てくるときは、最初の 1 回だけパス（`docs/spec/ir-schema/ の 7.2`）にし、2 回目以降は「ir-schema の 7.2」のままにした（目次の README が、「ir-schema の 7.2」はこの仕様の 7.2 だと言っている）。
- **出力に入る文字列は触らなかった。** ir-schema への参照が出ていたのは docstring・コメント・スキーマの `description`・テストの文言・規則表の本文だけで、アダプタの診断の `message` には 1 つも無かった（grep で確かめた）。golden は 101/101 のまま。
- **`references/` に README.md を置いた。** doctor の `REQUIRED_FILES` と `test_doctor_required_files.py` は、一覧とディスクの実行時のファイルの等式を比べるが、`references/` の README.md は実行時に読まないので一覧に入れない（等式は崩れない）。代わりに `tests/architecture/test_skill_entry.py` が `references/` の中身を「規則表 3 つ＋README.md」に固定する。
- **SKILL.md は配るものなので、`docs/` へのクリックできるリンクを張らない。** 仕様の場所は「このリポジトリの `docs/spec/ir-schema/`（SKILL だけを取り込んだ環境には無い）」と文字で書いた。SKILL の下の文書の相対リンクが SKILL の外を指さないことをテストで守る。
- **SKILL.md で書いたこと。** 動くのは doctor・adapt_tf・adapt_cfn・validate_ir・find_aws_icon の 5 つだけで、図の出力（`diagram.py`、draw.io・Mermaid・PNG）と、正規化・配置は無い、と先頭の「状態」に書いた。`--out` を持たない `validate_ir.py` と `find_aws_icon.py` は標準出力に書く（これまでの「結果は標準出力ではなく `--out`」は、この 2 つに対して正しくなかったので、例外として書いた）。アダプタの終了コードは diagnostics に warn・error があっても 0 であること、level の意味を、ir-schema の 7.5 から写して書いた。`validate_ir.py --write` は渡したファイルを書き換えるので使わない、と書いた。description に「現在は準備中」を足した。
- **PLAN の木は、実在するものを実在のとおりに書き、無いものだけ「予定」とした**（`render-png.yml`、`diagram.py`、`export_png.py`、`references/workflow/`、`result-json.md`、`data/rules/`、vpc 5.x・eks 20.x の要約表、`normalize/`・`layout/`・`emit/`・`validate/`・`icons/` の中身）。
- **architecture.md の節の番号は変えない。** `adapt_tf.py`・`adapt_cfn.py` の docstring が「docs/architecture.md の 2 と 6」と書いているため。8「気をつけること」を最後に足した。表の行数は実際の行数に直した（R4 で `modules/summaries.py` が 129 → 222 行に増えていたなど、ずれていた）。

### 新しいテスト（412 → 424 件）
- `tests/architecture/test_markdown_links.py`（8 件）と道具 `tests/support/md_links.py`: README・PLAN・`docs/`（`dev-notes/` を除く）・SKILL の下の .md・CRITERIA・fixtures の README（60 文書、リンク 71 本）の、相対リンク（`[文字](パス#見出し)` と参照形式）の先と `#見出し`（GitHub の ID の作り方）が実在する。コードブロックとインラインコードの中、外部の URL は読まない。SKILL の下の文書のリンクが SKILL の外を指さない。文書・コード・テストに文字で書いた `docs/…` のパスが実在する（他のリポジトリの `docs/LEARNINGS_DRAWIO_NATIVE.md` を指す PLAN の 1 か所だけ許可）。検査そのものの試験（壊れたリンク、見出し、コードの中、SKILL の閉じ込め、`docs/` のパス）は一時フォルダで行う。
- `tests/architecture/test_skill_entry.py`（4 件）: SKILL.md の frontmatter が `name` と `description` だけ、90 行以下、書いたスクリプトが実在し `scripts/` の直下の入口がすべて書いてある、`maintenance/` を書かない、コマンドが `uv run "<SKILL>/scripts/…"` の 1 行でシェルの機能を使わない、書いたオプションをどれかの入口が持つ、SKILL の外へのリンクが無い、「準備中」と図の出力がまだ無いことが書いてある、`references/` が規則表 3 つ＋README.md。変異 7 通り（入口の書き忘れ、`>`、無いオプション、保守用、`../docs` のリンク、長さ、frontmatter）が失敗することを、テストの中で確かめる。
- 既存のテスト 2 つを直した: `test_diagnostics.py`（7 章のファイルを読む。7.5 は 7 章の最後の節なので次の `## ` までを節にする）、`test_documented_paths.py`（`docs/` の下の仕様のファイルは `docs/**` の走査に入る）。

### 確かめたこと
- **単体テスト 424 件**（412 + 12）が、Windows の通常の TEMP（約 100〜120 秒。skipped 0）、別のドライブの TEMP（`subst Y:`。96 秒）で OK。WSL（Ubuntu、`git archive` を `/tmp` に展開、`uv sync --locked`）で `uv run python -m unittest discover -s tests -v` が 424 件 OK（52 秒、skipped 0）。golden 101/101（Windows・WSL）。`uv lock --check` OK（66 パッケージ）。
- **README のコマンドを 1 行ずつ実行した**（Windows の PowerShell）: doctor、`uv sync --locked`、`build_icon_catalog.py`（1045 件。`data/icons/` の差分 0）、`find_aws_icon.py`、`adapt_cfn.py`＋`validate_ir.py`、`adapt_tf.py`（`--var-file`、`--plan`、plan JSON だけ）＋`validate_ir.py`、正解 IR の検証、`check_coverage.py --lint`、`c1_check.py`（入力 25・辺 513・対応の無い辺 0）、`tf_public_check.py --pairs` と `--all --jobs 4`（205 フォルダ、error 0）、`check_icons.py`（draw.io 32.4.1。1032 件、壊れ 0、`data/icons/` の差分 0）、テストの 4 通りの起動のしかた（領域、1 ファイル、直接、1 件）、`golden.py`、`golden.py --list`。`winget`・`mklink` だけは実行していない。
- **SKILL.md のコマンドを実行した**: SKILL のフォルダだけを `…\r6doc 日本語 パス\aws-iac-diagram\`（スペースと日本語を含む。リポジトリの `docs/` は無い）にコピーして、`doctor.py`（終了 0、`missing_files` 0、draw.io と mmdc があるので `ok`）、`adapt_tf.py`（`--var-file env\dev.tfvars`）→`validate_ir.py`、`adapt_cfn.py`（`--param EnvType=prod`）→`validate_ir.py`、`find_aws_icon.py` がすべて終了 0。`skills/` の下に `../docs` のリンクも、`docs/` を開くコードも無いことを grep で確かめた（`docs/` が出てくるのは、コメントと文字のパスだけ）。
- **リンクの検査**: `test_markdown_links.py` の本物の検査（60 文書、リンク 71 本）に加えて、`docs/…` のパスを 202 ファイル（文書、`ci.yml`、`scripts/`・`tools/`・`tests/` の `.py`）で走査し、実在しないものは他のリポジトリを指す PLAN の 1 か所だけ。
- **変異（文書を壊すと落ちること）**: ir-schema 7.5 の `TF-PARSE-ERROR` の綴りを変える、`TF-PARSE-ERROR` の level を error→warn に変える、「43 個」を「44 個」に変える → `test_diagnostics.py` が落ちる。README の `07-raw-output.md` へのリンク、README の `#nope` の見出し、`docs/architecture.md` の `docs/spec/ir-schema/07-raw-output.md`、ir-schema の README の目次のリンク、`references/README.md` のリンクを 1 文字変える → `test_markdown_links.py` が落ちる。`docs/architecture.md` の `tests/architecture/test_markdown_links.py` を 1 文字変える → `test_documented_paths.py` が落ちる。SKILL.md のスクリプト名・オプション・`docs/` へのリンクを変える → `test_skill_entry.py` が落ちる。**生き残った変異**: ir-schema の見出し `### 7.5 診断` を `### 7.5 診断書` に変える（照合は見出しの接頭辞 `### 7.5 診断` で探すので）。見出しの語を変える変更は、7.5 の中身と一覧の食い違いを生まないので許した。
- **pyflakes** は、触った Python（28 ファイル）で 0 件。
- 動きの確認: R6 でコードの実行される部分は変えていない（変えたのは docstring・コメント・スキーマの `description`・テストの文言だけ）。golden 101/101 と、既存の 412 件が変わらず通ることが証拠。

### 残したこと・リスク
- コードのコメントの多くは、2 回目以降の参照を「ir-schema の 7.2」のままにしてある（パスは最初の 1 回だけ）。`docs/spec/ir-schema/README.md` が説明している。
- `references/` の 3 つの規則表は、フェーズ 3 で `data/rules/` に移すまで SKILL の中の文書（本文は「正規化の草案」）。その説明（規則表を読むための `docs/spec/` の文書）は、フェーズ 3 で作る。
- SKILL.md の「環境が複数あるときはユーザーに確かめる」は PLAN の A4 の方針を書いたもので、スクリプトが検出する機能ではない（アダプタは `evaluation` に使った値を書くだけ）。`GITHUB_ACTIONS` が `true` のときの扱い（確認しない）との関係は、フェーズ 6 の SKILL.md の仕上げで決める。
- リンクの検査は GitHub の見出しの ID の作り方に近い実装で、完全ではない（`<a name>` のアンカー、HTML は見ない）。いまの文書にはアンカー付きのリンクが少ない。
- CI（GitHub Actions）は実行していない（push していない）。

## フェーズ2b のまとめ（R1〜R6、2026-10-24 の合意から 2026-10-26）

### 前と後
```
前（6587691。フェーズ 2 の完了）                           後（R6 の後）
skills/aws-iac-diagram/                                    skills/aws-iac-diagram/
├── SKILL.md                                               ├── SKILL.md                入口だけ（63 行）
├── references/ 7 文書 + icons/                            ├── references/             規則表 3 つ + README（validate_ir.py が読む）
│   ir-schema.md(387)  module-summaries.md(4,826)          ├── data/                   schemas/ icons/ module-summaries/<モジュール>/v<major>.md
│   ir*.schema.json  規則表 3 つ  icons/                   ├── assets/
├── assets/                                                └── scripts/
└── scripts/                                                   入口 5（doctor・validate_ir・find_aws_icon・adapt_tf・adapt_cfn）
    入口 + build_icon_catalog・check_icons                     maintenance/（辞書の保守 2 + sidebar_harness.js）
    lib/ 6 ファイル                                            aws_iac_diagram/ 層（core・adapters/{terraform,cloudformation}・platform と空の層）
    adapters/tf.py(2,613) cfn.py(1,327)                    docs/spec/ir-schema/ 9 章 + README、docs/spec/module-summaries.md
.py 12 ファイル、最大 2,613 行                             docs/architecture.md
tests/ 平ら 10 ファイル、最大 2,381 行（281 件）            tests/ unit/ integration/ golden/ architecture/ support/（.py 70 ファイル、最大 565 行。424 件）
```
- 数字: `scripts/` の `.py` 12 → 67 ファイル（`__init__.py` 14 を含む）、最大 2,613 → 763 行（`evaluator/functions.py`）、1,500 行を超えるファイル 2 → 0、免除 0。`tests/` の `.py` 10 → 70 ファイル、最大 2,381 → 565 行。単体テスト 281 → 424 件。診断コードの一覧 62 個（TF 43・CFN 19）を 1 つの表に。golden 101 ケース（Windows・Linux で同じ SHA-256）。出力が変わったのは R4 の 14 ケース（要約表のパスを含む診断の文言）だけ。
- 守る決まり（テスト）: 依存の向きと循環、アダプタの中の順序、動的 import の禁止、行数、診断コードの一覧と ir-schema の 7.5、doctor の必須ファイルとディスクの等式、テストの置き場と名前、文書のテストのパス、SKILL.md の内容、Markdown の相対リンクと `docs/` のパス。

### 第三者レビューが見つけたこと（R1〜R5。R6 はこれから）
1. **黙って劣化する欠け（R1 の MAJOR、R4 の MINOR）**: 要約表の 1 ファイルが無いと、終了コード 0 のまま three-tier-modules が 42 → 13 リソースになり、doctor も ok だった。doctor の必須ファイル、`TF-MODULE-SUMMARY-TABLE-MISSING`、`KNOWN_MODULES`、`summaries.problems()` で「大きな声で失敗」に変えた。**ファイルの位置に依る相対パスは、移動のたびに golden で確かめる**（`SUMMARY_FILE` の深さで実際に起きた）。
2. **構成のテストの抜け穴（R1）**: `platform` 層が標準ライブラリを隠す、入口どうしの import、`importlib`・`exec`。後の R5 で同じ型の穴（テストのフォルダ・補助のファイルの名前が標準ライブラリやインストール済みのパッケージを隠す）が見つかり、同じ検査を広げた。
3. **配布物の表示が分割で消える（R4 の MAJOR）**: Apache-2.0 の出典表示が `module-summaries.md` の先頭にしか無く、分割したデータのファイルから消えた。全ファイルの先頭と `NOTICE.md` に戻し、`NOTICE.md` は doctor の一覧に入れた。**ファイルを分けるときは、ライセンス表示と読み込みの前提（ヘッダ）も複製する。**
4. **動きの同一性は大量の比較で確かめた**: R2 は約 110 万回、R3 は約 6,400 ケースで旧コードと差 0。R3 のレビューは、診断コードの一覧の限界（best-effort）の明記と level の照合を TF にも広げた。
5. **テストの強さ（R5）**: 移す前から生き残っていた変異（自己ループの検査、`literal_only` の比較、golden の絶対パス、Conditions の `stronger`、`cidrsubnet` の境目）を殺すテストが無かった。移した後も落ちるテストの集合が同じであることを変異 14 通りで確かめ、生き残りには新しいテスト 14 件（同じ変異を殺す 11 件と、文書のパスの実在 3 件）を足した。
6. **文書の古い参照（R2・R5）**: 移したあと、`tf_modules.py` や `tests/test_*.py` などの旧いパスが文書に残った。R5 で「文書に書いたテストのパスの実在」をテストにし、R6 で Markdown の相対リンクと `docs/` のパスにも広げた。
7. 共通する型: 「動かしたあとに壊れるのは、相対パスと文書の参照と、黙って通る欠け」。どれも最後は、壊したら落ちるテストにして固定した。


## 2026-10-26 vpc 5.x・eks 20.x の要約表

ユーザーの 2026-10-24 の決定（vpc 5.x・eks 20.x の要約表を作る。そのタグのソースの取り込みも許可）による。ブランチ `summaries-vpc5-eks20`（main の `0652deb` から。ローカル。push はまだ）。「残りの作業の順番」の 5。

### 概要
- T16（`learn-terraform-provision-eks-cluster`）が vpc `5.8.1`・eks `20.8.5` を固定し、T18 の `environment` が vpc `~> 5.0` を呼ぶので、`data/module-summaries/terraform-aws-vpc/v5.md` と `terraform-aws-eks/v20.md` を足した。**ローダー（`summaries.py`）と版の選び方（`resolve.choose`）のコードは変えていない**（表のデータが増えただけで、5.x の制約は 5、20.x は 20 が選ばれる）。R4〜R6 の「ファイルを足すだけで入る」の確認になった。
- **T18 の eks は `~> 19.15.2`**（vpc だけが 5.x）。19.x の表は作らない（ユーザーの決定は 20.x まで）ので、T18 の `eks-blue`・`eks-green` の `module.eks_cluster.module.eks` は黒箱のまま（`it has 20.x, 21.x` と理由に書く）。「T16・T18 の vpc・eks の黒箱が無くなる」は、T16 の 2 つと T18 `environment` の vpc で成り立ち、T18 の eks だけは当てはまらない。

### コミット
| | コミット | 内容 |
|---|---|---|
| 1/4 | `a4a71a6` | 照合用のソースの取り込み（310 ファイル、2.44 MB）と SOURCES.md |
| 2/4 | `19722ab` | `v5.md`・`v20.md`、doctor の一覧、NOTICE.md、テスト 8 件、`docs/spec/module-summaries.md` |
| 3/4 | `b34a3eb` | golden の固定値を 5 ケース更新（証明はこの節の「golden の更新」） |
| 4/4 | この節を含むコミット | README・PLAN・HANDOFF・WORKLOG と、数字（205 → 248 フォルダ）の更新 |

### 取り込んだソース（SOURCES.md の M03〜M05）
取得方法は M01・M02 と同じ（`git ls-remote --tags` → `git clone --depth 1 --branch <タグ>` を一時フォルダに → `.git` を削除 → 画像だけ除く）。取得元は terraform-aws-modules の vpc・eks の 2 リポジトリだけ。タグは軽量タグなので、コミットはタグが指すコミット。

| ID | ディレクトリ | タグ | コミット | タグのコミット日 | ファイル数・大きさ |
|---|---|---|---|---|---|
| M03 | `terraform-aws-vpc-v5.8.1/` | v5.8.1（T16 の版） | `25322b6b6be69db6cca7f167d7b0e5327156a595` | 2024-04-26 | 85・0.77 MB |
| M04 | `terraform-aws-vpc-v5.21.0/` | v5.21.0（5.x の最新。`git ls-remote` で v5.x.y の最大。T18 の `~> 5.0` が選ぶ版） | `7c1f791efd61f326ed6102d564d1a65d1eceedf0` | 2025-04-21 | 90・0.83 MB |
| M05 | `terraform-aws-eks-v20.8.5/` | v20.8.5（T16 の版） | `afadb14e44d1cdbd852dbae815be377c4034e82a` | 2024-04-08 | 135・0.84 MB |

- 合計 310 ファイル、2,438,412 バイト（2.44 MB）。上限（15 MB・2,000 ファイル）の内側。削除したのは eks の `.github/images/*.svg` の 2 ファイルだけ（画像は除外の決まり）。Apache-2.0。LICENSE は取得元のまま。ルートの NOTICE の 3 は「terraform-aws-modules の各リポジトリ」を Apache-2.0 として挙げ、版を書かない書き方なので、新しいフォルダにそのまま当てはまり、書き換えていない。
- 取り込みコミットのメッセージに「約 3.1 MB」と書いたのは、作業ツリー（CRLF）のディスク上の大きさ。コミットされる内容（LF）は上の 2.44 MB。
- eks の 20.x の最新（v20.37.2）は取り込んでいない（指示のとおり）。比較のためだけに一時フォルダ（リポジトリの外）にクローンし、下の「eks 20.x の確かめ」で使った。
- `tf_public_check.py --all` の対象は、`.tf` のあるフォルダ 205 → **248**（+43）。リソース 11621 → 16706（取り込み直後）→ **16898**（表を足した後。T16・T18 だけでなく、新しいフォルダの `examples/` がレジストリの vpc `~> 5.0` を呼んでいて、5.x の表で展開される）。warn 2582、info 22063、error 0。既定の 52 ルートは、リソース 2480 → **2553**（+73 = T16 の +59 と T18 の `environment` の +14）、warn 381 → 400、info 1027 → 1032。golden の 52 ルートの一覧（`root_folders()`）は変えていないので、新しいフォルダは golden に入らない。

### 表の作り方（決めたこと）
- **vpc 5.x（`v5.md`）**: v6 の表（v6.7.3）を元に、5.21.0 の本物のソースと突き合わせて直した（変数の宣言 81 件の既定値と型、出力 51 件の式、リソースのブロックの属性を、使い捨ての比較スクリプトで本物と照合。違いは次の 4 つだけ）: ① 6.x で足された `region` の変数と `region = var.region` を除く、② AZ か AZ ID かを見分ける正規表現が 5.x は `^[a-z]{2}-`（6.x は `^[a-z]+-`）、③ `aws_route_table_association.database` の count は 5.x では `local.create_database_subnets ? len : 0`（6.x の「DB のルートテーブルか private のサブネットがあるとき」の条件が無い）、④ 6.x の `# not-covered:` の入力は 5.x でも同じ（elasticache・redshift・outpost のサブネット、専用の NACL、IPv6 のプレフィックス、DHCP オプション、フローログ、VPN の経路の伝播、IPAM、Block Public Access など）。出力の `vgw_id` だけ 5.x は `aws_vpn_gateway_attachment` も見る（`vpn_gateway_id` が not-covered なので同じ値）。
- **5.8.1 と 5.21.0 の違い**（`diff` で本物の 2 つを比べた。表は 5.21.0 に合わせた。1 つの major に 1 つの表しか持てないため）: ① `create_multiple_public_route_tables = true` のとき、public のルートテーブルから IGW への経路（`aws_route.public_internet_gateway`、IPv6 のときは `…_ipv6`）が、5.8.1 は 1 つ（`aws_route_table.public[0]` だけ）、5.21.0 はテーブルごと。表は後者なので、5.8.1 の呼び出しでこの入力を使うと、表は 2 つ多く出す（意図した違い。テストで固定）。② `create_private_nat_gateway_route`（`aws_route.private_nat_gateway` の count）は 5.21.0 で足された入力で、5.8.1 には無い。既定 true なので、5.8.1 の動きと同じ。③ 5.21.0 で足されたもの（`aws_vpc_block_public_access_*`、DHCP オプションの IPv6 のリース、フローログの IAM の入力、`*_subnet_objects` の出力）は図に出ないか、5.8.1 の呼び出しでは渡せない。T16 の入力（education-vpc、23 件）は両方の版で本物と全部一致。
- **eks 20.x（`v20.md`）**: v20.8.5 の `main.tf`・`node_groups.tf`・サブモジュール 3 つ（eks-managed-node-group・fargate-profile・self-managed-node-group）から作った。変数の宣言は、本物の `variables.tf` から、表の本文が使うものだけを、`description` を除いて機械的に写した（root 72、managed 35、fargate 15、self-managed 33）。本文は v21 の表と同じ書き方（使い捨てのスクリプトで宣言と本文を組み立てた）。v21 との違い: ① 20.x の名前（`cluster_name`・`cluster_version`・`cluster_addons`・`cluster_endpoint_*`・`cluster_security_group_*`・`cluster_encryption_config`（既定で `{ resources = ["secrets"] }` なので KMS を作る））、② node のグループの引数は、本物の `try(each.value.x, var.<…>_defaults.x, 既定値)` の鎖をそのまま写した（図に要る引数だけ。`eks_managed_node_group_defaults` などが効く）、③ クラスタのタグを primary SG に付ける `aws_ec2_tag.cluster_primary_security_group`（`tags`・`cluster_tags` の `Name` 以外ごとに 1 件）を写した（`tags` は最もよく渡す入力なので、書かないと本物と address がずれる）、④ EFA の SG ルール（root）、IAM ポリシーの追加（`iam_role_additional_policies`）、IPv6 の CNI の attachment を写した、⑤ `module.kms` は表の中の黒箱（20.8.5 の版は 2.1.0。v21 は 4.0.0）、⑥ クラスタ作成者の ARN は v21 と同じ固定の文字列。
- **eks 20.x の `# not-covered:`**: `outpost_config`、`cluster_identity_providers`（`aws_eks_identity_provider_config`）、`create_cni_ipv6_iam_policy`、node のグループの `enable_efa_support`・`create_placement_group`・`schedules`（`eks_managed_node_groups.*.…`・`self_managed_node_groups.*.…` と、`*_defaults.…`）。`data.tls_certificate`（OIDC のルート CA の thumbprint）・`data.aws_eks_addon_version`・`module.user_data`（`null_resource` の検査）は表に載せない（本物との違い。docs/spec/module-summaries.md の 3）。Karpenter・aws-auth のサブモジュールは表にしない。
- **版の選び方**: コードは同じ。`5.8.1`・`~> 5.0`・`>= 5, < 6`・`< 6.0` は 5、`20.8.5`・`~> 20.0` は 20、`>= 5.0, < 7.0` は 6（前提に書く）、vpc の `2.77.0`・eks の `~> 19.15.2` は黒箱（理由に `it has 5.x, 6.x`・`it has 20.x, 21.x`）。

### 選び方の確認（これまでの表の選び方が変わっていないこと）
`SummaryTest.test_choose_is_unchanged_for_every_previous_pair`（永続のテスト）と、使い捨てのスクリプトで確かめた。
- 旧い表（5・20 を除いたフォルダ）と今の表の `resolve.choose(source, version)` を、9 つの source（vpc・alb・rds・eks、サブモジュール、kms、レジストリのホスト付き、無関係）× 約 440 の版の制約 = **3,987 組**で比べた: 前に表が選ばれていた **1,256 組は、選ばれる表（同じファイルの同じ内容）も前提の文も同じ**。前は「表に無い major」で今は 5 か 20 の表が当たるのが **98 組**（vpc の 5 を許すもの、eks の 20 を許すもの）。前も今も表が無いのが 2,633 組（理由の文の「表にある major」の列挙だけが増える）。
- fixture（`aws-iac-diagram-workspace/fixtures` の `.tf`）の、レジストリのモジュールの (source, version) の組 46（呼び出し 147）: 前と同じ表が **7 組**、前は表が無く今は当たるのが **3 組**（vpc `5.8.1`、vpc `~> 5.0`、eks `20.8.5`）、表が無いままが 36 組。

### 本物と突き合わせたテスト（`tests/unit/terraform/test_module_summaries.py`、新規 8 件）
同じ入力で、本物のタグのソース（`fixtures/public/terraform-aws-vpc-v5.8.1` など）をローカルモジュールとして展開した結果と、要約表で展開した結果を、作られるリソースの address・表のリソースの間の参照・名前とタグで突き合わせる（既存の `compare_with_source`）。
- vpc 5: v5.8.1（制約 `5.8.1`）と v5.21.0（`~> 5.0`、`>= 5, < 6`）× 4 入力（v6 のテストと同じ 3 つ + T16 の education-vpc）が、25・39・17・23 件で全部一致。5.8.1 と 5.21.0 の違い（public の複数ルートテーブル、IPv6 の NAT64 の経路、`create_private_nat_gateway_route`）は、本物の 2 つの版の違いと一致することを固定した（`allowed` に、違う address を 1 つずつ書く）。
- eks 20: v20.8.5 を、マネージド（`*_defaults`、既存の IAM ロール、起動テンプレートの名前、`attach_cluster_primary_security_group`）・Fargate・セルフマネージド（`create_access_entry = false` など）・アドオン（`before_compute`）・アクセスエントリ・`tags` を渡した入力で展開し、`null_resource`（4 件）を除いて **54 件**の address・参照・名前が一致。最小の入力（23 件）、暗号化なし（`module.kms` が `enabled: false`、暗号化のポリシーが出ない）も確認。参照の形（クラスタ → ロール・kms・SG、node のグループ → ロール・起動テンプレート → node の SG など）を 10 組、期待どおりに固定した。
- 表を壊すと落ちること（変異）: v5.md の IGW 経路の count を 1 にする → `test_vpc5_differences…` が落ちる、v20.md の node の SG ルールの名前を 1 つ変え・`prefix_list_ids` の既定を変える → `test_eks20_summary_matches_source` が落ちる。
- T16・T18: `test_t16_and_t18_have_no_blackbox_for_the_summarised_modules`。T16 の黒箱は `module.eks.module.kms`（表の中の黒箱。terraform-aws-modules/kms は 4 つの表の外）と `module.irsa-ebs-csi`（IAM だけ。H-IAM）。T18 `environment` は `module.acm` だけ。T18 `eks-blue`・`eks-green` は 11 件（eks 19.x、eks-blueprints の addons・teams、`gitops_bridge_bootstrap`（git）、IAM の IRSA 2 件）。
- ほかのテストの変更（弱めていない）: `test_choose_version` の「5.8.1 などは表が無い」の期待を「5 を選ぶ」に（`2.77.0`・`4.0.0`・`7.0.0` などで「表が無い」は残した）、`test_summary_expansion_diagnostics` の黒箱の例を `5.8.1` → `4.0.2` に、`test_summary_file` に版ごとのファイルと majors を確かめる行を足した。doctor の一覧と `RUNTIME_DATA` に 2 ファイルを足した（食い違うとテストが落ちる）。

### eks 20.x の確かめ（取り込まなかった版との比較。リポジトリの外の一時フォルダ）
`v20.md` はコミットした v20.8.5 でだけ確かめている。20.37.2（最新。2025-07-17）を一時フォルダにクローンし、同じ入力（54 件の入力）で本物と表を突き合わせると、**`aws_iam_policy.custom[0]` と `aws_iam_role_policy_attachment.custom[0]`（`enable_auto_mode_custom_tags` の既定が true。IAM だけ）の 2 つが本物に多い**だけで、残りの address・参照・名前は一致した。20.8.5 と 20.37.2 の `main.tf` の差は 464 行あるが、この入力が通る範囲では表の結果が変わらなかった、という意味で、20.37.2 までのすべてを保証するものではない（`~> 20.0` は 20.8.5 から作った表で展開され、20.2x 以降の追加リソースは出ない）。

### golden の更新（意図した変更）
`golden.py --update --accept-changes`。101 ケースのうち変わったのは **5 つだけ**（追加・削除なし。`tests/golden/manifest.json` の差は 5 エントリ）。
- **証明の方法**: 旧（`0652deb`）の SKILL（`git archive` を一時フォルダに）と新で、golden と同じ引数・同じ fixture の `adapt_tf.py` を、`tf/public/` の **52 ルートすべて**で動かし、raw IR を保存した。旧の出力の SHA-256 は manifest の旧の値と 52 件すべて一致（旧の出力を再現できた）。新の出力の SHA-256 は、更新後の manifest と 52 件すべて一致。そのうえで、使い捨てのスクリプト（リポジトリの外。`golden_diff_check.py`）が、旧と新の構造を規則で比べた。規則（どれにも当てはまらなければ失敗）: 変わらない = バイトが同じ / 型 A = ある呼び出し X（vpc 5.x・eks 20.x のレジストリ呼び出し）が黒箱から要約表の展開に変わった: (a) 消えたリソース = 旧の X の黒箱のエントリだけ、(b) 増えたリソース = `X.` の下の `via: module_summary`（と、表の中の `X.module.kms` の黒箱）だけ、(c) 両方にあるリソースの違いは、旧の値が X への `$res` を含む場所だけ、(d) 参照: X に触れない旧の参照はすべて同じ、X に触れる旧の参照は消え、新しい参照は X に触れるものだけ、(e) 診断: X に触れない旧の診断は同じ順序で同じ、X 自身についての旧の診断（黒箱の通知と、呼び出しの引数の TF-UNEVALUATED）は消え、新しい診断は X の下か、(c) で変わったリソースのものだけ、(f) `evaluation`・`format`・`root` などは同じ / 型 B = `TF-MODULE-BLACKBOX` の診断の文の「表にある major」の列挙だけが違う。
- **結果**（`golden_proof.txt` の抜粋。52 ルート）:
  ```
  unchanged (byte-identical old vs new): 47
  type A (blackbox -> summary expansion): 2
    learn-terraform-provision-eks-cluster (T16)  S=[module.eks, module.vpc]
      resources: removed 2 (blackbox calls), added 61, changed-by-reference 1 [module.irsa-ebs-csi]
      references: old 7 (touching S 6), new 156, new-only 155
      diagnostics: removed 2, added {TF-MODULE-SUMMARY: 2, TF-UNEVALUATED: 2, TF-MODULE-BLACKBOX: 1 (module.eks.module.kms)}
    blue-green-upgrade/environment (T18)  S=[module.vpc]
      resources: removed 1, added 15, changed-by-reference 0
      references: old 5 (touching S 0), new 25, new-only 20
      diagnostics: removed 4 (blackbox 1 + 引数の TF-UNEVALUATED 3), added {TF-MODULE-SUMMARY: 1, TF-UNEVALUATED: 12, TF-COUNT-UNRESOLVED: 8, TF-COUNT-INDEX: 4}
  type B (message text only): 3
    learn-terraform-aws-asg      vpc 2.77.0:    (it has 6.x)  -> (it has 5.x, 6.x)
    blue-green-upgrade/eks-blue  eks ~> 19.15.2: (it has 21.x) -> (it has 20.x, 21.x)
    blue-green-upgrade/eks-green 同上
  FAILED: 0
  ```
- 型 B の 3 ケースは、vpc 5.x・eks 20.x を使わない（`learn-terraform-aws-asg` は vpc 2.77.0、eks-blue・eks-green は eks 19.15.2）が、黒箱の診断の文が「表にある major」を列挙するので、表が増えると文だけが変わる。指示（vpc 5.x・eks 20.x を使わないケースはバイト単位で同じ）の例外で、構造の違いは無い（文の置換で旧と新が一致することを上の規則 B で確かめた）。
- **T16 の `module.irsa-ebs-csi`** の違い: `provider_url = module.eks.oidc_provider` は、旧は `module.eks` への参照、新は `$unknown`（`replace()` の引数のクラスタの issuer が apply 前に決まらない）と `TF-UNEVALUATED` 1 件。`role_name` の `module.eks.cluster_name` は `module.eks.aws_eks_cluster.this[0].name` への参照。**`provider_url` を通る参照は、OIDC プロバイダのリソースではなく `module.eks.aws_eks_cluster.this[0]`（`attr: identity`）への `state: unevaluated` の参照として残り、`through: ["module.eks.output.oidc_provider"]` が付く**（`role_name` を通るクラスタへの active な参照も付く。フェーズ 3 の H-IAM が `through` で OIDC プロバイダに結べる。下の「レビュー対応」の 5）。v21 の表でも同じ（出力 `oidc_provider` の式が本物と同じで、評価器が未知の値への `replace()` を未知にするため）。
- T18 `environment` の vpc は、`azs` が `length(data.aws_availability_zones…names)` に依って apply 前に決まらないので、サブネット・ルートテーブル・NAT などが「×N」の 1 ブロックで出る（`TF-COUNT-UNRESOLVED`）。評価器の既存の扱い（A4）で、今回の変更ではない。

### 確かめたこと
- 単体テスト **432 件**（424 + 新規 8）が **Windows の通常の TEMP**（114 秒）と **`subst Y:` の別のドライブの TEMP**（`TEMP`・`TMP` を `Y:	mp` に。122 秒）で OK。`uv lock --check` OK、golden 101/101、pyflakes 0 件（触った Python）。新しいテスト 8 件: `test_choose_is_unchanged_for_every_previous_pair`、`test_vpc5_summary_matches_source`、`test_vpc5_differences_between_5_8_1_and_5_21_0`、`test_vpc5_not_covered_inputs_are_reported`、`test_eks20_summary_matches_source`、`test_eks20_references_between_summarised_resources`、`test_eks20_not_covered_inputs_are_reported`、`test_t16_and_t18_have_no_blackbox_for_the_summarised_modules`（`SummaryTest`）。既存のテストの変更は、期待が変わる 2 件と拡張 1 件（`test_choose_version`・`test_summary_expansion_diagnostics`・`test_summary_file`。上）と、`test_folder_lists`（フォルダ数の下限を 200 → 248 にし、新しいフォルダが入っていることの確認を足した）、doctor の一覧 2 か所への 2 行だけで、緩めたものは無い。
- **WSL（Ubuntu。`git archive HEAD` を WSL の中で展開した 2,132 ファイルのコピー）**: `uv sync --locked`、単体テスト 432 件 OK（72 秒）、golden 101/101、`tf_public_check.py --all --jobs 4` は Windows と同じ **248 フォルダ、リソース 16898、warn 2582、info 22063、error 0**、`c1_check.py` は入力 25・辺 513・対応の無い辺 0（変わらない）、CI の「正解 IR と fixture の検証」の手順（`validate_ir.py`、`check_coverage.py --lint`、自作 TF 5 構成・CFN 5 構成・plan JSON の `adapt_*.py` を PEP 723 の入口で動かして `validate_ir.py`）がすべて OK。
- **SKILL だけのコピーを日本語とスペースを含むパス（`日本語 パス`）に置いて**（Windows の PowerShell と WSL の両方）、`doctor.py`（Windows は ok、WSL は mmdc・draw.io が無いだけの warn。欠けたファイル 0・表の置き方の誤り 0）と、コピーの `adapt_tf.py` で T16 と T18 `environment`（サンプルのフォルダは SKILL の外なのでリポジトリのパスを `--input` に渡す）を動かした出力が、リポジトリの中のスクリプトの出力と**バイト単位で同じ**（T16 88,078 バイト、T18 24,291 バイト。manifest の SHA-256 とも一致）。コピーで `validate_ir.py` も OK。
- 変異: 上の「本物と突き合わせたテスト」。

### 残したこと・リスク
- **eks 20.x の表は v20.8.5 でだけ確かめた**。`~> 20.0` は 20.37.x を指すが、20.37.2 では IAM の 2 件が多い（上）。20.8.5 に無い入力（20.2x〜20.3x で増えた Auto Mode の `compute_config` など）は、変数の宣言が無いので、渡されると `TF-MODULE-SUMMARY-INPUT`（info）に名前が出る（意図した動き）。一方、20.8.5 に有って新しい版で既定の挙動が変わったもの（上の IAM の custom ポリシー）は、入力を渡さなくても本物は作るので、通知は出ない。
- vpc 5.x の表は 5.21.0 に合わせた。5.8.1 は上の 1 点（public の複数ルートテーブルのときの IGW 経路の数）で表が多く出す。5.9〜5.20 の途中の版は確かめていない（両端の 2 つの版の `main.tf`・`variables.tf`・`outputs.tf` の `diff` で、表が覆う範囲の違いは上の 3 つだけと確かめた）。
- IPv6 の NAT64 の経路（`private_dns64_nat_gateway`、`database_dns64_nat_gateway`、`database_ipv6_egress`）は、v6 の表と同じく 5 の表にも写していない。`enable_ipv6 = true` と NAT を使うと、表はそれらを出さない（テストで固定。`TF-MODULE-SUMMARY-INPUT` にも出ない: `enable_ipv6` は他の理由で宣言している入力のため）。v6 の表にも同じ欠けがある（今回は直していない）。
- kms（`module.eks.module.kms`）は表の外のモジュールなので、eks の 20.x・21.x どちらも黒箱のまま（KMS キーのリソースは出ない）。
- T18 の eks `~> 19.15.2` は黒箱のまま（19.x の表は作らない）。
- `aws_ec2_tag.cluster_primary_security_group` は、20.x では `tags` の `Name` 以外ごとに 1 件の `aws_ec2_tag` として raw IR に出る（本物と同じ。正規化（フェーズ 3）で扱いを決める）。
- CI（GitHub Actions）は実行していない（push していない）。

### レビュー対応（follow-ups。第三者レビュー: APPROVE WITH CHANGES。1 つのコミットで直した）
表の忠実度は、レビューが vpc 126 件・eks 92 件の差分実行で確かめた。指摘は MINOR 3 件と NIT。出力（golden）は変わらない（101/101）。
1. **MINOR 1: `launch_template_tags` の宣言漏れ**（eks 20.x の self-managed の表）。親の呼び出しが渡す入力に、子の表に宣言が無いものがあり、セルフマネージドのグループごとに `TF-MODULE-SUMMARY-INPUT` が出ていた。本物の `modules/self-managed-node-group/variables.tf` の宣言（`type = map(string)`、`default = {}`）を写して足した。**同じ種類の欠けの点検**: 表の中の親の `module` ブロックが渡す入力と、子の表が宣言する変数を、すべての子の表（eks 20 の 3、eks 21 の 3、rds 7 の 5。計 11）で突き合わせた。欠けは `launch_template_tags` の 1 件だけ（ほかの 10 は 0 件）。`module.kms` は表の外（黒箱）で宣言を持たないので対象外。回帰テスト: `test_every_input_a_table_passes_to_a_submodule_is_declared_there`（上の突き合わせを全表に対して永続化。修正を戻すと落ちることを確かめた）、`test_eks20_empty_node_groups_report_no_uncovered_inputs`（`self_managed_node_groups = { s = {} }` などで `TF-MODULE-SUMMARY-INPUT` が 0 件。v21 の表も同じ形で確かめる）。
2. **MINOR 2: 生き残った変異を殺すテスト**。`compare_with_source` に `extra`（呼び出しの後ろの HCL）と `ignore`（入力に依って有る・無いが変わる検査用の `null_resource` を除く）を足し、次を足した: `test_eks20_switches_match_source`（`create = false`、`create_iam_role = false`、`enable_irsa = false`、ログのグループを作らない、クラスタ／node の SG を作らない、自分の KMS キー、暗号化のポリシーなし、と組み合わせ 2 つ。11 通りを本物と突き合わせ、あわせて出力 `oidc_provider_arn`・`cluster_name` を読む `aws_ssm_parameter` の probe の値が本物と同じ）、`test_eks21_switches_match_source`（v21 の既存の表にも同じ 6 通り。表は変更なし）、`test_vpc_switches_match_source`（5.8.1・5.21.0・6.7.3 × `create_database_subnet_group = false`、`one_nat_gateway_per_az` は既定のまま（AZ 3、サブネット 2 で NAT が 2 つ）、`create_vpc = false`、`create_igw = false`）。
3. **MINOR 3: 通知されない欠けの文書化**。`docs/spec/module-summaries.md` の 3 に「まだ写していないもの（通知されない欠け）」を足し（`aws_route.private_dns64_nat_gateway`・`database_dns64_nat_gateway`・`database_ipv6_egress`、本物にあって表に無い出力 vpc 68・eks 20 は 4・eks 21 は 16 を名前で）、`v5.md`・`v6.md` の先頭の `#` の行にも書いた（ローダーは `# not-covered:` の行しか読まない。v6 の表の動きは変えていない。golden 101/101 で確認）。
4. **NIT**: `test_module_summaries.py` の 314 文字の行（空白が潰れていた）を複数行に戻した。変数の説明（`NOTICE.md`・`docs/spec/module-summaries.md` の 1）を、「表の本文が使う変数の宣言だけを写す」に直し、宣言した数を本物の数と並べた: vpc 5.x 82 / 234、vpc 6.x 83 / 236、eks 20.x 72 / 88、eks 21.x 62 / 108。残りは `TF-MODULE-SUMMARY-INPUT` で通知される。HANDOFF の現在の状態の行の数は 248 フォルダ・437 件に直した（205 は履歴の文だけ）。
5. **T16 の IRSA の文書**: `docs/spec/module-summaries.md` の 3 に段落を足した。`module.eks.output.oidc_provider` は `replace(issuer, "https://", "")` なので、`provider_url` は値が決まらない参照のまま残り、参照 `module.irsa-ebs-csi → module.eks.aws_eks_cluster.this[0]`（`attr: identity`、`state: unevaluated`）に `through: ["module.eks.output.oidc_provider"]` が付く。フェーズ 3 の H-IAM は `through` で IRSA のロールと `aws_iam_openid_connect_provider` を結べる。評価器と表は意図して変えていない。**上の golden の節の「IRSA のロール → OIDC プロバイダの辺は付かない」は不正確だった**: 参照（unevaluated）は付く。付かないのは active な辺と、OIDC プロバイダのリソースそのものへの参照。

#### 変異の殺し方（表の変異 10 件。表を一時的に書き換え、`tests.unit.terraform.test_module_summaries` だけを流した。使い捨てのスクリプト）
| 変異 | 対象 | 追加前の単体テスト | 追加後に落ちるテスト |
|---|---|---|---|
| M1 `aws_db_subnet_group` の count から `var.create_database_subnet_group` を外す | vpc v5・v6 | 生き残る（2 件とも） | `test_vpc_switches_match_source` |
| M2 `one_nat_gateway_per_az` の既定を true にする | vpc v5・v6 | 生き残る | `test_vpc_switches_match_source` |
| M3 `aws_eks_cluster` の count を 1 に固定 | eks v20 | 生き残る | `test_eks20_switches_match_source` |
| M4 `create_oidc_provider` から `enable_irsa` を外す | eks v20 | 生き残る | `test_eks20_switches_match_source` |
| M5 `create_iam_role` を無視する | eks v20 | 生き残る | `test_eks20_switches_match_source` |
| M6 ログのグループの count を 1 に固定 | eks v20 | 生き残る | `test_eks20_switches_match_source` |
| M7 出力 `oidc_provider_arn` の名前を変える | eks v20 | 生き残る | `test_eks20_switches_match_source` |
| M8 出力 `cluster_name` の名前を変える | eks v20 | 生き残る | `test_eks20_switches_match_source` |

「追加前」は、追加前のテストファイル（コミット済みの `19722ab` の版）で同じ変異を当てた結果（10 件すべて生き残り、golden でしか見つからない状態）。「追加後」は 10 件すべて、単体テストで落ちる（golden に頼らない）。

#### 数字
- 単体テスト **437 件**（432 + 新規 5: `test_eks20_switches_match_source`、`test_eks21_switches_match_source`、`test_vpc_switches_match_source`、`test_every_input_a_table_passes_to_a_submodule_is_declared_there`、`test_eks20_empty_node_groups_report_no_uncovered_inputs`）。
- `tf_public_check.py --all`: 248 フォルダ、リソース **16898**、warn 2582、info 22063、error 0（`launch_template_tags` の修正では変わらない: 公開サンプルに、親の表で展開される self-managed のグループは無い）。golden 101/101。
- 確認（レビュー対応のコミット）: Windows の通常の TEMP（164 秒）と `subst Y:` の TEMP（167 秒）で 437 件 OK、`uv lock --check` OK、golden 101/101、pyflakes 0 件。WSL（`git archive HEAD` を WSL の中で展開）は 437 件 OK（98 秒）、golden 101/101、`tf_public_check.py --all --jobs 4` は 248 フォルダ・16898 リソース・error 0、`c1_check.py` は 25・513・0、SKILL だけのコピー（日本語とスペースのパス）の T16・T18 の出力は在リポジトリの出力とバイト単位で同じ（88,078・24,291 バイト。manifest と一致）。
