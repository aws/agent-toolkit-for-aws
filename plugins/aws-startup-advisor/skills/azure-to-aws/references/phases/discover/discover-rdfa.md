---
_fragment: rdfa
_of_phase: discover
_contributes:
  - azure-resource-inventory.json (resources[].config.measured_utilization, rdfa_metadata section)
  - azure-resource-clusters.json (simplified clustering when rdfa is the sole source, merged with IaC/live otherwise)
---

# Discover — RDfA Report Parse

> **Fragment unit.** See `discover.md` for how it composes into the phase. RDfA needs no
> such split: reading an archive the customer already handed over is not interactive, so
> this fragment carries no Part A/Part B — it is file-only and non-interactive end to end,
> unlike `discover-live.md`'s main-window-consent + dispatched-parse split. It still owes
> the customer an informational block (not a consent gate) naming the tool and the roles
> it needs, output when no RDfA report is reachable this run (see § Step 0 and the
> informational block below) — the only decision point here is whether the customer goes
> and runs the tool at all, and that decision happens before this fragment ever has
> anything to read.

Produces the same two artifacts every other discover fragment writes —
`azure-resource-inventory.json` (`resources[].config.measured_utilization`, the
`rdfa_metadata` top-level section) and `azure-resource-clusters.json` — joined onto
whatever IaC/live entries already exist by `azure_id`, never creating a second entry for
a resource another source already described. `discover-assemble.md`'s existing
precedence rule applies without modification: RDfA loses to live `az` on state (an
archive can be days old), wins on measurement (live has no utilization rollup).

**Execute ALL steps in order. Do not skip or optimize.**

## Status — net-new (build step: Discover, RDfA path)

Fills the capability `discover.md`'s Status table reserves ("the `rdfa` fragment (RDfA
archive parse). Live `az` has landed (`discover-live.md`)") and that `SKILL.md`'s "Still
missing" line previously named. This fragment maps the 17 highest-value RDfA collectors
(VMs, scale sets, App Service + plans, flexible and non-flexible Postgres/MySQL/MariaDB,
SQL Database + SQL Server, Cosmos, Redis, Storage, ACR, AKS, container groups) per the §
Step 2 table; the remaining collectors derive-or-flag per § Step 2's unmapped-collector
rule rather than being dropped. Consumption-CSV parsing is explicitly deferred (§ Step 4)
— this fragment contributes `measured_utilization` from the Metrics report, never a
dollar figure.

## Step 0: Locate the report

Look for the first of, in order:

1. An already-extracted RDfA report directory under `$MIGRATION_DIR/rdfa-report/` — this
   fragment's own canonical extraction target, so a re-entry finds its own prior
   extraction here first and never re-extracts.
2. A `*.zip` matching `*ResourcesReport*.zip` anywhere directly under the workspace root
   (not recursively — RDfA's own delivery is flat), or a path the user explicitly named
   in conversation.
3. An already-extracted directory anywhere in the workspace containing at least one
   `Inventory_*.json` file (the one artifact every RDfA run produces even with
   `-SkipMetrics -SkipConsumption`) — covers "I unzipped it myself before telling you."

**On a ZIP match:** extract it to `$MIGRATION_DIR/rdfa-report/` using the standard
library's zip extraction, never a shell `unzip` call — this fragment is file-only, with
no `_exec` shell access implied. **On an already-extracted directory match (not under
`rdfa-report/`):** read it in place; do not copy or move it. The fragment is read-only
everywhere.

**No match of either shape:** this fragment's `_trigger` evaluates false and it
contributes nothing this run — same "absent is normal" contract `discover-live.md` uses
for a missing `live-capture/manifest.json`. Output the informational block below once per
Discover run, when no RDfA report is found AND the live-`az` main-window pre-work did not
produce a manifest either for this attempt.

### Multiple subscriptions

A tenant-wide `Run-AllSubscriptions.ps1` run bundles per-subscription ZIPs into one outer
ZIP whose own `Compress-Archive` step adds the per-subscription `.zip` FILES flat into the
outer archive — extracting the outer zip yields N sibling `.zip` files at the top level,
not N directories. Do a genuine two-pass extraction: extract the outer zip into
`$MIGRATION_DIR/rdfa-report/`, which yields one `.zip` file per subscription sitting
directly in that directory; then extract each of those inner zips in turn, into its own
subdirectory named after the inner zip's filename stem (so each subscription's
`Inventory_*.json`/`Metrics_*.json`/`Consumption_*.csv` triple does not collide on name
with another subscription's). Process every `Inventory_*.json`/`Metrics_*.json`/
`Consumption_*.csv` triple found across all subscription subfolders, keyed by their own
`Subscription`/`ID` fields — never assume a single-subscription layout.

### Corrupt or unreadable reports

A report that exists but cannot actually be read is a real, documented failure mode for
this tool (RDfA's own `docs/consumption-data.md` has a "Recovering from a consumption
crash" section for exactly this reason). Wrap the extraction step and every
`Inventory_*.json`/`Metrics_*.json` parse in a try/except. On any of:

- (a) a corrupt or password-protected ZIP that extraction raises on,
- (b) a file that extracts/exists but fails to parse as JSON (a truncated run), or
- (c) a ZIP that matched `*ResourcesReport*.zip` by name but, once extracted, contains
  none of `Inventory_*.json`/`Metrics_*.json`/`Consumption_*.csv`,

do **not** silently treat the run as "no RDfA report found" (that would discard the
informational block's context, which specifically distinguishes "nothing to read" from
"something was there but broken") and do **not** halt the whole Discover phase over one
bad file. Instead: record one `warnings[]` entry with code `rdfa_report_unreadable`
(`schema-discover-azure.md` § Warnings), naming the file (`identifier`, since a corrupt
report has no reliable `azure_id` to attach to) and the failure in `detail` (e.g. "RDfA
report `AllSubscriptions_ResourcesReport_2024-03-01.zip` could not be read: zip extraction
failed (corrupt or password-protected archive). RDfA-sourced resources and measured
utilization are unavailable this run."); skip that one file/report only (if the outer
multi-subscription case hits this on one inner zip, continue processing the other inner
zips normally — the failure is per-file, not per-run); and fall back to the informational
block for every other purpose, exactly as if no RDfA report had been found at all (the
warning is additive context, not a replacement for that fallback).

### Tie-break when multiple ZIPs match

A customer who ran RDfA twice will have two matching files side by side. Relying on
directory-listing order is non-deterministic across OSes, and a raw lexicographic
comparison of the `<timestamp>` filename substrings is unsafe across RDfA's two real
timestamp formats (`Run-AllSubscriptions.ps1`'s outer-bundle stamp,
`yyyy-MM-dd_HH-mm-ss`, hyphen-separated; `ResourceInventory.ps1`'s single-subscription
stamp, `yyyyMMddHHmmssfff` plus a 4-hex-character discriminator, no separators) — ASCII
`-` sorts below every digit, so a 2025 tenant-wide file can sort lexicographically
*before* a 2024 single-subscription file, backwards from actual chronology.

**Rule: normalize before comparing, never compare the raw filename substrings.** For each
matching filename, extract the `<timestamp>` substring, strip every non-digit character
from it (removing the hyphens from the `yyyy-MM-dd_HH-mm-ss` form and the trailing hex
discriminator from the `yyyyMMddHHmmssfff<hex>` form), and compare the resulting plain
digit runs as strings. Both formats reduce to a leading `yyyyMMddHHmmssfff...` digit
sequence once separators are gone, and a leading-digit run of that shape sorts correctly
against another one of the same shape. Pick the file whose normalized digit run sorts
lexicographically latest. This stays a plain string comparison (not a filesystem mtime or
glob-order read), so it is deterministic regardless of OS or extraction order. Record
every OTHER match (not just the count) in `rdfa_metadata.other_reports_found[]` (see §
Output Files) as the matched filename plus its parsed (normalized) timestamp, so a stale
second report is not silently invisible to the customer.

## Step 1: Scale guard and extraction

RDfA's `Metrics_ResourcesReport_<date>.json` is a flat array with one row **per
(resource, metric) pair**, not one row per resource — as few as 2 metric rows per VM up
to ~9 for a vCore-serverless SQL Database, all multiplied by however many resources
exist. This is structurally bigger than `discover-live.md`'s `az resource list` dump (one
row per resource, no per-metric fan-out).

**Write a throwaway extraction script, `$MIGRATION_DIR/_extract_rdfa.py` (mirroring
`discover-live.md`'s `_extract_live.py` naming), any time `Metrics_ResourcesReport_*.json`
exists at all** — not gated at the ~100-resource threshold `discover-live.md`'s own
Security Contract states for its raw captures, because RDfA's metric fan-out multiplies
resource count by metric-row count, so even a modest resource count can produce a large
file. The script:

1. Streams the Metrics JSON (a flat array — safe to parse incrementally).
2. Projects ONLY the fields Step 3 needs per row: **`ID`, `Service`, `Metric`,
   `MetricPercentile`, `MetricCount`, `MetricError`, `StartTime`, `EndTime`**. Explicitly
   drops `MetricSeries`, `MetricAggregate`, `MetricTimeGrain` (aggregation method and
   sampling interval — never the window length), `MetricMeasure`, `MetricValue`,
   `MetricTotalCount`, `Subscription`, `ResourceGroup`, `Name`, `Location` — fields the
   inventory-mapping step (§ Step 2) gets from the Inventory JSON entry it is attaching
   `measured_utilization` to, not from Metrics rows a second time.
3. Writes its projected output to `$MIGRATION_DIR/rdfa-report/metrics-extracted.json`.
4. Is deleted after it runs.

The same rule applies to `Inventory_ResourcesReport_*.json` whenever it exceeds the live
path's own ~100-resource threshold (same number — an Inventory JSON row has the same flat
per-resource shape live `az`'s own capture does). This fragment's mapping steps read ONLY
the extracted files (or the raw files directly when they were small enough that no
extraction ran) — never a raw `Metrics_*.json`/`Inventory_*.json` file whose size crossed
the threshold.

The Consumption CSV is out of this fragment's parsing path entirely (§ Step 4), so it
needs no scale-guard treatment here — the deferral itself is the mitigation.

## Step 2: Map Inventory rows to inventory entries

The Inventory JSON's **top-level key** that each per-resource array sits under is the
collector module's own name (its `.ps1` filename's base name), not a human-readable
`Service` string — `VirtualMachines`, `PostgreSQLflexible`, `AppServices`, etc. None of
the per-service `Obj` hashtables these collectors write carries a `Type`/`ResourceType`
key; the ARM type was already consumed as the collector's own filter and discarded before
emission. Map the module key to a canonical ARM type via this table:

| RDfA Inventory JSON key (collector module name) | Canonical ARM type                                                                         | Shape note                                                                                                                                      |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `VirtualMachines`                                 | `Microsoft.Compute/virtualMachines`                                                        | one row per VM, one `azure_id` per row                                                                                                          |
| `VMSS`                                             | `Microsoft.Compute/virtualMachineScaleSets`                                                | one row per scale set                                                                                                                           |
| `AppServices`                                      | `Microsoft.Web/sites`                                                                      | kind-qualify per `arm-type-canonicalization.md`'s trap row — the Inventory row's `AppType`/`KIND` field is the discriminator, same as live `az` |
| `AppServicePlan`                                   | `Microsoft.Web/serverfarms`                                                                | one row per plan                                                                                                                                 |
| `PostgreSQLflexible`                               | `Microsoft.DBforPostgreSQL/flexibleServers`                                                | one row per server                                                                                                                               |
| `MySQLflexible`                                    | `Microsoft.DBforMySQL/flexibleServers`                                                     | one row per server                                                                                                                               |
| `MariaDB`                                          | `Microsoft.DBforMariaDB/servers`                                                            | one row per server                                                                                                                               |
| `MySQL`                                            | `Microsoft.DBforMySQL/servers`                                                              | one row per server                                                                                                                               |
| `POSTGRE`                                          | `Microsoft.DBforPostgreSQL/servers`                                                         | one row per server                                                                                                                               |
| `SQLDB`                                            | `Microsoft.Sql/servers/databases`                                                           | one row per database                                                                                                                             |
| `SQLSERVER`                                        | `Microsoft.Sql/servers`                                                                     | one row per server                                                                                                                               |
| `CosmosDB`                                         | `Microsoft.DocumentDB/databaseAccounts`                                                     | one row per account                                                                                                                              |
| `RedisCache`                                       | **`Microsoft.Cache/Redis` OR `Microsoft.Cache/redisEnterprise` — see discriminator below** | **no `Type` field; needs `Family` discriminator**                                                                                               |
| `StorageAcc`                                       | `Microsoft.Storage/storageAccounts`                                                        | one row per account                                                                                                                              |
| `REGISTRIES`                                       | `Microsoft.ContainerRegistry/registries`                                                   | one row per registry                                                                                                                             |
| `AKS`                                              | `Microsoft.ContainerService/managedClusters`                                               | **MULTIPLE rows per cluster, one per node pool, same `ID`**                                                                                     |
| `CONTAINER`                                        | `Microsoft.ContainerInstance/containerGroups`                                               | **MULTIPLE rows per container group, one per container, same `ID`**                                                                             |

### RedisCache discriminator

`RedisCache.ps1` collects both `microsoft.cache/redis` and `microsoft.cache/redisenterprise`
resources under the single module key `RedisCache`, with no `Type` field on either
branch's `$Obj`. The only distinguishing signal is `Family`, and it is overloaded: on the
non-enterprise branch `Family` holds the SKU family letter (`C`/`P`-prefixed, e.g.
`C1`/`P1`); on the enterprise branch it is always the literal string `"enterprise"`.
**Rule: if `Family == "enterprise"` (case-sensitive, exact match), stamp
`Microsoft.Cache/redisEnterprise`; for every other `Family` value, stamp
`Microsoft.Cache/Redis`.** This is a safe discriminator because the two branches' value
spaces for `Family` never overlap.

### AKS and CONTAINER grouping

`AKS.ps1` emits one row per node pool, every pool's row sharing the cluster's own `ID`.
`CONTAINER.ps1` emits one row per container the same way, every container's row sharing
the container group's `ID`. Both would collide on `azure_id` if mapped naively, violating
`discover-assemble.md`'s "one entry per `azure_id`; never two." Fold per-pool/per-container
detail into an array field on ONE inventory entry per `ID` instead of synthesizing a
sub-resource `azure_id` RDfA never observed (RDfA's rows carry no independent node-pool-
or container-level identity — `ID` is always the parent's id):

- **AKS:** group all rows sharing one `ID` into a SINGLE inventory entry
  (`azure_type: Microsoft.ContainerService/managedClusters`). Take cluster-level fields
  (`Sku`, `SkuTier`, `KubernetesVersion`, `LoadBalancerSku`) from the first row — they are
  identical across every row for that `ID`. Collect the per-pool fields into
  **`config.node_pools[]`** (lowercase, snake_case — matching the rename
  `discover-live.md`'s own row-4 table now makes for its captured `nodePools` array, so
  both sources produce the same shape for the same cluster and `discover-assemble.md`'s
  drift comparison can actually compare them), one array element per source row:
  `{ name: NodePoolName, mode: PoolMode, os_type: PoolOS, vm_size: NodeSize, node_count:
  Nodes, min_count: AutoscaleMin, max_count: AutoscaleMax, max_pods_per_node:
  MaxPodsPerNode }`.
- **CONTAINER:** group all rows sharing one `ID` into a SINGLE inventory entry
  (`azure_type: Microsoft.ContainerInstance/containerGroups`). Take group-level fields
  (`Sku`, `InstanceOSType`) from the first row. Collect per-container fields into
  `config.containers[]`: `{ name: ContainerName, image: ContainerImage, state:
  ContainerState, request_cpu: RequestCPU, request_memory_gb: RequestMemoryGB,
  restart_count: RestartCount }`.
- `measured_utilization` (§ Step 3) attaches to the ONE grouped entry by its shared `ID`
  — AKS/CONTAINER do not appear in the Metrics report's metric-definition list at all, so
  this is moot in practice for these two types, but the grouping rule is what keeps the
  "one entry per `azure_id`" invariant true regardless.

### Per-type `config` field renames

Rename the Inventory JSON's raw field names to the canonical `config` keys
`extract-terraform.md`'s § "Per-type attributes" table defines for that `azure_type`, the
same way `discover-live.md`'s own Step 3 rename table does for its capture rows — a
non-canonical key reads as absent to every downstream reader and breaks a drift
comparison against an IaC-sourced duplicate of the same resource:

- `VirtualMachines.ps1`'s `Size` → **`size`** (lowercase — `extract-terraform.md` line 264
  states the canonical `Microsoft.Compute/virtualMachines` key is lowercase `size`; a
  passthrough as `Size` would leave an RDfA-sourced VM on a different JSON key than a
  Terraform-sourced one, breaking drift-matching, right-sizing lookups, and any
  merge-by-field logic).
- `HybridBenefit` → license-info parity with live `az`'s row-5 `Lic` handling.
- `OSDisk`/`OSDiskSizeGB` → `os_disk`/`os_disk_size_gb`.
- `PowerState` → `power_state`.
- `Zones` → `zone_count`.

`azure_type_provenance` is `"table"` when the module key matched the table above,
`"derived_uncorroborated"` otherwise (see below). `source` is `"rdfa"` on every entry.

### Unmapped collectors: derive-or-flag, never guess

A collector module present in the Inventory JSON but absent from the table above (57
collectors exist upstream; this fragment maps 17 on first cut) follows the same
derive-or-warn path `discover-live.md` already uses for an unrecognized live `az` type:
do not drop the resource — stamp `azure_type_provenance: "derived_uncorroborated"` and
record the module name in `rdfa_metadata.unmapped_collectors[]` (an RDfA-local field, not
`warnings[]`, mirroring `live_metadata.derived_types`'s separation). `measured_utilization`
still attaches to a `derived_uncorroborated` entry when the Metrics JSON has rows for its
`ID` — the join (§ Step 3) is by `ID`, not by `azure_type`, so an unmapped-collector
resource with a real metrics row loses nothing by being type-unmapped.

**`azure_type` is never actually absent, because the `ID` field's own ARM path segments
supply it for every unmapped collector.** Every single-row-per-resource RDfA collector's
`Obj` hashtable carries an `ID` field holding the resource's full ARM resource id
(`/subscriptions/<sub>/resourceGroups/<rg>/providers/<rp>/<type>/<name>`, sometimes with
an extra `/<subtype>/<subname>` suffix for a child resource), even when that same
collector's `Obj` carries no `Type`/`ResourceType` field at all.

**Derivation rule: split the ARM id on `/`. The segment immediately after the literal
segment `providers` is the provider namespace (e.g. `Microsoft.Sql`). Every segment after
that alternates `type`, `name`, `type`, `name`, ... in order. `azure_type` is the provider
namespace joined with EVERY `type` segment, in order, skipping every alternating `name`
segment — never the parent type alone.** For
`.../providers/Microsoft.Sql/managedInstances/<mi>/databases/<db>` the type segments are
`managedInstances` then `databases`, so `azure_type = Microsoft.Sql/managedInstances/databases`
— the database's own type, not the parent managed instance's
`Microsoft.Sql/managedInstances`. For
`.../providers/Microsoft.Sql/servers/<server>/elasticPools/<pool>` the type segments are
`servers` then `elasticPools`, so `azure_type = Microsoft.Sql/servers/elasticPools` —
again the pool's own type, not the parent server's. For the flat, single-type-segment
case — `.../providers/Microsoft.RedHatOpenShift/openShiftClusters/<name>` — there is only
one `type` segment (`openShiftClusters`) after the provider, so the rule yields
`Microsoft.RedHatOpenShift/openShiftClusters`.

This requires no guessing and no module-name casing heuristic — it is the same ARM type
the collector itself already filtered on before discarding it, recovered from the `ID`
string's own structure. Record this derivation as part of the same
`azure_type_provenance: "derived_uncorroborated"` stamp (no new provenance value is
needed — deriving the type from the `ID` path is exactly what `derived_uncorroborated`
already means per `schema-discover-azure.md`), and continue recording the collector's
module name in `rdfa_metadata.unmapped_collectors[]` as before, now alongside the derived
`azure_type` string.

## Step 3: Attach `measured_utilization`

RDfA's `Metrics_ResourcesReport_<date>.json` is a flat array of (resource, metric) rows.
Join onto the Step 2 inventory entries by `ID` (exact match — safe even on an obfuscated
report, because `Extension/Metrics.ps1`'s obfuscation block looks up the same primary
dictionary for both Inventory and Metrics rows, unlike Consumption's separate token
cache — see § Step 4). For AKS/CONTAINER's grouped entries, the join is unaffected since
those two types never appear in the Metrics report's metric definitions at all —
`measured_utilization` is simply absent there, the correct "no evidence" outcome.

**`MetricPercentile` is the field that becomes `p95`, never `MetricValue`.**
`MetricPercentile` is a genuine P95 across the per-metric lookback window's sampled
series; `MetricValue` is a rolled-up value using whichever aggregation
(`Average`/`Maximum`/`Largest`/`Sum`/`Minimum`) that particular metric definition
requests, answering a different question per metric. Mixing the two would silently
change what "P95 utilization" means across resource types.

**`MetricError: true` means the call failed, not that the value is 0.** On a caught
exception RDfA sets `MetricQueryResults = 0`, `MetricQueryResultsCount = 0`,
`MetricPercentile = 0`, **and** `MetricError = true` in the same `catch` branch — so a
genuine zero-usage resource and a failed Monitor call are bit-for-bit identical in every
numeric field and are distinguished **only** by `MetricError`. Check `MetricError` before
trusting any numeric field on that row; a value of `0` with `MetricError: false` is a
real, trustworthy zero.

Write, per qualifying `resources[]` entry, `config.measured_utilization`:

```jsonc
"config": {
  // ...existing per-type config fields...
  "measured_utilization": {
    "cpu_percent": {
      "p95": 42.3,                     // MetricPercentile, as-is
      "sample_count": 720,              // MetricCount — the non-null sample size the P95 was computed over
      "window_days": 31,                // ceil((EndTime - StartTime).TotalDays) for THIS row
      "metric_error": false,            // MetricError, verbatim — REQUIRED, caller must check before trusting p95
      "source_metric": "Percentage CPU" // RDfA's own metric name, kept for traceability/debugging — not re-derived
    },
    "memory_available_bytes": {
      "p95": 1073741824,
      "sample_count": 720,
      "window_days": 31,
      "metric_error": false,
      "source_metric": "Available Memory Bytes"
    }
  }
}
```

- One entry per canonical metric name actually captured for that resource — never a
  placeholder for a metric RDfA did not define for that service.
- `metric_error: true` rows are **still written** (not dropped) — a reader needs to know
  the call was attempted and failed, not merely that no row exists. Design/Estimate
  consumers MUST treat a `metric_error: true` entry as **absent** evidence for the
  `measured` tier (fall back to `inferred`), never as a measurement of zero.
- `sample_count` comes from `MetricCount` (the count AFTER null-filtering, i.e. how many
  real samples the P95 was actually computed from), never `MetricTotalCount` (the raw page
  size before filtering, which would overstate confidence on a resource with gaps).
- **`window_days` is per-row**, computed as `ceil((EndTime - StartTime).TotalDays)` from
  that row's own `StartTime`/`EndTime` — never assumed from `rdfa_metadata.lookback_days`
  (the report-wide default setting, kept there purely for display/traceability). The
  default RDfA lookback is 31 days, but several SQL Database metrics (`cpu_limit`,
  `dtu_limit`, `app_cpu_billed`, `allocated_data_storage`, `storage`, `storage_percent`)
  and every CosmosDB and ContainerRegistry metric use a fixed 1-day window instead — a
  mixed 31-day/1-day population genuinely occurs within one report, and
  `rightsizing-thresholds.json`'s `confidence_rules.min_window_days` (14) gates `measured`
  vs `inferred` on this per-row length: a SQL Database's `storage_percent` row (1-day
  window) fails the 14-day gate and downgrades to `inferred` even when the same
  resource's `cpu_used` row (31-day window) passes.
- `MetricSeries` is **never** parsed into this structure or written anywhere in the
  artifact.

### The canonical-metric-name mapping table

RDfA's `Metric` field spelling is per-service. Map `(Service, Metric)` to one canonical
signal name before writing `measured_utilization`:

| RDfA `Service`                                                      | RDfA `Metric`                         | Canonical signal name                                                                                   | `StartTime` window |
| ------------------------------------------------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------| ------------------- |
| Virtual Machines                                                     | `Percentage CPU`                       | `cpu_percent`                                                                                             | 31-day (default)    |
| Virtual Machines                                                     | `Available Memory Bytes`               | `memory_available_bytes`                                                                                   | 31-day (default)    |
| Virtual Machines Scale Sets                                          | `Percentage CPU`                       | `cpu_percent`                                                                                              | 31-day (default)    |
| Virtual Machines Scale Sets                                          | `Available Memory Bytes`               | `memory_available_bytes`                                                                                   | 31-day (default)    |
| Managed Disk                                                         | `Composite Disk Read Operations/sec`   | `disk_read_iops`                                                                                            | 31-day (default)    |
| Managed Disk                                                         | `Composite Disk Write Operations/sec`  | `disk_write_iops`                                                                                           | 31-day (default)    |
| Managed Disk                                                         | `Composite Disk Read Bytes/sec`        | `disk_read_bytes_per_sec`                                                                                   | 31-day (default)    |
| Managed Disk                                                         | `Composite Disk Write Bytes/sec`       | `disk_write_bytes_per_sec`                                                                                  | 31-day (default)    |
| SQL Database                                                         | `cpu_percent`                           | `cpu_percent`                                                                                               | 31-day (default)    |
| SQL Database                                                         | `cpu_used`                              | `cpu_vcore_used`                                                                                            | 31-day (default)    |
| SQL Database                                                         | `cpu_limit`                             | `cpu_vcore_limit`                                                                                           | **1-day (fixed)**   |
| SQL Database                                                         | `dtu_used`                              | `dtu_used`                                                                                                   | 31-day (default)    |
| SQL Database                                                         | `dtu_limit`                             | `dtu_limit`                                                                                                  | **1-day (fixed)**   |
| SQL Database                                                         | `storage`                               | `storage_bytes`                                                                                              | **1-day (fixed)**   |
| SQL Database                                                         | `storage_percent`                       | `storage_percent`                                                                                            | **1-day (fixed)**   |
| SQL Database                                                         | `allocated_data_storage`                | `allocated_storage_bytes`                                                                                   | **1-day (fixed)**   |
| SQL Database                                                         | `physical_data_read_percent`            | `physical_data_read_percent` (passthrough)                                                                  | 31-day (default)    |
| SQL Database                                                         | `log_write_percent`                     | `log_write_percent` (passthrough)                                                                            | 31-day (default)    |
| SQL Database (serverless only)                                       | `app_cpu_billed`                        | `cpu_billed_seconds` (not a utilization %, carried for completeness; never fed to the P95 rubric bands)      | **1-day (fixed)**   |
| Functions                                                            | `FunctionExecutionCount`                | `invocation_count`                                                                                            | 31-day (default)    |
| Functions                                                            | `FunctionExecutionUnits`                | `invocation_gb_seconds`                                                                                       | 31-day (default)    |
| MariaDB / MySQL / MySQL Flexible / PostgreSQL / PostgreSQL Flexible   | `cpu_percent`                           | `cpu_percent`                                                                                                 | 31-day (default)    |
| MariaDB / MySQL / MySQL Flexible / PostgreSQL / PostgreSQL Flexible   | `memory_percent`                        | `memory_percent`                                                                                               | 31-day (default)    |
| MariaDB / MySQL / MySQL Flexible / PostgreSQL / PostgreSQL Flexible   | `storage_percent`                       | `storage_percent`                                                                                              | **1-day (fixed)**   |
| CosmosDB                                                             | `TotalRequests`                         | `request_count`                                                                                                | **1-day (fixed)**   |
| CosmosDB                                                             | `TotalRequestUnits`                     | `request_units_consumed`                                                                                       | **1-day (fixed)**   |
| CosmosDB                                                             | `DataUsage`                             | `data_usage_bytes`                                                                                             | **1-day (fixed)**   |
| CosmosDB                                                             | `ProvisionedThroughput`                 | `provisioned_throughput_ru`                                                                                     | **1-day (fixed)**   |
| ContainerRegistry                                                    | `StorageUsed`                           | `storage_used_bytes`                                                                                           | **1-day (fixed)**   |

The "`StartTime` window" column is informational — this fragment never hardcodes these
values; `window_days` always comes from the row's own `StartTime`/`EndTime`, so this
table does not need updating if a future RDfA release changes any of these.

The **only** canonical names the `measured` rubric bands in `rightsizing-thresholds.json`
currently consume are `cpu_percent` and `memory_percent`/`memory_available_bytes`. Every
other row above is written to `measured_utilization` for completeness and for a future
rubric to consume, but this fragment does not change `compute.md`'s or any other
rubric's decision logic to read them. This table is a closed, append-only list scoped to
the services RDfA's `Metrics.ps1` defines today — a service RDfA adds later needs a new
row here before its metrics can be trusted, matching
`arm-type-canonicalization.md`'s own closed-list philosophy.

## Step 4: Consumption CSV — deferred

This fragment does **not** implement consumption-CSV parsing. Two independent reasons:

1. **No join path to the inventory, by RDfA's own design.** On an obfuscated report (the
   only shape RDfA's own docs expect to be shared externally), `Consumption_*.csv`'s
   `ResourceId` is tokenized through a **separate, per-run cache** from the
   Inventory/Metrics obfuscation dictionary. Only the ARM path *structure*
   (`/subscriptions/<tok>/resourcegroups/<tok>/providers/<rp>/<type>/<tok>`) survives,
   which can categorize a row by resource TYPE but can never attach a quantity to one
   specific `azure_id` the way `measured_utilization` does.
2. **No dollar signal exists in the source at all.** RDfA's `Get-UsageAggregates` call
   returns usage quantity (`Quantity` + `Unit`), never billed cost — there is no price or
   spend column. So even a successful parse could only ever produce a usage-quantity
   confidence signal, never a baseline dollar figure.

Metrics obfuscation is unaffected by this deferral — it looks up the SAME primary
dictionary first for every metric row's `ID`, falling back to per-run caches only when an
id is absent from the primary dictionary, so Step 3's `ID` join stays exact-match-safe on
an obfuscated report regardless of this deferral.

Record the deferral explicitly in `rdfa_metadata` rather than silently never looking for
the CSV:

```jsonc
"consumption_csv": {
  "found": true,
  "parsed": false,
  "reason": "Deferred: RDfA consumption uses a separate obfuscation token cache from inventory/metrics, so an obfuscated report's consumption rows cannot be ID-joined to the inventory this fragment writes; only ARM path structure survives. Even unobfuscated, the CSV carries usage quantities, never dollar cost (Get-UsageAggregates has no price column). See discover-rdfa.md § Consumption CSV (deferred)."
}
```

(`found: false` when no `Consumption_*.csv` is present at all, e.g. the customer ran
`-SkipConsumption`; `parsed` is always `false` on this build regardless of `found`.)

## Step 5: Merge with IaC/live discovery

This step is deliberately thin — the actual precedence and drift-recording mechanics
already live in `discover-assemble.md`'s Assembly rule 4 (RDfA loses to live `az` on
state, wins on measurement, loses to neither on IaC's provenance claims). This fragment
only needs to emit entries with `source: "rdfa"` and let the assembler apply the existing
precedence; it performs no merge logic of its own.

## Step 6: Write output

Write `rdfa_metadata` to `azure-resource-inventory.json`'s top level, parallel to
`live_metadata`:

```jsonc
"rdfa_metadata": {
  "found": true,
  "report_path": "<path to the ZIP or extracted directory the fragment read>",
  "obfuscated": true,                 // detected by scanning for prod_/nonprod_ token shapes in ID fields
  "lookback_days": 31,                 // the report's own MetricsLookbackDays SETTING (display/traceability only — NEVER used to populate a measured_utilization row's window_days, which is always computed from that row's own StartTime/EndTime)
  "subscriptions": ["<name or token>"],
  "collectors_found": ["VirtualMachines", "PostgreSQLflexible", "AppServices"],
  "unmapped_collectors": [],           // module keys present but not in the § Step 2 table, each entry carrying its derived azure_type alongside the module name
  "other_reports_found": [],           // other *ResourcesReport*.zip matches NOT selected by the § Step 0 tie-break, e.g. [{"filename": "AllSubscriptions_ResourcesReport_20240115.zip", "timestamp": "20240115"}]; [] when only one match (or none) existed
  "consumption_csv": {
    "found": false,
    "parsed": false,
    "reason": "Deferred: ..."          // verbatim per § Step 4 when found is true; omitted detail when found is false
  },
  "metrics_found": true
}
```

`drift` is NOT duplicated here — § Step 5's merge feeds into `discover-assemble.md`'s
existing `resources[].drift` / run-level `live_metadata.drift`-shaped rollup; this
fragment does not introduce a second drift rollup field.

## Resource Discovery for Azure (RDfA) — optional accuracy upgrade

Output this block once per Discover run when no RDfA report is found AND the live-`az`
main-window pre-work did not produce a manifest either for this attempt (mirroring the
"offered when there is no Terraform IaC... or as an accuracy upgrade alongside IaC"
framing `discover-live.md` already uses for its own offer). This is prose output by the
main window, never a `[A]/[B]` choice this fragment blocks on — blocking would stall the
whole phase on a tool that takes real wall-clock time to run outside this conversation
entirely. There is nothing to consent to here, unlike the live-`az` consent gate: RDfA is
a separate PowerShell tool the customer downloads and runs against their own Azure
credentials, producing a ZIP they hand to this skill; the only decision point is whether
the customer wants to go run the tool at all, and that happens before this fragment ever
has anything to read.

```
─── Resource Discovery for Azure (RDfA) — optional accuracy upgrade ───

I can get a much more accurate picture of your actual Azure usage — real
CPU/memory utilization (not just declared SKU size) and reserved-vs-pay-as-you-go
status — if you run Resource Discovery for Azure (RDfA; the tool's own README
calls itself "RDA"), AWS's own open-source inventory tool, and hand me the
resulting report.

This is a SEPARATE tool you run yourself; I cannot run it for you (it needs its
own Azure PowerShell session on your machine). It is a ONE-TIME, single-sitting
run: it reaches back over the 31 days of utilization history Azure Monitor
already retains, it does not wait 31 days or run continuously.

  1. Clone https://github.com/awslabs/resource-discovery-for-azure
  2. Ensure your Azure account has: Reader, Billing Reader, Monitoring Reader,
     and Cost Management Reader roles
  3. Run ./Run-AllSubscriptions.ps1 (or ./ResourceInventory.ps1 for one
     subscription) — add -Obfuscate first if you want to mask resource names/IDs
     before sharing the report with anyone, including me
  4. Point me at the resulting *ResourcesReport*.zip (or its extracted folder)

This is entirely optional — I can continue with Terraform / live `az` discovery
alone, with inferred (not measured) sizing.
```

The roles named are the exact four RDfA's own `README.md` § "Required Azure Roles"
lists: Reader, Billing Reader, Monitoring Reader, Cost Management Reader. `-Obfuscate` is
the customer's own choice, not something this fragment requests or depends on — the
fragment parses an obfuscated report exactly as it parses an unobfuscated one (§ Step 3's
join is unaffected; § Step 4 explicitly accounts for the obfuscated-consumption
limitation). "ONE-TIME... reaches back over the already-retained trailing 31-day
history, NOT a 31-day wait" is stated explicitly because a reader skimming "31 days"
could otherwise assume this blocks the whole migration for a month.
