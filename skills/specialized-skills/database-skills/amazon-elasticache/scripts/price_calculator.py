#!/usr/bin/env python3
"""
ElastiCache Price Calculator

Fetches live pricing from AWS and estimates costs for specific configurations.

Supports:
- Serverless (Valkey, Redis OSS, Memcached)
- Node-based on-demand and reserved instances
- Multi-node clusters with replicas
- Extended Support surcharge for EOL Redis versions

Usage:
  # Serverless estimate
  python3 price_calculator.py --engine valkey --mode serverless --data-gb 5 --ecpu-millions 200

  # Node-based with replicas
  python3 price_calculator.py --engine valkey --mode node --node-type cache.r7g.large --nodes 3

  # Node-based with specific RI term
  python3 price_calculator.py --mode node --node-type cache.r7g.large --nodes 2 --ri-term 1yr_no_upfront

  # Show all reserved options for a node type
  python3 price_calculator.py --mode node --node-type cache.r7g.large --nodes 2 --show-ri-options

  # Specific region
  python3 price_calculator.py --engine valkey --region eu-west-1 --mode serverless --data-gb 10

  # Extended Support surcharge for EOL Redis versions
  python3 price_calculator.py --engine redis --extended-support --node-type cache.r7g.large --nodes 6

  # Interactive mode
  python3 price_calculator.py --interactive
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pricing import PricingLoader

# Detect region from environment with us-east-1 as fallback
REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"

HOURS_PER_MONTH = 730

PRICING_DISCLAIMER = (
    "  Estimates only. Verify current pricing at https://aws.amazon.com/elasticache/pricing/"
)


def estimate_serverless(loader, engine, region, data_gb, ecpu_millions_per_month, avg_payload_kb=1.0):
    storage_rate = loader.get_serverless_storage_rate(region, engine)
    ecpu_rate = loader.get_serverless_ecpu_rate(region, engine)
    min_gb = 0.1 if engine == "valkey" else 1.0
    billing_gb = max(data_gb, min_gb)
    storage = billing_gb * storage_rate * HOURS_PER_MONTH
    scaled_ecpus = ecpu_millions_per_month * max(1.0, avg_payload_kb)
    compute = scaled_ecpus * 1_000_000 * ecpu_rate
    result = {
        "model": "serverless",
        "engine": engine,
        "region": region,
        "data_gb": data_gb,
        "ecpu_millions": ecpu_millions_per_month,
        "storage_monthly": round(storage, 2),
        "compute_monthly": round(compute, 2),
        "total_monthly": round(storage + compute, 2),
    }
    if avg_payload_kb != 1.0:
        result["avg_payload_kb"] = avg_payload_kb
        result["ecpu_millions_scaled"] = round(scaled_ecpus, 1)
    return result


def estimate_node_based(loader, engine, region, node_type, node_count, ri_term=None):
    try:
        hourly = loader.get_node_hourly_rate(region, node_type, engine)
    except ValueError as e:
        return {"error": str(e)}

    monthly_per_node = hourly * HOURS_PER_MONTH
    total = monthly_per_node * node_count
    mem = loader.get_node_memory_gb(node_type)

    result = {
        "model": "node-based (on-demand)",
        "engine": engine,
        "region": region,
        "node_type": node_type,
        "node_count": node_count,
        "memory_per_node_gb": mem if mem > 0 else "unknown",
        "total_memory_gb": round(mem * node_count, 1) if mem > 0 else "unknown",
        "per_node_monthly": round(monthly_per_node, 2),
        "total_monthly": round(total, 2),
    }

    # Try real reserved pricing first, fall back to hardcoded discount
    if ri_term:
        ri_map = {
            "1yr_no_upfront": ("1yr", "No Upfront"),
            "1yr_partial_upfront": ("1yr", "Partial Upfront"),
            "1yr_all_upfront": ("1yr", "All Upfront"),
            "3yr_no_upfront": ("3yr", "No Upfront"),
            "3yr_partial_upfront": ("3yr", "Partial Upfront"),
            "3yr_all_upfront": ("3yr", "All Upfront"),
        }
        if ri_term in ri_map:
            lease, purchase = ri_map[ri_term]
            try:
                eff_monthly = loader.get_reserved_effective_monthly(
                    region, node_type, engine, lease, purchase
                )
                ri_total = eff_monthly * node_count
                discount_pct = round((1 - ri_total / total) * 100)
                result["reserved"] = {
                    "term": ri_term,
                    "discount_pct": discount_pct,
                    "per_node_monthly": eff_monthly,
                    "total_monthly": round(ri_total, 2),
                    "annual_savings": round((total - ri_total) * 12, 2),
                    "source": "live",
                }
            except ValueError:
                pass  # no reserved pricing available for this combo

    return result


def format_ri_options(loader, engine, region, node_type, node_count):
    """Show all reserved pricing options for a specific node configuration."""
    options = loader.list_reserved_options(region, node_type, engine)
    hourly = loader.get_node_hourly_rate(region, node_type, engine)
    od_monthly = hourly * HOURS_PER_MONTH * node_count

    lines = []
    lines.append("=" * 68)
    lines.append("Reserved Pricing Options (live pricing)")
    lines.append("=" * 68)
    lines.append("")
    lines.append("  Node type: {}  x {}  ({} engine)".format(node_type, node_count, engine))
    lines.append("  On-demand: ${:,.2f}/month".format(od_monthly))
    lines.append("")

    if not options:
        lines.append("  No reserved pricing options found for this configuration.")
        lines.append("")
        lines.append(PRICING_DISCLAIMER)
        lines.append("")
        return "\n".join(lines)

    lines.append("  {:<10} {:<18} {:>12} {:>10} {:>10}".format(
        "Term", "Purchase Option", "Monthly", "Upfront", "Savings"))
    lines.append("  {} {} {} {} {}".format("-" * 10, "-" * 18, "-" * 12, "-" * 10, "-" * 10))

    for opt in options:
        eff_total = opt["effective_monthly"] * node_count
        savings_pct = round((1 - eff_total / od_monthly) * 100)
        upfront_total = opt["upfront"] * node_count
        lines.append("  {:<10} {:<18} ${:>9,.2f} ${:>8,.0f} {:>8}%".format(
            opt["lease_length"], opt["purchase_option"],
            eff_total, upfront_total, savings_pct))

    lines.append("")
    lines.append(PRICING_DISCLAIMER)
    lines.append("")
    return "\n".join(lines)


def estimate_extended_support(loader, engine, region, node_type, node_count):
    """Estimate Extended Support surcharge for EOL Redis versions."""
    results = {"engine": engine, "region": region, "node_type": node_type, "node_count": node_count, "years": []}

    if not loader.has_extended_support_pricing():
        results["note"] = "Extended Support pricing not available in bulk pricing API. Check the ElastiCache pricing page."
        return results

    for year in ["1", "2", "3"]:
        try:
            hourly = loader.get_extended_support_rate(region, node_type, engine, year)
            monthly = hourly * HOURS_PER_MONTH * node_count
            results["years"].append({
                "year": int(year),
                "per_node_hourly": hourly,
                "total_monthly": round(monthly, 2),
                "total_annual": round(monthly * 12, 2),
            })
        except ValueError:
            pass

    if results["years"]:
        try:
            base_hourly = loader.get_node_hourly_rate(region, node_type, engine)
            base_monthly = base_hourly * HOURS_PER_MONTH * node_count
            results["base_monthly"] = round(base_monthly, 2)
            total_yr1 = base_monthly + results["years"][0]["total_monthly"]
            results["total_with_surcharge_monthly"] = round(total_yr1, 2)
        except ValueError:
            pass
        results["recommendation"] = (
            "Migrating to Valkey eliminates Extended Support charges. "
            "Savings vs other engines: 20% lower on node-based, 33% lower on serverless."
        )

    return results


def format_extended_support_report(results):
    """Generate a human-readable Extended Support cost report."""
    lines = []
    lines.append("=" * 60)
    lines.append("Extended Support Cost Estimate (live pricing)")
    lines.append("=" * 60)
    lines.append("")
    lines.append("  Engine: {}".format(results["engine"]))
    lines.append("  Region: {}".format(results["region"]))
    lines.append("  Node type: {}".format(results.get("node_type", "unknown")))
    lines.append("  Nodes:  {}".format(results["node_count"]))
    lines.append("")

    if not results["years"]:
        lines.append("  {}".format(results.get("note", "No pricing data available.")))
        lines.append("")
        return "\n".join(lines)

    lines.append("  {:<18} {:>16} {:>16}".format("Year After EOL", "Monthly Cost", "Annual Cost"))
    lines.append("  {} {} {}".format("-" * 18, "-" * 16, "-" * 16))

    for y in results["years"]:
        lines.append("  Year {:<13} ${:>13,.2f} ${:>13,.2f}".format(
            y["year"], y["total_monthly"], y["total_annual"]
        ))

    if results.get("base_monthly"):
        lines.append("")
        lines.append("  Base node cost:       ${:>13,.2f}/month".format(results["base_monthly"]))
        lines.append("  Total (base + Yr1):   ${:>13,.2f}/month".format(results["total_with_surcharge_monthly"]))

    lines.append("")
    if "recommendation" in results:
        lines.append("  {}".format(results["recommendation"]))
    lines.append("")
    lines.append(PRICING_DISCLAIMER)
    lines.append("")
    return "\n".join(lines)


def estimate_ecpu_from_ops(ops_per_sec, avg_ecpu_per_op=1.0):
    """Convert operations per second to monthly ECPUs (millions).

    Default: 1 ECPU per operation (assumes simple GET/SET with payload under 1 KB).
    For larger payloads, use --avg-payload-kb which scales ECPUs linearly.
    For complex commands (SORT, ZADD, etc.), pass a higher avg_ecpu_per_op.
    """
    ecpu_per_month = ops_per_sec * avg_ecpu_per_op * 3600 * HOURS_PER_MONTH
    return round(ecpu_per_month / 1_000_000, 1)


def interactive(loader, region):
    """Interactive interview-style cost estimation."""
    print("=== ElastiCache Price Calculator (live pricing) ===\n")

    engine = input("Engine [valkey/redis/memcached] (default: valkey): ").strip().lower() or "valkey"
    data_gb = float(input("Estimated data size in GB (default: 1): ").strip() or "1")
    mode = input("Deployment [serverless/node] (default: serverless): ").strip().lower() or "serverless"

    if mode == "serverless":
        ops = input("Estimated operations per second (default: 100): ").strip() or "100"
        ops_per_sec = float(ops)
        ecpu_millions = estimate_ecpu_from_ops(ops_per_sec)
        print("  -> Estimated {}M ECPUs/month".format(ecpu_millions))
        result = estimate_serverless(loader, engine, region, data_gb, ecpu_millions)
        print("\n{}".format(json.dumps(result, indent=2)))

    elif mode == "node":
        node_type = input("Node type (default: cache.r7g.large): ").strip() or "cache.r7g.large"
        nodes = int(input("Number of nodes (default: 2): ").strip() or "2")
        result = estimate_node_based(loader, engine, region, node_type, nodes, ri_term="1yr_no_upfront")
        print("\n{}".format(json.dumps(result, indent=2)))
        show_ri = input("\nShow all reserved options? [y/n] (default: n): ").strip().lower()
        if show_ri == "y":
            print("\n{}".format(format_ri_options(loader, engine, region, node_type, nodes)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ElastiCache Price Calculator (live pricing)")
    parser.add_argument("--interactive", action="store_true", help="Interactive mode")
    parser.add_argument("--engine", choices=["valkey", "redis", "memcached"], default="valkey")
    parser.add_argument("--mode", choices=["serverless", "node"], default="serverless")
    parser.add_argument("--region", default=REGION, help="AWS region (default: from env or us-east-1)")
    parser.add_argument("--data-gb", type=float, default=1.0, help="Data stored in GB")
    parser.add_argument("--ecpu-millions", type=float, default=None, help="ECPUs per month (millions)")
    parser.add_argument("--ops-per-sec", type=float, default=None, help="Operations per second (auto-converts to ECPUs)")
    parser.add_argument("--node-type", default="cache.r7g.large", help="Node type for node-based")
    parser.add_argument("--nodes", type=int, default=2, help="Node count for node-based")
    parser.add_argument("--ri-term", default=None,
                        choices=["1yr_no_upfront", "1yr_partial_upfront", "1yr_all_upfront",
                                 "3yr_no_upfront", "3yr_partial_upfront", "3yr_all_upfront"],
                        help="Reserved instance term")
    parser.add_argument("--show-ri-options", action="store_true",
                        help="Show all reserved pricing options for the node type")
    parser.add_argument("--extended-support", action="store_true",
                        help="Show Extended Support surcharge for EOL Redis versions")
    parser.add_argument("--avg-payload-kb", type=float, default=1.0,
                        help="Average payload size in KB (default: 1.0). ECPUs scale linearly with payload.")
    parser.add_argument("--pricing-csv", default=None, help="Optional local pricing CSV (overrides live fetch)")
    args = parser.parse_args()

    loader = PricingLoader(args.pricing_csv)

    if args.interactive:
        interactive(loader, args.region)
        sys.exit(0)

    # Auto-convert ops/sec to ECPUs if provided
    ecpu_millions = args.ecpu_millions
    if ecpu_millions is None and args.ops_per_sec:
        ecpu_millions = estimate_ecpu_from_ops(args.ops_per_sec)
    elif ecpu_millions is None:
        ecpu_millions = 100.0

    if args.extended_support:
        result = estimate_extended_support(loader, args.engine, args.region, args.node_type, args.nodes)
        print(format_extended_support_report(result))
    elif args.show_ri_options:
        print(format_ri_options(loader, args.engine, args.region, args.node_type, args.nodes))
    elif args.mode == "serverless":
        result = estimate_serverless(loader, args.engine, args.region, args.data_gb, ecpu_millions, args.avg_payload_kb)
        result["disclaimer"] = "Estimates only. Verify at https://aws.amazon.com/elasticache/pricing/"
        print(json.dumps(result, indent=2))
    elif args.mode == "node":
        result = estimate_node_based(loader, args.engine, args.region, args.node_type, args.nodes, ri_term=args.ri_term)
        result["disclaimer"] = "Estimates only. Verify at https://aws.amazon.com/elasticache/pricing/"
        print(json.dumps(result, indent=2))
