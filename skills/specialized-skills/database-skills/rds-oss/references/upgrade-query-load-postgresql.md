# RDS PostgreSQL — Query Load Analysis & Explain Plan Review

## Step 1: Get Top 5 Queries by Load

```sql
SELECT queryid, query, calls, total_exec_time::numeric(12,2) AS total_time_ms,
  mean_exec_time::numeric(12,2) AS avg_time_ms,
  rows, shared_blks_hit, shared_blks_read
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC LIMIT 5;
```

## Step 2: Run EXPLAIN on Each Query

```sql
EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <query>;
```

For data-modifying queries, wrap in a transaction and rollback.

## Step 3: Flag Upgrade-Impacting Patterns

### 🔴 Critical

| Pattern | Versions | Action |
|---|---|---|
| `Sort Method: external merge` | PG 15+ | `work_mem` per-operation accounting changed. Tune `work_mem` and `hash_mem_multiplier`. |
| `HashAggregate` with `Batches > 1` | PG 15+ | Memory accounting different. Adjust `work_mem`. |
| JIT on short queries | PG 14+ | JIT overhead causes latency spikes. Adjust `jit_above_cost` thresholds. |

### 🟡 Warning

| Pattern | Versions | Action |
|---|---|---|
| Nested Loop without Memoize | PG 14+ | PG 14 introduced Memoize. Usually beneficial. Set `enable_memoize=off` if regression. |
| Parallel scan threshold changes | PG 14-16 | Plans may gain/lose parallelism. Compare on test instance. |
| Merge Join on large tables | PG 16+ | Improved costing may change join strategy. Benchmark. |

### 🟢 Clean

| Pattern | Notes |
|---|---|
| Simple Index Scan / Index Only Scan | Stable across versions. |
| Seq Scan on small tables | No change. |

## Key PostgreSQL Optimizer Changes

- PG 14: Memoize node, improved extended statistics
- PG 15: work_mem hash operation changes, improved sort
- PG 16: Subquery decorrelation, improved merge join costing
- PG 17: Enhanced memory management, improved vacuum
