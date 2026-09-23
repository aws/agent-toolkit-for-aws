#!/usr/bin/env python3
"""Validate heroku-to-aws migration-report.html (thin stakeholder report).

Required sections: decision-summary, exec-costs, cost-optimization, next-steps.
Conditional: what-if-scenarios when scenarios/index.json has ≥2 entries.
Footer must contain "draft for review".

Also enforces the report's own decision-UX and a11y contract (ported subset of
the gcp-to-aws report validator, #223 — gated to what the Heroku one-pager
actually emits):
  - decision-summary must NOT contain any badge-verdict-* pill (the skeleton mandates
    a typography-first `verdict-headline`; color-only verdict carriers are banned).
  - when estimation-infra.json declares recommendation.outcome, decision-summary
    must contain a `verdict-headline` element.
  - <html> must declare a lang attribute; any <th> must declare scope=col|row;
    any <figure> must carry aria-label + <figcaption>.

Deliberately NOT enforced (would false-fail the intentionally-thin Heroku
report, whose skeleton puts <nav class="toc"> before the verdict and emits no
<h1> / table <caption>): decision-before-TOC ordering, single-<h1>, per-table
<caption>, glossary/appendix set.

Exit 0 on PASS, 1 on FAIL.

Usage:
  python3 validate-heroku-migration-report.py /path/to/migration-report.html \\
      --migration-dir "$MIGRATION_DIR"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# Sections required in BOTH report modes. cost-optimization is required in full
# mode only (see _required_sections) — the decision pack is pre-execution and does
# not carry the optimization table.
COMMON_REQUIRED_SECTION_IDS = [
    "decision-summary",
    "exec-costs",
]
# The structural difference between modes: full (migration-report.html) ends on a
# next-steps list AND carries cost-optimization; decision (decision-report.html) ends
# on a decision-cta pointing at Generate (next-steps assumes MIGRATION_GUIDE.md /
# terraform/ already exist — they don't yet in decision mode).
MODE_REQUIRED_SECTION_ID = {
    "full": "next-steps",
    "decision": "decision-cta",
}


def _required_sections(mode: str) -> list[str]:
    required = [*COMMON_REQUIRED_SECTION_IDS, MODE_REQUIRED_SECTION_ID[mode]]
    if mode == "full":
        required.append("cost-optimization")
    return required

# Section identity/count/fragment come from the stdlib HTML parser, never a
# raw-source regex, so that:
#   - a <section id="..."> that exists ONLY inside an HTML comment (e.g. the
#     skeleton's commented `<!-- <section id="what-if-scenarios"> -->` placeholder)
#     is never counted — HTMLParser routes comment text to handle_comment and
#     never re-tokenizes it as a tag;
#   - a section wrapped in an inert subtree (<template>/<script>/<style>) is not
#     counted — it is never rendered, so it must not satisfy a required-section
#     gate, and its inner HTML is not returned as a section fragment;
#   - the real `id` attribute is read regardless of spelling (quoted, unquoted,
#     or spaced `id = "x"`), and a `data-id` (or any non-`id` attribute) is NOT
#     mistaken for the section id;
#   - a duplicate that exists only in a comment does not inflate the count.
_SECTION_INERT_TAGS = {"script", "style", "template"}


class _SectionParser(HTMLParser):
    """Parse rendered <section> structure: per-id counts and inner-HTML fragments,
    excluding comments and inert (script/style/template) subtrees."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)  # keep raw text/entities in fragments
        self.counts: dict[str, int] = {}
        # Captured fragments: id -> list of inner-HTML strings (document order).
        self.fragments: dict[str, list[str]] = {}
        self._inert_depth = 0
        # Stack of open sections we are capturing: each {id, parts, seen_depth}.
        self._open_sections: list[dict] = []
        self._section_depth = 0  # nesting depth of <section> (for fragment close)

    def _emit(self, markup: str) -> None:
        # Append raw markup to every section fragment currently being captured.
        for s in self._open_sections:
            s["parts"].append(markup)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SECTION_INERT_TAGS:
            self._inert_depth += 1
            return
        if self._inert_depth > 0:
            return  # inside an inert subtree — not rendered
        if tag == "section":
            sid = dict(attrs).get("id")
            self._section_depth += 1
            if sid:
                self.counts[sid] = self.counts.get(sid, 0) + 1
                self.fragments.setdefault(sid, [])
                self._open_sections.append(
                    {"id": sid, "parts": [], "depth": self._section_depth}
                )
            return
        self._emit(self.get_starttag_text() or "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SECTION_INERT_TAGS or self._inert_depth > 0:
            return
        if tag == "section":
            sid = dict(attrs).get("id")
            if sid:
                self.counts[sid] = self.counts.get(sid, 0) + 1
                self.fragments.setdefault(sid, []).append("")
            return
        self._emit(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SECTION_INERT_TAGS:
            if self._inert_depth > 0:
                self._inert_depth -= 1
            return
        if self._inert_depth > 0:
            return
        if tag == "section":
            # Close the innermost open captured section at this depth.
            while self._open_sections and self._open_sections[-1]["depth"] >= self._section_depth:
                done = self._open_sections.pop()
                self.fragments.setdefault(done["id"], []).append("".join(done["parts"]))
            if self._section_depth > 0:
                self._section_depth -= 1
            return
        self._emit(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._inert_depth == 0:
            self._emit(data)

    def handle_entityref(self, name: str) -> None:
        if self._inert_depth == 0:
            self._emit(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._inert_depth == 0:
            self._emit(f"&#{name};")


def _parse_sections(html: str) -> _SectionParser:
    parser = _SectionParser()
    parser.feed(html)
    parser.close()
    return parser


def _section_counts(html: str) -> dict[str, int]:
    """Count rendered <section id> occurrences (comments/inert excluded)."""
    return _parse_sections(html).counts


def _section_html(html: str, section_id: str) -> str | None:
    """Return the inner HTML of the first rendered <section id="section_id">,
    or None when it is absent (or exists only in a comment/inert subtree). A
    nested <section> does not truncate early — the parser closes on the
    matching depth."""
    frags = _parse_sections(html).fragments.get(section_id)
    if not frags:
        return None
    return frags[0]


def _body_scope(html: str) -> str:
    """Body only, excluding <style> blocks, so CSS hex/decimal values never
    trip the currency-formatting check (mirrors the GCP validator's
    _readability_scope)."""
    no_style = re.sub(r"<style\b.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    body = re.search(r"<body\b[^>]*>(.*?)</body>", no_style, re.DOTALL | re.IGNORECASE)
    return body.group(1) if body else no_style


# Ported from validate-migration-report.py — same currency-formatting rule
# (monthly figures render as whole dollars; cents are reserved for genuinely
# sub-dollar precision or per-unit rates). See that file's comment for the
# full rationale; kept identical here so both validators stay in sync. The
# Heroku report has no documented Calculation/Notes column (its exec-costs
# section is a Heroku-vs-AWS side-by-side or three-tier table, per
# generate-report.md — no per-service arithmetic show-work column), so this
# copy has no calc-column exemption; everything else ports unchanged.
CENTS_RE = re.compile(r"\$([0-9][0-9,]*)\.([0-9]{2})\b")

# Deliberately does NOT accept a BARE "month"/"mo" as itself the qualifying
# unit — see validate-migration-report.py's _RATE_SUFFIX_RE comment for the
# full rationale (a bare "/mo" is exactly the unit an ordinary monthly total
# is denominated in, not evidence of a per-unit rate). "/mo per <unit>" is
# still accepted (e.g. "$5.00/mo per policy").
_RATE_SUFFIX_RE = re.compile(
    r"^\s*(?:/|\(|\bper\b)?\s*(?:mo\b\s*(?:per\b\s*)?)?"
    r"(?:hr|hour|hourly|vcpu|gb|gib|tb|image|unit|policy|1m|10k|"
    r"[0-9]+-mo)\b",
    re.IGNORECASE,
)

_CENTS_MEANINGFUL_BELOW = 2


class _DecodedTextParser(HTMLParser):
    """Extract rendered text as the browser would present it — entities
    decoded, comments and inert content (script/style/template) excluded —
    while preserving amount/unit adjacency across inline markup (mirrors
    validate-migration-report.py's _DecodedTextRunParser; see that file's
    class docstring for the full rationale). No Calculation/Notes column
    tracking here — the Heroku report has no such column."""

    _INLINE_TAGS = {
        "a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em",
        "i", "kbd", "mark", "q", "s", "samp", "small", "span", "strong",
        "sub", "sup", "time", "u", "var", "wbr",
    }
    _INERT_TAGS = {"script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._inert_depth = 0
        # Absolute offsets (into text()) of every block-level separator — a
        # rate-suffix match must never read past one of these into unrelated
        # content from a different cell/row/paragraph (see
        # validate-migration-report.py's identical tracking for the full
        # rationale — a single separating space does not itself stop a
        # word-based regex when the next block happens to start with a real
        # rate-unit word like "Hourly").
        self._boundaries: list[int] = []

    def _append(self, text: str, *, is_boundary: bool = False) -> None:
        if not text:
            return
        if is_boundary:
            self._boundaries.append(sum(len(p) for p in self._parts))
        self._parts.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._INERT_TAGS:
            self._inert_depth += 1
            return
        if self._inert_depth == 0 and tag not in self._INLINE_TAGS:
            self._append(" ", is_boundary=True)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self._INLINE_TAGS and tag not in self._INERT_TAGS:
            self._append(" ", is_boundary=True)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._INERT_TAGS:
            if self._inert_depth > 0:
                self._inert_depth -= 1
            return
        if self._inert_depth == 0 and tag not in self._INLINE_TAGS:
            self._append(" ", is_boundary=True)

    def handle_data(self, data: str) -> None:
        if self._inert_depth == 0:
            self._append(data)

    def text(self) -> str:
        return "".join(self._parts)

    def boundaries(self) -> list[int]:
        return self._boundaries


def _decoded_text(html: str) -> tuple[str, list[int]]:
    parser = _DecodedTextParser()
    parser.feed(_body_scope(html))
    parser.close()
    return parser.text(), parser.boundaries()


def _validate_currency_formatting(html: str) -> list[str]:
    """Monthly cost figures must render as whole dollars. Flag any $X.YY
    figure whose whole-dollar part is >= $2 and that is not immediately
    followed by a per-unit-rate suffix (/hr, per policy, etc.)."""
    errors: list[str] = []
    text, boundaries = _decoded_text(html)
    seen: set[str] = set()
    for match in CENTS_RE.finditer(text):
        whole = int(match.group(1).replace(",", ""))
        if whole < _CENTS_MEANINGFUL_BELOW:
            continue
        cutoff = match.end() + 25
        for boundary in boundaries:
            if boundary >= match.end():
                cutoff = min(cutoff, boundary)
                break
        trailing = text[match.end():cutoff]
        if _RATE_SUFFIX_RE.match(trailing):
            continue
        token = match.group(0)
        if token in seen:
            continue
        seen.add(token)
        errors.append(
            f'currency formatting: "{token}" renders cents on a monthly-scale '
            "figure — round to a whole dollar (cents only for genuinely "
            'sub-dollar precision, e.g. "$1.50", "$0.40", or a per-unit rate '
            'like "$0.018/hr")'
        )
    return errors


class _TagAttrCollector(HTMLParser):
    """Collect (tag, attrs-dict, is_self_closed) for every RENDERED start tag,
    using the stdlib parser rather than a literal-syntax regex. This accepts any
    legal HTML attribute spelling — quoted or unquoted values, spaces around `=`,
    single or double quotes — instead of only the exact `name="value"` form a
    hand-rolled regex happens to match.

    Tags inside an inert subtree (`<script>`, `<style>`, `<template>`) are
    skipped — the browser never renders them, so a class/attribute declared only
    there (e.g. a `verdict-headline` inside a `<template>`) must not be read as a
    rendered element. Mirrors _DecodedTextParser's inert handling so every
    "is this rendered?" check in this file agrees on the answer."""

    _INERT_TAGS = {"script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str | None], bool]] = []
        self._inert_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._INERT_TAGS:
            self._inert_depth += 1
            return
        if self._inert_depth == 0:
            self.tags.append((tag, dict(attrs), False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # A self-closed inert tag opens no subtree; a self-closed normal tag is a
        # rendered element (unless nested in an inert subtree).
        if tag in self._INERT_TAGS:
            return
        if self._inert_depth == 0:
            self.tags.append((tag, dict(attrs), True))

    def handle_endtag(self, tag: str) -> None:
        if tag in self._INERT_TAGS and self._inert_depth > 0:
            self._inert_depth -= 1


def _collect_tags(html: str) -> list[tuple[str, dict[str, str | None], bool]]:
    parser = _TagAttrCollector()
    parser.feed(html)
    parser.close()
    return parser.tags


def _html_lang_declared(html: str) -> bool:
    for tag, attrs, _ in _collect_tags(html):
        if tag != "html":
            continue
        lang = attrs.get("lang")
        return bool(lang) and bool(re.fullmatch(r"[a-z]{2}(?:-[A-Za-z0-9]+)?", lang, re.IGNORECASE))
    return False


NO_ELIGIBLE_COMMITMENT_SENTENCE = (
    "no 1-year/3-year commitment product applies to this architecture"
)


class _OpportunityRowParser(HTMLParser):
    """Stdlib-parser scan for a populated <td> inside a <table> — parses actual
    table structure rather than matching raw HTML source, so it:
      - decodes character references (convert_charrefs=True) before text is
        seen, so a cell containing only "&nbsp;"/"&#160;" is correctly treated
        as blank rather than non-empty literal markup;
      - never sees text inside HTML comments (HTMLParser's tokenizer routes
        comments to handle_comment, not handle_data), so a commented-out
        <tr>...</tr> can never register as a populated row;
      - tracks "inside <table>, inside <tr>, inside <td>" state directly,
        without requiring an explicit <tbody> — a <table><tr><td> with no
        <tbody> is valid HTML (browsers infer an implicit tbody) and must be
        treated the same as one with an explicit <tbody>.
    <th> cells are deliberately excluded — header rows never count as an
    opportunity row, regardless of tbody/thead placement.

    Inert subtrees (`<script>`, `<style>`, `<template>`) are skipped entirely:
    text inside them is never rendered, so a cell whose only content is a
    `<template>`/`<script>`, or a whole table nested in a `<template>`, must not
    register as a populated opportunity row. Mirrors _DecodedTextParser's inert
    handling so this check agrees with the fallback-sentence check on what
    counts as rendered content."""

    _INERT_TAGS = {"script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found = False
        self._table_depth = 0
        self._tr_depth = 0
        self._td_open = False  # a <td> is currently open (its end tag may be omitted)
        self._td_has_text = False
        self._inert_depth = 0  # >0 while inside script/style/template

    def _in_table(self) -> bool:
        return self._table_depth > 0

    def _close_cell(self) -> None:
        """Finalize whatever <td> is currently open, exactly as a real HTML
        parser would when the cell's end tag is omitted: the HTML Standard
        permits a <td> end tag to be omitted immediately before the next
        <td>/<th>, or before its parent <tr>/<table> closes. Only checking
        text on an EXPLICIT handle_endtag("td") missed every cell written
        with an omitted end tag (e.g. `<table><tr><td>text</tr></table>`,
        which never fires handle_endtag("td") at all) — a populated,
        perfectly valid compact table would then silently register as
        empty."""
        if self._td_open and self._td_has_text:
            self.found = True
        self._td_open = False
        self._td_has_text = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._INERT_TAGS:
            self._inert_depth += 1
            return
        if self._inert_depth > 0:
            return  # table/row/cell structure inside an inert subtree is not rendered
        if tag == "table":
            self._table_depth += 1
        elif tag == "tr" and self._in_table():
            self._close_cell()  # any cell open from a previous row must not leak across rows
            self._tr_depth += 1
        elif tag in ("td", "th") and self._tr_depth > 0:
            self._close_cell()  # a new cell always implicitly closes any sibling cell still open
            if tag == "td":
                self._td_open = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._INERT_TAGS or self._inert_depth > 0:
            return
        if tag in ("td", "th") and self._tr_depth > 0:
            self._close_cell()  # a self-closed <td/> or <th/> can never carry text content

    def handle_endtag(self, tag: str) -> None:
        if tag in self._INERT_TAGS:
            if self._inert_depth > 0:
                self._inert_depth -= 1
            return
        if self._inert_depth > 0:
            return
        if tag in ("td", "th"):
            self._close_cell()
        elif tag == "tr":
            self._close_cell()
            if self._tr_depth > 0:
                self._tr_depth -= 1
        elif tag == "table":
            self._close_cell()
            if self._table_depth > 0:
                self._table_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._inert_depth == 0 and self._td_open and data.strip():
            self._td_has_text = True


def _has_populated_opportunity_row(body: str) -> bool:
    """True if any <tr> inside a <table> has a <td> (not <th>) with non-empty
    text content — i.e. an actual opportunity row, not just a header row, an
    empty cell, a whitespace-only/entity-only cell, or a commented-out row."""
    parser = _OpportunityRowParser()
    parser.feed(body)
    parser.close()
    return parser.found


def _validate_optimization_content(body: str) -> list[str]:
    """The cost-optimization section must render EITHER a populated opportunities
    table (a real <tbody> row with data) OR the explicit no-eligible-commitment
    sentence — nothing else counts as content. This is a positive check, not
    "any leftover text after stripping headings/<th>": that older approach let a
    heading, column headers, AND any other prose (e.g. the credits disclaimer
    that accompanies a populated table, or explanatory filler) satisfy the
    requirement even with an empty <tbody>. Only a real opportunity row or the
    literal no-eligible sentence can pass."""
    if _has_populated_opportunity_row(body):
        return []
    # Extract the RENDERED text (entities decoded, comments and inert
    # script/style/template excluded) rather than raw-regex-stripping tags — so
    # the fallback sentence is recognized when written with entity escapes
    # (`1&#45;year`, `&nbsp;` between words) and is NOT satisfied by a copy that
    # exists only inside an HTML comment or <template> the browser never renders.
    # Reuses the same _DecodedTextParser the currency check uses, so both agree
    # on what "rendered" means.
    parser = _DecodedTextParser()
    parser.feed(body)
    parser.close()
    # Normalize decoded whitespace (incl. NBSP U+00A0 from `&nbsp;`) to single
    # spaces so an entity-separated sentence matches the literal one.
    text = re.sub(r"\s+", " ", parser.text().replace("\u00a0", " ")).strip().lower()
    if NO_ELIGIBLE_COMMITMENT_SENTENCE in text:
        return []
    return [
        '<section id="cost-optimization"> has no substantive content — render a '
        "populated opportunity row (not just column headers, an empty <tbody>, or "
        "other prose like the credits disclaimer) or the exact "
        f'"{NO_ELIGIBLE_COMMITMENT_SENTENCE}" sentence, never a blank, '
        "heading-only, or table-header-only section"
    ]


def _class_tokens(html_fragment: str) -> set[str]:
    """Return the set of all `class` attribute tokens across every tag in the
    fragment, parsed via the stdlib HTMLParser (the same approach already used
    for lang/scope/aria-label) rather than a literal `class="value"` regex. This
    accepts any legal spelling — `class="a b"`, `class = "a b"`, or an unquoted
    single token like `class=verdict-headline` — so equivalent HTML always
    produces the same tokens regardless of formatting."""
    tokens: set[str] = set()
    for _, attrs, _ in _collect_tags(html_fragment):
        cls = attrs.get("class")
        if cls:
            tokens.update(cls.split())
    return tokens


def _validate_verdict(html: str, migration_dir: Path | None) -> list[str]:
    """Typography-first verdict rules (skill: verdict is the section thesis and
    must never be a colored-pill row)."""
    errors: list[str] = []
    summary = _section_html(html, "decision-summary")
    if summary is None:
        return errors  # missing-section already reported by the required-ID check

    summary_classes = _class_tokens(summary)

    # Colored pill badges are banned outright (not merely as the "sole" carrier).
    if any(token.startswith("badge-verdict-") for token in summary_classes):
        errors.append(
            'decision-summary must use a typography-first verdict-headline, '
            "not badge-verdict-* pills (meaning must not depend on color alone)"
        )

    # When Estimate declared a recommendation outcome, the verdict headline is required.
    recommendation_outcome = False
    if migration_dir is not None:
        est_path = migration_dir / "estimation-infra.json"
        if est_path.is_file():
            try:
                est = json.loads(est_path.read_text(encoding="utf-8"))
                rec = (est or {}).get("recommendation") or {}
                recommendation_outcome = bool(rec.get("outcome"))
            except (OSError, json.JSONDecodeError):
                # Fail open on ambiguity: a missing/corrupt estimate does not force the
                # verdict-headline requirement (we can't confirm an outcome was declared).
                recommendation_outcome = False
    if recommendation_outcome and "verdict-headline" not in summary_classes:
        errors.append(
            "estimation-infra.json declares recommendation.outcome but "
            "decision-summary has no verdict-headline element "
            '(render outcome_label as <p class="verdict-headline">…</p>)'
        )
    return errors


class _AccessibilityParser(HTMLParser):
    """Stdlib-parser accessibility scan: <th scope> and <figure aria-label> +
    <figcaption>. Using the parser (rather than a literal `name="value"` regex)
    accepts any legal HTML attribute syntax — `scope=col`, `scope = "col"`,
    single quotes, etc. — the same attribute in different valid spellings must
    not flip a validator result. VOID_ELEMENTS avoids mis-tracking self-closing
    tags (e.g. <br>) as unclosed ancestors."""

    VOID_ELEMENTS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    _INERT_TAGS = {"script", "style", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.table_issues: list[int] = []  # 1-based table index with a scope-less <th>
        self.figure_issues: list[tuple[int, bool, bool]] = []  # (index, has_aria_label, has_figcaption)
        self._table_index = 0
        self._figure_index = 0
        self._table_depth = 0  # >0 while inside a <table> (nesting-tolerant)
        self._table_bad_at: dict[int, bool] = {}
        self._figure_stack: list[dict[str, bool | None]] = []
        self._inert_depth = 0  # >0 while inside script/style/template

    def _in_table(self) -> bool:
        return self._table_depth > 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._INERT_TAGS:
            self._inert_depth += 1
            return
        if self._inert_depth > 0:
            return  # a <th>/<figure> inside an inert subtree is not rendered — do not audit it
        attr_map = dict(attrs)
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._table_index += 1
                self._table_bad_at[self._table_index] = False
        elif tag == "th" and self._in_table():
            scope = attr_map.get("scope")
            if not (scope and scope.lower() in ("col", "row")):
                self._table_bad_at[self._table_index] = True
        elif tag == "figure":
            self._figure_index += 1
            aria_label = attr_map.get("aria-label")
            self._figure_stack.append(
                {
                    "index": self._figure_index,
                    "has_aria_label": bool(aria_label and aria_label.strip()),
                    "has_figcaption": False,
                }
            )
        elif tag == "figcaption" and self._figure_stack:
            self._figure_stack[-1]["has_figcaption"] = True
        if tag not in self.VOID_ELEMENTS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closed tags never open a scope for descendants (e.g. a self-closed
        # <figure /> can never contain a <figcaption>) — handled naturally since
        # we don't push onto self.stack or self._figure_stack for these.
        pass

    def handle_endtag(self, tag: str) -> None:
        if tag in self._INERT_TAGS:
            if self._inert_depth > 0:
                self._inert_depth -= 1
            return
        if self._inert_depth > 0:
            return
        if tag == "table" and self._table_depth > 0:
            self._table_depth -= 1
            if self._table_depth == 0:
                if self._table_bad_at.get(self._table_index):
                    self.table_issues.append(self._table_index)
        elif tag == "figure" and self._figure_stack:
            fig = self._figure_stack.pop()
            self.figure_issues.append(
                (fig["index"], fig["has_aria_label"], fig["has_figcaption"])
            )
        while self.stack and tag in self.stack:
            popped = self.stack.pop()
            if popped == tag:
                break


def _validate_accessibility(html: str) -> list[str]:
    """Dependency-free WCAG-oriented semantics — the safe subset the Heroku
    one-pager emits (no single-<h1> / per-table-<caption> requirement)."""
    errors: list[str] = []
    if not _html_lang_declared(html):
        errors.append("accessibility: <html> must declare a valid lang attribute")

    body = re.sub(r"<style\b.*?</style>", "", html, flags=re.IGNORECASE | re.DOTALL)
    parser = _AccessibilityParser()
    parser.feed(body)
    parser.close()

    for index in parser.table_issues:
        errors.append(
            f'accessibility: table {index} header cells must declare '
            'scope="col" or scope="row"'
        )

    for index, has_aria_label, has_figcaption in parser.figure_issues:
        if not has_aria_label:
            errors.append(f"accessibility: figure {index} must have an aria-label")
        if not has_figcaption:
            errors.append(f"accessibility: figure {index} must include a <figcaption>")
    return errors


def validate(html: str, migration_dir: Path | None, mode: str = "full") -> list[str]:
    errors: list[str] = []
    counts = _section_counts(html)

    for sid in _required_sections(mode):
        n = counts.get(sid, 0)
        if n == 0:
            errors.append(f'missing required <section id="{sid}">')
        elif n > 1:
            errors.append(f'duplicate <section id="{sid}"> ({n} occurrences)')

    # The other mode's terminal section must NOT appear — decision-report.html must
    # not carry a next-steps pointer into an execution pack that does not exist yet,
    # and migration-report.html must not carry the pre-execution decision-cta once the
    # real next-steps exists.
    other_mode = "decision" if mode == "full" else "full"
    other_terminal = MODE_REQUIRED_SECTION_ID[other_mode]
    if counts.get(other_terminal, 0) >= 1:
        errors.append(
            f'--mode {mode} report must not contain <section id="{other_terminal}"> '
            f"(that is the {other_mode}-mode terminal section)"
        )

    if "draft for review" not in html.lower():
        errors.append('footer must contain "draft for review" disclaimer')

    errors.extend(_validate_currency_formatting(html))

    # cost-optimization must carry substantive content (generate-report.md Step 3
    # item 6: a table of real opportunity rows, or the explicit no-eligible-commitment
    # sentence — never empty, and never satisfied by a heading or table-header text
    # alone). A heading like "Cost Optimization Opportunities" or a table with only
    # column headers and an empty <tbody> must not pass as content. Full mode only —
    # the decision pack carries no optimization table.
    if mode == "full" and counts.get("cost-optimization", 0) >= 1:
        body = _section_html(html, "cost-optimization") or ""
        errors.extend(_validate_optimization_content(body))

    errors.extend(_validate_verdict(html, migration_dir))
    errors.extend(_validate_accessibility(html))

    if migration_dir is not None:
        index_path = migration_dir / "scenarios" / "index.json"
        if index_path.is_file():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                index = None
            scenarios = (index or {}).get("scenarios") or []
            if len(scenarios) >= 2 and counts.get("what-if-scenarios", 0) < 1:
                errors.append(
                    'scenarios/index.json has ≥2 scenarios but no '
                    '<section id="what-if-scenarios">'
                )

        # generate-report.md / report-decision-core.md § decision-basis: when Estimate
        # declared decision_basis (evidence/assumptions behind the verdict), the report
        # MUST render it — in both modes, since decision mode reuses these exact content
        # rules. Read the same estimation-infra.json the report was built from, so a
        # report that silently drops decision-basis cannot still say REPORT_OK.
        est_path = migration_dir / "estimation-infra.json"
        if est_path.is_file():
            try:
                est = json.loads(est_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                est = None
            decision_basis = ((est or {}).get("recommendation") or {}).get("decision_basis")
            if decision_basis and counts.get("decision-basis", 0) < 1:
                errors.append(
                    "estimation-infra.json declares recommendation.decision_basis "
                    'but the report has no <section id="decision-basis"> '
                    '("What This Assessment Rests On")'
                )

    if mode == "decision" and migration_dir is not None:
        # Decision mode's invariant: THIS decide-complete cycle has not itself gone
        # through Generate yet (phases.generate is "pending"/absent). It is NOT "no
        # terraform/ file exists" — a prior Generate/workshop-reprice cycle's execution
        # pack can legitimately still be on disk (workshop re-entry preserves it). The
        # signal is .phase-status.json's own bookkeeping, not the filesystem.
        #
        # Fail open ONLY on a genuinely MISSING status file (no run ever tracked state
        # here, e.g. the isolated unit-test path). Do NOT fail open on a file that
        # EXISTS but is unreadable/invalid JSON: that is corruption, and INTERPRETER.md
        # § State-file validation says invalid JSON is a STOP condition, not "no state."
        phase_path = migration_dir / ".phase-status.json"
        generate_status: str | None = None
        if phase_path.is_file():
            try:
                phase_text = phase_path.read_text(encoding="utf-8")
                if not phase_text.strip():
                    raise json.JSONDecodeError("empty file", phase_text, 0)
                phase = json.loads(phase_text)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(
                    "decision mode: .phase-status.json exists but could not be "
                    f"read/parsed ({exc}) — state corrupted (invalid JSON). Delete the "
                    "file and restart the current phase (INTERPRETER.md § State-file "
                    "validation); an unreadable state file is not evidence of a "
                    "pre-execution decision"
                )
            else:
                generate_status = (phase or {}).get("phases", {}).get("generate")
        if generate_status in ("completed", "in_progress"):
            errors.append(
                "decision mode: .phase-status.json phases.generate is "
                f"{generate_status!r} — this decide-complete cycle already went through "
                "Generate; decision mode is pre-execution only for the CURRENT cycle (a "
                "prior cycle's execution pack may legitimately remain on disk after a "
                "workshop reprice)"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_path", type=Path)
    parser.add_argument("--migration-dir", type=Path, default=None)
    parser.add_argument(
        "--mode",
        choices=["full", "decision"],
        default="full",
        help="full = migration-report.html (default); decision = decision-report.html",
    )
    args = parser.parse_args()

    if not args.report_path.is_file():
        print(f"REPORT_FAIL | file={args.report_path} | reason=not_found", file=sys.stderr)
        return 1

    html = args.report_path.read_text(encoding="utf-8")
    errors = validate(html, args.migration_dir, args.mode)
    if errors:
        print(f"REPORT_FAIL | file={args.report_path} | errors={len(errors)}", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    counts = _section_counts(html)
    optional = []
    if counts.get("what-if-scenarios", 0) >= 1:
        optional.append("what-if-scenarios")
    required = _required_sections(args.mode)
    print(
        "REPORT_OK | structure=complete | sections="
        f"{len(required)}/{len(required)}"
        + (f" | optional={','.join(optional)}" if optional else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
