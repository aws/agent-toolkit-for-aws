# CloudWatch Logs Insights

Complete query syntax reference, performance tips, and reusable query library.

## Contents
- [Commands](#commands)
- [Filter syntax](#filter-syntax)
- [Parse command](#parse-command)
- [Stats and aggregation](#stats-and-aggregation)
- [Time functions](#time-functions)
- [Advanced commands](#advanced-commands)
- [Known issues](#known-issues)
- [Reusable query library](#reusable-query-library)

---

## Commands

| Command | Description | Infrequent Access |
|---------|-------------|:-----------------:|
| `fields` | Select/transform fields, supports functions | Yes |
| `filter` | Match conditions with boolean/regex | Yes |
| `stats` | Aggregate statistics | Yes |
| `sort` | Order results `asc` or `desc` | Yes |
| `limit` | Specify max returned events (default 10,000 if omitted) | Yes |
| `parse` | Extract fields via glob or regex | Yes |
| `display` | Choose which fields to show | Yes |
| `dedup` | Remove duplicates by field | Yes |
| `unnest` | Flatten arrays into rows | Yes |
| `lookup` | Enrich with lookup table data | Yes |
| `join` | Combine events across log groups by key | Yes |
| `subqueries` | Nested queries as input | Yes |
| `anomaly` | ML anomaly detection | No |
| `pattern` | ML-based log clustering | No |
| `diff` | Compare current vs previous time period | No |
| `unmask` | Reveal data-protection masked content | No |
| `filterIndex` | Force field-index scan optimization | No |
| `SOURCE` | Programmatic log group selection (CLI/API only) | Yes |

Auto-discovered fields: `@timestamp`, `@message`, `@logStream`, `@log` (account-id:log-group-name), `@ingestionTime`, `@entity`. JSON fields auto-flattened with dot notation.

---

## Filter syntax

```
# Comparison: =, !=, <, <=, >, >=
filter statusCode >= 400

# Boolean: and, or, not
filter statusCode >= 400 and statusCode < 500

# Set membership
filter statusCode in [400, 401, 403, 404]

# Substring
filter @message like "ERROR"

# Regex
filter @message like /(?i)error/        # case-insensitive
filter @message =~ /timeout after \d+/  # regex match

# Negation
filter @message not like "DEBUG"
```

**Field index optimization**: Only `filter field = value` and `filter field IN [...]` use indexes. `filter field like` does NOT use indexes.

---

## Parse command

### Glob mode (wildcards)
```
parse @message "User * performed * on *" as user, action, resource
```

### Regex mode (named groups)
```
parse @message /User (?<user>\w+) performed (?<action>\w+)/
```

### Chaining for complex logs
```
# XML parsing
parse @message "<EventData>*</EventData>" as @EventData
| parse @EventData "<Data Name='ObjectName'>*</Data>" as ObjectName
```

---

## Stats and aggregation

```
# Basic aggregation
stats count(*), sum(duration), avg(duration), min(duration), max(duration)

# Percentiles
stats pct(duration, 50) as p50, pct(duration, 95) as p95, pct(duration, 99) as p99

# Time bucketing
stats count(*) as cnt by bin(5m)

# Group by field
stats count(*) as cnt by statusCode

# Combined
stats avg(duration) as avg_ms, pct(duration, 99) as p99 by serviceName, bin(1h)
```

---

## Time functions

- `bin(period)` — time bucketing: `bin(5m)`, `bin(1h)`, `bin(1d)`
- `datefloor(ts, period)`, `dateceil(ts, period)` — truncate/round
- `fromMillis(num)`, `toMillis(ts)` — epoch conversion
- `now()` — time query processing was started, in epoch seconds

**bin() caps**:
- ms → max 1000, s → max 60, m → max 60, h → max 24
- Use `bin(5m)` **NOT** `bin(300s)` — 300 exceeds the s→60 cap

---

## Advanced commands

### JOIN
Correlate events across log groups by a shared key:
```
filter status >= 500
| join type=inner left=api right=infra
    where api.requestId=infra.requestId
    (SOURCE '/aws/infra-logs')
```

### Subqueries
Use nested queries to filter the outer query:
```
filter requestId in (
    SOURCE '/aws/lambda/database-service'
    | filter errorType = "DatabaseConnectionTimeout"
    | fields requestId
)
```

### Anomaly detection
```
fields @timestamp, @message
| filter @message like /ERROR/
| pattern @message
| anomaly
```

### Scheduled queries
Recurring queries with results delivered to S3 and EventBridge. Configure via console or API.

---

## Known issues

1. **Backtick-escape field names with special characters**: `event-name` is interpreted as `event` minus `name`. Use `` `event-name` `` instead.

2. **100 concurrent query limit** per account (not adjustable). Partition queries by time range instead of parallelizing beyond this limit.

3. **JSON structured logs only ~10% faster** than unstructured text search. The real speedup comes from parallelizing across time ranges.

4. **Parallelization strategy**: Break queries into time-range chunks and run in parallel (14 × 12h instead of 1 × 7d). Reduces 84-minute query to ~6 minutes.

5. **`pattern`, `diff`, `unmask`, `anomaly`, and `filterIndex` don't work on Infrequent Access** log class.

6. **`head` and `tail` are deprecated** — use `limit` instead.

7. **StartQuery API**: 10 TPS (most regions). GetQueryResults: 10 TPS.

8. **Max 50 log groups** per query (API-level limit on `logGroupNames`/`logGroupIdentifiers`).

9. **No nested subqueries or correlated subqueries** — only simple subqueries.

10. **Subquery inner execution is limited to 30 seconds**. The overall query timeout is 60 minutes.

---

## Reusable query library

### Error analysis
```
# Recent errors with context
fields @timestamp, @message, @logStream
| filter @message like /ERROR/
| sort @timestamp desc
| limit 100

# Error rate by time bucket
fields @timestamp, @message
| filter @message like /ERROR/
| stats count(*) as errorCount by bin(5m)
| sort errorCount desc

# Top error patterns (ML clustering)
fields @timestamp, @message
| filter @message like /ERROR/
| pattern @message
```

### Lambda-specific
```
# Cold start analysis
filter @type = "REPORT"
| stats avg(@duration) as avg_ms, max(@duration) as max_ms,
        count(*) as invocations,
        sum(strcontains(@message, "Init Duration")) as coldStarts
  by bin(1h)

# Memory utilization
filter @type = "REPORT"
| stats max(@memorySize / 1000 / 1000) as provisioned_mb,
        max(@maxMemoryUsed / 1000 / 1000) as used_mb,
        avg(@maxMemoryUsed * 100 / @memorySize) as utilization_pct
  by bin(1h)

# Timeout detection
filter @message like /Task timed out/
| fields @timestamp, @requestId, @message
| sort @timestamp desc
| limit 20
```

### API Gateway
```
# 5xx errors by endpoint
fields @timestamp, httpMethod, resourcePath, status
| filter status >= 500
| stats count(*) as errors by resourcePath, httpMethod
| sort errors desc

# Latency percentiles by endpoint
fields @timestamp, resourcePath, responseLatency
| stats pct(responseLatency, 50) as p50,
        pct(responseLatency, 90) as p90,
        pct(responseLatency, 99) as p99
  by resourcePath
| sort p99 desc
```

### Cross-service correlation
```
# Multi-log-group error correlation (using SOURCE)
SOURCE logGroups(namePrefix: ['/app-logs', '/api-gateway-logs'])
| fields @timestamp, @message, @log
| filter @message like /ERROR/ or status >= 500
| sort @timestamp desc
| limit 200
```
