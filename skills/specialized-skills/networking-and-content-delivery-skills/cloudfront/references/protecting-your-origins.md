# Protecting Your Origins

## Overview

Domain expertise for making CloudFront the only way to reach an origin, so viewers cannot bypass
the edge by hitting the origin directly. The right mechanism depends on the origin type, and the
three combine to cover the full catalog:

- Amazon S3 origin: origin access control (OAC) plus a scoped bucket policy and Block Public Access.
- ALB, NLB, or EC2 in a private subnet: a VPC origin plus a security group that allows the
  CloudFront managed prefix list or service-managed security group.
- Public, on-premises, or other-cloud origin: origin mutual TLS (origin mTLS), where CloudFront
  presents a client certificate the origin validates.

Does not cover restricting which viewers can see content (see securing-your-content), creating the
distribution (see when-to-use-cloudfront), or custom domains (see
managing-certificates-with-cloudfront).

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Decision: which origin-locking mechanism
- S3 origin: OAC, scoped bucket policy, Block Public Access
- Private ALB, NLB, or EC2: VPC origins and security groups
- Security groups as a lighter alternative to VPC origins
- Public or hybrid origin: origin mutual TLS
- Procedure
- Troubleshooting
- Security Considerations
- Additional Resources

## Decision: which origin-locking mechanism

| Origin | Mechanism |
| --- | --- |
| Private Amazon S3 bucket | Origin access control (OAC) + scoped bucket policy + Block Public Access |
| ALB, NLB, or EC2 in a private subnet | VPC origin + security group referencing the CloudFront managed prefix list or service-managed security group |
| Public, on-premises, or other-cloud HTTP origin | Origin mutual TLS (CloudFront presents a client certificate) |

**Constraints:**

- You MUST pick the mechanism by origin type; they are not interchangeable
- You MAY combine mechanisms, for example a VPC origin and origin mTLS, when an origin needs both

## S3 origin: OAC, scoped bucket policy, Block Public Access

**Constraints:**

- You MUST default to origin access control (OAC), not origin access identity (OAI). OAI does not
  cover all Regions, server-side encryption with AWS KMS, or write requests. Reserve OAI for
  migrating an older setup
- You MUST create the OAC set to always sign and attach it to the S3 origin
- You MUST write the bucket policy together with the OAC, allowing `cloudfront.amazonaws.com` scoped
  to the specific distribution with both `AWS:SourceArn` and `AWS:SourceAccount` conditions, not a
  broad grant
- You MUST keep S3 Block Public Access fully on
- You SHOULD enable default encryption (SSE-S3 or SSE-KMS) on the S3 bucket. If using SSE-KMS, the
  KMS key policy MUST grant `kms:Decrypt` (and `kms:GenerateDataKey*` for writes) to the
  `cloudfront.amazonaws.com` service principal, scoped to the distribution ARN with both
  `AWS:SourceArn` and `AWS:SourceAccount` conditions, so CloudFront can read the encrypted objects
- You MUST confirm the origin is a standard S3 bucket, not a website endpoint, which OAC does not
  support

## Private ALB, NLB, or EC2: VPC origins and security groups

**Constraints:**

- You MUST recommend a VPC origin for an ALB, NLB, or EC2 origin in a private subnet rather than
  moving it to a public subnet
- You MUST update the security group on the origin resource to allow inbound traffic from the
  CloudFront managed prefix list or the service-managed security group, not a broad CIDR. Missing
  this rule causes silent failures
- You MUST validate the resource type against the current VPC origins documentation before
  proceeding, rather than relying on a fixed list — supported and unsupported origin types and
  features evolve as the service changes. As examples to verify (not an authoritative list): some
  load-balancer types such as Gateway Load Balancers, dual-stack NLBs, and NLBs with TLS listeners
  have been unsupported, an NLB must have a security group attached, and VPC origins have not
  supported gRPC or Lambda@Edge origin-facing triggers
- You MUST allow time for the VPC origin to deploy (on the order of several minutes); confirm the
  origin reaches a deployed state before relying on it

## Public or hybrid origin: origin mutual TLS

Origin mTLS lets CloudFront authenticate itself to the origin with a client certificate, so the
origin accepts connections only from authorized CloudFront distributions. It replaces brittle IP
allowlists and secret-header schemes for public, on-premises, and other-cloud origins.

**Constraints:**

- You MUST make clear the origin server, not CloudFront, validates the client certificate: the
  origin must request client certificates and hold the issuing CA in its trust store before origin
  mTLS is enabled
- You MUST import the client certificate in ACM and enable origin mTLS per origin (different origins
  can use different certificates)
- You SHOULD use origin mTLS instead of IP allowlists or custom-header secrets for hybrid and
  multi-cloud origins

## Security groups as a lighter alternative to VPC origins

For ALB and NLB origins that must remain in a public subnet (not using VPC origins), the customer
restricts the security group to only allow inbound traffic from CloudFront IP ranges using the
CloudFront managed prefix list. This is simpler but less secure than VPC origins because the origin
still has a public IP.

**Constraints:**

- You SHOULD recommend VPC origins as the more secure default; security group restrictions are a
  fallback when the origin must remain in a public subnet
- You MUST use the CloudFront managed prefix list, not manually maintained CIDR ranges

## Procedure

### Overview

This procedure selects the mechanism by origin type, applies it, and surfaces the console link to
verify.

### Parameters

- **distribution_id** (required): The distribution with the origin.
- **origin_type** (required): `s3`, `vpc-origin`, or `public-custom`.
- **origin_ref** (required): The bucket name, the ALB/NLB/EC2 ARN, or the custom origin domain.
- **account_id** (required for S3): For the bucket-policy source ARN.

**Constraints for parameter acquisition:**

- You MUST ask for the origin type and reference upfront
- You MUST confirm an S3 origin is a standard bucket, not a website endpoint

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm the origin type and, for VPC origins, that the resource type is supported

#### 2a. S3 origin: OAC and scoped bucket policy

**Constraints:**

- You MUST create the OAC set to always sign and attach it to the S3 origin:

  ```
  aws cloudfront create-origin-access-control --origin-access-control-config '{
    "Name": "{origin_ref}-oac", "OriginAccessControlOriginType": "s3",
    "SigningBehavior": "always", "SigningProtocol": "sigv4"
  }'
  ```

- You MUST write the scoped bucket policy and keep Block Public Access on:

  ```
  {"Version":"2012-10-17","Statement":[{"Effect":"Allow",
    "Principal":{"Service":"cloudfront.amazonaws.com"},"Action":"s3:GetObject",
    "Resource":"arn:aws:s3:::{origin_ref}/*",
    "Condition":{"StringEquals":{"AWS:SourceArn":"arn:aws:cloudfront::{account_id}:distribution/{distribution_id}","AWS:SourceAccount":"{account_id}"}}}]}
  ```

  Include both `AWS:SourceArn` and `AWS:SourceAccount` for defense in depth, so the bucket admits
  only the specific distribution in the expected account and a confused-deputy request from another
  account cannot reach the origin.

#### 2b. Private ALB/NLB/EC2: VPC origin and security group

**Constraints:**

- You MUST create the VPC origin from the resource ARN, add it as the distribution origin, and add
  the security group inbound rule referencing the CloudFront managed prefix list or service-managed
  security group

#### 2c. Public or hybrid origin: origin mTLS

**Constraints:**

- You MUST import the client certificate in ACM, confirm the origin is configured to request and
  validate client certificates, then enable origin mTLS on the origin

#### 3. Confirm and surface the console link

**Constraints:**

- You MUST wait for the distribution to reach `Deployed`, then confirm content loads through
  CloudFront and the origin rejects direct access
- You MUST present the distribution detail console link, filling `{distributionId}` from the input
  `distribution_id` parameter:

  ```
  https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/{distributionId}
  ```

### Example

#### Example input

```json
{
  "distribution_id": "E1ABCDEF2GHIJK",
  "origin_type": "vpc-origin",
  "origin_ref": "arn:aws:elasticloadbalancing:us-east-1:111122223333:loadbalancer/app/my-alb/abc",
  "account_id": "111122223333"
}
```

#### Example output

```
Created a VPC origin for the private ALB and added it to E1ABCDEF2GHIJK.
Added an inbound rule on the ALB security group referencing the CloudFront managed prefix list.
Verify in the console:
https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/E1ABCDEF2GHIJK
```

## Troubleshooting

### VPC origin requests fail silently with no error in the logs
The origin security group is missing the inbound rule for the CloudFront managed prefix list or
service-managed security group. Add it.

### Cannot point a VPC origin at a Gateway Load Balancer
Some load-balancer types (for example Gateway Load Balancers, dual-stack NLBs, and NLBs with TLS
listeners) have not been supported as VPC origins; confirm against the current VPC origins
documentation. Use a supported ALB, NLB, or EC2 origin.

### CloudFront returns access denied reaching the S3 bucket
The scoped bucket policy is missing or does not allow `cloudfront.amazonaws.com` for this
distribution. Write the scoped policy.

### OAC does not work on the S3 origin
The origin is a website endpoint. Use a standard S3 bucket origin.

### The origin rejects CloudFront with origin mTLS enabled
The origin server is not configured with the issuing CA in its trust store, or is not requesting
client certificates. Configure the origin to validate the client certificate; CloudFront only
presents it.

## Security Considerations

- **Scope the bucket policy, never broaden it.** Allow `cloudfront.amazonaws.com` scoped to the
  specific distribution with both `AWS:SourceArn` and `AWS:SourceAccount` conditions rather than a
  broad grant, and keep S3 Block Public Access fully on.
- **Scope the KMS key policy for SSE-KMS origins.** Grant `kms:Decrypt` (and `kms:GenerateDataKey*`
  for writes) only to `cloudfront.amazonaws.com`, scoped to the distribution ARN with both
  `AWS:SourceArn` and `AWS:SourceAccount` conditions, not a broad key grant.
- **Prune stale security group rules.** Use the CloudFront managed prefix list or service-managed
  security group; remove manually maintained CIDR rules, which drift and leave the origin reachable
  from unintended ranges.
- **Rotate origin mTLS certificates.** The origin validates the client certificate CloudFront
  presents; track its expiry and rotate ahead of time so origin connections do not break or fall
  back to weaker controls.
- **Audit origin protection changes with CloudTrail.** Enable AWS CloudTrail to record the
  CloudFront, S3, and EC2 management API calls that change origin locking
  (`cloudfront:UpdateDistribution`, `s3:PutBucketPolicy`, `ec2:AuthorizeSecurityGroupIngress`) so
  changes are tracked for a compliance and forensic audit trail.

## Additional Resources

- [Restrict access to an Amazon S3 origin (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)
- [Amazon CloudFront introduces origin access control (OAC) (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/amazon-cloudfront-introduces-origin-access-control-oac/)
- [Restrict access with VPC origins (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html)
- [Introducing CloudFront VPC origins (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/introducing-cloudfront-virtual-private-cloud-vpc-origins-shield-your-web-applications-from-public-internet/)
- [Origin mutual TLS with CloudFront (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/origin-mtls-authentication.html)
- [Amazon CloudFront now supports mTLS authentication to origins (AWS Networking and Content Delivery Blog)](https://aws.amazon.com/blogs/networking-and-content-delivery/amazon-cloudfront-now-supports-mtls-authentication-to-origins/)
