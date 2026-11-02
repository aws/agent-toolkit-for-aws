"""Guard: PR #433 second review round (leon1418) fixes stay in place.

Finding 1 — GPT-6 source-price breakpoint note (pricing-cache.md OpenAI tables).
Finding 2 — runtime_openai_cris gate/dispatch coverage for GPT-6/GPT-5.6.
Finding 3 — GPT-6 Astra Invoke-support correction (openai-on-bedrock.md).
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

PRICING_CACHE_FILES = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "shared" / "pricing-cache.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "shared" / "pricing-cache.md",
]

OPENAI_ON_BEDROCK_FILES = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "shared" / "openai-on-bedrock.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "shared" / "openai-on-bedrock.md",
]

DESIGN_AI_FILES = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "design" / "design-ai.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "design" / "design-ai.md",
]

GENERATE_ARTIFACTS_AI_FILES = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md",
]

SCHEMA_DESIGN_AWS_AI = (
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "shared" / "schema-design-aws-ai.md"
)

GENERATE_AI_GCP = PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-ai.md"

ESTIMATE_AI_FILES = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "estimate" / "estimate-ai.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "estimate" / "estimate-ai.md",
]


# --- Finding 1: source-price breakpoint note ---

def test_both_pricing_caches_document_gpt6_breakpoint() -> None:
    for f in PRICING_CACHE_FILES:
        text = f.read_text(encoding="utf-8")
        assert "GPT-6" in text and "272,000 input tokens" in text, (
            f"{f}: GPT-6 source-price breakpoint note missing (Finding 1)"
        )


def test_both_estimate_ai_files_require_matching_context_tiers() -> None:
    for f in ESTIMATE_AI_FILES:
        text = f.read_text(encoding="utf-8")
        assert "long-context parity" in text.lower(), (
            f"{f}: no OpenAI/GPT source-side long-context parity rule (Finding 1)"
        )
        assert "272,000 input tokens" in text, (
            f"{f}: long-context parity rule missing the 272,000-token breakpoint (Finding 1)"
        )
        assert "approximate" in text.lower(), (
            f"{f}: long-context parity rule does not flag the comparison approximate when "
            f"request-size data is unknown (Finding 1)"
        )


# --- Finding 2: runtime_openai_cris gate/dispatch ---

def test_design_ai_scopes_mantle_only_to_gpt55_gpt54() -> None:
    for f in DESIGN_AI_FILES:
        text = f.read_text(encoding="utf-8")
        assert "runtime_openai_cris" in text, (
            f"{f}: no runtime_openai_cris carve-out for GPT-6/5.6 (Finding 2)"
        )
        assert "GPT-5.5" in text and "GPT-5.4" in text, (
            f"{f}: mantle-only scoping must name GPT-5.5/GPT-5.4 specifically (Finding 2)"
        )


def test_generate_artifacts_ai_dispatches_runtime_openai_cris() -> None:
    for f in GENERATE_ARTIFACTS_AI_FILES:
        text = f.read_text(encoding="utf-8")
        assert "runtime_openai_cris" in text, (
            f"{f}: generator does not dispatch runtime_openai_cris (Finding 2)"
        )


def test_generate_ai_gcp_timeline_handles_runtime_openai_cris() -> None:
    text = GENERATE_AI_GCP.read_text(encoding="utf-8")
    assert "runtime_openai_cris" in text, (
        "generate-ai.md: fast-track timeline does not branch on runtime_openai_cris (Finding 2)"
    )


def test_schema_design_aws_ai_vocabulary_includes_runtime_openai_cris() -> None:
    text = SCHEMA_DESIGN_AWS_AI.read_text(encoding="utf-8")
    assert "runtime_openai_cris" in text, (
        "schema-design-aws-ai.md: migration_path vocabulary missing runtime_openai_cris (Finding 2)"
    )
    assert "GPT-5.5" in text and "GPT-5.4" in text, (
        "schema-design-aws-ai.md: mantle-only scoping must name GPT-5.5/GPT-5.4 specifically, "
        "not blanket 'proprietary GPT' (Finding 2)"
    )


# --- Finding 3: Astra Invoke-support correction ---

def test_openai_on_bedrock_scopes_invoke_support_per_model() -> None:
    for f in OPENAI_ON_BEDROCK_FILES:
        text = f.read_text(encoding="utf-8")
        normalized = re.sub(r"\s+", " ", text)
        assert "does NOT support `Invoke`" in normalized, (
            f"{f}: no per-model Invoke-support carve-out (Finding 3)"
        )
        assert "Astra" in text, f"{f}: Astra Invoke exception not documented (Finding 3)"
        # The old, now-wrong blanket claim must be gone.
        assert "All four support `Responses`, `Chat Completions`, `Invoke`, and" not in text, (
            f"{f}: stale blanket Invoke-support claim still present (Finding 3)"
        )


def test_openai_on_bedrock_notes_mantle_never_supports_invoke() -> None:
    for f in OPENAI_ON_BEDROCK_FILES:
        text = f.read_text(encoding="utf-8")
        assert "Invoke is NOT available on `bedrock-mantle`" in text or (
            "Invoke" in text and "mantle" in text.lower()
        ), f"{f}: missing the mantle-never-supports-Invoke correction (Finding 3)"
