# Event Routing

How to capture, route, and act on ElastiCache operational events across node-based and serverless deployments.

## Event Sources Overview

| Event Source | What It Captures | Deployment Type | Destination |
|-------------|-----------------|-----------------|-------------|
| ElastiCache cluster events (SNS) | Failover, maintenance, scaling, snapshot, configuration changes | Node-based | SNS topic |
| DescribeEvents API | Same as SNS but pull-based; also supports serverless-cache and serverless-cache-snapshot source types | Both | API response |
| CloudTrail | All ElastiCache API calls (create, modify, delete, describe) | Both | S3, CloudWatch Logs |
| EventBridge (via CloudTrail) | CloudTrail-derived API events for rule-based routing | Both | Lambda, SNS, SQS, Step Functions, etc. |
| EventBridge (direct service events) | Cache lifecycle events: Cache Created, Cache Deleted, Cache Updated, Cache Limit Approaching, Snapshot Created, etc. | Serverless | Lambda, SNS, SQS, Step Functions, etc. |

## Node-Based Event Pipeline

Node-based clusters emit operational events via SNS and the DescribeEvents API. **Note:** Node-based clusters use SNS for real-time cluster event notifications and EventBridge for CloudTrail-derived API events. Native ElastiCache service events via EventBridge are serverless-only.

### SNS Notifications

ElastiCache publishes cluster events directly to an SNS topic. This is the fastest way to get notified about operational events.

**SNS topic constraints:**

- Only **one** SNS topic can be configured per cluster for ElastiCache notifications.
- The SNS topic **cannot be encrypted** (at-rest). Attaching an encrypted topic will cause its status to show as "inactive", effectively disassociating it from the cluster.
- The SNS topic must be in the **same Region** as the ElastiCache cluster.
- The AWS account owning the SNS topic must be the **same account** that owns the cluster.

> **Security note:** Because at-rest encryption is not supported on this topic, event data (cluster names, failover and maintenance details) is stored unencrypted in SNS. Restrict the topic access policy to authorized principals only, and use HTTPS-only subscription protocols to protect events in transit.

For Valkey/Redis OSS replication groups:

```bash
aws elasticache modify-replication-group \
  --replication-group-id my-cluster \
  --notification-topic-arn arn:aws:sns:us-east-1:123456789012:elasticache-events \
  --notification-topic-status active \
  --apply-immediately \
  --region us-east-1
```

For Memcached clusters (which use cache clusters, not replication groups):

```bash
aws elasticache modify-cache-cluster \
  --cache-cluster-id my-memcached-cluster \
  --notification-topic-arn arn:aws:sns:us-east-1:123456789012:elasticache-events \
  --notification-topic-status active \
  --apply-immediately \
  --region us-east-1
```

**Key events delivered via SNS:**

| Event Type | Description | Action |
|-----------|-------------|--------|
| `ElastiCache:FailoverComplete` | Failover completed (Valkey/Redis OSS) | Verify application reconnection; check for data loss |
| `ElastiCache:CacheClusterProvisioningComplete` | Cluster provisioning finished | Verify cluster health; begin application traffic |
| `ElastiCache:CacheClusterScalingComplete` | Node type change or shard modification finished | Verify performance post-scaling |
| `ElastiCache:CacheClusterScalingFailed` | Scaling operation failed | Investigate; retry or revert |
| `ElastiCache:SnapshotComplete` | Backup creation finished (Valkey/Redis OSS) | No action needed |
| `ElastiCache:SnapshotFailed` | Backup creation failed (Valkey/Redis OSS) | Investigate; check snapshot limits |
| `ElastiCache:NodeReplacementScheduled` | Upcoming node replacement (maintenance) | Plan maintenance window; inform team |
| `ElastiCache:ServiceUpdateAvailableForNode` | Patch or version update available | Review release notes; schedule application |
| `ElastiCache:CacheNodeReplaceStarted` | Node replacement in progress | Monitor; expect brief disruption |
| `ElastiCache:CacheNodeReplaceComplete` | Node replacement finished | Verify cluster health |

### DescribeEvents API (Pull-Based)

```bash
# For node-based clusters:
aws elasticache describe-events \
  --source-type replication-group \
  --source-identifier my-cluster \
  --duration 1440 \
  --region us-east-1

# For serverless caches:
aws elasticache describe-events \
  --source-type serverless-cache \
  --max-items 40 \
  --region us-east-1
```

DescribeEvents supports both node-based and serverless source types. Valid `--source-type` values include: `cache-cluster`, `replication-group`, `serverless-cache`, `serverless-cache-snapshot`, `user`, `user-group`, and others. Events can be retrieved for up to 14 days.

## Serverless Event Pipeline

ElastiCache emits native service events directly to EventBridge for serverless caches (best-effort delivery). Serverless caches do not support SNS topic notifications; use EventBridge for serverless event routing.

### Native EventBridge Service Events

ElastiCache sends these events directly to EventBridge for serverless caches:

| Detail-Type | Category | Description |
|-------------|----------|-------------|
| `Cache Created` | notification | Serverless cache provisioning complete |
| `Cache Creation Failed` | notification | Serverless cache provisioning failed |
| `Cache Deleted` | notification | Serverless cache deleted |
| `Cache Updated` | notification | Serverless cache modification complete |
| `Cache Update Failed` | notification | Serverless cache modification failed |
| `Cache Limit Approaching` | notification | A slot is using more than X% of the 32 GB per-slot limit |
| `Snapshot Created` | notification | Snapshot creation complete |
| `Snapshot Creation Failed` | notification | Snapshot creation failed |
| `Snapshot Export Failed` | notification | Snapshot export to S3 failed |
| `Snapshot Copy Failed` | notification | Cross-region snapshot copy failed |

> **Note:** These native EventBridge service events apply to serverless caches only. Some events like `Cache Limit Approaching` are serverless-specific.

### EventBridge Rules for Service Events

Create EventBridge rules that match native ElastiCache service events:

```bash
aws events put-rule \
  --name elasticache-serverless-events \
  --event-pattern '{
    "source": ["aws.elasticache"],
    "detail-type": [
      "Cache Created",
      "Cache Creation Failed",
      "Cache Deleted",
      "Cache Updated",
      "Cache Update Failed",
      "Cache Limit Approaching",
      "Snapshot Created",
      "Snapshot Creation Failed",
      "Snapshot Export Failed",
      "Snapshot Copy Failed"
    ]
  }' \
  --region us-east-1
```

Add targets via `aws events put-targets` pointing to SNS, Lambda, SQS, or Step Functions.

For change management auditing, also create a CloudTrail-based rule:

```bash
aws events put-rule \
  --name elasticache-serverless-api-audit \
  --event-pattern '{
    "source": ["aws.elasticache"],
    "detail-type": ["AWS API Call via CloudTrail"],
    "detail": {
      "eventSource": ["elasticache.amazonaws.com"],
      "eventName": [
        "CreateServerlessCache",
        "ModifyServerlessCache",
        "DeleteServerlessCache"
      ]
    }
  }' \
  --region us-east-1
```

### CloudTrail API Events

All ElastiCache API calls (including serverless operations) are recorded in CloudTrail:

- `CreateServerlessCache`
- `ModifyServerlessCache`
- `DeleteServerlessCache`
- `CreateUser`, `ModifyUser`, `DeleteUser`
- `CreateUserGroup`, `ModifyUserGroup`, `DeleteUserGroup`

## CloudTrail for Both Deployment Types

Ensure CloudTrail is enabled for ElastiCache API event recording.

Generate EventBridge rules and SNS topics via CloudFormation or CDK. The pattern matches `source: aws.elasticache` with `detail-type: AWS API Call via CloudTrail`.

## Recommended Event Pipeline by Deployment Type

### Node-Based Production

1. **SNS notifications** on the replication group for real-time operational alerts (failover, maintenance, scaling).
2. **EventBridge rule** matching CloudTrail API events for change management auditing.
3. **CloudTrail** enabled for compliance and post-incident investigation.

### Serverless Production

1. **EventBridge rule** matching native service events (`Cache Limit Approaching`, `Cache Update Failed`, etc.) for operational alerting.
2. **EventBridge rule** matching CloudTrail-derived API events for change management auditing.
3. **CloudWatch alarms** (see `alarm-packs.md`) for performance and throttling alerts (ECPU consumption, latency, throttled commands).
4. **CloudTrail** enabled for compliance and post-incident investigation.

### Development / Staging

1. **EventBridge rule** for destructive operations only (delete, modify) to catch accidental changes.
2. **CloudTrail** with short retention for debugging.

## Event-to-Action Mapping

| Event | Severity | Recommended Action |
|-------|----------|-------------------|
| Failover started | P1 (page) | Alert on-call; verify application reconnection |
| Failover complete | P2 (next hour) | Confirm replicas healthy; check for data loss |
| Maintenance scheduled | P3 (next day) | Inform team; verify maintenance window is acceptable |
| Service update available | P3 (next day) | Review release notes; schedule during maintenance window |
| DeleteServerlessCache / DeleteReplicationGroup | P1 (page) | Alert immediately; verify intentional (audit trail) |
| ModifyReplicationGroup (parameter change) | P2 (next hour) | Review change; verify no unexpected impact |
| Throttled commands (serverless) | P2 (next hour) | Handled by CloudWatch alarms; increase ECPU limits |
