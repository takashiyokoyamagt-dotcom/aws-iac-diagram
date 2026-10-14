variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

variable "s3_bucket_name" {
  description = "Name of the S3 bucket for data storage"
  type        = string
}

variable "s3_bucket_arn" {
  description = "ARN of the S3 bucket"
  type        = string
}

variable "glue_role_arn" {
  description = "ARN of the Glue IAM role"
  type        = string
}

variable "glue_job_name" {
  description = "Name of the AWS Glue data quality job"
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9_-]+$", var.glue_job_name))
    error_message = "Glue job name can only contain letters, numbers, underscores, and hyphens."
  }
}

variable "glue_job_timeout" {
  description = "Timeout for the Glue job in minutes"
  type        = number

  validation {
    condition     = var.glue_job_timeout >= 1 && var.glue_job_timeout <= 2880
    error_message = "Glue job timeout must be between 1 and 2880 minutes (48 hours)."
  }
}

variable "glue_worker_type" {
  description = "Type of worker for Glue job (G.1X, G.2X, G.4X, G.8X, Z.2X)"
  type        = string

  validation {
    condition     = contains(["G.1X", "G.2X", "G.4X", "G.8X", "Z.2X"], var.glue_worker_type)
    error_message = "Worker type must be one of: G.1X, G.2X, G.4X, G.8X, Z.2X."
  }
}

variable "glue_number_of_workers" {
  description = "Number of workers for Glue job"
  type        = number

  validation {
    condition     = var.glue_number_of_workers >= 2 && var.glue_number_of_workers <= 299
    error_message = "Number of workers must be between 2 and 299."
  }
}

variable "cloudwatch_retention_days" {
  description = "Number of days to retain CloudWatch logs"
  type        = number
  default     = 14

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1827, 3653], var.cloudwatch_retention_days)
    error_message = "CloudWatch retention days must be a valid value."
  }
}



variable "enable_schedule" {
  description = "Enable scheduled execution of the Glue job"
  type        = bool
  default     = false
}

variable "schedule_expression" {
  description = "Cron expression for scheduled execution (e.g., 'cron(0 2 * * ? *)')"
  type        = string
  default     = "cron(0 2 * * ? *)"
}



variable "enable_data_lineage" {
  description = "Enable data lineage tracking"
  type        = bool
  default     = true
}

variable "data_quality_threshold" {
  description = "Minimum data quality score threshold (0.0-1.0)"
  type        = number
  default     = 0.95

  validation {
    condition     = var.data_quality_threshold >= 0.0 && var.data_quality_threshold <= 1.0
    error_message = "Data quality threshold must be between 0.0 and 1.0."
  }
}

variable "tags" {
  description = "Common tags to be applied to all resources"
  type        = map(string)
  default     = {}
}

# ============================================================================
# [NEW] Catalog-based Data Quality Variables
# Added to support catalog-based data quality validation feature
# These variables enable configuration of:
#   - Glue Database and Crawler for automatic table discovery
#   - Catalog-specific data quality rules
#   - Independent scheduling for catalog DQ jobs
# ============================================================================

# [NEW] Enable/disable catalog-based data quality
variable "catalog_dq_enabled" {
  description = "Enable catalog-based data quality validation"
  type        = bool
  default     = false
}

# [NEW] Glue database name for catalog tables
variable "catalog_database_name" {
  description = "Name of the Glue database for catalog tables"
  type        = string
  default     = "data_quality_catalog"

  validation {
    condition     = can(regex("^[a-zA-Z0-9_-]+$", var.catalog_database_name))
    error_message = "Catalog database name can only contain letters, numbers, underscores, and hyphens."
  }
}

# [NEW] S3 paths for crawler to discover tables
variable "s3_data_paths" {
  description = "List of S3 paths containing parquet data for catalog table creation"
  type        = list(string)
  default     = ["data/"]

  validation {
    condition     = length(var.s3_data_paths) > 0
    error_message = "At least one S3 data path must be specified."
  }
}

# [NEW] Specific tables to validate (empty = all tables)
variable "catalog_table_names" {
  description = "List of catalog table names to validate (empty means all tables in database)"
  type        = list(string)
  default     = []
}

# [NEW] Data quality rules for catalog validation
variable "catalog_dq_rules" {
  description = "Data quality rules for catalog-based validation"
  type        = string
  default     = ""
}

# [NEW] Enable scheduled execution for catalog DQ
variable "catalog_enable_schedule" {
  description = "Enable scheduled execution for catalog data quality"
  type        = bool
  default     = false
}

# [NEW] Cron expression for catalog DQ job schedule
variable "catalog_schedule_expression" {
  description = "Cron expression for catalog data quality schedule"
  type        = string
  default     = "cron(0 6 * * ? *)"

  validation {
    condition     = can(regex("^cron\\(.*\\)$", var.catalog_schedule_expression))
    error_message = "Catalog schedule expression must be a valid cron expression starting with 'cron('."
  }
}

# [NEW] Cron expression for crawler schedule
variable "catalog_crawler_schedule" {
  description = "Cron expression for crawler execution schedule"
  type        = string
  default     = "cron(0 4 * * ? *)"

  validation {
    condition     = can(regex("^cron\\(.*\\)$", var.catalog_crawler_schedule))
    error_message = "Crawler schedule expression must be a valid cron expression starting with 'cron('."
  }
}
