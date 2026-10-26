"""1つのスタックの評価 StackEval: リソースを 1 つずつ評価して Context に入れる（SAM の Globals と暗黙の API を含む）。"""
from __future__ import annotations

from pathlib import Path

from aws_iac_diagram.adapters.cloudformation.conditions import stronger, weaker
from aws_iac_diagram.adapters.cloudformation.evaluator import Evaluator
from aws_iac_diagram.adapters.cloudformation.loader import bool_name
from aws_iac_diagram.adapters.cloudformation.model import NO_VALUE, OUTSIDE_PROPS, Context
from aws_iac_diagram.adapters.cloudformation.nested import NestedMixin
from aws_iac_diagram.adapters.cloudformation.outputs import OutputsMixin
from aws_iac_diagram.adapters.cloudformation.refs import collect_active
from aws_iac_diagram.adapters.cloudformation.sam import GLOBALS, implicit_apis, merge_globals


class StackEval(NestedMixin, OutputsMixin, Evaluator):
    """1つのスタック（テンプレート）を評価する。子のスタックは、出力を使うときか、スタックのリソースを読むときに展開する。

    ネストスタックは NestedMixin、Outputs・Export は OutputsMixin。継承の順は NestedMixin・OutputsMixin が Evaluator の前
    （Evaluator の stack_output・import_value を上書きするため）。
    """

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
        self.resources = self.expand_foreach(self.resources)
        if isinstance(self.template.get("Outputs"), dict):
            self.template = {**self.template, "Outputs": self.expand_foreach(self.template["Outputs"], record=False)}
        ctx.stacks.append(self)

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
                    raw_props = merge_globals(globals_[section], raw_props)
            enabled = self.enabled  # 親のスタックの enabled を引き継ぐ
            if "Condition" in body:
                c = self.condition(body["Condition"], "Condition")
                enabled = weaker(enabled, c)
                if c is None and bool_name(body["Condition"], self.conditions) in self.conditions:
                    self.diag("info", "CFN-CONDITION-UNKNOWN", "Condition",
                              f"condition {body['Condition']} cannot be decided")
            if rtype in ("AWS::Serverless::Function", "AWS::Serverless::StateMachine") and isinstance(raw_props, dict):
                for api in implicit_apis(raw_props):
                    implicit[api] = stronger(implicit.get(api, False), enabled)
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
            entry["props"] = collect_active(props, "Properties", address, ctx.refs)
            for key in OUTSIDE_PROPS:
                if key in body:
                    collect_active(self.eval(body[key], key), key, address, ctx.refs)
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
                     "props": collect_active(props, "Properties", address, ctx.refs), "implicit": True}
            if self.stack_address is not None:
                entry["via"] = "nested_stack"
            ctx.resources.append(entry)
        ctx.active_files.pop()
