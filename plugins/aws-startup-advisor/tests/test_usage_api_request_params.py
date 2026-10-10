"""Guard: usage-API request parameters match each provider's documented limits.

PR #425 Cursor review findings 1 and 2 (reproduced in
.agents/tasks/pr425-cursor-fixes/reproductions.md):

- Finding 2: Azure's discover-openai-api.md requested `limit=180` (the Costs
  endpoint's own max) on every usage endpoint row too, even though OpenAI's
  usage endpoints cap `bucket_width=1d&limit` at 31. A `limit=180` usage
  request is rejected outright, which would trigger an all-usage-failed exit.
- Finding 1: both discover-anthropic-api.md copies' cost_report capture
  grouped only by `description`, with no way to break a multi-workspace
  selection's cost back out per workspace, and the consent block's "Never
  captured ... data from workspaces you don't select" bullet did not
  disclose that the Step 2b probe call reads an org-wide, per-workspace
  total before workspace selection happens.

These are documentation-contract checks (string/regex assertions against the
markdown contract), matching this suite's existing pattern.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

AZURE_OPENAI_FILE = (
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-openai-api.md"
)

ANTHROPIC_FILES = [
    PLUGIN_ROOT
    / "skills"
    / "gcp-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-anthropic-api.md",
    PLUGIN_ROOT
    / "skills"
    / "azure-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-anthropic-api.md",
]

USAGE_ROW_PATTERN = re.compile(
    r"/v1/organization/usage/\S+.*?limit=(\d+)", re.MULTILINE
)
COSTS_ROW_PATTERN = re.compile(r"/v1/organization/costs.*?limit=(\d+)")


def test_azure_openai_usage_rows_do_not_request_limit_180() -> None:
    text = AZURE_OPENAI_FILE.read_text(encoding="utf-8")
    usage_limits = USAGE_ROW_PATTERN.findall(text)
    assert usage_limits, "expected to find usage-endpoint rows with a limit= parameter"
    for limit in usage_limits:
        assert limit != "180", (
            "a usage-endpoint row still requests limit=180 (OpenAI's usage "
            "endpoints cap bucket_width=1d&limit at 31) — see finding 2"
        )
        assert limit == "31", f"usage-endpoint row requests limit={limit}, expected limit=31"


def test_azure_openai_costs_row_keeps_limit_180() -> None:
    text = AZURE_OPENAI_FILE.read_text(encoding="utf-8")
    costs_limits = COSTS_ROW_PATTERN.findall(text)
    assert costs_limits, "expected to find a costs-endpoint row with a limit= parameter"
    assert all(limit == "180" for limit in costs_limits), (
        "the Costs endpoint row's limit=180 should be unchanged — only usage "
        "rows (2-6) are capped at 31"
    )


def test_azure_openai_has_copy_paste_trap_callout() -> None:
    text = AZURE_OPENAI_FILE.read_text(encoding="utf-8")
    assert "copy-paste trap" in text, (
        "expected a callout warning against copying the Costs row's limit=180 "
        "onto a usage row, mirroring discover-anthropic-api.md's existing callout"
    )


def test_anthropic_cost_report_carries_workspace_id_per_row() -> None:
    for f in ANTHROPIC_FILES:
        text = f.read_text(encoding="utf-8")
        assert "workspace_id" in text.split("## Step 3", 1)[-1].split("## Step 4", 1)[0], (
            f"{f}: Step 3's costs_by_description[] schema no longer carries "
            f"workspace_id per row — see finding 1"
        )
        assert '"workspace_id": "wrkspc_abc"' in text, (
            f"{f}: the costs_by_description[] example row is missing workspace_id"
        )


def test_anthropic_cost_report_uses_single_call_with_compound_group_by() -> None:
    for f in ANTHROPIC_FILES:
        text = f.read_text(encoding="utf-8")
        step2 = text.split("## Step 2:", 1)[-1].split("## Step 3", 1)[0]
        normalized = re.sub(r"\s+", " ", step2).lower()
        assert "group_by[]=workspace_id&group_by[]=description" in normalized, (
            f"{f}: Step 2c no longer documents a single cost_report call "
            f"grouped by both workspace_id and description — see finding A "
            f"(PR 425 review 5475407077)"
        )
        # Row 2 (cost_report) must not carry workspace_ids[] — the endpoint has
        # no such parameter. Row 1 (usage_report/messages) legitimately keeps
        # workspace_ids[], so scope the "must not contain" check to the
        # cost_report table row specifically, not the whole Step 2 section.
        table_row_match = re.search(
            r"\|\s*2\s*\|\s*`/v1/organizations/cost_report`.*?\|\s*$",
            step2,
            re.MULTILINE,
        )
        assert table_row_match, f"{f}: could not find the cost_report table row"
        assert "workspace_ids[]=" not in table_row_match.group(0), (
            f"{f}: the cost_report table row still requests workspace_ids[]=, "
            f"but that endpoint has no such parameter — see finding A"
        )


def test_anthropic_probe_uses_bracket_group_by() -> None:
    """The Step 2b probe call must use `group_by[]=workspace_id` (bracket array
    syntax), not the bare scalar `group_by=workspace_id` — a live Anthropic
    API call with the scalar form returns HTTP 400 'Invalid parameter
    group_by. Use group_by[] for array parameters.'"""
    for f in ANTHROPIC_FILES:
        text = f.read_text(encoding="utf-8")
        step2 = text.split("## Step 2:", 1)[-1].split("## Step 3", 1)[0]
        assert "group_by=workspace_id" not in step2, (
            f"{f}: Step 2b probe still uses the bare scalar `group_by=workspace_id`"
            f" — must be `group_by[]=workspace_id`"
        )
        assert "group_by[]=workspace_id&limit=31" in step2, (
            f"{f}: Step 2b probe is missing the bracket-array `group_by[]=workspace_id` form"
        )


def test_anthropic_usage_messages_row_uses_bracket_group_by() -> None:
    """The Capture Endpoint Table's usage_report/messages row (Row 1) must
    group by model and service_tier using the bracket-array form, not the
    comma-separated scalar form `group_by=model,service_tier`."""
    for f in ANTHROPIC_FILES:
        text = f.read_text(encoding="utf-8")
        step2 = text.split("## Step 2:", 1)[-1].split("## Step 3", 1)[0]
        assert "group_by=model,service_tier" not in step2, (
            f"{f}: usage_report/messages row still uses the comma-separated "
            f"scalar form `group_by=model,service_tier`"
        )
        assert "group_by[]=model&group_by[]=service_tier" in step2, (
            f"{f}: usage_report/messages row is missing the bracket-array "
            f"`group_by[]=model&group_by[]=service_tier` form"
        )


def test_anthropic_consent_block_discloses_preselection_probe() -> None:
    for f in ANTHROPIC_FILES:
        text = f.read_text(encoding="utf-8")
        step0 = text.split("## Step 0:", 1)[-1].split("## Step 1:", 1)[0]
        assert "Never captured" in step0, f"{f}: Step 0 consent block missing"
        assert "Step 2b" in step0, (
            f"{f}: Step 0 consent block's 'Never captured' bullet does not "
            f"disclose the Step 2b pre-selection probe exception — see finding 1"
        )
