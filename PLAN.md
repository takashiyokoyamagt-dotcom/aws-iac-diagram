# aws-iac-diagram 計画書

- 作成日: 2026-10-14
- 状態: **フェーズ2 完了**（2026-10-26。完了基準の「TF 版と CFN 版が同じ IR」は、ユーザーの決定でフェーズ3 の基準に分けた）。**フェーズ1 完了**（2026-10-17）。CloudFormation アダプタ（入口 `scripts/adapt_cfn.py`、本体 `scripts/aws_iac_diagram/adapters/cloudformation/`）が raw IR を出し、C1（cfn-lint のグラフとの照合、`aws-iac-diagram-workspace/tools/c1_check.py`）は対応の無い辺 0。Terraform アダプタ（入口 `scripts/adapt_tf.py`、本体 `scripts/aws_iac_diagram/adapters/terraform/`。.tf と plan JSON、A4、A5）は、公開サンプルの `.tf` のあるフォルダすべて（248）で error の診断 0（`aws-iac-diagram-workspace/tools/tf_public_check.py`）、自作5構成では正解 IR の TF 側の網羅分類と一致（`ExpectedIrTest`）。評価基準値は [evals/CRITERIA.md](aws-iac-diagram-workspace/evals/CRITERIA.md)。**フェーズ 2b（構成の階層化）は完了**（2026-10-26。R1: 出力の固定、骨組み、`lib/` の移動、依存の向きのテスト。R2: Terraform の分割、行数の免除を空に。R3: CloudFormation の分割、診断コードの一覧 `core/diagnostics.py`。R4: スクリプトが読むデータを `data/`（`schemas/`・`icons/`・`module-summaries/<モジュール>/v<major>.md`）へ、同梱ファイルの場所は `core/paths.py` の 1 か所。R5: テストを `tests/` の `unit/`・`integration/`・`golden/`・`architecture/` と共有の道具 `support/` に分け、置き場の決まりをテストで守る。R6: `SKILL.md` を入口だけにし、`ir-schema.md` を SKILL の外の `docs/spec/ir-schema/` に章ごとに分け、`references/` は規則表 3 つだけにし、`docs/architecture.md` と下の構成図を今の姿に直し、SKILL.md と文書のリンクを守るテストを足した）。層と拡張のしかたは [docs/architecture.md](docs/architecture.md)。**vpc 5.x・eks 20.x の要約表（A5）も完了**（2026-10-26。`data/module-summaries/` にファイルを足しただけで、ローダーと版の選び方のコードは変えていない。T16 の vpc 5.8.1・eks 20.8.5 と T18 の vpc `~> 5.0` は黒箱でなくなった。T18 の eks `~> 19.15.2` は 19.x の表を作らないので黒箱のまま）。次はフェーズ 3（正規化）。実行環境の方針は 1.2、**共通 Agent Skill の方針は 1.3**（1.1・1.2 より優先する）。**WSL での開発と使う環境は 1.5**、構成の階層化は 1.4（2026-10-24）。再開時は [docs/dev-notes/HANDOFF.md](docs/dev-notes/HANDOFF.md) から読むこと
- 目的: Terraform と CloudFormation のコードを読み込み、AWS 構成図を draw.io・Mermaid・PNG の3形式で出力する Agent Skill を作る。1つの SKILL を Claude Code、VS Code + GitHub Copilot、GitHub Agentic Workflows（gh-aw）で共通に使う（1.3）

---

## 1. 確定した要件と決定事項

| 項目 | 決定内容 |
|---|---|
| 入力（Terraform） | `.tf` を python-hcl2 で静的に解析するのが基本（file・props・参照の位置と参照の組は .tf を正本にする）。`terraform show -json` の plan JSON があれば、address・count／for_each の展開・作られるか・値は plan を使い、plan の `configuration` にあって .tf の参照に無い組は `unevaluated` で足す（実装は `scripts/aws_iac_diagram/adapters/terraform/plan/`）。plan JSON だけを渡しても読める |
| 入力（CloudFormation） | YAML と JSON の両方。SAM と CDK の出力（`cdk.out` 配下のテンプレート）も対象 |
| 出力 | `.drawio`（これを正本とする）、`.mmd`（Mermaid）、`.png` の3形式 |
| 置き場所 | 独立した公開リポジトリ（MIT）`takashiyokoyamagt-dotcom/aws-iac-diagram` の `skills/aws-iac-diagram/`。手元では `~/.claude/skills/aws-iac-diagram` と `~/.copilot/skills/aws-iac-diagram` からジャンクションで参照する。ほかのリポジトリやクラウドへはタグを付けて配る（1.3 の 5） |
| インストール（許可済み） | draw.io Desktop（brew cask／winget）、`@mermaid-js/mermaid-cli`（npm）、uv（winget、2026-10-16）。Python のパッケージは uv が入れる。WSL と CI に入れる物（uv、draw.io の deb、xvfb、Chromium）も、2026-10-24 にユーザーがまとめて許可した。同日、WSL での開発に要る Node.js（mmdc 用）・gh・Claude Code も許可した（1.5） |
| ダウンロード（許可済み） | draw.io の `Sidebar-AWS4.js`（Apache-2.0）。awslabs/aws-icons-for-plantuml の Mermaid 用アイコン JSON は、CC-BY-ND-2.0（改変禁止）で、MIT のこのリポジトリに置けないので、同梱しない（2026-10-24 に取り除いた）。Mermaid のアイコンは利用者の環境のアイコンパックを使う |
| ライセンス上の注意 | TerraVision は AGPL-3.0 なので、考え方だけを参考にしてコードは流用しない。awslabs のスキル（Apache-2.0）や vidanov のスキル（MIT）から取り入れた知見は、NOTICE に出典を明記する |

環境の確認結果（2026-10-14、Mac）:
- インストール済み: Node/npm、Python 3.14、PyYAML、gh
- 未インストール: draw.io、mmdc（mermaid-cli）、python-hcl2、terraform、graphviz

### 1.1 Windows への移行（2026-10-15）

開発環境を Windows 11 に移した。Mac と Windows の両方で動くことを前提にする。

| 項目 | Mac | Windows |
|---|---|---|
| draw.io Desktop | `brew install --cask drawio` | `winget install JGraph.Draw`（v32.4.1、`%LOCALAPPDATA%\Programs\draw.io\draw.io.exe`） |
| SKILL の登録 | symlink（`ln -s`） | ジャンクション（`mklink /J`。管理者権限も開発者モードも不要） |
| venv の Python | `.venv/bin/python` | `.venv\Scripts\python.exe`（3.12.10）。**1.3 で `uv run` に置き換えた** |
| PNG 書き出し | `export_png.sh` の予定だった | **`export_png.py` に変更**し、両 OS で同じスクリプトを使う。draw.io の実行ファイルの場所は OS ごとに探す |

- スクリプトは Python で書き、シェルスクリプトは作らない。パスは `pathlib` で扱う。
- 生成するテキストファイルは UTF-8・LF で書く（`newline="\n"`）。git の自動改行変換で C5（バイト単位で同じ出力）が崩れないよう、`.gitattributes` で LF に固定する。
- Windows で確認済み: draw.io `-x -f png --disable-gpu` で PNG が出る。`mmdc` 12.0.0 で architecture-beta の PNG が出る。

### 1.2 実行環境（Windows・GitHub Web UI・WSL）（2026-10-15）

Windows（手元）と GitHub の Web UI（Claude Code on the web、GitHub Actions の `@claude`）の両方で動かす。Web UI 側はどちらも Linux コンテナで動く。

**方針**
1. **中心部分は Python と pip パッケージだけで動かす。** IaC 解析 → IR → 正規化 → 配置 → `.drawio`／`.mmd` の出力 → 検証（validate.py）の間は外部アプリ（draw.io、mmdc、terraform など）を呼ばない。どの環境でも正本の `.drawio` は必ず出せる。外部アプリを使うのは、中心部分の後に任意で行う次の2つだけ。
   - PNG の書き出し（draw.io。下の 2）。PNG は `.drawio` から作る。
   - `.mmd` の描画確認（mmdc。`.mmd` が Mermaid で描けるかを PNG に書き出して確かめる。この PNG は成果物にしない）。mmdc が無い・動かないときは、この確認だけスキップして報告する。
2. **PNG の書き出しは環境で切り替える。**
   - Windows／Mac: 手元の draw.io Desktop を使う（いまの `drawio_cli.py` のまま）。
   - Linux: draw.io を `xvfb-run` と `--no-sandbox` 付きで動かす。`drawio_cli.py` に画面の有無の判定（`DISPLAY`／`WAYLAND_DISPLAY`）と、画面が無いときの `xvfb-run -a` の付与を足す。画面があっても xvfb を使う指定（環境変数か引数。名前は仮）も設ける。
   - draw.io が使えなければ PNG だけ飛ばして知らせ、全体は失敗にしない（終了コードは 0、報告に「PNG スキップ」と理由を出す）。「使えない」は、見つからない（`DRAWIO` のパスが無いことを含む）・起動できない・タイムアウト・出力が無いか 0 バイトで終わる（2.2 の 12）のいずれか。いまの `drawio_cli.py` は `DRAWIO` のパスが無いとエラーにするので、スキップにする際に合わせて直す。
   - mmdc も Linux では Chromium と `--no-sandbox`（puppeteer の設定ファイルを `-p` で渡す）が要る見込み。
3. **GitHub の画面で使う場合は PNG を GitHub Actions で作る。**
   - `.drawio` がコミットされたら CI が PNG を作り（`.mmd` は描画確認だけ）、コミットするか artifact に置く。
   - CI では draw.io の版、ランナーのイメージ（例 `ubuntu-24.04`）、フォントを固定する（C5 を守る。どれかが違うと PNG の差分が出る）。これでバイト単位で同じ PNG になるかは 5a で試し、駄目なら PNG の基準（バイト一致）を見直す。
   - 同じ GitHub Actions で（ワークフローは別）、Windows と Ubuntu の両方でテストを流す。
   - **コミットする PNG は CI（GitHub Actions の Ubuntu）で作ったものを正本にする**（2026-10-24 のユーザーの決定）。手元の Windows や WSL で作った PNG は確認用で、コミットしない。
4. ~~SKILL はプラグインとして配る。~~ **1.3 の 5 でタグ付きの Skill リポジトリから配ることにし、プラグイン案はやめた**（2026-10-16）。
5. **WSL（Ubuntu）は Linux での動作確認用に使う。** → **1.5 で、WSL を普段の開発の場所に変えた（2026-10-24）。** 下の clone の場所と xvfb の経路の注意はそのまま使う。
   - 普段の開発と SKILL の利用は Windows ネイティブのまま。（1.5 で変更）
   - WSL には uv、draw.io の deb、xvfb、mmdc を入れ、push の前に Linux での動きを試す。
   - 確認用のリポジトリは WSL 側へ clone する（`/mnt/c` 越しはファイル I/O が遅い）。
   - WSL は通常 WSLg で `DISPLAY`／`WAYLAND_DISPLAY` があるので、そのままでは画面ありの経路になり、クラウドや CI と同じ xvfb の経路を通らない。WSL では `DISPLAY`／`WAYLAND_DISPLAY` を外すか、xvfb を使う指定をして画面なしの経路を試す。

**環境ごとの役割と PNG の作り方**

| 環境 | 役割 | `.drawio`／`.mmd` | PNG の作り方 |
|---|---|---|---|
| Windows 11（手元） | 普段の開発、SKILL の利用 | Python だけで生成 | draw.io Desktop（`--disable-gpu`）。mmdc は `.mmd` の描画確認 |
| Mac | 予備の開発環境 | Python だけで生成 | draw.io Desktop。mmdc は `.mmd` の描画確認 |
| WSL（Ubuntu） | push 前の Linux での動作確認 | Python だけで生成（`uv run`。リポジトリは WSL 側へ clone） | draw.io の deb を `DISPLAY`／`WAYLAND_DISPLAY` を外して（または xvfb を使う指定で）`xvfb-run`＋`--no-sandbox` で。`--disable-gpu` も付ける（Windows と引数をそろえる。xvfb には GPU が無い）。mmdc は Chromium＋`--no-sandbox` |
| VS Code + Copilot（Windows） | SKILL の利用（WSL を使わない人も含む）。コマンドは PowerShell 5.1 で実行される | Python だけで生成（`uv run`） | draw.io Desktop（`--disable-gpu`）。無ければ PNG をスキップ |
| Claude Code on the web／Actions の `@claude`／gh-aw | GitHub の画面からの SKILL の利用。コマンドは bash で実行される | Python だけで生成（`uv run`） | 動けば `xvfb-run`＋`--no-sandbox`＋`--disable-gpu`。動かなければ PNG をスキップして報告し、下の CI に任せる |
| GitHub Actions（CI） | PNG の生成、両 OS のテスト | テストで生成して検証 | 版・ランナーのイメージ・フォントを固定した draw.io（Ubuntu は `xvfb-run`）。結果をコミットか artifact に |

**採らない案**

| 案 | 採らない理由 |
|---|---|
| draw.io を使わず、IR → SVG → resvg で PNG を自前で描く | 正本の `.drawio` と見た目がずれ、C6 で採点する対象が二重になる。draw.io がどこでも動かないと分かったときの最後の予備として残す |
| Docker イメージ（drawio-export など）で書き出す | Actions では使えるが、クラウドのセッションで Docker が使えるとは限らない |

**未確認事項**（フェーズ5 の手前のスパイク 5a で小さく試す）
- クラウドの環境（Claude Code on the web、Actions の `@claude`）で draw.io＋xvfb が動くか。apt で入れられるか、ネットワークの制限で deb を取れるか。
- 同じ環境で mmdc（Chromium＋`--no-sandbox`）が動くか。
- gh-aw で、ワークフローの frontmatter に `uv` の実行とネットワーク（`pypi.org`、`files.pythonhosted.org`、`github.com`）の許可を書けば `uv run` が動くか。書き方を README に載せる。
- gh-aw で、このリポジトリの SKILL をタグを指定して読み込めるか（APM の `packages:`、`gh skill install`）。
- VS Code + Copilot で、`~/.copilot/skills/` と `.github/skills/` に置いた SKILL が読まれ、PowerShell 5.1 から SKILL.md の1行のコマンドが動くか。`<SKILL>` を絶対パスに置き換えて実行するか。
- Claude Code on the web で、図を作りたいリポジトリの `.claude/skills/` に置いた SKILL が読まれるか。
- Actions で draw.io の版・ランナーのイメージ・フォントを固定したとき、PNG がバイト単位で同じになるか。
- （1.5 で追加）github.com の画面の Copilot Chat で、SKILL がどこまで使えるか（読めるか、コマンドを実行できるか）。実行できなければ 1.5 の 3 の案内が働くか。
- （1.5 で追加）Copilot coding agent（Issue を割り当ててクラウドで作業するもの）で、SKILL が読まれ `uv run` が動くか。ネットワークの許可（`copilot-setup-steps.yml` やファイアウォールの許可リスト）の書き方。

### 1.3 共通 Agent Skill の方針（2026-10-16）

[docs/skill-cross-platform-guide.md](docs/skill-cross-platform-guide.md)（以下ガイド）に従う。1.1・1.2 と食い違うところは、この節を優先する。

1. **SKILL は1つだけ作る。** `skills/aws-iac-diagram/SKILL.md`（Agent Skills 標準。frontmatter は `name` と `description` だけ）を、Claude Code、VS Code + Copilot（Windows）、gh-aw で共通に使う。2026-10-24 に、GitHub Copilot Chat の3つ（VS Code の中、github.com の画面、coding agent）を対象に加えた（1.5）。
2. **エージェントに実行させるのは、OS とシェルに依存しない1行のコマンドだけにする。** 形は `uv run "<SKILL>/scripts/<名前>.py" --<引数> ... --out <ファイル>`。`&&`、パイプ、リダイレクト、`grep`、`$VAR` などは SKILL.md に書かない。処理はすべて Python のスクリプトの中で行う。
3. **起動は `uv run` に統一する。** 依存は各スクリプトの先頭に PEP 723 で書く（版は `==` で固定し、C5 のために揃える）。`.venv`＋`requirements.txt` はやめ、開発用の環境（単体テスト・fixture の検証）は `pyproject.toml` と `uv.lock` にする。
4. **結果はファイル（JSON、UTF-8・LF）で受け渡し、終了コードの意味を決める。** 0 = 成功（PNG や描画確認のスキップは結果の JSON に書き、0 のまま。1.2 の 2）、1 = 検証で問題が見つかった、2 = 実行エラー（`error` を JSON に書く）。PowerShell 5.1 で標準出力を受けると文字コードが変わるため、標準出力に頼らない。
5. **配布はこのリポジトリからタグ付きで行う。** 使う側は `skills/aws-iac-diagram/` を丸ごと置く（Copilot: `.github/skills/` か `~/.copilot/skills/`、Claude Code: `.claude/skills/` か `~/.claude/skills/`、gh-aw: APM か `gh skill install` でタグを指定）。プラグイン（マーケットプレイス）は使わない。
6. **SKILL のフォルダには実行に要るものだけを置く。** 単体テストはルートの `tests/`、fixture・正解 IR・開発用のツールは `aws-iac-diagram-workspace/` に置く。辞書の保守用のスクリプト（`build_icon_catalog.py`、`check_icons.py`）は `scripts/maintenance/` に置き（2026-10-24 のユーザーの決定。1.4）、SKILL.md からは呼ばない。開発者向けの仕様（docs/spec/ir-schema/ など）は SKILL の外の `docs/spec/` に置く（1.4）。
7. **環境チェックの `scripts/doctor.py` を置く。** OS、Python・uv の版、文字コード、draw.io と mmdc の有無、Linux の画面と `xvfb-run`、`GITHUB_ACTIONS` を JSON で出す。SKILL.md に「失敗したらまず doctor を実行して報告する」と書く。doctor の終了コードは 0 = そろっている、1 = 任意のツール（draw.io、mmdc）が無い、2 = SKILL のファイルが足りないか doctor 自体の失敗（4 の `diagram.py` とは 1 の意味が違う）。
8. **環境ごとの違いは SKILL.md の中で分ける。** `GITHUB_ACTIONS=true`（gh-aw、`@claude`）なら対話的な確認をしない。それ以外は結果を見せ、変更の前に確認を取る。
9. **Claude Code にしかない機能は必須の手順にしない。** C6 の別のサブエージェントによる目視採点や PostToolUse フックは、使える環境でだけ使う。正式な判定は validate.py の数値の検証（重なり・貫通・網羅など）と、[評価基準](aws-iac-diagram-workspace/evals/CRITERIA.md) の半自動の基準（別のサブエージェントか人が判定し、根拠を記録に残すもの。大きいサンプルの抜き取りと点検表、TF／SAM の対の許す違いの一覧）とする。
10. **CI は最初から Windows と Ubuntu の両方で流す**（`.github/workflows/ci.yml`）。Windows では利用者と同じ PowerShell 5.1 から、日本語とスペースを含むパスに置いた SKILL を起動して確かめる。

図を作る入口のコマンド（フェーズ5・6 で作る。名前は仮）:

```
uv run "<SKILL>/scripts/diagram.py" --input <IaC のフォルダかファイル> --out-dir <出力先> [--env <dev など>]
```

出力先に `.drawio`・`.mmd`・`.png`・説明の `.md`・`coverage.md` と、結果の `result.json`（出したファイル、スキップしたもの、検証の結果、ユーザーに確かめたい点）を書く。あいまいな点（環境が複数あるなど）は `result.json` に書いて終了コード 0 で返し、エージェントがユーザーに確かめてから引数を足して再実行する（スクリプトは対話入力を使わない）。

### 1.4 構成の階層化（2026-10-24 にユーザーと合意）

SKILL・関連ファイル・スクリプトが大きくなるのに備え、階層に分けて拡張の余地を残す。**フェーズ2 の完了の後、vpc 5.x・eks 20.x の要約表の前**に、フェーズ 2b として行う（手順4 のレビュー前の変更とファイルの移動が混ざらないように。Windows の CI が通り、出力を固定できる状態から始める）。構成は「リポジトリ構成」の図（3 のあと）。

1. **入口と中身を分ける。** `scripts/` の直下は入口のスクリプトだけ（PEP 723 と引数の処理。`uv run` の1行の起動は 1.3 のまま）。中身はパッケージ `scripts/aws_iac_diagram/`（今の `lib/`・`adapters/` の中身）に置き、`core`・`adapters/{terraform,cloudformation}`・`normalize`・`layout`・`emit`・`validate`・`icons`・`platform` に分ける。
2. **文書とデータを分ける。** `references/` はエージェントが読む文書だけ（手順、`result.json` の読み方）。スクリプトが読むものは `data/`（`schemas/`、`module-summaries/<モジュール>/v<メジャー>.md`、`icons/`、`rules/`）に、1ファイル1単位で置く。開発者向けの仕様（ir-schema を章ごとに分けたもの、規則表の説明）は SKILL の外の `docs/spec/` に移す（ユーザーの決定）。
3. **辞書の保守用のスクリプトは `scripts/maintenance/`**（ユーザーの決定）。SKILL.md からは呼ばない。
4. **テストで守る決まり:** 依存の向き（`core` はほかを読み込まない、アダプタ同士は読み込み合わない、全体をつなぐのは入口だけ。import を読んで確かめる）、1ファイルの行数（目安 800、1,500 を超えたら失敗）、診断コードの一覧（`core/diagnostics.py`。一覧に無いコードを使ったら失敗）。
5. **拡張点:** 入力の形式は `adapters/<名前>/` と `adapters/registry.py`、出力の形式は `emit/<名前>.py`、モジュールの要約表は `data/module-summaries/` にファイルを足す、型の扱いは `data/rules/` に行を足す。`docs/architecture.md` に書く。
6. **移し方:** 中身の動きは変えない。最初に自作の fixture・公開サンプルの TF のルート 52・CFN の 25 の raw IR を固定し（`tests/golden/`）、各手順の後でバイト単位で同じことと、テストがすべて通ることを確かめる。ファイルは `git mv` で移して履歴を残す。手順は R1（出力の固定、骨組み、`lib/` の移動、依存の向きのテスト）、R2（Terraform の分割）、R3（CloudFormation の分割、診断コードの一覧）、R4（`data/` への分割）、R5（テストを `unit/`・`integration/`・`golden/` に分ける）、R6（SKILL.md・references・docs/spec・architecture.md・この PLAN の構成図）。手順ごとに第三者レビューを受ける。

   **状況（2026-10-26）:** R1 は済み。出力は `tests/golden/manifest.json`（101 ケース）に固定し、`lib/` の中身は `scripts/aws_iac_diagram/{core,adapters/terraform,platform}/` に、辞書の保守用は `scripts/maintenance/` に `git mv` した。`scripts/adapters/cfn.py` は R3 まで入口と本体を兼ねた（R1・R2 の間は CLI のパスのまま）。**R2（2026-10-26）:** `scripts/adapters/tf.py` は入口 `scripts/adapt_tf.py`（引数の処理だけ）と `scripts/aws_iac_diagram/adapters/terraform/`（hcl・参照・`module_*`・`evaluator/`・`modules/`・`plan/` の 26 ファイル。最大 763 行）に分けた（旧パスの互換は置かない）。依存の向きは `tests/architecture/test_dependency_direction.py`、行数は `tests/architecture/test_file_size.py` が確かめる（R1 の時点で 1,500 行を超えていた `tf.py`・`tf_plan.py` の免除は、R2 で外して `EXEMPT` は空）。層と拡張のしかたは [docs/architecture.md](docs/architecture.md)。 **R3（2026-10-26）:** `scripts/adapters/cfn.py`（1,327 行）は入口 `scripts/adapt_cfn.py`（引数の処理だけ）と `scripts/aws_iac_diagram/adapters/cloudformation/`（`build`・`stack`・`evaluator`・`intrinsics`・`conditions`・`params`・`foreach`・`nested`・`outputs`・`marks`・`refs`・`loader`・`sam`・`cdk`・`model` の 15 ファイル。最大 191 行）に分け、`scripts/adapters/` は無くなった（旧パスの互換は置かない）。診断コードは `core/diagnostics.py` の 1 つの表（TF 43 個・CFN 19 個）にあり、一覧に無いコードを使う・一覧のコードを使わないとテストが落ちる。 **R4（2026-10-26）:** スクリプトが読むものを `references/` から `skills/aws-iac-diagram/data/` に移した（`schemas/`、`icons/`、`module-summaries/<モジュール>/v<major>.md`。要約表 `module-summaries.md` の説明は `docs/spec/module-summaries.md` へ。規則表 3 つはフェーズ 3 まで `references/` に残す。`ir-schema.md` は R6 で `docs/spec/ir-schema/` に移した）。同梱ファイルの場所は `core/paths.py` の 1 か所。出力が変わったのは、要約表のパスを含む診断の文言だけ（golden の 14 ケースを `--update --accept-changes` で更新。旧い出力のパスを置換すると新しい出力と一致する、という証明つき）。 **R5（2026-10-26）:** `tests/` の直下に平らに置いていたテストを、`tests/unit/`（領域ごとに 1 ファイル）・`integration/`（fixture・公開サンプルを入口や CLI から通す）・`golden/`・`architecture/` と、共有の道具 `tests/support/` に分けた（テストの本文は変えていない）。置き場の決まり（`__init__.py` の置き忘れ、標準ライブラリを隠す名前、文書に書いたテストのパスの実在）はテストで守る。 **R6（2026-10-26）:** `SKILL.md` を入口だけの文書（状態、コマンドの書き方、環境の確認、動くスクリプト、参照先）に直し、`ir-schema.md` を `references/` から `docs/spec/ir-schema/` に移して章ごとの 9 ファイルと目次（`README.md`）に分け（章・節の番号は識別子として変えない）、`references/` は `validate_ir.py` が読む規則表 3 つ（フェーズ 3 で `data/rules/` へ）と README だけにした。`docs/architecture.md` と下の構成図は今の姿に直した。SKILL.md の内容と、Markdown の相対リンク・文書に書いた `docs/…` のパスの実在をテストで守る（`tests/architecture/test_skill_entry.py`・`test_markdown_links.py`）。出力は変えていない（golden 101/101）。2b の完了後、フェーズ 3 より前に、vpc 5.x・eks 20.x の要約表を `data/module-summaries/` にファイルを足して入れた（A5。2026-10-26）。


### 1.5 WSL での開発と、使う環境の広げ方（2026-10-24 にユーザーと合意）

1.1・1.2 と食い違うところは、この節を優先する（1.3 の方針はそのまま）。

1. **普段の開発は WSL（Ubuntu）で行う。** リポジトリは WSL の側（`~/` の下。`/mnt/c` は遅いので使わない）に clone し、VS Code は Remote-WSL で開く。Claude Code・uv・gh・Node.js（mmdc）・draw.io の deb・xvfb・Chromium を WSL に入れる（すべて許可済み）。SKILL の登録は `~/.claude/skills/aws-iac-diagram` から WSL の側のリポジトリへのシンボリックリンク。
2. **移る時期:** HANDOFF の「残りの作業の順番」の 1（Windows の CI の修正）を今の Windows で済ませた後（別のドライブを Windows で再現する必要があるため）。2（手順4 のレビュー）から WSL で進める。
3. **使う環境と、できること:**

   | 環境 | コマンドの実行 | 図の作り方 |
   |---|---|---|
   | VS Code ＋ Copilot（Windows。Copilot Chat のエージェントモード） | ○（PowerShell 5.1） | SKILL.md の1行のコマンド。SKILL は `.github/skills/` か `~/.copilot/skills/` |
   | VS Code ＋ Copilot（Remote-WSL） | ○（bash） | 同じ。Linux の経路（画面が無ければ xvfb） |
   | GitHub Agentic Workflows | ○（Actions の Ubuntu） | 同じ。ネットワークの許可リストに PyPI などを書く。PNG が作れなければ render-png に任せる |
   | Copilot coding agent | ○の見込み（Actions の環境） | gh-aw と同じ条件。5a で確かめる |
   | github.com の画面の Copilot Chat | ×の見込み（読むだけ） | スクリプトを実行できないので図は作らない。SKILL.md に「コマンドを実行できない環境では、図を作る Actions のワークフロー（`diagram.yml`。名前は仮。`workflow_dispatch` で入力のパスを受け、図を artifact かコミットで返す）か coding agent を案内する」と書く。5a で確かめ、できることが分かれば広げる |

4. **Windows でしか分からないことは、CI と手での確認で守る。** WSL では、PowerShell 5.1 の文字コード、日本語とスペースを含むパス、パスの長さ、別のドライブ（`os.path.relpath` の D:／C:）を再現できない。CI の Windows のランナーで毎回確かめ、タグを付ける前に Windows の VS Code ＋ Copilot で手で動かす（チェックリストは README に置く）。Windows で試す SKILL は Windows の側の clone かタグから入れる（`\\wsl.localhost\…` を Windows の側から登録しない）。
5. **Linux と Windows の違いをテストで防ぐ:** 大文字と小文字だけが違うファイル名（Windows で衝突する）、改行（`.gitattributes` で LF）、実行権限に頼らない（起動は `uv run` だけ）。
---

## 2. 調査で分かったこと（計画の根拠）

### 2.1 参考事例

- **Classmethod の記事**（https://dev.classmethod.jp/articles/trial-and-error-aws-diagram-agent-skills/ ）
  - アイコン定義と検索スクリプト `find_aws_icon.py` を用意したことで、読み込むトークンが約1/18に減った
  - レイアウトのルールを具体的に書くと品質が安定した
  - スキルを直すたびに同じプロンプトで再生成して比べた
  - それでも出来上がりは「ドラフト止まり」だった
- **awslabs/agent-plugins の deploy-on-aws / aws-architecture-diagram**（Apache-2.0。AWS 公式の Diagram MCP Server の後継）
  - IaC は LLM に直接読ませている
  - 座標も LLM が決めている
  - PostToolUse フックで XML を検証し、決定論的な修正を当てている
  - 重なりの検査はない
- **vidanov/aws-architecture-diagram-skill**（MIT）
  - 壊れるステンシルの代替表を持っている（例: `dynamodb_table` は空の箱になるので `dynamodb` を使う）
  - サービスの改名に対応する表を持っている
  - resourceIcon とそれ以外とで strokeColor の規則が逆になる
- **jgraph/drawio-mcp**（draw.io 公式、Apache-2.0）
  - `drawio --layout` で ELK を使える
  - `libavoid` は頂点を動かさずに辺だけを迂回させる
  - Mermaid から直接 `-e` 付きで PNG を出すとクラッシュするので、一度 `.drawio` を経由する
- **Agents365-ai/drawio-skill**（MIT）
  - 約15ノードを超えたら Graphviz で自動レイアウトする
  - `--tune` で上下方向と左右方向を両方試し、スコアで選ぶ
  - 「目視だけでは幾何学的な欠陥を見逃すし、存在しない欠陥を幻視もする」
- **TerraVision**（AGPL。考え方のみ参考）
  - 型ごとの統合・削除・移動の表を持っている
  - VPC → AZ → Subnet の中間ノードを挿入している
  - SG はポートのラベル付きの辺に変換している
  - TerraVision のリポジトリの `docs/LEARNINGS_DRAWIO_NATIVE.md`（このリポジトリのファイルではない）に多数の失敗知見がある（下の 2.2）
- **InfraMap**（MIT）
  - 型ごとに「ノードにする型」と「辺にする型」の表を持っている
  - 中間の型は1本の辺に畳んでいる
- **cfn-diagram**
  - Ref、GetAtt、Sub、ImportValue を再帰的に集めている（DependsOn は見ていない）
  - SAM の Events は向きを逆にした Invoke 辺として描いている
- **pagopa/dx generate-terraform-module-diagram**
  - Mermaid のアイコンパックを使っている
  - アイコンノードに `classDef` で塗りを付けるとアイコンが隠れる

### 2.2 失敗知見（実装時に必ず守ること）

**アイコンとスタイル**
1. アイコン名は推測しない。`Sidebar-AWS4.js` から機械的に作った辞書だけを使う。`stencils/aws4.xml` から作った名前は壊れる。
2. シェイプには3つの系統があり、それぞれ指定が違う。
   - 直接シェイプ: 48x48、fillColor を指定、`strokeColor=none`
   - resourceIcon: 78x78、`strokeColor=#ffffff`
   - group: grIcon を使う
3. fillColor を省くとアイコンが見えなくなる。

**座標と配置**
4. 子要素の座標は「直接の親」からの相対座標になる。
5. Graphviz のスプライン制御点を waypoint に流用すると、線がコンテナを突き抜ける。`orthogonalEdgeStyle` にして waypoint を置かず、ルーティングは draw.io に任せる。
6. レイアウトを整えるための不可視エッジを、実在の辺として出力しないこと。

**XML の書き方**
7. `<mxfile><diagram><mxGraphModel><root>` の入れ子と、id=0／id=1 のセルは必須。エッジには `mxGeometry` が必要。
8. `background` 属性を付けるとダークモードが崩れる。ラベルの背景を white にしない。
9. XML コメントの中に `--` を書かない。圧縮した XML にしない。
10. 画像を埋め込むときは `data:image/png,<base64>` の形式にする（`;base64` を付けない）。

**書き出し**
11. PNG にするとグループの外が黒くなることがある。全体を覆う背景矩形を最背面に置いて防ぐ。
12. `drawio -x` について
    - サンドボックス内では、何も出力せずに終わることがある
    - `--scale` を付けるとハングするという issue がある（#1774）
    - GPU エラーが出る場合は `--disable-gpu` を付ける
    - 出力サイズが0なら失敗として扱う
    - `--timeout` は v31.5.2 以降で使える

**CloudFormation の読み込み**
13. `!Ref` などの短縮タグは、通常の YAML パーサではエラーになる。awscli の yamlhelper と同じ方式で、`Fn::*` の長い形式に正規化する。

**Mermaid**
14. architecture-beta の組み込みアイコンは5種類しかなく、6〜8ノードを超えると読めなくなる。
15. 存在しないアイコン名は「?」で表示される。
16. GitHub では独自のアイコンパックが効かない。
17. ARN をノードIDにすると壊れる。

### 2.3 調査から導いた設計原則

- **IaC の解析・配置・検証はスクリプトで決定論的に行う。** LLM が担当するのは、判断（あいまいな点の確認）、最終の目視確認、説明文の作成だけにする。ラベルと名前は B3 の規則でスクリプトが決める（2026-10-16、評価基準の 0 の 5 に合わせて「ラベル付け」を LLM の役割から外した）。
- **中間表現（IR、JSON）を正本にする。** draw.io・Mermaid・PNG はすべて IR から生成する。

---

## 3. アーキテクチャ

```
入力の自動判定
 ├ Terraform plan JSON（あれば address・値）  ─┐
 ├ Terraform .tf（python-hcl2）（参照の正本） ─┼→ ① アダプタ → IR（ノード・辺・入れ子・由来）
 └ CloudFormation / SAM / cdk.out             ─┘
 ② 正規化（型別の設定表）: 統合 / 非表示 / 移動、AZ の挿入、関係リソースの辺への変換、SG を辺に変換
 ③ 配置: 枠と階層はスクリプトでグリッド計算。候補を複数作り、スコアで選ぶ（B1）
 ④ 出力: .drawio（正本）、.mmd（アイコン付き版と GitHub 表示用の素の版）、.png
    ├ ①〜④ の .drawio／.mmd までは Python だけ。外部アプリを呼ばない（1.2 の 1）
    └ .png は環境で切り替え（1.2 の 2）: Windows／Mac は draw.io Desktop、Linux は（画面が無ければ）xvfb-run＋--no-sandbox、
      draw.io が使えなければ PNG だけスキップして報告（全体は失敗にしない）。GitHub の画面からは Actions で生成（1.2 の 3）
 ⑤ 検証: XML 構造、アイコンの辞書照合、重なりと貫通の数値判定、IR との突き合わせ、網羅（A6）
 ⑥ LLM: あいまいな点を一括で確認、別のサブエージェントによる目視採点（C6）、説明 .md の作成（ラベルは ③〜④ でスクリプトが決める）
```

### リポジトリ構成

フェーズ 2b の完了時（2026-10-26）の実際の構成。まだ無いものは「予定」と書いた（`render-png.yml` の名前は仮。フェーズ 5 で決める）。層の分け方と依存の向きは [docs/architecture.md](docs/architecture.md)。

```
aws-iac-diagram/                     ← Skill 専用リポジトリ（正本）。タグを付けて配る（1.3 の 5）
├── PLAN.md  README.md  LICENSE  NOTICE  .gitattributes  .gitignore
├── pyproject.toml  uv.lock  .python-version   # 開発用の環境（1.3 の 3）
├── docs/                            ← 開発者向け（SKILL の外。配らない）
│   ├── architecture.md              # 層の分け方、依存の向き、拡張のしかた（1.4）
│   ├── skill-cross-platform-guide.md          # 共通 Agent Skill のガイド（1.3）
│   ├── spec/
│   │   ├── ir-schema/               # IR スキーマ。章ごとの 9 ファイル（01-overview.md … 09-changes-from-v0.1.md）と目次 README.md
│   │   └── module-summaries.md      # 要約表（data/module-summaries/）の説明
│   └── dev-notes/                   # HANDOFF.md（再開用）・WORKLOG.md（作業の経緯）
├── .github/workflows/
│   ├── ci.yml                       # Windows（PowerShell 5.1）と Ubuntu で単体テスト・検証・SKILL の起動（3形式の生成・検証はフェーズ6 で足す）
│   └── render-png.yml               # 【予定・仮】.drawio のコミットで PNG を生成（.mmd は描画確認のみ）（draw.io の版を固定）
├── tests/                           # SKILL のフォルダの外
│   ├── support/                     # 共有の道具（テストは置かない）
│   ├── unit/                        # 領域ごとに 1 ファイル: terraform/（plan/）・cloudformation/・core/・validate/・icons/・host/
│   ├── integration/                 # fixture・公開サンプルを入口のスクリプトや CLI から通す
│   ├── golden/                      # 固定した raw IR（101 ケース）とのバイト単位の比較（1.4 の 6）
│   └── architecture/                # 依存の向き・行数・診断コードの一覧・SKILL.md・文書のリンク・テストの置き場の検査（1.4 の 4）
├── skills/aws-iac-diagram/          ← 配布する SKILL。手元では ~/.claude/skills と ~/.copilot/skills からジャンクション
│   ├── SKILL.md                     # 入口だけ（状態、コマンドの書き方、環境の確認、動くスクリプト）
│   ├── references/                  # エージェントが読む文書。今は README.md と規則表 3 つ（resource-catalog.md・relation-resources.md・edge-rules.md。validate_ir.py が読む。フェーズ 3 で data/rules/ へ）
│   │                                #   【予定】workflow/（図を作る手順、あいまいな点の確かめ方、失敗したとき）、result-json.md（結果の読み方）はフェーズ 6
│   ├── data/                        # スクリプトが読むデータ（1ファイル1単位）
│   │   ├── schemas/                 #   ir.schema.json、ir-raw.schema.json
│   │   ├── module-summaries/        #   terraform-aws-vpc/v5.md・v6.md、alb/v10.md、rds/v7.md、eks/v20.md・v21.md、iam-only-sources.md、NOTICE.md（A5）
│   │   ├── icons/                   #   catalog.json、broken.json、カテゴリ別の一覧（生成物）
│   │   └── rules/                   #   【予定・フェーズ3】型の扱い・関係リソース・辺の規則（A1〜A3）を表にする
│   ├── assets/                      # vendor（draw.io の Sidebar-AWS4.js）など。Mermaid 用のアイコン JSON は同梱しない
│   └── scripts/
│       ├── doctor.py  validate_ir.py  adapt_tf.py  adapt_cfn.py  find_aws_icon.py
│       │                            # ↑入口だけ（PEP 723 と引数の処理）。validate_ir.py・doctor.py・find_aws_icon.py は本体も兼ねている
│       │                            #   【予定】diagram.py（入口の1行のコマンド。1.3。result.json と終了コードを返す）、export_png.py（フェーズ5）
│       ├── maintenance/             # 辞書の保守用。SKILL.md からは呼ばない
│       │   └── build_icon_catalog.py  check_icons.py  sidebar_harness.js
│       └── aws_iac_diagram/         # 中身のパッケージ
│           ├── core/                #   raw IR の部品（ir_raw.py）、診断コードの一覧（diagnostics.py）、同梱ファイルの場所（paths.py）
│           ├── adapters/
│           │   ├── registry.py      #   入力の形式 → アダプタのパッケージの名前の表（形式を見分けて振り分ける処理は【予定】）
│           │   ├── terraform/       #   hcl・参照・module_*（count／for_each の展開を含む）・evaluator/・modules/・plan/
│           │   └── cloudformation/  #   テンプレート・組み込み関数・条件・SAM・ネストスタック・cdk.out
│           ├── platform/            #   draw.io の探索と呼び出し（drawio_cli.py）。環境の確認（doctor の中身）はフェーズ5 で寄せる
│           ├── normalize/           #   【予定・空】フェーズ3
│           ├── layout/              #   【予定・空】フェーズ4
│           ├── emit/                #   【予定・空】drawio・mermaid・png（フェーズ4・5）
│           ├── validate/            #   【予定・空】IR、.drawio（重なり・貫通）。今の IR の検査は scripts/validate_ir.py
│           └── icons/               #   【予定・空】辞書の読み込みと検索。今の検索は scripts/find_aws_icon.py
└── aws-iac-diagram-workspace/
    ├── fixtures/{tf,tf-plan,cfn,public}/…  expected/*.ir.json
    ├── tools/                       # c1_check・check_coverage・golden・tf_public_check・make_plan_json など
    └── evals/                       # CRITERIA.md
```

---

## 4. 精度向上策（ユーザーがおすすめどおり採用）

### A. 図の正しさ
- **A1 関係リソースを辺に変換する**
  - 対象: `aws_lambda_event_source_mapping`、`aws_sns_topic_subscription`、`aws_lb_listener`、`aws_lb_target_group_attachment`、`aws_lambda_permission`、Route53 の alias、EventBridge の target、CloudFront の origin、API Gateway の integration_uri など
  - CloudFormation の同等の型も同じ表で扱う
- **A2 矢印の向きを型の組で決める**
  - Terraform の参照は依存の向きを表し、データの流れとは逆になることがある
  - 「参照元の型 × 参照先の型 → 向き・ラベル」の表で決める
- **A3 確信度を3段階にする**

  | 確信度 | 根拠 | 描き方 |
  |---|---|---|
  | 確定 | 直接の参照 | 実線 |
  | 導出 | A1 の変換、SG から導いたもの | 実線 + ラベル |
  | 推定 | IAM の Resource ARN、環境変数の文字列一致 | 破線 + 凡例。既定では非表示にもできる |

  推定した辺は、根拠を説明 .md に一覧で載せる。
- **A4 変数と条件を評価する**
  - Terraform: tfvars、`*.auto.tfvars`、default、単純な locals
  - CloudFormation: Parameters の default、Conditions、`Fn::If`、`Fn::FindInMap`
  - 環境が複数ある場合は、最初に1回だけユーザーに確認する
- **A5 公開モジュールの要約表を持つ**
  - まず `terraform-aws-modules` の vpc／eks／rds／alb の4つから始める
  - vpc 5.x・eks 20.x の要約表も作る（2026-10-24 のユーザーの決定。T16・T18 を黒箱にしないため。そのタグのソースの取り込みも許可済み）。**済（2026-10-26）**: vpc は 5（v5.21.0 に合わせ v5.8.1 とも突き合わせ）と 6、eks は 20（v20.8.5）と 21 の表がある。eks の 19.x（T18 の `~> 19.15.2`）の表は作らない。eks の 20.x は v20.8.5 でだけ確かめた（それより新しい 20.x は確かめていない）
  - ローカルモジュールは再帰的に読み込む
- **A6 網羅を保証する**
  - 入力の全リソースを「描画 / 統合先 / 非表示（規則ID） / 未知の型」のいずれかに分類し、`coverage.md` に出力する
  - 分類が漏れたリソースがあれば検証エラーにする

### B. 見やすさ
- **B1 配置の候補を複数作り、スコアで選ぶ**
  - 候補: 左右方向と上下方向、同じ階層の中での並び順
  - スコアの指標: 辺の交差数、折れ数、総延長、縦横比
- **B2 詳細度の違う3つのビューを出す**
  - 全体図、ネットワーク図、詳細図
  - 大きい構成は VPC 単位やスタック単位で図を分割する
- **B3 ラベルの付け方**
  - `Name` タグ → `name` 属性 → アドレスの順で採用する
  - 長いものは省略規則で縮める。日本語のラベルも選べるようにする

### C. 検証と評価
- **C1 既存ツールで検算する**: CloudFormation は `cfn-lint --build-graph`（MIT-0）の依存グラフと突き合わせ、差分をレポートする
- **C2 壊れたアイコンを自動検出する**: 辞書の全アイコンを1枚に描画し、画素のばらつきから空箱・黒・単色を判定する。draw.io を更新したら再実行する
- **C3 実在の構成で試験する**（評価フェーズで実施）: `terraform-aws-modules` の examples と、aws-samples の CloudFormation テンプレートを数本使う
- **C4 変異テスト**（評価フェーズで実施）: 入力に機械的な変更を加え、図がそれに追従するかを確認する
- **C5 決定論的な出力**
  - ID はリソースのアドレスから作り、出力の順序を固定する
  - 同じ入力からは同じファイルが出るようにする（git で差分を見られるように）
- **C6 第三者による採点**: 最終の目視確認は、生成したエージェントとは別のサブエージェントが観点表で採点する

### 見送り
- 手で直した座標を、図を作り直したときに保持する機能（Agents365 の sync 相当）。第1版の対象外とする。

---

## 5. フェーズと完了基準

| # | 内容 | 完了基準 |
|---|---|---|
| 0 | ・ツールのインストール（venv、draw.io、mmdc）<br>・symlink の作成<br>・テスト用構成を5種類作る（3層 ALB/ECS/RDS、サーバーレス API GW/Lambda/DynamoDB、VPC+NAT+エンドポイント、モジュール利用、RAG）。それぞれ Terraform 版と CloudFormation 版を用意する<br>・各構成の正解 IR を作る<br>・アイコン辞書を生成し、壊れたアイコンを検出する（C2） | 正解 IR が第三者レビュー済み。辞書の生成と C2 が通る |
| 1 | ・IR スキーマを決める<br>・CloudFormation アダプタ: 短縮タグ、Ref／GetAtt／Sub（`${}`）／ImportValue／DependsOn、SAM の Events、cdk.out<br>・A4（CloudFormation 側の評価）<br>・C1（cfn-lint との突き合わせ） | テストが通る。cfn-lint のグラフの辺のすべてに、アダプタの出力（raw IR）の参照が対応する（CRITERIA の 1.6。2026-10-17 に変更） |
| 2 | ・Terraform アダプタ: 参照は .tf を正本にし、plan JSON の `configuration` にあって .tf の参照に無い組を `unevaluated` で足す（address・count／for_each の展開・値は plan。実装は `scripts/aws_iac_diagram/adapters/terraform/plan/`）<br>・count／for_each のうち値が決まらないものは「×N」として扱う<br>・A4（Terraform 側の評価）<br>・A5（4モジュール） | **完了（2026-10-26）。** raw IR の段階で: 自作5構成の正解 IR の TF 側の網羅分類と一致する（`ExpectedIrTest`）。公開サンプルの TF（T01〜T20、P01〜P04 のルート 52、`.tf` のあるフォルダ 205（vpc 5.x・eks 20.x の元のソースを足した 2026-10-26 の後は 248））がすべて読め、raw IR の検査を通り error の診断が 0。TF／SAM の対（T06、T07、T11 と T01、T05）のリソースの型の多重集合の違いが、理由つきの表と一致する。**「同じ構成の TF 版と CFN 版が同じ IR になる」は正規化の後の比較なので、フェーズ3 の完了基準に分けた**（2026-10-26 にユーザーが決め、CRITERIA.md の 1.1 も2行に分けた。フェーズ2 の時点では、SAM の暗黙のリソースや TF の分割したリソースを、図の形にするまで比べられないため） |
| 2b | 構成の階層化（1.4。2026-10-24 にユーザーと合意）<br>・R1 出力の固定、パッケージの骨組み、`lib/` の移動、依存の向きのテスト<br>・R2 Terraform の分割　・R3 CloudFormation の分割、診断コードの一覧<br>・R4 `data/` への分割　・R5 テストの分け直し<br>・R6 SKILL.md・references・`docs/spec/`・architecture.md・構成図 | **完了（2026-10-26。R1〜R5 は第三者レビューを受けて main に取り込み済み。R6 は実装済みで、レビューを受けて取り込む）。** 中身の動きが変わらない（固定した raw IR とバイト単位で同じ。テストがすべて通る。両 OS の CI が通る）。1.4 の 4 の決まり（依存の向き・行数・診断コードの一覧）をテストが確かめている。この後の vpc 5.x・eks 20.x の要約表は `data/module-summaries/` にファイルを足すだけで入った（2026-10-26） |
| 3 | 正規化: 型別の表、A1、A2、A3、A6、AZ の挿入、SG を辺に変換、B3 | 網羅分類の漏れと重複が0件（CRITERIA の X4。`unknown` は分類として正しい）。正解 IR に対する再現率と適合率が CRITERIA の 1.1・1.2 を満たす。raw IR の参照で分類されないものが0件（CRITERIA の 1.8）。同じ構成の TF 版と CFN 版が同じ IR になる（自作5構成は canonical 部が一致、公開サンプルの TF／SAM の対 T06・T07・T11 は SELECTION.md の 3 の 3 のノードの型・辺の多重集合。フェーズ2 から分けた） |
| 4 | draw.io の出力と配置<br>・相対座標、辺と図形の2レイヤ、背景矩形<br>・B1、B2、C5<br>・ELK が入れ子のコンテナを保てるか試し、採否を決める | CRITERIA の 2.2 を満たす（重なり・はみ出しは0件。辺の貫通は0件で、L4 だけ図1枚ごとに辺の本数の 5% 以下）。同じ入力を再実行してもバイト単位で同じになる |
| 5a | スパイク（1.2 の未確認事項。フェーズ5 の手前で小さく試す）<br>・Claude Code on the web と Actions の `@claude` で、draw.io の deb＋xvfb を入れて `xvfb-run drawio --no-sandbox -x` が動くか<br>・同じ環境で mmdc（Chromium＋`--no-sandbox`）が動くか<br>・gh-aw で `uv run` を許可する frontmatter の書き方と、このリポジトリの SKILL をタグ指定で読み込めるか（APM、`gh skill install`）<br>・VS Code + Copilot（`~/.copilot/skills/`・`.github/skills/`）と Claude Code on the web（`.claude/skills/`）で SKILL が読まれ、1行のコマンドが動くか<br>・Actions で draw.io の版・ランナーのイメージ（例 `ubuntu-24.04`）・フォントを固定して、PNG がバイト単位で同じになるか | 各項目の可否と手順（または動かない理由）が WORKLOG に記録され、1.2 の表とフェーズ5・6 の作業が結果に合わせて直っている |
| 5 | ・Mermaid の出力（アイコン付き版と GitHub 表示用版。ノードが多いときは flowchart に切り替える）<br>・PNG の書き出し（`export_png.py`）と環境による切り替え（1.2 の 2）: draw.io が使えない（見つからない・起動できない・タイムアウト・無出力か 0 バイト）ときは PNG だけスキップして報告し、`.drawio`／`.mmd` は出す。`DRAWIO` のパスが無いときもエラーではなくスキップにする。mmdc が使えないときは `.mmd` の描画確認だけスキップして報告<br>・Linux 対応: `drawio_cli.py` に画面の有無の判定と `xvfb-run`・`--no-sandbox` の付与、xvfb を使う指定（名前は仮）、Linux の既定の場所（`_candidates()` に既にある）の確認と追加。mmdc の puppeteer 設定（`--no-sandbox`）<br>・WSL（Ubuntu）での動作確認（`DISPLAY`／`WAYLAND_DISPLAY` を外すか xvfb を使う指定で、画面なしの経路を通す）<br>・GitHub Actions のワークフロー `render-png`（仮）: `.drawio` のコミットで PNG を生成（`.mmd` は描画確認だけ）してコミットか artifact に。draw.io の版・ランナーのイメージ・フォントを固定<br>・validate.py（必要なら PostToolUse フックも） | ・Windows で3形式とも生成でき、検証が通る<br>・WSL（Ubuntu）で画面なし（xvfb）の経路で3形式とも生成でき、検証が通る<br>・draw.io が無い環境（`DRAWIO` を存在しないパスにする、または PATH と既定の場所から外して試す）で `.drawio` と `.mmd` は出て検証が通り、PNG のスキップが報告され、終了コードは失敗にならない<br>・`render-png` が固定した版・イメージ・フォントで PNG を作り、同じ入力で再実行してもバイト単位で同じになる（5a で再現しないと分かれば基準を見直す）。コミットする PNG は `render-png` が作ったものだけ（1.2 の 3） |
| 6 | ・SKILL.md の仕上げ（骨組みは 2026-10-16 に作成済み。`diagram.py` の手順、`result.json` の読み方、あいまいな点の確認のしかた）<br>・配布: タグ（例 `v0.1.0`）を付け、Copilot・Claude Code・gh-aw での取り込み方を README に書く（1.3 の 5）<br>・CI `ci.yml`（`render-png` とは別のワークフロー）に3形式の生成・検証を足す<br>・評価: C3、C4、C6（使える環境で。1.3 の 9）、3回実行したときのばらつき<br>・第三者レビューのサイクル | ・評価基準（[evals/CRITERIA.md](aws-iac-diagram-workspace/evals/CRITERIA.md)、2026-10-16 確定）を満たす<br>・Windows と Ubuntu の CI で3形式が生成でき、検証が通る<br>・別のリポジトリにタグを指定して取り込み、VS Code + Copilot（Windows）・Claude Code・gh-aw で SKILL を使える（クラウドは 5a で可能と分かったもの）<br>・README と NOTICE を整える |

### 進め方
- 実装はサブエージェントが行い、そのレビューは別のサブエージェントが第三者として行う（ほかのスキルと同じやり方）
- 区切りごとに docs/dev-notes/HANDOFF.md を更新し、main へ反映する

---

## 6. 主な出典
- https://dev.classmethod.jp/articles/trial-and-error-aws-diagram-agent-skills/
- https://dev.classmethod.jp/articles/claude-code-awslabs-aws-architecture-diagram/
- https://dev.classmethod.jp/articles/claude-code-skill-aws-architecture-diagram/
- https://dev.classmethod.jp/articles/claude-code-trying-out-drawio-skill-for-aws-architecture/
- https://github.com/awslabs/agent-plugins/tree/main/plugins/deploy-on-aws
- https://github.com/vidanov/aws-architecture-diagram-skill
- https://github.com/jgraph/drawio-mcp
- https://github.com/Agents365-ai/drawio-skill
- https://github.com/oharu121/oharu-commands-skills-gems
- https://github.com/nirmal84/aws-arch-drawio-plugin
- https://github.com/patrickchugh/terravision（AGPL。参考は考え方のみ）
- https://github.com/cycloidio/inframap
- https://github.com/ljacobsson/cfn-diagram
- https://github.com/awslabs/diagram-as-code
- https://github.com/awslabs/aws-icons-for-plantuml
- https://blog.serverworks.co.jp/cfn-python
