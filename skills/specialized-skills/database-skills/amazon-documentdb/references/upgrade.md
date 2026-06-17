# DocumentDB — Major Version Upgrade

Orchestrate DocumentDB major version upgrades. Supports two paths:

- **4.0 → 5.0**
- **5.0 → 8.0**

Two approaches:

- **Option A: In-place MVU** — simpler, has downtime (multiple reboots). Best for dev/staging, small clusters, or when downtime is acceptable.
- **Option B: Near-zero downtime** — clone + MVU on clone + CDC + cutover. Source stays online. Best for production.

**Cannot skip versions** (3.6 must go 3.6→5.0→8.0). **Elastic Clusters:** MVU is not supported — no workaround. **Global Clusters:** direct in-place MVU is not supported. Workaround: remove the cluster from the Global Cluster first (this converts it to a standalone regional cluster), perform the upgrade using Option A or B below, then re-add it to the Global Cluster.

## What to ask upfront

- Source cluster id, region
- Current engine version (detect with `aws docdb describe-db-clusters --query 'DBClusters[0].EngineVersion'`)
- Target version (`5.0` or `8.0`)
- `app_name` (artifact naming)
- Tolerate downtime (Option A) or need near-zero downtime (Option B)

## Prerequisites (all paths)

**Mandatory on every `modify-db-cluster` MVU command:** `--allow-major-version-upgrade`. **When cluster uses a custom parameter group:** also `--db-cluster-parameter-group-name` pointing at a new PG for the target engine family (`docdb5.0`, `docdb8.0`).

**Pre-upgrade checks:**

- Manual snapshot created and available (use polling loop — `aws docdb wait` is not in all CLI versions)
- Pending OS maintenance applied
- No `db.r4` instances (not supported on 4.0+) — upgrade to `db.r5+` first
- Burstable instance index counts within limits: `db.t4g.medium` ≤ 3,000 indexes, `db.t3.medium` ≤ 10,000. If over, scale primary to `db.r5.large` before upgrading

## Option A: In-Place MVU

### Step 1: Create manual snapshot

```bash
aws docdb create-db-cluster-snapshot \
  --db-cluster-identifier <id> \
  --db-cluster-snapshot-identifier <id>-pre-mvu-$(date +%Y%m%d) \
  --region <region>
```

Poll until `Status=available`.

### Step 2: Create target parameter group (if custom PG in use)

```bash
aws docdb create-db-cluster-parameter-group \
  --db-cluster-parameter-group-name <id>-docdb<version>-pg \
  --db-parameter-group-family docdb<version> \
  --description "MVU target for <id>" --region <region>
```

### Step 3: Execute the upgrade

```bash
aws docdb modify-db-cluster \
  --db-cluster-identifier <id> \
  --engine-version <target-version> \
  --db-cluster-parameter-group-name <id>-docdb<version>-pg \
  --allow-major-version-upgrade --apply-immediately \
  --region <region>
```

Cluster unavailable during upgrade (multiple reboots). Time depends on collection / index / instance count.

### Step 4: Verify

```bash
# Engine version
aws docdb describe-db-clusters --db-cluster-identifier <id> \
  --query 'DBClusters[0].EngineVersion' --region <region>
# Confirm via mongosh: db.version() and db.runCommand({ping: 1})
```

For 5.0→8.0: wait for "Index metadata refresh process completed" event (up to 2 hours). Do NOT reboot, failover, or scale the writer during this time.

## Option B: Near-Zero Downtime (clone + MVU + CDC)

### Step 1: Enable change streams on the source

Custom parameter group required (defaults can't be modified). After switching to a custom PG, **reboot the instance** and confirm `DBClusterParameterGroupStatus=in-sync` before proceeding:

```
change_stream_log_retention_duration = 86400    # 24 hours
```

Enable change streams on all databases:

```javascript
db.adminCommand({ modifyChangeStreams: 1, database: "", collection: "", enable: true })
```

### Step 2: Clone the source cluster

```bash
aws docdb restore-db-cluster-to-point-in-time \
  --db-cluster-identifier <id>-clone \
  --source-db-cluster-identifier <id> \
  --use-latest-restorable-time \
  --region <region>
```

Record clone creation time (DMS CDC start = 2 min before, as Unix epoch). Add instances to the clone and wait for `available`.

### Step 3: Upgrade the clone in place

Apply Option A Steps 2–4 to the clone. Do NOT write to the clone after it's upgraded.

### Step 4: Set up CDC replication (DMS is the primary method)

Follow `references/migration.md` for DMS setup:

- SG allows inbound TCP 27017 on the DocumentDB SG from DMS instance SG
- DMS replication subnet group in the same VPC
- RDS CA cert imported into DMS
- Endpoints created with `--ssl-mode verify-full` and the cert ARN
- Both endpoint connection tests pass (`successful`)

Then create the replication task with `migration-type cdc` (data changes only — clone already has the data) and CDC start time = 2 minutes before clone creation:

```bash
aws dms create-replication-task \
  --replication-task-identifier <id>-mvu-cdc \
  --source-endpoint-arn <source-ep-arn> \
  --target-endpoint-arn <clone-ep-arn> \
  --replication-instance-arn <dms-instance-arn> \
  --migration-type cdc \
  --cdc-start-position "checkpoint:<2-min-before-clone-time-epoch>" \
  --table-mappings '{"rules":[{"rule-type":"selection","rule-id":"1","rule-name":"all","object-locator":{"schema-name":"%","table-name":"%"},"rule-action":"include"}]}' \
  --replication-task-settings '{"ErrorBehavior":{"FailOnNoTablesCaptured":false}}' \
  --region <region>
```

Start the task. Monitor `CDCLatencySource` — should decrease toward 0.

**Fallback:** `amazon-documentdb-tools/migration/mvu-tool/mvu-cdc-migrator.py`. Source URI MUST NOT include `readPreference=secondaryPreferred` (change streams are primary-only).

### Step 5: Pre-cutover checklist

- CDC lag near zero (`CDCLatencySource` < 60s)
- Counts match within 0.1% on 3+ largest collections
- All indexes exist on clone; critical queries tested
- For 5.0→8.0: Query Planner v3 active, Zstd on new collections, driver updated

### Step 6: Cutover (in order)

1. Put app in maintenance mode
2. Wait for CDC lag = 0
3. Final document count verification
4. Stop the DMS task; update app connection strings to the upgraded clone's endpoint
5. Update driver version if needed; start app; run smoke tests
6. Monitor CloudWatch for 15–30 minutes
7. Keep source running read-only for 24–48 hours as rollback — do NOT write to it

### Step 7: Rollback

**Before cutover:** delete the clone; source is untouched.

```bash
aws docdb delete-db-cluster --db-cluster-identifier <clone-id> --skip-final-snapshot
```

**After cutover, within 24–48 hours:** point app back at source (still has data up to cutover). Manual reconciliation needed for writes made to the clone after cutover.

**If source was already deleted:** restore from the pre-upgrade snapshot:

```bash
aws docdb restore-db-cluster-from-snapshot \
  --db-cluster-identifier <id>-restored \
  --snapshot-identifier <pre-upgrade-snapshot-id> --engine docdb
```

### Step 8: Post-cutover cleanup (after 24–48 hours)

- Delete old source cluster; disable change streams on upgraded cluster
- Delete DMS resources (instance, endpoints, task)
- Add read replicas to match production topology; copy alerts
- Update IaC; take a manual snapshot

## What changes by target version

**4.0 → 5.0:** Vector search, LZ4 compression (off by default), I/O-Optimized storage, partial indexes, text indexes v1. Recommended but optional: `db.collection.reIndex()` on low-cardinality indexes.

**5.0 → 8.0:** Query Planner v3 (7× faster aggregations), Zstd compression (on by default, 5× ratio), Text v2 parser, Collation (default-on), Views, new stages (`$merge`, `$bucket`, `$replaceWith`, `$vectorSearch`), 30× faster vector index builds. No index rebuild needed. Update driver to MongoDB 6.0+/7.0+/8.0 to use new features.
