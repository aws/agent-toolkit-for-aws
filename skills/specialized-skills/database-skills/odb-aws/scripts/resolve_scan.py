#!/usr/bin/env python3
"""resolve_scan.py — Verify SCAN hostname resolution from app VPC.

Usage: python3 resolve_scan.py <scan-hostname> [dns-listener-ip]

Checks:
  1. SCAN hostname resolves via default DNS
  2. If dns-listener-ip provided, also tests direct resolution against ODB DNS
"""

import socket
import subprocess
import sys


def resolve_hostname(hostname: str) -> list[str]:
    """Resolve hostname using system DNS."""
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_INET)
        return sorted(set(r[4][0] for r in results))
    except socket.gaierror:
        return []


def resolve_via_dig(hostname: str, dns_server: str | None = None) -> list[str]:
    """Resolve hostname using dig (if available)."""
    cmd = ["dig", "+short", hostname]
    if dns_server:
        cmd.insert(1, f"@{dns_server}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        ips = [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        return sorted(ips)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 resolve_scan.py <scan-hostname> [dns-listener-ip]")
        sys.exit(1)

    hostname = sys.argv[1]
    dns_listener = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"=== SCAN Hostname Resolution Check ===")
    print(f"Hostname: {hostname}")
    print()

    # System DNS resolution
    print("--- System DNS (via VPC resolver) ---")
    ips = resolve_hostname(hostname)
    if ips:
        print(f"✅ Resolved to {len(ips)} IP(s):")
        for ip in ips:
            print(f"   {ip}")
    else:
        print(f"❌ FAILED: Cannot resolve {hostname}")
        print()
        print("Likely cause: Route 53 Resolver forwarding rule not set up")
        print("Fix: Create outbound endpoint + forwarding rule for oraclevcn.com")

        # Try dig for more detail
        dig_ips = resolve_via_dig(hostname)
        if dig_ips:
            print(f"\nNote: dig resolved it ({dig_ips}) but socket.getaddrinfo did not.")
            print("This may indicate a DNS caching issue. Try: sudo systemd-resolve --flush-caches")
    print()

    # Direct DNS listener resolution (if provided)
    if dns_listener:
        print(f"--- Direct DNS (via ODB DNS listener {dns_listener}) ---")
        dig_ips = resolve_via_dig(hostname, dns_listener)
        if dig_ips:
            print(f"✅ Resolved to {len(dig_ips)} IP(s):")
            for ip in dig_ips:
                print(f"   {ip}")
            if not ips:
                print()
                print("DNS listener works but VPC resolver doesn't → forwarding rule issue")
        else:
            print(f"❌ FAILED: Cannot resolve via DNS listener {dns_listener}")
            print("Check: Is the DNS listener IP correct? Is the ODB network healthy?")
        print()

    # Summary
    if ips:
        print("=== Resolution OK ✅ ===")
        if len(ips) == 3:
            print("3 IPs returned — typical for a 3-node RAC cluster")
        elif len(ips) == 1:
            print("1 IP returned — single-node or Autonomous DB")
    else:
        print("=== Resolution FAILED ❌ ===")
        sys.exit(1)


if __name__ == "__main__":
    main()
