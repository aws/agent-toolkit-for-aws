# Writing and Troubleshooting Stateful Suricata Rules

## Overview

Domain expertise for writing custom stateful intrusion prevention and detection rules in AWS Network
Firewall and fixing rules that do not act on the traffic they target. Covers choosing the rule order
for the rule group and the policy, writing Suricata-compatible rules with the required keywords and a
unique signature ID, the Suricata engine constraints the Network Firewall engine enforces, and localizing
why a rule does not match.

A stateful rule that looks correct can silently do nothing. The most common reasons are a missing
`flow` keyword (which turns the rule into a once-per-flow IP-only match), a rule order mismatch
between the rule group and the policy, a duplicate or missing signature ID, and a lower-layer rule
acting before the application-layer rule the customer intended.

Does not cover firewall deployment and routing, domain list rule groups, logging setup, or TLS
inspection. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region` matching the firewall's Region on
every command.

## Table of Contents

- Overview
- Workflow
- Set the rule order before writing rules
- Every stateful rule needs a flow keyword
- Required options and a unique SID
- Suricata engine constraints the engine enforces
- Layer 4 rules can act before Layer 7 rules
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To write and troubleshoot stateful rules end to end, follow the procedure. It sets the rule order on
the rule group and the policy first, writes Suricata rules with the required keywords and unique
signature IDs under the Suricata engine constraints, attaches the rule group to the policy, and reads the
alert logs to confirm each rule fired on the traffic it targets.

## Set the rule order before writing rules

Rule order is decided on both the rule group and the policy, the two must match, and the choice is
immutable once set. It changes how every rule in the group is evaluated.

**Constraints:**

- You MUST establish the rule order before writing rules and set it consistently on the rule group
  and the policy: `STRICT_ORDER` (recommended, rules evaluate by priority then definition order) or
  `DEFAULT_ACTION_ORDER` (legacy, all pass rules before drop before alert)
- You MUST explain that under action order the `priority` keyword inside a rule is ignored, so a rule
  placed last can fire first
- You MUST state that the rule order is immutable on both the rule group and the policy; changing it
  means creating new resources

## Every stateful rule needs a flow keyword

**Constraints:**

- You MUST add a `flow` keyword with a direction (for example `flow:to_server,established`) to a
  TCP or UDP stateful rule; without it Network Firewall treats the rule as IP-only and evaluates it
  on the first packet of the flow rather than across the established connection
- You MUST treat a rule that "matches nothing" or "matches only sometimes" as a missing or wrong
  `flow` keyword until that is ruled out

## Required options and a unique SID

**Constraints:**

- You MUST include `msg`, `sid`, and `rev` on every rule; the rule group fails validation without
  them
- You MUST give every rule a unique `sid`; a duplicate signature ID causes a later rule to override
  an earlier one or fails validation, and the error does not point at the duplicate

## Suricata engine constraints the engine enforces

The Network Firewall engine runs Suricata with constraints that rules written for other Suricata
deployments do not assume.

**Constraints:**

- You MUST use PCRE2 syntax for the `pcre` keyword, and place `pcre` next to an anchoring buffer
  (`content`, `tls.sni`, `http.host`, or `dns.query`); a bare `pcre` is rejected
- You MUST place a sticky buffer (for example `http.uri`) immediately before the payload keywords it
  applies to
- You SHOULD keep each rule within the per-rule length limit measured after variable expansion, and
  add `http2` protocol rules alongside `http` rules when inspecting decrypted HTTP/2

## Layer 4 rules can act before Layer 7 rules

**Constraints:**

- You MUST check the rule's layer when a Layer 7 rule (for example on `http`) does not act: a blanket
  Layer 4 rule (on `tcp`) can match the connection before the engine detects the application
  protocol
- You MUST add `flow:to_server` to the lower-layer rule so it waits for the application protocol, and
  order the rules so the specific rule is reached

## Troubleshooting

### Rule matches nothing
Usually a missing `flow` keyword (the rule is treated as IP-only) or a rule order that evaluates a
pass rule first. Add the `flow` direction and confirm the rule order (Every stateful rule needs a
flow keyword, Set the rule order before writing rules).

### Rule group fails validation
A required option (`msg`, `sid`, `rev`) is missing or a `sid` is duplicated. Add the options and make
each `sid` unique (Required options and a unique SID).

### A rule that works elsewhere is rejected here
A Suricata engine constraint: PCRE2 syntax, `pcre` not next to an anchoring buffer, or a misplaced sticky
buffer. Adjust to the engine's constraints (Suricata engine constraints the engine enforces).

### A Layer 7 rule never fires
A Layer 4 rule acted on the connection first. Add `flow:to_server` and order the specific rule ahead
(Layer 4 rules can act before Layer 7 rules).

## Procedure

### Overview

This procedure sets the rule order on the rule group and the policy, writes Suricata rules with the
required keywords and unique signature IDs under the Suricata engine constraints, attaches the rule group,
and confirms each rule fires from the alert logs.

### Parameters

- **rule_group_name** (required): Name for the stateful rule group.
- **rule_order** (required): `STRICT_ORDER` or `DEFAULT_ACTION_ORDER`; must match the policy.
- **capacity** (required): Capacity units for the rule group (immutable after creation).
- **rules** (required): The Suricata rules to add.
- **kms_key_id** (required): A customer-managed AWS KMS key to encrypt the rule group at rest.
- **firewall_policy_arn** (required): The policy to attach the rule group to.
- **firewall_name** (required): The firewall that uses this policy, for the console link in Step 4.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the rule order matches the policy before creating the rule group

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to the specific `network-firewall:` actions and resources this task needs, never long-lived access keys or broad administrative access
- You MUST confirm the firewall policy exists and read its `RuleOrder` so the rule group matches it

#### 2. Write the rules under the constraints

**Constraints:**

- You MUST add a `flow` direction, a `msg`, a unique `sid`, and a `rev` to each rule
- You MUST apply the Suricata engine constraints (PCRE2, `pcre` next to an anchoring buffer, sticky
  buffers immediately before their payload keywords)

#### 3. Create the rule group

**Constraints:**

- You MUST create the stateful rule group with the matching rule order, and encrypt the rule group at
  rest with a customer-managed AWS KMS key via `--encryption-configuration` (the rule group holds the
  rule logic that governs what traffic is allowed):

  ```
  aws network-firewall create-rule-group --rule-group-name {rule_group_name} \
    --type STATEFUL --capacity {capacity} \
    --rule-group '{"RulesSource":{"RulesString":"{rules}"},"StatefulRuleOptions":{"RuleOrder":"{rule_order}"}}' \
    --encryption-configuration Type=CUSTOMER_KMS,KeyId={kms_key_id} \
    --region {region}
  ```

#### 4. Attach the rule group and confirm it fires

**Constraints:**

- You MUST reference the rule group from the policy with a priority that matches the intended
  evaluation order
- You SHOULD add an `alert` variant or enable logging and confirm from the alert logs that each rule
  fires on the traffic it targets

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST confirm the rules act as intended from the logs or a test connection
- You MUST present the firewall console link, filling `{region}` and `{firewall_name}`:

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#FirewallDetails:firewallName={firewall_name}
  ```

### Example

#### Example input

```json
{
  "rule_group_name": "egress-ips-rules",
  "rule_order": "STRICT_ORDER",
  "capacity": 200,
  "rules": "drop tcp $HOME_NET any -> $EXTERNAL_NET 22 (msg:\"Block outbound SSH\"; flow:to_server,established; sid:1000001; rev:1;)",
  "kms_key_id": "arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab",
  "firewall_policy_arn": "arn:aws:network-firewall:us-east-1:111122223333:firewall-policy/egress-policy",
  "firewall_name": "egress-fw"
}
```

#### Example output

```
Confirmed policy RuleOrder STRICT_ORDER; created egress-ips-rules to match.
Each rule has a flow direction, a unique sid, msg, and rev.
Attached at priority 1. Alert logs confirm the SSH block fires on outbound 22.
Open the console and confirm the firewall:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#FirewallDetails:firewallName=egress-fw
```

### Troubleshooting

#### Rule does not act
Missing `flow` keyword or a rule order mismatch. Add the `flow` direction and match the order (Step 2,
Step 1).

#### Validation fails
A required option is missing or a `sid` is duplicated. Fix the options (Step 2).

#### A Layer 7 rule is bypassed
A Layer 4 rule fired first. Add `flow:to_server` and reorder (Step 2).

## Security Considerations

A stateful rule that silently does nothing is a security gap, so confirm rules act, not just that
they validate.

- You MUST use `STRICT_ORDER` with explicit `aws:drop_established` and `aws:alert_established`
  default actions, so traffic that matches no rule is dropped (fail-closed) rather than passed;
  fail-closed is a fundamental security control for a network firewall, not an option.
- You MUST confirm each rule actually fires on its target traffic from the alert logs; a missing
  `flow` keyword or an order or layer issue can leave a block rule inert while the policy looks
  correct.
- You MUST encrypt the rule group itself at rest with a customer-managed AWS KMS key (via
  `--encryption-configuration` on `create-rule-group`), consistent with encrypting the firewall
  resource at creation, since the rule group holds the rule logic that governs what traffic is allowed.
- You MUST encrypt every destination that receives firewall logs (alert, flow, or TLS), using a
  customer-managed AWS KMS key on Amazon CloudWatch Logs log groups (`aws logs associate-kms-key`)
  and either SSE-S3 or a customer-managed AWS KMS key on Amazon S3 buckets, because these logs expose sensitive network metadata (source and
  destination IPs, domain names, and SNI values).
- You SHOULD scope each log destination's resource policy (the S3 bucket policy, the CloudWatch
  Logs resource policy, and the Amazon Data Firehose delivery-stream policy) with `aws:SourceArn`
  (the firewall's ARN) and `aws:SourceAccount` condition keys, so only this firewall in the
  expected account can write to the destination and another account or service cannot
  (confused-deputy prevention).
- You SHOULD keep rule content with sensitive indicators (internal CIDRs, threat intelligence) out
  of shared or version-controlled text in the clear, and reference IP sets or AWS Systems Manager
  Parameter Store values encrypted at rest instead.
- You MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to
  the specific `network-firewall:` actions and resources this task needs, never long-lived access
  keys or broad administrative access.
- You SHOULD enable AWS CloudTrail on the account so firewall, policy, rule group, and
  logging-configuration API changes are recorded for audit and incident review.
- You SHOULD configure CloudWatch alarms to alert on firewall endpoint failures, rule group capacity
  warnings, and anomalies in alert or dropped-packet volume after a rule change, so issues are
  detected and escalated promptly. You MUST encrypt any SNS topic used for these alarm
  notifications with a customer-managed AWS KMS key and restrict alarm notification recipients to
  authorized operations and security personnel, since alarm messages can expose sensitive firewall
  metadata (endpoint status, traffic patterns, and capacity).

## Additional Resources

- [Stateful rule groups in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/stateful-rule-groups.html)
- [Suricata compatibility in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/suricata-compatibility.html)
- [Evaluation order for stateful rule groups in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/suricata-rule-evaluation-order.html)
- [Examples of stateful rules for AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/stateful-rule-examples.html)
- [Troubleshooting rules in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/troubleshooting-rules.html)
