# 構成（層・依存の向き・拡張のしかた）

開発者向けの文書です（SKILL の外。配りません）。決めた経緯は [PLAN.md](../PLAN.md) の 1.4。**この文書は階層化の途中（フェーズ 2b）で書いています。** 「R4」「R5」のように印を付けた所は、その手順で中身が変わるので、そのとき書き直します（印は最後の R6 で全部消す）。Terraform の側は R2、CloudFormation の側は R3 で分け終えました（2 の下の「Terraform アダプタの中身」「CloudFormation アダプタの中身」）。

## 1. 全体の形

```
skills/aws-iac-diagram/
├── SKILL.md
├── references/            エージェントが読む文書（R4・R6 で data/ と分ける）
├── assets/                vendor（draw.io の Sidebar-AWS4.js）
└── scripts/
    ├── doctor.py  validate_ir.py  find_aws_icon.py     入口（直下）
    ├── adapt_tf.py  adapt_cfn.py                         アダプタの入口（本体は aws_iac_diagram/adapters/{terraform,cloudformation}/）
    ├── maintenance/                                      辞書の保守用の入口（SKILL.md からは呼ばない）
    │   └── build_icon_catalog.py  check_icons.py  sidebar_harness.js
    └── aws_iac_diagram/                                  中身のパッケージ（層）
        ├── core/  adapters/{terraform,cloudformation}/  normalize/  layout/  emit/  validate/  icons/  platform/
```

- **入口のスクリプト**は引数の処理（終了コードとエラーの文言も）と、パッケージの関数の呼び出しだけをする。PEP 723 の宣言を持ち、`uv run <パス>` の 1 行で動く（どのフォルダからでも、日本語やスペースを含むパスに置いても）。
- **パッケージ `aws_iac_diagram`** は入口からだけ読まれる。入口は先頭で、自分の場所から `scripts/` を `sys.path` の先頭に入れる（`sys.path.insert(0, str(Path(__file__).resolve().parent...))`。`scripts/` の直下の入口（`adapt_tf.py`・`adapt_cfn.py` を含む）は `.parent`、`maintenance/` の入口は `.parent.parent`）。この 1 行だけが入口とパッケージの接点で、ほかの方法（ヘルパーの import、`PYTHONPATH`、`pip install`）は使わない。
- パッケージの中の import は絶対名（`from aws_iac_diagram.core import ir_raw`）で書く。
- **`aws_iac_diagram/` のフォルダ自体を `sys.path` に入れない（その中で `python` を動かさない、`python -m` の作業フォルダにしない）。** 層の名前 `platform` が標準ライブラリの `platform` を隠すため（PLAN の 1.4 の層の名前なので残してある）。`sys.path` に入れるのは `scripts/` だけ。テスト（`tests/test_architecture.py` の `STDLIB_ALLOW`）は、標準ライブラリと同じ名前を許すのを `platform` の 1 つだけにし、新しいフォルダ・モジュールの名前が標準ライブラリと重なると失敗する。

## 2. 層

| 層 | 中身 | 状態 |
|---|---|---|
| `core` | raw IR の部品（印・パス・正規化の共通処理）`ir_raw.py`、診断コードの一覧 `diagnostics.py`（下の「診断コードの一覧」） | `ir_raw.py`・`diagnostics.py`（R3） |
| `adapters/terraform` | Terraform アダプタの中身（下の「Terraform アダプタの中身」）。入口は `scripts/adapt_tf.py` | 済み（R2） |
| `adapters/cloudformation` | CloudFormation アダプタの中身（下の「CloudFormation アダプタの中身」）。入口は `scripts/adapt_cfn.py` | 済み（R3） |
| `adapters`（`registry.py`） | 入力の形式 → アダプタのパッケージ名の表。形式を見分けて振り分ける処理は後で足す | 名前の表だけ |
| `normalize` | 正規化（型別の表、A1〜A3、AZ の挿入、SG を辺に変換） | 空。フェーズ 3 |
| `layout` | 配置（枠と階層のグリッド計算、候補のスコア） | 空。フェーズ 4 |
| `emit` | 出力（`drawio.py`・`mermaid.py`・`png.py`） | 空。フェーズ 4・5 |
| `validate` | 検証（IR、`.drawio` の重なり・貫通） | 空。今の IR の検査は `scripts/validate_ir.py` にある（中身を移すのはフェーズ 4・5） |
| `icons` | アイコン辞書の読み込みと検索 | 空。今の検索は `scripts/find_aws_icon.py` にある |
| `platform` | 環境（draw.io の探索と呼び出し） | `drawio_cli.py` のみ。環境の確認（`doctor.py` の中身）はフェーズ 5 で寄せる |

### Terraform アダプタの中身（`aws_iac_diagram/adapters/terraform/`。R2 で分けた）

入口 `scripts/adapt_tf.py` は引数の処理・終了コード・エラーの文言だけで、`build.build_raw`（か `build_from_plan`）を呼んで JSON を書く。1 回の読み込みの流れは、`build.py` が `Context`（診断・リソース・参照の入れ物）と、ルートの `ModuleEval` を作り、`.tf` を読み（`module_load`）、変数を重ね（`module_vars`）、ブロックを評価して出す（`module_emit` → `module_props` → `module_expr`）。`count`・`for_each` とモジュールの呼び出しの展開は `module_expand`。plan JSON が絡む入力は `plan/`。

| ファイル | 行数 | 役割 |
|---|---|---|
| `build.py` | 128 | `build_raw`・`build_from_plan`・`dump`（入口が呼ぶ）。変数のファイルの探し方 |
| `module_eval.py` | 85 | `ModuleEval` 本体: 6 つのミックスインを束ね、状態（`__init__`）と `diag`・`add_ref` を持つ |
| `module_load.py` | 151 | `.tf`（か要約表の HCL）を読み、ブロックを集める。override の重ね方 |
| `module_vars.py` | 358 | 変数・local・output の値、type の変換、sensitive、子のモジュールの変数と出力 |
| `module_expand.py` | 272 | `count`・`for_each` の展開、モジュールの呼び出し（ローカル・要約表・黒箱）のインスタンス |
| `module_expr.py` | 662 | 式の評価（演算、条件式、for 式、関数の呼び出し、参照、添字、テンプレート）と pruned の参照の集め方 |
| `module_props.py` | 136 | 評価した値を props の印にする。ブロックの本体（dynamic を含む） |
| `module_emit.py` | 281 | リソースの出力（インスタンスごと）、provider・region、depends_on、要約表に写していない入力の診断 |
| `model.py` | 108 | `Block`・`Instances`・`Context`・`ModObj` などのデータの型、メタ引数の集合 |
| `hcl.py` | 395 | 構文木（lark）の道具、heredoc の修正、式・テンプレートの字句 |
| `refs.py`・`addresses.py` | 70・22 | 参照の through・並べ方・重なりの除去／address の添字の付け外し（`.tf` と plan で共通） |
| `evaluator/values.py` | 404 | 値の型（`Res`・`Unknown` など）、変換・比較、`format()` の本体 |
| `evaluator/functions.py` | 763 | 組み込み関数の表（`@fn("名前")`）と `call_function` |
| `modules/sources.py`・`summaries.py`・`resolve.py` | 46・97・85 | source の見分け／要約表（A5）の読み込み／版の選択と黒箱 |
| `plan/read.py`・`reader.py` | 215・601 | plan JSON を読み形を確かめる／`PlanReader`（インスタンスとモジュールを集める） |
| `plan/values.py`・`addresses.py`・`masking.py`・`consistency.py`・`diagnostics.py`・`raw.py`・`combine.py` | 183・65・72・59・10・78・273 | unknown・sensitive の印を持つ値／plan の address／sensitive の伏せ字／props と参照の整合／診断の部品／plan だけから raw IR／`.tf` と合わせる |

- **ミックスインは状態を持たない。** `ModuleEval` の属性はすべて `module_eval.py` の `__init__` に書く（ミックスインのメソッドは `self.xxx` で互いを呼ぶ）。ミックスインは `module_eval.py` を実行時には import しない（子のモジュールは `type(self)(…)` で作る。型の注釈のためだけに `TYPE_CHECKING` で import する）。
- **adapters/terraform の中の順序**（`tests/test_architecture.py` の `TERRAFORM_GROUPS`・`INTRA_TERRAFORM`。下の表と同じで、食い違うとテストが落ちる）: ファイルを次のグループに分け、**グループのあいだでは表の「import してよいグループ」にある向きだけ**を許す（同じグループの中は常に可。グループの中のファイルの順序は見ない）。表に無いファイルを足すと失敗する（グループを決める）。`if TYPE_CHECKING:` の中の import は実行されないので数えない（型の注釈のために `module_eval` を読むものがある）。今の実際の import と同じ最小の辺だけを書いてある。

<!-- terraform-order:begin -->
| グループ | 中身 | import してよいグループ |
|---|---|---|
| `evaluator` | `evaluator/`（値の型と組み込み関数） | （なし） |
| `base` | `hcl`・`model`・`addresses`・`refs` | `evaluator` |
| `modules` | `modules/`（source・要約表・版の選択） | （なし） |
| `mixins` | `module_load`・`module_vars`・`module_expand`・`module_expr`・`module_props`・`module_emit` | `base` `evaluator` `modules` |
| `module_eval` | `module_eval` | `base` `mixins` `modules` |
| `build` | `build` | `base` `evaluator` `module_eval` `plan` |
| `plan` | `plan/`（plan JSON） | `base` |
<!-- terraform-order:end -->

  つまり、`evaluator/`・`modules/` はほかの Terraform のファイルを import せず、`plan/` は `evaluator/`・`modules/`・`module_*` を import せず（`base` だけ）、入口の `adapt_tf.py` だけが `build`・`plan/read` を読む（入口はこの表の外。パッケージ全体の決まりは 3 の表）。
- モジュールの属性を直接書き換えるテスト（`mock.patch.object`）は、使われる側のモジュールに当てる（`plan/read.py` の `MAX_PLAN_BYTES`・`_read_json`、`modules/summaries.py` の `SUMMARY_FILE`）。移したときは、当てた先が実際に使われているか（当てたのに落ちない、が無いか）を変異で確かめる。

### CloudFormation アダプタの中身（`aws_iac_diagram/adapters/cloudformation/`。R3 で分けた）

入口 `scripts/adapt_cfn.py` は引数の処理（`--param`・`--param-file`）・終了コード・エラーの文言だけで、`build.build_raw` を呼んで JSON を書く。1 回の読み込みの流れは、`build.py` が `Context`（診断・リソース・参照・Export の入れ物）を作り、テンプレート（か cdk.out の各スタック）ごとに `StackEval` を作る（`loader` が YAML／JSON を読む）。`StackEval` が Resources を 1 つずつ評価し（`Evaluator.eval` が組み込み関数を、`sam` が Globals と暗黙の API を）、ネストスタックの子は `nested` が必要になったときに展開する。最後に `build.py` が参照の重なりを除いて raw IR にまとめる。

| ファイル | 行数 | 役割 |
|---|---|---|
| `build.py` | 88 | `build_raw`（入口が呼ぶ）・`dump`。最上位のスタックを作り、子を先に展開し、参照・診断をまとめて raw IR にする |
| `stack.py` | 116 | `StackEval`: リソースを 1 つずつ評価し（Condition → enabled、SAM の Globals、暗黙の API、DependsOn）Context に入れる。ミックスインを束ねる |
| `evaluator.py` | 136 | `Evaluator`: 評価の入れ物（状態は `__init__` に集める）、診断、参照の記録、`eval`（組み込み関数への振り分け）。4 つのミックスインを束ねる |
| `intrinsics.py` | 191 | `IntrinsicsMixin`: Ref・GetAtt・Sub・Join・Select・Split・FindInMap と擬似パラメータ |
| `conditions.py` | 102 | `ConditionsMixin`: Conditions の 3 値（真／偽／決まらない）の評価と Fn::If。リソースの enabled の組み合わせ（`weaker`・`stronger`） |
| `params.py` | 78 | `ParametersMixin`: テンプレートの Parameters の評価（外から渡す値 → 親から渡された値 → Default）。`--param-file` の読み込み |
| `foreach.py` | 92 | `ForEachMixin`: Fn::ForEach の展開（プロパティの中と、Resources・Outputs の中） |
| `nested.py` | 117 | `NestedMixin`: ネストスタックの子テンプレートの場所（TemplateURL の読み替え）・展開・出力のたどり方 |
| `outputs.py` | 61 | `OutputsMixin`: スタックの Outputs の評価、Export・ImportValue |
| `marks.py` | 74 | 値の中の `$res` の印と、一時的な印（`__fn`・`__through`）の付け外し |
| `refs.py` | 77 | 参照の集め方: 評価しない値の静的な参照、評価した値からの active の参照、重なりの除去 |
| `loader.py` | 82 | YAML の短縮タグ（!Ref など）を長い形にする `_Loader`、`load_template`、YAML 1.1 の真偽値を名前に戻す `bool_name` |
| `sam.py` | 41 | SAM の Globals の混ぜ方、暗黙の API を作る関数の見分け方 |
| `cdk.py` | 57 | cdk.out の manifest.json からスタックを集める（入れ子のアセンブリを含む） |
| `model.py` | 64 | 定数（印・関数の名前の集合・正規表現）と `Context` |

- **ミックスインは状態を持たない。** 評価の状態は `Evaluator.__init__`（テンプレート 1 つ分）と `StackEval.__init__`（スタックの入れ物: `ctx`・`children`・`outputs` など）に書く。ミックスインのメソッドは `self.xxx` で互いを呼ぶ。`StackEval(NestedMixin, OutputsMixin, Evaluator)` の順は意味がある（`Evaluator` の `stack_output`・`import_value` を上書きするため。`NestedMixin.stack_output` の `super()` は `Evaluator` に届く）。ミックスインは `stack.py` を実行時には import しない（子のスタックは `type(self)(…)` で作る。型の注釈のためだけに `TYPE_CHECKING` で import する）。
- **adapters/cloudformation の中の順序**（`tests/test_architecture.py` の `CLOUDFORMATION_GROUPS`・`INTRA_CLOUDFORMATION`。下の表と同じで、食い違うとテストが落ちる）: Terraform と同じ決まり。グループのあいだでは「import してよいグループ」の向きだけを許し（同じグループの中は常に可）、表に無いファイルを足すと失敗する（グループを決める）。`if TYPE_CHECKING:` の中の import は数えない。今の実際の import と同じ最小の辺だけを書いてある。

<!-- cloudformation-order:begin -->
| グループ | 中身 | import してよいグループ |
|---|---|---|
| `base` | `loader`・`model`・`marks`・`refs`・`sam`・`cdk` | （なし） |
| `mixins` | `params`・`conditions`・`intrinsics`・`foreach`・`outputs`・`nested` | `base` |
| `evaluator` | `evaluator` | `base` `mixins` |
| `stack` | `stack` | `base` `mixins` `evaluator` |
| `build` | `build` | `base` `stack` |
<!-- cloudformation-order:end -->

  つまり、`base` の関数は評価の本体を知らず、ミックスインは `evaluator`・`stack`・`build` を import せず、入口の `adapt_cfn.py` だけが `build`・`params` を読む。
- CloudFormation の側の `base` に置いた `model.py` の `Context` は、`StackEval` を型の注釈にだけ使う（`TYPE_CHECKING`）。

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
- パッケージの中から入口のスクリプトを読まない。入口どうしも読み合わない（`scripts/` の直下と `maintenance/` のすべての入口の名前が対象。共通の処理はパッケージに置く。無くなった入口のフォルダ `adapters`・`lib` の名前の import も入口の import と数える）。例外は `tests/test_architecture.py` の `ENTRY_IMPORT_ALLOW` に理由を付けて書いたものだけで、今は `maintenance/check_icons.py` → `build_icon_catalog`（辞書の書き出しの共有）の 1 つ。辞書の読み書きを `icons` 層に移すときに外す。
- パッケージの中で動的な import（`importlib`、`__import__`）と `exec`・`eval` の呼び出しをしない（静的な import の検査をすり抜けるため）。
- 層どうしが循環しない。

向きを変える・層を足すときは、テストの `ALLOWED` とこの表を同じコミットで直し、理由をコミットメッセージに書きます。

### 診断コードの一覧（`core/diagnostics.py`。R3 で作った）

アダプタが出す診断コード（raw IR の `diagnostics[].code`。Terraform の `TF-…` 43 個、CloudFormation の `CFN-…` 19 個）は、`core/diagnostics.py` の 1 つの表にある。コードごとに、出うる level（`error`＞`warn`＞`info`。場所によって level を変えるコードがある）と短い説明を持つ。データだけで、アダプタは実行時には読まない（出力のバイト列を変えないため。コードは各アダプタが文字列で書いたまま）。

- **コードを足すとき:** `core/diagnostics.py` の表に 1 行、`references/ir-schema.md` の 7.5 の一覧に 1 項目（CFN は「`コード`（level。説明）」の形）を、同じコミットで足す。コードは 1 つの文字列で書く（`"TF-" + 名前` や `f"TF-{x}"` のように組み立てない）。
- **テストが守ること**（`tests/test_architecture.py` の `DiagnosticRegistryRuleTest`）: ① `scripts/adapt_*.py` と `aws_iac_diagram/adapters/` の下の `TF-…`・`CFN-…` の文字列（`^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$`）がすべて表にある、② 接頭辞で始まるのにコードの形でない文字列（組み立て、打ち間違い）が無い、③ 表のコードは、どこかで出されている（コードの集合 `{…}` や比較 `== "…"`・`in (…)` だけの位置は数えない）。使われないコードを残すときは `UNUSED_ALLOW` に理由を書く（今は空）、④ コードのそばに `"warn"` などの level が直接書いてあれば、表の levels にある。
- `tests/test_diagnostics.py` が守ること: 表の形（コードの形、接頭辞、重い順の levels、説明、並び）、表と ir-schema.md の 7.5 が TF・CFN の両方で同じ、アダプタを実際に動かして出た (code, level) が表にある（fixture と、error になる入力）。
- 限界: 範囲は入口のアダプタと `adapters/` の下だけ（`NORM-…` は正規化の層ができるときに範囲を広げる）。level を変数で渡すところ（`Unknown` の既定の level など）の level は静的には見られないので、動かして確かめるテストが受け持つ。`"TF" + "-X"` のような、接頭辞が単独の文字列になっていない組み立ては見つけられない。

## 4. 1 ファイルの大きさ

`scripts/` の下の `.py` は、800 行を超えたら注意（テストが印字するだけ）、1,500 行を超えたら失敗です。超えるファイルは、`tests/test_architecture.py` の `EXEMPT` に日付・理由・外す手順を付けて書けます（決めた日の行数を超えて増えたら失敗、1,500 行以内になった免除は消さないと失敗）が、**今の `EXEMPT` は空です（R2 で `adapters/tf.py` と `tf_plan.py` の免除を外した。R3 の `adapters/cfn.py` は免除を作らずに分けた。空であることも `test_no_exemptions_remain` が確かめる）**。800 行を超えるファイルは R3 の後は無く、最大は `adapters/terraform/evaluator/functions.py` の 763 行です。

## 5. 出力の固定（golden）

構成を動かす手順（R1〜R6）は、中身の動きを変えません。`tests/golden/manifest.json` が、アダプタの CLI の出力（raw IR）101 ケースの SHA-256 を固定していて、`tests/test_golden.py` と `aws-iac-diagram-workspace/tools/golden.py` が比べます（自作の fixture、plan JSON、公開サンプルの TF のルート 52、CFN の入力 25）。

- 落ちたら、コードを直します。**`golden.py --update` で通してはいけません。** 調べるには `golden.py --dump <名前> --out <ファイル>` で今の出力を書き、移す前のコミット（`git worktree add` か `git archive`）の同じケースの出力と比べます（名前の一覧は `golden.py --list`）。
- `--update` は、アダプタの動きを意図して変えたとき（フェーズ 3 以降の仕様変更や fixture の追加）だけ、理由をコミットメッセージに書いて使います。既存のケースの hash が変わるとき、ケースが減るときは `--accept-changes` が要ります。`--only` に合うケースが無いと失敗します。
- 入口のスクリプトの場所を変えたとき（R2・R3）は、`golden.py` の `ENTRY` の表を直します。出力（manifest）は変わりません。

## 6. 拡張のしかた

| やりたいこと | すること |
|---|---|
| Terraform の組み込み関数を足す | `evaluator/functions.py` に `@fn("名前")` で足す（構造だけで決まる関数は `structural=True`）。`NOT_EVALUATED` にある名前は評価しない関数。単体テストは `tests/test_tf_adapter.py` の `EvaluatorTest` |
| Terraform の式・メタ引数・リソースの出し方を変える | 式は `module_expr.py`、`count`・`for_each`・モジュールの展開は `module_expand.py`、変数と型は `module_vars.py`、props の印は `module_props.py`、リソースの出力・provider・depends_on は `module_emit.py`。診断コードは `references/ir-schema.md` の 7.5 に書く |
| Terraform の plan JSON の扱いを変える | `plan/`（読み込みは `read.py`、インスタンスの集め方は `reader.py`、`.tf` と合わせるのは `combine.py`） |
| CloudFormation の組み込み関数・Conditions・SAM・ネストスタックの扱いを変える | 関数は `intrinsics.py`（Ref・Sub など）か `conditions.py`、Parameters は `params.py`、Fn::ForEach は `foreach.py`、SAM は `sam.py` と `stack.py` の `run`、ネストスタックは `nested.py`、Outputs・Export は `outputs.py`、cdk.out は `cdk.py`、raw IR のまとめ方は `build.py`。新しいファイルを足したら `CLOUDFORMATION_GROUPS`（テスト）とこの文書の表と `doctor.py` の `REQUIRED_FILES` に足す。診断コードは `core/diagnostics.py` と `references/ir-schema.md` に書く。単体テストは `tests/test_cfn_adapter.py` |
| 入力の形式を足す | `adapters/<名前>/` を作り（`__init__.py` と本体）、`scripts/adapt_<名前>.py`（入口）を足し、`adapters/registry.py` の表に書く。`ALLOWED` とこの文書の表に層を足す。golden にケースを足す（`golden.py --update`。理由を書く） |
| 出力の形式を足す | `emit/<名前>.py` を足す（フェーズ 4・5 から） |
| モジュールの要約表を足す | **R4 以降:** `data/module-summaries/<モジュール>/v<メジャー>.md` を足すだけ。今（R1〜R3）は `references/module-summaries.md` に書く |
| 型の扱いを足す | **R4 以降（フェーズ 3 で表にする）:** `data/rules/` に行を足す |
| 辞書を作り直す | `scripts/maintenance/build_icon_catalog.py`、`check_icons.py`（README の「アイコン辞書」） |
| 診断コードを足す | `core/diagnostics.py` の表に足し、`references/ir-schema.md` の 7.5 にも書く（一覧に無いコードを使う・一覧のコードを使わないとテストが落ちる。`tests/test_architecture.py` と `tests/test_diagnostics.py`）。出力が変わるときは golden も更新する |
