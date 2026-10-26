"""Terraform・CloudFormation のアダプタのテストが共有する、raw IR の取り出しと検査。"""

from __future__ import annotations

import unittest

import validate_ir as v
from aws_iac_diagram.core import ir_raw


def res_of(raw: dict, address: str) -> dict:
    return next(r for r in raw["resources"] if r["address"] == address)


def props(raw: dict, address: str) -> dict:
    return res_of(raw, address)["props"]


def refs(raw: dict, frm: str | None = None) -> list[tuple]:
    return [(r["from"], r["path"], r["to"], r["attr"], r["fn"], r["state"]) for r in raw["references"]
            if frm is None or r["from"] == frm]


def assert_valid(test: unittest.TestCase, raw: dict) -> None:
    test.assertEqual(v.schema_errors(raw), [])
    test.assertEqual(ir_raw.semantic_errors(raw), [])
