#!/usr/bin/env python3
"""
Find an existing SSM-managed EC2 instance in a VPC to use as a tunnel target.

This is the zero-cost path for local development: reuse an instance the
customer already has instead of creating a new jump host.

Dependencies:
    pip install boto3

Usage:
    python find_tunnel_host.py --vpc-id vpc-abc123
    python find_tunnel_host.py --vpc-id vpc-abc123 --region us-west-2
    python find_tunnel_host.py --vpc-id vpc-abc123 --profile my-profile
"""

from __future__ import annotations

import argparse
import os
import sys

try:
    import boto3
except ImportError:
    print(
        "Error: the 'boto3' package is required.\n"
        "Install it with:\n"
        "  pip install boto3"
    )
    sys.exit(2)


def find_tunnel_hosts(vpc_id: str, region: str, profile: str | None) -> list[dict]:
    session = boto3.Session(profile_name=profile, region_name=region)
    ec2 = session.client("ec2")
    ssm = session.client("ssm")

    print(f"Scanning VPC {vpc_id} in {region} for SSM-managed instances ...\n")

    paginator = ec2.get_paginator("describe_instances")
    pages = paginator.paginate(
        Filters=[
            {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )

    instances = []
    for page in pages:
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                name = ""
                for tag in inst.get("Tags", []):
                    if tag["Key"] == "Name":
                        name = tag["Value"]
                        break
                instances.append(
                    {
                        "instance_id": inst["InstanceId"],
                        "name": name,
                        "type": inst["InstanceType"],
                        "az": inst["Placement"]["AvailabilityZone"],
                        "private_ip": inst.get("PrivateIpAddress", ""),
                    }
                )

    if not instances:
        print("No running EC2 instances found in this VPC.\n")
        print("Options:")
        print("  1. Create a minimal jump host: t4g.nano (~$3/month)")
        print("     Launch one with: aws ec2 run-instances (attach the AmazonSSMManagedInstanceCore IAM policy), then run scripts/start_tunnel.py to connect")
        print("  2. Deploy your app to Lambda/ECS/EKS in the VPC (no tunnel needed)")
        return []

    ssm_managed = set()
    try:
        instance_ids = [inst["instance_id"] for inst in instances]
        ssm_paginator = ssm.get_paginator("describe_instance_information")
        for page in ssm_paginator.paginate(
            Filters=[{"Key": "InstanceIds", "Values": instance_ids}]
        ):
            for info in page["InstanceInformationList"]:
                ssm_managed.add(info["InstanceId"])
    except Exception as exc:
        error_code = ""
        if hasattr(exc, "response"):
            error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("AccessDeniedException", "AccessDenied", "UnauthorizedAccess"):
            print(f"ERROR: Access denied querying SSM. Ensure your IAM role/user has "
                  f"ssm:DescribeInstanceInformation permission.")
            print("Listing all instances -- SSM status unknown.\n")
        else:
            print(f"Warning: could not query SSM: {exc}")
            print("Listing all instances -- SSM status unknown.\n")

    results = []
    for inst in instances:
        inst["ssm"] = inst["instance_id"] in ssm_managed
        results.append(inst)

    results.sort(key=lambda x: (not x["ssm"], x["type"]))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find SSM-managed EC2 instances in a VPC for tunnel use.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--vpc-id", required=True, help="VPC ID to scan")
    _default_region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1"
    )
    parser.add_argument(
        "--region", default=_default_region, help=f"AWS region (default: {_default_region})"
    )
    parser.add_argument("--profile", default=None, help="AWS profile name")
    args = parser.parse_args()

    try:
        results = find_tunnel_hosts(args.vpc_id, args.region, args.profile)
    except Exception as e:
        error_code = ""
        if hasattr(e, "response"):
            error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("AccessDeniedException", "AccessDenied", "UnauthorizedAccess"):
            print(f"ERROR: Access denied. Ensure your IAM role/user has ec2:DescribeInstances "
                  f"and ssm:DescribeInstanceInformation permissions.")
        else:
            print(f"ERROR: {e}")
        sys.exit(1)

    if not results:
        sys.exit(1)

    ssm_ready = [r for r in results if r["ssm"]]
    not_ssm = [r for r in results if not r["ssm"]]

    if ssm_ready:
        print(f"Found {len(ssm_ready)} SSM-managed instance(s) (ready for tunnel, $0 extra cost):\n")
        print(f"  {'Instance ID':<22} {'Name':<25} {'Type':<14} {'AZ':<16} {'Private IP'}")
        print(f"  {'-'*22} {'-'*25} {'-'*14} {'-'*16} {'-'*15}")
        for r in ssm_ready:
            print(f"  {r['instance_id']:<22} {r['name']:<25} {r['type']:<14} {r['az']:<16} {r['private_ip']}")

        best = ssm_ready[0]
        print(f"\nRecommended: {best['instance_id']} ({best['name'] or best['type']})")
        print(f"\nNext step: start a tunnel with:")
        print(f"  python scripts/start_tunnel.py \\")
        print(f"    --instance-id {best['instance_id']} \\")
        print(f"    --cache-host <your-cache-endpoint> \\")
        print(f"    --region {args.region}")
        print(f"\n  For ElastiCache Serverless, you must also tunnel port 6380:")
        print(f"  python scripts/start_tunnel.py \\")
        print(f"    --instance-id {best['instance_id']} \\")
        print(f"    --cache-host <your-cache-endpoint> \\")
        print(f"    --cache-port 6380 \\")
        print(f"    --local-port 6380 \\")
        print(f"    --region {args.region}")
        print(f"\n  Note: ElastiCache Serverless requires TLS. When connecting through")
        print(f"  the tunnel, use --tls with --sni <your-cache-endpoint> to pass the")
        print(f"  the real cache hostname for reference.")
    else:
        print(f"Found {len(not_ssm)} instance(s) but none have SSM agent:\n")
        print(f"  {'Instance ID':<22} {'Name':<25} {'Type':<14}")
        print(f"  {'-'*22} {'-'*25} {'-'*14}")
        for r in not_ssm:
            print(f"  {r['instance_id']:<22} {r['name']:<25} {r['type']:<14}")
        print("\nOptions:")
        print("  1. Install SSM agent on one of these instances (free):")
        print("     Attach the AmazonSSMManagedInstanceCore IAM policy to the instance role")
        print("  2. Create a minimal jump host (~$3/month):")
        print("     Launch one with: aws ec2 run-instances (attach the AmazonSSMManagedInstanceCore IAM policy), then run scripts/start_tunnel.py to connect")

    if not_ssm and ssm_ready:
        print(f"\n({len(not_ssm)} additional instance(s) without SSM agent not shown)")


if __name__ == "__main__":
    main()
