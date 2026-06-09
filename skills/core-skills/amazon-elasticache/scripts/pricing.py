"""
ElastiCache pricing loader.

Fetches live pricing from the AWS Bulk Pricing API (public, no auth required).
Caches locally to avoid repeated downloads. Refreshes if cache is older than 7 days.

Source: https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonElastiCache/current/index.json

Also accepts an optional local CSV for offline or override use.

Supports On-Demand and Reserved Node pricing (1-year and 3-year terms with
No Upfront, Partial Upfront, and All Upfront purchase options). Reserved pricing
is extracted from the bulk pricing JSON terms.Reserved section.
"""
import csv
import json
import os
import sys
import time
import urllib.request
from typing import Dict, Optional, Tuple

BULK_PRICING_URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonElastiCache/current/index.json"
CACHE_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 days
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pricing_cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "elasticache_pricing.json")


def _cache_is_fresh() -> bool:
    """Check if local cache exists and is younger than CACHE_MAX_AGE_SECONDS."""
    if not os.path.exists(_CACHE_FILE):
        return False
    age = time.time() - os.path.getmtime(_CACHE_FILE)
    return age < CACHE_MAX_AGE_SECONDS


def _fetch_and_cache() -> dict:
    """Fetch bulk pricing JSON from AWS and cache locally."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    print("Fetching live ElastiCache pricing from AWS...", file=sys.stderr)
    try:
        req = urllib.request.Request(BULK_PRICING_URL)
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
    except Exception as e:
        raise RuntimeError(
            "Failed to fetch pricing from {}. Error: {}. "
            "Check network connectivity or provide a local pricing CSV.".format(BULK_PRICING_URL, e)
        )

    data = json.loads(raw)
    parsed = _parse_bulk_pricing(data)
    parsed["fetched_at"] = time.time()

    with open(_CACHE_FILE, "w") as f:
        json.dump(parsed, f)

    print("  Pricing cached at: {}".format(_CACHE_FILE), file=sys.stderr)
    return parsed


def _load_cache() -> dict:
    """Load parsed pricing from local cache."""
    with open(_CACHE_FILE, "r") as f:
        return json.load(f)


def _parse_bulk_pricing(data: dict) -> dict:
    """Parse the AWS bulk pricing JSON into our compact format.

    Extracts:
      - On-demand node-based hourly rates by (region, instance_type, engine)
      - Reserved node-based rates by (region, instance_type, engine, lease, purchase_option)
      - Serverless storage rates by (region, engine)
      - Serverless ECPU rates by (region, engine)
      - Extended Support surcharges by (region, engine, year)
    """
    products = data.get("products", {})
    terms = data.get("terms", {}).get("OnDemand", {})
    reserved_terms = data.get("terms", {}).get("Reserved", {})

    node_pricing = {}       # "region|instance_type|engine" -> $/hr
    serverless_storage = {} # "region|engine" -> $/GB-hr
    serverless_ecpu = {}    # "region|engine" -> $/ECPU
    extended_support = {}   # "region|instance_type|engine|year" -> $/node-hr
    reserved_pricing = {}   # "region|instance_type|engine|lease|purchase" -> {"hourly": $, "upfront": $}
    node_memory = {}        # "instance_type" -> GB (float)

    for sku, product in products.items():
        attrs = product.get("attributes", {})
        family = product.get("productFamily", "")
        region = attrs.get("regionCode", "")
        if not region:
            continue
        # Skip Outpost and non-standard location types
        if attrs.get("locationType", "") != "AWS Region":
            continue

        # Get the on-demand price and unit for this SKU
        price_info = _get_od_price_with_unit(sku, terms)
        if price_info is None:
            continue
        price_per_unit, unit = price_info
        if price_per_unit <= 0:
            continue

        if family == "Cache Instance":
            instance_type = attrs.get("instanceType", "")
            engine = _normalize_engine(attrs.get("cacheEngine", ""))
            usagetype = attrs.get("usagetype", "")

            # Extended Support entries live under "Cache Instance" family
            # but have "ExtendedSupport" in the usagetype
            if "ExtendedSupport" in usagetype:
                if not engine or not instance_type or unit != "Hrs":
                    continue
                years = _parse_extended_support_years(usagetype)
                for year in years:
                    key = "{}|{}|{}|{}".format(region, instance_type, engine, year)
                    extended_support[key] = price_per_unit
            elif instance_type and engine and unit == "Hrs":
                key = "{}|{}|{}".format(region, instance_type, engine)
                node_pricing[key] = price_per_unit
                # Extract memory from product attributes (e.g., "103.68 GiB")
                if instance_type not in node_memory:
                    mem_str = attrs.get("memory", "")
                    mem_gb = _parse_memory_gib(mem_str)
                    if mem_gb > 0:
                        node_memory[instance_type] = mem_gb

        elif family == "ElastiCache Serverless":
            engine = _normalize_engine(attrs.get("cacheEngine", ""))
            operation = attrs.get("operation", "")
            usagetype = attrs.get("usagetype", "")
            if "Snapshot" in operation or "Backup" in usagetype:
                continue
            if not engine:
                continue
            key = "{}|{}".format(region, engine)
            unit_lower = unit.lower()
            if "gb-hour" in unit_lower or "CachedData" in usagetype:
                serverless_storage[key] = price_per_unit
            elif "processingunit" in unit_lower or "ProcessingUnits" in usagetype:
                serverless_ecpu[key] = price_per_unit

    # Parse Reserved terms for node-based instances
    _valid_purchase_options = {"No Upfront", "Partial Upfront", "All Upfront"}
    for sku, offers in reserved_terms.items():
        product = products.get(sku)
        if not product or product.get("productFamily") != "Cache Instance":
            continue
        attrs = product.get("attributes", {})
        if attrs.get("locationType", "") != "AWS Region":
            continue
        if "ExtendedSupport" in attrs.get("usagetype", ""):
            continue
        region = attrs.get("regionCode", "")
        instance_type = attrs.get("instanceType", "")
        engine = _normalize_engine(attrs.get("cacheEngine", ""))
        if not (region and instance_type and engine):
            continue

        for offer_id, offer in offers.items():
            ta = offer.get("termAttributes", {})
            purchase_option = ta.get("PurchaseOption", "")
            if purchase_option not in _valid_purchase_options:
                continue  # skip legacy "Heavy Utilization"
            lease = ta.get("LeaseContractLength", "")  # "1yr" or "3yr"

            hourly = 0.0
            upfront = 0.0
            for dim in offer.get("priceDimensions", {}).values():
                try:
                    price = float(dim.get("pricePerUnit", {}).get("USD", "0"))
                except (ValueError, TypeError):
                    continue
                unit = dim.get("unit", "")
                if unit == "Hrs":
                    hourly = price
                elif unit == "Quantity":
                    upfront = price

            key = "{}|{}|{}|{}|{}".format(
                region, instance_type, engine, lease, purchase_option
            )
            reserved_pricing[key] = {"hourly": hourly, "upfront": upfront}

    return {
        "node_pricing": node_pricing,
        "serverless_storage": serverless_storage,
        "serverless_ecpu": serverless_ecpu,
        "extended_support": extended_support,
        "reserved_pricing": reserved_pricing,
        "node_memory": node_memory,
    }


def _get_od_price_with_unit(sku: str, terms: dict) -> Optional[Tuple[float, str]]:
    """Extract on-demand price and unit for a SKU from the terms section."""
    sku_terms = terms.get(sku, {})
    for offer in sku_terms.values():
        dimensions = offer.get("priceDimensions", {})
        for dim in dimensions.values():
            try:
                price = float(dim.get("pricePerUnit", {}).get("USD", "0"))
                unit = dim.get("unit", "")
                return (price, unit)
            except (ValueError, TypeError):
                continue
    return None


def _parse_extended_support_years(usagetype: str) -> list:
    """Extract year tiers from an Extended Support usagetype string.

    AWS usagetype format:
      - "USE1-ExtendedSupportYr1_Yr2-NodeUsage:cache.r7g.large" -> years 1 and 2 (same rate)
      - "USE1-ExtendedSupportYr3-NodeUsage:cache.r7g.large" -> year 3+

    Returns a list of year strings, e.g. ["1", "2"] or ["3"].
    """
    ut = usagetype.lower()
    if "yr1_yr2" in ut:
        return ["1", "2"]
    if "yr3" in ut:
        return ["3"]
    if "yr1" in ut and "yr2" not in ut:
        return ["1"]
    if "yr2" in ut and "yr1" not in ut:
        return ["2"]
    # Fallback: generic extended support mention without year
    if "extendedsupport" in ut.replace("-", "").replace("_", ""):
        return ["1"]
    return []


def _normalize_engine(engine_str: str) -> str:
    """Normalize engine name from bulk pricing to our standard names."""
    eng = engine_str.lower().strip()
    if "valkey" in eng:
        return "valkey"
    if "redis" in eng:
        return "redis"
    if "memcached" in eng:
        return "memcached"
    return eng


def _parse_memory_gib(mem_str: str) -> float:
    """Parse memory string like '103.68 GiB' into a float GB value."""
    if not mem_str:
        return 0.0
    try:
        parts = mem_str.strip().split()
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


class PricingLoader:
    """Load and look up ElastiCache pricing.

    Priority:
      1. Local CSV (if provided) - for offline or override use
      2. Live AWS bulk pricing (fetched and cached locally for 7 days)
    """

    def __init__(self, pricing_csv: Optional[str] = None):
        self._serverless_storage: Dict[Tuple[str, str], float] = {}
        self._serverless_ecpu: Dict[Tuple[str, str], float] = {}
        self._node_od: Dict[Tuple[str, str, str], float] = {}
        self._extended_support: Dict[Tuple[str, str, str, str], float] = {}  # (region, itype, engine, year)
        self._reserved: Dict[Tuple[str, str, str, str, str], dict] = {}  # (region, itype, engine, lease, purchase) -> {"hourly", "upfront"}
        self._node_memory: Dict[str, float] = {}  # instance_type -> GB

        if pricing_csv and os.path.exists(pricing_csv):
            self._load_csv(pricing_csv)
        elif pricing_csv:
            raise FileNotFoundError(
                "Pricing CSV not found: {}".format(pricing_csv)
            )
        else:
            self._load_live()

    def _load_live(self):
        """Load pricing from AWS bulk pricing (cached locally)."""
        if _cache_is_fresh():
            data = _load_cache()
        else:
            data = _fetch_and_cache()

        for key, price in data.get("node_pricing", {}).items():
            parts = key.split("|")
            if len(parts) == 3:
                region, itype, engine = parts
                self._node_od[(region, itype, engine)] = price

        for key, price in data.get("serverless_storage", {}).items():
            parts = key.split("|")
            if len(parts) == 2:
                region, engine = parts
                self._serverless_storage[(region, engine)] = price

        for key, price in data.get("serverless_ecpu", {}).items():
            parts = key.split("|")
            if len(parts) == 2:
                region, engine = parts
                self._serverless_ecpu[(region, engine)] = price

        for key, price in data.get("extended_support", {}).items():
            parts = key.split("|")
            if len(parts) == 4:
                region, itype, engine, year = parts
                self._extended_support[(region, itype, engine, year)] = price

        for key, price_info in data.get("reserved_pricing", {}).items():
            parts = key.split("|")
            if len(parts) == 5:
                region, itype, engine, lease, purchase = parts
                self._reserved[(region, itype, engine, lease, purchase)] = price_info

        self._node_memory = data.get("node_memory", {})

    def _load_csv(self, path: str):
        """Load pricing from a local CSV."""
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                family = row.get("Product Family", "")
                region = row.get("Region Code", "")
                engine = row.get("Cache Engine", "").lower()
                term = row.get("TermType", "")
                try:
                    price = float(row.get("PricePerUnit", "0"))
                except (ValueError, TypeError):
                    continue
                if price <= 0 or not region:
                    continue

                if family == "Cache Instance" and term == "OnDemand":
                    itype = row.get("Instance Type", "")
                    if itype and row.get("Unit") == "Hrs":
                        self._node_od[(region, itype, engine)] = price

                elif family == "ElastiCache Serverless":
                    unit = row.get("Unit", "")
                    operation = row.get("Operation", row.get("operation", ""))
                    if "Snapshot" in operation or unit == "GB-months":
                        continue
                    unit_lower = unit.lower()
                    if "gb-hour" in unit_lower:
                        self._serverless_storage[(region, engine)] = price
                    elif "processingunit" in unit_lower:
                        self._serverless_ecpu[(region, engine)] = price

        # CSV loader only supports on-demand node and serverless pricing.
        # Reserved pricing, Extended Support surcharges, and node memory data
        # are only available from the live bulk pricing API.
        if not self._reserved:
            print(
                "Note: CSV pricing does not include Reserved Instance or Extended Support data. "
                "Use live pricing (omit --pricing-csv) for full coverage.",
                file=sys.stderr,
            )

    def get_serverless_storage_rate(self, region: str, engine: str) -> float:
        """Get serverless storage rate in $/GB-hour."""
        eng = engine.lower()
        key = (region, eng)
        if key in self._serverless_storage:
            return self._serverless_storage[key]
        raise ValueError(
            "No serverless storage pricing found for region={}, engine={}. "
            "Available: {}".format(region, eng, self._list_serverless_regions(eng))
        )

    def get_serverless_ecpu_rate(self, region: str, engine: str) -> float:
        """Get serverless ECPU rate in $ per single ECPU."""
        eng = engine.lower()
        key = (region, eng)
        if key in self._serverless_ecpu:
            return self._serverless_ecpu[key]
        raise ValueError(
            "No serverless ECPU pricing found for region={}, engine={}. "
            "Available: {}".format(region, eng, self._list_serverless_regions(eng))
        )

    def get_node_hourly_rate(self, region: str, instance_type: str, engine: str = "valkey") -> float:
        """Get node on-demand hourly rate."""
        eng = engine.lower()
        key = (region, instance_type, eng)
        if key in self._node_od:
            return self._node_od[key]
        raise ValueError(
            "No node pricing found for region={}, instance_type={}, engine={}".format(
                region, instance_type, eng
            )
        )

    def get_node_monthly_rate(self, region: str, instance_type: str, engine: str = "valkey") -> float:
        """Get node on-demand monthly rate (hourly x 730 hours)."""
        return self.get_node_hourly_rate(region, instance_type, engine) * 730

    def get_extended_support_rate(self, region: str, instance_type: str, engine: str, year: str = "1") -> float:
        """Get Extended Support surcharge in $/node-hour for the given year tier.

        Year tiers: '1' and '2' (same rate, from Yr1_Yr2), '3' (higher rate, from Yr3).
        """
        eng = engine.lower()
        key = (region, instance_type, eng, str(year))
        if key in self._extended_support:
            return self._extended_support[key]
        raise ValueError(
            "No Extended Support pricing found for region={}, instance_type={}, engine={}, year={}. "
            "This may mean Extended Support pricing is not published for this combination.".format(
                region, instance_type, eng, year
            )
        )

    def has_extended_support_pricing(self) -> bool:
        """Check if any Extended Support pricing was loaded."""
        return len(self._extended_support) > 0

    def get_node_memory_gb(self, instance_type: str) -> float:
        """Get memory capacity in GB for a node type. Returns 0 if unknown."""
        return self._node_memory.get(instance_type, 0.0)

    def get_all_node_memory(self) -> dict:
        """Get the full instance_type -> memory_gb mapping."""
        return dict(self._node_memory)

    def _list_serverless_regions(self, engine: str) -> str:
        """List regions that have serverless pricing loaded for an engine."""
        regions = sorted(set(
            r for (r, e) in self._serverless_storage if e == engine
        ))
        if len(regions) > 5:
            return ", ".join(regions[:5]) + " and {} more".format(len(regions) - 5)
        return ", ".join(regions) if regions else "none loaded"

    # --- Reserved pricing methods ---

    def get_reserved_rate(
        self, region: str, instance_type: str, engine: str = "valkey",
        lease_length: str = "1yr", purchase_option: str = "No Upfront",
    ) -> dict:
        """Get reserved pricing for a node.

        Returns {"hourly": float, "upfront": float}.
        - "No Upfront": upfront=0, hourly=full reserved rate
        - "All Upfront": upfront=lump sum, hourly=0
        - "Partial Upfront": upfront=partial lump sum, hourly=reduced rate
        """
        eng = engine.lower()
        key = (region, instance_type, eng, lease_length, purchase_option)
        if key in self._reserved:
            return self._reserved[key]
        raise ValueError(
            "No reserved pricing found for region={}, instance_type={}, engine={}, "
            "lease={}, purchase={}".format(region, instance_type, eng, lease_length, purchase_option)
        )

    def get_reserved_effective_monthly(
        self, region: str, instance_type: str, engine: str = "valkey",
        lease_length: str = "1yr", purchase_option: str = "No Upfront",
    ) -> float:
        """Get effective monthly cost for a reserved node.

        Amortizes upfront payment over the term and adds the recurring hourly cost.
        Formula: (upfront / term_months) + (hourly * 730)
        """
        rate = self.get_reserved_rate(region, instance_type, engine, lease_length, purchase_option)
        term_months = 12 if lease_length == "1yr" else 36
        monthly = (rate["upfront"] / term_months) + (rate["hourly"] * 730)
        return round(monthly, 2)

    def list_reserved_options(
        self, region: str, instance_type: str, engine: str = "valkey",
    ) -> list:
        """List all available reserved pricing options for a node.

        Returns a list of dicts with lease_length, purchase_option,
        hourly, upfront, and effective_monthly.
        """
        eng = engine.lower()
        results = []
        for (r, it, e, lease, purchase), rate in self._reserved.items():
            if r == region and it == instance_type and e == eng:
                term_months = 12 if lease == "1yr" else 36
                effective = round(
                    (rate["upfront"] / term_months) + (rate["hourly"] * 730), 2
                )
                results.append({
                    "lease_length": lease,
                    "purchase_option": purchase,
                    "hourly": rate["hourly"],
                    "upfront": rate["upfront"],
                    "effective_monthly": effective,
                })
        results.sort(key=lambda x: x["effective_monthly"])
        return results
