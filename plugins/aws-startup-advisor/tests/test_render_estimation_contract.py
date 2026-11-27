"""Generate pre-check contract for render-to-aws estimation-infra.json.

An estimate written before the tier semantics (scenarios.capacity_preserving / right_sized,
delta_monthly_usd, no scenarios.balanced / like_for_like / rightsizing_delta) must fail the
Generate pre-check before the worker is dispatched, with the missing keys named.
"""
from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed local validator
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = PLUGIN_ROOT / "skills/render-to-aws"
EXPECTED = SKILL_ROOT / "fixtures/expected"
VALIDATOR = PLUGIN_ROOT / "scripts/validate-artifacts.py"
RENDER_SCHEMA = SKILL_ROOT / "references/shared/schema-render-estimation-infra.json"
SHARED_SCHEMA = PLUGIN_ROOT / "skills/shared/estimate/estimation-infra.schema.json"


def _precheck(run_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        [sys.executable, str(VALIDATOR), "--run-dir", str(run_dir), "--skill", "render-to-aws"],
        capture_output=True, text=True, cwd=PLUGIN_ROOT, check=False,
    )


def _run_dir(tmp_path: Path, estimate: dict) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    (run / "estimation-infra.json").write_text(json.dumps(estimate), encoding="utf-8")
    return run


def _current() -> dict:
    return json.loads((EXPECTED / "estimation-infra.json").read_text(encoding="utf-8"))


def test_current_fixture_estimate_passes_the_generate_precheck(tmp_path: Path) -> None:
    result = _precheck(_run_dir(tmp_path, _current()))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_pre_tier_semantics_estimate_fails_the_precheck_naming_the_missing_keys(tmp_path: Path) -> None:
    old = _current()
    scenarios = old["scenarios"]
    old["scenarios"] = {"capacity_preserving": scenarios["like_for_like"], "right_sized": scenarios["balanced"]}
    del old["rightsizing_delta"]
    old["delta_monthly_usd"] = 52.0
    result = _precheck(_run_dir(tmp_path, old))
    assert result.returncode == 1, result.stdout + result.stderr
    for key in ("scenarios.premium", "scenarios.balanced", "scenarios.optimized", "scenarios.like_for_like", "rightsizing_delta"):
        assert f":: {key}" in result.stdout, (key, result.stdout)
    assert "schema-render-estimation-infra.json" in result.stdout


def test_precheck_rejects_an_estimate_missing_only_the_comparison_block(tmp_path: Path) -> None:
    estimate = _current()
    del estimate["scenarios"]["like_for_like"]
    result = _precheck(_run_dir(tmp_path, estimate))
    assert result.returncode == 1, result.stdout
    assert ":: scenarios.like_for_like" in result.stdout


def test_render_schema_keeps_every_shared_constraint_and_only_adds_the_tier_keys() -> None:
    render = json.loads(RENDER_SCHEMA.read_text(encoding="utf-8"))
    shared = json.loads(SHARED_SCHEMA.read_text(encoding="utf-8"))
    assert set(render["required"]) == set(shared["required"]) | {"scenarios", "rightsizing_delta"}
    assert set(render["properties"]) == set(shared["properties"]) | {"scenarios", "rightsizing_delta"}
    for name, spec in shared["properties"].items():
        assert render["properties"][name] == spec, name
    assert render["properties"]["scenarios"]["required"] == ["premium", "balanced", "optimized", "like_for_like"]


def test_manifest_points_render_estimation_infra_at_the_render_schema() -> None:
    manifest = json.loads((PLUGIN_ROOT / "scripts/artifact-contracts.json").read_text(encoding="utf-8"))
    spec = manifest["skills"]["render-to-aws"]["estimation-infra.json"]
    assert spec["json_schema"] == "skills/render-to-aws/references/shared/schema-render-estimation-infra.json"


def test_generate_md_tells_the_user_to_rerun_design_and_estimate() -> None:
    text = (SKILL_ROOT / "references/phases/generate/generate.md").read_text(encoding="utf-8")
    section = text.split("## Main-window artifact pre-check")[1].split("## Worker sequence")[0]
    for needle in ("scenarios.like_for_like", "rightsizing_delta", "re-run Design and then Estimate", "capacity_preserving"):
        assert needle in section, needle
