variable "aws_region" {
  description = "AWS Region selected during Clarify."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Stable project name used for tags and resource names."
  type        = string
  default     = "render-static-site"
}

variable "environment" {
  description = "Deployment environment represented by this stack."
  type        = string
  default     = "production"
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
