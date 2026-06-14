"""Aurora Serverless v2 ACU Calculator.

Estimates ACU sizing, costs, and generates provisioned-vs-serverless comparisons.

Pricing & instance data: pulls live from AWS Pricing API + EC2/RDS APIs when
boto3 credentials are available, falls back to static defaults (us-east-1,
static fallback) when offline or credentials are missing.

Usage:
    python acu_calculator.py --help
    python acu_calculator.py estimate --instance db.r6g.xlarge --cpu-p95 35 --cpu-max 72 --storage 500
    python acu_calculator.py estimate --region eu-west-1 --instance db.r6g.2xlarge --cpu-p95 20 --cpu-max 55 --connections 200 --storage 1000 --working-set 12
"""

import argparse
import json
import math
import re
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Static fallback data (us-east-1)
# Used when AWS APIs are unavailable (no credentials, offline, API errors).
# ---------------------------------------------------------------------------
_STATIC_ACU_PRICE_STANDARD = 0.12  # $/ACU-Hr
_STATIC_ACU_PRICE_IO_OPTIMIZED = 0.156  # $/ACU-Hr (30% premium)
_STATIC_STORAGE_STANDARD_PER_GIB = 0.10  # $/GiB-month
_STATIC_STORAGE_IO_OPT_PER_GIB = 0.225  # $/GiB-month
_STATIC_LAST_UPDATED = "2026-03-28"
_STATIC_REGION = "us-east-1"

# Static instance specs: {name: (vcpus, memory_gib, price_per_hour)}
_STATIC_INSTANCE_SPECS = {
    "db.t3.medium": (2, 4, 0.082),
    "db.t3.large": (2, 8, 0.164),
    "db.t4g.medium": (2, 4, 0.073),
    "db.t4g.large": (2, 8, 0.146),
    "db.r5.large": (2, 16, 0.290),
    "db.r5.xlarge": (4, 32, 0.580),
    "db.r5.2xlarge": (8, 64, 1.160),
    "db.r5.4xlarge": (16, 128, 2.320),
    "db.r5.8xlarge": (32, 256, 4.640),
    "db.r5.12xlarge": (48, 384, 6.960),
    "db.r5.16xlarge": (64, 512, 9.280),
    "db.r5.24xlarge": (96, 768, 13.920),
    "db.r6g.large": (2, 16, 0.260),
    "db.r6g.xlarge": (4, 32, 0.519),
    "db.r6g.2xlarge": (8, 64, 1.038),
    "db.r6g.4xlarge": (16, 128, 2.076),
    "db.r6g.8xlarge": (32, 256, 4.152),
    "db.r6g.12xlarge": (48, 384, 6.228),
    "db.r6g.16xlarge": (64, 512, 8.304),
    "db.r7g.large": (2, 16, 0.276),
    "db.r7g.xlarge": (4, 32, 0.553),
    "db.r7g.2xlarge": (8, 64, 1.106),
    "db.r7g.4xlarge": (16, 128, 2.211),
    "db.r7g.8xlarge": (32, 256, 4.422),
    "db.r7g.12xlarge": (48, 384, 6.633),
    "db.r7g.16xlarge": (64, 512, 8.844),
    "db.r8g.large": (2, 16, 0.276),
    "db.r8g.xlarge": (4, 32, 0.552),
    "db.r8g.2xlarge": (8, 64, 1.104),
    "db.r8g.4xlarge": (16, 128, 2.208),
    "db.r8g.8xlarge": (32, 256, 4.416),
    "db.r8g.12xlarge": (48, 384, 6.624),
    "db.r8g.16xlarge": (64, 512, 8.832),
    "db.r8g.24xlarge": (96, 768, 13.248),
    "db.r8g.48xlarge": (192, 1536, 26.496),
}

# ---------------------------------------------------------------------------
# Constants (non-pricing, do not vary by region)
# ---------------------------------------------------------------------------
# Aurora bills storage on actual usage per GiB-month with dynamic resizing —
# there is no fixed minimum billed storage. (No MIN_STORAGE_GIB floor.)
HOURS_PER_MONTH = 730
ACU_MIN = 0.5
ACU_MAX = 256
IO_OPT_COMPUTE_MULTIPLIER = 1.30  # I/O-Optimized compute premium
GIB_PER_ACU = 2.0  # Each ACU provides ~2 GiB of memory

# Instance family -> ACU ratio
ACU_FAMILY_RATIO = {"r": 4, "m": 2, "t": 2, "c": 1, "x": 4}

# AWS region code -> Pricing API "location" name
_REGION_NAMES = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-west-3": "EU (Paris)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-north-1": "EU (Stockholm)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "ca-central-1": "Canada (Central)",
    "sa-east-1": "South America (Sao Paulo)",
}

# ---------------------------------------------------------------------------
# Active pricing & catalog (mutable — overwritten by refresh_pricing())
# ---------------------------------------------------------------------------
ACU_PRICE_STANDARD = _STATIC_ACU_PRICE_STANDARD
ACU_PRICE_IO_OPTIMIZED = _STATIC_ACU_PRICE_IO_OPTIMIZED
STORAGE_STANDARD_PER_GIB = _STATIC_STORAGE_STANDARD_PER_GIB
STORAGE_IO_OPT_PER_GIB = _STATIC_STORAGE_IO_OPT_PER_GIB
INSTANCE_SPECS = dict(_STATIC_INSTANCE_SPECS)

# Tracks where the active data came from
_pricing_source: dict[str, Any] = {
    "source": "static_fallback",
    "region": _STATIC_REGION,
    "last_updated": _STATIC_LAST_UPDATED,
    "details": "Built-in us-east-1 defaults",
}


# ---------------------------------------------------------------------------
# Live AWS API fetchers
# ---------------------------------------------------------------------------


def _fetch_instance_pricing(region: str) -> dict[str, float]:
    """Fetch on-demand hourly pricing for Aurora instances via the Pricing API.

    The Pricing API is only available in us-east-1 and ap-south-1, but returns
    pricing for any region. Queries aurora-mysql (covers all instance types).

    Returns dict: instance_type -> price_per_hour.
    """
    import boto3

    location = _REGION_NAMES.get(region)
    if not location:
        raise ValueError(
            f"Unknown region '{region}'. Supported: {', '.join(sorted(_REGION_NAMES))}"
        )

    pricing = boto3.client("pricing", region_name="us-east-1")
    filters = [
        {"Type": "TERM_MATCH", "Field": "databaseEngine", "Value": "Aurora MySQL"},
        {"Type": "TERM_MATCH", "Field": "location", "Value": location},
        {"Type": "TERM_MATCH", "Field": "deploymentOption", "Value": "Single-AZ"},
        {"Type": "TERM_MATCH", "Field": "termType", "Value": "OnDemand"},
    ]

    prices = {}
    paginator = pricing.get_paginator("get_products")
    for page in paginator.paginate(ServiceCode="AmazonRDS", Filters=filters):
        for item_json in page["PriceList"]:
            item = json.loads(item_json) if isinstance(item_json, str) else item_json
            attrs = item.get("product", {}).get("attributes", {})
            instance_type = attrs.get("instanceType", "")
            if not instance_type.startswith("db."):
                continue
            # Skip I/O-Optimized SKUs
            if "IOOptimized" in attrs.get("usagetype", ""):
                continue
            terms = item.get("terms", {}).get("OnDemand", {})
            for term in terms.values():
                for dim in term.get("priceDimensions", {}).values():
                    try:
                        price = float(dim.get("pricePerUnit", {}).get("USD", "0"))
                    except (ValueError, TypeError):
                        continue
                    if price > 0:
                        prices[instance_type] = price

    return prices


def _fetch_instance_pricing_bulk(region: str) -> dict[str, float]:
    """Fetch on-demand Aurora MySQL pricing from the public AWS Bulk Pricing CSV.

    No IAM credentials required — this is a publicly accessible HTTPS endpoint.
    Used as a fallback when the Pricing API is not accessible (AccessDeniedException).

    Returns dict: instance_type -> price_per_hour (Aurora Standard only).
    """
    import csv
    import io
    import urllib.request

    url = (
        f"https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/"
        f"current/{region}/index.csv"
    )
    req = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        # CSV has metadata rows before the header; find the header row
        raw = resp.read().decode("utf-8")

    # AWS pricing CSVs start with metadata lines (FormatVersion, Disclaimer, etc.)
    # before the actual column header. Find the header row (starts with "SKU").
    lines = raw.splitlines()
    header_idx = 0
    for i, line in enumerate(lines):
        if line.startswith('"SKU"') or line.startswith("SKU"):
            header_idx = i
            break
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    prices = {}
    for row in reader:
        if row.get("Database Engine") != "Aurora MySQL":
            continue
        if row.get("Deployment Option") != "Single-AZ":
            continue
        # On-demand hourly rates only. The CSV also carries Reserved rows
        # (including fixed-fee Quantity rows with values like 2530), which would
        # otherwise overwrite the real hourly price via last-write-wins.
        if row.get("TermType") != "OnDemand" or row.get("Unit") != "Hrs":
            continue
        instance_type = row.get("Instance Type", "")
        if not instance_type.startswith("db."):
            continue
        # Skip I/O-Optimized SKUs. The column is "usageType" (camelCase) in the
        # AWS RDS bulk CSV; I/O-Optimized is encoded there as InstanceUsageIOOptimized:*.
        usage_type = row.get("usageType", "")
        if "IOOptimized" in usage_type:
            continue
        try:
            price = float(row.get("PricePerUnit", "0"))
        except (ValueError, TypeError):
            continue
        if price > 0:
            prices[instance_type] = price

    return prices


def _fetch_acu_and_storage_pricing(region: str) -> dict:
    """Fetch ACU and storage pricing from the Pricing API.

    Returns dict with acu_standard, acu_io_optimized, storage_standard,
    storage_io_optimized keys.
    """
    import boto3

    location = _REGION_NAMES.get(region)
    if not location:
        raise ValueError(f"Unknown region '{region}'")

    pricing = boto3.client("pricing", region_name="us-east-1")
    result = {}

    # ACU pricing
    acu_filters = [
        {"Type": "TERM_MATCH", "Field": "databaseEngine", "Value": "Aurora MySQL"},
        {"Type": "TERM_MATCH", "Field": "location", "Value": location},
        {"Type": "TERM_MATCH", "Field": "termType", "Value": "OnDemand"},
    ]
    paginator = pricing.get_paginator("get_products")
    for page in paginator.paginate(ServiceCode="AmazonRDS", Filters=acu_filters):
        for item_json in page["PriceList"]:
            item = json.loads(item_json) if isinstance(item_json, str) else item_json
            attrs = item.get("product", {}).get("attributes", {})
            usagetype = attrs.get("usagetype", "")
            if "ServerlessV2Usage" in usagetype and "IOOptimized" not in usagetype:
                terms = item.get("terms", {}).get("OnDemand", {})
                for term in terms.values():
                    for dim in term.get("priceDimensions", {}).values():
                        price = float(dim.get("pricePerUnit", {}).get("USD", "0"))
                        if price > 0:
                            result["acu_standard"] = price
                            result["acu_io_optimized"] = round(price * IO_OPT_COMPUTE_MULTIPLIER, 4)

    # Storage pricing
    storage_filters = [
        {"Type": "TERM_MATCH", "Field": "databaseEngine", "Value": "Aurora MySQL"},
        {"Type": "TERM_MATCH", "Field": "location", "Value": location},
        {"Type": "TERM_MATCH", "Field": "termType", "Value": "OnDemand"},
        {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Database Storage"},
    ]
    for page in paginator.paginate(ServiceCode="AmazonRDS", Filters=storage_filters):
        for item_json in page["PriceList"]:
            item = json.loads(item_json) if isinstance(item_json, str) else item_json
            attrs = item.get("product", {}).get("attributes", {})
            usagetype = attrs.get("usagetype", "")
            terms = item.get("terms", {}).get("OnDemand", {})
            for term in terms.values():
                for dim in term.get("priceDimensions", {}).values():
                    price = float(dim.get("pricePerUnit", {}).get("USD", "0"))
                    if price <= 0:
                        continue
                    if "IOOptimized" in usagetype:
                        result["storage_io_optimized"] = price
                    elif "Aurora:StorageUsage" in usagetype:
                        result["storage_standard"] = price

    return result


def _fetch_instance_catalog(region: str) -> dict[str, tuple]:
    """Discover Aurora instance types via RDS + EC2 APIs.

    Returns dict: instance_type -> (vcpus, memory_gib, 0.0).
    Price is 0.0 here; caller merges with pricing data.
    """
    import boto3

    rds = boto3.client("rds", region_name=region)
    instances = {}

    for engine in ("aurora-mysql",):
        try:
            paginator = rds.get_paginator("describe_orderable_db_instance_options")
            for page in paginator.paginate(Engine=engine):
                for opt in page.get("OrderableDBInstanceOptions", []):
                    name = opt.get("DBInstanceClass", "")
                    if name.startswith("db.") and name != "db.serverless":
                        instances[name] = {"vcpus": 0, "memory_gib": 0.0}
        except Exception:
            pass

    if not instances:
        return {}

    # Get vCPU/memory from EC2 describe_instance_types
    ec2 = boto3.client("ec2", region_name=region)
    ec2_names = [name.replace("db.", "", 1) for name in instances]

    for i in range(0, len(ec2_names), 100):
        batch = ec2_names[i : i + 100]
        try:
            resp = ec2.describe_instance_types(InstanceTypes=batch)
            for it in resp.get("InstanceTypes", []):
                db_name = "db." + it["InstanceType"]
                if db_name in instances:
                    instances[db_name]["vcpus"] = it.get("VCpuInfo", {}).get("DefaultVCpus", 0)
                    instances[db_name]["memory_gib"] = (
                        it.get("MemoryInfo", {}).get("SizeInMiB", 0) / 1024
                    )
        except Exception:
            # Try one by one for families EC2 doesn't know about
            for ec2_name in batch:
                try:
                    resp = ec2.describe_instance_types(InstanceTypes=[ec2_name])
                    for it in resp.get("InstanceTypes", []):
                        db_name = "db." + it["InstanceType"]
                        if db_name in instances:
                            instances[db_name]["vcpus"] = it.get("VCpuInfo", {}).get(
                                "DefaultVCpus", 0
                            )
                            instances[db_name]["memory_gib"] = (
                                it.get("MemoryInfo", {}).get("SizeInMiB", 0) / 1024
                            )
                except Exception:
                    pass

    # Convert to tuple format, drop entries missing vCPU/memory
    catalog = {}
    for name, spec in instances.items():
        if spec["vcpus"] > 0 and spec["memory_gib"] > 0:
            catalog[name] = (spec["vcpus"], spec["memory_gib"], 0.0)

    return catalog


def refresh_pricing(region: str = "us-east-1") -> dict:
    """Refresh all pricing and instance data from AWS APIs.

    Tries live APIs first. On any failure, falls back to static defaults
    and reports what succeeded and what didn't.

    Returns a summary dict describing the pricing source.
    """
    global ACU_PRICE_STANDARD, ACU_PRICE_IO_OPTIMIZED
    global STORAGE_STANDARD_PER_GIB, STORAGE_IO_OPT_PER_GIB
    global INSTANCE_SPECS, _pricing_source

    errors = []
    live_instances = 0
    live_prices = 0
    live_acu = False

    # 1. Try to fetch the instance catalog (RDS + EC2)
    api_catalog = {}
    try:
        api_catalog = _fetch_instance_catalog(region)
        live_instances = len(api_catalog)
    except Exception as e:
        errors.append(f"Instance catalog: {e}")

    # 2. Try to fetch instance pricing (Pricing API, then public bulk CSV fallback)
    instance_prices = {}
    try:
        instance_prices = _fetch_instance_pricing(region)
        live_prices = len(instance_prices)
    except Exception as e:
        errors.append(f"Instance pricing (API): {e}")
        # Fallback: public bulk pricing CSV (no IAM credentials needed)
        try:
            instance_prices = _fetch_instance_pricing_bulk(region)
            live_prices = len(instance_prices)
            if live_prices > 0:
                errors[-1] += " [recovered via bulk pricing CSV]"
        except Exception as e2:
            errors.append(f"Instance pricing (bulk CSV): {e2}")

    # 3. Try to fetch ACU + storage pricing
    try:
        acu_data = _fetch_acu_and_storage_pricing(region)
        if "acu_standard" in acu_data:
            ACU_PRICE_STANDARD = acu_data["acu_standard"]
            ACU_PRICE_IO_OPTIMIZED = acu_data.get(
                "acu_io_optimized",
                round(acu_data["acu_standard"] * IO_OPT_COMPUTE_MULTIPLIER, 4),
            )
            live_acu = True
        if "storage_standard" in acu_data:
            STORAGE_STANDARD_PER_GIB = acu_data["storage_standard"]
        if "storage_io_optimized" in acu_data:
            STORAGE_IO_OPT_PER_GIB = acu_data["storage_io_optimized"]
    except Exception as e:
        errors.append(f"ACU/storage pricing: {e}")

    # 4. Merge: start with static, overlay API catalog, overlay prices
    merged = dict(_STATIC_INSTANCE_SPECS)

    for name, (vcpus, mem, _) in api_catalog.items():
        price = instance_prices.get(name, 0.0)
        # If API didn't return a price, keep static price if we have one
        if price == 0.0 and name in _STATIC_INSTANCE_SPECS:
            price = _STATIC_INSTANCE_SPECS[name][2]
        merged[name] = (vcpus, mem, price)

    # For instances in static but not in API catalog, update price if available
    for name in _STATIC_INSTANCE_SPECS:
        if name not in api_catalog and name in instance_prices:
            v, m, _ = _STATIC_INSTANCE_SPECS[name]
            merged[name] = (v, m, instance_prices[name])

    INSTANCE_SPECS = merged

    # Determine source description
    if not errors:
        source = "live"
        details = (
            f"Live AWS APIs ({region}): {live_instances} instance types, "
            f"{live_prices} prices, ACU=${ACU_PRICE_STANDARD}/hr"
        )
    elif live_prices > 0 or live_acu:
        source = "partial_live"
        details = (
            f"Partial live data ({region}): {live_instances} instances, "
            f"{live_prices} prices. Gaps filled from static defaults. "
            f"Errors: {'; '.join(errors)}"
        )
    else:
        # Full fallback
        source = "static_fallback"
        INSTANCE_SPECS = dict(_STATIC_INSTANCE_SPECS)
        ACU_PRICE_STANDARD = _STATIC_ACU_PRICE_STANDARD
        ACU_PRICE_IO_OPTIMIZED = _STATIC_ACU_PRICE_IO_OPTIMIZED
        STORAGE_STANDARD_PER_GIB = _STATIC_STORAGE_STANDARD_PER_GIB
        STORAGE_IO_OPT_PER_GIB = _STATIC_STORAGE_IO_OPT_PER_GIB
        details = (
            f"Static fallback (us-east-1, {_STATIC_LAST_UPDATED}). "
            f"Live fetch failed: {'; '.join(errors)}"
        )

    _pricing_source = {
        "source": source,
        "region": region,
        "last_updated": _STATIC_LAST_UPDATED if source == "static_fallback" else "now",
        "details": details,
        "instance_count": len(INSTANCE_SPECS),
        "acu_price_standard": ACU_PRICE_STANDARD,
        "storage_price_standard": STORAGE_STANDARD_PER_GIB,
    }
    if errors:
        _pricing_source["errors"] = errors

    return _pricing_source


def get_pricing_source() -> dict:
    """Return metadata about the active pricing data source."""
    return dict(_pricing_source)


# ---------------------------------------------------------------------------
# Core calculation functions
# ---------------------------------------------------------------------------


def round_up_to_half(value: float) -> float:
    """Round up to nearest 0.5 ACU."""
    return math.ceil(value * 2) / 2


def family_ratio(instance_type: str) -> int:
    """Get ACU ratio for an instance family."""
    m = re.match(r"db\.([a-z])", instance_type)
    if m:
        return ACU_FAMILY_RATIO.get(m.group(1), 4)
    return 4


def get_instance_specs(instance_type: str) -> tuple:
    """Get (vcpus, memory_gib, price_per_hour) for an instance type."""
    if instance_type in INSTANCE_SPECS:
        return INSTANCE_SPECS[instance_type]
    raise ValueError(
        f"Unknown instance type: {instance_type}. "
        f"Supported: {', '.join(sorted(INSTANCE_SPECS.keys()))}"
    )


def estimate_acu(
    cpu_p95: float,
    cpu_max: float,
    vcpus: int,
    instance_type: str,
    cpu_avg: float = 0,
) -> dict:
    """Estimate ACU needed for a workload.

    Returns dict with typical ACU, min/max recommendations, and breakdown.
    """
    ratio = family_ratio(instance_type)

    # Typical ACU: weighted 95/5 blend
    weighted_cpu = (cpu_p95 * 0.95 + cpu_max * 0.05) / 100
    raw_typical = weighted_cpu * vcpus * ratio
    typical_acu = round_up_to_half(raw_typical)
    typical_acu = max(ACU_MIN, min(typical_acu, ACU_MAX))

    # Peak ACU
    raw_peak = (cpu_max / 100) * vcpus * ratio
    peak_acu = round_up_to_half(raw_peak)

    # Average ACU (for min recommendation)
    if cpu_avg > 0:
        avg_acu = round_up_to_half((cpu_avg / 100) * vcpus * ratio)
    else:
        # Estimate average as 60% of P95 when not provided
        avg_acu = round_up_to_half((cpu_p95 * 0.6 / 100) * vcpus * ratio)

    exceeds_capacity = raw_typical > ACU_MAX or raw_peak > ACU_MAX

    return {
        "typical_acu": typical_acu,
        "peak_acu": peak_acu,
        "avg_acu": avg_acu,
        "raw_typical": round(raw_typical, 2),
        "raw_peak": round(raw_peak, 2),
        "family_ratio": ratio,
        "exceeds_capacity": exceeds_capacity,
    }


def recommend_min_max(
    acu_result: dict,
    connections: int = 0,
    working_set_gib: float = 0,
) -> dict:
    """Recommend min/max ACU settings."""
    avg_acu = acu_result["avg_acu"]
    typical_acu = acu_result["typical_acu"]
    peak_acu = acu_result["peak_acu"]

    # Connection floor
    conn_mem_gib = connections * 10 / 1024  # ~10 MB per connection average
    conn_acu = round_up_to_half(conn_mem_gib / GIB_PER_ACU)

    # Memory floor (advisory — working set)
    mem_acu = round_up_to_half(working_set_gib / GIB_PER_ACU) if working_set_gib > 0 else 0

    # Min: based on avg CPU + connection floor (uncapped first, so we can detect
    # a baseline that already exceeds serverless limits).
    raw_min = max(ACU_MIN, avg_acu, conn_acu)

    # Max: peak + 30% headroom, at least 1.5x typical
    recommended_max = round_up_to_half(peak_acu * 1.3)
    recommended_max = max(recommended_max, round_up_to_half(typical_acu * 1.5))
    recommended_max = min(recommended_max, ACU_MAX)

    # The workload's baseline doesn't fit a single serverless instance when the
    # uncapped min exceeds the ACU ceiling or the (capped) max — flag it, mirroring
    # estimate_acu's exceeds_capacity.
    exceeds_capacity = raw_min > ACU_MAX or raw_min > recommended_max

    # Cap min at ACU_MAX and enforce the invariant: min must never exceed max.
    recommended_min = min(raw_min, ACU_MAX, recommended_max)

    # Memory advisory
    memory_advisory = None
    if mem_acu > recommended_min:
        memory_advisory = (
            f"Working set needs {mem_acu} ACU ({working_set_gib:.1f} GiB / "
            f"{GIB_PER_ACU} GiB per ACU). Your min ACU ({recommended_min}) is below this. "
            f"Setting min to {mem_acu} ACU keeps the working set cached and avoids "
            f"cold-cache I/O penalties on scale-up. Trade-off: higher baseline cost."
        )

    return {
        "recommended_min": recommended_min,
        "recommended_max": recommended_max,
        "connection_floor_acu": conn_acu,
        "memory_floor_acu": mem_acu,
        "memory_advisory": memory_advisory,
        "exceeds_capacity": exceeds_capacity,
    }


def calculate_costs(
    typical_acu: float,
    min_acu: float,
    max_acu: float,
    storage_gib: float,
    provisioned_instance: str,
    num_provisioned_instances: int = 1,
    exceeds_capacity: bool = False,
) -> dict:
    """Calculate and compare serverless vs provisioned costs."""
    _, _, price_per_hour = get_instance_specs(provisioned_instance)

    # Provisioned cost
    prov_compute = price_per_hour * HOURS_PER_MONTH * num_provisioned_instances
    prov_storage = storage_gib * STORAGE_STANDARD_PER_GIB
    prov_total = prov_compute + prov_storage

    # Serverless cost (typical steady-state)
    sv_compute = typical_acu * ACU_PRICE_STANDARD * HOURS_PER_MONTH
    sv_storage = storage_gib * STORAGE_STANDARD_PER_GIB
    sv_total = sv_compute + sv_storage

    # Serverless cost range
    sv_low = min_acu * ACU_PRICE_STANDARD * HOURS_PER_MONTH + sv_storage
    sv_high = max_acu * ACU_PRICE_STANDARD * HOURS_PER_MONTH + sv_storage

    # Savings
    savings = prov_total - sv_total
    savings_pct = (savings / prov_total * 100) if prov_total > 0 else 0

    # Recommendation logic
    if exceeds_capacity:
        recommendation = "not_recommended"
        reason = (
            f"Workload's baseline/peak demand exceeds the {ACU_MAX:.0f} ACU serverless "
            f"maximum. Stay with provisioned or split across multiple serverless clusters."
        )
    elif savings_pct > 10 and sv_high <= prov_total * 2:
        recommendation = "recommended"
        reason = (
            f"Serverless saves ${savings:.0f}/mo ({savings_pct:.0f}%) vs provisioned. "
            f"Cost range: ${sv_low:.0f}–${sv_high:.0f}/mo."
        )
    elif savings_pct > 10:
        recommendation = "consider"
        reason = (
            f"Typical cost is lower (${sv_total:.0f} vs ${prov_total:.0f}/mo), but "
            f"peak cost could reach ${sv_high:.0f}/mo. Variable workloads benefit; "
            f"sustained peaks may not."
        )
    elif savings_pct > -5:
        recommendation = "consider"
        reason = (
            f"Similar cost (${sv_total:.0f} vs ${prov_total:.0f}/mo). Choose serverless "
            f"for auto-scaling and zero management overhead."
        )
    elif savings_pct > -30:
        recommendation = "more_expensive"
        reason = (
            f"Serverless costs ${abs(savings):.0f}/mo more than provisioned "
            f"(${sv_total:.0f} vs ${prov_total:.0f}/mo)."
        )
    else:
        recommendation = "not_recommended"
        reason = (
            f"Serverless at ${sv_total:.0f}/mo is {abs(savings_pct):.0f}% more expensive "
            f"than provisioned at ${prov_total:.0f}/mo. Sustained workloads are cheaper "
            f"on provisioned instances."
        )

    return {
        "provisioned": {
            "instance_type": provisioned_instance,
            "num_instances": num_provisioned_instances,
            "compute_monthly": round(prov_compute, 2),
            "storage_monthly": round(prov_storage, 2),
            "total_monthly": round(prov_total, 2),
        },
        "serverless": {
            "typical_acu": typical_acu,
            "compute_monthly": round(sv_compute, 2),
            "storage_monthly": round(sv_storage, 2),
            "total_monthly": round(sv_total, 2),
            "cost_range": {
                "low": round(sv_low, 2),
                "typical": round(sv_total, 2),
                "high": round(sv_high, 2),
            },
        },
        "savings_monthly": round(savings, 2),
        "savings_pct": round(savings_pct, 1),
        "recommendation": recommendation,
        "reason": reason,
    }


def format_table(result: dict) -> str:
    """Format result as a readable text table."""
    lines = []
    source = result.get("pricing_source", _pricing_source)
    tag = source.get("source", "static_fallback").replace("_", " ").title()
    lines.append("=" * 65)
    lines.append("  Aurora Serverless v2 — ACU Estimate & Cost Comparison")
    lines.append(f"  Pricing: {tag} ({source.get('region', '?')})")
    lines.append("=" * 65)

    # ACU settings
    acu = result["acu_settings"]
    lines.append("")
    lines.append("  ACU Configuration")
    lines.append("  " + "-" * 45)
    lines.append(f"  Recommended Min ACU:  {acu['recommended_min']:.1f}")
    lines.append(f"  Recommended Max ACU:  {acu['recommended_max']:.1f}")
    lines.append(f"  Typical ACU:          {acu['typical_acu']:.1f}")
    lines.append(f"  Peak ACU:             {acu['peak_acu']:.1f}")
    if acu.get("connection_floor_acu", 0) > 0:
        lines.append(f"  Connection floor:     {acu['connection_floor_acu']:.1f} ACU")
    if acu.get("memory_floor_acu", 0) > 0:
        lines.append(f"  Memory floor:         {acu['memory_floor_acu']:.1f} ACU (advisory)")
    if acu.get("memory_advisory"):
        lines.append(f"  NOTE: {acu['memory_advisory']}")

    # Cost comparison
    costs = result["cost_comparison"]
    prov = costs["provisioned"]
    sv = costs["serverless"]
    lines.append("")
    lines.append("  Monthly Cost Comparison")
    lines.append("  " + "-" * 45)
    lines.append(f"  {'':30s} {'Provisioned':>14s} {'Serverless':>14s}")
    lines.append(
        f"  {'Compute':30s} {'$'+str(prov['compute_monthly']):>14s} {'$'+str(sv['compute_monthly']):>14s}"
    )
    lines.append(
        f"  {'Storage':30s} {'$'+str(prov['storage_monthly']):>14s} {'$'+str(sv['storage_monthly']):>14s}"
    )
    lines.append(
        f"  {'Total':30s} {'$'+str(prov['total_monthly']):>14s} {'$'+str(sv['total_monthly']):>14s}"
    )
    lines.append("")
    lines.append(
        f"  Serverless cost range: ${sv['cost_range']['low']:.0f} – ${sv['cost_range']['high']:.0f}/mo"
    )
    lines.append(f"  Savings: ${costs['savings_monthly']:.0f}/mo ({costs['savings_pct']:.0f}%)")

    # Recommendation
    lines.append("")
    lines.append(f"  Recommendation: {costs['recommendation'].upper()}")
    lines.append(f"  {costs['reason']}")
    lines.append("")
    lines.append("=" * 65)

    return "\n".join(lines)


def run_estimate(args) -> dict:
    """Run full estimation from CLI arguments."""
    vcpus, memory_gib, price = get_instance_specs(args.instance)

    acu_result = estimate_acu(
        cpu_p95=args.cpu_p95,
        cpu_max=args.cpu_max,
        vcpus=vcpus,
        instance_type=args.instance,
        cpu_avg=args.cpu_avg,
    )

    min_max = recommend_min_max(
        acu_result,
        connections=args.connections,
        working_set_gib=args.working_set,
    )

    # Workload overflows serverless if EITHER signal trips: estimate_acu's
    # typical/peak check, or recommend_min_max's baseline-min check.
    exceeds_capacity = acu_result["exceeds_capacity"] or min_max["exceeds_capacity"]

    costs = calculate_costs(
        typical_acu=acu_result["typical_acu"],
        min_acu=min_max["recommended_min"],
        max_acu=min_max["recommended_max"],
        storage_gib=args.storage,
        provisioned_instance=args.instance,
        num_provisioned_instances=args.num_instances,
        exceeds_capacity=exceeds_capacity,
    )

    return {
        "input": {
            "instance_type": args.instance,
            "vcpus": vcpus,
            "memory_gib": memory_gib,
            "cpu_p95": args.cpu_p95,
            "cpu_max": args.cpu_max,
            "cpu_avg": args.cpu_avg,
            "connections": args.connections,
            "working_set_gib": args.working_set,
            "storage_gib": args.storage,
            "num_instances": args.num_instances,
        },
        "acu_settings": {
            "recommended_min": min_max["recommended_min"],
            "recommended_max": min_max["recommended_max"],
            "typical_acu": acu_result["typical_acu"],
            "peak_acu": acu_result["peak_acu"],
            "avg_acu": acu_result["avg_acu"],
            "connection_floor_acu": min_max["connection_floor_acu"],
            "memory_floor_acu": min_max["memory_floor_acu"],
            "memory_advisory": min_max["memory_advisory"],
            "exceeds_capacity": exceeds_capacity,
        },
        "cost_comparison": costs,
        "pricing_source": get_pricing_source(),
    }


def main():
    # Shared flags accepted both before the subcommand and after it (so e.g.
    # `... estimate --region X --offline` and `... --region X estimate` both work).
    # Defaults are SUPPRESSed here so a subparser copy does NOT re-apply its own
    # default and clobber a value the user passed before the subcommand; the real
    # defaults are resolved once, after parsing, below.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--region",
        default=argparse.SUPPRESS,
        help="AWS region for pricing (default: us-east-1). "
        "Live pricing requires boto3 + AWS credentials.",
    )
    common.add_argument(
        "--offline",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Skip live API calls, use static fallback data only.",
    )

    parser = argparse.ArgumentParser(
        description="Aurora Serverless v2 ACU Calculator", parents=[common]
    )
    sub = parser.add_subparsers(dest="command")

    # estimate command
    est = sub.add_parser("estimate", parents=[common], help="Estimate ACU sizing and compare costs")
    est.add_argument(
        "--instance", required=True, help="Current provisioned instance type (e.g., db.r6g.xlarge)"
    )
    est.add_argument("--cpu-p95", type=float, required=True, help="P95 CPU utilization (0-100)")
    est.add_argument("--cpu-max", type=float, required=True, help="Maximum CPU utilization (0-100)")
    est.add_argument(
        "--cpu-avg",
        type=float,
        default=0,
        help="Average CPU utilization (0-100), estimated if omitted",
    )
    est.add_argument("--connections", type=int, default=0, help="Peak connection count")
    est.add_argument("--working-set", type=float, default=0, help="Working set size in GiB")
    est.add_argument("--storage", type=float, default=10, help="Storage in GiB")
    est.add_argument(
        "--num-instances",
        type=int,
        default=1,
        help="Number of provisioned instances (for cost comparison)",
    )
    est.add_argument("--format", choices=["json", "table"], default="json", help="Output format")

    # list-instances command
    sub.add_parser(
        "list-instances",
        parents=[common],
        help="List supported instance types with specs and pricing",
    )

    # pricing-source command
    sub.add_parser(
        "pricing-source", parents=[common], help="Show where pricing data is coming from"
    )

    args = parser.parse_args()

    # Resolve shared-flag defaults once (they were SUPPRESSed on both the main and
    # subparsers so neither position clobbers the other; an explicit flag in either
    # position lands in the namespace, otherwise we apply the default here).
    if not hasattr(args, "region"):
        args.region = "us-east-1"
    if not hasattr(args, "offline"):
        args.offline = False

    # Refresh pricing (live or offline)
    if not args.offline:
        source = refresh_pricing(region=args.region)
        if args.command != "pricing-source":
            # Brief status line to stderr so it doesn't pollute JSON output
            tag = (
                "LIVE"
                if source["source"] == "live"
                else ("PARTIAL" if source["source"] == "partial_live" else "STATIC")
            )
            print(
                f"[Pricing: {tag} — {source['region']}, "
                f"{source['instance_count']} instances, "
                f"ACU=${source['acu_price_standard']}/hr]",
                file=sys.stderr,
            )

    if args.command == "estimate":
        result = run_estimate(args)
        if args.format == "table":
            print(format_table(result))
        else:
            print(json.dumps(result, indent=2))

    elif args.command == "list-instances":
        source = get_pricing_source()
        print(f"Pricing source: {source['source']} ({source['region']})")
        print(f"{'Instance Type':<25s} {'vCPUs':>6s} {'Memory':>8s} {'$/hr':>8s} {'$/mo':>10s}")
        print("-" * 62)
        for name in sorted(INSTANCE_SPECS.keys()):
            v, m, p = INSTANCE_SPECS[name]
            print(f"{name:<25s} {v:>6d} {m:>6.0f} GiB {p:>8.3f} {p*730:>10.2f}")
        print(f"\nTotal: {len(INSTANCE_SPECS)} instance types")

    elif args.command == "pricing-source":
        print(json.dumps(get_pricing_source(), indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
