"""Aurora Reserved Instance & Database Savings Plan estimator.

Read-only tool that fetches live RI and DSP rates from AWS and projects
monthly cost under each commitment option for a cluster, fleet, or
user-supplied workload. No purchase APIs are ever called.

Usage:
    python commitment_pricing_analyzer.py --cluster my-cluster --region us-east-1
    python commitment_pricing_analyzer.py --all --region us-east-1
    python commitment_pricing_analyzer.py offline \\
        --instance db.r7g.2xlarge --num-instances 2 --region us-east-1
    python commitment_pricing_analyzer.py offline \\
        --serverless --avg-acu 8 --region us-east-1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass

HOURS_PER_MONTH = 730

# ---------------------------------------------------------------------------
# Static fallback on-demand prices (us-east-1, Aurora MySQL Standard;
# Aurora MySQL and PostgreSQL share these instance rates).
# I/O-Optimized premium applied via multiplier.
# ---------------------------------------------------------------------------
IO_OPT_COMPUTE_MULTIPLIER = 1.30
ACU_PRICE_STANDARD = 0.12  # $/ACU-Hr
ACU_PRICE_IO_OPTIMIZED = 0.156

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
}

# DSP only covers these families
_DSP_ELIGIBLE_FAMILIES = {"r7g", "r7i", "r8g", "r8gd", "m7g", "m7i", "c7g", "c7i", "x8g"}

_DSP_SIZE_MAP = {
    "micro": "micro",
    "small": "small",
    "medium": "medium",
    "large": "large",
    "xl": "xlarge",
    "2xl": "2xlarge",
    "4xl": "4xlarge",
    "8xl": "8xlarge",
    "12xl": "12xlarge",
    "16xl": "16xlarge",
    "24xl": "24xlarge",
    "48xl": "48xlarge",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RIOffering:
    instance_type: str
    term_years: int
    payment_option: str  # "No Upfront" | "Partial Upfront" | "All Upfront"
    effective_hourly: float  # (upfront / term_hours) + recurring
    upfront_cost: float
    recurring_hourly: float

    def monthly_cost(self) -> float:
        return self.effective_hourly * HOURS_PER_MONTH


@dataclass
class DSPRate:
    usage_type: str  # instance type or "ServerlessV2"
    term_years: int  # always 1 for Aurora DSP
    payment_option: str
    rate_per_hour: float

    def monthly_cost(self) -> float:
        return self.rate_per_hour * HOURS_PER_MONTH


# ---------------------------------------------------------------------------
# Live AWS fetchers
# ---------------------------------------------------------------------------


def _family_from_instance(instance_type: str) -> str:
    m = re.match(r"db\.([a-z0-9]+)\.", instance_type)
    return m.group(1) if m else ""


def get_on_demand_price(instance_type: str, region: str = "us-east-1") -> float:
    """Return on-demand hourly price. Tries Pricing API, falls back to static."""
    try:
        import boto3
    except ImportError:
        return _STATIC_INSTANCE_PRICES.get(instance_type, 0.0)

    location = _REGION_NAMES.get(region)
    if not location:
        return _STATIC_INSTANCE_PRICES.get(instance_type, 0.0)

    try:
        pricing = boto3.client("pricing", region_name="us-east-1")
        filters = [
            {"Type": "TERM_MATCH", "Field": "databaseEngine", "Value": "Aurora MySQL"},
            {"Type": "TERM_MATCH", "Field": "location", "Value": location},
            {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
            {"Type": "TERM_MATCH", "Field": "deploymentOption", "Value": "Single-AZ"},
            {"Type": "TERM_MATCH", "Field": "termType", "Value": "OnDemand"},
        ]
        for page in pricing.get_paginator("get_products").paginate(
            ServiceCode="AmazonRDS", Filters=filters
        ):
            for item_json in page["PriceList"]:
                item = json.loads(item_json) if isinstance(item_json, str) else item_json
                attrs = item.get("product", {}).get("attributes", {})
                if "IOOptimized" in attrs.get("usagetype", ""):
                    continue
                for term in item.get("terms", {}).get("OnDemand", {}).values():
                    for dim in term.get("priceDimensions", {}).values():
                        try:
                            price = float(dim.get("pricePerUnit", {}).get("USD", "0"))
                        except (ValueError, TypeError):
                            continue
                        if price > 0:
                            return price
    except Exception:
        pass

    return _STATIC_INSTANCE_PRICES.get(instance_type, 0.0)


def fetch_ri_offerings(instance_type: str, region: str) -> list[RIOffering]:
    """Fetch all RI offerings for an instance type. Returns [] on failure."""
    try:
        import boto3
    except ImportError:
        return []

    results: list[RIOffering] = []
    try:
        rds = boto3.client("rds", region_name=region)
        for engine in ("aurora-mysql",):
            try:
                paginator = rds.get_paginator("describe_reserved_db_instances_offerings")
                for page in paginator.paginate(
                    DBInstanceClass=instance_type,
                    ProductDescription=engine,
                    MultiAZ=False,
                ):
                    for offering in page.get("ReservedDBInstancesOfferings", []):
                        inst = offering.get("DBInstanceClass", "")
                        if inst != instance_type:
                            continue
                        duration = offering.get("Duration", 0)
                        term_years = 3 if duration > 94_000_000 else 1
                        payment = offering.get("OfferingType", "")
                        fixed = float(offering.get("FixedPrice", 0.0))
                        recurring_list = offering.get("RecurringCharges", [])
                        recurring_hr = sum(
                            float(rc.get("RecurringChargeAmount", 0.0)) for rc in recurring_list
                        )
                        term_hours = term_years * 365 * 24
                        effective = (fixed / term_hours) + recurring_hr
                        results.append(
                            RIOffering(
                                instance_type=inst,
                                term_years=term_years,
                                payment_option=payment,
                                effective_hourly=round(effective, 6),
                                upfront_cost=round(fixed, 2),
                                recurring_hourly=round(recurring_hr, 6),
                            )
                        )
            except Exception:
                continue
    except Exception:
        return []

    # Deduplicate (same offering exists for both engines)
    seen = set()
    deduped = []
    for r in results:
        key = (r.term_years, r.payment_option, round(r.effective_hourly, 6))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def fetch_dsp_rates(region: str) -> dict[str, list[DSPRate]]:
    """Fetch Database Savings Plan rates for Aurora in the region.

    Returns dict mapping usage key (instance type or 'ServerlessV2') to rates.
    """
    try:
        import boto3
    except ImportError:
        return {}

    result: dict[str, list[DSPRate]] = {}
    try:
        sp = boto3.client("savingsplans", region_name="us-east-1")
    except Exception:
        return {}

    for engine in ("Aurora MySQL",):
        try:
            rates = []
            token = None
            while True:
                kwargs = {
                    "savingsPlanTypes": ["Database"],
                    "products": ["RDS"],
                    "serviceCodes": ["AmazonRDS"],
                    "filters": [
                        {"name": "region", "values": [region]},
                        {"name": "productDescription", "values": [engine]},
                    ],
                    "maxResults": 1000,
                }
                if token:
                    kwargs["nextToken"] = token
                resp = sp.describe_savings_plans_offering_rates(**kwargs)
                rates.extend(resp.get("searchResults", []))
                token = resp.get("nextToken")
                if not token:
                    break

            for rate_entry in rates:
                offering = rate_entry.get("savingsPlanOffering", {})
                dur = offering.get("durationSeconds", 0)
                term_years = 3 if dur > 94_000_000 else 1
                payment = offering.get("paymentOption", "")
                try:
                    rate_val = float(rate_entry.get("rate", "0"))
                except (ValueError, TypeError):
                    continue
                if rate_val <= 0:
                    continue

                usage = rate_entry.get("usageType", "")
                unit = rate_entry.get("unit", "")

                # Skip I/O-Optimized variants for consistency; main pricing uses Standard
                if "IOOptimized" in usage:
                    continue

                if unit == "ACU-Hr" and "ServerlessV2" in usage:
                    key = "ServerlessV2"
                else:
                    m = re.match(r"InstanceUsage:db\.(\w+)\.(\w+)", usage)
                    if not m:
                        continue
                    family = m.group(1)
                    short_size = m.group(2)
                    size = _DSP_SIZE_MAP.get(short_size, short_size)
                    key = f"db.{family}.{size}"

                entry = DSPRate(
                    usage_type=key,
                    term_years=term_years,
                    payment_option=payment,
                    rate_per_hour=round(rate_val, 6),
                )
                existing = result.get(key, [])
                if not any(
                    e.term_years == entry.term_years and e.payment_option == entry.payment_option
                    for e in existing
                ):
                    result.setdefault(key, []).append(entry)
        except Exception:
            continue

    return result


# ---------------------------------------------------------------------------
# Best-of selection (lowest effective monthly cost per term/category)
# ---------------------------------------------------------------------------


def best_ri(offerings: list[RIOffering], term_years: int) -> RIOffering | None:
    candidates = [r for r in offerings if r.term_years == term_years]
    if not candidates:
        return None
    return min(candidates, key=lambda r: r.effective_hourly)


def best_dsp(rates: list[DSPRate], term_years: int = 1) -> DSPRate | None:
    candidates = [r for r in rates if r.term_years == term_years]
    if not candidates:
        return None
    return min(candidates, key=lambda r: r.rate_per_hour)


# ---------------------------------------------------------------------------
# Comparison builder — single workload
# ---------------------------------------------------------------------------


def build_comparison(
    instance_type: str,
    num_instances: int,
    region: str,
    io_optimized: bool = False,
    is_serverless: bool = False,
    avg_acu: float = 0.0,
    dsp_rates: dict[str, list[DSPRate]] | None = None,
) -> dict:
    """Compare on-demand, RI, and DSP for a single workload description."""
    if dsp_rates is None:
        dsp_rates = fetch_dsp_rates(region)

    if is_serverless:
        od_hourly = ACU_PRICE_IO_OPTIMIZED if io_optimized else ACU_PRICE_STANDARD
        # For Serverless v2, "number of instances" is irrelevant — we price avg ACU continuously
        units = avg_acu
        od_monthly = od_hourly * units * HOURS_PER_MONTH

        dsp_entry = best_dsp(dsp_rates.get("ServerlessV2", []))
        dsp_monthly = dsp_entry.rate_per_hour * units * HOURS_PER_MONTH if dsp_entry else None
        dsp_savings = (od_monthly - dsp_monthly) if dsp_monthly is not None else None

        return {
            "workload_type": "serverless_v2",
            "avg_acu": avg_acu,
            "io_optimized": io_optimized,
            "on_demand": {
                "hourly": od_hourly,
                "monthly": round(od_monthly, 2),
            },
            "ri_1yr": None,
            "ri_3yr": None,
            "dsp_1yr": _format_dsp(dsp_entry, units, od_monthly) if dsp_entry else None,
            "recommendation": _recommend_serverless(dsp_savings, od_monthly),
            "notes": [
                "Reserved Instances do not apply to Aurora Serverless v2.",
                "DSP covers ACU-hours but bills the committed $/hr continuously, "
                "even during auto-pause. Only commit to the steady baseline ACU.",
            ],
        }

    # Provisioned
    family = _family_from_instance(instance_type)
    od_hourly = get_on_demand_price(instance_type, region)
    if io_optimized:
        od_hourly *= IO_OPT_COMPUTE_MULTIPLIER
    od_monthly = od_hourly * HOURS_PER_MONTH * num_instances

    ri_offerings = fetch_ri_offerings(instance_type, region)
    ri_1yr = best_ri(ri_offerings, 1)
    ri_3yr = best_ri(ri_offerings, 3)

    # I/O-Optimized RI coverage (AWS Compute Optimizer, verified): an I/O-Optimized
    # instance is FULLY covered by Reserved Instances — no portion is forced to
    # on-demand — but it "consumes 30% more normalized units per hour than Aurora
    # Standard", i.e. it draws down RI capacity at 1.30×. So the effective RI cost is
    # the (Standard-normalized) RI rate × 1.30. Equivalently: buy ~30% more normalized
    # RI units to cover the same I/O-Optimized fleet.
    #   io-opt RI monthly = ri_rate × 1.30 × hours × N
    def ri_adjusted_monthly(ri: RIOffering | None) -> float | None:
        if ri is None:
            return None
        units = IO_OPT_COMPUTE_MULTIPLIER if io_optimized else 1.0
        return ri.effective_hourly * units * HOURS_PER_MONTH * num_instances

    ri_1yr_monthly = ri_adjusted_monthly(ri_1yr)
    ri_3yr_monthly = ri_adjusted_monthly(ri_3yr)

    dsp_entry = best_dsp(dsp_rates.get(instance_type, []))
    dsp_monthly = dsp_entry.rate_per_hour * HOURS_PER_MONTH * num_instances if dsp_entry else None

    dsp_eligible = family in _DSP_ELIGIBLE_FAMILIES
    notes = []
    if not dsp_eligible:
        notes.append(
            f"Database Savings Plans do not cover the {family} family. "
            f"DSP requires r7g, r8g, r7i, or newer-gen Aurora-compatible families."
        )
    if io_optimized:
        notes.append(
            "Cluster is I/O-Optimized (30% compute premium). Both RI and DSP cover the "
            "full I/O-Optimized instance price — I/O-Optimized consumes 30% more "
            "normalized units per hour, so an RI draws down capacity at 1.30× (buy ~30% "
            "more normalized RI units to fully cover the fleet); no portion is on-demand."
        )

    return {
        "workload_type": "provisioned",
        "instance_type": instance_type,
        "num_instances": num_instances,
        "io_optimized": io_optimized,
        "on_demand": {
            "hourly": round(od_hourly, 4),
            "monthly": round(od_monthly, 2),
        },
        "ri_1yr": _format_ri(ri_1yr, ri_1yr_monthly, od_monthly, num_instances),
        "ri_3yr": _format_ri(ri_3yr, ri_3yr_monthly, od_monthly, num_instances),
        "dsp_1yr": (_format_dsp(dsp_entry, num_instances, od_monthly) if dsp_entry else None),
        "recommendation": _recommend_provisioned(
            od_monthly,
            ri_1yr_monthly,
            ri_3yr_monthly,
            dsp_monthly,
            dsp_eligible=dsp_eligible,
            io_optimized=io_optimized,
        ),
        "notes": notes,
    }


def _format_ri(
    ri: RIOffering | None, monthly: float | None, od_monthly: float, n: int
) -> dict | None:
    if ri is None or monthly is None:
        return None
    savings = od_monthly - monthly
    pct = (savings / od_monthly * 100) if od_monthly > 0 else 0
    return {
        "term_years": ri.term_years,
        "payment_option": ri.payment_option,
        "effective_hourly_per_instance": round(ri.effective_hourly, 4),
        "upfront_total": round(ri.upfront_cost * n, 2),
        "monthly": round(monthly, 2),
        "savings_monthly": round(savings, 2),
        "savings_pct": round(pct, 1),
    }


def _format_dsp(dsp: DSPRate | None, units: float, od_monthly: float) -> dict | None:
    if dsp is None:
        return None
    monthly = dsp.rate_per_hour * HOURS_PER_MONTH * units
    savings = od_monthly - monthly
    pct = (savings / od_monthly * 100) if od_monthly > 0 else 0
    return {
        "term_years": dsp.term_years,
        "payment_option": dsp.payment_option,
        "rate_per_hour": round(dsp.rate_per_hour, 4),
        "monthly": round(monthly, 2),
        "savings_monthly": round(savings, 2),
        "savings_pct": round(pct, 1),
    }


def _recommend_provisioned(
    od: float,
    ri_1yr: float | None,
    ri_3yr: float | None,
    dsp: float | None,
    dsp_eligible: bool,
    io_optimized: bool,
) -> dict:
    options = []
    if ri_1yr is not None:
        options.append(("1yr RI", ri_1yr))
    if ri_3yr is not None:
        options.append(("3yr RI", ri_3yr))
    if dsp is not None:
        options.append(("1yr DSP", dsp))

    if not options:
        return {
            "best_option": "on_demand",
            "reason": "No RI or DSP offerings available for this instance type/region.",
        }

    best_label, best_cost = min(options, key=lambda x: x[1])
    savings = od - best_cost
    pct = (savings / od * 100) if od > 0 else 0

    reasons = [
        f"{best_label} is the lowest-cost option, saving ${savings:.0f}/mo ({pct:.0f}%) vs on-demand."
    ]
    if best_label == "3yr RI":
        reasons.append(
            "Best fit for steady 24/7 workloads you're confident will stay on this instance family for 3 years."
        )
    elif best_label == "1yr DSP":
        reasons.append(
            "Offers flexibility — covers any eligible Aurora instance family in the account, including future upgrades."
        )
        if io_optimized:
            reasons.append(
                "DSP is particularly attractive for I/O-Optimized clusters since it covers the full rate."
            )
    elif best_label == "1yr RI":
        reasons.append(
            "Shorter commitment than 3yr, useful when instance-family migration is on the horizon."
        )

    if not dsp_eligible and dsp is None:
        reasons.append(
            "DSP is not available for this instance family, so RI is the only commitment option."
        )

    return {
        "best_option": best_label,
        "best_monthly_cost": round(best_cost, 2),
        "savings_vs_on_demand": round(savings, 2),
        "savings_pct": round(pct, 1),
        "reason": " ".join(reasons),
    }


def _recommend_serverless(dsp_savings: float | None, od_monthly: float) -> dict:
    if dsp_savings is None:
        return {
            "best_option": "on_demand",
            "reason": "No Database Savings Plan rates available for Serverless v2 ACU in this region.",
        }
    if dsp_savings <= 0:
        return {
            "best_option": "on_demand",
            "reason": "DSP would not save money at the specified average ACU.",
        }
    pct = (dsp_savings / od_monthly * 100) if od_monthly > 0 else 0
    return {
        "best_option": "1yr DSP",
        "savings_vs_on_demand": round(dsp_savings, 2),
        "savings_pct": round(pct, 1),
        "reason": (
            f"1yr DSP saves ${dsp_savings:.0f}/mo ({pct:.0f}%). "
            "Size the commitment to your steady baseline ACU — DSP bills the committed $/hr "
            "continuously, even during idle periods."
        ),
    }


# ---------------------------------------------------------------------------
# Live cluster analysis
# ---------------------------------------------------------------------------


def _is_empty_cluster(cluster: dict) -> bool:
    """Skip clusters with no compute to analyze.

    An Aurora cluster with no DB instances has no compute cost, so RI and DSP
    commitment analysis doesn't apply. Typical cases: the last writer/reader
    instance was deleted, paused/stopped clusters, or clusters mid-migration.
    """
    return len(cluster.get("DBClusterMembers", [])) == 0


def analyze_cluster_live(cluster_id: str, region: str) -> dict:
    import boto3

    rds = boto3.client("rds", region_name=region)

    try:
        resp = rds.describe_db_clusters(DBClusterIdentifier=cluster_id)
    except Exception as e:
        return {"cluster_id": cluster_id, "error": str(e)}
    clusters = resp.get("DBClusters", [])
    if not clusters:
        return {"cluster_id": cluster_id, "error": "cluster not found"}
    cluster = clusters[0]
    storage_type = cluster.get("StorageType", "aurora")
    io_optimized = storage_type == "aurora-iopt1"
    engine = cluster.get("Engine", "")

    # Guardrail: skip clusters with no DB instances (last instance deleted, paused, mid-migration, etc.)
    if _is_empty_cluster(cluster):
        return {
            "cluster_id": cluster_id,
            "engine": engine,
            "engine_version": cluster.get("EngineVersion", ""),
            "storage_type": storage_type,
            "skipped": True,
            "reason": (
                "Cluster has no DB instances — no compute to price. "
                "RI and DSP commitment analysis does not apply. "
                "This typically indicates the last instance was deleted, a paused "
                "cluster, or a cluster mid-migration."
            ),
        }

    # Identify instances
    member_ids = [m["DBInstanceIdentifier"] for m in cluster.get("DBClusterMembers", [])]
    type_counts: dict[str, int] = {}
    serverless_instances = 0
    for mid in member_ids:
        try:
            iresp = rds.describe_db_instances(DBInstanceIdentifier=mid)
            for inst in iresp.get("DBInstances", []):
                itype = inst.get("DBInstanceClass", "")
                if itype == "db.serverless":
                    serverless_instances += 1
                else:
                    type_counts[itype] = type_counts.get(itype, 0) + 1
        except Exception:
            continue

    # Prefetch DSP rates once for this cluster analysis
    dsp_rates = fetch_dsp_rates(region)

    sub_workloads = []
    for itype, count in type_counts.items():
        sub_workloads.append(
            build_comparison(
                instance_type=itype,
                num_instances=count,
                region=region,
                io_optimized=io_optimized,
                dsp_rates=dsp_rates,
            )
        )
    if serverless_instances > 0:
        # Without observed ACU metrics, we can't price serverless exactly — note it
        sub_workloads.append(
            {
                "workload_type": "serverless_v2",
                "instance_count": serverless_instances,
                "note": "Serverless v2 instances detected. Re-run with 'offline --serverless "
                "--avg-acu <N>' using your observed average ACU (from CloudWatch "
                "ServerlessDatabaseCapacity metric) for a precise DSP estimate.",
                "io_optimized": io_optimized,
            }
        )

    return {
        "cluster_id": cluster_id,
        "engine": engine,
        "storage_type": storage_type,
        "io_optimized": io_optimized,
        "instance_mix": {**type_counts, "serverless": serverless_instances},
        "workloads": sub_workloads,
    }


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
# Output formatting
# ---------------------------------------------------------------------------


def _format_table_single(result: dict) -> str:
    lines = []
    lines.append("=" * 72)
    if result.get("workload_type") == "serverless_v2":
        lines.append(f"Aurora Serverless v2 Commitment Pricing")
        lines.append(
            f"  Avg ACU: {result.get('avg_acu', 0):.1f}  "
            f"I/O-Optimized: {result.get('io_optimized', False)}"
        )
    else:
        lines.append(
            f"Aurora Commitment Pricing — "
            f"{result.get('num_instances', 1)}× {result.get('instance_type', '?')}"
        )
        if result.get("io_optimized"):
            lines.append("  Storage: I/O-Optimized (30% compute premium applied)")
    lines.append("=" * 72)
    od_monthly = result["on_demand"]["monthly"]
    lines.append("")
    lines.append(f"  {'Option':<28} {'Monthly':>12} {'Savings':>12} {'Upfront':>12}  Term")
    lines.append("  " + "-" * 70)
    lines.append(f"  {'On-Demand':<28} ${od_monthly:>11,.0f} {'—':>12} {'$0':>12}  —")

    for key, label, term_hint in (
        ("ri_1yr", "1yr RI", "1 year"),
        ("ri_3yr", "3yr RI", "3 years"),
        ("dsp_1yr", "1yr DSP", "1 year"),
    ):
        entry = result.get(key)
        if not entry:
            continue
        payment = entry.get("payment_option", "")
        display = f"{label} ({payment})" if payment else label
        monthly = entry.get("monthly", 0)
        savings = entry.get("savings_monthly", 0)
        pct = entry.get("savings_pct", 0)
        upfront = entry.get("upfront_total", 0)
        savings_str = f"${savings:,.0f} ({pct:.0f}%)" if savings else "—"
        upfront_str = f"${upfront:,.0f}" if upfront else "$0"
        lines.append(
            f"  {display:<28} ${monthly:>11,.0f} {savings_str:>12} {upfront_str:>12}  {term_hint}"
        )

    rec = result.get("recommendation", {})
    lines.append("")
    lines.append(f"  Recommendation: {rec.get('best_option', '?')}")
    lines.append(f"  {rec.get('reason', '')}")

    notes = result.get("notes", [])
    if notes:
        lines.append("")
        for n in notes:
            lines.append(f"  Note: {n}")
    lines.append("=" * 72)
    return "\n".join(lines)


def _format_cluster(result: dict) -> str:
    lines = []
    lines.append(
        f"Cluster: {result.get('cluster_id', '?')}  "
        f"({result.get('engine', '?')})  "
        f"storage_type={result.get('storage_type', '?')}"
    )
    workloads = result.get("workloads", [])
    for wl in workloads:
        if wl.get("workload_type") == "serverless_v2" and "note" in wl:
            lines.append("")
            lines.append(f"  [Serverless v2 — {wl.get('instance_count', 0)} instance(s)]")
            lines.append(f"  {wl['note']}")
            continue
        lines.append("")
        lines.append(_format_table_single(wl))
    return "\n".join(lines)


def _format_fleet(output: dict) -> str:
    lines = []
    lines.append(f"Region: {output['region']}")
    lines.append("")
    total_od = 0.0
    total_best = 0.0
    for cluster in output["clusters"]:
        if "error" in cluster:
            lines.append(f"{cluster['cluster_id']}: ERROR {cluster['error']}")
            continue
        for wl in cluster.get("workloads", []):
            if wl.get("workload_type") != "provisioned":
                continue
            od = wl["on_demand"]["monthly"]
            best = wl.get("recommendation", {}).get("best_monthly_cost", od)
            total_od += od
            total_best += best
    lines.append(f"  Fleet monthly on-demand:    ${total_od:,.0f}")
    lines.append(f"  With best commitments:      ${total_best:,.0f}")
    savings = total_od - total_best
    pct = (savings / total_od * 100) if total_od > 0 else 0
    lines.append(f"  Fleet savings opportunity:  ${savings:,.0f}/mo ({pct:.0f}%)")
    lines.append("")
    for cluster in output["clusters"]:
        if "error" in cluster:
            continue
        lines.append("")
        lines.append(_format_cluster(cluster))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Aurora RI & Database Savings Plan estimator (read-only)"
    )
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--format", choices=["json", "table"], default="json")
    parser.add_argument("--cluster", help="Analyze a single cluster by identifier")
    parser.add_argument(
        "--all", action="store_true", help="Analyze all Aurora clusters in the region"
    )

    sub = parser.add_subparsers(dest="mode")
    off = sub.add_parser("offline", help="Use user-supplied workload description")
    off.add_argument("--instance", help="Instance type (e.g., db.r7g.2xlarge)")
    off.add_argument("--num-instances", type=int, default=1)
    off.add_argument(
        "--io-optimized", action="store_true", help="Workload uses Aurora I/O-Optimized storage"
    )
    off.add_argument(
        "--serverless", action="store_true", help="Serverless v2 workload — requires --avg-acu"
    )
    off.add_argument(
        "--avg-acu", type=float, default=0.0, help="Average ACU for serverless workload"
    )
    off.add_argument("--region", default="us-east-1")
    off.add_argument("--format", choices=["json", "table"], default="json")

    args = parser.parse_args()

    if args.mode == "offline":
        if args.serverless:
            if args.avg_acu <= 0:
                print("ERROR: --serverless requires --avg-acu > 0", file=sys.stderr)
                sys.exit(2)
            result = build_comparison(
                instance_type="",
                num_instances=0,
                region=args.region,
                io_optimized=args.io_optimized,
                is_serverless=True,
                avg_acu=args.avg_acu,
            )
        else:
            if not args.instance:
                print("ERROR: offline mode requires --instance (or --serverless)", file=sys.stderr)
                sys.exit(2)
            result = build_comparison(
                instance_type=args.instance,
                num_instances=args.num_instances,
                region=args.region,
                io_optimized=args.io_optimized,
            )
        if args.format == "json":
            print(json.dumps(result, indent=2, default=str))
        else:
            print(_format_table_single(result))
        return

    # Live modes require boto3
    try:
        import boto3  # noqa: F401
    except ImportError:
        print(
            "ERROR: boto3 required for live AWS analysis. Use the 'offline' subcommand.",
            file=sys.stderr,
        )
        sys.exit(2)

    if args.all:
        cluster_ids = list_clusters(args.region)
        results = [analyze_cluster_live(cid, args.region) for cid in cluster_ids]
        output = {"region": args.region, "cluster_count": len(results), "clusters": results}
        if args.format == "json":
            print(json.dumps(output, indent=2, default=str))
        else:
            print(_format_fleet(output))
        return

    if args.cluster:
        result = analyze_cluster_live(args.cluster, args.region)
        if args.format == "json":
            print(json.dumps(result, indent=2, default=str))
        else:
            print(_format_cluster(result))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
