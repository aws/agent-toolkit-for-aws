#!/usr/bin/env python3
"""Provision per-user AgentCore Payments data-plane resources (instrument + optional session).

Control-plane (manager/connector/credential provider) is created by the AgentCore CLI.
This script uses the AgentCore SDK for the data plane:
  - one payment instrument (wallet) per end user
  - optionally one budget-bounded payment session

Usage:
  python setup_payment_user.py --user-id alice --email alice@example.com [--budget 5] \
      [--manager-arn ...] [--connector-id ...] [--region us-east-1] [--network ETHEREUM]

Manager ARN / connector ID are auto-read from agentcore/.cli/deployed-state.json if not passed.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from bedrock_agentcore.payments import PaymentManager


def _from_deployed_state():
    """Best-effort: read manager ARN + connector ID from the CLI's deployed state.

    CLI 0.20.x writes targets.<target>.resources.payments[]; older shapes used a
    top-level payments[]. Handle both.
    """
    path = Path("agentcore/.cli/deployed-state.json")
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text())
        payments = None
        targets = data.get("targets") or {}
        target = targets.get("default") or (next(iter(targets.values()), {}) if targets else {})
        if isinstance(target, dict):
            payments = (target.get("resources") or {}).get("payments")
        if not payments:
            payments = data.get("payments")  # legacy/top-level fallback
        if not payments:
            return None, None
        pay = payments[0]
        connectors = pay.get("connectors") or []
        return pay.get("managerArn"), (connectors[0].get("connectorId") if connectors else None)
    except Exception:
        return None, None


def main():
    ap = argparse.ArgumentParser(description="Provision a per-user AgentCore Payments instrument")
    ap.add_argument("--user-id", required=True, help="Stable end-user identifier")
    ap.add_argument("--email", required=True, help="End-user email (linked to the wallet; required for delegation)")
    ap.add_argument("--budget", default=None, help="Optional session spend cap in USD, e.g. 5")
    ap.add_argument("--expiry-minutes", type=int, default=60, help="Session expiry, 15-480")
    ap.add_argument("--network", default="ETHEREUM", help="Wallet network family: ETHEREUM or SOLANA")
    ap.add_argument("--manager-arn", default=os.environ.get("PAYMENT_MANAGER_ARN"))
    ap.add_argument("--connector-id", default=os.environ.get("PAYMENT_CONNECTOR_ID"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    args = ap.parse_args()

    manager_arn, connector_id = args.manager_arn, args.connector_id
    if not manager_arn or not connector_id:
        ds_arn, ds_conn = _from_deployed_state()
        manager_arn = manager_arn or ds_arn
        connector_id = connector_id or ds_conn
    if not manager_arn or not connector_id:
        sys.exit("Could not resolve manager ARN / connector ID. Pass --manager-arn and --connector-id, "
                 "or run from the project dir with agentcore/.cli/deployed-state.json present.")

    manager = PaymentManager(payment_manager_arn=manager_arn, region_name=args.region)

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
    print("Session ID    :", session_id or "(none - use `agentcore invoke --auto-session`)")
    print("\nExport these for the x402 tool (Step 8):")
    print(f"  export PAYMENT_MANAGER_ARN={manager_arn}")
    print(f"  export PAYMENT_INSTRUMENT_ID={instrument_id}")
    if session_id:
        print(f"  export PAYMENT_SESSION_ID={session_id}")
    print(f"  export PAYMENT_USER_ID={args.user_id}")
    print(f"  export AWS_REGION={args.region}")
    print("\nOne-time per wallet:")
    if redirect_url:
        print(f"  1. Delegation (Coinbase): visit {redirect_url}, log in, grant access to {wallet_address}")
    else:
        print("  1. Delegation (Privy): approve delegation via the Privy frontend SDK")
    print(f"  2. Funding: send testnet USDC to {wallet_address} via https://faucet.circle.com/ (Base Sepolia)")


if __name__ == "__main__":
    main()
