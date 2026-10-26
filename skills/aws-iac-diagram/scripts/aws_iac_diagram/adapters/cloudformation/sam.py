"""SAM（AWS::Serverless::*）: Globals の混ぜ方と、暗黙の API。"""
from __future__ import annotations


# SAM の Globals の節 → 混ぜる先の型
GLOBALS = {"Function": "AWS::Serverless::Function", "Api": "AWS::Serverless::Api",
           "HttpApi": "AWS::Serverless::HttpApi", "SimpleTable": "AWS::Serverless::SimpleTable",
           "StateMachine": "AWS::Serverless::StateMachine", "LayerVersion": "AWS::Serverless::LayerVersion"}

def merge_globals(global_props, props):
    """SAM の Globals の混ぜ方: マップは中まで混ぜ、リストは Globals の後ろにつなぎ、値はリソースの方を使う。

    組み込み関数（Ref・Fn::*・Condition のキーが1つのオブジェクト）はマップではなく1つの値として扱う（SAM と同じ）。
    """
    if (isinstance(global_props, dict) and isinstance(props, dict)
            and not _is_intrinsic(global_props) and not _is_intrinsic(props)):
        out = dict(global_props)
        for k, v in props.items():
            out[k] = merge_globals(global_props[k], v) if k in global_props else v
        return out
    if isinstance(global_props, list) and isinstance(props, list):
        return global_props + props
    return props

def _is_intrinsic(v) -> bool:
    if not (isinstance(v, dict) and len(v) == 1):
        return False
    key = next(iter(v))
    return key in ("Ref", "Condition") or key.startswith("Fn::")

def implicit_apis(props: dict) -> set[tuple[str, str]]:
    out = set()
    for ev in (props.get("Events") or {}).values():
        if not isinstance(ev, dict):
            continue
        p = ev.get("Properties") or {}
        if ev.get("Type") == "Api" and "RestApiId" not in p:
            out.add(("ServerlessRestApi", "AWS::Serverless::Api"))
        if ev.get("Type") == "HttpApi" and "ApiId" not in p:
            out.add(("ServerlessHttpApi", "AWS::Serverless::HttpApi"))
    return out
