# Forwarding Signals with Dynamic Label Interpolation

## Overview

Domain expertise for forwarding AWS WAF signals to the origin with a single rule using dynamic label
interpolation, instead of one custom rule per label. Covers the `${namespace:}` placeholder syntax
that resolves at evaluation time, the synthetic values for client IP and TLS fingerprints, the
10-placeholder-per-string limit and the fully-qualified-namespace rule, and the mandatory
inbound-header-stripping companion.

Does not cover turning Bot Control on, collapsing labels into a confidence signal (its own
reference), or the application's response. Those are separate references.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- One rule forwards a whole namespace
- Synthetic values
- Limits and the fully-qualified-namespace rule
- Strip inbound headers
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To forward signals with interpolation end to end, follow the procedure exactly. See the Procedure
section below.

The procedure covers:

- Adding one custom-header rule that interpolates a label namespace
- Adding synthetic values (client IP, TLS fingerprints, request ID) where wanted
- Staying within the placeholder limit and namespace rules
- Adding the inbound-header-stripping rule

## One rule forwards a whole namespace

The one-rule-per-label approach is unmaintainable; every new managed label means another web ACL
edit. Interpolation forwards an entire namespace in a single custom header.

**Constraints:**

- You MUST use the `${namespace:}` placeholder, which resolves at evaluation time, to forward a
  whole namespace in one rule rather than adding a rule per label
- You SHOULD note a single label resolves to a terminal value, multiple labels to a comma-separated
  list, and no match to an empty string

## Synthetic values

Interpolation exposes values that resolve from request context, not the label store, so the
customer does not have to reconstruct them downstream.

**Constraints:**

- You SHOULD forward `${awswaf:ip:}` (client IP), `${awswaf:ja3:}` and `${awswaf:ja4:}` (TLS
  fingerprints), and `${awswaf:request_id:}` through interpolation when the origin needs them,
  rather than parsing them by hand

## Limits and the fully-qualified-namespace rule

Two traps cause interpolation to not resolve as expected.

**Constraints:**

- You MUST keep to at most 10 placeholders per string value
- You MUST use the fully qualified namespace in interpolation for custom labels, even though
  label-match statements accept the short name

## Strip inbound headers

The forwarded values arrive as `x-amzn-waf-*` headers, which an attacker can set inbound unless
they are stripped first.

**Constraints:**

- You MUST pair this workflow with the inbound-header-stripping rule (see
  stripping-inbound-waf-headers-before-trusting-them), placed before the forwarding rule
- You MUST forward the `x-amzn-waf-*` signals only to an HTTPS-only origin, and the application MUST
  validate the origin's TLS certificate, so the signals are not exposed in cleartext. You SHOULD use
  AWS Certificate Manager (ACM) to provision and manage the origin's TLS certificate (for example on
  an Application Load Balancer), so the certificate is validated and automatically renewed

## Troubleshooting

### A custom label does not resolve in interpolation
The short name was used. Use the fully qualified namespace (Limits and the fully-qualified-namespace
rule).

### A header value is truncated or missing placeholders
The string exceeds 10 placeholders. Split the forwarding across values (Limits and the
fully-qualified-namespace rule).

### The origin receives a spoofed forwarded value
No inbound stripping rule is in place. Add it before the forwarding rule (Strip inbound headers).

## Procedure

### Overview

This procedure adds an interpolation-based forwarding rule, strips spoofed inbound headers, and
surfaces the console link.

### Parameters

- **web_acl_name**, **web_acl_id**, **scope** (required): Identify the web ACL.
- **namespace** (required): The label namespace to forward.
- **synthetic_values** (optional): Which of client IP, JA3, JA4, request ID to include.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the labeling rules that produce the namespace run before the forwarding rule

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm the labels to forward are actually being produced by an earlier rule or group

#### 2. Add the interpolation forwarding rule

**Constraints:**

- You MUST add a custom-header rule that interpolates the namespace with `${namespace:}`, staying
  within 10 placeholders per string and using the fully qualified namespace for custom labels
- You MUST fetch the current `LockToken` before `update-web-acl` and pass the full rule set
- You MUST preserve the web ACL's existing `DefaultAction` from the `get-web-acl` response and pass
  it back as `{default_action}`; do not assume `Allow={}`, since that would silently open all
  unmatched traffic on a web ACL whose default action is `Block`. For example, a Count rule that
  interpolates the namespace into a custom header sent to the origin:

  ```
  aws wafv2 get-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} --region {region}
  aws wafv2 update-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} \
    --lock-token {lock_token} --default-action {default_action} \
    --rules '[{"Name":"ForwardBotCategory","Priority":10,"Action":{"Count":{"CustomRequestHandling":{"InsertHeaders":[{"Name":"x-amzn-waf-bot-category","Value":"${awswaf:managed:aws:bot-control:bot:category:}"}]}}},"Statement":{"LabelMatchStatement":{"Scope":"NAMESPACE","Key":"awswaf:managed:aws:bot-control:bot:category:"}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"ForwardBotCategory"}}]' \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName={web_acl_name} \
    --region {region}
  ```

#### 3. Strip inbound headers and surface the console link

**Constraints:**

- You MUST add the inbound `x-amzn-waf-*` stripping rule before the forwarding rule
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
  "namespace": "awswaf:managed:aws:bot-control:bot:category:",
  "synthetic_values": ["ip", "ja4"]
}
```

#### Example output

```
Added one rule forwarding the bot-category namespace plus ${awswaf:ip:} and ${awswaf:ja4:} to the origin.
Added an inbound x-amzn-waf-* strip rule before it.
Open the web ACL and confirm the rule order:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### A custom label does not resolve
Use the fully qualified namespace (Step 2).

#### Placeholders missing from the header
The string exceeds 10 placeholders. Split across values (Step 2).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.
- **Header-spoofing risk.** Any `x-amzn-waf-*` signal forwarded to the origin can be forged inbound. You MUST add the inbound-header-stripping rule whenever a signal or client IP is forwarded (see stripping-inbound-waf-headers-before-trusting-them); without it the origin trusts a spoofable value.
- **Encrypted transport.** You MUST forward the signal only to an HTTPS-only origin and the application MUST validate the origin's TLS certificate, so the signal is not exposed in cleartext. You SHOULD use AWS Certificate Manager (ACM) to provision and manage the origin's TLS certificate (for example on an Application Load Balancer), so the certificate is validated and automatically renewed.
- **Defense in depth.** You SHOULD treat the forwarded signal as one input among several, not a sole gate; over-relying on a single signal without defense in depth leaves the application exposed if the signal is evaded or degraded.

## Additional Resources

- [Dynamic label interpolation (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-dynamic-label-interpolation.html)
- [Customizing web requests and responses in AWS WAF (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-custom-request-response.html)
