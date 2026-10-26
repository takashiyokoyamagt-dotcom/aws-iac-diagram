"""評価した値を raw IR の props（印 $res・$unknown など）にし、ブロックの本体（属性と入れ子のブロック、dynamic）を props にする。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from lark import Tree

from aws_iac_diagram.adapters.terraform.evaluator import functions as E
from aws_iac_diagram.adapters.terraform.evaluator.functions import Az, Concat, Json, Pseudo, Res, Unknown
from aws_iac_diagram.adapters.terraform.hcl import identifier_name, label_text, name_of, sig
from aws_iac_diagram.adapters.terraform.refs import ref_order
from aws_iac_diagram.core import ir_raw

if TYPE_CHECKING:
    from aws_iac_diagram.adapters.terraform.module_eval import ModuleEval


# 作られないブロックの中で info に下げる code（値が決まらないことによるもの。参照の誤り・循環は下げない）
UNDECIDED = {"TF-UNRESOLVED-VAR", "TF-EVAL-ERROR", "TF-UNEVALUATED", "TF-UNSUPPORTED-FUNCTION"}


class PropertiesMixin:
    """ModuleEval の値 → props。状態は ModuleEval の __init__ が持つ。"""

    # --- 書き出し（印への変換）
    def materialize(self, v, path: str):
        """評価した値を raw IR の値にする。Unknown は $unknown にし、中の参照を unevaluated で残して診断を書く。"""
        if isinstance(v, Unknown):
            for to, attr, through in sorted(v.refs, key=ref_order):
                self.add_ref(path, to, attr, "unevaluated", through)
            reason = v.reason or "the value is not known"
            # 作られないリソース（count が 0 など）は Terraform も評価しないので、図に影響しない（info にする）
            level = "info" if self.current_enabled is False and v.level == "warn" and v.code in UNDECIDED else v.level
            self.diag(level, v.code, path, reason)
            return {"$unknown": reason}
        if isinstance(v, Res):  # through は一時的な __through で運び、emit で references に移す
            return {"$res": v.to, "attr": v.attr, **({"__through": list(v.through)} if v.through else {})}
        if isinstance(v, Pseudo):
            return {"$pseudo": v.name}
        if isinstance(v, Az):
            return {"$az": v.index}
        if isinstance(v, Concat):
            parts = [p if isinstance(p, str) else self.materialize(p, path) for p in v.parts]
            return ir_raw.maybe_json(ir_raw.normalize_concat(parts))
        if isinstance(v, Json):
            inner = self.materialize(v.value, path)
            return inner if isinstance(inner, dict) and "$unknown" in inner else {"$json": inner}
        if isinstance(v, str):
            return ir_raw.maybe_json(v)
        if isinstance(v, float):
            return E.norm_number(v)
        if isinstance(v, list):
            return [self.materialize(e, ir_raw.join_path(path, i)) for i, e in enumerate(v)]
        if isinstance(v, dict):
            return {("$" + k if k.startswith("$") else k): self.materialize(e, ir_raw.join_path(path, k))
                    for k, e in v.items()}
        return v

    def value_at(self, expr, path: str, env: dict):
        """属性1つを評価して書き出す。値に残らなかった参照は、この位置に pruned で残す。"""
        saved, self.sink = self.sink, set()
        try:
            v = self.eval_safe(expr, env)
            out = self.materialize(v, path)
        finally:
            pruned, self.sink = self.sink, saved
        for to, attr, through in sorted(pruned, key=ref_order):
            self.add_ref(path, to, attr, "pruned", through)
        return v, out

    def body_props(self, body: Tree, path: str, env: dict, meta: set = frozenset()) -> dict:
        """属性とブロックを props にする。ブロックは同じ名前のものをリストにする（plan JSON と同じ形）。"""
        out: dict = {}
        for item in sig(body):
            if not isinstance(item, Tree):
                continue
            if item.data == "attribute":
                cs = sig(item)
                name = name_of(cs[0])
                if name in meta:
                    continue
                v, m = self.value_at(cs[-1], ir_raw.join_path(path, name), env)
                if v is not None:  # null は書かないのと同じ
                    out[name] = m
            elif item.data == "block":
                cs = sig(item)
                btype = name_of(cs[0])
                if btype in meta:
                    continue
                if btype == "dynamic" and len(cs) >= 3:
                    self.dynamic_block(label_text(cs[1]), cs[-1], path, env, out)
                    continue
                lst = out.setdefault(btype, [])
                if not isinstance(lst, list):
                    self.diag("warn", "TF-MALFORMED-BLOCK", ir_raw.join_path(path, btype),
                              f"block {btype} has the same name as an attribute")
                    continue
                lst.append(self.body_props(cs[-1], ir_raw.join_path(ir_raw.join_path(path, btype), len(lst)), env))
        return out

    def dynamic_block(self, label: str, body: Tree, path: str, env: dict, out: dict) -> None:
        """dynamic ブロックを展開する。for_each が決まらなければ、$unknown の要素1つ（中の参照は unevaluated）。"""
        lst = out.setdefault(label, [])
        if not isinstance(lst, list):
            self.diag("warn", "TF-MALFORMED-BLOCK", ir_raw.join_path(path, label),
                      f"block {label} has the same name as an attribute")
            return
        attrs = self.body_attrs(body)
        content = next((sig(b)[-1] for b in sig(body) if isinstance(b, Tree) and b.data == "block"
                        and name_of(sig(b)[0]) == "content"), None)
        iterator = identifier_name(attrs["iterator"]) if "iterator" in attrs else label
        block_path = ir_raw.join_path(path, label)
        if "for_each" not in attrs or content is None:
            self.diag("warn", "TF-MALFORMED-BLOCK", block_path, f"dynamic block {label} has no for_each or content")
            return
        saved, self.sink = self.sink, set()
        try:
            fe = self.eval_safe(attrs["for_each"], env)
        finally:
            pruned, self.sink = self.sink, saved
        items = self.iter_items(fe)
        if items is None:
            if fe is None:
                return
            p = ir_raw.join_path(block_path, len(lst))
            u = E.unknown_from(fe, f"for_each of dynamic block {label} is not known before apply",
                               extra_refs=self.static_refs(content))
            lst.append(self.materialize(u, p))
            return
        for to, attr, through in sorted(pruned, key=ref_order):
            self.add_ref(block_path, to, attr, "pruned", through)
        for k, v in items:
            env2 = dict(env)
            env2[iterator or label] = {"key": k, "value": v}
            lst.append(self.body_props(content, ir_raw.join_path(block_path, len(lst)), env2))
