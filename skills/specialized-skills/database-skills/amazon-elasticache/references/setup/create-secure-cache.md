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

- Vector search needed? Use node-based Valkey 8.2 or above (recommend 9.1) or Serverless Valkey 9.0+ (not available on data-tiering nodes; t3/t4g need a larger memory reserve). See [Search features and limits](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/search-features-limits.html).
- Global Datastore needed? Force node-based
- Serverless? AUTH tokens not supported. RBAC required. Clients must support cluster mode enabled.
- Node-based? Must explicitly enable: TLS, at-rest encryption, Multi-AZ, automatic failover, daily backups. At-rest encryption is immutable after creation. TLS can be enabled post-creation via a two-step process (set transit-encryption-mode to `preferred`, then `required`).
- Durable primary database needed? Force node-based Valkey 9.0+ with durability: `sync` gives zero data loss with single-digit-ms writes; `async` gives microsecond writes with up to 10 seconds of loss on failure. Check the Durability requirements below.

## Create the Cache

### Serverless

Key differences from node-based:

- Deploys in under a minute
- TLS, encryption at rest, Multi-AZ: all automatic (no flags needed)
- Snapshots are supported but must be explicitly configured via `SnapshotRetentionLimit` > 0 and optionally `DailySnapshotTime`. They are not enabled by default.
- Subnet IDs go directly (no subnet group resource needed)
- Must set `--cache-usage-limits` for cost controls (DataStorage in GB + ECPUPerSecond)
- Primary: `aws elasticache create-serverless-cache ...` (or boto3 `create_serverless_cache`, or CloudFormation `AWS::ElastiCache::ServerlessCache`)

#### Public Endpoint (Serverless Valkey 9.0+ only)

A Serverless Valkey 9.0+ cache can use a public endpoint instead of a VPC endpoint, so clients connect over the internet with no tunnel. Every connection uses IAM auth and TLS 1.3. The connection type can't change after creation. Set it with `--connection-type public` (CLI), CloudFormation `ConnectionType: public`, or Terraform `connection_type = "public"` on `aws_elasticache_serverless_cache` (AWS provider 6.73.0 or later).

**MUST confirm first.** Before running `--connection-type public`, confirm the user wants the cache reachable from the internet, and offer a VPC-only cache reached through VPC peering, a VPN, or an SSM tunnel first. A request that already asks for public access and rules out the VPC options counts as confirmed.

The cache needs a user group in which every user uses IAM auth: the system-managed `default.iam-user-group`, or a custom group created before the cache.

```bash
aws elasticache create-serverless-cache \
  --serverless-cache-name <name> --engine valkey --major-engine-version 9 \
  --connection-type public --user-group-id default.iam-user-group \
  --cache-usage-limits 'DataStorage={Maximum=10,Unit=GB},ECPUPerSecond={Maximum=5000}' \
  --tags <Global rule 9 tags> \
  --region <region>
```

After creating, give the Public Access Notice below. `--network-type` (`ipv4`, `ipv6`, `dual_stack`) applies to both connection types.

### Node-Based

Key differences from serverless:

- Takes 5-15 minutes to provision
- Requires explicit security flags: `--transit-encryption-enabled`, `--at-rest-encryption-enabled`, `--automatic-failover-enabled`, `--multi-az-enabled`, `--snapshot-retention-limit 7`
- Requires a subnet group (separate resource)
- For property names per IaC tool, see `iac-reference.md`
- Primary: `aws elasticache create-replication-group ...` (Valkey/Redis with replication; or boto3 `create_replication_group`, or CloudFormation `AWS::ElastiCache::ReplicationGroup`). Use `create-cache-cluster` only for Memcached.

#### Durability (Valkey 9.0+, node-based)

Add `--durability sync` or `--durability async` to `create-replication-group`:

```bash
aws elasticache create-replication-group \
  --replication-group-id <name> --engine valkey --engine-version 9.1 \
  --num-node-groups <n> --replicas-per-node-group <n> --cache-node-type <type> \
  --multi-az-enabled --automatic-failover-enabled --transit-encryption-enabled \
  --at-rest-encryption-enabled --durability sync \
  --tags <Global rule 9 tags> \
  --region <region>
```

Requirements and limits (check all before recommending durability):

- Cluster Mode Enabled only; Multi-AZ with at least one replica per shard.
- Node families R6g/R7g/R8g, M6g/M7g/M8g, C7gn/C8gn only (confirm against [Durability limitations](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Durability.Limitations.html) if a newer family may have launched).
- Not supported on Serverless, Global Datastore, data tiering, Outposts, or Local Zones.
- Up to 100 MiBps of write throughput per primary node.
- Encryption at rest is turned on automatically, and stays on if durability is later disabled.
- No online migration from self-managed Valkey or Redis OSS into a durable cluster. Migrate first, turn TLS on (`preferred`, then `required`), then turn durability on.
- With search indexes, writes to indexed keys can be throttled.

Durability can change on an existing cluster without recreating it: `aws elasticache modify-replication-group --replication-group-id <name> --durability {sync|async|disabled}`. The cluster needs in-transit encryption in mode `required` (`preferred` is refused), and the durability change must be the only change in that request. Nodes are replaced, so expect a brief failover per shard; run it in a maintenance window. Confirm with `EffectiveDurability` in `describe-replication-groups` once the status is `available` (a failed change rolls back). See [Changing durability on an existing cluster](https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/Durability.ChangingDurability.html). In Terraform, set `durability` on `aws_elasticache_replication_group`.

Monitor `DurabilityLag` (age of the oldest acknowledged write not yet in the Multi-AZ transaction log, milliseconds) and, for `async`, `DurabilityBufferExceededErrorCount` (writes rejected for exceeding the 10-second window).

### VPC-Only Access Notice (mandatory after creating a VPC-only cache)

Always tell the user after creating:

> Your cache is VPC-only. If you are on a local machine, you need a tunnel to connect.
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

### Public Access Notice (mandatory after creating a public cache)

Always tell the user after creating:

> Your cache is reachable from the whole internet. To restrict who can create public caches, use the `elasticache:ConnectionType` condition key on `elasticache:CreateServerlessCache`. Grant `elasticache:Connect` only to the roles that need it, enable CloudTrail API logging, and alarm on failed logins and spikes in new connections.

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

- Backups are cross-compatible between deployment models for Valkey and Redis OSS: node-based snapshots can be restored into serverless caches, and serverless snapshots can be restored into node-based clusters. Memcached serverless snapshots can only be restored into Memcached serverless caches. Serverless restore requires RDB files compatible with Valkey 7.2+ or Redis OSS 5.0+. Data-tiering backups (r6gd/r7gd/r8gd) can restore to any r6gd/r7gd/r8gd node type, never into a non-tiered cluster.
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
