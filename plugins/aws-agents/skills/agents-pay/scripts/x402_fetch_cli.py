#!/usr/bin/env python3
"""Command-line entry point for the agent: pay for a URL and print the result.

This is how a harness invokes the skill. Claude Code, Codex, Cursor, Kiro and
OpenClaw run shell commands and read files — they do not import Python and build an
agent object — so the contract is argv in, JSON on stdout. Same behaviour in every
harness, nothing to register, no framework binding.

    python3 x402_fetch_cli.py https://merchant.example/paid
    python3 x402_fetch_cli.py --status
    python3 x402_fetch_cli.py --browser-handle https://merchant.example/paid

Exit codes let a harness branch without parsing:

    0  paid, or fetched without payment being required
    2  refused by policy, or missing configuration — NOT an error to retry
    1  unexpected failure

A refusal is exit 2 and not 1 on purpose: it is a decision, not a fault. Retrying it
unchanged will refuse again.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Importable whether the harness runs this from the skill directory or by absolute
# path, without requiring PYTHONPATH to be set.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import x402_fetch  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="x402_fetch_cli.py",
        description="Pay for an x402-protected URL, or report payment session status.",
        epilog="Exit 0 = ok, 2 = refused or unconfigured, 1 = unexpected failure.",
    )
    ap.add_argument("url", nargs="?", help="The https:// URL to fetch, paying if it returns 402")
    ap.add_argument("--status", action="store_true",
                    help="Report whether the payment session can currently be spent")
    ap.add_argument("--browser-handle", metavar="URL", dest="browser_url",
                    help="Pay for URL and return an opaque single-use handle for a browser "
                         "navigation, instead of fetching the content here")
    ap.add_argument("--method", default="GET", choices=["GET", "HEAD"],
                    help="HTTP method (GET or HEAD only — a request body would let the "
                         "agent send data to an arbitrary origin)")
    ap.add_argument("--purchase-id", default=None,
                    help="Distinguish a deliberate repeat purchase of the same resource")
    args = ap.parse_args()

    if args.status:
        payload = x402_fetch.payment_session_status()
        print(payload)
        return 0 if json.loads(payload).get("usable") else 2

    target = args.browser_url or args.url
    if not target:
        ap.print_usage(sys.stderr)
        print("\nGive a URL, or --status.", file=sys.stderr)
        return 1

    if args.browser_url:
        payload = x402_fetch.prepare_browser_payment(target, args.purchase_id)
    else:
        payload = x402_fetch.x402_fetch(target, args.purchase_id, args.method)

    print(payload)
    result = json.loads(payload)
    if result.get("refused"):
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
