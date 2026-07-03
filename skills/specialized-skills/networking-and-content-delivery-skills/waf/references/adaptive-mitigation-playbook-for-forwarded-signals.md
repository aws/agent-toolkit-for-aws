# Adaptive Mitigation Playbook for Forwarded Signals

## Overview

Domain expertise for what the application does once a bot confidence signal reaches it, the decision
layer on top of the labels-to-confidence-signal and dynamic-label-interpolation references. Covers
the graduated response by confidence level, the friction-free path for teams that will not use
CAPTCHA, and the one piece that is AWS WAF configuration: a rate-based rule aggregating on the
session token for volumetric abuse.

This reference is mostly application-side guidance, not AWS WAF steps. Deciding when to move a
customer from signal forwarding into this playbook belongs to the router and reasoning layer, not to
this reference reaching into another.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Graduated response by confidence
- The friction-free path without CAPTCHA
- Volumetric abuse: rate-based on the session token
- Boundary
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To apply the adaptive mitigation playbook, follow the guidance below and the procedure for the one
AWS WAF piece. The application owns the low, medium, and high responses; AWS WAF owns the rate-based
rule.

## Graduated response by confidence

A single block-or-allow decision either lets abuse through or blocks real users. A graduated
response uses the confidence signal the application already receives.

**Constraints:**

- You SHOULD guide the application to a graduated response: at low confidence, withhold valuable
  data or nudge the user to sign in; at medium, require authentication or step-up multi-factor
  authentication (MFA); at high, route to a manual-review queue rather than auto-processing
- You MUST frame these as application-side responses the customer implements, not as AWS WAF steps
  this reference executes

## The friction-free path without CAPTCHA

Teams that refuse CAPTCHA still need to slow abuse without blocking real users.

**Constraints:**

- You SHOULD offer the friction-free responses (data withholding, step-up authentication,
  manual-review routing) for teams that will not use CAPTCHA, rather than falling back to blocking

## Volumetric abuse: rate-based on the session token

Volumetric abuse from sessions that each stay under a per-IP limit is keyed to a token, not an
address. This is the one piece that is AWS WAF configuration.

**Constraints:**

- You MUST add a rate-based rule aggregating on the session token or JSON Web Token (JWT) for the
  volumetric case, so the limit follows the session rather than the IP (see the adding-rate-based-
  rules reference for the mechanics)
- You SHOULD let the application handle the throttling response (returning fewer items, slowing the
  flow) once the rate-based rule flags the session

## Boundary

This reference is the decision layer, not an orchestrator.

**Constraints:**

- You MUST NOT chain the customer from this playbook into a different workflow; the router and
  reasoning layer decide when a customer moves between forwarding signals and acting on them
- You SHOULD keep this reference focused on the response to a signal that already exists, not on
  producing the signal (that is the labels-to-confidence and interpolation references)

## Troubleshooting

### Real users get blocked under the playbook
The response is too aggressive at low confidence. Withhold data or nudge to sign in rather than
block (Graduated response by confidence).

### Volumetric abuse continues despite a per-IP rate limit
The abuse is per-session, not per-IP. Add a rate-based rule on the session token (Volumetric abuse:
rate-based on the session token).

## Procedure

### Overview

This procedure covers the one AWS WAF piece, the session-token rate-based rule; the graduated
responses are application-side guidance above.

### Parameters

- **web_acl_name**, **web_acl_id**, **scope** (required): Identify the web ACL.
- **session_key** (required): The session token or JWT field to aggregate on.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm a confidence signal is already reaching the application before advising on the
  graduated responses

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm the session token or JWT is present on the requests to aggregate on

#### 2. Add the session-token rate-based rule

**Constraints:**

- You MUST add a rate-based rule with a `CUSTOM_KEYS` aggregation on the session token or JWT, in
  Count first, following the adding-rate-based-rules reference for the window and threshold rules
- You MUST fetch the current `LockToken` with `get-web-acl` immediately before `update-web-acl`
  and pass the full rule set, since `--rules` is a complete replacement
- You MUST preserve the web ACL's existing `DefaultAction` from the `get-web-acl` response and pass
  it back as `{default_action}`; do not assume `Allow={}`, since that would silently open all
  unmatched traffic on a web ACL whose default action is `Block`. For example, a `CUSTOM_KEYS`
  rate-based rule aggregating on the session-token header, in Count:

  ```
  aws wafv2 get-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} --region {region}
  aws wafv2 update-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} \
    --lock-token {lock_token} --default-action {default_action} \
    --rules '[{"Name":"RateLimitSession","Priority":1,"Action":{"Count":{}},"Statement":{"RateBasedStatement":{"Limit":100,"EvaluationWindowSec":300,"AggregateKeyType":"CUSTOM_KEYS","CustomKeys":[{"Header":{"Name":"{session_key}","TextTransformations":[{"Priority":0,"Type":"NONE"}]}}]}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"RateLimitSession"}}]' \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName={web_acl_name} \
    --region {region}
  ```

- You SHOULD leave the throttling response to the application once the rule flags the session

#### 3. Surface the console link

**Constraints:**

- You MUST present the web ACL console link and tell the customer to confirm the rate-based rule:

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
  "session_key": "x-session-token"
}
```

#### Example output

```
Application guidance: low -> withhold data / nudge sign-in; medium -> step-up MFA; high -> manual review.
Added a CUSTOM_KEYS rate-based rule on x-session-token for the volumetric case, in Count.
Open the web ACL and confirm the rate-based rule:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### Real users blocked
Soften the low-confidence response (Step, Graduated response by confidence).

#### Per-session abuse continues
Add the session-token rate-based rule (Step 2).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.
- **Defense in depth.** You SHOULD treat the forwarded confidence signal as one input among several, not a sole gate; over-relying on a single signal without defense in depth leaves the application exposed if the signal is evaded or degraded.

## Additional Resources

- [How to use AWS WAF Bot Control for targeted bots signals and mitigate evasive bots with adaptive user experience (AWS Networking & Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/how-to-use-aws-waf-bot-control-for-targeted-bots-signals-and-mitigate-evasive-bots-with-adaptive-user-experience/)
- [AWS WAF CAPTCHA and Challenge actions (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-captcha-and-challenge.html)
- [Using rate-based rule statements in AWS WAF (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-statement-type-rate-based.html)
