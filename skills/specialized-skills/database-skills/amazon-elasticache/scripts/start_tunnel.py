#!/usr/bin/env python3
"""
Start an SSM port-forwarding tunnel to an ElastiCache endpoint.

Wraps the AWS SSM StartPortForwardingSessionToRemoteHost document into a
single command with pre-flight checks. Designed to be invoked by an AI agent
or a human developer, with clear error messages at every failure point.

Dependencies:
    pip install boto3

Prerequisites:
    - AWS CLI v2 installed
    - Session Manager plugin installed
      (https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
    - An SSM-managed EC2 instance in the same VPC as the cache
      (use find_tunnel_host.py to locate one)

Usage:
    python start_tunnel.py \\
        --instance-id i-0abc123def456 \\
        --cache-host my-cache.serverless.use1.cache.amazonaws.com

    python start_tunnel.py \\
        --instance-id i-0abc123def456 \\
        --cache-host my-cache.serverless.use1.cache.amazonaws.com \\
        --cache-port 6379 --local-port 6379 \\
        --region us-west-2 --profile my-profile
"""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import signal
import socket
import subprocess
import sys
import time

try:
    import boto3
except ImportError:
    print(
        "Error: the 'boto3' package is required.\n"
        "Install it with:\n"
        "  pip install boto3"
    )
    sys.exit(2)


def check_ssm_plugin() -> bool:
    """Verify the Session Manager plugin is installed."""
    return shutil.which("session-manager-plugin") is not None


def check_aws_cli() -> bool:
    """Verify the AWS CLI is installed."""
    return shutil.which("aws") is not None


def check_instance_ssm_status(instance_id: str, session: boto3.Session) -> bool:
    """Verify the target instance is online in SSM."""
    ssm = session.client("ssm")
    try:
        resp = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
        )
        instances = resp.get("InstanceInformationList", [])
        if not instances:
            return False
        return instances[0].get("PingStatus") == "Online"
    except Exception as exc:
        print(f"Warning: could not verify SSM status: {exc}")
        return False


def check_instance_running(instance_id: str, session: boto3.Session) -> bool:
    """Verify the target EC2 instance is in a running state."""
    ec2 = session.client("ec2")
    try:
        resp = ec2.describe_instance_status(
            InstanceIds=[instance_id], IncludeAllInstances=True
        )
        statuses = resp.get("InstanceStatuses", [])
        if not statuses:
            return False
        return statuses[0]["InstanceState"]["Name"] == "running"
    except Exception as exc:
        print(f"Warning: could not verify instance state: {exc}")
        return False


def validate_port(port: int, label: str = "port") -> None:
    """Validate that a port number is in the usable range (1-65535)."""
    if not isinstance(port, int) or port < 1 or port > 65535:
        print(f"  [FAIL] {label} must be between 1 and 65535 (got {port})")
        sys.exit(1)


def check_port_available(port: int) -> bool:
    """Check that nothing is already listening on the local port.

    Returns True if the port is free, False if something is already bound.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def wait_for_port(port: int, timeout: float = 10.0) -> bool:
    """Wait for the local port to become available (tunnel is up)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def start_tunnel(
    instance_id: str,
    cache_host: str,
    cache_port: int,
    local_port: int,
    region: str,
    profile: str | None,
) -> None:
    """Start SSM port forwarding and keep it running until interrupted."""

    session = boto3.Session(profile_name=profile, region_name=region)

    # --- Pre-flight checks ---
    print("Pre-flight checks:\n")

    # 1. Port validation
    validate_port(cache_port, "--cache-port")
    validate_port(local_port, "--local-port")
    print(f"  [OK]   Port numbers are valid (local={local_port}, remote={cache_port})")

    # 2. Local port not already in use
    if not check_port_available(local_port):
        print(f"  [FAIL] Local port {local_port} is already in use.")
        print(f"         Another process is listening on 127.0.0.1:{local_port}.")
        print(f"         Stop that process first, or use --local-port to pick a different port.")
        sys.exit(1)
    print(f"  [OK]   Local port {local_port} is available")

    # 3. AWS CLI
    if not check_aws_cli():
        print("  [FAIL] AWS CLI not found on PATH.")
        print("         Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html")
        sys.exit(1)
    print("  [OK]   AWS CLI found")

    # 4. SSM plugin
    if not check_ssm_plugin():
        print("  [FAIL] Session Manager plugin not found on PATH.")
        print("         Install: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html")
        sys.exit(1)
    print("  [OK]   Session Manager plugin found")

    # 5. Instance running
    if not check_instance_running(instance_id, session):
        print(f"  [FAIL] Instance {instance_id} is not in 'running' state.")
        print("         Start the instance or choose a different one (use find_tunnel_host.py).")
        sys.exit(1)
    print(f"  [OK]   Instance {instance_id} is running")

    # 6. SSM agent online
    if not check_instance_ssm_status(instance_id, session):
        print(f"  [WARN] Instance {instance_id} is not reporting to SSM as Online.")
        print("         The tunnel may fail. Ensure the instance has:")
        print("           - SSM agent installed and running")
        print("           - AmazonSSMManagedInstanceCore IAM policy attached")
        print("           - Network route to SSM endpoints (NAT gateway or VPC endpoint)")
        print("         Proceeding anyway ...\n")
    else:
        print(f"  [OK]   Instance {instance_id} SSM agent is online")

    print()

    # --- Build the SSM command ---
    parameters = json.dumps(
        {
            "host": [cache_host],
            "portNumber": [str(cache_port)],
            "localPortNumber": [str(local_port)],
        }
    )

    cmd = [
        "aws", "ssm", "start-session",
        "--target", instance_id,
        "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
        "--parameters", parameters,
        "--region", region,
    ]
    if profile:
        cmd.extend(["--profile", profile])

    print(f"Starting tunnel: 127.0.0.1:{local_port} -> {cache_host}:{cache_port}")
    print(f"  via SSM instance: {instance_id}")
    print(f"  region: {region}")
    print()
    print("Tunnel command:")
    print(f"  {' '.join(cmd)}")
    print()

    # --- Launch the tunnel ---
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Give the tunnel a moment to start, then check if the port is up
        time.sleep(2)

        if proc.poll() is not None:
            # Process already exited -- something went wrong
            output = proc.stdout.read() if proc.stdout else ""
            print(f"Tunnel process exited immediately (code {proc.returncode}):\n")
            print(output)
            sys.exit(1)

        if wait_for_port(local_port, timeout=15.0):
            print(f"Tunnel is UP. Local port 127.0.0.1:{local_port} is accepting connections.\n")
            is_serverless = ".serverless." in cache_host
            if is_serverless:
                print("Note: ElastiCache Serverless requires TLS. Your client must connect")
                print(f"  with TLS enabled and SNI set to {cache_host}")
                print(f"  (the tunnel forwards raw TCP; TLS negotiation happens end-to-end).\n")
            print("Test with:")
            print(f"  python scripts/test_connection.py 127.0.0.1 --port {local_port} \\")
            print(f"    --tunnel-mode --server-name {cache_host} \\")
            print(f"    --username <user> --password <password>")
            print()
            print("Press Ctrl+C to stop the tunnel.")
        else:
            print(f"Warning: local port {local_port} not yet responding after 15s.")
            print("The tunnel may still be starting. Check the output below.\n")

        # Stream SSM output with periodic health checks.
        # Uses select() to avoid blocking forever if the session stalls.
        health_check_interval = 30  # seconds between port probes

        assert proc.stdout is not None
        while proc.poll() is None:
            ready, _, _ = select.select([proc.stdout], [], [], health_check_interval)
            if ready:
                line = proc.stdout.readline()
                if line:
                    print(f"  [SSM] {line}", end="")
                else:
                    break  # EOF -- process closed stdout
            else:
                # No output for health_check_interval seconds, check tunnel
                if not wait_for_port(local_port, timeout=3.0):
                    print(f"\n  [WARN] Tunnel port {local_port} is no longer responding.")
                    print("         The SSM session may have stalled. Press Ctrl+C to stop.")

        proc.wait()
        if proc.returncode != 0:
            print(f"\nTunnel exited with code {proc.returncode}")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\nShutting down tunnel ...")
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("Tunnel closed.")
    except Exception as exc:
        print(f"\nError: {exc}")
        if proc and proc.poll() is None:
            proc.kill()
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start an SSM port-forwarding tunnel to an ElastiCache endpoint.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--instance-id", required=True,
        help="SSM-managed EC2 instance ID (use find_tunnel_host.py to discover)",
    )
    parser.add_argument(
        "--cache-host", required=True,
        help="ElastiCache endpoint hostname (e.g. my-cache.serverless.use1.cache.amazonaws.com)",
    )
    parser.add_argument(
        "--cache-port", type=int, default=6379,
        help="ElastiCache port (default: 6379; serverless reader endpoint uses 6380)",
    )
    parser.add_argument(
        "--local-port", type=int, default=6379,
        help="Local port to forward to (default: 6379)",
    )
    _default_region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1"
    )
    parser.add_argument(
        "--region", default=_default_region,
        help=f"AWS region (default: {_default_region})",
    )
    parser.add_argument(
        "--profile", default=None,
        help="AWS profile name",
    )

    args = parser.parse_args()

    start_tunnel(
        instance_id=args.instance_id,
        cache_host=args.cache_host,
        cache_port=args.cache_port,
        local_port=args.local_port,
        region=args.region,
        profile=args.profile,
    )


if __name__ == "__main__":
    main()
