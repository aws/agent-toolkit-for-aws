# Subscribing to Shield Advanced and Protecting Resources

## Overview

Domain expertise for starting with AWS Shield Advanced: subscribing an account and then explicitly
adding resources to protection. Covers the per-account subscription model, the consolidated billing
rules customers most often ask about, the load-bearing fact that subscribing protects nothing on
its own, and the auto-renewal and unsubscribe behavior that surprises customers later.

Does not cover automatic application layer mitigation, health-based detection, SRT setup, event review, or
protection groups; those are separate references. Authoring AWS WAF rules is the waf skill. Rolling
Shield Advanced out across an organization with Firewall Manager is the firewallmanager skill.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. Shield Advanced control-plane calls run in
`us-east-1`; pass `--region us-east-1` on every command.

## Table of Contents

- Overview
- Workflow
- Decision: which resource type to protect
- Subscribing protects nothing on its own
- Billing model
- Auto-renewal and unsubscribe
- Troubleshooting
- Security considerations
- Procedure
- Additional Resources

## Workflow

To subscribe and protect resources end to end, follow the procedure exactly. See the Procedure
section below.

The procedure covers:

- Subscribing the account that owns the resources to protect
- Confirming the subscription is active
- Adding each resource to protection by its ARN
- Surfacing the console link to verify protected resources

## Decision: which resource type to protect

| Resource type | Notes |
| --- | --- |
| CloudFront distribution | Protect here for web applications; also the place to protect an Application Load Balancer that sits behind CloudFront |
| Application Load Balancer | Protect at the load balancer when it is not behind CloudFront |
| Network Load Balancer | Protect through an attached Elastic IP address, not the load balancer directly |
| Elastic IP address | Protects the attached EC2 instance or Network Load Balancer |
| Global Accelerator standard accelerator | Protect the accelerator directly |
| Route 53 hosted zone | Protect the hosted zone directly; note it does not support health-based detection |

**Constraints:**

- You MUST protect a Network Load Balancer or EC2 instance through an Elastic IP address where the
  resource model requires it, rather than expecting to protect the instance directly
- You SHOULD protect at the CloudFront distribution when an Application Load Balancer sits behind
  CloudFront, since that is where edge mitigation applies

## Subscribing protects nothing on its own

A subscription enables Shield Advanced for the account, but no resource is protected until it is
added explicitly. Customers assume subscribing covers everything in the account and discover during
or after an attack that nothing was protected.

**Constraints:**

- You MUST treat adding resources as a required second step right after subscribing, not an
  optional follow-up
- You MUST confirm at least one resource is protected before telling the customer they are covered

## Billing model

The billing model is the most common Shield Advanced question and customers regularly overpay or
hold back out of confusion about it.

**Constraints:**

- You MUST explain that one subscription fee covers all subscribed accounts in the same AWS
  Organizations consolidated billing family, charged once to the payer account
- You MUST tell the customer each account that owns protected resources still calls
  `create-subscription` individually, even though only one fee is charged
- You SHOULD note the payer account itself does not need to be subscribed, since billing routes to
  the payer regardless
- You SHOULD state that the subscription includes standard AWS WAF costs (web ACL, rules, and
  request inspection up to 1,500 web ACL capacity units) for Shield-protected resources, while Bot
  Control, CAPTCHA, and usage above 1,500 web ACL capacity units are not included
- You MUST NOT invent a dollar figure for the subscription fee; point the customer at the current
  Shield pricing page

## Auto-renewal and unsubscribe

The subscription is a commitment that auto-renews, and there is no self-service unsubscribe. A
customer who does not know this is surprised at renewal.

**Constraints:**

- You MUST state before the customer subscribes that the subscription auto-renews by default and
  that fully unsubscribing requires contacting AWS Support
- You SHOULD note auto-renewal can be disabled, but that disabling renewal is not the same as
  cancelling the current term

## Troubleshooting

### Subscribed but a resource is still unprotected
Subscribing does not protect anything. Add the resource with `create-protection` for its ARN
(Procedure).

### `create-protection` fails with an invalid parameter
The resource may already be protected, or the ARN format is wrong (an Elastic IP address uses the
allocation-id ARN form). Confirm with `list-protections` and correct the ARN.

### Customer fears duplicate monthly fees across accounts
One fee covers the whole consolidated billing family, charged to the payer. Each account still
subscribes individually (Billing model).

### A Network Load Balancer cannot be protected directly
Protect it through an attached Elastic IP address (Decision: which resource type to protect).

## Security considerations

Subscribing and protecting resources commits the account to a billing term and changes account-wide
protection, so call out the risks and the controls that contain them.

- **Least privilege for the operator.** Scope the caller's IAM permissions to the minimum this
  procedure needs (`shield:CreateSubscription`, `shield:GetSubscriptionState`,
  `shield:CreateProtection`, `shield:ListProtections`) rather than broad Shield or administrator
  access.
- **Audit trail.** Keep AWS CloudTrail enabled and logging `shield:*` calls so every subscription and
  protection change leaves a record, and confirm the CloudTrail trail uses SSE-KMS encryption on its
  S3 log bucket and CloudWatch Logs log group, since CloudTrail records contain sensitive API
  metadata (caller identities, resource ARNs, parameters).
- **The subscription auto-renews.** The subscription auto-renews by default and fully unsubscribing
  requires contacting AWS Support; review the subscription's necessity periodically so the account is
  not committed beyond what it needs.
- **Role-based access control.** Limit who can subscribe accounts and add protections to authorized
  personnel through role-based access control rather than granting it broadly.

## Procedure

### Overview

This procedure subscribes an account to Shield Advanced and adds one or more resources to
protection, then surfaces the console link to verify coverage.

### Parameters

- **account** (required): The AWS account that owns the resources to protect. Each owning account
  must be subscribed.
- **resource_arns** (required): The ARNs of the resources to protect (CloudFront distribution,
  Application Load Balancer, Network Load Balancer via Elastic IP, Elastic IP address, Global
  Accelerator accelerator, or Route 53 hosted zone).
- **protection_names** (required): A descriptive name for each protection.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST confirm each resource ARN exists and is owned by a subscribed account before protecting

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You SHOULD use temporary credentials from an assumed IAM role (for example via IAM Identity Center
  or an instance profile) rather than long-lived IAM user access keys for these security-sensitive
  Shield Advanced operations
- You MUST confirm the account owning the resources is the one being subscribed
- You SHOULD scope the caller's IAM permissions to the minimum this procedure needs
  (`shield:CreateSubscription`, `shield:GetSubscriptionState`, `shield:CreateProtection`,
  `shield:ListProtections`) rather than broad Shield or administrator access
- You SHOULD confirm AWS CloudTrail is enabled and logging `shield:*` calls so every Shield Advanced
  configuration change leaves an audit trail
- You SHOULD confirm the CloudTrail trail is configured with SSE-KMS encryption on its S3 log bucket
  and CloudWatch Logs log group, since CloudTrail records contain sensitive API metadata (caller
  identities, resource ARNs, parameters)

#### 2. Subscribe the account

**Constraints:**

- You MUST tell the customer the subscription auto-renews and that unsubscribing requires AWS
  Support before they commit
- You MUST subscribe the account before adding any protection:

  ```
  aws shield create-subscription --region us-east-1
  ```

- You MUST confirm the subscription is active:

  ```
  aws shield get-subscription-state --region us-east-1
  ```

#### 3. Add each resource to protection

**Constraints:**

- You MUST create a protection for each resource ARN:

  ```
  aws shield create-protection --name {protection_name} --resource-arn {resource_arn} --region us-east-1
  ```

- You MUST capture the `ProtectionId` from each response
- You MUST NOT consider the account protected until at least one protection exists
- You SHOULD recommend associating an AWS WAF web ACL with every internet-facing protected resource
  (CloudFront distributions and Application Load Balancers) as defense in depth — Shield Advanced
  (layer 3/4) and AWS WAF (layer 7) are complementary, and a rate-based AWS WAF rule is also what
  cost protection eligibility later requires — and point to the waf skill to set it up

#### 4. Confirm and surface the console link

**Constraints:**

- You MUST list protections to confirm coverage:

  ```
  aws shield list-protections --region us-east-1
  ```

- You MUST present the Shield protected-resources console link and tell the customer to open it and
  confirm the resources are listed as protected:

  ```
  https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/protections
  ```

### Example

#### Example input

```json
{
  "account": "111122223333",
  "resource_arns": ["arn:aws:cloudfront::111122223333:distribution/EDFDVBD6EXAMPLE"],
  "protection_names": ["my-app-distribution"]
}
```

#### Example output

```
Subscribed account 111122223333 to Shield Advanced (auto-renews; unsubscribe via AWS Support).
Protected: my-app-distribution -> arn:aws:cloudfront::111122223333:distribution/EDFDVBD6EXAMPLE
Open the Shield console and confirm the resource is listed as protected:
https://us-east-1.console.aws.amazon.com/wafv2/shieldv2#/protections
```

### Troubleshooting

#### Subscribed but the resource is still unprotected
Subscribing does not protect anything. Add the resource with `create-protection` (Step 3).

#### `create-protection` fails with an invalid parameter
The resource may already be protected, or the ARN format is wrong. Confirm with `list-protections`
and correct the ARN.

#### A Network Load Balancer cannot be protected directly
Protect it through an attached Elastic IP address (Decision: which resource type to protect).

## Additional Resources

- [Subscribing to AWS Shield Advanced (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/enable-ddos-prem.html)
- [Adding and configuring resource protections with Shield Advanced (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-choose-resources.html)
- [Adding AWS Shield Advanced protection to AWS resources (AWS WAF, AWS Firewall Manager, and AWS Shield Advanced Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/configure-new-protection.html)
- [AWS Shield Advanced pricing](https://aws.amazon.com/shield/pricing/)
