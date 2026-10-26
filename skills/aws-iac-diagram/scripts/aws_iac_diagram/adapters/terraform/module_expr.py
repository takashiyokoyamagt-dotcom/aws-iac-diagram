"""式の評価（定数、参照、演算、条件式、for 式、組み込み関数の呼び出し、テンプレート、添字・属性・スプラット）と、
評価しなかった式の中の参照の集め方（unevaluated・pruned）。値の型と関数の本体は evaluator/ にある。
"""
from __future__ import annotations

from dataclasses import replace

from lark import Token, Tree

from aws_iac_diagram.adapters.terraform.addresses import block_address, inst_address
from aws_iac_diagram.adapters.terraform.evaluator import values as V
from aws_iac_diagram.adapters.terraform.evaluator import functions as F
from aws_iac_diagram.adapters.terraform.evaluator.values import (
    Az, Concat, EvalError, Json, Pseudo, Res, Unknown, ZeroColl,
)
from aws_iac_diagram.adapters.terraform.hcl import (
    HEREDOC, TRAVERSAL, apply_strip, build_template, const, flatten, heredoc_body, identifier_name,
    name_of, sig, string_tokens, text_tokens, token_trees, unescape, unwrap,
)
from aws_iac_diagram.adapters.terraform.model import ModObj, ResList
from aws_iac_diagram.adapters.terraform.refs import through_refs


# 引数や要素から選ぶ関数（選ばなかったものの中の参照を pruned にする。CFN の Fn::Select と同じ）
SELECTING = {"coalesce", "coalescelist", "element", "slice", "one"}
# data.<型>.<名前>.<属性> → 擬似パラメータ（7.2。CFN と同じ名前）。引数の無い data だけ
PSEUDO_DATA = {
    ("aws_region", "name"): "AWS::Region", ("aws_region", "region"): "AWS::Region", ("aws_region", "id"): "AWS::Region",
    ("aws_caller_identity", "account_id"): "AWS::AccountId",
    ("aws_partition", "partition"): "AWS::Partition", ("aws_partition", "id"): "AWS::Partition",
    ("aws_partition", "dns_suffix"): "AWS::URLSuffix",
}


class ExpressionMixin:
    """ModuleEval の式の評価。状態は ModuleEval の __init__ が持つ。"""

    # --- 評価
    def eval_safe(self, t, env: dict):
        """eval の誤り（EvalError）を、評価できなかった値（Unknown）にする。"""
        try:
            return self.eval(t, env)
        except EvalError as e:
            return Unknown(str(e) or "evaluation error", "TF-EVAL-ERROR", "warn", self.static_refs(t))
        except RecursionError:
            return Unknown("the expression is too deeply nested", "TF-UNEVALUATED", "warn", self.static_refs(t))

    def spec_refs(self, trees, env: dict) -> set:
        """評価で使わなかった式（条件式の選ばれなかった側など）の中の参照。評価してみて、だめなら式から探す。"""
        trees = trees if isinstance(trees, list) else [trees]
        saved, self.sink = self.sink, set()
        out: set = set()
        try:
            for t in trees:
                try:
                    out |= V.refs_in(self.eval(t, env))
                except (EvalError, RecursionError):
                    out |= set(self.static_refs(t))
            out |= self.sink
        finally:
            self.sink = saved
        return out

    def lose(self, before, after) -> None:
        """評価で値に残らなかった参照を pruned にする。"""
        if isinstance(after, Unknown):
            return
        self.prune(V.refs_in(before), after)

    def prune(self, refs: set, after) -> None:
        """refs のうち、after に同じリソースへの参照が無いものを pruned にする（属性が違うだけなら捨てていない）。"""
        kept = {block_address(r[0]) for r in V.refs_in(after)}
        self.sink |= {r for r in refs if block_address(r[0]) not in kept}

    def eval(self, t, env: dict):
        t = unwrap(t)
        if not isinstance(t, Tree):
            raise EvalError(f"unexpected token {getattr(t, 'type', t)}")
        d = t.data
        if d in ("int_lit", "float_lit", "literal_value"):
            return const(t)
        if d == "string":
            return self.template(string_tokens(t), env)
        if d in HEREDOC:
            return self.template(text_tokens(heredoc_body(str(t.children[0]))), env)
        if d == "template_string":  # %{…} の中の \"…\"
            return unescape(str(t.children[0])[2:-2])
        if d == "tuple":
            return [self.eval(c, env) for c in sig(t)]
        if d == "object":
            return self.object(t, env)
        if d == "function_call":
            return self.call(t, env)
        if d in TRAVERSAL or d == "identifier":
            return self.reference(t, env)
        if d == "unary_op":
            return self.unary(t, env)
        if d == "binary_op":
            return self.binary(t, env)
        if d == "conditional":
            return self.conditional(t, env)
        if d in ("for_tuple_expr", "for_object_expr"):
            return self.for_expr(t, env)
        return Unknown(f"{d} is not supported", "TF-UNEVALUATED", "warn", self.static_refs(t))

    # テンプレート
    def template(self, tokens: list, env: dict):
        """"${…}" と heredoc。${…} が1つだけなら、その値のまま（HCL と同じ）。"""
        trees = token_trees(tokens)
        bad = any(not isinstance(tok, str) and (tok[0] == "bad" or None in tok) for tok in tokens)
        try:
            nodes = None if bad else build_template(apply_strip(tokens))
        except ValueError:
            nodes = None
        if nodes is None:
            return Unknown("a template cannot be parsed", "TF-UNEVALUATED", "warn",
                           set().union(*[self.static_refs(x) for x in trees]) if trees else set())
        if len(tokens) == 1 and not isinstance(tokens[0], str) and tokens[0][0] == "expr":
            return self.eval(tokens[0][1], env)
        return V.concat_parts(self.template_nodes(nodes, env))

    def template_nodes(self, nodes: list, env: dict) -> list:
        parts: list = []
        for n in nodes:
            if isinstance(n, str):
                parts.append(n)
            elif n[0] == "expr":
                parts.append(V.template_part(self.eval(n[1], env)))
            elif n[0] == "if":
                c = self.eval(n[1], env)
                if isinstance(c, bool) or c in ("true", "false"):
                    chosen, other = (n[2], n[3]) if V.to_bool(c) else (n[3], n[2])
                    got = self.template_nodes(chosen, env)
                    self.prune(self.spec_node_refs(other, env), got)
                    parts += got
                else:
                    parts.append(V.unknown_from(c, "%{if} with a condition that is not known before apply",
                                                extra_refs=self.spec_node_refs(n[2] + n[3], env)))
            else:  # for
                names, coll = n[1], self.eval(n[2], env)
                items = self.iter_items(coll)
                if items is None:
                    parts.append(V.unknown_from(coll, "%{for} over a value that is not known before apply",
                                                extra_refs=self.spec_node_refs(n[3], env)))
                    continue
                for k, v in items:
                    env2 = dict(env)
                    if len(names) == 2:
                        env2[names[0]], env2[names[1]] = k, v
                    else:
                        env2[names[0]] = v
                    parts += self.template_nodes(n[3], env2)
        return parts

    def spec_node_refs(self, nodes: list, env: dict) -> set:
        saved, self.sink = self.sink, set()
        try:
            try:
                out = V.refs_in(self.template_nodes(nodes, env))
            except (EvalError, RecursionError):
                out = set()
                for t in self.node_trees(nodes):
                    out |= set(self.static_refs(t))
            return out | self.sink
        finally:
            self.sink = saved

    def node_trees(self, nodes: list) -> list:
        out = []
        for n in nodes:
            if isinstance(n, str):
                continue
            if n[0] == "expr":
                out.append(n[1])
            elif n[0] == "if":
                out += [n[1]] + self.node_trees(n[2]) + self.node_trees(n[3])
            else:
                out += [n[2]] + self.node_trees(n[3])
        return out

    @staticmethod
    def iter_items(coll):
        """for 式・%{for}・dynamic で回す (キー, 値) の並び。回せない値なら None。"""
        if isinstance(coll, dict):
            return [(k, coll[k]) for k in sorted(coll)]
        if isinstance(coll, list):
            return list(enumerate(coll))
        return None

    # 演算と条件式
    def unary(self, t: Tree, env: dict):
        op = str(t.children[0]).strip()
        v = self.eval(t.children[-1], env)
        if not V.is_concrete(v):
            return V.unknown_from(v, f"operator {op} on a value that is not known before apply")
        if op == "-":
            return V.norm_number(-V.to_number(v))
        return not V.to_bool(v)

    def binary(self, t: Tree, env: dict):
        cs = sig(t)
        term = sig(cs[1])
        op = name_of(term[0])
        a = self.eval(cs[0], env)
        b = self.eval(term[1], env)
        if op in ("&&", "||"):
            for x in (a, b):  # 片方で決まるときは決める（false && …、true || …）
                if isinstance(x, bool) and x == (op == "||"):
                    return x
        if op in ("==", "!=") and (a is None) != (b is None):
            # null との比較は、もう一方が null になりえない値（マップ・リスト・文字列のテンプレート・擬似パラメータ・AZ）
            # なら、中に決まらない値があっても決まる（リソースの属性 $res と $unknown は null かもしれない）
            other = b if a is None else a
            whole = isinstance(other, Res) and other.attr is None  # リソース・モジュールの呼び出しそのもの
            if isinstance(other, (dict, list, Concat, Json, Pseudo, Az, ModObj)) or whole or V.is_concrete(other):
                return op == "!="
        if not (V.is_concrete(a) and V.is_concrete(b)):
            return V.unknown_from([a, b], f"operator {op} on a value that is not known before apply")
        if op == "==":
            return V.same(a, b)
        if op == "!=":
            return not V.same(a, b)
        if op == "&&":
            return V.to_bool(a) and V.to_bool(b)
        if op == "||":
            return V.to_bool(a) or V.to_bool(b)
        x, y = V.to_number(a), V.to_number(b)
        if op in ("+", "-", "*", "/", "%"):
            return V.arith(op, x, y)
        if op == "<":
            return x < y
        if op == ">":
            return x > y
        if op == "<=":
            return x <= y
        if op == ">=":
            return x >= y
        raise EvalError(f"unknown operator {op}")

    def conditional(self, t: Tree, env: dict):
        cond_t, a_t, b_t = sig(t)[:3]
        c = self.eval(cond_t, env)
        if isinstance(c, bool) or c in ("true", "false"):
            chosen, other = (a_t, b_t) if V.to_bool(c) else (b_t, a_t)
            v = self.eval(chosen, env)
            self.prune(self.spec_refs(other, env), v)
            return v
        if V.is_concrete(c):
            raise EvalError(f"the condition is {V.type_name(c)}, not bool")
        return V.unknown_from(c, "the condition is not known before apply", extra_refs=self.spec_refs([a_t, b_t], env))

    def for_expr(self, t: Tree, env: dict):
        intro = next(c for c in t.children if isinstance(c, Tree) and c.data == "for_intro")
        names = [name_of(c) for c in intro.children if isinstance(c, Tree) and c.data == "identifier"]
        coll_t = next(c for c in intro.children if isinstance(c, Tree) and c.data not in ("identifier",
                                                                                         "new_line_or_comment"))
        cond_t = next((sig(c)[-1] for c in t.children if isinstance(c, Tree) and c.data == "for_cond"), None)
        body = [c for c in t.children if isinstance(c, Tree) and c.data not in ("for_intro", "for_cond",
                                                                                 "new_line_or_comment")]
        grouping = any(isinstance(c, Token) and c.type == "ELLIPSIS" for c in t.children)
        is_obj = t.data == "for_object_expr"
        coll = self.eval(coll_t, env)
        items = self.iter_items(coll)
        rest = body + ([cond_t] if cond_t is not None else [])
        if items is None:
            if coll is None:
                raise EvalError("for expression over null")
            return V.unknown_from(coll, "for expression over a value that is not known before apply",
                                  extra_refs=self.spec_refs_static(rest))
        out_list: list = []
        out_map: dict = {}
        excluded: set = set()  # if で除いた要素の参照（pruned）
        for k, v in items:
            env2 = dict(env)
            if len(names) == 2:
                env2[names[0]], env2[names[1]] = k, v
            else:
                env2[names[0]] = v
            if cond_t is not None:
                c = self.eval(cond_t, env2)
                if not (isinstance(c, bool) or c in ("true", "false")):
                    if V.is_concrete(c):
                        raise EvalError("the for condition is not bool")
                    return V.unknown_from([coll, c], "the for condition is not known before apply",
                                          extra_refs=self.spec_refs_static(rest))
                if not V.to_bool(c):
                    excluded |= V.refs_in(v) | (V.refs_in(k) if len(names) == 2 else set())
                    continue
            if is_obj:
                key = self.eval(body[0], env2)
                if isinstance(key, bool) or V.is_number(key):
                    key = V.to_string(key)
                if not isinstance(key, str):
                    if V.is_concrete(key):
                        raise EvalError("the key of a for expression must be a string")
                    return V.unknown_from([coll, key], "the key of a for expression is not known before apply",
                                          extra_refs=self.spec_refs_static(rest))
                val = self.eval(body[1], env2)
                if grouping:
                    out_map.setdefault(key, []).append(val)
                elif key in out_map:
                    raise EvalError(f"duplicate key {key!r} in a for expression")
                else:
                    out_map[key] = val
            else:
                out_list.append(self.eval(body[0], env2))
        result = out_map if is_obj else out_list
        self.prune(excluded, result)
        return result

    def spec_refs_static(self, trees: list) -> set:
        out: set = set()
        for t in trees:
            out |= set(self.static_refs(t))
        return out

    def object(self, t: Tree, env: dict):
        out: dict = {}
        unknown_key = None
        for el in sig(t):
            cs = sig(el)
            key_t = cs[0]
            c = sig(key_t)[0]
            if isinstance(c, Tree) and c.data == "keyword":
                key = name_of(c)
            elif (n := identifier_name(c)) is not None:
                key = n
            else:
                key = self.eval(c, env)
                if isinstance(key, bool) or V.is_number(key):
                    key = V.to_string(key)
            val = self.eval(cs[-1], env)
            if not isinstance(key, str):
                unknown_key = unknown_key or (key, val)
                out[f"\u0000{len(out)}"] = [key, val]  # 決まらないキー（下で Unknown にする）
                continue
            out[key] = val
        if unknown_key is not None:
            if V.is_concrete(unknown_key[0]):
                raise EvalError("an object key must be a string")
            return V.unknown_from(list(out.values()), "an object key is not known before apply")
        return out

    def call(self, t: Tree, env: dict):
        cs = sig(t)
        name = "::".join(name_of(c) for c in cs if isinstance(c, Tree) and c.data == "identifier")
        args_t = next((c for c in cs if isinstance(c, Tree) and c.data == "arguments"), None)
        arg_trees = [c for c in sig(args_t) if isinstance(c, Tree)] if args_t is not None else []
        expand = args_t is not None and any(isinstance(c, Token) and c.type == "ELLIPSIS" for c in args_t.children)
        if name == "try":
            return self.call_try(arg_trees, env)
        if name == "can":
            return self.call_can(arg_trees, env)
        args = [self.eval(a, env) for a in arg_trees]
        if expand and args:
            last = args[-1]
            if not isinstance(last, list):
                return V.unknown_from(args, f"{name}(...) with an argument that is not known before apply")
            args = args[:-1] + list(last)
        result = F.call_function(name, args)
        if name in SELECTING:
            self.lose(args, result)
        return result

    def call_try(self, arg_trees: list, env: dict):
        failed: set = set()  # 誤りになった式の中の参照（値に残らないので pruned）
        for i, a in enumerate(arg_trees):
            saved, self.sink = self.sink, set()
            self.try_depth += 1
            try:
                v = self.eval(a, env)
            except EvalError:
                self.sink = saved
                failed |= self.static_refs(a)
                continue
            finally:
                self.try_depth -= 1
            sub, self.sink = self.sink, saved
            self.sink |= sub
            rest = self.spec_refs(arg_trees[i + 1:], env) if i + 1 < len(arg_trees) else set()
            if isinstance(v, Unknown):
                return Unknown(v.reason, v.code, v.level, v.refs | rest | failed)
            self.prune(rest | failed, v)
            return v
        raise EvalError("try(): no expression succeeded")

    def call_can(self, arg_trees: list, env: dict):
        if len(arg_trees) != 1:
            raise EvalError("can() takes one argument")
        self.try_depth += 1
        try:
            v = self.eval(arg_trees[0], env)
        except EvalError:
            return False
        finally:
            self.try_depth -= 1
        if not V.is_concrete(v):  # 値の全体が決まらなければ、誤りになるかも決まらない（Terraform と同じ）
            return V.unknown_from(v, "can() of a value that is not known before apply")
        return True

    # 参照
    def reference(self, t: Tree, env: dict):
        root, steps = flatten(t)
        if not (isinstance(root, Tree) and root.data == "identifier"):
            return self.traverse(self.eval(root, env), steps, env)
        name = name_of(root)
        if name in env:
            return self.traverse(env[name], steps, env)
        first = steps[0][1] if steps and steps[0][0] == "attr" else None
        if self.const_mode:
            raise EvalError(f"a reference ({name}) is not allowed here")
        if name == "var":
            return self.traverse(self.var_value(first), steps[1:], env)
        if name == "local":
            return self.traverse(self.local_value(first), steps[1:], env)
        if name in ("count", "each"):
            return Unknown(f"{name}.{first} is used outside a block with {'count' if name == 'count' else 'for_each'}",
                           "TF-UNDEFINED-REF")
        if name == "self":
            return Unknown("self is only known in provisioners and connections", "TF-UNEVALUATED", "info")
        if name == "path":
            if first == "module" and self.dir is None:
                return Unknown("path.module of a module expanded from the summary table", "TF-UNEVALUATED", "info")
            if first in ("module", "root", "cwd"):
                return self.ctx.rel(self.dir) if first == "module" else "."
            return Unknown(f"path.{first} is not supported", "TF-UNEVALUATED")
        if name == "terraform":
            if first == "workspace":
                self.ctx.assume(f'terraform.workspace is evaluated as "{self.ctx.workspace}"'
                                + (" (--workspace)" if self.ctx.workspace != "default" else ""))
                return self.ctx.workspace
            return Unknown(f"terraform.{first} is not supported", "TF-UNEVALUATED")
        if name == "ephemeral":
            base = f"ephemeral.{first}.{steps[1][1] if len(steps) > 1 and steps[1][0] == 'attr' else ''}"
            blk = self.ephemerals.get(base)
            if blk is None:
                return Unknown(f"reference to undefined {base}", "TF-UNDEFINED-REF")
            return Unknown(f"{base} is an ephemeral value; it is not known", "TF-EPHEMERAL", "info",
                           self.static_refs(blk.body))
        if name == "data":
            base, rest = f"data.{first}.{steps[1][1] if len(steps) > 1 and steps[1][0] == 'attr' else ''}", steps[2:]
        elif name == "module":
            base, rest = f"module.{first}", steps[1:]
        else:
            base, rest = f"{name}.{first}", steps[1:]
        blk = self.blocks.get(base) if first else None
        if blk is None:
            return Unknown(f"reference to undefined {base if first else name}", "TF-UNDEFINED-REF")
        if blk.kind == "data" and "provider" not in blk.attrs and self.instances(blk).mode == "single":
            a = rest[0][1] if rest and rest[0][0] == "attr" else None
            if blk.plain and (blk.type, a) in PSEUDO_DATA:
                return self.traverse(Pseudo(PSEUDO_DATA[(blk.type, a)]), rest[1:], env)
            # AZ は state などの引数があってもよい（別のリージョンを指す provider だけ除く）
            if blk.type == "aws_availability_zones" and a == "names":
                return self.traverse(Az("*"), rest[1:], env)
            # 別の state の出力（terraform_remote_state）は読まない。attr は outputs.<出力の名前>（7.2）
            if blk.type == "terraform_remote_state" and a == "outputs" and len(rest) > 1:
                st = rest[1]
                out = st[1] if st[0] == "attr" else const(st[1]) if st[0] == "index" and isinstance(st[1], Tree) \
                    else None
                if isinstance(out, str):
                    return self.traverse(Res(self.prefix + blk.base, f"outputs.{out}"), rest[2:], env)
        if blk.kind == "module" and self.expanded(blk):
            return self.resolve_mods(self.traverse(self.block_value(blk), rest, env))
        if blk.kind == "data" and self.via == "module_summary":
            return Unknown(f"{base} in the summary table is not read", "TF-UNEVALUATED", "info")
        return self.traverse(self.block_value(blk), rest, env)

    def traverse(self, v, steps: list, env: dict):
        for st in steps:
            v = self.step(v, st, env)
        return v

    def step(self, v, st, env: dict):
        kind = st[0]
        if isinstance(v, Unknown):
            return v
        if isinstance(v, ModObj):  # 展開したモジュールの呼び出し: 属性は出力
            if kind == "attr":
                return self.module_output(v, st[1])
            if kind == "index":
                if v.child.multi:  # ×N のモジュールは、どの添字でも同じ1つ（Res の [*] と同じ）
                    return v
                key = st[1] if isinstance(st[1], int) else self.eval(st[1], env)
                if isinstance(key, str):
                    return self.module_output(v, key)
                if not V.is_concrete(key):
                    return V.unknown_from(key, "an index that is not known before apply")
                raise EvalError("a module call is not a list")
            return self.traverse(v, st[1], env) if v.child.multi else [self.traverse(v, st[1], env)]
        if kind == "attr":
            name = st[1]
            if isinstance(v, Res):
                return v if v.attr is not None else replace(v, attr=name)
            if isinstance(v, dict):
                if name not in v:
                    raise EvalError(f"unsupported attribute {name!r}")
                return v[name]  # マップ・オブジェクトの引かなかった値の参照は pruned にしない（each.value.x などで多くなる）
            if v is None:
                raise EvalError(f"attribute {name!r} of null")
            if isinstance(v, (Pseudo, Az, Concat, Json)):
                return V.unknown_from(v, f"attribute {name} of a value that is not known before apply")
            raise EvalError(f"attribute {name!r} of a {V.type_name(v)}")
        if kind == "index":
            key = st[1] if isinstance(st[1], int) else self.eval(st[1], env)
            if isinstance(v, Res):
                return replace(v, attr=None, multi=False) if v.multi else v
            if isinstance(v, ZeroColl):
                if self.try_depth:  # try()・can() の中では Terraform と同じく誤り（次の式に進む）
                    raise EvalError("index into a block whose count is 0")
                return v.res
            if isinstance(v, Az) and v.index == "*" and V.is_number(key):
                i = V.to_int(key)
                if i < 0:
                    raise EvalError("negative index")
                return Az(i)
            if not V.is_concrete(key):
                return V.unknown_from([v, key], "an index that is not known before apply")
            if isinstance(v, list):
                if isinstance(key, bool):
                    raise EvalError("a bool cannot be a list index")
                i = V.to_int(key)
                if not (0 <= i < len(v)):
                    raise EvalError(f"index {i} is out of range (length {len(v)})")
                out = v[i]
                if not isinstance(v, ResList):  # リストの選ばなかった要素の参照は pruned（CFN の Fn::Select と同じ）
                    self.lose(v, out)
                return out
            if isinstance(v, dict):
                k = key if isinstance(key, str) else V.to_string(key)
                if k not in v:
                    raise EvalError(f"no key {k!r}")
                return v[k]
            if v is None:
                raise EvalError("index of null")
            if isinstance(v, (Pseudo, Az, Concat, Json)):
                return V.unknown_from([v, key], "an index into a value that is not known before apply")
            raise EvalError(f"index into a {V.type_name(v)}")
        # splat
        sub = st[1]
        if v is None:
            return []
        if isinstance(v, Res):
            if v.multi:  # ×N のまとまりのスプラットは、[*] への1つの $res（7.2）
                return self.traverse(replace(v, attr=None, multi=False), sub, env)
            if v.attr is not None:
                return self.traverse(v, sub, env)
            return [self.traverse(v, sub, env)]
        if isinstance(v, list):
            return [self.traverse(e, sub, env) for e in v]
        if isinstance(v, Az) and v.index == "*":
            return v
        return [self.traverse(v, sub, env)]

    def static_refs(self, node) -> set:
        """式を評価せずに、中のリソース・data・module への参照を探す（local はその式をたどる）。"""
        out: set = set()
        seen: set = set()

        def walk_step(st):
            if st[0] == "index" and isinstance(st[1], Tree):
                walk(st[1])
            elif st[0] == "splat":
                for s in st[1]:
                    walk_step(s)

        def walk(t):
            if isinstance(t, list):
                for x in t:
                    walk(x)
                return
            if not isinstance(t, Tree):
                return
            if t.data in HEREDOC:
                for tree in token_trees(text_tokens(heredoc_body(str(t.children[0])))):
                    walk(tree)
                return
            if t.data == "expr_term" or t.data in TRAVERSAL:
                root, steps = flatten(t)
                if isinstance(root, Tree) and root.data == "identifier":
                    self.static_ref(name_of(root), steps, out, seen, walk)
                    for st in steps:
                        walk_step(st)
                    return
                if root is not t:
                    walk(root)
                    for st in steps:
                        walk_step(st)
                    return
            for c in t.children:
                walk(c)

        walk(node)
        return out

    def static_ref(self, name: str, steps: list, out: set, seen: set, walk) -> None:
        first = steps[0][1] if steps and steps[0][0] == "attr" else None
        if name == "local":
            if first in self.locals and first not in seen:
                seen.add(first)
                walk(self.locals[first])
            return
        if name == "data":
            base, rest = f"data.{first}.{steps[1][1] if len(steps) > 1 and steps[1][0] == 'attr' else ''}", steps[2:]
        elif name == "module":
            base, rest = f"module.{first}", steps[1:]
        else:
            base, rest = f"{name}.{first}", steps[1:]
        blk = self.blocks.get(base) if first else None
        if blk is None:
            return
        if blk.kind == "data" and "provider" not in blk.attrs and self.instances(blk).mode == "single":
            a = rest[0][1] if rest and rest[0][0] == "attr" else None
            if (blk.plain and (blk.type, a) in PSEUDO_DATA) or (blk.type == "aws_availability_zones" and a == "names"):
                return
        if self.expanded(blk):  # 展開するモジュール: 出力の式の中の参照（through に output を足す）
            keys = self.child_keys(blk)
            if rest and rest[0][0] == "index":
                key = rest[0][1] if isinstance(rest[0][1], int) else const(rest[0][1])
                keys = [key] if key in keys else keys
                rest = rest[1:]
            elif rest and rest[0][0] == "splat":
                rest = rest[0][1] + rest[1:]
            name = rest[0][1] if rest and rest[0][0] == "attr" else None
            for k in keys:
                out |= self.child(blk, k).static_output_refs(name)
            return
        addrs = self.all_addresses(blk)
        if rest and rest[0][0] == "index":
            key = rest[0][1] if isinstance(rest[0][1], int) else const(rest[0][1])
            inst = self.instances(blk)
            if inst.mode in ("count", "each") and key in inst.keys:
                addrs = [inst_address(self.prefix + blk.base, key)]
            rest = rest[1:]
        elif rest and rest[0][0] == "splat":
            rest = rest[0][1] + rest[1:]
        attr = rest[0][1] if rest and rest[0][0] == "attr" else None
        for a in addrs:
            out.add((a, attr, ()))

    def static_output_refs(self, name: str | None) -> set:
        """出力（name が None ならすべての出力）の式の中の参照。式を評価せずに探す。"""
        names = [name] if name is not None else sorted(self.outputs)
        out: set = set()
        for n in names:
            body = self.outputs.get(n)
            key = ("static-output", n)
            if body is None or key in self._busy:
                continue
            attrs = self.body_attrs(body)
            if "value" not in attrs:
                continue
            self._busy.add(key)
            try:
                out |= through_refs(self.static_refs(attrs["value"]), f"{self.prefix}output.{n}")
            finally:
                self._busy.discard(key)
        return out
