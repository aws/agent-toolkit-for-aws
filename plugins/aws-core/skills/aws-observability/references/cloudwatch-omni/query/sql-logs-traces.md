# Omni Query Syntax Reference

The SQL dialect for querying logs and traces in CloudWatch Omni. Both Omni experiences — **Application Observability** (APM, distributed tracing, log analysis) and **Agent Observability** (LLM/AI agent monitoring) — use this same SQL query surface. All queries are read-only `SELECT` statements.

**The SQL syntax is identical whether you query logs or traces.** They share the exact same grammar, functions, quoting rules, and constraints. The *only* difference between tables is the data they contain — that is, which fields are present. This reference documents the dialect once, covering logs and traces in Omni.

> **The schema is dynamic and varies across the data.** All telemetry for an account (logs, traces, metrics) is stored in Omni, and different applications, services, or telemetry types will have completely different field structures. One application's logs may have fields that another's does not. The *only* fields guaranteed to exist on every record are the `@`-prefixed system fields documented below. Before writing a query that references any other field, discover the actual schema by narrowing to the relevant slice of data with `EXPLAIN (ANALYZE_FIELDS)` (see [Schema Discovery](#5-schema-discovery)).

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

**Metrics are not in this table.** Metrics are not SQL — they are queried with PromQL, and there is no `metrics.default` `FROM` target. See [promql-metrics.md](promql-metrics.md) for the PromQL surface, label conventions, and per-service metric catalog.

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
| `` `@timestamp` `` | Mandatory filter field. Every query must constrain this. |
| `` `@record` `` | All user-visible data as JSON. Contains the full record structure. |
| `` `@message` `` | Original ingestion payload. Permission-gated — may not be available to all users. |
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

**Joins:**

- `INNER JOIN`
- `LEFT JOIN`
- `RIGHT JOIN`
- `FULL OUTER JOIN`

**Subqueries & Composition:**

- Common Table Expressions (WITH clause): `WITH name AS (SELECT ...) SELECT ... FROM name`
- Subqueries: `IN (SELECT ...)`, `EXISTS (SELECT ...)`, derived tables `FROM (SELECT ...) AS t`
- Set operations: `UNION`, `UNION ALL`, `INTERSECT`, `EXCEPT`

**Window functions:**

- `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)`
- `RANK() OVER (...)`
- Aggregate functions with `OVER (PARTITION BY ... ORDER BY ...)`

**Expressions:**

- `CASE WHEN ... THEN ... ELSE ... END`
- `LIKE` / `NOT LIKE`
- `IN (value1, value2, ...)`
- `BETWEEN ... AND ...`
- `IS NULL` / `IS NOT NULL`
- `CAST(expr AS type)`
- `TRY_CAST(expr AS type)` — returns NULL instead of failing on invalid conversion
- Arithmetic: `+`, `-`, `*`, `/`

### Table Sampling (TABLESAMPLE)

`TABLESAMPLE` reduces the amount of data scanned by sampling a table reference. It is placed immediately after a table reference in the `FROM` clause.

**Syntax:** `TABLESAMPLE (<p> PERCENT)` — only the `PERCENT` unit is supported, and `p` must satisfy `0 < p <= 100`.

```sql
SELECT * FROM "logs.default" TABLESAMPLE (10 PERCENT)
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

**Per-occurrence / per-table** — each table reference carries its own independent sampling rate. In multi-datastore joins and self-joins, every occurrence is sampled separately:

```sql
SELECT *
FROM "logs.default" a TABLESAMPLE (10 PERCENT)
JOIN "traces.default" b TABLESAMPLE (50 PERCENT) ON a.id = b.id
WHERE a.`@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
  AND b.`@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
```

**Behavior** — `TABLESAMPLE` returns an approximate sample, not an exact `p%` of rows: the returned row count is an approximation of the requested percentage. Sampling is repeatable — re-running the same query over the same time range returns the same sample.

**Supported tables** — `logs.` / `traces.` / bare `default`. It is **NOT** supported on `metrics.` tables.

**Rejection rules** — each of the following raises an explicit error:

- Combining with `EXPLAIN (ANALYZE_FIELDS)`.
- A percentage outside `(0, 100]`.
- `ROWS` or no unit — `PERCENT` is the only supported unit.
- A sampling method name such as `BERNOULLI` / `SYSTEM`.
- `REPEATABLE` / `SEED` — sampling is deterministic and cannot be seeded.
- `BUCKET`.
- A non-numeric percentage.
- `TABLESAMPLE` in an unsupported position — a `SELECT`-list scalar subquery, a `HAVING` subquery, or a `JOIN ... ON` subquery. It **is** allowed on `FROM` relations, `WHERE` subqueries, derived tables, and `UNION` branches.
- Conflicting percentages on the same table occurrence.

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

- `regexp_matches(s, pattern)` — true if string matches pattern
- `regexp_like(s, pattern)` — alias for regexp_matches
- `regexp_replace(s, pattern, replacement)` — regex replace
- `regexp_extract_all(s, pattern)` — all matches as array
- `regexp_substr(s, pattern)` — first match
- `regexp_count(s, pattern)` — count of matches

### Time & Date

- `NOW()` — current timestamp
- `to_timestamp_nanos(string)` — parse ISO-8601 string to timestamp. E.g., `to_timestamp_nanos('2026-08-20T15:00:00.000Z')`
- `to_timestamp(string)` — parse string to timestamp
- `to_unixtime(timestamp)` — timestamp to epoch seconds
- `from_unixtime(integer)` — epoch seconds to timestamp
- `fromMillis(integer)` — epoch milliseconds to timestamp
- `toMillis(timestamp)` — timestamp to epoch milliseconds
- `date_trunc(unit, timestamp)` — truncate to unit. E.g., `date_trunc('minute', \`@timestamp\`)`
- `dateceil(timestamp, unit)` — ceiling to unit. E.g., `dateceil(\`@timestamp\`, '5 minutes')`
- `date_part(field, timestamp)` — extract part (year, month, day, hour, minute, second)
- `extract(field FROM timestamp)` — same as date_part
- `date_bin(interval, timestamp, origin)` — bin timestamps into fixed intervals
- `date_diff(date, date)` — difference between dates
- `convert_timezone(from, to, timestamp)` — timezone conversion
- `add_months(date, n)` — add months
- `make_timestamp(y, m, d, h, min, sec)` — create timestamp from parts

### JSON

> **Prefer bracket notation** for ingested JSON data (already extracted). Use these only for fields containing raw JSON strings.

- `json_get(s, path...)` — extract value at path
- `json_get_str(s, path...)` / `json_get_int(...)` / `json_get_float(...)` / `json_get_bool(...)` — typed extraction
- `json_length(s, path...)` — array/object length at path
- `json_contains(s, path...)` — check if path exists
- `json_keys(s, path...)` — list keys at path
- `jsonParse(s)` — parse and validate JSON string
- `jsonStringify(value)` — serialize to JSON string

### IP

- `isIpInSubnet(ip, cidr)` — check if IP in subnet. E.g., `isIpInSubnet(ip, '10.0.0.0/8')`
- `isValidIp(s)` — validate IP address
- `isValidIpV4(s)` / `isValidIpV6(s)` — validate specific version
- `isIpv4InSubnet(ip, cidr)` / `isIpv6InSubnet(ip, cidr)` — version-specific subnet check
- `ipv4_string_to_num(s)` / `ipv4_num_to_string(n)` — IPv4 conversion

### Array

- `array_agg(expr [ORDER BY ...]) [FILTER (WHERE ...)]` — collect values into array
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
- `pattern(string)` — log clustering (groups similar text into patterns)

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

Only `PERCENT` is supported (`0 < p <= 100`), and `TABLESAMPLE` is unavailable on `metrics.` tables.

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

### Pattern Matching (Text Clustering)

The `pattern()` function groups similar text values into clusters. Use `UNNEST` to expand the results:

```sql
SELECT UNNEST(pattern(`@message`))
FROM "default"
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
LIMIT 1000
```

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

```sql
-- 'your.partition.key' is a placeholder for a real field
SELECT `@timestamp`,
       attributes['your.partition.key'] AS group_key,
       count(*) OVER (
         PARTITION BY attributes['your.partition.key']
         ORDER BY `@timestamp`
       ) AS running_count
FROM default
WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
ORDER BY `@timestamp` DESC
LIMIT 200
```

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
  ON t.attributes['your.correlation.key'] = c.corr_key
WHERE t.`@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW()
ORDER BY t.`@timestamp` ASC
```

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
10. **`TABLESAMPLE` is approximate** — it returns an approximate sample rather than an exact `p%` of rows, is repeatable for the same query and time range, supports the `PERCENT` unit only (`0 < p <= 100`), and is unavailable on `metrics.` tables.

### Performance Tips

- **Narrow the time range** — this is the main driver of query latency. A shorter `@timestamp` window scans less data and returns results faster. If sorting by timestamp, try a narrower period first.
- **Avoid ORDER BY when order doesn't matter** — sorting adds overhead. Omit it for aggregation or exploratory queries where row order is irrelevant.
- **Prefer equality predicates** — `=` and `IN (...)` filters are the most efficient for narrowing down results.
- **IS NULL / IS NOT NULL are efficient** — these help narrow down the search in most cases.
- **Avoid LIKE when possible** — pattern matching is expensive. If you must use LIKE, combine it with other more selective filters (equality, time range) to reduce the data scanned first.
- **Set a LIMIT** — especially useful for "find the slowest" or TOP-K type queries. Adding `ORDER BY CAST(durationNano AS DOUBLE) DESC LIMIT 10` (with `durationNano IS NOT NULL`) is much cheaper than sorting the entire dataset.
- **Use EXPLAIN (ANALYZE_FIELDS) once to discover the schema** — then write precise queries against known fields rather than scanning with `@record`.
