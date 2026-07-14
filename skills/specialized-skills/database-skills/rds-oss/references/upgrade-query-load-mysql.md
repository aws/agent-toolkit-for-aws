# RDS MySQL/MariaDB — Query Load Analysis & Explain Plan Review

## Step 1: Get Top 5 Queries by Load

```sql
SELECT DIGEST_TEXT, COUNT_STAR, SUM_TIMER_WAIT/1000000000000 AS total_time_sec,
  AVG_TIMER_WAIT/1000000000 AS avg_time_ms, SUM_ROWS_EXAMINED, SUM_ROWS_SENT,
  FIRST_SEEN, LAST_SEEN
FROM performance_schema.events_statements_summary_by_digest
WHERE SCHEMA_NAME NOT IN ('mysql','information_schema','performance_schema','sys')
ORDER BY SUM_TIMER_WAIT DESC LIMIT 5;
```

## Step 2: Run EXPLAIN on Each Query

```sql
EXPLAIN FORMAT=JSON <query>;
```

## Step 3: Flag Upgrade-Impacting Patterns

### 🔴 Critical

| Pattern | Why It Matters in 8.0 | Action |
|---|---|---|
| `using_temporary_table: true` | TempTable engine replaces MEMORY. Overflow goes to mmap, not MyISAM. | Tune `temptable_max_ram`. Monitor `Created_tmp_disk_tables`. |
| `using_filesort: true` + large rows | Sort algorithm changed. | Benchmark on test instance. |
| GROUP BY implicit sort relied upon | 8.0 no longer implicitly sorts GROUP BY. | Add explicit ORDER BY. |

### 🟡 Warning

| Pattern | Why It Matters | Action |
|---|---|---|
| `Block Nested Loop` joins | 8.0 may replace with hash join. Usually faster. | Test. Use `optimizer_switch` to disable hash_join if regression. |
| Derived table materialization | 8.0 improved derived table merging. | Usually beneficial. Monitor. |
| `index_merge` usage | Behavior refined in 8.0. | Verify same indexes used post-upgrade. |

### 🟢 Clean

| Pattern | Notes |
|---|---|
| Simple index lookups (`ref`, `eq_ref`, `const`) | No change. |
| Covering indexes (`Using index`) | No change. |

## Key MySQL 8.0 Optimizer Changes

- Hash joins for equi-joins without indexes
- TempTable engine replaces MEMORY for internal temp tables
- GROUP BY no longer implicitly sorts
- Descending indexes supported natively
- Updated cost model for I/O and memory
