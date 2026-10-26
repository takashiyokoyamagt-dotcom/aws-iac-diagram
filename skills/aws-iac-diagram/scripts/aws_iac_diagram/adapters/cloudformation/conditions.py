"""Conditions（A4）: 条件関数を 真／偽／決まらない の3つの値で評価する。リソースの enabled の組み合わせ。"""
from __future__ import annotations

from aws_iac_diagram.adapters.cloudformation.loader import bool_name
from aws_iac_diagram.adapters.cloudformation.model import UNKNOWN


def cfn_str(v) -> str:
    """Fn::Equals で比べるときの文字列（CFN は値を文字列として比べる）。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ",".join(cfn_str(x) for x in v)
    return str(v)

def stronger(a, b):
    """enabled の強い方。true > null > false（どれか1つでも作られるなら作られる）。"""
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False

def weaker(a, b):
    """作られるか（enabled）の弱い方。false > null > true（親のスタックの Condition を子に引き継ぐ）。"""
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True

class ConditionsMixin:
    """Conditions（A4）の評価と、リソースの enabled の3値。状態は持たない（Evaluator.__init__ に書いてある）。"""

    def condition(self, name, path: str = ""):
        """名前の付いた条件を評価する。True／False／None（決まらない）。"""
        name = bool_name(name, self.conditions) if isinstance(name, bool) else name
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
            return cfn_str(a) == cfn_str(b)
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
