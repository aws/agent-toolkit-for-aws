# Agent Wiring Code

Once the developer confirms delegation and funding are done, **modify their existing agent code** to add a custom x402-aware fetch tool.

**Find the agent's entrypoint file** (e.g., `main.py`, `app.py`, or the file containing the `Agent(...)` constructor). Based on the framework detected in Step 1, use the appropriate pattern below.

> **Why a custom tool instead of the AgentCorePaymentsPlugin?**
> The `AgentCorePaymentsPlugin` works by intercepting tool results via an
> `after_tool_call` hook. It only works when the tool surfaces the full HTTP
> response. Many tools do not expose response headers where the x402 challenge
> often lives.
>
> The custom `x402_fetch` tool handles the full flow internally:
> request → detect 402 → extract challenge (body OR header) → ProcessPayment →
> build proof → retry with fresh client → return content.
>
> **Critical: Use a fresh httpx client for the retry.** Some merchants set cookies
> on the 402 response that cause the retry to fail if sent back.
>
> **Version-aware proof.** The tool reads `x402Version` from the challenge and
> builds the matching proof: v1 sends an `X-PAYMENT` header with a flat proof
> (top-level `scheme`/`network`), v2 sends a `PAYMENT-SIGNATURE` header where
> `accepted` is a top-level sibling of `payload` and `payload` holds only
> `signature` + `authorization` (no top-level `scheme`/`network`). The
> `ProcessPayment` input is the same for both (always CAIP-2 network); only the
> proof presented to the merchant differs.

## Core Payment Logic (shared across all frameworks)

```python
import os
import json
import base64
import httpx
import boto3

# Payment configuration from environment
PAYMENT_MANAGER_ARN = os.getenv("PAYMENT_MANAGER_ARN")
PAYMENT_INSTRUMENT_ID = os.getenv("PAYMENT_INSTRUMENT_ID")
PAYMENT_SESSION_ID = os.getenv("PAYMENT_SESSION_ID")
PAYMENT_USER_ID = os.environ.get("PAYMENT_USER_ID")  # Required — no insecure default
REGION = os.getenv("AWS_REGION", "us-west-2")

# AgentCore Payments data plane client
_dp_client = boto3.client("bedrock-agentcore", region_name=REGION) if PAYMENT_MANAGER_ARN else None


def _validate_url(url: str) -> str | None:
    """Validate URL is HTTPS and not targeting private/internal networks."""
    from urllib.parse import urlparse
    import ipaddress
    import socket

    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "Only HTTPS URLs are supported for payment requests"

    # Resolve hostname and block private/internal IP ranges
    try:
        addrinfos = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
        for family, _, _, _, sockaddr in addrinfos:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return "Cannot fetch private/internal network addresses"
    except socket.gaierror:
        return "Cannot resolve hostname"

    return None


def _x402_fetch_impl(url: str, method: str = "GET") -> str:
    """Fetch a URL with automatic x402 payment handling.

    If the endpoint returns 402 Payment Required with an x402 challenge,
    automatically processes the payment and retries with proof.
    """
    # Validate URL (HTTPS-only, no private IPs)
    url_error = _validate_url(url)
    if url_error:
        return json.dumps({"error": url_error})

    # Validate PAYMENT_USER_ID is set
    if not PAYMENT_USER_ID:
        return json.dumps({"error": "PAYMENT_USER_ID environment variable is required"})

    # NOTE: Payment Sessions enforce service-level budget and time limits
    # (expiryTimeInMinutes). Keep sessions short-lived to bound spending.

    # First attempt
    response = httpx.request(method, url, timeout=30)

    if response.status_code != 402:
        return json.dumps({
            "status_code": response.status_code,
            "body": response.text
        })

    # --- Got 402: Extract x402 challenge ---
    x402_challenge = None

    # Try response body first (standard x402 v1 style)
    try:
        body_json = response.json()
        if "x402Version" in body_json and "accepts" in body_json:
            x402_challenge = body_json
    except Exception:
        pass

    # Fall back to payment-required header (base64-encoded)
    if not x402_challenge:
        header_val = response.headers.get("payment-required")
        if header_val:
            try:
                x402_challenge = json.loads(base64.b64decode(header_val))
            except Exception:
                pass

    if not x402_challenge:
        return json.dumps({
            "status_code": 402,
            "error": "Payment required but no x402 challenge found",
            "body": response.text
        })

    # --- Call ProcessPayment ---
    if not _dp_client or not PAYMENT_MANAGER_ARN:
        return json.dumps({
            "status_code": 402,
            "error": "Payment required but no payment configuration available. Set PAYMENT_MANAGER_ARN env var.",
            "x402_challenge": x402_challenge
        })

    accepts = x402_challenge["accepts"][0]
    try:
        payment_response = _dp_client.process_payment(
            paymentManagerArn=PAYMENT_MANAGER_ARN,
            paymentInstrumentId=PAYMENT_INSTRUMENT_ID,
            paymentSessionId=PAYMENT_SESSION_ID,
            userId=PAYMENT_USER_ID,
            paymentType="CRYPTO_X402",
            paymentInput={
                "cryptoX402": {
                    "version": str(x402_challenge.get("x402Version", "1")),
                    "payload": {
                        "scheme": accepts.get("scheme", "exact"),
                        "network": accepts["network"],
                        "amount": accepts.get("amount", accepts.get("maxAmountRequired", "0")),
                        "asset": accepts["asset"],
                        "payTo": accepts["payTo"],
                        "maxTimeoutSeconds": accepts.get("maxTimeoutSeconds", 60),
                        **({"extra": accepts["extra"]} if "extra" in accepts else {})
                    }
                }
            }
        )
    except Exception as e:
        return json.dumps({
            "status_code": 402,
            "error": f"ProcessPayment failed: {e}"
        })

    # --- Build the payment header proof (version-aware) ---
    # ProcessPayment input above is identical for v1 and v2 (always CAIP-2).
    # Only the proof presented to the merchant differs by x402 version.
    crypto_output = payment_response["paymentOutput"]["cryptoX402"]
    auth = crypto_output["payload"]["authorization"]
    x402_version = int(x402_challenge.get("x402Version", 1))

    authorization = {
        "from": auth["from"],
        "to": auth["to"],
        "value": auth["value"],
        "validAfter": auth["validAfter"],
        "validBefore": auth["validBefore"],
        "nonce": auth["nonce"]
    }

    if x402_version >= 2:
        # x402 v2: header is PAYMENT-SIGNATURE. `accepted` is a TOP-LEVEL sibling
        # of `payload` (echoing the merchant's accepted entry, CAIP-2 network).
        # `payload` holds ONLY signature + authorization. There are NO top-level
        # scheme/network fields. This matches the Coinbase facilitator
        # x402V2PaymentPayload schema.
        proof = {
            "x402Version": 2,
            "accepted": {
                "scheme": accepts.get("scheme", "exact"),
                "network": accepts["network"],
                "amount": accepts.get("amount", accepts.get("maxAmountRequired", "0")),
                "asset": accepts["asset"],
                "payTo": accepts["payTo"],
                "maxTimeoutSeconds": accepts.get("maxTimeoutSeconds", 60),
                **({"extra": accepts["extra"]} if "extra" in accepts else {})
            },
            "payload": {
                "signature": crypto_output["payload"]["signature"],
                "authorization": authorization
            }
        }
        # Optionally echo the resource block from the challenge if present.
        if "resource" in x402_challenge:
            proof["resource"] = x402_challenge["resource"]
        payment_header_name = "PAYMENT-SIGNATURE"
    else:
        # x402 v1: header is X-PAYMENT, proof is flat (top-level scheme/network).
        proof = {
            "x402Version": 1,
            "scheme": "exact",
            "network": accepts["network"],
            "payload": {
                "signature": crypto_output["payload"]["signature"],
                "authorization": authorization
            }
        }
        payment_header_name = "X-PAYMENT"

    payment_header = base64.b64encode(
        json.dumps(proof, separators=(',', ':')).encode()
    ).decode()

    # --- Retry with payment proof (fresh client to avoid cookie contamination) ---
    with httpx.Client(verify=True) as client:
        retry_response = client.request(
            method, url,
            headers={payment_header_name: payment_header},
            timeout=30
        )

    # payment_made reflects the actual retry status — a 2xx means the merchant
    # accepted the proof. Do NOT hardcode this True: ProcessPayment can succeed
    # (proof generated) while the retry still returns 402 (e.g. wrong proof
    # shape, expired proof, or an on-chain settlement failure).
    return json.dumps({
        "status_code": retry_response.status_code,
        "body": retry_response.text,
        "payment_made": 200 <= retry_response.status_code < 300,
        "process_payment_id": payment_response.get("processPaymentId", "unknown")
    })
```

## Strands — tool decorator pattern

```python
from strands import Agent, tool

@tool
def x402_fetch(url: str, method: str = "GET") -> str:
    """Fetch a URL with automatic x402 payment handling.

    If the endpoint returns 402 Payment Required with an x402 challenge,
    this tool automatically processes the payment and retries with proof.

    Args:
        url: The URL to fetch
        method: HTTP method (GET, POST, etc.)
    """
    return _x402_fetch_impl(url, method)

agent = Agent(
    model="<model_id>",
    tools=[x402_fetch],
    system_prompt=(
        "You are a helpful assistant that can access paid APIs and content. "
        "Use the x402_fetch tool to access URLs that may require payment — "
        "it handles x402 payments automatically."
    ),
)
```

## LangGraph — tool pattern

```python
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langchain_aws import ChatBedrock

@tool
def x402_fetch(url: str, method: str = "GET") -> str:
    """Fetch a URL with automatic x402 payment handling.

    If the endpoint returns 402 Payment Required with an x402 challenge,
    this tool automatically processes the payment and retries with proof.

    Args:
        url: The URL to fetch
        method: HTTP method (GET, POST, etc.)
    """
    return _x402_fetch_impl(url, method)

model = ChatBedrock(model_id="<model_id>", region_name=REGION)
graph = create_react_agent(model, tools=[x402_fetch])

# Invoke:
result = graph.invoke({"messages": [("human", "Fetch https://paid-api.example.com/data")]})
print(result["messages"][-1].content)
```

## OpenAI Agents SDK — function_tool pattern

```python
from agents import Agent, Runner, function_tool

@function_tool
def x402_fetch(url: str, method: str = "GET") -> str:
    """Fetch a URL with automatic x402 payment handling.

    If the endpoint returns 402 Payment Required with an x402 challenge,
    this tool automatically processes the payment and retries with proof.

    Args:
        url: The URL to fetch
        method: HTTP method (GET, POST, etc.)
    """
    return _x402_fetch_impl(url, method)

agent = Agent(
    name="PaymentAgent",
    instructions=(
        "You are a helpful assistant that can access paid APIs and content. "
        "Use the x402_fetch tool to access URLs that may require payment — "
        "it handles x402 payments automatically."
    ),
    tools=[x402_fetch],
)

# Invoke:
import asyncio
result = asyncio.run(Runner.run(agent, "Fetch https://paid-api.example.com/data"))
print(result.final_output)
```

## Other Frameworks

If the developer's framework is not listed above, they can call `_x402_fetch_impl()` directly from whatever tool/function mechanism their framework provides. The core logic is pure Python with no framework dependencies.
