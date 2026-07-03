# Turning Bot Control Labels into a Confidence Signal

## Overview

Domain expertise for collapsing the many Bot Control Targeted labels into a single
application-facing confidence signal. Covers overriding the Targeted rules to the non-terminating
Challenge action, mapping many `TGT_*` labels into one `x-amzn-waf-bot-confidence` header with
label-match rules, defining the mapping in the web ACL so the application contract stays fixed, and
the mandatory inbound-header-stripping companion.

Does not cover turning Bot Control on (that is the protecting-against-bots reference), forwarding a
whole namespace with interpolation (its own reference), or the application's response (the adaptive
mitigation reference).

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Override Targeted rules to Challenge
- Collapse labels into one confidence header
- Define the mapping in the web ACL
- Strip inbound headers
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To turn Bot Control labels into a confidence signal end to end, follow the procedure exactly. See
the Procedure section below.

The procedure covers:

- Overriding the Targeted rules to Challenge so evaluation continues
- Mapping label groups to low, medium, and high with OR label-match rules
- Forwarding one `x-amzn-waf-bot-confidence` header to the origin
- Adding the inbound-header-stripping rule

## Override Targeted rules to Challenge

Block or CAPTCHA terminate evaluation, so later rules that forward the signal never run. Challenge
is non-terminating with a valid token.

**Constraints:**

- You MUST override the Targeted rules to Challenge when the goal is to forward a signal rather than
  block at the edge, so AWS WAF keeps evaluating later rules
- You MUST NOT use a terminating action (Block, CAPTCHA) on the rules whose labels feed the signal

## Collapse labels into one confidence header

Targeted produces hundreds of `TGT_*` labels. The application cannot act on all of them, so map
groups of labels to a small set of confidence levels.

**Constraints:**

- You MUST collapse the labels into a single confidence signal (low, medium, high) using OR
  label-match rules, rather than exposing raw labels to the application
- You MUST place the label-match rules at a higher priority number than the Bot Control group, so
  the labels exist when the matches run

## Define the mapping in the web ACL

If the application keys on specific label names, it has to change whenever AWS adds or renames a
label. Defining the mapping in the web ACL keeps the application contract fixed.

**Constraints:**

- You MUST define the label-to-confidence mapping inside the web ACL and forward one stable header
  (`x-amzn-waf-bot-confidence`), so the application contract does not change as labels evolve

## Strip inbound headers

The confidence header is an `x-amzn-waf-*` header, which an attacker can set inbound unless it is
stripped first.

**Constraints:**

- You MUST pair this workflow with the inbound-header-stripping rule (see
  stripping-inbound-waf-headers-before-trusting-them), placed before the forwarding rules, so the
  signal cannot be forged
- You MUST forward `x-amzn-waf-bot-confidence` only to an HTTPS-only origin and SHOULD have the
  application set HSTS, so the confidence signal is not exposed in cleartext. You SHOULD use
  AWS Certificate Manager (ACM) to provision and manage the origin's TLS certificate (for example on
  an Application Load Balancer), so the certificate is validated and automatically renewed

## Troubleshooting

### The forwarding rule never runs
A terminating action on an earlier rule stopped evaluation. Override the Targeted rules to Challenge
(Override Targeted rules to Challenge).

### The label-match rules do not see the labels
They are at a lower priority number than the Bot Control group. Move them after it (Collapse labels
into one confidence header).

### The application receives a spoofed confidence value
No inbound stripping rule is in place. Add it before the forwarding rules (Strip inbound headers).

## Procedure

### Overview

This procedure overrides the Targeted rules to Challenge, maps labels to a confidence header,
strips spoofed inbound headers, and surfaces the console link.

### Parameters

- **web_acl_name**, **web_acl_id**, **scope** (required): Identify the web ACL.
- **confidence_mapping** (required): Which label groups map to low, medium, and high.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm Bot Control Targeted is already enabled (see the protecting-against-bots
  reference)

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm Bot Control Targeted is enabled and producing labels

#### 2. Override Targeted rules to Challenge

**Constraints:**

- You MUST override the Targeted rules to Challenge so evaluation continues to the forwarding rules
- You MUST fetch the current `LockToken` before `update-web-acl` and pass the full rule set
- You MUST preserve the web ACL's existing `DefaultAction` from the `get-web-acl` response and pass
  it back as `{default_action}`; do not assume `Allow={}`, since that would silently open all
  unmatched traffic on a web ACL whose default action is `Block`. For example, the Bot Control group
  with `RuleActionOverrides` setting Targeted rules to Challenge:

  ```
  aws wafv2 get-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} --region {region}
  aws wafv2 update-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} \
    --lock-token {lock_token} --default-action {default_action} \
    --rules '[{"Name":"AWS-BotControl","Priority":1,"Statement":{"ManagedRuleGroupStatement":{"VendorName":"AWS","Name":"AWSManagedRulesBotControlRuleSet","ManagedRuleGroupConfigs":[{"AWSManagedRulesBotControlRuleSet":{"InspectionLevel":"TARGETED"}}],"RuleActionOverrides":[{"Name":"TGT_VolumetricSession","ActionToUse":{"Challenge":{}}}]}},"OverrideAction":{"None":{}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"AWS-BotControl"}}]' \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName={web_acl_name} \
    --region {region}
  ```

#### 3. Map labels to a confidence header

**Constraints:**

- You MUST add OR label-match rules that map label groups to low, medium, and high, at a higher
  priority number than the Bot Control group
- You MUST forward one `x-amzn-waf-bot-confidence` header via custom request handling. For example,
  a Count rule that matches a label group and inserts the header (insert this rule with a fresh
  `LockToken` alongside the rest of the rule set):

  ```
  --rules '[{"Name":"ConfidenceHigh","Priority":10,"Action":{"Count":{"CustomRequestHandling":{"InsertHeaders":[{"Name":"x-amzn-waf-bot-confidence","Value":"high"}]}}},"Statement":{"LabelMatchStatement":{"Scope":"LABEL","Key":"awswaf:managed:aws:bot-control:targeted:aggregate:volumetric:session:maximum"}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"ConfidenceHigh"}}]'
  ```

#### 4. Strip inbound headers and surface the console link

**Constraints:**

- You MUST add the inbound `x-amzn-waf-*` stripping rule before the forwarding rules
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
  "scope": "REGIONAL",
  "confidence_mapping": {"low": ["TGT_VolumetricSession"], "high": ["TGT_VolumetricSessionMaximum"]}
}
```

#### Example output

```
Overrode Targeted rules to Challenge so evaluation continues.
Mapped label groups to x-amzn-waf-bot-confidence (low/medium/high) and added an inbound strip rule first.
Open the web ACL and confirm the rule order:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### The forwarding rule never runs
An earlier terminating action stopped evaluation. Use Challenge (Step 2).

#### Labels are not visible to the match rules
Priority order is wrong. Move the label-match rules after the Bot Control group (Step 3).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.
- **Header-spoofing risk.** Any `x-amzn-waf-*` signal forwarded to the origin can be forged inbound. You MUST add the inbound-header-stripping rule whenever a signal or client IP is forwarded (see stripping-inbound-waf-headers-before-trusting-them); without it the origin trusts a spoofable value.
- **Encrypted transport.** You MUST forward the signal only to an HTTPS-only origin and the application MUST validate the origin's TLS certificate, so the signal is not exposed in cleartext. You SHOULD use AWS Certificate Manager (ACM) to provision and manage the origin's TLS certificate (for example on an Application Load Balancer), so the certificate is validated and automatically renewed.
- **Defense in depth.** You SHOULD treat the forwarded signal as one input among several, not a sole gate; over-relying on a single signal without defense in depth leaves the application exposed if the signal is evaded or degraded.

## Additional Resources

- [AWS WAF label match rule statement (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-label-match-statement.html)
- [AWS WAF rule action (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-action.html)
- [Customizing web requests and responses in AWS WAF (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-custom-request-response.html)
- [How to use AWS WAF Bot Control for targeted bots signals and mitigate evasive bots with adaptive user experience (AWS Networking & Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/how-to-use-aws-waf-bot-control-for-targeted-bots-signals-and-mitigate-evasive-bots-with-adaptive-user-experience/)
