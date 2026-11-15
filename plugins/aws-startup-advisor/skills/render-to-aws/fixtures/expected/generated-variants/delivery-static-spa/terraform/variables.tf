variable "aws_region" {
  description = "AWS Region selected during Clarify."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Stable project name used for tags and resource names."
  type        = string
  default     = "render-static-site"
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,17}$", var.project_name))
    error_message = "project_name must be 1 to 18 characters of lowercase letters, digits and hyphens, starting with a letter or digit, so the derived bucket_prefix stays within the 37 character provider limit."
  }
}

variable "environment" {
  description = "Deployment environment represented by this stack."
  type        = string
  default     = "production"
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,9}$", var.environment))
    error_message = "environment must be 1 to 10 characters of lowercase letters, digits and hyphens, starting with a letter or digit, so the derived bucket_prefix stays within the 37 character provider limit."
  }
}

variable "custom_domain_names" {
  description = "Custom domain names served by CloudFront. Leave empty to use the default CloudFront domain."
  type        = list(string)
  default     = []
}

variable "cloudfront_certificate_arn" {
  description = "ARN of an ACM certificate in us-east-1 that is already validated and Issued. Required when custom_domain_names is not empty."
  type        = string
  default     = null
  validation {
    condition     = var.cloudfront_certificate_arn == null || can(regex("^arn:aws(?:-[a-z]+)?:acm:us-east-1:[0-9]{12}:certificate/[0-9a-fA-F-]{36}$", var.cloudfront_certificate_arn))
    error_message = "cloudfront_certificate_arn must be an ACM certificate ARN in us-east-1."
  }
}

variable "price_class" {
  description = "CloudFront price class."
  type        = string
  default     = "PriceClass_100"
  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.price_class)
    error_message = "price_class must be PriceClass_100, PriceClass_200 or PriceClass_All."
  }
}
