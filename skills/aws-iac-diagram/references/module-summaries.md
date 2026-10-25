# 公開モジュールの要約表（A5）

- 状態: フェーズ2 の手順3（2026-10-17）で作成。対象は terraform-aws-modules の vpc・alb・rds・eks（PLAN の A5）。4つとも、タグを付けた版の本物のソース（`aws-iac-diagram-workspace/fixtures/public/`）と突き合わせるテストがある
- 使うもの: TF アダプタ（`scripts/adapters/tf.py`）が、手元に中身の無いレジストリモジュールの呼び出しを、この表の HCL で展開する。読み込みは `scripts/aws_iac_diagram/adapters/terraform/tf_modules.py`
- raw IR での出し方: [ir-schema.md](ir-schema.md) の 7.2（モジュール）と 4章の `via: "module_summary"`
- 表の HCL は terraform-aws-modules（Apache-2.0）のソースから、変数の宣言（`type`・`default`・`nullable`）・出力・主要なリソースのブロックを写して短くしたもの（改変あり）。出典とライセンスは、ルートの [NOTICE](../../../NOTICE) の 2(b)

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

次の source（サブモジュールを含む）は、IAM のリソースだけを作る。アダプタは黒箱の呼び出し（`via: module_blackbox`）として出し、正規化が `hidden`（規則 `H-IAM`。ir-schema.md の 2章）にする。判定は `scripts/aws_iac_diagram/adapters/terraform/tf_modules.py` の `iam_only()`（source の前方一致。ホスト名 `registry.terraform.io/` は除く）。ローカルモジュールは中身を読むので、リソースの型ごとに `H-IAM` になる（この一覧は使わない）。

<!-- iam-only-sources -->
```text
terraform-aws-modules/iam/aws
```

- 公開サンプルでは T16 の `iam-assumable-role-with-oidc`（`5.39.0`）、T18 の `iam-role-for-service-accounts-eks`（`~> 5.20`）が当たる。
- 足すときは、本物のソースで IAM 以外のリソース（`aws_*` の IAM 以外の型）を作らないことを確かめてから、この一覧に1行足す。

## 5. 表の直し方

1. 本物のソース（タグを付けた版）を `fixtures/public/` に取り、`resource` の count・for_each の式と、図に要る属性（名前・タグ・`vpc_id`・`subnet_id`・ルートの先など）をそのまま写す。変数は、使うものの宣言を本物の `variables.tf` からそのまま写す（トップレベルの `description` だけ除く）。
2. `<!-- module-summary source="…" majors="…" -->` の行の直後のコードブロックに書く。写していないリソースを作る入力は `# not-covered:` の行に書く。
3. `tests/test_tf_adapter.py` の `SummaryTest` が、同じ入力で手元のソースを読んだ結果と、要約表で展開した結果を突き合わせる（作られるリソースの address、表のリソースの間の参照、名前とタグ）。版を上げたらソースを取り直してテストを流す。

## 6. 表

### vpc（6.x）

<!-- module-summary source="terraform-aws-modules/vpc/aws" majors="6" -->
```hcl
# not-covered: elasticache_subnets, redshift_subnets, outpost_subnets, secondary_cidr_blocks, enable_dhcp_options, enable_flow_log
# not-covered: public_dedicated_network_acl, private_dedicated_network_acl, database_dedicated_network_acl, intra_dedicated_network_acl
# not-covered: public_subnet_ipv6_prefixes, private_subnet_ipv6_prefixes, database_subnet_ipv6_prefixes, intra_subnet_ipv6_prefixes
# not-covered: customer_gateways, vpn_gateway_id, propagate_private_route_tables_vgw, propagate_public_route_tables_vgw, manage_default_vpc
# not-covered: use_ipam_pool, reuse_nat_ips, vpc_block_public_access_options, vpc_block_public_access_exclusions
variable "amazon_side_asn" {
  type        = string
  default     = "64512"
}

variable "azs" {
  type        = list(string)
  default     = []
}

variable "cidr" {
  type        = string
  default     = "10.0.0.0/16"
}

variable "create_database_internet_gateway_route" {
  type        = bool
  default     = false
}

variable "create_database_nat_gateway_route" {
  type        = bool
  default     = false
}

variable "create_database_subnet_group" {
  type        = bool
  default     = true
}

variable "create_database_subnet_route_table" {
  type        = bool
  default     = false
}

variable "create_egress_only_igw" {
  type        = bool
  default     = true
}

variable "create_igw" {
  type        = bool
  default     = true
}

variable "create_multiple_intra_route_tables" {
  type        = bool
  default     = false
}

variable "create_multiple_public_route_tables" {
  type        = bool
  default     = false
}

variable "create_private_nat_gateway_route" {
  type        = bool
  default     = true
}

variable "create_vpc" {
  type        = bool
  default     = true
}

variable "database_route_table_tags" {
  type        = map(string)
  default     = {}
}

variable "database_subnet_group_name" {
  type        = string
  default     = null
}

variable "database_subnet_group_tags" {
  type        = map(string)
  default     = {}
}

variable "database_subnet_ipv6_native" {
  type        = bool
  default     = false
}

variable "database_subnet_ipv6_prefixes" {
  type        = list(string)
  default     = []
}

variable "database_subnet_names" {
  type        = list(string)
  default     = []
}

variable "database_subnet_suffix" {
  type        = string
  default     = "db"
}

variable "database_subnet_tags" {
  type        = map(string)
  default     = {}
}

variable "database_subnets" {
  type        = list(string)
  default     = []
}

variable "default_network_acl_name" {
  type        = string
  default     = null
}

variable "default_network_acl_tags" {
  type        = map(string)
  default     = {}
}

variable "default_route_table_name" {
  type        = string
  default     = null
}

variable "default_route_table_tags" {
  type        = map(string)
  default     = {}
}

variable "default_security_group_name" {
  type        = string
  default     = null
}

variable "default_security_group_tags" {
  type        = map(string)
  default     = {}
}

variable "elasticache_subnet_ipv6_prefixes" {
  type        = list(string)
  default     = []
}

variable "elasticache_subnets" {
  type        = list(string)
  default     = []
}

variable "enable_dns_hostnames" {
  type        = bool
  default     = true
}

variable "enable_dns_support" {
  type        = bool
  default     = true
}

variable "enable_ipv6" {
  type        = bool
  default     = false
}

variable "enable_nat_gateway" {
  type        = bool
  default     = false
}

variable "enable_vpn_gateway" {
  type        = bool
  default     = false
}

variable "external_nat_ip_ids" {
  type        = list(string)
  default     = []
}

variable "external_nat_ips" {
  type        = list(string)
  default     = []
}

variable "igw_tags" {
  type        = map(string)
  default     = {}
}

variable "instance_tenancy" {
  type        = string
  default     = "default"
}

variable "intra_route_table_tags" {
  type        = map(string)
  default     = {}
}

variable "intra_subnet_ipv6_native" {
  type        = bool
  default     = false
}

variable "intra_subnet_ipv6_prefixes" {
  type        = list(string)
  default     = []
}

variable "intra_subnet_names" {
  type        = list(string)
  default     = []
}

variable "intra_subnet_suffix" {
  type        = string
  default     = "intra"
}

variable "intra_subnet_tags" {
  type        = map(string)
  default     = {}
}

variable "intra_subnets" {
  type        = list(string)
  default     = []
}

variable "ipv4_ipam_pool_id" {
  type        = string
  default     = null
}

variable "manage_default_network_acl" {
  type        = bool
  default     = true
}

variable "manage_default_route_table" {
  type        = bool
  default     = true
}

variable "manage_default_security_group" {
  type        = bool
  default     = true
}

variable "map_public_ip_on_launch" {
  type        = bool
  default     = false
}

variable "name" {
  type        = string
  default     = ""
}

variable "nat_eip_tags" {
  type        = map(string)
  default     = {}
}

variable "nat_gateway_destination_cidr_block" {
  type        = string
  default     = "0.0.0.0/0"
}

variable "nat_gateway_tags" {
  type        = map(string)
  default     = {}
}

variable "one_nat_gateway_per_az" {
  type        = bool
  default     = false
}

variable "private_route_table_tags" {
  type        = map(string)
  default     = {}
}

variable "private_subnet_ipv6_native" {
  type        = bool
  default     = false
}

variable "private_subnet_ipv6_prefixes" {
  type        = list(string)
  default     = []
}

variable "private_subnet_names" {
  type        = list(string)
  default     = []
}

variable "private_subnet_suffix" {
  type        = string
  default     = "private"
}

variable "private_subnet_tags" {
  type        = map(string)
  default     = {}
}

variable "private_subnet_tags_per_az" {
  type        = map(map(string))
  default     = {}
}

variable "private_subnets" {
  type        = list(string)
  default     = []
}

variable "public_route_table_tags" {
  type        = map(string)
  default     = {}
}

variable "public_subnet_ipv6_native" {
  type        = bool
  default     = false
}

variable "public_subnet_ipv6_prefixes" {
  type        = list(string)
  default     = []
}

variable "public_subnet_names" {
  type        = list(string)
  default     = []
}

variable "public_subnet_suffix" {
  type        = string
  default     = "public"
}

variable "public_subnet_tags" {
  type        = map(string)
  default     = {}
}

variable "public_subnet_tags_per_az" {
  type        = map(map(string))
  default     = {}
}

variable "public_subnets" {
  type        = list(string)
  default     = []
}

variable "putin_khuylo" {
  type        = bool
  default     = true
}

variable "redshift_subnet_ipv6_prefixes" {
  type        = list(string)
  default     = []
}

variable "redshift_subnets" {
  type        = list(string)
  default     = []
}

variable "region" {
  type        = string
  default     = null
}

variable "reuse_nat_ips" {
  type        = bool
  default     = false
}

variable "single_nat_gateway" {
  type        = bool
  default     = false
}

variable "tags" {
  type        = map(string)
  default     = {}
}

variable "use_ipam_pool" {
  type        = bool
  default     = false
}

variable "vpc_tags" {
  type        = map(string)
  default     = {}
}

variable "vpn_gateway_az" {
  type        = string
  default     = null
}

variable "vpn_gateway_tags" {
  type        = map(string)
  default     = {}
}

locals {
  len_public_subnets      = max(length(var.public_subnets), length(var.public_subnet_ipv6_prefixes))
  len_private_subnets     = max(length(var.private_subnets), length(var.private_subnet_ipv6_prefixes))
  len_database_subnets    = max(length(var.database_subnets), length(var.database_subnet_ipv6_prefixes))
  len_elasticache_subnets = max(length(var.elasticache_subnets), length(var.elasticache_subnet_ipv6_prefixes))
  len_redshift_subnets    = max(length(var.redshift_subnets), length(var.redshift_subnet_ipv6_prefixes))
  len_intra_subnets       = max(length(var.intra_subnets), length(var.intra_subnet_ipv6_prefixes))

  max_subnet_length = max(
    local.len_private_subnets,
    local.len_public_subnets,
    local.len_elasticache_subnets,
    local.len_database_subnets,
    local.len_redshift_subnets,
  )

  vpc_id     = try(aws_vpc.this[0].id, "")
  create_vpc = var.create_vpc && var.putin_khuylo

  create_public_subnets       = local.create_vpc && local.len_public_subnets > 0
  num_public_route_tables     = var.create_multiple_public_route_tables ? local.len_public_subnets : 1
  create_private_subnets      = local.create_vpc && local.len_private_subnets > 0
  create_database_subnets     = local.create_vpc && local.len_database_subnets > 0
  create_database_route_table = local.create_database_subnets && var.create_database_subnet_route_table
  create_intra_subnets        = local.create_vpc && local.len_intra_subnets > 0
  num_intra_route_tables      = var.create_multiple_intra_route_tables ? local.len_intra_subnets : 1

  nat_gateway_count = var.single_nat_gateway ? 1 : var.one_nat_gateway_per_az ? length(var.azs) : local.max_subnet_length
  nat_gateway_ips   = var.reuse_nat_ips ? var.external_nat_ip_ids : aws_eip.nat[*].id
}

resource "aws_vpc" "this" {
  count = local.create_vpc ? 1 : 0

  region               = var.region
  cidr_block           = var.use_ipam_pool ? null : var.cidr
  ipv4_ipam_pool_id    = var.ipv4_ipam_pool_id
  instance_tenancy     = var.instance_tenancy
  enable_dns_hostnames = var.enable_dns_hostnames
  enable_dns_support   = var.enable_dns_support

  tags = merge({ "Name" = var.name }, var.tags, var.vpc_tags)
}

resource "aws_subnet" "public" {
  count = local.create_public_subnets && (!var.one_nat_gateway_per_az || local.len_public_subnets >= length(var.azs)) ? local.len_public_subnets : 0

  region                  = var.region
  availability_zone       = length(regexall("^[a-z]+-", element(var.azs, count.index))) > 0 ? element(var.azs, count.index) : null
  availability_zone_id    = length(regexall("^[a-z]+-", element(var.azs, count.index))) == 0 ? element(var.azs, count.index) : null
  cidr_block              = var.public_subnet_ipv6_native ? null : element(concat(var.public_subnets, [""]), count.index)
  map_public_ip_on_launch = var.map_public_ip_on_launch
  vpc_id                  = local.vpc_id

  tags = merge(
    {
      Name = try(
        var.public_subnet_names[count.index],
        format("${var.name}-${var.public_subnet_suffix}-%s", element(var.azs, count.index))
      )
    },
    var.tags,
    var.public_subnet_tags,
    lookup(var.public_subnet_tags_per_az, element(var.azs, count.index), {})
  )
}

resource "aws_route_table" "public" {
  count = local.create_public_subnets ? local.num_public_route_tables : 0

  region = var.region
  vpc_id = local.vpc_id

  tags = merge(
    {
      "Name" = var.create_multiple_public_route_tables ? format(
        "${var.name}-${var.public_subnet_suffix}-%s",
        element(var.azs, count.index),
      ) : "${var.name}-${var.public_subnet_suffix}"
    },
    var.tags,
    var.public_route_table_tags,
  )
}

resource "aws_route_table_association" "public" {
  count = local.create_public_subnets ? local.len_public_subnets : 0

  region         = var.region
  subnet_id      = element(aws_subnet.public[*].id, count.index)
  route_table_id = element(aws_route_table.public[*].id, var.create_multiple_public_route_tables ? count.index : 0)
}

resource "aws_route" "public_internet_gateway" {
  count = local.create_public_subnets && var.create_igw ? local.num_public_route_tables : 0

  region                 = var.region
  route_table_id         = aws_route_table.public[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this[0].id
}

resource "aws_route" "public_internet_gateway_ipv6" {
  count = local.create_public_subnets && var.create_igw && var.enable_ipv6 ? local.num_public_route_tables : 0

  region                      = var.region
  route_table_id              = aws_route_table.public[count.index].id
  destination_ipv6_cidr_block = "::/0"
  gateway_id                  = aws_internet_gateway.this[0].id
}

resource "aws_subnet" "private" {
  count = local.create_private_subnets ? local.len_private_subnets : 0

  region               = var.region
  availability_zone    = length(regexall("^[a-z]+-", element(var.azs, count.index))) > 0 ? element(var.azs, count.index) : null
  availability_zone_id = length(regexall("^[a-z]+-", element(var.azs, count.index))) == 0 ? element(var.azs, count.index) : null
  cidr_block           = var.private_subnet_ipv6_native ? null : element(concat(var.private_subnets, [""]), count.index)
  vpc_id               = local.vpc_id

  tags = merge(
    {
      Name = try(
        var.private_subnet_names[count.index],
        format("${var.name}-${var.private_subnet_suffix}-%s", element(var.azs, count.index))
      )
    },
    var.tags,
    var.private_subnet_tags,
    lookup(var.private_subnet_tags_per_az, element(var.azs, count.index), {})
  )
}

resource "aws_route_table" "private" {
  count = local.create_private_subnets && local.max_subnet_length > 0 ? local.nat_gateway_count : 0

  region = var.region
  vpc_id = local.vpc_id

  tags = merge(
    {
      "Name" = var.single_nat_gateway ? "${var.name}-${var.private_subnet_suffix}" : format(
        "${var.name}-${var.private_subnet_suffix}-%s",
        element(var.azs, count.index),
      )
    },
    var.tags,
    var.private_route_table_tags,
  )
}

resource "aws_route_table_association" "private" {
  count = local.create_private_subnets ? local.len_private_subnets : 0

  region    = var.region
  subnet_id = element(aws_subnet.private[*].id, count.index)
  route_table_id = element(
    aws_route_table.private[*].id,
    var.single_nat_gateway ? 0 : count.index,
  )
}

resource "aws_subnet" "database" {
  count = local.create_database_subnets ? local.len_database_subnets : 0

  region               = var.region
  availability_zone    = length(regexall("^[a-z]+-", element(var.azs, count.index))) > 0 ? element(var.azs, count.index) : null
  availability_zone_id = length(regexall("^[a-z]+-", element(var.azs, count.index))) == 0 ? element(var.azs, count.index) : null
  cidr_block           = var.database_subnet_ipv6_native ? null : element(concat(var.database_subnets, [""]), count.index)
  vpc_id               = local.vpc_id

  tags = merge(
    {
      Name = try(
        var.database_subnet_names[count.index],
        format("${var.name}-${var.database_subnet_suffix}-%s", element(var.azs, count.index), )
      )
    },
    var.tags,
    var.database_subnet_tags,
  )
}

resource "aws_db_subnet_group" "database" {
  count = local.create_database_subnets && var.create_database_subnet_group ? 1 : 0

  region      = var.region
  name        = lower(coalesce(var.database_subnet_group_name, var.name))
  description = "Database subnet group for ${var.name}"
  subnet_ids  = aws_subnet.database[*].id

  tags = merge(
    { "Name" = lower(coalesce(var.database_subnet_group_name, var.name)) },
    var.tags,
    var.database_subnet_group_tags,
  )
}

resource "aws_route_table" "database" {
  count = local.create_database_route_table ? var.single_nat_gateway || var.create_database_internet_gateway_route ? 1 : local.len_database_subnets : 0

  region = var.region
  vpc_id = local.vpc_id

  tags = merge(
    {
      "Name" = var.single_nat_gateway || var.create_database_internet_gateway_route ? "${var.name}-${var.database_subnet_suffix}" : format(
        "${var.name}-${var.database_subnet_suffix}-%s",
        element(var.azs, count.index),
      )
    },
    var.tags,
    var.database_route_table_tags,
  )
}

resource "aws_route_table_association" "database" {
  count = local.create_database_subnets && (local.create_database_route_table || local.create_private_subnets) ? local.len_database_subnets : 0

  region    = var.region
  subnet_id = element(aws_subnet.database[*].id, count.index)
  route_table_id = element(
    coalescelist(aws_route_table.database[*].id, aws_route_table.private[*].id),
    var.create_database_subnet_route_table ? var.single_nat_gateway || var.create_database_internet_gateway_route ? 0 : count.index : count.index,
  )
}

resource "aws_route" "database_internet_gateway" {
  count = local.create_database_route_table && var.create_igw && var.create_database_internet_gateway_route && !var.create_database_nat_gateway_route ? 1 : 0

  region                 = var.region
  route_table_id         = aws_route_table.database[0].id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this[0].id
}

resource "aws_route" "database_nat_gateway" {
  count = local.create_database_route_table && !var.create_database_internet_gateway_route && var.create_database_nat_gateway_route && var.enable_nat_gateway ? var.single_nat_gateway ? 1 : local.len_database_subnets : 0

  region                 = var.region
  route_table_id         = element(aws_route_table.database[*].id, count.index)
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = element(aws_nat_gateway.this[*].id, count.index)
}

resource "aws_subnet" "intra" {
  count = local.create_intra_subnets ? local.len_intra_subnets : 0

  region               = var.region
  availability_zone    = length(regexall("^[a-z]+-", element(var.azs, count.index))) > 0 ? element(var.azs, count.index) : null
  availability_zone_id = length(regexall("^[a-z]+-", element(var.azs, count.index))) == 0 ? element(var.azs, count.index) : null
  cidr_block           = var.intra_subnet_ipv6_native ? null : element(concat(var.intra_subnets, [""]), count.index)
  vpc_id               = local.vpc_id

  tags = merge(
    {
      Name = try(
        var.intra_subnet_names[count.index],
        format("${var.name}-${var.intra_subnet_suffix}-%s", element(var.azs, count.index))
      )
    },
    var.tags,
    var.intra_subnet_tags,
  )
}

resource "aws_route_table" "intra" {
  count = local.create_intra_subnets ? local.num_intra_route_tables : 0

  region = var.region
  vpc_id = local.vpc_id

  tags = merge(
    {
      "Name" = var.create_multiple_intra_route_tables ? format(
        "${var.name}-${var.intra_subnet_suffix}-%s",
        element(var.azs, count.index),
      ) : "${var.name}-${var.intra_subnet_suffix}"
    },
    var.tags,
    var.intra_route_table_tags,
  )
}

resource "aws_route_table_association" "intra" {
  count = local.create_intra_subnets ? local.len_intra_subnets : 0

  region         = var.region
  subnet_id      = element(aws_subnet.intra[*].id, count.index)
  route_table_id = element(aws_route_table.intra[*].id, var.create_multiple_intra_route_tables ? count.index : 0)
}

resource "aws_internet_gateway" "this" {
  count = local.create_public_subnets && var.create_igw ? 1 : 0

  region = var.region
  vpc_id = local.vpc_id

  tags = merge({ "Name" = var.name }, var.tags, var.igw_tags)
}

resource "aws_egress_only_internet_gateway" "this" {
  count = local.create_vpc && var.create_egress_only_igw && var.enable_ipv6 && local.max_subnet_length > 0 ? 1 : 0

  region = var.region
  vpc_id = local.vpc_id

  tags = merge({ "Name" = var.name }, var.tags, var.igw_tags)
}

resource "aws_route" "private_ipv6_egress" {
  count = local.create_vpc && var.create_egress_only_igw && var.enable_ipv6 && local.len_private_subnets > 0 ? local.nat_gateway_count : 0

  region                      = var.region
  route_table_id              = element(aws_route_table.private[*].id, count.index)
  destination_ipv6_cidr_block = "::/0"
  egress_only_gateway_id      = element(aws_egress_only_internet_gateway.this[*].id, 0)
}

resource "aws_eip" "nat" {
  count = local.create_vpc && var.enable_nat_gateway && !var.reuse_nat_ips ? local.nat_gateway_count : 0

  region = var.region
  domain = "vpc"

  tags = merge(
    {
      "Name" = format(
        "${var.name}-%s",
        element(var.azs, var.single_nat_gateway ? 0 : count.index),
      )
    },
    var.tags,
    var.nat_eip_tags,
  )

  depends_on = [aws_internet_gateway.this]
}

resource "aws_nat_gateway" "this" {
  count = local.create_vpc && var.enable_nat_gateway ? local.nat_gateway_count : 0

  region = var.region
  allocation_id = element(
    local.nat_gateway_ips,
    var.single_nat_gateway ? 0 : count.index,
  )
  subnet_id = element(
    aws_subnet.public[*].id,
    var.single_nat_gateway ? 0 : count.index,
  )

  tags = merge(
    {
      "Name" = format(
        "${var.name}-%s",
        element(var.azs, var.single_nat_gateway ? 0 : count.index),
      )
    },
    var.tags,
    var.nat_gateway_tags,
  )

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route" "private_nat_gateway" {
  count = local.create_vpc && var.enable_nat_gateway && var.create_private_nat_gateway_route ? local.nat_gateway_count : 0

  region                 = var.region
  route_table_id         = element(aws_route_table.private[*].id, count.index)
  destination_cidr_block = var.nat_gateway_destination_cidr_block
  nat_gateway_id         = element(aws_nat_gateway.this[*].id, count.index)
}

resource "aws_vpn_gateway" "this" {
  count = local.create_vpc && var.enable_vpn_gateway ? 1 : 0

  region            = var.region
  vpc_id            = local.vpc_id
  amazon_side_asn   = var.amazon_side_asn
  availability_zone = var.vpn_gateway_az

  tags = merge({ "Name" = var.name }, var.tags, var.vpn_gateway_tags)
}

resource "aws_default_security_group" "this" {
  count = local.create_vpc && var.manage_default_security_group ? 1 : 0

  region = var.region
  vpc_id = aws_vpc.this[0].id

  tags = merge(
    { "Name" = coalesce(var.default_security_group_name, "${var.name}-default") },
    var.tags,
    var.default_security_group_tags,
  )
}

resource "aws_default_network_acl" "this" {
  count = local.create_vpc && var.manage_default_network_acl ? 1 : 0

  region                 = var.region
  default_network_acl_id = aws_vpc.this[0].default_network_acl_id

  tags = merge(
    { "Name" = coalesce(var.default_network_acl_name, "${var.name}-default") },
    var.tags,
    var.default_network_acl_tags,
  )
}

resource "aws_default_route_table" "default" {
  count = local.create_vpc && var.manage_default_route_table ? 1 : 0

  region                 = var.region
  default_route_table_id = aws_vpc.this[0].default_route_table_id

  tags = merge(
    { "Name" = coalesce(var.default_route_table_name, "${var.name}-default") },
    var.tags,
    var.default_route_table_tags,
  )
}

output "vpc_id" {
  value = try(aws_vpc.this[0].id, null)
}

output "vpc_arn" {
  value = try(aws_vpc.this[0].arn, null)
}

output "vpc_cidr_block" {
  value = try(aws_vpc.this[0].cidr_block, null)
}

output "default_security_group_id" {
  value = try(aws_vpc.this[0].default_security_group_id, null)
}

output "default_network_acl_id" {
  value = try(aws_vpc.this[0].default_network_acl_id, null)
}

output "default_route_table_id" {
  value = try(aws_vpc.this[0].default_route_table_id, null)
}

output "vpc_main_route_table_id" {
  value = try(aws_vpc.this[0].main_route_table_id, null)
}

output "vpc_ipv6_cidr_block" {
  value = try(aws_vpc.this[0].ipv6_cidr_block, null)
}

output "vpc_owner_id" {
  value = try(aws_vpc.this[0].owner_id, null)
}

output "igw_id" {
  value = try(aws_internet_gateway.this[0].id, null)
}

output "igw_arn" {
  value = try(aws_internet_gateway.this[0].arn, null)
}

output "public_subnet_objects" {
  value = aws_subnet.public
}

output "public_subnets" {
  value = aws_subnet.public[*].id
}

output "public_subnet_arns" {
  value = aws_subnet.public[*].arn
}

output "public_subnets_cidr_blocks" {
  value = compact(aws_subnet.public[*].cidr_block)
}

output "public_route_table_ids" {
  value = aws_route_table.public[*].id
}

output "public_internet_gateway_route_id" {
  value = try(aws_route.public_internet_gateway[0].id, null)
}

output "public_route_table_association_ids" {
  value = aws_route_table_association.public[*].id
}

output "private_subnet_objects" {
  value = aws_subnet.private
}

output "private_subnets" {
  value = aws_subnet.private[*].id
}

output "private_subnet_arns" {
  value = aws_subnet.private[*].arn
}

output "private_subnets_cidr_blocks" {
  value = compact(aws_subnet.private[*].cidr_block)
}

output "private_route_table_ids" {
  value = aws_route_table.private[*].id
}

output "private_nat_gateway_route_ids" {
  value = aws_route.private_nat_gateway[*].id
}

output "private_ipv6_egress_route_ids" {
  value = aws_route.private_ipv6_egress[*].id
}

output "private_route_table_association_ids" {
  value = aws_route_table_association.private[*].id
}

output "database_subnet_objects" {
  value = aws_subnet.database
}

output "database_subnets" {
  value = aws_subnet.database[*].id
}

output "database_subnet_arns" {
  value = aws_subnet.database[*].arn
}

output "database_subnets_cidr_blocks" {
  value = compact(aws_subnet.database[*].cidr_block)
}

output "database_subnet_group" {
  value = try(aws_db_subnet_group.database[0].id, null)
}

output "database_subnet_group_name" {
  value = try(aws_db_subnet_group.database[0].name, null)
}

output "database_route_table_ids" {
  value = length(aws_route_table.database[*].id) > 0 ? aws_route_table.database[*].id : aws_route_table.private[*].id
}

output "database_internet_gateway_route_id" {
  value = try(aws_route.database_internet_gateway[0].id, null)
}

output "database_nat_gateway_route_ids" {
  value = aws_route.database_nat_gateway[*].id
}

output "database_route_table_association_ids" {
  value = aws_route_table_association.database[*].id
}

output "intra_subnet_objects" {
  value = aws_subnet.intra
}

output "intra_subnets" {
  value = aws_subnet.intra[*].id
}

output "intra_subnet_arns" {
  value = aws_subnet.intra[*].arn
}

output "intra_subnets_cidr_blocks" {
  value = compact(aws_subnet.intra[*].cidr_block)
}

output "intra_route_table_ids" {
  value = aws_route_table.intra[*].id
}

output "intra_route_table_association_ids" {
  value = aws_route_table_association.intra[*].id
}

output "nat_ids" {
  value = aws_eip.nat[*].id
}

output "nat_public_ips" {
  value = var.reuse_nat_ips ? var.external_nat_ips : aws_eip.nat[*].public_ip
}

output "natgw_ids" {
  value = aws_nat_gateway.this[*].id
}

output "natgw_interface_ids" {
  value = aws_nat_gateway.this[*].network_interface_id
}

output "egress_only_internet_gateway_id" {
  value = try(aws_egress_only_internet_gateway.this[0].id, null)
}

output "vgw_id" {
  value = try(aws_vpn_gateway.this[0].id, null)
}

output "vgw_arn" {
  value = try(aws_vpn_gateway.this[0].arn, null)
}

output "azs" {
  value = var.azs
}

output "name" {
  value = var.name
}
```

### alb（10.x）

<!-- module-summary source="terraform-aws-modules/alb/aws" majors="10" -->
```hcl
# not-covered: listeners.*.authenticate_cognito, listeners.*.authenticate_oidc, listeners.*.jwt_validation
# not-covered: listeners.*.mutual_authentication, listeners.*.rules.*.transform
# not-covered: listeners.*.rules.*.actions.*.authenticate_cognito, listeners.*.rules.*.actions.*.authenticate_oidc
# not-covered: listeners.*.rules.*.actions.*.jwt_validation, connection_logs, health_check_logs, ipam_pools
variable "access_logs" {
  type = object({
    bucket  = string
    enabled = optional(bool, true)
    prefix  = optional(string)
  })
  default = null
}

variable "additional_target_group_attachments" {
  type = map(object({
    target_group_key  = string
    target_id         = string
    target_type       = optional(string)
    port              = optional(number)
    availability_zone = optional(string)
  }))
  default = null
}

variable "associate_web_acl" {
  type        = bool
  default     = false
}

variable "create" {
  type        = bool
  default     = true
}

variable "create_security_group" {
  type        = bool
  default     = true
}

variable "default_port" {
  type        = number
  default     = 80
}

variable "default_protocol" {
  type        = string
  default     = "HTTP"
}

variable "enable_deletion_protection" {
  type        = bool
  default     = true
}

variable "internal" {
  type        = bool
  default     = null
}

variable "ip_address_type" {
  type        = string
  default     = null
}

variable "listeners" {
  type = map(object({
    alpn_policy                 = optional(string)
    certificate_arn             = optional(string)
    additional_certificate_arns = optional(list(string), [])
    authenticate_cognito = optional(object({
      authentication_request_extra_params = optional(map(string))
      on_unauthenticated_request          = optional(string)
      scope                               = optional(string)
      session_cookie_name                 = optional(string)
      session_timeout                     = optional(number)
      user_pool_arn                       = optional(string)
      user_pool_client_id                 = optional(string)
      user_pool_domain                    = optional(string)
    }))
    authenticate_oidc = optional(object({
      authentication_request_extra_params = optional(map(string))
      authorization_endpoint              = string
      client_id                           = string
      client_secret                       = string
      issuer                              = string
      on_unauthenticated_request          = optional(string)
      scope                               = optional(string)
      session_cookie_name                 = optional(string)
      session_timeout                     = optional(number)
      token_endpoint                      = string
      user_info_endpoint                  = string
    }))
    fixed_response = optional(object({
      content_type = string
      message_body = optional(string)
      status_code  = optional(string)
    }))
    forward = optional(object({
      target_group_arn = optional(string)
      target_group_key = optional(string)
    }))
    jwt_validation = optional(object({
      issuer        = string
      jwks_endpoint = string
      additional_claim = optional(list(object({
        format = string
        name   = string
        values = list(string)
      })))
    }))
    weighted_forward = optional(object({
      target_groups = optional(list(object({
        target_group_arn = optional(string)
        target_group_key = optional(string)
        weight           = optional(number)
      })))
      stickiness = optional(object({
        duration = optional(number)
        enabled  = optional(bool)
      }))
    }))
    redirect = optional(object({
      host        = optional(string)
      path        = optional(string)
      port        = optional(string)
      protocol    = optional(string)
      query       = optional(string)
      status_code = string
    }))
    mutual_authentication = optional(object({
      advertise_trust_store_ca_names   = optional(string)
      ignore_client_certificate_expiry = optional(bool)
      mode                             = string
      trust_store_arn                  = optional(string)
    }))
    order                                                                 = optional(number)
    port                                                                  = optional(number)
    protocol                                                              = optional(string)
    routing_http_request_x_amzn_mtls_clientcert_header_name               = optional(string)
    routing_http_request_x_amzn_mtls_clientcert_issuer_header_name        = optional(string)
    routing_http_request_x_amzn_mtls_clientcert_leaf_header_name          = optional(string)
    routing_http_request_x_amzn_mtls_clientcert_serial_number_header_name = optional(string)
    routing_http_request_x_amzn_mtls_clientcert_subject_header_name       = optional(string)
    routing_http_request_x_amzn_mtls_clientcert_validity_header_name      = optional(string)
    routing_http_request_x_amzn_tls_cipher_suite_header_name              = optional(string)
    routing_http_request_x_amzn_tls_version_header_name                   = optional(string)
    routing_http_response_access_control_allow_credentials_header_value   = optional(string)
    routing_http_response_access_control_allow_headers_header_value       = optional(string)
    routing_http_response_access_control_allow_methods_header_value       = optional(string)
    routing_http_response_access_control_allow_origin_header_value        = optional(string)
    routing_http_response_access_control_expose_headers_header_value      = optional(string)
    routing_http_response_access_control_max_age_header_value             = optional(string)
    routing_http_response_content_security_policy_header_value            = optional(string)
    routing_http_response_server_enabled                                  = optional(bool)
    routing_http_response_strict_transport_security_header_value          = optional(string)
    routing_http_response_x_content_type_options_header_value             = optional(string)
    routing_http_response_x_frame_options_header_value                    = optional(string)
    ssl_policy                                                            = optional(string)
    tcp_idle_timeout_seconds                                              = optional(number)
    tags                                                                  = optional(map(string), {})

    # Listener rules
    rules = optional(map(object({
      actions = list(object({
        authenticate_cognito = optional(object({
          authentication_request_extra_params = optional(map(string))
          on_unauthenticated_request          = optional(string)
          scope                               = optional(string)
          session_cookie_name                 = optional(string)
          session_timeout                     = optional(number)
          user_pool_arn                       = string
          user_pool_client_id                 = string
          user_pool_domain                    = string
        }))
        authenticate_oidc = optional(object({
          authentication_request_extra_params = optional(map(string))
          authorization_endpoint              = string
          client_id                           = string
          client_secret                       = string
          issuer                              = string
          on_unauthenticated_request          = optional(string)
          scope                               = optional(string)
          session_cookie_name                 = optional(string)
          session_timeout                     = optional(number)
          token_endpoint                      = string
          user_info_endpoint                  = string
        }))
        jwt_validation = optional(object({
          issuer        = string
          jwks_endpoint = string
          additional_claim = optional(list(object({
            format = string
            name   = string
            values = list(string)
          })))
        }))
        fixed_response = optional(object({
          content_type = string
          message_body = optional(string)
          status_code  = optional(string)
        }))
        forward = optional(object({
          target_group_arn = optional(string)
          target_group_key = optional(string)
        }))
        order = optional(number)
        redirect = optional(object({
          host        = optional(string)
          path        = optional(string)
          port        = optional(string)
          protocol    = optional(string)
          query       = optional(string)
          status_code = string
        }))
        weighted_forward = optional(object({
          stickiness = optional(object({
            duration = optional(number)
            enabled  = optional(bool)
          }))
          target_groups = optional(list(object({
            target_group_arn = optional(string)
            target_group_key = optional(string)
            weight           = optional(number)
          })))
        }))
      }))
      conditions = list(object({
        host_header = optional(object({
          values       = optional(list(string))
          regex_values = optional(list(string))
        }))
        http_header = optional(object({
          http_header_name = string
          values           = optional(list(string))
          regex_values     = optional(list(string))
        }))
        http_request_method = optional(object({
          values = list(string)
        }))
        path_pattern = optional(object({
          values       = optional(list(string))
          regex_values = optional(list(string))
        }))
        query_string = optional(list(object({
          key   = optional(string)
          value = string
        })))
        source_ip = optional(object({
          values = list(string)
        }))
      }))
      listener_arn = optional(string)
      listener_key = optional(string)
      priority     = optional(number)
      transform = optional(map(object({
        type = optional(string)
        host_header_rewrite_config = optional(object({
          rewrite = optional(object({
            regex   = string
            replace = string
          }))
        }))
        url_rewrite_config = optional(object({
          rewrite = optional(object({
            regex   = string
            replace = string
          }))
        }))
      })))
      tags = optional(map(string), {})
    })), {})
  }))
  default = {}
}

variable "load_balancer_type" {
  type        = string
  default     = "application"
}

variable "name" {
  type        = string
  default     = null
}

variable "name_prefix" {
  type        = string
  default     = null
}

variable "putin_khuylo" {
  type        = bool
  default     = true
}

variable "region" {
  type        = string
  default     = null
}

variable "route53_records" {
  type = map(object({
    zone_id                = string
    name                   = optional(string)
    type                   = string
    evaluate_target_health = optional(bool, true)
  }))
  default = null
}

variable "security_group_description" {
  type        = string
  default     = null
}

variable "security_group_egress_rules" {
  type = map(object({
    name = optional(string)

    cidr_ipv4                    = optional(string)
    cidr_ipv6                    = optional(string)
    description                  = optional(string)
    from_port                    = optional(string)
    ip_protocol                  = optional(string, "tcp")
    prefix_list_id               = optional(string)
    referenced_security_group_id = optional(string)
    tags                         = optional(map(string), {})
    to_port                      = optional(string)
  }))
  default = null
}

variable "security_group_ingress_rules" {
  type = map(object({
    name = optional(string)

    cidr_ipv4                    = optional(string)
    cidr_ipv6                    = optional(string)
    description                  = optional(string)
    from_port                    = optional(string)
    ip_protocol                  = optional(string, "tcp")
    prefix_list_id               = optional(string)
    referenced_security_group_id = optional(string)
    tags                         = optional(map(string), {})
    to_port                      = optional(string)
  }))
  default = null
}

variable "security_group_name" {
  type        = string
  default     = null
}

variable "security_group_tags" {
  type        = map(string)
  default     = {}
}

variable "security_group_use_name_prefix" {
  type        = bool
  default     = true
}

variable "security_groups" {
  type        = list(string)
  default     = []
}

variable "subnet_mapping" {
  type = list(object({
    allocation_id        = optional(string)
    ipv6_address         = optional(string)
    private_ipv4_address = optional(string)
    subnet_id            = string
  }))
  default = null
}

variable "subnets" {
  type        = list(string)
  default     = null
}

variable "tags" {
  type        = map(string)
  default     = {}
}

variable "target_groups" {
  type = map(object({
    connection_termination = optional(bool)
    deregistration_delay   = optional(number)
    health_check = optional(object({
      enabled             = optional(bool)
      healthy_threshold   = optional(number)
      interval            = optional(number)
      matcher             = optional(string)
      path                = optional(string)
      port                = optional(string)
      protocol            = optional(string)
      timeout             = optional(number)
      unhealthy_threshold = optional(number)
    }))
    ip_address_type                    = optional(string)
    lambda_multi_value_headers_enabled = optional(bool)
    load_balancing_algorithm_type      = optional(string)
    load_balancing_anomaly_mitigation  = optional(string)
    load_balancing_cross_zone_enabled  = optional(string)
    name                               = optional(string)
    name_prefix                        = optional(string)
    port                               = optional(number)
    preserve_client_ip                 = optional(bool)
    protocol                           = optional(string)
    protocol_version                   = optional(string)
    proxy_protocol_v2                  = optional(bool)
    slow_start                         = optional(number)
    stickiness = optional(object({
      cookie_duration = optional(number)
      cookie_name     = optional(string)
      enabled         = optional(bool)
      type            = string
    }))
    tags = optional(map(string))
    target_failover = optional(list(object({
      on_deregistration = string
      on_unhealthy      = string
    })))
    target_group_health = optional(object({
      dns_failover = optional(object({
        minimum_healthy_targets_count      = optional(string)
        minimum_healthy_targets_percentage = optional(string)
      }))
      unhealthy_state_routing = optional(object({
        minimum_healthy_targets_count      = optional(number)
        minimum_healthy_targets_percentage = optional(string)
      }))
    }))
    target_health_state = optional(object({
      enable_unhealthy_connection_termination = bool
      unhealthy_draining_interval             = optional(number)
    }))
    target_type = optional(string)
    target_id   = optional(string)
    vpc_id      = optional(string)
    # Attachment
    create_attachment = optional(bool, true)
    availability_zone = optional(string)
    # Lambda
    attach_lambda_permission  = optional(bool, false)
    lambda_qualifier          = optional(string)
    lambda_statement_id       = optional(string)
    lambda_action             = optional(string)
    lambda_principal          = optional(string)
    lambda_source_account     = optional(string)
    lambda_event_source_token = optional(string)
  }))
  default = null
}

variable "vpc_id" {
  type        = string
  default     = null
}

variable "web_acl_arn" {
  type        = string
  default     = null
}

locals {
  create = var.create && var.putin_khuylo
}

resource "aws_lb" "this" {
  count = local.create ? 1 : 0

  region = var.region

  dynamic "access_logs" {
    for_each = var.access_logs != null ? [var.access_logs] : []

    content {
      bucket  = access_logs.value.bucket
      enabled = access_logs.value.enabled
      prefix  = access_logs.value.prefix
    }
  }

  enable_deletion_protection = var.enable_deletion_protection
  internal                   = var.internal
  ip_address_type            = var.ip_address_type
  load_balancer_type         = var.load_balancer_type
  name                       = var.name
  name_prefix                = var.name_prefix
  security_groups            = var.create_security_group ? concat([aws_security_group.this[0].id], var.security_groups) : var.security_groups

  dynamic "subnet_mapping" {
    for_each = var.subnet_mapping != null ? var.subnet_mapping : []

    content {
      allocation_id        = subnet_mapping.value.allocation_id
      ipv6_address         = subnet_mapping.value.ipv6_address
      private_ipv4_address = subnet_mapping.value.private_ipv4_address
      subnet_id            = subnet_mapping.value.subnet_id
    }
  }

  subnets = var.subnets
  tags    = var.tags
}

resource "aws_lb_listener" "this" {
  for_each = { for k, v in var.listeners : k => v if local.create }

  region = var.region

  certificate_arn = each.value.certificate_arn

  dynamic "default_action" {
    for_each = each.value.fixed_response != null ? [each.value.fixed_response] : []

    content {
      fixed_response {
        content_type = default_action.value.content_type
        message_body = default_action.value.message_body
        status_code  = default_action.value.status_code
      }

      order = each.value.order
      type  = "fixed-response"
    }
  }

  dynamic "default_action" {
    for_each = each.value.forward != null ? [each.value.forward] : []

    content {
      order            = each.value.order
      target_group_arn = try(aws_lb_target_group.this[default_action.value.target_group_key].arn, default_action.value.target_group_arn)
      type             = "forward"
    }
  }

  dynamic "default_action" {
    for_each = each.value.weighted_forward != null ? [each.value.weighted_forward] : []

    content {
      forward {
        dynamic "target_group" {
          for_each = default_action.value.target_groups != null ? default_action.value.target_groups : []

          content {
            arn    = try(aws_lb_target_group.this[target_group.value.target_group_key].arn, target_group.value.target_group_arn)
            weight = target_group.value.weight
          }
        }
      }

      order = each.value.order
      type  = "forward"
    }
  }

  dynamic "default_action" {
    for_each = each.value.redirect != null ? [each.value.redirect] : []

    content {
      redirect {
        host        = default_action.value.host
        path        = default_action.value.path
        port        = default_action.value.port
        protocol    = default_action.value.protocol
        query       = default_action.value.query
        status_code = default_action.value.status_code
      }

      order = each.value.order
      type  = "redirect"
    }
  }

  load_balancer_arn = aws_lb.this[0].arn
  port              = coalesce(each.value.protocol, var.default_protocol) != "GENEVE" ? coalesce(each.value.port, var.default_port) : null
  protocol          = coalesce(each.value.protocol, var.default_protocol) != "GENEVE" ? coalesce(each.value.protocol, var.default_protocol) : null
  ssl_policy        = contains(["HTTPS", "TLS"], coalesce(each.value.protocol, var.default_protocol)) ? coalesce(each.value.ssl_policy, "ELBSecurityPolicy-TLS13-1-3-2021-06") : each.value.ssl_policy

  tags = merge(
    var.tags,
    each.value.tags,
  )
}

locals {
  listener_rules = flatten([
    for listener_key, listener_values in var.listeners : [
      for rule_key, rule_values in listener_values.rules :
      merge(rule_values, {
        listener_key = listener_key
        rule_key     = rule_key
      })
    ]
  ])
}

resource "aws_lb_listener_rule" "this" {
  for_each = { for v in local.listener_rules : "${v.listener_key}/${v.rule_key}" => v if local.create }

  region = var.region

  dynamic "action" {
    for_each = [for action in each.value.actions : action if action.fixed_response != null]

    content {
      dynamic "fixed_response" {
        for_each = [action.value.fixed_response]

        content {
          content_type = fixed_response.value.content_type
          message_body = fixed_response.value.message_body
          status_code  = fixed_response.value.status_code
        }
      }

      order = action.value.order
      type  = "fixed-response"
    }
  }

  dynamic "action" {
    for_each = [for action in each.value.actions : action if action.forward != null]

    content {
      order            = action.value.order
      target_group_arn = try(aws_lb_target_group.this[action.value.forward.target_group_key].arn, action.value.forward.target_group_arn)
      type             = "forward"
    }
  }

  dynamic "action" {
    for_each = [for action in each.value.actions : action if action.redirect != null]

    content {
      dynamic "redirect" {
        for_each = [action.value.redirect]

        content {
          host        = redirect.value.host
          path        = redirect.value.path
          port        = redirect.value.port
          protocol    = redirect.value.protocol
          query       = redirect.value.query
          status_code = redirect.value.status_code
        }
      }

      order = action.value.order
      type  = "redirect"
    }
  }

  dynamic "action" {
    for_each = [for action in each.value.actions : action if action.weighted_forward != null]

    content {
      dynamic "forward" {
        for_each = [action.value.weighted_forward]

        content {
          dynamic "target_group" {
            for_each = forward.value.target_groups

            content {
              arn    = try(aws_lb_target_group.this[target_group.value.target_group_key].arn, target_group.value.target_group_arn)
              weight = target_group.value.weight
            }
          }
        }
      }

      order = action.value.order
      type  = "forward"
    }
  }

  dynamic "condition" {
    for_each = each.value.conditions

    content {
      dynamic "host_header" {
        for_each = condition.value.host_header != null ? [condition.value.host_header] : []

        content {
          values       = host_header.value.values
          regex_values = host_header.value.regex_values
        }
      }

      dynamic "http_header" {
        for_each = condition.value.http_header != null ? [condition.value.http_header] : []

        content {
          http_header_name = http_header.value.http_header_name
          values           = http_header.value.values
          regex_values     = http_header.value.regex_values
        }
      }

      dynamic "http_request_method" {
        for_each = condition.value.http_request_method != null ? [condition.value.http_request_method] : []

        content {
          values = http_request_method.value.values
        }
      }

      dynamic "path_pattern" {
        for_each = condition.value.path_pattern != null ? [condition.value.path_pattern] : []

        content {
          values       = path_pattern.value.values
          regex_values = path_pattern.value.regex_values
        }
      }

      dynamic "query_string" {
        for_each = condition.value.query_string != null ? condition.value.query_string : []

        content {
          key   = query_string.value.key
          value = query_string.value.value
        }
      }

      dynamic "source_ip" {
        for_each = condition.value.source_ip != null ? [condition.value.source_ip] : []

        content {
          values = source_ip.value.values
        }
      }
    }
  }

  listener_arn = try(aws_lb_listener.this[each.value.listener_key].arn, each.value.listener_arn)
  priority     = each.value.priority

  tags = merge(
    var.tags,
    each.value.tags,
  )
}

locals {
  additional_certs = merge(values({
    for listener_key, listener_values in var.listeners : listener_key =>
    {
      for idx, cert_arn in listener_values.additional_certificate_arns :
      "${listener_key}/${idx}" => {
        listener_key    = listener_key
        certificate_arn = cert_arn
      }
    } if length(listener_values.additional_certificate_arns) > 0
  })...)
}

resource "aws_lb_listener_certificate" "this" {
  for_each = { for k, v in local.additional_certs : k => v if local.create }

  region          = var.region
  listener_arn    = aws_lb_listener.this[each.value.listener_key].arn
  certificate_arn = each.value.certificate_arn
}

resource "aws_lb_target_group" "this" {
  for_each = local.create && var.target_groups != null ? var.target_groups : {}

  region = var.region

  dynamic "health_check" {
    for_each = each.value.health_check != null ? [each.value.health_check] : []

    content {
      enabled             = health_check.value.enabled
      healthy_threshold   = health_check.value.healthy_threshold
      interval            = health_check.value.interval
      matcher             = health_check.value.matcher
      path                = health_check.value.path
      port                = health_check.value.port
      protocol            = health_check.value.protocol
      timeout             = health_check.value.timeout
      unhealthy_threshold = health_check.value.unhealthy_threshold
    }
  }

  name             = each.value.name
  name_prefix      = each.value.name_prefix
  port             = each.value.target_type == "lambda" ? null : coalesce(each.value.port, var.default_port)
  protocol         = each.value.target_type == "lambda" ? null : coalesce(each.value.protocol, var.default_protocol)
  protocol_version = each.value.protocol_version
  target_type      = each.value.target_type
  vpc_id           = coalesce(each.value.vpc_id, var.vpc_id)

  tags = merge(
    var.tags,
    each.value.tags,
  )
}

resource "aws_lb_target_group_attachment" "this" {
  for_each = local.create && var.target_groups != null ? { for k, v in var.target_groups : k => v if v.create_attachment } : {}

  region            = var.region
  target_group_arn  = aws_lb_target_group.this[each.key].arn
  target_id         = each.value.target_id
  port              = each.value.target_type == "lambda" ? null : coalesce(each.value.port, var.default_port)
  availability_zone = each.value.availability_zone

  depends_on = [aws_lambda_permission.this]
}

resource "aws_lb_target_group_attachment" "additional" {
  for_each = local.create && var.additional_target_group_attachments != null ? var.additional_target_group_attachments : {}

  region            = var.region
  target_group_arn  = aws_lb_target_group.this[each.value.target_group_key].arn
  target_id         = each.value.target_id
  port              = each.value.target_type == "lambda" ? null : coalesce(each.value.port, var.default_port)
  availability_zone = each.value.availability_zone

  depends_on = [aws_lambda_permission.this]
}

locals {
  lambda_target_groups = var.target_groups != null ? {
    for k, v in var.target_groups :
    (k) => merge(v, { lambda_function_name = split(":", v.target_id)[6] })
    if v.attach_lambda_permission
  } : {}
}

resource "aws_lambda_permission" "this" {
  for_each = { for k, v in local.lambda_target_groups : k => v if local.create }

  region        = var.region
  function_name = each.value.lambda_function_name
  qualifier     = each.value.lambda_qualifier
  statement_id  = coalesce(each.value.lambda_statement_id, "AllowExecutionFromLb")
  action        = coalesce(each.value.lambda_action, "lambda:InvokeFunction")
  principal     = coalesce(each.value.lambda_principal, "elasticloadbalancing.${data.aws_partition.current.dns_suffix}")
  source_arn    = aws_lb_target_group.this[each.key].arn
}

data "aws_partition" "current" {}

locals {
  create_security_group = local.create && var.create_security_group
  security_group_name   = try(coalesce(var.security_group_name, var.name, var.name_prefix), "")
}

resource "aws_security_group" "this" {
  count = local.create_security_group ? 1 : 0

  region      = var.region
  name        = var.security_group_use_name_prefix ? null : local.security_group_name
  name_prefix = var.security_group_use_name_prefix ? "${local.security_group_name}-" : null
  description = coalesce(var.security_group_description, "Security group for ${local.security_group_name} ${var.load_balancer_type} load balancer")
  vpc_id      = var.vpc_id

  tags = merge(var.tags, var.security_group_tags)
}

resource "aws_vpc_security_group_ingress_rule" "this" {
  for_each = local.create_security_group && var.security_group_ingress_rules != null ? var.security_group_ingress_rules : {}

  region                       = var.region
  cidr_ipv4                    = each.value.cidr_ipv4
  cidr_ipv6                    = each.value.cidr_ipv6
  description                  = each.value.description
  from_port                    = each.value.from_port
  ip_protocol                  = each.value.ip_protocol
  prefix_list_id               = each.value.prefix_list_id
  referenced_security_group_id = each.value.referenced_security_group_id
  security_group_id            = aws_security_group.this[0].id

  tags = merge(
    var.tags,
    var.security_group_tags,
    { "Name" = coalesce(each.value.name, "${local.security_group_name}-${each.key}") },
    each.value.tags
  )

  to_port = try(coalesce(each.value.to_port, each.value.from_port), null)
}

resource "aws_vpc_security_group_egress_rule" "this" {
  for_each = local.create_security_group && var.security_group_egress_rules != null ? var.security_group_egress_rules : {}

  region                       = var.region
  cidr_ipv4                    = each.value.cidr_ipv4
  cidr_ipv6                    = each.value.cidr_ipv6
  description                  = each.value.description
  from_port                    = try(coalesce(each.value.from_port, each.value.to_port), null)
  ip_protocol                  = each.value.ip_protocol
  prefix_list_id               = each.value.prefix_list_id
  referenced_security_group_id = each.value.referenced_security_group_id
  security_group_id            = aws_security_group.this[0].id

  tags = merge(
    var.tags,
    var.security_group_tags,
    { "Name" = coalesce(each.value.name, "${local.security_group_name}-${each.key}") },
    each.value.tags
  )

  to_port = each.value.to_port
}

resource "aws_route53_record" "this" {
  for_each = var.create && var.route53_records != null ? var.route53_records : {}

  zone_id = each.value.zone_id
  name    = coalesce(each.value.name, each.key)
  type    = each.value.type

  alias {
    name                   = aws_lb.this[0].dns_name
    zone_id                = aws_lb.this[0].zone_id
    evaluate_target_health = each.value.evaluate_target_health
  }
}

resource "aws_wafv2_web_acl_association" "this" {
  count = var.associate_web_acl ? 1 : 0

  region       = var.region
  resource_arn = aws_lb.this[0].arn
  web_acl_arn  = var.web_acl_arn
}


output "id" {
  value       = try(aws_lb.this[0].id, null)
}

output "arn" {
  value       = try(aws_lb.this[0].arn, null)
}

output "arn_suffix" {
  value       = try(aws_lb.this[0].arn_suffix, null)
}

output "dns_name" {
  value       = try(aws_lb.this[0].dns_name, null)
}

output "zone_id" {
  value       = try(aws_lb.this[0].zone_id, null)
}


output "listeners" {
  value       = aws_lb_listener.this
}

output "listener_rules" {
  value       = aws_lb_listener_rule.this
}


output "target_groups" {
  value       = aws_lb_target_group.this
}


output "security_group_arn" {
  value       = try(aws_security_group.this[0].arn, null)
}

output "security_group_id" {
  value       = try(aws_security_group.this[0].id, null)
}


output "route53_records" {
  value       = aws_route53_record.this
}
```

### rds（7.x）

<!-- module-summary source="terraform-aws-modules/rds/aws" majors="7" -->
```hcl
# not-covered: db_instance_automated_backups_replication, s3_import, restore_to_point_in_time
variable "allocated_storage" {
  type        = number
  default     = null
}

variable "availability_zone" {
  type        = string
  default     = null
}

variable "cloudwatch_log_group_kms_key_id" {
  type        = string
  default     = null
}

variable "cloudwatch_log_group_retention_in_days" {
  type        = number
  default     = 7
}

variable "cloudwatch_log_group_tags" {
  type        = map(string)
  default     = {}
}

variable "create_cloudwatch_log_group" {
  type        = bool
  default     = false
}

variable "create_db_instance" {
  type        = bool
  default     = true
}

variable "create_db_option_group" {
  type        = bool
  default     = true
}

variable "create_db_parameter_group" {
  type        = bool
  default     = true
}

variable "create_db_subnet_group" {
  type        = bool
  default     = false
}

variable "create_monitoring_role" {
  type        = bool
  default     = false
}

variable "db_instance_role_associations" {
  type        = map(string)
  default     = {}
}

variable "db_instance_tags" {
  type        = map(string)
  default     = {}
}

variable "db_name" {
  type        = string
  default     = null
}

variable "db_option_group_tags" {
  type        = map(string)
  default     = {}
}

variable "db_parameter_group_tags" {
  type        = map(string)
  default     = {}
}

variable "db_subnet_group_description" {
  type        = string
  default     = null
}

variable "db_subnet_group_name" {
  type        = string
  default     = null
}

variable "db_subnet_group_tags" {
  type        = map(string)
  default     = {}
}

variable "db_subnet_group_use_name_prefix" {
  type        = bool
  default     = true
}

variable "deletion_protection" {
  type        = bool
  default     = false
}

variable "enabled_cloudwatch_logs_exports" {
  type        = list(string)
  default     = []
}

variable "engine" {
  type        = string
  default     = null
}

variable "engine_version" {
  type        = string
  default     = null
}

variable "family" {
  type        = string
  default     = null
}

variable "final_snapshot_identifier_prefix" {
  type        = string
  default     = "final"
}

variable "identifier" {
  type        = string
}

variable "instance_class" {
  type        = string
  default     = null
}

variable "instance_use_identifier_prefix" {
  type        = bool
  default     = false
}

variable "kms_key_id" {
  type        = string
  default     = null
}

variable "major_engine_version" {
  type        = string
  default     = null
}

variable "manage_master_user_password" {
  type        = bool
  default     = true
}

variable "manage_master_user_password_rotation" {
  type        = bool
  default     = false
}

variable "master_user_password_rotate_immediately" {
  type        = bool
  default     = null
}

variable "master_user_password_rotation_automatically_after_days" {
  type        = number
  default     = null
}

variable "master_user_password_rotation_duration" {
  type        = string
  default     = null
}

variable "master_user_password_rotation_schedule_expression" {
  type        = string
  default     = null
}

variable "monitoring_interval" {
  type        = number
  default     = 0
}

variable "monitoring_role_arn" {
  type        = string
  default     = null
}

variable "monitoring_role_description" {
  type        = string
  default     = null
}

variable "monitoring_role_name" {
  type        = string
  default     = "rds-monitoring-role"
}

variable "monitoring_role_use_name_prefix" {
  type        = bool
  default     = false
}

variable "multi_az" {
  type        = bool
  default     = false
}

variable "option_group_description" {
  type        = string
  default     = null
}

variable "option_group_name" {
  type        = string
  default     = null
}

variable "option_group_use_name_prefix" {
  type        = bool
  default     = true
}

variable "options" {
  type = list(object({
    option_name                    = string
    port                           = optional(number)
    version                        = optional(string)
    db_security_group_memberships  = optional(list(string))
    vpc_security_group_memberships = optional(list(string))
    option_settings = optional(list(object({
      name  = string
      value = string
    })))
  }))
  default = null
}

variable "parameter_group_description" {
  type        = string
  default     = null
}

variable "parameter_group_name" {
  type        = string
  default     = null
}

variable "parameter_group_use_name_prefix" {
  type        = bool
  default     = true
}

variable "parameters" {
  type = list(object({
    name         = string
    value        = string
    apply_method = optional(string)
  }))
  default = null
}

variable "port" {
  type        = string
  default     = null
}

variable "publicly_accessible" {
  type        = bool
  default     = false
}

variable "putin_khuylo" {
  type        = bool
  default     = true
}

variable "region" {
  type        = string
  default     = null
}

variable "replicate_source_db" {
  type        = string
  default     = null
}

variable "skip_final_snapshot" {
  type        = bool
  default     = false
}

variable "snapshot_identifier" {
  type        = string
  default     = null
}

variable "storage_encrypted" {
  type        = bool
  default     = true
}

variable "storage_type" {
  type        = string
  default     = null
}

variable "subnet_ids" {
  type        = list(string)
  default     = []
}

variable "tags" {
  type        = map(string)
  default     = {}
}

variable "username" {
  type        = string
  default     = null
}

variable "vpc_security_group_ids" {
  type        = list(string)
  default     = []
}

locals {
  create_db_subnet_group    = var.create_db_subnet_group && var.putin_khuylo
  create_db_parameter_group = var.create_db_parameter_group && var.putin_khuylo
  create_db_instance        = var.create_db_instance && var.putin_khuylo

  db_subnet_group_name    = var.create_db_subnet_group ? module.db_subnet_group.db_subnet_group_id : var.db_subnet_group_name
  parameter_group_name_id = var.create_db_parameter_group ? module.db_parameter_group.db_parameter_group_id : var.parameter_group_name

  create_db_option_group = var.create_db_option_group && var.engine != "postgres"
  option_group           = local.create_db_option_group ? module.db_option_group.db_option_group_id : var.option_group_name
}

module "db_subnet_group" {
  source = "./modules/db_subnet_group"

  create          = local.create_db_subnet_group
  name            = coalesce(var.db_subnet_group_name, var.identifier)
  use_name_prefix = var.db_subnet_group_use_name_prefix
  description     = var.db_subnet_group_description
  region          = var.region
  subnet_ids      = var.subnet_ids

  tags = merge(var.tags, var.db_subnet_group_tags)
}

module "db_parameter_group" {
  source = "./modules/db_parameter_group"

  create          = local.create_db_parameter_group
  name            = coalesce(var.parameter_group_name, var.identifier)
  use_name_prefix = var.parameter_group_use_name_prefix
  description     = var.parameter_group_description
  family          = var.family
  parameters      = var.parameters
  region          = var.region

  tags = merge(var.tags, var.db_parameter_group_tags)
}

module "db_option_group" {
  source = "./modules/db_option_group"

  create                   = local.create_db_option_group
  name                     = coalesce(var.option_group_name, var.identifier)
  use_name_prefix          = var.option_group_use_name_prefix
  option_group_description = var.option_group_description
  engine_name              = var.engine
  major_engine_version     = var.major_engine_version
  options                  = var.options
  region                   = var.region

  tags = merge(var.tags, var.db_option_group_tags)
}

module "db_instance" {
  source = "./modules/db_instance"

  create                = local.create_db_instance
  identifier            = var.identifier
  use_identifier_prefix = var.instance_use_identifier_prefix

  engine            = var.engine
  engine_version    = var.engine_version
  instance_class    = var.instance_class
  allocated_storage = var.allocated_storage
  storage_type      = var.storage_type
  storage_encrypted = var.storage_encrypted
  kms_key_id        = var.kms_key_id

  db_name                     = var.db_name
  username                    = var.username
  port                        = var.port
  manage_master_user_password = var.manage_master_user_password

  manage_master_user_password_rotation                   = var.manage_master_user_password_rotation
  master_user_password_rotate_immediately                = var.master_user_password_rotate_immediately
  master_user_password_rotation_automatically_after_days = var.master_user_password_rotation_automatically_after_days
  master_user_password_rotation_duration                 = var.master_user_password_rotation_duration
  master_user_password_rotation_schedule_expression      = var.master_user_password_rotation_schedule_expression

  vpc_security_group_ids = var.vpc_security_group_ids
  db_subnet_group_name   = local.db_subnet_group_name
  parameter_group_name   = local.parameter_group_name_id
  option_group_name      = var.engine != "postgres" ? local.option_group : null

  availability_zone   = var.availability_zone
  multi_az            = var.multi_az
  publicly_accessible = var.publicly_accessible

  snapshot_identifier              = var.snapshot_identifier
  skip_final_snapshot              = var.skip_final_snapshot
  final_snapshot_identifier_prefix = var.final_snapshot_identifier_prefix

  replicate_source_db = var.replicate_source_db

  monitoring_interval                  = var.monitoring_interval
  monitoring_role_arn                  = var.monitoring_role_arn
  monitoring_role_name                 = var.monitoring_role_name
  monitoring_role_use_name_prefix      = var.monitoring_role_use_name_prefix
  monitoring_role_description          = var.monitoring_role_description
  create_monitoring_role               = var.create_monitoring_role

  enabled_cloudwatch_logs_exports        = var.enabled_cloudwatch_logs_exports
  create_cloudwatch_log_group            = var.create_cloudwatch_log_group
  cloudwatch_log_group_retention_in_days = var.cloudwatch_log_group_retention_in_days
  cloudwatch_log_group_kms_key_id        = var.cloudwatch_log_group_kms_key_id
  cloudwatch_log_group_tags              = var.cloudwatch_log_group_tags

  deletion_protection = var.deletion_protection

  db_instance_tags = var.db_instance_tags
  region           = var.region
  tags             = var.tags
}

module "db_instance_role_association" {
  source = "./modules/db_instance_role_association"

  for_each = { for k, v in var.db_instance_role_associations : k => v if var.create_db_instance }

  feature_name           = each.key
  role_arn               = each.value
  db_instance_identifier = module.db_instance.db_instance_identifier
  region                 = var.region
}

output "enhanced_monitoring_iam_role_name" {
  value       = module.db_instance.enhanced_monitoring_iam_role_name
}

output "enhanced_monitoring_iam_role_arn" {
  value       = module.db_instance.enhanced_monitoring_iam_role_arn
}

output "db_instance_address" {
  value       = module.db_instance.db_instance_address
}

output "db_instance_arn" {
  value       = module.db_instance.db_instance_arn
}

output "db_instance_availability_zone" {
  value       = module.db_instance.db_instance_availability_zone
}

output "db_instance_endpoint" {
  value       = module.db_instance.db_instance_endpoint
}

output "db_listener_endpoint" {
  value       = module.db_instance.db_listener_endpoint
}

output "db_instance_engine" {
  value       = module.db_instance.db_instance_engine
}

output "db_instance_engine_version_actual" {
  value       = module.db_instance.db_instance_engine_version_actual
}

output "db_instance_hosted_zone_id" {
  value       = module.db_instance.db_instance_hosted_zone_id
}

output "db_instance_identifier" {
  value       = module.db_instance.db_instance_identifier
}

output "db_instance_resource_id" {
  value       = module.db_instance.db_instance_resource_id
}

output "db_instance_status" {
  value       = module.db_instance.db_instance_status
}

output "db_instance_name" {
  value       = module.db_instance.db_instance_name
}

output "db_instance_username" {
  value       = module.db_instance.db_instance_username
  sensitive   = true
}

output "db_instance_domain" {
  value       = module.db_instance.db_instance_domain
}

output "db_instance_domain_auth_secret_arn" {
  value       = module.db_instance.db_instance_domain_auth_secret_arn
}

output "db_instance_domain_dns_ips" {
  value       = module.db_instance.db_instance_domain_dns_ips
}

output "db_instance_domain_fqdn" {
  value       = module.db_instance.db_instance_domain_fqdn
}

output "db_instance_domain_iam_role_name" {
  value       = module.db_instance.db_instance_domain_iam_role_name
}

output "db_instance_domain_ou" {
  value       = module.db_instance.db_instance_domain_ou
}

output "db_instance_port" {
  value       = module.db_instance.db_instance_port
}

output "db_instance_ca_cert_identifier" {
  value       = module.db_instance.db_instance_ca_cert_identifier
}

output "db_instance_master_user_secret_arn" {
  value       = module.db_instance.db_instance_master_user_secret_arn
}

output "db_instance_upgrade_rollout_order" {
  value       = module.db_instance.db_instance_upgrade_rollout_order
}

output "db_subnet_group_id" {
  value       = module.db_subnet_group.db_subnet_group_id
}

output "db_subnet_group_arn" {
  value       = module.db_subnet_group.db_subnet_group_arn
}

output "db_parameter_group_id" {
  value       = module.db_parameter_group.db_parameter_group_id
}

output "db_parameter_group_arn" {
  value       = module.db_parameter_group.db_parameter_group_arn
}

output "db_option_group_id" {
  value       = module.db_option_group.db_option_group_id
}

output "db_option_group_arn" {
  value       = module.db_option_group.db_option_group_arn
}


output "db_instance_cloudwatch_log_groups" {
  value       = module.db_instance.db_instance_cloudwatch_log_groups
}


output "db_instance_role_associations" {
  value       = module.db_instance_role_association
}


output "db_instance_secretsmanager_secret_rotation_enabled" {
  value       = module.db_instance.db_instance_secretsmanager_secret_rotation_enabled
}
```

### rds の db_instance（7.x）

<!-- module-summary source="terraform-aws-modules/rds/aws//modules/db_instance" majors="7" -->
```hcl
variable "allocated_storage" {
  type        = number
  default     = null
}

variable "availability_zone" {
  type        = string
  default     = null
}

variable "cloudwatch_log_group_kms_key_id" {
  type        = string
  default     = null
}

variable "cloudwatch_log_group_retention_in_days" {
  type        = number
  default     = 7
}

variable "cloudwatch_log_group_tags" {
  type        = map(string)
  default     = {}
}

variable "create" {
  type        = bool
  default     = true
}

variable "create_cloudwatch_log_group" {
  type        = bool
  default     = false
}

variable "create_monitoring_role" {
  type        = bool
  default     = false
}

variable "db_instance_tags" {
  type        = map(string)
  default     = {}
}

variable "db_name" {
  type        = string
  default     = null
}

variable "db_subnet_group_name" {
  type        = string
  default     = null
}

variable "deletion_protection" {
  type        = bool
  default     = false
}

variable "enabled_cloudwatch_logs_exports" {
  type        = list(string)
  default     = []
}

variable "engine" {
  type        = string
  default     = null
}

variable "engine_version" {
  type        = string
  default     = null
}

variable "final_snapshot_identifier_prefix" {
  type        = string
  default     = "final"
}

variable "identifier" {
  type        = string
}

variable "instance_class" {
  type        = string
  default     = null
}

variable "kms_key_id" {
  type        = string
  default     = null
}

variable "manage_master_user_password" {
  type        = bool
  default     = true
}

variable "manage_master_user_password_rotation" {
  type        = bool
  default     = false
}

variable "master_user_password_rotate_immediately" {
  type        = bool
  default     = null
}

variable "master_user_password_rotation_automatically_after_days" {
  type        = number
  default     = null
}

variable "master_user_password_rotation_duration" {
  type        = string
  default     = null
}

variable "master_user_password_rotation_schedule_expression" {
  type        = string
  default     = null
}

variable "monitoring_interval" {
  type        = number
  default     = 0
}

variable "monitoring_role_arn" {
  type        = string
  default     = null
}

variable "monitoring_role_description" {
  type        = string
  default     = null
}

variable "monitoring_role_name" {
  type        = string
  default     = "rds-monitoring-role"
}

variable "monitoring_role_use_name_prefix" {
  type        = bool
  default     = false
}

variable "multi_az" {
  type        = bool
  default     = false
}

variable "option_group_name" {
  type        = string
  default     = null
}

variable "parameter_group_name" {
  type        = string
  default     = null
}

variable "port" {
  type        = string
  default     = null
}

variable "publicly_accessible" {
  type        = bool
  default     = false
}

variable "region" {
  type        = string
  default     = null
}

variable "replicate_source_db" {
  type        = string
  default     = null
}

variable "skip_final_snapshot" {
  type        = bool
  default     = false
}

variable "snapshot_identifier" {
  type        = string
  default     = null
}

variable "storage_encrypted" {
  type        = bool
  default     = true
}

variable "storage_type" {
  type        = string
  default     = null
}

variable "tags" {
  type        = map(string)
  default     = {}
}

variable "use_identifier_prefix" {
  type        = bool
  default     = false
}

variable "username" {
  type        = string
  default     = null
}

variable "vpc_security_group_ids" {
  type        = list(string)
  default     = []
}

locals {
  monitoring_role_arn = var.create_monitoring_role ? aws_iam_role.enhanced_monitoring[0].arn : var.monitoring_role_arn

  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.final_snapshot_identifier_prefix}-${var.identifier}-${try(random_id.snapshot_identifier[0].hex, "")}"

  identifier        = var.use_identifier_prefix ? null : var.identifier
  identifier_prefix = var.use_identifier_prefix ? "${var.identifier}-" : null

  monitoring_role_name        = var.monitoring_role_use_name_prefix ? null : var.monitoring_role_name
  monitoring_role_name_prefix = var.monitoring_role_use_name_prefix ? "${var.monitoring_role_name}-" : null

  is_replica = var.replicate_source_db != null
}

data "aws_partition" "current" {}

resource "random_id" "snapshot_identifier" {
  count = var.create && !var.skip_final_snapshot ? 1 : 0

  keepers = {
    id                  = var.identifier
    snapshot_identifier = var.snapshot_identifier
  }

  byte_length = 4
}

resource "aws_db_instance" "this" {
  count = var.create ? 1 : 0

  identifier        = local.identifier
  identifier_prefix = local.identifier_prefix

  engine            = local.is_replica ? null : var.engine
  engine_version    = var.engine_version
  instance_class    = var.instance_class
  allocated_storage = var.allocated_storage
  storage_type      = var.storage_type
  storage_encrypted = var.storage_encrypted
  kms_key_id        = var.kms_key_id

  db_name                     = var.db_name
  username                    = !local.is_replica ? var.username : null
  port                        = var.port
  manage_master_user_password = !local.is_replica && var.manage_master_user_password ? var.manage_master_user_password : null

  vpc_security_group_ids = var.vpc_security_group_ids
  db_subnet_group_name   = var.db_subnet_group_name
  parameter_group_name   = var.parameter_group_name
  option_group_name      = var.option_group_name

  availability_zone   = var.availability_zone
  multi_az            = var.multi_az
  publicly_accessible = var.publicly_accessible

  snapshot_identifier       = var.snapshot_identifier
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = local.final_snapshot_identifier

  replicate_source_db = var.replicate_source_db
  monitoring_interval = var.monitoring_interval
  monitoring_role_arn = var.monitoring_interval > 0 ? local.monitoring_role_arn : null

  enabled_cloudwatch_logs_exports = var.enabled_cloudwatch_logs_exports
  deletion_protection             = var.deletion_protection
  region                          = var.region

  tags = merge(var.tags, var.db_instance_tags)

  depends_on = [aws_cloudwatch_log_group.this]
}

resource "aws_cloudwatch_log_group" "this" {
  for_each = toset([for log in var.enabled_cloudwatch_logs_exports : log if var.create && var.create_cloudwatch_log_group && !var.use_identifier_prefix])

  name              = "/aws/rds/instance/${var.identifier}/${each.value}"
  retention_in_days = var.cloudwatch_log_group_retention_in_days
  kms_key_id        = var.cloudwatch_log_group_kms_key_id
  region            = var.region

  tags = merge(var.tags, var.cloudwatch_log_group_tags)
}

resource "aws_iam_role" "enhanced_monitoring" {
  count = var.create_monitoring_role ? 1 : 0

  name        = local.monitoring_role_name
  name_prefix = local.monitoring_role_name_prefix
  description = var.monitoring_role_description

  tags = merge(
    {
      "Name" = format("%s", var.monitoring_role_name)
    },
    var.tags,
  )
}

resource "aws_iam_role_policy_attachment" "enhanced_monitoring" {
  count = var.create_monitoring_role ? 1 : 0

  role       = aws_iam_role.enhanced_monitoring[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

resource "aws_secretsmanager_secret_rotation" "this" {
  count = var.create && var.manage_master_user_password && var.manage_master_user_password_rotation ? 1 : 0

  secret_id          = aws_db_instance.this[0].master_user_secret[0].secret_arn
  rotate_immediately = var.master_user_password_rotate_immediately
  region             = var.region

  rotation_rules {
    automatically_after_days = var.master_user_password_rotation_automatically_after_days
    duration                 = var.master_user_password_rotation_duration
    schedule_expression      = var.master_user_password_rotation_schedule_expression
  }
}

output "enhanced_monitoring_iam_role_name" {
  value       = try(aws_iam_role.enhanced_monitoring[0].name, null)
}

output "enhanced_monitoring_iam_role_arn" {
  value       = try(aws_iam_role.enhanced_monitoring[0].arn, null)
}

output "db_instance_address" {
  value       = try(aws_db_instance.this[0].address, null)
}

output "db_instance_arn" {
  value       = try(aws_db_instance.this[0].arn, null)
}

output "db_instance_availability_zone" {
  value       = try(aws_db_instance.this[0].availability_zone, null)
}

output "db_instance_endpoint" {
  value       = try(aws_db_instance.this[0].endpoint, null)
}

output "db_listener_endpoint" {
  value       = try(aws_db_instance.this[0].listener_endpoint, null)
}

output "db_instance_engine" {
  value       = try(aws_db_instance.this[0].engine, null)
}

output "db_instance_engine_version_actual" {
  value       = try(aws_db_instance.this[0].engine_version_actual, null)
}

output "db_instance_hosted_zone_id" {
  value       = try(aws_db_instance.this[0].hosted_zone_id, null)
}

output "db_instance_identifier" {
  value       = try(aws_db_instance.this[0].identifier, null)
}

output "db_instance_resource_id" {
  value       = try(aws_db_instance.this[0].resource_id, null)
}

output "db_instance_status" {
  value       = try(aws_db_instance.this[0].status, null)
}

output "db_instance_name" {
  value       = try(aws_db_instance.this[0].db_name, null)
}

output "db_instance_username" {
  value       = try(aws_db_instance.this[0].username, null)
  sensitive   = true
}

output "db_instance_port" {
  value       = try(aws_db_instance.this[0].port, null)
}

output "db_instance_ca_cert_identifier" {
  value       = try(aws_db_instance.this[0].ca_cert_identifier, null)
}

output "db_instance_domain" {
  value       = try(aws_db_instance.this[0].domain, null)
}

output "db_instance_domain_auth_secret_arn" {
  value       = try(aws_db_instance.this[0].domain_auth_secret_arn, null)
}

output "db_instance_domain_dns_ips" {
  value       = try(aws_db_instance.this[0].domain_dns_ips, null)
}

output "db_instance_domain_fqdn" {
  value       = try(aws_db_instance.this[0].domain_fqdn, null)
}

output "db_instance_domain_iam_role_name" {
  value       = try(aws_db_instance.this[0].domain_iam_role_name, null)
}

output "db_instance_domain_ou" {
  value       = try(aws_db_instance.this[0].domain_ou, null)
}

output "db_instance_master_user_secret_arn" {
  value       = try(aws_db_instance.this[0].master_user_secret[0].secret_arn, null)
}

output "db_instance_upgrade_rollout_order" {
  value       = try(aws_db_instance.this[0].upgrade_rollout_order, null)
}


output "db_instance_cloudwatch_log_groups" {
  value       = aws_cloudwatch_log_group.this
}


output "db_instance_secretsmanager_secret_rotation_enabled" {
  value       = try(aws_secretsmanager_secret_rotation.this[0].rotation_enabled, null)
}
```

### rds の db_subnet_group（7.x）

<!-- module-summary source="terraform-aws-modules/rds/aws//modules/db_subnet_group" majors="7" -->
```hcl
variable "create" {
  type        = bool
  default     = true
}

variable "description" {
  type        = string
  default     = null
}

variable "name" {
  type        = string
  default     = ""
}

variable "region" {
  type        = string
  default     = null
}

variable "subnet_ids" {
  type        = list(string)
  default     = []
}

variable "tags" {
  type        = map(string)
  default     = {}
}

variable "use_name_prefix" {
  type        = bool
  default     = true
}

locals {
  name        = var.use_name_prefix ? null : var.name
  name_prefix = var.use_name_prefix ? "${var.name}-" : null

  description = coalesce(var.description, format("%s subnet group", var.name))
}

resource "aws_db_subnet_group" "this" {
  count = var.create ? 1 : 0

  name        = local.name
  name_prefix = local.name_prefix
  description = local.description
  region      = var.region
  subnet_ids  = var.subnet_ids

  tags = merge(
    var.tags,
    {
      "Name" = var.name
    },
  )
}

output "db_subnet_group_id" {
  value       = try(aws_db_subnet_group.this[0].id, null)
}

output "db_subnet_group_arn" {
  value       = try(aws_db_subnet_group.this[0].arn, null)
}
```

### rds の db_parameter_group（7.x）

<!-- module-summary source="terraform-aws-modules/rds/aws//modules/db_parameter_group" majors="7" -->
```hcl
variable "create" {
  type        = bool
  default     = true
}

variable "description" {
  type        = string
  default     = null
}

variable "family" {
  type        = string
  default     = null
}

variable "name" {
  type        = string
  default     = ""
}

variable "parameters" {
  type = list(object({
    name         = string
    value        = string
    apply_method = optional(string)
  }))
  default = null
}

variable "region" {
  type        = string
  default     = null
}

variable "skip_destroy" {
  type        = bool
  default     = null
}

variable "tags" {
  type        = map(string)
  default     = {}
}

variable "use_name_prefix" {
  type        = bool
  default     = true
}

locals {
  name        = var.use_name_prefix ? null : var.name
  name_prefix = var.use_name_prefix ? "${var.name}-" : null

  description = coalesce(var.description, format("%s parameter group", var.name))
}

resource "aws_db_parameter_group" "this" {
  count = var.create ? 1 : 0

  name        = local.name
  name_prefix = local.name_prefix
  description = local.description
  family      = var.family

  dynamic "parameter" {
    for_each = var.parameters != null ? var.parameters : []
    content {
      name         = parameter.value.name
      value        = parameter.value.value
      apply_method = parameter.value.apply_method
    }
  }

  region       = var.region
  skip_destroy = var.skip_destroy

  tags = merge(
    var.tags,
    {
      "Name" = var.name
    },
  )

  lifecycle {
    create_before_destroy = true
  }
}

output "db_parameter_group_id" {
  value       = try(aws_db_parameter_group.this[0].id, null)
}

output "db_parameter_group_arn" {
  value       = try(aws_db_parameter_group.this[0].arn, null)
}
```

### rds の db_option_group（7.x）

<!-- module-summary source="terraform-aws-modules/rds/aws//modules/db_option_group" majors="7" -->
```hcl
variable "create" {
  type        = bool
  default     = true
}

variable "engine_name" {
  type        = string
  default     = null
}

variable "major_engine_version" {
  type        = string
  default     = null
}

variable "name" {
  type        = string
  default     = ""
}

variable "option_group_description" {
  type        = string
  default     = null
}

variable "options" {
  type = list(object({
    option_name                    = string
    port                           = optional(number)
    version                        = optional(string)
    db_security_group_memberships  = optional(list(string))
    vpc_security_group_memberships = optional(list(string))
    option_settings = optional(list(object({
      name  = string
      value = string
    })))
  }))
  default = null
}

variable "region" {
  type        = string
  default     = null
}

variable "skip_destroy" {
  type        = bool
  default     = null
}

variable "tags" {
  type        = map(string)
  default     = {}
}

variable "timeouts" {
  type = object({
    delete = optional(string)
  })
  default = null
}

variable "use_name_prefix" {
  type        = bool
  default     = true
}

locals {
  name        = var.use_name_prefix ? null : var.name
  name_prefix = var.use_name_prefix ? "${var.name}-" : null

  description = coalesce(var.option_group_description, format("%s option group", var.name))
}

resource "aws_db_option_group" "this" {
  count = var.create ? 1 : 0

  name                     = local.name
  name_prefix              = local.name_prefix
  option_group_description = local.description
  engine_name              = var.engine_name
  major_engine_version     = var.major_engine_version

  dynamic "option" {
    for_each = var.options != null ? var.options : []
    content {
      option_name                    = option.value.option_name
      port                           = option.value.port
      version                        = option.value.version
      db_security_group_memberships  = option.value.db_security_group_memberships
      vpc_security_group_memberships = option.value.vpc_security_group_memberships

      dynamic "option_settings" {
        for_each = option.value.option_settings != null ? option.value.option_settings : []
        content {
          name  = option_settings.value.name
          value = option_settings.value.value
        }
      }
    }
  }

  region       = var.region
  skip_destroy = var.skip_destroy

  tags = merge(
    var.tags,
    {
      "Name" = var.name
    },
  )

  dynamic "timeouts" {
    for_each = var.timeouts != null ? [var.timeouts] : []

    content {
      delete = timeouts.value.delete
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

output "db_option_group_id" {
  value       = try(aws_db_option_group.this[0].id, null)
}

output "db_option_group_arn" {
  value       = try(aws_db_option_group.this[0].arn, null)
}
```

### rds の db_instance_role_association（7.x）

<!-- module-summary source="terraform-aws-modules/rds/aws//modules/db_instance_role_association" majors="7" -->
```hcl
variable "create" {
  type        = bool
  default     = true
}

variable "db_instance_identifier" {
  type        = string
  default     = null
}

variable "feature_name" {
  type        = string
  default     = null
}

variable "region" {
  type        = string
  default     = null
}

variable "role_arn" {
  type        = string
  default     = null
}

resource "aws_db_instance_role_association" "this" {
  count = var.create ? 1 : 0

  db_instance_identifier = var.db_instance_identifier
  feature_name           = var.feature_name
  region                 = var.region
  role_arn               = var.role_arn
}

output "db_instance_role_association_id" {
  value       = try(aws_db_instance_role_association.this[0].id, "")
}
```

### eks（21.x）

<!-- module-summary source="terraform-aws-modules/eks/aws" majors="21" -->
```hcl
# not-covered: compute_config, create_auto_mode_iam_resources, outpost_config, identity_providers, node_iam_role_additional_policies
# not-covered: create_cni_ipv6_iam_policy, iam_role_additional_policies, cluster_tags, create_primary_security_group_tags
variable "create" { default = true }
variable "putin_khuylo" { default = true }
variable "region" { default = null }
variable "tags" { default = {} }
variable "prefix_separator" { default = "-" }
variable "name" { default = "" }
variable "kubernetes_version" { default = null }
variable "enabled_log_types" { default = ["audit", "api", "authenticator"] }
variable "authentication_mode" { default = "API_AND_CONFIG_MAP" }
variable "deletion_protection" { default = null }
variable "force_update_version" { default = null }
variable "additional_security_group_ids" { default = [] }
variable "control_plane_subnet_ids" { default = [] }
variable "subnet_ids" { default = [] }
variable "vpc_id" { default = null }
variable "endpoint_private_access" { default = true }
variable "endpoint_public_access" { default = false }
variable "endpoint_public_access_cidrs" { default = ["0.0.0.0/0"] }
variable "ip_family" { default = "ipv4" }
variable "encryption_config" {
  type = object({
    provider_key_arn = optional(string)
    resources        = optional(list(string), ["secrets"])
  })
  default = {}
}
variable "attach_encryption_policy" { default = true }
variable "create_kms_key" { default = true }
variable "kms_key_description" { default = null }
variable "kms_key_aliases" { default = [] }
variable "create_cloudwatch_log_group" { default = true }
variable "cloudwatch_log_group_retention_in_days" { default = 90 }
variable "cloudwatch_log_group_kms_key_id" { default = null }
variable "cloudwatch_log_group_class" { default = null }
variable "cloudwatch_log_group_tags" { default = {} }
variable "create_security_group" { default = true }
variable "security_group_id" { default = "" }
variable "security_group_name" { default = null }
variable "security_group_use_name_prefix" { default = true }
variable "security_group_description" { default = "EKS cluster security group" }
variable "security_group_additional_rules" { default = {} }
variable "security_group_tags" { default = {} }
variable "create_node_security_group" { default = true }
variable "node_security_group_id" { default = "" }
variable "node_security_group_name" { default = null }
variable "node_security_group_use_name_prefix" { default = true }
variable "node_security_group_description" { default = "EKS node shared security group" }
variable "node_security_group_additional_rules" { default = {} }
variable "node_security_group_enable_recommended_rules" { default = true }
variable "node_security_group_tags" { default = {} }
variable "enable_irsa" { default = true }
variable "openid_connect_audiences" { default = [] }
variable "custom_oidc_thumbprints" { default = [] }
variable "create_iam_role" { default = true }
variable "iam_role_arn" { default = null }
variable "iam_role_name" { default = null }
variable "iam_role_use_name_prefix" { default = true }
variable "iam_role_path" { default = null }
variable "iam_role_tags" { default = {} }
variable "encryption_policy_name" { default = null }
variable "encryption_policy_use_name_prefix" { default = true }
variable "enable_cluster_creator_admin_permissions" { default = false }
variable "access_entries" {
  type = map(object({
    kubernetes_groups = optional(list(string))
    principal_arn     = string
    type              = optional(string, "STANDARD")
    user_name         = optional(string)
    tags              = optional(map(string), {})
    policy_associations = optional(map(object({
      policy_arn = string
      access_scope = object({
        namespaces = optional(list(string))
        type       = string
      })
    })), {})
  }))
  default = {}
}
variable "addons" {
  type = map(object({
    name                 = optional(string)
    before_compute       = optional(bool, false)
    most_recent          = optional(bool, true)
    addon_version        = optional(string)
    configuration_values = optional(string)
    service_account_role_arn = optional(string)
    tags                 = optional(map(string), {})
  }))
  default = null
}
variable "dataplane_wait_duration" { default = "30s" }
variable "fargate_profiles" {
  type = map(object({
    create                     = optional(bool)
    name                       = optional(string)
    subnet_ids                 = optional(list(string))
    selectors                  = optional(list(object({ labels = optional(map(string)), namespace = string })))
    create_iam_role            = optional(bool)
    iam_role_arn               = optional(string)
    iam_role_name              = optional(string)
    iam_role_use_name_prefix   = optional(bool)
    iam_role_attach_cni_policy = optional(bool)
    tags                       = optional(map(string))
  }))
  default = null
}
variable "eks_managed_node_groups" {
  type = map(object({
    create                     = optional(bool)
    kubernetes_version         = optional(string)
    name                       = optional(string)
    use_name_prefix            = optional(bool)
    subnet_ids                 = optional(list(string))
    min_size                   = optional(number)
    max_size                   = optional(number)
    desired_size               = optional(number)
    ami_type                   = optional(string)
    capacity_type              = optional(string)
    instance_types             = optional(list(string))
    labels                     = optional(map(string))
    create_launch_template     = optional(bool)
    use_custom_launch_template = optional(bool)
    launch_template_name       = optional(string)
    create_iam_role            = optional(bool)
    iam_role_arn               = optional(string)
    iam_role_name              = optional(string)
    iam_role_use_name_prefix   = optional(bool)
    iam_role_attach_cni_policy = optional(bool)
    iam_role_additional_policies = optional(map(string))
    tags                       = optional(map(string))
  }))
  default = null
}
variable "self_managed_node_groups" {
  type = map(object({
    create                      = optional(bool)
    create_autoscaling_group    = optional(bool)
    name                        = optional(string)
    use_name_prefix             = optional(bool)
    subnet_ids                  = optional(list(string))
    min_size                    = optional(number)
    max_size                    = optional(number)
    desired_size                = optional(number)
    ami_type                    = optional(string)
    instance_type               = optional(string)
    create_launch_template      = optional(bool)
    launch_template_name        = optional(string)
    create_iam_instance_profile = optional(bool)
    iam_role_arn                = optional(string)
    iam_role_name               = optional(string)
    iam_role_use_name_prefix    = optional(bool)
    iam_role_attach_cni_policy  = optional(bool)
    iam_role_additional_policies = optional(map(string))
    create_access_entry         = optional(bool)
    tags                        = optional(map(string))
  }))
  default = null
}

locals {
  kubernetes_network_config = try(aws_eks_cluster.this[0].kubernetes_network_config[0], {})

  create                   = var.create && var.putin_khuylo
  role_arn                 = try(aws_iam_role.this[0].arn, var.iam_role_arn)
  enable_encryption_config = var.encryption_config != null

  security_group_name   = coalesce(var.security_group_name, "${var.name}-cluster")
  create_security_group = local.create && var.create_security_group
  security_group_id     = local.create_security_group ? aws_security_group.cluster[0].id : var.security_group_id

  cluster_security_group_rules = { for k, v in {
    ingress_nodes_443 = {
      description                = "Node groups to cluster API"
      protocol                   = "tcp"
      from_port                  = 443
      to_port                    = 443
      type                       = "ingress"
      source_node_security_group = true
    }
  } : k => v if local.create_node_sg }

  node_sg_name           = coalesce(var.node_security_group_name, "${var.name}-node")
  create_node_sg         = var.create && var.create_node_security_group
  node_security_group_id = local.create_node_sg ? aws_security_group.node[0].id : var.node_security_group_id

  node_security_group_rules = {
    ingress_cluster_443 = {
      description                   = "Cluster API to node groups"
      protocol                      = "tcp"
      from_port                     = 443
      to_port                       = 443
      type                          = "ingress"
      source_cluster_security_group = true
    }
    ingress_cluster_kubelet = {
      description                   = "Cluster API to node kubelets"
      protocol                      = "tcp"
      from_port                     = 10250
      to_port                       = 10250
      type                          = "ingress"
      source_cluster_security_group = true
    }
    ingress_self_coredns_tcp = {
      description = "Node to node CoreDNS"
      protocol    = "tcp"
      from_port   = 53
      to_port     = 53
      type        = "ingress"
      self        = true
    }
    ingress_self_coredns_udp = {
      description = "Node to node CoreDNS UDP"
      protocol    = "udp"
      from_port   = 53
      to_port     = 53
      type        = "ingress"
      self        = true
    }
  }

  node_security_group_recommended_rules = { for k, v in {
    ingress_nodes_ephemeral = {
      description = "Node to node ingress on ephemeral ports"
      protocol    = "tcp"
      from_port   = 1025
      to_port     = 65535
      type        = "ingress"
      self        = true
    }
    ingress_cluster_4443_webhook = {
      description                   = "Cluster API to node 4443/tcp webhook"
      protocol                      = "tcp"
      from_port                     = 4443
      to_port                       = 4443
      type                          = "ingress"
      source_cluster_security_group = true
    }
    ingress_cluster_10251_webhook = {
      description                   = "Cluster API to node 10251/tcp webhook"
      protocol                      = "tcp"
      from_port                     = 10251
      to_port                       = 10251
      type                          = "ingress"
      source_cluster_security_group = true
    }
    ingress_cluster_6443_webhook = {
      description                   = "Cluster API to node 6443/tcp webhook"
      protocol                      = "tcp"
      from_port                     = 6443
      to_port                       = 6443
      type                          = "ingress"
      source_cluster_security_group = true
    }
    ingress_cluster_8443_webhook = {
      description                   = "Cluster API to node 8443/tcp webhook"
      protocol                      = "tcp"
      from_port                     = 8443
      to_port                       = 8443
      type                          = "ingress"
      source_cluster_security_group = true
    }
    ingress_cluster_9443_webhook = {
      description                   = "Cluster API to node 9443/tcp webhook"
      protocol                      = "tcp"
      from_port                     = 9443
      to_port                       = 9443
      type                          = "ingress"
      source_cluster_security_group = true
    }
    egress_all = {
      description      = "Allow all egress"
      protocol         = "-1"
      from_port        = 0
      to_port          = 0
      type             = "egress"
      cidr_blocks      = ["0.0.0.0/0"]
      ipv6_cidr_blocks = var.ip_family == "ipv6" ? ["::/0"] : null
    }
  } : k => v if var.node_security_group_enable_recommended_rules }

  create_oidc_provider = local.create && var.enable_irsa

  create_iam_role        = local.create && var.create_iam_role
  iam_role_name          = coalesce(var.iam_role_name, "${var.name}-cluster")
  iam_role_policy_prefix = "arn:${data.aws_partition.current.partition}:iam::aws:policy"
  cluster_encryption_policy_name = coalesce(var.encryption_policy_name, "${local.iam_role_name}-ClusterEncryption")

  bootstrap_cluster_creator_admin_permissions = { for k, v in {
    cluster_creator = {
      principal_arn = "cluster creator (the caller of Terraform)"
      type          = "STANDARD"
      policy_associations = {
        admin = {
          policy_arn   = "arn:${data.aws_partition.current.partition}:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
          access_scope = { type = "cluster" }
        }
      }
    }
  } : k => v if var.enable_cluster_creator_admin_permissions }

  merged_access_entries = merge(local.bootstrap_cluster_creator_admin_permissions, var.access_entries)

  flattened_access_entries = flatten([
    for entry_key, entry_val in local.merged_access_entries : [
      for pol_key, pol_val in entry_val.policy_associations : {
        principal_arn                 = entry_val.principal_arn
        entry_key                     = entry_key
        pol_key                       = pol_key
        association_policy_arn        = pol_val.policy_arn
        association_access_scope_type = pol_val.access_scope.type
      }
    ]
  ])
}

data "aws_partition" "current" {}

resource "aws_eks_cluster" "this" {
  count = local.create ? 1 : 0

  region                    = var.region
  name                      = var.name
  role_arn                  = local.role_arn
  version                   = var.kubernetes_version
  enabled_cluster_log_types = var.enabled_log_types

  access_config {
    authentication_mode = var.authentication_mode
  }

  vpc_config {
    security_group_ids      = compact(distinct(concat(var.additional_security_group_ids, [local.security_group_id])))
    subnet_ids              = coalescelist(var.control_plane_subnet_ids, var.subnet_ids)
    endpoint_private_access = var.endpoint_private_access
    endpoint_public_access  = var.endpoint_public_access
    public_access_cidrs     = var.endpoint_public_access_cidrs
  }

  dynamic "encryption_config" {
    for_each = local.enable_encryption_config ? [var.encryption_config] : []

    content {
      provider {
        key_arn = var.create_kms_key ? module.kms.key_arn : encryption_config.value.provider_key_arn
      }
      resources = encryption_config.value.resources
    }
  }

  tags = var.tags

  depends_on = [
    aws_iam_role_policy_attachment.this,
    aws_security_group_rule.cluster,
    aws_security_group_rule.node,
    aws_cloudwatch_log_group.this,
  ]
}

resource "aws_cloudwatch_log_group" "this" {
  count = local.create && var.create_cloudwatch_log_group ? 1 : 0

  region            = var.region
  name              = "/aws/eks/${var.name}/cluster"
  retention_in_days = var.cloudwatch_log_group_retention_in_days
  kms_key_id        = var.cloudwatch_log_group_kms_key_id

  tags = merge(var.tags, var.cloudwatch_log_group_tags, { Name = "/aws/eks/${var.name}/cluster" })
}

resource "aws_eks_access_entry" "this" {
  for_each = { for k, v in local.merged_access_entries : k => v if local.create }

  region            = var.region
  cluster_name      = aws_eks_cluster.this[0].id
  kubernetes_groups = try(each.value.kubernetes_groups, null)
  principal_arn     = each.value.principal_arn
  type              = try(each.value.type, null)
  user_name         = try(each.value.user_name, null)

  tags = merge(var.tags, try(each.value.tags, {}))
}

resource "aws_eks_access_policy_association" "this" {
  for_each = { for k, v in local.flattened_access_entries : "${v.entry_key}_${v.pol_key}" => v if local.create }

  region = var.region

  access_scope {
    type = each.value.association_access_scope_type
  }

  cluster_name  = aws_eks_cluster.this[0].id
  policy_arn    = each.value.association_policy_arn
  principal_arn = each.value.principal_arn

  depends_on = [aws_eks_access_entry.this]
}

module "kms" {
  source  = "terraform-aws-modules/kms/aws"
  version = "4.0.0"
  create  = local.create && var.create_kms_key && local.enable_encryption_config

  region      = var.region
  description = coalesce(var.kms_key_description, "${var.name} cluster encryption key")
  key_users   = [local.role_arn]
  aliases     = var.kms_key_aliases
  computed_aliases = {
    cluster = { name = "eks/${var.name}" }
  }
  tags = var.tags
}

resource "aws_security_group" "cluster" {
  count = local.create_security_group ? 1 : 0

  region      = var.region
  name        = var.security_group_use_name_prefix ? null : local.security_group_name
  name_prefix = var.security_group_use_name_prefix ? "${local.security_group_name}${var.prefix_separator}" : null
  description = var.security_group_description
  vpc_id      = var.vpc_id

  tags = merge(var.tags, { "Name" = local.security_group_name }, var.security_group_tags)
}

resource "aws_security_group_rule" "cluster" {
  for_each = { for k, v in merge(
    local.cluster_security_group_rules,
    var.security_group_additional_rules
  ) : k => v if local.create_security_group }

  region                   = var.region
  security_group_id        = aws_security_group.cluster[0].id
  protocol                 = each.value.protocol
  from_port                = each.value.from_port
  to_port                  = each.value.to_port
  type                     = each.value.type
  description              = try(each.value.description, null)
  cidr_blocks              = try(each.value.cidr_blocks, null)
  ipv6_cidr_blocks         = try(each.value.ipv6_cidr_blocks, null)
  prefix_list_ids          = try(each.value.prefix_list_ids, null)
  self                     = try(each.value.self, null)
  source_security_group_id = try(each.value.source_node_security_group, false) ? local.node_security_group_id : try(each.value.source_security_group_id, null)
}

resource "aws_iam_openid_connect_provider" "oidc_provider" {
  count = local.create_oidc_provider ? 1 : 0

  client_id_list  = distinct(compact(concat(["sts.amazonaws.com"], var.openid_connect_audiences)))
  thumbprint_list = var.custom_oidc_thumbprints
  url             = aws_eks_cluster.this[0].identity[0].oidc[0].issuer

  tags = merge({ Name = "${var.name}-eks-irsa" }, var.tags)
}

resource "aws_iam_role" "this" {
  count = local.create_iam_role ? 1 : 0

  name        = var.iam_role_use_name_prefix ? null : local.iam_role_name
  name_prefix = var.iam_role_use_name_prefix ? "${local.iam_role_name}${var.prefix_separator}" : null
  path        = var.iam_role_path

  tags = merge(var.tags, var.iam_role_tags)
}

resource "aws_iam_role_policy_attachment" "this" {
  for_each = { for k, v in {
    AmazonEKSClusterPolicy = "${local.iam_role_policy_prefix}/AmazonEKSClusterPolicy",
  } : k => v if local.create_iam_role }

  policy_arn = each.value
  role       = aws_iam_role.this[0].name
}

resource "aws_iam_role_policy_attachment" "cluster_encryption" {
  count = local.create_iam_role && var.attach_encryption_policy && local.enable_encryption_config ? 1 : 0

  policy_arn = aws_iam_policy.cluster_encryption[0].arn
  role       = aws_iam_role.this[0].name
}

resource "aws_iam_policy" "cluster_encryption" {
  count = local.create_iam_role && var.attach_encryption_policy && local.enable_encryption_config ? 1 : 0

  name        = var.encryption_policy_use_name_prefix ? null : local.cluster_encryption_policy_name
  name_prefix = var.encryption_policy_use_name_prefix ? local.cluster_encryption_policy_name : null
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = ["kms:Encrypt", "kms:Decrypt", "kms:ListGrants", "kms:DescribeKey"]
        Effect   = "Allow"
        Resource = var.create_kms_key ? module.kms.key_arn : var.encryption_config.provider_key_arn
      },
    ]
  })

  tags = var.tags
}

resource "aws_eks_addon" "this" {
  for_each = var.addons != null && local.create ? { for k, v in var.addons : k => v if !v.before_compute } : {}

  region                   = var.region
  cluster_name             = aws_eks_cluster.this[0].id
  addon_name               = coalesce(each.value.name, each.key)
  addon_version            = each.value.addon_version
  configuration_values     = each.value.configuration_values
  service_account_role_arn = each.value.service_account_role_arn

  tags = merge(var.tags, each.value.tags)

  depends_on = [
    module.fargate_profile,
    module.eks_managed_node_group,
    module.self_managed_node_group,
  ]
}

resource "aws_eks_addon" "before_compute" {
  for_each = var.addons != null && local.create ? { for k, v in var.addons : k => v if v.before_compute } : {}

  region                   = var.region
  cluster_name             = aws_eks_cluster.this[0].id
  addon_name               = coalesce(each.value.name, each.key)
  addon_version            = each.value.addon_version
  configuration_values     = each.value.configuration_values
  service_account_role_arn = each.value.service_account_role_arn

  tags = merge(var.tags, each.value.tags)
}

resource "time_sleep" "this" {
  count = var.create ? 1 : 0

  create_duration = var.dataplane_wait_duration

  triggers = {
    name                       = aws_eks_cluster.this[0].id
    endpoint                   = aws_eks_cluster.this[0].endpoint
    kubernetes_version         = aws_eks_cluster.this[0].version
    service_cidr               = var.ip_family == "ipv6" ? try(local.kubernetes_network_config.service_ipv6_cidr, "") : try(local.kubernetes_network_config.service_ipv4_cidr, "")
    certificate_authority_data = aws_eks_cluster.this[0].certificate_authority[0].data
  }
}

resource "aws_security_group" "node" {
  count = local.create_node_sg ? 1 : 0

  region      = var.region
  name        = var.node_security_group_use_name_prefix ? null : local.node_sg_name
  name_prefix = var.node_security_group_use_name_prefix ? "${local.node_sg_name}${var.prefix_separator}" : null
  description = var.node_security_group_description
  vpc_id      = var.vpc_id

  tags = merge(
    var.tags,
    {
      "Name"                              = local.node_sg_name
      "kubernetes.io/cluster/${var.name}" = "owned"
    },
    var.node_security_group_tags
  )
}

resource "aws_security_group_rule" "node" {
  for_each = { for k, v in merge(
    local.node_security_group_rules,
    local.node_security_group_recommended_rules,
    var.node_security_group_additional_rules,
  ) : k => v if local.create_node_sg }

  region                   = var.region
  security_group_id        = aws_security_group.node[0].id
  protocol                 = each.value.protocol
  from_port                = each.value.from_port
  to_port                  = each.value.to_port
  type                     = each.value.type
  description              = try(each.value.description, null)
  cidr_blocks              = try(each.value.cidr_blocks, null)
  ipv6_cidr_blocks         = try(each.value.ipv6_cidr_blocks, null)
  prefix_list_ids          = try(each.value.prefix_list_ids, null)
  self                     = try(each.value.self, null)
  source_security_group_id = try(each.value.source_cluster_security_group, false) ? local.security_group_id : try(each.value.source_security_group_id, null)
}

module "fargate_profile" {
  source = "./modules/fargate-profile"

  for_each = var.create && var.fargate_profiles != null ? var.fargate_profiles : {}

  create                     = each.value.create
  region                     = var.region
  cluster_name               = time_sleep.this[0].triggers["name"]
  cluster_ip_family          = var.ip_family
  name                       = coalesce(each.value.name, each.key)
  subnet_ids                 = coalesce(each.value.subnet_ids, var.subnet_ids)
  selectors                  = each.value.selectors
  create_iam_role            = each.value.create_iam_role
  iam_role_arn               = each.value.iam_role_arn
  iam_role_name              = each.value.iam_role_name
  iam_role_use_name_prefix   = each.value.iam_role_use_name_prefix
  iam_role_attach_cni_policy = each.value.iam_role_attach_cni_policy
  tags                       = merge(var.tags, each.value.tags)
}

module "eks_managed_node_group" {
  source = "./modules/eks-managed-node-group"

  for_each = var.create && var.eks_managed_node_groups != null ? var.eks_managed_node_groups : {}

  create                       = each.value.create
  region                       = var.region
  cluster_name                 = time_sleep.this[0].triggers["name"]
  kubernetes_version           = each.value.kubernetes_version != null ? each.value.kubernetes_version : time_sleep.this[0].triggers["kubernetes_version"]
  cluster_ip_family            = var.ip_family
  name                         = coalesce(each.value.name, each.key)
  use_name_prefix              = each.value.use_name_prefix
  subnet_ids                   = coalesce(each.value.subnet_ids, var.subnet_ids)
  min_size                     = each.value.min_size
  max_size                     = each.value.max_size
  desired_size                 = each.value.desired_size
  ami_type                     = each.value.ami_type
  capacity_type                = each.value.capacity_type
  instance_types               = each.value.instance_types
  labels                       = each.value.labels
  create_launch_template       = each.value.create_launch_template
  use_custom_launch_template   = each.value.use_custom_launch_template
  launch_template_name         = each.value.launch_template_name
  vpc_security_group_ids       = compact([local.node_security_group_id])
  create_iam_role              = each.value.create_iam_role
  iam_role_arn                 = each.value.iam_role_arn
  iam_role_name                = each.value.iam_role_name
  iam_role_use_name_prefix     = each.value.iam_role_use_name_prefix
  iam_role_attach_cni_policy   = each.value.iam_role_attach_cni_policy
  iam_role_additional_policies = each.value.iam_role_additional_policies
  tags                         = merge(var.tags, each.value.tags)
}

module "self_managed_node_group" {
  source = "./modules/self-managed-node-group"

  for_each = var.create && var.self_managed_node_groups != null ? var.self_managed_node_groups : {}

  create                       = each.value.create
  region                       = var.region
  cluster_name                 = time_sleep.this[0].triggers["name"]
  cluster_ip_family            = var.ip_family
  create_autoscaling_group     = each.value.create_autoscaling_group
  name                         = coalesce(each.value.name, each.key)
  use_name_prefix              = each.value.use_name_prefix
  subnet_ids                   = coalesce(each.value.subnet_ids, var.subnet_ids)
  min_size                     = each.value.min_size
  max_size                     = each.value.max_size
  desired_size                 = each.value.desired_size
  ami_type                     = each.value.ami_type
  instance_type                = each.value.instance_type
  create_launch_template       = each.value.create_launch_template
  launch_template_name         = each.value.launch_template_name
  vpc_security_group_ids       = compact([local.node_security_group_id])
  create_iam_instance_profile  = each.value.create_iam_instance_profile
  iam_role_arn                 = each.value.iam_role_arn
  iam_role_name                = each.value.iam_role_name
  iam_role_use_name_prefix     = each.value.iam_role_use_name_prefix
  iam_role_attach_cni_policy   = each.value.iam_role_attach_cni_policy
  iam_role_additional_policies = each.value.iam_role_additional_policies
  create_access_entry          = each.value.create_access_entry
  tags                         = merge(var.tags, each.value.tags)
}

output "cluster_arn" {
  value = try(aws_eks_cluster.this[0].arn, null)
}

output "cluster_certificate_authority_data" {
  value = try(aws_eks_cluster.this[0].certificate_authority[0].data, null)
}

output "cluster_endpoint" {
  value = try(aws_eks_cluster.this[0].endpoint, null)
}

output "cluster_id" {
  value = try(aws_eks_cluster.this[0].cluster_id, "")
}

output "cluster_name" {
  value = try(aws_eks_cluster.this[0].name, "")
}

output "cluster_oidc_issuer_url" {
  value = try(aws_eks_cluster.this[0].identity[0].oidc[0].issuer, null)
}

output "cluster_version" {
  value = try(aws_eks_cluster.this[0].version, null)
}

output "cluster_primary_security_group_id" {
  value = try(aws_eks_cluster.this[0].vpc_config[0].cluster_security_group_id, null)
}

output "access_entries" {
  value = aws_eks_access_entry.this
}

output "kms_key_arn" {
  value = module.kms.key_arn
}

output "kms_key_id" {
  value = module.kms.key_id
}

output "cluster_security_group_arn" {
  value = try(aws_security_group.cluster[0].arn, null)
}

output "cluster_security_group_id" {
  value = try(aws_security_group.cluster[0].id, null)
}

output "node_security_group_arn" {
  value = try(aws_security_group.node[0].arn, null)
}

output "node_security_group_id" {
  value = try(aws_security_group.node[0].id, null)
}

output "oidc_provider" {
  value = try(replace(aws_eks_cluster.this[0].identity[0].oidc[0].issuer, "https://", ""), null)
}

output "oidc_provider_arn" {
  value = try(aws_iam_openid_connect_provider.oidc_provider[0].arn, null)
}

output "cluster_iam_role_name" {
  value = try(aws_iam_role.this[0].name, null)
}

output "cluster_iam_role_arn" {
  value = try(aws_iam_role.this[0].arn, null)
}

output "cluster_addons" {
  value = merge(aws_eks_addon.this, aws_eks_addon.before_compute)
}

output "cloudwatch_log_group_name" {
  value = try(aws_cloudwatch_log_group.this[0].name, null)
}

output "cloudwatch_log_group_arn" {
  value = try(aws_cloudwatch_log_group.this[0].arn, null)
}

output "fargate_profiles" {
  value = module.fargate_profile
}

output "eks_managed_node_groups" {
  value = module.eks_managed_node_group
}

output "self_managed_node_groups" {
  value = module.self_managed_node_group
}
```

### eks の eks-managed-node-group（21.x）

<!-- module-summary source="terraform-aws-modules/eks/aws//modules/eks-managed-node-group" majors="21" -->
```hcl
variable "create" {
  default  = true
  nullable = false
}
variable "region" { default = null }
variable "tags" { default = {} }
variable "cluster_name" { default = "" }
variable "kubernetes_version" { default = null }
variable "cluster_ip_family" {
  default  = "ipv4"
  nullable = false
}
variable "name" { default = "" }
variable "use_name_prefix" {
  default  = true
  nullable = false
}
variable "subnet_ids" { default = null }
variable "min_size" {
  default  = 1
  nullable = false
}
variable "max_size" {
  default  = 3
  nullable = false
}
variable "desired_size" {
  default  = 1
  nullable = false
}
variable "ami_type" {
  default  = "AL2023_x86_64_STANDARD"
  nullable = false
}
variable "capacity_type" {
  default  = "ON_DEMAND"
  nullable = false
}
variable "instance_types" { default = null }
variable "labels" { default = null }
variable "create_launch_template" {
  default  = true
  nullable = false
}
variable "use_custom_launch_template" {
  default  = true
  nullable = false
}
variable "launch_template_name" { default = null }
variable "launch_template_version" { default = null }
variable "launch_template_use_name_prefix" {
  default  = true
  nullable = false
}
variable "vpc_security_group_ids" {
  default  = []
  nullable = false
}
variable "create_iam_role" {
  default  = true
  nullable = false
}
variable "iam_role_arn" { default = null }
variable "iam_role_name" { default = null }
variable "iam_role_use_name_prefix" {
  default  = true
  nullable = false
}
variable "iam_role_attach_cni_policy" {
  default  = true
  nullable = false
}
variable "iam_role_additional_policies" {
  default  = {}
  nullable = false
}

locals {
  launch_template_name   = coalesce(var.launch_template_name, "${var.name}-eks-node-group")
  launch_template_id      = var.create && var.create_launch_template ? try(aws_launch_template.this[0].id, null) : null
  launch_template_version = coalesce(var.launch_template_version, try(aws_launch_template.this[0].default_version, "$Default"))
  create_iam_role        = var.create && var.create_iam_role
  iam_role_name          = coalesce(var.iam_role_name, "${var.name}-eks-node-group")
  iam_role_policy_prefix = "arn:${data.aws_partition.current.partition}:iam::aws:policy"
  ipv4_cni_policy = { for k, v in {
    AmazonEKS_CNI_Policy = "${local.iam_role_policy_prefix}/AmazonEKS_CNI_Policy"
  } : k => v if var.iam_role_attach_cni_policy && var.cluster_ip_family == "ipv4" }
}

data "aws_partition" "current" {}

resource "aws_launch_template" "this" {
  count = var.create && var.create_launch_template && var.use_custom_launch_template ? 1 : 0

  region                 = var.region
  name                   = var.launch_template_use_name_prefix ? null : local.launch_template_name
  name_prefix            = var.launch_template_use_name_prefix ? "${local.launch_template_name}-" : null
  vpc_security_group_ids = var.vpc_security_group_ids

  tags = var.tags

  depends_on = [
    aws_iam_role_policy_attachment.this,
    aws_iam_role_policy_attachment.additional,
  ]
}

resource "aws_eks_node_group" "this" {
  count = var.create ? 1 : 0

  region        = var.region
  cluster_name  = var.cluster_name
  node_role_arn = var.create_iam_role ? aws_iam_role.this[0].arn : var.iam_role_arn
  subnet_ids    = var.subnet_ids

  scaling_config {
    min_size     = var.min_size
    max_size     = var.max_size
    desired_size = var.desired_size
  }

  node_group_name        = var.use_name_prefix ? null : var.name
  node_group_name_prefix = var.use_name_prefix ? "${var.name}-" : null
  ami_type               = var.ami_type
  version                = var.kubernetes_version
  capacity_type          = var.capacity_type
  instance_types         = var.instance_types
  labels                 = var.labels

  dynamic "launch_template" {
    for_each = var.use_custom_launch_template ? [1] : []

    content {
      id      = local.launch_template_id
      version = local.launch_template_version
    }
  }

  tags = merge(var.tags, { Name = var.name })
}

resource "aws_iam_role" "this" {
  count = local.create_iam_role ? 1 : 0

  name        = var.iam_role_use_name_prefix ? null : local.iam_role_name
  name_prefix = var.iam_role_use_name_prefix ? "${local.iam_role_name}-" : null

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "this" {
  for_each = { for k, v in merge(
    {
      AmazonEKSWorkerNodePolicy          = "${local.iam_role_policy_prefix}/AmazonEKSWorkerNodePolicy"
      AmazonEC2ContainerRegistryReadOnly = "${local.iam_role_policy_prefix}/AmazonEC2ContainerRegistryReadOnly"
    },
    local.ipv4_cni_policy,
  ) : k => v if local.create_iam_role }

  policy_arn = each.value
  role       = aws_iam_role.this[0].name
}

resource "aws_iam_role_policy_attachment" "additional" {
  for_each = { for k, v in var.iam_role_additional_policies : k => v if local.create_iam_role }

  policy_arn = each.value
  role       = aws_iam_role.this[0].name
}

output "launch_template_id" {
  value = try(aws_launch_template.this[0].id, null)
}

output "node_group_arn" {
  value = try(aws_eks_node_group.this[0].arn, null)
}

output "node_group_id" {
  value = try(aws_eks_node_group.this[0].id, null)
}

output "node_group_resources" {
  value = try(aws_eks_node_group.this[0].resources, null)
}

output "node_group_autoscaling_group_names" {
  value = try(flatten(aws_eks_node_group.this[0].resources[*].autoscaling_groups[*].name), [])
}

output "iam_role_name" {
  value = try(aws_iam_role.this[0].name, null)
}

output "iam_role_arn" {
  value = try(aws_iam_role.this[0].arn, var.iam_role_arn)
}
```

### eks の fargate-profile（21.x）

<!-- module-summary source="terraform-aws-modules/eks/aws//modules/fargate-profile" majors="21" -->
```hcl
variable "create" {
  default  = true
  nullable = false
}
variable "region" { default = null }
variable "tags" { default = {} }
variable "cluster_name" { default = "" }
variable "cluster_ip_family" {
  default  = "ipv4"
  nullable = false
}
variable "name" { default = "" }
variable "subnet_ids" { default = [] }
variable "selectors" { default = null }
variable "create_iam_role" {
  default  = true
  nullable = false
}
variable "iam_role_arn" { default = null }
variable "iam_role_name" { default = "" }
variable "iam_role_use_name_prefix" {
  default  = true
  nullable = false
}
variable "iam_role_attach_cni_policy" {
  default  = true
  nullable = false
}

locals {
  create_iam_role        = var.create && var.create_iam_role
  iam_role_name          = coalesce(var.iam_role_name, var.name, "fargate-profile")
  iam_role_policy_prefix = "arn:${data.aws_partition.current.partition}:iam::aws:policy"
  ipv4_cni_policy = { for k, v in {
    AmazonEKS_CNI_Policy = "${local.iam_role_policy_prefix}/AmazonEKS_CNI_Policy"
  } : k => v if var.iam_role_attach_cni_policy && var.cluster_ip_family == "ipv4" }
}

data "aws_partition" "current" {}

resource "aws_iam_role" "this" {
  count = local.create_iam_role ? 1 : 0

  name        = var.iam_role_use_name_prefix ? null : local.iam_role_name
  name_prefix = var.iam_role_use_name_prefix ? "${local.iam_role_name}-" : null

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "this" {
  for_each = { for k, v in merge(
    {
      AmazonEKSFargatePodExecutionRolePolicy = "${local.iam_role_policy_prefix}/AmazonEKSFargatePodExecutionRolePolicy"
    },
    local.ipv4_cni_policy,
  ) : k => v if local.create_iam_role }

  policy_arn = each.value
  role       = aws_iam_role.this[0].name
}

resource "aws_eks_fargate_profile" "this" {
  count = var.create ? 1 : 0

  region                 = var.region
  cluster_name           = var.cluster_name
  fargate_profile_name   = var.name
  pod_execution_role_arn = var.create_iam_role ? aws_iam_role.this[0].arn : var.iam_role_arn
  subnet_ids             = var.subnet_ids

  dynamic "selector" {
    for_each = var.selectors != null ? var.selectors : []

    content {
      namespace = selector.value.namespace
      labels    = selector.value.labels
    }
  }

  tags = var.tags
}

output "iam_role_name" {
  value = try(aws_iam_role.this[0].name, null)
}

output "iam_role_arn" {
  value = try(aws_iam_role.this[0].arn, var.iam_role_arn)
}

output "fargate_profile_arn" {
  value = try(aws_eks_fargate_profile.this[0].arn, null)
}

output "fargate_profile_id" {
  value = try(aws_eks_fargate_profile.this[0].id, null)
}

output "fargate_profile_pod_execution_role_arn" {
  value = try(aws_eks_fargate_profile.this[0].pod_execution_role_arn, null)
}
```

### eks の self-managed-node-group（21.x）

<!-- module-summary source="terraform-aws-modules/eks/aws//modules/self-managed-node-group" majors="21" -->
```hcl
variable "create" {
  default  = true
  nullable = false
}
variable "region" { default = null }
variable "tags" { default = {} }
variable "cluster_name" { default = "" }
variable "cluster_ip_family" { default = "ipv4" }
variable "create_autoscaling_group" {
  default  = true
  nullable = false
}
variable "name" { default = "" }
variable "use_name_prefix" {
  default  = true
  nullable = false
}
variable "subnet_ids" { default = null }
variable "min_size" {
  default  = 1
  nullable = false
}
variable "max_size" {
  default  = 3
  nullable = false
}
variable "desired_size" {
  default  = 1
  nullable = false
}
variable "ami_type" {
  default  = "AL2023_x86_64_STANDARD"
  nullable = false
}
variable "instance_type" {
  default  = "m6i.large"
  nullable = false
}
variable "create_launch_template" {
  default  = true
  nullable = false
}
variable "launch_template_name" { default = null }
variable "launch_template_version" { default = null }
variable "launch_template_use_name_prefix" {
  default  = true
  nullable = false
}
variable "vpc_security_group_ids" {
  default  = []
  nullable = false
}
variable "create_iam_instance_profile" {
  default  = true
  nullable = false
}
variable "iam_role_arn" { default = null }
variable "iam_role_name" { default = null }
variable "iam_role_use_name_prefix" {
  default  = true
  nullable = false
}
variable "iam_role_attach_cni_policy" {
  default  = true
  nullable = false
}
variable "iam_role_additional_policies" {
  default  = {}
  nullable = false
}
variable "create_access_entry" {
  default  = true
  nullable = false
}

locals {
  launch_template_name        = coalesce(var.launch_template_name, "${var.name}-node-group")
  launch_template_id          = var.create && var.create_launch_template ? aws_launch_template.this[0].id : null
  launch_template_version     = coalesce(var.launch_template_version, try(aws_launch_template.this[0].default_version, "$Default"))
  create_iam_instance_profile = var.create && var.create_iam_instance_profile
  iam_role_name               = coalesce(var.iam_role_name, "${var.name}-node-group")
  iam_role_policy_prefix      = "arn:${data.aws_partition.current.partition}:iam::aws:policy"
  ipv4_cni_policy = { for k, v in {
    AmazonEKS_CNI_Policy = "${local.iam_role_policy_prefix}/AmazonEKS_CNI_Policy"
  } : k => v if var.iam_role_attach_cni_policy && var.cluster_ip_family == "ipv4" }
}

data "aws_partition" "current" {}

resource "aws_launch_template" "this" {
  count = var.create && var.create_launch_template ? 1 : 0

  region                 = var.region
  name                   = var.launch_template_use_name_prefix ? null : local.launch_template_name
  name_prefix            = var.launch_template_use_name_prefix ? "${local.launch_template_name}-" : null
  instance_type          = var.instance_type
  vpc_security_group_ids = var.vpc_security_group_ids

  iam_instance_profile {
    arn = var.create_iam_instance_profile ? aws_iam_instance_profile.this[0].arn : null
  }

  tags = var.tags

  depends_on = [
    aws_iam_role_policy_attachment.this,
    aws_iam_role_policy_attachment.additional,
  ]
}

resource "aws_autoscaling_group" "this" {
  count = var.create && var.create_autoscaling_group ? 1 : 0

  region              = var.region
  name                = var.use_name_prefix ? null : var.name
  name_prefix         = var.use_name_prefix ? "${var.name}-" : null
  min_size            = var.min_size
  max_size            = var.max_size
  desired_capacity    = var.desired_size
  vpc_zone_identifier = var.subnet_ids

  launch_template {
    id      = local.launch_template_id
    version = local.launch_template_version
  }
}

resource "aws_iam_role" "this" {
  count = local.create_iam_instance_profile ? 1 : 0

  name        = var.iam_role_use_name_prefix ? null : local.iam_role_name
  name_prefix = var.iam_role_use_name_prefix ? "${local.iam_role_name}-" : null

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "this" {
  for_each = { for k, v in merge(
    {
      AmazonEKSWorkerNodePolicy          = "${local.iam_role_policy_prefix}/AmazonEKSWorkerNodePolicy"
      AmazonEC2ContainerRegistryReadOnly = "${local.iam_role_policy_prefix}/AmazonEC2ContainerRegistryReadOnly"
    },
    local.ipv4_cni_policy,
  ) : k => v if local.create_iam_instance_profile }

  policy_arn = each.value
  role       = aws_iam_role.this[0].name
}

resource "aws_iam_role_policy_attachment" "additional" {
  for_each = { for k, v in var.iam_role_additional_policies : k => v if local.create_iam_instance_profile }

  policy_arn = each.value
  role       = aws_iam_role.this[0].name
}

resource "aws_iam_instance_profile" "this" {
  count = local.create_iam_instance_profile ? 1 : 0

  role        = aws_iam_role.this[0].name
  name        = var.iam_role_use_name_prefix ? null : local.iam_role_name
  name_prefix = var.iam_role_use_name_prefix ? "${local.iam_role_name}-" : null

  tags = var.tags
}

resource "aws_eks_access_entry" "this" {
  count = var.create && var.create_access_entry ? 1 : 0

  region        = var.region
  cluster_name  = var.cluster_name
  principal_arn = var.create_iam_instance_profile ? aws_iam_role.this[0].arn : var.iam_role_arn
  type          = startswith(var.ami_type, "WINDOWS_") ? "EC2_WINDOWS" : "EC2_LINUX"

  tags = var.tags
}

output "launch_template_id" {
  value = try(aws_launch_template.this[0].id, null)
}

output "autoscaling_group_name" {
  value = try(aws_autoscaling_group.this[0].name, null)
}

output "autoscaling_group_arn" {
  value = try(aws_autoscaling_group.this[0].arn, null)
}

output "autoscaling_group_id" {
  value = try(aws_autoscaling_group.this[0].id, null)
}

output "iam_role_name" {
  value = try(aws_iam_role.this[0].name, null)
}

output "iam_role_arn" {
  value = try(aws_iam_role.this[0].arn, null)
}

output "iam_instance_profile_arn" {
  value = try(aws_iam_instance_profile.this[0].arn, null)
}
```
