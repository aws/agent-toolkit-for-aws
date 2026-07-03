# Protecting Against Bots with Bot Control

## Overview

Domain expertise for the AWS WAF Bot Control on-ramp: adding the Bot Control managed rule group,
choosing Common versus Targeted, and observing in Count mode before enforcing. Covers the sharp
difference between Common and Targeted, the application integration SDK as a precondition for
Targeted, the machine learning warm-up, the verified-bot Count-override gotcha, and the added cost.

Does not cover what to do with the labels Bot Control produces; turning labels into a confidence
signal, forwarding that signal, and the application's response are three separate references that
build on this one.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Decision: Common vs Targeted
- The SDK is a precondition for Targeted
- Machine learning warm-up
- Verified-bot Count-override gotcha
- Added cost
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To turn on Bot Control end to end, follow the procedure exactly. See the Procedure section below.

The procedure covers:

- Adding the Bot Control rule group and choosing the inspection level
- Running in Count mode to see how traffic is labeled
- Keeping verified bots passing while tuning
- Deciding which categories to block, challenge, or allow, then enforcing

This reference is the on-ramp. Turning the labels into an application decision is the
turning-bot-control-labels-into-a-confidence-signal reference and the ones after it.

## Decision: Common vs Targeted

| Level | Detects | SDK | Best for |
| --- | --- | --- | --- |
| Common | Self-identifying bots (user-agent such as `curl`, `python-requests`, declared crawlers) and known-bad IPs | Not required | Basic filtering of honest bots |
| Targeted | Adds behavioral machine learning, browser interrogation, and token session tracking | Strongly required | Login, checkout, any high-value endpoint facing evasive bots |

**Constraints:**

- You MUST push Targeted for any real or evasive bot threat; Common alone is not meaningful
  protection against bots that impersonate a real browser (headless Chrome, Puppeteer, Selenium,
  residential proxies)
- You MUST NOT present Targeted as an optional upgrade when the customer faces credential stuffing
  or inventory hoarding on a high-value endpoint

## The SDK is a precondition for Targeted

Targeted's behavioral machine learning, browser interrogation, and token session tracking are
largely blind without the application integration SDK or its JavaScript token.

**Constraints:**

- You MUST treat the application integration SDK as a precondition for Targeted, not an optional
  add-on
- You SHOULD confirm the SDK is integrated before relying on Targeted detection

## Machine learning warm-up

The `TGT_ML_*` rules need up to roughly 24 hours to establish a traffic baseline. Customers enable
Targeted, see nothing fire immediately, and assume it is broken.

**Constraints:**

- You MUST set the expectation that `TGT_ML_*` rules need up to roughly 24 hours of warm-up before
  they act
- You SHOULD advise against disabling Targeted during the warm-up window

## Verified-bot Count-override gotcha

Bot Control does not block verified bots; it labels them. Overriding the whole rule group to Count
while tuning also overrides the implicit Allow for verified bots, so they fall through to the
customer's other rules.

**Constraints:**

- You MUST add an explicit Allow rule on the `awswaf:managed:aws:bot-control:bot:verified` label
  when tuning the group in Count, so verified bots keep passing
- You MUST place that Allow rule at a higher priority number than the Bot Control group, so the
  verified-bot label exists when the Allow rule runs
- You SHOULD rely on the verified-bot labeling rather than blanket-blocking all automated traffic

## Added cost

Bot Control incurs additional fees beyond the basic AWS WAF charges.

**Constraints:**

- You MUST state the additional cost before the customer adds the rule group, not after it appears
  on the invoice

## Troubleshooting

### Evasive bots still get through on Common
Common only catches self-identifying bots and known-bad IPs. Move to Targeted with the SDK
(Decision: Common vs Targeted).

### Targeted fires nothing right after enabling
The `TGT_ML_*` rules are still warming up. Wait up to roughly 24 hours (Machine learning warm-up).

### Verified bots get blocked while tuning
Overriding the whole group to Count canceled the verified-bot Allow. Add an explicit Allow on the
verified label (Verified-bot Count-override gotcha).

## Procedure

### Overview

This procedure adds Bot Control at the chosen level in Count mode, keeps verified bots passing,
then enforces, and surfaces the console link.

### Parameters

- **web_acl_name**, **web_acl_id**, **scope** (required): Identify the web ACL.
- **inspection_level** (required): `COMMON` or `TARGETED`.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm logging is enabled and, for Targeted, that the application integration SDK is
  integrated

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm logging and sampling are on
- For Targeted, you MUST confirm the application integration SDK is in place

#### 2. Add Bot Control in Count mode

**Constraints:**

- You MUST add the Bot Control rule group at the chosen inspection level with the group in Count
  while observing
- You MUST add an explicit Allow rule on `awswaf:managed:aws:bot-control:bot:verified` so verified
  bots keep passing during tuning
- You MUST fetch the current `LockToken` before `update-web-acl` and pass the full rule set
- You MUST preserve the web ACL's existing `DefaultAction` from the `get-web-acl` response and pass
  it back as `{default_action}`; do not assume `Allow={}`, since that would silently open all
  unmatched traffic on a web ACL whose default action is `Block`. For example, the Bot Control group
  at the chosen inspection level plus the verified-bot Allow rule:

  ```
  aws wafv2 get-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} --region {region}
  aws wafv2 update-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} \
    --lock-token {lock_token} --default-action {default_action} \
    --rules '[{"Name":"AWS-BotControl","Priority":1,"Statement":{"ManagedRuleGroupStatement":{"VendorName":"AWS","Name":"AWSManagedRulesBotControlRuleSet","ManagedRuleGroupConfigs":[{"AWSManagedRulesBotControlRuleSet":{"InspectionLevel":"{inspection_level}"}}]}},"OverrideAction":{"Count":{}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"AWS-BotControl"}},{"Name":"AllowVerifiedBots","Priority":2,"Action":{"Allow":{}},"Statement":{"LabelMatchStatement":{"Scope":"LABEL","Key":"awswaf:managed:aws:bot-control:bot:verified"}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"AllowVerifiedBots"}}]' \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName={web_acl_name} \
    --region {region}
  ```

#### 3. Review and enforce

**Constraints:**

- You MUST review the labeled traffic (allowing for the Targeted warm-up) before enforcing
- You MUST decide per category whether to block, challenge, or allow, then enforce

#### 4. Surface the console link

**Constraints:**

- You MUST present the web ACL console link and tell the customer to open the Bot Control rule and
  confirm its level and actions:

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
  "inspection_level": "TARGETED"
}
```

#### Example output

```
Confirmed the SDK is integrated. Added Bot Control TARGETED in Count, with an explicit Allow on the verified-bot label.
TGT_ML rules need up to ~24h to warm up before acting.
Open the web ACL and confirm the Bot Control level and actions:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### Evasive bots get through on Common
Move to Targeted with the SDK (Step 1).

#### Nothing fires right after enabling Targeted
The machine learning is warming up; wait up to roughly 24 hours (Step 3).

#### Verified bots blocked while tuning
Add the explicit Allow on the verified label (Step 2).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.

## Additional Resources

- [AWS WAF Bot Control rule group (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-bot.html)
- [Adding the AWS WAF Bot Control managed rule group to your web ACL (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-bot-control-rg-using.html)
- [Using managed rule groups in AWS WAF (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-managed-rule-groups.html)
