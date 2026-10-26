"""plan の address の道具: address の字句（parse_steps）、モジュールの経路、参照のまとめ方（collapse）。添字の付け外しは addresses.py（.tf と共通）。
"""
from __future__ import annotations

import json
import re
from bisect import bisect_left


_STEP = re.compile(r'\.?([A-Za-z_][A-Za-z0-9_-]*)|\[("(?:[^"\\]|\\.)*"|\d+|\*)\]')


def parse_steps(text: str) -> list:
    """address・参照の文字列を [("attr", 名前) | ("index", 0 | "key" | "*")] に分ける。読めなければ []。"""
    out, pos = [], 0
    while pos < len(text):
        m = _STEP.match(text, pos)
        if not m or m.end() == pos:
            return []
        if m.group(1) is not None:
            out.append(("attr", m.group(1)))
        else:
            g = m.group(2)
            out.append(("index", json.loads(g) if g.startswith('"') else "*" if g == "*" else int(g)))
        pos = m.end()
    return out


def module_path(address: str) -> str:
    """module.a["k"].module.b[0].aws_x.y → module.a.module.b（添字なしのモジュールの経路）。"""
    steps = parse_steps(address)
    parts, i = [], 0
    while i + 1 < len(steps) and steps[i] == ("attr", "module"):
        parts.append(f"module.{steps[i + 1][1]}")
        i += 3 if i + 2 < len(steps) and steps[i + 2][0] == "index" else 2
    return ".".join(parts)


def key_order(k):
    return (0, k, "") if isinstance(k, int) else (1, 0, str(k))


def collapse(refs: list[str]) -> list[str]:
    """configuration の references の重なりを、最も細かいもの1つにまとめる（7.3）。

    aws_subnet.private[0].id・aws_subnet.private[0]・aws_subnet.private → aws_subnet.private[0].id。ほかの文字列の
    前の部分（後ろに . か [ が続く）になっている文字列を除く。順は最初に現れた順。
    """
    uniq = list(dict.fromkeys(r for r in refs if isinstance(r, str)))
    ordered = sorted(uniq)
    return [r for r in uniq if not (_has_prefixed(ordered, r + ".") or _has_prefixed(ordered, r + "["))]


def prefixed(ordered: list[str], prefix: str):
    """整列した文字列のうち、prefix で始まるもの。"""
    i = bisect_left(ordered, prefix)
    while i < len(ordered) and ordered[i].startswith(prefix):
        yield ordered[i]
        i += 1


def _has_prefixed(ordered: list[str], prefix: str) -> bool:
    """整列した文字列の中に、prefix で始まるものがあるか（prefix 自身を除く。prefix は "." か "[" で終わる）。"""
    i = bisect_left(ordered, prefix)
    return i < len(ordered) and ordered[i].startswith(prefix)
