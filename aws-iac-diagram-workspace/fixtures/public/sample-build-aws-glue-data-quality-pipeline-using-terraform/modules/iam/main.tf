data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_iam_policy_document" "glue_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
    
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "glue_role" {
  name                 = "aws-glue-data-quality-role-${var.environment}"
  assume_role_policy   = data.aws_iam_policy_document.glue_assume_role.json
  max_session_duration = 3600
  
  tags = merge(var.tags, {
    Name = "aws-glue-data-quality-role-${var.environment}"
  })
}

data "aws_iam_policy_document" "glue_minimal_policy" {
  # S3 permissions - only what's needed
  statement {
    sid    = "S3ReadAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject"
    ]
    resources = ["${var.s3_bucket_arn}/data/*", "${var.s3_bucket_arn}/glue-scripts/*"]
  }
  
  statement {
    sid    = "S3WriteResults"
    effect = "Allow"
    actions = [
      "s3:PutObject"
    ]
    resources = [
      "${var.s3_bucket_arn}/dq-results/*",
      "${var.s3_bucket_arn}/catalog-dq-results/*",
      "${var.s3_bucket_arn}/glue-temp/*"
    ]
  }
  
  statement {
    sid    = "S3ListBucket"
    effect = "Allow"
    actions = [
      "s3:ListBucket"
    ]
    resources = [var.s3_bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["data/*", "dq-results/*", "glue-temp/*"]
    }
  }
  
  # CloudWatch Logs - for jobs and crawlers
  statement {
    sid    = "CloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    resources = [
      "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws-glue/jobs/*",
      "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws-glue/crawlers*"
    ]
  }
  
  # CloudWatch Metrics - required for data quality
  statement {
    sid    = "CloudWatchMetrics"
    effect = "Allow"
    actions = [
      "cloudwatch:PutMetricData"
    ]
    resources = ["*"]
  }
  
  # Data Quality Publishing - required for results publishing
  statement {
    sid    = "DataQualityPublishing"
    effect = "Allow"
    actions = [
      "glue:PublishDataQuality",
      "glue:GetDataQualityResult",
      "glue:BatchGetDataQualityResult"
    ]
    resources = [
      "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:dataQualityRuleset/*"
    ]
  }
  
  # Glue Catalog - required for catalog-based data quality
  statement {
    sid    = "GlueCatalogAccess"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:CreateTable",
      "glue:UpdateTable",
      "glue:DeleteTable",
      "glue:BatchCreatePartition",
      "glue:BatchDeletePartition",
      "glue:UpdatePartition"
    ]
    resources = [
      "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:database/*",
      "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/*/*"
    ]
  }
}

resource "aws_iam_role_policy" "glue_minimal_access" {
  name   = "glue-minimal-access-${var.environment}"
  role   = aws_iam_role.glue_role.id
  policy = data.aws_iam_policy_document.glue_minimal_policy.json
}