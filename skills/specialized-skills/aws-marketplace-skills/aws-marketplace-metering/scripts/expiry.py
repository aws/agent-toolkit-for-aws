"""Aggregated-usage expiry Lambda.

EventBridge-scheduled on the SAME rate(5 minutes) rule as the submitter (independent
target, ReservedConcurrentExecutions=1). It sweeps the ``aggregated_usage`` table and
terminally expires pending records that can no longer be metered, so a record that was
never submitted (e.g. after a prolonged submitter backlog, or a previous-month record once
the month-end grace closes) is never left pending forever and the loss is always alarmed
(never silent). It operates on ``aggregated_usage`` ONLY — the raw usage table's own
age-out is handled by the discoverer's ageout shards.

Expiry rules (a pending aggregated record is expired when):
  - its hour is more than 24h in the past (past the BatchMeterUsage billable window); OR
  - it is a PREVIOUS-month record and the month-end grace has closed — i.e. it is on/after
    06:00 UTC on the 1st of the month. Before 06:00 UTC on the 1st the previous-month grace
    is still open, so previous-month records are still submittable and are NOT expired.

Case (b) INCLUDES previous-month records still INSIDE the 24h window: once the grace has
closed the service rejects them, so the submitter (which reads the now-23h..now-1h window)
would otherwise re-attempt them every run until they cross 24h. The expiry sweep therefore
also covers the in-window range (1..23) for previous-month buckets when the grace is closed,
and its past-window sweep starts at hours_back == 24 so it is CONTIGUOUS with the submitter's
window (no bucket falls between the two). Current-month in-window buckets are still
submittable and are never expired.

Expiring = REMOVE meteringPending, SET meteringStatus=SubmissionExpired, emit the
UsageSubmissionExpired metric (distinct from the raw table's UsageAggregationExpired age-out,
so an operator can tell "aggregated but never submitted" from "aged out before aggregation").
The record itself is retained (audit).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from handlers import metering_core as core

logger = core.logger

# How far back to sweep for stale pending buckets, and the empty-streak early stop — a
# sparse, self-terminating lookback (a backlog of non-empty buckets extends it).
EXPIRY_MAX_HOURS_BACK = 24 * 400
EXPIRY_EMPTY_STREAK_STOP = 6


def handler(event, context):
    if core.aggregated_usage_table is None:
        raise RuntimeError("AGGREGATED_USAGE_TABLE not configured")

    now = datetime.now(timezone.utc)
    base = now.replace(minute=0, second=0, microsecond=0)
    grace_open = core.previous_month_grace_open(now)  # 1st of month, before 06:00 UTC

    aged = 0

    # (b) Month-end reconciliation: once the grace has CLOSED (on/after 06:00 UTC on the
    # 1st), previous-month records INSIDE the 24h window are no longer submittable — the
    # service rejects them — yet the submitter's now-23h..now-1h window would keep
    # re-attempting them every run (failed submits + alarm noise) until they naturally
    # cross 24h. So when the grace is closed, expire previous-month buckets in the in-window
    # range 1..23 too. Current-month in-window buckets are still submittable → never touched.
    if not grace_open:
        for hours_back in range(1, 24):
            hour_bucket = (base - timedelta(hours=hours_back)).strftime(core.HOUR_FMT)
            if core.is_previous_month_bucket(hour_bucket, now):
                aged += _expire_bucket(hour_bucket)

    # Past-window sweep: everything strictly older than 24h is unbillable regardless of
    # month. Start at hours_back == 24 so this range is CONTIGUOUS with the submitter's
    # now-1h..now-23h window (no bucket falls between the two). A previous-month bucket while
    # the grace is still OPEN is skipped (still submittable). Sparse, self-terminating walk.
    hours_back = 24
    empty_streak = 0
    while hours_back <= EXPIRY_MAX_HOURS_BACK and empty_streak < EXPIRY_EMPTY_STREAK_STOP:
        hour_bucket = (base - timedelta(hours=hours_back)).strftime(core.HOUR_FMT)
        hours_back += 1

        is_prev_month = core.is_previous_month_bucket(hour_bucket, now)
        # A previous-month bucket is only expirable once the grace has CLOSED (>=06:00 UTC
        # on the 1st). While the grace is open, previous-month records are still submittable
        # → skip. Current-month buckets past 24h are always expirable.
        if is_prev_month and grace_open:
            continue

        found_any = _expire_bucket(hour_bucket)
        aged += found_any
        empty_streak = 0 if found_any else empty_streak + 1

    if aged:
        logger.error(f"Expired {aged} aggregated record(s) past the submittable window")
    else:
        logger.info("No aggregated records to expire")
    return {"expired": aged}


def _expire_bucket(hour_bucket) -> int:
    expired = 0
    kwargs: Dict[str, Any] = {
        "IndexName": "metering_pending",
        "KeyConditionExpression": "meteringPending = :hb",
        "ExpressionAttributeValues": {":hb": hour_bucket},
    }
    while True:
        response = core.aggregated_usage_table.query(**kwargs)
        for item in response.get("Items", []):
            core.emf_metric("UsageSubmissionExpired", 1)
            _expr, _vals, _ = core.with_audit_timestamps(
                "REMOVE meteringPending SET meteringStatus = :st",
                {":st": "SubmissionExpired"},
            )
            core.aggregated_usage_table.update_item(
                Key={
                    "licenseArn": item["licenseArn"],
                    "account_dimension_hour": item["account_dimension_hour"],
                },
                UpdateExpression=_expr,
                ExpressionAttributeValues=_vals,
            )
            logger.warning(
                "AGGREGATED EXPIRY: unbillable pending aggregated record "
                f"license={core.mask(item['licenseArn'])} hour={hour_bucket}"
            )
            expired += 1
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return expired
