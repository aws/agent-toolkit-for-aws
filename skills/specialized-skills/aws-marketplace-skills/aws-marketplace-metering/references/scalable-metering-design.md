# AWS Marketplace Metering Pipeline — System Design

This document describes the metering pipeline this skill generates for an AWS Marketplace
SaaS usage-based (pay-as-you-go) product. It is the reference architecture the skill
materializes into a seller's workspace and deploys; the generated CloudFormation/SAM
templates (`assets/template-main.yaml`, `assets/template-events.yaml`) and Lambda handlers
(`scripts/*.py`) implement exactly what is described here.

## Overview

Metering turns a seller's usage into billed revenue by submitting `UsageRecord`s to the AWS
Marketplace `BatchMeterUsage` API. The seller writes raw usage into DynamoDB; the pipeline
discovers, aggregates, and submits that usage. It is designed to scale to sellers
writing thousands of metering records per hour while staying within the `BatchMeterUsage` rate
limit and DynamoDB per-partition write limits, and to meter usage once — avoiding double-billing
and reducing the chance of silently losing usage.

The pipeline is deployed as **two CloudFormation stacks**:

- **Events stack** (`awsmp-events-stack`, us-east-1, shared by all of a seller's products):
  receives AWS Marketplace subscription lifecycle events from EventBridge and maintains the
  subscribers table. AWS Marketplace emits these events only in us-east-1.
- **Main stack** (`awsmp-<productCode>-metering`, one per product per metering Region):
  the registration endpoint, the usage/aggregated-usage tables, and the metering pipeline
  itself. `BatchMeterUsage` is regional, so a seller deploys one main stack in each Region
  where usage occurs and meters in-Region.

Resource names use the fixed `awsmp-*` convention. The two-stack split, the table/index key
schemas, and the event wiring are fixed; sellers customize only the marked configuration
parameters (product code, Region(s), stage name, tags, retention, alarm actions).

## Design principles

1. **Decouple every stage.** Discovery, aggregation, submission, and per-row write-back run
   as independent Lambdas connected by SQS queues, so each scales on its own and no single
   invocation is bounded by another stage's latency.
2. **Idempotent by construction.** Every stage can be safely re-run. A single durable commit
   point (a conditional write) plus `BatchMeterUsage`'s first-write-wins de-duplication make
   at-least-once delivery safe.
3. **Surface failures.** Each failure mode is designed to either self-heal on the next
   scheduled run or surface on a CloudWatch alarm, so that dropped usage is accompanied by an
   operator-visible signal rather than failing silently.
4. **Bounded load.** Second-precision timestamps bound any one aggregation group to 3,600
   rows/hour, which in turn bounds every downstream read, memory footprint, and write fan-out.
5. **Least privilege.** Each Lambda's execution role grants only the specific actions and
   resource ARNs it uses; lookups use GSI `Query`, never `Scan`.

## Data model

### Subscribers table (events stack, us-east-1)

One unified table holding subscription/agreement **state**, keyed for Concurrent Agreements by
`licenseArn` (partition) + `customerAWSAccountId` (sort). One buyer holding N concurrent
agreements is N rows (same account, different license). Each row carries `productCode`,
`agreementId`, `agreementStatus` (`active`/`inactive` — the agreement lifecycle),
`subscriptionStatus` (`active`/`deprovisioning`/`inactive` — the license lifecycle), and
`registeredRegions` (a DynamoDB String Set of Regions in which the buyer has registered — reference only,
never a metering gate).

The subscribers table is **PII-free**: it holds only the identifiers and lifecycle statuses
above. Because it carries no buyer PII, it is safe to keep in us-east-1 alongside EventBridge
even for products whose buyers are in an opt-in Region. Two GSIs keep lookups off `Scan`:
`customerAWSAccountId-index` (find all agreements for a buyer; the registration lookup) and
`agreementId-index` (the subscription lookup when an agreement event omits the license ARN).

### Customer-profile table (main stack, per Region)

Buyer registration data (PII — contact name, email, company, use-case, and any seller-defined
fields) is stored **in-Region** in `awsmp-<productCode>-customer-profile`, keyed by
`licenseArn` (partition) + `customerAWSAccountId` (sort) to align with the subscriber identity.
Keeping registration PII in the Region the buyer registered in — rather than in the shared
us-east-1 subscribers table — lets a seller in an opt-in Region keep that Region's buyer PII in
that Region. The registration Lambda writes the allowlisted fields as a `registrationData` map;
a seller may promote any field to its own top-level attribute with a matching GSI for direct
lookup. This table is not on the metering path; it is a seller-owned buyer datastore.

### Usage table (main stack)

The seller writes raw usage here. Keyed by `licenseArn` (partition) + a composite
`customerAWSAccountId#dimension#timestamp` (sort), where `timestamp` is a whole-second UTC value
(`YYYY-MM-DDTHH:MM:SS`). Second precision lets multiple rows exist for the same
`(licenseArn, customerAWSAccountId, dimension, hour)` — each distinct second is its own row —
while bounding a group to at most 3,600 rows/hour. `customerAWSAccountId`, `dimension`, and
`timestamp` are also stored as top-level attributes so the pipeline reads them without parsing
the sort key; in particular a Concurrent Agreements `UsageRecord` is built entirely from a usage
row, with no subscriber lookup.

A sparse `metering_pending` GSI (partition = `meteringPending` hour bucket `YYYY-MM-DDTHH`,
sort = `licenseArn`, projecting `customerAWSAccountId` + `dimension`) makes pending usage
discoverable. The writer sets `meteringPending` to the row's UTC hour bucket when it writes a
row; the pipeline clears it once the row's aggregation group reaches a terminal state.

### Aggregated-usage table (main stack)

`awsmp-aggregated-usage`, keyed by `licenseArn` (partition) + `account#dimension#hour` (sort),
is the **source of truth for submission**: one row per `(licenseArn, customerAWSAccountId,
dimension, hour)` group, carrying the summed quantity, merged usage allocations, and its own
`meteringPending` marker. A sparse `metering_pending` GSI (partition = `meteringPending`) lets
the submitter find pending records. Records are written by a conditional `PutItem`, making the
write the pipeline's idempotency commit point.

### Audit timestamps

Every row the pipeline writes to any of these tables carries two ISO-8601 UTC audit
attributes: `createdAt` (set once, via `if_not_exists` on updates or on first insert) and
`updatedAt` (refreshed on every write). These are audit/reference metadata only — not keys, not
PII, and never a metering or billing input: they do **NOT gate metering** (metering decisions
follow `subscriptionStatus` / the `metering_pending` GSI, never `createdAt`/`updatedAt`). For the
seller-written raw usage table, the seller
is asked to stamp the same attributes; the pipeline stamps `updatedAt` whenever it finalizes a
raw row.

### Writer contract (seller-owned)

Ingestion — writing usage rows — is always the seller's responsibility; the pipeline never
writes usage. A conforming raw usage row requires:

- the composite sort key `{customerAWSAccountId}#{dimension}#{YYYY-MM-DDTHH:MM:SS}` in whole
  seconds, UTC, with its account and dimension segments equal to the row's own attributes;
- `meteringPending` equal to the UTC hour of the row's own timestamp (this is the discovery
  key — a mismatched bucket is the one writer error the pipeline cannot detect, so it is
  verified by the post-deploy hands-on test);
- a non-negative integer `quantity`;
- optional `usageAllocations` in the `BatchMeterUsage` `UsageAllocation` shape for Vendor
  Metered Tagging.

## Architecture

```
  EventBridge — 6 rules × 5 constant-Input targets = 30 invocations (one discoverer Lambda)
  ┌──────────────────────────────────────────────────────────────────────┐
  │ 23 targets: {mode: meter,  hourOffset: 1..23}                          │
  │  7 targets: {mode: ageout, shard: 0..6}                                │
  └──────────────────────────────────────────────────────────────────────┘
                                  │  (reserved concurrency = 30)
                ┌─────────────────┴──────────────────┐
                ▼                                     ▼
   ┌──────────────────────────┐          ┌──────────────────────────────────┐
   │ Discoverer — meter mode   │          │ Discoverer — ageout mode          │
   │ Query metering_pending    │          │ shard M owns hours where          │
   │ GSI for ONE hour bucket   │          │ hours_back % 7 == M               │
   │ = floor(now,h) - offset;  │          │ REMOVE meteringPending +          │
   │ enqueue 1 message/group   │          │ SET meteringStatus =              │
   │ (no-op if offset < lock)  │          │   AggregationExpired;             │
   └──────────────────────────┘          │ emit UsageAggregationExpired      │
                │                          └──────────────────────────────────┘
                ▼  SQS: awsmp-metering-work ──► DLQ
   ┌───────────────────────────────────────────────────────────────────────┐
   │ Aggregator (SQS-triggered, high concurrency)                           │
   │  read group rows: Query(licenseArn, begins_with(SK,                    │
   │    "account#dimension#hour"))  — ≤3600 rows, streamed                  │
   │  sum quantity · merge usageAllocations (≤2500) · validate structure    │
   │   ├─ valid   → conditional PutItem into awsmp-aggregated-usage  ◄── commit point
   │   │            (meteringPending = hour) → enqueue cleanup              │
   │   └─ invalid → meteringStatus = RejectedClientSide + reason + EMF      │
   │                (never submitted)                                        │
   └───────────────────────────────────────────────────────────────────────┘
        │ (cleanup)                                     │ (submit)
        ▼  SQS: awsmp-metering-cleanup ──► DLQ          ▼  EventBridge rate(5 min)
   ┌──────────────────────────────┐        ┌────────────────────────────────────┐
   │ Cleanup (SQS-triggered)      │        │ Submitter (reserved = 1)            │
   │ message = ≤100 raw-row keys  │        │ read aggregated_usage pending (GSI) │
   │ per-key UpdateItem:          │        │ oldest-first, deprovisioning-first; │
   │  REMOVE meteringPending +    │        │ coalesce ≤25 → BatchMeterUsage;     │
   │  SET meteringStatus =        │        │ retry once, isolate a poison        │
   │      Aggregated (raw table)  │        │ record by bisection;                │
   └──────────────────────────────┘        │ write MeteringRecordId + status +   │
                                            │ REMOVE meteringPending on           │
                                            │ aggregated_usage (never raw table)  │
                                            └────────────────────────────────────┘

  EventBridge rate(5 min): submission-expiry Lambda sweeps aggregated_usage for records that
  can no longer be billed and marks them SubmissionExpired (emits UsageSubmissionExpired).
```

## Pipeline stages

### Discoverer

A single Lambda (reserved concurrency 30) invoked by 6 EventBridge rules carrying 5 constant
`Input` targets each — 30 invocations total. Each invocation's slice identity comes only from
its constant target `Input`, never from a wall-clock read, so slices are disjoint and
gap-free.

- **`meter` mode** (23 targets, `hourOffset` 1–23): Query the `metering_pending` GSI for the
  single hour bucket `floor(now, hour) - hourOffset` and enqueue one work message per
  `(licenseArn, customerAWSAccountId, dimension, hour)` group. It reads no group rows,
  aggregates nothing, and submits nothing. It no-ops when `hourOffset` is below the configured
  lock (see Metering lock period).
- **`ageout` mode** (7 targets, `shard` 0–6): shard M owns lookback hours where
  `hours_back % 7 == M`. For a raw row still pending past the 24-hour billable window, it
  clears `meteringPending`, sets `meteringStatus = AggregationExpired`, and emits the
  `UsageAggregationExpired` metric — a bounded, alarmed record of usage that aged out before it
  could be aggregated.

The discoverer is the sole enqueuer and the sole age-out path, so a scheduler stall would
silently stop both metering and age-out. A dedicated "did not run" alarm (breaching on missing
data) catches that case.

### Aggregator

An SQS-triggered Lambda that processes one group per message. It reads the group's rows with a
targeted `begins_with(sortKey, "account#dimension#hour")` Query (never a whole-partition scan),
streams the fold to a running sum, merges seller-provided `usageAllocations`, and runs
structural client-side validation.

Validation is a property of aggregation, so client-side rejection lives here, not in the
submitter. The pipeline is **not** configured with the product's dimension list — dimension
validity is server-authoritative (`BatchMeterUsage` fails the call with a request-level `InvalidUsageDimensionException` for an
undefined dimension), which keeps the stack decoupled from the AWS Marketplace catalog so
adding or renaming a dimension needs no redeploy. The client-side checks are structural only:
dimension present; whole-second sort key with matching segments; non-negative integer quantity;
timestamp within the window; identifier shape; allocation invariants (≤2,500 tag-sets). A group
that fails any check is written with `meteringStatus = RejectedClientSide` and a reason,
emits the `UsageRecordRejected` metric, and never reaches submission.

A valid group is written as one aggregated record via **conditional `PutItem`**
(`attribute_not_exists`). This conditional write is the pipeline's commit point:

- On success (a fresh write), the aggregator enqueues cleanup carrying the authoritative sum
  and row count.
- On `ConditionalCheckFailedException` (the record already exists — a duplicate SQS delivery,
  overlapping triggers, or a late re-visit), the aggregator skips the put and does **not**
  enqueue cleanup. Because the group read only returns rows that still carry `meteringPending`,
  an already-cleaned group yields no rows and no-ops; a genuinely lost cleanup self-heals on
  the next scheduled re-visit, which re-detects the still-pending rows and cleans them. This
  keeps the cleanup queue from inflating on every duplicate visit while preserving self-healing.

A zero-quantity group inside the window is deferred (submitting 0 early would lock the hour at 0
via first-write-wins); at the oldest processed edge it is finalized as `Quantity: 0`.

### Cleanup

An SQS-triggered Lambda that clears `meteringPending` on the raw rows of an aggregated group
and stamps their terminal status — off the submit path so submission latency is not tied to a
large volume of per-row writes. Because `BatchWriteItem` cannot partially update an item,
cleanup issues a surgical per-key `UpdateItem` from a bounded thread pool with exponential
backoff.

- A message from a fresh aggregation write carries the `Aggregated` status, sum, and count →
  `REMOVE meteringPending` and `SET meteringStatus = Aggregated`, `meteringStatusReason =
  "Aggregated total quantity <sum> from <count> raw usage records"` (unconditional, hence
  idempotent).
- A message without a status → `REMOVE meteringPending` only (never stamps a possibly-stale
  sum).

All rows of a group share the `licenseArn` partition (~1,000 WCU/s limit), so the global writer
count is bounded on two axes: the per-invocation thread pool and the cleanup queue's event
source `MaximumConcurrency`. Their product is kept under the per-partition limit; keys are
batched at ≤100 per message. A persistent failure fails the message, redelivers, and eventually
lands on the cleanup DLQ — never a silent drop.

### Submitter

An EventBridge-scheduled Lambda (`rate(5 minutes)`, reserved concurrency 1 — a single serial
submitter is the safest posture against the `BatchMeterUsage` rate limit). It reads pending
`aggregated_usage` records over `now-23h … now-1h`, ordering deprovisioning-license records
first and otherwise oldest-first (closest to expiry first), and drains up to a configurable
maximum per run. It coalesces up to 25 records per `BatchMeterUsage` call, splitting Concurrent
Agreements and legacy submissions, retries once, and isolates a poison record by bisection so
its co-batched records still meter. It writes the returned `MeteringRecordId` and per-record
status back to the aggregated-usage record and clears that record's `meteringPending` — never
touching the raw usage table. The submitter does not age records out and does not finalize
subscribers; those are separate stages (Submission expiry, Deprovisioning).

The default per-run maximum is API-feasible: at ≤25 records per call and the documented `BatchMeterUsage` quota of 10 requests/second per account per region, a run
comfortably drains a large backlog within its 5-minute schedule, so records do not age past the
24-hour window under normal operation.

### Submission expiry

A scheduled Lambda (on the same `rate(5 minutes)` rule as the submitter, an independent target,
reserved concurrency 1) that operates on `aggregated_usage` only. It terminally expires a
pending aggregated record — `REMOVE meteringPending`, `SET meteringStatus = SubmissionExpired`,
emit `UsageSubmissionExpired` — when the record can no longer be billed: either its hour is more
than 24 hours in the past, or it is a previous-month record and the month-end grace has closed
(on/after 06:00 UTC on the 1st). This is designed so that no aggregated record is left pending
indefinitely and any submission-stage loss is alarmed — distinct from the raw table's
aggregation-stage `UsageAggregationExpired`, so an operator can tell which stage lost revenue.

## Idempotency and no-loss design

- **Commit point** — the conditional `PutItem` into `aggregated_usage`. A duplicate visit of
  the same group fails the condition, so the aggregator neither re-writes nor re-submits.
- **Raw rows retain `meteringPending` until cleanup succeeds**, so a lost cleanup is
  self-healing: the rows are re-discovered on the next run and re-cleaned. The cleanup
  `UpdateItem` is idempotent, so re-cleaning is harmless.
- **Submission is de-duplicated by AWS Marketplace.** `BatchMeterUsage` is first-write-wins per
  `CustomerAWSAccountId + LicenseArn + dimension + hour` per Region, so a re-submitted identical
  record cannot double-bill. (A resubmit with a *different* quantity returns `DuplicateRecord`
  and is not billed — an under-billing risk the writer contract calls out, not a pipeline bug.)
- **Loss is surfaced, not silent.** Aged-out raw rows (`UsageAggregationExpired`) and expired
  aggregated records (`UsageSubmissionExpired`) are terminal, alarmed states; SQS failures
  redeliver and eventually DLQ. The intent is that any usage that cannot be metered leaves an
  operator-visible signal rather than disappearing quietly.

## Subscription lifecycle and deprovisioning

The subscription Lambda (events stack) applies AWS Marketplace lifecycle events to the
subscribers table. Two status fields move independently and are never conflated:

- `agreementStatus`: `active` (`License Updated`) → `inactive` (`Purchase Agreement Ended`).
- `subscriptionStatus`: `active` (`License Updated`) → `deprovisioning` (`License
  Deprovisioned`) → `inactive` (finalized by the deprovision-cleanup Lambda). There is no
  `deprovisioned` value.

Metering decisions follow the license lifecycle and the usage table's `metering_pending` GSI —
not `agreementStatus` and not registration state. `Purchase Agreement Ended` updates agreement
status only; it does not stop metering or open a flush window.

### Expedited deprovisioning flush

`License Deprovisioned` opens a **~1-hour window** in which AWS Marketplace still accepts
`BatchMeterUsage` for the license; after it closes, submission returns `CustomerNotSubscribed`
and the usage is unbillable. Because the ordinary meter path defers an hour by the configured
lock (up to 20 hours), a deprovisioning license's final usage would otherwise miss the window.
The pipeline expedites it, reusing the existing stages:

- **Sparse deprovisioning index.** On `License Deprovisioned`, the subscription Lambda sets
  `subscriptionStatus = deprovisioning` plus a constant `deprovisioningPendingFlag` and a
  `deprovisioningExpiry` (the event time + ~1 hour), populating a sparse
  `deprovisioning-pending-index` (partition = the constant flag, sort = expiry, `KEYS_ONLY`).
  The index holds only licenses currently in a flush window and is self-emptying (the markers
  are removed at finalization), so it is queried in O(count), never scanned. Its key shape
  serves both access patterns: `Query(flag)` returns the active set; `Query(flag AND expiry ≤
  now)` returns the expired set.
- **`flush-deprovisioning` discoverer mode**, on a dedicated `rate(5 minutes)` rule. It Queries
  the index for the active set and, for each deprovisioning license, enqueues that license's
  pending groups over `now-23h … now-1h` using a targeted per-license `metering_pending` Query
  (`meteringPending = :hb AND licenseArn = :la`, using the GSI sort key — O(deprovisioning
  groups), never a whole-partition read), **bypassing the lock**. The messages go to a
  dedicated `awsmp-deprovision-work` queue with its own aggregator event source mapping, so a
  deprovisioning backlog is isolated from — never queued behind — the regular backlog. The
  current (in-progress) hour is normally reserved for the seller's final writes, but is **also
  flushed** for a license once `now ≥ deprovisioningExpiry − 10 minutes` (within the last ~10
  minutes before that license's window closes), so its current-hour usage still traverses the
  pipeline in time. The 10-minute lead gives the 5-minute-cadence pipeline headroom to drain.
- **Submitter prioritization.** The submitter Queries the index once per run (best-effort — a
  lookup failure falls back to the ordinary pass, never blocking submission) and reads the
  deprovisioning set's pending aggregated records in a SEPARATE first pass, submitting them ahead
  of the ordinary oldest-first backlog. That first pass reads each such license's records via a
  targeted per-license query on the aggregated-usage `metering_pending` GSI over `now-23h … now-1h`
  **and the current (offset-0) hour** (the current hour is read only for deprovisioning licenses,
  since the flush sweep enqueues their current-hour groups near window close), and is not subject
  to the ordinary read cap — so a closing-window license is neither delayed behind nor dropped by
  the ordinary backlog.
- **Time-based finalization.** A deprovisioning license may have usage across multiple hours and
  multiple Regions (one submitter per Region, one shared subscribers table), so no single
  submitter run can know the license is fully drained — the submitter therefore does not flip it
  to `inactive`. Instead the events-stack **`awsmp-deprovision-cleanup` Lambda** (EventBridge
  Scheduler `rate(15 minutes)`) Queries the index for entries whose `deprovisioningExpiry ≤ now`
  and sets `subscriptionStatus = inactive` and removes both markers, conditioned on the flag
  still being present so concurrent runs are idempotent. Because the window is absolute, once it
  elapses no Region can meter the license, so a single us-east-1 finalization is correct for all
  Regions with no cross-region coordination.

Everything the flush reuses is otherwise unchanged; non-deprovisioning licenses behave exactly
as before. The flush enqueue produces the same work-message shape, so the conditional-put commit
and first-write-wins de-duplication prevent any double-bill if the ordinary post-lock run later
re-enqueues the same group. A flush that still misses the window surfaces on the existing
`CustomerNotSubscribed` metric. Because the flush depends on the discoverer, its rule is gated
to the full-pipeline deployment mode; the submitter prioritization and the deprovision-cleanup
Lambda apply in both modes.

## Metering lock period

`MeteringLockHours` (default 1, validated 1–20) sets how long a metering hour stays open for
late usage before it is aggregated and submitted. The discoverer's meter mode no-ops when
`hourOffset < MeteringLockHours`:

- **Lock = 1 (default):** only fully-complete hours are processed. At 12:20 the discoverer
  processes 11:00–11:59:59 (offset 1), never the in-progress 12:00 hour.
- **Lock = 6:** offsets 1–5 no-op; offset 6 is the first to aggregate the hour, giving writers a
  full six hours to send late events for that hour.

An hour is first submitted at age `MeteringLockHours`, leaving `24 − MeteringLockHours` hours
inside the 24-hour billable window before age-out. Capping the lock at 20 leaves ≥4 hours of
margin after first submission — room for ≥3 hourly retries of a transient failure and for a
seller to inspect and re-drive a client-side rejection (fix the source row; it re-meters within
the remaining window) before the hour ages out. The lock does not move the 24-hour age-out
boundary. A genuinely zero-quantity group still finalizes at the oldest processed edge; because
the processed hours are exactly those older than the lock, the lock never defers a zero-quantity
finalization.

## Month-boundary reconciliation

AWS Marketplace accepts previous-month usage until **06:00 UTC on the 1st** of the next month
(the month-end grace, which extends past the rolling 24-hour window for month-boundary records).
The per-bucket lock is therefore month-aware, classifying each bucket as current- or
previous-month in UTC:

- **Current-month bucket** — the configured `MeteringLockHours`, always.
- **Previous-month bucket, before 03:00 UTC on the 1st** — the configured lock, unchanged
  (the seller keeps writing late or corrected previous-month records as usual).
- **Previous-month bucket, from 03:00 UTC on the 1st** — lock 0: on each run everything pending
  for the previous month, plus anything newly written, aggregates and submits immediately, until
  the 06:00 cutoff. The 03:00→06:00 span is the submit-and-retry margin.

Age-out is suppressed for previous-month buckets while the grace is open (before 06:00 UTC on
the 1st), so the sweep does not expire the very records the grace preserves; after 06:00 UTC,
previous-month records are unbillable and normal age-out resumes. A previous-month raw record
written after 03:00 UTC on the 1st must already be pre-aggregated by the seller — if the pipeline
has already submitted that group, a further write resubmits and returns `DuplicateRecord`
(first-write-wins), so post-03:00 previous-month writes are the seller's risk.

## Deployment modes

The pipeline supports two modes, selected at deploy time, so a seller creates only the
components their ingestion pattern needs:

- **Full pipeline (default):** the seller writes raw per-second usage rows and the pipeline
  discovers, aggregates, cleans up, and submits. Deploys the raw usage table and GSI, the
  aggregated-usage table, the work/deprovision-work/cleanup queues and DLQs, and the
  discoverer/aggregator/cleanup/submitter/submission-expiry Lambdas.
- **Direct-submit:** the seller already produces finalized hourly totals and writes them
  directly into `aggregated_usage`. Deploys only the aggregated-usage table, the submitter, the
  submission-expiry Lambda, and the registration/subscription path. In this mode a record must
  be **final before insert** — any record present in `aggregated_usage` may be submitted on the
  next run, and a second write to the same group returns `DuplicateRecord` (the later quantity is
  not billed).

Mode is not a one-way door: a seller can switch later via a stack update that adds or removes
the mode-specific resources (the raw usage table is retained on deletion). The deployment-mode
condition gates the raw-pipeline resources so no always-present resource ever references a gated
one.

## Scale ceiling and higher-throughput ingestion

Second precision bounds a group at ≤3,600 rows/hour, and the whole pipeline is sized for that:
the aggregator reads at most ~1.8 MB per group and streams the fold; cleanup fans a group into
at most ~36 SQS messages of ≤100 keys each; the single serial submitter drains a large backlog
within its 5-minute schedule. The design supports high volume as long as ingestion is
≤ ~1 write/second per `(licenseArn, customerAWSAccountId, dimension)` group — i.e. the seller's
writer collapses sub-second events into the per-second row.

For finer-than-per-second capture or higher sustained per-group rates, front the usage table
with a streaming ingestion tier (for example, Amazon Kinesis Data Streams): buffer raw events in
the stream and aggregate to per-second (or per-hour) rows in a consumer before writing them to
the usage table. The downstream pipeline is unchanged. Setting up that ingestion tier is
general AWS practice rather than a first-class part of this skill.

## Observability

Alarms cover every failure mode so none is silent. On the main stack (16 alarms): pipeline
Lambda `Errors` (discoverer, aggregator, submitter, submission-expiry — cleanup failures surface
via its DLQ); submitter and aggregator `Throttles`; "did not run" alarms for the submitter and
the discoverer (the discoverer being the sole enqueuer and age-out path); work,
deprovision-work, and cleanup DLQ depth; work-queue and deprovision-work-queue oldest-message-age
(the deprovision threshold well under the ~1-hour window, since a DLQ-depth signal alone fires
too late for that urgent path); and the business-status metrics `UsageAggregationExpired`,
`UsageSubmissionExpired`, `UsageRecordRejected`, `UsageRecordUnprocessed` (records still
unprocessed after the submitter's single retry — the submitter does not raise on this, so this
is the only alarm-able signal for it), `CustomerNotSubscribed`, and
`BatchMeterUsageException`. The events stack alarms the subscription Lambda and its DLQ, and the
deprovision-cleanup Lambda's `Errors` and "did not run" (it solely owns deprovisioning
finalization and the self-emptying of the sparse index).

Business-status metrics are emitted via CloudWatch Embedded Metric Format from the Lambda logs,
so they need no extra runtime IAM. Every alarm's action wires to an optional seller-supplied
in-Region SNS topic; handling alarms is the seller's responsibility. Two health dashboards are
created by default (a `CreateDashboard` parameter opts out): a per-product main-stack dashboard
(per-Lambda Errors/Throttles/Invocations/Duration; queue and DLQ depths and oldest-message-age;
the granular EMF status metrics, with `UsageRecordRejected` broken down by reason via a Metrics
Insights query) and a shared events-stack dashboard (subscription Lambda health and queue/DLQ
depth).

## Data retention

Both tables support seller-configurable TTL:

- **Raw usage table** (`UsageTableTtlDays`, default 365, recommended on): the high-volume table,
  so a TTL controls storage cost. The floor (≥2 days, and greater than `MeteringLockHours` + 24
  hours) is chosen so a row is not deleted before it is metered. The seller's writer sets the
  `ttl` attribute; the template only makes DynamoDB honor it.
- **Aggregated-usage table** (`AggregatedUsageTableTtlDays`, default 0 = retain): a small billing
  audit trail. When enabled, the submitter sets `ttl` only on finalized `Success` records.

A value of 0 omits the `TimeToLiveSpecification` via a CloudFormation condition.

## Security posture

- **Least privilege.** Each Lambda role grants only the actions it uses. The meter path holds
  `aws-marketplace:BatchMeterUsage` plus scoped DynamoDB `Query`/`UpdateItem` on its tables and
  the `metering_pending` index; the registration Lambda holds `aws-marketplace:ResolveCustomer`
  plus `PutItem`/`UpdateItem`/`Query` on the in-Region customer-profile table (and its GSIs) and
  PII-free `GetItem`/`UpdateItem`/`Query` on the subscribers table; the deprovision-cleanup role
  holds `Query` on the sparse index and `UpdateItem` on the subscribers table. No role holds
  `dynamodb:Scan` or a broad `dynamodb:*`/`aws-marketplace:*`.
- **Buyer PII stays in-Region** in the customer-profile table, is masked in logs, and is never
  written to the shared us-east-1 subscribers table.
- **Encryption at rest** on SQS, SNS, and DynamoDB; Lambda and API log groups are explicit
  resources with retention and optional KMS keys (they may contain buyer account IDs and license
  ARNs).
- **The registration API is intentionally unauthenticated** (AWS Marketplace posts the
  fulfillment token to it), so the template attaches a baseline WAF WebACL by default
  (rate-based plus common-exploit rules; a seller WebACL overrides it), API Gateway throttling
  and access logging are always on, and the registration Lambda persists only an allowlisted,
  length-bounded set of fields.

## Handler layout

Shared helpers live in `metering_core.py`, imported by every handler.

| Module | Responsibility |
|--------|----------------|
| `metering_core.py` | DynamoDB/SQS clients; `get_pending_groups` and `get_pending_groups_for_license` (GSI discovery); `read_group_rows` (targeted `begins_with`); the `collect_group` fold; `merge_allocations`, `validate_group`, `finalize_allocations`; `submit_records` (retry-once, bisect-isolate); `deprovisioning_licenses` / `deprovisioning_licenses_with_expiry` (sparse-index queries); audit-timestamp and EMF/masking helpers; second-precision time helpers. |
| `discoverer.py` | `meter` mode — enqueue pending groups for one hour bucket. `ageout` mode — sharded terminal expiry of the raw table. `flush-deprovisioning` mode — expedited per-license flush to the deprovision-work queue, current hour included within 10 minutes of the window close. |
| `aggregator.py` | Fold a group, validate, conditional-put into aggregated-usage or reject client-side, then enqueue cleanup on a fresh write. |
| `cleanup.py` | Per-key `UpdateItem` finalization of raw rows (idempotent), from a bounded, backoff-guarded thread pool. |
| `submitter.py` | Read aggregated-usage pending, order deprovisioning-first then oldest-first, coalesce into `BatchMeterUsage` batches, write back the result. |
| `expiry.py` | Sweep aggregated-usage for records that can no longer be billed and mark them `SubmissionExpired`. |
| `deprovision_cleanup.py` (events stack) | Finalize deprovisioning licenses to `inactive` once their flush window has elapsed. |
| `register.py`, `subscription.py` (events/registration) | Buyer registration (ResolveCustomer + in-Region profile write + PII-free subscriber upsert) and subscription lifecycle handling. |

## EventBridge rule and target layout

Slice identity is a literal constant `Input` per target (the single source of truth), and the
hour is derived inside the Lambda as `floor(now, hour) - hourOffset`, so targets never race on
wall-clock time. Age-out shard M owns lookback hours where `hours_back % 7 == M` (complete,
disjoint, and idempotent regardless).

| Rule | Targets |
|------|---------|
| `awsmp-meter-dispatch-1` (`rate(15 min)`) | hourOffset 1–5 |
| `awsmp-meter-dispatch-2` (`rate(15 min)`) | hourOffset 6–10 |
| `awsmp-meter-dispatch-3` (`rate(15 min)`) | hourOffset 11–15 |
| `awsmp-meter-dispatch-4` (`rate(15 min)`) | hourOffset 16–20 |
| `awsmp-meter-dispatch-5` (`rate(15 min)`) | hourOffset 21–23 + ageout shard 0,1 |
| `awsmp-meter-dispatch-6` (`rate(15 min)`) | ageout shard 2–6 |
| `awsmp-submit-dispatch` (`rate(5 min)`) | submitter + submission-expiry |
| `awsmp-flush-deprovisioning` (`rate(5 min)`, full pipeline only) | discoverer `{"mode":"flush-deprovisioning"}` |

The meter rules run every 15 minutes rather than hourly: meter mode is idempotent and each
bucket's identity is its constant target offset, so a bucket is simply re-evaluated up to four
times an hour and the conditional put de-duplicates — this shortens the time from a late write
becoming eligible to its submission without changing correctness.
