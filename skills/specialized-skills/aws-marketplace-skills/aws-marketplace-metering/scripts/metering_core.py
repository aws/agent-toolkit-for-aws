"""Shared metering core for the decoupled metering pipeline.

This module holds the logic reused across the four pipeline Lambdas
(``discoverer`` / ``aggregator`` / ``cleanup`` / ``submitter``): DynamoDB clients,
the ``metering_pending`` GSI discovery, the targeted per-group read, VMT allocation
merging, strict quantity/record validation, the BatchMeterUsage submit (with retry-once
and request-level poison isolation), and the small helpers (masking, EMF metrics).

design (see references/scalable-metering-design.md):
  - Usage-table sort key is ``customerAWSAccountId#dimension#timestampSeconds`` at SECOND
    precision (revises the earlier millisecond precision). Each second-row is treated as
    authoritative; the pipeline does NOT coalesce same-second events.
  - Aggregation, submission and raw-row cleanup are decoupled into separate Lambdas
    connected by SQS. ``aggregated_usage`` (PK licenseArn, SK account#dimension#hour) is
    the submission source of truth, written by the aggregator via a CONDITIONAL PutItem
    (the idempotency commit point) and consumed by the submitter.
"""

import json
import logging
import math
import os
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Subscribers table is in us-east-1 (where EventBridge lifecycle events land).
_dynamodb_iad = boto3.resource(
    "dynamodb", region_name=os.environ.get("SUBSCRIBERS_TABLE_REGION", "us-east-1")
)
subscribers_table = _dynamodb_iad.Table(os.environ["SUBSCRIBERS_TABLE"])

# Usage + aggregated-usage tables are in the seller's metering region (this Lambda's
# runtime region).
_dynamodb = boto3.resource("dynamodb")
# USAGE_TABLE is set on the raw-pipeline functions (discoverer/aggregator/cleanup). In
# direct-submit mode there is no raw usage table, so the submitter/expiry (which import this
# module) run without it — tolerate its absence rather than failing at import.
_USAGE_TABLE_NAME = os.environ.get("USAGE_TABLE")
# Typed Any (not Optional[Table]) so mypy check_untyped_defs does not flag .query on the
# raw-pipeline read helpers below: those helpers only run on the discoverer/aggregator/
# cleanup Lambdas, where USAGE_TABLE is always set. No behavior change.
usage_table: Any = _dynamodb.Table(_USAGE_TABLE_NAME) if _USAGE_TABLE_NAME else None
# AGGREGATED_USAGE_TABLE is set on the aggregator/submitter/cleanup functions; the
# discoverer does not need it, so tolerate its absence there.
_AGG_TABLE_NAME = os.environ.get("AGGREGATED_USAGE_TABLE")
aggregated_usage_table = _dynamodb.Table(_AGG_TABLE_NAME) if _AGG_TABLE_NAME else None

# BatchMeterUsage is a REGIONAL API: no hardcoded region so it runs in the Lambda's region.
mp_client = boto3.client("meteringmarketplace")

PRODUCT_CODE = os.environ["PRODUCT_CODE"]

BATCH_SIZE = 25 # BatchMeterUsage hard limit: max 25 UsageRecords per call.
MAX_ALLOCATIONS_PER_RECORD = 2500 # BatchMeterUsage per-UsageRecord UsageAllocations cap.
MAX_TAGS_PER_ALLOCATION = 5 # BatchMeterUsage per-allocation Tags cap.
CLEANUP_KEYS_PER_MESSAGE = 100 # row keys per cleanup SQS message.

_LICENSE_ARN_RE = re.compile(r"^arn:aws[a-zA-Z-]*:license-manager:[^:]*:[0-9]{12}:license:.+$")

METRIC_NAMESPACE = os.environ.get("METRIC_NAMESPACE", "AwsMarketplace/Metering")
# live (prod) vs dry-run (non-prod sandbox). Emitted as an EMF dimension so a dry run is never
# mistaken for real billing on the dashboards/alarms.
METERING_MODE = os.environ.get("METERING_MODE", "live").strip().lower()

STATUS_REJECTED = "RejectedClientSide"

# Max recursion depth for request-level-failure bisection. Bisecting isolates a poison record so
# its co-batched records still meter, but UNBOUNDED bisection can issue up to ~2N BatchMeterUsage
# calls for an N-record batch when many records fail — a real load/throttle risk on the submitter.
# The cap is DERIVED from BATCH_SIZE as ceil(log2(BATCH_SIZE)) (= 5 for 25) so the recursion can
# always narrow a full batch down to a SINGLE record — a shallower cap (e.g. 3) leaves the
# smallest reachable sub-batch at ~4 records and can NEVER isolate a lone poison record, defeating
# the purpose. At the cap a still-failing MULTI-record sub-batch is NOT split further — it is left
# pending (no terminal outcome) so it is retried on the NEXT run and a BisectDepthExceeded metric
# is emitted; a single isolated record is still terminally reason-coded.
MAX_BISECT_DEPTH = math.ceil(math.log2(BATCH_SIZE)) if BATCH_SIZE > 1 else 0

# Sparse deprovisioning index (subscribers table): the subscription Lambda sets
# `deprovisioningPendingFlag = DEPROVISIONING_PENDING_VALUE` (constant HASH) + a
# `deprovisioningExpiry` (event time + ~1h, ISO) on License Deprovisioned; the events-stack
# cleanup Lambda REMOVEs both once expired. The index is HASH=flag + RANGE=expiry, so a
# single Query returns every license still in a flush window (discoverer sweep + submitter),
# and a range Query (expiry <= now) returns the expired ones (cleanup).
DEPROVISIONING_PENDING_INDEX = "deprovisioning-pending-index"
DEPROVISIONING_PENDING_VALUE = "1"

# Hour-bucket format (GSI HASH) and second-precision timestamp format (sort key).
HOUR_FMT = "%Y-%m-%dT%H"
SECOND_FMT = "%Y-%m-%dT%H:%M:%S"  # raw-usage sort-key suffix precision (whole seconds)


def validate_sort_key(sort_key: str, account_id: str, dimension: str) -> Optional[str]:
    """Validate a raw-usage row's sort key is exactly
    ``{customerAWSAccountId}#{dimension}#{YYYY-MM-DDTHH:MM:SS}`` (SECOND precision).

    Returns a client-side reject reason code if malformed, else None. This enforces the
    seller-writer contract at aggregation time (the aggregator's fold) so a wrong-precision
    (e.g. millisecond) or malformed suffix is caught as a reason-coded RejectedClientSide row
    rather than silently mis-folded or never metered. The account/dimension segments MUST
    match the group the row was read for (a mismatch means a corrupt/mis-keyed row).
    """
    if not sort_key:
        return "MalformedSortKey"
    # rsplit on the last two '#': the timestamp suffix has no '#', but a dimension MAY.
    parts = sort_key.split("#")
    if len(parts) < 3:
        return "MalformedSortKey"
    key_account = parts[0]
    key_ts = parts[-1]
    key_dimension = "#".join(parts[1:-1])
    if key_account != account_id or key_dimension != dimension:
        return "SortKeyMismatch"
    # Exact SECOND precision: strptime accepts it AND re-formatting round-trips (so a
    # millisecond/fractional or truncated suffix like '...:07.123' or '...T13' is rejected).
    try:
        parsed = datetime.strptime(key_ts, SECOND_FMT)
    except (ValueError, TypeError):
        return "MalformedTimestamp"
    if parsed.strftime(SECOND_FMT) != key_ts:
        return "MalformedTimestamp"
    return None


# ─── Time windows ────────────────────────────────────────────────────────────
def completed_hour_buckets(now: datetime) -> List[str]:
    """Hour-bucket strings for now-23h .. now-1h inclusive, OLDEST first."""
    base = now.replace(minute=0, second=0, microsecond=0)
    return [(base - timedelta(hours=h)).strftime(HOUR_FMT) for h in range(23, 0, -1)]


def hour_bucket_for_offset(now: datetime, hour_offset: int) -> str:
    """The single completed hour bucket ``floor(now, hour) - hour_offset``.

    The discoverer derives its bucket purely from the constant target Input offset, never
    from a second wall-clock read, so 23 offsets map to 23 disjoint, gap-free buckets.
    """
    base = now.replace(minute=0, second=0, microsecond=0)
    return (base - timedelta(hours=hour_offset)).strftime(HOUR_FMT)


# ─── Audit timestamps (createdAt/updatedAt) ────────────────────────────────────
def now_iso() -> str:
    """Current time as an ISO-8601 UTC timestamp (whole seconds, 'Z' suffix)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def with_audit_timestamps(update_expr: str, values: dict, names: Optional[dict] = None):
    """Augment an UpdateItem expression with createdAt/updatedAt audit stamps.

    Sets ``createdAt = if_not_exists(createdAt, :now)`` (written ONCE, preserved on upsert)
    and ``updatedAt = :now`` (refreshed on EVERY write). Works whether ``update_expr`` already
    has a ``SET`` clause (the stamps are appended to it) or is REMOVE-only (a ``SET`` clause is
    added). Returns the augmented (expr, values, names). Idempotent stamping of createdAt makes
    repeated upserts keep the original creation time.
    """
    ts = now_iso()
    values = dict(values)
    values[":now"] = ts
    stamps = "createdAt = if_not_exists(createdAt, :now), updatedAt = :now"
    if "SET " in update_expr:
        update_expr = f"{update_expr}, {stamps}"
    else:
        # REMOVE-only (or other clause) with no SET — add one.
        update_expr = f"{update_expr} SET {stamps}"
    return update_expr, values, names


def audit_item(item: dict) -> dict:
    """Stamp createdAt + updatedAt on a PutItem payload (both = now for a fresh insert)."""
    ts = now_iso()
    item = dict(item)
    item.setdefault("createdAt", ts)
    item["updatedAt"] = ts
    return item


# ─── Month-boundary reconciliation window ────────────────────────────
# AWS Marketplace accepts PREVIOUS-month usage until this UTC hour on the 1st of the next
# month (the documented month-end grace). Named constants so the boundary is adjustable.
MONTH_GRACE_LOCK_DROP_HOUR = 3 # from 03:00 UTC on the 1st, previous-month lock -> 0
MONTH_GRACE_CUTOFF_HOUR = 6 # service stops accepting previous-month usage at 06:00 UTC


def is_previous_month_bucket(hour_bucket: str, now: datetime) -> bool:
    """True if the bucket's hour falls in the calendar month BEFORE ``now``'s month (UTC)."""
    bucket_ts = datetime.strptime(hour_bucket, HOUR_FMT).replace(tzinfo=timezone.utc)
    return (bucket_ts.year, bucket_ts.month) < (now.year, now.month)


def _in_month_grace_flush(now: datetime) -> bool:
    """True during the month-end IMMEDIATE-flush window: the 1st of the month, at/after
    MONTH_GRACE_LOCK_DROP_HOUR (03:00) and before the MONTH_GRACE_CUTOFF_HOUR (06:00) UTC."""
    return now.day == 1 and MONTH_GRACE_LOCK_DROP_HOUR <= now.hour < MONTH_GRACE_CUTOFF_HOUR


def effective_lock_hours(hour_bucket: str, now: datetime, configured_lock: int) -> int:
    """Month-aware effective lock (in hours) for one bucket.

    - Current-month bucket: the configured lock, always.
    - Previous-month bucket, from 03:00 UTC on the 1st (until the 06:00 cutoff): 0 (submit
      immediately every run).
    - Previous-month bucket, before 03:00 UTC on the 1st (and any other time it is still a
      previous-month bucket within the window): the configured lock, unchanged.
    """
    lock = min(max(configured_lock, 1), 20)
    if is_previous_month_bucket(hour_bucket, now) and _in_month_grace_flush(now):
        return 0
    return lock


def previous_month_grace_open(now: datetime) -> bool:
    """True while previous-month age-out SHALL be suppressed: on the 1st of the month
    before the 06:00 UTC service cutoff. After the cutoff, normal age-out resumes."""
    return now.day == 1 and now.hour < MONTH_GRACE_CUTOFF_HOUR


# ─── metering_pending GSI discovery ──────────────────────────────────────────
def get_pending_groups(hour_bucket: str) -> List[Tuple[str, str, str]]:
    """Query the ``metering_pending`` GSI for one hour bucket and return de-duplicated
    ``(licenseArn, customerAWSAccountId, dimension)`` tuples.

    Errors are NOT swallowed: a failed GSI query raises so the invocation fails and the
    alarm fires.
    """
    seen = set()
    ordered: List[Tuple[str, str, str]] = []
    kwargs: Dict[str, Any] = {
        "IndexName": "metering_pending",
        "KeyConditionExpression": "meteringPending = :hb",
        "ExpressionAttributeValues": {":hb": hour_bucket},
    }
    response = usage_table.query(**kwargs)
    while True:
        for item in response.get("Items", []):
            arn = item.get("licenseArn", "")
            if not arn:
                continue
            tup = (arn, item.get("customerAWSAccountId", ""), item.get("dimension", ""))
            if tup not in seen:
                seen.add(tup)
                ordered.append(tup)
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = usage_table.query(**kwargs)
    return ordered


def get_pending_groups_for_license(hour_bucket: str, license_arn: str) -> List[Tuple[str, str, str]]:
    """TARGETED variant of get_pending_groups for a SINGLE license.

    The ``metering_pending`` GSI is HASH ``meteringPending`` + RANGE ``licenseArn``,
    so adding ``AND licenseArn = :la`` scopes the read to just this license's pending groups in
    the bucket — O(this-license's-groups), never the whole-bucket partition across all licenses.
    Used by the flush-deprovisioning sweep so it does not read every license's pending set to
    isolate a handful of deprovisioning ones (a targeted read, never a full-partition scan).
    Errors are NOT swallowed.
    """
    seen = set()
    ordered: List[Tuple[str, str, str]] = []
    kwargs: Dict[str, Any] = {
        "IndexName": "metering_pending",
        "KeyConditionExpression": "meteringPending = :hb AND licenseArn = :la",
        "ExpressionAttributeValues": {":hb": hour_bucket, ":la": license_arn},
    }
    response = usage_table.query(**kwargs)
    while True:
        for item in response.get("Items", []):
            arn = item.get("licenseArn", "")
            if not arn:
                continue
            tup = (arn, item.get("customerAWSAccountId", ""), item.get("dimension", ""))
            if tup not in seen:
                seen.add(tup)
                ordered.append(tup)
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = usage_table.query(**kwargs)
    return ordered


def read_group_rows(license_arn: str, account_id: str, dimension: str, hour_bucket: str):
    """Targeted read of ONE (license, account, dimension, hour) group via the sort-key
    begins_with prefix — NOT a full licenseArn-partition query + filter.

    The prefix is ``{account}#{dimension}#{hourBucket}``; with SECOND precision the sort
    key is ``{account}#{dimension}#{YYYY-MM-DDTHH:MM:SS}`` so the hour-prefix match still
    captures every second within the hour. Streams pages (caller folds; never materializes
    all rows beyond the returned page list).
    """
    prefix = f"{account_id}#{dimension}#{hour_bucket}"
    rows = []
    kwargs: Dict[str, Any] = {
        "KeyConditionExpression": (
            "licenseArn = :la AND begins_with(customerAWSAccountId_dimension_timestamp, :pfx)"
        ),
        "ExpressionAttributeValues": {":la": license_arn, ":pfx": prefix},
    }
    response = usage_table.query(**kwargs)
    rows.extend(response.get("Items", []))
    while "LastEvaluatedKey" in response:
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        response = usage_table.query(**kwargs)
        rows.extend(response.get("Items", []))
    return rows


# ─── Aggregation (fold a group's rows into one record) ───────────────────────
def collect_group(license_arn, account_id, dimension, hour_bucket) -> Dict[str, Any]:
    """Read the targeted (license, account, dimension, hour) rows and fold them into one
    aggregation group dict (sum quantity + merge VMT allocations + capture row keys).
    """
    hour_ts = datetime.strptime(hour_bucket, HOUR_FMT).replace(tzinfo=timezone.utc)
    group: Dict[str, Any] = {
        "license_arn": license_arn,
        "account_id": account_id,
        "dimension": dimension,
        "hour_bucket": hour_bucket,
        "hour_ts": hour_ts,
        "quantity": 0,
        "row_keys": [],
        "alloc_by_tagset": {}, # signature -> {"tags": [...], "qty": int}
        "tagged_nonzero_rows": 0,
        "untagged_nonzero_rows": 0,
        "reject_reason": None,
        "customer_identifier": "",
    }
    for row in read_group_rows(license_arn, account_id, dimension, hour_bucket):
        if "meteringPending" not in row:
            continue
        sort_key = row.get("customerAWSAccountId_dimension_timestamp", "")
        group["row_keys"].append(sort_key)
        sk_reason = validate_sort_key(sort_key, account_id, dimension)
        if sk_reason:
            group["reject_reason"] = group["reject_reason"] or sk_reason
            continue
        if not group["customer_identifier"]:
            group["customer_identifier"] = row.get("customerIdentifier", "") or ""

        raw_qty = row.get("quantity", 0)
        qty = strict_int(raw_qty)
        if qty is None:
            group["reject_reason"] = group["reject_reason"] or quantity_reason(raw_qty)
            continue
        if qty < 0:
            group["reject_reason"] = group["reject_reason"] or "NegativeQuantity"
            continue

        group["quantity"] += qty

        row_allocs = row.get("usageAllocations")
        if qty == 0:
            continue
        if row_allocs:
            group["tagged_nonzero_rows"] += 1
            reason = merge_allocations(group["alloc_by_tagset"], row_allocs)
            if reason:
                group["reject_reason"] = group["reject_reason"] or reason
        else:
            group["untagged_nonzero_rows"] += 1
    return group


def merge_allocations(alloc_by_tagset, row_allocs) -> Optional[str]:
    """Merge one row's seller-provided usageAllocations into the group's map, summing
    identical tag sets. Returns a reason code if malformed, else None. The meter
    logic NEVER invents or re-partitions tags — only carries through the seller's split.
    """
    if not isinstance(row_allocs, list):
        return "MalformedAllocations"
    for alloc in row_allocs:
        if not isinstance(alloc, dict):
            return "MalformedAllocations"
        aq = strict_int(alloc.get("AllocatedUsageQuantity"))
        if aq is None or aq < 0:
            return "NegativeOrNonIntegerAllocation"
        tags = alloc.get("Tags", [])
        if not isinstance(tags, list) or not (1 <= len(tags) <= MAX_TAGS_PER_ALLOCATION):
            return (
                "TooManyTags"
                if isinstance(tags, list) and len(tags) > MAX_TAGS_PER_ALLOCATION
                else "MissingTagKeyOrValue"
            )
        norm = []
        for t in tags:
            if not isinstance(t, dict) or not t.get("Key") or not t.get("Value"):
                return "MissingTagKeyOrValue"
            norm.append((str(t["Key"]), str(t["Value"])))
        signature = tuple(sorted(norm))
        entry = alloc_by_tagset.setdefault(signature, {"tags": norm, "qty": 0})
        entry["qty"] += aq
    return None


def validate_group(group: Dict[str, Any], now: datetime) -> Optional[str]:
    """Return a specific reason code if the aggregated group is invalid, else None.

    Covers a source-row reason recorded during the fold, dimension, identifier (incl.
    LicenseArn shape, ), the 24h timestamp window, and the merged VMT allocation
    invariants. Zero-quantity in-window handling is the caller's concern.
    """
    if group["reject_reason"]:
        return group["reject_reason"]

    license_arn = group["license_arn"]
    account_id = group["account_id"]
    dimension = group["dimension"]
    quantity = group["quantity"]
    hour_ts = group["hour_ts"]

    if not dimension:
        return "MissingDimension"
    # NOTE: dimension VALIDITY is intentionally NOT checked client-side against a configured
    # list. BatchMeterUsage is the authority on which dimensions the catalog accepts; a bad
    # dimension surfaces as a per-record UsageRecordResult status at submit time. This keeps
    # the pipeline decoupled from the catalog — adding/renaming a pricing dimension needs NO
    # stack redeploy.

    if hour_ts > now:
        return "TimestampInFuture"
    if hour_ts < now - timedelta(hours=24):
        return "TimestampOutOfWindow"

    if license_arn.startswith("arn:"):
        if not _LICENSE_ARN_RE.match(license_arn):
            return "InvalidLicenseArn"
        if not account_id:
            return "MissingCustomerAWSAccountId"
    else:
        if not group.get("customer_identifier") and not account_id:
            return "MissingLegacyIdentifier"

    if group["tagged_nonzero_rows"] and group["untagged_nonzero_rows"]:
        return "MixedAllocatedAndUnallocated"
    if group["alloc_by_tagset"]:
        if len(group["alloc_by_tagset"]) > MAX_ALLOCATIONS_PER_RECORD:
            return "TooManyAllocations"
        alloc_sum = sum(e["qty"] for e in group["alloc_by_tagset"].values())
        if alloc_sum != quantity:
            return "AllocationSumMismatch"
    return None


def finalize_allocations(group: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the merged UsageAllocations list for the record, or [] to omit it."""
    if group["untagged_nonzero_rows"] or not group["alloc_by_tagset"]:
        return []
    return [
        {
            "AllocatedUsageQuantity": entry["qty"],
            "Tags": [{"Key": k, "Value": v} for k, v in entry["tags"]],
        }
        for entry in group["alloc_by_tagset"].values()
    ]


# ─── BatchMeterUsage submit ──────────────────────────────────────────────────
def submit_records(records, keys, outcomes, use_product_code=False) -> bool:
    """Send one <=25-record batch, capture per-record terminal status into ``outcomes``,
    retry transient UnprocessedRecords ONCE, and ISOLATE a request-level failure by
    bisecting (bounded to MAX_BISECT_DEPTH levels). Returns True if any records remain
    unprocessed and should be retried on the next run (transient, OR a still-failing sub-batch
    left un-isolated at the bisect-depth cap).
    """
    if not records:
        return False
    return _submit(records, keys, outcomes, use_product_code, depth=0)


def _submit(records, keys, outcomes, use_product_code, depth=0) -> bool:
    key_by_identity = {_identity(records[i]): keys[i] for i in range(len(records))}
    kwargs: Dict[str, Any] = {"UsageRecords": records}
    if use_product_code:
        kwargs["ProductCode"] = PRODUCT_CODE

    try:
        response = mp_client.batch_meter_usage(**kwargs)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if _is_transient(code):
            raise
        if len(records) == 1:
            gk = keys[0]
            # A single record isolated by bisection == a REQUEST-level BatchMeterUsage exception
            # for THIS record (InvalidUsageDimensionException, TimestampOutOfBoundsException,
            # InvalidTagException, InvalidProductCodeException, InvalidLicenseException, ...) — NOT
            # a per-record Results status. Stamp the aggregated record RejectedClientSide with the
            # exception name as reason, and emit the BatchMeterUsageException metric (by exception)
            # here, where the real terminal status for this record is decided (after all bisecting).
            exception = code or "RequestRejected"
            outcomes[gk] = {
                "MeteringRecordId": None,
                "Status": STATUS_REJECTED,
                "Reason": exception,
                "RequestException": exception,
            }
            emf_metric("BatchMeterUsageException", 1, exception=exception)
            logger.warning(f"Isolated request-level BatchMeterUsage exception ({exception}) for a single record")
            return False
        if depth >= MAX_BISECT_DEPTH:
            # Bisect cap reached and this multi-record sub-batch still fails. Do NOT split further
            # (that is what puts ~2N calls of load on the submitter). Leave these records PENDING
            # (no terminal outcome stamped, so meteringPending stays set) to be retried on the next
            # submission run, and signal that records remain unprocessed so the invocation fails and
            # the alarm fires. The offending record still ages out at 24h if never isolated.
            logger.warning(
                f"Bisect depth cap ({MAX_BISECT_DEPTH}) reached with {len(records)} record(s) still "
                f"failing ({code}); leaving them pending for the next run rather than bisecting further"
            )
            emf_metric("BisectDepthExceeded", len(records))
            return True
        mid = len(records) // 2
        left = _submit(records[:mid], keys[:mid], outcomes, use_product_code, depth + 1)
        right = _submit(records[mid:], keys[mid:], outcomes, use_product_code, depth + 1)
        return left or right

    _capture_results(response, key_by_identity, outcomes)

    unprocessed = list(response.get("UnprocessedRecords", []) or [])
    if not unprocessed:
        return False

    logger.warning(f"{len(unprocessed)} unprocessed record(s); retrying once")
    retry_kwargs: Dict[str, Any] = {"UsageRecords": unprocessed}
    if use_product_code:
        retry_kwargs["ProductCode"] = PRODUCT_CODE
    retry_response = mp_client.batch_meter_usage(**retry_kwargs)
    _capture_results(retry_response, key_by_identity, outcomes)

    still_unprocessed = list(retry_response.get("UnprocessedRecords", []) or [])
    if still_unprocessed:
        logger.error(
            f"{len(still_unprocessed)} record(s) still unprocessed after retry; "
            "left pending for the next run"
        )
        emf_metric("UsageRecordUnprocessed", len(still_unprocessed))
        return True
    return False


def _capture_results(response, key_by_identity, outcomes):
    for result in response.get("Results", []):
        rec = result.get("UsageRecord", {})
        gk = key_by_identity.get(_identity(rec))
        if gk is not None:
            outcomes[gk] = {
                "MeteringRecordId": result.get("MeteringRecordId"),
                "Status": result.get("Status", ""),
            }
        observe_status(result.get("Status", ""), rec)


def _is_transient(code):
    return code in ("ThrottlingException", "InternalServiceException", "ServiceUnavailable")


def _identity(record):
    return (
        record.get("LicenseArn") or record.get("CustomerIdentifier") or "",
        record.get("CustomerAWSAccountId", ""),
        record.get("Dimension", ""),
        _ts_iso(record.get("Timestamp")),
    )


def _ts_iso(ts):
    # Hour bucket is always UTC. If a tz-aware datetime is passed, CONVERT it to UTC before
    # formatting (a non-UTC datetime would otherwise bucket in the wrong hour); a naive
    # datetime is assumed to already be UTC (the documented writer contract).
    if isinstance(ts, datetime):
        if ts.tzinfo is not None:
            ts = ts.astimezone(timezone.utc)
        return ts.strftime(HOUR_FMT)
    return str(ts)[:13]


def observe_status(status, rec):
    # Per-record Results[].Status from BatchMeterUsage is only Success / CustomerNotSubscribed /
    # DuplicateRecord. An invalid/undefined dimension is NOT a per-record status — it is a
    # REQUEST-level InvalidUsageDimensionException that fails the whole call and is isolated in
    # _submit (see there), so it is NOT handled here.
    if status in ("Success", "DuplicateRecord"):
        if status == "DuplicateRecord":
            emf_metric("DuplicateRecord", 1)
        return
    logger.warning(
        f"Metering status={status} account={mask(rec.get('CustomerAWSAccountId', ''))} "
        f"dimension={rec.get('Dimension', 'unknown')}"
    )
    if status == "CustomerNotSubscribed":
        emf_metric("CustomerNotSubscribed", 1)


# ─── Subscriber deprovisioning set (sparse-index query) ──────────────────────
# NOTE: finalization (deprovisioning -> inactive) is NOT done here or by the submitter — a
# license may have usage across multiple hours/regions, so it is owned by the events-stack
# deprovision_cleanup Lambda, which finalizes once the ~1h flush window (deprovisioningExpiry)
# has elapsed. This module only exposes the ACTIVE deprovisioning set for expediting.
def deprovisioning_licenses() -> set:
    """Return the set of licenseArns currently in a deprovisioning flush window.

    Queries the sparse ``deprovisioning-pending-index`` by its constant HASH flag — the
    index holds ONLY licenses the subscription Lambda marked on `License Deprovisioned` and
    has not yet finalized, so this is O(deprovisioning-count) and never a Scan. Used by the
    discoverer's flush-deprovisioning sweep and by the submitter's deprovisioning-first
    prioritization.
    """
    licenses = set()
    kwargs = {
        "IndexName": DEPROVISIONING_PENDING_INDEX,
        "KeyConditionExpression": "deprovisioningPendingFlag = :v",
        "ExpressionAttributeValues": {":v": DEPROVISIONING_PENDING_VALUE},
    }
    while True:
        response = subscribers_table.query(**kwargs)
        for item in response.get("Items", []):
            arn = item.get("licenseArn")
            if arn:
                licenses.add(arn)
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return licenses


def deprovisioning_licenses_with_expiry() -> dict:
    """Return ``{licenseArn: deprovisioningExpiry}`` for licenses currently in a deprovisioning window.

    Same sparse-index Query as ``deprovisioning_licenses`` but keeps each license's
    ``deprovisioningExpiry`` (= the deprovision event time + ~1h, the window-close instant; it is
    the index RANGE key, always projected) so the flush sweep can decide whether the license's
    CURRENT hour is within the last ~10 min before the window closes and should be flushed.
    O(deprovisioning-count), never a Scan.
    """
    out = {}
    kwargs = {
        "IndexName": DEPROVISIONING_PENDING_INDEX,
        "KeyConditionExpression": "deprovisioningPendingFlag = :v",
        "ExpressionAttributeValues": {":v": DEPROVISIONING_PENDING_VALUE},
    }
    while True:
        response = subscribers_table.query(**kwargs)
        for item in response.get("Items", []):
            arn = item.get("licenseArn")
            if arn:
                out[arn] = item.get("deprovisioningExpiry")
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return out


# ─── Small helpers ───────────────────────────────────────────────────────────
def strict_int(value):
    """Return int(value) ONLY if value is an exact integer; None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        d = Decimal(str(value))
        return int(d) if d == d.to_integral_value() else None
    except Exception:
        return None


def quantity_reason(raw):
    """Classify why a raw quantity is not a valid non-negative integer."""
    try:
        Decimal(str(raw))
        return "NonIntegerQuantity"
    except Exception:
        return "NonNumericQuantity"


def mask(identifier):
    s = str(identifier or "")
    return "***" if len(s) <= 6 else f"{s[:3]}***{s[-3:]}"


def emf_metric(name, value, reason=None, exception=None):
    """Emit a business-status metric via CloudWatch Embedded Metric Format (EMF).

    Each metric that a ``GROUP BY`` widget/alarm consumes is emitted on a SINGLE dimension set
    that carries the grouped key + MeteringMode, so it stays filterable/groupable
    (WHERE ProductCode / GROUP BY Reason|Exception) WITHOUT being double-counted (emitting the
    same value on both a bare and a MeteringMode-bearing set would make a ``GROUP BY`` query sum
    both series ~2x):
    - ``reason`` (UsageRecordRejected): [Reason, MeteringMode, ProductCode]. No bare, reason-less
      [ProductCode] series, so the ``GROUP BY Reason`` widget shows no spurious "Other" series
      (every rejection has a reason). The UsageRecordRejected alarm sums this via Metrics Insights.
    - ``exception`` (BatchMeterUsageException): [Exception, MeteringMode, ProductCode] so the
      request-level BatchMeterUsage exceptions (InvalidUsageDimensionException,
      TimestampOutOfBoundsException, InvalidTagException, InvalidProductCodeException,
      InvalidLicenseException, ...) are plotted per exception type (alarm sums via Metrics Insights).
    - otherwise (CustomerNotSubscribed, DuplicateRecord, UsageAggregationExpired,
      UsageSubmissionExpired, UsageRecordUnprocessed, DryRunSubmitted, ...): emitted on the bare
      [ProductCode] set — these are consumed by PLAIN metric alarms/widgets on the [ProductCode]
      dimension (no GROUP BY), so there is no "Other"/double-count concern and dropping the bare
      series would leave those alarms with no datapoints (silently never firing).
    """
    if name == "UsageRecordRejected" and reason:
        dimensions = [["Reason", "MeteringMode", "ProductCode"]]
        fields = {"Reason": reason, "ProductCode": PRODUCT_CODE, "MeteringMode": METERING_MODE, name: value}
    elif name == "BatchMeterUsageException" and exception:
        dimensions = [["Exception", "MeteringMode", "ProductCode"]]
        fields = {"Exception": exception, "ProductCode": PRODUCT_CODE, "MeteringMode": METERING_MODE, name: value}
    else:
        dimensions = [["ProductCode"]]
        fields = {"ProductCode": PRODUCT_CODE, name: value}
    emf = {
        "_aws": {
            "Timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": METRIC_NAMESPACE,
                    "Dimensions": dimensions,
                    "Metrics": [{"Name": name, "Unit": "Count"}],
                }
            ],
        },
        **fields,
    }
    print(json.dumps(emf))


# ─── aggregated_usage keys ───────────────────────────────────────────────────
def agg_sort_key(account_id: str, dimension: str, hour_bucket: str) -> str:
    """Sort key for the aggregated_usage table: ``account#dimension#hour``."""
    return f"{account_id}#{dimension}#{hour_bucket}"


# ─── Bounded, throttle-guarded per-row writes (shared by cleanup + reject) ────
import random  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: E402

DDB_MAX_WORKERS = int(os.environ.get("CLEANUP_MAX_WORKERS", "16"))
DDB_MAX_RETRIES = int(os.environ.get("CLEANUP_MAX_RETRIES", "5"))
_THROTTLE_CODES = (
    "ProvisionedThroughputExceededException",
    "ThrottlingException",
    "RequestLimitExceeded",
)

# boto3 RESOURCE objects (like the module-level ``usage_table``) are NOT thread-safe and
# must not be shared across threads — only low-level clients are. The concurrent per-row
# writers below therefore use a per-thread resource Table (created lazily, once per worker
# thread) rather than the shared module-level one. This keeps the ergonomic
# ``.update_item(**kwargs)`` call (native Python types, no manual attribute-value
# marshalling) while being thread-safe.
_thread_local = threading.local()


def _tl_usage_table():
    tbl = getattr(_thread_local, "usage_table", None)
    if tbl is None:
        tbl = boto3.resource("dynamodb").Table(os.environ["USAGE_TABLE"])
        _thread_local.usage_table = tbl
    return tbl


def update_item_with_backoff(license_arn, sort_key, update_expr, values, names=None):
    """One raw-usage-row UpdateItem with exponential backoff on per-partition throttling.

    All rows of a group share the ``licenseArn`` partition, so a burst hits ONE partition
    (~1000 WCU/s). This retries throttling with full-jitter backoff; a non-throttle error
    (or exhausted retries) raises so the caller can fail the SQS message (redelivery/DLQ).
    Runs on a worker thread, so it uses a THREAD-LOCAL resource Table (boto3 resources are
    not thread-safe), never the shared module-level ``usage_table``.
    """
    # Audit timestamps: stamp updatedAt on every write + createdAt-once (the seller's writer owns the
    # raw row's original createdAt; if_not_exists preserves it, else this sets it here).
    update_expr, values, names = with_audit_timestamps(update_expr, values or {}, names)
    kwargs: Dict[str, Any] = {
        "Key": {
            "licenseArn": license_arn,
            "customerAWSAccountId_dimension_timestamp": sort_key,
        },
        "UpdateExpression": update_expr,
    }
    if values:  # a REMOVE-only expression has no values; DynamoDB rejects an empty map
        kwargs["ExpressionAttributeValues"] = values
    if names:
        kwargs["ExpressionAttributeNames"] = names
    attempt = 0
    while True:
        try:
            _tl_usage_table().update_item(**kwargs)
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in _THROTTLE_CODES and attempt < DDB_MAX_RETRIES:
                time.sleep(min(2 ** attempt, 8) * (0.5 + random.random() / 2))
                attempt += 1
                continue
            raise


def update_rows_bounded(license_arn, sort_keys, update_expr, values, names=None):
    """Apply ``update_item_with_backoff`` to many rows of one license via a BOUNDED thread
    pool (guards the shared-partition WCU limit per invocation). Raises if any row fails
    after retries, listing how many failed — the caller fails the message (redelivery/DLQ),
    never a silent drop."""
    errors = []
    with ThreadPoolExecutor(max_workers=DDB_MAX_WORKERS) as pool:
        futures = {
            pool.submit(update_item_with_backoff, license_arn, sk, update_expr, values, names): sk
            for sk in sort_keys
            if sk
        }
        for fut in as_completed(futures):
            exc = fut.exception()
            if exc is not None:
                errors.append(exc)
    if errors:
        raise RuntimeError(
            f"{len(errors)}/{len(sort_keys)} UpdateItem(s) failed for "
            f"license={mask(license_arn)}; first error: {type(errors[0]).__name__}"
        )
