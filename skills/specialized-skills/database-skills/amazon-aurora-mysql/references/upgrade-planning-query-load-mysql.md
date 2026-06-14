# Aurora MySQL — Query Load Analysis & Explain Plan Review

## Purpose

Identify the top queries generating load, run EXPLAIN on them, and flag execution plan patterns that will behave differently after upgrading from Aurora MySQL 2 (5.7) to Aurora MySQL 3 (8.0).

## Step 1: Get Top 5 Queries by Load

### Option A: Performance Schema (preferred)

```sql
SELECT DIGEST_TEXT, COUNT_STAR, SUM_TIMER_WAIT/1000000000000 AS total_time_sec,
  AVG_TIMER_WAIT/1000000000 AS avg_time_ms, SUM_ROWS_EXAMINED, SUM_ROWS_SENT,
  FIRST_SEEN, LAST_SEEN
FROM performance_schema.events_statements_summary_by_digest
WHERE SCHEMA_NAME NOT IN ('mysql','information_schema','performance_schema','sys')
ORDER BY SUM_TIMER_WAIT DESC LIMIT 5;
```

### Option B: sys schema (if available)

```sql
SELECT query, exec_count, total_latency, avg_latency, rows_examined_avg, rows_sent_avg
FROM sys.statements_with_runtimes_in_95th_percentile LIMIT 5;
```

## Step 2: Run EXPLAIN on Each Query

For each query from Step 1, run:

```sql
EXPLAIN FORMAT=JSON <query>;
```

If the query has parameters (using `?` placeholders from digest), substitute reasonable values or use:

```sql
EXPLAIN FORMAT=JSON SELECT ... FROM ... WHERE col = 1;
```

## Step 3: Flag Upgrade-Impacting Patterns

Analyze each EXPLAIN output for these patterns and flag accordingly:

### 🔴 Critical — Behavior Changes That Will Impact Performance

| Pattern in EXPLAIN | Why It Matters in 8.0 | Action |
|---|---|---|
| `"using_temporary_table": true` | MySQL 8.0 replaces the internal temp table engine. In 5.7, `MEMORY` engine is used for in-memory temp tables. In 8.0, `TempTable` engine is default with new parameters (`temptable_max_ram`, `temptable_max_mmap`). In 5.7, the on-disk internal temp-table engine defaults to InnoDB on the writer (set via `internal_tmp_disk_storage_engine`; readers use MyISAM). In 8.0, TempTable overflow goes to memory-mapped temporary files by default, or to InnoDB on-disk temp tables, controlled by `temptable_max_mmap` (readers always use TempTable/mmap in v3). | Set `internal_tmp_mem_storage_engine=TempTable` and tune `temptable_max_ram` (default 1GB). Monitor `Created_tmp_disk_tables` after upgrade. If queries relied on MEMORY engine behavior, test thoroughly. |
| `"using_filesort": true` with large `rows_examined` | The sort algorithm changed in 8.0. New optimizer may choose different sort strategies. | Benchmark these queries on a snapshot-restored test cluster before upgrade. |
| Hash join absent on large joins | MySQL 8.0 introduces hash joins for equi-joins without indexes. Optimizer may choose different plans. | Queries that were slow due to nested loop joins may improve, but verify with EXPLAIN on 8.0. |

### 🟡 Warning — Optimizer Behavior Differences

| Pattern in EXPLAIN | Why It Matters in 8.0 | Action |
|---|---|---|
| `"using_join_buffer": "Block Nested Loop"` | 8.0 may replace BNL with hash join for certain queries. Usually faster, but plan changes can surprise. | Test on snapshot cluster. Consider `optimizer_switch` to disable hash_join if regression found. |
| Derived table materialization (`"materialized_from_subquery"`) | 8.0 optimizer has improved derived table merging. Plans may change. | Usually beneficial. Monitor after upgrade. |
| `"index_merge"` usage | Index merge behavior refined in 8.0. | Verify same indexes are used post-upgrade. |
| Full table scan on small tables | 8.0 optimizer cost model updated. May choose index where 5.7 chose scan (or vice versa). | Run EXPLAIN on test cluster to compare. |
| `"query_cost"` significantly different | Cost model recalibrated in 8.0. | Use as baseline comparison only. |

### 🟢 Clean — No Upgrade Impact

| Pattern | Notes |
|---|---|
| Simple index lookups (`ref`, `eq_ref`, `const`) | No behavioral change expected. |
| Primary key lookups | Stable across versions. |
| Covering indexes (`Using index`) | No change. |

## Step 4: Generate Recommendations

For each flagged query, provide:

1. The query (truncated if long)
2. Current execution stats (calls, avg time, rows examined)
3. The problematic EXPLAIN pattern
4. Why it matters for the upgrade
5. Specific action: parameter to set, index to add, or test to run

## Key MySQL 8.0 Optimizer Changes to Watch For

- **Hash joins**: New in 8.0, replaces BNL for equi-joins without indexes
- **TempTable engine**: Replaces MEMORY for internal temp tables, different overflow behavior
- **Descending indexes**: Now supported natively (no more backward scans)
- **Invisible indexes**: Can test index removal without dropping
- **Histograms**: Optimizer can use column statistics for better cardinality estimates
- **Derived table merging**: Improved, may change plans for subqueries
- **Cost model**: Updated I/O and memory cost factors
- **GROUP BY no longer implicitly sorts**: Queries relying on implicit GROUP BY ordering will break
