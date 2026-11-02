"""Guard: GCP Generate's Mantle dispatch path is self-consistent.

PR #431 reviewer (leon1418) finding 2: gcp-to-aws `generate-artifacts-ai.md`'s
Mantle dispatch (`migration_path == mantle_openai_responses`) carried three
sub-bugs:

(a) Step 2's harness unconditionally did `from provider_adapter import
    get_provider`, but the Mantle path skips Step 1 and emits no
    `provider_adapter` module — a broken import on that path.
(b) Step 1M printed a Mantle base URL ending in a bare `/v1`; the proprietary
    GPT models that route through Mantle require `/openai/v1` (a bare `/v1`
    404s), per `references/shared/openai-on-bedrock.md`.
(c) Step 3 granted `bedrock:InvokeModel` and verified via a `converse` call, but
    `bedrock:InvokeModel` does not authorize Mantle calls and the Mantle models
    are reached via Responses / Chat Completions, not Converse.

Azure's `generate-artifacts-ai.md` was already correct; a parity assertion guards
it against regression. These checks anchor on stable substrings so benign
rewording does not trip them.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

GCP_GENERATE = (
    PLUGIN_ROOT
    / "skills"
    / "gcp-to-aws"
    / "references"
    / "phases"
    / "generate"
    / "generate-artifacts-ai.md"
)
AZURE_GENERATE = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "generate"
    / "generate-artifacts-ai.md"
)


def test_step1m_base_url_uses_openai_v1_with_caveat() -> None:
    # (b) Mantle base path is /openai/v1, and the "/v1 404s" caveat is present.
    text = GCP_GENERATE.read_text(encoding="utf-8")
    assert "bedrock-mantle.{region}.api.aws/openai/v1" in text, (
        "Step 1M's Mantle OPENAI_BASE_URL is not /openai/v1 (finding 2b)"
    )
    assert "bedrock-mantle.{region}.api.aws/v1`" not in text, (
        "Step 1M still prints a bare Mantle /v1 base URL (finding 2b)"
    )
    assert "404" in text, (
        "Step 1M no longer carries the 'bare /v1 404s' caveat (finding 2b)"
    )


def test_step2_harness_import_conditional_on_mantle_path() -> None:
    # (a) The provider_adapter import must be scoped to the non-Mantle paths, and
    # the Mantle path must have a no-adapter client-setup branch.
    text = GCP_GENERATE.read_text(encoding="utf-8")
    harness_idx = text.index("## Step 2: Generate Test Comparison Harness")
    step3_idx = text.index("## Step 3: Generate Bedrock Setup Script")
    harness = text[harness_idx:step3_idx]

    assert "from provider_adapter import get_provider" in harness, (
        "Step 2 no longer mentions the provider_adapter import for the "
        "non-Mantle paths that do emit the adapter (finding 2a)"
    )
    # The import must now be conditional, not unconditional: the Mantle path has
    # its own no-adapter client-setup branch.
    assert "Mantle / runtime CRIS" in harness and "do not import `provider_adapter`" in harness, (
        "Step 2 does not scope the provider_adapter import away from the Mantle "
        "path (finding 2a) — the Mantle path emits no adapter module"
    )
    assert "client.responses.create" in harness, (
        "Step 2's Mantle branch does not set up the OpenAI SDK Responses client "
        "in place of the omitted adapter (finding 2a)"
    )


def test_step3_mantle_iam_and_test_api_are_conditional() -> None:
    # (c) The Mantle path grants bedrock-mantle:* (not bedrock:InvokeModel) and
    # verifies via Responses/Chat Completions (not converse); the non-Mantle
    # paths retain bedrock:InvokeModel + converse.
    text = GCP_GENERATE.read_text(encoding="utf-8")
    step3_idx = text.index("## Step 3: Generate Bedrock Setup Script")
    step3b_idx = text.index("## Step 3B: Generate Gateway Configuration")
    step3 = text[step3_idx:step3b_idx]

    # Mantle IAM action present.
    assert "bedrock-mantle:CreateInference" in step3, (
        "Step 3's Mantle branch does not grant bedrock-mantle:CreateInference "
        "(finding 2c)"
    )
    assert "bedrock-mantle:CallWithBearerToken" in step3
    assert "project/*" in step3
    # Non-Mantle paths keep the runtime action.
    assert "bedrock:InvokeModel" in step3, (
        "Step 3 dropped bedrock:InvokeModel for the non-Mantle paths, which is "
        "wrong — those paths still need it (finding 2c)"
    )
    # Setup invokes the same selected client as the comparison harness.
    assert "Match inference permissions to the selected endpoint" in step3
    assert "test_comparison.py --target-only --quick" in step3
    assert "same selected API, model ID and region" in step3
    assert "A Mantle selection must never run a Converse probe" in step3
    assert "runtime selection must preserve its validated profile ID" in step3


def test_azure_generate_mantle_branch_still_correct() -> None:
    # Parity guard: Azure's generate file was already correct — keep it that way.
    text = AZURE_GENERATE.read_text(encoding="utf-8")
    assert "bedrock-mantle.{region}.api.aws/openai/v1" in text, (
        "Azure generate-artifacts-ai.md regressed off the /openai/v1 Mantle base "
        "path"
    )
    assert "bedrock-mantle:" in text, (
        "Azure generate-artifacts-ai.md regressed off the bedrock-mantle:* IAM "
        "action for the Mantle path"
    )
