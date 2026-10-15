data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---------------------------------------------------------------- ingest (S3 put -> StartIngestionJob)

data "archive_file" "ingest" {
  type        = "zip"
  source_dir  = "${path.module}/src/ingest"
  output_path = "${path.module}/build/ingest.zip"
}

resource "aws_iam_role" "ingest" {
  name               = "${local.name}-ingest"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "ingest_logs" {
  role       = aws_iam_role.ingest.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "ingest" {
  statement {
    actions   = ["bedrock:StartIngestionJob"]
    resources = [aws_bedrockagent_knowledge_base.docs.arn]
  }
}

resource "aws_iam_role_policy" "ingest" {
  name   = "ingest"
  role   = aws_iam_role.ingest.id
  policy = data.aws_iam_policy_document.ingest.json
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${local.name}-ingest"
  retention_in_days = 14
}

resource "aws_lambda_function" "ingest" {
  function_name    = "${local.name}-ingest"
  role             = aws_iam_role.ingest.arn
  runtime          = "python3.13"
  handler          = "app.handler"
  filename         = data.archive_file.ingest.output_path
  source_code_hash = data.archive_file.ingest.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      KNOWLEDGE_BASE_ID = aws_bedrockagent_knowledge_base.docs.id
      DATA_SOURCE_ID    = aws_bedrockagent_data_source.docs.data_source_id
    }
  }

  depends_on = [aws_cloudwatch_log_group.ingest]
}

resource "aws_lambda_permission" "s3_invoke_ingest" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.docs.arn
}

# 関係リソース: 参照はバケット通知 → バケット と → 関数。辺はバケット → 関数（R-S3-NOTIFICATION）
resource "aws_s3_bucket_notification" "docs" {
  bucket = aws_s3_bucket.docs.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "docs/"
  }

  depends_on = [aws_lambda_permission.s3_invoke_ingest]
}

# ---------------------------------------------------------------- query (API -> RetrieveAndGenerate)

data "archive_file" "query" {
  type        = "zip"
  source_dir  = "${path.module}/src/query"
  output_path = "${path.module}/build/query.zip"
}

resource "aws_iam_role" "query" {
  name               = "${local.name}-query"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "query_logs" {
  role       = aws_iam_role.query.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "query" {
  statement {
    sid       = "Retrieve"
    actions   = ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"]
    resources = [aws_bedrockagent_knowledge_base.docs.arn]
  }

  # 生成モデルは IAM の Resource ARN（文字列）からだけ分かる（推定の辺）
  statement {
    sid       = "Generate"
    actions   = ["bedrock:InvokeModel"]
    resources = [local.generation_model_arn]
  }
}

resource "aws_iam_role_policy" "query" {
  name   = "query"
  role   = aws_iam_role.query.id
  policy = data.aws_iam_policy_document.query.json
}

resource "aws_cloudwatch_log_group" "query" {
  name              = "/aws/lambda/${local.name}-query"
  retention_in_days = 14
}

resource "aws_lambda_function" "query" {
  function_name    = "${local.name}-query"
  role             = aws_iam_role.query.arn
  runtime          = "python3.13"
  handler          = "app.handler"
  filename         = data.archive_file.query.output_path
  source_code_hash = data.archive_file.query.output_base64sha256
  timeout          = 60

  environment {
    variables = {
      KNOWLEDGE_BASE_ID = aws_bedrockagent_knowledge_base.docs.id
      MODEL_ARN         = local.generation_model_arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.query]
}
