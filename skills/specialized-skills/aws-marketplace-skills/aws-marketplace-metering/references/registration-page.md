# Buyer onboarding / registration page

## The `RegistrationUrl` is a backend, not the buyer-facing page

The main stack outputs a `RegistrationUrl` — a raw API Gateway endpoint. When a buyer clicks
**Set up your account** in AWS Marketplace, Marketplace redirects them to the product's
Fulfillment URL with an `x-amzn-marketplace-token` (POSTed as form data). The register Lambda
behind `RegistrationUrl` calls `ResolveCustomer` with that token and persists
`CustomerAWSAccountId` + `LicenseArn` + `ProductCode` (+ any allowlisted extra fields) to the
subscribers table.

That backend is **not a finished onboarding experience.** The product's **Fulfillment URL
should point at the branded front-end page**, not at the raw `RegistrationUrl` — the
Marketplace redirect must land the buyer's browser on a page that renders. Pointing the
Fulfillment URL straight at `RegistrationUrl` gives the buyer no page (and no branding or
extra-field capture) and is only a bare-bones fallback for an initial smoke test. Most
sellers want a **branded, buyer-facing registration page** — this is what the AWS
**Serverless SaaS Integration reference architecture** and the Marketplace seller onboarding
lab provide. Do not let a seller believe onboarding is "done" once the backend deploys.

## Recommended pattern (branded page)

A static site that is itself the **Fulfillment URL target** and sits in front of the
`RegistrationUrl`:

- **S3 + CloudFront** host the page (optionally a **custom domain** + an ACM certificate so the
  Fulfillment URL is the seller's own branded domain). **The AMMP Fulfillment URL points here.**
- The page receives the Marketplace redirect (buyer's browser + token), renders the seller's
  branding/marketing, and **captures additional buyer fields** (e.g. contact name, email,
  company, use-case).
- On submit it forwards the **token unchanged** plus the captured fields (as allowlisted form
  keys) to `RegistrationUrl` (the backend). The token is short-lived (~4h) and reusable until
  expiry.
- **Secure the public page (same protections the backend `RegistrationUrl` already gets):**
  - Attach a **CloudFront response-headers policy** setting `Content-Security-Policy`,
    `Strict-Transport-Security` (HSTS), `X-Frame-Options`, and `X-Content-Type-Options` so the
    buyer-facing page carries the same security headers the register Lambda returns.
  - Front the CloudFront distribution with **AWS WAF** (a rate-based rule + the common-exploit
    managed rule set) for defense in depth on this public, unauthenticated page.

The page's markup/branding is **seller-owned** (like usage-write logic — out of scope of the
generated backend), but the skill can scaffold the S3 + CloudFront (+ optional custom domain,
response-headers policy, and WAF association) and wire the form contract on request. Ask the
seller whether they want the branded-page scaffold or will host their own.

## Capture "Know Your Buyer" (KYB) fields from the start
The register Lambda (in-region) persists ONLY the fields named in `ALLOWED_REGISTRATION_FIELDS`
(comma-separated, each length-bounded, up to a max count; the token is never stored) — and it
writes them to the **in-region `customer-profile` table** (PK `licenseArn` + SK
`customerAWSAccountId`), NOT the subscribers table (which is kept PII-free and lives in
us-east-1). Because the profile table is schemaless, **no table change is needed to add a buyer
attribute** — you only need (1) the field on the onboarding form and (2) the field name in the
allowlist; add a GSI on the profile table only if you want to look profiles up by that field.

At initial integration, propose capturing the buyer fields the AWS Marketplace **Know Your
Buyer (KYB)** initiative plans to collect — typically buyer **contact name, email,
company/organization, and use-case** — so they are written into the customer-profile table from
day one. Doing this up front avoids a later backfill/migration when KYB fields become required.

> **This describes a NEW skill-generated integration.** For an EXISTING seller stack the skill
> ADAPTS instead: the seller may already store registration data in their own shape, and if their
> subscribers table already holds buyer PII, moving it to a per-Region profile table is a data
> migration + code cutover — not a drop-in. See `references/existing-sellers.md` → "Adding a new
> capability to an EXISTING stack".

Guidance:

- Set `ALLOWED_REGISTRATION_FIELDS` to the seller's chosen KYB + custom fields
  (e.g. `contact_name,contact_email,company,use_case`).
- Keep the fields OPTIONAL and seller-confirmed — do not invent PII fields the seller did not
  ask for; whether a KYB field is mandatory is an AWS Marketplace program decision, not this
  skill's.
- Buyer PII stays IN-REGION (in the customer-profile table) and OUT of logs (identifiers are
  masked on output); the token is never persisted; PII is never written to the us-east-1
  subscribers table.
