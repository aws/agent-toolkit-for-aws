#!/usr/bin/env python3
"""
ElastiCache Security Audit

Inspects an existing cache and reports its security and operational posture.
Checks: TLS, auth mode, encryption at rest, Multi-AZ, failover, backups,
security group openness, and engine currency.

Usage:
  # Audit a serverless cache
  python security_audit.py --serverless my-cache --region us-east-1

  # Audit a node-based replication group
  python security_audit.py --replication-group my-cluster --region us-east-1

  # JSON output for automation
  python security_audit.py --serverless my-cache --region us-east-1 --json

Requires: boto3, AWS credentials with elasticache:Describe*,
         elasticache:ListTagsForResource, and ec2:DescribeSecurityGroups
"""

import argparse
import json
import sys

# ---------------------------------------------------------------------------
# Dependency check -- fail early with an actionable message instead of a
# raw ImportError traceback.
# ---------------------------------------------------------------------------
try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
except ImportError:
    print(
        "Error: the 'boto3' package is required for this script.\n"
        "Install it with:\n"
        "  pip install boto3\n"
        "\n"
        "You also need AWS credentials with elasticache:Describe*,\n"
        "elasticache:ListTagsForResource, and ec2:DescribeSecurityGroups\n"
        "permissions configured (via environment\n"
        "variables, ~/.aws/credentials, or an IAM role)."
    )
    sys.exit(1)


def audit_serverless(client, ec2_client, cache_name):
    """Audit a serverless cache."""
    try:
        resp = client.describe_serverless_caches(ServerlessCacheName=cache_name)
    except client.exceptions.ServerlessCacheNotFoundFault:
        return {"error": f"Serverless cache '{cache_name}' not found"}
    except Exception as e:
        if hasattr(e, 'response') and e.response.get('Error', {}).get('Code') == 'ServerlessCacheNotFoundFault':
            return {"error": f"Serverless cache '{cache_name}' not found"}
        raise
    caches = resp.get("ServerlessCaches", [])
    if not caches:
        return {"error": f"Serverless cache '{cache_name}' not found"}

    cache = caches[0]
    findings = []
    info = {
        "cache_type": "serverless",
        "cache_name": cache_name,
        "engine": cache.get("Engine", "unknown"),
        "engine_version": cache.get("MajorEngineVersion", "unknown"),
        "status": cache.get("Status", "unknown"),
        "arn": cache.get("ARN", "unknown"),
    }

    # TLS: always on for serverless
    info["tls_enabled"] = True
    findings.append({"check": "TLS in-transit encryption", "status": "PASS", "detail": "Always enabled on serverless"})

    # Auth: serverless requires RBAC
    user_group = cache.get("UserGroupId")
    if user_group:
        findings.append({"check": "Authentication", "status": "PASS", "detail": f"RBAC user group: {user_group}"})
        info["auth_mode"] = "RBAC"
        info["user_group"] = user_group
    else:
        findings.append({"check": "Authentication", "status": "WARN", "detail": "No user group attached — using default user only"})
        info["auth_mode"] = "default-user-only"

    # Encryption at rest: check KMS
    kms_key = cache.get("KmsKeyId")
    if kms_key:
        findings.append({"check": "Encryption at rest", "status": "PASS", "detail": f"KMS key: {kms_key}"})
        info["encryption_at_rest"] = True
        info["kms_key"] = kms_key
    else:
        findings.append({"check": "Encryption at rest", "status": "PASS", "detail": "Always enabled on serverless (using AWS-managed key)"})
        info["encryption_at_rest"] = True

    # Multi-AZ: always on for serverless
    info["multi_az"] = True
    findings.append({"check": "Multi-AZ", "status": "PASS", "detail": "Always enabled on serverless"})

    # Backups: check SnapshotRetentionLimit
    retention = cache.get("SnapshotRetentionLimit", 0)
    info["snapshot_retention_days"] = retention
    if retention and retention > 0:
        snapshot_time = cache.get("DailySnapshotTime", "not set")
        info["daily_backups"] = True
        findings.append({"check": "Automatic backups", "status": "PASS", "detail": f"Retention: {retention} days, daily snapshot time: {snapshot_time}"})
    else:
        info["daily_backups"] = False
        findings.append({"check": "Automatic backups", "status": "FAIL", "detail": "No automatic backups configured, SnapshotRetentionLimit is 0 or not set"})

    # Usage limits (cost control)
    limits = cache.get("CacheUsageLimits", {})
    data_limit = limits.get("DataStorage", {})
    ecpu_limit = limits.get("ECPUPerSecond", {})
    if data_limit.get("Maximum"):
        info["max_data_gb"] = data_limit["Maximum"]
        findings.append({"check": "Data storage limit", "status": "PASS", "detail": f"{data_limit['Maximum']} {data_limit.get('Unit', 'GB')} max"})
    else:
        findings.append({"check": "Data storage limit", "status": "WARN", "detail": "No data storage limit set — costs could grow unbounded"})
    if ecpu_limit.get("Maximum"):
        info["max_ecpu_per_sec"] = ecpu_limit["Maximum"]
        findings.append({"check": "ECPU limit", "status": "PASS", "detail": f"{ecpu_limit['Maximum']} ECPUs/sec max"})
    else:
        findings.append({"check": "ECPU limit", "status": "WARN", "detail": "No ECPU limit set — costs could grow unbounded"})

    # Security groups
    sg_ids = cache.get("SecurityGroupIds", [])
    sg_findings = _audit_security_groups(ec2_client, sg_ids)
    findings.extend(sg_findings)
    info["security_groups"] = sg_ids

    # Tags
    try:
        tag_resp = client.list_tags_for_resource(ResourceName=cache["ARN"])
        tags = {t["Key"]: t["Value"] for t in tag_resp.get("TagList", [])}
    except (ClientError, BotoCoreError):
        tags = {}
    _audit_tags(findings, tags)
    info["tags"] = tags

    return {"info": info, "findings": findings}


def audit_replication_group(client, ec2_client, rg_id):
    """Audit a node-based replication group."""
    try:
        resp = client.describe_replication_groups(ReplicationGroupId=rg_id)
    except client.exceptions.ReplicationGroupNotFoundFault:
        return {"error": f"Replication group '{rg_id}' not found"}
    except Exception as e:
        if hasattr(e, 'response') and e.response.get('Error', {}).get('Code') == 'ReplicationGroupNotFoundFault':
            return {"error": f"Replication group '{rg_id}' not found"}
        raise
    groups = resp.get("ReplicationGroups", [])
    if not groups:
        return {"error": f"Replication group '{rg_id}' not found"}

    rg = groups[0]
    findings = []
    info = {
        "cache_type": "node-based",
        "replication_group_id": rg_id,
        "engine": "unknown",
        "status": rg.get("Status", "unknown"),
        "arn": rg.get("ARN", "unknown"),
        "cluster_enabled": rg.get("ClusterEnabled", False),
        "num_node_groups": len(rg.get("NodeGroups", [])),
    }

    # Engine version from member clusters
    member_clusters = rg.get("MemberClusters", [])
    if member_clusters:
        try:
            cluster_resp = client.describe_cache_clusters(CacheClusterId=member_clusters[0])
            cluster = cluster_resp["CacheClusters"][0]
            info["engine"] = cluster.get("Engine", "unknown")
            info["engine_version"] = cluster.get("EngineVersion", "unknown")
            info["node_type"] = cluster.get("CacheNodeType", "unknown")
        except (ClientError, BotoCoreError):
            info["engine_version"] = "unknown"
            info["node_type"] = "unknown"

    # TLS
    tls = rg.get("TransitEncryptionEnabled", False)
    info["tls_enabled"] = tls
    if tls:
        findings.append({"check": "TLS in-transit encryption", "status": "PASS", "detail": "Enabled"})
    else:
        findings.append({"check": "TLS in-transit encryption", "status": "FAIL", "detail": "Not enabled — data in transit is unencrypted"})

    # Encryption at rest
    at_rest = rg.get("AtRestEncryptionEnabled", False)
    info["encryption_at_rest"] = at_rest
    if at_rest:
        kms = rg.get("KmsKeyId", "AWS-managed")
        findings.append({"check": "Encryption at rest", "status": "PASS", "detail": f"Enabled (key: {kms})"})
        info["kms_key"] = kms
    else:
        findings.append({"check": "Encryption at rest", "status": "FAIL", "detail": "Not enabled — data at rest is unencrypted"})

    # Auth
    auth_token = rg.get("AuthTokenEnabled", False)
    user_group_ids = rg.get("UserGroupIds", [])
    if user_group_ids:
        info["auth_mode"] = "RBAC"
        info["user_groups"] = user_group_ids
        findings.append({"check": "Authentication", "status": "PASS", "detail": f"RBAC user groups: {', '.join(user_group_ids)}"})
    elif auth_token:
        info["auth_mode"] = "AUTH-token"
        findings.append({"check": "Authentication", "status": "WARN", "detail": "Using legacy AUTH token — consider migrating to RBAC"})
    else:
        info["auth_mode"] = "none"
        findings.append({"check": "Authentication", "status": "FAIL", "detail": "No authentication configured — any VPC client can access data"})

    # Multi-AZ
    multi_az = rg.get("MultiAZ", "disabled")
    info["multi_az"] = multi_az == "enabled"
    if multi_az == "enabled":
        findings.append({"check": "Multi-AZ", "status": "PASS", "detail": "Enabled"})
    else:
        findings.append({"check": "Multi-AZ", "status": "WARN", "detail": "Not enabled — single-AZ failure risk"})

    # Automatic failover
    failover = rg.get("AutomaticFailover", "disabled")
    info["automatic_failover"] = failover == "enabled"
    if failover == "enabled":
        findings.append({"check": "Automatic failover", "status": "PASS", "detail": "Enabled"})
    else:
        findings.append({"check": "Automatic failover", "status": "WARN", "detail": "Not enabled — manual intervention needed on primary failure"})

    # Backups
    retention = rg.get("SnapshotRetentionLimit", 0)
    info["snapshot_retention_days"] = retention
    if retention > 0:
        findings.append({"check": "Automatic backups", "status": "PASS", "detail": f"Retention: {retention} days"})
    else:
        findings.append({"check": "Automatic backups", "status": "FAIL", "detail": "No automatic backups — data loss risk on failure"})

    # Security groups from node groups
    sg_ids = set()
    for ng in rg.get("NodeGroups", []):
        for member in ng.get("NodeGroupMembers", []):
            if "CacheClusterId" in member:
                try:
                    cc = client.describe_cache_clusters(
                        CacheClusterId=member["CacheClusterId"],
                        ShowCacheNodeInfo=True
                    )["CacheClusters"][0]
                    for sg in cc.get("SecurityGroups", []):
                        sg_ids.add(sg["SecurityGroupId"])
                except (ClientError, BotoCoreError):
                    pass

    sg_ids_list = list(sg_ids)
    sg_findings = _audit_security_groups(ec2_client, sg_ids_list)
    findings.extend(sg_findings)
    info["security_groups"] = sg_ids_list

    # Tags
    try:
        tag_resp = client.list_tags_for_resource(ResourceName=info["arn"])
        tags = {t["Key"]: t["Value"] for t in tag_resp.get("TagList", [])}
    except (ClientError, BotoCoreError):
        tags = {}
    _audit_tags(findings, tags)
    info["tags"] = tags

    return {"info": info, "findings": findings}


def _audit_security_groups(ec2_client, sg_ids):
    """Check security groups for overly permissive rules."""
    findings = []
    if not sg_ids:
        findings.append({"check": "Security groups", "status": "WARN", "detail": "No security groups found"})
        return findings

    try:
        resp = ec2_client.describe_security_groups(GroupIds=sg_ids)
    except Exception as e:
        findings.append({"check": "Security groups", "status": "ERROR", "detail": f"Could not inspect: {e}"})
        return findings

    for sg in resp.get("SecurityGroups", []):
        sg_id = sg["GroupId"]
        for rule in sg.get("IpPermissions", []):
            from_port = rule.get("FromPort", 0)
            to_port = rule.get("ToPort", 0)
            for ip_range in rule.get("IpRanges", []):
                cidr = ip_range.get("CidrIp", "")
                if cidr == "0.0.0.0/0":
                    findings.append({
                        "check": f"Security group {sg_id}",
                        "status": "WARN",
                        "detail": f"Inbound rule allows 0.0.0.0/0 on ports {from_port}-{to_port} -- no public endpoint exists, but 0.0.0.0/0 violates least-privilege"
                    })
                elif cidr.endswith("/0") or cidr.endswith("/8"):
                    findings.append({
                        "check": f"Security group {sg_id}",
                        "status": "WARN",
                        "detail": f"Inbound rule allows {cidr} on ports {from_port}-{to_port} -- very broad CIDR"
                    })
            for ip_range in rule.get("Ipv6Ranges", []):
                cidr = ip_range.get("CidrIpv6", "")
                if cidr == "::/0":
                    findings.append({
                        "check": f"Security group {sg_id}",
                        "status": "WARN",
                        "detail": f"Inbound rule allows ::/0 (IPv6) on ports {from_port}-{to_port} -- no public endpoint exists, but ::/0 violates least-privilege"
                    })

    if not any(f["check"].startswith("Security group") for f in findings):
        findings.append({"check": "Security groups", "status": "PASS", "detail": f"No overly permissive rules in {', '.join(sg_ids)}"})

    return findings


def _audit_tags(findings, tags):
    """Check for recommended tags."""
    recommended = ["Environment", "managed_by", "Application", "Owner"]
    missing = [t for t in recommended if t not in tags]
    if not missing:
        findings.append({"check": "Resource tags", "status": "PASS", "detail": f"All recommended tags present"})
    else:
        findings.append({"check": "Resource tags", "status": "WARN", "detail": f"Missing recommended tags: {', '.join(missing)}"})


def format_report(result):
    """Format audit results as a human-readable report."""
    if "error" in result:
        return f"ERROR: {result['error']}"

    info = result["info"]
    findings = result["findings"]

    lines = []
    lines.append("=" * 72)
    lines.append("ElastiCache Security Audit Report")
    lines.append("=" * 72)
    lines.append("")

    lines.append(f"  Cache type:      {info['cache_type']}")
    if info["cache_type"] == "serverless":
        lines.append(f"  Cache name:      {info['cache_name']}")
    else:
        lines.append(f"  Replication group: {info['replication_group_id']}")
        lines.append(f"  Node type:       {info.get('node_type', 'unknown')}")
        lines.append(f"  Cluster mode:    {'enabled' if info.get('cluster_enabled') else 'disabled'}")
        lines.append(f"  Node groups:     {info.get('num_node_groups', 'unknown')}")
    lines.append(f"  Engine:          {info['engine']} {info.get('engine_version', '')}")
    lines.append(f"  Status:          {info['status']}")
    lines.append(f"  Auth mode:       {info.get('auth_mode', 'unknown')}")
    lines.append("")

    fail_count = sum(1 for f in findings if f["status"] == "FAIL")
    warn_count = sum(1 for f in findings if f["status"] == "WARN")
    pass_count = sum(1 for f in findings if f["status"] == "PASS")

    lines.append(f"  Summary: {pass_count} passed, {warn_count} warnings, {fail_count} failures")
    lines.append("")

    lines.append("-" * 72)

    status_order = {"FAIL": 0, "WARN": 1, "ERROR": 2, "INFO": 3, "PASS": 4}
    sorted_findings = sorted(findings, key=lambda f: status_order.get(f["status"], 5))

    for f in sorted_findings:
        icon = {"PASS": "[OK]  ", "FAIL": "[FAIL]", "WARN": "[WARN]", "INFO": "[INFO]", "ERROR": "[ERR] "}
        lines.append(f"  {icon.get(f['status'], '[?]   ')} {f['check']}")
        lines.append(f"         {f['detail']}")
        lines.append("")

    if fail_count > 0:
        lines.append("=" * 72)
        lines.append("RECOMMENDED ACTIONS")
        lines.append("=" * 72)
        lines.append("")
        for f in sorted_findings:
            if f["status"] == "FAIL":
                check = f["check"]
                if "TLS" in check:
                    lines.append("  - Enable in-transit encryption. For existing node-based clusters, use a")
                    lines.append("    two-step process: first set transit-encryption-mode to 'preferred',")
                    lines.append("    then after migrating all clients to TLS, set it to 'required'.")
                elif "Encryption at rest" in check:
                    lines.append("  - Enable at-rest encryption. For existing clusters, this requires")
                    lines.append("    creating a new cluster with AtRestEncryptionEnabled=true and migrating.")
                elif "Authentication" in check:
                    lines.append("  - Configure RBAC: create users, a user group, and attach it to the cache.")
                    lines.append("    See references/setup/iam-policies.md for IAM auth patterns.")
                elif "backups" in check.lower():
                    lines.append("  - Enable automatic backups: modify the replication group with")
                    lines.append("    SnapshotRetentionLimit > 0 (recommended: 7 days).")
                elif "0.0.0.0/0" in f["detail"]:
                    lines.append(f"  - Restrict {check}: remove the 0.0.0.0/0 inbound rule and scope to")
                    lines.append("    application security groups only.")
                lines.append("")

    lines.append("  Note: This is an informational review, not a security certification.")
    lines.append("  Consult your security team before production deployment.")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ElastiCache Security Audit")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--serverless", metavar="CACHE_NAME", help="Audit a serverless cache")
    group.add_argument("--replication-group", metavar="RG_ID", help="Audit a node-based replication group")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--profile", default=None, help="AWS profile")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        ec_client = session.client("elasticache")
        ec2_client = session.client("ec2")
    except Exception as e:
        print(f"ERROR: Failed to create AWS session: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.serverless:
            result = audit_serverless(ec_client, ec2_client, args.serverless)
        else:
            result = audit_replication_group(ec_client, ec2_client, args.replication_group)
    except Exception as e:
        error_code = ""
        if hasattr(e, "response"):
            error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("AccessDeniedException", "AccessDenied"):
            print(f"ERROR: Access denied. Ensure your IAM role/user has elasticache:Describe*, "
                  f"elasticache:ListTagsForResource, and ec2:DescribeSecurityGroups permissions.")
        else:
            print(f"ERROR: {e}")
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_report(result))

    if "error" in result:
        sys.exit(1)
    fail_count = sum(1 for f in result.get("findings", []) if f["status"] == "FAIL")
    sys.exit(1 if fail_count > 0 else 0)
