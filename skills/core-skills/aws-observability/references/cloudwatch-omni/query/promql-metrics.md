# Querying metrics in CloudWatch Omni with PromQL

How metric querying works in CloudWatch Omni, and which metric answers which symptom
for each AWS service. Metrics in Omni are queried with **PromQL**, not SQL — the SQL
dialect in [sql-logs-traces.md](sql-logs-traces.md) reaches logs and traces only. This
file covers the decision between the two surfaces, what is and is not queryable, how to
discover metric names and labels, the PromQL conventions Omni adds (the `@`-labels and
the `__name__` matcher), a per-service catalog of the metrics that matter (unit, gauge
vs counter, identity label, derived formulas, dimension traps), and how to read an empty
result.

Treat every metric, label, and scope name in this file as vocabulary to recognise, not
schema to trust. Confirm the exact name against the account's own data (section 3)
before putting it in a query, a dashboard panel, or an alert rule.

## Contents

1. [Metrics are PromQL, not SQL](#1-metrics-are-promql-not-sql)
2. [What is queryable — and what is not](#2-what-is-queryable--and-what-is-not)
3. [Discovering metric names and labels](#3-discovering-metric-names-and-labels)
4. [Query mechanics](#4-query-mechanics)
5. [Per-service metric catalog](#5-per-service-metric-catalog)
6. [Reading results](#6-reading-results)
7. [Where PromQL is used](#7-where-promql-is-used)

---

## 1. Metrics are PromQL, not SQL

Omni has two query surfaces, and the shape of the ask decides which one you use:

| The ask is about | Surface | Looks like | Reference |
|---|---|---|---|
| A number over time — CPU, latency, request/error rate, queue depth, throttles, saturation, "how is X trending" | **PromQL** over metrics | An expression that does **not** start with `SELECT`, e.g.`rate({__name__="Invocations", ...}[5m])` | this file |
| Log lines, log fields, log counts by field | **SQL** over `logs.default`|`SELECT ... FROM logs.default WHERE \`@timestamp\`BETWEEN ...` | [sql-logs-traces.md](sql-logs-traces.md) |
| Spans, traces, span attributes, per-span durations | **SQL** over `traces.default`|`SELECT ... FROM traces.default WHERE ...` | [sql-logs-traces.md](sql-logs-traces.md) |

Rules that follow from this:

- **There is no `metrics.default` SQL table.** A metric request is answered with a raw
  PromQL expression — never `SELECT ... FROM metrics.default`and never a`promql()`
  wrapper inside SQL. A SQL query aimed at metrics is rejected by `StartTelemetryQuery`
  with `ValidationException: Metrics queries are not supported.`
- **Nothing SQL-specific applies to metrics.** `` `@record` ``,`` `@message` ``,
  `TABLESAMPLE`,`EXPLAIN (ANALYZE_FIELDS)`, and fine-grained access control (FGAC)
  are logs/traces features. Metrics do not apply FGAC.
- **No cross-surface JOIN.** There is no metric↔metric or metric↔logs/traces JOIN. To
  correlate a metric with logs or traces, run the PromQL query and the SQL query as
  **separate steps** and line them up on a shared time window and a shared identity
  (service name, function name, instance id).
- **Derive from spans only as a fallback.** A per-request latency percentile or error
  count can also be computed from `traces.default`(span`durationNano`,`status['code']`)
  in SQL. Prefer the metric when one exists — it is cheaper and pre-aggregated — and
  fall back to the span derivation only when no metric grounds the signal.

### How this differs from CloudWatch metrics

CloudWatch (`aws cloudwatch get-metric-data`, metric math, Metrics Insights) and
Omni PromQL are different query models over different surfaces. Do not translate one into
the other mechanically:

| CloudWatch | Omni PromQL |
|---|---|
| Metric is addressed by **namespace** (`AWS/Lambda`) + name + dimensions | Metric is addressed by **name** (via`__name__`) + **labels**; the namespace becomes an instrumentation-scope label (`"@instrumentation.@name"="cloudwatch.aws/lambda"`) |
| **Dimensions** (`FunctionName`) | The same names, as **labels** (`FunctionName="..."`) |
| **Statistic** chosen per query (`Sum`,`Average`,`p99`) | Aggregation is an **operator/function** (`sum`,`avg`,`rate`,`histogram_quantile`) and depends on whether the metric is a gauge, counter, or histogram |
| **Period** | **Range vector** (`[5m]`) plus the **step** of the evaluation (dashboards:`promqlQueryOptions.step`) |
| Metric math expressions (`m1/m2*100`) | Ordinary PromQL arithmetic between series with matching labels |
| Every vended metric is present | Only OTLP metrics, span-derived metrics, and **OTel-enriched** vended metrics are present (section 2) |

For publishing custom metrics, EMF, metric filters, and CloudWatch metric math, see
[../../cloudwatch/metrics.md](../../cloudwatch/metrics.md). If the account does not have Omni
enabled, or the metric is a CloudWatch-only vended metric, the CloudWatch route is the right
answer — not a forced PromQL query.

---

## 2. What is queryable — and what is not

Omni serves metrics from one OpenTelemetry-native, PromQL-queryable surface. It carries
resource and scope **attributes/labels** rather than a CloudWatch namespace.

| Family | What it is | Identity labels | Example |
|---|---|---|---|
| **OTLP-ingested metrics** | Custom application metrics your services emit through an OTel SDK or collector, including Kubernetes workload metrics | `"@resource.service.name"`,`"@resource.k8s.*"`|`http_server_request_duration`,`k8s.pod.phase` |
| **Span-derived RED metrics** | Platform-generated from ingested traces — the rate/error/duration signals the service map and service dashboards use | `"@resource.service.name"`,`"@status.code"`|`traces.span.metrics.calls`(counter),`traces.span.metrics.duration` (native histogram) |
| **OTel-enriched vended AWS metrics** | Metrics AWS services publish natively (EC2, Lambda, RDS, ...) **after** OTel enrichment has projected them onto this surface | `"@instrumentation.@name"="cloudwatch.aws/<service>"`+ the original dimension as a bare label (`InstanceId`,`FunctionName`) |`{__name__="CPUUtilization", "@instrumentation.@name"="cloudwatch.aws/ec2"}` |

### Not queryable: CloudWatch vended metrics that are not enriched

Vended CloudWatch metrics that have **not** been OTel-enriched, and usage/billing-style
metrics such as `AWS/Logs` `IncomingBytes`/`IncomingLogEvents`, are **not yet supported
in CloudWatch Omni**. There is no CloudWatch execution path inside Omni (no `GetMetricData`
or Metrics Insights route behind the PromQL surface).

When the ask resolves to a CloudWatch-only metric:

- Say so plainly: *"CloudWatch metric queries are not yet supported in CloudWatch Omni
  (some vended metrics are not available)."* Do not force a PromQL query that can only
  return empty.
- Do not substitute a log-content scan for a metric. "How much are my log groups
  ingesting?" is a metric question (`IncomingBytes`), not a`logs.default` query.
- If the user only needs the number, offer the **CloudWatch** route as a
  separate, non-Omni step (`aws cloudwatch get-metric-data`; see
  [../../cloudwatch/metrics.md](../../cloudwatch/metrics.md)). If they want it in Omni, the
  fix is enrichment (below) — for resource types enrichment supports.

### OTel enrichment for vended AWS metrics

Vended AWS metrics are CloudWatch metrics by default. **OTel enrichment** ("vended metrics
in PromQL" in the AWS documentation) is the opt-in feature that also projects them onto
the PromQL surface:

- **Opt-in per account, per region.** Enable it in each region you need. The CloudWatch
  metric is unchanged and stays available through the CloudWatch APIs.
- **Ordered prerequisite.** First enable **resource tags on telemetry** for the account
  (`aws observabilityadmin start-telemetry-enrichment`, IAM action
  `observabilityadmin:StartTelemetryEnrichment`, which provisions the Resource Explorer
  indexing that enrichment relies on; check with `get-telemetry-enrichment-status`),
  **then** enable OTel enrichment (`aws cloudwatch start-otel-enrichment`, IAM action
  `cloudwatch:StartOTelEnrichment`; check with`get-otel-enrichment`, disable with
  `stop-otel-enrichment`). Both are public operations of their own services — CloudWatch
  Observability Admin and CloudWatch — not of `cloudwatch-omni`, and the CloudWatch API
  itself documents this order. An AWS CLI released before `start-otel-enrichment` will
  not have that subcommand; upgrade the CLI rather than look for it under another
  service.
- **Mapping is by metric name + dimensions → resource ARN**, not by tags. A supported
  resource does **not** need to be tagged to become PromQL-queryable; tags that are
  present are simply surfaced as `@aws.tag.*` labels.
- **Gated on a supported-resource list.** Only supported AWS resource types are
  enriched.
- **Names are preserved.** The metric keeps its CloudWatch name (`CPUUtilization`,
  `4xxErrors`), its dimensions become PromQL labels, and it gains an instrumentation
  scope label `"@instrumentation.@name"="cloudwatch.aws/<service>"` (service segment
  lowercase).

So "why isn't my EC2 / Lambda metric in PromQL?" almost always means one of: enrichment
is not enabled for that account/region, resource-tags-on-telemetry was never enabled
first, or the resource type is not on the supported list.

---

## 3. Discovering metric names and labels

Metric names, label names, and scope spellings are **not guaranteed** — they depend on
what has been ingested and enriched in this account. A misspelled name does not error; it
returns an empty series. Discover before you write.

**Method 1 (not available for metrics): `ListTelemetryFields`.** The
`ListTelemetryFields`API enumerates the known fields of a data set for`LOGS` and
`TRACES`only —`METRICS`is not an accepted`telemetryType` in the current service
model (the value was removed), so there is no API call that lists metric names. Its
`fields`entries carry only`name`and`children`, so even for the telemetry types it
does cover it returns no instrument type (Sum / Gauge / Histogram) and no temporality
(delta / cumulative). For metrics, take names from the catalog below or from Method 2,
and derive the instrument type from the catalog or from the metric's behaviour (a
monotonically increasing series is a counter).

Once you know the instrument type, read the aggregation off it:

| Instrument type | Read it with |
|---|---|
| Gauge | `avg()`/`max()`/`min()`— never`rate()` |
| Sum, **cumulative** | `rate()`/`increase()` |
| Sum, **delta** | `sum_over_time(<m>[w])` |
| Histogram | `histogram_quantile(0.99, rate(<base>[5m]))`on the **base** name — no`_bucket`, no`by (le)` |

**Method 2: probe with a selector.** Once you have a candidate name, run a narrow
instant selector over a short window and inspect the label set that comes back:

```promql
{__name__="Invocations", "@instrumentation.@name"="cloudwatch.aws/lambda"}
```

The returned series show every label the metric actually carries (`FunctionName`,
`@aws.account`,`@aws.region`, any`@aws.tag.*`), which is what you group and filter by.

**Do not** use the SQL discovery tools for metrics — `EXPLAIN (ANALYZE_FIELDS)` and
`SELECT \`@record\`` are logs/traces-only.

Use the names discovery returns **exactly** — do not shorten, alias, pluralize, or
invent. Nouns in the request ("throttles", "5xx", "timeouts") describe what to aggregate,
not field names; map each to a real, grounded metric.

---

## 4. Query mechanics

### Label conventions

Labels on Omni's metrics surface follow an `@`-prefixed convention:

| Label form | Meaning | Examples |
|---|---|---|
| `"@resource.*"`| Resource attributes — the identity of an OTLP-native workload |`"@resource.service.name"`,`"@resource.k8s.namespace.name"`,`"@resource.k8s.deployment.name"`,`"@resource.k8s.pod.name"`,`"@resource.cloud.resource_id"` |
| `"@instrumentation.@name"`| Instrumentation scope — how an **enriched vended AWS metric** is scoped to its service (lowercase service segment). Replaces the CloudWatch`AWS/<Service>`namespace |`"cloudwatch.aws/ec2"`,`"cloudwatch.aws/lambda"`,`"cloudwatch.aws/rds"` |
| `"@aws.tag.*"`| Resource tags surfaced by enrichment |`"@aws.tag.Environment"` |
| `"@aws.*"`(without`tag`) | Reserved system labels |`"@aws.account"`,`"@aws.region"` |
| bare names | Datapoint attributes — the original CloudWatch dimensions of a vended metric | `InstanceId`,`FunctionName`,`TableName`,`QueueName` |

**Quoting rule:** any label name that is dotted or `@`-prefixed must be **double-quoted
inside the braces** — `{"@instrumentation.@name"="cloudwatch.aws/ec2"}`. The same
applies inside `by (...)`:`sum by ("@resource.service.name") (...)`. Bare dimension
labels (`InstanceId`) are written unquoted as usual.

For OTLP / Kubernetes workloads and span RED metrics, the identity is **always** a
`"@resource.*"`label. Never use a generic Prometheus`job=`or bare`service=`
selector, and never the underscore `k8s_*` form — those are ungrounded and return
nothing.

### Selecting a metric: the `__name__` matcher

A PromQL metric name is really the reserved `__name__` label. A name that starts with a
digit or contains `%`,`.`, or spaces is **not** a legal bare identifier — common for
vended AWS metrics (`4xxErrors`,`4XXError`,`5XXError`,`4xxErrorRate`,`EBSIOBalance%`,
`Memory % Committed Bytes In Use`) and for every dotted OTel name
(`traces.span.metrics.calls`). Select those with a`__name__` matcher inside the braces:

```promql
{__name__="4xxErrors", FilterId="EntireBucket"}
{__name__="EBSIOBalance%", InstanceId="<instance-id>"}
{__name__="traces.span.metrics.calls", "@resource.service.name"="<service>"}
```

The value is an ordinary double-quoted string, so any character is legal there. A plain
identifier-safe name (`CPUUtilization`,`http_requests_total`) may be written bare
(`CPUUtilization{InstanceId="..."}`), but the`__name__` form always works — prefer it
for vended metrics so the scope and dimensions read uniformly:

```promql
{__name__="Errors", "@instrumentation.@name"="cloudwatch.aws/lambda", FunctionName="<fn>"}
{__name__="CPUUtilization", "@instrumentation.@name"="cloudwatch.aws/ec2", InstanceId="<id>"}
```

**Never write the metric name as a bare token inside the braces** (a leading `"name",`
before the label matchers). That form does not parse on this surface. This applies
everywhere a metric is selected, including inside `rate(...)`,`sum(...)`, and
`histogram_quantile(...)`.

### Gauge, counter, histogram — the read decides the function

- **Gauge** — a level (CPU %, queue depth, free memory, connections, latency of a
  vended metric). Read with `avg`/`max`/`min`. **Never`rate()` a gauge.**
- **Counter (cumulative Sum)** — accumulates (requests, bytes, errors, invocations).
  Read with `rate()`(per-second) or`increase()` (total over the window). **Never read a
  raw counter value or average it.**
- **Delta Sum** — a per-interval count that does not accumulate. Read with
  `sum_over_time(<m>[w])`.
- **Histogram** — `traces.span.metrics.duration` is a native exponential histogram. Read
  percentiles with `histogram_quantile(0.99, rate({__name__="traces.span.metrics.duration", ...}[5m]))`
  on the **base** metric name — no `_bucket`suffix, no`by (le)`.
- **Already-per-second gauges** (RDS `ReadIOPS`,`ReadThroughput`) must **not** be
  wrapped in `rate()` — that double-rates into nonsense.

Applying `rate()` to a gauge, or averaging a per-period counter, is the most common way
to produce a confident-but-meaningless number. When unsure, check the instrument type
via discovery (section 3).

### Time range binding

Where the query runs decides how time is expressed:

| Context | Time handling |
|---|---|
| **Interactive / ad hoc query** | `StartTelemetryQuery`takes only`queryString`and a`sessionId`(from`StartTelemetryQuerySession`); results come back through`GetTelemetryQueryResults`. There is no language or time-range parameter because the query string is always parsed as SQL — a bare PromQL expression fails with`ValidationException`. PromQL reaches this path only embedded as the table function`promql('<data set>', '<expression>', <step-seconds>)`inside a SQL statement, and the evaluation window is that relation's mandatory`WHERE \`@timestamp\`BETWEEN ... AND ...`predicate. Metrics through`StartTelemetryQuery`are disabled per account at GA (`ValidationException: Metrics queries are not supported.`, section 1), so for an ad hoc metric read use a dashboard panel or an alert rule, where the language is explicit and the service does the wrapping. |
| **Dashboard panel** ([../dashboards.md](../dashboards.md)) | Keep the expression **windowless** — the panel/dashboard `scope`drives the range. Set`queryLanguage: "promql"`explicitly and match`promqlQueryOptions.step`(seconds) to the range vector — a`[5m]`window at the default 60 s step over-samples 5x; set`step: 300`. |
| **Alert rule** ([../alerts.md](../alerts.md)) | The alert has no window of its own — the expression **must** carry its own range selector (`[5m]`). Do **not** bake the threshold comparison into the expression; the threshold is a separate field on the condition. Set`language: PROMQL`. |

### Common functions

| Need | Expression shape |
|---|---|
| Per-second rate of a counter | `rate(<selector>[5m])` |
| Total increase over a window | `increase(<selector>[1h])` |
| Aggregate across series | `sum(...)`,`avg(...)`,`max(...)`,`min(...)`,`count(...)` |
| Group by an identity | `sum by (FunctionName) (rate(...))`,`avg by ("@resource.service.name") (...)` |
| Top N | `topk(10, sum by (...) (rate(...)))` |
| Ratio / derived metric | `rate(<errors>[5m]) / rate(<total>[5m])`(labels must match on both sides; add`on (...)`/`ignoring (...)` when they do not) |
| Percentile from a native histogram | `histogram_quantile(0.99, rate(<base>[5m]))` |
| Smooth a gauge | `avg_over_time(<gauge>[15m])`,`max_over_time(<gauge>[15m])` |

Worked examples:

```promql
# Lambda error rate per function (both counters -> rate, then divide)
sum by (FunctionName) (rate({__name__="Errors", "@instrumentation.@name"="cloudwatch.aws/lambda"}[5m]))
  /
sum by (FunctionName) (rate({__name__="Invocations", "@instrumentation.@name"="cloudwatch.aws/lambda"}[5m]))

# Request rate per service from span RED metrics
sum by ("@resource.service.name") (rate({__name__="traces.span.metrics.calls"}[5m]))

# p99 latency per service from the native histogram
histogram_quantile(0.99, sum by ("@resource.service.name") (rate({__name__="traces.span.metrics.duration"}[5m])))

# Pods per deployment in a namespace (gauge -> count as-is)
count by ("@resource.k8s.deployment.name") ({__name__="k8s.pod.phase", "@resource.k8s.namespace.name"="<ns>"})

# S3 request error ratio (digit-leading names -> __name__)
rate({__name__="4xxErrors", FilterId="EntireBucket"}[5m]) / rate({__name__="AllRequests", FilterId="EntireBucket"}[5m])
```

---

## 5. Per-service metric catalog

Each section names the CloudWatch namespace (for recognition only — the CloudWatch surface is
not queryable here) and the **identity label** to filter and group by. On the PromQL
surface an enriched vended metric is reached via
`"@instrumentation.@name"="cloudwatch.aws/<service>"` (lowercase) plus the identity
label. Confirm the exact scope and label spelling against discovery.

Two universal rules:

- **Gauge vs counter decides the read** (section 4).
- **An empty series is often correct, not a bug.** A signal that exists only under a
  specific configuration (an agent installed, a burstable instance type, a
  request-metrics filter, an export enabled) returns nothing when that condition is
  absent. Read "no data" as "not configured / not applicable here" before treating it as
  an outage.

Signal taxonomies:

- **Request-serving services** (ALB, API Gateway, CloudFront, S3 request metrics,
  Application Signals) → **RED**: Rate, Errors, Duration.
- **Resources / infrastructure** (EC2, EBS, RDS, ECS, Lambda concurrency) → **USE /
  saturation**: Utilization, Saturation, Errors, plus headroom signals (credit balances,
  free storage, free memory, queue depth) that trend toward a limit.
- **Flow / queue services** (SQS, SNS) → throughput (counters) vs backlog and age
  (gauges).

### EC2 — `AWS/EC2`(+`CWAgent`), identity`InstanceId`

| Metric | Type | Unit | Read as |
|---|---|---|---|
| `CPUUtilization`| gauge | Percent |`avg`/`max`— never`rate()` |
| `CPUCreditBalance`| gauge | Credits |`min` — burstable (T-family) only |
| `NetworkIn`/`NetworkOut`/`NetworkPacketsIn`/`NetworkPacketsOut`| counter | Bytes / Count |`rate()` |
| `DiskReadBytes`/`DiskWriteBytes`/`DiskReadOps`/`DiskWriteOps`| counter | Bytes / Count |`rate()` — **instance-store only**, not EBS |
| `StatusCheckFailed`/`_Instance`/`_System`/`_AttachedEBS`| binary per-period | 0/1 |`max`— a`1` means it failed in the period; averaging hides it |
| `InstanceEBSIOPSExceededCheck`/`InstanceEBSThroughputExceededCheck`| binary | 0/1 |`max` (Nitro) |
| `EBSIOBalance%`/`EBSByteBalance%`| gauge | Percent |`min`—`__name__` form |
| `mem_used_percent`,`disk_used_percent`(CWAgent) | gauge | Percent |`avg` — **only if the CloudWatch agent is installed** |

- Burstable instance pinned at baseline with `CPUCreditBalance` near 0 is throttling, not
  health. `CPUCreditBalance` is empty on non-burstable types (correct).
- Memory and disk-**space** metrics exist only in `CWAgent`; an empty guest-OS chart
  usually means "no agent," not "no data" — the hypervisor cannot see guest RAM.
- `_System`= AWS hardware;`_Instance` = your OS/network.
- Correlate with: EBS (volume side of the same I/O), ALB (instances as targets), RDS
  (app tier driving the DB).

### EBS — `AWS/EBS`, identity`VolumeId`

| Metric | Type | Unit | Read as |
|---|---|---|---|
| `VolumeReadOps`/`VolumeWriteOps`/`VolumeReadBytes`/`VolumeWriteBytes`| counter | Count / Bytes |`rate()` |
| `VolumeTotalReadTime`/`VolumeTotalWriteTime` | counter | Seconds | derived latency only (Xen-era) |
| `VolumeAvgReadLatency`/`VolumeAvgWriteLatency`| gauge | ms |`avg`/`max` (Nitro — prefer these) |
| `VolumeAvgIOPS`/`VolumeAvgThroughput`| gauge | ops/s / KiB/s |`avg` (Nitro) |
| `VolumeIOPSExceededCheck`/`VolumeThroughputExceededCheck`/`VolumeStalledIOCheck`| binary | 0/1 |`max` |
| `VolumeQueueLength`| gauge | Count |`avg`/`max` — a count, not a duration |
| `BurstBalance`| gauge | Percent |`min` — gp2/st1/sc1 only |

- **Xen-era latency is derived:** per-op read latency ≈
  `rate(VolumeTotalReadTime[5m]) / rate(VolumeReadOps[5m])` (x1000 for ms) — an average
  only, never a percentile. On Nitro, `VolumeTotalReadTime` is documented as not
  relevant; use the `VolumeAvg*` gauges.
- `BurstBalance` is empty on gp3/io1/io2 (correct).
- Correlate with: EC2 (instance side), RDS (its storage behaves like an EBS volume — a
  write-latency spike with healthy CPU points at storage).

### Lambda — `AWS/Lambda`, identity`FunctionName`

| Metric | Type | Unit | Read as |
|---|---|---|---|
| `Invocations`/`Errors`/`Throttles`| counter | Count |`rate()` |
| `Duration`| gauge | ms |`avg`/`max` — no percentile label on this surface |
| `ConcurrentExecutions`| gauge | Count |`max` |
| `ProvisionedConcurrencyUtilization`/`ClaimedAccountConcurrency`| gauge | ratio 0–1 (e.g.`0.7`, not a percent) / Count |`max` (saturation) |
| `UnreservedConcurrentExecutions`| gauge | Count | account/region-level — **no`FunctionName`** |
| `AsyncEventsReceived`/`AsyncEventsDropped`| counter | Count |`rate()` |
| `AsyncEventAge`| gauge | ms |`max` (async backlog) |
| `IteratorAge`| gauge | ms |`max` — Kinesis / DynamoDB Streams consumer lag |
| `OffsetLag`| gauge | Count |`max` — Kafka / MSK consumer lag |

- **Error rate is derived:** `rate(Errors) / rate(Invocations)` (section 4 example). Do
  not read `Errors` alone without the denominator.
- Grouping `UnreservedConcurrentExecutions` by function returns nothing (correct).
- Cold starts are **not** a metric (`Duration` excludes cold-start time) — cold-start and
  error detail live in the function log group `/aws/lambda/<function>`, a SQL log query.
- A true pNN for `Duration` is not available on this surface — chart avg/max, or derive
  the percentile from spans in SQL.
- Correlate with: API Gateway / ALB (invokers), SQS / DynamoDB (event sources).

### DynamoDB — `AWS/DynamoDB`, identity`TableName`

| Metric | Type | Unit | Dimensions | Read as |
|---|---|---|---|---|
| `SuccessfulRequestLatency`| gauge | ms |`TableName`,`Operation`|`avg`/`max` — group by **both** or GetItem/Query/Scan blend |
| `ThrottledRequests`| counter | Count |`TableName`,`Operation`|`rate()` |
| `ConsumedReadCapacityUnits`/`ConsumedWriteCapacityUnits`| counter | Units |`TableName`,`GlobalSecondaryIndexName`(writes add`Source`) |`rate()`/`increase()`— **no`Operation`** |
| `ReadThrottleEvents`/`WriteThrottleEvents`| counter | Count |`TableName`,`GlobalSecondaryIndexName`|`rate()` |
| `SystemErrors`| counter | Count |`TableName`,`Operation`|`rate()`— **not published on`TableName` alone** |
| `UserErrors`| counter | Count | account/region-level |`rate()` |
| `ConditionalCheckFailedRequests`/`TransactionConflict`| counter | Count |`TableName`|`rate()` (secondary) |

- A `SystemErrors`alert scoped to`TableName` only never has data — include
  `Operation`.
- Compare consumed against provisioned capacity for saturation.
- Correlate with: Lambda (pair throttles with function errors), Application Signals.

### ECS — `AWS/ECS`and`ECS/ContainerInsights`, identity`ClusterName`(+`ServiceName`)

| Metric | Type | Unit | Tier | Read as |
|---|---|---|---|---|
| `CPUUtilization`/`MemoryUtilization`| gauge | Percent | cluster or service |`avg`/`max` |
| `EBSFilesystemUtilization`| gauge | Percent | service (with an EBS volume) |`max` |
| `CPUReservation`/`MemoryReservation`/`GPUReservation`| gauge | Percent | **cluster,`AWS/ECS`, EC2 launch type only** |`avg` |
| `RunningTaskCount`/`PendingTaskCount`/`DesiredTaskCount`| gauge | Count | Container Insights (opt-in) |`max`/`min` |

- **Split the tiers by dimension:** service-tier series carry `ClusterName` **and** a
  non-empty `ServiceName`; cluster-tier series carry`ClusterName` only. Filtering the
  wrong one blends or empties the series.
- Fargate emits no reservation metrics; `GPUReservation` also needs GPU instances (both
  correct-empty). Reservations are not under Container Insights.
- Correlate with: ALB (in front), EC2 (container instances for EC2 launch type).

### RDS — `AWS/RDS`, identity`DBInstanceIdentifier`

| Metric | Type | Unit | Read as |
|---|---|---|---|
| `CPUUtilization`| gauge | Percent |`avg`/`max` |
| `DatabaseConnections`| gauge | Count |`avg`/`max`— never`rate()` |
| `ReadIOPS`/`WriteIOPS`| gauge (already per-second) | Count/s |`avg`— **do not`rate()`** |
| `ReadThroughput`/`WriteThroughput`| gauge (already per-second) | Bytes/s |`avg`— **do not`rate()`** |
| `ReadLatency`/`WriteLatency`| gauge | **Seconds** |`avg`/`max` (x1000 for ms) — raw, not derived |
| `DiskQueueDepth`| gauge | Count |`max` (storage saturation) |
| `FreeableMemory`/`FreeStorageSpace`| gauge | Bytes |`min` — **free**, so alert *below* a threshold |
| `ReplicaLag`| gauge | Seconds |`max` |
| `BurstBalance`,`EBSIOBalance%`,`EBSByteBalance%`| gauge | Percent |`min`— burstable storage only;`__name__`form for`%` |
| `ServerlessDatabaseCapacity`| gauge | ACUs |`avg` — Aurora Serverless only |

- Best chart: `CPUUtilization`overlaid with`DatabaseConnections`. CPU tracking
  connections is an app problem; CPU high at flat connections is a query/plan problem.
- RDS has no `*TotalTime` metrics — latency is raw, unlike EBS.
- Logs require export: `/aws/rds/instance/<id>/<logType>` (error / slowquery / audit /
  general / postgresql); the error log is free-form.
- Correlate with: EBS (storage layer), EC2 (app tier).

### Application Load Balancer — `AWS/ApplicationELB`, identity`LoadBalancer`

| Metric | Type | Unit | Read as |
|---|---|---|---|
| `RequestCount`/`ActiveConnectionCount`| counter | Count |`rate()` |
| `HTTPCode_Target_2XX_Count`/`_3XX_`/`_4XX_`/`_5XX_Count`| counter | Count |`rate()` — target-generated |
| `HTTPCode_ELB_3XX_Count`/`_4XX_`/`_5XX_Count`(+`_500_`/`_502_`/`_503_`/`_504_Count`) | counter | Count |`rate()` — **LB-generated, a different family** |
| `TargetResponseTime`| gauge | **Seconds** |`avg`/`max` (x1000 for ms) — no percentile label |
| `HealthyHostCount`/`UnHealthyHostCount`| gauge | Count |`min`/`max`— per`TargetGroup` only |
| `RejectedConnectionCount`/`TargetConnectionErrorCount`/`TargetTLSNegotiationErrorCount`| counter | Count |`rate()` (saturation / connection errors) |
| `LambdaUserError`/`LambdaInternalError`| counter | Count |`rate()` (Lambda targets) |

- The names carry a **`_Count`suffix** —`HTTPCode_Target_5XX` alone returns nothing.
- An ELB-5xx spike with flat target-5xx points at the LB / health-check path (e.g. no
  healthy target), not the app.
- The `LoadBalancer`label value is the`app/<name>/<hash>` segment, not the full ARN.
  ALB (`AWS/ApplicationELB`) ≠ NLB (`AWS/NetworkELB`) ≠ CloudWatch (`AWS/ELB`).
- Fractional host counts are normal from flapping.
- Correlate with: EC2 (instance targets), Lambda (Lambda targets).

### SQS — `AWS/SQS`, identity`QueueName`

| Metric | Type | Unit | Read as |
|---|---|---|---|
| `ApproximateAgeOfOldestMessage`| gauge | Seconds |`max` — **the best signal** |
| `ApproximateNumberOfMessagesVisible`| gauge | Count |`max` (backlog) |
| `ApproximateNumberOfMessagesNotVisible`| gauge | Count |`max` (in flight — **not** backlog) |
| `ApproximateNumberOfMessagesDelayed`| gauge | Count |`max` (delay timer) |
| `NumberOfMessagesSent`/`Received`/`Deleted`| counter | Count |`sum(rate(...))` — not the average |

- A low-depth queue with high oldest-age is a poison pill or stalled consumer.
- Total enqueued ≈ Visible + NotVisible + Delayed.
- FIFO queues share the same metrics. A dead-letter queue is just another `QueueName` —
  rising Visible on a DLQ means the source queue is failing processing.
- Correlate with: SNS (fan-out source), Lambda (event-source-mapping consumer — pair
  age/backlog with function `Errors`/`Throttles`/`Duration`).

### SNS — `AWS/SNS`, identity`TopicName`

| Metric | Type | Unit | Read as |
|---|---|---|---|
| `NumberOfMessagesPublished`/`NumberOfNotificationsDelivered`/`NumberOfNotificationsFailed`| counter | Count |`rate()` |
| `NumberOfNotificationsFilteredOut`(+`-MessageAttributes`/`-MessageBody`/`-InvalidAttributes`) | counter | Count |`rate()` — "why didn't my subscriber get it" |
| `NumberOfNotificationsRedrivenToDlq`/`NumberOfNotificationsFailedToRedriveToDlq`| counter | Count |`rate()` |
| `PublishSize`| gauge | Bytes |`avg` |
| `SMSSuccessRate`| gauge | Fraction |`avg`— a`sum` is meaningless |
| `SMSMonthToDateSpentUSD`| cumulative, resets monthly | USD |`max`within the month — never`rate()` |

- `NumberOfNotificationsFailed` is a **delivery** failure — a failed Publish call surfaces
  in API 4xx/5xx, not here.
- **Do not compute delivered / published as a success rate**: one publish fans out to N
  subscribers, so delivered normally exceeds published.
- Correlate with: SQS (subscriber queue depth / DLQ), Lambda (subscribed functions).

### S3 — `AWS/S3`, identity`BucketName` (two families)

| Family | Metric | Type | Unit | Required label | Read as |
|---|---|---|---|---|---|
| Storage (daily, free) | `BucketSizeBytes`| gauge | Bytes |`StorageType`(e.g.`StandardStorage`) |`max` over a multi-day window |
| Storage (daily, free) | `NumberOfObjects`| gauge | Count |`StorageType="AllStorageTypes"`|`max` over a multi-day window |
| Request (1-minute, opt-in, billed) | `AllRequests`,`GetRequests`,`PutRequests`, ... | counter | Count |`FilterId`(commonly`EntireBucket`) |`rate()` |
| Request | `4xxErrors`/`5xxErrors`| counter | Count |`FilterId`|`rate()`—`__name__` form |
| Request | `FirstByteLatency`/`TotalRequestLatency`| gauge | ms |`FilterId`|`avg`/`max` |

- Storage metrics look flat or broken at short ranges because emission is daily.
  Omitting `StorageType` returns multiple or no series.
- Request metrics exist only where a request-metrics filter is configured; omitting
  `FilterId` double-counts. An empty request overview is a config gap, not a bug.
- Error ratio: see the S3 example in section 4.
- Correlate with: CloudFront (most public reads hit the CDN and never reach S3 request
  metrics), ALB (same RED grammar).

### API Gateway — `AWS/ApiGateway`, identity varies by flavour

| Flavour | Identity | RED metrics | Error metrics |
|---|---|---|---|
| REST (v1) | `ApiName`(+`Stage`,`Resource`,`Method`) |`Count`(counter),`Latency`,`IntegrationLatency`(gauges, ms) |`4XXError`/`5XXError`(counters,`__name__` form) |
| HTTP (v2) | `ApiId`(+`Stage`,`Route`) |`Count`,`Latency`,`IntegrationLatency`,`DataProcessed`|`4xx`/`5xx`(counters,`__name__` form) |
| WebSocket (v2) | `ApiId`(+`Stage`,`Route`) |`ConnectCount`,`MessageCount`,`IntegrationLatency`|`IntegrationError`,`ClientError`,`ExecutionError` |

- Using the wrong identity label (`ApiName`vs`ApiId`) returns an empty series.
  WebSocket APIs do **not** emit `4xx`/`5xx`/`Count`/`Latency`.
- Derived: gateway overhead = `Latency - IntegrationLatency`. High`Latency` with flat
  `IntegrationLatency` implicates the gateway/config; the reverse implicates the backend.
- `CacheHitCount`/`CacheMissCount` are empty unless caching is enabled (correct).
  Method/route-level metrics need "detailed metrics" enabled. Access/execution logs are
  opt-in with no fixed group name.
- Correlate with: Lambda (pair `IntegrationLatency`with`Duration`), Application
  Signals.

### CloudFront — `AWS/CloudFront`, identity`DistributionId`(+ fixed`Region="Global"`)

| Metric | Type | Unit | Read as |
|---|---|---|---|
| `Requests`| counter | Count |`rate()`for req/s,`increase()` for a daily total |
| `BytesDownloaded`/`BytesUploaded`| counter | Bytes |`rate()` |
| `TotalErrorRate`/`4xxErrorRate`/`5xxErrorRate`| gauge | Percent |`avg`— **never`rate()`, never divide by`Requests`** (already a percentage);`__name__` form |

- 4xx (client / cache-miss 403/404) vs 5xx (origin-fetch) split the headline error rate.
- Metrics live only in `us-east-1`under`Region="Global"` regardless of edge location —
  query us-east-1; never emit another region matcher for CloudFront.
- Cache-hit-rate and per-edge metrics are opt-in (paid). Access logs go to S3 or a
  stream, not CloudWatch Logs.
- Correlate with: S3 (pair `5xxErrorRate`with S3`5xxErrors`), ALB origin (target 5xx).

### Application Signals — `AWS/ApplicationSignals`, identity`Service`(SLOs:`SloName`)

| Metric | Type | Unit | Read as |
|---|---|---|---|
| `Latency`| gauge | ms |`avg`/`max` |
| `Fault`| counter | Count |`rate()` — HTTP 5xx + OTel span-status errors |
| `Error`| counter | Count |`rate()` — HTTP 4xx client errors (excluding intentional, e.g. 429) |
| `TotalRequestCountPerMinute`/`BadRequestCountPerMinute`| counter | Count |`rate()` (request-based SLOs; observability only) |
| `AttainmentRate`/`BreachedCount`| gauge / counter | Percent / Count |`min`/`rate()`— dimensioned by **`SloName`** |

- The names are **`Fault`/`Error`**, not`FaultCount`/`ErrorCount`. Service
  dimensions are `Service`,`Operation`,`Environment`; dependency metrics add
  `RemoteService`/`RemoteOperation`.
- **Availability** = `(1 - Fault / Total) x 100`, where Total is the request count
  (classically `SampleCount(Latency)`).
- This is the entry point for "how is `<service>` doing?" when the entity is an
  Application Signals service or SLO — it aggregates across the infrastructure services
  above.
- Correlate with: the infrastructure behind the span (EC2/ECS/Lambda), and the traces
  themselves for the offending span path.

### Kubernetes / EKS (OTLP) — identity `"@resource.service.name"`(RED),`"@resource.k8s.*"` (USE)

OTLP-ingested Kubernetes workloads have no CloudWatch namespace and no vended-AWS
instrumentation scope. Group and filter by the double-quoted `"@resource.*"` labels.

| Signal | Metric | Type | Read as |
|---|---|---|---|
| Request / error rate | `traces.span.metrics.calls`| counter |`sum by ("@resource.service.name") (rate(...[5m]))`; split errors by`"@status.code"` |
| Latency p50/p90/p99 | `traces.span.metrics.duration`| native histogram |`histogram_quantile(0.99, rate(...[5m]))` on the base name |
| Container / pod CPU and memory vs requests/limits | OTLP `k8s.*`/`container.*`resource metrics | gauge |`avg`/`max`, grouped by`"@resource.k8s.namespace.name"`→`"@resource.k8s.deployment.name"`→`"@resource.k8s.pod.name"` (broadest to narrowest) |
| Restarts, pod phase | `k8s.container.restarts`,`k8s.pod.phase`| counter / gauge |`increase()`/`count by (...)` |

- This is the same span-derived layer the service map uses.
- An empty series usually means the workload is not exporting that OTLP metric (no
  collector/exporter for it), not that usage is zero.
- Correlate with: Application Signals (application-scoped RED of the same spans), node /
  EC2 metrics for host-level saturation.

---

## 6. Reading results

### Empty series: expected vs real

Before treating "no data" as an outage, check whether the metric can exist here:

| Empty series on | Usually means |
|---|---|
| Any vended AWS metric (`CPUUtilization`,`Invocations`, ...) | OTel enrichment is not enabled for this account/region, resource-tags-on-telemetry was not enabled first, or the resource type is not supported (section 2) |
| A metric selected with a bare dotted/digit-leading name | Parse problem — use the `__name__` form (section 4) |
| A vended metric with the wrong identity label (`ApiName`vs`ApiId`,`HTTPCode_Target_5XX`without`_Count`) | Wrong label or name — re-check discovery |
| `CPUCreditBalance`,`BurstBalance`,`EBSIOBalance%` | Non-burstable instance / volume type — correct |
| `CWAgent` memory / disk-space metrics | CloudWatch agent not installed — correct |
| S3 request metrics | No request-metrics filter configured — correct |
| S3 storage metrics at a short range | Daily emission — widen to multiple days |
| ECS reservations | Fargate, or a service-tier filter on a cluster-tier metric |
| `UnreservedConcurrentExecutions`grouped by function;`SystemErrors`on`TableName` alone | Metric is not published at that dimensionality |
| CloudFront outside `us-east-1`/ with a region matcher | Metrics exist only under`Region="Global"` in us-east-1 |
| API Gateway `4xx`/`Count`/`Latency` on a WebSocket API | WebSocket emits a different set |
| Any OTLP / Kubernetes metric | Not exported by the workload's collector |
| Any `"@resource.*"`grouping | Used`job=`/`service=`/`k8s_*`instead of the`"@resource.*"` form |

An empty result is **not** a reason to fabricate a number or switch to a log scan; it is
a reason to re-ground the name (section 3) or explain the missing configuration.

### Common errors and their causes

| Symptom | Cause | Fix |
|---|---|---|
| `ValidationException: Metrics queries are not supported.`| A SQL query aimed at metrics (`FROM metrics.default`) | Write PromQL; set the language to PromQL |
| "CloudWatch metric queries are not yet supported in CloudWatch Omni (some vended metrics are not available)." | The metric is a non-enriched vended or usage metric | Enable enrichment (if supported), or use CloudWatch outside Omni |
| Parse error on a selector | Metric name written as a bare token inside the braces, or a dotted / `@`label left unquoted |`{__name__="<name>", "@label"="..."}` |
| A rate that is impossibly small or noisy | `rate()`applied to a gauge, or to an already-per-second gauge (RDS IOPS/throughput) | Read gauges with`avg`/`max` |
| A "count" that never grows / averages to nonsense | `avg()`on a counter |`rate()`/`increase()` |
| A percentile that disagrees with the console | Requested pNN on a vended gauge (`Duration`,`TargetResponseTime`,`SuccessfulRequestLatency`) that has no percentile label here | Chart avg/max, or derive from spans in SQL |
| Latency off by 1000x | Unit mismatch — ALB `TargetResponseTime`and RDS`*Latency`are **seconds**; Lambda`Duration`, DynamoDB, EBS`VolumeAvg*` are **ms** | Convert explicitly |
| Alert fires twice as often as expected / cannot be retuned | Threshold comparison baked into the PromQL expression | Remove it; the threshold is a field on the condition ([../alerts.md](../alerts.md)) |
| Dashboard panel frozen or ignoring the time picker | Absolute time pinned in the expression | Keep panel queries windowless; let `scope` drive the range ([../dashboards.md](../dashboards.md)) |
| Panel shows nothing, no error | `queryLanguage`not set to`promql` | Set it explicitly — it is not inferred |

---

## 7. Where PromQL is used

PromQL is the metric language everywhere in Omni, not only for ad hoc queries:

- **Dashboards** — [../dashboards.md](../dashboards.md). Each `explore` panel takes a
  `queryString`, an explicit`queryLanguage`(`"promql"`for metrics,`"sql"` for
  log/trace content), `autoRun: true`, and`promqlQueryOptions.step` in seconds. Panel
  expressions are **windowless**; the `@`-labels are double-quoted PromQL and therefore
  JSON-escaped once more inside the `queryString`. The dashboard reference includes
  per-archetype panel templates (Lambda, EC2, ALB, RDS, Kubernetes) whose PromQL follows
  the conventions in this file.
- **Alerts** — [../alerts.md](../alerts.md). A condition on a metric must use
  `language: PROMQL`; the expression carries its own range selector (`[5m]`) and no
  threshold comparison. Metric alerts on a gauge, a counter rate, or a
  `histogram_quantile` percentile all go through this path; SQL alerts reach logs and
  traces only.
- **Ad hoc queries** — `StartTelemetryQuery`(`queryString`+`sessionId`) and
  `GetTelemetryQueryResults` carry no language or time-range parameter: the query
  string is always SQL, PromQL is accepted only embedded as
  `promql('<data set>', '<expression>', <step-seconds>)` with the window bound by that
  relation's `@timestamp` predicate, and metrics through this path are disabled per
  account at GA (section 1; section 4, "Time range binding"). Prefer a dashboard panel
  or an alert rule.
- **Views** — [views.md](views.md) are SQL over logs and traces; they do not wrap PromQL.

For the concepts behind Spaces, data sets, and access — which govern what an account's
PromQL can see — see [../concepts.md](../concepts.md).
