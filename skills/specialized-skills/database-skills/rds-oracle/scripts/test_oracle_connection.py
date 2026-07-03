#!/usr/bin/env python3
"""
Test Oracle connection to an RDS instance.
Usage: python3 test_oracle_connection.py <endpoint> <port> <service_name> <username>

Password is read from ORACLE_PASSWORD environment variable, or prompted interactively.

Tests: connection, basic query, encryption status, session info.
Requires: pip install oracledb
"""

import getpass
import os
import sys
import time


def main():
    verbose = "--verbose" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--verbose"]
    if len(args) < 4:
        print(
            "Usage: python3 test_oracle_connection.py <endpoint> <port> <service_name> <username> [--verbose]"
        )
        print("  Set ORACLE_PASSWORD env var, or you will be prompted.")
        print(
            "Example: ORACLE_PASSWORD=<from-secrets-manager> python3 test_oracle_connection.py mydb.xxx.us-east-1.rds.amazonaws.com 1521 ORCL admin"
        )
        sys.exit(1)

    endpoint = args[0]
    port = args[1]
    service_name = args[2]
    username = args[3]
    password = os.environ.get("ORACLE_PASSWORD") or getpass.getpass("Password: ")

    dsn = f"{endpoint}:{port}/{service_name}"

    print("=== Oracle Connection Test ===")
    # SECURITY: connection metadata (endpoint, DSN, username) is hidden by default and shown
    # only with --verbose, to avoid exposing system architecture in persisted logs. Do NOT use
    # --verbose in production or CI/CD pipelines. The password is never printed.
    if verbose:
        print(f"Endpoint:     {endpoint}")
        print(f"Port:         {port}")
        print(f"Service Name: {service_name}")
        print(f"Username:     {username}")
        print(f"DSN:          {dsn}")
    else:
        print("(connection metadata hidden; pass --verbose to show endpoint/DSN/username)")
    print()

    try:
        import oracledb
    except ImportError:
        print("FAIL: oracledb not installed")
        print("  Fix: pip install oracledb")
        sys.exit(1)

    print(f"Driver:       python-oracledb {oracledb.__version__}")
    print(f"Mode:         {'Thick' if not oracledb.is_thin_mode() else 'Thin'}")
    print()

    print("--- Connection Test ---")
    start = time.time()
    try:
        conn = oracledb.connect(user=username, password=password, dsn=dsn)
        elapsed = time.time() - start
        print(f"PASS: Connected in {elapsed:.2f}s")
        print(f"  Database version: {conn.version}")
    except oracledb.DatabaseError as e:
        elapsed = time.time() - start
        (error,) = e.args
        print(f"FAIL: Connection failed after {elapsed:.2f}s")
        print(f"  ORA-{error.code}: {error.message}")
        hints = {
            12170: "TNS connect timeout — check security groups, VPC routing, endpoint",
            12541: "No listener — check endpoint and port are correct",
            1017: "Invalid username/password — check credentials",
            12514: "Listener does not know of service — check service name",
            12505: "Listener does not know of SID — try SERVICE_NAME instead of SID",
            28000: "Account is locked — unlock the user in the database",
        }
        if error.code in hints:
            print(f"  Hint: {hints[error.code]}")
        sys.exit(1)
    print()

    print("--- Query Test ---")
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sysdate, SYS_CONTEXT('USERENV', 'DB_NAME'), SYS_CONTEXT('USERENV', 'SESSION_USER') FROM dual"
        )
        row = cursor.fetchone()
        print("PASS: Query succeeded")
        print(f"  Server time:  {row[0]}")
        print(f"  Database:     {row[1]}")
        print(f"  Session user: {row[2]}")
    except oracledb.DatabaseError as e:
        (error,) = e.args
        print(f"FAIL: Query failed — ORA-{error.code}: {error.message}")
    print()

    print("--- Encryption Status ---")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT SYS_CONTEXT('USERENV', 'NETWORK_PROTOCOL') FROM dual")
        protocol = cursor.fetchone()[0]
        print(f"  Network protocol: {protocol}")
        if protocol and protocol.lower() == "tcps":
            print("  PASS: Connection is SSL/TLS encrypted (TCPS)")
        elif protocol and protocol.lower() == "tcp":
            print("  INFO: Connection is TCP (check if NNE is active below)")
        else:
            print(f"  INFO: Protocol is '{protocol}'")

        cursor.execute(
            """
            SELECT network_service_banner
            FROM v$session_connect_info
            WHERE sid = SYS_CONTEXT('USERENV', 'SID')
            AND network_service_banner IS NOT NULL
        """
        )
        banners = cursor.fetchall()
        if banners:
            for banner in banners:
                print(f"  Banner: {banner[0]}")
                if "encryption" in str(banner[0]).lower() or "crypto" in str(banner[0]).lower():
                    print("  PASS: Encryption is active (NNE or SSL)")
        else:
            print("  INFO: No encryption banners found — connection may be unencrypted")
    except oracledb.DatabaseError as e:
        (error,) = e.args
        print(f"  WARN: Cannot check encryption — ORA-{error.code}: {error.message}")
        print("  (This may require additional privileges)")
    print()

    print("--- Authentication Info ---")
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT SYS_CONTEXT('USERENV', 'AUTHENTICATION_METHOD'),
                   SYS_CONTEXT('USERENV', 'AUTHENTICATED_IDENTITY'),
                   SYS_CONTEXT('USERENV', 'HOST')
            FROM dual
        """
        )
        row = cursor.fetchone()
        print(f"  Auth method:  {row[0]}")
        print(f"  Identity:     {row[1]}")
        print(f"  Client host:  {row[2]}")
    except oracledb.DatabaseError as e:
        (error,) = e.args
        print(f"  WARN: Cannot check auth info — ORA-{error.code}")
    print()

    conn.close()
    print("=== All tests passed ===")


if __name__ == "__main__":
    main()
