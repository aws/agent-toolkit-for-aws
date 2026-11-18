variable "aws_region" {
  description = "AWS Region selected during Clarify."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Stable project name used for tags and resource names."
  type        = string
  default     = "render-migration"
}

variable "environment" {
  description = "Deployment environment represented by this stack."
  type        = string
  default     = "production"
}

variable "valkey_major_version" {
  description = "Valkey major version for the serverless cache."
  type        = string
  default     = "8"
}

variable "valkey_max_data_gb" {
  description = "Upper bound on cached data in GB, sized from the source memory plan with headroom."
  type        = number
  default     = 10
  validation {
    condition     = var.valkey_max_data_gb >= 1
    error_message = "valkey_max_data_gb must be at least 1."
  }
}

variable "valkey_max_ecpu_per_second" {
  description = "Upper bound on ElastiCache Processing Units per second to cap spend."
  type        = number
  default     = 10000
  validation {
    condition     = var.valkey_max_ecpu_per_second >= 1000
    error_message = "valkey_max_ecpu_per_second must be at least 1000."
  }
}

variable "snapshot_retention_days" {
  description = "Daily snapshot retention in days; 0 disables snapshots for a pure cache."
  type        = number
  default     = 1
  validation {
    condition     = var.snapshot_retention_days >= 0 && var.snapshot_retention_days <= 35
    error_message = "snapshot_retention_days must be between 0 and 35."
  }
}
