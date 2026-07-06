# Configure a Multi-Tenant Distribution

## Overview

Domain expertise for serving content for multiple domains through a single shared CloudFront
configuration, using multi-tenant distributions. A multi-tenant distribution acts as a template
defining shared settings (cache behaviors, origins, security). Distribution tenants inherit those
settings, each serving as the front door for a specific domain. A connection group provides the
CloudFront routing endpoint (DNS and Anycast routing) that tenants share.

This is the scaling path for SaaS providers and platform teams managing many customer domains.
Instead of creating a separate standard distribution for each domain (duplicating configuration
and making updates error-prone at scale), customers define the configuration once and inherit it
across all tenants.

Does not cover the certificate management details for tenants (see
managing-certificates-with-cloudfront), creating the initial distribution (see
when-to-use-cloudfront), or origin security (see protecting-your-origins).

Execute commands using the AWS MCP server when connected (sandboxed execution, audit logging,
observability). Fall back to the AWS CLI otherwise.

## Table of Contents

- Overview
- The three-part model
- Decision: standard distribution vs multi-tenant
- Per-tenant customizations
- Unsupported features
- Connection groups and blast radius management
- Tenant activation
- Procedure
- Troubleshooting
- Security Considerations
- Additional Resources

## The three-part model

| Component | Role |
| --- | --- |
| Multi-tenant distribution | Template defining shared settings. Cannot serve traffic directly |
| Distribution tenant | Front door for each domain. Inherits the template configuration |
| Connection group | Provides the CloudFront routing endpoint (DNS like d123.cloudfront.net and Anycast routing) used in DNS |

**Constraints:**

- You MUST explain this three-part model before the customer starts creating resources
- You MUST make clear the multi-tenant distribution cannot serve traffic directly — only tenants do
- You MUST point DNS at the connection group routing endpoint, never at the multi-tenant
  distribution template

## Decision: standard distribution vs multi-tenant

| Situation | Use |
| --- | --- |
| One domain, or a few unrelated ones | Standard distribution |
| Many domains sharing configuration (SaaS, platform) | Multi-tenant distribution |

**Constraints:**

- You MUST identify when a customer manages multiple domains with similar settings and guide them
  toward a multi-tenant distribution instead of repeated standard distributions

## Per-tenant customizations

A limited set of settings can be overridden at the distribution tenant level; everything else is
inherited from the multi-tenant distribution template. The set evolves as the service adds support,
so verify the current list of per-tenant customizable settings against the CloudFront Developer Guide
rather than treating the examples below as exhaustive. Examples that have been overridable per tenant:

- AWS WAF web ACL
- TLS certificate
- Geographic restrictions
- Parameters (such as origin path and domain)

Everything else is fixed at the multi-tenant distribution level.

**Constraints:**

- You MUST clarify what is customizable per tenant versus what is fixed at the multi-tenant
  distribution level
- You MUST NOT lead customers to expect per-tenant cache behavior or origin configuration changes

## Unsupported features

Multi-tenant distributions do not support every standard-distribution feature, and the exact list
evolves as the service adds support. Examples of features that have been unsupported or have required
a standard distribution include origin access identity (OAI) — use OAC instead — AWS WAF Classic
(use AWS WAF v2), Smooth streaming, continuous deployment, dedicated IP custom SSL, and the default
testing domain.

- You MUST verify the current support matrix in the CloudFront Developer Guide (multi-tenant /
  distribution tenants) rather than relying on a fixed list, since unsupported features can become
  supported as the service evolves; treat the items above as examples to check, not an authoritative
  list

**Constraints:**

- You MUST surface unsupported features and their better alternatives before migration, so the
  customer does not discover gaps after switching
- You MUST recommend a standard distribution when the customer requires a feature that the current
  CloudFront Developer Guide lists as unsupported on multi-tenant distributions (verify against the
  guide rather than a fixed list)

## Connection groups and blast radius management

A default connection group is created automatically by CloudFront when the multi-tenant
distribution is created. Customers may create additional connection groups to limit the blast
radius — if one connection group has an issue, tenants on other connection groups are unaffected.

**Constraints:**

- You SHOULD suggest additional connection groups for large-scale deployments where blast radius
  isolation matters
- You MUST note that if no connection group is specified when creating a tenant, it uses the default

## Tenant activation

Tenants must be explicitly activated to serve traffic. This is a manual step.

- For DNS and import certificate validation: activate after explicitly associating the issued
  certificate with the tenant
- For HTTP-validated managed certificates: activate after HTTP validation completes (certificate
  association is automatic)

**Constraints:**

- You MUST always remind customers about the explicit activation step
- You MUST explain there is no automated mechanism to activate the tenant — activation always
  requires explicit customer action (for HTTP-validated managed certificates, certificate
  association is automatic, but the tenant still must be activated)

## Procedure

### Overview

This procedure creates a multi-tenant distribution, adds distribution tenants for each domain,
and activates them.

### Parameters

- **domains** (required): List of domains to serve.
- **shared_origin** (required): The origin all tenants share.
- **certificate_approach** (required): `wildcard` or `per-tenant`.

**Constraints for parameter acquisition:**

- You MUST ask how many domains and whether they share configuration
- You MUST ask whether the provider controls subdomains (wildcard) or tenants bring their own
  domains (per-tenant certificates)

### Steps

#### 1. Verify dependencies

**Constraints:**

- You MUST confirm credentials with `aws sts get-caller-identity`

#### 2. Create the multi-tenant distribution

**Constraints:**

- You MUST create the multi-tenant distribution with the shared configuration (cache behaviors,
  origins, security settings). Do not embed a static managed cache policy id; look up the current
  `Managed-CachingOptimized` policy by name and use its id for `CachePolicyId` (managed policy ids
  can change):

  ```
  # resolve the managed CachingOptimized cache policy id (do not hardcode a UUID):
  aws cloudfront list-cache-policies --type managed \
    --query "CachePolicyList.Items[?CachePolicy.CachePolicyConfig.Name=='Managed-CachingOptimized'].CachePolicy.Id | [0]" --output text
  aws cloudfront create-distribution --distribution-config '{"CallerReference":"mt-2024-01","ConnectionMode":"tenant-only","Origins":{"Quantity":1,"Items":[{"Id":"shared-origin","DomainName":"origin.myapp.com","CustomOriginConfig":{"HTTPPort":80,"HTTPSPort":443,"OriginProtocolPolicy":"https-only"}}]},"DefaultCacheBehavior":{"TargetOriginId":"shared-origin","ViewerProtocolPolicy":"redirect-to-https","CachePolicyId":"{cache_policy_id}"},"Enabled":true}'
  ```

- You MUST set the shared template's viewer protocol policy to redirect-HTTP-to-HTTPS (or
  HTTPS-only) and, for custom origins, the origin protocol policy to HTTPS-only, so every tenant
  inherits encryption in transit end-to-end
- You MUST note the default connection group is created automatically
- You MUST attach a response headers policy with browser security headers (HSTS, CSP,
  X-Frame-Options, X-Content-Type-Options) to the shared template so every tenant inherits the
  security baseline; look up the managed `Managed-SecurityHeadersPolicy` id by name via
  `aws cloudfront list-response-headers-policies --type managed` rather than hardcoding a UUID (see
  securing-your-content for the lookup), since managed policy ids can change
- You SHOULD attach an AWS WAF web ACL to the multi-tenant distribution for baseline Layer 7
  protection, noting that because tenants serve multiple customer domains the attack surface is
  larger, and that the web ACL can be customized per tenant
- You SHOULD enable standard logging on the multi-tenant distribution for traffic visibility across
  all tenants (the distribution tenant identifier field lets you break logs down per tenant)

#### 3. Create distribution tenants

**Constraints:**

- You MUST create a distribution tenant for each domain, referencing the multi-tenant
  distribution as the template:

  ```
  aws cloudfront create-distribution-tenant --distribution-id {distributionId} \
    --name {tenant-name} --domains '[{"Domain":"tenant1.myapp.com"}]'
  ```

- You MUST associate the appropriate certificate (wildcard inherited or per-tenant managed)
- You MUST activate each tenant after certificate association/validation by updating it with
  `Enabled` set to true:

  ```
  aws cloudfront update-distribution-tenant --id {tenantId} --enabled --if-match {etag}
  ```

#### 4. Surface the console link

**Constraints:**

- You MUST present the distribution detail console link:

  ```
  https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/{distributionId}
  ```

### Example

#### Example input

```json
{
  "domains": ["tenant1.myapp.com", "tenant2.myapp.com"],
  "shared_origin": "origin.myapp.com",
  "certificate_approach": "wildcard"
}
```

#### Example output

```
Created multi-tenant distribution E1ABCDEF2GHIJK with shared origin and cache behaviors.
Default connection group created automatically.
Created distribution tenants for tenant1.myapp.com and tenant2.myapp.com, inheriting
the wildcard certificate *.myapp.com from the distribution.
Tenants activated and ready to serve traffic.
Verify in the console:
https://us-east-1.console.aws.amazon.com/cloudfront/v4/home?region=us-east-1#/distributions/E1ABCDEF2GHIJK
```

## Troubleshooting

### The multi-tenant distribution does not serve traffic
The template cannot serve traffic directly. Create distribution tenants for each domain and point
DNS at the connection group routing endpoint.

### A tenant is not serving traffic after certificate issuance
The tenant has not been activated. Explicitly activate the tenant after associating the certificate.

### A feature the customer needs is not available
Verify the feature against the current CloudFront Developer Guide support matrix rather than a fixed
list. As examples that have required a standard distribution or been unsupported on multi-tenant:
OAI (use OAC), AWS WAF Classic (use AWS WAF v2), smooth streaming, continuous deployment, dedicated
IP custom SSL, and the default testing domain.

### Configuration changes don't apply to a specific tenant
Only a limited set of settings is customizable per tenant (examples that have been overridable: AWS
WAF web ACL, TLS certificate, geographic restrictions, and parameters — verify the current set
against the CloudFront Developer Guide); all other settings are inherited from the multi-tenant
distribution template.

## Security Considerations

- **Shared configuration is a shared blast radius.** A misconfiguration on the multi-tenant
  template (origin, cache behavior, security setting) propagates to every tenant at once. Review
  template changes against all tenants before applying.
- **Isolate tenants with per-tenant AWS WAF web ACLs.** The web ACL is customizable per tenant; use it
  to apply per-customer Layer 7 rules and rate limits rather than relying only on a single shared
  ACL across all domains.
- **Encryption in transit on the template.** Set the viewer protocol policy to
  redirect-HTTP-to-HTTPS (or HTTPS-only) and the origin protocol policy to HTTPS-only on the shared
  template so every inheriting tenant is encrypted end-to-end.
- **Enable logging for cross-tenant audit.** Enable standard logging on the distribution; the
  distribution tenant identifier field lets you attribute and audit requests per tenant.
- **Least-privilege IAM for tenant management.** Scope tenant create/update/activate permissions to
  the operators who manage them rather than granting broad `cloudfront:*`, since these operations
  affect customer-facing domains.
- **Audit the management plane with CloudTrail.** Enable AWS CloudTrail to track tenant creation,
  activation, and template changes (`cloudfront:CreateDistribution`,
  `cloudfront:CreateDistributionTenant`, `cloudfront:UpdateDistributionTenant`) for a compliance and
  forensic audit trail.

## Additional Resources

- [Understand how multi-tenant distributions work (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/multi-tenant-distributions.html)
- [Distribution tenant customizations (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/distribution-tenant-customizations.html)
- [Migrate to a multi-tenant distribution (Amazon CloudFront Developer Guide)](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/migrate-to-multi-tenant.html)
