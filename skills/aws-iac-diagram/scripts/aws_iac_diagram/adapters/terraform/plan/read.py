"""plan JSON のファイルを読み、形を確かめる（plan JSON か、版に対応しているか、大きさ・数値の扱い）。
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path


MAX_PLAN_BYTES = 256 * 1024 * 1024  # plan JSON の大きさの上限（これより大きいものは読まない）
_sniffed: tuple | None = None       # is_plan_file が読んだ直近の1件（load_plan で二度読みしないため）


class PlanError(ValueError):
    """plan JSON として読めない。"""


def looks_like_plan(doc) -> bool:
    return isinstance(doc, dict) and "format_version" in doc and "terraform_version" in doc and \
        ("planned_values" in doc or "resource_changes" in doc)


def _reject_constant(name: str):
    raise ValueError(f"non-finite number: {name}")


def _parse_float(text: str) -> float:
    f = float(text)
    if not math.isfinite(f):  # 1e999 など
        raise ValueError("non-finite number")
    return f


def _read_json(path: Path):
    """plan JSON を読む。大きすぎるもの・NaN／Infinity・深すぎる入れ子は PlanError（メッセージにパスは書かない）。"""
    try:
        size = path.stat().st_size
    except OSError as e:
        raise PlanError(f"ファイルを開けません: {path.name}: {type(e).__name__}") from e
    if size > MAX_PLAN_BYTES:
        raise PlanError(f"大きすぎます（{MAX_PLAN_BYTES >> 20} MiB まで）: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=_reject_constant,
                          parse_float=_parse_float)
    except RecursionError as e:
        raise PlanError(f"入れ子が深すぎます: {path.name}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise PlanError(f"ファイルを開けません: {path.name}: {type(e).__name__}") from e
    except ValueError as e:  # 構文の誤り・NaN／Infinity・巨大な数
        raise PlanError(f"JSON として不正です: {path.name}: {type(e).__name__}") from e


def _stamp(path: Path):
    st = path.stat()
    return (str(path.resolve()), st.st_mtime_ns, st.st_size)


def load_plan(path: Path) -> dict:
    global _sniffed
    doc = None
    if _sniffed is not None:
        try:
            if _sniffed[0] == _stamp(path):
                doc = _sniffed[1]
        except OSError:
            pass
        _sniffed = None
    if doc is None:
        doc = _read_json(path)
    if not looks_like_plan(doc):
        if isinstance(doc, dict) and "values" in doc and "format_version" in doc:
            raise PlanError(f"state の JSON です（plan JSON ではありません）: {path.name}")
        raise PlanError(f"terraform show -json の plan の出力ではありません: {path.name}")
    major = str(doc.get("format_version", "")).split(".")[0]
    if major != "1":
        raise PlanError(f"format_version {version_text(doc.get('format_version'))} には対応していません"
                        "（1.x だけ）")
    validate(doc)
    return doc


def is_plan_file(path: Path) -> bool:
    """--input に渡したファイルが plan JSON か（.json で、terraform show -json の plan の形）。"""
    global _sniffed
    try:
        if not (path.is_file() and path.suffix.lower() == ".json"):
            return False
        doc = _read_json(path)
        if not looks_like_plan(doc):
            return False
        _sniffed = (_stamp(path), doc)
        return True
    except Exception:  # noqa: BLE001  読めないものは plan JSON ではない（RecursionError・巨大なファイルなども）
        return False


def why_unreadable(path: Path) -> str | None:
    """.json のファイルが plan JSON として読めない理由（大きすぎる・入れ子が深すぎる・NaN など）。JSON として読めて、
    ただ plan の形ではないだけなら None。"""
    try:
        _read_json(path)
    except PlanError as e:
        return str(e)
    except Exception:  # noqa: BLE001
        return None
    return None


def version_text(v) -> str:
    """plan JSON の terraform_version・format_version を、IR に書く前に整える（英数字と . + _ - だけ、32 字まで）。"""
    s = v if isinstance(v, str) else ""
    s = re.sub(r"[^0-9A-Za-z.+_-]", "", s)[:32]
    return s or "unknown"


def _bad(path: str):
    raise PlanError(f"unexpected structure at {path}")


def validate(plan: dict) -> None:
    """plan JSON のうち、このアダプタが読む入れ物の型を確かめる。違えば PlanError（値は書かない）。"""
    def obj(v, p, nullable=True):
        if v is None and nullable:
            return {}
        if not isinstance(v, dict):
            _bad(p)
        return v

    def lst(v, p):
        if v is None:
            return []
        if not isinstance(v, list):
            _bad(p)
        return v

    def text(v, p, required=False):
        if v is None and not required:
            return
        if not isinstance(v, str) or not v:
            _bad(p)

    def flags(v, p):  # after・after_unknown・after_sensitive: オブジェクトか null か真偽値（削除では false）
        if v is not None and not isinstance(v, (dict, bool)):
            _bad(p)

    def expressions(v, p):
        for k, x in obj(v, p).items():
            if not isinstance(x, (dict, list)):
                _bad(f"{p}.{k}")
            if isinstance(x, dict) and not isinstance(x.get("references", []), list):
                _bad(f"{p}.{k}.references")
            if isinstance(x, list):
                for i, y in enumerate(x):
                    if not isinstance(y, dict):
                        _bad(f"{p}.{k}[{i}]")

    def cfg_mod(v, p):
        v = obj(v, p)
        for i, r in enumerate(lst(v.get("resources"), f"{p}.resources")):
            q = f"{p}.resources[{i}]"
            obj(r, q, False)
            text(r.get("address"), f"{q}.address", True)
            text(r.get("mode"), f"{q}.mode")
            text(r.get("type"), f"{q}.type", True)
            text(r.get("provider_config_key"), f"{q}.provider_config_key")
            expressions(r.get("expressions"), f"{q}.expressions")
            lst(r.get("depends_on"), f"{q}.depends_on")
        for name, c in obj(v.get("module_calls"), f"{p}.module_calls").items():
            q = f"{p}.module_calls.{name}"
            obj(c, q, False)
            expressions(c.get("expressions"), f"{q}.expressions")
            lst(c.get("depends_on"), f"{q}.depends_on")
            cfg_mod(c.get("module"), f"{q}.module")
        for name, o in obj(v.get("outputs"), f"{p}.outputs").items():
            obj(obj(o, f"{p}.outputs.{name}").get("expression"), f"{p}.outputs.{name}.expression")
        for name, o in obj(v.get("variables"), f"{p}.variables").items():
            obj(o, f"{p}.variables.{name}")

    def values_mod(v, p):
        v = obj(v, p)
        for i, r in enumerate(lst(v.get("resources"), f"{p}.resources")):
            q = f"{p}.resources[{i}]"
            obj(r, q, False)
            text(r.get("address"), f"{q}.address", True)
            text(r.get("mode"), f"{q}.mode")
            text(r.get("type"), f"{q}.type", True)
            flags(r.get("values"), f"{q}.values")
            flags(r.get("sensitive_values"), f"{q}.sensitive_values")
        for i, c in enumerate(lst(v.get("child_modules"), f"{p}.child_modules")):
            values_mod(c, f"{p}.child_modules[{i}]")

    for k, x in obj(plan.get("variables"), "variables").items():
        obj(x, f"variables.{k}")
    for i, rc in enumerate(lst(plan.get("resource_changes"), "resource_changes")):
        q = f"resource_changes[{i}]"
        obj(rc, q, False)
        text(rc.get("address"), f"{q}.address", True)
        text(rc.get("mode"), f"{q}.mode")
        text(rc.get("type"), f"{q}.type")
        text(rc.get("provider_config_key"), f"{q}.provider_config_key")
        ch = obj(rc.get("change"), f"{q}.change")
        for j, a in enumerate(lst(ch.get("actions"), f"{q}.change.actions")):
            text(a, f"{q}.change.actions[{j}]", True)
        for f in ("after", "after_unknown", "after_sensitive"):
            flags(ch.get(f), f"{q}.change.{f}")
    prior = obj(plan.get("prior_state"), "prior_state")
    values_mod(obj(prior.get("values"), "prior_state.values").get("root_module"), "prior_state.values.root_module")
    values_mod(obj(plan.get("planned_values"), "planned_values").get("root_module"), "planned_values.root_module")
    cfg = obj(plan.get("configuration"), "configuration")
    for k, x in obj(cfg.get("provider_config"), "configuration.provider_config").items():
        q = f"configuration.provider_config.{k}"
        obj(x, q, False)
        expressions(x.get("expressions"), f"{q}.expressions")
    cfg_mod(cfg.get("root_module"), "configuration.root_module")
