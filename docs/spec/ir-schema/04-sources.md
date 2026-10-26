## 4. 由来部（sources）

```json
"sources": {
  "tf": {
    "root": "fixtures/tf/three-tier",
    "resources": [
      {"address": "aws_lb.app", "type": "aws_lb", "file": "alb.tf", "class": "drawn", "node": "alb/demo-alb"},
      {"address": "aws_lb_listener.http", "type": "aws_lb_listener", "file": "alb.tf", "class": "merged_into",
       "into": ["alb/demo-alb->ecs_service/demo-app", "external/internet->alb/demo-alb"], "rule": "R-LB-LISTENER"},
      {"address": "aws_iam_role.task_execution", "type": "aws_iam_role", "file": "ecs.tf", "class": "hidden", "rule": "H-IAM"}
    ],
    "edges": [
      {"edge": "alb/demo-alb->ecs_service/demo-app", "rules": ["R-LB-LISTENER", "R-LB-TG", "R-SG"],
       "evidence": ["aws_lb_listener.http.default_action.target_group_arn", "aws_ecs_service.app.load_balancer.target_group_arn"]}
    ]
  }
}
```

### 網羅分類（A6）

入力の **すべてのリソース**（TF は `resource` と `data`、CFN は `Resources` の全エントリ）が `resources` にちょうど1回ずつ現れる。

| `class` | 必須の項目 | 意味 |
|---|---|---|
| `drawn` | `node` | そのリソースがノードになった |
| `merged_into` | `into`、`rule` | ほかのノードに統合された（M-*）か、辺に変換された（R-*。このとき `into` は辺の id） |
| `hidden` | `rule` | 図に描かない（H-*）。count が 0・Condition が偽のものも `H-COND-FALSE` でここに入る |
| `unknown` | （なし） | 型が `resource-catalog.md` に無い。分類としては正しく、検証エラーにはしない（終了コードは 0 のまま）。件数と型を `result.json` と `coverage.md` に出す。検証エラー（終了コード 1）になるのは、分類の漏れと重複。主セットで 0 件にするのは評価の基準（[CRITERIA.md](../../../aws-iac-diagram-workspace/evals/CRITERIA.md) の 1.2） |

- `address`: TF は plan と同じ形のインスタンスアドレス（`aws_subnet.public[0]`、`module.vpc.aws_vpc.this[0]`、`data.aws_iam_policy_document.x`、for_each は `aws_vpc_endpoint.interface["ssm"]`）。count が 0 に評価されたブロックはインデックスなし（`aws_instance.bastion`）で1件。CFN は論理ID で、ネストスタックの中は `<親の論理ID>/<論理ID>`（`NetworkStack/Vpc`）。
- `type`: 入力のままの型（`aws_vpc`、`AWS::EC2::VPC`）。
- `file`: `root` からの相対パス。
- `via`（省略可）: 入力の読み方が通常と違うもの。
  - `module_summary`: レジストリモジュール（`terraform-aws-modules/vpc/aws` など）の中身で、ソースを読まずに A5 の要約表（[data/module-summaries/](../../../skills/aws-iac-diagram/data/module-summaries/)）から展開したもの。`file` はモジュール呼び出しのあるファイル（要約表の中のサブモジュールも、最初の呼び出しのファイル）。要約表から展開するのは、その入力で作られる managed リソースだけ（モジュール内部の `data` と、count が 0 になるリソースは載せない）。ローカルモジュールの中のリソースは `via` を付けず、`file` はそのモジュールのファイル（`modules/ecs-service/main.tf`）。
  - `module_blackbox`: 黒箱のモジュールの呼び出し（2章）。
- `file` がルートの外にあるとき（ローカルモジュールの source が `../../` など）は、ルートからの `../` 付きの相対パス（`/` 区切り、`..` 以外の `.` は除く）で書く。
- ノードを作る1つのリソースが、同時にほかのノードの配置を決めることがある（例: `aws_db_subnet_group` は統合されるが、DB の `spans` を決める）。分類は1つだけ書き、ほかの役割は `edges` の根拠や `note` に書く。

### 辺の根拠（edges）

canonical 部の **すべての辺** について、形式ごとに1件ずつ、使った規則（`rules`）と根拠（`evidence`。`アドレス.属性` の形の短い文字列）を書く。**正規化（ツール）が出す根拠は、`<raw の参照の from>.<raw の参照の path>` で始める**（後ろに ` (説明)` を付けてよい）。CRITERIA の 1.8 は、この前方一致で raw の参照と照合する。正解 IR の根拠は人が書いた短い形のままでよい（比較には使わない）。推定（inferred）の辺は、ここが説明 .md の「推定した辺の一覧」の元になる（A3）。
