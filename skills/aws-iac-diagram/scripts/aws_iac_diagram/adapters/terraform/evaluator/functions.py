"""Terraform の組み込み関数（value 型は values.py）。docs/spec/ir-schema/ の 7.2。

関数は、値が決まっていれば Terraform と同じ結果を返し、決まらない値（Res・Unknown など）を含むと、
構造だけで決まるもの（length・concat・merge・lookup など）は印を残したまま、それ以外は Unknown を返す。
引数の誤り（範囲外の添字、無いキーなど）は EvalError（try・can で使う）。
"""
from __future__ import annotations

import base64
import ipaddress
import json
import math
import posixpath
import re

from aws_iac_diagram.adapters.terraform.evaluator.values import (
    Az, Concat, EvalError, Json, MARKER_TYPES, Pseudo, Res, Unknown, arith, concat_parts, dedupe,
    format_string, is_concrete, is_number, norm_number, refs_in, same, sorted_keys, template_part,
    to_bool, to_int, to_number, to_set, to_string, type_name, unknown_from,
)


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


# AZ 名の代表（リージョンの形の違うもの）。$az に正規表現を当てるとき、すべてでマッチの数が同じなら、その数に決める
AZ_NAME_SAMPLES = ("us-east-1a", "ap-northeast-1c", "eu-central-1b", "cn-north-1a", "us-gov-west-1a", "il-central-1a",
                   "ap-southeast-3b", "me-central-1a")


@fn("regexall", structural=True)
def _regexall(pattern, s):
    if isinstance(s, Az) and isinstance(s.index, int) and isinstance(pattern, str):
        # data.aws_availability_zones の names の要素（AZ 名）。AZ 名の形で決まるパターン（vpc モジュールの
        # "^[a-z]+-"。AZ 名か AZ ID かの判定）のマッチの数だけを、代表の名前で決める（マッチした文字列は決まらない）。
        # 代表によって数が違えば決めない
        rx = _re(pattern)
        counts = {len(list(rx.finditer(name))) for name in AZ_NAME_SAMPLES}
        if len(counts) != 1:
            return unknown_from([s], "regexall() on an AZ name whose result depends on the region")
        return [Unknown("regexall() on an AZ name: only the number of matches is known", "TF-UNEVALUATED",
                        "info", refs_in(s))] * counts.pop()
    if not (is_concrete(pattern) and is_concrete(s)):
        return unknown_from([pattern, s], "regexall() of a value that is not known before apply")
    return [_match_value(m) for m in _re(to_string(pattern)).finditer(to_string(s))]


@fn("replace")
def _replace(s, substr, repl):
    s, substr, repl = to_string(s), to_string(substr), to_string(repl)
    if len(substr) > 1 and substr.startswith("/") and substr.endswith("/"):
        py_repl = re.sub(r"\$\{(\w+)\}|\$(\d+)", lambda m: "\\g<" + (m.group(1) or m.group(2)) + ">", repl)
        return _re(substr[1:-1]).sub(py_repl, s)
    return s.replace(substr, repl)


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
    if isinstance(m, dict) and not m and default:  # 空のマップは、キーが決まらなくても既定値（vpc モジュールの *_tags_per_az）
        return default[0]
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
