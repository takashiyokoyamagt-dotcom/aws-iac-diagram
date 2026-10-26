"""Terraform アダプタのテスト（tests/unit/terraform/ と tests/integration/terraform/）が共有する道具: 文字列から .tf を一時フォルダに書いて raw IR を作る。"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

from aws_iac_diagram.adapters.terraform import build as tf_build


def write_files(tmp: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8", newline="\n")


def build(files: dict[str, str] | str) -> dict:
    if isinstance(files, str):
        files = {"main.tf": files}
    with tempfile.TemporaryDirectory() as tmp:
        write_files(Path(tmp), files)
        return tf_build.build_raw(Path(tmp), Path(tmp))


def codes(raw: dict, address: str | None = None) -> list[str]:
    return [d["code"] for d in raw["diagnostics"] if address is None or d.get("address") == address]


def res(address: str, attr: str | None = None) -> dict:
    return {"$res": address, "attr": attr}


NETWORK = """
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "public" {
  count  = length(var.azs)
  vpc_id = aws_vpc.main.id
}
"""
