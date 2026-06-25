# Observability with Amazon OpenSearch

The summary version is in `SKILL.md` (§ Logs & observability). This file owns the deep playbooks: ISM lifecycle, Splunk/Datadog migration, Trace Analytics, alerting, cost optimization at scale.

## Why OpenSearch for observability

- **Apache 2.0 license** — no per-host or per-GB ingestion tax (unlike Splunk/Datadog).
- **OpenTelemetry-native** end-to-end. Logs/traces/metrics in one engine.
- **PPL** (Piped Processing Language) for logs/traces; **PromQL** for metrics.
- **Trace Analytics** built-in: service map, latency views, RED metrics computed from traces.
- **Alerting** plugin with native SNS/Lambda/Slack destinations.
- **Cost predictability**: cluster cost only; no surprise per-GB ingestion bill.

**Observability features are exposed in OpenSearch UI** (the newer dashboards experience), not the older OpenSearch Dashboards.

## ISM lifecycle (the standard pattern)

```
hot (gp3 EBS, 0–7 days) → UltraWarm (S3-backed, 7–90 days) → Cold (S3, 90–365 days) → delete
```

### Key thresholds

- **UltraWarm cost-effective at ≥ ~2.5 TiB hot data**
- **UltraWarm storage**: $0.024/GiB-month
- **Cold storage**: $0.022/GiB-month, no compute attached
- **Per-node shard cap (current values)**: see [sizing.md §Topology defaults](sizing.md).

### Sample ISM policy (hot → warm → cold → delete)

```json
{
  "policy": {
    "description": "Hot 7d, warm 83d, cold 275d, delete after 365d",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [{ "rollover": { "min_size": "30gb", "min_index_age": "7d" } }],
        "transitions": [{ "state_name": "warm", "conditions": { "min_index_age": "7d" } }]
      },
      {
        "name": "warm",
        "actions": [{ "warm_migration": {} }],
        "transitions": [{ "state_name": "cold", "conditions": { "min_index_age": "90d" } }]
      },
      {
        "name": "cold",
        "actions": [{ "cold_migration": {} }],
        "transitions": [{ "state_name": "delete", "conditions": { "min_index_age": "365d" } }]
      },
      {
        "name": "delete",
        "actions": [{ "cold_delete": {} }]
      }
    ],
    "ism_template": [{ "index_patterns": ["logs-*"] }]
  }
}
```

### ISM gotchas

- ISM jobs run **every 5–8 minutes** (or 30–48 min on pre-1.3 clusters)
- AWS-specific operations: `warm_migration`, `cold_migration`, `cold_delete` (idempotent — operations continue past timeout)
- `open` and `close` ops require ES/OS 7.4+; `snapshot` op requires 7.7+
- AWS-managed ISM cluster settings are restricted: only `plugins.index_state_management.enabled`, `.history.enabled`, and `.rollover_alias` are user-tunable
- Cold storage is **NOT directly queryable** — must thaw to UltraWarm before query (minutes-to-hours)
- ISM templates with `ism_template.index_patterns` apply on index creation; existing indexes need explicit `_opendistro/_ism/add/<index>` call

## Index naming for time-series

| Pattern | When |
|---|---|
| `logs-app-2026-06-01` | Daily rotation; high-volume |
| `logs-app-2026-06` | Monthly; low-volume |
| `logs-app-000001` | Rollover alias; let ISM rollover at size/age |

**ISM rollover** is preferred — it manages the date math for you. Configure with `min_size: 30gb` (search) or `min_size: 50gb` (logs) and `min_index_age: 1d`.

## Trace Analytics

OpenSearch has built-in Trace Analytics:

- **Service map**: visualize service-to-service dependencies, latencies, error rates
- **RED metrics** (Rate, Errors, Duration) per service, computed from traces
- Indexes follow `otel-v1-apm-span-*` and `otel-v1-apm-service-map-*`
- Ingest via **OpenSearch Ingestion** with the OTel processor, or directly via OTel Collector with the OpenSearch exporter

### OTel pipeline (OSI)

```yaml
otel-trace-pipeline:
  source:
    otel_trace_source: {}
  processor:
    - otel_trace_raw: {}
    - otel_trace_group: {}
  sink:
    - opensearch:
        index_type: "trace-analytics-raw"
```

## Alerting

Native Alerting plugin:

- **Per-monitor schedule**: 1 minute minimum (cron or interval)
- **Trigger types**: query-based (search hits exceed threshold), aggregation, anomaly detector signal
- **Destinations**: SNS, Slack, Chime, custom webhook, Microsoft Teams, email
- **Notification channels** centralize destinations (configure once, reuse across monitors)

### Sample monitor

```json
{
  "name": "5xx error spike",
  "type": "monitor",
  "monitor_type": "query_level_monitor",
  "schedule": { "period": { "interval": 1, "unit": "MINUTES" } },
  "inputs": [{
    "search": {
      "indices": ["logs-app-*"],
      "query": {
        "size": 0,
        "query": {
          "bool": {
            "must": [
              { "range": { "@timestamp": { "gte": "now-5m", "lt": "now" } } },
              { "range": { "status": { "gte": 500 } } }
            ]
          }
        },
        "aggs": { "error_count": { "value_count": { "field": "_id" } } }
      }
    }
  }],
  "triggers": [{
    "name": "100+ errors in 5min",
    "condition": { "script": { "source": "ctx.results[0].aggregations.error_count.value > 100", "lang": "painless" } },
    "actions": [{ "destination_id": "<sns-destination>", "subject_template": { "source": "5xx spike", "lang": "mustache" } }]
  }]
}
```

## PPL (Piped Processing Language)

PPL is the SQL/Splunk-style query language for logs. Pipe-separated commands.

### Examples

```ppl
source=logs-app-2026-06-01 | where status >= 500 | stats count() by service | sort -count() | head 10
```

```ppl
source=logs-app-* | where @timestamp >= now() - 1h | parse uri "(?<endpoint>/api/[^?]+)" | stats avg(latency_ms), p99(latency_ms) by endpoint
```

```ppl
source=logs-app-* | eval is_error = if(status >= 500, 1, 0) | stats sum(is_error) as errors, count() as total by service | eval error_rate = errors / total | where error_rate > 0.01
```

PPL operators: `where`, `stats`, `fields`, `eval`, `dedup`, `sort`, `head`, `tail`, `parse`, `rename`, `top`.

## Replacing Splunk

| Splunk concept | OpenSearch equivalent |
|---|---|
| Index | Index |
| Sourcetype | Field (often `service`, `source`) |
| Search head / indexer split | Coordinator / data nodes (mostly transparent on AOS) |
| **SPL queries** | **PPL or DSL** — most queries need rewrite |
| Dashboards | OpenSearch Dashboards / OpenSearch UI |
| Saved searches | Saved searches in Dashboards |
| Alerts | Alerting plugin |
| Apps (e.g., Splunk ES) | Security Analytics plugin (subset) |
| Universal Forwarder | Fluent Bit, Fluentd, OTel Collector, Filebeat-OSS |
| Heavy Forwarder | Data Prepper / OpenSearch Ingestion |
| Indexer cluster | OpenSearch domain |
| Search head cluster | Multi-AZ data nodes |

**Migration scoping** is anchored on **detector / dashboard / pipeline count + complexity classification**, not on calendar duration. Wall-clock depends on team size, parallelism, and reuse pace — pacing is the customer's call, not the skill's.

The streams that decompose any Splunk replatform:

- **Discovery** — inventory every SPL query, dashboard, alert, scheduled search, and custom app. The output is a count by category and a first-pass classification (see below). This is mandatory step 1 — without it the rest is a guess.
- **Data pipeline migration** — forwarders (UF / HF) → OpenSearch Ingestion or Fluent Bit / OTel.
- **Query and dashboard rewrite** — SPL → PPL or DSL. Classify each detector / saved-search:
  - **PPL-translatable** (search → stats / where / sort / dedup / fields) — typically the majority. Mechanical mapping; pattern reuse dominates after the first ~10.
  - **DSL hand-translation required** — correlation searches, multi-search joins, transactions, lookups against external KV stores, complex eventstats — these don't have a clean PPL form and need rewriting against the Query DSL or restructured against `_msearch` / aggregations.
- **Alert / detector rewrite** — onto the Alerting plugin (monitors + triggers + destinations) and Anomaly Detection plugin where applicable; Security Analytics for security-domain detectors.
- **Parallel-run validation** — both stacks live, side-by-side, until detector parity is confirmed.

When responding to a Splunk replatform prompt: NAME the concrete detector / dashboard / pipeline counts the customer gave you and break them down by classification (PPL-translatable vs DSL hand-port; trivial vs complex; correlation searches as their own bucket). Surface the parallelism lever — *"can be compressed by splitting across N engineers"* — without declaring a wall-clock. Do NOT produce week / month / sprint estimates for coding effort: a dedicated team will deliver much faster than a generic estimate suggests, and the customer's own staffing decides the calendar.

## Replacing Datadog

| Datadog concept | OpenSearch equivalent |
|---|---|
| **Logs** | OpenSearch logs (PPL queries) |
| **APM / traces** | Trace Analytics (built-in; less polished than DD) |
| **Metrics** | Prometheus + AMP/Grafana, or Metric Analytics in OS UI |
| **Synthetics** | Not built-in — pair with CloudWatch Synthetics or external tool |
| **RUM** | Not built-in — pair with CloudWatch RUM or external |
| **Notebooks** | OpenSearch Dashboards Notebooks |
| **Watchdog (anomaly detection)** | Anomaly Detection plugin |
| **CSPM / cloud security** | Security Analytics plugin (limited) |
| **Workflow Automation** | Lambda + Alerting destinations |

**Honest assessment:**

- Datadog APM is more polished than OpenSearch Trace Analytics. If APM is your main use case, the gap is real.
- For pure logs + metrics + alerting, OpenSearch is competitive at a fraction of Datadog's cost.
- Scope the rewrite by detector / dashboard / pipeline counts and complexity classification (PPL-translatable vs DSL hand-port), and run the parallel-run validation stream until parity is confirmed. Do not declare a calendar estimate — the universal no-timeline rule applies; pacing is the customer's call.

## Cost optimization at scale

### The Kaltura case study

Kaltura achieved **60% cost reduction** vs prior observability setup by moving to Amazon OpenSearch Service with aggressive ISM tiering. Key levers:

1. **OR1 instances** for ingest tier (logs are write-heavy; OR1 is ~40% cheaper for write workloads)
2. **Aggressive ISM** to UltraWarm at day 7 (or even day 3 for less-queried indexes)
3. **Cold storage** for compliance retention (logs > 90 days where queries are rare)
4. **Single-AZ for non-prod observability** — saves replica cost
5. **Index-per-time-bucket with ISM rollover** to keep shard counts predictable

### Instance family selection for log workloads

For log-analytics workloads, default to OR1 (write-heavy log profile) with UltraWarm tiering for >7-day retention. Full instance family list: [sizing.md §Instance family selection](sizing.md). Source of truth: [supported-instance-types.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/supported-instance-types.html).

**OR1 trade-offs (observability-specific):**

- Replica simplicity: replica=1 is enough (S3 provides durability)
- LOSES on cache-miss aggregations and k-NN graphs (RAM-bound)
- Migration to OR1 is **irreversible**

### Refresh interval tuning

For logs, set `refresh_interval: 30s` or `60s` to reduce CPU overhead from frequent segment refreshes. Default 1s is search-app-tuned.

```json
PUT logs-app-*/_settings
{ "index.refresh_interval": "30s" }
```

### Bulk size for ingest

3–5 MiB per bulk request for general ingest; **10 MiB** for OR1.

### Replicas during ingest

Set `number_of_replicas: 0` during initial bulk load; raise to target after. Halves storage and indexing cost during reindex.

### Translog tuning

`index.translog.durability`:

- `request` (default): fsync per request — durable, slower ingest
- `async`: fsync every `sync_interval` (default 5s) — bigger throughput, seconds-of-data risk on crash

For non-critical observability indexes, `async` typically gives 2–5× ingest throughput improvement.

### Force-merge after rollover

Once an index is rolled over (read-only), force-merge to 1 segment per shard:

```bash
POST logs-app-2026-06-01/_forcemerge?max_num_segments=1
```

Reduces segment count → improves search performance and reduces JVM overhead.

## Watermarks for observability clusters

Defaults (also valid for OpenSearch):

- **low watermark**: 85% — no new shards allocated to this node
- **high watermark**: 90% — cluster actively relocates shards off this node
- **flood_stage**: 95% — applies `index.blocks.read_only_allow_delete=true` on every index

This is THE most common "cluster went read-only at 3am" cause. Set up alerting on `FreeStorageSpace` < 25 GB or storage usage > 80%.

## Logstash with OpenSearch

**Important license gotcha:** the default Logstash distro has a license check that rejects OpenSearch. Two workarounds:

1. Use the **OSS distro** of Logstash (Apache 2.0)
2. Use the `logstash-output-opensearch` plugin

Or skip Logstash entirely and use **OpenSearch Ingestion** (managed Data Prepper) or **Fluent Bit**.

## Anomaly Detection plugin

Built-in Anomaly Detection plugin runs Random Cut Forest models on time-series streams. Common observability uses:

- Detect anomalies in error rate, request rate, or latency per service
- Drive Alerting monitors based on anomaly score
- Train on 8+ days of historical data; updates incrementally

```json
PUT _plugins/_anomaly_detection/detectors
{
  "name": "5xx-anomaly-detector",
  "indices": ["logs-app-*"],
  "feature_attributes": [{
    "feature_name": "5xx-rate",
    "feature_enabled": true,
    "aggregation_query": {
      "5xx_count": { "value_count": { "field": "_id" } }
    }
  }],
  "filter_query": { "range": { "status": { "gte": 500 } } },
  "detection_interval": { "period": { "interval": 1, "unit": "MINUTES" } },
  "window_delay": { "period": { "interval": 1, "unit": "MINUTES" } }
}
```

## Common observability gotchas

1. **CloudWatch Logs subscription** can pipe directly to OSI — handy bridge from CloudWatch to OpenSearch.
2. **Slow logs to CloudWatch** are billable — turn them on selectively, not on all indexes.
3. **AOS automated snapshots are kept 14 days** — don't rely on them as backup. Manual snapshots bill against your S3 bucket.
4. **Cross-AZ data transfer within the cluster is free**; transfer between your VPC and AOS endpoint is billed normally.
5. **Master node sizing**: master nodes scale with cluster size. OS 2.17+: 8 GiB master = up to 30 nodes/15K shards; 32 GiB = 120 nodes/60K shards.
6. **Dashboards multi-tenancy** is enabled by FGAC — supports private and shared tenants.
