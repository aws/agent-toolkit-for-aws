"""Guard: gcp-to-aws live discovery captures 30-day utilization and attaches it.

Rows 21a–21n of discover-live.md are an exact-command allowlist: one metric
and one aligner per row, fourteen rows, no reducers. The agent never Reads a
raw `monitoring-*.json`; `summarize-monitoring.py` is the only reader, and the
inventory carries its output as `utilization` beside `config`. These contracts
pin the table, the security wording, the consent text, the schema, the report
exclusion line, and the fixture inventory with and without `utilization`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
GCP_REFS = PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references"
DISCOVER_LIVE = GCP_REFS / "phases" / "discover" / "discover-live.md"
SCHEMA = GCP_REFS / "shared" / "schema-discover-iac.md"
REPORT = GCP_REFS / "phases" / "generate" / "generate-artifacts-report.md"
VALIDATOR = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"
FIXTURE = PLUGIN_ROOT / "fixtures" / "gcp-utilization-capture"
INVENTORY = FIXTURE / "after-discover" / "gcp-resource-inventory.json"
EXPECTED_SUMMARY = FIXTURE / "expected-utilization-summary.json"

LIVE = DISCOVER_LIVE.read_text()

METRIC_TYPES = {
    "compute.googleapis.com/instance/cpu/utilization": "gce-cpu",
    "agent.googleapis.com/memory/percent_used": "gce-mem",
    "cloudsql.googleapis.com/database/cpu/utilization": "sql-cpu",
    "cloudsql.googleapis.com/database/memory/utilization": "sql-mem",
    "cloudsql.googleapis.com/database/disk/bytes_used": "sql-disk",
    "cloudsql.googleapis.com/database/network/connections": "sql-conn",
    "cloudsql.googleapis.com/database/postgresql/num_backends": "sql-pgconn",
}
OUTPUT_RE = re.compile(
    r"^`monitoring-(gce-cpu|gce-mem|sql-cpu|sql-mem|sql-disk|sql-conn|sql-pgconn)"
    r"-ALIGN_(MEAN|MAX)-p<N>\.json`$"
)
BASELINED_PATHS = {
    "edges",
    "migration_id",
    "metadata.discovery_timestamp",
    "metadata.project",
}


def _split_row(line: str) -> list[str]:
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [c.strip() for c in cells[1:-1]]


def _table_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in LIVE.splitlines():
        if line.startswith("| 21") or line.startswith("| 22") or line.startswith("| 7 "):
            cells = _split_row(line)
            rows[cells[0]] = cells
    return rows


ROWS = _table_rows()
SERIES_ROWS = {k: v for k, v in ROWS.items() if re.fullmatch(r"21[a-n]", k)}


def _slice(start: str, end: str) -> str:
    i = LIVE.index(start)
    j = LIVE.index(end, i)
    return LIVE[i:j]


def _run_validator(run_dir: Path) -> dict:
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--run-dir", str(run_dir), "--skill", "gcp-to-aws", "--json"],
        capture_output=True,
        text=True,
        cwd=PLUGIN_ROOT,
    )
    assert r.stdout, r.stderr
    return json.loads(r.stdout)


def _unbaselined_errors(report: dict) -> list[dict]:
    out = []
    for e in report["errors"]:
        path = re.sub(r"\[\d+\]", "[*]", e["path"])
        if path == "resources[*].id" or path in BASELINED_PATHS:
            continue
        out.append(e)
    return out


# --------------------------------------------------------------------------- capture table


def test_fourteen_series_rows_one_metric_one_aligner_each():
    assert sorted(SERIES_ROWS) == [f"21{c}" for c in "abcdefghijklmn"]
    for label, cells in SERIES_ROWS.items():
        command = cells[1]
        assert command.count('metric.type="') == 1, label
        assert len(re.findall(r"perSeriesAligner=ALIGN_(MEAN|MAX)\b", command)) == 1, label
        assert " OR " not in command, label
        assert "crossSeriesReducer" not in command, label
        assert "groupByFields=" not in command, label
        assert "ALIGN_PERCENTILE" not in command, label
        assert cells[3] == "always", label


def test_seven_metrics_each_with_mean_and_max_and_matching_output_files():
    seen = set()
    for label, cells in SERIES_ROWS.items():
        command, output = cells[1], cells[2]
        metric = re.search(r'metric\.type="([^"]+)"', command).group(1)
        aligner = re.search(r"perSeriesAligner=ALIGN_(MEAN|MAX)", command).group(1)
        assert metric in METRIC_TYPES, (label, metric)
        m = OUTPUT_RE.match(output)
        assert m, (label, output)
        assert m.group(1) == METRIC_TYPES[metric], (label, output)
        assert m.group(2) == aligner, (label, output)
        seen.add((metric, aligner))
    assert seen == {(m, a) for m in METRIC_TYPES for a in ("MEAN", "MAX")}


def test_row_21a_carries_the_full_curl_with_an_hour_aligned_30_day_window():
    command = SERIES_ROWS["21a"][1]
    for needle in (
        "gcloud auth print-access-token",
        "https://monitoring.googleapis.com/v3/projects/$GCP_PROJECT/timeSeries",
        'resource.type="gce_instance"',
        "interval.startTime=<UTC now rounded down to the hour minus 30 days, RFC3339>",
        "interval.endTime=<UTC now rounded down to the hour, RFC3339>",
        "aggregation.alignmentPeriod=3600s",
        "pageSize=1000",
        "nextPageToken",
        "EVERY row 21a–21n",
    ):
        assert needle in command, needle
    for label in "bcdefghijklmn":
        assert "same `projects.timeSeries.list` curl as 21a" in SERIES_ROWS[f"21{label}"][1], label
    for label, cells in SERIES_ROWS.items():
        if label in ("21a", "21b", "21c", "21d"):
            assert 'resource.type="gce_instance"' in cells[1], label
        else:
            assert 'resource.type="cloudsql_database"' in cells[1], label


def test_row_7_projects_the_instance_id_and_row_21_checks_the_monitoring_api():
    assert "json(id, name, zone" in ROWS["7"][1]
    # Assert the exact gcloud command fragment, not a bare hostname substring
    # (CodeQL py/incomplete-url-substring-sanitization flags the latter).
    assert (
        'gcloud services list --enabled --filter="config.name=monitoring.googleapis.com"'
        in ROWS["21"][1]
    )
    assert ROWS["21"][2] == "`monitoring-api.json`"
    assert "`skipped`" in ROWS["21"][1]
    assert "never enable the API" in ROWS["21"][1]


def test_mig_rows_branch_on_zone_or_region():
    assert "instance-groups managed list " in ROWS["22"][1]
    assert ROWS["22"][2] == "`mig-groups.json`"
    assert "instance-groups managed list-instances <group>" in ROWS["22a"][1]
    assert "--zone=" in ROWS["22a"][1]
    assert "--region=" in ROWS["22a"][1]
    assert ROWS["22a"][2] == "`mig-members-<group>.json`"


# --------------------------------------------------------------------------- security contract


def test_security_contract_names_the_token_exception_rows_and_per_row_refresh():
    contract = _slice("## Security Contract", "## Step 0")
    token_rule = contract[contract.index("print-access-token") :]
    assert "16a–16c" in token_rule[:400]
    assert "21a–21n" in token_rule[:400]
    assert "refreshed at the start" in contract
    assert "`metadata.items`" in contract
    assert "Row 22a never reads `metadata.items`" in contract
    assert "deleted after the last page of 16c and again after the last page of 21n" in contract
    assert "Never Read a `monitoring-*.json` raw file" in contract
    assert "summarize-monitoring.py" in contract


def test_consent_block_discloses_cloud_monitoring_reads():
    consent = _slice("## Step 1: Consent Gate", "## Step 2: Capture")
    for needle in (
        "Cloud Monitoring",
        "monitoring.timeSeries.list",
        "30 days of hourly CPU, memory, disk and connection",
        "Ops Agent",
        "prompts, or completions",
    ):
        assert needle in consent, needle


def test_only_the_script_reads_raw_monitoring_files():
    assert "Never Read a `monitoring-*.json` raw file" in LIVE
    assert 'python3 "$PLUGIN_ROOT/skills/gcp-to-aws/scripts/summarize-monitoring.py"' in LIVE
    assert "--window-start" in LIVE and "--window-end" in LIVE
    assert "utilization-summary.json" in LIVE
    for md in sorted((GCP_REFS / "phases").rglob("*.md")):
        for n, line in enumerate(md.read_text().splitlines(), start=1):
            if "monitoring-" in line and ".json" in line and re.search(r"\bRead\b", line):
                assert "Never Read" in line, f"{md.relative_to(PLUGIN_ROOT)}:{n}: {line}"


def test_notes_and_error_table_treat_monitoring_failures_as_skipped():
    note = _slice("**Utilization-metrics note (rows 21–22a).**", "**Sizing caveat:**")
    for needle in ("30 days", "whole hour", "`pageSize` counts points", "never a halt", "expire after an hour"):
        assert needle in note, needle
    errors = _slice("## Error Handling", "## Scope Boundary")
    assert "Monitoring row 4xx / API disabled" in errors
    assert "`no_data`" in errors


# --------------------------------------------------------------------------- join + merge


def test_step_3_joins_the_summary_and_step_6_carries_it():
    step3 = _slice("## Step 3", "## Step 4")
    assert "utilization" in step3
    assert "`config.id`" in step3 and "`instance_id`" in step3
    assert '"$GCP_PROJECT:" + config.name' in step3 and "`database_id`" in step3
    assert "Compare ids as strings" in step3
    step6 = " ".join(_slice("## Step 6", "## Step 7").split())
    assert "utilization" in step6
    assert "attach the live entry's `utilization` object as a sibling of `config`" in step6
    assert "`utilization` is never a `config_conflicts` entry" in step6
    scope = _slice("## Scope Boundary", "Nothing else.**")
    assert "`utilization` from `utilization-summary.json`" in scope


# --------------------------------------------------------------------------- schema + report


def test_schema_documents_utilization_in_live_extensions_only():
    text = SCHEMA.read_text()
    lines = text.splitlines()
    # scripts/artifact-contracts.json anchors `@L128` to the fence that opens the
    # single-resource example (validator line numbers are 1-based).
    assert lines[127] == "```json" and lines[128] == "{", "the @L128 anchor must not move"
    live = text[text.index("### Live discovery extensions") :]
    for needle in (
        "`utilization`",
        "mig_member",
        "samples_expected",
        "samples_present",
        '"resource_type": "gce_instance|cloudsql_database"',
        '"coverage": "sufficient|insufficient|no_data"',
        '"status": "unavailable|no_data"',
        "disk_bytes_used",
        "database_id",
        "A 1.0 inventory without it still validates",
        "Not yet used for sizing",
    ):
        assert needle in live, needle
    assert "utilization" not in text[: text.index("### Live discovery extensions")]


def test_report_exclusions_say_utilization_is_not_yet_used_for_sizing():
    text = REPORT.read_text()
    exclusions = text[text.index("**Exclusions list:**") : text.index("**Terraform validation:**")]
    assert "not yet used for sizing" in exclusions
    assert "`utilization`" in exclusions
    assert "Cloud Monitoring read access" in exclusions
    # Step 2d emits an all-no_data summary even when every monitoring row was
    # skipped, so the "captured" branch must not fire on `utilization` alone.
    assert "`coverage` is not `no_data`" in exclusions
    assert "every `utilization.coverage` is `no_data`" in exclusions
    assert "when any inventory resource carries `utilization`" not in exclusions
    # `coverage` is CPU-only, so the rule is three-way: a numeric memory/disk/
    # connections block beside `coverage: no_data` is a partial capture, not a
    # missing-read-access case.
    assert "(i)" in exclusions and "(ii)" in exclusions and "(iii)" in exclusions
    assert "partial 30-day utilization was captured" in exclusions
    assert "name the metrics" in exclusions
    assert "CPU coverage is unavailable" in exclusions
    for block in ("`memory`", "`disk_bytes_used`", "`connections`"):
        assert block in exclusions, block
    assert "no `utilization` object anywhere has a numeric block" in exclusions


def _exclusion_branch(resources: list[dict]) -> str:
    """The documented three-way rule, applied to inventory resources."""
    utilizations = [r["utilization"] for r in resources if "utilization" in r]
    if any(u["coverage"] != "no_data" for u in utilizations):
        return "captured"
    blocks = ("memory", "disk_bytes_used", "connections")
    if any("p95" in u.get(block, {}) for u in utilizations for block in blocks):
        return "partial"
    return "read_access"


def test_partial_capture_inventory_validates_and_is_not_the_read_access_case(tmp_path):
    inventory = json.loads(INVENTORY.read_text())
    assert _exclusion_branch(inventory["resources"]) == "captured"
    # Reviewer's shape: CPU rows skipped (coverage no_data everywhere) while the
    # memory row succeeded with a complete numeric block.
    for r in inventory["resources"]:
        u = r.get("utilization")
        if u is None:
            continue
        u["cpu"] = {"status": "no_data"}
        u["coverage"] = "no_data"
        if u["resource_type"] == "gce_instance":
            u["burst"] = False
            u["idle"] = False
    partial = [r["utilization"] for r in inventory["resources"] if "utilization" in r]
    assert all(u["coverage"] == "no_data" for u in partial)
    assert any("p95" in u["memory"] for u in partial)
    assert _exclusion_branch(inventory["resources"]) == "partial"
    run_dir = tmp_path / "after-discover"
    run_dir.mkdir()
    (run_dir / "gcp-resource-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    report = _run_validator(run_dir)
    assert report["checked_artifacts"] == 1
    assert _unbaselined_errors(report) == []
    # Every metric a status block: only then does the read-access sentence apply.
    for u in partial:
        for block in ("memory", "disk_bytes_used", "connections"):
            if block in u:
                u[block] = {"status": "no_data"}
    assert _exclusion_branch(inventory["resources"]) == "read_access"


# --------------------------------------------------------------------------- fixture inventory


def test_fixture_inventory_with_utilization_passes_the_contract():
    report = _run_validator(INVENTORY.parent)
    assert report["checked_artifacts"] == 1
    assert _unbaselined_errors(report) == []
    inventory = json.loads(INVENTORY.read_text())
    with_util = [r for r in inventory["resources"] if "utilization" in r]
    assert len(with_util) == 3
    expected = {
        (u["resource_type"], u.get("instance_id") or u.get("database_id")): u
        for u in json.loads(EXPECTED_SUMMARY.read_text())["resources"]
    }
    for r in with_util:
        u = r["utilization"]
        assert "config" in r
        key = (u["resource_type"], u.get("instance_id") or u.get("database_id"))
        assert u == expected[key], r["address"]
        if u["resource_type"] == "gce_instance":
            assert r["config"]["id"] == u["instance_id"]
            assert r["config"]["zone"].rsplit("/", 1)[-1] == u["zone"]
        else:
            assert u["database_id"] == f"{inventory['metadata']['project']}:{r['config']['name']}"


def test_fixture_inventory_without_utilization_still_passes(tmp_path):
    inventory = json.loads(INVENTORY.read_text())
    for r in inventory["resources"]:
        r.pop("utilization", None)
    run_dir = tmp_path / "after-discover"
    run_dir.mkdir()
    (run_dir / "gcp-resource-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    report = _run_validator(run_dir)
    assert report["checked_artifacts"] == 1
    assert _unbaselined_errors(report) == []


def test_expected_summary_fits_the_byte_budget():
    assert EXPECTED_SUMMARY.stat().st_size < 65536
