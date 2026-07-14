# Securing Your Content

## Overview

Domain expertise for limiting who can view content served through CloudFront, using four controls
that answer different questions:

- Identity: signed URLs or signed cookies, backed by a trusted key group.
- Location: built-in geographic restrictions, by country, across the whole distribution.
- Client certificate: viewer mutual TLS (viewer mTLS), where the client presents a certificate
  CloudFront validates against a trust store.
- Authorization token: a CloudFront function on the viewer-request event that validates an OAuth
  bearer token or JSON Web Token (JWT) at the edge.

All four only hold if the origin cannot be reached directly. Pair every content control with origin
locking (see protecting-your-origins).

Does not cover locking the origin (see protecting-your-origins), custom domains (see
managing-certificates-with-cloudfront), or creating the distribution (see when-to-use-cloudfront).

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- Decision: which content control
- Identity: signed URLs vs signed cookies
- Location: geographic restrictions
- Client certificate: viewer mutual TLS
- Authorization token: validate at the edge with CloudFront Functions
- Pair every control with origin locking
- Procedure
- Troubleshooting
- Security Considerations
- Additional Resources

## Decision: which content control

| Question | Control |
| --- | --- |
| Is this viewer authorized (paying, licensed)? | Signed URLs or signed cookies |
| Is this viewer in an allowed country? | Geographic restrictions |
| Does this client hold a valid certificate? | Viewer mutual TLS |
| Does this request carry a valid auth token? | CloudFront function on viewer-request |

**Constraints:**

- You MUST ask whether the customer is gating on identity, location, client certificate, or token,
  and route to the matching control rather than letting one stand in for another
- You MAY combine controls; they are independent

## Identity: signed URLs vs signed cookies

| Choice | Use when |
| --- | --- |
| Signed URLs | A single file, or a client without cookie support. Signature, policy, and expiration go in query-string parameters |
| Signed cookies | Many files, or no change to the URL is acceptable. Same data goes in cookies; the URL is unchanged |

**Constraints:**

- You MUST set up trusted key groups on the distribution and have the application issue the signed
  URL or cookies. The legacy CloudFront key pairs approach is deprecated and MUST NOT be used for
  new implementations
- You MUST store the private signing key in AWS Secrets Manager (or AWS Systems Manager Parameter
  Store SecureString), not on disk or in application config, so the key is not exposed
- You MUST match the choice to one file versus many, and to whether any URL change is acceptable

## Location: geographic restrictions

**Constraints:**

- You MUST explain geographic restrictions apply to the whole distribution at the country level, not
  per path
- You SHOULD route per-path or finer-than-country needs to separate distributions or a third-party
  geolocation approach

## Client certificate: viewer mutual TLS

**Constraints:**

- You MUST create the trust store from a PEM CA bundle in S3, then enable viewer mutual
  authentication on the distribution
- You MUST select required mode to reject any client without a valid certificate (optional lets
  unauthenticated clients through; passthrough forwards the raw certificate to the origin)
- You MUST disable HTTP/3 and confirm every cache behavior uses HTTPS-only or
  redirect-HTTP-to-HTTPS before enabling mTLS
- You SHOULD note the trust store reads the CA bundle from S3 only at creation time, so rotation
  needs a manual trust store update

## Authorization token: validate at the edge with CloudFront Functions

**Constraints:**

- You SHOULD validate an OAuth bearer token or JWT in a CloudFront function on the viewer-request
  event when the logic is lightweight and viewer-facing
- You MUST route token checks that need network access or origin-facing events to Lambda@Edge
- You MUST publish the function to the LIVE stage before associating it with the distribution

## Pair every control with origin locking

A content control only holds if access is forced through CloudFront. While the origin URL is
directly reachable, viewers bypass the control entirely.

**Constraints:**

- You MUST pair every content control with an origin-locking mechanism: origin access control for an
  S3 origin, or VPC origins or origin mTLS for a custom origin (see protecting-your-origins)
- You MUST NOT present a content control as complete while the origin is still directly reachable

## Procedure

### Overview

This procedure selects the content control by question, applies it, pairs it with origin locking,
and surfaces the console link.

### Parameters

- **distribution_id** (required): The distribution to secure.
- **control** (required): `signed`, `geo`, `viewer-mtls`, or `token`.
- **gate_detail** (required): The key group, country list, trust store source, or token type.

**Constraints for parameter acquisition:**

- You MUST ask what the customer is gating on upfront
- You MUST confirm the origin-locking plan before calling the setup complete

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST confirm the origin is locked or plan to lock it (see protecting-your-origins)

#### 2. Apply the chosen control

**Constraints:**

- For identity, you MUST configure a trusted key group and have the application issue signed URLs or
  cookies. Create the key group, then reference it from the cache behavior's `TrustedKeyGroups`:

  ```
  aws cloudfront create-key-group --key-group-config \
    '{"Name":"paid-users","Items":["{publicKeyId}"]}'
  ```

- For location, you MUST set the geographic restriction allowlist or denylist on the distribution by
  updating its config (the `Restrictions.GeoRestriction` block). Fetch the current config and ETag,
  set the `Restrictions.GeoRestriction` block, then pass the full modified config back as an inline
  JSON string (use an inline JSON string, not a `file://` reference, for portability across
  execution environments):

  ```
  aws cloudfront get-distribution-config --id {distribution_id}
  # set Restrictions.GeoRestriction in the returned DistributionConfig, then put it back.
  # RestrictionType is an AWS API enum; its only allowed values are "whitelist" (allowlist),
  # "blacklist" (denylist), and "none" — use the API's exact token here for the allowlist case:
  aws cloudfront update-distribution --id {distribution_id} --if-match {etag} \
    --distribution-config '{"CallerReference":"...","Restrictions":{"GeoRestriction":{"RestrictionType":"whitelist","Quantity":1,"Items":["US"]}}, ...rest of the unchanged config...}'
  ```

- For client certificate, you MUST create the trust store, disable HTTP/3, set all behaviors to
  HTTPS, and enable viewer mutual authentication in required mode. Create the trust store from the
  PEM CA bundle in S3:

  ```
  aws cloudfront create-trust-store --name {name} \
    --s3-bucket {bucket} --s3-object-key {ca-bundle.pem}
  ```

- For token, you MUST write a CloudFront function on viewer-request that validates the token, then
  publish and associate it.
- ⚠️ You MUST implement real signature verification before publishing. A function that only checks
  token presence and length does not verify authenticity — any arbitrary string passes, which is a
  false sense of security. The validation logic below is described as steps, not as runnable code, so
  it is not deployed as-is: the function MUST (a) read the bearer token from the `authorization`
  header, (b) reject a missing or over-length token with a 401, and (c) **verify the token's
  signature** (for example, validate the JWT signature with `crypto.subtle` in a CloudFront Functions
  runtime that supports it) before returning `event.request`. Author the function code to do all three.
- Create the function with your authored, signature-verifying code (replace `{function_code}` with
  it), and set `Runtime` to the current CloudFront Functions runtime that supports your code — do not
  hardcode a runtime string that ages; check the available runtimes in the CloudFront Developer Guide
  (CloudFront Functions) and select the latest supported one for `{runtime}`:

  ```
  aws cloudfront create-function --name {name} \
    --function-config '{"Comment":"token-check","Runtime":"{runtime}"}' \
    --function-code '{function_code}'
  ```

- Only after the function performs signature verification, publish and associate it:

  ```
  aws cloudfront publish-function --name {name} --if-match {etag}
  ```

- You MUST also attach a response headers policy that adds browser security headers (HSTS,
  Content-Security-Policy, X-Frame-Options, X-Content-Type-Options) to complement these access
  controls, since they defend against different browser-based attacks (clickjacking, MIME sniffing,
  protocol downgrade). The AWS managed `SecurityHeadersPolicy` is a starting point. Look up its
  current id by name (do not hardcode a UUID — managed policy ids can change), fetch the current
  config and ETag, set the behavior's `ResponseHeadersPolicyId`, then pass the full modified config
  back as an inline JSON string (use an inline JSON string, not a `file://` reference, for
  portability across execution environments):

  ```
  # resolve the managed SecurityHeadersPolicy id by name (do not hardcode a UUID):
  aws cloudfront list-response-headers-policies --type managed \
    --query "ResponseHeadersPolicyList.Items[?ResponseHeadersPolicy.ResponseHeadersPolicyConfig.Name=='Managed-SecurityHeadersPolicy'].ResponseHeadersPolicy.Id | [0]" --output text
  aws cloudfront get-distribution-config --id {distribution_id}
  # set DefaultCacheBehavior.ResponseHeadersPolicyId to the resolved managed SecurityHeadersPolicy id
  # in the returned DistributionConfig, then put it back:
  aws cloudfront update-distribution --id {distribution_id} --if-match {etag} \
    --distribution-config '{"CallerReference":"...","DefaultCacheBehavior":{"ResponseHeadersPolicyId":"{security_headers_policy_id}", ...}, ...rest of the unchanged config...}'
  ```

#### 3. Confirm origin locking and surface the console link

**Constraints:**

- You MUST confirm the origin cannot be reached directly before calling the control complete
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
  "control": "signed",
  "gate_detail": "trusted-key-group: paid-users"
}
```

#### Example output

```
Configured trusted key group paid-users on E1ABCDEF2GHIJK for signed URLs.
Origin locked with origin access control so the signing cannot be bypassed.
Verify in the console:
https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/E1ABCDEF2GHIJK
```

## Troubleshooting

### Viewers still download files directly despite signed URLs
The origin is directly reachable, so signing is bypassed. Lock the origin (see
protecting-your-origins).

### Geographic restrictions do not apply to only part of the content
Geographic restrictions apply to the whole distribution at the country level. Use separate
distributions or a third-party geolocation approach for finer control.

### Enabling viewer mTLS returns a configuration error
HTTP/3 is enabled or a cache behavior allows HTTP. Disable HTTP/3 and set every behavior to HTTPS,
then enable mTLS.

### Clients without a certificate are still allowed through
The validation mode is optional or passthrough. Use required mode to reject clients without a valid
certificate.

### A token-validation function association fails
The function was not published to the LIVE stage. Publish it, then associate it.

## Security Considerations

- **Origin locking is mandatory.** Every content control here is bypassed while the origin is
  directly reachable. Pair each control with origin access control, VPC origins, or origin mTLS
  (see protecting-your-origins) before calling it complete.
- **Rotate signing keys.** Signed URLs and cookies stay valid until they expire. Rotate the keys in
  the trusted key group on a schedule and on suspected compromise, and keep expirations short.
- **Rotate the viewer mTLS trust store.** The trust store reads the CA bundle from S3 only at
  creation time, so rotating or revoking a CA requires a manual trust store update; stale CAs keep
  granting access.
- **Avoid permissive geographic restrictions.** Country-level allowlists or denylists apply to the whole
  distribution. Overly broad lists weaken the control; confirm the list matches the actual policy.
- **Add browser security headers.** Attach a response headers policy (HSTS, CSP, X-Frame-Options,
  X-Content-Type-Options) so the access controls are complemented by defenses against clickjacking,
  MIME sniffing, and protocol downgrade.
- **Pair access controls with AWS WAF for defense in depth.** Signed URLs, geographic restrictions,
  viewer mTLS, and token validation gate who reaches content, but they do not filter malicious
  requests at Layer 7. Attach an AWS WAF web ACL with baseline rules (the AWS Managed Rules Core
  Rule Set and Known Bad Inputs rule group) to the distribution for comprehensive edge protection.
- **Audit content-access changes with CloudTrail.** Enable AWS CloudTrail to record the CloudFront
  management API calls that change access controls (`cloudfront:CreateFunction`,
  `cloudfront:PublishFunction`, `cloudfront:UpdateDistribution`) for a compliance and forensic audit
  trail.

## Additional Resources

- [Serve private content with signed URLs and signed cookies (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/PrivateContent.html)
- [Decide to use signed URLs or signed cookies (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-choosing-signed-urls-cookies.html)
- [Restrict the geographic distribution of your content (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/georestrictions.html)
- [Mutual TLS authentication with CloudFront (Viewer mTLS) (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/mtls-authentication.html)
- [Enable mutual TLS for CloudFront distributions (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/enable-mtls-distributions.html)
- [Customize at the edge with CloudFront Functions and Lambda@Edge (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/edge-functions.html)
