# Observing CloudFront Traffic with Logs

## Overview

Domain expertise for getting visibility into CloudFront requests: choosing between standard logging
and real-time logs, understanding their latency, completeness, and cost differences, reading the
rich fields already present in the logs, and querying logs at rest with Amazon Athena.

Standard logging (v2) delivers comprehensive access logs to Amazon CloudWatch Logs, Amazon Data
Firehose, or Amazon S3 on a delay of minutes, with selectable fields and output formats. Real-time
logs deliver sampled records to an Amazon Kinesis data stream within seconds, on a best-effort
basis. The two coexist and serve different needs: completeness versus freshness.

Does not cover creating the distribution (see when-to-use-cloudfront), origin or content security,
or CloudWatch alarm authoring beyond pointing logs at a destination.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Decision: standard logging vs real-time logs
- Latency, completeness, and cost
- Rich fields already in the logs
- Querying at rest with Athena and Parquet
- Procedure
- Troubleshooting
- Security Considerations
- Additional Resources

## Decision: standard logging vs real-time logs

| Need | Choose |
| --- | --- |
| Complete record for billing reconciliation, audit, detailed after-the-fact analysis | Standard logging to S3, CloudWatch Logs, or Firehose |
| Live dashboards, fast anomaly detection within seconds | Real-time logs to a Kinesis data stream |

**Constraints:**

- You MUST pick by whether the customer needs completeness (standard) or freshness (real-time)
- You SHOULD note the two coexist, and standard logging also coexists with legacy standard
  logging

## Latency, completeness, and cost

**Constraints:**

- You MUST explain standard logs are comprehensive and arrive minutes later with no CloudFront
  charge for log delivery (customer pays only for the destination — S3 storage, CloudWatch Logs
  ingestion/storage, or Firehose delivery; CloudWatch Logs bills a per-event included byte allowance
  with overage charged per byte — direct the customer to the current Amazon CloudWatch Logs pricing
  page for the exact allowance and rates rather than quoting a fixed number, which can change);
  real-time logs arrive within seconds, are sampled
  at a rate you set, and are best-effort with a CloudFront per-line charge plus the Kinesis data
  stream throughput cost (real-time logs go only to a Kinesis data stream)
- You MUST set the expectation that real-time log counts will not match the AWS billing and usage
  reports, because delivery is best-effort and sampled. Route exact accounting to standard logs
- You MUST warn that 100% sampling on real-time logs generates significant charges; recommend
  starting at a lower percentage for cost-sensitive workloads
- You MUST surface the cost levers: real-time logs bill for CloudFront plus the destination, and
  choosing Parquet output on standard logs incurs a CloudWatch vended-logs conversion charge
- You SHOULD mention Amazon CloudWatch Internet Monitor provides internet weather data and connectivity
  insights, helping customers correlate CloudFront performance with broader internet conditions

## Rich fields already in the logs

Customers often ask for data CloudFront already logs, then build extra tooling to derive it.

**Constraints:**

- You MUST surface the rich fields already present rather than send the customer to build tooling:
  the edge result type and cache hit or miss, the origin response and origin errors, the time
  taken, the viewer TLS protocol and cipher, and, for multi-tenant distributions, the distribution
  tenant identifier the request belonged to (enabling per-tenant dashboards and alerting)
- You MUST highlight field selection as configurable in both standard and real-time logs — customers
  choose exactly which fields to include, reducing storage costs and simplifying analysis

## Querying at rest with Athena and Parquet

**Constraints:**

- You SHOULD point the customer at Amazon Athena to query logs in S3 with SQL
- You SHOULD enable Hive-compatible partitioning and the Parquet output format to cut the data
  scanned per query, lowering cost and latency
- You SHOULD reference the published integration patterns rather than have the customer build from
  scratch

## Procedure

### Overview

This procedure selects the logging mechanism, enables it with the chosen fields and destination,
and points the customer at analysis.

### Parameters

- **distribution_id** (required): The distribution to log.
- **mechanism** (required): `standard` or `real-time`.
- **destination** (required): For standard, `s3` / `cloudwatch` / `firehose`; for real-time, the
  Kinesis data stream.
- **fields** (optional): The log fields to include.

**Constraints for parameter acquisition:**

- You MUST ask whether the customer needs completeness or freshness before choosing the mechanism
- You MUST confirm the destination and any required permissions

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm the destination exists and has the required delivery permissions
- You MUST enable encryption at rest on the log destination: SSE-S3 or SSE-KMS on an S3 bucket,
  SSE-KMS on an Amazon Data Firehose delivery stream, KMS encryption on a Kinesis data stream used
  for real-time logs, and a KMS key on every CloudWatch Logs log group receiving CloudFront logs
  (CloudFront request logs routinely carry sensitive data such as signed URL query strings and
  cookie values)
- You SHOULD warn that signed URL query strings and cookie values can appear in the logs, and use
  field selection to exclude sensitive fields when they are not needed for analysis
- You MUST enable AWS CloudTrail to record CloudFront management API calls (such as
  `cloudfront:CreateDistribution` and `cloudfront:UpdateDistribution`) for a compliance and forensic
  audit trail, separate from the request access logs above

#### 2a. Enable standard logging

**Constraints:**

- You MUST enable standard logging to the chosen destination, selecting fields and, for S3,
  partitioning and (if wanted) the Parquet output format, noting the conversion charge

#### 2b. Create a real-time log configuration

**Constraints:**

- You MUST create the real-time configuration with a sampling rate, the chosen fields, and the
  Kinesis data stream, then attach it to the cache behaviors to cover:

  ```
  aws cloudfront create-realtime-log-config --name {name} \
    --sampling-rate {rate} --fields {fields} \
    --end-points '[{"StreamType":"Kinesis","KinesisStreamConfig":{...}}]'
  ```

#### 3. Point at analysis and surface the console link

**Constraints:**

- You SHOULD set up an Athena table over the S3 logs (Hive partitioning, Parquet) for ad hoc
  queries, or a Kinesis consumer for real-time
- You MUST present the distribution detail console link, filling `{distributionId}` from the input
  `distribution_id` parameter:

  ```
  https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/{distributionId}
  ```

### Example

#### Example input

```json
{
  "distribution_id": "E1ABCDEF2GHIJK",
  "mechanism": "standard",
  "destination": "s3",
  "fields": ["timestamp", "x-edge-result-type", "sc-status", "time-taken"]
}
```

#### Example output

```
Enabled standard logging on E1ABCDEF2GHIJK to S3.
Logs include edge result type, status, and time taken; query them with Athena.
Consider enabling Hive partitioning and Parquet output to reduce query cost (note: Parquet incurs a vended-logs conversion charge).
Verify in the console:
https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/E1ABCDEF2GHIJK
```

## Troubleshooting

### Real-time log counts do not match the billing reports
Real-time delivery is best-effort and sampled, so counts will differ. Use standard logs for exact
accounting.

### Standard logs are not arriving in the destination
The destination is missing the required delivery permissions, or the S3 path conflicts with legacy
logging. Set the vended-logs permissions and use a separate bucket or prefix from legacy logs.

### Athena queries are slow or expensive
The logs are not partitioned or not in Parquet, so queries scan everything. Enable Hive-compatible
partitioning and the Parquet output format.

### A field the customer wants seems missing
It may already be a selectable field. Check the standard log fields reference for edge result type,
origin errors, time taken, TLS protocol and cipher, and the tenant field.

## Security Considerations

- **Logs can carry sensitive data.** Signed URL query strings and cookie values appear in the logs.
  Use field selection to exclude these fields when they are not needed for analysis.
- **Encrypt the log destination.** Enable SSE-S3 or SSE-KMS on the S3 bucket, SSE-KMS on an Amazon
  Data Firehose delivery stream, KMS encryption on a Kinesis data stream for real-time logs, and a
  KMS key on the CloudWatch Logs log group.
- **Lock down access to log destinations.** Scope read access to the log bucket, stream, or log
  group to the operators and tools that need it, not a broad grant, since logs expose request
  detail.
- **High sampling exposes volume.** 100% real-time sampling captures every request (and any
  sensitive fields) in addition to the cost; start at a lower rate unless full capture is required.
- **Audit the management plane with CloudTrail.** Request access logs do not record who changed the
  distribution. Enable AWS CloudTrail to track CloudFront API calls
  (`cloudfront:CreateDistribution`, `cloudfront:UpdateDistribution`) for a compliance and forensic
  audit trail.

## Additional Resources

- [Configure standard logging (v2) (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logging.html)
- [Use real-time access logs (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/real-time-logs.html)
- [Standard log file fields reference (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logs-reference.html)
- [Querying Amazon CloudFront logs (Amazon Athena User Guide)](https://docs.aws.amazon.com/athena/latest/ug/cloudfront-logs.html)
- [Sending CloudFront standard logs to CloudWatch Logs for analysis (AWS Cloud Operations Blog)](https://aws.amazon.com/blogs/mt/sending-cloudfront-standard-logs-to-cloudwatch-logs-for-analysis/)
