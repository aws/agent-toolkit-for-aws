# Filtering Outbound Traffic by Domain Name

## Overview

Domain expertise for controlling which external sites workloads in a VPC can reach, using an AWS
Network Firewall stateful domain list rule group. Covers choosing an action (allow or deny), listing
domains (exact names or wildcard names that start with a dot), selecting whether to inspect HTTP,
HTTPS, or both, and adding the rule group to the firewall policy.

Domain filtering matches on the TLS Server Name Indication (SNI) for HTTPS and the host header for
HTTP. It never does an out-of-band DNS lookup and never matches on the resolved IP. That changes
what the rules can and cannot enforce.

Does not cover firewall deployment and routing, logging, TLS inspection, or the full-URL path
filtering that needs TLS inspection. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Pass `--region` matching the firewall's Region
on every command.

## Table of Contents

- Overview
- Workflow
- Domain rules match the handshake, not the IP
- An allow list silently drops the rest of the protocol
- Do not mix allow with reject or alert under action order
- Override HOME_NET for centralized deployments
- Domain filtering applies only to HTTP and HTTPS
- PQC ClientHello fragmentation can defeat SNI matching
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To filter outbound traffic by domain end to end, follow the procedure. It creates a stateful domain
list rule group with the chosen action, domain targets, and target types (HTTP host, TLS SNI, or
both), then adds the rule group to the firewall policy the firewall enforces.

## Domain rules match the handshake, not the IP

**Constraints:**

- You MUST explain that domain rules match the TLS SNI (HTTPS) or the HTTP host header, not the
  resolved IP address, and that Network Firewall does not do a DNS lookup to match
- You SHOULD pair domain rules with IP-based rules when evasion is a concern, because a client that
  manipulates the SNI or host header can get around a domain rule

## An allow list silently drops the rest of the protocol

**Constraints:**

- You MUST make explicit that an allow action denies all non-matching traffic of the same protocol,
  so an allow list covering HTTPS endpoints but omitting a needed HTTP destination quietly blocks it
- You MUST confirm the protocol scope (HTTP, HTTPS, or both) and the implicit deny with the customer
  before committing the rule group

## Do not mix allow with reject or alert under action order

**Constraints:**

- You MUST NOT combine an allow domain list with a reject or alert domain list in the same policy
  under action order: the implicit drop the allow group adds takes effect before the reject and
  alert rules, so traffic the customer expected to be alerted on is dropped first
- You SHOULD use strict rule ordering when the customer genuinely needs that combination

## Override HOME_NET for centralized deployments

**Constraints:**

- You MUST set the `HOME_NET` variable to include the source ranges when the firewall inspects
  traffic from outside its own VPC; the default `HOME_NET` covers only the inspection VPC's CIDR, so
  domain rules match nothing for spoke-VPC traffic until it is overridden
- You SHOULD set `HOME_NET` at the firewall policy level so it applies to rule groups that do not
  define their own

## Domain filtering applies only to HTTP and HTTPS

Domain filtering reads the HTTP host header or the TLS SNI field. Protocols that carry neither cannot
be filtered by domain at all, and the failure is silent.

**Constraints:**

- You MUST scope domain filtering to HTTP and HTTPS only; SMTP (ports 25 and 587), SFTP, AMQPS,
  MQTT, and other non-HTTP and non-HTTPS protocols carry no host header or SNI, so a domain rule
  cannot match them
- You MUST explain that such traffic is silently passed if no rule matches, or silently dropped if a
  default deny is active, with nothing signalling that domain filtering does not apply
- You SHOULD route the customer to IP-based Suricata rules for domain-like control over non-HTTP
  protocols

## PQC ClientHello fragmentation can defeat SNI matching

A post-quantum (PQC) ClientHello larger than one TCP segment can prevent the firewall from reading
the SNI, so a working allow list silently starts dropping traffic with no configuration change on
the customer's side.

**Constraints:**

- You SHOULD warn that clients negotiating a post-quantum (PQC) key exchange can send an oversized
  ClientHello across multiple TCP segments, so the firewall cannot extract the SNI to match the
  domain rule and the result is a TCP reset or timeout with no alert log (consult the AWS Network
  Firewall TLS inspection documentation or the client runtime's current TLS/PQC documentation for the
  specific key-exchange algorithm names in effect)
- You SHOULD offer the fixes in order: SNI session holding on the firewall (the AWS-native fix that
  holds the connection until the SNI is seen; note this requires TLS inspection),
  then IP-based rules for critical endpoints, then client-side PQC disablement (consult the client
  runtime's current TLS/PQC documentation for the mechanism to disable post-quantum key exchange,
  where the runtime supports it) only where the customer controls the client

## Troubleshooting

### Rules match nothing for traffic from other VPCs
`HOME_NET` covers only the deployment VPC. Override it to include the source ranges (Override HOME_NET).

### A needed destination is blocked
An allow list denies all non-matching traffic of the same protocol. Add the destination, or confirm
the protocol scope (An allow list silently drops the rest of the protocol).

### Alert or reject rules do not fire alongside an allow list
Under action order the allow list's implicit drop runs first. Switch to strict order (Do not mix
allow with reject or alert under action order).

### A client reaches a blocked domain anyway
The client manipulated the SNI or host header. Pair the domain rule with an IP-based rule (Domain
rules match the handshake, not the IP).

### A non-HTTP protocol is not being filtered by domain
SMTP, SFTP, AMQPS, MQTT, and similar protocols carry no host header or SNI. Use IP-based Suricata
rules instead (Domain filtering applies only to HTTP and HTTPS).

### An allow list starts dropping traffic with no rule change
Possibly a PQC ClientHello spanning multiple segments, defeating SNI extraction. Enable SNI session
holding, or fall back to TLS inspection or IP-based rules (PQC ClientHello fragmentation can defeat
SNI matching).

## Procedure

### Overview

This procedure creates a stateful domain list rule group with the chosen action, targets, and target
types, then adds it to the firewall policy.

### Parameters

- **rule_group_name** (required): Name for the domain list rule group.
- **action** (required): `ALLOWLIST` or `DENYLIST`.
- **domains** (required): Domain targets (exact, or wildcard starting with a dot).
- **target_types** (required): `HTTP_HOST`, `TLS_SNI`, or both.
- **capacity** (required): Capacity units for the rule group (immutable after creation).
- **kms_key_id** (required): A customer-managed AWS KMS key to encrypt the rule group at rest.
- **firewall_policy_arn** (required): The policy to add the rule group to.
- **firewall_name** (required): The firewall that uses this policy, for the console link in Step 4.
- **home_net_cidrs** (optional): Source CIDRs to set in `HOME_NET` for a centralized deployment.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the protocol scope and, for an allow list, that the customer understands the
  implicit deny of non-matching same-protocol traffic

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`, and you MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to the specific `network-firewall:` actions and resources this task needs, never long-lived access keys or broad administrative access
- You MUST confirm the firewall policy exists at `firewall_policy_arn`
- You MUST confirm whether the firewall inspects traffic from outside its own VPC, to decide on a
  `HOME_NET` override

#### 2. Create the domain list rule group

**Constraints:**

- You MUST create the stateful domain list rule group with the action, targets, and target types.
  `Targets` and `TargetTypes` are JSON arrays of strings — `Targets` like `["example.com",
  ".amazonaws.com"]` (a leading dot is a wildcard suffix match), `TargetTypes` is `["HTTP_HOST"]`,
  `["TLS_SNI"]`, or both, and `GeneratedRulesType` is `ALLOWLIST` or `DENYLIST`:

  Encrypt the rule group at rest with a customer-managed AWS KMS key via `--encryption-configuration`,
  since it holds the allow/deny logic that governs what traffic is permitted:

  ```
  aws network-firewall create-rule-group --rule-group-name {rule_group_name} \
    --type STATEFUL --capacity {capacity} \
    --rule-group '{"RulesSource":{"RulesSourceList":{"Targets":["example.com",".amazonaws.com"],"TargetTypes":["HTTP_HOST","TLS_SNI"],"GeneratedRulesType":"ALLOWLIST"}}}' \
    --encryption-configuration Type=CUSTOMER_KMS,KeyId={kms_key_id} \
    --region {region}
  ```

#### 3. Set the default action, HOME_NET, and rule group reference in one call

**Constraints:**

- You MUST first retrieve the current policy with `describe-firewall-policy`, then include all
  existing fields (for example `StatefulRuleGroupReferences`, `StatefulDefaultActions`,
  `StatefulEngineOptions`, `StatelessRuleGroupReferences`) in the `--firewall-policy` JSON, merging in
  only the new `StatefulDefaultActions`, `StatefulRuleGroupReferences`, and `PolicyVariables` fields.
  The response also returns the `{update_token}` the update call requires. `update-firewall-policy`
  replaces the entire policy object rather than merging, so omitting a field deletes it and can drop
  all stateful rules and cause an outage:

  ```
  aws network-firewall describe-firewall-policy \
    --firewall-policy-arn {firewall_policy_arn} --region {region}
  ```

- You MUST, for an allow list, set the `aws:drop_established` stateful default action, the `HOME_NET`
  override (for a centralized deployment), and the rule group reference in a single
  `update-firewall-policy` call on that complete merged policy, carrying every existing field through
  unchanged, so the policy never holds a drop-all default with no rule group attached:

  ```
  aws network-firewall update-firewall-policy \
    --firewall-policy-arn {firewall_policy_arn} \
    --update-token {update_token} \
    --firewall-policy '{"StatelessDefaultActions":["aws:forward_to_sfe"],"StatelessFragmentDefaultActions":["aws:forward_to_sfe"],"StatefulDefaultActions":["aws:drop_established"],"StatefulRuleGroupReferences":[{"ResourceArn":"{rule_group_arn}","Priority":1}],"PolicyVariables":{"RuleVariables":{"HOME_NET":{"Definition":[{home_net_cidrs}]}}}}' \
    --region {region}
  ```

- You MUST, for a centralized deployment, override `HOME_NET` in the firewall policy to include the
  spoke source CIDRs

#### 4. Confirm the rule group is attached

**Constraints:**

- You MUST verify the rule group reference and the `aws:drop_established` default action are present
  on the policy with `aws network-firewall describe-firewall-policy --firewall-policy-arn {firewall_policy_arn} --region {region}`
- You SHOULD avoid mixing allow with reject or alert domain lists under action order; use strict
  order if both are needed

#### 5. Confirm and surface the console link

**Constraints:**

- You MUST confirm the rule group is attached and traffic is filtered as expected
- You MUST present the firewall console link, filling `{region}` and `{firewall_name}`:

  ```
  https://{region}.console.aws.amazon.com/vpcconsole/home?region={region}#FirewallDetails:firewallName={firewall_name}
  ```

### Example

#### Example input

```json
{
  "rule_group_name": "allowed-domains",
  "action": "ALLOWLIST",
  "domains": [".amazonaws.com", "updates.example.com"],
  "target_types": ["HTTP_HOST", "TLS_SNI"],
  "capacity": 100,
  "kms_key_id": "arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab",
  "firewall_policy_arn": "arn:aws:network-firewall:us-east-1:111122223333:firewall-policy/egress-policy",
  "firewall_name": "egress-fw"
}
```

#### Example output

```
Created allow-list rule group allowed-domains (HTTP_HOST + TLS_SNI).
Set policy stateful default action to aws:drop_established so non-matching traffic is dropped.
Added the rule group to egress-policy at priority 1.
Open the console and confirm the firewall:
https://us-east-1.console.aws.amazon.com/vpcconsole/home?region=us-east-1#FirewallDetails:firewallName=egress-fw
```

### Troubleshooting

#### Spoke-VPC traffic not matching
Override `HOME_NET` to include the source ranges (Step 3).

#### A needed HTTP destination is blocked by an HTTPS allow list
Add the destination and confirm the protocol scope (Step 1).

## Security Considerations

Domain filtering matches the handshake, so it controls but does not fully prove what a workload
reaches.

- You MUST configure an allow list with `aws:drop_established` as the stateful default action rather
  than a deny list, so any destination not explicitly permitted is blocked rather than passed;
  fail-closed is a fundamental security control for a network firewall, not an option.
- You MUST encrypt the rule group itself at rest with a customer-managed AWS KMS key (via
  `--encryption-configuration` on `create-rule-group`), consistent with how the firewall resource is
  encrypted, since the rule group holds the domain allow/deny logic that governs what traffic is permitted.
- You SHOULD pair domain rules with IP-based Suricata rules when evasion is a concern, since a client
  that manipulates the SNI or host header can bypass a domain-only rule, and route non-HTTP and
  non-HTTPS protocols to IP-based rules since they carry no SNI or host header to match.
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
- You MUST use ephemeral, least-privilege credentials (a time-bound assumed-role session) scoped to
  the specific `network-firewall:` actions and resources this task needs, never long-lived access
  keys or broad administrative access.
- You SHOULD enable AWS CloudTrail on the account so firewall, policy, rule group, and
  logging-configuration API changes are recorded for audit and incident review.
- You SHOULD configure CloudWatch alarms to alert on firewall endpoint failures, rule group capacity
  warnings, and spikes in blocked-domain or dropped traffic, so issues are detected and escalated
  promptly. You MUST encrypt any SNS topic used for these alarm notifications with a
  customer-managed AWS KMS key and restrict alarm notification recipients to authorized operations and
  security personnel, since alarm messages can expose sensitive firewall metadata (endpoint status,
  traffic patterns, and capacity).

## Additional Resources

- [Stateful domain list rule groups in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/stateful-rule-groups-domain-names.html)
- [Options for stateful rules in Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/stateful-rule-group-options.html)
- [Enhance TLS inspection with SNI session holding in AWS Network Firewall (AWS Security Blog)](https://aws.amazon.com/blogs/security/enhance-tls-inspection-with-sni-session-holding-in-aws-network-firewall/)
- [Considerations when working with TLS inspection configurations in AWS Network Firewall (AWS Network Firewall Developer Guide)](https://docs.aws.amazon.com/network-firewall/latest/developerguide/tls-inspection-considerations.html)
