"""Writer regression coverage for emit-plan-json.py.

The web-import schema types runId as a lowercase-canonical UUID, but the state
schema (and native `uuidgen` on macOS) can carry an uppercase UUID. The writer
must lowercase a UUID-shaped run_id at the handoff boundary so the emitted plan
still imports. This anchors that canonicalization against a real golden run.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
WRITER = PLUGIN_ROOT / "scripts" / "emit-plan-json.py"
GOLDEN = PLUGIN_ROOT / "fixtures" / "gcp-decision-gate" / "after-decide-complete"


def _load_writer_module():
    """Load emit-plan-json.py as an importable module (hyphenated filename, so it
    can't be imported normally) to unit-test its internal functions directly."""
    spec = importlib.util.spec_from_file_location("emit_plan_json", WRITER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _emit(run: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(WRITER), "--migration-dir", str(run)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"writer exited {result.returncode}: {result.stderr}"
    plan = run / "plan.json"
    assert plan.exists(), f"writer did not emit plan.json: {result.stdout}"
    return json.loads(plan.read_text())


def _seed(tmp_path: Path, run_id: str) -> Path:
    run = tmp_path / "run"
    shutil.copytree(GOLDEN, run)
    status_path = run / ".phase-status.json"
    status = json.loads(status_path.read_text())
    status["run_id"] = run_id
    status_path.write_text(json.dumps(status, indent=2))
    return run


def test_uppercase_uuid_run_id_is_lowercased(tmp_path: Path) -> None:
    upper = "8C1E4F2A-3B6D-4A7E-9F10-5D2C8B7A6E41"
    data = _emit(_seed(tmp_path, upper))
    assert data["runId"] == upper.lower(), f"runId not lowercased: {data.get('runId')!r}"


def test_lowercase_uuid_run_id_is_unchanged(tmp_path: Path) -> None:
    lower = "8c1e4f2a-3b6d-4a7e-9f10-5d2c8b7a6e41"
    data = _emit(_seed(tmp_path, lower))
    assert data["runId"] == lower, f"runId altered: {data.get('runId')!r}"


def test_azure_infra_run_emits_plan(tmp_path: Path) -> None:
    """A representative Azure infrastructure estimate produces the active handoff."""
    golden = PLUGIN_ROOT / "fixtures" / "azure-iac-terraform" / "after-estimate"
    run = tmp_path / "run"
    shutil.copytree(golden, run)
    status_path = run / ".phase-status.json"
    status = json.loads(status_path.read_text())
    status["owning_skill"] = "AZURE_TO_AWS"
    status["run_id"] = "8c1e4f2a-3b6d-4a7e-9f10-5d2c8b7a6e41"
    status_path.write_text(json.dumps(status, indent=2))

    data = _emit(run)
    assert data["sourcePlatform"] == "AZURE"
    assert data["scope"] == "INFRA_ONLY"
    assert data["cost"]["awsMonthlyBasis"] == "BALANCED"
    assert data["cost"]["awsMonthly"] == 460.13
    assert data["cost"]["sourceMonthly"] == 4200
    assert len(data["cost"]["awsServiceItems"]) == 12
    assert round(sum(item["monthlyCost"] for item in data["cost"]["awsServiceItems"]), 2) == 460.13


def test_azure_mixed_run_is_skipped_because_the_estimate_has_no_accuracy_band(tmp_path: Path) -> None:
    """Documented limitation: Azure plan.json is infrastructure-only. A representative Azure
    infra estimate plus a valid AI estimate is a FULL run, which needs a usable overall band
    from both estimates; Azure's records none, so the writer skips (fail open, no file)."""
    run = tmp_path / "run"
    shutil.copytree(PLUGIN_ROOT / "fixtures" / "azure-iac-terraform" / "after-estimate", run)
    shutil.copy(PLUGIN_ROOT / "fixtures" / "estimation-ai" / "multi-provider-direct" / "estimation-ai.json", run)
    status_path = run / ".phase-status.json"
    status = json.loads(status_path.read_text())
    status.update({"owning_skill": "AZURE_TO_AWS", "run_id": "8c1e4f2a-3b6d-4a7e-9f10-5d2c8b7a6e41"})
    status_path.write_text(json.dumps(status, indent=2))
    result = subprocess.run([sys.executable, str(WRITER), "--migration-dir", str(run)], capture_output=True, text=True)
    assert result.returncode == 0
    assert "PLAN_SKIP | reason=FULL run needs a usable accuracy band from both the base and AI estimates" in result.stdout
    assert not (run / "plan.json").exists()
    assert "Azure plans are infrastructure-only" in WRITER.read_text()
    (run / "estimation-ai.json").unlink()
    assert _emit(run)["scope"] == "INFRA_ONLY"
def test_invalid_or_missing_azure_estimates_still_fail_open(tmp_path: Path) -> None:
    golden = PLUGIN_ROOT / "fixtures" / "azure-iac-terraform" / "after-estimate"
    expected_reason = {
        "missing": "PLAN_SKIP | reason=no cost estimate to hand off",
        "malformed": "PLAN_SKIP | reason=unreadable input:",
    }
    for case in ("missing", "malformed"):
        run = tmp_path / case
        shutil.copytree(golden, run)
        status_path = run / ".phase-status.json"
        status = json.loads(status_path.read_text())
        status.update({"owning_skill": "AZURE_TO_AWS", "run_id": "8c1e4f2a-3b6d-4a7e-9f10-5d2c8b7a6e41"})
        status_path.write_text(json.dumps(status, indent=2))
        estimate = run / "estimation-infra.json"
        if case == "missing":
            estimate.unlink()
        else:
            estimate.write_text("{not-json")

        result = subprocess.run(
            [sys.executable, str(WRITER), "--migration-dir", str(run)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout.startswith("PLAN_SKIP"), result.stdout
        assert not (run / "plan.json").exists()


def test_azure_composition_share_is_not_exported_as_accuracy() -> None:
    """The Azure fixture's accuracy_confidence states a per-line composition share
    (RDS is 59% of the priced total) and an observability-only band (+/-35%), not
    an overall accuracy band ('not a simple band', verbatim). Neither must be
    exported as cost.accuracy (PR #435 review, databaseId 4240400318)."""
    module = _load_writer_module()
    golden = PLUGIN_ROOT / "fixtures" / "azure-iac-terraform" / "after-estimate"
    infra = json.loads((golden / "estimation-infra.json").read_text())
    assert module._accuracy(infra) is None, (
        f"composition share exported as accuracy: {module._accuracy(infra)!r}"
    )


def test_accuracy_still_parses_declared_overall_bands() -> None:
    """GCP/Heroku's bare sign-prefixed bands must keep parsing exactly as before."""
    module = _load_writer_module()
    assert module._accuracy({"accuracy_confidence": "+/-5-10%"}) == {"minPercent": 5, "maxPercent": 10}
    assert module._accuracy({"accuracy_confidence": "±30-40%"}) == {"minPercent": 30, "maxPercent": 40}


def test_azure_service_items_use_azure_field_names_and_exclude_floors() -> None:
    """Azure rows carry aws_service/right_sized_monthly, not service/monthly/mid.
    Rollups and rows marked excluded_from_total/exclusion_reason (3 no-rate/
    no-quantity nulls, 2 Windows licensing floors) must not appear in
    awsServiceItems; the row sum must equal the fixture's declared total of
    $460.13 across the 12 eligible rows (PR #435 review, databaseId 4240400321)."""
    module = _load_writer_module()
    golden = PLUGIN_ROOT / "fixtures" / "azure-iac-terraform" / "after-estimate"
    infra = json.loads((golden / "estimation-infra.json").read_text())
    projected = infra["projected_costs"]
    items = module._service_items(projected)
    assert len(items) == 12, f"expected 12 eligible rows, got {len(items)}: {items}"
    assert round(sum(i["monthlyCost"] for i in items), 2) == 460.13
    names = {i["serviceName"] for i in items}
    assert "FSx for Windows File Server" not in names
    assert "DocumentDB" not in names
    assert "Lambda" not in names
    excluded_floor_names = {i["serviceName"] for i in items if i["monthlyCost"] in (70.72, 140.16)}
    assert not excluded_floor_names, f"excluded floor rows leaked into awsServiceItems: {excluded_floor_names}"


def test_azure_non_usd_baseline_is_omitted_from_source_monthly() -> None:
    """current_costs.currency explicitly non-USD (e.g. EUR) must omit
    sourceMonthly rather than copy the figure as if it were USD (PR #435 review,
    databaseId 4240400322)."""
    module = _load_writer_module()
    golden = PLUGIN_ROOT / "fixtures" / "azure-iac-terraform" / "after-estimate"
    infra = json.loads((golden / "estimation-infra.json").read_text())
    eur_infra = json.loads(json.dumps(infra))
    eur_infra["current_costs"]["currency"] = "EUR"
    eur_infra["current_costs"]["azure_monthly"] = 4200
    assert module._source_monthly(eur_infra, "AZURE") is None

    usd_infra = json.loads(json.dumps(infra))
    assert module._source_monthly(usd_infra, "AZURE") == usd_infra["current_costs"]["azure_monthly"]

    assert module._source_monthly({"current_costs": {"gcp_monthly": 300}}, "GCP") == 300


def test_heroku_skill_writer_matches_plugin_copy() -> None:
    """heroku-to-aws invokes the writer from its own scripts/ dir so a standalone
    ``npx skills add --skill heroku-to-aws`` install (which carries only the skill
    tree, not plugin-root scripts/) can still emit the handoff plan. That skill copy
    must stay byte-identical to the shared plugin-level writer — this guards the two
    from drifting, since nothing else keeps them in sync."""
    skill_copy = PLUGIN_ROOT / "skills" / "heroku-to-aws" / "scripts" / "emit-plan-json.py"
    assert skill_copy.exists(), f"heroku skill writer missing: {skill_copy}"
    assert skill_copy.read_bytes() == WRITER.read_bytes(), (
        "heroku skill emit-plan-json.py has drifted from the plugin-level copy; "
        "re-copy plugins/aws-startup-advisor/scripts/emit-plan-json.py"
    )

RENDER_GOLDEN = PLUGIN_ROOT / "skills" / "render-to-aws" / "fixtures" / "expected" / "estimation-infra.json"
RENDER_RUN_ID = "8c1e4f2a-3b6d-4a7e-9f10-5d2c8b7a6e41"
def _render_run(tmp_path: Path, mutate=None, name: str = "render") -> Path:
    run = tmp_path / name
    run.mkdir()
    estimate = json.loads(RENDER_GOLDEN.read_text())
    if mutate is not None:
        mutate(estimate)
    (run / "estimation-infra.json").write_text(json.dumps(estimate))
    (run / ".phase-status.json").write_text(
        json.dumps({"owning_skill": "RENDER_TO_AWS", "run_id": RENDER_RUN_ID.upper()})
    )
    return run
def _build(run: Path, module=None):
    """build_plan in-process, so a test can lift the importer gate on the module."""
    module = module or _load_writer_module()
    return module.build_plan(run, PLUGIN_ROOT / ".claude-plugin" / "plugin.json")


def _writer_with_render_enabled():
    """The writer module with RENDER_TO_AWS mapped, as it will be once the importer is
    confirmed to accept RENDER. Everything below the gate (the Render adapter, the scope
    table, the reconcile guard) stays under test while the shipped default is gated."""
    module = _load_writer_module()
    module.SKILL_TO_PLATFORM = {**module.SKILL_TO_PLATFORM, "RENDER_TO_AWS": "RENDER"}
    return module


def test_render_is_gated_off_until_the_importer_accepts_it(tmp_path: Path) -> None:
    """The importer has not been confirmed to accept sourcePlatform RENDER, so a Render run
    must not produce a plan to upload (the same hold `main` kept on AZURE until it was
    confirmed). The fail-open handoff then adds nothing."""
    module = _load_writer_module()
    assert "RENDER_TO_AWS" not in module.SKILL_TO_PLATFORM
    assert set(module.SKILL_TO_PLATFORM) == {"AZURE_TO_AWS", "GCP_TO_AWS", "HEROKU_TO_AWS"}
    run = _render_run(tmp_path)
    result = subprocess.run(
        [sys.executable, str(WRITER), "--migration-dir", str(run)], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout.startswith("PLAN_SKIP"), result.stdout
    assert "owning_skill 'RENDER_TO_AWS' has no web handoff yet" in result.stdout
    assert not (run / "plan.json").exists()


def test_render_adapter_is_kept_so_enabling_it_is_a_one_line_change() -> None:
    module = _load_writer_module()
    assert module.PLATFORM_SOURCE_FIELD["RENDER"] == ("current_costs", "render_monthly")
    assert module.VALID_SCOPES_BY_PLATFORM["RENDER"] == {"INFRA_ONLY"}
    assert callable(module._render_service_items)


def test_render_infra_run_emits_plan_from_balanced_lines(tmp_path: Path) -> None:
    """Render keeps projected_costs.breakdown empty; service items come from the
    balanced (right-sized) scenario lines, summed per label, with unpriced and zero
    lines left out so the list reconciles to the known-cost figure."""
    plan, platform, scope = _build(_render_run(tmp_path), _writer_with_render_enabled())
    assert (platform, scope) == ("RENDER", "INFRA_ONLY")
    assert plan["sourcePlatform"] == "RENDER"
    assert plan["scope"] == "INFRA_ONLY"
    assert plan["runId"] == RENDER_RUN_ID
    assert plan["cost"]["awsMonthly"] == 313.5
    assert plan["cost"]["awsMonthlyBasis"] == "BALANCED"
    assert plan["cost"]["sourceMonthly"] == 123.45
    assert "accuracy" not in plan["cost"]
    items = plan["cost"]["awsServiceItems"]
    names = [item["serviceName"] for item in items]
    assert len(names) == len(set(names))
    assert next(i for i in items if i["serviceName"] == "Amazon EFS")["monthlyCost"] == 1.5
    assert "AWS Certificate Manager + external DNS" not in names
    assert next(i for i in items if i["serviceName"] == "ECS on Fargate")["monthlyCost"] == 75.0
    assert round(sum(item["monthlyCost"] for item in items), 2) == 313.5
    assert {item["classification"] for item in items} == {"INFRASTRUCTURE"}


def test_render_source_baseline_requires_explicit_usd(tmp_path: Path) -> None:
    def drop_currency(estimate: dict) -> None:
        del estimate["current_costs"]["currency"]

    def euro(estimate: dict) -> None:
        estimate["current_costs"]["currency"] = "EUR"

    def unavailable(estimate: dict) -> None:
        estimate["current_costs"] = {"source": "unavailable", "render_monthly": None, "breakdown": {}}

    for index, mutate in enumerate((drop_currency, euro, unavailable)):
        plan, _, _ = _build(_render_run(tmp_path, mutate, name=f"baseline-{index}"), _writer_with_render_enabled())
        assert "sourceMonthly" not in plan["cost"]
        assert plan["cost"]["awsMonthly"] == 313.5


def test_render_service_items_omitted_when_lines_do_not_reconcile(tmp_path: Path) -> None:
    def drift(estimate: dict) -> None:
        estimate["scenarios"]["balanced"]["known_cost_monthly_usd"] = 999.0

    plan, _, _ = _build(_render_run(tmp_path, drift), _writer_with_render_enabled())
    assert "awsServiceItems" not in plan["cost"]
    assert plan["cost"]["awsMonthly"] == 313.5


def test_render_ai_estimate_fails_open_without_plan(tmp_path: Path) -> None:
    """Render defers AI, so a run that also carries an AI estimate would be FULL, which
    the import does not accept for RENDER; the writer must skip rather than emit it.
    The estimate here carries an accuracy band, so the FULL accuracy check would pass:
    only the RENDER scope table stops it."""
    run = _render_run(tmp_path, lambda estimate: estimate.__setitem__("accuracy_confidence", "+/-30%"))
    (run / "estimation-ai.json").write_text(
        json.dumps({"accuracy_confidence": "+/-30%", "cost_comparison": {"projected_bedrock_monthly": 50}})
    )
    module = _writer_with_render_enabled()
    try:
        _build(run, module)
    except module.SkipEmit as skip:
        assert "RENDER + FULL is not an importable combination" in str(skip), str(skip)
    else:
        raise AssertionError("a Render run with an AI estimate must not produce a plan")
    # And through the CLI, as shipped (gated), a stale plan.json is removed and nothing is written.
    (run / "plan.json").write_text("{}")
    result = subprocess.run(
        [sys.executable, str(WRITER), "--migration-dir", str(run)], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout.startswith("PLAN_SKIP"), result.stdout
    assert not (run / "plan.json").exists()


def test_render_missing_estimate_fails_open(tmp_path: Path) -> None:
    run = _render_run(tmp_path)
    (run / "estimation-infra.json").unlink()
    module = _writer_with_render_enabled()
    try:
        _build(run, module)
    except module.SkipEmit:
        pass
    else:
        raise AssertionError("a Render run with no estimate must not produce a plan")
    result = subprocess.run(
        [sys.executable, str(WRITER), "--migration-dir", str(run)], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert result.stdout.startswith("PLAN_SKIP"), result.stdout
    assert not (run / "plan.json").exists()


def test_render_version_two_keeps_the_version_one_service_items(tmp_path: Path) -> None:
    """Render's items come from scenario lines, not the breakdown the retained-input
    pointers select, so an opt-in version-2 export must carry the same list, without
    inputs, instead of an empty or different one."""
    module = _writer_with_render_enabled()
    run = _render_run(tmp_path)
    plugin_json = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    legacy = module.build_plan(run, plugin_json)[0]
    upgraded = module.build_plan(run, plugin_json, 2)[0]
    assert upgraded["schemaVersion"] == 2
    assert legacy["cost"]["awsServiceItems"]
    assert upgraded["cost"]["awsServiceItems"] == legacy["cost"]["awsServiceItems"]


def test_render_skill_writer_matches_plugin_copy() -> None:
    """render-to-aws runs the writer from its own scripts/ dir so a standalone skill
    install can emit the handoff; the copy must stay byte-identical to the plugin one."""
    skill_copy = PLUGIN_ROOT / "skills" / "render-to-aws" / "scripts" / "emit-plan-json.py"
    assert skill_copy.read_bytes() == WRITER.read_bytes(), (
        "render skill emit-plan-json.py has drifted from the plugin-level copy; "
        "re-copy plugins/aws-startup-advisor/scripts/emit-plan-json.py"
    )


def test_infra_row_sources_survive_duplicate_labels_and_filtered_rows() -> None:
    """Display labels cannot bind context to a cost row. Preserve the source key
    and the selected amount, without substituting a cheaper alternative."""
    module = _load_writer_module()
    projected = {"breakdown": {
        "total": 30,
        "run:web": {"service": "ECS Fargate", "monthly": 10, "mid": 1},
        "excluded": {"monthly": 70, "excluded_from_total": True},
        "run:worker": {"service": "ECS Fargate", "mid": 20},
        "invalid_primary": {"monthly": None, "mid": 99},
        "free_control": 0,
    }}
    original = json.loads(json.dumps(projected))
    rows = module._service_rows(projected)
    assert [(key, field) for key, field, _ in rows] == [
        ("run:web", "monthly"), ("run:worker", "mid"), ("free_control", None),
    ]
    assert [item["monthlyCost"] for _, _, item in rows] == [10, 20, 0]
    assert [item["serviceName"] for _, _, item in rows] == [
        "ECS Fargate", "ECS Fargate", "free_control",
    ]
    assert module._service_items(projected) == [item for _, _, item in rows]
    assert projected == original


def test_billing_row_sources_keep_original_indices() -> None:
    """Filtering must not shift source indices or collapse duplicate targets."""
    module = _load_writer_module()
    projection = {"services": [
        {"aws_target": "Total", "aws_mid": 40},
        {"aws_target": "Amazon S3", "aws_mid": 10, "unknowns": ["storage class"]},
        {"aws_target": "Amazon S3", "aws_mid": None},
        {"aws_target": "Amazon S3", "aws_mid": 30},
    ]}
    rows = module._billing_service_rows(projection)
    assert [index for index, _ in rows] == [1, 3]
    assert [item["monthlyCost"] for _, item in rows] == [10, 30]
    assert module._billing_service_items(projection) == [item for _, item in rows]
    assert all(set(item) == {"serviceName", "monthlyCost", "classification"} for _, item in rows)


def test_workshop_export_keeps_balanced_rows_without_inventing_context(tmp_path: Path) -> None:
    """Use the captured workshop amounts with synthetic valid run attribution.
    The optimized recommendation does not change the export's BALANCED basis."""
    golden = PLUGIN_ROOT / "fixtures" / "heroku-workshop" / "after-arm64-reprice"
    run = tmp_path / "run"
    shutil.copytree(golden, run)
    status_path = run / ".phase-status.json"
    status = json.loads(status_path.read_text())
    status.update(owning_skill="HEROKU_TO_AWS", run_id="8c1e4f2a-3b6d-4a7e-9f10-5d2c8b7a6e41")
    status_path.write_text(json.dumps(status))
    data = _emit(run)
    assert data["schemaVersion"] == 1
    assert data["cost"]["awsMonthlyBasis"] == "BALANCED"
    assert data["cost"]["awsMonthly"] == 88
    assert data["cost"]["awsServiceItems"] == [
        {"serviceName": "Elastic Beanstalk", "monthlyCost": 43, "classification": "INFRASTRUCTURE"},
        {"serviceName": "RDS PostgreSQL", "monthlyCost": 45, "classification": "INFRASTRUCTURE"},
    ]
    assert set(data["cost"]) == {"awsMonthly", "awsMonthlyBasis", "accuracy", "awsServiceItems"}
