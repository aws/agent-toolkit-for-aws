# ElastiCache Insights and OpenTelemetry Metrics (node-based Valkey only)

Node-based Valkey clusters publish OpenTelemetry (OTel) metrics to CloudWatch, queryable with PromQL. Standard monitoring publishes a core set every 60 seconds at no extra charge. Detailed monitoring publishes the metrics you select every 15 seconds, billed at CloudWatch OTel prices. Turn it on from the cluster's Metrics tab, or with a CloudWatch call (not `elasticache`):

```bash
aws cloudwatch create-resource-metrics-configuration \
  --resource-arn arn:aws:elasticache:<region>:<account-id>:replicationgroup:<cluster-id> \
  --metric-selections '[{"IncludeMetrics": ["valkey.command.duration", "valkey.command.calls"]}]'
```

The caller needs `cloudwatch:CreateResourceMetricsConfiguration`, `cloudwatch:UpdateResourceMetricsConfiguration`, `cloudwatch:GetResourceMetricsConfiguration`, and `cloudwatch:DeleteResourceMetricsConfiguration` on `"Resource": "*"`, scoped with a `cloudwatch:ResourceArn` condition set to the cluster ARN. These actions are authorized at the action level, so an ARN in `Resource` does not restrict them. Omitting `--metric-selections` selects and bills every metric. `update-resource-metrics-configuration` replaces the whole selection. View the metrics in ElastiCache Insights, a CloudWatch dashboard filterable by cluster, shard, node, or AZ (open it from the Metrics tab or CloudWatch Infrastructure Monitoring). Not available for Serverless or Memcached.
