# Redshift sizing (from the source profile)

> AI-facing knowledge: how to draft a Redshift target cluster from the source
> `inventory.json` (see `references/teradata/discovery-queries.md`) and workload signals (see
> `references/teradata/performance.md`). Facts in, a sizing recommendation out.

## Philosophy

Target **RG (Graviton) provisioned** nodes. **Node count is driven by parallelism or
memory — never by raw data volume.** Teradata `ResUsage` decides the bottleneck:

- **CPU-bound** (avg CPU busy ≥ threshold) → size by **parallelism**: source AMPs → target
  slices, `node_count = ceil(target_slices / slices_per_node)`.
- **memory-bound** (below threshold) → size by **RAM**: target aggregate RAM ≈ source RAM,
  `node_count = ceil(total_ram_gib / ram_per_node)`.
- **ResUsage unavailable** → fall back to **parallelism** (AMP count is always known) at
  lower confidence; flag that CPU- vs memory-bound was not verified.

Managed storage on RG is decoupled and large, so storage is **only a capacity check**,
never the node-count driver.

> Target is **RG (Graviton), not RA3.**

## RG node specs

> **Verify against the live API before sizing** — node specs and limits change as AWS updates
> the lineup. Treat the table below as a **fallback/example snapshot** (per the AWS *Amazon
> Redshift Management Guide* — "Clusters and nodes in Amazon Redshift → Node type details"),
> and confirm current values at runtime:
> `aws redshift describe-orderable-cluster-options --query 'OrderableClusterOptions[?starts_with(NodeType, \`rg.\`)].{NodeType:NodeType}' --output table`
> plus the Management Guide spec table for vCPU/RAM/slices/storage.

Resolve the full candidate list and per-node specs **at runtime** (API + Management Guide).
Illustration of the *shape* of one fetched record (example row, retrieved 2026-07; do not
reuse the values — fetch current ones):

| RG node (example) | vCPU | RAM | default slices/node | managed storage / node | node range (create) |
|---------|------|-----|---------------------|------------------------|---------------------|
| `rg.xlarge` (multi-node) | 4 | 32 GiB | 2 | 32 TB | 2–16 |

Minimum cluster = 2 nodes. "Default slices per node" is the create-time value (elastic
resize keeps the cluster's *total* slice count constant while changing node count). For
RA3→RG equivalences, consult the current AWS documentation/API rather than fixed mappings —
node lineups and equivalences change.

> **Node-count clamp bounds:** clamp to the **create-time node range** — not the
> elastic-resize maximums — since the skill provisions a new cluster. The Logic below consumes
> `max_nodes(node_type)` **fetched at runtime** from `aws redshift
> describe-orderable-cluster-options`; the table above is illustrative only and is never read
> by the Logic.
>
> Source: <https://docs.aws.amazon.com/redshift/latest/mgmt/working-with-clusters.html#rs-rg-nodes-table>

## Inputs (from `inventory.json`)

| Input | Field | Use |
|-------|-------|-----|
| Source AMPs | `system.amp_count` | parallelism → target slices |
| CPU busy % | `workload.resource_stats.avg_cpu_busy_pct` | bottleneck decision |
| Source RAM | node hardware spec / operator (**not** ResUsage — see note) | memory-bound path |
| Storage | `storage.total_current_perm_bytes` | capacity check only |
| Workload mix / peak | `workload.query_stats` (DBQL) | Concurrency Scaling + WLM |

## Logic

Resolve per-node specs **at runtime** before sizing — `slices(n)`, `ram_gib(n)`, `max_nodes(n)`
for each candidate node type — from `aws redshift describe-orderable-cluster-options` (node
types + node ranges) and the Management Guide spec table (slices/RAM). The logic below is
**symbolic**: it references only those fetched values, never literal numbers. Candidates are
ordered smallest→largest (e.g. `rg.xlarge` → `rg.4xlarge` → `rg.12xlarge`).

```
fetch candidates C = ordered list of RG node types with slices(c), ram_gib(c), max_nodes(c)

if resource_stats.avg_cpu_busy_pct is not null:
    if avg_cpu_busy_pct >= CPU_BOUND_PCT:        # cpu-bound
        target_slices = max(slices(C[0]) * 2, ceil(amp_count * SLICE_PER_AMP))
        node_type  = smallest c in C where target_slices <= slices(c) * max_nodes(c)
        node_count = clamp(ceil(target_slices / slices(node_type)), 2, max_nodes(node_type))
    else:                                         # memory-bound
        node_type  = smallest c in C where total_ram_gib <= ram_gib(c) * max_nodes(c)
        node_count = clamp(ceil(total_ram_gib / ram_gib(node_type)), 2, max_nodes(node_type))
else:                                             # ResUsage absent → fallback
    size by parallelism (as cpu-bound), confidence = low

# The Logic targets the smallest multi-node production type (rg.xlarge today) as the floor.
# rg.large has the same slice count but half the vCPU/RAM per slice — consider it for
# cost-sensitive workloads. Storage is only a capacity check; raise node_count if the
# fetched managed-storage-per-node capacity is exceeded.
```

## Recommendation shape

```json
{
  "node_type": "rg.xlarge",
  "node_count": 2,
  "sizing_basis": "parallelism: AMP->slices (cpu-bound per ResUsage)",
  "bottleneck": "cpu-bound|memory-bound|unknown",
  "basis_detail": { "source_amps": 24, "slice_per_amp": 1.0, "target_slices": 24, "slices_per_node": 2 },
  "storage_check": { "source_total_current_perm_bytes": 0, "cluster_managed_capacity_bytes": 0, "sufficient": true },
  "concurrency_notes": "peak-hour arrival → Concurrency Scaling / WLM slots",
  "wlm_notes": "statement mix → ETL vs BI queues",
  "assumptions": ["DRAFT: AMP->slice ratio and CPU-bound threshold are placeholders pending calibration."],
  "confidence": "low|medium|high"
}
```

Confidence is `high` only when both ResUsage and DBQL are present; `medium` with ResUsage
only; `low` on the parallelism fallback.

## Calibration placeholders (not yet validated)

- `slice_per_amp = 1.0` — Graviton slices are more powerful, so a 1:1 AMP:slice mapping is
  likely **conservative**. Calibrate against a real workload.
- `cpu_bound_pct = 60` — the avg-CPU-busy threshold separating CPU- vs memory-bound.

## ResUsage validation (live cluster, 2026-06-24)

Validated against `DBC.ResUsageSpma` (logging ON @60s; 12,272 samples, 2 nodes):

- ✅ **CPU-busy formula is correct**: `(CPUUExec + CPUUServ) / (CPUUExec + CPUUServ +
  CPUIdle) * 100`. The dev cluster is near-idle (avg 0.05%, max 2.13%) — plausible, so the
  cpu-bound path and the bottleneck decision are sound.
- ⚠️ **`ResUsageSpma.MemSize` is NOT physical node RAM** (observed ~126,844 per sample —
  not bytes, ≈124 MB-scale). The earlier `MemSize × nodes / 1 GiB` derivation yields ~0 and
  is **invalid**. **Source aggregate RAM must come from the node hardware spec or operator
  input (`migration-config`), not from ResUsage.** Until a reliable RAM source is wired in,
  the **parallelism (CPU-bound) path is the dependable one**; the memory-bound branch needs
  a RAM input before it can be trusted.

## Placement (resolved)

This sizing logic is deterministic, but per the team's **text-only** decision the skill ships
**no scripts** — it stays here as knowledge and the AI applies it at runtime (same as
conversion). No `scripts/` helper.

> Source endpoints come from `migration-config.yaml` — operator-provided, never hard-coded in the skill.
