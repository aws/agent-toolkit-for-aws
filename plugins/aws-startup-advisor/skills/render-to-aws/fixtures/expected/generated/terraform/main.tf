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
      Environment = var.environment
      ManagedBy   = "terraform"
      Migration   = "render-to-aws"
      Project     = var.project_name
    }
  }
}

locals {
  name_prefix   = "${var.project_name}-${var.environment}"
  private_cidrs = ["10.42.1.0/24", "10.42.2.0/24"]
  public_cidrs  = ["10.42.101.0/24", "10.42.102.0/24"]
}
