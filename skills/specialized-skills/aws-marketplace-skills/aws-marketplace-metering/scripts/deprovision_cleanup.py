"""Deprovision cleanup Lambda (events stack, us-east-1).

Fired by an EventBridge Scheduler rate(15 minutes). Finalizes licenses whose ~1-hour
post-deprovision flush window has closed: it Queries the sparse deprovisioning-pending-index
for entries whose ``deprovisioningExpiry <= now`` and, for each, sets
``subscriptionStatus = inactive`` and REMOVEs both deprovisioning markers
(``deprovisioningPendingFlag`` + ``deprovisioningExpiry``) so the row drops out of the index.

Why a time-based cleanup owns finalization (not the submitter):
  * A deprovisioning license may have usage across MULTIPLE hours and MULTIPLE regions
    (one submitter per metering region, one shared subscribers table in us-east-1). No single
    submitter run can know the license is fully drained, so a submitter-driven flip to
    ``inactive`` would fire prematurely on the first region/hour submitted.
  * The flush window is absolute (~1h after the deprovision event). Once it has elapsed, no
    region can meter the license anymore (BatchMeterUsage returns CustomerNotSubscribed), so a
    single time-based finalize in us-east-1 is correct for all regions at once — no cross-region
    coordination.

Idempotent: the finalize UpdateItem is conditioned on the marker still being present, so
concurrent/duplicate runs do not clobber a row that was already finalized or re-deprovisioned.
"""

import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
subscribers_table = dynamodb.Table(os.environ["SUBSCRIBERS_TABLE"])


def _mask(value):
    """Mask a sensitive identifier for logging: keep only the last 4 chars. Buyer account IDs /
    license ARNs are sensitive and MUST NOT be logged in full (mirrors register.py._mask)."""
    if not value:
        return "<none>"
    s = str(value)
    return "****" + s[-4:] if len(s) > 4 else "****"

DEPROVISIONING_PENDING_INDEX = "deprovisioning-pending-index"
DEPROVISIONING_PENDING_VALUE = "1"  # constant HASH of the sparse index


def handler(event, context):
    """Finalize every deprovisioning license whose flush window has elapsed."""
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    finalized = 0
    kwargs = {
        "IndexName": DEPROVISIONING_PENDING_INDEX,
        # flag = constant HASH, deprovisioningExpiry = RANGE: everything already expired.
        "KeyConditionExpression": (
            "deprovisioningPendingFlag = :f AND deprovisioningExpiry <= :now"
        ),
        "ExpressionAttributeValues": {":f": DEPROVISIONING_PENDING_VALUE, ":now": now_iso},
    }
    while True:
        response = subscribers_table.query(**kwargs)
        for item in response.get("Items", []):
            finalized += _finalize(item)
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    logger.info(f"Deprovision cleanup: finalized {finalized} expired license(s) as inactive")
    return {"finalized": finalized}


def _finalize(item):
    """Set subscriptionStatus=inactive and REMOVE both deprovisioning markers, idempotently."""
    license_arn = item.get("licenseArn", "")
    account_id = item.get("customerAWSAccountId", "")
    if not license_arn or not account_id:
        return 0
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        subscribers_table.update_item(
            Key={"licenseArn": license_arn, "customerAWSAccountId": account_id},
            UpdateExpression=(
                # updatedAt goes in the SET clause (row already exists, so createdAt is kept);
                # REMOVE follows the full SET clause per DynamoDB expression syntax.
                "SET subscriptionStatus = :inactive, updatedAt = :now "
                "REMOVE deprovisioningPendingFlag, deprovisioningExpiry"
            ),
            # Only finalize while the marker is still present — makes concurrent/duplicate
            # runs (and a row re-deprovisioned in the meantime) safe.
            ConditionExpression="attribute_exists(deprovisioningPendingFlag)",
            ExpressionAttributeValues={":inactive": "inactive", ":now": now},
        )
        logger.info(
            f"Finalized deprovisioning->inactive for licenseArn={_mask(license_arn)} (window elapsed)"
        )
        return 1
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        # Already finalized by a concurrent run (or re-deprovisioned) — nothing to do.
        return 0
