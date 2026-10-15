terraform {
  required_version = ">= 1.11.1" # terraform-aws-modules/rds v7 の要件

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}
