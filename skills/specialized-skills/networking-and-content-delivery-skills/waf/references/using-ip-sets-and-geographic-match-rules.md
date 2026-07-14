# Using IP Sets and Geographic Match Rules

## Overview

Domain expertise for allow and block lists in AWS WAF based on source IP range or country. Covers
the IP set scope that must match the web ACL, the fact that a geographic match matches only at the
country level (region-level needs a paired label-match rule), the forwarded-IP configuration needed
behind a proxy, and keeping a compliance country list current without hand edits.

Does not cover rate-based rules, managed rules, bot, or fraud rule groups; those are separate
references. Recovering the real client IP behind a CDN has its own reference that this one points
at.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- IP set scope must match the web ACL
- Geographic match is country-level by default
- Reading the real client IP behind a proxy
- Keeping a compliance country list current
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To add IP set or geographic match rules end to end, follow the procedure exactly. See the Procedure
section below.

The procedure covers:

- Creating an IP set in the scope that matches the web ACL
- Adding an IP set match or geographic match statement with an allow or block action
- Configuring forwarded-IP reading when behind a proxy
- Confirming and surfacing the console link

## IP set scope must match the web ACL

An IP set used with a CloudFront web ACL must be in the Global (CloudFront) scope; a regional web
ACL needs a regional IP set in the same Region. A scope mismatch means the web ACL cannot reference
the IP set.

**Constraints:**

- You MUST create the IP set in the scope that matches the protected resource type before
  referencing it
- You MUST NOT expect a regional IP set to be usable from a CloudFront web ACL or vice versa

## Geographic match is country-level by default

A geographic match statement matches by itself only at the country level. Region-level (sub-country)
matching requires a geo match rule followed by a label-match rule. Customers try a single rule for
a region and it silently does not match.

**Constraints:**

- You MUST pair a geo match rule with a label-match rule when the customer asks for region-level
  control, rather than expecting the single statement to match a sub-country region
- You SHOULD note that the geo match adds a country label automatically that the label-match rule
  then keys on

## Reading the real client IP behind a proxy

By default a geo match reads the country from the request origin IP, which is the proxy or load
balancer rather than the real client, so the wrong sources are matched.

**Constraints:**

- You MUST enable forwarded-IP configuration to read the client address from a header such as
  `X-Forwarded-For` when the application sits behind a proxy
- You SHOULD trust the forwarded header only from a known upstream, and pair it with the
  inbound-header-stripping reference (see stripping-inbound-waf-headers-before-trusting-them)

## Keeping a compliance country list current

Customers maintaining a blocked-country list for compliance edit it by hand and it drifts out of
date.

**Constraints:**

- You SHOULD point at the automated pattern that keeps the blocked-country list current from a
  configuration source, rather than relying on manual edits, when the list backs a compliance
  requirement

## Troubleshooting

### The web ACL cannot reference the IP set
The IP set is in the wrong scope. Recreate it in the scope that matches the web ACL (IP set scope
must match the web ACL).

### A region-level geo rule does not match
A single geo match statement is country-level only. Pair it with a label-match rule (Geographic
match is country-level by default).

### Geo matching blocks the wrong sources
The rule reads the proxy IP. Enable forwarded-IP configuration (Reading the real client IP behind a
proxy).

## Procedure

### Overview

This procedure creates an IP set in the right scope, adds an IP set or geographic match rule, and
surfaces the console link.

### Parameters

- **web_acl_name**, **web_acl_id**, **scope** (required): Identify the web ACL.
- **match_type** (required): `ip_set` or `geo`.
- **addresses** (required for `ip_set`): The IP addresses and CIDR ranges.
- **country_codes** (required for `geo`): The country codes to match.
- **action** (required): `Allow` or `Block`.
- **forwarded_ip** (optional): Whether to read the client IP from a forwarding header.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST set the IP set scope to match the web ACL before creating it

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`

#### 2. Create the IP set (for an IP set rule)

**Constraints:**

- You MUST create the IP set in the matching scope:

  ```
  aws wafv2 create-ip-set --name {name} --scope {scope} --ip-address-version IPV4 \
    --addresses {addresses} --region {region}
  ```

- You MUST treat `update-ip-set` as a full replacement; pass the complete merged list, not just new
  entries

#### 3. Add the match rule

**Constraints:**

- You MUST add the IP set match or geographic match statement with the chosen action, fetching the
  current `LockToken` immediately before `update-web-acl` and passing the full rule set
- You MUST preserve the web ACL's existing `DefaultAction` from the `get-web-acl` response and pass
  it back as `{default_action}`; do not assume `Allow={}`, since that would silently open all
  unmatched traffic on a web ACL whose default action is `Block`
- You MUST add a paired label-match rule for region-level geo control
- You MUST enable forwarded-IP configuration when the application is behind a proxy

#### 4. Confirm and surface the console link

**Constraints:**

- You MUST present the web ACL console link and tell the customer to open it and confirm the rule:

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
  "match_type": "geo",
  "country_codes": ["KP", "IR"],
  "action": "Block",
  "forwarded_ip": true
}
```

#### Example output

```
Added a geo-match Block rule for KP, IR, reading the client IP from X-Forwarded-For.
Open the web ACL and confirm the rule:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### The IP set cannot be referenced
Scope mismatch. Recreate the IP set in the web ACL's scope (Step 2).

#### A sub-country region does not match
Geo match is country-level. Add a label-match rule (Step 3).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.
- **Header-spoofing risk.** Any `x-amzn-waf-*` signal forwarded to the origin can be forged inbound. You MUST add the inbound-header-stripping rule whenever a signal or client IP is forwarded (see stripping-inbound-waf-headers-before-trusting-them); without it the origin trusts a spoofable value.

## Additional Resources

- [Creating and managing an IP set in AWS WAF (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-ip-set-managing.html)
- [Geographic match rule statement (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-statement-type-geo-match.html)
- [How to use AWS WAF to filter incoming traffic from embargoed countries (AWS Security Blog)](https://aws.amazon.com/blogs/security/how-to-use-aws-waf-to-filter-incoming-traffic-from-embargoed-countries/)
