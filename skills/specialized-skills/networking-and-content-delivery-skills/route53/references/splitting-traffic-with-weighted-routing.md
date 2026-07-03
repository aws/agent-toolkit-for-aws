# Splitting Traffic with Route 53 Weighted Routing

## Overview

Domain expertise for splitting DNS responses across two or more endpoints in a defined ratio
using weighted records: blue/green deployments, canary releases, A/B testing, and gradual
cutover. Covers how weights are interpreted, how to take an endpoint out of rotation safely,
health-aware routing for non-AWS targets, and the two distinct zero-weight behaviors.

Does not cover failover routing (a separate skill), latency or geolocation routing, or complex
nested Traffic Flow policies.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Weights are relative, not percentages
- Decision: zero-weight vs delete to stop traffic
- Health-aware routing for non-AWS endpoints
- Two zero-weight behaviors
- Troubleshooting
- Procedure
- Additional Resources

## Workflow

To split traffic with weighted records, follow the procedure exactly.
See the Procedure section below.

The procedure covers:

- Creating one weighted record per endpoint with the right relative weights
- Taking an endpoint out of rotation with a zero weight while keeping rollback
- Attaching health checks to non-alias weighted records
- Surfacing the console link to verify

## Weights are relative, not percentages

**Constraints:**

- You MUST compute each record's share as its weight divided by the sum of all weights for that
  name and type. Records weighted 1, 1, 2 send 25, 25, and 50 percent of queries, not 1, 1, and 2
  percent. Do not let the customer read the weight as a percent value
- Each weight MUST be an integer from 0 to 255. To express a fine-grained split (for example
  99.5/0.5), scale the ratio to fit within 0 to 255; a raw split wider than 255 to 1 cannot be
  expressed directly
- You MUST NOT create a non-weighted (simple) record with the same name and type as a weighted
  record. Route 53 forbids mixing the two for one name and type

## Decision: zero-weight vs delete to stop traffic

| Choice | Use when |
| --- | --- |
| Zero-weight | The pull is temporary and instant rollback matters (canary abort, blue/green hold). The record stays in place; raising the weight restores traffic |
| Delete | The endpoint is going away for good |

**Constraints:**

- You SHOULD set an endpoint's weight to zero to pull traffic while keeping rollback. Deleting the
  record also stops traffic but throws away instant rollback

## Health-aware routing for non-AWS endpoints

**Constraints:**

- You MUST attach a health check explicitly to each non-alias weighted record (raw IPs, external
  hostnames). Evaluate Target Health works for alias records but not for non-alias targets, so
  without a health check an unhealthy non-AWS endpoint keeps receiving its share

## Two zero-weight behaviors

A zero weight behaves in two completely different ways depending on whether all weights are zero
and whether health checks are attached. Do not conflate them.

**Constraints:**

- You MUST warn the customer that setting every record in the group to weight 0 does NOT stop
  traffic. Route 53 treats all-zero as a safety net and routes to every record with equal
  probability. To actually take traffic off an endpoint, leave at least one other record with a
  nonzero weight, or delete the records. An operator zeroing every record to halt traffic during
  an incident will instead spread traffic evenly across all of them
- You SHOULD tell the customer that the health-based fallback is a separate mechanism: when nonzero
  records carry health checks, Route 53 serves only the healthy nonzero records, and falls back to
  zero-weighted records only if every nonzero record is unhealthy. This makes a zero-weight record
  a last-resort backup
- You MUST state the precondition for that fallback: it only triggers when the nonzero records have
  health checks attached. Without health checks, a record is always treated as eligible, so a
  zero-weight backup is never reached

## Troubleshooting

### Traffic split is not what was expected
Weights were read as percentages instead of relative shares. Recompute: each share is its weight
divided by the sum of all weights.

### Cannot roll back after stopping traffic
The record was deleted instead of zero-weighted. Use weight zero to pull traffic while keeping
the record.

### Dead non-AWS endpoint still gets traffic
No health check is attached to the non-alias record. Attach a health check to each non-alias
weighted record.

### Zeroing every record did not stop traffic
Expected. All-zero is a safety net: Route 53 routes to every record equally. Leave one record
nonzero, or delete the records, to actually pull traffic.

### Zero-weight backup never receives traffic when others fail
The nonzero records have no health checks, so Route 53 never sees them as unhealthy and never
falls back. Attach health checks to the nonzero records.

## Procedure

### Overview

This procedure splits DNS responses across two or more endpoints in a defined ratio using
weighted records. It creates one weighted record per endpoint, takes an endpoint out of rotation
safely with a zero weight, attaches health checks to non-alias targets, and surfaces the console
link to verify.

### Parameters

- **hosted_zone_id** (required): The hosted zone ID.
- **record_name** (required): The shared record name (e.g., `app.example.com`).
- **record_type** (required): The shared record type (e.g., `A`).
- **endpoints** (required): A list of `{set_identifier, target, weight}` triples, one per endpoint.
  `set_identifier` is a label unique within the weighted group (for example the target value or a
  short name); Route 53 requires a distinct `SetIdentifier` per record in the group.
- **health_checks** (optional): Health check IDs for non-alias targets.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the intended split ratio and translate it to relative weights with the
  customer

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST REQUIRE provisioning credentials through ephemeral mechanisms (IAM roles via instance profiles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than long-lived IAM user access keys.
- You MUST enable Route 53 query logging to an encrypted destination where applicable, ensure CloudTrail is enabled to audit changes, and set CloudWatch alarms on health-check status where health checks are involved.

#### 2. Create one weighted record per endpoint

**Constraints:**

- You MUST create one record per endpoint with the same name and type, each with its own weight
  and a unique `SetIdentifier`:

  ```
  aws route53 change-resource-record-sets --hosted-zone-id {hosted_zone_id} --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "{record_name}", "Type": "{record_type}",
        "SetIdentifier": "{set_identifier}", "Weight": {weight},
        "TTL": 60, "ResourceRecords": [{"Value": "{target}"}]
      }
    }]
  }'
  ```

- You MUST remind the customer that weights are relative shares, not percentages

#### 3. Attach health checks to non-alias targets

**Constraints:**

- For non-alias targets (raw IPs, external hostnames), you MUST attach a `HealthCheckId` to each
  weighted record, or unhealthy endpoints keep receiving their share. Evaluate Target Health does
  not cover non-alias targets

#### 4. Take an endpoint out of rotation (when needed)

**Constraints:**

- You SHOULD set an endpoint's weight to zero to pull traffic while keeping the record for instant
  rollback, rather than deleting the record

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST verify the query distribution matches the intended ratio
- You MUST present the records view console link, filling `{hostedZoneId}`:

  ```
  https://console.aws.amazon.com/route53/v2/hostedzones#ListRecordSets/{hostedZoneId}
  ```

### Example

#### Example input

```json
{
  "hosted_zone_id": "Z1234567890ABC",
  "record_name": "app.example.com",
  "record_type": "A",
  "endpoints": [
    {"set_identifier": "primary-192.0.2.10", "target": "192.0.2.10", "weight": 9},
    {"set_identifier": "canary-192.0.2.20", "target": "192.0.2.20", "weight": 1}
  ]
}
```

#### Example output

```
Created 2 weighted A records for app.example.com (90% / 10% split).
Verify in the console:
https://console.aws.amazon.com/route53/v2/hostedzones#ListRecordSets/Z1234567890ABC
```

### Troubleshooting

#### Traffic split is not what was expected
Weights read as percentages. Recompute: share = weight / sum of weights (Step 2).

#### Cannot roll back after stopping traffic
The record was deleted instead of zero-weighted. Use weight zero (Step 4).

#### Dead non-AWS endpoint still gets traffic
No health check on the non-alias record. Attach one to each (Step 3).

## Security Considerations

- You SHOULD use least-privilege IAM credentials provisioned through ephemeral mechanisms (IAM
  roles, SSO/IAM Identity Center session credentials, or `aws sts assume-role`) rather than
  long-lived IAM user access keys, and prefer read-only credentials for inspection steps. Grant
  only the specific actions this procedure needs — `route53:ChangeResourceRecordSets` and
  `route53:GetChange` to create the weighted records and confirm propagation, plus
  `route53:ListResourceRecordSets` and `route53:GetHostedZone` for inspection — rather than
  `route53:*` or broader `service:*` wildcards.
- You MUST enable Route 53 query logging to an encrypted destination (KMS on CloudWatch Logs,
  SSE-S3/SSE-KMS on S3, or server-side encryption on a Data Firehose stream) to confirm the
  weighted distribution matches expectations, and ensure CloudTrail is enabled to audit record
  changes. This matters most for canary and blue/green cutovers, where an unexpected split can
  cause an outage.
- You SHOULD set CloudWatch alarms on the health-check status metrics of any health checks
  attached to the weighted records with an SNS notification, so an unhealthy endpoint still
  receiving its share is detected.
- You MUST enable KMS server-side encryption on the SNS topic used for health-check alarm
  notifications, because notification content can reveal endpoint and infrastructure topology.
- You MUST confirm the SNS topic's subscription list is limited to authorized personnel.

## Additional Resources

- [Weighted routing (Route 53 Developer Guide)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/routing-policy-weighted.html)
- [Weighted routing rule (Route 53 console help panel)](https://docs.aws.amazon.com/help-panel/Route53/latest/console/traffic_flow_weighted_routing_rule.html)
