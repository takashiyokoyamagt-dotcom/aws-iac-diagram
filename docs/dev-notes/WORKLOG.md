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
