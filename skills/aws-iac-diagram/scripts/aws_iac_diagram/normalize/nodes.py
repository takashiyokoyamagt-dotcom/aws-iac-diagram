"""正規化の段階 2: ノード（N）。`drawn` に分類したリソースから、ノード（id・type・category・name・label・attrs・multiplicity）を作る。

- id と名前は `names`（B3・K-NAME）。`label` はいまは `name` と同じ（省略規則・日本語はフェーズ 4。設計草案 8 章の 5 の (a)）。
- `parent`・`spans` は入れ子の段階（4）が決める。ここでは `parent: None` を置くだけ（段階 4 が上書きする）。
- 値が決まらない count／for_each（raw の `multiplicity: "N"`）は `multiplicity: "N"`（×N）。
- `attrs`（ir-schema の 2 章の表のキーだけ）: `cidr`（vpc・subnet。文字列のときだけ）、`endpoint_type`・`service`（vpc_endpoint）、
  `module_source`・`module_version`（黒箱のモジュール。TF は source・version、CFN はネストスタックの `TemplateURL`、SAR の `Location`）。`access`（subnet）はルート（R-ROUTE）の結果で決まるので、辺の段階の後で足す。
- 合成ノード（AZ、`external/internet`、`bedrock_model`）は、入れ子（N-AZ）と辺（N-EXT-INTERNET・N-BEDROCK-MODEL）の段階で作る。
- `enabled: null`（条件・count が決まらない）のリソースも描き、`NORM-COND-UNKNOWN`（warn）を出す（ir-schema の 7.2）。

ここは標準ライブラリと core と normalize の view・classify・names だけを使う。
"""
from __future__ import annotations

import re

from aws_iac_diagram.core.rules import Rules
from aws_iac_diagram.normalize import names, view
from aws_iac_diagram.normalize.classify import Decision
from aws_iac_diagram.normalize.view import Index, Resource

# VPC エンドポイントのサービス名（`com.amazonaws.<リージョン>.<サービス>`。リージョンは $pseudo のことがある）
_SERVICE = re.compile(r"^com\.amazonaws\.[^.]+\.(.+)$")
ENDPOINT_TYPE_DEFAULT = "Gateway"  # TF・CFN とも、省略時は Gateway 型


def _service_name(value) -> str | None:
    """`service_name`／`ServiceName` の末尾のサービス名（`s3`・`ssm`・`ecr.api`）。リージョンが擬似パラメータでもよい。"""
    if isinstance(value, dict) and "$concat" in value:
        text = ""
        for part in value["$concat"]:
            if isinstance(part, str):
                text += part
            elif isinstance(part, dict) and part.get("$pseudo") == "AWS::Region":
                text += "region"  # 名前の形を見るだけなので、どのリージョンでもよい
            else:
                return None
        value = text
    if not isinstance(value, str):
        return None
    m = _SERVICE.match(value)
    return m.group(1) if m else None


def _cfn_module_source(res: Resource) -> tuple[str | None, str | None]:
    """CFN の黒箱の source と版: ネストスタックは `TemplateURL`。SAM のアプリケーション（SAR）は `Location` で、
    `{ApplicationId, SemanticVersion}` の形ならその 2 つ、文字列（手元のテンプレートのパスか URL）ならそれ。"""
    url = view.plain_str(res.get("TemplateURL"))
    if url:
        return url, None
    loc = res.get("Location")
    if isinstance(loc, str):
        return view.plain_str(loc), None
    if isinstance(loc, dict) and not view.is_mark(loc):
        return view.plain_str(view.get(loc, "ApplicationId")), view.plain_str(view.get(loc, "SemanticVersion"))
    return None, None


def attrs_of(res: Resource, type_id: str) -> dict:
    """ノードの `attrs`（評価できた値だけ）。"""
    out: dict = {}
    if type_id in ("vpc", "subnet"):
        cidr = view.plain_str(res.get("cidr_block"))
        if cidr:
            out["cidr"] = cidr
    elif type_id == "vpc_endpoint":
        t = view.plain(res.get("vpc_endpoint_type"))
        out["endpoint_type"] = t if isinstance(t, str) and t in ("Gateway", "Interface", "GatewayLoadBalancer") else ENDPOINT_TYPE_DEFAULT
        svc = _service_name(res.get("service_name"))
        if svc:
            out["service"] = svc
    elif type_id == "module":
        if isinstance(res.source, str) and res.source:
            out["module_source"] = res.source
        elif res.fmt == "cfn":
            src, ver = _cfn_module_source(res)
            if src:
                out["module_source"] = src
            if ver:
                out["module_version"] = ver
        if isinstance(res.version, str) and res.version:
            out["module_version"] = res.version
    return out


def build_nodes(index: Index, decisions: dict[str, Decision], rules: Rules) -> tuple[dict[str, dict], list[dict]]:
    """描くリソースの address → ノードと、診断。ノードは段階 2 で決まるフィールドだけを持つ（parent は None）。"""
    items: list[tuple[Resource, str, names.Name]] = []
    for res in index.resources:
        d = decisions[res.address]
        if d.cls != "drawn":
            continue
        row = rules.row(d.type_id)
        items.append((res, d.type_id, names.choose_name(res, row)))
    ids, diags = names.assign_ids(items)
    out: dict[str, dict] = {}
    for res, type_id, nm in items:
        row = rules.row(type_id)
        node = {"id": ids[res.address], "type": type_id, "category": row.category, "name": nm.name, "label": nm.name,
                "parent": None}
        a = attrs_of(res, type_id)
        if a:
            node["attrs"] = a
        if res.multiplicity == "N":
            node["multiplicity"] = "N"
        if res.enabled is None:
            diags.append({"level": "warn", "code": "NORM-COND-UNKNOWN", "address": res.address,
                          "message": "作られるか（count・for_each・Condition）が決まらないが、描いた"})
        out[res.address] = node
    return out, diags
