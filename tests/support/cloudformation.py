"""CloudFormation アダプタのテストが共有する道具: 文字列から raw IR を作る、複数のファイルを一時フォルダに書く。"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

from aws_iac_diagram.adapters.cloudformation import build as cfn_build


def build(yaml_text: str, name: str = "template.yaml") -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / name
        p.write_text(textwrap.dedent(yaml_text), encoding="utf-8")
        return cfn_build.build_raw(p, Path(tmp))


BASE = """
AWSTemplateFormatVersion: '2010-09-09'
Parameters:
  Env:
    Type: String
    Default: dev
  Subnets:
    Type: CommaDelimitedList
    Default: subnet-a,subnet-b
  KeyName:
    Type: String
Resources:
  Bucket:
    Type: AWS::S3::Bucket
  Topic:
    Type: AWS::SNS::Topic
"""


def write_files(tmp: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8")


def ref_by(raw: dict, frm: str, path: str) -> list[dict]:
    return [r for r in raw["references"] if r["from"] == frm and r["path"] == path]
