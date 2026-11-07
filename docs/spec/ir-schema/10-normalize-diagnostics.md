## 10. 正規化の診断（`NORM-…`）

正規化（`scripts/normalize_ir.py`、`scripts/aws_iac_diagram/normalize/`）が normalized IR の `diagnostics` に書く診断。形は 7.5 と同じ（`level`・`code`・`address`・`message`。`path` は使うときだけ）で、`code` は `NORM-` で始まる（ir.schema.json の pattern）。raw IR の診断（`TF-…`・`CFN-…`）は normalized IR に写さない（raw のファイルに残る）。

```json
{"level": "info", "code": "NORM-NAME-FALLBACK", "address": "aws_vpc.main", "message": "Name タグ・名前属性が無い（か評価できない）ので、論理名 'main' を名前にした"}
```

- `level` の意味は 7.5 と同じ（`info` = 結果に影響しない読み替え、`warn` = 図が不完全・不確かになりうる、`error` = 読めなかった）。`address` は入力のリソースの address（AZ など入力に無いものは使わない）。
- **一覧の正は `scripts/aws_iac_diagram/core/diagnostics.py`**（7.5 と同じ。下の一覧と同じであること、正規化のコードにある `NORM-…` の文字列がそこにあることをテストが確かめる）。
- 状態: フェーズ 3 の手順 4b の時点のもの。辺の段階が育つときに、設計草案の 5.3 の案（使わなかった pruned・unevaluated の参照など）を足す（章・節の番号は変えない）。
- 正規化の `code` の一覧（10 個。書き方は 7.5 と同じ「`コード`（level。説明）」）:
  - 網羅分類（A6）と統合（M-*）: `NORM-MERGE-TARGET`（warn。M-* の統合先が見つからず、分類が仮のまま（`into` が空）。統合先が無いときの H-* の規則は 8 章）、`NORM-MERGE-DEPENDS-ON`（info。参照が無いので、統合されるものが自分で宣言した DependsOn の先（候補がちょうど 1 つ）を統合先にした）、`NORM-MERGE-AMBIGUOUS`（warn。統合先が 1 つの規則（親を名指す属性を持つ M-*）で候補が 2 つ以上あり、決まった順の最初の 1 つにした）。
  - ノード（N）と名前（B3・K-NAME。2 章）: `NORM-COND-UNKNOWN`（warn。作られるか（count・for_each・Condition）が決まらない（raw の `enabled: null`）リソースを描いた。7.2）、`NORM-NAME-FALLBACK`（info。名前が論理名に落ちた。名前が記号だけで、id の key を論理名から作ったときも）、`NORM-KEY-COLLISION`（info。同じ型で id の key が重なり、2 つ目以降に `.<論理名の key>` を付けた）。
  - 入れ子（P）と AZ（N-AZ）: `NORM-PLACEMENT`（warn。VPC の中に置く型（P-VPC・P-SUBNET・P-SPANS の型、サブネット）の置き場所のサブネット・VPC が決まらず `parent` を null にした、または ×N のサブネットを指すので `spans` を付けず `parent` を共通の祖先にした）、`NORM-AZ-UNKNOWN`（info。サブネットの AZ が静的に決まらず（`{"$az": "*"}`・値が無い・評価できない）、AZ のノードを作らずにサブネットを VPC の下に置いた）。
  - 辺（E）と参照の会計（CRITERIA の 1.8）: `NORM-RELATION-NOEDGE`（warn。関係リソース（R-*）から辺ができず、行き先の非表示の規則（fallback）も規則表に無いので、分類が仮のまま（`into` が空）。条件の無い Glue のトリガー、統合先がリソースでない API の統合など。8 章）、`NORM-UNUSED-REF`（info。active の参照が、辺の根拠・辺にしない参照（E-NOEDGE-*）・参照先にノードが無い参照（E-REF-NONODE）のどれにも当たらない。`address` は参照の from、`path` は raw の path、`message` に to と attr。docs/spec/rules/refs.md）。
