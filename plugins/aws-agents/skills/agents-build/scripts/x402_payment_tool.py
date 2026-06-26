"""Framework-agnostic x402 payment tool for AgentCore Payments.

Copy this file into your agent project and register `x402_fetch` as a tool in
whatever framework you use (Strands, LangGraph, OpenAI Agents SDK, etc.). The
core logic is pure Python with no framework dependency.

It handles the full flow internally:
  request -> detect 402 -> extract x402 challenge (body OR header) ->
  ProcessPayment -> build version-aware proof -> retry with a fresh client.

The merchant's on-chain settlement can be transient: ProcessPayment succeeds but
the paid retry still returns 402. The tool re-runs the full settle flow (fresh
challenge + nonce each pass) up to X402_MAX_PAYMENT_ATTEMPTS times before giving up.

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
import base64
import ipaddress
import json
import os
import socket
from urllib.parse import urlparse

import httpx
from bedrock_agentcore.payments import PaymentManager

PAYMENT_MANAGER_ARN = os.getenv("PAYMENT_MANAGER_ARN")
PAYMENT_INSTRUMENT_ID = os.getenv("PAYMENT_INSTRUMENT_ID")
PAYMENT_SESSION_ID = os.getenv("PAYMENT_SESSION_ID")
PAYMENT_USER_ID = os.environ.get("PAYMENT_USER_ID")  # required — no insecure default
REGION = os.getenv("AWS_REGION", "us-west-2")
# Transient on-chain settlement can leave the paid retry at 402 even though
# ProcessPayment succeeded; re-settle (fresh challenge + nonce) up to this many times.
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


def _extract_challenge(response):
    """Pull the x402 challenge from a 402 response body, or the payment-required header."""
    try:
        body_json = response.json()
        if "x402Version" in body_json and "accepts" in body_json:
            return body_json
    except Exception:
        pass
    header_val = response.headers.get("payment-required")
    if header_val:
        try:
            return json.loads(base64.b64decode(header_val))
        except Exception:
            pass
    return None


def _settle_and_retry(url, method, x402_challenge):
    """ProcessPayment for one challenge, build the version-aware proof, retry the request.

    Returns (retry_response, process_payment_id). Raises on a ProcessPayment failure.
    """
    # --- ProcessPayment via the AgentCore SDK (input is identical for v1 and v2 — always CAIP-2) ---
    accepts = x402_challenge["accepts"][0]
    payment_response = _manager.process_payment(
        payment_session_id=PAYMENT_SESSION_ID,
        payment_instrument_id=PAYMENT_INSTRUMENT_ID,
        payment_type="CRYPTO_X402",
        user_id=PAYMENT_USER_ID,
        payment_input={
            "cryptoX402": {
                "version": str(x402_challenge.get("x402Version", "1")),
                "payload": {
                    "scheme": accepts.get("scheme", "exact"),
                    "network": accepts["network"],
                    "amount": accepts.get("amount", accepts.get("maxAmountRequired", "0")),
                    "asset": accepts["asset"],
                    "payTo": accepts["payTo"],
                    "maxTimeoutSeconds": accepts.get("maxTimeoutSeconds", 60),
                    **({"extra": accepts["extra"]} if "extra" in accepts else {}),
                },
            }
        },
    )

    # --- Build the version-aware proof header ---
    crypto_output = payment_response["paymentOutput"]["cryptoX402"]
    auth = crypto_output["payload"]["authorization"]
    authorization = {
        "from": auth["from"], "to": auth["to"], "value": auth["value"],
        "validAfter": auth["validAfter"], "validBefore": auth["validBefore"], "nonce": auth["nonce"],
    }
    if int(x402_challenge.get("x402Version", 1)) >= 2:
        # v2: PAYMENT-SIGNATURE header; `accepted` is a top-level sibling of `payload`;
        # `payload` holds only signature + authorization (no top-level scheme/network).
        proof = {
            "x402Version": 2,
            "accepted": {
                "scheme": accepts.get("scheme", "exact"),
                "network": accepts["network"],
                "amount": accepts.get("amount", accepts.get("maxAmountRequired", "0")),
                "asset": accepts["asset"],
                "payTo": accepts["payTo"],
                "maxTimeoutSeconds": accepts.get("maxTimeoutSeconds", 60),
                **({"extra": accepts["extra"]} if "extra" in accepts else {}),
            },
            "payload": {"signature": crypto_output["payload"]["signature"], "authorization": authorization},
        }
        if "resource" in x402_challenge:
            proof["resource"] = x402_challenge["resource"]
        payment_header_name = "PAYMENT-SIGNATURE"
    else:
        # v1: X-PAYMENT header; flat proof (top-level scheme/network).
        proof = {
            "x402Version": 1,
            "scheme": "exact",
            "network": accepts["network"],
            "payload": {"signature": crypto_output["payload"]["signature"], "authorization": authorization},
        }
        payment_header_name = "X-PAYMENT"

    payment_header = base64.b64encode(json.dumps(proof, separators=(",", ":")).encode()).decode()

    # Retry with a FRESH client so cookies from the 402 response don't contaminate it.
    with httpx.Client(verify=True) as client:
        retry_response = client.request(method, url, headers={payment_header_name: payment_header}, timeout=30)
    return retry_response, payment_response.get("processPaymentId", "unknown")


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
            "x402_challenge": _extract_challenge(response),
        })

    last_process_payment_id = "unknown"
    # Re-settle on a transient post-payment 402 (fresh challenge + nonce each pass).
    for attempt in range(1, MAX_PAYMENT_ATTEMPTS + 1):
        x402_challenge = _extract_challenge(response)
        if not x402_challenge:
            return json.dumps({"status_code": 402, "error": "No x402 challenge found", "body": response.text})

        try:
            retry_response, last_process_payment_id = _settle_and_retry(url, method, x402_challenge)
        except Exception as e:  # noqa: BLE001 - surface any payment failure (incl. typed SDK errors) to the agent
            return json.dumps({"status_code": 402, "error": f"ProcessPayment failed: {e}"})

        if retry_response.status_code != 402:
            # Success (2xx) or a non-transient error — return it; payment_made reflects the actual status.
            return json.dumps({
                "status_code": retry_response.status_code,
                "body": retry_response.text,
                "payment_made": 200 <= retry_response.status_code < 300,
                "process_payment_id": last_process_payment_id,
                "payment_attempts": attempt,
            })

        # Transient post-payment 402 — re-extract the fresh challenge and settle again.
        response = retry_response

    return json.dumps({
        "status_code": 402,
        "error": f"Paid and retried {MAX_PAYMENT_ATTEMPTS} times but the merchant still returned 402 "
                 "(transient on-chain settlement). Try again shortly.",
        "body": response.text,
        "payment_made": False,
        "process_payment_id": last_process_payment_id,
        "payment_attempts": MAX_PAYMENT_ATTEMPTS,
    })
