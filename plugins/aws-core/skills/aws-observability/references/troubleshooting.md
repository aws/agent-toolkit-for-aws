# Observability Troubleshooting

Error → cause → fix for CloudWatch, X-Ray, and CloudTrail issues. Start with the 5 most common fixes.

## Top 5 Fixes

1. **Alarm stuck in INSUFFICIENT_DATA** → Check namespace/dimensions match exactly, verify metric is being published, check missing data treatment setting
2. **Alarm not triggering** → Check Evaluation Range (wider than configured), verify M-of-N settings, check metric delay
3. **Missing logs** → Check log group exists, verify IAM permissions, check log retention hasn't expired (takes up to 72 hours after expiry)
4. **X-Ray traces missing** → Check sampling rules (default: 1/sec + 5%), verify tracing is enabled on all services in the path, check IAM permissions
5. **High CloudWatch bill** → Check log retention (default: never expire), audit GetMetricData callers, check custom metric dimension cardinality

---

## Alarm Issues

### INSUFFICIENT_DATA state

| Symptom | Cause | Fix |
|---------|-------|-----|
| Alarm immediately goes to INSUFFICIENT_DATA | Wrong namespace or dimension names | Verify exact namespace (`AWS/Lambda` not `aws/lambda`) and dimension values match |
| Alarm goes to INSUFFICIENT_DATA after working | Metric stopped being published | Check if the resource still exists and is active |
| Alarm stays in INSUFFICIENT_DATA forever | Metric has no data in evaluation window | Verify metric exists with `aws cloudwatch list-metrics` |
| New alarm starts in INSUFFICIENT_DATA | Normal — no data yet | Wait for at least one evaluation period of data |

### Alarm not triggering

| Symptom | Cause | Fix |
|---------|-------|-----|
| Metric breaching but alarm stays OK | M-of-N not met — only some datapoints breach | Lower M or increase N (e.g., 2 of 5 instead of 3 of 3) |
| Metric breaching but alarm in INSUFFICIENT_DATA | Missing data treatment = `missing` (default) | Change to `notBreaching` for error metrics |
| Dead man switch fires late | Total evaluation window (Periods × Period) exceeds one day | Multi-day alarms are evaluated once per hour — expect delay beyond the configured period |
| Alarm fires then immediately returns to OK | Single spike with M=N=1 | Use M-of-N (e.g., 2 of 3) to require sustained breach |
| Alarm on math expression won't stop EC2 | Metric math alarms cannot perform EC2 actions (stop/terminate/reboot/recover) | Use a simple metric alarm with the per-instance metric and `InstanceId` dimension |

### Alarm flapping (OK → ALARM → OK rapidly)

| Cause | Fix |
|-------|-----|
| Threshold too close to normal | Increase threshold or use anomaly detection |
| M=N=1 catches transient spikes | Use M-of-N (2 of 3 or 3 of 5) |
| Metric is naturally spiky | Use a percentile statistic (`p90`/`p99`) instead of `Maximum`; for non-latency metrics (e.g., CPU), `Average` is also acceptable. Consider anomaly detection for highly variable workloads |

---

## Log Issues

### Missing logs

| Symptom | Cause | Fix |
|---------|-------|-----|
| No logs appearing | Log group doesn't exist | Create log group or verify auto-creation is enabled |
| Logs stopped appearing | IAM permissions changed | Verify `logs:CreateLogStream` and `logs:PutLogEvents` permissions |
| Old logs disappeared | Retention policy expired | Logs deleted up to 72 hours after retention expiry — not recoverable |
| Lambda logs missing | Function missing `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` permissions | Attach `AWSLambdaBasicExecutionRole` |

### Log Insights query issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Query returns no results | Wrong time range or log group | Verify log group name and expand time range |
| `pattern` command fails | Using Infrequent Access log class | `pattern`, `diff`, `unmask`, `anomaly`, `filterIndex` not supported on IA |
| Field not found | JSON field not auto-discovered | Use `parse` to extract, or check field name spelling |
| `event-name` returns wrong results | Interpreted as subtraction | Use backticks: `` `event-name` `` |
| Query times out | Too much data | Narrow time range or parallelize across time chunks |
| `bin(300s)` gives unexpected results | bin() numeric value caps: s→60, ms→1000, m→60, h→24 | Use `bin(5m)` instead of `bin(300s)` |

---

## Metric Issues

### Custom metrics not appearing

| Symptom | Cause | Fix |
|---------|-------|-----|
| Metric not in console | No new data published for 2+ weeks — `list-metrics` and the console stop returning inactive metrics | Use `get-metric-statistics` with exact namespace, metric name, and dimensions — `list-metrics` won't return metrics with no data for 2+ weeks |
| EMF metrics not extracted | Invalid EMF JSON | Validate `_aws.CloudWatchMetrics` structure, check `Timestamp` is in milliseconds |
| Wrong metric values | Dimension mismatch | Each unique dimension combination is a separate metric — verify exact combo |
| Metric shows in wrong namespace | Namespace typo | Namespace is case-sensitive and cannot be changed after creation |

### High metric costs

| Cause | Fix |
|-------|-----|
| Dimension explosion (high-cardinality) | Remove requestId/userId/sessionId from dimensions |
| Third-party tools polling GetMetricData | Use Metric Streams instead; GetMetricData has per-request charges |
| Unused custom metrics | Audit with `list-metrics` and stop publishing unused ones |
| High-resolution metrics (1-second) | Switch to standard (60-second) unless sub-minute granularity is needed |

---

## Tracing Issues

### Missing traces

| Symptom | Cause | Fix |
|---------|-------|-----|
| No traces at all | Tracing not enabled | Enable active tracing on Lambda/API Gateway |
| Partial traces (gaps in service map) | Downstream service not instrumented | Add ADOT/X-Ray instrumentation to all services |
| Low trace volume | Default sampling too conservative | Increase reservoir or rate in sampling rules |
| Traces disappear after 30 days | X-Ray retention is 30 days (not configurable) | Export traces to S3 if longer retention needed |

### Annotation/metadata issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Can't filter traces by custom field | Data stored as metadata (not indexed) | Use annotations for searchable data |
| "Too many annotations" error | Exceeded 50 per trace | Move less-critical data to metadata |
| Annotation key rejected | Invalid characters | Use only alphanumeric + underscore |

---

## CloudTrail Issues

### Can't find events

| Symptom | Cause | Fix |
|---------|-------|-----|
| Event not in Event History | Data event (S3 GetObject, Lambda Invoke) | Enable data events on trail (additional cost) |
| Event older than 90 days | Event History only keeps 90 days | Create a trail to S3 for long-term retention |
| Can't see events from other accounts | Single-account trail | Create organization trail |
| Network activity not logged | Not enabled by default | Enable network activity events on trail |
