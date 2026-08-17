"""Trusted x402 fetch: settle a 402 and return metadata without leaking secrets.

Register `x402_fetch` as a tool in any Python framework. Everything
security-relevant happens in this process, never in the model's context:

  * The policy gate (x402_policy) decides whether to pay, before any signing.
  * The signed payment proof is attached to the outbound request and then
    discarded. It is never returned, logged, or shown to the model.
  * Provider credentials are never parameters — this module never touches them.
    Signing happens inside AgentCore Payments; only resource IDs live here.
  * Paid content is not returned into the model context. The tool returns only
    bounded metadata and a SHA-256 hash, so fetched instructions cannot become
    payment-capable instructions.

Configuration
-------------
Resource identifiers and the payment policy come from one operator-owned file,
~/.agents-pay/config.json. The runtime binds this path to the operating-system
account and ignores HOME, AGENTS_PAY_CONFIG, and X402_POLICY_FILE. Administrative
commands may use --path or AGENTS_PAY_CONFIG explicitly. The file holds no provider
credentials, only ARNs and IDs plus the limits. See x402_policy for its shape.

The config file takes precedence over the environment for every identifier. That
ordering is deliberate: the session ID names the budget being drawn down, so if a
variable could override the 0600 file, anything able to set that variable could
redirect spending to a larger session. The environment remains a fallback for
container and Lambda deployments with no writable home — a weaker mode, because
whatever sets the environment there chooses the session.

Region/resource-resolution fixes (see agents_pay_admin.py for the admin-side
half of this batch: resolve_region() and resolve_manager_arn() there fix the
same pattern for the admin CLI's config.json lookups)
-------------------------------------------------------------------------------
Three call sites in this file used to build PaymentManager with
`region_name=pol.resolve_resource(policy, "region") or "us-west-2"`. That
hardcoded fallback only fires when nothing configures a region anywhere — a
normal state for a deployment that relies on its AWS profile/IMDS region rather
than setting one explicitly — and PaymentManager already falls back to
boto3.Session().region_name internally before its own "us-west-2" default. So
forcing "us-west-2" here could send a real payment against the wrong AWS region
and fail with a confusing manager-not-found error. Fixed by passing
pol.resolve_resource(policy, "region") (or None) and letting boto3/PaymentManager
resolve it themselves. See payment_session_status(), prepare_browser_payment(),
and x402_fetch() below.

A related fix in x402_policy.derive_client_token() closes a second instance of
the same pattern: it read PAYMENT_SESSION_ID from the environment directly
whenever a caller omitted session_id, bypassing resolve_resource()'s documented
config-file-first precedence for a spending credential. See its docstring.

Tunables (behaviour only, never identifiers):

  X402_MAX_BODY_BYTES    response cap (default 262144, clamped 1 KiB - 64 MiB)
  X402_TIMEOUT_SECONDS   per-request timeout (default 20, clamped 1 - 120)

This module deliberately does NOT provide session creation or infrastructure
setup. Those are separate trusted paths with separate credentials, so a
compromised agent cannot mint budget or create payment resources.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import socket
import ssl
import time
from typing import Any
from urllib.parse import urlparse

import httpx

import x402_policy as pol

AGENT_NAME = "openclaw-aws-agents-pay"


def _bounded_env(name: str, default: float, minimum: float, maximum: float) -> float:
    """Read a numeric tunable, ignoring values that are invalid or out of range.

    Parsed defensively at import: a malformed value raising here would escape
    every handler and break the contract that x402_fetch never raises into the
    agent loop. A zero or negative limit would also silently disable the control,
    so values are clamped rather than trusted.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value < minimum or value > maximum:
        return default
    return value


# Cap between 1 KiB and 64 MiB; a 0/negative/garbage value falls back to default.
MAX_BODY_BYTES = int(_bounded_env("X402_MAX_BODY_BYTES", 256 * 1024, 1024, 64 * 1024 * 1024))
TIMEOUT_SECONDS = _bounded_env("X402_TIMEOUT_SECONDS", 20.0, 1.0, 120.0)
# Transient on-chain settlement can leave a paid retry at 402; replay the SAME
# authorization up to this many times. Bounded so a bad value cannot loop forever.
MAX_PAYMENT_ATTEMPTS = int(_bounded_env("X402_MAX_PAYMENT_ATTEMPTS", 5, 1, 10))

class PaymentBlocked(Exception):
    """Raised when trusted code refuses to pay or to fetch."""


def _require_resource(policy: dict, key: str) -> str:
    """Resolve a required resource identifier, config file first then environment.

    Config wins over the environment on purpose: the session ID names the budget
    being spent, so if a variable could override the 0600 file, anything able to
    set that variable could redirect spending to a larger session.
    """
    value = pol.resolve_resource(policy, key)
    if not value:
        env = pol.RESOURCE_ENV.get(key, key.upper())
        raise PaymentBlocked(
            f"Missing payment resource '{key}'. Add it to the config "
            f"(agents_pay_admin.py init-config) or set {env}. Provision resources "
            "with the trusted setup path first."
        )
    return value


def _ssl_context() -> ssl.SSLContext:
    """Strict TLS context: hostname checking and chain verification always on.

    Prefers certifi's CA bundle when present, because some hosts (including
    mise-managed Pythons) have no system CA file and would otherwise fail
    verification. Verification is never disabled — if no bundle is available the
    request fails closed rather than proceeding unverified.
    """
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


class _PinnedResolverTransport(httpx.HTTPTransport):
    """HTTP transport that only ever connects to a pre-vetted IP address.

    Closes the DNS-rebinding window. Validating a hostname and then letting the
    HTTP client resolve it again independently leaves a TOCTOU gap: the second
    lookup can return an internal address. Here resolution happens once, every
    answer is vetted, and the socket is opened directly to a vetted address.

    Implemented by overriding the connection pool's socket creation rather than
    by patching `socket.getaddrinfo`. Patching that global is not thread-safe —
    two concurrent fetches to different hosts can restore or observe each
    other's state, and a request can end up resolving *unpinned*, which silently
    reopens the very window this class exists to close.

    The URL keeps its real hostname, so SNI and certificate verification are
    unaffected; only the dialed address is fixed. (Rewriting the URL to a bare
    IP would break certificate validation.)
    """

    def __init__(self, pinned_ip: str, **kwargs):
        super().__init__(**kwargs)
        self._pinned_ip = pinned_ip
        pool = self._pool  # httpcore connection pool
        original_factory = pool._network_backend

        class _PinnedBackend:
            """Delegates to the real backend, forcing the destination address."""

            def __init__(self, backend, pinned: str):
                self._backend = backend
                self._pinned = pinned

            def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
                # Re-vet at connect time; the pin was vetted at resolve time too.
                pol.assert_public_ip(self._pinned)
                return self._backend.connect_tcp(
                    self._pinned, port, timeout=timeout,
                    local_address=local_address, socket_options=socket_options,
                )

            def __getattr__(self, name):
                return getattr(self._backend, name)

        pool._network_backend = _PinnedBackend(original_factory, pinned_ip)


def _resolve_and_vet(hostname: str, port: int) -> str:
    """Resolve once, reject if ANY answer is internal, return the address to pin."""
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise PaymentBlocked("Payment URL hostname does not resolve.") from None
    if not infos:
        raise PaymentBlocked("Payment URL hostname does not resolve.")
    for info in infos:
        pol.assert_public_ip(info[4][0])
    return infos[0][4][0]


#: Only side-effect-free verbs. A body-bearing request (POST/PUT/PATCH) would let the
#: agent push agent-chosen data to an arbitrary origin, which widens the very
#: exfiltration surface, and the policy gate validates the URL, not a request body.
#: Paid *retrieval* is what this skill is for.
_ALLOWED_METHODS = ("GET", "HEAD")


def _get(url: str, headers: dict[str, str] | None = None, method: str = "GET") -> httpx.Response:
    """One hardened HTTPS request: no redirects, pinned address, bounded body."""
    method = method.upper()
    if method not in _ALLOWED_METHODS:
        raise PaymentBlocked(
            f"Method {method} is not allowed; this skill fetches paid content with "
            f"{' or '.join(_ALLOWED_METHODS)}. A request body would let the agent send "
            "data to an arbitrary origin, which the policy gate does not validate."
        )
    parsed = urlparse(url)
    host, port = parsed.hostname or "", parsed.port or 443
    pinned_ip = _resolve_and_vet(host, port)

    transport = _PinnedResolverTransport(pinned_ip, verify=_ssl_context(), retries=0)

    request_headers = {
        "Accept": "application/json, text/plain",
        # Refuse compressed responses. httpx advertises gzip/deflate by default
        # and iter_bytes() yields DECOMPRESSED bytes, so a small compressed body
        # can expand by ~1000x and blow past the size cap before it is checked
        # (a decompression bomb against a payment-capable process).
        "Accept-Encoding": "identity",
    }
    if headers:
        request_headers.update(headers)

    with httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=min(5.0, TIMEOUT_SECONDS)),
        follow_redirects=False,  # a 30x is surfaced, never auto-followed
        max_redirects=0,
    ) as client:
        with client.stream(method, url, headers=request_headers) as response:
            # Reject an oversized body before reading any of it, when declared.
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
                raise PaymentBlocked(
                    f"Response declares {declared} bytes, over the {MAX_BODY_BYTES} limit."
                )

            body = bytearray()
            # Check BEFORE extending, so the buffer can never exceed the cap even
            # if a single chunk arrives larger than expected (e.g. a decompressing
            # transport). Small chunks also keep peak memory close to the cap.
            for chunk in response.iter_bytes(chunk_size=8192):
                if len(body) + len(chunk) > MAX_BODY_BYTES:
                    raise PaymentBlocked(
                        f"Response exceeded {MAX_BODY_BYTES} bytes; refusing to buffer more."
                    )
                body.extend(chunk)
            response.read_body = bytes(body)  # type: ignore[attr-defined]
            return response


def _body_text(response: httpx.Response) -> str:
    raw: bytes = getattr(response, "read_body", b"")
    return raw.decode(response.encoding or "utf-8", errors="replace")


def _safe_content(response: httpx.Response, policy: dict | None = None) -> dict[str, Any]:
    """Return metadata about paid content; optionally return the body.

    By default, paid publisher content is withheld from model context as a
    security control (it may contain prompt injection). Operators can opt in
    to body return by setting `return_body: true` in the policy section of
    the config file (~/.agents-pay/config.json). The config file is bound to
    the OS account (0600) and cannot be set by the model at runtime.
    """
    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    raw: bytes = getattr(response, "read_body", b"")
    result: dict[str, Any] = {
        "content_type": content_type or "unknown",
        "body_sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }
    return_body = (policy or {}).get("return_body") is True
    if return_body:
        result["body_returned"] = True
        result["body"] = raw.decode("utf-8", errors="replace")[:10240]
        result["truncated"] = len(raw) > 10240
        result["untrusted"] = True
    else:
        result["body_returned"] = False
        result["note"] = (
            "Body withheld: paid publisher content is untrusted and must not enter "
            "the payment-capable model context. Use a separate no-payment/no-network "
            "analysis context if summarisation is required. To opt in, set "
            "'return_body: true' in the policy section of the config file."
        )
    return result


def payment_session_status() -> str:
    """Report whether the configured payment session can currently be spent.

    Read-only: it cannot create, extend, or fund anything. Exposing this to the
    model is safe and useful — it lets an agent say "the budget is exhausted, ask
    your operator" instead of discovering it as a failed payment mid-task.

    Returns JSON with a `usable` boolean. When false, `next_step` says what a
    HUMAN must do; the agent has no way to remedy it itself.
    """
    try:
        try:
            policy = pol.load_config()
        except pol.PolicyError:
            policy = {"_resources": {}}   # no config: fall back to the environment
        session_id = pol.resolve_resource(policy, "payment_session_id")
        manager_arn = pol.resolve_resource(policy, "payment_manager_arn")
        user_id = pol.resolve_resource(policy, "user_id")
        if not session_id or not manager_arn:
            return json.dumps(
                {
                    "usable": False,
                    "reason": "No payment session is configured.",
                    "next_step": (
                        "An operator must run: agents_pay_admin.py new-session "
                        "(requires a human at a terminal)."
                    ),
                }
            )

        try:
            from bedrock_agentcore.payments import PaymentManager
        except ImportError:
            return json.dumps(
                {
                    "usable": False,
                    "reason": "bedrock-agentcore payments support is not installed.",
                    "next_step": "Install bedrock-agentcore>=1.19.0.",
                }
            )

        manager = PaymentManager(
            payment_manager_arn=manager_arn,
            # Region resolution here must match agents_pay_admin.py's resolve_region():
            # config.json's resources.region, else AWS_REGION, else let boto3/PaymentManager
            # resolve it (profile, IMDS, etc.) themselves. A hardcoded "us-west-2" fallback
            # would silently override a correctly-resolved region whenever the operator's
            # deployment lives elsewhere and neither config nor env sets one explicitly —
            # PaymentManager itself already falls back to boto3.Session().region_name before
            # its own "us-west-2" default, so passing None here is safe and correct.
            region_name=pol.resolve_resource(policy, "region"),
            agent_name=AGENT_NAME,
        )
        session = manager.get_payment_session(payment_session_id=session_id, user_id=user_id)

        # Field names vary across SDK revisions; read defensively and report only
        # what we can positively confirm rather than guessing a usable=True.
        status = str(session.get("status") or session.get("sessionStatus") or "").upper()
        limits = session.get("limits") or {}
        spend_cap = (limits.get("maxSpendAmount") or {}).get("value")
        spent = (session.get("spentAmount") or {}).get("value")

        usable = status in ("ACTIVE", "READY")
        result: dict[str, Any] = {"usable": usable, "status": status or "unknown"}
        if spend_cap is not None:
            result["budget_usd"] = str(spend_cap)
        if spent is not None:
            result["spent_usd"] = str(spent)
        if not usable:
            result["next_step"] = (
                "An operator must run: agents_pay_admin.py new-session "
                "(requires a human at a terminal). The agent cannot mint budget."
            )
        return json.dumps(result)

    except Exception as e:  # noqa: BLE001 - never raise into the agent loop
        return json.dumps(
            {
                "usable": False,
                "reason": f"{type(e).__name__} while reading session status.",
                "next_step": "An operator must check PAYMENT_SESSION_ID and AWS credentials.",
            }
        )


# --- Browser path: opaque handles instead of raw proofs -----------------------
#
# Some paid resources must render in a real browser, so the payment proof has to
# be attached to a navigation the agent controls. Handing the proof to the model
# must not expose the proof to the model, so it never leaves this process. It is held
# here and referenced by a single-use handle bound to one origin and resource.
#
# The handle is useless to an attacker who reads the transcript — it is not a
# credential, cannot be replayed elsewhere, and expires.

_PROOF_VAULT: dict[str, dict[str, Any]] = {}
_HANDLE_TTL_SECONDS = 90.0


def _purge_expired(now: float) -> None:
    for handle in [h for h, e in _PROOF_VAULT.items() if e["expires_at"] <= now]:
        entry = _PROOF_VAULT.pop(handle, None)
        if entry:
            entry["header"].clear()


def prepare_browser_payment(url: str, purchase_id: str | None = None) -> str:
    """Pay for a URL and return an OPAQUE HANDLE for a browser to replay.

    Same trusted pipeline as `x402_fetch` — policy gate, SSRF checks, strict
    challenge parsing, derived idempotency — but instead of fetching the content
    it retains the signed proof in-process and returns a handle.

    The model receives the handle and a redacted receipt. It never sees the proof.
    Pass the handle to `attach_browser_payment()` at navigation time.
    """
    try:
        policy = pol.load_config()
        origin = pol.assert_public_https_url(url)
        # Origin pinning is optional, so an empty allowed_origins list permits public
        # HTTPS origins. The mandatory SSRF controls above and below still apply.
        allowed = [o.lower().rstrip("/") for o in (policy.get("allowed_origins") or [])]
        if allowed and origin.lower() not in allowed:
            raise PaymentBlocked(f"Origin {origin} is not in the configured allowed_origins.")

        response = _get(url)
        if response.status_code != 402:
            return json.dumps(
                {
                    "paid": False,
                    "refused": True,
                    "reason": f"URL returned {response.status_code}, not 402. No payment needed.",
                }
            )

        challenge = _extract_challenge(response)
        decision = pol.authorize_payment(url, challenge, policy, purchase_id)

        manager_arn = _require_resource(policy, "payment_manager_arn")
        instrument_id = _require_resource(policy, "payment_instrument_id")
        session_id = _require_resource(policy, "payment_session_id")
        user_id = _require_resource(policy, "user_id")

        try:
            from bedrock_agentcore.payments import PaymentManager
        except ImportError:
            raise PaymentBlocked(
                "bedrock-agentcore with payments support is not installed."
            ) from None

        manager = PaymentManager(
            payment_manager_arn=manager_arn,
            # See the resolve_region()-equivalent rationale in payment_session_status():
            # config.json/env first, else let boto3 resolve region itself rather than
            # forcing "us-west-2" and risking a manager-not-found against an ARN that
            # actually lives in the operator's real deployment region.
            region_name=pol.resolve_resource(policy, "region"),
            agent_name=AGENT_NAME,
        )

        # Only the vetted entry reaches the signer — resource is included only
        # after URL-binding validation in the policy gate (see _validated_resource).
        vetted = {"x402Version": decision["x402_version"], "accepts": [decision["accept"]]}
        if decision.get("resource"):
            vetted["resource"] = decision["resource"]
        vetted_challenge = json.dumps(vetted)
        payment_header = manager.generate_payment_header(
            payment_instrument_id=instrument_id,
            payment_session_id=session_id,
            user_id=user_id,
            client_token=decision["client_token"],
            payment_required_request={
                "statusCode": 402,
                "headers": {"content-type": "application/json"},
                "body": vetted_challenge,
            },
        )
        if not isinstance(payment_header, dict):
            raise PaymentBlocked("Payment header generation returned an unexpected shape.")

        now = time.monotonic()
        _purge_expired(now)
        handle = "x402h_" + secrets.token_urlsafe(24)
        _PROOF_VAULT[handle] = {
            "header": payment_header,     # stays here; never returned
            "origin": decision["origin"],
            "path": urlparse(url).path or "/",
            "expires_at": now + _HANDLE_TTL_SECONDS,
        }

        return json.dumps(
            {
                "paid": True,
                "handle": handle,
                "expires_in_seconds": int(_HANDLE_TTL_SECONDS),
                "receipt": {
                    "amount_usd": decision["amount_usd"],
                    "network": decision["accept"]["network"],
                    "resource": f"{decision['origin']}{urlparse(url).path}",
                },
                "next_step": (
                    "Call attach_browser_payment(handle, url) to get the header to set on "
                    "the browser, then navigate. The handle is single-use and expires."
                ),
            }
        )

    except (pol.PolicyError, PaymentBlocked) as e:
        return json.dumps({"paid": False, "refused": True, "reason": str(e)})
    except Exception as e:  # noqa: BLE001
        return json.dumps(
            {"paid": False, "refused": True, "reason": f"{type(e).__name__} during payment flow."}
        )


def attach_browser_payment(handle: str, url: str) -> dict[str, str]:
    """Redeem a handle for the header to set on a browser, for ONE navigation.

    Returns the actual `{header: value}` mapping, so this is the one point where
    the proof becomes visible to the caller. Give it to browser-driving code, not
    to the model: a framework should register `prepare_browser_payment` as the
    model-facing tool and call this from trusted glue at navigation time.

    Single-use and origin+path bound: a handle stolen from a transcript cannot be
    redeemed for a different resource, and cannot be redeemed twice.
    """
    now = time.monotonic()
    _purge_expired(now)

    entry = _PROOF_VAULT.get(handle)
    if entry is None:
        raise PaymentBlocked("Unknown, already-used, or expired payment handle.")

    # Bind redemption to the exact resource the payment was authorized for.
    if pol._canonical_origin(url).lower() != entry["origin"].lower():
        raise PaymentBlocked("Handle does not match this origin.")
    if (urlparse(url).path or "/") != entry["path"]:
        raise PaymentBlocked("Handle does not match this resource path.")

    _PROOF_VAULT.pop(handle, None)  # single use: consumed on redemption
    header = entry["header"]
    return dict(header)


def _extract_challenge(response: httpx.Response) -> dict:
    """Parse an x402 challenge from the `payment-required` header or the body.

    Strict: a challenge must be a JSON object carrying `accepts`, with no default
    version fallback or tolerance for merely plausible shapes.
    """
    import base64

    header = response.headers.get("payment-required") or response.headers.get("x-payment-required")
    if header:
        for decode in (lambda h: base64.b64decode(h, validate=True).decode("utf-8"), lambda h: h):
            try:
                parsed = json.loads(decode(header))
                if isinstance(parsed, dict) and parsed.get("accepts"):
                    return parsed
            except Exception:  # noqa: BLE001 - try the next decoding strategy
                continue

    try:
        parsed = json.loads(_body_text(response))
    except json.JSONDecodeError:
        raise PaymentBlocked("402 response contains no parseable x402 challenge.") from None

    if isinstance(parsed, dict):
        if parsed.get("accepts"):
            return parsed
        inner = parsed.get("challenge")
        if isinstance(inner, dict) and inner.get("accepts"):
            return inner
    raise PaymentBlocked("402 challenge is missing the required 'accepts' array.")


def x402_fetch(url: str, purchase_id: str | None = None, method: str = "GET") -> str:
    """Fetch an x402-protected URL, paying only if trusted policy allows it.

    Returns a JSON string. On success it contains status, response metadata,
    and a redacted payment receipt (amount, network, resource) — never the
    signed proof, credential, or transaction signature. The paid body is
    returned only when `return_body: true` is set in the operator's config
    file; otherwise only content type, byte count, and SHA-256 hash are
    included.
    """
    try:
        # Pre-flight: load policy and clear the origin BEFORE any network I/O, so
        # an unapproved host is never contacted at all. Checking only after the
        # probe would still leave the probe itself as an SSRF primitive.
        policy = pol.load_config()
        origin = pol.assert_public_https_url(url)
        # Origin pinning is optional, so an empty allowed_origins list permits public
        # HTTPS origins. The mandatory SSRF controls above and below still apply.
        allowed = [o.lower().rstrip("/") for o in (policy.get("allowed_origins") or [])]
        if allowed and origin.lower() not in allowed:
            raise PaymentBlocked(f"Origin {origin} is not in the configured allowed_origins.")

        response = _get(url, method=method)

        if response.status_code != 402:
            return json.dumps(
                {
                    "status_code": response.status_code,
                    "paid": False,
                    "untrusted": True,
                    **_safe_content(response, policy),
                }
            )

        # --- 402 path: every decision below is made in trusted code. ---
        challenge = _extract_challenge(response)
        # Re-runs the destination and origin checks, then validates the challenge
        # (scheme, network, asset, recipient, amount) against the same policy.
        decision = pol.authorize_payment(url, challenge, policy, purchase_id)  # raises to refuse

        manager_arn = _require_resource(policy, "payment_manager_arn")
        instrument_id = _require_resource(policy, "payment_instrument_id")
        session_id = _require_resource(policy, "payment_session_id")
        user_id = _require_resource(policy, "user_id")

        try:
            from bedrock_agentcore.payments import PaymentManager
        except ImportError:
            raise PaymentBlocked(
                "bedrock-agentcore with payments support is not installed "
                "(needs a version providing bedrock_agentcore.payments)."
            ) from None

        manager = PaymentManager(
            payment_manager_arn=manager_arn,
            # Same fix as the two call sites above and agents_pay_admin.py's
            # resolve_region(): never force "us-west-2" over a region that config.json,
            # the environment, or boto3's own session/profile resolution already has
            # right — doing so on this signing path risked a real payment attempt
            # failing with a confusing manager-not-found instead of succeeding.
            region_name=pol.resolve_resource(policy, "region"),
            agent_name=AGENT_NAME,
        )

        # CRITICAL: hand the signer ONLY the entry the policy approved.
        #
        # Forwarding the publisher's raw 402 (its headers and body) would mean
        # validating one document and signing another: the challenge can carry
        # several accepts entries, or a compliant header alongside a hostile
        # body, so the SDK could settle terms the gate never saw. The vetted
        # entry is reserialized into a single-entry challenge; the resource
        # object is included only after URL-binding validation in the policy
        # gate (see _validated_resource).
        vetted = {"x402Version": decision["x402_version"], "accepts": [decision["accept"]]}
        if decision.get("resource"):
            vetted["resource"] = decision["resource"]
        vetted_challenge = json.dumps(vetted)

        # Settle and replay, retrying a TRANSIENT post-payment 402.
        #
        # On Base Sepolia the proof is often valid while on-chain settlement lags, so
        # the paid retry still returns 402. Without a retry that surfaces as a failed
        # fetch for a payment the user already made. The SDK only builds the header —
        # it does not make the merchant call — so the retry has to live here.
        #
        # Safe because the SAME derived client_token is reused for every attempt:
        # ProcessPayment is idempotent on it, so each attempt replays one
        # authorization/nonce. A retry either settles the not-yet-settled payment or,
        # if it had already settled, reverts on-chain. It cannot charge twice.
        paid_response = None
        for attempt in range(1, MAX_PAYMENT_ATTEMPTS + 1):
            # The proof lives only in this local variable, for the length of one
            # request. It is never returned to the caller and never logged. The
            # `finally` guarantees it is dropped even if the paid request raises —
            # a bare `del` after the call would be skipped on the exception path.
            payment_header = None
            try:
                payment_header = manager.generate_payment_header(
                    payment_instrument_id=instrument_id,
                    payment_session_id=session_id,
                    user_id=user_id,
                    client_token=decision["client_token"],  # stable => retry-safe
                    payment_required_request={
                        "statusCode": 402,
                        "headers": {"content-type": "application/json"},
                        "body": vetted_challenge,
                    },
                )
                if not isinstance(payment_header, dict):
                    # Defensive: the SDK contract is a {header: value} mapping. Bail
                    # out rather than passing an unknown shape to the HTTP layer.
                    raise PaymentBlocked("Payment header generation returned an unexpected shape.")
                paid_response = _get(url, headers=payment_header, method=method)
            finally:
                if isinstance(payment_header, dict):
                    payment_header.clear()  # overwrite the mapping, then drop it
                del payment_header

            if paid_response.status_code != 402:
                break  # 2xx, or a non-transient error worth surfacing as-is

        if paid_response is not None and paid_response.status_code == 402:
            return json.dumps(
                {
                    "paid": False,
                    "refused": False,
                    "status_code": 402,
                    "attempts": MAX_PAYMENT_ATTEMPTS,
                    "reason": (
                        f"Paid and replayed {MAX_PAYMENT_ATTEMPTS} times but the merchant "
                        "still returns 402 — usually transient on-chain settlement. The same "
                        "authorization was replayed each time, so there is no double charge. "
                        "Retry shortly, or raise X402_MAX_PAYMENT_ATTEMPTS."
                    ),
                }
            )

        return json.dumps(
            {
                "status_code": paid_response.status_code,
                "paid": 200 <= paid_response.status_code < 300,
                "untrusted": True,
                "receipt": {  # redacted by construction
                    "amount_usd": decision["amount_usd"],
                    "network": decision["accept"]["network"],
                    "resource": f"{decision['origin']}{urlparse(url).path}",
                },
                **_safe_content(paid_response, policy),
            }
        )

    except (pol.PolicyError, PaymentBlocked) as e:
        # Refusals are safe to surface: they carry no challenge values or secrets.
        return json.dumps({"paid": False, "refused": True, "reason": str(e)})
    except Exception as e:  # noqa: BLE001
        # Never let a raw exception escape — SDK errors can embed request detail.
        return json.dumps(
            {"paid": False, "refused": True, "reason": f"{type(e).__name__} during payment flow."}
        )
