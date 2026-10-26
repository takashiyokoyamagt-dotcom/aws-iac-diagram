"""Terraform のモジュールの source の見分け（ファイルは読まない）。

ローカルのパスか、レジストリの source か（ホスト名を除いた形にする）。要約表の中の module ブロックのローカルの source を、
要約表の source にする。ir-schema.md の 7.2。
"""
from __future__ import annotations

import re

_REGISTRY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_-]*/[A-Za-z0-9][A-Za-z0-9_-]*$")


def is_local(source: str) -> bool:
    """ローカルのパス（./・../ で始まる。Terraform と同じ）か。"""
    return source.startswith(("./", "../")) or source in (".", "..")


def registry_key(source: str) -> str | None:
    """レジストリの source なら、ホスト名を除いた形（namespace/name/provider、サブモジュールは //path 付き）。"""
    s = source.strip()
    for host in ("registry.terraform.io/", "registry.opentofu.org/"):
        if s.startswith(host):
            s = s[len(host):]
    if "::" in s or "://" in s or "?" in s or s.startswith(("github.com/", "bitbucket.org/", "git@")):
        return None
    base, _, sub = s.partition("//")
    if not _REGISTRY.match(base):
        return None
    sub = "/".join(p for p in sub.split("/") if p and p != ".")
    return base + (f"//{sub}" if sub else "")


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
