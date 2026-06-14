# Aurora PostgreSQL — Query Load Analysis & Explain Plan Review

## Purpose

Identify the top queries generating load, run EXPLAIN on them, and flag plan patterns that behave differently after a major version upgrade (e.g., PG 14→15, 15→16, 16→17).

## Step 1: Get Top 5 Queries by Load

### Using pg_stat_statements (must be enabled)

```sql
SELECT queryid, query, calls, total_exec_time::numeric(12,2) AS total_time_ms,
  mean_exec_time::numeric(12,2) AS avg_time_ms,
  rows, shared_blks_hit, shared_blks_read
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC LIMIT 5;
```

### Fallback: pg_stat_activity snapshot (running queries)

```sql
SELECT pid, now() - query_start AS duration, state, query
FROM pg_stat_activity
WHERE state = 'active' AND query NOT LIKE '%pg_stat_activity%'
ORDER BY duration DESC LIMIT 5;
```

## Step 2: Run EXPLAIN on Each Query

For each Step 1 query, run:

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <query>;
```

For data-modifying queries (INSERT/UPDATE/DELETE), wrap in a rollback:

```sql
BEGIN;
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <query>;
ROLLBACK;
```

For parameterized queries ($1, $2...), substitute representative values or use:

```sql
EXPLAIN (FORMAT JSON) <query with literal values>;
```

## Step 3: Flag Upgrade-Impacting Patterns

Analyze each EXPLAIN output for these patterns, by target version:

### 🔴 Critical — Behavior Changes That Impact Performance

| Pattern in EXPLAIN | Versions Affected | Why It Matters | Action |
|---|---|---|---|
| `Sort Method: external merge` (disk sort) | PG 15+ | PG 15 replaced polyphase merge sort with a balanced k-way merge and improved on-disk sorts exceeding `work_mem`; large sorts may spill differently. Per-operation hash memory accounting via `hash_mem_multiplier` arrived in PG 13; PG 15 only raised its default from 1.0 to 2.0, so hash-heavy plans get ~2x `work_mem` after a 14→15 upgrade. | Tune `work_mem` and `hash_mem_multiplier`. Test on snapshot cluster. |
| `HashAggregate` with `Batches > 1` (spilling) | PG 15+ | Hash aggregation disk spill improved but changed; memory accounting differs. | Monitor `temp_blks_written`. Tune `work_mem` or `hash_mem_multiplier`. |
| Nested Loop with high `actual rows` on inner | PG 14+ | PG 14 introduced `enable_memoize`; optimizer may add Memoize nodes changing plan shape. | Usually beneficial. If regression, set `enable_memoize=off` per query. |
| `JIT` compilation on short queries | PG 12+ (any upgrade) | JIT (LLVM expression/tuple compilation) arrived in PG 11, enabled by default since PG 12. On short/OLTP queries the planner can still trigger JIT when estimated cost exceeds `jit_above_cost`, adding compilation latency. Not PG14-specific — verify JIT thresholds on any upgrade from PG 12 onward. | Adjust `jit_above_cost`, `jit_inline_above_cost`, `jit_optimize_above_cost` or disable JIT for OLTP. |

### 🟡 Warning — Optimizer Behavior Differences

| Pattern in EXPLAIN | Versions Affected | Why It Matters | Action |
|---|---|---|---|
| `Parallel Seq Scan` or `Parallel Hash Join` | PG 14→15→16 | Parallel thresholds and costing refined each version; plans may gain or lose parallelism. | Compare `max_parallel_workers_per_gather`. Test on snapshot. |
| `Index Scan` vs `Bitmap Index Scan` choice | All major upgrades | Cost model updates may flip index scan strategy. | Compare via EXPLAIN on test cluster. Usually fine. |
| `Incremental Sort` | PG 13+ | When upgrading from PG 12 or earlier, incremental sort may change plans for ORDER BY with partial indexes. | Usually beneficial. Monitor. |
| `Merge Join` on large tables | PG 16+ | PG 16 improved merge join costing; may choose merge join where hash join ran before. | Benchmark on test cluster. |
| Large `Rows Removed by Filter` (bad estimates) | All versions | A major upgrade does NOT carry over optimizer statistics (`pg_upgrade` does not transfer `pg_statistic`), so the planner has none until you run `ANALYZE`. Skipping this can cause severe plan regressions and slow queries. | Run `ANALYZE` on all tables post-upgrade. |
| `SubPlan` (correlated scalar subquery) | Aurora PG 16.8+ (NOT core PG16) | Aurora can transform a single-aggregate correlated subquery in SELECT/WHERE into an outer join, and/or add a Memoize subquery cache. Aurora-specific, from Aurora PostgreSQL 16.8 (Babelfish 4.2.0), controlled by `apg_enable_correlated_scalar_transform` (default OFF) and `apg_enable_subquery_cache` (default OFF). Opt-in; do NOT activate automatically on a PG15→16 upgrade. | Optional: test on a snapshot, then set ON in the parameter group if beneficial. Validate per AWS-documented limitations (aggregate-only, plain equality correlation, no GROUP BY/HAVING). See [Aurora correlated subquery optimization](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/apg-correlated-subquery.html). |

### 🟢 Clean — No Upgrade Impact

| Pattern | Notes |
|---|---|
| Simple `Index Scan` / `Index Only Scan` | Stable across versions. |
| `Seq Scan` on small tables | No behavioral change. |
| `CTE Scan` (non-recursive) | PG 12+ inlines CTEs by default. |
| `Append` for partitioned tables | Partition pruning stable since PG 11. |

## Step 4: Generate Recommendations

For each flagged query, provide:

1. The query (truncated to first 200 chars if long)
2. Current stats (calls, avg time, rows, shared buffers)
3. The problematic EXPLAIN pattern found
4. The version change causing the behavioral difference
5. Specific action: parameter to tune, index to add, or test on snapshot cluster

## Key PostgreSQL Optimizer Changes by Version

### PG 14

- Memoize node for nested loops
- Improved extended statistics
- Better handling for many-connection workloads

### PG 15

- Improved sort (balanced k-way merge replaces polyphase merge; leaner in-memory sorts)
- `hash_mem_multiplier` default raised 1.0 → 2.0
- `MERGE` command (SQL-standard merge)
- `pg_stat_statements` tracks JIT stats

### PG 16

- Improved parallelism for `FULL` and `RIGHT` joins
- Better merge join costing
- `pg_stat_io` view for I/O statistics
- Logical replication improvements

### PG 17

- Incremental backup support
- Improved vacuum performance
- Better memory management for large operations
- Enhanced JSON functionality
- Improved planner for complex joins

## Important Notes

- Always run `ANALYZE` on all tables after a major version upgrade (a major upgrade does not transfer the `pg_statistic` table, so tables start with no statistics; skipping this can cause severe plan regressions and slow queries)
- Consider `REINDEX` on critical indexes after upgrade
- Monitor `pg_stat_user_tables` for sequential-scan increases
