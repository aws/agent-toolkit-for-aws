# Enabling Firewall Logging and Tuning Rules

## Overview

Domain expertise for getting visibility into what an AWS Network Firewall allows and blocks, and
using that visibility to tune rules. Covers enabling logging after the firewall exists, choosing log
types (alert, flow, TLS), sending each type to a destination (Amazon S3, Amazon CloudWatch Logs, or
Amazon Data Firehose), and reading alert logs to find traffic that is wrongly dropped or wrongly
allowed.

Firewall logging only covers traffic forwarded to the stateful engine. Traffic handled
entirely by stateless rules never produces a log, so logging can look configured while the records
the customer wants are never generated.

Does not cover firewall deployment, rule authoring, or TLS inspection configuration. Those are
separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region` matching the firewall's Region
on every command.

## Table of Contents

- Overview
- Workflow
- Only stateful-engine traffic is logged
- Match the log type to the goal
- Match the destination to how the logs are used
- TLS logging needs TLS inspection
- Drops with no logs can be PQC ClientHello fragmentation
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To enable logging and tune rules end to end, follow the procedure. It confirms the traffic of
interest reaches the stateful engine, enables the needed log types to chosen destinations, and reads
the alert logs to adjust rule groups.

## Only stateful-engine traffic is logged

**Constraints:**

- You MUST confirm the traffic of interest is forwarded to the stateful engine before relying on
  logs; traffic handled entirely by stateless rules produces no log and the gap is silent
- You MUST name the stateless default action at work: of `aws:pass`, `aws:drop`, and
  `aws:forward_to_sfe`, only `aws:forward_to_sfe` sends traffic to the stateful engine where it can
  be logged; traffic a stateless rule passes or drops outright never appears in any log
- You SHOULD verify the stateless default action forwards to the stateful engine when the customer
  expects to see all flows

## Match the log type to the goal

**Constraints:**

- You SHOULD use alert logs for rule tuning and incident review: they are a small, targeted set tied
  to rules with a drop, alert, or reject action
- You SHOULD enable flow logs only when full traffic visibility is worth the volume and cost; flow
  logs capture every flow forwarded to the stateful engine and the volume surprises customers

## Match the destination to how the logs are used

**Constraints:**

- You SHOULD match the destination to the customer's analysis and retention needs rather than
  defaulting to one: Amazon S3, CloudWatch Logs, and Amazon Data Firehose differ in cost, retention,
  and how easily the logs are queried later
- You MUST encrypt the S3 log bucket with SSE-S3 or a customer-managed AWS KMS key (consult the
  current Amazon S3 and AWS Network Firewall logging documentation for the supported key types)
- You MUST enable encryption on CloudWatch Logs log groups receiving firewall logs using a
  customer-managed AWS KMS key (`aws logs associate-kms-key`) to protect sensitive network traffic
  metadata (source and destination IPs, domain names, SNI values, connection metadata)
- You MUST enable encryption on Amazon Data Firehose delivery streams receiving firewall logs using a
  customer-managed AWS KMS key, since these logs expose sensitive network metadata (source and
  destination IPs, domain names, and SNI values)

## TLS logging needs TLS inspection

**Constraints:**

- You MUST make TLS inspection a stated precondition for TLS logging; without TLS inspection
  configured, TLS logs are empty and the customer waits on records that will not arrive

## Drops with no logs can be PQC ClientHello fragmentation

Traffic dropped while no alert log appears at all is a distinct failure from "stateless traffic is
not logged" and "TLS logs need TLS inspection." A post-quantum (PQC) ClientHello that spans more
than one TCP segment defeats the firewall's Server Name Indication (SNI) extraction, so the firewall
applies the default action before any rule matches and writes no alert log.

**Constraints:**

- You SHOULD treat "traffic dropped, no alert log at all" as a possible PQC pattern: a client
  negotiating a post-quantum (PQC) key exchange adds over a thousand bytes to the ClientHello and
  pushes it across multiple TCP segments (consult the AWS Network Firewall TLS inspection
  documentation or the client runtime's current TLS/PQC documentation for the specific key-exchange
  algorithm names in effect)
- You SHOULD have the customer check for empty SNI fields or wholly absent log entries, since the
  drop happens before rule evaluation and so produces no rule-match log
- You SHOULD point the customer to SNI session holding as the firewall-side fix (it holds the
  connection until the SNI is seen and matched), with TLS inspection or IP-based rules as
  alternatives; client-side PQC disablement (consult the client runtime's current TLS/PQC
  documentation for the mechanism to disable post-quantum key exchange, where the runtime supports
  it) is an option only where the customer controls the client

## Troubleshooting

### Logging enabled but no records
The traffic is handled by stateless rules and never reaches the stateful engine. Forward it to the
stateful engine (Only stateful-engine traffic is logged).

### Log volume and cost higher than expected
Flow logs capture every flow. Use alert logs for tuning and reserve flow logs for when full
visibility is worth the cost (Match the log type to the goal).

### TLS logs are empty
TLS inspection is not configured. Configure it first (TLS logging needs TLS inspection).

### Traffic dropped but no alert log appears at all
Possibly PQC ClientHello fragmentation defeating SNI extraction, which drops before any rule matches.
Check for empty or absent SNI and enable SNI session holding (Drops with no logs can be PQC
ClientHello fragmentation).

## Procedure

### Overview

This procedure confirms traffic reaches the stateful engine, enables the chosen log types to chosen
destinations, and reads the alert logs to tune rules.

### Parameters

- **firewall_name** (required): The firewall to log.
- **log_types** (required): Any of `ALERT`, `FLOW`, `TLS`.
- **destinations** (required): Per log type, the destination type and target (S3 bucket, CloudWatch
  log group, or Amazon Data Firehose delivery stream).

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm TLS inspection is configured before enabling the `TLS` log type

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to the specific `network-firewall:` actions and resources this task needs, never long-lived access keys or broad administrative access
- You MUST confirm the firewall exists and the traffic of interest reaches the stateful engine
- You MUST confirm each destination exists and is writable by the firewall
- You MUST verify each CloudWatch Logs destination log group is encrypted with a customer-managed AWS
  KMS key before logs are written (`aws logs describe-log-groups --log-group-name-prefix {log_group}`);
  if not, enable it with `aws logs associate-kms-key --log-group-name {log_group} --kms-key-id
  {kms_key_arn}` so sensitive network metadata is encrypted from the first record
- You MUST verify each Amazon S3 destination bucket has default encryption enabled (SSE-S3 or a
  customer-managed AWS KMS key) before logs are
  written (`aws s3api get-bucket-encryption --bucket {bucket}`); if not, enable it so sensitive
  network metadata is encrypted from the first record — with a customer-managed AWS KMS key:

  ```
  aws s3api put-bucket-encryption --bucket {bucket} --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"{kms_key_arn}"}}]}'
  ```

  or with SSE-S3, use `"SSEAlgorithm":"AES256"` and omit `KMSMasterKeyID`
- You MUST verify each Amazon Data Firehose delivery stream encrypts records with a customer-managed
  AWS KMS key before logs are written (`aws firehose describe-delivery-stream --delivery-stream-name
  {stream}`); if not, enable it with `aws firehose start-delivery-stream-encryption
  --delivery-stream-name {stream} --delivery-stream-encryption-configuration-input
  KeyType=CUSTOMER_MANAGED_CMK,KeyARN={kms_key_arn}` so sensitive network metadata is encrypted from
  the first record
- You SHOULD scope each log destination's resource policy (the S3 bucket policy, the CloudWatch Logs
  resource policy, or the Amazon Data Firehose delivery-stream policy) with `aws:SourceArn` (the
  firewall's ARN) and `aws:SourceAccount` condition keys, so only this firewall in the expected
  account can write to the destination (confused-deputy prevention), e.g.:

  ```json
  "Condition": {
    "ArnLike": {"aws:SourceArn": "arn:aws:network-firewall:{region}:{account_id}:firewall/{firewall_name}"},
    "StringEquals": {"aws:SourceAccount": "{account_id}"}
  }
  ```

#### 2. Enable logging

**Constraints:**

- You MUST set the logging configuration with the chosen log types and destinations:

  ```
  aws network-firewall update-logging-configuration --firewall-name {firewall_name} \
    --logging-configuration '{"LogDestinationConfigs":[{"LogType":"ALERT","LogDestinationType":"CloudWatchLogs","LogDestination":{"logGroup":"/aws/network-firewall/alert/{firewall_name}"}}]}' \
    --region {region}
  ```

- You MUST NOT try to change a destination in place; disable then re-enable to move a log type

#### 3. Read alert logs and tune rules

**Constraints:**

- You SHOULD read alert logs to find traffic wrongly dropped or wrongly allowed, then adjust the
  rule groups
- You SHOULD confirm the traffic of interest appears in the logs before concluding a rule is wrong

#### 4. Confirm and surface the console link

**Constraints:**

- You MUST confirm logging is active and records are arriving at the destination
- You MUST present the firewall console link, filling `{region}` and `{firewall_name}`:

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#FirewallDetails:firewallName={firewall_name}
  ```

### Example

#### Example input

```json
{
  "firewall_name": "protected-vpc-fw",
  "log_types": ["ALERT", "FLOW"],
  "destinations": {
    "ALERT": {"type": "CloudWatchLogs", "target": "/aws/network-firewall/alert/protected-vpc-fw"},
    "FLOW": {"type": "S3", "target": "my-nfw-logs-bucket/flow"}
  }
}
```

#### Example output

```
Enabled ALERT logs to CloudWatch and FLOW logs to S3 for protected-vpc-fw.
Confirmed the traffic of interest is forwarded to the stateful engine.
Open the console and confirm logging:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#FirewallDetails:firewallName=protected-vpc-fw
```

### Troubleshooting

#### No records
Traffic is not reaching the stateful engine. Forward it (Step 1).

#### Cannot change a destination
Destinations cannot be updated in place. Disable then re-enable (Step 2).

## Security Considerations

Firewall logs record sensitive network metadata, so the log destinations need the same protection
as the traffic they describe.

- You MUST encrypt every destination that receives firewall logs (alert, flow, or TLS), using a
  customer-managed AWS KMS key on Amazon CloudWatch Logs log groups (`aws logs associate-kms-key`),
  either SSE-S3 or a customer-managed AWS KMS key on Amazon S3 buckets, and a customer-managed AWS KMS key on Amazon Data Firehose delivery
  streams, because these logs expose sensitive network metadata (source and destination IPs, domain
  names, and SNI values).
- You SHOULD scope each log destination's resource policy (the S3 bucket policy, the CloudWatch
  Logs resource policy, and the Amazon Data Firehose delivery-stream policy) with `aws:SourceArn`
  (the firewall's ARN) and `aws:SourceAccount` condition keys, so only this firewall in the
  expected account can write to the destination and another account or service cannot
  (confused-deputy prevention).
- You SHOULD restrict access to the log destinations to the operators and incident responders who
  need it.
- You MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to
  the specific `network-firewall:` actions and resources this task needs, never long-lived access
  keys or broad administrative access, because disabling logging silently removes the firewall's
  audit trail.
- You SHOULD enable AWS CloudTrail on the account so firewall, policy, rule group, and
  logging-configuration API changes are recorded for audit and incident review.
- You SHOULD configure CloudWatch alarms to alert on firewall endpoint failures, log-delivery
  failures, and alert-volume anomalies, so logging gaps and capacity warnings are detected and
  escalated promptly. You MUST encrypt any SNS topic used for these alarm notifications with a
  customer-managed AWS KMS key and restrict alarm notification recipients to authorized operations and
  security personnel, since alarm messages can expose sensitive firewall metadata (endpoint status,
  traffic patterns, and capacity).

## Additional Resources

- [Logging network traffic from AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/firewall-logging.html)
- [Cost considerations and common options for AWS Network Firewall log management (AWS Security Blog)](https://aws.amazon.com/blogs/security/cost-considerations-and-common-options-for-aws-network-firewall-log-management/)
- [Enhance TLS inspection with SNI session holding in AWS Network Firewall (AWS Security Blog)](https://aws.amazon.com/blogs/security/enhance-tls-inspection-with-sni-session-holding-in-aws-network-firewall/)
- [Considerations when working with TLS inspection configurations in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/tls-inspection-considerations.html)
