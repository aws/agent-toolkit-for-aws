#!/usr/bin/env python3
"""Provision per-user AgentCore Payments data-plane resources (instrument + optional session).

Control-plane (manager/connector/credential provider) is created by the AgentCore CLI.
This script uses the AgentCore SDK for the data plane:
  - one payment instrument (wallet) per end user
  - optionally one budget-bounded payment session

Usage:
  python setup_payment_user.py --user-id alice --email alice@example.com \
      [--manager-arn ...] [--connector-id ...] [--target staging]
  python setup_payment_user.py --user-id alice --session-only \
      --instrument-id <id> --budget 5 [--target staging]

Manager ARN / connector ID are read from `agentcore status --target <target> --json`
for v1 projects. The default target is "default".
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

def _from_deployed_state(target="default", manager_arn=None):
    """Discover only an unambiguous manager/connector pair for the selected target."""
    if Path("agentcore/agentcore.json").exists():
        try:
            result = subprocess.run(
                ["agentcore", "status", "--target", target, "--json"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode == 0:
                managers = [
                    resource for resource in json.loads(result.stdout).get("resources", [])
                    if resource.get("resourceType") == "payment-manager"
                    and resource.get("arn")
                    and (manager_arn is None or resource["arn"] == manager_arn)
                ]
                if len(managers) == 1:
                    connectors = [
                        child for child in managers[0].get("children", [])
                        if child.get("resourceType") == "payment-connector" and child.get("id")
                    ]
                    return managers[0]["arn"], connectors[0]["id"] if len(connectors) == 1 else None
                return None, None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass

    # Legacy v0 projects recorded payment outputs in deployed state.
    try:
        if json.loads(Path("agentcore/agentcore.json").read_text()).get("version") == 2:
            return None, None
    except (OSError, ValueError):
        pass
    path = Path("agentcore/.cli/deployed-state.json")
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text())
        payments = None
        targets = data.get("targets") or {}
        legacy_target = targets.get(target) or {}
        if isinstance(legacy_target, dict):
            payments = (legacy_target.get("resources") or {}).get("payments")
        if not payments:
            payments = data.get("payments")  # legacy/top-level fallback
        if not payments:
            return None, None
        managers = list(payments.values()) if isinstance(payments, dict) else payments
        managers = [pay for pay in managers if manager_arn is None or pay.get("managerArn") == manager_arn]
        if len(managers) != 1:
            return None, None
        pay = managers[0]
        connectors = pay.get("connectors") or []
        connectors = list(connectors.values()) if isinstance(connectors, dict) else connectors
        connectors = [connector for connector in connectors if connector.get("connectorId")]
        return pay.get("managerArn"), connectors[0]["connectorId"] if len(connectors) == 1 else None
    except Exception:
        return None, None


def main():
    ap = argparse.ArgumentParser(description="Provision a per-user AgentCore Payments instrument")
    ap.add_argument("--user-id", required=True, help="Stable end-user identifier")
    ap.add_argument("--email", help="End-user email (required when creating an instrument)")
    ap.add_argument("--budget", default=None, help="Optional session spend cap in USD, e.g. 5")
    ap.add_argument("--session-only", action="store_true",
                    help="Create a session for an existing instrument after delegation and funding")
    ap.add_argument("--instrument-id", help="Existing instrument ID (required with --session-only)")
    ap.add_argument("--expiry-minutes", type=int, default=60, help="Session expiry, 15-480")
    ap.add_argument("--network", default="ETHEREUM", help="Wallet network family: ETHEREUM or SOLANA")
    ap.add_argument("--manager-arn", default=os.environ.get("PAYMENT_MANAGER_ARN"))
    ap.add_argument("--connector-id", default=os.environ.get("PAYMENT_CONNECTOR_ID"))
    ap.add_argument("--region", help="SDK region override; defaults to the payment manager ARN's region")
    ap.add_argument("--target", default=os.environ.get("AGENTCORE_TARGET", "default"),
                    help="AgentCore deployment target used for status discovery")
    args = ap.parse_args()
    if args.session_only:
        if not args.instrument_id or not args.budget:
            ap.error("--session-only requires --instrument-id and --budget")
    elif not args.email:
        ap.error("--email is required when creating an instrument")

    manager_arn, connector_id = args.manager_arn, args.connector_id
    if not manager_arn or not connector_id:
        ds_arn, ds_conn = _from_deployed_state(args.target, manager_arn)
        manager_arn = manager_arn or ds_arn
        connector_id = connector_id or ds_conn
    if not manager_arn or (not args.session_only and not connector_id):
        sys.exit("Could not resolve a unique payment manager and connector for this target. Pass "
                 "--manager-arn and, when creating an instrument, --connector-id; or check "
                 "`agentcore status --target <target> --json` in the deployed project.")

    from bedrock_agentcore.payments import PaymentManager

    region = args.region or manager_arn.split(":")[3]
    manager = PaymentManager(payment_manager_arn=manager_arn, region_name=region)

    wallet_address = None
    redirect_url = None
    if args.session_only:
        instrument_id = args.instrument_id
    else:
        # Data plane: per-user instrument (wallet). Email -> linkedAccounts.
        instrument = manager.create_payment_instrument(
            user_id=args.user_id,
            payment_connector_id=connector_id,
            payment_instrument_type="EMBEDDED_CRYPTO_WALLET",
            payment_instrument_details={
                "embeddedCryptoWallet": {
                    "network": args.network,
                    "linkedAccounts": [{"email": {"emailAddress": args.email}}],
                }
            },
        )
        instrument_id = instrument["paymentInstrumentId"]
        wallet = instrument.get("paymentInstrumentDetails", {}).get("embeddedCryptoWallet", {})
        wallet_address = wallet.get("walletAddress")
        redirect_url = wallet.get("redirectUrl")  # Coinbase delegation URL; None for Privy

    # Data plane: optional budget-bounded session. NOTE: cap key is "value", not "amount".
    session_id = None
    if args.budget:
        session = manager.create_payment_session(
            user_id=args.user_id,
            expiry_time_in_minutes=args.expiry_minutes,
            limits={"maxSpendAmount": {"value": str(args.budget), "currency": "USD"}},  # cap currency is USD
        )
        session_id = session["paymentSessionId"]

    print("Instrument ID :", instrument_id)
    print("Wallet address:", wallet_address)
    print("Session ID    :", session_id or "(none - create an approved session before spending)")
    print("\nExport these for the x402 tool (Step 8):")
    print(f"  export PAYMENT_MANAGER_ARN={manager_arn}")
    print(f"  export PAYMENT_INSTRUMENT_ID={instrument_id}")
    if session_id:
        print(f"  export PAYMENT_SESSION_ID={session_id}")
    print(f"  export PAYMENT_USER_ID={args.user_id}")
    print(f"  export AWS_REGION={region}")
    if not args.session_only:
        print("\nOne-time per wallet:")
        if redirect_url:
            print(f"  1. Delegation (Coinbase): visit {redirect_url}, log in, grant access to {wallet_address}")
        else:
            print("  1. Delegation (Privy): approve delegation via the Privy frontend SDK")
        print(f"  2. Funding: send testnet USDC to {wallet_address} via https://faucet.circle.com/ (Base Sepolia)")


if __name__ == "__main__":
    main()
