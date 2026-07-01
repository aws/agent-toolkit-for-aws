# Recovering the Real Client IP Behind a CDN

## Overview

Domain expertise for making AWS WAF act on the real client IP when it sits behind a third-party
content delivery network (CDN) or proxy, where the connection IP is the CDN's. Covers enabling
forwarded-IP configuration on rate-based, IP set, and geographic match rules, forwarding
`${awswaf:ip:}` to the origin, and trusting forwarded headers only from a known upstream.

Does not cover the rules themselves in depth (see the rate-based and IP/geo references); this is the
forwarded-IP concern that cuts across them. Pairs with the inbound-header-stripping reference.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- The problem: WAF sees the CDN's IP
- Enable forwarded-IP on the affected rules
- Trust the header only from a known upstream
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To recover the real client IP end to end, follow the procedure exactly. See the Procedure section
below.

The procedure covers:

- Identifying which rules act on the wrong address
- Enabling forwarded-IP configuration on rate-based and IP or geo rules
- Optionally forwarding `${awswaf:ip:}` to the origin
- Pairing with the inbound-header-stripping rule

## The problem: WAF sees the CDN's IP

Behind a CDN, the connection IP AWS WAF reads is the CDN's, not the user's, so IP set rules,
rate-based rules, and geographic match rules all act on the wrong address. Customers often do not
know AWS WAF can recover the true client IP and conclude their rules are broken.

**Constraints:**

- You MUST recognize that IP-based rules act on the CDN address by default when behind a CDN, and
  surface the forwarded-IP option rather than letting the customer disable rules that look broken

## Enable forwarded-IP on the affected rules

Forwarded-IP configuration tells the rule to read the client address from a header such as
`X-Forwarded-For`, `True-Client-IP`, or a custom header.

**Constraints:**

- You MUST enable forwarded-IP configuration on the rate-based and IP or geo rules that need the
  real client address
- You SHOULD forward `${awswaf:ip:}` (the resolved client IP) to the origin via interpolation when
  the origin needs it, rather than parsing the forwarding header downstream
- You MUST forward the interpolated client IP only to an HTTPS-only origin, and the application MUST
  validate the origin's TLS certificate, so the header is not exposed in cleartext. You SHOULD use
  AWS Certificate Manager (ACM) to provision and manage the origin's TLS certificate (for example on
  an Application Load Balancer), so the certificate is validated and automatically renewed

## Trust the header only from a known upstream

A forwarding header can be set by anyone unless the upstream is trusted, which lets an attacker
forge the client address.

**Constraints:**

- You MUST trust the forwarded header only when it comes from a known, trusted upstream
- You MUST pair this with the inbound-header-stripping rule (see
  stripping-inbound-waf-headers-before-trusting-them) when forwarding the client IP to the origin

## Troubleshooting

### Rate or geo rules act on the wrong source behind a CDN
The rules read the CDN IP. Enable forwarded-IP configuration on them (Enable forwarded-IP on the
affected rules).

### An attacker forges the client IP
The forwarding header is trusted from an untrusted source. Trust it only from a known upstream and
add the strip rule (Trust the header only from a known upstream).

## Procedure

### Overview

This procedure enables forwarded-IP on the affected rules, optionally forwards the client IP to the
origin, and surfaces the console link.

### Parameters

- **web_acl_name**, **web_acl_id**, **scope** (required): Identify the web ACL.
- **forwarding_header** (required): `X-Forwarded-For`, `True-Client-IP`, or a custom header the
  trusted upstream sets.
- **affected_rules** (required): Which rate-based, IP set, or geo rules need the real client IP.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm which upstream sets the forwarding header and that it is trusted

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm the trusted upstream reliably sets the forwarding header

#### 2. Enable forwarded-IP on the rules

**Constraints:**

- You MUST add forwarded-IP configuration (header name and fallback behavior) to the affected
  rate-based and IP or geo rules
- You MUST fetch the current `LockToken` before `update-web-acl` and pass the full rule set
- You MUST preserve the web ACL's existing `DefaultAction` from the `get-web-acl` response and pass
  it back as `{default_action}`; do not assume `Allow={}`, since that would silently open all
  unmatched traffic on a web ACL whose default action is `Block`. For example, a geo-match rule
  reading the client IP from a forwarding header:

  ```
  aws wafv2 get-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} --region {region}
  aws wafv2 update-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} \
    --lock-token {lock_token} --default-action {default_action} \
    --rules '[{"Name":"BlockHighRiskCountries","Priority":1,"Action":{"Block":{}},"Statement":{"GeoMatchStatement":{"CountryCodes":["KP","IR"],"ForwardedIPConfig":{"HeaderName":"{forwarding_header}","FallbackBehavior":"NO_MATCH"}}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"BlockHighRiskCountries"}}]' \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName={web_acl_name} \
    --region {region}
  ```

  Rate-based rules take the same `ForwardedIPConfig` under `RateBasedStatement`; `FallbackBehavior`
  is `MATCH` or `NO_MATCH` for when the header is absent

#### 3. Optionally forward the client IP and add the strip rule

**Constraints:**

- You SHOULD forward `${awswaf:ip:}` to the origin if it needs the client IP
- You MUST add the inbound-header-stripping rule when forwarding the client IP

#### 4. Surface the console link

**Constraints:**

- You MUST present the web ACL console link and tell the customer to confirm the rules read the
  forwarded IP:

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
  "forwarding_header": "X-Forwarded-For",
  "affected_rules": ["RateLimitLogin", "BlockHighRiskCountries"]
}
```

#### Example output

```
Enabled forwarded-IP (X-Forwarded-For) on the rate-based and geo rules so they act on the real client IP.
Confirmed the CDN is a trusted upstream and added an inbound x-amzn-waf-* strip rule.
Open the web ACL and confirm the rules read the forwarded IP:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### Rules still act on the CDN address
Forwarded-IP is not enabled on them. Add it (Step 2).

#### The client IP can be forged
Trust the header only from a known upstream and add the strip rule (Step 3).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.
- **Header-spoofing risk.** Any `x-amzn-waf-*` signal forwarded to the origin can be forged inbound. You MUST add the inbound-header-stripping rule whenever a signal or client IP is forwarded (see stripping-inbound-waf-headers-before-trusting-them); without it the origin trusts a spoofable value.
- **Encrypted transport.** You MUST forward the signal only to an HTTPS-only origin and the application MUST validate the origin's TLS certificate, so the signal is not exposed in cleartext. You SHOULD use AWS Certificate Manager (ACM) to provision and manage the origin's TLS certificate (for example on an Application Load Balancer), so the certificate is validated and automatically renewed.
- **Defense in depth.** You SHOULD treat the forwarded signal as one input among several, not a sole gate; over-relying on a single signal without defense in depth leaves the application exposed if the signal is evaded or degraded.

## Additional Resources

- [Using forwarded IP addresses in AWS WAF (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-statement-forwarded-ip-address.html)
- [Dynamic label interpolation (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-dynamic-label-interpolation.html)
