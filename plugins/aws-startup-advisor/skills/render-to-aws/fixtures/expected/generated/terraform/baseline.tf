# Account-wide security baseline (compliance: none, cloudtrail_retention_days = 90).
# See terraform/README.md for the opt-out procedure.
variable "operations_email" {
  description = "Operations alternate contact and alert subscription email"
  type        = string
}
########## Account Baseline ##########
variable "billing_email" {
  description = "Billing alternate contact and budget notification email"
  type        = string
}
variable "security_email" {
  description = "Security alternate contact email"
  type        = string
}
data "aws_caller_identity" "current" {}
locals {
  cloudtrail_retention_days = 90
  baseline_tags = {
    Component = "security-baseline"
  }
}
# Replace the placeholder phone number after apply.
resource "aws_account_alternate_contact" "operations" {
  alternate_contact_type = "OPERATIONS"
  name                   = "Operations"
  title                  = "Operations Contact"
  email_address          = var.operations_email
  phone_number           = "+1-555-0100"
}
resource "aws_account_alternate_contact" "billing" {
  alternate_contact_type = "BILLING"
  name                   = "Billing"
  title                  = "Billing Contact"
  email_address          = var.billing_email
  phone_number           = "+1-555-0100"
}
resource "aws_account_alternate_contact" "security" {
  alternate_contact_type = "SECURITY"
  name                   = "Security"
  title                  = "Security Contact"
  email_address          = var.security_email
  phone_number           = "+1-555-0100"
}
resource "aws_iam_account_password_policy" "baseline" {
  minimum_password_length        = 14
  password_reuse_prevention      = 24
  max_password_age               = 90
  require_lowercase_characters   = true
  require_uppercase_characters   = true
  require_numbers                = true
  require_symbols                = true
  allow_users_to_change_password = true
  hard_expiry                    = false
}
resource "aws_s3_account_public_access_block" "baseline" {
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
# defense-in-depth: encrypt new EBS volumes by default.
resource "aws_ebs_encryption_by_default" "baseline" {
  enabled = true
}
resource "aws_accessanalyzer_analyzer" "baseline" {
  analyzer_name = "${var.project_name}-baseline"
  type          = "ACCOUNT"
  tags          = local.baseline_tags
}
# defense-in-depth: require IMDSv2 for new instances.
resource "aws_ec2_instance_metadata_defaults" "baseline" {
  http_tokens                 = "required"
  http_put_response_hop_limit = 2
}
resource "aws_s3_bucket" "cloudtrail_logs" {
  bucket = "${local.name_prefix}-cloudtrail-${data.aws_caller_identity.current.account_id}"
  tags   = local.baseline_tags
}
resource "aws_s3_bucket_public_access_block" "cloudtrail_logs" {
  bucket                  = aws_s3_bucket.cloudtrail_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
resource "aws_s3_bucket_versioning" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}
# Retention is 90 days: no STANDARD_IA transition (needs 90+ days) and no GLACIER transition.
resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  rule {
    id     = "expire-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = local.cloudtrail_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = local.cloudtrail_retention_days
    }
  }
}
resource "aws_s3_bucket_policy" "cloudtrail_logs" {
  bucket = aws_s3_bucket.cloudtrail_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AWSCloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.cloudtrail_logs.arn
        Condition = {
          StringEquals = {
            "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:cloudtrail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:trail/${var.project_name}-baseline"
          }
        }
      },
      {
        Sid       = "AWSCloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.cloudtrail_logs.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"  = "bucket-owner-full-control"
            "aws:SourceArn" = "arn:${data.aws_partition.current.partition}:cloudtrail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:trail/${var.project_name}-baseline"
          }
        }
      }
    ]
  })
}
# An existing trail with the same name or account-level trail may collide; rename or import it.
resource "aws_cloudtrail" "baseline" {
  name                          = "${var.project_name}-baseline"
  s3_bucket_name                = aws_s3_bucket.cloudtrail_logs.id
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  tags                          = local.baseline_tags
  depends_on                    = [aws_s3_bucket_policy.cloudtrail_logs]
}
# Budget limit = max(50, ceil(aws_monthly_balanced * 1.2)) = max(50, ceil(358.5 * 1.2)) = 431.
resource "aws_budgets_budget" "monthly_spend" {
  name         = "${local.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = "431"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.billing_email]
    }
  }
}
# defense-in-depth: GuardDuty has a 30-day trial, then roughly $2-25/month.
resource "aws_guardduty_detector" "baseline" {
  enable                       = true
  finding_publishing_frequency = "FIFTEEN_MINUTES"
  tags                         = local.baseline_tags
}
########## End Account Baseline ##########
########## Remote State ##########
data "aws_caller_identity" "tfstate" {}
resource "aws_s3_bucket" "tfstate" {
  bucket = "${var.project_name}-${var.environment}-tfstate-${data.aws_caller_identity.tfstate.account_id}"
  tags   = { Component = "terraform-state" }
}
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}
resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_dynamodb_table" "tfstate_lock" {
  name         = "${var.project_name}-${var.environment}-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
  tags = { Component = "terraform-state" }
}
########## End Remote State ##########
