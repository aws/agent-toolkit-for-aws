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

import json
import re
import subprocess
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

UPFRONT_NOTICE = PLUGIN_ROOT / "skills" / "shared" / "migration" / "upfront-credits.md"
LLM_SKILL = PLUGIN_ROOT / "skills" / "llm-to-bedrock" / "SKILL.md"
PLUGIN_README = PLUGIN_ROOT / "README.md"
UPFRONT_DISCOVER_FILES = {
    "gcp": PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "discover" / "discover.md",
    "heroku": PLUGIN_ROOT / "skills" / "heroku-to-aws" / "references" / "phases" / "discover" / "discover.md",
    "azure": PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "discover" / "discover.md",
}
AGENT_ADVISOR_MIGRATION_PLAN = (
    PLUGIN_ROOT / "skills" / "agent-advisor" / "references" / "phases"
    / "migration-plan" / "migration-plan.md"
)
APPROVED_CREDIT_COPY = (
    "Get $1,500 in AWS Promotional Credits for your migration when you create "
    "an assessment. Migrating a larger workload? You may be eligible for more. "
    "Talk to your AWS representative. Final eligibility determined by AWS."
)
SUPERSEDED_CREDIT_COPY = (
    "Complete your migration assessment to see whether you qualify for AWS "
    "migration credits.",
    "up to $1,500",
    "Credits are not guaranteed",
    "Qualification and credits are not guaranteed",
)


def test_migration_credit_notice_is_vendored_and_qualified() -> None:
    canonical = UPFRONT_NOTICE.read_bytes()
    text = canonical.decode()
    assert APPROVED_CREDIT_COPY in text
    assert all(unsupported not in text for unsupported in SUPERSEDED_CREDIT_COPY)
    assert "plan.json" in text and "migrate/credits" in text
    assert "Azure, GCP, or Heroku" in text
    assert "upload below" not in text.lower()
    for provider in UPFRONT_DISCOVER_FILES:
        vendored = (
            PLUGIN_ROOT / "skills" / f"{provider}-to-aws" / "references"
            / "vendored" / "migration" / "upfront-credits.md"
        )
        assert vendored.read_bytes() == canonical



def test_readme_uses_qualification_based_migration_credit_copy() -> None:
    text = PLUGIN_README.read_text(encoding="utf-8")

    assert text.count(APPROVED_CREDIT_COPY) == 1
    assert all(unsupported not in text for unsupported in SUPERSEDED_CREDIT_COPY)
    # Azure writes importable plans like GCP and Heroku: the importer accepts `AZURE`, and the writer maps
    # AZURE_TO_AWS to it for infrastructure or mixed runs. Only an AI-only run is skipped.
    assert "mixed Azure, GCP, or Heroku assessment" in text
    assert "Azure, GCP, and Heroku write importable plans" in text
    assert "importer's `AZURE` platform for infrastructure or mixed runs" in text
    assert "`PLAN_SKIP` (no file, migration unaffected) for an AI-only run" in text
    # the superseded claim that Azure is held back until the importer supports it must be gone
    assert "until the downstream importer accepts Azure plans" not in text
    assert "GCP and Heroku currently write importable plans" not in text


def test_llm_a1_preinitializes_provider_state_in_the_selected_directory() -> None:
    llm_text = LLM_SKILL.read_text(encoding="utf-8")
    a1 = llm_text[
        llm_text.index("### A1 — Run Discover, Clarify, Design, and Estimate"):
        llm_text.index("### A2 — Confirm Assess is complete")
    ]
    assert "Never create provider state in another path" in a1
    assert "`GCP_TO_AWS` or `AZURE_TO_AWS`" in a1
    assert "skip the provider's resume/Fresh prompt" in a1
    assert "`initiated_by` to `LLM_TO_BEDROCK`" in a1
    assert "genuinely unused" in a1
    # the LLM-only offer is gone until this flow can write plan.json
    assert "upfront-credits-llm" not in a1
    assert ".llm-upfront-credits-offered" not in llm_text
    assert "INVOCATION_ORIGIN" not in llm_text


def test_llm_flow_has_no_standalone_credit_notice_until_it_writes_plan_json() -> None:
    notice = "upfront-credits-llm.md"
    migration_dirs = (
        PLUGIN_ROOT / "skills" / "shared" / "migration",
        PLUGIN_ROOT / "skills" / "llm-to-bedrock" / "references" / "vendored" / "migration",
    )
    assert not any((d / notice).exists() for d in migration_dirs)
    assert notice not in PLUGIN_README.read_text(encoding="utf-8")


def test_migration_credit_notice_runs_once_at_fresh_discover_start() -> None:
    for provider, path in UPFRONT_DISCOVER_FILES.items():
        text = path.read_text(encoding="utf-8")
        notice_idx = text.index("references/vendored/migration/upfront-credits.md")
        assert "fresh run" in text[max(0, notice_idx - 250):notice_idx + 250].lower()
        assert "resum" in text[notice_idx:notice_idx + 500].lower()
        assert "render it later" in text[notice_idx:notice_idx + 600].lower()
        if provider == "gcp":
            initiated_by_write_idx = text.index("also set `initiated_by`")
            assert initiated_by_write_idx < notice_idx < text.index("## Step 1: Scan")
            assert "AI-only" in text[notice_idx:notice_idx + 600]
            assert "initiated_by: LLM_TO_BEDROCK" in text[notice_idx:notice_idx + 600]
        elif provider == "azure":
            window = text[notice_idx - 1200:notice_idx + 900]
            assert "LLM-preinitialized delegation" in window
            assert "schema-valid `.phase-status.json`" in window
            assert "do not\nrender the migration-credit notice" in window
            assert "direct AI-only" in text[notice_idx:notice_idx + 900]
            assert notice_idx < text.index("Discovery orientation", notice_idx)
            assert "records `initiated_by: \"LLM_TO_BEDROCK\"`" not in text
            assert "MUST include `initiated_by" not in text
        else:
            assert notice_idx < text.index("**When to offer capture:**", notice_idx)


def test_agent_advisor_delegation_uses_resume_routable_state(tmp_path: Path) -> None:
    advisor_text = AGENT_ADVISOR_MIGRATION_PLAN.read_text(encoding="utf-8")
    discover_text = UPFRONT_DISCOVER_FILES["gcp"].read_text(encoding="utf-8")
    step_one = advisor_text[
        advisor_text.index("## Step 1 — Resolve the target repo"):
        advisor_text.index("## Step 2 — Assemble the injection context")
    ]
    pointer_idx = step_one.index("Immediately read-merge-write agent-advisor's state")
    provider_idx = step_one.index("Then inspect `$MIGRATION_DIR/.phase-status.json`")
    envelope_start = advisor_text.index('"initiated_by": "AGENT_ADVISOR"')

    assert pointer_idx < provider_idx
    assert "reuse those exact paths on re-entry" in step_one
    assert "sole path selected on every re-entry" in step_one
    assert "collision-suffixed unused directory" in step_one
    assert "Reuse the envelope unchanged" in step_one
    assert "occupied-directory conflict" in step_one
    assert "otherwise empty" in step_one
    existing_branch = step_one[
        step_one.index("- If it exists"):
        step_one.index("- If it does not exist")
    ]
    no_state_branch = step_one[step_one.index("- If it does not exist"):]
    assert re.search(r"continue to\s+Step 2", existing_branch)
    assert "mint a fresh `run_id`" not in existing_branch
    assert "Only in this\n  no-state branch" in no_state_branch
    assert "mint a fresh `run_id`" in no_state_branch
    assert '{"initiated_by":"AGENT_ADVISOR"}' not in advisor_text
    assert envelope_start < advisor_text.index("### Phase A — Discover")
    for required in (
        '"migration_id": "[selected $MIGRATION_DIR directory name, including any collision suffix]"',
        '"run_id": "[fresh random UUID from uuidgen]"',
        '"owning_skill": "GCP_TO_AWS"',
        '"current_phase": "discover"',
        '"discover": "in_progress"',
    ):
        assert required in advisor_text
    assert "schema-valid `.phase-status.json`" in discover_text
    assert "normal Resume" in discover_text
    assert "do not recreate state" in discover_text
    assert "change its `migration_id`/`run_id`" in discover_text
    assert "preserve the existing `migration_plan_ctx` unchanged" in advisor_text

    repo = tmp_path / "repo"
    original_dir = repo / ".migration" / "0101-1200"
    original_dir.mkdir(parents=True)
    advisor_state = {
        "migration_plan_ctx": {
            "repo": str(repo.resolve()),
            "migration_dir": str(original_dir.resolve()),
        }
    }
    provider_state = {
        "migration_id": "0101-1200",
        "run_id": "11111111-2222-4333-8444-555555555555",
        "owning_skill": "GCP_TO_AWS",
        "initiated_by": "AGENT_ADVISOR",
        "last_updated": "2026-04-01T12:00:00Z",
        "current_phase": "design",
        "phases": {
            "discover": "completed",
            "clarify": "completed",
            "design": "in_progress",
            "estimate": "pending",
            "workshop": "pending",
            "generate": "pending",
            "feedback": "pending",
        },
    }
    advisor_path = tmp_path / "advisor-state.json"
    provider_path = original_dir / ".phase-status.json"
    advisor_path.write_text(json.dumps(advisor_state))
    provider_path.write_text(json.dumps(provider_state))

    def initialize_provider(selected: Path) -> dict[str, object]:
        state_path = selected / ".phase-status.json"
        if state_path.exists():
            return json.loads(state_path.read_text(encoding="utf-8"))
        fresh_state: dict[str, object] = {
            "migration_id": selected.name,
            "run_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "owning_skill": "GCP_TO_AWS",
            "initiated_by": "AGENT_ADVISOR",
            "last_updated": "2026-04-01T12:01:00Z",
            "current_phase": "discover",
            "phases": {
                "discover": "in_progress",
                "clarify": "pending",
                "design": "pending",
                "estimate": "pending",
                "workshop": "pending",
                "generate": "pending",
                "feedback": "pending",
            },
        }
        state_path.write_text(json.dumps(fresh_state), encoding="utf-8")
        return fresh_state

    original_bytes = provider_path.read_bytes()
    for derived_now in (
        repo / ".migration" / "0101-1200",
        repo / ".migration" / "0101-1201",
    ):
        persisted = json.loads(advisor_path.read_text())
        selected = Path(persisted["migration_plan_ctx"]["migration_dir"])
        resumed = initialize_provider(selected)
        assert selected == original_dir.resolve()
        assert selected != derived_now or derived_now == original_dir
        assert resumed["run_id"] == provider_state["run_id"]
        assert resumed["phases"] == provider_state["phases"]
        assert provider_path.read_bytes() == original_bytes

    unused_dir = repo / ".migration" / "0101-1201"
    unused_dir.mkdir()
    created = initialize_provider(unused_dir)
    assert created["run_id"] != provider_state["run_id"]
    assert created["current_phase"] == "discover"
    assert json.loads((unused_dir / ".phase-status.json").read_text()) == created


def test_azure_skill_describes_only_implemented_discovery_sources() -> None:
    text = (
        PLUGIN_ROOT / "skills" / "azure-to-aws" / "SKILL.md"
    ).read_text(encoding="utf-8")
    description = text.split("---", 2)[1]
    defaults = text[text.index("## Defaults"):text.index("## Scope Notes")]

    for section in (description, defaults):
        assert "Terraform" in section
        assert "consent-gated" in section
        assert "application code" in section
        assert "RDfA" in section
        assert "Billing exports, Bicep, and ARM" in section
        assert "not implemented" in section
        assert "user-stated" in section or "azure_monthly_spend" in section
    input_security = text[
        text.index("### Input Security"):text.index("## State Validation")
    ]
    assert "RDfA" in input_security
    assert "unsupported" in input_security
    assert "do not read, extract, or ingest them" in input_security
    assert "Bicep files or ARM templates are present" in input_security
    assert "halt per `discover-iac.md` Step 2" in input_security
    assert re.search(r"even\s+when supported sources are also present", input_security)
    assert "accompanies at least one supported source" in input_security
    assert "continue with the supported sources" in input_security
    assert "billing-export-only workspace" in input_security
    assert "halts at Discover's precondition" in input_security
    # RDfA is an implemented, supported source: it must never be grouped with the
    # unsupported-and-halting inputs (Bicep/ARM/billing exports).
    assert "RDfA report archive is the only source" not in input_security
    assert "RDfA archive or billing export" not in input_security

    iac_text = (
        PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases"
        / "discover" / "discover-iac.md"
    ).read_text(encoding="utf-8")
    assert "HALT if a dialect is present and its ref is not on disk" in iac_text
    assert "No dialect present\" is a clean exit" in iac_text

    for stale_claim in (
        "billing exports as a fallback",
        "Azure Cost Management exports",
        "Resource Discovery for Azure report archives",
        "RDfA, Bicep, and ARM templates are not implemented",
        "RDfA, Bicep, and ARM are not implemented",
        "fragment covers Terraform, Bicep, and ARM",
        "Azure invoice line items",
    ):
        assert stale_claim not in text


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
