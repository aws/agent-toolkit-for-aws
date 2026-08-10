"""Deterministic x402 payment policy gate — the trusted decision point.

Every payment decision is made HERE, in code, from a policy file the operator
controls. Nothing in this module reads model output, chat history, or publisher
content as authorization. That is the whole point: an agent (or a prompt
injection inside paid content) cannot talk its way past these checks.

Why this file exists
--------------------
Instructions to a model are not an access control. This module makes the
payment rules executable, so the guarantee holds even when the model is wrong
or hostile.

Config file
-----------
The runtime resolves ~/.agents-pay/config.json from the operating-system account,
not HOME or a config-path environment variable. Administrative callers and tests
may pass a path explicitly. The file must be regular, owned by the current user,
mode 0600, in a directory that is not group/world-writable, with no symlinks (see
load_config). One file, two sections:

    {
      "resources": {                   # what to pay WITH
        "payment_manager_arn": "arn:aws:bedrock-agentcore:...:payment-manager/pm-1",
        "payment_instrument_id": "pi-...",
        "payment_session_id": "ps-...",   # a spending credential
        "user_id": "alice",
        "region": "us-west-2"
      },
      "policy": {                      # what may be paid
        "max_per_payment_usd": "0.05",   # PER-PAYMENT ceiling, required
        "allowed_networks": ["eip155:84532"],
        "allowed_assets": {             # network -> exact asset contract(s)
          "eip155:84532": ["0x036CbD53842c5426634e7929541eC2318f3dCF7e"]
        },
        "allowed_recipients": ["0x1111111111111111111111111111111111111111"],
        # Or, instead of allowed_recipients:
        # "allow_any_recipient": true,
        "allowed_origins": ["https://sandbox.node4all.com"],
        "allowed_schemes": ["exact"]
      }
    }

Absent keys deny rather than allow. There is no implicit wildcard.

Recipient validation
--------------------
By default, the payee (`payTo`) must appear in `allowed_recipients`, an
operator-approved allowlist in the config file. Unknown recipients are refused
before signing. An operator may instead set `allow_any_recipient` to the literal
boolean `true`. The two modes are mutually exclusive, and the runtime rejects a
policy that enables both.

Allowing any recipient means a publisher controls the beneficiary. Network,
asset, scheme, origin/resource, per-payment, and cumulative session limits still
apply, but recipient allowlisting no longer protects against a malicious payee.

Two ceilings, not one
---------------------
`max_per_payment_usd` is NOT a duplicate of the session budget:

  * the session budget is CUMULATIVE — total spend before a human must re-approve;
  * `max_per_payment_usd` is PER TRANSACTION.

With only the session budget, one hostile challenge for the full remaining balance
drains it in a single payment. A trusted positive maximum for each payment keeps
both bounds meaningful.

Scope / non-goals
-----------------
This module decides IF a payment may proceed and derives the idempotency key.
It never holds provider credentials, never signs, never performs network I/O.
Fetching and settlement live in x402_fetch.py.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import stat
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

# USDC has 6 decimals on every chain AgentCore Payments supports. x402 quotes
# amounts as integer base units, so 500000 base units == 0.50 USDC.
USDC_DECIMALS = 6

# Fields we require on an accepts[] entry before it is eligible for payment.
_REQUIRED_ACCEPT_FIELDS = ("scheme", "network", "asset", "payTo")


class PolicyError(Exception):
    """A payment was refused, or the policy itself is unusable.

    Carries no challenge values, so the message is safe to surface to a model.
    """


def _fail(reason: str) -> "PolicyError":
    return PolicyError(reason)


def runtime_config_path() -> Path:
    """Return the config path bound to the current OS account.

    Path.home(), HOME, and config-path environment variables are caller-controlled
    in shell-capable harnesses. The runtime therefore asks the OS account database
    for the home directory and fails closed where that trusted lookup is unavailable.
    """
    try:
        import pwd
    except ImportError:
        raise _fail(
            "Cannot resolve the runtime payment config from the OS account on this "
            "platform. Payments are refused."
        ) from None

    try:
        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except KeyError:
        raise _fail(
            "The current uid has no OS account home directory. Payments are refused."
        ) from None
    if not home.is_absolute():
        raise _fail("The OS account home directory is not absolute. Payments are refused.")
    return home / ".agents-pay" / "config.json"


def load_config(path: str | os.PathLike[str] | None = None) -> dict:
    """Load and validate the operator config: resource identifiers + payment policy.

    One file, two sections. `resources` holds the identifiers the runtime needs
    (manager ARN, instrument, session, user); `policy` holds the limits. They live
    together because they are written at the same moment by the same human, and
    splitting them made the operator hand-copy identifiers between steps.

    Merging them also buys a real control, not just convenience: the session ID is
    a spending credential, and the sanctioned runtime cannot select a replacement
    policy file through HOME or a config-path environment variable. Resource values
    in the file also win over environment fallbacks — see resolve_resource().

    The file is a security control, so one that anyone else can write is treated as
    no config at all. lstat (not stat) rejects symlinks rather than following them.
    These checks do not protect against arbitrary code already running as the file
    owner; that requires OS, container, or IAM isolation around the signer.
    """
    p = Path(path) if path is not None else runtime_config_path()

    try:
        st = p.lstat()
    except FileNotFoundError:
        raise _fail(
            f"No payment config at {p}. Payments are refused until an operator "
            "creates one (agents_pay_admin.py init-config). This is intentional: "
            "there is no permissive default."
        ) from None

    if stat.S_ISLNK(st.st_mode):
        raise _fail(f"Payment config {p} is a symlink; refusing to follow it.")
    if not stat.S_ISREG(st.st_mode):
        raise _fail(f"Payment config {p} is not a regular file.")
    if st.st_uid != os.getuid():
        raise _fail(f"Payment config {p} is not owned by the current user.")
    # Reject any group/other bit: a config others can rewrite is not a control.
    if st.st_mode & 0o077:
        raise _fail(
            f"Payment config {p} has mode {stat.filemode(st.st_mode)}; "
            "expected 0600. Run: chmod 600 " + str(p)
        )

    # The containing directory matters as much as the file. Write access to the
    # directory lets another principal rename a wider config into place, which
    # no amount of checking on the old inode would detect.
    try:
        dir_st = p.parent.lstat()
    except OSError:
        raise _fail(f"Cannot stat the directory containing {p}.") from None
    if dir_st.st_uid != os.getuid():
        raise _fail(f"Directory {p.parent} is not owned by the current user.")
    if dir_st.st_mode & 0o022:
        raise _fail(
            f"Directory {p.parent} is group/world-writable "
            f"({stat.filemode(dir_st.st_mode)}); another user could replace the "
            "config file. Run: chmod 700 " + str(p.parent)
        )

    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise _fail(f"Payment config {p} is not valid JSON: {e}") from None
    if not isinstance(raw, dict):
        raise _fail(f"Payment config {p} must be a JSON object.")

    # A flat file (policy keys at the top level) is still accepted, so an existing
    # policy.json keeps working rather than failing open or failing loudly.
    policy = raw.get("policy") if isinstance(raw.get("policy"), dict) else raw
    resources = raw.get("resources") if isinstance(raw.get("resources"), dict) else {}

    if "max_per_payment_usd" in policy:
        cap_key = "max_per_payment_usd"
    elif "max_amount_usd" in policy:      # earlier name, still honoured
        cap_key = "max_amount_usd"
    else:
        raise _fail(
            "Payment policy is missing 'max_per_payment_usd'. This is the PER-PAYMENT "
            "ceiling and is not the same thing as the session budget: the session "
            "budget is cumulative, so without a per-payment cap a single hostile "
            "challenge can drain the whole budget in one transaction."
        )
    try:
        cap = Decimal(str(policy[cap_key]))
    except (InvalidOperation, ValueError):
        raise _fail(f"Payment policy '{cap_key}' is not a decimal number.") from None
    policy["max_per_payment_usd"] = policy[cap_key]  # normalize for callers
    policy["_resources"] = resources                 # carried for resolve_resource()
    if cap <= 0:
        raise _fail(f"Payment policy '{cap_key}' must be greater than zero.")

    return policy


#: config `resources` key -> the environment variable that may substitute for it.
RESOURCE_ENV = {
    "payment_manager_arn": "PAYMENT_MANAGER_ARN",
    "payment_instrument_id": "PAYMENT_INSTRUMENT_ID",
    "payment_session_id": "PAYMENT_SESSION_ID",
    "user_id": "PAYMENT_USER_ID",
    "region": "AWS_REGION",
}


def resolve_resource(policy: dict, key: str) -> str | None:
    """Resolve one resource identifier: **config file first**, environment second.

    The precedence is the security-relevant part, and it is deliberately the
    opposite of the usual "env overrides file" convention.

    The session ID is a spending credential: it names the budget being drawn down.
    If the environment could override the file, an agent able to set a variable
    could point the runtime at some other session with a larger budget, and the
    0600 file would be decorative. So the file wins wherever it speaks.

    The environment remains the fallback for deployments with no writable home —
    containers, Lambda — where identifiers arrive by injection. That is a real
    need, but it is the weaker mode: anything that can set the environment can
    choose the session.
    """
    resources = policy.get("_resources") or {}
    from_file = resources.get(key)
    if from_file:
        return str(from_file)
    env_name = RESOURCE_ENV.get(key)
    return os.environ.get(env_name) if env_name else None

def per_payment_cap(policy: dict) -> str:
    """The per-payment USD ceiling, under either the current or the earlier key.

    load_config() normalizes this, but callers may hand a policy dict straight in
    (tests, embedded use), so resolve it here too rather than assuming. Missing is
    a refusal, never an unbounded payment.
    """
    for key in ("max_per_payment_usd", "max_amount_usd"):
        if key in policy:
            return str(policy[key])
    raise _fail(
        "Payment policy has no per-payment ceiling ('max_per_payment_usd'). "
        "Refusing to pay: the session budget is cumulative and does not bound a "
        "single transaction."
    )


def _policy_list(policy: dict, key: str) -> list[str]:
    """Read a list-valued policy key. Missing or malformed means deny (empty)."""
    value = policy.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise _fail(f"Payment policy '{key}' must be a list.")
    return [str(v) for v in value]


def _canonical_origin(url: str) -> str:
    """scheme://host[:port], lowercased, with the default HTTPS port dropped."""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.port and u.port != 443:
        return f"{u.scheme}://{host}:{u.port}"
    return f"{u.scheme}://{host}"


def assert_public_https_url(url: str) -> str:
    """Require HTTPS and a publicly routable destination; return the origin.

    Resolves every address the hostname maps to and rejects the request if ANY
    of them is internal. Checking only the first answer would let a host with
    one public and one private address through.

    This is a pre-flight check. It does not by itself defeat DNS rebinding,
    because the OS resolves again when the socket is opened — x402_fetch.py
    closes that gap by pinning the connection to a vetted address.
    """
    u = urlparse(url)
    if u.scheme != "https":
        raise _fail("Only https:// payment URLs are allowed.")
    if not u.hostname:
        raise _fail("Payment URL has no host.")
    if u.username or u.password:
        raise _fail("Payment URL must not contain embedded credentials.")

    try:
        infos = socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise _fail("Payment URL hostname does not resolve.") from None

    for info in infos:
        assert_public_ip(info[4][0])

    return _canonical_origin(url)


def assert_public_ip(addr: str) -> None:
    """Reject loopback, private, link-local, and other non-public ranges.

    Deliberately broader than is_private/is_loopback/is_link_local, which alone
    still admit multicast and the CGNAT 100.64/10 shared-address space.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        raise _fail("Payment URL resolved to an unparseable address.") from None

    # Unwrap ::ffff:127.0.0.1 style addresses so v4 rules apply to them.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise _fail("Payment URL resolves to a non-public address.")

    # 100.64.0.0/10 (CGNAT) is not flagged by any is_* property but is not
    # publicly routable, and 169.254.169.254 lives behind it in some networks.
    if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
        raise _fail("Payment URL resolves to a non-public address.")


def base_units_to_usd(amount: str | int, decimals: int = USDC_DECIMALS) -> Decimal:
    """Convert an x402 integer base-unit amount to a USD Decimal.

    Accepts ONLY a canonical non-negative integer literal: digits, nothing else.
    Decimal() would otherwise happily parse "1E+7", "Infinity", "500000.0",
    " 500000 ", and "+500000". None of those breach the ceiling on their own
    (the comparison still holds), but a publisher should not get to express an
    amount in a form that a human reviewing logs would misread. An exotic
    encoding therefore fails closed rather than relying on downstream
    arithmetic to save us.
    """
    text = amount if isinstance(amount, str) else str(amount)
    if not isinstance(amount, int) and not text.isdigit():
        raise _fail("Payment challenge amount must be a plain integer in base units.")
    try:
        raw = Decimal(text)
    except InvalidOperation:
        raise _fail("Payment challenge amount is not a number.") from None
    if raw <= 0:
        raise _fail("Payment challenge amount must be positive.")
    return raw / (Decimal(10) ** decimals)


def validated_amount_units(entry: dict) -> str:
    """Resolve one canonical amount and reject conflicting aliases.

    x402 v1 commonly uses maxAmountRequired while v2 uses amount. Supporting both
    is safe only when they cannot describe different transactions.
    """
    amount = entry.get("amount")
    maximum = entry.get("maxAmountRequired")
    if amount is not None and maximum is not None and str(amount) != str(maximum):
        raise _fail("Payment challenge contains conflicting amount fields.")
    resolved = amount if amount is not None else maximum
    if resolved is None:
        raise _fail("Payment challenge has no amount.")
    text = str(resolved)
    base_units_to_usd(text)
    return text


def select_accept_entry(challenge: dict, policy: dict) -> dict:
    """Return the first accepts[] entry that satisfies policy, else raise.

    Each entry must earn selection by passing every configured check. The publisher
    cannot choose the network, asset, recipient, or amount unilaterally.
    """
    accepts = challenge.get("accepts")
    if not isinstance(accepts, list) or not accepts:
        raise _fail("Payment challenge has no accepts entries.")

    allowed_networks = _policy_list(policy, "allowed_networks")
    allowed_schemes = _policy_list(policy, "allowed_schemes")
    if "allowed_schemes" not in policy:
        allowed_schemes = ["exact"]
    allow_any_recipient = policy.get("allow_any_recipient", False)
    if not isinstance(allow_any_recipient, bool):
        raise _fail("Payment policy 'allow_any_recipient' must be a boolean.")
    if (
        "allow_any_recipient" in policy
        and "allowed_recipients" in policy
    ):
        raise _fail(
            "Payment policy 'allow_any_recipient' and 'allowed_recipients' "
            "are mutually exclusive."
        )
    allowed_recipients = [r.lower() for r in _policy_list(policy, "allowed_recipients")]
    allowed_assets = policy.get("allowed_assets") or {}
    if not isinstance(allowed_assets, dict):
        raise _fail("Payment policy 'allowed_assets' must be an object.")
    cap_usd = Decimal(str(per_payment_cap(policy)))

    if not allowed_networks:
        raise _fail("Payment policy allows no networks.")
    if not allowed_schemes:
        raise _fail("Payment policy allows no schemes.")
    if not allow_any_recipient and not allowed_recipients:
        raise _fail("Payment policy allows no recipients.")

    for entry in accepts:
        if not isinstance(entry, dict):
            continue
        if any(entry.get(f) in (None, "") for f in _REQUIRED_ACCEPT_FIELDS):
            continue
        if str(entry["scheme"]) not in allowed_schemes:
            continue
        network = str(entry["network"])
        if network not in allowed_networks:
            continue
        # Asset contracts are compared case-insensitively: EVM addresses are
        # hex and often differ only by EIP-55 checksum capitalization.
        permitted_assets = [a.lower() for a in allowed_assets.get(network, [])]
        if str(entry["asset"]).lower() not in permitted_assets:
            continue
        if (
            not allow_any_recipient
            and str(entry["payTo"]).lower() not in allowed_recipients
        ):
            continue
        try:
            amount_units = validated_amount_units(entry)
            if base_units_to_usd(amount_units) > cap_usd:
                continue
        except PolicyError:
            continue
        return entry

    # Uniform refusal: naming the failed field would let a publisher probe the
    # policy by iterating challenges until the message changed.
    raise _fail(
        "No payment option in this challenge satisfies the configured policy "
        "(scheme, network, asset, recipient, and amount ceiling are all enforced). "
        "Refusing to pay."
    )


def _validated_resource(challenge: dict, url: str) -> dict | None:
    """Validate and sanitize the challenge's resource object before signing.

    The x402 v2 spec requires the signed header to echo the resource for URL
    binding. However, the publisher controls the challenge, so we must verify
    that resource.url matches the URL we actually requested. This prevents a
    hostile publisher from binding the signature to a different resource.

    Comparison uses origin+path only: query parameters appended by the
    publisher (e.g. tracking params) do not change which server gets paid.

    Returns a sanitized dict with only the `url` field, or None if the
    challenge has no resource. Raises PolicyError on mismatch.
    """
    resource = challenge.get("resource")
    if resource is None:
        return None
    if not isinstance(resource, dict):
        return None
    resource_url = resource.get("url")
    if not isinstance(resource_url, str):
        return None
    # Bind: resource.url origin+path must match the requested origin+path.
    requested = urlparse(url)
    challenged = urlparse(resource_url)
    req_base = f"{requested.scheme}://{requested.netloc}{requested.path}".rstrip("/")
    ch_base = f"{challenged.scheme}://{challenged.netloc}{challenged.path}".rstrip("/")
    if req_base != ch_base:
        raise _fail("Challenge resource.url does not match the requested URL.")
    # Forward only the url field — no arbitrary publisher-controlled keys.
    return {"url": resource_url}


def authorize_payment(
    url: str,
    challenge: dict,
    policy: dict | None = None,
    purchase_id: str | None = None,
) -> dict:
    """Full gate: validate destination and challenge, return an approved decision.

    Returns the vetted accepts entry plus the derived amount, origin, and a
    stable idempotency key. Raises PolicyError on any refusal.

    `purchase_id` distinguishes deliberate repeat purchases of the same resource;
    see derive_client_token.
    """
    policy = policy if policy is not None else load_config()

    origin = assert_public_https_url(url)

    # Origin allowlisting is optional. HTTPS, address vetting, redirect refusal,
    # rebinding protection, timeouts, and byte limits are always enforced. An
    # operator with a known merchant set can pin it with allowed_origins.
    allowed_origins = _policy_list(policy, "allowed_origins")
    if allowed_origins and origin.lower() not in [o.lower().rstrip("/") for o in allowed_origins]:
        raise _fail(f"Origin {origin} is not in the configured allowed_origins.")

    if not isinstance(challenge, dict):
        raise _fail("Payment challenge is not a JSON object.")

    entry = select_accept_entry(challenge, policy)
    amount_units = validated_amount_units(entry)
    x402_version = int(challenge.get("x402Version") or challenge.get("version") or 1)

    # Sign exactly the amount the gate validated. v1 uses maxAmountRequired and
    # v2 uses amount; the non-canonical alias is removed so downstream code cannot
    # apply different precedence from the policy gate.
    vetted_entry = dict(entry)
    vetted_entry.pop("amount", None)
    vetted_entry.pop("maxAmountRequired", None)
    if x402_version == 1:
        vetted_entry["maxAmountRequired"] = amount_units
    else:
        vetted_entry["amount"] = amount_units

    return {
        "accept": vetted_entry,
        "origin": origin,
        "resource": _validated_resource(challenge, url),
        "amount_base_units": str(amount_units),
        "amount_usd": str(base_units_to_usd(amount_units)),
        "x402_version": x402_version,
        "client_token": derive_client_token(
            url,
            vetted_entry,
            challenge,
            purchase_id,
            session_id=resolve_resource(policy, "payment_session_id") or "",
        ),
    }


def derive_client_token(
    url: str,
    accept: dict,
    challenge: dict,
    purchase_id: str | None = None,
    *,
    session_id: str | None = None,
) -> str:
    """Derive a stable idempotency token for one logical purchase.

    Same (session, resource, network, asset, recipient, amount) always yields the
    same token, so a retry after a lost response replays the SAME authorization
    instead of creating a second irreversible payment. Derived rather than random
    precisely so it survives a process restart.

    The publisher's nonce is deliberately NOT part of the material. A retry
    re-fetches the 402 and many servers issue a fresh nonce each time, so mixing
    it in would produce a different token per attempt — turning the retry this
    function exists to protect into a second real payment, and handing a hostile
    publisher a way to force double charges by rotating nonces.

    The trade-off: two intentional purchases of the same resource, for the same
    amount, in the same session collapse to one token, so the second would be
    suppressed as a replay. Pass an explicit `purchase_id` (an order number, a
    turn counter — anything the caller controls) to distinguish deliberate
    repeat buys. Suppressing a duplicate charge is the safer default when the
    caller has not said otherwise.
    """
    session = session_id if session_id is not None else os.environ.get("PAYMENT_SESSION_ID", "")
    material = "\x1f".join(  # unit separator: cannot appear in these values
        [
            session,
            _canonical_origin(url),
            urlparse(url).path or "/",
            str(accept.get("network", "")),
            str(accept.get("asset", "")).lower(),
            str(accept.get("payTo", "")).lower(),
            validated_amount_units(accept),
            purchase_id or "",
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
