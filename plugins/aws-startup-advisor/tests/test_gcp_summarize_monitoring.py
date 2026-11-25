"""Behavior tests for skills/gcp-to-aws/scripts/summarize-monitoring.py (discover-live rows 21a-21n reduction)."""
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "skills" / "gcp-to-aws" / "scripts" / "summarize-monitoring.py"
FIXTURE = PLUGIN_ROOT / "fixtures" / "gcp-utilization-capture"
LIVE = FIXTURE / "live-capture"
EXPECTED = FIXTURE / "expected-utilization-summary.json"
PROJECT = "acme-prod"
ZONE = "us-central1-a"
WINDOW_START = datetime(2026, 11, 13, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 11, 20, tzinfo=timezone.utc)
HOURS = 168
COMPUTE = f"https://www.googleapis.com/compute/v1/projects/{PROJECT}"
GCE_CPU = "compute.googleapis.com/instance/cpu/utilization"
GCE_MEM = "agent.googleapis.com/memory/percent_used"
SQL_CPU = "cloudsql.googleapis.com/database/cpu/utilization"
SQL_PGCONN = "cloudsql.googleapis.com/database/postgresql/num_backends"
def _load_module():
    spec = importlib.util.spec_from_file_location("summarize_monitoring", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
sm = _load_module()
# ---------------------------------------------------------------- helpers
def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
def end_times(n: int = HOURS, end: datetime = WINDOW_END) -> list[datetime]:
    """Newest-first aligned hourly endTimes covering (end - n h, end]."""
    return [end - timedelta(hours=i) for i in range(n)]
def points(values, key: str = "doubleValue", ends=None) -> list[dict]:
    ends = ends or end_times(len(values))
    out = []
    for dt, value in zip(ends, values):
        stamp = _ts(dt)
        payload = {key: str(int(value))} if key == "int64Value" else {key: value}
        out.append({"interval": {"startTime": stamp, "endTime": stamp}, "value": payload})
    return out
def series(metric_type: str, resource_labels: dict, metric_labels: dict | None, values, key: str = "doubleValue",
           unit: str | None = None, ends=None, resource_type: str = "gce_instance") -> dict:
    metric = {"type": metric_type}
    if metric_labels:
        metric["labels"] = metric_labels
    out = {"metric": metric, "resource": {"type": resource_type, "labels": resource_labels}, "metricKind": "GAUGE",
           "valueType": "INT64" if key == "int64Value" else "DOUBLE", "points": points(values, key, ends)}
    if unit is not None:
        out["unit"] = unit
    return out
def page(unit, series_list, token=None) -> dict:
    out = {}
    if series_list:
        out["timeSeries"] = series_list
    if token:
        out["nextPageToken"] = token
    if unit is not None:
        out["unit"] = unit
    return out
def gce_labels(instance_id: str) -> dict:
    return {"zone": ZONE, "instance_id": instance_id, "project_id": PROJECT}
def sql_labels(name: str) -> dict:
    return {"region": "us-central1", "project_id": PROJECT, "database_id": f"{PROJECT}:{name}"}
def write(capture: Path, name: str, obj) -> None:
    (capture / name).write_text(json.dumps(obj), encoding="utf-8")
def _manifest_upsert(capture: Path, file: str, status: str) -> None:
    """Add or replace the manifest.json captures[] row for one monitoring file (Step 2c writes one per row)."""
    path = capture / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {
        "captured_at": "2026-11-20T00:00:00Z", "project": PROJECT, "captures": []}
    manifest["captures"] = [e for e in manifest["captures"] if e.get("file") != file]
    manifest["captures"].append({"command": "curl ...", "file": file, "status": status, "note": None})
    write(capture, "manifest.json", manifest)


def write_metric(capture: Path, short: str, aligner: str, pages: list[dict], manifest_status: str | None = "ok") -> None:
    """Write a row's pages and, unless manifest_status is None, its ok manifest row (as Step 2c does)."""
    for index, body in enumerate(pages, start=1):
        write(capture, f"monitoring-{short}-{aligner}-p{index}.json", body)
    if manifest_status is not None:
        _manifest_upsert(capture, f"monitoring-{short}-{aligner}-p1.json", manifest_status)
def gce_json(*vms: tuple[str, str, str]) -> list[dict]:
    return [{"id": iid, "name": name, "status": "RUNNING",
             "zone": f"{COMPUTE}/zones/{ZONE}",
             "machineType": f"{COMPUTE}/zones/{ZONE}/machineTypes/{mtype}"} for iid, name, mtype in vms]
def sql_json(*dbs: tuple[str, str, str]) -> list[dict]:
    return [{"name": name, "region": "us-central1", "databaseVersion": version, "settings": {"tier": tier}}
            for name, version, tier in dbs]
def summarize(capture: Path) -> dict:
    return sm.build_summary(capture, PROJECT, WINDOW_START, WINDOW_END)
def by_id(summary: dict, key: str) -> dict:
    return next(r for r in summary["resources"] if r.get("instance_id") == key or r.get("database_id") == key)
@pytest.fixture
def capture(tmp_path: Path) -> Path:
    cap = tmp_path / "live-capture"
    cap.mkdir()
    write(cap, "gce.json", [])
    write(cap, "sql.json", [])
    return cap
def simple_vm(capture: Path, iid: str = "1000000000000000001", cpu_means=None, cpu_maxes=None, mem_used=None,
              mem_unit="%") -> None:
    """One VM with full cpu coverage and (optionally) a used-memory series."""
    write(capture, "gce.json", gce_json((iid, "vm", "n2-standard-8")))
    cpu_means = cpu_means if cpu_means is not None else [0.10] * HOURS
    cpu_maxes = cpu_maxes if cpu_maxes is not None else [m + 0.05 for m in cpu_means]
    write_metric(capture, "gce-cpu", "ALIGN_MEAN", [page("10^2.%", [series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, cpu_means)])])
    write_metric(capture, "gce-cpu", "ALIGN_MAX", [page("10^2.%", [series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, cpu_maxes)])])
    if mem_used is not None:
        write_metric(capture, "gce-mem", "ALIGN_MEAN", [page(mem_unit, [series(GCE_MEM, gce_labels(iid), {"state": "used"}, mem_used)])])
        write_metric(capture, "gce-mem", "ALIGN_MAX", [page(mem_unit, [series(GCE_MEM, gce_labels(iid), {"state": "used"}, [v + 1 for v in mem_used])])])
# ---------------------------------------------------------------- paging
def test_paging_merges_a_series_split_across_pages(capture):
    iid = "1000000000000000001"
    values = [0.1 + i / 10000 for i in range(HOURS)]
    full = series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, values)
    first = dict(full, points=full["points"][:100])
    rest = dict(full, points=full["points"][100:])
    write_metric(capture, "gce-cpu", "ALIGN_MEAN", [page("10^2.%", [first], "tok"), page("10^2.%", [rest])])
    loaded = sm.load_metric(capture, "gce-cpu", "ALIGN_MEAN")
    assert loaded["status"] == "ok"
    assert len(loaded["series"]) == 1
    merged = next(iter(loaded["series"].values()))
    assert len(merged["points"]) == HOURS
    assert merged["unit"] == "10^2.%"
# ---------------------------------------------------------------- stale, failed and incomplete page sets
def manifest(capture: Path, rows: dict[str, str]) -> None:
    """Set the manifest.json status of each monitoring-<short>-<aligner>-p1.json row, replacing what write_metric recorded."""
    for key, status in rows.items():
        _manifest_upsert(capture, f"monitoring-{key}-p1.json", status)
@pytest.mark.parametrize("status", ["skipped", "failed"])
def test_manifest_row_not_ok_is_no_data_despite_pages_on_disk(capture, status):
    iid = "1000000000000000001"
    simple_vm(capture, iid)
    manifest(capture, {"gce-cpu-ALIGN_MEAN": status, "gce-cpu-ALIGN_MAX": "ok"})
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MEAN") == {"status": "no_data"}
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MAX")["status"] == "ok"
    vm = by_id(summarize(capture), iid)
    assert vm["cpu"] == {"status": "no_data"}
    assert vm["coverage"] == "no_data"
def test_manifest_row_ok_keeps_reducing(capture):
    iid = "1000000000000000001"
    simple_vm(capture, iid)
    manifest(capture, {"gce-cpu-ALIGN_MEAN": "ok"})
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MEAN")["status"] == "ok"
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MAX")["status"] == "ok"
    assert by_id(summarize(capture), iid)["coverage"] == "sufficient"


def test_missing_manifest_row_is_no_data_despite_pages_on_disk(capture):
    """A page set with no manifest row is stale output of an earlier run, not a capture of this one."""
    iid = "1000000000000000001"
    simple_vm(capture, iid)
    path = capture / "manifest.json"
    manifest_obj = json.loads(path.read_text(encoding="utf-8"))
    manifest_obj["captures"] = [e for e in manifest_obj["captures"] if e["file"] != "monitoring-gce-cpu-ALIGN_MEAN-p1.json"]
    write(capture, "manifest.json", manifest_obj)
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MEAN") == {"status": "no_data"}
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MAX")["status"] == "ok"
    assert by_id(summarize(capture), iid)["cpu"] == {"status": "no_data"}


@pytest.mark.parametrize("damage", ["missing", "unreadable", "no_captures"])
def test_missing_or_unreadable_manifest_is_no_data(capture, damage):
    iid = "1000000000000000001"
    simple_vm(capture, iid)
    path = capture / "manifest.json"
    if damage == "missing":
        path.unlink()
    elif damage == "unreadable":
        path.write_text("{not json", encoding="utf-8")
    else:
        write(capture, "manifest.json", {"captured_at": "2026-11-20T00:00:00Z", "project": PROJECT})
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MEAN") == {"status": "no_data"}
    assert by_id(summarize(capture), iid)["coverage"] == "no_data"
def test_http_error_envelope_is_no_data_not_an_empty_response(capture):
    iid = "1000000000000000001"
    simple_vm(capture, iid)
    envelope = {"error": {"code": 403, "message": "Permission monitoring.timeSeries.list denied", "status": "PERMISSION_DENIED"}}
    write_metric(capture, "gce-cpu", "ALIGN_MEAN", [envelope])
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MEAN") == {"status": "no_data"}
    assert by_id(summarize(capture), iid)["cpu"] == {"status": "no_data"}
def test_lone_first_page_with_next_page_token_is_no_data(capture):
    iid = "1000000000000000001"
    s = series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, [0.1] * HOURS)
    write_metric(capture, "gce-cpu", "ALIGN_MEAN", [page("10^2.%", [s], "tok")])
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MEAN") == {"status": "no_data"}
def test_gap_in_page_chain_is_no_data(capture):
    iid = "1000000000000000001"
    s = series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, [0.1] * HOURS)
    write(capture, "monitoring-gce-cpu-ALIGN_MEAN-p1.json", page("10^2.%", [s], "tok"))
    write(capture, "monitoring-gce-cpu-ALIGN_MEAN-p3.json", page("10^2.%", [s]))
    _manifest_upsert(capture, "monitoring-gce-cpu-ALIGN_MEAN-p1.json", "ok")
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MEAN") == {"status": "no_data"}
def test_stale_higher_page_after_a_shorter_rerun_is_no_data(capture):
    iid = "1000000000000000001"
    s = series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, [0.1] * HOURS)
    # A rerun wrote a terminal p1 but an older run's p2 survived: the chain has two terminal pages.
    write_metric(capture, "gce-cpu", "ALIGN_MEAN", [page("10^2.%", [s]), page("10^2.%", [s])])
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MEAN") == {"status": "no_data"}
def test_middle_page_without_next_page_token_is_no_data(capture):
    iid = "1000000000000000001"
    s = series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, [0.1] * HOURS)
    write_metric(capture, "gce-cpu", "ALIGN_MEAN", [page("10^2.%", [s], "tok"), page("10^2.%", [s]), page("10^2.%", [s])])
    assert sm.load_metric(capture, "gce-cpu", "ALIGN_MEAN") == {"status": "no_data"}
# ---------------------------------------------------------------- units
def test_normalize_unit_divides_percent_and_passes_others():
    assert sm.normalize_unit(50.0, "%") == 0.5
    assert sm.normalize_unit(0.5, "10^2.%") == 0.5
    assert sm.normalize_unit(0.9, "1") == 0.9
    assert sm.normalize_unit(87293952, "By") == 87293952
def test_per_series_unit_wins_over_response_unit(capture):
    iid = "1000000000000000001"
    s = series(GCE_MEM, gce_labels(iid), {"state": "used"}, [30.0] * HOURS, unit="%")
    write_metric(capture, "gce-mem", "ALIGN_MEAN", [page("1", [s])])
    loaded = sm.load_metric(capture, "gce-mem", "ALIGN_MEAN")
    merged = next(iter(loaded["series"].values()))
    assert merged["unit"] == "%"
    hourly = sm.hourly_values(merged, merged["unit"], WINDOW_START, WINDOW_END)
    assert all(v == pytest.approx(0.30) for v in hourly.values())
def test_series_omitting_unit_falls_back_to_response_unit(capture):
    iid = "1000000000000000001"
    write_metric(capture, "gce-mem", "ALIGN_MEAN", [page("%", [series(GCE_MEM, gce_labels(iid), {"state": "used"}, [30.0] * HOURS)])])
    loaded = sm.load_metric(capture, "gce-mem", "ALIGN_MEAN")
    assert next(iter(loaded["series"].values()))["unit"] == "%"
@pytest.mark.parametrize("response_unit", [None, "{not_a_unit}"])
def test_missing_or_not_a_unit_marks_metric_no_data(capture, response_unit):
    iid = "1000000000000000001"
    write_metric(capture, "gce-mem", "ALIGN_MEAN", [page(response_unit, [series(GCE_MEM, gce_labels(iid), {"state": "used"}, [30.0] * HOURS)])])
    assert sm.load_metric(capture, "gce-mem", "ALIGN_MEAN") == {"status": "no_data"}
def test_bad_unit_on_memory_yields_no_data_block_for_every_vm(capture):
    iid = "1000000000000000001"
    simple_vm(capture, iid, mem_used=[30.0] * HOURS, mem_unit="{not_a_unit}")
    summary = summarize(capture)
    assert by_id(summary, iid)["memory"] == {"status": "no_data"}
    assert summary["_units"]["gce-mem"] is None
    assert summary["_units"]["gce-cpu"] == "10^2.%"
# ---------------------------------------------------------------- memory state filter
def test_memory_keeps_only_the_used_state(capture):
    iid = "1000000000000000001"
    simple_vm(capture, iid)
    states = {"used": 30.0, "free": 50.0, "cached": 15.0, "buffered": 1.0, "slab": 4.0}
    mean_series = [series(GCE_MEM, gce_labels(iid), {"state": s}, [v] * HOURS, unit="%") for s, v in states.items()]
    max_series = [series(GCE_MEM, gce_labels(iid), {"state": s}, [v + 1] * HOURS, unit="%") for s, v in states.items()]
    write_metric(capture, "gce-mem", "ALIGN_MEAN", [page("%", mean_series)])
    write_metric(capture, "gce-mem", "ALIGN_MAX", [page("%", max_series)])
    memory = by_id(summarize(capture), iid)["memory"]
    assert memory["p95"] == pytest.approx(0.30)
    assert memory["mean"] == pytest.approx(0.30)
    assert memory["max"] == pytest.approx(0.31)
    assert memory["samples_present"] == HOURS
def test_two_used_series_for_one_vm_is_no_data(capture):
    iid = "1000000000000000001"
    simple_vm(capture, iid)
    twice = [series(GCE_MEM, dict(gce_labels(iid), zone="us-central1-b"), {"state": "used"}, [30.0] * HOURS),
             series(GCE_MEM, gce_labels(iid), {"state": "used"}, [40.0] * HOURS)]
    write_metric(capture, "gce-mem", "ALIGN_MEAN", [page("%", twice)])
    write_metric(capture, "gce-mem", "ALIGN_MAX", [page("%", twice)])
    assert by_id(summarize(capture), iid)["memory"] == {"status": "no_data"}
# ---------------------------------------------------------------- num_backends summation and int64
def test_num_backends_series_are_summed_hour_by_hour():
    ends = end_times(1)
    hourlies = [sm.hourly_values(series(SQL_PGCONN, sql_labels("db"), {"database": db}, [v], ends=ends), "1", WINDOW_START, WINDOW_END)
                for db, v in (("orders", 0), ("cloudsqladmin", 2), ("postgres", 0), ("template1", 3))]
    summed = sm.sum_series_by_hour(hourlies)
    assert summed == {_ts(ends[0]): 5.0}
def test_int64_under_max_and_double_under_mean_reduce_together(capture):
    write(capture, "sql.json", sql_json(("orders-db", "POSTGRES_15", "db-f1-micro")))
    labels = sql_labels("orders-db")
    for short, metric in (("sql-cpu", SQL_CPU), ("sql-mem", "cloudsql.googleapis.com/database/memory/utilization")):
        write_metric(capture, short, "ALIGN_MEAN", [page("1", [series(metric, labels, None, [0.5] * HOURS, resource_type="cloudsql_database")])])
        write_metric(capture, short, "ALIGN_MAX", [page("1", [series(metric, labels, None, [0.6] * HOURS, resource_type="cloudsql_database")])])
    disk = "cloudsql.googleapis.com/database/disk/bytes_used"
    write_metric(capture, "sql-disk", "ALIGN_MEAN", [page("By", [series(disk, labels, None, [87293952.0] * HOURS, resource_type="cloudsql_database")])])
    write_metric(capture, "sql-disk", "ALIGN_MAX", [page("By", [series(disk, labels, None, [87293952] * HOURS, key="int64Value", resource_type="cloudsql_database")])])
    write_metric(capture, "sql-conn", "ALIGN_MEAN", [page("1", [])])
    write_metric(capture, "sql-conn", "ALIGN_MAX", [page("1", [])])
    backends_max = {"orders": 3, "cloudsqladmin": 2, "postgres": 0, "template1": 0}
    mean_pages, max_pages = [], []
    for index, (db, value) in enumerate(backends_max.items(), start=1):
        token = "next" if index < len(backends_max) else None
        mean_pages.append(page("1", [series(SQL_PGCONN, labels, {"database": db}, [float(value)] * HOURS, resource_type="cloudsql_database")], token))
        max_pages.append(page("1", [series(SQL_PGCONN, labels, {"database": db}, [value] * HOURS, key="int64Value", resource_type="cloudsql_database")], token))
    write_metric(capture, "sql-pgconn", "ALIGN_MEAN", mean_pages)
    write_metric(capture, "sql-pgconn", "ALIGN_MAX", max_pages)
    db = by_id(summarize(capture), f"{PROJECT}:orders-db")
    assert db["database_id"] == f"{PROJECT}:orders-db"
    assert db["disk_bytes_used"] == {"p95": 87293952, "mean": 87293952, "max": 87293952, "samples_present": HOURS, "samples_expected": HOURS}
    assert all(isinstance(db["disk_bytes_used"][k], int) for k in ("p95", "mean", "max"))
    assert db["connections"]["p95"] == 5.0 and db["connections"]["max"] == 5.0
    assert db["coverage"] == "sufficient"
    assert "burst" not in db and "idle" not in db
# ---------------------------------------------------------------- reduction math
def test_p95_is_nearest_rank_of_hourly_means():
    means = {f"h{i}": float(v) for i, v in enumerate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])}
    maxes = {f"h{i}": float(v) for i, v in enumerate([3, 4, 5, 6, 7, 8, 9, 10, 11, 12])}
    block = sm.reduce_metric(means, maxes, 10)
    # ceil(0.95 * 10) - 1 = 9 -> sorted[9] = 10; a 20-value list would pick index 18.
    assert block == {"p95": 10.0, "mean": 5.5, "max": 12.0, "samples_present": 10, "samples_expected": 10}
    twenty = {f"h{i}": float(i + 1) for i in range(20)}
    assert sm.reduce_metric(twenty, twenty, 20)["p95"] == 19.0
def test_no_zero_fill_for_partial_coverage(capture):
    iid = "1000000000000000005"
    write(capture, "gce.json", gce_json((iid, "new-vm", "e2-standard-2")))
    partial = series(GCE_CPU, gce_labels(iid), {"instance_name": "new-vm"}, [0.2] * 100)
    write_metric(capture, "gce-cpu", "ALIGN_MEAN", [page("10^2.%", [partial])])
    write_metric(capture, "gce-cpu", "ALIGN_MAX", [page("10^2.%", [partial])])
    vm = by_id(summarize(capture), iid)
    assert vm["cpu"]["samples_present"] == 100
    assert vm["cpu"]["samples_expected"] == HOURS
    assert vm["coverage"] == "insufficient"
    assert vm["burst"] is False and vm["idle"] is False
def test_point_at_window_start_is_dropped(capture):
    iid = "1000000000000000001"
    ends = end_times(HOURS) + [WINDOW_START]
    s = series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, [0.1] * (HOURS + 1), ends=ends)
    assert len(s["points"]) == 169
    hourly = sm.hourly_values(s, "10^2.%", WINDOW_START, WINDOW_END)
    assert len(hourly) == HOURS
    assert _ts(WINDOW_START) not in hourly
    assert _ts(WINDOW_END) in hourly
# ---------------------------------------------------------------- flags
def test_burst_requires_two_consecutive_hot_means_not_a_hot_max(capture):
    iid = "1000000000000000004"
    means = [0.10] * HOURS
    means[40], means[41] = 0.6, 0.6
    simple_vm(capture, iid, cpu_means=means)
    assert by_id(summarize(capture), iid)["burst"] is True
    # Same baseline, one hot max with an ordinary mean: never a burst.
    maxes = [0.15] * HOURS
    maxes[50] = 0.9
    simple_vm(capture, iid, cpu_means=[0.10] * HOURS, cpu_maxes=maxes)
    vm = by_id(summarize(capture), iid)
    assert vm["cpu"]["max"] == 0.9
    assert vm["burst"] is False
def test_hot_hours_separated_by_a_missing_bucket_are_not_consecutive(capture):
    iid = "1000000000000000004"
    write(capture, "gce.json", gce_json((iid, "vm", "n2-standard-8")))
    ends = end_times(HOURS)
    means = [0.10] * HOURS
    means[40], means[42] = 0.6, 0.6
    del ends[41], means[41]  # 167 of 168 buckets: coverage stays sufficient, the hour between the hot ones is absent
    mean_series = series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, means, ends=ends)
    max_series = series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, [m + 0.05 for m in means], ends=ends)
    write_metric(capture, "gce-cpu", "ALIGN_MEAN", [page("10^2.%", [mean_series])])
    write_metric(capture, "gce-cpu", "ALIGN_MAX", [page("10^2.%", [max_series])])
    vm = by_id(summarize(capture), iid)
    assert vm["coverage"] == "sufficient"
    assert vm["cpu"]["samples_present"] == HOURS - 1
    assert vm["burst"] is False
    # The same two hot hours with the bucket between them also hot: a real run of adjacent hours.
    means.insert(41, 0.6)
    ends.insert(41, end_times(HOURS)[41])
    mean_series = series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, means, ends=ends)
    max_series = series(GCE_CPU, gce_labels(iid), {"instance_name": "vm"}, [m + 0.05 for m in means], ends=ends)
    write_metric(capture, "gce-cpu", "ALIGN_MEAN", [page("10^2.%", [mean_series])])
    write_metric(capture, "gce-cpu", "ALIGN_MAX", [page("10^2.%", [max_series])])
    assert by_id(summarize(capture), iid)["burst"] is True
def test_single_hot_mean_is_not_a_burst(capture):
    iid = "1000000000000000001"
    means = [0.10] * HOURS
    means[40] = 0.6
    means[42] = 0.6  # hot but not consecutive
    simple_vm(capture, iid, cpu_means=means)
    assert by_id(summarize(capture), iid)["burst"] is False
def test_idle_true_with_low_cpu_and_memory(capture):
    iid = "1000000000000000006"
    simple_vm(capture, iid, cpu_means=[0.01] * HOURS, cpu_maxes=[0.02] * HOURS, mem_used=[10.0] * HOURS)
    assert by_id(summarize(capture), iid)["idle"] is True
def test_idle_false_when_memory_p95_at_or_above_threshold(capture):
    iid = "1000000000000000006"
    simple_vm(capture, iid, cpu_means=[0.01] * HOURS, cpu_maxes=[0.02] * HOURS, mem_used=[20.0] * HOURS)
    vm = by_id(summarize(capture), iid)
    assert vm["memory"]["p95"] == 0.2
    assert vm["idle"] is False
def test_idle_true_when_memory_is_a_status_block(capture):
    iid = "1000000000000000006"
    simple_vm(capture, iid, cpu_means=[0.01] * HOURS, cpu_maxes=[0.02] * HOURS)
    vm = by_id(summarize(capture), iid)
    assert vm["memory"] == {"status": "no_data"}
    assert vm["idle"] is True
# ---------------------------------------------------------------- missing files
def test_missing_memory_files_give_memory_no_data_with_cpu_sufficient(capture):
    iid = "1000000000000000001"
    simple_vm(capture, iid)
    summary = summarize(capture)
    vm = by_id(summary, iid)
    assert vm["memory"] == {"status": "no_data"}
    assert vm["coverage"] == "sufficient"
    assert summary["_units"]["gce-mem"] is None
def test_missing_cpu_files_give_coverage_no_data_even_with_memory(capture):
    iid = "1000000000000000001"
    simple_vm(capture, iid, mem_used=[30.0] * HOURS)
    for path in capture.glob("monitoring-gce-cpu-*"):
        path.unlink()
    vm = by_id(summarize(capture), iid)
    assert vm["cpu"] == {"status": "no_data"}
    assert vm["memory"]["p95"] == 0.3
    assert vm["coverage"] == "no_data"
    assert vm["burst"] is False and vm["idle"] is False
def test_memory_file_present_without_series_is_unavailable(capture):
    iid = "1000000000000000004"
    simple_vm(capture, iid)
    write_metric(capture, "gce-mem", "ALIGN_MEAN", [page("%", [])])
    write_metric(capture, "gce-mem", "ALIGN_MAX", [page("%", [])])
    assert by_id(summarize(capture), iid)["memory"] == {"status": "unavailable"}
def test_connections_unavailable_when_both_files_present_but_empty(capture):
    write(capture, "sql.json", sql_json(("orders-db", "POSTGRES_15", "db-f1-micro")))
    for short in ("sql-conn", "sql-pgconn"):
        write_metric(capture, short, "ALIGN_MEAN", [page("1", [])])
        write_metric(capture, short, "ALIGN_MAX", [page("1", [])])
    db = by_id(summarize(capture), f"{PROJECT}:orders-db")
    assert db["connections"] == {"status": "unavailable"}
    assert db["cpu"] == {"status": "no_data"}
    assert db["coverage"] == "no_data"
# ---------------------------------------------------------------- joins
def test_mig_member_flag_from_mig_members_file(capture):
    member, other = "1000000000000000007", "1000000000000000001"
    write(capture, "gce.json", gce_json((member, "web-mig-7f3k", "e2-medium"), (other, "web-steady", "n2-standard-8")))
    write(capture, "mig-members-web-mig.json", [{"instance": f"{COMPUTE}/zones/{ZONE}/instances/web-mig-7f3k"}])
    summary = summarize(capture)
    assert by_id(summary, member)["mig_member"] is True
    assert by_id(summary, other)["mig_member"] is False
def test_join_gce_uses_string_ids_and_last_url_segments():
    joined = sm.join_gce([{"id": 1000000000000000007, "name": "web-mig-7f3k", "zone": f"{COMPUTE}/zones/{ZONE}",
                           "machineType": f"{COMPUTE}/zones/{ZONE}/machineTypes/e2-medium"}],
                         [[{"instance": f"{COMPUTE}/zones/{ZONE}/instances/web-mig-7f3k"}]])
    assert joined == {"1000000000000000007": {"name": "web-mig-7f3k", "zone": ZONE, "machine_type": "e2-medium", "mig_member": True}}
def test_only_resources_in_gce_json_get_a_summary(capture):
    kept, deleted = "1000000000000000001", "1000000000000000099"
    write(capture, "gce.json", gce_json((kept, "vm", "n2-standard-8")))
    both = [series(GCE_CPU, gce_labels(i), {"instance_name": "x"}, [0.1] * HOURS) for i in (kept, deleted)]
    write_metric(capture, "gce-cpu", "ALIGN_MEAN", [page("10^2.%", both)])
    write_metric(capture, "gce-cpu", "ALIGN_MAX", [page("10^2.%", both)])
    assert [r["instance_id"] for r in summarize(capture)["resources"]] == [kept]
def test_shared_core_cpu_above_one_is_kept(capture):
    iid = "1000000000000000008"
    maxes = [1.3] * HOURS
    maxes[12] = 1.965
    simple_vm(capture, iid, cpu_means=[1.2] * HOURS, cpu_maxes=maxes)
    vm = by_id(summarize(capture), iid)
    assert vm["cpu"]["p95"] == 1.2
    assert vm["cpu"]["max"] == 1.965
def test_resources_sorted_by_type_then_id(capture):
    write(capture, "gce.json", gce_json(("1000000000000000002", "b", "e2-small"), ("1000000000000000001", "a", "e2-small")))
    write(capture, "sql.json", sql_json(("orders-db", "POSTGRES_15", "db-f1-micro")))
    keys = [r.get("instance_id") or r.get("database_id") for r in summarize(capture)["resources"]]
    assert keys == [f"{PROJECT}:orders-db", "1000000000000000001", "1000000000000000002"]
# ---------------------------------------------------------------- top level and CLI
def test_top_level_shape_and_window_math(capture):
    summary = summarize(capture)
    assert set(summary) == {"_units", "alignment", "window_days", "window_start", "window_end", "resources"}
    assert summary["alignment"] == "1h"
    assert summary["window_days"] == 7
    assert summary["window_start"] == "2026-11-13T00:00:00Z"
    assert summary["window_end"] == "2026-11-20T00:00:00Z"
    assert set(summary["_units"]) == {"gce-cpu", "gce-mem", "sql-cpu", "sql-mem", "sql-disk", "sql-conn", "sql-pgconn"}
    assert all(v is None for v in summary["_units"].values())
    assert summary["resources"] == []
def test_cli_exits_zero_with_only_gce_and_sql_json(capture):
    result = subprocess.run([sys.executable, str(SCRIPT), "--capture-dir", str(capture), "--project", PROJECT,
                             "--window-start", "2026-11-13T00:00:00Z", "--window-end", "2026-11-20T00:00:00Z"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    written = json.loads((capture / "utilization-summary.json").read_text())
    assert written["resources"] == []
def test_cli_exits_two_on_missing_capture_dir(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--capture-dir", str(tmp_path / "nope"), "--project", PROJECT,
                             "--window-start", "2026-11-13T00:00:00Z", "--window-end", "2026-11-20T00:00:00Z"],
                            capture_output=True, text=True)
    assert result.returncode == 2
def test_fixture_end_to_end_matches_expected_byte_for_byte(tmp_path):
    out = tmp_path / "u.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--capture-dir", str(LIVE), "--project", PROJECT,
                             "--window-start", "2026-11-13T00:00:00Z", "--window-end", "2026-11-20T00:00:00Z",
                             "--output", str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert out.read_bytes() == EXPECTED.read_bytes()
def test_fixture_summary_is_within_byte_budget():
    assert EXPECTED.stat().st_size < 65536
def test_fixture_summary_exercises_every_rule():
    summary = json.loads(EXPECTED.read_text())
    assert summary["_units"] == {"gce-cpu": "10^2.%", "gce-mem": "%", "sql-cpu": "10^2.%", "sql-mem": "1",
                                 "sql-disk": "By", "sql-conn": "1", "sql-pgconn": "1"}
    web_steady = by_id(summary, "1000000000000000001")
    assert (web_steady["coverage"], web_steady["burst"], web_steady["idle"]) == ("sufficient", False, False)
    assert web_steady["cpu"]["max"] == 0.9 and web_steady["cpu"]["samples_present"] == HOURS
    batch = by_id(summary, "1000000000000000004")
    assert batch["burst"] is True and batch["memory"] == {"status": "unavailable"}
    new_vm = by_id(summary, "1000000000000000005")
    assert new_vm["coverage"] == "insufficient" and new_vm["cpu"]["samples_present"] == 100
    assert by_id(summary, "1000000000000000006")["idle"] is True
    assert by_id(summary, "1000000000000000007")["mig_member"] is True
    ops = by_id(summary, "1000000000000000008")
    assert ops["cpu"]["p95"] > 1.0 and ops["cpu"]["max"] == 1.965 and "p95" in ops["memory"]
    orders = by_id(summary, f"{PROJECT}:orders-db")
    assert orders["disk_bytes_used"]["p95"] == 87293952 and orders["connections"]["max"] == 5.0
    assert orders["memory"]["p95"] >= 0.999 and orders["cpu"]["samples_present"] == HOURS
    assert "p95" in by_id(summary, f"{PROJECT}:reports-db")["connections"]
def test_fixture_inventory_utilization_blocks_match_expected_summary():
    summary = json.loads(EXPECTED.read_text())
    inventory = json.loads((FIXTURE / "after-discover" / "gcp-resource-inventory.json").read_text())
    for resource in inventory["resources"]:
        key = resource["config"].get("id") or f"{PROJECT}:{resource['config']['name']}"
        assert resource["utilization"] == by_id(summary, key)
