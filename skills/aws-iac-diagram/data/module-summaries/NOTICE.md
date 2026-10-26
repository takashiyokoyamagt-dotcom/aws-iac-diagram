# このフォルダのファイルの出典とライセンス

このフォルダの `<モジュール>/v<数字>.md` は、terraform-aws-modules の Terraform モジュールのソースから、変数の宣言（`type`・`default`・`nullable`）・出力・
主要なリソースのブロックを写して**短くした**もの（**改変あり**）です。変数は、表の本文が使うものの宣言だけを写しています（残りは宣言が無く、呼び出しで渡されると TF-MODULE-SUMMARY-INPUT に名前が出ます）。TF アダプタが、手元に中身の無いレジストリモジュールの呼び出しを展開するときに読みます。
`iam-only-sources.md` は、IAM のリソースだけを作るモジュールの source 名の一覧で、ソースコードの写しではありません。

| ファイル | 上流のリポジトリ | 写した版 |
|---|---|---|
| `terraform-aws-vpc/v5.md` | https://github.com/terraform-aws-modules/terraform-aws-vpc | v5.21.0（コミット 7c1f791）。v5.8.1（コミット 25322b6）とも突き合わせた |
| `terraform-aws-vpc/v6.md` | https://github.com/terraform-aws-modules/terraform-aws-vpc | v6.7.3（コミット b3abd6d） |
| `terraform-aws-alb/v10.md` | https://github.com/terraform-aws-modules/terraform-aws-alb | v10.5.1（コミット 6c6e48c） |
| `terraform-aws-rds/v7.md` | https://github.com/terraform-aws-modules/terraform-aws-rds | v7.2.2（コミット 175da04） |
| `terraform-aws-eks/v20.md` | https://github.com/terraform-aws-modules/terraform-aws-eks | v20.8.5（コミット afadb14） |
| `terraform-aws-eks/v21.md` | https://github.com/terraform-aws-modules/terraform-aws-eks | v21.29.0（コミット 91b8a8d） |

- ライセンス: Apache License 2.0（https://www.apache.org/licenses/LICENSE-2.0）。著作権表示は各上流リポジトリの LICENSE にあります。
- ライセンス全文（標準の Apache License 2.0 の本文）は、この SKILL の `assets/vendor/LICENSE-drawio-Apache-2.0.txt` と同じです（ファイル名は同梱している別の Apache-2.0 の成果物のものですが、本文は標準です）。
- 改変の内容: ソースを短くした（主要なリソースと、count・for_each の条件、名前・参照の属性、変数の宣言、出力だけを残した）。変数の宣言は本物のものを写し、トップレベルの `description` だけ除いた。
- このファイルは実行時には読みません（TF アダプタは `v<数字>.md` と `iam-only-sources.md` だけを読みます）。ライセンス表示のために一緒に配ります。リポジトリ直下の `NOTICE` の 2(b) も参照してください。
