# Adding Rate-Based Rules

## Overview

Domain expertise for throttling HTTP floods and brute force with AWS WAF rate-based rules. Covers
the aggregation key choice, the request floor and the allowed evaluation windows, the small cap on
rate-based rules per web ACL and the composite-key way around rule sprawl, scope-down to limit a
subset of requests, and the Count-mode-first path that also matters for Shield cost-protection
eligibility.

Does not cover managed rules, match rules, bot, or fraud rule groups; those are separate
references. Account-based abuse (credential stuffing, fake accounts) goes to the fraud control
reference, not here.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Decision: aggregation key
- Request floor and evaluation windows
- The per-web-ACL cap and composite keys
- Scope-down to a subset of requests
- Count mode and the Shield cost-protection link
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To add a rate-based rule end to end, follow the procedure exactly. See the Procedure section below.

The procedure covers:

- Choosing the aggregation key and a measured threshold
- Setting a valid evaluation window
- Adding a scope-down statement to target a subset of requests
- Running in Count mode, confirming the threshold, then switching to Block

## Decision: aggregation key

| Key | Use when | Avoid when |
| --- | --- | --- |
| `IP` | Direct client connections, no proxy or CDN | Behind a CDN; all requests collapse to the CDN IP |
| `FORWARDED_IP` | A trusted proxy forwards the real client IP in a header | The header is absent or attacker-controlled |
| `CUSTOM_KEYS` | Per-user or per-tenant limits (API key, session, user ID); up to 5 components | The key field is absent on many requests |
| `CONSTANT` | A hard ceiling on total requests to a path; always requires scope-down | Per-client limits are needed |

**Constraints:**

- You MUST choose `FORWARDED_IP` (not `IP`) when the application sits behind a CDN, or the limit
  acts on the CDN address (see the recovering-the-real-client-IP reference)
- You MUST add a scope-down statement when using `CONSTANT`; the API rejects it otherwise

## Request floor and evaluation windows

Customers assume an arbitrary threshold and window and get surprised by the constraints.

**Constraints:**

- You MUST keep the request limit at or above the floor of 10 requests
- You MUST set the evaluation window to one of 60, 120, 300, or 600 seconds; no other value is
  valid
- You SHOULD compute the limit as acceptable requests per second times the window in seconds

## The per-web-ACL cap and composite keys

A web ACL allows only a small number of these high-cost rules (roughly ten). Customers building one
rate-based rule per URI path hit the cap.

**Constraints:**

- You MUST NOT add a separate rate-based rule per path because this quickly exhausts the cap; use
  composite aggregation keys plus scope-down inside fewer rules
- You SHOULD solve per-path limiting with `CUSTOM_KEYS` (for example IP plus API key) and a
  scope-down statement, rather than rule sprawl

## Scope-down to a subset of requests

Customers expect a rate-based rule to count only a specific path, then find it counting all
traffic, because they did not scope it down.

**Constraints:**

- You MUST add a scope-down statement when the customer wants to rate limit a subset such as a
  login endpoint
- You SHOULD apply a `LOWERCASE` text transformation on the path match so casing does not cause the
  scope-down to miss

## Count mode and the Shield cost-protection link

Turning a new rate-based rule straight to Block catches legitimate bursts. Leaving it in Count has
a second consequence on CloudFront and Application Load Balancer resources.

**Constraints:**

- You MUST run the rule in Count mode against production traffic to confirm the threshold before
  switching to Block
- You MUST flag that on CloudFront and Application Load Balancer resources, a rate-based rule in
  Block mode is a prerequisite for AWS Shield Advanced cost protection credits; a Count-only rule
  silently disqualifies a future claim (the shieldadvanced skill owns that workflow)

## Troubleshooting

### The rule never fires under load
The scope-down is not matching (often a casing issue), or the threshold is too high. Add
`LOWERCASE`, or remove the scope-down to test (Scope-down to a subset of requests).

### Rule creation fails validation
`CONSTANT` was used without a scope-down statement, or the window is not one of the allowed values
(Request floor and evaluation windows).

### The rule fires for some sources but not others
Traffic arrives via a proxy and the rule reads the proxy IP. Switch to `FORWARDED_IP` (Decision:
aggregation key).

## Procedure

### Overview

This procedure adds a rate-based rule with a measured threshold, a valid window, and a scope-down,
runs it in Count, then switches to Block, and surfaces the console link.

### Parameters

- **web_acl_name**, **web_acl_id**, **scope** (required): Identify the web ACL.
- **aggregation_key** (required): `IP`, `FORWARDED_IP`, `CUSTOM_KEYS`, or `CONSTANT`.
- **custom_key_components** (required when `aggregation_key` is `CUSTOM_KEYS`): Up to 5 key
  components (for example `IP`, a header name such as `x-api-key`) used for composite aggregation.
- **limit** (required): The request limit, at or above 10.
- **window** (required): One of 60, 120, 300, or 600 seconds.
- **scope_down** (required for `CONSTANT`, recommended otherwise): The statement narrowing which
  requests are counted.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm logging is enabled so the Count-mode threshold can be validated

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm logging and sampling are on

#### 2. Add the rate-based rule in Count mode

**Constraints:**

- You MUST add the rule with a valid window and a limit at or above 10, in Count mode
- You MUST fetch the current `LockToken` with `get-web-acl` immediately before `update-web-acl` and
  pass the full rule set
- You MUST preserve the web ACL's existing `DefaultAction` from the `get-web-acl` response and pass
  it back as `{default_action}`; do not assume `Allow={}`, since that would silently open all
  unmatched traffic on a web ACL whose default action is `Block`:

  ```
  aws wafv2 get-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} --region {region}
  aws wafv2 update-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} \
    --lock-token {lock_token} --default-action {default_action} \
    --rules '[{"Name":"RateLimit","Priority":1,"Action":{"Count":{}},"Statement":{"RateBasedStatement":{"Limit":{limit},"EvaluationWindowSec":{window},"AggregateKeyType":"CUSTOM_KEYS","CustomKeys":[{"Header":{"Name":"x-api-key","TextTransformations":[{"Priority":0,"Type":"NONE"}]}},{"IP":{}}]}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"RateLimit"}}]' \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName={web_acl_name} \
    --region {region}
  ```

- You MUST include a scope-down statement for `CONSTANT`, and use composite `CUSTOM_KEYS` rather
  than many per-path rules

#### 3. Confirm the threshold and switch to Block

**Constraints:**

- You MUST review Count-mode data to confirm the threshold does not catch legitimate bursts
- You MUST switch the rule action to Block once validated by re-running `update-web-acl` with the
  rule's `"Action"` changed from `{"Count":{}}` to `{"Block":{}}` (fetch a fresh `LockToken` first
  and pass the full rule set)
- For CloudFront and Application Load Balancer resources, you MUST confirm the rule is in Block mode
  if the customer relies on Shield Advanced cost protection

#### 4. Surface the console link

**Constraints:**

- You MUST present the web ACL console link and tell the customer to open it and confirm the
  rate-based rule and its action:

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
  "aggregation_key": "CUSTOM_KEYS",
  "custom_key_components": ["IP", "x-api-key"],
  "limit": 20,
  "window": 300,
  "scope_down": "URI path starts with /login"
}
```

#### Example output

```
Added a CUSTOM_KEYS (IP + x-api-key) rate-based rule, limit 20 per 300s, scoped to /login, in Count.
Confirmed the threshold does not catch legitimate logins, switched to Block.
Open the web ACL and confirm the rate-based rule and action:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### The rule never fires
Scope-down casing or threshold too high. Add `LOWERCASE` or lower the limit (Step 2).

#### Validation error on creation
`CONSTANT` without scope-down, or an invalid window. Fix both (Step 2).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.

## Additional Resources

- [Using rate-based rule statements in AWS WAF (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-statement-type-rate-based.html)
- [Testing and tuning your AWS WAF protections (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/web-acl-testing.html)
- [The three most important AWS WAF rate-based rules (AWS Security Blog)](https://aws.amazon.com/blogs/security/three-most-important-aws-waf-rate-based-rules/)
