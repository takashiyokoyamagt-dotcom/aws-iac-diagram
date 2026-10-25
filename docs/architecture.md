# 構成（層・依存の向き・拡張のしかた）

開発者向けの文書です（SKILL の外。配りません）。決めた経緯は [PLAN.md](../PLAN.md) の 1.4。**この文書は階層化の途中（フェーズ 2b）で書いています。** 「R2」「R3」のように印を付けた所は、その手順で中身が変わるので、そのとき書き直します（印は最後の R6 で全部消す）。

## 1. 全体の形

```
skills/aws-iac-diagram/
├── SKILL.md
├── references/            エージェントが読む文書（R4・R6 で data/ と分ける）
├── assets/                vendor（draw.io の Sidebar-AWS4.js）
└── scripts/
    ├── doctor.py  validate_ir.py  find_aws_icon.py     入口（直下）
    ├── adapters/tf.py  cfn.py                            入口でもあり本体でもある（R2・R3 で入口 adapt_tf.py／adapt_cfn.py と本体に分ける）
    ├── maintenance/                                      辞書の保守用の入口（SKILL.md からは呼ばない）
    │   └── build_icon_catalog.py  check_icons.py  sidebar_harness.js
    └── aws_iac_diagram/                                  中身のパッケージ（層）
        ├── core/  adapters/{terraform,cloudformation}/  normalize/  layout/  emit/  validate/  icons/  platform/
```

- **入口のスクリプト**は引数の処理と、パッケージの関数の呼び出しだけをする。PEP 723 の宣言を持ち、`uv run <パス>` の 1 行で動く（どのフォルダからでも、日本語やスペースを含むパスに置いても）。
- **パッケージ `aws_iac_diagram`** は入口からだけ読まれる。入口は先頭で、自分の場所から `scripts/` を `sys.path` の先頭に入れる（`sys.path.insert(0, str(Path(__file__).resolve().parent...))`。`scripts/` の直下の入口は `.parent`、`adapters/`・`maintenance/` の入口は `.parent.parent`）。この 1 行だけが入口とパッケージの接点で、ほかの方法（ヘルパーの import、`PYTHONPATH`、`pip install`）は使わない。
- パッケージの中の import は絶対名（`from aws_iac_diagram.core import ir_raw`）で書く。

## 2. 層

| 層 | 中身 | 状態 |
|---|---|---|
| `core` | raw IR の部品（印・パス・正規化の共通処理）`ir_raw.py`。診断コードの一覧は R3 で `diagnostics.py` に置く | `ir_raw.py` のみ |
| `adapters/terraform` | Terraform アダプタの中身。今は `tf_eval.py`（式の評価）・`tf_modules.py`（A5 の要約表）・`tf_plan.py`（plan JSON）の 3 ファイル | **R2** で hcl・参照・`evaluator/`・`modules/`・`plan/` に分け、本体（`scripts/adapters/tf.py`）も移す |
| `adapters/cloudformation` | CloudFormation アダプタの中身 | 空。**R3** で `scripts/adapters/cfn.py` から分ける |
| `adapters`（`registry.py`） | 入力の形式 → アダプタのパッケージ名の表。形式を見分けて振り分ける処理は後で足す | 名前の表だけ |
| `normalize` | 正規化（型別の表、A1〜A3、AZ の挿入、SG を辺に変換） | 空。フェーズ 3 |
| `layout` | 配置（枠と階層のグリッド計算、候補のスコア） | 空。フェーズ 4 |
| `emit` | 出力（`drawio.py`・`mermaid.py`・`png.py`） | 空。フェーズ 4・5 |
| `validate` | 検証（IR、`.drawio` の重なり・貫通） | 空。今の IR の検査は `scripts/validate_ir.py` にある（中身を移すのはフェーズ 4・5） |
| `icons` | アイコン辞書の読み込みと検索 | 空。今の検索は `scripts/find_aws_icon.py` にある |
| `platform` | 環境（draw.io の探索と呼び出し） | `drawio_cli.py` のみ。環境の確認（`doctor.py` の中身）はフェーズ 5 で寄せる |

`doctor.py`・`validate_ir.py`・`find_aws_icon.py` は、いまは入口と本体が 1 ファイルです（R1 では動きを変えないため、そのままにした）。本体の部分は、`validate`・`icons`・`platform` が育つフェーズで層に移します。

## 3. 依存の向き

`tests/test_architecture.py` が、`ast` で import を読んで確かめます（実行しません）。下の表が許す向きのすべてで、**表と `ALLOWED`（テスト）は同じでなければならず**、食い違うとテストが落ちます。自分の層の中の import は常に可。入口のスクリプトだけが、どの層でも import できます。

<!-- allowed-edges:begin -->
| 層 | import してよい層 |
|---|---|
| `core` | （なし） |
| `adapters` | `core` |
| `adapters/terraform` | `core` |
| `adapters/cloudformation` | `core` |
| `normalize` | `core` |
| `layout` | `core` |
| `emit` | `core` `layout` `icons` `platform` |
| `validate` | `core` `icons` |
| `icons` | `core` |
| `platform` | `core` |
<!-- allowed-edges:end -->

決まりの要点:

- `core` はほかの層を読み込まない。
- `adapters/terraform` と `adapters/cloudformation` は読み込み合わない。アダプタは `emit`・`layout`・`normalize`・`validate` を読まない（アダプタの出力は raw IR という JSON で、次の段は JSON を読む）。
- `platform`・`icons` は `adapters` を読まない。
- パッケージの中から入口のスクリプトを読まない。入口どうしも読み合わない（共通の処理はパッケージに置く）。
- 層どうしが循環しない。

向きを変える・層を足すときは、テストの `ALLOWED` とこの表を同じコミットで直し、理由をコミットメッセージに書きます。

## 4. 1 ファイルの大きさ

`scripts/` の下の `.py` は、800 行を超えたら注意（テストが印字するだけ）、1,500 行を超えたら失敗です。超えているファイルは、`tests/test_architecture.py` の `EXEMPT` に日付・理由・外す手順を付けて書きます。免除は増やせません（決めた日の行数を超えて増えたら失敗）。1,500 行以内になった免除は、消さないと失敗します。**R1 の時点の免除は 2 つ**（`adapters/tf.py` 2613 行、`adapters/terraform/tf_plan.py` 1558 行）で、**R2 で空にします**。

## 5. 出力の固定（golden）

構成を動かす手順（R1〜R6）は、中身の動きを変えません。`tests/golden/manifest.json` が、アダプタの CLI の出力（raw IR）101 ケースの SHA-256 を固定していて、`tests/test_golden.py` と `aws-iac-diagram-workspace/tools/golden.py` が比べます（自作の fixture、plan JSON、公開サンプルの TF のルート 52、CFN の入力 25）。

- 落ちたら、コードを直します。**`golden.py --update` で通してはいけません。** 調べるには `golden.py --dump <名前> --out <ファイル>` で今の出力を書き、移す前のコミット（`git worktree add` か `git archive`）の同じケースの出力と比べます（名前の一覧は `golden.py --list`）。
- `--update` は、アダプタの動きを意図して変えたとき（フェーズ 3 以降の仕様変更や fixture の追加）だけ、理由をコミットメッセージに書いて使います。既存のケースの hash が変わるときは `--accept-changes` が要ります。
- 入口のスクリプトの場所を変えたとき（R2・R3）は、`golden.py` の `ENTRY` の表を直します。出力（manifest）は変わりません。

## 6. 拡張のしかた

| やりたいこと | すること |
|---|---|
| 入力の形式を足す | `adapters/<名前>/` を作り（`__init__.py` と本体）、`scripts/adapt_<名前>.py`（入口）を足し、`adapters/registry.py` の表に書く。`ALLOWED` とこの文書の表に層を足す。golden にケースを足す（`golden.py --update`。理由を書く） |
| 出力の形式を足す | `emit/<名前>.py` を足す（フェーズ 4・5 から） |
| モジュールの要約表を足す | **R4 以降:** `data/module-summaries/<モジュール>/v<メジャー>.md` を足すだけ。今（R1〜R3）は `references/module-summaries.md` に書く |
| 型の扱いを足す | **R4 以降（フェーズ 3 で表にする）:** `data/rules/` に行を足す |
| 辞書を作り直す | `scripts/maintenance/build_icon_catalog.py`、`check_icons.py`（README の「アイコン辞書」） |
| 診断コードを足す | **R3 以降:** `core/diagnostics.py` の一覧に足す（一覧に無いコードを使うとテストが落ちる）。今は `references/ir-schema.md` の 7.5 に書く（`tests/test_tf_public.py` が照合する） |
