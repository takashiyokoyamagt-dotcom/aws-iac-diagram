# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML==6.0.3"]
# ///
"""CloudFormation のテンプレートを読み、アダプタの出力（raw IR。references/ir-schema.md の 7章）を作る。

いまの範囲（フェーズ1 の手順2〜4）:
  - YAML の短縮タグ（!Ref など）を Fn::* の長い形に正規化する（PLAN 2.2 の失敗知見 13。awscli の yamlhelper と同じ考え方）
  - Ref・Fn::GetAtt・Fn::Sub・Fn::Join・Fn::Select・Fn::Split・Fn::GetAZs・Fn::ImportValue・DependsOn を評価し、
    props の印（$res・$pseudo・$concat・$json・$az・$import・$unknown）と references を作る
  - パラメータは、外から渡した値（--param、--param-file）→ Default の順に使う（どちらも無ければ $unknown）。
    ネストスタックでは親から渡された値を使う
  - A4: Conditions（Fn::Equals・And・Or・Not・Condition）を 真／偽／決まらない の3つの値で評価する。
    リソースの Condition から enabled を決め、ネストスタックの子にも伝える。Fn::If・Fn::FindInMap（DefaultValue を含む）・
    Fn::Length・Fn::ToJsonString を評価する。Fn::ForEach（AWS::LanguageExtensions）を展開する（値が決まらなければ ×N）
  - YAML の値の真偽値は YAML 1.1 のまま（cfn-lint と同じ）。マップのキーは元の文字のまま読む
  - SAM: Globals を各リソースに混ぜる。Events に API の指定が無いときは、暗黙の API（implicit）を足す
  - ネストスタック: 子テンプレートを展開し、Outputs・Parameters をたどって元のリソースへの $res にする（経路は through）。
    TemplateURL が URL なら手元のファイルに読み替え、読めなければ黒箱（via: module_blackbox）にする
  - cdk.out: manifest.json のスタックをすべて読み、address に "<スタック名>::" を付ける。Export を ImportValue で解決する
評価できない値（決まらない条件の Fn::If、Fn::Base64、Fn::Cidr など）は $unknown にし、中の参照は
state: "unevaluated" で残す。選ばれなかった値の中の参照は state: "pruned" で残す。

使い方:
  uv run scripts/adapters/cfn.py --input <テンプレートか cdk.out のフォルダ> --out <raw.json>
      [--root-base <フォルダ>] [--param KEY=VALUE ...] [--param-file <parameters.json> ...]
  --root-base: raw IR の root を、このフォルダからの相対パスで書く（既定: 作業中のフォルダ）
  --param: パラメータの値。AWS::Region などの擬似パラメータは、条件の評価にだけ使う（props は $pseudo のまま）
  --param-file: aws cloudformation の CLI の形（[{"ParameterKey", "ParameterValue"}]）、{"Parameters": {...}}、{キー: 値}

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
# 条件関数（Conditions の中と、プロパティの中の両方で評価する）
CONDITION_FNS = {"Fn::Equals", "Fn::And", "Fn::Or", "Fn::Not"}
# 評価しない関数（値は $unknown。中の参照は unevaluated で残す）
UNEVALUATED = {"Fn::Base64", "Fn::Cidr", "Fn::Transform", "Fn::ForEach"}
UNKNOWN = object()  # 条件の評価で、値が決まらないもの
OUTSIDE_PROPS = ("Metadata", "CreationPolicy", "UpdatePolicy")
SUB_VAR = re.compile(r"\$\{([^}]*)\}")


# ------------------------------------------------------------------ 読み込み

class _Loader(yaml.SafeLoader):
    """短縮タグを Fn::* の長い形にする。日付・時刻の暗黙の型変換はしない（'2010-09-09' を文字列のまま読む）。

    値の真偽値は YAML 1.1 のまま（yes・on なども真偽値。cfn-lint と同じ）。マップのキーは元の文字のまま読む
    （Yes・On・1 のようなキーも文字列の名前として残す。条件・リソース・Mappings の名前を失わないように）。
    """

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.MappingNode):
            return super().construct_mapping(node, deep=deep)
        self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.ScalarNode):
                key = key_node.value
            else:
                key = self.construct_object(key_node, deep=True)
            mapping[key] = self.construct_object(value_node, deep=True)
        return mapping


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
YAML11_TRUE = {"yes", "true", "on"}
YAML11_FALSE = {"no", "false", "off"}


def _bool_name(value, names):
    """名前の位置に YAML 1.1 の真偽値として読まれた値（Condition: Yes など）を、元の名前に戻す。決まらなければ None。"""
    if not isinstance(value, bool):
        return value if isinstance(value, str) else None
    words = YAML11_TRUE if value else YAML11_FALSE
    hits = [n for n in names if isinstance(n, str) and n.lower() in words]
    return hits[0] if len(hits) == 1 else None


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

    def __init__(self, template: dict, diagnostics: list[dict], prefix: str = "",
                 overrides: dict | None = None, stack_address: str | None = None):
        self.template = template
        self.resources = template.get("Resources") or {}
        self.parameters = template.get("Parameters") or {}
        self.diagnostics = diagnostics
        self.prefix = prefix  # address の前に付けるもの（ネストスタックの "NetworkStack/"、cdk.out の "App::"）
        self.overrides = overrides or {}  # 親のスタックから渡されたパラメータの値（評価済み）
        self.stack_address = stack_address  # ネストスタックなら、親の中のスタックのリソースの address
        self.param_values: dict = {}
        self.extra_refs: list[dict] = []  # pruned / unevaluated の参照
        self.current: str = ""  # いま評価しているリソースの address
        self.stack_name: str | None = None  # 分かっているスタック名（cdk.out）
        self.resolve_stack_name = False  # True の間だけ AWS::StackName をスタック名にする（Export の名前）
        self.conditions = template.get("Conditions") or {}
        self.mappings = template.get("Mappings") or {}
        self.condition_values: dict = {}  # 評価した条件（True／False／None）
        self.given: dict = {}  # 外から渡されたパラメータの値（最上位のスタックだけ。--param、--param-file）
        self.pseudo_values: dict = {}  # 条件の評価にだけ使う擬似パラメータの値（--param AWS::Region=…）
        self.in_condition = False

    def addr(self, logical_id: str) -> str:
        return self.prefix + logical_id

    # --- ネストスタック・Export（StackEval が上書きする。単独のテンプレートでは何もしない）
    def stack_output(self, res: str, output: str, path: str):
        return {"$res": self.addr(res), "attr": f"Outputs.{output}", "__fn": "GetAtt"}

    def import_value(self, name: str, path: str):
        return {"$import": name}

    # --- 診断と参照
    def diag(self, level: str, code: str, path: str, message: str) -> None:
        self.diagnostics.append({"level": level, "code": code, "address": self.current, "path": path,
                                 "message": message})

    def scan_refs(self, value, path: str, state: str) -> None:
        """評価しない値の中の参照を、static に探して state 付きで残す。"""
        for to, attr, fn in _static_refs(value, set(self.resources)):
            self.extra_refs.append({"from": self.current, "path": path, "to": self.addr(to), "attr": attr, "fn": fn,
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
        ptype = str(p.get("Type", ""))
        if name in self.overrides:
            # 親から渡された値。List 型なら区切り文字で分け、たどった経路を through に足す（7.2・7.3）
            value = self.overrides[name]
            if ptype.startswith("List<") or ptype == "CommaDelimitedList":
                if isinstance(value, str):
                    value = [s.strip() for s in value.split(",")]
                elif isinstance(value, dict) and "$concat" in value:
                    value = split_concat(value["$concat"], ",")
                elif not isinstance(value, list) and not (isinstance(value, dict) and "$unknown" in value):
                    value = [value]  # 要素が1つの !Join は印そのものになるので、リストに包む
            value = _prepend_through(value, f"{self.stack_address}.Parameters.{name}")
            self.param_values[name] = value
            return value
        if ptype.startswith("AWS::SSM::Parameter::Value<"):
            # SSM のパラメータの名前が渡されても、値は分からない（Default のときと同じ）
            value = {"$unknown": f"parameter {name} is an SSM parameter"}
            self.diag("warn", "CFN-SSM-PARAM", path, f"parameter {name} is an SSM parameter")
            self.param_values[name] = value
            return value
        if self.given.get(name) is not None:  # null（UsePreviousValue など）は渡されていないものとして Default に進む
            value = self.given[name]
            allowed = p.get("AllowedValues")
            if isinstance(allowed, list) and str(value) not in [str(a) for a in allowed]:
                self.diag("warn", "CFN-PARAM-NOT-ALLOWED", path,
                          f"parameter {name}: {value} is not in AllowedValues {allowed}")
            if ptype.startswith("List<") or ptype == "CommaDelimitedList":
                value = [str(x) for x in value] if isinstance(value, list) else [s.strip() for s in str(value).split(",")]
            elif ptype == "Number" and isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
                value = int(value)
            self.param_values[name] = value
            return value
        if "Default" not in p:
            v = {"$unknown": f"parameter {name} has no value"}
            self.diag("warn", "CFN-UNRESOLVED-PARAM", path, f"parameter {name} has no value")
            return v
        value = p["Default"]
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
                    return self.import_value(name, path)
                return self.unknown(arg, path, f"Fn::ImportValue with a computed name {json.dumps(name, ensure_ascii=False)}")
            if key == "Fn::If":
                return self.fn_if(arg, path)
            if key == "Fn::FindInMap":
                return self.find_in_map(arg, path)
            # {"Condition": "名前"} だけが条件関数。値がオブジェクトなら、IAM の Condition などのふつうのプロパティ
            if key in CONDITION_FNS or (key == "Condition" and isinstance(arg, str)):
                v = self.cond_eval(node, path)
                return v if v is not None else self.unknown(node, path, f"{key} cannot be decided")
            if key == "Fn::Length":
                v = self.eval(arg, path)
                return len(v) if isinstance(v, list) else self.unknown(arg, path, "Fn::Length of a non-list value")
            if key == "Fn::ToJsonString":
                v = self.eval(arg, path)
                return {"$json": v} if v is not NO_VALUE else self.unknown([], path, "Fn::ToJsonString of no value")
            if key in UNEVALUATED or key.startswith("Fn::"):
                return self.unknown(node, path, f"{key} is not evaluated")
        if any(isinstance(k, str) and k.startswith("Fn::ForEach::") for k in node):
            node = self.expand_inline_foreach(node, path)
        out = {}
        for k, v in node.items():
            ev = self.eval(v, ir_raw.join_path(path, k))
            if ev is not NO_VALUE:
                out["$" + k if k.startswith("$") else k] = ev  # 入力の $ のキーは $$ で逃がす（7.2）
        return out

    def expand_inline_foreach(self, node: dict, path: str) -> dict:
        """プロパティの中の Fn::ForEach::<名前> を展開する。決まらなければ落とし、中の参照を unevaluated で残す。"""
        out: dict = {}
        for k, v in node.items():
            if not (isinstance(k, str) and k.startswith("Fn::ForEach::")):
                out[k] = v
                continue
            if not (isinstance(v, list) and len(v) == 3 and isinstance(v[0], str) and isinstance(v[2], dict)):
                self.unknown(v, path, f"malformed {k}")
                continue
            ident, collection, templates = v
            values = self.eval(collection, path)
            if isinstance(values, list) and all(isinstance(x, (str, int)) and not isinstance(x, bool) for x in values):
                for x in values:
                    for tk, tv in templates.items():
                        out[_foreach_subst(tk, ident, str(x))] = _foreach_subst(tv, ident, str(x))
            else:
                self.unknown(templates, path, f"{k}: the collection cannot be decided", "CFN-FOREACH-UNRESOLVED")
        return out

    def pseudo(self, name: str):
        if name == "AWS::StackName" and self.resolve_stack_name and self.stack_name:
            return self.stack_name
        if self.in_condition and name in self.pseudo_values:
            return self.pseudo_values[name]
        return {"$pseudo": name}

    # --- 条件（A4）
    def condition(self, name, path: str = ""):
        """名前の付いた条件を評価する。True／False／None（決まらない）。"""
        name = _bool_name(name, self.conditions) if isinstance(name, bool) else name
        if not isinstance(name, str) or name not in self.conditions:
            self.diag("warn", "CFN-UNDEFINED-CONDITION", path, f"condition {name} is undefined")
            return None
        if name not in self.condition_values:
            self.condition_values[name] = UNKNOWN  # 循環の検出
            v = self.cond_eval(self.conditions[name], f"Conditions.{name}")
            self.condition_values[name] = v
        v = self.condition_values[name]
        if v is UNKNOWN:
            self.diag("error", "CFN-CONDITION-CYCLE", path, f"condition {name} refers to itself")
            return None
        return v

    def cond_eval(self, node, path: str):
        """条件関数を3つの値（True／False／None）で評価する。"""
        if isinstance(node, bool):
            return node
        if isinstance(node, str) and node.lower() in ("true", "false"):
            return node.lower() == "true"
        if not (isinstance(node, dict) and len(node) == 1):
            return None
        (key, arg), = node.items()
        if key == "Condition":
            return self.condition(arg, path)
        if key == "Fn::Equals" and isinstance(arg, list) and len(arg) == 2:
            a, b = (self.cond_value(x, path) for x in arg)
            if a is UNKNOWN or b is UNKNOWN:
                return None
            return _cfn_str(a) == _cfn_str(b)
        if key in ("Fn::And", "Fn::Or") and isinstance(arg, list):
            vals = [self.cond_eval(x, path) for x in arg]
            hit = key == "Fn::Or"  # Or は True が1つでもあれば True、And は False が1つでもあれば False
            if hit in vals:
                return hit
            return None if None in vals else not hit
        if key == "Fn::Not" and isinstance(arg, list) and len(arg) == 1:
            v = self.cond_eval(arg[0], path)
            return None if v is None else not v
        return None

    def cond_value(self, node, path: str):
        """Fn::Equals の引数を評価する。値が決まらなければ UNKNOWN。参照は残さない（条件はリソースを参照しない）。"""
        saved, n = self.in_condition, len(self.extra_refs)
        self.in_condition = True
        try:
            v = self.eval(node, path)
        finally:
            self.in_condition = saved
            del self.extra_refs[n:]
        if isinstance(v, (str, int, float, bool)):
            return v
        if isinstance(v, list) and all(isinstance(x, (str, int, float, bool)) for x in v):
            return v
        return UNKNOWN

    def fn_if(self, arg, path: str):
        if not (isinstance(arg, list) and len(arg) == 3):
            return self.unknown({"Fn::If": arg}, path, "malformed Fn::If")
        c = self.condition(arg[0], path)
        if c is None:
            return self.unknown({"Fn::If": arg}, path, f"condition {arg[0]} cannot be decided",
                                "CFN-CONDITION-UNKNOWN")
        chosen, other = (arg[1], arg[2]) if c else (arg[2], arg[1])
        self.scan_refs(other, path, "pruned")  # 選ばれなかった側の参照は pruned（7.2）
        return self.eval(chosen, path)

    def find_in_map(self, arg, path: str):
        if not (isinstance(arg, list) and len(arg) in (3, 4)):
            return self.unknown({"Fn::FindInMap": arg}, path, "malformed Fn::FindInMap")
        # キーの評価には擬似パラメータの値を使う（リージョンごとの AMI の表など。マップの値は参照を含まない）
        saved = self.in_condition
        self.in_condition = True
        try:
            keys = [self.eval(k, path) for k in arg[:3]]
        finally:
            self.in_condition = saved
        default = arg[3].get("DefaultValue") if len(arg) == 4 and isinstance(arg[3], dict) else None
        if not all(isinstance(k, (str, int)) and not isinstance(k, bool) for k in keys):
            return self.unknown({"Fn::FindInMap": arg}, path, "Fn::FindInMap with a computed key")
        m, top, second = (str(k) for k in keys)
        table = {str(k): v for k, v in self.mappings.items()}.get(m)
        value = None
        if isinstance(table, dict):
            row = {str(k): v for k, v in table.items()}.get(top)
            if isinstance(row, dict):
                value = {str(k): v for k, v in row.items()}.get(second)
        if value is None:
            if default is not None:  # AWS::LanguageExtensions の DefaultValue
                return self.eval(default, path)
            return self.unknown([], path, f"Fn::FindInMap: {m}.{top}.{second} is not in Mappings",
                                "CFN-MAPPING-MISSING")
        return self.eval(value, path)

    def is_stack(self, logical_id: str) -> bool:
        body = self.resources.get(logical_id)
        return isinstance(body, dict) and body.get("Type") == "AWS::CloudFormation::Stack"

    def ref(self, name, path: str):
        if isinstance(name, bool):
            name = _bool_name(name, list(self.resources) + list(self.parameters))
        if not isinstance(name, str):
            return self.unknown({"Ref": name}, path, "Ref with a non-string argument")
        if name == "AWS::NoValue":
            return NO_VALUE
        if name in PSEUDO:
            return self.pseudo(name)
        if name in self.resources:
            return {"$res": self.addr(name), "attr": None, "__fn": "Ref"}
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
                if attr.startswith("Outputs.") and self.is_stack(res):
                    return self.stack_output(res, attr[len("Outputs."):], path)
                return {"$res": self.addr(res), "attr": attr, "__fn": fn}
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
                parts.append({"$res": self.addr(var), "attr": None, "__fn": "Sub"})
            elif "." in var and var.split(".", 1)[0] in self.resources:
                res, attr = var.split(".", 1)
                if attr.startswith("Outputs.") and self.is_stack(res):
                    parts.append(self.stack_output(res, attr[len("Outputs."):], path))
                else:
                    parts.append({"$res": self.addr(res), "attr": attr, "__fn": "Sub"})
            elif var in PSEUDO:
                parts.append(self.pseudo(var))
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


def _cfn_str(v) -> str:
    """Fn::Equals で比べるときの文字列（CFN は値を文字列として比べる）。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ",".join(_cfn_str(x) for x in v)
    return str(v)


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


# ------------------------------------------------------------------ 一時的な印の扱い（__fn と __through）

def _walk_res(value, fn):
    """値の中の $res の印のそれぞれに fn(印) を当てたコピーを返す。"""
    if isinstance(value, list):
        return [_walk_res(v, fn) for v in value]
    if isinstance(value, dict):
        if "$res" in value:
            return fn(dict(value))
        if "$concat" in value:
            return {"$concat": [_walk_res(v, fn) for v in value["$concat"]]}
        if "$json" in value:
            return {"$json": _walk_res(value["$json"], fn)}
        if ir_raw.is_marker(value):
            return value
        return {k: _walk_res(v, fn) for k, v in value.items()}
    return value


def _prepend_through(value, hop: str):
    """ネストスタックの出力・パラメータ、Export をたどったとき、経路を through の先頭に足す（7.3）。"""
    def f(m):
        m["__through"] = [hop] + m.get("__through", [])
        return m
    return _walk_res(value, f)


def _set_fn(value, fn_name: str):
    def f(m):
        m["__fn"] = fn_name
        return m
    return _walk_res(value, f)


def _strip_internal(value):
    """出力する前に、一時的な __fn・__through を取り除く。"""
    def f(m):
        return {"$res": m["$res"], "attr": m.get("attr")}
    return _walk_res(value, f)


# ------------------------------------------------------------------ raw IR の組み立て

def _collect_active(value, base: str, frm: str, out: list[dict]):
    """評価した後の値から $res を集めて active の参照にし、一時的な印を取り除いた値を返す。"""
    found: list[tuple] = []

    def strip(v, path):
        if isinstance(v, list):
            return [strip(x, ir_raw.join_path(path, i)) for i, x in enumerate(v)]
        if isinstance(v, dict):
            if "$res" in v:
                found.append((path, v["$res"], v.get("attr"), v.get("__fn", "Ref"), v.get("__through")))
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
    for path, to, attr, fn, through in found:
        ref = {"from": frm, "path": path, "to": to, "attr": attr, "fn": fn, "state": "active"}
        if through:
            ref["through"] = through
        out.append(ref)
    return cleaned


def _dedupe(refs: list[dict]) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for r in refs:
        key = ir_raw.ref_key(r)
        # 同じキーなら active を優先する
        if key not in seen or (seen[key]["state"] != "active" and r["state"] == "active"):
            seen[key] = r
    return list(seen.values())


TEMPLATE_SUFFIXES = (".yaml", ".yml", ".json", ".template")
IN_PROGRESS = object()  # 子のスタックを展開している途中（循環の検出）
# SAM の Globals の節 → 混ぜる先の型
GLOBALS = {"Function": "AWS::Serverless::Function", "Api": "AWS::Serverless::Api",
           "HttpApi": "AWS::Serverless::HttpApi", "SimpleTable": "AWS::Serverless::SimpleTable",
           "StateMachine": "AWS::Serverless::StateMachine", "LayerVersion": "AWS::Serverless::LayerVersion"}
STACK_NAME = re.compile(r"[A-Za-z][-A-Za-z0-9]*")


def _merge_globals(global_props, props):
    """SAM の Globals の混ぜ方: マップは中まで混ぜ、リストは Globals の後ろにつなぎ、値はリソースの方を使う。

    組み込み関数（Ref・Fn::*・Condition のキーが1つのオブジェクト）はマップではなく1つの値として扱う（SAM と同じ）。
    """
    if (isinstance(global_props, dict) and isinstance(props, dict)
            and not _is_intrinsic(global_props) and not _is_intrinsic(props)):
        out = dict(global_props)
        for k, v in props.items():
            out[k] = _merge_globals(global_props[k], v) if k in global_props else v
        return out
    if isinstance(global_props, list) and isinstance(props, list):
        return global_props + props
    return props


def _is_intrinsic(v) -> bool:
    if not (isinstance(v, dict) and len(v) == 1):
        return False
    key = next(iter(v))
    return key in ("Ref", "Condition") or key.startswith("Fn::")


def _stronger(a, b):
    """enabled の強い方。true > null > false（どれか1つでも作られるなら作られる）。"""
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def _weaker(a, b):
    """作られるか（enabled）の弱い方。false > null > true（親のスタックの Condition を子に引き継ぐ）。"""
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


SKIP_DIRS = {"node_modules", ".git", "cdk.out", ".aws-sam", "__pycache__", ".venv"}


class Context:
    """1回の読み込み全体で共有するもの（リソースと参照の集まり、診断、Export の表）。"""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.diagnostics: list[dict] = []
        self.resources: list[dict] = []
        self.refs: list[dict] = []
        self.stacks: list["StackEval"] = []
        self.assumptions: list[str] = []
        self.exports: dict[str, tuple["StackEval", str]] = {}
        self.active_files: list[Path] = []
        self._files: list[str] | None = None
        self.pseudo_values: dict = {}

    def rel(self, path: Path) -> str:
        return Path(os.path.relpath(path.resolve(), self.root_dir.resolve())).as_posix()

    def local_files(self) -> list[str]:
        """URL を読み替える候補のファイル。node_modules・.git などの下は除く。"""
        if self._files is None:
            self._files = sorted(
                self.rel(p) for p in self.root_dir.rglob("*")
                if p.is_file() and p.suffix.lower() in TEMPLATE_SUFFIXES
                and not SKIP_DIRS.intersection(p.relative_to(self.root_dir).parts[:-1]))
        return self._files


class StackEval(Evaluator):
    """1つのスタック（テンプレート）を評価する。子のスタックは、出力を使うときか、スタックのリソースを読むときに展開する。"""

    def __init__(self, ctx: Context, template: dict, path: Path, prefix: str = "",
                 overrides: dict | None = None, stack_address: str | None = None,
                 enabled: bool | None = True, asset_dir: Path | None = None, stack_name: str | None = None,
                 given: dict | None = None):
        super().__init__(template, ctx.diagnostics, prefix, overrides, stack_address)
        self.ctx = ctx
        self.given = given or {}
        self.pseudo_values = ctx.pseudo_values
        self.path = path
        self.file = ctx.rel(path)
        self.enabled = enabled  # 親のスタックのリソースの enabled（子のリソースに引き継ぐ）
        self.asset_dir = asset_dir or ctx.root_dir  # CDK の asset のパスの基準（入れ子のアセンブリのフォルダ）
        self.stack_name = stack_name  # cdk.out のスタック名（Export の名前の AWS::StackName を解く）
        self.children: dict[str, object] = {}
        self.outputs: dict[str, object] = {}
        self.output_extras: dict[str, list[dict]] = {}
        self.multiplicity: dict[str, str] = {}
        self.foreach_origin: dict[str, str] = {}
        self.resources = self.expand_foreach(self.resources)
        if isinstance(self.template.get("Outputs"), dict):
            self.template = {**self.template, "Outputs": self.expand_foreach(self.template["Outputs"], record=False)}
        ctx.stacks.append(self)

    # --- Fn::ForEach（AWS::LanguageExtensions）
    def expand_foreach(self, resources: dict, depth: int = 0, record: bool = True) -> dict:
        """Resources（と Outputs）の Fn::ForEach::<名前> を展開する。値が決まらなければ ×N（ir-schema.md の 2章）。

        展開した名前が重なったら、後のものは診断を出して飛ばす（CloudFormation でも誤り）。
        ×N の名前が重なったら、後ろに ".<ForEach の名前>" を付けて両方残す（網羅の A6 で落とさない）。
        """
        out: dict = {}

        def put(name, body):
            if name in out:
                self.diag("error", "CFN-FOREACH-DUPLICATE", name, f"{name} is defined more than once; the later one is ignored")
            else:
                out[name] = body
        for key, body in resources.items():
            if not (isinstance(key, str) and key.startswith("Fn::ForEach::")):
                put(key, body)
                continue
            self.current = self.where()
            if not (isinstance(body, list) and len(body) == 3 and isinstance(body[0], str)
                    and isinstance(body[2], dict)) or depth > 5:
                self.diag("error", "CFN-MALFORMED-RESOURCE", key, "malformed Fn::ForEach")
                continue
            ident, collection, templates = body
            saved, n = self.in_condition, len(self.extra_refs)
            values = self.eval(collection, key)
            del self.extra_refs[n:]
            self.in_condition = saved
            if isinstance(values, list) and all(isinstance(v, (str, int)) and not isinstance(v, bool)
                                                for v in values):
                for v in values:
                    for tkey, tbody in templates.items():
                        out_key = _foreach_subst(tkey, ident, str(v))
                        expanded = self.expand_foreach({out_key: _foreach_subst(tbody, ident, str(v))}, depth + 1, record)
                        for k2, b2 in expanded.items():
                            put(k2, b2)
            else:
                self.diag("warn", "CFN-FOREACH-UNRESOLVED", key,
                          f"{key}: the collection cannot be decided; drawn once as xN")
                for tkey, tbody in templates.items():
                    name = re.sub(r"[$&]\{[^}]*\}", "*", tkey)
                    if name in out:
                        name = f"{name}.{key[len('Fn::ForEach::'):]}"
                    # 識別子は * にする（Ref が未定義の名前の警告にならないように）
                    put(name, _foreach_subst(tbody, ident, "*"))
                    if record:
                        self.multiplicity[name] = "N"
        return out

    def where(self) -> str:
        """このスタックの出力などの診断に使う address（最上位なら空）。"""
        return self.stack_address or self.prefix.rstrip(":/")

    # --- 出力と Export
    def output(self, name: str):
        """このスタックの Outputs の値（評価済み。一時的な印付き）。無ければ None。

        出力の中の pruned／unevaluated の参照は、使った側の参照にするので output_extras に取っておく。
        """
        if name not in self.outputs:
            body = (self.template.get("Outputs") or {}).get(name)
            if not isinstance(body, dict) or "Value" not in body:
                self.outputs[name] = None
            else:
                saved, n = self.current, len(self.extra_refs)
                self.current = self.where()
                self.outputs[name] = self.eval(body["Value"], f"Outputs.{name}")
                self.output_extras[name] = self.extra_refs[n:]
                del self.extra_refs[n:]
                self.current = saved
        return self.outputs[name]

    def register_exports(self) -> None:
        for name, body in (self.template.get("Outputs") or {}).items():
            if isinstance(body, dict) and isinstance(body.get("Export"), dict):
                saved, n = self.current, len(self.extra_refs)
                self.current = self.where()
                if "Condition" in body:
                    c = self.condition(body["Condition"], f"Outputs.{name}.Condition")
                    if c is False:  # 作られない出力の Export は無い
                        self.current = saved
                        continue
                    if c is None:
                        self.diag("info", "CFN-CONDITION-UNKNOWN", f"Outputs.{name}.Condition",
                                  f"output {name}: condition cannot be decided; the export is used")
                self.resolve_stack_name = True  # cdk.out ではスタック名が分かるので、Export の名前の中だけ解く
                export = self.eval(body["Export"].get("Name"), f"Outputs.{name}.Export.Name")
                self.resolve_stack_name = False
                del self.extra_refs[n:]
                if isinstance(export, str):
                    if export in self.ctx.exports and self.ctx.exports[export] != (self, name):
                        self.diag("warn", "CFN-EXPORT-CONFLICT", f"Outputs.{name}.Export.Name",
                                  f"export {export} is defined more than once; the first one is used")
                    else:
                        self.ctx.exports[export] = (self, name)
                self.current = saved

    def import_value(self, name: str, path: str):
        hit = self.ctx.exports.get(name)
        if hit is None:
            return {"$import": name}
        stack, output = hit
        value = stack.output(output)
        if value is None:
            return {"$import": name}
        return _set_fn(_prepend_through(value, f"Export:{name}"), "ImportValue")

    # --- ネストスタック
    def stack_output(self, res: str, output: str, path: str):
        child = self.child(res)
        if child is IN_PROGRESS:
            return self.unknown([], path, f"nested stack {res} refers to itself", "CFN-NESTED-CYCLE")
        if child is None:  # 読めないスタックは黒箱。出力への参照はスタックへの参照のまま
            return super().stack_output(res, output, path)
        value = child.output(output)
        if value is None:
            return self.unknown([], path, f"output {output} is not in nested stack {res}", "CFN-UNDEFINED-REF")
        hop = f"{self.addr(res)}.Outputs.{output}"
        # 出力の中の pruned／unevaluated の参照は、使った側（いまのリソース）の参照にする
        for r in child.output_extras.get(output, []):
            self.extra_refs.append({**r, "from": self.current, "path": path,
                                    "through": [hop] + r.get("through", [])})
        # 出力の値に参照が残らない（文字列になった、評価できなかった）ときも、スタックへの参照を残す（7.3）
        if not any(True for _ in _res_with_fn(value)):
            self.extra_refs.append({"from": self.current, "path": path, "to": self.addr(res),
                                    "attr": f"Outputs.{output}", "fn": "GetAtt", "state": "unevaluated"})
        return _prepend_through(value, hop)

    def locate(self, res: str, body: dict) -> Path | None:
        """子テンプレートのファイルを探す（ir-schema.md の 7.4）。見つからなければ None。"""
        meta = body.get("Metadata") or {}
        asset = meta.get("aws:asset:path") if isinstance(meta, dict) else None
        if isinstance(asset, str) and (self.asset_dir / asset).is_file():  # CDK のネストスタック
            return self.asset_dir / asset
        saved = self.current
        self.current = self.addr(res)
        url = self.eval((body.get("Properties") or {}).get("TemplateURL"), "Properties.TemplateURL")
        self.current = saved
        if isinstance(url, str) and "://" not in url and not url.startswith("s3:"):
            local = (self.path.parent / url)
            return local if local.is_file() else None
        if isinstance(url, dict) and "$concat" in url and isinstance(url["$concat"][-1], str):
            url = url["$concat"][-1]  # 組み立てた URL は、最後の印より後ろの文字列（パス）で比べる
        if not isinstance(url, str):
            return None
        tail = [s for s in re.sub(r"^[a-z0-9]+://[^/]*", "", url).split("?")[0].split("/") if s]
        best, hits = 0, []
        for f in self.ctx.local_files():
            segs = f.split("/")
            n = 0
            while n < min(len(segs), len(tail)) and segs[-1 - n] == tail[-1 - n]:
                n += 1
            if n > best:
                best, hits = n, [f]
            elif n == best and n:
                hits.append(f)
        if best and len(hits) == 1:
            self.ctx.assumptions.append(f"{self.addr(res)}: TemplateURL {url} を {hits[0]} に読み替えた")
            return self.ctx.root_dir / hits[0]
        return None

    def child(self, res: str):
        if res in self.children:
            return self.children[res]
        body = self.resources[res]
        path = self.locate(res, body)
        if path is None:
            self.children[res] = None
            saved, self.current = self.current, self.addr(res)
            self.diag("warn", "CFN-NESTED-UNREADABLE", "Properties.TemplateURL",
                      f"nested stack {res}: the child template is not found; drawn as a black box")
            self.current = saved
            return None
        if path.resolve() in self.ctx.active_files:
            self.children[res] = None
            saved, self.current = self.current, self.addr(res)
            self.diag("error", "CFN-NESTED-CYCLE", "Properties.TemplateURL", f"nested stack {res} includes itself")
            self.current = saved
            return None
        self.children[res] = IN_PROGRESS
        saved, self.current = self.current, self.addr(res)
        overrides = {}
        for k, v in ((body.get("Properties") or {}).get("Parameters") or {}).items():
            val = self.eval(v, ir_raw.join_path("Properties.Parameters", k))
            if val is not NO_VALUE:
                overrides[k] = val
        self.current = saved
        try:
            template = load_template(path)
        except (OSError, ValueError, yaml.YAMLError) as e:
            self.children[res] = None
            self.diag("error", "CFN-NESTED-UNREADABLE", "Properties.TemplateURL", f"nested stack {res}: {e}")
            return None
        # 親のスタックのリソースが作られないなら、子のリソースも作られない
        enabled = _weaker(self.enabled, self.condition(body["Condition"], "Condition") if "Condition" in body else True)
        child = StackEval(self.ctx, template, path, prefix=self.addr(res) + "/", overrides=overrides,
                          stack_address=self.addr(res), enabled=enabled, asset_dir=self.asset_dir)
        child.register_exports()
        self.ctx.active_files.append(path.resolve())
        child.run()
        self.ctx.active_files.pop()
        self.children[res] = child
        return child

    # --- 本体
    def run(self) -> None:
        ctx = self.ctx
        ctx.active_files.append(self.path.resolve())
        globals_ = self.template.get("Globals") or {}
        implicit: dict[tuple[str, str], object] = {}  # 暗黙の API → それを作る関数の enabled の強い方
        for logical_id, body in self.resources.items():
            address = self.addr(logical_id)
            self.current = address
            if not isinstance(body, dict):
                self.diag("error", "CFN-MALFORMED-RESOURCE", "", "resource body is not an object")
                continue
            rtype = body.get("Type")
            if not isinstance(rtype, str) or not rtype:
                self.diag("error", "CFN-MALFORMED-RESOURCE", "Type", "resource has no Type")
                continue
            raw_props = body.get("Properties") or {}
            for section, target in GLOBALS.items():
                if rtype == target and isinstance(globals_.get(section), dict) and isinstance(raw_props, dict):
                    raw_props = _merge_globals(globals_[section], raw_props)
            enabled = self.enabled  # 親のスタックの enabled を引き継ぐ
            if "Condition" in body:
                c = self.condition(body["Condition"], "Condition")
                enabled = _weaker(enabled, c)
                if c is None and _bool_name(body["Condition"], self.conditions) in self.conditions:
                    self.diag("info", "CFN-CONDITION-UNKNOWN", "Condition",
                              f"condition {body['Condition']} cannot be decided")
            if rtype in ("AWS::Serverless::Function", "AWS::Serverless::StateMachine") and isinstance(raw_props, dict):
                for api in _implicit_apis(raw_props):
                    implicit[api] = _stronger(implicit.get(api, False), enabled)
            entry: dict = {"address": address, "type": rtype, "file": self.file, "enabled": enabled}
            if logical_id in self.multiplicity:
                entry["multiplicity"] = self.multiplicity[logical_id]
            if self.stack_address is not None:
                entry["via"] = "nested_stack"
            if rtype == "AWS::CloudFormation::Stack" and self.child(logical_id) is None:
                entry["via"] = "module_blackbox"
            if rtype == "AWS::Serverless::Application":
                entry["via"] = "module_blackbox"
            self.current = address
            props = self.eval(raw_props, "Properties")
            if props is NO_VALUE or not isinstance(props, dict):
                props = {}
            entry["props"] = _collect_active(props, "Properties", address, ctx.refs)
            for key in OUTSIDE_PROPS:
                if key in body:
                    _collect_active(self.eval(body[key], key), key, address, ctx.refs)
            depends = body.get("DependsOn") or []
            for dep in [depends] if isinstance(depends, str) else depends:
                if dep in self.resources:
                    ctx.refs.append({"from": address, "path": "DependsOn", "to": self.addr(dep), "attr": None,
                                     "fn": "DependsOn", "state": "active"})
                else:
                    self.diag("warn", "CFN-UNDEFINED-REF", "DependsOn", f"DependsOn to undefined resource {dep}")
            ctx.resources.append(entry)
        # SAM が暗黙に作る API（7.2 の implicit）。Globals.Api／Globals.HttpApi も当てる（SAM と同じ）
        sections = {"AWS::Serverless::Api": "Api", "AWS::Serverless::HttpApi": "HttpApi"}
        for (logical_id, rtype), api_enabled in sorted(implicit.items(), key=lambda kv: kv[0]):
            if logical_id in self.resources:
                continue
            address = self.addr(logical_id)
            self.current = address
            g = globals_.get(sections[rtype])
            props = self.eval(g, "Properties") if isinstance(g, dict) else {}
            if props is NO_VALUE or not isinstance(props, dict):
                props = {}
            entry = {"address": address, "type": rtype, "file": self.file, "enabled": api_enabled,
                     "props": _collect_active(props, "Properties", address, ctx.refs), "implicit": True}
            if self.stack_address is not None:
                entry["via"] = "nested_stack"
            ctx.resources.append(entry)
        ctx.active_files.pop()


def _implicit_apis(props: dict) -> set[tuple[str, str]]:
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


def _cdk_artifacts(asm_dir: Path, depth: int = 0) -> list[tuple[str, str, Path, Path]]:
    """クラウドアセンブリのスタックを (stackName, artifact の ID, テンプレート, アセンブリのフォルダ) で返す。

    CDK の Stage は入れ子のアセンブリ（type: cdk:cloud-assembly、properties.directoryName）なので、再帰で読む。
    """
    if depth > 10:
        raise ValueError("cdk.out の入れ子のアセンブリが深すぎます")
    manifest = json.loads((asm_dir / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for artifact_id, art in (manifest.get("artifacts") or {}).items():
        if not isinstance(art, dict):
            continue
        props = art.get("properties") or {}
        if art.get("type") == "cdk:cloud-assembly" and isinstance(props.get("directoryName"), str):
            sub = asm_dir / props["directoryName"]
            if (sub / "manifest.json").is_file():
                out += _cdk_artifacts(sub, depth + 1)
            continue
        if art.get("type") != "aws:cloudformation:stack" or not isinstance(props.get("templateFile"), str):
            continue
        out.append((props.get("stackName") or artifact_id, artifact_id, asm_dir / props["templateFile"], asm_dir))
    return out


def _cdk_stacks(cdk_dir: Path, diagnostics: list[dict]) -> list[tuple[str, Path, Path, str]]:
    """cdk.out のスタックを (address の接頭辞に使う名前, テンプレート, アセンブリのフォルダ, stackName) で返す。

    名前は stackName。同じ stackName が2つ以上あるとき（別の環境・リージョンに同じ名前で置く）は artifact の ID を使う。
    """
    arts = _cdk_artifacts(cdk_dir)
    if not arts:
        raise ValueError("cdk.out にスタックがありません")
    counts: dict[str, int] = {}
    for name, _, _, _ in arts:
        counts[name] = counts.get(name, 0) + 1
    out = []
    for name, artifact_id, template, asm_dir in arts:
        stack_name = name
        if counts[name] > 1:
            diagnostics.append({"level": "info", "code": "CFN-CDK-STACKNAME-DUPLICATE", "address": "", "path": "",
                                "message": f"stack name {name} is used more than once; artifact id {artifact_id} is used"})
            name = artifact_id
        if not STACK_NAME.fullmatch(name):
            raise ValueError(f"cdk.out のスタック名が使えない形: {name}")
        out.append((name, template, asm_dir, stack_name))
    names = [n for n, _, _, _ in out]
    if len(set(names)) != len(names):
        raise ValueError(f"cdk.out のスタックの名前が重なっています: {sorted(n for n in set(names) if names.count(n) > 1)}")
    return sorted(out)


def build_raw(input_path: Path, root_base: Path | None = None, parameters: dict | None = None) -> dict:
    """テンプレート1つ（ネストスタックを含む）か、cdk.out（ディレクトリか manifest.json）から raw IR を作る。

    parameters: 外から渡すパラメータの値（--param、--param-file）。最上位のスタックに渡す。
    AWS:: で始まる名前（AWS::Region など）は、条件の評価にだけ使う（props は $pseudo のまま）。
    """
    parameters = dict(parameters or {})
    pseudo = {k: v for k, v in parameters.items() if k.startswith("AWS::")}
    given = {k: v for k, v in parameters.items() if not k.startswith("AWS::")}
    if input_path.is_dir() or input_path.name == "manifest.json":
        cdk_dir = input_path if input_path.is_dir() else input_path.parent
        ctx = Context(cdk_dir)
        ctx.pseudo_values = pseudo
        # Export の名前の AWS::StackName は、address に使う名前ではなく本当の stackName で解く
        tops = [StackEval(ctx, load_template(p), p, prefix=f"{name}::", asset_dir=asm, stack_name=real, given=given)
                for name, p, asm, real in _cdk_stacks(cdk_dir, ctx.diagnostics)]
        root_path = cdk_dir
    else:
        ctx = Context(input_path.parent)
        ctx.pseudo_values = pseudo
        tops = [StackEval(ctx, load_template(input_path), input_path, given=given)]
        root_path = input_path
    unused = sorted(set(given) - {k for s in tops for k in s.parameters})
    for k in unused:
        ctx.diagnostics.append({"level": "info", "code": "CFN-PARAM-UNUSED", "address": "", "path": "",
                                "message": f"parameter {k} is given but not defined in the template"})
    for s in tops:
        s.register_exports()
    # 子のスタックの Export も使えるように、最上位のリソースを読む前に子をすべて展開する
    for s in tops:
        ctx.active_files.append(s.path.resolve())
        for logical_id in list(s.resources):
            if s.is_stack(logical_id):
                s.child(logical_id)
        ctx.active_files.pop()
    for s in tops:
        s.run()
    conditions = {}
    for s in ctx.stacks:
        for name in s.conditions:
            s.current = s.where()
            conditions[s.prefix + str(name)] = s.condition(name, f"Conditions.{name}")
    refs = _dedupe(ctx.refs + [r for s in ctx.stacks for r in s.extra_refs])
    root_base = root_base or Path.cwd()
    try:
        root = Path(os.path.relpath(root_path.resolve(), root_base.resolve())).as_posix()
    except ValueError:  # Windows でドライブが違うと相対パスにできない
        root = root_path.resolve().as_posix()
        ctx.diagnostics.append({"level": "info", "code": "CFN-ABSOLUTE-ROOT", "address": "", "path": "",
                                "message": "root is on another drive; written as an absolute path"})
    # 同じ診断（同じ場所・同じ内容）は1つにまとめる
    diagnostics = list({(d.get("address", ""), d.get("path", ""), d["code"], d["message"]): d
                        for d in ctx.diagnostics}.values())
    used = {}
    for s in ctx.stacks:
        for k, v in s.param_values.items():
            used[s.prefix + k] = _strip_internal(v)
    raw = {
        "ir_version": "1.0",
        "stage": "raw",
        "format": "cfn",
        "root": root,
        "evaluation": {"parameters": dict(sorted(used.items())), "conditions": dict(sorted(conditions.items())),
                       "assumptions": ctx.assumptions},
        "resources": ctx.resources,
        "references": refs,
        "diagnostics": diagnostics,
    }
    return ir_raw.canonical_raw(raw)


def load_parameter_file(path: Path) -> dict:
    """パラメータの値のファイルを読む。次の3つの形を受け付ける:
    - aws cloudformation の CLI の形: [{"ParameterKey": "K", "ParameterValue": "V"}, ...]
    - CodePipeline などの形: {"Parameters": {"K": "V"}}
    - {"K": "V"}
    """
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(doc, list):
        # ParameterValue の無い行（UsePreviousValue: true）は読まない
        return {str(x["ParameterKey"]): x["ParameterValue"] for x in doc
                if isinstance(x, dict) and "ParameterKey" in x and x.get("ParameterValue") is not None}
    if isinstance(doc, dict) and isinstance(doc.get("Parameters"), dict):
        return {str(k): v for k, v in doc["Parameters"].items()}
    if isinstance(doc, dict):
        return {str(k): v for k, v in doc.items()}
    raise ValueError(f"パラメータのファイルの形が分かりません: {path}")


def _foreach_subst(value, ident: str, item: str):
    """Fn::ForEach の識別子を値に置き換える（${Id} と &{Id}（英数字だけ）と、Ref Id）。"""
    alnum = re.sub(r"[^A-Za-z0-9]", "", item)
    if isinstance(value, str):
        return value.replace("${" + ident + "}", item).replace("&{" + ident + "}", alnum)
    if isinstance(value, list):
        return [_foreach_subst(v, ident, item) for v in value]
    if isinstance(value, dict):
        if value == {"Ref": ident}:
            return item
        return {_foreach_subst(k, ident, item): _foreach_subst(v, ident, item) for k, v in value.items()}
    return value


def dump(raw: dict) -> str:
    return json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="CloudFormation のテンプレートから raw IR を作る")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--root-base", type=Path, default=None)
    ap.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                    help="パラメータの値（何回でも指定できる。AWS::Region などは条件の評価にだけ使う）")
    ap.add_argument("--param-file", type=Path, action="append", default=[],
                    help="パラメータの値のファイル（CLI の parameters.json の形、{\"Parameters\": {...}}、{キー: 値}）")
    a = ap.parse_args(argv)
    try:
        params: dict = {}
        for f in a.param_file:
            params.update(load_parameter_file(f))
        for kv in a.param:
            if "=" not in kv:
                print(f"--param は KEY=VALUE の形で指定してください: {kv}", file=sys.stderr)
                return 2
            k, v = kv.split("=", 1)
            params[k] = v
        raw = build_raw(a.input, a.root_base, params)
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
