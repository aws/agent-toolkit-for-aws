# Stripping Inbound x-amzn-waf-* Headers Before Trusting Them

## Overview

Domain expertise for the mandatory safety companion to any AWS WAF header forwarding: a block rule
that rejects inbound requests already carrying an `x-amzn-waf-*` header, so an attacker cannot
forge the signal the origin trusts. Covers why the gap exists (AWS WAF does not strip pre-existing
`x-amzn-waf-*` headers before inserting its own) and the rule placement.

Does not cover the forwarding workflows themselves; this is their required companion. The
confidence-signal, interpolation, and client-IP references all point here.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Why the spoofing gap exists
- A mandatory companion, not optional hardening
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To add the inbound-header-stripping rule end to end, follow the procedure exactly. See the
Procedure section below.

The procedure covers:

- Adding a block rule matching any inbound `x-amzn-waf-*` header
- Placing it before the forwarding rules
- Confirming and surfacing the console link

## Why the spoofing gap exists

AWS WAF custom request handling does not strip a pre-existing `x-amzn-waf-*` header before inserting
its own. A request that arrives already carrying one passes that forged value to the origin, so an
origin trusting `x-amzn-waf-bot-category:verified`, a spoofed confidence value, or a spoofed client
IP is bypassable.

**Constraints:**

- You MUST add a block rule that rejects any inbound request already carrying an `x-amzn-waf-*`
  header
- You MUST place that rule at a lower priority number than the forwarding rules, so it runs first
  and only AWS-WAF-set values reach the origin

## A mandatory companion, not optional hardening

The vulnerability is the absence of a rule, not a misconfiguration that throws an error, so it is
easy to ship header forwarding without it.

**Constraints:**

- You MUST treat this rule as a mandatory companion whenever the skill recommends header forwarding,
  not an optional hardening step
- You SHOULD confirm the stripping rule is present before declaring any forwarding workflow complete

## Troubleshooting

### The origin trusts a forged signal
No stripping rule is present, or it runs after the forwarding rules. Add it before them (Why the
spoofing gap exists).

### Legitimate requests are blocked by the strip rule
A legitimate upstream is setting an `x-amzn-waf-*` header. That is unusual; confirm the upstream and
narrow the match if a specific known header must pass, but default to blocking all inbound
`x-amzn-waf-*`.

## Procedure

### Overview

This procedure adds a block rule for inbound `x-amzn-waf-*` headers before the forwarding rules,
then surfaces the console link.

### Parameters

- **web_acl_name**, **web_acl_id**, **scope** (required): Identify the web ACL.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm which forwarding rules exist so the strip rule is placed before them

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST identify the priority numbers of the forwarding rules

#### 2. Add the inbound strip rule

**Constraints:**

- You MUST add a block rule matching any request that carries an `x-amzn-waf-*` header (a header
  match on the `x-amzn-waf-` prefix), at a lower priority number than the forwarding rules
- You MUST fetch the current `LockToken` before `update-web-acl` and pass the full rule set
- You MUST preserve the web ACL's existing `DefaultAction` from the `get-web-acl` response and pass
  it back as `{default_action}`; do not assume `Allow={}`, since that would silently open all
  unmatched traffic on a web ACL whose default action is `Block`. For example, a Block rule whose
  `ByteMatchStatement` matches the `x-amzn-waf-` prefix on header keys:

  ```
  aws wafv2 get-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} --region {region}
  aws wafv2 update-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} \
    --lock-token {lock_token} --default-action {default_action} \
    --rules '[{"Name":"StripInboundWafHeaders","Priority":0,"Action":{"Block":{}},"Statement":{"ByteMatchStatement":{"SearchString":"x-amzn-waf-","PositionalConstraint":"STARTS_WITH","FieldToMatch":{"Headers":{"MatchPattern":{"All":{}},"MatchScope":"KEY","OversizeHandling":"MATCH"}},"TextTransformations":[{"Priority":0,"Type":"LOWERCASE"}]}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"StripInboundWafHeaders"}}]' \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName={web_acl_name} \
    --region {region}
  ```

#### 3. Confirm and surface the console link

**Constraints:**

- You MUST confirm the strip rule runs before the forwarding rules
- You MUST present the web ACL console link and tell the customer to confirm the rule order:

  ```
  https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region={region}
  ```

### Example

#### Example input

```json
{
  "web_acl_name": "example-webacl",
  "web_acl_id": "abc",
  "scope": "REGIONAL"
}
```

#### Example output

```
Added a Block rule rejecting any inbound request carrying an x-amzn-waf-* header, at priority 0 (before the forwarding rules).
Open the web ACL and confirm the strip rule runs first:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### The origin trusts a forged value
The strip rule is missing or runs after the forwarding rules. Place it before them (Step 2).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.
- **Header-spoofing risk.** Any `x-amzn-waf-*` signal forwarded to the origin can be forged inbound. You MUST add the inbound-header-stripping rule whenever a signal or client IP is forwarded (see stripping-inbound-waf-headers-before-trusting-them); without it the origin trusts a spoofable value.

## Additional Resources

- [Customizing web requests and responses in AWS WAF (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-custom-request-response.html)
- [How to use AWS WAF Bot Control for targeted bots signals and mitigate evasive bots with adaptive user experience (AWS Networking & Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/how-to-use-aws-waf-bot-control-for-targeted-bots-signals-and-mitigate-evasive-bots-with-adaptive-user-experience/)
