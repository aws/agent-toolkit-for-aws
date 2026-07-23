# Performance — baseline, comparison & Redshift sizing

> AI-facing knowledge: how to extract a representative Teradata workload, compare it
> against Redshift after migration, and size the target cluster from the source profile.
> The AI generates the extraction/replay runner; this doc is the knowledge.

## Purpose

1. Establish a Teradata **performance baseline** (workload + resource profile) →
   `output/performance/result/perf_baseline.json`.
2. **Compare** the same queries on Redshift after migration →
   `output/performance/result/perf_compare.json`.
3. Feed **Redshift sizing** from the source `inventory.json` (see Sizing below).

Inputs come from `references/teradata/discovery-queries.md` (`inventory.json`) plus the two
workload sources here. Both are **read-only**.

> **Source of truth:** the DBQL/ResUsage extraction queries in this doc ARE the source of
> truth. The skill ships no executable collector — the AI generates the runner at run time
> (BTEQ driver template in `references/teradata/discovery-queries.md` → Execution modes).

## Workload extraction (DBQL)

`DBC.DBQLogTbl` holds query history. It is **often disabled** — probe first
(`SELECT COUNT(*) FROM DBC.DBQLogTbl`); 0 rows → mark `query_log` unavailable and skip the
rich stats (the baseline still produces from AMPUsage + ResUsage).

```sql
-- Overall stats (one row; empty when logging off).
SELECT TRIM(CAST(COUNT(*) AS BIGINT)) || '|' ||
       TRIM(CAST(COUNT(DISTINCT UserName) AS INTEGER)) || '|' ||
       TRIM(CAST(CAST(AVG(AMPCPUTime) AS DECIMAL(18,4)) AS VARCHAR(40))) || '|' ||
       TRIM(CAST(CAST(MAX(AMPCPUTime) AS DECIMAL(18,4)) AS VARCHAR(40))) || '|' ||
       TRIM(CAST(SUM(TotalIOCount) AS BIGINT)) AS rec
FROM DBC.DBQLogTbl
HAVING COUNT(*) > 0;

-- Mix by StatementType (ETL vs BI → WLM queues).
SELECT TRIM(StatementType) || '|' || TRIM(CAST(COUNT(*) AS BIGINT)) AS rec
FROM DBC.DBQLogTbl GROUP BY StatementType ORDER BY COUNT(*) DESC;

-- Top query-issuing users.
SELECT TRIM(UserName) || '|' || TRIM(CAST(COUNT(*) AS BIGINT)) || '|' ||
       TRIM(CAST(CAST(SUM(AMPCPUTime) AS DECIMAL(18,4)) AS VARCHAR(40))) AS rec
FROM DBC.DBQLogTbl GROUP BY UserName ORDER BY COUNT(*) DESC;

-- Concurrency/peak proxy: query count by hour-of-day.
SELECT TRIM(CAST(EXTRACT(HOUR FROM StartTime) AS INTEGER)) || '|' ||
       TRIM(CAST(COUNT(*) AS BIGINT)) AS rec
FROM DBC.DBQLogTbl
GROUP BY EXTRACT(HOUR FROM StartTime)
ORDER BY EXTRACT(HOUR FROM StartTime);
```

`peak_hour` = the hour bucket with the max count; it sizes Concurrency Scaling / WLM slots.

## Resource extraction (ResUsage)

`DBC.ResUsageSpma` is the per-node system resource time series — node-level CPU/memory.
It is enabled at **node level** (`ctl`/`dbscontrol`), **not via SQL**.

> The shared test cluster now has `ResUsageSpma` logging **ON at a 60s interval**, so this
> query was validated against real samples (see the validated note below).

```sql
-- System resource summary (one row; empty when logging off).
--   cpu_busy% = (CPUUExec + CPUUServ) / (CPUUExec + CPUUServ + CPUIdle) * 100   [VALIDATED]
-- NOTE: ResUsageSpma.MemSize is NOT physical node RAM (see validated note below) — do not
-- derive total RAM from it. Source RAM for sizing comes from node spec / operator.
SELECT TRIM(CAST(COUNT(*) AS BIGINT)) || '|' ||
       TRIM(CAST(COUNT(DISTINCT NodeID) AS INTEGER)) || '|' ||
       TRIM(CAST(CAST(AVG((CPUUExec + CPUUServ) * 100.0
            / NULLIFZERO(CPUUExec + CPUUServ + CPUIdle)) AS DECIMAL(6,2)) AS VARCHAR(20))) || '|' ||
       TRIM(CAST(CAST(MAX((CPUUExec + CPUUServ) * 100.0
            / NULLIFZERO(CPUUExec + CPUUServ + CPUIdle)) AS DECIMAL(6,2)) AS VARCHAR(20))) AS rec
FROM DBC.ResUsageSpma
HAVING COUNT(*) > 0;
```

**Gotcha:** `EXTRACT(HOUR FROM ResUsageSpma.TheTimestamp)` fails (Failure 5326) — a
per-hour ResUsage breakdown needs a different time column/derivation than the DBQL
`StartTime` form above. Keep ResUsage to the summary until the time grain is validated.

> **Validated live (2026-06-24, 12,272 samples / 2 nodes):** the cpu-busy formula is
> correct; the dev cluster is near-idle (avg **0.05%**, max **2.13%**). `MemSize` is **not**
> physical RAM (~126,844 per sample — not bytes), so the RAM-from-MemSize derivation was
> dropped. Source RAM for memory-bound sizing must come from node spec / operator — see
> `references/teradata/sizing.md`.

## Baseline → compare

- **Representative-query selection** — take the top queries by frequency × cost from DBQL
  (`by_user` / statement mix), capture each query's TD runtime and `AMPCPUTime`/IO.
- **Replay** — run the *converted* queries (converted per `references/teradata/conversion-rules.md`) on
  Redshift; capture runtime/cost from `SVL_QUERY_REPORT` / `STL_QUERY`.
- **Compare** — per-query and aggregate deltas; flag regressions.

**Fairness notes:** control for warm vs cold cache (run twice, report warm), match
concurrency (the dev cluster has a **system concurrency limit of 2**), and document
WLM/queue settings on both sides. Compare like-for-like result sets.

### `perf_baseline.json` (Teradata)

```json
{
  "source": "teradata",
  "window": { "from": null, "to": null, "note": "DBQL retention window" },
  "query_stats": {
    "total_queries": 0, "distinct_users": 0,
    "avg_amp_cpu": 0.0, "max_amp_cpu": 0.0, "total_io": 0,
    "by_statement": [{ "statement_type": "Select", "count": 0 }],
    "by_hour": [{ "hour": 0, "count": 0 }],
    "top_users": [{ "user": "tester", "count": 0, "cpu": 0.0 }],
    "peak_hour": null, "peak_hour_count": 0
  },
  "resource_stats": {
    "sample_count": 0, "node_count": 2,
    "avg_cpu_busy_pct": null, "max_cpu_busy_pct": null
  },
  "representative_queries": [
    { "id": "q1", "sql": "...", "td_runtime_s": 0.0, "amp_cpu": 0.0, "io": 0 }
  ]
}
```

### `perf_compare.json` (Redshift vs Teradata)

```json
{
  "pairs": [
    { "id": "q1", "td_runtime_s": 0.0, "rs_runtime_s": 0.0, "delta_pct": 0.0, "status": "ok|regression" }
  ],
  "aggregate": { "queries": 0, "median_delta_pct": 0.0, "regressions": 0 },
  "notes": "warm-cache, concurrency-matched"
}
```

`query_stats` / `resource_stats` reuse the `inventory.json` workload shape
(`references/teradata/discovery-queries.md`) — populated only when DBQL / ResUsage are available.

## Redshift sizing

Sizing the Redshift target from this profile (RG node type + count, CPU- vs memory-bound
decision, concurrency/WLM) is covered in **`references/teradata/sizing.md`**. Performance feeds it
the workload signals: `resource_stats.avg_cpu_busy_pct` (bottleneck) and `query_stats`
(peak-hour concurrency + statement mix for WLM).

> Source endpoints come from `migration-config.yaml` — operator-provided, never hard-coded
> in the skill.
