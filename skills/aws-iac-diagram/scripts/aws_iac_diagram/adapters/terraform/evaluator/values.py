"""Terraform の式の評価に使う値の型（Res・Pseudo・Az・Concat・Json・Unknown・ZeroColl）と、値の道具（変換・比較・数の扱い）。

評価の中では、値を次の形で持つ（raw IR の印に直すのは module_props.py の materialize）:
  - ふつうの値: str・int・float・bool・None・list・dict（キーは入力のまま。$$ の逃がしは書き出すときに行う）
  - Res: リソース・data・module への参照（$res）。multi=True は count・for_each が決まらない ×N のまとまり（[*]）。
    through はモジュールの出力・変数をたどった経路（references の through。from の側から順に）
  - Pseudo・Az: 擬似パラメータと AZ（$pseudo・$az）。Az("*") は data.aws_availability_zones の names 全体
  - Concat・Json: 文字列のテンプレートと jsonencode（$concat・$json）
  - Unknown: 評価できなかった値（$unknown）。中にあった参照（refs）を持ち歩き、書き出すときに unevaluated で残す
  - ZeroColl: count が 0・for_each が空のリソースのまとまり（空のリスト。添字で引くと作られないリソースへの Res）
組み込み関数は functions.py。ir-schema.md の 7.2。
"""
from __future__ import annotations

import decimal
import json
import re
from dataclasses import dataclass


class EvalError(Exception):
    """Terraform なら評価の誤りになるもの（try・can で受ける）。"""


@dataclass(frozen=True)
class Res:
    to: str
    attr: str | None = None
    multi: bool = False  # count・for_each が決まらない ×N のまとまり（to は [*] で終わる）
    through: tuple = ()  # モジュールの出力・変数をたどった経路（module.x.output.y・module.x.var.y。7.3）


@dataclass(frozen=True)
class Pseudo:
    name: str


@dataclass(frozen=True)
class Az:
    index: int | str  # 0 始まりの番号か "*"（names 全体）


@dataclass(frozen=True)
class Concat:
    parts: tuple  # str と、Res・Pseudo・Az・Unknown


@dataclass
class Json:
    value: object


class Unknown:
    """評価できなかった値。reason は $unknown の文、code・level は診断、refs は中にあった参照 (to, attr, through)。"""

    __slots__ = ("reason", "code", "level", "refs")

    def __init__(self, reason: str, code: str = "TF-UNEVALUATED", level: str = "warn", refs=frozenset()):
        self.reason = reason
        self.code = code
        self.level = level
        self.refs = frozenset(refs)

    def __repr__(self) -> str:
        return f"Unknown({self.reason!r}, {self.code}, refs={sorted(self.refs, key=str)})"


class ZeroColl(list):
    """count が 0（for_each が空）のリソース。値は空のリストだが、添字で引くと作られないリソースへの Res になる。"""

    def __init__(self, res: Res):
        super().__init__()
        self.res = res


MARKER_TYPES = (Res, Pseudo, Az, Concat, Json, Unknown)


# ------------------------------------------------------------------ 値の道具

def refs_in(v) -> set:
    """値の中の参照 (to, attr, through)。Unknown は持ち歩いている参照。"""
    out: set = set()

    def walk(x):
        if isinstance(x, Res):
            out.add((x.to, x.attr, x.through))
        elif isinstance(x, Unknown):
            out.update(x.refs)
        elif isinstance(x, Concat):
            for p in x.parts:
                walk(p)
        elif isinstance(x, Json):
            walk(x.value)
        elif isinstance(x, list):
            for e in x:
                walk(e)
        elif isinstance(x, dict):
            for e in x.values():
                walk(e)

    walk(v)
    return out


def is_concrete(v) -> bool:
    """印を含まない、ふつうの値か。"""
    if isinstance(v, MARKER_TYPES):
        return False
    if isinstance(v, list):
        return all(is_concrete(e) for e in v)
    if isinstance(v, dict):
        return all(is_concrete(e) for e in v.values())
    return True


def first_unknown(v) -> Unknown | None:
    if isinstance(v, Unknown):
        return v
    if isinstance(v, Concat):
        return next((p for p in v.parts if isinstance(p, Unknown)), None)
    if isinstance(v, Json):
        return first_unknown(v.value)
    if isinstance(v, list):
        for e in v:
            u = first_unknown(e)
            if u is not None:
                return u
    if isinstance(v, dict):
        for e in v.values():
            u = first_unknown(e)
            if u is not None:
                return u
    return None


def unknown_from(values, reason: str, code: str = "TF-UNEVALUATED", level: str = "warn", extra_refs=()) -> Unknown:
    """values を使って評価できなかったときの Unknown。values の中に Unknown があれば、その理由を引き継ぐ。"""
    u = first_unknown(values)
    refs = refs_in(values) | set(extra_refs)
    if u is not None:
        return Unknown(u.reason, u.code, u.level, refs)
    return Unknown(reason, code, level, refs)


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def arith(op: str, x, y):
    """数の演算（+ - * / %）。Terraform の数は10進で正確なので（0.1 + 0.2 は 0.3）、Decimal で計算する。"""
    dx, dy = decimal.Decimal(repr(x)), decimal.Decimal(repr(y))
    with decimal.localcontext() as c:
        c.prec = 34
        if op in ("/", "%") and dy == 0:
            raise EvalError("division by zero")
        d = {"+": dx + dy, "-": dx - dy, "*": dx * dy, "/": dx / dy if op == "/" else None,
             "%": dx % dy if op == "%" else None}[op]  # Decimal の % は、符号を割られる数に合わせる（Go と同じ）
    if d == d.to_integral_value() and abs(d) < 2 ** 53:
        return int(d)
    return float(d)


def norm_number(v):
    """整数になる float は int にする（Terraform の数は1つの型）。"""
    if isinstance(v, float) and v.is_integer() and abs(v) < 2 ** 53:
        return int(v)
    return v


def fmt_number(v) -> str:
    v = norm_number(v)
    if isinstance(v, int):
        return str(v)
    s = repr(v)
    return s


def same(a, b) -> bool:
    """Terraform の == （型を区別する。true と 1 は違う）。どちらもふつうの値のときだけ使う。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if is_number(a) and is_number(b):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if type(a) is not type(b) and not (a is None or b is None):
        return False
    return a == b


def to_number(v):
    """数への変換（Terraform の自動変換。"1" → 1）。変換できなければ EvalError。"""
    if is_number(v):
        return v
    if isinstance(v, str):
        try:
            return norm_number(int(v)) if re.fullmatch(r"-?\d+", v.strip()) else norm_number(float(v))
        except ValueError:
            pass
    raise EvalError(f"a number is required, got {type_name(v)}")


def to_string(v):
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if is_number(v):
        return fmt_number(v)
    raise EvalError(f"a string is required, got {type_name(v)}")


def to_bool(v):
    if isinstance(v, bool):
        return v
    if v in ("true", "false"):
        return v == "true"
    raise EvalError(f"a bool is required, got {type_name(v)}")


def to_int(v) -> int:
    n = to_number(v)
    if isinstance(n, float):
        if not n.is_integer():
            raise EvalError(f"an integer is required, got {n}")
        n = int(n)
    return n


def type_name(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if is_number(v):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return "unknown value"


def sorted_keys(d: dict) -> list:
    return sorted(d)


def dedupe(items: list) -> list:
    out: list = []
    for x in items:
        if not any(same(x, y) if is_concrete(x) and is_concrete(y) else x == y for y in out):
            out.append(x)
    return out


def to_set(items: list) -> list:
    """集合（重なりを除き、文字列・数だけなら並べる。Terraform の set の順）。"""
    out = dedupe(items)
    if out and all(isinstance(x, str) for x in out):
        return sorted(out)
    if out and all(is_number(x) for x in out):
        return sorted(out)
    return out


# ------------------------------------------------------------------ テンプレートの部品

def template_part(v):
    """テンプレートの中に入れる値（文字列か、$concat の要素になれる印）。入れられなければ Unknown。"""
    if isinstance(v, (Res, Pseudo, Unknown)):
        return v
    if isinstance(v, Az):
        return v if v.index != "*" else unknown_from(v, "a list in a string template is not evaluated")
    if isinstance(v, Concat):
        return v
    if v is None:
        return Unknown("null in a string template", "TF-EVAL-ERROR")
    if isinstance(v, (str, bool)) or is_number(v):
        return to_string(v)
    return unknown_from(v, "a list, an object or a JSON value in a string template is not evaluated")


def concat_parts(parts: list):
    """部品をつないだ値（文字列だけなら文字列、印が1つだけならその印）。"""
    flat: list = []
    for p in parts:
        items = p.parts if isinstance(p, Concat) else (p,)
        for it in items:
            if it == "":
                continue
            if isinstance(it, str) and flat and isinstance(flat[-1], str):
                flat[-1] += it
            else:
                flat.append(it)
    if all(isinstance(p, str) for p in flat):
        return "".join(flat)
    if len(flat) == 1:
        return flat[0]
    return Concat(tuple(flat))


# ------------------------------------------------------------------ 型の変換（variable の type）

def convert(v, spec):
    """variable の type に合わせて値を変換する（できなければ元の値のまま）。spec は module_vars.py の parse_type の形。"""
    if spec is None or v is None or isinstance(v, MARKER_TYPES):
        return v
    kind = spec[0]
    try:
        if kind == "string":
            return to_string(v) if isinstance(v, (str, bool, int, float)) else v
        if kind == "number":
            return to_number(v) if isinstance(v, (str, int, float)) and not isinstance(v, bool) else v
        if kind == "bool":
            return to_bool(v) if isinstance(v, (str, bool)) else v
    except EvalError:
        return v
    if kind in ("list", "set") and isinstance(v, list):
        items = [convert(e, spec[1]) for e in v]
        return to_set(items) if kind == "set" else items
    if kind == "map" and isinstance(v, dict):
        return {k: convert(e, spec[1]) for k, e in v.items()}
    if kind == "tuple" and isinstance(v, list) and len(v) == len(spec[1]):
        return [convert(e, t) for e, t in zip(v, spec[1])]
    if kind == "object" and isinstance(v, dict):
        out = {}
        for name, (t, optional, default) in spec[1].items():
            if name in v and v[name] is not None:
                out[name] = convert(v[name], t)
            elif optional and default is not NODEFAULT:
                out[name] = convert(default, t)
            else:
                out[name] = None
        return out
    return v


NODEFAULT = object()


# ------------------------------------------------------------------ format() の本体

FORMAT_VERB = re.compile(r"%(?:\[(\d+)\])?([-+# 0]*)(\d+)?(?:\.(\d+))?([a-zA-Z%])")


def format_string(fmt: str, args: list):
    """format() の本体。%s・%v に印を渡したときは、つないだ値（Concat）を返す。"""
    parts: list = []
    pos = 0
    argi = 0
    for m in FORMAT_VERB.finditer(fmt):
        parts.append(fmt[pos:m.start()])
        pos = m.end()
        explicit, flags, width, prec, verb = m.groups()
        if verb == "%":
            parts.append("%")
            continue
        if explicit:
            argi = int(explicit) - 1
        if argi >= len(args):
            raise EvalError("format(): not enough arguments")
        a = args[argi]
        argi += 1
        if isinstance(a, MARKER_TYPES):
            if verb in ("s", "v") and not width:
                parts.append(template_part(a))
                continue
            return unknown_from(args, "format() of a value that is not known before apply")
        if verb in ("s", "v") and isinstance(a, (str, bool, int, float)):
            text = to_string(a)
        elif verb == "v":
            text = "null" if a is None else json.dumps(a, ensure_ascii=False, separators=(",", ":"))
        elif verb == "s":
            raise EvalError(f"format(): %s of {type_name(a)}")
        elif verb == "q":
            text = json.dumps(to_string(a), ensure_ascii=False)
        elif verb == "d":
            text = str(to_int(a))
        elif verb in ("f", "e", "g"):
            text = ("%" + (f".{prec}" if prec else "") + verb) % float(to_number(a))
        elif verb == "t":
            text = "true" if to_bool(a) else "false"
        elif verb in ("x", "X", "o", "b"):
            n = to_int(a)
            text = {"x": "%x", "X": "%X", "o": "%o"}.get(verb, "{:b}")
            text = text % n if verb != "b" else format(n, "b")
        else:
            raise EvalError(f"format(): unsupported verb %{verb}")
        if width:
            w = int(width)
            if "-" in flags:
                text = text.ljust(w)
            elif "0" in flags and verb in ("d", "f", "e", "g", "x", "X", "o", "b"):
                text = text.rjust(w, "0")
            else:
                text = text.rjust(w)
        parts.append(text)
    parts.append(fmt[pos:])
    return concat_parts(parts)
