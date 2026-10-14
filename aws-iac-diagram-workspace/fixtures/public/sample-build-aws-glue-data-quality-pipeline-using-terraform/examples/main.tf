terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  bucket_name = "${var.bucket_prefix}-${data.aws_caller_identity.current.account_id}-${var.environment}"
}

module "s3_bucket" {
  source = "../modules/s3-bucket"

  bucket_name = local.bucket_name
  environment = var.environment
  tags        = var.tags
}

module "iam" {
  source = "../modules/iam"

  environment   = var.environment
  s3_bucket_arn = module.s3_bucket.bucket_arn
  tags          = var.tags
}

resource "aws_s3_object" "sample_data" {
  bucket = module.s3_bucket.bucket_id
  key    = "data/sample-data.parquet"
  source = "${path.module}/data/sample-data.parquet"
  etag   = filemd5("${path.module}/data/sample-data.parquet")

  lifecycle {
    precondition {
      condition     = fileexists("${path.module}/data/sample-data.parquet")
      error_message = "Sample data file does not exist at ${path.module}/data/sample-data.parquet"
    }
  }
}





resource "aws_cloudwatch_metric_alarm" "data_quality_failure" {
  alarm_name          = "glue-data-quality-failure-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "glue.driver.aggregate.numFailedTasks"
  namespace           = "Glue"
  period              = "300"
  statistic           = "Sum"
  threshold           = "0"
  alarm_description   = "This metric monitors glue data quality job failures"

  dimensions = {
    JobName = var.glue_job_name
  }
}

module "glue_data_quality" {
  source = "../modules/glue-data-quality"

  depends_on = [module.iam, module.s3_bucket, aws_s3_object.sample_data]

  environment               = var.environment
  s3_bucket_name            = module.s3_bucket.bucket_id
  s3_bucket_arn             = module.s3_bucket.bucket_arn
  glue_role_arn             = module.iam.glue_role_arn
  glue_job_name             = var.glue_job_name
  glue_job_timeout          = var.glue_job_timeout
  glue_worker_type          = var.glue_worker_type
  glue_number_of_workers    = var.glue_number_of_workers
  cloudwatch_retention_days = var.cloudwatch_retention_days

  # ETL Data Quality Configuration
  enable_schedule        = var.enable_schedule
  schedule_expression    = var.schedule_expression
  enable_data_lineage    = var.enable_data_lineage
  data_quality_threshold = var.data_quality_threshold

  # ============================================================================
  # [NEW] Catalog Data Quality Configuration
  # Added to support catalog-based data quality validation
  # Set catalog_dq_enabled = true to create:
  #   - Glue Database for catalog tables
  #   - Glue Crawler for automatic schema discovery
  #   - Catalog Data Quality Glue Job
  #   - Scheduled triggers for crawler and DQ job
  #   - CloudWatch alarms for monitoring
  # ============================================================================
  catalog_dq_enabled          = var.catalog_dq_enabled
  catalog_database_name       = var.catalog_database_name
  s3_data_paths               = var.s3_data_paths
  catalog_table_names         = var.catalog_table_names
  catalog_dq_rules            = var.catalog_dq_rules
  catalog_enable_schedule     = var.catalog_enable_schedule
  catalog_schedule_expression = var.catalog_schedule_expression
  catalog_crawler_schedule    = var.catalog_crawler_schedule

  tags = var.tags
}
