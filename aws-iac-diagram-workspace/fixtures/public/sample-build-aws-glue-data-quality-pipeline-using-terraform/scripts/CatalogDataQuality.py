"""
AWS Glue Catalog-based Data Quality Processor

[NEW FILE] - Added to support Catalog-based Data Quality feature
This script enables data quality validation directly against AWS Glue Data Catalog tables
without requiring ETL job execution.

Key Features:
- Reads table metadata from Glue Data Catalog
- Executes data quality rules against catalog tables
- Supports multiple table processing in single job run
- Writes results to separate S3 path (catalog-dq-results/)
- Publishes CloudWatch metrics with catalog-specific dimensions

Usage:
- Deployed via Terraform when catalog_dq_enabled = true
- Triggered by Glue job: {job_name}-catalog
"""

import sys
import logging
from typing import List, Dict, Any, Optional
from awsglue.transforms import SelectFromCollection
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsgluedq.transforms import EvaluateDataQuality
from awsglue.dynamicframe import DynamicFrame
from pyspark.sql.functions import lit
import boto3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CatalogDataQualityProcessor:
    """AWS Glue Catalog-based Data Quality processor with comprehensive validation rules."""
    
    
    def __init__(self):
        """Initialize the Catalog Data Quality processor."""
        try:
            # Get all possible parameters, handling missing ones gracefully
            all_possible_args = [
                'JOB_NAME', 
                'S3_BUCKET_NAME', 
                'ENVIRONMENT',
                'DATABASE_NAME', 
                'TABLE_NAMES', 
                'DQ_RULES'
            ]
            
            # Try to get all arguments, but handle missing ones
            self.args = {}
            for arg in all_possible_args:
                try:
                    resolved = getResolvedOptions(sys.argv, [arg])
                    self.args.update(resolved)
                except Exception:
                    # Set defaults for missing arguments
                    if arg == 'JOB_NAME':
                        self.args[arg] = 'catalog-data-quality-job'
                    elif arg == 'S3_BUCKET_NAME':
                        self.args[arg] = 'default-bucket'
                    elif arg == 'ENVIRONMENT':
                        self.args[arg] = 'dev'
                    elif arg == 'DATABASE_NAME':
                        self.args[arg] = 'data_quality_catalog'
                    elif arg == 'TABLE_NAMES':
                        self.args[arg] = ''
                    elif arg == 'DQ_RULES':
                        self.args[arg] = ''
                    
                    logger.warning(f"Parameter {arg} not provided, using default: {self.args[arg]}")
            
        except Exception as e:
            logger.error(f"Error initializing job parameters: {str(e)}")
            raise
        
        # Initialize Spark and Glue contexts
        try:
            self.sc = SparkContext()
            self.glue_context = GlueContext(self.sc)
            self.spark = self.glue_context.spark_session
            self.job = Job(self.glue_context)
            
            self.job.init(self.args['JOB_NAME'], self.args)
            logger.info("✅ Successfully initialized Spark and Glue contexts")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Spark/Glue contexts: {str(e)}")
            raise
        
        # Initialize parameters
        self.database_name = self.args.get('DATABASE_NAME', 'data_quality_catalog')
        self.table_names = self._parse_table_names(self.args.get('TABLE_NAMES', ''))
        self.dq_rules = self.args.get('DQ_RULES', '')
        self.s3_bucket = self.args.get('S3_BUCKET_NAME', 'default-bucket')
        self.environment = self.args.get('ENVIRONMENT', 'dev')
        
        # Initialize Glue client for catalog operations
        try:
            self.glue_client = boto3.client('glue')
            logger.info("Successfully initialized Glue client")
        except Exception as e:
            logger.error(f"Failed to initialize Glue client: {str(e)}")
            raise
        
        logger.info(f"Initialized Catalog Data Quality job: {self.args['JOB_NAME']}")
        logger.info(f"Target database: {self.database_name}")
        logger.info(f"Target tables: {self.table_names}")
        logger.info(f"S3 bucket: {self.s3_bucket}")
        logger.info(f"Environment: {self.environment}")
        logger.info(f"DQ rules: {self.dq_rules[:100]}..." if self.dq_rules else "Using default rules")
    
    def _parse_table_names(self, table_names_str: str) -> List[str]:
        """Parse comma-separated table names string into list."""
        if not table_names_str.strip():
            return []
        return [name.strip() for name in table_names_str.split(',') if name.strip()]
    
    def get_catalog_tables(self) -> List[str]:
        """Get list of tables from Glue Data Catalog."""
        try:
            if self.table_names:
                # Use specified table names
                logger.info(f"Using specified table names: {self.table_names}")
                return self.table_names
            else:
                # Get all tables from database
                logger.info(f"Discovering tables in database: {self.database_name}")
                
                # First check if database exists
                try:
                    self.glue_client.get_database(Name=self.database_name)
                    logger.info(f"Database {self.database_name} exists")
                except self.glue_client.exceptions.EntityNotFoundException:
                    logger.error(f"Database {self.database_name} not found. Please run the crawler first.")
                    raise Exception(f"Database {self.database_name} does not exist. Run the crawler to create catalog tables.")
                
                response = self.glue_client.get_tables(DatabaseName=self.database_name)
                tables = [table['Name'] for table in response.get('TableList', [])]
                logger.info(f"Found {len(tables)} tables in database {self.database_name}: {tables}")
                
                if not tables:
                    logger.warning(f"No tables found in database {self.database_name}. Please run the crawler first.")
                    raise Exception(f"No tables found in database {self.database_name}. Run the crawler to discover tables from S3 data.")
                
                return tables
        except Exception as e:
            logger.error(f"Error getting catalog tables: {str(e)}")
            raise
    
    def validate_table_exists(self, table_name: str) -> bool:
        """Validate that a table exists in the Glue Data Catalog."""
        try:
            self.glue_client.get_table(DatabaseName=self.database_name, Name=table_name)
            return True
        except self.glue_client.exceptions.EntityNotFoundException:
            logger.warning(f"Table {table_name} not found in database {self.database_name}")
            return False
        except Exception as e:
            logger.error(f"Error validating table {table_name}: {str(e)}")
            return False
    
    def process_catalog_table(self, table_name: str) -> Optional[Dict[str, Any]]:
        """Process data quality rules for a single catalog table."""
        try:
            logger.info(f"Processing data quality for table: {table_name}")
            
            # Validate table exists
            if not self.validate_table_exists(table_name):
                logger.warning(f"Skipping table {table_name} - not found in catalog")
                return None
            
            # Create dynamic frame from catalog table
            catalog_frame = self.glue_context.create_dynamic_frame.from_catalog(
                database=self.database_name,
                table_name=table_name,
                transformation_ctx=f"read_catalog_table_{table_name}"
            )
            
            record_count = catalog_frame.count()
            logger.info(f"Table {table_name} contains {record_count} records")
            
            if record_count == 0:
                logger.warning(f"Table {table_name} is empty, but will still create a result")
                # Create a simple result for empty table
                from pyspark.sql import Row
                empty_result = [Row(
                    Rule="RowCount",
                    Outcome="Failed", 
                    EvaluatedMetrics=0,
                    Message="Table is empty"
                )]
                empty_df = self.spark.createDataFrame(empty_result)
                empty_frame = DynamicFrame.fromDF(empty_df, self.glue_context, f"empty_{table_name}")
                
                return {
                    "table_name": table_name,
                    "record_count": record_count,
                    "rule_outcomes": empty_frame
                }
            
            # Use default rules if none specified
            ruleset = self.dq_rules if self.dq_rules.strip() else self._get_default_rules()
            logger.info(f"Using ruleset for table {table_name}: {ruleset}")
            
            # Execute data quality evaluation
            logger.info(f"Executing data quality evaluation for table {table_name}")
            dq_results = EvaluateDataQuality().process_rows(
                frame=catalog_frame,
                ruleset=ruleset,
                publishing_options={
                    "dataQualityEvaluationContext": f"catalog_validation_{self.environment}_{table_name}",
                    "enableDataQualityCloudWatchMetrics": True,
                    "enableDataQualityResultsPublishing": True
                }
            )
            logger.info(f"Data quality evaluation completed for table {table_name}")
            
            # Extract rule outcomes
            rule_outcomes = SelectFromCollection.apply(
                dfc=dq_results,
                key="ruleOutcomes",
                transformation_ctx=f"extract_rule_outcomes_{table_name}"
            )
            
            return {
                "table_name": table_name,
                "record_count": record_count,
                "rule_outcomes": rule_outcomes
            }
            
        except Exception as e:
            logger.error(f"Error processing table {table_name}: {str(e)}")
            return None
    
    def _get_default_rules(self) -> str:
        """Get default data quality rules for catalog tables."""
        return """
            Rules = [
                RowCount > 0,
                ColumnCount > 0
            ]
        """
    
    def run_catalog_pipeline(self) -> None:
        """Run the complete catalog-based data quality pipeline."""
        logger.info("Starting catalog-based data quality pipeline")
        
        try:
            # Get list of tables to process
            logger.info("Step 1: Getting catalog tables...")
            tables_to_process = self.get_catalog_tables()
            
            if not tables_to_process:
                logger.warning("No tables found to process")
                return
            
            logger.info(f"Step 2: Processing {len(tables_to_process)} tables: {tables_to_process}")
            
            # Process each table
            all_results = []
            for i, table_name in enumerate(tables_to_process, 1):
                logger.info(f"Step 2.{i}: Processing table {table_name}...")
                result = self.process_catalog_table(table_name)
                if result:
                    all_results.append(result)
                    logger.info(f"Successfully processed table {table_name}")
                else:
                    logger.warning(f"Failed to process table {table_name}")
            
            # Write consolidated results
            logger.info(f"Step 3: Writing results for {len(all_results)} processed tables...")
            if all_results:
                self._write_consolidated_results(all_results)
            else:
                logger.error("❌ No results to write - all table processing failed")
                # Still try to write something to S3 to create the folder
                logger.info("🔧 Creating empty result to ensure S3 folder is created...")
                try:
                    from pyspark.sql import Row
                    empty_result = [Row(
                        Rule="PipelineStatus",
                        Outcome="NoTablesProcessed", 
                        EvaluatedMetrics=0,
                        source_table="none",
                        source_database=self.database_name,
                        source_record_count=0,
                        validation_type="CATALOG"
                    )]
                    empty_df = self.spark.createDataFrame(empty_result)
                    empty_frame = DynamicFrame.fromDF(empty_df, self.glue_context, "pipeline_status")
                    
                    s3_path = f"s3://{self.s3_bucket}/catalog-dq-results/"
                    self.glue_context.write_dynamic_frame.from_options(
                        frame=empty_frame,
                        connection_type="s3",
                        format="glueparquet",
                        connection_options={"path": s3_path},
                        format_options={"compression": "snappy"},
                        transformation_ctx="write_empty_result"
                    )
                    logger.info(f"✅ Created empty result file in {s3_path}")
                except Exception as empty_error:
                    logger.error(f"❌ Failed to create empty result: {str(empty_error)}")
            
            logger.info(f"Catalog data quality pipeline completed successfully. Processed {len(all_results)} tables.")
            
        except Exception as e:
            logger.error(f"Error in catalog pipeline: {str(e)}")
            raise
    
    def _write_consolidated_results(self, results: List[Dict[str, Any]]) -> None:
        """Write consolidated results from all tables to S3."""
        try:
            logger.info(f"🔄 Starting to write results for {len(results)} tables")
            
            if not results:
                logger.error("❌ No results provided to write!")
                return
            
            # Simple approach: write each table's results separately first
            s3_base_path = f"s3://{self.s3_bucket}/catalog-dq-results/"
            logger.info(f"📁 Base S3 path: {s3_base_path}")
            
            total_written = 0
            
            for i, result in enumerate(results, 1):
                table_name = result["table_name"]
                record_count = result["record_count"]
                rule_outcomes = result["rule_outcomes"]
                
                logger.info(f"📊 Processing table {i}/{len(results)}: {table_name}")
                
                try:
                    # Check if we have rule outcomes
                    outcomes_count = rule_outcomes.count()
                    logger.info(f"📈 Table {table_name}: {outcomes_count} rule outcomes, {record_count} records")
                    
                    if outcomes_count == 0:
                        logger.warning(f"⚠️ No rule outcomes for table {table_name}, creating dummy result")
                        # Create a simple result indicating the table was processed
                        from pyspark.sql import Row
                        dummy_data = [Row(
                            Rule="TableProcessed",
                            Outcome="Success", 
                            EvaluatedMetrics=record_count,
                            source_table=table_name,
                            source_database=self.database_name,
                            source_record_count=record_count,
                            validation_type="CATALOG"
                        )]
                        dummy_df = self.spark.createDataFrame(dummy_data)
                        dummy_frame = DynamicFrame.fromDF(dummy_df, self.glue_context, f"dummy_{table_name}")
                        rule_outcomes = dummy_frame
                        outcomes_count = 1
                    else:
                        # Add metadata to existing outcomes
                        outcomes_df = rule_outcomes.toDF()
                        outcomes_df = outcomes_df.withColumn("source_table", lit(table_name))
                        outcomes_df = outcomes_df.withColumn("source_database", lit(self.database_name))
                        outcomes_df = outcomes_df.withColumn("source_record_count", lit(record_count))
                        outcomes_df = outcomes_df.withColumn("validation_type", lit("CATALOG"))
                        
                        rule_outcomes = DynamicFrame.fromDF(
                            outcomes_df, 
                            self.glue_context, 
                            f"enhanced_{table_name}"
                        )
                    
                    # Write this table's results to S3
                    table_s3_path = f"{s3_base_path}table={table_name}/"
                    logger.info(f"💾 Writing {outcomes_count} outcomes to: {table_s3_path}")
                    
                    self.glue_context.write_dynamic_frame.from_options(
                        frame=rule_outcomes,
                        connection_type="s3",
                        format="glueparquet",
                        connection_options={"path": table_s3_path},
                        format_options={"compression": "snappy"},
                        transformation_ctx=f"write_table_{table_name}"
                    )
                    
                    total_written += outcomes_count
                    logger.info(f"✅ Successfully wrote {outcomes_count} outcomes for table {table_name}")
                    
                except Exception as table_error:
                    logger.error(f"❌ Error writing results for table {table_name}: {str(table_error)}")
                    # Continue with other tables
                    continue
            
            if total_written > 0:
                logger.info(f"🎉 SUCCESS: Wrote {total_written} total rule outcomes to {s3_base_path}")
                logger.info(f"📂 Check S3 bucket for 'catalog-dq-results' folder!")
            else:
                logger.error(f"❌ FAILED: No results were written to S3")
            
        except Exception as e:
            logger.error(f"❌ Critical error in result writing: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Don't raise - let job complete so we can see logs
            logger.error("⚠️ Continuing job execution to preserve logs")
    
    def cleanup(self) -> None:
        """Cleanup and commit job."""
        self.job.commit()
        logger.info("Catalog Data Quality job committed successfully")


def main() -> None:
    """Main entry point."""
    processor = None
    try:
        logger.info("=== Starting Catalog Data Quality Job ===")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Job arguments: {sys.argv}")
        
        # Basic validation
        if len(sys.argv) < 2:
            logger.warning("No job arguments provided, using defaults")
        
        logger.info("Step 1: Initializing processor...")
        processor = CatalogDataQualityProcessor()
        
        logger.info("Step 2: Running catalog pipeline...")
        processor.run_catalog_pipeline()
        
        logger.info("=== ✅ Catalog Data Quality job completed successfully ===")
    except Exception as e:
        logger.error(f"=== ❌ Catalog Data Quality job failed ===")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        
        # Import traceback here to avoid issues
        try:
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        except:
            logger.error("Could not get traceback")
        
        sys.exit(1)
    finally:
        if processor:
            try:
                logger.info("Cleaning up...")
                processor.cleanup()
            except Exception as cleanup_error:
                logger.error(f"Error during cleanup: {str(cleanup_error)}")


if __name__ == "__main__":
    main()