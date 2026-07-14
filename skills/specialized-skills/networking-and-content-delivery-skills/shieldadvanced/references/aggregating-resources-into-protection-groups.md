# Aggregating Resources into Protection Groups

## Overview

Domain expertise for grouping AWS Shield Advanced protected resources so Shield treats them as one
unit for detection. Covers when a group helps (noisy per-resource detection, resources that share
traffic patterns), the aggregation choice (sum, mean, max), the membership pattern (all, by
resource type, or an explicit list), and the boundary that protection groups are detection-only and
do not apply shared mitigation.

Does not cover subscribing and protecting resources, automatic mitigation, health-based detection,
SRT setup, or event review; those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Shield Advanced control-plane calls run in
`us-east-1`; pass `--region us-east-1` on every command.

## Table of Contents

- Overview
- Workflow
- Decision: aggregation
- Decision: membership pattern
- Protection groups are detection-only
- Troubleshooting
- Security considerations
- Procedure
- Additional Resources

## Workflow

To aggregate resources into a protection group end to end, follow the procedure exactly. See the
Procedure section below.

The procedure covers:

- Confirming the member resources are already individually protected
- Choosing the aggregation and the membership pattern
- Creating the protection group
- Surfacing the console link to verify the group

## Always tell the customer (state all of these)

When advising on protection groups, you MUST state ALL of the following points together, not a
subset:

1. Protection groups are **detection and reporting only** — they do NOT apply shared mitigation;
   automatic mitigation still applies per individual resource, never to the group as a whole.
2. **Every member must already be individually protected with Shield Advanced before it joins the
   group** — a group built over unprotected resources shows **zero members** and aggregates nothing.
3. For a multi-tier topology (e.g. CloudFront in front of an Application Load Balancer in front of
   EC2), use **MAX aggregation** so one high-traffic tier is not diluted by the others.

The sections below give the detail behind each point.

## Decision: aggregation

| Aggregation | Behavior | Use when |
| --- | --- | --- |
| Sum | Combines traffic across all members | Many small-traffic resources, or a new resource that needs to inherit an existing baseline; reduces false positives |
| Mean | Averages traffic across members | Members with uniform traffic, such as a fleet of load balancers |
| Max | Tracks the highest single-member traffic | Multi-tier applications where one tier carries most of the traffic (for example CloudFront in front of an Application Load Balancer in front of EC2) |

**Constraints:**

- You MUST match the aggregation to the customer's topology rather than leaving it as a guess; the
  wrong choice makes detection too sensitive or too slow
- You SHOULD use sum for many small-traffic resources or for a new resource that needs an existing
  baseline, mean for uniform-traffic members, and max for a multi-tier application

## Decision: membership pattern

| Pattern | Behavior |
| --- | --- |
| All | All protected resources regardless of type |
| By resource type | All protected resources of a specified resource type |
| Arbitrary | A manually specified list of resource ARNs |

**Constraints:**

- You MUST choose a membership pattern that matches how the customer wants resources grouped
- You SHOULD use an arbitrary list when the customer wants a specific set of related resources (for
  example a distribution and the load balancer behind it) rather than a whole resource type

## Protection groups are detection-only

A protection group changes detection across its members; it does not apply mitigation as a group.
Customers expect a group to mitigate the whole set and are surprised when it does not.

**Constraints:**

- You MUST state that protection groups are for detection and reporting only
- You MUST tell the customer that automatic application layer mitigation still applies to
  individual resources, not to the group, even when the resources are grouped
- You MUST NOT present a protection group as a shared mitigation control
- You MUST tell the customer that every member resource must already be individually protected with
  Shield Advanced *before* it can be in the group: a protection group only aggregates resources that
  already carry their own protection, so a group built over unprotected resources shows zero members
  and aggregates nothing. State this membership prerequisite explicitly, not just by implication

## Troubleshooting

### A protection group shows zero members
The pattern only matches resources that are already individually protected. Protect the resources
first, then they fall into the group (Procedure, Step 1).

### Grouping did not mitigate an attack across the members
Protection groups are detection-only. Mitigation still applies per resource (Protection groups are
detection-only).

### Detection is too sensitive or too slow after grouping
The aggregation does not match the topology. Reconsider sum vs mean vs max (Decision: aggregation).

## Security considerations

Protection groups change detection across protected resources, so call out the risks and the
controls that contain them.

- **Removing the Shield rule group silently disables mitigation.** A protection group is
  detection-only and does not apply shared mitigation; automatic application layer mitigation still
  runs per resource through its `ShieldMitigationRuleGroup` rule group. Warn against removing that
  rule group from a web ACL during cleanup, since its removal turns off automatic mitigation for
  every resource using that web ACL with no obvious signal.
- **Least privilege for the operator.** Scope the caller's IAM permissions to the minimum this
  procedure needs (`shield:ListProtections`, `shield:CreateProtectionGroup`,
  `shield:ListProtectionGroups`) rather than broad Shield or administrator access.
- **Audit trail.** Keep AWS CloudTrail enabled and logging `shield:*` calls so every protection-group
  configuration change leaves a record, and confirm the CloudTrail trail uses SSE-KMS encryption on
  its S3 log bucket and CloudWatch Logs log group, since CloudTrail records contain sensitive API
  metadata (caller identities, resource ARNs, parameters).

## Procedure

### Overview

This procedure creates a protection group over resources that are already individually protected,
with the chosen aggregation and membership pattern, then surfaces the console link to verify.

### Parameters

- **protection_group_id** (required): A name for the protection group.
- **aggregation** (required): `SUM`, `MEAN`, or `MAX`.
- **pattern** (required): `ALL`, `BY_RESOURCE_TYPE`, or `ARBITRARY`.
- **resource_type** (required when pattern is `BY_RESOURCE_TYPE`): The resource type to group.
  `ALL` does not take a resource type.
- **members** (required when pattern is `ARBITRARY`): The list of resource ARNs to include.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm every intended member is already an individual Shield Advanced protection
  (via list-protections) BEFORE creating the group. A protection group never protects an
  unprotected resource; if members are not already protected the group is created with zero
  effective members and silently protects nothing

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD use temporary credentials from an assumed IAM role (for example via IAM Identity Center
  or an instance profile) rather than long-lived IAM user access keys for these security-sensitive
  Shield Advanced operations
- You SHOULD scope the caller's IAM permissions to the minimum this procedure needs
  (`shield:ListProtections`, `shield:CreateProtectionGroup`, `shield:ListProtectionGroups`) rather
  than broad Shield or administrator access
- You SHOULD confirm AWS CloudTrail is enabled and logging `shield:*` calls so every Shield Advanced
  configuration change leaves an audit trail
- You SHOULD confirm the CloudTrail trail is configured with SSE-KMS encryption on its S3 log bucket
  and CloudWatch Logs log group, since CloudTrail records contain sensitive API metadata (caller
  identities, resource ARNs, parameters)
- You MUST confirm the member resources are already protected:

  ```
  aws shield list-protections --region us-east-1
  ```

#### 2. Create the protection group

**Constraints:**

- You MUST create the group with the chosen aggregation and pattern. For an `ALL` pattern (every
  protected resource regardless of type), do not pass `--resource-type`:

  ```
  aws shield create-protection-group --protection-group-id {protection_group_id} \
    --aggregation {aggregation} --pattern ALL --region us-east-1
  ```

- For a `BY_RESOURCE_TYPE` pattern, you MUST pass the resource type:

  ```
  aws shield create-protection-group --protection-group-id {protection_group_id} \
    --aggregation {aggregation} --pattern BY_RESOURCE_TYPE --resource-type {resource_type} --region us-east-1
  ```

- For an `ARBITRARY` pattern, you MUST pass the member ARNs instead of a resource type:

  ```
  aws shield create-protection-group --protection-group-id {protection_group_id} \
    --aggregation {aggregation} --pattern ARBITRARY --members '["{member_arn}"]' --region us-east-1
  ```

#### 3. Confirm and surface the console link

**Constraints:**

- You MUST confirm the group was created:

  ```
  aws shield list-protection-groups --region us-east-1
  ```

- You MUST present the Shield protected-resources console link and tell the customer to open it and
  confirm the protection group and its members:

  ```
  https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/protections
  ```

### Example

#### Example input

```json
{
  "protection_group_id": "edge-and-origin",
  "aggregation": "MAX",
  "pattern": "ARBITRARY",
  "members": [
    "arn:aws:cloudfront::111122223333:distribution/EDFDVBD6EXAMPLE",
    "arn:aws:elasticloadbalancing:us-east-1:111122223333:loadbalancer/app/origin-alb/abc"
  ]
}
```

#### Example output

```
Confirmed both members are individually protected.
Created protection group edge-and-origin with MAX aggregation over the distribution and origin ALB.
Note: this groups detection only — automatic mitigation still applies per resource.
Open the Shield console and confirm the protection group:
https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/protections
```

#### Example input (group every protected Application Load Balancer)

```json
{
  "protection_group_id": "all-albs",
  "aggregation": "MEAN",
  "pattern": "BY_RESOURCE_TYPE",
  "resource_type": "APPLICATION_LOAD_BALANCER"
}
```

#### Example output (group every protected Application Load Balancer)

```
Confirmed protected Application Load Balancers exist.
Created protection group all-albs with MEAN aggregation over every protected ALB.
Note: this groups detection only — automatic mitigation still applies per resource.
Open the Shield console and confirm the protection group:
https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/protections
```

### Troubleshooting

#### The group shows zero members
The members are not individually protected. Protect them first (Step 1).

#### Grouping did not mitigate across members
Protection groups are detection-only (Protection groups are detection-only).

#### Detection is too sensitive or too slow
Reconsider the aggregation against the topology (Decision: aggregation).

## Additional Resources

- [Grouping your AWS Shield Advanced protections (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-protection-groups.html)
- [Adding and configuring resource protections with Shield Advanced (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-choose-resources.html)
