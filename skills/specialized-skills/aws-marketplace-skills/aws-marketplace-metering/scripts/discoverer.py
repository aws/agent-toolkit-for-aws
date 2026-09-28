"""Discoverer Lambda.

Invoked hourly via 6 EventBridge rules x 5 constant-Input targets = 30 invocations on ONE
function (ReservedConcurrentExecutions=30). Each invocation owns exactly one slice,
determined SOLELY by its constant target Input (never a runtime clock read):

  - {"mode": "meter", "hourOffset": N} for N in 1..23 -> meter one completed hour
  - {"mode": "ageout", "shard": M} for M in 0..6 -> age out one lookback shard

meter mode:
  Query the metering_pending GSI for the single hour bucket floor(now,hour)-hourOffset and
  enqueue ONE work message per (licenseArn, customerAWSAccountId, dimension, hourBucket)
  group to the work queue. It does NOT read group rows, aggregate, submit, or write back.
  The lock gate is MONTH-AWARE: current-month buckets use the configured lock; a
  previous-month bucket drops to lock 0 (immediate) from 03:00 UTC on the 1st until the
  06:00 UTC month-end service cutoff, so previous-month reconciliation flushes in time.

ageout mode:
  Enumerate lookback buckets older than 24h whose (hours_back % 7) == shard, and for each
  stale pending row perform the terminal age-out directly: REMOVE meteringPending, set
  meteringStatus=AggregationExpired, emit the UsageAggregationExpired metric. Age-out is a cheap UpdateItem that
  does not need the aggregation pipeline. Previous-month buckets are NOT aged out while the
  month-end grace is open (on the 1st before 06:00 UTC) — the service still accepts them.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import boto3

from handlers import metering_core as core

logger = core.logger

sqs = boto3.client("sqs")
WORK_QUEUE_URL = os.environ.get("WORK_QUEUE_URL", "")
# Deprovisioning flush enqueues to a DEDICATED work queue (its own aggregator ESM) so a
# deprovisioning backlog is isolated from — never queued behind — the regular hourly backlog.
DEPROVISION_WORK_QUEUE_URL = os.environ.get("DEPROVISION_WORK_QUEUE_URL", "")

# For a deprovisioning license, also flush its CURRENT (in-progress) hour once we are within
# this lead time of the license's deprovisioningExpiry (the ~1h window close) — leaving ~10 min
# for the pipeline (sweep -> aggregator -> rate(5m) submitter) to drain the current hour before
# the window closes, while reserving the current hour until then for the seller's final writes.
CURRENT_HOUR_LEAD = timedelta(minutes=10)


def _parse_iso(ts):
    """Parse an ISO-8601 UTC timestamp (e.g. '2026-09-16T15:00:00Z') to an aware datetime,
    or None if absent/unparseable (caller then conservatively does NOT flush the current hour)."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

# Seller-configured lock period: an hour is not aggregated/submitted until it has
# been closed for MeteringLockHours hours. meter-mode invocations whose hourOffset is below
# the lock no-op, giving the seller's writers that many hours to send late usage for the
# hour before it is locked and submitted. Default 1 (process a fully-complete hour).
METERING_LOCK_HOURS = int(os.environ.get("METERING_LOCK_HOURS", "1"))

# Age-out lookback bounds (mirror the previous meter_usage age-out sweep, sharded by 7).
AGEOUT_EMPTY_STREAK_STOP = 6
AGEOUT_MAX_HOURS_BACK = 24 * 400
AGEOUT_SHARDS = 7


def handler(event, context):
    mode = (event or {}).get("mode")
    if mode == "meter":
        return _handle_meter(int(event["hourOffset"]))
    if mode == "ageout":
        return _handle_ageout(int(event["shard"]))
    if mode == "flush-deprovisioning":
        return _handle_flush_deprovisioning()
    raise RuntimeError(f"Discoverer invoked without a valid mode/offset: {event!r}")


def _handle_meter(hour_offset: int):
    if not (1 <= hour_offset <= 23):
        raise RuntimeError(f"hourOffset out of range: {hour_offset}")
    if not WORK_QUEUE_URL:
        raise RuntimeError("WORK_QUEUE_URL not configured")

    now = datetime.now(timezone.utc)
    hour_bucket = core.hour_bucket_for_offset(now, hour_offset)

    # Month-aware lock: current-month buckets use the configured lock; a
    # previous-month bucket drops to lock 0 (immediate) from 03:00 UTC on the 1st until the
    # 06:00 UTC service cutoff, so month-end reconciliation flushes before the grace closes.
    lock = core.effective_lock_hours(hour_bucket, now, METERING_LOCK_HOURS)
    if hour_offset < lock:
        logger.info(
            f"hourOffset {hour_offset} < effective lock {lock} for bucket {hour_bucket}: "
            "still open for late usage; no-op"
        )
        return {"hourOffset": hour_offset, "lock": lock, "enqueued": 0, "noop": True}

    groups = core.get_pending_groups(hour_bucket)
    if not groups:
        logger.info(f"No pending usage for hour bucket {hour_bucket} (offset {hour_offset})")
        return {"hourBucket": hour_bucket, "enqueued": 0}

    enqueued = _enqueue_work(groups, hour_bucket)
    logger.info(f"Enqueued {enqueued} group(s) for hour bucket {hour_bucket}")
    return {"hourBucket": hour_bucket, "enqueued": enqueued}


def _handle_flush_deprovisioning():
    """Expedited flush for licenses in their ~1-hour deprovisioning window.

    Runs on a rate(5m) rule (independent of the ordinary hourly meter rules, which are
    UNCHANGED). Queries the sparse deprovisioning-pending-index for licenses the subscription
    Lambda marked on `License Deprovisioned`, then enqueues each such license's pending groups
    over now-23h .. now-1h to the DEDICATED deprovision-work queue (isolated from the regular
    backlog), IGNORING MeteringLockHours so the aggregator + 5-min submitter can flush them
    before the window closes. The CURRENT (in-progress) hour is normally RESERVED (left for the
    seller's own direct writes/final events), BUT is ALSO flushed for a license once we are
    within CURRENT_HOUR_LEAD (10 min) of that license's deprovisioningExpiry (the ~1h window
    close) — so the current-hour usage still traverses the pipeline before the window closes.
    Idempotent: the aggregator conditional-put + BatchMeterUsage first-write-wins dedup prevent
    a double-bill if the ordinary run later re-enqueues the same group.
    """
    if not DEPROVISION_WORK_QUEUE_URL:
        raise RuntimeError("DEPROVISION_WORK_QUEUE_URL not configured")

    # {licenseArn: deprovisioningExpiry} — expiry (= deprovision event time + ~1h, the window
    # close) gates whether the CURRENT hour should now be flushed (see CURRENT_HOUR_LEAD below).
    deprovisioning = core.deprovisioning_licenses_with_expiry()
    if not deprovisioning:
        logger.info("flush-deprovisioning: no licenses in a deprovisioning window")
        return {"deprovisioningLicenses": 0, "enqueued": 0}

    now = datetime.now(timezone.utc)

    # Current-hour flush is gated on the window close: for each deprovisioning license, also
    # sweep the CURRENT (in-progress) hour ONCE we are within CURRENT_HOUR_LEAD (10 min) of the
    # license's deprovisioningExpiry, so the current-hour usage still traverses discoverer ->
    # aggregator -> submitter before the ~1-hour window closes, while leaving the current hour
    # reserved until then for the seller's final writes. Flush when now >= expiry - 10min.
    current_hour_licenses = set()
    for license_arn, expiry in deprovisioning.items():
        exp = _parse_iso(expiry)
        if exp is not None and now >= exp - CURRENT_HOUR_LEAD:
            current_hour_licenses.add(license_arn)

    total_enqueued = 0
    # offset 0 = current hour (only for settled licenses); offsets 1..23 = completed hours (all).
    for hour_offset in range(0, 24):
        hour_bucket = core.hour_bucket_for_offset(now, hour_offset)
        licenses_for_bucket = (
            current_hour_licenses if hour_offset == 0 else deprovisioning.keys()
        )
        if not licenses_for_bucket:
            continue
        # TARGETED read: query the metering_pending GSI per deprovisioning license
        # (meteringPending=:hb AND licenseArn=:la) rather than reading the whole bucket
        # partition across ALL licenses and filtering in memory — O(deprovisioning-groups),
        # never a full-partition scan. Lock is deliberately NOT consulted here —
        # that is the whole point of expediting.
        groups = []
        for license_arn in licenses_for_bucket:
            groups.extend(core.get_pending_groups_for_license(hour_bucket, license_arn))
        if groups:
            total_enqueued += _enqueue_work(groups, hour_bucket, DEPROVISION_WORK_QUEUE_URL)
    logger.info(
        f"flush-deprovisioning: enqueued {total_enqueued} group(s) across "
        f"{len(deprovisioning)} deprovisioning license(s) "
        f"({len(current_hour_licenses)} also current-hour-flushed) (lock bypassed)"
    )
    return {"deprovisioningLicenses": len(deprovisioning), "enqueued": total_enqueued}


def _enqueue_work(groups, hour_bucket, queue_url=None) -> int:
    """SendMessageBatch one message per (licenseArn, account, dimension, hourBucket) group.
    ``queue_url`` defaults to the regular work queue; the deprovisioning flush passes the
    dedicated deprovision-work queue so its backlog is isolated from the regular one."""
    queue_url = queue_url or WORK_QUEUE_URL
    enqueued = 0
    batch: List[Dict[str, Any]] = []
    for license_arn, account_id, dimension in groups:
        body = {
            "licenseArn": license_arn,
            "customerAWSAccountId": account_id,
            "dimension": dimension,
            "hourBucket": hour_bucket,
        }
        batch.append(
            {"Id": str(len(batch)), "MessageBody": json.dumps(body)}
        )
        if len(batch) == 10: # SQS SendMessageBatch max 10
            _flush_batch(batch, queue_url)
            enqueued += len(batch)
            batch = []
    if batch:
        _flush_batch(batch, queue_url)
        enqueued += len(batch)
    return enqueued


def _flush_batch(batch, queue_url):
    resp = sqs.send_message_batch(QueueUrl=queue_url, Entries=batch)
    failed = resp.get("Failed", [])
    if failed:
        # Do not swallow: a failed enqueue means those groups would silently not be
        # metered. Raise so the invocation fails and the alarm fires; the rows keep
        # meteringPending and are re-discovered next hour.
        raise RuntimeError(f"SQS SendMessageBatch had {len(failed)} failure(s): {failed}")


def _handle_ageout(shard: int):
    """Age out pending rows > 24h old whose (hours_back % 7) == shard."""
    if not (0 <= shard < AGEOUT_SHARDS):
        raise RuntimeError(f"shard out of range: {shard}")
    now = datetime.now(timezone.utc)
    base = now.replace(minute=0, second=0, microsecond=0)
    from datetime import timedelta

    hours_back = 24
    empty_streak = 0
    aged = 0
    while hours_back <= AGEOUT_MAX_HOURS_BACK and empty_streak < AGEOUT_EMPTY_STREAK_STOP:
        if hours_back % AGEOUT_SHARDS != shard:
            hours_back += 1
            continue
        hour_bucket = (base - timedelta(hours=hours_back)).strftime(core.HOUR_FMT)
        hours_back += 1
        # do NOT age out a PREVIOUS-month bucket while the month-end grace is open
        # (on the 1st before 06:00 UTC) — the service still accepts it, and age-out here
        # would expire exactly the records the reconciliation window is meant to save.
        if core.previous_month_grace_open(now) and core.is_previous_month_bucket(hour_bucket, now):
            continue
        pending = core.get_pending_groups(hour_bucket)
        if not pending:
            empty_streak += 1
            continue
        empty_streak = 0
        aged += _expire_bucket(pending, hour_bucket)
    logger.info(f"Age-out shard {shard}: expired {aged} row(s)")
    return {"shard": shard, "expired": aged}


def _expire_bucket(pending, hour_bucket) -> int:
    aged = 0
    for license_arn, account_id, dimension in pending:
        for row in core.read_group_rows(license_arn, account_id, dimension, hour_bucket):
            if "meteringPending" not in row:
                continue
            sort_key = row.get("customerAWSAccountId_dimension_timestamp", "")
            logger.warning(
                "AGE-OUT: dropping pending usage older than 24h (unbillable) "
                f"license={core.mask(license_arn)} account={core.mask(account_id)} "
                f"dim={dimension} hour={hour_bucket}"
            )
            core.emf_metric("UsageAggregationExpired", 1)
            _expr, _vals, _ = core.with_audit_timestamps(
                "REMOVE meteringPending SET meteringStatus = :st",
                {":st": "AggregationExpired"},
            )
            core.usage_table.update_item(
                Key={
                    "licenseArn": license_arn,
                    "customerAWSAccountId_dimension_timestamp": sort_key,
                },
                UpdateExpression=_expr,
                ExpressionAttributeValues=_vals,
            )
            aged += 1
    return aged
