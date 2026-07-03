# MySQL/MariaDB DDL Compatibility with Blue/Green Replication

Blue/Green uses binlog replication (ROW format) to keep green in sync with blue. Some DDL operations break this replication.

## Safe Operations (replication continues)

| Operation | Notes |
|-----------|-------|
| ADD COLUMN at end of table | Replication continues. New column is NULL on blue rows. |
| ADD INDEX / DROP INDEX | Index-only changes don't affect row format. |
| OPTIMIZE TABLE | Internally does ALTER TABLE FORCE + ANALYZE. Safe on green. |
| ANALYZE TABLE | Statistics refresh only. No schema change. |
| ALTER TABLE ... ENGINE=InnoDB | Table rebuild. Safe on green. |
| Partition reorganization | Safe if partitioning schema remains compatible. |

## Replication-Breaking Operations (proceed to switchover immediately)

| Operation | Why It Breaks | What To Do |
|-----------|---------------|------------|
| MODIFY COLUMN (type change) | Row format changes. Binlog events can't be applied. | Apply DDL, then switchover immediately. Do NOT wait. |
| CHANGE COLUMN (rename + type) | Same as MODIFY — row format mismatch. | Apply DDL, then switchover. |
| ADD COLUMN ... AFTER col | Column position changes. Binlog column index mismatch. | Use ADD COLUMN at end instead, or switchover immediately. |
| RENAME TABLE | Binlog references old table name. | Switchover immediately after rename. |
| RENAME COLUMN | Binlog uses column index, but metadata mismatch can cause issues. | Switchover immediately. |

## Operations That May Fail Switchover

| Operation | Risk |
|-----------|------|
| DROP COLUMN on green | Blue still writes to that column. Replication fails. Switchover may fail. |
| Change AUTO_INCREMENT value | Sequence gaps or conflicts during switchover. |
| Add UNIQUE constraint on green | Blue may have duplicates that violate the constraint. |

## Foreign Key Handling

Blue/Green handles foreign keys natively — no need to drop/recreate them as with gh-ost. DDL on tables with foreign keys works as expected on the green environment.

## Best Practice

1. Apply all DDL changes on green in a single session
2. If any change breaks replication, proceed to switchover immediately
3. Do NOT apply further changes on blue after replication breaks
4. Verify schema on green before initiating switchover
