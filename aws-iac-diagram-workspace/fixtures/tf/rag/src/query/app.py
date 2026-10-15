"""Fixture handler (not deployed). POST /query -> Bedrock RetrieveAndGenerate."""
import json
import os

import boto3

RUNTIME = boto3.client("bedrock-agent-runtime")


def handler(event, context):
    question = json.loads(event.get("body") or "{}").get("question", "")
    resp = RUNTIME.retrieve_and_generate(
        input={"text": question},
        retrieveAndGenerateConfiguration={
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": os.environ["KNOWLEDGE_BASE_ID"],
                "modelArn": os.environ["MODEL_ARN"],
            },
        },
    )
    return {"statusCode": 200, "body": json.dumps({"answer": resp["output"]["text"]})}
