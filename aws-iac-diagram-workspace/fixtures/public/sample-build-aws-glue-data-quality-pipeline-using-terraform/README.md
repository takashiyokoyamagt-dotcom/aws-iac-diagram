# AWS Glue Data Quality Pipeline with Terraform

A Terraform solution for implementing AWS Glue Data Quality pipelines with both ETL-based and Catalog-based validation, comprehensive rules, and monitoring.

## 🚀 Quick Start

```bash
cd examples/
terraform init
terraform apply -auto-approve
```

## 📋 What This Creates

### Core Infrastructure
- **S3 Bucket** with AES256 encryption for data storage
- **IAM Role** with required permissions for Glue operations
- **CloudWatch Dashboard** for comprehensive monitoring
- **Sample Data** (NYC taxi dataset) for testing

### ETL-based Data Quality
- **Glue Job** with comprehensive data quality rules during ETL processing
- **Scheduled Triggers** for automated execution
- **Results Storage** in S3 with detailed rule outcomes

### Catalog-based Data Quality (Optional)
- **Glue Database** for catalog table management
- **Glue Crawler** for automatic schema discovery from S3 data
- **Catalog Data Quality Job** for validation against catalog tables
- **Independent Scheduling** separate from ETL data quality
- **Enhanced Monitoring** with catalog-specific metrics and alarms

## 🏗️ Architecture

```
                    S3 Bucket (Parquet Data)
                           ↓
                    ┌─────────────────┐
                    │   ETL Mode      │   Catalog Mode
                    │                 │
    ETL Processing  │  Glue DQ Job    │  Glue Crawler → Catalog Tables
         ↓          │       ↓         │       ↓              ↓
    DQ Validation   │  Rule Engine    │  Catalog DQ Job → Rule Engine
         ↓          │       ↓         │       ↓              ↓
    ETL Results     │  S3 Results     │  Catalog Results → S3 Results
                    │       ↓         │       ↓              ↓
                    └───────┼─────────┘       ↓              ↓
                            ↓                 ↓              ↓
                    CloudWatch Dashboard ←────┴──────────────┘
```

## 📁 Project Structure

```
├── examples/                    # Main deployment
│   ├── main.tf                 # Infrastructure configuration
│   ├── variables.tf            # Input variables
│   ├── outputs.tf              # Output values
│   ├── terraform.tfvars        # Configuration file
│   └── data/                   # Sample data files
├── modules/
│   ├── glue-data-quality/      # Glue jobs, crawlers, monitoring
│   ├── iam/                    # IAM roles and policies
│   └── s3-bucket/              # S3 bucket configuration
├── scripts/
│   ├── GlueDataQualityDynamicRules.py  # ETL data quality script
│   ├── CatalogDataQuality.py           # Catalog data quality script
│   └── run_catalog_pipeline.py         # Helper script
└── README.md
```

## ⚙️ Configuration

### Required Variables

Edit `examples/terraform.tfvars`:

```hcl
aws_region    = "us-east-1"
environment   = "dev"
bucket_prefix = "your-unique-prefix"  # Must be globally unique
glue_job_name = "data-quality-pipeline"
```

### Optional Variables

```hcl
# Job Configuration
glue_worker_type         = "G.1X"        # G.1X, G.2X, G.4X
glue_number_of_workers   = 2             # 2-299
glue_job_timeout         = 60            # minutes
data_quality_threshold   = 0.95          # 0.0-1.0
cloudwatch_retention_days = 14           # Log retention

# ETL Scheduling (Optional)
enable_schedule        = true            # Enable scheduled runs
schedule_expression    = "cron(0 2 * * ? *)"  # Daily at 2 AM

# Catalog Data Quality (Optional)
catalog_dq_enabled = true                # Enable catalog-based validation
catalog_database_name = "sample_data_catalog"
s3_data_paths = ["data/"]
catalog_enable_schedule = true
catalog_schedule_expression = "cron(0 6 * * ? *)"  # Daily at 6 AM
catalog_crawler_schedule = "cron(0 4 * * ? *)"     # Crawler at 4 AM
```

## 🎯 Data Quality Rules

### ETL Data Quality Rules

```sql
Rules = [
    CustomSql "select vendorid from primary where passenger_count > 0" with threshold > 0.9,
    Mean "trip_distance" < 150,
    Sum "total_amount" between 1000 and 100000,
    RowCount between 1000 and 1000000,
    Completeness "fare_amount" > 0.9,
    DistinctValuesCount "ratecodeid" between 3 and 10,
    ColumnCount = 19
]
```

### Catalog Data Quality Rules

```sql
Rules = [
    RowCount > 0,
    Completeness "vendorid" > 0.9,
    Completeness "passenger_count" > 0.95,
    Mean "trip_distance" < 150,
    ColumnCount > 5
]
```

## 🚀 Deployment Steps

### 1. Prerequisites

- AWS CLI configured
- Terraform >= 1.0 installed
- Appropriate AWS permissions

### 2. Deploy Infrastructure

```bash
cd examples/
# Edit terraform.tfvars with your values
terraform init
terraform plan
terraform apply
```

### 3. Run Data Quality Jobs

#### ETL Data Quality Job
```bash
# Get job name from output
terraform output glue_job_name

# Run the ETL job
aws glue start-job-run --job-name <job-name>

# Check job status
aws glue get-job-runs --job-name <job-name> --max-items 1
```

#### Catalog Data Quality (if enabled)
```bash
# Run crawler first to discover tables
aws glue start-crawler --name <crawler-name>

# Wait for crawler to complete, then run catalog job
aws glue start-job-run --job-name <catalog-job-name>
```

### 4. View Results

```bash
# Check ETL results
aws s3 ls s3://<bucket-name>/dq-results/ --recursive

# Check catalog results (if enabled)
aws s3 ls s3://<bucket-name>/catalog-dq-results/ --recursive

# View CloudWatch dashboard
# Navigate to CloudWatch > Dashboards > DataQuality-<environment>
```

## 📊 Monitoring

### CloudWatch Dashboard

Access your dashboard at: `AWS Console > CloudWatch > Dashboards > DataQuality-{environment}`

**Metrics Included:**
- Job completion rates
- Task success/failure counts
- Execution duration trends
- Crawler status (if catalog enabled)

### Log Analysis

```bash
# View job logs
aws logs tail /aws-glue/jobs/<job-name> --follow

# Check for errors
aws logs filter-log-events \
  --log-group-name "/aws-glue/jobs/<job-name>" \
  --filter-pattern "ERROR"
```

## 📈 Results Structure

```
s3://your-bucket/
├── data/
│   └── sample-data.parquet          # Source data
├── dq-results/                      # ETL results
│   └── rule-outcomes/
├── catalog-dq-results/              # Catalog results (if enabled)
│   └── rule-outcomes/
├── glue-scripts/
│   ├── GlueDataQualityDynamicRules.py
│   └── CatalogDataQuality.py
└── glue-temp/                       # Temporary files
```

## 🔧 Customization

### Adding New ETL Rules

Edit `scripts/GlueDataQualityDynamicRules.py`:

```python
comprehensive_ruleset = """
    Rules = [
        # Add your custom rules here
        Completeness "your_column" > 0.95,
        CustomSql "your custom SQL" with threshold > 0.9
    ]
"""
```

### Adding New Catalog Rules

Configure via `terraform.tfvars`:

```hcl
catalog_dq_rules = <<EOF
Rules = [
  RowCount > 1000,
  Completeness "critical_column" > 0.99,
  Uniqueness "id_column" > 0.95
]
EOF
```

### Scaling Configuration

For larger datasets:

```hcl
glue_worker_type       = "G.2X"
glue_number_of_workers = 4
glue_job_timeout       = 120
```

## 💰 Cost Estimation

### ETL-Only Mode
| Component | Dev/Month | Prod/Month |
|-----------|-----------|------------|
| Glue Jobs | $20-50 | $100-300 |
| S3 Storage | $1-5 | $10-30 |
| CloudWatch | $2-10 | $10-30 |
| **Total** | **$23-65** | **$120-360** |

### Hybrid Mode (ETL + Catalog)
| Component | Dev/Month | Prod/Month |
|-----------|-----------|------------|
| Glue Jobs | $35-90 | $180-550 |
| Glue Crawler | $5-15 | $20-60 |
| S3 Storage | $2-8 | $15-45 |
| CloudWatch | $3-15 | $15-45 |
| **Total** | **$45-128** | **$230-700** |

## 🔍 Troubleshooting

### Common Issues

**Job Fails to Start:**
```bash
# Check IAM permissions
aws iam get-role --role-name <glue-role-name>

# Verify script exists
aws s3 ls s3://<bucket>/glue-scripts/
```

**No Data Quality Results:**
```bash
# Check source data
aws s3 ls s3://<bucket>/data/

# Verify job parameters
aws glue get-job --job-name <job-name>
```

**Crawler Fails (Catalog Mode):**
```bash
# Check crawler configuration
aws glue get-crawler --name <crawler-name>

# Verify S3 paths are accessible
aws s3 ls s3://<bucket>/data/ --recursive
```

**Performance Issues:**
```hcl
# Increase resources
glue_worker_type = "G.2X"
glue_number_of_workers = 4
```

## 📚 Resources

- [AWS Glue Data Quality Documentation](https://docs.aws.amazon.com/glue/latest/dg/glue-data-quality.html)
- [AWS Glue Data Catalog](https://docs.aws.amazon.com/glue/latest/dg/catalog-and-crawler.html)
- [Terraform AWS Provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [Data Quality Best Practices](https://docs.aws.amazon.com/wellarchitected/latest/analytics-lens/data-quality.html)

## 🧹 Cleanup

```bash
terraform destroy -auto-approve
```

## 📝 Outputs

After deployment:

```bash
terraform output
# s3_bucket_name = "your-bucket-name"
# glue_job_name = "your-job-name"
# glue_role_arn = "arn:aws:iam::account:role/role-name"
# catalog_database_name = "your-catalog-db" (if enabled)
# catalog_crawler_name = "your-crawler-name" (if enabled)
# quick_start_commands = {
#   "run_job" = "aws glue start-job-run --job-name your-job-name"
#   "check_results" = "aws s3 ls s3://your-bucket/dq-results/ --recursive"
# }
```

---

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.
