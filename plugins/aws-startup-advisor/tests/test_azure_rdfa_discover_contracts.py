"""Behavioral and prose contracts for Azure RDfA discovery."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DISCOVER_DIR = PLUGIN_ROOT / "skills/azure-to-aws/references/phases/discover"
DISCOVER = DISCOVER_DIR / "discover.md"
DISCOVER_RDFA = DISCOVER_DIR / "discover-rdfa.md"
DISCOVER_ASSEMBLE = DISCOVER_DIR / "discover-assemble.md"
DISCOVER_LIVE = DISCOVER_DIR / "discover-live.md"
SCHEMA_AZURE = PLUGIN_ROOT / "skills/azure-to-aws/references/shared/schema-discover-azure.md"
SCHEMA_AI = PLUGIN_ROOT / "skills/azure-to-aws/references/shared/schema-discover-ai.md"
THRESHOLDS = PLUGIN_ROOT / "skills/azure-to-aws/knowledge/estimate/rightsizing-thresholds.json"
FIXTURE_ROOT = PLUGIN_ROOT / "fixtures/azure-rdfa-report"
FINAL_RUN = PLUGIN_ROOT / "fixtures/azure-rdfa-final/after-discover"
VALIDATOR = PLUGIN_ROOT / "scripts/validate-artifacts.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _flatten_metric_batches(batches: list[dict]) -> list[dict]:
    rows = []
    for batch in batches:
        assert isinstance(batch, dict) and isinstance(batch.get("Metrics"), list)
        rows.extend(batch["Metrics"])
    return rows


def _eligible(row: dict, window_days=None, minimum=14) -> bool:
    return (
        row["MetricError"] is False
        and row["MetricCount"] > 0
        and isinstance(window_days, (int, float))
        and window_days >= minimum
    )


def _normalize_pool(row: dict) -> dict:
    desired = int(row["Nodes"])
    minimum, maximum = int(row["AutoscaleMin"]), int(row["AutoscaleMax"])
    if row["Autoscale"].lower() != "true" or (
        desired > 0 and minimum == maximum == 0
    ):
        minimum = maximum = desired
    # EKS requires maxSize >= 1 (Capacity minimum). A legitimate zero-node Azure
    # user pool would otherwise normalize to max_size 0 and be rejected by the EKS
    # API. Floor the maximum to 1 while keeping desired/minimum at their real zero.
    if maximum == 0:
        maximum = 1
    assert minimum <= desired <= maximum
    assert maximum >= 1
    return {"desired_size": desired, "min_size": minimum, "max_size": maximum}


def _map_vm(row: dict) -> dict:
    disk = {}
    if row.get("OSDisk") not in {None, "None", "Custom VHD"}:
        disk["storage_account_type"] = row["OSDisk"]
    if row.get("OSDiskSizeGB") is not None:
        disk["disk_size_gb"] = row["OSDiskSizeGB"]
    return {"size": row["Size"], "os_disk": disk}


def _fingerprint_directory(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(files.items()):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(value)
    return digest.hexdigest()


def _source_manifest(path: str, source_type: str, files: dict[str, bytes]) -> dict:
    return {
        "source_path": path,
        "source_type": source_type,
        "fingerprint": _fingerprint_directory(files),
    }


def _discover_candidates(workspace: Path, prior_manifest: dict | None = None) -> list[Path]:
    candidates = list(workspace.rglob("*ResourcesReport*.zip"))
    candidates.extend({path.parent for path in workspace.rglob("Inventory_*.json")})
    if prior_manifest:
        prior_source = Path(prior_manifest["source_path"])
        if prior_source.exists() and prior_source not in candidates:
            candidates.append(prior_source)
    return candidates


def _prepare_zip(source: Path, output: Path) -> tuple[list[dict], list[dict]]:
    inventories = []
    warnings = []

    def prepare_archive(archive: Path) -> None:
        try:
            with zipfile.ZipFile(archive) as report:
                report.extractall(output / archive.stem)
        except (OSError, zipfile.BadZipFile, RuntimeError) as error:
            warnings.append({
                "code": "rdfa_report_unreadable",
                "identifier": archive.name,
                "detail": str(error),
            })
            return
        for nested in (output / archive.stem).rglob("*.zip"):
            prepare_archive(nested)
        for inventory in (output / archive.stem).rglob("Inventory_*.json"):
            try:
                inventories.append(json.loads(inventory.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as error:
                warnings.append({
                    "code": "rdfa_report_unreadable",
                    "identifier": inventory.name,
                    "detail": str(error),
                })

    prepare_archive(source)
    return inventories, warnings


def _discover_outputs(*, iac=False, live=False, rdfa=False, app_ai=False) -> set[str]:
    outputs = set()
    if iac or live or rdfa:
        outputs.update({"azure-resource-inventory.json", "azure-resource-clusters.json"})
    if app_ai:
        outputs.add("ai-workload-profile.json")
    return outputs


def _reconcile_ai(entries: list[dict]) -> tuple[list[dict], set[str]]:
    by_id = {}
    sources = set()
    for entry in entries:
        sources.add(entry["source"])
        current = by_id.setdefault(entry["azure_id"], {"azure_id": entry["azure_id"], "sources": []})
        current["sources"].append(entry["source"])
        current.update({k: v for k, v in entry.items() if k not in {"source", "config"}})
        current.setdefault("config", {}).update(entry.get("config", {}))
    return list(by_id.values()), sources


# Producer-compatible execution simulations

def test_metrics_batches_flatten_real_envelopes_and_accept_empty_batch() -> None:
    batch = _load("metrics.json")
    rows = _flatten_metric_batches([batch, {"Metrics": []}])
    assert len(rows) == len(batch["Metrics"])
    assert all("StartTime" not in row and "EndTime" not in row for row in rows)


def test_error_empty_and_sampled_zero_have_distinct_eligibility() -> None:
    rows = _load("metrics.json")["Metrics"]
    errored = next(row for row in rows if row["MetricError"])
    empty = next(row for row in rows if row["Name"] == "vm-empty")
    sampled_zero = next(row for row in rows if row["Name"] == "vm-idle")
    assert not _eligible(errored, 31)
    assert not _eligible(empty, 31)
    assert _eligible(sampled_zero, 31)
    assert not _eligible(sampled_zero, None)


def test_report_only_and_app_code_plus_report_are_admitted() -> None:
    assert _discover_outputs(rdfa=True) == {
        "azure-resource-inventory.json",
        "azure-resource-clusters.json",
    }
    assert _discover_outputs(rdfa=True, app_ai=True) == {
        "azure-resource-inventory.json",
        "azure-resource-clusters.json",
        "ai-workload-profile.json",
    }
    assert _discover_outputs() == set()


def test_source_identity_reuses_only_exact_source_and_replacement_wins() -> None:
    first = _source_manifest("/reports/a", "directory", {"Inventory_a.json": b"one"})
    repeated = _source_manifest("/reports/a", "directory", {"Inventory_a.json": b"one"})
    replaced = _source_manifest("/reports/b", "directory", {"Inventory_b.json": b"two"})
    changed_zip = _source_manifest("/reports/a.zip", "zip", {"a.zip": b"new bytes"})
    assert first == repeated
    assert first != replaced
    assert first != changed_zip


def test_external_directory_reentry_seeds_recorded_source_without_new_input(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    external = tmp_path / "outside-workspace" / "report"
    workspace.mkdir()
    external.mkdir(parents=True)
    inventory = external / "Inventory_external.json"
    inventory.write_text('{"VirtualMachines": []}', encoding="utf-8")
    prior = _source_manifest(str(external), "directory", {inventory.name: inventory.read_bytes()})

    assert _discover_candidates(workspace, prior) == [external]


def test_corrupt_selected_report_records_preparation_warning(tmp_path: Path) -> None:
    corrupt = tmp_path / "Selected_ResourcesReport_2025.zip"
    corrupt.write_bytes(b"not a zip")

    inventories, warnings = _prepare_zip(corrupt, tmp_path / "prepared")

    assert inventories == []
    assert warnings[0]["code"] == "rdfa_report_unreadable"
    assert warnings[0]["identifier"] == corrupt.name


def test_partial_nested_report_keeps_valid_inner_and_warns_for_bad_inner(tmp_path: Path) -> None:
    good_inner = tmp_path / "good.zip"
    with zipfile.ZipFile(good_inner, "w") as report:
        report.writestr("Inventory_good.json", '{"VirtualMachines": []}')
    outer = tmp_path / "AllSubscriptions_ResourcesReport_2025.zip"
    with zipfile.ZipFile(outer, "w") as report:
        report.write(good_inner, "good.zip")
        report.writestr("bad.zip", b"not a zip")

    inventories, warnings = _prepare_zip(outer, tmp_path / "prepared")

    assert inventories == [{"VirtualMachines": []}]
    assert any(warning["identifier"] == "bad.zip" for warning in warnings)


def test_fixed_and_autoscaled_aks_bounds_are_valid() -> None:
    pools = _load("inventory.json")["AKS"]
    assert pools[0]["Autoscale"] == "true"
    fixed = _normalize_pool(pools[0])
    autoscaled = _normalize_pool(pools[2])
    assert fixed == {"desired_size": 3, "min_size": 3, "max_size": 3}
    assert autoscaled == {"desired_size": 1, "min_size": 0, "max_size": 2}


def test_zero_node_aks_pool_gets_eks_valid_max_size() -> None:
    """Azure permits a user pool with zero nodes. Normalizing its absent 0/0 bounds
    to 0/0/0 would emit max_size 0, which the EKS API rejects (maxSize minimum 1).
    Keep desired/minimum at the real zero and floor the maximum to 1."""
    zero_node = {"Nodes": "0", "Autoscale": "false", "AutoscaleMin": "0", "AutoscaleMax": "0"}
    assert _normalize_pool(zero_node) == {"desired_size": 0, "min_size": 0, "max_size": 1}


def test_vm_os_disk_maps_to_canonical_nested_shape() -> None:
    mapped = _map_vm(_load("inventory.json")["VirtualMachines"][0])
    assert mapped["os_disk"] == {
        "storage_account_type": "Premium_LRS",
        "disk_size_gb": 128,
    }
    assert "caching" not in mapped["os_disk"]


def test_rdfa_ml_workspace_contributes_and_mixed_identity_reconciles() -> None:
    workspace = _load("inventory.json")["MachineLearning"][0]
    rdfa = {"azure_id": workspace["ID"], "source": "rdfa", "config": {"sku": "Basic"}}
    merged, sources = _reconcile_ai([
        {"azure_id": workspace["ID"], "source": "terraform", "address": "azurerm_machine_learning_workspace.main", "config": {}},
        rdfa,
        {"azure_id": workspace["ID"], "source": "live", "config": {"sku": "Enterprise"}},
    ])
    assert len(merged) == 1
    assert set(merged[0]["sources"]) == {"terraform", "rdfa", "live"}
    assert sources == {"terraform", "rdfa", "live"}


# Published prose and artifact contracts

def test_rw_fragment_owns_no_executable_preparation() -> None:
    phase = _text(DISCOVER)
    fragment = _text(DISCOVER_RDFA)
    assert "main-window pre-dispatch action" in phase
    assert "never extracts ZIPs, runs Python" in phase
    assert "This `rw` fragment reads only prepared files" in fragment
    assert "Write a throwaway extraction script" not in fragment


def test_absent_report_guidance_is_reachable_before_trigger() -> None:
    phase = _text(DISCOVER)
    guidance = phase.index("If no candidate exists, output")
    dispatch = phase.index("Run each fragment whose `_trigger` holds")
    assert guidance < dispatch


def test_main_window_owns_reentry_and_preparation_failure_contracts() -> None:
    phase = _text(DISCOVER)
    assembler = _text(DISCOVER_ASSEMBLE)
    assert "existing manifest's `source_path`" in phase
    assert "preparation-result.json" in phase
    assert "rdfa_report_unreadable" in phase
    assert "corrupt or password-protected ZIP" in phase
    assert "continue preparing every other valid inner ZIP" in phase
    assert "preparation-result.json" in assembler


def test_discover_and_assembler_include_rdfa_everywhere() -> None:
    phase = _text(DISCOVER)
    assembler = _text(DISCOVER_ASSEMBLE)
    assert "OR a validated RDfA preparation manifest" in phase
    assert "A report-only run is an infrastructure run" in assembler
    assert "rdfa (fragment contribution" in assembler


def test_schema_registers_rdfa_inventory_and_ai_provenance() -> None:
    azure = _text(SCHEMA_AZURE)
    ai = _text(SCHEMA_AI)
    assert '"rdfa_metadata": {}' in azure
    assert "## rdfa_metadata" in azure
    assert '"rdfa": false' in ai
    assert "rdfa_report" in ai


def test_confidence_contract_requires_samples_and_known_window() -> None:
    rules = json.loads(THRESHOLDS.read_text())
    requirement = rules["confidence_rules"]["measured_requires"]
    assert "sample_count > 0" in requirement
    assert "Null/unknown window_days fails closed" in requirement


def test_live_and_rdfa_use_same_node_pool_key() -> None:
    assert "config.node_pools[]" in _text(DISCOVER_RDFA)
    assert "rename the array's own key `nodePools` → `node_pools`" in _text(DISCOVER_LIVE)


def test_fixture_corrupt_zip_is_invalid_and_tie_break_is_deterministic() -> None:
    corrupt = next((PLUGIN_ROOT / "fixtures/azure-rdfa-report-corrupt-zip").glob("*.zip"))
    assert not zipfile.is_zipfile(corrupt)
    files = [p.name for p in (PLUGIN_ROOT / "fixtures/azure-rdfa-report-multi-zip").glob("*.zip")]
    newest = max(files, key=lambda name: "".join(ch for ch in name if ch.isdigit()))
    assert newest == "AllSubscriptions_ResourcesReport_2025-06-01_12-00-00.zip"


def test_final_rdfa_inventory_passes_real_artifact_validator() -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--run-dir", str(FINAL_RUN), "--skill", "azure-to-aws", "--no-baseline", "--json"],
        cwd=PLUGIN_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
