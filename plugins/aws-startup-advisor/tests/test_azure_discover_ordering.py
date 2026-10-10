"""Guard: Azure's usage-API consent/capture steps run after assembly.

PR #425 Cursor review finding 3 (reproduced in
.agents/tasks/pr425-cursor-fixes/reproductions.md): the three usage-API
"consent + capture" sections used to be nested under "Pre-dispatch
main-window action", which runs BEFORE '## Step: Run the phase' (where
fragments and discover-assemble.md actually execute, and where
ai-workload-profile.json is written for a from-scratch migration). On a
fresh run, the OpenAI/OpenRouter/Anthropic trigger conditions that key off
ai-workload-profile.json would evaluate against a file that doesn't exist
yet.

This test guards against that ordering bug recurring: it asserts the three
usage-API headings appear, in document order, after the
'## Step: Run the phase' heading and after the point where
discover-assemble.md is referenced within it.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

DISCOVER_FILE = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover.md"
)

USAGE_HEADINGS = [
    "OpenAI usage-API consent + capture",
    "OpenRouter usage-API consent + capture",
    "Anthropic usage-API consent + capture",
]


def test_usage_api_sections_run_after_phase_execution_step() -> None:
    text = DISCOVER_FILE.read_text(encoding="utf-8")

    run_phase_idx = text.index("## Step: Run the phase")
    assert run_phase_idx != -1

    assemble_ref_idx = text.index("discover-assemble.md", run_phase_idx)
    assert assemble_ref_idx > run_phase_idx, (
        "discover-assemble.md reference not found after '## Step: Run the phase'"
    )

    for heading in USAGE_HEADINGS:
        heading_idx = text.index(heading, assemble_ref_idx)
        assert heading_idx > assemble_ref_idx, (
            f"'{heading}' appears before the discover-assemble.md execution "
            f"step inside '## Step: Run the phase' — usage-API capture must "
            f"run after fragments/assembly, not before (see finding 3)"
        )


def test_usage_api_sections_no_longer_under_pre_dispatch_heading() -> None:
    text = DISCOVER_FILE.read_text(encoding="utf-8")
    pre_dispatch_idx = text.index(
        "## Pre-dispatch main-window action (live `az` consent + capture)"
    )
    orientation_idx = text.index("## Orientation")

    pre_dispatch_section = text[pre_dispatch_idx:orientation_idx]
    for heading in USAGE_HEADINGS:
        assert heading not in pre_dispatch_section, (
            f"'{heading}' is still nested under the pre-dispatch main-window "
            f"action section — it must run after assembly instead (finding 3)"
        )


def test_init_paragraph_no_longer_claims_already_done_by_pre_dispatch() -> None:
    text = DISCOVER_FILE.read_text(encoding="utf-8")
    run_phase_idx = text.index("## Step: Run the phase")
    output_files_idx = text.index("## Output Files")
    run_phase_section = text[run_phase_idx:output_files_idx]

    assert "already\n   done" not in run_phase_section and "**already\n   done**" not in run_phase_section, (
        "the _init paragraph in 'Step: Run the phase' still claims _init was "
        "already done by the pre-dispatch action — that claim is only true "
        "while usage-API capture precedes _init's normal position, which is "
        "no longer the case now that usage-API capture runs after assembly"
    )
