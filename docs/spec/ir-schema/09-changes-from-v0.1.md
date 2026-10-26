## 9. v0.1 からの変更点（2026-10-17）

- `ir_version` を `1.0` にした。正規化後の形は v0.1 と互換（正解 IR は `ir_version` を直しただけ）。
- `attrs` のキーを表で固定した（2章）。v0.1 の正解 IR が使っていた `cidr`、`access`、`endpoint_type`、`service` に、黒箱のモジュール用の `module_source`、`module_version` を足した。
- 黒箱のモジュール（型 `module`、`via: "module_blackbox"`）を足した（2章、4章）。辺は `inferred` にした。
- ×N の出し方と、AZ が静的に決まらないときの key を決めた（2章）。
- 正規化後の IR に、省略可の `diagnostics` を足した（1章）。
- アダプタの出力（`stage: "raw"`）を定義した（7章）。第三者レビュー（2026-10-17）の指摘で、印の名前を `$res` にし（JSON Schema の `$ref` との取り違えを避ける）、`$$` の逃がし方、`$json`、`$concat` の正規形、リストの分割、参照の `state`・一意のキー、複数スタックの address、解決できた ImportValue、SAM の Globals と暗黙のリソース、TF の `$pseudo`・スプラット・`through` の書き方を決めた。
- 網羅分類の `file` に、ルートの外の `../` 付きのパスを認めた（4章）。
