"""規則表（`data/rules/`）の読み込み・索引・検査。

規則表は TOML（標準ライブラリの `tomllib` だけで読む）で、領域別のファイルに分けてある。説明の文章（なぜそうするか）は
リポジトリの `docs/spec/rules/`（SKILL の外）にあり、そこの表は `aws-iac-diagram-workspace/tools/render_rules.py` が、ここで読むデータから作る。

  data/rules/types/*.toml   [[type]]      型の扱い: 描く型（drawn）・統合（M-*。merged_into）・非表示（H-*。hidden）
  data/rules/relations.toml [[relation]]  関係リソース（R-*）: 2 つのリソースを結ぶだけの型を辺に変える
  data/rules/edges.toml     [[edge]] ほか 確信度、辺の規則（E-*）、kind の対応表、まとめ方の優先順、合成ノード（N-*）、ラベルの書式
  data/rules/refs.toml      [[noedge]] [[nonode]]  辺にしない参照（E-NOEDGE-*）、参照先にノードが無い参照（E-REF-NONODE）
  data/rules/placement.toml [[placement]] [[attr]] 入れ子（N-AZ・P-*）と attrs の取り方

読む順は決まっている（`types/` の中は名前の昇順、ほかは固定の名前、行は書いた順）。ディレクトリの列挙の順や OS には依らない。
決まりに合わないデータ（TOML として読めない、ID の重複、未知のフィールド、必須の列が無い、型の重複、`class` と接頭辞の不整合、
存在しない ID や型への参照など）は、読み込みのときにすべて `RulesError` にする（検査を通ったデータだけが使える）。

ここは標準ライブラリと core 自身（paths）だけを使う（core の決まり）。`validate_ir.py`（と将来の `normalize/`）が同じ関数を使い、
規則表を 2 か所で読まない。
"""
from __future__ import annotations

import fnmatch
import functools
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from aws_iac_diagram.core import paths

# 規則 ID（`H-IAM`・`R-LB-TG`・`E-NOEDGE-SG` など）と、描く型の正規の型名（`alb`・`subnet`。ノードの id の接頭辞と同じ）
RULE_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
TYPE_ID = re.compile(r"^[a-z0-9_]+$")  # ir.schema.json の type と同じ
TF_TYPE = re.compile(r"^[a-z][a-z0-9_]*\*?$")  # `aws_vpc`、`random_*`
CFN_TYPE = re.compile(r"^AWS::[A-Za-z0-9]+::[A-Za-z0-9]+$")

# class → 規則 ID の接頭辞（validate_ir.py が「class と規則の接頭辞」の検査に使う）
CLASS_PREFIX = {"hidden": ("H-",), "merged_into": ("M-", "R-")}
CLASSES = ("drawn", "merged_into", "hidden")
CATEGORIES = ("resource", "group", "external")  # ir.schema.json の category
KINDS = ("request", "event", "data", "route", "network")  # ir.schema.json の edge の kind
CONFIDENCES = ("confirmed", "derived", "inferred")
VIA_VALUES = ("nested_stack", "module_summary", "module_blackbox")  # ir-raw.schema.json の via
KIND_TABLES = ("kind_by_target", "iam_action_kind", "merge_priority")  # [[edge]] の kind_by が指せる表
FROM_CLASSES = ("merged_into", "hidden")

# 規則 ID の接頭辞 → 表（どの表の行がどの接頭辞を持つか）
TABLE_PREFIX = {"type:merged_into": ("M-",), "type:hidden": ("H-",), "relation": ("R-",), "edge": ("E-",), "noedge": ("E-",),
                "nonode": ("E-",), "synthetic": ("N-",), "placement": ("N-", "P-")}

TYPES_DIR_NAME = "types"
FIXED_FILES = ("relations.toml", "edges.toml", "refs.toml", "placement.toml")
ALLOWED_ROOT_NAMES = frozenset({TYPES_DIR_NAME, "README.md", *FIXED_FILES})

EDGES_TOP_LEVEL = {"confidence_order", "iam_action_priority", "iam_action_default"}
FILE_TABLES = {  # ファイル（types/ の中は共通）→ 置いてよい表
    "types": {"type"},
    "relations.toml": {"relation"},
    "edges.toml": {"confidence", "edge", "kind_by_target", "iam_action_kind", "merge_priority", "synthetic", "label_format"},
    "refs.toml": {"noedge", "nonode"},
    "placement.toml": {"placement", "attr"},
}


class RulesError(Exception):
    """規則データの読み込み・検査の失敗。`problems` に 1 件ずつの文がある（メッセージはその連結）。"""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("規則表（data/rules/）に問題があります:\n" + "\n".join(f"  - {p}" for p in self.problems))


def neutral_key(name: str) -> str:
    """TF の snake_case と CFN の CamelCase を同じ名前にそろえる中立キー（小文字にして `_` を除く。`vpc_id` と `VpcId` は `vpcid`）。"""
    return name.lower().replace("_", "")


# ------------------------------------------------------------------ 列の型の検査

def _is_str(v) -> bool:
    return isinstance(v, str)


def _is_nonempty_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _is_strs(v) -> bool:  # 空でない文字列の配列（空の配列も可）
    return isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v)


def _is_strs1(v) -> bool:  # 1 つ以上
    return _is_strs(v) and len(v) > 0


def _is_bool(v) -> bool:
    return isinstance(v, bool)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_str_table(v) -> bool:
    return isinstance(v, dict) and all(isinstance(k, str) and isinstance(x, str) for k, x in v.items())


CHECKS = {"str": _is_str, "text": _is_nonempty_str, "strs": _is_strs, "strs1": _is_strs1, "bool": _is_bool, "int": _is_int}
KIND_NAMES = {"str": "文字列", "text": "空でない文字列", "strs": "文字列の配列", "strs1": "1 つ以上の文字列の配列", "bool": "true／false", "int": "整数"}

# 表ごとの列: 名前 → (型, 必須か)
TYPE_COMMON = {"id": ("text", True), "class": ("text", True), "tf": ("strs", True), "cfn": ("strs", True),
               "tf_note": ("text", False), "cfn_note": ("text", False)}  # when は別に検査
TYPE_BY_CLASS = {
    "drawn": {"category": ("text", True), "name_attr": ("name_attr", True), "icon": ("strs1", True), "synthetic": ("text", False),
              "name_from": ("text", False), "icon_note": ("text", False), "data": ("bool", False)},
    "merged_into": {"into": ("into", True), "reason": ("text", True), "refs_as_target": ("bool", False)},
    "hidden": {"applies": ("text", True), "reason": ("text", True), "tf_data": ("strs", False), "data_block": ("bool", False),
              "evidence_source": ("bool", False), "module_sources_file": ("text", False)},
}
RELATION = {"id": ("text", True), "class": ("text", True), "tf": ("strs", True), "cfn": ("strs", True), "tf_props": ("strs", False),
            "cfn_props": ("strs", False), "sam": ("strs", False), "tf_note": ("text", False), "cfn_note": ("text", False),
            "edge": ("text", True), "kind": ("str", True), "kind_note": ("text", False), "label": ("str", True),
            "confidence": ("text", True), "fallback": ("text", False)}
OTHER_TABLES = {
    "confidence": {"level": ("text", True), "basis": ("text", True), "rules": ("strs1", True), "draw": ("text", True)},
    "edge": {"id": ("text", True), "input": ("text", True), "edge": ("text", True), "kind": ("str", True), "kind_by": ("text", False),
             "kind_note": ("text", False), "confidence": ("str", True), "confidence_note": ("text", False)},
    "kind_by_target": {"kind": ("text", True), "types": ("strs1", True)},
    "iam_action_kind": {"kind": ("text", True), "actions": ("strs1", True), "actions_note": ("text", False)},
    "merge_priority": {"rank": ("int", True), "rules": ("strs1", True)},
    "synthetic": {"id": ("text", True), "trigger": ("text", True), "node": ("text", True), "edges": ("text", True)},
    "label_format": {"subject": ("text", True), "format": ("text", True), "example": ("str", True)},
    "noedge": {"id": ("text", True), "attrs": ("strs", True), "use": ("strs", True), "match": ("text", True),
               "use_text": ("text", True), "from_class": ("strs1", False), "except_rules": ("strs", False)},
    "nonode": {"id": ("text", True), "target": ("text", True), "handling": ("text", True)},
    "placement": {"id": ("text", True), "types": ("strs1", True), "content": ("text", True)},
    "attr": {"type": ("text", True), "name": ("text", True), "values": ("strs1", True), "source": ("text", True), "rule": ("text", True)},
}


def _check_fields(where: str, row: dict, spec: dict, errs: list[str]) -> None:
    for k in row:
        if k not in spec:
            errs.append(f"{where}: 未知のフィールド {k!r}（綴りの誤りか、この表に無い列）")
    for k, (kind, required) in spec.items():
        if k not in row:
            if required:
                errs.append(f"{where}: 必須の列 {k!r} が無い")
            continue
        if kind in CHECKS:
            if not CHECKS[kind](row[k]):
                errs.append(f"{where}: {k!r} は{KIND_NAMES[kind]}（値: {row[k]!r}）")
        elif kind == "name_attr":
            v = row[k]
            if not (_is_str_table(v) and set(v) <= {"tf", "cfn"} and all(x.strip() for x in v.values())):
                errs.append(f"{where}: {k!r} は {{ tf = …, cfn = … }}（どちらも省略可。タグだけなら {{}}）の表（値: {v!r}）")
        elif kind == "into":
            v = row[k]
            if not (isinstance(v, dict) and set(v) == {"node_types", "select"} and _is_strs1(v["node_types"]) and _is_nonempty_str(v["select"])):
                errs.append(f"{where}: {k!r} は {{ node_types = [型…], select = \"統合先の選び方\" }}（値: {v!r}）")


def _check_when(where: str, when, errs: list[str]) -> None:
    allowed = {"types", "prop", "in", "default", "via", "via_not"}
    if not isinstance(when, dict):
        errs.append(f"{where}: when は表（値: {when!r}）")
        return
    for k in when:
        if k not in allowed:
            errs.append(f"{where}: when の未知のキー {k!r}（{sorted(allowed)} だけ）")
    for k in ("types", "in", "via", "via_not"):
        if k in when and not _is_strs1(when[k]):
            errs.append(f"{where}: when.{k} は 1 つ以上の文字列の配列")
    for k in ("via", "via_not"):
        if _is_strs(when.get(k)) and [x for x in when[k] if x not in VIA_VALUES]:
            errs.append(f"{where}: when.{k} は {list(VIA_VALUES)} のどれか（値: {when[k]}）")
    if "prop" in when:
        p = when["prop"]
        if not (_is_str_table(p) and p and set(p) <= {"tf", "cfn"} and all(x.strip() for x in p.values())):
            errs.append(f"{where}: when.prop は {{ tf = 属性名, cfn = 属性名 }}")
        if "in" not in when:
            errs.append(f"{where}: when.prop があるのに when.in が無い")
    elif "in" in when or "default" in when:
        errs.append(f"{where}: when.in／when.default は when.prop と一緒に書く")
    if "default" in when and (not _is_nonempty_str(when["default"]) or ("in" in when and _is_strs(when["in"]) and when["default"] not in when["in"])):
        errs.append(f"{where}: when.default は when.in の中の値")
    if "via" in when and "via_not" in when:
        errs.append(f"{where}: when.via と when.via_not は一緒に書かない")


# ------------------------------------------------------------------ 読み込んだ結果

def _freeze(v):
    if isinstance(v, dict):
        return MappingProxyType({k: _freeze(x) for k, x in v.items()})
    if isinstance(v, list):
        return tuple(_freeze(x) for x in v)
    return v


@dataclass(frozen=True)
class Row:
    """表の 1 行（読み込み後は変えられない。列は `get` と属性の両方で読める）。`table` は表の名前、`file` は SKILL の data/rules/ からの相対パス。"""
    table: str
    file: str
    fields: MappingProxyType

    def __getattr__(self, name: str):
        try:
            return self.fields[name]
        except KeyError:
            raise AttributeError(name) from None

    def get(self, name: str, default=None):
        return self.fields.get(name, default)

    @property
    def id(self) -> str:
        return self.fields["id"]

    @property
    def cls(self) -> str:
        """`class`（Python の予約語なので別名）。relation の行は merged_into。"""
        return self.fields.get("class", "")


@dataclass(frozen=True)
class Rules:
    """読み込んで検査した規則表。表は読んだ順の tuple。"""
    types: tuple[Row, ...]
    relations: tuple[Row, ...]
    confidences: tuple[Row, ...]
    edges: tuple[Row, ...]
    kind_by_target: tuple[Row, ...]
    iam_action_kinds: tuple[Row, ...]
    merge_priority: tuple[Row, ...]
    synthetic: tuple[Row, ...]
    label_formats: tuple[Row, ...]
    noedge: tuple[Row, ...]
    nonode: tuple[Row, ...]
    placement: tuple[Row, ...]
    attrs: tuple[Row, ...]
    edges_options: MappingProxyType  # edges.toml の最上位のキー（confidence_order など）

    # --- 型の表
    @property
    def drawn(self) -> tuple[Row, ...]:
        return tuple(r for r in self.types if r.cls == "drawn")

    @property
    def merged(self) -> tuple[Row, ...]:
        return tuple(r for r in self.types if r.cls == "merged_into")

    @property
    def hidden(self) -> tuple[Row, ...]:
        return tuple(r for r in self.types if r.cls == "hidden")

    # --- 規則 ID の集合（validate_ir.py が検査に使う。描く型の正規の型名は含まない）
    @functools.cached_property
    def _id_sets(self) -> dict[str, frozenset[str]]:
        def ids(rows):
            return frozenset(r.get("id") for rows_ in (rows,) for r in rows_ if isinstance(r.get("id"), str))
        return {"hidden": ids(self.hidden), "merged": ids(self.merged), "relation": ids(self.relations), "edge": ids(self.edges),
                "ref": ids(self.noedge) | ids(self.nonode), "synthetic": ids(self.synthetic), "placement": ids(self.placement)}

    @property
    def hidden_ids(self) -> frozenset[str]:
        return self._id_sets["hidden"]

    @property
    def merged_ids(self) -> frozenset[str]:
        """M-*（統合。into はノード）。"""
        return self._id_sets["merged"]

    @property
    def relation_ids(self) -> frozenset[str]:
        """R-*（関係リソース。into は辺）。"""
        return self._id_sets["relation"]

    @property
    def edge_ids(self) -> frozenset[str]:
        """E-*（辺を作る規則と E-MERGE）。辺にしない参照（E-NOEDGE-*・E-REF-NONODE）は `ref_ids`。"""
        return self._id_sets["edge"]

    @property
    def ref_ids(self) -> frozenset[str]:
        """E-NOEDGE-* と E-REF-NONODE。"""
        return self._id_sets["ref"]

    @property
    def synthetic_ids(self) -> frozenset[str]:
        return self._id_sets["synthetic"]

    @property
    def placement_ids(self) -> frozenset[str]:
        return self._id_sets["placement"]

    @functools.cached_property
    def rule_ids(self) -> frozenset[str]:
        """定義されている規則 ID すべて（`sources.*.resources[].rule`・`sources.*.edges[].rules` が指してよいもの）。"""
        out: frozenset[str] = frozenset()
        for s in self._id_sets.values():
            out |= s
        return out

    @functools.cached_property
    def drawn_ids(self) -> frozenset[str]:
        return frozenset(r.get("id") for r in self.drawn if isinstance(r.get("id"), str))

    @functools.cached_property
    def synthetic_types(self) -> frozenset[str]:
        """合成ノードの型（`synthetic` を持つ描く型: availability_zone・external・bedrock_model）。"""
        return frozenset(r.get("id") for r in self.drawn if r.get("synthetic") and isinstance(r.get("id"), str))

    def drawable_types(self) -> dict[str, frozenset[str]]:
        """入力の型（TF・CFN／SAM）→ それから描ける正規の型名の集合（描く型の `tf`・`cfn` から作る）。"""
        out: dict[str, set[str]] = {}
        for r in self.drawn:
            for t in (*r.tf, *r.cfn):
                out.setdefault(t, set()).add(r.id)
        return {k: frozenset(v) for k, v in out.items()}

    def row(self, id_: str) -> Row:
        """規則 ID（描く型は正規の型名）の行。無ければ KeyError。"""
        for r in (*self.types, *self.relations, *self.edges, *self.noedge, *self.nonode, *self.synthetic, *self.placement):
            if r.id == id_:
                return r
        raise KeyError(id_)

    def rows_for_input_type(self, input_type: str) -> tuple[Row, ...]:
        """入力の型を `tf`・`cfn`（`random_*` のような末尾の `*` を含む）に持つ型・関係の行（`when` は見ない）。"""
        return tuple(r for r in (*self.types, *self.relations) if any(_matches(p, input_type) for p in (*r.tf, *r.cfn)))


def _matches(pattern: str, name: str) -> bool:
    return fnmatch.fnmatchcase(name, pattern) if "*" in pattern else pattern == name


# ------------------------------------------------------------------ 読み込み

def _read_toml(path: Path, rel: str, errs: list[str]) -> dict:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        errs.append(f"{rel}: 読めない（UTF-8 のファイルが要る）: {e}")
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        errs.append(f"{rel}: TOML として読めない: {e}")
        return {}


def _files(rules_dir: Path, errs: list[str]) -> list[tuple[str, Path, str]]:
    """読むファイル (相対パス, 実体, ファイルの種類) を決まった順序で。無い・余る・名前の違うものは errs に足す。"""
    out: list[tuple[str, Path, str]] = []
    try:
        entries = sorted(rules_dir.iterdir(), key=lambda p: p.name)
    except OSError as e:
        errs.append(f"{rules_dir.name}/: 開けない: {e}")
        return out
    names = {p.name for p in entries}
    for e in entries:
        if e.name not in ALLOWED_ROOT_NAMES:
            errs.append(f"{e.name}: 規則表のフォルダに置いてよい名前ではない（読まれない。{sorted(ALLOWED_ROOT_NAMES)} だけ）")
    for n in FIXED_FILES:
        if n not in names:
            errs.append(f"{n}: 無い（規則表のファイル）")
        elif (rules_dir / n).is_file():
            out.append((n, rules_dir / n, n))
        else:
            errs.append(f"{n}: ファイルでない")
    tdir = rules_dir / TYPES_DIR_NAME
    if not tdir.is_dir():
        errs.append(f"{TYPES_DIR_NAME}/: 無い（型の表のフォルダ）")
        return out
    tfiles = []
    for f in sorted(tdir.iterdir(), key=lambda p: p.name):
        if f.is_file() and f.name.endswith(".toml"):
            tfiles.append((f"{TYPES_DIR_NAME}/{f.name}", f, "types"))
        else:
            errs.append(f"{TYPES_DIR_NAME}/{f.name}: 読まれない（{TYPES_DIR_NAME}/ に置くのは .toml のファイルだけ）")
    if not tfiles:
        errs.append(f"{TYPES_DIR_NAME}/: .toml のファイルが 1 つも無い")
    return tfiles + out


def load(rules_dir: Path | None = None) -> Rules:
    """`rules_dir`（省略すると SKILL の `data/rules/`）を読んで検査する。問題があれば、すべて集めて `RulesError`。"""
    rules_dir = Path(rules_dir) if rules_dir is not None else paths.RULES_DIR
    errs: list[str] = []
    tables: dict[str, list[Row]] = {k: [] for k in ("type", "relation", "confidence", "edge", "kind_by_target", "iam_action_kind",
                                                     "merge_priority", "synthetic", "label_format", "noedge", "nonode", "placement", "attr")}
    options: dict = {}
    for rel, path, kind in _files(rules_dir, errs):
        data = _read_toml(path, rel, errs)
        allowed = FILE_TABLES[kind]
        for key, value in data.items():
            if key in allowed:
                if not (isinstance(value, list) and all(isinstance(x, dict) for x in value)):
                    errs.append(f"{rel}: {key} は [[{key}]]（表の配列）で書く")
                    continue
                for n, row in enumerate(value, 1):
                    tables[key].append(_row(key, rel, n, row, errs))
            elif kind == "edges.toml" and key in EDGES_TOP_LEVEL:
                options[key] = value
            else:
                errs.append(f"{rel}: 未知のキー {key!r}（このファイルに置いてよいのは {sorted(allowed | (EDGES_TOP_LEVEL if kind == 'edges.toml' else set()))}）")
    rules = Rules(types=tuple(tables["type"]), relations=tuple(tables["relation"]), confidences=tuple(tables["confidence"]),
                  edges=tuple(tables["edge"]), kind_by_target=tuple(tables["kind_by_target"]),
                  iam_action_kinds=tuple(tables["iam_action_kind"]), merge_priority=tuple(tables["merge_priority"]),
                  synthetic=tuple(tables["synthetic"]), label_formats=tuple(tables["label_format"]), noedge=tuple(tables["noedge"]),
                  nonode=tuple(tables["nonode"]), placement=tuple(tables["placement"]), attrs=tuple(tables["attr"]),
                  edges_options=_freeze(options))
    _cross_checks(rules, rules_dir, errs)
    if errs:
        raise RulesError(errs)
    return rules


def _row(table: str, rel: str, n: int, row: dict, errs: list[str]) -> Row:
    ident = row.get("id") or row.get("level") or row.get("kind") or row.get("subject") or row.get("rank") or ""
    where = f"{rel}: [[{table}]] #{n}" + (f"（{ident}）" if ident else "")
    if table == "type":
        cls = row.get("class")
        if cls in CLASSES:
            spec = {**TYPE_COMMON, **TYPE_BY_CLASS[cls]}
        else:
            errs.append(f"{where}: class は {list(CLASSES)} のどれか（値: {cls!r}）")
            spec = {**TYPE_COMMON, **{k: (kind, False) for d in TYPE_BY_CLASS.values() for k, (kind, _) in d.items()}}
    elif table == "relation":
        spec = RELATION
        if row.get("class") != "merged_into":
            errs.append(f"{where}: relation の class は merged_into（値: {row.get('class')!r}）")
    else:
        spec = OTHER_TABLES[table]
    # when は型と関係の行だけが持てる（別に検査する）。ほかの表に書けば未知のフィールドになる
    has_when = table in ("type", "relation")
    _check_fields(where, {k: v for k, v in row.items() if not (has_when and k == "when")}, spec, errs)
    if has_when and "when" in row:
        _check_when(where, row["when"], errs)
    return Row(table=table, file=rel, fields=_freeze(row))


# ------------------------------------------------------------------ 表どうしの検査

def _disjoint(a: dict, b: dict) -> bool:
    """2 つの `when` が同時に成り立たないと言えるか。"""
    pa, pb = a.get("prop"), b.get("prop")
    if pa is not None and pb is not None and pa == pb and not (set(a["in"]) & set(b["in"])):
        return True
    va, vb = a.get("via"), b.get("via")
    na, nb = a.get("via_not"), b.get("via_not")
    if va is not None and vb is not None and not (set(va) & set(vb)):
        return True
    if va is not None and nb is not None and set(va) <= set(nb):
        return True
    if vb is not None and na is not None and set(vb) <= set(na):
        return True
    return False


def _applies(when: dict | None, input_type: str) -> bool:
    return when is not None and ("types" not in when or input_type in when["types"])


def _glob_hits(pattern: str, ids: frozenset[str]) -> bool:
    return any(_matches(pattern, i) for i in ids)


def _cross_checks(rules: Rules, rules_dir: Path, errs: list[str]) -> None:
    # --- ID の形・接頭辞と class・重複
    seen: dict[str, str] = {}

    def see(row: Row, id_: str, label: str) -> None:
        if id_ in seen:
            errs.append(f"{row.file}: {label} の id {id_!r} が重複（{seen[id_]} にもある）")
        else:
            seen[id_] = f"{row.file}"

    for r in rules.types:
        id_, cls = r.get("id"), r.get("class")
        if not isinstance(id_, str):
            continue
        see(r, id_, "[[type]]")
        if cls == "drawn":
            if not TYPE_ID.match(id_) or RULE_ID.match(id_):
                errs.append(f"{r.file}: 描く型の id {id_!r} は正規の型名（小文字・数字・_）")
        elif cls in ("merged_into", "hidden"):
            want = TABLE_PREFIX[f"type:{cls}"]
            if not RULE_ID.match(id_) or not id_.startswith(want):
                errs.append(f"{r.file}: class {cls} の id {id_!r} は {'／'.join(p + '*' for p in want)} の形の規則 ID")
    for table, rows in (("relation", rules.relations), ("edge", rules.edges), ("noedge", rules.noedge), ("nonode", rules.nonode),
                        ("synthetic", rules.synthetic), ("placement", rules.placement)):
        for r in rows:
            id_ = r.get("id")
            if not isinstance(id_, str):
                continue
            see(r, id_, f"[[{table}]]")
            want = TABLE_PREFIX[table]
            if not RULE_ID.match(id_) or not id_.startswith(want):
                errs.append(f"{r.file}: [[{table}]] の id {id_!r} は {'／'.join(p + '*' for p in want)} の形の規則 ID")

    drawn_ids = rules.drawn_ids
    rule_ids = rules.rule_ids

    # --- 入力の型の形と、重複（同じ型が複数の行に当たるのは、`when` で同時に成り立たないときだけ）
    entries: list[tuple[str, Row]] = []
    for r in (*rules.types, *rules.relations):
        for key, shape in (("tf", TF_TYPE), ("cfn", CFN_TYPE), ("tf_data", TF_TYPE)):
            vals = r.get(key, ())
            if not (isinstance(vals, tuple) and all(isinstance(v, str) for v in vals)):
                continue
            if len(set(vals)) != len(vals):
                errs.append(f"{r.file}: {r.get('id')} の {key} に同じ型が 2 回ある")
            for v in vals:
                if not shape.match(v):
                    errs.append(f"{r.file}: {r.get('id')} の {key} の {v!r} は {'CFN' if key == 'cfn' else 'TF'} の型の形でない")
                elif key != "tf_data":
                    entries.append((v, r))
    for i, (a, ra) in enumerate(entries):
        for b, rb in entries[i + 1:]:
            if ra is rb or not (_matches(a, b) or _matches(b, a)):
                continue
            t = b if "*" in a and "*" not in b else a  # when の types に当てる具体的な型
            wa, wb = ra.get("when"), rb.get("when")
            if wa is not None and wb is not None and _applies(wa, t) and _applies(wb, t) and _disjoint(wa, wb):
                continue
            errs.append(f"型 {a if a == b else f'{a} と {b}'} が複数の行に当たる: {ra.get('id')}（{ra.file}）と {rb.get('id')}（{rb.file}）。"
                        "同時に成り立たない when（同じ prop の in が重ならない、via と via_not など）で分ける")

    # --- 型の行
    for r in rules.drawn:
        if r.get("category") not in CATEGORIES and "category" in r.fields:
            errs.append(f"{r.file}: {r.id} の category は {list(CATEGORIES)} のどれか（値: {r.category!r}）")
        syn = r.get("synthetic")
        if syn is not None:
            if syn not in rules.synthetic_ids | {i for i in rules.placement_ids if i.startswith("N-")}:
                errs.append(f"{r.file}: {r.id} の synthetic {syn!r} が、合成ノードの規則（edges.toml の [[synthetic]]、placement.toml の N-*）に無い")
            if r.get("tf") or r.get("cfn"):
                errs.append(f"{r.file}: 合成ノード {r.id} に入力の型（tf・cfn）は書かない")
        elif "tf" in r.fields and not (r.tf or r.cfn):
            errs.append(f"{r.file}: 描く型 {r.id} に入力の型（tf・cfn）が 1 つも無い（合成ノードなら synthetic を書く）")
    for r in rules.merged:
        into = r.get("into")
        if isinstance(into, MappingProxyType):
            bad = [t for t in into.get("node_types", ()) if t not in drawn_ids]
            if bad:
                errs.append(f"{r.file}: {r.id} の into.node_types {bad} が描く型にない")
    refs_as = [r.id for r in rules.merged if r.get("refs_as_target")]
    if any(r.get("data") for r in rules.drawn) and not any(r.get("data_block") for r in rules.hidden):
        errs.append("types: data = true の型があるのに、data_block = true の H-* の行（H-DATA）が無い")
    for r in rules.hidden:
        f = r.get("module_sources_file")
        if f is not None and not (rules_dir.parent.parent / f).is_file():
            errs.append(f"{r.file}: {r.id} の module_sources_file {f!r} が SKILL の下に無い")

    # --- 関係リソース
    hidden_ids = rules.hidden_ids
    for r in rules.relations:
        k = r.get("kind")
        if k not in (None, "") and k not in KINDS:
            errs.append(f"{r.file}: {r.id} の kind {k!r} は {list(KINDS)} のどれか（または空）")
        if k == "" and not r.get("kind_note"):
            errs.append(f"{r.file}: {r.id} の kind が空なのに kind_note が無い（空は『既存の辺に従う』ときだけ）")
        if r.get("confidence") not in CONFIDENCES:
            errs.append(f"{r.file}: {r.id} の confidence は {list(CONFIDENCES)} のどれか（値: {r.get('confidence')!r}）")
        fb = r.get("fallback")
        if fb is not None and fb not in hidden_ids:
            errs.append(f"{r.file}: {r.id} の fallback {fb!r} が非表示の規則（H-*）にない")

    # --- 確信度
    levels = [r.get("level") for r in rules.confidences]
    for lv in levels:
        if lv not in CONFIDENCES:
            errs.append(f"edges.toml: [[confidence]] の level {lv!r} は {list(CONFIDENCES)} のどれか")
    if len(set(levels)) != len(levels):
        errs.append("edges.toml: [[confidence]] の level が重複")
    order = rules.edges_options.get("confidence_order")
    if order is not None and tuple(order) != tuple(CONFIDENCES):
        errs.append(f"edges.toml: confidence_order は {list(CONFIDENCES)}（値: {list(order)}）")
    by_level = {r.get("level"): r.get("rules", ()) for r in rules.confidences}
    for lv, pats in by_level.items():
        for p in pats:
            if not _glob_hits(p, rule_ids):
                errs.append(f"edges.toml: [[confidence]] {lv} の rules の {p!r} に当たる規則 ID が無い")

    def covered(level: str, id_: str) -> bool:
        return any(_matches(p, id_) for p in by_level.get(level, ()))

    for r in rules.relations:
        if r.get("confidence") in CONFIDENCES and not covered(r.confidence, r.id):
            errs.append(f"{r.file}: {r.id} の confidence {r.confidence} が、edges.toml の確信度の表の rules に無い")
    for r in rules.edges:
        c = r.get("confidence")
        if c not in (None, ""):
            if c not in CONFIDENCES:
                errs.append(f"{r.file}: {r.id} の confidence は {list(CONFIDENCES)} のどれか（または空）")
            elif not covered(c, r.id):
                errs.append(f"{r.file}: {r.id} の confidence {c} が、確信度の表の rules に無い")
        kb = r.get("kind_by")
        if kb is not None:
            if kb not in KIND_TABLES:
                errs.append(f"{r.file}: {r.id} の kind_by {kb!r} は {list(KIND_TABLES)} のどれか")
            if r.get("kind"):
                errs.append(f"{r.file}: {r.id} は kind と kind_by を両方持てない")
        elif r.get("kind") not in (None, "") and r.kind not in KINDS:
            errs.append(f"{r.file}: {r.id} の kind {r.kind!r} は {list(KINDS)} のどれか（または空）")

    # --- kind の対応表・優先順
    seen_types: dict[str, str] = {}
    for r in rules.kind_by_target:
        if r.get("kind") not in KINDS:
            errs.append(f"edges.toml: [[kind_by_target]] の kind {r.get('kind')!r} は {list(KINDS)} のどれか")
        for t in r.get("types", ()):
            if not _glob_hits(t, drawn_ids):
                errs.append(f"edges.toml: [[kind_by_target]] の型 {t!r} が描く型にない")
            if t in seen_types:
                errs.append(f"edges.toml: [[kind_by_target]] の型 {t!r} が重複（{seen_types[t]} にもある）")
            seen_types[t] = str(r.get("kind"))
    for r in rules.iam_action_kinds:
        if r.get("kind") not in KINDS:
            errs.append(f"edges.toml: [[iam_action_kind]] の kind {r.get('kind')!r} は {list(KINDS)} のどれか")
    seen_actions: set[str] = set()
    for r in rules.iam_action_kinds:
        for a in r.get("actions", ()):
            if a in seen_actions:
                errs.append(f"edges.toml: [[iam_action_kind]] のアクション {a!r} が重複")
            seen_actions.add(a)
    if rules.iam_action_kinds and rules.edges_options.get("iam_action_priority") != "first_row_wins":
        errs.append("edges.toml: iam_action_priority = \"first_row_wins\" が要る（[[iam_action_kind]] は上の行が優先）")
    ranks = [r.get("rank") for r in rules.merge_priority]
    if ranks != list(range(1, len(ranks) + 1)):
        errs.append(f"edges.toml: [[merge_priority]] の rank は 1 から順に 1 つずつ（値: {ranks}）")
    for r in rules.merge_priority:
        for p in r.get("rules", ()):
            if not _glob_hits(p, rule_ids):
                errs.append(f"edges.toml: [[merge_priority]] の rules の {p!r} に当たる規則 ID が無い")
    for r in rules.edges:
        kb = r.get("kind_by")
        tbl = {"kind_by_target": rules.kind_by_target, "iam_action_kind": rules.iam_action_kinds, "merge_priority": rules.merge_priority}.get(kb)
        if kb in KIND_TABLES and not tbl:
            errs.append(f"{r.file}: {r.id} の kind_by {kb} の表が空")

    # --- 辺にしない参照
    seen_keys: dict[str, str] = {}
    for r in rules.noedge:
        keys = [neutral_key(a) for a in r.get("attrs", ())]
        if len(set(keys)) != len(keys):
            errs.append(f"{r.file}: {r.id} の attrs に、中立キー（小文字にして _ を除く）が同じ属性名が 2 回ある: {list(r.get('attrs', ()))}")
        for a, k in zip(r.get("attrs", ()), keys):
            if k in seen_keys and seen_keys[k] != r.id:
                errs.append(f"{r.file}: 属性名 {a!r} が {r.id} と {seen_keys[k]} の両方にある（上から当てはめるので前の規則が隠す）")
            seen_keys.setdefault(k, r.id)
        for p in r.get("use", ()):
            if not _glob_hits(p, rule_ids):
                errs.append(f"{r.file}: {r.id} の use の {p!r} に当たる規則 ID が無い")
        has_fc, has_ex = "from_class" in r.fields, "except_rules" in r.fields
        if has_fc != has_ex:
            errs.append(f"{r.file}: {r.id} の from_class と except_rules は一緒に書く")
        for c in r.get("from_class", ()):
            if c not in FROM_CLASSES:
                errs.append(f"{r.file}: {r.id} の from_class {c!r} は {list(FROM_CLASSES)} のどれか")
        for x in r.get("except_rules", ()):
            if x not in rules.merged_ids:
                errs.append(f"{r.file}: {r.id} の except_rules {x!r} が統合の規則（M-*）にない")
        if not r.get("attrs") and not has_fc:
            errs.append(f"{r.file}: {r.id} は attrs が空なのに from_class が無い（何にも当たらない規則）")
    if refs_as and not any(x in refs_as for r in rules.noedge for x in r.get("except_rules", ())):
        errs.append(f"types: refs_as_target の {refs_as} を、辺にしない参照の except_rules が指していない")

    # --- 入れ子
    for r in rules.placement:
        for t in r.get("types", ()):
            if t not in drawn_ids:
                errs.append(f"{r.file}: {r.id} の types の {t!r} が描く型にない")
    for r in rules.attrs:
        if r.get("type") not in drawn_ids:
            errs.append(f"{r.file}: [[attr]] の type {r.get('type')!r} が描く型にない")
        if r.get("source") not in rule_ids:
            errs.append(f"{r.file}: [[attr]] の source {r.get('source')!r} が規則 ID にない")


@functools.lru_cache(maxsize=1)
def default() -> Rules:
    """SKILL の `data/rules/` を読んだ結果（プロセスの中で 1 回だけ読む）。"""
    return load()
