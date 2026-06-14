# Express vs Full Configuration — Extended Comparison

This extends the `SKILL.md` five-dimension table (engines, networking, capacity mode, time-to-first-query, use cases) to operational capabilities: backup and PITR, monitoring, encryption, IAM, parameter groups, lifecycle, and advanced-feature eligibility.

Cells reflect the Express configuration settings table and Limitations section. Express configuration capabilities may expand over time; where a behavior is not yet enumerated by AWS, the cell reads "Default — verify in the AWS User Guide" rather than inventing a value.

## Extended comparison table

| Dimension | Express Configuration | Full Configuration |
|-----------|-----------------------|--------------------|
| Backup retention | Default 1 day (configurable 1–35 days; changeable after creation) | User-specified at creation (1–35 days) |
| Point-in-time recovery (PITR) | Supported per Aurora defaults — verify window in the AWS User Guide | Supported per configured backup retention window |
| Automated snapshots | Applied per Aurora defaults — verify schedule in the AWS User Guide | Applied per configured backup retention window |
| Manual snapshots | Supported (standard Aurora mechanics) | Supported |
| Snapshot sharing / cross-account | Aurora defaults — verify in the AWS User Guide | Supported |
| Snapshot copy to another region | Aurora defaults — verify in the AWS User Guide | Supported |
| CloudWatch metrics | Standard Aurora CloudWatch metrics apply | Standard Aurora CloudWatch metrics apply |
| Performance Insights | Disabled by default; enable after creation | Supported (optional, configurable retention) |
| Enhanced Monitoring | Disabled by default; enable after creation | Supported (optional, configurable interval) |
| Database Activity Streams | Not supported (express clusters have no VPC) | Supported |
| Encryption at rest | Enabled with an AWS owned key (SSE-RDS) — the AWS-controlled key you cannot view, manage, or change | Enabled, user-selectable AWS KMS key (AWS managed key or customer managed key) |
| Customer-managed KMS keys | Not available in the express flow — verify in the AWS User Guide | Supported |
| Encryption in transit | TLS-enforced per Aurora defaults | TLS-configurable per cluster parameters |
| IAM database authentication | Required / IAM-only. Cannot be modified. | Supported (opt-in per cluster) |
| Secrets Manager managed master password | Not supported. Express clusters use IAM auth only — no master password exists. | Supported (opt-in at creation) |
| Parameter group (cluster) | Default Aurora PostgreSQL cluster parameter group for the selected version | User-selectable (default or customer-managed) |
| Parameter group swap post-creation | Uses the Aurora default DB cluster parameter group; changeable after the create operation completes | Supported |
| Custom DB parameter group | Default — verify in the AWS User Guide | Supported |
| Deletion protection | Disabled by default; user-configurable during or after creation | User-configurable at creation and post-creation |
| Final snapshot on delete | Default — verify in the AWS User Guide | User-configurable at delete time |
| Backtrack (Aurora MySQL only) | Not applicable (PostgreSQL-only flow) | Aurora MySQL only |
| Aurora Global Database eligibility | Not supported (no VPC) | Supported (opt-in, cross-region replication) |
| Aurora Replicas / Read Replicas | Supported — add readers (local Aurora Replicas) after creation; writer and reader in different AZs (automatic failover) | Supported (up to 15 Aurora Replicas per cluster) |
| Cross-region replica | Not supported (no VPC; Aurora Global Database cross-region replication unavailable, and Cross-Region Aurora Replicas are MySQL-only while express is PostgreSQL-only) | Supported |
| Blue/Green deployments | Not supported (no VPC) | Supported |
| Zero-ETL integrations | Not supported (no VPC association) | Supported per [Aurora zero-ETL integrations documentation](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/zero-etl.html) |
| RDS Data API | Supported but disabled by default; enable after creation via ModifyDBCluster. On express clusters it does NOT support master username/password auth — you must create new user credentials | Supported per [Aurora Data API documentation](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/data-api.html) |
| Aurora zero downtime patching (ZDP) | Not supported with express configuration (no VPC association) | Follows configured behavior per cluster |
| Maintenance window | User-configurable (weekly window or No preference); changeable during or after creation. Default varies by Region | User-configurable |
| Tagging | Supported per Aurora defaults | Supported |
| VPC flow logs / VPC-level network telemetry | Not applicable (no customer VPC) | Available at the customer VPC level |

## Notes and caveats

- **Encryption-key control is the clearest break** — Express clusters use an AWS owned key (SSE-RDS), an AWS-controlled key customers cannot view, manage, or change. This is distinct from the AWS managed key for Amazon Aurora (the account-visible aws/rds key, now legacy). Workloads needing a customer-managed KMS key (BYOK/regulated) require Full Configuration. See [Encrypting Amazon Aurora resources](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Overview.Encryption.html).
- **Performance Insights and Enhanced Monitoring are disabled by default in the express flow and can be enabled after creation**, per the settings table. See [Performance Insights](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_PerfInsights.html), [Enhanced Monitoring](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_Monitoring.OS.html).
- **Parameter groups are the second-biggest operational break** — A workload needing a non-default `shared_preload_libraries`, tuned `max_connections`, or other custom cluster tuning signals Full Configuration is the right start. Express clusters use the Aurora default DB cluster parameter group, changeable after the create operation completes. See [Aurora PostgreSQL parameters](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Appendix.PostgreSQL.CommonDBATasks.Parameters.html).
- **Advanced features needing a VPC are unsupported** — Aurora Global Database, Zero-ETL integrations, and Blue/Green deployments are explicitly excluded by the express Limitations (no VPC association). Read Replicas (local Aurora Replicas) are supported and addable after creation. Workloads needing the excluded features must use Full Configuration.
- **VPC-layer observability is a non-starter by construction.** No customer VPC means VPC Flow Logs, VPC security group telemetry, and NACL logs do not apply; such workloads need Full Configuration. Standard Aurora CloudWatch metrics (CPU, connections, buffer cache, latency) still work via normal channels regardless of creation flow.

## Source documentation

Links not already cited inline:

- Create with express configuration: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_GettingStartedAurora.AuroraPostgreSQL.ExpressConfig.html
- Aurora serverless: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.html
- IAM database authentication: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.IAMDBAuth.html
- Aurora Global Database: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-global-database.html
- Aurora Blue/Green deployments: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/blue-green-deployments.html
- Aurora backups: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/USER_WorkingWithAutomatedBackups.html
