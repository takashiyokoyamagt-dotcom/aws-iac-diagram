# data/rules/

正規化（フェーズ 3）と `scripts/validate_ir.py` が読む**規則表**です（TOML。読み込みと検査は `scripts/aws_iac_diagram/core/rules.py`）。このファイルは読まれません（説明だけ）。

| ファイル | 内容 |
|---|---|
| `types/*.toml` | 型の扱い。描く型（ノードになる）、統合する型（M-*）、非表示にする型（H-*）。TF と CFN の型を 1 行に並べる |
| `relations.toml` | 関係リソース（R-*）。2 つのリソースを結ぶためだけの型を、辺に変える |
| `edges.toml` | 確信度、辺を作る規則（E-*）、kind の対応表、辺をまとめる優先順、合成ノード（N-*）、ラベルの書式 |
| `refs.toml` | 辺にしない参照（E-NOEDGE-*）、参照先にノードが無い参照（E-REF-NONODE） |
| `placement.toml` | 入れ子の規則（N-AZ・P-*）と、ノードの `attrs` の取り方 |

- 規則 ID（`H-IAM`・`R-LB-TG` など）は、IR の `sources` が指す名前です。名前も意味も変えず、消さないでください。
- 行を足したり直したりしたら、`scripts/validate_ir.py`（規則表を読み込んで検査します。壊れていれば終了コード 2）と `scripts/doctor.py`（同じ検査の結果を `skill.rules_problems` に出し、error にします）で確かめます。
- このフォルダに置いてよいのは、上の表のファイル（`types/` の中は `.toml` だけ）とこの README だけです。ほかの名前（`foo.toml`・`notes.txt`・`types/x.toml.bak` など）は置き場所や綴りの誤りとして検査に落ちます。ただし OS やエディタが作るもの（`.` で始まる名前（`.DS_Store`・`.edges.toml.swp` など）、`Thumbs.db`・`desktop.ini`、末尾が `~`・`.swp`・`.swo` の名前、`#…#`）は読まずに無視します。
- 規則の理由・列の説明・表の一覧は、この SKILL を配るリポジトリの `docs/spec/rules/`（SKILL の外。配りません）にあります。
