#!/usr/bin/env python3
"""Price the usage step's lines and render the cost estimate report.

Input (JSON on stdin): the region (or a list of regions for a multi-region
workload; each line's usage type already carries its region), the rateType, and
the usage step's lines.
A line whose source is UNKNOWN needs no low, mid or high; other fields are ignored.
A Bedrock line can name its "model", as the Price List spells it.

  {"region": "us-east-1",
   "rateType": "BEFORE_DISCOUNTS",
   "lines": [
     {"serviceCode": "AmazonS3", "usageType": "TimedStorage-ByteHrs", "operation": "",
      "low": 500, "mid": 500, "high": 500,
      "source": "CUSTOMER_STATED", "assumption": "Stated: 500 GB in S3 Standard."},
     {"serviceCode": "AWSEvents", "usageType": "Event-64K-Chunks", "operation": "",
      "source": "UNKNOWN"}]}

Every line that is not UNKNOWN is priced through price_usage_lines with amounts
[low, mid, high], in calls of at most price_usage_lines.MAX_LINES lines each.
The exception is a line whose model shares its SCUTO with other models in the
Price List: the pricing API would price whichever model it finds first, so that
line is priced at the model's own OnDemand rate from the Price List instead, and
the report says no discount is applied to it.

Output (markdown on stdout, exit 0): a summary line, the top cost drivers (up to
five services by Mid), one row per serviceCode, a total row, a note for every
line that has usage but prices at $0, and a footer for every line left out of
the total and why.

A line priced at $0 is checked against the Price List's free range for its
SCUTO. Inside it, the note says so. Above it, the pricing API has returned $0
for usage the Price List charges for: under a discounted rate type the line is
priced again at BEFORE_DISCOUNTS and marked as list price; otherwise, or if that
also returns $0, the line is left out of the total with the reason.

It also writes the priced lines, each with its amounts, costs, source and
assumption, to cost-estimate-priced.json in the current directory, for the
user and for tools that check the estimate against what was priced. The report
table shows only the cost per service, so this file is where a line's
assumption can be read. Both that file and the request file are
replaced on the next run, so each estimate is also saved as
cost-estimate-request-<YYYYMMDD-HHMMSS>.json and
cost-estimate-priced-<YYYYMMDD-HHMMSS>.json (local time), never replacing an
earlier copy, and the report's last line names the two files.

  The estimated bill is about $14.83/month.

  Top cost drivers:
  1. AmazonS3: $11.50 (78%)
  2. AWSLambda: $3.33 (22%)

  Monthly cost estimate (public on-demand rates, us-east-1)

  | Service | Low | Mid | High | % of total |
  |---|---|---|---|---|
  | AmazonS3 | $11.50 | $11.50 | $11.50 | 78% |
  | AWSLambda | $3.33 | $3.33 | $3.33 | 22% |
  | **Total** | **$14.83** | **$14.83** | **$14.83** | **100%** |

  Priced at $0 despite usage:
  - AWSLambda / Request / Invoke: prices at $0, within the Price List's free tier

  Not included in the total:
  - AWSEvents / Event-64K-Chunks: could not determine a usage amount, so no cost

  Saved this estimate as cost-estimate-request-20261114-153012.json and
  cost-estimate-priced-20261114-153012.json.
  Each line's usage, cost and assumption is in
  cost-estimate-priced-20261114-153012.json.

On failure (exit 1), stdout holds one error. For example, a problem in the
request file:

  {"error": {"code": "ValidationException", "message": "lines[1] is missing low"}}

an assumed log volume that costs more than LOG_COMPUTE_RATIO times the compute
writing the logs (see check_assumed_logs):

  {"error": {"code": "AssumedLogVolumeTooHigh",
             "message": "cost-estimate-request.json: the assumed log volume ... run again. ..."}}

or a pricing error, passed through unchanged:

  {"error": {"code": "ValidationException",
             "message": "Invalid rate type for a member account. ..."}}

Usage:
  python scripts/render_report.py < cost-estimate-request.json
"""

import argparse
import json
import math
import os
import sys
import traceback
from collections import Counter
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

import boto3
import price_usage_lines as pricing
from errors import ScriptError, fail

BANDS = ("low", "mid", "high")
UNKNOWN = "UNKNOWN"
RATE_TYPE_LABELS = {
    "BEFORE_DISCOUNTS": "public on-demand rates",
    "AFTER_DISCOUNTS": "after negotiated discounts",
    "AFTER_DISCOUNTS_AND_COMMITMENTS": (
        "after negotiated discounts plus Savings Plans and Reserved Instances"
    ),
}
# Services listed as the top cost drivers, before the table.
MAX_DRIVERS = 5
# An assumed log volume may cost at most this many times the compute that writes the logs. Few
# services log more than that, and the ones that do are run by owners who know it and give the
# volume, which this check never questions.
LOG_COMPUTE_RATIO = 2.0
# ... and only when the logs are at least this share of the whole estimate. The check protects the
# total: a log line below this share moves the total by at most about as much even when it is
# several times too high, which isn't worth sending the agent back to price again. It also keeps
# the check off small estimates whose compute is nearly idle. Such a line can still be high for
# its service; that is left to how the log volume is sized, not to this check.
LOG_MIN_SHARE = 0.10
# Compute: the application compute that runs the code writing per-request logs, by service, and
# EC2's instance usage types (EC2 also covers Elastic Beanstalk, Batch and EMR). Data stores
# (RDS, DynamoDB, DAX, ElastiCache, OpenSearch) are left out on purpose: they rarely write logs per
# request, and counting them would let a large database hide an oversized log line. A service
# missing here usually means the check finds no compute and doesn't run.
COMPUTE_SERVICES = (
    "AmazonECS",
    "AWSLambda",
    "AmazonEKS",
    "AmazonSageMaker",
    "AWSAppRunner",
    "AmazonLightsail",
)
EC2_COMPUTE = ("BoxUsage", "SpotUsage", "DedicatedUsage")
# Log lines: CloudWatch Logs ingestion (standard and vended) and the stored log data it adds.
LOG_INGESTION = ("DataProcessing-Bytes", "VendedLog-Bytes")
LOG_STORAGE = ("TimedStorage-ByteHrs",)
UNKNOWN_REASON = "could not determine a usage amount, so no cost"
MISSING_REASON = "not returned by the pricing API"
NOTHING_PRICED = "No line could be priced, so there is no estimate."
ZERO_COST_REASON = "prices at $0, within the Price List's free tier"
ZERO_UNCHECKED_REASON = "prices at $0; the Price List could not be checked for a free tier"
ZERO_CHARGED_REASON = "the pricing API returned $0 for usage the Price List charges for, so no cost"
LIST_RATE = "BEFORE_DISCOUNTS"
SHARED_NOTE = (
    "several models share these lines' usage types, so each is priced at its model's "
    "own rate from the Price List and no discount is applied"
)
NO_MODEL_REASON = "the Price List has no single flat OnDemand rate for this model on this line"
NO_PRICE_LIST_REASON = "the Price List could not be read for this model's rate"
PRICED_FILE = "cost-estimate-priced.json"
# Each estimate's saved copies: <prefix>-<YYYYMMDD-HHMMSS>.json, in local time.
COPY_PREFIXES = ("cost-estimate-request", "cost-estimate-priced")


def region_label(region):
    """The report's region: one region, or every region of a multi-region workload."""
    return ", ".join(region) if isinstance(region, list) else region


def scuto_of(line):
    return (line["serviceCode"], line["usageType"], line["operation"])


def key_of(line):
    """A line's identity: its SCUTO, plus its model when it names one."""
    return scuto_of(line) + ((line["model"],) if line.get("model") else ())


def validate(request):
    """Check the request before anything is priced."""
    if not isinstance(request, dict):
        raise ScriptError("ValidationException", "request must be a JSON object")
    if not isinstance(request.get("rateType"), str) or not request["rateType"]:
        raise ScriptError("ValidationException", "request is missing rateType")
    region = request.get("region")
    regions = region if isinstance(region, list) else [region]
    if not regions or not all(isinstance(r, str) and r for r in regions):
        raise ScriptError(
            "ValidationException", "request is missing region (a region, or a list of regions)"
        )
    lines = request.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ScriptError("ValidationException", "request must hold at least one line")
    seen = set()
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            raise ScriptError("ValidationException", f"lines[{i}] must be an object")
        missing = [f for f in ("serviceCode", "usageType", "operation", "source") if f not in line]
        if line.get("source") != UNKNOWN:
            missing += [band for band in BANDS if band not in line]
        if missing:
            raise ScriptError("ValidationException", f"lines[{i}] is missing {', '.join(missing)}")
        if line.get("source") != UNKNOWN:
            amounts = [line[band] for band in BANDS]
            if not all(
                isinstance(a, (int, float)) and not isinstance(a, bool) and math.isfinite(a)
                for a in amounts
            ):
                raise ScriptError(
                    "ValidationException", f"lines[{i}] low, mid and high must all be numbers"
                )
            if amounts[0] < 0 or not amounts[0] <= amounts[1] <= amounts[2]:
                raise ScriptError(
                    "ValidationException",
                    f"lines[{i}] amounts must satisfy 0 <= low <= mid <= high",
                )
        if "model" in line and not (isinstance(line["model"], str) and line["model"]):
            raise ScriptError("ValidationException", f"lines[{i}].model must be a model name")
        key = key_of(line)
        if key in seen:
            raise ScriptError("ValidationException", f"lines[{i}] repeats SCUTO {key}")
        seen.add(key)
        if not isinstance(line.get("assumption") or "", str):
            raise ScriptError("ValidationException", f"lines[{i}].assumption must be text")


def pricing_request(request):
    """The price_usage_lines request: every line that is not UNKNOWN, amounts [low, mid, high]."""
    return {
        "rateType": request["rateType"],
        "usage": [
            {
                "serviceCode": line["serviceCode"],
                "usageType": line["usageType"],
                "operation": line["operation"],
                "amounts": [line[band] for band in BANDS],
            }
            for line in request["lines"]
            if line["source"] != UNKNOWN
        ],
    }


def model_rates(session, line):
    """The OnDemand USD rate of each model the Price List lists on this line's SCUTO."""
    filters = [{"Type": "TERM_MATCH", "Field": "usagetype", "Value": line["usageType"]}]
    rates: dict[str, set] = {}
    client = session.client("pricing", region_name="us-east-1", config=pricing.APP_CONFIG)
    for page in client.get_paginator("get_products").paginate(
        ServiceCode=line["serviceCode"], Filters=filters
    ):
        for product in map(json.loads, page.get("PriceList", [])):
            attributes = product.get("product", {}).get("attributes", {})
            if attributes.get("operation", "") != line["operation"]:
                continue
            dimensions = [
                dimension
                for term in product.get("terms", {}).get("OnDemand", {}).values()
                for dimension in term.get("priceDimensions", {}).values()
            ]
            flat = len(dimensions) == 1 and dimensions[0].get("endRange") == "Inf"
            rate = Decimal(dimensions[0]["pricePerUnit"]["USD"]) if flat else None
            rates.setdefault(attributes.get("model", ""), set()).add(rate)
    return rates


def price_shared_models(request, session):
    """Price each model line whose SCUTO the Price List shares among models, or that shares its
    SCUTO with another line in the request, at that model's own rate. Returns (priced lines,
    footer entries); any other model line is in neither and goes to the pricing API as usual,
    which takes each SCUTO once."""
    priced, footer = [], []
    in_request = Counter(scuto_of(line) for line in request["lines"] if line["source"] != UNKNOWN)
    for line in request["lines"]:
        if line["source"] == UNKNOWN or not line.get("model"):
            continue
        try:
            rates = model_rates(session, line)
        except Exception:  # noqa: BLE001 - this line goes to the footer, the rest still price
            footer.append((key_of(line), NO_PRICE_LIST_REASON))
            continue
        if len(rates) <= 1 and in_request[scuto_of(line)] == 1:
            continue
        rate = rates.get(line["model"], set())
        if len(rate) != 1 or None in rate:
            footer.append((key_of(line), NO_MODEL_REASON))
            continue
        (rate,) = rate
        priced.append(
            {
                **{f: line[f] for f in ("serviceCode", "usageType", "operation", "model")},
                "amounts": {band: line[band] for band in BANDS},
                **{band: float(rate * Decimal(str(line[band]))) for band in BANDS},
                "pricedAt": LIST_RATE,
                "sharedScuto": True,
            }
        )
    return priced, footer


def join(request, response):
    """Split the request's lines into priced lines and footer entries.

    Every line ends up in exactly one of the two. A priced line carries its
    SCUTO, low, mid and high cost, and its usage amounts (for the $0-line note
    and the priced-lines file, never the report table); a footer entry carries
    the reason it has no cost.
    """
    costs = {scuto_of(item): item["estimatedCosts"] for item in response.get("lineItems", [])}
    errors = {
        scuto_of(err): err.get("errorMessage") or err.get("errorCode")
        for err in response.get("errors", [])
    }
    priced, footer = [], []
    for line in request["lines"]:
        # The calculator's results are keyed by SCUTO; the footer keeps the line's model too.
        scuto, key = scuto_of(line), key_of(line)
        if line["source"] == UNKNOWN:
            footer.append((key, UNKNOWN_REASON))
        elif scuto in costs and len(costs[scuto]) != len(BANDS):
            footer.append(
                (
                    key,
                    f"the pricing API returned {len(costs[scuto])} costs for "
                    f"{len(BANDS)} amounts",
                )
            )
        elif scuto in costs:
            priced.append(
                {
                    "serviceCode": line["serviceCode"],
                    "usageType": line["usageType"],
                    "operation": line["operation"],
                    **({"model": line["model"]} if line.get("model") else {}),
                    "amounts": {band: line[band] for band in BANDS},
                    **{band: float(cost) for band, cost in zip(BANDS, costs[scuto])},
                }
            )
        else:
            footer.append((key, errors.get(scuto) or MISSING_REASON))
    return priced, footer


def zero_cost(priced):
    """The priced lines whose expected usage is above zero but whose expected cost is $0, such as
    usage inside a free tier. The table sums them into their service silently, so each gets a
    note."""
    return [
        line
        for line in priced
        if isinstance(line["amounts"]["mid"], (int, float))
        and not isinstance(line["amounts"]["mid"], bool)
        and line["amounts"]["mid"] > 0
        and round(line["mid"], 2) == 0
    ]


def _product_free_range(product):
    """One Price List product's $0 range: the end of a $0 tier that starts at 0, inf when every
    tier is $0, 0.0 when there is no $0 tier, and None when it has no OnDemand tiers."""
    dimensions = [
        dimension
        for term in product.get("terms", {}).get("OnDemand", {}).values()
        for dimension in term.get("priceDimensions", {}).values()
    ]
    if not dimensions:
        return None
    usd = [float(d.get("pricePerUnit", {}).get("USD", 0) or 0) for d in dimensions]
    if not any(rate > 0 for rate in usd):
        return float("inf")
    free = [
        float(d.get("endRange", "0"))
        for d, rate in zip(dimensions, usd)
        if rate == 0 and str(d.get("beginRange", "0")) == "0"
    ]
    return max(free, default=0.0)


def free_range(session, line):
    """The amount the Price List prices at $0 for this line's SCUTO (see _product_free_range),
    or None when the Price List can't be read or its matching products disagree. Only products
    with the line's own operation count, so an empty operation matches only products that have
    none. A failed lookup never fails the report."""
    if session is None:
        return None
    filters = [
        {"Type": "TERM_MATCH", "Field": "usagetype", "Value": line["usageType"]},
    ]
    if line["operation"]:
        filters.append({"Type": "TERM_MATCH", "Field": "operation", "Value": line["operation"]})
    try:
        client = session.client("pricing", region_name="us-east-1", config=pricing.APP_CONFIG)
        products = client.get_products(
            ServiceCode=line["serviceCode"], Filters=filters, MaxResults=10
        ).get("PriceList", [])
    except Exception:  # noqa: BLE001 - any failure leaves the line as priced
        return None
    matching = [
        product
        for product in map(json.loads, products)
        if product.get("product", {}).get("attributes", {}).get("operation", "")
        == line["operation"]
    ]
    ranges = {_product_free_range(product) for product in matching}
    return ranges.pop() if len(ranges) == 1 else None


def check_zero_cost(request, priced, footer, session):
    """Sort the $0 lines with usage: (inside a free range, unchecked, priced again at list
    price). A line the Price List charges for is priced again at LIST_RATE under a discounted
    rate type; one that still prices at $0, or that was already at LIST_RATE, goes to the
    footer. `priced` and `footer` are updated in place."""
    free, unchecked, charged = [], [], []
    for line in zero_cost(priced):
        limit = free_range(session, line)
        if limit is None:
            unchecked.append(line)
        elif line["amounts"]["mid"] <= limit:
            free.append(line)
        else:
            charged.append(line)
    repriced = []
    if charged and request["rateType"] != LIST_RATE:
        lines = {scuto_of(line): line for line in charged}
        try:
            again = _price_at_list(charged, session)
        except Exception:  # noqa: BLE001 - the main pricing succeeded; these lines go to the footer
            again = {}
        for item in again.get("lineItems", []):
            line = lines.get(scuto_of(item))
            costs = item.get("estimatedCosts") or []
            if line and len(costs) == len(BANDS) and float(costs[1]) > 0:
                line.update({band: float(cost) for band, cost in zip(BANDS, costs)})
                line["pricedAt"] = LIST_RATE
                repriced.append(line)
    for line in charged:
        if line not in repriced:
            priced.remove(line)
            footer.append((key_of(line), ZERO_CHARGED_REASON))
    return free, unchecked, repriced


def _price_at_list(lines, session):
    """Price the given lines again at LIST_RATE, amounts [low, mid, high]."""
    return price(
        {
            "rateType": LIST_RATE,
            "usage": [
                {
                    **{f: line[f] for f in ("serviceCode", "usageType", "operation")},
                    "amounts": [line["amounts"][band] for band in BANDS],
                }
                for line in lines
            ],
        },
        session,
    )


def source_and_assumption(line):
    """A request line's source tag and assumption, as the priced-lines file records them."""
    return {"source": line["source"], "assumption": line.get("assumption") or ""}


def priced_lines(request, priced, footer):
    """The priced lines as data: each line's amounts, costs, source and assumption, and each line
    left out and why. The report shows only the cost per service, so this file is where a line's
    assumption, and whether its amount was stated or assumed, can be read."""
    by_key = {key_of(line): line for line in request["lines"]}
    return {
        "region": request["region"],
        "rateType": request["rateType"],
        "lines": [
            {
                **{f: line[f] for f in ("serviceCode", "usageType", "operation")},
                **({"model": line["model"]} if line.get("model") else {}),
                "amounts": line["amounts"],
                "costs": {band: line[band] for band in BANDS},
                **({"pricedAt": line["pricedAt"]} if line.get("pricedAt") else {}),
                **source_and_assumption(by_key[key_of(line)]),
            }
            for line in priced
        ],
        "notIncluded": [
            {
                **dict(zip(("serviceCode", "usageType", "operation", "model"), key)),
                "reason": str(reason),
                **source_and_assumption(by_key[key]),
            }
            for key, reason in footer
        ],
    }


def build_rows(priced):
    """One row per serviceCode, highest Mid first."""
    by_service: dict[str, list[dict]] = {}
    for line in priced:
        by_service.setdefault(line["serviceCode"], []).append(line)
    rows = []
    for service, lines in by_service.items():
        rows.append(
            {
                "service": service,
                **{band: sum(line[band] for line in lines) for band in BANDS},
            }
        )
    return sorted(rows, key=lambda row: (-row["mid"], row["service"]))


def format_usd(value):
    """A cost in dollars to the cent with thousands separators: 12345.678 -> $12,345.68."""
    return f"${value:,.2f}"


def share(part, total):
    """A row's share of the total Mid as a whole percent, "<1%" below 0.5%, "-" for a $0 total."""
    if total <= 0:
        return "-"
    if part <= 0:
        return "0%"
    pct = Decimal(repr(part / total * 100))
    if pct < Decimal("0.5"):
        return "<1%"
    return f"{pct.quantize(Decimal(1), rounding=ROUND_HALF_UP)}%"


def cell(text):
    """Keep a value inside one markdown table cell."""
    return " ".join(str(text).split()).replace("|", "\\|")


def summary_line(totals):
    """The report's first sentence: the Mid total, and the Low-High range when they differ."""
    if totals["low"] == totals["high"]:
        return f"The estimated bill is about {format_usd(totals['mid'])}/month."
    return (
        f"The most likely bill is about {format_usd(totals['mid'])}/month, with a plausible "
        f"range of {format_usd(totals['low'])} - {format_usd(totals['high'])}."
    )


def top_drivers(rows, totals):
    """The services that cost most, at Mid, before the table: up to MAX_DRIVERS of `rows`, which
    are already highest Mid first. Left out for a single service, which the summary line already
    covers, and for a $0 estimate, which has nothing to rank."""
    if len(rows) < 2 or totals["mid"] <= 0:
        return []
    out = ["Top cost drivers:"]
    for n, row in enumerate(rows[:MAX_DRIVERS], 1):
        out.append(
            f"{n}. {row['service']}: {format_usd(row['mid'])} ({share(row['mid'], totals['mid'])})"
        )
    return out + [""]


def scuto_label(key):
    """A line's label, such as AmazonS3 / Requests, with the model last on a model line."""
    return " / ".join(part for part in key if part)


def render(request, priced, footer, zero=None):
    """`zero` is check_zero_cost's (free, unchecked, repriced); without it, every $0 line with
    usage is treated as unchecked."""
    out = []
    if priced:
        rows = build_rows(priced)
        totals = {band: sum(line[band] for line in priced) for band in BANDS}
        rate = RATE_TYPE_LABELS.get(request["rateType"], request["rateType"])
        out += [summary_line(totals), ""]
        out += top_drivers(rows, totals)
        out += [
            f"Monthly cost estimate ({rate}, {region_label(request['region'])})",
            "",
            "| Service | Low | Mid | High | % of total |",
            "|---|---|---|---|---|",
        ]
        for row in rows:
            out.append(
                f"| {cell(row['service'])} | {format_usd(row['low'])} | {format_usd(row['mid'])} | "
                f"{format_usd(row['high'])} | {share(row['mid'], totals['mid'])} |"
            )
        total_share = "100%" if totals["mid"] > 0 else "-"
        out.append(
            f"| **Total** | **{format_usd(totals['low'])}** | **{format_usd(totals['mid'])}** | "
            f"**{format_usd(totals['high'])}** | **{total_share}** |"
        )
        free, unchecked, repriced = zero or ([], zero_cost(priced), [])
        if free or unchecked:
            out += ["", "Priced at $0 despite usage:"]
            out += [f"- {scuto_label(key_of(line))}: {ZERO_COST_REASON}" for line in free]
            out += [f"- {scuto_label(key_of(line))}: {ZERO_UNCHECKED_REASON}" for line in unchecked]
        if repriced:
            out += [
                "",
                f"Priced at {RATE_TYPE_LABELS[LIST_RATE]}: at {rate} the pricing API returned $0 "
                "for usage the Price List charges for, so no discount is applied to these lines:",
            ]
            out += [f"- {scuto_label(key_of(line))}" for line in repriced]
        shared = [line for line in priced if line.get("sharedScuto")]
        if shared:
            out += ["", f"Priced at {RATE_TYPE_LABELS[LIST_RATE]}: {SHARED_NOTE}:"]
            out += [f"- {scuto_label(key_of(line))}" for line in shared]
    else:
        out.append(NOTHING_PRICED)
    if footer:
        out += ["", "Not included in the total:"]
        out += [
            f"- {scuto_label(scuto)}: {' '.join(str(reason).split())}" for scuto, reason in footer
        ]
    return "\n".join(out) + "\n"


def price(price_request, session):
    """Price the request in calls of at most pricing.MAX_LINES lines and merge the results.

    The line limit belongs to the pricing API's contract, so a larger workload is
    split here rather than rejected. A request-level failure in any call fails the
    whole run.
    """
    usage = price_request["usage"]
    merged: dict[str, list] = {"lineItems": [], "errors": []}
    for start in range(0, len(usage), pricing.MAX_LINES):
        part = pricing.run(
            {
                "rateType": price_request["rateType"],
                "usage": usage[start : start + pricing.MAX_LINES],
            },
            session,
        )
        merged["lineItems"] += part.get("lineItems", [])
        merged["errors"] += part.get("errors", [])
    return merged


def is_compute(line):
    if line["serviceCode"] in COMPUTE_SERVICES:
        return True
    return line["serviceCode"] == "AmazonEC2" and any(
        name in line["usageType"] for name in EC2_COMPUTE
    )


def is_log_line(line, names):
    return line["serviceCode"] == "AmazonCloudWatch" and any(
        name in line["usageType"] for name in names
    )


def check_assumed_logs(request, priced):
    """Refuse an estimate whose assumed log volume costs more than LOG_COMPUTE_RATIO times the
    compute that writes the logs, before it is shown.

    A per-request log size times a large request count can make logs most of an estimate, far
    above what the service logs. Applies only when every log ingestion line is ASSUMED (a volume
    the user gave, or worked out from what they gave, is never checked), the estimate has a
    compute line, and the logs are at least LOG_MIN_SHARE of the estimate. Mid costs are
    compared; an ASSUMED stored-log line counts with ingestion, one the user gave never does.
    """
    sources = {scuto_of(line): line["source"] for line in request["lines"]}
    ingestion = [line for line in priced if is_log_line(line, LOG_INGESTION)]
    if not ingestion or any(sources.get(scuto_of(line)) != "ASSUMED" for line in ingestion):
        return
    compute = sum(line["mid"] for line in priced if is_compute(line))
    stored = [
        line
        for line in priced
        if is_log_line(line, LOG_STORAGE) and sources.get(scuto_of(line)) == "ASSUMED"
    ]
    logs = ingestion + stored
    log_cost = sum(line["mid"] for line in logs)
    total = sum(line["mid"] for line in priced)
    if compute <= 0 or log_cost <= LOG_COMPUTE_RATIO * compute or log_cost < LOG_MIN_SHARE * total:
        return
    names = ", ".join(scuto_label(key_of(line)) for line in logs)
    raise ScriptError(
        "AssumedLogVolumeTooHigh",
        f"cost-estimate-request.json: the assumed log volume ({names}) costs more than "
        f"{LOG_COMPUTE_RATIO:g} times the compute that writes the logs, which few services log. "
        "Re-check the assumed log size per request or event, how many requests are logged "
        "(services at high traffic often sample or log only errors) and, for stored log data, "
        "the retention and age of the store; lower the amounts, say why in the assumption, and "
        "run again. If the user gave a log volume, even as a range, size the line from it and "
        "tag it CUSTOMER_STATED or DERIVED instead.",
    )


def run(request, session, priced_out=None):
    """The report. With `priced_out`, the priced lines are also written there as JSON, and the
    request and priced lines are saved next to it under a timestamp (see save_copies), which the
    report's last line names."""
    validate(request)
    shared, shared_footer = price_shared_models(request, session)
    skip = {key_of(line) for line in shared} | {key for key, _reason in shared_footer}
    rest = {**request, "lines": [line for line in request["lines"] if key_of(line) not in skip]}
    usage = pricing_request(rest)
    response = price(usage, session) if usage["usage"] else {}
    priced, footer = join(rest, response)
    zero = check_zero_cost(request, priced, footer, session)
    priced += shared
    footer += shared_footer
    # After every line is priced, so the estimate's total includes the model lines priced apart.
    check_assumed_logs(request, priced)
    report = render(request, priced, footer, zero)
    # Only after the report renders, so a failed run leaves no priced lines behind.
    if priced_out:
        payload = priced_lines(request, priced, footer)
        try:
            with open(priced_out, "w") as f:
                json.dump(payload, f, indent=2)
        except OSError as exc:
            # The report is still right; only the checking tools lose their copy.
            print(f"could not write {priced_out}: {exc}", file=sys.stderr)
        names = save_copies(os.path.dirname(priced_out) or ".", request, payload)
        if names:
            report += (
                f"\nSaved this estimate as {names[0]} and {names[1]}.\n"
                f"Each line's usage, cost and assumption is in {names[1]}.\n"
            )
    return report


def save_copies(directory, request, payload, now=None):
    """Keep this estimate: its request and priced lines under one new timestamp.

    The working files are replaced on every run, so a follow-up would otherwise lose the earlier
    estimate. An existing file is never replaced. Returns the two file names, or None when they
    could not be written; the report is still right then.
    """
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    names = [f"{prefix}-{stamp}.json" for prefix in COPY_PREFIXES]
    try:
        for name, content in zip(names, (request, payload)):
            # "x": fail rather than replace an earlier copy.
            with open(os.path.join(directory, name), "x") as f:
                json.dump(content, f, indent=2)
    except OSError as exc:
        print(f"could not save a copy of this estimate: {exc}", file=sys.stderr)
        return None
    return names


def main(argv=None):
    # Credentials come from boto3's default chain (env vars, AWS_PROFILE, role).
    argparse.ArgumentParser(
        description="Price usage lines and render the cost report (request JSON on stdin)."
    ).parse_args(argv)
    try:
        request = json.load(sys.stdin)
        report = run(request, boto3.session.Session(), priced_out=PRICED_FILE)
    except json.JSONDecodeError as exc:
        return fail("ValidationException", f"stdin is not valid JSON: {exc}")
    except ScriptError as exc:
        return fail(exc.code, exc.message)
    except Exception as exc:  # keep the JSON error contract for anything unexpected
        traceback.print_exc()  # stderr, for debugging; stdout remains JSON
        return fail(
            "UnexpectedError",
            f"the report script failed unexpectedly ({type(exc).__name__}: {exc})",
        )
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
