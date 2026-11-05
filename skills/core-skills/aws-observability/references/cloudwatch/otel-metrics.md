# CloudWatch OpenTelemetry metrics

CloudWatch has two metric models:

- **Classic metrics** — namespace + dimensions, published with `PutMetricData` or EMF, read
  with `GetMetricData` / Metrics Insights / metric math. See [metrics.md](metrics.md).
- **OpenTelemetry (OTel) metrics** — ingested over OTLP, labelled with OTel attributes, read
  with PromQL. Querying is in [promql.md](promql.md); this file covers what an agent needs
  to decide, ingest, and debug them. Endpoint limits, pricing, Region availability, and the
  step-by-step collector and SDK setup are in the CloudWatch documentation ("OpenTelemetry
  metrics", "OTLP endpoints") — confirm current values there rather than quoting from
  memory. Deploying a collector or instrumenting an application for the first time is the
  `setting-up-cloudwatch-observability` skill's job.

## Classic or OTel?

| Choose | When |
|---|---|
| **OTel** (the AWS-recommended default for new custom metrics) | New workloads; high-cardinality labels (Kubernetes workload names, customer IDs, OTel semantic-convention attributes); existing PromQL or Grafana content; one OTel pipeline for metrics, logs, and traces |
| **Classic** | Alarms, dashboards, or metric math that already depend on a namespace and dimensions; EMF from Lambda |

The two models do not cross on the query side: PromQL does not read classic custom metrics,
so a metric that must be PromQL-queryable is published over OTLP (or, for a vended AWS
metric, enriched — below). Moving off classic metrics is incremental — publish both ways until
PromQL alarms and widgets replace the classic ones — per the CloudWatch "Migrate from Classic to
OTel metrics" documentation.

## Ingestion — what is easy to get wrong

- **Endpoint and signing:** `https://monitoring.<region>.amazonaws.com/v1/metrics`, signed
  with SigV4 using the service name **`monitoring`**; the IAM action is
  `cloudwatch:PutMetricData`. A bearer token (CloudWatch API key) is the alternative for a
  sender that cannot obtain AWS credentials; it works only for this ingestion endpoint, not
  for queries. Prefer SigV4 with short-term credentials from an IAM role wherever the sender
  can get them. When a key is unavoidable, give it an expiry, keep it in AWS Secrets Manager
  (or SSM Parameter Store as a SecureString), and inject it at runtime (a mounted file or an
  environment variable) — never in the collector configuration itself.
- **HTTP only.** The endpoint does not accept OTLP over gRPC — use the collector's
  `otlphttp` exporter (with the `sigv4auth` or `bearertokenauth` extension) or the SDK's HTTP
  exporter.
- **The `awsemf` exporter produces classic metrics, not OTel metrics.** Its output becomes
  namespace metrics by way of EMF log events, so none of it reaches PromQL. Use the OTLP
  endpoint when the user wants OTel metrics.
- **A 200 response can still be a partial rejection.** Data points that break a limit — too
  many labels (resource, scope, and datapoint attributes count together), oversized label
  metadata, or a timestamp outside the accepted window — are dropped while the request still
  succeeds, so check the response body or the exporter's logs before concluding everything
  landed. The limits themselves are in the "OTLP endpoints" documentation.
- **Temporality is whatever the sender emits.** Delta and cumulative series need different
  PromQL (`sum_over_time` vs `rate`); check `__temporality__` rather than assuming
  ([promql.md](promql.md), section 3).
- **Histograms** keep the sender's type and temporality in `__type__` / `__temporality__`
  (`Histogram` for explicit buckets, `ExponentialHistogram`; cumulative or delta), are read on
  the base name with histogram functions, and percentiles are bucket estimates; when they matter, use exponential bucket aggregation in
  the SDK ("How CloudWatch stores histogram metrics").
- **Cardinality is cheap; bytes are not.** Every label key and value adds to the ingested
  volume, so drop labels nobody queries (request IDs, UUIDs) at the collector. Pricing is in
  the "OTel metrics pricing and storage" documentation.
- **A fresh data point takes a minute or more to become queryable**, so an immediate query after a
  200 can return empty; poll before concluding it was dropped, and end count windows a
  minute or two in the past.
- **Retention** is 15 months, the same as classic metrics — confirm in the CloudWatch "OTel
  metrics pricing and storage" documentation before quoting it.
- **Security:** labels are stored and queryable by anyone with read access to the
  metrics, so keep secrets and personal data out of attribute values. Datasets can be
  encrypted with a customer-managed KMS key; a sender then also needs `kms:Decrypt` on that
  key. OTLP ingestion is recorded as CloudTrail data events on `AWS::CloudWatch::Dataset`
  ([cloudtrail.md](cloudtrail.md)).

## Vended AWS metrics in OTel format (enrichment)

Vended AWS metrics (EC2 `CPUUtilization`, Lambda `Invocations`, …) are classic metrics by
default. **OTel enrichment** additionally projects supported ones onto the PromQL surface,
with no agent or code change; the classic metric is unchanged.

- **Opt-in per account, per Region**, in each Region the user needs.
- **Ordered prerequisite.** First enable **resource tags on telemetry**
  (`aws observabilityadmin start-telemetry-enrichment`, IAM action
  `observabilityadmin:StartTelemetryEnrichment`; check with `get-telemetry-enrichment-status`), **then** OTel enrichment
  (`aws cloudwatch start-otel-enrichment`, IAM action `cloudwatch:StartOTelEnrichment`;
  check with `get-otel-enrichment`). Both are operations of CloudWatch Observability Admin and
  CloudWatch — not of `cloudwatch-omni`. An AWS CLI older than `start-otel-enrichment` lacks
  the subcommand; upgrade the CLI rather than look for it under another service.
- **Mapping is by metric name + identifying dimension → resource ARN**, not by tags. A
  supported resource does not need to be tagged; tags that are present surface as
  `"@aws.tag.*"` labels.
- **Gated on a supported-resource list** in the CloudWatch documentation; only metrics that
  carry a resource-identifier dimension are enriched.
- Scope literals and per-service reads are in [promql.md](promql.md), section 5.
