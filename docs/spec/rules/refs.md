# 辺にしない参照（`data/rules/refs.toml`）

- **これは開発者向けの説明です（SKILL の外。配りません）。** 表そのもの（スクリプトが実行時に読むデータ）は `skills/aws-iac-diagram/data/rules/`（TOML）にあります。下の表は、そのデータから `aws-iac-diagram-workspace/tools/render_rules.py` が作った生成物です（`<!-- rules-table: … -->` の間は直接直さない。直すのはデータ）。全体は [README.md](README.md)

- 状態: **草案**（手順 1 でデータにした。内容は変えていない。2026-10-17 に規則 ID 付きの表にした〈フェーズ 1 の手順 1〉）。1.8（CRITERIA）の「参照の会計」の 3 番目の分類に使う
- 元は edge-rules.md の 2 章の後半。辺を作る規則（E-ENV-REF など）は [edges.md](edges.md)

## 列

<!-- rules-table: fields-refs -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

**`[[noedge]]`**

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `id` | 文字列 | 必須 | 規則 ID（`E-NOEDGE-` で始まる）。上の行から順に当てはめ、最初に当たった規則を使う |
| `attrs` | 文字列の配列 | 必須 | 参照の属性名（raw IR の path の最後の要素）。TF の書き方で書けば CFN にも当たる（中立キー）。中立キーが同じになる別名は書かない |
| `use` | 文字列の配列 | 必須 | 代わりに使う規則（`R-*` のような前方一致も書ける。空は「描かない」） |
| `match` | 文字列 | 必須 | 当たる参照（原文） |
| `use_text` | 文字列 | 必須 | 代わりに使うところ（原文） |
| `from_class` | 文字列の配列（1 つ以上） | 省略可 | 属性名でなく、参照する側のリソースの class（`merged_into`・`hidden`）で当てる |
| `except_rules` | 文字列の配列 | 省略可 | `from_class` で当たるうち、除く統合の規則（M-*。`refs_as_target` の行） |

**`[[nonode]]`**

| 列 | 型 | 必須 | 意味 |
|---|---|---|---|
| `id` | 文字列 | 必須 | 規則 ID（`E-REF-NONODE`） |
| `target` | 文字列 | 必須 | 参照先（原文） |
| `handling` | 文字列 | 必須 | 扱い（原文） |

<!-- /rules-table -->

**参照先にノードが無いときの参照**（`E-REF-NONODE`。E-ENV-REF・E-KB-STORAGE などの直接の参照に適用）

<!-- rules-table: nonode -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 規則ID | 参照先 | 扱い |
|---|---|---|
| `E-REF-NONODE` | R-* で辺に変換された関係リソース（例: rag の `DATA_SOURCE_ID = aws_bedrockagent_data_source.docs.data_source_id`）、または H-* で非表示のリソース（ロググループ、IAM など） | 辺を作らない。根拠（`sources.*.edges[].evidence`）には、同じ計算リソースから出るほかの辺があればそこに「辺にしなかった参照」として書く。M-* で統合されたリソースへの参照は、**統合先のノードへの参照** として扱う（例: タスク定義 → サービス、DB サブネットグループ → DB） |

<!-- /rules-table -->

**辺にしない参照**（入れ子・統合・権限のための参照。`E-NOEDGE-*`）

参照（raw IR の `references`。docs/spec/ir-schema/ の 7.3）のうち、次の表に当たるものからは辺を作らない。ほかの規則で使うものは、その規則で扱う。参照の属性名は、raw IR の `path` の最後の要素（リストの位置 `[n]` とマップのキー `["k"]` を除いたもの）で、TF と CFN の書き方の両方で照合する。上から順に当てはめ、最初に当たった規則を使う。

<!-- rules-table: noedge -->
<!-- 生成: aws-iac-diagram-workspace/tools/render_rules.py（直接直さない。直すのはデータ data/rules/ の TOML） -->

| 規則ID | 当たる参照（原文） | 機械が読む属性名（中立キー） | 代わりに使うところ |
|---|---|---|---|
| `E-NOEDGE-FROM-RULE` | **参照する側**のリソースが、関係リソース（R-*）、統合（M-*）、非表示（H-*）に分類されたもの（例: `AWS::EC2::VPCGatewayAttachment` の `InternetGatewayId`、`AWS::ApiGateway::Stage` の `DeploymentId`、`AWS::EC2::FlowLog` の `ResourceId`、`AWS::IAM::InstanceProfile` の `Roles`、`AWS::OpenSearchServerless::Index` の `CollectionEndpoint`、`aws_s3_bucket_versioning` の `bucket`、ルート・リスナー・SG のルールの中の参照）。**ただし** `M-ECS-TASKDEF` で統合したタスク定義の中の参照は、統合先のサービスの参照として扱うので、ここには当てない（下の行と E-ENV-REF で扱う） | 参照する側が `merged_into`・`hidden` の規則（`M-ECS-TASKDEF` は除く） | その R-*・M-*・H-* の規則（辺を作るかどうかはその規則が決める） |
| `E-NOEDGE-PLACEMENT` | `vpc_id`／`VpcId`、`subnet_id`・`subnet_ids`・`subnets`／`SubnetId`・`SubnetIds`・`Subnets`、`availability_zone`／`AvailabilityZone`、`db_subnet_group_name`／`DBSubnetGroupName`、`vpc_config`／`VpcConfig` の中のサブネット | `vpc_id`、`subnet_id`、`subnet_ids`、`subnets`、`availability_zone`、`db_subnet_group_name`、`vpc_config` | 入れ子（placement.toml。P-*） |
| `E-NOEDGE-SG` | 計算リソースなどに SG を付ける属性: `security_groups`・`security_group_ids`・`vpc_security_group_ids`／`SecurityGroups`・`SecurityGroupIds`・`VPCSecurityGroups` | `security_groups`、`security_group_ids`、`vpc_security_group_ids`、`VPCSecurityGroups` | R-SG |
| `E-NOEDGE-ROLE` | `role`・`role_arn`・`execution_role_arn`・`task_role_arn`・`iam_instance_profile`／`Role`・`RoleArn`・`ExecutionRoleArn`・`TaskRoleArn`・`IamInstanceProfile`、SAM の `Policies`（ポリシーテンプレートの中の参照も含む） | `role`、`role_arn`、`execution_role_arn`、`task_role_arn`、`iam_instance_profile`、`Policies` | E-IAM |
| `E-NOEDGE-LOG` | ロググループへの参照（`log_group_name`、`awslogs-group`／`LogGroupName`） | `log_group_name`、`awslogs-group` | （描かない） |
| `E-NOEDGE-MERGE` | 参照する側を統合先にする参照: `cluster`／`Cluster`、`task_definition`／`TaskDefinition`、`allocation_id`／`AllocationId` | `cluster`、`task_definition`、`allocation_id` | 統合先のノード（M-*） |
| `E-NOEDGE-DEPENDS` | `depends_on`／`DependsOn` | `depends_on` | （描かない。作る順序だけの依存） |

<!-- /rules-table -->

- この表に無い属性からの参照で、ほかの規則（E-ENV-REF、E-KB-STORAGE、R-* など）にも当たらないものは、正規化で `diagnostics`（code `NORM-UNUSED-REF`、level `info`）に残す。黙って捨てない（CRITERIA の 1.8）。
- 参照先が R-* で辺に変換されたか、H-* で非表示のリソースなら、この表より先に、上の「参照先にノードが無いときの参照」の `E-REF-NONODE` を当てる。
- `path` の最後の要素から除く `["k"]` は、識別子として書けないキー（`aws:SourceArn` など）だけなので、そのときは1つ手前の要素（`ArnEquals` など）が属性名になる。いまの表には、これで判定が変わる行は無い。
- 黒箱のモジュール（`module`）の入力からの辺は、属性名ではなく参照先の型で決める（ir-schema の 2章）。
