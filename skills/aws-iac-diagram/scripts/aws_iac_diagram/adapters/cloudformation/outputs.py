"""スタックの Outputs と Export・ImportValue（cdk.out のスタックどうしの受け渡しにも使う）。"""
from __future__ import annotations

from aws_iac_diagram.adapters.cloudformation.marks import prepend_through, set_fn


class OutputsMixin:
    """スタックの Outputs の評価と、Export・ImportValue。状態（outputs・output_extras）は StackEval.__init__ に書いてある。"""

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
        return set_fn(prepend_through(value, f"Export:{name}"), "ImportValue")
