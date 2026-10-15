locals {
  name           = var.project
  archive_bucket = "${local.name}-orders-archive"
}

# ---------------------------------------------------------------- DynamoDB

resource "aws_dynamodb_table" "orders" {
  name             = "${local.name}-orders"
  billing_mode     = "PAY_PER_REQUEST"
  hash_key         = "pk"
  range_key        = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }
}

# ---------------------------------------------------------------- IAM (共通)

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---------------------------------------------------------------- API handler

data "archive_file" "api_handler" {
  type        = "zip"
  source_dir  = "${path.module}/src/api_handler"
  output_path = "${path.module}/build/api_handler.zip"
}

resource "aws_iam_role" "api_handler" {
  name               = "${local.name}-api-handler"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "api_handler_logs" {
  role       = aws_iam_role.api_handler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "api_handler" {
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
    resources = [aws_dynamodb_table.orders.arn]
  }
}

resource "aws_iam_role_policy" "api_handler" {
  name   = "orders-table"
  role   = aws_iam_role.api_handler.id
  policy = data.aws_iam_policy_document.api_handler.json
}

resource "aws_cloudwatch_log_group" "api_handler" {
  name              = "/aws/lambda/${local.name}-api-handler"
  retention_in_days = 14
}

resource "aws_lambda_function" "api_handler" {
  function_name    = "${local.name}-api-handler"
  role             = aws_iam_role.api_handler.arn
  runtime          = "python3.13"
  handler          = "app.handler"
  filename         = data.archive_file.api_handler.output_path
  source_code_hash = data.archive_file.api_handler.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.orders.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.api_handler]
}

# ---------------------------------------------------------------- HTTP API

resource "aws_apigatewayv2_api" "http" {
  name          = "${local.name}-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "api_handler" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api_handler.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "this" {
  for_each = var.routes

  api_id    = aws_apigatewayv2_api.http.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api_handler.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowHttpApiInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# ---------------------------------------------------------------- stream processor

data "archive_file" "stream_processor" {
  type        = "zip"
  source_dir  = "${path.module}/src/stream_processor"
  output_path = "${path.module}/build/stream_processor.zip"
}

resource "aws_iam_role" "stream_processor" {
  name               = "${local.name}-stream-processor"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "stream_processor_logs" {
  role       = aws_iam_role.stream_processor.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "stream_processor" {
  statement {
    sid       = "ReadStream"
    actions   = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"]
    resources = [aws_dynamodb_table.orders.stream_arn]
  }

  statement {
    sid       = "Publish"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.order_events.arn]
  }

  # バケットを参照せず ARN を文字列で書いている（推定の辺の根拠: IAM の Resource ARN と名前の一致）
  statement {
    sid       = "Archive"
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${local.archive_bucket}/*"]
  }
}

resource "aws_iam_role_policy" "stream_processor" {
  name   = "stream-processor"
  role   = aws_iam_role.stream_processor.id
  policy = data.aws_iam_policy_document.stream_processor.json
}

resource "aws_cloudwatch_log_group" "stream_processor" {
  name              = "/aws/lambda/${local.name}-stream-processor"
  retention_in_days = 14
}

resource "aws_lambda_function" "stream_processor" {
  function_name    = "${local.name}-stream-processor"
  role             = aws_iam_role.stream_processor.arn
  runtime          = "python3.13"
  handler          = "app.handler"
  filename         = data.archive_file.stream_processor.output_path
  source_code_hash = data.archive_file.stream_processor.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      TOPIC_ARN      = aws_sns_topic.order_events.arn # 直接の参照（確定）
      ARCHIVE_BUCKET = local.archive_bucket           # 文字列（バケット名と一致するだけ。推定）
    }
  }

  depends_on = [aws_cloudwatch_log_group.stream_processor]
}

# 参照は ESM → テーブル（のストリーム）と ESM → 関数。データの流れはテーブル → 関数（A1、A2）
resource "aws_lambda_event_source_mapping" "orders_stream" {
  event_source_arn  = aws_dynamodb_table.orders.stream_arn
  function_name     = aws_lambda_function.stream_processor.arn
  starting_position = "LATEST"
  batch_size        = 100

  # ESM の作成時にストリームを読む権限が要る
  depends_on = [aws_iam_role_policy.stream_processor]
}

# ---------------------------------------------------------------- SNS → SQS

resource "aws_sns_topic" "order_events" {
  name = "${local.name}-order-events"
}

resource "aws_sqs_queue" "order_events" {
  name                      = "${local.name}-order-events"
  message_retention_seconds = 345600
}

resource "aws_sns_topic_subscription" "order_events_queue" {
  topic_arn            = aws_sns_topic.order_events.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.order_events.arn
  raw_message_delivery = true
}

data "aws_iam_policy_document" "order_events_queue" {
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.order_events.arn]

    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_sns_topic.order_events.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "order_events" {
  queue_url = aws_sqs_queue.order_events.id
  policy    = data.aws_iam_policy_document.order_events_queue.json
}

# ---------------------------------------------------------------- S3 archive

resource "aws_s3_bucket" "archive" {
  bucket = local.archive_bucket
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
