# 同梱アセットの出典

取得日: 2026-10-15。更新するときは、版と SHA-256 をこの表に書き直し、`scripts/build_icon_catalog.py` を再実行すること。

| ファイル | 取得元 | 版 | ライセンス | SHA-256 |
|---|---|---|---|---|
| `vendor/Sidebar-AWS4.js` | https://github.com/jgraph/drawio/blob/v32.4.1/src/main/webapp/js/diagramly/sidebar/Sidebar-AWS4.js | jgraph/drawio `v32.4.1` | Apache-2.0 | `F633E20B449058C6CB92F1666DB0D9678DA09AAA894DA82BDCBB01AC96D0BC32` |
| `aws-icons-mermaid.json` | https://github.com/awslabs/aws-icons-for-plantuml/blob/v23.1/dist/aws-icons-mermaid.json | awslabs/aws-icons-for-plantuml `v23.1` | アイコン: AWS Architecture Icons の利用規約に従う | `36BFF63D2B9F5F94021543A0F0E3B2ED845062A1953EB9038DBF23651FD47111` |

- `Sidebar-AWS4.js` は辞書の生成元としてだけ使う。描画には draw.io 本体のステンシルを使う。
- draw.io Desktop の版も `v32.4.1` に合わせてある（2026-10-15 時点）。Desktop を更新したら、同じ版の `Sidebar-AWS4.js` を取り直し、C2（壊れたアイコンの検出）を再実行する。
