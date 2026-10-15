"""Fixture handler (not deployed). DynamoDB stream -> SNS + S3 archive."""
import json
import os

import boto3

SNS = boto3.client("sns")
S3 = boto3.client("s3")


def handler(event, context):
    for record in event["Records"]:
        body = json.dumps(record["dynamodb"], default=str)
        SNS.publish(TopicArn=os.environ["TOPIC_ARN"], Message=body)
        S3.put_object(Bucket=os.environ["ARCHIVE_BUCKET"], Key=f"stream/{record['eventID']}.json", Body=body)
