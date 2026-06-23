# Troubleshooting AOS Log Analytics

## Common Issues

| Error | Cause | Fix |
|-------|-------|-----|
| `403 Forbidden` on PPL query | Missing data access policy or FGAC role | Add IAM principal to data access policy; for AOS, map IAM role in Dashboards |
| `index_not_found_exception` | Wrong index pattern or no data ingested | List indices with `GET /_cat/indices`; verify OSI pipeline is running |
| `PPL syntax error` | Unquoted dotted field name | Backtick-quote: `` `log.level` `` not `log.level` |
| OSI pipeline STOPPED | Role permission issue or sink unreachable | Check pipeline logs in CloudWatch; verify role trust policy |
| `SearchPhaseExecutionException` | Query too broad, OOM | Add `head 1000` to limit results; narrow time range with `where` |
| Subscription filter not delivering | Wrong destination ARN or permission | Verify pipeline ARN format and logs:PutSubscriptionFilter permission |

## Debugging OSI Pipelines

1. Check pipeline status: `aws osis get-pipeline --pipeline-name <name>`
2. Check CloudWatch Logs for pipeline errors: `/aws/vendedlogs/OpenSearchIngestion/<pipeline-name>/`
3. Verify source role can read CloudWatch: `aws iam simulate-principal-policy --action-names logs:GetLogEvents`
4. Verify sink role can write to AOS: test with `curl -XPOST` using SigV4

## Debugging PPL Queries

1. Start simple: `source = <index> | head 5` — verify access
2. Check field names: `GET /<index>/_mapping` — confirm exact field paths
3. Narrow time range first, then add filters
4. If `patterns` returns nothing: ensure there are enough documents (needs ≥10 for pattern detection)
