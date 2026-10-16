"""Contract tests for the Azure RDfA discovery fragment (`discover-rdfa.md`).

Design: /Users/lkleier/Downloads/startups-pr/.agents/tasks/azure-rdfa-discovery/design.md
Plan:   /Users/lkleier/Downloads/startups-pr/.agents/tasks/azure-rdfa-discovery/plan.md

This plugin's azure-to-aws skill files are prose instructions an LLM worker
reads and executes — there is no runtime fragment executor to exercise
directly, matching every existing test in this suite for azure/heroku
discovery (`test_azure_discover_ordering.py`,
`test_heroku_discover_addon_identity.py`). So this module does two things:

1. Prose/string-assertion checks against `discover-rdfa.md`, `discover-live.md`,
   and `schema-discover-azure.md` pinning the design decisions that are easy to
   silently regress (MetricPercentile vs MetricValue, the node_pools rename
   landing in both fragments, the nested-ARM-id derivation, the Scale guard's
   projected-field list, the new warnings code).
2. Fixture-shape assertions directly against the JSON/ZIP fixtures under
   `fixtures/azure-rdfa-report*/` (not against a nonexistent runtime parser) —
   these pin the FIXTURE's own internal consistency, the same role
   `test_ai_workload_profile_contracts.py`'s `_assert_profile_semantics` plays
   for its fixtures.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

DISCOVER_RDFA = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-rdfa.md"
)

DISCOVER_LIVE = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-live.md"
)

DISCOVER = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover.md"
)

SCHEMA_DISCOVER_AZURE = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "shared"
    / "schema-discover-azure.md"
)

ESTIMATE_INFRA = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "estimate"
    / "estimate-infra.md"
)

FIXTURE_ROOT = PLUGIN_ROOT / "fixtures" / "azure-rdfa-report"
FIXTURE_CORRUPT_ZIP_DIR = PLUGIN_ROOT / "fixtures" / "azure-rdfa-report-corrupt-zip"
FIXTURE_MULTI_ZIP_DIR = PLUGIN_ROOT / "fixtures" / "azure-rdfa-report-multi-zip"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- prose contracts


def test_discover_rdfa_has_no_consent_gate_language() -> None:
    """Guards against reintroducing a Part A/Part B split: RDfA is a plain
    fragment, no `_preconditions`/consent-gate block of its own."""
    text = _text(DISCOVER_RDFA)
    assert "_preconditions" not in text
    assert "Consent Gate" not in text
    assert "[A] Proceed" not in text


def test_discover_rdfa_uses_metric_percentile_not_metric_value_for_p95() -> None:
    text = _text(DISCOVER_RDFA)
    assert '"p95": 42.3,                     // MetricPercentile, as-is' in text
    assert "never `MetricValue`" in text


def test_discover_rdfa_nested_arm_id_derivation_is_full_path_not_parent_type() -> None:
    text = _text(DISCOVER_RDFA)
    assert "Microsoft.Sql/managedInstances/databases" in text
    idx = text.index("Microsoft.Sql/managedInstances/databases")
    window = text[max(0, idx - 400) : idx + 400]
    assert "the database's own type, not the parent managed instance's" in window
    # the parent-only type must not appear as the resolved answer in that sentence
    assert "`azure_type = Microsoft.Sql/managedInstances`\n" not in window


def test_discover_rdfa_and_discover_live_both_use_node_pools_snake_case() -> None:
    rdfa_text = _text(DISCOVER_RDFA)
    live_text = _text(DISCOVER_LIVE)
    assert "config.node_pools[]" in rdfa_text or "**`config.node_pools[]`**" in rdfa_text
    assert "node_pools" in rdfa_text
    # discover-live.md's row-4 notes column must carry the array-key rename too,
    # proving the cross-fragment rename landed in both files, not only this one.
    assert "rename the array's own key `nodePools` → `node_pools`" in live_text


def test_discover_rdfa_scale_guard_keeps_start_and_end_time() -> None:
    text = _text(DISCOVER_RDFA)
    assert "_extract_rdfa.py" in text
    idx = text.index("Projects ONLY the fields")
    window = text[idx : idx + 400]
    assert "StartTime" in window
    assert "EndTime" in window


def test_discover_rdfa_size_rename_is_lowercase() -> None:
    text = _text(DISCOVER_RDFA)
    assert "`Size` → **`size`**" in text


def test_schema_discover_azure_has_rdfa_report_unreadable_warning_code() -> None:
    text = _text(SCHEMA_DISCOVER_AZURE)
    assert "`rdfa_report_unreadable`" in text
    idx = text.index("rdfa_report_unreadable")
    window = text[idx : idx + 400]
    assert "could not be extracted or parsed" in window


def test_discover_fragments_list_includes_rdfa_before_assemble() -> None:
    text = _text(DISCOVER)
    rdfa_idx = text.index("_id: rdfa")
    assemble_idx = text.index("_assemble:")
    assert rdfa_idx < assemble_idx
    assert "phases/discover/discover-rdfa.md" in text


def test_estimate_infra_rung_2_no_longer_says_deferred_verbatim() -> None:
    text = _text(ESTIMATE_INFRA)
    assert "needs RDfA (deferred)" not in text
    assert "usage-quantity-only" in text


# --------------------------------------------------------------------------- fixture shape


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_fixture_aks_rows_share_one_id() -> None:
    inventory = _load_fixture("inventory.json")
    aks_rows = inventory["AKS"]
    assert len(aks_rows) == 3
    ids = {row["ID"] for row in aks_rows}
    assert len(ids) == 1
    pool_names = {row["NodePoolName"] for row in aks_rows}
    assert pool_names == {"systempool", "apppool", "gpupool"}


def test_fixture_rediscache_rows_discriminate_by_family() -> None:
    inventory = _load_fixture("inventory.json")
    redis_rows = inventory["RedisCache"]
    assert len(redis_rows) == 2
    families = {row["Family"] for row in redis_rows}
    assert families == {"C1", "enterprise"}


def test_fixture_sql_database_metrics_share_id_with_different_windows() -> None:
    metrics = json.loads((FIXTURE_ROOT / "metrics.json").read_text(encoding="utf-8"))
    sql_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/"
        "rg-data/providers/Microsoft.Sql/servers/sql-core/databases/orders"
    )
    sql_rows = [row for row in metrics if row["ID"] == sql_id]
    assert len(sql_rows) == 2
    windows = set()
    for row in sql_rows:
        start = row["StartTime"]
        end = row["EndTime"]
        assert start != end
        windows.add((row["Metric"], start, end))
    metrics_seen = {m for m, _, _ in windows}
    assert metrics_seen == {"cpu_used", "storage_percent"}
    # the two rows' windows must differ in length (31-day vs 1-day), proving
    # window_days is computed per-row rather than assumed report-wide
    cpu_row = next(r for r in sql_rows if r["Metric"] == "cpu_used")
    storage_row = next(r for r in sql_rows if r["Metric"] == "storage_percent")
    assert cpu_row["StartTime"] != storage_row["StartTime"]


def test_fixture_vm_row_has_clean_and_metric_error_rows() -> None:
    metrics = json.loads((FIXTURE_ROOT / "metrics.json").read_text(encoding="utf-8"))
    vm_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/"
        "rg-app/providers/Microsoft.Compute/virtualMachines/vm-web-01"
    )
    vm_rows = [row for row in metrics if row["ID"] == vm_id]
    assert len(vm_rows) == 2
    clean = next(r for r in vm_rows if r["Metric"] == "Percentage CPU")
    errored = next(r for r in vm_rows if r["Metric"] == "Available Memory Bytes")
    assert clean["MetricError"] is False
    assert clean["MetricPercentile"] == 42.3
    assert errored["MetricError"] is True
    # MetricError rows carry zeroed numeric fields, bit-for-bit identical to a
    # genuine zero-usage reading, distinguished only by MetricError
    assert errored["MetricPercentile"] == 0
    assert errored["MetricCount"] == 0


def test_fixture_unmapped_collector_resources_derive_azure_type_from_arm_id() -> None:
    inventory = _load_fixture("inventory.json")
    sqlmidb_rows = inventory["SQLMIDB"]
    assert len(sqlmidb_rows) == 1
    assert sqlmidb_rows[0]["ID"].endswith(
        "/providers/Microsoft.Sql/managedInstances/mi1/databases/db1"
    )
    aro_rows = inventory["ARO"]
    assert len(aro_rows) == 1
    assert aro_rows[0]["ID"].endswith(
        "/providers/Microsoft.RedHatOpenShift/openShiftClusters/aro-cluster"
    )


def test_fixture_vm_row_uses_capitalized_size_key_in_raw_inventory() -> None:
    """The RAW fixture uses RDfA's own `Size` spelling — the rename to lowercase
    `size` is the fragment's job (§ Step 2), not the fixture's."""
    inventory = _load_fixture("inventory.json")
    vm_row = inventory["VirtualMachines"][0]
    assert vm_row["Size"] == "Standard_D4s_v5"
    assert "size" not in vm_row


def test_fixture_no_consumption_csv_present() -> None:
    """Decision 4's deferral path: this fixture carries no Consumption_*.csv."""
    assert not list(FIXTURE_ROOT.glob("*.csv"))
    assert not list(FIXTURE_ROOT.glob("Consumption_*"))


def test_fixture_corrupt_zip_is_not_a_valid_zip() -> None:
    files = list(FIXTURE_CORRUPT_ZIP_DIR.glob("*ResourcesReport*.zip"))
    assert len(files) == 1
    corrupt_zip = files[0]
    assert corrupt_zip.stat().st_size > 0
    assert zipfile.is_zipfile(corrupt_zip) is False


def test_fixture_multi_zip_tie_break_normalizes_before_comparing() -> None:
    files = sorted(p.name for p in FIXTURE_MULTI_ZIP_DIR.glob("*ResourcesReport*.zip"))
    assert "AllSubscriptions_ResourcesReport_2025-06-01_12-00-00.zip" in files
    assert "CompanyName_ResourcesReport_20240101000000083a.zip" in files

    def normalized_digits(name: str) -> str:
        # extract the <timestamp> substring the way discover-rdfa.md's tie-break
        # rule does: strip every non-digit character.
        return "".join(ch for ch in name if ch.isdigit())

    newest = max(files, key=normalized_digits)
    assert newest == "AllSubscriptions_ResourcesReport_2025-06-01_12-00-00.zip"

    # A naive raw lexicographic comparison (no normalization) would pick the
    # WRONG file — proving normalization is actually necessary for this pair,
    # not merely harmless.
    raw_newest = max(files)
    assert raw_newest == "CompanyName_ResourcesReport_20240101000000083a.zip"
    assert raw_newest != newest
