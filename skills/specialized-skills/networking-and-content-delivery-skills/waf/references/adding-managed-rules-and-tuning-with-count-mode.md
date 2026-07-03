# Adding Managed Rules and Tuning with Count Mode

## Overview

Domain expertise for adding AWS Managed Rules rule groups to a web ACL and rolling them out without
blocking legitimate traffic. Covers matching rule groups to the workload, the web ACL capacity unit
(WCU) budget (the basic price covers up to 1,500 WCUs; a web ACL holds a hard maximum of 5,000),
the Count-mode-first tuning path, and reading the triggering rule from logs to override just that
rule rather than the whole group.

Does not cover rate-based rules, match rules, bot, or fraud rule groups; those are separate
references. Logging must already be set up (see the logging reference).

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Decision: which managed rule groups
- WCU budget: 1,500 priced tier, 5,000 hard maximum
- Count mode first
- Override one rule, not the whole group
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To add managed rules and tune them end to end, follow the procedure exactly. See the Procedure
section below.

The procedure covers:

- Selecting managed rule groups that match the workload, within the WCU budget
- Adding them in Count mode with logging and metrics on
- Reviewing which legitimate requests would have been blocked
- Overriding the offending rules and switching the rest to Block

## Decision: which managed rule groups

| Workload | Rule group |
| --- | --- |
| Broad coverage (OWASP Top 10) | Core Rule Set (CRS) |
| Known exploit patterns | Known Bad Inputs |
| Database-backed application | SQL database rule group |
| Reputation filtering | Amazon IP reputation list, Anonymous IP list |

**Constraints:**

- You MUST match rule groups to the workload using the published rule group list, rather than
  enabling all of them or none
- You SHOULD start from a small baseline (Core Rule Set plus one or two targeted groups) and add
  more only as needed

## WCU budget: 1,500 priced tier, 5,000 hard maximum

Each managed rule group consumes WCUs against the web ACL's capacity. The basic web ACL price
covers up to 1,500 WCUs; beyond that, usage is billed on a tiered model that AWS WAF adjusts
automatically. The hard maximum for a web ACL is 5,000 WCUs. The Core Rule Set alone is 700, so a
second large group moves into the priced tier quickly.

**Constraints:**

- You MUST track WCU usage as rule groups are added, naming the real numbers: the basic price
  covers up to 1,500 WCUs and the web ACL maximum is 5,000 WCUs
- You SHOULD account for the Core Rule Set's 700 WCUs before adding a second large group such as
  Known Bad Inputs or the Anonymous IP list
- You MUST NOT describe 1,500 as a ceiling or limit; it is the point where tiered pricing begins,
  not a cap. Crossing 1,500 increases cost but does not block traffic or rule additions
- You SHOULD note the 5,000 WCU maximum is fixed and not raisable; when a web ACL approaches it,
  trim or consolidate rules rather than expecting a quota increase

## Count mode first

Adding a managed group straight in Block mode can take down legitimate traffic, because the
predefined rules match patterns the application uses normally.

**Constraints:**

- You MUST add managed rule groups in Count mode first, which records matches without changing how
  requests are handled
- You MUST switch to Block only after the customer reviews the Count-mode matches

## Override one rule, not the whole group

When a false positive appears, customers often disable the whole rule group and lose its
protection. The fix is to override only the offending rule.

**Constraints:**

- You MUST identify the triggering rule from the logs and override just that rule to Count using
  `RuleActionOverrides`, rather than disabling the group
- You MUST set the group's `OverrideAction` to `None` when using individual `RuleActionOverrides`;
  setting `OverrideAction` to `Count` overrides the whole group and the individual overrides have
  no effect
- You SHOULD note that a rule overridden to Count still adds its labels, so a downstream label-match
  rule can still act on it

## Troubleshooting

### Legitimate traffic is blocked after enabling a group
A managed rule is a false positive for this application. Find it in the logs and override just that
rule to Count (Override one rule, not the whole group).

### The web ACL hit the 5,000 WCU maximum
The combined rule groups exceed the 5,000 WCU hard maximum, which is not raisable. Trim or
consolidate rules (WCU budget: 1,500 priced tier, 5,000 hard maximum). Note: crossing 1,500 WCUs
does not cause this error; it only moves the web ACL into tiered pricing.

### Individual rule overrides have no effect
`OverrideAction` is set to `Count` for the whole group, which cancels individual overrides. Set
`OverrideAction` to `None` (Override one rule, not the whole group).

## Procedure

### Overview

This procedure adds managed rule groups in Count mode within the WCU budget, tunes false positives,
and switches to Block, then surfaces the console link.

### Parameters

- **web_acl_name**, **web_acl_id**, **scope** (required): Identify the web ACL.
- **rule_groups** (required): The managed rule groups to add, matched to the workload.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm logging is already enabled before adding rules in Count mode

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm logging and request sampling are on (see the logging reference)

#### 2. Add managed rule groups in Count mode

**Constraints:**

- You MUST add each rule group with `OverrideAction` set to `Count` initially, tracking WCU usage
  (the basic price covers up to 1,500 WCUs; the web ACL maximum is 5,000)
- You MUST fetch the current `LockToken` with `get-web-acl` immediately before each `update-web-acl`
  and pass the full rule set, since `--rules` is a complete replacement
- You MUST preserve the web ACL's existing `DefaultAction` from the `get-web-acl` response and pass
  it back as `{default_action}`; do not assume `Allow={}`, since that would silently open all
  unmatched traffic on a web ACL whose default action is `Block`:

  ```
  aws wafv2 get-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} --region {region}
  aws wafv2 update-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} \
    --lock-token {lock_token} --default-action {default_action} \
    --rules '[{"Name":"AWS-CRS","Priority":1,"Statement":{"ManagedRuleGroupStatement":{"VendorName":"AWS","Name":"AWSManagedRulesCommonRuleSet"}},"OverrideAction":{"Count":{}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"AWS-CRS"}}]' \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName={web_acl_name} \
    --region {region}
  ```

#### 3. Review and tune

**Constraints:**

- You MUST review the Count-mode matches in the logs and sampled requests over a representative
  period
- You MUST override only the rules that produce false positives, using `RuleActionOverrides` with
  the group's `OverrideAction` set to `None`

#### 4. Switch to Block and surface the console link

**Constraints:**

- You MUST switch the tuned groups to enforce by setting `OverrideAction` to `None` and let the
  group's own actions apply
- You MUST present the web ACL console link and tell the customer to open it and confirm the rules
  and their actions:

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
  "rule_groups": ["AWSManagedRulesCommonRuleSet", "AWSManagedRulesKnownBadInputsRuleSet"]
}
```

#### Example output

```
Added Core Rule Set (700 WCU) and Known Bad Inputs (200 WCU) in Count mode — 900 WCUs used (within the 1,500 base-price tier; web ACL max is 5,000).
Reviewed matches, overrode CrossSiteScripting_BODY to Count for the API path false positive.
Switched the rest to Block.
Open the web ACL and confirm the rules and actions:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### Legitimate traffic blocked
Find the offending rule in the logs and override just it to Count (Step 3).

#### Capacity maximum hit
The groups exceed the 5,000 WCU maximum (not 1,500, which is only a pricing threshold). Trim or consolidate rules (Step 2).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.

## Additional Resources

- [Using managed rule groups in AWS WAF (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-managed-rule-groups.html)
- [AWS Managed Rules rule groups list (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-list.html)
- [Baseline rule groups (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-baseline.html)
- [Testing and tuning your AWS WAF protections (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/web-acl-testing.html)
