# Python: `fiat-extension-for-x402`

## Contents

- [Install](#install)
- [FastAPI next to an existing network](#fastapi-next-to-an-existing-network)
- [FastAPI with aws:base only](#fastapi-with-awsbase-only)
- [Flask](#flask)
- [Bring-your-own key](#bring-your-own-key)
- [Accept each payment once](#accept-each-payment-once)
- [DPoP replay store](#dpop-replay-store)
- [AWS Lambda](#aws-lambda)

## Install

```bash
pip install "fiat-extension-for-x402>=1.0.1" "x402[fastapi]"   # or "x402[flask]"; keep x402[evm] etc. if already used
```

Install the latest release; 1.0.1 is the minimum (the first that signs and requires the scheme and network claims). pip resolves a compatible `x402` 2.x; see the PyPI page for supported Python versions.

## FastAPI next to an existing network

The seller already protects `GET /weather` with USDC on Base through a remote facilitator. Lines marked `# added` are the whole change:

```python
from fastapi import FastAPI
from x402 import x402Facilitator, x402ResourceServer
from x402.http import FacilitatorConfig, HTTPFacilitatorClient
from x402.http.middleware.fastapi import payment_middleware
from x402.http.types import PaymentOption, RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme

from fiat_extension_x402 import (  # added
    AgenticCommerceVerifier,
    KmsQuoteSigner,
    KmsQuoteSignerConfig,
    KmsSellerKeyResolver,
    register_exact_agentic_commerce_facilitator,
    register_exact_agentic_commerce_server,
)

KEY_ARN = "arn:aws:kms:us-east-1:111122223333:alias/my-quote-key"  # added: the listing's key
SERVICE_URL = "https://api.example.com"                            # added: the listing's endpoint URL
EXISTING_FACILITATOR_URL = "https://facilitator.example.com"       # existing: your current facilitator

signer = KmsQuoteSigner(  # added
    KmsQuoteSignerConfig(key_arn=KEY_ARN, region="us-east-1", service_url=SERVICE_URL)
)
verifier = AgenticCommerceVerifier(  # added
    seller_key_resolver=KmsSellerKeyResolver(KEY_ARN, "us-east-1")
)
aws_facilitator = register_exact_agentic_commerce_facilitator(  # added
    x402Facilitator(), verifier=verifier
)

server = x402ResourceServer([
    HTTPFacilitatorClient(FacilitatorConfig(url=EXISTING_FACILITATOR_URL)),  # existing
    aws_facilitator,                                                                # added
])
server.register("eip155:*", ExactEvmServerScheme())               # existing
register_exact_agentic_commerce_server(server, signer=signer)     # added: aws:base

routes = {
    "GET /weather": RouteConfig(
        accepts=[
            PaymentOption(scheme="exact", network="eip155:8453",     # existing
                          pay_to="0xYourWallet", price="$0.01"),
            PaymentOption(scheme="exact", network="aws:base",        # added
                          pay_to="prod-example123", price="$0.01",
                          extra={"description": "Current weather", "reference": "weather-v1"}),
        ],
        description="Current weather",
    ),
}

app = FastAPI()


@app.get("/weather")
def weather() -> dict[str, object]:
    return {"temperature_f": 58}


app.middleware("http")(payment_middleware(routes, server))
```

x402 core maps each facilitator client to the networks and schemes it advertises; when two advertise the same pair, the earlier one in the list wins. The remote facilitator advertises `eip155:*`, the in-process facilitator advertises `aws:base`.

## FastAPI with aws:base only

A seller with no other network passes the in-process facilitator alone:

```python
facilitator = register_exact_agentic_commerce_facilitator(x402Facilitator(), verifier=verifier)
server = register_exact_agentic_commerce_server(x402ResourceServer(facilitator), signer=signer)
```

## Flask

Flask's middleware is synchronous, so every x402 object **MUST** be the `Sync` variant, since the async ones cannot run inside Flask's request cycle:

```python
from flask import Flask
from x402 import x402FacilitatorSync, x402ResourceServerSync
from x402.http import FacilitatorConfig, HTTPFacilitatorClientSync
from x402.http.middleware.flask import payment_middleware

# signer, verifier and routes as in the FastAPI example
aws_facilitator = register_exact_agentic_commerce_facilitator(x402FacilitatorSync(), verifier=verifier)
server = x402ResourceServerSync([
    HTTPFacilitatorClientSync(FacilitatorConfig(url=EXISTING_FACILITATOR_URL)),  # existing
    aws_facilitator,
])
server.register("eip155:*", ExactEvmServerScheme())  # existing
register_exact_agentic_commerce_server(server, signer=signer)

app = Flask(__name__)


@app.get("/weather")
def weather() -> dict[str, object]:
    return {"temperature_f": 58}


payment_middleware(app, routes, server)
```

Flask answers `HEAD` with the `GET` view, and x402 matches methods exactly, so an unpaid `HEAD /weather` runs the view. You **MUST** key paid Flask routes `"* /weather"` (every method pays) instead of `"GET /weather"`. FastAPI refuses `HEAD` on a `GET` route with `405`, so it needs no change.

## Bring-your-own key

Replace the KMS signer and resolver when the listing has a JWKS URL:

```python
from pathlib import Path

from fiat_extension_x402 import JwksSellerKeyResolver, LocalQuoteSigner, jwks_document

signer = LocalQuoteSigner.from_pem(
    Path("/run/secrets/quote-key.pem").read_bytes(),
    kid="quote-key-1",
    service_url=SERVICE_URL,
)
verifier = AgenticCommerceVerifier(seller_key_resolver=JwksSellerKeyResolver(SERVICE_URL))


@app.get("/.well-known/jwks.json")  # not a paid route
def jwks() -> dict[str, list[dict[str, object]]]:
    return jwks_document(signer.public_jwk)
```

`JwksSellerKeyResolver` takes the base URL and appends `/.well-known/jwks.json`. Key rules are in [seller-keys.md](seller-keys.md).

## Accept each payment once

Verification is stateless: the facilitator accepts the same payment token on every request until the token or its quote expires. Add an after-verify hook that records the verified payment token's `payment_id` and refuses one already recorded. x402 runs hooks registered with `on_after_verify` for **every** payment, on every network and also when verification failed, so the hook **MUST** skip anything that is not a valid `aws:base` payment, because recording an unverified token would let a forged one block a real payment:

```python
import base64
import json
import time

from x402.schemas import AbortResult

SKEW_SECONDS = 60


def _claims(token: str) -> dict:
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


class MemoryPaymentStore:
    """Single-process only. Behind several instances, use a shared store instead."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def claim(self, payment_id: str, expires_at: int) -> bool:
        """Record the id; False if it is already recorded and unexpired."""
        now = time.time()
        self._seen = {k: v for k, v in self._seen.items() if v > now}
        if payment_id in self._seen:
            return False
        self._seen[payment_id] = expires_at
        return True


def accept_each_payment_once(store):
    async def hook(context):
        if context.requirements.network != "aws:base" or not context.result.is_valid:
            return None
        # The payment token the facilitator has just verified. Never key on a paymentId
        # elsewhere in the payload: the buyer sets it and nothing checks it.
        token = _claims(context.payment_payload.payload["paymentToken"])
        quote = _claims(token["quote_token"])
        expires_at = max(int(token["exp"]), int(quote["exp"])) + SKEW_SECONDS
        if not store.claim(str(token["payment_id"]), expires_at):
            return AbortResult(reason="payment_replayed", message="Payment already used")
        return None

    return hook


server.on_after_verify(accept_each_payment_once(MemoryPaymentStore()))
```

With Flask (`x402ResourceServerSync`), make `hook` a plain `def`.

Behind several instances, every instance **MUST** share the record. Ask the seller which shared store they use, and implement `claim` on it as an atomic "insert if absent or expired" (for example a conditional write in their database or cache), so two instances cannot both accept the same `payment_id`. If `claim` is a blocking call, run it from the async hook with `await asyncio.to_thread(store.claim, payment_id, expires_at)` so it does not stall the event loop. If the seller has no shared store, tell them replay protection is not in place across instances.

## DPoP replay store

Pass a store to the server scheme. A store implements `has(jti) -> bool` and `add(jti, expires_at) -> None`; `has` **MUST** return `True` for an id until its `expires_at` (Unix seconds):

```python
import time


class MemoryNonceStore:
    """Single-process only. Behind several instances, use a shared store instead."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def has(self, jti: str) -> bool:
        expires_at = self._seen.get(jti)
        return expires_at is not None and time.time() < expires_at

    def add(self, jti: str, expires_at: int) -> None:
        now = time.time()
        self._seen = {k: v for k, v in self._seen.items() if v > now}
        self._seen[jti] = expires_at


register_exact_agentic_commerce_server(server, signer=signer, dpop_nonce_store=MemoryNonceStore())
```

For several instances, back `has`/`add` with the seller's shared store, using an atomic conditional write. A store that records the id inside `has` (an atomic check-and-set) **MUST** give it its own expiry of about 70 seconds, because `add` is not called when a payment is refused after `has`.

## AWS Lambda

With Mangum, x402's FastAPI middleware needs the ASGI `raw_path`, which Mangum does not set:

```python
from typing import Any
from urllib.parse import quote

from mangum import Mangum


def with_raw_path(asgi_app: Any) -> Any:
    async def wrapped(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http" and not scope.get("raw_path"):
            scope = {**scope, "raw_path": quote(scope["path"]).encode("ascii")}
        await asgi_app(scope, receive, send)

    return wrapped


handler = Mangum(with_raw_path(app), lifespan="off")
```

The function's role needs `kms:Sign` and `kms:GetPublicKey` granted on the key's **key ARN** (`key/<id>`), not its alias ARN — see [seller-keys.md](seller-keys.md). `SERVICE_URL` **MUST** be the endpoint URL registered on the listing, and the URL x402 sees for each request **MUST** be the public one buyers call, since DPoP proofs are bound to it.
