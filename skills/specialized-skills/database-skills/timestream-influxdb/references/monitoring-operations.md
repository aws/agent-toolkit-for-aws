# Monitoring and Operations

## When to Activate

User asks about CloudWatch metrics, alarms, instance health, maintenance windows, or operational best practices. For backups, snapshots, or restores, load [backup and restore](backup-restore.md).

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

Before giving maintenance guidance, retrieve the maintenance-window documentation for the engine variant: [InfluxDB 3 clusters](https://docs.aws.amazon.com/timestream/latest/developerguide/influxdb3-maintenance-windows.html) or [InfluxDB 2 instances](https://docs.aws.amazon.com/timestream/latest/developerguide/timestream-for-influx-managing-maintaining-db.html). Then inspect the `--maintenance-schedule` shape in the installed API model. Where the guides and the API model disagree, follow the API model; for example, one guide example omits `timezone`, and another passes `--identifier` to `update-db-cluster`.

**What it controls:**

- Every resource has a weekly window for mandatory hardware, operating-system, and engine updates. A window defines when maintenance *can* run, not that it will. Maintenance typically runs no more than once a week and at least once a month, starting within the first 30 minutes of the window.
- Maintenance is service-managed by default. Setting `preferredMaintenanceWindow` makes the window customer-managed; passing an empty string returns scheduling to the service.
- Maintenance missed in one window can run in a later one. Maintenance deferred for more than 25 days may run outside the preferred window.

**Request shape:** `--maintenance-schedule '{"timezone":"<iana-zone>","preferredMaintenanceWindow":"ddd:HH:MM-ddd:HH:MM"}'`

- The API requires both fields.
- `ddd` is `Mon`–`Sun` and times use the 24-hour clock. The window must be at least 2 and at most 24 hours long. Cross-midnight windows such as `Sat:21:00-Sun:01:00` are supported.
- `timezone` takes an IANA identifier such as `UTC`, `America/New_York`, or `Asia/Tokyo`. Abbreviations such as `EST`, `PST`, or `GMT+5` are rejected. In a zone that observes DST, avoid local times from 01:00 to 03:00, because a window inside the skipped spring-forward hour is skipped that week.
- Window times are local to `timezone`, not UTC. The API model's field description says "(UTC)", but the maintenance-window documentation states that window times are interpreted in the specified time zone; with `UTC` the two agree.
- When a requested window is shorter than 2 hours, do not submit it. Tell the user about the minimum and propose a compliant window, for example extending `Sun:03:00-Sun:04:00` to `Sun:03:00-Sun:05:00`.

```bash
# V2 instance
aws timestream-influxdb update-db-instance \
  --identifier <instance-id> \
  --maintenance-schedule '{"timezone":"UTC","preferredMaintenanceWindow":"Sun:03:00-Sun:05:00"}' \
  --region <region>

# V3 cluster or V2 Read Replica cluster
aws timestream-influxdb update-db-cluster \
  --db-cluster-id <cluster-id> \
  --maintenance-schedule '{"timezone":"America/New_York","preferredMaintenanceWindow":"Sat:21:00-Sun:01:00"}' \
  --region <region>

# Return scheduling to the service
aws timestream-influxdb update-db-cluster \
  --db-cluster-id <cluster-id> \
  --maintenance-schedule '{"timezone":"UTC","preferredMaintenanceWindow":""}' \
  --region <region>
```

- `create-db-instance`, `create-db-cluster`, and `restore-from-db-backup` accept the same `--maintenance-schedule` value, so set the window at creation instead of with a follow-up update.
- To verify, wait until the resource is `AVAILABLE`. Then read `maintenanceSchedule` from `get-db-instance` or `get-db-cluster` and confirm both fields match the request. Report `nextMaintenanceTime` and `lastMaintenanceTime`, which are always in UTC regardless of the configured time zone.

**During maintenance:**

- Status changes to `MAINTENANCE` and the resource may be temporarily unavailable; afterward it returns to `AVAILABLE`.
- Multi-AZ V2 instances patch the standby first and then fail over.
- Multi-node clusters reached through the cluster endpoint shift traffic to available nodes.
- Single-AZ instances and single-node clusters have no standby or peer node, so they may be briefly unavailable.

Applying a DB parameter group with `update-db-cluster` also runs a maintenance action; follow the confirmation rules in the [processing-engine guide](processing-engine-guide.md).

## Backup and Restore

Load [backup and restore](backup-restore.md) for on-demand, scheduled, and continuous `DbBackup` operations, point-in-time and in-place restore, backup retention, and portable data-plane exports.

## AWS CloudTrail Integration

Before asserting event coverage, retrieve the [Timestream for InfluxDB CloudTrail documentation](https://docs.aws.amazon.com/timestream/latest/developerguide/logging-using-cloudtrail-influxdb.html). Configure a trail to record the management-event classes and operations that documentation lists, retain them according to organizational policy, and apply the CloudTrail S3 encryption and log-file validation controls in [security best practices](security-best-practices.md#auditing).

Do not infer data-plane coverage from management-event coverage. Verify native audit-log and metrics availability for the selected engine variant before recommending data-access monitoring, and state only the coverage the service documentation confirms.

## Operational Checklist

- [ ] CloudWatch alarms configured for each verified resource-health and capacity signal
- [ ] Maintenance window (2–24 hours, IANA time zone) set to a low-traffic period and verified with `get-db-instance` or `get-db-cluster`
- [ ] Automated `DbBackup` configurations enabled, with `CONTINUOUS` when point-in-time restore is required and the variant's backup and restore guide and API model confirm support, and a restore tested to a `NEW_RESOURCE`
- [ ] SNS topic and its customer-managed KMS key permit only the intended CloudWatch alarms and authorized subscribers
- [ ] CloudTrail event coverage verified and a trail configured for the documented management events
- [ ] Instance right-sized for workload (check CPU/memory utilization trends)
- [ ] Storage monitoring uses the documented surface for the selected engine variant and deployment
