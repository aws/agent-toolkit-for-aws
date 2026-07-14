"""RDS Reserved Instance & Database Savings Plan estimator.

Read-only tool that fetches live RI and DSP rates from AWS and projects
monthly cost under each commitment option for RDS MySQL, MariaDB, and
PostgreSQL instances. No purchase APIs are ever called.

Usage:
    python rds_commitment_pricing_analyzer.py --instance my-rds-db --region us-east-1
    python rds_commitment_pricing_analyzer.py --region us-east-1 offline \
        --instance-type db.r7g.2xlarge --engine mysql --num-instances 2
    python rds_commitment_pricing_analyzer.py --region us-east-1 offline \
        --instance-type db.r7g.2xlarge --engine postgres --multi-az
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass

HOURS_PER_MONTH = 730

ENGINE_PRODUCT_MAP = {
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "postgres": "PostgreSQL",
}

_STATIC_INSTANCE_PRICES = {
    "db.t3.medium": 0.068,
    "db.t3.large": 0.136,
    "db.t4g.medium": 0.065,
    "db.t4g.large": 0.129,
    "db.m5.large": 0.171,
    "db.m5.xlarge": 0.342,
    "db.m5.2xlarge": 0.684,
    "db.m6g.large": 0.154,
    "db.m6g.xlarge": 0.308,
    "db.m6g.2xlarge": 0.616,
    "db.m7g.large": 0.162,
    "db.m7g.xlarge": 0.324,
    "db.m7g.2xlarge": 0.648,
    "db.r5.large": 0.240,
    "db.r5.xlarge": 0.480,
    "db.r5.2xlarge": 0.960,
    "db.r5.4xlarge": 1.920,
    "db.r5.8xlarge": 3.840,
    "db.r6g.large": 0.218,
    "db.r6g.xlarge": 0.435,
    "db.r6g.2xlarge": 0.870,
    "db.r6g.4xlarge": 1.740,
    "db.r6g.8xlarge": 3.480,
    "db.r7g.large": 0.228,
    "db.r7g.xlarge": 0.456,
    "db.r7g.2xlarge": 0.912,
    "db.r7g.4xlarge": 1.824,
    "db.r7g.8xlarge": 3.648,
    "db.r8g.large": 0.240,
    "db.r8g.xlarge": 0.480,
    "db.r8g.2xlarge": 0.960,
    "db.r8g.4xlarge": 1.920,
    "db.r8g.8xlarge": 3.840,
}

MULTI_AZ_MULTIPLIER = 2.0
_DSP_ELIGIBLE_FAMILIES = {"r7g", "r7i", "r8g", "r8gd", "m7g", "m7i", "c7g", "c7i", "x8g"}

_REGION_NAMES = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-central-1": "EU (Frankfurt)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-south-1": "Asia Pacific (Mumbai)",
}


@dataclass
class RIOffering:
    instance_type: str
    term_years: int
    payment_option: str
    effective_hourly: float
    upfront_cost: float
    recurring_hourly: float
    multi_az: bool = False

    def monthly_cost(self) -> float:
        return self.effective_hourly * HOURS_PER_MONTH


@dataclass
class DSPRate:
    usage_type: str
    term_years: int
    payment_option: str
    rate_per_hour: float

    def monthly_cost(self) -> float:
        return self.rate_per_hour * HOURS_PER_MONTH


def _family_from_instance(instance_type: str) -> str:
    m = re.match(r"db\.([a-z0-9]+)\.", instance_type)
    return m.group(1) if m else ""


def get_on_demand_price(
    instance_type: str, region: str = "us-east-1", multi_az: bool = False
) -> float:
    price = _STATIC_INSTANCE_PRICES.get(instance_type, 0.0)
    if region != "us-east-1" and price > 0:
        # Static prices reflect us-east-1 only; actual price in other regions may differ
        import warnings

        warnings.warn(
            f"On-demand price for {instance_type} is based on us-east-1. "
            f"Actual price in {region} may differ."
        )
    if multi_az:
        price *= MULTI_AZ_MULTIPLIER
    return price


def fetch_ri_offerings(
    instance_type: str, engine: str, region: str, multi_az: bool = False
) -> list[RIOffering]:
    try:
        import boto3
    except ImportError:
        return []

    product_desc = ENGINE_PRODUCT_MAP.get(engine, "MySQL")
    results: list[RIOffering] = []
    try:
        rds = boto3.client("rds", region_name=region)
        paginator = rds.get_paginator("describe_reserved_db_instances_offerings")
        for page in paginator.paginate(
            DBInstanceClass=instance_type,
            ProductDescription=product_desc,
            MultiAZ=multi_az,
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
                        multi_az=multi_az,
                    )
                )
    except Exception:
        return []

    seen = set()
    deduped = []
    for r in results:
        key = (r.term_years, r.payment_option, round(r.effective_hourly, 6))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def fetch_dsp_rates(engine: str, region: str) -> dict[str, list[DSPRate]]:
    try:
        import boto3
    except ImportError:
        return {}

    result: dict[str, list[DSPRate]] = {}
    product_desc = ENGINE_PRODUCT_MAP.get(engine, "MySQL")
    try:
        sp = boto3.client("savingsplans", region_name="us-east-1")
        rates = []
        token = None
        while True:
            kwargs = {
                "savingsPlanTypes": ["Database"],
                "products": ["RDS"],
                "serviceCodes": ["AmazonRDS"],
                "filters": [
                    {"name": "region", "values": [region]},
                    {"name": "productDescription", "values": [product_desc]},
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
            # Usage types may carry a region prefix (e.g. "USE2-InstanceUsage:db.r7g.2xlarge"),
            # so search anywhere in the string rather than anchoring at the start.
            m = re.search(r"InstanceUsage:db\.(\w+)\.(\w+)", usage)
            if not m:
                continue
            family = m.group(1)
            size = m.group(2)
            key = f"db.{family}.{size}"
            entry = DSPRate(
                usage_type=key,
                term_years=term_years,
                payment_option=payment,
                rate_per_hour=round(rate_val, 6),
            )
            result.setdefault(key, []).append(entry)
    except Exception:
        pass
    return result


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


def build_comparison(
    instance_type: str,
    engine: str,
    num_instances: int,
    region: str,
    multi_az: bool = False,
    dsp_rates: dict[str, list[DSPRate]] | None = None,
) -> dict:
    if dsp_rates is None:
        dsp_rates = fetch_dsp_rates(engine, region)

    family = _family_from_instance(instance_type)
    od_hourly = get_on_demand_price(instance_type, region, multi_az)
    od_monthly = od_hourly * HOURS_PER_MONTH * num_instances

    ri_offerings = fetch_ri_offerings(instance_type, engine, region, multi_az)
    ri_1yr = best_ri(ri_offerings, 1)
    ri_3yr = best_ri(ri_offerings, 3)

    ri_1yr_monthly = ri_1yr.effective_hourly * HOURS_PER_MONTH * num_instances if ri_1yr else None
    ri_3yr_monthly = ri_3yr.effective_hourly * HOURS_PER_MONTH * num_instances if ri_3yr else None

    dsp_entry_1yr = best_dsp(dsp_rates.get(instance_type, []), 1)
    dsp_entry_3yr = best_dsp(dsp_rates.get(instance_type, []), 3)
    # Multi-AZ consumes 2x the compute hours the savings plan must cover, mirroring
    # the on-demand and RI Multi-AZ handling above. Without this, DSP savings are overstated.
    az_multiplier = MULTI_AZ_MULTIPLIER if multi_az else 1.0
    dsp_1yr_monthly = (
        dsp_entry_1yr.rate_per_hour * HOURS_PER_MONTH * num_instances * az_multiplier
        if dsp_entry_1yr
        else None
    )
    dsp_3yr_monthly = (
        dsp_entry_3yr.rate_per_hour * HOURS_PER_MONTH * num_instances * az_multiplier
        if dsp_entry_3yr
        else None
    )

    dsp_eligible = family in _DSP_ELIGIBLE_FAMILIES
    notes = []
    if od_hourly == 0:
        notes.append(
            f"No static on-demand price is bundled for {instance_type}, so the offline "
            f"baseline is $0 and savings cannot be computed. Run against a live instance "
            f"(no 'offline' subcommand) or supply pricing to get accurate figures."
        )
    if not dsp_eligible:
        notes.append(
            f"Database Savings Plans do not cover the {family} family. "
            f"Eligible families: {', '.join(sorted(_DSP_ELIGIBLE_FAMILIES))}."
        )
    if multi_az:
        notes.append(
            "Multi-AZ pricing applied. Multi-AZ RIs are separate offerings from Single-AZ. "
            "Ensure you purchase the correct deployment type."
        )
    if region != "us-east-1" and od_hourly > 0:
        notes.append(
            f"On-demand baseline for {instance_type} uses us-east-1 static pricing; "
            f"actual {region} pricing may differ by 10-20%, so savings percentages are approximate. "
            f"Provide live pricing or run in us-east-1 for exact figures."
        )

    def _fmt(ri, monthly, od):
        if ri is None or monthly is None:
            return None
        savings = od - monthly
        pct = (savings / od * 100) if od > 0 else 0
        return {
            "term_years": ri.term_years,
            "payment_option": ri.payment_option,
            "effective_hourly_per_instance": round(ri.effective_hourly, 4),
            "upfront_total": round(ri.upfront_cost * num_instances, 2),
            "monthly": round(monthly, 2),
            "savings_monthly": round(savings, 2),
            "savings_pct": round(pct, 1),
        }

    def _fmt_dsp(dsp, monthly, od):
        if dsp is None or monthly is None:
            return None
        savings = od - monthly
        pct = (savings / od * 100) if od > 0 else 0
        return {
            "term_years": dsp.term_years,
            "payment_option": dsp.payment_option,
            "rate_per_hour": round(dsp.rate_per_hour, 4),
            "monthly": round(monthly, 2),
            "savings_monthly": round(savings, 2),
            "savings_pct": round(pct, 1),
        }

    options = []
    if ri_1yr_monthly is not None:
        options.append(("1yr RI", ri_1yr_monthly))
    if ri_3yr_monthly is not None:
        options.append(("3yr RI", ri_3yr_monthly))
    if dsp_1yr_monthly is not None:
        options.append(("1yr DSP", dsp_1yr_monthly))
    if dsp_3yr_monthly is not None:
        options.append(("3yr DSP", dsp_3yr_monthly))

    if options:
        best_label, best_cost = min(options, key=lambda x: x[1])
        savings = od_monthly - best_cost
        pct = (savings / od_monthly * 100) if od_monthly > 0 else 0
        recommendation = {
            "best_option": best_label,
            "best_monthly_cost": round(best_cost, 2),
            "savings_vs_on_demand": round(savings, 2),
            "savings_pct": round(pct, 1),
        }
    else:
        recommendation = {"best_option": "on_demand", "reason": "No RI or DSP offerings found."}

    return {
        "engine": engine,
        "instance_type": instance_type,
        "num_instances": num_instances,
        "multi_az": multi_az,
        "on_demand": {"hourly": round(od_hourly, 4), "monthly": round(od_monthly, 2)},
        "ri_1yr": _fmt(ri_1yr, ri_1yr_monthly, od_monthly),
        "ri_3yr": _fmt(ri_3yr, ri_3yr_monthly, od_monthly),
        "dsp_1yr": _fmt_dsp(dsp_entry_1yr, dsp_1yr_monthly, od_monthly),
        "dsp_3yr": _fmt_dsp(dsp_entry_3yr, dsp_3yr_monthly, od_monthly),
        "recommendation": recommendation,
        "notes": notes,
    }


def analyze_instance_live(instance_id: str, region: str) -> dict:
    import boto3

    rds = boto3.client("rds", region_name=region)
    try:
        resp = rds.describe_db_instances(DBInstanceIdentifier=instance_id)
    except Exception as e:
        return {"instance_id": instance_id, "error": str(e)}
    instances = resp.get("DBInstances", [])
    if not instances:
        return {"instance_id": instance_id, "error": "instance not found"}
    inst = instances[0]
    engine = inst.get("Engine", "")
    instance_type = inst.get("DBInstanceClass", "")
    multi_az = inst.get("MultiAZ", False)
    replicas = inst.get("ReadReplicaDBInstanceIdentifiers", [])

    result = build_comparison(
        instance_type=instance_type,
        engine=engine,
        num_instances=1,
        region=region,
        multi_az=multi_az,
    )
    result["instance_id"] = instance_id
    result["engine_version"] = inst.get("EngineVersion", "")
    if replicas:
        result["notes"].append(
            f"Instance has {len(replicas)} read replica(s). "
            "Consider separate RI/DSP for each replica (Single-AZ pricing)."
        )
    return result


def main():
    parser = argparse.ArgumentParser(
        description="RDS RI & Database Savings Plan estimator (read-only)"
    )
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--format", choices=["json"], default="json")
    parser.add_argument("--instance", help="Analyze a single RDS instance by identifier")

    sub = parser.add_subparsers(dest="mode")
    off = sub.add_parser("offline", help="Use user-supplied workload description")
    off.add_argument("--instance-type", required=True, help="e.g., db.r7g.2xlarge")
    off.add_argument("--engine", required=True, choices=["mysql", "mariadb", "postgres"])
    off.add_argument("--num-instances", type=int, default=1)
    off.add_argument("--multi-az", action="store_true")
    # --region and --format are defined on the main parser above; do NOT redefine them
    # here, or the subparser's default silently overrides a value passed before 'offline'.

    args = parser.parse_args()

    if args.mode == "offline":
        result = build_comparison(
            instance_type=args.instance_type,
            engine=args.engine,
            num_instances=args.num_instances,
            region=args.region,
            multi_az=args.multi_az,
        )
        print(json.dumps(result, indent=2, default=str))
        return

    if args.instance:
        result = analyze_instance_live(args.instance, args.region)
        print(json.dumps(result, indent=2, default=str))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
