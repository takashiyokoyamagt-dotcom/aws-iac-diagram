"""plan の値の道具: known after apply（UNK）と sensitive（SENS）の印を持つ値への変換、印の位置の扱い。
"""
from __future__ import annotations

from aws_iac_diagram.core import ir_raw


UNKNOWN_REASON = "known after apply (terraform plan)"
SENSITIVE_REASON = "sensitive value in the plan; not used"


class _Unk:
    """plan の after_unknown（known after apply）の値。"""
    __slots__ = ()


class _Sens:
    """plan の after_sensitive の値（使わない）。"""
    __slots__ = ()


UNK = _Unk()
SENS = _Sens()
ABSENT = object()


def conv(value, unknown=None, sens=None):
    """plan の値を、unknown・sensitive の印を付けた値にする。null は ABSENT（書かない）。"""
    if sens is True:
        return ABSENT if value is None and unknown is not True else SENS  # null は伏せるものが無い
    if has_true(sens) and not (value is None or (isinstance(value, dict) and isinstance(sens, dict)) or
                               (isinstance(value, list) and isinstance(sens, list))):
        return SENS  # 値の形と sensitive の印の形が合わない（値が dict なのに印が list など）: 伏せる側に倒す
    if unknown is True:
        return UNK
    if isinstance(value, dict) or isinstance(unknown, dict) or isinstance(sens, dict):
        v = value if isinstance(value, dict) else {}
        u = unknown if isinstance(unknown, dict) else {}
        s = sens if isinstance(sens, dict) else {}
        keys = list(v) + [k for k in u if k not in v and u[k] is True] + \
            [k for k in s if k not in v and s[k] is True and k not in u]
        if not isinstance(value, dict) and value is None and not keys:
            return ABSENT
        out = {}
        for k in keys:
            x = conv(v.get(k), u.get(k), s.get(k))
            if x is not ABSENT:
                out[("$" + k) if k.startswith("$") else k] = x
        return out
    if isinstance(value, list) or isinstance(unknown, list):
        v = value if isinstance(value, list) else []
        u = unknown if isinstance(unknown, list) else []
        s = sens if isinstance(sens, list) else []
        out = []
        for i, x in enumerate(v):
            c = conv(x, u[i] if i < len(u) else None, s[i] if i < len(s) else None)
            out.append(None if c is ABSENT else c)
        return out
    if value is None:
        return ABSENT
    if isinstance(value, str):
        return ir_raw.maybe_json(value)
    return value


def leaves(v, path: str, out: list, kind) -> list:
    """v の中の kind（UNK など）の位置（props の上のパス）。"""
    if v is kind:
        out.append(path)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            leaves(x, ir_raw.join_path(path, i), out, kind)
    elif isinstance(v, dict) and not ir_raw.is_marker(v):
        for k, x in v.items():
            leaves(x, ir_raw.join_path(path, ir_raw.unescape_key(k)), out, kind)
    elif isinstance(v, dict) and "$json" in v:
        leaves(v["$json"], path, out, kind)
    return out


def has_mark(v) -> bool:
    if v is UNK or v is SENS:
        return True
    if isinstance(v, list):
        return any(has_mark(x) for x in v)
    if isinstance(v, dict):
        return any(has_mark(x) for x in v.values())
    return False


def set_at(v, rel: list, new):
    """v の中の rel（("key", k) | ("idx", i) の並び）の位置を new にした値。"""
    if not rel:
        return new
    kind, k = rel[0]
    if isinstance(v, dict) and "$json" in v and len(v) == 1:
        return {"$json": set_at(v["$json"], rel, new)}
    if kind == "idx":
        out = list(v)
        out[k] = set_at(out[k], rel[1:], new)
        return out
    out = dict(v)
    key = ("$" + k) if k.startswith("$") else k
    out[key] = set_at(out[key], rel[1:], new)
    return out


def mark_paths(v, path: str, kind, rel=()) -> list:
    """kind の位置を (props のパス, 相対の位置) で返す（leaves と同じ順）。"""
    out = []
    if v is kind:
        return [(path, list(rel))]
    if isinstance(v, list):
        for i, x in enumerate(v):
            out += mark_paths(x, ir_raw.join_path(path, i), kind, rel + (("idx", i),))
    elif isinstance(v, dict) and "$json" in v and len(v) == 1:
        out += mark_paths(v["$json"], path, kind, rel)
    elif isinstance(v, dict) and not ir_raw.is_marker(v):
        for k, x in v.items():
            uk = ir_raw.unescape_key(k)
            out += mark_paths(x, ir_raw.join_path(path, uk), kind, rel + (("key", uk),))
    return out


def string_paths(v, path: str, rel=()) -> list:
    """文字列の位置（$json の中も）を (props のパス, 相対の位置, 文字列) で返す。"""
    out = []
    if isinstance(v, str):
        return [(path, list(rel), v)]
    if isinstance(v, list):
        for i, x in enumerate(v):
            out += string_paths(x, ir_raw.join_path(path, i), rel + (("idx", i),))
    elif isinstance(v, dict) and "$json" in v and len(v) == 1:
        out += string_paths(v["$json"], path, rel)
    elif isinstance(v, dict) and not ir_raw.is_marker(v):
        for k, x in v.items():
            uk = ir_raw.unescape_key(k)
            out += string_paths(x, ir_raw.join_path(path, uk), rel + (("key", uk),))
    return out


def finish(v):
    """印を残した値を raw IR の値にする（UNK・SENS → $unknown）。"""
    if v is UNK:
        return {"$unknown": UNKNOWN_REASON}
    if v is SENS:
        return {"$unknown": SENSITIVE_REASON}
    if isinstance(v, list):
        return [finish(x) for x in v]
    if isinstance(v, dict):
        if "$res" in v:
            return v
        return {k: finish(x) for k, x in v.items()}
    return v


def merge_flags(a, b):
    """sensitive の印を位置ごとに OR で合わせる（どちらかが true の位置は true。形が違って片方に true があれば全体を true）。"""
    if a is True or b is True:
        return True
    if not has_true(a):
        return b if b is not None else a
    if not has_true(b):
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, x in b.items():
            out[k] = merge_flags(out.get(k), x)
        return out
    if isinstance(a, list) and isinstance(b, list):
        return [merge_flags(a[i] if i < len(a) else None, b[i] if i < len(b) else None)
                for i in range(max(len(a), len(b)))]
    return True


def has_true(v) -> bool:
    if v is True:
        return True
    if isinstance(v, list):
        return any(has_true(x) for x in v)
    if isinstance(v, dict):
        return any(has_true(x) for x in v.values())
    return False
