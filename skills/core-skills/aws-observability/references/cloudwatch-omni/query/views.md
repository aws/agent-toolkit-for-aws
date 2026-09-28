# Omni Views Reference

Views in CloudWatch Omni are named SQL queries that can be referenced as tables. They allow reusing common query logic without repeating it — use `FROM view.<name>` in any query to inline the view's stored SQL.

## 1. Using Views in Queries

Reference a view by its name with the `view.` prefix in the FROM clause:

```sql
SELECT `@timestamp`, `@record`
FROM view.my_error_logs
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
ORDER BY `@timestamp` DESC
```

Views behave like inline subqueries:

- They **inherit the outer query's `@timestamp` bounds** — no need to specify a time range inside the view definition
- They can be used anywhere a table is used: JOINs, subqueries, UNION, etc.
- They can reference other views (up to 32 levels of nesting)
- Cyclic references (a view referencing itself, directly or transitively) are detected and rejected
- The view's SQL is re-evaluated fresh on every query execution (not cached results)

### Views in JOINs

```sql
SELECT e.`@timestamp`, e.`@record`
FROM view.error_logs AS e
INNER JOIN view.slow_traces AS s
  ON e.traceId = s.traceId
WHERE e.`@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
  AND s.`@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

### Composing Views (nested)

A view can reference other views in its definition:

```sql
-- If view.base_errors is defined as (projecting severityNumber so it is exposed
-- as a bare top-level column the composed view can narrow on):
--   SELECT `@timestamp`, `@record`, severityNumber FROM logs.default WHERE TRY_CAST(severityNumber AS BIGINT) >= 17
-- Then another view can build on it (a composed view may only narrow on bare
-- top-level columns — see "Views expose only bare top-level columns" in section 4):
--   SELECT * FROM view.base_errors WHERE TRY_CAST(severityNumber AS BIGINT) >= 21
-- And queries can reference the composed view:
SELECT COUNT(*) FROM view.fatal_errors
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

> **Verify field names before filtering or grouping.** An unknown or mistyped top-level column resolves to NULL silently — no error is raised — so a wrong field name matches zero rows. Confirm the real field names for your data with `EXPLAIN (ANALYZE_FIELDS)`, as described in [sql-logs-traces.md](sql-logs-traces.md#5-schema-discovery), before referencing them in a view.

## 2. Managing Views

### CreateView

Creates a new named view.

| Parameter | Required | Description |
|---|---|---|
| `name` | Yes | View name. Must match `^view\.[a-z0-9][a-z0-9_-]{0,250}$` and be **6–256 characters** total. It **must start with the lowercase prefix `view.`**, the first character after `view.` must be alphanumeric (`[a-z0-9]`), and the remaining characters use the lowercase set `[a-z0-9_-]` (letters, digits, hyphen, underscore) — a **second `.` is NOT allowed** (only the `view.` prefix contains a dot), and **uppercase is NOT allowed**. A **user** view **must not start with `view.aws.`** (reserved for AWS-managed views) |
| `definition` | Yes | A single SQL SELECT statement |
| `description` | No | Human-readable description of the view's purpose |
| `tags` | No | Tag map. `CreateView` is the only view operation that takes tags |
| `clientToken` | No | Idempotency token, 1–64 chars |

Example:

```
CreateView
  name: "view.error_logs_last_hour"
  definition: "SELECT `@timestamp`, `@record` FROM logs.default WHERE TRY_CAST(severityNumber AS BIGINT) >= 17"
  description: "All error-level log entries"
```

### UpdateView

Updates an existing view's definition and/or description.

| Parameter | Required | Description |
|---|---|---|
| `name` | Yes | The view name to update |
| `definition` | No | New SQL SELECT statement |
| `description` | No | New description |

A new `definition` replaces the old one in place, changing results for everything that
reads the view. Draft the change and confirm with the user before calling `UpdateView`.

### DeleteView

Deletes a view by name.

| Parameter | Required | Description |
|---|---|---|
| `name` | Yes | The view name to delete |

**Confirm before deleting.** Deleting a view is a destructive write and cannot be
undone — any saved query or dashboard panel that reads `FROM view.<name>` breaks once
it is gone. Name the specific view and confirm with the user before calling `DeleteView`;
do not delete on inference.

### ListViews

Lists views in the account, optionally filtered by `type` (`USER` | `MANAGED`); paginated with `maxResults` (1–100) and `nextToken`. Each `ViewSummary` carries `name`, `type` (`USER` | `MANAGED`), `description`, `createdAt` and `updatedAt`. View definitions are not included — call `GetView` for the SQL. There is no `scope` field.

### GetView

Gets a single view by name. Returns `name`, `type` (`USER` | `MANAGED`), `description`, `definition`, `createdAt`, `updatedAt`, and `arn`. There is no `scope` field.

## 3. View Naming Rules

View names must match `^view\.[a-z0-9][a-z0-9_-]{0,250}$` and be **6–256 characters** total:

- Must start with the lowercase prefix `view.`
- A **user** view must not start with `view.aws.` — that prefix is reserved for managed/curated views provided by AWS
- The first character after `view.` must be alphanumeric (`[a-z0-9]`)
- The remaining characters use the lowercase set `[a-z0-9_-]` (letters, digits, hyphen, underscore) — a **second `.` is NOT allowed** (only the `view.` prefix contains a dot), and **uppercase is NOT allowed**

Although a hyphen is legal in a view name, an unquoted hyphenated identifier in a `FROM` clause parses as subtraction (`view.checkout-slow` reads as `view.checkout` minus `slow`), so a hyphenated name must be quoted or escaped when referenced — which is why the examples below use underscores.

Examples of valid names:

- `view.my_error_logs`
- `view.checkout_slow_requests`
- `view.team_dashboard_metrics`

Examples of invalid names:

- `view.checkout.slow-requests` (a second dot is not allowed)
- `view.Checkout` (uppercase not allowed)

## 4. View Definition Rules

- Must be a single SQL SELECT statement
- Cannot contain multiple statements (no semicolons)
- Can reference any SQL table: `logs.default`, `traces.default`, `default`. Metrics are not SQL and cannot be wrapped in a view — they are queried with PromQL (see [promql-metrics.md](promql-metrics.md))
- Can reference other views: `FROM view.other_view`
- Does NOT need its own `@timestamp` filter — it inherits from the outer query
- Can include any supported SQL: JOINs, CTEs, window functions, aggregations, etc.

### Views expose only bare top-level columns

A view's schema is limited to **bare top-level columns** — `@timestamp`, `@record`, and simple columns such as `severityNumber`, `name`, or `durationNano` (optionally wrapped in `CAST`/functions or given an alias). A view definition **cannot** reference a nested map or struct field with bracket access — `resource['attributes'][...]`, `status['code']`, `attributes[...]` — and a view does **not** expose those fields to the outer query either. Both fail to bind at planning:

```
Failed to bind view `view.<name>`: Schema error: No field named resource.
Valid fields are "@timestamp", "@record", "severityNumber".
```

This holds even when the nested field is aliased in the view's SELECT (`status['code'] AS status_code` still fails to bind), and even when the outer query — not the view — does the bracket access over the view. The **same** bracket access works fine in a *direct* query against `logs.default` / `traces.default` / `default`; the restriction is specific to view definitions and to querying through a view. So to filter or group by a nested field (a service name, an environment, a span status code), query the base table directly rather than wrapping it in a view.

## 5. Constraints

- Maximum **100 views per account**
- Maximum nesting depth: **32 levels** (views referencing views referencing views...)
- Cyclic references are rejected (a → b → a, or a → a)
- `view.aws.*` prefix is reserved (cannot create or modify)

## 6. Common Patterns

### Encapsulate a filtered subset

A view definition may only reference bare top-level columns (see [Views expose only bare top-level columns](#views-expose-only-bare-top-level-columns)), so encapsulate the part of the filter that uses one — here the error-severity threshold:

```
CreateView
  name: "view.severe_logs"
  definition: "SELECT `@timestamp`, `@record` FROM logs.default WHERE TRY_CAST(severityNumber AS BIGINT) >= 17"
```

Query the view for a running count of severe logs:

```sql
SELECT COUNT(*) AS error_count
FROM view.severe_logs
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

To group or filter those errors by a nested field — a service name or an environment — query the base table directly, because a view cannot reference a nested map field. Group severe-log counts by environment (`COALESCE` covers both attribute keys, `deployment.environment.name` and `deployment.environment`):

```sql
SELECT COUNT(*) AS error_count,
       COALESCE(resource['attributes']['deployment.environment.name'],
                resource['attributes']['deployment.environment']) AS environment
FROM logs.default
WHERE TRY_CAST(severityNumber AS BIGINT) >= 17
  AND `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
GROUP BY COALESCE(resource['attributes']['deployment.environment.name'],
                  resource['attributes']['deployment.environment'])
ORDER BY error_count DESC
```

### Correlate errors across logs and traces

A log error (`severityNumber`) and a span error (`status['code']`) live on different planes but share the unified `default` table. The span-error test reads the nested `status` field, so this cannot be a view (see [Views expose only bare top-level columns](#views-expose-only-bare-top-level-columns)) — run it as a direct query:

```sql
SELECT COUNT(*) AS error_count
FROM default
WHERE (TRY_CAST(severityNumber AS BIGINT) >= 17
       OR upper(TRY_CAST(status['code'] AS VARCHAR)) IN ('2', 'ERROR', 'STATUS_CODE_ERROR'))
  AND `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

### Create a view for slow spans

`name` and `durationNano` are bare span columns, so this filter and projection can live in a view. The span's service lives in the nested `resource` map, which a view cannot expose, so it is not selected here — join or read it in a direct query if you need it:

```
CreateView
  name: "view.slow_spans"
  definition: "SELECT `@timestamp`, name, CAST(durationNano AS DOUBLE) / 1e6 AS duration_ms FROM traces.default WHERE durationNano IS NOT NULL AND CAST(durationNano AS DOUBLE) > 2e9"
```

Then alert or dashboard on it:

```sql
SELECT `@timestamp`, name, duration_ms
FROM view.slow_spans
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
ORDER BY duration_ms DESC
LIMIT 50
```
