"""Guard: PR #433 round 4 findings (CRIS carve-out propagation + Execute-phase
GPT-6 recognition, report pricing bugs).

Finding 0 — runtime_openai_cris carve-out gaps:
  (a) Azure design.md / generate.md _assert blocks must scope the GPT-ban to
      GPT-5.5/GPT-5.4 and explicitly carve out GPT-5.6/GPT-6 on runtime_openai_cris.
  (b) GCP generate-ai.md Part 1 must route runtime_openai_cris through
      bedrock-runtime, not the mantle URL/IAM.
  (c) Canonical model-selection guide + vendored guardrails must name the full
      GPT-6 model set, not just GPT-5.6.
  (d) Both estimators' Part 5 "+10% for model_change:false" must carve out
      Global CRIS parity.

Finding 1 — bare GPT-6 IDs recognized as Mantle-only by Execute-phase helpers
(prose files only here; code helper tests live alongside their scripts).
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

AZURE_DESIGN_MD = PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "design" / "design.md"
AZURE_GENERATE_MD = PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "generate" / "generate.md"

GCP_GENERATE_AI_MD = PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-ai.md"
GCP_GENERATE_ARTIFACTS_AI_MD = (
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md"
)

GUARDRAILS_CANONICAL = PLUGIN_ROOT / "skills" / "shared" / "ai" / "ai-migration-guardrails.md"
GUARDRAILS_VENDORED = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "vendored" / "ai" / "ai-migration-guardrails.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "vendored" / "ai" / "ai-migration-guardrails.md",
]

OPENAI_GUIDE_CANONICAL = PLUGIN_ROOT / "skills" / "shared" / "ai" / "ai-openai-to-bedrock.md"
OPENAI_GUIDE_VENDORED = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "vendored" / "ai" / "ai-openai-to-bedrock.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "vendored" / "ai" / "ai-openai-to-bedrock.md",
]

ESTIMATE_AI_FILES = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "estimate" / "estimate-ai.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "estimate" / "estimate-ai.md",
]

RESOLVER_MD = (
    PLUGIN_ROOT
    / "skills"
    / "llm-to-bedrock"
    / "references"
    / "helpers"
    / "resolve-bedrock-model-id"
    / "resolve-bedrock-model-id.md"
)
CODE_ANALYZER_MD = PLUGIN_ROOT / "agents" / "llm2bedrock-code-analyzer.md"
PROMPT_EVALUATOR_MD = PLUGIN_ROOT / "agents" / "llm2bedrock-prompt-evaluator.md"
CODE_REWRITER_MD = PLUGIN_ROOT / "agents" / "llm2bedrock-code-rewriter.md"
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

REPORT_GENERATOR_MD = PLUGIN_ROOT / "agents" / "llm2bedrock-report-generator.md"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# --- Finding 0.1: Azure design.md / generate.md assert carve-out ---


def test_azure_design_assert_scopes_gpt_ban_to_55_54_and_carves_out_cris() -> None:
    text = _norm(AZURE_DESIGN_MD.read_text(encoding="utf-8"))
    assert "no proprietary GPT-5.5 or GPT-5.4 model ID is paired" in text, (
        "design.md _assert must scope the ban to GPT-5.5/GPT-5.4, not blanket 'openai.gpt-*'"
    )
    assert "runtime_openai_cris on bedrock-runtime — this is not a violation" in text
    assert "no proprietary openai.gpt-* model ID is paired" not in text


def test_azure_generate_assert_scopes_gpt_ban_to_55_54_and_carves_out_cris() -> None:
    text = _norm(AZURE_GENERATE_MD.read_text(encoding="utf-8"))
    assert "no proprietary GPT-5.5 or GPT-5.4 model ID is paired" in text, (
        "generate.md _assert must scope the ban to GPT-5.5/GPT-5.4, not blanket 'openai.gpt-*'"
    )
    assert "runtime_openai_cris on bedrock-runtime — this is not a violation" in text
    assert "no proprietary openai.gpt-* model ID is paired" not in text


# --- Finding 0.2: GCP generate-ai.md Part 1 routing ---


def test_gcp_generate_ai_routes_cris_through_bedrock_runtime_not_mantle() -> None:
    text = GCP_GENERATE_AI_MD.read_text(encoding="utf-8")
    assert "bedrock-runtime.{region}.amazonaws.com/openai/v1" in text, (
        "generate-ai.md Part 1 must route runtime_openai_cris through the bedrock-runtime URL"
    )
    # The CRIS bullet must explicitly disclaim the mantle URL/IAM for this path.
    normalized = _norm(text)
    assert "not the mantle url" in normalized.lower() or "not** the mantle url" in normalized.lower()
    assert "not** `bedrock-mantle:*`" in normalized or "not `bedrock-mantle:*`" in normalized.lower()


def test_gcp_step1m_and_harness_agree_on_adapter_free_paths() -> None:
    text = GCP_GENERATE_ARTIFACTS_AI_MD.read_text(encoding="utf-8")
    step1m = text.split("## Step 1M:", 1)[1].split("## Step 1:", 1)[0]
    harness = text.split("## Step 2:", 1)[1].split("## Step 3:", 1)[0]
    assert "do not emit or import a provider-adapter stub" in step1m
    assert "Mantle / runtime CRIS" in harness
    assert "do not import `provider_adapter`" in harness
    assert "from provider_adapter import get_provider" in harness
    assert "client.responses.create" in harness
    assert "client.chat.completions.create" in harness


# --- Finding 0.3: canonical guide + vendored guardrails name full GPT-6 set ---


def test_guardrails_canonical_and_vendored_name_gpt6_family() -> None:
    text = GUARDRAILS_CANONICAL.read_text(encoding="utf-8")
    assert "GPT-6" in text
    assert "fallback exists only for GPT-5.6 and GPT-6" in text or (
        "GPT-5.6 and GPT-6" in text
    )
    for vendored in GUARDRAILS_VENDORED:
        assert vendored.read_text(encoding="utf-8") == text, (
            f"{vendored} is not byte-identical to the canonical ai-migration-guardrails.md"
        )


def test_openai_guide_canonical_and_vendored_region_gate_names_gpt6() -> None:
    text = OPENAI_GUIDE_CANONICAL.read_text(encoding="utf-8")
    assert "GPT-6 Astra / Sol / Luna / 6.1 Sol:" in text, (
        "ai-openai-to-bedrock.md Region gate section must have a GPT-6 bullet"
    )
    for vendored in OPENAI_GUIDE_VENDORED:
        assert vendored.read_text(encoding="utf-8") == text, (
            f"{vendored} is not byte-identical to the canonical ai-openai-to-bedrock.md"
        )


# --- Finding 0.4: estimators carve out Global CRIS parity ---


def test_both_estimators_carve_out_global_cris_parity() -> None:
    for f in ESTIMATE_AI_FILES:
        text = f.read_text(encoding="utf-8")
        normalized = _norm(text)
        assert "model_change: false" in text
        assert "Global CRIS" in text, f"{f}: no Global CRIS carve-out near model_change:false rule"
        assert "parity" in normalized.lower()
        assert "computed Part 5 result, not a fixed premium" in text
        assert "source comparison is unavailable" in text


# --- Finding 1 (prose): bare GPT-6 recognized by resolver / agents ---


def test_resolver_covers_bare_gpt6_ids() -> None:
    text = RESOLVER_MD.read_text(encoding="utf-8")
    assert "openai.gpt-6" in text or "GPT-6" in text, (
        "resolve-bedrock-model-id.md must route bare GPT-6 IDs (Case A) same as GPT-5.5/5.4"
    )


def test_code_analyzer_covers_gpt6() -> None:
    text = CODE_ANALYZER_MD.read_text(encoding="utf-8")
    assert "gpt-6" in text.lower(), "llm2bedrock-code-analyzer.md must extend openai.gpt-5* refs to GPT-6"


def test_prompt_evaluator_covers_gpt6() -> None:
    text = PROMPT_EVALUATOR_MD.read_text(encoding="utf-8")
    assert "gpt-6" in text.lower(), "llm2bedrock-prompt-evaluator.md must extend openai.gpt-5* refs to GPT-6"


def test_code_rewriter_covers_gpt6() -> None:
    text = CODE_REWRITER_MD.read_text(encoding="utf-8")
    assert "gpt-6" in text.lower(), "llm2bedrock-code-rewriter.md must extend openai.gpt-5* refs to GPT-6"


def test_behavior_delta_reference_covers_gpt6() -> None:
    text = BEHAVIOR_DELTA_MD.read_text(encoding="utf-8")
    assert "gpt-6" in text.lower(), (
        "behavior-delta-detection/references/openai-to-bedrock.md same-model (mantle) deltas "
        "list must include the four GPT-6 IDs"
    )


# --- Finding 4 (report-generator gap): §6.2 source-pricing table has GPT-6 rows ---


def test_report_generator_section_6_2_has_gpt6_source_rows() -> None:
    text = REPORT_GENERATOR_MD.read_text(encoding="utf-8")
    expected_rows = {
        "gpt-6-astra": ("10.00", "50.00"),
        "gpt-6.1-sol": ("2.00", "10.00"),
        "gpt-6-sol": ("2.00", "10.00"),
        "gpt-6-luna": ("0.10", "0.50"),
    }
    for model, (input_rate, output_rate) in expected_rows.items():
        pattern = re.compile(
            r"\|\s*" + re.escape(model) + r"\s*\|\s*" + re.escape(input_rate)
            + r"\s*\|\s*" + re.escape(output_rate) + r"\s*\|"
        )
        assert pattern.search(text), (
            f"§6.2 source-pricing table missing/incorrect row for {model} "
            f"(expected {input_rate}/{output_rate})"
        )
