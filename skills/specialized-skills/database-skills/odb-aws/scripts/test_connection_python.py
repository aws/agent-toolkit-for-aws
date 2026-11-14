#!/usr/bin/env python3
"""test_connection_python.py — Test python-oracledb connection to ODB@AWS.

Usage:
  # TCP
  python3 test_connection_python.py --scan-host <host> --port 1521 --service <svc> --user <user>

  # TCPS with wallet
  python3 test_connection_python.py --scan-host <host> --port 2484 --service <svc> --user <user> --wallet-dir /path/to/wallet
"""

import argparse
import getpass
import sys
import time


def main():
    parser = argparse.ArgumentParser(description="Test ODB@AWS connection via python-oracledb")
    parser.add_argument("--scan-host", required=True, help="SCAN hostname")
    parser.add_argument("--port", type=int, default=1521, help="Port (default: 1521)")
    parser.add_argument("--service", required=True, help="Service name")
    parser.add_argument("--user", required=True, help="Database username")
    parser.add_argument("--password", help="Database password (prompted if not provided)")
    parser.add_argument("--wallet-dir", help="Wallet directory (for TCPS)")
    parser.add_argument("--wallet-password", help="Wallet password (prompted if wallet-dir set)")
    args = parser.parse_args()

    try:
        import oracledb
    except ImportError:
        print("❌ python-oracledb not installed. Run: pip install oracledb")
        sys.exit(1)

    dsn = f"{args.scan_host}:{args.port}/{args.service}"
    print(f"=== ODB@AWS Connection Test (python-oracledb thin mode) ===")
    print(f"DSN: {dsn}")
    print(f"User: {args.user}")
    print(f"Wallet: {args.wallet_dir or 'None (TCP mode)'}")
    print()

    # Get password
    if not args.password:
        args.password = getpass.getpass("Database password: ")

    if args.wallet_dir and not args.wallet_password:
        args.wallet_password = getpass.getpass("Wallet password: ")

    # Build connection kwargs
    connect_kwargs = {
        "user": args.user,
        "password": args.password,
        "dsn": dsn,
    }
    if args.wallet_dir:
        connect_kwargs["config_dir"] = args.wallet_dir
        connect_kwargs["wallet_location"] = args.wallet_dir
        connect_kwargs["wallet_password"] = args.wallet_password

    # Connect
    print("--- Connecting ---")
    start = time.time()
    try:
        conn = oracledb.connect(**connect_kwargs)
        elapsed = time.time() - start
        print(f"✅ Connected in {elapsed:.2f}s")
    except oracledb.DatabaseError as e:
        elapsed = time.time() - start
        error = e.args[0]
        print(f"❌ Connection failed after {elapsed:.2f}s")
        print(f"   Error: {error.message}")
        print(f"   Code: ORA-{error.code}")
        sys.exit(1)

    # Run test queries
    print()
    print("--- Test Queries ---")
    try:
        with conn.cursor() as cursor:
            # Database version
            cursor.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
            row = cursor.fetchone()
            print(f"✅ Database: {row[0]}")

            # Instance name
            cursor.execute("SELECT instance_name, host_name FROM v$instance")
            row = cursor.fetchone()
            print(f"✅ Instance: {row[0]} on {row[1]}")

            # Service name
            cursor.execute("SELECT sys_context('USERENV', 'SERVICE_NAME') FROM DUAL")
            row = cursor.fetchone()
            print(f"✅ Service: {row[0]}")

            # Current user
            cursor.execute("SELECT USER FROM DUAL")
            row = cursor.fetchone()
            print(f"✅ User: {row[0]}")

            # Encryption status
            cursor.execute("""
                SELECT network_service_banner
                FROM v$session_connect_info
                WHERE sid = SYS_CONTEXT('USERENV', 'SID')
                AND network_service_banner LIKE '%Encryption%'
            """)
            row = cursor.fetchone()
            if row:
                print(f"✅ Encryption: {row[0]}")
            else:
                print("⚠️  Encryption: Not detected (TCP mode)")

    except oracledb.DatabaseError as e:
        print(f"⚠️  Query failed: {e}")
    finally:
        conn.close()

    print()
    print("=== Connection test passed ✅ ===")


if __name__ == "__main__":
    main()
