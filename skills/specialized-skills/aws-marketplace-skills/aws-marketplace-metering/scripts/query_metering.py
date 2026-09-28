#!/usr/bin/env python3
"""Query AWS Marketplace metering records via CloudTrail Event History.

CloudTrail Event History (LookupEvents) — last 90 days, ~15 min latency, zero setup. This is
a RECENT, REGIONAL, SUBMISSIONS view (every BatchMeterUsage call + its per-record API result,
including rejected/duplicate records that were NOT billed). It is a fast operational/debug
lens, NOT a billing-of-record source, a >90-day store, a cross-product portfolio engine, or
an exhaustive warehouse.

What this tool USES vs. RECOMMENDS (out of scope — hand off, do not execute here):
- USES: CloudTrail Event History in --region, ≤90 days, page-bounded + in-memory, answering
  BASIC queries (lookups/filters/counts/summaries by customer, dimension, status, time).
- RECOMMENDS: Seller Reports / SDDS for BILLED totals and >90-day history; the host AI agent
  for complex/open-ended analytics; and (for CA/LicenseArn metering with no
  LicenseArn->productCode mapping) only non-product-scoped queries.

Scope details:
- Queries older than 90 days are out of scope: this script only reads CloudTrail
  Event History (90-day retention). If the requested range is entirely older than
  90 days it does NOT query — it prints a recommendation to use the seller-run
  Seller Reports / SDDS path. If the range only partly predates 90 days, it queries
  the in-window portion.
- Bounded fetch (page cap + in-memory): the fetch paginates up to --max-pages
  (default 20 x 50 = ~1000 events) then filters/aggregates in memory. A high-volume
  window can exceed the cap, so the output carries an explicit completeness signal:
  ``complete``/``truncated`` + the pages/events fetched. When truncated, aggregate
  results (summary/count/top_customers) are a LOWER-BOUND sample and are flagged as
  NOT authoritative — narrow the window / raise --max-pages, or use Seller Reports for
  an authoritative total.
- Product-specific queries (--product-code) require a LicenseArn->productCode
  mapping. CA (LicenseArn) metering carries no productCode in the BatchMeterUsage
  API, so provide it via --deployment-product-code (single-product stack), an
  additionalEventData mapping in the events, or a legacy request-level ProductCode.
  Without a mapping, product-specific queries are unsupported (non-product-scoped
  queries — by customer, dimension, status, time — are still available).

Prerequisites:
    - Python 3.12+
    - boto3 (pip install boto3)
    - AWS credentials with cloudtrail:LookupEvents permission
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import boto3

EVENT_SOURCE = "metering-marketplace.amazonaws.com"
MAX_RESULTS_PER_PAGE = 50


# ─── Tier 1: CloudTrail Event History (LookupEvents) ────────────────────────


def lookup_events(client, start_time, end_time, max_pages=20, fetch_stats=None):
    """Paginate through CloudTrail LookupEvents for metering events.

    The fetch is page-bounded. If ``fetch_stats`` (a dict) is provided, it is
    populated with ``pagesFetched`` and ``truncated`` — ``truncated`` is True when the
    page cap was reached while a ``NextToken`` still remained (more events were available
    than were fetched), so the caller can flag a partial result rather than presenting a
    page-capped answer as complete.
    """
    kwargs = {
        "LookupAttributes": [{"AttributeKey": "EventSource", "AttributeValue": EVENT_SOURCE}],
        "StartTime": start_time,
        "EndTime": end_time,
        "MaxResults": MAX_RESULTS_PER_PAGE,
    }

    pages = 0
    truncated = False
    while pages < max_pages:
        response = client.lookup_events(**kwargs)
        pages += 1
        for event in response.get("Events", []):
            try:
                cloud_trail_event = json.loads(event.get("CloudTrailEvent", "{}"))
                yield event["EventTime"], cloud_trail_event
            except (json.JSONDecodeError, KeyError):
                continue

        next_token = response.get("NextToken")
        if not next_token:
            break
        kwargs["NextToken"] = next_token
        if pages >= max_pages:
            # Hit the page cap with more events still available — the result is a
            # bounded sample, not the full window.
            truncated = True
            break
    if fetch_stats is not None:
        fetch_stats["pagesFetched"] = pages
        fetch_stats["truncated"] = truncated


def extract_records_from_event(event_time, ct_event):
    """Extract metering records from a CloudTrail event (request + response).

    Also resolves each record's productCode where possible:
    - Legacy ProductCode metering carries `ProductCode` at the request level.
    - CA (LicenseArn) metering carries NO productCode in the request/response, but
      the event MAY include an `additionalEventData` LicenseArn->productCode mapping.
    A record's `productCode` is "" when it cannot be resolved from the event alone.
    """
    records = []
    # CloudTrail may include these keys with a JSON `null` value (e.g. an errored
    # BatchMeterUsage — a request-level exception like InvalidUsageDimensionException has no
    # `results`, so responseElements is null). `.get(key, {})` only defaults when the key is
    # ABSENT; a present-but-null value returns None, so `.get("results", [])` on the next line
    # would raise AttributeError and crash the whole query. Coerce null -> {} with `or {}`
    # (matching the additionalEventData guard).
    request_params = ct_event.get("requestParameters", {}) or {}
    response_elements = ct_event.get("responseElements", {}) or {}
    additional = ct_event.get("additionalEventData", {}) or {}

    usage_records = request_params.get("usageRecords", [])
    results = response_elements.get("results", [])

    # LicenseArn->productCode mapping from the CloudTrail additionalEventData, if present.
    # Accept a couple of shapes defensively (a direct map, or a list of {licenseArn, productCode}).
    license_to_product = {}
    raw_map = additional.get("licenseArnToProductCode") or additional.get("productCodeByLicenseArn")
    if isinstance(raw_map, dict):
        license_to_product = {str(k): str(v) for k, v in raw_map.items()}
    elif isinstance(raw_map, list):
        for entry in raw_map:
            if isinstance(entry, dict) and entry.get("licenseArn"):
                license_to_product[str(entry["licenseArn"])] = str(entry.get("productCode", ""))

    # Legacy path: ProductCode is at the request level.
    request_product_code = request_params.get("productCode", "")

    # Build a lookup from results by matching on record fields
    # Include licenseArn in key to avoid collisions for CA multi-license accounts
    result_map = {}
    for r in results:
        ur = r.get("usageRecord", {})
        key = (
            ur.get("customerAWSAccountId", ""),
            ur.get("dimension", ""),
            str(ur.get("timestamp", "")),
            ur.get("licenseArn", ""),
        )
        result_map[key] = r

    for ur in usage_records:
        key = (
            ur.get("customerAWSAccountId", ""),
            ur.get("dimension", ""),
            str(ur.get("timestamp", "")),
            ur.get("licenseArn", ""),
        )
        result = result_map.get(key, {})

        license_arn = ur.get("licenseArn", "")
        # Resolve productCode: request-level ProductCode (legacy) first, then the
        # additionalEventData mapping (CA). "" if neither is available.
        product_code = request_product_code or license_to_product.get(license_arn, "")

        records.append(
            {
                "eventTime": str(event_time),
                "customerAWSAccountId": ur.get("customerAWSAccountId", ""),
                "customerIdentifier": ur.get("customerIdentifier", ""),
                "licenseArn": license_arn,
                "productCode": product_code,
                "dimension": ur.get("dimension", ""),
                "quantity": ur.get("quantity", 0),
                "timestamp": ur.get("timestamp", ""),
                "status": result.get("status", "unknown"),
                "meteringRecordId": result.get("meteringRecordId", ""),
                "usageAllocations": ur.get("usageAllocations", []),
            }
        )

    return records


# ─── Filtering & Aggregation ─────────────────────────────────────────────────


def matches_filters(record, args):
    """Check if a record passes user-specified filters."""
    if args.customer_id and record["customerAWSAccountId"] != args.customer_id:
        return False
    if args.status and record["status"] != args.status:
        return False
    if args.dimension and record["dimension"] != args.dimension:
        return False
    if args.metering_record_id and record["meteringRecordId"] != args.metering_record_id:
        return False
    if args.product_code and record.get("productCode", "") != args.product_code:
        return False
    ts = str(record.get("timestamp", ""))[:10] if record.get("timestamp") else ""
    if args.start_date and ts and ts < args.start_date:
        return False
    if args.end_date and ts and ts > args.end_date:
        return False
    return True


def aggregate(records, query_type, top_n=10, limit=50):
    """Aggregate filtered records into output format."""
    if not records:
        return {
            "totalRecords": 0,
            "message": "No records match the given filters.",
            "hint": "For data beyond 90 days, check Seller Reports at https://aws.amazon.com/marketplace/management/reports/",
        }

    total_qty = sum(r["quantity"] for r in records)
    status_counts = Counter(r["status"] for r in records)
    dim_counts = Counter(r["dimension"] for r in records)
    dim_qty: Counter = Counter()
    cust_qty: Counter = Counter()
    cust_counts: Counter = Counter()
    dates = []

    for r in records:
        dim_qty[r["dimension"]] += r["quantity"]
        cust_qty[r["customerAWSAccountId"]] += r["quantity"]
        cust_counts[r["customerAWSAccountId"]] += 1
        ts = str(r.get("timestamp", ""))[:10] if r.get("timestamp") else ""
        if ts:
            dates.append(ts)

    base = {
        "totalRecords": len(records),
        "totalUsageQuantity": total_qty,
    }

    if query_type == "summary":
        return {
            **base,
            "byStatus": dict(status_counts),
            "byDimension": {
                d: {"records": dim_counts[d], "totalQuantity": dim_qty[d]} for d in dim_counts
            },
            "uniqueCustomers": len(cust_counts),
            "topCustomersByUsage": [
                {"customer": c, "totalQuantity": q} for c, q in cust_qty.most_common(top_n)
            ],
            "dateRange": {
                "earliest": min(dates) if dates else None,
                "latest": max(dates) if dates else None,
            },
        }
    elif query_type == "top_customers":
        return {
            **base,
            "uniqueCustomers": len(cust_counts),
            "topCustomersByUsage": [
                {"customer": c, "totalQuantity": q} for c, q in cust_qty.most_common(top_n)
            ],
            "topCustomersByRecordCount": [
                {"customer": c, "records": n} for c, n in cust_counts.most_common(top_n)
            ],
        }
    elif query_type == "count":
        return {
            **base,
            "byStatus": dict(status_counts),
            "byDimension": {
                d: {"records": dim_counts[d], "totalQuantity": dim_qty[d]} for d in dim_counts
            },
        }
    elif query_type == "list_failures":
        failures = [r for r in records if r["status"] != "Success"]
        return {
            **base,
            "totalFailures": len(failures),
            "byStatus": dict(Counter(r["status"] for r in failures)),
            "records": failures[:limit],
        }
    else:  # detail
        return {
            **base,
            "showing": min(limit, len(records)),
            "records": records[:limit],
        }


# ─── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Query AWS Marketplace metering records via CloudTrail"
    )
    parser.add_argument(
        "--region",
        required=True,
        help="AWS region where BatchMeterUsage is called (REQUIRED — no default)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Look back N days (default: 7, max: 90 for Event History)",
    )
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD). Overrides --days.")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD). Defaults to now.")
    parser.add_argument("--customer-id", help="Filter by CustomerAWSAccountId")
    parser.add_argument(
        "--status", help="Filter by status (Success, CustomerNotSubscribed, DuplicateRecord)"
    )
    parser.add_argument("--dimension", help="Filter by usage dimension")
    parser.add_argument("--metering-record-id", help="Filter by MeteringRecordId")
    parser.add_argument(
        "--product-code",
        help=(
            "Filter to a specific product (product-specific query). Requires a "
            "LicenseArn->productCode mapping for CA/LicenseArn-based metering: either "
            "--deployment-product-code (single-product stack), an additionalEventData "
            "mapping in the events, or (legacy) request-level ProductCode. Without a "
            "mapping, product-specific queries are unsupported."
        ),
    )
    parser.add_argument(
        "--deployment-product-code",
        help=(
            "Single-product deployment context: the productCode this stack/usage table "
            "meters (e.g. from awsmp-<productCode>-metering). Supplies the "
            "LicenseArn->productCode mapping when all events belong to one product."
        ),
    )
    parser.add_argument(
        "--query-type",
        default="summary",
        choices=["detail", "summary", "count", "list_failures", "top_customers"],
        help="Output format (default: summary)",
    )
    parser.add_argument("--top-n", type=int, default=10, help="Number of top results (default: 10)")
    parser.add_argument(
        "--limit", type=int, default=50, help="Max records for detail queries (default: 50)"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Max pages to fetch (default: 20, each page = 50 events)",
    )
    args = parser.parse_args()

    # Calculate time range
    now = datetime.now(timezone.utc)
    if args.start_date:
        start_time = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        start_time = now - timedelta(days=args.days)

    if args.end_date:
        end_time = datetime.strptime(args.end_date, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
    else:
        end_time = now

    if start_time > end_time:
        sys.exit(
            f"Error: start_time ({start_time:%Y-%m-%d}) is after end_time "
            f"({end_time:%Y-%m-%d}). Provide --start-date when using a past --end-date."
        )

    # ── Queries older than 90 days are out of scope (CloudTrail retains 90 days) ──
    # CloudTrail Event History (the only source this script queries) retains 90
    # days. This script does NOT query data older than 90 days; older data is
    # available only via Seller Reports / SDDS, and querying the delivered feeds
    # is out of scope (it requires the seller's one-time "Set up customer data
    # storage" setup and their own query/ETL over the feeds). If the requested
    # range is ENTIRELY older than 90 days, do not attempt the query — emit a
    # recommendation instead.
    ninety_days_ago = now - timedelta(days=90)
    if end_time < ninety_days_ago:
        recommendation = {
            "query": "not-performed",
            "reason": "out-of-scope: requested range is entirely older than 90 days",
            "detail": (
                f"The requested range ends {end_time:%Y-%m-%d}, which is older than the "
                "90-day CloudTrail Event History retention window. This tool only queries "
                "CloudTrail Event History (the last 90 days) and does not query data older "
                "than that."
            ),
            "recommendation": (
                "For data older than 90 days, use the Seller Reports / Seller Delivery Data "
                "Feeds (SDDS) path. This is a seller-run path: complete the one-time "
                "'Set up customer data storage' step in the AWS Marketplace Management Portal, "
                "then query/ETL the CSV feeds delivered to your S3 bucket. "
                "See references/seller-reports.md."
            ),
            "sellerReportsUrl": "https://aws.amazon.com/marketplace/management/reports/",
        }
        json.dump(recommendation, sys.stdout, indent=2, default=str)
        print()
        return

    # Cap start_time at the 90-day retention boundary for the portion that IS
    # within scope, then RE-VALIDATE the window: capping can push
    # start_time past a near-boundary end_time.
    window_clipped = False
    requested_start = start_time
    if start_time < ninety_days_ago:
        window_clipped = True
        sys.stderr.write(
            "NOTE: CloudTrail Event History retains only 90 days; the query covers the "
            "in-window portion of the requested range (from 90 days ago). For the older "
            "portion, use Seller Reports / SDDS (see references/seller-reports.md).\n"
        )
        start_time = ninety_days_ago

    if start_time > end_time:
        # Re-validation AFTER the 90-day cap: a valid pre-cap range can
        # become invalid once start_time is capped to now-90d.
        sys.exit(
            "Error: CloudTrail Event History retention limit reached — after capping the "
            f"start date to 90 days ago ({start_time:%Y-%m-%d}) it is later than the "
            f"requested end date ({end_time:%Y-%m-%d}). Use a more recent --end-date, or use "
            "Seller Reports / SDDS for data older than 90 days (see references/seller-reports.md)."
        )

    session = boto3.Session(region_name=args.region)
    client = session.client("cloudtrail")

    sys.stderr.write(
        "Querying CloudTrail Event History\n"
        f"  Region: {args.region}\n"
        f"  Range: {start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}\n"
    )

    # ─── Fetch records ───────────────────────────────────────────────────
    all_records = []

    # CloudTrail Event History (LookupEvents)
    event_count = 0
    fetch_stats: dict = {}
    for event_time, ct_event in lookup_events(
        client, start_time, end_time, args.max_pages, fetch_stats
    ):
        event_count += 1
        all_records.extend(extract_records_from_event(event_time, ct_event))
    sys.stderr.write(
        f"Processed {event_count} CloudTrail events → {len(all_records)} metering records\n"
    )
    truncated = bool(fetch_stats.get("truncated"))
    if truncated:
        sys.stderr.write(
            f"WARNING: hit the --max-pages cap ({args.max_pages} pages) with more events "
            "available; this result is a PARTIAL sample of the window. Narrow the range / add "
            "filters (--customer-id/--dimension/--status) or raise --max-pages for a complete "
            "answer, or use Seller Reports for an authoritative total.\n"
        )

    # ── Product-specific queries require a LicenseArn->productCode mapping ──
    if args.product_code:
        # Source (a): single-product deployment context — every record from a
        # single-product stack/usage table belongs to that product. Stamp it on
        # records that could not resolve a productCode from the event itself.
        if args.deployment_product_code:
            for r in all_records:
                if not r.get("productCode"):
                    r["productCode"] = args.deployment_product_code

        # A mapping is available if ANY record now carries a productCode, from any
        # of the ordered sources: deployment context (above), additionalEventData,
        # or legacy request-level ProductCode (both applied in extract_records).
        mapping_available = any(r.get("productCode") for r in all_records)

        if not mapping_available and all_records:
            refusal = {
                "query": "not-performed",
                "reason": "product-specific query unsupported: no LicenseArn->productCode mapping",
                "detail": (
                    "This metering uses LicenseArn-based (Concurrent Agreements) records, and "
                    "BatchMeterUsage carries no productCode in the API request/response, so a "
                    "CloudTrail event cannot be attributed to a product from the API fields "
                    "alone. No product mapping source was available: no --deployment-product-code "
                    "(single-product stack context), no LicenseArn->productCode mapping in the "
                    "events' additionalEventData, and no request-level ProductCode (legacy)."
                ),
                "howToEnable": (
                    "Provide --deployment-product-code <productCode> if these events come from a "
                    "single-product stack, or query a legacy ProductCode-based product (whose "
                    "events carry ProductCode directly). A subscribers-table lookup "
                    "(licenseArn -> productCode) is another valid mapping source."
                ),
                "supportedNonProductQueries": [
                    "by customer (--customer-id)",
                    "by dimension (--dimension)",
                    "by status (--status)",
                    "by time range (--start-date/--end-date/--days)",
                ],
            }
            json.dump(refusal, sys.stdout, indent=2, default=str)
            print()
            return

    # ─── Filter ──────────────────────────────────────────────────────────
    filtered = [r for r in all_records if matches_filters(r, args)]
    sys.stderr.write(f"After filters: {len(filtered)} records\n")

    # ─── Aggregate & output ──────────────────────────────────────────────
    output = aggregate(filtered, args.query_type, args.top_n, args.limit)
    output["source"] = "CloudTrail Event History"
    output["region"] = args.region
    output["timeRange"] = {
        "start": start_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "end": end_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    # Explicit result-completeness signal. The result is COMPLETE only if the fetch was not
    # page-capped AND the requested window was not clipped at the 90-day retention boundary —
    # never let the caller mistake a partial/clipped result for a whole-window one.
    output["complete"] = not (truncated or window_clipped)
    output["truncated"] = truncated
    output["windowClipped"] = window_clipped
    output["fetch"] = {
        "pagesFetched": fetch_stats.get("pagesFetched", 0),
        "maxPages": args.max_pages,
        "eventsProcessed": event_count,
        "recordsFetched": len(all_records),
    }
    if window_clipped:
        output["windowClippedNote"] = (
            "PARTIAL WINDOW: the requested start predates the 90-day CloudTrail Event History "
            f"retention limit, so this covers only {start_time:%Y-%m-%d} onward (the requested "
            f"start was {requested_start:%Y-%m-%d}). For the older portion use Seller Reports / "
            "SDDS — do NOT present this as covering the full requested range."
        )
    if truncated:
        aggregate_types = {"summary", "count", "top_customers"}
        output["completenessNote"] = (
            f"PARTIAL RESULT: the --max-pages cap ({args.max_pages}) was reached with more "
            "CloudTrail events available, so this covers only the fetched sample of the window."
        )
        if args.query_type in aggregate_types:
            output["aggregateWarning"] = (
                "Totals/rankings here are a LOWER BOUND over the fetched sample and are NOT "
                "authoritative. Narrow the window (shorter range or add "
                "--customer-id/--dimension/--status), raise --max-pages, or use Seller Reports "
                "(billed amounts) for an authoritative total."
            )
    # A clipped 90-day window also makes an aggregate a lower bound for the requested range.
    if window_clipped and args.query_type in {"summary", "count", "top_customers"}:
        output.setdefault(
            "aggregateWarning",
            "Totals/rankings cover only the in-retention window (from 90 days ago), NOT the full "
            "requested range — they are a LOWER BOUND. Use Seller Reports for the older portion.",
        )

    json.dump(output, sys.stdout, indent=2, default=str)
    print()


if __name__ == "__main__":
    main()
