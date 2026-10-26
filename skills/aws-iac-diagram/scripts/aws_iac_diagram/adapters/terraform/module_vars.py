"""変数・local・output の値: tfvars・--var・plan の variables を重ねた変数の値、type への変換、sensitive の扱い、子のモジュールの変数と出力。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import hcl2
from lark import Tree

from aws_iac_diagram.adapters.terraform.evaluator import values as V
from aws_iac_diagram.adapters.terraform.evaluator.values import EvalError, Unknown, ZeroColl
from aws_iac_diagram.adapters.terraform.hcl import (
    NOTCONST, const, fix_heredocs, identifier_name, name_of, parse_expr, sig, unwrap,
)
from aws_iac_diagram.adapters.terraform.model import ModObj
from aws_iac_diagram.adapters.terraform.refs import prepend_through, through_refs


COMPLEX_TYPES = {"list", "set", "map", "object", "tuple"}


class VariablesMixin:
    """ModuleEval の変数・local・output の値。状態は ModuleEval の __init__ が持つ。"""

    # --- 変数
    def setup_variables(self, sources: list, redact=()) -> None:
        """変数の値を決める。sources は Terraform の読み順に並べた ("file", Path) と ("var", "K=V")。

        redact: 値を伏せる変数の名前（--redact-var）。sensitive = true と同じく、値を使わない。
        """
        given: dict = {}
        origin: dict = {}  # 変数の名前 → 値を取ったところ（変数のファイルの名前か "--var"）
        self.redact = set(redact)
        for name in sorted(self.redact - set(self.variables)):
            self.diag("warn", "TF-VAR-UNDECLARED", "", f"--redact-var: variable {name} is not declared", "")
        for kind, item in sources:
            if kind == "file":
                shown = self.var_file_name(item)
                self.var_files.append(shown)
                for name, value in self.read_var_file(item, shown).items():
                    if name not in self.variables:
                        self.diag("warn", "TF-VAR-UNDECLARED", "", f"{shown}: variable {name} is not declared", "")
                        continue
                    given[name], origin[name] = value, shown
            elif kind in ("value", "plan"):  # build_raw の vars と、plan JSON の variables（値をそのまま渡す）
                name, value = item
                if name not in self.variables:
                    self.diag("warn", "TF-VAR-UNDECLARED", "", f"variable {name} is not declared", "")
                    continue
                given[name], origin[name] = value, "--var" if kind == "value" else "plan"
            else:
                name, text = item.split("=", 1)
                name = name.strip()
                if name not in self.variables:
                    self.diag("warn", "TF-VAR-UNDECLARED", "", f"--var: variable {name} is not declared", "")
                    continue
                value = self.parse_cli_var(name, text)
                if value is not NOTCONST:
                    given[name], origin[name] = value, "--var"
        for name, body in sorted(self.variables.items()):
            attrs = self.body_attrs(body)
            spec = self.parse_type(attrs["type"]) if "type" in attrs else None
            secret = next((k for k in ("sensitive", "ephemeral") if k in attrs and const(attrs[k]) is True), None)
            if secret is None and name in self.redact:
                secret = "redact-var"
            nullable = const(attrs["nullable"]) if "nullable" in attrs else True
            value = given.get(name, NOTCONST)
            source = origin.get(name)
            if (value is NOTCONST or (value is None and nullable is False)) and "default" in attrs:
                value = self.eval_const(attrs["default"])
                source = "default"
                if value is NOTCONST:
                    source = None
                    self.diag("warn", "TF-VAR-INVALID", "", f"variable {name}: default is not a constant value", "")
            entry: dict = {"source": source if value is not NOTCONST else None}
            if secret:
                entry["hidden"] = secret
            self.var_sources[name] = entry
            if secret:  # 秘密の値として扱うと書かれた（または --redact-var で伏せた）変数の値は使わない（IR に書かない）
                why = "redacted by --redact-var" if secret == "redact-var" else secret
                self.var_values[name] = Unknown(f"variable {name} is {why}; its value is not used",
                                                "TF-SENSITIVE-VAR", "info")
                continue
            if value is NOTCONST:
                self.var_values[name] = Unknown(f"variable {name} has no value", "TF-UNRESOLVED-VAR")
                continue
            self.var_values[name] = V.convert(value, spec)

    def var_file_name(self, path: Path) -> str:
        """evaluation.var_files に書く名前（root からの相対パス。別のドライブならファイル名だけ）。"""
        try:
            return Path(os.path.relpath(Path(path).resolve(), Path(self.ctx.root_dir).resolve())).as_posix()
        except ValueError:  # Windows でドライブが違う（絶対パスにはユーザー名などが入りうるので書かない）
            self.diag("info", "TF-VARFILE-OTHER-DRIVE", "",
                      f"{Path(path).name}: the var file is on another drive; only the file name is written", "")
            return Path(path).name

    def read_var_file(self, path: Path, rel: str) -> dict:
        if path.name.endswith(".json"):
            try:
                doc = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, ValueError) as e:
                raise ValueError(f"変数のファイルを読めません: {path}: {e}") from e
            if not isinstance(doc, dict):
                raise ValueError(f"変数のファイルがオブジェクトではありません: {path}")
            return doc
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as e:
            raise ValueError(f"変数のファイルを読めません: {path}: {e}") from e
        try:
            tree = hcl2.parses_to_tree(fix_heredocs(text)[0])
        except Exception as e:  # noqa: BLE001
            # lark の文には値の一部（字句）が入るので、位置だけを書く（秘密の値を出さない）
            where = f"line {e.line}, column {e.column}" if getattr(e, "line", None) else type(e).__name__
            raise ValueError(f"変数のファイルを読めません: {path}: 構文の誤り（{where}）") from e
        out = {}
        for name, expr in self.body_attrs(sig(tree)[0]).items():
            v = self.eval_const(expr)
            if v is NOTCONST:
                self.diag("warn", "TF-VAR-INVALID", "", f"{rel}: the value of {name} is not a constant value", "")
                continue
            out[name] = v
        return out

    def parse_cli_var(self, name: str, text: str):
        """--var の値。type が複合の型（list・map・object など）なら HCL の式として読む。"""
        attrs = self.body_attrs(self.variables[name])
        spec = self.parse_type(attrs["type"]) if "type" in attrs else None
        if spec is not None and spec[0] in COMPLEX_TYPES:
            tree = parse_expr(text)
            v = self.eval_const(tree) if tree is not None else NOTCONST
            if v is NOTCONST:
                self.diag("warn", "TF-VAR-INVALID", "", f"--var: the value of {name} is not a valid expression", "")
            return v
        return text

    def eval_const(self, expr):
        """参照を使わない式（tfvars、default）の値。決まらなければ NOTCONST。"""
        saved, self.const_mode = self.const_mode, True
        try:
            v = self.eval(expr, {})
        except EvalError:
            return NOTCONST
        finally:
            self.const_mode = saved
        return v if V.is_concrete(v) else NOTCONST

    def parse_type(self, t):
        """variable の type の式を、evaluator/values.py の convert の形にする。読めなければ None（変換しない）。"""
        t = unwrap(t)
        if isinstance(t, Tree) and t.data == "identifier":
            n = name_of(t)
            return (n,) if n in ("string", "number", "bool", "any") else None
        if not (isinstance(t, Tree) and t.data == "function_call"):
            return None
        cs = sig(t)
        n = name_of(cs[0])
        args_t = next((c for c in cs if isinstance(c, Tree) and c.data == "arguments"), None)
        args = [c for c in sig(args_t) if isinstance(c, Tree)] if args_t is not None else []
        if n in ("list", "set", "map") and len(args) == 1:
            return (n, self.parse_type(args[0]))
        if n == "tuple" and len(args) == 1 and isinstance(unwrap(args[0]), Tree) and unwrap(args[0]).data == "tuple":
            return ("tuple", [self.parse_type(x) for x in sig(unwrap(args[0]))])
        if n == "object" and len(args) == 1 and isinstance(unwrap(args[0]), Tree) and unwrap(args[0]).data == "object":
            attrs = {}
            for el in sig(unwrap(args[0])):
                ecs = sig(el)
                key = self.object_key_name(ecs[0])
                if not isinstance(key, str):
                    return None
                at = unwrap(ecs[-1])
                if isinstance(at, Tree) and at.data == "function_call" and name_of(sig(at)[0]) == "optional":
                    oargs_t = next((c for c in sig(at) if isinstance(c, Tree) and c.data == "arguments"), None)
                    oargs = [c for c in sig(oargs_t) if isinstance(c, Tree)] if oargs_t is not None else []
                    default = self.eval_const(oargs[1]) if len(oargs) > 1 else V.NODEFAULT
                    if default is NOTCONST:
                        default = V.NODEFAULT
                    attrs[key] = (self.parse_type(oargs[0]) if oargs else None, True, default)
                else:
                    attrs[key] = (self.parse_type(at), False, V.NODEFAULT)
            return ("object", attrs)
        return None

    @staticmethod
    def object_key_name(t):
        c = sig(t)[0]
        if isinstance(c, Tree) and c.data == "keyword":
            return name_of(c)
        n = identifier_name(c)
        if n is not None:
            return n
        v = const(c)
        return v if isinstance(v, str) else NOTCONST

    def var_value(self, name):
        if name not in self.variables:
            return Unknown(f"reference to undefined var.{name}", "TF-UNDEFINED-REF")
        if self.parent is not None:
            return self.child_var(name)
        return self.var_values.get(name, Unknown(f"variable {name} has no value", "TF-UNRESOLVED-VAR"))

    # --- 子のモジュールの変数と出力
    def setup_child(self) -> None:
        """子のモジュールの、呼び出しの引数と変数の突き合わせ（値は使うときに評価する）。"""
        undeclared = sorted(set(self.call_args) - set(self.variables))
        if self.via == "module_summary":
            plain = {u for u in self.summary.uncovered if "." not in u}
            self._uncovered = sorted(set(undeclared) | (set(self.call_args) & plain))
            if self.parent is not None and self.parent.via is None:
                s = self.summary
                self.diag("info", "TF-MODULE-SUMMARY", "",
                          f"expanded from the summary table ({s.source}, {'/'.join(f'{m}.x' for m in s.majors)}; "
                          "references/module-summaries.md); only the main resources are written",
                          self.call_address)
            return
        for name in undeclared:
            self.diag("warn", "TF-VAR-UNDECLARED", name,
                      f"variable {name} is not declared in the module {self.call_address}", self.call_address)
        for name, body in sorted(self.variables.items()):
            attrs = self.body_attrs(body)
            entry: dict = {"source": "argument" if name in self.call_args else "default" if "default" in attrs
                           else None}
            secret = next((k for k in ("sensitive", "ephemeral") if k in attrs and const(attrs[k]) is True), None)
            if secret:
                entry["hidden"] = secret
            self.var_sources[name] = entry

    def child_var(self, name):
        """子のモジュールの変数の値。呼び出しの引数を親の中で評価し、type に合わせて変換する（through に var を足す）。"""
        if name in self._var_cache:
            v, pruned = self._var_cache[name]
            self.sink |= pruned
            return v
        key = ("var", name)
        if key in self._busy:
            return Unknown(f"var.{name} of {self.call_address} refers to itself", "TF-CYCLE")
        self._busy.add(key)
        try:
            attrs = self.body_attrs(self.variables[name])
            spec = self.parse_type(attrs["type"]) if "type" in attrs else None
            secret = next((k for k in ("sensitive", "ephemeral") if k in attrs and const(attrs[k]) is True), None)
            nullable = const(attrs["nullable"]) if "nullable" in attrs else True
            pruned: set = set()
            v = NOTCONST
            if name in self.call_args:
                p = self.parent
                saved, p.sink = p.sink, set()
                saved_try, p.try_depth = p.try_depth, 0
                try:
                    v = p.eval_safe(self.call_args[name], self.call_env)
                finally:
                    pruned, p.sink = p.sink, saved
                    p.try_depth = saved_try
                if v is None and nullable is False:
                    v = NOTCONST
            if v is NOTCONST and "default" in attrs:
                v = self.eval_const(attrs["default"])
                if v is NOTCONST:
                    v = Unknown(f"variable {name} of {self.call_address}: default is not a constant value",
                                "TF-VAR-INVALID")
            if v is NOTCONST:
                v = Unknown(f"variable {name} of {self.call_address} has no value (not set by the module call)",
                            "TF-UNRESOLVED-VAR")
            if secret:  # 秘密の値として扱うと書かれた変数の値は使わない（中の参照は残す）
                v = Unknown(f"variable {name} of {self.call_address} is {secret}; its value is not used",
                            "TF-SENSITIVE-VAR", "info", V.refs_in(v))
            elif not isinstance(v, Unknown):
                v = V.convert(v, spec)
            hop = f"{self.prefix}var.{name}"
            v, pruned = prepend_through(v, hop), frozenset(through_refs(pruned, hop))
        finally:
            self._busy.discard(key)
        self._var_cache[name] = (v, pruned)
        self.sink |= pruned
        return v

    def output_value(self, name: str):
        """子のモジュールの出力の値と、値に残らなかった参照（pruned）。through に output を足す。"""
        if name in self._out_cache:
            return self._out_cache[name]
        hop = f"{self.prefix}output.{name}"
        body = self.outputs.get(name)
        if body is None:
            if self.via == "module_summary":
                u = Unknown(f"output {name} of {self.call_address} is not in the summary table",
                            "TF-MODULE-SUMMARY-OUTPUT")
            else:
                u = Unknown(f"reference to undefined output {name} of {self.call_address}", "TF-UNDEFINED-REF")
            return u, frozenset()
        key = ("output", name)
        if key in self._busy:
            return Unknown(f"output {name} of {self.call_address} refers to itself", "TF-CYCLE"), frozenset()
        attrs = self.body_attrs(body)
        self._busy.add(key)
        saved, self.sink = self.sink, set()
        saved_try, self.try_depth = self.try_depth, 0
        try:
            v = self.eval_safe(attrs["value"], {}) if "value" in attrs else \
                Unknown(f"output {name} of {self.call_address} has no value", "TF-MALFORMED-BLOCK")
        finally:
            pruned, self.sink = self.sink, saved
            self.try_depth = saved_try
            self._busy.discard(key)
        secret = next((k for k in ("sensitive", "ephemeral") if k in attrs and const(attrs[k]) is True), None)
        if secret:  # sensitive の出力の値は使わない（中の参照は unevaluated で残す）
            v = Unknown(f"output {name} of {self.call_address} is {secret}; its value is not used",
                        "TF-SENSITIVE-VAR", "info", V.refs_in(v))
        out = (prepend_through(v, hop), frozenset(through_refs(pruned, hop)))
        self._out_cache[name] = out
        return out

    def module_output(self, obj: ModObj, name: str):
        v, pruned = obj.child.output_value(name)
        self.sink |= pruned
        return v

    def resolve_mods(self, v):
        """値の中に残ったモジュールの呼び出し（module.x そのもの）を、出力の値のオブジェクトにする。"""
        if isinstance(v, ModObj):
            return {n: self.resolve_mods(self.module_output(v, n)) for n in sorted(v.child.outputs)}
        if isinstance(v, ZeroColl):
            return v
        if isinstance(v, list) and any(isinstance(e, (ModObj, list, dict)) for e in v):
            return type(v)(self.resolve_mods(e) for e in v)
        if isinstance(v, dict) and any(isinstance(e, (ModObj, list, dict)) for e in v.values()):
            return type(v)((k, self.resolve_mods(e)) for k, e in v.items())
        return v

    # --- locals と count・for_each
    def local_value(self, name):
        if name in self._local_cache:
            v, pruned = self._local_cache[name]
            self.sink |= pruned
            return v
        if name not in self.locals:
            return Unknown(f"reference to undefined local.{name}", "TF-UNDEFINED-REF")
        key = ("local", name)
        if key in self._busy:
            return Unknown(f"local.{name} refers to itself", "TF-CYCLE")
        self._busy.add(key)
        saved, self.sink = self.sink, set()
        saved_try, self.try_depth = self.try_depth, 0
        try:
            v = self.eval_safe(self.locals[name], {})
        finally:
            pruned, self.sink = self.sink, saved
            self.try_depth = saved_try
            self._busy.discard(key)
        self._local_cache[name] = (v, frozenset(pruned))
        self.sink |= pruned
        return v
