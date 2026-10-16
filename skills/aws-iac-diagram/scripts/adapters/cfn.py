# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""CloudFormation のテンプレートを読み、アダプタの出力（raw IR。references/ir-schema.md の 7章）を作る。

フェーズ1 の手順2（土台）の範囲:
  - YAML の短縮タグ（!Ref など）を Fn::* の長い形に正規化する（PLAN 2.2 の失敗知見 13。awscli の yamlhelper と同じ考え方）
  - Ref・Fn::GetAtt・Fn::Sub・Fn::Join・Fn::Select・Fn::Split・Fn::GetAZs・Fn::ImportValue・DependsOn を評価し、
    props の印（$res・$pseudo・$concat・$json・$az・$import・$unknown）と references を作る
  - パラメータは Default の値を使う（Default が無ければ $unknown）
手順3 以降で足すもの: SAM（Globals、暗黙のリソース）、ネストスタック、cdk.out（手順3）、
Conditions・Fn::If・Fn::FindInMap・Fn::Equals などの評価（手順4）。それまでは $unknown にし、中の参照は
state: "unevaluated" で残す。

使い方:
  uv run scripts/adapters/cfn.py --input <テンプレート> --out <raw.json> [--root-base <フォルダ>]
  --root-base: raw IR の root を、このフォルダからの相対パスで書く（既定: 作業中のフォルダ）

終了コード: 0 = 書けた（diagnostics に warn・error があっても）、2 = テンプレートを読めなかった
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import ir_raw  # noqa: E402

PSEUDO = {"AWS::Region", "AWS::AccountId", "AWS::Partition", "AWS::StackName", "AWS::StackId",
          "AWS::URLSuffix", "AWS::NotificationARNs"}
NO_VALUE = object()  # AWS::NoValue（プロパティやリストの要素ごと消す）
# 手順4 で評価する関数。それまでは $unknown にして、中の参照を unevaluated で残す
DEFERRED = {"Fn::If", "Fn::FindInMap", "Fn::Equals", "Fn::And", "Fn::Or", "Fn::Not", "Condition"}
# 評価しない関数（値は $unknown。中の参照は unevaluated で残す）
UNEVALUATED = {"Fn::Base64", "Fn::Cidr", "Fn::Length", "Fn::ToJsonString", "Fn::Transform", "Fn::ForEach"}
OUTSIDE_PROPS = ("Metadata", "CreationPolicy", "UpdatePolicy")
SUB_VAR = re.compile(r"\$\{([^}]*)\}")


# ------------------------------------------------------------------ 読み込み

class _Loader(yaml.SafeLoader):
    """短縮タグを Fn::* の長い形にする。日付・時刻の暗黙の型変換はしない（'2010-09-09' を文字列のまま読む）。"""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _intrinsic(loader: yaml.Loader, suffix: str, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    if suffix == "Ref":
        return {"Ref": value}
    if suffix == "Condition":
        return {"Condition": value}
    if suffix == "GetAtt" and isinstance(value, str):
        # !GetAtt A.B.C → ["A", "B.C"]（最初の . で分ける）
        value = value.split(".", 1)
    return {f"Fn::{suffix}": value}


_Loader.add_multi_constructor("!", _intrinsic)


def load_template(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    # 拡張子によらず、{ で始まれば先に JSON として読む（.template の JSON にはタブの字下げがあり、YAML では読めない）
    if path.suffix.lower() == ".json" or text.lstrip().startswith("{"):
        try:
            doc = json.loads(text)
        except ValueError:
            if path.suffix.lower() == ".json":
                raise
            doc = yaml.load(text, Loader=_Loader)  # noqa: S506
    else:
        doc = yaml.load(text, Loader=_Loader)  # noqa: S506  _Loader は SafeLoader を元にしている
    if not isinstance(doc, dict):
        raise ValueError("テンプレートの最上位がオブジェクトではない")
    return doc


# ------------------------------------------------------------------ 評価

class Evaluator:
    """1つのテンプレートの組み込み関数を評価する。参照は、印に一時的な "__fn" を付けて運び、最後に references にする。"""

    def __init__(self, template: dict, diagnostics: list[dict]):
        self.resources = template.get("Resources") or {}
        self.parameters = template.get("Parameters") or {}
        self.diagnostics = diagnostics
        self.param_values: dict = {}
        self.extra_refs: list[dict] = []  # pruned / unevaluated の参照
        self.current: str = ""  # いま評価しているリソースの address

    # --- 診断と参照
    def diag(self, level: str, code: str, path: str, message: str) -> None:
        self.diagnostics.append({"level": level, "code": code, "address": self.current, "path": path,
                                 "message": message})

    def scan_refs(self, value, path: str, state: str) -> None:
        """評価しない値の中の参照を、static に探して state 付きで残す。"""
        for to, attr, fn in _static_refs(value, set(self.resources)):
            self.extra_refs.append({"from": self.current, "path": path, "to": to, "attr": attr, "fn": fn,
                                    "state": state})

    def unknown(self, value, path: str, reason: str, code: str = "CFN-UNEVALUATED"):
        self.scan_refs(value, path, "unevaluated")
        self.diag("warn", code, path, reason)
        return {"$unknown": reason}

    # --- パラメータ
    def parameter(self, name: str, path: str):
        if name in self.param_values:
            return self.param_values[name]
        p = self.parameters[name] or {}
        if "Default" not in p:
            v = {"$unknown": f"parameter {name} has no value"}
            self.diag("warn", "CFN-UNRESOLVED-PARAM", path, f"parameter {name} has no value")
            return v
        value = p["Default"]
        ptype = str(p.get("Type", ""))
        if (ptype.startswith("List<") or ptype == "CommaDelimitedList") and isinstance(value, str):
            value = [s.strip() for s in value.split(",")]
        elif ptype.startswith("AWS::SSM::Parameter::Value<"):
            value = {"$unknown": f"parameter {name} is an SSM parameter"}
            self.diag("warn", "CFN-SSM-PARAM", path, f"parameter {name} is an SSM parameter")
        self.param_values[name] = value
        return value

    # --- 本体
    def eval(self, node, path: str):
        if isinstance(node, list):
            out = []
            for item in node:
                v = self.eval(item, ir_raw.join_path(path, len(out)))
                if v is not NO_VALUE:
                    out.append(v)
            return out
        if not isinstance(node, dict):
            if isinstance(node, str):
                if "{{resolve:" in node:
                    return self.unknown(node, path, "dynamic reference {{resolve:…}}", "CFN-DYNAMIC-REF")
                return _maybe_json(node)
            return node
        if len(node) == 1:
            (key, arg), = node.items()
            if key == "Ref":
                return self.ref(arg, path)
            if key == "Fn::GetAtt":
                return self.getatt(arg, path)
            if key == "Fn::Sub":
                return self.sub(arg, path)
            if key == "Fn::Join":
                return self.join(arg, path)
            if key == "Fn::Select":
                return self.select(arg, path)
            if key == "Fn::Split":
                return self.split(arg, path)
            if key == "Fn::GetAZs":
                return {"$az": "*"}
            if key == "Fn::ImportValue":
                name = self.eval(arg, path)
                if isinstance(name, str):
                    return {"$import": name}
                return self.unknown(arg, path, f"Fn::ImportValue with a computed name {json.dumps(name, ensure_ascii=False)}")
            # {"Condition": "名前"} だけが条件関数。値がオブジェクトなら、IAM の Condition などのふつうのプロパティ
            if key in DEFERRED and (key != "Condition" or isinstance(arg, str)):
                return self.unknown(node, path, f"{key} is not evaluated yet (phase 1 step 4)", "CFN-DEFERRED")
            if key in UNEVALUATED or key.startswith("Fn::"):
                return self.unknown(node, path, f"{key} is not evaluated")
        out = {}
        for k, v in node.items():
            ev = self.eval(v, ir_raw.join_path(path, k))
            if ev is not NO_VALUE:
                out["$" + k if k.startswith("$") else k] = ev  # 入力の $ のキーは $$ で逃がす（7.2）
        return out

    def ref(self, name, path: str):
        if not isinstance(name, str):
            return self.unknown({"Ref": name}, path, "Ref with a non-string argument")
        if name == "AWS::NoValue":
            return NO_VALUE
        if name in PSEUDO:
            return {"$pseudo": name}
        if name in self.resources:
            return {"$res": name, "attr": None, "__fn": "Ref"}
        if name in self.parameters:
            return self.parameter(name, path)
        return self.unknown({"Ref": name}, path, f"Ref to undefined name {name}", "CFN-UNDEFINED-REF")

    def getatt(self, arg, path: str, fn: str = "GetAtt"):
        if isinstance(arg, str) and "." in arg:  # 長い形の文字列 Fn::GetAtt: A.B.C も最初の . で分ける
            arg = arg.split(".", 1)
        if isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str):
            res, attr = arg
            attr = self.eval(attr, path) if not isinstance(attr, str) else attr
            if res in self.resources and isinstance(attr, str):
                return {"$res": res, "attr": attr, "__fn": fn}
            if res in self.resources:
                return self.unknown({"Fn::GetAtt": arg}, path, "Fn::GetAtt with a computed attribute")
            return self.unknown({"Fn::GetAtt": arg}, path, f"Fn::GetAtt to undefined resource {res}",
                                "CFN-UNDEFINED-REF")
        return self.unknown({"Fn::GetAtt": arg}, path, "malformed Fn::GetAtt")

    def sub(self, arg, path: str):
        if isinstance(arg, str):
            template, variables = arg, {}
        elif isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str) and isinstance(arg[1], dict):
            template, variables = arg
        else:
            return self.unknown({"Fn::Sub": arg}, path, "malformed Fn::Sub")
        parts: list = []
        pos = 0
        for m in SUB_VAR.finditer(template):
            parts.append(template[pos:m.start()])
            pos = m.end()
            var = m.group(1).strip()
            if var.startswith("!"):  # ${!Literal} は ${Literal} という文字列
                parts.append("${" + var[1:] + "}")
            elif var in variables:
                parts.append(self.eval(variables[var], path))
            elif var in self.resources:
                parts.append({"$res": var, "attr": None, "__fn": "Sub"})
            elif "." in var and var.split(".", 1)[0] in self.resources:
                res, attr = var.split(".", 1)
                parts.append({"$res": res, "attr": attr, "__fn": "Sub"})
            elif var in PSEUDO:
                parts.append({"$pseudo": var})
            elif var in self.parameters:
                parts.append(self.parameter(var, path))
            else:
                parts.append(self.unknown({"Ref": var}, path, f"Fn::Sub variable {var} is undefined",
                                          "CFN-UNDEFINED-REF"))
        parts.append(template[pos:])
        return self.concat(parts, path)

    def concat(self, parts: list, path: str):
        flat: list = []
        for p in parts:
            if p is NO_VALUE:  # 文字列の中の AWS::NoValue は CFN でも誤り。値を決められない
                return self.unknown([], path, "AWS::NoValue in a string")
            if isinstance(p, bool):
                p = "true" if p else "false"
            elif isinstance(p, (int, float)):
                p = str(p)
            elif p is None:
                return self.unknown([], path, "null in a string")
            elif isinstance(p, list):  # つなげる値がリストのとき（パラメータの List 型など）は評価できない
                return self.unknown(parts, path, "list value in a string")
            elif isinstance(p, str) and "{{resolve:" in p:
                return self.unknown([], path, "dynamic reference {{resolve:…}}", "CFN-DYNAMIC-REF")
            elif isinstance(p, dict) and "$json" in p:  # 文字列の途中に入る JSON は、元の文字列に戻せないので扱わない
                return self.unknown([], path, "JSON value in a string")
            flat.append(p)
        value = ir_raw.normalize_concat(flat)
        return _maybe_json(value)

    def join(self, arg, path: str):
        if not (isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str)):
            return self.unknown({"Fn::Join": arg}, path, "malformed Fn::Join")
        delim, items = arg[0], self.eval(arg[1], path)
        if not isinstance(items, list):
            return self.unknown({"Fn::Join": arg}, path, "Fn::Join of a non-list value")
        parts: list = []
        for i, it in enumerate(items):
            if i:
                parts.append(delim)
            parts.append(it)
        return self.concat(parts, path)

    def select(self, arg, path: str):
        if not (isinstance(arg, list) and len(arg) == 2):
            return self.unknown({"Fn::Select": arg}, path, "malformed Fn::Select")
        index = self.eval(arg[0], path)
        try:
            index = int(index)
        except (TypeError, ValueError):
            return self.unknown({"Fn::Select": arg}, path, "Fn::Select with a computed index")
        src = arg[1]
        if isinstance(src, dict) and set(src) == {"Fn::GetAZs"}:
            return {"$az": index}
        if isinstance(src, list):
            # 選ばれなかった要素の中の参照は pruned で残す（7.2）
            for i, item in enumerate(src):
                if i != index:
                    self.scan_refs(item, path, "pruned")
            if 0 <= index < len(src):
                return self.eval(src[index], path)
            return self.unknown({"Fn::Select": arg}, path, "Fn::Select index out of range")
        values = self.eval(src, path)
        if isinstance(values, list) and 0 <= index < len(values):
            for i, item in enumerate(values):
                if i != index:
                    for to, attr, fn in _res_with_fn(item):
                        self.extra_refs.append({"from": self.current, "path": path, "to": to, "attr": attr,
                                                "fn": fn, "state": "pruned"})
            return values[index]
        return self.unknown({"Fn::Select": arg}, path, "Fn::Select of a non-list value")

    def split(self, arg, path: str):
        if not (isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str) and arg[0]):
            return self.unknown({"Fn::Split": arg}, path, "malformed Fn::Split")
        delim, src = arg[0], self.eval(arg[1], path)
        if isinstance(src, str):
            return src.split(delim)
        if isinstance(src, dict) and "$concat" in src:
            return split_concat(src["$concat"], delim)
        return self.unknown({"Fn::Split": arg}, path, "Fn::Split of a computed value")


def _res_with_fn(value):
    """評価した後の値の中の $res を (to, attr, fn) で返す（fn は評価中に付けた一時的な __fn）。"""
    if isinstance(value, list):
        for v in value:
            yield from _res_with_fn(v)
    elif isinstance(value, dict):
        if "$res" in value:
            yield value["$res"], value.get("attr"), value.get("__fn", "Ref")
        elif "$concat" in value:
            for v in value["$concat"]:
                yield from _res_with_fn(v)
        elif "$json" in value:
            yield from _res_with_fn(value["$json"])
        elif not ir_raw.is_marker(value):
            for v in value.values():
                yield from _res_with_fn(v)


def split_concat(parts: list, delim: str) -> list:
    """$concat を区切り文字の位置で分ける。印は分けない（7.2 のリストの分割）。"""
    out: list = []
    cur: list = []
    for p in parts:
        if isinstance(p, str):
            pieces = p.split(delim)
            for i, piece in enumerate(pieces):
                if i:
                    out.append(cur)
                    cur = []
                cur.append(piece)
        else:
            cur.append(p)
    out.append(cur)
    return [ir_raw.normalize_concat(c) for c in out]


PLACEHOLDER = "\u0000AWSIACDIAGRAM{}\u0000"


def _maybe_json(value):
    """JSON の文字列（Fn::Sub などで組み立てたものと、印の無いふつうの文字列）を、読めれば $json にする（7.2）。"""
    if isinstance(value, str):
        if not value.lstrip().startswith(("{", "[")):
            return value
        try:
            doc = json.loads(value)
        except ValueError:
            return value
        return {"$json": _escape_keys(doc)} if isinstance(doc, (dict, list)) else value
    if not (isinstance(value, dict) and "$concat" in value):
        return value
    parts = value["$concat"]
    markers = [p for p in parts if not isinstance(p, str)]
    text = "".join(p if isinstance(p, str) else PLACEHOLDER.format(markers.index(p)) for p in parts)
    if not text.lstrip().startswith(("{", "[")):
        return value
    try:
        doc = json.loads(text, strict=False)  # 目印の \u0000 を文字列の中で許す
    except ValueError:
        return value
    placeholder = re.compile("\u0000AWSIACDIAGRAM(\\d+)\u0000")

    def restore(v):
        if isinstance(v, str):
            if not placeholder.search(v):
                return v
            pieces: list = []
            pos = 0
            for m in placeholder.finditer(v):
                pieces.append(v[pos:m.start()])
                pieces.append(markers[int(m.group(1))])
                pos = m.end()
            pieces.append(v[pos:])
            return ir_raw.normalize_concat(pieces)
        if isinstance(v, list):
            return [restore(x) for x in v]
        if isinstance(v, dict):
            if any(placeholder.search(k) for k in v):
                raise ValueError("placeholder in a key")
            return {("$" + k if k.startswith("$") else k): restore(x) for k, x in v.items()}
        return v

    try:
        return {"$json": restore(doc)}
    except ValueError:
        return value


def _escape_keys(v):
    """JSON の中の $ で始まるキーを $$ で逃がす（7.2）。"""
    if isinstance(v, list):
        return [_escape_keys(x) for x in v]
    if isinstance(v, dict):
        return {("$" + k if k.startswith("$") else k): _escape_keys(x) for k, x in v.items()}
    return v


def _static_refs(value, resources: set[str]):
    """評価しない値の中の Ref・GetAtt・Sub の参照を探す（(to, attr, fn) を返す）。"""
    if isinstance(value, list):
        for v in value:
            yield from _static_refs(v, resources)
    elif isinstance(value, dict):
        if len(value) == 1:
            (k, arg), = value.items()
            if k == "Ref" and isinstance(arg, str) and arg in resources:
                yield arg, None, "Ref"
                return
            if k == "Fn::GetAtt":
                if isinstance(arg, str) and "." in arg:
                    arg = arg.split(".", 1)
                if isinstance(arg, list) and arg and isinstance(arg[0], str) and arg[0] in resources:
                    yield arg[0], arg[1] if len(arg) > 1 and isinstance(arg[1], str) else None, "GetAtt"
                    return
            if k == "Fn::Sub":
                tmpl = arg if isinstance(arg, str) else (arg[0] if isinstance(arg, list) and arg else "")
                variables = arg[1] if isinstance(arg, list) and len(arg) > 1 and isinstance(arg[1], dict) else {}
                for m in SUB_VAR.finditer(tmpl if isinstance(tmpl, str) else ""):
                    var = m.group(1).strip()
                    if var in variables or var.startswith("!"):
                        continue
                    if var in resources:
                        yield var, None, "Sub"
                    elif "." in var and var.split(".", 1)[0] in resources:
                        r, a = var.split(".", 1)
                        yield r, a, "Sub"
                yield from _static_refs(variables, resources)
                return
        for v in value.values():
            yield from _static_refs(v, resources)


# ------------------------------------------------------------------ raw IR の組み立て

def _collect_active(value, base: str, frm: str, out: list[dict]):
    """評価した後の値から $res を集めて active の参照にし、一時的な __fn を取り除いた値を返す。"""
    found: list[tuple] = []

    def strip(v, path):
        if isinstance(v, list):
            return [strip(x, ir_raw.join_path(path, i)) for i, x in enumerate(v)]
        if isinstance(v, dict):
            if "$res" in v:
                found.append((path, v["$res"], v.get("attr"), v.get("__fn", "Ref")))
                return {"$res": v["$res"], "attr": v.get("attr")}
            if "$concat" in v:
                return {"$concat": [strip(x, path) if isinstance(x, dict) else x for x in v["$concat"]]}
            if "$json" in v:
                return {"$json": strip(v["$json"], path)}
            if ir_raw.is_marker(v):
                return v
            return {k: strip(x, ir_raw.join_path(path, ir_raw.unescape_key(k))) for k, x in v.items()}
        return v

    cleaned = strip(value, base)
    for path, to, attr, fn in found:
        out.append({"from": frm, "path": path, "to": to, "attr": attr, "fn": fn, "state": "active"})
    return cleaned


def _dedupe(refs: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for r in refs:
        key = ir_raw.ref_key(r)
        # 同じキーなら active を優先する
        if key not in seen or (seen[key]["state"] != "active" and r["state"] == "active"):
            seen[key] = r
    return list(seen.values())


def build_raw(template_path: Path, root_base: Path | None = None) -> dict:
    diagnostics: list[dict] = []
    template = load_template(template_path)
    ev = Evaluator(template, diagnostics)
    resources: list[dict] = []
    refs: list[dict] = []
    for logical_id, body in (template.get("Resources") or {}).items():
        ev.current = logical_id
        if logical_id.startswith("Fn::ForEach::"):
            # AWS::LanguageExtensions の繰り返し。展開は手順4（値が決まらなければ ×N。ir-schema.md の 2章）
            ev.diag("warn", "CFN-DEFERRED", "", "Fn::ForEach is not expanded yet (phase 1 step 4)")
            continue
        if not isinstance(body, dict):
            ev.diag("error", "CFN-MALFORMED-RESOURCE", "", "resource body is not an object")
            continue
        if not isinstance(body.get("Type"), str) or not body["Type"]:
            ev.diag("error", "CFN-MALFORMED-RESOURCE", "Type", "resource has no Type")
            continue
        enabled = True
        if "Condition" in body:
            enabled = None  # 手順4 で評価する
            ev.diag("info", "CFN-CONDITION-DEFERRED", "Condition",
                    f"Condition {body['Condition']} is not evaluated yet (phase 1 step 4)")
        props = ev.eval(body.get("Properties") or {}, "Properties")
        if props is NO_VALUE or not isinstance(props, dict):
            props = {}
        props = _collect_active(props, "Properties", logical_id, refs)
        for key in OUTSIDE_PROPS:
            if key in body:
                _collect_active(ev.eval(body[key], key), key, logical_id, refs)
        depends = body.get("DependsOn") or []
        for i, dep in enumerate([depends] if isinstance(depends, str) else depends):
            if dep in ev.resources:
                refs.append({"from": logical_id, "path": "DependsOn", "to": dep, "attr": None, "fn": "DependsOn",
                             "state": "active"})
            else:
                ev.diag("warn", "CFN-UNDEFINED-REF", "DependsOn", f"DependsOn to undefined resource {dep}")
        resources.append({"address": logical_id, "type": body["Type"],
                          "file": template_path.name, "enabled": enabled, "props": props})
    refs = _dedupe(refs + ev.extra_refs)
    # active の参照が props にあるものと重なった pruned／unevaluated は、active だけを残す（_dedupe 済み）
    root_base = root_base or Path.cwd()
    try:
        root = Path(os.path.relpath(template_path.resolve(), root_base.resolve())).as_posix()
    except ValueError:  # Windows でドライブが違うと相対パスにできない
        root = template_path.resolve().as_posix()
        ev.current = ""
        ev.diag("info", "CFN-ABSOLUTE-ROOT", "", "root is on another drive; written as an absolute path")
    # 同じ診断（同じ場所・同じ内容）は1つにまとめる
    diagnostics[:] = list({(d.get("address", ""), d.get("path", ""), d["code"], d["message"]): d
                           for d in diagnostics}.values())
    raw = {
        "ir_version": "1.0",
        "stage": "raw",
        "format": "cfn",
        "root": root,
        "evaluation": {"parameters": {k: v for k, v in sorted(ev.param_values.items())}, "conditions": {},
                       "assumptions": []},
        "resources": resources,
        "references": refs,
        "diagnostics": diagnostics,
    }
    return ir_raw.canonical_raw(raw)


def dump(raw: dict) -> str:
    return json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="CloudFormation のテンプレートから raw IR を作る")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--root-base", type=Path, default=None)
    a = ap.parse_args(argv)
    try:
        raw = build_raw(a.input, a.root_base)
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"テンプレートを読めませんでした: {a.input}: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001  想定外の失敗も終了コード 2 で返す（自分を指すアンカーの RecursionError など）
        print(f"テンプレートの評価に失敗しました: {a.input}: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(dump(raw), encoding="utf-8", newline="\n")
    print(f"raw: resources={len(raw['resources'])} references={len(raw['references'])} "
          f"diagnostics={len(raw['diagnostics'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
