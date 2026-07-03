# Protecting Logins and Signups with Fraud Control

## Overview

Domain expertise for AWS WAF Fraud Control: the Account Takeover Prevention (ATP) managed rule group
for login protection and the Account Creation Fraud Prevention (ACFP) managed rule group for signup
protection. Covers why rate limiting misses this abuse, the mandatory application integration SDK,
the CloudFront-only limitation on response inspection and its workaround, and the Count-first tuning
path.

Does not cover generic rate limiting (the rate-based reference) or bot detection (the bot
references). Those are separate.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Decision: ATP, ACFP, or both
- The SDK is mandatory
- Response inspection is CloudFront only
- Count mode first
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To protect logins and signups end to end, follow the procedure exactly. See the Procedure section
below.

The procedure covers:

- Adding ATP for login protection, ACFP for signup protection, or both
- Integrating the application integration SDK
- Configuring request inspection (and response inspection where supported)
- Running in Count mode, then mapping labels to actions

## Decision: ATP, ACFP, or both

| Threat | Rule group |
| --- | --- |
| Credential stuffing against a login page | Account Takeover Prevention (ATP) |
| Fake-account creation against a signup page | Account Creation Fraud Prevention (ACFP) |
| Both | Add both rule groups |

**Constraints:**

- You MUST reach for ATP and ACFP for account-based abuse rather than rate-based rules; the abuse is
  distributed and low-rate per source, so rate limiting misses it
- You SHOULD configure the login path for ATP and both the registration page and creation paths for
  ACFP

## The SDK is mandatory

Both rule groups rely on session tokens that the application integration SDK issues. Without it the
protection is weak.

**Constraints:**

- You MUST treat the application integration SDK as mandatory for ATP and ACFP, not optional
- You SHOULD confirm the SDK is integrated before relying on these rule groups

## Response inspection is CloudFront only

Response inspection (tracking login success and failure) is available only on web ACLs protecting
CloudFront distributions.

**Constraints:**

- You MUST tell the customer that on an Application Load Balancer the response-based rules such as
  `VolumetricIpFailedLoginResponseHigh` and `VolumetricSessionFailedLoginResponseHigh` will not fire
- You SHOULD offer the workaround of putting CloudFront in front of the Application Load Balancer
  when response inspection is needed

## Count mode first

Turning these rule groups straight to Block risks locking out real users on a busy login page.

**Constraints:**

- You MUST run ATP and ACFP in Count mode first, review the labeled traffic, then map labels to
  actions before enforcing

## Troubleshooting

### Credential stuffing gets through despite a rate limit
Rate limiting misses distributed, low-rate account abuse. Add ATP (Decision: ATP, ACFP, or both).

### Response-based rules never fire on an ALB
Response inspection is CloudFront only. Put CloudFront in front of the ALB (Response inspection is
CloudFront only).

### Protection is weak even with ATP enabled
The SDK is not integrated. Integrate it (The SDK is mandatory).

## Procedure

### Overview

This procedure adds ATP, ACFP, or both with the SDK, configures inspection, runs in Count, then
maps labels to actions, and surfaces the console link.

### Parameters

- **web_acl_name**, **web_acl_id**, **scope** (required): Identify the web ACL.
- **rule_groups** (required): `ATP`, `ACFP`, or both.
- **login_path** (required for ATP): The login endpoint path.
- **registration_path** and **creation_path** (required for ACFP): The signup paths.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm the application integration SDK is integrated and logging is on

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm the SDK is integrated and logging and sampling are on
- You SHOULD confirm whether the resource is CloudFront (response inspection) or an ALB (request
  inspection only)

#### 2. Add the rule groups in Count mode

**Constraints:**

- You MUST add ATP with the login path, and ACFP with both the registration and creation paths,
  configuring request inspection for the username, password, and (ACFP) email fields
- You MUST configure response inspection only on a CloudFront web ACL
- You MUST fetch the current `LockToken` before `update-web-acl` and pass the full rule set
- You MUST preserve the web ACL's existing `DefaultAction` from the `get-web-acl` response and pass
  it back as `{default_action}`; do not assume `Allow={}`, since that would silently open all
  unmatched traffic on a web ACL whose default action is `Block`. For example, adding ATP with
  request inspection on the login path:

  ```
  aws wafv2 get-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} --region {region}
  aws wafv2 update-web-acl --name {web_acl_name} --scope {scope} --id {web_acl_id} \
    --lock-token {lock_token} --default-action {default_action} \
    --rules '[{"Name":"AWS-ATP","Priority":1,"Statement":{"ManagedRuleGroupStatement":{"VendorName":"AWS","Name":"AWSManagedRulesATPRuleSet","ManagedRuleGroupConfigs":[{"AWSManagedRulesATPRuleSet":{"LoginPath":"{login_path}","RequestInspection":{"PayloadType":"JSON","UsernameField":{"Identifier":"/username"},"PasswordField":{"Identifier":"/password"}}}}]}},"OverrideAction":{"Count":{}},"VisibilityConfig":{"SampledRequestsEnabled":true,"CloudWatchMetricsEnabled":true,"MetricName":"AWS-ATP"}}]' \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName={web_acl_name} \
    --region {region}
  ```

  ACFP uses `AWSManagedRulesACFPRuleSet` with `RegistrationPagePath`, `CreationPath`, and its own
  `RequestInspection` (including the email field); add a `ResponseInspection` block only on a
  CloudFront web ACL

#### 3. Review and map labels to actions

**Constraints:**

- You MUST review the Count-mode labels (such as the compromised-credential label) before enforcing
- You MUST map labels to actions and switch to enforcement once validated

#### 4. Surface the console link

**Constraints:**

- You MUST present the web ACL console link and tell the customer to confirm the Fraud Control rules
  and their actions:

  ```
  https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region={region}
  ```

### Example

#### Example input

```json
{
  "web_acl_name": "example-cf-webacl",
  "web_acl_id": "abc",
  "scope": "CLOUDFRONT",
  "rule_groups": ["ATP"],
  "login_path": "/api/login"
}
```

#### Example output

```
Confirmed the SDK is integrated and the resource is CloudFront, so response inspection is available.
Added ATP on /api/login with request and response inspection, in Count.
Reviewed labels, mapped the compromised-credential label to Block, then enforced.
Open the web ACL and confirm the Fraud Control rules:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### Credential stuffing gets through
Rate limiting misses it. Add ATP (Step 2).

#### Response rules never fire on an ALB
Response inspection is CloudFront only. Front the ALB with CloudFront (Step 1).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.

## Additional Resources

- [AWS WAF Fraud Control account takeover prevention (ATP) rule group (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-atp.html)
- [AWS WAF Fraud Control account creation fraud prevention (ACFP) rule group (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-acfp.html)
- [ATP example: Response inspection configuration (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-atp-control-example-response-inspection.html)
- [Testing and tuning your AWS WAF protections (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/web-acl-testing.html)
