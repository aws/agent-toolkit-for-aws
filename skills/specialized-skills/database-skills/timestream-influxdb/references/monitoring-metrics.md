# Timestream for InfluxDB Metric Discovery

## Rule

Treat metric names, dimensions, units, statistics, and engine/deployment availability as runtime facts. Never invent or normalize a name from memory, and never use this skill as an availability inventory.

## CloudWatch

1. Identify the resource, Region, engine variant, and deployment type.
2. Retrieve the Timestream for InfluxDB monitoring documentation and verify the documented namespace, dimensions, and supported metrics for that deployment.
3. Inspect the metrics published in the resource's account and Region:

   ```bash
   aws cloudwatch list-metrics \
     --namespace AWS/TimestreamInfluxDB \
     --region <region>

   aws cloudwatch list-metrics \
     --namespace AWS/TimestreamInfluxDB \
     --dimensions Name=<verified-resource-dimension>,Value=<resource-id> \
     --region <region>
   ```

4. Use the exact metric name and dimensions confirmed by the documentation or returned telemetry. Verify the unit and supported statistic before configuring an alarm.
5. Do not treat an empty `list-metrics` response as proof that a metric is unsupported. Recheck the account, Region, resource dimension, publication activity, and service documentation.

If documentation retrieval or the CloudWatch query fails, disclose the failure and do not substitute a remembered metric name.

## Other Monitoring Surfaces

Before asserting that an engine exposes another monitoring endpoint, retrieve its monitoring documentation. When the documentation confirms one, inspect its authenticated metric exposition and use only exact names observed there. Keep credentials out of command arguments and logs, and use scoped tokens loaded from AWS Secrets Manager.

## Alarm Selection

Map the requested operational signal to a verified metric or documented alternative. Derive thresholds and evaluation periods from the metric semantics, resource capacity, workload baseline, and operational objectives. Do not transfer names, dimensions, or thresholds between engine variants or deployment types without verification.
