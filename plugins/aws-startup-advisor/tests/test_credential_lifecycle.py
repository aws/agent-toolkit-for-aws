"""Guard: every terminal exit deletes the admin-key file, or carves out why not.

Finding 6 (PR425, SECURITY-SENSITIVE): the Anthropic usage-discovery sub-files
(both the gcp-to-aws and azure-to-aws copies) and the Azure OpenAI usage-
discovery sub-file only documented deleting their admin-key env file on the
Step 4 success path. Every terminal exit that happens before Step 4 — the
Anthropic organization-type fork, an all-rows-failed capture, and the
`KEY_INVALID_MID_RUN` abort — left the key file undeleted with no documented
reason, except that `KEY_INVALID_MID_RUN` legitimately needs the key to
survive for a resume.

This is a documentation-contract test (consistent with
test_decision_gate_wiring.py): it asserts on markdown content/structure, not
runtime execution. It enumerates the known exit branches and fails if a
future edit removes the deletion/carve-out language from any of them.

What this verifies: the DOCUMENTED CONTRACT an agent will follow now routes
every enumerated exit through deletion-or-carve-out, enforced automatically.
What this does NOT verify: no live Anthropic/OpenAI Admin API call was made
and no real file-deletion syscall was exercised — these are instruction files
for an agent, not executable code with a real HTTP client or filesystem
operation in this repo.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

ANTHROPIC_FILES = [
    PLUGIN_ROOT / "skills" / "gcp-to-aws" / "references" / "phases" / "discover" / "discover-anthropic-api.md",
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "discover" / "discover-anthropic-api.md",
]

AZURE_OPENAI_FILE = (
    PLUGIN_ROOT / "skills" / "azure-to-aws" / "references" / "phases" / "discover" / "discover-openai-api.md"
)

ALL_FILES = ANTHROPIC_FILES + [AZURE_OPENAI_FILE]


def test_manifest_schema_declares_retry_pending() -> None:
    for f in ALL_FILES:
        text = f.read_text(encoding="utf-8")
        assert '"retry_pending"' in text, (
            f"{f.name}: manifest.json schema no longer declares retry_pending"
        )


def test_key_invalid_mid_run_is_the_only_documented_retry_carve_out() -> None:
    for f in ALL_FILES:
        text = f.read_text(encoding="utf-8")
        assert "KEY_INVALID_MID_RUN" in text, f"{f.name}: missing KEY_INVALID_MID_RUN branch"
        assert "retry_pending: true" in text, (
            f"{f.name}: KEY_INVALID_MID_RUN branch no longer carves out "
            f"retry_pending: true as the documented reason to keep the key file"
        )
        assert "retry_pending: false" in text, (
            f"{f.name}: other terminal exits no longer explicitly set "
            f"retry_pending: false alongside their deletion instruction"
        )


def test_anthropic_org_type_fork_deletes_key_file() -> None:
    for f in ANTHROPIC_FILES:
        text = f.read_text(encoding="utf-8")
        idx = text.index("Org-type fork handling")
        branch = text[idx : idx + 600]
        assert ".anthropic-admin-env" in branch and "delete" in branch.lower(), (
            f"{f.name}: Enterprise-org-type-fork exit no longer deletes the "
            f"admin-key file"
        )


def test_anthropic_all_rows_failed_deletes_key_file() -> None:
    for f in ANTHROPIC_FILES:
        text = f.read_text(encoding="utf-8")
        idx = text.index("If EVERY row")
        branch = text[idx : idx + 200]
        assert ".anthropic-admin-env" in branch and "delete" in branch.lower(), (
            f"{f.name}: all-rows-failed exit no longer deletes the admin-key file"
        )


def test_anthropic_key_invalid_mid_run_keeps_key_file() -> None:
    for f in ANTHROPIC_FILES:
        text = f.read_text(encoding="utf-8")
        idx = text.index("abort the remaining calls")
        branch = text[idx : idx + 700]
        assert "retry_pending: true" in branch and "NOT delete" in branch, (
            f"{f.name}: KEY_INVALID_MID_RUN branch no longer documents keeping "
            f"the key file via retry_pending: true"
        )


def test_azure_openai_all_usage_failed_deletes_key_file() -> None:
    text = AZURE_OPENAI_FILE.read_text(encoding="utf-8")
    idx = text.index("If EVERY usage row")
    branch = text[idx : idx + 200]
    assert ".openai-admin-env" in branch and "delete" in branch.lower(), (
        "discover-openai-api.md: all-usage-failed exit no longer deletes the "
        "admin-key file"
    )


def test_azure_openai_key_invalid_mid_run_keeps_key_file() -> None:
    text = AZURE_OPENAI_FILE.read_text(encoding="utf-8")
    idx = text.index("abort the remaining calls")
    branch = text[idx : idx + 700]
    assert "retry_pending: true" in branch and "NOT delete" in branch, (
        "discover-openai-api.md: KEY_INVALID_MID_RUN branch no longer "
        "documents keeping the key file via retry_pending: true"
    )


def test_step4_success_path_deletion_language_is_unchanged() -> None:
    # This FEAT only adds deletion to non-success terminal paths plus the one
    # retry carve-out; the existing Step 4 "default, not optional" deletion
    # on the success path must stay exactly as documented.
    for f in ANTHROPIC_FILES:
        text = f.read_text(encoding="utf-8")
        assert "**Clean up (default, not optional):** delete" in text
        assert ".anthropic-admin-env` now" in text

    text = AZURE_OPENAI_FILE.read_text(encoding="utf-8")
    assert "**Clean up (default, not optional):** delete" in text
    assert ".openai-admin-env` now" in text
