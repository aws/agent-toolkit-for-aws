#!/usr/bin/env python3
"""Deterministically regenerate live-capture/ for the gcp-utilization-capture fixture (see README.md).

Run from anywhere: python3 make_fixture.py. Then refresh the golden summary with
summarize-monitoring.py (command in README.md). Re-running must produce no git diff.
"""
from __future__ import annotations
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
HERE = Path(__file__).resolve().parent
OUT = HERE / "live-capture"
PROJECT = "acme-prod"
ZONE = "us-central1-a"
REGION = "us-central1"
WINDOW_START = datetime(2026, 11, 13, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 11, 20, tzinfo=timezone.utc)
HOURS = 168
SEED = 20261120
COMPUTE = f"https://www.googleapis.com/compute/v1/projects/{PROJECT}"
rng = random.Random(SEED)
def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
# Hourly aligned endTimes, newest first, covering (WINDOW_START, WINDOW_END].
END_TIMES = [WINDOW_END - timedelta(hours=i) for i in range(HOURS)]
def points(values, int64: bool = False, end_times=None) -> list[dict]:
    out = []
    for dt, value in zip(end_times or END_TIMES, values):
        stamp = ts(dt)
        payload = {"int64Value": str(int(value))} if int64 else {"doubleValue": round(float(value), 6)}
        out.append({"interval": {"startTime": stamp, "endTime": stamp}, "value": payload})
    return out
def gce_series(metric_type: str, instance_id: str, metric_labels: dict, pts: list[dict], unit: str | None = None) -> dict:
    series = {
        "metric": {"labels": metric_labels, "type": metric_type},
        "resource": {"type": "gce_instance", "labels": {"zone": ZONE, "instance_id": instance_id, "project_id": PROJECT}},
        "metricKind": "GAUGE",
        "valueType": "DOUBLE",
        "points": pts,
    }
    if unit is not None:
        series["unit"] = unit
    return series
def sql_series(metric_type: str, name: str, metric_labels: dict | None, pts: list[dict], value_type: str = "DOUBLE") -> dict:
    metric = {"type": metric_type}
    if metric_labels:
        metric["labels"] = metric_labels
    return {
        "metric": metric,
        "resource": {"type": "cloudsql_database", "labels": {"region": REGION, "project_id": PROJECT, "database_id": f"{PROJECT}:{name}"}},
        "metricKind": "GAUGE",
        "valueType": value_type,
        "points": pts,
    }
def uniform_series(low: float, high: float, n: int = HOURS) -> list[float]:
    return [rng.uniform(low, high) for _ in range(n)]
def write(name: str, obj) -> None:
    (OUT / name).write_text(json.dumps(obj, separators=(",", ":")) + "\n", encoding="utf-8")
def write_pretty(name: str, obj) -> None:
    (OUT / name).write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
def page(unit: str, series: list[dict], token: str | None = None) -> dict:
    out: dict = {}
    if series:
        out["timeSeries"] = series
    if token:
        out["nextPageToken"] = token
    out["unit"] = unit
    return out
# ---------------------------------------------------------------- VMs
VMS = [
    # name, machine type, instance id, cpu (low, high), mem used % (low, high), hours present
    ("web-steady", "n2-standard-8", "1000000000000000001", (0.06, 0.125), (8.0, 15.5), HOURS),
    ("api-lowload", "n2-standard-8", "1000000000000000002", (0.04, 0.085), (5.0, 8.5), HOURS),
    ("cache-heavy", "n2-standard-8", "1000000000000000003", (0.06, 0.125), (55.0, 63.5), HOURS),
    ("batch-bursty", "n2-standard-8", "1000000000000000004", (0.05, 0.105), None, HOURS),
    ("new-vm", "e2-standard-2", "1000000000000000005", (0.10, 0.30), (20.0, 35.0), 100),
    ("idle-vm", "n2-standard-2", "1000000000000000006", (0.005, 0.012), (8.0, 10.5), HOURS),
    ("web-mig-7f3k", "e2-medium", "1000000000000000007", (0.10, 0.30), (30.0, 45.0), HOURS),
    ("ops-small", "e2-small", "1000000000000000008", (0.70, 1.25), (21.0, 39.0), HOURS),
]
CPU = "compute.googleapis.com/instance/cpu/utilization"
MEM = "agent.googleapis.com/memory/percent_used"
def build_gce() -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    gce_json, cpu_mean, cpu_max, mem_mean, mem_max = [], [], [], [], []
    for name, machine_type, instance_id, cpu_range, mem_range, hours in VMS:
        gce_json.append({
            "disks": [{"diskSizeGb": "50"}],
            "id": instance_id,
            "labels": {"env": "prod"},
            "machineType": f"{COMPUTE}/zones/{ZONE}/machineTypes/{machine_type}",
            "name": name,
            "networkInterfaces": [{"network": f"{COMPUTE}/global/networks/main",
                                   "subnetwork": f"{COMPUTE}/regions/{REGION}/subnetworks/main"}],
            "status": "RUNNING",
            "zone": f"{COMPUTE}/zones/{ZONE}",
        })
        means = uniform_series(*cpu_range, n=hours)
        maxes = [m + rng.uniform(0.02, 0.08) for m in means]
        if name == "web-steady":
            means[50], maxes[50] = 0.12, 0.9  # one hot max with an ordinary mean: never a burst
        if name == "batch-bursty":
            means[40], means[41] = 0.6, 0.6  # two consecutive hot hourly means: burst
            maxes[40], maxes[41] = 0.95, 0.93
        if name == "ops-small":
            maxes[12] = 1.965  # shared-core CPU exceeds 1.0 and stays unclamped
        cpu_mean.append(gce_series(CPU, instance_id, {"instance_name": name}, points(means)))
        cpu_max.append(gce_series(CPU, instance_id, {"instance_name": name}, points(maxes)))
        if mem_range is None:
            continue
        used = uniform_series(*mem_range, n=hours)
        used_max = [u + rng.uniform(0.5, 2.0) for u in used]
        if name == "ops-small":
            # Ops Agent reports all five states; this VM's series carry a per-series unit.
            states = {
                "used": (used, used_max),
                "free": ([100 - u - 30 for u in used], [100 - u - 29 for u in used]),
                "cached": (uniform_series(20.0, 24.0, n=hours), uniform_series(24.0, 26.0, n=hours)),
                "buffered": (uniform_series(0.8, 1.2, n=hours), uniform_series(1.2, 1.4, n=hours)),
                "slab": (uniform_series(4.0, 5.0, n=hours), uniform_series(5.0, 5.5, n=hours)),
            }
            for state, (mean_values, max_values) in states.items():
                mem_mean.append(gce_series(MEM, instance_id, {"state": state}, points(mean_values), unit="%"))
                mem_max.append(gce_series(MEM, instance_id, {"state": state}, points(max_values), unit="%"))
        else:
            mem_mean.append(gce_series(MEM, instance_id, {"state": "used"}, points(used)))
            mem_max.append(gce_series(MEM, instance_id, {"state": "used"}, points(used_max)))
    return gce_json, cpu_mean, cpu_max, mem_mean, mem_max
# ---------------------------------------------------------------- Cloud SQL
SQL_CPU = "cloudsql.googleapis.com/database/cpu/utilization"
SQL_MEM = "cloudsql.googleapis.com/database/memory/utilization"
SQL_DISK = "cloudsql.googleapis.com/database/disk/bytes_used"
SQL_CONN = "cloudsql.googleapis.com/database/network/connections"
SQL_PGCONN = "cloudsql.googleapis.com/database/postgresql/num_backends"
ORDERS_DISK = 87293952
REPORTS_DISK = 12 * 1024 ** 3
def build_sql() -> tuple[list[dict], dict[str, dict]]:
    sql_json = [
        {"databaseVersion": "POSTGRES_15", "name": "orders-db", "region": REGION,
         "settings": {"availabilityType": "ZONAL", "dataDiskSizeGb": "10", "dataDiskType": "PD_HDD", "tier": "db-f1-micro"}},
        {"databaseVersion": "MYSQL_8_0", "name": "reports-db", "region": REGION,
         "settings": {"availabilityType": "ZONAL", "dataDiskSizeGb": "50", "dataDiskType": "PD_SSD", "tier": "db-custom-2-8192"}},
    ]
    files: dict[str, dict] = {}
    # orders-db: values seeded from a real db-f1-micro (cpu ~0.10, memory 0.999-1.0, disk constant).
    orders_cpu_mean = uniform_series(0.085, 0.11)
    orders_cpu_max = [m + rng.uniform(0.01, 0.05) for m in orders_cpu_mean]
    orders_mem_mean = uniform_series(0.999, 1.0)
    orders_mem_max = [min(m + 0.0005, 1.0) for m in orders_mem_mean]
    reports_cpu_mean = uniform_series(0.2, 0.31)
    reports_cpu_max = [m + rng.uniform(0.05, 0.2) for m in reports_cpu_mean]
    reports_mem_mean = uniform_series(0.45, 0.51)
    reports_mem_max = [m + rng.uniform(0.005, 0.02) for m in reports_mem_mean]
    reports_disk = [REPORTS_DISK + (HOURS - i) * 4096 for i in range(HOURS)]
    reports_conn_max = [rng.randint(10, 40) for _ in range(HOURS)]
    reports_conn_mean = [c - rng.uniform(0.0, 4.0) for c in reports_conn_max]
    # The orders-db ALIGN_MEAN cpu series carries one extra point at endTime == window start (an
    # unaligned-window partial bucket that the script must drop).
    extra_end = [WINDOW_START]
    orders_cpu_mean_points = points(orders_cpu_mean) + points([0.0973], end_times=extra_end)
    files["monitoring-sql-cpu-ALIGN_MEAN-p1.json"] = page("10^2.%", [
        sql_series(SQL_CPU, "orders-db", None, orders_cpu_mean_points),
        sql_series(SQL_CPU, "reports-db", None, points(reports_cpu_mean)),
    ])
    files["monitoring-sql-cpu-ALIGN_MAX-p1.json"] = page("10^2.%", [
        sql_series(SQL_CPU, "orders-db", None, points(orders_cpu_max)),
        sql_series(SQL_CPU, "reports-db", None, points(reports_cpu_max)),
    ])
    files["monitoring-sql-mem-ALIGN_MEAN-p1.json"] = page("1", [
        sql_series(SQL_MEM, "orders-db", None, points(orders_mem_mean)),
        sql_series(SQL_MEM, "reports-db", None, points(reports_mem_mean)),
    ])
    files["monitoring-sql-mem-ALIGN_MAX-p1.json"] = page("1", [
        sql_series(SQL_MEM, "orders-db", None, points(orders_mem_max)),
        sql_series(SQL_MEM, "reports-db", None, points(reports_mem_max)),
    ])
    files["monitoring-sql-disk-ALIGN_MEAN-p1.json"] = page("By", [
        sql_series(SQL_DISK, "orders-db", None, points([ORDERS_DISK] * HOURS)),
        sql_series(SQL_DISK, "reports-db", None, points(reports_disk)),
    ])
    files["monitoring-sql-disk-ALIGN_MAX-p1.json"] = page("By", [
        sql_series(SQL_DISK, "orders-db", None, points([ORDERS_DISK] * HOURS, int64=True), value_type="INT64"),
        sql_series(SQL_DISK, "reports-db", None, points(reports_disk, int64=True), value_type="INT64"),
    ])
    # network/connections exists for MySQL/SQL Server only: reports-db has a series, orders-db does not.
    files["monitoring-sql-conn-ALIGN_MEAN-p1.json"] = page("1", [
        sql_series(SQL_CONN, "reports-db", None, points(reports_conn_mean)),
    ])
    files["monitoring-sql-conn-ALIGN_MAX-p1.json"] = page("1", [
        sql_series(SQL_CONN, "reports-db", None, points(reports_conn_max, int64=True), value_type="INT64"),
    ])
    # num_backends: one series per database, one series per page, pageSize=1000 counts points.
    backends_max = {
        "orders": [rng.randint(0, 3) for _ in range(HOURS)],
        "cloudsqladmin": [2] * HOURS,
        "postgres": [0] * HOURS,
        "template1": [0] * HOURS,
    }
    backends_mean = {db: [max(v - rng.choice([0, 0.25, 0.5]), 0.0) if db == "orders" else float(v) for v in values]
                     for db, values in backends_max.items()}
    for index, db in enumerate(backends_max, start=1):
        token = f"page{index + 1}" if index < len(backends_max) else None
        files[f"monitoring-sql-pgconn-ALIGN_MEAN-p{index}.json"] = page("1", [
            sql_series(SQL_PGCONN, "orders-db", {"database": db}, points(backends_mean[db])),
        ], token)
        files[f"monitoring-sql-pgconn-ALIGN_MAX-p{index}.json"] = page("1", [
            sql_series(SQL_PGCONN, "orders-db", {"database": db}, points(backends_max[db], int64=True), value_type="INT64"),
        ], token)
    return sql_json, files
# ---------------------------------------------------------------- manifest
def curl_row(metric_type: str, aligner: str) -> str:
    return (f'curl ... https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries '
            f'filter=metric.type="{metric_type}" aggregation.alignmentPeriod=3600s aggregation.perSeriesAligner={aligner} pageSize=1000')
def build_manifest(monitoring_files: dict[str, int]) -> dict:
    """monitoring_files maps each written monitoring-*.json name to its byte size (discover-live.md Step 2d: byte sizes go in `note`)."""
    captures = [
        {"command": f"gcloud compute instances list --project={PROJECT} --format=json(id, name, zone, machineType, status, ...)",
         "file": "gce.json", "status": "ok", "note": None},
        {"command": f"gcloud sql instances list --project={PROJECT} --format=json(...)",
         "file": "sql.json", "status": "ok", "note": None},
        {"command": f'gcloud services list --enabled --project={PROJECT} --filter="config.name=monitoring.googleapis.com" --format="json(config.name)"',
         "file": "monitoring-api.json", "status": "ok", "note": None},
    ]
    series_rows = [
        ("gce-cpu", CPU), ("gce-mem", MEM), ("sql-cpu", SQL_CPU), ("sql-mem", SQL_MEM),
        ("sql-disk", SQL_DISK), ("sql-conn", SQL_CONN), ("sql-pgconn", SQL_PGCONN),
    ]
    for short, metric_type in series_rows:
        for aligner in ("ALIGN_MEAN", "ALIGN_MAX"):
            pages = sorted(f for f in monitoring_files if f.startswith(f"monitoring-{short}-{aligner}-p"))
            total = sum(monitoring_files[f] for f in pages)
            span = pages[0] if len(pages) == 1 else f"{pages[0]} .. {pages[-1]}"
            captures.append({
                "command": curl_row(metric_type, aligner),
                "file": pages[0],
                "status": "ok",
                "note": f"{len(pages)} page{'s' if len(pages) != 1 else ''} ({span}), {total} bytes",
            })
    captures.append({"command": f"gcloud compute instance-groups managed list --project={PROJECT} --format=json(name, zone, region)",
                     "file": "mig-groups.json", "status": "ok", "note": None})
    captures.append({"command": f"gcloud compute instance-groups managed list-instances web-mig --zone={ZONE} --project={PROJECT} --format=json(instance)",
                     "file": "mig-members-web-mig.json", "status": "ok", "note": None})
    return {
        "captured_at": ts(WINDOW_END),
        "gcloud_version": "Google Cloud SDK 532.0.0",
        "account": "founder@acme-demo.com",
        "project": PROJECT,
        "method": "per_service",
        "cai_enable_offered": True,
        "cai_enable_accepted": False,
        "captures": captures,
    }
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.json"):
        stale.unlink()
    gce_json, cpu_mean, cpu_max, mem_mean, mem_max = build_gce()
    sql_json, sql_files = build_sql()
    # gce-cpu ALIGN_MEAN is split across two pages: web-steady's series is cut at 100 points.
    web_steady = cpu_mean[0]
    first, rest = web_steady["points"][:100], web_steady["points"][100:]
    page1 = dict(web_steady, points=first)
    page2 = [dict(web_steady, points=rest)] + cpu_mean[1:]
    monitoring_files = {
        "monitoring-gce-cpu-ALIGN_MEAN-p1.json": page("10^2.%", [page1], "page2"),
        "monitoring-gce-cpu-ALIGN_MEAN-p2.json": page("10^2.%", page2),
        "monitoring-gce-cpu-ALIGN_MAX-p1.json": page("10^2.%", cpu_max),
        "monitoring-gce-mem-ALIGN_MEAN-p1.json": page("%", mem_mean),
        "monitoring-gce-mem-ALIGN_MAX-p1.json": page("%", mem_max),
        **sql_files,
    }
    sizes = {}
    for name, obj in monitoring_files.items():
        write(name, obj)
        sizes[name] = (OUT / name).stat().st_size
    write_pretty("gce.json", gce_json)
    write_pretty("sql.json", sql_json)
    write_pretty("monitoring-api.json", [{"config": {"name": "monitoring.googleapis.com"}}])
    write_pretty("mig-groups.json", [{"name": "web-mig", "region": None, "zone": f"{COMPUTE}/zones/{ZONE}"}])
    write_pretty("mig-members-web-mig.json", [{"instance": f"{COMPUTE}/zones/{ZONE}/instances/web-mig-7f3k"}])
    write_pretty("manifest.json", build_manifest(sizes))
if __name__ == "__main__":
    main()
