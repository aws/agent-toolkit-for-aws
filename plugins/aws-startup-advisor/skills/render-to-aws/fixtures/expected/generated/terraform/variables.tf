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

variable "issued_certificate_arn" {
  description = "ARN of an ACM certificate already validated and issued for source resource rr-domain."
  type        = string

  validation {
    condition     = can(regex("^arn:aws(?:-[a-z]+)?:acm:[a-z0-9-]+:[0-9]{12}:certificate/[0-9a-fA-F-]{36}$", var.issued_certificate_arn))
    error_message = "issued_certificate_arn must be a non-empty ACM certificate ARN."
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

variable "private_image" {
  description = "Immutable ECR image for Render source resource rr-private."
  type        = string
  default     = "000000000000.dkr.ecr.us-east-1.amazonaws.com/render-migration@sha256:2222222222222222222222222222222222222222222222222222222222222222"

  validation {
    condition     = can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$", var.private_image))
    error_message = "private_image must be an immutable ECR digest reference."
  }
}

variable "worker_image" {
  description = "Immutable ECR image for Render source resource rr-worker; the selected cron reuses this reviewed task artifact."
  type        = string
  default     = "000000000000.dkr.ecr.us-east-1.amazonaws.com/render-migration@sha256:3333333333333333333333333333333333333333333333333333333333333333"

  validation {
    condition     = can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$", var.worker_image))
    error_message = "worker_image must be an immutable ECR digest reference."
  }
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

variable "runtime_configuration_value" {
  description = "Non-secret runtime configuration supplied at apply time."
  type        = string
  sensitive   = true
}
