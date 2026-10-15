locals {
  name            = var.project
  collection_name = "${local.name}-kb"
  index_name      = "${local.name}-index"

  # モデルはリソースではなく文字列の ARN で指定する（正規化で bedrock_model ノードを作る: N-BEDROCK-MODEL）
  embedding_model_arn  = "arn:aws:bedrock:${var.region}::foundation-model/${var.embedding_model_id}"
  generation_model_arn = "arn:aws:bedrock:${var.region}::foundation-model/${var.generation_model_id}"
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------- S3 (data source documents)

resource "aws_s3_bucket" "docs" {
  bucket = "${local.name}-docs"
}

resource "aws_s3_bucket_versioning" "docs" {
  bucket = aws_s3_bucket.docs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "docs" {
  bucket                  = aws_s3_bucket.docs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# ---------------------------------------------------------------- OpenSearch Serverless (vector store)

resource "aws_opensearchserverless_security_policy" "encryption" {
  name = local.collection_name
  type = "encryption"
  policy = jsonencode({
    Rules = [
      {
        ResourceType = "collection"
        Resource     = ["collection/${local.collection_name}"]
      }
    ]
    AWSOwnedKey = true
  })
}

resource "aws_opensearchserverless_security_policy" "network" {
  name = local.collection_name
  type = "network"
  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "collection"
          Resource     = ["collection/${local.collection_name}"]
        }
      ]
      AllowFromPublic = true
    }
  ])
}

resource "aws_opensearchserverless_access_policy" "data" {
  name = local.collection_name
  type = "data"
  policy = jsonencode([
    {
      Rules = [
        {
          ResourceType = "index"
          Resource     = ["index/${local.collection_name}/*"]
          Permission   = ["aoss:CreateIndex", "aoss:DescribeIndex", "aoss:ReadDocument", "aoss:WriteDocument", "aoss:UpdateIndex", "aoss:DeleteIndex"]
        },
        {
          ResourceType = "collection"
          Resource     = ["collection/${local.collection_name}"]
          Permission   = ["aoss:CreateCollectionItems", "aoss:DescribeCollectionItems", "aoss:UpdateCollectionItems"]
        }
      ]
      Principal = [aws_iam_role.kb.arn, data.aws_caller_identity.current.arn]
    }
  ])
}

resource "aws_opensearchserverless_collection" "kb" {
  name = local.collection_name
  type = "VECTORSEARCH"

  depends_on = [
    aws_opensearchserverless_security_policy.encryption,
    aws_opensearchserverless_security_policy.network,
    aws_opensearchserverless_access_policy.data,
  ]
}

resource "opensearch_index" "kb" {
  name                           = local.index_name
  number_of_shards               = "2"
  number_of_replicas             = "0"
  index_knn                      = true
  index_knn_algo_param_ef_search = "512"
  force_destroy                  = true
  mappings = jsonencode({
    properties = {
      embedding = {
        type      = "knn_vector"
        dimension = 1024
        method = {
          name       = "hnsw"
          engine     = "faiss"
          space_type = "l2"
        }
      }
      text     = { type = "text" }
      metadata = { type = "text", index = false }
    }
  })

  depends_on = [aws_opensearchserverless_collection.kb]
}

# アクセスポリシーの反映待ち（ユーティリティ。H-UTILITY）
resource "time_sleep" "wait_for_policies" {
  create_duration = "30s"

  depends_on = [
    aws_opensearchserverless_access_policy.data,
    aws_iam_role_policy.kb,
  ]
}

# ---------------------------------------------------------------- Bedrock Knowledge Base

data "aws_iam_policy_document" "bedrock_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "kb" {
  name               = "${local.name}-kb"
  assume_role_policy = data.aws_iam_policy_document.bedrock_assume.json
}

data "aws_iam_policy_document" "kb" {
  statement {
    sid       = "ReadDocs"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.docs.arn, "${aws_s3_bucket.docs.arn}/*"]
  }

  statement {
    sid       = "VectorStore"
    actions   = ["aoss:APIAccessAll"]
    resources = [aws_opensearchserverless_collection.kb.arn]
  }

  statement {
    sid       = "Embedding"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.embedding_model_arn]
  }
}

resource "aws_iam_role_policy" "kb" {
  name   = "knowledge-base"
  role   = aws_iam_role.kb.id
  policy = data.aws_iam_policy_document.kb.json
}

resource "aws_bedrockagent_knowledge_base" "docs" {
  name     = "${local.name}-kb"
  role_arn = aws_iam_role.kb.arn

  knowledge_base_configuration {
    type = "VECTOR"

    vector_knowledge_base_configuration {
      embedding_model_arn = local.embedding_model_arn
    }
  }

  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"

    opensearch_serverless_configuration {
      collection_arn    = aws_opensearchserverless_collection.kb.arn
      vector_index_name = opensearch_index.kb.name

      field_mapping {
        vector_field   = "embedding"
        text_field     = "text"
        metadata_field = "metadata"
      }
    }
  }

  depends_on = [time_sleep.wait_for_policies]
}

# 関係リソース: KB と S3 バケットを結ぶ（辺 S3 → KB に変換。R-BEDROCK-DATA-SOURCE）
resource "aws_bedrockagent_data_source" "docs" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.docs.id
  name              = "${local.name}-docs"

  data_source_configuration {
    type = "S3"

    s3_configuration {
      bucket_arn         = aws_s3_bucket.docs.arn
      inclusion_prefixes = ["docs/"]
    }
  }
}
