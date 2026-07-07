# Migrating from a Third-Party Firewall

## Overview

Domain expertise for replacing a self-managed third-party firewall appliance (for example Palo Alto
or FortiGate, often running behind a Gateway Load Balancer) with AWS Network Firewall, without an
outage or a gap in inspection. Covers translating the appliance's rules into Network Firewall rule
groups, running the new firewall in parallel with the appliance to confirm it makes the same
decisions, cutting routing over endpoint by endpoint, and keeping a rollback path until the new
firewall is trusted.

This is a replacement, not first-time setup. The customer already has a working rule set and a live
traffic path to protect, so the work is sequenced to keep production inspected at every step.

Does not cover first-time firewall deployment, Suricata rule syntax in depth, logging, or TLS
inspection. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region` matching the firewall's Region on
every command.

## Table of Contents

- Overview
- Workflow
- Translate rules by intent, not one to one
- Run the firewall in parallel before cutover
- Cut routing over endpoint by endpoint with appliance mode
- Keep a rollback path until validated
- Size capacity for the translated rule set
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To migrate from a third-party firewall end to end, follow the procedure. It maps the appliance's
rules to Network Firewall rule groups by intent, stands the new firewall up alongside the appliance,
compares their decisions from the logs, cuts routing over one endpoint at a time with appliance mode
enabled, and keeps the appliance path available for rollback until the firewall is validated.

## Translate rules by intent, not one to one

The appliance and Network Firewall use different matching and evaluation models, so a literal
translation does not behave the same.

**Constraints:**

- You MUST map each appliance construct to its Network Firewall equivalent: application or URL rules
  to domain lists or Suricata rules, address objects to IP sets, top-down list order to rule group
  and policy order
- You MUST flag appliance constructs with no direct equivalent (for example application-ID matching)
  rather than translating them literally, and propose the closest Network Firewall mechanism
- You MUST note that Network Firewall matches domains on the TLS SNI and HTTP host header, not on the
  appliance's URL model, so HTTPS rules see the domain and not the path without TLS inspection

## Run the firewall in parallel before cutover

**Constraints:**

- You MUST route a subset of production traffic through the new firewall (for example by updating
  route tables for one AZ or one set of subnets) before any cutover; Network Firewall is inline-only
  and has no passive or tap mode, so traffic cannot be mirrored or copied to it
- You MUST compare the new firewall's alert and flow logs against the appliance's behavior to confirm
  it makes the same allow and block decisions

## Cut routing over endpoint by endpoint with appliance mode

**Constraints:**

- You MUST sequence the routing cutover one endpoint at a time, not all at once, so a problem affects
  one path and not the whole network
- You MUST route both directions of a flow through the same firewall endpoint; where the firewall is
  reached through a transit gateway, enable appliance mode on the transit gateway VPC attachment or
  stateful inspection breaks

## Keep a rollback path until validated

**Constraints:**

- You MUST keep the appliance path available as rollback until the new firewall is validated in
  production, rather than decommissioning the appliance at cutover
- You SHOULD define the rollback as reverting the route table change for the cut-over endpoint

## Size capacity for the translated rule set

**Constraints:**

- You MUST size rule group capacity for the translated rule set plus headroom at creation; capacity
  is immutable, and running out as the rules with no direct equivalent are added forces a recreate
- You SHOULD count the translated rules (including the ones that expand from a single appliance rule)
  before setting capacity

## Troubleshooting

### The new firewall blocks or allows differently than the appliance
A rule was translated literally where the model differs. Re-map by intent and compare logs in
parallel (Translate rules by intent, not one to one; Run the firewall in parallel before cutover).

### Connections break right after cutover
Asymmetric routing: the return path takes a different endpoint. Enable appliance mode and route both
directions through the same endpoint (Cut routing over endpoint by endpoint with appliance mode).

### Ran out of rule group capacity mid-migration
Capacity is immutable. Size for the full translated set plus headroom at creation (Size capacity for
the translated rule set).

## Procedure

### Overview

This procedure translates the appliance rules by intent, runs the new firewall in parallel to
compare decisions, cuts routing over endpoint by endpoint with appliance mode, and keeps the
appliance as rollback until validated.

### Parameters

- **firewall_name** (required): The new Network Firewall to migrate to.
- **appliance_type** (required): The appliance being replaced (for example Palo Alto, FortiGate).
- **endpoints** (required): The traffic paths or endpoints to cut over, in order.
- **uses_transit_gateway** (required): Whether the firewall is reached through a transit gateway.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the appliance rule set is available to translate before starting

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to the specific `network-firewall:` actions and resources this task needs, never long-lived access keys or broad administrative access
- You MUST confirm the new firewall exists and is `READY`, and that its policy and rule groups can
  hold the translated rules

#### 2. Translate the rules by intent

**Constraints:**

- You MUST map application or URL rules to domain lists or Suricata rules, address objects to IP
  sets, and flag constructs with no equivalent
- You MUST size rule group capacity for the full translated set plus headroom

#### 3. Run in parallel and compare

**Constraints:**

- You MUST route a subset of production traffic through the new firewall (for example by updating
  route tables for one AZ or one set of subnets) and compare its alert and flow logs against the
  appliance's decisions before cutover; Network Firewall is inline-only and traffic cannot be
  mirrored or copied to it

#### 4. Cut over endpoint by endpoint

**Constraints:**

- You MUST cut routing over one endpoint at a time, enabling appliance mode where a transit gateway
  is in the path:

  ```
  aws ec2 modify-transit-gateway-vpc-attachment \
    --transit-gateway-attachment-id {tgw_attachment_id} \
    --options ApplianceModeSupport=enable --region {region}
  ```

- You MUST keep the appliance path available to roll back each endpoint

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST confirm each cut-over endpoint is inspected by the new firewall before moving to the next,
  and decommission the appliance only after all endpoints are validated
- You MUST present the firewall console link, filling `{region}` and `{firewall_name}`:

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#FirewallDetails:firewallName={firewall_name}
  ```

### Example

#### Example input

```json
{
  "firewall_name": "replacement-fw",
  "appliance_type": "Palo Alto",
  "endpoints": ["egress-az1", "egress-az2"],
  "uses_transit_gateway": true
}
```

#### Example output

```
Translated Palo Alto app/URL rules to domain lists + Suricata, address objects to IP sets; flagged app-ID rules with no equivalent. Capacity sized for the full set plus headroom.
Parallel run: new firewall matched the appliance's allow/block decisions in the logs.
Cut egress-az1 over with appliance mode enabled, validated, then egress-az2. Appliance kept as rollback until both validated.
Open the console and confirm:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#FirewallDetails:firewallName=replacement-fw
```

### Troubleshooting

#### Decisions differ from the appliance
A literal translation where the model differs. Re-map by intent (Step 2).

#### Connections break after cutover
Asymmetric routing. Enable appliance mode and route both directions through the same endpoint (Step 4).

## Security Considerations

A migration must not open an inspection gap while the appliance is being replaced.

- You MUST keep production traffic inspected at every step: run the new firewall in parallel and
  confirm matching decisions before cutover, and keep the appliance path as rollback until the new
  firewall is validated.
- You MUST translate rules so the new policy preserves a default-drop posture rather than defaulting
  to allow when a construct has no direct equivalent; fail-closed is a fundamental security control
  for a network firewall, not an option, so flag such constructs rather than loosening the policy to
  make traffic flow.
- You MUST encrypt every destination that receives firewall logs (alert, flow, or TLS), using a
  customer-managed AWS KMS key on Amazon CloudWatch Logs log groups (`aws logs associate-kms-key`)
  and either SSE-S3 or a customer-managed AWS KMS key on Amazon S3 buckets, because these logs expose sensitive network metadata (source and
  destination IPs, domain names, and SNI values).
- You SHOULD scope each log destination's resource policy (the S3 bucket policy, the CloudWatch
  Logs resource policy, and the Amazon Data Firehose delivery-stream policy) with `aws:SourceArn`
  (the firewall's ARN) and `aws:SourceAccount` condition keys, so only this firewall in the
  expected account can write to the destination and another account or service cannot
  (confused-deputy prevention).
- You MUST encrypt the firewall's data at rest with a customer-managed AWS KMS key, and retain that
  key for the life of the firewall, since deleting or revoking it puts the firewall into a
  non-recoverable failed state.
- You MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to
  the specific `network-firewall:` actions and resources this task needs, never long-lived access
  keys or broad administrative access.
- You SHOULD enable AWS CloudTrail on the account so firewall, policy, rule group, and
  logging-configuration API changes are recorded for audit and incident review.
- You SHOULD configure CloudWatch alarms to alert on firewall endpoint failures, rule group capacity
  warnings, and traffic-volume anomalies during and after cutover, so regressions from the migration
  are detected and escalated promptly. You MUST encrypt any SNS topic used for these alarm
  notifications with a customer-managed AWS KMS key and restrict alarm notification recipients to
  authorized operations and security personnel, since alarm messages can expose sensitive firewall
  metadata (endpoint status, traffic patterns, and capacity).

## Additional Resources

- [Stateful rule groups in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/stateful-rule-groups.html)
- [Stateful domain list rule groups in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/stateful-rule-groups-domain-names.html)
- [Route table configurations for AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/route-tables.html)
- [Transit gateway attachment configuration for AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/vpc-config-tgw-multi-az.html)
- [Deployment models for AWS Network Firewall (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/deployment-models-for-aws-network-firewall/)
