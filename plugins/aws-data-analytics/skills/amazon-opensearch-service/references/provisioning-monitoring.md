# CloudWatch Monitoring for AOS

> **Note:** Enable OpenSearch application logs (index slow logs, search slow logs, error logs, audit logs) and configure CloudTrail for API-level auditing. Store logs in encrypted CloudWatch Logs groups (specify `--kms-key-id` at log group creation: `aws logs create-log-group --log-group-name /aws/opensearch/my-domain --kms-key-id arn:aws:kms:<region>:<account>:key/<key-id>`).

## Key Metrics to Monitor

| Metric | Threshold | Action |
|--------|-----------|--------|
| `CPUUtilization` | > 80% sustained | Scale up instance type or add nodes |
| `JVMMemoryPressure` | > 80% | Increase instance size; check for large aggregations |
| `ClusterStatus.red` | = 1 | Immediate: check for unassigned shards |
| `ClusterStatus.yellow` | = 1 | Investigate: replica shards not allocated |
| `FreeStorageSpace` | < 20 GB (adjust based on provisioned storage) | Add EBS capacity or migrate old indices to UltraWarm |
| `SearchLatency` | > 500ms p99 | Optimize queries; consider adding data nodes |
| `IndexingLatency` | > 100ms p99 | Check bulk queue; scale indexing capacity |
| `ThreadpoolSearchRejected` | > 0 | Search queue full; scale or throttle clients |

## Creating CloudWatch Alarms

### Cluster Health (Red)

```bash
aws cloudwatch put-metric-alarm --alarm-name aos-cluster-red \
  --namespace AWS/ES --metric-name ClusterStatus.red \
  --dimensions Name=DomainName,Value=my-domain Name=ClientId,Value=<account-id> \
  --statistic Maximum --period 60 --evaluation-periods 1 \
  --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions arn:aws:sns:<region>:<account>:my-alerts
```

> **REQUIRED:** SNS topics receiving CloudWatch alarms MUST have KMS encryption enabled. CloudWatch alarm notifications may contain cluster status, metric values, and other sensitive operational data. Enable encryption when creating the topic:
>
> ```bash
> aws sns create-topic --name my-alerts \
>   --attributes KmsMasterKeyId=alias/aws/sns
> ```
>
> For existing topics: `aws sns set-topic-attributes --topic-arn <arn> --attribute-name KmsMasterKeyId --attribute-value alias/aws/sns`
> Verify all SNS subscription recipients belong to authorized personnel before deploying alarms.

### JVM Memory Pressure

```bash
aws cloudwatch put-metric-alarm --alarm-name aos-jvm-pressure \
  --namespace AWS/ES --metric-name JVMMemoryPressure \
  --dimensions Name=DomainName,Value=my-domain Name=ClientId,Value=<account-id> \
  --statistic Maximum --period 300 --evaluation-periods 3 \
  --threshold 80 --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions arn:aws:sns:<region>:<account>:my-alerts
```

### Free Storage Space

```bash
aws cloudwatch put-metric-alarm --alarm-name aos-low-storage \
  --namespace AWS/ES --metric-name FreeStorageSpace \
  --dimensions Name=DomainName,Value=my-domain Name=ClientId,Value=<account-id> \
  --statistic Minimum --period 300 --evaluation-periods 1 \
  --threshold 20480 --comparison-operator LessThanOrEqualToThreshold \
  --alarm-actions arn:aws:sns:<region>:<account>:my-alerts
```

## Recommended Alarm Set

For production domains, create alarms for:

1. ClusterStatus.red (immediate)
2. ClusterStatus.yellow (sustained 15 min)
3. JVMMemoryPressure > 80% (sustained 15 min)
4. CPUUtilization > 80% (sustained 15 min)
5. FreeStorageSpace < 20 GB (immediate; adjust based on provisioned storage)
6. ThreadpoolSearchRejected > 0 (sum over 5 min)
7. AutomatedSnapshotFailure > 0 (immediate)
