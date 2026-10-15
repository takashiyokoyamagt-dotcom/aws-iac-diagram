# vpc-endpoints（CloudFormation 版、JSON）

構成・試すこと・判断の理由は [TF 版の README](../../tf/vpc-endpoints/README.md)。正解 IR は [expected/vpc-endpoints.ir.json](../../../expected/vpc-endpoints.ir.json)。

CFN 版で追加で試すこと:

| 入力の要素 | 期待される扱い |
|---|---|
| JSON 形式（`Fn::Sub`、`Ref`、`Fn::GetAtt` の長い形式） | YAML と同じ IR になる |
| `parameters.json`（`Project=net`。テンプレートの既定値は `example`） | A4 でパラメータファイルの値を使う。既定値のままでは ID が一致しない |
| Interface エンドポイントが3つの別リソース（TF は for_each 1つ） | 同じ3ノード |
| `AWS::EC2::VPCGatewayAttachment` | IGW に統合（M-IGW-ATTACH） |
| `AWS::EC2::FlowLog`（`ResourceType: VPC`） | H-OBSERVABILITY |

TF 版との違い: 網羅分類は TF 38 件、CFN 33 件（IAM のポリシーと data が CFN ではロールの中に入る）。canonical 部は同じ。

- SG の egress: TF の `aws_security_group` は egress を書かないと egress なしになる（Terraform が AWS 既定の全許可の egress を消す）。CFN の `AWS::EC2::SecurityGroup` は `SecurityGroupEgress` を書かないと既定の全許可が残る。この構成ではエンドポイントの SG が該当（TF は egress なし、CFN は全許可）。v0.1 は egress から辺を作らない（relation-resources.md の補足）ので、IR は変わらない。
