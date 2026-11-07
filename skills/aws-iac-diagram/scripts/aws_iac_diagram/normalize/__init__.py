"""正規化（raw IR → normalized IR。型別の表、A1〜A3、AZ の挿入、SG を辺に変換）。入口の関数は `build.normalize`。

フェーズ 3 の手順 3a: 段階 0〜2（読み込み `view`、仮分類と確定 `classify`・統合先の探し方 `merge`、名前と id `names`、ノード `nodes`）まで。
辺・入れ子・合成ノードは後の手順で足す。core だけを import する（docs/architecture.md の層の表）。
"""
