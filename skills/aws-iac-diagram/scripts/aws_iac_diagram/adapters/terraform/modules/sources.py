"""Terraform のモジュールの source の見分け（ファイルは読まない）。

ローカルのパスか、レジストリの source か（ホスト名を除いた形にする。後者は core/module_sources.py の `registry_key`）。要約表の中の module ブロックのローカルの source を、
要約表の source にする。docs/spec/ir-schema/ の 7.2。
"""
from __future__ import annotations

from aws_iac_diagram.core.module_sources import registry_key  # レジストリの source の形（IAM だけのモジュールの判定と共通なので core にある）

__all__ = ["is_local", "join_summary_source", "registry_key"]


def is_local(source: str) -> bool:
    """ローカルのパス（./・../ で始まる。Terraform と同じ）か。"""
    return source.startswith(("./", "../")) or source in (".", "..")


def join_summary_source(parent: str, local: str) -> str | None:
    """要約表の中の module ブロックのローカルの source（"./modules/x"）を、要約表の source にする。"""
    base, _, sub = parent.partition("//")
    parts = [p for p in sub.split("/") if p]
    for p in local.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(p)
    return base + ("//" + "/".join(parts) if parts else "")
