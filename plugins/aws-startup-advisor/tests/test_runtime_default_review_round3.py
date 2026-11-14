"""Guards for the PR 588 review-round-2 findings that land on PR 585's branch (F12, F15, F3 Azure
half, F4 cloud half).

Public basis (read 2026-11-09, all under https://docs.aws.amazon.com/bedrock/latest/userguide/):
  inference-responses-api.html — stored responses exist on the Responses API of either endpoint;
      bedrock-mantle inference authorizes `bedrock-mantle:CreateInference`, bedrock-runtime stored
      response management authorizes `bedrock:GetInvoke` / `CancelInvoke` / `DeleteInvoke` on the
      default project (F12).
  web-search.html + security-web-search.html — actions `bedrock-websearch:InvokeSearch`,
      `InvokeFetch`, `ExternalWebAccess` on resource `*`; `aws:RequestedRegion` the only condition
      key; `external_web_access` defaults to true and Fetch fails without the action (F15).
  model-card-openai-gpt-6-sol.html / -6-luna / -6-1-sol / -6-astra / -56-* / -55 / -54 — Guardrails
      API scope is per model (F3).
  web-search.html, inference-responses-api.html, projects.html, workspaces.html — the API each
      selector requires (F4).

Helper behaviour lives next to the helper (`skills/llm-to-bedrock/scripts/test_iam_policy_round2.py`,
classes TestStoredResponseOps / TestWebSearchGrants); this file pins the prose recipes, the
Design/schema contracts and the new design fixture.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
SCRIPTS = SKILLS / "llm-to-bedrock" / "scripts"
REPORT_GENERATOR = PLUGIN_ROOT / "agents" / "llm2bedrock-report-generator.md"
CODE_REWRITER = PLUGIN_ROOT / "agents" / "llm2bedrock-code-rewriter.md"
GCP_GENERATE_ARTIFACTS = SKILLS / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md"
AZURE_GENERATE_ARTIFACTS = SKILLS / "azure-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md"
CANONICAL_GUIDE = SKILLS / "shared" / "ai" / "ai-openai-to-bedrock.md"
VENDORED_GUIDES = [
    SKILLS / "gcp-to-aws" / "references" / "vendored" / "ai" / "ai-openai-to-bedrock.md",
    SKILLS / "azure-to-aws" / "references" / "vendored" / "ai" / "ai-openai-to-bedrock.md",
]
GCP_DESIGN_AI = SKILLS / "gcp-to-aws" / "references" / "phases" / "design" / "design-ai.md"
AZURE_DESIGN_AI = SKILLS / "azure-to-aws" / "references" / "phases" / "design" / "design-ai.md"
CANONICAL_SCHEMA_DOC = SKILLS / "shared" / "ai" / "schema-design-aws-ai.md"
VENDORED_SCHEMA_DOCS = [
    SKILLS / "gcp-to-aws" / "references" / "vendored" / "ai" / "schema-design-aws-ai.md",
    SKILLS / "azure-to-aws" / "references" / "vendored" / "ai" / "schema-design-aws-ai.md",
]
GCP_SHADOW_SCHEMA = SKILLS / "gcp-to-aws" / "references" / "shared" / "schema-design-aws-ai.md"
AZURE_SHADOW_SCHEMA = SKILLS / "azure-to-aws" / "references" / "shared" / "schema-design-aws-ai.md"
ALL_SCHEMA_DOCS = [CANONICAL_SCHEMA_DOC, *VENDORED_SCHEMA_DOCS, GCP_SHADOW_SCHEMA, AZURE_SHADOW_SCHEMA]
DESIGN_FIXTURES = sorted((PLUGIN_ROOT / "fixtures" / "aws-design-ai").glob("*/aws-design-ai.json"))
NEW_FIXTURE = PLUGIN_ROOT / "fixtures" / "aws-design-ai" / "chat-source-web-search-continuity-kept" / "aws-design-ai.json"
DESIGN_AI_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "aws-design-ai.schema.json"
ARTIFACT_VALIDATOR = PLUGIN_ROOT / "scripts" / "validate-artifacts.py"

RESPONSES_PAGE = "https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html"
WEB_SEARCH_PAGE = "https://docs.aws.amazon.com/bedrock/latest/userguide/web-search.html"
WEB_SEARCH_IAM_PAGE = "https://docs.aws.amazon.com/bedrock/latest/userguide/security-web-search.html"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i: text.index(end, i)]


def _squash(text: str) -> str:
    return " ".join(text.split())


def _recipe() -> tuple[str, str]:
    raw = _section(REPORT_GENERATOR.read_text(), "# 6.4 Generate scoped IAM policy artifact", "# 7. Generate report")
    return _squash(raw), _section(raw, "```bash", "```\n")


# --------------------------------------------------------------------------- F12 + F15: report §6.4

def test_report_recipe_passes_mantle_selectors_and_external_web_access_to_the_helper() -> None:
    recipe, code = _recipe()
    assert "[--mantle-selector <bedrock_models[].mantle_selector of every mantle_* row" in code
    assert "[--external-web-access — ONLY when the user explicitly confirmed external web access" in code
    # Round-2 pinned strings survive.
    assert "only when a `--target` row is a runtime GPT CRIS id on `responses`" in recipe
    assert "`reason: stored_response_ops_no_responses_row` for a Converse / Anthropic Messages / Chat Completions plan" in recipe
    assert "When the field is absent or `[]`, omit the flag" in recipe


def test_report_recipe_dispatches_stored_response_grants_by_endpoint() -> None:
    recipe, _ = _recipe()
    para = _section(recipe, "**Retained stored-response operations need their own grant.**", "**Web Search needs its own grants.**")
    assert "the grant is dispatched by endpoint" in para
    assert "a `--target` row that is a bare Mantle id on `responses` (a `mantle_openai_responses` plan) satisfies retained ops through the `BedrockMantleInference` statement" in para
    assert "`GET /v1/responses/{id}`" in para and "`bedrock-mantle:CreateInference`" in para
    assert "no `bedrock:GetInvoke` is added for it and the helper does not exit 1" in para
    assert "read 2026-11-09" in para
    assert "Stored responses exist only on the runtime Responses API" not in recipe


def test_report_recipe_names_the_web_search_grants_and_the_fetch_default() -> None:
    recipe, _ = _recipe()
    para = _section(recipe, "**Web Search needs its own grants.**", "The script handles the dual-ARN pattern")
    assert "`--mantle-selector web_search`" in para and "`BedrockWebSearch` statement" in para
    assert "`bedrock-websearch:InvokeSearch`" in para and "`bedrock-websearch:InvokeFetch`" in para
    assert "resource `*`" in para and "`aws:RequestedRegion` condition" in para
    assert "`bedrock-websearch:ExternalWebAccess`" in para
    assert 'MUST set `"external_web_access": false`' in para
    assert "the parameter defaults to `true`" in para
    assert "every Fetch then fails authorization before the cache is read" in para
    assert "pass `--external-web-access` too" in para
    assert WEB_SEARCH_PAGE in para and WEB_SEARCH_IAM_PAGE in para and "read 2026-11-09" in para
    assert "`reason: web_search_without_mantle_row`" in para
    assert "`reason: external_web_access_without_web_search`" in para
    assert "A plan with no `web_search` row gets no `bedrock-websearch:*` action" in para


def test_report_checklist_has_a_tool_level_permission_check() -> None:
    apply = _squash(_section(REPORT_GENERATOR.read_text(), "## How to Apply", "## How to Undo"))
    assert "Tool-level permission check" in apply
    assert "Render ONLY when `web_search` is a confirmed mantle requirement" in apply
    assert 'tools=[{"type": "web_search", "external_web_access": False}]' in apply
    assert "`web_search_call` item or a `url_citation` annotation" in apply
    assert "CloudTrail Web Search data events for a denied `InvokeSearch` / `InvokeFetch`" in apply
    assert "a plain model ping passing does not prove the Web Search grant" in apply
    # The create-plus-retrieve bullet gained its Mantle variant.
    assert "For a `mantle_openai_responses` plan run the same `responses.create` / `responses.retrieve(r.id)` pair against the Mantle base URL" in apply
    assert "`BedrockMantleInference` statement is not attached" in apply


# --------------------------------------------------------------------------- F12 + F15: setup recipes

@pytest.mark.parametrize("path", [GCP_GENERATE_ARTIFACTS, AZURE_GENERATE_ARTIFACTS, CANONICAL_GUIDE], ids=lambda p: p.parent.parent.name if "shared" not in p.parts else "canonical")
def test_setup_recipes_name_the_web_search_grants_and_mantle_stored_response_coverage(path: Path) -> None:
    text = _squash(path.read_text())
    # Round-2 pinned strings survive.
    assert "iam_policy.py --stored-response-ops retrieve[,cancel,delete]" in text
    assert "client.responses.retrieve(r.id)" in text and "read 2026-11-08" in text
    assert re.search(r"`converse`(,| /) `messages`", text), path
    # F12
    assert "`BedrockMantleInference`" in text, path
    assert "`GET /v1/responses/{id}`" in text and "`bedrock-mantle:CreateInference`" in text, path
    assert "no `bedrock:GetInvoke`" in text, path
    # F15
    assert "bedrock-websearch:InvokeSearch" in text and "bedrock-websearch:InvokeFetch" in text, path
    assert "bedrock-websearch:ExternalWebAccess" in text, path
    assert "--mantle-selector web_search" in text, path
    assert '"external_web_access": false' in text, path
    assert "defaults to `true`" in text, path
    assert "--external-web-access" in text, path
    assert WEB_SEARCH_PAGE in text and WEB_SEARCH_IAM_PAGE in text, path
    assert "read 2026-11-09" in text, path
    assert "no `bedrock-websearch:*` action" in text, path


def test_setup_verification_has_a_tool_level_web_search_check() -> None:
    for path in (GCP_GENERATE_ARTIFACTS, AZURE_GENERATE_ARTIFACTS):
        text = _squash(path.read_text())
        assert 'tools=[{"type": "web_search", "external_web_access": False}]' in text, path
        assert "`web_search_call` item or a `url_citation` annotation" in text, path
        assert "a plain model ping passing does not prove the grant" in text, path


def test_vendored_openai_guides_match_canonical() -> None:
    for vendored in VENDORED_GUIDES:
        assert vendored.read_bytes() == CANONICAL_GUIDE.read_bytes(), vendored


# --------------------------------------------------------------------------- F3 (Azure half): per-model Guardrails rule

BLANKET_GUARDRAILS = [
    "never `responses`) for 6.1 Sol and the other GPT-6/5.6",
    "the other GPT-6/5.6 CRIS models except Astra",
    "note Guardrails are Converse-only",
]
NINE_CARDS = [
    "model-card-openai-gpt-6-sol.html", "model-card-openai-gpt-6-luna.html", "model-card-openai-gpt-6-1-sol.html",
    "model-card-openai-gpt-6-astra.html", "model-card-openai-gpt-56-sol.html", "model-card-openai-gpt-56-terra.html",
    "model-card-openai-gpt-56-luna.html", "model-card-openai-gpt-55.html", "model-card-openai-gpt-54.html",
]


@pytest.mark.parametrize("path", [AZURE_DESIGN_AI, AZURE_SHADOW_SCHEMA, CANONICAL_SCHEMA_DOC, GCP_SHADOW_SCHEMA, CODE_REWRITER],
                         ids=lambda p: p.name if p.suffix == ".md" and "agents" in p.parts else str(p.relative_to(SKILLS)))
def test_blanket_converse_only_guardrails_wording_is_gone(path: Path) -> None:
    text = _squash(path.read_text())
    for blanket in BLANKET_GUARDRAILS:
        assert blanket not in text, f"{path}: blanket wording {blanket!r} still present"


@pytest.mark.parametrize("path", [AZURE_DESIGN_AI, AZURE_SHADOW_SCHEMA], ids=lambda p: p.parent.name)
def test_azure_design_and_schema_carry_the_per_model_guardrails_api_rule(path: Path) -> None:
    text = _squash(path.read_text())
    assert "`converse` for GPT-6 Astra, GPT-5.6 Sol / Terra / Luna, GPT-5.5, GPT-5.4 and GPT-6.1 Terra" in text
    assert "`responses` / `chat_completions` / `invoke` / `converse` for GPT-6 Sol and GPT-6 Luna" in text
    assert "`chat_completions` / `invoke` / `converse` (never `responses`) for GPT-6.1 Sol" in text
    assert "model cards read 2026-11-09" in text
    for card in NINE_CARDS:
        assert card in text, f"{path}: {card} not cited"


def test_azure_design_closes_with_the_card_scoped_responses_rule() -> None:
    azure = _squash(AZURE_DESIGN_AI.read_text())
    assert "Do not leave the client on `responses` when Guardrails is required on a model whose card excludes Responses." in azure
    assert "Do not leave the client on `responses` when Guardrails is required.**" not in azure
    for name in ("GPT-6 Sol", "GPT-6 Luna", "GPT-6.1 Sol", "GPT-6 Astra", "GPT-5.5", "GPT-5.4", "GPT-6.1 Terra"):
        assert name in azure, name


def test_code_rewriter_carries_the_per_model_guardrails_and_caching_scope() -> None:
    text = _squash(CODE_REWRITER.read_text())
    assert "Guardrails and prompt-caching API scope are per model card and are carried by `bedrock_models[].required_client_api`" in text
    assert "GPT-6 Sol / Luna list Guardrails on Responses, Chat Completions, InvokeModel and Converse" in text
    assert "GPT-6.1 Sol on Chat Completions, InvokeModel and Converse (not Responses)" in text
    assert "GPT-5.6 Sol / Terra / Luna, GPT-5.5, GPT-5.4 and GPT-6 Astra on Converse only" in text
    assert "implicit prompt caching is Responses-only on runtime for GPT-5.5 / GPT-5.4" in text
    assert "cards read 2026-11-09" in text


# --------------------------------------------------------------------------- F4 (cloud half): selector ↔ API validation

STEP_08_PHRASES = [
    "Validate the matched selector against the API it requires",
    "require the Responses API",
    "`workspaces` requires the Anthropic Messages API",
    "`projects` requires an OpenAI-compatible API",
    "explicit API-continuity decision",
    "never a silent same-API Mantle row",
    "`mantle_openai_chat` / `mantle_messages` is never recorded for a Responses-only selector",
    "read 2026-11-09",
]


@pytest.mark.parametrize(("path", "end"), [(GCP_DESIGN_AI, "## Part 1"), (AZURE_DESIGN_AI, "Exactly one of")],
                         ids=["gcp", "azure"])
def test_step_08_validates_the_selector_against_its_api_before_choosing_a_path(path: Path, end: str) -> None:
    step = _squash(_section(path.read_text(), "## Step 0.8", end))
    for phrase in STEP_08_PHRASES:
        assert phrase in step, f"{path}: {phrase!r} missing from Step 0.8"
    assert "1b." in step
    assert re.search(r"2\. \*\*(Any m|M)atch that passes 1b", step), f"{path}: rule 2 must depend on 1b"
    assert "keep the source API on `bedrock-runtime` and drop the requirement" in step
    assert "move to `mantle_openai_responses`" in step
    assert "`workspaces` on an OpenAI SDK workload, `projects` on an Anthropic SDK workload" in step


@pytest.mark.parametrize("path", ALL_SCHEMA_DOCS, ids=lambda p: str(p.relative_to(SKILLS)))
def test_schema_docs_carry_the_responses_only_selector_decision(path: Path) -> None:
    text = _squash(path.read_text())
    assert "A matched selector is validated against the API it requires before the path is chosen" in text
    assert "`web_search`, `background_inference`, and `server_side_tools` require the Responses API" in text
    assert "explicit API-continuity decision" in text and "never a silent same-API Mantle row" in text
    assert "`workspaces` on OpenAI, `projects` on Anthropic" in text


def test_vendored_schema_docs_are_byte_identical_to_the_canonical() -> None:
    for vendored in VENDORED_SCHEMA_DOCS:
        assert vendored.read_bytes() == CANONICAL_SCHEMA_DOC.read_bytes(), vendored


def _design_ai_findings(design: dict) -> list:
    validator = _load_module("round3_artifact_validator", ARTIFACT_VALIDATOR)
    schema = json.loads(DESIGN_AI_SCHEMA.read_text())
    findings: list = []
    validator.validate_json_schema(schema, design, "", "design", str(DESIGN_AI_SCHEMA), findings)
    return findings


def test_chat_source_web_search_fixture_keeps_the_api_and_discloses_the_dropped_selector() -> None:
    design = json.loads(NEW_FIXTURE.read_text())
    assert _design_ai_findings(design) == []
    rows = design["ai_architecture"]["bedrock_models"]
    assert len(rows) == 1
    row = rows[0]
    assert row["migration_path"] == "runtime_openai_cris"
    assert row["required_client_api"] == "chat_completions"
    assert "mantle_selector" not in row and "mantle_requirement" not in row
    assert row["endpoint_assumption"].startswith("No Mantle-only requirement was recorded for wl_openai_research_bot; bedrock-runtime selected.")
    assert any("web_search" in gap and "Responses API" in gap and "explicit decision" in gap for gap in row["capability_gaps"])
    assert "Step 0.8 rule 1b" in design["design_blocks"][0]["rationale"]
    assert design["metadata"]["ai_sources"][0]["models"] == ["gpt-5.6-terra"]
    assert design["metadata"]["bedrock_models_selected"] == [row["aws_model_id"]] == ["us.openai.gpt-5.6-terra"]
    # The Geo CRIS rate is published on the GPT-5.6 Terra card; GPT-5.5 / GPT-5.4 publish no Geo/Global
    # price, so a runtime CRIS row for them must never carry a verified-looking parity price.
    assert row["bedrock_price"] == "2.20/13.20 per 1M tokens"
    assert row["source_provider_price"] == "2.00/12.00 per 1M tokens"
    assert row["price_comparison"] != "parity"


def test_design_fixture_corpus_never_records_a_responses_only_selector_on_a_same_api_mantle_row() -> None:
    assert NEW_FIXTURE in DESIGN_FIXTURES
    for path in DESIGN_FIXTURES:
        for row in json.loads(path.read_text())["ai_architecture"]["bedrock_models"]:
            selector = row.get("mantle_selector")
            if row.get("migration_path") == "mantle_openai_chat":
                assert selector not in {"web_search", "background_inference", "server_side_tools"}, f"{path}: Responses-only selector on a Chat Mantle row"
            if row.get("migration_path") == "mantle_messages":
                assert selector not in {"background_inference", "projects"}, f"{path}: OpenAI-only selector on a Messages Mantle row"
