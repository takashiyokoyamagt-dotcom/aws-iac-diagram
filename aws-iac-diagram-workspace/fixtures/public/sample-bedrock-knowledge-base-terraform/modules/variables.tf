variable "kb_model_id" {
  description = "The ID of the foundational model used by the knowledge base."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "kb_name" {
  description = "The knowledge base name."
  type        = string
  default     = "resourceKB"
}

variable "kb_s3_bucket_name_prefix" {
  description = "The name prefix of the S3 bucket for the data source of the knowledge base."
  type        = string
}

variable "kb_oss_collection_name" {
  description = "The name of the OSS collection for the knowledge base."
  type        = string
  default     = "bedrock-resource-kb"
}

variable "vector_dimension" {
  description = "The dimension of the vectors produced by the model."
  type        = number
  default     = 1024
}

variable "chunking_strategy" {
  type        = string
  description = "Chunking strategy to use (DEFAULT, FIXED_SIZE, HIERARCHICAL, SEMANTIC)"
  default     = "FIXED_SIZE"
  validation {
    condition     = contains(["DEFAULT", "FIXED_SIZE", "HIERARCHICAL", "SEMANTIC", "NONE"], var.chunking_strategy)
    error_message = "Chunking strategy must be one of: DEFAULT, FIXED_SIZE, HIERARCHICAL, SEMANTIC, NONE"
  }
}

# Fixed Size Chunking Variables
variable "fixed_size_max_tokens" {
  type        = number
  description = "Maximum number of tokens for fixed-size chunking"
  default     = 512
}

variable "fixed_size_overlap_percentage" {
  type        = number
  description = "Percentage of overlap between chunks"
  default     = 20
}

# Hierarchical Chunking Variables
variable "hierarchical_overlap_tokens" {
  type        = number
  description = "Number of tokens to overlap in hierarchical chunking"
  default     = 70
}

variable "hierarchical_parent_max_tokens" {
  type        = number
  description = "Maximum tokens for parent chunks"
  default     = 1000
}

variable "hierarchical_child_max_tokens" {
  type        = number
  description = "Maximum tokens for child chunks"
  default     = 500
}

# Semantic Chunking Variables
variable "semantic_max_tokens" {
  type        = number
  description = "Maximum tokens for semantic chunking"
  default     = 512
}

variable "semantic_buffer_size" {
  type        = number
  description = "Buffer size for semantic chunking"
  default     = 1
}

variable "semantic_breakpoint_percentile_threshold" {
  type        = number
  description = "Breakpoint percentile threshold for semantic chunking"
  default     = 75
}