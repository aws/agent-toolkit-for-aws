# Setup Path — Deploy New Metering Integration

## Product Type Gate

> **IMPORTANT:** Before proceeding, verify the product is SaaS with usage-based pricing (ExternallyMetered dimensions). Query the Catalog API after getting credentials. If the product is AMI, Container, or SaaS Contract-only, respond that the product type is out of scope and redirect to the [public AWS documentation](https://docs.aws.amazon.com/marketplace/).

## Seller Questionnaire

Ask ALL five questions before generating any code:

**Q1: Product code and dimensions?**

- "What is your Marketplace product code (or entity ID) and which usage dimensions do you want to meter?"
- They MUST provide the product code (like `4ml54db8vrmjuykaw1psroool`) and at least one dimension key.

**Q2: Are you the ISV/seller or building for one?**

- Confirms they have access to the seller account and AWS Marketplace Management Portal.

**Q3: Multi-region or single region?**

- Events stack is always in us-east-1 (marketplace lifecycle events emit only there). Deploy a metering (main) stack in **each** region where the seller runs and meters their SaaS, each with its own regional usage table.
- **`BatchMeterUsage` is a regional API** — call it in-region from where the usage occurred (for SaaS on another cloud or on-premise, use the nearest AWS region). There is no benefit to routing all usage through one region, and doing so works against data-residency (e.g. EU usage should stay in `eu-west-1`).
- **Metering records are per-region.** De-duplication is per **CustomerAWSAccountId + LicenseArn + dimension + hour** (SaaS CA products), scoped to the region the record was submitted in, first-write-wins within that region. A buyer whose usage genuinely spans regions is metered in each region where the usage actually occurred — the same customer/dimension/hour submitted in different regions is expected and correct. Do NOT force all of a customer's usage into a single region and do NOT funnel every customer's usage into one global table.
- Supported regions: see [BatchMeterUsage region support](https://docs.aws.amazon.com/marketplace/latest/developerguide/metering-regions.html#batchmeterusage-region-support).

**Q4: API stage name (mandatory)?**

- "What API Gateway stage name should the registration endpoint use — for example `v1`, `live`, or `prod`? This is your choice and there is no default."
- The `StageName` template parameter has **no default** and an `AllowedPattern` that rejects an empty value. The seller MUST supply a non-empty value; there is no silent default and no fallback to `prod`. A direct `sam deploy` fails fast at the template level if it is missing/empty, and `deploy.sh` performs the same check (pass the seller's choice via `STAGE_NAME`; the fulfillment URL tracks it).

**Q5: Does a metering stack already exist for this product?**

- If yes (or the skill otherwise determines one exists), treat this as a modify/extend case: gather context on the seller's existing stack and inspect it before changing anything. Do NOT assume it follows this skill's `awsmp-*` naming — see `references/existing-sellers.md`.

> **CCP is out of scope (handled at the Product Type Gate above).** If the product is Contract with Consumption Pricing, contract-only, AMI, or Container, respond that it is out of scope and redirect to the [public AWS documentation](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-integrate-contract.html); do NOT provide CCP implementation steps, code, or API sequences.
>
> **Concurrent Agreements is the default.** All new products use `CustomerAWSAccountId` + `LicenseArn`. Do not ask the seller — this is the default for all new products.

## Product Portfolio: Stack Naming Convention

| Component | Pattern | Example |
|-----------|---------|---------|
| Events stack | `awsmp-events-stack` | Shared across all products, us-east-1 |
| Main stack | `<prefix>-metering` | `awsmp-prod-abc123-metering` |
| Prefix | `awsmp-<env>-<product-shortcode>` | `awsmp-prod-u32tk6e2xza22` |

## Supported Features

| Feature | Status |
|---------|--------|
| SaaS Usage (PAYG) | ✅ Supported |
| Concurrent Agreements | ✅ Supported |
| Contract with Consumption Pricing (CCP) | ❌ Out of scope — redirect to [public AWS docs](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-integrate-contract.html) |
| [Vendor Metered Tagging (VMT)](https://aws.amazon.com/blogs/aws-cloud-financial-management/launch-aws-marketplace-vendor-metered-tagging/) | ✅ Supported |
| Multi-region SaaS runtime | ✅ Supported — `BatchMeterUsage` is regional; deploy a main stack per metering region and meter in-region (nearest AWS region for on-prem/other-cloud). Metering records are per-region; the same customer/dimension/hour can be metered in each region where that customer's usage occurred. Do NOT force all of a customer's usage into one region. |
| Multi-product portfolio | ✅ Supported |
| AMI/Container metering | ❌ Out of scope — redirect to [public AWS docs](https://docs.aws.amazon.com/marketplace/) |
| SaaS Contract-only (GetEntitlements) | ❌ Out of scope — redirect to [public AWS docs](https://docs.aws.amazon.com/marketplace/) |

## Prerequisites

- AWS account with Marketplace seller registration
- Product listed in AWS Marketplace (product code assigned)
- At least one usage dimension configured on the product
- Product must be **SaaS with ExternallyMetered dimensions** (verified via Catalog API)

## AWS Credentials (ephemeral-first — configure before deploying)

Have the seller configure **ephemeral** credentials in their own environment before you
deploy or run tests — do NOT ask them to hand over long-lived IAM user access keys, and do
NOT ask for credentials outright as a first step. Preferred order:

1. **IAM Identity Center / SSO** — `aws configure sso && aws sso login`
2. **STS assume-role** — assume a dedicated deployer role (session includes `AWS_SESSION_TOKEN`)
3. **Last resort:** short-lived STS session env vars (with `AWS_SESSION_TOKEN`) — never long-lived user keys

Then verify with `aws sts get-caller-identity` and confirm the correct seller account before
proceeding. The same ephemeral credentials are used for Catalog API validation, deployment,
and integration testing.

> For the ephemeral-first setup commands and the full least-privilege IAM deployer policy
> (conditioned trust policy + permissions-boundary'd `iam:CreateRole`), load
> `references/iam-credentials.md`.

## Validate Product Code and Dimensions via Catalog API

After credentials are verified, run this command. Do NOT skip — incorrect values cause runtime failures.

```bash
aws marketplace-catalog describe-entity \
  --catalog AWSMarketplace \
  --entity-id <PRODUCT_ID> \
  --region us-east-1 \
  --query 'Details' --output text | python3 -c "
import sys, json
details = json.loads(sys.stdin.read())
print('=== Dimensions (use these Key values for metering) ===')
for d in details.get('Dimensions', []):
    print(f\"  {d['Key']} - {d['Name']} ({d['Unit']}) - Types: {d.get('Types', [])}\")
"
```

> **Important:** The product ID (`prod-xxx`) is NOT the product code. Always verify via the Catalog API or AMMP.

## Tool Requirements

- A recent AWS SAM CLI (`sam --version`) and AWS CLI v2 (`aws --version`). Verify the installed versions work; consult the SAM CLI / AWS CLI release notes if a command is unsupported.

## Deployment Steps

> For the full 6-step deployment walkthrough, load `references/deployment-steps.md`.

Summary:

1. Generate SAM template + Lambda code
2. Deploy Events Stack (us-east-1) — shared EventBridge rules
3. Deploy Main Stack (seller's region) — Lambda + DynamoDB + API Gateway
4. Configure Fulfillment URL in AMMP
5. Test End-to-End (subscribe → resolve → write conforming usage row → discoverer → aggregator → submitter → verify `Aggregated` + `Success`)
6. Validate via CloudTrail logs

## ⚠️ Usage Ingestion — Seller's Responsibility

The deployed stacks provide the **metering pipeline** (discoverer → aggregator → cleanup → submitter; a shared subscription path) that reads usage rows from the usage DynamoDB table and submits them to `BatchMeterUsage`. However, **writing usage rows into the table is entirely the seller's responsibility.**

The seller must build:

- **Usage capture** — instrument their application to record per-customer, per-dimension usage events
- **Cross-account aggregation** (if multi-account runtime) — collect usage from all runtime accounts into the central metering account
- **Write pipeline** — durably write usage rows into the usage DynamoDB table, in the exact schema below, before the hour is aggregated

The pipeline meters whatever conforms to the schema; it does not distinguish billable from non-billable usage and applies no business filtering. The seller must ensure only metered-eligible usage lands in the table.

**Recommended pattern:** Durable buffer (SQS/Kinesis) → per-second/hour idempotent aggregator (Lambda/Step Functions) → usage DynamoDB table.

### Usage-row writer contract (what every row MUST look like)

The pipeline reads rows on trust for what it cannot re-derive, and reason-code-rejects (raw-row `meteringStatus = RejectedClientSide`, `UsageRecordRejected` metric) what it can check. A row MUST have:

| Attribute | Requirement | If wrong |
|---|---|---|
| `licenseArn` (PK) | The buyer's LicenseArn from the `License Updated` event (or, legacy pre-CA, the ProductCode fallback). | Group keyed wrong / not billed for the right buyer. |
| `customerAWSAccountId_dimension_timestamp` (SK) | EXACTLY `{customerAWSAccountId}#{dimension}#{YYYY-MM-DDTHH:MM:SS}` — **whole-second** precision in **UTC**, NOT millisecond/`.000Z` and NOT local time. The account + dimension segments MUST equal the row's own `customerAWSAccountId` / `dimension` attributes. | Rejected client-side with one code per condition (in order): `MalformedSortKey` (empty / fewer than 3 `#`-segments) → `SortKeyMismatch` (account or dimension segment ≠ the row's own attribute) → `MalformedTimestamp` (timestamp segment not exact whole-second, incl. millisecond/fractional or hour-truncated). A local-time timestamp instead buckets in the wrong UTC hour (silently mis-metered). |
| `customerAWSAccountId`, `dimension`, `timestamp` | Stored ALSO as separate top-level attributes (the pipeline reads these). `dimension` present and non-empty; `timestamp` in UTC. | `MissingDimension` reject; or discovered under the wrong group. |
| `meteringPending` | Set to the row's hour bucket `YYYY-MM-DDTHH` in **UTC** — this is the GSI HASH that makes the row discoverable, and the pipeline queries it by UTC bucket (`now` is UTC). It MUST equal the UTC hour of the row's own timestamp. The pipeline REMOVES it when the row is finalized; the writer sets it only on a new pending row. | Wrong value (incl. a LOCAL-time bucket) ⇒ row is discovered under the wrong hour and **silently never metered**, or malformed ⇒ never discovered at all. **The pipeline cannot catch this — it is verified only by the hands-on test.** |
| `quantity` | Non-negative INTEGER (no negative, fractional, or non-numeric). | `NegativeQuantity` / `NonIntegerQuantity` / `NonNumericQuantity` reject. |
| `usageAllocations` (optional, VMT) | If present, exact BatchMeterUsage `UsageAllocation` shape; all-or-nothing across a group's non-zero rows; ≤2500 tag-sets; ≤5 tags each; allocations sum to the row quantity. | `MalformedAllocations` / `TooManyTags` / `TooManyAllocations` / `AllocationSumMismatch` / `MixedAllocatedAndUnallocated` reject. |
| `ttl` (optional) | Epoch-seconds; only honored if the raw-table TTL is enabled. MUST be far enough out that a row is never TTL-deleted before it is metered (the template validates the floor). | Premature deletion of un-metered usage. |
| `createdAt`, `updatedAt` (recommended) | ISO-8601 UTC audit timestamps — `createdAt` set once when the writer first inserts the row, `updatedAt` refreshed on any rewrite. Audit/reference metadata only (not keyed, not billing-relevant). The pipeline stamps `updatedAt` when it finalizes a row (and `createdAt` if absent); the seller SHOULD stamp them at write time for its own rows. | No metering impact; only lost audit trail if omitted. |

> **The `meteringPending` accuracy point is the one the pipeline cannot self-correct.** If the writer stamps a bucket that disagrees with the row's timestamp hour, the row is discovered under a bucket whose read-prefix its sort key does not match, so its quantity is silently omitted and its marker is never cleared. There is no client-side reject for it (the row is effectively invisible to the group that would validate it). Getting `meteringPending == floor(timestamp, hour)` right is a hard writer obligation — the hands-on test below is how the seller confirms it.

### What the seller owns once the stacks are in place

After the two stacks deploy successfully, the skill SHALL make these ongoing seller responsibilities explicit:

1. **Write usage rows** conforming to the contract above (the only thing that makes metering happen).
2. **Wire the alarms** — subscribe an SNS topic / notification to the created alarms (`AlertsTopicArn`); the stack raises them but acting on them is the seller's job (`deployment-steps.md`).
3. **Watch the health dashboards** — especially `UsageRecordRejected` (writer-contract violations, sliced by `Reason`), `BatchMeterUsageException` / `CustomerNotSubscribed` (terminal, server-side), and `UsageAggregationExpired` (raw usage aged out before aggregation) / `UsageSubmissionExpired` (aggregated but not submitted in time).
4. **Manage dimensions in the catalog** — add/rename pricing dimensions in AMMP; no redeploy is needed (dimension validity is server-authoritative).
5. **Set the Fulfillment URL** in AMMP to the **branded registration page** URL (the CloudFront/custom-domain front-end that captures buyer/KYB fields and calls `RegistrationUrl`); the raw `RegistrationUrl` is only a bare-bones smoke-test fallback. See `references/registration-page.md`. (A one-time manual seller step.)
6. **Own the deployed source** — the generated template + handlers live in the seller's workspace; re-deploy from there and customize the marked `TODO:` sections.

The skill SHALL then **walk the seller through the hands-on end-to-end test in `references/deployment-steps.md` Step 5** — subscribe → verify registration/EventBridge → write a conforming test usage row (correct second-precision sort key + matching `meteringPending`) → trigger discoverer/aggregator/submitter → verify the raw row finalizes as `Aggregated` and the aggregated record reaches `Success`. This exercise is how each writer-contract expectation above is demonstrated and confirmed to be met, and how a mis-stamped `meteringPending` (otherwise silent) is surfaced.

## Additional References

- **Concurrent Agreements details:** Load `references/concurrent-agreements.md`
- **Architecture diagram + data model:** Load `references/architecture.md`
- **Troubleshooting errors:** Load `references/troubleshooting.md`
- **Existing sellers (modify/extend):** Load `references/existing-sellers.md`

## Common Mistakes

1. Using `CustomerIdentifier` instead of `CustomerAWSAccountId` in UsageRecords
2. Mixing `ProductCode` and `LicenseArn` for the same customer/hour
3. Using SNS instead of EventBridge (SNS lacks `CustomerAWSAccountId`)
4. Deploying EventBridge rule in seller's region instead of us-east-1
5. Dimension key not defined in the catalog — `BatchMeterUsage` fails the call with a request-level `InvalidUsageDimensionException` (server-authoritative; the submitter isolates the record → `RejectedClientSide` reason `InvalidUsageDimensionException`; surfaced on the `BatchMeterUsageException` metric/alarm, not billed). Fix the key or add the dimension in AMMP; no redeploy needed.
6. Writing the sort-key timestamp at millisecond precision (`.000Z`) instead of whole-second `YYYY-MM-DDTHH:MM:SS` — rejected as `MalformedTimestamp`.
7. Stamping `meteringPending` with an hour that doesn't match the row's timestamp hour — the row is discovered under the wrong bucket and **silently never metered** (the one failure the pipeline can't catch; verify via the Step 5 test).
8. Activating metering on `Purchase Agreement Created` — that event carries no licenseArn and is not consumed by the metering path. Metering follows `License Updated` (access granted) and the usage table's `metering_pending` GSI.

## Security

- Lambda needs ONLY `aws-marketplace:BatchMeterUsage` + DynamoDB read/write
- EventBridge rule scoped to `source: ["aws.agreement-marketplace"]`
- Enable CloudTrail for audit
- Separate accounts for prod vs test

## Unified Subscribers Table (exact schema)

Use ONE unified DynamoDB table for SUBSCRIPTION/AGREEMENT STATE (do NOT split subscription state across separate "customer-profiles" + "subscriptions" tables). Buyer PII / registration-form data is a SEPARATE concern and lives in its own per-Region `customer-profile` table (below) — that separation is intentional (keeps the subscribers table PII-free), not the old split-subscription-state anti-pattern.

- **Concurrent Agreements (default):** `licenseArn` = PARTITION key (HASH), `customerAWSAccountId` = SORT key (RANGE). LicenseArn MUST be the partition key. One buyer with N concurrent agreements = N rows (same customerAWSAccountId, different licenseArn), tracked independently.
- **Legacy (pre-CA):** `customerAWSAccountId` = partition key (understand the seller's actual schema first; do not impose the CA layout).
- **Attributes on a new CA record (PII-FREE):** `productCode`, `agreementId`, `agreementStatus` (active/inactive — agreement lifecycle), `subscriptionStatus` (active/deprovisioning/inactive — license lifecycle; no `deprovisioned` value), `registeredRegions` (DynamoDB String Set of AWS Region names, added idempotently via `ADD`, reference-only). It does NOT carry `customerIdentifier` (deprecated, legacy-only) and does NOT carry buyer PII / registration-form data. Buyer PII lives in the per-Region `customer-profile` table (`awsmp-<productCode>-customer-profile`, PK `licenseArn` + SK `customerAWSAccountId`, seller-requested GSIs), written in-region by the register Lambda — so the subscribers table stays PII-free and safe in us-east-1 for opt-in-Region products.
- **Two GSIs** so lookups never need a `Scan`: `customerAWSAccountId-index` (register lookup / all agreements for one buyer) and `agreementId-index` (subscription lookup when an event omits `license.arn`).

**Usage table:** keyed by `licenseArn` (PARTITION key) + `customerAWSAccountId#dimension#timestamp` (SORT key) — the sort-key value is the `#`-delimited composite `{customerAWSAccountId}#{dimension}#{timestamp}` at **second precision** (`YYYY-MM-DDTHH:MM:SS`), bounding a group at ≤3600 rows/hour. Each item ALSO stores `customerAWSAccountId`, `dimension`, and `timestamp` as top-level attributes so the pipeline reads them without parsing the sort key. It has a sparse `metering_pending` GSI (HASH = `meteringPending` hour-bucket, RANGE = `licenseArn`): the usage writer sets `meteringPending` when it writes a row, and the pipeline clears it after the row's aggregation group reaches a terminal result.

## Metering pipeline flow (recite when asked how metering works)

Metering is a decoupled, SQS-connected pipeline driven by the usage table's `metering_pending` GSI, NOT by registration state — not every seller uses ResolveCustomer (some obtain the LicenseArn via EventBridge or SDDS and never register), so metering must not depend on a registered subscriber. The stages:

1. **Discoverer** (hourly, `metering_pending` GSI): queries the GSI for a completed hour bucket and enqueues ONE work message per `(licenseArn, customerAWSAccountId, dimension, hourBucket)` group onto the work SQS queue. It only meters completed hours in the `now-23h … now-1h` window (never the in-progress hour) and only once an hour has been closed for `MeteringLockHours` (default 1). It does NOT read group rows, aggregate, submit, or write back. The same discoverer, on its age-out targets, terminally expires raw rows older than 24h that were never aggregated (REMOVE `meteringPending`, `meteringStatus=AggregationExpired`, `UsageAggregationExpired` metric).
2. **Aggregator** (SQS-triggered, one message = one group): reads the group's rows via the targeted `begins_with` prefix (streamed fold), takes `customerAWSAccountId`/`dimension` from the rows (no subscriber lookup), aggregates all second-precision rows into ONE quantity, and MERGES seller-provided `usageAllocations`. It runs the structural/format client-side validations (dimension present; second-precision sort key with matching segments; non-negative integer quantity; timestamp window; identifier shape; allocation invariants) — dimension NAME validity is left to `BatchMeterUsage`. A valid group is written as ONE record via conditional `PutItem` into the `awsmp-aggregated-usage` table (idempotency commit point); a rejected group is finalized `RejectedClientSide` with a reason code + `UsageRecordRejected` metric.
3. **Cleanup** (SQS-triggered): after the aggregated record is durably written, clears `meteringPending` on the raw rows and stamps `meteringStatus=Aggregated`. **The raw usage table NEVER carries the submission outcome** — its `meteringStatus` domain is exactly `Aggregated` / `RejectedClientSide` / `AggregationExpired`.
4. **Submitter** (EventBridge `rate(5 minutes)`, `reserved=1`): reads pending records from `awsmp-aggregated-usage` over the `now-23h … now-1h` window OLDEST-first, coalesces ≤25 UsageRecords per `BatchMeterUsage` call, retries `UnprocessedRecords` once, and writes the returned `MeteringRecordId` + per-record `Status` (`Success`/`DuplicateRecord`/`CustomerNotSubscribed`/…) back **onto the `awsmp-aggregated-usage` record only** (REMOVE its `meteringPending`). Records still unprocessed after the retry keep their marker and the invocation FAILS so the `Errors` alarm fires. It finalizes `deprovisioning` subscribers after a successful final flush.
5. **Expiry** (separate EventBridge `rate(5 minutes)` target, `reserved=1`): terminally expires a pending `awsmp-aggregated-usage` record that can no longer be metered — its hour is >24h in the past, OR it is a previous-month record and the month-end grace has closed (on/after 06:00 UTC on the 1st) — REMOVE `meteringPending`, `meteringStatus=SubmissionExpired`, `UsageSubmissionExpired` metric.

**Zero-quantity groups:** while its hour is still inside the window, a group summing to 0 is left pending (not submitted) so the seller can still write usage for that hour — submitting a 0 early would lock the hour at 0 via first-write-wins dedup. At the oldest edge of the window it IS submitted as `Quantity: 0` to close the hour out.

**Throughput / concurrency:** the pipeline uses FIXED concurrency (there is no single meter Lambda and no `MeterReservedConcurrency` parameter): discoverer `ReservedConcurrentExecutions=30`, aggregator SQS-ESM `MaximumConcurrency: 50` with `ReportBatchItemFailures`, cleanup SQS-ESM `MaximumConcurrency` (bounded per-partition writer), submitter and expiry `reserved=1`. SQS absorbs bursts, so scale comes from queue depth draining rather than raising Lambda concurrency. If a seller needs higher sustained metering TPS than the `reserved=1` serial submitter + `BatchMeterUsage` rate limit allow, advise them to contact AWS Marketplace Seller Operations rather than raising these values unsafely.

## Deployment modes — the aggregation pipeline is OPTIONAL

The full pipeline above (discoverer → aggregator → cleanup → submitter → submission-expiry) is the default and is for sellers who write RAW per-second usage rows. A seller who **already produces finalized hourly aggregated records upstream** can instead choose **direct-submit** mode (`DEPLOYMENT_MODE=direct-submit`): the skill deploys ONLY the `aggregated_usage` table + submitter + submission-expiry + the register/subscription path — no raw usage table, no work/cleanup queues, and no discoverer/aggregator/cleanup. The seller writes finalized records straight into `awsmp-aggregated-usage`:

| Attribute | Requirement |
|---|---|
| `licenseArn` (PK) | buyer LicenseArn (or legacy ProductCode fallback) |
| `account_dimension_hour` (SK) | `{customerAWSAccountId}#{dimension}#{YYYY-MM-DDTHH}` (hour precision, **UTC**) |
| `customerAWSAccountId`, `dimension`, `hourBucket`, `quantity` | top-level attributes (`hourBucket` in UTC) |
| `meteringPending` | the hour bucket `YYYY-MM-DDTHH` in **UTC** (makes the record discoverable by the submitter, which queries by UTC bucket) |

> **Finalize before insert (critical).** ANY record present in `aggregated_usage` MAY be picked up and submitted on the next 5-minute submitter run. Write a record ONLY when it is FINAL for its `(licenseArn, customerAWSAccountId, dimension, hour)` — a second write for an already-submitted group returns `DuplicateRecord` (first-write-wins) and the later quantity is **not billed** (under-billing risk). The seller owns the upstream aggregation/idempotency in this mode; the skill provides no raw-row aggregation.

The alarms and health dashboard are created to match the deployed components — direct-submit mode omits the aggregation-stage alarms/widgets (aggregator/cleanup/discoverer, work/cleanup DLQ, `UsageAggregationExpired`, `UsageRecordRejected`) and shows a submitter/expiry-focused dashboard.

**Mode is not a one-way door.** A seller can start in either mode and switch later (change `DEPLOYMENT_MODE` and re-deploy), and the skill can layer on additional implementation as needs evolve. Switching an actively-metering live stack is a stack UPDATE that adds/removes the mode-specific resources: the raw `usage` table is `Retain` (its data survives), but moving to direct-submit REMOVES the work/cleanup queues + discoverer/aggregator/cleanup — confirm the blast radius with the seller before flipping the mode on a live stack.

## Vendor Metered Tagging (VMT)

VMT lets sellers break usage down by seller-defined tags. **The allocation breakdown is the seller's responsibility, provided on each usage row — there is NO enable flag.** A usage row participates in VMT simply by carrying a `usageAllocations` attribute (a list of `{AllocatedUsageQuantity, Tags:[{Key,Value}]}` objects in the exact BatchMeterUsage `UsageAllocation` shape). The aggregator MERGES the per-row allocations of a group into the hour's single UsageRecord (summing identical tag sets); it never decides or derives the tag split.

Rules the usage-writer must follow (the skill explains these at initial integration):

- Each row's `AllocatedUsageQuantity` values SHALL sum to that row's own `quantity`.
- Max **5 tags** per allocation; max **2500** merged allocations per UsageRecord (a group with more distinct tag sets is rejected as `TooManyAllocations`).
- **All-or-nothing per group:** for a given `(licenseArn, customerAWSAccountId, dimension, hour)`, either every non-zero row carries `usageAllocations` or none does. Mixing tagged and untagged non-zero rows is rejected client-side (`MixedAllocatedAndUnallocated`). Zero-quantity rows are ignored for this check. Different groups in the same hour/batch may independently have or omit allocations.
- The merged allocation sum must equal the record `Quantity` (else `AllocationSumMismatch`) — this is automatic if each row's allocations sum to its quantity.
- If a group has no tagged rows, `UsageAllocations` is omitted.

Ask the seller for their real tag keys/values — the packaged code carries no illustrative tag and no `VmtEnabled`/`VmtTagAttribute` parameter.

## Usage-writer quantity contract

Usage quantities MUST be **non-negative integers**. The aggregator rejects a negative (`NegativeQuantity`), fractional/decimal (`NonIntegerQuantity`), or non-numeric (`NonNumericQuantity`) quantity client-side — it never truncates (e.g. `2.5`→`2`) or clamps a negative to `0`. Aggregate/round in your writer before persisting. A `0` quantity is valid (not a rejection).

## ResolveCustomer token behavior

- Registration tokens are short-lived (~4 hours) and **reusable until they expire** (NOT one-time-use — re-resolving the same token before expiry returns the same result).
- `ExpiredTokenException` → the buyer re-does "Set up your account" in Marketplace for a fresh token (a full resubscribe is NOT required).
- After a successful resolve, persist `CustomerAWSAccountId` + `LicenseArn` + `ProductCode` and append the invocation Region to `registeredRegions` (idempotent). Do NOT persist `CustomerIdentifier` for a new integration (deprecated, legacy-only).

## TimestampOutOfBounds

- BatchMeterUsage accepts timestamps within the last **24 hours**; older records → `TimestampOutOfBoundsException`, and one bad timestamp rejects the ENTIRE batch.
- The pipeline's hourly `now-23h … now-1h` catch-up window recovers a missed/failed run within 24 hours (the discoverer re-enqueues pending hours; the submitter re-drains `aggregated_usage`). A 6-hour month-boundary grace period applies (previous-month records accepted until 06:00 UTC on the 1st).

## Cancellation event model

- `License Updated` → `agreementStatus = active` and `subscriptionStatus = active`.
- `License Deprovisioned` → `subscriptionStatus = deprovisioning` (+ a `deprovisioningExpiry`); OPENS the ~1-hour flush window; the pipeline flushes any remaining aggregated usage, and the events-stack deprovision-cleanup Lambda (`rate(15m)`) sets `subscriptionStatus = inactive` once `deprovisioningExpiry` passes (time-based, not the submitter).
- `Purchase Agreement Ended` → `agreementStatus = inactive` ONLY (does NOT stop metering or flush).
- `Purchase Agreement Amended` → update agreement metadata (stays active).
- `Purchase Agreement Created` → not consumed by metering; the seller handles it where needed.
