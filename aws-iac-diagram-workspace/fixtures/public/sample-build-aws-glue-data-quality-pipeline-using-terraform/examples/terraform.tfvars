# AWS Glue Data Quality Configuration Example
# Copy this file to terraform.tfvars and customize for your environment

# ============================================================================
# REQUIRED CONFIGURATION
# ============================================================================

# General Configuration
aws_region  = "us-east-1"                    # Your AWS region
environment = "dev"                          # Environment: dev, staging, prod

# ============================================================================
# S3 CONFIGURATION
# ============================================================================

bucket_prefix = "glue-data-quality"    # Deployment will create bucket glue-data-quality-{AWS AccountID}-{env} ,must be globally unique

# ============================================================================
# GLUE JOB CONFIGURATION
# ============================================================================

# Job Settings
glue_job_name          = "data-quality-pipeline"
glue_job_timeout       = 60                  # Minutes (1-2880)
glue_worker_type       = "G.1X"             # G.1X, G.2X, G.4X, G.8X, Z.2X
glue_number_of_workers = 2                  # 2-299

# ============================================================================
# DATA QUALITY CONFIGURATION
# ============================================================================

# Quality Thresholds
data_quality_threshold = 0.95               # 0.0-1.0 (95% quality score required)

# Features
enable_data_lineage    = true               # Enable data catalog integration

# ============================================================================
# MONITORING CONFIGURATION
# ============================================================================

cloudwatch_retention_days = 14              # Log retention: 1,3,5,7,14,30,60,90...

# ============================================================================
# SECURITY CONFIGURATION
# ============================================================================

kms_deletion_window = 7                     # 7-30 days
enable_key_rotation = true                  # Enable automatic key rotation

# ============================================================================
# RESOURCE TAGS
# ============================================================================

tags = {
  Project     = "DataQuality"
  CostCenter  = "12345"
  Environment = "dev"
  Owner       = "DataTeam"
  Application = "GlueDataQuality"
  ManagedBy   = "Terraform"
}

# ============================================================================
# ENVIRONMENT-SPECIFIC EXAMPLES
# ============================================================================

# Development Environment
# glue_worker_type = "G.1X"
# glue_number_of_workers = 2
# cloudwatch_retention_days = 7
# data_quality_threshold = 0.90

# Staging Environment
# glue_worker_type = "G.1X"
# glue_number_of_workers = 2
# cloudwatch_retention_days = 14
# data_quality_threshold = 0.95

# Production Environment
# glue_worker_type = "G.2X"
# glue_number_of_workers = 4
# cloudwatch_retention_days = 30
# data_quality_threshold = 0.98

# ============================================================================
# CATALOG-BASED DATA QUALITY CONFIGURATION
# ============================================================================

# Enable catalog-based data quality (in addition to ETL-based)
catalog_dq_enabled = true                   # Set to true to enable catalog DQ

# Catalog Configuration
catalog_database_name = "sample_data_catalog"  # Glue database name for catalog tables
s3_data_paths        = ["data/"]            # S3 paths containing parquet data

# Table Selection (empty list means all tables in database)
catalog_table_names = []                    # Specific tables to validate, or [] for all

# Catalog Data Quality Rules
catalog_dq_rules = <<EOF
Rules = [
  RowCount > 0,
  Completeness "vendorid" > 0.9,
  Completeness "passenger_count" > 0.95,
  Mean "trip_distance" < 150,
  Sum "total_amount" between 1000 and 100000,
  DistinctValuesCount "ratecodeid" between 3 and 10,
  ColumnCount > 5
]
EOF

# Catalog Scheduling (independent from ETL scheduling)
catalog_enable_schedule      = false        # Enable scheduled catalog DQ execution
catalog_schedule_expression  = "cron(0 6 * * ? *)"  # Run at 6 AM daily
catalog_crawler_schedule     = "cron(0 4 * * ? *)"  # Run crawler at 4 AM daily

# ============================================================================
# CATALOG DQ CONFIGURATION EXAMPLES BY ENVIRONMENT
# ============================================================================

# Development Environment - Catalog DQ
# catalog_dq_enabled = true
# catalog_enable_schedule = false           # Manual execution only
# catalog_dq_rules = "Rules = [RowCount > 0, ColumnCount > 0]"

# Staging Environment - Catalog DQ
# catalog_dq_enabled = true
# catalog_enable_schedule = true
# catalog_schedule_expression = "cron(0 8 * * ? *)"  # 8 AM daily
# catalog_crawler_schedule = "cron(0 6 * * ? *)"     # 6 AM daily

# Production Environment - Catalog DQ
# catalog_dq_enabled = true
# catalog_enable_schedule = true
# catalog_schedule_expression = "cron(0 6 * * ? *)"  # 6 AM daily
# catalog_crawler_schedule = "cron(0 4 * * ? *)"     # 4 AM daily
# catalog_table_names = ["critical_table1", "critical_table2"]  # Specific tables only

# ============================================================================
# HYBRID ETL + CATALOG CONFIGURATION EXAMPLE
# ============================================================================

# Example: Run both ETL and Catalog DQ on different schedules
# enable_schedule = true
# schedule_expression = "cron(0 2 * * ? *)"          # ETL DQ at 2 AM
# catalog_dq_enabled = true
# catalog_enable_schedule = true
# catalog_schedule_expression = "cron(0 6 * * ? *)"  # Catalog DQ at 6 AM
# catalog_crawler_schedule = "cron(0 4 * * ? *)"     # Crawler at 4 AM