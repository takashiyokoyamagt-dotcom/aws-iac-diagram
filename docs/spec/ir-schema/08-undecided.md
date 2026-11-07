## 8. 決めなかったこと（後のフェーズで決める）

- **複数ビュー（B2）の詳細度:** IR には持たせない。どのノードをどのビューに出すかは、型ごとに規則表の型の行（`data/rules/types/`）の列で決める（フェーズ4。IR を表示の都合で変えないため）。
- **TF のリソースの属性の値を、設定に書いた値から決めるか**（`cidrsubnet(aws_vpc.main.cidr_block, 8, 1)` など。いまは `$res` のまま、関数の引数なら `$unknown`）。図の `cidr` に要るかを、フェーズ3 の正規化で確かめてから決める。
- **TF の `.tf.json` を .tf だけで読むか:** 読まないと決めた（フェーズ2 の手順5。7.2 の「TF のそのほかのブロック」）。HCL の JSON の書き方では、`"ingress": {…}` が入れ子のブロックか、オブジェクトの値の属性かが書き方から決まらず、決めるには provider のスキーマが要る（props の形が .tf と plan JSON で変わる）。公開サンプルに無く、plan JSON と一緒なら正しく読める（plan の `configuration` はスキーマで読んだ後の形）ので、.tf だけのときは警告（`TF-TFJSON-UNSUPPORTED`）に留める。provider のスキーマ（`terraform providers schema -json`）を入力に取るようになれば読める。
- **診断の `code` の一覧:** CFN と TF は 7.5 のとおり確定した。正規化の `NORM-…` はフェーズ3 で決める（手順 3a で使っているもの: `NORM-NAME-FALLBACK`・`NORM-KEY-COLLISION`・`NORM-COND-UNKNOWN`・`NORM-MERGE-TARGET`・`NORM-MERGE-DEPENDS-ON`・`NORM-MERGE-AMBIGUOUS`。一覧への登録は入口 `normalize_ir.py` と一緒に行う）。
- **統合先が見つからない M-\*:** 規則表に「統合先が無いときの H-\*」の規則（設計草案 4.1 の案。ID はまだ決めていない）が無い（規則表は凍結しているので足していない）。フェーズ3 の手順 3a では、統合先が見つからない M-\* は仮の分類（`merged_into`、`into` が空。`validate_ir.py` は通らない）のまま残し、`NORM-MERGE-TARGET`（warn）を出す。規則を足すかは、主セットで件数を見てから決める（2026-11-07 の時点で、自作 10 入力と主セット 12 入力では 0 件）。
- **M-\* の統合先の手がかりとしての DependsOn:** 参照（DependsOn 以外）と名前の一致で決まらないときの最後の手としてだけ使い、統合される側が自分で宣言した DependsOn（外向き）で、候補がちょうど 1 つのときに限る（`NORM-MERGE-DEPENDS-ON`、info）。ほかのリソースから統合される側への DependsOn は使わない（関係の無いリソースが順序のためだけに DependsOn を書くことがあるため）。TF の `opensearch_index` は provider の `url` でしかコレクションを指さず、raw IR には DependsOn しか残らない。
- **ノード ID の重なり**（2章）を解いたときの、TF／CFN の対応表の形（フェーズ3 の正規化で決める。フェーズ2 では、TF／SAM の対の raw IR のリソースの型の多重集合を `tf_public_check.py` で比べるところまで行った。違いはすべて理由つきの表に残っている）。
