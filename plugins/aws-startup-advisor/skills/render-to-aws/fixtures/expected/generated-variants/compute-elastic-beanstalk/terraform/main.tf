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

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name_prefix   = "render-migration"
  private_cidrs = ["10.43.1.0/24", "10.43.2.0/24"]
  public_cidrs  = ["10.43.101.0/24", "10.43.102.0/24"]
}
