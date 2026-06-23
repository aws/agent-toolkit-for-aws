# Log-analytics capability — entry point and guide

This file is the **entry point** for the `log-analytics` capability. It covers log search at scale, observability, PPL queries, anomaly detection, OpenSearch Dashboards, alerting, and SIEM patterns — including replatforming from Splunk, Datadog, or self-managed ELK.

## When to use this capability

`SKILL.md` routes here when the user is doing **log analytics or observability** on AOS / AOSS. Concrete triggers:

- Phrases: *"PPL query"*, *"OpenSearch Dashboards"*, *"ingest logs"*, *"anomaly detection"*, *"alerting rule"*, *"Splunk replatform"*, *"Datadog alternative"*, *"OSI pipeline"*, *"log search"*, *"SIEM"*
- Tasks: query logs, set up OSI ingestion, configure ISM tiering / UltraWarm, build dashboards, define alerts, replatform a Splunk/Datadog/ELK stack

## All log-analytics files (capability index)

| User need | File |
|---|---|
| Full log analytics workflow | this file |
| Set up OSI ingestion pipelines | [`log-analytics-osi-pipelines.md`](log-analytics-osi-pipelines.md) |
| Replatform from Splunk / Datadog / ELK | [`observability.md`](observability.md) |
| Troubleshoot ingestion or query issues | [`log-analytics-troubleshooting.md`](log-analytics-troubleshooting.md) |

Cross-cutting refs you may also load: [`observability.md`](observability.md) (ISM / UltraWarm / Cold tiering details), [`security.md`](security.md), [`personas.md`](personas.md).

## Cross-capability handoff

- For **provisioning the OSI pipeline infra** (CloudFormation, IAM, source connectors): see [`provisioning-reference.md`](provisioning-reference.md).
- For **migrating an existing Splunk / Datadog / ELK stack**: see [`assessment-workflow.md`](assessment-workflow.md) (use the Splunk-replatform shape).
- For **trace data on the same domain**: see [`trace-analytics-trace-queries.md`](trace-analytics-trace-queries.md).

## Overview

This guide instructs you on how to perform log analytics against an existing OpenSearch domain or collection. The approach is discovery-first: understand what indices exist, learn the schema, sample the data, then build queries. Do not assume any particular index pattern or field names — discover them.

## Data Plane Access with awscurl

Use `awscurl` for SigV4-authenticated HTTP requests to AOS/AOSS endpoints.

### Setup

```bash
pip install awscurl
```

### Environment Variables

| Variable | Example | Description |
|---|---|---|
| `OPENSEARCH_ENDPOINT` | `https://my-domain.us-east-1.es.amazonaws.com` | AOS domain or AOSS collection endpoint |
| `AWS_REGION` | `us-east-1` | AWS region |
| `AWS_PROFILE` | `default` | AWS CLI profile (optional) |

### Base Commands

**AOS (managed domains):**

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "<PPL_QUERY>"}'
```

**AOSS (serverless collections):**

```bash
awscurl --service aoss --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "<PPL_QUERY>"}'
```

> Use `--service es` for AOS domains, `--service aoss` for AOSS collections.

## Security Considerations

- Verify domain/collection encryption at rest is enabled before ingesting sensitive data
- Use fine-grained access control (FGAC) to restrict index and field-level access
- Do not ingest PII or credentials without field-level encryption or masking
- Apply data retention policies via ISM to comply with regulatory requirements
- Enable CloudTrail logging to audit control plane API calls, and enable OpenSearch audit logs to track data plane operations (queries, indexing) for compliance

## Connecting to the Domain/Collection

Determine the domain or collection type and endpoint using the AWS CLI (or `call_aws` if the AWS MCP server is available):

- If the user names a domain: `aws opensearch describe-domain --domain-name <name>` → extract `Endpoint` and `ARN` (region from ARN). With AWS MCP: `call_aws opensearch describe-domain`.
- If the user names a collection: `aws opensearchserverless batch-get-collection --names <name>` → extract `collectionEndpoint`. With AWS MCP: `call_aws opensearchserverless batch-get-collection`.
- If unclear: list with `aws opensearch list-domain-names` or `aws opensearchserverless list-collections`

This is important because the connection method, authentication, and available features differ between AOS domains and AOSS collections.

## Phase 1 — Discover Available Indices

> **AOSS Note:** OpenSearch Serverless does not support `_cat` APIs. Use `--service aoss` instead of `--service es` for all AOSS requests. For index discovery on AOSS, use PPL: `source = * | stats count() by index`.

Before writing any query, find out what log indices exist on the domain or collection.

### List All Indices

```bash
awscurl --service es --region $AWS_REGION \
  "$OPENSEARCH_ENDPOINT/_cat/indices?format=json&h=index,health,docs.count,store.size&s=docs.count:desc"
```

Look for indices that suggest logs: names containing `log`, `logs`, `events`, `audit`, `access`, `syslog`, `otel`, `cwl` (CloudWatch Logs), or date-based patterns like `logs-2024.01.15`.

### List Index Patterns with Aliases

```bash
awscurl --service es --region $AWS_REGION \
  "$OPENSEARCH_ENDPOINT/_cat/aliases?format=json&h=alias,index&s=alias"
```

### Check Data Streams

```bash
awscurl --service es --region $AWS_REGION \
  "$OPENSEARCH_ENDPOINT/_data_stream"
```

After discovering indices, ask the user which index or index pattern they want to analyze if it's not obvious. If there are multiple log indices, ask about the relationship between them (e.g., are they daily rollover indices for the same data? different applications? different log levels?).

## Phase 2 — Understand the Schema

Once you know the target index pattern, inspect its mapping to learn the available fields.

### Get Index Mapping

```bash
awscurl --service es --region $AWS_REGION \
  "$OPENSEARCH_ENDPOINT/<INDEX_PATTERN>/_mapping"
```

Via PPL:

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "describe <INDEX_NAME>"}'
```

> Use a concrete index name (e.g., `logs-2024.01.15`) for `describe`, not a wildcard pattern.

### Identify Key Fields

From the mapping, identify:

1. **Timestamp field** — usually `@timestamp`, `timestamp`, `time`, or `event.created`
2. **Log level field** — `level`, `log.level`, `severity`, `severityText`, `loglevel`
3. **Message field** — `message`, `msg`, `body`, `log`, `event.original`
4. **Service/source field** — `service`, `service.name`, `host.name`, `source`, `kubernetes.pod.name`, `resource.attributes.service.name`
5. **Error fields** — `error.message`, `error.stack_trace`, `exception.type`
6. **Correlation fields** — `traceId`, `trace_id`, `spanId`, `request_id`, `correlation_id`

If the mapping is large or unclear, ask the user: "I see fields like X, Y, Z — which field contains the log message? Which one is the log level?"

### Sample Documents

Always look at a few real documents to understand the actual data shape — mappings alone can be misleading (e.g., dynamic fields, nested objects, multi-value fields):

Via PPL:

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=<INDEX_PATTERN> | head 5"}'
```

Review the sample documents to confirm:

- Which fields are actually populated (vs defined but empty)
- The format of timestamps, log levels, and messages
- Whether the message field is structured JSON or free-text
- Whether there are nested objects that need backtick-quoting in PPL

## Phase 3 — Ask Clarifying Questions (If Needed)

If the schema is not self-explanatory, ask the user:

- "What does this index contain? Application logs, access logs, audit logs?"
- "I see multiple log indices (X, Y, Z) — are these from different services or different time periods?"
- "The message field appears to contain JSON — should I parse specific fields from it?"
- "I see a `trace_id` field — do you want to correlate logs with traces?"
- "What time range are you interested in?"

Do not skip this step if the data is ambiguous. Getting the schema right upfront saves failed queries later.

## Phase 4 — Perform Analytics

With the schema understood, build PPL queries using the actual field names discovered above. All examples below use placeholder field names — substitute with the real ones.

### Running PPL Queries

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "<PPL_QUERY>"}'
```

> For AOSS, use `--service aoss` instead of `--service es`.

### Log Volume Over Time

```
source=<INDEX_PATTERN> | stats count() as volume by span(<TIMESTAMP_FIELD>, 1h)
```

### Error Count by Service

```
source=<INDEX_PATTERN> | where <LEVEL_FIELD> = 'ERROR' | stats count() as errors by <SERVICE_FIELD> | sort - errors
```

### Error Rate Trend

```
source=<INDEX_PATTERN> | stats count() as total, sum(case(<LEVEL_FIELD> = 'ERROR', 1 else 0)) as errors by span(<TIMESTAMP_FIELD>, 1h)
```

### Recent Errors

```
source=<INDEX_PATTERN> | where <LEVEL_FIELD> = 'ERROR' | fields <TIMESTAMP_FIELD>, <SERVICE_FIELD>, <MESSAGE_FIELD> | sort - <TIMESTAMP_FIELD> | head 20
```

### Full-Text Search

```
source=<INDEX_PATTERN> | where match(<MESSAGE_FIELD>, 'connection timeout') | sort - <TIMESTAMP_FIELD> | head 20
```

### Top Error Messages

```
source=<INDEX_PATTERN> | where <LEVEL_FIELD> = 'ERROR' | top 10 <MESSAGE_FIELD>
```

### Rare Error Messages

```
source=<INDEX_PATTERN> | where <LEVEL_FIELD> = 'ERROR' | rare <MESSAGE_FIELD>
```

### Log Pattern Discovery

Automatically cluster similar log messages:

```
source=<INDEX_PATTERN> | where <LEVEL_FIELD> = 'ERROR' | patterns <MESSAGE_FIELD> | fields <MESSAGE_FIELD>, patterns_field | head 30
```

### Error Breakdown by Level and Service

```
source=<INDEX_PATTERN> | stats count() by <LEVEL_FIELD>, <SERVICE_FIELD>
```

### Time-Filtered Queries

```
source=<INDEX_PATTERN> | where <TIMESTAMP_FIELD> > DATE_SUB(NOW(), INTERVAL 1 HOUR) | stats count() by <LEVEL_FIELD>
```

### Unique Services/Hosts

```
source=<INDEX_PATTERN> | stats distinct_count(<SERVICE_FIELD>) as services, distinct_count(<HOST_FIELD>) as hosts
```

### Latency from Structured Logs

If logs contain a duration/latency field:

```
source=<INDEX_PATTERN> | stats avg(<DURATION_FIELD>) as avg_ms, percentile(<DURATION_FIELD>, 95) as p95_ms, percentile(<DURATION_FIELD>, 99) as p99_ms by <SERVICE_FIELD>
```

### Extract Fields from Unstructured Messages

If the message field contains unstructured text, use grok or parse to extract fields:

```
source=<INDEX_PATTERN> | grok <MESSAGE_FIELD> '%{IP:client_ip} %{WORD:method} %{URIPATHPARAM:path} %{NUMBER:status}' | stats count() by status
```

> **Caveat:** `grok` processes all matching rows in memory. Add `| head N` before `grok` on large indices to avoid resource errors.

## Phase 5 — Advanced Analysis

### Cross-Index Correlation

If logs span multiple indices (e.g., application logs + access logs), correlate using shared fields like `request_id`, `trace_id`, or timestamp proximity:

Step 1 — Find an event of interest in one index:

```
source=<APP_LOGS> | where <LEVEL_FIELD> = 'ERROR' | fields <CORRELATION_FIELD>, <TIMESTAMP_FIELD>, <MESSAGE_FIELD> | head 10
```

Step 2 — Look up the same correlation ID in the other index:

```
source=<ACCESS_LOGS> | where <CORRELATION_FIELD> = '<VALUE>' | fields <TIMESTAMP_FIELD>, <MESSAGE_FIELD>
```

### Anomaly Detection

Use PPL's built-in anomaly detection on numeric fields (e.g., log volume, error count):

```
source=<INDEX_PATTERN> | stats count() as volume by span(<TIMESTAMP_FIELD>, 5m) | ad time_field=<TIMESTAMP_FIELD>
```

> The `ad` command auto-detects input fields from the pipeline. It works best on time-series data with regular intervals.

### Query DSL for Complex Aggregations

For queries that PPL doesn't support well (nested aggregations, scripted fields), fall back to Query DSL:

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/<INDEX_PATTERN>/_search" \
  -H 'Content-Type: application/json' \
  -d '{
  "size": 0,
  "query": {
    "bool": {
      "must": [{"match": {"<LEVEL_FIELD>": "ERROR"}}],
      "filter": [{"range": {"<TIMESTAMP_FIELD>": {"gte": "now-1h"}}}]
    }
  },
  "aggs": {
    "by_service": {
      "terms": {"field": "<SERVICE_FIELD>", "size": 20},
      "aggs": {
        "over_time": {
          "date_histogram": {"field": "<TIMESTAMP_FIELD>", "fixed_interval": "5m"}
        }
      }
    }
  }
}'
```

## Common Log Schemas Reference

When you encounter these common schemas, use the field mappings below:

### Elastic Common Schema (ECS)

Timestamp: `@timestamp`, Level: `log.level`, Message: `message`, Service: `service.name`, Host: `host.name`, Error: `error.message`

### OTel Logs (logs-otel-v1-*)

Timestamp: `@timestamp`, Level: `severityText`, Message: `body`, Service: `` `resource.attributes.service.name` `` (backtick-quoted), Trace: `traceId`, Span: `spanId`

### Simple JSON Logs

Timestamp: `timestamp` or `@timestamp`, Level: `level`, Message: `message` or `msg`, Service: `service`, Host: `host`

### Syslog

Timestamp: `@timestamp`, Level: `severity`, Message: `message`, Host: `host`, Program: `program`, Facility: `facility`

### Apache/Nginx Access Logs

Client: `clientip`, Request: `request`, Status: `response`, Bytes: `bytes`, Method: `verb`, Agent: `agent`

## Key PPL Tips for Log Analytics

- Always backtick-quote dotted field names: `` `log.level` ``, `` `host.name` ``
- Use `head N` before memory-intensive commands (`grok`, `streamstats`, `eventstats`)
- Use `span(<timestamp>, <interval>)` for time bucketing — common intervals: `5m`, `15m`, `1h`, `1d`
- Use `match()` for full-text search, `like` for wildcard patterns, `match_phrase()` for exact phrases
- Use `patterns` for automatic log message clustering
- Use `dedup` to find unique error messages: `dedup <MESSAGE_FIELD> | fields <MESSAGE_FIELD>`

## Index Management with awscurl

### Create Log Index with Mappings

```bash
awscurl --service es --region $AWS_REGION \
  -X PUT "$OPENSEARCH_ENDPOINT/application-logs" \
  -H 'Content-Type: application/json' \
  -d '{
  "settings": {"number_of_shards": 1, "number_of_replicas": 1},
  "mappings": {
    "properties": {
      "@timestamp": {"type": "date"},
      "level": {"type": "keyword"},
      "message": {"type": "text"},
      "service": {"type": "keyword"},
      "trace_id": {"type": "keyword"}
    }
  }
}'
```

### Bulk Index Log Documents

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/_bulk" \
  -H 'Content-Type: application/x-ndjson' \
  -d '{"index": {"_index": "application-logs"}}
{"@timestamp": "2024-01-15T10:30:00Z", "level": "ERROR", "message": "Connection timeout to database", "service": "order-service"}
{"index": {"_index": "application-logs"}}
{"@timestamp": "2024-01-15T10:30:05Z", "level": "INFO", "message": "Retry succeeded", "service": "order-service"}
'
```

### Create ISM Policy for Log Rotation

```bash
awscurl --service es --region $AWS_REGION \
  -X PUT "$OPENSEARCH_ENDPOINT/_plugins/_ism/policies/log-rotation-policy" \
  -H 'Content-Type: application/json' \
  -d '{
  "policy": {
    "description": "Hot-warm-delete lifecycle for logs",
    "default_state": "hot",
    "states": [
      {"name": "hot", "actions": [], "transitions": [{"state_name": "warm", "conditions": {"min_index_age": "7d"}}]},
      {"name": "warm", "actions": [{"read_only": {}}], "transitions": [{"state_name": "delete", "conditions": {"min_index_age": "30d"}}]},
      {"name": "delete", "actions": [{"delete": {}}], "transitions": []}
    ],
    "ism_template": [{"index_patterns": ["application-logs*"], "priority": 100}]
  }
}'
```

### Create Data Stream for Time-Series Logs

```bash
# Create index template for data stream
awscurl --service es --region $AWS_REGION \
  -X PUT "$OPENSEARCH_ENDPOINT/_index_template/logs-template" \
  -H 'Content-Type: application/json' \
  -d '{
  "index_patterns": ["logs-*"],
  "data_stream": {},
  "template": {
    "settings": {"number_of_shards": 1},
    "mappings": {
      "properties": {
        "@timestamp": {"type": "date"},
        "message": {"type": "text"},
        "level": {"type": "keyword"}
      }
    }
  }
}'

# Create the data stream
awscurl --service es --region $AWS_REGION \
  -X PUT "$OPENSEARCH_ENDPOINT/_data_stream/logs-stream"
```
