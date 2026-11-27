#!/usr/bin/env python3
"""Price SCUTO usage lines with the BCM Pricing Calculator GetUsageLinesEstimatedCost API.

Input (JSON on stdin): a rateType and up to MAX_LINES usage lines, each a SCUTO
(operation may be "") with 1 to MAX_AMOUNTS amounts.

  {"rateType": "BEFORE_DISCOUNTS",
   "usage": [
     {"serviceCode": "AmazonS3", "usageType": "TimedStorage-ByteHrs", "operation": "",
      "amounts": [100, 500, 2000]},
     {"serviceCode": "AmazonS3", "usageType": "FakeUsage-Nope", "operation": "",
      "amounts": [1, 2, 3]}]}

Output (JSON on stdout, exit 0): every input line comes back exactly once, in
lineItems with one cost per amount in the same order, or in errors. Response
order is not meaningful.

  {"costCurrency": "USD",
   "rateType": "BEFORE_DISCOUNTS",
   "lineItems": [
     {"serviceCode": "AmazonS3", "usageType": "TimedStorage-ByteHrs", "operation": "",
      "estimatedCosts": [2.3, 11.5, 46.0]}],
   "errors": [
     {"serviceCode": "AmazonS3", "usageType": "FakeUsage-Nope", "operation": "",
      "errorCode": "BAD_REQUEST", "errorMessage": "No matching usage found ..."}]}

On a request-level failure (exit 1), stdout holds the error:

  {"error": {"code": "ValidationException",
             "message": "Invalid rate type for a member account. ..."}}

Pricing uses GetUsageLinesEstimatedCost through the boto3 bcm-pricing-calculator
client, so it needs a boto3 recent enough to include that operation.

Usage:
  python3 scripts/price_usage_lines.py < request.json
"""

import argparse
import json
import sys
import traceback

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from errors import ScriptError, fail

SERVICE = "bcm-pricing-calculator"
ENDPOINT_REGION = "us-east-1"
MAX_LINES = 1000
MAX_AMOUNTS = 5
API_MAX_LINES = 500  # GetUsageLinesEstimatedCost limit per call
MAX_ATTEMPTS = 5
TIMEOUT_SECS = 60
# Added to the User-Agent of every AWS API call the skill's scripts make, as `app/<APP_ID>`, so the
# Pricing Calculator and Price List APIs can count the calls this skill makes.
APP_ID = "AWSSkill-CostEstimation"
APP_CONFIG = Config(user_agent_appid=APP_ID)
RETRY_CONFIG = APP_CONFIG.merge(
    Config(
        retries={"max_attempts": MAX_ATTEMPTS, "mode": "standard"},
        connect_timeout=TIMEOUT_SECS,
        read_timeout=TIMEOUT_SECS,
    )
)
CURRENCY = "USD"
UNPRICED = "UNPRICED"


def validate(request):
    """Checks what the script needs before it can split lines into API entries.

    Enforces the script's own size limits, stops a missing field from crashing
    build_entries, and rejects a repeated SCUTO, which would make results
    impossible to match back to lines. Types and values are left to the API,
    whose errors are passed through.
    """
    if not isinstance(request, dict) or "rateType" not in request:
        raise ScriptError("ValidationException", "request must be an object with a rateType")
    usage = request.get("usage")
    if not isinstance(usage, list) or not 1 <= len(usage) <= MAX_LINES:
        raise ScriptError("ValidationException", f"usage must hold 1-{MAX_LINES} lines")
    seen = set()
    for i, line in enumerate(usage):
        if not isinstance(line, dict):
            raise ScriptError("ValidationException", f"usage[{i}] must be an object")
        missing = [f for f in ("serviceCode", "usageType", "operation", "amounts") if f not in line]
        if missing:
            raise ScriptError("ValidationException", f"usage[{i}] is missing {', '.join(missing)}")
        if not isinstance(line["amounts"], list) or not 1 <= len(line["amounts"]) <= MAX_AMOUNTS:
            raise ScriptError(
                "ValidationException", f"usage[{i}].amounts must hold 1-{MAX_AMOUNTS} numbers"
            )
        scuto = (line["serviceCode"], line["usageType"], line["operation"])
        if scuto in seen:
            raise ScriptError("ValidationException", f"usage[{i}] repeats SCUTO {scuto}")
        seen.add(scuto)


class Client:
    """Sends GetUsageLinesEstimatedCost calls with the session's credentials.

    Every (line, amount) pair is one entry; up to API_MAX_LINES entries go in a call.
    """

    def __init__(self, session):
        try:
            self.client = session.client(SERVICE, region_name=ENDPOINT_REGION, config=RETRY_CONFIG)
        except BotoCoreError as exc:
            raise ScriptError("UnsupportedBoto3", f"{exc}; upgrade boto3") from exc
        if not hasattr(self.client, "get_usage_lines_estimated_cost"):
            raise ScriptError(
                "UnsupportedBoto3",
                f"boto3 {boto3.__version__} has no GetUsageLinesEstimatedCost; upgrade boto3",
            )

    def price(self, request):
        entries, slots = build_entries(request["usage"])
        batches = [entries[s : s + API_MAX_LINES] for s in range(0, len(entries), API_MAX_LINES)]
        rate_type = request["rateType"]
        results = {}
        # One call at a time, since the API has a low burst rate.
        # If any call fails, the whole request fails and nothing partial is returned.
        for batch in batches:
            results.update(self._send(rate_type, batch))
        return assemble(request, slots, results)

    def _send(self, rate_type, batch):
        """Return key -> {"cost": float} or {"errorCode", "errorMessage"}."""
        out = self._call({"rateType": rate_type, "usage": batch})
        results: dict[str, dict] = {}
        for item in out.get("lineItems") or []:
            cost = (item.get("estimatedCost") or {}).get("cost")
            if cost is not None:
                results[item["key"]] = {"cost": float(cost)}
            else:
                results[item["key"]] = {
                    "errorCode": UNPRICED,
                    "errorMessage": "returned by the pricing API without a cost",
                }
        for err in out.get("errors") or []:
            results[err["key"]] = {
                "errorCode": err.get("errorCode"),
                "errorMessage": err.get("errorMessage"),
            }
        return results

    def _call(self, payload):
        try:
            return self.client.get_usage_lines_estimated_cost(**payload)
        except ClientError as exc:
            error = exc.response.get("Error", {})
            raise ScriptError(error.get("Code", "Unknown"), error.get("Message", "")) from exc
        except BotoCoreError as exc:
            raise ScriptError(type(exc).__name__, str(exc)) from exc


def build_entries(usage):
    """One entry per (line, amount). slots maps each key to (line index, amount index)."""
    entries: list[dict] = []
    slots: dict[str, tuple[int, int]] = {}
    for i, line in enumerate(usage):
        for j, amount in enumerate(line["amounts"]):
            key = f"L{len(entries)}"  # <= 5 chars (L4999); API allows 10 of [a-zA-Z0-9]
            slots[key] = (i, j)
            entries.append(
                {
                    "key": key,
                    "serviceCode": line["serviceCode"],
                    "usageType": line["usageType"],
                    "operation": line["operation"],
                    "amount": amount,
                }
            )
    return entries, slots


def assemble(request, slots, results):
    """Fold per-entry results into exactly one lineItem or one error per input line.

    A line with any failed amount goes to errors with its first failed entry's
    error, unchanged. An entry missing from the response is reported as UNPRICED.
    """
    usage = request["usage"]
    costs = [[None] * len(line["amounts"]) for line in usage]
    line_error: dict[int, dict] = {}
    for key, (i, j) in sorted(slots.items(), key=lambda kv: kv[1]):
        result = results.get(key)
        if result is None:
            result = {
                "errorCode": UNPRICED,
                "errorMessage": "missing from the pricing API response (neither priced nor rejected)",
            }
        if "cost" in result:
            costs[i][j] = result["cost"]
        else:
            line_error.setdefault(i, result)

    line_items, errors = [], []
    for i, line in enumerate(usage):
        scuto = {k: line[k] for k in ("serviceCode", "usageType", "operation")}
        if i in line_error:
            errors.append({**scuto, **line_error[i]})
        else:
            line_items.append({**scuto, "estimatedCosts": costs[i]})
    return {
        "costCurrency": CURRENCY,
        "rateType": request["rateType"],
        "lineItems": line_items,
        "errors": errors,
    }


def run(request, session):
    validate(request)
    return Client(session).price(request)


def main(argv=None):
    # Credentials come from boto3's default chain (env vars, AWS_PROFILE, role).
    argparse.ArgumentParser(
        description="Price SCUTO usage lines (request JSON on stdin)."
    ).parse_args(argv)
    try:
        request = json.load(sys.stdin)
        result = run(request, boto3.session.Session())
    except json.JSONDecodeError as exc:
        return fail("ValidationException", f"stdin is not valid JSON: {exc}")
    except ScriptError as exc:
        return fail(exc.code, exc.message)
    except Exception as exc:  # keep the JSON error contract for anything unexpected
        traceback.print_exc()  # stderr, for debugging; stdout remains JSON
        return fail(
            "UnexpectedError",
            f"the pricing script failed unexpectedly ({type(exc).__name__}: {exc})",
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
