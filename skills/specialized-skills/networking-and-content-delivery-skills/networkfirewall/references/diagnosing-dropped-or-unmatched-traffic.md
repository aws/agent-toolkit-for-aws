# Diagnosing Dropped or Unmatched Traffic

## Overview

Domain expertise for finding why an AWS Network Firewall drops traffic that should pass, passes
traffic that should drop, or has a rule that does not seem to act on the traffic it targets. Covers
reading the firewall endpoint status message, testing routing symmetry, and checking `HOME_NET`,
evaluation order, rule layer, and inspection limits before rewriting anything.

The investigation is driven by the symptom, not by guesswork. Each symptom traces to a small set of
causes, and several of them are invisible without a deliberate check (asymmetric routing, a
`HOME_NET` that does not cover the source ranges, a flow exceeding the inspection limits).

Does not cover firewall deployment, rule authoring from scratch, or TLS inspection setup. Those are
separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region` matching the firewall's Region
on every command.

## Table of Contents

- Overview
- Workflow
- Read the endpoint status: error vs failure
- Test routing symmetry before rewriting rules
- HOME_NET defaults to the inspection VPC
- Drop rule not taking effect: order and layer
- A rule matches intermittently
- Drops with no logs: PQC ClientHello fragmentation
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To diagnose unexpected firewall behavior, follow the procedure. It starts from the symptom: an
endpoint that will not come up gets its status message read first; traffic that is dropped or never
reaches a rule gets routing, `HOME_NET`, evaluation order, rule layer, and inspection limits checked
in turn, then the specific cause is corrected.

## Read the endpoint status: error vs failure

The endpoint status message names the cause and tells you whether the state is recoverable. The
message can take up to 15 minutes to appear.

**Constraints:**

- You MUST read the endpoint status message first when an endpoint will not come up, from
  `describe-firewall` (firewall subnet endpoint) or `describe-vpc-endpoint-association` (VPC
  endpoint association)
- You MUST interpret the state: an `Error` is something the customer can fix, after which the
  service retries automatically; a `Failed` state is non-recoverable and requires deleting and
  recreating the firewall
- You MUST note that a deleted or revoked KMS key puts the firewall into a failed state that drops
  all traffic

## Test routing symmetry before rewriting rules

Network Firewall does not support asymmetric routing: request and response must traverse the same
firewall endpoint, or stateful features break. This is invisible without a deliberate test.

**Constraints:**

- You SHOULD run the documented symmetry test before rewriting rules: attach an empty strict-order
  policy that forwards to the stateful engine, add a single `alert tcp any any -> any any
  (... flow:established ...)` rule, generate a connection, and confirm the alert fires
- You SHOULD confirm both the request and response flow logs share the same `flow_id`; seeing only
  the request side means the return path is routing around the firewall endpoint

## HOME_NET defaults to the inspection VPC

**Constraints:**

- You MUST check whether the firewall inspects traffic from outside its own VPC when rules match
  nothing for spoke-VPC traffic; `HOME_NET` defaults to the inspection VPC's CIDR and the console
  does not surface this for every rule group
- You MUST override `HOME_NET` in the firewall policy to include the spoke CIDRs before concluding
  the rules are wrong; Network Firewall keeps `EXTERNAL_NET` as the negation of the `HOME_NET` you set

## Drop rule not taking effect: order and layer

A drop rule that does not stop traffic has two common causes the symptom does not distinguish.

**Constraints:**

- You MUST check the policy's evaluation order: under action order, pass rules evaluate before drop
  rules and the default action is pass, so traffic likely matched a pass rule. Recommend strict
  order with `aws:drop_established` and `aws:alert_established` default actions
- You MUST check the rule's layer: a blanket TCP (Layer 4) rule can act on a connection before the
  HTTP (Layer 7) rule the customer intended, because the engine sees TCP before it can detect HTTP.
  Add `flow:to_server` so the lower-layer rule waits until the application protocol is detected

## A rule matches intermittently

**Constraints:**

- You SHOULD explain that a flow exceeding the stateful engine's inspection limits (for example the
  TCP reassembly depth) cannot be matched past that point, which looks like an intermittent miss
- You SHOULD add a `stream-event:reassembly_depth_reached` alert rule so the condition surfaces in
  the logs instead of staying invisible

## Drops with no logs: PQC ClientHello fragmentation

Traffic dropped while no alert log appears at all is its own branch, distinct from stateless traffic
not being logged and from TLS logs needing TLS inspection. The drop happens before any rule matches,
so there is no rule-match log to find.

**Constraints:**

- You SHOULD suspect post-quantum (PQC) ClientHello fragmentation when the customer reports drops
  with no alert log: a client negotiating a post-quantum key exchange sends an oversized ClientHello
  across more than one TCP segment, the firewall cannot read the Server Name Indication (SNI) from
  the fragment, and it applies the default action before rule evaluation. Consult the AWS Network
  Firewall TLS inspection documentation or the client runtime's current TLS/PQC documentation for the
  specific key-exchange algorithm names in effect
- You SHOULD have the customer check for empty SNI fields or wholly absent log entries, then point
  them to SNI session holding as the firewall-side fix, with TLS inspection or IP-based rules as
  alternatives, before they rewrite any rules

## Troubleshooting

### Endpoint will not come up
Read the status message and interpret error (fixable, auto-retried) vs failure (delete and recreate)
(Read the endpoint status: error vs failure).

### Stateful inspection fails erratically
Likely asymmetric routing. Run the symmetry test (Test routing symmetry before rewriting rules).

### Rules match nothing for other VPCs
`HOME_NET` covers only the inspection VPC. Override it (HOME_NET defaults to the inspection VPC).

### Drop rule does not stop traffic
Action order let a pass rule fire first, or a TCP rule acted before the HTTP rule. Switch to strict
order and add `flow:to_server` (Drop rule not taking effect: order and layer).

### Rule matches intermittently
The flow exceeded an inspection limit. Add a reassembly-depth alert rule to confirm (A rule matches
intermittently).

### Traffic dropped but no alert log at all
Possibly PQC ClientHello fragmentation defeating SNI extraction, dropping before rule evaluation.
Check for empty or absent SNI and enable SNI session holding (Drops with no logs: PQC ClientHello
fragmentation).

## Procedure

### Overview

This procedure works from the symptom: read the endpoint status, test routing symmetry, then check
`HOME_NET`, evaluation order, rule layer, and inspection limits, and correct the specific cause.

### Parameters

- **firewall_name** (required): The firewall to diagnose.
- **symptom** (required): One of `endpoint-down`, `traffic-dropped`, `traffic-passed`, `rule-not-matching`.
- **deployment** (optional): `single-vpc` or `centralized`, to decide whether a `HOME_NET` override applies.

**Constraints for parameter acquisition:**

- You MUST ask for the firewall name and the symptom upfront
- You MUST NOT rewrite rules before reading the endpoint status and testing routing symmetry

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to the specific `network-firewall:` actions and resources this task needs, never long-lived access keys or broad administrative access
- You MUST confirm the firewall exists and identify its policy and rule groups

#### 2. Read the endpoint status (for endpoint-down)

**Constraints:**

- You MUST read the status message and interpret error vs failure:

  ```
  aws network-firewall describe-firewall --firewall-name {firewall_name} \
    --query 'FirewallStatus.SyncStates' --region {region}
  ```

- You MUST treat a `Failed` state (for example from a deleted KMS key) as non-recoverable: delete
  and recreate the firewall

#### 3. Test routing symmetry (for dropped or erratic traffic)

**Constraints:**

- You SHOULD run the documented symmetry test with an empty strict-order policy and a single
  `flow:established` alert rule, then confirm request and response flow logs share a `flow_id`
- You SHOULD enable appliance mode on the transit gateway VPC attachment when return traffic takes a
  different path in a centralized deployment

#### 4. Check HOME_NET, evaluation order, and rule layer

**Constraints:**

- You MUST override `HOME_NET` in the policy to include spoke CIDRs for a centralized deployment when
  rules match nothing for spoke traffic
- You MUST switch a policy from action order to strict order (with `aws:drop_established` and
  `aws:alert_established` defaults) when a drop rule does not take effect because a pass rule fired
  first
- You MUST add `flow:to_server` to a lower-layer rule that acts before the intended application-layer
  rule

#### 5. Check inspection limits and PQC fragmentation (for intermittent matches or drops with no logs)

**Constraints:**

- You SHOULD add a `stream-event:reassembly_depth_reached` alert rule to confirm a flow is exceeding
  the inspection limit
- You SHOULD suspect PQC ClientHello fragmentation when drops have no alert log at all: check for
  empty or absent SNI and enable SNI session holding, or fall back to TLS inspection or IP-based
  rules

#### 6. Confirm and surface the console link

**Constraints:**

- You MUST confirm the corrected behavior with logs or a test connection
- You MUST present the firewall console link, filling `{region}` and `{firewall_name}`:

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#FirewallDetails:firewallName={firewall_name}
  ```

### Example

#### Example input

```json
{
  "firewall_name": "protected-vpc-fw",
  "symptom": "traffic-dropped",
  "deployment": "centralized"
}
```

#### Example output

```
Endpoint status READY, so not an endpoint failure.
Symmetry test: alert fired and request+response flow logs share flow_id 7766... routing is symmetric.
HOME_NET covered only the inspection VPC; overrode it to include spoke CIDRs 10.20.0.0/16.
Spoke traffic now matches the rules. Open the console and confirm:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#FirewallDetails:firewallName=protected-vpc-fw
```

### Troubleshooting

#### Endpoint failed, not error
Non-recoverable. Delete and recreate the firewall (Step 2).

#### Only request-side flow logs
Return path routes around the firewall. Fix routing or enable appliance mode (Step 3).

#### Drop rule still passes traffic
Action order or a lower-layer rule. Switch to strict order and add `flow:to_server` (Step 4).

## Security Considerations

Diagnosis reads sensitive traffic data and can tempt loosening the policy to make a symptom go away.

- You MUST encrypt every destination that receives firewall logs (alert, flow, or TLS), using a
  customer-managed AWS KMS key on Amazon CloudWatch Logs log groups (`aws logs associate-kms-key`)
  and either SSE-S3 or a customer-managed AWS KMS key on Amazon S3 buckets, because these logs expose sensitive network metadata (source and
  destination IPs, domain names, and SNI values).
- You SHOULD scope each log destination's resource policy (the S3 bucket policy, the CloudWatch
  Logs resource policy, and the Amazon Data Firehose delivery-stream policy) with `aws:SourceArn`
  (the firewall's ARN) and `aws:SourceAccount` condition keys, so only this firewall in the
  expected account can write to the destination and another account or service cannot
  (confused-deputy prevention).
- You MUST NOT relax the policy to a global pass to clear a drop; correct the specific cause
  (routing, `HOME_NET`, evaluation order, inspection limits) so traffic stays inspected.
- You SHOULD prefer fixing routing symmetry over disabling stateful inspection when connections fail
  erratically, so inspection is preserved.
- You MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to
  the specific `network-firewall:` actions and resources this task needs, never long-lived access
  keys or broad administrative access, preferring read-only credentials for the diagnostic reads and
  scoping any corrective change to the specific resource.
- You SHOULD enable AWS CloudTrail on the account so firewall, policy, rule group, and
  logging-configuration API changes are recorded for audit and incident review.
- You SHOULD configure CloudWatch alarms to alert on firewall endpoint failures, dropped-packet
  spikes, and sudden drops in processed traffic volume, so inspection problems are detected and
  escalated promptly rather than surfacing only as user-reported outages. You MUST encrypt any
  SNS topic used for these alarm notifications with a customer-managed AWS KMS key and restrict alarm
  notification recipients to authorized operations and security personnel, since alarm messages can
  expose sensitive firewall metadata (endpoint status, traffic patterns, and capacity).

## Additional Resources

- [Troubleshooting AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/troubleshooting.html)
- [Troubleshooting general issues in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/troubleshooting-general-issues.html)
- [Troubleshooting firewall endpoint failures in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/firewall-troubleshooting-endpoint-failures.html)
- [Troubleshooting rules in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/troubleshooting-rules.html)
- [Enhance TLS inspection with SNI session holding in AWS Network Firewall (AWS Security Blog)](https://aws.amazon.com/blogs/security/enhance-tls-inspection-with-sni-session-holding-in-aws-network-firewall/)
- [Considerations when working with TLS inspection configurations in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/tls-inspection-considerations.html)
