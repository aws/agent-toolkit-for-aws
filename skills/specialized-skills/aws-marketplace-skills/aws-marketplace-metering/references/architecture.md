## Architecture

```
                          us-east-1                              seller region (e.g. us-west-2)
                    ┌─────────────────────┐              ┌──────────────────────────────────┐
                    │  EventBridge Rule    │              │  API Gateway                     │
Marketplace ──────► │  (aws.agreement-     │              │  POST /register                  │
Agreement +         │   marketplace)       │              │       │                          │
License Events      │       │              │              │       ▼                          │
                    │       ▼              │              │  Register Lambda                 │
                    │  SQS Queue ──► DLQ   │              │  (ResolveCustomer)               │
                    │       │              │              │       │                          │
                    │       ▼              │   read+write │       └──► updates subscribers ──┤
                    │  Subscription Lambda │◄─────────────┼────────────(cross-region)        │
                    │       │              │              │                                  │
                    │       ▼              │              │  EventBridge Schedule (rate 15m) │
                    │  DynamoDB            │              │       │                          │
                    │  (awsmp-subscribers) │◄─────────────┼── Metering pipeline reads subs   │
                    │  PK: licenseArn      │   read       │       ▼                          │
                    │  SK: customerAWSAcct │              │  discoverer→aggregator→cleanup   │
                    │  productCode,        │              │  →submitter (→ BatchMeterUsage)  │
                    │  agreementStatus,    │              │                                  │
                    │  subscriptionStatus, │              │  DynamoDB (usage)                │
                    │  registeredRegions   │              │  PK: licenseArn                  │
                    └─────────────────────┘              │  SK: custAcct#dimension#ts       │
                                                         └──────────────────────────────────┘
```

### Data Model

**Unified Subscribers Table** — a SINGLE table holding subscription/agreement STATE, **PII-FREE**. Lives in `us-east-1` alongside EventBridge. Populated by EventBridge events and updated by the register Lambda (identity + statuses + `registeredRegions` only). Buyer registration-form data (PII) is NOT stored here — it lives in the per-Region `customer-profile` table (below).

For **Concurrent Agreements (default, new products):** `licenseArn` is the PARTITION key, `customerAWSAccountId` is the sort key. A buyer with multiple concurrent agreements has multiple rows (same `customerAWSAccountId`, different `licenseArn`), tracked independently.

For **legacy (pre-CA) products:** key by `customerAWSAccountId` alone.

| Field | Source | Description |
|-------|--------|-------------|
| `licenseArn` (PK, CA) | License Updated event: `detail.license.arn` | License ARN — partition key for CA products |
| `customerAWSAccountId` (SK) | Agreement events: `detail.acceptor.accountId` | Buyer's AWS account ID |
| `productCode` | License Updated event: `detail.product.code` | Metering product code |
| `agreementId` | Agreement events: `detail.agreement.id` | Unique agreement identifier |
| `agreementStatus` | Set by subscription Lambda | `active` (License Updated) / `inactive` (Purchase Agreement Ended) — the agreement lifecycle |
| `subscriptionStatus` | Set by subscription Lambda (transitions) + deprovision-cleanup Lambda (finalization) | `active` (License Updated) → `deprovisioning` (License Deprovisioned — final-usage flush window open) → `inactive` (deprovision-cleanup Lambda, once `deprovisioningExpiry` passes). There is no `deprovisioned` value. |
| `registeredRegions` | Appended by the register Lambda | DynamoDB String Set (SS) of AWS Region names where the buyer was registered (added idempotently via `ADD`, so no duplicates). Reference-only; NEVER gates metering |
| `customerIdentifier` | ResolveCustomer response (legacy only) | Deprecated; persisted only for legacy (pre-CA) support, NOT for new integrations |

> **The subscribers table is PII-FREE.** It carries only the CA identity (`licenseArn`, `customerAWSAccountId`, `productCode`, `agreementId`), the two lifecycle statuses, and `registeredRegions`. Buyer registration-form data (PII — contact name, email, company, KYB, seller-defined fields) is NOT stored here; it lives in the **per-Region `customer-profile` table** (below), written in-region by the register Lambda. Because it holds no PII, the subscribers table is safe in `us-east-1` even when the product/buyers operate in other (opt-in) Regions.

**Customer-profile table (per Region)** — `awsmp-<productCode>-customer-profile`, keyed by `licenseArn` (PK) + `customerAWSAccountId` (SK), deployed IN EACH metering/registration Region. Holds the seller's allowlisted registration/KYB fields (buyer PII), with additional seller-requested GSIs on those fields. Written by the in-region register Lambda; kept in-region so buyer PII is never replicated to us-east-1. Not on the metering path.

> **Mapping a `licenseArn` to the seller's internal SaaS tenant ID is the SELLER's responsibility — this skill does not own the tenant model.** AWS Marketplace identifies a buyer by `licenseArn` (+ `customerAWSAccountId`); how that maps to the seller's own tenant/account/org ID is the seller's application concern. The skill provides TWO places the seller can anchor that mapping, and the seller CHOOSES which (or both):
>
> - **Subscribers table** (us-east-1) — carries the `licenseArn` from the **`License Updated`** EventBridge event (the authoritative, refreshed-on-renewal source; PII-free, so store only a non-PII internal tenant identifier here if you add one).
> - **Customer-profile table** (in-Region) — carries the `licenseArn` captured at **registration time** (when the buyer clicks "Set up your account" and `ResolveCustomer` runs), alongside the buyer's registration/KYB fields — a natural home if the tenant record is created from the registration form.
>
> A row may exist in one before the other (registration and `License Updated` can arrive in either order), so a seller that needs the mapping available from the earliest moment often writes it in BOTH. The seller adds their own `tenantId` (or equivalent) attribute — the skill neither invents nor requires a specific tenant-ID scheme — and, if they need to look a tenant up by that ID, defines a GSI on it (on the customer-profile table for a PII/registration-derived ID, or on the subscribers table for a non-PII one).

**Usage Table** — keyed by `licenseArn` (PK) + `customerAWSAccountId#dimension#timestamp` (SK, **second precision**). Keying by licenseArn (not account) ensures usage is attributed per-agreement, preventing double-billing when a buyer holds multiple concurrent licenses. `customerAWSAccountId`, `dimension`, and `timestamp` are also stored as top-level attributes so the pipeline reads them without parsing the sort key. The seller writes usage here (and sets `meteringPending`); the metering pipeline reads it and calls BatchMeterUsage.

### Event Flow (Order of Operations)

```
1. Buyer clicks "Subscribe"
   → EventBridge: Purchase Agreement Created (us-east-1)
   → NOT consumed by the metering path. It carries no licenseArn and is not needed
     to meter usage. Sellers MAY add their own rule/target for other use cases
     (see "Purchase Agreement Created — seller use cases" below).

2. Shortly after (~seconds)
   → EventBridge: License Updated (us-east-1)
   → Subscription Lambda UPSERTS the subscriber record (us-east-1), keyed by the real
     licenseArn (detail.license.arn) + customerAWSAccountId, with productCode
     (detail.product.code) and subscriptionStatus=active. This is the row that drives
     metering — there is no separate "pending" placeholder row.

3. Buyer clicks "Set up your account"
   → Marketplace redirects the buyer's browser (with x-amzn-marketplace-token) to the
     Fulfillment URL = the branded registration PAGE (S3+CloudFront); the page renders,
     captures extra buyer/KYB fields, then POSTs the token + fields to the RegistrationUrl
     backend (a raw RegistrationUrl Fulfillment URL is a bare-bones fallback only)
   → Register Lambda calls ResolveCustomer (this skill deploys the register Lambda in the
     main-stack region as a packaging choice; ResolveCustomer's region is the seller's free
     choice and does NOT gate metering or have to match the BatchMeterUsage region)
   → Gets: CustomerAWSAccountId, LicenseArn, ProductCode
   → Writes buyer PII (allowlisted registration/KYB fields) to the IN-REGION
     customer-profile table keyed by licenseArn + customerAWSAccountId; upserts the PII-FREE
     subscriber row (identity + statuses) and appends the invocation Region to
     registeredRegions (idempotent, PII-free metadata write to us-east-1). Registration
     never gates metering.

4. Every 15 minutes (metering pipeline; NOT a single hourly Meter Lambda)
   → The discoverer (rate(15m)) queries the metering_pending GSI for each completed hour
     bucket and enqueues one work message per (licenseArn, account, dimension, hour) group;
     the aggregator sums the group's rows and conditionally writes one aggregated_usage
     record; cleanup clears the raw rows' meteringPending; the submitter (rate(5m)) drains
     aggregated_usage and calls BatchMeterUsage. Driven by the metering_pending GSI, not by
     registration state.
   → Calls BatchMeterUsage with CustomerAWSAccountId + LicenseArn per record

5. Buyer cancels / agreement expires
   → EventBridge: Purchase Agreement Ended (us-east-1)
   → Subscription Lambda sets agreementStatus=inactive ONLY. This does NOT change
     subscriptionStatus, stop metering, or trigger a flush — the buyer may still be
     entitled to usage until the license is deprovisioned.

6. License Deprovisioned (us-east-1)
   → Subscription Lambda sets subscriptionStatus=deprovisioning + a deprovisioningExpiry
     (event time + ~1h). This OPENS the ~1-hour final-usage flush window: the pipeline
     flushes any remaining usage, and the events-stack deprovision-cleanup Lambda (rate(15m))
     later sets subscriptionStatus=inactive once deprovisioningExpiry has passed. Once the
     server-side window closes, BatchMeterUsage returns CustomerNotSubscribed.
```

> **Status lifecycle:** agreementStatus: `active` (License Updated) → `inactive`
> (Purchase Agreement Ended). subscriptionStatus: `active` (License Updated) →
> `deprovisioning` (License Deprovisioned opens the ~1-hour flush window) → `inactive`
> (deprovision-cleanup Lambda, once `deprovisioningExpiry` passes). The two move independently and are never
> conflated. Metering decisions follow subscriptionStatus / the metering_pending GSI, not
> agreementStatus or registeredRegions.

### Purchase Agreement Created — seller use cases

The metering path does **not** consume `Purchase Agreement Created`, but it is a useful
signal for other seller workflows. Per the AWS Marketplace SaaS EventBridge integration,
this event fires when *a new agreement is created, an existing agreement is replaced, or an
existing agreement is renewed*, and is delivered to both the manufacturer and proposer
roles. Sellers commonly use it to:

- **Post-sale onboarding / provisioning** — kick off tenant provisioning, welcome emails,
  or CRM/opportunity updates as soon as a buyer subscribes (before the license arrives).
- **Free-trial detection** — call `DescribeAgreement` to determine whether the new
  agreement is a free trial and branch onboarding accordingly.
- **Renewal / replacement tracking** — because the event also fires on replace/renew, use
  `agreement.id` (and any prior-agreement linkage) to track renewals and upgrades.
- **CPPO awareness** — the manufacturer vs proposer variants differ by the presence of a
  `resaleAuthorization` ID; use this to distinguish direct vs channel-partner resale deals.

To act on it, add an EventBridge rule that matches
`detail-type: "Purchase Agreement Created - Manufacturer"` (and/or `- Proposer`) with
`source: "aws.agreement-marketplace"` and route it to your own target — do not add it to the
metering Subscription Lambda. References:

- [Managing SaaS subscription events with Amazon EventBridge](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-eventbridge-integration.html)
- [When a SaaS subscription ends / is cancelled](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-subscriptions.html)

> **Key insight:** The subscribers table lives in `us-east-1` alongside EventBridge. When the metering region is a different region, the register Lambda and the metering pipeline (discoverer/submitter) read it cross-region. **If the seller's metering region is also `us-east-1`, the events stack and main stack are both in `us-east-1` and everything is single-region — no cross-region reads at all.** us-east-1 is a fully supported metering region for `BatchMeterUsage`.
>
> **Multi-region sellers:** Each metering region gets its own main stack (usage table + Lambdas). All regions share the single subscribers table in `us-east-1`. Deploy the events stack once (us-east-1), then deploy the main stack to each metering region — which MAY include us-east-1 itself.
