"""Guard: both handoff exits must wire the web-handoff.

The fixture asserters and test_emit_plan_json.py both cover the WRITER itself
(that a run's artifacts yield a valid plan.json). Nothing else guards that the
skill handlers actually invoke the writer and present the import CTA at the two
exits that reach a customer: the Estimate decision gate ("Done for now") and the
Generate completion. Without this, silently deleting those steps from the skill
markdown would leave the whole suite green. These checks anchor on stable
substrings (the script filename, the import-page path, and the writer's
PLAN_OK/PLAN_SKIP status tokens) so benign rewording does not trip them.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
# Every skill exit that must emit plan.json and present the web CTA.
HANDOFF_FILES = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "estimate" / "estimate.md",
    PLUGIN_ROOT / "skills" / "heroku-to-aws" / "references" / "phases" / "estimate" / "estimate-assemble.md",
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "generate" / "generate.md",
    PLUGIN_ROOT / "skills" / "heroku-to-aws" / "references" / "phases" / "generate" / "generate-assemble.md",
]


def test_handoff_exits_invoke_plan_writer() -> None:
    for f in HANDOFF_FILES:
        text = f.read_text(encoding="utf-8")
        assert "emit-plan-json.py" in text, (
            f"{f.name}: handoff exit no longer invokes the plan.json writer"
        )
        assert "--migration-dir" in text, (
            f"{f.name}: writer invocation is missing its --migration-dir argument"
        )


def test_handoff_exits_present_import_cta() -> None:
    for f in HANDOFF_FILES:
        text = f.read_text(encoding="utf-8")
        assert "migrate/credits" in text, (
            f"{f.name}: handoff exit no longer presents the web-import CTA"
        )


def test_handoff_exits_are_fail_open_gated() -> None:
    # The emit + CTA must stay fail-open: the writer's PLAN_OK / PLAN_SKIP status
    # tokens gate whether the CTA is shown. If a handler stops mentioning both,
    # the gating has been dropped (e.g. the CTA would show even without a file).
    for f in HANDOFF_FILES:
        text = f.read_text(encoding="utf-8")
        assert "PLAN_OK" in text and "PLAN_SKIP" in text, (
            f"{f.name}: handoff exit no longer gates the CTA on the writer's "
            f"PLAN_OK/PLAN_SKIP status (fail-open contract)"
        )
        # Beyond mere presence: the block must be *conditioned* on the status, so
        # prose that merely names the tokens while showing the CTA unconditionally
        # still fails. PLAN_OK gates presenting the block; PLAN_SKIP gates omitting it.
        assert re.search(r"only when[^\n]{0,40}PLAN_OK", text), (
            f"{f.name}: web-handoff block is no longer gated on PLAN_OK "
            f"(the CTA must be presented only when the writer prints PLAN_OK)"
        )
        assert re.search(r"PLAN_SKIP[^\n]{0,40}omit", text), (
            f"{f.name}: web-handoff block is no longer omitted on PLAN_SKIP"
        )
