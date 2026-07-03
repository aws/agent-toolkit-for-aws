# Creating a Web ACL and Associating It with a Resource

## Overview

Domain expertise for putting AWS WAF in front of an application: creating a web access control list
(web ACL) and associating it with the resource it protects. Covers the immutable scope choice
(`CLOUDFRONT` in `us-east-1` versus `REGIONAL` in the resource's Region), the fact that a web ACL
filters nothing until it is associated, the one-web-ACL-per-resource and CloudFront-only
constraints, and starting rules in Count mode.

Does not cover the rules that go inside the web ACL (managed rules, rate-based, match, bot, fraud);
those are separate references. CloudFront distribution and Application Load Balancer configuration
are their own skills.

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Workflow
- Decision: scope
- Least-privilege IAM
- A web ACL filters nothing until associated
- One web ACL per resource, CloudFront is exclusive
- Start rules in Count mode
- Troubleshooting
- Procedure
- Security Considerations
- Additional Resources

## Workflow

To create a web ACL and associate it end to end, follow the procedure exactly. See the Procedure
section below.

The procedure covers:

- Choosing the scope from the resource type
- Creating the web ACL with a default action
- Associating it with the resource
- Confirming the association and surfacing the console link

## Decision: scope

| Resource | Scope | Region |
| --- | --- | --- |
| CloudFront distribution | `CLOUDFRONT` | `us-east-1` (required) |
| Application Load Balancer, API Gateway REST API, AppSync GraphQL API, Cognito user pool, App Runner, Verified Access, Amplify | `REGIONAL` | the resource's own Region |

**Constraints:**

- You MUST set the scope from the resource type before creating the web ACL; scope is immutable
  after creation
- You MUST create a `CLOUDFRONT` web ACL in `us-east-1` regardless of where the distribution serves
- You MUST create a `REGIONAL` web ACL in the same Region as the resource it protects

## Least-privilege IAM

The credentials that run these commands should carry only the WAF actions the task needs, not broad
access.

**Constraints:**

- You MUST grant only the specific `wafv2:` actions these procedures use — for the entry-point
  workflow that is `wafv2:CreateWebACL`, `wafv2:GetWebACL`, `wafv2:UpdateWebACL`, and
  `wafv2:AssociateWebACL` — rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy
- You SHOULD extend the same least-privilege approach to the other references (for example
  `wafv2:PutLoggingConfiguration` for logging, `wafv2:CreateIPSet`/`wafv2:UpdateIPSet` for IP sets),
  granting only what each task requires
- You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session,
  or `aws sts assume-role`) rather than long-lived IAM user access keys when running these commands

## A web ACL filters nothing until associated

A web ACL inspects no traffic until it is associated with a resource. Customers finish the web ACL
and assume traffic is filtered.

**Constraints:**

- You MUST treat the association as a required closing step, not optional
- You MUST confirm the resource is associated before reporting the setup complete

## One web ACL per resource, CloudFront is exclusive

Each resource can have only one web ACL, and a web ACL associated with a CloudFront distribution
cannot be associated with any other resource type. Customers design around a shared web ACL that
cannot exist.

**Constraints:**

- You MUST NOT associate more than one web ACL with a single resource
- You MUST NOT reuse a CloudFront-associated web ACL on a regional resource
- You SHOULD explain these constraints before the customer designs a shared web ACL

## Start rules in Count mode

Enabling rules straight to Block can take down legitimate traffic. The recommended path for a first
web ACL is Count, then Block after review.

**Constraints:**

- You SHOULD start new rules in Count mode and move them to Block only after the customer reviews
  the matches
- You SHOULD confirm logging is set up first so Count-mode matches are reviewable

## Troubleshooting

### A CloudFront distribution does not appear in the association list
The web ACL was created in the wrong scope or Region. Recreate it as `CLOUDFRONT` scope in
`us-east-1` (Decision: scope).

### Rules are configured but traffic is not filtered
The web ACL is not associated with the resource. Associate it (A web ACL filters nothing until
associated).

### A web ACL cannot be reused across CloudFront and a regional resource
CloudFront web ACLs are exclusive and each resource takes one web ACL. Create separate web ACLs
(One web ACL per resource, CloudFront is exclusive).

## Procedure

### Overview

This procedure creates a web ACL in the correct scope, associates it with the resource, and
surfaces the console link to verify.

### Parameters

- **web_acl_name** (required): A name for the web ACL.
- **resource_arn** (required): The ARN of the resource to protect.
- **scope** (required): `CLOUDFRONT` or `REGIONAL`, derived from the resource type.
- **default_action** (required): `Allow` or `Block` when no rule matches. Set this deliberately to
  match the intended posture; an `Allow` default passes any traffic not matched by a rule through
  unfiltered, so prefer `Block` as the secure default and use `Allow` only when explicit blocking
  rules carry the enforcement.

**Constraints for parameter acquisition:**

- You MUST ask for all required parameters upfront in a single prompt
- You MUST derive the scope and Region from the resource type, not from the customer's working
  Region

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm the resource exists in the expected Region

#### 2. Create the web ACL

**Constraints:**

- You MUST create the web ACL in the correct scope and Region:

  ```
  aws wafv2 create-web-acl --name {web_acl_name} --scope {scope} \
    --default-action {default_action}={} \
    --visibility-config SampledRequestsEnabled=true,CloudWatchMetricsEnabled=true,MetricName={web_acl_name} \
    --region {region}
  ```

- You MUST capture the web ACL ARN and id from the response

#### 3. Associate the web ACL with the resource

**Constraints:**

- You MUST associate the web ACL with the resource ARN:

  ```
  aws wafv2 associate-web-acl --web-acl-arn {web_acl_arn} --resource-arn {resource_arn} --region {region}
  ```

- You MUST NOT consider the setup complete until the association succeeds

#### 4. Confirm and surface the console link

**Constraints:**

- You MUST confirm the association and present the AWS WAF console link, telling the customer to
  open it and confirm the web ACL and its associated resource:

  ```
  https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region={region}
  ```

### Example

#### Example input

```json
{
  "web_acl_name": "example-frontend-webacl",
  "resource_arn": "arn:aws:cloudfront::111122223333:distribution/EDFDVBD6EXAMPLE",
  "scope": "CLOUDFRONT",
  "default_action": "Block"
}
```

(`Block` is the secure default — unmatched requests are denied, and Allow rules admit the
traffic you intend. Use `"default_action": "Allow"` only when the customer explicitly wants an
allow-by-default web ACL whose rules do the blocking.)

#### Example output

```
Created CLOUDFRONT web ACL example-frontend-webacl in us-east-1 with default action Block.
Associated it with distribution EDFDVBD6EXAMPLE.
Open the AWS WAF console and confirm the web ACL and its associated resource:
https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls?region=us-east-1
```

### Troubleshooting

#### The distribution is missing from the association list
The web ACL is in the wrong scope or Region. Recreate as `CLOUDFRONT` in `us-east-1` (Step 2).

#### Traffic is not being filtered
The web ACL is not associated. Associate it (Step 3).

## Security Considerations

This procedure modifies a security control, so misconfiguration directly weakens the application's defenses.

- **Least-privilege IAM.** You MUST grant only the specific `wafv2:` actions a task needs (for example `wafv2:GetWebACL` and `wafv2:UpdateWebACL`) rather than `wafv2:*` or the `AWSWAFFullAccess` managed policy.
- **Ephemeral credentials.** You MUST use IAM roles with temporary credentials (such as an EC2 instance profile, SSO session, or `aws sts assume-role`) rather than long-lived IAM user access keys when running these WAF CLI commands.
- **Monitor configuration changes.** You SHOULD enable AWS CloudTrail on `wafv2` management events and set CloudWatch alarms on critical web ACL configuration changes (such as `DeleteWebACL` and `UpdateWebACL` rule removals) and on the web ACL's `BlockedRequests` and `CountedRequests` metrics, so rule changes and sudden spikes in blocked or counted traffic are detected.

## Additional Resources

- [Resources that you can protect with AWS WAF (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/how-aws-waf-works-resources.html)
- [Creating a web ACL in AWS WAF (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/web-acl-creating.html)
- [Associating or disassociating protection with an AWS resource (AWS WAF Developer Guide)](https://docs.aws.amazon.com/waf/latest/developerguide/web-acl-associating-aws-resource.html)
