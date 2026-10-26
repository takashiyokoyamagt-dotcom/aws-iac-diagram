# 公開モジュールの要約表（A5）

- 状態: フェーズ2 の手順3（2026-10-17）で作成。対象は terraform-aws-modules の vpc・alb・rds・eks（PLAN の A5）。4つとも、タグを付けた版の本物のソース（`aws-iac-diagram-workspace/fixtures/public/`）と突き合わせるテストがある
- **これは開発者向けの説明です（SKILL の外。配りません）。表そのもの（TF アダプタが実行時に読むデータ）は `skills/aws-iac-diagram/data/module-summaries/` にあります**（R4 で `references/module-summaries.md` から分けた。説明はここ、表はデータのフォルダ）
- 使うもの: TF アダプタ（`scripts/adapt_tf.py`）が、手元に中身の無いレジストリモジュールの呼び出しを、この表の HCL で展開する。読み込みは `scripts/aws_iac_diagram/adapters/terraform/modules/summaries.py`
- raw IR での出し方: [ir-schema.md](../../skills/aws-iac-diagram/references/ir-schema.md) の 7.2（モジュール）と 4章の `via: "module_summary"`
- 表の HCL は terraform-aws-modules（Apache-2.0）のソースから、変数の宣言（`type`・`default`・`nullable`）・出力・主要なリソースのブロックを写して短くしたもの（改変あり）。出典とライセンスは、ルートの [NOTICE](../../NOTICE) の 2(b)

## 1. 考え方

- **要約表は、本物のモジュールの主要なリソースと出力を、同じ HCL の書き方で写したもの。** アダプタは、手元のローカルモジュールと同じように評価する（変数・locals・count・for_each・出力・`through`）。表の形を別に決めず HCL にしたのは、count・for_each の条件（`single_nat_gateway` で NAT の数が変わる、など）を本物と同じ式で評価するため。
- 写すのは、図に要るもの（ノードになる型、辺・入れ子の根拠になる参照、名前の属性・タグ）と、その count・for_each の条件だけ。そのほかの属性は写さない。変数は本物の宣言をそのまま写す（`type` の変換で `1` が `"1"` になる、などを本物と揃えるため）。
- **展開するのは、その入力で作られる managed リソースだけ。** 表の中の `data` は載せない（`data.aws_partition` などは擬似パラメータとして使う）。count が 0・for_each が空のリソースも載せない（`try(aws_x.y[0].id, null)` は Terraform と同じく `null` になる）。決まらない count・for_each のものは ×N で載せる。**手元のソースをローカルモジュールとして読んだときは、count が 0 のブロックも `enabled: false` で載る**（ルートモジュールと同じ。ir-schema.md の 7.2）。同じモジュールでも、要約表で展開したときと手元のソースを読んだときで、`enabled: false` のリソースの数が違う。
- 表の中の黒箱の呼び出し（eks の `module.kms`）は、`create` 引数が false と決まれば `enabled: false`、決まらなければ `enabled: null` で載せる（ir-schema.md の 7.2。`TF-MODULE-NOT-CREATED`。参照の先を残すため、count が 0 のリソースと違って載せる）。
- address は本物と同じ（`module.vpc.aws_subnet.public[0]`、`module.db.module.db_instance.aws_db_instance.this[0]`、`module.eks.module.kms`）。`file` は呼び出しのあるファイル（4章）。
- **写していないリソースを作る入力**は、呼び出しで渡されたら診断 `TF-MODULE-SUMMARY-INPUT`（info）に名前を書く。表に宣言の無い入力と、コードブロックの `# not-covered:` の行に書いた入力が対象。`# not-covered:` には、入れ子の経路も書ける（`listeners.*.authenticate_cognito`。`*` はマップのどのキー・リストのどの要素でもよい。渡した値のその位置に `null`・空の `{}`・`[]` 以外の値があれば当たる。途中の値が決まらず調べられなければ、そのことを info に書く）。そのリソース・属性は図に出ない（推測して描かない。CRITERIA の 2.3 の A5）。
- 表に無い出力を参照したら `$unknown`（`TF-MODULE-SUMMARY-OUTPUT`、warn）。
- 秘密の値の扱いはルートモジュールと同じ（`sensitive` の変数・出力の値は使わない）。

## 2. 版の選び方

- 各表は、対象の major を持つ（下の `majors`）。呼び出しの `version` の制約（`~> 6.7`、`6.6.0`、`>= 6.0, < 7.0`）が許す major のうち、表のある最も新しいものを使う。
- `version` が無い、上限の無い制約（`>= 5.0`）、2つ以上の major を許す制約（`>= 5.0, < 7.0`）は、表のある最も新しい major を使い、`evaluation.assumptions` に書く。
- 許す major の表が無ければ黒箱（`type: module`、`via: module_blackbox`、`TF-MODULE-BLACKBOX`）。例: vpc の 5.x（T16 の `5.8.1`、T18 の `~> 5.0`）、eks の 20.x・19.x（作るかはフェーズ6 の前に決める）。
- サブモジュール（`terraform-aws-modules/rds/aws//modules/db_instance`）は、`//modules/<名前>` を付けた source の表。表の中の `module` ブロックの `./modules/<名前>` も、同じ版のこの表で展開する。

## 3. 表の一覧

| source | majors | 確かめたソース | 主なリソース | 写していないもの（入力を渡すと TF-MODULE-SUMMARY-INPUT） |
|---|---|---|---|---|
| `terraform-aws-modules/vpc/aws` | 6 | v6.7.3（`fixtures/public/terraform-aws-vpc`、P01、コミット b3abd6d）。突き合わせのテストあり | VPC、サブネット（public・private・database・intra）、ルートテーブル・関連付け・ルート（IGW・NAT・egress-only IGW）、IGW、EIP、NAT、DB サブネットグループ、VPN ゲートウェイ、既定の SG・NACL・ルートテーブル | elasticache・redshift・outpost のサブネット、専用の NACL、IPv6 の CIDR、セカンダリ CIDR、DHCP オプション、フローログ、カスタマーゲートウェイ、VPN の経路の伝播、IPAM、Block Public Access |
| `terraform-aws-modules/alb/aws` | 10 | v10.5.1（`fixtures/public/terraform-aws-alb`、コミット 6c6e48c、2026-10-17 に取得）。突き合わせのテストあり | ロードバランサ、リスナー（forward・weighted_forward・redirect・fixed-response）、リスナーのルール（同じ4種のアクションと条件）、追加の証明書、ターゲットグループ、ターゲットの登録（`additional` を含む）、Lambda のターゲットの `aws_lambda_permission`、SG と `aws_vpc_security_group_{ingress,egress}_rule`、Route 53 のレコード、WAF の関連付け | 認証のアクション（`listeners.*.authenticate_cognito`・`authenticate_oidc`・`jwt_validation`、ルールの `actions.*` の同じもの）、mTLS（`listeners.*.mutual_authentication`）、ルールの `transform`、接続・ヘルスチェックのログ、IPAM |
| `terraform-aws-modules/rds/aws`（と `//modules/db_instance`・`db_subnet_group`・`db_parameter_group`・`db_option_group`・`db_instance_role_association`） | 7 | v7.2.2（`fixtures/public/terraform-aws-rds`、コミット 175da04、2026-10-17 に取得）。突き合わせのテストあり | DB インスタンス、サブネットグループ・パラメータグループ・オプショングループ（`create_*` で作るとき）、ロググループ（`enabled_cloudwatch_logs_exports`）、拡張モニタリングのロール、マスターパスワードのローテーション、IAM ロールの関連付け | 自動バックアップのリージョン間レプリケーション（`db_instance_automated_backups_replication`）、`s3_import`、`restore_to_point_in_time` |
| `terraform-aws-modules/eks/aws`（と `//modules/eks-managed-node-group`・`fargate-profile`・`self-managed-node-group`） | 21 | v21.29.0（`fixtures/public/terraform-aws-eks`、P03、コミット 91b8a8d）。突き合わせのテストあり | クラスタ、ロググループ、クラスタと node の SG とルール、クラスタの IAM ロール、OIDC プロバイダ、KMS（`module.kms`。表に無いので黒箱）、アドオン、アクセスエントリ、`time_sleep`、マネージドノードグループ・Fargate プロファイル・セルフマネージドノードグループ（それぞれ IAM ロール・起動テンプレートなど） | Auto Mode、Outposts、ID プロバイダ、IPv6 の CNI ポリシー、追加の IAM ポリシー、ノードグループの SG・配置グループ・ユーザーデータ、Karpenter・hybrid-node-role などのサブモジュール |

- rds-aurora（`terraform-aws-modules/rds-aurora/aws`）は表にしない。公開サンプルでレジストリから呼ぶものが無く、P04 は `source = "../../"` で手元のソースを読む（ローカルモジュールとして展開される）。
- **本物との違い（意図したもの）:** eks の `data.aws_iam_session_context` から引くクラスタ作成者の ARN は、文字列 `"cluster creator (the caller of Terraform)"` にした。ノードグループのユーザーデータのサブモジュール（`module.user_data`）の `null_resource`（入力の検査だけのもの）は写していない。表の中で `data.aws_partition` を擬似パラメータとして使うので、本物では data への参照になる属性（alb の `aws_lambda_permission` の `principal` など）が `$pseudo` になる。
- **本物と突き合わせた結果（2026-10-17）:**
  - vpc: 3通りの入力（three-tier-modules と同じもの、AZ を `data.aws_availability_zones` から取り NAT を AZ ごとにするもの、DB サブネットをインターネットゲートウェイに向けるもの）で、作られるリソースの address（25・39・17 件）、表のリソースの間の参照、名前とタグがすべて一致した。
  - eks: マネージド・Fargate・セルフマネージドのノードグループ、アドオン、アクセスエントリを渡した入力で、`null_resource` （2件）を除いて 48 件の address と参照・名前が一致した。
  - alb: three-tier-modules と同じ入力（6 件）と、ルール（weighted_forward・forward）・HTTPS と追加の証明書・redirect・Lambda のターゲット・Route 53 を渡した入力（14 件）で、address・参照・名前とタグが一致した。props の違いは、weighted_forward の空の `stickiness` と、上の `$pseudo` だけ。
  - rds: three-tier-modules と同じ入力（1 件）と、mysql・サブネットグループ・パラメータグループ・オプショングループ・拡張モニタリング・ロググループを作る入力（8 件）で、address・参照・props が一致した。

## 4. IAM だけを作るモジュール（H-IAM）

次の source（サブモジュールを含む）は、IAM のリソースだけを作る。アダプタは黒箱の呼び出し（`via: module_blackbox`）として出し、正規化が `hidden`（規則 `H-IAM`。ir-schema.md の 2章）にする。判定は `scripts/aws_iac_diagram/adapters/terraform/modules/summaries.py` の `iam_only()`（source の前方一致。ホスト名 `registry.terraform.io/` は除く）。ローカルモジュールは中身を読むので、リソースの型ごとに `H-IAM` になる（この一覧は使わない）。

一覧は `data/module-summaries/iam-only-sources.md`（今は `terraform-aws-modules/iam/aws` の 1 行）。

- 公開サンプルでは T16 の `iam-assumable-role-with-oidc`（`5.39.0`）、T18 の `iam-role-for-service-accounts-eks`（`~> 5.20`）が当たる。
- 足すときは、本物のソースで IAM 以外のリソース（`aws_*` の IAM 以外の型）を作らないことを確かめてから、この一覧に1行足す。

## 5. 表の直し方

1. 本物のソース（タグを付けた版）を `fixtures/public/` に取り、`resource` の count・for_each の式と、図に要る属性（名前・タグ・`vpc_id`・`subnet_id`・ルートの先など）をそのまま写す。変数は、使うものの宣言を本物の `variables.tf` からそのまま写す（トップレベルの `description` だけ除く）。
2. `data/module-summaries/<モジュール>/v<メジャー>.md` に、`<!-- module-summary source="…" majors="…" -->` の行の直後のコードブロックとして書く（新しい major は新しいファイル。サブモジュールの表は親と同じファイルに入れる）。写していないリソースを作る入力は `# not-covered:` の行に書く。
3. `tests/test_tf_adapter.py` の `SummaryTest` が、同じ入力で手元のソースを読んだ結果と、要約表で展開した結果を突き合わせる（作られるリソースの address、表のリソースの間の参照、名前とタグ）。版を上げたらソースを取り直してテストを流す。
4. **ファイルを足す・名前を変えたら**、`scripts/doctor.py` の `REQUIRED_FILES` と `tests/test_doctor_required_files.py` の `RUNTIME_DATA` にも足す（食い違うとテストが落ちる）。選び方（版の制約 → 表）のテストは `tests/test_tf_adapter.py` の `SummaryTest`、読み込みの順序は `tests/test_paths.py` の `SummaryDirectoryTest`。

## 6. 表の置き場所（R4）

| 場所 | 中身 |
|---|---|
| `data/module-summaries/terraform-aws-vpc/v6.md` | vpc の 6.x |
| `data/module-summaries/terraform-aws-alb/v10.md` | alb の 10.x |
| `data/module-summaries/terraform-aws-rds/v7.md` | rds の 7.x と、サブモジュール 5 つ（`db_instance`・`db_subnet_group`・`db_parameter_group`・`db_option_group`・`db_instance_role_association`） |
| `data/module-summaries/terraform-aws-eks/v21.md` | eks の 21.x と、サブモジュール 3 つ（`eks-managed-node-group`・`fargate-profile`・`self-managed-node-group`） |
| `data/module-summaries/iam-only-sources.md` | H-IAM の source の一覧（4） |

- 1 つのファイルは 1 つのモジュールの 1 つの major。ファイルの先頭の見出しと説明の行（`# …`、`> …`）と、表ごとの見出し（`### …`）は読み込みに影響しない（読むのは `<!-- module-summary … -->` の行とその直後のコードブロック、`<!-- iam-only-sources -->` の直後のコードブロックだけ）。
- 読み込み（`summaries.load`）は、フォルダの下の `.md` を、パスの文字と数を分けた順序（`v6` は `v10` の前）で読む。同じ source の表が複数のファイルにあるときも、選び方（`resolve.choose`）は 2 の規則のまま（major で選ぶ）。
- R4 より前は、これらを `references/module-summaries.md` 1 つに書いていた。表の HCL は、分ける前とバイト単位で同じ（`tests` ではなく WORKLOG の R4 の「確かめたこと」に、分ける前のファイルとの照合を書いた）。
