# Monitoring and Operations

## When to Activate

User asks about CloudWatch metrics, alarms, instance health, maintenance windows, backups, snapshots, or operational best practices.

## Discover CloudWatch Metrics

Before naming or configuring a metric, retrieve the service monitoring documentation for the selected engine variant and deployment type, then inspect the metrics published for the resource in its account and Region:

```bash
aws cloudwatch list-metrics \
  --namespace AWS/TimestreamInfluxDB \
  --region <region>

aws cloudwatch list-metrics \
  --namespace AWS/TimestreamInfluxDB \
  --dimensions Name=<verified-resource-dimension>,Value=<resource-id> \
  --region <region>
```

Follow [metric discovery](monitoring-metrics.md) to verify the exact metric name, namespace, dimensions, unit, and supported statistics. Use only values confirmed by the documentation or observed telemetry. An empty `list-metrics` result is not proof that a metric is unsupported; verify the account, Region, dimensions, publication activity, and documentation before drawing that conclusion.

## Recommended Alarm Configuration

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name <alarm-name> \
  --metric-name <verified-metric-name> \
  --namespace AWS/TimestreamInfluxDB \
  --statistic <verified-statistic> \
  --period <period-seconds> \
  --threshold <workload-derived-threshold> \
  --comparison-operator <comparison-operator> \
  --evaluation-periods <evaluation-periods> \
  --dimensions Name=<verified-resource-dimension>,Value=<resource-id> \
  --alarm-actions <sns-topic-arn>
```

Derive thresholds from the metric's documented semantics, resource capacity, workload baseline, and operational objectives. For a signal not exposed through CloudWatch, use only an alternative monitoring surface documented for the selected engine variant and deployment.

> **MUST:** Enable SSE-KMS on your SNS topic to encrypt alarm notifications at rest — never use at-rest unencrypted notifications for operational data. Alarm notifications can contain operationally sensitive information (instance IDs, metric thresholds, account details). Ensure your SNS topic access policy restricts `sns:Subscribe` to authorized principals only, and verify that all subscription endpoints (email, HTTPS, Lambda) belong to your organization. If alarm notifications are also delivered to CloudWatch Logs, enable SSE-KMS encryption on those log groups as well.

```bash
SNS_TOPIC_ARN="$(aws sns create-topic \
  --name timestream-influxdb-alarms \
  --attributes KmsMasterKeyId="<kms-key-arn>" \
  --query TopicArn --output text)"
```

Before connecting a CloudWatch alarm to a topic encrypted with a customer-managed KMS key, retrieve the [Amazon SNS key-management guidance](https://docs.aws.amazon.com/sns/latest/dg/sns-key-management.html#compatibility-with-aws-services) and [CloudWatch alarm-notification guidance](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Notify_Users_Alarm_Changes.html). Verify the service principal, required KMS actions, and supported source conditions. Merge the documented permissions into the existing policy of `<kms-key-arn>`; if the retrieved guidance differs from this template, use the retrieved values:

```json
{
  "Sid": "AllowCloudWatchAlarmsToUseKey",
  "Effect": "Allow",
  "Principal": {
    "Service": "cloudwatch.amazonaws.com"
  },
  "Action": [
    "kms:GenerateDataKey*",
    "kms:Decrypt"
  ],
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "aws:SourceAccount": "<account-id>"
    },
    "ArnLike": {
      "aws:SourceArn": "arn:<partition>:cloudwatch:<region>:<account-id>:alarm:<alarm-name>"
    }
  }
}
```

In a KMS key policy, `"Resource": "*"` refers only to the KMS key to which the policy is attached. Keep the source-account condition and use the full ARN of each authorized alarm; when a topic serves multiple alarms, list their ARNs rather than broadening access beyond the intended alarms.

Merge this statement into the topic's existing resource policy, preserving its administrative statements:

```json
{
  "Sid": "AllowAuthorizedSubscriptions",
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::<account-id>:role/<authorized-operations-role>"
  },
  "Action": "sns:Subscribe",
  "Resource": "<sns-topic-arn>"
}
```

Apply the merged policy with `aws sns set-topic-attributes --topic-arn "$SNS_TOPIC_ARN" --attribute-name Policy --attribute-value file://<merged-topic-policy.json>`. Then run `aws sns list-subscriptions-by-topic --topic-arn "$SNS_TOPIC_ARN"` and confirm every endpoint and protocol is authorized before connecting the topic to an alarm.

## Maintenance Windows

Customer Managed Maintenance Windows:

- Set preferred day, time, and timezone via console, CLI, or SDK
- Engine patches and minor updates applied during the window
- Major version changes require explicit approval

```bash
# V2 instance
aws timestream-influxdb update-db-instance \
  --identifier <instance-id> \
  --maintenance-schedule '{"timezone":"UTC","preferredMaintenanceWindow":"Sun:03:00-Sun:05:00"}'

# V3 cluster
aws timestream-influxdb update-db-cluster \
  --db-cluster-id <cluster-id> \
  --maintenance-schedule '{"timezone":"UTC","preferredMaintenanceWindow":"Sun:03:00-Sun:05:00"}'
```

## Backup & Snapshots

- Before providing backup guidance, verify the [customer-managed backup and restore documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/influxdb3-customer-managed-backup-restore.html) and Timestream for InfluxDB CLI or SDK API model. Confirm support by engine variant and Region for on-demand, scheduled, continuous, point-in-time, and self-service restore capabilities rather than treating any of them as universally available.
- When the API exposes `CreateDbBackup`, `DbBackupConfiguration`, or `RestoreFromDbBackup`, describe the resulting `DbBackup` resources as backups, not snapshots.
- Before selecting a restore mode, verify the restrictions in the [`RestoreFromDbBackup` Boto3 reference](https://docs.aws.amazon.com/boto3/latest/reference/services/timestream-influxdb/client/restore_from_db_backup.html) and the [customer-managed backup and restore documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/influxdb3-customer-managed-backup-restore.html). When those sources prohibit `REPLACE_EXISTING` for a cluster encrypted with a customer-managed KMS key, use `NEW_RESOURCE`.
- Verify the documentation for service-managed snapshot accessibility and recovery before describing an AWS Support path. Check the API model before asserting that a customer-managed snapshot operation is absent; regardless of API evolution, do not relabel a `DbBackup` resource as a snapshot.
- For an independent, portable copy, use the InfluxDB data-plane API and store the export in an S3 bucket protected with SSE-KMS. Never put a token literal in the command or write an unencrypted export to local disk.

Load `INFLUX_TOKEN` or `V3_TOKEN` from Secrets Manager using the patterns in [getting started](getting-started.md), keep shell tracing disabled, and then export:

```bash
# V2: Stage only on an encrypted volume, then upload an encrypted archive.
set -o pipefail
umask 077
BACKUP_DIR="<directory-on-encrypted-volume>"
install -d -m 700 "$BACKUP_DIR"

influx backup "$BACKUP_DIR" --host https://<endpoint>:8086 &&
  tar -C "$BACKUP_DIR" -czf - . |
    aws s3 cp - s3://<backup-bucket>/<backup-key>.tar.gz \
      --sse aws:kms --sse-kms-key-id <kms-key-arn>
BACKUP_STATUS=$?

unset INFLUX_TOKEN
if test "$BACKUP_STATUS" -eq 0; then
  rm -rf -- "$BACKUP_DIR"
else
  printf 'Backup or upload failed; staging preserved at %s\n' "$BACKUP_DIR" >&2
  exit "$BACKUP_STATUS"
fi

# V3: Stage only on an encrypted volume, then upload the verified export.
set -o pipefail
umask 077
EXPORT_FILE="<file-on-encrypted-volume>"

printf 'Authorization: Bearer %s\n' "$V3_TOKEN" |
  curl --fail-with-body -X POST "https://<endpoint>:8181/api/v3/query_sql" \
    -H @- \
    -H "Content-Type: application/json" \
    -d '{"db":"<database>","q":"SELECT * FROM <table>","format":"csv"}' \
    -o "$EXPORT_FILE" &&
  test -s "$EXPORT_FILE" &&
  aws s3 cp "$EXPORT_FILE" s3://<backup-bucket>/<backup-key>.csv \
    --sse aws:kms --sse-kms-key-id <kms-key-arn>
EXPORT_STATUS=$?

unset V3_TOKEN
if test "$EXPORT_STATUS" -eq 0; then
  rm -f -- "$EXPORT_FILE"
else
  printf 'Export or upload failed; staging preserved at %s\n' "$EXPORT_FILE" >&2
  exit "$EXPORT_STATUS"
fi
```

Delete staging data only after a successful S3 upload, following the organization's secure-deletion policy; preserve it on failure so the upload can be retried. Keep shell tracing disabled, unset token variables immediately after use, and restrict the backup bucket and KMS key policies to authorized backup and restore roles.

## AWS CloudTrail Integration

Before asserting event coverage, retrieve the [Timestream for InfluxDB CloudTrail documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/logging-using-cloudtrail-influxdb.html). Configure a trail to record the management-event classes and operations that documentation lists, retain them according to organizational policy, and apply the CloudTrail S3 encryption and log-file validation controls in [security best practices](security-best-practices.md#auditing).

Do not infer data-plane coverage from management-event coverage. Verify native audit-log and metrics availability for the selected engine variant before recommending data-access monitoring, and state only the coverage the service documentation confirms.

## Operational Checklist

- [ ] CloudWatch alarms configured for each verified resource-health and capacity signal
- [ ] Maintenance window set to low-traffic period
- [ ] Backup and restore strategy defined after verifying `DbBackup`, restore, and data-plane export capabilities
- [ ] SNS topic and its customer-managed KMS key permit only the intended CloudWatch alarms and authorized subscribers
- [ ] CloudTrail event coverage verified and a trail configured for the documented management events
- [ ] Instance right-sized for workload (check CPU/memory utilization trends)
- [ ] Storage monitoring uses the documented surface for the selected engine variant and deployment
