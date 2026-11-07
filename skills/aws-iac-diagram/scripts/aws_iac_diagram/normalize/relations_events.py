"""イベント・データの流れの関係リソース: R-LAMBDA-ESM、R-SNS-SUBSCRIPTION、R-S3-NOTIFICATION、R-BEDROCK-DATA-SOURCE、
R-EVENTS-TARGET、R-GLUE-TRIGGER と、許可の関係リソース R-LAMBDA-PERMISSION、R-SQS-QUEUE-POLICY、R-SNS-TOPIC-POLICY。

向きはデータの流れ（A2）: ESM はイベントソース → 関数（関数がポーリングするが）、データソースはバケット → ナレッジベース。
プロパティの形（relations.toml の `cfn_props`・`sam`）も読む: `AWS::SNS::Topic.Subscription`、`AWS::S3::Bucket.NotificationConfiguration`、
`AWS::Events::Rule.Targets`、SAM の関数の `Events`（`DynamoDB`・`Kinesis`・`SQS` → ESM、`SNS` → 購読）。

許可の関係リソース（R-LAMBDA-PERMISSION・R-SQS-QUEUE-POLICY・R-SNS-TOPIC-POLICY）は、同じ組の辺がほかの規則でできていれば
その根拠に加わるだけで、無いときだけ自分の kind（候補の `weak_kind`）で辺を作る。送信元が入力のリソースに決まらなければ辺を作らず、
分類の確定で fallback の H-IAM になる。送信元は、Lambda の許可は `source_arn`／`SourceArn` の中の参照（無ければ S3 の ARN の文字列
`arn:<partition>:s3:::<名前>` とバケットの名前の一致）、キュー・トピックのポリシーは条件の `aws:SourceArn` の参照だけ
（`Principal.Service` だけでは送信元のリソースが決まらない）。

ここは標準ライブラリと core と normalize の view・classify・relations_base だけを使う。
"""
from __future__ import annotations

import re

from aws_iac_diagram.core.rules import neutral_key
from aws_iac_diagram.normalize import view
from aws_iac_diagram.normalize.relations_base import Candidate, Context, make, path_keys, value_at

SAM_FUNCTION = "AWS::Serverless::Function"
SOURCE_ARN = neutral_key("aws:SourceArn")
# 送信元に使う条件の演算子（中立キー）。Deny の文や、否定・存在の演算子（ArnNotEquals、Null など）の条件は使わない
ALLOW_OPERATORS = frozenset(neutral_key(x) for x in ("ArnEquals", "ArnLike", "StringEquals", "StringLike"))
_S3_ARN = re.compile(r"^arn:[^:]*:s3:::([^/*]+)$")
_PARTITION = "\x00partition\x00"


def _pairs(ctx: Context, rule: str, kind: str | None, src_refs: list[dict], dst_refs: list[dict], members=(), weak_kind=None,
           src_types=None, dst_types=None) -> list[Candidate]:
    out = []
    for s, s_ref in ctx.targets(src_refs, src_types):
        for d, d_ref in ctx.targets(dst_refs, dst_types):
            out.append(make(s, d, rule, kind, "", [s_ref, d_ref], members, weak_kind))
    return out


def _sam_events(ctx: Context, types: dict[str, str]) -> list[tuple[object, str, str]]:
    """SAM の関数の Events のうち、Type が types のもの → (関数, イベントの名前, 参照のプロパティ名)。"""
    out = []
    if ctx.fmt != "cfn":
        return out
    for fn in ctx.drawn("lambda_function"):
        events = fn.get("Events") if fn.type == SAM_FUNCTION else None
        if isinstance(events, dict):
            for name in sorted(events):
                t = events[name].get("Type") if isinstance(events[name], dict) else None
                if t in types:
                    out.append((fn, name, types[t]))
    return out


def _sam_pairs(ctx: Context, rule: str, kind: str, types: dict[str, str]) -> list[Candidate]:
    """SAM のイベント: 参照先（ストリーム・キュー・トピック）→ 関数。"""
    out = []
    for fn, name, key in _sam_events(ctx, types):
        fn_node = ctx.nodes[fn.address]["id"]
        for s, ref in ctx.targets(ctx.refs_under(fn.address, f"Properties.Events.{name}.Properties.{key}")):
            out.append(make(s, fn_node, rule, kind, "", [ref]))
    return out


def esm(ctx: Context) -> list[Candidate]:
    rule = "R-LAMBDA-ESM"
    out = []
    for r in ctx.resources(rule):
        out += _pairs(ctx, rule, "event", ctx.refs(r.address, ("eventsourcearn",)), ctx.refs(r.address, ("functionname",)), (r.address,))
    return out + _sam_pairs(ctx, rule, "event", {"DynamoDB": "Stream", "Kinesis": "Stream", "SQS": "Queue"})


def sns_subscription(ctx: Context) -> list[Candidate]:
    rule = "R-SNS-SUBSCRIPTION"
    out = []
    for r in ctx.resources(rule):
        out += _pairs(ctx, rule, "event", ctx.refs(r.address, ("topicarn",)), ctx.refs(r.address, ("endpoint",)), (r.address,))
    for topic in ctx.drawn("sns_topic"):
        t_node = ctx.nodes[topic.address]["id"]
        for d, ref in ctx.targets(ctx.refs(topic.address, ("subscription", "endpoint"))) if ctx.fmt == "cfn" else []:
            out.append(make(t_node, d, rule, "event", "", [ref]))
    return out + _sam_pairs(ctx, rule, "event", {"SNS": "Topic"})


def s3_notification(ctx: Context) -> list[Candidate]:
    rule = "R-S3-NOTIFICATION"
    targets = (("lambdafunction", "lambdafunctionarn"), ("queue", "queuearn"), ("topic", "topicarn"))
    out = []
    for r in ctx.resources(rule):
        out += _pairs(ctx, rule, "event", ctx.refs(r.address, ("bucket",)), ctx.refs(r.address, *targets), (r.address,),
                      src_types=("s3_bucket",))
    if ctx.fmt == "cfn":
        cfn_targets = (("notificationconfiguration", "lambdaconfigurations", "function"),
                       ("notificationconfiguration", "queueconfigurations", "queue"),
                       ("notificationconfiguration", "topicconfigurations", "topic"))
        for b in ctx.drawn("s3_bucket"):
            b_node = ctx.nodes[b.address]["id"]
            for d, ref in ctx.targets(ctx.refs(b.address, *cfn_targets)):
                out.append(make(b_node, d, rule, "event", "", [ref]))
    return out


def bedrock_data_source(ctx: Context) -> list[Candidate]:
    rule = "R-BEDROCK-DATA-SOURCE"
    out = []
    for r in ctx.resources(rule):
        bucket = ctx.refs(r.address, ("datasourceconfiguration", "s3configuration", "bucketarn"))
        out += _pairs(ctx, rule, "data", bucket, ctx.refs(r.address, ("knowledgebaseid",)), (r.address,),
                      dst_types=("bedrock_knowledge_base",))
    return out


def events_target(ctx: Context) -> list[Candidate]:
    rule = "R-EVENTS-TARGET"
    out = []
    for r in ctx.resources(rule):
        out += _pairs(ctx, rule, "event", ctx.refs(r.address, ("rule",)), ctx.refs(r.address, ("arn",)), (r.address,),
                      src_types=("eventbridge_rule",))
    if ctx.fmt == "cfn":
        for rl in ctx.drawn("eventbridge_rule"):
            r_node = ctx.nodes[rl.address]["id"]
            for d, ref in ctx.targets(ctx.refs(rl.address, ("targets", "arn"))):
                out.append(make(r_node, d, rule, "event", "", [ref]))
    return out


def glue_trigger(ctx: Context) -> list[Candidate]:
    """条件（predicate のジョブ・クローラ）→ 起動するジョブ・クローラ。条件の無いトリガー（スケジュール・オンデマンド）は辺を作らない。"""
    rule = "R-GLUE-TRIGGER"
    out = []
    for r in ctx.resources(rule):
        src = ctx.refs(r.address, ("predicate", "conditions", "jobname"), ("predicate", "conditions", "crawlername"))
        dst = ctx.refs(r.address, ("actions", "jobname"), ("actions", "crawlername"))
        out += _pairs(ctx, rule, "event", src, dst, (r.address,))
    return out


# ------------------------------------------------------------------ 許可の関係リソース

def _concat_text(value) -> str | None:
    """文字列か、文字列と `$pseudo` だけの `$concat` → 文字列（`$pseudo` は印の文字にする）。ほかは None。"""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and set(value) == {"$concat"}:
        out = ""
        for p in value["$concat"]:
            if isinstance(p, str):
                out += p
            elif isinstance(p, dict) and set(p) == {"$pseudo"}:
                out += _PARTITION
            else:
                return None
        return out
    return None


def _bucket_by_arn(ctx: Context, value) -> list[str]:
    """S3 の ARN の文字列（`arn:<partition>:s3:::<名前>`）→ 名前が一致するバケットのノード。"""
    text = _concat_text(value)
    m = _S3_ARN.match(text) if text and _PARTITION not in text.split(":s3:::", 1)[-1] else None
    if not m:
        return []
    out = []
    for b in ctx.drawn("s3_bucket"):
        attr = ctx.rules.row("s3_bucket").get("name_attr", {}).get(b.fmt)
        if attr and view.plain_str(b.get(attr)) == m.group(1):
            out.append(ctx.nodes[b.address]["id"])
    return sorted(out)


def lambda_permission(ctx: Context) -> list[Candidate]:
    rule = "R-LAMBDA-PERMISSION"
    out = []
    for r in ctx.resources(rule):
        principal = view.plain_str(ctx.value(r.address, "principal")) or ""
        kind = "request" if principal.split(".", 1)[0] in ("apigateway", "elasticloadbalancing") else "event"
        fns = ctx.targets(ctx.refs(r.address, ("functionname",)), ("lambda_function",))
        src_refs = ctx.refs(r.address, ("sourcearn",))
        sources = ctx.targets(src_refs)
        for fn, fn_ref in fns:
            for s, s_ref in sources:
                out.append(make(s, fn, rule, None, "", [s_ref, fn_ref], (r.address,), weak_kind=kind))
            if not sources:
                for s in _bucket_by_arn(ctx, ctx.value(r.address, "source_arn")):
                    attr = "source_arn" if r.fmt == "tf" else "SourceArn"
                    out.append(make(s, fn, rule, None, "", [fn_ref], (r.address,), weak_kind=kind,
                                    texts=(f"{r.address}.{attr} (S3 の ARN の名前の一致)",)))
    return out


def _allowed_condition_ref(ctx: Context, ref: dict) -> bool:
    """ポリシーの文の中の `aws:SourceArn` の参照で、文が Allow、演算子が ArnEquals・ArnLike・StringEquals・StringLike のものか。"""
    keys = path_keys(ref["path"])
    if SOURCE_ARN not in keys:
        return False
    i = keys.index(SOURCE_ARN)
    if i == 0 or keys[i - 1] not in ALLOW_OPERATORS:
        return False
    cut = ref["path"].lower().rfind(".condition")
    statement = value_at(dict(ctx.index.by_address[ref["from"]].props), ref["path"][:cut]) if cut > 0 else None
    return isinstance(statement, dict) and view.plain_str(view.get(statement, "effect")) == "Allow"


def _policy_sources(ctx: Context, address: str) -> tuple[list[dict], list[dict]]:
    """ポリシーの条件の `aws:SourceArn` の参照（送信元）と、たどったポリシー文書への参照。TF でポリシーが
    `data.aws_iam_policy_document` への参照なら、その文書の条件（`condition[]` の `variable = "aws:SourceArn"` で、`test` が上の演算子、
    文の `effect` が Allow（省略時も Allow））の `values` の参照をたどる。"""
    sources = [r for r in ctx.refs(address) if _allowed_condition_ref(ctx, r)]
    via = []
    for ref in ctx.refs(address, ("policy",)):
        doc = ctx.index.by_address.get(ref["to"])
        if doc is None or doc.type != "aws_iam_policy_document":
            continue
        found = []
        for i, st in enumerate(view.get(dict(doc.props), "statement") or []):
            if not isinstance(st, dict) or (view.plain_str(view.get(st, "effect")) or "Allow") != "Allow":
                continue
            for j, cond in enumerate(view.get(st, "condition") or []):
                if (isinstance(cond, dict) and cond.get("variable") == "aws:SourceArn"
                        and neutral_key(str(cond.get("test", ""))) in ALLOW_OPERATORS):
                    found += ctx.refs_under(doc.address, f"statement[{i}].condition[{j}].values")
        if found:
            via.append(ref)
            sources += found
    return sources, via


def _policy(ctx: Context, rule: str, target_keys: tuple[tuple[str, ...], ...], target_types: tuple[str, ...]) -> list[Candidate]:
    out = []
    for r in ctx.resources(rule):
        src_refs, via = _policy_sources(ctx, r.address)
        sources = ctx.targets(src_refs)
        for t, t_ref in ctx.targets(ctx.refs(r.address, *target_keys), target_types):
            for s, s_ref in sources:
                out.append(make(s, t, rule, None, "", [s_ref, t_ref] + via, (r.address,), weak_kind="event",
                                notes={(x["from"], x["path"], x["to"]): "aws:SourceArn の条件を持つポリシー文書" for x in via}))
    return out


def sqs_queue_policy(ctx: Context) -> list[Candidate]:
    return _policy(ctx, "R-SQS-QUEUE-POLICY", (("queueurl",), ("queues",)), ("sqs_queue",))


def sns_topic_policy(ctx: Context) -> list[Candidate]:
    return _policy(ctx, "R-SNS-TOPIC-POLICY", (("arn",), ("topics",)), ("sns_topic",))


def event_candidates(ctx: Context) -> list[Candidate]:
    return (esm(ctx) + sns_subscription(ctx) + s3_notification(ctx) + bedrock_data_source(ctx) + events_target(ctx)
            + glue_trigger(ctx) + lambda_permission(ctx) + sqs_queue_policy(ctx) + sns_topic_policy(ctx))
