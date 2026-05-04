# CloudWatch Custom Metrics

Publishing, querying, and managing custom metrics — EMF, PutMetricData, metric filters, and retention.

## Contents

- [EMF vs PutMetricData](#emf-vs-putmetricdata)
- [Embedded Metric Format (EMF)](#embedded-metric-format-emf)
- [PutMetricData API](#putmetricdata-api)
- [Metric filters](#metric-filters)
- [Metric retention](#metric-retention)
- [Dimension design](#dimension-design)
- [Metric math](#metric-math)
- [EMF constraints](#emf-constraints)

---

## EMF vs PutMetricData

| Criteria | EMF | PutMetricData |
|----------|-----|---------------|
| Latency impact | None (async via logs) | Synchronous API call |
| Log correlation | Yes — Metrics + logs in same event | No — Separate |
| Max metrics per call | 100 per MetricDirective | 1,000 MetricDatum per request |
| High-resolution | Yes — StorageResolution=1 | Yes — StorageResolution=1 |
| Cost model | Log ingestion pricing | Per-metric API charges |
| Best for | **Lambda, containers** | Batch jobs, custom agents |

**Default recommendation**: Use EMF for Lambda and containerized workloads. Use PutMetricData for batch jobs or when you need synchronous confirmation.

---

## Embedded Metric Format (EMF)

### JSON structure

```json
{
  "_aws": {
    "Timestamp": 1574109732004,
    "CloudWatchMetrics": [{
      "Namespace": "MyService",
      "Dimensions": [["ServiceName", "Environment"]],
      "Metrics": [
        { "Name": "Latency", "Unit": "Milliseconds", "StorageResolution": 60 },
        { "Name": "RequestCount", "Unit": "Count" }
      ]
    }]
  },
  "ServiceName": "OrderService",
  "Environment": "Production",
  "Latency": 100,
  "RequestCount": 1,
  "RequestId": "abc-123"
}
```

### EMF limits

- Max **100 metrics** per MetricDirective
- Max **30 dimensions** per DimensionSet (may be empty)
- Dimension value: max **1024 characters**, must be string
- Metric value: must be numeric or array of numerics (max **100 values**)
- Max log event size: **1 MB**
- Namespace: 1–1024 characters, should not start with `AWS/`
- `Timestamp` in `_aws` is **required** per the EMF spec and JSON schema (milliseconds since epoch). In practice, if omitted, CloudWatch uses the log event's ingestion time — but explicitly setting it is recommended to avoid clock-skew issues.

### EMF libraries

For Lambda/containers, use a library that handles EMF serialization (e.g., Lambda Powertools Metrics, `aws-embedded-metrics`). These libraries manage the `_aws` metadata block, dimension limits, and metric flushing automatically.

---

## PutMetricData API

### Limits

- **500 TPS** per account per region (adjustable via Service Quotas) — NOT 150 TPS
- Up to **1,000 MetricDatum** items per request
- Up to **150 values** per MetricDatum (for percentile statistics support)
- Max **30 dimensions** per metric
- Metric name: max 255 characters
- Namespace: max 255 characters, should not start with `AWS/`

### StatisticSets (batch optimization)
Instead of publishing individual data points, aggregate into StatisticSets:

```json
{
  "MetricName": "Latency",
  "StatisticValues": {
    "SampleCount": 100,
    "Sum": 5000,
    "Minimum": 10,
    "Maximum": 200
  },
  "Unit": "Milliseconds"
}
```

Reduces API calls and cost.

---

## Metric filters

Extract metrics from log events automatically.

- **Max 100 metric filters per log group**
- Filter pattern: space-delimited terms or JSON property matching
- PutMetricFilter API: 5 TPS
- Metric filter → CloudWatch metric → alarm pipeline is the standard log-to-alert pattern

### Example: count 5xx errors from access logs

```
{ $.statusCode >= 500 }
```

Publishes a metric with value 1 for each matching log event.

---

## Metric retention

### Automatic aggregation cascade

| Data point period | Available for | Then aggregated to |
|-------------------|---------------|--------------------|
| < 60s (high-res) | **3 hours** | 1-minute |
| 60s (1 min) | **15 days** | 5-minute |
| 300s (5 min) | **63 days** | 1-hour |
| 3600s (1 hr) | **455 days (15 months)** | — |

**Key insight**: You cannot query 1-minute data from 2 months ago. It has been automatically aggregated to 5-minute resolution. High-resolution (1-second) data is only available for 3 hours.

**OTel metrics**: Only **30 days** retention (public preview) — significantly shorter than traditional CloudWatch metrics (15 months).

### Metric expiry

- Metrics with no new data for **15 months** expire
- Metrics with no data for **2 weeks** are not listed by ListMetrics (but still exist)

---

## Dimension design

**Note**: Each unique dimension combination = separate metric = separate cost.

### Anti-patterns

- Do not use `requestId`, `userId`, `sessionId` as dimensions — creates millions of metrics
- Do not publish `{InstanceId, InstanceType}` and expect to query by `InstanceId` alone — must publish both combinations separately
- Do not use inconsistent units — metrics with different units are separate data streams

### Best practices

- Use low-cardinality dimensions: `ServiceName`, `Environment`, `Operation`, `StatusCode`
- Use the `SEARCH` function for cross-dimension queries
- Always specify units consistently
- Audit custom metrics regularly — remove unused ones

---

## Metric math

Combine metrics using expressions in alarms and dashboards.

### Functions
`SUM`, `AVG`, `MIN`, `MAX`, `STDDEV`, `PERIOD`, `SEARCH`, `IF`, `FILL`, `ANOMALY_DETECTION_BAND`

### Error rate pattern

```
errors * 100 / invocations
```

### SEARCH expression (dynamic metrics)

```
SEARCH('{AWS/Lambda,FunctionName} MetricName="Errors"', 'Sum', 300)
```

Automatically includes new functions matching the pattern — useful in dashboards and graphs (SEARCH cannot be used in alarms).

### Limits

- Max **10 metrics** in a metric math alarm expression
- Use Metrics Insights queries for more (max 10,000 metrics, 500 time series returned)
- Metrics Insights alarm data window: **3 hours** only
- Max **500 metrics+expressions** per dashboard graph

### Metric math in alarms — constraints

- **`FILL` can permanently stick an alarm**: If a metric is published with slight delay, `FILL` replaces the missing latest point with the fill value, keeping the alarm in a fixed state. Use M-of-N alarms instead.
- **`RATE` on sparse metrics is unpredictable**: The evaluation range varies, causing inconsistent rate calculations. Avoid `RATE` in alarms on metrics that don't publish every period.
- **Anomaly detection restrictions** (non-exhaustive): Cannot use more than one `ANOMALY_DETECTION_BAND` per expression, cannot combine with `METRICS()` or `SEARCH`, cannot use high-resolution metrics. See [CloudWatch metric math docs](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/using-metric-math.html) for full list.

---

## EMF constraints

- **Flush interval affects alarms**: Flush EMF logs to CloudWatch at ≤5 second intervals. Longer intervals cause alarms to evaluate partial or missing data. In Lambda (where flush is automatic), use M-of-N alarms to compensate.
- **Monitor EMF parsing failures**: `AWS/Logs` namespace publishes `EMFValidationErrors` and `EMFParsingErrors` metrics. Check these if metrics aren't appearing.
- **Target values cannot be nested**: `"A.a"` matches `{ "A.a": 1 }`, NOT `{ "A": { "a": 1 } }`. Metric and dimension values must be on the root node.
- **Multiple DimensionSets multiply metrics**: `Dimensions: [["Service"], ["Service", "Operation"]]` creates 2 metrics per data point, not 1. Libraries like Powertools do this by default.
- **Dimension key max 250 chars** (per EMF schema); dimension value max 1024 chars.
