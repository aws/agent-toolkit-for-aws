"""Guards for the PR 585 review-round-2 findings (head f3c01556).

Public basis (read 2026-11-08):
  https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html
  ("Permissions": creating a response authorizes bedrock:InvokeModel on the inference
  target AND the default project; retrieving, canceling and deleting a stored response
  authorize bedrock:GetInvoke / CancelInvoke / DeleteInvoke on the project)

1. Report §6.4 IAM recipe: the `--target` ids come from the VALIDATED analysis mapping
   (C4 `resolved_model_overrides` applied), not from aws-design-ai.json's original rows —
   a Sol → Terra change in C4 must yield a C6 policy naming Terra and not Sol.
2. Retained stored-response reads: analyzer records `stored_response_ops`, the recipe
   carries them to `iam_policy.py --stored-response-ops`, the GCP / Azure setup and the
   shared OpenAI guide name the project-scoped GetInvoke grant, and the report checklist
   has a create-plus-retrieve check. Converse / Messages never get the grant.
3. B4 resume: the saved `resolved_runtime_api` is reused only after the saved design /
   source / target identity is checked (`preflight_bedrock.py --resume-runtime-api`).

Helper behaviour is tested next to the helpers in
`skills/llm-to-bedrock/scripts/test_iam_policy_round2.py` and
`test_preflight_resume_runtime_api.py`; this file covers the prose contracts and the
end-to-end C4-change → C6-policy regression through the documented recipe.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
SKILL_MD = SKILLS / "llm-to-bedrock" / "SKILL.md"
SCRIPTS = SKILLS / "llm-to-bedrock" / "scripts"
ANALYZER = PLUGIN_ROOT / "agents" / "llm2bedrock-code-analyzer.md"
REPORT_GENERATOR = PLUGIN_ROOT / "agents" / "llm2bedrock-report-generator.md"
ANALYSIS_SCHEMA = SCRIPTS / "schemas" / "analysis.json"
GCP_GENERATE_ARTIFACTS = SKILLS / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md"
GCP_GENERATE_AI = SKILLS / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-ai.md"
AZURE_GENERATE_ARTIFACTS = SKILLS / "azure-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md"
CANONICAL_GUIDE = SKILLS / "shared" / "ai" / "ai-openai-to-bedrock.md"
VENDORED_GUIDES = [
    SKILLS / "gcp-to-aws" / "references" / "vendored" / "ai" / "ai-openai-to-bedrock.md",
    SKILLS / "azure-to-aws" / "references" / "vendored" / "ai" / "ai-openai-to-bedrock.md",
]
RESPONSES_PAGE = "https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html"


def _load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i: text.index(end, i)]


def _recipe() -> tuple[str, str]:
    raw = _section(REPORT_GENERATOR.read_text(), "# 6.4 Generate scoped IAM policy artifact", "# 7. Generate report")
    return " ".join(raw.split()), _section(raw, "```bash", "```\n")


# --- Finding 1: the recipe joins plan rows to the validated mapping, overrides applied ---

def test_report_recipe_sources_ids_from_the_validated_mapping_not_the_design_rows() -> None:
    recipe, code = _recipe()
    assert "--target <aws_model_id>=<that row's required_client_api>" in code
    assert "is the VALIDATED target id for that row, not the design row's own `aws_model_id`" in recipe
    assert "resolved_model_overrides" in recipe
    assert "keeps the ORIGINAL design id after the user changes a target in C4" in recipe
    assert "Sol → Terra change would grant `us.openai.gpt-5.6-sol` and omit the Terra profile" in recipe
    assert "validated `target_models`" in recipe and "FINAL validated id with every override applied" in recipe
    assert "iam_policy.validated_target_pairs(" in recipe
    assert "MUST equal the set on your context's `Target Bedrock model(s)` line" in recipe
    assert "never fall back to the row's original `aws_model_id`" in recipe
    # The inputs section names target_models as the join source.
    inputs = _section(REPORT_GENERATOR.read_text(), "# 3. Inputs from orchestrator", "# 4. Skills to load")
    assert "FINAL validated ids §6.4's IAM recipe joins the plan rows to" in inputs


def test_c4_target_change_flows_into_the_c6_policy_through_the_documented_recipe() -> None:
    """The reviewer's regression: C4 changes Sol → Terra. aws-design-ai.json still holds
    Sol; the validated analysis holds Terra. The recipe's helper must emit Terra's
    profile and the default-project grant, and no Sol permission at all."""
    iam = _load("iam_policy")
    design_rows = [{"source_model_id": "gpt-5.6-sol", "aws_model_id": "us.openai.gpt-5.6-sol",
                    "required_client_api": "responses", "migration_path": "runtime_openai_cris"}]
    # C4 recorded {"us.openai.gpt-5.6-sol": "us.openai.gpt-5.6-terra"}; C1 re-ran and validated:
    analysis_target_models = ["gpt-5.6-sol -> us.openai.gpt-5.6-terra"]
    pairs = iam.validated_target_pairs(design_rows, analysis_target_models,
                                       primary_model_id="us.openai.gpt-5.6-terra", primary_api="responses")
    assert pairs == [("us.openai.gpt-5.6-terra", "responses")]
    policy = iam.generate_policy([m for m, _ in pairs], "us-east-1", "123456789012",
                                 migration_path="runtime_openai_responses",
                                 target_apis=iam.target_apis_by_id(pairs))
    dumped = json.dumps(policy)
    assert "gpt-5.6-terra" in dumped and "gpt-5.6-sol" not in dumped
    invoke = {s["Sid"]: s for s in policy["Statement"]}["BedrockInvokeModelScoped"]["Resource"]
    assert iam.inference_profile_arn("us.openai.gpt-5.6-terra", "us-east-1", "123456789012") in invoke
    assert iam.default_project_arn("us-east-1", "123456789012") in invoke
    # Control: the pre-fix behaviour (re-reading the design row) is what emitted Sol.
    stale = iam.generate_policy([r["aws_model_id"] for r in design_rows], "us-east-1", "123456789012",
                                target_apis={"us.openai.gpt-5.6-sol": "responses"})
    assert "gpt-5.6-sol" in json.dumps(stale) and "gpt-5.6-terra" not in json.dumps(stale)


# --- Finding 2: retained stored-response ops → project-scoped GetInvoke, propagated everywhere ---

def test_analysis_schema_and_analyzer_carry_stored_response_ops() -> None:
    schema = json.loads(ANALYSIS_SCHEMA.read_text())
    payload = schema["oneOf"][0]
    prop = payload["properties"]["stored_response_ops"]
    assert "stored_response_ops" not in payload["required"], "optional: older analyses stay valid"
    assert prop["items"]["enum"] == ["retrieve", "cancel", "delete"]
    text = ANALYZER.read_text()
    scan = _section(text, "## 8.3 Detect special patterns", "# 9. Detect behavior deltas")
    assert "responses\\.retrieve(" in scan and "responses\\.cancel(" in scan and "responses\\.delete(" in scan
    joined = " ".join(scan.split())
    assert "`stored_response_ops`" in joined
    assert "bedrock:GetInvoke` / `bedrock:CancelInvoke` / `bedrock:DeleteInvoke` on the account's default project" in joined
    assert RESPONSES_PAGE in joined and "read 2026-11-08" in joined
    assert "Creation (`responses.create`) is NOT one of them" in joined
    assert "never emit it for a Chat Completions, Converse or Anthropic Messages source" in joined
    completion = _section(text, "# 14. Completion", "## Example result")
    assert "`stored_response_ops` (§8.3) is the one optional typed field" in completion


def test_report_recipe_carries_stored_response_ops_to_the_helper_with_controls() -> None:
    recipe, code = _recipe()
    assert "[--stored-response-ops <comma-joined analysis.stored_response_ops — omit when absent or empty>]" in code
    assert "Retained stored-response operations need their own grant" in recipe
    assert "`BedrockStoredResponseOps` statement" in recipe
    assert "`bedrock:GetInvoke` for `retrieve`, `bedrock:CancelInvoke` for `cancel`, `bedrock:DeleteInvoke` for `delete`" in recipe
    assert RESPONSES_PAGE in recipe and "read 2026-11-08" in recipe
    assert "creation and the preflight ping pass while the app's existing `responses.retrieve(id)` is denied" in recipe
    # Controls: only a runtime Responses row; Converse / Messages / Chat refused; absent → no flag.
    assert "only when a `--target` row is a runtime GPT CRIS id on `responses`" in recipe
    assert "`reason: stored_response_ops_no_responses_row` for a Converse / Anthropic Messages / Chat Completions plan" in recipe
    assert "When the field is absent or `[]`, omit the flag" in recipe


def test_report_checklist_has_a_create_plus_retrieve_permission_check() -> None:
    apply = _section(REPORT_GENERATOR.read_text(), "## How to Apply", "## How to Undo")
    joined = " ".join(apply.split())
    assert "Create-plus-retrieve permission check" in joined
    assert "Render ONLY when `analysis.stored_response_ops` is non-empty" in joined
    assert "client.responses.create(" in joined and "client.responses.retrieve(r.id)" in joined
    assert "the preflight ping only exercises creation" in joined
    assert "`BedrockStoredResponseOps` statement" in joined and "project/default" in joined


def test_setup_contracts_name_the_get_invoke_grant_and_its_controls() -> None:
    for path in (CANONICAL_GUIDE, GCP_GENERATE_AI, GCP_GENERATE_ARTIFACTS, AZURE_GENERATE_ARTIFACTS):
        text = " ".join(path.read_text().split())
        assert "bedrock:GetInvoke" in text, f"{path}: no GetInvoke grant"
        assert "client.responses.retrieve(id)" in text, path
        assert "iam_policy.py --stored-response-ops retrieve[,cancel,delete]" in text, path
        assert "read 2026-11-08" in text, f"{path}: record the read date"
        # Only the retained ops; the grant stays on the default project ARN.
        assert re.search(r"only (for )?the (ops actually )?retained", text), path
        assert "project/default" in text, path
        # Converse / Messages control.
        assert re.search(r"`converse`(,| /) `messages`", text), f"{path}: converse / messages must be excluded"
    # Setup verification does create-plus-retrieve.
    for path in (GCP_GENERATE_ARTIFACTS, AZURE_GENERATE_ARTIFACTS, CANONICAL_GUIDE):
        text = " ".join(path.read_text().split())
        assert "client.responses.retrieve(r.id)" in text, f"{path}: no create-plus-retrieve verification"


def test_iam_helper_grants_get_invoke_for_responses_only_and_refuses_converse_and_messages() -> None:
    iam = _load("iam_policy")
    sol, claude, nova = "us.openai.gpt-5.6-sol", "global.anthropic.claude-sonnet-5", "us.amazon.nova-lite-v1:0"
    project = iam.default_project_arn("us-east-1", "123456789012")
    pol = iam.generate_policy([claude, sol], "us-east-1", "123456789012", migration_path="runtime_messages",
                              target_apis={claude: "messages", sol: "responses"}, stored_response_ops=["retrieve"])
    stmt = {s["Sid"]: s for s in pol["Statement"]}["BedrockStoredResponseOps"]
    assert stmt["Action"] == ["bedrock:GetInvoke"] and stmt["Resource"] == [project]
    for apis in ({claude: "messages"}, {nova: "converse"}, {sol: "converse"}, {sol: "chat_completions"}):
        try:
            iam.generate_policy(list(apis), "us-east-1", "123456789012", target_apis=apis,
                                stored_response_ops=["retrieve"])
        except ValueError as e:
            assert "stored-response ops" in str(e)
        else:  # pragma: no cover - the assertion above is the contract
            raise AssertionError(f"GetInvoke granted for {apis}")
    plain = iam.generate_policy([sol], "us-east-1", "123456789012", target_apis={sol: "responses"})
    assert "BedrockStoredResponseOps" not in [s["Sid"] for s in plain["Statement"]]


def test_vendored_openai_guides_match_canonical() -> None:
    for vendored in VENDORED_GUIDES:
        assert vendored.read_bytes() == CANONICAL_GUIDE.read_bytes(), vendored


# --- Finding 3: saved API reused only after the identity check ---

def test_b4_checks_saved_identity_before_reusing_the_answer() -> None:
    text = SKILL_MD.read_text()
    b4 = " ".join(_section(text, "### B4 — Bedrock preflight", "## Phase C — Execute").split())
    assert "check the saved answer's identity BEFORE reusing it" in b4
    assert "--resume-runtime-api $PHASE_DIR/run-context.json --design $MIGRATION_DIR/aws-design-ai.json" in b4
    assert "`reason: saved_identity_match`" in b4
    assert "saved `assess_design_sha256` equals the current design's sha256" in b4
    assert "saved `target_models`" in b4 and "equal the current `bedrock_models[]` rows" in b4
    assert "`saved_identity_mismatch`" in b4
    assert "do NOT read the saved value" in b4 and "before any probe" in b4
    assert "A cached `messages` answer must never send a new GPT row to the Anthropic endpoint" in b4
    assert "a stale `responses` answer must never override a Chat Completions source" in b4
    # The old unconditional reuse sentence is gone from both places that had it.
    assert "and reuse it without asking; otherwise AskUserQuestion" not in b4
    context = " ".join(_section(text, "### The context block", "### C0 — Run-context gate").split())
    assert "read `resolved_runtime_api` from run-context before asking again" not in context
    assert "only when B4's `--resume-runtime-api` gate reports `saved_identity_match`" in context


def test_actual_gate_forces_re_resolution_on_identity_mismatch_and_reuses_on_match() -> None:
    preflight = _load("preflight_bedrock")
    gpt_rows = [{"source_model_id": "gpt-5.6-sol", "aws_model_id": "us.openai.gpt-5.6-sol"}]
    saved = {"resolved_runtime_api": "messages", "assess_design_sha256": "a" * 64,
             "target_models": [{"source_model": "claude-sonnet-4-5",
                                "aws_model_id": "global.anthropic.claude-sonnet-5", "use_case": "chat"}]}
    # New GPT row under a changed design: the cached `messages` must not be reused.
    mismatch = preflight.resume_runtime_api(saved, "b" * 64, gpt_rows)
    assert mismatch["ok"] is False and mismatch["reason"] == "saved_identity_mismatch"
    assert "resolved_runtime_api" not in mismatch
    # Same design, same rows: reuse without re-asking.
    saved_gpt = {"resolved_runtime_api": "chat_completions", "assess_design_sha256": "a" * 64,
                 "target_models": [{"source_model": "gpt-5.6-sol", "aws_model_id": "us.openai.gpt-5.6-sol",
                                    "use_case": "chat"}]}
    match = preflight.resume_runtime_api(saved_gpt, "a" * 64, gpt_rows)
    assert match == {"ok": True, "reason": "saved_identity_match", "resolved_runtime_api": "chat_completions",
                     "detail": "Saved design, source and target identity match; reuse without asking."}
    # Only the design changed (stale `responses` over a Chat source): still re-resolve.
    stale = preflight.resume_runtime_api({**saved_gpt, "resolved_runtime_api": "responses"}, "c" * 64, gpt_rows)
    assert stale["reason"] == "saved_identity_mismatch"
