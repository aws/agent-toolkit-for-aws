#!/usr/bin/env python3
"""Validate migration-report.html completeness after Generate phase.

Checks required section IDs, TOC anchor integrity, minimum appendix content,
artifact-derived cost markers, and customer-facing readability rules. Exit 0
on PASS, 1 on FAIL.

Usage:
  python3 validate-migration-report.py /path/to/migration-report.html
  python3 validate-migration-report.py report.html \\
      --estimation-infra estimation-infra.json \\
      --estimation-ai estimation-ai.json

Script location: this file lives at
  plugins/aws-startup-advisor/scripts/validate-migration-report.py
Agents should invoke it via Path(__file__) resolution or:
  python3 "$(dirname ...)/scripts/validate-migration-report.py" ...
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

# Plugin root: plugins/aws-startup-advisor/
PLUGIN_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_SECTION_IDS = [
    "decision-summary",
    "exec-assumptions",
    "exec-services",
    "exec-costs",
    "exec-timeline",
    "exec-risks",
    "appendix-services",
    "appendix-costs",
    "appendix-steps",
    "appendix-artifacts",
]

# Decision mode (decision-report.html rendered at the post-Estimate Decision
# gate, choice A): executive sections + CTA only — appendices are forbidden
# because no Generate artifacts exist yet.
DECISION_REQUIRED_SECTION_IDS = [
    "decision-summary",
    "exec-assumptions",
    "exec-services",
    "exec-costs",
    "exec-timeline",
    "exec-risks",
    "decision-cta",
]

# AI-only mode (migration-report.html for an app-code-only / AI-workload repo with
# NO infrastructure track — no aws-design.json / estimation-infra.json / terraform/).
# The report is rendered from the AI artifacts (ai-workload-profile.json,
# aws-design-ai.json, estimation-ai.json, generation-ai.json) so it MUST NOT require
# the infra executive/appendix sections (exec-services, exec-costs, appendix-costs,
# appendix-services, appendix-steps) that an AI-only run cannot populate. It still
# requires the decision core, the assumptions panel, the risk panel, and the AI
# appendices so the customer always receives a structured report, never a stub.
AI_ONLY_REQUIRED_SECTION_IDS = [
    "decision-summary",
    "exec-assumptions",
    "exec-risks",
    "appendix-ai",
    "appendix-artifacts",
    "appendix-config",
    "appendix-glossary",
]

OPTIONAL_SECTION_IDS = [
    "exec-share",
    "exec-tco",
    "exec-architecture",
    "exec-security-teaser",
    "exec-optimization",
    "what-if-scenarios",
    "appendix-ai",
    "appendix-config",
    "appendix-security",
    "appendix-security-gap",
    "appendix-assumptions",
    "appendix-optimization",
    "appendix-glossary",
]

FORBIDDEN_PATTERNS = [
    (r"\[placeholder\]", "placeholder text"),
    (r"\bTODO\b", "TODO marker"),
]

# Customer-facing readability rules (enforced unless --no-readability).
# These move the de-jargoning and no-numbering conventions from "example in the
# fixture" to "enforced gate", so a stray internal scoring trace or a patched
# "Section 0/1b" heading fails the report instead of silently shipping.
READABILITY_PATTERNS = [
    (
        r"(?<![-_])\bTCO\b|Total\s+Cost\s+of\s+Ownership",
        'misleading ownership-cost label ("TCO") — use "estimated AWS monthly '
        'run rate"; the report does not price staffing or operating labor',
    ),
    (
        r"Rubric:",
        'internal scoring trace ("Rubric:") — drop it or gate behind a '
        '<details> "Why this mapping?" block',
    ),
    (
        r"\d+\s*(?:–|-|to)\s*\d+\s*(?:engineering\s+|effort\s+)?hours\b",
        "effort-hours range — the plugin has no calibrated effort data and "
        "hour figures get pasted into budgets; communicate time as stage "
        "sequence + duration drivers (migration-complexity.md § Provenance)",
    ),
    (
        r"(?<!uncalibrated\):\s)(?<!uncalibrated\): )\b\d+\s*(?:–|-|to)\s*\d+\+?\s*weeks\b",
        'bare week-range estimate — durations are uncalibrated; either drop it '
        'or label it "Legacy planning heuristic (uncalibrated): N–M weeks"',
    ),
    (
        r"Section\s+0\b",
        'literal "Section 0" heading — drop numeric "Section N" prefixes from '
        "customer-facing headings; let the table of contents carry structure",
    ),
    (
        r"<h[1-6][^>]*>\s*Section\s+\d+[a-z]?\s*[—-]",
        'numbered "Section N —" heading — drop numeric prefixes from headings; '
        "let the table of contents carry structure",
    ),
    (
        r"\b(?:very|significantly|extremely|vastly)\b",
        "vague intensifier (very/significantly/extremely/vastly) — quantify the "
        'claim from artifact data instead ("-32% ($497/mo lower)"), or drop it',
    ),
    (
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
        "slash-format date (N/N/YYYY reads differently across locales) — use "
        "ISO YYYY-MM-DD for all dates",
    ),
]

# Visual readability contract for generated reports. This intentionally checks
# structural CSS capabilities rather than pixel-perfect declarations: agents
# may refine colors and spacing, but they must not regress to unboxed prose on
# a plain white page or uneven inline-block metric cards.
VISUAL_CONTRACT_CHECKS = [
    (
        r"body\s*\{[^}]*background\s*:\s*(?:var\([^)]*\)|#f6f8fa)",
        "body must use a contrasting page background",
    ),
    (
        r"\.(?:report|container)\s*\{[^}]*max-width\s*:",
        "report shell must constrain line length with max-width",
    ),
    (
        r"section\s*\{[^}]*background\s*:[^;}]+;?[^}]*border\s*:[^;}]+;?"
        r"[^}]*border-radius\s*:",
        "sections must render as bordered surface cards",
    ),
    (
        r"\.metrics\s*\{[^}]*display\s*:\s*grid[^}]*grid-template-columns\s*:",
        "executive metrics must use a responsive CSS grid",
    ),
    (
        r"\.metric\s*\{[^}]*border\s*:[^;}]+;?[^}]*border-radius\s*:",
        "metric cards must have a bordered card treatment",
    ),
    (
        r"\.verdict\s*\{[^}]*background\s*:[^;}]+;?[^}]*border\s*:",
        "recommendation must have a visually distinct callout treatment",
    ),
    (
        r"\.savings\s*\{[^}]*color\s*:",
        "supported savings values must have a reusable visual treatment",
    ),
    (
        r"\.appendix-header\s*\{",
        "full/decision shared shell must define an appendix divider",
    ),
    (
        r":focus-visible\s*\{",
        "keyboard focus must be visibly styled",
    ),
    (
        r"@media\s*\([^)]*max-width\s*:\s*700px[^)]*\)",
        "mobile readability breakpoint (700px) is required",
    ),
    (
        r"@media\s+print\s*\{",
        "print-specific styling is required",
    ),
]

# Executive-flow sections must speak the reader's language, not the system's.
# Artifact filenames and Terraform resource IDs are internal build vocabulary —
# they belong in the technical appendices, not the executive summary. (Enforced
# unless --no-readability.)
EXEC_SECTION_IDS = (
    "decision-summary",
    "exec-share",
    "exec-tco",
    "exec-services",
    "exec-costs",
    "exec-architecture",
    "exec-security-teaser",
    "exec-optimization",
    "what-if-scenarios",
    "exec-timeline",
    "exec-risks",
)

ARTIFACT_FILENAME_RE = re.compile(r"\b[a-z0-9][a-z0-9_-]*\.json\b", re.IGNORECASE)
TERRAFORM_RESOURCE_RE = re.compile(r"\baws_[a-z0-9_]+\.[a-z0-9_]+\b")

APPENDIX_STUB_PATTERNS = [
    re.compile(
        r'<section[^>]*id="appendix-costs"[^>]*>.*?Full artifacts:\s*<code>estimation-infra\.json</code>',
        re.DOTALL | re.IGNORECASE,
    ),
    re.compile(
        r'<section[^>]*id="appendix-services"[^>]*>\s*<p>\s*See\s*<code>aws-design\.json</code>',
        re.DOTALL | re.IGNORECASE,
    ),
]

MIN_CONTENT_DEPTH = {
    "appendix-costs": 3,
    "appendix-services": 2,
    "appendix-steps": 2,
}

SECTION_OPEN = re.compile(
    r"<section\b[^>]*\bid=(['\"])([^'\"]+)\1",
    re.IGNORECASE,
)

# Migration ID baked into the reference fixture. If this appears in a real
# $MIGRATION_DIR run, the agent copied the golden file verbatim (fixture bleed).
FIXTURE_CANARY_ID = "0611-0606"
MIGRATION_ID_RE = re.compile(r"\b(\d{4}-\d{4})\b")

def plugin_script_path() -> Path:
    """Return absolute path to this validator (for agent invocation)."""
    return Path(__file__).resolve()


class _SectionScopeParser(HTMLParser):
    """Locate <section id="..."> ... </section> by parsed tag structure rather
    than a literal `id="value"` regex, so that:
      - any legal attribute-value spelling is recognized (single-quoted
        id='exec-costs', unquoted id=exec-costs, spaces around `=`) — a regex
        anchored to `id=\"value\"` silently misses all of these;
      - the matching CLOSE tag is found by counting nested <section> opens and
        closes of the same tag name, so `</section >` (whitespace before `>`)
        or a newline before the `>` still closes the section correctly, and a
        nested <section> (if one ever appears) does not truncate the match
        early;
      - when `_section_html` returns None for a section that IS present in the
        source but in a spelling regex doesn't recognize, callers must not
        silently skip validation that section was supposed to gate (this was
        the direct cause of a missing-anchor bypass: a validator's
        `if exec_costs_html is not None:` guard skipped a real, rendered
        section entirely because the extraction, not the requirement, failed).
    Reuses the same approach already used elsewhere in this codebase
    (`_CostAnchorParser`, and the Heroku validator's tag-depth section finder)
    rather than inventing a third one.
    """

    def __init__(self, target_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self.target_id = target_id
        self.found_html: str | None = None
        self._depth = 0  # >0 while inside the matched <section>, counting nested <section>s
        self._parts: list[str] = []
        self._raw_pos_stack: list[int] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "section":
            if self._depth > 0:
                self._parts.append(self.get_starttag_text() or "")
            return
        if self._depth > 0:
            self._depth += 1
            self._parts.append(self.get_starttag_text() or "")
            return
        if dict(attrs).get("id") == self.target_id:
            self._depth = 1
            self._parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth > 0:
            self._parts.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if tag != "section" or self._depth == 0:
            if self._depth > 0:
                self._parts.append(f"</{tag}>")
            return
        self._depth -= 1
        if self._depth == 0:
            if self.found_html is None:
                self.found_html = "".join(self._parts)
        else:
            self._parts.append("</section>")

    def handle_data(self, data: str) -> None:
        if self._depth > 0:
            # Re-escape markup-syntax characters before appending. With
            # convert_charrefs=True (the default this parser wants — plain
            # decoded text is what every OTHER caller of _section_html
            # expects, e.g. matching a dollar amount written as a numeric
            # character reference), handle_data receives ALREADY-DECODED
            # text: an escaped code example like `&lt;span
            # data-cost-key="x"&gt;$112&lt;/span&gt;` decodes to the literal
            # text `<span data-cost-key="x">$112</span>` — indistinguishable,
            # once appended into the returned string, from a REAL <span> tag
            # that was never actually in the source. Re-escaping `<`, `>`,
            # and `&` here (the only characters that make reparsed text look
            # like markup) makes the returned string round-trip safely
            # through a second HTMLParser pass (e.g. _cost_anchor_matches)
            # while leaving every other decoded character — including
            # decoded numeric/named character references that are NOT
            # `<`/`>`/`&` themselves, like a literal "$" from `&#36;` — as
            # plain, matchable text for callers that scan for prose/dollar
            # amounts rather than reparsing HTML structure.
            self._parts.append(
                data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )

    def handle_comment(self, data: str) -> None:
        if self._depth > 0:
            self._parts.append(f"<!--{data}-->")


def _section_html(html: str, section_id: str) -> str | None:
    """Return the inner HTML of the first <section id="section_id"> in `html`,
    found via parsed tag structure (any legal attribute/closing-tag spelling),
    or None if that section is genuinely absent."""
    parser = _SectionScopeParser(section_id)
    parser.feed(html)
    parser.close()
    return parser.found_html


def _section_id_counts(html: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in SECTION_OPEN.finditer(html):
        sid = match.group(2)
        counts[sid] = counts.get(sid, 0) + 1
    return counts


def _validate_required_sections(
    html: str, required_ids: list[str] | None = None
) -> list[str]:
    errors: list[str] = []
    counts = _section_id_counts(html)
    for section_id in required_ids if required_ids is not None else REQUIRED_SECTION_IDS:
        n = counts.get(section_id, 0)
        if n == 0:
            errors.append(f'missing required <section id="{section_id}">')
        elif n > 1:
            errors.append(f'duplicate <section id="{section_id}"> ({n} occurrences)')
    return errors


def _toc_hrefs(html: str) -> list[str]:
    nav_match = re.search(
        r"<nav\b[^>]*\bclass=[\"'][^\"']*toc[^\"']*[\"'][^>]*>(.*?)</nav>",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not nav_match:
        return []
    return re.findall(r'href="#([^"]+)"', nav_match.group(1), re.IGNORECASE)


def _validate_toc(html: str, required_ids: list[str] | None = None) -> list[str]:
    if required_ids is None:
        required_ids = REQUIRED_SECTION_IDS
    errors: list[str] = []
    hrefs = _toc_hrefs(html)
    if not hrefs:
        return errors  # TOC optional if nav.toc absent; spec requires it in generated reports

    section_ids = set(_section_id_counts(html).keys())
    for href in hrefs:
        if href not in section_ids:
            errors.append(f'TOC broken link href="#{href}" — no matching <section id="{href}">')

    # Every required section must be linked from the TOC.
    for section_id in required_ids:
        if section_id in section_ids and section_id not in hrefs and hrefs:
            errors.append(
                f'TOC missing link to required section id="{section_id}" '
                f'(add <a href="#{section_id}">)'
            )
    return errors


def _validate_decision_first(html: str) -> list[str]:
    """The verdict is the report thesis and must precede navigation."""
    decision = re.search(
        r'<section\b[^>]*\bid=["\']decision-summary["\']',
        html,
        re.IGNORECASE,
    )
    toc = re.search(
        r'<nav\b[^>]*\bclass=["\'][^"\']*\btoc\b[^"\']*["\']',
        html,
        re.IGNORECASE,
    )
    if decision and toc and decision.start() > toc.start():
        return [
            "decision-summary must appear before the table of contents "
            "(show the report thesis before navigation)"
        ]
    return []


def _count_table_rows(section_html: str) -> int:
    tbody = re.search(r"<tbody>(.*?)</tbody>", section_html, re.DOTALL | re.IGNORECASE)
    if not tbody:
        return 0
    return len(re.findall(r"<tr\b", tbody.group(1), re.IGNORECASE))


def _section_content_depth(section_id: str, section_html: str) -> int:
    rows = _count_table_rows(section_html)
    if section_id == "appendix-services":
        clusters = len(re.findall(r'class="cluster-block"', section_html))
        return max(rows, clusters)
    if section_id == "appendix-steps":
        phases = len(re.findall(r"<h3>Phase\s+\d", section_html, re.IGNORECASE))
        return max(rows, phases)
    return rows


def _security_scoped_html(html: str) -> str:
    chunks: list[str] = []
    for sid in ("appendix-security", "appendix-costs", "exec-security-teaser"):
        part = _section_html(html, sid)
        if part:
            chunks.append(part)
    return "\n".join(chunks)


def _dollar_amount_present(amount: float | int, text: str) -> bool:
    """True when a dollar-formatted value appears in text (not bare CSS integers)."""
    normalized = text.replace(",", "")
    v = float(amount)
    candidates: list[str] = []
    if v == int(v):
        i = int(v)
        candidates.extend([f"${i}", f"${i}.00", f"${i}.0"])
    candidates.append(f"${v:.2f}")
    return any(c in normalized for c in candidates)


def _has_guardduty_or_baseline(html: str, estimation_infra: dict | None) -> tuple[bool, str]:
    scope = _security_scoped_html(html)
    if not scope:
        return False, "missing security content in appendix-security or appendix-costs sections"

    if re.search(r"GuardDuty", scope, re.IGNORECASE):
        return True, ""

    if not estimation_infra:
        return False, "missing GuardDuty mention in security/cost appendix sections"

    breakdown = estimation_infra.get("projected_costs", {}).get("breakdown", {})
    baseline = breakdown.get("security_baseline")
    if not baseline:
        return True, ""  # no baseline in estimate — nothing to cross-check

    components = baseline.get("components") or {}
    for _key, val in components.items():
        if val is not None and float(val) > 0 and _dollar_amount_present(val, scope):
            return True, ""

    return False, (
        "appendix-security/appendix-costs must mention GuardDuty or include dollar-formatted "
        "security_baseline component costs from estimation-infra.json "
        "(e.g. GuardDuty $13.00, CloudTrail $1.50)"
    )


def _readability_scope(html: str) -> str:
    """Body only, excluding <style> blocks so CSS class names like .rubric or
    selectors never trip the readability patterns."""
    no_style = re.sub(r"<style\b.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    body = re.search(r"<body\b[^>]*>(.*?)</body>", no_style, re.DOTALL | re.IGNORECASE)
    return body.group(1) if body else no_style


def _validate_readability(html: str) -> list[str]:
    errors: list[str] = []
    scope = _readability_scope(html)
    for pattern, label in READABILITY_PATTERNS:
        if re.search(pattern, scope, re.IGNORECASE):
            errors.append(f"readability: {label}")
    return errors


# generate-artifacts-report.md rule 2 ("Currency formatting"): monthly figures
# render as whole dollars with thousands separators ($1,415, $118); cents are
# reserved for genuinely sub-dollar precision ($1.50, $0.40) — e.g. hourly or
# per-unit rates, or small monthly totals under ~$2 where a cents digit is
# still meaningful. A multi-hundred/thousand-dollar figure rendered with cents
# (e.g. $25,684.89/mo) is the regression this check exists to catch: it read
# as unrounded raw arithmetic output rather than an authored report figure,
# and it is long enough to overflow a fixed-width metric card.
CENTS_RE = re.compile(r"\$([0-9][0-9,]*)\.([0-9]{2})\b")

# A cents figure immediately followed (within ~25 chars of DECODED, tag-free
# text) by one of these is a per-unit rate, not an absolute monthly cost —
# cents are meaningful there regardless of the whole-dollar magnitude (e.g.
# "$21.18 (1-mo commit)" for a model-unit-hour rate, "$5.00/mo per policy").
# Deliberately does NOT accept a BARE "month"/"mo" as itself the qualifying
# unit: that is exactly the unit an ordinary MONTHLY total is denominated in,
# so treating it alone as a rate suffix would exempt the very figures this
# rule targets (the regression case itself renders as "$25,684.89/mo" —
# trailing "/mo" alone is not evidence of a per-unit rate). "/mo per <unit>"
# IS still accepted, since "per <unit>" is what actually marks it a rate —
# "/mo" there is just a connector before the real per-unit qualifier, as in
# "$5.00/mo per policy". Genuine sub-dollar-precision monthly totals are
# instead handled by the _CENTS_MEANINGFUL_BELOW threshold below, not by
# unit text.
_RATE_SUFFIX_RE = re.compile(
    r"^\s*(?:/|\(|\bper\b)?\s*(?:mo\b\s*(?:per\b\s*)?)?"
    r"(?:hr|hour|hourly|vcpu|gb|gib|tb|image|unit|policy|1m|10k|"
    r"[0-9]+-mo)\b",
    re.IGNORECASE,
)

# Whole-dollar part below this is small enough that a cents digit is itself
# meaningful precision (matches the skill rule's own examples: $1.50, $0.40).
_CENTS_MEANINGFUL_BELOW = 2

# Appendix B's documented per-service cost breakdown table
# (generate-artifacts-report.md: "Service Category, AWS Service, Monthly Cost
# (Balanced), Calculation/Notes") renders its arithmetic show-work in a
# dedicated column, e.g. "1 vCPU × $0.04048 × 511 hrs" — a per-unit rate with
# no adjacent unit suffix at all (it's followed by "× <quantity> <unit>", not
# "/hr"). Cells under a "Calculation" or "Notes" column header ARE where rate
# operands like this legitimately appear with cents, but the column header
# alone is not proof every dollar figure in the cell is a rate: the same
# cell's prose can carry ordinary whole-dollar component amounts summed
# together ("ALB $22 + NAT $33 for VPC-attached Fargate/RDS") or the
# calculated monthly RESULT of the shown arithmetic ("... = $12,008.50/mo")
# — neither of those is itself a per-unit rate, and both must still be held
# to the whole-dollar rule. Only an operand actually adjacent to a
# multiplication marker (×, "x", or "times") — on EITHER side, since the
# rate can be the left or right operand ("1 vCPU × $0.04048" vs.
# "511 hrs × $23.50") — is exempt; scope the exemption to that operand
# specifically, not the whole cell.
#
# The bare "x" alternative must not match a capital "X" that merely opens an
# unrelated word like "X-Ray": a plain \b is satisfied by the letter/hyphen
# boundary there, so the marker additionally requires either end-of-string
# or a following separator (whitespace, "$", or a digit) that actually looks
# like the start of the other operand, never a letter/hyphen continuing a
# service name.
_CALC_NOTES_HEADER_RE = re.compile(r"calculation|\bnotes\b", re.IGNORECASE)
_CALC_RATE_OPERAND_TRAILING_RE = re.compile(
    r"^\s*(?:×|times\b|x(?=\s|$|[$0-9]))", re.IGNORECASE
)
_CALC_RATE_OPERAND_LEADING_RE = re.compile(
    r"(?:×|\btimes|(?<=[\s0-9])x)\s*$", re.IGNORECASE
)


class _DecodedTextRunParser(HTMLParser):
    """Extract rendered text as the browser would present it — entities
    decoded, comments and inert content (script/style/template) excluded —
    while preserving amount/unit adjacency across inline markup and marking
    which text runs fall inside a table cell under a "Calculation"/"Notes"
    column header.

    Rationale (all three are real gaps in matching raw HTML source directly):
      - character references (`&nbsp;`, `&times;`) are never decoded before
        pattern matching, so a rate written with an entity separator reads as
        different text than the same rate written with a literal character;
      - comments and <script>/<style> content are not rendered, but a plain
        substring/regex scan over raw HTML sees them as ordinary text — a
        commented-out raw figure must not be flagged, since the browser never
        shows it;
      - inline tags split adjacent tokens in the source (`<strong>$23.50</strong>/hr`
        has `</strong>` between the amount and its unit) even though a reader
        sees "$23.50/hr" as one continuous phrase — inline tags must not
        introduce a gap, while block-level tags (row/cell/paragraph
        boundaries) SHOULD still separate otherwise-unrelated text so two
        different table cells' numbers never fuse into one token.
    """

    # A conservative set of tags that visually run text together with their
    # siblings (the browser renders no line break) — every other tag is
    # treated as block-level and gets a separating space.
    _INLINE_TAGS = {
        "a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em",
        "i", "kbd", "mark", "q", "s", "samp", "small", "span", "strong",
        "sub", "sup", "time", "u", "var", "wbr",
    }
    _INERT_TAGS = {"script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._calc_col: list[bool] = []  # per-part flag: inside a Calculation/Notes cell
        self._inert_depth = 0
        # Table header tracking: which <th> column index (0-based) is a
        # Calculation/Notes column, per currently-open table (stack, for
        # nested tables — innermost wins).
        self._table_stack: list[dict[str, object]] = []
        # Absolute character offsets (into text()) where a block-level
        # boundary (a separating space from a non-inline tag) was inserted.
        # A rate-suffix match must never read PAST one of these into
        # unrelated content from a different cell/row/paragraph — a single
        # space alone doesn't stop a word-based regex, since a real word
        # like "Hourly" can legitimately start the very next cell's text
        # (see the class docstring's third bullet).
        self._boundaries: list[int] = []

    def _current_table(self) -> dict[str, object] | None:
        return self._table_stack[-1] if self._table_stack else None

    def _emit(self, text: str, *, is_boundary: bool = False) -> None:
        if not text:
            return
        if is_boundary:
            self._boundaries.append(sum(len(p) for p in self._parts))
        table = self._current_table()
        in_calc = bool(table and table.get("in_calc_cell"))
        self._parts.append(text)
        self._calc_col.append(in_calc)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._INERT_TAGS:
            self._inert_depth += 1
            return
        if self._inert_depth > 0:
            return
        if tag == "table":
            self._table_stack.append(
                {"header_row": False, "col": 0, "calc_col_index": None,
                 "in_calc_cell": False, "cell_col": 0}
            )
        elif tag in ("thead", "tr"):
            table = self._current_table()
            if table is not None and tag == "tr":
                table["cell_col"] = 0
        elif tag in ("th", "td") and self._current_table() is not None:
            table = self._current_table()
            col_index = table["cell_col"]
            if tag == "th":
                table["_pending_th_col"] = col_index
            elif tag == "td" and table.get("calc_col_index") == col_index:
                table["in_calc_cell"] = True
        elif tag not in self._INLINE_TAGS:
            self._emit(" ", is_boundary=True)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self._INLINE_TAGS and tag not in self._INERT_TAGS:
            self._emit(" ", is_boundary=True)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._INERT_TAGS:
            if self._inert_depth > 0:
                self._inert_depth -= 1
            return
        if self._inert_depth > 0:
            return
        table = self._current_table()
        if tag == "th" and table is not None and "_pending_th_col" in table:
            table["cell_col"] = table["_pending_th_col"] + 1
        elif tag == "td" and table is not None:
            table["in_calc_cell"] = False
            table["cell_col"] = table["cell_col"] + 1
        elif tag == "table" and self._table_stack:
            self._table_stack.pop()
        if tag not in self._INLINE_TAGS:
            self._emit(" ", is_boundary=True)

    def handle_data(self, data: str) -> None:
        if self._inert_depth > 0:
            return
        table = self._current_table()
        if table is not None and "_pending_th_col" in table:
            if _CALC_NOTES_HEADER_RE.search(data):
                table["calc_col_index"] = table["_pending_th_col"]
        self._emit(data)

    def text(self) -> str:
        return "".join(self._parts)

    def calc_mask(self) -> list[bool]:
        """Per-character (matching text()) flag: True while inside a
        Calculation/Notes column cell."""
        mask: list[bool] = []
        for part, in_calc in zip(self._parts, self._calc_col):
            mask.extend([in_calc] * len(part))
        return mask

    def boundaries(self) -> list[int]:
        """Absolute offsets (into text()) of every block-level separator —
        the hard stops a rate-suffix match must never read past."""
        return self._boundaries


def _decoded_text_with_calc_mask(html: str) -> tuple[str, list[bool], list[int]]:
    scope = _readability_scope(html)
    parser = _DecodedTextRunParser()
    parser.feed(scope)
    parser.close()
    return parser.text(), parser.calc_mask(), parser.boundaries()


def _validate_currency_formatting(html: str) -> list[str]:
    """Monthly cost figures must render as whole dollars (rule 2). Flag any
    $X.YY figure whose whole-dollar part is >= $2 and that is not immediately
    followed by a per-unit-rate suffix (/hr, per policy, etc.) — those are
    legitimately sub-dollar-precision rates, not rounded monthly totals — and
    that is not inside a documented Calculation/Notes column cell (Appendix B
    per-service breakdown show-work, which legitimately renders rate
    arithmetic like "1 vCPU × $0.04048 × 511 hrs" with no adjacent unit
    suffix at all)."""
    errors: list[str] = []
    text, calc_mask, boundaries = _decoded_text_with_calc_mask(html)
    seen: set[str] = set()
    for match in CENTS_RE.finditer(text):
        whole = int(match.group(1).replace(",", ""))
        if whole < _CENTS_MEANINGFUL_BELOW:
            continue
        # The rate-suffix / rate-operand window must stop at the next
        # block-level boundary (table cell/row, paragraph, etc.) even if
        # that's before the normal 25-char lookahead — a boundary is
        # inserted as a single space, which does not itself stop a
        # word-based regex, so an unrelated word that happens to start the
        # NEXT cell/block (e.g. "Hourly" opening a sibling note column) must
        # never be readable as this figure's own rate suffix. bisect finds
        # the first boundary offset > match.end(); a boundary exactly AT
        # match.end() (the very next char) also cuts the window to empty,
        # correctly blocking any suffix read across it.
        cutoff = match.end() + 25
        for boundary in boundaries:
            if boundary >= match.end():
                cutoff = min(cutoff, boundary)
                break
        trailing = text[match.end():cutoff]
        if _RATE_SUFFIX_RE.match(trailing):
            continue
        # In a Calculation/Notes cell, ONLY a figure immediately adjacent to
        # a multiplication marker (×, "x", "times") is a rate operand and
        # exempt — a component amount being summed ("ALB $22 + NAT $33") or
        # the calculated monthly result ("= $12,008.50/mo") in the SAME cell
        # is not itself a rate and must still be held to the whole-dollar
        # rule, even though the cell as a whole is rate context. The rate
        # can appear as either operand of the multiplication ("$0.04048 ×
        # 511 hrs" or "511 hrs × $23.50"), so both a trailing marker
        # (checked above the figure) and a leading marker (checked below,
        # from the previous boundary up to the figure) qualify.
        if any(calc_mask[match.start():match.end()]):
            if _CALC_RATE_OPERAND_TRAILING_RE.match(trailing):
                continue
            lead_start = 0
            for boundary in reversed(boundaries):
                if boundary <= match.start():
                    lead_start = boundary
                    break
            leading = text[max(lead_start, match.start() - 25):match.start()]
            if _CALC_RATE_OPERAND_LEADING_RE.search(leading):
                continue
        token = match.group(0)
        if token in seen:
            continue
        seen.add(token)
        errors.append(
            f'currency formatting: "{token}" renders cents on a monthly-scale '
            "figure — round to a whole dollar (generate-artifacts-report.md "
            'rule 2: cents only for genuinely sub-dollar precision, e.g. "'
            '$1.50", "$0.40", or a per-unit rate like "$0.018/hr")'
        )
    return errors


def _validate_visual_contract(html: str) -> list[str]:
    """Validate the shared report shell's minimum visual readability contract."""
    style_blocks = re.findall(
        r"<style\b[^>]*>(.*?)</style>",
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not style_blocks:
        return ["visual readability: missing inline <style> report shell"]
    css = "\n".join(style_blocks)
    errors: list[str] = []
    for pattern, label in VISUAL_CONTRACT_CHECKS:
        if not re.search(pattern, css, re.DOTALL | re.IGNORECASE):
            errors.append(f"visual readability: {label}")
    return errors


def _validate_exec_vocabulary(html: str) -> list[str]:
    """Executive-flow sections must name what the reader controls, not how the
    system is built. Artifact filenames (*.json) and Terraform resource IDs
    (aws_<resource>.<name>) are internal vocabulary and belong in the technical
    appendices. Appendix sections are exempt by design."""
    errors: list[str] = []
    for sid in EXEC_SECTION_IDS:
        section = _section_html(html, sid)
        if not section:
            continue
        filenames = sorted(set(m.lower() for m in ARTIFACT_FILENAME_RE.findall(section)))
        resources = sorted(set(TERRAFORM_RESOURCE_RE.findall(section)))
        if filenames:
            errors.append(
                f'exec vocabulary: <section id="{sid}"> exposes artifact filename(s) '
                f"{filenames} — name what the reader controls in the executive flow; "
                "keep artifact filenames in the technical appendices"
            )
        if resources:
            errors.append(
                f'exec vocabulary: <section id="{sid}"> exposes Terraform resource ID(s) '
                f"{resources} — move resource names to the appendix; the executive flow "
                "names what the reader controls"
            )
    return errors


def _has_security_baseline(estimation_infra: dict | None) -> bool:
    if not estimation_infra:
        return False
    return bool(
        estimation_infra.get("projected_costs", {}).get("breakdown", {}).get("security_baseline")
    )


def _validate_security_teaser(html: str, estimation_infra: dict | None) -> list[str]:
    """When a security baseline exists, the executive flow must carry a compact
    teaser (exec-security-teaser) — not the full control table inline."""
    if not _has_security_baseline(estimation_infra):
        return []
    if _section_id_counts(html).get("exec-security-teaser", 0) >= 1:
        return []
    return [
        'security_baseline exists but no <section id="exec-security-teaser"> — keep a compact '
        "teaser in the executive flow and the full control table in appendix-security"
    ]


def _validate_action_lists(html: str) -> list[str]:
    """Key decisions ahead and Next steps must be ordered lists — actionable sequence."""
    errors: list[str] = []
    summary = _section_html(html, "decision-summary") or ""
    for heading in ("Key decisions ahead", "Next steps"):
        pattern = re.compile(
            rf"<h3[^>]*>\s*{re.escape(heading)}\s*</h3>\s*<(ul|ol)\b",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(summary)
        if match and match.group(1).lower() == "ul":
            errors.append(
                f'decision-summary: "{heading}" must use <ol class="compact"> (ordered action '
                "items), not a bullet list"
            )
    return errors


def _validate_decision_language(
    html: str, estimation_infra: dict | None
) -> list[str]:
    """Keep whole-stack decisions distinct from track-scoped holds."""
    summary = _section_html(html, "decision-summary") or ""
    errors: list[str] = []
    recommendation = (estimation_infra or {}).get("recommendation") or {}
    has_stay_reasons = bool(recommendation.get("stay_if"))
    expected_heading_count = len(
        re.findall(
            r"<h[1-6][^>]*>\s*Stay\s+entirely\s+if\s*</h[1-6]>",
            summary,
            re.I,
        )
    )
    if has_stay_reasons and expected_heading_count != 1:
        errors.append(
            "decision-summary has recommendation.stay_if reasons and must contain "
            'exactly one "Stay entirely if" heading '
            f"(found {expected_heading_count})"
        )
    elif re.search(r"<h[1-6][^>]*>\s*Stay\s+if\s*</h[1-6]>", summary, re.I):
        errors.append(
            'decision-summary heading "Stay if" is ambiguous — use '
            '"Stay entirely if" for whole-stack reasons'
        )
    if re.search(r'class=["\'][^"\']*\bbadge-verdict-', summary, re.I):
        errors.append(
            "decision-summary must use a typography-first verdict headline and "
            "plain-text metadata, not badge-verdict-* pills"
        )
    return errors


OPTIMIZATION_EXEC_ID = "exec-optimization"
OPTIMIZATION_APPENDIX_ID = "appendix-optimization"
_SP_RE = re.compile(r"savings\s*plans?", re.I)
_RI_RE = re.compile(r"reserved\s+(?:instances?|capacity|nodes?)", re.I)
_COMMITMENT_SERVICE_RE = re.compile(
    r"\b(?:rds|aurora|fargate|lambda|elasticache|dynamodb|ec2)\b", re.I
)
_NON_STACK_RE = re.compile(
    r"(?:not\s+additive|do\s+not\s+add|already\s+embed|already\s+includes|"
    r"not\s+a\s+sum|already\s+assume)",
    re.I,
)


def _optimization_opportunities(
    estimation_infra: dict | None,
    estimation_ai: dict | None,
) -> list[dict]:
    rows: list[dict] = []
    for artifact in (estimation_infra, estimation_ai):
        if not artifact:
            continue
        for item in artifact.get("optimization_opportunities") or []:
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _opp_blob(item: dict) -> str:
    targets = item.get("target_services")
    if isinstance(targets, list):
        target_text = " ".join(str(t) for t in targets)
    else:
        target_text = str(targets or "")
    return " ".join(
        [
            str(item.get("opportunity") or ""),
            str(item.get("type") or ""),
            str(item.get("description") or ""),
            target_text,
        ]
    )


def _has_optimization_columns(section: str) -> bool:
    """True if ANY <thead> in the section has the required columns.

    Section 3c allows a decision-mode exec-optimization to render a posture
    comparison table *and* the opportunity table in the same section. Only
    the opportunity table needs these columns — checking just the first
    <thead> rejects a valid report whenever the posture table (which has its
    own, different columns) happens to come first.
    """
    headers = re.findall(r"<thead\b[^>]*>(.*?)</thead>", section, re.DOTALL | re.IGNORECASE)
    for header in headers:
        text = unescape(re.sub(r"<[^>]+>", " ", header)).lower()
        if (
            "optimization" in text
            and "target" in text
            and "commitment" in text
            and "effort" in text
            and "saving" in text
        ):
            return True
    return False


def _table_rows_text(section: str) -> str:
    """Plain text from every <tbody> in a section — data rows only.

    Headings, explanatory prose, and links can legitimately say "Savings
    Plans and Reserved Instances" while the actual commitment-discount rows
    were removed. Presence checks for a specific product must look at
    rendered data, not surrounding copy.
    """
    bodies = re.findall(r"<tbody\b[^>]*>(.*?)</tbody>", section, re.DOTALL | re.IGNORECASE)
    if not bodies:
        return ""
    return unescape(re.sub(r"<[^>]+>", " ", " ".join(bodies)))


def _thead_has_optimization_columns(thead_html: str) -> bool:
    """True if this <thead> is the opportunity table's header (not the posture table)."""
    text = unescape(re.sub(r"<[^>]+>", " ", thead_html)).lower()
    return (
        "optimization" in text
        and "target" in text
        and "commitment" in text
        and "effort" in text
        and "saving" in text
    )


def _opportunity_table_optimization_cells(section: str) -> list[str]:
    """First-column (Optimization) text of each data row in the *opportunity* table.

    A Section 3c optimization section can carry two tables: a posture
    comparison (Balanced / Savings Plan / Optimized rows, whose cells and
    caveats name "Savings Plan") and the line-level opportunity table (the
    one with Optimization / Target / Commitment / Effort columns). Presence of
    a product must be proven by an opportunity row, so this isolates the
    table whose <thead> matches the required columns and returns the
    Optimization cell (first <td>) of every <tbody> data row. Posture rows,
    heading prose, and Optimized-tier caveats are therefore never counted, and
    an empty opportunity <tbody> yields no cells.
    """
    cells: list[str] = []
    for table in re.findall(r"<table\b[^>]*>(.*?)</table>", section, re.DOTALL | re.IGNORECASE):
        thead = re.search(r"<thead\b[^>]*>(.*?)</thead>", table, re.DOTALL | re.IGNORECASE)
        if not thead or not _thead_has_optimization_columns(thead.group(1)):
            continue
        for body in re.findall(r"<tbody\b[^>]*>(.*?)</tbody>", table, re.DOTALL | re.IGNORECASE):
            for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.DOTALL | re.IGNORECASE):
                first_cell = re.search(
                    r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE
                )
                if first_cell:
                    cells.append(unescape(re.sub(r"<[^>]+>", " ", first_cell.group(1))).strip())
    return cells


def _opp_classification_blob(item: dict) -> str:
    """Text used ONLY to classify an opportunity as a Savings Plan / RI product.

    Deliberately excludes `description` and `target_services`: description is
    explanatory prose that can state a product does NOT apply (e.g. "Database
    Savings Plans do not cover ElastiCache for Redis OSS or Memcached"), which
    would otherwise get matched as evidence the artifact contains that
    product. Classification uses only the structured `opportunity` name and
    `type` (underscores normalized to spaces so `elasticache_reserved_nodes`
    matches the same regex as "ElastiCache Reserved Nodes").
    """
    type_text = str(item.get("type") or "").replace("_", " ")
    return f"{item.get('opportunity') or ''} {type_text}"


def _design_has_commitment_eligible(aws_design: dict | None) -> bool:
    if not aws_design:
        return False
    return bool(_COMMITMENT_SERVICE_RE.search(json.dumps(aws_design)))


def _opportunities_target_commitment_eligible(opportunities: list[dict]) -> bool:
    return any(_COMMITMENT_SERVICE_RE.search(_opp_blob(item)) for item in opportunities)


def _validate_optimization_sections(
    html: str,
    estimation_infra: dict | None,
    estimation_ai: dict | None,
    aws_design: dict | None,
    *,
    mode: str,
    require_toc: bool,
) -> list[str]:
    """Dedicated Cost Optimization section is required when Estimate emitted rows.

    A table buried only under appendix-costs is not enough — that is how
    Savings Plans / RI content was dropped from generated reports.
    """
    opportunities = _optimization_opportunities(estimation_infra, estimation_ai)
    if not opportunities:
        return []

    errors: list[str] = []
    counts = _section_id_counts(html)
    exec_n = counts.get(OPTIMIZATION_EXEC_ID, 0)
    appendix_n = counts.get(OPTIMIZATION_APPENDIX_ID, 0)

    if exec_n == 0:
        errors.append(
            "optimization_opportunities exist but no "
            f'<section id="{OPTIMIZATION_EXEC_ID}"> — render a standalone Cost '
            "Optimization section (Balanced on-demand vs Savings Plans / Reserved "
            "Instances). A table buried only in appendix-costs does not satisfy this gate"
        )
    elif exec_n > 1:
        errors.append(f'duplicate <section id="{OPTIMIZATION_EXEC_ID}"> ({exec_n} occurrences)')

    if mode == "full":
        if appendix_n == 0:
            errors.append(
                "optimization_opportunities exist but no "
                f'<section id="{OPTIMIZATION_APPENDIX_ID}"> — the opportunity table '
                "must be its own appendix section, not only a subsection of appendix-costs"
            )
        elif appendix_n > 1:
            errors.append(
                f'duplicate <section id="{OPTIMIZATION_APPENDIX_ID}"> ({appendix_n} occurrences)'
            )

    if require_toc:
        hrefs = _toc_hrefs(html)
        if hrefs:
            if exec_n and OPTIMIZATION_EXEC_ID not in hrefs:
                errors.append(
                    f'TOC missing link to required section id="{OPTIMIZATION_EXEC_ID}" '
                    f'(add <a href="#{OPTIMIZATION_EXEC_ID}">)'
                )
            if mode == "full" and appendix_n and OPTIMIZATION_APPENDIX_ID not in hrefs:
                errors.append(
                    f'TOC missing link to required section id="{OPTIMIZATION_APPENDIX_ID}" '
                    f'(add <a href="#{OPTIMIZATION_APPENDIX_ID}">)'
                )

    exec_html = _section_html(html, OPTIMIZATION_EXEC_ID) or ""
    appendix_html = _section_html(html, OPTIMIZATION_APPENDIX_ID) or ""
    table_scope = appendix_html if mode == "full" else exec_html
    if table_scope and not _has_optimization_columns(table_scope):
        where = OPTIMIZATION_APPENDIX_ID if mode == "full" else OPTIMIZATION_EXEC_ID
        errors.append(
            f"{where} table must include Optimization, Target, Monthly savings "
            "(or Est. savings), Commitment, and Effort columns"
        )

    if exec_html:
        if not re.search(r"balanced", exec_html, re.I):
            errors.append(
                "exec-optimization must compare commitment savings to the Balanced "
                "on-demand baseline"
            )
        if re.search(r"optimized", exec_html, re.I) and not _NON_STACK_RE.search(exec_html):
            errors.append(
                "exec-optimization mentions Optimized but does not warn that Savings "
                "Plans / RI savings are incremental to Balanced and must not be added "
                "on top of the Optimized tier"
            )

    # Classify using only the structured opportunity name/type — never
    # `description`, which can state a product does NOT apply (see
    # _opp_classification_blob docstring).
    has_sp_opp = any(_SP_RE.search(_opp_classification_blob(item)) for item in opportunities)
    has_ri_opp = any(_RI_RE.search(_opp_classification_blob(item)) for item in opportunities)

    # Presence in the report must be a rendered opportunity row, not a
    # heading, a caveat paragraph, or a posture-comparison row that merely
    # names the product. Bind the check to the opportunity table (identified
    # by its required columns) and read only its Optimization cells, so an
    # empty opportunity <tbody> or an Optimized-tier caveat cannot substitute
    # for an actual Savings Plan / RI option row. The opportunity table lives
    # in appendix-optimization (full mode) or exec-optimization (decision mode).
    opp_cells = _opportunity_table_optimization_cells(appendix_html) + (
        _opportunity_table_optimization_cells(exec_html)
    )
    opp_row_text = "\n".join(opp_cells)

    if has_sp_opp and not _SP_RE.search(opp_row_text):
        errors.append(
            "optimization_opportunities include a Savings Plan but the opportunity "
            "table (appendix-optimization / exec-optimization) has no Savings Plans "
            "data row — a heading, caveat, or posture-comparison row does not satisfy this gate"
        )
    if has_ri_opp and not _RI_RE.search(opp_row_text):
        errors.append(
            "optimization_opportunities include a Reserved Instance (or reserved "
            "capacity/nodes) but the opportunity table (appendix-optimization / "
            "exec-optimization) has no Reserved Instances data row — a heading, caveat, "
            "or posture-comparison row does not satisfy this gate"
        )
    if (
        not has_sp_opp
        and not has_ri_opp
        and (
            _design_has_commitment_eligible(aws_design)
            or _opportunities_target_commitment_eligible(opportunities)
        )
        and not (_SP_RE.search(opp_row_text) or _RI_RE.search(opp_row_text))
    ):
        errors.append(
            "RDS, Aurora, Fargate, or Lambda is in the design (or opportunity targets) "
            "but the opportunity table has no Savings Plans or Reserved Instances row"
        )

    return errors


def _validate_share_section(
    html: str,
    estimation_infra: dict | None,
    estimation_ai: dict | None,
) -> list[str]:
    """A copy-ready leadership brief is required when estimates are available."""
    if estimation_infra is None and estimation_ai is None:
        return []
    section = _section_html(html, "exec-share")
    if section is None:
        return [
            "monthly estimation artifacts exist but no <section id=\"exec-share\"> "
            "copy-ready leadership brief was rendered"
        ]
    errors: list[str] = []
    card = re.search(
        r'<(?P<tag>div|aside)\b[^>]*class=["\'][^"\']*\bshare-card\b[^"\']*["\'][^>]*>'
        r"(?P<body>.*?)</(?P=tag)>",
        section,
        re.I | re.DOTALL,
    )
    if not card:
        errors.append('exec-share must contain a class="share-card" decision brief')
        return errors
    paragraphs = re.findall(
        r"<p\b[^>]*>(.*?)</p>", card.group("body"), re.I | re.DOTALL
    )
    if len(paragraphs) != 1:
        errors.append(
            "exec-share share-card must contain exactly one standalone <p> "
            f"(found {len(paragraphs)})"
        )
    else:
        text = unescape(re.sub(r"<[^>]+>", " ", paragraphs[0]))
        word_count = len(re.findall(r"\b[\w'-]+\b", text))
        if word_count < 20:
            errors.append(
                "exec-share share-card paragraph must contain a substantive "
                f"copy-ready brief of at least 20 words (found {word_count})"
            )
    if re.search(r"<(?:button|script|input|textarea)\b", section, re.I):
        errors.append(
            "exec-share must be a static copy-ready paragraph without buttons, "
            "scripts, or editable controls"
        )
    return errors


def _validate_appendix_config(html: str) -> list[str]:
    """When appendix-config is present, require provenance columns."""
    section = _section_html(html, "appendix-config")
    if not section:
        return []
    errors: list[str] = []
    if not re.search(r"<table\b", section, re.IGNORECASE):
        errors.append("appendix-config must contain an HTML table of configuration choices")
        return errors
    header = re.search(r"<thead\b.*?</thead>", section, re.DOTALL | re.IGNORECASE)
    if not header:
        errors.append("appendix-config table must have <thead> with column headers")
        return errors
    hdr_text = header.group(0).lower()
    if "question" not in hdr_text and "assumption" not in hdr_text:
        errors.append(
            'appendix-config table must include a "Question" or "Assumption" column (from preferences.prompt)'
        )
    if "consequence" not in hdr_text:
        errors.append(
            "appendix-config table must include a Design consequence column (from preferences.design_consequence)"
        )
    rows = _count_table_rows(section)
    if rows < 2:
        errors.append(f"appendix-config must have >=2 configuration rows (found {rows})")
    return errors


def _canonical_money(value: float) -> str:
    """Canonical display form for a dollar amount, matching the emitter's own
    rule (generate-artifacts-report.md rule 19 / the currency-formatting gate):
    monthly-scale totals (>= $2) round to the nearest whole dollar; genuinely
    small totals (< $2) keep two-decimal cents. Both the rendered figure and the
    JSON figure pass through this SAME function before comparison, so a correctly
    rounded `$113` for `112.90` matches, and the small-total exception (e.g.
    `$0.40`) is preserved instead of being truncated to `0`."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise
    # Decide precision on the ROUNDED magnitude, not the raw one, so a value that
    # rounds up ACROSS the $2 threshold canonicalizes consistently with how it
    # renders. Otherwise 1.999 (raw < 2 -> "2.00") would mismatch a displayed $2
    # (2.0 >= 2 -> "2"): both must land on "2". round() first, then classify.
    rounded_whole = int(round(v))
    if abs(rounded_whole) >= _CENTS_MEANINGFUL_BELOW:
        return str(rounded_whole)  # nearest-dollar; 112.90->113, 112.4->112, 1.999->2
    return f"{v:.2f}"  # genuinely small total: retain cents (0.40 -> "0.40")


def _normalize_money(text: str) -> str | None:
    """Reduce a rendered money string to its canonical display form for exact
    comparison against the JSON figure (same normalization on both sides via
    `_canonical_money`). '$1,415/mo' -> '1415'; '$112.90' -> '113'; '$0.40' ->
    '0.40'. Returns None when no dollar amount is present."""
    m = re.search(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text)
    if not m:
        return None
    try:
        return _canonical_money(float(m.group(1).replace(",", "")))
    except (TypeError, ValueError):
        return None


# Which estimation-infra.json figure each data-cost-key anchor must equal. The
# validator asserts every figure the emitter tagged with a data-cost-key anchor
# (generate-artifacts-report.md); an untagged *illustrative* figure is never guessed
# at. Required keys are the exception: a required figure whose JSON value exists must
# BE anchored when exec-costs is present (see _REQUIRED_COST_KEYS) — a missing anchor
# there is a FAIL, not a skip.
_COST_ANCHORS = {
    "aws_monthly_balanced": ("projected_costs", "aws_monthly_balanced"),
    "aws_monthly_premium": ("projected_costs", "aws_monthly_premium"),
    "aws_monthly_optimized": ("projected_costs", "aws_monthly_optimized"),
    "current_monthly": ("current_costs", "gcp_monthly"),
}

# Keys whose figure is load-bearing: when its JSON value exists AND the report has
# an exec-costs section, the anchor MUST be present (a missing anchor is a FAIL, not
# a skip — otherwise an un-anchored wrong figure passes, which is the bug P1-C exists
# to catch). Premium/optimized are optional (skip when absent).
_REQUIRED_COST_KEYS = ("aws_monthly_balanced", "current_monthly")

# Elements whose subtree the browser never renders — an anchor (or its text)
# inside one must never stand in for the visible figure. Mirrors
# _DecodedTextRunParser's _INERT_TAGS so the anchor collector and the currency
# text parser agree on what "rendered" means.
_ANCHOR_INERT_TAGS = {"script", "style", "template"}


class _CostAnchorParser(HTMLParser):
    """Collect the rendered text of every `data-cost-key="..."` element.

    Uses the stdlib HTML parser rather than a regex so that:
    (a) markup inside an HTML comment is never mistaken for a real anchor —
        comments are a distinct token the parser never re-tokenizes as tags;
    (b) nested child markup is read through the anchored element's OWN matching
        close tag, not the first `</` encountered, by counting nested
        opens/closes — and a NESTED `data-cost-key` element is collected as its
        own anchor too (an outer anchor being open must not swallow a recognized
        inner figure), tracked on a stack;
    (c) inert subtrees (`<script>`, `<style>`, `<template>`) are skipped — their
        content is never rendered by the browser, so an anchor or dollar token
        placed there must not satisfy the visible-figure requirement, even when
        the inert element itself carries `data-cost-key`;
    (d) an element with a truthy `hidden` attribute is skipped for the same
        reason — its subtree is not rendered.
    Character references are decoded automatically (`convert_charrefs=True`).
    """

    # Void elements never have an end tag, so they must not be pushed onto the
    # element stack (doing so would desync every subsequent close).
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[tuple[str, str]] = []  # (key, inner text), document order
        # One frame per open non-void element, innermost last. Each frame:
        #   {"tag", "inert": bool, "hidden": bool, "anchor": {key,parts}|None}
        # `inert`/`hidden` are STICKY down the subtree (an element inside an inert
        # or hidden ancestor is itself skipped) — computed as ancestor-or-self.
        self._stack: list[dict] = []

    def _in_skip(self) -> bool:
        """True when the current point is inside an inert or hidden subtree."""
        return bool(self._stack) and (self._stack[-1]["inert"] or self._stack[-1]["hidden"])

    @staticmethod
    def _is_hidden(attrs: list[tuple[str, str | None]]) -> bool:
        # `hidden` is a BOOLEAN attribute: its mere presence hides the subtree,
        # regardless of value. In HTML `hidden="false"` is NOT a not-hidden value —
        # "false" is an invalid value for a boolean attribute, whose invalid-value
        # default is the Hidden state. So any `hidden` attribute (including
        # `hidden=""`, `hidden="hidden"`, and `hidden="false"`) hides the element;
        # only the attribute's ABSENCE leaves it visible.
        return "hidden" in dict(attrs)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        parent = self._stack[-1] if self._stack else None
        # inert/hidden are STICKY: an element inside an inert/hidden ancestor is
        # itself inert/hidden. Kept as clean booleans (never a truthy list).
        inert = bool(parent and parent["inert"]) or tag in _ANCHOR_INERT_TAGS
        hidden = bool(parent and parent["hidden"]) or self._is_hidden(attrs)
        anchor = None
        key = dict(attrs).get("data-cost-key")
        # Start a new anchor only when this element is actually rendered.
        if key and not inert and not hidden:
            anchor = {"key": key.lower(), "parts": []}
        frame = {"tag": tag, "inert": inert, "hidden": hidden, "anchor": anchor}
        if tag not in self._VOID_TAGS:
            self._stack.append(frame)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _ANCHOR_INERT_TAGS or self._in_skip():
            return
        parent_hidden = self._stack[-1]["hidden"] if self._stack else False
        key = dict(attrs).get("data-cost-key")
        # A self-closed anchor has no text content; record it (empty) only if rendered.
        if key and not parent_hidden and not self._is_hidden(attrs):
            self.results.append((key.lower(), ""))

    def handle_endtag(self, tag: str) -> None:
        if tag in self._VOID_TAGS:
            return
        # Pop to the nearest matching open tag (tolerate minor misnesting). Every
        # frame in the popped slice that carried an anchor is emitted — including
        # any INNER anchors implicitly closed by an outer element's end tag — so a
        # nested `data-cost-key` is never silently dropped. Emit innermost-first,
        # then the matched frame, all in the order they closed.
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i]["tag"] == tag:
                popped = self._stack[i:]
                del self._stack[i:]
                for frame in reversed(popped):  # innermost closes first
                    if frame["anchor"] is not None:
                        self.results.append(
                            (frame["anchor"]["key"], "".join(frame["anchor"]["parts"]))
                        )
                return
        # Unmatched close tag: ignore.

    def handle_data(self, data: str) -> None:
        if self._in_skip():
            return
        # Append rendered text to every open anchor on the stack (an outer
        # anchor's text legitimately includes its children's text).
        for frame in self._stack:
            if frame["anchor"] is not None:
                frame["anchor"]["parts"].append(data)


def _cost_anchor_matches(html: str) -> list[tuple[str, str]]:
    """Parse `html` and return every (data-cost-key, rendered text) pair found
    outside comments and non-rendered markup (script/style/template/hidden),
    including nested recognized anchors."""
    parser = _CostAnchorParser()
    parser.feed(html)
    parser.close()
    return parser.results


def _dig(d: dict, path: tuple[str, ...]):
    cur = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _validate_cost_figures(
    html: str, estimation_infra: dict | None, *, require_anchors: bool = True
) -> list[str]:
    """Assert the report's cost figures match estimation-infra.json (P1-C).

    Fail direction:
    - No estimation-infra.json / not a dict -> skip (fail open on absence).
    - A REQUIRED key (aws_monthly_balanced, current_monthly) whose JSON value is
      present, when exec-costs exists, MUST carry a data-cost-key anchor -> a
      missing anchor FAILs (an un-anchored wrong figure must not pass).
    - Anchor present + JSON value present but rendered dollars differ -> FAIL.
    - Anchored element with a real JSON value but no $ amount rendered -> FAIL.
    - Non-numeric / non-whole-dollar JSON value -> FAIL (named), never a crash.
    - Unknown anchor key, or an optional key's absent JSON value -> skip.
    """
    if not isinstance(estimation_infra, dict):
        return []
    errors: list[str] = []

    for key, text in _cost_anchor_matches(html):
        key = key.lower()
        path = _COST_ANCHORS.get(key)
        if path is None:
            continue  # unknown anchor key -> not ours to assert
        expected = _dig(estimation_infra, path)
        if expected is None:
            continue  # the JSON does not carry this figure -> nothing to assert
        try:
            # Normalize the JSON figure to the SAME display precision the emitter
            # renders at (nearest dollar for monthly-scale, cents for small
            # totals) so a correctly rounded report matches — not a truncation.
            expected_dollars = _canonical_money(float(expected))
        except (TypeError, ValueError):
            errors.append(
                f'estimation-infra.json {".".join(path)} is not a numeric dollar '
                f"amount: {expected!r}"
            )
            continue
        rendered = _normalize_money(text)
        if rendered is None:
            errors.append(
                f'data-cost-key="{key}" element renders no dollar amount '
                f"(expected ${expected_dollars} from {'.'.join(path)})"
            )
            continue
        if expected_dollars != rendered:
            errors.append(
                f'cost figure mismatch: data-cost-key="{key}" renders '
                f'"${rendered}" but estimation-infra.json {".".join(path)} = '
                f"${expected_dollars}"
            )

    # Required figures must be anchored INSIDE <section id="exec-costs"> when their
    # JSON value exists and that section is rendered — per generate-artifacts-report.md
    # rule 21 ("Wrap ... in exec-costs with a data-cost-key attribute"). A redundant
    # anchor elsewhere (e.g. a decision-summary hero metric) is still cross-checked by
    # the mismatch loop above, but does not satisfy this requirement: exec-costs is the
    # section customers read as the authoritative cost comparison, and its own dollar
    # cells must be the ones a validator can hold to the estimate. Gated on
    # require_anchors so deliberately minimal unit fixtures (run with --no-require-toc)
    # are not forced to anchor; the mismatch / no-$ / non-numeric checks above always run.
    if require_anchors:
        exec_costs_html = _section_html(html, "exec-costs")
        if exec_costs_html is not None:
            exec_costs_keys = {k.lower() for k, _ in _cost_anchor_matches(exec_costs_html)}
            for key in _REQUIRED_COST_KEYS:
                path = _COST_ANCHORS[key]
                if _dig(estimation_infra, path) is None:
                    continue  # JSON does not carry it -> nothing to require
                if key not in exec_costs_keys:
                    errors.append(
                        f'missing data-cost-key="{key}" anchor inside '
                        f'<section id="exec-costs">; cannot confirm the rendered figure '
                        f"matches estimation-infra.json {'.'.join(path)} (wrap that "
                        f'figure in <span data-cost-key="{key}">...</span> inside '
                        f"exec-costs)"
                    )
    return errors


def _validate_verdict(html: str, estimation_infra: dict | None) -> list[str]:
    """When a recommendation block exists, the decision summary must state a
    one-sentence verdict in a visually distinct class="verdict" callout."""
    if not estimation_infra or not estimation_infra.get("recommendation"):
        return []
    summary = _section_html(html, "decision-summary") or ""
    if re.search(r'class="[^"]*\bverdict\b[^"]*"', summary, re.IGNORECASE):
        return []
    return [
        "recommendation block exists but decision-summary has no verdict banner "
        '(wrap the one-sentence recommendation in class="verdict")'
    ]


def _validate_activate_link(html: str) -> list[str]:
    """Keep the Activate action attached to its executive-summary benefit."""
    summary = _section_html(html, "decision-summary") or ""
    if not re.search(r"AWS\s+Activate|Activate\s+(?:Founders|Portfolio|credits)", summary, re.I):
        return []
    if re.search(
        r'href=["\']https://aws\.amazon\.com/startups/credits/?["\']',
        summary,
        re.IGNORECASE,
    ):
        return []
    return [
        "decision-summary mentions AWS Activate but has no clickable official "
        "apply link (https://aws.amazon.com/startups/credits/)"
    ]


def _validate_glossary_table(html: str) -> list[str]:
    """Full reports present terms and meanings in a scannable two-column table."""
    section = _section_html(html, "appendix-glossary")
    if section is None:
        return [
            'full report must include a dedicated <section id="appendix-glossary">'
        ]
    match = re.search(
        r'<table\b[^>]*class=["\'][^"\']*\bglossary-table\b[^"\']*["\'][^>]*>'
        r"(.*?)</table>",
        section,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return [
            'full report glossary must use <table class="glossary-table"> '
            "with distinct Term and Meaning cells"
        ]
    table = match.group(1)
    header = re.search(r"<thead\b[^>]*>(.*?)</thead>", table, re.DOTALL | re.I)
    if not header or not re.search(r">\s*Term\s*<", header.group(1), re.I) or not re.search(
        r">\s*Meaning\s*<", header.group(1), re.I
    ):
        return ['glossary-table must have "Term" and "Meaning" column headers']
    if _count_table_rows(f"<table>{table}</table>") < 3:
        return ["glossary-table must contain at least 3 term-definition rows"]
    return []


def _validate_accessibility(html: str) -> list[str]:
    """Dependency-free checks for high-value WCAG-oriented HTML semantics."""
    errors: list[str] = []
    if not re.search(r"<html\b[^>]*\blang=[\"'][a-z]{2}(?:-[A-Za-z0-9]+)?[\"']", html, re.I):
        errors.append('accessibility: <html> must declare a valid lang attribute')

    body = re.sub(r"<style\b.*?</style>", "", html, flags=re.I | re.S)
    if len(re.findall(r"<h1\b", body, re.I)) != 1:
        errors.append("accessibility: report must contain exactly one <h1>")

    for index, table_match in enumerate(re.finditer(r"<table\b[^>]*>.*?</table>", body, re.I | re.S), 1):
        table = table_match.group(0)
        if not re.search(r"<caption\b", table, re.I):
            errors.append(f"accessibility: table {index} must include a <caption>")
        for th in re.findall(r"<th\b[^>]*>", table, re.I):
            if not re.search(r"\bscope=[\"'](?:col|row)[\"']", th, re.I):
                errors.append(
                    f'accessibility: table {index} header cells must declare scope="col" or scope="row"'
                )
                break

    for index, figure_match in enumerate(
        re.finditer(r"<figure\b[^>]*>.*?</figure>", body, re.I | re.S), 1
    ):
        figure = figure_match.group(0)
        opening = re.match(r"<figure\b[^>]*>", figure, re.I)
        opening_tag = opening.group(0) if opening else ""
        if not re.search(r'\brole=["\']img["\']', opening_tag, re.I):
            errors.append(f'accessibility: figure {index} must declare role="img"')
        if not re.search(r'\baria-label=["\'][^"\']+["\']', opening_tag, re.I):
            errors.append(f"accessibility: figure {index} must have an aria-label")
        if not re.search(r"<figcaption\b", figure, re.I):
            errors.append(f"accessibility: figure {index} must include a <figcaption>")
    return errors


def _validate_fixture_bleed(html: str, migration_dir: Path | None) -> list[str]:
    """Catch agents that copied the reference fixture verbatim into a real run.

    Only active when --migration-dir is passed (i.e. validating a real
    $MIGRATION_DIR report, not the fixture itself). Fails if the fixture canary
    ID appears, or if the report's stated migration ID does not match the run dir.
    """
    if migration_dir is None:
        return []  # fixture-self-exemption: no run dir → don't flag the canary

    errors: list[str] = []
    dir_name = migration_dir.name
    body = _readability_scope(html)

    if FIXTURE_CANARY_ID in body and dir_name != FIXTURE_CANARY_ID:
        errors.append(
            f'fixture bleed: reference canary migration ID "{FIXTURE_CANARY_ID}" appears in a '
            f'real run (--migration-dir={dir_name}) — the report was copied from the fixture'
        )

    ids_in_report = {m.group(1) for m in MIGRATION_ID_RE.finditer(body)}
    if re.fullmatch(r"\d{4}-\d{4}", dir_name) and ids_in_report and dir_name not in ids_in_report:
        errors.append(
            f'migration ID mismatch: report references {sorted(ids_in_report)} but '
            f"--migration-dir is {dir_name} — verify the report belongs to this run"
        )
    return errors


def validate_report(
    html: str,
    estimation_infra: dict | None = None,
    estimation_ai: dict | None = None,
    aws_design: dict | None = None,
    *,
    require_toc: bool = True,
    check_readability: bool = True,
    migration_dir: Path | None = None,
    mode: str = "full",
) -> list[str]:
    errors: list[str] = []

    if mode == "ai_only":
        required_ids = AI_ONLY_REQUIRED_SECTION_IDS
    elif mode == "decision":
        required_ids = DECISION_REQUIRED_SECTION_IDS
    else:
        required_ids = REQUIRED_SECTION_IDS
    errors.extend(_validate_required_sections(html, required_ids))

    if mode == "decision":
        # No Generate artifacts exist at decision time: appendices are forbidden.
        counts = _section_id_counts(html)
        for sid in counts:
            if sid.startswith("appendix-"):
                errors.append(
                    f'decision mode forbids <section id="{sid}"> — the decision report '
                    "has no appendices; the full migration report (Generate) carries them"
                )

    if require_toc:
        if not _toc_hrefs(html):
            errors.append('missing <nav class="toc"> with href="#section-id" links')
        errors.extend(_validate_toc(html, required_ids))
        errors.extend(_validate_decision_first(html))

    for pattern, label in FORBIDDEN_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE):
            errors.append(f"forbidden content: {label}")

    if check_readability:
        errors.extend(_validate_readability(html))
        errors.extend(_validate_currency_formatting(html))
        errors.extend(_validate_exec_vocabulary(html))
        errors.extend(_validate_decision_language(html, estimation_infra))
        # Normal generated reports require a TOC. Use the same signal to
        # enforce the visual shell while preserving --no-require-toc as the
        # lightweight escape hatch for deliberately minimal unit fixtures.
        if require_toc:
            errors.extend(_validate_visual_contract(html))
    # Accessibility semantics are independent of prose/readability checks.
    # --no-require-toc remains the deliberate escape hatch for minimal unit
    # fixtures, but --no-readability must never disable HTML accessibility.
    if require_toc:
        errors.extend(_validate_accessibility(html))

    for section_id, min_depth in MIN_CONTENT_DEPTH.items():
        section = _section_html(html, section_id)
        if section is None:
            continue
        depth = _section_content_depth(section_id, section)
        if depth < min_depth:
            errors.append(
                f"appendix section id={section_id} has insufficient content ({depth}), "
                f"need >= {min_depth}"
            )

    for stub in APPENDIX_STUB_PATTERNS:
        if stub.search(html):
            errors.append(
                "appendix appears to be a stub (links to JSON only) — "
                "expand per generate-artifacts-report.md"
            )

    if "draft for review" not in html.lower():
        errors.append('footer must contain "draft for review" disclaimer')

    if estimation_infra and estimation_infra.get("projected_costs", {}).get("breakdown", {}).get(
        "security_baseline"
    ):
        ok, msg = _has_guardduty_or_baseline(html, estimation_infra)
        if not ok:
            errors.append(msg)

    # Combined AWS monthly run-rate section required only when BOTH estimate
    # artifacts exist (not AI-only runs). exec-tco is a legacy structural ID.
    if estimation_infra is not None and estimation_ai is not None:
        counts = _section_id_counts(html)
        if counts.get("exec-tco", 0) != 1:
            errors.append(
                "when both estimation-infra.json and estimation-ai.json exist, "
                'include exactly one <section id="exec-tco"> with the combined '
                "infra+AI estimated AWS monthly run rate"
            )

    # Security teaser must exist in the exec flow when a baseline is estimated.
    errors.extend(_validate_security_teaser(html, estimation_infra))

    # Decision summary must state a one-sentence verdict when a recommendation exists.
    errors.extend(_validate_verdict(html, estimation_infra))
    errors.extend(
        _validate_cost_figures(html, estimation_infra, require_anchors=require_toc)
    )
    errors.extend(_validate_activate_link(html))
    if require_toc:
        errors.extend(_validate_share_section(html, estimation_infra, estimation_ai))
    if mode in ("full", "ai_only") and require_toc:
        errors.extend(_validate_glossary_table(html))

    # Ordered action lists and configuration provenance (when sections present).
    errors.extend(_validate_action_lists(html))
    errors.extend(_validate_appendix_config(html))

    # Dedicated Cost Optimization section when Estimate emitted opportunities.
    errors.extend(
        _validate_optimization_sections(
            html,
            estimation_infra,
            estimation_ai,
            aws_design,
            mode=mode,
            require_toc=require_toc,
        )
    )

    # Catch verbatim copies of the reference fixture into a real run.
    errors.extend(_validate_fixture_bleed(html, migration_dir))

    # What-if workshop scenario table — required when ≥2 scenarios were snapshotted.
    if migration_dir is not None:
        index_path = migration_dir / "scenarios" / "index.json"
        if index_path.is_file():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                index = None
            scenarios = (index or {}).get("scenarios") or []
            counts = _section_id_counts(html)
            if len(scenarios) >= 2 and counts.get("what-if-scenarios", 0) < 1:
                errors.append(
                    'scenarios/index.json has ≥2 scenarios but no '
                    '<section id="what-if-scenarios"> (workshop compare table is '
                    "required in the migration report when variants exist)"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate migration-report.html")
    parser.add_argument("report_path", type=Path, help="Path to migration-report.html")
    parser.add_argument("--estimation-infra", type=Path, default=None)
    parser.add_argument("--estimation-ai", type=Path, default=None)
    parser.add_argument(
        "--aws-design",
        type=Path,
        default=None,
        help="aws-design.json. When RDS/Aurora/Fargate/Lambda is in the design, "
        "the Cost Optimization section must include a Savings Plan or Reserved "
        "Instance row if optimization_opportunities exist.",
    )
    parser.add_argument(
        "--migration-dir",
        type=Path,
        default=None,
        help="Migration output dir ($MIGRATION_DIR). Enables fixture-bleed detection: "
        "the report's migration ID must match this folder, and the reference fixture's "
        "canary ID must not appear in a real run.",
    )
    parser.add_argument(
        "--no-require-toc",
        action="store_true",
        help="Skip TOC requirement (for minimal test fixtures)",
    )
    parser.add_argument(
        "--no-readability",
        action="store_true",
        help="Skip customer-facing readability checks (Rubric:/Section N/intensifiers/dates)",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "decision", "ai_only"],
        default="full",
        help="full = migration-report.html (default); decision = decision-report.html "
        "written at the post-Estimate Decision gate (exec sections + CTA, no appendices)",
    )
    args = parser.parse_args()

    if not args.report_path.is_file():
        print(f"REPORT_FAIL | file={args.report_path} | reason=not_found", file=sys.stderr)
        return 1

    html = args.report_path.read_text(encoding="utf-8")

    estimation_infra = None
    if args.estimation_infra and args.estimation_infra.is_file():
        estimation_infra = json.loads(args.estimation_infra.read_text(encoding="utf-8"))

    estimation_ai = None
    if args.estimation_ai and args.estimation_ai.is_file():
        estimation_ai = json.loads(args.estimation_ai.read_text(encoding="utf-8"))

    aws_design = None
    if args.aws_design and args.aws_design.is_file():
        aws_design = json.loads(args.aws_design.read_text(encoding="utf-8"))

    errors = validate_report(
        html,
        estimation_infra,
        estimation_ai,
        aws_design,
        require_toc=not args.no_require_toc,
        check_readability=not args.no_readability,
        migration_dir=args.migration_dir,
        mode=args.mode,
    )
    if errors:
        print("REPORT_FAIL | migration-report.html", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    counts = _section_id_counts(html)
    optional_present = [sid for sid in OPTIONAL_SECTION_IDS if counts.get(sid, 0) >= 1]
    required_count = len(
        AI_ONLY_REQUIRED_SECTION_IDS
        if args.mode == "ai_only"
        else DECISION_REQUIRED_SECTION_IDS
        if args.mode == "decision"
        else REQUIRED_SECTION_IDS
    )
    mode_tag = "" if args.mode == "full" else f"mode={args.mode} | "
    print(
        f"REPORT_OK | {mode_tag}structure=complete | sections="
        + str(required_count)
        + f"/{required_count}"
        + (f" | optional={','.join(optional_present)}" if optional_present else "")
        + " | note=verify dollar figures against estimation JSON before sign-off"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
