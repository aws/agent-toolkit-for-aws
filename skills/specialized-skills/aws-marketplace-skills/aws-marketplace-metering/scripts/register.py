import json
import logging
import os
import urllib.parse

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource(
    "dynamodb", region_name=os.environ.get("SUBSCRIBERS_TABLE_REGION", "us-east-1")
)
subscribers_table = dynamodb.Table(os.environ["SUBSCRIBERS_TABLE"])
mp_client = boto3.client("meteringmarketplace", region_name="us-east-1")

# In-region customer-profile table (buyer PII). Uses the Lambda's OWN region (no region_name
# override) so PII stays in-region — never written to the us-east-1 subscribers table.
_dynamodb_local = boto3.resource("dynamodb")
_CUSTOMER_PROFILE_TABLE = os.environ.get("CUSTOMER_PROFILE_TABLE")
customer_profile_table = (
    _dynamodb_local.Table(_CUSTOMER_PROFILE_TABLE) if _CUSTOMER_PROFILE_TABLE else None
)

PRODUCT_CODE = os.environ["PRODUCT_CODE"]
MAX_TOKEN_LENGTH = 16384

# Subset of ALLOWED_REGISTRATION_FIELDS the seller PROMOTED to top-level attributes on the
# customer-profile table (each has a matching GSI). Promoted fields are written BOTH into the
# registrationData map AND as a top-level attribute so a GSI can look profiles up by them.
PROMOTED_PROFILE_FIELDS = [
    f.strip() for f in os.environ.get("PROMOTED_PROFILE_FIELDS", "").split(",") if f.strip()
]

# The AWS Region this register Lambda runs in — added to the subscriber row's
# registeredRegions String Set (BatchMeterUsage is regional, so a buyer may be resolved in
# multiple regions). Lambda sets AWS_REGION automatically.
INVOCATION_REGION = os.environ.get("AWS_REGION", "")

# Registration input allowlist + bounds. The endpoint is public and unauthenticated, so
# only these named fields are persisted, each length-bounded, up to a max field count.
# TODO(seller): set ALLOWED_REGISTRATION_FIELDS (comma-separated) to YOUR form fields.
ALLOWED_REGISTRATION_FIELDS = [
    f.strip() for f in os.environ.get("ALLOWED_REGISTRATION_FIELDS", "").split(",") if f.strip()
]
MAX_REGISTRATION_FIELDS = int(os.environ.get("MAX_REGISTRATION_FIELDS", "20"))
MAX_FIELD_VALUE_LENGTH = int(os.environ.get("MAX_FIELD_VALUE_LENGTH", "512"))


def _mask(value):
    """Mask a sensitive identifier for logging (ILER-R1a): keep only the last 4 chars.
    Buyer account IDs / license ARNs are sensitive and MUST NOT be logged in full."""
    if not value:
        return "<none>"
    s = str(value)
    return "****" + s[-4:] if len(s) > 4 else "****"


def _stamp(update_expr, values):
    """Append createdAt(once)/updatedAt audit stamps to a SET UpdateExpression (createdAt once, updatedAt every write)."""
    from datetime import datetime, timezone

    values = dict(values)
    values[":now"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"{update_expr}, createdAt = if_not_exists(createdAt, :now), updatedAt = :now",
        values,
    )


def handler(event, context):
    """Handle buyer registration: resolve the fulfillment token, upsert the subscriber.

    Flow:
    1. Buyer clicks "Set up your account" in AWS Marketplace after subscribing.
    2. AWS Marketplace POSTs to our registration URL with x-amzn-marketplace-token.
    3. We call ResolveCustomer to get CustomerAWSAccountId + LicenseArn (+ ProductCode).
       The registration token is reusable until it expires (~4 hours), not one-time-use.
    4. We upsert the buyer's profile row in the IN-REGION customer-profile table, keyed by
       licenseArn + customerAWSAccountId — ALWAYS (a registered buyer has an in-region profile
       even with no extra form fields), setting productCode plus, when the seller collected
       allowlisted fields, the registrationData map + any promoted top-level fields. We upsert
       the PII-FREE subscriber row (us-east-1) with only productCode + this Lambda's AWS Region
       appended to registeredRegions (idempotent). NO registration PII is written to the
       subscribers table.

    registeredRegions is reference-only and NEVER gates metering (metering is driven by
    the usage table's metering_pending GSI). CustomerIdentifier is a deprecated legacy
    field and is NOT persisted for a new integration.

    Note: this script is for NEW skill-generated integrations. For an EXISTING seller
    integration, do NOT use this script — read the seller's existing registration code
    and adapt guidance to it.
    """
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        import base64

        body = base64.b64decode(body).decode("utf-8")

    if not body or len(body) > MAX_TOKEN_LENGTH:
        return _response(400, {"error": "Invalid request body"})

    form = urllib.parse.parse_qs(body)
    token = form.get("x-amzn-marketplace-token", [None])[0]

    if not token or not token.strip():
        return _response(400, {"error": "Missing x-amzn-marketplace-token"})

    try:
        result = mp_client.resolve_customer(RegistrationToken=token)
    except mp_client.exceptions.ExpiredTokenException:
        return _response(
            400,
            {
                "error": "Registration token expired. Please return to AWS Marketplace and "
                "click Set up your account again."
            },
        )
    except mp_client.exceptions.InvalidTokenException:
        return _response(400, {"error": "Invalid registration token"})
    except Exception as e:
        logger.error(f"ResolveCustomer failed: {type(e).__name__}")
        return _response(500, {"error": "Failed to resolve customer. Please try again."})

    customer_aws_account_id = result.get("CustomerAWSAccountId")
    license_arn = result.get("LicenseArn")
    product_code = result.get("ProductCode")

    if not customer_aws_account_id or not product_code:
        logger.error("ResolveCustomer response missing required fields")
        return _response(500, {"error": "Failed to resolve customer. Please try again."})

    if product_code != PRODUCT_CODE:
        logger.error(f"Product code mismatch: received={product_code} expected={PRODUCT_CODE}")
        return _response(400, {"error": "Product code mismatch"})

    if not license_arn:
        # A Concurrent Agreements ResolveCustomer returns a LicenseArn. Without one we
        # cannot key the subscriber row by the real licenseArn; surface the error rather
        # than inventing a placeholder. (A `License Updated` event will create the row.)
        logger.error(
            f"ResolveCustomer returned no LicenseArn for account={_mask(customer_aws_account_id)}; "
            "cannot persist a keyed subscriber row (a License Updated event will create it)"
        )
        return _response(
            200,
            {"message": "Registration received; your account is being activated."},
        )

    # 1) Buyer profile → the IN-REGION customer-profile table, keyed by the resolved
    #    identity (licenseArn + customerAWSAccountId). We ALWAYS upsert this row — a buyer that
    #    registered has an in-region profile record even if the seller collected no extra form
    #    fields — and additionally set the registrationData map + any promoted top-level fields
    #    WHEN there are allowlisted fields to store. Never written to the us-east-1 subscribers table.
    registration_data = _extract_registration_fields(form)
    if customer_profile_table is None:
        # No profile store configured. In this reference (new-stack) handler the template always
        # sets CUSTOMER_PROFILE_TABLE, so this indicates a misconfiguration — fail loud (500)
        # rather than silently skip persisting the buyer's in-region profile. (An EXISTING
        # seller's own handler may store registration data differently — the skill adapts to
        # that; this reference script is not used verbatim there.)
        logger.error("CUSTOMER_PROFILE_TABLE not configured; cannot persist buyer profile")
        return _response(500, {"error": "Registration store not configured. Please try again."})

    # Always stamp productCode + the invocation Region on the profile row (identity/reference
    # metadata, not PII). Set registrationData + promoted fields only when the seller has
    # allowlisted fields to store.
    profile_expr = "SET productCode = :pc"
    profile_values = {":pc": product_code}
    profile_names = {}
    if registration_data:
        # Use INDEX-based expression tokens (not the raw field name) so a promoted field whose
        # name contains characters invalid in an expression token (e.g. a hyphen or space) does
        # not break the UpdateItem. Each promoted field is written both into the registrationData
        # map (:rd) AND as its own top-level attribute (via #n{i}) so its GSI can index it.
        profile_expr += ", registrationData = :rd"
        profile_values[":rd"] = registration_data
        for i, field in enumerate(PROMOTED_PROFILE_FIELDS):
            if field in registration_data:
                name_tok = f"#n{i}"
                val_tok = f":v{i}"
                profile_expr += f", {name_tok} = {val_tok}"
                profile_names[name_tok] = field
                profile_values[val_tok] = registration_data[field]
    profile_expr, profile_values = _stamp(profile_expr, profile_values)
    kwargs = {
        "Key": {"licenseArn": license_arn, "customerAWSAccountId": customer_aws_account_id},
        "UpdateExpression": profile_expr,
        "ExpressionAttributeValues": profile_values,
    }
    if profile_names:
        kwargs["ExpressionAttributeNames"] = profile_names
    customer_profile_table.update_item(**kwargs)

    # 2) Subscribers row (us-east-1) — PII-FREE: only the non-PII productCode + the
    #    idempotent registeredRegions append. NO registration form data is written here.
    # registeredRegions is a DynamoDB String Set (SS). `ADD` on a set is atomic and idempotent
    # (a no-op if the region is already present), so concurrent/retried registrations for the
    # same buyer + region can never duplicate an entry — no read-then-write, no get_item.
    update_expr = "SET productCode = :pc"
    values = {":pc": product_code}
    if INVOCATION_REGION:
        update_expr += " ADD registeredRegions :region"
        values[":region"] = {INVOCATION_REGION}  # Python set -> DynamoDB String Set

    update_expr, values = _stamp(update_expr, values)
    subscribers_table.update_item(
        Key={"licenseArn": license_arn, "customerAWSAccountId": customer_aws_account_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=values,
    )

    logger.info(
        f"Registered customer account={_mask(customer_aws_account_id)} region={INVOCATION_REGION} "
        f"(PII → in-region customer-profile table; subscribers row PII-free)"
    )

    return _response(
        200,
        {"message": "Registration successful. Your account is being activated."},
    )


def _extract_registration_fields(form):
    """Extract ALLOWLISTED custom registration form fields.

    The registration endpoint is public and unauthenticated, so we do NOT persist
    arbitrary caller-supplied fields. We persist only the fields named in the
    ALLOWED_REGISTRATION_FIELDS env var (comma-separated), and enforce per-field length
    and total field-count bounds. Unknown/oversized fields are dropped, not written
    verbatim to DynamoDB. The token is never persisted.

    TODO(seller): configure ALLOWED_REGISTRATION_FIELDS to match your registration form,
    e.g. "company_name,email,team_size". If unset, no custom fields are persisted.
    """
    registration_data: dict[str, str] = {}
    if not ALLOWED_REGISTRATION_FIELDS:
        return registration_data
    count = 0
    for key in ALLOWED_REGISTRATION_FIELDS:
        if count >= MAX_REGISTRATION_FIELDS:
            break
        values = form.get(key)
        if not values:
            continue
        value = values[0]  # single-valued only; ignore repeated params
        if not isinstance(value, str):
            continue
        if len(value) > MAX_FIELD_VALUE_LENGTH:
            logger.warning(f"Registration field '{key}' exceeds max length; truncating")
            value = value[:MAX_FIELD_VALUE_LENGTH]
        registration_data[key] = value
        count += 1
    return registration_data


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        },
        "body": json.dumps(body),
    }
