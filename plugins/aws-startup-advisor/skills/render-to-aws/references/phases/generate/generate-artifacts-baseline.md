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
2. **Budget.** When `cost.budget_guardrail` in `preferences.json` is a number, `limit_amount` is that number. Otherwise (the default `no_budget_limit`) use the documented default `max(50, ceil(aws_monthly_balanced * 1.2))` with `aws_monthly_balanced` from `estimation-infra.json` → `projected_costs`. If the key is missing use 50 and say so in a comment. The comment above `limit_amount` shows the formula with the actual estimate.
3. **Header and locals.** A header comment names the resolved retention. A `locals` block holds `cloudtrail_retention_days` and `baseline_tags = { Component = "security-baseline" }`.
4. **Declarations owned by this file.** Shared declarations come first, outside every marker pair, because other files use them: `variable "operations_email"` (also used by `monitoring.tf`). `data.aws_partition.current` is declared once in `terraform/main.tf` by `artifacts-infra`; this file, `backup.tf` and `monitoring.tf` reference it and never redeclare it. Everything else this file owns goes inside the `########## Account Baseline ##########` / `########## End Account Baseline ##########` markers, which wrap the `locals` block and items 5 and 6: `variable "billing_email"`, `variable "security_email"` (required, no defaults), `data.aws_caller_identity.current` and the `locals` block. All variables have no defaults. Append the three email rows to `terraform.tfvars.example` with `.invalid` placeholder addresses. Do not edit `variables.tf` or `main.tf`.
5. **Always-on resources**, in this order:
   - `aws_account_alternate_contact` for OPERATIONS, BILLING and SECURITY (pinned `name` and `title`, `phone_number = "+1-555-0100"` with a comment to replace it).
   - `aws_iam_account_password_policy` (length 14, reuse prevention 24, max age 90, all four character classes).
   - `aws_s3_account_public_access_block` (all four flags true).
   - `aws_ebs_encryption_by_default` (`defense-in-depth`).
   - `aws_accessanalyzer_analyzer` (`type = "ACCOUNT"`).
   - `aws_ec2_instance_metadata_defaults` (`http_tokens = "required"`, `http_put_response_hop_limit = 2`, `defense-in-depth`).
   - `aws_cloudtrail` (multi-region, management events, log file validation, `depends_on` the bucket policy) with `aws_s3_bucket.cloudtrail_logs`, its public-access block, SSE, versioning, lifecycle (expiration `cloudtrail_retention_days`) and a bucket policy limited to `cloudtrail.amazonaws.com` by `aws:SourceArn`. The trail name must match that `SourceArn`.
   - `aws_budgets_budget` (limit from item 2) with notifications at 50, 80 and 100 percent ACTUAL to `var.billing_email`.
   - `aws_guardduty_detector` (`defense-in-depth`; comment the 30-day trial).
6. **Compliance-conditional**, only when `global.compliance` contains `soc2`, `pci`, `hipaa` or `fedramp`, wrapped in `########## Compliance-Conditional ##########` markers and placed before Remote State: Config role (partition-aware `arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWS_ConfigRole`), configuration recorder, delivery channel, recorder status, Config bucket with the same hardening, `aws_securityhub_account`, the FSBP standards subscription, and the PCI standard only for `pci`. No NIST 800-53 subscription. `gdpr` changes retention only.
7. **Remote State**, always the final section, wrapped in `########## Remote State ##########` markers: `aws_s3_bucket.tfstate` with versioning, SSE (`aws:kms`) and public-access block, and `aws_dynamodb_table.tfstate_lock` (`PAY_PER_REQUEST`, hash key `LockID`). It declares its own `data "aws_caller_identity" "tfstate"` for the bucket name and uses a literal `{ Component = "terraform-state" }` tag. Besides `var.project_name` and `var.environment` from `variables.tf`, it references nothing outside its own section. Do not add an active `backend` block to `main.tf`; the README names the bootstrap step.
8. **Lifecycle.** Omit the `STANDARD_IA` transition when retention is under 90 days and `GLACIER` when under 365 days.

**Opting out:** delete the block from `########## Account Baseline ##########` through `########## End Account Baseline ##########` (it includes the Compliance-Conditional block), and remove the `billing_email` and `security_email` tfvars rows. Keep the shared declarations above the block and the Remote State section. Keep `operations_email` while `monitoring.tf` exists. The result must pass `terraform validate`.

## monitoring.tf (each group gated)

| Group | Gate | Resources |
| --- | --- | --- |
| ECS autoscaling | An ECS service mapping (`render.web_service`, `render.private_service`, `render.background_worker`) whose `aws_config.desired_count` is greater than 1, or a `preferences.json` `questions[]` answer for that `resource_id` that indicates scaling (autoscaling, burst, variable load) | `aws_appautoscaling_target` (`min_capacity = desired_count`, `max_capacity = max(desired_count * 4, 4)`), CPU and memory `aws_appautoscaling_policy` target tracking. The `infra-compute` fragment writes `lifecycle { ignore_changes = [desired_count] }` on that `aws_ecs_service`; this file never edits `compute.tf`. |
| ECS alarms | Every emitted `aws_ecs_service` | CPU and memory high alarms in `AWS/ECS` (dimensions `ClusterName`, `ServiceName`) |
| ECS Express alarms | Every emitted `aws_ecs_express_gateway_service` | CPU and memory high alarms in `AWS/ECS` (dimensions `ClusterName`, `ServiceName`). Express emits no `aws_lb`, so no ALB alarm row applies to it |
| ALB alarms | An `aws_lb` is emitted | `HTTPCode_ELB_5XX_Count`, `UnHealthyHostCount`, `TargetResponseTime` in `AWS/ApplicationELB` |
| RDS alarms | An `aws_db_instance` is generated | `CPUUtilization`, `FreeStorageSpace`, `DatabaseConnections` in `AWS/RDS` with dimension `DBInstanceIdentifier` |
| Aurora alarms | An `aws_rds_cluster` is generated | `CPUUtilization`, `DatabaseConnections`, `FreeLocalStorage` in `AWS/RDS`, one alarm per `aws_rds_cluster_instance` with dimension `DBInstanceIdentifier`. Aurora publishes no `FreeStorageSpace`. For Aurora Serverless v2 add `ServerlessDatabaseCapacity` against `max_capacity` with dimension `DBClusterIdentifier` |
| ElastiCache alarms | An `aws_elasticache_replication_group` is generated | `CPUUtilization`, `DatabaseMemoryUsagePercentage`, `Evictions` in `AWS/ElastiCache`, one alarm per member cache cluster with dimension `CacheClusterId` (`<replication_group_id>-001` and so on, one per `num_cache_clusters`). Node-based metrics are not published under `ReplicationGroupId` alone |
| Valkey Serverless alarms | An `aws_elasticache_serverless_cache` is generated | `ElastiCacheProcessingUnits` and `BytesUsedForCache` in `AWS/ElastiCache` with dimension `clusterId` (the cache `name`), compared against the `cache_usage_limits` maximums. No per-member alarm applies, because a serverless cache has no member cache clusters |
| Alerts topic | At least one alarm is emitted | `aws_sns_topic.alerts` encrypted with a customer-managed key, an email subscription to `var.operations_email`, and `alarm_actions` and `ok_actions` on every alarm |

CloudWatch alarm actions cannot publish to a topic encrypted with the AWS managed `alias/aws/sns` key, so never use it for the alerts topic. When `kms.tf` is emitted the topic uses that key. Otherwise `monitoring.tf` emits its own `aws_kms_key.alerts` (rotation enabled) and alias, with its own `data.aws_caller_identity.monitoring`. In both cases the key policy has an explicit account-root statement and a statement granting `cloudwatch.amazonaws.com` `kms:GenerateDataKey*` and `kms:Decrypt`, scoped by `aws:SourceAccount` and an `aws:SourceArn` pattern for alarms named `${local.name_prefix}-*`.

## kms.tf (gated)

Emit only when `global.compliance` contains `hipaa`, `pci` or `fedramp`, or an `aws_config` in `aws-design.json` sets `customer_managed_key: true` or `kms: "customer_managed"`. Emit exactly one stack key, `aws_kms_key.stack`, with rotation enabled, an alias `alias/${local.name_prefix}-stack`, and a key policy with an explicit account-root statement. Also emit the output `kms_key_arn` (the key ARN) in `kms.tf`, so compute can grant `kms:Decrypt` on it. No other file declares a customer-managed key for stack data, and the gate for this file is the gate every generation fragment uses to decide between this key and AWS-managed encryption. When `monitoring.tf` emits the alerts topic, also add the CloudWatch statement from the monitoring section to this key policy (declare any data source the key needs in `kms.tf` itself). Then use `aws_kms_key.stack` on the SNS topic. `kms.tf` does not edit resources owned by other files. `data.tf` (see `generate-infra-data.md`) and `storage.tf` reference `aws_kms_key.stack` for the RDS or Aurora storage, Performance Insights and managed master secret, ElastiCache, and EFS file system they emit. Without `kms.tf` those resources use AWS-managed encryption and carry no `kms_key_id` argument.

## RDS backup and point-in-time recovery

Verify only. Generated RDS blocks keep `backup_retention_period` at 7 or higher (35 when any framework is declared). Raise a lower value; do not lower a higher one.

## backup.tf (gated)

Emit only when an `Amazon EFS` mapping exists. Emit `aws_backup_vault` (the customer-managed key when `kms.tf` is emitted), `aws_backup_plan` with a daily rule, an `aws_iam_role` trusted by `backup.amazonaws.com` with `AWSBackupServiceRolePolicyForBackup` attached through a partition-aware ARN, and `aws_backup_selection` of the EFS file system ARN. Do not also emit `aws_efs_backup_policy`.

`delete_after` is the resolved integer written as a literal: 35 when no framework is declared, otherwise `max(35, min(cloudtrail_retention_days, 365))`. Never reference `local.cloudtrail_retention_days`. Account Baseline opt-out removes that local, and a reference would fail validation.

A stack with no EFS, no RDS, no alarms to create and compliance `none` emits `baseline.tf` only.
