# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML==6.0.3", "cfn-lint==1.57.2"]
# ///
"""C1（CRITERIA.md の 1.6）: cfn-lint のグラフの辺のすべてに、アダプタの出力（raw IR）の参照が対応するかを調べる。

照合のしかた（CRITERIA.md の 1.6）:
  - 入力（テンプレートか cdk.out）を CFN アダプタで読み、展開した各ファイルを cfn-lint 1.57.2 にかける。
  - cfn-lint の辺 (A, B, 属性の場所) の両端に、そのファイルの address の接頭辞（ネストスタックの "<親>/"、cdk.out の
    "<スタック名>::"）を付ける。同じファイルを2つのスタックから使うときは、接頭辞ごとに照合する。
  - 属性の場所は最初の Ref／Fn::* の位置で止め、raw IR の path と要素の区切りで前方一致（どちら向きでも）で比べる。
  - raw IR の参照の to が B か、参照の through の先頭が "<B>.Outputs." で始まれば対応とする（親のスタック → スタック）。
  - 参照の fn と state は照合に使わない（cfn-lint は Sub の中の参照を Ref／GetAtt として数え、条件も評価しない）。
逆向き（raw IR にあって cfn-lint に無い参照）は、件数を参考値として出す。

使い方:
  uv run python aws-iac-diagram-workspace/tools/c1_check.py [入力 ...] [--out <report.json>]
  入力を省くと、fixtures/cfn と fixtures/public の CFN のテンプレートをすべて探す（ほかのテンプレートの子として読まれる
  ものは、親の側で照合する）。

終了コード: 0 = すべての辺が対応した、1 = 対応の無い辺がある、2 = 入力を読めなかった
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
SCRIPTS = WS.parent / "skills" / "aws-iac-diagram" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from aws_iac_diagram.adapters.cloudformation import evaluator as cfn  # noqa: E402
from aws_iac_diagram.core import ir_raw  # noqa: E402

TEMPLATE_SUFFIXES = (".yaml", ".yml", ".json", ".template")


def lint_edges(path: Path):
    """cfn-lint のグラフのリソースどうしの辺を (A, B, 関数の位置で止めた属性の場所) で返す。"""
    from cfnlint.decode import decode
    from cfnlint.template import Template

    tpl, matches = decode(str(path))
    if tpl is None:
        raise ValueError(f"cfn-lint がテンプレートを読めません: {path}: {matches[:1]}")
    template = Template(str(path), tpl, ["us-east-1"])
    # cfn-lint --build-graph と同じく、変換（SAM の Globals を混ぜる、Fn::ForEach を展開する）の後のグラフを使う
    errors = template.transform()
    if errors:
        raise ValueError(f"cfn-lint の変換に失敗しました: {path}: {errors[:1]}")
    g = template.graph.graph
    res = {n for n, d in g.nodes.items() if d.get("type") == "Resource"}
    for a, b, d in g.edges(data=True):
        if a in res and b in res:
            p = ""
            for el in d.get("source_paths") or []:
                if isinstance(el, str) and (el == "Ref" or el.startswith("Fn::")):
                    break
                p = ir_raw.join_path(p, el)
            yield a, b, p


def prefix_match(a: str, b: str) -> bool:
    s, l = sorted((a, b), key=len)  # noqa: E741
    return l == s or l.startswith(s + ".") or l.startswith(s + "[")


def matched(raw: dict, a: str, b: str, path: str) -> bool:
    for r in raw["references"]:
        if r["from"] != a or not prefix_match(path, r["path"]):
            continue
        if r["to"] == b or (r.get("through") and r["through"][0].startswith(b + ".Outputs.")):
            return True
    return False


def root_dir(input_path: Path) -> Path:
    return input_path if input_path.is_dir() else input_path.parent


def address_prefix(address: str) -> str:
    """address の接頭辞（ネストスタックの "<親>/"、cdk.out の "<スタック名>::"）。論理ID には / も :: も入らない。"""
    i = max(address.rfind("/"), address.rfind("::") + 1 if "::" in address else -1)
    return address[: i + 1] if i >= 0 else ""


def file_prefixes(raw: dict) -> dict[str, set[str]]:
    """展開した各ファイルと、その address の接頭辞（同じファイルを2つのスタックから使えば2つ）。"""
    out: dict[str, set[str]] = {}
    for r in raw["resources"]:
        if not r.get("implicit"):
            out.setdefault(r["file"], set()).add(address_prefix(r["address"]))
    return out


def check_input(input_path: Path) -> dict:
    """1つの入力を照合する。結果: edges、unmatched（対応の無い辺）、raw_only（参考値）、files。"""
    raw = cfn.build_raw(input_path, WS)
    base = root_dir(input_path)
    edges, unmatched, seen = 0, [], set()
    prefixes_by_file = file_prefixes(raw)
    for f, prefixes in sorted(prefixes_by_file.items()):
        for prefix in sorted(prefixes):
            for a, b, p in lint_edges(base / f):
                edges += 1
                seen.add((prefix + a, prefix + b))
                if not matched(raw, prefix + a, prefix + b, p):
                    unmatched.append({"file": f, "from": prefix + a, "to": prefix + b, "path": p})
    raw_only = sum(1 for r in raw["references"]
                   if (r["from"], r["to"]) not in seen and r["fn"] not in ("DependsOn",))
    return {"input": input_path.resolve().relative_to(WS.parent).as_posix() if input_path.resolve().is_relative_to(WS.parent)
            else input_path.as_posix(),
            "files": len(prefixes_by_file), "resources": len(raw["resources"]),
            "edges": edges, "unmatched": unmatched, "raw_only_refs": raw_only}


def discover() -> list[Path]:
    """fixtures/cfn と fixtures/public の CFN のテンプレートのうち、ほかのテンプレートの子として読まれないもの。"""
    candidates = []
    for d in (WS / "fixtures" / "cfn", WS / "fixtures" / "public"):
        for p in sorted(d.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in TEMPLATE_SUFFIXES or cfn.SKIP_DIRS.intersection(p.parts):
                continue
            try:
                doc = cfn.load_template(p)
            except Exception:  # noqa: BLE001  テンプレートでないファイル（Terraform の変数ファイルなど）は飛ばす
                continue
            res = doc.get("Resources")
            if isinstance(res, dict) and any(isinstance(b, dict) and str(b.get("Type", "")).startswith(("AWS::", "Custom::"))
                                             for b in res.values()):
                candidates.append(p)
    children: set[Path] = set()
    for p in candidates:
        try:
            raw = cfn.build_raw(p, WS)
        except Exception:  # noqa: BLE001
            continue
        for r in raw["resources"]:
            if r.get("via") == "nested_stack":
                children.add((p.parent / r["file"]).resolve())
    return [p for p in candidates if p.resolve() not in children]


# CRITERIA の 1.6 の対象（主セットと補助セットの CFN、SAM 版、自作 fixture）。discover はこれをすべて含まなければならない
REQUIRED = [
    "fixtures/cfn/three-tier/template.yaml", "fixtures/cfn/serverless-api/template.yaml",
    "fixtures/cfn/vpc-endpoints/template.json", "fixtures/cfn/rag/template.yaml", "fixtures/cfn/three-tier-modules/root.yaml",
    "fixtures/public/amazon-cloudfront-secure-static-site/templates/main.yaml",  # C01
    "fixtures/public/aws-cloudformation-templates/Solutions/WebApp/webapp.yaml",  # C02
    "fixtures/public/aws-cloudformation-templates/VPC/VPC_With_Managed_NAT_And_Private_Subnet.yaml",  # C03
    "fixtures/public/aws-cloudformation-templates/Solutions/VPCPeering/templates/VPCPeering-Accepter.main.cfn.yaml",  # C04
    "fixtures/public/aws-cloudformation-templates/Solutions/VPCPeering/templates/VPCPeering-Requester.main.cfn.yaml",  # C04
    "fixtures/public/ecs-refarch-cloudformation/master.yaml",  # C05
    "fixtures/public/serverless-patterns/lambda-sqs/template.yaml",  # T01s
    "fixtures/public/serverless-patterns/eventbridge-sqs/template.yaml",  # T05s
    "fixtures/public/serverless-patterns/eventbridge-sns-lambda/template.yaml",  # T06s
    "fixtures/public/serverless-patterns/apigw-lambda-dynamodb/template.yaml",  # T07s
    "fixtures/public/serverless-patterns/apigw-sfn-crud/template.yaml",  # T11s
]


def missing_required(inputs: list[Path]) -> list[str]:
    got = {p.resolve() for p in inputs}
    return [r for r in REQUIRED if (WS / r).resolve() not in got]


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="cfn-lint のグラフと raw IR の参照を照合する（CRITERIA.md の 1.6）")
    ap.add_argument("inputs", nargs="*", type=Path)
    ap.add_argument("--out", type=Path, help="結果の JSON を書くファイル")
    a = ap.parse_args(argv)
    inputs = a.inputs or discover()
    results, code = [], 0
    if not a.inputs:
        missing = missing_required(inputs)
        for m in missing:
            print(f"NG CRITERIA の 1.6 の対象が見つからない: {m}")
        if missing:
            code = 2
    for p in inputs:
        try:
            r = check_input(p)
        except Exception as e:  # noqa: BLE001
            print(f"NG {p}: {type(e).__name__}: {e}")
            results.append({"input": p.as_posix(), "error": f"{type(e).__name__}: {e}"})
            code = 2
            continue
        results.append(r)
        mark = "OK" if not r["unmatched"] else "NG"
        print(f"{mark} {r['input']}  files={r['files']} resources={r['resources']} edges={r['edges']} "
              f"unmatched={len(r['unmatched'])} raw_only={r['raw_only_refs']}")
        for u in r["unmatched"]:
            print(f"    {u['from']} -> {u['to']} {u['path']} ({u['file']})")
        if r["unmatched"] and code == 0:
            code = 1
    total = sum(r.get("edges", 0) for r in results)
    bad = sum(len(r.get("unmatched", [])) for r in results)
    print(f"inputs={len(results)} edges={total} unmatched={bad}")
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps({"results": results, "edges": total, "unmatched": bad}, ensure_ascii=False,
                                    indent=2) + "\n", encoding="utf-8", newline="\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
