"""plan が sensitive とした位置と、作られないブロックの値を伏せる（.tf の値のマスク）。
"""
from __future__ import annotations

from aws_iac_diagram.adapters.terraform.plan.values import ABSENT, SENSITIVE_REASON, has_true
from aws_iac_diagram.core import ir_raw


VALUELESS = ("$res", "$pseudo", "$az")  # 値を持たない印（参照・疑似パラメータ）。$unknown の理由の文には値が入りうる
NOT_CREATED_REASON = "not created; only literal values are kept (not values from plan variables)"


def mask_sensitive(tv, ps, path: str, found: list):
    """.tf の値 tv のうち、plan の sensitive の印 ps の位置（と、印の形が合わない container の全体）を $unknown にする。

    .tf の評価は plan の variables の値を使うので、sensitive と宣言していない変数が provider の sensitive の
    属性（password・secret_string など）に入ると、.tf の値に秘密が残る。IR に書く前に、plan が sensitive とした位置は
    必ず伏せる（7.2）。$json・$concat などの印は値の全体として扱う。伏せた位置（props のパス）を found に足す。
    """
    if ps is None or ps is False or not has_true(ps):
        return tv
    if ps is True:
        if isinstance(tv, dict) and any(k in tv for k in VALUELESS):
            return tv  # 参照などで、秘密の値そのものは持たない
        found.append(path)
        return {"$unknown": SENSITIVE_REASON}
    if isinstance(tv, dict) and isinstance(ps, dict) and not ir_raw.is_marker(tv):
        out = {}
        for k, x in tv.items():
            uk = ir_raw.unescape_key(k)
            out[k] = mask_sensitive(x, ps.get(uk), ir_raw.join_path(path, uk), found)
        return out
    if isinstance(tv, list) and isinstance(ps, list) and len(ps) == len(tv):
        return [mask_sensitive(x, ps[i], ir_raw.join_path(path, i), found) for i, x in enumerate(tv)]
    if isinstance(tv, dict) and any(k in tv for k in VALUELESS):
        return tv
    found.append(path)  # 値の形と印の形が合わない: 全体を伏せる
    return {"$unknown": SENSITIVE_REASON}


def mask_props(props, sens, found: list):
    """mask_sensitive の入口。sens が true（すべて sensitive）のときは、props の属性ごとに伏せる（props は object のまま）。"""
    if sens is True and isinstance(props, dict):
        sens = {ir_raw.unescape_key(k): True for k in props}
    return mask_sensitive(props, sens, "", found)


def literal_only(tv, pv, path: str, found: list):
    """作られないリソースの .tf の値のうち、plan の configuration の定数（pv）と同じものと、値を持たない印だけを残す。

    .tf の評価は plan の variables の値を使うが、作られないリソースには plan の after も sensitive の印も無く、
    変数の値が sensitive かどうかを plan から確かめられない。変数から来た値は $unknown にする。
    """
    if isinstance(tv, dict) and any(k in tv for k in VALUELESS):
        return tv
    if isinstance(tv, dict) and not ir_raw.is_marker(tv):
        pd = pv if isinstance(pv, dict) and not ir_raw.is_marker(pv) else {}
        return {k: literal_only(x, pd.get(k, ABSENT), ir_raw.join_path(path, ir_raw.unescape_key(k)), found)
                for k, x in tv.items()}
    if isinstance(tv, list):
        pl = pv if isinstance(pv, list) else []
        return [literal_only(x, pl[i] if i < len(pl) else ABSENT, ir_raw.join_path(path, i), found)
                for i, x in enumerate(tv)]
    if pv is not ABSENT and type(tv) is type(pv) and tv == pv:
        return tv
    found.append(path)
    return {"$unknown": NOT_CREATED_REASON}


def under_any(paths: list, path: str) -> bool:
    """path が、paths のどれか（または、その下）か。"""
    return any(path == m or path.startswith(m + ".") or path.startswith(m + "[") for m in paths)
