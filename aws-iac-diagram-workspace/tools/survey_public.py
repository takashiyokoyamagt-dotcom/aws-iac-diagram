"""公開サンプル（fixtures/public）の規模と使っている機能を数える。SELECTION.md の表の元データ。

式は評価しないので、数はブロック単位（count／for_each で増える分は数えない）。
ローカルモジュールは再帰的に数え、レジストリ／git のモジュールは呼び出しの数だけ数える。

使い方:
  .venv\\Scripts\\python.exe aws-iac-diagram-workspace\\tools\\survey_public.py [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from iac_inventory import cfn_inventory, cfn_template_features, tf_inventory  # noqa: E402

PUB = Path(__file__).resolve().parent.parent / "fixtures" / "public"

# ID → (形式, ルートの一覧)。ルートは PUB からの相対パス。TF はディレクトリ、CFN はテンプレート。
SAMPLES: dict[str, tuple[str, list[str]]] = {
    "T01": ("tf", ["serverless-patterns/eventbridge-sqs-terraform"]),
    "T02": ("tf", ["aws-transit-gateway-vpc-terraform"]),
    "T03": ("tf", ["learn-terraform-rds"]),
    "T04": ("tf", ["terraform-aws-static-website-s3-cloudfront-acm/examples/custom-error-response-and-bucket"]),
    "T05": ("tf", ["serverless-patterns/lambda-sqs-terraform"]),
    "T06": ("tf", ["serverless-patterns/eventbridge-sns-lambda-terraform"]),
    "T07": ("tf", ["serverless-patterns/apigw-lambda-dynamodb-terraform"]),
    "T08": ("tf", ["serverless-patterns/dynamodb-glue-s3-terraform"]),
    "T09": ("tf", ["sample-bedrock-knowledge-base-terraform"]),
    "T10": ("tf", ["learn-terraform-aws-asg"]),
    "T11": ("tf", ["serverless-patterns/apigw-sfn-crud-terraform"]),
    "T12": ("tf", ["sample-build-aws-glue-data-quality-pipeline-using-terraform/examples"]),
    "T13": ("tf", ["hub-and-spoke-with-shared-services-vpc-terraform"]),
    "T14": ("tf", ["terraform-aws-cloudfront/examples/complete"]),
    "T15": ("tf", ["terraform-aws-bedrock/examples/agent-with-knowledge-base"]),
    "T16": ("tf", ["learn-terraform-provision-eks-cluster"]),
    "T17": ("tf", ["amazon-ecs-fullstack-app-terraform/Infrastructure"]),
    "T18": ("tf", ["terraform-aws-eks-blueprints/patterns/blue-green-upgrade/environment",
                   "terraform-aws-eks-blueprints/patterns/blue-green-upgrade/eks-blue",
                   "terraform-aws-eks-blueprints/patterns/blue-green-upgrade/eks-green"]),
    "T19": ("tf", ["aws-network-hub-for-terraform"]),
    "T20": ("tf", []),  # iac/roots 配下の *.tf を持つディレクトリをすべて（下で展開）
    "P01": ("tf", ["terraform-aws-vpc/examples/simple", "terraform-aws-vpc/examples/complete"]),
    "P02": ("tf", ["terraform-aws-ecs/examples/fargate"]),
    "P03": ("tf", ["terraform-aws-eks/examples/eks-managed-node-group"]),
    "P04": ("tf", ["terraform-aws-rds-aurora/examples/postgresql"]),
    "C01": ("cfn", ["amazon-cloudfront-secure-static-site/templates/main.yaml"]),
    "C02": ("cfn", ["aws-cloudformation-templates/Solutions/WebApp/webapp.yaml"]),
    "C03": ("cfn", ["aws-cloudformation-templates/VPC/VPC_With_Managed_NAT_And_Private_Subnet.yaml"]),
    "C04": ("cfn", ["aws-cloudformation-templates/Solutions/VPCPeering/templates/VPCPeering-Requester.main.cfn.yaml",
                    "aws-cloudformation-templates/Solutions/VPCPeering/templates/VPCPeering-Accepter.main.cfn.yaml",
                    "aws-cloudformation-templates/Solutions/VPCPeering/templates/VPCPeering-Updates.cfn.yaml"]),
    "C05": ("cfn", ["ecs-refarch-cloudformation/master.yaml"]),
    # SAM 版（T01/T05/T06/T07/T11 の対）
    "T01s": ("cfn", ["serverless-patterns/eventbridge-sqs/template.yaml"]),
    "T05s": ("cfn", ["serverless-patterns/lambda-sqs/template.yaml"]),
    "T06s": ("cfn", ["serverless-patterns/eventbridge-sns-lambda/template.yaml"]),
    "T07s": ("cfn", ["serverless-patterns/apigw-lambda-dynamodb/template.yaml"]),
    "T11s": ("cfn", ["serverless-patterns/apigw-sfn-crud/template.yaml"]),
}


def t20_roots() -> list[str]:
    base = PUB / "sample-multi-source-cdc-iceberg-lakehouse" / "iac" / "roots"
    dirs = sorted({p.parent for p in base.rglob("*.tf")})
    return [d.relative_to(PUB).as_posix() for d in dirs]


def survey_tf(roots: list[str]) -> dict:
    res = Counter()
    types: Counter = Counter()
    reg_modules: list[str] = []
    feat = Counter()
    errors = []
    for r in roots:
        d = PUB / r
        try:
            blocks = tf_inventory(d)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{r}: {type(e).__name__}: {e}")
            continue
        for b in blocks:
            if b.kind == "resource":
                res["resource"] += 1
                types[b.type] += 1
                feat["count"] += b.count
                feat["for_each"] += b.for_each
            elif b.kind == "data":
                res["data"] += 1
            elif b.kind == "module":
                if b.local:
                    res["module_local"] += 1
                else:
                    res["module_remote"] += 1
                    reg_modules.append(re.sub(r"\?ref=.*$", "", b.source or ""))
                feat["count"] += b.count
                feat["for_each"] += b.for_each
        # dynamic ブロックと tfvars はテキストで数える（ローカルモジュールは含めない近似）
        for f in d.rglob("*.tf"):
            feat["dynamic"] += len(re.findall(r'^\s*dynamic\s+"', f.read_text(encoding="utf-8"), re.M))
        feat["tfvars"] += len(list(d.glob("*.tfvars")))
    providers = Counter(t.split("_", 1)[0] for t in types)
    return {
        "roots": len(roots), "resources": res["resource"], "data": res["data"],
        "module_local": res["module_local"], "module_remote": res["module_remote"],
        "remote_modules": sorted(set(reg_modules)), "distinct_types": len(types),
        "non_aws_types": sorted(t for t in types if not t.startswith("aws_")),
        "count": feat["count"], "for_each": feat["for_each"], "dynamic": feat["dynamic"],
        "tfvars": feat["tfvars"], "providers": dict(sorted(providers.items())), "errors": errors,
    }


def survey_cfn(templates: list[str]) -> dict:
    total = Counter()
    types: Counter = Counter()
    transforms: set[str] = set()
    errors = []
    nested = 0
    for t in templates:
        p = PUB / t
        try:
            inv = cfn_inventory(p)
            f = cfn_template_features(p)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{t}: {type(e).__name__}: {e}")
            continue
        for r in inv:
            types[r.type] += 1
            nested += r.type == "AWS::CloudFormation::Stack"
            total["conditional"] += r.condition is not None
        total["resources"] += len(inv)
        total["parameters"] += f["parameters"]
        total["conditions"] += f["conditions"]
        total["mappings"] += f["mappings"]
        transforms.update(f["transform"])
    return {"templates": len(templates), "resources": total["resources"], "distinct_types": len(types),
            "nested_stacks": nested, "conditional_resources": total["conditional"],
            "parameters": total["parameters"], "conditions": total["conditions"], "mappings": total["mappings"],
            "transform": sorted(transforms), "errors": errors}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = {}
    for sid, (fmt, roots) in SAMPLES.items():
        if sid == "T20":
            roots = t20_roots()
        out[sid] = {"format": fmt, **(survey_tf(roots) if fmt == "tf" else survey_cfn(roots))}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for sid, s in out.items():
        if s["format"] == "tf":
            print(f"{sid}: roots={s['roots']} res={s['resources']} data={s['data']} mod_local={s['module_local']} "
                  f"mod_remote={s['module_remote']} types={s['distinct_types']} count={s['count']} "
                  f"for_each={s['for_each']} dynamic={s['dynamic']} tfvars={s['tfvars']} "
                  f"remote={s['remote_modules']} nonaws={s['non_aws_types']} err={s['errors']}")
        else:
            print(f"{sid}: tpl={s['templates']} res={s['resources']} types={s['distinct_types']} "
                  f"nested={s['nested_stacks']} cond_res={s['conditional_resources']} params={s['parameters']} "
                  f"conds={s['conditions']} maps={s['mappings']} transform={s['transform']} err={s['errors']}")


if __name__ == "__main__":
    main()
