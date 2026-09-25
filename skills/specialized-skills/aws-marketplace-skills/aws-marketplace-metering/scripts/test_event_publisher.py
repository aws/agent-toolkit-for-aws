"""Test event publisher — NON-PRODUCTION / dry-run stages ONLY.

Generates EventBridge events whose ``detail`` shape EXACTLY matches AWS Marketplace subscription
events (the detail-types the subscription Lambda consumes) with RANDOMIZED but VALID field
values, so a seller can exercise the full metering integration in a sandbox stage without any
real Marketplace subscription. It is a TEST SIMULATOR: the events it emits are NOT real
subscriptions and confer NO entitlements — they only drive the seller's own non-prod pipeline.

Events are emitted under a STAGE-SCOPED source (``<stageName>.agreement-marketplace``), NEVER the
reserved AWS service source ``aws.agreement-marketplace``: (1) EventBridge reserves the ``aws.``
source prefix for real AWS-service events, so a custom PutEvents with an ``aws.`` source is not
reliably delivered to rules; (2) a stage-scoped source is DISJOINT from the real production
source, so a same-account non-prod stage's test events can never be matched (double-written) by
the production rule. An ``aws.*`` source is REJECTED (no default).

Guardrails (must be enforced by the deploying stack / caller):
  * Deploy ONLY in a stage whose MeteringMode is ``dry-run`` (the submitter then never calls the
    real BatchMeterUsage). NEVER deploy this in a ``live`` stage.
  * ``acceptor.accountId`` is drawn ONLY from the seller-declared TEST_ACCOUNT_ALLOWLIST — never
    a real/production buyer account.
  * The event source is stage-scoped (never ``aws.*``); the productCode is supplied PER INVOCATION
    (payload ``productCode``) so the SHARED events stack carries no per-product value.
  * Publish to the same account/region as the non-prod events stack so its EventBridge rule
    (scoped to the stage source + test accounts) picks the events up.

Scenarios (``--scenario`` / event ``scenario`` field): new, deprovision, agreement-ended,
agreement-amended, multi-region, multi-dimension, burst, malformed, month-boundary, duplicate.
"""

import argparse
import json
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# The reserved AWS service source — the test publisher must NOT emit under this (see module
# docstring); it is referenced only to REJECT it. There is deliberately no default source.
RESERVED_SOURCE_PREFIX = "aws."

# Detail-types the subscription Lambda consumes (must match production exactly).
DETAIL_TYPES = {
    "new": "License Updated",
    "deprovision": "License Deprovisioned",
    "agreement-ended": "Purchase Agreement Ended",
    "agreement-amended": "Purchase Agreement Amended",
}

SCENARIOS = [
    "new",
    "deprovision",
    "agreement-ended",
    "agreement-amended",
    "multi-region",
    "multi-dimension",
    "burst",
    "malformed",
    "month-boundary",
    "duplicate",
]

# A small pool of well-formed sample regions/dimensions for randomized-but-valid values.
_SAMPLE_REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-2"]
_SAMPLE_DIMENSIONS = ["Requests", "GBHours", "Users", "DataProcessedGB"]


def _rand_account_id():
    """A syntactically valid 12-digit AWS account id (for shape only)."""
    return "".join(random.choices(string.digits, k=12))


def _rand_license_arn(account_id):
    return f"arn:aws:license-manager::{account_id}:license:l-{uuid.uuid4().hex[:16]}"


def _rand_agreement_id():
    return "agmt-" + uuid.uuid4().hex[:20]


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_event_source(event_source):
    """A stage-scoped event source is REQUIRED — there is no default, and an ``aws.*`` source is
    rejected (a custom PutEvents cannot reliably deliver the reserved AWS-service prefix, and it
    would collide with the real production source)."""
    if not event_source:
        raise ValueError("event_source is required (a stage-scoped '<stageName>.agreement-marketplace'); "
                         "there is no default")
    if event_source.startswith(RESERVED_SOURCE_PREFIX):
        raise ValueError(f"event_source '{event_source}' uses the reserved 'aws.' prefix — use a "
                         "stage-scoped '<stageName>.agreement-marketplace' instead")
    return event_source


def build_event(scenario, test_accounts, product_code, now=None, event_source=None):
    """Build ONE EventBridge event dict in AWS Marketplace shape for the given scenario.

    ``test_accounts`` is the REQUIRED non-empty allowlist of test buyer account ids — the
    acceptor is chosen only from it (test accounts only). ``event_source`` is REQUIRED and must be
    a stage-scoped source (never the reserved ``aws.`` prefix); the detail shape matches
    production. Returns the event dict (not yet published).
    """
    if not test_accounts:
        raise ValueError("test_accounts (TestAccountAllowlist) must be non-empty — non-prod "
                         "test events may use test accounts ONLY")
    event_source = _require_event_source(event_source)
    now = now or datetime.now(timezone.utc)
    account_id = random.choice(test_accounts)
    license_arn = _rand_license_arn(account_id)
    agreement_id = _rand_agreement_id()

    # Base detail shared by the lifecycle events.
    detail = {
        "acceptor": {"accountId": account_id},
        "license": {"arn": license_arn},
        "agreement": {"id": agreement_id, "endTime": _iso(now + timedelta(days=365))},
        "product": {"code": product_code},
    }

    # Map compound scenarios onto a concrete detail-type. These use a License Updated envelope;
    # 'malformed' then corrupts it below, the others vary the USAGE-row side.
    detail_type_key = scenario
    if scenario in ("multi-region", "multi-dimension", "burst", "duplicate", "month-boundary", "malformed"):
        detail_type_key = "new"

    detail_type = DETAIL_TYPES.get(detail_type_key, "License Updated")

    if scenario == "deprovision":
        # Deprovision opens the ~1h flush window; the subscription Lambda derives expiry from time.
        detail["entitlement"] = {"status": "deprovisioning"}
    elif detail_type == "License Updated":
        detail["entitlement"] = {"status": "active", "dimension": random.choice(_SAMPLE_DIMENSIONS)}

    if scenario == "malformed":
        # Emit a GENUINELY malformed License Updated event so the non-prod subscription Lambda's
        # bad-input handling is exercised (it should reject/skip and DLQ, not crash): drop the
        # REQUIRED license.arn entirely and corrupt acceptor.accountId to a non-12-digit value.
        detail["license"].pop("arn", None)
        detail["acceptor"]["accountId"] = "not-an-account-id"

    event = {
        "Source": event_source,
        "DetailType": detail_type,
        "Detail": json.dumps(detail),
        # Non-standard helper fields the seeder/consumer may read for the usage-row side; they
        # do NOT appear in real Marketplace events and are ignored by the subscription Lambda.
        "scenario": scenario,
        "time": _iso(now),
    }
    return event


def build_batch(scenario, test_accounts, product_code, count=1, now=None, event_source=None):
    """Build N events for a scenario. ``burst`` implies many; ``duplicate`` repeats one event."""
    now = now or datetime.now(timezone.utc)
    if scenario == "burst" and count == 1:
        count = 50
    events = [build_event(scenario, test_accounts, product_code, now, event_source) for _ in range(count)]
    if scenario == "duplicate" and events:
        # Emit the SAME event twice to exercise idempotency/first-write-wins downstream.
        events.append(json.loads(json.dumps(events[0])))
    return events


def _publish(events, event_bus_name=None, region=None):
    import boto3

    client = boto3.client("events", region_name=region) if region else boto3.client("events")
    sent = 0
    for i in range(0, len(events), 10):  # PutEvents max 10 entries/call
        chunk = events[i:i + 10]
        entries = []
        for e in chunk:
            entry = {"Source": e["Source"], "DetailType": e["DetailType"], "Detail": e["Detail"]}
            if event_bus_name:
                entry["EventBusName"] = event_bus_name
            entries.append(entry)
        resp = client.put_events(Entries=entries)
        failed = resp.get("FailedEntryCount", 0)
        if failed:
            raise RuntimeError(f"PutEvents reported {failed} failed entr(ies): {resp}")
        sent += len(entries)
    return sent


def handler(event, context):
    """Lambda entrypoint: generate + publish per the invocation payload.

    Invocation payload (the JSON you pass when invoking the Lambda), e.g.::

        {"scenario": "new", "count": 3, "productCode": "abcd1234efgh5678"}

    - ``productCode`` (REQUIRED) — the AWS Marketplace product code to stamp on the simulated
      events' ``detail.product.code``. It is supplied PER INVOCATION (NOT a stack parameter or an
      environment variable) on purpose: the events stack is SHARED by every product in the stage,
      so a single deployed publisher can simulate ANY product just by passing a different
      ``productCode`` per invocation — and there is no shared per-product value that a second
      product's deploy could overwrite. How callers pass it:
        * AWS CLI:  aws lambda invoke --function-name awsmp-events-<stage>-test-event-publisher \\
                      --payload '{"scenario":"new","productCode":"<code>"}' out.json
        * Console:  Lambda > Test > event JSON ``{"scenario":"new","productCode":"<code>"}``
        * The generated test plan / seeder passes the product under test.
      There is NO default and NO env fallback — a missing productCode raises (fail fast) rather
      than silently stamping the wrong/empty product.
    - ``scenario`` (default ``new``) and ``count`` (default 1) select the scenario + how many events.

    TEST_ACCOUNT_ALLOWLIST, EVENT_SOURCE, and EVENT_BUS_NAME come from the environment (set by the
    stack only in a dry-run stage).
    """
    if os.environ.get("METERING_MODE", "").strip().lower() != "dry-run":
        raise RuntimeError("test_event_publisher may run ONLY in a dry-run (non-prod) stage")
    test_accounts = [a.strip() for a in os.environ.get("TEST_ACCOUNT_ALLOWLIST", "").split(",") if a.strip()]
    # productCode is PER INVOCATION (payload) — never a stack param/env. This lets ONE shared
    # publisher simulate any product in the stage with no shared per-product value to overwrite.
    product_code = (event or {}).get("productCode")
    if not product_code:
        raise RuntimeError(
            "productCode is required in the invocation payload, e.g. "
            "{\"scenario\": \"new\", \"productCode\": \"<awsMarketplaceProductCode>\"}"
        )
    # Stage-scoped source (e.g. "beta.agreement-marketplace"); required, never the reserved "aws." prefix.
    event_source = _require_event_source(os.environ.get("EVENT_SOURCE", "").strip())
    scenario = (event or {}).get("scenario", "new")
    count = int((event or {}).get("count", 1))
    events = build_batch(scenario, test_accounts, product_code, count, event_source=event_source)
    sent = _publish(events, event_bus_name=os.environ.get("EVENT_BUS_NAME") or None)
    return {"scenario": scenario, "productCode": product_code, "published": sent}


def main():
    p = argparse.ArgumentParser(description="Publish AWS-Marketplace-shape TEST events (non-prod only)")
    p.add_argument("--scenario", choices=SCENARIOS, default="new")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--product-code", required=True)
    p.add_argument("--test-accounts", required=True,
                   help="Comma-separated test buyer account ids (allowlist)")
    p.add_argument("--region")
    p.add_argument("--event-bus-name")
    p.add_argument("--event-source", required=True,
                   help="Event Source — REQUIRED, a stage-scoped '<stageName>.agreement-marketplace' "
                        "(the reserved 'aws.' prefix is rejected)")
    p.add_argument("--dry-print", action="store_true",
                   help="Print the generated events instead of publishing")
    args = p.parse_args()
    try:
        _require_event_source(args.event_source)
    except ValueError as e:
        p.error(str(e))
    accounts = [a.strip() for a in args.test_accounts.split(",") if a.strip()]
    events = build_batch(args.scenario, accounts, args.product_code, args.count,
                         event_source=args.event_source)
    if args.dry_print:
        print(json.dumps(events, indent=2))
        return
    sent = _publish(events, event_bus_name=args.event_bus_name, region=args.region)
    print(f"Published {sent} '{args.scenario}' test event(s).")


if __name__ == "__main__":
    main()
