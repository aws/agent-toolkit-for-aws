## Common Patterns

**Top 10 buyers by usage (last 30 days):**

```bash
python3 ./scripts/query_metering.py --region us-east-1 --days 30 --query-type top_customers --top-n 10
```

**Total usage for last 7 days:**

```bash
python3 ./scripts/query_metering.py --region us-east-1 --query-type summary
```

**All failures last 7 days:**

```bash
python3 ./scripts/query_metering.py --region us-east-1 --query-type list_failures
```

**Specific customer detail:**

```bash
python3 ./scripts/query_metering.py --region us-east-1 --customer-id 123456789012 --query-type detail
```

**Count by dimension:**

```bash
python3 ./scripts/query_metering.py --region us-east-1 --dimension fgt_cnf_hours --query-type count
```

## Data Tiers — Where Metering Data Lives

AWS Marketplace metering data is available in multiple tiers. Choose based on your needs:

| Tier | Latency | Retention | Cost | Shows |
|------|---------|-----------|------|-------|
| 1. CloudTrail Event History | ~15 min | 90 days | Free (always on) | Submitted records (raw API calls) |
| 2. Seller Reports (AMMP) | ~24 hours | Full history | Free | Billed records with revenue data |
| 3. DDB Metering Table (PITR export) | Real-time | Configurable | Low (DDB + S3 storage) | All submitted records from deployed stack |
| 4. CloudTrail trail → S3 | ~5-15 min | Indefinite (your S3 lifecycle) | Low (S3 storage; first trail is free) | Raw `BatchMeterUsage`/`ResolveCustomer` API events (the same submissions view as Event History, but retained beyond 90 days) |

### "I want a durable record of submissions beyond Event History — what do I set up?"
Two complementary options (either or both), depending on whether you want the **raw API-call audit record** or the **pipeline's stored records**:

- **CloudTrail trail to S3** (raw API audit record): create a CloudTrail **trail** (management events) delivering to an S3 bucket in the seller's metering region. This captures every `BatchMeterUsage`/`ResolveCustomer` call — the SAME submissions view as Event History — but retained INDEFINITELY per your S3 lifecycle (Event History alone only keeps 90 days). Query the delivered logs with Athena. This is the durable, low-cost audit trail for "what did I submit" beyond 90 days. (Use a plain trail-to-S3, NOT CloudTrail **Lake** — Lake adds cost/setup with no benefit here.)
- **DDB PITR export to S3** (pipeline's records): if the seller deployed the metering stack, export the `aggregated_usage` table via DynamoDB PITR to S3 and query with Athena — full history of the records the pipeline persisted (see Tier 3 below).
Note: neither is BILLED revenue — for billed/disbursed amounts use Seller Reports (Tier 2). CloudTrail (trail or Event History) shows ALL submissions incl. rejected/duplicate.

### When to use which tier:

- **"What did I submit in the last hour/day/week?"** → CloudTrail Event History (zero setup, ~15 min latency)
- **"What happened 6 months ago?"** → Seller Reports, DDB PITR export, or a CloudTrail trail-to-S3 (if one was set up before then)
- **"Durable record of submissions beyond the 90-day Event History?"** → CloudTrail trail to S3 (raw API audit) and/or DDB PITR export to S3 (pipeline records)
- **"What was actually billed?"** → Seller Reports (disbursement/revenue data)
- **"Why don't my totals match the disbursement report?"** → CloudTrail shows ALL submitted (including DuplicateRecord + CustomerNotSubscribed). Seller Reports show only successfully billed. The difference = rejected/duplicate records.
- **"I need SQL queries on historical data"** → SDDS (Seller Delivery Data Feeds — feeds delivered to your S3 bucket, SQL-queryable via Athena) or Seller Reports.

### CloudTrail Event History (Tier 1 — zero setup, free)

Use this for real-time queries (last 90 days, ~15 min delay). Event History is ALWAYS ON — do
NOT use CloudTrail **Lake** / `create-event-data-store` for metering lookups (no data store is
needed; Lake adds cost and setup for no benefit here):

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventSource,AttributeValue=metering-marketplace.amazonaws.com \
  --region <SELLER_METERING_REGION> \
  --start-time $(date -d '7 days ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --max-results 50
```

**Key facts:**

- **90-day retention limit** — cannot query older than 90 days (for older, recommend Seller Reports / SDDS — do NOT use CloudTrail Lake)
- **50 events per page** — use `--next-token` from response to paginate (see Pagination section below)
- **Regional** — MUST query the same region where your application calls BatchMeterUsage
- **~15 minute delivery latency** — events appear ~15 min after the API call (NOT 24-48 hours)
- Filter by `eventSource=metering-marketplace.amazonaws.com` (CloudTrail eventSource — note the hyphen; distinct from the CLI service name `meteringmarketplace`)
- To verify a submission, read each event's CloudTrail `responseElements` — check **`results`** (per-record `status`) vs **`unprocessedRecords`** FIRST; a record in `unprocessedRecords` was not accepted and should be retried. CloudTrail lowercases response field names (`results`/`status`/`meteringRecordId`/`unprocessedRecords`); the direct SDK `BatchMeterUsage` response is PascalCase (`Results`/`Status`/`MeteringRecordId`/`UnprocessedRecords`).

### Seller Reports (Tier 2 — full billing history, free)

Access via [AWS Marketplace Management Portal (AMMP)](https://aws.amazon.com/marketplace/management/reports/):

- **Revenue reports** — billed amounts per customer per dimension
- **Disbursement reports** — payouts received
- **Monthly billed revenue** — aggregated billing data
- **24-hour SLA** — data available within 24 hours of billing cycle close

Use Seller Reports when:

- You need historical data beyond 90 days
- You need to reconcile billed amounts (not raw submissions)
- You want free access without additional infrastructure

### DDB Metering Table with PITR Export (Tier 3 — low cost)

If the seller deployed the metering stack (from the `setting-up-marketplace-metering` skill), their DynamoDB `MeteringRecords` table stores all submitted records with Point-in-Time Recovery enabled:

- **Export to S3**: Use DynamoDB PITR export to create a queryable S3 dataset
- **Query with Athena**: Set up a Glue table on the exported data for SQL queries
- **Cost**: DDB storage + S3 storage + Athena per-query (typically pennies/month for moderate volume)

Use DDB PITR when:

- Seller already has the deployed stack (data is already there)
- Need full submitted record history (not just billed)
- Prefer lower-cost SQL over exported records

### CloudTrail Trail to S3 (Tier 4 — durable raw API audit beyond 90 days)

CloudTrail **Event History** (Tier 1) is always on but only retains **90 days**. For a durable
record of the raw `BatchMeterUsage`/`ResolveCustomer` API calls beyond that, create a CloudTrail
**trail** that delivers events to an S3 bucket:

- **Set up a trail** (per metering region, or a multi-region/organization trail) capturing
  **management events** to an S3 bucket you own. The `metering-marketplace` API calls are
  management events, so no data-event config is needed. The first trail per account is free;
  you pay only S3 storage (apply an S3 lifecycle policy to age/expire objects).
- **Query with Athena**: point an Athena/Glue table at the delivered CloudTrail S3 prefix and
  filter `eventsource = 'metering-marketplace.amazonaws.com'` — the SAME submissions view as
  Event History (`results[].status`, `unprocessedRecords`, request-level exceptions), but with
  the retention YOU choose.
- Use a plain **trail → S3**, NOT CloudTrail **Lake** (`create-event-data-store`) — Lake adds
  cost and setup for no benefit for this audit use.

Use a CloudTrail trail to S3 when:

- You want a durable, self-owned audit record of submissions beyond the 90-day Event History
- You want the RAW API-call record (not the pipeline's stored records, which is Tier 3 DDB PITR)
- You may want both this and DDB PITR — they are complementary (API audit vs. pipeline records)

## CloudTrail Query Patterns (Real-Time, Last 90 Days)

Use these patterns when the seller needs real-time data (last 90 days). **MUST use the region where BatchMeterUsage is called** (ask the seller — do not assume us-east-1).

### Find failed submissions (last 7 days)

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventSource,AttributeValue=metering-marketplace.amazonaws.com \
  --region <SELLER_METERING_REGION> \
  --start-time $(date -d '7 days ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --max-results 50 --output json | \
python3 -c "
import sys, json
data = json.load(sys.stdin)
for event in data.get('Events', []):
    ce = json.loads(event.get('CloudTrailEvent', '{}'))
    results = ce.get('responseElements', {}).get('results', [])
    for r in results:
        if r.get('status') != 'Success':
            ur = r.get('usageRecord', {})
            print(f\"  {r['status']} | account={ur.get('customerAWSAccountId','?')} dim={ur.get('dimension','?')} qty={ur.get('quantity','?')}\")
"
```

Look for these failure statuses:

- `CustomerNotSubscribed` — customer's subscription is inactive, do NOT retry
- `DuplicateRecord` — first-write-wins and REPORTED; the original quantity stays billed. A resubmit with a different quantity is NOT billed (under-billing risk). Not simply "benign"; safe only for an identical retry
- `TimestampOutOfBoundsException` — timestamp older than 24 hours (rejects entire batch)

### Top N buyers by usage (from CloudTrail)

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventSource,AttributeValue=metering-marketplace.amazonaws.com \
  --region <SELLER_METERING_REGION> \
  --start-time $(date -d '30 days ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --max-results 50 --output json | \
python3 -c "
import sys, json
from collections import Counter
data = json.load(sys.stdin)
usage = Counter()
for event in data.get('Events', []):
    ce = json.loads(event.get('CloudTrailEvent', '{}'))
    for record in ce.get('requestParameters', {}).get('usageRecords', []):
        acct = record.get('customerAWSAccountId', 'unknown')
        qty = record.get('quantity', 0)
        usage[acct] += qty
print('Top 10 buyers by usage:')
for acct, total in usage.most_common(10):
    print(f'  {acct}: {total} units')
"
```

**Note:** This only covers one page (50 events). For complete results, paginate with `--next-token` (see Pagination section) or use `--max-pages` with the query script.

### Records for a specific buyer (by CustomerAWSAccountId)

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventSource,AttributeValue=metering-marketplace.amazonaws.com \
  --region <SELLER_METERING_REGION> \
  --start-time $(date -d '7 days ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --max-results 50 --output json | \
python3 -c "
import sys, json
TARGET = '123456789012'  # replace with buyer's AWS account ID
data = json.load(sys.stdin)
for event in data.get('Events', []):
    ce = json.loads(event.get('CloudTrailEvent', '{}'))
    for record in ce.get('requestParameters', {}).get('usageRecords', []):
        if record.get('customerAWSAccountId') == TARGET:
            print(f\"  {event['EventTime']} | dim={record.get('dimension')} qty={record.get('quantity')} licenseArn={record.get('licenseArn','N/A')}\")
    for result in ce.get('responseElements', {}).get('results', []):
        ur = result.get('usageRecord', {})
        if ur.get('customerAWSAccountId') == TARGET:
            print(f\"    → status={result.get('status')} meteringRecordId={result.get('meteringRecordId','N/A')}\")
"
```

### Total usage by dimension (from CloudTrail)

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventSource,AttributeValue=metering-marketplace.amazonaws.com \
  --region <SELLER_METERING_REGION> \
  --start-time $(date -d '30 days ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --max-results 50 --output json | \
python3 -c "
import sys, json
from collections import Counter
data = json.load(sys.stdin)
by_dim = Counter()
for event in data.get('Events', []):
    ce = json.loads(event.get('CloudTrailEvent', '{}'))
    for record in ce.get('requestParameters', {}).get('usageRecords', []):
        dim = record.get('dimension', 'unknown')
        qty = record.get('quantity', 0)
        by_dim[dim] += qty
print('Usage by dimension:')
for dim, total in by_dim.most_common():
    print(f'  {dim}: {total} units')
"
```

### Confirm a specific record was accepted

```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventSource,AttributeValue=metering-marketplace.amazonaws.com \
  --region <SELLER_METERING_REGION> \
  --start-time $(date -d '1 day ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --max-results 50 --output json | \
python3 -c "
import sys, json
TARGET_ID = '<METERING_RECORD_ID>'  # from BatchMeterUsage response
data = json.load(sys.stdin)
for event in data.get('Events', []):
    ce = json.loads(event.get('CloudTrailEvent', '{}'))
    for result in ce.get('responseElements', {}).get('results', []):
        if result.get('meteringRecordId') == TARGET_ID:
            print(f\"Found: status={result['status']}\")
            print(f\"  Record: {json.dumps(result['usageRecord'], default=str)}\")
            break
"
```

**Verification path (3 methods):**

1. **Immediate:** Check `Results` vs `UnprocessedRecords` in the direct `BatchMeterUsage` SDK/API response (PascalCase)
2. **After ~15 min:** Query CloudTrail (as above) to find the record by `meteringRecordId` — CloudTrail `responseElements` is lowercase (`results`/`status`/`meteringRecordId`/`unprocessedRecords`)
3. **After billing cycle:** Check Seller Reports for the billed amount

## Pagination

### CloudTrail LookupEvents (50 events per page)

```bash
# First page
RESULT=$(aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventSource,AttributeValue=metering-marketplace.amazonaws.com \
  --region <SELLER_METERING_REGION> --max-results 50 --output json)

TOKEN=$(echo $RESULT | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('NextToken',''))")

# Subsequent pages
while [ -n "$TOKEN" ]; do
  RESULT=$(aws cloudtrail lookup-events \
    --lookup-attributes AttributeKey=EventSource,AttributeValue=metering-marketplace.amazonaws.com \
    --region <SELLER_METERING_REGION> --max-results 50 --next-token "$TOKEN" --output json)
  TOKEN=$(echo $RESULT | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('NextToken',''))")
done
```

For large result sets (full month of data), consider:

- Redirect stdout to a temp file (e.g. `> results.json`) for large result sets
- Or use `--max-pages` to cap memory usage and run multiple bounded queries with date ranges

## Troubleshooting

### "No records found"
Three most common causes:

1. **Wrong region** — CloudTrail Event History is REGIONAL. You MUST query the same region where your application calls BatchMeterUsage.
2. **Too soon** — ~15 minutes delivery latency. Wait at least 15 min after submission before querying CloudTrail.
3. **Wrong filter** — Ensure `eventSource=metering-marketplace.amazonaws.com` (not `aws-marketplace` or `marketplace`).
4. **Beyond 90 days** — Event History only retains 90 days. Use SDDS / Seller Reports for older data.

### CloudTrail totals don't match disbursement report
This is expected. CloudTrail shows **all submitted records** — including:

- `DuplicateRecord` — first-write-wins; the original quantity was billed (a differing-quantity resubmit is not billed — an under-billing risk, not simply "benign")
- `CustomerNotSubscribed` — rejected, never billed

Seller Reports show only **successfully billed** amounts. The difference between these two views is the rejected/duplicate records.

### "No errors but buyers are not being billed"
This means your dimension name does not match exactly (case-sensitive). There is NO runtime error — usage is silently dropped. Call `aws marketplace-catalog describe-entity` to verify the exact dimension key. Common mistakes: camelCase vs snake_case, extra spaces, typos.

### Script is slow or returns too much data

- Use `--max-pages` to cap the number of API calls (each page = 50 events)
- Use `--limit` to cap the number of retained records for `detail` queries
- Use `--start-date` and `--end-date` to narrow the time window
- For full-month exports, run bounded queries by week rather than loading 90 days at once
