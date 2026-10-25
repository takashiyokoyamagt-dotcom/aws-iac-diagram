"""Terraform の plan JSON（`terraform show -json <plan>` の出力）から raw IR（ir-schema.md の 7章）を作る。

フェーズ2 の手順4。標準ライブラリだけで動く（tf.py から使う）。決まりは ir-schema.md の 7.2「TF の plan JSON」と
7.3「plan JSON の参照」。

  - address・count／for_each の展開・作られるか（enabled）は Terraform の結果（planned_values・resource_changes・
    prior_state）をそのまま使う。設定（configuration）にあってインスタンスが無いブロックは、添字なしの address で
    enabled: false（.tf と同じ）。レジストリなどリモートのモジュールの中の、作られないブロックと data は載せない
    （要約表の展開と同じ。4章の module_summary）
  - props は、設定（configuration の expressions）に書かれた属性とブロックだけ。値は plan の after（data は
    prior_state の values）。known after apply（after_unknown）は $unknown、sensitive（after_sensitive）の値は使わず
    $unknown
  - 参照は configuration の references。重なり（aws_subnet.private[0].id・aws_subnet.private[0]・aws_subnet.private）
    は最も細かいもの1つにまとめる（7.3）。var.*（モジュールの変数）は呼び出しの式へ、module.x.y は子の出力の式へ
    たどり、through に書く。local.* は plan JSON に式が無いのでたどれない（TF-PLAN-LOCALS）
  - 参照を props のどこに置くか（$res にして active にするか）は、値の形と先のリソースの値で決める（7.3）

combine() は、同じ構成の .tf から作った raw IR と合わせる（--input <フォルダ> --plan <plan JSON>）。address と
作られるかは plan、file・props・参照の位置は .tf、.tf で決まらなかった値は plan の値で埋める。plan の設定にあって
.tf の参照に無い組（from とブロック）は unevaluated で足す。plan が sensitive とした位置は、.tf の値も使わない
（mask_sensitive。.tf の評価は plan の variables の値を使うので、sensitive と宣言していない変数が入りうる）。
"""
from __future__ import annotations

import json
import math
import os
import re
from bisect import bisect_left
from dataclasses import dataclass, field
from pathlib import Path

from lib import ir_raw

# .tf では $pseudo にする data の属性（7.2。引数の無い data だけ）
PSEUDO_DATA = {"aws_region": ("name", "region", "id"), "aws_caller_identity": ("account_id",),
               "aws_partition": ("partition", "id", "dns_suffix")}
SKIP_ROOTS = {"count", "each", "path", "terraform", "self", "ephemeral"}
INSTANCE_KEY = re.compile(r'\[(?:\d+|\*|"(?:[^"\\]|\\.)*")\]$')
_STEP = re.compile(r'\.?([A-Za-z_][A-Za-z0-9_-]*)|\[("(?:[^"\\]|\\.)*"|\d+|\*)\]')
UNKNOWN_REASON = "known after apply (terraform plan)"
SENSITIVE_REASON = "sensitive value in the plan; not used"
# .tf の診断のうち、plan の値で埋めてよい $unknown の理由（秘密の値 TF-SENSITIVE-VAR などは埋めない）
FILLABLE = {"TF-UNRESOLVED-VAR", "TF-UNEVALUATED", "TF-EVAL-ERROR", "TF-UNSUPPORTED-FUNCTION", "TF-COUNT-INDEX",
            "TF-MODULE-SUMMARY-OUTPUT", "TF-UNDEFINED-REF"}


class PlanError(ValueError):
    """plan JSON として読めない。"""


# ------------------------------------------------------------------ 読み込みと判定

def looks_like_plan(doc) -> bool:
    return isinstance(doc, dict) and "format_version" in doc and "terraform_version" in doc and \
        ("planned_values" in doc or "resource_changes" in doc)


MAX_PLAN_BYTES = 256 * 1024 * 1024  # plan JSON の大きさの上限（これより大きいものは読まない）
_sniffed: tuple | None = None       # is_plan_file が読んだ直近の1件（load_plan で二度読みしないため）


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
        raise PlanError(f"format_version {_version(doc.get('format_version'))} には対応していません"
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


def _version(v) -> str:
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


# ------------------------------------------------------------------ address

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


def block_address(address: str) -> str:
    return INSTANCE_KEY.sub("", address)


def inst_address(base: str, key) -> str:
    if key is None:
        return base
    if isinstance(key, int):
        return f"{base}[{key}]"
    return f"{base}[{json.dumps(key, ensure_ascii=False)}]"


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


# ------------------------------------------------------------------ 値

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


# ------------------------------------------------------------------ plan の中身

@dataclass
class Inst:
    address: str
    mode: str
    type: str
    after: object
    unknown: object
    sens: object
    provider_key: str | None = None

    def value_of(self, attr: str | None):
        """属性の値（決まっていて sensitive でないときだけ）。無ければ ABSENT。"""
        if attr is None or not isinstance(self.after, dict):
            return ABSENT
        if self.sens is True:
            return ABSENT
        u = self.unknown.get(attr) if isinstance(self.unknown, dict) else None
        s = self.sens.get(attr) if isinstance(self.sens, dict) else None
        if u is True or s is True or (s and has_true(s)):
            return ABSENT
        v = self.after.get(attr)
        if v is None or (u and has_true(u)):
            return ABSENT
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


@dataclass
class Target:
    to: str
    attr: str | None
    through: tuple = ()
    exact: bool = True       # インスタンス1つを指す（添字があるか、count・for_each の無いブロック）
    whole: bool = False      # count・for_each のブロックの全体（スプラットなど）のインスタンスの1つ


@dataclass
class ModInst:
    prefix: str              # "module.vpc." のようなインスタンスの経路（ルートは ""）
    cfg: dict                # configuration の module（resources・module_calls・outputs・variables）
    parent: "ModInst | None" = None
    name: str = ""           # 呼び出しの名前
    call: dict = field(default_factory=dict)
    remote: bool = False     # レジストリ・git などのモジュール（とその中のモジュール）
    zero: bool = False       # count が 0・for_each が空の呼び出し（添字なしの経路）
    children: dict = field(default_factory=dict)  # 名前 → [ModInst]
    dir: str | None = None   # ローカルモジュールのフォルダ（ルートからの相対。.tf.json の file を探すため）
    rindex: dict | None = None  # cfg の resources を address で引く表（block_cfg が最初に使うときに作る）


def is_local_source(src) -> bool:
    return isinstance(src, str) and (src.startswith("./") or src.startswith("../"))


class PlanReader:
    def __init__(self, plan: dict, file_name: str):
        self.plan = plan
        self.file = file_name
        self.insts: dict[str, Inst] = {}
        self.by_block: dict[str, list[Inst]] = {}
        self.resources: list[dict] = []
        self.refs: list[dict] = []
        self.diagnostics: list[dict] = []
        self.locals_seen: set = set()
        self.emitted: set = set()
        self.deleted: set = set()       # actions が delete・forget だけのリソースの address
        self.deleted_sens: dict = {}    # そのブロックの address → sensitive の印（before・after・prior_state の OR）
        self.destroy_plan = False       # managed のリソースの変更がすべて delete・forget（terraform plan -destroy）
        self.root_vars = {k: (v or {}).get("value") for k, v in (plan.get("variables") or {}).items()}
        self.provider_config = (plan.get("configuration") or {}).get("provider_config") or {}
        self.collect_instances()
        root_cfg = (plan.get("configuration") or {}).get("root_module") or {}
        self.root = ModInst("", root_cfg, dir=".")
        self.build_tree(self.root)

    # ---- インスタンス
    def add_inst(self, inst: Inst) -> None:
        if inst.address in self.insts:
            # resource_changes・prior_state・planned_values のどれかが sensitive とした位置は、全部で sensitive にする
            old = self.insts[inst.address]
            old.sens = merge_flags(old.sens, inst.sens)
            return
        self.insts[inst.address] = inst
        self.by_block.setdefault(block_address(inst.address), []).append(inst)

    def collect_instances(self) -> None:
        live_managed = False
        for rc in self.plan.get("resource_changes") or []:
            if "deposed" in rc:
                continue  # 置き換えで残った古いオブジェクト（同じ address の今のオブジェクトとは別）
            ch = rc.get("change") or {}
            actions = ch.get("actions") or []
            if actions == ["delete"] or actions == ["forget"]:
                # 設定から消えたもの・terraform plan -destroy の対象（これから消す）は図に載せない。prior_state にも
                # あるので、address を覚えておいて、そちらから足さない
                self.deleted.add(rc["address"])
                self.note_deleted_sens(rc["address"], ch.get("before_sensitive"))
                self.note_deleted_sens(rc["address"], ch.get("after_sensitive"))
                continue
            live_managed = live_managed or rc.get("mode", "managed") == "managed"
            self.add_inst(Inst(rc["address"], rc.get("mode", "managed"), rc.get("type", ""), ch.get("after"),
                               ch.get("after_unknown") or {},
                               merge_flags(ch.get("after_sensitive") or {}, ch.get("before_sensitive")),
                               rc.get("provider_config_key")))
        self.destroy_plan = bool(self.deleted) and not live_managed

        def walk(mod):
            for r in (mod or {}).get("resources") or []:
                if r["address"] in self.deleted:
                    self.note_deleted_sens(r["address"], r.get("sensitive_values"))
                    continue
                self.add_inst(Inst(r["address"], r.get("mode", "managed"), r.get("type", ""), r.get("values"), {},
                                   r.get("sensitive_values") or {}))
            for c in (mod or {}).get("child_modules") or []:
                walk(c)
        walk(((self.plan.get("prior_state") or {}).get("values") or {}).get("root_module"))
        walk((self.plan.get("planned_values") or {}).get("root_module"))
        for lst in self.by_block.values():
            lst.sort(key=lambda i: key_order(self.inst_key(i.address)))
        self.sorted_addrs = sorted(self.insts)

    def note_deleted_sens(self, address: str, flags) -> None:
        """これから消すリソース（図には作られないものとして出す）の sensitive の印。ブロックごとに合わせて覚える。"""
        b = block_address(address)
        self.deleted_sens[b] = merge_flags(self.deleted_sens.get(b), flags)

    @staticmethod
    def inst_key(address: str):
        steps = parse_steps(address)
        return steps[-1][1] if steps and steps[-1][0] == "index" else None

    # ---- モジュールの木
    def build_tree(self, mod: ModInst) -> None:
        for name, call in sorted(((mod.cfg.get("module_calls") or {}).items())):
            src = call.get("source")
            remote = mod.remote or not is_local_source(src)
            child_dir = None
            if not remote and mod.dir is not None and isinstance(src, str):
                child_dir = os.path.normpath(os.path.join(mod.dir, src)).replace("\\", "/")
            base = f"{mod.prefix}module.{name}"
            counted = "count_expression" in call or "for_each_expression" in call
            keys = set()
            if counted:
                for a in prefixed(self.sorted_addrs, base + "["):
                    steps = parse_steps(a[len(mod.prefix):])
                    if len(steps) >= 3 and steps[2][0] == "index":
                        keys.add(steps[2][1])
            kids = []
            if counted and not keys:
                kids.append(ModInst(base + ".", call.get("module") or {}, mod, name, call, remote, True,
                                    dir=child_dir))
            elif counted:
                for k in sorted(keys, key=key_order):
                    kids.append(ModInst(inst_address(base, k) + ".", call.get("module") or {}, mod, name, call,
                                        remote, mod.zero, dir=child_dir))
            else:
                kids.append(ModInst(base + ".", call.get("module") or {}, mod, name, call, remote, mod.zero,
                                    dir=child_dir))
            mod.children[name] = kids
            for k in kids:
                self.build_tree(k)

    def all_mods(self, mod: ModInst | None = None):
        mod = mod or self.root
        yield mod
        for kids in mod.children.values():
            for k in kids:
                yield from self.all_mods(k)

    def block_cfg(self, mod: ModInst, rel: str) -> dict | None:
        if mod.rindex is None:
            mod.rindex = {}
            for r in mod.cfg.get("resources") or []:
                mod.rindex.setdefault(r.get("address"), r)
        return mod.rindex.get(rel)

    def listed(self, mod: ModInst, rel: str, cfg: dict) -> bool:
        """そのブロックを resources に載せるか（リモートのモジュールの中の data と作られないブロックは載せない）。"""
        if not mod.remote:
            return True
        if cfg.get("mode") == "data":
            return False
        return bool(self.by_block.get(mod.prefix + rel)) and not mod.zero

    # ---- 参照の解決
    def resolve(self, mod: ModInst, ref: str, extra: list | None = None, depth: int = 0) -> list[Target]:
        steps = parse_steps(ref)
        if not steps or steps[0][0] != "attr" or depth > 32:
            return []
        steps = steps + list(extra or [])
        head = steps[0][1]
        if head in SKIP_ROOTS:
            return []
        if head == "local":
            if len(steps) > 1:
                self.locals_seen.add(f"{mod.prefix}local.{steps[1][1]}")
            return []
        if head == "var":
            if mod.parent is None or len(steps) < 2:
                return []
            name = steps[1][1]
            expr = (mod.call.get("expressions") or {}).get(name)
            if not isinstance(expr, dict):
                return []
            hop = f"{mod.prefix[:-1]}.var.{name}"
            out = []
            for r in collapse(expr.get("references") or []):
                for t in self.resolve(mod.parent, r, steps[2:], depth + 1):
                    out.append(Target(t.to, t.attr, (hop,) + t.through, t.exact, t.whole))
            return out
        if head == "module":
            if len(steps) < 2:
                return []
            name = steps[1][1]
            rest = steps[2:]
            kids = mod.children.get(name) or []
            if rest and rest[0][0] == "index":
                want = rest[0][1]
                kids = [k for k in kids if self.inst_key(k.prefix[:-1]) == want]
                rest = rest[1:]
            if not rest or rest[0][0] != "attr":
                return []
            out_name = rest[0][1]
            out = []
            for k in kids:
                o = (k.cfg.get("outputs") or {}).get(out_name) or {}
                expr = o.get("expression") or {}
                hop = f"{k.prefix[:-1]}.output.{out_name}"
                for r in collapse(expr.get("references") or []):
                    for t in self.resolve(k, r, rest[1:], depth + 1):
                        out.append(Target(t.to, t.attr, (hop,) + t.through, t.exact, t.whole))
            return out
        if head == "data":
            if len(steps) < 3:
                return []
            rel = f"data.{steps[1][1]}.{steps[2][1]}"
            typ, rest = steps[1][1], steps[3:]
            cfg = self.block_cfg(mod, rel)
            first = next((s[1] for s in rest if s[0] == "attr"), None)
            if cfg is not None and first in PSEUDO_DATA.get(typ, ()) and not cfg.get("expressions"):
                return []  # .tf の $pseudo と同じく参照にしない
            if cfg is not None and typ == "aws_availability_zones" and first == "names":
                return []  # .tf の $az と同じく参照にしない
        else:
            if len(steps) < 2:
                return []
            rel = f"{head}.{steps[1][1]}"
            rest = steps[2:]
            cfg = self.block_cfg(mod, rel)
        if cfg is None or not self.listed(mod, rel, cfg):
            return []
        base = mod.prefix + rel
        insts = self.by_block.get(base, [])
        if rest and rest[0][0] == "index":
            key = rest[0][1]
            attr = rest[1][1] if len(rest) > 1 and rest[1][0] == "attr" else None
            if not insts:
                return [Target(base, attr)]  # 作られないブロック（.tf と同じく添字なし）
            if key == "*":
                return [Target(i.address, attr, exact=False, whole=True) for i in insts]
            a = inst_address(base, key)
            return [Target(a, attr)] if a in self.insts else []
        attr = rest[0][1] if rest and rest[0][0] == "attr" else None
        if insts and any(self.inst_key(i.address) is not None for i in insts):
            return [Target(i.address, attr, exact=False, whole=True) for i in insts]
        return [Target(base, attr)]

    def resolve_all(self, mod: ModInst, refs: list) -> tuple[list[Target], bool]:
        refs = refs if isinstance(refs, list) else []
        dyn = any(isinstance(r, str) and r.split(".")[0] in ("count", "each") for r in refs)
        out: list[Target] = []
        seen: set = set()
        for r in collapse(refs if isinstance(refs, list) else []):
            for t in self.resolve(mod, r):
                if (t.to, t.attr, t.through) not in seen:
                    seen.add((t.to, t.attr, t.through))
                    out.append(t)
        return out, dyn

    # ---- props と参照
    def add_ref(self, frm: str, path: str, t: Target, state: str, fn: str = "ref") -> None:
        r = {"from": frm, "path": path or "depends_on", "to": t.to, "attr": t.attr if fn == "ref" else None,
             "fn": fn, "state": state}
        if t.through:
            r["through"] = list(t.through)
        self.refs.append(r)

    @staticmethod
    def res_marker(t: Target) -> dict:
        m = {"$res": t.to, "attr": t.attr}
        if t.through:
            m["__through"] = list(t.through)
        return m

    def place(self, frm: str, path: str, v, targets: list[Target], dyn: bool, created: bool):
        """1つの式の値 v に参照を置く（7.3 の plan JSON の参照）。置いた値を返す。"""
        if not targets:
            return v
        if not created:
            v = UNK  # 作られないブロックは値が無い（.tf と同じく、参照は $res のまま残す）
        if v is UNK:
            if not dyn and len(targets) == 1 and targets[0].exact:
                return self.res_marker(targets[0])
            if not dyn and any(t.whole for t in targets):
                return [self.res_marker(t) for t in targets]
            for t in targets:
                self.add_ref(frm, path, t, "unevaluated")
            return v
        unk = mark_paths(v, path, UNK)
        if unk:
            if not dyn and len(unk) == len(targets) and all(t.exact for t in targets):
                for (p, rel), t in zip(unk, targets):
                    v = set_at(v, rel, self.res_marker(t))
                return v
            if not dyn and len(unk) == 1 and targets and all(t.whole for t in targets):
                return set_at(v, unk[0][1], [self.res_marker(t) for t in targets])
            for t in targets:
                self.add_ref(frm, path, t, "unevaluated")
            return v
        if v is ABSENT or v is None:
            for t in targets:
                self.add_ref(frm, path, t, "pruned")  # 値が null（条件で選ばれなかった）
            return v
        for t in targets:
            tv = self.insts[t.to].value_of(t.attr) if t.to in self.insts else ABSENT
            done = False
            if tv is not ABSENT and conv(tv) == v and not isinstance(tv, bool):
                v = self.res_marker(t)  # 値がそのまま先の属性の値（JSON の文字列は $json どうしで比べる）
                continue
            if isinstance(tv, (str, int, float)) and not isinstance(tv, bool):
                tv_s = str(tv)
                for p, rel, s in string_paths(v, path):
                    if s == tv_s:
                        v = set_at(v, rel, self.res_marker(t))
                        done = True
                        break
                    if len(tv_s) >= 3 and tv_s in s:
                        pieces = s.split(tv_s)
                        parts = []
                        for i, piece in enumerate(pieces):
                            if i:
                                parts.append(self.res_marker(t))
                            parts.append(piece)
                        v = set_at(v, rel, ir_raw.normalize_concat(parts))
                        done = True
                        break
            if not done:
                self.add_ref(frm, path, t, "unevaluated")
        return v

    def body(self, frm: str, mod: ModInst, exprs: dict, after, unknown, sens, path: str, created: bool) -> dict:
        out: dict = {}
        a = after if isinstance(after, dict) else {}
        u = unknown if isinstance(unknown, dict) else {}
        s = sens if isinstance(sens, dict) else {}
        sg = (lambda _k: True) if sens is True else s.get  # sens が true: すべての属性が sensitive
        for k in exprs:
            e = exprs[k]
            p = ir_raw.join_path(path, k)
            if isinstance(e, list):  # 入れ子のブロック
                if sg(k) is True:  # ブロックの全体が sensitive: 中の値は使わない
                    for be in e:
                        for t in self.resolve_all(mod, all_refs(be))[0]:
                            self.add_ref(frm, p, t, "unevaluated")
                    out[("$" + k) if k.startswith("$") else k] = SENS
                    continue
                vals = a.get(k) if isinstance(a.get(k), list) else []
                us = u.get(k) if isinstance(u.get(k), list) else []
                ss = s.get(k) if isinstance(s.get(k), list) else []
                blocks = []
                n = len(vals) if created else len(e)
                for i in range(n):
                    be = e[i] if i < len(e) else (e[-1] if e else {})
                    if not isinstance(be, dict):
                        continue
                    blocks.append(self.body(frm, mod, be, vals[i] if i < len(vals) else None,
                                            us[i] if i < len(us) else None, ss[i] if i < len(ss) else None,
                                            ir_raw.join_path(p, i), created))
                if blocks:
                    out[k] = blocks
                elif e and created:
                    for be in e:
                        for t in self.resolve_all(mod, all_refs(be))[0]:
                            self.add_ref(frm, p, t, "pruned")  # ブロックが無い（dynamic の空など）
                continue
            if not isinstance(e, dict):
                continue
            if created:
                v = conv(a.get(k), u.get(k), sg(k))
            else:  # 作られない（destroy の plan のものは、消す前の sensitive の印で伏せる）
                v = conv(e["constant_value"], None, sg(k)) if "constant_value" in e else ABSENT
            targets, dyn = self.resolve_all(mod, e.get("references") or [])
            v = self.place(frm, p, v, targets, dyn, created) if targets else v
            if v is ABSENT or v is None or (v is UNK and not created):
                continue  # 作られないブロックの、参照を置けなかった値は書かない（値が無い）
            out[("$" + k) if k.startswith("$") else k] = v
        if created:
            for k, x in a.items():  # 設定に無い入れ子のブロック（dynamic ブロック。plan JSON の設定に現れない）
                if k in exprs or not (isinstance(x, list) and x and all(isinstance(y, dict) for y in x)):
                    continue
                if path == "" and k in ("timeouts",):
                    continue
                v = conv(x, u.get(k), sg(k))
                if v and v is not ABSENT:
                    out[("$" + k) if k.startswith("$") else k] = v
                    self.diag("info", "TF-PLAN-DYNAMIC-BLOCK", frm, ir_raw.join_path(path, k),
                              "block that is not in the plan's configuration (a dynamic block, or a block the "
                              "provider fills); references in it are not known from the plan JSON")
        return out

    def diag(self, level, code, address, path, message) -> None:
        self.diagnostics.append({"level": level, "code": code, "address": address, "path": path,
                                 "message": message})

    # ---- provider と region
    def provider_of(self, mod: ModInst, cfg: dict, inst: Inst | None):
        key = (inst.provider_key if inst and inst.provider_key else None) or cfg.get("provider_config_key") or ""
        name = key.split(":", 1)[1] if ":" in key else key
        conf = self.provider_config.get(key) or {}
        in_module = ":" in key
        provider = name if "." in name else None
        after_region = None
        if inst and isinstance(inst.after, dict) and isinstance(inst.after.get("region"), str) \
                and cfg.get("type", "").startswith("aws_"):
            after_region = inst.after["region"]  # AWS provider v6 は、すべてのリソースの region を埋める
        region = None
        if provider or in_module:
            region = after_region or self.config_region(conf, in_module)
        elif "region" in (cfg.get("expressions") or {}):
            # リソースの引数 region（v6）。null を渡したもの（モジュールの region = var.region など）は、after では
            # 既定のリージョンが入るので、既定と違うときと、定数で書いたときだけ書く（.tf と同じ）
            e = cfg["expressions"]["region"]
            if isinstance(e, dict) and isinstance(e.get("constant_value"), str):
                region = e["constant_value"]
            elif after_region and after_region != self.config_region(self.provider_config.get("aws") or {}, False):
                region = after_region
        return provider, region

    def config_region(self, conf: dict, in_module: bool) -> str | None:
        """provider の設定の region（定数か、ルートの変数）。"""
        e = (conf.get("expressions") or {}).get("region") or {}
        if isinstance(e.get("constant_value"), str):
            return e["constant_value"]
        refs = collapse(e.get("references") or [])
        if not in_module and len(refs) == 1 and refs[0].startswith("var.") \
                and isinstance(self.root_vars.get(refs[0][4:]), str):
            return self.root_vars[refs[0][4:]]
        return None

    # ---- 書き出し
    def run(self) -> None:
        mods = list(self.all_mods())
        for mod in mods:
            for cfg in mod.cfg.get("resources") or []:
                rel = cfg.get("address")
                if not rel or not self.listed(mod, rel, cfg):
                    continue
                base = mod.prefix + rel
                insts = [] if mod.zero else self.by_block.get(base, [])
                if insts:
                    for inst in insts:
                        self.emit(mod, cfg, inst.address, inst, True)
                else:
                    self.emit(mod, cfg, base, None, False)
        known = {r["address"] for r in self.resources}
        self.res_by_block = {}
        self.res_by_module = {}
        for r in self.resources:  # 以下で何度も引くので、一度だけ表にする
            self.res_by_block.setdefault(block_address(r["address"]), []).append(r["address"])
            self.res_by_module.setdefault(r.get("module", ""), []).append(r["address"])
        self.res_sorted = sorted(known)
        for mod in mods:  # depends_on（モジュールの呼び出しのものは中のすべてのリソースへ）
            for cfg in mod.cfg.get("resources") or []:
                addrs = self.res_by_block.get(mod.prefix + cfg.get("address", ""), [])
                if not addrs or not cfg.get("depends_on"):
                    continue
                targets = self.depends_targets(mod, cfg.get("depends_on") or [])
                for a in addrs:
                    for t in targets:
                        self.add_ref(a, "depends_on", Target(t, None), "active", "depends_on")
            inherited = []
            m = mod
            while m.parent is not None:
                inherited += self.depends_targets(m.parent, m.call.get("depends_on") or [])
                m = m.parent
            if inherited:
                for a in self.res_by_module.get(mod.prefix[:-1], []):
                    for t in inherited:
                        self.add_ref(a, "depends_on", Target(t, None), "active", "depends_on")
        self.refs = [r for r in self.refs if r["from"] in known and r["to"] in known]
        if self.locals_seen:
            self.diag("info", "TF-PLAN-LOCALS", "", "",
                      f"the plan JSON has no expressions for local values; references through "
                      f"{len(self.locals_seen)} local value(s) are not known (pass the .tf folder with --input to "
                      "read them)")
        if self.deleted:
            if self.destroy_plan:
                self.diag("warn", "TF-PLAN-DESTROY", "", "",
                          f"this is a destroy plan (every resource change is a delete): {len(self.deleted)} "
                          "resource(s) will be destroyed; resources still in the configuration are written as "
                          "not created (enabled: false)")
            else:
                self.diag("info", "TF-PLAN-DESTROY", "", "",
                          f"{len(self.deleted)} resource(s) will be destroyed or forgotten by this plan; they are "
                          "not drawn as created")
        if self.plan.get("errored"):
            self.diag("warn", "TF-PLAN-ERRORED", "", "", "the plan failed (errored: true); the plan may be partial")
        elif self.plan.get("complete") is False:
            self.diag("warn", "TF-PLAN-INCOMPLETE", "", "",
                      "the plan is not complete (complete: false, e.g. deferred changes or -target)")
        if self.plan.get("deferred_changes"):
            self.diag("warn", "TF-PLAN-INCOMPLETE", "", "deferred_changes",
                      f"{len(self.plan['deferred_changes'])} change(s) are deferred and not in the plan")

    def depends_targets(self, mod: ModInst, items: list) -> list[str]:
        out = []
        for d in items:
            steps = parse_steps(d) if isinstance(d, str) else []
            if len(steps) >= 2 and steps[0] == ("attr", "module"):
                pre = f"{mod.prefix}module.{steps[1][1]}"
                out += list(prefixed(self.res_sorted, pre + ".")) + list(prefixed(self.res_sorted, pre + "["))
            elif steps:
                base = mod.prefix + ".".join(s[1] for s in steps[:3 if steps[0] == ("attr", "data") else 2])
                out += self.res_by_block.get(base, [])
        return sorted(set(out))

    def emit(self, mod: ModInst, cfg: dict, address: str, inst: Inst | None, created: bool) -> None:
        if address in self.emitted:
            return
        self.emitted.add(address)
        entry = {"address": address, "type": cfg.get("type", inst.type if inst else ""), "file": self.file,
                 "enabled": created}
        if mod.prefix:
            entry["module"] = mod.prefix[:-1]
        provider, region = self.provider_of(mod, cfg, inst)
        if provider:
            entry["provider"] = provider
        if region:
            entry["region"] = region
        exprs = cfg.get("expressions") or {}
        sens = inst.sens if inst else self.deleted_sens.get(block_address(address))
        props = self.body(address, mod, exprs, inst.after if inst else None, inst.unknown if inst else None,
                          sens, "", created)
        for p in leaves(props, "", [], SENS):
            self.diag("info", "TF-PLAN-SENSITIVE", address, p, "sensitive value in the plan; not used")
        for p in leaves(props, "", [], UNK):
            self.diag("info", "TF-PLAN-UNKNOWN", address, p, "value is known only after apply")
        entry["props"] = collect(finish(props), address, self.refs)
        self.resources.append(entry)

    def module_vars(self) -> dict:
        out = {}
        for mod in self.all_mods():
            if mod.parent is None or mod.remote:
                continue
            given = mod.call.get("expressions") or {}
            for name, spec in sorted((mod.cfg.get("variables") or {}).items()):
                spec = spec or {}
                src = "argument" if name in given else "default" if "default" in spec else None
                e = {"source": src}
                if spec.get("sensitive"):
                    e["hidden"] = "sensitive"
                elif spec.get("ephemeral"):
                    e["hidden"] = "ephemeral"
                out[f"{mod.prefix}{name}"] = e
        return out


def all_refs(be) -> list:
    out = []
    if isinstance(be, dict):
        if "references" in be and isinstance(be["references"], list):
            out += be["references"]
        for k, v in be.items():
            if k not in ("references", "constant_value"):
                out += all_refs(v)
    elif isinstance(be, list):
        for x in be:
            out += all_refs(x)
    return out


def collect(props, frm: str, out: list[dict]):
    """props の中の $res を active の参照にし、__through を参照の through に移した props を返す。"""
    def strip(v, path):
        if isinstance(v, list):
            return [strip(x, ir_raw.join_path(path, i)) for i, x in enumerate(v)]
        if isinstance(v, dict):
            if "$res" in v:
                ref = {"from": frm, "path": path, "to": v["$res"], "attr": v.get("attr"), "fn": "ref",
                       "state": "active"}
                if v.get("__through"):
                    ref["through"] = list(v["__through"])
                out.append(ref)
                return {"$res": v["$res"], "attr": v.get("attr")}
            if "$concat" in v:
                return {"$concat": [strip(x, path) if isinstance(x, dict) else x for x in v["$concat"]]}
            if "$json" in v:
                return {"$json": strip(v["$json"], path)}
            if ir_raw.is_marker(v):
                return v
            return {k: strip(x, ir_raw.join_path(path, ir_raw.unescape_key(k))) for k, x in v.items()}
        return v
    return strip(props, "")


def dedupe(refs: list[dict]) -> list[dict]:
    rank = {"active": 2, "unevaluated": 1, "pruned": 0}
    seen: dict[tuple, dict] = {}
    for r in refs:
        key = ir_raw.ref_key(r)
        if key not in seen or rank[r["state"]] > rank[seen[key]["state"]]:
            seen[key] = r
    return list(seen.values())


def assumption(plan: dict) -> str:
    return (f"read from a terraform plan JSON (terraform {_version(plan.get('terraform_version'))}, format "
            f"{_version(plan.get('format_version'))}); addresses, count/for_each and values are Terraform's")


def root_text(path: Path, root_base: Path) -> tuple[str, bool]:
    """raw IR の root（root_base からの相対パス）。ドライブが違うときは相対パスにできないので、名前だけ
    （絶対パスは書かない）。plan だけのときも .tf と合わせるときも同じ規則。2つ目は相対パスにできたか。"""
    try:
        return Path(os.path.relpath(path.resolve(), root_base.resolve())).as_posix(), True
    except ValueError:  # Windows でドライブが違う
        return path.resolve().name or ".", False


ROOT_OTHER_DRIVE_MESSAGE = "root is on another drive; written as the file or folder name only"


def read_plan(plan: dict, file_name: str) -> "PlanReader":
    """PlanReader を作って読み込む。想定外の形は PlanError にする（値や絶対パスは書かない）。"""
    try:
        reader = PlanReader(plan, file_name)
        reader.run()
        return reader
    except PlanError:
        raise
    except RecursionError as e:
        raise PlanError("入れ子が深すぎます") from e
    except (KeyError, TypeError, AttributeError, IndexError, ValueError) as e:
        raise PlanError(f"unexpected structure in the plan JSON ({type(e).__name__})") from e


def build_plan_raw(plan_path: Path, root_base: Path | None = None) -> dict:
    """plan JSON だけから raw IR を作る（--input <plan JSON>）。"""
    plan = load_plan(plan_path)
    reader = read_plan(plan, plan_path.name)
    root, relative = root_text(plan_path, root_base or Path.cwd())
    if not relative:
        reader.diag("info", "TF-ROOT-OTHER-DRIVE", "", "", ROOT_OTHER_DRIVE_MESSAGE)
    root_cfg = (plan.get("configuration") or {}).get("root_module") or {}
    vars_ = {}
    for name, spec in sorted((root_cfg.get("variables") or {}).items()):
        spec = spec or {}
        e = {"source": "plan" if name in reader.root_vars else ("default" if "default" in spec else None)}
        if spec.get("sensitive"):
            e["hidden"] = "sensitive"
        elif spec.get("ephemeral"):
            e["hidden"] = "ephemeral"
        vars_[name] = e
    vars_.update(reader.module_vars())
    diagnostics = list({ir_raw.diag_key(d) + (d["message"],): d for d in reader.diagnostics}.values())
    known = {r["address"] for r in reader.resources}
    for r in reader.resources:
        r["props"] = _drop_missing(r["props"], known)
    raw = {
        "ir_version": "1.0", "stage": "raw", "format": "tf", "root": root,
        "evaluation": {"var_files": [], "vars": dict(sorted(vars_.items())), "assumptions": [assumption(plan)]},
        "resources": reader.resources,
        "references": dedupe(_props_consistent(reader.resources, reader.refs)),
        "diagnostics": diagnostics,
    }
    return ir_raw.canonical_raw(raw)


def plan_variables(plan: dict) -> dict:
    """ルートの変数の値（plan の variables）。.tf と合わせるときに --var の代わりに渡す。"""
    return {k: (v or {}).get("value") for k, v in (plan.get("variables") or {}).items()}


# ------------------------------------------------------------------ .tf の raw IR と合わせる

def _walk_fill(tv, pv, pu, ps, path: str, fill_paths: set, filled: list):
    """.tf の値 tv の $unknown のうち、fill_paths にある位置を plan の値で埋める。"""
    if isinstance(tv, dict) and set(tv) == {"$unknown"}:
        if path in fill_paths and pu is not True and ps is not True and not has_true(ps) and not has_true(pu) \
                and pv is not None:
            filled.append(path)
            return finish(conv(pv))
        return tv
    if isinstance(tv, dict) and "$json" in tv and len(tv) == 1:
        if ps is True or has_true(ps) or pu is True or has_true(pu):
            return tv  # JSON の文字列の全体が sensitive・known after apply: 中の位置も plan の値で埋めない
        if isinstance(pv, str):
            try:
                inner = json.loads(pv)
            except (ValueError, RecursionError):
                return tv
            return {"$json": _walk_fill(tv["$json"], inner, None, None, path, fill_paths, filled)}
        return tv
    if isinstance(tv, dict) and "$concat" in tv:
        if path in fill_paths and isinstance(pv, str) and pu is not True and ps is not True \
                and not has_true(ps) and not any(isinstance(x, dict) and "$res" in x for x in tv["$concat"]):
            filled.append(path)
            return ir_raw.maybe_json(pv)
        return tv
    if isinstance(tv, list):
        pl = pv if isinstance(pv, list) else []
        ul = pu if isinstance(pu, list) else []
        sl = ps if isinstance(ps, list) else []
        return [_walk_fill(x, pl[i] if i < len(pl) else None, ul[i] if i < len(ul) else None,
                           True if ps is True else sl[i] if i < len(sl) else None, ir_raw.join_path(path, i),
                           fill_paths, filled)
                for i, x in enumerate(tv)]
    if isinstance(tv, dict) and not ir_raw.is_marker(tv):
        pd = pv if isinstance(pv, dict) else {}
        ud = pu if isinstance(pu, dict) else {}
        sd = ps if isinstance(ps, dict) else {}
        out = {}
        for k, x in tv.items():
            uk = ir_raw.unescape_key(k)
            out[k] = _walk_fill(x, pd.get(uk), ud.get(uk), True if ps is True else sd.get(uk),
                                ir_raw.join_path(path, uk), fill_paths, filled)
        return out
    return tv


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


def _diag(code: str, address: str, path: str, message: str) -> dict:
    return {"level": "info", "code": code, "address": address, "path": path, "message": message}


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


def _tfjson_files(reader: PlanReader, input_dir: Path) -> dict:
    """.tf.json に書かれたブロックの address（インスタンスの添字なし）→ file（ルートとローカルモジュール）。

    plan の source で決まるフォルダのうち、--input のフォルダの外にあるものは読まない。
    """
    out = {}
    try:
        top = input_dir.resolve()
    except OSError:
        return out
    outside = 0
    for mod in reader.all_mods():
        if mod.remote or mod.dir is None:
            continue
        d = (input_dir / mod.dir)
        try:
            if not d.is_dir():
                continue
            if not d.resolve().is_relative_to(top):
                outside += 1
                continue
        except (OSError, ValueError):
            continue
        for f in sorted(d.glob("*.tf.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, ValueError, RecursionError):
                continue
            rel = Path(os.path.relpath(f, input_dir)).as_posix()
            for kind, prefix in (("resource", ""), ("data", "data.")):
                blocks = doc.get(kind) if isinstance(doc, dict) else None
                items = blocks if isinstance(blocks, list) else [blocks] if isinstance(blocks, dict) else []
                for it in items:
                    for typ, names in (it or {}).items():
                        for nm in (names if isinstance(names, dict) else {}):
                            out[f"{mod.prefix}{prefix}{typ}.{nm}"] = rel
    if outside:
        reader.diag("info", "TF-PLAN-PATH-OUTSIDE", "", "",
                    f"{outside} local module folder(s) are outside the --input folder; their .tf.json files are "
                    "not looked up")
    return out


def combine(tf_raw: dict, plan_path: Path, input_dir: Path, root_base: Path | None = None,
            plan: dict | None = None) -> dict:
    """.tf の raw IR（tf_raw）と plan JSON を合わせる（7.2 の「TF の plan JSON」の .tf と合わせるとき）。

    plan: 読み込み済みの plan JSON（build_raw が変数の値のために読んだもの。無ければ plan_path から読む）。
    """
    plan = plan if plan is not None else load_plan(plan_path)
    reader = read_plan(plan, plan_path.name)
    p_res = {r["address"]: r for r in reader.resources}
    t_res = {r["address"]: r for r in tf_raw["resources"]}
    t_file_by_block: dict = {}
    for r in tf_raw["resources"]:
        t_file_by_block.setdefault(block_address(r["address"]).replace("[*]", ""), r["file"])
    t_file_by_module: dict = {}
    for r in tf_raw["resources"]:
        if r.get("module"):
            t_file_by_module.setdefault(r["module"], r["file"])
        if r["type"] == "module":
            t_file_by_module.setdefault(r["address"], r["file"])
    tfjson = _tfjson_files(reader, input_dir)
    diags_t = [d for d in tf_raw["diagnostics"]]
    fillable: dict = {}  # address → 値が決まらないことによる診断の位置（plan の値で埋めてよい位置）
    for d in diags_t:
        if d.get("address") and d["code"] in FILLABLE:
            fillable.setdefault(d["address"], set()).add(d.get("path", ""))
    out_res: list[dict] = []
    from_tf: set = set()
    filled_paths: dict = {}
    sens_diags: list[dict] = []
    masked_paths: dict = {}  # address → 伏せた位置（.tf の診断の文に値が入りうるので、その下の診断は消す）
    for a, pr in sorted(p_res.items()):
        tr = t_res.get(a)
        if tr is not None and tr["type"] == pr["type"]:
            e = json.loads(json.dumps(tr))
            e["enabled"] = pr["enabled"]
            e.pop("multiplicity", None)
            inst = reader.insts.get(a)
            masked: list = []
            if inst is not None:
                if pr["enabled"]:
                    filled: list = []
                    e["props"] = _walk_fill(e["props"], inst.after, inst.unknown, inst.sens, "",
                                            fillable.get(a, set()), filled)
                    filled_paths[a] = set(filled)
                # .tf の評価は plan の変数の値を使うので、sensitive と宣言していない変数が provider の sensitive の
                # 属性に入っていることがある。plan が sensitive とした位置は、.tf の値も必ず伏せる
                found: list = []
                e["props"] = mask_props(e["props"], inst.sens, found)
                masked += found
                sens_diags += [_diag("TF-PLAN-SENSITIVE", a, path, "sensitive value in the plan; not used")
                               for path in found]
            if not pr["enabled"]:
                # 作られないリソース（count 0・destroy の plan）: 消す前の sensitive の印があれば伏せ、そのうえで、
                # plan の変数から来た値は使わない（リテラルの値だけ残す）
                lit: list = []
                e["props"] = literal_only(e["props"], pr["props"], "", lit)
                found = []
                flags = reader.deleted_sens.get(block_address(a))
                if flags is not None:
                    e["props"] = mask_props(e["props"], flags, found)
                masked += lit + found
                sens_diags += [_diag("TF-PLAN-SENSITIVE", a, path, "sensitive value in the plan; not used")
                               for path in found]
                sens_diags += [_diag("TF-PLAN-LITERAL-ONLY", a, path,
                                     "the resource is not created; a value that is not a literal is not taken from "
                                     "the plan variables") for path in lit if path not in found]
            if masked:
                masked_paths[a] = masked
            out_res.append(e)
            from_tf.add(a)
            continue
        e = json.loads(json.dumps(pr))
        b = block_address(a)
        mod_file = None
        m = pr.get("module")
        while m:  # モジュールの中なら、そのモジュール（無ければ外側の呼び出し）の .tf のファイル
            if m in t_file_by_module:
                mod_file = t_file_by_module[m]
                break
            m = m.rsplit(".module.", 1)[0] if ".module." in m else None
        e["file"] = tfjson.get(b) or t_file_by_block.get(b) or mod_file or reader.file
        out_res.append(e)
    final = {r["address"] for r in out_res}
    final_by_block: dict = {}
    for x in sorted(final):
        final_by_block.setdefault(block_address(x), []).append(x)

    def expand(to: str) -> list[str]:
        if to in final:
            return [to]
        if to.endswith("[*]"):
            return final_by_block.get(to[:-3], [])
        return []

    refs: list[dict] = []
    t_pairs: dict = {}
    for r in tf_raw["references"]:
        if r["from"] not in from_tf:
            continue
        for to in expand(r["to"]):
            n = dict(r, to=to)
            if to != r["to"] and n["state"] == "active" and n["fn"] == "ref":  # depends_on は active のまま
                n["state"] = "unevaluated"
            refs.append(n)
            t_pairs.setdefault(r["from"], set()).add(block_address(to))
    # .tf の props の $res の先が無くなったもの（×N の [*] や黒箱の呼び出し）は $unknown にする
    for e in out_res:
        if e["address"] not in from_tf:
            continue
        e["props"] = _drop_missing(e["props"], final)
    for r in reader.refs:
        if r["from"] in from_tf:
            # configuration の参照を優先する: .tf の参照に無い組（from とブロック）は足す
            if block_address(r["to"]) in t_pairs.get(r["from"], set()):
                continue
            n = dict(r)
            if n["state"] == "active" and n["fn"] == "ref":
                n["state"] = "unevaluated"
            refs.append(n)
            reader.diag("info", "TF-PLAN-EXTRA-REF", r["from"], r["path"],
                        f"reference to {r['to']} is in the plan's configuration but not found in the .tf; "
                        "added as unevaluated")
            continue
        refs.append(r)
    diagnostics = []
    for d in diags_t:
        a = d.get("address", "")
        if a and a not in final:
            continue
        if a in filled_paths and d.get("path", "") in filled_paths[a] and d["code"] in FILLABLE:
            continue
        if d["code"] == "TF-TFJSON-UNSUPPORTED":
            d = dict(d, level="info", message=d["message"] + "; its blocks are taken from the plan JSON")
        if d["code"] == "TF-UNRESOLVED-VARS":
            continue
        if a in masked_paths and under_any(masked_paths[a], d.get("path", "")):
            continue
        diagnostics.append(d)
    for d in reader.diagnostics:
        if d["code"] == "TF-PLAN-LOCALS":
            continue  # locals は .tf で読んでいる
        a = d.get("address", "")
        if a and a in from_tf and d["code"] in ("TF-PLAN-UNKNOWN", "TF-PLAN-DYNAMIC-BLOCK", "TF-PLAN-SENSITIVE"):
            continue  # 値と参照の位置は .tf のもの
        diagnostics.append(d)
    diagnostics += sens_diags
    mismatch = _mismatch(tf_raw["resources"], p_res)
    if mismatch:
        diagnostics.append({"level": "warn", "code": "TF-PLAN-MISMATCH", "address": "", "path": "",
                            "message": mismatch + "; the plan and the .tf folder probably do not match"})
    dropped = sorted(a for a in t_res if a not in final)
    if dropped:
        diagnostics.append({"level": "info", "code": "TF-PLAN-NOT-PLANNED", "address": "", "path": "",
                            "message": f"{len(dropped)} resource(s) read from the .tf are not in the plan and are "
                                       f"not written: {', '.join(dropped[:20])}" + (" …" if len(dropped) > 20 else "")})
    ev = json.loads(json.dumps(tf_raw["evaluation"]))
    ev.setdefault("assumptions", []).append(assumption(plan) + "; file, props and reference positions are from the .tf")
    raw = dict(tf_raw, evaluation=ev, resources=out_res, references=dedupe(_props_consistent(out_res, refs)),
               diagnostics=list({ir_raw.diag_key(d) + (d["message"],): d for d in diagnostics}.values()))
    return ir_raw.canonical_raw(raw)


_INSTANCE_KEYS = re.compile(r'\[(?:\d+|\*|"(?:[^"\\]|\\.)*")\]')


def _mismatch(tf_resources: list[dict], p_res: dict) -> str:
    """plan のブロックと .tf のブロックの食い違いが大きいとき（3割を超える）、その説明。無ければ ""。

    添字は無視して、ブロックで比べる。.tf の黒箱のモジュールの中のブロックは、.tf に無くて当然なので数えない。
    """
    blackbox = [_INSTANCE_KEYS.sub("", r["address"]) for r in tf_resources if r["type"] == "module"]
    tk = {_INSTANCE_KEYS.sub("", r["address"]) for r in tf_resources if r["type"] != "module"}
    pk = {_INSTANCE_KEYS.sub("", a) for a in p_res}
    pk = {x for x in pk if not any(x.startswith(b + ".") for b in blackbox)}
    only_plan, only_tf = pk - tk, tk - pk
    parts = []
    if pk and len(only_plan) * 10 > len(pk) * 3:
        parts.append(f"{len(only_plan)} of {len(pk)} resource block(s) in the plan are not in the .tf folder")
    if tk and len(only_tf) * 10 > len(tk) * 3:
        parts.append(f"{len(only_tf)} of {len(tk)} resource block(s) in the .tf folder are not in the plan")
    return "; ".join(parts)


def _drop_missing(v, final: set):
    if isinstance(v, list):
        return [_drop_missing(x, final) for x in v]
    if isinstance(v, dict):
        if "$res" in v:
            return v if v["$res"] in final else {"$unknown": f"{v['$res']} is not in the plan"}
        if "$concat" in v:
            return ir_raw.normalize_concat([_drop_missing(x, final) if isinstance(x, dict) else x
                                            for x in v["$concat"]])
        if "$json" in v:
            return {"$json": _drop_missing(v["$json"], final)}
        if ir_raw.is_marker(v):
            return v
        return {k: _drop_missing(x, final) for k, x in v.items()}
    return v


def _props_consistent(resources: list[dict], refs: list[dict]) -> list[dict]:
    """active の参照を props の $res と1対1にそろえる（props に無い active は unevaluated にする）。"""
    have = set()
    for r in resources:
        for path, to, attr in ir_raw.iter_res(r["props"], ""):
            have.add((r["address"], path, to, attr))
    out = []
    for r in refs:
        if r["state"] == "active" and r["fn"] == "ref" and (r["from"], r["path"], r["to"], r["attr"]) not in have:
            r = dict(r, state="unevaluated")
        out.append(r)
    return out
