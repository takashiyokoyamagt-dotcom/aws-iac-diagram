"""cdk.out（クラウドアセンブリ）: manifest.json からスタックを集める。"""
from __future__ import annotations

import json
from pathlib import Path

from aws_iac_diagram.adapters.cloudformation.model import STACK_NAME


def _cdk_artifacts(asm_dir: Path, depth: int = 0) -> list[tuple[str, str, Path, Path]]:
    """クラウドアセンブリのスタックを (stackName, artifact の ID, テンプレート, アセンブリのフォルダ) で返す。

    CDK の Stage は入れ子のアセンブリ（type: cdk:cloud-assembly、properties.directoryName）なので、再帰で読む。
    """
    if depth > 10:
        raise ValueError("cdk.out の入れ子のアセンブリが深すぎます")
    manifest = json.loads((asm_dir / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for artifact_id, art in (manifest.get("artifacts") or {}).items():
        if not isinstance(art, dict):
            continue
        props = art.get("properties") or {}
        if art.get("type") == "cdk:cloud-assembly" and isinstance(props.get("directoryName"), str):
            sub = asm_dir / props["directoryName"]
            if (sub / "manifest.json").is_file():
                out += _cdk_artifacts(sub, depth + 1)
            continue
        if art.get("type") != "aws:cloudformation:stack" or not isinstance(props.get("templateFile"), str):
            continue
        out.append((props.get("stackName") or artifact_id, artifact_id, asm_dir / props["templateFile"], asm_dir))
    return out

def cdk_stacks(cdk_dir: Path, diagnostics: list[dict]) -> list[tuple[str, Path, Path, str]]:
    """cdk.out のスタックを (address の接頭辞に使う名前, テンプレート, アセンブリのフォルダ, stackName) で返す。

    名前は stackName。同じ stackName が2つ以上あるとき（別の環境・リージョンに同じ名前で置く）は artifact の ID を使う。
    """
    arts = _cdk_artifacts(cdk_dir)
    if not arts:
        raise ValueError("cdk.out にスタックがありません")
    counts: dict[str, int] = {}
    for name, _, _, _ in arts:
        counts[name] = counts.get(name, 0) + 1
    out = []
    for name, artifact_id, template, asm_dir in arts:
        stack_name = name
        if counts[name] > 1:
            diagnostics.append({"level": "info", "code": "CFN-CDK-STACKNAME-DUPLICATE", "address": "", "path": "",
                                "message": f"stack name {name} is used more than once; artifact id {artifact_id} is used"})
            name = artifact_id
        if not STACK_NAME.fullmatch(name):
            raise ValueError(f"cdk.out のスタック名が使えない形: {name}")
        out.append((name, template, asm_dir, stack_name))
    names = [n for n, _, _, _ in out]
    if len(set(names)) != len(names):
        raise ValueError(f"cdk.out のスタックの名前が重なっています: {sorted(n for n in set(names) if names.count(n) > 1)}")
    return sorted(out)
