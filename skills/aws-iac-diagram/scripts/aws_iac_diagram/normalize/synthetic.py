"""ARN の文字列の読み方と、合成ノード N-BEDROCK-MODEL（基盤モデル）・N-EXT-INTERNET（インターネット）。

- ARN は、文字列か、文字列と `$pseudo`（パーティション・リージョン・アカウント）だけの `$concat`。`arn:<partition>:<service>:<region>:
  <account>:<resource>` に分け、`$pseudo` はパーティション・リージョン・アカウントの位置でだけ認める（リソースの部分に `$pseudo` や
  ワイルドカードがあれば照合しない。v0.1 の E-IAM の決まり。S3 の `<bucket>/*` だけは例外）。
- リソースの部分から、入力の描くノードを名前で引く（`string_targets`）: S3（`<bucket>`・`<bucket>/*`）、DynamoDB（`table/<名前>`）、
  SNS（`<名前>`）、SQS（`<名前>`）、Lambda（`function:<名前>`）、Step Functions（`stateMachine:<名前>`）。名前は型の名前属性
  （`name_attr`）の値で比べる。
- 基盤モデル（`bedrock` の `foundation-model/<model id>`）は、入力にリソースが無いので合成ノード `bedrock_model/<model id の key>`
  （`name`・`label` はモデル ID、`parent: null`、`synthetic: true`。edges.toml の N-BEDROCK-MODEL）にする。
- N-EXT-INTERNET（edges.toml の `[[synthetic]]`）: `external/internet`（label `Internet`、`parent: null`、`synthetic: true`。構成ごとに
  1 つ）と、そこからの辺（`request`、`derived`）。(a) インターネット向けの LB で、付けた SG が `0.0.0.0/0`／`::/0` からの ingress を
  許すもの（relations_sg.py の `SgResult.open_lbs`。TCP のポートの範囲が決まるルールだけで、UDP・ICMP・決まらないものは当たらない）
  → 許すポートのリスナー（R-LB-LISTENER。ラベルはリスナーの `<PROTOCOL> <port>`）
  と、そのリスナーのポートを許す SG のルール（R-SG）と、この規則の 3 つを根拠に internet → LB。**当たるリスナーが無ければ辺を作らない**（relations.md の
  補足「リスナーと SG の両方から導く」。SG だけではプロトコルが分からない）。(b) パブリックな API Gateway: HTTP API（いつも公開。`protocol_type` が WEBSOCKET や決まらないものは除く）と、
  REST API のエンドポイントの種類が `REGIONAL`／`EDGE`（書かなければ既定の `EDGE`。`PRIVATE` や値の決まらないものは公開としない）
  → internet → API（ラベル `HTTPS`）。ノードは、internet からの辺が 1 本でも残ったときだけ足す（edges.py）。

ここは標準ライブラリと core と normalize の view・names・relations_base・relations_lb・relations_sg だけを使う。
"""
from __future__ import annotations

from aws_iac_diagram.core.rules import Rules, neutral_key
from aws_iac_diagram.normalize import relations_lb, view
from aws_iac_diagram.normalize.names import key_of
from aws_iac_diagram.normalize.relations_base import Candidate, Context, make
from aws_iac_diagram.normalize.relations_sg import ALL_TCP, INTERNET, SgResult, internet_facing

MODEL_TYPE = "bedrock_model"
INTERNET_RULE = "N-EXT-INTERNET"
INTERNET_TYPE = "external"
PUBLIC_REST = ("REGIONAL", "EDGE")
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


# ------------------------------------------------------------------ N-EXT-INTERNET

def internet_node(rules: Rules) -> dict:
    row = rules.row(INTERNET_TYPE)
    label = row.get("name_from") or "Internet"
    return {"id": INTERNET, "type": INTERNET_TYPE, "category": row.category, "name": key_of(label), "label": label,
            "parent": None, "synthetic": True}


def covers(rng: tuple[int, int] | None, port: int | None) -> bool:
    """ルールの TCP の範囲（None は TCP を許さない・決まらない）が、リスナーのポート（None は決まらない）を許すか。ポートの決まらない
    リスナーは、全ポートを許すルール（`ALL`・`TCP 0-65535`）にだけ当たる。"""
    if rng is None:
        return False
    if port is None:
        return rng == ALL_TCP
    return rng[0] <= port <= rng[1]


def _lb_candidates(ctx: Context, sg: SgResult) -> list[Candidate]:
    out = []
    for lb in sorted(sg.open_lbs):
        found = sg.open_lbs[lb]
        listeners = relations_lb.listener_candidates(ctx, lb, INTERNET, lambda p, found=found: any(covers(r, p) for _, r in found))
        if not listeners:
            continue
        why = internet_facing(ctx, lb)
        ports = [p for p, _ in listeners]
        # 出したリスナーのポートを許すルールだけを、この辺の根拠にする（TCP 22 だけのルールなどは H-SG-NOEDGE のまま）
        out += [c for _, c in listeners] + [c for c, r in found if any(covers(r, p) for p in ports)]
        out += [make(INTERNET, n, INTERNET_RULE, "request", "", [], texts=(why,)) for n in ctx.nodes_of(lb)]
    return out


def _present(props, *names) -> bool:
    """属性が書かれているか（値が `$unknown` などの印でも書かれているものとする）。"""
    keys = {neutral_key(n) for n in names}
    return isinstance(props, dict) and any(isinstance(k, str) and neutral_key(k) in keys for k in props)


def _endpoint_types(res) -> list[str] | None:
    """REST API のエンドポイントの種類（大文字）。書かれていなければ []、決まらなければ None。"""
    v = res.get("endpoint_configuration")
    if v is None:
        return None if _present(dict(res.props), "endpoint_configuration") else []
    if isinstance(v, list):  # TF のブロック
        v = v[0] if len(v) == 1 else ({} if not v else None)
    if isinstance(v, str):  # SAM の短い形（`EndpointConfiguration: REGIONAL`）
        return [v.upper()]
    if not isinstance(v, dict) or view.is_mark(v):
        return None
    t = view.get(v, "types")
    if t is None:
        t = view.get(v, "type")  # SAM の `EndpointConfiguration.Type`
    if t is None:
        return None if _present(v, "types", "type") else []
    t = t if isinstance(t, list) else [t]
    if not all(isinstance(x, str) for x in t):
        return None
    return [x.upper() for x in t]


def _api_candidates(ctx: Context) -> list[Candidate]:
    out = []
    for res in ctx.drawn("apigw_http_api", "apigw_rest_api"):
        nid = ctx.nodes[res.address]["id"]
        pre = "Properties." if res.fmt == "cfn" else ""
        if ctx.nodes[res.address]["type"] == "apigw_http_api":
            pt = view.plain_str(res.get("protocol_type"))
            if pt is None and _present(dict(res.props), "protocol_type"):
                continue  # 値が決まらない
            if pt is not None and pt.upper() != "HTTP":
                continue  # WebSocket の API は HTTPS の入口として描かない（ir-schema の 8 章）
            why = f"{res.address}.{pre}{'ProtocolType' if pre else 'protocol_type'} ({pt})" if pt else f"{res.address}.Type ({res.type})"
        else:
            types = _endpoint_types(res)
            if types is None or (types and not set(types) & set(PUBLIC_REST)):
                continue
            attr = "EndpointConfiguration" if pre else "endpoint_configuration"
            why = f"{res.address}.{pre}{attr} ({', '.join(types)})" if types else f"{res.address}.{pre}{attr} (既定値 EDGE)"
        out.append(make(INTERNET, nid, INTERNET_RULE, "request", "HTTPS", [], texts=(why,)))
    return out


def internet_candidates(ctx: Context, sg: SgResult) -> list[Candidate]:
    """N-EXT-INTERNET の辺の候補（LB と API Gateway）。"""
    return _lb_candidates(ctx, sg) + _api_candidates(ctx)
