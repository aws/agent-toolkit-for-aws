import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    _BOTO3_IMPORT_ERROR: Optional[str] = None
except ImportError as _exc:  # pragma: no cover - exercised only in offline environments
    boto3 = None
    _BOTO3_IMPORT_ERROR = str(_exc)

    class _Boto3Missing(Exception):
        """Placeholder so the `except` clauses below stay valid without botocore."""

    BotoCoreError = ClientError = _Boto3Missing

# NOTE: Pricing Source - there are two interchangeable pricing pathways, selected with
# --pricing-source:
#
#   api    - broker, storage, and data-transfer prices are fetched live from the AWS Pricing
#            API (boto3 `pricing` client's GetProducts) for whichever region is passed via
#            --region. Requires boto3 plus credentials with the `pricing:GetProducts`
#            permission. Accurate for every region, and never stale.
#   static - prices come from the STATIC_PRICING_* tables embedded below. Requires no
#            credentials, no network, and not even boto3, but covers only
#            STATIC_PRICING_REGION and goes stale whenever AWS changes a rate.
#   auto   - (default) try `api`, fall back to `static` with a warning when the Pricing API
#            is unreachable or unauthorized.
#
# The Price List API itself is only served from the us-east-1 (or ap-south-1) endpoint
# regardless of the target region — the target region is selected via a
# `regionCode`/`fromRegionCode` filter on the request, not the client's region. See
# fetch_pricing() below. Broker capacity specs (EBS/NIC throughput, partition limits) are
# NOT exposed by the Pricing API and remain hardcoded in INSTANCE_SPECS.

# NOTE: Unit Convention - All throughput is in **MiB/s**, all storage is in **GiB**
# Conversions use the binary factor 1024 (e.g., MiB/s × 3600 / 1024 → GiB/h).
#
# AWS lists provisioned storage throughput in MiB/s (per the MSK docs) and
# bills storage at "$/GB-month" where GB == GiB per the AWS Service Terms.
# Variable names ending in `_mbs` and `_gb` are kept for backwards compatibility
# but should be read as MiB/s and GiB throughout this file. CLI prompts, help
# strings, and explain output use the precise unit names.

# NOTE: Instance Specifications
# These are physical broker capacity limits, not pricing — the AWS Pricing API does not
# expose EBS/NIC throughput caps or partition limits, so they stay hardcoded here. On-demand
# instance price (USD/hr) is fetched live per-region by fetch_pricing() instead of stored here.
#
# Standard (M5 / M7g):
#   ebs_throughput_mbs     – maximum provisionable EBS volume throughput per broker (MiB/s);
#                            also used as the documented PST cap for the instance
#   network_throughput_mbs – NIC bandwidth available to the broker (MiB/s)
#   rec_partitions         – recommended max partitions per broker (leaders + followers)
#   max_partitions         – hard max partitions per broker
#
# Express (M7g):
#   ingress_mbs    – max producer throughput per broker (MiB/s); used directly
#   rec_partitions, max_partitions as above

INSTANCE_SPECS = {
    "kafka.m5.large": {
        "ebs_throughput_mbs": 81.0,
        "network_throughput_mbs": 96,
        "rec_partitions": 1000,
        "max_partitions": 1500,
    },
    "kafka.m5.xlarge": {
        "ebs_throughput_mbs": 144.0,
        "network_throughput_mbs": 160,
        "rec_partitions": 1000,
        "max_partitions": 1500,
    },
    "kafka.m5.2xlarge": {
        "ebs_throughput_mbs": 250.0,
        "network_throughput_mbs": 320,
        "rec_partitions": 2000,
        "max_partitions": 3000,
    },
    "kafka.m5.4xlarge": {
        "ebs_throughput_mbs": 593.75,
        "network_throughput_mbs": 640,
        "rec_partitions": 4000,
        "max_partitions": 6000,
    },
    "kafka.m5.8xlarge": {
        "ebs_throughput_mbs": 850.0,
        "network_throughput_mbs": 1280,
        "rec_partitions": 4000,
        "max_partitions": 6000,
    },
    "kafka.m5.12xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 1536,
        "rec_partitions": 4000,
        "max_partitions": 6000,
    },
    "kafka.m5.16xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 2560,
        "rec_partitions": 4000,
        "max_partitions": 6000,
    },
    "kafka.m5.24xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 3200,
        "rec_partitions": 4000,
        "max_partitions": 4000,
    },
    "kafka.m7g.large": {
        "ebs_throughput_mbs": 78.75,
        "network_throughput_mbs": 117,
        "rec_partitions": 1000,
        "max_partitions": 1500,
    },
    "kafka.m7g.xlarge": {
        "ebs_throughput_mbs": 156.25,
        "network_throughput_mbs": 234,
        "rec_partitions": 1000,
        "max_partitions": 1500,
    },
    "kafka.m7g.2xlarge": {
        "ebs_throughput_mbs": 312.5,
        "network_throughput_mbs": 469,
        "rec_partitions": 2000,
        "max_partitions": 3000,
    },
    "kafka.m7g.4xlarge": {
        "ebs_throughput_mbs": 625.0,
        "network_throughput_mbs": 937,
        "rec_partitions": 4000,
        "max_partitions": 6000,
    },
    "kafka.m7g.8xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 1875,
        "rec_partitions": 4000,
        "max_partitions": 6000,
    },
    "kafka.m7g.12xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 2812,
        "rec_partitions": 4000,
        "max_partitions": 6000,
    },
    "kafka.m7g.16xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 3750,
        "rec_partitions": 4000,
        "max_partitions": 6000,
    },
    "kafka.m7g.large (Express)": {
        "ingress_mbs": 15.625,
        "rec_partitions": 1000,
        "max_partitions": 1500,
    },
    "kafka.m7g.xlarge (Express)": {
        "ingress_mbs": 31.25,
        "rec_partitions": 1000,
        "max_partitions": 2000,
    },
    "kafka.m7g.2xlarge (Express)": {
        "ingress_mbs": 62.5,
        "rec_partitions": 2500,
        "max_partitions": 4000,
    },
    "kafka.m7g.4xlarge (Express)": {
        "ingress_mbs": 125.0,
        "rec_partitions": 6000,
        "max_partitions": 8000,
    },
    "kafka.m7g.8xlarge (Express)": {
        "ingress_mbs": 250.0,
        "rec_partitions": 12000,
        "max_partitions": 16000,
    },
    "kafka.m7g.12xlarge (Express)": {
        "ingress_mbs": 375.0,
        "rec_partitions": 16000,
        "max_partitions": 24000,
    },
    "kafka.m7g.16xlarge (Express)": {
        "ingress_mbs": 500.0,
        "rec_partitions": 20000,
        "max_partitions": 32000,
    },
}

# Only 4xlarge and larger support Provisioned Storage Throughput (PST)
PST_ELIGIBLE = {
    "kafka.m5.4xlarge",
    "kafka.m5.8xlarge",
    "kafka.m5.12xlarge",
    "kafka.m5.16xlarge",
    "kafka.m7g.4xlarge",
    "kafka.m7g.8xlarge",
    "kafka.m7g.12xlarge",
    "kafka.m7g.16xlarge",
    "kafka.m5.24xlarge",
}


def discount_multiplier(discount_pct: float) -> float:
    """Convert a PPA / EDP discount percentage into a cost multiplier.

    Applies uniformly to every cost dimension: broker hours, storage, Tiered
    Storage, Provisioned Storage Throughput, Express data-in, and cross-AZ transfer.
    """
    if not 0 <= discount_pct < 100:
        raise ValueError(f"discount_pct must be >= 0 and < 100; got {discount_pct}")
    return 1 - discount_pct / 100


# NOTE: EBS volumes are provisioned with a 50% utilization buffer because a disk-full
# event on a Kafka broker is catastrophic (broker stops accepting writes and
# can corrupt segments).
EBS_HEADROOM_FACTOR = 2.0

# NOTE: Sizing assumes 3 AZs, because Express only supports 3 AZ configurations. Standard also
# supports 2 AZ configurations, but this is not supported by the script as a configuration today.
NUM_AZS = 3
HOURS_PER_MONTH = 730
MAX_EBS_GB_PER_BROKER = 16384  # EBS max for MSK is 16 TiB

# Default per-cluster broker quota (MSK Provisioned). Used to pick a "recommended"
# instance per class — the cheapest size whose broker count fits within the quota.
DEFAULT_BROKER_QUOTA = 60

# NOTE: Entitlement-Factor Constants
#
# Standard (M5 / M7g):
#   All broker I/O operations (ingress, replication, TS writes, consumer lag,
#   rebalancing) consume EBS and NIC bandwidth as multiples of ingress rate,
#   sized for a 1-AZ-down state.
#
#   STORAGE_IO_FACTOR_BASE: EBS write I/O per unit ingress without Tiered Storage
#     (1.5 ingress + 1.5 replication-in + 0.5 lagging + 3.0 rebalancing = 6.5)
#   STORAGE_IO_FACTOR_TS_ADD: extra EBS I/O when Tiered Storage is enabled
#     (1.5 remote-storage staging writes)
#
#   NETWORK_IO_BASE: static outbound NIC multiplier without Tiered Storage
#     (2.2 replication-out + 0.5 lagging + 3.0 rebalancing = 5.7)
#   NETWORK_IO_TS_ADD: extra NIC traffic when Tiered Storage is enabled
#     (1.5 remote writes / fetches)
#   Fan-out adds AZ_SCALE_FACTOR per unit of fan-out ratio on top of the base.
#   AZ_SCALE_FACTOR: consumer traffic scales up by NUM_AZS/(NUM_AZS-1) in 1-AZ-down state.
#
#   Tiered Storage is detected as "in use" when retention_hours > primary_retention_hours.
#
# Express (M7g):
#   No inter-broker replication or EBS writes.  ingress_mbs is the published
#   per-broker ingress limit.  Egress capacity = ingress_mbs * EXPRESS_EGRESS_FACTOR.

STORAGE_IO_FACTOR_BASE = 6.5  # without Tiered Storage
STORAGE_IO_FACTOR_TS_ADD = 1.5  # additional EBS load when TS is enabled
NETWORK_IO_BASE = 5.7  # without Tiered Storage
NETWORK_IO_TS_ADD = 1.5  # additional NIC load when TS is enabled
AZ_SCALE_FACTOR = NUM_AZS / (NUM_AZS - 1)  # 1.5 for 3 AZs
EXPRESS_EGRESS_FACTOR = 2.5  # Express egress capacity = ingress_mbs * this factor


@dataclass
class SizingInputs:
    avg_data_in_mbs: float  # Average producer throughput (MiB/s)
    peak_data_in_mbs: float  # Peak producer throughput (MiB/s)
    avg_data_out_mbs: float  # Average consumer throughput (MiB/s)
    peak_data_out_mbs: float  # Peak consumer throughput (MiB/s)
    num_partitions: int  # Total partitions including replicas
    replication_factor: int  # Kafka replication factor (Standard: 2 or 3; Express: always 3)
    retention_hours: int  # Total data retention (hours)
    primary_retention_hours: int  # Primary (EBS) retention (hours); remainder goes to TS
    utilization_standard: float  # Max fraction of broker capacity to use (Standard)
    utilization_express: float  # Max fraction of broker capacity to use (Express)
    pst_per_broker_mbs: Optional[float] = (
        None  # Provisioned storage throughput per broker (MiB/s); 250–1000
    )
    use_max_partitions: bool = False  # Use hard max partition limit instead of recommended
    rack_affined_consumers: bool = True  # When False, cross-AZ cost includes consumer fetch traffic

    def __post_init__(self) -> None:
        for name, value in (
            ("avg_data_in_mbs", self.avg_data_in_mbs),
            ("peak_data_in_mbs", self.peak_data_in_mbs),
            ("avg_data_out_mbs", self.avg_data_out_mbs),
            ("peak_data_out_mbs", self.peak_data_out_mbs),
        ):
            if value is None or value <= 0:
                raise ValueError(f"{name} must be > 0; got {value}")

        if self.peak_data_in_mbs < self.avg_data_in_mbs:
            raise ValueError(
                f"peak_data_in_mbs ({self.peak_data_in_mbs}) must be >= "
                f"avg_data_in_mbs ({self.avg_data_in_mbs})"
            )
        if self.peak_data_out_mbs < self.avg_data_out_mbs:
            raise ValueError(
                f"peak_data_out_mbs ({self.peak_data_out_mbs}) must be >= "
                f"avg_data_out_mbs ({self.avg_data_out_mbs})"
            )

        if self.replication_factor not in (2, 3):
            raise ValueError(
                f"replication_factor must be 2 or 3; got {self.replication_factor}. "
                "Express always uses RF=3 internally regardless of this value."
            )

        if self.primary_retention_hours > self.retention_hours:
            raise ValueError(
                f"primary_retention_hours ({self.primary_retention_hours}) must be "
                f"<= retention_hours ({self.retention_hours})"
            )

        if self.pst_per_broker_mbs is not None:
            if not (250 <= self.pst_per_broker_mbs <= 1000):
                raise ValueError(
                    f"pst_per_broker_mbs must be between 250 and 1000 MiB/s; "
                    f"got {self.pst_per_broker_mbs}"
                )


# Published on https://aws.amazon.com/ec2/pricing/on-demand/ for virtually every commercial
# region, even where the Price List API doesn't publish a distinct IntraRegion SKU (see
# fetch_pricing()'s cross-AZ fallback).
FALLBACK_CROSS_AZ_COST_PER_GB_ONE_WAY = 0.01


@dataclass
class Pricing:
    """Pricing for one region, from either pricing pathway.

    Built by fetch_pricing() (live AWS Pricing API) or static_pricing() (embedded table).
    `source` records which, so the output can label figures honestly.

    broker_price_per_hr is keyed by INSTANCE_SPECS instance type (e.g. "kafka.m5.large",
    "kafka.m7g.large (Express)"). Instance types with no pricing available in the region
    are omitted from the dict and excluded from sizing.
    """

    region: str
    broker_price_per_hr: Dict[str, float] = field(default_factory=dict)
    ebs_cost_per_gb_month: float = 0.0
    tiered_storage_cost_per_gb_month: float = 0.0
    express_storage_cost_per_gb_month: float = 0.0
    express_data_in_per_gb: float = 0.0
    cross_az_cost_per_gb: float = 0.0
    pst_cost_per_mbs_month: float = 0.0
    source: str = "api"


# ─── Pricing Errors ───────────────────────────────────────────────────────────


class PricingError(RuntimeError):
    """Base class for every pricing-resolution failure."""


class PricingUnavailableError(PricingError):
    """The Pricing API pathway as a whole is unusable.

    Raised for missing/expired credentials, a missing `pricing:GetProducts` permission,
    throttling, an unreachable endpoint, or boto3 not being installed. These are the
    conditions `--pricing-source auto` recovers from by falling back to static pricing.
    """


class PricingDimensionError(PricingError):
    """The Pricing API works, but one specific price could not be resolved.

    Raised when a filter combination returns no products, or a product carries no
    OnDemand price dimension. Distinct from PricingUnavailableError so that a
    credentials failure can never be mistaken for a genuinely unpublished SKU — see
    fetch_pricing()'s cross-AZ handler, which recovers from this error only.
    """


# ─── Static (credential-free) Pricing ─────────────────────────────────────────

# Embedded public on-demand rates used by `--pricing-source static` and by the `auto`
# fallback. This pathway needs no credentials, no network access, and no boto3, which makes
# the script usable in offline, air-gapped, and evaluation environments — but the rates are
# a point-in-time snapshot of ONE region and go stale whenever AWS republishes a price.
#
# Captured from the AWS Price List API (GetProducts) on the date below and cross-checked
# against the worked examples on https://aws.amazon.com/msk/pricing/. To refresh, run with
# `--pricing-source api --emit-static-pricing` and paste the output back over these tables.
STATIC_PRICING_REGION = "us-east-1"
STATIC_PRICING_CAPTURED = "2026-10-05"

STATIC_BROKER_PRICE_PER_HR = {
    "kafka.m5.large": 0.21,
    "kafka.m5.xlarge": 0.42,
    "kafka.m5.2xlarge": 0.84,
    "kafka.m5.4xlarge": 1.68,
    "kafka.m5.8xlarge": 3.36,
    "kafka.m5.12xlarge": 5.04,
    "kafka.m5.16xlarge": 6.73,
    "kafka.m5.24xlarge": 10.08,
    "kafka.m7g.large": 0.204,
    "kafka.m7g.xlarge": 0.408,
    "kafka.m7g.2xlarge": 0.816,
    "kafka.m7g.4xlarge": 1.632,
    "kafka.m7g.8xlarge": 3.264,
    "kafka.m7g.12xlarge": 4.896,
    "kafka.m7g.16xlarge": 6.528,
    "kafka.m7g.large (Express)": 0.408,
    "kafka.m7g.xlarge (Express)": 0.816,
    "kafka.m7g.2xlarge (Express)": 1.632,
    "kafka.m7g.4xlarge (Express)": 3.264,
    "kafka.m7g.8xlarge (Express)": 6.528,
    "kafka.m7g.12xlarge (Express)": 9.792,
    "kafka.m7g.16xlarge (Express)": 13.056,
}

# Shared (non-per-instance) dimensions. cross_az_cost_per_gb is already doubled, because
# EC2 Regional data transfer bills both the sending and the receiving side of an AZ
# boundary — see the note in fetch_pricing().
STATIC_SHARED_PRICING = {
    "ebs_cost_per_gb_month": 0.10,
    "tiered_storage_cost_per_gb_month": 0.06,
    "express_storage_cost_per_gb_month": 0.10,
    "express_data_in_per_gb": 0.01,
    "cross_az_cost_per_gb": FALLBACK_CROSS_AZ_COST_PER_GB_ONE_WAY * 2,
    "pst_cost_per_mbs_month": 0.08,
}


def _assert_static_region(region: str) -> None:
    """Refuse to price a region the embedded table does not actually cover.

    Silently applying STATIC_PRICING_REGION rates to another region would produce
    confidently wrong dollar figures, and this script's output is reported to customers
    verbatim, so this is a hard error rather than a warning.
    """
    if region != STATIC_PRICING_REGION:
        raise PricingError(
            f"static pricing covers only {STATIC_PRICING_REGION}, but --region {region} "
            f"was requested. {region} rates differ, so reusing {STATIC_PRICING_REGION} "
            "figures would be wrong. Re-run with --pricing-source api (requires AWS "
            "credentials with pricing:GetProducts), or size against "
            f"--region {STATIC_PRICING_REGION}."
        )


def static_pricing(region: str, broker_classes: List[str]) -> Pricing:
    """Build a Pricing object from the embedded tables, with no AWS calls whatsoever."""
    _assert_static_region(region)

    selected_groups = {cls for group in broker_classes for cls in BROKER_CLASS_GROUPS[group]}
    need_standard = bool({"m5_standard", "m7g_standard"} & selected_groups)
    need_express = "express" in selected_groups

    broker_price_per_hr: Dict[str, float] = {}
    for instance_type in INSTANCE_SPECS:
        cls = _classify(instance_type)
        if cls == "express" and not need_express:
            continue
        if cls in ("m5_standard", "m7g_standard") and not need_standard:
            continue
        price = STATIC_BROKER_PRICE_PER_HR.get(instance_type)
        if price is None:
            print(
                f"WARNING: no static pricing recorded for {instance_type}; "
                "excluding from sizing",
                file=sys.stderr,
            )
            continue
        broker_price_per_hr[instance_type] = price

    shared = dict(STATIC_SHARED_PRICING)
    # Zero out the dimensions the selected broker classes cannot incur, mirroring
    # fetch_pricing() so both pathways yield identical Pricing shapes.
    if not need_standard:
        shared["ebs_cost_per_gb_month"] = 0.0
        shared["tiered_storage_cost_per_gb_month"] = 0.0
        shared["pst_cost_per_mbs_month"] = 0.0
    if not need_express:
        shared["express_storage_cost_per_gb_month"] = 0.0
        shared["express_data_in_per_gb"] = 0.0

    return Pricing(
        region=region,
        broker_price_per_hr=broker_price_per_hr,
        source="static",
        **shared,
    )


# ─── AWS Pricing API Lookups ───────────────────────────────────────────────────


def _compute_family(instance_type: str) -> str:
    """Map an INSTANCE_SPECS key to the Pricing API's `computeFamily` attribute.

    "kafka.m5.large" -> "m5.large"; "kafka.m7g.large (Express)" -> "express.m7g.large".
    """
    suffix = " (Express)"
    if instance_type.endswith(suffix):
        base = instance_type[: -len(suffix)]
        if base.startswith("kafka."):
            base = base[len("kafka.") :]
        return f"express.{base}"
    if instance_type.startswith("kafka."):
        return instance_type[len("kafka.") :]
    return instance_type


_pricing_client = None

# ClientError codes that mean "this caller cannot use the Pricing API", as opposed to
# "this particular price does not exist". These make the whole api pathway unusable and so
# trigger the `auto` fallback to static pricing.
_UNAVAILABLE_ERROR_CODES = frozenset(
    {
        "AccessDenied",
        "AccessDeniedException",
        "UnauthorizedOperation",
        "UnrecognizedClientException",
        "InvalidClientTokenId",
        "InvalidSignatureException",
        "ExpiredToken",
        "ExpiredTokenException",
        "RequestExpired",
        "ThrottlingException",
        "Throttling",
        "TooManyRequestsException",
        "ServiceUnavailable",
        "InternalFailure",
    }
)


def _get_pricing_client():
    global _pricing_client
    if boto3 is None:
        raise PricingUnavailableError(
            f"boto3 is not installed ({_BOTO3_IMPORT_ERROR}), so live pricing cannot be "
            "fetched. Install boto3, or re-run with --pricing-source static to use the "
            f"embedded {STATIC_PRICING_REGION} rates."
        )
    if _pricing_client is None:
        _pricing_client = boto3.client("pricing", region_name="us-east-1")
    return _pricing_client


def _get_products(service_code: str, filters: List[Tuple[str, str]]) -> List[dict]:
    """Call the Pricing API's GetProducts and return the parsed product list.

    Requires boto3 and credentials with the `pricing:GetProducts` permission. The
    Price List API is only served from the us-east-1 (or ap-south-1) endpoint
    regardless of which region's prices are being requested — the target region
    is selected via a `regionCode`/`fromRegionCode` filter, not the client region.

    Raises PricingUnavailableError when the API is unusable (credentials, permissions,
    throttling, connectivity) and PricingDimensionError for anything else, so callers
    can tell a broken pathway apart from an unpublished SKU.
    """
    client = _get_pricing_client()
    api_filters = [
        {"Type": "TERM_MATCH", "Field": field_name, "Value": value} for field_name, value in filters
    ]
    try:
        products: List[dict] = []
        paginator = client.get_paginator("get_products")
        for page in paginator.paginate(ServiceCode=service_code, Filters=api_filters):
            products += [json.loads(item) for item in page["PriceList"]]
        return products
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        detail = (
            f"Pricing API GetProducts failed for service={service_code} "
            f"filters={filters}: {exc}"
        )
        if code in _UNAVAILABLE_ERROR_CODES:
            raise PricingUnavailableError(detail) from exc
        raise PricingDimensionError(detail) from exc
    except BotoCoreError as exc:
        # botocore-level failures are always transport/credential problems — a SKU that
        # does not exist comes back as an empty PriceList, not an exception.
        raise PricingUnavailableError(
            f"Pricing API GetProducts failed for service={service_code} "
            f"filters={filters}: {exc}"
        ) from exc


def _price_per_unit_usd(product: dict) -> float:
    for term in product.get("terms", {}).get("OnDemand", {}).values():
        for dim in term.get("priceDimensions", {}).values():
            return float(dim["pricePerUnit"]["USD"])
    sku = product.get("product", {}).get("sku", "unknown")
    raise PricingDimensionError(f"no OnDemand priceDimensions found in pricing product (sku={sku})")


def _fetch_single_price(service_code: str, filters: List[Tuple[str, str]], context: str) -> float:
    products = _get_products(service_code, filters)
    if not products:
        raise PricingDimensionError(
            f"No pricing found for {context} (service={service_code}, filters={filters}). "
            "Check that the region and dimension are correct/available."
        )
    return _price_per_unit_usd(products[0])


def fetch_pricing(region: str, broker_classes: List[str]) -> Pricing:
    """Fetch live on-demand pricing for *region*, scoped to the selected broker classes.

    Broker prices are fetched in a single `aws pricing get-products` call per region
    (filtered only by regionCode + operation=RunBroker) and matched locally by
    computeFamily, rather than one call per instance type.
    """
    selected_groups = {cls for group in broker_classes for cls in BROKER_CLASS_GROUPS[group]}
    need_standard = bool({"m5_standard", "m7g_standard"} & selected_groups)
    need_express = "express" in selected_groups

    broker_price_per_hr: Dict[str, float] = {}
    if need_standard or need_express:
        broker_products = _get_products(
            "AmazonMSK", [("regionCode", region), ("operation", "RunBroker")]
        )
        price_by_compute_family = {
            attrs["computeFamily"]: _price_per_unit_usd(p)
            for p in broker_products
            if (attrs := p["product"]["attributes"]).get("computeFamily")
        }
        for instance_type in INSTANCE_SPECS:
            cls = _classify(instance_type)
            if cls == "express" and not need_express:
                continue
            if cls in ("m5_standard", "m7g_standard") and not need_standard:
                continue
            compute_family = _compute_family(instance_type)
            if compute_family in price_by_compute_family:
                broker_price_per_hr[instance_type] = price_by_compute_family[compute_family]
            else:
                print(
                    f"WARNING: no {region} pricing found for {instance_type} "
                    f"(computeFamily={compute_family}); excluding from sizing",
                    file=sys.stderr,
                )

    ebs_cost = tiered_cost = pst_cost = 0.0
    express_storage_cost = express_data_in = 0.0
    if need_standard:
        ebs_cost = _fetch_single_price(
            "AmazonMSK",
            [("regionCode", region), ("operation", "RunVolume"), ("storageFamily", "GP2")],
            context="EBS (GP2) storage",
        )
        tiered_cost = _fetch_single_price(
            "AmazonMSK",
            [
                ("regionCode", region),
                ("operation", "TieredStorage"),
                ("storageFamily", "Tiered storage"),
            ],
            context="Tiered Storage",
        )
        pst_cost = _fetch_single_price(
            "AmazonMSK",
            [("regionCode", region), ("operation", "RunVolume"), ("storageFamily", "General")],
            context="Provisioned Storage Throughput",
        )
    if need_express:
        express_storage_cost = _fetch_single_price(
            "AmazonMSK",
            [
                ("regionCode", region),
                ("operation", "Storage"),
                ("storageFamily", "Express storage"),
            ],
            context="Express storage",
        )
        express_data_in = _fetch_single_price(
            "AmazonMSK",
            [("regionCode", region), ("operation", "Data-In")],
            context="Express data-in",
        )

    # EC2 "Regional" data transfer is billed per-GB on both the sending and receiving
    # side of an AZ boundary, so one GB crossing AZs costs 2x the published one-way rate.
    try:
        cross_az_one_way = _fetch_single_price(
            "AmazonEC2",
            [
                ("productFamily", "Data Transfer"),
                ("fromRegionCode", region),
                ("transferType", "IntraRegion"),
            ],
            context="cross-AZ data transfer",
        )
    except PricingDimensionError:
        # Catch only PricingDimensionError, never PricingUnavailableError: a credentials or
        # permissions failure must not be silently reported as the published $0.01/GB rate.
        #
        # The Price List API only publishes a distinct IntraRegion (cross-AZ) SKU for a
        # handful of legacy regions (us-east-1, us-west-1/2, eu-west-1, eu-central-1,
        # ap-northeast-1/2, ap-southeast-1/2, sa-east-1, us-gov-west-1); every other region
        # is missing this SKU entirely even though AWS's public pricing page documents the
        # same $0.01/GB one-way rate everywhere. Fall back to that published rate rather than
        # failing the whole run.
        print(
            f"WARNING: no {region} cross-AZ data-transfer pricing published via the Pricing "
            f"API; falling back to the standard ${FALLBACK_CROSS_AZ_COST_PER_GB_ONE_WAY:g}/GB "
            "one-way rate documented at https://aws.amazon.com/ec2/pricing/on-demand/",
            file=sys.stderr,
        )
        cross_az_one_way = FALLBACK_CROSS_AZ_COST_PER_GB_ONE_WAY

    return Pricing(
        region=region,
        broker_price_per_hr=broker_price_per_hr,
        ebs_cost_per_gb_month=ebs_cost,
        tiered_storage_cost_per_gb_month=tiered_cost,
        express_storage_cost_per_gb_month=express_storage_cost,
        express_data_in_per_gb=express_data_in,
        cross_az_cost_per_gb=cross_az_one_way * 2,
        pst_cost_per_mbs_month=pst_cost,
        source="api",
    )


PRICING_SOURCES = ("auto", "api", "static")


def resolve_pricing(region: str, broker_classes: List[str], pricing_source: str) -> Pricing:
    """Return pricing for *region* using the requested pathway.

    "api" and "static" force one pathway. "auto" prefers the live API and falls back to the
    embedded table only when the API pathway is unusable (no credentials, no
    pricing:GetProducts, no boto3, no connectivity) — never when the API answered but a
    specific SKU was missing, which is a real data problem the static table cannot fix.
    """
    if pricing_source not in PRICING_SOURCES:
        raise PricingError(
            f"unknown pricing source {pricing_source!r}; choose from: "
            f"{', '.join(PRICING_SOURCES)}"
        )

    if pricing_source == "static":
        return static_pricing(region, broker_classes)
    if pricing_source == "api":
        return fetch_pricing(region, broker_classes)

    try:
        return fetch_pricing(region, broker_classes)
    except PricingUnavailableError as exc:
        if region != STATIC_PRICING_REGION:
            raise PricingError(
                f"{exc}\n\nFalling back to static pricing is not possible for "
                f"--region {region}: the embedded table covers only "
                f"{STATIC_PRICING_REGION}. Supply AWS credentials with "
                f"pricing:GetProducts to price {region}, or size against "
                f"--region {STATIC_PRICING_REGION} with --pricing-source static."
            ) from exc
        print(
            f"WARNING: the AWS Pricing API is unavailable ({exc}).\n"
            f"WARNING: falling back to embedded {STATIC_PRICING_REGION} pricing captured on "
            f"{STATIC_PRICING_CAPTURED}; rates may be stale. Re-run with "
            "--pricing-source api once credentials are available to confirm.",
            file=sys.stderr,
        )
        return static_pricing(region, broker_classes)


@dataclass
class BottleneckDetail:
    """Per-constraint detail for a sizing result."""

    name: str
    brokers_needed: int
    demand: float
    per_broker_capacity: float
    unit: str


@dataclass
class SizingResult:
    instance_type: str
    broker_count: int
    bottleneck: str
    monthly_broker_cost: float
    monthly_ebs_cost: float
    monthly_ts_cost: float
    monthly_data_in_cost: float
    monthly_cross_az_cost: float
    monthly_pst_cost: float = 0.0
    total_monthly_cost: float = 0.0
    bottleneck_details: Dict[str, BottleneckDetail] = field(default_factory=dict)


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _brokers_for(demand: float, per_broker_capacity: float) -> int:
    """Minimum broker count to serve *demand*, rounded up to a multiple of NUM_AZS."""
    raw = math.ceil(demand / per_broker_capacity)
    return math.ceil(raw / NUM_AZS) * NUM_AZS


# ─── Sizing Logic ──────────────────────────────────────────────────────────────


def calculate_standard_sizing(
    inputs: SizingInputs, pricing: Pricing, discount_pct: float = 0.0
) -> List[SizingResult]:
    """Calculate sizing for all Standard (M5 / M7g) instance types."""
    discount = discount_multiplier(discount_pct)
    results = []

    ebs_gb_data = (
        inputs.avg_data_in_mbs
        * inputs.primary_retention_hours
        * 3600
        * inputs.replication_factor
        / 1024
    )
    ebs_gb = ebs_gb_data * EBS_HEADROOM_FACTOR

    # TS is "in use" only when retention exceeds primary retention
    ts_in_use = inputs.retention_hours > inputs.primary_retention_hours
    storage_factor = STORAGE_IO_FACTOR_BASE + (STORAGE_IO_FACTOR_TS_ADD if ts_in_use else 0.0)
    network_base = NETWORK_IO_BASE + (NETWORK_IO_TS_ADD if ts_in_use else 0.0)

    if ts_in_use:
        ts_gb = (
            inputs.avg_data_in_mbs
            * (inputs.retention_hours - inputs.primary_retention_hours)
            * 3600
            / 1024
        )
    else:
        ts_gb = 0.0

    monthly_ebs_cost = ebs_gb * pricing.ebs_cost_per_gb_month * discount
    monthly_ts_cost = ts_gb * pricing.tiered_storage_cost_per_gb_month * discount

    pst_mbs_per_broker = inputs.pst_per_broker_mbs or 0.0

    cross_az_mbs = inputs.avg_data_in_mbs * (NUM_AZS - 1) / NUM_AZS
    if not inputs.rack_affined_consumers:
        cross_az_mbs += inputs.avg_data_out_mbs * (NUM_AZS - 1) / NUM_AZS
    cross_az_gb_mo = cross_az_mbs * 3600 * HOURS_PER_MONTH / 1024
    monthly_cross_az_cost = cross_az_gb_mo * pricing.cross_az_cost_per_gb * discount

    fan_out = inputs.peak_data_out_mbs / inputs.peak_data_in_mbs
    network_factor = fan_out * AZ_SCALE_FACTOR + network_base

    partition_key = "max_partitions" if inputs.use_max_partitions else "rec_partitions"

    for instance_type, specs in INSTANCE_SPECS.items():
        if "Express" in instance_type:
            continue
        price_per_hr = pricing.broker_price_per_hr.get(instance_type)
        if price_per_hr is None:
            continue

        util = inputs.utilization_standard

        # Available ingress per broker is the minimum of what EBS writes and NIC
        # bandwidth can sustain, accounting for all concurrent I/O operations.
        storage_limit = specs["ebs_throughput_mbs"] / storage_factor
        network_limit = specs["network_throughput_mbs"] / network_factor
        ingress_per_broker = min(storage_limit, network_limit)

        ingress_capacity_per_broker = ingress_per_broker * util
        egress_capacity_per_broker = fan_out * ingress_per_broker * util

        brokers_for_ingress = _brokers_for(inputs.peak_data_in_mbs, ingress_capacity_per_broker)
        brokers_for_egress = _brokers_for(inputs.peak_data_out_mbs, egress_capacity_per_broker)
        brokers_for_partitions = _brokers_for(inputs.num_partitions, specs[partition_key])
        brokers_for_storage = _brokers_for(ebs_gb, MAX_EBS_GB_PER_BROKER)

        details: Dict[str, BottleneckDetail] = {
            "ingress": BottleneckDetail(
                name="ingress",
                brokers_needed=brokers_for_ingress,
                demand=inputs.peak_data_in_mbs,
                per_broker_capacity=ingress_capacity_per_broker,
                unit="MiB/s peak ingress (after util)",
            ),
            "egress": BottleneckDetail(
                name="egress",
                brokers_needed=brokers_for_egress,
                demand=inputs.peak_data_out_mbs,
                per_broker_capacity=egress_capacity_per_broker,
                unit="MiB/s peak egress (after util, fan-out)",
            ),
            "partitions": BottleneckDetail(
                name="partitions",
                brokers_needed=brokers_for_partitions,
                demand=float(inputs.num_partitions),
                per_broker_capacity=float(specs[partition_key]),
                unit=f"partitions ({'max' if inputs.use_max_partitions else 'rec'})",
            ),
            "storage": BottleneckDetail(
                name="storage",
                brokers_needed=brokers_for_storage,
                demand=ebs_gb,
                per_broker_capacity=float(MAX_EBS_GB_PER_BROKER),
                unit="GiB EBS primary",
            ),
        }

        if inputs.pst_per_broker_mbs is not None and instance_type in PST_ELIGIBLE:
            effective_pst = min(inputs.pst_per_broker_mbs, specs["ebs_throughput_mbs"])
            brokers_for_pst = _brokers_for(inputs.avg_data_out_mbs, effective_pst)
            details["pst"] = BottleneckDetail(
                name="pst",
                brokers_needed=brokers_for_pst,
                demand=inputs.avg_data_out_mbs,
                per_broker_capacity=effective_pst,
                unit="MiB/s avg egress (capacity = PST cap, clamped to instance EBS max)",
            )

        broker_count = max(d.brokers_needed for d in details.values())
        bottleneck = max(details, key=lambda k: details[k].brokers_needed)

        monthly_broker_cost = broker_count * price_per_hr * HOURS_PER_MONTH * discount

        if pst_mbs_per_broker > 0 and instance_type in PST_ELIGIBLE:
            effective_pst_mbs = min(pst_mbs_per_broker, specs["ebs_throughput_mbs"])
            monthly_pst_cost = (
                broker_count * effective_pst_mbs * pricing.pst_cost_per_mbs_month * discount
            )
        else:
            monthly_pst_cost = 0.0

        total = (
            monthly_broker_cost
            + monthly_ebs_cost
            + monthly_ts_cost
            + monthly_cross_az_cost
            + monthly_pst_cost
        )

        results.append(
            SizingResult(
                instance_type=instance_type,
                broker_count=broker_count,
                bottleneck=bottleneck,
                monthly_broker_cost=monthly_broker_cost,
                monthly_ebs_cost=monthly_ebs_cost,
                monthly_ts_cost=monthly_ts_cost,
                monthly_data_in_cost=0.0,
                monthly_cross_az_cost=monthly_cross_az_cost,
                monthly_pst_cost=monthly_pst_cost,
                total_monthly_cost=total,
                bottleneck_details=details,
            )
        )

    return results


def calculate_express_sizing(
    inputs: SizingInputs, pricing: Pricing, discount_pct: float = 0.0
) -> List[SizingResult]:
    """Calculate sizing for all Express (M7g) instance types."""
    discount = discount_multiplier(discount_pct)
    results = []

    cross_az_mbs = inputs.avg_data_in_mbs * (NUM_AZS - 1) / NUM_AZS
    if not inputs.rack_affined_consumers:
        cross_az_mbs += inputs.avg_data_out_mbs * (NUM_AZS - 1) / NUM_AZS
    cross_az_gb_mo = cross_az_mbs * 3600 * HOURS_PER_MONTH / 1024
    monthly_cross_az_cost = cross_az_gb_mo * pricing.cross_az_cost_per_gb * discount

    data_in_gb_mo = inputs.avg_data_in_mbs * 3600 * HOURS_PER_MONTH / 1024
    monthly_data_in_cost = data_in_gb_mo * pricing.express_data_in_per_gb * discount

    express_storage_gb = inputs.avg_data_in_mbs * inputs.retention_hours * 3600 / 1024
    monthly_express_storage_cost = (
        express_storage_gb * pricing.express_storage_cost_per_gb_month * discount
    )

    partition_key = "max_partitions" if inputs.use_max_partitions else "rec_partitions"

    for instance_type, specs in INSTANCE_SPECS.items():
        if "Express" not in instance_type:
            continue
        price_per_hr = pricing.broker_price_per_hr.get(instance_type)
        if price_per_hr is None:
            continue

        util = inputs.utilization_express

        ingress_capacity_per_broker = specs["ingress_mbs"] * util
        egress_capacity_per_broker = specs["ingress_mbs"] * EXPRESS_EGRESS_FACTOR

        brokers_for_ingress = _brokers_for(inputs.peak_data_in_mbs, ingress_capacity_per_broker)
        brokers_for_egress = _brokers_for(inputs.peak_data_out_mbs, egress_capacity_per_broker)
        brokers_for_partitions = _brokers_for(inputs.num_partitions, specs[partition_key])

        details: Dict[str, BottleneckDetail] = {
            "ingress": BottleneckDetail(
                name="ingress",
                brokers_needed=brokers_for_ingress,
                demand=inputs.peak_data_in_mbs,
                per_broker_capacity=ingress_capacity_per_broker,
                unit="MiB/s peak ingress (after util)",
            ),
            "egress": BottleneckDetail(
                name="egress",
                brokers_needed=brokers_for_egress,
                demand=inputs.peak_data_out_mbs,
                per_broker_capacity=egress_capacity_per_broker,
                unit="MiB/s peak egress",
            ),
            "partitions": BottleneckDetail(
                name="partitions",
                brokers_needed=brokers_for_partitions,
                demand=float(inputs.num_partitions),
                per_broker_capacity=float(specs[partition_key]),
                unit=f"partitions ({'max' if inputs.use_max_partitions else 'rec'})",
            ),
        }

        broker_count = max(d.brokers_needed for d in details.values())
        bottleneck = max(details, key=lambda k: details[k].brokers_needed)

        monthly_broker_cost = broker_count * price_per_hr * HOURS_PER_MONTH * discount

        results.append(
            SizingResult(
                instance_type=instance_type,
                broker_count=broker_count,
                bottleneck=bottleneck,
                monthly_broker_cost=monthly_broker_cost,
                monthly_ebs_cost=monthly_express_storage_cost,
                monthly_ts_cost=0.0,
                monthly_data_in_cost=monthly_data_in_cost,
                monthly_cross_az_cost=monthly_cross_az_cost,
                monthly_pst_cost=0.0,
                total_monthly_cost=(
                    monthly_broker_cost
                    + monthly_express_storage_cost
                    + monthly_data_in_cost
                    + monthly_cross_az_cost
                ),
                bottleneck_details=details,
            )
        )

    return results


def _classify(instance_type: str) -> str:
    """Group results into the three classes used for recommendations."""
    if "Express" in instance_type:
        return "express"
    if instance_type.startswith("kafka.m7g."):
        return "m7g_standard"
    if instance_type.startswith("kafka.m5."):
        return "m5_standard"
    return "other"


def recommend_per_class(
    results: List[SizingResult],
    broker_quota: int = DEFAULT_BROKER_QUOTA,
) -> Dict[str, Optional[SizingResult]]:
    """Pick the cheapest result per class whose broker count fits within *broker_quota*.

    Returns a dict keyed by class with the recommended SizingResult, or None when
    no instance in that class fits within the quota.
    """
    by_class: Dict[str, List[SizingResult]] = {"m5_standard": [], "m7g_standard": [], "express": []}
    for r in results:
        cls = _classify(r.instance_type)
        if cls in by_class:
            by_class[cls].append(r)

    recs: Dict[str, Optional[SizingResult]] = {}
    for cls, items in by_class.items():
        eligible = [r for r in items if r.broker_count <= broker_quota]
        recs[cls] = min(eligible, key=lambda r: r.total_monthly_cost) if eligible else None
    return recs


_CLASS_LABELS = {
    "m5_standard": "Standard M5",
    "m7g_standard": "Standard M7g",
    "express": "Express M7g",
}

# Broker classes selectable via --broker-classes, mapped to the recommendation classes
# they cover.
BROKER_CLASS_GROUPS = {
    "standard": ("m5_standard", "m7g_standard"),
    "express": ("express",),
}


def parse_broker_classes(value: str) -> List[str]:
    """Parse a --broker-classes value into an ordered, de-duplicated list.

    Accepts "standard", "express", or any comma-separated combination.
    """
    selected: List[str] = []
    for raw in value.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token not in BROKER_CLASS_GROUPS:
            valid = ", ".join(sorted(BROKER_CLASS_GROUPS))
            raise argparse.ArgumentTypeError(
                f"invalid broker class {raw.strip()!r}; choose from: {valid} "
                "(comma-separate to select both)"
            )
        if token not in selected:
            selected.append(token)
    if not selected:
        raise argparse.ArgumentTypeError(
            "--broker-classes requires at least one of: "
            f"{', '.join(sorted(BROKER_CLASS_GROUPS))}"
        )
    return selected


def _format_summary_line(r: SizingResult) -> str:
    return (
        f"{r.instance_type}: {r.broker_count} brokers "
        f"(bottleneck: {r.bottleneck}) → ${r.total_monthly_cost:,.2f}/mo"
    )


# Cost dimensions that may be identical across every instance in a class, in which
# case they are printed once per class instead of once per instance. Broker cost is
# never hoisted — it scales with broker count and instance price.
_SHAREABLE_COST_FIELDS = (
    ("Storage", "monthly_ebs_cost"),
    ("Tiered Storage", "monthly_ts_cost"),
    ("PST", "monthly_pst_cost"),
    ("Express data-in", "monthly_data_in_cost"),
    ("Cross-AZ", "monthly_cross_az_cost"),
)


def _shared_costs(results: List[SizingResult]) -> Dict[str, tuple]:
    """Cost fields that are non-zero and identical across every result.

    Keyed by attribute name, valued as (label, amount).
    """
    shared: Dict[str, tuple] = {}
    for label, attr in _SHAREABLE_COST_FIELDS:
        values = {round(getattr(r, attr), 6) for r in results}
        if len(values) == 1:
            (value,) = tuple(values)
            if value > 0:
                shared[attr] = (label, value)
    return shared


def _shared_subtotal(shared: Dict[str, tuple]) -> float:
    """Sum of the shared cost rows as displayed, so the printed column adds up."""
    return sum(round(value, 2) for _, value in shared.values())


def _format_inputs_block(
    inputs: SizingInputs,
    results: List[SizingResult],
    discount_pct: float,
    region: str,
    pricing_source: str = "api",
) -> str:
    """Echo every setting that shaped the numbers below. Printed once."""
    present = {name for r in results for name in r.bottleneck_details}
    has_standard = any("Express" not in r.instance_type for r in results)
    has_express = any("Express" in r.instance_type for r in results)
    partition_limit = "maximum" if inputs.use_max_partitions else "recommended"

    rows = [
        ("average ingress", f"{inputs.avg_data_in_mbs:,.2f}", "MiB/s"),
        ("peak ingress", f"{inputs.peak_data_in_mbs:,.2f}", "MiB/s"),
        ("average egress", f"{inputs.avg_data_out_mbs:,.2f}", "MiB/s"),
        ("peak egress", f"{inputs.peak_data_out_mbs:,.2f}", "MiB/s"),
        (
            "partitions",
            f"{inputs.num_partitions:,}",
            f"total including replicas, sized against the {partition_limit} per-broker limit",
        ),
        (
            "retention",
            f"{inputs.retention_hours:,}",
            f"hours total, of which {inputs.primary_retention_hours:,} are primary",
        ),
    ]

    if has_standard:
        rows.append(
            (
                "replication factor",
                f"{inputs.replication_factor}",
                "Standard; Express always replicates 3 ways",
            )
        )
        rows.append(
            (
                "utilization",
                f"{inputs.utilization_standard:.2f}",
                "capacity buffer for headroom (Standard)",
            )
        )
    if has_express:
        rows.append(
            (
                "utilization (Express)" if has_standard else "utilization",
                f"{inputs.utilization_express:.2f}",
                "capacity buffer for headroom (Express)",
            )
        )

    if "storage" in present:
        storage_gb = next(
            r.bottleneck_details["storage"].demand
            for r in results
            if "storage" in r.bottleneck_details
        )
        rows.append(
            (
                "storage",
                f"{storage_gb:,.2f}",
                f"GiB EBS primary (average ingress x {inputs.primary_retention_hours}h primary "
                f"retention x RF{inputs.replication_factor} x {EBS_HEADROOM_FACTOR:g} headroom)",
            )
        )
    if "pst" in present and inputs.pst_per_broker_mbs is not None:
        rows.append(
            (
                "provisioned storage throughput",
                f"{inputs.pst_per_broker_mbs:,.2f}",
                "MiB/s per broker requested, clamped to each instance's EBS max; "
                "sized against average egress",
            )
        )

    rows.append(
        (
            "consumer rack awareness",
            "yes" if inputs.rack_affined_consumers else "no",
            (
                "consumers fetch from local-AZ replicas, so cross-AZ cost excludes consumer fetch"
                if inputs.rack_affined_consumers
                else "consumers fetch across AZs, so cross-AZ cost includes consumer fetch"
            ),
        )
    )
    rows.append(
        (
            "pricing",
            f"-{discount_pct:g}%" if discount_pct else "list",
            (
                f"{region} on-demand with a {discount_pct:g}% negotiated discount "
                "applied to every cost dimension"
                if discount_pct
                else f"{region} public on-demand, no negotiated discount applied"
            ),
        )
    )
    rows.append(
        (
            "pricing source",
            pricing_source,
            (
                f"embedded {STATIC_PRICING_REGION} rates captured "
                f"{STATIC_PRICING_CAPTURED}; no live lookup, may be stale"
                if pricing_source == "static"
                else f"live AWS Pricing API lookup for {region}"
            ),
        )
    )

    label_w = max(len(label) for label, _, _ in rows)
    value_w = max(len(value) for _, value, _ in rows)
    return "\n".join(
        f"  {label:<{label_w}}  {value:>{value_w}}  {note}" for label, value, note in rows
    )


def _format_shared_costs(shared: Dict[str, tuple]) -> str:
    lines = [f"  {label:<16} ${value:>14,.2f}" for label, value in shared.values()]
    lines.append(f"  {'Subtotal':<16} ${_shared_subtotal(shared):>14,.2f}")
    return "\n".join(lines)


def _format_broker_table(results: List[SizingResult], shared: Dict[str, tuple]) -> str:
    """One Markdown row per instance.

    `required brokers` is the maximum across every constraint; `bottleneck` names the
    constraint that produced it.
    """
    headers = ["broker type", "required brokers", "bottleneck"]

    # Any non-zero cost dimension that varies across instances needs its own column,
    # otherwise broker cost + shared costs will not add up to the total.
    per_instance_costs = [
        (label, attr)
        for label, attr in _SHAREABLE_COST_FIELDS
        if attr not in shared and any(getattr(r, attr) > 0 for r in results)
    ]

    headers.append("broker cost / mo")
    headers += [f"{label} / mo" for label, _ in per_instance_costs]
    headers.append("total cost / mo incl. shared" if shared else "total cost / mo")

    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for r in results:
        cells = [r.instance_type, f"{r.broker_count}", r.bottleneck]
        cells.append(f"${r.monthly_broker_cost:,.2f}")
        cells += [f"${getattr(r, attr):,.2f}" for _, attr in per_instance_costs]
        cells.append(f"${r.total_monthly_cost:,.2f}")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _print_sizing_section(title: str, results: List[SizingResult]) -> None:
    print(f"\n=== {title} ===")
    shared = _shared_costs(results)
    if shared:
        print("\nShared monthly costs (same for every instance in this section):")
        print(_format_shared_costs(shared))
        print("\nBroker sizing:")
    print(_format_broker_table(results, shared))


def _print_recommendations(
    results: List[SizingResult],
    broker_quota: int,
    broker_classes: Optional[List[str]] = None,
) -> None:
    selected = broker_classes or list(BROKER_CLASS_GROUPS)
    classes = [cls for group in selected for cls in BROKER_CLASS_GROUPS[group]]
    recs = recommend_per_class(results, broker_quota=broker_quota)
    print(f"\n=== Recommended pick per class (≤ {broker_quota} brokers, lowest monthly cost) ===")
    print("  Cost breakdown for each pick is in the sizing sections above.")
    for cls in classes:
        label = _CLASS_LABELS[cls]
        rec = recs[cls]
        if rec is None:
            print(
                f"  {label}: no instance fits within {broker_quota} brokers — request a quota increase or pick a larger size"
            )
        else:
            print(f"  {label}: {_format_summary_line(rec)}")


def _parse_args():
    p = argparse.ArgumentParser(
        description=(
            "MSK broker sizing calculator. Cost figures are fetched live from the AWS "
            "Pricing API for the requested --region."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region to price against; broker/storage/data-transfer pricing is looked up live via the AWS Pricing API",
    )
    p.add_argument(
        "--pricing-source",
        choices=PRICING_SOURCES,
        default="auto",
        help=(
            "where prices come from. 'api' queries the AWS Pricing API live (needs "
            "credentials with pricing:GetProducts; works for any region). 'static' uses the "
            f"rates embedded in this script (no credentials or network needed, "
            f"{STATIC_PRICING_REGION} only, captured {STATIC_PRICING_CAPTURED}). 'auto' "
            "tries the API and falls back to static with a warning"
        ),
    )
    p.add_argument(
        "--emit-static-pricing",
        action="store_true",
        help=(
            "print the resolved prices as Python literals for pasting into this script's "
            f"STATIC_* tables, then exit. Use with --pricing-source api --region "
            f"{STATIC_PRICING_REGION} to refresh the embedded snapshot"
        ),
    )
    # These describe the workload and are required for sizing, but not for
    # --emit-static-pricing, which only refreshes price tables. They are therefore declared
    # optional here and enforced in _parse_args() below.
    p.add_argument("--avg-data-in-mbs", type=float, help="Average producer throughput (MiB/s)")
    p.add_argument("--peak-data-in-mbs", type=float, help="Peak producer throughput (MiB/s)")
    p.add_argument("--avg-data-out-mbs", type=float, help="Average consumer throughput (MiB/s)")
    p.add_argument("--peak-data-out-mbs", type=float, help="Peak consumer throughput (MiB/s)")
    p.add_argument("--num-partitions", type=int, help="Total partitions including replicas")
    p.add_argument("--replication-factor", type=int, default=3, help="Kafka replication factor")
    p.add_argument("--retention-hours", type=int, help="Total data retention (hours)")
    p.add_argument(
        "--primary-retention-hours",
        type=int,
        help="Primary (EBS) retention (hours); remainder goes to Tiered Storage",
    )
    p.add_argument(
        "--utilization-standard",
        type=float,
        default=0.50,
        help="Max broker capacity fraction to use (Standard)",
    )
    p.add_argument(
        "--utilization-express",
        type=float,
        default=0.75,
        help="Max broker capacity fraction to use (Express)",
    )
    p.add_argument(
        "--pst-per-broker-mbs",
        type=float,
        default=None,
        help="Provisioned Storage Throughput per broker (MiB/s); 4xlarge+ only",
    )
    p.add_argument(
        "--use-max-partitions",
        action="store_true",
        help="Size against hard max partition limit instead of recommended",
    )
    p.add_argument(
        "--no-rack-affined-consumers",
        dest="rack_affined_consumers",
        action="store_false",
        default=True,
        help="Include cross-AZ consumer fetch traffic in the cost estimate (assumes consumers fetch across AZs instead of from local-AZ replicas). Does NOT change broker count.",
    )
    p.add_argument(
        "--discount-pct",
        type=parse_discount_pct,
        default=0.0,
        help="Private Pricing Agreement (PPA) or Enterprise Discount Program (EDP) discount percentage, applied to every cost dimension (e.g. 15 for 15%% off)",
    )
    p.add_argument(
        "--broker-classes",
        type=parse_broker_classes,
        default="standard,express",
        metavar="standard|express|standard,express",
        help="Broker classes to size and report. Pass 'express' to suppress Standard results entirely",
    )
    p.add_argument(
        "--broker-quota",
        type=int,
        default=DEFAULT_BROKER_QUOTA,
        help="Per-cluster broker quota used to pick a 'recommended' instance per class (default 60 for KRaft clusters, 30 for Zookeeper, can be increased via AWS Support case)",
    )
    args = p.parse_args()

    if not args.emit_static_pricing:
        missing = [
            "--" + name.replace("_", "-")
            for name in _REQUIRED_WORKLOAD_ARGS
            if getattr(args, name) is None
        ]
        if missing:
            p.error("the following arguments are required: " + ", ".join(missing))

    return args


# Required for sizing, but not for --emit-static-pricing. Enforced in _parse_args().
_REQUIRED_WORKLOAD_ARGS = (
    "avg_data_in_mbs",
    "peak_data_in_mbs",
    "avg_data_out_mbs",
    "peak_data_out_mbs",
    "num_partitions",
    "retention_hours",
    "primary_retention_hours",
)


def parse_discount_pct(value: str) -> float:
    """Validate a --discount-pct value as a percentage in [0, 100)."""
    try:
        pct = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid discount percentage {value!r}; expected a number"
        )
    if not 0 <= pct < 100:
        raise argparse.ArgumentTypeError(f"discount percentage must be >= 0 and < 100; got {value}")
    return pct


def _pricing_provenance(source: str) -> str:
    """One sentence naming where the printed prices came from, for the output banner."""
    if source == "static":
        return (
            "from rates embedded in this script, captured on "
            f"{STATIC_PRICING_CAPTURED} (NOT fetched live, and possibly stale — re-run with\n"
            "--pricing-source api to confirm against current published pricing)"
        )
    return "fetched live via the AWS Pricing API"


def _format_pricing_banner(discount_pct: float, region: str, source: str = "api") -> str:
    provenance = _pricing_provenance(source)
    if discount_pct == 0:
        return (
            f"\nNOTE: all cost figures below use {region} public on-demand pricing,\n"
            f"{provenance}; other regions will differ.\n"
            "If your organization has a Private Pricing Agreement (PPA), Enterprise Discount\n"
            "Program (EDP), or other negotiated pricing, your actual costs will differ. Contact\n"
            "your AWS account team for pricing that reflects your agreements, then re-run with\n"
            "--discount-pct to model them."
        )
    return (
        f"\nNOTE: cost figures below apply a {discount_pct:g}% negotiated discount to every cost\n"
        f"dimension, based on {region} on-demand pricing {provenance}.\n"
        "Confirm the discount against your agreement with your AWS account team before sharing\n"
        "these figures."
    )


def format_static_pricing_literals(pricing: Pricing) -> str:
    """Render *pricing* as Python literals for refreshing the STATIC_* tables."""
    lines = [
        f'STATIC_PRICING_REGION = "{pricing.region}"',
        f'STATIC_PRICING_CAPTURED = "{date.today().isoformat()}"',
        "",
        "STATIC_BROKER_PRICE_PER_HR = {",
    ]
    for instance_type in INSTANCE_SPECS:
        price = pricing.broker_price_per_hr.get(instance_type)
        if price is not None:
            lines.append(f'    "{instance_type}": {price:g},')
    lines += [
        "}",
        "",
        "STATIC_SHARED_PRICING = {",
        f'    "ebs_cost_per_gb_month": {pricing.ebs_cost_per_gb_month:g},',
        f'    "tiered_storage_cost_per_gb_month": {pricing.tiered_storage_cost_per_gb_month:g},',
        f'    "express_storage_cost_per_gb_month": '
        f"{pricing.express_storage_cost_per_gb_month:g},",
        f'    "express_data_in_per_gb": {pricing.express_data_in_per_gb:g},',
        f'    "cross_az_cost_per_gb": {pricing.cross_az_cost_per_gb:g},',
        f'    "pst_cost_per_mbs_month": {pricing.pst_cost_per_mbs_month:g},',
        "}",
    ]
    return "\n".join(lines)


def _inputs_from_args(a) -> SizingInputs:
    return SizingInputs(
        avg_data_in_mbs=a.avg_data_in_mbs,
        peak_data_in_mbs=a.peak_data_in_mbs,
        avg_data_out_mbs=a.avg_data_out_mbs,
        peak_data_out_mbs=a.peak_data_out_mbs,
        num_partitions=a.num_partitions,
        replication_factor=a.replication_factor,
        retention_hours=a.retention_hours,
        primary_retention_hours=a.primary_retention_hours,
        utilization_standard=a.utilization_standard,
        utilization_express=a.utilization_express,
        pst_per_broker_mbs=a.pst_per_broker_mbs,
        use_max_partitions=a.use_max_partitions,
        rack_affined_consumers=a.rack_affined_consumers,
    )


if __name__ == "__main__":
    args = _parse_args()
    broker_classes = args.broker_classes

    try:
        pricing = resolve_pricing(args.region, broker_classes, args.pricing_source)
    except PricingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.emit_static_pricing:
        print(format_static_pricing_literals(pricing))
        sys.exit(0)

    inputs = _inputs_from_args(args)
    partition_mode = "maximum" if inputs.use_max_partitions else "recommended"

    standard_results = (
        calculate_standard_sizing(inputs, pricing, args.discount_pct)
        if "standard" in broker_classes
        else []
    )
    express_results = (
        calculate_express_sizing(inputs, pricing, args.discount_pct)
        if "express" in broker_classes
        else []
    )
    all_results = standard_results + express_results

    print(_format_pricing_banner(args.discount_pct, args.region, pricing.source))

    if all_results:
        print("\n=== Sizing inputs ===")
        print(
            _format_inputs_block(
                inputs, all_results, args.discount_pct, args.region, pricing.source
            )
        )

    section_suffix = f"using {partition_mode} partition limits per broker"

    if standard_results:
        _print_sizing_section(f"Standard Sizing ({section_suffix})", standard_results)

    if express_results:
        _print_sizing_section(f"Express Sizing ({section_suffix})", express_results)

    _print_recommendations(
        all_results,
        broker_quota=args.broker_quota,
        broker_classes=broker_classes,
    )
