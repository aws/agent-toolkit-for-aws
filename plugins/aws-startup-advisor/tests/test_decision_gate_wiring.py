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
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "estimate" / "estimate.md",
    PLUGIN_ROOT / "skills" / "heroku-to-aws" / "references" / "phases" / "estimate" / "estimate-assemble.md",
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "generate" / "generate.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "generate" / "generate.md",
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
        assert "migrate/plans/import" in text, (
            f"{f.name}: handoff exit no longer presents the web-import CTA"
        )


def test_estimate_exports_only_after_postconditions() -> None:
    """Estimate's plan.json export + CTA must run after _postconditions/HANDOFF_OK,
    matching Generate's ordering (PR #435 review, databaseId 4240400327)."""
    text = (
        PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "estimate" / "estimate.md"
    ).read_text(encoding="utf-8")
    postconditions_idx = text.find("Evaluate `_postconditions`")
    writer_idx = text.find("emit-plan-json.py")
    assert postconditions_idx != -1 and writer_idx != -1
    assert writer_idx > postconditions_idx, (
        "emit-plan-json.py is invoked before _postconditions is evaluated in estimate.md's "
        "Run the phase step"
    )
    assert re.search(r"only after[^\n]{0,40}HANDOFF_OK", text), (
        "estimate.md's writer invocation is not explicitly gated on HANDOFF_OK, matching generate.md"
    )
    # Step 3a in estimate-assemble.md must no longer invoke the writer directly.
    assemble_text = (
        PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "estimate" / "estimate-assemble.md"
    ).read_text(encoding="utf-8")
    assert "emit-plan-json.py" not in assemble_text, (
        "estimate-assemble.md still invokes the writer directly; it must move to estimate.md, "
        "after _postconditions"
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


IMPORT_PAGE = "https://startups.aws.com/migrate/plans/import"
TRACKED_LINK = IMPORT_PAGE + "?source=plugin&run=<run_id>"
RULE_TEXT = "Never name AWS Startup Advisor's import page without its address"


def _flat(text: str) -> str:
    """Join wrapped lines (and drop blockquote markers) so a name and its address split
    across a line break still count as adjacent."""
    return " ".join(line.lstrip().lstrip(">").strip() for line in text.splitlines())


def test_every_user_facing_mention_carries_the_import_page_address() -> None:
    # A user run on 2026-11-16: the agent condensed the What's next block and the user got
    # "upload plan.json to AWS Startups Migrate" with no URL and no idea what the site is.
    # Every place the product name reaches the user now carries the import page's address
    # within a few characters, so a paraphrase keeps it.
    for f in HANDOFF_FILES:
        text = _flat(f.read_text(encoding="utf-8"))
        assert "Startups Migrate" not in text, f"{f.name}: the product is AWS Startup Advisor"
        rule_spans = [(m.start(), m.end()) for m in re.finditer(re.escape(RULE_TEXT), text)]
        user_facing = [m.start() for m in re.finditer(r"AWS Startup Advisor", text)
                       if not any(a <= m.start() < b for a, b in rule_spans)]
        assert user_facing, f"{f.name}: no user-facing AWS Startup Advisor mention found"
        for start in user_facing:
            window = text[start:start + 80]
            assert IMPORT_PAGE in window, f"{f.name}: names the product without its address: {window}"
        assert RULE_TEXT in text, f.name


def test_both_links_carry_the_run_for_attribution() -> None:
    for f in HANDOFF_FILES:
        text = f.read_text(encoding="utf-8")
        assert text.count(TRACKED_LINK) == 2, f"{f.name}: expected the bullet link and the CTA link"
        bullet = next(line for line in text.splitlines()
                      if "upload plan.json to see the AWS migration credits" in line)
        assert f"[AWS Startup Advisor]({TRACKED_LINK})" in bullet, f.name
        assert "AWS Builder ID" in bullet and "where you import your migration plan" in bullet, f.name
        assert f"[Go to AWS Startup Advisor →]({TRACKED_LINK})" in text, f.name


def test_no_stale_not_live_ship_note() -> None:
    # The import page is live (checked 2026-11-16). A note saying it is not could lead an
    # agent to drop the What's next block.
    for f in HANDOFF_FILES:
        assert "reaches customers only after the import page" not in f.read_text(encoding="utf-8"), f.name


def test_the_address_rule_comes_before_the_verbatim_instruction() -> None:
    # Review on #676: the last instruction before the What's next block must stay the
    # verbatim one, so "if you shorten or restate" cannot read as permission to paraphrase.
    for f in HANDOFF_FILES:
        text = _flat(f.read_text(encoding="utf-8"))
        rule = text.index(RULE_TEXT)
        verbatim = text.index("Do not reword it", rule)
        block = text.index("**💬 What's next**", verbatim)
        assert rule < verbatim < block, f.name
        assert RULE_TEXT not in text[verbatim:block], f.name
