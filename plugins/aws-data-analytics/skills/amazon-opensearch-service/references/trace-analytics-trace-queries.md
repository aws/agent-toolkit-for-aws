# Trace-analytics capability — entry point and query templates

This file is the **entry point** for the `trace-analytics` capability. It covers distributed traces with OpenTelemetry — span queries, service maps, latency analysis (p50/p95/p99), error rate by service, and root-cause via parent/child spans.

## When to use this capability

`SKILL.md` routes here when the user is working with **distributed traces** on AOS / AOSS. Concrete triggers:

- Phrases: *"trace analytics"*, *"service map"*, *"otel"*, *"distributed traces"*, *"span query"*, *"otel-v1-apm-span-*"*, *"Data Prepper"*, *"latency p99"*
- Tasks: query trace spans, build service maps, ingest traces (OTel collector → Data Prepper / OSI), troubleshoot trace pipeline or query issues

## All trace-analytics files (capability index)

| User need | File |
|---|---|
| Span queries (PPL on `otel-v1-apm-span-*`) | this file |
| Trace ingestion (OTel collector → Data Prepper / OSI) | [`trace-analytics-trace-ingestion.md`](trace-analytics-trace-ingestion.md) |
| Troubleshoot trace pipeline or queries | [`trace-analytics-troubleshooting.md`](trace-analytics-troubleshooting.md) |

Cross-cutting refs you may also load: [`security.md`](security.md), [`personas.md`](personas.md) (observability-engineer).

## Cross-capability handoff

- For **log queries on the same domain**: see [`log-analytics-guide.md`](log-analytics-guide.md).
- For **provisioning the trace-collector infra** (Data Prepper / OSI / IAM): see [`provisioning-reference.md`](provisioning-reference.md).
- For **OSI pipeline configuration shared with logs**: see [`log-analytics-osi-pipelines.md`](log-analytics-osi-pipelines.md).

## Data Plane Access with awscurl

All queries below use the PPL API at `/_plugins/_ppl`. Use `awscurl` for SigV4-authenticated requests:

### Base Command (AOS)

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "<PPL_QUERY>"}'
```

### Base Command (AOSS)

```bash
awscurl --service aoss --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "<PPL_QUERY>"}'
```

> **Prerequisites:** `pip install awscurl`, AWS credentials configured via `aws configure` or environment variables.

### Verifying Trace Indices

```bash
awscurl --service es --region $AWS_REGION \
  "$OPENSEARCH_ENDPOINT/_cat/indices/otel-v1-apm-*?v&h=index,health,docs.count,store.size"
```

### Sampling Recent Spans

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/otel-v1-apm-span-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{"size": 5, "sort": [{"startTime": "desc"}], "query": {"match_all": {}}}'
```

## Trace Index Key Fields

| Field | Type | Description |
|---|---|---|
| `traceId` | keyword | Unique 128-bit trace identifier |
| `spanId` | keyword | Unique 64-bit span identifier |
| `parentSpanId` | keyword | Parent span ID (empty for root spans) |
| `serviceName` | keyword | Service that produced the span |
| `name` | keyword | Span operation name |
| `kind` | keyword | Span kind (SPAN_KIND_SERVER, SPAN_KIND_CLIENT, SPAN_KIND_INTERNAL, SPAN_KIND_PRODUCER, SPAN_KIND_CONSUMER) |
| `startTime` | date | Span start timestamp |
| `endTime` | date | Span end timestamp |
| `durationInNanos` | long | Span duration in nanoseconds |
| `status.code` | integer | 0=Unset, 1=Ok, 2=Error |
| `attributes.gen_ai.operation.name` | keyword | GenAI operation type |
| `attributes.gen_ai.agent.name` | keyword | Agent name |
| `attributes.gen_ai.agent.id` | keyword | Agent identifier |
| `attributes.gen_ai.request.model` | keyword | Requested model |
| `attributes.gen_ai.usage.input_tokens` | long | Input token count |
| `attributes.gen_ai.usage.output_tokens` | long | Output token count |
| `attributes.gen_ai.tool.name` | keyword | Tool name |
| `attributes.gen_ai.tool.call.id` | keyword | Tool call identifier |
| `attributes.gen_ai.tool.call.arguments` | text | Tool call arguments (JSON) |
| `attributes.gen_ai.tool.call.result` | text | Tool call result (JSON) |
| `attributes.gen_ai.conversation.id` | keyword | Conversation identifier |
| `attributes.error_type` | keyword | Error type category |
| `events.attributes.exception.type` | keyword | Exception class/type |
| `events.attributes.exception.message` | text | Exception message |
| `events.attributes.exception.stacktrace` | text | Exception stacktrace |

## GenAI Operation Types

| Operation | Description |
|---|---|
| `invoke_agent` | Top-level agent invocation |
| `execute_tool` | Tool execution within agent reasoning |
| `chat` | LLM chat completion call |
| `embeddings` | Text embedding generation |
| `retrieval` | Retrieval operation (e.g., RAG) |
| `create_agent` | Agent creation/initialization |
| `text_completion` | Text completion (non-chat) |
| `generate_content` | Generic content generation |

## PPL Query Templates

> **Usage:** Replace `<PPL_QUERY>` in the base command above with any query below. Example:
>
> ```bash
> awscurl --service es --region us-east-1 \
>   -X POST "https://my-domain.us-east-1.es.amazonaws.com/_plugins/_ppl" \
>   -H 'Content-Type: application/json' \
>   -d '{"query": "source=otel-v1-apm-span-* | where `attributes.gen_ai.operation.name` = '\''invoke_agent'\'' | head 20"}'
> ```

### Agent Invocation Spans

```ppl
source = otel-v1-apm-span-* | where `attributes.gen_ai.operation.name` = 'invoke_agent' | fields traceId, spanId, `attributes.gen_ai.agent.name`, `attributes.gen_ai.request.model`, durationInNanos, startTime | sort - startTime | head 20
```

### Tool Execution Spans

```ppl
source = otel-v1-apm-span-* | where `attributes.gen_ai.operation.name` = 'execute_tool' | fields traceId, spanId, `attributes.gen_ai.tool.name`, durationInNanos, startTime | sort - startTime | head 20
```

### Slow Spans

Default threshold: 5 seconds (5,000,000,000 nanoseconds). Adjust as needed.

```ppl
source = otel-v1-apm-span-* | where durationInNanos > 5000000000 | fields traceId, spanId, serviceName, name, durationInNanos, startTime | sort - durationInNanos | head 20
```

### Error Spans

`status.code` = 2 means ERROR in OTel:

```ppl
source = otel-v1-apm-span-* | where `status.code` = 2 | fields traceId, spanId, serviceName, name, `status.code`, startTime | sort - startTime | head 20
```

### Token Usage by Model

```ppl
source = otel-v1-apm-span-* | where `attributes.gen_ai.usage.input_tokens` > 0 | stats sum(`attributes.gen_ai.usage.input_tokens`) as total_input, sum(`attributes.gen_ai.usage.output_tokens`) as total_output by `attributes.gen_ai.request.model`
```

### Token Usage by Agent

```ppl
source = otel-v1-apm-span-* | where `attributes.gen_ai.usage.input_tokens` > 0 | stats sum(`attributes.gen_ai.usage.input_tokens`) as total_input, sum(`attributes.gen_ai.usage.output_tokens`) as total_output by `attributes.gen_ai.agent.name`
```

### Service Operations Listing

```ppl
source = otel-v1-apm-span-* | stats count() by serviceName, `attributes.gen_ai.operation.name`
```

### Trace Tree Reconstruction

```ppl
source = otel-v1-apm-span-* | where traceId = '<TRACE_ID>' | fields traceId, spanId, parentSpanId, serviceName, name, startTime, endTime, durationInNanos, `status.code` | sort startTime
```

### Root Span Identification

```ppl
source = otel-v1-apm-span-* | where traceId = '<TRACE_ID>' AND parentSpanId = '' | fields traceId, spanId, serviceName, name, durationInNanos, startTime, endTime
```

### Spans with Exceptions

```ppl
source = otel-v1-apm-span-* | where `status.code` = 2 | fields traceId, spanId, serviceName, name, `events.attributes.exception.type`, `events.attributes.exception.message`, `attributes.error_type`, startTime | sort - startTime | head 20
```

### Conversation Tracking

```ppl
source = otel-v1-apm-span-* | where `attributes.gen_ai.conversation.id` != '' | stats count() as turns, sum(`attributes.gen_ai.usage.input_tokens`) as total_input_tokens, sum(`attributes.gen_ai.usage.output_tokens`) as total_output_tokens by `attributes.gen_ai.conversation.id`
```

### Tool Call Inspection

```ppl
source = otel-v1-apm-span-* | where `attributes.gen_ai.operation.name` = 'execute_tool' | fields traceId, spanId, `attributes.gen_ai.tool.name`, `attributes.gen_ai.tool.call.id`, `attributes.gen_ai.tool.call.arguments`, `attributes.gen_ai.tool.call.result`, durationInNanos, startTime | sort - startTime | head 20
```

## Service Map Queries

> **Important:** In `otel-v2-apm-service-map-*`, `sourceNode` and `targetNode` are nested struct objects with `keyAttributes.name` for the service name — not flat strings.

### Service Topology

```ppl
source = otel-v2-apm-service-map-* | dedup nodeConnectionHash | fields sourceNode, targetNode, sourceOperation, targetOperation
```

## Remote Service Identification with coalesce()

Different OTel instrumentation libraries use different attributes. Use `coalesce()` to check multiple fields:

```ppl
source = otel-v1-apm-span-* | where serviceName = 'frontend' | where kind = 'SPAN_KIND_CLIENT' | eval _remoteService = coalesce(`attributes.net.peer.name`, `attributes.server.address`, `attributes.rpc.service`, `attributes.db.system`, `attributes.gen_ai.system`, 'unknown') | stats count() as calls by _remoteService | sort - calls
```

## Query DSL Examples (awscurl)

For complex aggregations that PPL doesn't support well, use Query DSL with awscurl:

### Latency Percentiles by Service

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/otel-v1-apm-span-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{
  "size": 0,
  "query": {"range": {"startTime": {"gte": "now-1h"}}},
  "aggs": {
    "by_service": {
      "terms": {"field": "serviceName", "size": 20},
      "aggs": {
        "latency_percentiles": {
          "percentiles": {
            "field": "durationInNanos",
            "percents": [50, 90, 95, 99]
          }
        }
      }
    }
  }
}'
```

### Error Rate by Service

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/otel-v1-apm-span-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{
  "size": 0,
  "query": {"range": {"startTime": {"gte": "now-1h"}}},
  "aggs": {
    "by_service": {
      "terms": {"field": "serviceName", "size": 20},
      "aggs": {
        "total": {"value_count": {"field": "spanId"}},
        "errors": {
          "filter": {"term": {"status.code": 2}},
          "aggs": {
            "count": {"value_count": {"field": "spanId"}}
          }
        }
      }
    }
  }
}'
```

### Throughput Over Time

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/otel-v1-apm-span-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{
  "size": 0,
  "query": {"range": {"startTime": {"gte": "now-1h"}}},
  "aggs": {
    "over_time": {
      "date_histogram": {
        "field": "startTime",
        "fixed_interval": "5m"
      },
      "aggs": {
        "by_service": {
          "terms": {"field": "serviceName", "size": 10}
        }
      }
    }
  }
}'
```

### Slow Operations (P99 > 1s)

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/otel-v1-apm-span-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{
  "size": 0,
  "aggs": {
    "by_operation": {
      "terms": {"field": "name", "size": 50},
      "aggs": {
        "p99_latency": {
          "percentiles": {
            "field": "durationInNanos",
            "percents": [99]
          }
        },
        "high_latency": {
          "bucket_selector": {
            "buckets_path": {"p99": "p99_latency.99"},
            "script": "params.p99 > 1000000000"
          }
        }
      }
    }
  }
}'
```

### Find Spans by Service (DSL)

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/otel-v1-apm-span-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{
  "query": {
    "bool": {
      "must": [
        {"term": {"serviceName": "ORDER_SERVICE"}},
        {"range": {"startTime": {"gte": "now-1h"}}}
      ]
    }
  },
  "sort": [{"startTime": "desc"}],
  "size": 20
}'
```

### Get Full Trace by ID (DSL)

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/otel-v1-apm-span-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{
  "query": {"term": {"traceId": "TRACE_ID_HERE"}},
  "sort": [{"startTime": "asc"}],
  "size": 100
}'
```

### Service Map (DSL)

```bash
awscurl --service es --region $AWS_REGION \
  -X POST "$OPENSEARCH_ENDPOINT/otel-v2-apm-service-map-*/_search" \
  -H 'Content-Type: application/json' \
  -d '{"size": 200, "query": {"match_all": {}}}'
```
