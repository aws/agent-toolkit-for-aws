# RDS Upgrade Workflow (MySQL / MariaDB / PostgreSQL)

Live prechecks, query-load analysis, and checklists for RDS MySQL, MariaDB, and PostgreSQL — major and minor version upgrades, including instances with Read Replicas. Never executes the upgrade.

## When This Applies

User mentions: "upgrade this instance", "upgrade RDS MySQL/MariaDB/PostgreSQL", "pre-upgrade checklist", "post-upgrade steps", "upgrade prechecks", "what version should I upgrade to", Read Replica upgrade ordering, or Blue/Green for major upgrades. Do NOT use this workflow for Aurora clusters — Aurora has a separate upgrade skill.

## Tasks

### 1. Identify the Instance

Gather instance metadata. RDS uses `describe-db-instances`, not `describe-db-clusters`.

**Constraints:**

- You MUST ask for the DB instance identifier and region upfront (default: `us-east-1`)
- You MUST run `aws rds describe-db-instances --db-instance-identifier <id>` to identify the instance
- You MUST capture: engine (`mysql`, `mariadb`, or `postgres`), engine version, status, DB parameter group, instance class, Multi-AZ, encryption, deletion protection
- You MUST check `ReadReplicaSourceDBInstanceIdentifier` — if set, this instance IS a replica
- You MUST check `ReadReplicaDBInstanceIdentifiers` — if non-empty, this instance HAS replicas
- You MUST explain what command is being run and why before invoking it

### 2. Enumerate Upgrade Targets and Recommend

```bash
aws rds describe-db-engine-versions --engine <engine> --engine-version <current> \
  --query "DBEngineVersions[0].ValidUpgradeTarget[*].{EngineVersion:EngineVersion,IsMajorVersionUpgrade:IsMajorVersionUpgrade}"
```

**Constraints:**

- You MUST run `describe-db-engine-versions` rather than hard-coding versions, because valid targets change as AWS ships releases
- Engine values are exactly: `mysql`, `mariadb`, or `postgres`
- You MUST NOT mention LTS releases — RDS does NOT have LTS (unlike Aurora). Present the latest available version and the latest minor within the current major.
- You SHOULD call out Extended Support surcharge if applicable (RDS MySQL 5.7, RDS PostgreSQL 11/12)
- For instances with Read Replicas, the upgrade behavior differs by upgrade type:
  - **Minor version upgrade**: if the instance has any read replicas, upgrade the read replicas first, then upgrade the source instance.
  - **Major version upgrade**: Amazon RDS automatically upgrades in-Region read replicas along with the primary DB instance. You do NOT need to upgrade replicas separately — RDS handles this. Cross-Region read replicas are NOT automatically upgraded and must be handled independently.
- You SHOULD NOT confuse with Aurora upgrade order (Aurora upgrades the writer and readers together in a cluster — different mechanism from RDS)
- You SHOULD recommend Blue/Green deployments as a safer path for major version upgrades (see [bluegreen-advisor-workflow.md](bluegreen-advisor-workflow.md))

### 3. Live Database Precheck

**Constraints:**

- You MUST ask the user how to connect, offering three options:
  1. SSM Run Command (requires EC2 instance ID + credentials)
  2. Direct connection (publicly accessible or tunneled)
  3. Generate a script for the user to run and paste results
- RDS Data API is NOT available for standalone RDS instances — do NOT offer it
- You MUST run engine-specific queries from [upgrade-prechecks-mysql.md](upgrade-prechecks-mysql.md) for `mysql` and `mariadb` engines, or [upgrade-prechecks-postgresql.md](upgrade-prechecks-postgresql.md) for `postgres`
- For `mariadb`, run the same MySQL-compatible precheck queries from [upgrade-prechecks-mysql.md](upgrade-prechecks-mysql.md) — MariaDB is a MySQL fork and uses the same `information_schema` / `performance_schema` query surface, so run the full set (reserved keywords, `sql_mode` changes, removed features, auth plugins, engines, row formats, character sets, partitioning, definers, XA). Interpret the results against the target MariaDB version: a handful of findings are MySQL-8.0-version-specific (the 8.0 reserved-keyword additions, `caching_sha2_password`, query-cache removal) and MariaDB has its own reserved-word and parameter set, so confirm each flagged item against the target MariaDB release notes rather than assuming the MySQL 8.0 verdict applies verbatim.
- When running prechecks via SSM Run Command, enable KMS encryption on the SSM output before retrieval (schema metadata may contain sensitive details). Use minimal-privilege credentials scoped to read-only access on `information_schema`, `performance_schema`, and `mysql.user` rather than the master user.
- You MUST categorize findings as 🔴 Critical (blocks upgrade) / 🟡 Warning (behavior change) / 🟢 Clean
- You MUST generate a recommended DB parameter group (instance-level) preserving current behavior where relevant

### 4. Query Load Analysis (Optional)

**Constraints:**

- You MUST offer this step after prechecks and let the user opt in — don't force it
- You MUST pull top 5 queries from `performance_schema` (MySQL/MariaDB) or `pg_stat_statements` (PostgreSQL)
- You MUST run EXPLAIN in the engine-appropriate format: `EXPLAIN FORMAT=JSON` (MySQL/MariaDB) or `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` (PostgreSQL)
- Flag patterns per [upgrade-query-load-mysql.md](upgrade-query-load-mysql.md) or [upgrade-query-load-postgresql.md](upgrade-query-load-postgresql.md)
- MariaDB uses the same `performance_schema` and EXPLAIN approach as MySQL

### 5. Pre-Upgrade Checklist

See [upgrade-pre-checklist.md](upgrade-pre-checklist.md) for the 10-step walkthrough.

**Constraints:**

- You MUST recommend a manual snapshot before any upgrade
- You MUST explain that automated backups are NOT required for in-place upgrades, but when enabled RDS takes a pre-upgrade snapshot automatically (and skips it when disabled)
- You MUST explain that automated backups ARE required for Blue/Green deployments
- You MUST recommend testing on a snapshot-restored instance first
- You MUST mention the RDS pre-upgrade validation prechecker that runs automatically during major upgrades, and recommend previewing it manually first
- You MUST warn about MySQL 8.0 reserved keywords that may conflict with schema identifiers
- You MUST link to the target release notes: MySQL `https://dev.mysql.com/doc/relnotes/mysql/8.0/en/`, MariaDB `https://mariadb.com/kb/en/release-notes/`, PostgreSQL `https://www.postgresql.org/docs/release/`
- You MUST explain that without a custom parameter group, RDS assigns the default for the target family (e.g., `default.mysql8.0`) with target-version defaults
- You SHOULD recommend Blue/Green for major upgrades — see [bluegreen-advisor-workflow.md](bluegreen-advisor-workflow.md)
- You MUST NOT execute `modify-db-instance --engine-version` or any upgrade command

### 6. Post-Upgrade Checklist

See [upgrade-post-checklist.md](upgrade-post-checklist.md).

**Constraints:**

- You MUST NOT blanket-recommend `ANALYZE TABLE` on all user tables — it's expensive and shouldn't run during active traffic. Recommend it only if regressions are observed, targeting affected tables in a low-traffic window.
- You MUST recommend monitoring CloudWatch metrics (all engines): CPUUtilization, DatabaseConnections, ReadIOPS, WriteIOPS, FreeableMemory, FreeStorageSpace
- You MUST NOT reference non-CloudWatch metrics (e.g., `Created_tmp_disk_tables`) in the CloudWatch monitoring step — those live in `performance_schema`
- You MUST NOT recommend cleanup (deleting snapshots, old Blue/Green environments) until the user confirms the upgrade is successful with no regressions, because the pre-upgrade snapshot is the cheapest rollback path
- You MUST NOT recommend rolling back unless the user explicitly reports failure

## Troubleshooting

- **`describe-db-instances` returns no results**: Verify region and identifier spelling.
- **SSM returns empty output**: Query returned zero rows. Confirm connectivity with `SHOW DATABASES` or `SELECT datname FROM pg_database`.
- **SSM times out**: Security group missing inbound from EC2. Add port 3306 (MySQL/MariaDB) or 5432 (PostgreSQL).
- **Zero digests in `performance_schema`**: Consumer disabled or no workload. Skip query load analysis.
- **Credentials expired**: Ask user to refresh and retry.
- **Blue/Green not available**: Requires MySQL 5.7+, MariaDB 10.4+, or PostgreSQL 12.7+. If older, use in-place upgrade with snapshot.

## References

- [upgrade-prechecks-mysql.md](upgrade-prechecks-mysql.md) / [upgrade-prechecks-postgresql.md](upgrade-prechecks-postgresql.md)
- [upgrade-query-load-mysql.md](upgrade-query-load-mysql.md) / [upgrade-query-load-postgresql.md](upgrade-query-load-postgresql.md)
- [upgrade-pre-checklist.md](upgrade-pre-checklist.md)
- [upgrade-post-checklist.md](upgrade-post-checklist.md)
