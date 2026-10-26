"""組み込み関数（Ref・GetAtt・Sub・Join・Select・Split・FindInMap）の評価。"""
from __future__ import annotations

from aws_iac_diagram.adapters.cloudformation.loader import bool_name
from aws_iac_diagram.adapters.cloudformation.marks import res_with_fn, split_concat
from aws_iac_diagram.adapters.cloudformation.model import NO_VALUE, PSEUDO, SUB_VAR
from aws_iac_diagram.core import ir_raw


class IntrinsicsMixin:
    """Ref・Fn::GetAtt・Fn::Sub・Fn::Join・Fn::Select・Fn::Split・Fn::FindInMap と擬似パラメータの評価。

    状態は持たない（Evaluator.__init__ に書いてある）。診断・参照・値の評価（diag・unknown・scan_refs・eval）は Evaluator のもの。
    """

    def pseudo(self, name: str):
        if name == "AWS::StackName" and self.resolve_stack_name and self.stack_name:
            return self.stack_name
        if self.in_condition and name in self.pseudo_values:
            return self.pseudo_values[name]
        return {"$pseudo": name}

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
            name = bool_name(name, list(self.resources) + list(self.parameters))
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
        return ir_raw.maybe_json(value)

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
                    for to, attr, fn in res_with_fn(item):
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
