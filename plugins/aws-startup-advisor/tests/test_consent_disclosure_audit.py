"""Tests for `scripts/consent-disclosure-audit.py`.

Builds throwaway `discover-*-api.md` fixtures under a scratch plugin tree so
the committed skill files are never edited by the test run itself. Each test
constructs a minimal file with just the two sections the script reads: a
"## Step 2: Capture" section containing a Capture Endpoint Table, and a
blanket GET-only claim somewhere else in the file.

Run: ``uv run --with pytest python -m pytest plugins/aws-startup-advisor/tests/test_consent_disclosure_audit.py``
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "consent-disclosure-audit.py"
TARGET_REL = "skills/example-skill/references/phases/discover/discover-example-api.md"


def _load():
    spec = importlib.util.spec_from_file_location("consent_disclosure_audit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _run(plugin_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--plugin-root", str(plugin_root)],
        capture_output=True,
        text=True,
    )


def _write_fixture(tmp_path: Path, text: str) -> Path:
    root = tmp_path / "plugin"
    path = root / TARGET_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return root


# A minimal GET-only file: Step 0 claims GET-only, the table is all GET.
_GET_ONLY_FILE = """\
# Discover Phase: Example Usage API Discovery

## Security Contract (applies to every step)

1. Exact-endpoint allowlist, GET only. Call ONLY the endpoints below.

## Step 0: Consent Gate

This runs GET requests only, against a fixed list of usage endpoints.

## Step 2: Capture

**2c. Capture Endpoint Table.** Every row is `GET` against
`https://example.com/api/v1`.

| # | Endpoint (GET) | Purpose | Output file |
| - | -------------- | ------- | ------------ |
| 1 | `/usage`       | usage   | usage.json   |

## Scope Boundary

- Any non-GET method is forbidden.
"""

# Same file, but a POST row was added to the table and NO claim was updated —
# the exact shape of PR #436's round-1 bug, reproduced across all three
# sections it occurred in (Step 0, the table lead-in, Scope Boundary).
_UNQUALIFIED_POST_FILE = _GET_ONLY_FILE.replace(
    "| 1 | `/usage`       | usage   | usage.json   |",
    "| 1 | `/usage`       | usage   | usage.json   |\n"
    "| 2 | `POST /analytics/query` | per-model split | analytics.json |",
)

# The same POST addition, but every blanket claim was updated with an inline
# exception naming the method — the fix shape PR #436 converged on.
_QUALIFIED_POST_FILE = """\
# Discover Phase: Example Usage API Discovery

## Security Contract (applies to every step)

1. Exact-endpoint allowlist, GET + one scoped POST. All are `GET` EXCEPT
   `POST /analytics/query`, a read-only aggregate query.

## Step 0: Consent Gate

This runs GET requests against a fixed list of usage endpoints, plus one
read-only POST to /analytics/query for an aggregate split.

## Step 2: Capture

**2c. Capture Endpoint Table.** Row 1 is `GET` against
`https://example.com/api/v1`. Row 2 is `POST` to that same base, read-only.

| # | Endpoint                | Purpose          | Output file      |
| - | ------------------------ | ---------------- | ----------------- |
| 1 | `GET /usage`             | usage            | usage.json        |
| 2 | `POST /analytics/query`  | per-model split  | analytics.json    |

## Scope Boundary

- Any HTTP method other than GET EXCEPT the one read-only POST
  /analytics/query aggregate query is forbidden.
"""


def test_clean_get_only_file_passes(tmp_path: Path) -> None:
    root = _write_fixture(tmp_path, _GET_ONLY_FILE)
    result = _run(root)
    assert result.returncode == 0, result.stderr
    assert "consent-disclosure audit: OK" in result.stdout


def test_unqualified_post_claim_fails_in_every_section(tmp_path: Path) -> None:
    """Reproduces PR #436 round 1: a POST row with no exception anywhere.
    All three historically-affected sections (Security Contract lead-in via
    Step 0's consent text, the table's own lead-in, and Scope Boundary) must
    each be reported — not just the first one found."""
    root = _write_fixture(tmp_path, _UNQUALIFIED_POST_FILE)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "GET requests only" in result.stderr
    assert "Every row is `GET`" in result.stderr or "Every row is" in result.stderr
    assert "non-GET method" in result.stderr
    assert TARGET_REL in result.stderr


def test_qualified_post_claim_passes(tmp_path: Path) -> None:
    """The fix shape PR #436 converged on: every blanket claim rewritten with
    an inline exception naming the actual non-GET method/endpoint."""
    root = _write_fixture(tmp_path, _QUALIFIED_POST_FILE)
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_exception_naming_the_wrong_method_still_fails(tmp_path: Path) -> None:
    """An 'except' clause that doesn't name one of the file's actual non-GET
    methods must not silence a real gap (e.g. a stale exception left over
    from a different, now-removed endpoint)."""
    text = _GET_ONLY_FILE.replace(
        "This runs GET requests only, against a fixed list of usage endpoints.",
        "This runs GET requests only, against a fixed list of usage "
        "endpoints, except for an unrelated PATCH on a retired endpoint.",
    )
    text = text.replace(
        "| 1 | `/usage`       | usage   | usage.json   |",
        "| 1 | `/usage`       | usage   | usage.json   |\n"
        "| 2 | `POST /analytics/query` | per-model split | analytics.json |",
    )
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "the Capture Endpoint Table calls POST too" in result.stderr


def test_scope_outside_the_discover_api_file_pattern_is_ignored(tmp_path: Path) -> None:
    """A SKILL.md or any other file describing HTTP methods is out of scope
    — only discover-*-api.md sub-files make a consent promise this script
    checks."""
    root = tmp_path / "plugin"
    other = root / "skills" / "example-skill" / "SKILL.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text(
        "This flow runs GET requests only.\n\n"
        "| 1 | `POST /x` | y | z.json |\n",
        encoding="utf-8",
    )
    (
        root / "skills" / "example-skill" / "references" / "phases" / "discover"
    ).mkdir(parents=True, exist_ok=True)
    target = (
        root
        / "skills"
        / "example-skill"
        / "references"
        / "phases"
        / "discover"
        / "discover-example-api.md"
    )
    target.write_text(_GET_ONLY_FILE, encoding="utf-8")
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_no_matching_files_is_a_setup_error_not_a_silent_pass(tmp_path: Path) -> None:
    root = tmp_path / "plugin"
    (root / "skills").mkdir(parents=True)
    result = _run(root)
    assert result.returncode == 1
    assert "found ZERO files" in result.stderr


def test_methods_in_capture_section_reads_table_rows() -> None:
    mod = _load()
    methods, unrecognized = mod._methods_in_capture_section(_UNQUALIFIED_POST_FILE)
    assert methods == {"GET", "POST"}
    assert unrecognized is False


def test_methods_in_capture_section_ignores_scope_boundary_mentions() -> None:
    """A method named only in Scope Boundary/Error Handling prose (never in
    the Capture Endpoint Table itself) must not be read as a real call."""
    mod = _load()
    text = _GET_ONLY_FILE  # Scope Boundary mentions "non-GET" but never POST.
    methods, unrecognized = mod._methods_in_capture_section(text)
    assert methods == {"GET"}
    assert unrecognized is False


# The real Anthropic/Azure-OpenAI table shape: every row lists only a path,
# and the single shared method lives in the "Endpoint (METHOD, ...)" header
# cell, far enough past the words "Capture Endpoint Table" that a
# length-bounded slice would miss it (the real files put ~600-800 characters
# of prose in between). Regression fixture for the blocking review finding
# on this PR: a bounded slice silently returned no method for this shape,
# which was then treated as GET-only and skipped — so swapping GET for POST
# in the header, with every "GET requests only" sentence left in place,
# still exited 0.
_HEADER_METHOD_FILE = """\
# Discover Phase: Example Usage API Discovery

## Security Contract (applies to every step)

1. Exact-endpoint allowlist, GET only. Call ONLY the two endpoints below.

## Step 0: Consent Gate

This runs GET requests only, against a fixed list of usage/cost endpoints.

## Step 2: Capture

**2c. Capture Endpoint Table.** Row 1 is filtered to the selected workspaces
in a single call via repeated `workspace_ids[]=<id>` query parameters. Row 2
has no `workspace_ids[]` parameter at all — the endpoint has none — but it
does accept `group_by` as an array, so it runs in one single call with both
dimensions together. Each returned row already carries its own workspace_id
field plus the parsed description dimension. After the call returns, filter
the rows client-side to keep only those whose workspace_id is in the
selection — discard the rest before anything is written to the output file.
Unselected workspaces' rows pass through this one response but are never
stored past that filter, consistent with the Step 0 consent promise made
above. This padding exists so the header cell below lands well past the
400-character mark some bounded-slice implementations use.

| # | Endpoint ({method}, `https://api.example.com`) | Query parameters | Output file |
|---|---|---|---|
| 1 | `/v1/organizations/usage_report/messages` | `starting_at`, `bucket_width=1d` | usage-messages.json |
| 2 | `/v1/organizations/cost_report` | `starting_at`, `bucket_width=1d` | cost-report.json |

## Scope Boundary

- Any non-GET method is forbidden.
"""


def test_methods_in_capture_section_reads_header_cell_convention_far_from_the_label() -> None:
    """The 'Endpoint (METHOD, ...)' header-cell shape must be read regardless
    of how much prose sits between the words 'Capture Endpoint Table' and the
    header row — no fixed-length slice."""
    mod = _load()
    text = _HEADER_METHOD_FILE.format(method="GET")
    methods, unrecognized = mod._methods_in_capture_section(text)
    assert methods == {"GET"}
    assert unrecognized is False


def test_header_cell_post_is_detected_even_far_from_the_label(tmp_path: Path) -> None:
    """The exact exploit from the blocking review finding: the table's own
    header cell says POST, but every blanket 'GET requests only' sentence
    was left unchanged. This must fail — not pass as if the file were
    GET-only."""
    root = _write_fixture(tmp_path, _HEADER_METHOD_FILE.format(method="POST"))
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "GET requests only" in result.stderr
    assert "non-GET method" in result.stderr


def test_committed_anthropic_and_azure_openai_files_have_their_method_detected() -> None:
    """Regression for the exact files named in the blocking review finding:
    both discover-anthropic-api.md copies and azure's discover-openai-api.md
    put their method in a header cell far past any fixed-length slice. Each
    must resolve to a non-empty, GET-only method set on the real committed
    files (not an empty set silently treated as GET-only)."""
    mod = _load()
    for rel in (
        "skills/gcp-to-aws/references/phases/discover/discover-anthropic-api.md",
        "skills/azure-to-aws/references/phases/discover/discover-anthropic-api.md",
        "skills/azure-to-aws/references/phases/discover/discover-openai-api.md",
    ):
        text = (PLUGIN_ROOT / rel).read_text(encoding="utf-8")
        methods, unrecognized = mod._methods_in_capture_section(text)
        assert methods == {"GET"}, f"{rel}: expected {{'GET'}}, got {methods!r}"
        assert unrecognized is False, rel


def test_all_six_committed_discovery_files_return_a_nonempty_method_set() -> None:
    """Every real discover-*-api.md file in this plugin must resolve to a
    non-empty method set — an empty read must never be silently treated as
    'this file is GET-only, nothing to check.'"""
    mod = _load()
    files = sorted(
        PLUGIN_ROOT.glob("skills/*/references/phases/discover/discover-*-api.md")
    )
    assert len(files) == 6, f"expected 6 discovery sub-files, found {len(files)}"
    for path in files:
        text = path.read_text(encoding="utf-8")
        methods, unrecognized = mod._methods_in_capture_section(text)
        assert methods, f"{path}: no HTTP method read (unrecognized={unrecognized})"
        assert unrecognized is False, path


def test_unrecognized_table_shape_fails_closed_instead_of_skipping(tmp_path: Path) -> None:
    """A Capture Endpoint Table whose shape matches neither the per-row nor
    the header-cell convention must fail the audit, not be treated as a
    GET-only file with nothing to check."""
    text = """\
## Step 2: Capture

**2c. Capture Endpoint Table.**

| # | Something unrecognized | Purpose |
| - | ----------------------- | ------- |
| 1 | mystery-cell            | x       |
"""
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "no HTTP method could be read" in result.stderr


def test_mutating_the_real_anthropic_header_to_post_is_caught(tmp_path: Path) -> None:
    """End-to-end reproduction of the blocking finding's exact mutation: copy
    the real committed Anthropic file, flip its header cell from GET to
    POST, change nothing else, and confirm the audit now fails instead of
    exiting 0."""
    rel = "skills/gcp-to-aws/references/phases/discover/discover-anthropic-api.md"
    real_text = (PLUGIN_ROOT / rel).read_text(encoding="utf-8")
    assert "Endpoint (GET, `https://api.anthropic.com`)" in real_text
    mutated = real_text.replace(
        "Endpoint (GET, `https://api.anthropic.com`)",
        "Endpoint (POST, `https://api.anthropic.com`)",
    )
    root = _write_fixture(tmp_path, mutated)
    # _write_fixture writes to a generic example path; move it to match the
    # real relative path so the fixture's own section-detection logic (which
    # doesn't care about the path) still exercises the real file's content.
    (root / TARGET_REL).write_text(mutated, encoding="utf-8")
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "GET requests only" in result.stderr or "non-GET" in result.stderr


def test_soft_wrapped_claim_across_two_lines_is_caught(tmp_path: Path) -> None:
    """Regression for the Markdown-soft-wrap finding: 'This runs GET
    requests' and 'only.' on the next line render as one sentence and must
    be read as one claim, not two unmatched fragments."""
    text = _UNQUALIFIED_POST_FILE.replace(
        "This runs GET requests only, against a fixed list of usage endpoints.",
        "This runs GET requests\nonly, against a fixed list of usage endpoints.",
    )
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "GET requests" in result.stderr


def test_soft_wrapped_exception_still_qualifies_the_claim(tmp_path: Path) -> None:
    """The wrapped counterpart must still pass: a claim AND its exception,
    both soft-wrapped, in the same logical block."""
    text = _QUALIFIED_POST_FILE.replace(
        "This runs GET requests against a fixed list of usage endpoints, plus one\n"
        "read-only POST to /analytics/query for an aggregate split.",
        "This runs GET requests against a fixed list of usage\nendpoints, plus one "
        "read-only POST to /analytics/query\nfor an aggregate split.",
    )
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_adjacent_bullet_exception_does_not_qualify_a_different_bullet(tmp_path: Path) -> None:
    """Regression for the list-item finding: two adjacent bullets with no
    blank line between them must stay separate logical blocks, so the
    second bullet's exception cannot silence the first bullet's unqualified
    claim."""
    text = _UNQUALIFIED_POST_FILE.replace(
        "This runs GET requests only, against a fixed list of usage endpoints.",
        "- This runs GET requests only.\n"
        "- Forbidden: other calls, except POST /analytics/query.",
    )
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "This runs GET requests only." in result.stderr


def test_sibling_bullet_with_own_exception_still_passes(tmp_path: Path) -> None:
    """The same two-bullet shape, but the FIRST bullet carries its own
    exception rather than borrowing the second bullet's — must still pass."""
    text = """\
# Discover Phase: Example Usage API Discovery

## Step 0: Consent Gate

- This runs GET requests only, except POST /analytics/query.
- A second, unrelated bullet with no claim at all.

## Step 2: Capture

**2c. Capture Endpoint Table.**

| # | Endpoint | Purpose | Output file |
| - | -------- | ------- | ------------ |
| 1 | `GET /usage` | usage | usage.json |
| 2 | `POST /analytics/query` | per-model split | analytics.json |
"""
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 0, result.stderr


_GET_POST_PATCH_TABLE = """\

## Step 2: Capture

**2c. Capture Endpoint Table.**

| # | Endpoint | Purpose | Output file |
| - | -------- | ------- | ------------ |
| 1 | `GET /usage` | usage | usage.json |
| 2 | `POST /analytics/query` | per-model split | analytics.json |
| 3 | `PATCH /settings` | update settings | settings.json |
"""


def test_exception_naming_only_one_of_two_undisclosed_methods_still_fails(tmp_path: Path) -> None:
    """Regression for the multi-method finding: a table calling GET, POST,
    and PATCH, with a claim excepting only POST, must still fail on the
    undisclosed PATCH."""
    text = (
        "# Discover Phase: Example Usage API Discovery\n\n"
        "## Step 0: Consent Gate\n\n"
        "This runs GET requests only, except POST /analytics/query, against a "
        "fixed list of usage endpoints.\n"
        + _GET_POST_PATCH_TABLE
    )
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "PATCH" in result.stderr


def test_exception_naming_every_undisclosed_method_passes(tmp_path: Path) -> None:
    """The same GET/POST/PATCH table, but the claim excepts both non-GET
    methods — must pass."""
    text = (
        "# Discover Phase: Example Usage API Discovery\n\n"
        "## Step 0: Consent Gate\n\n"
        "This runs GET requests only, except POST /analytics/query and PATCH "
        "/settings, against a fixed list of usage endpoints.\n"
        + _GET_POST_PATCH_TABLE
    )
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_unreadable_file_fails_closed_instead_of_being_skipped(tmp_path: Path) -> None:
    """Regression for the unreadable-input finding: a file that can't be
    decoded as UTF-8 must be reported as a failure (and never counted among
    'checked' files), not silently skipped as if it had passed."""
    root = _write_fixture(tmp_path, _UNQUALIFIED_POST_FILE)
    (root / TARGET_REL).write_bytes(
        _UNQUALIFIED_POST_FILE.encode("utf-8") + b"\xff"
    )
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "could not read file" in result.stderr
    assert "OK (1 discovery sub-file(s) checked)" not in result.stdout


def test_prohibited_example_in_prose_is_not_read_as_a_real_call(tmp_path: Path) -> None:
    """Regression for the prohibited-example finding: a 'Never call `POST
    /v1/messages`' counter-example sitting right before a GET-only table
    must not be read as a real non-GET call. The GET-only claim must still
    pass, since the table itself declares only GET."""
    text = """\
# Discover Phase: Example Usage API Discovery

## Step 0: Consent Gate

This runs GET requests only, against a fixed list of usage endpoints.

## Step 2: Capture

- Never call `POST /v1/messages`; only the usage-report endpoints below are
  allowed.

**2c. Capture Endpoint Table.**

| # | Endpoint (GET) | Purpose | Output file |
| - | --------------- | ------- | ------------ |
| 1 | `/usage`        | usage   | usage.json   |
"""
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_prohibited_example_outside_step_2_is_also_ignored(tmp_path: Path) -> None:
    """The same prohibition note, stated outside Step 2 entirely (e.g. a
    Security Contract bullet), must likewise never be read as a call."""
    text = """\
# Discover Phase: Example Usage API Discovery

## Security Contract (applies to every step)

- Never call `POST /v1/messages`; only the usage-report endpoints below are
  allowed.

## Step 0: Consent Gate

This runs GET requests only, against a fixed list of usage endpoints.

## Step 2: Capture

**2c. Capture Endpoint Table.**

| # | Endpoint (GET) | Purpose | Output file |
| - | --------------- | ------- | ------------ |
| 1 | `/usage`        | usage   | usage.json   |
"""
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_real_post_row_is_still_caught_despite_prose_scoping(tmp_path: Path) -> None:
    """The table-row scoping fix must not blind the script to a REAL non-GET
    row — only free-form Step 2 prose (lead-in sentences, notes, prohibited
    examples) is excluded from method extraction, not the table itself."""
    root = _write_fixture(tmp_path, _UNQUALIFIED_POST_FILE)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "POST" in result.stderr


def test_inline_code_wrapped_method_in_existing_claim_is_still_caught(tmp_path: Path) -> None:
    """Regression for the inline-code-formatting finding: 'This runs `GET`
    requests only.' (method wrapped in backticks, as this plugin's prose
    already does) must be read the same as the unwrapped phrasing."""
    text = _UNQUALIFIED_POST_FILE.replace(
        "This runs GET requests only, against a fixed list of usage endpoints.",
        "This runs `GET` requests only, against a fixed list of usage endpoints.",
    )
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "GET` requests only" in result.stderr or "GET requests only" in result.stderr


def test_inline_code_wrapped_claim_variants_are_all_caught(tmp_path: Path) -> None:
    """The other blanket-claim phrasings must also recognize an inline-code
    wrapped GET: '`GET` only' and 'every row is `GET`'."""
    for claim in ("This flow calls `GET` only.", "Every row is `GET` against the base URL."):
        text = _UNQUALIFIED_POST_FILE.replace(
            "This runs GET requests only, against a fixed list of usage endpoints.",
            claim,
        )
        root = _write_fixture(tmp_path, text)
        result = _run(root)
        assert result.returncode == 1, (claim, result.stdout)


def test_plain_unwrapped_claim_variants_still_pass_when_qualified(tmp_path: Path) -> None:
    """Sanity check the inline-code pattern change didn't break the
    unwrapped spelling: a properly qualified unwrapped claim still passes."""
    root = _write_fixture(tmp_path, _QUALIFIED_POST_FILE)
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_negated_exception_marker_does_not_falsely_qualify_the_claim(tmp_path: Path) -> None:
    """Regression for the negated-marker finding: 'without exception; POST
    and PATCH are forbidden' contains the word 'exception' but grants none —
    it must not satisfy the exception check and silence a real gap."""
    text = """\
# Discover Phase: Example Usage API Discovery

## Step 0: Consent Gate

This runs GET requests only, without exception; POST and PATCH are
forbidden.
""" + _GET_POST_PATCH_TABLE
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout


def test_method_name_hiding_inside_an_unrelated_word_does_not_qualify(tmp_path: Path) -> None:
    """Regression for the substring finding: 'except POST /analytics/dispatch'
    must not silence an undisclosed PATCH just because the path 'dispatch'
    contains the letters 'patch'."""
    text = (
        "# Discover Phase: Example Usage API Discovery\n\n"
        "## Step 0: Consent Gate\n\n"
        "This runs GET requests only, except POST /analytics/dispatch.\n"
        + _GET_POST_PATCH_TABLE
    )
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "PATCH" in result.stderr


def test_method_name_hiding_inside_an_unrelated_word_in_output_does_not_qualify(
    tmp_path: Path,
) -> None:
    """The PUT counterpart: a sentence containing 'output' must not satisfy
    PUT merely because 'output' contains the letters 'put'."""
    text = (
        "# Discover Phase: Example Usage API Discovery\n\n"
        "## Step 0: Consent Gate\n\n"
        "This runs GET requests only, except POST /analytics/query; save "
        "the output locally.\n"
        + _GET_POST_PATCH_TABLE.replace(
            "| 3 | `PATCH /settings` | update settings | settings.json |\n",
            "| 3 | `PUT /settings` | update settings | settings.json |\n",
        )
    )
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "PUT" in result.stderr


def test_method_named_only_in_a_separate_denial_sentence_does_not_qualify(
    tmp_path: Path,
) -> None:
    """Regression: 'This runs GET requests only, except POST /query. PATCH
    requests are forbidden.' must still fail — PATCH is named only in a
    separate, denying sentence, not in the affirmative exception clause that
    grants POST. A method must be named in the SAME exception sentence to
    count as disclosed."""
    text = """\
# Discover Phase: Example Usage API Discovery

## Step 0: Consent Gate

This runs GET requests only, except POST /query. PATCH requests are
forbidden.

## Step 2: Capture

**2c. Capture Endpoint Table.**

| # | Endpoint | Purpose | Output file |
| - | -------- | ------- | ------------ |
| 1 | `GET /usage` | usage | usage.json |
| 2 | `POST /query` | q | q.json |
| 3 | `PATCH /settings` | update settings | settings.json |
"""
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert "PATCH" in result.stderr


def test_both_methods_named_in_the_same_exception_sentence_passes(tmp_path: Path) -> None:
    """The same table, but POST and PATCH are both named within the single
    exception sentence — must pass."""
    text = """\
# Discover Phase: Example Usage API Discovery

## Step 0: Consent Gate

This runs GET requests only, except POST /query and PATCH /settings.

## Step 2: Capture

**2c. Capture Endpoint Table.**

| # | Endpoint | Purpose | Output file |
| - | -------- | ------- | ------------ |
| 1 | `GET /usage` | usage | usage.json |
| 2 | `POST /query` | q | q.json |
| 3 | `PATCH /settings` | update settings | settings.json |
"""
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_prohibited_example_in_a_get_rows_own_cell_is_not_a_real_call(tmp_path: Path) -> None:
    """Regression: a prohibited-example counter-example sitting inside a GET
    row's own Purpose cell (not a separate prose line, as the earlier fix
    covered) must not be read as a second method on that row."""
    text = """\
# Discover Phase: Example Usage API Discovery

## Step 0: Consent Gate

This runs GET requests only, against a fixed list of usage endpoints.

## Step 2: Capture

**2c. Capture Endpoint Table.**

| # | Endpoint (GET) | Purpose | Output file |
| - | --------------- | ------- | ------------ |
| 1 | `/usage` | Never call `POST /v1/messages` here | usage.json |
"""
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_header_looking_prose_outside_the_real_header_row_is_ignored(tmp_path: Path) -> None:
    """Regression: 'Endpoint (POST)' appearing in ordinary Step 2 prose,
    never inside the table's own header row, must not be read as the
    table's declared method."""
    text = """\
# Discover Phase: Example Usage API Discovery

## Step 0: Consent Gate

This runs GET requests only, against a fixed list of usage endpoints.

## Step 2: Capture

**2c. Capture Endpoint Table.** Note: Endpoint (POST) is never used here,
only GET.

| # | Endpoint (GET) | Purpose | Output file |
| - | --------------- | ------- | ------------ |
| 1 | `/usage` | usage | usage.json |
"""
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 0, result.stderr


def test_real_post_header_row_is_still_caught_after_column_scoping(tmp_path: Path) -> None:
    """The column-scoping fix must not blind the script to a real header-cell
    method declaration — only prose outside the actual header row is
    excluded."""
    rel = "skills/gcp-to-aws/references/phases/discover/discover-anthropic-api.md"
    real_text = (PLUGIN_ROOT / rel).read_text(encoding="utf-8")
    mutated = real_text.replace(
        "Endpoint (GET, `https://api.anthropic.com`)",
        "Endpoint (POST, `https://api.anthropic.com`)",
    )
    root = _write_fixture(tmp_path, mutated)
    (root / TARGET_REL).write_text(mutated, encoding="utf-8")
    result = _run(root)
    assert result.returncode == 1, result.stdout


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
def test_head_and_options_rows_are_recognized_as_non_get(tmp_path: Path, method: str) -> None:
    """Regression: HEAD and OPTIONS rows must be counted as non-GET methods
    requiring disclosure, not silently dropped from the recognized-method
    vocabulary (which previously let a GET row mask an unrecognized
    HEAD/OPTIONS row and report the table as GET-only)."""
    text = f"""\
# Discover Phase: Example Usage API Discovery

## Step 0: Consent Gate

This runs GET requests only.

## Step 2: Capture

**2c. Capture Endpoint Table.**

| # | Endpoint | Purpose | Output file |
| - | -------- | ------- | ------------ |
| 1 | `GET /usage` | usage | usage.json |
| 2 | `{method} /usage` | check | none |
"""
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout
    assert method in result.stderr


def test_uppercase_except_marker_still_qualifies_the_claim(tmp_path: Path) -> None:
    """Regression for the case-sensitivity gap introduced by the whole-word
    fix: 'EXCEPT' and 'Except' must still grant an exception, matching the
    script's own documentation which spells it in uppercase."""
    for marker in ("EXCEPT", "Except"):
        text = f"""\
# Discover Phase: Example Usage API Discovery

## Step 0: Consent Gate

This runs GET requests only, {marker} POST /query.

## Step 2: Capture

**2c. Capture Endpoint Table.**

| # | Endpoint | Purpose | Output file |
| - | -------- | ------- | ------------ |
| 1 | `GET /usage` | usage | usage.json |
| 2 | `POST /query` | q | q.json |
"""
        root = _write_fixture(tmp_path, text)
        result = _run(root)
        assert result.returncode == 0, (marker, result.stderr)


def test_negated_marker_still_fails_regardless_of_case(tmp_path: Path) -> None:
    """The case-insensitivity fix must not reopen the earlier negated-marker
    gap: 'WITHOUT EXCEPTION' must still fail to grant one, in any case."""
    text = """\
# Discover Phase: Example Usage API Discovery

## Step 0: Consent Gate

This runs GET requests only, WITHOUT EXCEPTION; POST is forbidden.

## Step 2: Capture

**2c. Capture Endpoint Table.**

| # | Endpoint | Purpose | Output file |
| - | -------- | ------- | ------------ |
| 1 | `GET /usage` | usage | usage.json |
| 2 | `POST /query` | q | q.json |
"""
    root = _write_fixture(tmp_path, text)
    result = _run(root)
    assert result.returncode == 1, result.stdout


def test_real_plugin_discovery_files_pass_on_main() -> None:
    """Smoke test against the actual committed discover-*-api.md files (not
    a scratch fixture) — this is the gate's real-world assertion: whatever
    ships in this plugin today must already be internally consistent."""
    result = _run(PLUGIN_ROOT)
    assert result.returncode == 0, result.stderr
    assert "consent-disclosure audit: OK" in result.stdout
