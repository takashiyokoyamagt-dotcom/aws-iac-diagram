## 1. 全体の構造

```json
{
  "ir_version": "1.0",
  "stage": "normalized",
  "name": "three-tier",
  "description": "…",
  "notes": ["判断の記録（比較には使わない）"],
  "evaluation": {"tf": {"var_files": ["env/dev.tfvars"], "vars": {}}, "cfn": {"parameters": {"EnvType": "dev"}}, "assumptions": []},
  "nodes": [ … ],
  "edges": [ … ],
  "sources": {"tf": { … }, "cfn": { … }}
}
```

| キー | 部 | 内容 |
|---|---|---|
| `nodes`, `edges` | **canonical 部** | 図に描く内容。入力の形式（TF／CFN）によらない。TF 版と CFN 版の比較はここだけで行う |
| `sources.tf`, `sources.cfn` | **由来部** | 入力の各リソースがどう扱われたか（網羅分類 A6）と、各辺の根拠。形式ごとに1つ |
| `evaluation` | 前提 | 変数・パラメータの評価（A4）に使った値。tfvars のどれを選んだか、など |
| `name`, `description`, `notes` | 説明 | `notes` は判断理由。比較には使わない |
| `diagnostics` | 記録 | 省略可。正規化で残した記録（「使わなかった参照」など。形は 7.5、code は `NORM-…`）。比較には使わない |

**同じ構成の TF 版と CFN 版は canonical 部が一致する**（フェーズ3 の完了基準。canonical 部は正規化の後に作る）。由来部は形式ごとに違ってよい（例: TF には `aws_s3_bucket_versioning` のような設定だけのリソースがあり、CFN ではそれが `AWS::S3::Bucket` のプロパティになる。逆に CFN には `AWS::EC2::VPCGatewayAttachment` があり、TF では `aws_internet_gateway.vpc_id` で表す）。
