#!/usr/bin/env python3
"""Reduce the Cloud Monitoring pages captured by discover-live.md rows 21a-21n into one small utilization-summary.json.

The agent never reads a raw monitoring-*.json file: this script pages, joins, aligns and reduces them to
per-resource p95/mean/max blocks plus coverage/burst/idle flags, keyed to gce.json / sql.json so only
resources that still exist get a summary object.
"""
from __future__ import annotations
import argparse
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
# Every tunable lives in the skill's knowledge/estimate/rightsizing-thresholds.json (one file for
# this script, size-from-utilization.py, Estimate and the tests). The script travels with the
# skill tree, so the file is resolved relative to this script.
THRESHOLDS_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "estimate" / "rightsizing-thresholds.json"
def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
THRESHOLDS = load_thresholds()
COVERAGE_MIN = THRESHOLDS["coverage_min"]
IDLE_CPU_P95_MAX = THRESHOLDS["idle"]["cpu_p95_max"]
IDLE_MEMORY_P95_MAX = THRESHOLDS["idle"]["memory_p95_max"]
BURST_CPU_P95_MAX = THRESHOLDS["burst"]["cpu_p95_max"]
BURST_SPIKE_MULTIPLE = THRESHOLDS["burst"]["spike_multiple"]
BURST_CONSECUTIVE_HOURS = THRESHOLDS["burst"]["consecutive_hours"]
ALIGNMENT = "1h"
ALIGNMENT_PERIOD = timedelta(seconds=3600)
ALIGNERS = ("ALIGN_MEAN", "ALIGN_MAX")
METRIC_TYPES = {
    "gce-cpu": "compute.googleapis.com/instance/cpu/utilization",
    "gce-mem": "agent.googleapis.com/memory/percent_used",
    "sql-cpu": "cloudsql.googleapis.com/database/cpu/utilization",
    "sql-mem": "cloudsql.googleapis.com/database/memory/utilization",
    "sql-disk": "cloudsql.googleapis.com/database/disk/bytes_used",
    "sql-conn": "cloudsql.googleapis.com/database/network/connections",
    "sql-pgconn": "cloudsql.googleapis.com/database/postgresql/num_backends",
}
PASS_THROUGH_UNITS = ("10^2.%", "1", "By")
NOT_A_UNIT = "{not_a_unit}"
NO_DATA = {"status": "no_data"}
UNAVAILABLE = {"status": "unavailable"}
_PAGE_RE = re.compile(r"-p(\d+)\.json$")
def parse_rfc3339(value: str) -> datetime:
    """Parse an RFC3339 timestamp with a trailing Z (or offset) into an aware UTC datetime."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
def series_key(series: dict[str, Any]) -> tuple:
    """Identity of a series across pages: metric type plus sorted resource and metric labels."""
    metric = series.get("metric") or {}
    resource = series.get("resource") or {}
    return (
        metric.get("type"),
        tuple(sorted((resource.get("labels") or {}).items())),
        tuple(sorted((metric.get("labels") or {}).items())),
    )
def page_files(capture_dir: Path, short_name: str, aligner: str) -> list[Path]:
    """All monitoring-<short>-<aligner>-p<N>.json pages in page order."""
    files = []
    for path in capture_dir.glob(f"monitoring-{short_name}-{aligner}-p*.json"):
        match = _PAGE_RE.search(path.name)
        if match:
            files.append((int(match.group(1)), path))
    return [path for _, path in sorted(files)]
def manifest_rejects(capture_dir: Path, short_name: str, aligner: str) -> bool:
    """True unless a readable manifest.json lists this row's monitoring-<short>-<aligner>-p* file with status ok.

    Step 2c writes a manifest row for every monitoring call before Step 2d reduces, so pages on disk
    with no readable manifest, no row for this file, or a row whose status is not ok are stale output
    of an earlier run (or a skipped/failed retry) and must not be reduced. Only an explicit ok row
    for a matching file admits the page set.
    """
    manifest = _read_json(capture_dir / "manifest.json", None)
    captures = manifest.get("captures") if isinstance(manifest, dict) else None
    if not isinstance(captures, list):
        return True
    prefix = f"monitoring-{short_name}-{aligner}-p"
    accepted = False
    for entry in captures:
        if not isinstance(entry, dict) or not str(entry.get("file") or "").startswith(prefix):
            continue
        if entry.get("status") != "ok":
            return True
        accepted = True
    return not accepted


def load_metric(capture_dir: Path, short_name: str, aligner: str = "ALIGN_MEAN") -> dict[str, Any]:
    """Merge one metric's pages into series keyed by series_key, each carrying its resolved unit.

    Returns {"status": "ok", "unit": <unit>, "series": {key: series}} or {"status": "no_data"} when no
    readable manifest row marks this file ok (missing manifest, missing row, or skipped/failed), no page exists, a page is unparseable or an HTTP error envelope,
    the pages are not a contiguous p1..pN chain whose last page alone lacks nextPageToken, or any series
    has no usable unit (missing or {not_a_unit}).
    """
    if manifest_rejects(capture_dir, short_name, aligner):
        return {"status": "no_data"}
    files = page_files(capture_dir, short_name, aligner)
    if not files:
        return {"status": "no_data"}
    merged: dict[tuple, dict[str, Any]] = {}
    unit: str | None = None
    for index, path in enumerate(files, start=1):
        if int(_PAGE_RE.search(path.name).group(1)) != index:
            return {"status": "no_data"}
        try:
            page = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"status": "no_data"}
        if not isinstance(page, dict) or "error" in page:
            return {"status": "no_data"}
        if bool(page.get("nextPageToken")) != (index < len(files)):
            return {"status": "no_data"}
        page_unit = page.get("unit")
        if unit is None and isinstance(page_unit, str) and page_unit != NOT_A_UNIT:
            unit = page_unit
        for series in page.get("timeSeries") or []:
            resolved = series.get("unit", page_unit)
            if not isinstance(resolved, str) or resolved == NOT_A_UNIT:
                return {"status": "no_data"}
            if unit is None:
                unit = resolved
            key = series_key(series)
            target = merged.setdefault(key, {"metric": series.get("metric") or {}, "resource": series.get("resource") or {},
                                             "unit": resolved, "points": []})
            target["points"].extend(series.get("points") or [])
    return {"status": "ok", "unit": unit, "series": merged}
def normalize_unit(value: float, unit: str) -> float:
    """Bring a point value into the summary's scale: '%' is divided by 100; 10^2.%, 1 and By pass through."""
    if unit == "%":
        return value / 100.0
    return value
def point_value(point: dict[str, Any]) -> float | None:
    """Read a point's doubleValue or int64Value (a string in the API)."""
    value = point.get("value") or {}
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "int64Value" in value:
        return float(value["int64Value"])
    return None
def hourly_values(series: dict[str, Any], unit: str, window_start: datetime, window_end: datetime) -> dict[str, float]:
    """Per-hour values keyed by endTime, keeping only window_start < endTime <= window_end. No zero-fill."""
    out: dict[str, float] = {}
    for point in series.get("points") or []:
        end_time = (point.get("interval") or {}).get("endTime")
        if not end_time:
            continue
        try:
            end = parse_rfc3339(end_time)
        except ValueError:
            continue
        if not (window_start < end <= window_end):
            continue
        value = point_value(point)
        if value is None:
            continue
        out[end_time] = normalize_unit(value, unit)
    return out
def sum_series_by_hour(hourlies: list[dict[str, float]]) -> dict[str, float]:
    """Add several series hour by hour (num_backends has one series per database)."""
    out: dict[str, float] = {}
    for hourly in hourlies:
        for hour, value in hourly.items():
            out[hour] = out.get(hour, 0.0) + value
    return out
def p95_nearest_rank(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(math.ceil(0.95 * len(ordered)) - 1, 0)]
def reduce_metric(means: dict[str, float], maxes: dict[str, float], samples_expected: int, integer: bool = False) -> dict[str, Any]:
    """Five-key block from hourly means and maxes; p95 and mean come from means, max from maxes."""
    if not means or not maxes:
        return dict(UNAVAILABLE)
    mean_values = list(means.values())
    p95 = p95_nearest_rank(mean_values)
    mean = sum(mean_values) / len(mean_values)
    maximum = max(maxes.values())
    if integer:
        p95, mean, maximum = int(round(p95)), int(round(mean)), int(round(maximum))
    else:
        p95, mean, maximum = round(p95, 4), round(mean, 4), round(maximum, 4)
    return {
        "p95": p95,
        "mean": mean,
        "max": maximum,
        "samples_present": min(len(means), samples_expected),
        "samples_expected": samples_expected,
    }
def is_block(metric: dict[str, Any]) -> bool:
    return "status" not in metric
def coverage_of(cpu: dict[str, Any]) -> str:
    if not is_block(cpu):
        return "no_data"
    if cpu["samples_expected"] and cpu["samples_present"] / cpu["samples_expected"] >= COVERAGE_MIN:
        return "sufficient"
    return "insufficient"
def flags(cpu: dict[str, Any], memory: dict[str, Any], cpu_means: dict[str, float]) -> tuple[str, bool, bool]:
    """(coverage, burst, idle) for a GCE instance. burst uses time-ordered hourly means, never max.

    Consecutive means consecutive clock hours: a hot bucket only extends the run when it ends exactly one
    alignment period after the previous bucket, so a missing hour between two hot hours resets the run.
    """
    coverage = coverage_of(cpu)
    burst = False
    idle = False
    if coverage == "sufficient" and cpu["p95"] < BURST_CPU_P95_MAX:
        threshold = BURST_SPIKE_MULTIPLE * cpu["p95"]
        run = 0
        previous: datetime | None = None
        for hour in sorted(cpu_means, key=parse_rfc3339):
            end = parse_rfc3339(hour)
            if cpu_means[hour] > threshold:
                run = run + 1 if previous is not None and end - previous == ALIGNMENT_PERIOD else 1
            else:
                run = 0
            previous = end
            if run >= BURST_CONSECUTIVE_HOURS:
                burst = True
                break
    if coverage == "sufficient" and cpu["p95"] < IDLE_CPU_P95_MAX and not burst:
        idle = (not is_block(memory)) or memory["p95"] < IDLE_MEMORY_P95_MAX
    return coverage, burst, idle
def last_segment(url: str | None) -> str | None:
    if not url:
        return None
    return str(url).rstrip("/").rsplit("/", 1)[-1]
def zone_of_url(url: str) -> str | None:
    parts = url.split("/")
    if "zones" in parts:
        index = parts.index("zones")
        if index + 1 < len(parts):
            return parts[index + 1]
    return None
def join_gce(gce_json: list[dict[str, Any]], mig_files: list[Any]) -> dict[str, dict[str, Any]]:
    """instance_id (string) -> {name, zone, machine_type, mig_member} from gce.json and mig-members*.json."""
    members: set[tuple[str, str | None]] = set()
    for entries in mig_files:
        for entry in entries or []:
            url = (entry or {}).get("instance")
            if isinstance(url, str):
                members.add((last_segment(url), zone_of_url(url)))
    joined: dict[str, dict[str, Any]] = {}
    for vm in gce_json or []:
        if not isinstance(vm, dict) or vm.get("id") is None:
            continue
        zone = last_segment(vm.get("zone"))
        name = vm.get("name")
        joined[str(vm["id"])] = {
            "name": name,
            "zone": zone,
            "machine_type": last_segment(vm.get("machineType")),
            "mig_member": (name, zone) in members,
        }
    return joined
def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
def _series_for(loaded: dict[str, Any], predicate) -> list[dict[str, Any]]:
    if loaded.get("status") != "ok":
        return []
    return [series for series in loaded["series"].values() if predicate(series)]
def _metric_block(mean_loaded: dict[str, Any], max_loaded: dict[str, Any], predicate, window_start: datetime,
                  window_end: datetime, samples_expected: int, integer: bool = False, summed: bool = False) -> tuple[dict[str, Any], dict[str, float]]:
    """Resolve one metric for one resource. Returns (block, hourly means)."""
    if mean_loaded.get("status") != "ok" or max_loaded.get("status") != "ok":
        return dict(NO_DATA), {}
    mean_series = _series_for(mean_loaded, predicate)
    max_series = _series_for(max_loaded, predicate)
    if not mean_series and not max_series:
        return dict(UNAVAILABLE), {}
    if not summed and (len(mean_series) > 1 or len(max_series) > 1):
        return dict(NO_DATA), {}
    means = sum_series_by_hour([hourly_values(s, s["unit"], window_start, window_end) for s in mean_series])
    maxes = sum_series_by_hour([hourly_values(s, s["unit"], window_start, window_end) for s in max_series])
    return reduce_metric(means, maxes, samples_expected, integer=integer), means
def build_summary(capture_dir: Path, project: str, window_start: datetime, window_end: datetime) -> dict[str, Any]:
    hours = (window_end - window_start).total_seconds() / 3600.0
    samples_expected = int(math.floor(hours))
    window_days = int(round(hours / 24.0))
    loaded = {short: {aligner: load_metric(capture_dir, short, aligner) for aligner in ALIGNERS} for short in METRIC_TYPES}
    units = {}
    for short in METRIC_TYPES:
        mean_loaded, max_loaded = loaded[short]["ALIGN_MEAN"], loaded[short]["ALIGN_MAX"]
        units[short] = mean_loaded.get("unit") if mean_loaded.get("status") == "ok" and max_loaded.get("status") == "ok" else None
    gce_json = _read_json(capture_dir / "gce.json", [])
    sql_json = _read_json(capture_dir / "sql.json", [])
    mig_files = [_read_json(path, []) for path in sorted(capture_dir.glob("mig-members*.json"))]
    joined = join_gce(gce_json if isinstance(gce_json, list) else [], mig_files)
    resources: list[dict[str, Any]] = []
    for instance_id, vm in joined.items():
        def by_instance(series, instance_id=instance_id):
            return str((series["resource"].get("labels") or {}).get("instance_id")) == instance_id
        def by_instance_used(series, instance_id=instance_id):
            return by_instance(series, instance_id) and (series["metric"].get("labels") or {}).get("state") == "used"
        cpu, cpu_means = _metric_block(loaded["gce-cpu"]["ALIGN_MEAN"], loaded["gce-cpu"]["ALIGN_MAX"], by_instance,
                                       window_start, window_end, samples_expected)
        memory, _ = _metric_block(loaded["gce-mem"]["ALIGN_MEAN"], loaded["gce-mem"]["ALIGN_MAX"], by_instance_used,
                                  window_start, window_end, samples_expected)
        coverage, burst, idle = flags(cpu, memory, cpu_means)
        resources.append({
            "resource_type": "gce_instance",
            "instance_id": instance_id,
            "zone": vm["zone"],
            "window_days": window_days,
            "alignment": ALIGNMENT,
            "mig_member": vm["mig_member"],
            "cpu": cpu,
            "memory": memory,
            "coverage": coverage,
            "burst": burst,
            "idle": idle,
        })
    for db in sql_json if isinstance(sql_json, list) else []:
        if not isinstance(db, dict) or not db.get("name"):
            continue
        database_id = f"{project}:{db['name']}"
        def by_database(series, database_id=database_id):
            return (series["resource"].get("labels") or {}).get("database_id") == database_id
        cpu, _ = _metric_block(loaded["sql-cpu"]["ALIGN_MEAN"], loaded["sql-cpu"]["ALIGN_MAX"], by_database,
                               window_start, window_end, samples_expected)
        memory, _ = _metric_block(loaded["sql-mem"]["ALIGN_MEAN"], loaded["sql-mem"]["ALIGN_MAX"], by_database,
                                  window_start, window_end, samples_expected)
        disk, _ = _metric_block(loaded["sql-disk"]["ALIGN_MEAN"], loaded["sql-disk"]["ALIGN_MAX"], by_database,
                                window_start, window_end, samples_expected, integer=True)
        connections = _connections_block(loaded, by_database, window_start, window_end, samples_expected)
        resources.append({
            "resource_type": "cloudsql_database",
            "database_id": database_id,
            "region": db.get("region"),
            "window_days": window_days,
            "alignment": ALIGNMENT,
            "cpu": cpu,
            "memory": memory,
            "disk_bytes_used": disk,
            "connections": connections,
            "coverage": coverage_of(cpu),
        })
    resources.sort(key=lambda r: (r["resource_type"], r.get("instance_id") or r.get("database_id") or ""))
    return {
        "_units": units,
        "alignment": ALIGNMENT,
        "window_days": window_days,
        "window_start": window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_end": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "resources": resources,
    }
def _connections_block(loaded: dict[str, dict[str, Any]], predicate, window_start: datetime, window_end: datetime,
                       samples_expected: int) -> dict[str, Any]:
    """sql-conn (MySQL/SQL Server) when it has a series for the resource, else summed sql-pgconn (PostgreSQL)."""
    conn_mean, conn_max = loaded["sql-conn"]["ALIGN_MEAN"], loaded["sql-conn"]["ALIGN_MAX"]
    pg_mean, pg_max = loaded["sql-pgconn"]["ALIGN_MEAN"], loaded["sql-pgconn"]["ALIGN_MAX"]
    conn_ok = conn_mean.get("status") == "ok" and conn_max.get("status") == "ok"
    pg_ok = pg_mean.get("status") == "ok" and pg_max.get("status") == "ok"
    if conn_ok and (_series_for(conn_mean, predicate) or _series_for(conn_max, predicate)):
        block, _ = _metric_block(conn_mean, conn_max, predicate, window_start, window_end, samples_expected)
        return block
    if pg_ok and (_series_for(pg_mean, predicate) or _series_for(pg_max, predicate)):
        block, _ = _metric_block(pg_mean, pg_max, predicate, window_start, window_end, samples_expected, summed=True)
        return block
    if conn_ok and pg_ok:
        return dict(UNAVAILABLE)
    return dict(NO_DATA)
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--capture-dir", required=True, help="live-capture directory holding monitoring-*.json, gce.json, sql.json")
    parser.add_argument("--project", required=True, help="GCP project id (builds Cloud SQL database_id as project:name)")
    parser.add_argument("--window-start", required=True, help="RFC3339 UTC, e.g. 2026-11-13T00:00:00Z (same value as rows 21a-21n)")
    parser.add_argument("--window-end", required=True, help="RFC3339 UTC, e.g. 2026-11-20T00:00:00Z")
    parser.add_argument("--output", help="default <capture-dir>/utilization-summary.json")
    args = parser.parse_args(argv)
    capture_dir = Path(args.capture_dir)
    if not capture_dir.is_dir():
        print(f"summarize-monitoring: capture dir not found: {capture_dir}", file=sys.stderr)
        return 2
    try:
        window_start = parse_rfc3339(args.window_start)
        window_end = parse_rfc3339(args.window_end)
    except ValueError as exc:
        print(f"summarize-monitoring: bad window timestamp: {exc}", file=sys.stderr)
        return 2
    if window_end <= window_start:
        print("summarize-monitoring: --window-end must be after --window-start", file=sys.stderr)
        return 2
    summary = build_summary(capture_dir, args.project, window_start, window_end)
    output = Path(args.output) if args.output else capture_dir / "utilization-summary.json"
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0
if __name__ == "__main__":
    sys.exit(main())
