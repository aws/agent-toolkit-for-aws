variable "aws_region" {
  description = "AWS Region selected during Clarify."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Stable project name used for tags and resource names."
  type        = string
  default     = "render-migration"
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,15}$", var.project_name))
    error_message = "project_name must be 1 to 16 characters of lowercase letters, digits and hyphens, starting with a letter or digit, so derived ALB, target group and bucket_prefix names stay within the 32 and 37 character provider limits."
  }
}

variable "environment" {
  description = "Deployment environment represented by this stack."
  type        = string
  default     = "production"
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,9}$", var.environment))
    error_message = "environment must be 1 to 10 characters of lowercase letters, digits and hyphens, starting with a letter or digit, so derived ALB, target group and bucket_prefix names stay within the 32 and 37 character provider limits."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block of the VPC; it must be a /16 so the /24 tier subnets fit."
  type        = string
  default     = "10.42.0.0/16"
  validation {
    condition     = can(cidrnetmask(var.vpc_cidr)) && tonumber(split("/", var.vpc_cidr)[1]) == 16
    error_message = "vpc_cidr must be a valid IPv4 /16 CIDR block."
  }
}

variable "issued_certificate_arn" {
  description = "ARN of an ACM certificate already validated and issued for source resource rr-domain."
  type        = string
  validation {
    condition     = can(regex("^arn:aws(?:-[a-z]+)?:acm:[a-z0-9-]+:[0-9]{12}:certificate/[0-9a-fA-F-]{36}$", var.issued_certificate_arn))
    error_message = "issued_certificate_arn must be a non-empty ACM certificate ARN."
  }
}

variable "enable_deletion_protection" {
  description = "Protect the application load balancer from accidental deletion."
  type        = bool
  default     = true
}

variable "access_log_retention_days" {
  description = "Days to keep load balancer access logs."
  type        = number
  default     = 90
  validation {
    condition     = var.access_log_retention_days >= 1
    error_message = "access_log_retention_days must be at least 1."
  }
}

variable "ecr_keep_image_count" {
  description = "Number of most recent images kept so promoted digests are not expired early."
  type        = number
  default     = 50
  validation {
    condition     = var.ecr_keep_image_count >= 10
    error_message = "ecr_keep_image_count must be at least 10."
  }
}

variable "web_image" {
  description = "Immutable ECR image for Render source resource rr-web."
  type        = string
  default     = "000000000000.dkr.ecr.us-east-1.amazonaws.com/render-migration@sha256:1111111111111111111111111111111111111111111111111111111111111111"
  validation {
    condition     = can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$", var.web_image))
    error_message = "web_image must be an immutable ECR digest reference."
  }
}
