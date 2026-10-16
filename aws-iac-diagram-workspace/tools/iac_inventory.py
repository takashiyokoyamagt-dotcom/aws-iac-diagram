# /// script
# requires-python = ">=3.12"
# dependencies = ["python-hcl2==8.1.4", "PyYAML==6.0.3"]
# ///
"""テスト用構成（fixtures）の入力リソースを列挙する小さなライブラリ。

本番のアダプタ（PLAN 3 の ① adapters/）ではない。正解 IR の網羅分類（A6）と入力の突き合わせ、
公開サンプルの規模調査にだけ使う。式は評価しない（count／for_each／Condition は「付いているか」だけを見る）。

- Terraform: ディレクトリ直下の *.tf を python-hcl2 で読み、resource／data／module ブロックを列挙する。
  ローカルモジュール（source が ./ か ../）は再帰的に読み、アドレスに module.<名前>. を前置する。
  レジストリや git のモジュールは中身を読まず、module ブロックとして記録する。
- CloudFormation: YAML（短縮タグ !Ref などを Fn::* の長い形式に読み替える。失敗知見13）と JSON。
  AWS::CloudFormation::Stack の TemplateURL がローカルのパスなら、子テンプレートを再帰的に読み、
  論理ID に <親の論理ID>/ を前置する。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import hcl2
import yaml


# ---------------------------------------------------------------- Terraform

@dataclass
class TfBlock:
    kind: str            # resource | data | module
    type: str            # aws_vpc など。module のときは "module"
    name: str
    address: str         # module.x.aws_vpc.main / module.x.data.aws_region.current / module.x
    file: str            # ルートからの相対パス（/ 区切り）
    count: bool = False
    for_each: bool = False
    source: str | None = None   # module のときだけ
    count_expr: object = None   # count／for_each の式（python-hcl2 の値のまま。"${length(var.azs)}" など）
    module_path: str = ""       # 属するモジュールのアドレス（ルートは ""）
    local: bool = False         # module のとき、ローカルモジュールなら True


def _unq(s):
    """python-hcl2 8.x はラベルや文字列を引用符付きで返すので外す。"""
    if isinstance(s, str) and len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _load_tf_dir(d: Path) -> list[tuple[Path, dict]]:
    out = []
    for f in sorted(d.glob("*.tf")):
        with f.open(encoding="utf-8") as fh:
            out.append((f, hcl2.load(fh)))
    return out


def tf_inventory(root: Path, _dir: Path | None = None, _prefix: str = "", _seen=None) -> list[TfBlock]:
    root = Path(root)
    d = Path(_dir) if _dir else root
    seen = _seen if _seen is not None else set()
    blocks: list[TfBlock] = []
    for f, doc in _load_tf_dir(d):
        rel = os.path.relpath(f, root).replace(os.sep, "/")
        for kind in ("resource", "data"):
            for item in doc.get(kind, []):
                for rtype, named in item.items():
                    for rname, body in named.items():
                        rtype_u, rname_u = _unq(rtype), _unq(rname)
                        mid = "data." if kind == "data" else ""
                        blocks.append(TfBlock(
                            kind=kind, type=rtype_u, name=rname_u,
                            address=f"{_prefix}{mid}{rtype_u}.{rname_u}", file=rel,
                            count="count" in body, for_each="for_each" in body,
                            count_expr=body.get("count", body.get("for_each")), module_path=_prefix.rstrip(".")))
        for item in doc.get("module", []):
            for mname, body in item.items():
                mname_u = _unq(mname)
                src = _unq(body.get("source", ""))
                is_local = src.startswith("./") or src.startswith("../")
                addr = f"{_prefix}module.{mname_u}"
                blocks.append(TfBlock(kind="module", type="module", name=mname_u, address=addr, file=rel,
                                      count="count" in body, for_each="for_each" in body,
                                      source=src, local=is_local))
                if is_local:
                    sub = (d / src).resolve()
                    key = (str(sub), addr)
                    if key not in seen and sub.is_dir():
                        seen.add(key)
                        blocks.extend(tf_inventory(root, sub, addr + ".", seen))
    return blocks


def unquote_value(v):
    """python-hcl2 の値から、文字列の引用符を再帰的に外す。"""
    if isinstance(v, str):
        return _unq(v)
    if isinstance(v, list):
        return [unquote_value(x) for x in v]
    if isinstance(v, dict):
        return {_unq(k): unquote_value(x) for k, x in v.items() if k != "__is_block__"}
    return v


def tf_variables(root: Path, var_files: list[str] = ()) -> dict:
    """ルートモジュールの変数の値: variable の default → terraform.tfvars → *.auto.tfvars（名前順）→ var_files（順に）。"""
    root = Path(root)
    vals: dict = {}
    for _f, doc in _load_tf_dir(root):
        for item in doc.get("variable", []):
            for name, body in item.items():
                if "default" in body:
                    vals[_unq(name)] = unquote_value(body["default"])
    files = []
    if (root / "terraform.tfvars").exists():
        files.append(root / "terraform.tfvars")
    files += sorted(root.glob("*.auto.tfvars"))
    files += [root / f for f in var_files]
    seen = []
    for f in files:
        if f in seen:
            continue
        seen.append(f)
        with f.open(encoding="utf-8") as fh:
            vals.update({_unq(k): unquote_value(v) for k, v in hcl2.load(fh).items()})
    return vals


_EXPR = re.compile(r"^\$\{\s*(length|toset)?\(?\s*var\.([A-Za-z0-9_]+)\s*\)?\s*\}$")


def eval_instances(expr, variables: dict, is_for_each: bool):
    """count／for_each の単純な式を評価して、インスタンスのキーの一覧を返す。評価できなければ None。

    対応する式: 整数、${length(var.X)}、${var.X}（count なら数、for_each なら map のキーか set の要素）、${toset(var.X)}。
    count のキーは整数、for_each のキーは文字列。
    """
    if isinstance(expr, bool):
        return None
    if isinstance(expr, int):
        return list(range(expr)) if not is_for_each else None
    if not isinstance(expr, str):
        return None
    m = _EXPR.match(expr.strip())
    if not m or m.group(2) not in variables:
        return None
    fn, val = m.group(1), variables[m.group(2)]
    if fn == "length":
        return list(range(len(val))) if not is_for_each and isinstance(val, (list, dict)) else None
    if is_for_each:
        if isinstance(val, dict):
            return sorted(val)
        if isinstance(val, list) and (fn == "toset" or all(isinstance(x, str) for x in val)):
            return sorted(set(val))
        return None
    return list(range(val)) if isinstance(val, int) and not isinstance(val, bool) else None


def tf_var_files(root: Path) -> list[Path]:
    root = Path(root)
    return sorted(list(root.glob("*.tfvars")) + list(root.glob("**/*.tfvars")))


# ---------------------------------------------------------- CloudFormation

class CfnLoader(yaml.SafeLoader):
    """!Ref 等の短縮タグを {"Ref": ...} / {"Fn::X": ...} に読み替える（awscli の yamlhelper と同じ方式）。"""


def _cfn_tag(loader, tag_suffix, node):
    name = tag_suffix
    if isinstance(node, yaml.ScalarNode):
        val = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        val = loader.construct_sequence(node, deep=True)
    else:
        val = loader.construct_mapping(node, deep=True)
    if name == "Ref":
        return {"Ref": val}
    if name == "GetAtt" and isinstance(val, str):
        val = val.split(".", 1)
    if name == "Condition":
        return {"Condition": val}
    return {f"Fn::{name}": val}


CfnLoader.add_multi_constructor("!", _cfn_tag)


def load_cfn(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() == ".json":
        return json.loads(text)
    return yaml.load(text, Loader=CfnLoader)  # noqa: S506 (SafeLoader の派生)


@dataclass
class CfnResource:
    logical_id: str      # ネストスタックの中は "<親の論理ID>/<論理ID>"
    type: str
    file: str
    condition: str | None = None
    nested_template: str | None = None   # AWS::CloudFormation::Stack で、ローカルの子テンプレートがあるとき
    extra: dict = field(default_factory=dict)


def _local_template_url(props: dict, base: Path) -> Path | None:
    url = props.get("TemplateURL") or props.get("Location")
    if not isinstance(url, str) or re.match(r"^[a-z]+://", url):
        return None
    p = (base / url).resolve()
    return p if p.exists() else None


def cfn_inventory(path: Path, _root: Path | None = None, _prefix: str = "") -> list[CfnResource]:
    path = Path(path)
    root = Path(_root) if _root else path.parent
    doc = load_cfn(path)
    rel = path.resolve().relative_to(root.resolve()).as_posix()
    out: list[CfnResource] = []
    for lid, body in (doc.get("Resources") or {}).items():
        rtype = body.get("Type", "")
        r = CfnResource(logical_id=f"{_prefix}{lid}", type=rtype, file=rel, condition=body.get("Condition"))
        if rtype in ("AWS::CloudFormation::Stack", "AWS::Serverless::Application"):
            child = _local_template_url(body.get("Properties") or {}, path.parent)
            if child:
                r.nested_template = child.relative_to(root.resolve()).as_posix()
                out.append(r)
                out.extend(cfn_inventory(child, root, f"{_prefix}{lid}/"))
                continue
        out.append(r)
    return out


def cfn_template_features(path: Path) -> dict:
    doc = load_cfn(path)
    tr = doc.get("Transform")
    if isinstance(tr, str):
        tr = [tr]
    return {
        "transform": tr or [],
        "parameters": len(doc.get("Parameters") or {}),
        "conditions": len(doc.get("Conditions") or {}),
        "mappings": len(doc.get("Mappings") or {}),
        "resources": len(doc.get("Resources") or {}),
    }
