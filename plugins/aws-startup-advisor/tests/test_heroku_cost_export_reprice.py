"""Replay workshop ordering with repository artifacts, not a live IDE/pricing run."""
import copy
import hashlib
import shutil
import subprocess
import sys

import pytest

from test_cost_export_inputs import PLUGIN, WRITER, plan, read, save, writer


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replay_heroku_reprice(run, *, old_stamp=False):
    """Use captured quotes without inventing their missing row/resource evidence."""
    seed = PLUGIN / "fixtures/heroku-workshop/seed"
    repriced = PLUGIN / "fixtures/heroku-workshop/after-arm64-reprice"
    shutil.copytree(seed, run)
    module = writer()
    preferences = read(run, "preferences.json")
    preferences["workshop"] = {"active": True, "active_scenario_id": "scenario-001"}
    save(run, "preferences.json", preferences)
    index = {
        "baseline_scenario_id": "scenario-001",
        "active_scenario_id": "scenario-001",
        "inventory_fingerprint": digest(run / "heroku-resource-inventory.json"),
        "scenarios": [{"scenario_id": "scenario-001", "source": "baseline"}],
    }
    save(run, "scenarios/index.json", index)
    save(run, "scenarios/scenario-001.json", index["scenarios"][0])
    for name in ("preferences.json", "aws-design.json", "estimation-infra.json"):
        shutil.copyfile(run / name, run / "scenarios" / f"scenario-001.{name}")
    historical = {path.name: digest(path) for path in (run / "scenarios").glob("scenario-001.*")}
    state = read(run, ".phase-status.json")
    state["phases"]["workshop"] = "in_progress"
    save(run, ".phase-status.json", state)

    # Apply captured sheet changes but retain the previous active selection.
    preferences = read(repriced, "preferences.json")
    preferences["workshop"]["active_scenario_id"] = index["active_scenario_id"]
    save(run, "preferences.json", preferences)
    assert digest(run / "heroku-resource-inventory.json") == index["inventory_fingerprint"]

    # Refresh step 3a allocates an invocation value before Design and Estimate.
    destination = f"scenario-{max(int(row['scenario_id'].split('-')[1]) for row in index['scenarios']) + 1:03d}"
    assert not list((run / "scenarios").glob(f"{destination}.*"))
    shutil.copyfile(repriced / "aws-design.json", run / "aws-design.json")
    snapshot = module.capture_inputs(run, "estimation-infra.json")
    selection_during_pricing = read(run, "preferences.json")["workshop"]["active_scenario_id"]
    assert selection_during_pricing == read(run, "scenarios/index.json")["active_scenario_id"] == "scenario-001"

    # Fixed fixture quote stands in for the cost engine; no new price is calculated.
    estimate = read(repriced, "estimation-infra.json")
    stamp = selection_during_pricing if old_stamp else destination
    estimate["workshop"]["scenario_id"] = stamp
    estimate["export_inputs"] = {
        "snapshot": snapshot,
        "rows": {
            pointer: {"monthlyCost": item["monthlyCost"],
                      "estimateInput": {"source": {"scenarioId": stamp}}}
            for pointer, item in module._selected_cost_rows(estimate, "estimation-infra.json")
        },
    }
    save(run, "estimation-infra.json", estimate)
    # Reproduce the original bug by permitting its old stamp only in the negative replay.
    if not old_stamp:
        assert estimate["workshop"]["scenario_id"] == destination
    for name in ("preferences.json", "aws-design.json", "estimation-infra.json"):
        shutil.copyfile(run / name, run / "scenarios" / f"{destination}.{name}")
    save(run, f"scenarios/{destination}.json", {"scenario_id": destination, "source": "workshop"})
    index["scenarios"].append({"scenario_id": destination, "source": "workshop"})
    index["active_scenario_id"] = destination
    save(run, "scenarios/index.json", index)
    preferences["workshop"]["active_scenario_id"] = destination
    save(run, "preferences.json", preferences)
    assert historical == {path.name: digest(path) for path in (run / "scenarios").glob("scenario-001.*")}
    assert read(run, ".phase-status.json") == state
    assert digest(run / "heroku-resource-inventory.json") == index["inventory_fingerprint"]
    return {
        "evidenceKind": "Repository-fixture workflow replay; no actual IDE execution or new price/resource provenance.",
        "selectionDuringPricing": selection_during_pricing,
        "allocatedBeforePricing": destination,
        "estimateStamp": stamp,
        "finalIndexSelection": index["active_scenario_id"],
        "finalPreferencesSelection": preferences["workshop"]["active_scenario_id"],
        "estimateMatchesNewSnapshot": estimate == read(run, f"scenarios/{destination}.estimation-infra.json"),
        "historicalScenarioDigestsUnchanged": historical,
        "inventoryDigestUnchanged": index["inventory_fingerprint"],
        "sourceQuote": str((repriced / "estimation-infra.json").relative_to(PLUGIN)),
        "sourceQuoteSha256": digest(repriced / "estimation-infra.json"),
    }


def test_heroku_reprice_selects_the_reserved_estimate_without_rewriting_history(tmp_path):
    run = tmp_path / "run"
    trace = replay_heroku_reprice(run)
    assert trace["selectionDuringPricing"] == "scenario-001"
    assert trace["estimateStamp"] == trace["finalIndexSelection"] == "scenario-002"
    assert writer()._selected_scenario(run, "estimation-infra.json", read(run, "estimation-infra.json")) == "scenario-002"
    subprocess.run([sys.executable, str(WRITER), "--migration-dir", str(run), "--schema-version", "2"],
                   check=True, capture_output=True)
    result = read(run, "plan.json")
    assert result["sourcePlatform"] == "HEROKU"
    assert result["schemaVersion"] == 2
    assert result["cost"]["awsMonthlyBasis"] == "BALANCED"
    assert result["cost"]["awsMonthly"] == 88
    rows = result["cost"]["awsServiceItems"]
    assert [row["monthlyCost"] for row in rows] == [43, 45]
    for row in rows:
        context = row["estimateInput"]
        assert context["source"]["scenarioId"] == "scenario-002"
        assert context["source"]["estimateFile"] == "estimation-infra.json"
        assert set(context) == {"source"}  # Unknown configuration/upfront/joins stay absent.
        assert "resourceIds" not in context["source"]
    legacy = plan(run, 1)
    without_context = copy.deepcopy(result)
    without_context["schemaVersion"] = 1
    for row in without_context["cost"]["awsServiceItems"]:
        del row["estimateInput"]
    assert without_context == legacy


def test_old_assembler_stamp_still_fails_even_when_snapshot_matches(tmp_path):
    run = tmp_path / "run"
    trace = replay_heroku_reprice(run, old_stamp=True)
    assert trace["estimateMatchesNewSnapshot"]
    with pytest.raises(ValueError, match="scenario selection mismatch"):
        writer()._selected_scenario(run, "estimation-infra.json", read(run, "estimation-infra.json"))
    assert all("estimateInput" not in row for row in plan(run)["cost"]["awsServiceItems"])


@pytest.mark.parametrize("stale", ["row_scenario", "input_digest"])
def test_reprice_does_not_relabel_stale_retained_evidence(tmp_path, stale):
    run = tmp_path / "run"
    replay_heroku_reprice(run)
    estimate = read(run, "estimation-infra.json")
    if stale == "row_scenario":
        for entry in estimate["export_inputs"]["rows"].values():
            entry["estimateInput"]["source"]["scenarioId"] = "scenario-001"
    else:
        estimate["export_inputs"]["snapshot"]["files"]["aws-design.json"] = writer()._input_digest(
            read(run, "scenarios/scenario-001.aws-design.json"))
    save(run, "estimation-infra.json", estimate)
    save(run, "scenarios/scenario-002.estimation-infra.json", estimate)
    assert all("estimateInput" not in row for row in plan(run)["cost"]["awsServiceItems"])


def test_heroku_workflow_wires_allocation_before_estimate():
    """The workflow is prose; guard its wiring separately from the Python replay."""
    phases = PLUGIN / "skills/heroku-to-aws/references/phases"
    refresh = (phases / "workshop/workshop-refresh.md").read_text()
    assemble = (phases / "estimate/estimate-assemble.md").read_text()
    engine = (phases / "estimate/estimate-cost-engine.md").read_text()
    allocation = refresh.index("### 3a. Allocate the destination before repricing")
    pricing = refresh.index("### 5. Re-run Estimate (inner)")
    snapshot = refresh.index("### 6. Snapshot new scenario")
    assert allocation < pricing < snapshot
    assert "estimate_scenario_id" in refresh[allocation:pricing]
    assert "with `estimate_scenario_id` from" in refresh[pricing:snapshot]
    assert "Allocate next id" not in refresh[snapshot:]
    assert '"scenario_id": "<estimate_scenario_id when supplied;' in assemble
    assert "caller's `estimate_scenario_id`" in engine
