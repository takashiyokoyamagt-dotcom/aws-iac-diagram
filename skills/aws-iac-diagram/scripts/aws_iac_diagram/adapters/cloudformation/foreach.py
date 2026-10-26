"""Fn::ForEach（AWS::LanguageExtensions）の展開。"""
from __future__ import annotations

import re


def foreach_subst(value, ident: str, item: str):
    """Fn::ForEach の識別子を値に置き換える（${Id} と &{Id}（英数字だけ）と、Ref Id）。"""
    alnum = re.sub(r"[^A-Za-z0-9]", "", item)
    if isinstance(value, str):
        return value.replace("${" + ident + "}", item).replace("&{" + ident + "}", alnum)
    if isinstance(value, list):
        return [foreach_subst(v, ident, item) for v in value]
    if isinstance(value, dict):
        if value == {"Ref": ident}:
            return item
        return {foreach_subst(k, ident, item): foreach_subst(v, ident, item) for k, v in value.items()}
    return value

class ForEachMixin:
    """Fn::ForEach（AWS::LanguageExtensions）の展開。プロパティの中のものと、Resources・Outputs のもの。

    状態は持たない（multiplicity は Evaluator.__init__ に書いてある）。
    """

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
                        out[foreach_subst(tk, ident, str(x))] = foreach_subst(tv, ident, str(x))
            else:
                self.unknown(templates, path, f"{k}: the collection cannot be decided", "CFN-FOREACH-UNRESOLVED")
        return out

    def expand_foreach(self, resources: dict, depth: int = 0, record: bool = True) -> dict:
        """Resources（と Outputs）の Fn::ForEach::<名前> を展開する。値が決まらなければ ×N（docs/spec/ir-schema/ の 2章）。

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
                        out_key = foreach_subst(tkey, ident, str(v))
                        expanded = self.expand_foreach({out_key: foreach_subst(tbody, ident, str(v))}, depth + 1, record)
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
                    put(name, foreach_subst(tbody, ident, "*"))
                    if record:
                        self.multiplicity[name] = "N"
        return out
