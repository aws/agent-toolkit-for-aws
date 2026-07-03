# MySQL/MariaDB RDS Proxy Pinning Risks

Pinning means the proxy locks a frontend connection to a specific backend database connection, preventing multiplexing. When pinned, the proxy can't reuse that backend connection for other clients, reducing the benefit of connection pooling.

## High Pinning Risk (defeats proxy purpose)

| Pattern | Why It Pins | Diagnostic Query |
|---------|-------------|------------------|
| Prepared statements (server-side) | Proxy can't move prepared state between backends | `SHOW GLOBAL STATUS LIKE 'Com_stmt_prepare';` — if high, pinning is frequent |
| SET SESSION variables | Session state is backend-specific | `SELECT s.VARIABLE_NAME, s.VARIABLE_VALUE AS session_val, g.VARIABLE_VALUE AS global_val FROM performance_schema.session_variables s JOIN performance_schema.global_variables g USING (VARIABLE_NAME) WHERE s.VARIABLE_VALUE <> g.VARIABLE_VALUE;` — rows where session differs from global indicate a `SET SESSION` was issued |
| User-defined variables (`@var`) | Session-scoped, can't be transferred | Check application code for `SET @var = ...` patterns |
| LOCK TABLES | Explicit lock is backend-specific | `SHOW GLOBAL STATUS LIKE 'Com_lock_tables';` |
| GET_LOCK() / RELEASE_LOCK() | Advisory locks are session-scoped | Check application code for `GET_LOCK()` usage |
| Temporary tables | `CREATE TEMPORARY TABLE` is session-scoped | `SHOW GLOBAL STATUS LIKE 'Created_tmp_tables';` — high values indicate risk |
| FOUND_ROWS() | Depends on previous query's state | Check application code |

## Medium Pinning Risk

| Pattern | Notes |
|---------|-------|
| SET NAMES / SET CHARACTER SET | Pins if different from proxy default. Configure proxy default charset to match app. |
| SET TRANSACTION ISOLATION LEVEL | Pins for the duration of the transaction |
| Multi-statement transactions | Pinned for transaction duration (expected, not a problem if transactions are short) |

## Low / No Pinning Risk

| Pattern | Notes |
|---------|-------|
| Simple SELECT/INSERT/UPDATE/DELETE | No session state. Full multiplexing. |
| Autocommit single statements | No pinning. |
| Connection attributes | Proxy handles these transparently. |

## Diagnostic: Check Current Pinning Rate

If RDS Proxy is already deployed, check pinning via CloudWatch:

- `ClientConnectionsSetupSucceeded` vs `DatabaseConnectionsCurrentlySessionPinned`
- Pinning rate = pinned / total × 100
- If > 30%, proxy benefit is significantly reduced

## Mitigation Strategies

1. Move prepared statements to client-side (use `useServerPrepStmts=false` in JDBC)
2. Avoid SET SESSION — use proxy's default connection init query instead
3. Keep transactions short to minimize pin duration
4. Avoid temporary tables — use CTEs or subqueries instead
5. Replace GET_LOCK() with application-level locking (Redis, DynamoDB)
