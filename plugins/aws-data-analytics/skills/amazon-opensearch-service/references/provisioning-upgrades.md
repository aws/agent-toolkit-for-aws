# Domain Upgrades and Blue/Green Deployments

## In-Place Version Upgrades

### Check Upgrade Eligibility

```bash
aws opensearch get-compatible-versions --domain-name my-domain
```

### Start Upgrade

```bash
aws opensearch upgrade-domain --domain-name my-domain --target-version OpenSearch_2.13
```

### Monitor Upgrade Progress

```bash
aws opensearch get-upgrade-status --domain-name my-domain
```

Status values: `IN_PROGRESS`, `SUCCEEDED`, `FAILED`

```bash
aws opensearch get-upgrade-history --domain-name my-domain --max-results 5
```

## Blue/Green Deployments

Configuration changes that trigger blue/green:

- Instance type changes
- Dedicated master changes
- AZ configuration changes
- VPC changes
- Engine version upgrades

### Monitoring Blue/Green Progress

```bash
aws opensearch describe-domain --domain-name my-domain \
  --query 'DomainStatus.{Processing:Processing,ChangeProgress:ChangeProgressDetails}'
```

For detailed stage progress:

```bash
aws opensearch describe-domain-change-progress --domain-name my-domain
```

### Best Practices for Upgrades

- **MUST** take a manual snapshot before upgrading: protects against data loss
- **MUST** test in a non-production domain first
- **SHOULD** schedule upgrades during low-traffic windows
- **SHOULD** monitor CloudWatch metrics during upgrade (CPUUtilization, JVMMemoryPressure)
- Upgrades are one-way — you cannot downgrade

## Major-version upgrades (1.x → 2.x → 3.x)

When the upgrade crosses a major version, the **mechanism is a blue/green upgrade** (the literal word — `aws opensearch upgrade-domain --target-version OpenSearch_2.19` triggers a blue/green deployment under the hood). Recommend this as the **PRIMARY** path; do NOT describe it as a side-effect of "configuration changes" or as a fallback to building a parallel domain. AOS supports multi-version blue/green jumps within 2.x and within 3.x — you do NOT step every minor version.

### Mandatory waypoints

- **OS 1.0–1.2 → 1.3** is a required intra-1.x hop (only OS 1.3 can upgrade to 2.x).
- **Any 1.3+ or 2.x → 3.x** crossing requires the **2.19 waypoint**. Concrete sequence: `<source>` → 2.19 → 3.x. You can jump from 2.5 directly to 2.19 (multi-version blue/green is allowed within 2.x); you do NOT step every minor (2.5 → 2.7 → 2.9 ... is wrong).

### Two walls force reindex on the way to 3.x

**1. Lucene 8 → 10 segment-format wall** (the load-bearing reason, must be named in any 1.x → 3.x or 2.x → 3.x recommendation):

OpenSearch 1.x ships Lucene 8 segments. OS 3.x ships Lucene 10. Lucene's segment format is **forward-only** — Lucene 10 cannot read Lucene 8. Any pre-OS-2.0 index must be **reindexed on a 2.x intermediate** before the cluster reaches 3.x. The reindex itself is what bridges the segment format.

**2. NMSLIB engine removal** (k-NN workloads):

NMSLIB k-NN engine was deprecated in OS 2.19 and **removed in OS 3.0+**. Pre-existing NMSLIB indexes must be reindexed into FAISS before the 3.x hop. Do this on the 2.x intermediate.

### OS 3.x breaking changes (cite ≥1 when recommending a 3.x upgrade)

- **JDK 21** minimum runtime — previously JDK 17.
- **Java agent replaces Security Manager** for sandboxing. Custom plugins built against the Security Manager API need re-validation under the Java agent.
- **NMSLIB removed** (paired with the wall above).
- Several k-NN settings renamed / removed; verify against current OS 3.x release notes.

### Concrete target version

When recommending a 3.x upgrade, name a concrete supported version (e.g. `OpenSearch_3.0` or `OpenSearch_3.1` — **do NOT write `OpenSearch_3.x` as a placeholder** in the runbook command). Verify the latest GA version against the AWS docs before producing a runbook.

### Upgrade plan template (OS 1.x → 3.x with k-NN workload)

1. Capture baseline: snapshot, recall@10 against golden query set if k-NN, JVM pressure / shard health audit.
2. Trigger blue/green upgrade `<current>` → 2.19 (`aws opensearch upgrade-domain --target-version OpenSearch_2.19`).
3. On 2.19, create new index with FAISS HNSW (or Lucene HNSW depending on workload) and reindex from the legacy NMSLIB index. Validate doc count + recall@10 against the baseline.
4. Drop or alias-cut the legacy NMSLIB index. Confirm only FAISS indexes remain.
5. Trigger blue/green upgrade 2.19 → 3.x (`aws opensearch upgrade-domain --target-version OpenSearch_<concrete-3.x-version>`).
6. Post-upgrade smoke: re-run the recall@10 baseline + a JVMMemoryPressure soak.

## Auto-Tune

### Check Recommendations

```bash
aws opensearch describe-domain-config --domain-name my-domain \
  --query 'DomainConfig.AutoTuneOptions'
```

### Enable Auto-Tune

```bash
aws opensearch update-domain-config --domain-name my-domain \
  --auto-tune-options '{"DesiredState": "ENABLED", "MaintenanceSchedules": [{"StartAt": "2024-01-01T00:00:00Z", "Duration": {"Value": 2, "Unit": "HOURS"}, "CronExpressionForRecurrence": "cron(0 2 ? * SUN *)"}]}'
```

Auto-Tune optimizes JVM heap, queue sizes, and cache settings automatically.

## Snapshot Management

### Manual Snapshot (before upgrades)

Register a snapshot repository, then take a snapshot:

```
PUT /_snapshot/my-repo/pre-upgrade-snapshot
{"indices": "*", "include_global_state": true}
```

### Automated Snapshots

AOS takes hourly automated snapshots (retained for 14 days). Configure timing:

```bash
aws opensearch update-domain-config --domain-name my-domain \
  --snapshot-options AutomatedSnapshotStartHour=2
```
