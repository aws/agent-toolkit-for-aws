# DSQL Database Operations Reference

Part of the [Aurora DSQL Skill](../SKILL.md). The PREFERRED execution path is `psql` via
[`scripts/psql-connect.sh`](../scripts/psql-connect.sh); application code should use the
language-specific [DSQL Connector](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html).

---

## 1. Read-Only Queries (SELECT)

**Use for:** SELECT queries, data exploration, ad-hoc analysis.

**Connect with the scoped (non-admin) auth token:**

```bash
./scripts/psql-connect.sh --cluster <cluster-id> --command "SELECT * FROM entities LIMIT 10"
```

The wrapper rejects multi-statement input, dollar-quoted strings, and SQL comment markers in
`--command` (a single trailing semicolon is accepted). For multi-statement scripts (BEGIN/COMMIT
blocks, migration files, GUC experiments), use `--script PATH` instead — it runs a SQL file
through `psql -f` with `ON_ERROR_STOP=1` and no semicolon guard. In application code, build SQL
with [`safe_query.build()`](../scripts/safe_query.py) and execute via your driver.

**Examples:**

```python
from safe_query import build, regex, ident, TENANT_SLUG

# Simple SELECT — user-supplied tenant_id goes through a validator
sql = build(
    "SELECT * FROM {tbl} WHERE tenant_id = {tid} LIMIT 10",
    tbl=ident("entities"),
    tid=regex(tenant_id, TENANT_SLUG),
)
# Pass `sql` to your driver: psycopg `cur.execute(sql)`, pgx `conn.Query(ctx, sql)`, etc.

# Aggregate query (no user-supplied values)
sql = build(
    "SELECT tenant_id, COUNT(*) as count FROM objectives GROUP BY tenant_id",
)

# Join query — declare e/o as table aliases after each ident() expansion
sql = build(
    "SELECT e.entity_id, e.name, o.title "
    "FROM {e} e INNER JOIN {o} o ON e.entity_id = o.entity_id "
    "WHERE e.tenant_id = {tid}",
    e=ident("entities"),
    o=ident("objectives"),
    tid=regex(tenant_id, TENANT_SLUG),
)
```

**Building queries:** **MUST** build SQL with
[`safe_query.build()`](../scripts/safe_query.py) for any value that originates outside the
developer's source code. F-string interpolation is the primary SQL-injection vector. See
[input-validation.md](input-validation.md) for the required pattern.

---

## 2. Write Operations (INSERT / UPDATE / DELETE / DDL)

**Use for:** INSERT, UPDATE, DELETE, CREATE TABLE, ALTER TABLE.

**Connect with the admin auth token (or a scoped role with the appropriate grants):**

```bash
./scripts/psql-connect.sh --cluster <cluster-id> --admin --command "ALTER TABLE entities ADD COLUMN status VARCHAR(50)"
```

**DSQL transaction rules (always apply):**

- **One DDL statement per transaction.** Each `psql -c` invocation already opens its own implicit
  transaction, so chaining DDL across one invocation is forbidden.
- **CREATE INDEX ASYNC** is required; synchronous index creation is not supported.
- **Atomic commit/rollback.** Multi-statement DML inside a single transaction commits or rolls
  back as a unit — open the transaction explicitly with `BEGIN;`/`COMMIT;` when feeding multiple
  statements through a driver.

**Examples (driver-side, using `safe_query` to compose the statements):**

```python
# Create table with index — TWO transactions, in order
conn.execute("CREATE TABLE IF NOT EXISTS entities (...)")           # tx 1: DDL
conn.execute("CREATE INDEX ASYNC idx_entities_tenant ON entities(tenant_id)")  # tx 2: DDL

# Insert rows — build each statement with safe_query.
from safe_query import build, allow, regex, literal, UUID, TENANT_SLUG

with conn.transaction():
    for row in rows:  # keep each transaction under 3,000 rows
        sql = build(
            "INSERT INTO entities (entity_id, tenant_id, name) "
            "VALUES ({eid}, {tid}, {name})",
            eid=regex(row["entity_id"], UUID),
            tid=regex(row["tenant_id"], TENANT_SLUG),
            name=literal(row["name"]),
        )
        conn.execute(sql)

# Two-step column migration
STATUSES = {"active", "archived", "pending"}
conn.execute("ALTER TABLE entities ADD COLUMN status VARCHAR(50)")  # tx 1
sql = build(
    "UPDATE entities SET status = {s} "
    "WHERE status IS NULL AND tenant_id = {tid}",
    s=allow("active", STATUSES),
    tid=regex(tenant_id, TENANT_SLUG),
)
conn.execute(sql)                                                   # tx 2
```

**Important Notes:**

- Each ALTER TABLE must be in its own transaction (DSQL limitation)
- Keep transactions under 3,000 rows and 10 MiB
- For large batch operations, split across multiple transactions
- **MUST** build every statement with [`safe_query.build()`](../scripts/safe_query.py) when any
  value is not a developer-controlled literal.

---

## 3. Schema Discovery

**Use for:** understanding table structure, planning migrations, exploring the database.

DSQL supports the standard PostgreSQL `information_schema` and `pg_catalog` views — no
DSQL-specific helper is needed.

**List tables in the public schema:**

```sql
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';
```

**Inspect a specific table's columns:**

```sql
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'entities'
ORDER BY ordinal_position;
```

**Inspect indexes on a table:**

```sql
SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'entities';
```

Run any of these via [`scripts/psql-connect.sh`](../scripts/psql-connect.sh) or your driver of
choice.
