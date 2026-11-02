"""Guard: PR #433 round 5 findings — GPT-6 IAM, Guardrails client-surface, and
Chat Completions corrections (prose). The IAM helper's own behavior is tested in
skills/llm-to-bedrock/scripts/test_iam_policy.py; this file covers the prose that
must stay aligned with it.

Finding 1 — generate-artifacts-ai.md Step 3 (both clouds) documents the
GPT-6 CRIS `project/default` grant.
Finding 2 — schema-design-aws-ai.md documents `required_client_api`; both
design-ai.md files require a Converse (non-Responses) client for a Guardrails
workload on `runtime_openai_cris`; both generate-artifacts-ai.md files consume
`required_client_api` in the CRIS Step 1M.
Finding 3 — the behavior-delta openai-to-bedrock.md no longer claims Chat
Completions is unverified/unsupported for GPT-6, and the matching design/
generate prose in both clouds no longer forces a GPT-6 Chat Completions
source to reshape.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

GCP_GENERATE_ARTIFACTS_AI_MD = (
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md"
)
AZURE_GENERATE_ARTIFACTS_AI_MD = (
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md"
)
GENERATE_ARTIFACTS_AI_FILES = [GCP_GENERATE_ARTIFACTS_AI_MD, AZURE_GENERATE_ARTIFACTS_AI_MD]

GCP_DESIGN_AI_MD = PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "design" / "design-ai.md"
AZURE_DESIGN_AI_MD = PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "design" / "design-ai.md"
DESIGN_AI_FILES = [GCP_DESIGN_AI_MD, AZURE_DESIGN_AI_MD]

GCP_GENERATE_AI_MD = PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-ai.md"

SCHEMA_DESIGN_AWS_AI = (
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "shared" / "schema-design-aws-ai.md"
)

BEHAVIOR_DELTA_MD = (
    PLUGIN_ROOT
    / "skills"
    / "llm-to-bedrock"
    / "references"
    / "helpers"
    / "behavior-delta-detection"
    / "references"
    / "openai-to-bedrock.md"
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# --- Finding 1: generate-artifacts-ai.md Step 3 names project/default for GPT-6 CRIS ---


def test_both_generate_artifacts_ai_document_gpt6_cris_project_default() -> None:
    for f in GENERATE_ARTIFACTS_AI_FILES:
        text = _norm(f.read_text(encoding="utf-8"))
        assert "project/default" in text, (
            f"{f}: Step 3/Step 1M must name the project/default ARN for a GPT-6 CRIS target"
        )
        assert "GPT-6" in text


# --- Finding 2: required_client_api schema + design + generate ---


def test_schema_documents_required_client_api_with_converse_for_guardrails() -> None:
    text = SCHEMA_DESIGN_AWS_AI.read_text(encoding="utf-8")
    assert "required_client_api" in text
    assert "converse" in text.lower()
    assert "Astra" in text


def test_both_design_ai_require_converse_client_for_astra_guardrails() -> None:
    for f in DESIGN_AI_FILES:
        text = _norm(f.read_text(encoding="utf-8"))
        assert "required_client_api" in text, (
            f"{f}: design must record required_client_api for a Guardrails workload on CRIS"
        )
        assert "converse" in text.lower()
        assert "never `responses`" in text.lower() or "never responses" in text.lower()


def test_both_generate_artifacts_ai_consume_required_client_api_in_cris_step() -> None:
    for f in GENERATE_ARTIFACTS_AI_FILES:
        text = _norm(f.read_text(encoding="utf-8"))
        assert "required_client_api" in text, (
            f"{f}: CRIS Step 1M must consume required_client_api"
        )
        assert "responses.create" in text


def test_region_only_cris_move_keeps_responses() -> None:
    for f in DESIGN_AI_FILES + GENERATE_ARTIFACTS_AI_FILES:
        text = _norm(f.read_text(encoding="utf-8"))
        assert "region-only" in text.lower()


# --- Finding 3: Chat Completions optional reshape for GPT-6/GPT-5.6 ---


def test_behavior_delta_no_longer_claims_chat_completions_unverified() -> None:
    text = BEHAVIOR_DELTA_MD.read_text(encoding="utf-8")
    assert "no GPT model card lists Chat Completions as supported" not in text, (
        "openai-to-bedrock.md must not claim Chat Completions is unverified for GPT-6/GPT-5.6"
    )
    assert "supported" in text.lower() and "Chat Completions" in text
    assert "OPTIONAL" in text, (
        "openai-to-bedrock.md must make the Responses reshape optional, not mandatory"
    )


def test_both_design_ai_no_longer_force_gpt6_chat_completions_reshape() -> None:
    for f in DESIGN_AI_FILES:
        text = _norm(f.read_text(encoding="utf-8"))
        assert "near-drop-in" in text.lower() or "optional" in text.lower(), (
            f"{f}: a GPT-6/GPT-5.6 Chat Completions source must not be forced to reshape"
        )
        assert "GPT-5.5" in text and "GPT-5.4" in text, (
            f"{f}: the mandatory-reshape exception must still be scoped to GPT-5.5/GPT-5.4"
        )


def test_gcp_generate_ai_no_longer_forces_gpt6_chat_completions_reshape() -> None:
    text = _norm(GCP_GENERATE_AI_MD.read_text(encoding="utf-8"))
    assert "optional" in text.lower()
    assert "GPT-5.5" in text and "GPT-5.4" in text
