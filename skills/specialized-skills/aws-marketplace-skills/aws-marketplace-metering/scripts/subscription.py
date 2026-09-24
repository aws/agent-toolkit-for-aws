import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
subscribers_table = dynamodb.Table(os.environ["SUBSCRIBERS_TABLE"])

# Sparse deprovisioning index markers. On License Deprovisioned the handler writes a constant
# `deprovisioningPendingFlag` (HASH) and a `deprovisioningExpiry` (RANGE) = event time + the
# flush window, so the events-stack cleanup Lambda can Query flag='1' AND expiry<=now to
# finalize expired licenses, while the main-stack sweep/submitter Query flag='1' for the
# active set. Kept in sync with metering_core.DEPROVISIONING_PENDING_VALUE (subscription.py
# runs in the events stack and does not import metering_core).
DEPROVISIONING_PENDING_VALUE = "1"
DEPROVISIONING_FLUSH_WINDOW = timedelta(hours=1)  # AWS Marketplace ~1h post-deprovision window


def _mask(value):
    """Mask a sensitive identifier for logging: keep only the last 4 chars. Buyer account IDs /
    license ARNs are sensitive and MUST NOT be logged in full (mirrors register.py._mask)."""
    if not value:
        return "<none>"
    s = str(value)
    return "****" + s[-4:] if len(s) > 4 else "****"


def _stamp(update_expr, values):
    """Append createdAt(once)/updatedAt audit stamps to a SET UpdateExpression (createdAt once, updatedAt every write)."""
    values = dict(values)
    values[":now"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"{update_expr}, createdAt = if_not_exists(createdAt, :now), updatedAt = :now",
        values,
    )


def handler(event, context):
    """Process EventBridge marketplace events from SQS into the unified subscribers table.

    Returns partial batch failures so only the failed message is retried (requires the
    event source mapping to set FunctionResponseTypes: ReportBatchItemFailures).
    """
    batch_item_failures = []
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
        except (json.JSONDecodeError, KeyError):
            logger.error("Invalid SQS message body, skipping (not retried)")
            continue

        try:
            if "detail-type" in body:
                _process_event(body)
            else:
                logger.warning("Unknown message format, skipping")
        except Exception:
            logger.exception("Failed to process record")
            batch_item_failures.append({"itemIdentifier": record.get("messageId", "")})

    return {"batchItemFailures": batch_item_failures}


def _process_event(event):
    """Route an EventBridge event to the appropriate handler.

    The subscriber row carries TWO independent status fields that this handler owns and
    MUST NOT conflate:

      * agreementStatus  (active | inactive)  — the AGREEMENT lifecycle.
      * subscriptionStatus (active | deprovisioning | inactive) — the LICENSE lifecycle.

    Metering DECISIONS are driven only by the license lifecycle:
      * `License Updated`      -> access granted/refreshed (agreement + subscription active).
      * `License Deprovisioned`-> access revoked; opens the ~1-hour final-usage flush
                                   window (subscriptionStatus = deprovisioning + a
                                   deprovisioningExpiry). The events-stack deprovision-cleanup
                                   Lambda sets it inactive once the window has elapsed.

    `Purchase Agreement Ended` and `Purchase Agreement Amended` update AGREEMENT status /
    metadata ONLY — they do NOT stop metering or trigger a flush. `Purchase Agreement
    Created` is intentionally NOT consumed (it carries no licenseArn and is not needed to
    meter); sellers who need it add their own rule/target — see
    references/architecture.md ("Purchase Agreement Created — seller use cases").
    """
    detail_type = event.get("detail-type", "")
    detail = event.get("detail", {})
    logger.info(f"EventBridge event: {detail_type}")

    if "License Updated" in detail_type:
        _handle_license_updated(detail)
    elif "License Deprovisioned" in detail_type:
        _handle_license_deprovisioned(detail, event.get("time"))
    elif "Purchase Agreement Ended" in detail_type:
        _handle_agreement_ended(detail)
    elif "Purchase Agreement Amended" in detail_type:
        _handle_agreement_amended(detail)
    elif "Purchase Agreement Created" in detail_type:
        # Not consumed by the metering path (no licenseArn; not needed to meter).
        # Logged only for observability. See references/architecture.md for how sellers
        # can use this event for other use cases (pre-provisioning, CRM sync, etc.).
        logger.info("Purchase Agreement Created received; not used by metering path (ignored)")


def _handle_license_updated(detail):
    """`License Updated` — the canonical event that provides the LicenseArn and
    establishes/refreshes the buyer's access. Upsert the subscriber row (keyed by the
    real licenseArn) and set BOTH agreementStatus and subscriptionStatus to active.
    """
    acceptor_account_id = detail.get("acceptor", {}).get("accountId", "")
    agreement_id = detail.get("agreement", {}).get("id", "")
    license_arn = detail.get("license", {}).get("arn", "")
    product_code = detail.get("product", {}).get("code", "")

    if not acceptor_account_id or not license_arn:
        logger.error("Missing acceptorAccountId or licenseArn in License Updated event")
        return

    key = {"licenseArn": license_arn, "customerAWSAccountId": acceptor_account_id}
    metadata_values = {":pc": product_code, ":aid": agreement_id, ":active": "active"}

    # EventBridge delivery is at-least-once and may be reordered, so a late/duplicate
    # `License Updated` could arrive AFTER `License Deprovisioned`. Only move
    # subscriptionStatus to `active` when it is absent or already `active`, so we never
    # resurrect a `deprovisioning`/`inactive` license and re-open metering for a revoked
    # buyer. agreementStatus + metadata are always refreshed.
    try:
        _mv = dict(metadata_values)
        _mv[":now"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        subscribers_table.update_item(
            Key=key,
            UpdateExpression=(
                "SET productCode = :pc, agreementId = :aid, "
                "agreementStatus = :active, subscriptionStatus = :active, "
                "createdAt = if_not_exists(createdAt, :now), updatedAt = :now"
            ),
            ConditionExpression=(
                "attribute_not_exists(subscriptionStatus) OR subscriptionStatus = :active"
            ),
            ExpressionAttributeValues=_mv,
        )
    except subscribers_table.meta.client.exceptions.ConditionalCheckFailedException:
        # Row is deprovisioning/inactive — refresh agreement metadata but do NOT reactivate.
        subscribers_table.update_item(
            Key=key,
            UpdateExpression=(
                "SET productCode = :pc, agreementId = :aid, agreementStatus = :active, "
                "createdAt = if_not_exists(createdAt, :now), updatedAt = :now"
            ),
            ExpressionAttributeValues=_mv,
        )
        logger.warning(
            "License Updated arrived for a non-active subscription "
            f"(account={_mask(acceptor_account_id)} licenseArn={_mask(license_arn)}); refreshed agreement "
            "metadata but left subscriptionStatus unchanged (not reactivating a revoked license)."
        )
        return
    logger.info(f"License updated (active): account={_mask(acceptor_account_id)} licenseArn={_mask(license_arn)}")


def _deprovisioning_expiry(event_time):
    """ISO-8601 UTC timestamp when the ~1h flush window closes: event time + window.

    Uses the EventBridge event `time` when available (the authoritative moment the license
    was deprovisioned), else falls back to now. The events-stack cleanup Lambda finalizes a
    license once this instant has passed.
    """
    base = None
    if event_time:
        try:
            base = datetime.fromisoformat(str(event_time).replace("Z", "+00:00"))
        except ValueError:
            base = None
    if base is None:
        base = datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return (base + DEPROVISIONING_FLUSH_WINDOW).astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _handle_license_deprovisioned(detail, event_time=None):
    """`License Deprovisioned` — access revoked. Opens the ~1-hour final-usage flush window.

    Sets subscriptionStatus = deprovisioning and marks the row in the sparse
    deprovisioning-pending-index (constant `deprovisioningPendingFlag` HASH + a
    `deprovisioningExpiry` = event time + ~1h RANGE). During the window the main-stack
    expedited sweep + submitter flush this license immediately (bypassing MeteringLockHours).
    Once `deprovisioningExpiry` has passed, the events-stack cleanup Lambda finalizes the
    license (deprovisioning -> inactive) and removes both markers. Finalization is NOT done by
    the submitter, because a license may have usage across multiple hours and regions and no
    single submitter run can know it is fully drained.

    Reference:
    https://docs.aws.amazon.com/marketplace/latest/userguide/saas-eventbridge-integration.html
    """
    acceptor_account_id = detail.get("acceptor", {}).get("accountId", "")
    license_arn = detail.get("license", {}).get("arn", "")

    if not license_arn:
        agreement_id = detail.get("agreement", {}).get("id", "")
        license_arn = _resolve_license_arn(agreement_id)

    if not acceptor_account_id or not license_arn:
        logger.error("Cannot resolve subscriber for License Deprovisioned event")
        return

    expiry = _deprovisioning_expiry(event_time)
    _dep_expr, _dep_vals = _stamp(
        "SET subscriptionStatus = :s, deprovisioningPendingFlag = :f, deprovisioningExpiry = :exp",
        {":s": "deprovisioning", ":f": DEPROVISIONING_PENDING_VALUE, ":exp": expiry},
    )
    subscribers_table.update_item(
        Key={
            "licenseArn": license_arn,
            "customerAWSAccountId": acceptor_account_id,
        },
        UpdateExpression=_dep_expr,
        ExpressionAttributeValues=_dep_vals,
    )
    logger.info(
        "License deprovisioned (final-usage flush window open until "
        f"{expiry}): account={_mask(acceptor_account_id)} licenseArn={_mask(license_arn)} "
        "subscriptionStatus=deprovisioning"
    )


def _handle_agreement_ended(detail):
    """`Purchase Agreement Ended` — a STATUS update only. Set agreementStatus = inactive.

    This does NOT change subscriptionStatus, stop metering, or trigger a flush: the buyer
    may still be entitled to usage until the license is deprovisioned. The flush window
    is opened by `License Deprovisioned`, not by this event.
    """
    acceptor_account_id = detail.get("acceptor", {}).get("accountId", "")
    license_arn = detail.get("license", {}).get("arn", "")

    if not license_arn:
        agreement_id = detail.get("agreement", {}).get("id", "")
        license_arn = _resolve_license_arn(agreement_id)

    if not acceptor_account_id or not license_arn:
        logger.error("Cannot resolve subscriber for Purchase Agreement Ended event")
        return

    _end_expr, _end_vals = _stamp("SET agreementStatus = :inactive", {":inactive": "inactive"})
    subscribers_table.update_item(
        Key={
            "licenseArn": license_arn,
            "customerAWSAccountId": acceptor_account_id,
        },
        UpdateExpression=_end_expr,
        ExpressionAttributeValues=_end_vals,
    )
    logger.info(
        "Purchase Agreement Ended (agreement status only; metering unaffected): "
        f"account={_mask(acceptor_account_id)} licenseArn={_mask(license_arn)} agreementStatus=inactive"
    )


def _handle_agreement_amended(detail):
    """`Purchase Agreement Amended` — update agreement metadata only (does not change
    subscriptionStatus or stop metering). The agreement remains active on an amendment.
    """
    acceptor_account_id = detail.get("acceptor", {}).get("accountId", "")
    agreement = detail.get("agreement", {})
    license_arn = detail.get("license", {}).get("arn", "")

    if not license_arn:
        agreement_id = agreement.get("id", "")
        license_arn = _resolve_license_arn(agreement_id)

    if not acceptor_account_id or not license_arn:
        logger.error("Cannot resolve subscriber for Purchase Agreement Amended event")
        return

    _amd_expr, _amd_vals = _stamp(
        "SET endTime = :et, agreementStatus = :active",
        {":et": agreement.get("endTime", ""), ":active": "active"},
    )
    subscribers_table.update_item(
        Key={
            "licenseArn": license_arn,
            "customerAWSAccountId": acceptor_account_id,
        },
        UpdateExpression=_amd_expr,
        ExpressionAttributeValues=_amd_vals,
    )
    logger.info(f"Agreement amended: account={_mask(acceptor_account_id)} licenseArn={_mask(license_arn)}")


def _resolve_license_arn(agreement_id):
    """Resolve licenseArn from agreementId via the agreementId GSI (Query, NOT a Scan),
    used when an Agreement Ended/Amended/Deprovisioned event omits license.arn.

    A genuinely-missing row returns "" (the caller logs and the message is retried/DLQ'd),
    but permission/config errors (AccessDenied etc.) are NOT swallowed as "not found" —
    they propagate so the handler's broad except records a batch-item failure (retry ->
    DLQ alarm) rather than silently leaving the subscriber unchanged.
    """
    if not agreement_id:
        return ""

    response = subscribers_table.query(
        IndexName="agreementId-index",
        KeyConditionExpression="agreementId = :agr",
        ExpressionAttributeValues={":agr": agreement_id},
        Limit=1,
    )
    items = response.get("Items", [])
    if items:
        return items[0].get("licenseArn", "")
    return ""
