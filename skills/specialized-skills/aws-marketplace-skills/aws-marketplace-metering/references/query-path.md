# Query Path — Find, Debug, and Analyze Metering Records

## What this query path is (and is not)

The query path is a **fast, zero-setup, recent (≤90 days), single-region, single-event-stream
operational lens over the metering SUBMISSIONS you sent to `BatchMeterUsage`** — it answers
debugging/triage questions from CloudTrail Event History. It reflects what was *submitted* and
how the API responded — the per-record `results[].status` values `Success`/`DuplicateRecord`/`CustomerNotSubscribed` (CloudTrail lowercases response field names; the direct SDK response is PascalCase `Results[].Status`), and request-level exceptions like `InvalidUsageDimensionException` that failed a whole call — including rejected/duplicate records that were **not** billed.

**USES (the skill queries this directly):**

- CloudTrail Event History (`LookupEvents`) in the seller's metering region, last ≤90 days,
  page-bounded and processed in memory (see "Result completeness" below).
- BASIC queries only: lookups and simple filters/counts/summaries by customer, dimension,
  status, or time range (the query types below).

**RECOMMENDS (out of scope for this query — hand off, do not run here):**

| The seller wants… | Why CloudTrail can't be the answer | Recommend instead |
|---|---|---|
| Billed totals / "what was I actually paid" / authoritative sums | CloudTrail is the *submissions* view (includes rejected/duplicate), not billing-of-record | **Seller Reports** (AMMP Insights / SDDS) — billed amounts; reconcile per "Totals don't match" below |
| Data older than 90 days / history | CloudTrail Event History retains only 90 days | **Seller Reports / SDDS** — seller-run (one-time "Set up customer data storage"; the seller queries the delivered feeds) |
| Per-product totals with no LicenseArn→productCode mapping | CA `BatchMeterUsage` events carry no `productCode` | Explain the limitation; offer only non-product-scoped queries |
| Complex/open-ended analytics (forecasting, arbitrary aggregations, cross-source joins) | Determined by the host agent + model, not the skill | Hand the fetched data to the host agent, or the seller's own analytics |
| An authoritative full-window total for a high-volume seller (fetch would truncate) | The fetch is page-bounded (see below) | Narrow window / raise `--max-pages`, or use **Seller Reports** |

When a question lands outside the USES scope, say so — don't return a bounded, submissions-only
answer as if it were the authoritative/billed total.

## CloudTrail-derived SQL analytics is the WRONG source for billing/usage analytics

Any CloudTrail-based path — CloudTrail **Lake** OR **Athena over a (self-managed) CloudTrail
`trail → S3` export** — analyzes **SUBMISSIONS only**: it includes rejected / `DuplicateRecord`
records (**NOT billed**), is **regional**, and for Concurrent Agreements carries **no
`productCode`** (no product attribution). So it is the wrong source for billing/usage analytics.

- **Do NOT set up CloudTrail Lake / `create-event-data-store` for metering** — not for analytics
  and not for lookups.
- **For complex SQL analytics, billing-grade totals, or data older than 90 days, use SDDS data
  feeds:** AWS pushes daily CSV (~midnight UTC, prior-day 24h) to your encrypted S3 bucket and
  you run your **OWN Athena/ETL** over the bi-temporal feeds. SDDS is **enrollment-forward (NO
  backfill)**, **push-only** (no on-demand query/trigger API), and enrolled via a one-time
  **MANUAL AMMP step** ("Set up customer data storage"). The skill **RECOMMENDS but does not
  run** it. (Billed history for any range with no setup is also in the console "Billed Revenue"
  dashboard — see `references/seller-reports.md`.)
- A self-managed CloudTrail **`trail → S3`** (never Lake) + Athena is acceptable **ONLY for
  long-term raw-SUBMISSION AUDIT retention** (from setup forward, no backfill) — NOT as a
  billing/usage-analytics source. The destination bucket stores raw `BatchMeterUsage`/
  `ResolveCustomer` submission data, so it **MUST** be encrypted at rest with **SSE-KMS**
  (`KMSKeyId` on the trail, a customer-managed key) and enforce **encryption in transit** with
  a bucket policy denying `aws:SecureTransport=false`; also block public access and restrict
  read to the auditing principals.
- **Do NOT reference the deprecated `GenerateDataSet`.**

## Step 1: Determine the Seller's Metering Region

**You MUST ask the user which region their application calls BatchMeterUsage from.** CloudTrail Event History is regional — you MUST query the same region where the API was invoked.

Ask the seller which region their application calls BatchMeterUsage from — do not assume a fixed set. You must query CloudTrail in that same region.

## Step 2: Extract Query Parameters

Parse the user's query to identify filters:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `customer_id` | CustomerAWSAccountId | `123456789012` |
| `status` | Result status | `Success`, `CustomerNotSubscribed`, `DuplicateRecord` |
| `dimension` | Usage dimension name | `fgt_cnf_hours` |
| `product_code` | Product to scope a product-specific query to (needs a mapping — see below) | `prod-abc123` |
| `start_date` / `end_date` | Date range (YYYY-MM-DD) | `2025-03-01` |
| `query_type` | Type of query | `summary`, `detail`, `count`, `list_failures`, `top_customers` |
| `top_n` | Number of top results | `10` |

## Step 3: Run the Query Script

```bash
python3 ./scripts/query_metering.py \
  --region <SELLER_METERING_REGION> \
  [--days N] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD] \
  [--customer-id CUSTOMER_AWS_ACCOUNT_ID] [--status STATUS] \
  [--dimension DIMENSION] [--query-type summary|detail|count|list_failures|top_customers] \
  [--product-code PRODUCT_CODE] [--deployment-product-code PRODUCT_CODE] \
  [--top-n N] [--limit N] [--max-pages N]
```

If `--start-date` is omitted, defaults to last 7 days.

### Queries older than 90 days are out of scope

CloudTrail Event History (the only source this script queries) retains **90 days**. Do NOT
attempt to query older data with this tool. If the requested range is entirely older than 90
days, the script does not query — it returns a recommendation to use the **seller-run Seller
Reports / SDDS path** (`references/seller-reports.md`): the seller completes the one-time
"Set up customer data storage" step in AMMP and runs their own query/ETL over the delivered
S3 feeds. If the range only partly predates 90 days, the script queries the in-window portion
and notes that the older portion needs Seller Reports / SDDS.

### Product-specific queries need a LicenseArn→productCode mapping

`BatchMeterUsage` for Concurrent Agreements (LicenseArn-based) carries **no** `productCode`, so
a CloudTrail event cannot be attributed to a product from the API fields alone. Before a
product-specific query (`--product-code`), establish a mapping from one of these, in order:

1. **Single-product deployment context** — pass `--deployment-product-code <productCode>` when
   the events come from a single-product stack (`awsmp-<productCode>-metering`/`-usage`).
2. **CloudTrail `additionalEventData`** — if the event carries a LicenseArn→productCode map, the
   script uses it automatically.
3. **Subscribers table** — the `productCode` attribute per licenseArn row can serve as the map.

If none is available, the script does NOT support the product-specific query: it explains why
and offers only non-product-scoped queries (by customer, dimension, status, or time range).
Legacy ProductCode-based metering carries `ProductCode` at the request level, so product
attribution is available directly.

## Step 4: Interpret Results

| query_type | Output |
|-----------|--------|
| summary | Total records, quantity, breakdowns by status/dimension, top customers |
| top_customers | Ranked list by usage quantity |
| detail | Individual records (capped by --limit) |
| count | Record and quantity totals |
| list_failures | Only non-Success records |

## Query Type Selection Guide

| User Question | query_type | Flags |
|--------------|------------|-------|
| "top 10 buyers" | `top_customers` | `--top-n 10` |
| "total usage this month" | `summary` | `--days 30` |
| "how many failures" | `list_failures` | |
| "records for customer X" | `detail` | `--customer-id X` |
| "usage by dimension" | `summary` | (dimension breakdown included) |

## Result completeness (bounded, in-memory fetch)

The query fetches CloudTrail Event History with `LookupEvents`, paginating up to `--max-pages`
(default 20 pages × 50 = ~1000 events), then filters and aggregates **in memory**. A single
query is a **bounded window**, not an exhaustive scan — a high-volume seller's broad window can
hold more events than the cap fetches.

Every result therefore carries explicit completeness signals:

- `complete: true` — the whole requested window was fetched (`truncated: false`, `windowClipped: false`).
- `truncated: true` — the page cap was hit with more events available; the result is a
  **partial sample**. `fetch.pagesFetched` / `fetch.eventsProcessed` show how much was read.
- `windowClipped: true` — the requested start predates the 90-day CloudTrail retention limit,
  so the result covers only the last 90 days (a SHORTER range than requested); the output states
  the covered start date. `complete` is `false` whenever the result is truncated OR clipped.

**Confirm completeness before presenting a result (double-pass).** Because this skill is run by
an AI agent, always inspect these signals on the query output before answering. If `complete` is
false, either (a) re-run to get a complete answer where feasible — narrow/adjust the range for a
clip, or raise `--max-pages` / add `--customer-id`/`--dimension`/`--status` for truncation — and
confirm the re-run is `complete: true`; or (b) present the result while explicitly stating it is
partial (what was clipped/truncated and the covered range) and pointing to **Seller Reports** for
the authoritative or older portion. For the aggregate query types (`summary`, `count`,
`top_customers`) a truncated or clipped result carries an `aggregateWarning` — the numbers are a
**lower bound**, not authoritative. Never report a partial result as covering the full requested
range, and never quote a partial aggregate as a definitive total.

## Status Explanations

| Status | Meaning | Action |
|--------|---------|--------|
| `Success` | Record accepted and billed | None needed |
| `CustomerNotSubscribed` | No active subscription | ⚠️ Do NOT retry |
| `DuplicateRecord` | First-write-wins: original quantity stays billed; a resubmit with a *different* quantity is NOT billed | Safe only for an identical retry; do NOT rely on it to correct a quantity (under-billing risk) |

Request-level exceptions (fail the whole `BatchMeterUsage` call — NOT per-record `Results` statuses; the pipeline isolates the offending record by bisection so co-batched records still meter):

- `InvalidUsageDimensionException` — a dimension not defined in the catalog (fix the dimension key / define it in AMMP; isolated to `RejectedClientSide` reason `InvalidUsageDimensionException`, surfaced on the `BatchMeterUsageException` metric).
- `TimestampOutOfBoundsException` — a record older than 24 hours (fix the timestamp).

## Data Tiers

| Tier | Retention | Cost | Use When |
|------|-----------|------|----------|
| CloudTrail Event History | 90 days | Free | Real-time, last 90 days |
| CloudTrail trail → S3 | Indefinite (your S3 lifecycle) | Low (S3) | Durable raw API-submission audit BEYOND 90 days |
| Seller Reports (AMMP) | Full history | Free | Billed amounts, reconciliation |
| DDB PITR Export | Configurable | Low | Full history from deployed stack |
| SDDS (Seller Delivery Data Feeds) | Full history | Free | SQL over S3-delivered feeds (>90 days, billing) |

**"Totals don't match disbursement?"** — CloudTrail shows ALL (including DuplicateRecord + rejected). Seller Reports show only billed. Difference = rejected/duplicate.

## Troubleshooting

**"No records found"** — Wrong region, too soon (<15 min), wrong filter, or beyond 90 days.

**"No errors but not billing"** — Dimension mismatch (case-sensitive, no runtime error).

**Script slow** — Use `--max-pages`, `--limit`, or narrow date range.

> For full CloudTrail CLI patterns and pagination examples, load `references/query-patterns.md`.
