"""公開サンプルの主セット（CRITERIA の 1.2。12 入力）の場所と、raw IR の作り方（正規化のテストと型の行のテストが共有する）。"""
from __future__ import annotations

from support.paths import PUBLIC, WS
from aws_iac_diagram.adapters.cloudformation import build as cfn_build  # noqa: E402
from aws_iac_diagram.adapters.terraform import build as tf_build  # noqa: E402

# CRITERIA の 1.2 の 12 入力（パスは aws-iac-diagram-workspace/tools/survey_public.py の SAMPLES と同じ）
MAIN_SET = {
    "T03": ("tf", "learn-terraform-rds"),
    "T06": ("tf", "serverless-patterns/eventbridge-sns-lambda-terraform"),
    "T06s": ("cfn", "serverless-patterns/eventbridge-sns-lambda/template.yaml"),
    "T07": ("tf", "serverless-patterns/apigw-lambda-dynamodb-terraform"),
    "T07s": ("cfn", "serverless-patterns/apigw-lambda-dynamodb/template.yaml"),
    "T09": ("tf", "sample-bedrock-knowledge-base-terraform"),
    "T11": ("tf", "serverless-patterns/apigw-sfn-crud-terraform"),
    "T11s": ("cfn", "serverless-patterns/apigw-sfn-crud/template.yaml"),
    "T12": ("tf", "sample-build-aws-glue-data-quality-pipeline-using-terraform/examples"),
    "T16": ("tf", "learn-terraform-provision-eks-cluster"),
    "C01": ("cfn", "amazon-cloudfront-secure-static-site/templates/main.yaml"),
    "C02": ("cfn", "aws-cloudformation-templates/Solutions/WebApp/webapp.yaml"),
}


def main_set_raw(sid: str) -> dict:
    """主セットの入力 sid の raw IR（変数・パラメータは既定値）。"""
    fmt, rel = MAIN_SET[sid]
    return (tf_build.build_raw if fmt == "tf" else cfn_build.build_raw)(PUBLIC / rel, WS)
