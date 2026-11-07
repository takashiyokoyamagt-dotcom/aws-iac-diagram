"""ARN の文字列の読み方と、合成ノード N-BEDROCK-MODEL（基盤モデル）。E-IAM・E-ENV-STR・E-BEDROCK-EMBEDDING が使う。

- ARN は、文字列か、文字列と `$pseudo`（パーティション・リージョン・アカウント）だけの `$concat`。`arn:<partition>:<service>:<region>:
  <account>:<resource>` に分け、`$pseudo` はパーティション・リージョン・アカウントの位置でだけ認める（リソースの部分に `$pseudo` や
  ワイルドカードがあれば照合しない。v0.1 の E-IAM の決まり。S3 の `<bucket>/*` だけは例外）。
- リソースの部分から、入力の描くノードを名前で引く（`string_targets`）: S3（`<bucket>`・`<bucket>/*`）、DynamoDB（`table/<名前>`）、
  SNS（`<名前>`）、SQS（`<名前>`）、Lambda（`function:<名前>`）、Step Functions（`stateMachine:<名前>`）。名前は型の名前属性
  （`name_attr`）の値で比べる。
- 基盤モデル（`bedrock` の `foundation-model/<model id>`）は、入力にリソースが無いので合成ノード `bedrock_model/<model id の key>`
  （`name`・`label` はモデル ID、`parent: null`、`synthetic: true`。edges.toml の N-BEDROCK-MODEL）にする。

ここは標準ライブラリと core と normalize の view・names・relations_base だけを使う。
"""
from __future__ import annotations

from aws_iac_diagram.core.rules import Rules
from aws_iac_diagram.normalize import view
from aws_iac_diagram.normalize.names import key_of
from aws_iac_diagram.normalize.relations_base import Context

MODEL_TYPE = "bedrock_model"
_PSEUDO = "\x00"

# サービス → (リソースの部分の接頭辞, 描く型)
_BY_NAME = {
    "dynamodb": ("table/", "dynamodb_table"),
    "sns": ("", "sns_topic"),
    "sqs": ("", "sqs_queue"),
    "lambda": ("function:", "lambda_function"),
    "states": ("stateMachine:", "sfn_state_machine"),
}


def arn_text(value) -> str | None:
    """文字列か、文字列と `$pseudo` だけの `$concat` → 文字列（`$pseudo` は印の文字）。ほかは None。"""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and set(value) == {"$concat"}:
        out = ""
        for p in value["$concat"]:
            if isinstance(p, str):
                out += p
            elif isinstance(p, dict) and set(p) == {"$pseudo"}:
                out += _PSEUDO
            else:
                return None
        return out
    return None


def parse_arn(value) -> tuple[str, str] | None:
    """ARN → (サービス, リソースの部分)。リソースの部分に `$pseudo` があれば None。"""
    text = arn_text(value)
    if not text or not text.startswith("arn:"):
        return None
    parts = text.split(":", 5)
    if len(parts) != 6 or _PSEUDO in parts[5] or _PSEUDO in parts[2]:
        return None
    return parts[2], parts[5]


def model_id(value) -> str | None:
    """基盤モデルの ARN（`arn:<partition>:bedrock:<region>::foundation-model/<id>`）→ モデル ID。"""
    p = parse_arn(value)
    if p and p[0] == "bedrock" and p[1].startswith("foundation-model/"):
        mid = p[1][len("foundation-model/"):]
        if mid and "*" not in mid:
            return mid
    return None


def model_node(rules: Rules, mid: str) -> dict:
    row = rules.row(MODEL_TYPE)
    return {"id": f"{MODEL_TYPE}/{key_of(mid)}", "type": MODEL_TYPE, "category": row.category, "name": mid, "label": mid,
            "parent": None, "synthetic": True}


def _by_name(ctx: Context, type_id: str, name: str, region: str | None = None, region_of=None) -> list[str]:
    out = []
    for res in ctx.drawn(type_id):
        if region and region_of is not None and region_of(res.address) and region_of(res.address) != region:
            continue  # ARN のリージョンもリソースのリージョンも文字列で決まり、違う
        attr = ctx.rules.row(type_id).get("name_attr", {}).get(res.fmt)
        if attr and view.plain_str(res.get(attr)) == name:
            out.append(ctx.nodes[res.address]["id"])
    return sorted(out)


def string_targets(ctx: Context, value, models: dict, region_of=None) -> list[str]:
    """ARN の文字列が指すノード（描くノード、または基盤モデルの合成ノード。合成ノードは models に足す）。照合できなければ空。
    `region_of`（address → リソースのリージョンか None）を渡すと、ARN のリージョンが文字列で、リソースのリージョンも決まっていて
    違うものは除く（アカウントは IR に持たないので比べない）。"""
    mid = model_id(value)
    if mid:
        node = model_node(ctx.rules, mid)
        models.setdefault(node["id"], node)
        return [node["id"]]
    p = parse_arn(value)
    if not p:
        return []
    service, res = p
    text = arn_text(value) or ""
    region = text.split(":")[3] if len(text.split(":")) > 3 and _PSEUDO not in text.split(":")[3] else None
    if service == "s3":
        bucket = res[:-2] if res.endswith("/*") else res
        return [] if not bucket or "*" in bucket or "/" in bucket else _by_name(ctx, "s3_bucket", bucket)
    if service in _BY_NAME and "*" not in res:
        prefix, type_id = _BY_NAME[service]
        if res.startswith(prefix) and res[len(prefix):] and "/" not in res[len(prefix):]:
            return _by_name(ctx, type_id, res[len(prefix):], region or None, region_of)
    return []
