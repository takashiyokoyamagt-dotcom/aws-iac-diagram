"""E-IAM（推定の辺）と E-IAM-SUPPRESS。edges.toml の E-IAM・`[[iam_action_kind]]`、docs/spec/rules/edges.md。

ロールを引き受けるリソース（`role`・`role_arn`・`execution_role_arn`・`task_role_arn`／`Role`・`RoleArn`・`ExecutionRoleArn`・
`TaskRoleArn` でロールを指すもの、インスタンスプロファイル経由の EC2。統合されたタスク定義はサービス）→ そのロールのポリシーの
`Resource` が指すリソース。確信度は `inferred`、ラベルは空。

- ポリシーの集め方: TF は `aws_iam_role_policy`（`policy` は `data.aws_iam_policy_document` への参照か `jsonencode`）、ロールの
  `inline_policy`、`aws_iam_role_policy_attachment` → `aws_iam_policy`。CFN はロールの `Policies[].PolicyDocument`、`Roles` でロールを
  指す `AWS::IAM::Policy`・`ManagedPolicy`、ロールの `ManagedPolicyArns`。SAM の関数の `Policies`（ポリシーの文と、ポリシーテンプレート
  `DynamoDBCrudPolicy` など。テンプレートは `TEMPLATE_ACTIONS` の代表のアクションで kind を決める）。
- 文は Allow だけ。kind は文のアクションを `[[iam_action_kind]]` の上の行から当てる（`iam_action_priority = "first_row_wins"`）。どの行にも
  当たらなければ辺を作らない（`iam_action_default = "none"`）。
- `Resource` の照合（v0.1）: 参照（`$res`）はその参照先。`<bucket の ARN>/*` の形の `$concat` は S3 のバケットだけ。文字列の ARN は
  リソースの部分にワイルドカードの無いものと S3 の `<bucket>/*` だけ（synthetic.py）。基盤モデルの ARN は N-BEDROCK-MODEL。
- E-IAM-SUPPRESS: E-IAM の辺と逆向きの辺がほかの規則でできていれば、E-IAM の辺は作らず、その逆向きの辺の根拠に
  E-IAM-SUPPRESS として書く（ESM のストリームを読む権限、KB がデータソースのバケットを読む権限）。edges.py が行う。

ここは標準ライブラリと core と normalize の view・classify・relations_base・synthetic・attr_edges だけを使う。
"""
from __future__ import annotations

import fnmatch

from aws_iac_diagram.normalize import synthetic, view
from aws_iac_diagram.normalize.attr_edges import walk
from aws_iac_diagram.normalize.relations_base import Candidate, Context, path_keys, ref_key

RULE = "E-IAM"
ROLE_KEYS = frozenset({"role", "rolearn", "executionrolearn", "taskrolearn"})
ROLE_TYPES = ("aws_iam_role", "AWS::IAM::Role")
PROFILE_TYPES = ("aws_iam_instance_profile", "AWS::IAM::InstanceProfile")
POLICY_DOC = "aws_iam_policy_document"

# SAM のポリシーテンプレート → 代表のアクション（kind を [[iam_action_kind]] で決めるため）
TEMPLATE_ACTIONS = {
    "DynamoDBCrudPolicy": "dynamodb:PutItem", "DynamoDBReadPolicy": "dynamodb:GetItem", "DynamoDBWritePolicy": "dynamodb:PutItem",
    "DynamoDBStreamReadPolicy": "dynamodb:GetRecords", "SNSPublishMessagePolicy": "sns:Publish", "SQSSendMessagePolicy": "sqs:SendMessage",
    "SQSPollerPolicy": "sqs:ReceiveMessage", "S3ReadPolicy": "s3:GetObject", "S3WritePolicy": "s3:PutObject", "S3CrudPolicy": "s3:PutObject",
    "LambdaInvokePolicy": "lambda:InvokeFunction", "StepFunctionsExecutionPolicy": "states:StartExecution",
    "EventBridgePutEventsPolicy": "events:PutEvents",
}


def _action_matches(action: str, pattern: str) -> bool:
    """文のアクション（`s3:GetObject`、ワイルドカードの `s3:Get*`・`sqs:*`）が、表のアクション（`dynamodb:*`、`bedrock:InvokeModel*`）に
    当たるか。表の側のワイルドカードで当てるほか、文の側のワイルドカードでも当てる（同じサービスの接頭辞の中だけ。`*` だけは当てない）。"""
    if fnmatch.fnmatchcase(action, pattern):
        return True
    if "*" in action and action != "*" and ":" in action and action.split(":", 1)[0] == pattern.split(":", 1)[0]:
        return fnmatch.fnmatchcase(pattern, action)
    return False


def action_kind(ctx: Context, actions: list[str]) -> str | None:
    """アクションの並び → kind（`[[iam_action_kind]]` の上の行が優先。どの行にも当たらなければ None）。"""
    acts = [a.lower() for a in actions if isinstance(a, str)]
    for row in ctx.rules.iam_action_kinds:
        if any(_action_matches(a, p.lower()) for a in acts for p in row.actions):
            return row.kind
    return None


def _as_list(v) -> list:
    return v if isinstance(v, list) else ([] if v is None else [v])


def _referrers(ctx: Context, address: str, keys: frozenset[str]) -> list[dict]:
    return [r for r in ctx.index.refs_to.get(address, ()) if r.get("fn") not in ("depends_on", "DependsOn")
            and path_keys(r["path"], quoted=False) and path_keys(r["path"], quoted=False)[-1] in keys]


def assumers(ctx: Context, role: str) -> list[str]:
    """ロールを引き受けるリソースのノード。"""
    out = set()
    for ref in _referrers(ctx, role, ROLE_KEYS):
        res = ctx.index.by_address[ref["from"]]
        if res.type in PROFILE_TYPES:
            for r2 in _referrers(ctx, res.address, frozenset({"iaminstanceprofile"})):
                out.update(ctx.nodes_of(r2["from"]))
        else:
            out.update(ctx.nodes_of(ref["from"]))
    for ref in _referrers(ctx, role, frozenset({"roles"})):  # インスタンスプロファイルの Roles
        res = ctx.index.by_address[ref["from"]]
        if res.type in PROFILE_TYPES:
            for r2 in _referrers(ctx, res.address, frozenset({"iaminstanceprofile"})):
                out.update(ctx.nodes_of(r2["from"]))
    return sorted(out)


def _doc(ctx: Context, owner: str, path: str, value):
    """ポリシーの値 → (文書の持ち主の address, 文書の path, 文書, TF の policy document の形か)。読めなければ None。"""
    if isinstance(value, dict) and "$res" in value:
        doc = ctx.index.by_address.get(value["$res"])
        if doc is not None and doc.type == POLICY_DOC:
            return doc.address, "", dict(doc.props), True
        return None
    while isinstance(value, dict) and set(value) == {"$json"}:
        value = value["$json"]
    return (owner, path, value, False) if isinstance(value, dict) else None


def documents(ctx: Context, role: str) -> list[tuple]:
    """ロールに付いたポリシーの文書。"""
    out = []
    res = ctx.index.by_address[role]
    if ctx.fmt == "tf":
        for i, ip in enumerate(_as_list(res.get("inline_policy"))):
            if isinstance(ip, dict):
                out.append(_doc(ctx, role, f"inline_policy[{i}].policy", ip.get("policy")))
        for ref in _referrers(ctx, role, frozenset({"role"})):
            pol = ctx.index.by_address[ref["from"]]
            if pol.type == "aws_iam_role_policy":
                out.append(_doc(ctx, pol.address, "policy", pol.get("policy")))
            elif pol.type == "aws_iam_role_policy_attachment":
                for r2 in ctx.refs(pol.address, ("policyarn",)):
                    p = ctx.index.by_address.get(r2["to"])
                    if p is not None and p.type == "aws_iam_policy":
                        out.append(_doc(ctx, p.address, "policy", p.get("policy")))
    else:
        for i, p in enumerate(_as_list(res.get("Policies"))):
            if isinstance(p, dict):
                out.append(_doc(ctx, role, f"Properties.Policies[{i}].PolicyDocument", p.get("PolicyDocument")))
        for ref in _referrers(ctx, role, frozenset({"roles"})):
            pol = ctx.index.by_address[ref["from"]]
            if pol.type in ("AWS::IAM::Policy", "AWS::IAM::ManagedPolicy"):
                out.append(_doc(ctx, pol.address, "Properties.PolicyDocument", pol.get("PolicyDocument")))
        for r2 in ctx.refs(role, ("managedpolicyarns",)):
            pol = ctx.index.by_address.get(r2["to"])
            if pol is not None and pol.type == "AWS::IAM::ManagedPolicy":
                out.append(_doc(ctx, pol.address, "Properties.PolicyDocument", pol.get("PolicyDocument")))
    return [d for d in out if d is not None]


def statements(owner: str, base: str, doc: dict, tf_doc: bool):
    """文書 → (アクション, [(Resource の path, 値)])。Allow の文だけ。"""
    if tf_doc:
        for i, st in enumerate(_as_list(doc.get("statement"))):
            if isinstance(st, dict) and (view.plain_str(st.get("effect")) or "Allow") == "Allow":
                yield _as_list(st.get("actions")), [(f"statement[{i}].resources[{j}]", v) for j, v in enumerate(_as_list(st.get("resources")))]
        return
    sts = doc.get("Statement")
    items = [(f"{base}.Statement[{i}]", s) for i, s in enumerate(sts)] if isinstance(sts, list) else [(f"{base}.Statement", sts)]
    for p, st in items:
        if not isinstance(st, dict) or view.plain_str(st.get("Effect")) != "Allow":
            continue
        r = st.get("Resource")
        res = [(f"{p}.Resource[{j}]", v) for j, v in enumerate(r)] if isinstance(r, list) else [(f"{p}.Resource", r)]
        yield _as_list(st.get("Action")), res


def _targets(ctx: Context, owner: str, path: str, value, models: dict) -> list[tuple[str, list[dict], str | None]]:
    """Resource の 1 つ → [(ノード, 参照, 文字列の根拠か None)]。"""
    refs = [r for r in ctx.index.refs_from.get(owner, ()) if r["path"] == path]
    if isinstance(value, dict) and "$res" in value:
        return [(n, [r], None) for r in refs for n in ctx.nodes_of(r["to"])]
    if isinstance(value, dict) and "$concat" in value and any(isinstance(p, dict) and "$res" in p for p in value["$concat"]):
        return _concat_targets(ctx, value["$concat"], refs)
    text = synthetic.arn_text(value)
    if not text:
        return []
    found = synthetic.string_targets(ctx, value, models, region_of=lambda a: ctx.index.by_address[a].region)
    if len(found) != 1:
        return []  # 名前で 2 つ以上に当たれば、どれを指すか決まらない（E-ENV-STR と同じ）
    return [(found[0], [], f"{owner}.{path} (IAM の Resource の文字列: {text.replace(chr(0), '${…}')})")]


# ARN のサービス → その ARN が指せる描く型（`$concat` の参照の型を確かめるため）
_SERVICE_TYPES = {"s3": "s3_bucket", "dynamodb": "dynamodb_table", "sqs": "sqs_queue", "sns": "sns_topic", "lambda": "lambda_function",
                  "states": "sfn_state_machine"}


def _concat_targets(ctx: Context, parts: list, refs: list[dict]) -> list[tuple[str, list[dict], str | None]]:
    """文字列・`$pseudo`・参照 1 つだけの `$concat`（`!Sub arn:${AWS::Partition}:s3:::${Bucket}/*`、`"arn:aws:s3:::${aws_s3_bucket.b.bucket}/*"`、
    `arn:…:sqs:${AWS::Region}:${AWS::AccountId}:${Queue.QueueName}`）は、その参照の先。参照の後ろは何も無いか、S3 の `/*` だけ。
    前の文字列が ARN なら、そのサービスと参照先の型が合うときだけ。"""
    idx = [i for i, p in enumerate(parts) if isinstance(p, dict) and "$res" in p]
    if len(idx) != 1 or not all(isinstance(p, str) or (isinstance(p, dict) and set(p) == {"$pseudo"})
                                for i, p in enumerate(parts) if i != idx[0]):
        return []
    tail = "".join(p for p in parts[idx[0] + 1:] if isinstance(p, str))
    if any(isinstance(p, dict) for p in parts[idx[0] + 1:]) or tail not in ("", "/*"):
        return []
    head = "".join(p if isinstance(p, str) else ":" for p in parts[:idx[0]])
    service = head.split(":")[2] if head.startswith("arn:") and len(head.split(":")) > 2 else None
    out = []
    for r in refs:
        for n in ctx.nodes_of(r["to"]):
            t = ctx.node_type(n)
            if (tail == "/*" and t != "s3_bucket") or (service in _SERVICE_TYPES and _SERVICE_TYPES[service] != t):
                continue
            out.append((n, [r], None))
    return out


def _make(frm: str, to: str, kind: str, refs: list[dict], text: str | None) -> Candidate:
    ev = tuple(sorted({f"{r['from']}.{r['path']}" for r in refs} | ({text} if text else set())))
    return Candidate(frm, to, RULE, kind, "", ev, (), None, "inferred", tuple(sorted({ref_key(r) for r in refs})))


def iam_candidates(ctx: Context, models: dict) -> list[Candidate]:
    out = []
    for role in [a for a in sorted(ctx.index.by_address) if ctx.index.by_address[a].type in ROLE_TYPES]:
        who = assumers(ctx, role)
        if not who:
            continue
        for owner, base, doc, tf_doc in documents(ctx, role):
            for actions, resources in statements(owner, base, doc, tf_doc):
                kind = action_kind(ctx, actions)
                if kind is None:
                    continue
                for path, value in resources:
                    for t, refs, text in _targets(ctx, owner, path, value, models):
                        out += [_make(a, t, kind, refs, text) for a in who]
    # SAM の関数の Policies（関数自身が引き受ける）
    for fn in ctx.drawn("lambda_function"):
        if fn.type != "AWS::Serverless::Function":
            continue
        me = ctx.nodes[fn.address]["id"]
        pols = fn.get("Policies")
        items = [("Properties.Policies", pols)] if isinstance(pols, dict) else [(f"Properties.Policies[{i}]", p) for i, p in enumerate(_as_list(pols))]
        for base, p in items:  # Policies は配列か、1 つの mapping（SAM はどちらも書ける）
            if not isinstance(p, dict):
                continue
            if "Statement" in p:
                for actions, resources in statements(fn.address, base, p, False):
                    kind = action_kind(ctx, actions)
                    for path, value in resources if kind else []:
                        out += [_make(me, t, kind, refs, text) for t, refs, text in _targets(ctx, fn.address, path, value, models)]
            for name, action in TEMPLATE_ACTIONS.items():
                if name in p:
                    kind = action_kind(ctx, [action])
                    for ref in ctx.refs_under(fn.address, f"{base}.{name}") if kind else []:
                        out += [_make(me, n, kind, [ref], None) for n in ctx.nodes_of(ref["to"])]
    return out


def suppress(cands: list[Candidate]) -> list[Candidate]:
    """E-IAM-SUPPRESS: E-IAM の候補のうち、ほかの規則の候補に逆向きの組があるものを、その逆向きの組の根拠（E-IAM-SUPPRESS）に変える。"""
    others = {(c.frm, c.to) for c in cands if c.rule != RULE}
    out = []
    for c in cands:
        if c.rule == RULE and (c.to, c.frm) in others:
            ev = tuple(f"{e} (逆向きなので辺にしない)" for e in c.evidence)
            out.append(Candidate(c.to, c.frm, "E-IAM-SUPPRESS", None, "", ev, (), None, "inferred", c.refs))
        else:
            out.append(c)
    return out

