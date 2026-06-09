# Production Readiness Checklist

Gate checklist before promoting an ElastiCache cache to production. Run through each section. Items marked REQUIRED are non-negotiable. Items marked RECOMMENDED are best practice but may be deferred with documented justification.

## Security

- [ ] **REQUIRED** In-transit encryption (TLS) enabled. Serverless: automatic. Node-based: set at creation (`TransitEncryptionEnabled: true`), or enabled on existing clusters using the `preferred`->`required` transit encryption mode migration via `modify-replication-group`.
- [ ] **REQUIRED** At-rest encryption enabled. Serverless: automatic. Node-based: must be set at creation (`AtRestEncryptionEnabled: true`). Cannot be added later.
- [ ] **REQUIRED** RBAC or IAM auth configured. No default user active (`modify-user --user-id default --access-string "off ~* -@all"`).
- [ ] **REQUIRED** Security group allows only necessary ports (6379, and 6380 for serverless reader) from application security groups only. No `0.0.0.0/0`.
- [ ] **RECOMMENDED** Security audit passed: `python3 scripts/security_audit.py --serverless <name>` or `--replication-group <name>`.
- [ ] **RECOMMENDED** Credentials stored in Secrets Manager with rotation enabled (if using password auth).

## Availability

- [ ] **REQUIRED** Multi-AZ enabled (node-based). Serverless: automatic.
- [ ] **REQUIRED** Automatic failover enabled (node-based). Serverless: automatic.
- [ ] **REQUIRED** At least 1 replica per shard (node-based). Serverless: automatic.
- [ ] **RECOMMENDED** Subnets span 3 AZs for maximum fault tolerance.

## Backup and Recovery

- [ ] **REQUIRED** Daily backups configured. Node-based: `--snapshot-retention-limit 7` (recommended; valid range is 1-35, 0 disables backups). Serverless: must explicitly set `DailySnapshotTime` and `SnapshotRetentionLimit` (no automatic daily snapshots by default).
- [ ] **RECOMMENDED** Manual pre-deployment snapshot taken and verified.
- [ ] **RECOMMENDED** Restore procedure tested at least once (restore snapshot to a test cluster, validate data).

## Observability

- [ ] **REQUIRED** CloudWatch alarms deployed for critical metrics. Run: `python3 scripts/generate_dashboards.py --serverless <name> --sns-topic <arn> --output observability.json`
- [ ] **REQUIRED** Alarm notification routing configured (SNS to Slack/PagerDuty/email).
- [ ] **RECOMMENDED** Slow log delivery enabled to CloudWatch Logs (JSON format, 30-day retention).
- [ ] **RECOMMENDED** CloudWatch dashboard deployed for visual monitoring.
- [ ] **RECOMMENDED** Baseline metrics observed for 1-2 weeks; alarm thresholds tuned from baseline.

## Application Resilience

- [ ] **REQUIRED** Connection pooling configured in the application. See `monitoring/client-tuning-and-diagnostics.md`.
- [ ] **REQUIRED** Retry logic with exponential backoff implemented (3 retries, 100-200ms base).
- [ ] **REQUIRED** Cache failure graceful degradation tested. Application must function (slower) when cache is unavailable. Cache calls wrapped in try/except.
- [ ] **RECOMMENDED** Client timeouts configured (connect: 2-5s, command: 1-2s). See `monitoring/client-tuning-and-diagnostics.md`.
- [ ] **RECOMMENDED** DNS TTL set to 5 seconds or less in the application to handle failover endpoint changes.
- [ ] **RECOMMENDED** Failover tested with `test-failover` command (node-based) during a maintenance window.

## Cost Controls

- [ ] **REQUIRED** (Serverless) CacheUsageLimits set for both DataStorage and ECPUPerSecond to prevent unbounded cost growth.
- [ ] **RECOMMENDED** Cost allocation tags applied (Environment, Application, Owner).
- [ ] **RECOMMENDED** Cost baseline established. Run `python3 scripts/price_calculator.py --mode serverless --data-gb <N> --ops-per-sec <N>` and `--mode node --node-type <type> --nodes <N> --show-ri-options` to validate deployment model choice.

## Data Integrity

- [ ] **REQUIRED** TTL strategy defined for all key prefixes. No unbounded key growth.
- [ ] **REQUIRED** Eviction policy set appropriately. Serverless: fixed at `volatile-lru` (not configurable; all keys must have TTLs set to be evictable). Node-based: set via parameter group (`allkeys-lru` for general caching, `volatile-lru` if some keys must never be evicted).
- [ ] **RECOMMENDED** Key naming convention documented and consistent across the application.

## Quick Validation Commands

```bash
# 1. Verify security posture
python3 scripts/security_audit.py --serverless <name> --region <region>

# 2. Deploy alarms + dashboard
python3 scripts/generate_dashboards.py --serverless <name> --sns-topic <arn> --output observability.json
aws cloudformation deploy --template-file observability.json --stack-name <name>-observability --region <region>

# 3. Enable slow log (node-based only; serverless does not support log delivery --
#    use CloudWatch metrics and client-side logging for serverless caches)
aws elasticache modify-replication-group --replication-group-id <id> \
  --apply-immediately \
  --log-delivery-configurations '[{"LogType":"slow-log","DestinationType":"cloudwatch-logs","DestinationDetails":{"CloudWatchLogsDetails":{"LogGroup":"/aws/elasticache/<name>/slowlog"}},"LogFormat":"json"}]'

# 4. Verify connectivity from application
python3 scripts/test_connection.py <endpoint>

# 5. Confirm alarms are in OK state
aws cloudwatch describe-alarms --alarm-name-prefix <name> --region <region> --query 'MetricAlarms[].{Name:AlarmName,State:StateValue}'
```

For node-based, replace `--serverless <name>` with `--replication-group <id>`. Log delivery (step 3) applies to node-based clusters only.
