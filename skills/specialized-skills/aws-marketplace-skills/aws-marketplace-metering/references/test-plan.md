# Hands-on test plan (verify the stack, don't blindly trust it)

Walk the seller through these test cases so they SEE each resource the skill created behave
correctly. The skill runs the CLI/verification steps; steps marked **[seller/browser]** are
manual. State each case's **expected observable outcome** so the seller reviews the evidence
(a table item's status, a metric, a log line), not just a green check.

The core happy-path commands are in `deployment-steps.md` Step 5; this plan adds the manual
setup, the full case list, and how to handle async waits.

## 0. Manual prerequisites (seller / browser) — a seller↔skill handshake

These four steps are performed by the SELLER in the browser; the skill CANNOT do them (no
catalog-write / no browser). Run them as a handshake: the skill explains the step and pauses,
the seller does it and confirms, then the skill proceeds (and polls where a result is async).

1. **[seller/browser] Fulfillment URL (AMMP change set).** AMMP → Products → SaaS → select the
   product → **Request changes → Update fulfillment options → edit the default Fulfillment
   URL** (this opens a change set). Set it to the **branded registration page** if ready and
   integrated with `RegistrationUrl`; if no page exists yet, set it to the raw `RegistrationUrl`
   (main-stack output) purely for testing. Submit the change set. → **Seller confirms submitted.**
   The change set takes time to apply; the skill/seller waits until the product is live again
   before subscribing (poll the product status or retry the subscribe page).
2. **[seller/browser] Buyer allowlist.** A `Limited` product allowlists the SELLER account by
   default — to test as the seller, SKIP this. To test with a DIFFERENT buyer account: AMMP →
   the product → **Update allowlist** → add that AWS account ID → submit. → **Seller confirms
   the test account is allowlisted.**
3. **[seller/browser] Subscribe.** Log into the TEST account (seller or the allowlisted buyer),
   open `https://aws.amazon.com/marketplace/pp?sku=<PRODUCT_CODE>`, and subscribe. → **Seller
   confirms subscribed.**
4. **[seller/browser] Set up your account.** After subscribing, click **Set up your account** —
   the buyer's browser is redirected to the Fulfillment URL (the branded page, which calls
   `RegistrationUrl`; or the raw endpoint in the fallback case). → **Seller confirms clicked.**
   The skill then POLLS the subscribers table for the resolved buyer + `licenseArn` (§1).

## 1. Async waits — poll, don't read once

Several results are NOT instantaneous. The skill polls with bounded backoff and reports
"still pending, retrying" vs. a real failure — it does not read once and declare failure.

- **After Set up your account:** `ResolveCustomer` persists the buyer immediately, but the
  `licenseArn` + `subscriptionStatus=active` come from the `License Updated` EventBridge event,
  which arrives after a short delay. Poll the subscribers table (us-east-1) until `licenseArn`
  is present. **Default poll contract: up to ~5 minutes total, at 15-second intervals (20
  attempts).** "Timed out" = `licenseArn` still absent after the last attempt; the skill then
  reports the timeout as a probable failure (check the fulfillment-URL wiring / the
  `License Updated` handler) rather than silently giving up. The bound/cadence is a default an
  operator MAY raise for a slow catalog.
- **Pipeline runs on EventBridge schedules:** the discoverer is hourly and the submitter/
  submission-expiry run on `rate(5 minutes)`. To validate the natural end-to-end path, poll for
  the result on the **same default contract: up to ~5 minutes at 15-second intervals**, after
  which a still-absent result is reported as a timeout (not a silent pass). To validate
  immediately, the skill MAY manually invoke the discoverer (`meter` mode at the matching
  `hourOffset`) then the submitter — it SHALL tell the seller which it is doing (waiting for the
  real schedule vs. a manual trigger).

Poll example (subscribers row):

```bash
for i in $(seq 1 20); do
  aws dynamodb scan --table-name <STACK_PREFIX>-subscribers --region us-east-1 \
    --query 'Items[?licenseArn].licenseArn.S' --output text | grep -q . && { echo "licenseArn present"; break; }
  echo "waiting for License Updated... ($i)"; sleep 15
done
```

## 2. Test cases (full-pipeline mode)

| # | Case | How | Expected observable outcome |
|---|------|-----|-----------------------------|
| T1 | Registration persisted | complete §0; poll (§1) | subscribers row (PII-free) has `customerAWSAccountId` + `productCode`; allowlisted KYB/PII fields are on the in-region `customer-profile` row (keyed `licenseArn`+`customerAWSAccountId`), NOT the subscribers row |
| T2 | License resolved / active | poll subscribers row | `licenseArn` populated; `subscriptionStatus=active` (from `License Updated`) |
| T3 | Metering happy path | write ONE conforming row (Step 5) → discoverer→aggregator→cleanup→submitter | raw row `meteringStatus=Aggregated` (`... from <count> raw usage records`); `aggregated_usage` row `meteringStatus=Success` + `meteringRecordId` |
| T4 | Reject: bad quantity | write a row with `quantity` = `-1` / `1.5` / `abc` | raw row `RejectedClientSide` + reason `NegativeQuantity`/`NonIntegerQuantity`/`NonNumericQuantity`; `UsageRecordRejected` metric (by reason) |
| T5 | Reject: malformed sort key / precision | write rows exercising each condition (one code each) | `RejectedClientSide` with the specific code: millisecond/fractional suffix (`...:07.123`, `...:07.000`) or hour-truncated (`...T13`) → `MalformedTimestamp`; sort key empty or <3 `#`-segments → `MalformedSortKey`; account/dimension segment ≠ the row's own attribute → `SortKeyMismatch` |
| T6 | Reject: missing dimension | row with empty `dimension` | `RejectedClientSide` + `MissingDimension` |
| T7 | Server-side invalid dimension | conforming row with a dimension NOT defined in the catalog | `BatchMeterUsage` fails the call with a request-level `InvalidUsageDimensionException` (server-authoritative); the submitter isolates the record → `aggregated_usage` row `meteringStatus=RejectedClientSide` reason `InvalidUsageDimensionException` + `BatchMeterUsageException` metric — fix the dimension in AMMP, no redeploy |
| T8 | Idempotency / duplicate | re-run the discoverer for T3's hour after it already aggregated | no double-bill (`DuplicateRecord` on re-submit is deduped); cleanup clears `meteringPending` WITHOUT restamping a stale sum |
| T9 | Age-out (raw, never aggregated) | a pending raw row whose hour is >24h old (or invoke an age-out shard) | raw row `meteringStatus=AggregationExpired`; `UsageAggregationExpired` metric |
| T10 | Submission-expiry (aggregated, never submitted) | an `aggregated_usage` pending row >24h old (invoke submission-expiry) | row `meteringStatus=SubmissionExpired`; `UsageSubmissionExpired` metric |
| T11 | Month-boundary (optional) | a previous-month bucket around the 1st (see the month-boundary behavior in `setup-path.md`) | previous-month records still submittable in-grace; expired only after 06:00 UTC on the 1st |
| T12 | Seller-supplied cases | the seller's own dimensions/quantities/VMT allocations/multi-region | as the seller expects; the skill runs and verifies them |

## 3. Test cases (direct-submit mode)

Direct-submit has no raw table / discoverer / aggregator / cleanup. Substitute:

| # | Case | How | Expected |
|---|------|-----|----------|
| D1–D2 | Registration / license | same as T1–T2 | same as T1–T2 |
| D3 | Happy path | write a FINALIZED `aggregated_usage` record (PK `licenseArn`, SK `account#dimension#hour`, `quantity`, `meteringPending`=hour) → submitter | `meteringStatus=Success` + `meteringRecordId` |
| D4 | Finalize-before-insert / duplicate | write a SECOND record for the same group after it submitted | second submit returns `DuplicateRecord`; later quantity NOT billed (confirms the finalize-before-insert contract) |
| D5 | Submission-expiry | pending record >24h old (or post-grace previous-month) | `SubmissionExpired` + `UsageSubmissionExpired` metric |

## 4. Clean up test data

Remove test rows the seller inserted (and, if a non-seller test account was used, note the
allowlist entry). The `aggregated_usage` audit rows are retained by design.
