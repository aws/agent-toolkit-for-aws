# Monitoring & Cost

**When to use:** The user wants to view CloudWatch metrics, set up dashboards or alarms, analyze ElastiCache costs, troubleshoot performance issues, run a security audit, or optimize cache spending.
**When not needed:** The user is creating a new cache (use create-secure-cache.md), choosing an engine or deployment model, writing connection code, or designing data models.

CloudWatch metrics, cost analysis, performance troubleshooting, and cost optimization for ElastiCache.

## Loading

Read this file first. Other references in this folder load on demand when the current answer requires them. Scripts in `scripts/` run on demand (for example, `generate_dashboards.py`, `security_audit.py`). For ElastiCache-specific error codes, see `references/shared-ux/error-remediation.md`.

## On-demand references

| File | Load when |
|------|-----------|
| `troubleshooting.md` | User reports a performance issue, latency, errors, or operational problem |
| `hot-key-detection.md` | User suspects a hot key, uneven shard load, or single-node CPU spike while peers are idle |
| `big-key-hunter.md` | User suspects oversized values, memory growing faster than key count, or latency on HGETALL/LRANGE/SMEMBERS |
| `key-space-distribution-by-prefix.md` | User wants to know what is in their cache by prefix, cost attribution by tenant, or TTL audit |
| `slot-memory-imbalance-detection.md` | User reports one shard full while others are low, hash-tag concentration, or pre-resharding analysis (Valkey 8.0+ cluster mode) |
| `slow-log-cross-signal-diagnosis.md` | User reports intermittent latency spike and needs root-cause correlation (node-based with slow-log enabled) |
| `client-tuning-and-diagnostics.md` | User asks about client timeouts, connection pooling config, TLS setup per language, or missing CloudWatch metrics |
| `alarm-packs.md` | User wants CloudWatch alarms for their cache |
| `cloudwatch-dashboards.md` | User wants a CloudWatch dashboard |
| `event-routing.md` | User wants event notifications, EventBridge rules, or CloudTrail integration |
| `log-delivery.md` | User wants to enable slow log, engine log, or command log delivery |
| `cost-reporting.md` | User wants cost analysis, optimization advice, or spend reporting |

## Symptom-to-File Routing

| User describes | Load |
|----------------|------|
| Slow responses, high latency | `troubleshooting.md` (High Latency) |
| One node hotter than others, uneven load | `hot-key-detection.md` |
| Can't connect, connection errors | `troubleshooting.md` (Cannot Connect) |
| High CPU on one shard | `hot-key-detection.md` then `troubleshooting.md` (High CPU) |
| Cache not helping, low hit rate | `troubleshooting.md` (Low Hit Rate) |
| Memory growing fast, big values suspected | `big-key-hunter.md` |
| Which prefix uses most memory, cost attribution by tenant | `key-space-distribution-by-prefix.md` |
| One shard full, others low, slot imbalance | `slot-memory-imbalance-detection.md` |
| Intermittent latency spike, need root cause | `slow-log-cross-signal-diagnosis.md` |
| Keys without TTL, orphan key cleanup | `key-space-distribution-by-prefix.md` (TTL Audit) |
| Bill too high, cost spike | `cost-reporting.md` |
| Want dashboards or alarms | `cloudwatch-dashboards.md` or `alarm-packs.md` |
| Want event notifications | `event-routing.md` (note: serverless caches do not support SNS topic notifications; instead, ElastiCache sends service events (Cache Created, Cache Updated, Cache Deleted, Snapshot Created, etc.) directly to EventBridge, and API calls are also available via CloudTrail + EventBridge. Node-based clusters use SNS for cluster events. EventBridge receives CloudTrail-derived API events for both deployment models; native ElastiCache service events via EventBridge are serverless-only) |
| Want to enable logging | `log-delivery.md` |
| Metrics not appearing, empty CloudWatch graphs | `client-tuning-and-diagnostics.md` (Missing CloudWatch Metrics) |
| Client timeout tuning, connection pool sizing | `client-tuning-and-diagnostics.md` (Client Timeout / Connection Pooling) |
| TLS connection setup per language | `client-tuning-and-diagnostics.md` (TLS Connection Quick Reference) |
| Specific error code (MOVED, CROSSSLOT, CLUSTERDOWN, WRONGPASS, OOM, READONLY, LOADING, MULTI/EXEC failure, IAM token error) | `references/shared-ux/error-remediation.md` |

## Check for existing context (agent-facing)

Before fetching metrics, check if CloudWatch data or cluster details are already in the conversation context. If `.elasticache/requirements.json` exists, read `infrastructure.cache_name`, `deployment_model`, `engine`, and `engine_version` to avoid re-asking. The engine and version gate certain diagnostics (e.g., CLUSTER SLOT-STATS requires Valkey 8.0+, OBJECT FREQ requires LFU policy).

## Day-1 Observability Checklist

For a newly created cache, run these 5 commands to establish baseline observability:

```bash
# 1. Generate dashboard + alarms
python3 scripts/generate_dashboards.py --serverless <name> --sns-topic <arn> --output observability.json

# 2. Deploy the stack
aws cloudformation deploy --template-file observability.json --stack-name <name>-observability --region <region>

# 3. Enable slow log delivery (node-based only)
# Log delivery (slow log, engine log, command log) is a node-based feature.
# Serverless caches do not support log delivery via the API or console.
# For serverless, use CloudWatch metrics and client-side logging instead.
# For node-based clusters, use modify-replication-group with --apply-immediately
# (see log-delivery.md for details).

# 4. Verify metrics are flowing (wait 5-10 min after first successful command)
# NOTE: CacheHitRate will return empty datapoints until the cache has served
# real traffic. This is expected. If empty, wait and retry after sending test
# commands (e.g., SET/GET). For node-based caches, use CacheHits with the
# CacheClusterId dimension instead (CacheHitRate is available for both serverless and node-based).
aws cloudwatch get-metric-statistics --namespace AWS/ElastiCache --metric-name CacheHitRate \
  --dimensions Name=ServerlessCacheName,Value=<name> --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) --period 300 --statistics Average --region <region>
# macOS: replace -d '1 hour ago' with -v-1H

# 5. Confirm alarm state
aws cloudwatch describe-alarms --alarm-name-prefix <name> --region <region> --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}'
```

For node-based, replace `--serverless <name>` with `--replication-group <id>` in step 1. Log delivery (step 3) applies to node-based clusters only.

## Workflow

1. Identify what the user needs: current metrics, cost data, security posture, or optimization advice
2. Use the AWS CLI or SDK to gather data
3. For collecting raw metrics from a running cache:

   ```bash
   ./scripts/collect_metrics.sh <endpoint> [port] [output_prefix]
   ```

4. If the user doesn't have dashboards/alarms yet, generate them:

   ```bash
   python3 scripts/generate_dashboards.py --serverless <name> --output observability.json
   python3 scripts/generate_dashboards.py --replication-group <name> --output observability.json
   ```

5. For security and operational posture, run the audit:

   ```bash
   python3 scripts/security_audit.py --serverless <name>
   python3 scripts/security_audit.py --replication-group <name>
   ```

6. Present results in a clean summary
7. Recommend optimizations if applicable

For metric names, dimensions, and query examples, see the CLI template in `troubleshooting.md`.

## Freshness disclaimer

When your response includes pricing, version constraints, or feature availability, include the freshness disclaimer per SKILL.md Global Rule #5: "For current pricing see https://aws.amazon.com/elasticache/pricing/. For current feature availability see https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/."

## Cost Analysis

Top 4 optimizations (highest impact first):

1. **Redis OSS to Valkey**: 33% cheaper serverless, 20% cheaper node-based. Zero-downtime in-place upgrade.
2. **Right-size nodes**: If CPU < 20% and memory < 30% sustained, scale down or switch to serverless.
3. **Reserved instances**: Reserved nodes save approximately 30-55% depending on term length and payment option (run `python3 scripts/price_calculator.py --mode node --node-type <type> --nodes <N> --show-ri-options` for current estimates). Node-based only; not applicable to serverless.
4. **Avoid Extended Support charges**: Redis OSS v4 and v5 enter Extended Support on Feb 1, 2026 (v6 on Feb 1, 2027) with escalating yearly premiums. Upgrade to Valkey or a supported version before the end-of-standard-support date to avoid these charges.

For full cost analysis, estimates, and hidden costs, load `cost-reporting.md`. For estimates, use `scripts/price_calculator.py --mode serverless --data-gb <N> --ops-per-sec <N>` and `--mode node --node-type <type> --nodes <N> --show-ri-options`.
