# DSQL DDL Migration Guide - Overview

This guide provides the **Table Recreation Pattern** for schema modifications that require rebuilding tables.

For column-level operations, see [column-operations.md](column-operations.md).
For constraint and structural operations, see [constraint-operations.md](constraint-operations.md).
For batched migration patterns, see [batched-migration.md](batched-migration.md).

---

## CRITICAL: Destructive Operations Warning

**The Table Recreation Pattern involves DESTRUCTIVE operations that can result in DATA LOSS.**

Table recreation requires dropping the original table, which is **irreversible**. If any step fails after the original table is dropped, data may be permanently lost.

### Mandatory User Verification Requirements

Agents MUST obtain explicit user approval before executing migrations on live tables:

1. **MUST present the complete migration plan** to the user before any execution
2. **MUST clearly state** that this operation will DROP the original table
3. **MUST confirm** the user has a current backup or accepts the risk of data loss
4. **MUST verify with the user** at each checkpoint before proceeding:
   - Before creating the new table structure
   - Before beginning data migration
   - Before dropping the original table (CRITICAL CHECKPOINT)
   - Before renaming the new table
5. **MUST NOT proceed** with any destructive action without explicit user confirmation
6. **MUST recommend** performing migrations on non-production environments first

### Risk Acknowledgment

Before proceeding, the user MUST confirm:

- [ ] They understand this is a destructive operation
- [ ] They have a backup of the table data (or accept the risk)
- [ ] They approve the agent to execute each step with verification
- [ ] They understand the migration cannot be automatically rolled back after DROP TABLE

---

## Table Recreation Operations

The following ALTER TABLE operations MUST use the **Table Recreation Pattern**:

| Operation                      | Key Approach                                   |
| ------------------------------ | ---------------------------------------------- |
| DROP COLUMN                    | Exclude column from new table                  |
| ALTER COLUMN TYPE              | Cast data type in SELECT                       |
| ALTER COLUMN SET/DROP NOT NULL | Change constraint in new table definition      |
| ALTER COLUMN SET/DROP DEFAULT  | Define default in new table definition         |
| ADD CONSTRAINT                 | Include constraint in new table definition     |
| DROP CONSTRAINT                | Remove constraint from new table definition    |
| MODIFY PRIMARY KEY             | Define new PK, validate uniqueness first       |
| Split/Merge Columns            | Use SPLIT_PART, SUBSTRING, or CONCAT in SELECT |

**Note:** The following operations ARE supported directly. Each is still subject to the
one-DDL-per-transaction rule — issue each as its own `psql -c` invocation (or its own
`BEGIN`/`COMMIT` block when scripted):

- `ALTER TABLE ... RENAME COLUMN` - Rename a column
- `ALTER TABLE ... RENAME TO` - Rename a table
- `ALTER TABLE ... ADD COLUMN` - Add a new column

---

## CREATE INDEX ASYNC Syntax (DSQL)

DSQL accepts a narrow subset of standard PostgreSQL `CREATE INDEX` syntax. The skill enforces
`CREATE INDEX ASYNC` everywhere; additional clauses behave as follows (validated against a live
DSQL cluster):

| Clause                                | DSQL behavior                                                                                 |
| ------------------------------------- | --------------------------------------------------------------------------------------------- |
| `IF NOT EXISTS`                       | Accepted                                                                                      |
| `INCLUDE (<columns>)`                 | Accepted (covering indexes)                                                                   |
| `UNIQUE` (`CREATE UNIQUE INDEX ASYNC`)| Accepted                                                                                      |
| `USING <method>` (btree/hash/gin/...) | **Rejected**: `ERROR: USING not supported for CREATE INDEX` — DSQL is btree-only              |
| `WHERE <predicate>`                   | **Rejected**: `ERROR: WHERE not supported for CREATE INDEX` — partial indexes are unavailable |
| `CONCURRENTLY`                        | **Rejected**: `ERROR: CONCURRENTLY not supported for CREATE INDEX` — use `ASYNC` instead (non-blocking by design) |

Without `ASYNC`, DSQL rejects with `ERROR: unsupported mode. please use CREATE INDEX ASYNC.` —
useful to grep for in failure logs.

If the migration source (e.g., a vanilla PostgreSQL dump) relies on partial indexes or non-btree
access methods, the pattern MUST be rewritten — denormalize via a filter column, or add a CHECK
constraint and a covering composite index. Document the workaround in the migration plan.

---

## Table Recreation Pattern Overview

MUST follow this sequence with user verification at each step:

1. **Plan & Confirm** - MUST present migration plan and obtain user approval to proceed
2. **Validate** - Check data compatibility with new structure; MUST report findings to user
3. **Create** - Create new table with desired structure; MUST verify with user before execution
4. **Migrate** - Copy data (batched for tables > 3,000 rows); MUST report progress to user
5. **Verify** - Confirm row counts match; MUST present comparison to user
6. **Swap** - CRITICAL: MUST obtain explicit user confirmation before DROP TABLE
7. **Re-index** - Recreate indexes using ASYNC; MUST confirm completion with user

### Transaction Rules

Defaults below; verify against the live limits via the AWS MCP Server's `aws___search_documentation` if available (`aurora dsql transaction limits`), or read the [DSQL documentation](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/) directly:

- **MUST batch** migrations exceeding 3,000 row mutations
- **PREFER batches of 500-1,000 rows** for optimal throughput
- **MUST respect** 10 MiB data size per transaction
- **MUST respect** 5-minute transaction duration

---

## Common Verify & Swap Pattern

All migrations end with this pattern (referenced in [column-operations.md](column-operations.md) and [constraint-operations.md](constraint-operations.md)).

**CRITICAL: MUST obtain explicit user confirmation before DROP TABLE step.**

```sql
-- MUST verify counts match
SELECT COUNT(*) FROM target_table;
SELECT COUNT(*) FROM target_table_new;

-- CHECKPOINT: MUST present count comparison to user and obtain confirmation
-- Agent MUST display: "Original table has X rows, new table has Y rows.
-- Proceeding will DROP the original table. This action is IRREVERSIBLE.
-- Do you want to proceed? (yes/no)"
-- MUST NOT proceed without explicit "yes" confirmation

-- MUST swap tables (DESTRUCTIVE - requires user confirmation above).
-- Each DDL below MUST run in its own transaction (DSQL: one DDL per
-- transaction). Run as separate `psql-connect.sh --command` calls,
-- or as separate transactions in your driver:
DROP TABLE target_table;
ALTER TABLE target_table_new RENAME TO target_table;

-- MUST recreate indexes (each in its own transaction; CREATE INDEX ASYNC
-- is non-blocking and required by DSQL):
CREATE INDEX ASYNC idx_target_tenant ON target_table(tenant_id);
```

### Recovery — Row Counts Do Not Match

When `target_table_new` has fewer rows than `target_table`, treat the migration as incomplete.
The original table still holds the authoritative data, so recovery is always possible — **MUST NOT**
proceed with `DROP TABLE` until the counts agree.

1. **Diagnose** — find the missing rows by comparing ranges (for cursor-based migrations, query
   `target_table` for IDs greater than `MAX(id)` in `target_table_new`; for OFFSET-based, check
   which batch dropped rows by re-running the SELECT portion of each batch and comparing counts).
2. **Retry the missing batches** — insert only the gap rows into `target_table_new`. Filter out
   already-migrated rows to avoid PK collisions (which would roll back the entire batch):

   ```sql
   -- Cursor-based: only insert rows beyond what was already migrated
   INSERT INTO target_table_new (id, col1, col2)
   SELECT id, col1, col2 FROM target_table
   WHERE id > (SELECT COALESCE(MAX(id), 0) FROM target_table_new)
   ORDER BY id LIMIT 1000;

   -- For non-sequential gaps, use NOT EXISTS:
   INSERT INTO target_table_new (id, col1, col2)
   SELECT id, col1, col2 FROM target_table
   WHERE NOT EXISTS (
     SELECT 1 FROM target_table_new WHERE target_table_new.id = target_table.id
   )
   ORDER BY id LIMIT 1000;
   ```

3. **If a type cast or constraint rejected rows** — migration cannot complete until the data is
   reconciled. Fix the source data in `target_table` (or adjust the new table's constraint),
   then re-run the missing batches.
4. **Escape hatch** — if diagnosis stalls, drop `target_table_new` and restart the migration
   from a clean slate. The original table is untouched, so no data is at risk.

Re-run the count comparison after each retry. Only proceed to `DROP TABLE` once
`COUNT(*)` matches exactly.

---

## Best Practices Summary

### User Verification (CRITICAL)

- **MUST present** complete migration plan to user before any execution
- **MUST obtain** explicit user confirmation before DROP TABLE operations
- **MUST verify** with user at each checkpoint during migration
- **MUST NOT** proceed with destructive actions without explicit user approval
- **MUST recommend** testing migrations on non-production data first
- **MUST confirm** user has backup or accepts data loss risk

### Technical Requirements

- **MUST validate** data compatibility before type changes
- **MUST batch** tables exceeding 3,000 rows
- **MUST verify** row counts before and after migration
- **MUST recreate** indexes after table swap using ASYNC
- **MUST NOT** drop original table until new table is verified
- **PREFER** cursor-based batching for very large tables
- **PREFER** batches of 500-1,000 rows for optimal throughput
