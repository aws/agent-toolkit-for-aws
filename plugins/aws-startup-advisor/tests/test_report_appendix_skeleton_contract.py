"""The canonical report appendix skeleton (skills/shared/report/report-appendix-skeleton.md)
is the prose side of the appendix contract that scripts/validate-migration-report.py enforces
by machine, and the four report specs build their appendix block from it. This file pins
them together so they cannot drift independently:
- the skeleton's lettering table equals the decision core's (the validator encodes section
  IDs, not letters, so the decision core is the pinning source for labels);
- every appendix section ID the validator knows (default sets, every profile's required and
  not_required sets, the depth floors) is named in the skeleton and has a lettering row;
- every `⟨parameter⟩` the skeleton uses is listed in its "Skill spec must supply" table and
  supplied (value, `n/a`, or declared omission) by every report spec, which loads the
  vendored copy;
- neither the skeleton nor any spec quotes a bare week range (the user's rule: timeline =
  stage order + duration drivers), checked with the validator's own regex;
- the four vendored copies are byte-identical to the canonical and listed in each manifest;
- heroku's spec declares every `SKILL_PROFILES["heroku"]` appendix exception plus the
  undeclared `appendix-artifacts` omission, so no divergence is silent;
- the canonical names no skill directory, skill-local file or script (every skill stays
  self-contained).
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
CANONICAL = PLUGIN_ROOT / "skills" / "shared" / "report" / "report-appendix-skeleton.md"
CORE = PLUGIN_ROOT / "skills" / "shared" / "report" / "report-decision-core.md"
VENDORED_POINTER = "references/vendored/report/report-appendix-skeleton.md"
SPECS = {
    "gcp-to-aws": "references/phases/generate/generate-artifacts-report.md",
    "azure-to-aws": "references/phases/generate/generate-artifacts-report.md",
    "render-to-aws": "references/phases/generate/generate-artifacts-report.md",
    "heroku-to-aws": "references/phases/generate/generate-report.md",
}
BARE_WEEK_RANGE = re.compile(r"\b\d+\s*(?:–|-|to)\s*\d+\+?\s*weeks\b", re.IGNORECASE)
PARAM_RE = re.compile(r"⟨([a-z_]+)⟩")
# the intro sentence writes the literal glyph pair `⟨parameter⟩` to name the convention
PARAM_PLACEHOLDER = {"parameter"}
LETTERING_ROW_RE = re.compile(
    r"^\|\s*`(appendix-[a-z-]+)`\s*\|\s*(Appendix [A-J](?:\.1)? — [^|]+?)\s*\|", re.MULTILINE
)


def _load():
    spec = importlib.util.spec_from_file_location("validate_migration_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _spec(skill: str) -> Path:
    return PLUGIN_ROOT / "skills" / skill / SPECS[skill]


def _vendored(skill: str) -> Path:
    return PLUGIN_ROOT / "skills" / skill / "references" / "vendored" / "report" / "report-appendix-skeleton.md"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def _lettering(text: str) -> list[tuple[str, str]]:
    return [(sid, label.strip()) for sid, label in LETTERING_ROW_RE.findall(text)]


def _params(text: str) -> set[str]:
    return set(PARAM_RE.findall(text)) - PARAM_PLACEHOLDER


def test_lettering_table_matches_decision_core():
    skeleton = _lettering(_read(CANONICAL))
    core = _lettering(_read(CORE))
    assert skeleton, "skeleton has no lettering table"
    assert skeleton == core, f"skeleton lettering {skeleton} != decision core {core}"


def test_skeleton_names_every_appendix_id_the_validator_knows():
    module = _load()
    text = _read(CANONICAL)
    rows = {sid for sid, _ in _lettering(text)}
    ids = set(
        list(module.REQUIRED_SECTION_IDS)
        + list(module.AI_ONLY_REQUIRED_SECTION_IDS)
        + list(module.OPTIONAL_SECTION_IDS)
    )
    for profile in module.SKILL_PROFILES.values():
        for mode_ids in profile["required_sections"].values():
            ids.update(mode_ids)
        ids.update(profile["not_required"])
    for sid in sorted(sid for sid in ids if sid.startswith("appendix-")):
        assert f"`{sid}`" in text, f"skeleton does not name appendix id `{sid}`"
        assert sid in rows, f"skeleton lettering table has no row for `{sid}`"
    for sid in module.MIN_CONTENT_DEPTH:
        assert f"`{sid}`" in text, f"skeleton does not name depth-floor id `{sid}`"


def test_every_parameter_is_declared_in_the_supply_table():
    text = _read(CANONICAL)
    params = _params(text)
    assert params, "skeleton uses no ⟨parameter⟩"
    table = text.split("## Skill spec must supply", 1)[1].split("## Declared skill exceptions", 1)[0]
    missing = sorted(p for p in params if f"⟨{p}⟩" not in table)
    assert not missing, f"skeleton parameters not listed under 'Skill spec must supply': {missing}"


@pytest.mark.parametrize("skill", sorted(SPECS))
def test_every_parameter_is_supplied_by_each_spec(skill):
    params = _params(_read(CANONICAL))
    spec = _read(_spec(skill))
    assert VENDORED_POINTER in spec, f"{skill} spec does not load {VENDORED_POINTER}"
    missing = sorted(p for p in params if f"⟨{p}⟩" not in spec)
    assert not missing, f"{skill} spec does not supply (value, n/a, or declared omission): {missing}"


def test_no_bare_week_range_in_skeleton_or_specs():
    module = _load()
    week_patterns = [p for p, label in module.READABILITY_PATTERNS if "bare week-range" in label]
    assert len(week_patterns) == 1, "validator no longer has exactly one bare week-range rule"
    validator_regex = re.compile(week_patterns[0], re.IGNORECASE)
    for path in [CANONICAL] + [_spec(s) for s in sorted(SPECS)]:
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
    for skill in sorted(SPECS):
        assert filecmp.cmp(_vendored(skill), CANONICAL, shallow=False), f"{skill} vendored copy differs"
        manifest = _read(PLUGIN_ROOT / "skills" / skill / "references" / "vendored" / "README.md")
        assert "`report/report-appendix-skeleton.md`" in manifest, f"{skill} manifest lacks the skeleton row"


def test_heroku_spec_declares_every_profile_appendix_exception():
    module = _load()
    text = _read(_spec("heroku-to-aws"))
    block = text.split("### Appendices (full report only)", 1)[1].split("### Table & figure accessibility", 1)[0]
    profile = module.SKILL_PROFILES["heroku"]
    # appendix-artifacts is absent from heroku's full set but not yet in not_required: the spec
    # declares that omission so it is not silent until the validator row lands.
    for key in list(profile["not_required"]) + ["appendix-artifacts"]:
        assert f"`{key}`" in block, f"heroku spec's Appendices block does not declare `{key}`"
    assert "--profile heroku" in text


def test_skeleton_names_no_skill_file():
    text = _read(CANONICAL)
    for token in (
        "gcp-to-aws/",
        "azure-to-aws/",
        "heroku-to-aws/",
        "render-to-aws/",
        "references/shared/",
        "design-refs/",
        "fixtures/",
        "scripts/0",
        ".sh",
    ):
        assert token not in text, f"canonical names a skill-local path: {token}"
