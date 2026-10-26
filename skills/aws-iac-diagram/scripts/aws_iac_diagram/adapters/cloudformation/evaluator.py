"""1つのテンプレートの評価の入れ物 Evaluator（診断・参照・eval の入口）。関数ごとの評価はミックスイン。"""
from __future__ import annotations

import json

from aws_iac_diagram.adapters.cloudformation.conditions import ConditionsMixin
from aws_iac_diagram.adapters.cloudformation.foreach import ForEachMixin
from aws_iac_diagram.adapters.cloudformation.intrinsics import IntrinsicsMixin
from aws_iac_diagram.adapters.cloudformation.model import CONDITION_FNS, NO_VALUE, UNEVALUATED
from aws_iac_diagram.adapters.cloudformation.params import ParametersMixin
from aws_iac_diagram.adapters.cloudformation.refs import static_refs
from aws_iac_diagram.core import ir_raw


class Evaluator(ParametersMixin, ConditionsMixin, IntrinsicsMixin, ForEachMixin):
    """1つのテンプレートの組み込み関数を評価する。参照は、印に一時的な "__fn" を付けて運び、最後に references にする。

    関数ごとの評価は 4 つのミックスイン（params・conditions・intrinsics・foreach）にある。ミックスインは状態を持たない
    （属性はすべてこの __init__ に書く）。ここには入れ物の状態、診断、評価の入口（eval）と、StackEval が上書きする 2 つの手がかりを置く。
    """

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
        self.multiplicity: dict[str, str] = {}  # ×N で出すリソース・出力の名前 → "N"（Fn::ForEach の集まりが決まらないとき）

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
        for to, attr, fn in static_refs(value, set(self.resources)):
            self.extra_refs.append({"from": self.current, "path": path, "to": self.addr(to), "attr": attr, "fn": fn,
                                    "state": state})

    def unknown(self, value, path: str, reason: str, code: str = "CFN-UNEVALUATED"):
        self.scan_refs(value, path, "unevaluated")
        self.diag("warn", code, path, reason)
        return {"$unknown": reason}

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
                return ir_raw.maybe_json(node)
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

    def where(self) -> str:
        """このスタックの出力などの診断に使う address（最上位なら空）。"""
        return self.stack_address or self.prefix.rstrip(":/")
