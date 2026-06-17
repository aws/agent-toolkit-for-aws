# DocumentDB — Well-Architected Review

Automated 41-check assessment across 6 pillars. Runs the bundled `scripts/wa_review.py`, reads the JSON results, and presents prioritized remediation commands.

## What to ask upfront

- `cluster_id` — the cluster name the user mentions in conversation (e.g., "my cluster xyz", "cluster docdb-prod") — this is the `--db-cluster-identifier` value, not a separate ID. Extract it directly from what the user said.
- `region` — AWS region the user mentioned (e.g., `us-east-1`)
- Optional: database connection string (enables 11 additional database-level checks)

If both are present in the user's message, use them and proceed directly to Step 1 without asking.

## Prerequisites

- AWS credentials with read access to: DocumentDB, CloudWatch, EC2, Secrets Manager
- Python 3.6+

## Workflow

### Step 1: Run the review

```bash
python3 scripts/wa_review.py \
  --cluster-id <cluster-id> \
  --region <region> \
  --output artifacts/<cluster-id>/ \
  [--uri "mongodb://admin:<pw>@<endpoint>:27017/?tls=true&tlsCAFile=global-bundle.pem&replicaSet=rs0&retryWrites=false"] \
  [--tls-ca-file global-bundle.pem]
```

If connection via URI fails, retry without `--uri` — infrastructure-only checks still run.

### Step 2: Read the results

Read `artifacts/<cluster-id>/wa_review_results.json`. Categorize findings:

- **FAIL** — must fix before production. Blockers: no deletion protection, TLS disabled, single AZ, swap usage, MVCC exhaustion risk
- **WARN** — should fix. Low backup retention, no audit logging, oversized instances, unused indexes, idle readers
- **PASS** — no action needed
- **INFO** — informational

### Step 3: Present recommendations with remediation commands

Organize findings by priority. For each FAIL and WARN, give the specific command:

**Enable deletion protection:**

```bash
aws docdb modify-db-cluster \
  --db-cluster-identifier <cluster-id> \
  --deletion-protection --region <region>
```

**Add a reader replica for HA:**

```bash
aws docdb create-db-instance \
  --db-instance-identifier <cluster-id>-reader \
  --db-instance-class <same-class-as-writer> --engine docdb \
  --db-cluster-identifier <cluster-id> --region <region>
```

**Increase backup retention:**

```bash
aws docdb modify-db-cluster \
  --db-cluster-identifier <cluster-id> \
  --backup-retention-period 7 --region <region>
```

**Enable audit logging:**

```bash
aws docdb modify-db-cluster-parameter-group \
  --db-cluster-parameter-group-name <pg> \
  --parameters "ParameterName=audit_logs,ParameterValue=enabled,ApplyMethod=immediate"
```

For each finding include:

1. What was checked and the result
2. Why it matters (one sentence)
3. The specific command to execute

## Checks reference (41 total)

### Reliability (8)
REL1 backup retention ≥ 7 days · REL2 deletion protection enabled · REL5a instances ≥ 2 · REL5b instances across ≥ 2 AZs · REL6 engine version currency · REL7 no failover events in last 13 days · REL8 no cursor timeouts · REL9 `AvailableMVCCIds` > 50%

### Security (6)
SEC1a encryption at rest · SEC1b TLS enabled · SEC2 SG not open to `0.0.0.0/0` · SEC3 credentials in Secrets Manager · SEC5 audit logging · SEC6 TLS ≥ 1.2

### Operational Excellence (5)
OPS2 subnet group spans ≥ 3 AZs · OPS5a profiler logging · OPS5b ≥ 3 CloudWatch alarms · OPS5c custom parameter group · OPS7 maintenance window review

### Cost Optimization (6)
COST1 CPU P95 per instance (< 10% = oversized) · COST3 unused indexes · COST4 TTL indexes present · COST6 ≥ 2 cost allocation tags · COST7 storage type (Standard vs I/O-Optimized) · COST9 idle reader detection

### Performance Efficiency (14)
PERF1 avg doc size < 8 KB · PERF1b no redundant (prefix) indexes · PERF1c no low-cardinality indexes · PERF5 connections < 70% of instance limit · PERF6 `BufferCacheHitRatio` ≥ 99% · PERF8 index-to-data ratio < 50% · PERF9 storage bloat < 30% · PERF10 no over-indexed collections (> 10 indexes) · PERF11 `FreeableMemory` > 10% of instance RAM · PERF12 no swap usage · PERF13 `DiskQueueDepth` < 5 · PERF14 `IndexBufferCacheHitRatio` ≥ 99% · PERF15 large collections have secondary indexes · PERF16 index size < 2× data size per collection

### Sustainability (2)
SUST1 Graviton instance family (`r6g`/`r8g`/`t4g`) · SUST2 compression enabled on all collections

## Common remediation patterns

**Upgrade to Graviton family (SUST1, COST1):** Scale each instance to a `db.r8g.*` or `db.r6g.*` class via `modify-db-instance --db-instance-class`. Requires engine 5.0+ for R8G.

**Enable Zstd compression (SUST2, COST7):** Available in 8.0, enabled by default on new collections. For existing collections, modify compression settings per collection.

**Remove unused indexes (COST3):**

```javascript
// Find indexes with zero usage
db.collection.aggregate([{ $indexStats: {} }])
db.collection.dropIndex("index_name")
```

**Fix redundant indexes (PERF1b):** If both `{a: 1}` and `{a: 1, b: 1}` exist, drop the single-field — the compound covers both access patterns.

**Enable I/O-Optimized (COST7):** When monthly I/O cost exceeds the I/O-Optimized storage + compute premium (~25% breakeven). Switch via `modify-db-cluster --storage-type iopt1`.

**Size a new workload or compare DocumentDB vs MongoDB costs:** Use the [DocumentDB Cost Estimator](https://builder.aws.com/content/3DLjpHB3gKnntEPemXnHlFTCEgX/amazon-documentdb-cost-estimator-size-your-workload-in-minutes-part-1) — it accepts MongoDB ops/sec, storage, and I/O patterns as inputs and produces a DocumentDB cost comparison in minutes. Surface this whenever the user asks about cost estimation or workload sizing.

## Output format

Present findings as a table grouped by pillar, with FAILs surfaced first. For each finding: check id, status, one-sentence rationale, remediation command. Then write a summary header to the user with the total FAIL / WARN / PASS counts and the top three remediation priorities.
