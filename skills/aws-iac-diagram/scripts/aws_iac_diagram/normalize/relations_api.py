"""R-APIGW-HTTP と R-APIGW-REST（API → 統合先の辺）。TF・CFN のリソースと、SAM の関数の `Events`（`HttpApi`・`Api`）。

- HTTP API: 統合（`aws_apigatewayv2_integration`／`AWS::ApiGatewayV2::Integration`）の API（`api_id`／`ApiId`）→ 統合先
  （`integration_uri`／`IntegrationUri`）。ラベルは、その統合を `target`／`Target` で指すルートのルートキーを辞書順に `, ` でつなぐ。
  `members` は統合とそのルート。
- REST API: 統合（TF の `aws_api_gateway_integration`、CFN の `AWS::ApiGateway::Method` の `Integration.Uri`）の API（`rest_api_id`／
  `RestApiId`）→ 統合先（`uri`／`Integration.Uri`）。ラベルは `<METHOD> <path>`（path はリソースの `path_part`／`PathPart` を
  `parent_id`／`ParentId` でたどったもの。API のルート（`root_resource_id`／`RootResourceId`）なら `/`）。`members` は統合、
  同じリソース・メソッドのメソッド、path のリソース（親を含む）。
- OpenAPI の定義（CFN の `AWS::Serverless::Api` の `DefinitionBody`、`AWS::ApiGateway::RestApi` の `Body`。`AWS::Include` で
  差し込んだものを含む）: `paths.<path>.<method>.x-amazon-apigateway-integration` ごとに、API → 統合先（`uri` の中の参照、
  無ければ `requestTemplates` の中の参照。上の REST API と同じ。`type: mock` は辺を作らない）。ラベルは `<METHOD> <path>`（`x-amazon-apigateway-any-method` は `ANY`）。
- SAM: `AWS::Serverless::Function` の `Events` の `Type: HttpApi`（`ApiId`、無ければ暗黙の `ServerlessHttpApi`）・`Type: Api`
  （`RestApiId`、無ければ `ServerlessRestApi`）。ラベルは `<METHOD> <Path>`（HTTP API で Method・Path が無ければ `$default`）。
- 統合先の無い統合・ルート・メソッド（MOCK、リダイレクトなど）は辺を作らない。

ここは標準ライブラリと core と normalize の view・classify・relations_base だけを使う。
"""
from __future__ import annotations

from aws_iac_diagram.core.ir_raw import join_path
from aws_iac_diagram.normalize import view
from aws_iac_diagram.normalize.relations_base import Candidate, Context, make

HTTP_RULE = "R-APIGW-HTTP"
REST_RULE = "R-APIGW-REST"
HTTP_INTEGRATION = ("aws_apigatewayv2_integration", "AWS::ApiGatewayV2::Integration")
HTTP_ROUTE = ("aws_apigatewayv2_route", "AWS::ApiGatewayV2::Route")
REST_RESOURCE = ("aws_api_gateway_resource", "AWS::ApiGateway::Resource")
REST_METHOD = ("aws_api_gateway_method", "AWS::ApiGateway::Method")
REST_INTEGRATION = ("aws_api_gateway_integration",)
HTTP_TYPES = ("apigw_http_api",)
REST_TYPES = ("apigw_rest_api",)
SAM_FUNCTION = "AWS::Serverless::Function"
IMPLICIT = {"HttpApi": "ServerlessHttpApi", "Api": "ServerlessRestApi"}
OPENAPI_BODY = {"AWS::Serverless::Api": "DefinitionBody", "AWS::ApiGateway::RestApi": "Body"}
OPENAPI_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "x-amazon-apigateway-any-method"}
OPENAPI_INTEGRATION = "x-amazon-apigateway-integration"


def _http(ctx: Context) -> list[Candidate]:
    out = []
    routes = ctx.resources(HTTP_RULE, HTTP_ROUTE)
    for integ in ctx.resources(HTTP_RULE, HTTP_INTEGRATION):
        apis = ctx.targets(ctx.refs(integ.address, ("apiid",)), HTTP_TYPES)
        # 統合先: integration_uri。AWS のサービスとの統合（Step Functions など）は request_parameters の StateMachineArn
        dests = (ctx.targets(ctx.refs(integ.address, ("integrationuri",)))
                 or ctx.targets(ctx.refs(integ.address, ("requestparameters", "statemachinearn"))))
        keys, members, route_refs = [], [integ.address], []
        for r in routes:
            to_integ = [x for x in ctx.refs(r.address, ("target",)) if x["to"] == integ.address]
            if to_integ:
                members.append(r.address)
                route_refs += to_integ
                k = view.plain_str(ctx.value(r.address, "route_key"))
                if k:
                    keys.append(k)
        label = ", ".join(sorted(set(keys)))
        for api, api_ref in apis:
            for dest, dest_ref in dests:
                out.append(make(api, dest, HTTP_RULE, "request", label, [api_ref, dest_ref] + route_refs, members))
    return out


def _rest_path(ctx: Context, resource: str, seen: tuple = ()) -> tuple[str, list[str]] | None:
    """REST のリソースの path と、path のリソース（自分と親）。API のルートなら ("/", [])。たどれなければ None。"""
    if resource in seen:
        return None
    res = ctx.index.by_address.get(resource)
    if res is None or res.type not in REST_RESOURCE:
        return "", []  # API のルート（root_resource_id）
    part = view.plain_str(res.get("path_part"))
    parents = ctx.refs(resource, ("parentid",))
    if part is None or len(parents) != 1:
        return None
    parent = _rest_path(ctx, parents[0]["to"], seen + (resource,))
    if parent is None:
        return None
    return f"{parent[0]}/{part}", parent[1] + [resource]


def _rest(ctx: Context) -> list[Candidate]:
    out = []
    methods = ctx.resources(REST_RULE, REST_METHOD)
    integrations = ctx.resources(REST_RULE, REST_INTEGRATION) if ctx.fmt == "tf" else [m for m in methods]
    for integ in integrations:
        apis = ctx.targets(ctx.refs(integ.address, ("restapiid",)), REST_TYPES)
        # 統合先: uri。AWS のサービスとの統合（uri が `arn:aws:apigateway:…:states:action/StartExecution` のような文字列）は、
        # request_templates の中の参照（T11 の Step Functions のステートマシン）
        dests = (ctx.targets(ctx.refs(integ.address, ("uri",), ("integration", "uri")))
                 or ctx.targets(ctx.refs(integ.address, ("requesttemplates",), ("integration", "requesttemplates"))))
        res_refs = ctx.refs(integ.address, ("resourceid",))
        method_value = ctx.value(integ.address, "http_method")
        members, extra = [integ.address], []
        if not isinstance(method_value, str):  # TF の http_method = aws_api_gateway_method.x.http_method（参照）
            for ref in ctx.refs(integ.address, ("httpmethod",)):
                method_value = ctx.value(ref["to"], "http_method")
                extra.append(ref)
        method = view.plain_str(method_value)
        path = _rest_path(ctx, res_refs[0]["to"]) if len(res_refs) == 1 else None
        if method is None or path is None:
            continue
        members += path[1]
        for m in methods:
            same_res = any(r["to"] == res_refs[0]["to"] for r in ctx.refs(m.address, ("resourceid",)))
            if same_res and view.plain_str(ctx.value(m.address, "http_method")) == method:
                members.append(m.address)
        label = f"{method.upper()} {path[0] or '/'}"
        for api, api_ref in apis:
            for dest, dest_ref in dests:
                out.append(make(api, dest, REST_RULE, "request", label, [api_ref, dest_ref] + res_refs + extra, members))
    return out


def _openapi(ctx: Context) -> list[Candidate]:
    """CFN の REST API の OpenAPI の定義（DefinitionBody・Body）の統合。操作（path とメソッド）ごとに候補を作る（ラベルは E-MERGE がまとめる）。"""
    if ctx.fmt != "cfn":
        return []
    out = []
    for api in ctx.drawn(*REST_TYPES):
        key = OPENAPI_BODY.get(api.type)
        body = api.props.get(key) if key else None
        while isinstance(body, dict) and set(body) == {"$json"}:  # 文字列の JSON で書いた定義
            body = body["$json"]
        paths = body.get("paths") if isinstance(body, dict) else None
        if not isinstance(paths, dict):
            continue
        api_node = ctx.nodes[api.address]["id"]
        base = join_path(join_path("Properties", key), "paths")
        for p in sorted(x for x in paths if isinstance(x, str)):
            ops = paths[p]
            if not isinstance(ops, dict):
                continue
            for m in sorted(x for x in ops if isinstance(x, str) and x.lower() in OPENAPI_METHODS):
                integ = ops[m].get(OPENAPI_INTEGRATION) if isinstance(ops[m], dict) else None
                if not isinstance(integ, dict) or str(integ.get("type", "")).lower() == "mock":  # MOCK は辺を作らない
                    continue
                prefix = join_path(join_path(join_path(base, p), m), OPENAPI_INTEGRATION)
                dests = (ctx.targets(ctx.refs_under(api.address, join_path(prefix, "uri")))
                         or ctx.targets(ctx.refs_under(api.address, join_path(prefix, "requestTemplates"))))
                method = "ANY" if m.lower() == "x-amazon-apigateway-any-method" else m.upper()
                for dest, dest_ref in dests:  # 統合先が API 自身の候補は、E-MERGE（edges.py）が自己ループとして捨てる
                    out.append(make(api_node, dest, REST_RULE, "request", f"{method} {p}", [dest_ref]))
    return out


def _sam(ctx: Context) -> list[Candidate]:
    """SAM の関数の Events（HttpApi → R-APIGW-HTTP、Api → R-APIGW-REST）。同じ API と関数の組はラベルをまとめる。"""
    if ctx.fmt != "cfn":
        return []
    groups: dict[tuple[str, str, str], tuple[list[str], list[dict], list[str]]] = {}
    for fn in ctx.drawn("lambda_function"):
        if fn.type != SAM_FUNCTION:
            continue
        events = fn.get("Events")
        if not isinstance(events, dict):
            continue
        fn_node = ctx.nodes[fn.address]["id"]
        for name in sorted(events):
            ev = events[name]
            t = ev.get("Type") if isinstance(ev, dict) else None
            if t not in IMPLICIT:
                continue
            rule, types, key = (HTTP_RULE, HTTP_TYPES, "ApiId") if t == "HttpApi" else (REST_RULE, REST_TYPES, "RestApiId")
            props = ev.get("Properties") if isinstance(ev.get("Properties"), dict) else {}
            prefix = f"Properties.Events.{name}.Properties.{key}"
            refs = ctx.refs_under(fn.address, prefix)
            apis = [a for a, _ in ctx.targets(refs, types)] if refs else ctx.nodes_of(IMPLICIT[t])
            method, path = view.plain_str(props.get("Method")), view.plain_str(props.get("Path"))
            label = f"{method.upper()} {path}" if method and path else ("$default" if t == "HttpApi" else "")
            for api in apis:
                labels, used, texts = groups.setdefault((api, fn_node, rule), ([], [], []))
                labels.append(label)
                used += refs
                if not refs:  # 暗黙の API（参照が無い）
                    texts.append(f"{fn.address}.Properties.Events.{name} (Type: {t}, {IMPLICIT[t]})")
    out = []
    for (api, fn_node, rule), (labels, refs, texts) in sorted(groups.items()):
        out.append(make(api, fn_node, rule, "request", ", ".join(sorted({x for x in labels if x})), refs, texts=tuple(texts)))
    return out


def api_candidates(ctx: Context) -> list[Candidate]:
    return _http(ctx) + _rest(ctx) + _openapi(ctx) + _sam(ctx)
