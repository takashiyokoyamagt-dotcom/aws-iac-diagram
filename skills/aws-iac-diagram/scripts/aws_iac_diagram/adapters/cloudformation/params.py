"""パラメータ: 外から渡す値のファイル（--param-file）と、テンプレートの Parameters の評価。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from aws_iac_diagram.adapters.cloudformation.marks import prepend_through, split_concat


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

class ParametersMixin:
    """テンプレートの Parameters の評価。値は --param・--param-file、親のスタックから渡された値、Default の順に使う。"""

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
            value = prepend_through(value, f"{self.stack_address}.Parameters.{name}")
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
