provider "aws" {
  region = "us-east-1" # Update this to your desired AWS region
}

module "knowledge_base" {
  source = "./modules"
  # Define required variables for the module
  kb_s3_bucket_name_prefix = "your-s3-bucket-name" # Replace this with name of existing S3 bucket to use as knowledge base data source
  
  # (Optional) Additional settings for variables defined in modules/variables.tf can be added here
  chunking_strategy        = "DEFAULT"      # Supports FIXED_SIZE, HIERARCHICAL, SEMANTIC, or NONE. By default, with DEFAULT chunking, it automatically splits the text into chunks of approximately 300 tokens.
  kb_model_id              = null           # Leave as null to use the default "amazon.titan-embed-text-v2:0", or replace with your desired model ID
  kb_name                  = null           # Leave as null to use the default KB value "resourceKB", or replace with a custom name
  kb_oss_collection_name   = null           # Leave as null to use the default OpenSearch value "bedrock-resource-kb", or replace with a custom name 
}

output "account_id" {
  value = module.knowledge_base.account_id
}

output "partition" {
  value = module.knowledge_base.partition
}

output "region" {
  value = module.knowledge_base.region
}

output "bedrockarn" {
  value = module.knowledge_base.bedrockarn
}

output "s3_bucket_name" {
  value = module.knowledge_base.s3_bucket_name
}

output "knowledge_base_id" {
  value       = module.knowledge_base.knowledge_base_id
  description = "The ID of the Knowledge Base"
}

output "knowledge_base_ARN" {
  value       = module.knowledge_base.knowledge_base_ARN
  description = "The ARN of the Knowledge Base"
}
