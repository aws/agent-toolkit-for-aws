# Client-Side Guardrails (applied BEFORE `BatchMeterUsage`)

This is the authoritative list of everything the metering pipeline checks or enforces
**client-side, before a record reaches the `BatchMeterUsage` service call.** The goal is
that a record only reaches the service if it will be accepted — a bad record is caught
locally, recorded with a specific reason, and never sent (so it neither wastes an API
call nor risks poisoning a batch).

Most checks live in the **aggregator** and are *reject-and-finalize*: the group's rows get
a terminal `meteringStatus = RejectedClientSide` plus a specific reason, `meteringPending`
is cleared, and one `UsageRecordRejected` metric (dimensioned by `Reason` + `ProductCode`)
is emitted. Because a rejected row was never sent, its dedup grain
(`CustomerAWSAccountId` + `LicenseArn` + `dimension` + `hour`) is untouched — **fix the
source row, re-write it within 24h, and it meters normally.**

> The per-reason "what to fix" table lives in `troubleshooting.md`
> ("Client-side rejection reason codes"). This document is the COMPLETE guardrail
> inventory including the timing, batch-shaping, and idempotency guardrails that are not
> reason codes.

## Raw-row `meteringStatus` domain

Every raw usage row that the pipeline finishes with reaches exactly one terminal
`meteringStatus`, so its fate is always observable on the row itself:

| `meteringStatus` | Set by | `meteringStatusReason` | Meaning |
|------------------|--------|------------------------|---------|
| `Aggregated` | cleanup Lambda | `Aggregated total quantity <sum> from <count> raw usage records` | Row was folded into its group's aggregated record (the happy path). |
| `RejectedClientSide` | aggregator | the specific reason code (see below) | Row's group failed a client-side guardrail and was never sent. |
| `AggregationExpired` | discoverer (age-out) | — | Row aged past the 24h window BEFORE it could be aggregated (lost before aggregation). |

> This is the RAW table's domain. The `awsmp-aggregated-usage` table has its OWN, disjoint status domain for the SUBMISSION stage — `Success` / `DuplicateRecord` / `CustomerNotSubscribed` (the per-record `BatchMeterUsage` `Results` statuses) / `RejectedClientSide` (a request-level `BatchMeterUsage` exception isolated to the record — reason is the exception name, e.g. `InvalidUsageDimensionException` or `InvalidLicenseException`; NOT a per-record status) / `SubmissionExpired` (aggregated but not submitted before the window/grace closed). "Expired" is never used un-qualified: raw = `AggregationExpired`, aggregated = `SubmissionExpired`.

The SUBMISSION outcome (`meteringRecordId`, and the `Success`/`CustomerNotSubscribed`/…
`BatchMeterUsage` status) is NOT written to the raw row — it lives on the
`aggregated_usage` record. A row still carrying `meteringPending` (no `meteringStatus`) is
simply awaiting processing.

## A. Timing / window guardrails

| Guardrail | Behavior |
|-----------|----------|
| Never meter the in-progress hour | Only completed hour buckets `now-23h … now-1h` are processed, oldest-first. A record is never built for an hour that is still accumulating. |
| Metering lock period | An hour is not aggregated/submitted until it has been closed for `MeteringLockHours` hours (default 1, configurable 1–20). Late usage has that long to land before the hour is submitted. |
| Month-boundary reconciliation | Previous-month hours keep the configured lock until 03:00 UTC on the 1st, then submit immediately (no lock) until the 06:00 UTC month-end cutoff, and are not aged out before then. A previous-month record written after 03:00 UTC on the 1st must already be pre-aggregated by the seller (else `DuplicateRecord`). |
| `TimestampInFuture` | A group whose hour is in the future is rejected client-side. |
| `TimestampOutOfWindow` | A group whose hour is older than the 24h acceptance window is rejected client-side — the service would otherwise reject the ENTIRE batch, so one stale record can't poison others. |
| `MalformedTimestamp` | A raw-usage row whose sort-key suffix is not an exact second-precision `YYYY-MM-DDTHH:MM:SS` timestamp (e.g. millisecond/fractional or hour-truncated) is rejected — enforces the second-precision writer contract at aggregation. |
| `MalformedSortKey` | A raw-usage row whose sort key is missing or has fewer than the three `account#dimension#timestamp` segments is rejected. |
| `SortKeyMismatch` | A raw-usage row whose sort-key account/dimension segments do not match the row's own attributes (a corrupt/mis-keyed row) is rejected. |
| Age-out before submit | Raw rows past 24h that were never aggregated are terminally expired (`meteringStatus = AggregationExpired`, `UsageAggregationExpired` metric) and never enter a batch; an aggregated record that was never submitted in time is expired on the aggregated table (`SubmissionExpired`, `UsageSubmissionExpired` metric). |

## B. Quantity guardrails (strict — never coerced)

| Guardrail (reason code) | Behavior |
|-------------------------|----------|
| `NonNumericQuantity` | A `quantity` not parseable as a number is rejected. |
| `NonIntegerQuantity` | A fractional/decimal quantity (e.g. `2.5`) is rejected — NEVER silently truncated or floored. |
| `NegativeQuantity` | A negative quantity is rejected. |
| (booleans) | A boolean quantity is rejected (not treated as `0`/`1`). |
| Zero handling | `0` is NOT a rejection. An in-window zero group is left pending (submitting `0` early would lock the hour at `0` via first-write-wins dedup); it is submitted as `Quantity: 0` only at the oldest processed edge. |

## C. Dimension guardrails

| Guardrail (reason code) | Behavior |
|-------------------------|----------|
| `MissingDimension` | A group with no dimension is rejected (structural: a dimension key must be present). |

> Dimension NAME validity is **not** checked client-side. `BatchMeterUsage` is the authority — an undefined pricing dimension fails the call server-side with a request-level `InvalidUsageDimensionException` at submit time (NOT a per-record status; the submitter isolates the offending record to `RejectedClientSide` with the exception name as reason, surfaced via the `BatchMeterUsageException` metric/alarm). This keeps the pipeline decoupled from the catalog, so adding or renaming a pricing dimension needs no redeploy.

## D. Identifier guardrails

| Guardrail (reason code) | Behavior |
|-------------------------|----------|
| `InvalidLicenseArn` | The LicenseArn is shape-validated against a License Manager ARN pattern BEFORE batching, so a malformed ARN never enters a batch (a bad ARN is a request-level error that would sink co-batched records). |
| `MissingCustomerAWSAccountId` | A Concurrent-Agreements (ARN-keyed) group with no account ID is rejected. |
| `MissingLegacyIdentifier` | A legacy (non-ARN) group with neither `CustomerIdentifier` nor `CustomerAWSAccountId` is rejected. |

## E. VMT / `UsageAllocations` guardrails (merged, all-or-nothing)

| Guardrail (reason code) | Behavior |
|-------------------------|----------|
| `MalformedAllocations` | `usageAllocations` is not a list, or an entry is not an object. |
| `NegativeOrNonIntegerAllocation` | An allocation quantity is negative or non-integer (same strict-int rule as quantity). |
| `MissingTagKeyOrValue` | An allocation has no tags, or a tag is missing a non-empty Key/Value. |
| `TooManyTags` | An allocation has more than 5 tags (service per-allocation cap). |
| `TooManyAllocations` | The merged group produced more than 2500 distinct tag-set allocations (service per-record cap). |
| `MixedAllocatedAndUnallocated` | Within one group, some non-zero rows carry allocations and some don't — must be all-tagged or all-untagged. |
| `AllocationSumMismatch` | The merged allocation quantities do not sum to the record `Quantity`. |
| tags carried through | The merge only SUMS the seller's own tag sets; the pipeline never invents or re-partitions the split. |

## F. Batch-shaping / submit-time guardrails

| Guardrail | Behavior |
|-----------|----------|
| ≤25 records per call | Records are chunked to the `BatchMeterUsage` hard limit. |
| ≤1 MB request payload | Independent of the record count: even a ≤25-record batch is rejected for SIZE if the serialized request exceeds 1 MB (large/many `usageAllocations` tag-sets, long ARNs). Chunk into fewer records per call so each request stays under 1 MB — it is the byte size, not the count. |
| CA vs legacy split | Concurrent-Agreements records (LicenseArn) and legacy records (ProductCode) go in separate batches — the two paths pass identifiers differently. |
| Request-level poison isolation | If a batch is rejected with a non-transient request-level error, the batch is recursively bisected (bounded to ⌈log2(batch size)⌉ = 5 levels, so a single poison record can always be isolated from a full 25-record batch) so a single poison record is isolated and terminally recorded while the rest still meter; at the depth cap a still-failing multi-record sub-batch is left pending for the next run (a `BisectDepthExceeded` metric fires) so a many-failure batch can't overload the serial submitter. |
| Retry-once on unprocessed | Transient `UnprocessedRecords` are retried once; any still-unprocessed are left pending (re-metered next run) and the invocation fails so the error alarm fires. |
| Transient vs terminal | Only throttling / internal-service / service-unavailable errors are retried; every other error is terminal for that record. |

## G. Idempotency / anti-double-billing guardrails

| Guardrail | Behavior |
|-----------|----------|
| Conditional write commit point | A group is written to the aggregated-usage table at most once (conditional put); a duplicate visit no-ops, so re-discovery can't submit the same group twice. |
| Second-precision dedup grain | The sort key bounds a group to one hour and de-duplicates the discovery tuples. |
| First-write-wins awareness | The pipeline deliberately avoids submitting `0` early because the service dedups per `(CustomerAWSAccountId + LicenseArn + dimension + hour)` and a premature `0` would lock the hour. |

## Why client-side first

Every guardrail above means a defective record is caught, reason-coded, and left
re-writable within the 24h window **without ever calling the service** — avoiding wasted
API calls, avoiding a single bad record rejecting a whole batch, and avoiding both
double-billing and silent under-billing. Anything that reaches `BatchMeterUsage` has
already passed all of these.
