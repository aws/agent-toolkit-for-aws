terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Environment = "production"
      ManagedBy   = "terraform"
      Migration   = "render-to-aws"
      Project     = "render-migration"
    }
  }
}

data "aws_partition" "current" {}

locals {
  name_prefix = "render-migration"
}
