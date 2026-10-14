"""
AWS Glue Data Quality Dynamic Rules Processor
"""

import sys
import logging
from awsglue.transforms import SelectFromCollection
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsgluedq.transforms import EvaluateDataQuality

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GlueDynamicDataQualityProcessor:
    """AWS Glue Data Quality processor with comprehensive validation rules."""
    
    def __init__(self):
        """Initialize the Glue Data Quality processor."""
        self.args = getResolvedOptions(
            sys.argv, 
            ['JOB_NAME', 'S3_BUCKET_NAME', 'ENVIRONMENT']
        )
        
        self.sc = SparkContext()
        self.glue_context = GlueContext(self.sc)
        self.spark = self.glue_context.spark_session
        self.job = Job(self.glue_context)
        
        self.job.init(self.args['JOB_NAME'], self.args)
        
        self.s3_bucket = self.args.get('S3_BUCKET_NAME', 'default-bucket')
        self.environment = self.args.get('ENVIRONMENT', 'dev')
        
        logger.info(f"Initialized Glue job: {self.args['JOB_NAME']}")
    
    def run_pipeline(self) -> None:
        """Run the complete data quality pipeline."""
        logger.info("Starting data quality pipeline")
        
        source_data = self.glue_context.create_dynamic_frame.from_options(
            format_options={},
            connection_type="s3",
            format="parquet",
            connection_options={
                "paths": [f"s3://{self.s3_bucket}/data/"],
                "recurse": True
            },
            transformation_ctx="read_source_data"
        )
        
        logger.info(f"Read {source_data.count()} records from source")
        
        comprehensive_ruleset = """
            Rules = [
                CustomSql "select vendorid from primary where passenger_count > 0" with threshold > 0.9,
                Mean "trip_distance" < 150,
                Sum "total_amount" between 1000 and 100000,
                RowCount between 1000 and 1000000,
                Completeness "fare_amount" > 0.9,
                DistinctValuesCount "ratecodeid" between 3 and 10,
                DistinctValuesCount "pulocationid" > 100,
                ColumnCount = 19
            ]
        """
        
        dq_results = EvaluateDataQuality().process_rows(
            frame=source_data,
            ruleset=comprehensive_ruleset,
            publishing_options={
                "dataQualityEvaluationContext": f"comprehensive_evaluation_{self.environment}",
                "enableDataQualityCloudWatchMetrics": True,
                "enableDataQualityResultsPublishing": True
            }
        )
        
        rule_outcomes = SelectFromCollection.apply(
            dfc=dq_results,
            key="ruleOutcomes",
            transformation_ctx="extract_rule_outcomes"
        )
        
        self.glue_context.write_dynamic_frame.from_options(
            frame=rule_outcomes,
            connection_type="s3",
            format="glueparquet",
            connection_options={"path": f"s3://{self.s3_bucket}/dq-results/"},
            format_options={"compression": "snappy"},
            transformation_ctx="write_results"
        )
        
        logger.info("Data quality pipeline completed successfully")
    
    def cleanup(self) -> None:
        """Cleanup and commit job."""
        self.job.commit()
        logger.info("Job committed successfully")


def main() -> None:
    """Main entry point."""
    processor = None
    try:
        processor = GlueDynamicDataQualityProcessor()
        processor.run_pipeline()
        logger.info("Job completed successfully")
    except Exception as e:
        logger.error(f"Job failed: {str(e)}")
        sys.exit(1)
    finally:
        if processor:
            processor.cleanup()


if __name__ == "__main__":
    main()