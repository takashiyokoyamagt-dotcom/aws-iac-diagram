"""Terraform の plan JSON（`terraform show -json <plan>` の出力）から raw IR（ir-schema.md の 7章）を作る。

フェーズ2 の手順4。標準ライブラリだけで動く（adapt_tf.py から使う）。決まりは ir-schema.md の 7.2「TF の plan JSON」と
7.3「plan JSON の参照」。

  - address・count／for_each の展開・作られるか（enabled）は Terraform の結果（planned_values・resource_changes・
    prior_state）をそのまま使う。設定（configuration）にあってインスタンスが無いブロックは、添字なしの address で
    enabled: false（.tf と同じ）。レジストリなどリモートのモジュールの中の、作られないブロックと data は載せない
    （要約表の展開と同じ。4章の module_summary）
  - props は、設定（configuration の expressions）に書かれた属性とブロックだけ。値は plan の after（data は
    prior_state の values）。known after apply（after_unknown）は $unknown、sensitive（after_sensitive）の値は使わず
    $unknown
  - 参照は configuration の references。重なり（aws_subnet.private[0].id・aws_subnet.private[0]・aws_subnet.private）
    は最も細かいもの1つにまとめる（7.3）。var.*（モジュールの変数）は呼び出しの式へ、module.x.y は子の出力の式へ
    たどり、through に書く。local.* は plan JSON に式が無いのでたどれない（TF-PLAN-LOCALS）
  - 参照を props のどこに置くか（$res にして active にするか）は、値の形と先のリソースの値で決める（7.3）

combine()（combine.py）は、同じ構成の .tf から作った raw IR と合わせる（--input <フォルダ> --plan <plan JSON>）。address と
作られるかは plan、file・props・参照の位置は .tf、.tf で決まらなかった値は plan の値で埋める。plan の設定にあって
.tf の参照に無い組（from とブロック）は unevaluated で足す。plan が sensitive とした位置は、.tf の値も使わない
（mask_sensitive。.tf の評価は plan の variables の値を使うので、sensitive と宣言していない変数が入りうる）。

ファイルの分け方: read（ファイルを読む・形を確かめる）、reader（PlanReader。インスタンスとモジュールを集める）、values（unknown・sensitive の印を持つ値）、
addresses、masking、consistency、diagnostics、raw（plan JSON だけから raw IR）、combine（.tf と合わせる）。
"""
