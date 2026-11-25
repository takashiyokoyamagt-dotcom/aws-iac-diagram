# aws-iac-diagram

Terraform（`.tf` と plan JSON）や CloudFormation（YAML／JSON、SAM、CDK の出力）を読み込み、AWS 構成図を作る Agent Skill です。構成図は draw.io・Mermaid・PNG の3つの形式で出力します。

1つの SKILL（[skills/aws-iac-diagram/](skills/aws-iac-diagram/)）を、次の環境で共通に使います。作り方の方針は [docs/skill-cross-platform-guide.md](docs/skill-cross-platform-guide.md) にあります。

- VS Code + GitHub Copilot（Windows。WSL は使わない）
- Claude Code（手元、Claude Code on the web、GitHub Actions の `@claude`）
- GitHub Agentic Workflows（gh-aw。GitHub Actions の Ubuntu ランナー）

**現在は開発中（アルファ）です。** IaC を読み、正規化し、全体図・ネットワーク図・詳細図を `.drawio`・`.mmd`・`.png` で出すところまで動きます（入口は `scripts/make_diagram.py`）。精度と見やすさの評価の数字は下の「評価」にあり、満たしていない基準もそのまま書いています。

非公式のプロジェクトです。AWS、HashiCorp、Anthropic、GitHub、draw.io とは提携しておらず、承認も受けていません。商標はそれぞれの所有者のものです。詳しくは末尾の「ライセンスと注意」を見てください。

## 評価（2026-11-25 時点）

評価基準は [aws-iac-diagram-workspace/evals/CRITERIA.md](aws-iac-diagram-workspace/evals/CRITERIA.md)、測り方と経緯は [docs/dev-notes/WORKLOG.md](docs/dev-notes/WORKLOG.md)。満たしていない基準も隠さずに書きます。読めなかった入力も分母から外していません。

| 項目 | 対象 | 結果 | 基準 |
|---|---|---|---|
| 図の正しさ（CRITERIA 1.1） | 自作 5 構成 × Terraform／CloudFormation（10 入力） | ノード・辺・入れ子・名前・網羅の分類がすべて正解 IR と一致。同じ構成の TF 版と CFN 版の図の中身がバイト単位で一致 | 満たす |
| 図の正しさ（1.2） | 公開サンプルの主セット 12 入力（正解 IR は出力を見ずに別に作成） | ノード・入れ子・名前・網羅 1.000、辺の適合率 1.000、辺の再現率 0.977（足りないのは既知の限界の 1 本） | 満たす |
| TF／SAM の対（1.4） | 3 組 | 3 組とも一致 | 満たす |
| 大きいサンプル（1.3） | T17・T19・C05 | 抜き取りの正しさは 3 入力とも全件正しい。点検表の再現率は T17 ノード 20/20・辺 19/20、C05 20/20・20/20、**T19 は 18/21・17/21 で不合格**（IPAM・RAM・ロググループを非表示にしているため） | T19 が未達 |
| 変異テスト（1.7） | Terraform 12 入力に追加・削除・`count = 0` の 20 変更 | 20/20 が変更の箇所だけに追従 | 満たす（CloudFormation と一部の変更の種類は未対応） |
| 見やすさ（2.2） | 101 入力・約 180 枚 | 重なり・はみ出し・線の貫通・線とラベルの重なりが 0 件、1 枚のアイコンは 40 以下 | 満たす（線の経路は検査のモデルによる。実際の描画は目視で確認） |
| 目視の採点（5 章、C6） | 自作 5 構成・主セット・大きいサンプルの約 40 枚 | 平均 3.85〜4.10（採点者による揺れ）。2 点以下の観点が残る（線の交差、NAT への並走線など） | **未達**（平均 4.0 以上かつ 2 点以下なし） |
| 決定論（3 章） | 101 入力 | 同じ入力から同じ IR・`.drawio`・`.mmd`、Windows と Ubuntu で一致（CI）。PNG は固定した環境で 2 回一致 | 満たす（エージェントを含む 3 回実行は未実施） |
| 規則表の網羅 | 公開サンプル 64 入力 | 型の分からないリソースが 248 件残る（主に T20 の Lake Formation・MSK・DMS など） | 主セットと大きいサンプルは 0 件 |

## リポジトリの構成

```
skills/aws-iac-diagram/   配る SKILL（SKILL.md、scripts/ の入口とパッケージ、data/〈スキーマ・アイコン・モジュールの要約表・規則表〉、references/、assets/）
docs/                     開発者向け（配らない）: architecture.md（層・依存の向き・拡張のしかた）、spec/（IR スキーマを章ごとに、規則表の説明）、dev-notes/
tests/                    unit/ integration/ golden/ architecture/ と共有の道具 support/
aws-iac-diagram-workspace/  fixtures/（自作の入力と公開サンプル）、expected/（正解 IR）、tools/（開発用の道具）、evals/（評価基準）
PLAN.md                   計画（決めたこと、フェーズ、リポジトリ構成の図）
```

SKILL の中身の分け方は [docs/architecture.md](docs/architecture.md) の 1 に、IR の形は [docs/spec/ir-schema/](docs/spec/ir-schema/README.md)、型の扱い・辺の規則（規則表。データは `skills/aws-iac-diagram/data/rules/`）の説明は [docs/spec/rules/](docs/spec/rules/README.md) にあります。

## SKILL を使う

### 必要なもの

| もの | 必須か | Windows | Linux／GitHub Actions |
|---|---|---|---|
| uv | 必須 | `winget install --id=astral-sh.uv -e` | 公式のインストールスクリプト、または `astral-sh/setup-uv` |
| draw.io Desktop | 任意（無ければ PNG だけスキップ） | `winget install -e --id JGraph.Draw` | draw.io の `.deb` と `xvfb` |
| mmdc（`@mermaid-js/mermaid-cli`） | 任意（無ければ `.mmd` の描画確認だけスキップ） | `npm install -g @mermaid-js/mermaid-cli` | 同左（Chromium が要る） |

Python は uv が自動で用意します。スクリプトの依存は各スクリプトの先頭（PEP 723）に書いてあり、`uv run` が自動で入れます。

### 取り込み方

SKILL は、このリポジトリにタグ（例: `v0.1.0`）を付けて配ります。`skills/aws-iac-diagram/` のフォルダを丸ごと、次のどれかに置きます。

| 環境 | 置き場所 |
|---|---|
| VS Code + Copilot | 図を作りたいリポジトリの `.github/skills/aws-iac-diagram/`、または個人用の `~/.copilot/skills/aws-iac-diagram/` |
| Claude Code | 図を作りたいリポジトリの `.claude/skills/aws-iac-diagram/`、または個人用の `~/.claude/skills/aws-iac-diagram/` |
| gh-aw | APM（`shared/apm.md` の `packages:`）か `gh skill install` で、タグを指定して読み込む |

gh-aw では、ワークフローの frontmatter で `uv` の実行と、uv が Python とパッケージを取りに行くネットワーク（`pypi.org`、`files.pythonhosted.org`、`github.com`）を許可してください。これは SKILL ではなくワークフロー側の設定です。書き方はまだ確かめていません（PLAN のスパイク 5a）。

### 図を作る

```bash
uv run "<SKILL のフォルダ>/scripts/make_diagram.py" --input "<.tf のフォルダ・テンプレート・cdk.out・plan JSON>" --out-dir "out/<名前>"
```

`out/<名前>/result.json` に結果のまとめ、`out/<名前>/diagram/` に図と `coverage.md`（入力の全リソースの分類）が出ます。環境が複数ある Terraform（dev・prod など）は、`--var-file` を付けるまで図を作らず、`result.json` の `questions` に選択肢を書きます。使い方の詳細は SKILL.md にあります。

### 環境の確認

うまく動かないときは、次の1行で環境を調べられます（どのシェルからでも同じです）。

```bash
uv run "<SKILL のフォルダ>/scripts/doctor.py" --out "out/doctor.json"
```

終了コードは、0 ならすべてそろっている、1 なら draw.io か mmdc が無い（PNG か描画確認がスキップされる）、2 なら SKILL のファイルが足りないか doctor 自体が失敗した、です。

## 開発

### セットアップ（Windows）

```powershell
winget install --id=astral-sh.uv -e
winget install -e --id JGraph.Draw
npm install -g @mermaid-js/mermaid-cli
uv sync
# 手元の Claude Code と Copilot に開発中の SKILL を登録する（ジャンクション。管理者権限は不要）
cmd /c mklink /J "$HOME\.claude\skills\aws-iac-diagram" "$PWD\skills\aws-iac-diagram"
cmd /c mklink /J "$HOME\.copilot\skills\aws-iac-diagram" "$PWD\skills\aws-iac-diagram"
```

`uv sync` で、単体テストと fixture の検証に使う開発用の環境（`.venv`、依存は [pyproject.toml](pyproject.toml) と `uv.lock`）ができます。SKILL のスクリプトはこの環境を使わず、PEP 723 の宣言だけで動きます。版は両方で揃えてください。plan JSON の fixture を作り直すとき（`aws-iac-diagram-workspace/tools/make_plan_json.py`）だけ使う moto は、既定の環境には入りません（依存グループ `fixtures`。`uv run --group fixtures python ...`。[fixtures の README](aws-iac-diagram-workspace/fixtures/README.md) を見てください）。

macOS では draw.io を `brew install --cask drawio` で入れ、登録は `ln -s` で行います。WSL（Ubuntu）を使う場合は、リポジトリを WSL 側（`~/work/...`）に clone してください。

### テスト

```powershell
uv run python -m unittest discover -s tests -v
```

テストは `tests/` の下に、`unit/`（1 つの領域につき 1 ファイル。`terraform/`・`cloudformation/`・`core/`・`validate/`・`icons/`・`host/`）、`integration/`（fixture・公開サンプルを入口のスクリプトや CLI から通す）、`golden/`（固定した raw IR との比較）、`architecture/`（構成の決まり）に分けてあります。共有の道具は `tests/support/` です（置き場の決まりは [docs/architecture.md](docs/architecture.md) の 7）。1 つの領域だけ動かすには次のようにします。

```powershell
uv run python -m unittest discover -s tests/unit/terraform -t tests -v     # 領域
uv run python -m unittest tests.unit.terraform.test_hcl -v                 # 1 ファイル
uv run python tests/unit/terraform/test_hcl.py                             # ファイルを直接
```

CI（[.github/workflows/ci.yml](.github/workflows/ci.yml)）は Ubuntu と Windows で、単体テスト、正解 IR と fixture の検証、日本語とスペースを含むパスに置いた SKILL の起動（Windows は PowerShell 5.1 から）を行います。

### 構成を守るテスト

構成の階層化（[PLAN.md](PLAN.md) の 1.4。フェーズ 2b で完了）では、中身の動きを変えずにファイルを移しました。層の分け方と依存の向き、拡張のしかたは [docs/architecture.md](docs/architecture.md) です。構成は次のテストが守ります（どれも上の単体テストに入っています）。

- **出力の固定（golden）:** アダプタの出力（raw IR）を、自作 fixture・plan JSON・公開サンプルの TF のルート 52・CFN の入力 25 の 101 ケースについて、SHA-256 で `tests/golden/manifest.json` に固定しています。単独で動かすには `uv run python aws-iac-diagram-workspace/tools/golden.py`（`--list`、`--only <接頭辞>`、不一致の調査には `--dump <名前> --out <ファイル>`）。**落ちたらコードを直します。`--update` で通してはいけません**（アダプタの動きを意図して変えたときだけ、理由を書いて使います）。
- **構成の検査（`tests/architecture/`）:** import を読んで層の依存の向きを、行数（800 行で注意、1,500 行で失敗。免除は今は無い）を、診断コードの一覧（`docs/spec/ir-schema/` の 7.5 との一致を含む）を確かめます。テストのファイルの置き場そのもの（フォルダの名前、行数）、`SKILL.md` の内容（書いたスクリプトとオプションが実在する）、Markdown の相対リンクと文書に書いた `docs/…` のパスの実在も確かめます。

### アイコン辞書の再生成

辞書は `skills/aws-iac-diagram/data/icons/` に出ます（`catalog.json`、カテゴリ別の `.md`、`broken.json`）。

```powershell
uv run skills\aws-iac-diagram\scripts\maintenance\build_icon_catalog.py
uv run skills\aws-iac-diagram\scripts\find_aws_icon.py lambda
```

### 壊れたアイコンの検出（C2）

draw.io Desktop を更新したとき、または `Sidebar-AWS4.js` を取り直したときに実行します。

```powershell
uv run skills\aws-iac-diagram\scripts\maintenance\check_icons.py
```

- 辞書の全アイコン（shape・resource_icon・group）を draw.io で PNG にし、セルごとに「空箱」「黒塗り」「単色」を判定します。さらに、ステンシル名（`resIcon`／`grIcon`／`shape`）だけを存在しない名前にした参照を隣に描いて比べ、画素がほぼ同じもの（グラデーションの正方形だけになる resourceIcon、アイコンの無い group 枠など）を「ステンシル欠落」とします。
- 判定しないもの: edge（矢印でステンシルを参照しない）と plain_group（AZ・SG などの枠で、中が空なのが正常）。
- 検出できないもの: 一部だけ欠ける・崩れる壊れ方と、別の実在アイコンに置き換わる壊れ方。気になるときは作業ディレクトリの PNG を目で見てください。
- 結果は `data/icons/broken.json` に書き、`catalog.json` とカテゴリ別 `.md` に `broken`（と `broken_reason`）として反映します。`build_icon_catalog.py` も `broken.json` を読んでマージするので、辞書を再生成しても消えません。
- `find_aws_icon.py` は既定で broken を除外します。表示するには `--include-broken` を付けます。
- 壊れ方が分かっている対照（存在しないシェイプ名 `dynamodb_table` など）と正常な対照を同じ図に描き、期待どおりに判定されなければ異常終了します（辞書は更新しません）。
- 作業ファイル（`.drawio`、ページごとの PNG、全件の指標 `report.json`）は `aws-iac-diagram-workspace/icon-check/` に出ます（git 管理外）。
- draw.io の場所は自動で探します。見つからないときは環境変数 `DRAWIO` に実行ファイルのパスを設定してください。Linux で画面が無いときは `xvfb-run -a` と `--no-sandbox` を付けて起動します。画面があっても xvfb を使うには `AWS_IAC_DIAGRAM_XVFB=1` を設定します。

### CloudFormation アダプタと C1

CloudFormation のテンプレート（ネストスタック、SAM、cdk.out を含む）から、アダプタの出力（raw IR。[ir-schema](docs/spec/ir-schema/07-raw-output.md) の 7章）を作ります。

```powershell
uv run skills\aws-iac-diagram\scripts\adapt_cfn.py --input aws-iac-diagram-workspace\fixtures\cfn\three-tier\template.yaml --out out\three-tier.raw.json --param EnvType=prod
uv run python skills\aws-iac-diagram\scripts\validate_ir.py out\three-tier.raw.json
```

パラメータの値は `--param KEY=VALUE` か `--param-file`（`aws cloudformation` の CLI の `parameters.json` の形など）で渡します。`AWS::Region` などの擬似パラメータに渡した値は、条件の評価にだけ使います。

C1（[CRITERIA.md](aws-iac-diagram-workspace/evals/CRITERIA.md) の 1.6）は、cfn-lint のグラフの辺のすべてに raw IR の参照が対応するかを調べます。入力を省くと、fixture と公開サンプルの CFN をすべて調べます。

```powershell
uv run python aws-iac-diagram-workspace\tools\c1_check.py
```

### Terraform アダプタ

Terraform のルートモジュール（.tf のフォルダ）から、同じ raw IR を作ります。変数・locals・式を評価し、count・for_each をインスタンスごとに展開します。ローカルモジュール（`./`・`../`）は中身を再帰的に読み、terraform-aws-modules の vpc（5.x・6.x）・alb（10.x）・rds（7.x）・eks（20.x・21.x）は要約表（`skills/aws-iac-diagram/data/module-summaries/`。モジュールと major ごとのファイル。説明は [docs/spec/module-summaries.md](docs/spec/module-summaries.md)）で展開します。呼び出しの `version` の制約が許す major のうち、表のある最も新しいものを使います（`5.8.1`・`~> 5.0` は 5.x、`20.8.5` は 20.x）。表の無い major（vpc の 4.x 以前、eks の 19.x など）・ほかのモジュール・git のモジュールは黒箱の呼び出し1件にします。eks の 20.x の表は v20.8.5 のソースと突き合わせたもので、それより新しい 20.x は確かめていません（docs/spec/module-summaries.md の 3）。どのモジュールも、ネットワークから取りに行きません。`.tf.json` は .tf だけでは読みません（警告 `TF-TFJSON-UNSUPPORTED`。plan JSON と一緒なら plan から取ります）。`terraform.workspace` は `default` で評価し、`--workspace <名前>` で変えられます。

`terraform show -json` の plan JSON も読めます（[ir-schema](docs/spec/ir-schema/07-raw-output.md) の 7.2「TF の plan JSON」）。.tf のフォルダと一緒に渡す（`--plan`）のがおすすめです。address と count・for_each の展開・作られるかは Terraform の結果を使い、ファイル名・値・参照の位置は .tf から読みます（.tf で決まらなかった値は plan の値で埋める）。plan JSON だけ（`--input` に `.json`）でも読めますが、plan JSON は locals・dynamic ブロックの式と .tf のファイル名を持たないので、参照の一部が分からず、`file` は plan JSON の名前になります。

```powershell
uv run skills\aws-iac-diagram\scripts\adapt_tf.py --input aws-iac-diagram-workspace\fixtures\tf\three-tier --out out\three-tier.tf.raw.json --var-file env\dev.tfvars
uv run python skills\aws-iac-diagram\scripts\validate_ir.py out\three-tier.tf.raw.json
# plan JSON と合わせる（変数の値は plan のもの）／plan JSON だけ
uv run skills\aws-iac-diagram\scripts\adapt_tf.py --input aws-iac-diagram-workspace\fixtures\tf\three-tier --plan aws-iac-diagram-workspace\fixtures\tf-plan\three-tier.dev.json --out out\three-tier.plan.raw.json
uv run skills\aws-iac-diagram\scripts\adapt_tf.py --input aws-iac-diagram-workspace\fixtures\tf-plan\three-tier.dev.json --out out\three-tier.planonly.raw.json
```

公開サンプルでの確認（フェーズ2 の手順5）は、`tf_public_check.py` で行います。T01〜T20、P01〜P04 のルート（52 フォルダ）が読めて raw IR の検査を通ること（error の診断が 0）と、TF／SAM の対（T01、T05、T06、T07、T11）のリソースの型の違いが、理由つきの表（`PAIR_EXPECTED`）と一致することを調べます。`--all` は `.tf` のあるフォルダすべて（248。vpc 5.x・eks 20.x の表の元のソースを足した 2026-10-26 から。それまでは 205）を読みます。

```powershell
uv run python aws-iac-diagram-workspace\tools\tf_public_check.py --pairs
uv run python aws-iac-diagram-workspace\tools\tf_public_check.py --all --jobs 4
```

**注意（plan JSON）:** plan JSON そのものには、`sensitive` の変数の値も平文で入ります（Terraform の仕様）。アダプタは plan の `sensitive` の位置の値を raw IR に書かず（.tf と合わせるときも、.tf の評価で値が出た位置を伏せます）、plan JSON のファイルの扱いには気をつけてください。

変数の値は Terraform と同じく、`terraform.tfvars`・`*.auto.tfvars` を自動で読み、`--var-file`（相対パスは作業中のフォルダ、無ければ `--input` のフォルダから）と `--var KEY=VALUE` で渡します（指定した順に後のものが優先）。値の無い変数があると、自動では読まれない `*.tfvars` の候補を診断 `TF-UNRESOLVED-VARS` に書きます。

**注意:** `sensitive` を付けていない変数の値は、raw IR の `props`（図のラベルなど）に入りえます。伏せたい変数には `sensitive = true` を付けるか、`--redact-var <名前>`（何回でも指定できる）を使ってください。`evaluation.vars` には変数の値を書かず、値の出どころ（変数のファイルの名前、`--var`、`default`）だけを書きます。

### 正解 IR と fixture の検証

```powershell
uv run python skills\aws-iac-diagram\scripts\validate_ir.py aws-iac-diagram-workspace\expected\*.ir.json
uv run python aws-iac-diagram-workspace\tools\check_coverage.py --lint
```

`check_coverage.py` は開発用の環境（`uv run python ...`）で動かしてください。`uv run check_coverage.py` だと、Windows では uv のキャッシュの中の cfn-lint のパスが 260 文字を超えて `--lint` が落ちることがあります。

### 規則表

型の扱い・関係リソース・辺の規則（正規化で使う規則表）は、データ（TOML）が `skills/aws-iac-diagram/data/rules/` にあり、説明は [docs/spec/rules/](docs/spec/rules/README.md) にあります。説明の中の表は、データから作った生成物です。データを直したら作り直し、食い違いがないかを調べます。

```powershell
uv run python aws-iac-diagram-workspace\tools\render_rules.py --write
uv run python aws-iac-diagram-workspace\tools\render_rules.py --check
```

fixture の説明は [aws-iac-diagram-workspace/fixtures/README.md](aws-iac-diagram-workspace/fixtures/README.md)、IR の形は [docs/spec/ir-schema/](docs/spec/ir-schema/README.md) にあります。

## ライセンスと注意

- このプロジェクトのコード・文書・テストは、MIT License（[LICENSE](LICENSE)）です。
- 第三者のファイルは MIT の対象外で、それぞれの元のライセンスに従います。一覧は [NOTICE](NOTICE) にあります。特に `aws-iac-diagram-workspace/fixtures/public/`（公開されている Terraform・CloudFormation のサンプル。試験用の入力データ）と `skills/aws-iac-diagram/assets/vendor/`（draw.io の `Sidebar-AWS4.js`、Apache-2.0）です。
- AWS のアイコン（AWS Architecture Icons）は、このリポジトリに同梱していません。図にアイコンを使うときは、[AWS の利用条件](https://aws.amazon.com/architecture/icons/)に従ってください。
- 非公式のプロジェクトです。AWS、Amazon CloudFormation、Terraform、draw.io、Claude、GitHub などの名前は、それぞれの所有者の商標です。
- Terraform の plan JSON や変数のファイルには、秘密の値が入っていることがあります。図や IR を共有する前に、中身を確かめてください。
