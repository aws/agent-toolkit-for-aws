# PromQL in CloudWatch Omni

Metrics in CloudWatch Omni are queried with **PromQL**, not SQL — the SQL dialect in
[sql-logs-traces.md](sql-logs-traces.md) reaches logs and traces only. How to write and run
the PromQL — what is queryable, the `@`-scoped labels, the `__name__` matcher, gauge vs
counter vs delta vs histogram reads, discovery, running a query, the per-service metric
catalog, the service-health checklist, and reading an empty result — is in
**[../../cloudwatch/promql.md](../../cloudwatch/promql.md)**; open it whenever you write or
read a metric query. This file covers the decision between the two surfaces and the Omni
specifics: panels, alerts, and the errors Omni returns.

## Contents

1. [Metrics are PromQL, not SQL](#1-metrics-are-promql-not-sql)
2. [Where PromQL is used in Omni](#2-where-promql-is-used-in-omni)
3. [Discovering metrics from inside Omni](#3-discovering-metrics-from-inside-omni)
4. [Omni-only errors](#4-omni-only-errors)

---

## 1. Metrics are PromQL, not SQL

Omni has two query surfaces, and the shape of the ask decides which one you use:

| The ask is about | Surface | Looks like | Reference |
|---|---|---|---|
| A number over time — CPU, latency, request/error rate, queue depth, throttles, saturation, "how is X trending" | **PromQL** over metrics | An expression that does **not** start with `SELECT`, e.g. `histogram_avg({__name__="CPUUtilization", "@instrumentation.@name"="cloudwatch.aws/ec2"})` | [../../cloudwatch/promql.md](../../cloudwatch/promql.md) |
| Log lines, log fields, log counts by field | **SQL** over `logs.default` | `SELECT ... FROM logs.default WHERE \`@timestamp\` BETWEEN ...` | [sql-logs-traces.md](sql-logs-traces.md) |
| Spans, traces, span attributes, per-span durations | **SQL** over `traces.default` | `SELECT ... FROM traces.default WHERE ...` | [sql-logs-traces.md](sql-logs-traces.md) |

Rules that follow from this:

- **There is no `metrics.default` SQL table.** A metric request is answered with a raw
  PromQL expression, not `SELECT ... FROM metrics.default` — that table does not exist.
  When the ask is for SQL and the signal also lives on spans (latency, error count), give
  the PromQL first and then the SQL over `traces.default` as a separate query (see the
  per-service latency bullet below).
  The one place PromQL text legally appears *inside* SQL is the `promql('<data set>',
  '<expression>', <step-seconds>)` table function — never as a bare expression. Omni's
  `StartTelemetryQuery` does not serve metric reads, so a metric read there fails either
  way: a bare PromQL expression is rejected by the SQL parser with `ValidationException:
  Invalid SQL`, while `SELECT ... FROM metrics.default` or a `promql()` wrapper parses but is
  rejected with `ValidationException: Metrics queries are not supported.`
- **Metrics are queried directly through CloudWatch's Prometheus-compatible HTTP API.**
  An ad hoc or programmatic metric read (a script, the CLI, an AI agent, Grafana) sends
  the PromQL expression to `https://monitoring.<region>.amazonaws.com/api/v1/query` or
  `/api/v1/query_range`, SigV4-signed with the service name `monitoring` (`awscurl
  --service monitoring`, or botocore `SigV4Auth` from code); the CloudWatch MCP server wraps
  the same API as tools (`execute_promql_query`, `execute_promql_range_query`, and the
  discovery tools `get_promql_series`, `get_promql_labels`, `get_promql_label_values`) —
  [../../cloudwatch/promql.md](../../cloudwatch/promql.md), section 4, "Running a PromQL
  query". Run a metric query this way whenever the user wants the numbers; a dashboard
  panel or an alert rule is where a query *lives*, not a prerequisite for running one.
- **Nothing SQL-specific applies to metrics.** `` `@record` ``, `` `@message` ``,
  `TABLESAMPLE`, `EXPLAIN (ANALYZE_FIELDS)`, and fine-grained access control (FGAC) are
  logs/traces features. Metrics do not apply FGAC.
- **No cross-surface JOIN.** There is no metric↔metric or metric↔logs/traces JOIN. Run the
  PromQL query and the SQL query as **separate steps** and line them up on a shared time
  window and a shared identity (service name, function name, instance id).
- **A latency percentile per service** comes from the span-derived histogram, read on its
  base name and grouped by the service label, with the window form chosen by
  `__temporality__` (both occur under one name: CloudWatch's `cloudwatch.aws/xray/span-metrics` series are delta, as below; a collector's `spanmetricsconnector` series are cumulative → `rate`; scope `"@instrumentation.@name"` to one):
  `histogram_quantile(0.99, sum by ("@resource.service.name") (sum_over_time({__name__="traces.span.metrics.duration", "@instrumentation.@name"="cloudwatch.aws/xray/span-metrics", "@resource.service.name"="<service>"}[5m])))`.
  Scope it to the service the user named: an unscoped selector over every service silently
  under-reads each one (HTTP 200, no warning).
  Give the span fallback with it, so the answer still works where no histogram metric
  exists: SQL over `traces.default` per service from `durationNano`, which is a nanosecond
  string — `CAST(durationNano AS DOUBLE)` before ranking or aggregating, and filter
  `durationNano IS NOT NULL`, since NULLs sort first under `DESC`:
  `` SELECT resource['attributes']['service.name'] AS service, approx_percentile_cont(CAST(durationNano AS DOUBLE), 0.99) / 1e6 AS p99_ms FROM traces.default WHERE `@timestamp` BETWEEN NOW() - INTERVAL '1 HOUR' AND NOW() AND durationNano IS NOT NULL GROUP BY 1 ``
  (every Omni SQL query constrains `@timestamp`; set the window to the ask).
- **Derive from spans only as a fallback.** A per-request latency percentile or error
  count can also be computed from `traces.default` (span `durationNano`, `status['code']`)
  in SQL. Prefer the metric when one exists — it is cheaper and pre-aggregated — and
  name the span derivation as the alternative for Spaces where that metric is absent. When you offer
  that fallback, give it whole: `durationNano` is nanoseconds and string-typed, so
  `CAST(durationNano AS DOUBLE)` before ranking or aggregating, and filter
  `durationNano IS NOT NULL`, because NULLs sort first under `DESC`
  ([sql-logs-traces.md](sql-logs-traces.md), "Span Duration").
- **Vended metrics that are not enriched are not queryable.** Vended CloudWatch metrics that
  have not been OTel-enriched, classic custom metrics, and usage/billing-style metrics such as
  `AWS/Logs` `IncomingBytes` are **not available in CloudWatch Omni**: there is no
  `GetMetricData` or Metrics Insights route behind the PromQL surface, and a PromQL query for
  one returns an empty result, not an error. Say so plainly — *"this metric is a classic CloudWatch metric, which CloudWatch
  Omni does not hold; Omni's PromQL covers OTLP, span-derived and OTel-enriched vended metrics"* — and do not
  force a PromQL query that can only return empty. If the
  user only needs the number, offer the CloudWatch route as a separate step (`aws cloudwatch
  get-metric-data`, [../../cloudwatch/metrics.md](../../cloudwatch/metrics.md)); OTel
  enrichment is the fix only for the resource types it supports
  ([../../cloudwatch/promql.md](../../cloudwatch/promql.md), section 2). Do not substitute a
  `logs.default` content scan: a metric such as ingestion volume is not something that
  counting or sizing log records reproduces.
- A custom metric the customer publishes with EMF or `PutMetricData` is a CloudWatch
  metric and is never enriched — enrichment covers AWS-vended service metrics only. To
  get it into Omni, emit it as an OTLP metric through OTel; that is instrumentation, in
  `setting-up-cloudwatch-observability` →
  `references/cloudwatch-omni/instrumentation/instrumentation.md` (§ Custom metrics).
  Enabling enrichment, or getting any metric into Omni, is likewise a setup step: answer it
  from `setting-up-cloudwatch-observability`.

---

## 2. Where PromQL is used in Omni

| Context | Rules |
|---|---|
| **Dashboard panel** ([../dashboards.md](../dashboards.md)) | Each `explore` panel takes a `queryString`, an explicit `queryLanguage` (`"promql"` for metrics, `"sql"` for log/trace content — **not inferred**), `autoRun: true`, and `promqlQueryOptions.step` in seconds. Keep the expression **windowless** — the panel/dashboard `scope` drives the range. A range selector such as `[5m]` inside `sum_over_time` / `rate` is per-point lookback, not a window, and stays. Match `promqlQueryOptions.step` to the range vector — a `[5m]` window at the default 60 s step over-samples 5x; set `step: 300`. The `@`-labels are double-quoted PromQL and therefore JSON-escaped once more inside the `queryString`. The dashboard reference includes per-archetype panel templates whose PromQL follows the conventions in [../../cloudwatch/promql.md](../../cloudwatch/promql.md). |
| **Alert rule** ([../alerts.md](../alerts.md)) | Set `language: PROMQL`. The alert has no window of its own — the expression **must** carry its own range selector (`[5m]`), placed where the instrument type takes a range vector: inside `sum_over_time` for a delta histogram (`histogram_avg(sum_over_time(<sel>[5m]))`, never `histogram_avg(<sel>[5m])`, which fails to parse); see the alerts reference's "Windowing a metric alert". Do **not** bake the threshold comparison into the expression; the threshold is a separate field on the condition. This is the opposite of a CloudWatch PromQL alarm, where every returned series is breaching ([../../cloudwatch/alarms.md](../../cloudwatch/alarms.md)). |
| **Ad hoc `StartTelemetryQuery`** (SQL) | Takes only `queryString` and a `sessionId`; the string is always SQL, with the window in its `` WHERE `@timestamp` BETWEEN ... AND ... `` predicate. PromQL appears only embedded as `promql('<data set>', '<expression>', <step-seconds>)`, and metric reads are not served on this path (section 1). |
| **Views** ([views.md](views.md)) | SQL over logs and traces; they do not wrap PromQL. |

**Selector spelling in panels and alerts:** write the metric with the `__name__` matcher
(`{__name__="<name>", ...}`), the form the panel and alert examples in this skill use.

For the concepts behind Spaces, data sets, and access — which govern what a Space's PromQL
can see — see [../concepts.md](../concepts.md).

---

## 3. Discovering metrics from inside Omni

`ListTelemetryFields` enumerates fields for `LOGS` and `TRACES` only — `METRICS` is not an
accepted `telemetryType` in the current service model, and its `fields` entries carry only
`name` and `children`, with no instrument type or temporality. Discover metric names and
labels with CloudWatch's Prometheus discovery endpoints or the CloudWatch MCP server's
discovery tools instead ([../../cloudwatch/promql.md](../../cloudwatch/promql.md),
section 3); a raw-selector instant query returns the `__type__` / `__temporality__` labels
that decide the read.

---

## 4. Omni-only errors

| Symptom | Cause | Fix |
|---|---|---|
| `ValidationException: Metrics queries are not supported.` | A SQL query (or `promql()` wrapper) aimed at metrics through `StartTelemetryQuery` — there is no `metrics.default` table, and that path does not serve metrics | Write PromQL; run it on CloudWatch's PromQL API, or as a panel or alert with the language set to PromQL |
| `ValidationException: Invalid SQL` on a PromQL expression | A bare PromQL expression sent to `StartTelemetryQuery` | Same as above |
| A PromQL query returns no series, and no error, for a metric CloudWatch shows | The metric is a classic custom metric or a non-enriched vended or usage metric | Vended metric: enable OTel enrichment (if supported). Custom metric (`PutMetricData`, EMF): enrichment never applies — publish it over OTLP. Otherwise use the classic CloudWatch route |
| Alert fires twice as often as expected / cannot be retuned | Threshold comparison baked into the PromQL expression | Remove it; the threshold is a field on the condition ([../alerts.md](../alerts.md)) |
| Dashboard panel frozen or ignoring the time picker | Absolute time pinned in the expression | Keep panel queries windowless; let `scope` drive the range ([../dashboards.md](../dashboards.md)) |
| Panel shows nothing, no error | `queryLanguage` not set to `promql` | Set it explicitly — it is not inferred |

Every other empty-series and wrong-number cause (enrichment, delta temporality, histograms,
units, opt-in metrics) is in [../../cloudwatch/promql.md](../../cloudwatch/promql.md),
section 6.
