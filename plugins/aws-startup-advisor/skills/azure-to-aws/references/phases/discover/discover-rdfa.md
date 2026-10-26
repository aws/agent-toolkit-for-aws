---
_fragment: rdfa
_of_phase: discover
_contributes:
  - azure-resource-inventory.json (resources[].config.measured_utilization, rdfa_metadata section)
  - azure-resource-clusters.json (simplified clustering when rdfa is the sole source, merged with IaC/live otherwise)
---

# Discover — RDfA Report Parse

> **Fragment unit.** See `discover.md` for composition and for the executable
> main-window preparation stage. This dispatched fragment is file-only: it reads
> `$MIGRATION_DIR/rdfa-cache/manifest.json` and prepared JSON, maps rows, and contributes
> artifacts. It never discovers/extracts ZIPs, creates/runs scripts, or prompts. Report
> detection and no-report guidance must run before dispatch, because this fragment is not
> loaded when its trigger is false.

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

## Step 0: Read the prepared source manifest

Source discovery, tie-breaking, fingerprinting, ZIP extraction, nested ZIP extraction,
JSON validation, and metrics projection have already run in `discover.md`'s executable
main-window pre-dispatch action. Read `$MIGRATION_DIR/rdfa-cache/manifest.json` and only
the prepared paths it names.

The manifest records `source_path`, `source_type` (`zip` or `directory`), SHA-256
`fingerprint`, `prepared_at`, and prepared inventory/metrics paths. `source_path` always
names the customer-supplied ZIP or external extracted directory; it never names
`rdfa-cache` or a generated projection. On re-entry, reuse derived files only when all
three identity fields exactly match the currently selected source. A newly confirmed
source wins, invalidates the old cache, and is prepared before this fragment dispatches.

A missing manifest means this fragment's trigger is false. The optional-accuracy block
at the end of this file is output by the main window during detection, not from this
unreachable fragment.

### Multiple subscriptions

The main-window preparation genuinely performs two-pass extraction for an outer
Run-AllSubscriptions ZIP and each sibling inner ZIP. Prepared paths retain subscription
separation and all Inventory/Metrics batches are processed; filenames never overwrite
one another.

### Corrupt or unreadable reports

`discover.md`'s executable main-window action owns corrupt ZIP, invalid JSON, empty-report,
and partial nested-archive handling. It writes
`$MIGRATION_DIR/rdfa-cache/preparation-result.json` before a success manifest can exist,
so assembly can retain every `rdfa_report_unreadable` warning even when this fragment does
not dispatch. This file-only fragment must not retry extraction or redefine that failure
result.

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

## Step 1: Read producer-compatible prepared data

The main-window preparer reads every `Metrics_*.json` as the object RDfA actually emits:
`{"Metrics": [...]}`. Concatenate each batch's `Metrics` array; an empty array is valid
and contributes no evidence. Reject a top-level flat array rather than silently blessing
the old synthetic fixture shape.

Prepared metric rows retain only `ID`, `Service`, `Metric`, `MetricPercentile`,
`MetricCount`, and `MetricError`. Current RDfA exports do not serialize query bounds, so
they cannot prove a measured window. `MetricSeries`, aggregate/value fields, and inventory
duplicates are omitted. Large inventory files are likewise projected in the executable
pre-dispatch stage. This `rw` fragment reads only prepared files and never writes or runs
`_extract_rdfa.py`.

Every emitted metric carries `window_days: null` and provenance explaining that the
producer omitted query bounds. `rdfa_metadata.lookback_days` remains display-only and
must never be substituted for a row's unavailable window.

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
  Nodes, min_count, max_count, max_pods_per_node: MaxPodsPerNode }`. Normalize bounds using
  the `Autoscale` field and bounds together: when `Autoscale != "true"`, or when
  `node_count > 0` and RDfA emitted the impossible autoscaled shape `AutoscaleMin: "0"` /
  `AutoscaleMax: "0"`, treat those zero bounds as the producer's absent-bounds sentinel and
  emit `min_count == max_count == node_count`. Otherwise preserve the autoscaled pool's
  actual bounds, including a legitimate minimum zero (for example min `0`, desired `1`,
  max `2`). **Zero-node pools:** Azure permits a user pool with `Nodes: "0"`, which the
  rule above would normalize to `0 / 0 / 0`; EKS rejects that because `maxSize` has a
  minimum of `1` (the EKS Capacity contract), so floor `max_count` to `1` while keeping
  `node_count` and `min_count` at their real `0`. The downstream EKS contract must always
  satisfy `min_count <= node_count <= max_count` **and** `max_count >= 1`.
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
- `OSDisk` → `os_disk.storage_account_type` and `OSDiskSizeGB` →
  `os_disk.disk_size_gb`. Omit `os_disk.caching`: RDfA does not collect it. Treat
  `OSDisk` values `Custom VHD` and `None` as unknown/non-SKU rather than a storage tier.
  This nested shape is the canonical inline root-volume contract consumed by
  `disk-ebs-sizing.json`.
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

RDfA metrics arrive from Step 1 as the concatenation of each producer object's `Metrics`
array. Join rows onto Step 2 inventory entries by `ID` (exact match — safe even on an obfuscated
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

**A metric is sizing evidence only when `MetricError == false` AND `MetricCount > 0`.**
RDfA emits zero percentile/count both for exceptions and for successful responses with no
usable samples; the error flag alone cannot distinguish an empty success. Keep every row
for traceability, but treat error rows and zero-sample rows as absent sizing evidence. A
genuine sampled zero (`MetricPercentile == 0`, `MetricCount > 0`, no error) remains valid.

Write, per qualifying `resources[]` entry, `config.measured_utilization`:

```jsonc
"config": {
  // ...existing per-type config fields...
  "measured_utilization": {
    "cpu_percent": {
      "p95": 42.3,                     // MetricPercentile, as-is
      "sample_count": 720,              // MetricCount — the non-null sample size the P95 was computed over
      "window_days": null,              // current RDfA export omits query bounds
      "window_provenance": "unavailable_rdfa_query_bounds",
      "metric_error": false,            // MetricError, verbatim — REQUIRED, caller must check before trusting p95
      "source_metric": "Percentage CPU" // RDfA's own metric name, kept for traceability/debugging — not re-derived
    },
    "memory_available_bytes": {
      "p95": 1073741824,
      "sample_count": 720,
      "window_days": null,
      "window_provenance": "unavailable_rdfa_query_bounds",
      "metric_error": false,
      "source_metric": "Available Memory Bytes"
    }
  }
}
```

- One entry per canonical metric name actually captured for that resource — never a
  placeholder for a metric RDfA did not define for that service.
- Rows with `metric_error: true` or `sample_count <= 0` are still written for
  traceability but are absent evidence for sizing. Only a non-error, positive-sample row
  may enter the utilization rubric; `p95: 0` remains valid when samples are positive.
- `sample_count` comes from `MetricCount` after null filtering, never
  `MetricTotalCount`.
- **`window_days` is `null` for current RDfA exports**, with
  `window_provenance: "unavailable_rdfa_query_bounds"`. Unknown fails
  `confidence_rules.min_window_days`; consumers fall back to `inferred` and explain that
  query bounds were not serialized. Never infer a 31-day measured window from
  `rdfa_metadata.lookback_days`, which is display-only.
- `MetricSeries` is **never** parsed into this structure or written anywhere in the
  artifact.

### The canonical-metric-name mapping table

RDfA's `Metric` field spelling is per-service. Map `(Service, Metric)` to one canonical
signal name before writing `measured_utilization`:

| RDfA `Service`                                                      | RDfA `Metric`                         | Canonical signal name                                                                                   | Serialized window |
| ------------------------------------------------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------| ------------------- |
| Virtual Machines                                                     | `Percentage CPU`                       | `cpu_percent`                                                                                             | unavailable    |
| Virtual Machines                                                     | `Available Memory Bytes`               | `memory_available_bytes`                                                                                   | unavailable    |
| Virtual Machines Scale Sets                                          | `Percentage CPU`                       | `cpu_percent`                                                                                              | unavailable    |
| Virtual Machines Scale Sets                                          | `Available Memory Bytes`               | `memory_available_bytes`                                                                                   | unavailable    |
| Managed Disk                                                         | `Composite Disk Read Operations/sec`   | `disk_read_iops`                                                                                            | unavailable    |
| Managed Disk                                                         | `Composite Disk Write Operations/sec`  | `disk_write_iops`                                                                                           | unavailable    |
| Managed Disk                                                         | `Composite Disk Read Bytes/sec`        | `disk_read_bytes_per_sec`                                                                                   | unavailable    |
| Managed Disk                                                         | `Composite Disk Write Bytes/sec`       | `disk_write_bytes_per_sec`                                                                                  | unavailable    |
| SQL Database                                                         | `cpu_percent`                           | `cpu_percent`                                                                                               | unavailable    |
| SQL Database                                                         | `cpu_used`                              | `cpu_vcore_used`                                                                                            | unavailable    |
| SQL Database                                                         | `cpu_limit`                             | `cpu_vcore_limit`                                                                                           | unavailable   |
| SQL Database                                                         | `dtu_used`                              | `dtu_used`                                                                                                   | unavailable    |
| SQL Database                                                         | `dtu_limit`                             | `dtu_limit`                                                                                                  | unavailable   |
| SQL Database                                                         | `storage`                               | `storage_bytes`                                                                                              | unavailable   |
| SQL Database                                                         | `storage_percent`                       | `storage_percent`                                                                                            | unavailable   |
| SQL Database                                                         | `allocated_data_storage`                | `allocated_storage_bytes`                                                                                   | unavailable   |
| SQL Database                                                         | `physical_data_read_percent`            | `physical_data_read_percent` (passthrough)                                                                  | unavailable    |
| SQL Database                                                         | `log_write_percent`                     | `log_write_percent` (passthrough)                                                                            | unavailable    |
| SQL Database (serverless only)                                       | `app_cpu_billed`                        | `cpu_billed_seconds` (not a utilization %, carried for completeness; never fed to the P95 rubric bands)      | unavailable   |
| Functions                                                            | `FunctionExecutionCount`                | `invocation_count`                                                                                            | unavailable    |
| Functions                                                            | `FunctionExecutionUnits`                | `invocation_gb_seconds`                                                                                       | unavailable    |
| MariaDB / MySQL / MySQL Flexible / PostgreSQL / PostgreSQL Flexible   | `cpu_percent`                           | `cpu_percent`                                                                                                 | unavailable    |
| MariaDB / MySQL / MySQL Flexible / PostgreSQL / PostgreSQL Flexible   | `memory_percent`                        | `memory_percent`                                                                                               | unavailable    |
| MariaDB / MySQL / MySQL Flexible / PostgreSQL / PostgreSQL Flexible   | `storage_percent`                       | `storage_percent`                                                                                              | unavailable   |
| CosmosDB                                                             | `TotalRequests`                         | `request_count`                                                                                                | unavailable   |
| CosmosDB                                                             | `TotalRequestUnits`                     | `request_units_consumed`                                                                                       | unavailable   |
| CosmosDB                                                             | `DataUsage`                             | `data_usage_bytes`                                                                                             | unavailable   |
| CosmosDB                                                             | `ProvisionedThroughput`                 | `provisioned_throughput_ru`                                                                                     | unavailable   |
| ContainerRegistry                                                    | `StorageUsed`                           | `storage_used_bytes`                                                                                           | unavailable   |

The `Serialized window` column is intentionally `unavailable`: current RDfA metric rows
contain no query bounds. The tool may use different internal lookbacks, but this artifact
cannot claim which window produced a row, so every row remains ineligible for measured
confidence until a future producer serializes that evidence.

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

## Step 5: Merge with IaC/live discovery and contribute AI provenance

Emit inventory entries with `source: "rdfa"`; the assembler applies live > RDfA > IaC
state precedence while RDfA measurement remains additive.

For every RDfA Cognitive Services account/deployment or Machine Learning workspace,
also contribute an `ai-workload-profile.json` infrastructure entry
`{azure_id, type, source: "rdfa", config{}}`, with no Terraform `address`/`file` and a
`detection_signals[]` row whose method is `rdfa_report`. Include deployment model data
when RDfA actually captured it; never invent a model for a workspace. The assembler
reconciles exact `azure_id` matches across IaC/live/RDfA and ORs source flags. This makes
a report-only ML workspace satisfy the producer agreement without pretending the report
was a live `az` observation.

## Step 6: Write output

Write `rdfa_metadata` to `azure-resource-inventory.json`'s top level, parallel to
`live_metadata`:

```jsonc
"rdfa_metadata": {
  "found": true,
  "report_path": "<manifest.source_path: the selected customer ZIP or external directory>",
  "source_type": "zip",               // zip | directory
  "source_fingerprint": "<SHA-256 from the preparation manifest>",
  "obfuscated": true,                 // detected by scanning for prod_/nonprod_ token shapes in ID fields
  "lookback_days": 31,                // display-only report setting; current metric rows carry window_days: null
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
