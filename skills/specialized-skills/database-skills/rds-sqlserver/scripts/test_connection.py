#!/usr/bin/env python3
"""
Test connection to RDS SQL Server via pymssql.

Validates connectivity, encryption, auth method, TLS, and server version.

Usage:
    # Basic SQL auth
    python test_connection.py --server mydb.abc123.us-east-1.rds.amazonaws.com \
        --user admin --password 'MyP@ss' --database mydb

    # Secrets Manager
    python test_connection.py --server mydb.abc123.us-east-1.rds.amazonaws.com \
        --secret-id mydb/credentials

    # IAM auth via RDS Proxy
    python test_connection.py --server myproxy.proxy-abc123.us-east-1.rds.amazonaws.com \
        --user iam_user --iam --database mydb

Requires: pymssql, boto3 (for --secret-id or --iam)
"""

import argparse
import json
import sys


def get_credentials_from_secret(secret_id, region=None):
    import boto3

    client = boto3.client("secretsmanager", **({"region_name": region} if region else {}))
    secret = json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
    return {
        "server": secret.get("host"),
        "port": str(secret.get("port", 1433)),
        "user": secret.get("username"),
        "password": secret.get("password"),
        "database": secret.get("dbname", "master"),
    }


def get_iam_token(server, port, user, region=None):
    import boto3

    client = boto3.client("rds", **({"region_name": region} if region else {}))
    return client.generate_db_auth_token(
        DBHostname=server,
        Port=int(port),
        DBUsername=user,
    )


def test_network_only(server, port, timeout=10):
    """Phase 1: Test TCP reachability and TLS handshake without credentials."""
    import socket
    import ssl

    results = {}
    passed = 0
    failed = 0

    print(f"\n{'='*60}")
    print(f"Network Test: {server}:{port}")
    print(f"{'='*60}")

    # 1. DNS resolution
    try:
        ip = socket.gethostbyname(server)
        print(f"\n✅ DNS: {server} → {ip}")
        results["dns"] = ip
        passed += 1
    except socket.gaierror as e:
        print(f"\n❌ DNS: Cannot resolve {server} — {e}")
        failed += 1
        print_summary(passed, failed, results)
        return False

    # 2. TCP connectivity
    try:
        sock = socket.create_connection((server, int(port)), timeout=timeout)
        print(f"✅ TCP: Port {port} reachable")
        results["tcp"] = True
        passed += 1
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        print(f"❌ TCP: Port {port} unreachable — {e}")
        print("   Check: security group inbound rules, NACLs, subnet routing")
        failed += 1
        print_summary(passed, failed, results)
        return False

    # 3. TLS handshake
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        tls_sock = ctx.wrap_socket(sock, server_hostname=server)
        tls_version = tls_sock.version()
        print(f"✅ TLS: Handshake succeeded ({tls_version})")
        results["tls"] = tls_version
        passed += 1
        tls_sock.close()
    except ssl.SSLError as e:
        print(f"⚠️  TLS: Handshake failed — {e}")
        print("   Note: SQL Server uses TDS-level encryption, not pure TLS on connect.")
        print("   This may be OK — proceed to full connection test.")
        results["tls"] = "TDS-level (not pure TLS)"
        passed += 1  # Not a failure for SQL Server
        sock.close()

    print_summary(passed, failed, results)
    return failed == 0


def test_connection(server, port, user, password, database, tds_version, encryption, login_timeout):
    import pymssql

    results = {}
    passed = 0
    failed = 0

    # 1. Connect
    print(f"\n{'='*60}")
    print(f"Testing: {server}:{port}/{database}")
    print(f"User: {user} | TDS: {tds_version} | Encryption: {encryption}")
    print(f"{'='*60}")

    try:
        conn = pymssql.connect(
            server=server,
            port=port,
            user=user,
            password=password,
            database=database,
            tds_version=tds_version,
            encryption=encryption,
            login_timeout=login_timeout,
        )
        print(f"\n✅ CONNECT: Success")
        passed += 1
    except Exception as e:
        print(f"\n❌ CONNECT: Failed — {e}")
        failed += 1
        results["connect"] = {"status": "FAIL", "error": str(e)}
        print_summary(passed, failed, results)
        return False

    cursor = conn.cursor(as_dict=True)

    # 2. Server version
    try:
        cursor.execute("SELECT @@VERSION AS version")
        row = cursor.fetchone()
        version = row["version"].split("\n")[0].strip()
        print(f"✅ VERSION: {version}")
        results["version"] = version
        passed += 1
    except Exception as e:
        print(f"❌ VERSION: {e}")
        failed += 1

    # 3. Encryption status
    try:
        cursor.execute(
            """
            SELECT encrypt_option
            FROM sys.dm_exec_connections
            WHERE session_id = @@SPID
        """
        )
        row = cursor.fetchone()
        encrypted = row["encrypt_option"].upper() == "TRUE"
        results["encrypted"] = encrypted
        if encrypted:
            print(f"✅ ENCRYPTION: Active")
            passed += 1
        else:
            print(f"⚠️  ENCRYPTION: Not active")
            failed += 1
    except Exception as e:
        print(f"❌ ENCRYPTION CHECK: {e}")
        failed += 1

    # 4. Connection properties (auth scheme, transport)
    try:
        cursor.execute(
            """
            SELECT
                net_transport,
                protocol_type,
                auth_scheme,
                client_net_address
            FROM sys.dm_exec_connections
            WHERE session_id = @@SPID
        """
        )
        row = cursor.fetchone()
        results["transport"] = row["net_transport"]
        results["protocol"] = row["protocol_type"]
        results["auth_scheme"] = row["auth_scheme"]
        results["client_ip"] = row["client_net_address"]
        print(f"✅ AUTH SCHEME: {row['auth_scheme']}")
        print(f"   Transport: {row['net_transport']} | Protocol: {row['protocol_type']}")
        print(f"   Client IP: {row['client_net_address']}")
        passed += 1
    except Exception as e:
        print(f"❌ CONNECTION PROPERTIES: {e}")
        failed += 1

    # 5. Database accessibility
    try:
        cursor.execute("SELECT DB_NAME() AS current_db")
        row = cursor.fetchone()
        results["current_db"] = row["current_db"]
        if row["current_db"].lower() == database.lower():
            print(f"✅ DATABASE: {row['current_db']}")
            passed += 1
        else:
            print(f"⚠️  DATABASE: Connected to {row['current_db']}, expected {database}")
            failed += 1
    except Exception as e:
        print(f"❌ DATABASE CHECK: {e}")
        failed += 1

    # 6. RDS detection
    try:
        cursor.execute(
            """
            SELECT CASE
                WHEN @@VERSION LIKE '%Amazon%' THEN 'RDS'
                WHEN SERVERPROPERTY('EngineEdition') = 8 THEN 'RDS'
                ELSE 'Non-RDS'
            END AS environment
        """
        )
        row = cursor.fetchone()
        results["environment"] = row["environment"]
        print(f"✅ ENVIRONMENT: {row['environment']}")
        passed += 1
    except Exception as e:
        print(f"❌ ENVIRONMENT CHECK: {e}")
        failed += 1

    conn.close()
    print_summary(passed, failed, results)
    return failed == 0


def print_summary(passed, failed, results):
    total = passed + failed
    print(f"\n{'─'*60}")
    print(f"RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f" ({failed} failed)")
    else:
        print(" — all checks passed ✅")
    print(f"{'─'*60}")

    if results.get("encrypted") is False:
        print("\n⚠️  Connection is NOT encrypted. To fix:")
        print("   • Set encryption='require' in pymssql.connect()")
        print("   • Or set rds.force_ssl=1 in the RDS parameter group")


def main():
    parser = argparse.ArgumentParser(
        description="Test pymssql connection to RDS SQL Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--server", required=True, help="RDS endpoint or proxy endpoint")
    parser.add_argument("--port", default="1433", help="Port (default: 1433)")
    parser.add_argument("--user", help="Database username")
    parser.add_argument("--password", help="Database password")
    parser.add_argument("--database", default="master", help="Database name (default: master)")
    parser.add_argument(
        "--tds-version",
        default="7.3",
        choices=["7.3", "7.4"],
        help="TDS protocol version: 7.3 (SQL Server 2008–2019), 7.4 (2022+ only). Default: 7.3",
    )
    parser.add_argument(
        "--encryption",
        default="require",
        choices=["off", "request", "require"],
        help="Encryption mode (default: require)",
    )
    parser.add_argument(
        "--login-timeout", type=int, default=30, help="Login timeout seconds (default: 30)"
    )
    parser.add_argument(
        "--secret-id", help="AWS Secrets Manager secret ID (alternative to --user/--password)"
    )
    parser.add_argument(
        "--iam", action="store_true", help="Use IAM auth token (requires --user, uses boto3)"
    )
    parser.add_argument("--region", help="AWS region (for --secret-id or --iam)")
    parser.add_argument(
        "--network-only",
        action="store_true",
        help="Test network connectivity only (DNS, TCP, TLS) — no credentials needed",
    )

    args = parser.parse_args()

    # Network-only mode
    if args.network_only:
        success = test_network_only(args.server, args.port, timeout=args.login_timeout)
        sys.exit(0 if success else 1)

    server = args.server
    port = args.port
    user = args.user
    password = args.password
    database = args.database

    # Resolve credentials
    if args.secret_id:
        print(f"Fetching credentials from Secrets Manager: {args.secret_id}")
        creds = get_credentials_from_secret(args.secret_id, args.region)
        server = creds.get("server", server)
        port = creds.get("port", port)
        user = creds.get("user", user)
        password = creds.get("password")
        database = creds.get("database", database)
    elif args.iam:
        if not args.user:
            parser.error("--iam requires --user")
        print(f"Generating IAM auth token for {args.user}@{server}:{port}")
        # IAM auth tokens expire after 15 minutes — do not cache for long-running apps
        password = get_iam_token(server, int(port), args.user, args.region)
    elif not args.user or not args.password:
        parser.error("Provide --user and --password, or --secret-id, or --user and --iam")

    success = test_connection(
        server=server,
        port=port,
        user=user,
        password=password,
        database=database,
        tds_version=args.tds_version,
        encryption=args.encryption,
        login_timeout=args.login_timeout,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
