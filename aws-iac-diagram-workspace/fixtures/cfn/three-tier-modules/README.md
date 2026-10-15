# three-tier-modules（CloudFormation 版、ネストスタック）

構成・試すこと・判断の理由は [TF 版の README](../../tf/three-tier-modules/README.md)。正解 IR は [expected/three-tier-modules.ir.json](../../../expected/three-tier-modules.ir.json)（canonical 部は three-tier と同じ）。

| ファイル | 中身 | TF 版で対応するもの |
|---|---|---|
| `root.yaml` | `AWS::CloudFormation::Stack` 5つ（`TemplateURL` はローカルパス） | ルートモジュール |
| `network.yaml` | VPC、サブネット6、IGW、NAT、ルート、DB サブネットグループ | `module.vpc` |
| `alb.yaml` | ALB、SG、ターゲットグループ、リスナー | `module.alb` |
| `security.yaml` | app と DB の SG | `module.app` の SG と、ルートの `aws_security_group.db` |
| `database.yaml` | RDS インスタンス | `module.db` |
| `service.yaml` | ECS クラスタ・ロググループ・ロール・タスク定義・サービス | `module.app` |

CFN 版で追加で試すこと:

| 入力の要素 | 期待される扱い |
|---|---|
| ネストスタック（ローカルの `TemplateURL`） | 子テンプレートを展開する。スタック自体は H-NESTED-STACK。論理ID は `NetworkStack/Vpc` |
| 親の `!GetAtt NetworkStack.Outputs.X` → 子の `Parameters` → `!Ref` | スタックの境界をまたいで参照をたどる。サービス → DB は `confirmed`（`DatabaseStack.Outputs.DbAddress` → `DbHost` → 環境変数 `DB_HOST`） |
| `List<AWS::EC2::Subnet::Id>` 型のパラメータに `!Join` した文字列を渡す | サブネットの参照としてたどる（ALB・サービスの `spans`） |

- **SG の置き場所が TF 版と違う。** TF では DB の SG がルート、app の SG がローカルモジュールにあり、リソース単位で依存するので循環しない。ネストスタックはスタック単位で依存するので、同じ分け方だと Service → Database → Service と循環する。SG を1つのスタック（`security.yaml`）にまとめて避けた。SG は辺に変換されるので図は同じ。
- SG の egress: TF の DB の SG は egress を書いていないので egress なし（Terraform が既定の全許可を消す）、CFN の `DbSecurityGroup` は既定の全許可が残る。ALB の SG はどちらも VPC の CIDR への全許可。v0.1 は egress から辺を作らないので IR は変わらない。
- `TemplateURL` がローカルパスなので cfn-lint の W3002 が出る。意図どおりなので、各スタックの `Metadata` で無効にしている。
