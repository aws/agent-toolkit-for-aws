# Migration

**When to use:** The user wants to migrate from self-hosted Redis to ElastiCache, upgrade from Redis OSS to Valkey, move between node-based and serverless deployment models, or needs a preflight compatibility check for a planned migration.
**When not needed:** The user is creating a new cache from scratch (use create-secure-cache.md), asking about data modeling patterns, monitoring, or GenAI features.

Migrate to ElastiCache from self-hosted Redis, or between ElastiCache engines and deployment models.

## Loading

Read this file first. Other references in this folder load on demand when the current answer requires them. Scripts in `scripts/` run on demand (for example, `migration_preflight.py` before cutover).

## Check for existing context

Before starting, read `.elasticache/requirements.json` if it exists. Use `engine`, `deployment_model`, and `infrastructure.endpoint` to understand the current cache. If the file does not exist, gather this information from the user.

## References

- `references/migration/valkey-migration-guide.md` -- Redis-to-Valkey migration decision tree, client compatibility matrix, multi-step upgrade paths, extended support cost impact. Load when the user is planning or executing a Redis-to-Valkey engine switch.
- `references/migration/self-managed-migration.md` -- self-managed Redis to ElastiCache migration details.
- `references/migration/upgrade-patching.md` -- engine version upgrades, service update patching, node type changes, maintenance windows.
- `references/migration/feature-comparison.md` -- engine and deployment model comparison matrices.
- `references/migration/auth-migration.md` -- AUTH token to RBAC migration, RBAC user/group setup, IAM auth setup, cluster-mode disabled to cluster-mode enabled migration. Load when the user is changing authentication models or enabling cluster mode.
- `references/migration/global-datastore-operations.md` -- Global Datastore setup, adding/removing secondary regions, cross-region failover, engine upgrades on Global Datastore. Load when the user is working with cross-region replication or Global Datastore.
- `references/migration/rollback-procedures.md` -- rollback plans, undo migration, recovery from failed migrations.
- `references/migration/topology-validation.md` -- AZ, subnet, security group validation before migration.
- `references/migration/sizing-assessment.md` -- memory, CPU, connection, throughput assessment for target sizing.

## Intent-to-File Routing

**IMPORTANT:** When the user mentions migrating from self-managed, self-hosted, on-prem, EC2-hosted, or any non-ElastiCache Redis/Valkey/Memcached instance, ALWAYS load `self-managed-migration.md` before answering. This file contains critical constraints (e.g., DUMP/RESTORE is banned for cross-engine migration because serialization formats are engine-specific). Without it, models default to DUMP/RESTORE which will silently corrupt data.

| User asks about | Load |
|---|---|
| Redis to Valkey, engine switch, cost savings | `valkey-migration-guide.md` |
| Self-managed, self-hosted, on-prem, EC2, non-ElastiCache Redis to ElastiCache | `self-managed-migration.md` (FORCE LOAD) |
| Version upgrade, patching, node type change, maintenance window | `upgrade-patching.md` |
| Engine or deployment model comparison | `feature-comparison.md` |
| AUTH to RBAC, cluster mode disabled to enabled | `auth-migration.md` -- CMD to CME is a two-step process (disabled to compatible to enabled), requires Valkey 7.2+/Redis OSS 7.0+, auto-failover with 1+ replicas, keys in DB 0 only, and is **irreversible** once set to enabled |
| Global Datastore, cross-region replication | `global-datastore-operations.md` |
| Rollback, undo migration, something went wrong | `rollback-procedures.md` |
| AZ mismatch, subnet, security group port issues | `topology-validation.md` |
| Target sizing, memory/CPU assessment, cost estimation | `sizing-assessment.md` |

## Scripts

- `scripts/migration_preflight.py` -- preflight validation (version, modules, memory, cluster mode)
- `scripts/serverless_estimator.py` -- estimates what existing clusters would cost on serverless (uses actual metrics)
- `scripts/command_classifier.py` -- classifies commands for ECPU estimation (used by serverless_estimator)
- `scripts/pricing.py` -- pricing loader with built-in defaults (used by serverless_estimator)
- `scripts/collect_metrics.sh` -- collects memory, commandstats, replication info from a running cluster
- `assets/examples/sample_input_simple.csv` -- example cluster input for serverless_estimator
- `assets/examples/sample_commandstats.csv` -- example per-command stats for detailed mode
- `scripts/price_calculator.py` -- greenfield cost comparison (serverless vs node-based, engine vs engine)

## Workflow

### IMPORTANT: Validate-Before-Migrate Gate (Hard Requirement)

**The skill must NOT emit, suggest, or execute any migration command (test-migration, start-migration, complete-migration, modify-replication-group for engine switch, or any data-migration command via CLI or SDK) until ALL preflight checks pass.** This is a hard gate, not a recommendation. If any preflight check returns a FAIL status, the skill must refuse to proceed and instruct the user to resolve the failures first.

This gate applies regardless of user urgency, automation context, or IDE mode. The "Never-Auto-Execute List" includes: migration cutover execution, engine switches, replication group deletion, snapshot restoration to production clusters, and Global Datastore regional failover.

### Step 1: Identify the migration path

Determine which migration path applies (see "Migration Paths" below). This determines which preflight checks, topology validations, and rollback procedures are relevant.

### Step 2: Run preflight validation (MANDATORY, blocks all subsequent steps)

Run the preflight check against the source:

```bash
python3 scripts/migration_preflight.py --host <source-host> --port 6379
python3 scripts/migration_preflight.py --host <source-host> --port 6379 --tls  # if TLS
```

This checks version compatibility, module usage, key count, memory, cluster mode, and sizing.

**Gate enforcement rules:**

- If the preflight script exits with a non-zero status (any FAIL finding), the skill MUST stop here.
- The skill MUST NOT proceed to Step 3 or any subsequent step.
- The skill MUST present each FAIL finding to the user with remediation guidance.
- The skill MUST ask the user to resolve all failures and re-run preflight before continuing.
- WARN findings should be presented to the user but do not block the migration.

### Topology and Sizing

After preflight passes, validate topology and sizing:

- Topology validation (AZ, subnet, security group compatibility): see `topology-validation.md`
- Sizing assessment (memory, CPU, connections, cost estimation): see `sizing-assessment.md`

### Step 3: Create pre-cutover snapshot

Before executing any migration command, create a snapshot of the source (if ElastiCache) or confirm a backup exists (if self-managed):

```bash
# For ElastiCache source
aws elasticache create-snapshot \
  --replication-group-id <source-cluster> \
  --snapshot-name pre-migration-$(date +%Y%m%d-%H%M%S) \
  --region <region>
```

The skill MUST confirm the snapshot is in `available` status before proceeding.

### Step 4: Execute migration with AWS CLI or SDK

Only after Steps 2, 3, and topology/sizing validation pass. Use the migration commands described in the "Migration Paths" section below.

### Step 5: Validate and cut over

Before cutover, the skill must follow this approval gate:

- Show before/after configuration diff
- Confirm timing window with the user
- Require explicit "proceed" from the user
- Suggest snapshot before cutover (already done in Step 3)

**Connection draining:** Before switching endpoints, drain existing connections to the old cache. Stop sending new requests to the old endpoint, wait for in-flight operations to complete (typically 5-10 seconds), then switch. If using connection pools, close the old pool after all borrowed connections are returned. Do not kill active connections mid-operation.

### Step 6: Run security audit on the new cache

```bash
python3 scripts/security_audit.py --serverless <name>
python3 scripts/security_audit.py --replication-group <name>
```

### Step 7: Post-migration validation

Verify key count, spot-check data, confirm latency, and monitor error rates. See the "Pre-Migration Checklist" section and `references/migration/rollback-procedures.md` for the verification checklist.

### Step 8: Update requirements.json and hand off

After migration completes, update `.elasticache/requirements.json` with the new cache's details: `engine`, `deployment_model`, `infrastructure.cache_name`, `infrastructure.endpoint`, `infrastructure.auth_model`. This ensures downstream sub-skills (setup, data-modeling, monitoring) pick up the new cache without re-asking. Then prompt the user: "Want me to set up monitoring for the new cache?" If yes, hand off to `monitoring`.

### Always: Confirm with the user before each destructive step

The skill must never auto-execute destructive operations (engine switches, cluster deletion, snapshot restoration, migration cutover). Always require explicit user confirmation.

## Migration Paths

### Self-Hosted Redis to ElastiCache

Migration tools in sequence:

1. **Test first**: `test-migration` -- validates connectivity and compatibility without moving data
2. **Start migration**: `start-migration` -- begins data replication from source to ElastiCache
3. **Complete migration**: `complete-migration` -- finalizes and cuts over

```bash
aws elasticache test-migration \
  --replication-group-id <target> \
  --customer-node-endpoint-list Address=<source>,Port=6379 \
  --region <region>
```

**Online migration prerequisites (test-migration / start-migration / complete-migration):**

*Target requirements:*

- Target must NOT have encryption in-transit enabled (you can enable TLS after migration completes)
- Target must have Multi-AZ enabled with automatic failover
- Target must be using Valkey, or Redis OSS 5.0.6 or higher
- Target must NOT be part of a global datastore
- Target must have data tiering disabled
- Number of shards in source and target must match
- Number of logical databases must be the same on source and target

*Source requirements:*

- Source must NOT have AUTH enabled
- Source `protected-mode` must be set to `no`
- Data-modification commands must not be renamed (e.g., `sync`, `psync`, `info`, `config`, `command`, `cluster`)
- If source has a `bind` configuration, it must allow requests from ElastiCache nodes

### Redis OSS to Valkey (In-Place Engine Upgrade)

Zero-downtime upgrade when upgrading from Redis OSS 5.0.6+. Upgrading from Redis OSS versions earlier than 5.0.6 may experience 30-60 seconds of failover during DNS propagation. No data migration needed.

```bash
aws elasticache modify-replication-group \
  --replication-group-id <cluster-id> \
  --engine valkey \
  --engine-version 7.2 \
  --apply-immediately \
  --region <region>
```

Key facts:

- Valkey is designed as a drop-in replacement for Redis OSS 7. You can upgrade from Redis OSS 5.x, 6.x, or 7.x directly to Valkey
- No application code changes needed for default parameter groups. If you have a custom cache parameter group, you must pass a custom Valkey parameter group with the same static parameter values
- To upgrade a single-node Redis OSS (cluster mode disabled) cluster, you must first add it to a replication group before performing the cross-engine upgrade
- AWS CLI version requirements: AWS CLI v1 minimum 1.35.2, AWS CLI v2 minimum 2.18.2
- Approximate 20% cost savings on node-based pricing (see https://aws.amazon.com/elasticache/pricing/ for current pricing)
- Can then migrate to serverless for additional savings (see https://aws.amazon.com/elasticache/pricing/ for current pricing)
- **Rollback supported**: ElastiCache supports rolling back from Valkey 7.2 to Redis OSS 7.1. Any user group/user associated with the cache being rolled back must be configured with engine type `REDIS`

### Node-Based to Serverless

No in-place conversion. Requires creating a new serverless cache and migrating data.

Steps:

1. Create new Valkey serverless cache (use `setup` sub-skill)
2. Dual-write: application writes to both old and new cache
3. Warm up: let reads gradually shift to new cache
4. Cut over: point all reads to serverless
5. Stop writes to old cache
6. Delete old cluster: `delete-replication-group` (with optional final snapshot)

Alternative: snapshot-restore if brief downtime is acceptable. Note: ElastiCache Serverless snapshot restore has engine version requirements. Verify RDB version compatibility against the latest AWS docs before attempting a restore: https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/

**Auth changes**: Serverless requires RBAC (AUTH tokens not supported). Update application auth before cutover.

**TLS changes**: Serverless always has TLS enabled. Update client config to use `ssl=True` / `tls: {}`.

**Cluster mode changes**: Serverless operates in cluster mode enabled only. Clients must support cluster mode enabled to connect. If your application currently uses a cluster-mode-disabled client, you must update it before cutover.

### Serverless to Node-Based

Rare, but needed when workload outgrows serverless cost-efficiency or requires vector search (Valkey 8.2 or above, node-based only).

Steps:

1. Create new node-based replication group
2. Dual-write pattern (same as above)
3. Cut over and decommission serverless cache: `delete-serverless-cache`

## Pre-Migration Checklist

- [ ] Check source Redis version compatibility (Valkey supports Redis OSS 7.2 commands)
- [ ] Check for Redis module usage (RedisJSON, RediSearch, RedisTimeSeries) -- not all available in Valkey
- [ ] If migrating to serverless: auth must use RBAC (not AUTH tokens), TLS is mandatory
- [ ] Verify VPC/security group configuration for the target
- [ ] Plan for DNS/endpoint changes in application config
- [ ] Test connectivity from application to new cache endpoint (`valkey-cli -h <endpoint> -p 6379 --tls PING`)
- [ ] For online migration (test-migration/start-migration/complete-migration): Target must NOT have encryption in-transit enabled
- [ ] For online migration: Target must have Multi-AZ enabled with automatic failover
- [ ] Have rollback plan (keep old cache running until validated)
- [ ] Run `scripts/serverless_estimator.py` for node-based to serverless cost validation
- [ ] Run `scripts/price_calculator.py --mode serverless --data-gb <N> --ops-per-sec <N>` and `--mode node --node-type <type> --nodes <N> --show-ri-options` to validate cost expectations for greenfield sizing

## Freshness disclaimer

When your response includes pricing, version constraints, or feature availability, include the freshness disclaimer per SKILL.md Global Rule #5: "For current pricing see https://aws.amazon.com/elasticache/pricing/. For current feature availability see https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/."
