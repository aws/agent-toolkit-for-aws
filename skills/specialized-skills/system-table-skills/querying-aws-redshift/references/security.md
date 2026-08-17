# Security: Least Privilege, KMS, Data Sensitivity, and Audit Trail

Loaded on demand from `querying-aws-redshift` SKILL.md. Read this before granting anyone access to published system tables — `query_text` can carry credentials, and the KMS key policy needs two service principals, not one.

## Least-Privilege IAM Policy

Scope permissions to the S3 Tables catalog rather than using wildcards:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3tables:GetTable",
        "s3tables:GetTableMetadataLocation",
        "s3tables:GetTableData",
        "s3tables:GetNamespace",
        "s3tables:ListTables",
        "s3tables:ListNamespaces",
        "s3tables:GetTableBucket"
      ],
      "Resource": [
        "arn:aws:s3tables:<REGION>:<ACCOUNT>:bucket/aws-redshift",
        "arn:aws:s3tables:<REGION>:<ACCOUNT>:bucket/aws-redshift/*"
      ]
    }
  ]
}
```

## KMS Key Policy (for encrypted logs)

When using `--s3-table-kms-key-id` (both Provisioned and Serverless), the KMS key must grant both the Redshift and S3 Tables service principals access:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EnableRedshiftSystemTableKeyUsage",
      "Effect": "Allow",
      "Principal": {
        "Service": "systemtables.redshift.amazonaws.com"
      },
      "Action": [
        "kms:DescribeKey",
        "kms:GenerateDataKey",
        "kms:Decrypt"
      ],
      "Resource": "arn:aws:kms:<REGION>:<ACCOUNT>:key/<KEY_ID>",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "<ACCOUNT>"
        }
      }
    },
    {
      "Sid": "EnableS3TableMaintenanceKeyUsage",
      "Effect": "Allow",
      "Principal": {
        "Service": "maintenance.s3tables.amazonaws.com"
      },
      "Action": [
        "kms:GenerateDataKey",
        "kms:Decrypt"
      ],
      "Resource": "arn:aws:kms:<REGION>:<ACCOUNT>:key/<KEY_ID>",
      "Condition": {
        "StringLike": {
          "kms:EncryptionContext:aws:s3:arn": "arn:aws:s3tables:<REGION>:<ACCOUNT>:bucket/aws-redshift/*"
        }
      }
    }
  ]
}
```

## Data Sensitivity

`SYS_*` system-table data may contain sensitive fields:
- `query_text` — may reveal schema, data values, or business logic
- `username` / `user_id` — the principal that ran the query
- `remote_host` (in `sys_connection_log`) — client IP address

Store query results in encrypted, access-controlled locations. Avoid logging or sharing raw output that contains query text, principal identifiers, or IP addresses.

**`query_text` can contain credentials, not just schema.** Applications that build SQL by string interpolation rather than parameterized queries embed literal values directly in the statement text — including passwords in `CREATE USER` / `ALTER USER`, connection strings, API keys passed to UDFs, and PII in `WHERE` clauses. All of that is captured verbatim in `sys_query_history` and published to the S3 table. Audit your applications for interpolated SQL **before** making `sys_query_history` broadly readable; a query-history grant is effectively a secrets grant if that anti-pattern is present. Restrict the column via Lake Formation column-level permissions where readers only need timing and identity data.

Athena is a second copy of the same text: `StartQueryExecution` records the full SQL in CloudTrail. If those events are delivered to CloudWatch Logs, encrypt the receiving log group with a customer-managed key (`aws logs associate-kms-key --log-group-name <NAME> --kms-key-id <KEY_ARN>`), since the default log-group encryption is not customer-managed.

## Audit Trail

Enable CloudTrail logging for Athena (`StartQueryExecution`, `GetQueryResults`) and S3 Tables (`s3tables:GetTableData`) API calls to maintain an audit trail of who queried what. Ensure CloudTrail logs are encrypted with SSE-KMS and stored in a bucket with access logging enabled.

Collecting logs is passive; add active detection so misuse surfaces without someone reading them. Two alarms worth having:

- **Access-denied spikes on the published tables** — a burst of `AccessDenied` on `s3tables:GetTableData` is the signature of enumeration or a broken least-privilege change. With CloudTrail delivering to CloudWatch Logs, create a metric filter and alarm on it:
  ```bash
  aws logs put-metric-filter \
    --log-group-name <CLOUDTRAIL_LOG_GROUP> \
    --filter-name S3TablesAccessDenied \
    --filter-pattern '{ ($.eventSource = "s3tables.amazonaws.com") && ($.errorCode = "AccessDenied*") }' \
    --metric-transformations metricName=S3TablesAccessDenied,metricNamespace=RedshiftSysTables,metricValue=1

  aws cloudwatch put-metric-alarm \
    --alarm-name S3TablesAccessDeniedSpike \
    --metric-name S3TablesAccessDenied --namespace RedshiftSysTables \
    --statistic Sum --period 300 --evaluation-periods 1 \
    --threshold 10 --comparison-operator GreaterThanThreshold \
    --alarm-actions <SNS_TOPIC_ARN>
  ```
- **Failed authentications against the cluster** — `sys_connection_log` records these, so once it is published you can detect credential-stuffing from the S3 table on a schedule rather than by ad-hoc query. Alert on a rising count of failed connections grouped by `remote_host`.

Tune both thresholds to your own baseline; the values above are starting points, not recommendations.

**Secure the notification path, not just the detection.** Alarm payloads describe who is touching which system tables, so the topic is itself sensitive. Encrypt it with a customer-managed key and audit who receives it:
```bash
aws sns set-topic-attributes \
  --topic-arn <SNS_TOPIC_ARN> \
  --attribute-name KmsMasterKeyId --attribute-value <KMS_KEY_ID>

aws sns list-subscriptions-by-topic --topic-arn <SNS_TOPIC_ARN>
```
The default `alias/aws/sns` key cannot be restricted by policy or revoked; a customer-managed key can. Review the subscription list on a schedule — an email or HTTP subscriber added later inherits every future alert, and confirm the key policy lets `cloudwatch.amazonaws.com` call `kms:GenerateDataKey*`/`kms:Decrypt`, or alarms will fail to publish silently.

