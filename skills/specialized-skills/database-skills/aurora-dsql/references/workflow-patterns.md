# Common DSQL Workflow Patterns

Part of the [Aurora DSQL Skill](../SKILL.md). The patterns below assume execution via a Postgres
driver (psycopg, pgx, etc.) using the language-specific [DSQL Connector](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html),
or via [`scripts/psql-connect.sh`](../scripts/psql-connect.sh) for ad-hoc shells.

---

## Pattern 1: Explore Schema

```sql
-- List tables
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';

-- Inspect a specific table
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'entities'
ORDER BY ordinal_position;

-- Sample data
SELECT * FROM entities LIMIT 10;
```

## Pattern 2: Create Table with Index

```python
# WRONG - Combined DDL and index in single transaction
with conn.transaction():
    conn.execute("CREATE TABLE entities (...)")
    conn.execute("CREATE INDEX ASYNC idx_tenant ON entities(tenant_id)")  # ❌ Will fail

# CORRECT - Separate transactions (one DDL each)
conn.execute("CREATE TABLE entities (...)")
conn.execute("CREATE INDEX ASYNC idx_tenant ON entities(tenant_id)")
```

## Pattern 3: Safe Data Migration

```python
from safe_query import build, allow, regex, TENANT_SLUG

STATUSES = {"active", "archived", "pending"}

# Step 1: Add column (its own transaction)
conn.execute("ALTER TABLE entities ADD COLUMN status VARCHAR(50)")

# Step 2: Populate in batches — each in its own transaction, under 3,000 rows
populate = build(
    "UPDATE entities SET status = {s} "
    "WHERE entity_id IN ("
    "    SELECT entity_id FROM entities WHERE status IS NULL LIMIT 1000"
    ")",
    s=allow("active", STATUSES),
)
conn.execute(populate)
conn.execute(populate)

# Step 3: Verify
rows = conn.execute("SELECT COUNT(*) AS total, COUNT(status) AS with_status FROM entities").fetchall()

# Step 4: Create index in a separate transaction
conn.execute("CREATE INDEX ASYNC idx_status ON entities(tenant_id, status)")
```

## Pattern 4: Batch Inserts

```python
from safe_query import build, regex, literal, UUID, TENANT_SLUG

with conn.transaction():               # one transaction per chunk
    for row in rows[:2500]:            # keep each transaction under 3,000 rows
        sql = build(
            "INSERT INTO entities (entity_id, tenant_id, name) "
            "VALUES ({eid}, {tid}, {name})",
            eid=regex(row["entity_id"], UUID),
            tid=regex(row["tenant_id"], TENANT_SLUG),
            name=literal(row["name"]),
        )
        conn.execute(sql)
```

## Pattern 5: Application-Layer Foreign Key Check

```python
from safe_query import build, regex, literal, UUID, TENANT_SLUG

check = build(
    "SELECT entity_id FROM entities "
    "WHERE entity_id = {eid} AND tenant_id = {tid}",
    eid=regex(parent_id, UUID),
    tid=regex(tenant_id, TENANT_SLUG),
)
if not conn.execute(check).fetchall():
    raise ValueError("Invalid parent reference")

insert = build(
    "INSERT INTO objectives (objective_id, entity_id, tenant_id, title) "
    "VALUES ({oid}, {eid}, {tid}, {title})",
    oid=regex(new_objective_id, UUID),
    eid=regex(parent_id, UUID),
    tid=regex(tenant_id, TENANT_SLUG),
    title=literal(objective_title),
)
conn.execute(insert)
```
