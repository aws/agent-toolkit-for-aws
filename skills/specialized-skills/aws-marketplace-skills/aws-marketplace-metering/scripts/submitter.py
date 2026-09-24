"""Submitter Lambda.

EventBridge-scheduled with ReservedConcurrentExecutions=1 (a single serial submitter — the
safe Option A posture vs. the BatchMeterUsage request-rate limit). It:

  1. Reads pending aggregated records from aggregated_usage via its metering_pending GSI
     (each record is ONE already-aggregated (licenseArn, account, dimension, hour) unit).
  2. Coalesces up to 25 UsageRecords per BatchMeterUsage call, split into Concurrent
     Agreements (LicenseArn) and legacy (ProductCode) batches; retries UnprocessedRecords
     once; isolates a request-level poison record by bisecting.
  3. Writes MeteringRecordId + meteringStatus (+ reason) and REMOVEs meteringPending ON THE
     aggregated_usage record (NOT the raw usage table).
  4. Submits any 'deprovisioning' license's records FIRST (deprovisioning-first ordering) so its
     final usage is flushed within the ~1h window. It does NOT finalize the subscriber — flipping
     subscriptionStatus to 'inactive' is done by the separate events-stack deprovision-cleanup
     Lambda once the deprovisioningExpiry window has elapsed (see the handler note below and
     scripts/deprovision_cleanup.py), because a license may span multiple hours/regions and no
     single submitter run can know it is fully drained.

Idempotency: BatchMeterUsage is first-write-wins deduped per
(CustomerAWSAccountId + LicenseArn + dimension + hour) per region, so a re-submitted
identical record is not double-billed. A record whose write-back was lost keeps
meteringPending and is re-submitted next run (deduped).
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from handlers import metering_core as core

logger = core.logger

# Max aggregated records to drain per invocation. reserved=1 is a single serial submitter;
# at 25 records/BatchMeterUsage call and the ~10 TPS API limit this is ~3000 calls, well
# within a 5-minute run — so the cap is API-feasible, not an artificial low ceiling.
MAX_RECORDS_PER_RUN = int(os.environ.get("MAX_RECORDS_PER_RUN", "50000"))

# Optional TTL (days) for finalized aggregated_usage rows (TTL config). 0 = disabled
# (default): the table has no TTL spec, so we never set `ttl`. When >0, set `ttl` ONLY on
# terminal Success rows so pending/failed rows are never auto-expired.
AGGREGATED_USAGE_TTL_DAYS = int(os.environ.get("AGGREGATED_USAGE_TTL_DAYS", "0"))

# MeteringMode decides prod (live) vs non-prod (dry-run). In dry-run the submitter runs the
# ENTIRE pipeline — read, build batches, deprovisioning-first ordering — but NEVER calls
# BatchMeterUsage/MeterUsage: it logs + EMF-emits the record(s) it WOULD have sent and writes
# meteringStatus=DryRunSubmitted. This lets a non-prod stage exercise everything without ever
# billing a real buyer. `live` is the only mode that calls the real API.
METERING_MODE = os.environ.get("METERING_MODE", "live").strip().lower()
DRY_RUN = METERING_MODE == "dry-run"
STATUS_DRY_RUN = "DryRunSubmitted"


def _dry_run_submit(batch, keys, outcomes, use_product_code=False):
    """Dry-run stand-in for core.submit_records: NEVER calls BatchMeterUsage. Records the
    would-be submission as DryRunSubmitted (masked) and emits a metric. Returns False
    (nothing is ever 'unprocessed' in dry-run)."""
    for i, rec in enumerate(batch):
        gk = keys[i]
        outcomes[gk] = {"MeteringRecordId": None, "Status": STATUS_DRY_RUN}
        logger.info(
            "DRY-RUN (MeteringMode=dry-run) — would submit UsageRecord: "
            f"license={core.mask(rec.get('LicenseArn', ''))} "
            f"account={core.mask(rec.get('CustomerAWSAccountId', ''))} "
            f"dimension={rec.get('Dimension', '')} quantity={rec.get('Quantity')} "
            f"(use_product_code={use_product_code}); NOT calling BatchMeterUsage"
        )
    core.emf_metric("DryRunSubmitted", len(batch))
    return False


def handler(event, context):
    if core.aggregated_usage_table is None:
        raise RuntimeError("AGGREGATED_USAGE_TABLE not configured")

    now = datetime.now(timezone.utc)

    # Deprovisioning-first: read the deprovisioning set's pending records SEPARATELY and submit
    # them AHEAD of the ordinary backlog, so a closing-window license is not delayed behind a
    # large oldest-first backlog (and is not lost to the MAX_RECORDS_PER_RUN cap on the regular
    # read). Best-effort: if the deprovisioning-index lookup fails (throttle/transient/misconfig)
    # we log and proceed with the ordinary pass only — a prioritization lookup failure must NOT
    # block ordinary metering submission.
    try:
        deprovisioning = core.deprovisioning_licenses()
    except Exception:
        logger.warning(
            "deprovisioning_licenses() lookup failed; submitting ordinary backlog only "
            "(deprovisioning records still submit via the regular pass)",
            exc_info=True,
        )
        deprovisioning = set()

    pending: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if deprovisioning:
        pending.update(_read_deprovisioning_pending(now, deprovisioning))
    # Regular oldest-first pass fills the remainder up to the cap (skips keys already read).
    _read_pending_aggregated(now, into=pending)
    if not pending:
        logger.info("No pending aggregated usage to submit")
        return {"submitted": 0}

    ca_batches, legacy_batches = _build_batches(pending, deprovisioning)

    outcomes: Dict[Any, Dict[str, Any]] = {}
    unprocessed_remaining = False
    _submit = _dry_run_submit if DRY_RUN else core.submit_records
    for batch, keys in ca_batches:
        unprocessed_remaining |= _submit(batch, keys, outcomes, use_product_code=False)
    for batch, keys in legacy_batches:
        unprocessed_remaining |= _submit(batch, keys, outcomes, use_product_code=True)

    for agg_key, outcome in outcomes.items():
        _write_back(pending[agg_key], outcome)

    # NOTE: the submitter does NOT flip subscriptionStatus to inactive. A deprovisioning
    # license may have usage across multiple hours AND multiple regions (one submitter per
    # region, one shared subscribers table), so no single submitter run can know the license
    # is fully drained. Finalization (deprovisioning -> inactive + clearing the deprovisioning
    # markers) is owned solely by the events-stack cleanup Lambda, which fires once the ~1h
    # flush window (deprovisioningExpiry) has elapsed — after which no region can meter it.
    # The submitter's only deprovisioning role is prioritization (deprovisioning records first).

    logger.info(
        f"Submitted {len(outcomes)} aggregated record(s) across "
        f"{len(set(k[0] for k in outcomes))} license(s)"
    )

    if unprocessed_remaining:
        raise RuntimeError(
            "One or more UsageRecords remained unprocessed after retry; their "
            "aggregated_usage meteringPending markers were kept for re-submission."
        )
    return {"submitted": len(outcomes)}


def _read_deprovisioning_pending(now, deprovisioning) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Read pending aggregated records for the deprovisioning set, across the full window
    INCLUDING the current in-progress hour (offset 0..23), via a TARGETED per-license query on
    the aggregated_usage metering_pending GSI (`meteringPending = :hb AND licenseArn = :la` —
    the GSI RANGE key). Returns ALL of them
    (NOT subject to MAX_RECORDS_PER_RUN) so a closing-window license is never left behind the
    ordinary oldest-first backlog or dropped by the regular read cap. O(deprovisioning-records)."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    base = now.replace(minute=0, second=0, microsecond=0)
    # Include the CURRENT hour (offset 0) as well as now-1h..now-23h: the flush-deprovisioning
    # sweep enqueues a deprovisioning license's current-hour groups near its window close, so a
    # current-hour aggregated record can be pending and MUST be submitted before the window
    # closes. (The ORDINARY pass never reads the in-progress current hour; the deprovisioning
    # pass does, because for a deprovisioning license the window can close inside it.)
    for hours_back in range(23, -1, -1):
        hour_bucket = (base - timedelta(hours=hours_back)).strftime(core.HOUR_FMT)
        for license_arn in deprovisioning:
            kwargs: Dict[str, Any] = {
                "IndexName": "metering_pending",
                "KeyConditionExpression": "meteringPending = :hb AND licenseArn = :la",
                "ExpressionAttributeValues": {":hb": hour_bucket, ":la": license_arn},
            }
            while True:
                response = core.aggregated_usage_table.query(**kwargs)
                for item in response.get("Items", []):
                    out[(item["licenseArn"], item["account_dimension_hour"])] = item
                if "LastEvaluatedKey" not in response:
                    break
                kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return out


def _read_pending_aggregated(now, into=None) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Read pending aggregated records via the aggregated_usage metering_pending GSI over
    the submittable window ``now-23h … now-1h``, OLDEST-first.

    Oldest-first is deliberate: an offset-23 record is closest to falling out of the 24h
    BatchMeterUsage window, so it is drained first. Fills up to MAX_RECORDS_PER_RUN total per
    run so the backlog flushes fast; ``into`` (the already-read deprovisioning-first records)
    is preserved and counted toward the cap, and its keys are not re-read. Records that DID age
    past 24h are handled by the separate scheduled expiry Lambda over aggregated_usage — NOT
    here."""
    pending: Dict[Tuple[str, str], Dict[str, Any]] = into if into is not None else {}
    base = now.replace(minute=0, second=0, microsecond=0)
    for hours_back in range(23, 0, -1):  # 23 (oldest) .. 1 (newest completed hour)
        hour_bucket = (base - timedelta(hours=hours_back)).strftime(core.HOUR_FMT)
        kwargs: Dict[str, Any] = {
            "IndexName": "metering_pending",
            "KeyConditionExpression": "meteringPending = :hb",
            "ExpressionAttributeValues": {":hb": hour_bucket},
        }
        while True:
            response = core.aggregated_usage_table.query(**kwargs)
            for item in response.get("Items", []):
                key = (item["licenseArn"], item["account_dimension_hour"])
                if key not in pending:  # keep the deprovisioning-first read; don't overwrite
                    pending[key] = item
                if len(pending) >= MAX_RECORDS_PER_RUN:
                    return pending
            if "LastEvaluatedKey" not in response:
                break
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return pending


def _build_batches(pending, deprovisioning_licenses=None):
    """Build BatchMeterUsage records from aggregated rows, split into CA and legacy <=25
    batches. Each aggregated row is already validated + merged by the aggregator, so the
    submitter does not re-validate; it only shapes the API records.

    Records for a license currently in its deprovisioning flush window
    (``deprovisioning_licenses``, queried once from the sparse deprovisioning-pending-index)
    are ordered FIRST so a closing-window license is drained ahead of ordinary backlog; within
    each tier the existing oldest-first ordering of ``pending`` (now-23h -> now-1h) is preserved
    (dict insertion order). This only reorders which records fill the first BatchMeterUsage
    batches — it does not change what is submitted, the dedup, or the cadence."""
    deprovisioning_licenses = deprovisioning_licenses or set()
    # Deprovisioning-first, otherwise preserve insertion (oldest-first) order.
    ordered_items = sorted(
        pending.items(),
        key=lambda kv: 0 if kv[1].get("licenseArn") in deprovisioning_licenses else 1,
    )

    ca_records, ca_keys = [], []
    legacy_records, legacy_keys = [], []

    for agg_key, item in ordered_items:
        license_arn = item["licenseArn"]
        account_id = item.get("customerAWSAccountId", "")
        dimension = item["dimension"]
        quantity = core.strict_int(item.get("quantity", 0)) or 0
        hour_ts = datetime.strptime(item["hourBucket"], core.HOUR_FMT).replace(
            tzinfo=timezone.utc
        )

        record: Dict[str, Any] = {
            "Timestamp": hour_ts,
            "Dimension": dimension,
            "Quantity": quantity,
        }
        allocations = item.get("usageAllocations")
        if allocations:
            record["UsageAllocations"] = _to_api_allocations(allocations)

        if license_arn.startswith("arn:"):
            record["CustomerAWSAccountId"] = account_id
            record["LicenseArn"] = license_arn
            ca_records.append(record)
            ca_keys.append(agg_key)
        else:
            record["CustomerIdentifier"] = item.get("customerIdentifier", "")
            legacy_records.append(record)
            legacy_keys.append(agg_key)

    return _chunk(ca_records, ca_keys), _chunk(legacy_records, legacy_keys)


def _to_api_allocations(allocations) -> List[Dict[str, Any]]:
    """Normalize stored usageAllocations to the BatchMeterUsage shape (ints, not Decimal)."""
    out = []
    for alloc in allocations:
        out.append(
            {
                "AllocatedUsageQuantity": core.strict_int(alloc.get("AllocatedUsageQuantity")) or 0,
                "Tags": [
                    {"Key": t["Key"], "Value": t["Value"]} for t in alloc.get("Tags", [])
                ],
            }
        )
    return out


def _chunk(records, keys):
    return [
        (records[i : i + core.BATCH_SIZE], keys[i : i + core.BATCH_SIZE])
        for i in range(0, len(records), core.BATCH_SIZE)
    ]


def _write_back(item, outcome):
    """Persist MeteringRecordId + Status (+ reason) and REMOVE meteringPending on the
    aggregated_usage record. Not written to the raw usage table."""
    status = outcome.get("Status", "")
    metering_record_id = outcome.get("MeteringRecordId")
    reason = outcome.get("Reason")

    update = "REMOVE meteringPending SET meteringStatus = :st"
    values: Dict[str, Any] = {":st": status}
    if metering_record_id:
        update += ", meteringRecordId = :mid"
        values[":mid"] = metering_record_id
    if reason:
        update += ", meteringStatusReason = :rsn"
        values[":rsn"] = reason
    # Set a TTL epoch ONLY on a terminal Success row when retention is configured (>0), so
    # a finalized record self-prunes but pending/failed rows are never auto-expired.
    if AGGREGATED_USAGE_TTL_DAYS > 0 and status == "Success":
        ttl_epoch = int(
            (datetime.now(timezone.utc).timestamp()) + AGGREGATED_USAGE_TTL_DAYS * 86400
        )
        update += ", #ttl = :ttl"
        values[":ttl"] = ttl_epoch

    update, values, _ = core.with_audit_timestamps(update, values)
    kwargs: Dict[str, Any] = {
        "Key": {
            "licenseArn": item["licenseArn"],
            "account_dimension_hour": item["account_dimension_hour"],
        },
        "UpdateExpression": update,
        "ExpressionAttributeValues": values,
    }
    # `ttl` is not a DynamoDB reserved word, but use a name placeholder for safety/clarity.
    if AGGREGATED_USAGE_TTL_DAYS > 0 and status == "Success":
        kwargs["ExpressionAttributeNames"] = {"#ttl": "ttl"}

    core.aggregated_usage_table.update_item(**kwargs)
