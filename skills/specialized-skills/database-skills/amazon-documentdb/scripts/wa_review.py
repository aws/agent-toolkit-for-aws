#!/usr/bin/env python3
"""DocumentDB Well-Architected Review — standalone CLI.

Runs 41 automated checks across 6 pillars against a DocumentDB cluster.
Infrastructure checks use boto3 (AWS APIs). Database-level checks use
a pre-collected analysis JSON file (from pymongo collStats/indexStats).

Usage:
    python3 wa_review.py --cluster-id <id> --region <region> [--analysis-data <path>]

Output:
    wa_review_results.json  — structured check results
    wa_review_report.md     — human-readable summary

Requires: boto3, AWS credentials with docdb/cloudwatch/ec2/secretsmanager read access.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import boto3
except ImportError:
    print("ERROR: boto3 required. Install with: pip install boto3")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONN_LIMITS = {
    "db.t3.medium": 1000,
    "db.t4g.medium": 1000,
    "db.r5.large": 3400,
    "db.r6g.large": 3400,
    "db.r6gd.large": 3400,
    "db.r8g.large": 3400,
    "db.r5.xlarge": 7000,
    "db.r6g.xlarge": 7000,
    "db.r6gd.xlarge": 7000,
    "db.r8g.xlarge": 7000,
    "db.r5.2xlarge": 14200,
    "db.r6g.2xlarge": 14200,
    "db.r6gd.2xlarge": 14200,
    "db.r8g.2xlarge": 14200,
    "db.r5.4xlarge": 28400,
    "db.r6g.4xlarge": 28400,
    "db.r6gd.4xlarge": 28400,
    "db.r8g.4xlarge": 28400,
    "db.r5.8xlarge": 60000,
    "db.r6g.8xlarge": 60000,
    "db.r6gd.8xlarge": 60000,
    "db.r8g.8xlarge": 60000,
    "db.r5.12xlarge": 60000,
    "db.r6g.12xlarge": 60000,
    "db.r6gd.12xlarge": 60000,
    "db.r8g.12xlarge": 60000,
    "db.r5.16xlarge": 60000,
    "db.r6g.16xlarge": 60000,
    "db.r6gd.16xlarge": 60000,
    "db.r8g.16xlarge": 60000,
    "db.r5.24xlarge": 60000,
}
INSTANCE_RAM_GIB = {
    "db.t3.medium": 4,
    "db.t4g.medium": 4,
    "db.r5.large": 16,
    "db.r6g.large": 16,
    "db.r6gd.large": 16,
    "db.r8g.large": 16,
    "db.r5.xlarge": 32,
    "db.r6g.xlarge": 32,
    "db.r6gd.xlarge": 32,
    "db.r8g.xlarge": 32,
    "db.r5.2xlarge": 64,
    "db.r6g.2xlarge": 64,
    "db.r6gd.2xlarge": 64,
    "db.r8g.2xlarge": 64,
    "db.r5.4xlarge": 128,
    "db.r6g.4xlarge": 128,
    "db.r6gd.4xlarge": 128,
    "db.r8g.4xlarge": 128,
    "db.r5.8xlarge": 256,
    "db.r6g.8xlarge": 256,
    "db.r6gd.8xlarge": 256,
    "db.r8g.8xlarge": 256,
    "db.r5.12xlarge": 384,
    "db.r6g.12xlarge": 384,
    "db.r6gd.12xlarge": 384,
    "db.r8g.12xlarge": 384,
    "db.r5.16xlarge": 512,
    "db.r6g.16xlarge": 512,
    "db.r6gd.16xlarge": 512,
    "db.r8g.16xlarge": 512,
    "db.r5.24xlarge": 768,
}
GRAVITON_FAMILIES = ("r6g", "r7g", "r8g", "t4g", "r6gd")


def _add(results, pillar, check_id, label, status, detail=""):
    results.append(
        {"pillar": pillar, "id": check_id, "label": label, "status": status, "detail": detail}
    )


# ---------------------------------------------------------------------------
# Infrastructure checks (boto3)
# ---------------------------------------------------------------------------
def run_infra_checks(cluster_id, region):
    results: list[dict] = []
    docdb = boto3.client("docdb", region_name=region)
    cw = boto3.client("cloudwatch", region_name=region)
    ec2 = boto3.client("ec2", region_name=region)

    try:
        cl = docdb.describe_db_clusters(DBClusterIdentifier=cluster_id)["DBClusters"][0]
    except Exception as e:
        _add(results, "Other", "ERR", f"Cannot describe cluster: {e}", "fail")
        return results

    try:
        insts = docdb.describe_db_instances(
            Filters=[{"Name": "db-cluster-id", "Values": [cluster_id]}]
        )["DBInstances"]
    except Exception as e:
        insts = []
        _add(results, "Other", "ERR", f"Cannot describe instances: {e}", "fail")

    # -- RELIABILITY --------------------------------------------------------
    retention = cl.get("BackupRetentionPeriod", 1)
    _add(
        results,
        "Reliability",
        "REL1",
        f"Backup retention period ({retention} days)",
        "pass" if retention >= 7 else "warn" if retention >= 3 else "fail",
        "Recommended: 7+ days for production" if retention < 7 else "",
    )

    del_prot = cl.get("DeletionProtection", False)
    _add(
        results,
        "Reliability",
        "REL2",
        f"Deletion protection ({'enabled' if del_prot else 'disabled'})",
        "pass" if del_prot else "fail",
        "" if del_prot else "Enable deletion protection for production clusters",
    )

    n_inst = len(insts)
    _add(
        results,
        "Reliability",
        "REL5a",
        f"Instance count ({n_inst})",
        "pass" if n_inst >= 2 else "fail",
        "Minimum 2 instances required for auto failover" if n_inst < 2 else "",
    )

    azs = {i.get("AvailabilityZone", "") for i in insts}
    _add(
        results,
        "Reliability",
        "REL5b",
        f"Instances across {len(azs)} AZ(s)",
        "pass" if len(azs) >= 2 else "fail",
        "Single AZ -- no failover protection" if len(azs) < 2 else "",
    )

    engine_ver = cl.get("EngineVersion", "unknown")
    major = engine_ver.split(".")[0] if engine_ver != "unknown" else ""
    if major in ("3", "4"):
        _add(
            results,
            "Reliability",
            "REL6",
            f"Engine version {engine_ver} (approaching or past end-of-life)",
            "fail",
            "Upgrade to DocumentDB 5.0 or 8.0",
        )
    elif major == "5":
        _add(
            results,
            "Reliability",
            "REL6",
            f"Engine version {engine_ver}",
            "pass",
            "Consider upgrading to 8.0 for Zstandard compression and Query Planner v3",
        )
    else:
        _add(results, "Reliability", "REL6", f"Engine version {engine_ver}", "pass")

    # Recent failover events (14 days) — paginated
    try:
        evt_end = datetime.now(timezone.utc)
        evt_start = evt_end - timedelta(days=13)
        events_list = []
        paginator = docdb.get_paginator("describe_events")
        for page in paginator.paginate(
            SourceIdentifier=cluster_id,
            SourceType="db-cluster",
            StartTime=evt_start,
            EndTime=evt_end,
        ):
            events_list.extend(page.get("Events", []))
        failover_events = [
            e
            for e in events_list
            if "failover" in e.get("Message", "").lower()
            or "failover" in ",".join(e.get("EventCategories", [])).lower()
        ]
        if failover_events:
            _add(
                results,
                "Reliability",
                "REL7",
                f"{len(failover_events)} failover event(s) in last 13 days",
                "warn",
                f"Most recent: {failover_events[-1].get('Message', '')[:120]}",
            )
        else:
            _add(results, "Reliability", "REL7", "No failover events in last 13 days", "pass")
    except Exception as e:
        _add(results, "Reliability", "REL7", f"Cannot check events: {e}", "warn")

    # -- SECURITY -----------------------------------------------------------
    encrypted = cl.get("StorageEncrypted", False)
    _add(
        results,
        "Security",
        "SEC1a",
        f"Encryption at rest ({'enabled' if encrypted else 'disabled'})",
        "pass" if encrypted else "fail",
        "" if encrypted else "Enable encryption at rest (requires new cluster)",
    )

    tls_val = "unknown"
    try:
        pg_name = cl.get("DBClusterParameterGroup", "")
        if pg_name:
            params = docdb.describe_db_cluster_parameters(DBClusterParameterGroupName=pg_name).get(
                "Parameters", []
            )
            for p in params:
                if p.get("ParameterName") == "tls":
                    tls_val = p.get("ParameterValue", "enabled")
                elif p.get("ParameterName") == "tls_version":
                    tv = p.get("ParameterValue", "")
                    if tv and "1.2" in tv and "1.0" not in tv and "1.1" not in tv:
                        _add(results, "Security", "SEC6", f"TLS minimum version: {tv}", "pass")
                    elif tv:
                        _add(
                            results,
                            "Security",
                            "SEC6",
                            f"TLS minimum version: {tv}",
                            "warn",
                            "Set tls_version to TLSv1.2 to disable older protocols",
                        )
    except Exception as e:
        _add(results, "Security", "SEC6", f"Cannot check TLS parameters: {e}", "warn")
    # Ensure SEC6 is always present
    if not any(r["id"] == "SEC6" for r in results):
        _add(
            results,
            "Security",
            "SEC6",
            "TLS minimum version: unknown",
            "warn",
            "Could not determine tls_version parameter",
        )
    _add(
        results,
        "Security",
        "SEC1b",
        f"TLS ({tls_val})",
        "pass" if tls_val == "enabled" else "warn" if tls_val == "unknown" else "fail",
        (
            "Could not determine TLS status"
            if tls_val == "unknown"
            else ("" if tls_val == "enabled" else "TLS should be enabled")
        ),
    )

    # Security groups
    sg_open = False
    sg_checked = 0
    for vsg in cl.get("VpcSecurityGroups", []):
        sg_id = vsg.get("VpcSecurityGroupId", "")
        if not sg_id:
            continue
        try:
            sg_detail = ec2.describe_security_groups(GroupIds=[sg_id])["SecurityGroups"][0]
            sg_checked += 1
            for rule in sg_detail.get("IpPermissions", []):
                for ip_range in rule.get("IpRanges", []):
                    if ip_range.get("CidrIp") == "0.0.0.0/0":
                        sg_open = True
                        _add(
                            results,
                            "Security",
                            "SEC2",
                            f"Security group {sg_id} open to 0.0.0.0/0",
                            "fail",
                            "Restrict to specific CIDR ranges",
                        )
                for ip_range in rule.get("Ipv6Ranges", []):
                    if ip_range.get("CidrIpv6") == "::/0":
                        sg_open = True
                        _add(
                            results,
                            "Security",
                            "SEC2",
                            f"Security group {sg_id} open to ::/0",
                            "fail",
                            "Restrict to specific CIDR ranges",
                        )
        except Exception as e:
            _add(results, "Security", "SEC2", f"Cannot check SG {sg_id}: {e}", "warn")
    if not sg_open and sg_checked > 0:
        _add(
            results,
            "Security",
            "SEC2",
            f"Security groups properly restricted ({sg_checked} checked)",
            "pass",
        )

    logs = cl.get("EnabledCloudwatchLogsExports", [])
    audit_enabled = "audit" in logs
    profiler_enabled = "profiler" in logs
    _add(
        results,
        "Security",
        "SEC5",
        f"Audit logging ({'enabled' if audit_enabled else 'disabled'})",
        "pass" if audit_enabled else "warn",
        "" if audit_enabled else "Enable audit logging for compliance",
    )

    # Secrets Manager
    try:
        sm = boto3.client("secretsmanager", region_name=region)
        found_secret = False
        for page in sm.get_paginator("list_secrets").paginate():
            for s in page.get("SecretList", []):
                name = (s.get("Name", "") or "").lower()
                desc = (s.get("Description", "") or "").lower()
                if cluster_id.lower() in name or cluster_id.lower() in desc:
                    found_secret = True
                    break
            if found_secret:
                break
        _add(
            results,
            "Security",
            "SEC3",
            f"Secrets Manager {'references' if found_secret else 'does not reference'} this cluster",
            "pass" if found_secret else "warn",
            "" if found_secret else "Store credentials in Secrets Manager",
        )
    except Exception as e:
        _add(results, "Security", "SEC3", f"Cannot check Secrets Manager: {e}", "warn")

    # -- OPERATIONAL EXCELLENCE ---------------------------------------------
    sg_name = cl.get("DBSubnetGroup", "")
    try:
        if sg_name:
            sg = docdb.describe_db_subnet_groups(DBSubnetGroupName=sg_name)["DBSubnetGroups"][0]
            sg_azs = {s["SubnetAvailabilityZone"]["Name"] for s in sg.get("Subnets", [])}
            _add(
                results,
                "Operational Excellence",
                "OPS2",
                f"Subnet group spans {len(sg_azs)} AZ(s)",
                "pass" if len(sg_azs) >= 3 else "warn",
                "Recommended: 3 AZs for failover flexibility" if len(sg_azs) < 3 else "",
            )
    except Exception as e:
        _add(results, "Operational Excellence", "OPS2", f"Cannot check subnet group: {e}", "warn")

    _add(
        results,
        "Operational Excellence",
        "OPS5a",
        f"Profiler logging ({'enabled' if profiler_enabled else 'disabled'})",
        "pass" if profiler_enabled else "warn",
        "" if profiler_enabled else "Enable profiler for slow query analysis",
    )

    pg_name = cl.get("DBClusterParameterGroup", "")
    _add(
        results,
        "Operational Excellence",
        "OPS5c",
        f"Parameter group: {pg_name}",
        "warn" if pg_name.startswith("default.") else "pass",
        (
            "Use a custom parameter group for workload-specific tuning"
            if pg_name.startswith("default.")
            else ""
        ),
    )

    _add(
        results,
        "Operational Excellence",
        "OPS7",
        f"Maintenance window: {cl.get('PreferredMaintenanceWindow', 'not set')}",
        "info",
        "Verify this window aligns with your lowest-traffic period",
    )

    try:
        n_alarms = len(cw.describe_alarms(AlarmNamePrefix=cluster_id).get("MetricAlarms", []))
        _add(
            results,
            "Operational Excellence",
            "OPS5b",
            f"CloudWatch alarms ({n_alarms} configured)",
            "pass" if n_alarms >= 3 else "warn" if n_alarms > 0 else "fail",
            (
                "Recommended: alarms for CPU, FreeableMemory, DatabaseConnections"
                if n_alarms < 3
                else ""
            ),
        )
    except Exception as e:
        _add(results, "Operational Excellence", "OPS5b", f"Cannot check alarms: {e}", "warn")

    # -- COST OPTIMIZATION --------------------------------------------------
    try:
        n_tags = len(
            docdb.list_tags_for_resource(ResourceName=cl["DBClusterArn"]).get("TagList", [])
        )
        _add(
            results,
            "Cost Optimization",
            "COST6",
            f"Cost allocation tags ({n_tags} tags)",
            "pass" if n_tags >= 2 else "warn",
            "Add cost allocation tags for expense tracking" if n_tags < 2 else "",
        )
    except Exception as e:
        _add(results, "Cost Optimization", "COST6", f"Cannot check tags: {e}", "warn")

    storage_type = cl.get("StorageType", "standard")
    _add(
        results,
        "Cost Optimization",
        "COST7",
        f"Storage type: {storage_type}",
        "info",
        (
            "Evaluate I/O-Optimized for write-heavy workloads"
            if storage_type != "iopt1"
            else "I/O-Optimized active -- no per-I/O charges"
        ),
    )

    # -- PER-INSTANCE CHECKS ------------------------------------------------
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)

    for inst in insts:
        iid = inst["DBInstanceIdentifier"]
        itype = inst["DBInstanceClass"]
        dim = [{"Name": "DBInstanceIdentifier", "Value": iid}]
        is_writer = inst.get("IsClusterWriter", False)
        family = itype.replace("db.", "").split(".")[0] if itype.startswith("db.") else ""

        # CPU — use hourly Maximum for P95 to capture peak usage within each hour
        try:
            raw_dps = cw.get_metric_statistics(
                Namespace="AWS/DocDB",
                MetricName="CPUUtilization",
                Dimensions=dim,
                StartTime=start,
                EndTime=end,
                Period=3600,
                Statistics=["Average", "Maximum"],
            ).get("Datapoints", [])
            if raw_dps:
                avg_cpu = sum(d["Average"] for d in raw_dps) / len(raw_dps)
                max_vals = sorted(d["Maximum"] for d in raw_dps)
                p95_cpu = max_vals[int(len(max_vals) * 0.95)]
                _add(
                    results,
                    "Cost Optimization",
                    "COST1",
                    f"CPU for {iid} (avg {avg_cpu:.1f}%, P95 {p95_cpu:.1f}%)",
                    "warn" if p95_cpu < 10 else "pass",
                    f"Instance {itype} may be oversized" if p95_cpu < 10 else "",
                )
        except Exception as e:
            _add(results, "Cost Optimization", "COST1", f"Cannot check CPU for {iid}: {e}", "warn")

        # Graviton
        _add(
            results,
            "Sustainability",
            "SUST1",
            f"{iid} {'uses' if family in GRAVITON_FAMILIES else 'does not use'} Graviton ({itype})",
            "pass" if family in GRAVITON_FAMILIES else "warn",
            (
                ""
                if family in GRAVITON_FAMILIES
                else "Migrate to Graviton (r6g/r8g) for better price-performance"
            ),
        )

        # Buffer cache hit ratio
        try:
            dps = [
                d["Average"]
                for d in cw.get_metric_statistics(
                    Namespace="AWS/DocDB",
                    MetricName="BufferCacheHitRatio",
                    Dimensions=dim,
                    StartTime=start,
                    EndTime=end,
                    Period=3600,
                    Statistics=["Average"],
                ).get("Datapoints", [])
            ]
            if dps:
                avg_cache = sum(dps) / len(dps)
                _add(
                    results,
                    "Performance Efficiency",
                    "PERF6",
                    f"Buffer cache hit ratio for {iid} ({avg_cache:.1f}%)",
                    "pass" if avg_cache >= 99 else "warn" if avg_cache >= 95 else "fail",
                    "Working set may not fit in memory" if avg_cache < 95 else "",
                )
        except Exception as e:
            _add(
                results,
                "Performance Efficiency",
                "PERF6",
                f"Cannot check cache for {iid}: {e}",
                "warn",
            )

        # Connections vs limits
        try:
            dps = [
                d["Maximum"]
                for d in cw.get_metric_statistics(
                    Namespace="AWS/DocDB",
                    MetricName="DatabaseConnections",
                    Dimensions=dim,
                    StartTime=start,
                    EndTime=end,
                    Period=3600,
                    Statistics=["Maximum"],
                ).get("Datapoints", [])
            ]
            limit = CONN_LIMITS.get(itype, 0)
            if dps and limit:
                max_conn = max(dps)
                pct = max_conn / limit * 100
                _add(
                    results,
                    "Performance Efficiency",
                    "PERF5",
                    f"Peak connections for {iid} ({int(max_conn)}/{limit} = {pct:.0f}%)",
                    "pass" if pct < 70 else "warn" if pct < 90 else "fail",
                    "Consider upsizing or connection pooling" if pct >= 70 else "",
                )
            elif dps:
                _add(
                    results,
                    "Performance Efficiency",
                    "PERF5",
                    f"Connection limit unknown for {iid} ({itype})",
                    "warn",
                    "Instance type not in lookup table",
                )
        except Exception as e:
            _add(
                results,
                "Performance Efficiency",
                "PERF5",
                f"Cannot check connections for {iid}: {e}",
                "warn",
            )

        # Idle reader detection
        if not is_writer:
            try:
                conn_dps = [
                    d["Average"]
                    for d in cw.get_metric_statistics(
                        Namespace="AWS/DocDB",
                        MetricName="DatabaseConnections",
                        Dimensions=dim,
                        StartTime=start,
                        EndTime=end,
                        Period=3600,
                        Statistics=["Average"],
                    ).get("Datapoints", [])
                ]
                io_dps = [
                    d["Average"]
                    for d in cw.get_metric_statistics(
                        Namespace="AWS/DocDB",
                        MetricName="ReadIOPS",
                        Dimensions=dim,
                        StartTime=start,
                        EndTime=end,
                        Period=3600,
                        Statistics=["Average"],
                    ).get("Datapoints", [])
                ]
                avg_conn = sum(conn_dps) / len(conn_dps) if conn_dps else 0
                avg_iops = sum(io_dps) / len(io_dps) if io_dps else 0
                if avg_conn < 2 and avg_iops < 5:
                    _add(
                        results,
                        "Cost Optimization",
                        "COST9",
                        f"Reader {iid} appears idle (avg {avg_conn:.0f} conn, {avg_iops:.0f} ReadIOPS)",
                        "warn",
                        "Consider removing this replica to reduce cost",
                    )
                else:
                    _add(
                        results,
                        "Cost Optimization",
                        "COST9",
                        f"Reader {iid} is active (avg {avg_conn:.0f} conn, {avg_iops:.0f} ReadIOPS)",
                        "pass",
                    )
            except Exception as e:
                _add(
                    results, "Cost Optimization", "COST9", f"Cannot check reader {iid}: {e}", "warn"
                )

        # FreeableMemory
        ram_gib = INSTANCE_RAM_GIB.get(itype, 0)
        if ram_gib:
            try:
                dps = [
                    d["Minimum"]
                    for d in cw.get_metric_statistics(
                        Namespace="AWS/DocDB",
                        MetricName="FreeableMemory",
                        Dimensions=dim,
                        StartTime=start,
                        EndTime=end,
                        Period=3600,
                        Statistics=["Minimum"],
                    ).get("Datapoints", [])
                ]
                if dps:
                    min_free = min(dps)
                    free_pct = min_free / (ram_gib * 1024**3) * 100
                    _add(
                        results,
                        "Performance Efficiency",
                        "PERF11",
                        f"FreeableMemory min for {iid}: {min_free / (1024**3):.1f} GiB ({free_pct:.0f}%)",
                        "fail" if free_pct < 5 else "warn" if free_pct < 10 else "pass",
                        "Instance under memory pressure" if free_pct < 10 else "",
                    )
            except Exception as e:
                _add(
                    results,
                    "Performance Efficiency",
                    "PERF11",
                    f"Cannot check memory for {iid}: {e}",
                    "warn",
                )
        else:
            _add(
                results,
                "Performance Efficiency",
                "PERF11",
                f"Unknown instance type {itype} -- cannot check FreeableMemory",
                "warn",
            )

        # SwapUsage
        try:
            dps = [
                d["Maximum"]
                for d in cw.get_metric_statistics(
                    Namespace="AWS/DocDB",
                    MetricName="SwapUsage",
                    Dimensions=dim,
                    StartTime=start,
                    EndTime=end,
                    Period=3600,
                    Statistics=["Maximum"],
                ).get("Datapoints", [])
            ]
            if dps and max(dps) > 0:
                _add(
                    results,
                    "Performance Efficiency",
                    "PERF12",
                    f"SwapUsage max for {iid}: {max(dps) / (1024**2):.0f} MB",
                    "fail",
                    "Instance is swapping -- critically undersized",
                )
            elif dps:
                _add(results, "Performance Efficiency", "PERF12", f"No swap on {iid}", "pass")
        except Exception as e:
            _add(
                results,
                "Performance Efficiency",
                "PERF12",
                f"Cannot check swap for {iid}: {e}",
                "warn",
            )

        # DiskQueueDepth
        try:
            dps = [
                d["Average"]
                for d in cw.get_metric_statistics(
                    Namespace="AWS/DocDB",
                    MetricName="DiskQueueDepth",
                    Dimensions=dim,
                    StartTime=start,
                    EndTime=end,
                    Period=3600,
                    Statistics=["Average"],
                ).get("Datapoints", [])
            ]
            if dps:
                avg_dqd = sum(dps) / len(dps)
                _add(
                    results,
                    "Performance Efficiency",
                    "PERF13",
                    f"DiskQueueDepth avg for {iid}: {avg_dqd:.1f}",
                    "warn" if avg_dqd > 5 else "pass",
                    "I/O backing up -- evaluate I/O-Optimized or upsizing" if avg_dqd > 5 else "",
                )
        except Exception as e:
            _add(
                results,
                "Performance Efficiency",
                "PERF13",
                f"Cannot check DiskQueueDepth for {iid}: {e}",
                "warn",
            )

        # IndexBufferCacheHitRatio
        try:
            dps = [
                d["Average"]
                for d in cw.get_metric_statistics(
                    Namespace="AWS/DocDB",
                    MetricName="IndexBufferCacheHitRatio",
                    Dimensions=dim,
                    StartTime=start,
                    EndTime=end,
                    Period=3600,
                    Statistics=["Average"],
                ).get("Datapoints", [])
            ]
            if dps:
                avg_idx = sum(dps) / len(dps)
                _add(
                    results,
                    "Performance Efficiency",
                    "PERF14",
                    f"IndexBufferCacheHitRatio for {iid}: {avg_idx:.1f}%",
                    "pass" if avg_idx >= 99 else "warn" if avg_idx >= 95 else "fail",
                    "Indexes do not fit in memory" if avg_idx < 95 else "",
                )
        except Exception as e:
            _add(
                results,
                "Performance Efficiency",
                "PERF14",
                f"Cannot check index cache for {iid}: {e}",
                "warn",
            )

        # DatabaseCursorsTimedOut
        try:
            dps = [
                d["Sum"]
                for d in cw.get_metric_statistics(
                    Namespace="AWS/DocDB",
                    MetricName="DatabaseCursorsTimedOut",
                    Dimensions=dim,
                    StartTime=start,
                    EndTime=end,
                    Period=86400,
                    Statistics=["Sum"],
                ).get("Datapoints", [])
            ]
            total = sum(dps) if dps else 0
            if total > 0:
                _add(
                    results,
                    "Reliability",
                    "REL8",
                    f"{int(total)} cursor(s) timed out on {iid} in last 7 days",
                    "warn",
                    "Application may not be closing cursors properly",
                )
            else:
                _add(results, "Reliability", "REL8", f"No cursor timeouts on {iid}", "pass")
        except Exception as e:
            _add(results, "Reliability", "REL8", f"Cannot check cursors for {iid}: {e}", "warn")

        # AvailableMVCCIds (writer only)
        if is_writer:
            try:
                dps = [
                    d["Minimum"]
                    for d in cw.get_metric_statistics(
                        Namespace="AWS/DocDB",
                        MetricName="AvailableMVCCIds",
                        Dimensions=dim,
                        StartTime=start,
                        EndTime=end,
                        Period=3600,
                        Statistics=["Minimum"],
                    ).get("Datapoints", [])
                ]
                if dps:
                    min_mvcc = min(dps)
                    pct = min_mvcc / 1_400_000_000 * 100
                    _add(
                        results,
                        "Reliability",
                        "REL9",
                        f"AvailableMVCCIds min: {min_mvcc:,.0f} ({pct:.0f}%)",
                        "fail" if pct < 25 else "warn" if pct < 50 else "pass",
                        (
                            "MVCC ID exhaustion risk -- investigate long-running transactions"
                            if pct < 50
                            else ""
                        ),
                    )
            except Exception as e:
                _add(results, "Reliability", "REL9", f"Cannot check MVCCIds: {e}", "warn")

    return results


# ---------------------------------------------------------------------------
# Database-level checks (from pre-collected analysis JSON)
# ---------------------------------------------------------------------------
def run_db_checks(analysis_data):
    results: list[dict] = []
    if not analysis_data:
        return results

    total_indexes = 0
    unused_indexes = 0
    redundant = 0
    low_cardinality = 0
    low_card_names = []
    large_docs = []
    ttl_colls = []
    total_data_size = 0
    total_index_size = 0
    total_unused_bytes = 0
    bloated_colls = []
    over_indexed_colls = []
    compression_disabled = []
    collscan_candidates = []
    write_amp_colls = []

    for db_name, collections in analysis_data.items():
        if not isinstance(collections, dict):
            continue
        for coll_name, stats in collections.items():
            if not isinstance(stats, dict) or "error" in stats:
                continue
            indexes = stats.get("indexes", [])
            total_indexes += len(indexes)

            for idx in indexes:
                if idx.get("usage", {}).get("potential_unused"):
                    unused_indexes += 1
                if idx.get("cardinality", {}).get("is_low"):
                    low_cardinality += 1
                    low_card_names.append(f"{db_name}.{coll_name}.{idx['name']}")
                if idx.get("expireAfterSeconds") is not None:
                    if f"{db_name}.{coll_name}" not in ttl_colls:
                        ttl_colls.append(f"{db_name}.{coll_name}")

            avg_obj = stats.get("avgObjSize", 0)
            if avg_obj > 8192:
                large_docs.append(f"{db_name}.{coll_name} ({avg_obj:,} bytes)")

            # Redundant indexes (prefix subset)
            ordered = [tuple(idx.get("ordered_fields", [])) for idx in indexes]
            for i, a in enumerate(ordered):
                for j, b in enumerate(ordered):
                    if i != j and len(a) > 0 and len(a) < len(b) and b[: len(a)] == a:
                        redundant += 1
                        break

            total_data_size += stats.get("size", 0)
            for idx in indexes:
                total_index_size += idx.get("size", 0)

            unused_info = stats.get("unusedStorageSize", {})
            unused_pct = unused_info.get("unusedPercent", 0.0)
            total_unused_bytes += unused_info.get("unusedBytes", 0)
            if unused_pct > 30:
                bloated_colls.append(f"{db_name}.{coll_name} ({unused_pct:.0f}%)")

            if len(indexes) > 10:
                over_indexed_colls.append(f"{db_name}.{coll_name} ({len(indexes)} indexes)")

            comp = stats.get("compression", {})
            if not comp.get("enabled", False):
                compression_disabled.append(f"{db_name}.{coll_name}")

            doc_count = stats.get("count", 0)
            non_id = [idx for idx in indexes if idx.get("name") != "_id_"]
            if doc_count > 100000 and len(non_id) == 0:
                collscan_candidates.append(f"{db_name}.{coll_name} ({doc_count:,} docs)")

            coll_data = stats.get("size", 0)
            coll_idx = sum(idx.get("size", 0) for idx in indexes)
            if coll_data > 0 and coll_idx > 2 * coll_data:
                write_amp_colls.append(
                    f"{db_name}.{coll_name} (index {coll_idx / coll_data:.1f}x data)"
                )

    # Emit checks
    if large_docs:
        _add(
            results,
            "Performance Efficiency",
            "PERF1",
            f"{len(large_docs)} collection(s) with avg doc size > 8 KB",
            "warn",
            ", ".join(large_docs[:5]),
        )
    else:
        _add(
            results,
            "Performance Efficiency",
            "PERF1",
            "All collections have avg doc size < 8 KB",
            "pass",
        )

    if redundant > 0:
        _add(
            results,
            "Performance Efficiency",
            "PERF1b",
            f"{redundant} redundant index(es) (prefix subsets)",
            "warn",
        )
    else:
        _add(results, "Performance Efficiency", "PERF1b", "No redundant indexes detected", "pass")

    if low_cardinality > 0:
        _add(
            results,
            "Performance Efficiency",
            "PERF1c",
            f"{low_cardinality} low cardinality index(es)",
            "warn",
            ", ".join(low_card_names[:5]),
        )
    else:
        _add(
            results,
            "Performance Efficiency",
            "PERF1c",
            "No low cardinality indexes detected",
            "pass",
        )

    if unused_indexes > 0:
        _add(
            results,
            "Cost Optimization",
            "COST3",
            f"{unused_indexes} unused index(es) of {total_indexes} total",
            "warn",
            "Remove unused indexes to reduce write overhead and storage",
        )
    else:
        _add(
            results,
            "Cost Optimization",
            "COST3",
            f"No unused indexes ({total_indexes} total)",
            "pass",
        )

    if ttl_colls:
        _add(
            results,
            "Cost Optimization",
            "COST4",
            f"TTL indexes on {len(ttl_colls)} collection(s)",
            "pass",
            ", ".join(ttl_colls[:5]),
        )
    else:
        _add(
            results,
            "Cost Optimization",
            "COST4",
            "No TTL indexes found",
            "warn",
            "Consider TTL indexes for automatic data expiration",
        )

    if total_data_size > 0:
        ratio = total_index_size / total_data_size * 100
        _add(
            results,
            "Performance Efficiency",
            "PERF8",
            f"Index-to-data ratio: {ratio:.0f}%",
            "warn" if ratio > 50 else "pass",
            "Indexes exceed 50% of data size" if ratio > 50 else "",
        )

    if bloated_colls:
        _add(
            results,
            "Performance Efficiency",
            "PERF9",
            f"{len(bloated_colls)} collection(s) with >30% storage bloat",
            "warn",
            "Run compact command. " + ", ".join(bloated_colls[:5]),
        )
    else:
        _add(results, "Performance Efficiency", "PERF9", "No significant storage bloat", "pass")

    if over_indexed_colls:
        _add(
            results,
            "Performance Efficiency",
            "PERF10",
            f"{len(over_indexed_colls)} collection(s) with >10 indexes",
            "warn",
            ", ".join(over_indexed_colls[:5]),
        )
    else:
        _add(results, "Performance Efficiency", "PERF10", "No over-indexed collections", "pass")

    if compression_disabled:
        _add(
            results,
            "Sustainability",
            "SUST2",
            f"Compression disabled on {len(compression_disabled)} collection(s)",
            "warn",
            ", ".join(compression_disabled[:5]),
        )
    else:
        _add(results, "Sustainability", "SUST2", "Compression enabled on all collections", "pass")

    if collscan_candidates:
        _add(
            results,
            "Performance Efficiency",
            "PERF15",
            f"{len(collscan_candidates)} large collection(s) with no secondary indexes",
            "warn",
            ", ".join(collscan_candidates[:5]),
        )
    else:
        _add(
            results,
            "Performance Efficiency",
            "PERF15",
            "All large collections have secondary indexes",
            "pass",
        )

    if write_amp_colls:
        _add(
            results,
            "Performance Efficiency",
            "PERF16",
            f"{len(write_amp_colls)} collection(s) with index size > 2x data",
            "warn",
            ", ".join(write_amp_colls[:5]),
        )
    else:
        _add(
            results, "Performance Efficiency", "PERF16", "No excessive index-to-data ratio", "pass"
        )

    return results


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def generate_report(results, cluster_id, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON output
    json_path = output_dir / "wa_review_results.json"
    with open(json_path, "w") as f:
        json.dump(
            {
                "cluster": cluster_id,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "checks": results,
            },
            f,
            indent=2,
        )

    # Markdown summary
    md_path = output_dir / "wa_review_report.md"
    pillars: dict[str, list] = {}
    for r in results:
        pillars.setdefault(r["pillar"], []).append(r)

    counts = {"pass": 0, "warn": 0, "fail": 0, "info": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    lines = [
        f"# Well-Architected Review: {cluster_id}\n",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n",
        f"**Summary:** {counts['pass']} pass, {counts['warn']} warnings, "
        f"{counts['fail']} failures, {counts['info']} info\n",
    ]

    status_icon = {"pass": "[PASS]", "warn": "[WARN]", "fail": "[FAIL]", "info": "[INFO]"}
    for pillar in [
        "Reliability",
        "Security",
        "Operational Excellence",
        "Cost Optimization",
        "Performance Efficiency",
        "Sustainability",
    ]:
        checks = pillars.get(pillar, [])
        if not checks:
            continue
        lines.append(f"\n## {pillar}\n")
        lines.append("| Status | Check | Detail |")
        lines.append("|--------|-------|--------|")
        for c in checks:
            icon = status_icon.get(c["status"], c["status"])
            label = c.get("label", "").replace("|", "/")
            detail = c.get("detail", "").replace("|", "/")
            lines.append(f"| {icon} | {label} | {detail} |")

    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return json_path, md_path


# ---------------------------------------------------------------------------
# Collect database stats via pymongo (--uri)
# ---------------------------------------------------------------------------
def _redact_uri_creds(msg):
    """Strip any embedded mongodb credentials (user:pass@) from an error
    message so they are never printed to stdout/logs."""
    return re.sub(r"://[^/@\s]*@", "://<redacted>@", str(msg))


def collect_db_stats(uri, tls_ca_file=None, tls_allow_invalid_certs=False):
    """Connect to DocumentDB/MongoDB, collect collStats + indexStats for all
    collections across all databases. Returns analysis_data dict compatible
    with run_db_checks()."""
    try:
        import pymongo
    except ImportError:
        print("ERROR: pymongo required for --uri. Install with: pip install pymongo")
        sys.exit(1)

    client = pymongo.MongoClient(
        uri,
        serverSelectionTimeoutMS=10000,
        tlsAllowInvalidCertificates=tls_allow_invalid_certs,
        **({"tlsCAFile": tls_ca_file} if tls_ca_file else {}),
    )
    analysis: dict[str, dict] = {}
    skip_dbs = {"admin", "local", "config"}

    try:
        for db_name in client.list_database_names():
            if db_name in skip_dbs:
                continue
            db = client[db_name]
            collections: dict[str, dict] = {}
            for coll_name in db.list_collection_names():
                if coll_name.startswith("system."):
                    continue
                try:
                    stats = db.command("collStats", coll_name)
                    idx_stats = list(db[coll_name].aggregate([{"$indexStats": {}}]))

                    indexes: list[dict] = []
                    raw_indexes = list(db[coll_name].list_indexes())
                    idx_usage = {s["name"]: s.get("accesses", {}).get("ops", 0) for s in idx_stats}

                    for idx in raw_indexes:
                        name = idx["name"]
                        key = idx.get("key", {})
                        size = stats.get("indexSizes", {}).get(name, 0)
                        ops = idx_usage.get(name, 0)
                        ordered_fields = list(key.keys())

                        entry = {
                            "name": name,
                            "fields": key,
                            "ordered_fields": ordered_fields,
                            "size": size,
                            "usage": {"ops": ops, "potential_unused": ops == 0 and name != "_id_"},
                            "cardinality": {"is_low": False},
                        }
                        if idx.get("expireAfterSeconds") is not None:
                            entry["expireAfterSeconds"] = idx["expireAfterSeconds"]
                        indexes.append(entry)

                    comp_enabled = False
                    comp_info = stats.get("compression", {})
                    comp_enabled = comp_info.get("enabled", False) or comp_info.get("enable", False)

                    data_size = stats.get("size", 0)
                    storage_size = stats.get("storageSize", 0)
                    unused_bytes = (
                        max(0, storage_size - data_size) if storage_size > data_size else 0
                    )
                    unused_pct = (unused_bytes / storage_size * 100) if storage_size > 0 else 0

                    collections[coll_name] = {
                        "count": stats.get("count", 0),
                        "size": data_size,
                        "storageSize": storage_size,
                        "avgObjSize": stats.get("avgObjSize", 0),
                        "totalIndexSize": stats.get("totalIndexSize", 0),
                        "indexes": indexes,
                        "compression": {"enabled": comp_enabled},
                        "unusedStorageSize": {
                            "unusedBytes": unused_bytes,
                            "unusedPercent": unused_pct,
                        },
                    }
                except Exception as e:
                    collections[coll_name] = {"error": str(e)}

            if collections:
                analysis[db_name] = collections
    except Exception as e:
        print(f"  ERROR: Cannot connect to database: {_redact_uri_creds(e)}")
        return {}
    finally:
        client.close()

    return analysis


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="DocumentDB Well-Architected Review")
    parser.add_argument("--cluster-id", required=True, help="DocumentDB cluster identifier")
    parser.add_argument("--region", required=True, help="AWS region")
    parser.add_argument(
        "--uri", default=None, help="MongoDB/DocumentDB connection URI for database-level checks"
    )
    parser.add_argument(
        "--analysis-data",
        default=None,
        help="Path to JSON file with database-level analysis (alternative to --uri)",
    )
    parser.add_argument(
        "--tls-ca-file",
        default=None,
        help="Path to CA bundle (e.g., global-bundle.pem) for TLS verification",
    )
    parser.add_argument(
        "--tls-allow-invalid-certs",
        action="store_true",
        default=False,
        help="Disable TLS certificate verification (not recommended)",
    )
    parser.add_argument("--output", default=".", help="Output directory (default: current)")
    args = parser.parse_args()

    print(f"Running Well-Architected Review for {args.cluster_id} in {args.region}...")

    # Infrastructure checks
    print("  Running infrastructure checks (AWS APIs)...")
    results = run_infra_checks(args.cluster_id, args.region)
    print(f"  Infrastructure: {len(results)} checks completed")

    # Database-level checks
    analysis = None
    if args.uri:
        print(f"  Collecting database stats via pymongo...")
        analysis = collect_db_stats(args.uri, args.tls_ca_file, args.tls_allow_invalid_certs)
        n_colls = sum(len(v) for v in analysis.values())
        print(f"  Collected stats for {n_colls} collections across {len(analysis)} databases")
    elif args.analysis_data:
        print(f"  Loading database stats from {args.analysis_data}...")
        with open(args.analysis_data) as f:
            analysis = json.load(f)

    if analysis:
        print("  Running database-level checks...")
        db_results = run_db_checks(analysis)
        results.extend(db_results)
        print(f"  Database: {len(db_results)} checks completed")
    else:
        print("  Skipping database-level checks (no --uri or --analysis-data)")

    # Generate report
    json_path, md_path = generate_report(results, args.cluster_id, args.output)
    print(f"\n  Results: {json_path}")
    print(f"  Report:  {md_path}")

    # Summary
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(
        f"\n  Total: {len(results)} checks -- "
        f"{counts.get('pass', 0)} pass, {counts.get('warn', 0)} warn, "
        f"{counts.get('fail', 0)} fail, {counts.get('info', 0)} info"
    )


if __name__ == "__main__":
    main()
