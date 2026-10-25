# plan JSON の読み方の試験用の小さな構成（フェーズ2 の手順4）。図にする構成ではない。
# デプロイはしない（tools/make_plan_json.py が moto に向けて plan だけを作る）。
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "ap-northeast-1"
}

provider "aws" {
  alias  = "use1"
  region = "us-east-1"
}

variable "queues" {
  type    = list(string)
  default = ["a", "b"]
}

variable "enable_extra" {
  type    = bool
  default = false
}

# 偽の値（試験用）。sensitive の値が raw IR に出ないことを確かめる
variable "db_password" {
  type      = string
  sensitive = true
  default   = "not-a-real-password"
}

locals {
  topic_arn = aws_sns_topic.t.arn
}

data "aws_caller_identity" "me" {}

resource "aws_sns_topic" "t" {
  name = "edge-topic"
}

# for_each と、each.value（リソースのマップ）を通した参照
resource "aws_sqs_queue" "q" {
  for_each = toset(var.queues)
  name     = "edge-${each.key}"
}

resource "aws_sns_topic_subscription" "s" {
  for_each  = aws_sqs_queue.q
  topic_arn = aws_sns_topic.t.arn
  protocol  = "sqs"
  endpoint  = each.value.arn
}

# count が 0（作られない）
resource "aws_sqs_queue" "extra" {
  count = var.enable_extra ? 1 : 0
  name  = "edge-extra"
}

resource "aws_sqs_queue" "uses_extra" {
  name              = "edge-uses-extra"
  kms_master_key_id = var.enable_extra ? aws_sqs_queue.extra[0].arn : null
}

# 別のリージョンの provider（alias）
resource "aws_acm_certificate" "cert" {
  provider          = aws.use1
  domain_name       = "example.com"
  validation_method = "DNS"
}

# sensitive の変数の値
resource "aws_ssm_parameter" "p" {
  name  = "/edge/p"
  type  = "SecureString"
  value = var.db_password
}

# dynamic ブロック（plan JSON の configuration には出ない）
resource "aws_security_group" "sg" {
  name = "edge"

  dynamic "ingress" {
    for_each = [80, 443]
    content {
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = ["10.0.0.0/8"]
    }
  }
}

# locals を通した参照（plan JSON には locals の式が無い）と、jsonencode
resource "aws_sns_topic_policy" "pol" {
  arn = local.topic_arn
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "s3.amazonaws.com" }, Action = "sns:Publish", Resource = aws_sns_topic.t.arn }]
  })
}

# 擬似パラメータ（account_id）と、ほかの属性
resource "aws_sqs_queue" "acct" {
  name = "edge-${data.aws_caller_identity.me.account_id}"
}

# ローカルモジュールの count と、count が 0 の呼び出し
module "m" {
  source    = "./mod"
  count     = 2
  name      = "edge-m${count.index}"
  topic_arn = aws_sns_topic.t.arn
}

module "off" {
  source    = "./mod"
  count     = 0
  name      = "edge-off"
  topic_arn = aws_sns_topic.t.arn
}

resource "aws_sqs_queue" "dep" {
  name       = "edge-dep"
  depends_on = [module.m]
}

# モジュールの出力を通した参照
resource "aws_sqs_queue" "from_module" {
  name                       = "edge-from-module"
  redrive_allow_policy       = jsonencode({ redrivePermission = "byQueue", sourceQueueArns = [module.m[0].queue_arn] })
  visibility_timeout_seconds = 30
}

# .tf では読まない関数（file）の値は、.tf と合わせると plan の値で埋まる
resource "aws_sqs_queue" "from_file" {
  name = trimspace(file("${path.module}/name.txt"))
}
