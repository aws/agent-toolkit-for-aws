## Troubleshooting

### "Product code mismatch"
The entity ID (`prod-xxx`) is not the metering product code. Check `ResolveCustomer` response in Lambda logs for the actual product code, then update `ProductCode` parameter in `template.yaml` and redeploy.

### "InvalidUsageDimensionException"
The dimension key doesn't match what's configured on the product. Verify dimensions in AMMP or via the Catalog API. Add missing dimensions in AMMP before retrying.

### "DisabledApiException" from BatchMeterUsage/MeterUsage
The metering API is regional and supported in MOST — but not all — commercial regions. If a call returns `DisabledApiException`, the chosen region does not yet support the API (e.g. a newly launched region). This is NOT a code or IAM bug: meter in a supported region instead (see the [region-support list](https://docs.aws.amazon.com/marketplace/latest/developerguide/metering-regions.html#batchmeterusage-region-support)). The metering region is the seller's choice (the region where usage occurs, or the nearest supported region), and per-region dedup makes metering the same usage in multiple supported regions correct — there is no `InvalidEndpointRegionException` for a "wrong" supported region.

### "No usage metered"
Metering is driven by the usage table's `metering_pending` GSI, not by subscriber status.
Check:

1. Is the usage writer setting `meteringPending` (the `%Y-%m-%dT%H` hour bucket) on rows as
   it writes them? The meter Lambda only meters rows that appear on that sparse GSI.
2. Are rows written for a COMPLETED hour? The meter Lambda meters the `now-23h … now-1h`
   window and never the in-progress current hour.
3. If you expected a subscriber row: the `License Updated` event (not `Purchase Agreement
   Created`) establishes/refreshes it. Check the subscription Lambda logs in us-east-1 and
   the DLQ for failed processing. A missing subscriber row does NOT block metering (the
   CA UsageRecord is built from the usage rows).

### EventBridge events not arriving
Marketplace events emit ONLY in `us-east-1`. Ensure the events stack is deployed to `us-east-1`, not the seller's preferred region.

**Important:** EventBridge does NOT retroactively deliver past events. If you deploy the events stack late, any subscriptions that occurred before deployment are lost. For those customers, manually query their subscription status or have them re-click "Set up your account" to trigger ResolveCustomer.

**Cross-region pattern (only when the metering region is NOT us-east-1):** If your main metering stack is in a different region (e.g., eu-west-1), the Meter/Register Lambdas read the us-east-1 subscribers table cross-region (already handled by `SUBSCRIBERS_TABLE_REGION=us-east-1`). **If your metering region IS us-east-1, no cross-region setup is needed — deploy both the events stack and the main stack in us-east-1.** us-east-1 is a supported `BatchMeterUsage` region.

### "ExpiredTokenException" on ResolveCustomer
The registration token is **reusable until it expires (~4 hours) — it is NOT one-time-use**, so a buyer who hit an error on the registration page can retry with their ORIGINAL link as long as they are still within that ~4-hour window (re-resolving the same token returns the same result). Once the ~4h has elapsed the token is expired: `ResolveCustomer` returns `ExpiredTokenException`, and the buyer must re-click "Set up your account" from the AWS Marketplace console to mint a FRESH token (a full resubscribe is NOT required). A token that was somehow already consumed/invalidated returns `InvalidTokenException` — same fix. So if a buyer clicked "Set up your account" **days ago** and only retries now, the original link's token is long expired and will NOT resolve — have them click "Set up your account" again for a new token, then retry.

### AccessDeniedException on ResolveCustomer
**Root cause: IAM namespace mismatch.** ResolveCustomer uses `aws-marketplace:ResolveCustomer` — this is a DIFFERENT service namespace from `meteringmarketplace:BatchMeterUsage`. Granting `marketplace:*` or `meteringmarketplace:*` does NOT cover ResolveCustomer.

**The fix:** Your Lambda role needs BOTH actions from DIFFERENT namespaces:

- `aws-marketplace:ResolveCustomer` — for the registration flow
- `aws-marketplace:BatchMeterUsage` — for metering (same namespace as ResolveCustomer, NOT meteringmarketplace)

**Common mistake:** Seller grants `meteringmarketplace:*` thinking it covers all Marketplace APIs. It doesn't — ResolveCustomer is under `aws-marketplace:`, not `meteringmarketplace:`.

> **Note:** Region — ResolveCustomer is regional but the region is the SELLER'S CHOICE; it does NOT have to match where the buyer uses the software or where `BatchMeterUsage` is called, and it does NOT gate metering. It is NOT us-east-1-only. The real constraint is the ACCOUNT (must be the publishing account — see below). If you get AccessDeniedException, the issue is almost always the IAM namespace (`aws-marketplace:`).

When `ResolveCustomer` succeeds, it returns four fields — store ALL of them:

- `CustomerAWSAccountId` — the buyer's AWS account ID (**use this for metering**)
- `LicenseArn` — the license ARN for this agreement (**use this for metering**)
- `CustomerIdentifier` — opaque string (store for reference, NOT for metering)
- `ProductCode` — your metering product code (store for validation)

### BatchMeterUsage returns UnprocessedRecords
The submitter retries the unprocessed records automatically ONCE. If any are STILL unprocessed after that retry, it does NOT raise or DLQ them — it logs an error, emits the **`UsageRecordUnprocessed`** metric, and leaves the records **pending for the next submitter run** (`rate(5m)`), so they are retried, not lost. Common causes: throttling, timestamp out of bounds (older than 24 hours), or a transient service issue. Because the submitter does not raise, this does NOT trip the Lambda `Errors` alarm — the dedicated **`*-usage-unprocessed`** alarm (on the `UsageRecordUnprocessed` metric) is the signal that records are repeatedly failing to meter. A persistent breach means the records are not clearing on retry; investigate the cause (and confirm they are not aging past the 24h window, which would then also trip `UsageSubmissionExpired`).

### Subscription cancelled mid-hour — what happens to metering?
If usage occurred while the subscription was active, the metering record SHOULD be accepted. However, there's a timing window:

- If `Purchase Agreement Ended` event was processed BEFORE your BatchMeterUsage call → you may get `CustomerNotSubscribed`
- If your metering call arrives BEFORE the cancellation is processed → record is accepted normally
- **Best practice:** Check subscription status in your DDB table before metering each customer. If inactive, skip them.
- Usage from before cancellation that was already metered in prior hourly batches is billed normally.

### Contract renewals — which event fires?
On contract renewal, a `License Updated` event fires via EventBridge (NOT `Purchase Agreement Created` and NOT a fabricated "Purchase Agreement Renewed" — no such event exists). **The existing LicenseArn does NOT change on renewal** — it persists across contract periods. The same CustomerAWSAccountId + LicenseArn you've been using continue to work. No metering code changes needed.

**Key facts about renewals:**

- LicenseArn stays the same ← do NOT update customer records
- CustomerAWSAccountId stays the same
- You receive `License Updated` event (not a new agreement event)
- Continue metering with the same identifiers — no action required
- If contract terms change (new dimensions), update entitlement checks only

### RegisterUsage for flat-rate products
RegisterUsage (NOT BatchMeterUsage) is for flat-rate subscription products (AMI, Container, or SaaS with fixed monthly fee):

- Call periodically (e.g., hourly) to confirm subscription is active
- Returns `Success` if active, `CustomerNotSubscribed` if expired
- `ThrottlingException` if called too frequently (back off and retry)
- Does NOT report quantity or usage — just validates subscription status
- Primary use case: AMI and Container products; SaaS flat-rate products typically use EventBridge subscription events instead

### ProductCode vs Product ID confusion
`InvalidProductCode` usually means you're passing the entity ID (`prod-xxx`) instead of the metering product code. To find the correct code:

```
aws marketplace-catalog describe-entity --catalog AWSMarketplace --entity-id <prod-xxx> --region us-east-1
```

Look for the ProductCode field in the response (format varies, often alphanumeric like `4ml54db8vrmjuykaw1psroool`). The code is case-sensitive.

### "TimestampOutOfBoundsException" — rejected submission
The timestamp in each UsageRecord must be within the **last 24 hours**.

- ✅ Valid: any hour within the last 24 hours
- ✅ Valid: e.g., if it's Aug 12 17:00, anything back to Aug 11 17:00
- ❌ Invalid: anything older than 24 hours
- ❌ Invalid: future timestamps

**If you missed an hour:**

- You can backfill up to 24 hours. Beyond 24h requires AWS Support.
- Fix your hourly schedule to prevent future misses.
- For historical corrections, contact AWS Support (Marketplace category).

### ResolveCustomer fails silently — wrong account
ResolveCustomer must be called from the **same AWS account that published the product**. If your registration page is deployed in a different account, the token will not resolve — no buyer can onboard. This is not an IAM permission issue; it's an account-level restriction.

### One bad timestamp rejects the entire batch
BatchMeterUsage validates ALL records in a batch before accepting any. If even ONE record has a timestamp older than 24 hours, the ENTIRE batch is rejected with `TimestampOutOfBoundsException`. Always validate timestamps before sending. Remove invalid records and resubmit the rest.

### GetEntitlements returns empty at onboarding
Do NOT call GetEntitlements immediately after ResolveCustomer. A resolved token only means a customer identity was created — the agreement may not exist yet (it can happen before the agreement is finalized). Call GetEntitlements when you receive the `License Updated` EventBridge event instead.

### Cancellation — flush during the window, no grace period
The wind-down spans two events, and the two subscriber status fields move independently:

1. On `Purchase Agreement Ended` — set `agreementStatus = inactive` ONLY. Do NOT change
   `subscriptionStatus`, stop metering, or flush; the buyer may still be entitled until the
   license is deprovisioned.
2. On `License Deprovisioned` (legacy SNS `unsubscribe-pending`) — set
   `subscriptionStatus = deprovisioning` + a `deprovisioningExpiry` (event time + ~1h). This OPENS
   the ~1-hour final-usage flush window: submit any remaining un-sent usage IMMEDIATELY. The
   pipeline meters this row during the window; the events-stack deprovision-cleanup Lambda
   (`rate(15m)`) then sets `subscriptionStatus = inactive` once `deprovisioningExpiry` has passed
   (time-based finalization — NOT the submitter).
   Once the server-side window closes, `BatchMeterUsage` returns `CustomerNotSubscribed`.
3. Do NOT invert the events (`License Deprovisioned`, not `Purchase Agreement Ended`, opens
   the flush window) and do NOT discard queued records before flushing. There is no
   `deprovisioned` status value. Do NOT rely on a grace period beyond that ~1-hour window.

### `ResourceInUseException` on CreateTable when re-deploying after a rollback
The main stack's `UsageTable` uses `DeletionPolicy: Retain` / `UpdateReplacePolicy: Retain` (intentional — never lose billing usage). If a first deploy fails and rolls back, the usage table is **retained** and left behind, so the next deploy's `dynamodb:CreateTable` collides with the existing table and fails with `ResourceInUseException`. On a **failed first deploy the retained `<prefix>-usage` table is empty** — delete it, then re-deploy:

```bash
aws dynamodb delete-table --table-name <prefix>-usage --region <metering-region>
```

Only do this for a failed/rolled-back initial deploy. Never delete a usage table that has already recorded billable usage.

### Monitoring & alarms (seller-owned)
The deployed stack creates `awsmp-*` CloudWatch metrics/alarms in the SELLER's account for
the revenue-loss signals: per-stage Lambda `Errors` and `Throttles` (discoverer/aggregator/cleanup/submitter/expiry), a "meter did not run"
(low `Invocations`) alarm, two `>24h` usage age-out alarms by stage (EMF `UsageAggregationExpired` for raw usage never aggregated, `UsageSubmissionExpired` for aggregated records never submitted),
plus register/subscription-error and DLQ-depth alarms on the events stack. Business-status
metrics (aged-out, rejected, `UsageRecordUnprocessed`, `CustomerNotSubscribed`, `DuplicateRecord`, `BatchMeterUsageException`)
are emitted via CloudWatch Embedded Metric Format (EMF) from the pipeline Lambda logs — no extra
runtime IAM.

**Alarms that tell you records are being rejected / not metered** (each fires into `AlertsTopicArn`):

- **`*-usage-unprocessed`** (`UsageRecordUnprocessed`) — records still unprocessed after the submitter's one retry (the ONLY alarm-able signal for the `UnprocessedRecords` case; does not trip the `Errors` alarm).
- **`*-usage-rejected`** (`UsageRecordRejected`) — client-side guardrail rejections (summed across all reasons).
- **`*-batchmeterusage-exception`** (`BatchMeterUsageException`) — request-level exception failed a whole call (dimension/license/etc.).
- **`*-customer-not-subscribed`** (`CustomerNotSubscribed`) — per-record status, no active subscription.
- The `>24h` age-out alarms (`UsageAggregationExpired`/`UsageSubmissionExpired`) catch usage that silently never metered. `DuplicateRecord` is dashboard-only (informational), not an alarm.

- Alarms are ALWAYS created. Each alarm's actions wire to an OPTIONAL seller-supplied
  in-region SNS topic (`AlertsTopicArn` on each stack); a CloudWatch alarm can only notify a
  topic in its own region, so use a us-east-1 topic for the events stack and a
  metering-region topic for the main stack.
- Neither the deployer role nor any Lambda publishes to the topic — CloudWatch fires the
  action. **Handling alarms and acting on failures is the seller's responsibility**; AWS
  Marketplace and this skill do not track client-side (seller-account) errors.
- Thresholds, the SNS topic, retention, and KMS keys are seller customization points (the
  `TODO:` parameters in the templates).

### Legacy (non-LicenseArn) integrations — assume nothing about the seller's stack
The packaged meter Lambda and usage-table schema describe the skill's OWN new Concurrent
Agreements integration. For a legacy `ProductCode`-based integration (no `LicenseArn`), do
NOT assume that schema or any specific storage: how usage is stored, where
`ProductCode`/`CustomerIdentifier` come from, how subscriptions are tracked, and how the
final-hour flush is handled all depend on the seller's EXISTING stack. First understand the
seller's integration (ask questions, read their code/config) and ground legacy guidance in
that plus the public AWS documentation. Preserve only the API-level invariants (call
`BatchMeterUsage` with `ProductCode` at the request level and `CustomerIdentifier` in
UsageRecords; the 24h window and per-region dedup; never silently skip customers). Do NOT
impose the CA usage-table keys, the `metering_pending` GSI, `registeredRegions`, or the
`agreementStatus`/`subscriptionStatus` fields on a legacy stack unless it already uses them.

### Client-side rejection reason codes (`UsageRecordRejected`)

When usage is rejected BEFORE it is sent to `BatchMeterUsage`, the meter Lambda records a
terminal `RejectedClientSide` status plus a specific reason on the usage row, and emits the
`UsageRecordRejected` CloudWatch metric (dimensioned by `Reason` + `ProductCode`, watched by
the `awsmp-*-usage-rejected` alarm). A rejected row was never sent, so its dedup grain is
untouched — **fix the source row and re-write it within 24h and it meters normally.** The
reason codes and what to fix:

> For the COMPLETE inventory of client-side guardrails — not just these reason codes, but
> also the timing/window, batch-shaping, and idempotency guardrails applied before
> `BatchMeterUsage` — see `references/client-side-guardrails.md`.

| Reason | What it means / what to fix |
|--------|-----------------------------|
| `NegativeQuantity` | `quantity` is negative. Write non-negative integers. |
| `NonIntegerQuantity` | `quantity` is fractional/decimal (e.g. `2.5`). Aggregate/round in your writer to an integer before persisting — it is NOT truncated for you. |
| `NonNumericQuantity` | `quantity` is not a number. |
| `MissingDimension` | The row has no `dimension`. |
| `TimestampInFuture` / `TimestampOutOfWindow` | The metering hour is in the future or older than the 24h acceptance window. |
| `MalformedTimestamp` | The raw-usage sort-key suffix is not an exact second-precision `YYYY-MM-DDTHH:MM:SS` timestamp (e.g. millisecond/fractional or hour-truncated). Write the suffix at whole-second precision. |
| `MalformedSortKey` | The sort key is missing or has fewer than the three `customerAWSAccountId#dimension#timestamp` segments. |
| `SortKeyMismatch` | The sort key's account/dimension segments don't match the row's own `customerAWSAccountId`/`dimension` attributes (corrupt/mis-keyed row). |
| `MissingCustomerAWSAccountId` | CA row without `customerAWSAccountId`. |
| `MissingLicenseArn` | CA path without a real `licenseArn`. |
| `InvalidLicenseArn` | `licenseArn` is not a syntactically valid License Manager ARN. Rejected client-side so it never poisons a batch. |
| `MissingLegacyIdentifier` | Legacy row with neither `CustomerIdentifier` nor `CustomerAWSAccountId`. |
| `MixedAllocatedAndUnallocated` | Within one `(license, account, dimension, hour)` group, some non-zero rows carry `usageAllocations` and some don't. Make the group all-tagged or all-untagged. |
| `AllocationSumMismatch` | The merged `AllocatedUsageQuantity` sum ≠ the record `Quantity`. Ensure each row's allocations sum to that row's quantity. |
| `TooManyTags` | An allocation has more than 5 tags. |
| `TooManyAllocations` | The merged group produced more than 2500 distinct tag-set allocations for one record. Reduce the tag cardinality per hour. |
| `MissingTagKeyOrValue` / `MalformedAllocations` | A tag lacks a non-empty Key/Value, or `usageAllocations` is not the expected list-of-objects shape. |

### One bad LicenseArn does not block the batch
A malformed/never-valid `LicenseArn` is returned by `BatchMeterUsage` as a request-level
`InvalidLicenseException` (not a per-record status). The meter Lambda validates the
LicenseArn shape client-side (rejecting `InvalidLicenseArn` before batching) and, if a
request-level error still occurs, ISOLATES the offending record by bisecting the batch
(bounded to ⌈log2(batch size)⌉ = 5 levels; at the cap a still-failing sub-batch is left pending for the next run),
so the other co-batched customers are still metered. A true `CustomerNotSubscribed` (valid
LicenseArn, ended/expired agreement, or suspended buyer) is a per-record status handled
terminally — do not retry it.
