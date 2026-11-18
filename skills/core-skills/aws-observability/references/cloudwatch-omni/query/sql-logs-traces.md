# Omni Query Syntax Reference

The SQL dialect for querying logs and traces in CloudWatch Omni. Both Omni experiences — **Application Observability** (APM, distributed tracing, log analysis) and **Agent Observability** (LLM/AI agent monitoring) — use this same SQL query surface. All queries are read-only `SELECT` statements.

**The SQL syntax is identical whether you query logs or traces.** They share the exact same grammar, functions, quoting rules, and constraints. The *only* difference between tables is the data they contain — that is, which fields are present. This reference documents the dialect once, covering logs and traces in Omni.

> **The schema is dynamic and varies across the data.** All telemetry for an account (logs, traces, metrics) is stored in Omni, and different applications, services, or telemetry types will have completely different field structures. One application's logs may have fields that another's does not. The *only* fields guaranteed to exist on every record are the `@`-prefixed system fields documented below. Before writing a query that references any other field, discover the actual schema by narrowing to the relevant slice of data with `EXPLAIN (ANALYZE_FIELDS)` (see [Schema Discovery](#5-schema-discovery)).

---

## 0. Running a Query

A statement is executed with these three operations, in order — there is no single
"execute query" call:

1. **`StartTelemetryQuerySession`** → returns a `sessionId`. One session carries many
   queries; reuse it rather than opening one per statement.
2. **`StartTelemetryQuery`** with `sessionId` + `queryString` (the SQL below) → returns a
   `queryId`. A statement that cannot be planned fails **here**, with the schema or parse
   error in the response.
3. **`GetTelemetryQueryResults`** with `queryId` — and **only** `queryId`; passing
   `sessionId` too is rejected as an unknown parameter. Poll it until `status` is
   `Complete` (results in `rows`) or `Failed`. A fresh query needs a moment: expect an
   in-progress status before the first `Complete`.

A session is closed with `StopTelemetryQuerySession`, and a long-running query with
`StopTelemetryQuery`. Sessions expire on their own; a reused `sessionId` that has gone
stale fails with `Session has been terminated. Please call StartSession to create a new
session.`, which means open a new session, not that the SQL is wrong.

In the AWS CLI these are `aws cloudwatchomni start-telemetry-query-session`,
`start-telemetry-query` and `get-telemetry-query-results`. The same three operations run
the queries in [views.md](views.md); see
[programmatic-access.md](../programmatic-access.md) for client setup and versions.

---

## 1. Tables & Addressing

| Table Reference | Contents |
|---|---|
| `default` | Logs + traces combined |
| `logs.default` | Logs only — syntactic sugar for `WHERE \`@telemetry_type\` = 'logs'` |
| `traces.default` | Traces/spans only — syntactic sugar for `WHERE \`@telemetry_type\` = 'traces'` |

Each `<type>.default` form is simply a convenience filter on `` `@telemetry_type` ``. Querying `default` and adding `WHERE \`@telemetry_type\` = 'logs'` is equivalent to querying `logs.default`.

Agent-evaluation scores (`gen_ai.evaluation.*`) are **log records in `logs.default`**, never
span columns on `traces.default`; filtering on them against `traces.default` returns zero rows
without error, indistinguishable from "no evaluations ran" — see agent-evaluation.md's "Query
surface" section.

**Metrics are not in this table.** Metrics are not SQL — they are queried with PromQL, and there is no `metrics.default` `FROM` target. Classic CloudWatch metrics (custom metrics, vended metrics without OTel enrichment, and usage metrics such as `AWS/Logs` `IncomingBytes`) are not in CloudWatch Omni at all: Omni's PromQL surface has no `GetMetricData` or Metrics Insights route behind it. Counting or sizing records in `logs.default` does not reproduce them, so do not offer it even as an approximation; read them in CloudWatch ([promql-metrics.md](promql-metrics.md), §1). See [../../cloudwatch/promql.md](../../cloudwatch/promql.md) for the PromQL surface, label conventions, and per-service metric catalog.

**FROM clause quoting is flexible** — all of these are equivalent:

```sql
SELECT * FROM logs.default WHERE ...
SELECT * FROM "logs.default" WHERE ...
SELECT * FROM "logs"."default" WHERE ...
```

The dot-separated form (`logs.default`) is the most common. Use whichever you prefer.

---

## 2. Required Time Range

Every query **must** include a filter on `` `@timestamp` ``. Queries without a time-range filter are rejected.

- `` `@timestamp` `` values are **timestamps**
- **On a span, `` `@timestamp` `` is the span END time** (`endTimeUnixNano`), not the start.
  A window that only brackets when a request *started* therefore excludes every span of that
  request that finished after the window closed — typically the slow root or client span that
  carries the error — and the query still completes normally, returning the fast child spans
  as if they were the whole trace. When fetching a whole trace or correlating by `traceId`,
  push the upper bound out by the longest span duration you expect (a span that ran for ten
  minutes is stamped ten minutes after it started).
- When self-joining, the `` `@timestamp` `` filter is required on **both** sides of the join

**Relative time range:**

```sql
SELECT `@timestamp`, `@record`
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

**Absolute time range:**

```sql
SELECT `@timestamp`, `@record`
FROM default
WHERE `@timestamp` BETWEEN to_timestamp_nanos('2026-08-20T15:25:48.000Z')
                        AND to_timestamp_nanos('2026-08-20T16:25:48.000Z')
```

INTERVAL syntax: a quoted number followed by the time unit — `MINUTE`/`MINUTES`, `HOUR`/`HOURS`, or `DAY`/`DAYS`. Example: `INTERVAL '30 MINUTE'`, `INTERVAL '2 HOURS'`, `INTERVAL '7 DAYS'`.

**Debugging a rejected or empty query (the three things that surprise people, together):**

- **The time filter is mandatory.** A query with no `` `@timestamp` `` bound is rejected outright. This is the most common cause of a "why was this rejected?".
- **`SELECT *` is not the wide row you expect.** It collapses to `` `@timestamp`, `@record` `` (see [System Fields](#3-system-fields)), not every discovered column.
- **A bare top-level field name is often wrong.** A name like `service` or `host` is usually a *nested* resource attribute reached with bracket notation (e.g. `` resource['attributes']['service.name'] ``). Under the permissive schema, a field that does not exist **silently returns NULL** instead of erroring (see [Field Access](#4-field-access--quoting)), so a mistyped or wrong-level name gives empty results rather than a rejection.

---

## 3. System Fields

These `@`-prefixed fields are the **only** fields guaranteed to exist on every record, regardless of telemetry type or what was ingested. Everything else is dynamic.

| Field | Description |
|---|---|
| `` `@timestamp` `` | Mandatory filter field. Every query must constrain this. **On a span it is the span END time** (`endTimeUnixNano`), not the start — see the note in [Required Time Range](#2-required-time-range). |
| `` `@record` `` | All user-visible data as JSON. Contains the full record structure. |
| `` `@message` `` | Original ingestion payload. Permission-gated — may not be available to all users. A grant can exclude `@message` itself (masked in `SELECT`, rejected in `WHERE`). Excluding a structured field does not redact its value inside `@message`; see [Translating CWL Insights `parse` to SQL](#translating-cwl-insights-parse-to-sql). |
| `` `@ingest_time` `` | When the record was ingested. |
| `` `@telemetry_type` `` | The record's telemetry type, e.g. `'logs'` or `'traces'`. |

The following system fields are present when the data source provides them:

| Field | Description |
|---|---|
| `` `@aws.account` `` | The AWS account where the data was originally ingested. |
| `` `@aws.region` `` | The AWS region where the data was originally ingested. |
| `` `@data_source_name` `` | Identifies the source of the data (e.g., `"amazon_vpc"`). See [AWS data sources](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/supported-aws-services-data-sources.html) and [third-party data sources](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/supported-third-party-sources-data-sources.html). |
| `` `@data_source_type` `` | The type of data source (e.g., `"flow"`). See [AWS data sources](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/supported-aws-services-data-sources.html) and [third-party data sources](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/supported-third-party-sources-data-sources.html). |
| `` `@data_format` `` | The format of the ingested data (e.g., `"VPC_FLOW_LOGS"`). |
| `` `@logGroupName` `` | The CloudWatch log group name (e.g., `"/aws/vpcflowlogs/vpc-xxx"`). |
| `` `@logStream` `` | The CloudWatch log stream name. |

Within the same `@data_source_name` and `@data_source_type` (or `@data_format`), the schema is mostly stable and publicly documented. It is worth browsing the relevant AWS service documentation externally for detailed field definitions.

**Important:** `SELECT *` collapses to `` `@timestamp`, `@record` ``.

---

## 4. Field Access & Quoting

### Top-level fields

- Plain identifiers work for simple field names: `SELECT myField FROM ...`
- Fields starting with `@` or containing special characters (`.`, `-`) MUST be backtick-quoted: `` `@timestamp` ``, `` `field-name` ``
- Unquoted `@`-prefixed fields are rejected with an error about variable references

```sql
-- Correct
SELECT `@message`, `@timestamp` FROM default WHERE ...

-- WRONG — will fail
SELECT @message, @timestamp FROM default WHERE ...
```

### Nested field access (bracket notation)

When JSON with nested objects is ingested, navigate into nested values using the root-level field name followed by bracket notation with string literals:

```sql
-- Given ingested JSON: { "request": { "method": "GET", "url": "/api" } }
SELECT request['method'], request['url']
FROM logs.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

**Key rules:**

- The root-level field is referenced as-is (or backtick-quoted if it has special characters)
- Nested keys use `['key']` with single-quoted string literals
- Special characters inside the bracket string are fine — no backticks needed there:

```sql
-- Given ingested JSON: { "attrs": { "http.method": "GET", "service-name": "api" } }
SELECT attrs['http.method'], attrs['service-name']
FROM logs.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

- Multiple nesting levels chain brackets: `root['level1']['level2']`

The field names shown here are **examples of the syntax**. The actual fields present depend entirely on the ingested data — use [Schema Discovery](#5-schema-discovery) to find what exists.

**Permissive schema:** Referencing a field that doesn't exist in the data will **silently return NULL** rather than producing an error. This means typos in field names won't fail your query — they'll just give empty results. Always verify field names via schema discovery if results look unexpectedly empty.

**An alias-qualified bracket path resolves to NULL.** With a table alias in scope,
`t.attributes['k']` and `t.resource['attributes']['k']` return NULL everywhere — in
`SELECT`, in `WHERE` and in a `JOIN ... ON` — while the same path written **without** the
alias returns the value. Measured on one query over `traces.default`:
`COUNT(t.attributes['session.id'])` = 0 against `COUNT(attributes['session.id'])` =
122,670. Nothing errors, so a join written the qualified way silently matches zero rows.
Write bracket paths unqualified, or project the nested field to a flat alias in a CTE or
derived table first and refer to that alias. Alias-qualifying a top-level column
(`` t.`@timestamp` ``, `t.name`) is unaffected.

**An all-NULL column from a query that ran is a signal to verify the field name before
concluding the data is absent — not proof the name is wrong.** A correctly-named field can
legitimately be NULL across every matching record, so rule out the three ways a field name
can be wrong first:

- **Misspelled or non-existent field** — permissive schema returns NULL, not an error.
  Re-discover the real names with [Schema Discovery](#5-schema-discovery).
- **A root-level field quoted wrong** — a field starting with `@` or containing a `.`/`-` MUST
  be backtick-quoted, and an *unquoted* `@`-prefixed field does not run empty — it is *rejected*
  with a variable-reference error. So a query that ran at all had its `@`-fields quoted
  correctly; the emptiness is in some non-`@` field.
- **A nested key over-quoted** — inside bracket notation the key is a plain single-quoted
  string; special characters *inside* the bracket string need no backticks
  (`attrs['http.method']`). Adding backticks there changes the key and silently returns NULL.

---

## 5. Schema Discovery

The schema is dynamic — it reflects what has been ingested, not a fixed definition. Since all telemetry for an account is stored together, different applications and services will have completely different fields. A query against all data will show the union of every application's schema, which is rarely useful. **Always narrow discovery to a specific telemetry type or application** to get a meaningful result. Aside from the `@`-prefixed [system fields](#3-system-fields), you cannot assume any field exists.

**Method 1: `EXPLAIN (ANALYZE_FIELDS)`** — the primary schema discovery mechanism

```sql
EXPLAIN (ANALYZE_FIELDS)
SELECT `@record`
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

Returns per-field type descriptors with sample values. It can be narrowed with `WHERE` filters to scope discovery to a specific time range or subset of data:

```sql
EXPLAIN (ANALYZE_FIELDS)
SELECT `@record`
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
  AND attributes['your.filter.key'] = 'some-value'
```

Whenever you are unsure about a field name, run `ANALYZE_FIELDS` first. The available fields depend entirely on what was instrumented and ingested.

**Method 2: `SELECT @record`**

```sql
SELECT `@record`
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '15 MINUTES' AND NOW()
LIMIT 10
```

Returns the full JSON structure of each record, showing all available fields for that record.

**Method 3: `ListTelemetryFields` API**

Call the `ListTelemetryFields` API to enumerate known fields for a data set and telemetry type (`LOGS` or `TRACES` — metrics are not listed; see [promql-metrics.md](promql-metrics.md)). It takes `dataSetName`, `telemetryType`, and optional `startTime`/`endTime`; each entry is `{name, children}`. A `nextToken` member is reserved in the shape but the service does not page today — it is always null, so read the whole field list from the single response and do not loop on it.

---

## 6. Supported SQL Operations

Only `SELECT` statements are allowed. All DDL (`CREATE`, `ALTER`, `DROP`) and DML (`INSERT`, `UPDATE`, `DELETE`) are blocked.

**Clauses:**

- `SELECT` (with column expressions, aliases)
- `FROM` (single table or JOINs)
- `WHERE` (must include `` `@timestamp` ``)
- `GROUP BY`
- `HAVING` (post-aggregation filter)
- `ORDER BY` (ASC/DESC, multiple columns)
- `LIMIT` — default is **10,000** if omitted
- `DISTINCT`

**Joins** — on base tables the outer joins need the **`OUTER`** keyword spelled out:

- `INNER JOIN` (and bare `JOIN`)
- `LEFT OUTER JOIN` — **not** `LEFT JOIN`
- `RIGHT OUTER JOIN` — **not** `RIGHT JOIN`
- `FULL OUTER JOIN`

The short `LEFT JOIN` / `RIGHT JOIN` spellings are rejected against base tables, and the
error blames a column rather than the keyword: `Schema error: No field named a."spanId".
Valid fields are a."@timestamp", b."@timestamp".` — every non-time column vanishes from
the reported schema, so it reads as a missing field. Add `OUTER` and the identical
`ON`/`WHERE` runs unchanged.

**Subqueries & Composition:**

- Common Table Expressions (WITH clause): `WITH name AS (SELECT ...) SELECT ... FROM name`
- Subqueries: `IN (SELECT ...)`, `EXISTS (SELECT ...)`, derived tables `FROM (SELECT ...) AS t`
- Set operations: `UNION`, `UNION ALL`, `INTERSECT`, `EXCEPT`

**Window functions:**

- `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)`
- `RANK() OVER (...)`
- Aggregate functions with `OVER (PARTITION BY ... ORDER BY ...)`
- **A window's `PARTITION BY` / `ORDER BY` takes a column or an alias, never a bracket
  path.** `PARTITION BY attributes['http.method']` is rejected with `Schema error: No
  field named attributes. Valid fields are "@timestamp", attributes` — an error that
  names nothing wrong in the query. Project the nested field in a CTE or derived table
  first and partition by that alias (see the running-count pattern in §8). Top-level
  columns (`kind`, `name`) work directly.

**Expressions:**

- `CASE WHEN ... THEN ... ELSE ... END`
- `LIKE` / `NOT LIKE`
- `IN (value1, value2, ...)`
- `BETWEEN ... AND ...`
- `IS NULL` / `IS NOT NULL`
- `CAST(expr AS type)`
- `TRY_CAST(expr AS type)` — returns NULL instead of failing on invalid conversion
- Arithmetic: `+`, `-`, `*`, `/`

### Estimating Scan Volume (EXPLAIN (ESTIMATE))

`EXPLAIN (ESTIMATE)` returns an **upper bound** on the bytes a query would scan, without
running the query. The estimate itself is not billed — its own `statistics.bytesScanned` is
`0` — so it is the safe first step before a query that may scan a lot.

```sql
EXPLAIN (ESTIMATE)
SELECT `@timestamp`, `@message`
FROM logs.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '7 DAYS' AND NOW()
  AND `@message` LIKE '%timeout%'
```

It runs through the same three operations as any statement
([Running a Query](#0-running-a-query)). The result is **exactly one row with one column,
`estimated_bytes`**: a non-negative integer, delivered as a string like every value in `rows`.

| Form | Behavior |
|---|---|
| `EXPLAIN (ESTIMATE)` or `EXPLAIN (ESTIMATE QUICK)` | The default. Returns in about a second. Can sit far above the real scan, and re-running the same statement can return a different number |
| `EXPLAIN (ESTIMATE ACCURATE)` | Takes seconds, longer on a wide range. Usually much closer to the real scan, and returns the same number for the same data — but it is not guaranteed to be lower than `QUICK` |

Use `QUICK` for a fast order-of-magnitude check. Use `ACCURATE` when the number feeds a
decision, such as whether to run a query as written. Both figures are upper bounds, so when you
have both, the smaller one is the tighter bound — which can be `QUICK`, since `ACCURATE` is not
always the lower of the two.

**Facts you MUST surface when reporting an estimate:**

- **It is an upper bound, not a prediction.** The query scans at most about this much, and often
  much less: the estimate does not account for how selective the filters are, and a `LIMIT`
  above `0` does not lower it. Say "up to N GB", never "will scan N GB".
- **There is no accuracy guarantee.** Never quote a margin of error, and never present the
  number, or a price computed from it, as what the query will be billed — only as a worst case.
- **It is a byte count only** — not a row count, a result size, or a run time.
- **A price is a worst case, and its rate needs a source.** To turn the bytes into dollars, use
  the **"Query — logs and traces"** rate (per GB scanned) in the "Analyze in CloudWatch Omni"
  table of the CloudWatch Omni pricing page, <https://aws.amazon.com/cloudwatch/omni/pricing/> —
  never a rate from memory, and never the CloudWatch Logs Insights query rate on the general
  CloudWatch pricing page, which is a different product. That page lists US East (N. Virginia)
  prices and points to the CloudWatch pricing page for other Regions. Name the page as the rate's
  source in the answer ("$X per GB scanned, from the CloudWatch Omni pricing page; check it for
  the current rate"), call the product a worst-case cost, and state the included query allowance
  that row lists, which can bring the real charge to zero.
- **The real figure arrives after the run.** When the query does run, its `statistics.bytesScanned`
  in `GetTelemetryQueryResults` reports what it actually scanned. Compare against that.
- **A relative window moves.** `NOW() - INTERVAL …` covers different data each time it is
  evaluated, so data that arrives between the estimate and the run is not in the estimate.
- **It is not comparable with a `MAX_VOLUME` budget.** A budget caps declared uncompressed bytes
  before pruning (see [Table Sampling](#table-sampling-tablesample));
  `estimated_bytes` is a different quantity. Never tell the user that a budget set from an
  estimate will scan exactly, or at most, that much.

**Joins, unions, subqueries, CTEs and views are estimated like any query.** The estimate is the
sum over every table occurrence the query reads, so a self-join — or the same view referenced
twice — counts its data twice, as the real query scans it twice. A `FROM view.<name>` query is
estimated over the tables the view reads.

**Rejected forms** — each fails at `StartTelemetryQuery` with the message shown:

| Form | Error |
|---|---|
| `EXPLAIN ESTIMATE <query>` (no parentheses) | `EXPLAIN ESTIMATE is not supported; use EXPLAIN (ESTIMATE) <query>.` |
| Any other `EXPLAIN` option alongside it — `(ESTIMATE, ANALYZE_FIELDS)`, `(ANALYZE, ESTIMATE)` | `EXPLAIN (ESTIMATE) cannot be combined with other EXPLAIN options.` |
| `TABLESAMPLE` anywhere in the inner query | `TABLESAMPLE cannot be combined with EXPLAIN (ESTIMATE).` — estimate the unsampled query instead |
| A `metrics.` table | `EXPLAIN (ESTIMATE) does not support metrics datastores.` — metrics are PromQL ([promql-metrics.md](promql-metrics.md)) |
| A mode other than `QUICK` or `ACCURATE` | ``Unknown ESTIMATE mode `<mode>`; use QUICK or ACCURATE.`` |

The inner query still needs its `` `@timestamp` `` bound ([Required Time Range](#2-required-time-range)).

**When to estimate first.** Before running a query that is likely to scan a lot — a window of
days rather than hours, no selective equality filter, a `LIKE` or `` `@record` `` scan, or a join
— estimate it, tell the user the bound in GB or TB, and when it is large offer:

1. a narrower time range or an added equality filter, then estimate again;
2. the same query with `TABLESAMPLE (… MAX_VOLUME)` to bound the scan (below);
3. running it as written.

Do not run the query until the user has chosen.

### Table Sampling (TABLESAMPLE)

`TABLESAMPLE` reduces the amount of data scanned by sampling a table reference. It is placed immediately after a table reference in the `FROM` clause.

**Syntax:** `TABLESAMPLE (<p> PERCENT)`, where `p` must satisfy `0 < p <= 100`. An extended form adds `MAX_VOLUME` and `BIAS` (below).

```sql
SELECT * FROM "logs.default" TABLESAMPLE (10 PERCENT)
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

**Per-occurrence / per-table** — each table reference carries its own independent sampling rate. In multi-datastore joins and self-joins, every occurrence is sampled separately:

```sql
SELECT a.`@timestamp` AS log_time, b.name AS span_name
FROM "logs.default" a TABLESAMPLE (10 PERCENT)
JOIN "traces.default" b TABLESAMPLE (50 PERCENT) ON a.traceId = b.traceId
WHERE a.`@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
  AND b.`@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
LIMIT 3
```

Project columns explicitly and qualify them, as above: `SELECT *` across two tables that
both expose `@timestamp` is rejected with `Schema error: Ambiguous reference to
unqualified field "@timestamp"` — the join itself is fine, the star is not. Join on a
field the two tables actually share (`traceId`), not a placeholder `id`.

**Behavior** — `TABLESAMPLE` returns an approximate sample, not an exact `p%` of rows: the returned row count is an approximation of the requested percentage. Sampling is repeatable — re-running the same query over the same time range returns the same sample.

**Supported tables** — `logs.` / `traces.` / bare `default`. It is **NOT** supported on `metrics.` tables.

**Rejection rules** — each of the following raises an explicit error:

- Combining with `EXPLAIN (ANALYZE_FIELDS)`.
- A percentage outside `(0, 100]`.
- `ROWS`, or a quantity with no unit at all — `PERCENT` and `MAX_VOLUME` are the only units.
- A sampling method name such as `BERNOULLI` / `SYSTEM`.
- `REPEATABLE` / `SEED` — sampling is deterministic and cannot be seeded.
- `BUCKET`.
- A non-numeric percentage.
- `TABLESAMPLE` in an unsupported position — a `SELECT`-list scalar subquery, a `HAVING` subquery, or a `JOIN ... ON` subquery. It **is** allowed on `FROM` relations, `WHERE` subqueries, derived tables, and `UNION` branches.
- Conflicting percentages on the same table occurrence.

#### MAX_VOLUME and BIAS — bounding a scan by bytes

Arguments are order-independent and each is optional, so a budget can stand alone — an omitted
percentage means `100`, an omitted bias means `SPREAD`:

```sql
SELECT `@timestamp`, `@record`
FROM "logs.default" TABLESAMPLE (100 PERCENT, 10G MAX_VOLUME, BIAS SPREAD)
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

| Argument | Meaning |
|----------|---------|
| `<n> MAX_VOLUME` | Ceiling on declared uncompressed bytes selected. Units `K` / `M` / `G` / `T`, optional `B`, base 1024; a bare number is bytes |
| `BIAS EARLIEST` / `BIAS LATEST` | Keep the earliest / latest part of the range at full time resolution |
| `BIAS SPREAD` | Keep the whole range and widen the stride instead (default) |

- **The budget is not the reported scan size.** It caps the declared uncompressed bytes of the
  *selected input*, counted before pruning; reported bytes scanned counts resolved files after
  pruning. The two are different quantities, so reported scan size can land either side of the
  budget. Never tell the user a budget means they will scan exactly, or at most, that much.
- **Recent data is not sampled.** Data still served from the ingest tier is scanned in full
  regardless of the sampling clause, and it counts toward reported bytes scanned.
- **Takes the tighter of the two bounds.** Given a percentage and a budget together, each is
  evaluated against the full candidate set and whichever selects fewer bytes is applied.
- **Manifest-granular.** Whole manifests are selected or skipped, so a budget is never met
  exactly. On skewed data it binds coarsely, and a budget below the smallest manifest can
  select nothing at all and reports `BELOW_MINIMUM_GRANULARITY`. Widen the budget or narrow
  the time range.
- Binds per table occurrence, exactly like the percentage form.

---

## 7. Functions Reference

### Conditional

- `COALESCE(a, b, ...)` — returns the first non-null argument
- `NULLIF(a, b)` — returns NULL if a = b, otherwise a
- `GREATEST(a, b, ...)` — returns the largest value
- `LEAST(a, b, ...)` — returns the smallest value
- `NVL(a, b)` — returns b if a is NULL (alias: IFNULL)

### Math

- `ABS(x)` — absolute value
- `CEIL(x)` — round up to integer
- `FLOOR(x)` — round down to integer
- `ROUND(x, n)` — round to n decimal places
- `POWER(base, exp)` — exponentiation
- `SQRT(x)` — square root
- `LN(x)` — natural log
- `LOG(base, x)` — logarithm
- `LOG10(x)` / `LOG2(x)` — base-10 / base-2 log
- `TRUNC(x, n)` — truncate to n decimal places
- `PI()` — pi constant
- `RANDOM()` — random float 0-1
- `safe_div(a, b)` — division returning NULL on divide-by-zero
- `width_bucket(value, min, max, n)` — histogram bucketing
- `clamp(value, min, max)` — clamp to range
- `sigmoid(x)` — sigmoid function

### String

- `length(s)` — string length
- `lower(s)` / `upper(s)` — case conversion
- `trim(s)` / `ltrim(s)` / `rtrim(s)` — whitespace removal
- `left(s, n)` / `right(s, n)` — first/last n characters
- `substr(s, start, len)` — substring extraction
- `concat(a, b, ...)` — concatenate strings
- `concat_ws(sep, a, b, ...)` — concatenate with separator
- `replace(s, from, to)` — replace occurrences
- `reverse(s)` — reverse a string
- `repeat(s, n)` — repeat string n times
- `split_part(s, delimiter, n)` — split and return part n (1-based)
- `strpos(s, substr)` — position of substring (1-based, 0 if not found)
- `position(substr IN s)` — same as strpos
- `starts_with(s, prefix)` / `ends_with(s, suffix)` — prefix/suffix check
- `contains(s, substr)` — substring existence check
- `lpad(s, len, pad)` / `rpad(s, len, pad)` — pad string
- `initcap(s)` — capitalize first letter of each word
- `parse_url(url, component)` — extract URL component (e.g., 'HOST', 'PATH')
- `url_decode(s)` / `url_encode(s)` — URL encoding
- `mask(s, ...)` — mask sensitive data

### Regex

- `regexp_match(s, pattern)` — array of the capture groups, NULL on no match; read with `array_element` (see [Translating CWL Insights `parse` to SQL](#translating-cwl-insights-parse-to-sql))
- `regexp_matches(s, pattern)` — every match, each as an array of its capture groups (the whole match when the pattern has none): `regexp_matches('a1b22', '\d+')` returns `[[1], [22]]`. It is not a true/false test; use `regexp_like`
- `regexp_like(s, pattern)` — true if string matches pattern
- `regexp_replace(s, pattern, replacement)` — regex replace
- `regexp_extract_all(s, pattern)` — all matches as an array, or the first capture group of each match when the pattern has one (`regexp_extract_all('k=1 k=22', 'k=(\d+)')` returns `[1, 22]`); an empty array when nothing matches. Omni provides it although upstream DataFusion does not
- `regexp_substr(s, pattern)` — first match
- `regexp_count(s, pattern)` — count of matches

### Time & Date

`` `@timestamp` `` is `Timestamp(Nanosecond)`. `dateceil` and `convert_timezone` accept only
`Timestamp(Microsecond)`, so call them on `arrow_cast(\`@timestamp\`, 'Timestamp(Microsecond, None)')`;
passed the raw column they fail at planning with`Failed to coerce arguments ... Timestamp(ns) to
the signature Exact(..., Timestamp(µs))`.`dateceil` takes an `INTERVAL`, not a`'5 minutes'`
string. `date_diff` takes dates: `date_diff(CAST(a AS DATE), CAST(b AS DATE))`.

- `NOW()` — current timestamp
- `to_timestamp_nanos(string)` — parse ISO-8601 string to timestamp. E.g., `to_timestamp_nanos('2026-08-20T15:00:00.000Z')`
- `to_timestamp(string)` — parse string to timestamp
- `to_unixtime(timestamp)` — timestamp to epoch seconds
- `from_unixtime(integer)` — epoch seconds to timestamp
- `fromMillis(integer)` — epoch milliseconds to timestamp
- `toMillis(timestamp)` — timestamp to epoch milliseconds
- `date_trunc(unit, timestamp)` — truncate to unit. E.g., `date_trunc('minute', \`@timestamp\`)`
- `dateceil(timestamp_us, interval)` — ceiling to interval; needs the microsecond cast. E.g., `dateceil(arrow_cast(\`@timestamp\`, 'Timestamp(Microsecond, None)'), INTERVAL '5 minutes')`
- `date_part(field, timestamp)` — extract part (year, month, day, hour, minute, second)
- `extract(field FROM timestamp)` — same as date_part
- `date_bin(interval, timestamp, origin)` — bin timestamps into fixed intervals
- `date_diff(date, date)` — difference between dates; cast timestamps first: `date_diff(CAST(\`@timestamp\` AS DATE), CAST(NOW() AS DATE))`
- `convert_timezone(from, to, timestamp_us)` — timezone conversion; needs the microsecond cast. E.g., `convert_timezone('UTC', 'Europe/London', arrow_cast(\`@timestamp\`, 'Timestamp(Microsecond, None)'))`
- `add_months(date, n)` — add months
- `make_timestamp(y, m, d, h, min, sec)` — create timestamp from parts

### JSON

> **Prefer bracket notation** for ingested JSON data (already extracted). Use these only for fields containing raw JSON strings.

- `json_get(s, path...)` — extract value at path
- `json_get_str(s, path...)` / `json_get_int(...)` / `json_get_float(...)` / `json_get_bool(...)` — typed extraction. Each path step is its own argument (`'user', 'name'`; the single string `'user.name'` is one key and returns NULL), and array indexes are 0-based. NULL when the path is missing, the value is of another JSON type (`json_get_str` on a number), or the text is not JSON
- `json_length(s, path...)` — array/object length at path
- `json_contains(s, path...)` — check if path exists
- `json_keys(s, path...)` — list keys at path
- `"jsonParse"(s)` — returns `s` if it is valid JSON, NULL if not. The result is text, not a struct: read keys from it with `json_get_*`, not brackets
- `"jsonStringify"(value)` — serialize to JSON string
- Both names are case-sensitive, so quote them: unquoted, `jsonParse(…)` fails with `Invalid function 'jsonparse'`

### IP

- `isIpInSubnet(ip, cidr)` — check if IP in subnet. E.g., `isIpInSubnet(ip, '10.0.0.0/8')`
- `isValidIp(s)` — validate IP address
- `isValidIpV4(s)` / `isValidIpV6(s)` — validate specific version
- `isIpv4InSubnet(ip, cidr)` / `isIpv6InSubnet(ip, cidr)` — version-specific subnet check
- `ipv4_string_to_num(s)` / `ipv4_num_to_string(n)` — IPv4 conversion

### Array

- `array_agg(expr [ORDER BY ...]) [FILTER (WHERE ...)]` — collect values into array
- `array_element(arr, n)` — element n (1-based)
- `array_length(arr)` — array length
- `array_first(arr)` / `array_last(arr)` — first/last element
- `array_sum(arr)` / `array_avg(arr)` / `array_count(arr)` — array math
- `array_filter(arr, condition)` — filter elements
- `array_contains(arr, value)` — check membership
- `array_distinct(arr)` — deduplicate
- `array_sort(arr)` — sort elements
- `array_concat(arr1, arr2)` — concatenate arrays
- `flatten(arr)` — flatten nested arrays

### Aggregate

- `COUNT(expr)` / `COUNT(*)` / `COUNT(DISTINCT expr)` — count
- `SUM(expr)` — sum
- `AVG(expr)` — average
- `MIN(expr)` / `MAX(expr)` — minimum / maximum
- `MEDIAN(expr)` — median value
- `STDDEV(expr)` / `STDDEV_POP(expr)` — standard deviation (sample / population)
- `FIRST_VALUE(expr [ORDER BY ...])` — first value by ordering
- `LAST_VALUE(expr [ORDER BY ...])` — last value by ordering
- `string_agg(expr, delimiter)` — concatenate strings with delimiter
- `approx_percentile_cont(expr, quantile)` — approximate percentile. E.g., `approx_percentile_cont(value, 0.99)`
- `bool_and(expr)` / `bool_or(expr)` — boolean aggregation
- `pattern(string)` — log clustering (groups similar text into patterns); `UNNEST` gives one struct per pattern with `pattern`, `patternId`, `sampleCount`, `ratio`, `severityLabel` and `logSamples` (see [Comparing two time windows](#comparing-two-time-windows-cwl-insights-diff))

All aggregate functions support the `FILTER (WHERE condition)` clause:

```sql
SUM(tokens) FILTER (WHERE kind = 'CLIENT') as client_tokens
```

### Window

All aggregate functions can be used as window functions with `OVER (...)`:

- `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)`
- `RANK()` / `DENSE_RANK()` — ranking with/without gaps
- `LAG(expr, offset)` / `LEAD(expr, offset)` — access previous/next rows
- `FIRST_VALUE(expr) OVER (...)` / `LAST_VALUE(expr) OVER (...)`
- `NTILE(n)` — divide into n buckets
- `CUME_DIST()` / `PERCENT_RANK()` — cumulative distribution

### Hashing

- `md5(s)` — MD5 hash
- `sha256(s)` / `sha512(s)` — SHA hashes
- `digest(s, algorithm)` — generic hash

---

## 8. Common Query Patterns

The patterns below work regardless of telemetry type. They reference only the guaranteed `@`-prefixed system fields plus **placeholder** field names shown purely to demonstrate syntax. Replace any non-`@` field name with a real field discovered via [Schema Discovery](#5-schema-discovery).

### Time Filtering + Ordering

```sql
SELECT `@timestamp`, `@record`
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
ORDER BY `@timestamp` DESC
LIMIT 100
```

### Table Sampling

Scan a fraction of the data with `TABLESAMPLE (<p> PERCENT)` placed after the table reference. The `` `@timestamp` `` bound is still mandatory. Sampling is approximate and repeatable, so this is best for exploratory scans over large windows rather than exact counts:

```sql
SELECT `@timestamp`, `@record`
FROM "logs.default" TABLESAMPLE (10 PERCENT)
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
ORDER BY `@timestamp` DESC
LIMIT 100
```

`p` must satisfy `0 < p <= 100`, and `TABLESAMPLE` is unavailable on `metrics.` tables. An extended form can also bound a scan by bytes with `MAX_VOLUME` / `BIAS`.

### Filter on a Discovered Field

```sql
-- 'your.field.key' is a placeholder — confirm real keys with ANALYZE_FIELDS first
SELECT `@timestamp`, `@record`
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
  AND attributes['your.field.key'] = 'some-value'
ORDER BY `@timestamp` DESC
```

### Aggregation Over Time Buckets

```sql
-- 'your.group.key' is a placeholder for a real field in your data
SELECT date_trunc('minute', `@timestamp`) AS time_bucket,
       attributes['your.group.key'] AS group_key,
       count(*) AS record_count
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '6 HOURS' AND NOW()
GROUP BY time_bucket, group_key
ORDER BY time_bucket DESC
```

### JSON Extraction

Most ingested JSON data is already extracted — use bracket notation (`field['key']`) to access nested values directly. Use `json_*` functions only when a field contains a raw JSON **string** that was not automatically extracted at ingestion (e.g., a serialized payload in a log body):

```sql
SELECT `@timestamp`,
       json_get_str(body, 'error', 'message') AS error_message,
       json_get_int(body, 'error', 'code') AS error_code
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '30 MINUTE' AND NOW()
  AND json_contains(body, 'error')
ORDER BY `@timestamp` DESC
```

### Translating CWL Insights `parse` to SQL

The CloudWatch Logs Insights (CWL) query language's `parse` command has no Omni SQL keyword.
Its four modes (glob, regex, logfmt and CSV), and reading JSON keys from a parsed field, map onto
existing functions: `regexp_match`, `regexp_extract_all`, `split_part`, `array_element`,
`json_get_str` and its typed variants, `NULLIF`, `TRY_CAST` and `unnest`. CWL parses `@message` when no field is named; in SQL, name the source and backtick it
(`` `@message` ``). The `` `@timestamp` `` bound is still required.

**Translating a `parse` query: state each of these that applies in the answer, not just the query:**

- **There is no `REGEXP_EXTRACT` and no `STR_TO_MAP`.** Capture groups come from `regexp_match`,
  read with `array_element(…, N)`, which is 1-based, never by subscripting the call.
- **Logfmt keys must be known up front.** There is no map, so each key is its own
  `regexp_match`, and a key the query does not name is not extracted. Say this in the answer.
- **A line that does not match keeps its row, with every field NULL.** Glob and regex are
  all-or-nothing, as in CWL: one missing literal part makes every group NULL. `SPLIT_PART`
  returns `''` instead of NULL, so wrap it in `NULLIF(…, '')`.
- **Positions hold only when every group is mandatory.** A `(…)?` or `|` group that does not
  match is dropped from the `regexp_match` array, shifting every later `array_element`
  position. This is not PostgreSQL behavior: no NULL stays in place. Translate an optional part
  as its own `regexp_match` call, so the field is NULL when absent and the others do not move.
- **The regex dialect is the Rust `regex` crate (RE2-style).** It has no backreferences (`\1`)
  and no lookahead or lookbehind (`(?=`, `(?!`, `(?<=`, `(?<!`). A CWL regex that uses them has
  no direct translation; rewrite it without them, for example by moving a lookbehind's text
  outside the group as plain literal text: `(?<=user=)(\w+)` becomes `user=(\w+)`, still read
  with `array_element(parts, 1)`. A pattern that does use them fails at run time as status
  `Failed`, with no error message. Matching is case-sensitive (`(?i)` folds case), and `.`
  does not match a newline (`(?s)` makes it match).
- **Field-level grants do not reach inside `@message`.** A grant that excludes a structured
  field (such as `attributes['user.email']`) does not redact that value in the raw `@message`
  text, so a `regexp_match` over `@message` can still return it. Only excluding `@message`
  itself protects it: an excluded `@message` returns NULL in `SELECT` and is rejected in
  `WHERE`. For OTel-structured data, read fields with bracket notation (`attributes['…']`, see
  [Field Access](#4-field-access--quoting)), and use `parse` only for a genuinely unstructured
  string payload.
- **`parse` never removes rows, so the faithful translation has no `@message` prefilter.** CWL
  returns every event in the window, with NULL fields on lines that do not match. A
  `` `@message` LIKE '%<fixed text>%' `` filter drops those lines, which changes `count(*)`, every
  `stats` total, and the NULL group of a `stats … by <parsed field>`. On one log group, a prefilter
  on the pattern's first literal returned 3,416 rows where CWL returned 6,704. The 2,144 matched
  rows were the same in both.
- **The `LIKE` prefilter is an optional optimization for matched rows only.** Add it only when
  the CWL query itself keeps only matched rows, for example with a later `filter ispresent(<field>)`
  or a `filter` on a parsed field, or when the user asks only about matched lines. Say in the answer
  that it was added and which CWL `filter` it stands for. Use text that every matching line must
  contain: a literal outside any optional group, alternation or `(?i)`. Prefer one `LIKE` per
  literal of the pattern (`LIKE '%user=%' AND LIKE '% action=%'`) over the first literal alone.
  However many literals it uses, a prefilter never brings back CWL's unmatched rows. It also keeps
  lines that contain the literals but do not match, so keep the SQL form of the CWL `filter`
  (`WHERE parts IS NOT NULL` for `filter ispresent(<field>)`) as well.
- **A filter on an extracted column does not narrow the scan; a `@message` prefilter can.**
  In testing, a prefilter cut the bytes scanned by 7× to 130× on some log groups, and made no
  difference on another (499.0 MB with it, 499.2 MB without, beside an `` `@logGroupName` ``
  equality). The effect of adding an `` `@logGroupName` `` equality also varied by account (it
  raised the scan on one and cut it on another). Measure rather than assume: compare with
  `EXPLAIN (ESTIMATE)` (see [Estimating Scan Volume](#estimating-scan-volume-explain-estimate)) or
  the run's `statistics.bytesScanned`.
- **Comparing with CWL: say whether a prefilter was applied.** Do not say the SQL matches CWL
  unless the total row count (`count(*)`) and the matched count (`count(<field>)`) were both
  compared with no prefilter. Matching grouped counts alone hides dropped rows.
- **One pass over the table.** Extract every field from the same `SELECT` (several
  `regexp_match` calls side by side), and chain `parse` stages with CTEs that read the previous
  stage. Never parse fields in separate subqueries over `logs.default` and JOIN them back: each
  subquery is another full scan, plus the join.
- **JSON keys come from `json_get_*`, one argument per path step.** CWL's
  `json field=payload "user.name"` is `json_get_str(payload, 'user', 'name')`; the single string
  `'user.name'` returns NULL. Array indexes are 0-based, unlike `array_element`. Use the
  function for the value's type (`json_get_int`, `json_get_float`, `json_get_bool`):
  `json_get_str` on a number returns NULL. Apply `json_get_*` in the `SELECT` that extracts the
  JSON text, and aggregate its result in the outer query. An aggregate around `json_get_*` of a
  column from an inner query, such as `sum(json_get_float(payload, …))`, fails with a bare
  `Validation error.` A log whose JSON Omni already extracted at ingestion needs no parse: use
  bracket notation (see [Field Access](#4-field-access--quoting)).
- **Known gaps.** CSV via `SPLIT_PART` splits inside a quoted field that contains a comma
  (`"hello, world"`), where CWL keeps the field whole. Parsing runs again on every execution, and
  nothing is cached. `multi` returns one row per match, so it can multiply the row count.

**Capture groups come from `regexp_match`, read with `array_element`.** `regexp_match(s,
pattern)` returns an array of the pattern's capture groups, or NULL when the pattern does not
match. Compute it once in a subquery and read each group with `array_element(parts, N)`, which is
1-based. For one group, `array_element(regexp_match(…), 1)` inline also works. Keep every group
mandatory. An optional group (`(…)?`, or one side of `|`) that does not take part in the match
is dropped from the array, and every later group moves up one position:
`regexp_match('ab', '(x)?(a)(b)')` returns `['a', 'b']`, not `[NULL, 'a', 'b']`. A group that
matches empty text stays as `''`. There is no single-call extractor:

| Form | Result |
|---|---|
| `REGEXP_EXTRACT(s, pattern, n)` (Trino / Presto / Athena) | `Invalid function 'regexp_extract'` |
| `regexp_match(…)[1]` (subscripting the call) | `unsupported nested access on column … access root is not a column reference` |

**Glob.** Each `*` becomes a capture group: `(.*?)`, except a `*` that ends the pattern, which is
`(.*)` and takes the rest of the line (`.` does not match a newline, so a trailing `\n` in
`` `@message` `` is dropped; CWL keeps it, and `(?s)(.*)` matches CWL exactly). A `*` followed by literal text stops at the first
occurrence of that text, so it is `(.*?)` even when it is the last `*`. Escape every regex
metacharacter in the literal text with `\` (for example `.` `(` `)` `[` `]` `{` `}` `?` `+` `|` `^` `$`
`\`). Matching is all-or-nothing, as in CWL: if the line lacks any literal part, every field is NULL.

```sql
-- CWL: parse @message "user=* action=*" as user, action
-- Faithful: every event in the window, with NULL fields on lines that do not match
SELECT array_element(parts, 1) AS user, array_element(parts, 2) AS action
FROM (
    SELECT regexp_match(`@message`, 'user=(.*?) action=(.*)') AS parts
    FROM logs.default
    WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
) t
```

When the CWL query keeps only matched rows, the prefilter is valid:

```sql
-- CWL: parse @message "user=* action=*" as user, action | filter ispresent(user)
SELECT array_element(parts, 1) AS user, array_element(parts, 2) AS action
FROM (
    SELECT regexp_match(`@message`, 'user=(.*?) action=(.*)') AS parts
    FROM logs.default
    WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
      -- Prefilter: stands for filter ispresent(user); one LIKE per literal of the pattern
      AND `@message` LIKE '%user=%' AND `@message` LIKE '% action=%'
) t
WHERE parts IS NOT NULL
```

A pattern of only space-separated wildcards, such as `"* * * *"`, translates the same way, to
`'(.*?) (.*?) (.*?) (.*)'`. ``SPLIT_PART(`@message`, ' ', N)`` (1-based) is an equivalent
**only when every line has exactly as many space-separated tokens as the pattern has wildcards**.
On a longer line its last field is one token rather than the rest of the line, and on a shorter
line it returns `''` where CWL returns NULL. Asked whether `SPLIT_PART` can replace such a pattern,
answer yes, as a shortcut with that condition, and give the regex form for lines whose token count
varies:

```sql
-- CWL: parse @message "* * * *" as ts, level, component, detail
-- Shortcut: equal to CWL only when every line has exactly 4 space-separated tokens
SELECT NULLIF(SPLIT_PART(`@message`, ' ', 1), '') AS ts,
       NULLIF(SPLIT_PART(`@message`, ' ', 2), '') AS level,
       NULLIF(SPLIT_PART(`@message`, ' ', 3), '') AS component,
       NULLIF(SPLIT_PART(`@message`, ' ', 4), '') AS detail
FROM logs.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

**Regex.** A CWL named group `(?<name>…)` can stay as it is, because the engine accepts the
syntax. Columns are named by your `AS` aliases, by position.

```sql
-- CWL: parse @message /status=(?<status>\d+) latency_ms=(?<latency>\d+)/
SELECT array_element(parts, 1) AS status, array_element(parts, 2) AS latency
FROM (
    SELECT regexp_match(`@message`, 'status=(\d+) latency_ms=(\d+)') AS parts
    FROM logs.default
    WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
) t
```

A CWL regex with an optional part, such as `(?: port=(?<port>\d+))?`, keeps its positions only if
that part captures nothing in the main pattern. Make it non-capturing there, and read its value
with a second `regexp_match`, which is NULL when the part is absent:

```sql
-- CWL: parse @message /host=(?<host>\S+)(?: port=(?<port>\d+))? path=(?<path>\S+)/
SELECT array_element(parts, 1) AS host, array_element(parts, 2) AS path,
       array_element(regexp_match(`@message`, ' port=(\d+)'), 1) AS port
FROM (
    SELECT `@message`, regexp_match(`@message`, 'host=(\S+)(?: port=\d+)? path=(\S+)') AS parts
    FROM logs.default
    WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
) t
```

The `multi` keyword (every match, one row each) is `unnest(regexp_extract_all(…))` in the
`SELECT` list. With a capture group, `regexp_extract_all` returns the group, not the whole match.
Sibling columns repeat on every match row, and a record with no match produces no row, as in CWL.
Put it in a subquery to aggregate:

```sql
-- CWL: parse @message /(?<ip>\d+\.\d+\.\d+\.\d+)/ multi | stats count(*) by ip
SELECT ip, count(*) AS n
FROM (
    SELECT unnest(regexp_extract_all(`@message`, '(\d+\.\d+\.\d+\.\d+)')) AS ip
    FROM logs.default
    WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
) t
GROUP BY ip
ORDER BY n DESC
```

Do not unnest with `CROSS JOIN UNNEST(t.<column>)`. It fails with `Proto serialization error:
outer_ref(t.<column>) is not yet supported`.

**Logfmt.** No function builds a map from `key=value` text: `STR_TO_MAP` is a Trino / Spark
function and fails with `Invalid function 'str_to_map'`. Extract each **known** key with its own
`regexp_match`, using `key=(\S+)`, or `key="([^"]*)"` for a quoted value. A key whose value is
sometimes quoted needs both patterns, in separate `regexp_match` calls, combined with `COALESCE`,
quoted first (the unquoted pattern would capture the opening `"`). For values with escaped quotes
use ``key="((?:[^"\\]|\\.)*)"``; the backslashes stay in the value. Name each array after its
key, and read it with `array_element(…, 1)`. A CWL reference such as `lf.level` becomes
`array_element(level_parts, 1)`, in the `SELECT` list and in the `WHERE`. When one key ends
another (`status=` inside `http_status=`), anchor it as `(?:^|\s)status=(\S+)`. Keys must be
known when the query is written. To find them, count the keys the lines carry. Prefilter on `=`
alone, not on one key: `LIKE '%level=%'` counts only the keys on lines that already carry
`level=`. Discovery needs only a sample, so narrow the `` `@timestamp` `` window to cut the scan:

```sql
SELECT k, count(*) AS n
FROM (
    SELECT unnest(regexp_extract_all(`@message`, '(?:^|\s)([A-Za-z_][A-Za-z0-9_.-]*)=')) AS k
    FROM logs.default
    WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
      AND `@message` LIKE '%=%'
) t
GROUP BY k
ORDER BY n DESC
LIMIT 50
```

```sql
-- CWL: parse @message logfmt as lf | filter lf.level = "error" | display lf.level, lf.msg
-- Keys must be known up front: there is no map, so only the keys named here are extracted;
-- add one regexp_match per extra key.
SELECT array_element(level_parts, 1) AS level, array_element(msg_parts, 1) AS msg
FROM (
    SELECT regexp_match(`@message`, 'level=(\S+)')   AS level_parts,
           regexp_match(`@message`, 'msg="([^"]*)"') AS msg_parts
    FROM logs.default
    WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
      -- Prefilter: stands for filter lf.level = "error", which keeps only matched rows
      AND `@message` LIKE '%level=error%'
) t
WHERE array_element(level_parts, 1) = 'error'
```

**CSV.** Each alias is ``SPLIT_PART(`@message`, ',', N)``, 1-based. Values keep surrounding spaces,
as in CWL. `SPLIT_PART` returns `''` for a missing field where CWL returns NULL, so wrap it in
`NULLIF(…, '')`. Use `TRY_CAST(… AS BIGINT / INT / DOUBLE)` for numeric fields, never `CAST`.
`TRY_CAST` returns NULL for text that is not a number, like CWL's coercion, while `CAST` fails the
whole query. That failure reaches `GetTelemetryQueryResults` as status `Failed`, with no error
message.

```sql
-- CWL: parse @message csv as host, method, path, status
SELECT
    NULLIF(SPLIT_PART(`@message`, ',', 1), '') AS host,
    NULLIF(SPLIT_PART(`@message`, ',', 2), '') AS method,
    NULLIF(SPLIT_PART(`@message`, ',', 3), '') AS path,
    TRY_CAST(SPLIT_PART(`@message`, ',', 4) AS BIGINT) AS status
FROM logs.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

**Chained parse.** Each `|` stage becomes one CTE, and the next stage parses the column the last
one produced:

```sql
-- CWL: parse @message "url=* " as url | parse url "/api/*/users/*" as version, userId
WITH step1 AS (
    SELECT array_element(url_parts, 1) AS url
    FROM (
        SELECT regexp_match(`@message`, 'url=(.*?) ') AS url_parts
        FROM logs.default
        WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
    ) a
)
SELECT array_element(path_parts, 1) AS version, array_element(path_parts, 2) AS userId
FROM (
    SELECT regexp_match(url, '/api/(.*?)/users/(.*)') AS path_parts
    FROM step1
) b
```

**JSON in a parsed field.** CWL pulls a JSON object out of the line with `parse`, then reads keys
from it with `json field=<field> "<path>"` or with `jsonParse(<field>)` and dot access. CWL reads an
array element with brackets, `j.a[0].b` (`j.a.0.b` silently returns nothing). In SQL, extract the
object with `regexp_match` and read each key with `json_get_*` in the same `SELECT`, with an array
index as its own 0-based argument (`json_get_str(<field>, 'a', 0, 'b')`):

```sql
-- CWL: parse @message /(?<payload>\{.*\})/ | json field=payload "user.name" as username
--      | stats count(*) by username
SELECT username, count(*) AS n
FROM (
    SELECT json_get_str(array_element(regexp_match(`@message`, '(\{.*\})'), 1), 'user', 'name') AS username
    FROM logs.default
    WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
) t
GROUP BY username
```

A numeric key uses `json_get_float` or `json_get_int` in the inner `SELECT`, and `sum` or `avg`
outside. On one embedded-metrics log group, this form matched CWL's `jsonParse` query exactly:
7,610 events and a sum of 28,821.

| CWL behavior | SQL equivalent |
|---|---|
| A record that does not match keeps its row, with NULL fields | `regexp_match` returns NULL. `SPLIT_PART` returns `''`; use `NULLIF` |
| `@message` is the default source | Name it, backticked: `` `@message` `` |
| Extracted strings coerce to numbers in `stats` | `TRY_CAST(… AS <type>)`, never `CAST` |
| `multi` | `unnest(regexp_extract_all(…))` in the `SELECT` list |
| Chained `parse` | One CTE per stage |
| `json field=<f> "a.b"`, or `jsonParse(<f>)` then `j.a.b` | `json_get_str(<f>, 'a', 'b')` (or a typed variant) in the inner `SELECT` |
| `jsonParse(<f>)` then `j.a[0].b` | `json_get_str(<f>, 'a', 0, 'b')` |

### Pattern Matching (Text Clustering)

The `pattern()` function groups similar text values into clusters. Use `UNNEST` to expand the results:

```sql
SELECT UNNEST(pattern(`@message`))
FROM "default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
LIMIT 1000
```

### Comparing two time windows (CWL Insights `diff`)

The CloudWatch Logs Insights (CWL) `diff` command compares log **patterns** in the query's time
window with an equal-length earlier window. Omni has no `diff` function: `diff(…)` fails with
`Invalid function 'diff'`. Compose it from `pattern()` instead. Cluster each window, join the two
pattern lists on `patternId`, and compute the change per pattern.

CWL accepts `diff` only after `pattern` (`… | pattern @message | diff`); without it the query fails
with `Diff operation has to be used after Pattern`. So the Omni form always starts from a
`pattern()` query. A CWL `filter` before `pattern` goes into **both** windows' `WHERE`. Narrowing
the input this way also makes the results line up with CWL: with `filter @message like /WARN/`
applied to both windows, every row matched CWL's, including `NEW` and `MISSING`.

**Translating a `diff` query: state each of these that applies in the answer, not just the query:**

- **Two `pattern()` lists joined on `patternId`.** Use one CTE per window and a `FULL OUTER JOIN`
  on `patternId`, a hash of the pattern template. Never join on the pattern text. The finding
  type is `NEW` when the pattern is only in the current window, `MISSING` when it is only in the
  comparison window, and `CHANGE_IN_COUNT` when it is in both. CWL does not split increases from
  decreases; the sign of the difference gives the direction.
- **Keep each window under 1,000 patterns.** `pattern()` returns at most 1,000 patterns. Over all
  of `logs.default` for 15 minutes it returned exactly 1,000, covering 415,188 of 1,519,045 events,
  and which 1,000 came back changed between runs. A diff reports that change as spurious `NEW` and
  `MISSING` rows. Scope both windows to one log group (`` `@logGroupName` = '<log-group>' ``) or a
  narrowing filter, and narrow further whenever a window returns exactly 1,000 patterns. Within
  that limit most repeat runs match exactly, but not every one: in 2 of 9 runs on one log group,
  1 to 4 patterns of 1 to 6 events differed, because a token became `<*>` in one run and not in
  the other. Re-run before acting on a `NEW` or `MISSING` row with a small count.
- **Leave late events time to arrive.** Events can reach Omni after their timestamp. For one
  recent window Omni held 883 events where CloudWatch Logs already had 1,081, and Omni caught up
  later. End the current window well in the past when the counts must be complete.
- **Equal, non-overlapping windows.** Bound both windows as `>= start AND < end`, with the same
  length. `BETWEEN` on both windows counts an event at the shared boundary twice, and that is
  not rare: on one account, 10,000 to 20,000 events carried a timestamp exactly on each whole
  minute.
- **An empty comparison window makes every pattern `NEW`.** CWL refuses a comparison window that
  falls before the log group existed or beyond its retention (`Diff compilation Failed : Query's
  baseline end time is either before the log groups creation time or exceeds the log groups log
  retention settings`). Omni returns every pattern as `NEW` instead. Count the comparison window's
  events before calling a pattern new.
- **It reads both windows, once each.** The bytes scanned are the two windows' scans added
  together. The join works on the short pattern lists and adds nothing, so this is the exception
  to the one-pass rule for `parse`. Do not cluster both windows in one pass with `GROUP BY` a
  window label: `pattern()` per group does not produce the same clusters, and the results change
  from run to run.
- **Results match CWL in meaning, not row for row.** Each window holds the same events and counts
  in both engines, the finding types agree, and the difference is computed the same way. But the
  two engines build templates differently (CWL writes `<*>`, Omni names tokens such as
  `<status>`), and either can split or merge a pattern the other keeps whole. So `patternId`s and
  the number of patterns differ across engines. Compare counts, not ids.

```sql
-- CWL: pattern @message | diff     (the last hour of one log group vs the hour before)
WITH current_window AS (
    SELECT c.patternId AS patternId, c.pattern AS pattern,
           c.sampleCount AS sampleCount, c.severityLabel AS severityLabel
    FROM (
        SELECT UNNEST(pattern(`@message`)) AS c
        FROM logs.default
        WHERE `@timestamp` >= NOW() - INTERVAL '1 HOUR' AND `@timestamp` < NOW()
          AND `@logGroupName` = '<log-group>'
    ) t
),
comparison_window AS (
    SELECT c.patternId AS patternId, c.pattern AS pattern,
           c.sampleCount AS sampleCount, c.severityLabel AS severityLabel
    FROM (
        SELECT UNNEST(pattern(`@message`)) AS c
        FROM logs.default
        WHERE `@timestamp` >= NOW() - INTERVAL '2 HOURS' AND `@timestamp` < NOW() - INTERVAL '1 HOUR'
          AND `@logGroupName` = '<log-group>'
    ) t
)
SELECT COALESCE(cur.pattern, cmp.pattern) AS pattern,
       COALESCE(cur.sampleCount, 0) AS current_count,
       COALESCE(cmp.sampleCount, 0) AS comparison_count,
       COALESCE(cur.sampleCount, 0) - COALESCE(cmp.sampleCount, 0) AS difference_event_count,
       CASE WHEN COALESCE(cmp.sampleCount, 0) = 0 THEN NULL
            ELSE ROUND((COALESCE(cur.sampleCount, 0) - cmp.sampleCount) * 100.0 / cmp.sampleCount, 2)
       END AS difference_pct,
       CASE WHEN cmp.patternId IS NULL THEN 'NEW'
            WHEN cur.patternId IS NULL THEN 'MISSING'
            ELSE 'CHANGE_IN_COUNT' END AS finding_type,
       COALESCE(cur.severityLabel, cmp.severityLabel) AS severity
FROM current_window cur
FULL OUTER JOIN comparison_window cmp ON cur.patternId = cmp.patternId
ORDER BY difference_event_count DESC
```

`difference_pct` is NULL for a `NEW` pattern, which has no baseline to divide by. Only the
comparison window's bounds change between CWL's comparison periods, for a current window `L` long:

| CWL | Comparison period | Comparison window |
|---|---|---|
| `diff` | Previous period | `>= NOW() - 2L AND < NOW() - L` |
| `diff previousDay` | Previous day | `>= NOW() - INTERVAL '1 DAY' - L AND < NOW() - INTERVAL '1 DAY'` |
| `diff previousWeek` | Previous week | `>= NOW() - INTERVAL '7 DAYS' - L AND < NOW() - INTERVAL '7 DAYS'` |
| `diff previousMonth` | Previous month (30 days) | `>= NOW() - INTERVAL '30 DAYS' - L AND < NOW() - INTERVAL '30 DAYS'` |

CWL's previous month is 30 days back, not one calendar month: its baseline totals matched the
window 30 days earlier exactly, and missed the window one calendar month earlier.

To compare one pattern only, add `WHERE COALESCE(cur.patternId, cmp.patternId) = '<patternId>'`
before the `ORDER BY`. Filter on both sides: `cur.patternId = '…'` alone drops the row when the
pattern is only in the comparison window (`MISSING`). The `patternId` comes from a `pattern()` result.

| Form | Result |
|---|---|
| `diff(…)` | `Invalid function 'diff'` (the suggested alternative varies) |
| `UNNEST(pattern(…)) AS cluster` inside a CTE | `Invalid SQL: Expected: ), found: cluster`. Name it `c` |
| A sub-field not aliased in the CTE (`SELECT c.patternId …`, then `cur.patternId` outside) | `Schema error: No field named …"patternId". Did you mean '…c[patternId]'?`. Alias every sub-field: `c.patternId AS patternId` |

### Span Duration (traces.default)

There is **no `duration_ms` column** on `traces.default`; a query that CASTs or aggregates
`duration_ms` is rejected at planning time. The span duration field is `durationNano` in
NANOseconds (string-typed; not milliseconds — a naive read is off by 1e6). Always
`CAST(durationNano AS DOUBLE)` before comparing, ranking, or aggregating — without the cast
the engine cannot coerce the string for numeric ordering, so `ORDER BY durationNano DESC`
on the raw field is wrong. Exclude NULL durations — under `ORDER BY … DESC`, NULLs sort
**first**, so without `durationNano IS NOT NULL` row 1 is not the slowest span. Service
identity is a resource attribute reached with bracket notation,
`resource['attributes']['service.name']`, not a bare top-level column.

```sql
SELECT `@timestamp`, name, resource['attributes']['service.name'] AS service,
       CAST(durationNano AS DOUBLE) / 1e6 AS duration_ms_derived
FROM traces.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
  AND resource['attributes']['service.name'] = '<service-name>'
  AND durationNano IS NOT NULL
ORDER BY CAST(durationNano AS DOUBLE) DESC
LIMIT 20
```

> **Slowest / longest / duration-ranked spans — state ALL of this in the answer, not just
> the query:** the duration field is `durationNano` (there is no `duration_ms` column — it
> fails at planning); it is NANOseconds, so a millisecond read is off by 1e6; it is
> string-typed, so it needs `CAST(durationNano AS DOUBLE)`; NULL durations sort first under
> `DESC`, so `durationNano IS NOT NULL` is required or the top row is not the slowest span;
> the `` `@timestamp` `` filter with a relative window is mandatory; and the service is
> `resource['attributes']['service.name']` (bracket notation), not a top-level field.

The `duration_ms_derived` alias above is computed from `durationNano`; it is not a stored
column and cannot be used in the same query's `WHERE`. `attributes['duration_ms']` is a
valid but almost always empty per-customer attribute lookup, not the span duration.

### Finding failed spans

A span's failure is read from its **status code**, not an invented `is_error`/`success`
boolean — no such top-level column exists. The OTel span status lives at `status['code']`, and an error is the ERROR status (OTel StatusCode
enum value 2). The value may be ingested as the proto numeric enum (integer `2` or string `'2'`) or
as the string `'ERROR'` or `'STATUS_CODE_ERROR'` in any letter case, so normalise before matching:
`upper(TRY_CAST(status['code'] AS VARCHAR)) IN ('2', 'ERROR', 'STATUS_CODE_ERROR')` casts whatever type is present to
text and folds case, catching every ingestion variant with a single-typed `IN` list (no
engine-dependent mixed-type list). An HTTP status attribute such as
`http.response.status_code` is **corroborating** evidence, reached with bracket notation
(`attributes['http.response.status_code']`), never as a bare top-level field.

```sql
SELECT `@timestamp`, `@record`
FROM traces.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
  AND upper(TRY_CAST(status['code'] AS VARCHAR)) IN ('2', 'ERROR', 'STATUS_CODE_ERROR')
-- narrow to the service via a discovered resource attribute, e.g.
--   AND resource['attributes']['service.name'] = '<your-service-name>'
LIMIT 100
```

Under the permissive schema a misspelled status field silently returns NULL rather than
erroring, so an empty result should prompt schema discovery (`ListTelemetryFields` /
`EXPLAIN (ANALYZE_FIELDS)`), not a conclusion that nothing failed.

> **Failed / erroring spans — state ALL of this in the answer, not just the query.** Open
> the answer with the schema caveat, before any filter query: field names depend on what
> was ingested, so first run `EXPLAIN (ANALYZE_FIELDS)` (or `ListTelemetryFields`) to
> confirm which field carries the span status — `status['code']` is the OTel convention and
> the usual answer, not a guarantee. Show that discovery query first, then the filter query.
> Then: failure is read from that status field (ERROR / `2` / `STATUS_CODE_ERROR`, normalised
> with `upper(TRY_CAST(... AS VARCHAR))`), never from an invented `is_error` column; an
> HTTP or gRPC status attribute is corroborating evidence reached with bracket notation;
> the `` `@timestamp` `` window is mandatory; the service is
> `resource['attributes']['service.name']`; and an empty result under the permissive schema
> means "check the field names", not "nothing failed".

For whole traces — fetching one by id, its span tree and time breakdown, failure analysis,
AI-agent span attributes, and finding traces by their spans — see
[trace-exploration.md](trace-exploration.md).

### Reading a span or trace you already have (pasted, or passed as UI context)

When a span object is handed to you directly (the user pastes it, or the UI passes the
currently open span as context), read it in place — the data is already supplied, so do
**not** probe the account, run a query, or ask the user to fetch it again. Its own fields
are the answer. **State all of these that apply, in the answer text:**

- **Error state is `status.code`.** `STATUS_CODE_ERROR` (numeric `2` in some exports)
  means the span failed, and `status.message` carries the reason. `STATUS_CODE_OK` is an
  explicit success. `STATUS_CODE_UNSET` means the producer set no explicit status — it is
  **not** an error signal, but it is not proof of success either: corroborating fields (an
  HTTP 5xx `http.response.status_code`, a non-OK `rpc.grpc.status_code`) can still
  indicate a failure on an UNSET span, so check them before calling it healthy.
- **Corroborate with the protocol status.** `attributes['http.response.status_code']`
  (a 5xx) or `attributes['rpc.grpc.status_code']` is supporting evidence for the same
  error, not a second independent one — report it as corroboration.
- **Service identity lives under `resource`** — `resource['attributes']['service.name']`,
  not a top-level field. Attribute the span to that service.
- **`durationNano` is NANOseconds, string-typed.** Convert it and show the arithmetic:
  `durationNano / 1e9` = seconds, `/ 1e6` = milliseconds. Reading the raw value as
  milliseconds is off by 1e6.
- **Point downstream when the evidence does.** `attributes['rpc.service']`,
  `attributes['peer.service']`, or `attributes['server.address']` names the callee; a
  5xx gateway status (502/503/504) plus a timeout-shaped `status.message` indicates the
  dependency did not respond in time rather than this service erroring internally.
- **Do not invent** errors, attributes, or child spans the object does not contain, and
  **do not claim a root cause from a single span** — say that confirming it needs the
  downstream spans in the same trace (join on `traceId`).

### Numeric Comparison on String-Typed Fields

Ingested values retain their original type. When values are stored as strings, use `TRY_CAST` to convert to numeric types. The field name below is a placeholder:

```sql
SELECT `@timestamp`, `@record`
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
  AND TRY_CAST(attributes['your.numeric.key'] AS BIGINT) > 1000
ORDER BY TRY_CAST(attributes['your.numeric.key'] AS BIGINT) DESC
LIMIT 20
```

### Window Function — Running Count per Group

The nested field has to be aliased in a CTE first — a window cannot partition by a
bracket path (§6):

```sql
-- 'your.partition.key' is a placeholder for a real field
WITH rows AS (
  SELECT `@timestamp`,
         attributes['your.partition.key'] AS group_key
  FROM default
  WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
)
SELECT `@timestamp`,
       group_key,
       count(*) OVER (
         PARTITION BY group_key
         ORDER BY `@timestamp`
       ) AS running_count
FROM rows
ORDER BY `@timestamp` DESC
LIMIT 200
```

Partitioning by the bracket path directly — `PARTITION BY attributes['your.partition.key']`
— fails with `Schema error: No field named attributes`, with or without `ORDER BY`, for
`count(*)` and `ROW_NUMBER()` alike.

### Approximate Percentiles

```sql
-- 'your.value.key' is a placeholder for a real numeric field
SELECT attributes['your.group.key'] AS group_key,
       approx_percentile_cont(TRY_CAST(attributes['your.value.key'] AS BIGINT), 0.50) AS p50,
       approx_percentile_cont(TRY_CAST(attributes['your.value.key'] AS BIGINT), 0.95) AS p95,
       approx_percentile_cont(TRY_CAST(attributes['your.value.key'] AS BIGINT), 0.99) AS p99
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
GROUP BY group_key
ORDER BY p99 DESC
```

### Common Table Expression + Self-Join

Note the `` `@timestamp` `` filter is required on **both** sides of a self-join. Field names below are placeholders:

```sql
WITH candidates AS (
  SELECT DISTINCT attributes['your.correlation.key'] AS corr_key
  FROM default
  WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
    AND TRY_CAST(attributes['your.value.key'] AS BIGINT) > 5000
)
SELECT t.`@timestamp`, t.`@record`
FROM default AS t
INNER JOIN candidates AS c
  ON attributes['your.correlation.key'] = c.corr_key
WHERE t.`@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
ORDER BY t.`@timestamp` ASC
```

The `ON` clause deliberately writes the bracket path **unqualified** — `attributes[...]`,
not `t.attributes[...]`. An alias-qualified bracket path resolves to NULL (see
[Field Access & Quoting](#4-field-access--quoting)), so the qualified spelling makes this
join match nothing and return zero rows **with no error**. Alias-qualifying a *top-level*
field, as in `` t.`@timestamp` `` above, is fine.

### Correlating logs with traces

Logs and spans correlate through a **field they share** — commonly the trace identifier the
logging library injected (`traceId` on OTel-shaped records, or a nested variant such as
`attributes['trace_id']`), but the name is not guaranteed. Discover it on **both** tables
first with `EXPLAIN (ANALYZE_FIELDS)`, then use either approach — **show both in the
answer**, each with the mandatory `` `@timestamp` `` bound:

1. **One unified query over `default`**, which holds both telemetry types, filtered by the
   shared field and tagged with `` `@telemetry_type` ``:

   ```sql
   SELECT `@telemetry_type`, `@timestamp`, `@record`
   FROM default
   WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
     AND <shared_field> = '<trace-id>'
   ORDER BY `@timestamp` ASC
   ```

2. **A `JOIN` of `logs.default` with `traces.default`** on the shared field, with the
   `` `@timestamp` `` filter on **both** sides:

   ```sql
   SELECT l.`@timestamp` AS log_time, l.`@message`, t.name AS span_name
   FROM logs.default AS l
   INNER JOIN traces.default AS t
     ON l.<shared_field> = t.<shared_field>
   WHERE l.`@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
     AND t.`@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
     AND t.<shared_field> = '<trace-id>'
   ORDER BY l.`@timestamp` ASC
   ```

Give the span side a wide upper bound: a span's `` `@timestamp` `` is its **end** time, so a
window that stops shortly after the request began drops its longest spans (section 2).

If the log records carry no trace context at all, no query can associate them after
ingestion — the fix is instrumentation (inject the active trace id into each log record),
not a different SQL shape.

### Combining Telemetry Types

Query multiple telemetry types together using the combined `default` table and `` `@telemetry_type` `` to distinguish them:

```sql
SELECT `@telemetry_type`, `@timestamp`, `@record`
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
  AND `@telemetry_type` IN ('logs', 'traces')
ORDER BY `@timestamp` ASC
```

Or use `UNION ALL` to combine results from separate tables:

```sql
SELECT 'logs' AS source, `@message` AS detail, `@timestamp`
FROM logs.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()

UNION ALL

SELECT 'traces' AS source, `@message` AS detail, `@timestamp`
FROM traces.default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()

ORDER BY `@timestamp` ASC
```

---

## 9. Constraints & Gotchas

1. **Single statement only** — no semicolons separating multiple queries. One `SELECT` per request.
2. **`` `@timestamp` `` filter is mandatory** — every `WHERE` must constrain it, and both sides of any self-join must constrain it.
3. **Default LIMIT 10,000** — if you omit `LIMIT`, the query returns at most 10,000 rows.
4. **Permissive schema hides mistakes** — a misspelled field, or a field that doesn't exist in your data, silently returns NULL instead of raising an error. If results look unexpectedly empty, verify field names with schema discovery.
5. **Use `to_timestamp_nanos()` for ISO strings** — when specifying absolute timestamps, pass ISO-8601 strings through `to_timestamp_nanos('2026-08-20T15:00:00.000Z')`.
6. **Unquoted `@`-fields fail** — always backtick-quote: `` `@timestamp` ``, `` `@message` ``, etc.
7. **Types match ingested values** — fields retain the type they were ingested with. When values are ingested as strings, use `TRY_CAST` to convert them to numeric types (`BIGINT`, `DOUBLE`, `INT`, `DECIMAL`) before arithmetic or comparison. `TRY_CAST` returns NULL if the conversion is not possible.
8. **Field names are never guaranteed** — the schema depends entirely on what was ingested. Only the `@`-prefixed [system fields](#3-system-fields) are guaranteed. Always confirm any other field with `EXPLAIN (ANALYZE_FIELDS)` before relying on it.
9. **No DDL/DML** — `INSERT`, `UPDATE`, `DELETE`, `CREATE`, `ALTER`, `DROP` are all blocked. Only `SELECT` is supported.
10. **`TABLESAMPLE` is approximate** — it returns an approximate sample rather than an exact `p%` of rows, is repeatable for the same query and time range, supports `PERCENT` (`0 < p <= 100`) plus the `MAX_VOLUME` / `BIAS` arguments, and is unavailable on `metrics.` tables.
11. **`EXPLAIN (ESTIMATE)` is an upper bound** — one row, one column (`estimated_bytes`), not billed, no accuracy guarantee; it cannot be combined with other `EXPLAIN` options, `TABLESAMPLE`, or `metrics.` tables (see [Estimating Scan Volume](#estimating-scan-volume-explain-estimate)).
12. **The CloudWatch Logs Insights `parse` command has no Omni SQL keyword** — glob and regex map to `regexp_match` read with `array_element(…, N)` (1-based), `multi` to `unnest(regexp_extract_all(…))`, logfmt to one `regexp_match` per known key, CSV to `SPLIT_PART` with `NULLIF` / `TRY_CAST`, and a JSON key read from a parsed field to `json_get_str(f, 'a', 'b')` (one argument per path step). `REGEXP_EXTRACT` and `STR_TO_MAP` do not exist (see [Translating CWL Insights `parse` to SQL](#translating-cwl-insights-parse-to-sql)).
13. **The CloudWatch Logs Insights `diff` command has no Omni SQL function** — cluster each window with `pattern()` in its own CTE (sub-fields aliased, the `UNNEST` alias not `cluster`), `FULL OUTER JOIN` the two on `patternId`, and scope both windows so each returns fewer than the 1,000 patterns `pattern()` can return (see [Comparing two time windows](#comparing-two-time-windows-cwl-insights-diff)).

### Performance Tips

- **Estimate before a wide scan** — `EXPLAIN (ESTIMATE) <query>` returns an upper bound on the bytes the query would scan, without running it and without being billed.
- **Narrow the time range** — this is the main driver of query latency. A shorter `@timestamp` window scans less data and returns results faster. If sorting by timestamp, try a narrower period first.
- **Avoid ORDER BY when order doesn't matter** — sorting adds overhead. Omit it for aggregation or exploratory queries where row order is irrelevant.
- **Prefer equality predicates** — `=` and `IN (...)` filters are the most efficient for narrowing down results.
- **IS NULL / IS NOT NULL are efficient** — these help narrow down the search in most cases.
- **Filter before you parse, only when the query keeps matched rows** — a parse query can be the exception to *Avoid LIKE* below: a literal `` `@message` LIKE '%<fixed text>%' `` can narrow its scan, while a filter on the extracted column does not. Add it only when the CWL query keeps only matched rows (`filter ispresent(<field>)` or a `filter` on a parsed field), or the user asks only about matched lines; otherwise it drops the NULL rows CWL `parse` keeps (see [Translating CWL Insights `parse` to SQL](#translating-cwl-insights-parse-to-sql)). The saving is not guaranteed: measure it with `EXPLAIN (ESTIMATE)` or `statistics.bytesScanned`.
- **Avoid LIKE when possible** — pattern matching is expensive. If you must use LIKE, combine it with other more selective filters (equality, time range) to reduce the data scanned first.
- **Set a LIMIT** — especially useful for "find the slowest" or TOP-K type queries. Adding `ORDER BY CAST(durationNano AS DOUBLE) DESC LIMIT 10` (with `durationNano IS NOT NULL`) is much cheaper than sorting the entire dataset.
- **Use EXPLAIN (ANALYZE_FIELDS) once to discover the schema** — then write precise queries against known fields rather than scanning with `@record`.
