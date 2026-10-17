"""Terraform の式の評価に使う値の型と、組み込み関数（scripts/adapters/tf.py が使う。ir-schema.md の 7.2）。

評価の中では、値を次の形で持つ（raw IR の印に直すのは tf.py の materialize）:
  - ふつうの値: str・int・float・bool・None・list・dict（キーは入力のまま。$$ の逃がしは書き出すときに行う）
  - Res: リソース・data・module への参照（$res）。multi=True は count・for_each が決まらない ×N のまとまり（[*]）
  - Pseudo・Az: 擬似パラメータと AZ（$pseudo・$az）。Az("*") は data.aws_availability_zones の names 全体
  - Concat・Json: 文字列のテンプレートと jsonencode（$concat・$json）
  - Unknown: 評価できなかった値（$unknown）。中にあった参照（refs）を持ち歩き、書き出すときに unevaluated で残す
  - ZeroColl: count が 0・for_each が空のリソースのまとまり（空のリスト。添字で引くと作られないリソースへの Res）

関数は、値が決まっていれば Terraform と同じ結果を返し、決まらない値（Res・Unknown など）を含むと、
構造だけで決まるもの（length・concat・merge・lookup など）は印を残したまま、それ以外は Unknown を返す。
引数の誤り（範囲外の添字、無いキーなど）は EvalError（try・can で使う）。
"""
from __future__ import annotations

import base64
import decimal
import ipaddress
import json
import math
import posixpath
import re
from dataclasses import dataclass


class EvalError(Exception):
    """Terraform なら評価の誤りになるもの（try・can で受ける）。"""


@dataclass(frozen=True)
class Res:
    to: str
    attr: str | None = None
    multi: bool = False  # count・for_each が決まらない ×N のまとまり（to は [*] で終わる）


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
    """評価できなかった値。reason は $unknown の文、code・level は診断、refs は中にあった参照 (to, attr)。"""

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
    """値の中の参照 (to, attr)。Unknown は持ち歩いている参照。"""
    out: set = set()

    def walk(x):
        if isinstance(x, Res):
            out.add((x.to, x.attr))
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
    """variable の type に合わせて値を変換する（できなければ元の値のまま）。spec は tf.py の parse_type の形。"""
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


# ------------------------------------------------------------------ 組み込み関数

FUNCTIONS: dict = {}
# 構造だけで決まる関数（印をそのまま扱う）。それ以外は、引数がすべてふつうの値のときだけ呼ぶ
STRUCTURAL: set = set()
# ファイル・時刻・乱数・ハッシュなど、評価しない関数（値は Unknown。中の参照は残す）
NOT_EVALUATED = {
    "file", "filebase64", "templatefile", "fileexists", "fileset", "filemd5", "filesha1", "filesha256",
    "filesha512", "filebase64sha256", "filebase64sha512", "abspath", "pathexpand",
    "timestamp", "plantimestamp", "timeadd", "timecmp", "formatdate", "uuid", "uuidv5", "bcrypt",
    "md5", "sha1", "sha256", "sha512", "base64sha256", "base64sha512", "base64gzip", "rsadecrypt",
    "yamlencode", "yamldecode", "csvdecode", "textencodebase64", "textdecodebase64", "templatestring",
}
FILE_FUNCTIONS = {"file", "filebase64", "templatefile", "fileexists", "fileset", "filemd5", "filesha1",
                  "filesha256", "filesha512", "filebase64sha256", "filebase64sha512"}


def fn(name: str, structural: bool = False):
    def deco(f):
        FUNCTIONS[name] = f
        if structural:
            STRUCTURAL.add(name)
        return f
    return deco


def call_function(name: str, args: list):
    """関数を呼ぶ。決まらない値を含むときは、構造だけで決まる関数以外は Unknown。"""
    f = FUNCTIONS.get(name)
    if f is None:
        if name in NOT_EVALUATED:
            reason = (f"{name}() is not evaluated (the file is not read)" if name in FILE_FUNCTIONS
                      else f"{name}() is not evaluated")
            return Unknown(reason, "TF-UNEVALUATED", "warn", refs_in(args))
        return unknown_from(args, f"function {name}() is not supported", "TF-UNSUPPORTED-FUNCTION")
    if name not in STRUCTURAL and not all(is_concrete(a) for a in args):
        return unknown_from(args, f"{name}() of a value that is not known before apply")
    return f(*args)


def _need_list(v, name: str):
    if isinstance(v, (Res, Unknown, Concat, Json, Pseudo)) or (isinstance(v, Az) and v.index == "*"):
        return None
    if not isinstance(v, list):
        raise EvalError(f"{name}(): a list is required, got {type_name(v)}")
    return v


def _need_map(v, name: str):
    if isinstance(v, MARKER_TYPES):
        return None
    if not isinstance(v, dict):
        raise EvalError(f"{name}(): a map is required, got {type_name(v)}")
    return v


# --- 数
@fn("abs")
def _abs(x):
    return norm_number(abs(to_number(x)))


@fn("ceil")
def _ceil(x):
    return math.ceil(to_number(x))


@fn("floor")
def _floor(x):
    return math.floor(to_number(x))


@fn("max")
def _max(*xs):
    if not xs:
        raise EvalError("max(): at least one argument is required")
    return norm_number(max(to_number(x) for x in xs))


@fn("min")
def _min(*xs):
    if not xs:
        raise EvalError("min(): at least one argument is required")
    return norm_number(min(to_number(x) for x in xs))


@fn("pow")
def _pow(a, b):
    return norm_number(float(to_number(a)) ** to_number(b))


@fn("signum")
def _signum(x):
    n = to_number(x)
    return (n > 0) - (n < 0)


@fn("parseint")
def _parseint(s, base):
    try:
        return int(to_string(s), to_int(base))
    except ValueError as e:
        raise EvalError(f"parseint(): {e}") from e


@fn("sum")
def _sum(xs):
    if not isinstance(xs, list) or not xs:
        raise EvalError("sum(): a non-empty list is required")
    return norm_number(sum(to_number(x) for x in xs))


# --- 文字列
@fn("chomp")
def _chomp(s):
    return re.sub(r"(\r\n|\n|\r)+$", "", to_string(s))


@fn("lower")
def _lower(s):
    return to_string(s).lower()


@fn("upper")
def _upper(s):
    return to_string(s).upper()


@fn("title")
def _title(s):
    return re.sub(r"\b([a-z])", lambda m: m.group(1).upper(), to_string(s))


@fn("strrev")
def _strrev(s):
    return to_string(s)[::-1]


@fn("trimspace")
def _trimspace(s):
    return to_string(s).strip()


@fn("trim")
def _trim(s, chars):
    return to_string(s).strip(to_string(chars))


@fn("trimprefix")
def _trimprefix(s, p):
    return to_string(s).removeprefix(to_string(p))


@fn("trimsuffix")
def _trimsuffix(s, p):
    return to_string(s).removesuffix(to_string(p))


@fn("startswith")
def _startswith(s, p):
    return to_string(s).startswith(to_string(p))


@fn("endswith")
def _endswith(s, p):
    return to_string(s).endswith(to_string(p))


@fn("strcontains")
def _strcontains(s, p):
    return to_string(p) in to_string(s)


@fn("substr")
def _substr(s, offset, length):
    s, offset, length = to_string(s), to_int(offset), to_int(length)
    if offset < 0:
        offset += len(s)
    if offset < 0 or offset > len(s):
        raise EvalError("substr(): offset is out of range")
    return s[offset:] if length < 0 else s[offset:offset + length]


@fn("indent")
def _indent(n, s):
    pad = " " * to_int(n)
    lines = to_string(s).split("\n")
    return "\n".join([lines[0]] + [pad + x for x in lines[1:]])


@fn("split")
def _split(sep, s):
    sep, s = to_string(sep), to_string(s)
    if s == "":
        return [""] if sep else []
    return s.split(sep) if sep else list(s)


def _re(pattern: str):
    try:
        return re.compile(pattern)
    except re.error as e:
        raise EvalError(f"invalid regular expression: {e}") from e


def _match_value(m: re.Match):
    if m.re.groupindex:
        return {k: m.group(k) for k in m.re.groupindex}
    if m.re.groups:
        return [g for g in m.groups()]
    return m.group(0)


@fn("regex")
def _regex(pattern, s):
    m = _re(to_string(pattern)).search(to_string(s))
    if m is None:
        raise EvalError("regex(): pattern did not match")
    return _match_value(m)


@fn("regexall")
def _regexall(pattern, s):
    return [_match_value(m) for m in _re(to_string(pattern)).finditer(to_string(s))]


@fn("replace")
def _replace(s, substr, repl):
    s, substr, repl = to_string(s), to_string(substr), to_string(repl)
    if len(substr) > 1 and substr.startswith("/") and substr.endswith("/"):
        py_repl = re.sub(r"\$\{(\w+)\}|\$(\d+)", lambda m: "\\g<" + (m.group(1) or m.group(2)) + ">", repl)
        return _re(substr[1:-1]).sub(py_repl, s)
    return s.replace(substr, repl)


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


@fn("format", structural=True)
def _format(fmt, *args):
    if not isinstance(fmt, str):
        return unknown_from([fmt, *args], "format() with a format that is not known before apply")
    if any(isinstance(a, Unknown) for a in args):
        return unknown_from(list(args), "")
    return format_string(fmt, list(args))


@fn("formatlist", structural=True)
def _formatlist(fmt, *args):
    if not isinstance(fmt, str) or not all(isinstance(a, (list, str, int, float, bool)) or a is None
                                           for a in args):
        return unknown_from([fmt, *args], "formatlist() of a value that is not known before apply")
    lengths = {len(a) for a in args if isinstance(a, list)}
    if len(lengths) > 1:
        raise EvalError("formatlist(): lists must have the same length")
    n = lengths.pop() if lengths else 1
    return [format_string(fmt, [a[i] if isinstance(a, list) else a for a in args]) for i in range(n)]


@fn("join", structural=True)
def _join(sep, *lists):
    if not isinstance(sep, str):
        return unknown_from([sep, *lists], "join() with a separator that is not known before apply")
    items: list = []
    for lst in lists:
        if _need_list(lst, "join") is None:
            return unknown_from(list(lists), "join() of a list that is not known before apply")
        items += lst
    parts: list = []
    for i, x in enumerate(items):
        if i:
            parts.append(sep)
        if x is None:
            raise EvalError("join(): null element")
        parts.append(template_part(x))
    return concat_parts(parts)


# --- コレクション
@fn("length", structural=True)
def _length(v):
    if isinstance(v, (list, dict)):
        return len(v)
    if isinstance(v, str):
        return len(v)
    if v is None:
        raise EvalError("length(): null value")
    return unknown_from(v, "length() of a value that is not known before apply")


@fn("concat", structural=True)
def _concat(*lists):
    out: list = []
    for lst in lists:
        if _need_list(lst, "concat") is None:
            return unknown_from(list(lists), "concat() of a list that is not known before apply")
        out += lst
    return out


@fn("merge", structural=True)
def _merge(*maps):
    out: dict = {}
    for m in maps:
        if m is None:
            continue
        if _need_map(m, "merge") is None:
            return unknown_from(list(maps), "merge() of a map that is not known before apply")
        out.update(m)
    return out


@fn("lookup", structural=True)
def _lookup(m, key, *default):
    if len(default) > 1:
        raise EvalError("lookup(): too many arguments")
    if _need_map(m, "lookup") is None or not isinstance(key, (str, int, float)) or isinstance(key, bool):
        return unknown_from([m, key, *default], "lookup() of a value that is not known before apply")
    key = to_string(key)
    if key in m:
        return m[key]
    if default:
        return default[0]
    raise EvalError(f"lookup(): no key {key!r}")


@fn("element", structural=True)
def _element(lst, idx):
    if isinstance(lst, Az) and lst.index == "*" and is_number(idx):
        return Az(to_int(idx))
    if _need_list(lst, "element") is None or not is_number(idx):
        return unknown_from([lst, idx], "element() of a value that is not known before apply")
    if not lst:
        raise EvalError("element(): empty list")
    i = to_int(idx)
    if i < 0:
        raise EvalError("element(): negative index")
    return lst[i % len(lst)]


@fn("slice", structural=True)
def _slice(lst, start, end):
    if not (is_number(start) and is_number(end)):
        return unknown_from([lst, start, end], "slice() of a value that is not known before apply")
    s, e = to_int(start), to_int(end)
    if isinstance(lst, Az) and lst.index == "*":
        if 0 <= s <= e:
            return [Az(i) for i in range(s, e)]
        raise EvalError("slice(): invalid range")
    if _need_list(lst, "slice") is None:
        return unknown_from([lst, start, end], "slice() of a list that is not known before apply")
    if not (0 <= s <= e <= len(lst)):
        raise EvalError("slice(): index out of range")
    return lst[s:e]


@fn("keys", structural=True)
def _keys(m):
    if _need_map(m, "keys") is None:
        return unknown_from(m, "keys() of a map that is not known before apply")
    return sorted_keys(m)


@fn("values", structural=True)
def _values(m):
    if _need_map(m, "values") is None:
        return unknown_from(m, "values() of a map that is not known before apply")
    return [m[k] for k in sorted_keys(m)]


@fn("toset", structural=True)
def _toset(v):
    if v is None:
        return None
    if _need_list(v, "toset") is None:
        return unknown_from(v, "toset() of a value that is not known before apply")
    if not all(is_concrete(x) or isinstance(x, Res) for x in v):
        return unknown_from(v, "toset() of a value that is not known before apply")
    return to_set(list(v))


@fn("tolist", structural=True)
def _tolist(v):
    if v is None:
        return None
    if _need_list(v, "tolist") is None:
        return unknown_from(v, "tolist() of a value that is not known before apply")
    return list(v)


@fn("tomap", structural=True)
def _tomap(v):
    if v is None:
        return None
    if _need_map(v, "tomap") is None:
        return unknown_from(v, "tomap() of a value that is not known before apply")
    return dict(v)


@fn("tostring", structural=True)
def _tostring(v):
    if v is None or isinstance(v, (Res, Concat, Pseudo, Unknown)) or (isinstance(v, Az) and v.index != "*"):
        return v
    if isinstance(v, (list, dict)) or isinstance(v, (Json, Az)):
        raise EvalError("tostring(): a string is required")
    return to_string(v)


@fn("tonumber", structural=True)
def _tonumber(v):
    if v is None or isinstance(v, (Res, Unknown)):
        return v
    if isinstance(v, MARKER_TYPES):
        return unknown_from(v, "tonumber() of a value that is not known before apply")
    return to_number(v)


@fn("tobool", structural=True)
def _tobool(v):
    if v is None or isinstance(v, (Res, Unknown)):
        return v
    if isinstance(v, MARKER_TYPES):
        return unknown_from(v, "tobool() of a value that is not known before apply")
    return to_bool(v)


@fn("coalesce", structural=True)
def _coalesce(*args):
    for a in args:
        if isinstance(a, Unknown):
            return unknown_from(list(args), "")
        if a is None or a == "":
            continue
        return a
    raise EvalError("coalesce(): no non-null, non-empty argument")


@fn("coalescelist", structural=True)
def _coalescelist(*args):
    for a in args:
        if _need_list(a, "coalescelist") is None:
            return unknown_from(list(args), "coalescelist() of a list that is not known before apply")
        if a:
            return a
    raise EvalError("coalescelist(): no non-empty list")


@fn("compact", structural=True)
def _compact(lst):
    if _need_list(lst, "compact") is None:
        return unknown_from(lst, "compact() of a list that is not known before apply")
    if any(isinstance(x, Unknown) for x in lst):
        return unknown_from(lst, "")
    return [x for x in lst if x is not None and x != ""]


@fn("flatten", structural=True)
def _flatten(lst):
    if _need_list(lst, "flatten") is None:
        return unknown_from(lst, "flatten() of a list that is not known before apply")
    out: list = []
    for x in lst:
        if isinstance(x, list):
            inner = _flatten(x)
            if isinstance(inner, Unknown):
                return unknown_from(lst, "")
            out += inner
        elif isinstance(x, (Unknown, Concat)) or (isinstance(x, Res) and (x.multi or x.attr is not None)):
            # 中身がリストかもしれない値（×N のまとまり、リストの属性）は平らにできない
            return unknown_from(lst, "flatten() of a value that is not known before apply")
        else:
            out.append(x)
    return out


@fn("distinct", structural=True)
def _distinct(lst):
    if _need_list(lst, "distinct") is None or any(isinstance(x, Unknown) for x in lst):
        return unknown_from(lst, "distinct() of a list that is not known before apply")
    return dedupe(lst)


@fn("reverse", structural=True)
def _reverse(lst):
    if _need_list(lst, "reverse") is None:
        return unknown_from(lst, "reverse() of a list that is not known before apply")
    return list(reversed(lst))


@fn("one", structural=True)
def _one(lst):
    if lst is None:
        return None
    if _need_list(lst, "one") is None:
        return unknown_from(lst, "one() of a list that is not known before apply")
    if len(lst) > 1:
        raise EvalError("one(): more than one element")
    return lst[0] if lst else None


@fn("contains", structural=True)
def _contains(lst, v):
    if _need_list(lst, "contains") is None or not is_concrete(v):
        return unknown_from([lst, v], "contains() of a value that is not known before apply")
    if any(is_concrete(x) and same(x, v) for x in lst):
        return True
    if not all(is_concrete(x) for x in lst):
        return unknown_from([lst, v], "contains() of a value that is not known before apply")
    return False


@fn("index")
def _index(lst, v):
    for i, x in enumerate(lst):
        if same(x, v):
            return i
    raise EvalError("index(): value not found")


@fn("range")
def _range(*args):
    nums = [to_number(a) for a in args]
    if len(nums) == 1:
        start, end, step = 0, nums[0], 1
    elif len(nums) == 2:
        start, end, step = nums[0], nums[1], 1 if nums[1] >= nums[0] else -1
    elif len(nums) == 3:
        start, end, step = nums
    else:
        raise EvalError("range(): 1 to 3 arguments")
    if step == 0:
        raise EvalError("range(): step must not be zero")
    out, x = [], start
    while x < end if step > 0 else x > end:
        if len(out) >= 1024:  # Terraform と同じ上限（黙って打ち切らない）
            raise EvalError("range(): more than 1024 elements")
        out.append(norm_number(x))
        x = arith("+", x, step)
    return out


@fn("zipmap", structural=True)
def _zipmap(keys, values):
    if _need_list(keys, "zipmap") is None or _need_list(values, "zipmap") is None or not is_concrete(keys):
        return unknown_from([keys, values], "zipmap() of a list that is not known before apply")
    if len(keys) != len(values):
        raise EvalError("zipmap(): lists must have the same length")
    return {to_string(k): v for k, v in zip(keys, values)}


@fn("sort")
def _sort(lst):
    return sorted(to_string(x) for x in lst)


@fn("alltrue")
def _alltrue(lst):
    return all(to_bool(x) for x in lst)


@fn("anytrue")
def _anytrue(lst):
    return any(to_bool(x) for x in lst)


@fn("chunklist", structural=True)
def _chunklist(lst, size):
    if _need_list(lst, "chunklist") is None or not is_number(size):
        return unknown_from([lst, size], "chunklist() of a list that is not known before apply")
    n = to_int(size)
    if n <= 0:
        return [list(lst)]
    return [lst[i:i + n] for i in range(0, len(lst), n)]


@fn("setunion")
def _setunion(*sets):
    return to_set([x for s in sets for x in s])


@fn("setintersection")
def _setintersection(first, *rest):
    return to_set([x for x in first if all(any(same(x, y) for y in s) for s in rest)])


@fn("setsubtract")
def _setsubtract(a, b):
    return to_set([x for x in a if not any(same(x, y) for y in b)])


@fn("setproduct")
def _setproduct(*sets):
    out: list = [[]]
    for s in sets:
        out = [x + [y] for x in out for y in s]
    return out


@fn("matchkeys")
def _matchkeys(values, keys, searchset):
    return [v for v, k in zip(values, keys) if any(same(k, s) for s in searchset)]


@fn("transpose")
def _transpose(m):
    out: dict = {}
    for k in sorted_keys(m):
        for v in m[k]:
            out.setdefault(to_string(v), []).append(k)
    return out


# --- 符号化
@fn("jsonencode", structural=True)
def _jsonencode(v):
    return v if isinstance(v, Unknown) else Json(v)


@fn("jsondecode")
def _jsondecode(s):
    try:
        return json.loads(to_string(s))
    except ValueError as e:
        raise EvalError(f"jsondecode(): {e}") from e


@fn("base64encode")
def _base64encode(s):
    return base64.b64encode(to_string(s).encode("utf-8")).decode("ascii")


@fn("base64decode")
def _base64decode(s):
    try:
        return base64.b64decode(to_string(s), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as e:
        raise EvalError(f"base64decode(): {e}") from e


@fn("urlencode")
def _urlencode(s):
    # Go の url.QueryEscape と同じ（空白は +。英数字と - _ . ~ 以外は %XX）
    from urllib.parse import quote_plus
    return quote_plus(to_string(s), safe="")


@fn("basename")
def _basename(p):
    return posixpath.basename(to_string(p).rstrip("/")) or "/"


@fn("dirname")
def _dirname(p):
    return posixpath.dirname(to_string(p)) or "."


# --- 印を素通しする関数
for _name in ("nonsensitive", "ephemeralasnull"):
    FUNCTIONS[_name] = lambda v: v
    STRUCTURAL.add(_name)


@fn("sensitive", structural=True)
def _sensitive(v):
    # 秘密の値として扱うと書かれた値は使わない（IR に書かない）。中の参照は引き継ぐ
    return Unknown("a sensitive value is not used", "TF-SENSITIVE-VAR", "info", refs_in(v))


# --- ネットワーク
def _network(prefix):
    try:
        return ipaddress.ip_network(to_string(prefix), strict=False)
    except ValueError as e:
        raise EvalError(f"invalid CIDR prefix: {e}") from e


@fn("cidrsubnet")
def _cidrsubnet(prefix, newbits, netnum):
    net = _network(prefix)
    newbits, netnum = to_int(newbits), to_int(netnum)
    new_len = net.prefixlen + newbits
    if newbits < 0 or new_len > net.max_prefixlen or not (0 <= netnum < 2 ** newbits):
        raise EvalError("cidrsubnet(): not enough bits or netnum out of range")
    addr = int(net.network_address) + (netnum << (net.max_prefixlen - new_len))
    return f"{ipaddress.ip_address(addr)}/{new_len}"


@fn("cidrsubnets")
def _cidrsubnets(prefix, *newbits_list):
    net = _network(prefix)
    out: list = []
    cursor = int(net.network_address)
    for nb in newbits_list:
        new_len = net.prefixlen + to_int(nb)
        if new_len > net.max_prefixlen:
            raise EvalError("cidrsubnets(): not enough bits")
        size = 1 << (net.max_prefixlen - new_len)
        cursor = (cursor + size - 1) // size * size
        if cursor + size > int(net.broadcast_address) + 1:
            raise EvalError("cidrsubnets(): not enough space")
        out.append(f"{ipaddress.ip_address(cursor)}/{new_len}")
        cursor += size
    return out


@fn("cidrhost")
def _cidrhost(prefix, hostnum):
    net = _network(prefix)
    n = to_int(hostnum)
    if n < 0:
        n += net.num_addresses
    if not (0 <= n < net.num_addresses):
        raise EvalError("cidrhost(): host number out of range")
    return str(ipaddress.ip_address(int(net.network_address) + n))


@fn("cidrnetmask")
def _cidrnetmask(prefix):
    net = _network(prefix)
    if net.version != 4:
        raise EvalError("cidrnetmask(): only IPv4")
    return str(net.netmask)


SUPPORTED = sorted(set(FUNCTIONS) | {"try", "can"})
