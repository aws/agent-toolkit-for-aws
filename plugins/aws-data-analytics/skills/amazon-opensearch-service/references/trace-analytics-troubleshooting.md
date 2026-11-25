# Troubleshooting AOS Trace Analytics

> OpenSearch REST calls in this file go through the `aws_opensearch` capability in `run_script` where the AWS MCP server is available, or `awscurl` otherwise; see [`data-plane-requests.md`](data-plane-requests.md).

## Common Issues

| Error | Cause | Fix |
|-------|-------|-----|
| No trace data in `otel-v1-apm-span-*` | Pipeline not running or misconfigured | `aws osis get-pipeline`; check CloudWatch logs |
| `traceId` not found | Trace hasn't been indexed yet or retention expired | Verify time range; check ISM policy retention |
| PPL returns empty for OTel fields | Field not indexed or wrong name | Sample a doc first; OTel attributes are nested under `attributes.*` |
| Service map empty | Service map processor not configured | Verify OSI pipeline has a sub-pipeline with the `service_map` processor feeding an `index_type: trace-analytics-service-map` sink |
| High latency on trace queries | Large index, no time filter | Always add time range: `where startTime > DATE_SUB(NOW(), INTERVAL 1 HOUR)` |

## Debugging Steps

### No Traces Appearing

1. Check OSI pipeline status: `aws osis get-pipeline --pipeline-name <name>`
2. Check pipeline CloudWatch logs: `/aws/vendedlogs/OpenSearchIngestion/<pipeline-name>/`
3. Verify ADOT collector is sending to correct endpoint
4. Verify trace index exists: `GET /_cat/indices/otel-v1-apm-span-*`
5. Check AOSS data access policy includes pipeline role

### Incomplete Trace Trees

1. Some spans may arrive late — add 1-2 minute buffer before querying
2. If cross-service: verify all services export to the same pipeline
3. Check `parentSpanId` field is populated in child spans

### Application Signals Not Routing to AOS

Application Signals traces reach AOS through the ADOT collector's OTLP exporter, not an X-Ray source. Check:

1. The collector's `traces` pipeline exports through an `otlphttp` exporter to `https://<pipeline-endpoint>/v1/traces`, authenticated by the `sigv4auth` extension with `service: "osis"`. The exporter's `compression` must match the pipeline source.
2. The collector's IAM role has `osis:Ingest` on the pipeline ARN (`arn:aws:osis:<region>:<account>:pipeline/<pipeline-name>`).
3. The pipeline logs in `/aws/vendedlogs/OpenSearchIngestion/<pipeline-name>/` and the `otel_trace_source.badRequests.count` / `requestTimeouts.count` metrics. 408: buffers full (https://docs.aws.amazon.com/opensearch-service/latest/developerguide/osis-features-overview.html). Check sink health (domain/collection throttling) and pipeline OCU use; raise max units if it is at max. 401/403: SigV4 service or `osis:Ingest`. 400/413: payload format or size.

Docs: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/configure-client-otel.html
