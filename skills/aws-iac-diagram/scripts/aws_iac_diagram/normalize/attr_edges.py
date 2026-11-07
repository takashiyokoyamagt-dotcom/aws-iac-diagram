"""属性の参照から作る辺（edges.toml の `[[edge]]`）: E-ENV-REF・E-ENV-STR、E-KB-STORAGE・E-BEDROCK-EMBEDDING、E-CDN-ORIGIN・E-CDN-WAF、
E-DNS-ALIAS、E-GLUE-TARGET、E-AUTHORIZER。

- **E-ENV-REF（confirmed）:** 計算リソース（Lambda の `environment.variables`／`Environment.Variables`、ECS のタスク定義の
  `container_definitions[].environment[].value`／`ContainerDefinitions[].Environment[].Value`。タスク定義は M-ECS-TASKDEF で統合した
  サービスの参照として扱う。refs_as_target）の環境変数の値が、ほかのリソースへの参照 → 計算リソース → 参照先。kind は参照先の型
  （`[[kind_by_target]]`）。表に無い型（VPC など）は辺にしない。参照先が黒箱のモジュール（その出力への参照）なら kind は `request`、
  確信度は `inferred`（ir-schema の 2 章）。
- **E-ENV-STR（inferred）:** 環境変数の値が文字列で、ほかのリソースの名前（型の名前属性の値）か ARN と一致する。当たるリソースが
  ちょうど 1 つのときだけ（同じ名前の API とユーザープールのように 2 つ以上に当たれば、どれを指すか決まらない）。名前の一致は、
  値が 3 文字以上で英字だけでないときだけ（`distinctive`。`STAGE=prod` と `prod` という名前のバケットは結ばない）。
- **E-KB-STORAGE（confirmed、data）:** ナレッジベースの `storage_configuration`／`StorageConfiguration` の中の参照 → ベクトルストア。
- **E-BEDROCK-EMBEDDING（derived、request）:** ナレッジベースの `embedding_model_arn`／`EmbeddingModelArn` → 基盤モデル（N-BEDROCK-MODEL）。
- **E-CDN-ORIGIN・E-CDN-WAF・E-DNS-ALIAS・E-GLUE-TARGET（confirmed）:** CloudFront のオリジン、Web ACL（Web ACL → ディストリビューション）、
  Route 53 のエイリアス、Glue のクローラのデータベースとターゲット。
- **E-AUTHORIZER（confirmed、request）:** M-APIGW-AUTHORIZER で統合したオーソライザーの `provider_arns`／`ProviderARNs`（ユーザープール）と
  `authorizer_uri`／`AuthorizerUri`（Lambda）→ 統合先の API から。統合先の API そのものへの参照（自分への辺）は捨てる。

参照の無い根拠（文字列の一致）は `<address>.<位置> (<説明>)` で書く（ir-schema の 4 章の例外）。

ここは標準ライブラリと core と normalize の view・classify・relations_base・synthetic だけを使う。
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import replace

from aws_iac_diagram.normalize import synthetic, view
from aws_iac_diagram.normalize.relations_base import Candidate, Context, make, path_keys

MODULE = "module"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def kind_of(ctx: Context, node_id: str) -> str | None:
    """参照先の型 → kind（edges.toml の `[[kind_by_target]]`）。表に無ければ None。"""
    t = ctx.node_type(node_id)
    for row in ctx.rules.kind_by_target:
        if any(fnmatch.fnmatchcase(t, p) for p in row.types):
            return row.kind
    return None


def walk(value, path: str):
    """値の中の (raw の形の path, 値) をすべて（`$json` は中身をたどる。印はそれ以上たどらない）。"""
    while isinstance(value, dict) and set(value) == {"$json"}:
        value = value["$json"]
    yield path, value
    if isinstance(value, dict) and not view.is_mark(value):
        for k in value:
            yield from walk(value[k], f"{path}.{k}" if _IDENT.match(k) else f'{path}["{k}"]')
    elif isinstance(value, list):
        for i, x in enumerate(value):
            yield from walk(x, f"{path}[{i}]")


def props_paths(res):
    """リソースの props の中の (raw の形の path, 値)。CFN は `Properties.` を前に付ける。"""
    for k, v in res.props.items():
        base = f"Properties.{k}" if res.fmt == "cfn" else k
        yield from walk(v, base)


ENV_KEYS = (("environment", "variables"), ("containerdefinitions", "environment", "value"))


def _env_values(res):
    """環境変数の値の (path, 値)（Lambda の variables の値、ECS のコンテナの environment[].value）。"""
    for path, v in props_paths(res):
        keys = path_keys(path)
        if (len(keys) == 3 and keys[:2] == ("environment", "variables")) or keys == ("containerdefinitions", "environment", "value"):
            yield path, v


def env_candidates(ctx: Context, models: dict) -> list[Candidate]:
    out = []
    computes = [r for r in ctx.drawn("lambda_function")]
    computes += [ctx.index.by_address[a] for a in sorted(ctx.decisions)
                 if ctx.decisions[a].cls == "merged_into" and ctx.decisions[a].rule == "M-ECS-TASKDEF" and not ctx.decisions[a].provisional]
    for res in computes:
        sources = ctx.nodes_of(res.address)
        refs = ctx.refs(res.address, *ENV_KEYS)
        for t, ref in ctx.targets(refs):
            blackbox = ctx.node_type(t) == MODULE
            kind = "request" if blackbox else kind_of(ctx, t)
            if kind is None:
                continue
            for s in sources:
                c = make(s, t, "E-ENV-REF", kind, "", [ref], confidence="confirmed")
                out.append(replace(c, confidence="inferred") if blackbox else c)
        for path, v in _env_values(res):
            if not isinstance(v, str) and synthetic.arn_text(v) is None:
                continue
            text = synthetic.arn_text(v)
            targets = synthetic.string_targets(ctx, v, models, region_of=lambda a: ctx.index.by_address[a].region) or _name_targets(ctx, text)
            if len(targets) != 1:
                continue  # 同じ文字列が 2 つ以上のリソースの名前に当たれば、どれを指すか決まらないので辺にしない
            for t in targets:
                kind = kind_of(ctx, t)
                if kind is None:
                    continue
                for s in sources:
                    out.append(Candidate(s, t, "E-ENV-STR", kind, "", (f"{res.address}.{path} (文字列の一致: {_short(text)})",),
                                         confidence="inferred"))
    return out


def _short(text: str | None) -> str:
    return (text or "").replace("\x00", "${…}")


def distinctive(text: str | None) -> bool:
    """名前の一致に使ってよい文字列か: 3 文字以上で、英字だけではない（`shop-orders-archive`・`orders_v2` は可、`prod`・`Movies`・`app` は
    不可。ステージ名などのありふれた語がリソースの名前と偶然一致するのを避ける）。ARN は string_targets が別に照合する。"""
    return bool(text) and "\x00" not in text and len(text) >= 3 and not text.isalpha()


def _name_targets(ctx: Context, text: str | None) -> list[str]:
    """文字列がリソースの名前（型の名前属性の値）と一致する描くノード。"""
    if not distinctive(text):
        return []
    out = []
    for a in sorted(ctx.nodes):
        t = ctx.nodes[a]["type"]
        attr = ctx.rules.row(t).get("name_attr", {}).get(ctx.fmt) if t != MODULE else None
        if attr and view.plain_str(ctx.index.by_address[a].get(attr)) == text:
            out.append(ctx.nodes[a]["id"])
    return out


def kb_candidates(ctx: Context, models: dict) -> list[Candidate]:
    out = []
    for kb in ctx.drawn("bedrock_knowledge_base"):
        k = ctx.nodes[kb.address]["id"]
        for t, ref in ctx.targets(ctx.refs(kb.address, ("storageconfiguration",))):
            out.append(make(k, t, "E-KB-STORAGE", "data", "", [ref], confidence="confirmed"))
        for path, v in props_paths(kb):
            keys = path_keys(path)
            if keys and keys[-1] == "embeddingmodelarn":
                for t in synthetic.string_targets(ctx, v, models):
                    if ctx.node_type(t) == synthetic.MODEL_TYPE:
                        out.append(Candidate(k, t, "E-BEDROCK-EMBEDDING", "request", "",
                                             (f"{kb.address}.{path} (基盤モデルの ARN)",), confidence="derived"))
    return out


def _simple(ctx: Context, rule: str, kind: str, types: tuple[str, ...], keypaths, reverse: bool = False,
            target_types: tuple[str, ...] | None = None) -> list[Candidate]:
    out = []
    for res in ctx.drawn(*types):
        me = ctx.nodes[res.address]["id"]
        for t, ref in ctx.targets(ctx.refs(res.address, *keypaths), target_types):
            out.append(make(t, me, rule, kind, "", [ref], confidence="confirmed") if reverse
                       else make(me, t, rule, kind, "", [ref], confidence="confirmed"))
    return out


def cdn_dns_glue_candidates(ctx: Context) -> list[Candidate]:
    cdn = ("cloudfront_distribution",)
    out = _simple(ctx, "E-CDN-ORIGIN", "request", cdn, [("origin", "domainname"), ("distributionconfig", "origins", "domainname")])
    out += _simple(ctx, "E-CDN-WAF", "request", cdn, [("webaclid",), ("distributionconfig", "webaclid")], reverse=True,
                   target_types=("waf_web_acl",))
    out += _simple(ctx, "E-DNS-ALIAS", "request", ("route53_record",),
                   [("alias", "name"), ("aliastarget", "dnsname"), ("recordsets", "aliastarget", "dnsname")])
    glue = [("databasename",), ("s3target", "path"), ("jdbctarget",), ("dynamodbtarget", "path"), ("catalogtarget",),
            ("deltatarget",), ("targets",)]
    out += _simple(ctx, "E-GLUE-TARGET", "data", ("glue_crawler",), glue)
    return out


def authorizer_candidates(ctx: Context) -> list[Candidate]:
    out = []
    for a in sorted(ctx.decisions):
        d = ctx.decisions[a]
        if not (d.cls == "merged_into" and d.rule == "M-APIGW-AUTHORIZER" and not d.provisional):
            continue
        for t, ref in ctx.targets(ctx.refs(a, ("providerarns",), ("authorizeruri",))):
            for api in d.into:
                if t != api:  # 統合先の API そのものへの参照は自分への辺なので捨てる
                    out.append(make(api, t, "E-AUTHORIZER", "request", "", [ref], confidence="confirmed"))
    return out


def attr_candidates(ctx: Context, models: dict) -> list[Candidate]:
    return env_candidates(ctx, models) + kb_candidates(ctx, models) + cdn_dns_glue_candidates(ctx) + authorizer_candidates(ctx)
