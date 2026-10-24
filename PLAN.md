# aws-iac-diagram 計画書

- 作成日: 2026-10-14
- 状態: **フェーズ1 完了**（2026-10-17）。CloudFormation アダプタ（`scripts/adapters/cfn.py`）が raw IR を出し、C1（cfn-lint のグラフとの照合、`aws-iac-diagram-workspace/tools/c1_check.py`）は対応の無い辺 0。評価基準値は [evals/CRITERIA.md](aws-iac-diagram-workspace/evals/CRITERIA.md)。フェーズ2（Terraform アダプタ、`scripts/adapters/tf.py`）を5つの手順に分けて進めている（手順は HANDOFF の 3a）。実行環境の方針は 1.2、**共通 Agent Skill の方針は 1.3**（1.1・1.2 より優先する）。再開時は [docs/dev-notes/HANDOFF.md](docs/dev-notes/HANDOFF.md) から読むこと
- 目的: Terraform と CloudFormation のコードを読み込み、AWS 構成図を draw.io・Mermaid・PNG の3形式で出力する Agent Skill を作る。1つの SKILL を Claude Code、VS Code + GitHub Copilot、GitHub Agentic Workflows（gh-aw）で共通に使う（1.3）

---

## 1. 確定した要件と決定事項

| 項目 | 決定内容 |
|---|---|
| 入力（Terraform） | `.tf` を python-hcl2 で静的に解析するのが基本。`terraform show -json` の plan JSON があれば、そちらを優先して使う |
| 入力（CloudFormation） | YAML と JSON の両方。SAM と CDK の出力（`cdk.out` 配下のテンプレート）も対象 |
| 出力 | `.drawio`（これを正本とする）、`.mmd`（Mermaid）、`.png` の3形式 |
| 置き場所 | 独立した公開リポジトリ（MIT）`takashiyokoyamagt-dotcom/aws-iac-diagram` の `skills/aws-iac-diagram/`。手元では `~/.claude/skills/aws-iac-diagram` と `~/.copilot/skills/aws-iac-diagram` からジャンクションで参照する。ほかのリポジトリやクラウドへはタグを付けて配る（1.3 の 5） |
| インストール（許可済み） | draw.io Desktop（brew cask／winget）、`@mermaid-js/mermaid-cli`（npm）、uv（winget、2026-10-16）。Python のパッケージは uv が入れる。WSL と CI に入れる物（draw.io の deb、xvfb、Chromium）は未許可で、入れる前にユーザーの許可を得る |
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
   - 手元の Windows で作った PNG と CI で作った PNG のどちらをコミットするかは未決（ユーザーが決める）。
4. ~~SKILL はプラグインとして配る。~~ **1.3 の 5 でタグ付きの Skill リポジトリから配ることにし、プラグイン案はやめた**（2026-10-16）。
5. **WSL（Ubuntu）は Linux での動作確認用に使う。**
   - 普段の開発と SKILL の利用は Windows ネイティブのまま。
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

### 1.3 共通 Agent Skill の方針（2026-10-16）

[docs/skill-cross-platform-guide.md](docs/skill-cross-platform-guide.md)（以下ガイド）に従う。1.1・1.2 と食い違うところは、この節を優先する。

1. **SKILL は1つだけ作る。** `skills/aws-iac-diagram/SKILL.md`（Agent Skills 標準。frontmatter は `name` と `description` だけ）を、Claude Code、VS Code + Copilot（Windows）、gh-aw で共通に使う。
2. **エージェントに実行させるのは、OS とシェルに依存しない1行のコマンドだけにする。** 形は `uv run "<SKILL>/scripts/<名前>.py" --<引数> ... --out <ファイル>`。`&&`、パイプ、リダイレクト、`grep`、`$VAR` などは SKILL.md に書かない。処理はすべて Python のスクリプトの中で行う。
3. **起動は `uv run` に統一する。** 依存は各スクリプトの先頭に PEP 723 で書く（版は `==` で固定し、C5 のために揃える）。`.venv`＋`requirements.txt` はやめ、開発用の環境（単体テスト・fixture の検証）は `pyproject.toml` と `uv.lock` にする。
4. **結果はファイル（JSON、UTF-8・LF）で受け渡し、終了コードの意味を決める。** 0 = 成功（PNG や描画確認のスキップは結果の JSON に書き、0 のまま。1.2 の 2）、1 = 検証で問題が見つかった、2 = 実行エラー（`error` を JSON に書く）。PowerShell 5.1 で標準出力を受けると文字コードが変わるため、標準出力に頼らない。
5. **配布はこのリポジトリからタグ付きで行う。** 使う側は `skills/aws-iac-diagram/` を丸ごと置く（Copilot: `.github/skills/` か `~/.copilot/skills/`、Claude Code: `.claude/skills/` か `~/.claude/skills/`、gh-aw: APM か `gh skill install` でタグを指定）。プラグイン（マーケットプレイス）は使わない。
6. **SKILL のフォルダには実行に要るものだけを置く。** 単体テストはルートの `tests/`、fixture・正解 IR・開発用のツールは `aws-iac-diagram-workspace/` に置く。辞書の保守用のスクリプト（`build_icon_catalog.py`、`check_icons.py`）は当面 `scripts/` に置いたままにし、SKILL.md からは呼ばない。
7. **環境チェックの `scripts/doctor.py` を置く。** OS、Python・uv の版、文字コード、draw.io と mmdc の有無、Linux の画面と `xvfb-run`、`GITHUB_ACTIONS` を JSON で出す。SKILL.md に「失敗したらまず doctor を実行して報告する」と書く。doctor の終了コードは 0 = そろっている、1 = 任意のツール（draw.io、mmdc）が無い、2 = SKILL のファイルが足りないか doctor 自体の失敗（4 の `diagram.py` とは 1 の意味が違う）。
8. **環境ごとの違いは SKILL.md の中で分ける。** `GITHUB_ACTIONS=true`（gh-aw、`@claude`）なら対話的な確認をしない。それ以外は結果を見せ、変更の前に確認を取る。
9. **Claude Code にしかない機能は必須の手順にしない。** C6 の別のサブエージェントによる目視採点や PostToolUse フックは、使える環境でだけ使う。正式な判定は validate.py の数値の検証（重なり・貫通・網羅など）と、[評価基準](aws-iac-diagram-workspace/evals/CRITERIA.md) の半自動の基準（別のサブエージェントか人が判定し、根拠を記録に残すもの。大きいサンプルの抜き取りと点検表、TF／SAM の対の許す違いの一覧）とする。
10. **CI は最初から Windows と Ubuntu の両方で流す**（`.github/workflows/ci.yml`）。Windows では利用者と同じ PowerShell 5.1 から、日本語とスペースを含むパスに置いた SKILL を起動して確かめる。

図を作る入口のコマンド（フェーズ5・6 で作る。名前は仮）:

```
uv run "<SKILL>/scripts/diagram.py" --input <IaC のフォルダかファイル> --out-dir <出力先> [--env <dev など>]
```

出力先に `.drawio`・`.mmd`・`.png`・説明の `.md`・`coverage.md` と、結果の `result.json`（出したファイル、スキップしたもの、検証の結果、ユーザーに確かめたい点）を書く。あいまいな点（環境が複数あるなど）は `result.json` に書いて終了コード 0 で返し、エージェントがユーザーに確かめてから引数を足して再実行する（スクリプトは対話入力を使わない）。

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
  - `docs/LEARNINGS_DRAWIO_NATIVE.md` に多数の失敗知見がある（下の 2.2）
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
 ├ Terraform plan JSON（あれば優先） ─┐
 ├ Terraform .tf（python-hcl2）     ─┼→ ① アダプタ → IR（ノード・辺・入れ子・由来）
 └ CloudFormation / SAM / cdk.out   ─┘
 ② 正規化（型別の設定表）: 統合 / 非表示 / 移動、AZ の挿入、関係リソースの辺への変換、SG を辺に変換
 ③ 配置: 枠と階層はスクリプトでグリッド計算。候補を複数作り、スコアで選ぶ（B1）
 ④ 出力: .drawio（正本）、.mmd（アイコン付き版と GitHub 表示用の素の版）、.png
    ├ ①〜④ の .drawio／.mmd までは Python だけ。外部アプリを呼ばない（1.2 の 1）
    └ .png は環境で切り替え（1.2 の 2）: Windows／Mac は draw.io Desktop、Linux は（画面が無ければ）xvfb-run＋--no-sandbox、
      draw.io が使えなければ PNG だけスキップして報告（全体は失敗にしない）。GitHub の画面からは Actions で生成（1.2 の 3）
 ⑤ 検証: XML 構造、アイコンの辞書照合、重なりと貫通の数値判定、IR との突き合わせ、網羅（A6）
 ⑥ LLM: あいまいな点を一括で確認、別のサブエージェントによる目視採点（C6）、説明 .md の作成（ラベルは ③〜④ でスクリプトが決める）
```

### リポジトリ構成（予定）

`render-png.yml` の名前は仮（フェーズ5 で決める）。

```
aws-iac-diagram/                     ← Skill 専用リポジトリ（正本）。タグを付けて配る（1.3 の 5）
├── PLAN.md  README.md  LICENSE  NOTICE        # HANDOFF.md・WORKLOG.md は docs/dev-notes/
├── pyproject.toml  uv.lock  .python-version   # 開発用の環境（1.3 の 3）
├── docs/skill-cross-platform-guide.md         # 共通 Agent Skill のガイド（1.3）
├── .github/workflows/
│   ├── ci.yml                       # Windows（PowerShell 5.1）と Ubuntu で単体テスト・検証・SKILL の起動（済。3形式の生成・検証はフェーズ6 で足す）
│   └── render-png.yml               # （仮）.drawio のコミットで PNG を生成（.mmd は描画確認のみ）（draw.io の版を固定）
├── tests/                           # 単体テスト（SKILL のフォルダの外）
├── skills/aws-iac-diagram/          ← 配布する SKILL。手元では ~/.claude/skills と ~/.copilot/skills からジャンクション
│   ├── SKILL.md
│   ├── references/
│   │   ├── resource-catalog.md      # aws_* ⇔ AWS::* ⇔ アイコン ⇔ 扱い（描く/統合/非表示/移動）
│   │   ├── relation-resources.md    # 辺に変換する「関係リソース」の表（A1）
│   │   ├── edge-rules.md            # 型の組ごとの向き・ラベル・確信度（A2, A3）
│   │   ├── module-summaries.md      # 公開モジュールの中身の要約（A5）
│   │   ├── layout-guidelines.md
│   │   └── icons/*.md               # カテゴリ別のアイコン定義（生成物）
│   ├── assets/                      # vendor（draw.io の Sidebar-AWS4.js）など。Mermaid 用のアイコン JSON は同梱しない
│   └── scripts/
│       ├── adapters/{tf_plan,tf_hcl,cfn}.py
│       ├── evaluate.py              # 変数・条件の評価（A4）
│       ├── normalize.py  layout.py  emit_drawio.py  emit_mermaid.py
│       ├── diagram.py               # 入口の1行のコマンド（1.3）。result.json と終了コードを返す
│       ├── doctor.py                # 環境チェック（1.3 の 7。済）
│       ├── export_png.py  validate.py  find_aws_icon.py
│       ├── lib/drawio_cli.py        # draw.io の探索と呼び出し。Linux の画面判定と xvfb-run・--no-sandbox の付与（1.2 の 2。済）
│       ├── build_icon_catalog.py    # Sidebar-AWS4.js から辞書を再生成
│       └── check_icons.py           # 全アイコンを描画して壊れたものを検出（C2）
└── aws-iac-diagram-workspace/
    ├── fixtures/{tf,cfn}/…  expected/*.ir.json
    └── evals/
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
| 2 | ・Terraform アダプタ: plan JSON の `configuration` にある参照を優先し、なければ .tf<br>・count／for_each のうち値が決まらないものは「×N」として扱う<br>・A4（Terraform 側の評価）<br>・A5（4モジュール） | 同じ構成の Terraform 版と CloudFormation 版が同じ IR になる |
| 3 | 正規化: 型別の表、A1、A2、A3、A6、AZ の挿入、SG を辺に変換、B3 | 網羅分類の漏れと重複が0件（CRITERIA の X4。`unknown` は分類として正しい）。正解 IR に対する再現率と適合率が CRITERIA の 1.1・1.2 を満たす。raw IR の参照で分類されないものが0件（CRITERIA の 1.8） |
| 4 | draw.io の出力と配置<br>・相対座標、辺と図形の2レイヤ、背景矩形<br>・B1、B2、C5<br>・ELK が入れ子のコンテナを保てるか試し、採否を決める | CRITERIA の 2.2 を満たす（重なり・はみ出しは0件。辺の貫通は0件で、L4 だけ上限以内）。同じ入力を再実行してもバイト単位で同じになる |
| 5a | スパイク（1.2 の未確認事項。フェーズ5 の手前で小さく試す）<br>・Claude Code on the web と Actions の `@claude` で、draw.io の deb＋xvfb を入れて `xvfb-run drawio --no-sandbox -x` が動くか<br>・同じ環境で mmdc（Chromium＋`--no-sandbox`）が動くか<br>・gh-aw で `uv run` を許可する frontmatter の書き方と、このリポジトリの SKILL をタグ指定で読み込めるか（APM、`gh skill install`）<br>・VS Code + Copilot（`~/.copilot/skills/`・`.github/skills/`）と Claude Code on the web（`.claude/skills/`）で SKILL が読まれ、1行のコマンドが動くか<br>・Actions で draw.io の版・ランナーのイメージ（例 `ubuntu-24.04`）・フォントを固定して、PNG がバイト単位で同じになるか | 各項目の可否と手順（または動かない理由）が WORKLOG に記録され、1.2 の表とフェーズ5・6 の作業が結果に合わせて直っている |
| 5 | ・Mermaid の出力（アイコン付き版と GitHub 表示用版。ノードが多いときは flowchart に切り替える）<br>・PNG の書き出し（`export_png.py`）と環境による切り替え（1.2 の 2）: draw.io が使えない（見つからない・起動できない・タイムアウト・無出力か 0 バイト）ときは PNG だけスキップして報告し、`.drawio`／`.mmd` は出す。`DRAWIO` のパスが無いときもエラーではなくスキップにする。mmdc が使えないときは `.mmd` の描画確認だけスキップして報告<br>・Linux 対応: `drawio_cli.py` に画面の有無の判定と `xvfb-run`・`--no-sandbox` の付与、xvfb を使う指定（名前は仮）、Linux の既定の場所（`_candidates()` に既にある）の確認と追加。mmdc の puppeteer 設定（`--no-sandbox`）<br>・WSL（Ubuntu）での動作確認（`DISPLAY`／`WAYLAND_DISPLAY` を外すか xvfb を使う指定で、画面なしの経路を通す）<br>・GitHub Actions のワークフロー `render-png`（仮）: `.drawio` のコミットで PNG を生成（`.mmd` は描画確認だけ）してコミットか artifact に。draw.io の版・ランナーのイメージ・フォントを固定<br>・validate.py（必要なら PostToolUse フックも） | ・Windows で3形式とも生成でき、検証が通る<br>・WSL（Ubuntu）で画面なし（xvfb）の経路で3形式とも生成でき、検証が通る<br>・draw.io が無い環境（`DRAWIO` を存在しないパスにする、または PATH と既定の場所から外して試す）で `.drawio` と `.mmd` は出て検証が通り、PNG のスキップが報告され、終了コードは失敗にならない<br>・`render-png` が固定した版・イメージ・フォントで PNG を作り、同じ入力で再実行してもバイト単位で同じになる（5a で再現しないと分かれば基準を見直す） |
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
