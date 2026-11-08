"""Guards for the PR 585 review-round-1 findings on the bedrock-runtime default.

Public basis (read 2026-11-07):
  https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html
  ("Permissions": a Responses request on bedrock-runtime authorizes bedrock:InvokeModel
  on the inference target AND on the account's default project)
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-sol.html
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-terra.html
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-luna.html
  (each: the identity "also needs bedrock:InvokeModel on your account's default project
  ... in addition to the inference profile" for its runtime CRIS ids)

1. Default-project grant: every setup recipe names the grant for EVERY runtime
   Responses / Chat Completions target, GPT-5.6 included, and cites the Responses page.
3. mantle_messages stop: llm-to-bedrock halts a `mantle_messages` plan at a lane gate
   before B4 / Phase C instead of labelling it Converse; GCP Generate's Step 0 matches
   `mantle_messages` in exactly one branch and keeps the supported `runtime_messages`
   route on Messages.
4. resolved_runtime_api: C0's current-context field list carries the field, the
   invalidation table has a row for it, B4 retains it on resume, and the actual
   comparator (`validate_result.compare_run_contexts`) matches an unchanged resume.

The id-form / API behaviour of the helpers themselves is tested next to them in
`skills/llm-to-bedrock/scripts/test_iam_policy.py` and `test_preflight_bedrock.py`.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
SKILL_MD = SKILLS / "llm-to-bedrock" / "SKILL.md"
SCRIPTS = SKILLS / "llm-to-bedrock" / "scripts"
GCP_GENERATE_ARTIFACTS = SKILLS / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md"
GCP_GENERATE_AI = SKILLS / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-ai.md"
AZURE_GENERATE_ARTIFACTS = SKILLS / "azure-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md"
REPORT_GENERATOR = PLUGIN_ROOT / "agents" / "llm2bedrock-report-generator.md"
CANONICAL_GUIDE = SKILLS / "shared" / "ai" / "ai-openai-to-bedrock.md"
VENDORED_GUIDES = [
    SKILLS / "gcp-to-aws" / "references" / "vendored" / "ai" / "ai-openai-to-bedrock.md",
    SKILLS / "azure-to-aws" / "references" / "vendored" / "ai" / "ai-openai-to-bedrock.md",
]
RESPONSES_PAGE = "https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html"


def _load(name: str):
    """Load a scripts-dir module by path. `validate_result` imports `jsonschema` for its
    payload validators; the comparator under test here is pure, so when the plugin test
    environment lacks jsonschema a stub stands in for the import only."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        sys.modules.setdefault("jsonschema", types.ModuleType("jsonschema"))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i: text.index(end, i)]


# --- Finding 1: the grant reaches every runtime Responses / Chat target, GPT-5.6 included ---

def test_setup_recipes_grant_project_default_to_every_runtime_openai_target() -> None:
    for path in (CANONICAL_GUIDE, GCP_GENERATE_AI, GCP_GENERATE_ARTIFACTS, AZURE_GENERATE_ARTIFACTS, REPORT_GENERATOR):
        text = path.read_text()
        windows = [text[max(0, m.start() - 900): m.end() + 900]
                   for m in re.finditer(r"project/default", text)]
        assert windows, f"{path}: no project/default grant sentence"
        joined = " ".join(" ".join(w.split()) for w in windows)
        assert "GPT-5.6" in joined, f"{path}: the default-project grant does not reach GPT-5.6"
        assert re.search(r"Responses\s*/\s*Chat Completions|responses.{0,12}chat_completions", joined), (
            f"{path}: the grant must be tied to the runtime Responses / Chat Completions path")
        assert RESPONSES_PAGE in joined, f"{path}: cite the public Responses API page"
        assert "2026-11-07" in joined, f"{path}: record the read date"
        # Not a GPT-6-only or GPT-6 + 5.4/5.5-only grant any more.
        assert not re.search(r"For (a )?GPT-6 CRIS( id)?, and for the GPT-5\.5 / GPT-5\.4 CRIS ids", text), path
        assert "GPT-6 / GPT-5.5 / GPT-5.4\n   also need" not in text, path


def test_vendored_openai_guides_match_canonical() -> None:
    for vendored in VENDORED_GUIDES:
        assert vendored.read_bytes() == CANONICAL_GUIDE.read_bytes(), vendored


# --- Finding 3: mantle_messages stops before B4 / Phase C; Step 0 branches are disjoint ---

def test_skill_has_a_lane_gate_before_b4_and_phase_c() -> None:
    text = SKILL_MD.read_text()
    b1 = _section(text, "### B1 — Read Assess outputs", "### B2 — AWS identity confirmation")
    assert "--check-lanes" in b1, "B1 must run preflight_bedrock.py --check-lanes"
    assert "unsupported_lane" in b1
    assert "mantle_messages" in b1 and "workspaces" in b1
    assert "Mantle Messages" in b1 and "deferred" in b1
    assert "runtime_messages" in b1, "the stop must point at the supported route"
    assert "Do NOT run B4" in b1 and "do NOT dispatch C1" in b1
    # The context rule no longer passes mantle_messages through as a Converse plan.
    context = _section(text, "### The context block", "### C0 — Run-context gate")
    assert "`mantle_messages` pass through `normalize_api_path` unchanged" not in context
    assert "mantle_messages` never reaches this" in context
    assert "must not be labelled" in context
    surface = next(line for line in context.splitlines() if line.startswith("Target API surface:"))
    assert "mantle_messages never reaches a dispatch" in surface


def test_iam_helper_refuses_mantle_messages_for_a_bare_claude_id() -> None:
    iam = _load("iam_policy")
    try:
        iam.generate_policy(["anthropic.claude-sonnet-5"], "us-east-1", "123456789012",
                            runtime_api="messages", migration_path="mantle_messages")
    except ValueError as e:
        assert "mantle_messages" in str(e) and "workspaces" in str(e)
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("generate_policy emitted runtime permissions for a mantle_messages plan")


def test_preflight_lane_gate_is_structured_and_names_lane_and_selector() -> None:
    preflight = _load("preflight_bedrock")
    stop = preflight.unsupported_lane_stop(
        [{"aws_model_id": "anthropic.claude-sonnet-5", "migration_path": "mantle_messages",
          "mantle_selector": "workspaces"}], "mantle_messages")
    assert stop["reason"] == "unsupported_lane"
    assert stop["lane"] == "mantle_messages" and stop["lane_status"] == "deferred"
    assert stop["mantle_selector"] == "workspaces"
    assert preflight.unsupported_lane_stop(
        [{"aws_model_id": "global.anthropic.claude-sonnet-5", "migration_path": "runtime_messages",
          "required_client_api": "messages"}], "runtime_messages") is None


def _step0_bullets(text: str) -> list[str]:
    step0 = text.split("## Step 0: Determine Artifact Path", 1)[1].split("## Step 1M:", 1)[0]
    return [line for line in step0.splitlines() if line.startswith("- ")]


def _bullet_matches(bullet: str, migration_path: str) -> bool:
    """Evaluate the Step 0 bullet heads the way an agent reads them: an exact-value
    bullet matches only its listed values; the `starts with "mantle"` bullet is scoped
    to the OpenAI-SDK spellings it enumerates."""
    head = bullet.split("→", 1)[0]
    excluded = set(re.findall(r'`"([a-z_\-]+)"` is NOT this branch', head))
    listed = set(re.findall(r'`"([a-z_\-]+)"`', head)) - excluded
    if "starts with" in head:
        return migration_path.startswith("mantle") and migration_path in listed
    if "or absent" in head:
        return migration_path in listed or migration_path == ""
    return migration_path in listed


def test_gcp_step0_matches_mantle_messages_in_exactly_one_branch() -> None:
    bullets = _step0_bullets(GCP_GENERATE_ARTIFACTS.read_text())
    matches = [b for b in bullets if _bullet_matches(b, "mantle_messages")]
    assert len(matches) == 1, [m[:120] for m in matches]
    branch = matches[0]
    assert '`migration_path` = `"mantle_messages"`' in branch
    assert "bedrock-mantle.{region}.api.aws/anthropic" in branch
    assert "`bedrock-mantle:*` IAM" in branch
    assert "Do NOT generate `migrate_to_mantle.sh`" in branch
    # The broad Mantle branch now enumerates the OpenAI-SDK spellings and excludes Messages.
    mantle_branch = next(b for b in bullets if 'starts with `"mantle"`' in b)
    assert '`"mantle_messages"` is NOT this branch' in mantle_branch
    for spelling in ("mantle", "mantle_openai_chat", "mantle_openai_responses"):
        assert [b for b in bullets if _bullet_matches(b, spelling)] == [mantle_branch], spelling


def test_gcp_step0_supported_runtime_messages_route_keeps_messages() -> None:
    bullets = _step0_bullets(GCP_GENERATE_ARTIFACTS.read_text())
    matches = [b for b in bullets if _bullet_matches(b, "runtime_messages")]
    assert len(matches) == 1
    branch = matches[0]
    assert "bedrock-runtime.{region}.amazonaws.com/anthropic" in branch
    assert '`required_client_api` is `"messages"`' in branch
    assert "do NOT rewrite to Converse" in branch
    assert "do NOT generate a Mantle script" in branch


# --- Finding 4: resolved_runtime_api survives the resume gate ---

def _c0_field_names(text: str) -> list[str]:
    c0 = _section(text, "### C0 — Run-context gate", "### C1 — Analyzer")
    template = re.search(r"```json\n(.*?)\n```", c0, re.S).group(1)
    return re.findall(r'^\s*"([a-z_]+)":', template, re.M)


def test_c0_context_schema_and_invalidation_table_carry_resolved_runtime_api() -> None:
    text = SKILL_MD.read_text()
    fields = _c0_field_names(text)
    assert "resolved_runtime_api" in fields, fields
    c0 = _section(text, "### C0 — Run-context gate", "### C1 — Analyzer")
    table = c0.split("| Mismatched field(s)")[1]
    row = next(line for line in table.splitlines() if line.startswith("| resolved_runtime_api"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1] == "EVAL, REWRITE, REPORT", row
    assert cells[2] == "ANALYSIS, INGESTION", row


def test_b4_resolves_the_api_once_and_reads_it_back_on_resume() -> None:
    text = SKILL_MD.read_text()
    b4 = _section(text, "### B4 — Bedrock preflight", "## Phase C — Execute")
    assert "$RESOLVED_RUNTIME_API" in b4
    assert "run-context.json" in b4 and "resolved_runtime_api" in b4
    assert "reuse it without" in b4 and "asking" in b4
    assert "--target <aws_model_id>=<that row's required_client_api>" in b4
    assert "unknown_runtime_api" in b4
    context = _section(text, "### The context block", "### C0 — Run-context gate")
    assert "`plan_runtime_api` is B4's `$RESOLVED_RUNTIME_API`" in context
    assert "written to current-context.json as\n`resolved_runtime_api`" in context


def _context_from_field_list(fields: list[str], resolved_runtime_api: str | None) -> dict:
    """Build a context with exactly C0's documented field list and plain fixture values."""
    ctx: dict = {}
    for name in fields:
        if name == "target_models":
            ctx[name] = [{"source_model": "gpt-5.5", "aws_model_id": "us.openai.gpt-5.5", "use_case": "chat"}]
        elif name in ("resolved_model_overrides",):
            ctx[name] = {}
        elif name == "log_files":
            ctx[name] = []
        elif name == "source_baseline_available":
            ctx[name] = False
        elif name in ("max_golden_cases", "schema_version", "evaluation_contract_version"):
            ctx[name] = 200 if name == "max_golden_cases" else 3 if name.startswith("evaluation") else 1
        elif name == "resolved_runtime_api":
            if resolved_runtime_api is not None:
                ctx[name] = resolved_runtime_api
        else:
            ctx[name] = f"fixture-{name}"
    return ctx


def test_actual_comparator_matches_an_unchanged_resume_with_resolved_runtime_api() -> None:
    validate = _load("validate_result")
    fields = _c0_field_names(SKILL_MD.read_text())
    saved = _context_from_field_list(fields, "chat_completions")
    current = _context_from_field_list(fields, "chat_completions")
    assert validate.compare_run_contexts(saved, current) == []


def test_actual_comparator_reproduces_the_reviewers_mismatch_when_the_field_is_dropped() -> None:
    # The finding: a current-context built from a field list that omits the saved answer
    # mismatches on $.resolved_runtime_api (saved="chat_completions" current="<absent>").
    validate = _load("validate_result")
    fields = _c0_field_names(SKILL_MD.read_text())
    saved = _context_from_field_list(fields, "chat_completions")
    current = _context_from_field_list(fields, None)
    lines = validate.compare_run_contexts(saved, current)
    assert lines == ['MISMATCH $.resolved_runtime_api saved="chat_completions" current="<absent>"']


def test_actual_comparator_flags_a_changed_api_for_scoped_invalidation() -> None:
    validate = _load("validate_result")
    fields = _c0_field_names(SKILL_MD.read_text())
    saved = _context_from_field_list(fields, "chat_completions")
    current = _context_from_field_list(fields, "responses")
    lines = validate.compare_run_contexts(saved, current)
    assert len(lines) == 1 and lines[0].startswith("MISMATCH $.resolved_runtime_api ")
    assert validate.top_key("$.resolved_runtime_api") == "resolved_runtime_api"
