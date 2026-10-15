"""Fixture handler (not deployed). GET/POST /orders -> DynamoDB."""
import json
import os

import boto3

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def handler(event, context):
    if event["requestContext"]["http"]["method"] == "POST":
        item = json.loads(event.get("body") or "{}")
        TABLE.put_item(Item=item)
        return {"statusCode": 201, "body": json.dumps(item)}
    resp = TABLE.query(KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": "ORDER"})
    return {"statusCode": 200, "body": json.dumps(resp["Items"], default=str)}
