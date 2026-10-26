## 6. 出力の規則（C5）

- UTF-8、改行は LF、末尾に改行1つ。インデントは2スペース、キーは辞書順。
- 配列の順: `nodes` は `id` 順、`edges` は `id` 順、`sources.*.resources` は `address` 順、`sources.*.edges` は `edge` 順、`spans`・`into`・`rules`・`evidence` は文字列順。`notes` と `assumptions` は書いた順のまま。
- raw（7章）の配列の順: `resources` は `address` 順、`references` は `from`・`path`・`to`・`attr`・`fn` の順、`diagnostics` は `address`・`path`・`code` の順（address の無いものは先頭）。`assumptions` は書いた順のまま。
- `validate_ir.py --write` でこの形に整形できる（正規化後と raw の両方。`stage` で見分ける）。`validate_ir.py` は形がずれていればエラーにする。
