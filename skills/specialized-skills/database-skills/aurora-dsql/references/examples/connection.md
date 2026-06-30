# DSQL Examples: Connection & Ad-Hoc Queries

Part of [Aurora DSQL Implementation Examples](../dsql-examples.md).

---

## Ad-Hoc Queries with psql

PREFER connecting with a scoped database role using `generate-db-connect-auth-token`.
Reserve `admin` for role and schema setup only. See [access-control.md](../access-control.md).

```bash
# PREFERRED: Execute queries with a scoped role
PGPASSWORD="$(aws dsql generate-db-connect-auth-token \
  --hostname ${CLUSTER}.dsql.${REGION}.on.aws \
  --region ${REGION})" \
psql -h ${CLUSTER}.dsql.${REGION}.on.aws -U app_readwrite -d postgres \
  -c "SELECT COUNT(*) FROM objectives WHERE tenant_id = 'tenant-123';"

# Admin only — for role/schema setup
PGPASSWORD="$(aws dsql generate-db-connect-admin-auth-token \
  --hostname ${CLUSTER}.dsql.${REGION}.on.aws \
  --region ${REGION})" \
PGAPPNAME="<app-name>/<model-id>" \
psql -h ${CLUSTER}.dsql.${REGION}.on.aws -U admin -d postgres
```

---

## Connection Management

### RECOMMENDED: DSQL Connector

Source: Adapted from the JavaScript connector samples listed at the [Aurora DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)

```javascript
import { AuroraDSQLPool } from "@aws/aurora-dsql-node-postgres-connector";

function createPool(clusterEndpoint, user) {
  return new AuroraDSQLPool({
    host: clusterEndpoint,
    user: user,
    application_name: "<app-name>/<model-id>",
    max: 10,
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 10000,
  });
}

async function example() {
  const pool = createPool(process.env.CLUSTER_ENDPOINT, process.env.CLUSTER_USER);

  try {
    const result = await pool.query("SELECT $1::int as value", [42]);
    console.log(`Result: ${result.rows[0].value}`);
  } finally {
    await pool.end();
  }
}
```
