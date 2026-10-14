#!/usr/bin/env python3
"""
Helper script to run the complete catalog data quality pipeline
This ensures the crawler runs first before the catalog DQ job

[NEW FILE] - Added to support Catalog-based Data Quality feature
This helper script orchestrates the catalog DQ pipeline execution:
1. Checks if Glue database exists
2. Runs crawler if tables don't exist
3. Waits for crawler completion
4. Starts the catalog data quality job

Usage:
    python scripts/run_catalog_pipeline.py
"""

import boto3
import time
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def wait_for_crawler(glue_client, crawler_name, max_wait_minutes=10):
    """Wait for crawler to complete."""
    max_wait_seconds = max_wait_minutes * 60
    wait_interval = 30
    elapsed = 0
    
    while elapsed < max_wait_seconds:
        try:
            response = glue_client.get_crawler(Name=crawler_name)
            state = response['Crawler']['State']
            
            if state == 'READY':
                logger.info(f"✅ Crawler {crawler_name} completed successfully")
                return True
            elif state in ['RUNNING']:
                logger.info(f"⏳ Crawler {crawler_name} is {state}, waiting...")
                time.sleep(wait_interval)
                elapsed += wait_interval
            else:
                logger.error(f"❌ Crawler {crawler_name} in unexpected state: {state}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error checking crawler status: {str(e)}")
            return False
    
    logger.error(f"❌ Crawler {crawler_name} timed out after {max_wait_minutes} minutes")
    return False

def main():
    """Run the complete catalog pipeline."""
    try:
        glue_client = boto3.client('glue')
        
        # Configuration
        crawler_name = "data-quality-pipeline-catalog-crawler"
        job_name = "data-quality-pipeline-catalog"
        database_name = "taxi_data_catalog"
        
        logger.info("🚀 Starting Catalog Data Quality Pipeline")
        
        # Step 1: Check if database exists, if not run crawler
        try:
            glue_client.get_database(Name=database_name)
            logger.info(f"✅ Database {database_name} already exists")
            
            # Check if tables exist
            tables_response = glue_client.get_tables(DatabaseName=database_name)
            tables = tables_response.get('TableList', [])
            
            if not tables:
                logger.info("📋 No tables found, running crawler to discover tables...")
                glue_client.start_crawler(Name=crawler_name)
                if not wait_for_crawler(glue_client, crawler_name):
                    logger.error("❌ Crawler failed, cannot proceed")
                    sys.exit(1)
            else:
                logger.info(f"✅ Found {len(tables)} existing tables: {[t['Name'] for t in tables]}")
                
        except glue_client.exceptions.EntityNotFoundException:
            logger.info(f"📋 Database {database_name} not found, running crawler...")
            glue_client.start_crawler(Name=crawler_name)
            if not wait_for_crawler(glue_client, crawler_name):
                logger.error("❌ Crawler failed, cannot proceed")
                sys.exit(1)
        
        # Step 2: Verify tables were created
        try:
            tables_response = glue_client.get_tables(DatabaseName=database_name)
            tables = tables_response.get('TableList', [])
            
            if not tables:
                logger.error(f"❌ No tables found in database {database_name} after crawler run")
                sys.exit(1)
            
            logger.info(f"✅ Ready to run catalog DQ job with {len(tables)} tables: {[t['Name'] for t in tables]}")
            
        except Exception as e:
            logger.error(f"❌ Error verifying tables: {str(e)}")
            sys.exit(1)
        
        # Step 3: Run catalog data quality job
        logger.info(f"🔍 Starting catalog data quality job: {job_name}")
        job_response = glue_client.start_job_run(JobName=job_name)
        job_run_id = job_response['JobRunId']
        
        logger.info(f"✅ Catalog data quality job started successfully!")
        logger.info(f"📊 Job Run ID: {job_run_id}")
        logger.info(f"🔗 Monitor job at: https://console.aws.amazon.com/glue/home#etl:tab=jobs")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Pipeline failed: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()