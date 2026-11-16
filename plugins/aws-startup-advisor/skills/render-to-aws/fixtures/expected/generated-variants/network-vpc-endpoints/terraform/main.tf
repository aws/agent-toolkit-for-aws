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

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  name_prefix   = "${var.project_name}-${var.environment}"
  az_count      = 2
  private_cidrs = [for index in range(local.az_count) : cidrsubnet(var.vpc_cidr, 8, index + 1)]
  public_cidrs  = [for index in range(local.az_count) : cidrsubnet(var.vpc_cidr, 8, index + 101)]
  # Endpoint mode: no NAT gateway. Tasks reach AWS APIs only through these endpoints.
  interface_endpoint_services = toset(["ecr.api", "ecr.dkr", "logs", "secretsmanager", "sts"])
  app_port                    = 8080
}
