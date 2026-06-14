"""Aurora I/O-Optimized vs Standard cost analyzer.

Assesses whether Aurora I/O-Optimized is a better fit than Aurora Standard for
one cluster, all clusters in a region, or offline user-supplied numbers.

Decision: I/O-Optimized is recommended when it actually lowers total monthly cost
(eliminated I/O charges exceed the compute + storage premium). The "I/O >= 25% of
total spend" figure is a useful rule-of-thumb, but the recommendation is gated on the
computed dollar savings, not the percentage alone (they can diverge near breakeven).
Same logic across Aurora engines (engine-neutral pricing math).

Pricing math and breakeven logic cross-checked with AWS documentation.

Usage:
    python io_optimized_analyzer.py --cluster my-cluster --region us-east-1
    python io_optimized_analyzer.py --all --region us-east-1 --days 14
    python io_optimized_analyzer.py offline --instance db.r6g.2xlarge \\
        --num-instances 2 --storage-gib 800 --monthly-io-millions 1200
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Pricing constants (us-east-1). Overridden by live API when available.
# ---------------------------------------------------------------------------
STORAGE_STANDARD_PER_GIB = 0.10  # $/GiB-month, Standard
STORAGE_IO_OPT_PER_GIB = 0.225  # $/GiB-month, I/O-Optimized
IO_COST_PER_MILLION = 0.20  # $/million I/O requests, Standard only
IO_OPT_COMPUTE_MULTIPLIER = 1.30  # 30% compute premium on I/O-Optimized
IO_OPT_BREAKEVEN_PCT = 25.0
HOURS_PER_MONTH = 730
MIN_VIABLE_DAYS = 7.0

# Static instance hourly prices (us-east-1, Standard, Aurora MySQL).
# Aurora MySQL and PostgreSQL share these rates; I/O-Optimized is derived via the multiplier.
_STATIC_INSTANCE_PRICES = {
    "db.t3.medium": 0.082,
    "db.t3.large": 0.164,
    "db.t4g.medium": 0.073,
    "db.t4g.large": 0.146,
    "db.r5.large": 0.290,
    "db.r5.xlarge": 0.580,
    "db.r5.2xlarge": 1.160,
    "db.r5.4xlarge": 2.320,
    "db.r5.8xlarge": 4.640,
    "db.r5.12xlarge": 6.960,
    "db.r5.16xlarge": 9.280,
    "db.r5.24xlarge": 13.920,
    "db.r6g.large": 0.260,
    "db.r6g.xlarge": 0.519,
    "db.r6g.2xlarge": 1.038,
    "db.r6g.4xlarge": 2.076,
    "db.r6g.8xlarge": 4.152,
    "db.r6g.12xlarge": 6.228,
    "db.r6g.16xlarge": 8.304,
    "db.r7g.large": 0.276,
    "db.r7g.xlarge": 0.553,
    "db.r7g.2xlarge": 1.106,
    "db.r7g.4xlarge": 2.211,
    "db.r7g.8xlarge": 4.422,
    "db.r7g.12xlarge": 6.633,
    "db.r7g.16xlarge": 8.844,
    "db.r8g.large": 0.276,
    "db.r8g.xlarge": 0.552,
    "db.r8g.2xlarge": 1.104,
    "db.r8g.4xlarge": 2.208,
    "db.r8g.8xlarge": 4.416,
    "db.r8g.12xlarge": 6.624,
    "db.r8g.16xlarge": 8.832,
    "db.r8g.24xlarge": 13.248,
    "db.r8g.48xlarge": 26.496,
}

_REGION_NAMES = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-north-1": "EU (Stockholm)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ca-central-1": "Canada (Central)",
    "sa-east-1": "South America (Sao Paulo)",
}

INSTANCE_PRICES = dict(_STATIC_INSTANCE_PRICES)
_pricing_source: dict[str, Any] = {"source": "static_fallback", "region": "us-east-1"}


# ---------------------------------------------------------------------------
# Live pricing (best-effort)
# ---------------------------------------------------------------------------


def refresh_pricing(region: str) -> dict:
    """Try to fetch live instance + storage + I/O pricing. Silent fallback on failure."""
    global INSTANCE_PRICES, STORAGE_STANDARD_PER_GIB, STORAGE_IO_OPT_PER_GIB
    global IO_COST_PER_MILLION, _pricing_source

    location = _REGION_NAMES.get(region)
    if not location:
        _pricing_source = {
            "source": "static_fallback",
            "region": region,
            "note": f"Region {region} not mapped; using us-east-1 defaults",
        }
        return _pricing_source

    try:
        import boto3
    except ImportError:
        _pricing_source = {
            "source": "static_fallback",
            "region": region,
            "note": "boto3 not installed",
        }
        return _pricing_source

    try:
        pricing = boto3.client("pricing", region_name="us-east-1")
        live_instances = 0
        filters = [
            {"Type": "TERM_MATCH", "Field": "databaseEngine", "Value": "Aurora MySQL"},
            {"Type": "TERM_MATCH", "Field": "location", "Value": location},
            {"Type": "TERM_MATCH", "Field": "deploymentOption", "Value": "Single-AZ"},
            {"Type": "TERM_MATCH", "Field": "termType", "Value": "OnDemand"},
        ]
        for page in pricing.get_paginator("get_products").paginate(
            ServiceCode="AmazonRDS", Filters=filters
        ):
            for item_json in page["PriceList"]:
                item = json.loads(item_json) if isinstance(item_json, str) else item_json
                attrs = item.get("product", {}).get("attributes", {})
                itype = attrs.get("instanceType", "")
                if not itype.startswith("db."):
                    continue
                if "IOOptimized" in attrs.get("usagetype", ""):
                    continue
                for term in item.get("terms", {}).get("OnDemand", {}).values():
                    for dim in term.get("priceDimensions", {}).values():
                        try:
                            price = float(dim.get("pricePerUnit", {}).get("USD", "0"))
                        except (ValueError, TypeError):
                            continue
                        if price > 0:
                            INSTANCE_PRICES[itype] = price
                            live_instances += 1

        # Storage + I/O pricing
        storage_filters = [
            {"Type": "TERM_MATCH", "Field": "databaseEngine", "Value": "Aurora MySQL"},
            {"Type": "TERM_MATCH", "Field": "location", "Value": location},
            {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Database Storage"},
            {"Type": "TERM_MATCH", "Field": "termType", "Value": "OnDemand"},
        ]
        for page in pricing.get_paginator("get_products").paginate(
            ServiceCode="AmazonRDS", Filters=storage_filters
        ):
            for item_json in page["PriceList"]:
                item = json.loads(item_json) if isinstance(item_json, str) else item_json
                attrs = item.get("product", {}).get("attributes", {})
                usage = attrs.get("usagetype", "")
                for term in item.get("terms", {}).get("OnDemand", {}).values():
                    for dim in term.get("priceDimensions", {}).values():
                        try:
                            price = float(dim.get("pricePerUnit", {}).get("USD", "0"))
                        except (ValueError, TypeError):
                            continue
                        if price <= 0:
                            continue
                        if "IOOptimized" in usage:
                            STORAGE_IO_OPT_PER_GIB = price
                        elif "Aurora:StorageUsage" in usage:
                            STORAGE_STANDARD_PER_GIB = price
                        elif "Aurora:StorageIOUsage" in usage:
                            IO_COST_PER_MILLION = price * 1_000_000  # per-request -> per-million

        _pricing_source = {
            "source": "live",
            "region": region,
            "live_instances": live_instances,
            "storage_standard": STORAGE_STANDARD_PER_GIB,
            "storage_io_opt": STORAGE_IO_OPT_PER_GIB,
            "io_per_million": IO_COST_PER_MILLION,
        }
    except Exception as e:
        _pricing_source = {"source": "static_fallback", "region": region, "error": str(e)}

    return _pricing_source


# ---------------------------------------------------------------------------
# Core calculation (shared by live and offline paths)
# ---------------------------------------------------------------------------


def compute_comparison(
    compute_monthly: float,
    storage_gib: float,
    monthly_io_millions: float,
) -> dict:
    """Return Standard vs I/O-Optimized comparison and recommendation."""
    storage_std = storage_gib * STORAGE_STANDARD_PER_GIB
    io_cost = monthly_io_millions * IO_COST_PER_MILLION
    total_std = compute_monthly + storage_std + io_cost

    compute_io_opt = compute_monthly * IO_OPT_COMPUTE_MULTIPLIER
    storage_io_opt = storage_gib * STORAGE_IO_OPT_PER_GIB
    total_io_opt = compute_io_opt + storage_io_opt

    io_pct = (io_cost / total_std * 100) if total_std > 0 else 0
    savings = total_std - total_io_opt

    # Drive the recommendation off the ACTUAL dollar savings, not the 25% heuristic
    # alone — near the breakeven boundary the two diverge, and gating purely on the
    # threshold can recommend I/O-Optimized while it actually costs more (and print a
    # nonsensical "saves $-N/mo"). The 25% rule is a useful rule-of-thumb but the real
    # decision is whether the I/O charges eliminated exceed the compute+storage premium.
    threshold_note = (
        f"I/O is {io_pct:.0f}% of total cost "
        f"({'≥' if io_pct >= IO_OPT_BREAKEVEN_PCT else 'below '}{IO_OPT_BREAKEVEN_PCT:.0f}% rule-of-thumb)."
    )
    if savings > 0:
        rec = "io_optimized"
        reason = f"{threshold_note} I/O-Optimized saves ${savings:.0f}/mo."
    else:
        rec = "standard"
        reason = f"{threshold_note} I/O-Optimized would cost ${abs(savings):.0f}/mo more."

    return {
        "standard": {
            "compute_monthly": round(compute_monthly, 2),
            "storage_monthly": round(storage_std, 2),
            "io_monthly": round(io_cost, 2),
            "total_monthly": round(total_std, 2),
        },
        "io_optimized": {
            "compute_monthly": round(compute_io_opt, 2),
            "storage_monthly": round(storage_io_opt, 2),
            "io_monthly": 0.0,
            "total_monthly": round(total_io_opt, 2),
        },
        "monthly_io_millions": round(monthly_io_millions, 1),
        "storage_gib": round(storage_gib, 1),
        "io_cost_pct_of_total": round(io_pct, 1),
        "savings_with_io_opt": round(savings, 2),
        "recommendation": rec,
        "reason": reason,
    }


def data_quality_tag(days: float) -> str:
    if days < 3:
        return "insufficient"
    if days < 7:
        return "short"
    if days < 14:
        return "adequate"
    return "good"


# ---------------------------------------------------------------------------
# Live AWS path
# ---------------------------------------------------------------------------


def _sum_metric(cw, cluster_id: str, metric: str, start: dt.datetime, end: dt.datetime) -> float:
    """Sum a CloudWatch metric over the window. Returns total."""
    resp = cw.get_metric_statistics(
        Namespace="AWS/RDS",
        MetricName=metric,
        Dimensions=[{"Name": "DBClusterIdentifier", "Value": cluster_id}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Sum"],
    )
    return sum(dp.get("Sum", 0) for dp in resp.get("Datapoints", []))


def _avg_metric(cw, cluster_id: str, metric: str, start: dt.datetime, end: dt.datetime) -> float:
    """Average a CloudWatch metric over the window."""
    resp = cw.get_metric_statistics(
        Namespace="AWS/RDS",
        MetricName=metric,
        Dimensions=[{"Name": "DBClusterIdentifier", "Value": cluster_id}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Average"],
    )
    dps = resp.get("Datapoints", [])
    return (sum(dp.get("Average", 0) for dp in dps) / len(dps)) if dps else 0.0


def _is_empty_cluster(cluster: dict) -> bool:
    """Skip clusters with no compute to analyze.

    An Aurora cluster with no DB instances has no compute cost to compare. The
    genuine cause is a cluster whose last writer/reader instance was deleted.
    Note: an auto-paused (scale-to-zero) Aurora
    serverless instance still appears in DBClusterMembers and is analyzable, so
    it is NOT an empty cluster. The cost comparison doesn't apply here — skip.
    """
    return len(cluster.get("DBClusterMembers", [])) == 0


def analyze_cluster_live(cluster_id: str, region: str, days: int) -> dict:
    """Analyze a single cluster using live AWS APIs."""
    import boto3

    rds = boto3.client("rds", region_name=region)
    cw = boto3.client("cloudwatch", region_name=region)

    # Cluster metadata
    resp = rds.describe_db_clusters(DBClusterIdentifier=cluster_id)
    clusters = resp.get("DBClusters", [])
    if not clusters:
        return {"cluster_id": cluster_id, "error": "cluster not found"}
    cluster = clusters[0]
    current_storage_type = cluster.get("StorageType", "aurora")  # 'aurora' or 'aurora-iopt1'
    engine = cluster.get("Engine", "")

    # Guardrail: skip clusters with no DB instances (last instance deleted / paused)
    if _is_empty_cluster(cluster):
        return {
            "cluster_id": cluster_id,
            "engine": engine,
            "engine_version": cluster.get("EngineVersion", ""),
            "current_storage_type": current_storage_type,
            "skipped": True,
            "reason": (
                "Cluster has no DB instances — no compute to analyze. "
                "This usually means the cluster's last writer/reader instance "
                "was deleted. The Standard vs I/O-Optimized comparison does not "
                "apply until the cluster has a running instance."
            ),
        }

    # Get instance types in the cluster
    member_ids = [m["DBInstanceIdentifier"] for m in cluster.get("DBClusterMembers", [])]
    compute_monthly = 0.0
    instance_summary = []
    compute_warnings = []
    for mid in member_ids:
        try:
            inst_resp = rds.describe_db_instances(DBInstanceIdentifier=mid)
            for inst in inst_resp.get("DBInstances", []):
                itype = inst.get("DBInstanceClass", "")
                # Aurora Serverless v2 (db.serverless) has no fixed hourly rate — it bills
                # per-ACU-hour from a CloudWatch metric, not from INSTANCE_PRICES. Counting it
                # at $0 would silently understate compute and skew the I/O-cost percentage, so
                # exclude it and flag the estimate as partial rather than emit a wrong number.
                if itype == "db.serverless":
                    instance_summary.append(
                        {"id": mid, "type": itype, "note": "serverless_excluded"}
                    )
                    compute_warnings.append(
                        f"{mid} is Aurora Serverless v2 (db.serverless) — its ACU-based compute "
                        "cost is not included (it has no fixed hourly rate); the Standard vs "
                        "I/O-Optimized compute figures below cover provisioned instances only."
                    )
                    continue
                price = INSTANCE_PRICES.get(itype, 0.0)
                if price == 0.0:
                    # Unknown/unpriced provisioned type — don't silently add $0.
                    instance_summary.append({"id": mid, "type": itype, "note": "unknown_price"})
                    compute_warnings.append(
                        f"{mid} ({itype}) has no known hourly price in the static/live table — "
                        "excluded from the compute estimate; results are partial."
                    )
                    continue
                compute_monthly += price * HOURS_PER_MONTH
                instance_summary.append({"id": mid, "type": itype, "price_hr": price})
        except Exception as e:
            instance_summary.append({"id": mid, "error": str(e)})

    # CloudWatch window
    end = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=days)
    observed_hours = days * 24

    read_io = _sum_metric(cw, cluster_id, "VolumeReadIOPs", start, end)
    write_io = _sum_metric(cw, cluster_id, "VolumeWriteIOPs", start, end)
    total_io = read_io + write_io
    # Extrapolate to 730-hour month
    monthly_io = (total_io / observed_hours * HOURS_PER_MONTH) if observed_hours > 0 else 0
    monthly_io_millions = monthly_io / 1_000_000

    # Storage (average)
    avg_bytes = _avg_metric(cw, cluster_id, "VolumeBytesUsed", start, end)
    storage_gib = avg_bytes / (1024**3)  # Aurora bills actual usage; no fixed minimum

    comparison = compute_comparison(compute_monthly, storage_gib, monthly_io_millions)

    result = {
        "cluster_id": cluster_id,
        "engine": engine,
        "current_storage_type": current_storage_type,
        "instances": instance_summary,
        "lookback_days": days,
        "data_quality": data_quality_tag(days),
        "observed_io_total": int(total_io),
        **comparison,
    }
    if compute_warnings:
        result["compute_partial"] = True
        result["compute_warnings"] = compute_warnings
    return result


def list_clusters(region: str) -> list[str]:
    import boto3

    rds = boto3.client("rds", region_name=region)
    names = []
    for page in rds.get_paginator("describe_db_clusters").paginate():
        for c in page.get("DBClusters", []):
            if c.get("Engine", "").startswith("aurora"):
                names.append(c["DBClusterIdentifier"])
    return names


# ---------------------------------------------------------------------------
# Offline path (no AWS calls)
# ---------------------------------------------------------------------------


def analyze_offline(
    instance: str,
    num_instances: int,
    storage_gib: float,
    monthly_io_millions: float,
) -> dict:
    if instance not in INSTANCE_PRICES:
        return {
            "error": f"Unknown instance type: {instance}. "
            f"Supported: {', '.join(sorted(INSTANCE_PRICES))}"
        }
    compute_monthly = INSTANCE_PRICES[instance] * HOURS_PER_MONTH * num_instances
    comparison = compute_comparison(compute_monthly, storage_gib, monthly_io_millions)
    return {
        "cluster_id": "offline-input",
        "instance_type": instance,
        "num_instances": num_instances,
        "data_quality": "user_supplied",
        **comparison,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Aurora I/O-Optimized vs Standard cost analyzer")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument(
        "--days", type=int, default=14, help="CloudWatch lookback window (default 14)"
    )
    parser.add_argument("--format", choices=["json", "table"], default="json")

    # Modes are positional/optional
    parser.add_argument("--cluster", help="Analyze a single cluster by identifier")
    parser.add_argument(
        "--all", action="store_true", help="Analyze all Aurora clusters in the region"
    )

    sub = parser.add_subparsers(dest="mode")
    off = sub.add_parser("offline", help="Use user-supplied numbers, no AWS calls")
    off.add_argument("--instance", required=True)
    off.add_argument("--num-instances", type=int, default=1)
    off.add_argument("--storage-gib", type=float, required=True)
    off.add_argument("--monthly-io-millions", type=float, required=True)
    # --region / --format are already defined on the main parser. Re-declare them on
    # the offline subparser so they are ALSO accepted after the subcommand, but with
    # SUPPRESSed defaults so a copy doesn't clobber a value passed before 'offline';
    # the real default is resolved once, post-parse, below.
    off.add_argument("--region", default=argparse.SUPPRESS)
    off.add_argument("--format", choices=["json", "table"], default=argparse.SUPPRESS)

    args = parser.parse_args()
    if not hasattr(args, "region") or args.region is None:
        args.region = "us-east-1"
    if not hasattr(args, "format") or args.format is None:
        args.format = "json"

    # Offline mode
    if args.mode == "offline":
        # Still attempt to refresh pricing so regional factors can apply
        refresh_pricing(args.region)
        result = analyze_offline(
            args.instance, args.num_instances, args.storage_gib, args.monthly_io_millions
        )
        result["pricing_source"] = _pricing_source
        _emit(result, args.format)
        return

    # Live modes require boto3
    try:
        import boto3  # noqa: F401
    except ImportError:
        print(
            "ERROR: boto3 required for live AWS analysis. Install boto3 or use the 'offline' subcommand.",
            file=sys.stderr,
        )
        sys.exit(2)

    refresh_pricing(args.region)

    if args.all:
        cluster_ids = list_clusters(args.region)
        if not cluster_ids:
            print(json.dumps({"status": "ok", "region": args.region, "clusters": []}, indent=2))
            return
        results = [analyze_cluster_live(cid, args.region, args.days) for cid in cluster_ids]
        summary = _fleet_summary(results)
        output = {
            "region": args.region,
            "pricing_source": _pricing_source,
            "summary": summary,
            "clusters": results,
        }
        _emit(output, args.format, fleet=True)
        return

    if args.cluster:
        result = analyze_cluster_live(args.cluster, args.region, args.days)
        result["pricing_source"] = _pricing_source
        _emit(result, args.format)
        return

    parser.print_help()


def _fleet_summary(results: list[dict]) -> dict:
    # Exclude errored and skipped clusters (no-instance) from dollar totals
    analyzable = [r for r in results if "error" not in r and not r.get("skipped")]
    skipped = [r for r in results if r.get("skipped")]
    total_std = sum(r.get("standard", {}).get("total_monthly", 0) for r in analyzable)
    total_io_opt = sum(r.get("io_optimized", {}).get("total_monthly", 0) for r in analyzable)
    switch_wins = [r["cluster_id"] for r in analyzable if r.get("recommendation") == "io_optimized"]
    return {
        "cluster_count": len(results),
        "analyzable_count": len(analyzable),
        "skipped_count": len(skipped),
        "skipped_clusters": [
            {"cluster_id": r["cluster_id"], "reason": r.get("reason", "")} for r in skipped
        ],
        "clusters_that_should_switch": switch_wins,
        "current_monthly_total_standard": round(total_std, 2),
        "if_all_on_io_optimized_monthly": round(total_io_opt, 2),
        "optimal_savings_monthly": round(
            sum(max(0, r.get("savings_with_io_opt", 0)) for r in analyzable),
            2,
        ),
    }


def _emit(result: dict, fmt: str, fleet: bool = False) -> None:
    if fmt == "json":
        print(json.dumps(result, indent=2, default=str))
        return
    # Table format
    if fleet:
        s = result["summary"]
        print(
            f"Region: {result['region']}  Clusters: {s['cluster_count']} "
            f"(analyzable: {s['analyzable_count']}, skipped: {s['skipped_count']})"
        )
        print(f"  Current (Standard):      ${s['current_monthly_total_standard']:.0f}/mo")
        print(f"  All on I/O-Optimized:    ${s['if_all_on_io_optimized_monthly']:.0f}/mo")
        print(f"  Optimal (switch winners): saves ${s['optimal_savings_monthly']:.0f}/mo")
        print(f"  Clusters to switch: {', '.join(s['clusters_that_should_switch']) or '(none)'}")
        if s.get("skipped_clusters"):
            print(f"  Skipped (not applicable):")
            for sc in s["skipped_clusters"]:
                print(f"    - {sc['cluster_id']}: {sc['reason'][:80]}")
        print()
        print(f"{'Cluster':<30} {'I/O %':>6} {'Std $/mo':>10} {'IOOpt $/mo':>12} {'Rec':>14}")
        print("-" * 76)
        for r in result["clusters"]:
            if "error" in r:
                print(f"{r['cluster_id']:<30} ERROR: {r['error']}")
                continue
            if r.get("skipped"):
                print(
                    f"{r['cluster_id']:<30} {'—':>6} {'—':>10} {'—':>12} {'skipped (no instances)':>22}"
                )
                continue
            print(
                f"{r['cluster_id']:<30} {r['io_cost_pct_of_total']:>5.0f}% "
                f"{r['standard']['total_monthly']:>10.0f} "
                f"{r['io_optimized']['total_monthly']:>12.0f} "
                f"{r['recommendation']:>14}"
            )
        return
    # Single cluster
    r = result
    if r.get("skipped"):
        print(f"Cluster: {r.get('cluster_id', '?')}")
        print(f"  Engine: {r.get('engine', '?')} {r.get('engine_version', '')}")
        print(f"  Status: SKIPPED — not applicable")
        print(f"  {r.get('reason', '')}")
        return
    print(f"Cluster: {r.get('cluster_id', '?')}  ({r.get('data_quality', '?')} data)")
    print(f"  Current storage type: {r.get('current_storage_type', '?')}")
    print(f"  Monthly I/O: {r.get('monthly_io_millions', 0):.0f}M requests")
    print(f"  Storage: {r.get('storage_gib', 0):.0f} GiB")
    print()
    std = r["standard"]
    ioo = r["io_optimized"]
    print(f"  {'Component':<12} {'Standard':>12} {'I/O-Optimized':>15}")
    print(f"  {'Compute':<12} {std['compute_monthly']:>12.0f} {ioo['compute_monthly']:>15.0f}")
    print(f"  {'Storage':<12} {std['storage_monthly']:>12.0f} {ioo['storage_monthly']:>15.0f}")
    print(f"  {'I/O':<12} {std['io_monthly']:>12.0f} {ioo['io_monthly']:>15.0f}")
    print(f"  {'Total':<12} {std['total_monthly']:>12.0f} {ioo['total_monthly']:>15.0f}")
    print()
    print(f"  I/O cost: {r['io_cost_pct_of_total']:.0f}% of total")
    print(f"  Recommendation: {r['recommendation'].upper()}")
    print(f"  {r['reason']}")


if __name__ == "__main__":
    main()
