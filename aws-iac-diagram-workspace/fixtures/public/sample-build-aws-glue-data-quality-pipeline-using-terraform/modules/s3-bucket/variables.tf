variable "bucket_name" {
  description = "Name of the S3 bucket"
  type        = string
}



variable "environment" {
  description = "Environment name"
  type        = string
}

variable "tags" {
  description = "Tags to be applied to all resources"
  type        = map(string)
}
