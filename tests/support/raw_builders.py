"""正規化の単体テスト（tests/unit/normalize/）が使う、小さな raw IR の組み立て。

アダプタを通さずに、ir-schema の 7 章の形の raw IR を手で作る（正規化の段階ごとの動きだけを見るため）。
"""
from __future__ import annotations


def resource(address: str, type_: str, props: dict | None = None, *, fmt: str = "tf", enabled=True, file: str = "main.tf",
             **extra) -> dict:
    """raw IR のリソース 1 件。`extra` は via・module・multiplicity・source・version など。"""
    r = {"address": address, "type": type_, "file": file if fmt == "tf" or file != "main.tf" else "template.yaml",
         "enabled": enabled, "props": props or {}}
    r.update(extra)
    return r


def reference(frm: str, path: str, to: str, attr=None, fn: str = "ref", state: str = "active") -> dict:
    return {"from": frm, "path": path, "to": to, "attr": attr, "fn": fn, "state": state}


def ref(frm: str, path: str, to: str, attr=None) -> dict:
    """active の参照（fn は CFN の位置なら Ref、TF なら ref）。"""
    return reference(frm, path, to, attr, fn="Ref" if path.startswith("Properties.") else "ref")


def raw_ir(fmt: str, resources: list[dict], references: list[dict] | None = None, root: str = "fixtures/x") -> dict:
    """raw IR（stage: raw）。evaluation は形式ごとの空のもの。"""
    ev = {"var_files": [], "vars": {}, "assumptions": []} if fmt == "tf" else {"parameters": {}, "conditions": {}, "assumptions": []}
    return {"ir_version": "1.0", "stage": "raw", "format": fmt, "root": root, "evaluation": ev,
            "resources": resources, "references": references or [], "diagnostics": []}
