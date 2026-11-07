"""正規化の段階 2 の一部: ノードの名前（B3）と id（K-NAME）。ir-schema の 2 章「ID の作り方（K-NAME）」のとおり。

名前の採用順（B3）:
  1. `Name` タグ（TF の `tags.Name`、CFN の `Tags` の `Key: Name`）
  2. 型ごとの名前属性（規則表の描く型の `name_attr`。TF と CFN で別の属性名）
  3. 論理名（TF: モジュールのパスを `.` でつないだもの + リソース名。インデックスは `-0`・`-ssm`。CFN: ネストスタックの
     論理 ID を `.` でつないだもの + 論理 ID）
評価できない値（印。`$unknown`・`$res` を含む `$concat` など）は使わず次の候補に落とす。3 に落ちたら `NORM-NAME-FALLBACK`（info）。
名前が記号だけ（`Name` タグが「本番」など。key が空になる）なら、名前・label はそのまま使い、id の key だけを次の候補から作る。
awscc の型の名前属性は、同じ名前の CFN の型の属性名（中立キー）で引く。
黒箱のモジュール（型 `module`）の名前は、はじめからモジュール呼び出しの名前（論理名と同じ形）で、落ちたことにはしない。

id の key は名前を小文字にして `[a-z0-9._-]` 以外を `-` にしたもの（`label` からは作らない）。同じ型で key が重なったら、
重なったリソースを address の辞書順に並べ、2 つ目以降の key の末尾に `.<論理名の key>` を付ける（`NORM-KEY-COLLISION`、info）。
それでも重なるもの（論理名まで同じ。TF の `data.aws_vpc.x` と `aws_vpc.x` など）は、address 全体の key を付けて分ける。

ここは標準ライブラリと core と normalize の view だけを使う。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from aws_iac_diagram.core.rules import Row
from aws_iac_diagram.normalize import view
from aws_iac_diagram.normalize.view import Resource

_KEY_BAD = re.compile(r"[^a-z0-9._-]")
_INDEX = re.compile(r'\[(?:"((?:[^"\\]|\\.)*)"|([^\]]*))\]')
_KEY_HEAD = re.compile(r"^[^a-z0-9]+")


def key_of(name: str) -> str:
    """名前 → id の key（小文字にして `[a-z0-9._-]` 以外を `-`）。ir.schema.json の id の形（先頭は英数字）に合わないときは、
    先頭の記号を除く（`.hidden` → `hidden`）。全部が記号なら `-` を返す（呼ぶ側が論理名に落とす）。"""
    k = _KEY_BAD.sub("-", name.lower())
    head = _KEY_HEAD.sub("", k)
    return head or "-"


def _index_suffix(segment: str) -> str:
    """`private[0]` → `private-0`、`interface["ssm"]` → `interface-ssm`、`x[*]` → `x`（×N はインデックスを付けない）。"""
    def sub(m: re.Match) -> str:
        v = m.group(1) if m.group(1) is not None else m.group(2)
        return "" if v == "*" else f"-{v}"
    return _INDEX.sub(sub, segment)


def logical_name(res: Resource) -> str:
    """論理名（B3 の 3 番目。K-NAME）。TF の黒箱のモジュールの呼び出しはモジュールのパス（`module.eks.module.kms` → `eks.kms`）。"""
    if res.fmt == "tf":
        parts = view.split_tf_address(res.address)
        mods: list[str] = []
        i = 0
        while i + 1 < len(parts) and parts[i] == "module":
            mods.append(_index_suffix(parts[i + 1]))
            i += 2
        rest = parts[i:]
        if rest and rest[0] == "data":
            rest = rest[1:]
        if not rest:  # 黒箱の呼び出し（address が module.… だけ）
            return ".".join(mods)
        return ".".join([*mods, _index_suffix(rest[-1])])
    # CFN: `Stack::Parent/Child` → `Stack.Parent.Child`。Fn::ForEach の決まらないひな形の `*` は除く
    return ".".join(p.replace("*", "") for p in res.address.replace("::", "/").split("/") if p.replace("*", ""))


@dataclass(frozen=True)
class Name:
    """名前（`name`・`label` にするもの）と、その出どころ（"tag"／"attr"／"logical"／"module"）。`key_from` は、名前が記号だけで
    id の key を作れない（`Name` タグが「本番」など）ときに、key を作った次の候補の値と出どころ（空なら名前から作る）。"""
    name: str
    source: str
    key_from: tuple[str, str] | None = None

    @property
    def key(self) -> str:
        return key_of(self.key_from[0] if self.key_from else self.name)


def name_attr_of(res: Resource, row: Row) -> str | None:
    """型ごとの名前属性（B3 の 2 番目）。awscc の型は同じ名前の CFN の型として扱うので、CFN の属性名を中立キーで引く。"""
    fmt = "cfn" if res.fmt == "tf" and res.type.startswith("awscc_") else res.fmt
    return row.get("name_attr", {}).get(fmt)


def choose_name(res: Resource, row: Row) -> Name:
    """B3 の順で名前を決める。名前が記号だけ（key が作れない）なら、名前はそのままにして、key だけを次の候補から作る。"""
    logical = logical_name(res)
    if row.id == "module":
        return Name(logical, "module")
    cands: list[tuple[str, str]] = []
    tag = view.name_tag(dict(res.props))
    if tag is not None:
        cands.append((tag, "tag"))
    attr = name_attr_of(res, row)
    if attr:
        v = view.plain_str(res.get(attr))
        if v is not None:
            cands.append((v, "attr"))
    cands.append((logical, "logical"))
    name, source = cands[0]
    if key_of(name) != "-":
        return Name(name, source)
    key_from = next((c for c in cands[1:] if key_of(c[0]) != "-"), (logical, "logical"))
    return Name(name, source, key_from)


def assign_ids(items: list[tuple[Resource, str, Name]]) -> tuple[dict[str, str], list[dict]]:
    """(リソース, 正規の型名, 名前) の並び → address → ノードの id と、診断（`NORM-NAME-FALLBACK`・`NORM-KEY-COLLISION`）。"""
    diags: list[dict] = []
    for res, _, nm in items:
        if nm.source == "logical":
            diags.append({"level": "info", "code": "NORM-NAME-FALLBACK", "address": res.address,
                          "message": f"Name タグ・名前属性が無い（か評価できない）ので、論理名 {nm.name!r} を名前にした"})
        elif nm.key_from and nm.key_from[1] == "logical":
            diags.append({"level": "info", "code": "NORM-NAME-FALLBACK", "address": res.address,
                          "message": f"名前 {nm.name!r} から id の key を作れない（記号だけ）ので、key は論理名 {nm.key_from[0]!r} から作った"})
    groups: dict[tuple[str, str], list[tuple[Resource, str, Name]]] = {}
    for item in items:
        groups.setdefault((item[1], item[2].key), []).append(item)
    ids: dict[str, str] = {}
    taken: set[str] = set()
    for (type_id, key), members in sorted(groups.items()):
        members = sorted(members, key=lambda x: x[0].address)
        first = f"{type_id}/{key}"
        ids[members[0][0].address] = first
        taken.add(first)
        for res, _, nm in members[1:]:
            nid = f"{type_id}/{key}.{key_of(logical_name(res))}"
            if nid in taken or nid in {f"{t}/{k}" for t, k in groups}:
                nid = f"{type_id}/{key}.{key_of(res.address)}"
            ids[res.address] = nid
            taken.add(nid)
            diags.append({"level": "info", "code": "NORM-KEY-COLLISION", "address": res.address,
                          "message": f"{first} が {members[0][0].address} と重なるので、{nid} にした"})
    return ids, diags
