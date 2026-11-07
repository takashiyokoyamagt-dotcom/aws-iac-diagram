"""正規化の段階 0: raw IR の読み方（中立キーのビュー、印の扱い、タグ、参照の索引）。

TF と CFN の書き方の違いをここで吸収する（設計草案の 4.4）:

- 属性名は中立キー（`core/rules.neutral_key`。小文字にして `_` を除く）で引く。`cidr_block` と `CidrBlock` は同じ。
- タグは TF の map（`tags = { Name = … }`）と CFN の `Key`／`Value` のリスト（`Tags: [{Key: Name, Value: …}]`）の両方を、
  1 つの関数（`tags`・`name_tag`）で読む。SAM の `Tags` のような map の形の CFN も読む。
- 印（`$res`・`$concat`・`$unknown` など。ir-schema の 7.2）は「評価できた値」ではない。名前や条件の値に使うのは、印でない
  ふつうの値だけ（`$unknown` は「その属性を持たない」として扱う。設計草案の 4.2）。入力にもともとあった `$` で始まるキーは
  raw IR で `$$` にしてあるので、印と取り違えない。

参照の索引（`Index`）は、リソースを address で、参照を from 別・to 別に引けるようにしたもの。`active` 以外（`pruned`・
`unevaluated`）の参照は使わない（設計草案の 4.2）。DependsOn は `is_depends_on` で見分ける（辺の根拠にはしない）。

ここは標準ライブラリと core だけを使う（normalize の決まり）。
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from aws_iac_diagram.core.rules import neutral_key

# raw IR の印のキー（ir-schema の 7.2）。`$res` は `attr` と組で 2 つのキーを持つ
MARK_KEYS = frozenset({"$res", "$pseudo", "$concat", "$json", "$az", "$import", "$unknown"})


def is_mark(value) -> bool:
    """raw IR の印（`{"$res": …}`・`{"$unknown": …}` など）か。入力にあった `$` のキー（raw では `$$schema`）は印ではない。"""
    return isinstance(value, dict) and any(k in MARK_KEYS for k in value)


def is_unknown(value) -> bool:
    return isinstance(value, dict) and "$unknown" in value


def plain(value):
    """印でない値はそのまま、印（`$unknown` を含む）は None（「評価できた値が無い」）。"""
    return None if is_mark(value) else value


def plain_str(value) -> str | None:
    """印でない文字列（空白だけの文字列は無いものとする）。それ以外は None。"""
    return value if isinstance(value, str) and value.strip() else None


def get(props: dict, name: str):
    """属性 `name` の値（TF・CFN のどちらの綴りで書いても、中立キーで引く）。無い・`$unknown` なら None。

    同じ中立キーの属性が 2 つあれば（ふつうは無い）、綴りが完全に一致するものを先に使う。"""
    if not isinstance(props, dict):
        return None
    if name in props:
        v = props[name]
    else:
        key = neutral_key(name)
        v = next((props[k] for k in sorted(props) if isinstance(k, str) and neutral_key(k) == key), None)
    return None if is_unknown(v) else v


def tags(props: dict) -> dict:
    """タグ（キー → 値）。TF の map、CFN の `Key`／`Value` のリスト、CFN の map（SAM など）のどれも読む。
    タグ全体やキーが評価できない（印）ものは読まない。値は印のまま返す（使う側が `plain_str` で選ぶ）。"""
    t = get(props, "tags")
    out: dict = {}
    if isinstance(t, dict) and not is_mark(t):
        for k, v in t.items():
            if isinstance(k, str) and not k.startswith("$"):
                out[k] = v
            elif isinstance(k, str) and k.startswith("$$"):
                out[k[1:]] = v  # 入力の `$` で始まるキー（raw では `$` をもう 1 つ付けてある）
    elif isinstance(t, list):
        for item in t:
            if isinstance(item, dict) and not is_mark(item):
                k = get(item, "key")
                if isinstance(k, str):
                    out.setdefault(k, item.get("Value", item.get("value")))
    return out


def name_tag(props: dict) -> str | None:
    """`Name` タグの値（印でない文字列のときだけ）。"""
    return plain_str(tags(props).get("Name"))


def strings_in(value):
    """値の中の、印でない文字列をすべて（`$json` の中身も歩く。`$concat` の中の文字列の断片は返さない）。決まった順で返す。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        if "$json" in value:
            yield from strings_in(value["$json"])
        elif not is_mark(value):
            for k in value:
                yield from strings_in(value[k])
    elif isinstance(value, list):
        for x in value:
            yield from strings_in(x)


def split_tf_address(address: str) -> list[str]:
    """TF の address を `.` で分ける（`["…"]` の中の `.` では分けない）。"""
    parts, buf, depth, quoted = [], "", 0, False
    for ch in address:
        if ch == '"' and depth:
            quoted = not quoted
        elif ch == "[" and not quoted:
            depth += 1
        elif ch == "]" and not quoted:
            depth -= 1
        if ch == "." and not depth and not quoted:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return parts


@dataclass(frozen=True)
class Resource:
    """raw IR のリソース 1 件（読むだけ）。`props` は raw のまま（印を含む）。"""
    address: str
    type: str
    file: str
    enabled: bool | None
    props: MappingProxyType
    fmt: str
    via: str | None = None
    module: str | None = None
    multiplicity: str | None = None
    source: str | None = None
    version: str | None = None
    region: str | None = None

    @property
    def is_data(self) -> bool:
        """TF の `data` ブロックか。address だけで決める（`module.x.data.…`。`module.<名前>[キー]` の組を前から外した次が `data`）。"""
        if self.fmt != "tf":
            return False
        parts = split_tf_address(self.address)
        i = 0
        while i + 1 < len(parts) and parts[i] == "module":
            i += 2
        return len(parts) - i >= 3 and parts[i] == "data"

    def get(self, name: str):
        return get(dict(self.props), name)


def is_depends_on(ref: dict) -> bool:
    """DependsOn（TF の `depends_on`、CFN の `DependsOn`）の参照か。"""
    return ref.get("fn") in ("depends_on", "DependsOn") or ref.get("path") in ("depends_on", "DependsOn")


class Index:
    """raw IR の索引（段階 0）。リソースは raw の順、参照は `active` のものだけ（raw の順）。"""

    def __init__(self, raw: dict):
        self.fmt: str = raw["format"]
        self.root: str = raw.get("root", "")
        self.resources: tuple[Resource, ...] = tuple(
            Resource(address=r["address"], type=r["type"], file=r.get("file", ""), enabled=r.get("enabled"),
                     props=MappingProxyType(r.get("props") or {}), fmt=self.fmt, via=r.get("via"), module=r.get("module"),
                     multiplicity=r.get("multiplicity"), source=r.get("source"), version=r.get("version"), region=r.get("region"))
            for r in raw.get("resources", []))
        self.by_address: dict[str, Resource] = {r.address: r for r in self.resources}
        self.refs_from: dict[str, list[dict]] = {}
        self.refs_to: dict[str, list[dict]] = {}
        for ref in raw.get("references", []):
            if ref.get("state") != "active":
                continue
            self.refs_from.setdefault(ref["from"], []).append(ref)
            self.refs_to.setdefault(ref["to"], []).append(ref)

    def neighbors(self, address: str, depends_on: bool = False) -> list[str]:
        """address が参照するリソースと、address を参照するリソース（重なりなし、名前順）。`depends_on` が偽なら DependsOn 以外の
        参照だけ、真なら DependsOn の参照だけ（DependsOn は弱い手がかりなので、ほかに無いときだけ使う）。"""
        out = {ref["to"] for ref in self.refs_from.get(address, ()) if is_depends_on(ref) == depends_on}
        out |= {ref["from"] for ref in self.refs_to.get(address, ()) if is_depends_on(ref) == depends_on}
        out.discard(address)
        return sorted(out)

    def referrers(self, address: str) -> list[str]:
        """address を参照する（DependsOn を除く）リソース（名前順）。"""
        return sorted({ref["from"] for ref in self.refs_to.get(address, ()) if not is_depends_on(ref)} - {address})
