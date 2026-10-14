output "glue_job_name" {
  description = "Name of the created Glue data quality job"
  value       = aws_glue_job.data_quality_job.name
}

output "glue_job_arn" {
  description = "ARN of the created Glue data quality job"
  value       = aws_glue_job.data_quality_job.arn
}

output "glue_job_id" {
  description = "ID of the created Glue data quality job"
  value       = aws_glue_job.data_quality_job.id
}

output "cloudwatch_log_group_name" {
  description = "Name of the CloudWatch Log Group for Glue job"
  value       = aws_cloudwatch_log_group.glue_log_group.name
}

output "cloudwatch_log_group_arn" {
  description = "ARN of the CloudWatch Log Group for Glue job"
  value       = aws_cloudwatch_log_group.glue_log_group.arn
}

output "glue_script_s3_path" {
  description = "S3 path where Glue scripts should be uploaded"
  value       = "s3://${var.s3_bucket_name}/glue-scripts/"
}

output "glue_trigger_name" {
  description = "Name of the Glue trigger (if enabled)"
  value       = var.enable_schedule ? aws_glue_trigger.data_quality_schedule[0].name : null
}

output "glue_script_location" {
  description = "S3 location of the Glue script"
  value       = "s3://${var.s3_bucket_name}/glue-scripts/GlueDataQualityDynamicRules.py"
}

# Rulesets removed - can be created manually via AWS Console

output "cloudwatch_dashboard_name" {
  description = "Name of the CloudWatch dashboard"
  value       = aws_cloudwatch_dashboard.data_quality_dashboard.dashboard_name
}

output "cloudwatch_dashboard_url" {
  description = "URL to access the CloudWatch dashboard"
  value       = "https://console.aws.amazon.com/cloudwatch/home?region=${data.aws_region.current.name}#dashboards:name=${aws_cloudwatch_dashboard.data_quality_dashboard.dashboard_name}"
}

output "job_run_command" {
  description = "Command to run the data quality job"
  value       = "aws glue start-job-run --job-name ${aws_glue_job.data_quality_job.name}"
}

# ============================================================================
# [NEW] Catalog-based Data Quality Outputs
# Added to support catalog-based data quality validation feature
# These outputs provide information about:
#   - Glue Database and Crawler resources
#   - Catalog Data Quality Job
#   - S3 paths for results
#   - CLI commands for execution
#   - Monitoring URLs
# ============================================================================

# [NEW] Catalog database outputs
output "catalog_database_name" {
  description = "Name of the Glue catalog database (if enabled)"
  value       = var.catalog_dq_enabled ? aws_glue_catalog_database.data_quality_db[0].name : null
}

output "catalog_database_arn" {
  description = "ARN of the Glue catalog database (if enabled)"
  value       = var.catalog_dq_enabled ? aws_glue_catalog_database.data_quality_db[0].arn : null
}

# [NEW] Catalog crawler outputs
output "catalog_crawler_name" {
  description = "Name of the catalog crawler (if enabled)"
  value       = var.catalog_dq_enabled ? aws_glue_crawler.catalog_crawler[0].name : null
}

output "catalog_crawler_arn" {
  description = "ARN of the catalog crawler (if enabled)"
  value       = var.catalog_dq_enabled ? aws_glue_crawler.catalog_crawler[0].arn : null
}

# [NEW] Catalog data quality job outputs
output "catalog_data_quality_job_name" {
  description = "Name of the catalog data quality job (if enabled)"
  value       = var.catalog_dq_enabled ? aws_glue_job.catalog_data_quality_job[0].name : null
}

output "catalog_data_quality_job_arn" {
  description = "ARN of the catalog data quality job (if enabled)"
  value       = var.catalog_dq_enabled ? aws_glue_job.catalog_data_quality_job[0].arn : null
}

# [NEW] Catalog results S3 path
output "catalog_dq_results_s3_path" {
  description = "S3 path where catalog data quality results are stored"
  value       = var.catalog_dq_enabled ? "s3://${var.s3_bucket_name}/catalog-dq-results/" : null
}

# [NEW] Catalog script location
output "catalog_script_location" {
  description = "S3 location of the catalog data quality script"
  value       = var.catalog_dq_enabled ? "s3://${var.s3_bucket_name}/glue-scripts/CatalogDataQuality.py" : null
}

# [NEW] Catalog trigger outputs
output "catalog_trigger_name" {
  description = "Name of the catalog data quality trigger (if enabled)"
  value       = var.catalog_dq_enabled && var.catalog_enable_schedule ? aws_glue_trigger.catalog_data_quality_schedule[0].name : null
}

output "crawler_trigger_name" {
  description = "Name of the crawler trigger (if enabled)"
  value       = var.catalog_dq_enabled ? aws_glue_trigger.crawler_schedule[0].name : null
}

# [NEW] CLI commands for catalog DQ execution
output "catalog_job_run_command" {
  description = "Command to run the catalog data quality job"
  value       = var.catalog_dq_enabled ? "aws glue start-job-run --job-name ${aws_glue_job.catalog_data_quality_job[0].name}" : null
}

output "crawler_run_command" {
  description = "Command to run the catalog crawler"
  value       = var.catalog_dq_enabled ? "aws glue start-crawler --name ${aws_glue_crawler.catalog_crawler[0].name}" : null
}

# [NEW] Monitoring URLs for catalog resources
output "catalog_monitoring_urls" {
  description = "URLs for monitoring catalog data quality resources"
  value = var.catalog_dq_enabled ? {
    crawler_url  = "https://console.aws.amazon.com/glue/home?region=${data.aws_region.current.name}#crawler:name=${aws_glue_crawler.catalog_crawler[0].name}"
    job_url      = "https://console.aws.amazon.com/glue/home?region=${data.aws_region.current.name}#etl:tab=jobs;jobName=${aws_glue_job.catalog_data_quality_job[0].name}"
    database_url = "https://console.aws.amazon.com/glue/home?region=${data.aws_region.current.name}#catalog:tab=databases;database=${aws_glue_catalog_database.data_quality_db[0].name}"
  } : null
}
