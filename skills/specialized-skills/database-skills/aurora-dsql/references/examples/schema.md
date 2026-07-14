# DSQL Examples: Schema Design

Part of [Aurora DSQL Implementation Examples](../dsql-examples.md).

---

## Schema Design: Table Creation

SHOULD use UUIDs with `gen_random_uuid()` for distributed write performance. Source: Adapted from the Liquibase migration sample listed at the [Aurora DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

```sql
CREATE TABLE IF NOT EXISTS owner (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(30) NOT NULL,
  city VARCHAR(80) NOT NULL,
  telephone VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS orders (
  order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id VARCHAR(255) NOT NULL,
  status VARCHAR(50) NOT NULL,
  tags TEXT,
  metadata TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Schema Design: Index Creation

MUST use `CREATE INDEX ASYNC` (defaults: max 24 indexes per table, 8 columns per index — verify via the AWS MCP Server's `aws___search_documentation` if available, or the [DSQL documentation](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/): `aurora dsql index limits`). Source: Adapted from the Liquibase migration sample listed at the [Aurora DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

```sql
CREATE INDEX ASYNC idx_owner_city ON owner(city);
CREATE INDEX ASYNC idx_orders_tenant ON orders(tenant_id);
CREATE INDEX ASYNC idx_orders_status ON orders(tenant_id, status);
```

---

## Schema Design: Column Modifications

MUST use two-step process: add column, then UPDATE for defaults (ALTER COLUMN not supported).

```sql
ALTER TABLE orders ADD COLUMN priority INTEGER;
UPDATE orders SET priority = 0 WHERE priority IS NULL;
```
