"""Fixture handler (not deployed). S3 ObjectCreated -> Bedrock StartIngestionJob."""
import os

import boto3

AGENT = boto3.client("bedrock-agent")


def handler(event, context):
    AGENT.start_ingestion_job(knowledgeBaseId=os.environ["KNOWLEDGE_BASE_ID"], dataSourceId=os.environ["DATA_SOURCE_ID"])
