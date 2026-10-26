"""address の道具（インスタンスの添字 [0]・["key"]・[*] の付け外し）。.tf の側と plan JSON の側で共通。
"""
from __future__ import annotations

import json
import re


INSTANCE_KEY = re.compile(r'\[(?:\d+|\*|"(?:[^"\\]|\\.)*")\]$')


def block_address(address: str) -> str:
    """インスタンスの添字（[0]・["key"]・[*]）を除いたブロックの address。"""
    return INSTANCE_KEY.sub("", address)


def inst_address(base: str, key) -> str:
    if key is None:
        return base
    if isinstance(key, int):
        return f"{base}[{key}]"
    return f"{base}[{json.dumps(key, ensure_ascii=False)}]"
