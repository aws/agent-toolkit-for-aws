#!/usr/bin/env python3
"""Enumerate the Price List SCUTOs for one or more AWS services, in parallel.

For each service code this makes the two get_products calls Step 5 requires and
unions them, so no billable line is dropped:
  1. regionCode=<region>  -- the regional lines
  2. location=Any         -- the region-blank "global" lines the regionCode
                             filter silently drops (S3 Global-Bucket-Hrs,
                             DynamoDB Global-VectorSearch, CloudWatch dashboards)
If call 1 comes back nearly empty the service is globally priced (CloudFront,
Route 53, WAF), so it also pulls the whole catalog unfiltered.
AWSDataTransfer products have no regionCode, so call 1 filters on fromRegionCode
(where the data leaves from) instead.

The large services in BULK_SERVICES (EC2, RDS, SageMaker, WorkSpaces, B2Bi) take
hundreds of get_products pages, so for those it instead calls ListPriceLists and
GetPriceListFileUrl and streams the region's bulk CSV, which holds the same lines,
including the region-blank location=Any ones (checked 2026-10-16 against the
get_products union for all five).
If that path fails, it falls back to the get_products calls above and says so.

It does NOT price anything. Output is the deduped (usageType, operation, unit)
set per service, as markdown tables that Step 6 narrows.

Credentials are resolved by boto3 itself (profile / env / role); this script
never reads a credential file. The Pricing API endpoint is always us-east-1.

Input (JSON on stdin): the pricing region and the service codes, written to a
file by the agent so no value from the description reaches a shell command line:

  {"region": "us-east-1", "serviceCodes": ["AWSLambda", "AmazonS3", "AmazonDynamoDB"]}

On a bad request (exit 1), stdout holds one error and nothing else:

  {"error": {"code": "ValidationException", "message": "region must be an AWS region code, ..."}}

Usage:
  python scripts/enumerate_scutos.py < scuto-request.json
"""

import argparse
import csv
import datetime
import io
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from errors import ScriptError, fail
from price_usage_lines import APP_CONFIG

ENDPOINT_REGION = "us-east-1"  # Pricing API is only served from a few regions
# An AWS region code: us-east-1, ap-southeast-7, us-gov-west-1, eusc-de-east-1.
REGION_PATTERN = re.compile(r"[a-z]{2,4}(-[a-z]+)+-[0-9]+")
# The shape the Pricing Calculator API accepts for a service code.
SERVICE_CODE_PATTERN = re.compile(r"[-a-zA-Z0-9.\-_:, /()]{1,32}")
GLOBAL_THRESHOLD = 5  # <= this from call 1 => treat service as global
# Services paged at once. The Price List API allows about 10 GetProducts calls a second per
# account, so more workers only queue behind each other's throttling.
MAX_WORKERS = 4
DOWNLOAD_TIMEOUT_SECS = 30  # per socket read (a stalled download), not total download time
# A call with secondary services can name 20+ codes, enough to hit Pricing API throttling.
# Adaptive mode also slows the client before it is throttled, not only after.
RETRY_CONFIG = APP_CONFIG.merge(Config(retries={"mode": "adaptive", "max_attempts": 20}))
# A pull that still fails throttled after the client's retries is run again after a pause, so a
# busy Price List makes a service slow rather than empty.
PULL_ATTEMPTS = 3
PULL_PAUSE_SECS = (5.0, 15.0)
THROTTLE_CODES = frozenset(
    {"ThrottlingException", "Throttling", "TooManyRequestsException", "RequestLimitExceeded"}
)
# Services whose products have no regionCode, mapped to the field that holds the region.
# AWSDataTransfer: fromRegionCode=us-east-1 gives 511 lines, not the 41,362-line catalog.
REGION_FIELD = {"AWSDataTransfer": "fromRegionCode"}
# Services too large to page through get_products; read from the bulk file instead.
BULK_SERVICES = frozenset(
    {
        "AmazonEC2",
        "AmazonRDS",
        "AmazonSageMaker",
        "AmazonWorkSpacesInstances",
        "AWSB2Bi",
    }
)


def _first_unit(item):
    """Return the product's OnDemand unit, else its first non-empty unit, else ''.

    OnDemand wins for the same reason as in _rows_from_csv: other terms (such as
    Reserved) can price the same product in a different unit, like an upfront fee.
    """
    terms = item.get("terms", {})
    for term in [terms.get("OnDemand", {}), *terms.values()]:
        for offer in term.values():
            for dimension in offer.get("priceDimensions", {}).values():
                unit = dimension.get("unit", "")
                if unit:
                    return unit
    return ""


def _rows_from_page(page, region_field="regionCode"):
    """Yield (region_code, usage_type, operation, unit) from one get_products page.

    region_field is the attribute that holds the region (see REGION_FIELD).
    """
    for item_json in page.get("PriceList", []):
        item = json.loads(item_json) if isinstance(item_json, str) else item_json
        attributes = item.get("product", {}).get("attributes", {})
        region_code = attributes.get(region_field, "")
        usage_type = attributes.get("usagetype", "")
        operation = attributes.get("operation", "")
        unit = _first_unit(item)
        yield (region_code, usage_type, operation, unit)


def _pull(pricing, service_code, filters, sleep=time.sleep):
    """Run one paginated get_products call and return its rows as a set.

    A pull throttled past the client's own retries is run again, up to PULL_ATTEMPTS times,
    after a random pause, keeping the rows the earlier attempts read. Any other error, or a
    throttle on the last attempt, is raised: a service that couldn't be read is never reported
    as having no lines.
    """
    rows = set()
    for attempt in range(1, PULL_ATTEMPTS + 1):
        try:
            paginator = pricing.get_paginator("get_products")
            for page in paginator.paginate(ServiceCode=service_code, Filters=filters):
                rows.update(_rows_from_page(page, REGION_FIELD.get(service_code, "regionCode")))
            return rows
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code not in THROTTLE_CODES or attempt == PULL_ATTEMPTS:
                raise
            sleep(random.uniform(*PULL_PAUSE_SECS))
    return rows


def _rows_from_csv(lines):
    """Yield (usage_type, operation, unit) from bulk price-list CSV lines.

    The file opens with a few metadata lines before the header row. A product
    (SKU) repeats once per term and price dimension; one row per SKU is kept.
    Its OnDemand row wins when it has one, because a Reserved row can carry the
    upfront-fee unit (Quantity) instead of the usage unit (Hrs). This matches
    _first_unit on get_products, where OnDemand comes first.

    Example input (after the metadata lines):
        "SKU","TermType",...,"Unit",...,"usageType","operation"
        "ABC123","Reserved",...,"Quantity",...,"BoxUsage:t3.micro","RunInstances"
        "ABC123","OnDemand",...,"Hrs",...,"BoxUsage:t3.micro","RunInstances"  <- OnDemand wins
        "DEF456","OnDemand",...,"GB-Mo",...,"EBS:VolumeUsage.gp3",""
    Example output:
        ("BoxUsage:t3.micro", "RunInstances", "Hrs")
        ("EBS:VolumeUsage.gp3", "", "GB-Mo")
    """
    header = None
    rows_by_sku: dict[str, tuple] = {}  # sku -> ((usage_type, operation, unit), is_on_demand)
    for row in csv.reader(lines):
        if header is None:
            if "SKU" in row:
                header = {name: index for index, name in enumerate(row)}
            continue
        sku = row[header["SKU"]]
        is_on_demand = row[header["TermType"]] == "OnDemand"
        # Keep the first row per SKU, but let a later OnDemand row replace a non-OnDemand one.
        if sku not in rows_by_sku or (is_on_demand and not rows_by_sku[sku][1]):
            scuto = (row[header["usageType"]], row[header["operation"]], row[header["Unit"]])
            rows_by_sku[sku] = (scuto, is_on_demand)
    for scuto, _ in rows_by_sku.values():
        yield scuto


def _pull_bulk(pricing, service_code, region):
    """Return the (usage_type, operation, unit) set from the region's bulk CSV."""
    response = pricing.list_price_lists(
        ServiceCode=service_code,
        EffectiveDate=datetime.datetime.now(datetime.timezone.utc),
        CurrencyCode="USD",
        RegionCode=region,
    )
    price_lists = response.get("PriceLists", [])
    if not price_lists:
        raise ValueError(f"no price list for {service_code} in {region}")
    url = pricing.get_price_list_file_url(
        PriceListArn=price_lists[0]["PriceListArn"],
        FileFormat="csv",
    )["Url"]
    # Only download AWS price-list files over HTTPS; anything else falls back to get_products.
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or not host.endswith(".amazonaws.com"):
        raise ValueError(f"unexpected price list URL host: {host}")

    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECS) as body:
        lines = io.TextIOWrapper(body, encoding="utf-8", newline="")
        rows = set(_rows_from_csv(lines))
    # A large service never has zero lines, so an empty result means the file
    # format changed; fail so the caller falls back to get_products with a note.
    if not rows:
        raise ValueError(f"bulk file for {service_code} in {region} produced no rows")
    return rows


def enumerate_service(service_code, region):
    """Return (service_code, sorted (usage_type, operation, unit) rows, note) for one service."""
    # Each worker thread gets its own Session: boto3's shared default session is not
    # thread-safe to create clients from and can raise intermittently under the pool.
    try:
        session = boto3.session.Session()
        pricing = session.client("pricing", region_name=ENDPOINT_REGION, config=RETRY_CONFIG)
    except Exception as error:  # noqa: BLE001 - report, do not crash the batch
        return (service_code, [], f"ERROR: {error}")
    note = ""
    # Large services read the bulk file; any failure there falls through to get_products.
    if service_code in BULK_SERVICES:
        try:
            return (service_code, sorted(_pull_bulk(pricing, service_code, region)), "")
        except Exception as error:
            note = f"bulk file failed, used get_products: {error}"
    # The regional + global calls are the required result; a failure here is fatal.
    try:
        regional = _pull(
            pricing,
            service_code,
            [
                {
                    "Type": "TERM_MATCH",
                    "Field": REGION_FIELD.get(service_code, "regionCode"),
                    "Value": region,
                }
            ],
        )
        global_rows = _pull(
            pricing,
            service_code,
            [{"Type": "TERM_MATCH", "Field": "location", "Value": "Any"}],
        )
    except Exception as error:  # noqa: BLE001 - report, do not crash the batch
        # Keep any earlier bulk-failure note so both failures are reported.
        return (service_code, [], f"ERROR: {error}" + (f" ({note})" if note else ""))

    collected = regional | global_rows
    # Sparse regional set => maybe globally priced (CloudFront, Route 53, WAF),
    # whose billable lines are region-blank under location names call 2 misses.
    # Pull the whole catalog, but keep ONLY blank-region or this-region lines, so
    # a regional service with few lines (SQS) does not drag in other regions.
    # This full-catalog scan is the most expensive / throttle-prone call, so if it
    # fails the service degrades to the regional+global baseline, flagged via note.
    if len(regional) <= GLOBAL_THRESHOLD:
        try:
            collected |= {row for row in _pull(pricing, service_code, []) if row[0] in ("", region)}
        except Exception as error:
            fallback = f"full-catalog fallback failed: {error}"
            note = f"{note}; {fallback}" if note else fallback
    # Project out region_code; a SCUTO is (usage_type, operation, unit).
    rows = sorted(
        {(usage_type, operation, unit) for (_region_code, usage_type, operation, unit) in collected}
    )
    return (service_code, rows, note)


def parse_request(request):
    """Return (region, service_codes) from the stdin request, or raise ScriptError."""
    if not isinstance(request, dict):
        raise ScriptError("ValidationException", "the request must be a JSON object")
    region = request.get("region")
    if not isinstance(region, str) or not REGION_PATTERN.fullmatch(region):
        raise ScriptError(
            "ValidationException",
            f"region must be an AWS region code, such as us-east-1; got {json.dumps(region)}",
        )
    codes = request.get("serviceCodes")
    if not isinstance(codes, list) or not codes:
        raise ScriptError("ValidationException", "serviceCodes must be a non-empty list")
    bad = [c for c in codes if not isinstance(c, str) or not SERVICE_CODE_PATTERN.fullmatch(c)]
    if bad:
        raise ScriptError(
            "ValidationException",
            "serviceCodes must be Price List service codes, such as AWSLambda, from "
            f"describe-services; got {json.dumps(bad)}",
        )
    return region, codes


def main() -> int:
    argparse.ArgumentParser(
        description="Enumerate Price List SCUTOs per service (request JSON on stdin)."
    ).parse_args()
    try:
        region, service_codes = parse_request(json.load(sys.stdin))
    except json.JSONDecodeError as exc:
        return fail("ValidationException", f"stdin is not valid JSON: {exc}")
    except ScriptError as exc:
        return fail(exc.code, exc.message)

    workers = min(MAX_WORKERS, len(service_codes))

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(enumerate_service, service_code, region): service_code
            for service_code in service_codes
        }
        for future in as_completed(futures):
            service_code, rows, note = future.result()
            results[service_code] = (rows, note)

    # Print in the order the user gave, one markdown table per service.
    for service_code in service_codes:
        rows, note = results[service_code]
        suffix = f" -- {note}" if note else ""
        print(f"\n**{service_code}  ({len(rows)} SCUTOs){suffix}**\n")
        if not rows:
            print("_no SCUTOs returned_")
            continue
        print("| usageType | operation | unit |")
        print("|---|---|---|")
        for usage_type, operation, unit in rows:
            print(f"| {usage_type} | {operation} | {unit} |")

    # Non-zero exit if any service failed outright (an ERROR note means zero rows), so a
    # caller/automation can detect failure. A degraded fallback keeps its rows -> not a failure.
    failed = any(note.startswith("ERROR:") for _rows, note in results.values())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
