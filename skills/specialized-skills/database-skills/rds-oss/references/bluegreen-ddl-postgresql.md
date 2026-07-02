# PostgreSQL DDL Compatibility with Blue/Green Replication

RDS PostgreSQL Blue/Green uses logical replication (not binlog). This has different compatibility characteristics than MySQL's binlog-based approach.

## Key Difference: Logical Replication

PostgreSQL Blue/Green creates a logical replication slot on blue and subscribes on green. Logical replication replicates row-level changes (INSERT, UPDATE, DELETE) but does NOT replicate DDL. This means:

- DDL on green does NOT automatically propagate to blue (by design)
- But some DDL on green can make the green schema incompatible with incoming replicated rows

## Safe Operations (replication continues)

| Operation | Notes |
|-----------|-------|
| ADD COLUMN at end with static default | e.g., `ADD COLUMN status TEXT DEFAULT 'active'`. Safe. |
| ADD COLUMN at end with NULL default | Safe. Replicated rows get NULL for new column. |
| CREATE INDEX / DROP INDEX | No schema change to row format. Safe. |
| CREATE INDEX CONCURRENTLY | Safe and recommended on green to avoid locks. |
| ADD/DROP CHECK constraint | No row format change. Safe. |
| ADD/DROP NOT NULL constraint | Safe if existing data complies. |
| ANALYZE / VACUUM | Maintenance only. Safe. |
| COMMENT ON | Metadata only. Safe. |

## Replication-Breaking Operations

| Operation | Why It Breaks | What To Do |
|-----------|---------------|------------|
| ALTER COLUMN TYPE (type change) | Table rewrite. Logical replication can't apply old-type rows to new-type column. | Apply on green, switchover immediately. |
| ADD COLUMN with volatile DEFAULT | e.g., `DEFAULT now()`, `DEFAULT gen_random_uuid()`. Each replicated row would need to evaluate the default, causing mismatches. | Use static default or NULL, then backfill after switchover. |
| RENAME TABLE | Logical replication subscription references the old table name. Slot breaks. | Switchover immediately after rename. |
| RENAME COLUMN | Logical replication uses column names (not positions like binlog). Rename breaks mapping. | Switchover immediately. |
| DROP COLUMN on green | Replicated rows still contain the dropped column. Logical replication fails. | Switchover immediately, or drop column after switchover. |

## PostgreSQL-Specific Gotchas

### Sequences

- Sequences are NOT replicated by logical replication
- After switchover, sequences on green may be behind if they were not manually advanced
- You MUST check and reset sequences after switchover:

```sql
SELECT setval('my_table_id_seq', (SELECT MAX(id) FROM my_table));
```

### Logical Replication Slots

- Blue/Green creates a replication slot on the blue instance
- During switchover, this slot is dropped
- If you have OTHER logical replication consumers (e.g., Debezium, DMS), their slots are unaffected
- But any downstream consumer of the Blue/Green slot itself needs to be re-established

### Large Objects (LOBs)

- Logical replication does NOT replicate large objects (`lo_*` types)
- If your schema uses `lo` or `oid` references to large objects, Blue/Green may not capture all data
- Use `bytea` or `text` columns instead

### TOAST Tables

- TOAST data is replicated correctly via logical replication
- No special handling needed for large `text`, `jsonb`, or `bytea` columns stored in TOAST

### Extension Changes

- Installing or upgrading extensions on green is safe
- But if an extension creates new data types used in replicated tables, replication may break
- Test extension changes on a snapshot-restored instance first

### Publication/Subscription

- Blue/Green manages its own publication and subscription
- Do NOT manually create publications or subscriptions on the blue or green instances
- Doing so may conflict with the managed replication

## Monitoring Replication Lag

Before switchover, check replication lag on blue:

```sql
SELECT slot_name, confirmed_flush_lsn, pg_current_wal_lsn(),
  (pg_current_wal_lsn() - confirmed_flush_lsn) AS lag_bytes
FROM pg_replication_slots
WHERE slot_type = 'logical';
```

Switchover will wait for lag to reach zero. If lag is large, switchover takes longer.

## Best Practice

1. Apply all DDL on green in a single session
2. If any change breaks logical replication, switchover immediately
3. After switchover, reset sequences: `SELECT setval(...)` for all serial/identity columns
4. After switchover, run `ANALYZE` on modified tables
5. Verify no orphaned replication slots remain on the new primary
