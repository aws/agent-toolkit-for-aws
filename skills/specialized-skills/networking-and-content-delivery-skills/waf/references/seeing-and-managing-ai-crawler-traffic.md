# Seeing and Managing AI and LLM Crawler Traffic

## Overview

Domain expertise for deciding, per AI scraper, whether to allow or block it in AWS WAF. Covers the
AI activity visibility surface, the AI and large language model (LLM) bot labels Bot Control
applies, category-based handling, and composing the AI labels into the existing bot confidence
signal.

Does not cover turning Bot Control on (the protecting-against-bots reference) or the confidence
signal chain in depth (its own references). This reference depends on Bot Control being enabled.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- See the AI traffic first
- Handle AI traffic by category
- Compose into the confidence signal
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To see and manage AI crawler traffic end to end, follow the procedure exactly. See the Procedure
section below.

The procedure covers:

- Using the AI activity surface to see which AI and LLM crawlers are arriving
- Reading the AI and LLM bot labels
- Handling that traffic by category (allow wanted crawlers, block or challenge unwanted ones)
- Optionally composing the AI labels into the existing confidence signal

## See the AI traffic first

Customers want to allow some AI crawlers and block others but cannot see the AI traffic, so they
cannot make the decision.

**Constraints:**

- You MUST surface the AI activity view and the AI and LLM bot labels so the customer can see which
  crawlers arrive before deciding on each
- You SHOULD confirm Bot Control is enabled, since the AI labels come from it

## Handle AI traffic by category

Customers treat all AI crawler traffic as one block-or-allow decision when they want different
handling per crawler.

**Constraints:**

- You MUST handle AI traffic by category using the bot labels, so the customer can allow wanted
  crawlers and block or challenge unwanted ones, rather than a single blanket decision

## Compose into the confidence signal

A customer already forwarding a bot confidence signal can feed AI labels into the same chain rather
than building a separate path.

**Constraints:**

- You SHOULD compose the AI labels into the existing confidence signal (see
  turning-bot-control-labels-into-a-confidence-signal) rather than building a separate AI path
- You MUST NOT duplicate the forwarding mechanism for AI traffic when a confidence signal already
  exists

## Troubleshooting

### The customer cannot see which AI crawlers are arriving
The AI activity surface or AI labels are not in view, or Bot Control is not enabled. Enable Bot
Control and use the AI activity view (See the AI traffic first).

### AI handling is all-or-nothing
The customer is making one blanket decision. Handle by category using the labels (Handle AI traffic
by category).

## Procedure

### Overview

This procedure surfaces AI crawler traffic, handles it by category, optionally composes it into the
confidence signal, and surfaces the console link.

### Parameters

- **web_acl_name**, **web_acl_id**, **scope** (required): Identify the web ACL.
- **category_handling** (required): Which AI or LLM categories to allow, block, or challenge.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm Bot Control is enabled and producing AI labels

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm Bot Control is enabled and AI labels are present

#### 2. Review AI traffic and add category handling

**Constraints:**

- You MUST review the AI activity and labels before deciding
- You MUST add label-match rules handling the AI categories per the customer's decision, fetching
  the current `LockToken` before `update-web-acl` and passing the full rule set
- You MUST preserve the web ACL's existing `DefaultAction` from the `get-web-acl` response and pass
  it back as `{default_action}`; do not assume `Allow={}`, since that would silently open all
  unmatched traffic on a web ACL whose default action is `Block`. For example, a Block rule on an
  unwanted AI crawler label:

  ```
  aws wafv2 get-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} --region {region}
  aws wafv2 update-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} \
    --lock-token {lock_token} --default-action {default_action} \
    --rules '[{"Name":"BlockUnwantedAICrawler","Priority":1,"Action":{"Block":{}},"Statement":{"LabelMatchStatement":{"Scope":"LABEL","Key":"awswaf:managed:aws:bot-control:bot:category:ai"}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"BlockUnwantedAICrawler"}}]' \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName={web_acl_name} \
    --region {region}
  ```

#### 3. Optionally compose into the confidence signal and surface the console link

**Constraints:**

- You SHOULD feed the AI labels into the existing confidence signal rather than a separate path
- You MUST present the web ACL console link and tell the customer to confirm the AI handling rules:

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
  "category_handling": {"allow": ["wanted search AI"], "block": ["unwanted scraper AI"]}
}
```

#### Example output

```
Reviewed AI crawler labels in the AI activity view.
Allowed the wanted crawler category, blocked the unwanted one, and fed the labels into the existing confidence signal.
Open the web ACL and confirm the AI handling rules:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### Cannot see AI crawlers
Enable Bot Control and use the AI activity view (Step 1).

#### Handling is all-or-nothing
Add per-category label-match rules (Step 2).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.

## Additional Resources

- [AWS WAF Bot Control rule group (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-bot.html)
- [AWS WAF label match rule statement (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-label-match-statement.html)
