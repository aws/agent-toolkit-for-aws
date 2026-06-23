# Troubleshooting AOS Trace Analytics

## Common Issues

| Error | Cause | Fix |
|-------|-------|-----|
| No trace data in `otel-v1-apm-span-*` | Pipeline not running or misconfigured | `aws osis get-pipeline`; check CloudWatch logs |
| `traceId` not found | Trace hasn't been indexed yet or retention expired | Verify time range; check ISM policy retention |
| PPL returns empty for OTel fields | Field not indexed or wrong name | Sample a doc first; OTel attributes are nested under `attributes.*` |
| Service map empty | Service map processor not configured | Verify OSI pipeline has `index_type: trace-analytics-service-map` sink |
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

1. Verify X-Ray is receiving traces in the AWS console
2. Confirm OSI pipeline source is configured for X-Ray format
3. Check IAM role has `xray:GetTraceSummaries` and `xray:BatchGetTraces` permissions
