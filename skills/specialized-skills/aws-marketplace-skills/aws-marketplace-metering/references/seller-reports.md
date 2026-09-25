# Seller Reports — Reconciliation & the SDDS Automation Boundary

This file covers only what the metering skill needs that the public AWS docs do not spell out
in this context: **how Seller Reports relate to the CloudTrail query path** (reconciliation)
and **why programmatic Seller-Reports access is not straightforward to automate** (the SDDS
boundary). The report catalogs (column dictionaries, IAM, dashboards) are AWS-documented and
change over time — use the official docs rather than a copy that can drift:

- Reports, data feeds & dashboards (overview): https://docs.aws.amazon.com/marketplace/latest/userguide/reports-and-data-feed.html
- Seller Delivery Data Service (SDDS): https://docs.aws.amazon.com/marketplace/latest/userguide/data-feed.html
- AMMP reports console: https://aws.amazon.com/marketplace/management/reports/

For the exact listing-fee percentage, billed columns, and IAM actions, read the seller's own
Billed Revenue report and the docs above — do NOT hardcode a fee percentage or a column list
in the skill.

## Two channels (what each is for)

- **AMMP Insights "Billed Revenue" dashboard** — interactive dashboards in the AWS Marketplace
  Management Portal. Billed revenue, per-customer/per-dimension usage, disbursements;
  billing-of-record. **Needs NO prior setup and covers ANY range, including a full year** —
  it requires only `aws-marketplace:GetSellerDashboard`; the default view is the **last 6
  months**, so widen the invoice-date filter for a year or more. It is **CONSOLE-ONLY**
  (QuickSight) with manual CSV export — there is **no on-demand billed-revenue query API**.
- **Seller Delivery Data Service (SDDS)** — the programmatic path: AWS **pushes** CSV data
  feeds to a seller-owned S3 bucket (see the boundary below), which the seller queries with
  their own Athena/ETL. Requires `aws-marketplace:GetSellerDashboard`. **Push-only and delivers
  only FROM ENROLLMENT FORWARD — it does NOT backfill**, so a historical year is available
  programmatically only if SDDS was already enrolled during that period; otherwise use the
  console dashboard above for the historical range. **Do NOT use the deprecated
  `GenerateDataSet`.**

> **Raw SUBMISSION history (incl. rejected/duplicate) beyond 90 days has no billed source** —
> Seller Reports/SDDS are billed-only, and CloudTrail Event History retains only 90 days. To
> retain raw submissions long-term, set up a self-managed CloudTrail **trail → S3** on
> `metering-marketplace.amazonaws.com` (a plain trail, NOT CloudTrail Lake); like SDDS it
> captures only FROM SETUP FORWARD and does not backfill. Because the bucket stores raw
> metering submission data, **encrypt it at rest with SSE-KMS** (set `KMSKeyId` on the trail,
> a customer-managed key) and **enforce encryption in transit** via a bucket policy denying
> `aws:SecureTransport=false`; block public access. See `references/query-patterns.md`.

Metered usage is billed on the **2nd/3rd of the following month** (e.g. November usage lands on
the December invoice), and dashboard revenue is **estimated** until the month closes.

## Billed Revenue report — key CSV columns

The exact schema is AWS-documented and can change — read the seller's own export / the docs
above for the authoritative list — but the Billed Revenue / usage CSV export includes both
**financial** and **identity** columns you can name when a seller asks "what columns are in the
report?":

- **Financial:** `Gross revenue` (billed amount before fees; a Private-Offer discount shows here
  as a lower value — there is no separate discount column), `Listing fee` (AWS Marketplace fee),
  `Seller net revenue` (what the seller nets after the listing fee), plus the currency/period
  columns.
- **Identity / attribution:** `Subscriber AWS account ID` (the buyer account), `Agreement ID`
  (the agreement, maps to the `agreementId` on the subscriber row), and `Product ID` (the
  product), plus the usage `Dimension`.

Use these to join billed rows back to the submitted CloudTrail records (by account + agreement/
product + dimension + period) during reconciliation. Do NOT hardcode a listing-fee percentage —
read it from the report.

## Reconciliation: CloudTrail (submissions) vs Seller Reports (billed)

The two views answer different questions — this is the model the query path relies on:

| Question | Source |
|----------|--------|
| Did my `BatchMeterUsage` call succeed / what did the API return? | **CloudTrail** (≤90 days) — the skill's query path |
| What was actually **billed** / disbursed? | **Seller Reports** (billed amounts, full history) |
| Why don't the totals match? | See below |

**Totals don't match?** Expected. **CloudTrail shows ALL submissions** — including
`DuplicateRecord` (first-write-wins; a differing-quantity resubmit is NOT billed — an
under-billing risk, not simply "benign") and `CustomerNotSubscribed` (rejected). **Seller
Reports show only BILLED amounts.** The difference is the rejected/duplicate delta. Other common
mismatches: a `$0`-revenue dimension usually means a **dimension-key mismatch** (case-sensitive
— accepted by the API but not billed); revenue appearing "late" is the 2nd/3rd-of-month billing
cadence; and subscriber ≠ payer under consolidated billing.

There is **no separate "discount" field**: Private Offer discounts show up as a lower
`Gross revenue`; a native **AWS Marketplace SaaS free trial** shows the metered usage at `$0`
estimated revenue until it converts (if the seller's own pricing meters only above a free
allowance, there is simply no usage to show below it); channel-partner
(CPPO) margin is `Gross revenue − Wholesale cost`.

## The SDDS automation boundary (why the skill recommends, but does not run, this path)

SDDS is **push-based, not an on-demand query API**: AWS Marketplace delivers structured **CSV**
data feeds **daily (~midnight UTC)** into a seller-owned, KMS-encrypted S3 bucket, in a
bi-temporal structure. **There is no API/CLI to trigger a delivery or query the feeds on
demand.** Setup requires a **one-time manual step that cannot be automated**:

1. Deploy the AWS-provided data-feed resources (KMS key + encrypted S3 bucket/policy, optional
   SNS topic) — automatable.
2. **Manual, mandatory:** in AMMP → **"Set up customer data storage"** → submit the bucket/KMS
   (and optional SNS) ARNs. This subscribes the account; it cannot be done via API/CLI.
3. The seller then runs **their own query/ETL** (e.g. Athena over the delivered S3 CSVs).

Consequently the metering skill **recommends** this path for billed totals and data older than
90 days but **does not perform** it: the skill cannot complete the manual enrollment for the
seller, and querying the delivered feeds is the seller's own responsibility. Do NOT ship or
reference the deprecated `marketplacecommerceanalytics` `GenerateDataSet` (legacy CSV export)
API — SDDS is the only current, supported programmatic mechanism.
