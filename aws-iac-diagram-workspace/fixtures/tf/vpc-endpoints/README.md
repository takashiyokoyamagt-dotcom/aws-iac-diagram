# vpc-endpoints（VPC＋NAT＋VPC エンドポイント）

- CFN 版: [../../cfn/vpc-endpoints/](../../cfn/vpc-endpoints/README.md)（**JSON**）
- 正解 IR: [expected/vpc-endpoints.ir.json](../../../expected/vpc-endpoints.ir.json)

## 構成

VPC `net`（10.10.0.0/16、2AZ）。パブリック・プライベートのサブネットを各2つ、**AZ ごとに NAT**（プライベートのルートテーブルも AZ ごと）。プライベートのルートテーブルに S3 の Gateway エンドポイント。プライベートサブネットに SSM 用の Interface エンドポイント3つ（ec2messages、ssm、ssmmessages）と、SSM で管理する EC2 1台。VPC フローログあり。

## 何を試すための構成か

| 観点 | 入力の要素 | 期待される扱い |
|---|---|---|
| ルート（A1） | パブリック1つ、プライベートは count で2つのルートテーブル。`aws_route` と関連付け | 公開サブネット → IGW ×2、プライベート 1a → NAT 1a、1c → NAT 1c（AZ ごとに別の NAT） |
| Gateway エンドポイント | `aws_vpc_endpoint.s3`（`route_table_ids`） | エンドポイントは VPC の直下。辺は「そのルートテーブルに関連付いたサブネット → エンドポイント」（R-VPCE-GATEWAY、ラベル `s3 prefix list`） |
| Interface エンドポイント | `for_each = toset(var.interface_endpoints)`、`subnet_ids` は2つ | 3つのノード、それぞれ `spans` にプライベートサブネット2つ |
| SG（A1） | エンドポイントの SG の ingress 1つ（送信元は EC2 の SG）を3つのエンドポイントが共有 | EC2 → 各エンドポイントの3本（`network`、`TCP 443`） |
| A4 | `variables.tf` の `project` の既定値は `example`、`terraform.tfvars` が `net` に上書き | 自動で読む tfvars を評価しないと ID がすべて `example-…` になって一致しない |
| count | EIP・NAT・プライベートのルートテーブル・ルート | インスタンス単位で分類 |
| 非表示 | フローログ、そのロググループと IAM、インスタンスプロファイル、AMI の SSM パラメータ | H-OBSERVABILITY、H-LOGS、H-IAM、H-DATA |

## 判断に迷ったところ

- **EC2 → Interface エンドポイントの kind を `network` にした。** SG が許しているだけで、EC2 が何のために繋ぐか（SSM エージェント）は IR からは分からない。`request` にすると推測が入る。
- **プライベートのルートテーブルは、NAT の辺と S3 エンドポイントの辺の両方に統合する。** ルートテーブル1つが2種類の経路を持つため。規則は R-ROUTE を記録し、エンドポイント側の根拠は辺の根拠（R-VPCE-GATEWAY）に書く。
- **フローログを描かない。** ネットワーク図（B2）では出す余地があるが、全体図の正解としては非表示にした。
- **EC2 → NAT の辺は作らない。** EC2 の SG の egress は `0.0.0.0/0` だけで、相手が決まらない。外に出る経路はサブネット → NAT の辺で分かる。
