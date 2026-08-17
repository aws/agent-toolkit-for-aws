#!/usr/bin/env python3
"""Trusted admin CLI for agents-pay. A HUMAN runs this, never the agent.

This is the deliberate separation of onboarding from runtime. The agent's runtime
surface can only SPEND an already-approved, budget-bounded session — it can pay,
check remaining budget, and obtain a browser handle, and nothing more. Creating
sessions, approving new payees, writing config, and provisioning payment resources
all live here, behind a human at a terminal.

Per the AWS IAM guide, a human runs these commands under the ManagementRole (which
explicitly denies ProcessPayment); the agent runs under the ProcessPaymentRole
(which cannot create sessions). The agent must not have this file or that role:
https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/payments-iam-roles.html

Why the split matters
---------------------
Administrative actions are not model-callable tools, take no model input, and
this file is never imported by the runtime fetch path. A payment-capable model
therefore cannot mint fresh budget or receive provider credentials through this
interface.

Commands
--------
    init-config       Write ~/.agents-pay/config.json (0600) — resources + policy
    show-config       Print the active config and its file permissions
    create-instrument Create the per-user wallet (ManagementRole)
    new-session       Create a budget-bounded session (ManagementRole, TTY approval)
    preflight         Verify wiring and confirm no secrets are exposed

Secrets are NEVER accepted as arguments here either. Provider credentials go to
the AgentCore CLI's own interactive wizard (`agentcore add payment-connector`),
which keeps them out of shell history and out of this process.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _check_aws_credentials(region: str | None = None) -> bool:
    """Fail fast with a clear message if AWS credentials are missing/expired.

    A cheap, read-only STS call (no IAM permissions beyond the default caller
    identity) run BEFORE any interactive prompts. Without this, a user can type
    through the entire setup-openclaw wizard only to discover at instrument or
    session creation — several prompts later — that their credentials expired,
    forcing a full re-run. boto3 is already a hard dependency of
    bedrock-agentcore, so this adds no new dependency.
    """
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
    except ImportError:
        # boto3 missing entirely is caught by the bedrock_agentcore.payments
        # import check that every caller already performs; nothing to add here.
        return True
    try:
        sts = boto3.client("sts", region_name=region or os.environ.get("AWS_REGION", "us-east-1"))
        sts.get_caller_identity()
        return True
    except (NoCredentialsError, ClientError, BotoCoreError) as exc:
        print(
            "AWS credentials are invalid, expired, or missing.\n"
            f"  ({exc})\n\n"
            "Run `aws sso login` (or otherwise refresh your credentials), then "
            "re-run this command.",
            file=sys.stderr,
        )
        return False

DEFAULT_DIR = Path.home() / ".agents-pay"
DEFAULT_CONFIG = DEFAULT_DIR / "config.json"
AGENT_NAME = "aws-agents-pay"
USDC_DECIMALS = 6


def admin_config_path(explicit: str | None) -> Path:
    """Resolve an operator-selected path for administrative commands only."""
    return Path(explicit or os.environ.get("AGENTS_PAY_CONFIG") or DEFAULT_CONFIG)


def deployed_state_candidates(project_dir: str | Path | None = None) -> list[Path]:
    """Paths where the AgentCore CLI may record deployed payment resources."""
    explicit = project_dir or os.environ.get("AGENTCORE_PROJECT_DIR")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        return [
            root / "agentcore/.cli/deployed-state.json",
            root / ".cli/deployed-state.json",
        ]
    return [
        Path("agentcore/.cli/deployed-state.json"),  # project root
        Path(".cli/deployed-state.json"),             # inside agentcore/
        Path("../.cli/deployed-state.json"),          # child of agentcore/
    ]


def _find_deployed_state(project_dir: str | Path | None = None) -> Path | None:
    """Return the first existing deployed-state.json candidate, or None."""
    for candidate in deployed_state_candidates(project_dir):
        if candidate.exists():
            return candidate
    return None


def discover_deployed(project_dir: str | Path | None = None) -> dict[str, str | None]:
    """Best-effort read of manager ARN / connector ID from the CLI's deploy record.

    Returns a dict with possibly-None values; callers fall back to flags or env.
    Purely a convenience: nothing security-relevant is decided from this file, and
    a wrong or missing value surfaces as a plain error from the service.

    Searches several relative paths so the command works whether you run from the
    project root, inside the agentcore/ directory, or a subdirectory of it.

    CLI 0.20.x writes targets.<target>.resources.payments[]; 0.26.x writes
    payments as objects keyed by name. Older layouts used a top-level payments[].
    All three are handled.
    """
    out: dict[str, str | None] = {"manager_arn": None, "connector_id": None, "role_arn": None}
    state_path = _find_deployed_state(project_dir)
    if state_path is None:
        return out
    try:
        data = json.loads(state_path.read_text())
        payments = None
        targets = data.get("targets") or {}
        target = targets.get("default") or (next(iter(targets.values()), {}) if targets else {})
        if isinstance(target, dict):
            payments = (target.get("resources") or {}).get("payments")
        if not payments:
            payments = data.get("payments")
        if not payments:
            return out
        # 0.26.x: payments is a dict keyed by name
        if isinstance(payments, dict):
            pay = next(iter(payments.values()), {})
        # 0.20.x and older: payments is a list
        elif isinstance(payments, list):
            pay = payments[0] if payments else {}
        else:
            return out
        connectors = pay.get("connectors") or []
        out["manager_arn"] = pay.get("managerArn")
        # 0.26.x: connectors may be a dict keyed by name
        if isinstance(connectors, dict):
            first_connector = next(iter(connectors.values()), {})
        elif isinstance(connectors, list):
            first_connector = connectors[0] if connectors else {}
        else:
            first_connector = {}
        out["connector_id"] = first_connector.get("connectorId") if first_connector else None
        out["role_arn"] = pay.get("processPaymentRoleArn")
    except Exception:  # noqa: BLE001 - convenience only; never fatal
        pass
    return out


def resolve_manager_arn(explicit: str | None, config_path: Path) -> str | None:
    """Manager ARN from --flag, else the environment, else config.json, else the CLI deploy record.

    config.json's resources.payment_manager_arn is exactly the value create-instrument
    (and init-config, when discoverable) persist right after a successful call — the
    same source of truth resolve_region() now reads for region. Checking it here means
    a repeat run of new-session from a different directory (no deployed-state.json in
    reach) still finds the manager ARN the tool itself already saved, instead of
    failing with "Could not determine the payment manager ARN" right next to a config
    file that has had the answer the whole time.
    """
    if explicit:
        return explicit
    env_arn = os.environ.get("PAYMENT_MANAGER_ARN")
    if env_arn:
        return env_arn
    config = load_raw_config(config_path)
    config_arn = (config.get("resources") or {}).get("payment_manager_arn")
    if config_arn:
        return config_arn
    return discover_deployed()["manager_arn"]


def resolve_region(explicit: str | None, config_path: Path) -> str | None:
    """Region from --flag, else the environment, else the config file, else None.

    init-config (and create-instrument, on success) persist the region actually
    used into resources.region, right alongside the manager ARN it goes with.
    Preferring that saved value here — instead of a hardcoded default — keeps
    the PaymentManager client in the same region as the manager ARN it was just
    told to use. Returning None when nothing is configured lets boto3's own
    session/profile resolution take over, rather than silently forcing a
    region the operator never chose.
    """
    if explicit:
        return explicit
    env_region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if env_region:
        return env_region
    config = load_raw_config(config_path)
    return (config.get("resources") or {}).get("region")

# USDC contract addresses per network. Pinned here so an operator cannot be
# tricked into allowlisting a look-alike token contract by pasting one in.
KNOWN_USDC = {
    "eip155:84532": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Base Sepolia (testnet)
    "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",   # Base mainnet
}


def _atomic_write_0600(path: Path, content: str) -> None:
    """Write content to path with mode 0600, atomically.

    Atomic replace prevents a reader from seeing a half-written policy, and the
    temp file is created 0600 in the same directory so the secret-ish content is
    never briefly world-readable and the rename never crosses filesystems.
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)  # tighten even if the dir already existed

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    os.chmod(path, 0o600)



def load_raw_config(path: Path) -> dict:
    """Read the config for editing. Missing or unreadable -> empty skeleton."""
    if not path.exists():
        return {"resources": {}, "policy": {}}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"resources": {}, "policy": {}}
    if not isinstance(data, dict):
        return {"resources": {}, "policy": {}}
    # A flat legacy policy file: lift its keys into the policy section.
    if "policy" not in data and "resources" not in data:
        return {"resources": {}, "policy": data}
    data.setdefault("resources", {})
    data.setdefault("policy", {})
    return data


def save_config(path: Path, config: dict) -> None:
    """Write the config atomically at 0600, preserving key order for readability."""
    ordered = {"resources": config.get("resources", {}), "policy": config.get("policy", {})}
    _atomic_write_0600(path, json.dumps(ordered, indent=2) + "\n")


def update_resources(path: Path, **values: str | None) -> None:
    """Merge resource identifiers into the config without touching the policy."""
    config = load_raw_config(path)
    for key, value in values.items():
        if value:
            config["resources"][key] = value
    save_config(path, config)



def resolve_user_id(explicit: str | None, config_path: Path) -> str | None:
    """The single-tenant user id: explicit flag, else whatever init-config generated.

    This skill treats one installation as one payer. The AgentCore Payments API still
    needs a userId to scope the instrument and session, but there is no reason to make
    an operator invent one and then retype it identically at every step — mismatching
    it between create-instrument and new-session produces a session that cannot spend
    the instrument, which is a confusing failure to debug.
    """
    if explicit:
        return explicit
    config = load_raw_config(config_path)
    return (config.get("resources") or {}).get("user_id") or os.environ.get("PAYMENT_USER_ID")


def generate_user_id() -> str:
    """A stable, opaque id for this installation.

    Random rather than derived from the host or login: it ends up in AgentCore
    Payments API calls and in the wallet's linked accounts, so it should not leak a
    machine name or a corporate username.
    """
    return "agents-pay-" + secrets.token_hex(6)


def cmd_init_config(args: argparse.Namespace) -> int:
    path = admin_config_path(args.path)
    if path.exists() and not args.force:
        print(f"Refusing to overwrite existing policy at {path} (pass --force).", file=sys.stderr)
        return 1

    network = args.network
    asset = KNOWN_USDC.get(network)
    if asset is None:
        print(
            f"Unknown network {network}. Known: {', '.join(KNOWN_USDC)}. "
            "Add the exact USDC contract to KNOWN_USDC rather than passing one in.",
            file=sys.stderr,
        )
        return 1


    config = load_raw_config(path) if args.force else {"resources": {}, "policy": {}}
    config["policy"] = {
        "max_per_payment_usd": args.max_per_payment_usd,
        "allowed_networks": [network],
        "allowed_assets": {network: [asset]},
        "allowed_schemes": ["exact"],
    }
    if args.allow_any_recipient:
        config["policy"]["allow_any_recipient"] = True
    else:
        config["policy"]["allowed_recipients"] = list(args.recipient)
    # Omitted entirely when not pinned, so the agent can browse the open web.
    if args.origin:
        config["policy"]["allowed_origins"] = list(args.origin)
    # One installation = one payer, so the user id is generated once here and read
    # from the config by every later step. Preserved on --force so an existing
    # instrument and session keep matching.
    existing_user = (config.get("resources") or {}).get("user_id")
    user_id = args.user_id or existing_user or generate_user_id()
    config["resources"]["user_id"] = user_id

    # Seed resources from the CLI deploy record so later steps have less to fill in.
    discovered = discover_deployed()
    if discovered["manager_arn"]:
        config["resources"].setdefault("payment_manager_arn", discovered["manager_arn"])
    if args.region:
        config["resources"].setdefault("region", args.region)

    save_config(path, config)
    print(f"Wrote config to {path} (mode 0600, in a 0700 directory)")
    print(f"Payer identity: {user_id}"
          + ("  (generated — single tenant, no need to pass it again)"
             if not args.user_id and not existing_user else ""))
    print(json.dumps({"resources": config["resources"], "policy": config["policy"]}, indent=2))
    print(
        "\nThe policy section authorizes payments made through the sanctioned runtime. "
        "That runtime ignores config-path environment overrides. Keep the config and "
        "ProcessPayment credentials outside any unrestricted same-user shell."
    )
    print(
        "\nTwo ceilings, both needed: max_per_payment_usd bounds ONE transaction; the\n"
        "session budget (set later by new-session) bounds CUMULATIVE spend. Without a\n"
        "per-payment cap, one hostile challenge for the whole remaining balance would\n"
        "drain the session in a single payment."
    )
    if args.allow_any_recipient:
        print(
            "\nWARNING: allow_any_recipient is enabled. The publisher may choose the\n"
            "payment beneficiary. Network, asset, scheme, origin, per-payment, and\n"
            "cumulative session limits remain enforced."
        )
    else:
        print(
            "\nApproved recipients are enforced in trusted code. A challenge whose payTo is\n"
            "not in allowed_recipients is refused before ProcessPayment is called."
        )
    if not args.origin:
        print(
            "\nNo allowed_origins set: the agent may fetch ANY public HTTPS site. The\n"
            "SSRF protections still apply (HTTPS only, internal ranges refused, pinned\n"
            "address, no redirects, bounded body). Pass --origin to pin a merchant set."
        )
    return 0


def cmd_show_config(args: argparse.Namespace) -> int:
    path = admin_config_path(args.path)
    if not path.exists():
        print(f"No config at {path}. Payments are refused until one exists.")
        print(
            "Create it with: agents_pay_admin.py init-config "
            "--max-per-payment-usd 0.05 --recipient <payTo> "
            "(or explicitly use --allow-any-recipient)"
        )
        return 1
    st = path.lstat()
    dir_st = path.parent.lstat()
    print(f"Config    : {path}")
    print(f"File mode : {stat.filemode(st.st_mode)} "
          f"{'OK' if not (st.st_mode & 0o077) else '*** TOO OPEN — chmod 600 ***'}")
    print(f"Dir mode  : {stat.filemode(dir_st.st_mode)} "
          f"{'OK' if not (dir_st.st_mode & 0o022) else '*** WRITABLE BY OTHERS — chmod 700 ***'}")
    print(f"Owner     : uid {st.st_uid} {'(you)' if st.st_uid == os.getuid() else '*** NOT YOU ***'}")
    config = load_raw_config(path)
    print("\n--- resources (what to pay WITH; no secrets) ---")
    print(json.dumps(config.get("resources", {}), indent=2))
    print("\n--- policy (what MAY be paid) ---")
    print(json.dumps(config.get("policy", {}), indent=2))
    missing = [k for k in ("payment_manager_arn", "payment_instrument_id", "payment_session_id", "user_id")
               if not config.get("resources", {}).get(k)]
    if missing:
        print(f"\nNot yet set: {', '.join(missing)}")
        print("These may also come from the environment, but the config file wins when present.")
    return 0


def cmd_create_instrument(args: argparse.Namespace) -> int:
    """Create the per-user wallet and print the delegation and funding steps."""
    try:
        from bedrock_agentcore.payments import PaymentManager
    except ImportError:
        print(
            "bedrock-agentcore with payments support is not installed.\n"
            "Activate the setup virtual environment, then run:\n"
            "  python -m pip install --upgrade 'bedrock-agentcore>=1.19.0'",
            file=sys.stderr,
        )
        return 1

    config_path = admin_config_path(args.path)
    region = resolve_region(args.region, config_path)

    if not _check_aws_credentials(region):
        return 1

    user_id = resolve_user_id(args.user_id, config_path)
    if not user_id:
        print(
            "No payer identity found. Run init-config first (it generates one), or "
            "pass --user-id explicitly.",
            file=sys.stderr,
        )
        return 1

    discovered = discover_deployed()
    manager_arn = resolve_manager_arn(args.manager_arn, config_path)
    connector_id = args.connector_id or os.environ.get("PAYMENT_CONNECTOR_ID") or discovered["connector_id"]

    if not manager_arn or not connector_id:
        checked = ", ".join(str(p) for p in deployed_state_candidates())
        print(
            f"Could not find deployed-state.json (checked: {checked}).\n\n"
            "This file is created by `agentcore deploy`. To resolve:\n"
            "  \u2022 Run this command from the directory that CONTAINS the agentcore/ folder, OR\n"
            "  \u2022 Run from inside the agentcore/ directory itself, OR\n"
            "  \u2022 Pass --manager-arn and --connector-id explicitly.",
            file=sys.stderr,
        )
        return 1

    manager = PaymentManager(
        payment_manager_arn=manager_arn,
        region_name=region,
        agent_name=AGENT_NAME,
    )
    instrument = manager.create_payment_instrument(
        user_id=user_id,
        payment_connector_id=connector_id,
        payment_instrument_type="EMBEDDED_CRYPTO_WALLET",
        payment_instrument_details={
            "embeddedCryptoWallet": {
                "network": args.network_family,
                "linkedAccounts": [{"email": {"emailAddress": args.email}}],
            }
        },
    )
    instrument_id = instrument["paymentInstrumentId"]
    wallet = (instrument.get("paymentInstrumentDetails") or {}).get("embeddedCryptoWallet", {})
    wallet_address = wallet.get("walletAddress")
    redirect_url = wallet.get("redirectUrl")  # Coinbase only; absent for Privy

    update_resources(
        config_path,
        payment_manager_arn=manager_arn,
        payment_instrument_id=instrument_id,
        user_id=user_id,
        region=region,
    )

    print(f"Instrument created : {instrument_id}")
    print(f"Wallet address     : {wallet_address}")
    print(f"Recorded in        : {config_path}  (nothing to copy by hand)")
    print("\nTwo one-time steps remain, both done by the END USER, not the agent:")
    if redirect_url:
        print(f"  1. Delegation: visit {redirect_url}, sign in, grant access to {wallet_address}")
    else:
        print("  1. Delegation: approve via the Privy frontend SDK")
        print("     https://github.com/privy-io/aws-agentcore-sdk")
    print(f"  2. Funding   : send testnet USDC to {wallet_address}")
    print("                 https://faucet.circle.com/ (Base Sepolia)")
    print(f"\nThen authorize spending:\n  {Path(__file__).name} new-session --budget 1.00 --expiry-minutes 120")
    return 0




def cmd_new_session(args: argparse.Namespace) -> int:
    """Create a budget-bounded payment session after explicit human confirmation."""
    # The TTY gate is checked FIRST, before dependency and argument validation,
    # so the approval requirement is not order-dependent: a headless caller gets
    # the same refusal whether or not the SDK is installed or the ARN is set.
    #
    # Interactive confirmation on a TTY is the approval artifact. It cannot be
    # produced by the model, by chat history, or by fetched publisher content.
    #
    # There is deliberately NO --yes / non-interactive escape hatch. This script
    # lives inside the skill directory, so any agent with shell access can run
    # it; a flag that skips the prompt would hand that agent the power to mint
    # budget. A TTY means a headless agent cannot satisfy the gate even by
    # invoking the command directly.
    if not sys.stdin.isatty():
        print(
            "Refusing to create a payment session without an interactive terminal.\n"
            "Session creation requires a human typing 'approve' at a TTY. There is no\n"
            "non-interactive mode: that would let an automated caller mint spending budget.",
            file=sys.stderr,
        )
        return 1

    try:
        from bedrock_agentcore.payments import PaymentManager
    except ImportError:
        print(
            "bedrock-agentcore with payments support is not installed.\n"
            "Install a version that provides bedrock_agentcore.payments, e.g.:\n"
            "  python -m pip install --upgrade 'bedrock-agentcore>=1.19.0'",
            file=sys.stderr,
        )
        return 1

    config_path = admin_config_path(args.path)
    region = resolve_region(args.region, config_path)

    if not _check_aws_credentials(region):
        return 1

    user_id = resolve_user_id(args.user_id, config_path)
    if not user_id:
        print(
            "No payer identity found. Run init-config first (it generates one), or "
            "pass --user-id explicitly.",
            file=sys.stderr,
        )
        return 1

    manager_arn = resolve_manager_arn(args.manager_arn, config_path)
    if not manager_arn:
        checked = ", ".join(str(p) for p in deployed_state_candidates())
        print(
            f"Could not determine the payment manager ARN.\n\n"
            f"Searched for deployed-state.json at: {checked}\n\n"
            "This file is created by `agentcore deploy`. To resolve:\n"
            "  \u2022 Run this command from the directory that CONTAINS the agentcore/ folder, OR\n"
            "  \u2022 Run from inside the agentcore/ directory itself, OR\n"
            "  \u2022 Pass --manager-arn explicitly, OR\n"
            "  \u2022 Set PAYMENT_MANAGER_ARN in your environment.",
            file=sys.stderr,
        )
        return 1

    print("About to create a payment session:")
    print(f"  manager   : {manager_arn}")
    print(f"  payer     : {user_id}")
    print(f"  budget    : {args.budget} USD (hard cap for the whole session)")
    print(f"  expires in: {args.expiry_minutes} minutes")
    if input("Type 'approve' to continue: ").strip() != "approve":
        print("Aborted. No session created.")
        return 1

    manager = PaymentManager(
        payment_manager_arn=manager_arn,
        region_name=region,
        agent_name=AGENT_NAME,
    )
    session = manager.create_payment_session(
        user_id=user_id,
        expiry_time_in_minutes=args.expiry_minutes,
        limits={"maxSpendAmount": {"value": str(args.budget), "currency": "USD"}},
    )
    session_id = session["paymentSessionId"]
    update_resources(config_path, payment_session_id=session_id, user_id=user_id)

    print(f"\nPayment session created: {session_id}")
    print(f"Recorded in            : {config_path}  (nothing to copy by hand)")
    print(
        f"\nThis session allows {args.budget} USD of CUMULATIVE spend. Each individual\n"
        "payment is additionally capped by max_per_payment_usd in the policy section —\n"
        "run show-config to see it. Both bounds apply."
    )
    print(
        "\nWhen this budget is spent, the agent CANNOT mint another session — by design.\n"
        "Re-run this command yourself to authorize more spending."
    )
    return 0


def _prompt(question: str, default: str = "") -> str:
    """Prompt with an optional default shown in brackets."""
    suffix = f" [{default}]: " if default else ": "
    answer = input(question + suffix).strip()
    return answer or default


def parse_positive_decimal(value: str, label: str) -> Decimal:
    """Parse a human-entered positive decimal without float rounding."""
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label} must be a decimal number.") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{label} must be greater than zero.")
    return amount


def usd_to_atomic(value: Decimal, decimals: int = USDC_DECIMALS) -> str:
    """Convert a decimal stablecoin amount to exact atomic units."""
    atomic = value * (Decimal(10) ** decimals)
    if atomic != atomic.to_integral_value():
        raise ValueError(
            f"Max per-payment USD supports at most {decimals} decimal places."
        )
    return str(int(atomic))


def format_duration(minutes: int) -> str:
    """Render minutes with a compact hours hint for human review."""
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{minutes} minutes ({hours} hour{'s' if hours != 1 else ''})"
    return f"{minutes} minutes"


def build_openclaw_config(
    *,
    region: str,
    manager_arn: str,
    instrument_id: str,
    session_id: str,
    user_id: str,
    network: str,
    asset: str,
    max_payment_atomic: str,
    recipients: list[str],
    allow_any: bool,
    origins: list[str],
    return_body: bool,
) -> dict:
    """Build the final OpenClaw configuration from validated wizard inputs."""
    plugin_config = {
        "region": region,
        "paymentManagerArn": manager_arn,
        "paymentInstrumentId": instrument_id,
        "payment_session_id": session_id,
        "userId": user_id,
        "networkPreferences": [network],
        "allowedAssetsByNetwork": {network: [asset]},
        "maxPaymentAmountAtomic": max_payment_atomic,
        "returnBody": return_body,
    }
    if allow_any:
        plugin_config["allowAnyRecipient"] = True
    else:
        plugin_config["allowedRecipients"] = recipients
    if origins:
        plugin_config["allowedOrigins"] = origins

    return {
        "plugins": {
            "allow": ["aws-agents-pay"],
            "entries": {
                "aws-agents-pay": {
                    "enabled": True,
                    "config": plugin_config,
                },
            },
        }
    }


def cmd_setup_openclaw(args: argparse.Namespace) -> int:
    """Interactive guided setup for OpenClaw — collects inputs once and threads through."""
    if not sys.stdin.isatty():
        print("setup-openclaw requires an interactive terminal.", file=sys.stderr)
        return 1
    project_dir = (
        Path(args.project_dir).expanduser().resolve()
        if args.project_dir
        else None
    )
    if project_dir and not project_dir.is_dir():
        print(f"AgentCore project directory does not exist: {project_dir}", file=sys.stderr)
        return 1

    print("\n" + "=" * 60)
    print("  AWS Agents Pay — OpenClaw Setup")
    print("=" * 60)
    print("\nThis wizard provisions payment resources and generates your")
    print("OpenClaw plugin configuration. You'll need:")
    print("  • agentcore CLI installed and deployed (agentcore deploy)")
    print("  • bedrock-agentcore Python package (>=1.19.0)")
    print("  • AWS credentials with the ManagementRole")
    if project_dir:
        print(f"  • AgentCore project: {project_dir}")
    print()

    # --- Prerequisites check ---
    try:
        from bedrock_agentcore.payments import PaymentManager
    except ImportError:
        print(
            "[FAIL] bedrock_agentcore.payments is not installed.\n"
            "Run: python -m pip install --upgrade 'bedrock-agentcore>=1.19.0'",
            file=sys.stderr,
        )
        return 1

    if not _check_aws_credentials():
        return 1

    # --- Step 1: User identity ---
    print("\n--- Step 1: User Identity ---")
    print("A stable userId ties your instrument and session together.")
    user_id = _prompt("User ID (blank to auto-generate)", "")
    if not user_id:
        user_id = generate_user_id()
        print(f"  Generated: {user_id}")

    # --- Step 2: Region ---
    region = _prompt("AWS region", "us-east-1")

    # --- Step 3: Network ---
    print("\n--- Step 2: Network ---")
    print(f"Known networks: {', '.join(KNOWN_USDC.keys())}")
    network = _prompt("CAIP-2 network", "eip155:84532")
    if network not in KNOWN_USDC:
        print(f"Unknown network {network}. Known: {', '.join(KNOWN_USDC)}", file=sys.stderr)
        return 1
    asset = KNOWN_USDC[network]

    # --- Step 4: Recipient mode ---
    print("\n--- Step 3: Recipient Mode ---")
    print("  1. Allowlist specific merchant addresses (recommended)")
    print("  2. Allow any recipient (high risk — publisher chooses beneficiary)")
    mode = _prompt("Choice", "1")
    recipients: list[str] = []
    allow_any = False
    if mode == "2":
        allow_any = True
        print("  ⚠ allow-any-recipient enabled.")
    else:
        print("Enter merchant wallet addresses (one per line, blank to finish):")
        while True:
            addr = input("  payTo: ").strip()
            if not addr:
                break
            recipients.append(addr)
        if not recipients:
            print("At least one recipient is required.", file=sys.stderr)
            return 1

    # --- Step 5: Per-payment cap ---
    print("\n--- Step 4: Spend Limits ---")
    max_usd_text = _prompt(
        "Max per-payment USD (for example 0.10, not atomic units)",
        "0.05",
    )
    try:
        max_usd = parse_positive_decimal(max_usd_text, "Max per-payment USD")
        max_payment_atomic = usd_to_atomic(max_usd)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"  ${format(max_usd, 'f')} USD = {max_payment_atomic} atomic units "
        f"(USDC, {USDC_DECIMALS} decimals)"
    )
    budget_text = _prompt("Cumulative session budget USD", "5.00")
    expiry_text = _prompt("Session expiry in minutes (1440 = 24 hours)", "120")
    try:
        budget = parse_positive_decimal(budget_text, "Session budget USD")
        expiry = int(expiry_text)
        if expiry <= 0:
            raise ValueError("Expiry minutes must be greater than zero.")
        if max_usd > budget:
            raise ValueError(
                "Max per-payment USD cannot exceed the cumulative session budget. "
                "Enter decimal USD values, not atomic units."
            )
    except (ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # --- Step 6: Origins ---
    print("\nAllowed origins (blank to allow any public HTTPS site):")
    origins: list[str] = []
    while True:
        origin = input("  origin: ").strip()
        if not origin:
            break
        origins.append(origin)

    # --- Step 7: Return body ---
    print("\n--- Step 5: Paid Content Return ---")
    print(
        "By default, paid publisher content is withheld from the model's context "
        "as a security\ncontrol — the response body may contain prompt injection. "
        "Returning it lets the agent\nread/summarize what it paid for, at that risk."
    )
    return_body_answer = _prompt("Return paid response body to the agent? (y/n)", "y")
    return_body = return_body_answer.strip().lower() not in ("n", "no", "false", "0")

    # --- Write config ---
    config_path = admin_config_path(args.path)
    config: dict = {"resources": {}, "policy": {}}
    config["resources"]["user_id"] = user_id
    config["resources"]["region"] = region
    config["policy"] = {
        "max_per_payment_usd": format(max_usd, "f"),
        "allowed_networks": [network],
        "allowed_assets": {network: [asset]},
        "allowed_schemes": ["exact"],
        "return_body": return_body,
    }
    if allow_any:
        config["policy"]["allow_any_recipient"] = True
    else:
        config["policy"]["allowed_recipients"] = recipients
    if origins:
        config["policy"]["allowed_origins"] = origins

    # Discover manager ARN
    discovered = discover_deployed(project_dir)
    manager_arn = discovered["manager_arn"]
    connector_id = discovered["connector_id"]
    if not manager_arn:
        checked = ", ".join(str(p) for p in deployed_state_candidates(project_dir))
        print(
            "\nCould not auto-discover payment manager ARN from deployed-state.json.\n"
            f"Checked: {checked}"
        )
        manager_arn = _prompt("Payment Manager ARN", "")
        if not manager_arn:
            print("Manager ARN is required.", file=sys.stderr)
            return 1
    else:
        print(f"\n  Discovered manager ARN: {manager_arn}")
    config["resources"]["payment_manager_arn"] = manager_arn

    if not connector_id:
        connector_id = _prompt("Payment Connector ID", "")
        if not connector_id:
            print("Connector ID is required.", file=sys.stderr)
            return 1
    else:
        print(f"  Discovered connector ID: {connector_id}")

    save_config(config_path, config)
    print(f"\n  ✓ Config written to {config_path}")
    print(
        f"  Paid response body will be {'RETURNED to' if return_body else 'WITHHELD from'} "
        "the agent (policy.return_body)."
    )

    # --- Create instrument ---
    print("\n--- Step 6: Create Payment Instrument ---")
    email = _prompt("End-user email (for wallet delegation)", "")
    if not email:
        print("Email is required for instrument creation.", file=sys.stderr)
        return 1

    network_family = "ETHEREUM" if "eip155" in network else "SOLANA"
    manager = PaymentManager(
        payment_manager_arn=manager_arn,
        region_name=region,
        agent_name=AGENT_NAME,
    )
    instrument = manager.create_payment_instrument(
        user_id=user_id,
        payment_connector_id=connector_id,
        payment_instrument_type="EMBEDDED_CRYPTO_WALLET",
        payment_instrument_details={
            "embeddedCryptoWallet": {
                "network": network_family,
                "linkedAccounts": [{"email": {"emailAddress": email}}],
            }
        },
    )
    instrument_id = instrument["paymentInstrumentId"]
    wallet = (instrument.get("paymentInstrumentDetails") or {}).get("embeddedCryptoWallet", {})
    wallet_address = wallet.get("walletAddress")
    redirect_url = wallet.get("redirectUrl")

    update_resources(config_path, payment_instrument_id=instrument_id)
    print(f"  ✓ Instrument created: {instrument_id}")
    print(f"    Wallet: {wallet_address}")

    # --- Delegation + funding ---
    print("\n--- Step 7: Delegate & Fund ---")
    if redirect_url:
        print(f"  1. Visit: {redirect_url}")
        print(f"     Sign in and grant access to {wallet_address}")
    else:
        print("  1. Approve via the Privy frontend SDK")
    print(f"  2. Send testnet USDC to {wallet_address}")
    print("     https://faucet.circle.com/ (Base Sepolia)")
    print()
    input("Press Enter when delegation and funding are complete...")

    # --- Create session ---
    print("\n--- Step 8: Create Payment Session ---")
    print(f"\n  About to create session:")
    print(f"    Budget:          ${format(budget, 'f')} USD cumulative")
    print(
        f"    Per-payment cap: ${format(max_usd, 'f')} USD "
        f"({max_payment_atomic} atomic units)"
    )
    print(f"    Expiry:          {format_duration(expiry)}")
    print(f"    User:            {user_id}")
    if input("  Type 'approve' to continue: ").strip() != "approve":
        print("Aborted. No session created.")
        return 1

    session = manager.create_payment_session(
        user_id=user_id,
        expiry_time_in_minutes=expiry,
        limits={
            "maxSpendAmount": {
                "value": format(budget, "f"),
                "currency": "USD",
            }
        },
    )
    session_id = session["paymentSessionId"]
    update_resources(config_path, payment_session_id=session_id)
    print(f"  ✓ Session created: {session_id}")

    # --- Generate OpenClaw config ---
    print("\n" + "=" * 60)
    print("  ✅ Setup complete!")
    print("=" * 60)
    print("\nAdd this to your OpenClaw config (~/.openclaw/openclaw.json):")
    print()
    openclaw_config = build_openclaw_config(
        region=region,
        manager_arn=manager_arn,
        instrument_id=instrument_id,
        session_id=session_id,
        user_id=user_id,
        network=network,
        asset=asset,
        max_payment_atomic=max_payment_atomic,
        recipients=recipients,
        allow_any=allow_any,
        origins=origins,
        return_body=return_body,
    )

    print(json.dumps(openclaw_config, indent=2))
    print("\nThen restart OpenClaw to activate the plugin.")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    """Verify runtime wiring and assert no secret-shaped values are exposed."""
    ok = True

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import x402_policy as pol

        policy = pol.load_config(admin_config_path(args.path))
        print(f"[ok]   policy loaded, max_per_payment_usd={policy['max_per_payment_usd']}")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] policy: {e}")
        ok = False

    required = ("PAYMENT_MANAGER_ARN", "PAYMENT_INSTRUMENT_ID", "PAYMENT_SESSION_ID", "PAYMENT_USER_ID")
    for var in required:
        print(f"[{'ok' if os.environ.get(var) else '--'}]   {var}{'' if os.environ.get(var) else ' not set'}")

    # If the manager ARN is missing but discoverable, hand the operator the exact
    # line to run rather than making them dig it out of deployed-state.json.
    if not os.environ.get("PAYMENT_MANAGER_ARN"):
        discovered = discover_deployed()
        if discovered["manager_arn"]:
            state_path = _find_deployed_state()
            print(f"\n       Found in {state_path}: run this to fix the above ->")
            print(f"         export PAYMENT_MANAGER_ARN={discovered['manager_arn']}")
        else:
            print(
                "\n       deployed-state.json not found "
                f"(checked: {', '.join(str(p) for p in deployed_state_candidates())})."
            )
            print("       Run from the directory that CONTAINS the agentcore/ folder,")
            print("       from inside it, or set the variables by hand.")

    # This design never needs provider secrets in the runtime process.
    leaked = [
        k
        for k in os.environ
        if any(t in k.upper() for t in ("CDP_API_KEY_SECRET", "WALLET_SECRET", "APP_SECRET", "AUTHORIZATION_PRIVATE_KEY"))
    ]
    if leaked:
        print(f"[FAIL] provider secrets present in this environment: {', '.join(sorted(leaked))}")
        print("       The runtime must never hold provider credentials; signing happens in AgentCore.")
        ok = False
    else:
        print("[ok]   no provider secrets in the runtime environment")

    try:
        from bedrock_agentcore.payments import PaymentManager  # noqa: F401

        print("[ok]   bedrock_agentcore.payments available")
    except ImportError:
        print("[--]   bedrock_agentcore.payments not installed (needed only to settle payments)")

    print("\nPreflight " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Trusted admin CLI for agents-pay. Run by a human, never by an agent.",
        epilog="This tool never accepts provider secrets as arguments.",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-config", help="Write the config file: resources + policy (mode 0600)")
    p.add_argument("--max-per-payment-usd", default="0.10",
                   help="PER-PAYMENT ceiling in USD (default 0.10). Distinct from the "
                        "session budget, which is cumulative.")
    p.add_argument("--region", default=None, help="AWS region to record in the config")
    p.add_argument("--user-id", default=None,
                   help="Payer identity. Omit to have one generated (single-tenant default).")
    p.add_argument("--network", default="eip155:84532", help="CAIP-2 network (default Base Sepolia testnet)")
    recipient_mode = p.add_mutually_exclusive_group(required=True)
    recipient_mode.add_argument(
        "--recipient",
        action="append",
        help="Approved merchant payTo wallet address (repeatable).",
    )
    recipient_mode.add_argument(
        "--allow-any-recipient",
        action="store_true",
        help="Allow any challenge payTo. High risk: the publisher chooses the beneficiary.",
    )
    p.add_argument("--origin", action="append", default=[],
                   help="Pin to these https origins (repeatable). Omit to allow the open web.")
    p.add_argument("--path", default=None, help="Config path (default ~/.agents-pay/config.json)")
    p.add_argument("--force", action="store_true", help="Overwrite an existing policy")
    p.set_defaults(func=cmd_init_config)

    p = sub.add_parser("show-config", help="Show the active config and its permissions")
    p.add_argument("--path", default=None)
    p.set_defaults(func=cmd_show_config)

    p = sub.add_parser("create-instrument", help="Create a per-user wallet (instrument)")
    p.add_argument("--user-id", default=None,
                   help="Override the payer identity (default: read from the config, which "
                        "init-config generated). Single-tenant, so rarely needed.")
    p.add_argument("--email", required=True, help="End-user email, linked to the wallet for delegation")
    p.add_argument("--network-family", default="ETHEREUM", help="ETHEREUM (covers Base) or SOLANA")
    p.add_argument("--manager-arn", default=None, help="Default: read from the CLI deploy record")
    p.add_argument("--connector-id", default=None, help="Default: read from the CLI deploy record")
    p.add_argument("--region", default=None)
    p.add_argument("--path", default=None, help="Config path (default ~/.agents-pay/config.json)")
    p.set_defaults(func=cmd_create_instrument)

    p = sub.add_parser("new-session", help="Create a budget-bounded session (human approval)")
    p.add_argument("--user-id", default=None, help="Override the payer identity (rarely needed)")
    p.add_argument("--budget", required=True, help="Session spend cap in USD")
    p.add_argument("--expiry-minutes", type=int, default=60, help="Session lifetime (default 60)")
    p.add_argument("--manager-arn", default=None)
    p.add_argument("--region", default=None)
    p.add_argument("--path", default=None, help="Config path (default ~/.agents-pay/config.json)")
    # No --yes flag by design: see cmd_new_session. Approval requires a TTY.
    p.set_defaults(func=cmd_new_session)

    p = sub.add_parser("preflight", help="Verify wiring and check for exposed secrets")
    p.add_argument("--path", default=None)
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("setup-openclaw", help="Interactive guided setup for OpenClaw (all steps in one flow)")
    p.add_argument("--path", default=None, help="Config path (default ~/.agents-pay/config.json)")
    p.add_argument(
        "--project-dir",
        default=None,
        help=(
            "AgentCore project directory used to locate deployed-state.json "
            "(or set AGENTCORE_PROJECT_DIR)"
        ),
    )
    p.set_defaults(func=cmd_setup_openclaw)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
