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

variable "postgres_engine_version" {
  description = "Aurora PostgreSQL engine version used at creation. Automatic minor upgrades are on and engine_version is in ignore_changes, so later minor versions do not plan a downgrade."
  type        = string
  default     = "16.4"
}

variable "postgres_instance_class" {
  description = "Aurora instance class selected from the balanced sizing recorded by Design."
  type        = string
  default     = "db.r6g.large"
}

variable "postgres_instance_count" {
  description = "Number of Aurora instances; 2 or more places a reader in a second Availability Zone."
  type        = number
  default     = 2
  validation {
    condition     = var.postgres_instance_count >= 1 && var.postgres_instance_count <= 15
    error_message = "postgres_instance_count must be between 1 and 15."
  }
}

variable "backup_retention_days" {
  description = "Automated backup and point-in-time recovery window in days."
  type        = number
  default     = 7
  validation {
    condition     = var.backup_retention_days >= 1 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 1 and 35."
  }
}
