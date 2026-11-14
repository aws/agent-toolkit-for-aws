---
_fragment: artifacts-baseline
_of_phase: generate
_contributes:
  - terraform/baseline.tf
  - terraform/monitoring.tf
  - terraform/kms.tf
  - terraform/backup.tf
---
# Generate account baseline and operational resources

Emit `baseline.tf` always. Emit `monitoring.tf`, `kms.tf` and `backup.tf` only when their gate below fires, so a stack without those resources does not grow. These files are not design mappings: they add no row to `generation-warnings.json`, change no `accounting` count, and need no new warning code. They are exempt from per-mapping classification.

Constraints for every file here: no source secret values, no unexpanded placeholder tokens, no `Action = "*"` or `Resource = "*"` in IAM policy documents, deterministic names built from `local.name_prefix`, and only `Component` tags (the provider `default_tags` in `main.tf` supply the rest). Use only resources available in the pinned AWS provider.

## baseline.tf (always emitted)

Account-wide controls that do not depend on the design. Do not probe for an existing trail, Config recorder or Security Hub enrollment; collision risk is an inline comment.

Read compliance from `preferences.json` → `global.compliance` (array). Treat `[]`, absent, `["none"]` and `["unknown"]` as no frameworks.

1. **Retention.** `cloudtrail_retention_days` is the maximum across declared frameworks, default 90: `soc2` 365, `pci` 365, `gdpr` 365, `fedramp` 1095, `hipaa` 2190.
2. **Budget.** `limit_amount = max(50, ceil(aws_monthly_balanced * 1.2))` with `aws_monthly_balanced` from `estimation-infra.json` → `projected_costs`. If the key is missing use 50 and say so in a comment.
3. **Header and locals.** A header comment names the resolved retention. A `locals` block holds `cloudtrail_retention_days` and `baseline_tags = { Component = "security-baseline" }`.
4. **Declarations owned by this file.** `variable "operations_email"`, `variable "billing_email"`, `variable "security_email"` (required, no defaults), `data.aws_caller_identity.current` and `data.aws_partition.current`. Append the three email rows to `terraform.tfvars.example` with `.invalid` placeholder addresses. Do not edit `variables.tf` or `main.tf`.
5. **Always-on resources**, in this order:
   - `aws_account_alternate_contact` for OPERATIONS, BILLING and SECURITY (pinned `name` and `title`, `phone_number = "+1-555-0100"` with a comment to replace it).
   - `aws_iam_account_password_policy` (length 14, reuse prevention 24, max age 90, all four character classes).
   - `aws_s3_account_public_access_block` (all four flags true).
   - `aws_ebs_encryption_by_default` (`defense-in-depth`).
   - `aws_accessanalyzer_analyzer` (`type = "ACCOUNT"`).
   - `aws_ec2_instance_metadata_defaults` (`http_tokens = "required"`, `http_put_response_hop_limit = 2`, `defense-in-depth`).
   - `aws_cloudtrail` (multi-region, management events, log file validation, `depends_on` the bucket policy) with `aws_s3_bucket.cloudtrail_logs`, its public-access block, SSE, versioning, lifecycle (expiration `cloudtrail_retention_days`) and a bucket policy limited to `cloudtrail.amazonaws.com` by `aws:SourceArn`. The trail name must match that `SourceArn`.
   - `aws_budgets_budget` with notifications at 50, 80 and 100 percent ACTUAL to `var.billing_email`.
   - `aws_guardduty_detector` (`defense-in-depth`; comment the 30-day trial).
6. **Compliance-conditional**, only when `global.compliance` contains `soc2`, `pci`, `hipaa` or `fedramp`, wrapped in `########## Compliance-Conditional ##########` markers and placed before Remote State: Config role (partition-aware `arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWS_ConfigRole`), configuration recorder, delivery channel, recorder status, Config bucket with the same hardening, `aws_securityhub_account`, the FSBP standards subscription, and the PCI standard only for `pci`. No NIST 800-53 subscription. `gdpr` changes retention only.
7. **Remote State**, always the final section, wrapped in `########## Remote State ##########` markers: `aws_s3_bucket.tfstate` with versioning, SSE (`aws:kms`) and public-access block, and `aws_dynamodb_table.tfstate_lock` (`PAY_PER_REQUEST`, hash key `LockID`). It uses a literal `{ Component = "terraform-state" }` tag and references nothing outside its own section. Do not add an active `backend` block to `main.tf`; the README names the bootstrap step.
8. **Lifecycle.** Omit the `STANDARD_IA` transition when retention is under 90 days and `GLACIER` when under 365 days.

**Opting out:** delete everything in `baseline.tf` outside the Remote State markers, remove the three email variables and their tfvars rows, and keep the `data` sources only if another file uses them.

## monitoring.tf (each group gated)

| Group | Gate | Resources |
| --- | --- | --- |
| ECS autoscaling | An ECS service mapping (`render.web_service`, `render.private_service`, `render.background_worker`) whose `aws_config.desired_count` is greater than 1, or a `preferences.json` `questions[]` answer for that `resource_id` that indicates scaling (autoscaling, burst, variable load) | `aws_appautoscaling_target` (`min_capacity = desired_count`, `max_capacity = max(desired_count * 4, 4)`), CPU and memory `aws_appautoscaling_policy` target tracking. Add `lifecycle { ignore_changes = [desired_count] }` to that `aws_ecs_service` only. |
| ECS alarms | Every emitted `aws_ecs_service` | CPU and memory high alarms in `AWS/ECS` (dimensions `ClusterName`, `ServiceName`) |
| ALB alarms | An `aws_lb` is emitted | `HTTPCode_ELB_5XX_Count`, `UnHealthyHostCount`, `TargetResponseTime` in `AWS/ApplicationELB` |
| RDS alarms | RDS is generated | `CPUUtilization`, `FreeStorageSpace`, `DatabaseConnections` in `AWS/RDS` |
| ElastiCache alarms | ElastiCache is generated | `CPUUtilization`, `DatabaseMemoryUsagePercentage`, `Evictions` in `AWS/ElastiCache` (dimension `ReplicationGroupId`) |
| Alerts topic | At least one alarm is emitted | `aws_sns_topic.alerts` with SSE, an email subscription to `var.operations_email`, and `alarm_actions` and `ok_actions` on every alarm |

The SNS topic uses `alias/aws/sns` unless `kms.tf` is emitted, then the customer-managed key.

## kms.tf (gated)

Emit only when `global.compliance` contains `hipaa`, `pci` or `fedramp`, or an `aws_config` in `aws-design.json` sets `customer_managed_key: true` or `kms: "customer_managed"`. Emit `aws_kms_key` with rotation enabled, an alias, and a key policy with an explicit account-root statement. Then set `kms_key_id` on the generated RDS instance, ElastiCache replication group and EFS file system, and on the SNS topic.

## RDS backup and point-in-time recovery

Verify only. Generated RDS blocks keep `backup_retention_period` at 7 or higher (35 when any framework is declared). Raise a lower value; do not lower a higher one.

## backup.tf (gated)

Emit only when an `Amazon EFS` mapping exists. Emit `aws_backup_vault` (the customer-managed key when `kms.tf` is emitted), `aws_backup_plan` with a daily rule and `delete_after = max(35, min(retention, 365))`, an `aws_iam_role` trusted by `backup.amazonaws.com` with `AWSBackupServiceRolePolicyForBackup` attached through a partition-aware ARN, and `aws_backup_selection` of the EFS file system ARN. Do not also emit `aws_efs_backup_policy`.

A stack with no EFS, no RDS, no alarms to create and compliance `none` emits `baseline.tf` only.
