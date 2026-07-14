# Managing Certificates with CloudFront

## Overview

Domain expertise for serving content from a custom domain over HTTPS, covering a single standard
distribution, a domain migrating from a third-party CDN, and a SaaS or platform provider running
many domains off one shared configuration with a certificate per tenant. The certificate work is
the part that trips customers up, and multi-tenant distributions are the scaling path where
certificate management matters most.

The ACM certificate CloudFront uses must be in `us-east-1` regardless of where the application
runs. For a standard distribution, add the domain as an alternate domain name (CNAME), attach a
`us-east-1` certificate that covers it, validate ownership, and wait for the certificate to reach
Issued. For many domains, a multi-tenant distribution is a template that cannot serve traffic
directly; each domain is a distribution tenant that inherits the template, and a connection group
provides the CloudFront routing endpoint DNS points at.

Does not cover the Route 53 DNS cutover (owned by the route53-cloudfront skill), creating the
distribution itself (see when-to-use-cloudfront), or origin and content security (see
protecting-your-origins and securing-your-content).

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise. CloudFront and its ACM certificates operate in
`us-east-1`.

## Table of Contents

- Overview
- The certificate must be in us-east-1
- Decision: validation method
- Decision: standard distribution vs multi-tenant
- The multi-tenant three-part model
- Decision: shared vs per-tenant certificate
- Test a tenant before the DNS cutover
- Procedure
- Troubleshooting
- Security Considerations
- Additional Resources

## The certificate must be in us-east-1

Customers request the certificate in their application's Region, try to attach it, and get an
error.

**Constraints:**

- You MUST always request or locate the ACM certificate in `us-east-1`, regardless of where the
  application runs
- You MUST identify a certificate requested in the application Region as the cause when attachment
  fails

## Decision: validation method

| Situation | Validation |
| --- | --- |
| New domain, no live traffic | DNS validation (CNAME records ACM provides) |
| Domain migrating from another CDN, still serving traffic | Import or reuse an existing certificate (standard), or HTTP-based validation (file upload or HTTP redirect) for a distribution tenant, so the certificate issues without a premature DNS change |

**Constraints:**

- You MUST detect when a domain already serves live traffic and offer a validation method that does
  not disrupt it
- You MUST check whether the domain is already associated with another CloudFront resource before
  adding it, because a domain can associate with only one CloudFront distribution or tenant at a
  time (otherwise a `CNAMEAlreadyExists` error)

## Decision: standard distribution vs multi-tenant

| Situation | Use |
| --- | --- |
| One domain, or a few unrelated ones | Standard distribution with an alternate domain name and a certificate |
| Many domains sharing configuration | Multi-tenant distribution with a distribution tenant per domain and per-tenant managed certificates |

**Constraints:**

- You MUST route a customer managing many similar domains to a multi-tenant distribution rather than
  repeated standard distributions

## The multi-tenant three-part model

The multi-tenant distribution is a template that holds shared settings and cannot serve traffic
directly. A distribution tenant is the front door for each domain and inherits the template. A
connection group provides the CloudFront routing endpoint that DNS points at.

**Constraints:**

- You MUST explain this three-part model before the customer creates resources
- You MUST point DNS at the connection group routing endpoint, never at the multi-tenant
  distribution template
- You SHOULD note that only a limited set of settings is customizable per tenant (examples that have
  been overridable: AWS WAF web ACL, TLS certificate, geographic restrictions, and parameters such as
  origin path and domain), and direct the customer to verify the current set against the CloudFront
  Developer Guide rather than treating the list as exhaustive

## Decision: shared vs per-tenant certificate

| Tenant domains | Certificate |
| --- | --- |
| Subdomains the provider controls | Shared wildcard certificate inherited from the template |
| Tenants bring their own domain names | Per-tenant managed certificate CloudFront requests on their behalf |

**Constraints:**

- You MUST match the certificate approach to the domain ownership model

## HTTP validation options for tenant-level certificates

For per-tenant managed certificates, CloudFront initiates the certificate request. The customer
proves domain ownership through one of three options:

| Option | How it works |
| --- | --- |
| Managed | Configure DNS to resolve the domain to CloudFront DNS (e.g., d123.cloudfront.net) or Anycast IP |
| Self-hosted with redirect | Place an HTTP redirect for the well-known certification validation path to the ACM endpoint (provided by Tenant API) |
| Self-hosted with direct token serving | Serve the token provided by CloudFront APIs from the well-known validation path |

**Constraints:**

- You MUST use self-hosted validation (redirect or token) when the domain still serves live traffic
  from another provider, because managed validation requires DNS to already point at CloudFront
- You MUST note that for HTTP-validated managed certificates, CloudFront associates the certificate
  automatically once validated — no explicit customer action needed
- You MUST note that for DNS validation and imported certificates, the customer must explicitly
  associate the certificate with the tenant AND activate the tenant to serve traffic
- You MUST remind customers that tenants must be explicitly activated after certificate association
  (for DNS and import methods) or after HTTP validation completes (for managed certificates)

## Test a tenant before the DNS cutover

Customers cut a production domain straight over and discover a misconfiguration only after live
traffic breaks.

**Constraints:**

- You MUST validate the tenant against the connection group's CloudFront routing endpoint before the
  DNS cutover, so the tenant is confirmed serving correctly while the real domain still resolves to
  its old target
- You MUST move DNS only after the tenant validates

## Procedure

### Overview

This procedure adds a custom domain over HTTPS, requesting the certificate in `us-east-1`,
choosing the validation method and (for many domains) the multi-tenant path, testing the tenant,
and surfacing the console link.

### Parameters

- **domain_name** (required): The custom domain (for example `www.example.com`).
- **distribution_id** (required for standard): The distribution to add the domain to.
- **multi_tenant** (required): Whether the customer is running many domains (`true`/`false`).
- **has_live_traffic** (required): Whether the domain already serves traffic elsewhere.

**Constraints for parameter acquisition:**

- You MUST ask whether the customer is managing one domain or many upfront
- You MUST ask whether the domain already has live traffic to pick the validation method

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`
- You MUST check the domain is not already associated with another CloudFront resource

#### 2. Request or locate the certificate in us-east-1

**Constraints:**

- You MUST request or import the certificate in `us-east-1` covering the domain:

  ```
  aws acm request-certificate --domain-name {domain_name} \
    --validation-method DNS --region us-east-1
  ```

- You MUST choose HTTP-based validation or an imported certificate when the domain already serves
  live traffic

#### 3. Add the domain and attach the certificate

**Constraints:**

- For a standard distribution, you MUST add the domain as an alternate domain name (CNAME) and
  attach the `us-east-1` certificate once it reaches `ISSUED`
- You MUST set the distribution's minimum protocol version to a current strong security policy (a
  TLS 1.2-or-higher `MinimumProtocolVersion`) rather than relying on the default, which may allow
  older TLS versions, to ensure strong encryption in transit. Do not hardcode a policy string that
  ages — select the newest TLS 1.2+ security policy CloudFront offers, confirming the current options
  against the CloudFront Developer Guide "supported protocols and ciphers" page
- You MUST enable standard logging on the distribution as part of this change if it is not already
  enabled, so configuring the custom domain does not leave an audit-trail gap on a production
  web-facing distribution (see the cloudfront-observability workflow for the logging configuration)
- For many domains, you MUST create the multi-tenant distribution (template), let CloudFront create
  the connection group, and create a distribution tenant per domain with the appropriate certificate

#### 4. Test the tenant before cutover (multi-tenant)

**Constraints:**

- You MUST validate the tenant against the connection group's CloudFront routing endpoint before any
  DNS change

#### 5. Hand off DNS and surface the console link

**Constraints:**

- You MUST hand the DNS cutover to the route53-cloudfront workflow (alias or CNAME at the routing
  endpoint), not perform it here
- You MUST present the distribution detail console link, filling `{distributionId}` from the input
  `distribution_id` parameter:

  ```
  https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/{distributionId}
  ```

### Example

#### Example input

```json
{
  "domain_name": "www.example.com",
  "distribution_id": "E1ABCDEF2GHIJK",
  "multi_tenant": false,
  "has_live_traffic": false
}
```

#### Example output

```
Requested an ACM certificate in us-east-1 covering www.example.com, validated by DNS.
Added www.example.com as an alternate domain name on E1ABCDEF2GHIJK and attached the certificate.
DNS cutover is a Route 53 step (route53-cloudfront skill).
Verify in the console:
https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/E1ABCDEF2GHIJK
```

## Troubleshooting

### CloudFront will not attach the ACM certificate
The certificate is not in `us-east-1`. Request or import it in `us-east-1` and attach the new one.

### CNAMEAlreadyExists when adding the domain
The domain is associated with another CloudFront distribution or tenant. Move it before adding.

### The certificate stays Pending validation
DNS validation records are missing, or the domain serves traffic elsewhere and cannot be reached.
Add the CNAME validation records, or use HTTP-based validation for a tenant.

### The multi-tenant distribution does not serve traffic
The template cannot serve traffic directly. Point DNS at the connection group routing endpoint, not
the template, and create distribution tenants for each domain.

### A tenant works on the routing endpoint but the custom domain fails
DNS has not been cut over, or the certificate does not cover the tenant domain. Confirm the
certificate covers the domain, then complete the Route 53 cutover.

## Security Considerations

- **Let ACM hold the private key.** Prefer ACM-issued or ACM-managed certificates so the private key
  never leaves ACM. For an imported certificate, store its private key in AWS Secrets Manager rather
  than on disk or in application config.
- **Enforce a minimum TLS version.** Set the distribution's minimum protocol version to a current
  strong TLS 1.2-or-higher security policy rather than relying on the default, which may allow older
  TLS versions. Choose the newest TLS 1.2+ policy CloudFront offers (confirm current options in the
  CloudFront Developer Guide) instead of hardcoding a policy string that ages.
- **Watch for stale or expiring certificates.** An expired certificate breaks HTTPS for the domain.
  Track expirations and renew ahead of time; ACM-managed certificates renew automatically while
  imported ones do not. Set a CloudWatch alarm on the ACM `DaysToExpiry` metric (or enable the AWS
  Config `acm-certificate-expiration-check` managed rule) to alert before a certificate expires,
  especially for imported certificates that do not auto-renew.
- **Keep DNS validation records in place.** ACM uses the DNS validation CNAME records to
  automatically renew certificates. Removing them prevents renewal and will cause HTTPS to break
  when the certificate expires.
- **Audit certificate operations with CloudTrail.** Enable AWS CloudTrail to record the ACM and
  CloudFront management API calls that change certificates and alternate domain names
  (`acm:RequestCertificate`, `acm:ImportCertificate`, `cloudfront:UpdateDistribution`) for a
  compliance and forensic audit trail.

## Additional Resources

- [Use custom URLs by adding alternate domain names (CNAMEs) (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/CNAMEs.html)
- [Requirements for using SSL/TLS certificates with CloudFront (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/cnames-and-https-requirements.html)
- [Request certificates for your CloudFront distribution tenant (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/managed-cloudfront-certificates.html)
- [Move an alternate domain name (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/alternate-domain-names-move.html)
- [Understand how multi-tenant distributions work (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/distribution-config-options.html)
- [Create custom connection group (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/custom-connection-group.html)
