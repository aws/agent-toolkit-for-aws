"""Framework-agnostic x402 payment tool for AgentCore Payments.

Copy this file into your agent project and register `x402_fetch` as a tool in
whatever framework you use (Strands, LangGraph, OpenAI Agents SDK, etc.). The
core logic is pure Python with no framework dependency.

Flow:
  request -> detect 402 -> PaymentManager.generate_payment_header (the SDK
  validates the 402, selects the network, processes the payment, and builds the
  version-aware v1/v2 proof header) -> retry with a fresh client.

Transient settlement: the SDK builds a valid header, but the merchant's
on-chain settlement is occasionally transient and the paid retry still returns
402. The SDK does not make the merchant HTTP call (it only builds the header),
so it cannot retry that — this tool re-runs the settle+replay flow up to
X402_MAX_PAYMENT_ATTEMPTS times before giving up. A single idempotency token
(client_token) is reused across all attempts of one fetch, so ProcessPayment is
idempotent: every retry replays the SAME on-chain authorization/nonce. That
recovers a not-yet-settled transient failure, and if the merchant actually did
settle but still returned 402, the replay simply reverts on-chain (nonce already
used) rather than charging the user a second time.

Control-plane resources (payment manager/connector) are created by the AgentCore
CLI; the per-user instrument/session are created by setup_payment_user.py. This
tool only consumes them, via these environment variables:

  PAYMENT_MANAGER_ARN        payment manager ARN      (from deployed-state.json)
  PAYMENT_INSTRUMENT_ID      per-user wallet ID       (from setup_payment_user.py)
  PAYMENT_SESSION_ID         per-conversation session (from setup_payment_user.py)
  PAYMENT_USER_ID            end-user identity        (required)
  AWS_REGION                 region                   (default us-west-2)
  X402_MAX_PAYMENT_ATTEMPTS  transient-402 retry cap  (default 5)
"""
import ipaddress
import json
import os
import socket
import uuid
from urllib.parse import urlparse

import httpx
from bedrock_agentcore.payments import PaymentManager

PAYMENT_MANAGER_ARN = os.getenv("PAYMENT_MANAGER_ARN")
PAYMENT_INSTRUMENT_ID = os.getenv("PAYMENT_INSTRUMENT_ID")
PAYMENT_SESSION_ID = os.getenv("PAYMENT_SESSION_ID")
PAYMENT_USER_ID = os.environ.get("PAYMENT_USER_ID")  # required — no insecure default
REGION = os.getenv("AWS_REGION", "us-west-2")
# Transient on-chain settlement can leave the paid retry at 402 even though the
# header was valid; re-settle (fresh header + idempotency token) up to this many times.
MAX_PAYMENT_ATTEMPTS = int(os.getenv("X402_MAX_PAYMENT_ATTEMPTS", "5"))

# AgentCore Payments data-plane client (SDK). Created when configured.
_manager = PaymentManager(payment_manager_arn=PAYMENT_MANAGER_ARN, region_name=REGION) if PAYMENT_MANAGER_ARN else None


def _validate_url(url):
    """Return an error string if the URL is not HTTPS or targets a private/internal IP."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "Only HTTPS URLs are supported for payment requests"
    try:
        for _family, _, _, _, sockaddr in socket.getaddrinfo(parsed.hostname, parsed.port or 443):
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return "Cannot fetch private/internal network addresses"
    except socket.gaierror:
        return "Cannot resolve hostname"
    return None


def _settle_and_retry(url, method, response, client_token):
    """Build the payment header from a 402 response via the SDK, then replay the request.

    The SDK's generate_payment_header does the whole settle workflow (validate the
    402, pick the network, ProcessPayment, build the v1 `X-PAYMENT` / v2
    `PAYMENT-SIGNATURE` proof) and returns {header_name: header_value}. We pass a
    STABLE client_token (the same one for every attempt of a single fetch) so
    ProcessPayment is idempotent — each retry replays the same authorization/nonce
    and can never double-charge.
    Returns the retry httpx.Response. Raises on a header-generation failure.
    """
    payment_header = _manager.generate_payment_header(
        payment_instrument_id=PAYMENT_INSTRUMENT_ID,
        payment_session_id=PAYMENT_SESSION_ID,
        user_id=PAYMENT_USER_ID,
        client_token=client_token,
        payment_required_request={
            "statusCode": response.status_code,
            "headers": dict(response.headers),
            "body": response.text,
        },
    )
    # Retry with a FRESH client so cookies from the 402 response don't contaminate it.
    with httpx.Client(verify=True) as client:
        return client.request(method, url, headers=payment_header, timeout=30)


def x402_fetch(url, method="GET"):
    """Fetch a URL, automatically settling any x402 402 Payment Required response.

    Returns a JSON string with status_code, body, and (on payment) payment_made.
    """
    url_error = _validate_url(url)
    if url_error:
        return json.dumps({"error": url_error})
    if not PAYMENT_USER_ID:
        return json.dumps({"error": "PAYMENT_USER_ID environment variable is required"})

    response = httpx.request(method, url, timeout=30)
    if response.status_code != 402:
        return json.dumps({"status_code": response.status_code, "body": response.text})

    if not _manager:
        return json.dumps({
            "status_code": 402,
            "error": "No payment configuration. Set PAYMENT_MANAGER_ARN.",
            "body": response.text,
        })

    # One idempotency token for the whole fetch: every retry replays the SAME
    # authorization/nonce, so a transient 402 can be re-settled without ever double-charging.
    client_token = str(uuid.uuid4())
    for attempt in range(1, MAX_PAYMENT_ATTEMPTS + 1):
        try:
            retry_response = _settle_and_retry(url, method, response, client_token)
        except Exception as e:  # noqa: BLE001 - surface any payment failure (incl. typed SDK errors) to the agent
            return json.dumps({"status_code": 402, "error": f"Payment header generation failed: {e}"})

        if retry_response.status_code != 402:
            # Success (2xx) or a non-transient error — return it; payment_made reflects the actual status.
            return json.dumps({
                "status_code": retry_response.status_code,
                "body": retry_response.text,
                "payment_made": 200 <= retry_response.status_code < 300,
                "payment_attempts": attempt,
            })

        # Transient post-payment 402 — retry with the same idempotency token (same
        # authorization/nonce), giving settlement another chance without double-charging.
        response = retry_response

    return json.dumps({
        "status_code": 402,
        "error": f"Paid and retried {MAX_PAYMENT_ATTEMPTS} times but the merchant still returned 402 "
                 "(transient on-chain settlement). Try again shortly.",
        "body": response.text,
        "payment_made": False,
        "payment_attempts": MAX_PAYMENT_ATTEMPTS,
    })
