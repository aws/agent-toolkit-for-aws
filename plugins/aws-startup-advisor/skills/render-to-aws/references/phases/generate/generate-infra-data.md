---
_fragment: infra-data
_of_phase: generate
_contributes:
  - terraform/data.tf
---

# Generate data infrastructure (`data.tf`)

Applies to the `render.postgres` and `render.key_value` rows of `aws-design.json`. Emit exactly the one target Design selected for each source resource (see `references/design-refs/data.md`); never emit both RDS and Aurora, or both Serverless and node-based Valkey, for one source. Network, compute, storage, and delivery guidance live in their own fragments and are out of scope here. Checked-in golden variants for this guidance are under `fixtures/expected/generated-variants/data-*`.

## Rules for every data resource

- Place every data resource in private subnets through a dedicated subnet group, with `publicly_accessible = false` where the attribute exists.
- Give the data tier its own security group. Allow only the database or cache port, and only from the security groups of the compute services that the design edges name. Never use `cidr_blocks` on a data ingress rule.
- Encrypt at rest and in transit. Prefer one customer-managed KMS key per stack with rotation enabled, shared by storage, Performance Insights, and the managed secret.
- Never emit a credential, connection string with a password, or `password`, `auth_token`, or `master_password` variable. Passwords created by RDS or by ElastiCache must never pass through Terraform state as inputs.
- Take engine major version, extensions, and parameters from the Discover and Clarify evidence. Pin the major version explicitly and never use `latest` or an unconstrained version.
- Size from the balanced sizing recorded by Design (`knowledge/design/postgres-rds-sizing.json`, `knowledge/design/keyvalue-elasticache-sizing.json`), through typed variables with validation.
- Emit non-secret endpoints, ports, and secret ARNs as outputs with descriptions. Mark an output `sensitive = true` only when its value contains something that must not be logged.

## Render PostgreSQL

### Amazon RDS for PostgreSQL (`aws_db_instance`)

Use for the conventional single-instance or Multi-AZ workload selected by rule 3 or 6 of the PostgreSQL selector.

- Engine: `engine = "postgres"` with an explicit `engine_version` major pin, and `db_name` from the source database name.
- Credentials: `manage_master_user_password = true`, optionally with `master_user_secret_kms_key_id`. Emit `username` as a non-secret value and omit `password`.
- Parameter group: `aws_db_parameter_group` whose `family` matches the engine major version (for example `postgres16`), referenced through `parameter_group_name`. Set `rds.force_ssl = 1`.
- Multi-AZ: set `multi_az` from the availability preference recorded in Clarify. A production or high-availability preference selects `true`; a documented development preference may select `false`.
- Storage: `storage_type = "gp3"`, `allocated_storage` from the sizing table, and `max_allocated_storage` set above it so storage autoscaling is on. Autoscaling cannot be reversed after growth, so choose the ceiling deliberately.
- Backups: `backup_retention_period` of at least 7 for production (point-in-time recovery requires a value above 0), `copy_tags_to_snapshot = true`, and a `backup_window` away from the maintenance window.
- Protection: `deletion_protection = true`, `skip_final_snapshot = false`, and a `final_snapshot_identifier`. A non-production stack may relax these only when the Clarify answers say the data is disposable.
- Observability: `performance_insights_enabled = true` with a KMS key, and `enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]`.
- Minor versions: `auto_minor_version_upgrade = true` with a `maintenance_window` outside peak traffic, and `apply_immediately = false` so parameter changes land in the window.

### Amazon Aurora PostgreSQL (`aws_rds_cluster` and `aws_rds_cluster_instance`)

Use only when rule 2 of the selector fired (Global Database, reader autoscaling, Serverless behavior, or an evidence-backed availability or performance requirement).

- Resources: one `aws_rds_cluster` with `engine = "aurora-postgresql"` plus `aws_rds_cluster_instance` resources that reference it. Do not use `aws_db_instance` for Aurora.
- Credentials: `manage_master_user_password = true` on the cluster, with `master_user_secret_kms_key_id`. The secret ARN is `master_user_secret[0].secret_arn`.
- Parameter groups: `aws_rds_cluster_parameter_group` with `family = "aurora-postgresql<major>"` referenced by `db_cluster_parameter_group_name`. Put logical-replication and SSL settings here, not on an instance group.
- Availability: Multi-AZ comes from instance count. Two or more instances place a reader in a second Availability Zone; set `promotion_tier` so the intended failover target is lowest. A high-availability preference with a single instance is a defect.
- Storage: Aurora storage grows automatically, so do not emit `allocated_storage`, `storage_type`, or `max_allocated_storage` unless Aurora I/O-Optimized was selected explicitly.
- Serverless v2: only when Design selected it, set `engine_mode = "provisioned"`, add a `serverlessv2_scaling_configuration` block with `min_capacity` and `max_capacity`, and use `instance_class = "db.serverless"`.
- Backups and protection: `backup_retention_period`, `deletion_protection = true`, `skip_final_snapshot = false`, and `final_snapshot_identifier`, as for RDS.
- Observability: `performance_insights_enabled = true` on each instance, and `enabled_cloudwatch_logs_exports = ["postgresql"]` on the cluster.

### Logical replication and migration prerequisites

The migration method selector (`pg_dump and pg_restore`, `logical replication`, `AWS Database Migration Service`) decides which of these appear.

- For logical replication or DMS change data capture, set `rds.logical_replication = 1` in the parameter group with `apply_method = "pending-reboot"`. It is a static parameter, so the instance or cluster must reboot after the change. Emit it before cutover and record the reboot in the Terraform README.
- Raise `max_replication_slots`, `max_wal_senders`, and `max_worker_processes` to cover one slot per migration task plus headroom. Static changes need a reboot as well.
- Leave `wal_sender_timeout` at its default unless DMS reports timeouts during full load.
- List extensions from the source inventory in the README with `CREATE EXTENSION` steps. Extensions that need `shared_preload_libraries` (for example `pg_stat_statements` or `pg_cron`) must be set in the parameter group, with a reboot. Never claim an extension that RDS or Aurora does not support; return to Clarify.
- Do not create a DMS replication instance, endpoints, or tasks in `data.tf`. Migration execution belongs to `scripts/migrate-postgres.sh`; Terraform only prepares the target.
- The source user needs the `REPLICATION` attribute (or `rds_superuser` on the target side). Record this as a manual prerequisite and never create or print the source credential.

## Render Key Value

Every target must preserve the persistence and eviction facts from the source. A source with persistence off is a cache, so snapshots may be disabled or short. A source that is a queue or holds only copies of data needs Design's explicit evidence before snapshots or Multi-AZ are dropped.

### ElastiCache for Valkey, node-based (`aws_elasticache_replication_group`)

- Resource: `aws_elasticache_replication_group` with `engine = "valkey"` and an explicit `engine_version`. Never write `engine = "redis"`.
- Topology: `num_cache_clusters` of 2 or more with `automatic_failover_enabled = true` and `multi_az_enabled = true` for a high-availability preference. Use `num_node_groups` and `replicas_per_node_group` only when the source uses cluster mode.
- Encryption: `at_rest_encryption_enabled = true`, `transit_encryption_enabled = true`, and `kms_key_id`. Clients must use TLS.
- Auth: use an `aws_elasticache_user_group` with IAM authentication or ACL users, passed through `user_group_ids`. Do not emit `auth_token`, which would pass a secret through Terraform input.
- Parameter group: `aws_elasticache_parameter_group` with the matching Valkey family (for example `valkey8`), referenced through `parameter_group_name`. Set `maxmemory-policy` to the source policy; use `allkeys-lru` only for a pure cache with no stored policy. `noeviction` is for queues and data stores where loss is not accepted.
- Persistence: `snapshot_retention_limit` of 0 for a cache that tolerates a cold start, and at least 1 with a `snapshot_window` for data that must survive a restart. Add `final_snapshot_identifier` when snapshots are on.
- Maintenance: `auto_minor_version_upgrade = true`, `maintenance_window`, and `apply_immediately = false`.
- Logs: add `log_delivery_configuration` for `slow-log` when a CloudWatch log group exists.
- Node type: take `node_type` from the sizing knowledge file for the balanced scenario, as a typed variable.

### ElastiCache for Valkey Serverless (`aws_elasticache_serverless_cache`)

Use only when the selector chose Serverless (rule 3), not as a default.

- Resource: `aws_elasticache_serverless_cache` with `engine = "valkey"` and `major_engine_version`.
- Limits: always set `cache_usage_limits` with `data_storage` and `ecpu_per_second` maxima from the memory plan, so cost has a ceiling.
- Network and encryption: `subnet_ids`, `security_group_ids`, and `kms_key_id`. Transit encryption is always on and is not configurable.
- Auth: a `user_group_id` with an `aws_elasticache_user` of `authentication_mode { type = "iam" }`, plus the required `default` user set to `access_string = "off -@all"`.
- Snapshots: `snapshot_retention_limit` and `daily_snapshot_time` follow the persistence rule above.
- Compatibility: Serverless runs in cluster mode only. If the source uses multi-key commands across slots, Lua, or `SELECT` of non-zero databases, Design must not have selected it. Stop and report the mismatch.
- Outputs: `endpoint[0].address`, `endpoint[0].port`, and the cache ARN. A node-based group uses `primary_endpoint_address` (or `configuration_endpoint_address` in cluster mode) and `reader_endpoint_address`.

### Amazon MemoryDB (`aws_memorydb_cluster`)

Use only for an explicit active-active cross-Region or durability requirement.

- Resources: `aws_memorydb_cluster` with `engine = "valkey"`, `tls_enabled = true`, `kms_key_arn`, `acl_name` from an `aws_memorydb_acl`, `subnet_group_name`, `security_group_ids`, `snapshot_retention_limit`, and `num_replicas_per_shard` of at least 1.
- Auth: an ACL with users that use IAM authentication or `passwords` generated outside Terraform. Never take a password variable.
- MemoryDB is durable by design, so do not set eviction to a cache policy unless the source does.
- A multi-Region requirement needs `aws_memorydb_multi_region_cluster`, which is a specialist item. Record it in `generation-warnings.json` and do not guess its settings.

### Self-managed Valkey on Amazon EC2

Terraform generation for this target is `unsupported`. Emit the `unsupported` row with the specialist-validation reason from Design and no EC2 data tier.

## Handing credentials and endpoints to compute

- Compute receives only references. For PostgreSQL, emit `database_endpoint`, `database_port`, and `database_secret_arn` as outputs. The ECS task definition injects the secret through `secrets[].valueFrom`, using the JSON key (for example `<secret_arn>:password::`), and gets host and port as plain `environment` entries.
- Never build a connection string with a password in Terraform, an output, a tfvars file, or a log. The application assembles it at startup from the injected parts, or reads the whole secret.
- Grant the task execution role `secretsmanager:GetSecretValue` on only the secret ARN, plus `kms:Decrypt` on the data KMS key when the secret uses a customer-managed key. Never use `Resource = "*"`.
- For Valkey with IAM authentication, grant the task role `elasticache:Connect` on the cache or replication group ARN and the user ARN. Emit the user ID as an output.
- Emit the data security group ID as an output so network and compute fragments refer to it. Do not edit compute or network files from this fragment.

## Anti-patterns

Fail generation, or fix before returning, if any of these appear:

- A `password`, `master_password`, or `auth_token` variable or literal, or a `random_password` resource that feeds a database.
- `publicly_accessible = true`, a data ingress with `0.0.0.0/0` or `::/0`, or a data port opened to a VPC CIDR instead of a security group.
- `storage_encrypted = false` or absent, `at_rest_encryption_enabled` absent on a replication group, or `transit_encryption_enabled = false`.
- `skip_final_snapshot = true` or `deletion_protection = false` on a production or unspecified-environment database.
- `backup_retention_period = 0` on a database that is not marked disposable.
- `rds.logical_replication` set with `apply_method = "immediate"`, or set on a cluster parameter group for an `aws_db_instance`.
- Using `aws_db_instance` for Aurora, or `allocated_storage` on an Aurora cluster.
- `multi_az = false` or a single Aurora instance when the availability preference is high availability.
- `engine = "redis"` when Design selected Valkey, or a Valkey Serverless cache without `cache_usage_limits`.
- Default parameter groups for a database that needs logical replication, `rds.force_ssl`, or a custom eviction policy.
- `apply_immediately = true` on a production database, or `latest` as an engine version.
- A connection string that contains a password, in Terraform or in generated docs.
- Emitting an `aws_dms_*` resource, or an RDS and Aurora pair, for one source.

## Ordering

1. KMS key and alias.
2. Subnet groups, then the data security group.
3. Parameter groups, then the cluster or instance that uses them.
4. Cluster before cluster instances; ACL users, then user group, then cache.
5. Outputs last.

Apply order for the operator, recorded in the Terraform README: apply the data stack, reboot after any static parameter change, create extensions, run the migration method selected by Design, validate, then cut over compute. Roll back by pointing compute at the Render endpoint. Do not delete the source until the rollback window closes.
