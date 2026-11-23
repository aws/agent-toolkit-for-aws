"""Guard: GCP Generate's Mantle dispatch path is self-consistent.

PR #431 reviewer (leon1418) finding 2: gcp-to-aws `generate-artifacts-ai.md`'s
Mantle dispatch (`migration_path == mantle_openai_responses`) carried three
sub-bugs:

(a) Step 2's harness unconditionally did `from provider_adapter import
    get_provider`, but the Mantle path skips Step 1 and emits no
    `provider_adapter` module — a broken import on that path.
(b) Step 1M printed a Mantle base URL ending in a bare `/v1`; the proprietary
    GPT models that route through Mantle require `/openai/v1` (a bare `/v1`
    404s), per `references/vendored/ai/openai-on-bedrock.md`.
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

AZURE_GENERATE = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "generate"
    / "generate-artifacts-ai.md"
)


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
    # Runtime-default: Mantle is no longer presented as Azure's primary path.
    assert "Mantle is the PRIMARY path" not in text, (
        "Azure generate-artifacts-ai.md still calls Mantle the PRIMARY path; "
        "bedrock-runtime CRIS is the default and Mantle is selector-gated"
    )
    assert "bedrock-runtime" in text
