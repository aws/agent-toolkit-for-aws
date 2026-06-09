#!/usr/bin/env python3
"""
ElastiCache connection validator.

Uses the valkey-py client library to perform a proper TLS-enabled
PING against an ElastiCache endpoint. Supports RBAC (username + password),
IAM auth, and legacy AUTH tokens (node-based only).

Serverless caches REQUIRE TLS -- this script defaults to TLS-on.

Dependencies:
    pip install valkey
    pip install boto3   # only needed for --iam-auth (includes botocore)

Usage examples:
    # Serverless with RBAC (TLS is default)
    python test_connection.py your-endpoint.serverless.use1.cache.amazonaws.com \\
        --username my-user --password my-password

    # Node-based with TLS and RBAC
    python test_connection.py your-endpoint.cache.amazonaws.com \\
        --username my-user --password my-password

    # Node-based with legacy AUTH token
    python test_connection.py your-endpoint.cache.amazonaws.com \\
        --password my-auth-token

    # Node-based WITHOUT TLS (not recommended)
    python test_connection.py your-endpoint.cache.amazonaws.com \\
        --no-tls --password my-auth-token

    # Serverless with IAM auth
    python test_connection.py your-endpoint.serverless.use1.cache.amazonaws.com \\
        --iam-auth --iam-user my-iam-user --region us-east-1 \\
        --cache-name my-cache

    # Through an SSM tunnel (see start_tunnel.py)
    python test_connection.py 127.0.0.1 --port 6379 \\
        --tunnel-mode --server-name my-cache.serverless.use1.cache.amazonaws.com \\
        --username my-user --password my-password
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
import time

# ---------------------------------------------------------------------------
# Dependency check -- fail early with an actionable message instead of a
# raw ImportError traceback.
#
# Required: valkey
# Optional: boto3 -- only needed when using --iam-auth.
# ---------------------------------------------------------------------------
try:
    import valkey as client_lib

    client_name = "valkey-py"
except ImportError:
    print(
        "Error: the 'valkey' package is required for this script.\n"
        "Install it with:\n"
        "  pip install valkey\n"
        "\n"
        "If using IAM authentication, you also need:\n"
        "  pip install boto3",
        file=sys.stderr,
    )
    sys.exit(2)


def get_iam_auth_token(
    cache_name: str, iam_user: str, region: str, is_serverless: bool = False
) -> str:
    """Generate a short-lived IAM auth token for ElastiCache."""
    cache_name = cache_name.lower()
    try:
        import botocore.session
        from botocore.signers import RequestSigner
        from botocore.model import ServiceId
    except ImportError:
        print(
            "Error: the 'botocore' package is required for IAM authentication.\n"
            "Install it with:\n"
            "  pip install botocore\n"
            "\n"
            "You also need AWS credentials configured (via environment\n"
            "variables, ~/.aws/credentials, or an IAM role).",
            file=sys.stderr,
        )
        sys.exit(2)

    session = botocore.session.get_session()
    signer = RequestSigner(
        ServiceId("elasticache"),
        region,
        "elasticache",
        "v4",
        session.get_credentials(),
        session.get_component("event_emitter"),
    )
    url = signer.generate_presigned_url(
        {
            "method": "GET",
            "url": f"http://{cache_name}/?Action=connect&User={iam_user}&ResourceType=ServerlessCache" if is_serverless else f"http://{cache_name}/?Action=connect&User={iam_user}",
            "body": {},
            "headers": {},
            "context": {},
        },
        operation_name="connect",
        expires_in=900,
        region_name=region,
    )
    token = url[len("http://"):] if url.startswith("http://") else url
    return token


def _check_dns(host: str) -> None:
    """Warn if the host resolves to a private IP and is not localhost."""
    import ipaddress
    import socket

    if host in ("127.0.0.1", "localhost", "::1"):
        return
    try:
        addr = socket.gethostbyname(host)
        ip = ipaddress.ip_address(addr)
        if ip.is_private:
            print(f"  WARNING: {host} resolves to private IP {addr}.", file=sys.stderr)
            print(f"  If you are not in the VPC, this connection will time out.", file=sys.stderr)
            print(f"  Use --tunnel-mode with scripts/start_tunnel.py for local development.\n", file=sys.stderr)
    except socket.gaierror:
        print(f"  WARNING: DNS lookup failed for {host}. The endpoint may be wrong,", file=sys.stderr)
        print(f"  or you may not have DNS access to the VPC.\n", file=sys.stderr)


def test_connection(
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    use_tls: bool,
    timeout: float,
    tunnel_mode: bool = False,
    server_name: str | None = None,
    is_serverless: bool = False,
) -> bool:
    """Connect to ElastiCache and run PING using the client library."""
    _check_dns(host)
    tls_label = "TLS" if use_tls else "plaintext"
    if tunnel_mode:
        tls_label += " tunnel-mode"
    auth_label = (
        f"user={username}"
        if username
        else ("password-auth" if password else "no-auth")
    )
    print(f"Connecting to {host}:{port} ({tls_label}, {auth_label}) via {client_name} ...")

    kwargs = {
        "host": host,
        "port": port,
        "socket_timeout": timeout,
        "socket_connect_timeout": timeout,
        "decode_responses": True,
    }

    if use_tls:
        kwargs["ssl"] = True
        if tunnel_mode:
            # Through an SSM tunnel the TLS cert is issued for the real cache
            # hostname (*.cache.amazonaws.com), not 127.0.0.1. Disable hostname
            # checking but keep certificate verification against the CA bundle.
            # Set SNI to the real cache hostname (--server-name) so that
            # serverless endpoints can route the TLS handshake correctly.
            kwargs["ssl_cert_reqs"] = "required"
            kwargs["ssl_ca_certs"] = ssl.get_default_verify_paths().cafile
            kwargs["ssl_check_hostname"] = False
            if server_name:
                kwargs["ssl_server_hostname"] = server_name
            print(f"  Tunnel mode: hostname verification disabled, target={host}:{port}")
            print(f"  WARNING: tunnel mode is for LOCAL DEVELOPMENT ONLY", file=sys.stderr)
        else:
            kwargs["ssl_cert_reqs"] = "required"
            kwargs["ssl_ca_certs"] = ssl.get_default_verify_paths().cafile

    if username:
        kwargs["username"] = username
    if password:
        kwargs["password"] = password

    # Detect serverless from hostname pattern OR the --serverless flag.
    # The flag is needed when connecting through a tunnel (e.g., 127.0.0.1)
    # where the hostname pattern is not present.
    is_serverless = is_serverless or ".serverless." in host

    # In tunnel mode, always use a non-cluster client. Cluster clients run
    # CLUSTER SLOTS/NODES discovery and try to connect directly to each node
    # using private VPC IPs, which are unreachable through the tunnel. A
    # standalone client connects only to the tunneled endpoint, which is
    # sufficient for a connectivity test (PING + INFO).
    use_cluster_client = is_serverless and not tunnel_mode

    try:
        if use_cluster_client:
            if client_name == "valkey-py":
                conn = client_lib.ValkeyCluster(**kwargs)
            else:
                conn = client_lib.RedisCluster(**kwargs)
        elif client_name == "valkey-py":
            conn = client_lib.Valkey(**kwargs)
        else:
            conn = client_lib.Redis(**kwargs)

        if is_serverless and tunnel_mode:
            print("  Note: using standalone client through tunnel (cluster discovery")
            print("  would return unreachable VPC IPs). PING validates connectivity.")
    except Exception as exc:
        print(f"  Client init FAILED: {exc}", file=sys.stderr)
        return False

    # Step 1: PING
    start = time.monotonic()
    try:
        result = conn.ping()
        elapsed_ms = (time.monotonic() - start) * 1000
        print(f"  PING: OK ({elapsed_ms:.1f} ms)")
    except client_lib.exceptions.AuthenticationError as exc:
        print(f"  PING FAILED: Authentication error -- {exc}", file=sys.stderr)
        print("  Hint: Check username/password or ensure the RBAC user exists and is active.", file=sys.stderr)
        return False
    except client_lib.exceptions.ConnectionError as exc:
        msg = str(exc)
        print(f"  PING FAILED: Connection error -- {exc}", file=sys.stderr)
        if "SSL" in msg or "tls" in msg.lower():
            if use_tls:
                print("  Hint: TLS handshake failed. Verify the endpoint supports in-transit encryption.", file=sys.stderr)
            else:
                print("  Hint: This endpoint may require TLS. Retry without --no-tls (TLS is default).", file=sys.stderr)
        else:
            print("  Hint: Check security group rules, VPC placement, and whether you need a tunnel or jump host.", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"  PING FAILED: {exc}", file=sys.stderr)
        return False

    # Step 2: INFO SERVER (lightweight metadata check)
    try:
        info = conn.info("server")
        engine = info.get("redis_version", info.get("valkey_version", "unknown"))
        mode = info.get("redis_mode", "unknown")
        print(f"  Server: engine version {engine}, mode={mode}")
    except Exception:
        # INFO may be blocked by ACL; that is fine
        print("  Server info: not available (ACL may restrict INFO command)", file=sys.stderr)

    # Step 3: Verify TLS status
    if use_tls:
        print("  TLS: enabled (in-transit encryption active)")
    else:
        print("  TLS: disabled -- consider enabling in-transit encryption for production use", file=sys.stderr)

    try:
        conn.close()
    except Exception:
        pass

    print("  Result: CONNECTION SUCCESSFUL")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate connectivity to an ElastiCache endpoint (serverless or node-based).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("host", help="ElastiCache endpoint hostname")
    parser.add_argument("--port", type=int, default=6379, help="Port (default: 6379; serverless reader endpoint uses 6380)")
    parser.add_argument("--timeout", type=float, default=5.0, help="Connection timeout in seconds (default: 5)")

    # TLS (default on)
    parser.add_argument(
        "--no-tls",
        action="store_true",
        default=False,
        help="Disable TLS (not recommended; serverless caches REQUIRE TLS)",
    )

    # Tunnel mode
    tunnel_group = parser.add_argument_group("tunnel mode (for SSM port-forwarded connections)")
    tunnel_group.add_argument(
        "--tunnel-mode",
        action="store_true",
        default=False,
        help="Enable tunnel mode: disables TLS hostname verification (dev only)",
    )
    tunnel_group.add_argument(
        "--server-name",
        help="Real cache hostname for TLS SNI (required for serverless endpoints in tunnel mode)",
    )

    # Auth
    auth_group = parser.add_argument_group("authentication")
    auth_group.add_argument("--username", help="RBAC username")
    auth_group.add_argument("--password", help="RBAC password or legacy AUTH token (node-based only)")
    auth_group.add_argument(
        "--iam-auth",
        action="store_true",
        default=False,
        help="Use IAM authentication (Valkey 7.2+ / Redis OSS 7.0+). Requires boto3.",
    )
    auth_group.add_argument("--iam-user", help="IAM-enabled ElastiCache user ID (required with --iam-auth)")
    auth_group.add_argument("--cache-name", help="Cache or replication group name (required with --iam-auth)")
    auth_group.add_argument(
        "--serverless",
        action="store_true",
        default=False,
        help="Target is a serverless cache (adds ResourceType=ServerlessCache to IAM token)",
    )
    _default_region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    auth_group.add_argument("--region", default=_default_region, help=f"AWS region (default: {_default_region})")

    args = parser.parse_args()

    use_tls = not args.no_tls
    password = args.password
    username = args.username

    # Tunnel mode validation
    if args.tunnel_mode and args.no_tls:
        parser.error("--tunnel-mode requires TLS (cannot combine with --no-tls)")

    # IAM auth flow
    if args.iam_auth:
        if not args.iam_user or not args.cache_name:
            parser.error("--iam-auth requires --iam-user and --cache-name")
        print(f"Generating IAM auth token for user={args.iam_user}, cache={args.cache_name} ...")
        password = get_iam_auth_token(args.cache_name, args.iam_user, args.region, is_serverless=args.serverless)
        username = args.iam_user
        print("  IAM token generated (valid for 15 minutes)")

    success = test_connection(
        host=args.host,
        port=args.port,
        username=username,
        password=password,
        use_tls=use_tls,
        timeout=args.timeout,
        tunnel_mode=args.tunnel_mode,
        server_name=args.server_name,
        is_serverless=args.serverless,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
