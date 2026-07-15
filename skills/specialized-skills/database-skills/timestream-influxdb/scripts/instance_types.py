#!/usr/bin/env python3
"""Timestream for InfluxDB instance type reference and sizing helper."""

INSTANCE_TYPES = {
    "db.influx.medium": {"vcpu": 1, "memory_gib": 8, "network": "Up to 10 Gbps"},
    "db.influx.large": {"vcpu": 2, "memory_gib": 16, "network": "Up to 10 Gbps"},
    "db.influx.xlarge": {"vcpu": 4, "memory_gib": 32, "network": "Up to 10 Gbps"},
    "db.influx.2xlarge": {"vcpu": 8, "memory_gib": 64, "network": "Up to 10 Gbps"},
    "db.influx.4xlarge": {"vcpu": 16, "memory_gib": 128, "network": "Up to 10 Gbps"},
    "db.influx.8xlarge": {"vcpu": 32, "memory_gib": 256, "network": "10 Gbps"},
    "db.influx.12xlarge": {"vcpu": 48, "memory_gib": 384, "network": "12 Gbps"},
    "db.influx.16xlarge": {"vcpu": 64, "memory_gib": 512, "network": "20 Gbps"},
    "db.influx.24xlarge": {"vcpu": 96, "memory_gib": 768, "network": "25 Gbps"},
}


def list_types():
    print(f"{'Instance Type':<25} {'vCPU':>5} {'Memory (GiB)':>13} {'Network':<15}")
    print("-" * 60)
    for name, spec in INSTANCE_TYPES.items():
        print(f"{name:<25} {spec['vcpu']:>5} {spec['memory_gib']:>13} {spec['network']:<15}")


def recommend(write_rate_per_sec: int, query_concurrency: int, data_retention_days: int):
    """Simple sizing recommendation based on workload parameters."""
    if write_rate_per_sec < 1000 and query_concurrency < 5:
        rec = "db.influx.medium"
    elif write_rate_per_sec < 10000 and query_concurrency < 20:
        rec = "db.influx.large"
    elif write_rate_per_sec < 50000 and query_concurrency < 50:
        rec = "db.influx.xlarge"
    elif write_rate_per_sec < 100000:
        rec = "db.influx.2xlarge"
    else:
        rec = "db.influx.4xlarge"
    # Bump up for high-retention workloads (more storage and memory pressure)
    type_names = list(INSTANCE_TYPES.keys())
    idx = type_names.index(rec)
    if data_retention_days > 365:
        idx = min(idx + 2, len(type_names) - 1)
    elif data_retention_days > 90:
        idx = min(idx + 1, len(type_names) - 1)
    rec = type_names[idx]
    spec = INSTANCE_TYPES[rec]
    print(f"Recommended: {rec} ({spec['vcpu']} vCPU, {spec['memory_gib']} GiB)")
    print(
        f"  Based on: {write_rate_per_sec} writes/s, {query_concurrency} concurrent queries, {data_retention_days}d retention"
    )
    print(f"  Note: This is a starting point. Monitor CloudWatch metrics and adjust.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "recommend":
        recommend(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    else:
        list_types()
