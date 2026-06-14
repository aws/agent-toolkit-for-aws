# Security Considerations

The amazon-aurora skill creates and modifies Aurora resources when the user requests it, but blocks destructive operations (deletes, major upgrades, purchases). The agent MUST enforce the practices below.

## Table of Contents

1. [IAM Principles](#iam-principles)
2. [Credential Hygiene](#credential-hygiene)
3. [RDS Data API Warning](#rds-data-api-warning)
4. [Secure Defaults in Examples](#secure-defaults-in-examples)
5. [Output Handling](#output-handling)

## IAM Principles

The caller's IAM principal needs read and write permissions for RDS to create and modify clusters. Scope permissions to the minimum required actions.

Required permissions (by service):

| Service | Required actions |
|---|---|
| RDS | `rds:DescribeDBClusters`, `rds:DescribeDBInstances`, `rds:DescribeDBEngineVersions`, `rds:DescribeReservedDBInstancesOfferings` |
| CloudWatch | `cloudwatch:GetMetricStatistics`, `cloudwatch:ListMetrics` |
| Pricing | `pricing:GetProducts`, `pricing:DescribeServices` |
| Savings Plans | `savingsplans:DescribeSavingsPlansOfferings`, `savingsplans:DescribeSavingsPlansOfferingRates` |

Managed policies `AmazonRDSReadOnlyAccess` and `CloudWatchReadOnlyAccess` cover most of this; add Pricing and Savings Plans read actions via a scoped custom policy.

Do NOT use `AdministratorAccess` or `*:FullAccess` managed policies. Scope write permissions to the specific actions the skill uses: `rds:CreateDBCluster`, `rds:CreateDBInstance`, `rds:ModifyDBCluster`, `rds:ModifyDBInstance`, `rds:AddTagsToResource`, `rds:RemoveTagsFromResource`. For reads: `rds:Describe*`, `rds:List*`.

## Credential Hygiene

- Prefer short-lived credentials (IAM roles, `ada credentials update`, SSO) over long-lived IAM user keys.
- Do NOT create or store long-lived DB passwords from within the skill. If the user's Isengard credentials are expired, prompt them to refresh outside the skill.
- **IAM auth tokens are approved.** Calling `aws rds generate-db-auth-token` or `rds_client.generate_db_auth_token()` is explicitly safe — these produce short-lived (15-minute) tokens derived from the caller's IAM identity. They are not stored credentials. This is the required connection method for express clusters.
- Do NOT log or echo DB passwords or raw secret values. For RDS Data API precheck runs, reference secrets by their `secretArn` and let the service resolve them.
- For SSM Run Command prechecks, pass DB credentials via inline JSON parameters attached to the Run Command invocation — never via positional filesystem arguments.

## RDS Data API Warning

Enabling RDS Data API solely to run upgrade prechecks widens the cluster's connectivity surface. The Data API endpoint is HTTPS-reachable over the public AWS plane (authenticated with IAM), so it's safer than opening a new SG ingress rule, but it's still an additional attack surface.

- Warn the user before recommending they enable Data API for a one-off precheck run
- If the cluster is production and Data API is not already enabled, prefer the `user-runs-script` precheck method instead
- If Data API is enabled for the workflow, remind the user to disable it after prechecks if it wasn't previously in use

## Secure Defaults in Examples

Any CloudFormation, CDK, or AWS CLI snippet produced by this skill MUST use secure defaults:

- Cluster configuration: `StorageEncrypted: true` (and `KmsKeyId` if the user has a customer-managed key)
- TLS: cluster parameter group enables `rds.force_ssl=1`
- Security groups: scoped CIDR ranges or security-group references — NEVER `0.0.0.0/0` or `::/0`
- Public accessibility: NEVER use `--publicly-accessible`. If the user needs connectivity from outside the VPC, use express configuration (internet-accessible via IAM), RDS Data API, or an EC2 bastion with SSH tunnel.
- Parameter groups: do NOT disable `log_statement`, `log_min_duration_statement`, or audit logging parameters "for convenience"
- Logging & monitoring: recommend enabling **CloudTrail** so Aurora control-plane API activity (create / modify / delete / failover) is recorded, and **CloudWatch alarms** on security-relevant metrics such as `LoginFailures` and `DatabaseConnections`. CloudWatch log exports (`postgresql`) give query-level visibility but do not cover API-level activity — CloudTrail does.
- Resource names: no `prod`, `production`, or `PROD` as example/default values — those get copy-pasted into production accidentally

## Output Handling

- Cost numbers, instance types, and cluster IDs are not sensitive on their own, but combined with account ID they reveal environment topology. When presenting results, don't unnecessarily include the account ID.
- If a workflow surfaces a secret ARN, show only the ARN, never attempt to resolve it.
- Upgrade precheck findings may include schema names, table names, or query text from the user's database. If the output is going to be shared (posted to a ticket, shared in chat), warn the user to review for sensitive identifiers before sharing.

## References

- [Security in Amazon Aurora](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.html)
- [AWS Well-Architected Framework — Security Pillar](https://docs.aws.amazon.com/wellarchitected/latest/security-pillar/welcome.html)
- [IAM database authentication for Aurora](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.IAMDBAuth.html)
- [Using SSL/TLS with Aurora PostgreSQL](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.Security.html)
