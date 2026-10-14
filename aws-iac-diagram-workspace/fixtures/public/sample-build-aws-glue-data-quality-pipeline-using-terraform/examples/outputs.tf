output "s3_bucket_name" {
  description = "Name of the created S3 bucket"
  value       = module.s3_bucket.bucket_id
}

output "s3_bucket_arn" {
  description = "ARN of the created S3 bucket"
  value       = module.s3_bucket.bucket_arn
}

output "glue_role_arn" {
  description = "ARN of the Glue IAM role"
  value       = module.iam.glue_role_arn
}

output "glue_job_name" {
  description = "Name of the created Glue data quality job"
  value       = module.glue_data_quality.glue_job_name
}





output "quick_start_commands" {
  description = "Commands to get started with the data quality pipeline"
  value = {

    run_job     = "aws glue start-job-run --job-name ${module.glue_data_quality.glue_job_name}"
    check_results = "aws s3 ls s3://${module.s3_bucket.bucket_id}/dq-results/ --recursive"
  }
}