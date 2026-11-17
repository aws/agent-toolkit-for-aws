variable "aws_region" {
  description = "AWS Region selected during Clarify."
  type        = string
  default     = "us-east-1"
}

variable "cron_image" {
  description = "Immutable ECR image for Render source resource rr-cron."
  type        = string
  default     = "000000000000.dkr.ecr.us-east-1.amazonaws.com/render-migration@sha256:4444444444444444444444444444444444444444444444444444444444444444"
  validation {
    condition     = can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$", var.cron_image))
    error_message = "cron_image must be an immutable ECR digest reference."
  }
}

variable "cron_schedule_expression" {
  description = "EventBridge Scheduler expression for the cron job."
  type        = string
  default     = "cron(0 * * * ? *)"
}

variable "cron_time_zone" {
  description = "IANA time zone the schedule expression is evaluated in."
  type        = string
  default     = "UTC"
}

variable "cron_timeout_seconds" {
  description = "Lambda timeout in seconds, derived from the design duration."
  type        = number
  default     = 300
  validation {
    condition     = var.cron_timeout_seconds >= 1 && var.cron_timeout_seconds <= 900
    error_message = "cron_timeout_seconds must be between 1 and 900."
  }
}

variable "cron_memory_mb" {
  description = "Lambda memory size in MB, derived from the design."
  type        = number
  default     = 512
  validation {
    condition     = var.cron_memory_mb >= 128 && var.cron_memory_mb <= 10240
    error_message = "cron_memory_mb must be between 128 and 10240."
  }
}
