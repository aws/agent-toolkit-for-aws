#!/usr/bin/env python3
"""Consent-disclosure drift lint for usage-API discovery sub-files.

Fails when a `discover-*-api.md` sub-file's Capture Endpoint Table calls a
non-`GET` HTTP method, but the file ALSO carries an unqualified "GET only"
style claim somewhere else that does not call out that method as an explicit
exception.

Why this exists: PR #436 added a read-only `POST /analytics/query` call to
`discover-openrouter-api.md` (both the gcp-to-aws and azure-to-aws copies).
The reviewer found the SAME contradiction reintroduced three separate times
in that one PR, in three different sections, over three review rounds:

  - Round 1: Step 0's consent text still said "This runs GET requests only."
  - Round 2 (after Step 0 was fixed): the Scope Boundary's FORBIDDEN bullet
    still banned "any non-GET method" with no exception.
  - Each fix only patched the one location flagged that round; the sibling
    location kept the stale blanket claim until the NEXT round caught it.

A consent promise that is accurate in one place and wrong in another is, from
the user's point of view, simply wrong: they read whichever one is in front
of them. This script makes the cost of adding a new non-GET capture endpoint
visible immediately — at authoring time, not three AI-review rounds later —
by checking every blanket GET-restriction claim in the file against what the
Capture Endpoint Table actually calls.

This is a textual contradiction check, not an HTTP conformance check: it does
not call any API. It reads two things out of each `discover-*-api.md` file:

  1. The real HTTP methods, from the Capture Endpoint Table (the "## Step 2:
     Capture" section): either a per-row `` `METHOD /path` `` cell, or the
     table's own "Endpoint (METHOD, ...)" header-column convention (the shape
     the Anthropic and Azure-OpenAI tables use, where every row lists only a
     path). If a table is present but neither shape is recognized, this is
     reported as a failure (an unrecognized table shape), never silently
     skipped as if the file were GET-only.
  2. Every blanket "GET only" / "non-GET" claim anywhere in the file (Security
     Contract, Step 0 consent copy, Scope Boundary FORBIDDEN bullets, or any
     other prose) via a fixed set of phrasings.

A claim is UNQUALIFIED (and so a failure) when the file has at least one
non-GET endpoint and that claim's own line contains neither "except" nor
"plus" alongside the actual method name. This matches the fix pattern PR #436
converged on in every location: "GET ... EXCEPT the one read-only POST
<endpoint>" / "GET requests against ... plus one read-only POST <endpoint>".

Stdlib only. Exit 0 = clean.

Modes (run from anywhere; paths resolve relative to this file):
    python3 plugins/aws-startup-advisor/scripts/consent-disclosure-audit.py
    python3 plugins/aws-startup-advisor/scripts/consent-disclosure-audit.py --plugin-root <dir>
        # check a copy of the plugin tree somewhere else (used by the tests)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# scripts/consent-disclosure-audit.py -> plugins/aws-startup-advisor/
DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# Only usage-API discovery sub-files declare a Capture Endpoint Table and make
# a consent promise about which HTTP methods they call — scope the check to
# them, not every markdown file in the plugin.
TARGET_GLOB = "references/phases/discover/discover-*-api.md"

SELF = Path(__file__).resolve()

_HTTP_METHOD = r"GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS"

# A real call site: an HTTP verb immediately followed by a path or full URL,
# inside backticks or in the table's Endpoint column — e.g. `` `GET /credits` ``,
# `` `POST /analytics/query` ``, "All are `GET` against `https://...`". Scoped
# to the Step 2 Capture section below so Error Handling / Scope Boundary prose
# that merely DISCUSSES methods is never read as a call site.
_METHOD_CALL_RE = re.compile(
    rf"\b({_HTTP_METHOD})\b\s*(?:to that same base|against)?\s*[`/]"
)
# The table's OWN header-column convention when every row shares one method,
# written as a parenthesized qualifier on the "Endpoint" column header itself
# — e.g. "| # | Endpoint (GET, `https://api.openai.com`) | ..." or
# "Endpoint (GET)". Anchored to "Endpoint (" (not a bare word search) so it
# only ever reads the table's own declared method, never an unrelated verb
# mentioned anywhere else in the section — and so it has no length limit to
# evade: the real Anthropic/Azure-OpenAI tables put this 600-800+ characters
# after the words "Capture Endpoint Table", which a bounded slice would miss.
_METHOD_IN_HEADER_CELL_RE = re.compile(rf"Endpoint\s*\(\s*({_HTTP_METHOD})\b")

# A table cell whose content IS (ignoring surrounding whitespace) the column
# label "Endpoint", optionally followed by its parenthesized method/base-URL
# qualifier — e.g. "Endpoint (GET)" or "Endpoint (GET, `https://...`)". Used
# to find which pipe-delimited cell is the Endpoint column, so later rows'
# method reads are confined to that one cell — never a Purpose/Notes/Output
# cell in the same row, and never "Endpoint"-looking prose that is not
# actually this table's own header row.
_ENDPOINT_HEADER_CELL_RE = re.compile(r"(?i)^endpoint\b")

# A markdown table is present in this section: a header-separator row, e.g.
# "| - | --- | --- |" or "|---|---|". If this matches but no method was read
# by either pattern above, the table's shape wasn't recognized — that is a
# gap in this script, not a GET-only file, and must fail rather than skip.
_TABLE_PRESENT_RE = re.compile(r"^\s*\|[\s:-]+\|[\s:-]+\|", re.MULTILINE)

# A table's header-separator row: every cell is only dashes/colons (and
# optional whitespace) — e.g. "| - | --- | --- |". Used to skip that row
# when scanning for the Endpoint column so it is never mistaken for a data
# row (its cells trivially match no useful content, but excluding it
# explicitly keeps the row-walk's intent clear).
_SEPARATOR_ROW_RE = re.compile(r"^[\s:-]+$")


def _table_cells(line: str) -> list[str] | None:
    """Split a markdown table row into its cells, or None if `line` is not a
    pipe-delimited table row at all. Leading/trailing empty cells from the
    row's own leading/trailing "|" are dropped."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells = stripped.split("|")
    # A well-formed "| a | b |" row splits to ['', ' a ', ' b ', '']; drop the
    # empty bookends a leading/trailing pipe produces.
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return [c.strip() for c in cells]

_STEP_HEADING_RE = re.compile(r"^##\s", re.MULTILINE)

# An optional inline-code wrapper around a bare method word — "`GET`" — that
# these discovery documents already use when naming a method in prose. Let
# each blanket-claim pattern below match "GET requests" and "`GET` requests"
# identically, rather than requiring the backtick-free spelling only.
_CODE = r"`?"


# Phrasings that make a BLANKET (unqualified unless the same line carries an
# exception) claim that this flow calls GET only / never calls non-GET. Each
# is checked line-by-line so the exact offending line can be reported.
_BLANKET_CLAIM_PATTERNS = [
    re.compile(rf"{_CODE}get{_CODE} requests? only", re.IGNORECASE),
    re.compile(r"\bget-only\b", re.IGNORECASE),
    re.compile(rf"\b{_CODE}get{_CODE} only\b", re.IGNORECASE),
    re.compile(rf"only call(?:s|ed)? {_CODE}get{_CODE}\b", re.IGNORECASE),
    re.compile(rf"i only call {_CODE}get{_CODE}\b", re.IGNORECASE),
    re.compile(r"non-get (?:method|request)", re.IGNORECASE),
    re.compile(rf"every row is {_CODE}get{_CODE}\b", re.IGNORECASE),
    re.compile(r"any other http method\b", re.IGNORECASE),
]

# A claim's own block is QUALIFIED (not a failure) when it names its own
# exception inline — the fix pattern PR #436 converged on in every location.
# Word-boundary AND case-insensitively matched: the script's own
# documentation above spells this "EXCEPT" in uppercase, and the noun
# "exception" (e.g. "without exception", "no exception") must never count as
# the preposition "except" granting one regardless of case — the two are
# unrelated English words that happen to share a prefix.
_EXCEPTION_MARKER_RES = [
    re.compile(r"\bexcept\b", re.IGNORECASE),
    re.compile(r"\bplus one\b", re.IGNORECASE),
    re.compile(r"\bplus a\b", re.IGNORECASE),
]


def _methods_in_capture_section(text: str) -> tuple[set[str], bool]:
    """Returns (real HTTP methods this file's Capture Endpoint Table calls,
    unrecognized_table) — `unrecognized_table` is True when Step 2 plainly
    contains a markdown table but neither method pattern read anything from
    it, meaning this script's table-shape coverage is incomplete for this
    file, not that the file is GET-only.

    Scoped to the "## Step 2: Capture" section (up to the next "## " heading)
    so a method named only in Error Handling, Security Contract prose, or the
    Scope Boundary's own FORBIDDEN list is never mistaken for a real call —
    those sections describe policy, not endpoints."""
    match = re.search(r"^##\s+Step 2:.*$", text, re.MULTILINE)
    if not match:
        return set(), False
    rest = text[match.end() :]
    end = _STEP_HEADING_RE.search(rest)
    section = rest[: end.start()] if end else rest

    methods: set[str] = set()

    # Find the table's own Endpoint column, from its header row, and read
    # methods ONLY from that column — never from a Purpose/Notes/Query
    # parameters/Output file cell in the same row, and never from
    # "Endpoint"-looking text that is not this table's own header. Without
    # this, a `` `POST /v1/messages` `` counter-example sitting in a GET
    # row's Purpose cell (e.g. "Never call `POST /v1/messages` here") reads
    # as a second method on a row that is actually GET-only, and
    # "Endpoint (POST)" prose anywhere outside the real header row is
    # misread as this table's own declared method.
    endpoint_col: int | None = None
    header_method: str | None = None
    for line in section.splitlines():
        cells = _table_cells(line)
        if cells is None:
            continue
        if endpoint_col is None:
            for idx, cell in enumerate(cells):
                if _ENDPOINT_HEADER_CELL_RE.match(cell):
                    endpoint_col = idx
                    m = _METHOD_IN_HEADER_CELL_RE.search(cell)
                    if m:
                        header_method = m.group(1)
                    break
            continue
        if endpoint_col is None or endpoint_col >= len(cells):
            continue
        if _SEPARATOR_ROW_RE.match(cells[endpoint_col]) and all(
            _SEPARATOR_ROW_RE.match(c) for c in cells
        ):
            continue  # the header-separator row itself, not a data row
        for m in _METHOD_CALL_RE.finditer(cells[endpoint_col]):
            methods.add(m.group(1))

    # The table's own "Endpoint (METHOD, ...)" header-column convention —
    # every row lists only a path, with the single shared method named once
    # in the header cell itself (the shape the real Anthropic and
    # Azure-OpenAI tables use). Already captured above from the real header
    # row; nothing further to scan.
    if header_method:
        methods.add(header_method)

    if methods:
        return methods, False

    # Nothing read. If the section has no markdown table at all, there is
    # genuinely nothing to extract (not every discovery sub-file necessarily
    # has one) — that is NOT an error.
    if not _TABLE_PRESENT_RE.search(section):
        return set(), False

    # A table IS present and neither pattern matched it: an unrecognized
    # table shape, not a GET-only file. Must not be treated the same as "no
    # non-GET method found" (which skips the file as clean) — report it so
    # the caller fails closed instead of silently passing an unchecked file.
    return set(), True


# A new Markdown list item ("- ", "* ", "+ ", or "1. ") at or above the
# current item's indentation starts a NEW logical block. A line indented
# deeper than the item marker (a wrapped continuation, or a nested item) stays
# part of the same block. Without this, two adjacent bullets with no blank
# line between them — the common case in this plugin's prose — are merged
# into one paragraph, letting a later bullet's exception wrongly qualify an
# earlier bullet's unrelated claim.
_LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-*+]|\d+\.)\s+")


def _paragraphs_with_line_numbers(text: str) -> list[tuple[int, str]]:
    """Split into logical blocks, each tagged with its starting line number.
    A block ends at a blank line, OR at the next list item written at the
    same or a shallower indent than the current one (a sibling or outer
    bullet) — whichever comes first. A line that wraps across physical lines
    with no blank line and no new list-item marker (plain prose, or a nested
    continuation line) stays part of the same block, so an exception clause
    stated two sentences — or two soft-wrapped lines — into the same bullet
    still counts as qualifying it. Only a DIFFERENT block repeating the claim
    with no exception is a failure."""
    paragraphs: list[tuple[int, str]] = []
    buf: list[str] = []
    start = 1
    item_indent: int | None = None
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip() == "":
            if buf:
                paragraphs.append((start, "\n".join(buf)))
                buf = []
            item_indent = None
            continue
        item_match = _LIST_ITEM_RE.match(line)
        if item_match:
            indent = len(item_match.group(1))
            if buf and (item_indent is None or indent <= item_indent):
                paragraphs.append((start, "\n".join(buf)))
                buf = []
            item_indent = indent
        if not buf:
            start = i
        buf.append(line)
    if buf:
        paragraphs.append((start, "\n".join(buf)))
    return paragraphs


def _line_for_offset(lines: list[str], offset: int) -> int:
    """Which physical line (0-indexed, into `lines`) a character offset in
    `" ".join(line.strip() for line in lines)` falls on — so a claim matched
    only after joining soft-wrapped lines back into one string can still be
    reported against a real source line."""
    pos = 0
    for idx, line in enumerate(lines):
        length = len(line.strip())
        if offset <= pos + length:
            return idx
        pos += length + 1  # +1 for the joining space
    return max(len(lines) - 1, 0)


# A sentence boundary within a normalized (soft-wrap-joined) block: a period,
# question mark, or exclamation point followed by whitespace (or end of
# string). Used to isolate the single sentence an exception marker appears
# in, so a method named only in a DIFFERENT, denying sentence of the same
# block ("... except POST /query. PATCH requests are forbidden.") is never
# credited as disclosed by that marker.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")


def _exception_clauses(normalized: str) -> list[str]:
    """Every sentence in `normalized` that itself contains an exception
    marker — the only text an exception marker is allowed to grant coverage
    from. A method mentioned in a sibling sentence that merely happens to
    sit in the same paragraph (a separate denial, a different claim) grants
    nothing."""
    return [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(normalized)
        if any(marker_re.search(sentence) for marker_re in _EXCEPTION_MARKER_RES)
    ]


def _unqualified_claims(text: str, non_get_methods: set[str]) -> list[tuple[int, str]]:
    """Every (line_number, offending_line) carrying a blanket GET-only claim
    with no inline exception, anywhere in its own logical block, for the
    non-GET methods this file actually calls.

    Methods are joined across physical lines before matching, so a claim that
    Markdown soft-wraps across two lines ("This runs GET requests" / "only.")
    is read as the single sentence it renders as. A block is QUALIFIED only
    when at least one of its SENTENCES carries an exception marker AND names
    every actual non-GET method the file calls, each as a complete token
    (`\\bPOST\\b`, not a substring match that "dispatch" or "output" would
    also satisfy) — naming just one of several undisclosed methods does not
    excuse the others, a method name hiding inside an unrelated word excuses
    nothing, and a method named only in a DIFFERENT sentence (e.g. a
    following denial — "except POST /query. PATCH requests are forbidden.")
    is not disclosed by that marker either; every undisclosed method must be
    named in the SAME affirmative exception sentence."""
    if not non_get_methods:
        return []
    failures: list[tuple[int, str]] = []
    for para_start, para in _paragraphs_with_line_numbers(text):
        lines = para.splitlines()
        normalized = " ".join(line.strip() for line in lines)
        clauses = _exception_clauses(normalized)
        has_exception = any(
            all(
                re.search(rf"\b{re.escape(method)}\b", clause, re.IGNORECASE)
                for method in non_get_methods
            )
            for clause in clauses
        )
        if has_exception:
            continue
        seen: set[int] = set()
        for pattern in _BLANKET_CLAIM_PATTERNS:
            for m in pattern.finditer(normalized):
                line_idx = _line_for_offset(lines, m.start())
                if line_idx in seen:
                    continue
                seen.add(line_idx)
                failures.append((para_start + line_idx, lines[line_idx].strip()))
    return failures


def audit(plugin: Path) -> tuple[list[str], list[str], int]:
    """Return (setup errors, failures, files-checked count)."""
    files = sorted(plugin.glob(f"skills/*/{TARGET_GLOB}"))
    if not files:
        return (
            [
                f"consent-disclosure audit: found ZERO files matching "
                f"skills/*/{TARGET_GLOB} — the discovery sub-file layout may "
                f"have changed. Refusing to run a no-op gate."
            ],
            [],
            0,
        )

    failures: list[str] = []
    checked = 0
    for path in files:
        rel = str(path.relative_to(plugin))
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as e:
            # An unreadable file was inspected for NOTHING, not confirmed
            # clean — it must count as a failure, not a silent skip that lets
            # the checked-file count claim an unread input passed.
            failures.append(f"{rel}: could not read file ({e}) — treating as a failure, not a skip")
            continue
        checked += 1

        real_methods, unrecognized_table = _methods_in_capture_section(text)
        if unrecognized_table:
            failures.append(
                f"{rel}: Step 2 contains a Capture Endpoint Table but no HTTP "
                f"method could be read from it (neither a per-row `METHOD "
                f"/path` cell nor an 'Endpoint (METHOD, ...)' header cell "
                f"matched) — fix the table shape, or this script's method "
                f"patterns, rather than letting this file pass unchecked"
            )
            continue

        non_get = real_methods - {"GET"}
        if not non_get:
            continue  # GET-only flow: no disclosure gap is even possible.

        for line_no, line in _unqualified_claims(text, non_get):
            failures.append(
                f"{rel}:{line_no}: claims a GET-only restriction, but the "
                f"Capture Endpoint Table calls {'/'.join(sorted(non_get))} too "
                f"— add an inline exception naming the method, or the "
                f"endpoint, to this line: {line!r}"
            )

    return [], failures, checked


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--plugin-root",
        type=Path,
        default=DEFAULT_PLUGIN_ROOT,
        help="plugin directory to check (default: the plugin this script lives in)",
    )
    args = ap.parse_args()

    plugin = args.plugin_root.resolve()
    if not plugin.is_dir():
        print(f"Plugin directory not found: {plugin}", file=sys.stderr)
        return 2

    errors, failures, checked = audit(plugin)
    if errors:
        print(f"consent-disclosure audit: {len(errors)} setup problem(s)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if failures:
        print(f"consent-disclosure audit: {len(failures)} problem(s)", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"consent-disclosure audit: OK ({checked} discovery sub-file(s) checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
