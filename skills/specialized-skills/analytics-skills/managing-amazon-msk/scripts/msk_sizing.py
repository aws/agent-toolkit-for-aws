import argparse
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# NOTE: Pricing Region - ALL PRICING IN THIS FILE IS BASED ON us-east-1 (N. Virginia) RATES.
# Costs in other regions will differ. For another region, replace the relevant constants and per-instance
# `price_per_hr` values with that region's published pricing
# (see https://aws.amazon.com/msk/pricing/ and https://aws.amazon.com/ec2/pricing/).

PRICING_REGION = "us-east-1"

# NOTE: Unit Convention - All throughput is in **MiB/s**, all storage is in **GiB**
# Conversions use the binary factor 1024 (e.g., MiB/s × 3600 / 1024 → GiB/h).
#
# AWS lists provisioned storage throughput in MiB/s (per the MSK docs) and
# bills storage at "$/GB-month" where GB == GiB per the AWS Service Terms.
# Variable names ending in `_mbs` and `_gb` are kept for backwards compatibility
# but should be read as MiB/s and GiB throughout this file. CLI prompts, help
# strings, and explain output use the precise unit names.

# NOTE: Instance Specifications
# Standard (M5 / M7g):
#   ebs_throughput_mbs     – maximum provisionable EBS volume throughput per broker (MiB/s);
#                            also used as the documented PST cap for the instance
#   network_throughput_mbs – NIC bandwidth available to the broker (MiB/s)
#   rec_partitions         – recommended max partitions per broker (leaders + followers)
#   max_partitions         – hard max partitions per broker
#   price_per_hr           – on-demand instance price (USD/hr)
#
# Express (M7g):
#   ingress_mbs    – max producer throughput per broker (MiB/s); used directly
#   rec_partitions, max_partitions, price_per_hr as above

INSTANCE_SPECS = {
    "kafka.m5.large": {
        "ebs_throughput_mbs": 81.0,
        "network_throughput_mbs": 96,
        "rec_partitions": 1000,
        "max_partitions": 1500,
        "price_per_hr": 0.21,
    },
    "kafka.m5.xlarge": {
        "ebs_throughput_mbs": 144.0,
        "network_throughput_mbs": 160,
        "rec_partitions": 1000,
        "max_partitions": 1500,
        "price_per_hr": 0.42,
    },
    "kafka.m5.2xlarge": {
        "ebs_throughput_mbs": 250.0,
        "network_throughput_mbs": 320,
        "rec_partitions": 2000,
        "max_partitions": 3000,
        "price_per_hr": 0.84,
    },
    "kafka.m5.4xlarge": {
        "ebs_throughput_mbs": 593.75,
        "network_throughput_mbs": 640,
        "rec_partitions": 4000,
        "max_partitions": 6000,
        "price_per_hr": 1.68,
    },
    "kafka.m5.8xlarge": {
        "ebs_throughput_mbs": 850.0,
        "network_throughput_mbs": 1280,
        "rec_partitions": 4000,
        "max_partitions": 6000,
        "price_per_hr": 3.36,
    },
    "kafka.m5.12xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 1536,
        "rec_partitions": 4000,
        "max_partitions": 6000,
        "price_per_hr": 5.04,
    },
    "kafka.m5.16xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 2560,
        "rec_partitions": 4000,
        "max_partitions": 6000,
        "price_per_hr": 6.72,
    },
    "kafka.m5.24xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 3200,
        "rec_partitions": 4000,
        "max_partitions": 4000,
        "price_per_hr": 10.08,
    },
    "kafka.m7g.large": {
        "ebs_throughput_mbs": 78.75,
        "network_throughput_mbs": 117,
        "rec_partitions": 1000,
        "max_partitions": 1500,
        "price_per_hr": 0.204,
    },
    "kafka.m7g.xlarge": {
        "ebs_throughput_mbs": 156.25,
        "network_throughput_mbs": 234,
        "rec_partitions": 1000,
        "max_partitions": 1500,
        "price_per_hr": 0.408,
    },
    "kafka.m7g.2xlarge": {
        "ebs_throughput_mbs": 312.5,
        "network_throughput_mbs": 469,
        "rec_partitions": 2000,
        "max_partitions": 3000,
        "price_per_hr": 0.816,
    },
    "kafka.m7g.4xlarge": {
        "ebs_throughput_mbs": 625.0,
        "network_throughput_mbs": 937,
        "rec_partitions": 4000,
        "max_partitions": 6000,
        "price_per_hr": 1.632,
    },
    "kafka.m7g.8xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 1875,
        "rec_partitions": 4000,
        "max_partitions": 6000,
        "price_per_hr": 3.264,
    },
    "kafka.m7g.12xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 2812,
        "rec_partitions": 4000,
        "max_partitions": 6000,
        "price_per_hr": 4.896,
    },
    "kafka.m7g.16xlarge": {
        "ebs_throughput_mbs": 1000.0,
        "network_throughput_mbs": 3750,
        "rec_partitions": 4000,
        "max_partitions": 6000,
        "price_per_hr": 6.528,
    },
    "kafka.m7g.large (Express)": {
        "ingress_mbs": 15.625,
        "rec_partitions": 1000,
        "max_partitions": 1500,
        "price_per_hr": 0.408,
    },
    "kafka.m7g.xlarge (Express)": {
        "ingress_mbs": 31.25,
        "rec_partitions": 1000,
        "max_partitions": 2000,
        "price_per_hr": 0.816,
    },
    "kafka.m7g.2xlarge (Express)": {
        "ingress_mbs": 62.5,
        "rec_partitions": 2500,
        "max_partitions": 4000,
        "price_per_hr": 1.632,
    },
    "kafka.m7g.4xlarge (Express)": {
        "ingress_mbs": 125.0,
        "rec_partitions": 6000,
        "max_partitions": 8000,
        "price_per_hr": 3.264,
    },
    "kafka.m7g.8xlarge (Express)": {
        "ingress_mbs": 250.0,
        "rec_partitions": 12000,
        "max_partitions": 16000,
        "price_per_hr": 6.528,
    },
    "kafka.m7g.12xlarge (Express)": {
        "ingress_mbs": 375.0,
        "rec_partitions": 16000,
        "max_partitions": 24000,
        "price_per_hr": 9.792,
    },
    "kafka.m7g.16xlarge (Express)": {
        "ingress_mbs": 500.0,
        "rec_partitions": 20000,
        "max_partitions": 32000,
        "price_per_hr": 13.056,
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

# Cost constants for sizing dimensions in us-east-1
EBS_COST_PER_GB_MONTH = 0.10
TIERED_STORAGE_COST_PER_GB_MONTH = 0.023
EXPRESS_DATA_IN_PER_GB = 0.01
CROSS_AZ_COST_PER_GB = 0.02
PST_COST_PER_MBS_MONTH = 0.08

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


def calculate_standard_sizing(inputs: SizingInputs) -> List[SizingResult]:
    """Calculate sizing for all Standard (M5 / M7g) instance types."""
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

    monthly_ebs_cost = ebs_gb * EBS_COST_PER_GB_MONTH
    monthly_ts_cost = ts_gb * TIERED_STORAGE_COST_PER_GB_MONTH

    pst_mbs_per_broker = inputs.pst_per_broker_mbs or 0.0

    cross_az_mbs = inputs.avg_data_in_mbs * (NUM_AZS - 1) / NUM_AZS
    if not inputs.rack_affined_consumers:
        cross_az_mbs += inputs.avg_data_out_mbs * (NUM_AZS - 1) / NUM_AZS
    cross_az_gb_mo = cross_az_mbs * 3600 * HOURS_PER_MONTH / 1024
    monthly_cross_az_cost = cross_az_gb_mo * CROSS_AZ_COST_PER_GB

    fan_out = inputs.peak_data_out_mbs / inputs.peak_data_in_mbs
    network_factor = fan_out * AZ_SCALE_FACTOR + network_base

    partition_key = "max_partitions" if inputs.use_max_partitions else "rec_partitions"

    for instance_type, specs in INSTANCE_SPECS.items():
        if "Express" in instance_type:
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
                unit=f"MiB/s avg egress (PST cap {effective_pst:.0f}; instance max {specs['ebs_throughput_mbs']:.0f})",
            )

        broker_count = max(d.brokers_needed for d in details.values())
        bottleneck = max(details, key=lambda k: details[k].brokers_needed)

        monthly_broker_cost = broker_count * specs["price_per_hr"] * HOURS_PER_MONTH

        if pst_mbs_per_broker > 0 and instance_type in PST_ELIGIBLE:
            effective_pst_mbs = min(pst_mbs_per_broker, specs["ebs_throughput_mbs"])
            monthly_pst_cost = broker_count * effective_pst_mbs * PST_COST_PER_MBS_MONTH
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


def calculate_express_sizing(inputs: SizingInputs) -> List[SizingResult]:
    """Calculate sizing for all Express (M7g) instance types."""
    results = []

    cross_az_mbs = inputs.avg_data_in_mbs * (NUM_AZS - 1) / NUM_AZS
    if not inputs.rack_affined_consumers:
        cross_az_mbs += inputs.avg_data_out_mbs * (NUM_AZS - 1) / NUM_AZS
    cross_az_gb_mo = cross_az_mbs * 3600 * HOURS_PER_MONTH / 1024
    monthly_cross_az_cost = cross_az_gb_mo * CROSS_AZ_COST_PER_GB

    data_in_gb_mo = inputs.avg_data_in_mbs * 3600 * HOURS_PER_MONTH / 1024
    monthly_data_in_cost = data_in_gb_mo * EXPRESS_DATA_IN_PER_GB

    express_storage_gb = inputs.avg_data_in_mbs * inputs.retention_hours * 3600 / 1024
    monthly_express_storage_cost = express_storage_gb * EBS_COST_PER_GB_MONTH

    partition_key = "max_partitions" if inputs.use_max_partitions else "rec_partitions"

    for instance_type, specs in INSTANCE_SPECS.items():
        if "Express" not in instance_type:
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

        monthly_broker_cost = broker_count * specs["price_per_hr"] * HOURS_PER_MONTH

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


def _format_summary_line(r: SizingResult) -> str:
    return (
        f"{r.instance_type}: {r.broker_count} brokers "
        f"(bottleneck: {r.bottleneck}) → ${r.total_monthly_cost:,.2f}/mo"
    )


def _format_explain_block(r: SizingResult) -> str:
    lines = [f"\n{r.instance_type}: {r.broker_count} brokers (bottleneck: {r.bottleneck})"]

    lines.append("  Constraint analysis (brokers needed, rounded up to multiple of AZs):")

    sorted_details = sorted(
        r.bottleneck_details.values(),
        key=lambda d: d.brokers_needed,
        reverse=True,
    )
    for d in sorted_details:
        marker = " ← bottleneck" if d.name == r.bottleneck else ""
        lines.append(
            f"    {d.name:<11} {d.brokers_needed:>5} brokers  "
            f"(demand {d.demand:,.2f} / capacity {d.per_broker_capacity:,.2f} per broker) "
            f"[{d.unit}]{marker}"
        )

    lines.append("  Monthly cost breakdown:")
    cost_rows = [
        ("Brokers", r.monthly_broker_cost),
        ("Storage", r.monthly_ebs_cost),
        ("Tiered Storage", r.monthly_ts_cost),
        ("Provisioned ST", r.monthly_pst_cost),
        ("Express data-in", r.monthly_data_in_cost),
        ("Cross-AZ", r.monthly_cross_az_cost),
    ]
    for label, cost in cost_rows:
        if cost > 0:
            pct = (cost / r.total_monthly_cost * 100) if r.total_monthly_cost else 0
            lines.append(f"    {label:<16} ${cost:>14,.2f}  ({pct:5.1f}%)")
    lines.append(f"    {'Total':<16} ${r.total_monthly_cost:>14,.2f}")
    return "\n".join(lines)


def _print_recommendations(
    results: List[SizingResult],
    broker_quota: int,
    explain: bool,
) -> None:
    recs = recommend_per_class(results, broker_quota=broker_quota)
    print(f"\n=== Recommended pick per class (≤ {broker_quota} brokers, lowest monthly cost) ===")
    for cls in ("m5_standard", "m7g_standard", "express"):
        label = _CLASS_LABELS[cls]
        rec = recs[cls]
        if rec is None:
            print(
                f"  {label}: no instance fits within {broker_quota} brokers — request a quota increase or pick a larger size"
            )
        else:
            print(f"  {label}: {_format_summary_line(rec)}")
            if explain:
                print(_format_explain_block(rec))


def _parse_args():
    p = argparse.ArgumentParser(
        description=(
            "MSK broker sizing calculator. "
            f"NOTE: all cost figures use {PRICING_REGION} on-demand pricing; "
            "other regions will differ."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--avg-data-in-mbs", type=float, required=True, help="Average producer throughput (MiB/s)"
    )
    p.add_argument(
        "--peak-data-in-mbs", type=float, required=True, help="Peak producer throughput (MiB/s)"
    )
    p.add_argument(
        "--avg-data-out-mbs", type=float, required=True, help="Average consumer throughput (MiB/s)"
    )
    p.add_argument(
        "--peak-data-out-mbs", type=float, required=True, help="Peak consumer throughput (MiB/s)"
    )
    p.add_argument(
        "--num-partitions", type=int, required=True, help="Total partitions including replicas"
    )
    p.add_argument("--replication-factor", type=int, default=3, help="Kafka replication factor")
    p.add_argument(
        "--retention-hours", type=int, required=True, help="Total data retention (hours)"
    )
    p.add_argument(
        "--primary-retention-hours",
        type=int,
        required=True,
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
        "--explain",
        action="store_true",
        help="Print per-constraint and per-cost-factor breakdown for every instance",
    )
    p.add_argument(
        "--broker-quota",
        type=int,
        default=DEFAULT_BROKER_QUOTA,
        help="Per-cluster broker quota used to pick a 'recommended' instance per class (default 60 for KRaft clusters, 30 for Zookeeper, can be increased via AWS Support case)",
    )
    return p.parse_args()


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
    inputs = _inputs_from_args(args)
    partition_mode = "max" if inputs.use_max_partitions else "recommended"

    standard_results = calculate_standard_sizing(inputs)
    express_results = calculate_express_sizing(inputs)
    all_results = standard_results + express_results

    print(
        f"\nNOTE: all cost figures below use {PRICING_REGION} on-demand pricing; other regions will differ."
    )

    print(f"\n=== Standard Sizing ({partition_mode} partitions) ===")
    for r in standard_results:
        print(_format_summary_line(r))
        if args.explain:
            print(_format_explain_block(r))

    print(f"\n=== Express Sizing ({partition_mode} partitions) ===")
    for r in express_results:
        print(_format_summary_line(r))
        if args.explain:
            print(_format_explain_block(r))

    _print_recommendations(all_results, broker_quota=args.broker_quota, explain=args.explain)
