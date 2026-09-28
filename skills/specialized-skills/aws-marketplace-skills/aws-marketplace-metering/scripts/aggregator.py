"""Aggregator Lambda.

SQS-triggered (the work queue), one message = one (licenseArn, account, dimension, hour)
group. Per group:

  1. Read the group's rows via the targeted begins_with prefix (streaming fold), sum the
     quantity, merge seller-provided VMT usageAllocations, and validate.
  2. INVALID -> reject-and-finalize CLIENT-SIDE here (not in the submitter): terminal
     RejectedClientSide + reason on each raw row, clear meteringPending, emit the
     UsageRecordRejected EMF metric. The group never reaches the submit path.
  3. VALID -> write ONE aggregated record into aggregated_usage via a CONDITIONAL
     PutItem (attribute_not_exists) — the idempotency commit point — carrying
     meteringPending so the submitter can find it. Then enqueue cleanup messages
     (<=100 raw row keys each) so the cleanup Lambda clears meteringPending on the raw
     rows asynchronously.

Idempotency: if the conditional PutItem fails (ConditionalCheckFailedException) the group
was already aggregated by a prior visit; skip the put AND skip enqueuing cleanup (inflation
guard). collect_group only returns rows still carrying meteringPending, so an already-cleaned
group yields no row_keys and no-ops earlier; a genuinely-lost cleanup self-heals on the next
scheduled re-visit (rows still pending are re-detected and cleaned), not by re-enqueuing on
every duplicate visit.

Zero-quantity handling: an in-window 0-quantity group is left pending
(submitting 0 early would lock the hour at 0 via first-write-wins); at the oldest edge
(hour == now-23h) it is aggregated as Quantity 0.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError

from handlers import metering_core as core

logger = core.logger

sqs = boto3.client("sqs")
CLEANUP_QUEUE_URL = os.environ.get("CLEANUP_QUEUE_URL", "")


def handler(event, context):
    if core.aggregated_usage_table is None:
        raise RuntimeError("AGGREGATED_USAGE_TABLE not configured")
    if not CLEANUP_QUEUE_URL:
        raise RuntimeError("CLEANUP_QUEUE_URL not configured")

    now = datetime.now(timezone.utc)
    failures = []
    for record in event.get("Records", []):
        try:
            _process_message(json.loads(record["body"]), now)
        except Exception as e:
            # Report partial batch failure so only the failed message is retried/DLQ'd.
            logger.error(f"Aggregation failed for a group: {type(e).__name__}: {e}")
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def _process_message(msg, now):
    license_arn = msg["licenseArn"]
    account_id = msg["customerAWSAccountId"]
    dimension = msg["dimension"]
    hour_bucket = msg["hourBucket"]

    group = core.collect_group(license_arn, account_id, dimension, hour_bucket)
    if not group["row_keys"]:
        # Nothing pending (already cleaned up by a prior visit) — no-op, idempotent.
        logger.info(
            f"No pending rows for group license={core.mask(license_arn)} "
            f"dim={dimension} hour={hour_bucket}; skipping"
        )
        return

    # In-window zero-quantity group: leave pending (do not aggregate yet). At the oldest
    # edge it falls through and is aggregated as Quantity 0.
    oldest_edge = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
    if group["quantity"] == 0 and not group["reject_reason"] and group["hour_ts"] > oldest_edge:
        logger.info(
            f"In-window zero-quantity group left pending license={core.mask(license_arn)} "
            f"dim={dimension} hour={hour_bucket}"
        )
        return

    reason = core.validate_group(group, now)
    if reason:
        _reject(group, reason)
        return

    written = _write_aggregated(group)
    if written:
        # Fresh write — enqueue cleanup carrying the authoritative Aggregated status + sum/count.
        _enqueue_cleanup(group, stamp_status=True)
    else:
        # Duplicate/concurrent visit: a PRIOR aggregator run already wrote the aggregated
        # record. Do NOT enqueue a (status-less) cleanup here — that only inflates the cleanup
        # queue. collect_group already filters to rows still carrying meteringPending, so if the
        # prior cleanup succeeded these rows would have been absent and we'd have no-op'd above;
        # if a prior cleanup was genuinely lost, the rows still carry meteringPending and are
        # re-discovered on the NEXT scheduled sweep, which re-detects and cleans them (one-cycle
        # self-heal) — without a status-less enqueue on every duplicate visit.
        logger.info(
            f"Aggregated record already exists (idempotent) for license={core.mask(license_arn)} "
            f"dim={dimension} hour={hour_bucket}; NOT re-enqueuing cleanup (inflation guard). "
            "Any still-pending rows self-heal on the next scheduled re-visit."
        )


def _write_aggregated(group) -> bool:
    """Conditional PutItem into aggregated_usage. Returns True if written, False if it
    already existed (ConditionalCheckFailedException — idempotent commit point)."""
    item = {
        "licenseArn": group["license_arn"],
        "account_dimension_hour": core.agg_sort_key(
            group["account_id"], group["dimension"], group["hour_bucket"]
        ),
        "customerAWSAccountId": group["account_id"],
        "dimension": group["dimension"],
        "hourBucket": group["hour_bucket"],
        "quantity": group["quantity"],
        "meteringPending": group["hour_bucket"],
    }
    allocations = core.finalize_allocations(group)
    if allocations:
        item["usageAllocations"] = allocations
    if group.get("customer_identifier"):
        item["customerIdentifier"] = group["customer_identifier"]
    try:
        core.aggregated_usage_table.put_item(
            Item=core.audit_item(item),
            ConditionExpression="attribute_not_exists(licenseArn)",
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _reject(group, reason):
    """Reject-and-finalize CLIENT-SIDE: terminal status + reason on every raw
    row of the group, clear meteringPending, WARN, emit the UsageRecordRejected metric.
    The rejected group is never aggregated or submitted. Writes use the shared bounded
    thread pool + backoff (a rejected group is up to ~3600 same-licenseArn-partition
    UpdateItems — same hot-partition guard as cleanup), and raise on any unrecoverable
    failure so the message is retried (SQS redelivery/DLQ), never silently half-rejected."""
    logger.warning(
        "Rejecting usage group client-side "
        f"(license={core.mask(group['license_arn'])} dim={group['dimension']} "
        f"hour={group['hour_bucket']}): {reason}"
    )
    core.emf_metric("UsageRecordRejected", 1, reason=reason)
    core.update_rows_bounded(
        group["license_arn"],
        group["row_keys"],
        "REMOVE meteringPending SET meteringStatus = :st, meteringStatusReason = :rsn",
        {":st": core.STATUS_REJECTED, ":rsn": reason},
    )


def _enqueue_cleanup(group, stamp_status):
    """Enqueue cleanup messages carrying ≤100 raw row keys each (PK licenseArn + SKs).

    stamp_status=True  (rule a — THIS invocation freshly wrote the aggregated record):
        include meteringStatus="Aggregated", totalQuantity, and recordCount so the cleanup
        Lambda stamps the authoritative "Aggregated total quantity <sum> from <count> raw
        usage records" reason. Only the writer knows the true sum/count.
    stamp_status=False (rule b — the record already existed; duplicate/concurrent visit):
        carry ONLY the row keys and NO status — cleanup clears meteringPending only, never
        stamping a sum that may differ from what the true writer persisted.

    Uses SendMessageBatch (≤10 entries/call, like the discoverer); a partial Failed result
    raises so the message is retried (a lost cleanup self-heals on the next hourly re-visit)."""
    license_arn = group["license_arn"]
    keys = group["row_keys"]
    entries: List[Dict[str, Any]] = []
    for i in range(0, len(keys), core.CLEANUP_KEYS_PER_MESSAGE):
        chunk = keys[i : i + core.CLEANUP_KEYS_PER_MESSAGE]
        body = {"licenseArn": license_arn, "rowKeys": chunk}
        if stamp_status:
            body["meteringStatus"] = "Aggregated"
            body["totalQuantity"] = group["quantity"]
            body["recordCount"] = len(keys)
        entries.append({"Id": str(len(entries)), "MessageBody": json.dumps(body)})
        if len(entries) == 10:  # SQS SendMessageBatch max 10 entries/call
            _flush_cleanup_batch(entries)
            entries = []
    if entries:
        _flush_cleanup_batch(entries)


def _flush_cleanup_batch(entries):
    resp = sqs.send_message_batch(QueueUrl=CLEANUP_QUEUE_URL, Entries=entries)
    failed = resp.get("Failed", [])
    if failed:
        raise RuntimeError(f"SQS SendMessageBatch had {len(failed)} cleanup failure(s): {failed}")
