"""The canonical report decision core (skills/shared/report/report-decision-core.md) is the
prose side of the contract that scripts/validate-migration-report.py enforces by machine.
The two drift independently unless something pins them together, so this file does:
- the canonical names every required section ID the validator demands in each mode and
  every `data-cost-key` anchor it looks for;
- each skill layer loads the vendored canonical first and names exactly one of the
  validator's `current_monthly` candidates (its own);
- neither the canonical nor any layer quotes a bare week range (the user's rule: timeline =
  shape + stage order + duration drivers), checked with the validator's own regex;
- the four vendored copies are byte-identical to the canonical and listed in each manifest;
- heroku's layer declares every `SKILL_PROFILES["heroku"]` exception, so no divergence is silent;
- the canonical names no skill directory or skill-local file (every skill stays self-contained).
"""
from __future__ import annotations

import filecmp
import importlib.util
import re
import subprocess  # nosec B404 — test-only, list args, no shell, committed script path
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "validate-migration-report.py"
SYNC = PLUGIN_ROOT / "tools" / "sync-vendored.py"
CANONICAL = PLUGIN_ROOT / "skills" / "shared" / "report" / "report-decision-core.md"
VENDORED_POINTER = "references/vendored/report/report-decision-core.md"
SKILLS = {
    "gcp-to-aws": "current_costs.gcp_monthly",
    "azure-to-aws": "current_costs.azure_monthly",
    "heroku-to-aws": "cost_comparison.heroku_monthly_baseline",
    "render-to-aws": "current_costs.render_monthly",
}
BARE_WEEK_RANGE = re.compile(r"\b\d+\s*(?:–|-|to)\s*\d+\+?\s*weeks\b", re.IGNORECASE)


def _load():
    spec = importlib.util.spec_from_file_location("validate_migration_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _layer(skill: str) -> Path:
    return PLUGIN_ROOT / "skills" / skill / "references" / "shared" / "report-decision-core.md"


def _vendored(skill: str) -> Path:
    return PLUGIN_ROOT / "skills" / skill / "references" / "vendored" / "report" / "report-decision-core.md"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def test_canonical_names_every_required_section_id_and_cost_anchor():
    module = _load()
    text = _read(CANONICAL)
    for sid in (
        list(module.REQUIRED_SECTION_IDS)
        + list(module.DECISION_REQUIRED_SECTION_IDS)
        + list(module.AI_ONLY_REQUIRED_SECTION_IDS)
    ):
        assert f"`{sid}`" in text, f"canonical does not name required section id `{sid}`"
    for key in module._COST_ANCHORS:
        assert f"`{key}`" in text, f"canonical does not name cost anchor `{key}`"
    assert "data-cost-key" in text


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_each_skill_layer_names_its_current_monthly_path(skill):
    module = _load()
    text = _read(_layer(skill))
    candidates = [".".join(path) for path in module._COST_ANCHORS["current_monthly"]]
    named = [c for c in candidates if f"`{c}`" in text]
    assert named == [SKILLS[skill]], f"{skill} layer names {named}, expected [{SKILLS[skill]!r}]"
    assert VENDORED_POINTER in text, f"{skill} layer does not load {VENDORED_POINTER}"


PARAMETER = re.compile(r"⟨[a-z_]+⟩")


@pytest.mark.parametrize("skill", sorted(SKILLS))
def test_each_skill_layer_supplies_every_canonical_parameter(skill):
    """Every `⟨parameter⟩` the canonical writes must appear in the layer (as a value,
    `n/a`, or a declared omission) — a parameter added to the canonical without a value
    in some layer is exactly the drift this file exists to catch."""
    canonical_params = set(PARAMETER.findall(_read(CANONICAL)))
    assert canonical_params, "canonical declares no ⟨parameter⟩ placeholders"
    layer_params = set(PARAMETER.findall(_read(_layer(skill))))
    missing = sorted(canonical_params - layer_params)
    assert not missing, f"{skill} layer does not supply: {missing}"
    unknown = sorted(layer_params - canonical_params)
    assert not unknown, f"{skill} layer supplies parameters the canonical never uses: {unknown}"


def test_no_bare_week_range_in_canonical_or_layers():
    module = _load()
    week_patterns = [p for p, label in module.READABILITY_PATTERNS if "bare week-range" in label]
    assert len(week_patterns) == 1, "validator no longer has exactly one bare week-range rule"
    validator_regex = re.compile(week_patterns[0], re.IGNORECASE)
    for path in [CANONICAL] + [_layer(s) for s in sorted(SKILLS)]:
        text = _read(path)
        assert validator_regex.search(text) is None, f"{path} quotes a bare week range"
        assert BARE_WEEK_RANGE.search(text) is None, f"{path} quotes a week range"


def test_vendored_copies_are_byte_identical():
    result = subprocess.run(  # nosec B603 — committed script, list args
        [sys.executable, str(SYNC), "--check"],
        capture_output=True,
        text=True,
        cwd=PLUGIN_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for skill in sorted(SKILLS):
        assert filecmp.cmp(_vendored(skill), CANONICAL, shallow=False), f"{skill} vendored copy differs"
        manifest = _read(PLUGIN_ROOT / "skills" / skill / "references" / "vendored" / "README.md")
        assert "`report/report-decision-core.md`" in manifest, f"{skill} manifest lacks the report row"


def test_heroku_layer_declares_every_profile_exception():
    module = _load()
    text = _read(_layer("heroku-to-aws"))
    profile = module.SKILL_PROFILES["heroku"]
    for key in list(profile["not_required"]) + list(profile["skip"]):
        assert f"`{key}`" in text, f"heroku layer does not declare profile exception `{key}`"
    assert "--profile heroku" in text


def test_canonical_names_no_skill_file():
    text = _read(CANONICAL)
    for token in (
        "gcp-to-aws/",
        "azure-to-aws/",
        "heroku-to-aws/",
        "render-to-aws/",
        "references/shared/",
        "design-refs/",
        "fixtures/",
    ):
        assert token not in text, f"canonical names a skill-local path: {token}"
