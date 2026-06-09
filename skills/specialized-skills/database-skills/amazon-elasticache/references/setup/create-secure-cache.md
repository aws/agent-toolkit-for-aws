# Create Secure Cache

End-to-end workflow from intent to a production-safe ElastiCache cache. Use when the user wants to create a new cache and you have enough context (engine, region, VPC). If context is missing, run requirements sub-skill first.

## Preflight Checks

**Do not create a new VPC if one already exists.** Use the VPC where the user's compute (Lambda, ECS, EKS, EC2) already runs. Find it from existing IaC, task definitions, or ask the user. If no VPC is found, confirm with the user before creating one.

Before provisioning, verify:

| Check | Pass criteria | Severity |
|-------|--------------|----------|
| Subnets span 2+ AZs | At least 2 subnets in different AZs | FAIL |
| Available IPs | Each subnet has 10+ free IPs (serverless needs ENIs) | WARN |
| Security group allows port 6379 | Inbound from app SG on TCP 6379 | FAIL |
| Security group allows port 6380 (serverless only) | Inbound from app SG on TCP 6380 (reader endpoint) | FAIL |
| Service quotas | Nodes per region (L-DFE45DF3), nodes per cluster CME (L-AF354865), or serverless caches per region (L-BBCDAECC) have headroom | FAIL |
| Caller permissions | `elasticache:Create*`, `ec2:CreateNetworkInterface` (serverless) | FAIL |
| Node type available (node-based only) | Offerings exist for the node type in the target region | FAIL |
| Subnet group exists (node-based only) | Named subnet group found | FAIL |

## Product Rules (check before proceeding)

- Vector search needed? Force node-based Valkey 8.2 or above (recommend 9.0; not available on data-tiering nodes; t2/t3/t4g instances require increased memory reserve). Note: T2 is transitioning to previous-generation. While still available, prefer T3 or T4g for new clusters.
- Global Datastore needed? Force node-based
- Serverless? AUTH tokens not supported. RBAC required. Clients must support cluster mode enabled.
- Node-based? Must explicitly enable: TLS, at-rest encryption, Multi-AZ, automatic failover, daily backups. At-rest encryption is immutable after creation. TLS can be enabled post-creation via a two-step process (set transit-encryption-mode to `preferred`, then `required`).

## Create the Cache

### Serverless

Key differences from node-based:

- Deploys in under a minute
- TLS, encryption at rest, Multi-AZ: all automatic (no flags needed)
- Snapshots are supported but must be explicitly configured via `SnapshotRetentionLimit` > 0 and optionally `DailySnapshotTime`. They are not enabled by default.
- Subnet IDs go directly (no subnet group resource needed)
- Must set `--cache-usage-limits` for cost controls (DataStorage in GB + ECPUPerSecond)
- Primary: `aws elasticache create-serverless-cache ...` (or boto3 `create_serverless_cache`, or CloudFormation `AWS::ElastiCache::ServerlessCache`)

### Node-Based

Key differences from serverless:

- Takes 5-15 minutes to provision
- Requires explicit security flags: `--transit-encryption-enabled`, `--at-rest-encryption-enabled`, `--automatic-failover-enabled`, `--multi-az-enabled`, `--snapshot-retention-limit 7`
- Requires a subnet group (separate resource)
- For property names per IaC tool, see `iac-reference.md`
- Primary: `aws elasticache create-replication-group ...` (Valkey/Redis with replication; or boto3 `create_replication_group`, or CloudFormation `AWS::ElastiCache::ReplicationGroup`). Use `create-cache-cluster` only for Memcached.

### VPC-Only Access Notice (mandatory after every creation)

Always tell the user after creating:

> Your cache is VPC-only. ElastiCache has no public endpoints. If you are on a local machine, you need a tunnel to connect.
>
> 1. **Reuse an existing EC2 instance ($0):**
>    - Primary: `python3 scripts/find_tunnel_host.py --vpc-id <vpc-id> --region <region>` (locates an SSM-managed instance via boto3)
> 2. **Create a new jump host (approximately $3/month, t4g.nano in us-east-1, pricing subject to change; verify current rates, only if no existing instance found):**
>    - Primary: launch a t4g.nano with `aws ec2 run-instances` and attach the `AmazonSSMManagedInstanceCore` IAM policy so SSM can manage it. Then open the tunnel with `python3 scripts/start_tunnel.py`. Bills until stopped/terminated.
> 3. **Skip** if your app runs inside the VPC (Lambda, ECS, EKS, EC2)
>
> Use the bundled scripts (`scripts/find_tunnel_host.py`, `scripts/start_tunnel.py`) as the primary path. Always try option 1 before option 2.

Tunnel startup:

```bash
python3 scripts/start_tunnel.py --instance-id <id> --cache-host <endpoint> --region <region>
python3 scripts/test_connection.py 127.0.0.1 --port 6379 --tunnel-mode --server-name <endpoint>
```

## Set Up Authentication

### RBAC sequence (both deployment models)

1. Create RBAC user: `create-user --user-id <name>-appuser --user-name <name>-appuser --engine <valkey|redis> --access-string "on ~* +@all" --authentication-mode Type=iam`
2. Create user group: `create-user-group --user-group-id <name>-usergroup --engine <valkey|redis> --user-ids default <name>-appuser`

Use the engine value that matches your cache engine (`valkey` for Valkey caches, `redis` for Redis OSS caches).
3. Attach to cache:

- Serverless: `modify-serverless-cache --serverless-cache-name <name> --user-group-id <name>-usergroup`
- Node-based: set `--user-group-ids` at creation time

**Note:** The `--engine` value for user and user-group accepts `valkey` or `redis`. Use the value that matches your cache engine.

### Authentication mode

| Mode | Flag | When to use |
|------|------|-------------|
| IAM auth (recommended) | `--authentication-mode Type=iam` | Cloud-native clients (Lambda, ECS, EKS). Requires Valkey 7.2+ or Redis OSS 7.0+ and TLS. |
| Password auth | `--authentication-mode Type=password,Passwords=<pw>` | Clients without IAM token support. Store password in Secrets Manager with rotation enabled. |

### Lock down the default user

Always disable the default user: `modify-user --user-id default --access-string "off ~* -@all"`

## Restore from Snapshot

Restore creates a new cache (cannot restore to an existing one). Constraints:

- Backups are cross-compatible between deployment models for Valkey and Redis OSS: node-based snapshots can be restored into serverless caches, and serverless snapshots can be restored into node-based clusters. Memcached serverless snapshots can only be restored into Memcached serverless caches. Serverless restore requires RDB files compatible with Valkey 7.2+ or Redis OSS 5.0+. Data-tiering (r6gd) backups can only restore to r6gd node types.
<!-- Source: https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/backups-restoring.html -->
- CLI commands differ: `create-serverless-cache --snapshot-arns-to-restore` vs `create-replication-group --snapshot-name`
- Final snapshot on delete: `--final-snapshot-name` (serverless) vs `--final-snapshot-identifier` (node-based). Memcached has no snapshot support; `--final-snapshot-identifier` does not apply to Memcached.
- Security settings (SGs, encryption, RBAC user groups) are NOT inherited. Must re-specify on the new cache.
- Cross-region snapshot copy: Native cross-region copy API is node-based only. Serverless snapshots can be exported to S3 via `export-serverless-cache-snapshot` and then copied cross-region through S3.
- S3 export for node-based snapshots uses `copy-snapshot --target-bucket`. For serverless snapshots, use the separate `export-serverless-cache-snapshot --serverless-cache-snapshot-name <name> --s3-bucket-name <bucket>` command. Available for Valkey and Redis OSS only (not Serverless Memcached). Bucket needs `elasticache.amazonaws.com` service principal in its policy.
<!-- Source: https://docs.aws.amazon.com/cli/latest/reference/elasticache/export-serverless-cache-snapshot.html -->

## Validate and Finish

1. Run `python3 scripts/test_connection.py <endpoint>` (or with `--tunnel-mode` if local)
2. If validation fails, see `connectivity-diagnostics.md`
3. Run `python3 scripts/security_audit.py --serverless <name> --region <region>` to verify security posture
4. Optionally generate observability: `python3 scripts/generate_dashboards.py --serverless <name> --region <region>`
5. Optionally generate IaC: see `iac-reference.md`

## Attribution Tags

Apply to all resources created by the skill:

| Tag Key | Value |
|---------|-------|
| `managed_by` | `aws-skills` |
| `skill` | `elasticache` |
| `skill_version` | `1.0.0` |
| `created_by` | `elasticache-skill` |
| `generation_model` | model ID of the Claude instance that ran the skill (e.g. `claude-sonnet-4-20250514`) |
| `Environment` | dev / staging / prod |
