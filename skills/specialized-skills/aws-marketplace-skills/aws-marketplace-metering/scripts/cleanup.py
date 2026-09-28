"""Cleanup Lambda.

SQS-triggered (the cleanup queue). Each message carries a licenseArn and ≤100 raw usage row
sort keys (PK+SK). A message MAY also carry meteringStatus="Aggregated" + totalQuantity +
recordCount — present ONLY when the enqueuing aggregator invocation FRESHLY WROTE the
aggregated record (so it knows the authoritative sum/count). Two message shapes:

  (d) WITH meteringStatus="Aggregated": per raw row clear meteringPending AND set
      meteringStatus="Aggregated" + meteringStatusReason="Aggregated total quantity <sum>
      from <count> raw usage records". Performed UNCONDITIONALLY (even if meteringPending was
      already cleared by another/duplicate process) so the authoritative status always lands.
  (e) WITHOUT a status (a duplicate/concurrent aggregator visit found the record already
      present): clear meteringPending ONLY — never stamp a sum that may differ from what the
      true writer persisted.

This makes a successfully-aggregated raw row observably distinct from a never-processed row
(previously only RejectedClientSide and AggregationExpired rows carried a status). The raw-row
meteringStatus domain is therefore {Aggregated, RejectedClientSide, AggregationExpired}; the
SUBMISSION outcome (meteringRecordId / Success / CustomerNotSubscribed / …) is NOT written
here — it lives only on the aggregated_usage record (the submitter owns it).

Why per-key UpdateItem and not BatchWriteItem
---------------------------------------------
DynamoDB BatchWriteItem only supports full-item Put/Delete — it CANNOT partially update a
single attribute. Rewriting the whole item via a PutRequest would clobber any concurrent
seller write to that row. So we apply a surgical
``UpdateItem ... REMOVE meteringPending SET meteringStatus, meteringStatusReason``
(idempotent: re-running overwrites the same values).

Avoiding a Lambda timeout without hot-spotting a partition
----------------------------------------------------------
To get batch-like speed we issue the per-key UpdateItems concurrently with a BOUNDED
thread pool (CLEANUP_MAX_WORKERS, default 16) rather than serially. Every row of a group
shares the same ``licenseArn`` partition key, so a burst hits ONE DynamoDB partition
(~1000 WCU/sec limit). Bounded concurrency + the <=100-keys-per-message chunk keep
instantaneous WCU under that limit; a throttling error is retried with exponential
backoff. A key that still fails after retries is NOT swallowed — the whole message is
failed (raising) so SQS redelivers it and it eventually lands on the DLQ; cleanup is never
silently dropped (the raw row simply keeps meteringPending and is re-discovered, where the
aggregator's conditional put no-ops and re-enqueues cleanup).

Cleanup runs only AFTER the aggregator durably wrote the aggregated_usage record, so
finalizing the raw rows here never loses un-aggregated usage.
"""

import json

from handlers import metering_core as core

logger = core.logger


def handler(event, context):
    failures = []
    for record in event.get("Records", []):
        try:
            _process_message(json.loads(record["body"]))
        except Exception as e:
            logger.error(f"Cleanup failed for a message: {type(e).__name__}: {e}")
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def _process_message(msg):
    license_arn = msg["licenseArn"]
    row_keys = [k for k in msg.get("rowKeys", []) if k]
    if not row_keys:
        return

    status = msg.get("meteringStatus")  # present only for a FRESH-write cleanup (rule a)
    if status == "Aggregated":
        # Rule (d): the aggregator freshly wrote the record, so this message carries the
        # authoritative sum + count. Clear meteringPending AND set the positive terminal
        # bookkeeping status/reason. UNCONDITIONAL — performed even if meteringPending was
        # already cleared by another process (a duplicate visit) — so the
        # authoritative status/reason always lands. Idempotent per-key UpdateItem.
        total_quantity = msg.get("totalQuantity", 0)
        record_count = msg.get("recordCount", len(row_keys))
        reason = f"Aggregated total quantity {total_quantity} from {record_count} raw usage records"
        core.update_rows_bounded(
            license_arn,
            row_keys,
            "REMOVE meteringPending SET meteringStatus = :st, meteringStatusReason = :rsn",
            {":st": "Aggregated", ":rsn": reason},
        )
        logger.info(
            f"Finalized {len(row_keys)} raw row(s) as Aggregated ({reason}) "
            f"for license={core.mask(license_arn)}"
        )
    else:
        # Rule (e): a status-less cleanup message (duplicate/concurrent visit).
        # Only clear meteringPending so the row leaves the sparse GSI; do NOT stamp a status
        # or a sum that might differ from what the true writer persisted.
        core.update_rows_bounded(
            license_arn,
            row_keys,
            "REMOVE meteringPending",
            {},
        )
        logger.info(
            f"Cleared meteringPending on {len(row_keys)} raw row(s) (no status) "
            f"for license={core.mask(license_arn)}"
        )
