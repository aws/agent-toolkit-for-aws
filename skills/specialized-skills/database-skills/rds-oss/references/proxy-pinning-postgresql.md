# PostgreSQL RDS Proxy Pinning Risks

RDS Proxy for PostgreSQL uses connection multiplexing at the session level. Certain PostgreSQL features create session state that prevents the proxy from reusing backend connections.

## High Pinning Risk (defeats proxy purpose)

| Pattern | Why It Pins | Diagnostic Query |
|---------|-------------|------------------|
| Prepared statements (PREPARE/EXECUTE) | Server-side prepared state is session-scoped | `SELECT name, statement FROM pg_prepared_statements;` (run per-session) |
| Advisory locks (pg_advisory_lock) | Lock is held on a specific backend | `SELECT * FROM pg_locks WHERE locktype = 'advisory';` |
| LISTEN/NOTIFY | LISTEN registers on a specific backend connection | `SELECT * FROM pg_listening_channels();` |
| SET (session parameters) | e.g., `SET search_path`, `SET work_mem` — session-scoped | `SHOW search_path;` — if app sets this per-connection, every connection pins |
| Temporary tables | Session-scoped, can't be transferred | Check application code for `CREATE TEMP TABLE` |
| DECLARE CURSOR WITH HOLD (without CLOSE) | Holdable cursor survives the transaction and is session-scoped | Check for open holdable cursors: `SELECT * FROM pg_cursors WHERE is_holdable = true;` |
| Sequence manipulation (CURRVAL) | CURRVAL depends on session's last NEXTVAL call | Check application code for `CURRVAL()` usage |

## Medium Pinning Risk

| Pattern | Notes |
|---------|-------|
| SET LOCAL (transaction-scoped) | Pins only for transaction duration. Less impactful than SET (session). |
| SAVEPOINT | Pins for transaction duration. Fine if transactions are short. |
| Large result sets with cursors | Pins until cursor is closed. Use LIMIT/OFFSET instead. |
| SET ROLE / SET SESSION AUTHORIZATION | Pins for session duration. |

## Low / No Pinning Risk

| Pattern | Notes |
|---------|-------|
| Simple queries (SELECT, INSERT, UPDATE, DELETE) | No session state. Full multiplexing. |
| Autocommit single statements | No pinning. |
| PL/pgSQL functions (without session state) | Executed server-side, no pinning. |
| COPY (bulk load) | No pinning after completion. |

## PostgreSQL-Specific Gotchas

### search_path
Many ORMs and frameworks set `search_path` per connection. This pins every connection. Mitigation:

- Set `search_path` in the proxy's init query instead of per-connection
- Or set it in the PostgreSQL parameter group as the default

### Extended query protocol
PostgreSQL's extended query protocol (Parse/Bind/Execute) creates server-side prepared statements implicitly. Many drivers (libpq, JDBC, node-postgres) use this by default. This causes pinning.

Mitigation:

- JDBC: set `prepareThreshold=0` to disable server-side prepared statements
- node-postgres: avoid passing a `name` property in query config objects (named queries create persistent server-side prepared statements that pin connections)
- Python psycopg2: uses simple query protocol by default (no pinning)
- Python psycopg3: uses extended protocol by default (pins) — set `prepare_threshold=None`

### PgBouncer vs RDS Proxy
If already using PgBouncer in transaction mode, RDS Proxy adds little value — both do connection multiplexing. RDS Proxy's advantage is managed infrastructure + IAM auth + automatic failover handling. But PgBouncer in transaction mode is more aggressive at multiplexing (no pinning on SET).

## Diagnostic: Check Pinning Potential

Run these on the database to estimate pinning risk before deploying proxy:

```sql
-- Check for advisory locks
SELECT COUNT(*) AS advisory_locks FROM pg_locks WHERE locktype = 'advisory';

-- Check for active LISTEN channels
SELECT COUNT(*) AS listen_channels FROM pg_listening_channels();

-- Check for prepared statements (current session — ask app team to check during peak)
SELECT COUNT(*) AS prepared_stmts FROM pg_prepared_statements;

-- Check for temp tables in current sessions
SELECT COUNT(*) AS temp_tables FROM pg_class WHERE relpersistence = 't';

-- Check for open cursors
SELECT COUNT(*) AS open_cursors FROM pg_cursors WHERE is_holdable = true;
```

## Mitigation Strategies

1. Move search_path to proxy init query or parameter group default
2. Disable server-side prepared statements in the driver (see above)
3. Replace advisory locks with application-level locking (Redis, DynamoDB)
4. Replace LISTEN/NOTIFY with SQS, SNS, or EventBridge
5. Avoid DECLARE CURSOR WITH HOLD — use LIMIT/OFFSET or keyset pagination
6. Keep transactions short to minimize pin duration
