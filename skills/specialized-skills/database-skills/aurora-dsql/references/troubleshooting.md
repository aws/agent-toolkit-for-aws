# Troubleshooting in DSQL

This file contains common additional errors encountered while working with DSQL and
guidelines for how to solve them.

Before referring to any listed errors, refer to the complete [DSQL troubleshooting guide](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/troubleshooting.html#troubleshooting-connections)

## Connection and Authorization

### Token Expiration

### Error: "Token has expired"

**Cause:** Authentication token older than 15 minutes
**Solutions:**

- Auto-regenerate tokens per connection or query OR
- Use connection pool hooks to refresh before expiration OR
- Implement retry logic with token regeneration

**Additional Recommendations:**

- Refresh connections within 15 minutes
- Auto-reconnect after observing auth errors

### Connection Timeouts

**Problem**: Database connections time out after 1 hour.
**Solution**:

- Configure connection pool lifetime < 1 hour
- Implement connection health checks
- Handle disconnection gracefully with retries

### Schema Privileges

**Problem**: Non-admin users get permission denied errors.

**Solution**:

- Non-admin users need explicit `GRANT` statements from admin to access any schema (including `public`). See [access-control.md](access-control.md) for the canonical role + grant setup.
- For sensitive data (PII, credentials, tokens), prefer a dedicated schema (e.g., `users_schema`) with scoped grants, separate from `public`. See [access-control.md](access-control.md#schema-separation-for-sensitive-data).
- Use `ALTER DEFAULT PRIVILEGES IN SCHEMA <schema> GRANT ... TO <role>` so tables created later inherit the grants automatically.
- Link database roles to IAM roles for authentication via `AWS IAM GRANT <role> TO '<iam-role-arn>'`.

### SSL Certificate Verification

**Problem**: SSL verification fails with certificate errors.

**Solution**:

- Use psql ≥14 (or a TLS library that supports SNI — required by DSQL's shared endpoint)
- Set `sslmode=verify-full` and point `sslrootcert` at a CA bundle that includes Amazon Root CAs (`sslrootcert=system` works on most OSes; libpq otherwise looks at `~/.postgresql/root.crt`)
- Use native TLS libraries (not OpenSSL 1.0.x)

### `root certificate file "/Users/<you>/.postgresql/root.crt" does not exist`

**Problem**: `psql` with `sslmode=verify-full` aborts because libpq is looking for a per-user CA bundle that doesn't exist. Common on a fresh macOS / Linux dev box that never had a personal CA bundle provisioned.

**Solution**: tell libpq to use the OS trust store instead. Either pass `sslrootcert=system` in the connection string, or set `PGSSLROOTCERT=system` in the environment. The bundled `scripts/psql-connect.sh` does this by default; only override `PGSSLROOTCERT` if you have a corporate CA bundle to point at.

```bash
export PGSSLROOTCERT=system            # libpq ≥16 supports `system` directly
psql "host=$ENDPOINT sslmode=verify-full sslrootcert=system" ...
```

**libpq <16:** the wrapper's `PGSSLROOTCERT=system` default will fail with `invalid value for parameter "sslrootcert": "system"`. Install the Amazon Root CAs into `~/.postgresql/root.crt` and override the env-var before invoking the wrapper:

```bash
PGSSLROOTCERT="$HOME/.postgresql/root.crt" ./scripts/psql-connect.sh --cluster <id> --command "..."
```

See the [accessing psql guide](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/accessing-psql.html) for the canonical CA-bundle setup.

## Incompatibility

When migrating from PostgreSQL, remember DSQL doesn't support:

- **Foreign key constraints** - Enforce referential integrity in application code
- **SERIAL types** - Use `GENERATED { ALWAYS | BY DEFAULT } AS IDENTITY` with sequences instead
- **Extensions** - No PL/pgSQL, PostGIS, pgvector, etc.
- **Triggers** - Implement logic in application layer
- **Temporary tables** - Use regular tables or application-level caching
- **TRUNCATE** - Use `DELETE FROM table` instead
- **Multiple databases** - Single `postgres` database per cluster
- **Custom types** - Limited type system support
- **Partitioning** - Manage data distribution in application

See [full list of unsupported features](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility-unsupported-features.html).

### Error: "Foreign key constraint not supported"

**Cause:** Attempting to create FOREIGN KEY constraint
**Solution:**

1. Remove FOREIGN KEY from DDL
2. Implement validation in application code
3. Check parent exists before INSERT
4. Check dependents before DELETE

### Error: "Datatype array not supported"

**Cause:** Using TEXT[] or other array types
**Solution:**

1. Change column to TEXT
2. Store as comma-separated: `"tag1,tag2,tag3"`
3. Or use JSON.stringify: `"["tag1","tag2","tag3"]"`
4. Deserialize in application layer

### Error: "Please use CREATE INDEX ASYNC"

**Cause:** Creating index without ASYNC keyword
**Solution:**

```sql
-- Wrong
CREATE INDEX idx_name ON table(column);

-- Correct
CREATE INDEX ASYNC idx_name ON table(column);
```

### Error: "Transaction exceeds 3000 rows"

**Cause:** Modifying too many rows in single transaction
**Solution:**

1. Batch operations into chunks of 500-1000 rows
2. Process each batch separately
3. Add WHERE clause to limit scope

### Error: "OC001 - Concurrent DDL operation"

**Cause:** Multiple DDL operations on same resource
**Solution:**

1. Wait for current DDL to complete
2. Retry with exponential backoff
3. Execute DDL operations sequentially

### Error: OCC / serialization failure ("could not serialize access" / "concurrent update")

**Cause:** Two concurrent transactions wrote to overlapping rows. DSQL uses optimistic concurrency
control — the loser of the race is aborted at COMMIT time and MUST be retried.

**Solution:**

1. **Retry with backoff.** Wrap writes in a retry loop (exponential, jittered, capped at 3–5 attempts). Most OCC errors clear on the first retry once the conflicting transaction commits.
2. **Check for hot keys.** If retries persist beyond a couple of attempts, the workload likely concentrates writes on a small set of keys. Diagnostics:
   - Run the query with `EXPLAIN ANALYZE` (Workflow 8) and inspect node-level row counts.
   - Cross-reference against the [scaling-guide.md "Hot Keys"](auth/scaling-guide.md) section.
3. **Reduce write fan-in.** Common fixes: introduce per-shard counters instead of a global one, batch writes by tenant rather than mixing tenants in one transaction, partition heavy-write tables by a high-cardinality dimension.

If the workload genuinely requires strict serial writes on the same key, accept the OCC retry cost
or move that subset to a different consistency primitive — DSQL's contract is optimistic.

## Protocol Compatibility

**Problem**: Some PostgreSQL clients send unsupported protocol messages.

**Solution**:

- Use officially tested drivers and connectors from the [Aurora DSQL connectivity tools page](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/aws-sdks.html)
- Test client compatibility before production deployment
