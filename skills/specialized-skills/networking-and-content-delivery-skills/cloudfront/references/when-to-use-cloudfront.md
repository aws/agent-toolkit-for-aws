# When to Use CloudFront, and How It Fits the Architecture

## Overview

Domain expertise for deciding whether Amazon CloudFront is the right entry layer for a workload,
what it integrates with, how to create a first distribution and choose the origin, how caching
works, when edge logic belongs in CloudFront Functions versus Lambda@Edge, and how to choose
between pay-as-you-go and Flat Rate Pricing (FRP).

CloudFront is a global content delivery network of hundreds of edge locations worldwide that does three jobs at
once: it accelerates delivery by caching and terminating viewer connections close to users, it
absorbs and blocks Layer 3/4 distributed denial-of-service (DDoS) attacks at the edge, and it
is the attachment point for the edge security and compute stack (AWS WAF, AWS Shield, CloudFront
Functions, Lambda@Edge, Amazon Route 53, AWS Certificate Manager, and origins). It serves more
than media: cacheable static assets, dynamic web pages, REST and GraphQL APIs, and large file
downloads all run through it. For dynamic traffic and APIs, CloudFront improves performance
through TLS termination closer to the end user, persistent connection pooling to origins (reducing
TCP/TLS handshake overhead), and optimized network paths between edge locations and origins.

Every standard CloudFront distribution is assigned a default domain name (e.g.,
d111111abcdef8.cloudfront.net) that can be used immediately for testing without configuring a
custom domain or certificate. Multi-tenant distributions do not have a default test domain.

Does not cover locking the origin (see protecting-your-origins), restricting who can view content
(see securing-your-content), custom domains and certificates (see
managing-certificates-with-cloudfront), logging and analysis (see cloudfront-observability), or the
Route 53 DNS cutover (owned by the route53-cloudfront skill).

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. CloudFront is a global service; its API calls
and ACM certificates are made in `us-east-1` regardless of where the application runs.

## Table of Contents

- Overview
- Decision: is CloudFront the right layer
- Decision: origin type
- Decision: CloudFront Functions vs Lambda@Edge
- Caching: cache behaviors and cache policies
- Decision: pay-as-you-go vs Flat Rate Pricing (FRP)
- Procedure
- Troubleshooting
- Security Considerations
- Additional Resources

## Decision: is CloudFront the right layer

| Signal | CloudFront fit |
| --- | --- |
| Cacheable or static content, or dynamic web and API traffic to accelerate | Yes. Caching and edge termination reduce latency and origin load |
| Need Layer 3/4 DDoS absorption and Layer 7 filtering at the edge | Yes. Shield is built in; AWS WAF attaches to the distribution |
| HTTP and HTTPS only | Yes. For non-HTTP (TCP/UDP) entry, use Global Accelerator instead |
| Static IP entry point partners allowlist, or sub-minute failover | No. Use Global Accelerator |

**Constraints:**

- You MUST recognize web, API, and download workloads as valid CloudFront use cases, not just media
- You MUST explain that CloudFront is the attachment point for AWS WAF, Shield, CloudFront
  Functions, Lambda@Edge, Route 53, and the ACM certificate, so the edge is designed once
- You SHOULD redirect non-HTTP protocols, static-IP entry, or sub-minute failover needs to Global
  Accelerator

## Decision: origin type

| Origin | Approach |
| --- | --- |
| Amazon S3 bucket (private) | Standard bucket origin with origin access control (default). See protecting-your-origins |
| Amazon S3 that must also be public outside CloudFront | S3 website endpoint as a custom origin (exception only) |
| ALB, NLB, or EC2 in a private subnet | VPC origin. See protecting-your-origins |
| Public or on-premises HTTP origin | Custom origin, optionally with origin mutual TLS. See protecting-your-origins |

**Constraints:**

- You MUST default an S3 origin to a standard bucket origin with origin access control, reserving
  the website endpoint for when the site must also be public outside CloudFront
- You MUST surface VPC origins for an ALB, NLB, or EC2 origin in a private subnet rather than
  advising a move to a public subnet

## Decision: CloudFront Functions vs Lambda@Edge

| Need | Choose |
| --- | --- |
| Lightweight viewer-facing transform: URL rewrite, header manipulation, redirect, token check | CloudFront Functions (viewer-request, viewer-response; sub-millisecond) |
| Network access, or origin-request / origin-response events, or a larger runtime | Lambda@Edge (higher latency and cost) |

**Constraints:**

- You MUST match the customer's edge logic to the right tool: CloudFront Functions run only on
  viewer-request and viewer-response events
- You MUST route logic that needs network access or origin-facing events to Lambda@Edge
- You MUST publish a CloudFront function to the LIVE stage before it can be associated with a
  distribution

## Caching: cache behaviors and cache policies

A cache policy holds the time to live (TTL) values and the cache-key definition; the cache behavior
points at the policy. TTLs are set on the policy, not directly on the behavior.

**Constraints:**

- You MUST attach a cache policy to the behavior and explain the policy, not the behavior, holds the
  TTLs and cache key
- You SHOULD reach for a managed cache policy for standard cases and reserve custom policies for
  when the cache key truly differs
- You MUST warn that a minimum TTL above zero overrides origin `no-cache`, `no-store`, and `private`
  directives for at least that duration
- You SHOULD add path-pattern cache behaviors (the default behavior is evaluated last) when rules
  differ per path, for example a long-TTL policy on `*.jpg` and a no-cache policy on `/api/*`

## Decision: pay-as-you-go vs Flat Rate Pricing (FRP)

| Option | Use when |
| --- | --- |
| Pay-as-you-go (per distribution) | Variable or low traffic; want granular per-dimension billing |
| Flat Rate Pricing (FRP) | Predictable, sustained high-volume traffic with a minimum monthly commitment; lower per-GB rates than pay-as-you-go with a fixed monthly commitment and overage at pay-as-you-go rates |

**Constraints:**

- You SHOULD surface FRP when the customer describes sustained, predictable
  high-volume traffic, and point them to the CloudFront pricing page or their AWS account team for
  the current minimum monthly commitment rather than quoting a specific threshold (commitment levels
  can change)
- You MUST note customers can move existing resources to FRP through the CloudFront console
- You MUST note FRP includes a fixed monthly commitment with overage charged at pay-as-you-go rates
- You SHOULD note FRP coexists with pay-as-you-go, which stays available per distribution

## Procedure

### Overview

This procedure creates a distribution, chooses the origin, sets the cache behavior, optionally
chooses a pricing plan, and surfaces the console link to verify.

### Parameters

- **origin_domain** (required): The origin (S3 bucket, ALB/NLB/EC2, or custom HTTP origin).
- **origin_type** (required): `s3`, `vpc-origin`, or `custom`.
- **default_root_object** (optional): For example `index.html`.

**Constraints for parameter acquisition:**

- You MUST ask for the origin and its type upfront
- You MUST confirm whether the workload needs non-HTTP protocols before recommending CloudFront

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm CloudFront is the right layer (HTTP/HTTPS, caching or edge security value)

#### 2. Create the distribution and choose the origin

**Constraints:**

- You MUST create the distribution with the chosen origin and let CloudFront set the default cache
  behavior. For an S3 origin you MUST first create an origin access control (OAC) — see
  protecting-your-origins for the `create-origin-access-control` call — and reference its id via
  `OriginAccessControlId` in the create call below (replace `{oac_id}`), so the origin is locked from
  the start rather than created reachable-and-then-hardened. Do not embed a static managed cache
  policy id; look up the current `Managed-CachingOptimized` policy by name and use its id for
  `CachePolicyId` (managed policy ids can change):

  ```
  # resolve the managed CachingOptimized cache policy id (do not hardcode a UUID):
  aws cloudfront list-cache-policies --type managed \
    --query "CachePolicyList.Items[?CachePolicy.CachePolicyConfig.Name=='Managed-CachingOptimized'].CachePolicy.Id | [0]" --output text
  aws cloudfront create-distribution --distribution-config '{"CallerReference":"dist-2024-01","Comment":"","Origins":{"Quantity":1,"Items":[{"Id":"s3-origin","DomainName":"{origin_domain}","OriginAccessControlId":"{oac_id}","S3OriginConfig":{"OriginAccessIdentity":""}}]},"DefaultCacheBehavior":{"TargetOriginId":"s3-origin","ViewerProtocolPolicy":"redirect-to-https","CachePolicyId":"{cache_policy_id}"},"DefaultRootObject":"index.html","Enabled":true}'
  ```

- You MUST default an S3 origin to a standard bucket origin and complete origin locking via the
  protecting-your-origins workflow: attach the OAC referenced above, write the scoped bucket policy,
  and keep S3 Block Public Access on, so the origin is never reachable directly
- You MUST enable standard logging on the distribution immediately after creation (it is not set by
  the create call above), since without it there is no audit or forensic trail; see the
  cloudfront-observability reference for the logging configuration
- You MUST set the viewer protocol policy to redirect-HTTP-to-HTTPS (or HTTPS-only) and the origin
  protocol policy to HTTPS-only for custom origins, ensuring encryption in transit end-to-end
- You SHOULD recommend attaching an AWS WAF web ACL with baseline rules (the AWS Managed Rules Core
  Rule Set and Known Bad Inputs rule group) to any public-facing distribution for Layer 7 defense
  in depth
- You SHOULD attach an AWS WAF rate-based rule for API origins, since CloudFront caching does not
  shield an origin from unthrottled dynamic or API requests
- You MUST attach a response headers policy with browser security headers (HSTS, CSP,
  X-Frame-Options, X-Content-Type-Options) as a secure default; the AWS managed
  `SecurityHeadersPolicy` is a starting point
- You MUST capture the distribution ID and the assigned `cloudfront.net` domain from the response

#### 3. Tune caching if rules differ per path

**Constraints:**

- You SHOULD attach a managed cache policy for the default behavior and add path-pattern behaviors
  only when the customer needs different rules per path
- You MUST keep the minimum TTL at zero unless the customer has a reason to force caching past
  origin directives

#### 4. Choose a pricing model if asked

**Constraints:**

- You SHOULD present FRP when the customer raises cost predictability or attack
  exposure, otherwise leave pay-as-you-go in place

#### 5. Wait for deployment and surface the console link

**Constraints:**

- You MUST set the expectation that the distribution must reach `Deployed` across edge locations
  before it serves content, so errors on the `cloudfront.net` URL right after creation are expected
- You MUST present the distribution detail console link, filling `{distributionId}` from the API
  response:

  ```
  https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/{distributionId}
  ```

### Example

#### Example input

```json
{
  "origin_domain": "my-private-site.s3.us-east-1.amazonaws.com",
  "origin_type": "s3",
  "default_root_object": "index.html"
}
```

#### Example output

```
Created distribution E1ABCDEF2GHIJK with a standard S3 origin and a managed cache policy on the default behavior.
Distribution is deploying; the cloudfront.net URL returns errors until it reaches Deployed.
Verify in the console:
https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/E1ABCDEF2GHIJK
```

## Troubleshooting

### The cloudfront.net URL returns errors right after creation
The distribution has not finished deploying across edge locations. Wait for `Deployed` status, then
test again.

### The S3 origin serves errors or is publicly reachable
The origin type or locking is wrong. Default to a standard bucket origin with origin access control
(see protecting-your-origins), not a website endpoint.

### Cannot find the per-file TTL fields on the cache behavior
TTLs and the cache key live on a cache policy the behavior points at, not on the behavior itself.
Attach a cache policy and set the TTLs there.

### CloudFront keeps serving stale content despite origin no-cache headers
A minimum TTL above zero overrides origin `no-cache`, `no-store`, and `private` directives. Set the
minimum TTL to zero.

### A function association fails right after writing the code
A CloudFront function must be published to the LIVE stage before it can be associated. Publish it
first.

### The workload needs UDP or a static IP entry point
CloudFront serves HTTP and HTTPS only. Use Global Accelerator for non-HTTP protocols, a static-IP
entry point, or sub-minute failover.

## Security Considerations

- **Enable logging from creation.** Without standard logging there is no audit or forensic trail for
  the distribution; enable it at creation time (see cloudfront-observability).
- **Rate-limit API origins.** Caching does not protect an origin from unthrottled dynamic or API
  traffic; attach an AWS WAF rate-based rule to API distributions.
- **Enforce a minimum TLS version.** Set the viewer protocol policy to redirect-HTTP-to-HTTPS (or
  HTTPS-only) and, when adding a custom domain, set the minimum protocol version to a current strong
  TLS 1.2-or-higher security policy rather than relying on the default — choose the newest TLS 1.2+
  policy CloudFront offers rather than a hardcoded string (see managing-certificates-with-cloudfront).
- **Do not leave the origin unlocked.** A distribution whose origin is directly reachable lets
  viewers bypass the edge entirely; lock the origin (see protecting-your-origins).
- **Audit the management plane with CloudTrail.** Request access logs do not record who changed the
  distribution. Enable AWS CloudTrail to track CloudFront management API calls
  (`cloudfront:CreateDistribution`, `cloudfront:UpdateDistribution`) for a compliance and forensic
  audit trail.

## Additional Resources

- [What is Amazon CloudFront? (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Introduction.html)
- [Create a distribution (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/distribution-web-creating-console.html)
- [Use various origins with CloudFront distributions (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/DownloadDistS3AndCustomOrigins.html)
- [Cache behavior settings (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/DownloadDistValuesCacheBehavior.html)
- [Use managed cache policies (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/using-managed-cache-policies.html)
- [Customize at the edge with CloudFront Functions and Lambda@Edge (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/edge-functions.html)
- [CloudFront flat-rate pricing plans (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/flat-rate-pricing-plan.html)
