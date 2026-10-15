terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
    # ベクトルインデックスの作成に使う（AWS 以外のプロバイダの型を網羅分類で扱う試験）
    opensearch = {
      source  = "opensearch-project/opensearch"
      version = "~> 2.3"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
  }
}

provider "aws" {
  region = var.region
}

provider "opensearch" {
  url         = aws_opensearchserverless_collection.kb.collection_endpoint
  aws_region  = var.region
  healthcheck = false
}
