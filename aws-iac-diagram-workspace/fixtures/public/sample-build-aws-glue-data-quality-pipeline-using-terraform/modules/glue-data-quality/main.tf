locals {
  script_path = "${path.root}/../scripts/GlueDataQualityDynamicRules.py"
}

resource "aws_cloudwatch_log_group" "glue_log_group" {
  name              = "/aws-glue/jobs/${var.glue_job_name}"
  retention_in_days = var.cloudwatch_retention_days
  tags              = var.tags
}

resource "aws_s3_object" "glue_script" {
  bucket = var.s3_bucket_name
  key    = "glue-scripts/GlueDataQualityDynamicRules.py"
  source = local.script_path
  etag   = filemd5(local.script_path)
  tags   = var.tags

  lifecycle {
    precondition {
      condition     = fileexists(local.script_path)
      error_message = "Glue script file does not exist at ${local.script_path}"
    }
  }
}

resource "aws_glue_job" "data_quality_job" {
  depends_on = [aws_s3_object.glue_script]

  name              = var.glue_job_name
  role_arn          = var.glue_role_arn
  glue_version      = "5.0"
  worker_type       = var.glue_worker_type
  number_of_workers = var.glue_number_of_workers
  timeout           = var.glue_job_timeout
  max_retries       = 0

  command {
    script_location = "s3://${var.s3_bucket_name}/glue-scripts/GlueDataQualityDynamicRules.py"
    python_version  = "3"
  }

  default_arguments = {
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-glue-datacatalog"          = "true"
    "--job-bookmark-option"              = "job-bookmark-enable"
    "--TempDir"                          = "s3://${var.s3_bucket_name}/glue-temp/"
    "--S3_BUCKET_NAME"                   = var.s3_bucket_name
    "--ENVIRONMENT"                      = var.environment
    "--DATA_QUALITY_THRESHOLD"           = tostring(var.data_quality_threshold)
    "--ENABLE_DATA_LINEAGE"              = tostring(var.enable_data_lineage)
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags = var.tags
}

resource "aws_glue_trigger" "data_quality_schedule" {
  count = var.enable_schedule ? 1 : 0

  name     = "${var.glue_job_name}-schedule"
  type     = "SCHEDULED"
  schedule = var.schedule_expression
  enabled  = true

  actions {
    job_name = aws_glue_job.data_quality_job.name
  }

  tags = var.tags
}

resource "aws_cloudwatch_dashboard" "data_quality_dashboard" {
  dashboard_name = "DataQuality-${var.environment}"

  dashboard_body = jsonencode({
    widgets = concat([
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6

        properties = {
          metrics = [
            ["AWS/Glue", "glue.driver.aggregate.numCompletedTasks", "JobName", var.glue_job_name],
            [".", "glue.driver.aggregate.numFailedTasks", ".", "."]
          ]
          view   = "timeSeries"
          region = data.aws_region.current.name
          title  = "ETL Data Quality Job Metrics"
          period = 300
        }
      }
      ], var.catalog_dq_enabled ? [
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6

        properties = {
          metrics = [
            ["AWS/Glue", "glue.driver.aggregate.numCompletedTasks", "JobName", "${var.glue_job_name}-catalog"],
            [".", "glue.driver.aggregate.numFailedTasks", ".", "."]
          ]
          view   = "timeSeries"
          region = data.aws_region.current.name
          title  = "Catalog Data Quality Job Metrics"
          period = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 6
        height = 6

        properties = {
          metrics = [
            ["AWS/Glue", "glue.driver.aggregate.numCompletedTasks", "JobName", var.glue_job_name],
            [".", "glue.driver.aggregate.numCompletedTasks", "JobName", "${var.glue_job_name}-catalog"]
          ]
          view   = "timeSeries"
          region = data.aws_region.current.name
          title  = "ETL vs Catalog DQ Comparison"
          period = 300
        }
      },
      {
        type   = "metric"
        x      = 6
        y      = 12
        width  = 6
        height = 6

        properties = {
          metrics = [
            ["AWS/Glue", "glue.ALL.s3.filesystem.read_bytes", "JobName", "${var.glue_job_name}-catalog"],
            [".", "glue.ALL.s3.filesystem.write_bytes", ".", "."]
          ]
          view   = "timeSeries"
          region = data.aws_region.current.name
          title  = "Catalog DQ Data Processing"
          period = 300
        }
      }
    ] : [])
  })
}

data "aws_region" "current" {}

# ============================================================================
# [NEW] Catalog-based Data Quality Resources
# Added to support catalog-based data quality validation feature
# These resources enable data quality validation directly against
# Glue Data Catalog tables without requiring ETL job execution
# ============================================================================

# [NEW] Glue Database for catalog tables
resource "aws_glue_catalog_database" "data_quality_db" {
  count = var.catalog_dq_enabled ? 1 : 0

  name        = var.catalog_database_name
  description = "Database for catalog-based data quality tables in ${var.environment} environment"

  tags = var.tags
}

# [NEW] Glue Crawler for automatic schema discovery from S3 parquet data
resource "aws_glue_crawler" "catalog_crawler" {
  count = var.catalog_dq_enabled ? 1 : 0

  database_name = aws_glue_catalog_database.data_quality_db[0].name
  name          = "${var.glue_job_name}-catalog-crawler"
  role          = var.glue_role_arn
  description   = "Crawler for discovering schema from S3 parquet data for catalog-based data quality"

  dynamic "s3_target" {
    for_each = var.s3_data_paths
    content {
      path = "s3://${var.s3_bucket_name}/${s3_target.value}"
    }
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  recrawl_policy {
    recrawl_behavior = "CRAWL_EVERYTHING"
  }

  configuration = jsonencode({
    Version = 1.0
    CrawlerOutput = {
      Partitions = { AddOrUpdateBehavior = "InheritFromTable" }
      Tables     = { AddOrUpdateBehavior = "MergeNewColumns" }
    }
  })

  tags = var.tags
}

# [NEW] Scheduled trigger for crawler execution
resource "aws_glue_trigger" "crawler_schedule" {
  count = var.catalog_dq_enabled ? 1 : 0

  name     = "${var.glue_job_name}-crawler-schedule"
  type     = "SCHEDULED"
  schedule = var.catalog_crawler_schedule
  enabled  = true

  actions {
    crawler_name = aws_glue_crawler.catalog_crawler[0].name
  }

  tags = var.tags
}

# [NEW] Local variable for catalog script path
locals {
  catalog_script_path = "${path.root}/../scripts/CatalogDataQuality.py"
}

# [NEW] Upload catalog data quality script to S3
resource "aws_s3_object" "catalog_glue_script" {
  count = var.catalog_dq_enabled ? 1 : 0

  bucket = var.s3_bucket_name
  key    = "glue-scripts/CatalogDataQuality.py"
  source = local.catalog_script_path
  etag   = filemd5(local.catalog_script_path)
  tags   = var.tags

  lifecycle {
    precondition {
      condition     = fileexists(local.catalog_script_path)
      error_message = "Catalog Glue script file does not exist at ${local.catalog_script_path}"
    }
  }
}

# [NEW] Glue Job for catalog-based data quality validation
resource "aws_glue_job" "catalog_data_quality_job" {
  count = var.catalog_dq_enabled ? 1 : 0

  depends_on = [aws_s3_object.catalog_glue_script, aws_glue_crawler.catalog_crawler]

  name              = "${var.glue_job_name}-catalog"
  role_arn          = var.glue_role_arn
  glue_version      = "5.0"
  worker_type       = var.glue_worker_type
  number_of_workers = var.glue_number_of_workers
  timeout           = var.glue_job_timeout
  max_retries       = 0

  command {
    script_location = "s3://${var.s3_bucket_name}/glue-scripts/CatalogDataQuality.py"
    python_version  = "3"
  }

  default_arguments = {
    "--enable-metrics"                   = "true"
    "--enable-continuous-cloudwatch-log" = "true"
    "--enable-glue-datacatalog"          = "true"
    "--job-bookmark-option"              = "job-bookmark-enable"
    "--TempDir"                          = "s3://${var.s3_bucket_name}/glue-temp/"
    "--DATABASE_NAME"                    = var.catalog_database_name
    "--TABLE_NAMES"                      = join(",", var.catalog_table_names)
    "--DQ_RULES"                         = var.catalog_dq_rules
    "--S3_BUCKET_NAME"                   = var.s3_bucket_name
    "--ENVIRONMENT"                      = var.environment
    "--DATA_QUALITY_THRESHOLD"           = tostring(var.data_quality_threshold)
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags = var.tags
}

# [NEW] Scheduled trigger for catalog data quality job
resource "aws_glue_trigger" "catalog_data_quality_schedule" {
  count = var.catalog_dq_enabled && var.catalog_enable_schedule ? 1 : 0

  name     = "${var.glue_job_name}-catalog-schedule"
  type     = "SCHEDULED"
  schedule = var.catalog_schedule_expression
  enabled  = true

  actions {
    job_name = aws_glue_job.catalog_data_quality_job[0].name
  }

  tags = var.tags
}

# [NEW] CloudWatch alarm for catalog data quality job failures
resource "aws_cloudwatch_metric_alarm" "catalog_data_quality_failure" {
  count = var.catalog_dq_enabled ? 1 : 0

  alarm_name          = "catalog-glue-data-quality-failure-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "glue.driver.aggregate.numFailedTasks"
  namespace           = "AWS/Glue"
  period              = "300"
  statistic           = "Sum"
  threshold           = "0"
  alarm_description   = "This metric monitors catalog-based glue data quality job failures"
  treat_missing_data  = "notBreaching"

  dimensions = {
    JobName = "${var.glue_job_name}-catalog"
  }

  tags = var.tags
}

# [NEW] CloudWatch alarm for catalog crawler failures
resource "aws_cloudwatch_metric_alarm" "catalog_crawler_failure" {
  count = var.catalog_dq_enabled ? 1 : 0

  alarm_name          = "catalog-crawler-failure-${var.environment}"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "glue.driver.aggregate.numCompletedTasks"
  namespace           = "AWS/Glue"
  period              = "3600"
  statistic           = "Sum"
  threshold           = "1"
  alarm_description   = "This metric monitors catalog crawler execution failures"
  treat_missing_data  = "breaching"

  dimensions = {
    JobName = "${var.glue_job_name}-catalog-crawler"
  }

  tags = var.tags
}
