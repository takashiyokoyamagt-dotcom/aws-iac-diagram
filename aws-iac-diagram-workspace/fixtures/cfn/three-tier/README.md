# three-tier（CloudFormation 版）

構成・試すこと・判断の理由は [TF 版の README](../../tf/three-tier/README.md)。正解 IR は [expected/three-tier.ir.json](../../../expected/three-tier.ir.json)（`EnvType=dev`）。

CFN 版で追加で試すこと:

| 入力の要素 | 期待される扱い |
|---|---|
| `Parameters`（`EnvType` 既定 dev、`AZ1`／`AZ2`、SSM パラメータ型の `LatestAmiId`） | A4 で既定値を使う |
| `Mappings`（`SubnetConfig`、`EnvConfig`）と `!FindInMap [EnvConfig, !Ref EnvType, …]` | A4 で評価する。IR には影響しない値 |
| `Conditions: IsProd` と `Condition: IsProd`（踏み台と SG）、`!If [IsProd, true, false]` | dev では偽なので `H-COND-FALSE` |
| `AWS::EC2::VPCGatewayAttachment`（TF には無い型） | IGW に統合（M-IGW-ATTACH） |
| `AWS::EC2::SecurityGroupIngress`（別リソース）とインラインの `SecurityGroupIngress` | どちらも R-SG |
| `!GetAtt Database.Endpoint.Address`（タスク定義の環境変数） | サービス → DB は `confirmed` |
| `DependsOn: HttpListener` | 辺にしない |

TF 版との違い: CFN にはインラインのルートが無いので、プライベートのルートも `AWS::EC2::Route`。IAM はロールの `ManagedPolicyArns` に含まれるので TF より1件少ない。網羅分類は TF 39 件、CFN 38 件。

- SG の egress: TF の `aws_security_group` は egress を書かないと egress なしになる（Terraform が AWS 既定の全許可の egress を消す）。CFN の `AWS::EC2::SecurityGroup` は `SecurityGroupEgress` を書かないと既定の全許可が残る。この構成では DB の SG が該当（TF は egress なし、CFN は全許可）。v0.1 は egress から辺を作らない（relation-resources.md の補足）ので、IR は変わらない。
