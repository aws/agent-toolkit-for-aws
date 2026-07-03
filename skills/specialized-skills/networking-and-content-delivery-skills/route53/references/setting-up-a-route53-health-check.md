# Setting Up a Route 53 Health Check

## Overview

Domain expertise for creating a Route 53 health check that monitors whether an endpoint is up,
choosing the right check type, handling private targets that public health checkers cannot reach,
and wiring the check to a CloudWatch alarm and an Amazon Simple Notification Service (SNS) topic
so someone is told when the endpoint goes unhealthy.

Does not cover the failover routing policy itself (that is the failover skill) or record
creation. A health check changes routing and raises alarms; it does not create records.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Decision: which health check type
- Decision: ETH vs a custom health check for an AWS resource
- Private targets
- Notifications
- Procedure
- Additional Resources

## Workflow

To create a health check and wire notifications, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Choosing the health check type
- Handling targets behind an Elastic Load Balancer with Evaluate Target Health (ETH)
- Handling private resources public checkers cannot reach
- Wiring a CloudWatch alarm and SNS topic for notifications
- Surfacing the console link to verify

## Decision: which health check type

| Type | Use when |
| --- | --- |
| Endpoint monitoring | A public HTTP, HTTPS, or TCP target |
| Calculated | The aggregate health of several child checks |
| CloudWatch alarm-based | A private resource, or any signal expressed as a CloudWatch metric |

**Constraints:**

- You MUST tell the customer that protocol, port, and IP address are immutable after creation.
  Fixing one means deleting the check and recreating it

## Decision: ETH vs a custom health check for an AWS resource

| Choice | Use when |
| --- | --- |
| Evaluate Target Health | The record is an alias to an AWS resource that reports its own health (ELB and other internal AWS targets). Free, nothing extra to maintain |
| Custom health check | The customer needs to monitor something ETH does not cover: a specific path, a non-ELB target, or a calculated combination |

**Constraints:**

- For an alias record pointing at an Elastic Load Balancer (ELB), you SHOULD prefer ETH. A
  Route 53 health check on the instances behind the ELB duplicates the monitoring the ELB already
  does, creates conflicting failure signals, and a check on a public ELB endpoint costs money per
  check

## Private targets

**Constraints:**

- You MUST recognize a private target before creating the check. Route 53 health checkers run
  from public AWS IP ranges; pointed at a private resource, a standard check reports all-failed
  and can never pass
- For an alias record to an internal AWS resource, use ETH. For anything with no usable target
  health, publish a custom signal to a CloudWatch metric (for example, from a Lambda function
  inside the VPC that probes the private resource) and back the health check with a CloudWatch
  alarm on that metric

## Notifications

**Constraints:**

- You MUST wire the health check to a CloudWatch alarm on its status metric, and point the alarm
  at an SNS topic the team subscribes to. A health check on its own changes routing and surfaces
  status, but does not notify anyone
- You MUST enable KMS server-side encryption (SSE) on the SNS topic (a new topic created with
  `--attributes KmsMasterKeyId={kms_key_id}`, or confirm an existing `sns_topic_arn` has SSE
  enabled), because the notification content can reveal endpoint and infrastructure topology
- You MUST confirm the SNS topic's subscription list is limited to authorized personnel before
  wiring the alarm, because health-check notifications reveal endpoint topology and availability
  status

## Procedure

### Overview

This procedure creates a Route 53 health check that monitors whether an endpoint is up. It
chooses the check type, handles targets behind an Elastic Load Balancer (ELB) with Evaluate
Target Health (ETH), handles private resources public checkers cannot reach, wires a CloudWatch
alarm and SNS topic for notifications, and surfaces the console link to verify.

### Parameters

- **target** (required): What to monitor: a public FQDN/IP, an alias-to-ELB record, or a private
  resource.
- **check_type** (required): `endpoint`, `calculated`, or `cloudwatch-alarm`.
- **protocol** (required for endpoint): `HTTP`, `HTTPS`, or `TCP`.
- **resource_path** (optional): The path to probe for HTTP/HTTPS checks (e.g., `/health`).
- **notify** (optional, default: true): Whether to wire a CloudWatch alarm and SNS topic.
- **sns_topic_arn** (optional): An existing SNS topic to notify.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm whether the target is public, behind an ELB, or private, because it changes
  the approach

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST REQUIRE provisioning credentials through ephemeral mechanisms (IAM roles via instance profiles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than long-lived IAM user access keys.
- You MUST enable Route 53 query logging to an encrypted destination where applicable, ensure CloudTrail is enabled to audit changes, and set CloudWatch alarms on health-check status where health checks are involved.

#### 2. Choose the approach for the target

**Constraints:**

- For an alias record to an ELB or other internal AWS resource, you SHOULD use ETH on the record
  rather than a standalone health check
- For a private resource with no usable target health, you MUST use a CloudWatch alarm-based
  check backed by a custom metric, not a standard endpoint check (public checkers cannot reach
  private resources)
- You MUST warn that protocol, port, and IP are immutable after creation

#### 3. Create the health check

**Constraints:**

- For a public endpoint:

  ```
  aws route53 create-health-check --caller-reference {ref} --health-check-config '{
    "Type": "{protocol}", "FullyQualifiedDomainName": "{fqdn}", "Port": {port},
    "ResourcePath": "{resource_path}", "RequestInterval": 30, "FailureThreshold": 3
  }'
  ```

- For a calculated check (aggregate health of several child checks):

  ```
  aws route53 create-health-check --caller-reference {ref} --health-check-config '{
    "Type": "CALCULATED",
    "ChildHealthChecks": ["{child_health_check_id_1}", "{child_health_check_id_2}"],
    "HealthThreshold": 1
  }'
  ```

  `HealthThreshold` is the minimum number of child checks that must be healthy for the calculated
  check to report Healthy.
- For a CloudWatch alarm-based check:

  ```
  aws route53 create-health-check --caller-reference {ref} --health-check-config '{
    "Type": "CLOUDWATCH_METRIC", "AlarmIdentifier": {"Region": "{region}", "Name": "{alarm_name}"},
    "InsufficientDataHealthStatus": "Unhealthy"
  }'
  ```

  Use `"Unhealthy"` as the default: a data gap forces the check unhealthy and acts on it rather
  than masking it. Override to `"LastKnownStatus"` only for standalone monitoring where spurious
  flaps from transient metric gaps are costlier than delayed detection.

#### 4. Wire notifications

**Constraints:**

- If `notify` is true, you MUST create a CloudWatch alarm on the health check status metric and
  point it at an SNS topic. You MUST enable KMS SSE on that topic — create a new topic with
  `aws sns create-topic --name {topic} --attributes KmsMasterKeyId={kms_key_id}`, or confirm a
  provided `sns_topic_arn` already has SSE enabled — because notification content can reveal
  infrastructure topology:

  ```
  aws cloudwatch put-metric-alarm \
    --alarm-name {alarm_name} --namespace AWS/Route53 \
    --metric-name HealthCheckStatus --dimensions Name=HealthCheckId,Value={health_check_id} \
    --statistic Minimum --period 60 --threshold 1 \
    --comparison-operator LessThanThreshold --evaluation-periods 1 \
    --alarm-actions {sns_topic_arn} --region us-east-1
  ```

- You MUST confirm the SNS topic's subscription list is limited to authorized personnel before
  wiring the alarm, because health-check notifications reveal endpoint topology and availability
  status

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST verify the check reports Healthy for a known-good target
- You MUST present the health check details console view, filling `{healthCheckId}`:

  ```
  https://console.aws.amazon.com/route53/v2/healthchecks/home#/details/{healthCheckId}
  ```

### Example

#### Example input

```json
{
  "target": "app.example.com",
  "check_type": "endpoint",
  "protocol": "HTTPS",
  "resource_path": "/health",
  "notify": true
}
```

#### Example output

```
Created HTTPS health check for app.example.com/health, wired to a CloudWatch alarm and SNS topic.
Verify in the console:
https://console.aws.amazon.com/route53/v2/healthchecks/home#/details/abcd1234-...
```

### Troubleshooting

#### Health check always Unhealthy for a target that is fine
The VPC security group may not allow inbound traffic from Route 53 health checkers. Add the
AWS-managed prefix list `com.amazonaws.<region>.route53-healthchecks` to the security group. If
the target is fully private, use ETH on the alias record or a CloudWatch alarm-based check
(Step 2). See [Configuring router and firewall rules for Route 53 health checks](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/dns-failover-router-firewall-rules.html).

#### Protocol, port, or IP fields are grayed out
Those fields are immutable. Delete and recreate the check (Step 2).

#### Duplicate or conflicting failure signals behind an ELB
A custom check duplicates the ELB's monitoring. Use ETH on the alias-to-ELB record (Step 2).

#### Endpoint went down but no one was alerted
The check is not wired to an alarm and topic. Add a CloudWatch alarm and SNS topic (Step 4).

## Security Considerations

- You SHOULD use least-privilege IAM credentials provisioned through ephemeral mechanisms (IAM
  roles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than
  long-lived IAM user access keys, and prefer read-only credentials for inspection steps.
- You MUST wire the health check to a CloudWatch alarm on its status metric pointed at an SNS
  topic, and ensure CloudTrail is enabled to audit health-check changes, because a check on its
  own raises no notification when an endpoint goes unhealthy.
- You MUST enable KMS server-side encryption on the SNS topic used for health-check alarm
  notifications, because notification content can reveal endpoint and infrastructure topology.
- You MUST confirm the SNS topic's subscription list is limited to authorized personnel.

## Additional Resources

- [Values that you specify when you create or update health checks (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/health-checks-creating-values.html)
- [Monitoring a private resource with a CloudWatch metric health check (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/health-checks-creating-cloudwatch.html)
- [Monitoring health check status and getting notifications (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/health-checks-monitor-view-status.html)
