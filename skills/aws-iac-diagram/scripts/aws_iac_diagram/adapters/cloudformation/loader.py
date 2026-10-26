"""テンプレートの読み込み: YAML の短縮タグ（!Ref など）を Fn::* の長い形にし、JSON も読む。"""
from __future__ import annotations

import json
from pathlib import Path

import yaml


class _Loader(yaml.SafeLoader):
    """短縮タグを Fn::* の長い形にする。日付・時刻の暗黙の型変換はしない（'2010-09-09' を文字列のまま読む）。

    値の真偽値は YAML 1.1 のまま（yes・on なども真偽値。cfn-lint と同じ）。マップのキーは元の文字のまま読む
    （Yes・On・1 のようなキーも文字列の名前として残す。条件・リソース・Mappings の名前を失わないように）。
    """

    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.MappingNode):
            return super().construct_mapping(node, deep=deep)
        self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.ScalarNode):
                key = key_node.value
            else:
                key = self.construct_object(key_node, deep=True)
            mapping[key] = self.construct_object(value_node, deep=True)
        return mapping


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
YAML11_TRUE = {"yes", "true", "on"}
YAML11_FALSE = {"no", "false", "off"}


def bool_name(value, names):
    """名前の位置に YAML 1.1 の真偽値として読まれた値（Condition: Yes など）を、元の名前に戻す。決まらなければ None。"""
    if not isinstance(value, bool):
        return value if isinstance(value, str) else None
    words = YAML11_TRUE if value else YAML11_FALSE
    hits = [n for n in names if isinstance(n, str) and n.lower() in words]
    return hits[0] if len(hits) == 1 else None


def _intrinsic(loader: yaml.Loader, suffix: str, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    if suffix == "Ref":
        return {"Ref": value}
    if suffix == "Condition":
        return {"Condition": value}
    if suffix == "GetAtt" and isinstance(value, str):
        # !GetAtt A.B.C → ["A", "B.C"]（最初の . で分ける）
        value = value.split(".", 1)
    return {f"Fn::{suffix}": value}


_Loader.add_multi_constructor("!", _intrinsic)


def load_template(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    # 拡張子によらず、{ で始まれば先に JSON として読む（.template の JSON にはタブの字下げがあり、YAML では読めない）
    if path.suffix.lower() == ".json" or text.lstrip().startswith("{"):
        try:
            doc = json.loads(text)
        except ValueError:
            if path.suffix.lower() == ".json":
                raise
            doc = yaml.load(text, Loader=_Loader)  # noqa: S506
    else:
        doc = yaml.load(text, Loader=_Loader)  # noqa: S506  _Loader は SafeLoader を元にしている
    if not isinstance(doc, dict):
        raise ValueError("テンプレートの最上位がオブジェクトではない")
    return doc
