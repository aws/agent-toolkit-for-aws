# Troubleshooting AOS Domains and Collections

## Common Issues

| Error | Cause | Fix |
|-------|-------|-----|
| `ValidationException` on create | Invalid config combination | Check instance type supports chosen EBS volume; verify AZ count matches instance count |
| Domain stuck in `Processing` | Blue/green in progress | Wait; check `describe-domain-change-progress` for stage details |
| `ResourceAlreadyExistsException` | Domain name taken in account | Choose a different name; domain names must be unique per account per region |
| Upgrade fails at pre-checks | Incompatible settings or plugins | Run `get-compatible-versions`; address breaking changes listed in upgrade guide |
| `DisabledOperationException` | Operation not available for config | Some operations (cold storage, UltraWarm) require specific instance families |
| Snapshot failure | S3 bucket permissions or IAM role | Verify snapshot role has `s3:PutObject` on the bucket; check trust policy |

## Debugging Domain Creation Failures

1. Check domain status: `aws opensearch describe-domain --domain-name <name>`
2. Look for `ServiceSoftwareOptions` — may indicate pending mandatory updates
3. Verify service-linked role exists: `aws iam get-role --role-name AWSServiceRoleForAmazonOpenSearchService`
4. If VPC: verify subnet has available IPs, security group allows port 443

## Debugging Blue/Green Stuck

1. `aws opensearch describe-domain-change-progress --domain-name <name>`
2. Check if cluster is red (blue/green won't complete with red cluster)
3. Verify sufficient capacity in the AZ for the new configuration
4. Common blocker: snapshot in progress — wait for it to complete

## Debugging Auto-Tune

1. Check state: `aws opensearch describe-domain-config --domain-name <name> --query 'DomainConfig.AutoTuneOptions'`
2. Auto-Tune requires: domain running OpenSearch 1.0+, instance types with >= 4 GiB RAM
3. Recommendations are applied during maintenance windows only

## High JVM pressure / RED cluster / unassigned shards

The canonical playbook for *"JVMMemoryPressure is at 9X%, cluster is RED, shards are unassigned"* on a provisioned domain.

### Math first — get the per-node shard count right

Be exact. Don't average across "what could fit" if some nodes are already capped:

```
shards_per_node_actual = total_shards ÷ live_data_nodes        (if shards balance perfectly)
shards_per_node_cap    = 1000 × (heap_GiB ÷ 16)                (OS ≥ 2.17 rule, capped at 4000)
                       = 25 × heap_GiB                           (legacy "safe target")
```

Worked example for the typical case (3 × `r7g.2xlarge.search` data nodes):

- Per `r7g.2xlarge.search`: 64 GiB RAM → 32 GiB JVM heap (50% rule, 32 GiB cap)
- Per-node shard cap (OS ≥ 2.17): `32 ÷ 16 × 1000 = 2000 shards/node` (hard ceiling)
- Per-node "safe" target: `25 × 32 = 800 shards/node`
- 4500 shards across 3 nodes = **1500 shards/node** (assuming even distribution) — under the 2000 hard cap, well over the 800 safe target. Heap pressure expected at this density.

When writing the assessment: do the division once, present the single number (`1500 shards/node`), then compare it against BOTH the hard cap and the safe target. Do NOT present `750 shards/node` somewhere and `1500 shards/node` later in the same response — the reader loses trust.

### The actual fix order (do these in this sequence)

**Step 1 — Stabilize the heap before changing topology.** Identify shards in flight (recovery, force-merge); throttle or pause them. Check field-data circuit breaker and clear unused field caches. Reduce indexing pressure (lower client-side bulk concurrency); rolling restart NOT advised at >85% pressure.

**Step 2 — Resolve unassigned shards (gets cluster out of RED).** Identify each unassigned shard's reason via `_cat/shards?h=index,shard,prirep,state,unassigned.reason`:

- **Replicas unassigned because of allocation rules** (most common): force allocation if a node has slots, OR temporarily reduce replica count for the affected non-critical indices to 0 — but ONLY for indices you can afford to lose if a node fails AND with an explicit "this is destructive availability tradeoff" callout. Re-raise replicas after consolidation.
- **Primaries unassigned**: do NOT touch replicas. The data itself is at risk. Add a node before doing anything else.

**Replica-drop is a LAST-RESORT availability tradeoff, not Step 1 of a runbook.** Always frame it as: *"This drops fault tolerance on these indices until we re-replicate. Acceptable only if data loss on a single-node failure is tolerable for the X-hour recovery window."* Without that framing the recommendation reads as casual destructiveness.

**Step 3 — Reduce shard overhead permanently** (the actual fix to the JVM-pressure root cause):

- Use `_shrink` to consolidate over-sharded write-once indices: target 30–50 GiB shard size, not the default 5-shard template that produced this problem.
- Use `_rollover` (or ISM-managed rollover) to retire write indices at a sane size threshold instead of letting them accumulate. New indices use the consolidated shard count.
- For time-series, set up an **ISM** policy: hot rollover at 50 GB or 1 day → warm at 7d → delete at 90d. ISM is the load-bearing operational fix; the runbook should name **`_rollover`**, **`_shrink`**, and **ISM** explicitly.
- Identify high-shard-count indices: `_cat/indices?v&s=pri:desc,index | head -30` — usually a handful of indices dominate.
- Close or delete unused indices to free shard slots immediately.

**Step 4 — Add capacity (only after Step 3 is in flight).** Scale 3 → 6 nodes via blue/green to redistribute shards and halve per-node density. Adding nodes before consolidating shards just delays the same problem.

### Disk watermark trio (cite alongside JVM pressure when relevant)

OpenSearch disk watermarks (defaults): **`cluster.routing.allocation.disk.watermark.low = 85%`** (no new shard allocations to this node), **`high = 90%`** (existing shards relocate off this node), **`flood_stage = 95%`** (index goes read-only — all writes blocked, recovery is a manual ack). High JVM and high disk often arrive together; both must be addressed.

### Pressure thresholds (what triggers the write-block)

- Write-block trigger: **JVMMemoryPressure > 92% for 30 consecutive minutes**.
- Write-block release: JVMMemoryPressure ≤ 88% for 5 minutes.
- At 91% with shard pressure, you are one spike away from the block. The runbook MUST cite the 92%/30-min threshold.
