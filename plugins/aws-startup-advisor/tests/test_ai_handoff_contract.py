"""Heroku and Render hand the shared AI profile to bedrock-migration-assessment.

Neither skill vendors the OpenAI-on-Bedrock guide or designs a Bedrock target.
"""

from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS = PLUGIN_ROOT / "skills"

HEROKU_DISCOVER = SKILLS / "heroku-to-aws/references/phases/discover/discover.md"
HEROKU_SKILL = SKILLS / "heroku-to-aws/SKILL.md"
RENDER_SKILL = SKILLS / "render-to-aws/SKILL.md"
RENDER_DISCOVER = SKILLS / "render-to-aws/references/phases/discover/discover.md"
RENDER_REPORT = SKILLS / "render-to-aws/references/phases/generate/generate-artifacts-report.md"
RENDER_DOCS = SKILLS / "render-to-aws/references/phases/generate/generate-artifacts-docs.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_heroku_discover_writes_the_shared_profile_and_does_not_design_it():
    text = _text(HEROKU_DISCOVER)
    assert "skills/bedrock-migration-assessment/references/phases/discover/discover-app-code.md" in text
    assert "ai-workload-profile.json" in text
    assert "skills/bedrock-migration-assessment/scripts/validate-ai-profile.py" in text
    assert "$PLUGIN_ROOT/" not in text
    assert '"status": "deferred_shared_ai_engine"' in text
    assert "Do not put this object in `.phase-status.json`" in text
    assert "openai-on-bedrock.md" not in text


def test_both_skills_start_the_assessment_on_the_profile_route():
    for path in (HEROKU_SKILL, RENDER_SKILL, RENDER_DISCOVER):
        text = _text(path)
        assert "skills/bedrock-migration-assessment/SKILL.md" in text or "follow the AI handoff" in text
        assert "profile route" in text or "follow the AI handoff" in text
        assert "future; not implemented" not in text
    for path in (HEROKU_SKILL, RENDER_SKILL):
        text = _text(path)
        assert "skills/bedrock-migration-assessment/SKILL.md" in text
        assert "profile route" in text
        assert "stops" in text


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
