# Setting Up Logging and Request Sampling

## Overview

Domain expertise for getting AWS WAF logging and request sampling working before any rule is
enabled, so Count-mode tuning has data to read. Covers the destination choice (Amazon CloudWatch
Logs, Amazon S3, or Amazon Data Firehose) and its traps (the `aws-waf-logs-` naming prefix, the
CloudFront-logs-in-us-east-1 rule), redacting sensitive fields, and confirming logs flow before
rules go on.

Does not cover the rules themselves; those are separate references. This reference is the
prerequisite the tuning workflows assume.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Decision: logging destination
- Naming and Region constraints
- Redact sensitive fields
- Confirm logs are flowing before enabling rules
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To set up logging and sampling end to end, follow the procedure exactly. See the Procedure section
below.

The procedure covers:

- Choosing a logging destination and meeting its naming and Region constraints
- Redacting sensitive fields before logging is enabled
- Enabling logging on the web ACL and confirming logs flow
- Confirming request sampling is on

## Decision: logging destination

| Destination | Best for | Latency |
| --- | --- | --- |
| CloudWatch Logs | Real-time analysis with Logs Insights and dashboards | Seconds |
| Amazon S3 | Long-term retention and Athena queries | Minutes |
| Amazon Data Firehose | Streaming to a SIEM or OpenSearch | Seconds |

**Constraints:**

- You SHOULD match the destination to the customer's need: CloudWatch Logs for real-time review, S3
  for retention and query, Firehose for streaming to a SIEM

## Naming and Region constraints

The destination has naming and Region traps that cause logs to silently never arrive.

**Constraints:**

- You MUST give the log destination a name carrying the `aws-waf-logs-` prefix; without it, logs
  fail silently
- You MUST send a CloudFront web ACL's logs to a destination in `us-east-1`
- You SHOULD confirm the destination's resource policy allows AWS WAF log delivery before enabling
- You MUST include `aws:SourceArn` and `aws:SourceAccount` condition keys in the log destination's
  resource policy to restrict delivery to the specific web ACL and account and prevent
  confused-deputy attacks
- You MUST enable encryption at rest on the log destination (CloudWatch Logs, Amazon S3, or Amazon
  Data Firehose, ideally with a customer-managed KMS key), since the logs can capture sensitive
  fields
- You MUST ensure the log destination accepts delivery only over encrypted channels: CloudWatch Logs
  delivery uses HTTPS, the S3 bucket policy MUST enforce `aws:SecureTransport`, and Firehose MUST use
  HTTPS

## Redact sensitive fields

Logging full requests can capture credentials and session cookies in plain text.

**Constraints:**

- You MUST redact sensitive fields such as the `authorization` header and `cookie` before enabling
  logging, so secrets are not written to the destination
- You SHOULD confirm with the customer which fields carry sensitive data for their application

## Confirm logs are flowing before enabling rules

Customers assume logging works, enable rules, and find the destination was misconfigured and
captured nothing during the tuning window.

**Constraints:**

- You MUST confirm logs are arriving at the destination before any rule is enabled
- You SHOULD confirm request sampling is on (it is part of the web ACL visibility config) so
  sampled requests are available for tuning

## Troubleshooting

### No logs arrive at the destination
The destination name is missing the `aws-waf-logs-` prefix, or its resource policy does not allow
AWS WAF delivery. Fix the name or policy (Naming and Region constraints).

### A CloudFront web ACL produces no logs
The destination is not in `us-east-1`. Create a destination there (Naming and Region constraints).

### Sensitive fields appear in logs
No redaction is configured. Add redacted fields for `authorization` and `cookie` (Redact sensitive
fields).

## Procedure

### Overview

This procedure chooses a logging destination, applies redaction, enables logging on the web ACL,
and confirms logs flow, then surfaces the console link.

### Parameters

- **web_acl_arn** (required): The ARN of the web ACL to log.
- **scope** (required): `CLOUDFRONT` or `REGIONAL`.
- **destination_arn** (required): The ARN of the log destination, its name carrying the
  `aws-waf-logs-` prefix.
- **redacted_fields** (required): The fields to redact (for example `authorization`, `cookie`).

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm a CloudFront web ACL's destination is in `us-east-1`

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm the destination name carries the `aws-waf-logs-` prefix
- You MUST verify or enable encryption at rest on the log destination before enabling logging,
  since WAF logs can capture credentials and session data. Use the mechanism for the destination
  type:

  ```
  # CloudWatch Logs: attach a KMS key to the log group
  aws logs associate-kms-key --log-group-name {log_group_name} --kms-key-id {kms_key_arn} --region {region}
  # Amazon S3: confirm default SSE (SSE-S3 or SSE-KMS) is set on the bucket
  aws s3api get-bucket-encryption --bucket {bucket_name}
  # Amazon Data Firehose: confirm server-side encryption is enabled on the stream
  aws firehose describe-delivery-stream --delivery-stream-name {stream_name} --region {region}
  ```

#### 2. Enable logging with redaction

**Constraints:**

- You MUST put the logging configuration with the redacted fields, passing the whole
  `--logging-configuration` as one JSON string (mixing CLI shorthand with inline JSON fails to
  parse, and `LogDestinationConfigs` is a list):

  ```
  aws wafv2 put-logging-configuration \
    --logging-configuration '{"ResourceArn":"{web_acl_arn}","LogDestinationConfigs":["{destination_arn}"],"RedactedFields":[{"SingleHeader":{"Name":"authorization"}},{"SingleHeader":{"Name":"cookie"}}]}' \
    --region {region}
  ```

#### 3. Confirm logs are flowing

**Constraints:**

- You MUST confirm log records are arriving at the destination before any rule is enabled
- You MUST confirm `SampledRequestsEnabled` is true on the web ACL visibility config

#### 4. Surface the console link

**Constraints:**

- You MUST present the web ACL console link and tell the customer to open the Logging and metrics
  tab to confirm logging is enabled:

  ```
  https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region={region}
  ```

### Example

#### Example input

```json
{
  "web_acl_arn": "arn:aws:wafv2:us-east-1:111122223333:regional/webacl/example-webacl/abc",
  "scope": "REGIONAL",
  "destination_arn": "arn:aws:logs:us-east-1:111122223333:log-group:aws-waf-logs-example",
  "redacted_fields": ["authorization", "cookie"]
}
```

#### Example output

```
Enabled logging for web ACL example-webacl to aws-waf-logs-example, redacting authorization and cookie.
Confirmed log records are arriving and request sampling is on.
Logging is ready — Count-mode tuning now has data to read.
Open the web ACL Logging and metrics tab to confirm:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### No logs arrive
The destination name lacks the `aws-waf-logs-` prefix or its policy blocks delivery (Step 1).

#### A CloudFront web ACL produces nothing
The destination is not in `us-east-1` (Step 1).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.
- **Protect log destinations.** Logs can capture credentials and session data. You MUST redact sensitive fields (such as the `authorization` header and `cookie`) and MUST enable encryption at rest on the log destination (CloudWatch Logs, Amazon S3, or Amazon Data Firehose).

## Additional Resources

- [Logging AWS WAF web ACL traffic (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/logging.html)
- [Testing and tuning your AWS WAF protections (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/web-acl-testing.html)
