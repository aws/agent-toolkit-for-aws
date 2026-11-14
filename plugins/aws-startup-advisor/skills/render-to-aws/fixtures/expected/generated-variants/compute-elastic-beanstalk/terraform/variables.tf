variable "aws_region" {
  description = "AWS Region selected during Clarify."
  type        = string
  default     = "us-east-1"
}

variable "eb_instance_type" {
  description = "Instance type chosen by Design from the Elastic Beanstalk sizing table."
  type        = string
  default     = "t3.small"
  validation {
    condition     = contains(["t3.micro", "t3.small", "t3.medium", "t3.large", "m6i.xlarge", "r6i.xlarge", "r6i.2xlarge"], var.eb_instance_type)
    error_message = "eb_instance_type must be one of the reviewed Elastic Beanstalk sizing targets."
  }
}

variable "eb_health_check_path" {
  description = "HTTP path the load balancer probes on each instance."
  type        = string
  default     = "/healthz"
  validation {
    condition     = startswith(var.eb_health_check_path, "/")
    error_message = "eb_health_check_path must start with a slash."
  }
}

variable "eb_application_port" {
  description = "Port the application listens on."
  type        = number
  default     = 8080
  validation {
    condition     = var.eb_application_port >= 1 && var.eb_application_port <= 65535
    error_message = "eb_application_port must be a valid TCP port."
  }
}

variable "issued_certificate_arn" {
  description = "ARN of an ACM certificate already validated and issued for the public web service."
  type        = string
  validation {
    condition     = can(regex("^arn:aws(?:-[a-z]+)?:acm:[a-z0-9-]+:[0-9]{12}:certificate/[0-9a-fA-F-]{36}$", var.issued_certificate_arn))
    error_message = "issued_certificate_arn must be a non-empty ACM certificate ARN."
  }
}

variable "app_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the application configuration. The value is set outside Terraform."
  type        = string
  validation {
    condition     = can(regex("^arn:aws(?:-[a-z]+)?:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:.+$", var.app_secret_arn))
    error_message = "app_secret_arn must be a Secrets Manager secret ARN."
  }
}
