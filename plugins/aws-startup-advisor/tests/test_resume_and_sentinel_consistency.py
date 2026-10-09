"""Guard: Discover resume/schema consistency (PR #425 findings 7, 8).

Finding 7: both gcp-to-aws's and azure-to-aws's discover.md gated Anthropic
resume/postcondition checks on bare manifest.json *existence*, not on whether
any capture row actually succeeded — unlike the OpenRouter sibling in the same
files, which already checks captures[]/activity status. These checks anchor
on the row-status language so a future edit can't silently regress back to
existence-only gating.

Finding 8: Anthropic's Step 4.4b sentinel-workload absence check was narrower
than Azure's — it only looked for a workload row with sdk_method: "usage_api"
specifically, so a model already covered by a real code workload under a
different sdk_method would still get a redundant usage_api sentinel. Azure's
discover-openai-api.md had no equivalent workload-row append at all. This
guards that both are now aligned.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

GCP_DISCOVER = PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "discover" / "discover.md"
AZURE_DISCOVER = PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "discover" / "discover.md"
GCP_ANTHROPIC = PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "discover" / "discover-anthropic-api.md"
AZURE_ANTHROPIC = PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "discover" / "discover-anthropic-api.md"
AZURE_OPENAI = PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "discover" / "discover-openai-api.md"


def test_gcp_discover_checks_anthropic_row_status_not_bare_existence() -> None:
    text = GCP_DISCOVER.read_text(encoding="utf-8")
    assert "status: \"ok\"" in text or "status == \"ok\"" in text, (
        "gcp-to-aws discover.md no longer checks captures[] row status for "
        "the Anthropic resume/route-output-gate (regressed to bare manifest "
        "existence)"
    )
    assert "retry_pending" in text, (
        "gcp-to-aws discover.md lost the retry_pending carve-out reference "
        "for the Anthropic resume check"
    )


def test_azure_discover_checks_anthropic_row_status_not_bare_existence() -> None:
    text = AZURE_DISCOVER.read_text(encoding="utf-8")
    assert "status: \"ok\"" in text, (
        "azure-to-aws discover.md no longer checks captures[] row status for "
        "the Anthropic resume gate (regressed to bare manifest existence)"
    )
    assert "retry_pending" in text, (
        "azure-to-aws discover.md lost the retry_pending carve-out reference "
        "for the Anthropic resume check"
    )
    # The _postconditions assert for Anthropic must no longer rely purely on
    # the generic templated OpenAI-mirroring text without the row-status caveat.
    assert "captures[] rows are ALL" in text, (
        "azure-to-aws discover.md's Anthropic postcondition no longer "
        "distinguishes an all-failed manifest from a successful capture"
    )


def test_azure_openai_discover_now_appends_workload_row() -> None:
    text = AZURE_OPENAI.read_text(encoding="utf-8")
    assert "workloads[]" in text, (
        "azure-to-aws discover-openai-api.md Step 4 still has no workloads[] "
        "append for usage-only models (finding 8 regression)"
    )
    assert "Workload row" in text, (
        "azure-to-aws discover-openai-api.md Step 4 is missing the "
        "'Workload row' sub-step mirroring Anthropic's corrected 4b logic"
    )


def test_anthropic_sentinel_condition_has_no_sdk_method_qualifier() -> None:
    for f in (GCP_ANTHROPIC, AZURE_ANTHROPIC):
        text = f.read_text(encoding="utf-8")
        assert 'AND `sdk_method: "usage_api"`' not in text, (
            f"{f.name}: Step 4.4b absence check still carries the "
            f"sdk_method qualifier (finding 8 regression) — it must match "
            f"it (any sdk_method)"
        )
        assert "any `sdk_method`" in text, (
            f"{f.name}: Step 4.4b absence check no longer documents that "
            f"it matches model_id under any sdk_method"
        )
