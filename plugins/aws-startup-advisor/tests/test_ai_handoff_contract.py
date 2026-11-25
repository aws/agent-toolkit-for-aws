"""Heroku and Render hand the shared AI profile to bedrock-migration-assessment.

Neither skill vendors the OpenAI-on-Bedrock guide or designs a Bedrock target.
"""

from __future__ import annotations

import re

import importlib.util
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS = PLUGIN_ROOT / "skills"

HEROKU_DISCOVER = SKILLS / "heroku-to-aws/references/phases/discover/discover.md"
HEROKU_SKILL = SKILLS / "heroku-to-aws/SKILL.md"
RENDER_SKILL = SKILLS / "render-to-aws/SKILL.md"
RENDER_DISCOVER = SKILLS / "render-to-aws/references/phases/discover/discover.md"
RENDER_REPORT = SKILLS / "render-to-aws/references/phases/generate/generate-artifacts-report.md"
RENDER_DOCS = SKILLS / "render-to-aws/references/phases/generate/generate-artifacts-docs.md"


ASSESSMENT = "bedrock-migration-assessment"
PROFILE_FIXTURE = (
    PLUGIN_ROOT / "fixtures" / "ai-workload-profiles" / "ai-only-multi-direct" / "ai-workload-profile.json"
)
INTERPRETERS = [
    SKILLS / "shared/dsl/INTERPRETER.md",
    *(SKILLS / s / "references/vendored/dsl/INTERPRETER.md"
      for s in ("heroku-to-aws", "render-to-aws", "azure-to-aws", "agent-advisor")),
]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_heroku_discover_writes_the_shared_profile_and_does_not_design_it():
    text = _text(HEROKU_DISCOVER)
    assert f"<SKILL_BASE>/../{ASSESSMENT}/references/phases/discover/discover-app-code.md" in text
    assert "ai-workload-profile.json" in text
    assert f"<SKILL_BASE>/../{ASSESSMENT}/scripts/validate-ai-profile.py" in text
    # bare plugin-root paths only resolve from a full plugin checkout with that cwd
    assert "python3 skills/" not in text
    assert "$PLUGIN_ROOT/" not in text
    assert '"status": "deferred_shared_ai_engine"' in text
    assert "Do not put this object in `.phase-status.json`" in text
    assert "openai-on-bedrock.md" not in text


def _validator_command(text: str) -> str:
    block = re.search(r"```bash\n\s*(PROFILE=.*?)```", text, re.S)
    assert block, "the profile validation command is missing"
    return block.group(1)


def _run_validator_as_written(skill_base: Path, project: Path) -> subprocess.CompletedProcess:
    run = project / ".migration" / "0101-1200"
    run.mkdir(parents=True)
    shutil.copy2(PROFILE_FIXTURE, run / "ai-workload-profile.json")
    command = _validator_command(_text(HEROKU_DISCOVER)).replace("<SKILL_BASE>", str(skill_base))
    return subprocess.run(
        ["bash", "-c", command],
        cwd=project,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "MIGRATION_DIR": ".migration/0101-1200"},
        capture_output=True,
        text=True,
    )


def test_heroku_validator_command_accepts_a_valid_profile_from_the_users_project(tmp_path):
    result = _run_validator_as_written(SKILLS / "heroku-to-aws", tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["ok"] is True


def test_heroku_gamma_package_ships_the_assessment_and_the_command_runs_there(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "build_gamma_skillset", PLUGIN_ROOT / "scripts" / "build-gamma-skillset.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    assert ASSESSMENT in builder.dependency_closure("heroku-to-aws")
    archive = tmp_path / "heroku.zip"
    builder.build_archive(PLUGIN_ROOT, "heroku-to-aws", archive)
    package = tmp_path / "package"
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(package)
    skill_base = package / "skills" / "heroku-to-aws"
    for relative in (
        "SKILL.md",
        "scripts/validate-ai-profile.py",
        "references/phases/discover/discover-app-code.md",
    ):
        assert (skill_base / ".." / ASSESSMENT / relative).is_file(), relative
    result = _run_validator_as_written(skill_base, tmp_path / "project")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["ok"] is True


def test_both_skills_skip_the_assessment_when_it_is_not_installed():
    discover = _text(HEROKU_DISCOVER)
    assert f"<SKILL_BASE>/../{ASSESSMENT}/SKILL.md` does not exist" in discover
    assert "were not scanned because the bedrock-migration-assessment skill is not installed" in discover
    for path in (HEROKU_SKILL, RENDER_SKILL):
        text = _text(path)
        assert f"<SKILL_BASE>/../{ASSESSMENT}/SKILL.md` does not exist" in text
        assert "not installed" in text


def test_both_skills_start_the_assessment_on_the_profile_route():
    for path in (HEROKU_SKILL, RENDER_SKILL):
        text = _text(path)
        assert f"<SKILL_BASE>/../{ASSESSMENT}/SKILL.md" in text
        assert "profile route" in text
        assert "stops" in text
        assert "future; not implemented" not in text
        assert "load Clarify with this skill's own `$MIGRATION_DIR`, never the `bma-` directory" in text
    text = _text(RENDER_DISCOVER)
    assert "follow the AI handoff" in text
    assert "future; not implemented" not in text


def test_bma_run_directories_do_not_trip_the_single_run_check():
    for path in INTERPRETERS:
        text = _text(path)
        assert "`bma-[MMDD-HHMM]` directory under the run root belongs to `bedrock-migration-assessment`" in text, path
        assert "not counting `bma-`" in text, path
        assert "\"Resume latest\" never selects a `bma-` directory" in text, path
    for path in (HEROKU_SKILL, RENDER_SKILL):
        text = _text(path)
        assert "Resume latest never selects it" in text


def test_handoff_state_is_tied_to_the_current_profile():
    for path in (HEROKU_SKILL, RENDER_SKILL):
        text = _text(path)
        assert "ai-handoff.json" in text
        assert "`profile_digest`" in text and "\"assessment_dir\"" in text
        for status in ("in_progress", "assessment_completed", "skipped"):
            assert f"`{status}`" in text, (path, status)
        assert "every later resume at Clarify" in text
        assert "Ask the user to resume it or skip it for now" in text
        assert "does not exist" in text and "delete `$MIGRATION_DIR/ai-handoff.json`" in text
    discover = _text(HEROKU_DISCOVER)
    assert "delete any `ai-workload-profile.json` and `ai-track.json` that an earlier Discover run left" in discover
    assert "a re-run that finds no AI leaves neither file" in discover


def test_render_no_longer_calls_the_handoff_future_work():
    report = _text(RENDER_REPORT)
    docs = _text(RENDER_DOCS)
    assert "future; not implemented" not in report
    assert "future work" not in docs
    assert "starts `bedrock-migration-assessment`" in report
    assert "starts `bedrock-migration-assessment`" in docs
    assert "No AI target, cost, model, adapter, or Terraform may appear" in report


def test_neither_skill_vendors_the_openai_guide():
    for skill in ("heroku-to-aws", "render-to-aws"):
        vendored = SKILLS / skill / "references/vendored"
        readmes = list(vendored.rglob("README.md"))
        assert readmes, skill
        for readme in readmes:
            assert "openai-on-bedrock.md" not in readme.read_text(encoding="utf-8")
        assert not (vendored / "ai/openai-on-bedrock.md").exists()


def test_handoff_completes_on_the_estimate_summary_not_on_design():
    # bedrock-migration-assessment runs Clarify, Design and Estimate and stops after Estimate
    # (its Step 4 offers opt-in Generate; a host skill answers no). Marking the handoff done
    # on the Design summary would let a session interrupted during Estimate skip the resume.
    for path in (HEROKU_SKILL, RENDER_SKILL):
        text = _text(path)
        assert "runs Clarify, Design and Estimate and stops" in text, path
        assert "When it asks whether to generate the migration artifacts, answer no" in text, path
        assert "Clarify and Design and stops" not in text, path
        assert "When its Estimate summary has been shown, set `status` to `assessment_completed`" in text, path
        assert "design_completed" not in text, path
        assert "Design summary has been shown" not in text, path
    for path in (RENDER_DOCS, RENDER_REPORT):
        text = _text(path)
        assert "estimates its cost, then stops before generate" in text, path
        assert "stops before estimate and generate" not in text, path
    skill = _text(SKILLS / ASSESSMENT / "SKILL.md")
    assert "When another skill invoked this one only for Design or Estimate, it answers no." in skill
