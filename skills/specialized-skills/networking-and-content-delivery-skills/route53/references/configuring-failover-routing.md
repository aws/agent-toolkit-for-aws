# Configuring Failover Routing Across Regions with Route 53

## Overview

Domain expertise for active-passive failover of an application running in two AWS Regions for
disaster recovery (DR): sending traffic to a primary endpoint by default, monitoring its health,
and shifting to a secondary when the primary is unhealthy. Spans the failover records and the
health check that drives the decision. Covers the active-active alternative, the control plane
dependency trap, TTL and transition delay, internal-target health checks, and the static
stability pattern.

Does not cover CloudFront-specific failover or general record creation. Those are separate skills.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Decision: active-passive vs active-active
- Decision: how to health-check the failover target
- Decision: health-check-driven vs static stability
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To build region-level failover, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Choosing active-passive vs active-active
- Creating the health check on the primary and the primary/secondary failover records
- Handling internal targets with ETH (alias) or a CloudWatch alarm-based health check (private endpoint)
- Setting TTL against the recovery target
- Surfacing the console links to verify

## Decision: active-passive vs active-active

| Choice | Use when |
| --- | --- |
| Active-passive (failover routing policy) | A primary should serve and a secondary should stand by |
| Active-active (any policy, unhealthy records excluded) | Both Regions should serve traffic at once |

## Decision: how to health-check the failover target

The PRIMARY failover record needs a health signal, or Route 53 always treats it as healthy and
never fails over. Pick the mechanism by how the target is reached:

| Choice | Use when |
| --- | --- |
| Standard endpoint health check | The target is publicly reachable and the customer needs to probe a specific path or signal. Route 53's public health checkers connect to the endpoint directly |
| ETH (Evaluate Target Health on an alias record) | The target is an alias to a *supported* AWS resource whose health Route 53 can evaluate (e.g., an ALB/NLB, whether internet-facing or internal, or another in-zone record that has its own health check). No public probe is needed |
| CloudWatch alarm-based health check | The target is a private endpoint that is NOT an alias to a supported resource (e.g., a private EC2/IP behind a standard record). Public health checkers cannot reach it and ETH does not apply, so the health check watches a CloudWatch metric/alarm instead |

## Decision: health-check-driven vs static stability

| Choice | Use when |
| --- | --- |
| Health-check-driven | Typical DR |
| Static stability | The workload cannot tolerate any control plane dependency in the failover path |

**Constraints:**

- You MUST set the record TTL deliberately. DNS failover transition delay is the record TTL plus
  the health check evaluation time; a long TTL makes traffic move slowly during a failover
- You MUST NOT rely on a standard (public-probe) health check for a private target, because
  Route 53's public health checkers cannot reach it. Use ETH when the target is an alias to a
  supported AWS resource; use a CloudWatch alarm-based health check when the private target is
  reached by a standard record and ETH does not apply
- For the most critical workloads, you SHOULD offer the static stability pattern: pre-create both
  records and shift traffic by flipping health check state (for example, an inverted health check
  the customer controls) rather than editing DNS during the event. A DR runbook that creates
  health checks or updates records during a disaster reintroduces the control plane dependency the
  customer is trying to remove. The data plane (resolution, health checks, failover) carries the
  100% availability target; the control plane (creating checks, updating records) does not
- You SHOULD mention Route 53 Application Recovery Controller (ARC) Region Switch when the customer
  wants a managed multi-Region failover path rather than building it by hand

## Troubleshooting

### Traffic moves slowly during failover
A long record TTL adds to the transition delay. Lower the TTL deliberately based on the recovery
target.

### Health check unhealthy for a healthy internal target
Public health checkers cannot reach a private resource. Use ETH when the target is an alias to a
supported AWS resource; use a CloudWatch alarm-based health check for a private endpoint behind a
standard record.

### Failover did not happen during a real outage
The runbook depended on a control plane change in the failed Region. Pre-create records and
checks; use static stability for critical paths.

### Both Regions serving when only one should
Active-active was built where active-passive was intended. Use the failover routing policy.

## Procedure

### Overview

This procedure configures active-passive failover for an application in two AWS Regions. It
creates a health check on the primary endpoint and primary/secondary failover records, handles
internal targets with ETH or a CloudWatch alarm-based health check, sets the TTL against the
recovery target, and surfaces the console links to verify.

### Parameters

- **hosted_zone_id** (required): The hosted zone ID for the failover records.
- **record_name** (required): The DNS name to fail over (e.g., `app.example.com`).
- **primary_target** (required): The primary Region's endpoint.
- **secondary_target** (required): The secondary Region's endpoint.
- **ttl** (optional, default: 60): TTL in seconds for the failover records. Set against the
  recovery target.
- **target_reachability** (optional, default: `public`): How the failover targets are reached,
  which selects the health-check mechanism:
  - `public` — publicly reachable endpoint → standard endpoint health check
  - `alias_to_aws_resource` — alias to a supported AWS resource (e.g., ALB/NLB, whether
    internet-facing or internal) whose health Route 53 evaluates directly → ETH (free, no probe)
  - `internal_endpoint` — private endpoint behind a standard record (e.g., private EC2/IP), where
    ETH does not apply → CloudWatch alarm-based health check
- **alarm_name** / **alarm_region** (required when `target_reachability` is `internal_endpoint`):
  The CloudWatch alarm that reflects the primary endpoint's health, and its Region.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the primary and secondary targets and the hosted zone before writing
- You MUST set the TTL deliberately against the customer's recovery target

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST REQUIRE provisioning credentials through ephemeral mechanisms (IAM roles via instance profiles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than long-lived IAM user access keys.
- You MUST enable Route 53 query logging to an encrypted destination where applicable, ensure CloudTrail is enabled to audit changes, and set CloudWatch alarms on health-check status where health checks are involved.

#### 2. Choose active-passive vs active-active

**Constraints:**

- You MUST confirm whether the customer wants a standby secondary (active-passive, failover
  policy) or both Regions serving (active-active, any policy with unhealthy records excluded)

#### 3. Create the health check on the primary

**Constraints:**

- If `target_reachability` is `public`, create a standard endpoint health check. Match the target
  field to `{primary_target}`: use `"IPAddress": "{primary_target}"` when the target is an IP, use
  `"FullyQualifiedDomainName": "{primary_target}"` when it is a hostname, or set both together to
  probe a specific IP with a `Host` header. Passing a dotted-decimal IP to
  `FullyQualifiedDomainName` is wrong because Route 53 then tries to DNS-resolve it:

  ```
  # When primary_target is an IP:
  aws route53 create-health-check --caller-reference {ref} --health-check-config '{
    "Type": "HTTPS", "IPAddress": "{primary_target}", "Port": 443,
    "ResourcePath": "/health", "RequestInterval": 30, "FailureThreshold": 3
  }'

  # When primary_target is a hostname:
  aws route53 create-health-check --caller-reference {ref} --health-check-config '{
    "Type": "HTTPS", "FullyQualifiedDomainName": "{primary_target}", "Port": 443,
    "ResourcePath": "/health", "RequestInterval": 30, "FailureThreshold": 3
  }'
  ```

- If `target_reachability` is `alias_to_aws_resource`, do NOT create a standard health check against
  the target. Use ETH on the alias record instead (Step 4) — Route 53 evaluates the supported
  resource's own health directly, so a paid standard health check is unnecessary whether the
  resource is internet-facing or internal
- If `target_reachability` is `internal_endpoint`, the target is private and not an alias to a
  supported resource, so ETH does not apply. Create a CloudWatch alarm-based health check that
  watches a metric reflecting the endpoint's health, then attach it to the primary record in
  Step 4:

  ```
  aws route53 create-health-check --caller-reference {ref} --health-check-config '{
    "Type": "CLOUDWATCH_METRIC",
    "AlarmIdentifier": {"Region": "{alarm_region}", "Name": "{alarm_name}"},
    "InsufficientDataHealthStatus": "Unhealthy"
  }'
  ```

  Set `"Unhealthy"` because this check drives failover: a data gap should force failover to the
  secondary rather than preserve a stale state on the primary.

#### 4. Create the failover records

**Constraints:**

- You MUST create a primary failover record and a secondary failover record with the same name
  and type:

  ```
  aws route53 change-resource-record-sets --hosted-zone-id {hosted_zone_id} --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "{record_name}", "Type": "A",
        "SetIdentifier": "primary", "Failover": "PRIMARY",
        "TTL": {ttl}, "ResourceRecords": [{"Value": "{primary_target}"}],
        "HealthCheckId": "{health_check_id}"
      }
    }]
  }'
  ```

- For an `alias_to_aws_resource` target, set `AliasTarget` with `EvaluateTargetHealth: true` instead
  of a `HealthCheckId`. For `public` and `internal_endpoint` targets, attach the health check created
  in Step 3 via `HealthCheckId`
- Repeat for the secondary with `SetIdentifier: secondary` and `Failover: SECONDARY`

#### 5. Offer static stability for critical workloads

**Constraints:**

- You SHOULD offer the static stability pattern when the workload cannot tolerate a control plane
  dependency in the failover path: pre-create both records and shift traffic by flipping a health
  check state the customer controls, with no DNS edit during the event
- You SHOULD mention Route 53 ARC Region Switch as the managed alternative

#### 6. Verify and surface the console links

**Constraints:**

- You MUST verify the records resolve to the primary while healthy, and that an unhealthy primary
  shifts traffic to the secondary within the expected window (TTL plus health check evaluation)
- You MUST present the console links, filling `{hostedZoneId}` and `{healthCheckId}`:
  - Records view:

    ```
    https://console.aws.amazon.com/route53/v2/hostedzones#ListRecordSets/{hostedZoneId}
    ```

  - Health check details:

    ```
    https://console.aws.amazon.com/route53/v2/healthchecks/home#/details/{healthCheckId}
    ```

### Example

#### Example input

```json
{
  "hosted_zone_id": "Z1234567890ABC",
  "record_name": "app.example.com",
  "primary_target": "192.0.2.1",
  "secondary_target": "198.51.100.1",
  "ttl": 60
}
```

#### Example output

```
Created failover records for app.example.com (primary 192.0.2.1, secondary 198.51.100.1)
with health check on the primary.
Verify in the console:
https://console.aws.amazon.com/route53/v2/hostedzones#ListRecordSets/Z1234567890ABC
https://console.aws.amazon.com/route53/v2/healthchecks/home#/details/abcd1234-...
```

### Troubleshooting

#### Traffic moves slowly during failover
Long record TTL adds to the transition delay. Lower the TTL against the recovery target (Step 4).

#### Health check unhealthy for a healthy internal target
Public health checkers cannot reach a private resource. Use ETH for an alias to a supported
resource, or a CloudWatch alarm-based health check for a private endpoint (Step 3/4).

#### Failover did not happen during a real outage
The runbook depended on a control plane change in the failed Region. Pre-create records and
checks; use static stability (Step 5).

#### Both Regions serving when only one should
Active-active built where active-passive was intended. Use the failover routing policy (Step 2).

## Security Considerations

- You SHOULD use least-privilege IAM credentials provisioned through ephemeral mechanisms (IAM
  roles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than
  long-lived IAM user access keys, and prefer read-only credentials for inspection steps. Grant
  only the specific actions this procedure needs — `route53:CreateHealthCheck`,
  `route53:ChangeResourceRecordSets`, and `route53:GetChange` to create the health check and
  failover records and confirm propagation, plus `route53:ListResourceRecordSets`,
  `route53:GetHostedZone`, and `route53:GetHealthCheckStatus` for inspection — rather than
  `route53:*` or broader `service:*` wildcards.
- You MUST enable Route 53 query logging to an encrypted destination (KMS on CloudWatch Logs,
  SSE-S3/SSE-KMS on S3, or server-side encryption on a Data Firehose stream) and ensure CloudTrail
  is enabled to audit record and health-check changes.
- You SHOULD set a CloudWatch alarm on the primary health check's status metric with an SNS
  notification, so the team is alerted when a failover triggers rather than discovering it later.
  A failover configuration without monitoring leaves the team unaware that failover has occurred.
- You MUST enable KMS server-side encryption on the SNS topic used for health-check alarm
  notifications, because notification content can reveal endpoint and infrastructure topology.
- You MUST confirm the SNS topic's subscription list is limited to authorized personnel.
- You MUST keep the failover path free of control plane dependencies for the most critical
  workloads (static stability), so a Regional event does not also disable the mechanism that moves
  traffic away from it.

## Additional Resources

- [Active-active and active-passive failover (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/dns-failover-types.html)
- [Creating Disaster Recovery Mechanisms Using Amazon Route 53 (Networking & Content Delivery blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/creating-disaster-recovery-mechanisms-using-amazon-route-53/)
- [Manual Failover and Failback Strategy with Amazon Route 53 (Networking & Content Delivery blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/manual-failover-and-failback-strategy-with-amazon-route53/)
