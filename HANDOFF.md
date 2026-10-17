# HANDOFF（再開用）

## 作業状況のまとめ（2026-10-17 時点）

再開するときは、まずこの節を読み、細かい経緯は下の節と [WORKLOG.md](WORKLOG.md)、計画は [PLAN.md](PLAN.md) を見る。

### フェーズの状態

| フェーズ | 内容 | 状態 |
|---|---|---|
| 0 | 準備（ツール、アイコン辞書と C2、自作 fixture 5構成と正解 IR、公開サンプルの選定、評価基準値） | **完了**（2026-10-16、`4b5787f`） |
| — | 共通 Agent Skill の方針への移行（[docs/skill-cross-platform-guide.md](docs/skill-cross-platform-guide.md)、PLAN の 1.3） | **完了**（2026-10-16、`4af11c3`） |
| 1 | IR スキーマの確定と CloudFormation アダプタ（A4、C1） | **完了**（2026-10-17、`7e14639`） |
| 2 | Terraform アダプタ（.tf と plan JSON、A4、A5） | **進行中**。手順1（土台、`e61aa9e`）・手順2（A4、`dd8d471`。秘密の値の扱いはユーザーの決定で `evaluation.vars` に値を書かず `--redact-var` を足した）はコミット済み。**手順3（モジュール、A5）もコミット済み**（2026-10-17。第三者レビュー「修正後コミット」→対応分の再確認「コミット可」）。残りは下の「次にやること」の 3a |
| 3〜6 | 正規化、配置と .drawio、Mermaid と PNG、SKILL.md の仕上げと評価 | 未着手 |

### できているもの

| もの | 場所 | 内容 |
|---|---|---|
| SKILL の本体 | `skills/aws-iac-diagram/` | SKILL.md は骨組み（図はまだ作れないと書いてある）。`scripts/doctor.py`（環境の確認） |
| IR スキーマ v1.0 | `references/ir-schema.md`、`ir.schema.json`、`ir-raw.schema.json` | 正規化後の形（1〜6章）と、アダプタの出力 raw IR（7章）。どちらも確定 |
| 規則表（草案） | `references/resource-catalog.md`、`relation-resources.md`、`edge-rules.md` | 型ごとの扱い、関係リソース、辺の規則、辺にしない参照（`E-NOEDGE-*`）。フェーズ3 で広げる |
| CloudFormation アダプタ | `scripts/adapters/cfn.py` | テンプレート・ネストスタック・SAM・cdk.out から raw IR を作る。条件の評価、`--param`／`--param-file` |
| Terraform アダプタ（作成中） | `scripts/adapters/tf.py`、`scripts/lib/tf_eval.py`、`scripts/lib/tf_modules.py` | ルートモジュールの .tf から raw IR を作る。変数（tfvars、`--var-file`・`--var`）・locals・式を評価し、count・for_each をインスタンスごとに展開する（手順2）。ローカルモジュールを再帰的に展開し、terraform-aws-modules の vpc・alb・rds・eks は要約表で展開、それ以外は黒箱（手順3）。plan JSON はまだ読まない（ir-schema.md の 7.6） |
| A5 の要約表 | `references/module-summaries.md` | vpc 6.x・alb 10.x・rds 7.x・eks 21.x の主要なリソースと出力を、本物のソースから HCL で写したもの。4つとも、タグを付けた版のソース（`fixtures/public/terraform-aws-{vpc,alb,rds,eks}`）の展開と突き合わせるテストあり。IAM だけのモジュールの source の一覧（H-IAM） |
| 検査 | `scripts/validate_ir.py`、`scripts/lib/ir_raw.py` | 正規化後と raw IR の両方を検査（`stage` で切り替え） |
| アイコン辞書と C2 | `references/icons/`、`scripts/build_icon_catalog.py`・`check_icons.py`・`find_aws_icon.py` | 1045 件、壊れたもの 0 件 |
| 評価基準 | `aws-iac-diagram-workspace/evals/CRITERIA.md` | 確定（ユーザーの了承済み） |
| fixture と正解 IR | `aws-iac-diagram-workspace/fixtures/`、`expected/` | 自作5構成（TF／CFN）、公開サンプル（T01〜T20、C01〜C05 など） |
| 開発用の道具 | `aws-iac-diagram-workspace/tools/` | `c1_check.py`（C1）、`check_coverage.py`（網羅）、`iac_inventory.py`、`survey_public.py` |
| テストと CI | `tests/`（205 件）、`.github/workflows/ci.yml` | Ubuntu 24.04 と Windows 2025（PowerShell 5.1 から SKILL を起動）で、テスト・検証・C1・TF アダプタの起動 |

### 数字で見た現状
- 単体テスト 205 件がすべて通過（TF アダプタと評価器の 70 件を含む）。
- TF アダプタ（手順3 まで）: 自作 fixture の5構成と、公開サンプルの TF のルート 52 フォルダ（T01〜T20、P01〜P04）、`.tf` のあるフォルダすべて（172）で例外なく動き、raw IR の検査を通る（error の診断 0）。正解 IR の TF 側の網羅分類と、モジュールの中身（要約表の展開とローカルモジュール）まで読み替えなしで一致（three-tier は `env/dev.tfvars`）。モジュールを展開したので、ルート 52 のリソースは 854 → 2480、warn は 130 → 381（展開したモジュールの中の、値の無い変数やリソースの属性に依る値。WORKLOG の「フェーズ2 の手順3」）。
- C1: 自作 fixture と公開サンプルの CFN（入力 25）で、cfn-lint のグラフの辺 513 本のすべてに raw IR の参照が対応（対応の無い辺 0）。
- 正解 IR の CFN 側の網羅分類と、CFN アダプタの出力の address・型・ファイル・作られるか（enabled）が、5構成すべてで一致。
- GitHub の CI は、`4af11c3` から `7e14639`（C1 の照合を足したもの）まで、両 OS で成功。

### 再開の手順（Windows）

```powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
uv sync
uv run python -m unittest discover -s tests
uv run python aws-iac-diagram-workspace\tools\c1_check.py
```

### 判断待ち・許可待ち
下の「ユーザーの判断待ち」の節にある5つ（L4 の辺の貫通の上限値、PNG をどちらで作るか、WSL と CI に入れるもののインストールの許可、実行時間の基準値の見直し、vpc 5.x・eks 20.x の要約表を作るか）。どれも急ぎではなく、フェーズ3〜6 の手前で確認する。

### 次にやること（要点）
1. **フェーズ2（Terraform アダプタ）。** 5つの手順に分けた（1=土台、2=A4、3=モジュール、4=plan JSON、5=公開サンプルでの確認と完了）。手順1・2 はコミット済み。手順3 もコミット済み。**次は手順4（plan JSON）**。決まっていること・気をつけることは「次にやること」の 3a。
2. 見送った小さな直し（「次にやること」の 0b）: CI の action の版の更新、doctor のパス長の診断、PEP 723 の間接依存の固定など。
3. 既知の制約: cdk.out は実物の `cdk synth` の出力では未確認（フェーズ6 の前に fixture を1つ足す）。

## ユーザーの判断待ち（2026-10-17 時点）
- **L4（T17、T19、T20）の辺の貫通の上限値**（CRITERIA.md の 7 の 4）。フェーズ4 の配置の実装を始める前に、案を出して了承を得る（結果を見てから決めない）。
- **手元の Windows で作った PNG と CI で作った PNG のどちらをコミットするか**（PLAN 1.2 の 3）。フェーズ5 までに決める。
- **WSL の Ubuntu と CI に入れるもの**（uv、draw.io の `.deb`、xvfb、Chromium）のインストールの許可。フェーズ5 の手前で確認する。
- （フェーズ3 の実測の後）実行時間の基準値（CRITERIA.md の 4）を見直すなら、案を出して了承を得る。見直してよいのは一度だけ。
- **vpc 5.x・eks 20.x の要約表を作るか**（T16 の vpc 5.8.1・eks 20.8.5、T18 の vpc `~> 5.0` が黒箱のまま）。フェーズ6 の評価の前に改めて決める（2026-10-17 のユーザーの決定。作るなら、そのタグのソースの取り込みの許可も要る）。

## 作業の進め方
- 作業はユーザーと合意した手順に分けて1つずつ進める。実装とテスト・動作確認のあと、別のサブエージェントが第三者レビューをする（2026-10-17 までは、raw IR の設計を知っている同じレビュアーに続けて頼んだ）。判定が「コミット可」か、「修正後コミット」で指摘を直したら main にコミットして push する。「要再レビュー」なら直して再レビューを受ける。確定した基準（CRITERIA.md）や計画を変えるときは、先にユーザーの了承を得る。
- Claude の Bash ツールに渡すコマンド文字列では、`\a` などのバックスラッシュが制御文字に化けることがある（HANDOFF に BEL 文字が混入した）。ファイルの編集は Edit／Write ツールで行い、シェルでは Windows のパスをスラッシュで書く。コミット前に `tr -cd '\000-\010\r' < file | wc -c` などで制御文字と CR が 0 件か確かめる。
- PATH 上の `python` は Windows ストアのスタブなので使わない。SKILL のスクリプトは `uv run <スクリプト>`、テストと開発用のツールは `uv run python ...`（リポジトリの開発用の環境）で動かす。winget で入れた直後のシェルでは PATH が古いので、`$env:Path` をレジストリから読み直す。
- シェルの作業ディレクトリをリポジトリの中のフォルダにしたままだと、そのフォルダを `git mv` できない（Permission denied）。絶対パスで指定し、`cd` は使わない。
- Bash のヒアドキュメントに、日本語と `'` を多く含む長い文書やコードを渡すと解析に失敗することがある（「unexpected EOF」）。またコードの文字列の `\n` が本物の改行に化けることがある。長い書き換えは、Write ツールで `.git/` の下に修正用の Python を書き、`.venv\Scripts\python.exe` で当ててから消す。

## 共通 Agent Skill への移行（2026-10-16）
- [docs/skill-cross-platform-guide.md](docs/skill-cross-platform-guide.md) の方針を採用した。内容は PLAN.md の **1.3**（1.1・1.2 より優先）。利用環境は Claude Code と VS Code + Copilot（Windows）と gh-aw の3つで、SKILL は1つだけ。配布はタグ付きの Skill リポジトリから行い、プラグイン案はやめた。
- SKILL は `skills/aws-iac-diagram/` に移した。手元の登録は `~/.claude/skills/aws-iac-diagram` と `~/.copilot/skills/aws-iac-diagram` のジャンクション。単体テストはルートの `tests/` に移した。
- `.venv`＋`requirements*.txt` をやめ、`uv`（0.13.1、winget）にした。依存は各スクリプト先頭の PEP 723、開発用の環境は `pyproject.toml`・`uv.lock`（`uv sync`）。
- 作ったもの: `SKILL.md`（骨組み。図はまだ作れないと書いてある）、`scripts/doctor.py`、`lib/drawio_cli.py` の Linux 対応（`--no-sandbox`、画面が無いときの `xvfb-run -a`、`AWS_IAC_DIAGRAM_XVFB=1`）、`.github/workflows/ci.yml`（Ubuntu 24.04 と Windows 2025。Windows は PowerShell 5.1 から日本語とスペースを含むパスの SKILL を起動）、テスト 11 件（計 61 件）。
- CI は `4af11c3` から GitHub で両 OS とも成功している。

## 背景（2026-10-15）
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
| 1 | ツールのインストール | **済（Windows）**: Git 2.55、Node 24.20、Python 3.12.10、gh、draw.io Desktop 32.4.1、mmdc 12.0.0、uv 0.13.1（2026-10-16）。Python の依存は uv が入れる |
| 2 | SKILL のフォルダの作成と登録 | **済**: 2026-10-16 に `skills/aws-iac-diagram/` へ移し、`~/.claude/skills/aws-iac-diagram` と `~/.copilot/skills/aws-iac-diagram` からジャンクションで登録 |
| 3 | アイコン素材の取得と辞書の生成 | **済**: 版と SHA-256 は [assets/SOURCES.md](skills/aws-iac-diagram/assets/SOURCES.md)。`scripts/build_icon_catalog.py` で `references/icons/`（1045件、31カテゴリ）を生成。検索は `scripts/find_aws_icon.py`。再実行してもバイト単位で同じ出力になることを確認済み |
| 3b | C2（壊れたアイコンの自動検出 `check_icons.py`） | **済**: draw.io 32.4.1 で 1032 件（shape・resource_icon・group）を判定し、**壊れたものは 0 件**。対照 9 件（壊れ 6 種・正常 3 種）はすべて期待どおり。結果は `references/icons/broken.json` → 辞書の `broken`。テストはルートの `tests/`（当時 31件） |
| 4 | 自作テスト構成5種（TF 版と CFN 版）と正解 IR、公開サンプルからの選定、第三者レビュー | **済（`46ae7c3`）**: 第三者レビュー2回（1回目「修正後コミット」、正解 IR の誤りは無し。指摘反映後の2回目「コミット可」）。構成5種（three-tier、serverless-api、vpc-endpoints、three-tier-modules、rag）を `fixtures/tf/`・`fixtures/cfn/`（YAML・SAM・JSON・ネストスタック）に、正解 IR を `expected/*.ir.json` に作成。IR スキーマ草案 v0.1（`references/ir-schema.md`・`ir.schema.json`）と規則表の草案（`resource-catalog.md`・`relation-resources.md`・`edge-rules.md`）。検証: `scripts/validate_ir.py`（全正解 IR が通過）、`workspace/tools/check_coverage.py --lint`（網羅分類と入力が一致、cfn-lint 警告0、hcl2 で全 .tf を読める）。公開サンプルの選定は `fixtures/public/SELECTION.md`（主セット12、補助セット） |
| 5 | フェーズ6の評価基準値を決めてユーザーの了承を得る | **済（2026-10-16、`606ffb4`）**: [aws-iac-diagram-workspace/evals/CRITERIA.md](aws-iac-diagram-workspace/evals/CRITERIA.md)。第三者レビュー2回のあと、ユーザーが了承して確定。8章の申し送りのうち、`unknown` の扱い（ir-schema.md・resource-catalog.md）、id の対応づけと名前の一致率（ir-schema.md の 5）、PLAN の LLM の役割と 1.3 の 9 は反映済み |

**フェーズ0 は完了。**

## 次にやること
0. （済）GitHub の `ci` は `4af11c3` で両 OS とも成功した（Windows 約45秒、Ubuntu 約20秒）。Node 20 の廃止の警告が出ている（0b）。
0b. 2026-10-16 のレビューで見送った推奨: R2（doctor に Windows のパス長の診断: `LongPathsEnabled`、SKILL のパスの長さ、uv のキャッシュの場所）、R4（PEP 723 の間接依存の固定: `[tool.uv] exclude-newer` か `uv lock --script`。PEP 723 と `pyproject.toml` の版が揃っているかのテスト）、CI の `actions/checkout`・`setup-uv` を Node 20 廃止に合わせて更新し SHA で固定。再レビューの R1: SKILL.md の「gh-aw では `RUNNER_TEMP` に出す」は、同じファイルの `$VAR` の禁止とぶつかる（エージェントが値を知るにはシェルで展開するしかない）→ `diagram.py` を作るときに、`--out`／`--out-dir` を省略したらスクリプトが既定値（`RUNNER_TEMP`、無ければ作業中のフォルダの `aws-iac-diagram-out`）を決め、書いた先を ASCII で標準出力に出すようにし、doctor も合わせる。あわせて doctor で `--out` に書けなかったときも、集めた診断の結果を捨てずに出す。
1. （済）表の 5（評価基準値）。
2. **フェーズ1**（CloudFormation のアダプタ）。5つの手順に分けて1つずつ進める（2026-10-17 にユーザーと合意）。
   1. （済）IR スキーマの確定（ir-schema.md v1.0。raw の形は手順5 で確定）。評価基準の 1.6（C1）を raw の段階の照合に変え、1.8 を足した（ユーザーの了承）。正規化後の形の確定（`attrs` のキーの表、黒箱のモジュール `module`、×N、AZ が静的に決まらないときの key）、アダプタの出力（`stage: "raw"`、7章と `ir-raw.schema.json`）、公開サンプルの問題の扱い（7.4）、「辺にしない参照」（edge-rules.md の `E-NOEDGE-*`）
   2. （済）CFN アダプタの土台（`scripts/adapters/cfn.py`）。短縮タグの正規化と、組み込み関数から raw IR の印と参照を作る。fixture の CFN 10 本で cfn-lint の辺 214 本がすべて対応した（仮の照合）。`Fn::If`・`FindInMap`・`Condition` は手順4 まで `$unknown`
   3. （済）SAM（Globals、暗黙の API）、ネストスタック（子の展開と through、S3 URL の読み替え、黒箱）、cdk.out（複数スタック、Export の解決）。three-tier-modules を root から読んで 41 リソース・診断 0
      - （解消）手順4 までの既知の差（vpc-endpoints の parameters.json、Fn::ForEach）
   4. （済）A4（CFN 側の評価）: Conditions を3つの値で、リソースの Condition（子のスタックにも伝える）、`Fn::If`・`FindInMap`・`Fn::ForEach`、`--param`／`--param-file`。three-tier の dev／prod、vpc-endpoints の parameters.json で確認
      - 注意: YAML 1.1 では `On`／`Off`／`Yes`／`No` が真偽値として読まれる（cfn-lint も同じ）。条件やリソースの名前に使われていると名前を失うので、`str()` で済ませず、元の名前を引けるようにする。ネストスタックの子の `enabled` は親から引き継ぐので、親の Condition を評価したら子にも伝わるようにする
   5. （済）C1 の道具 `aws-iac-diagram-workspace/tools/c1_check.py`（入力を省くと fixture と公開サンプルの CFN をすべて調べる。CI でも流す）。入力 25・cfn-lint の辺 513 本で対応の無い辺 0。ir-schema.md の 7章（raw）を確定
   - **フェーズ1 は完了**（2026-10-17）。完了基準（テストが通る、cfn-lint の辺のすべてに raw IR の参照が対応する）を満たした
   - 既知の制約（フェーズ1 から持ち越し）:
     - cdk.out は、テストの中で作った manifest でしか確かめていない。実際の `cdk synth` の出力は公開サンプルに無く、C1 の対象（`c1_check.py` の discover はフォルダを見ない）にも入っていない。フェーズ6 の評価の前に、実物の cdk.out を1つ fixture に足して確かめる
     - C1 の `raw_only`（raw IR にあって cfn-lint に無い参照）は、ネストスタックの出力をたどった参照の数え方の違い（WORKLOG の「フェーズ1 の手順5」）。参考値で基準ではない
3a. **フェーズ2（Terraform アダプタ）**。同じ raw IR（ir-schema.md の 7章）を .tf と plan JSON から出す。5つの手順に分けて1つずつ進め、それぞれ第三者レビューを受ける（2026-10-17）。
   1. （済、`e61aa9e`）**土台**（`scripts/adapters/tf.py`）。ルートモジュールの .tf を python-hcl2 の構文木で読み、resource・data・module、参照（`$res`、`depends_on`）、`$pseudo`・`$az`・`$json`・`$concat`、heredoc の前処理（T06）、`path.module`・`terraform.workspace`・`file()`／`templatefile()`、`provider`・`region`（Schema に足した）。まだ評価しないものは `$unknown`（`TF-DEFERRED`、中の参照は `unevaluated`）・×N（`[*]`、`enabled: null`）・黒箱の module 呼び出し（`TF-MODULE-DEFERRED`）で出す（ir-schema.md の 7.6）。手順1 の時点の `ExpectedIrTest` は、正解 IR を手順1 の形に読み替えていた
   2. （済）**A4（TF 側の評価）**: 評価器 `scripts/lib/tf_eval.py`（値の型、関数 81、type の変換）。変数（default → `terraform.tfvars` → `terraform.tfvars.json` → `*.auto.tfvars(.json)`（名前順）→ `--var-file`・`--var`（指定した順）。`TF_VAR_*` は読まない。sensitive の値は使わない）、locals、テンプレートの `%{if}`・`%{for}`、条件式・演算・for 式、`try`・`can`、`dynamic`。count・for_each を展開し（`[0]`・`["key"]`、0 個は添字なしで `enabled: false`、そこへの参照も添字なし）、決まらないものだけ ×N（`TF-COUNT-UNRESOLVED`）。インスタンスへの参照とスプラットはインスタンスごとの `$res`。`evaluation.var_files`・`vars`、値の無い変数と `*.tfvars` の候補（`TF-UNRESOLVED-VARS`）。`pruned` は条件式・`try`・選ぶ関数・リストの添字・for の `if` だけ（7.2）。`ephemeral`（resources に載せない）、`check` の中の `data`、override のファイルも読む。`ExpectedIrTest` はモジュールの中身だけを読み替えていた（`step3_expected()`。手順3 で外した）。詳細は WORKLOG の「フェーズ2 の手順2」
      - 第三者レビュー（判定「修正後コミット」）の指摘（M1・R1〜R3・任意 1〜6）を直してコミットした（`dd8d471`）。R1 はユーザーの決定で、`evaluation.vars` に値を書かず出どころだけを書き、`--redact-var` で値を伏せられるようにした（README・SKILL.md に注意書き）
   3. （済。2026-10-17）**モジュール**: ローカルモジュールの再帰（address `module.x.…`、count・for_each の呼び出しはインスタンスごと、`module` フィールド、`through` の `module.x.output.y`・`module.x.var.y`、`path.module`、depends_on、循環 `TF-MODULE-CYCLE`・深さ 16 段 `TF-MODULE-DEPTH`）、A5 の要約表（`references/module-summaries.md`。vpc 6.x・alb 10.x・rds 7.x・eks 21.x を HCL で写し、同じ評価器で展開。`via: module_summary`。vpc・eks は手元の本物のソースと突き合わせるテスト）、要約表に無い・版が合わないレジストリと `git::` などは黒箱（`TF-MODULE-BLACKBOX`）、IAM だけのモジュールは source の一覧で判定（`tf_modules.iam_only()`。raw IR は黒箱のまま、正規化が H-IAM）、`terraform_remote_state`（state を読まず `attr: "outputs.<名前>"`）、モジュールに渡した provider（`providers` 引数と既定の provider の引き継ぎでたどり、alias の `provider` と `region` を書く）。`ExpectedIrTest` の読み替えを外した。詳細は WORKLOG の「フェーズ2 の手順3」と ir-schema.md の 7.2「TF のモジュール」
      - 第三者レビュー（判定「修正後コミット」）の指摘（M1・R1〜R3・任意1〜3）を直した（コミットはまだ）。alb のリスナーのルール・weighted_forward を写し、`# not-covered:` に入れ子の経路を書けるようにした。eks の KMS は本物どおり `create` 引数（黒箱の `create = false` は `enabled: false`）。ユーザーの許可で terraform-aws-alb v10.5.1・terraform-aws-rds v7.2.2 を取り込み、要約表を本物と突き合わせた（WORKLOG の「フェーズ2 の手順3」の「第三者レビュー」）
      - 見送ったもの: alb の認証のアクション（`authenticate_*`・`jwt_validation`。入力を渡すと `TF-MODULE-SUMMARY-INPUT`）、vpc 5.x・eks 20.x の要約表（ユーザーの決定でフェーズ6 の前に改めて決める。T16・T18 が黒箱のまま）、kms などほかの terraform-aws-modules、`terraform init` 済みの `.terraform/modules` を読むこと
   4. **plan JSON**: `configuration` の参照を優先する。`references` が `aws_subnet.private[0].id`・`aws_subnet.private[0]`・`aws_subnet.private` を重ねて出すので、最も細かいインスタンスの address にまとめる規則を 7.3 に書く。「known after apply」は `$unknown`
   5. **公開サンプルでの確認と完了**: T01〜T20 で落ちない・検査を通ることに加え、TF／SAM の対（T06、T07、T11）の型の多重集合（SELECTION.md の 4 の 3）を確かめ、ir-schema.md の 7.6 を消して 7章を確定し、PLAN と HANDOFF を「フェーズ2 完了」にする
   - 手順1〜3 で見送った小さなこと: `.tf.json`（`TF-TFJSON-UNSUPPORTED` の warn で飛ばす。入れ子のブロックと属性の区別に provider のスキーマが要る。公開サンプルには無い。手順3 でも見送り、plan JSON の `configuration` で区別できるかを見て手順4・5 で決める）、`lifecycle` の `replace_triggered_by`・`provisioner` の中の参照（出さない）、ワークスペースを選ぶ引数（`terraform.workspace` は `"default"`）、リソースの属性の値を設定に書いた値から決めること（`cidrsubnet(aws_vpc.main.cidr_block, …)` は `$unknown`。ir-schema.md の 8章。フェーズ3 で要るかを見る）。`ephemeral`・`check` の中の `data`・override のファイルは手順2 で扱った
   - A5: terraform-aws-modules の vpc／eks／rds／alb の要約表（`via: module_summary`）。要約表に無いレジストリモジュールは黒箱（`module`）、IAM だけのものは H-IAM（手順3 で実装）
   - 完了基準: 同じ構成の TF 版と CFN 版が同じ IR になる（正規化の後）。フェーズ2 ではアダプタの出力を、正解 IR の TF 側の網羅分類と突き合わせるテスト（`tests/test_tf_adapter.py` の `ExpectedIrTest`）で確かめる
   - 主セットの正解 IR は、ツールの出力を見る前に別のサブエージェントが書き、さらに別のサブエージェントがレビューする（CRITERIA.md の 1.2）。
3. フェーズ5 の `export_png.py` は `scripts/lib/drawio_cli.py`（draw.io の探索と `-x -f png --disable-gpu` の呼び出し、0 バイトの失敗扱い、Linux の `--no-sandbox` と `xvfb-run`）を使って作る。draw.io が使えなければ（`DRAWIO` のパスが無いときも）PNG だけスキップして `result.json` に書き、終了コードは 0 のまま。
4. **実行環境の方針は PLAN.md の 1.2、共通 Agent Skill の方針は 1.3（こちらが優先）。** 中心部分は Python だけ、起動は `uv run` の1行、結果は JSON、PNG は環境で切り替え、GitHub の画面からは Actions で PNG を作る、配布はタグ、WSL は Linux の確認用。
5. **フェーズ5 の手前でスパイク（PLAN のフェーズ表の 5a）を行う**: クラウド（Claude Code on the web、Actions の `@claude`、gh-aw）で draw.io＋xvfb と mmdc が動くか、gh-aw で `uv run` を許可する書き方とタグ指定での SKILL の読み込み、VS Code + Copilot と Claude Code on the web で SKILL が読まれるか、Actions の PNG がバイト単位で再現するか。結果は WORKLOG に記録し、PLAN の 1.2・1.3 とフェーズ5・6 を直す。

## 正解 IR と fixture について（実装で分かったこと）
- 正解 IR は TF・CFN で共通の1ファイル。`nodes`・`edges`（canonical 部）は形式によらず同じで、形式ごとの違いは `sources.tf`／`sources.cfn`（網羅分類と辺の根拠）に書く。5種とも canonical 部は TF 版と CFN 版で同じになるように作った。
- ノード ID は `<正規の型名>/<名前>`（名前は Name タグ → 名前属性 → 論理名）。TF 版と CFN 版で名前を揃えてあるので ID が一致する。ARN は使わない。
- three-tier-modules の canonical 部は three-tier と同じ（`validate_ir.py --same-canonical` で確認できる）。
- 開発用の依存は `pyproject.toml`（cfn-lint 1.57.2、jsonschema 4.26.0 など）。`check_coverage.py` は `uv run python ...` で動かす（`uv run check_coverage.py` だと uv のキャッシュの中の cfn-lint のパスが 260 文字を超えて落ちることがある）。
- `tools/iac_inventory.py` は入力を列挙するだけ（評価できるのは単純な count／for_each の式だけ）。本番のアダプタではない。
- Claude のスクラッチパッドに Write で書いたファイルは、Bash／PowerShell からは見えなかった（アプリの仮想化）。シェルで使う一時ファイルは **`%TEMP%` 下の専用フォルダ（例 `%TEMP%\aws-iac-diagram-review`）にシェルで書く**。リポジトリ内や `.git/` の中には置かない。

## 辞書について（実装で分かったこと）
- `Sidebar-AWS4.js` は正規表現で読まず、`scripts/lib/sidebar_harness.js` で Sidebar をスタブ化して Node 上で実行し、登録されたエントリを記録している。
- id の形式は `<kind>:<name>`。kind は `resource_icon`（78x78、resIcon）、`shape`（直接シェイプ）、`group`（grIcon）、`plain_group`（AZ・SG など AWS ステンシルを使わない枠）、`edge`。
- 同じ名前が複数あるときは `#2` などが付く（例: `shape:lambda_function#2` は IoT カテゴリの 78x78 版）。grIcon を共有するグループ（Private／Public subnet）は title から名前を作る。
- Illustrations は title が null で、名前を value に持っている。
- 退役アイコン（`retired: true`）は既定では検索に出ない。

## 壊れたアイコンの検出（C2）について
- 実行: `uv run skills\aws-iac-diagram\scripts\check_icons.py`（約30秒、11ページ）。draw.io Desktop か `Sidebar-AWS4.js` を更新したら再実行する。
- 判定: 空箱・黒塗り・単色（画素の指標）と、ステンシル名だけ存在しない名前にした参照との差分（stencil_missing）。group は差分だけで判定する。閾値の根拠は WORKLOG.md。
- 検出できないもの: 一部だけ欠ける・崩れる壊れ方、別の実在アイコンに置き換わる壊れ方。対象外の kind: edge（ステンシルを参照しない）、plain_group（中が空なのが正常）。辞書ではこれらも `broken: false` だが、「判定していない」という意味である。
- 自己検査: 対照 9 件（壊れ 6 種・正常 3 種。一覧は `check_icons.py` の `controls()`）が期待どおりでなければ終了コード 3 で止まり、辞書を更新しない。draw.io の失敗やマーカーのずれは終了コード 2。
- `broken.json` が正本で、`build_icon_catalog.py` も `check_icons.py` も同じ `write_outputs()` で辞書に反映する。辞書を再生成しても `broken` は消えない。`sidebar_sha256` が今の `Sidebar-AWS4.js` と違えば、build 時に再実行を促す警告が出る。
- 辞書は Sidebar に実在するエントリだけから作っているので、vidanov の言う `dynamodb_table` のような壊れ名はそもそも辞書に無い。今回 0 件だったのはそのため。`check_icons.py` は辞書の元を変えたり draw.io を更新したりしたときの回帰検知として使う。
- 作業ファイル（`.drawio`・PNG・`report.json`）は `aws-iac-diagram-workspace/icon-check/`（git 管理外）。PNG を目で見るとよい。
