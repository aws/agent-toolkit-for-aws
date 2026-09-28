## Concurrent Agreements Integration

> **This section is critical. Read it fully before generating any code.**

AWS Marketplace introduced **Concurrent Agreements** to allow buyers to make multiple purchases of the same product on a single AWS account. This fundamentally changes which fields are used for metering.

### What Changed

| Field | Old Integration (Legacy) | New Integration (Concurrent Agreements — required for new products) |
|-------|--------------------------|---------------------------------------------------------------|
| **Customer identity in UsageRecord** | `CustomerIdentifier` (opaque string) | `CustomerAWSAccountId` (AWS account ID) |
| **Product/agreement identity** | `ProductCode` (at request level) | `LicenseArn` (per UsageRecord) |
| **Deduplication scope** | per (ProductCode + CustomerIdentifier + dimension + hour) | per (CustomerAWSAccountId + LicenseArn + dimension + hour) |

### Correct BatchMeterUsage Payload

```python
# ✅ CORRECT — New integration (Concurrent Agreements)
response = client.batch_meter_usage(
    UsageRecords=[
        {
            'Timestamp': timestamp,
            'CustomerAWSAccountId': '123456789012',  # from ResolveCustomer
            'LicenseArn': 'arn:aws:license-manager::123456789012:license/lic-xxx',  # from ResolveCustomer
            'Dimension': 'MyDimension',
            'Quantity': 5,
        }
    ]
    # NOTE: No ProductCode at request level when using LicenseArn
)
```

### Incorrect Patterns (Common AI-Generated Mistakes)

```python
# ❌ WRONG — Using CustomerIdentifier for metering
response = client.batch_meter_usage(
    UsageRecords=[
        {
            'Timestamp': timestamp,
            'CustomerIdentifier': 'cust-example-id-123',  # WRONG — don't use for new integrations
            'Dimension': 'MyDimension',
            'Quantity': 5,
        }
    ],
    ProductCode='abc123'
)

# ❌ WRONG — Mixing LicenseArn and ProductCode in the same request
response = client.batch_meter_usage(
    UsageRecords=[
        {
            'Timestamp': timestamp,
            'CustomerAWSAccountId': '123456789012',
            'LicenseArn': 'arn:aws:license-manager::123456789012:license/lic-xxx',
            'Dimension': 'MyDimension',
            'Quantity': 5,
        }
    ],
    ProductCode='abc123'  # WRONG — don't include ProductCode when using LicenseArn
)

# ❌ WRONG — Using CustomerIdentifier with LicenseArn
response = client.batch_meter_usage(
    UsageRecords=[
        {
            'Timestamp': timestamp,
            'CustomerIdentifier': 'cust-example-id-123',  # WRONG — use CustomerAWSAccountId
            'LicenseArn': 'arn:aws:license-manager::123456789012:license/lic-xxx',
            'Dimension': 'MyDimension',
            'Quantity': 5,
        }
    ]
)
```

### ResolveCustomer Response — What to Store

`ResolveCustomer` returns `LicenseArn`, `CustomerAWSAccountId`, and `ProductCode` (plus a
legacy, now-deprecated `CustomerIdentifier` that is null for new integrations). Store the first
three, and use `LicenseArn` + `CustomerAWSAccountId` for metering:

```python
result = client.resolve_customer(RegistrationToken=token)

# ResolveCustomer returns a TOP-LEVEL LicenseArn (plus CustomerAWSAccountId + ProductCode):
license_arn = result['LicenseArn']                    # ✅ top-level field, e.g. arn:aws:license-manager::...
customer_aws_account_id = result['CustomerAWSAccountId']  # ✅ USE THIS (with LicenseArn) for metering
product_code = result['ProductCode']                  # Store for validation only, NOT for metering
# result['CustomerIdentifier'] is DEPRECATED for new SaaS integrations and is null/absent —
# do NOT rely on it, and do NOT treat it as the LicenseArn. It is legacy-only (pre-CA).
```

> **Key Fact — ResolveCustomer returns LicenseArn directly:** `ResolveCustomer` returns a **top-level `LicenseArn`** field along with `CustomerAWSAccountId` and `ProductCode`. For NEW (Concurrent Agreements) integrations, `CustomerIdentifier` is **deprecated and null/absent** — do NOT use it and do NOT treat its value as the LicenseArn. Persist `LicenseArn` + `CustomerAWSAccountId` from the ResolveCustomer response; both are also reaffirmed by the `License Updated` EventBridge event (a row can alternatively be created from that event when a seller never calls ResolveCustomer). Downstream (BatchMeterUsage, entitlement checks) require `LicenseArn` + `CustomerAWSAccountId`.
>
> **Key Fact:** ResolveCustomer succeeding only means the registration token is valid — it does NOT confirm the subscription is active. Wait for the EventBridge `License Updated` / subscribe-succeed event before starting to meter.

### Unified Subscribers Table (DynamoDB schema)

Store subscribers in a SINGLE unified table (not separate customer-profiles + subscriptions tables). The primary key depends on the integration pattern:

| Pattern | Partition Key (PK) | Sort Key (SK) | Why |
|---------|-------------------|---------------|-----|
| **Concurrent Agreements (default, new products)** | `licenseArn` | `customerAWSAccountId` | One buyer can hold MULTIPLE active licenses for the same product; keying on `licenseArn` tracks each agreement independently and prevents double-billing |
| **Legacy (pre-CA, grandfathered)** | `customerAWSAccountId` | — | One buyer = one subscription; no concurrent agreements |

Unified table attributes (PII-FREE): `licenseArn` (PK), `customerAWSAccountId` (SK), `productCode`, `agreementId`, `agreementStatus` (active / inactive — agreement lifecycle), `subscriptionStatus` (active / deprovisioning / inactive — license lifecycle; there is no `deprovisioned` value), and `registeredRegions` (a DynamoDB String Set (SS) of AWS Region names where the buyer was registered, added idempotently via `ADD` — reference only, never gates metering). It does NOT carry `customerIdentifier` for a new CA integration (deprecated, legacy-only) and does NOT carry buyer PII / registration-form data — that lives in the per-Region `customer-profile` table (keyed `licenseArn` PK + `customerAWSAccountId` SK, seller GSIs), written in-region by the register Lambda. Keeping the subscribers table PII-free is why it can safely live in us-east-1 even for opt-in-Region products. The subscribers table defines two GSIs so lookups never need a `Scan`: `customerAWSAccountId-index` (register lookup / all agreements for one buyer) and `agreementId-index` (subscription lookup when an event omits `license.arn`).

> **Critical:** For CA products, `licenseArn` MUST be the partition key — NOT `customerAWSAccountId` and NOT `licenseArn` as a sort key. A buyer with two concurrent agreements has two rows (same `customerAWSAccountId`, different `licenseArn`). Keying by account alone would collapse them and cause double-billing or lost usage. The usage table is likewise keyed by `licenseArn` (PK) + `customerAWSAccountId#dimension#timestamp` (SK) so usage is attributed per-agreement. This unified single-table design aligns with the **AWS Marketplace Serverless SaaS Integration reference architecture**. Metering is driven by the usage table's `metering_pending` GSI (not by subscriber/registration state): the meter Lambda queries that GSI for licenseArns with pending usage, builds each UsageRecord entirely from the usage rows (which carry `customerAWSAccountId`), and only looks up the subscriber row to read/update `subscriptionStatus`. Usage rows are keyed by the real `licenseArn` — there are no `pending:`-prefixed placeholder rows.

The table lives in `us-east-1` alongside the EventBridge events (that is the only region where marketplace lifecycle events are emitted).

### Key Rules

1. **New products:** MUST use `CustomerAWSAccountId` + `LicenseArn` per UsageRecord. Do NOT include `ProductCode` at the request level.
2. **Existing (legacy) products:** Can continue using `CustomerIdentifier` + `ProductCode`, but should migrate to the new pattern.
3. **Never mix:** Do NOT send `LicenseArn` and `ProductCode` for the same customer in the same hour. This causes **duplicate billing**.
4. **`CustomerIdentifier` is NOT for metering:** It is an opaque identifier for customer lookup. Use `CustomerAWSAccountId` in UsageRecords.
5. **`LicenseArn` is per-agreement:** A single buyer can have multiple `LicenseArn` values for the same product. Each represents a separate agreement with separate usage tracking.

### Metering Cadence & Deduplication

- **Call frequency:** Once per hour (use EventBridge `rate(1 hour)` schedule)
- **Timestamp window:** Each UsageRecord timestamp must be within the **last 24 hours** of the event. Anything 24 hours or older is rejected with `TimestampOutOfBoundsException` (and one bad timestamp rejects the whole batch). A 6-hour month-boundary grace period applies: previous-month records are accepted until 06:00 UTC on the 1st of the next month.
- **DuplicateRecord = first-write-wins and REPORTED (NOT simply "benign"):** If you resend a record for the same (CustomerAWSAccountId + LicenseArn + dimension + hour), the API returns that record with `Status = DuplicateRecord` (NOT `Success`, and present in the response — not silently absent). The FIRST submitted quantity stays final/billed; a resubmission with a DIFFERENT quantity is NOT billed. If a seller intended to correct 5→10, the correction is not applied and they UNDER-BILL by 5. Warn sellers: an unexpected DuplicateRecord may mean under-reporting. Aggregate usage BEFORE submitting so you never need to correct.
- **Idempotent retries:** Retrying the SAME record/quantity on a transient failure is safe (returns DuplicateRecord, harmless). Never retry to change a quantity — that will not work.
- **25-record batch limit + 1 MB request-size limit:** Each `BatchMeterUsage` call accepts max 25 UsageRecords **AND** the total request payload must be ≤ **1 MB**. These are two INDEPENDENT limits — a batch of ≤25 records can still be rejected for SIZE if the records are large (many/large `usageAllocations` tag-sets, long ARNs). If you have 25 valid records but the request is rejected for size, split into smaller batches (fewer records per call) so each request stays under 1 MB — it is the byte size, not the record count, that is over. **Rate limit: 10 `BatchMeterUsage` requests/second per account per region** (documented quota) — the serial submitter stays within it.

### Why EventBridge (Not SNS) Is Required

The shift to `CustomerAWSAccountId` + `LicenseArn` also dictates which notification mechanism you must use:

| Mechanism | Identifies customer by | Compatible with new integration? |
|-----------|----------------------|----------------------------------|
| **SNS** (legacy `aws-mp-subscription-notification-*`) | `CustomerIdentifier` only | ❌ No — SNS notifications do not include `CustomerAWSAccountId` |
| **EventBridge** (`aws.agreement-marketplace`) | `CustomerAWSAccountId` (via agreement/acceptor details) | ✅ Yes |

**The problem:** Legacy SNS subscription notifications (`subscribe-success`, `unsubscribe-success`, etc.) identify the customer using `CustomerIdentifier`. But since new integrations must key everything on `CustomerAWSAccountId`, you cannot reliably match an SNS notification to a customer record keyed by `CustomerAWSAccountId` without an extra lookup/mapping step.

**EventBridge events** (`Purchase Agreement Created`, `Purchase Agreement Ended`, `License Deprovisioned`, etc.) include the buyer's AWS account ID in the event detail, making them directly compatible with `CustomerAWSAccountId`-based customer records.

**Bottom line:** If you are building a new integration, use **EventBridge only**. Do not set up SNS subscription topics. This skill deploys an EventBridge-based events stack in `us-east-1` for this reason.

> **Note for existing products migrating:** If you currently use SNS and are migrating to `CustomerAWSAccountId`-based metering, you must also migrate your subscription event handling from SNS to EventBridge. Running both during migration is safe — just ensure your customer table can be updated by either path.

### Fallback for Legacy Products

**The path is chosen by the seller's EXISTING integration, not by the `ResolveCustomer` response.** `ResolveCustomer` returns a top-level `LicenseArn` for SaaS products regardless of whether the integration is old or new, so its response is NOT the signal for which path to use.

- **New integrations** always use the Concurrent Agreements pattern: `CustomerAWSAccountId` + `LicenseArn` per UsageRecord.
- **Existing (legacy) integrations** that already meter with `ProductCode` + `CustomerIdentifier` can continue on that path. For an existing seller, the skill must understand the seller's current integration/code and support or migrate it — it does not force this skill's reference `register.py` / metering-pipeline handlers onto them.

The reference metering pipeline (`scripts/metering_core.py` + `scripts/submitter.py`) defaults to the CA (`LicenseArn`) path. A `ProductCode` fallback branch exists only to support a seller whose stored records predate CA (identified by a non-ARN `licenseArn` value), NOT because `ResolveCustomer` returned no LicenseArn:

```python
if str(customer.get('licenseArn', '')).startswith('arn:'):
    record['LicenseArn'] = customer['licenseArn']
    # No ProductCode at request level
else:
    # Legacy stored record (pre-CA): use ProductCode + CustomerIdentifier
    kwargs['ProductCode'] = PRODUCT_CODE
```

### Deprovisioning / Final Metering

Two independent status fields track different lifecycles and are NOT conflated:
`agreementStatus` (agreement) and `subscriptionStatus` (license). Metering decisions follow
the license lifecycle only:

1. **`Purchase Agreement Ended`** — set `agreementStatus = 'inactive'` ONLY. This is a
   status update; it does NOT change `subscriptionStatus`, stop metering, or trigger a
   flush. The buyer may still be entitled to usage until the license is deprovisioned.
2. **`License Deprovisioned`** — set `subscriptionStatus = 'deprovisioning'` + a `deprovisioningExpiry`
   (event time + ~1h). This OPENS the ~1-hour final-usage flush window: submit any remaining usage
   IMMEDIATELY. The pipeline meters this row during the window; the events-stack deprovision-cleanup
   Lambda (`rate(15m)`) then sets `subscriptionStatus = 'inactive'` once `deprovisioningExpiry` has
   passed (time-based finalization — NOT the submitter). Once the server-side window closes,
   `BatchMeterUsage` returns `CustomerNotSubscribed` (a terminal status — do not retry).

> **Do not invert these.** `License Deprovisioned` (not `Purchase Agreement Ended`) opens
> the flush window. Do NOT stop metering or flush on `Purchase Agreement Ended`, and do NOT
> discard queued records before flushing (that loses revenue). There is no `deprovisioned`
> status value — the license lifecycle is `active` → `deprovisioning` → `inactive`.
