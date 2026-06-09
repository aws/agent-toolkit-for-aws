#!/usr/bin/env python3
"""
ElastiCache Serverless Cost Estimator

Provides approximate cost estimates for what ElastiCache provisioned
clusters would cost on ElastiCache Serverless, or for sizing a new
serverless cache. These are estimates only. Actual serverless costs
depend on real-time workload characteristics and may differ from the
values produced by this tool. For accurate billing data, use CloudWatch
ElastiCacheProcessingUnits and BytesUsedForCache metrics on a running
serverless cache.

Two estimation modes:
  Simple:   Provide avg memory + daily command count per cluster.
            Each command is estimated at MAX(1, avg_payload_kb) ECPUs.
            This is a quick approximation for initial cost comparison.

  Detailed: Also provide per-command stats (from INFO commandstats).
            Classifies commands as simple (1 ECPU) or complex
            (estimated as MAX(calls, usec/3) ECPUs based on the
            assumption that 1 ECPU corresponds to approximately
            3 microseconds of vCPU time, derived from the AWS pricing
            blog example). Takes the higher of the CPU and network
            components. More accurate than simple mode but still an
            approximation.

IMPORTANT: The ECPU formulas used in this tool are heuristic approximations
based on publicly available AWS documentation and pricing examples. AWS does
not publish exact ECPU calculation formulas. The 3-microsecond-per-ECPU
assumption for complex commands is derived from the AWS pricing blog and may
not apply uniformly to all command types. See command_classifier.py for
details on command classification.

Pricing is fetched live from the AWS Bulk Pricing API and reflects current
published rates. See https://aws.amazon.com/elasticache/pricing/

Note: INFO commandstats returns cumulative counts that keep incrementing
from server start. If you include an "uptime_days" column in the
commandstats CSV, the estimator divides calls and usec by that value to
normalize to a daily rate. The --endpoint mode handles this automatically
by taking two snapshots and computing the delta.

Usage:
    python3 serverless_estimator.py --input clusters.csv
    python3 serverless_estimator.py --input clusters.csv --commandstats stats.csv
    python3 serverless_estimator.py --endpoint my-cluster.abc123.use1.cache.amazonaws.com:6379
    python3 serverless_estimator.py --endpoint my-cluster.abc123.use1.cache.amazonaws.com --instance-type cache.r7g.large
    python3 serverless_estimator.py --input clusters.csv --pricing pricing.csv
    python3 serverless_estimator.py --input clusters.csv --output estimate.csv --json
"""
import argparse
import csv
import json
import math
import os
import re
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from command_classifier import estimate_ecpus_from_commandstats
from pricing import PricingLoader

HOURS_PER_MONTH = 730

MIN_STORAGE_GB = {
    "valkey": 0.1,      # 100 MB
    "redis": 1.0,       # 1 GB
    "memcached": 1.0,   # 1 GB
}

# Number of sample points for sinusoidal workload modeling.
# 24 = one sample per hour over a daily cycle.
_SIN_SAMPLES = 24


def _sine_wave_samples(min_val, max_val, n=_SIN_SAMPLES):
    """Generate n hourly samples of a sine wave oscillating between min and max.

    Models a daily traffic pattern:
      value(t) = min + (max - min) * (1 + sin(2*pi*t/n)) / 2

    Returns a list of n float values representing the workload at each hour.
    """
    amplitude = (max_val - min_val) / 2.0
    midpoint = (max_val + min_val) / 2.0
    return [midpoint + amplitude * math.sin(2 * math.pi * i / n) for i in range(n)]


def compute_burst_multiplier(avg_val, min_val=None, max_val=None, peak_to_avg=None):
    """Compute a cost multiplier for bursty (sinusoidal) workloads.

    Serverless bills per-hour. A workload that swings between min and peak
    follows a sine curve over the day. This function samples the curve at
    24 hourly points and returns the ratio of the sine-wave average to the
    customer-provided average.

    Why this matters: if the customer says "my average is X" but their actual
    traffic swings from min to peak, the true average of the sine curve
    ((min+max)/2) may differ from X. The multiplier corrects for that.

    The caller can specify the burst in two ways:
      1. min_val + max_val: explicit floor and ceiling of the daily cycle
      2. peak_to_avg: ratio of peak to average (e.g., 3.0 means peak is 3x avg)

    Returns 1.0 (no adjustment) if no burst parameters are provided or if
    the workload is flat.
    """
    if peak_to_avg is not None and peak_to_avg > 1.0:
        max_val = avg_val * peak_to_avg
        min_val = max(0, avg_val * (2 - peak_to_avg))

    if min_val is None or max_val is None:
        return 1.0
    if max_val <= min_val or max_val <= 0:
        return 1.0
    if avg_val <= 0:
        return 1.0

    samples = _sine_wave_samples(min_val, max_val)
    sine_avg = sum(samples) / len(samples)

    return sine_avg / avg_val


def load_clusters(path: str) -> List[Dict]:
    """Load cluster data from CSV.

    Required columns:
        cluster_name, instance_type, region, engine, node_count,
        avg_memory_gb, daily_commands

    Optional columns:
        primary_nodes         -- defaults to max(1, node_count // 2). This is a
                                 rough heuristic; for CMD clusters (1 primary +
                                 N replicas) or CME clusters (1 primary per shard),
                                 provide the actual value via --primary-nodes or
                                 the primary_nodes CSV column for accurate results.
        current_monthly_cost  -- if known; otherwise computed from list price
        avg_payload_kb        -- average payload size in KB (default 1.0).
                                 ECPUs scale linearly with payload: 3.2 KB = 3.2 ECPUs per op.
        peak_commands         -- peak daily commands (for bursty workload modeling)
        min_commands          -- minimum daily commands (for bursty workload modeling)
        peak_to_avg_ratio     -- ratio of peak to average commands (alternative to min/max)
        peak_memory_gb        -- peak memory in GB (for bursty storage modeling)
        min_memory_gb         -- minimum memory in GB (for bursty storage modeling)
    """
    clusters = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            node_count = int(row.get("node_count", 1))
            primary_nodes = int(row.get("primary_nodes", 0))
            if primary_nodes == 0:
                # Heuristic: assumes half the nodes are primaries. This is only
                # accurate for 1-replica setups; actual primary count depends on
                # cluster topology (CMD: 1 primary + N replicas, CME: 1 primary
                # per shard). Provide the primary_nodes column for accuracy.
                primary_nodes = max(1, node_count // 2)

            clusters.append({
                "cluster_name": row["cluster_name"].strip(),
                "instance_type": row.get("instance_type", "").strip(),
                "region": row.get("region", "us-east-1").strip(),
                "engine": row.get("engine", "valkey").strip().lower(),
                "node_count": node_count,
                "primary_nodes": primary_nodes,
                "avg_memory_gb": float(row.get("avg_memory_gb", 0)),
                "daily_commands": float(row.get("daily_commands", 0)),
                "current_monthly_cost": float(row.get("current_monthly_cost", 0) or 0),
                "avg_payload_kb": float(row.get("avg_payload_kb", 1.0) or 1.0),
                "peak_commands": float(row.get("peak_commands", 0) or 0),
                "min_commands": float(row.get("min_commands", 0) or 0),
                "peak_to_avg_ratio": float(row.get("peak_to_avg_ratio", 0) or 0),
                "peak_memory_gb": float(row.get("peak_memory_gb", 0) or 0),
                "min_memory_gb": float(row.get("min_memory_gb", 0) or 0),
            })
    return clusters


def parse_commandstats_file(path: str) -> Dict[str, dict]:
    """Parse a commandstats CSV.

    Expected columns: cluster_name, command, calls, usec

    Optional columns:
        uptime_days  - days since server restart. When present, calls and
                       usec are divided by this value to normalize cumulative
                       INFO commandstats output to a daily rate. Without it
                       the raw cumulative values are used as-is.

    Returns a dict keyed by cluster_name. Each value is a dict of
    {command: {"calls": int, "usec": int}}. A special key
    "_normalized" (bool) indicates whether uptime_days normalization
    was applied for that cluster.
    """
    result = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            cluster = row["cluster_name"].strip()
            cmd = row["command"].strip().lower()
            calls = int(row.get("calls", 0))
            usec = int(row.get("usec", 0))

            uptime_raw = row.get("uptime_days", "").strip()
            uptime_days = float(uptime_raw) if uptime_raw else None

            if uptime_days and uptime_days > 0:
                calls = int(calls / uptime_days)
                usec = int(usec / uptime_days)
                normalized = True
            else:
                normalized = False

            if cluster not in result:
                result[cluster] = {"_normalized": normalized}  # type: ignore[dict-item]
            result[cluster][cmd] = {"calls": calls, "usec": usec}  # type: ignore[assignment]
            # If any row for this cluster has uptime_days, mark as normalized
            if normalized:
                result[cluster]["_normalized"] = True
    return result


def parse_commandstats_info(text: str) -> dict:
    """Parse raw INFO commandstats output from valkey-cli (or redis-cli).

    Example line: cmdstat_get:calls=1000,usec=1500,usec_per_call=1.50,rejected_calls=0,failed_calls=0
    """
    result = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"cmdstat_(\w+):calls=(\d+),usec=(\d+)", line)
        if match:
            cmd = match.group(1).lower()
            result[cmd] = {
                "calls": int(match.group(2)),
                "usec": int(match.group(3)),
            }
    return result


def estimate_cluster(
    cluster: Dict,
    pricing: PricingLoader,
    commandstats: Optional[dict] = None,
) -> Dict:
    """Estimate serverless cost for one cluster."""
    region = cluster["region"]
    engine = cluster["engine"]
    node_count = cluster["node_count"]
    instance_type = cluster["instance_type"]

    # --- Current provisioned cost ---
    if cluster["current_monthly_cost"] > 0:
        current_cost = cluster["current_monthly_cost"]
        cost_source = "provided"
    elif instance_type:
        try:
            hourly = pricing.get_node_hourly_rate(region, instance_type, engine)
            current_cost = hourly * HOURS_PER_MONTH * node_count
            cost_source = "list_price"
        except ValueError:
            current_cost = 0
            cost_source = "unknown"
    else:
        current_cost = 0
        cost_source = "unknown"

    # --- Serverless storage ---
    avg_memory_gb = cluster["avg_memory_gb"]
    min_gb = MIN_STORAGE_GB.get(engine, 1.0)
    billing_memory_gb = max(avg_memory_gb, min_gb)
    used_minimum = avg_memory_gb < min_gb

    # Bursty storage: if peak/min memory provided, adjust
    storage_burst = compute_burst_multiplier(
        avg_memory_gb,
        min_val=cluster.get("min_memory_gb") or None,
        max_val=cluster.get("peak_memory_gb") or None,
    )
    adjusted_memory_gb = billing_memory_gb * storage_burst

    monthly_gb_hours = adjusted_memory_gb * HOURS_PER_MONTH
    storage_rate = pricing.get_serverless_storage_rate(region, engine)
    storage_cost = monthly_gb_hours * storage_rate

    # --- Serverless ECPUs ---
    ecpu_rate = pricing.get_serverless_ecpu_rate(region, engine)

    # Bursty commands: if peak/min commands or peak_to_avg_ratio provided, adjust
    ecpu_burst = compute_burst_multiplier(
        cluster["daily_commands"],
        min_val=cluster.get("min_commands") or None,
        max_val=cluster.get("peak_commands") or None,
        peak_to_avg=cluster.get("peak_to_avg_ratio") or None,
    )

    if commandstats and engine == "memcached":
        print("WARNING: commandstats mode uses Redis/Valkey INFO format, which is "
              "incompatible with Memcached. ECPU estimates for Memcached cluster '{}' "
              "will be inaccurate. Falling back to simple estimation.".format(
                  cluster["cluster_name"]),
              file=sys.stderr)
        commandstats = None

    if commandstats:
        # _normalized is a metadata flag, not a command; exclude before estimation
        cs_normalized = commandstats.get("_normalized", False)
        cs_data = {k: v for k, v in commandstats.items() if k != "_normalized"}
        ecpu_result = estimate_ecpus_from_commandstats(cs_data)
        daily_cpu_ecpus = ecpu_result["total_ecpus"]
        # Network component: each command costs MAX(1, avg_payload_kb) ECPUs.
        # This approximates the "1 ECPU per KB transferred" pricing rule.
        # See: https://aws.amazon.com/elasticache/pricing/
        avg_payload_kb = cluster.get("avg_payload_kb", 1.0) or 1.0
        ecpu_per_request = max(1.0, avg_payload_kb)
        daily_net_ecpus = cluster["daily_commands"] * ecpu_per_request
        # Serverless charges the higher of vCPU time or data transferred.
        # See: https://aws.amazon.com/blogs/database/unlock-on-demand-cost-optimized-performance-with-amazon-elasticache-serverless/
        daily_ecpus = max(daily_cpu_ecpus, daily_net_ecpus)
        monthly_ecpus = daily_ecpus * 30 * ecpu_burst
        ecpu_mode = "detailed"
        fixed_ecpus = ecpu_result["fixed_ecpus"] * 30
        nonfixed_ecpus = ecpu_result["nonfixed_ecpus"] * 30
        internal_calls = ecpu_result["internal_calls"] * 30
    else:
        avg_payload_kb = cluster.get("avg_payload_kb", 1.0) or 1.0
        ecpu_per_request = max(1.0, avg_payload_kb)
        monthly_ecpus = cluster["daily_commands"] * 30 * ecpu_per_request * ecpu_burst
        ecpu_mode = "simple"
        fixed_ecpus = None
        nonfixed_ecpus = None
        internal_calls = None

    ecpu_cost = monthly_ecpus * ecpu_rate
    total_serverless = storage_cost + ecpu_cost

    # --- Comparison ---
    diff = total_serverless - current_cost if current_cost > 0 else None
    diff_pct = (diff / current_cost * 100) if diff is not None and current_cost > 0 else None

    # --- Notes ---
    notes = []
    if used_minimum:
        notes.append("Min storage applied ({} GB)".format(min_gb))
    if cost_source == "list_price":
        notes.append("Current cost: on-demand list price")
    if cost_source == "unknown":
        notes.append("Current cost unknown - provide current_monthly_cost or instance_type")
    if ecpu_mode == "simple":
        if avg_payload_kb > 1:
            notes.append("ECPU: {} ECPUs per request ({} KB avg payload)".format(
                round(ecpu_per_request, 1), round(avg_payload_kb, 1)))
        else:
            notes.append("ECPU: 1 cmd = 1 ECPU (provide avg_payload_kb for better accuracy)")
    if commandstats and not cs_normalized:
        notes.append("Commandstats not normalized by uptime; provide uptime_days column for accuracy")
    if ecpu_burst > 1.0:
        notes.append("Burst adjustment applied: {:.2f}x (peak/avg commands)".format(ecpu_burst))
    if storage_burst > 1.0:
        notes.append("Burst adjustment applied: {:.2f}x (peak/avg memory)".format(storage_burst))

    # Serverless compatibility warnings
    if engine in ("redis", "valkey"):
        notes.append("Serverless requires cluster-mode-enabled clients and TLS; Global Data Store and Data Tiering are not supported")

    return {
        "cluster_name": cluster["cluster_name"],
        "region": region,
        "engine": engine,
        "instance_type": instance_type,
        "node_count": node_count,
        "primary_nodes": cluster["primary_nodes"],
        "current_monthly_cost": round(current_cost, 2),
        "cost_source": cost_source,
        "avg_memory_gb": round(avg_memory_gb, 4),
        "billing_memory_gb": round(billing_memory_gb, 4),
        "monthly_gb_hours": round(monthly_gb_hours, 2),
        "storage_rate_per_gb_hour": storage_rate,
        "storage_cost": round(storage_cost, 2),
        "monthly_ecpus": round(monthly_ecpus),
        "ecpu_rate_per_million": round(ecpu_rate * 1_000_000, 4),
        "ecpu_cost": round(ecpu_cost, 2),
        "ecpu_mode": ecpu_mode,
        "fixed_ecpus": round(fixed_ecpus) if fixed_ecpus is not None else None,
        "nonfixed_ecpus": round(nonfixed_ecpus) if nonfixed_ecpus is not None else None,
        "internal_calls_excluded": round(internal_calls) if internal_calls is not None else None,
        "serverless_total": round(total_serverless, 2),
        "diff": round(diff, 2) if diff is not None else None,
        "diff_pct": round(diff_pct, 1) if diff_pct is not None else None,
        "notes": "; ".join(notes),
    }


def write_csv(results: List[Dict], path: str):
    """Write results to CSV."""
    if not results:
        return
    fields = [
        "cluster_name", "region", "engine", "instance_type",
        "node_count", "primary_nodes",
        "current_monthly_cost", "cost_source",
        "avg_memory_gb", "billing_memory_gb",
        "monthly_gb_hours", "storage_cost",
        "monthly_ecpus", "ecpu_cost", "ecpu_mode",
        "serverless_total", "diff", "diff_pct", "notes",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print("Output written to: {}".format(path))


def print_summary(results: List[Dict]):
    """Print summary to console."""
    total_current = sum(r["current_monthly_cost"] for r in results)
    total_sl = sum(r["serverless_total"] for r in results)
    total_stor = sum(r["storage_cost"] for r in results)
    total_ecpu = sum(r["ecpu_cost"] for r in results)
    cheaper = sum(1 for r in results if r["diff"] is not None and r["diff"] < 0)
    more_exp = sum(1 for r in results if r["diff"] is not None and r["diff"] > 0)

    print()
    print("=" * 65)
    print("  ElastiCache Serverless Cost Estimate")
    print("=" * 65)
    print("  Clusters analyzed:        {}".format(len(results)))
    print("  Total nodes:              {}".format(sum(r["node_count"] for r in results)))
    print()
    print("  Current provisioned cost: ${:>12,.2f} /month".format(total_current))
    print("  Estimated serverless:     ${:>12,.2f} /month".format(total_sl))
    print("    Data storage:           ${:>12,.2f}".format(total_stor))
    print("    ECPUs:                  ${:>12,.2f}".format(total_ecpu))
    print()
    if total_current > 0:
        savings = total_current - total_sl
        pct = savings / total_current * 100
        print("  Estimated savings:        ${:>12,.2f} ({:.1f}%)".format(savings, pct))
    print("  Clusters cheaper on SL:   {}".format(cheaper))
    print("  Clusters more expensive:  {}".format(more_exp))
    print("=" * 65)
    print()
    print("  {:<30s} {:>10s} {:>10s} {:>8s}".format(
        "Cluster", "Current", "Serverless", "Change"))
    print("  {} {} {} {}".format("-" * 30, "-" * 10, "-" * 10, "-" * 8))
    for r in sorted(results, key=lambda x: x.get("diff") or 0):
        name = r["cluster_name"][:30]
        cur = "${:,.0f}".format(r["current_monthly_cost"])
        sl = "${:,.0f}".format(r["serverless_total"])
        chg = "{:+.0f}%".format(r["diff_pct"]) if r["diff_pct"] is not None else "N/A"
        print("  {:<30s} {:>10s} {:>10s} {:>8s}".format(name, cur, sl, chg))
    print()
    print("  ECPU estimates assume 1 KB avg payload unless avg_payload_kb is provided.")
    print("  ECPUs scale linearly with payload size (e.g. 3 KB = 3x ECPUs).")
    print()
    print("  IMPORTANT: These are approximate estimates. Actual serverless costs depend")
    print("  on real-time workload characteristics and may differ. For accurate billing,")
    print("  use CloudWatch metrics on a running serverless cache.")
    print("  See https://aws.amazon.com/elasticache/pricing/")
    print()


def collect_from_endpoint(endpoint, cluster_name=None, instance_type="",
                          region="us-east-1", engine="valkey", node_count=2,
                          avg_payload_kb=1.0, use_tls=True, sample_seconds=60):
    """Connect to a live Valkey/Redis endpoint and collect metrics.

    Takes two INFO snapshots separated by sample_seconds and computes
    deltas. This gives the actual traffic rate during the sample window,
    which is more accurate than dividing cumulative totals by uptime.

    Returns (cluster_dict, commandstats_dict) ready for estimate_cluster().
    """
    try:
        import valkey as client_lib
    except ImportError:
        print("Error: the 'valkey' package is required for --endpoint mode.")
        print("Install with: pip install valkey")
        sys.exit(1)

    import time

    # Parse host:port
    if ":" in endpoint and not endpoint.startswith("["):
        host, port_str = endpoint.rsplit(":", 1)
        port = int(port_str)
    else:
        host = endpoint
        port = 6379

    if not cluster_name:
        cluster_name = host.split(".")[0]

    print("Connecting to {}:{}{}...".format(host, port, " (TLS)" if use_tls else ""))
    r = client_lib.Redis(host=host, port=port, ssl=use_tls,
                        ssl_cert_reqs=None, decode_responses=True,
                        socket_connect_timeout=10)
    print("  PING: {}".format(r.ping()))

    # Collect memory and replication (point-in-time, no delta needed)
    mem_info = r.info("memory")
    repl_info = r.info("replication")
    dataset_bytes = mem_info.get("used_memory_dataset", mem_info.get("used_memory", 0))
    dataset_gb = dataset_bytes / (1024 ** 3)
    role = repl_info.get("role", "unknown")

    print("  Role:   {}".format(role))
    print("  Memory: {:.4f} GB ({:,.0f} bytes)".format(dataset_gb, dataset_bytes))

    # Snapshot 1
    print("  Taking snapshot 1...")
    cs1 = r.info("commandstats")
    stats1 = r.info("stats")
    t1 = time.time()

    # Wait
    print("  Sampling for {} seconds...".format(sample_seconds))
    time.sleep(sample_seconds)

    # Snapshot 2
    print("  Taking snapshot 2...")
    cs2 = r.info("commandstats")
    stats2 = r.info("stats")
    t2 = time.time()

    elapsed = t2 - t1
    elapsed_days = elapsed / 86400

    # Compute commandstats deltas
    commandstats = {}
    total_delta_calls = 0
    for key in cs2:
        cmd = key.replace("cmdstat_", "")
        calls_delta = cs2[key].get("calls", 0) - cs1.get(key, {}).get("calls", 0)
        usec_delta = cs2[key].get("usec", 0) - cs1.get(key, {}).get("usec", 0)
        if calls_delta > 0:
            # Scale to daily rate
            daily_calls = int(calls_delta / elapsed_days)
            daily_usec = int(usec_delta / elapsed_days)
            commandstats[cmd] = {"calls": daily_calls, "usec": daily_usec}
            total_delta_calls += calls_delta

    commandstats["_normalized"] = True  # type: ignore[assignment]
    daily_commands = total_delta_calls / elapsed_days if elapsed_days > 0 else 0

    # Also get total commands delta for simple mode
    total_cmds_delta = stats2.get("total_commands_processed", 0) - stats1.get("total_commands_processed", 0)
    daily_commands_total = total_cmds_delta / elapsed_days if elapsed_days > 0 else 0

    print("  Sample window:  {:.0f} seconds".format(elapsed))
    print("  Commands in window: {:,}".format(total_cmds_delta))
    print("  Daily rate:     {:,.0f} commands/day".format(daily_commands_total))

    top_cmds = sorted(commandstats.items(),
                      key=lambda x: x[1].get("calls", 0) if isinstance(x[1], dict) else 0,
                      reverse=True)[:5]
    print("  Top commands:   {}".format(
        ", ".join("{} ({:,}/day)".format(k, v["calls"])
                  for k, v in top_cmds if isinstance(v, dict))))

    cluster = {
        "cluster_name": cluster_name,
        "instance_type": instance_type,
        "region": region,
        "engine": engine.lower(),
        "node_count": node_count,
        "primary_nodes": max(1, node_count // 2),
        "avg_memory_gb": dataset_gb,
        "daily_commands": daily_commands_total,
        "current_monthly_cost": 0,
        "avg_payload_kb": avg_payload_kb,
        "peak_commands": 0,
        "min_commands": 0,
        "peak_to_avg_ratio": 0,
        "peak_memory_gb": 0,
        "min_memory_gb": 0,
    }

    return cluster, commandstats


def main():
    parser = argparse.ArgumentParser(
        description="Estimate ElastiCache Serverless costs from provisioned cluster metrics"
    )
    parser.add_argument("--input", "-i",
                        help="CSV with cluster data (see README for format)")
    parser.add_argument("--endpoint", "-e",
                        help="Connect directly to a Valkey/Redis endpoint (host:port or host)")
    parser.add_argument("--cluster-name", default=None,
                        help="Cluster name (used with --endpoint, default: derived from host)")
    parser.add_argument("--instance-type", default="",
                        help="Instance type (used with --endpoint, e.g., cache.r7g.large)")
    parser.add_argument("--region", default="us-east-1",
                        help="AWS region (used with --endpoint, default: us-east-1)")
    parser.add_argument("--engine", default="valkey",
                        help="Engine (used with --endpoint, default: valkey)")
    parser.add_argument("--node-count", type=int, default=2,
                        help="Node count (used with --endpoint, default: 2)")
    parser.add_argument("--avg-payload-kb", type=float, default=1.0,
                        help="Average payload size in KB (default: 1.0)")
    parser.add_argument("--no-tls", action="store_true",
                        help="Disable TLS when connecting via --endpoint")
    parser.add_argument("--sample-seconds", type=int, default=60,
                        help="Seconds to sample when using --endpoint (default: 60). "
                             "Takes two snapshots this far apart and computes deltas.")
    parser.add_argument("--commandstats", "-c",
                        help="CSV with per-command stats for detailed ECPU estimation")
    parser.add_argument("--pricing", "-p",
                        help="Pricing CSV (optional - fetches live from AWS if omitted)")
    parser.add_argument("--output", "-o", default="serverless_estimate.csv",
                        help="Output CSV path (default: serverless_estimate.csv)")
    parser.add_argument("--json", action="store_true",
                        help="Also write JSON output")
    args = parser.parse_args()

    if not args.input and not args.endpoint:
        parser.error("Either --input (CSV) or --endpoint (host:port) is required")

    pricing = PricingLoader(args.pricing)

    if args.endpoint:
        # Direct endpoint mode: connect, collect, normalize, estimate
        cluster, commandstats = collect_from_endpoint(
            args.endpoint,
            cluster_name=args.cluster_name,
            instance_type=args.instance_type,
            region=args.region,
            engine=args.engine,
            node_count=args.node_count,
            avg_payload_kb=args.avg_payload_kb,
            use_tls=not args.no_tls,
            sample_seconds=args.sample_seconds,
        )
        results = [estimate_cluster(cluster, pricing, commandstats)]
    else:
        print("Loading clusters from: {}".format(args.input))
        clusters = load_clusters(args.input)
        print("  {} clusters loaded".format(len(clusters)))

        all_commandstats = None
        if args.commandstats:
            print("Loading commandstats from: {}".format(args.commandstats))
            all_commandstats = parse_commandstats_file(args.commandstats)
            print("  Stats for {} clusters".format(len(all_commandstats)))

        results = []
        for cluster in clusters:
            cs = all_commandstats.get(cluster["cluster_name"]) if all_commandstats else None
            results.append(estimate_cluster(cluster, pricing, cs))

    write_csv(results, args.output)
    print_summary(results)

    if args.json:
        base, _ = os.path.splitext(args.output)
        json_path = base + ".json"
        with open(json_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print("JSON written to: {}".format(json_path))


if __name__ == "__main__":
    main()
