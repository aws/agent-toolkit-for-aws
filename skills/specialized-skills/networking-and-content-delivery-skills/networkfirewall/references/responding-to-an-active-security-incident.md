# Responding to an Active Security Incident

## Overview

Domain expertise for blocking a specific indicator immediately on an already-deployed AWS Network
Firewall during an active incident, then confirming the block and removing it cleanly once the
incident closes. Covers adding a narrow, high-priority block rule for an IP, CIDR, or domain to the
existing policy, placing it so it is evaluated before the rules that would otherwise pass the
traffic, confirming the drop from the logs, and recording enough to back the change out.

This is a surgical, reversible change under time pressure, not firewall configuration. The firewall,
its policy, and its rule groups already exist. The goal is to stop the indicator now with the
smallest blast radius, not to redesign the rule set.

Does not cover first-time firewall deployment, full rule authoring, or TLS inspection. Those are
separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region` matching the firewall's Region on
every command.

## Table of Contents

- Overview
- Workflow
- Place the block where it is actually evaluated
- Keep the change narrow and within capacity
- Confirm the block from the logs
- Use AWS-managed threat intelligence where it fits
- Record the change for clean removal
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To block an indicator during an incident end to end, follow the procedure. It reads the existing
policy's rule order, adds a narrow block rule for the indicator at a priority that is evaluated
before the passing rules, confirms the drop from the alert logs, and records the rule so it can be
removed when the incident closes.

## Place the block where it is actually evaluated

A block rule does nothing if a pass rule is evaluated first.

**Constraints:**

- You MUST read the policy's rule order before adding the rule: under action order a pre-existing
  pass rule evaluates before any drop, and in strict order the new rule needs a priority ahead of the
  rule that passes the traffic
- You MUST place the emergency rule at a priority that is evaluated before the passing rule, and
  confirm the order so the block is actually reached

## Keep the change narrow and within capacity

**Constraints:**

- You MUST scope the rule to the specific indicator (the exact IP, CIDR, or domain), not a broad
  range, so the blast radius is the indicator and not the whole policy
- You MUST check the rule group has available capacity before adding; capacity is fixed at creation,
  and hitting the limit mid-incident turns the incident into an outage
- You MUST leave the existing rules intact

## Confirm the block from the logs

**Constraints:**

- You SHOULD pair the block with an alert (a drop rule generates an alert log, or add an
  accompanying alert) so the drops appear in the alert logs
- You SHOULD give the CloudWatch Logs Insights query that confirms the indicator is being dropped, so
  the responder knows the block is effective and whether to escalate

## Use AWS-managed threat intelligence where it fits

**Constraints:**

- You SHOULD surface the AWS-managed Active Threat Defense rule groups for known malicious
  infrastructure, rather than hand-building blocks for infrastructure AWS already tracks
- You MUST match the managed rule group to the policy's rule order (managed rule groups are published
  in order-specific variants), or the reference fails validation. List the available managed rule
  groups with `aws network-firewall list-rule-groups --scope MANAGED --region {region}` and consult
  the current AWS Network Firewall managed rule groups documentation to pick the variant matching the
  policy's rule order

## Record the change for clean removal

**Constraints:**

- You MUST record the rule you added (its signature ID and the indicator) so the emergency change can
  be found later
- You SHOULD offer a removal step once the incident closes, so the emergency rule does not become
  permanent drift that consumes capacity and blocks traffic no one remembers blocking

## Troubleshooting

### The indicator's traffic keeps flowing
A pass rule is evaluated before the new block. Place the block at a priority ahead of it and confirm
the rule order (Place the block where it is actually evaluated).

### Adding the rule fails
The rule group is at its capacity limit. Add the rule to a rule group with headroom, or to a new
high-priority rule group, rather than expanding a full one mid-incident (Keep the change narrow and
within capacity).

### Cannot tell whether the block is working
No alert is being generated for the drop. Pair the block with an alert and query the alert logs
(Confirm the block from the logs).

## Procedure

### Overview

This procedure reads the policy's rule order, adds a narrow block for the indicator at an
evaluated-first priority, confirms the drop from the alert logs, and records the rule for removal.

### Parameters

- **firewall_name** (required): The deployed firewall to act on.
- **indicator** (required): The IP, CIDR, or domain to block.
- **indicator_type** (required): `ip`, `cidr`, or `domain`.
- **rule_group_arn** (optional): An existing rule group with capacity to hold the block, if known.

**Constraints for parameter acquisition:**

- You MUST ask for the firewall name and the indicator upfront
- You MUST confirm the firewall already exists and is `READY` before changing it

### Steps

#### 1. Verify dependencies and read the policy

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to the specific `network-firewall:` actions and resources this task needs, never long-lived access keys or broad administrative access
- You MUST read the firewall's policy and its `RuleOrder`, and identify the rule group that will hold
  the block and its available capacity
- You MUST verify the alert log group is encrypted with a customer-managed AWS KMS key before
  querying it in Step 3, since existing alert logs hold sensitive network metadata (source and
  destination IPs, alert signatures); if not, enable it immediately with `aws logs associate-kms-key
  --log-group-name {log_group} --kms-key-id {kms_key_arn}`

#### 2. Add the narrow block at an evaluated-first priority

**Constraints:**

- You MUST add a rule scoped to the exact indicator, at a priority evaluated before the passing
  rules. For a domain indicator use a domain list block; for an IP or CIDR use a Suricata IP-layer
  drop that blocks on the first packet:

  ```
  drop ip {indicator} any <> any any (msg:"INCIDENT block {indicator}"; sid:{unique_sid}; rev:1;)
  ```

- You MUST NOT modify or remove existing rules
- You MUST retrieve the current rule group with `describe-rule-group` (capturing its
  `RulesSource` and `UpdateToken`), append the new block rule to the existing rules, and
  pass the complete rule set back via `update-rule-group` — this API performs a full replace,
  so omitting existing rules deletes them

#### 3. Confirm the drop from the logs

**Constraints:**

- You SHOULD confirm the indicator is being dropped from the alert logs with a CloudWatch Logs
  Insights query:

  ```
  aws logs start-query --log-group-name {alert_log_group} \
    --start-time $(date -d '1 hour ago' +%s) --end-time $(date +%s) \
    --query-string 'fields @timestamp, event.src_ip, event.dest_ip, event.alert.action, event.alert.signature | filter event.alert.action = "blocked" | sort @timestamp desc | limit 50' \
    --region {region}
  ```

- You SHOULD note that these alert logs contain sensitive network metadata (source and destination
  IPs, alert signatures): the CloudWatch Logs log group must be encrypted with a customer-managed AWS
  KMS key and access restricted to authorized incident responders only

#### 4. Record the change and surface the console link

**Constraints:**

- You MUST record the signature ID and indicator for later removal, and tell the customer how to
  remove the rule when the incident closes
- You MUST present the firewall console link, filling `{region}` and `{firewall_name}`:

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#FirewallDetails:firewallName={firewall_name}
  ```

### Example

#### Example input

```json
{
  "firewall_name": "edge-fw",
  "indicator": "198.51.100.23",
  "indicator_type": "ip"
}
```

#### Example output

```
Policy RuleOrder STRICT_ORDER. Added drop for 198.51.100.23 at priority 1 (sid 900001), existing rules untouched.
Alert logs confirm 198.51.100.23 is being blocked.
Recorded sid 900001 for removal after the incident. Open the console:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#FirewallDetails:firewallName=edge-fw
```

### Troubleshooting

#### Traffic still flowing
A pass rule fired first. Reprioritize the block ahead of it (Step 2).

#### Rule group full
Add the block to a rule group with capacity, not a full one (Step 1).

## Security Considerations

An incident change is made under time pressure, so keep the blast radius and the audit trail tight.

- You MUST scope the block to the exact indicator, not a broad range, so the emergency rule does not
  drop legitimate traffic alongside the threat.
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
- You MUST restrict access to the CloudWatch Logs alert queries that contain the incident's
  sensitive metadata (source and destination IPs, alert signatures) to authorized incident
  responders only.
- You MUST record the rule (signature ID and indicator) and offer a removal step, so the emergency
  rule does not become permanent undocumented drift.
- You MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to
  the specific `network-firewall:` actions and resources this task needs, never long-lived access
  keys or broad administrative access.
- You SHOULD enable AWS CloudTrail on the account so firewall, policy, rule group, and
  logging-configuration API changes are recorded for audit and incident review.
- You SHOULD configure CloudWatch alarms to alert on firewall endpoint failures and spikes in
  blocked or dropped traffic matching the incident indicator, so the emergency block's effect and any
  firewall health problems are detected and escalated promptly. You MUST encrypt any SNS topic
  used for these alarm notifications with a customer-managed AWS KMS key and restrict alarm
  notification recipients to authorized operations and security personnel, since alarm messages can
  expose sensitive firewall metadata (endpoint status, traffic patterns, and capacity).

## Additional Resources

- [Stateful rule groups in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/stateful-rule-groups.html)
- [Evaluation order for stateful rule groups in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/suricata-rule-evaluation-order.html)
- [AWS managed rule groups for AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/aws-managed-rule-groups.html)
- [Logging network traffic from AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/firewall-logging.html)
- [Rule group capacity in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/rule-group-capacity.html)
