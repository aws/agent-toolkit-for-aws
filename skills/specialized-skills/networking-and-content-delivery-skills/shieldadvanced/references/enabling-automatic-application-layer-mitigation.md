# Enabling Automatic Application Layer DDoS Mitigation

## Overview

Domain expertise for turning on AWS Shield Advanced automatic application layer (layer 7) DDoS
mitigation, which lets Shield Advanced create, test, and deploy AWS WAF rules during an attack
instead of an engineer hand-writing rules under pressure. Covers the AWS WAF (v2) web ACL
precondition, the Block versus Count decision, the baseline period that customers do not expect,
the load-bearing `ShieldMitigationRuleGroup` rule group, and the web ACL capacity it consumes.

Does not cover subscribing and protecting resources, health-based detection, SRT setup, event
review, or protection groups; those are separate references. Authoring the AWS WAF web ACL or its
rules is the waf skill.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Shield Advanced control-plane calls run in
`us-east-1`; pass `--region us-east-1` on every command.

## Table of Contents

- Overview
- Workflow
- Precondition: AWS WAF v2 web ACL
- Decision: Block vs Count
- Baseline period before custom rules
- The ShieldMitigationRuleGroup is load-bearing
- Web ACL capacity
- Troubleshooting
- Security considerations
- Procedure
- Additional Resources

## Workflow

To enable automatic application layer mitigation end to end, follow the procedure exactly. See the
Procedure section below.

The procedure covers:

- Confirming the resource is protected and has an AWS WAF (v2) web ACL associated
- Enabling the automatic response in Block or Count mode
- Confirming the Shield rule group was added to the web ACL
- Surfacing the console link to verify the configuration

## Precondition: AWS WAF v2 web ACL

Automatic mitigation works by managing rules inside an AWS WAF (v2) web ACL on the resource.
Without a v2 web ACL, or with an older AWS WAF Classic web ACL, enabling does nothing useful.

**Constraints:**

- You MUST confirm an AWS WAF (v2) web ACL is associated with the resource before enabling
- You MUST NOT attempt to enable automatic mitigation against an AWS WAF Classic web ACL
- You SHOULD point the customer at the waf skill if the web ACL does not exist yet, rather than
  authoring it here

## Decision: Block vs Count

| Mode | Behavior | Use when |
| --- | --- | --- |
| Count | Shield's rules observe and label suspect requests but do not block them | During the baseline period and for initial testing, so legitimate traffic is not blocked |
| Block | Shield's rules drop suspect requests | After the baseline is established and false-positive risk is understood |

**Constraints:**

- You SHOULD start in Count mode during the baseline period, then switch to Block once the customer
  has confirmed legitimate traffic is not caught
- You MUST be able to switch modes without disabling the feature, using the update call

## Always tell the customer (state all of these)

When advising on automatic application layer mitigation — especially when asked why no tailored
custom rules appeared, or before any cleanup — you MUST state ALL of the following points together,
not a subset:

1. Tailored custom rules require a baseline period of roughly **24 to 30 days** of traffic; they are
   not available immediately or during the first attack.
2. Run in **Count mode during the baseline period** (rules observe and label, do not block), then
   switch to Block only after confirming legitimate traffic is not caught.
3. **Do not remove the `ShieldMitigationRuleGroup`** from the web ACL: doing so silently disables
   automatic mitigation for **every resource that shares that web ACL**, with no obvious signal.

The sections below give the detail behind each point.

## Baseline period before custom rules

Customers enable automatic mitigation and expect tailored custom rules during the very next attack.
Shield Advanced needs a baseline period of roughly 24 to 30 days of traffic before it can tailor
rules to the application and test them against historical traffic.

**Constraints:**

- You MUST set the expectation that custom tailored rules are not available immediately; the
  baseline takes roughly 24 to 30 days of traffic
- You SHOULD recommend running in Count mode during the baseline rather than promising custom rules
  from day one

## The ShieldMitigationRuleGroup is load-bearing

When enabled, Shield Advanced adds a managed rule group whose name starts with
`ShieldMitigationRuleGroup` to the web ACL. Removing it during cleanup silently disables automatic
mitigation for every resource that shares that web ACL.

**Constraints:**

- You MUST warn against removing the `ShieldMitigationRuleGroup` rule group from the web ACL; its
  removal turns off automatic mitigation for all resources using that web ACL, with no obvious
  signal
- You MUST NOT add the Shield rule group to a CloudFormation web ACL template; AWS WAF maintains it
  automatically, and managing it in a template fights that
- You SHOULD note one rule group is added per web ACL regardless of how many resources share it
- You SHOULD explain that AWS WAF places and maintains the `ShieldMitigationRuleGroup` automatically;
  the customer does not set its priority, and their own rules continue to evaluate in their existing
  order. Point at the waf skill for authoring or ordering the customer's own rules

## Web ACL capacity

The Shield rule group consumes a fixed amount of the web ACL's capacity, which competes with the
customer's own rules.

**Constraints:**

- You SHOULD account for the web ACL capacity units the Shield rule group consumes when planning
  the web ACL, so the customer's other rules still fit within the web ACL capacity budget
- You SHOULD flag the capacity draw before enabling on a web ACL that is already near its limit

## Troubleshooting

### Enabling does nothing or reports no web ACL
The resource has no AWS WAF (v2) web ACL associated, or it is an AWS WAF Classic web ACL. Associate
a v2 web ACL first (Precondition).

### Automatic mitigation is not deploying custom rules during the first attack
The baseline is not established yet. Custom rules need roughly 24 to 30 days of traffic; run in
Count mode meanwhile (Baseline period before custom rules).

### Automatic mitigation stopped working after a web ACL cleanup
The `ShieldMitigationRuleGroup` rule group was removed. Re-enable the automatic response to restore
it (The ShieldMitigationRuleGroup is load-bearing).

### Legitimate traffic is being blocked
The response is in Block mode and a rule is over-matching. Switch to Count with the update call and
review before returning to Block (Decision: Block vs Count).

## Security considerations

Automatic mitigation manages AWS WAF rules inside the resource's web ACL, so call out the risks and
the controls that contain them.

- **The ShieldMitigationRuleGroup is critical and must not be removed.** Shield Advanced adds a
  managed rule group whose name starts with `ShieldMitigationRuleGroup` to the web ACL; removing it
  during cleanup silently disables automatic mitigation for every resource that shares that web ACL,
  with no obvious signal.
- **Over-broad rules can block legitimate traffic.** Block mode can drop legitimate requests if a
  rule over-matches; start in Count mode during the baseline and switch to Block only after
  confirming legitimate traffic is not caught.
- **Limit web ACL modifications to authorized personnel.** Restrict who can edit the web ACL so the
  Shield rule group is not removed or the mode flipped by unauthorized changes.
- **Least privilege for the operator.** Scope the caller's IAM permissions to the minimum this
  procedure needs (`shield:ListProtections`, `shield:EnableApplicationLayerAutomaticResponse`,
  `shield:UpdateApplicationLayerAutomaticResponse`) rather than broad Shield or administrator access.
- **Audit trail.** Keep AWS CloudTrail enabled and logging `shield:*` calls so every automatic
  response configuration change leaves a record, and confirm the CloudTrail trail uses SSE-KMS
  encryption on its S3 log bucket and CloudWatch Logs log group, since CloudTrail records contain
  sensitive API metadata (caller identities, resource ARNs, parameters).

## Procedure

### Overview

This procedure enables automatic application layer mitigation on a protected resource that already
has an AWS WAF (v2) web ACL, in the chosen mode, then surfaces the console link to verify.

### Parameters

- **resource_arn** (required): The ARN of the protected resource (CloudFront distribution or
  Application Load Balancer) that has an AWS WAF (v2) web ACL associated.
- **action** (required): `Count` (observe) or `Block` (mitigate). Default to `Count` during the
  baseline.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the resource is protected and has a v2 web ACL before enabling

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD use temporary credentials from an assumed IAM role (for example via IAM Identity Center
  or an instance profile) rather than long-lived IAM user access keys for these security-sensitive
  Shield Advanced operations
- You SHOULD scope the caller's IAM permissions to the minimum this procedure needs
  (`shield:ListProtections`, `shield:EnableApplicationLayerAutomaticResponse`,
  `shield:UpdateApplicationLayerAutomaticResponse`) rather than broad Shield or administrator access
- You SHOULD confirm AWS CloudTrail is enabled and logging `shield:*` calls so every Shield Advanced
  configuration change leaves an audit trail
- You SHOULD confirm the CloudTrail trail is configured with SSE-KMS encryption on its S3 log bucket
  and CloudWatch Logs log group, since CloudTrail records contain sensitive API metadata (caller
  identities, resource ARNs, parameters)
- You MUST confirm the resource is protected by Shield Advanced with `aws shield list-protections
  --region us-east-1`
- You MUST confirm an AWS WAF (v2) web ACL is associated with the resource

#### 2. Enable the automatic response

**Constraints:**

- You MUST enable the automatic response with the chosen action:

  ```
  aws shield enable-application-layer-automatic-response \
    --resource-arn {resource_arn} --action '{"{action}":{}}' --region us-east-1
  ```

- You SHOULD use `Count` during the baseline period and switch to `Block` later:

  ```
  aws shield update-application-layer-automatic-response \
    --resource-arn {resource_arn} --action '{"Block":{}}' --region us-east-1
  ```

#### 3. Confirm the Shield rule group was added

**Constraints:**

- You MUST confirm the `ShieldMitigationRuleGroup` rule group is present in the resource's web ACL
- You MUST tell the customer not to remove that rule group during future web ACL edits

#### 4. Surface the console link

**Constraints:**

- You MUST present the Shield protected-resources console link and tell the customer to open the
  resource and confirm the automatic application layer DDoS mitigation status and mode:

  ```
  https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/protections
  ```

### Example

#### Example input

```json
{
  "resource_arn": "arn:aws:elasticloadbalancing:us-east-1:111122223333:loadbalancer/app/my-app-alb/abc",
  "action": "Count"
}
```

#### Example output

```
Enabled automatic application layer mitigation in Count mode on my-app-alb.
Shield added the ShieldMitigationRuleGroup rule group to the web ACL — do not remove it.
Custom tailored rules become available after the ~24-30 day baseline; switch to Block once traffic is validated.
Open the Shield console and confirm the automatic mitigation status:
https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/protections
```

### Troubleshooting

#### Enabling reports no web ACL
Associate an AWS WAF (v2) web ACL with the resource first (Step 1).

#### No custom rules during the first attack
The baseline is not established. Run in Count mode and wait roughly 24 to 30 days (Step 2).

#### Automatic mitigation stopped after a web ACL cleanup
The `ShieldMitigationRuleGroup` was removed. Re-enable the automatic response (Step 2).

## Additional Resources

- [Enabling automatic application layer DDoS mitigation (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-automatic-app-layer-response-config.html)
- [Deciding whether to subscribe to AWS Shield Advanced and apply additional protections (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-advanced-summary-deciding.html)
- [AWS Shield Advanced Update: Automatic Application Layer DDoS Mitigation (AWS News Blog)](https://aws.amazon.com/blogs/aws/aws-shield-advanced-update-automatic-application-layer-ddos-mitigation/)
