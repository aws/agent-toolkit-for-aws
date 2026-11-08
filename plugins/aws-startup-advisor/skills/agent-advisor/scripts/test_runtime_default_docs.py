"""Doc lock for the bedrock-runtime default (PR 3 of the endpoint-policy stack).

The engines (anthropic_model_recommendation.py, openai_model_recommendation.py) default to
bedrock-runtime and select a Mantle path only with a recorded mantle_selector. These tests pin
the agent-advisor prose to that behavior: the Model Recommend questionnaire asks for the
selector and in-Region residency, the decision ref points at the vendored endpoint policy
instead of restating it, the advisor->migration translation emits PR 2's migration_path /
required_client_api / mantle_selector vocabulary for every new path, and the stale PR 1
disclosures about catalog-order fallbacks and unrecognized GPT-5.5/5.4 identities are gone.
Matching is whitespace-normalized (markdown wraps lines).
"""
import pathlib
import re

import pytest

SKILL = pathlib.Path(__file__).parent.parent
PLUGIN_SKILLS = SKILL.parent
MODEL_RECOMMEND_MD = SKILL / "references" / "phases" / "model-recommend" / "model-recommend.md"
MODEL_SELECTION_MD = SKILL / "references" / "decision-refs" / "model-selection.md"
MIGRATION_PLAN_MD = SKILL / "references" / "phases" / "migration-plan" / "migration-plan.md"
HANDOFF_MD = SKILL / "references" / "handoff" / "handoff-migration.md"
CONFIRM_MD = SKILL / "references" / "phases" / "confirm" / "confirm.md"
DESIGN_MD = SKILL / "references" / "phases" / "design" / "design.md"
POC_MD = SKILL / "references" / "phases" / "poc" / "poc.md"
SKILL_MD = SKILL / "SKILL.md"
GCP_DESIGN_AI_MD = PLUGIN_SKILLS / "gcp-to-aws" / "references" / "phases" / "design" / "design-ai.md"

POLICY_REF = "bedrock-endpoint-policy.md"
NEW_PATHS = ("runtime_openai_responses", "runtime_openai_chat", "runtime_messages")
STALE_PHRASES = (
    "deliberate consequence",
    "ordering limitation",
    "does not yet recognize",
    "currently reshaped to Responses",
)


def _norm(path):
    return re.sub(r"\s+", " ", path.read_text())


@pytest.mark.parametrize("path", [MODEL_RECOMMEND_MD, MODEL_SELECTION_MD])
def test_model_docs_reference_the_vendored_endpoint_policy(path):
    assert POLICY_REF in _norm(path), f"{path.name} must point at the vendored endpoint policy"


def test_model_recommend_asks_for_selector_and_in_region_residency():
    text = _norm(MODEL_RECOMMEND_MD)
    for needle in ("mantle_selector", "in_region_required", *NEW_PATHS):
        assert needle in text, f"model-recommend.md must name {needle}"
    frontmatter = text.split("---", 2)[1]
    assert "references/vendored/ai/bedrock-endpoint-policy.md" in frontmatter, \
        "model-recommend.md must load the vendored endpoint policy as knowledge"


@pytest.mark.parametrize("phrase", STALE_PHRASES)
def test_model_recommend_drops_pr1_fallback_disclosures(phrase):
    assert phrase not in _norm(MODEL_RECOMMEND_MD), \
        f"model-recommend.md still carries the stale disclosure {phrase!r}"


def test_model_selection_lists_the_runtime_paths_and_the_selector_rule():
    text = _norm(MODEL_SELECTION_MD)
    for needle in (*NEW_PATHS, "mantle_selector", "runtime_converse", "runtime_invoke",
                   "mantle_messages", "mantle_openai_chat", "mantle_openai_responses"):
        assert f"`{needle}`" in text, f"model-selection.md must list {needle}"
    assert "verified Mantle selector plus Converse-only governance" in text
    assert "API continuity plus runtime-only governance" not in text


@pytest.mark.parametrize("path", [MIGRATION_PLAN_MD, HANDOFF_MD, GCP_DESIGN_AI_MD])
def test_handoff_translation_names_every_new_path_and_the_selector(path):
    text = _norm(path)
    for needle in (*NEW_PATHS, "mantle_selector", "runtime_openai_cris", "required_client_api"):
        assert needle in text, f"{path.name} must translate {needle}"
    for api in ("responses", "chat_completions", "messages", "converse"):
        assert f"`{api}`" in text or f'"{api}"' in text, f"{path.name} must name required_client_api {api}"


def test_migration_plan_snippet_translates_runtime_and_mantle_paths():
    text = _norm(MIGRATION_PLAN_MD)
    assert "_RUNTIME_OPENAI" in text
    assert "_PROPRIETARY_GPT" in text
    for model in ("openai.gpt-6", "openai.gpt-5.6-", "openai.gpt-5.5", "openai.gpt-5.4"):
        assert f'"{model}"' in text, f"the proprietary GPT tuple must cover {model}"
    assert 'migration_path == "runtime_messages"' in text
    assert 'path.startswith("mantle_")' in text
    assert "mantle_selector == selector" in text
    assert "mantle_selector=None" in text


def _comparator():
    section = MIGRATION_PLAN_MD.read_text().split("### Step 3.5", 1)[1].split("### Phase D", 1)[0]
    code = re.search(r"```python\n(.*?)\n```", section, re.S).group(1)
    ns = {}
    exec(compile(code, str(MIGRATION_PLAN_MD), "exec"), ns)  # nosec B102 - committed handoff algorithm
    return ns["matches_advisor_model"]


@pytest.mark.parametrize("path,api,model,invocation", [
    ("runtime_openai_responses", "responses", "openai.gpt-5.4", "global.openai.gpt-5.4"),
    ("runtime_openai_chat", "chat_completions", "openai.gpt-5.5", "us.openai.gpt-5.5"),
    ("runtime_converse", "converse", "openai.gpt-5.4", "us.openai.gpt-5.4"),
    ("runtime_converse", "converse", "openai.gpt-6-astra", "global.openai.gpt-6-astra"),
])
def test_comparator_translates_runtime_openai_paths_to_runtime_openai_cris(path, api, model, invocation):
    matches = _comparator()
    advisor = {"model": model, "api_path": path, "invocation_model_id": invocation,
               "mantle_selector": None}
    assert matches(advisor, invocation, "runtime_openai_cris", api)
    other = {"responses", "chat_completions", "converse"} - {api}
    for wrong_api in other:
        assert not matches(advisor, invocation, "runtime_openai_cris", wrong_api)
    assert not matches(advisor, model, "runtime_openai_cris", api)  # bare id is not the CRIS id
    assert not matches(advisor, invocation, path, api)  # advisor path names are not GCP paths
    assert not matches({**advisor, "invocation_model_id": None}, invocation, "runtime_openai_cris", api)


def test_comparator_translates_runtime_messages():
    matches = _comparator()
    advisor = {"model": "anthropic.claude-sonnet-5", "api_path": "runtime_messages",
               "invocation_model_id": "global.anthropic.claude-sonnet-5", "mantle_selector": None}
    assert matches(advisor, "global.anthropic.claude-sonnet-5", "runtime_messages")
    assert matches(advisor, "global.anthropic.claude-sonnet-5", "runtime_messages", "messages")
    assert not matches(advisor, "global.anthropic.claude-sonnet-5", "runtime_messages", "converse")
    assert not matches(advisor, "anthropic.claude-sonnet-5", "runtime_messages", "messages")
    assert not matches(advisor, "global.anthropic.claude-sonnet-5", "converse", "converse")
    assert not matches({**advisor, "invocation_model_id": None},
                       "global.anthropic.claude-sonnet-5", "runtime_messages", "messages")


@pytest.mark.parametrize("path,model", [
    ("mantle_openai_responses", "openai.gpt-5.6-sol"),
    ("mantle_openai_chat", "openai.gpt-6-astra"),
    ("mantle_messages", "anthropic.claude-opus-5-5"),
])
def test_comparator_requires_an_equal_non_null_mantle_selector(path, model):
    matches = _comparator()
    advisor = {"model": model, "api_path": path, "invocation_model_id": model,
               "mantle_selector": "background_inference"}
    assert matches(advisor, model, path, None, "background_inference")
    assert not matches(advisor, model, path)  # plan row without a selector
    assert not matches(advisor, model, path, None, "web_search")
    assert not matches(advisor, model, "runtime_openai_cris", None, "background_inference")
    # an advisor Mantle contract that carries a null selector never validates
    assert not matches({**advisor, "mantle_selector": None}, model, path, None, "background_inference")
    assert not matches({**advisor, "mantle_selector": None}, model, path)


def test_gcp_design_ai_todo_is_resolved():
    assert "TODO(PR 3" not in GCP_DESIGN_AI_MD.read_text()


def test_poc_constructs_runtime_messages_and_runtime_openai_clients():
    text = _norm(POC_MD)
    for needle in NEW_PATHS:
        assert f"`{needle}`" in text, f"poc.md must branch on {needle}"
    assert "bedrock-runtime.{region}.amazonaws.com/anthropic" in text
    assert "bedrock-runtime.{region}.amazonaws.com/openai/v1" in text


@pytest.mark.parametrize("path", [CONFIRM_MD, DESIGN_MD])
def test_confirm_and_design_carry_mantle_selector(path):
    assert "mantle_selector" in _norm(path), f"{path.name} must carry mantle_selector"


def test_skill_md_files_table_lists_the_vendored_policy():
    text = SKILL_MD.read_text()
    files_section = text.split("## Files", 1)[1]
    assert "`references/vendored/ai/bedrock-endpoint-policy.md`" in files_section
