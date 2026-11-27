#!/usr/bin/env python3
"""heroku-to-aws add-on checks for migration-report.html / decision-report.html.

This is the SECOND of two validators. The shared validator at
`$PLUGIN_ROOT/scripts/validate-migration-report.py --profile heroku` carries the
structure and content standard (required section IDs per mode, TOC integrity,
decision-summary before the TOC, the visual shell, accessibility, whole-dollar
currency, readability and exec vocabulary, the typography-first verdict rules,
`metric-hero`, the "What would flip this" list, the what-if columns, the exec-share
brief, the `draft for review` footer, and the `aws_monthly_balanced` /
`current_monthly` cost anchors). Nothing in this file repeats those rules.

This file enforces only what the shared validator does not:
  - full mode renders no `decision-cta` (the decision-mode terminal section);
  - no mode renders a retired heroku section id (`next-steps`, `cost-optimization`,
    `decision-basis`) — the error names the shared-id replacement;
  - decision mode renders no `.appendix-header` divider;
  - the `.share-card` CSS rule gives the CFO brief a border;
  - the `heroku_monthly_like_for_like` cost anchor: cross-checked against
    `cost_comparison.heroku_monthly_like_for_like`, required inside exec-costs when
    `cost_comparison.like_for_like_comparison` exists, and the estimate must agree
    with itself about that figure;
  - the AWS Activate callout rules driven by preferences.json
    `global.startup_program_status` (known status requires the `.callout-info`
    callout; unknown/absent forbids a confirmed-tier claim; has_credits forbids
    "apply for" wording; an invalid value fails);
  - full mode: `exec-optimization` and `appendix-optimization` (each when present)
    render a populated table row or the exact no-eligible-commitment sentence;
  - full mode: the `appendix-security` table has "What it does" and "Threat
    mitigated" columns;
  - `exec-assumptions` is rendered when `recommendation.decision_basis` exists;
  - decision mode: `.phase-status.json` `phases.generate` is not completed /
    in_progress, and an unreadable status file fails.

Both validators must print REPORT_OK and exit 0. Exit 0 on PASS, 1 on FAIL.

Usage:
  python3 validate-heroku-migration-report.py /path/to/migration-report.html \\
      --migration-dir "$MIGRATION_DIR" [--mode full|decision]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# decision (decision-report.html) ends on a decision-cta pointing at Generate; full
# (migration-report.html) renders its Next steps as an <ol class="compact"> inside
# decision-summary and ends on the appendix block. The shared validator's heroku
# profile requires decision-cta in decision mode; this file rejects it in full mode.
FULL_MODE_FORBIDDEN = "decision-cta"

# Heroku section ids retired when the report converged on the shared contract.
# Any rendered <section> with one of these ids fails in BOTH modes; the value names
# what to render instead.
RETIRED_SECTION_IDS = {
    "next-steps": (
        'the decision-summary "Next steps" <ol class="compact"> (full mode) / '
        "decision-cta (decision mode)"
    ),
    "cost-optimization": "exec-optimization plus appendix-optimization (Appendix B.1)",
    "decision-basis": 'exec-assumptions ("What This Assessment Rests On")',
}

# The one stylesheet rule the shared visual contract does not cover: the CFO brief's
# share card (generate-report.md "Visual shell"). Everything else in that block is
# gated by the shared validator.
VISUAL_CONTRACT_CHECKS = [
    (
        r"\.share-card\s*\{[^}]*border\s*:",
        "the CFO brief must render as a bordered share card",
    ),
]


def _validate_visual_shell(html: str) -> list[str]:
    style = "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", html, flags=re.IGNORECASE | re.DOTALL))
    return [message for pattern, message in VISUAL_CONTRACT_CHECKS if not re.search(pattern, style, re.IGNORECASE | re.DOTALL)]


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
        # Rendered elements carrying the `appendix-header` class (the visible
        # divider above the appendix block), counted with the same comment and
        # inert-subtree exclusions as sections so decision mode can reject it.
        self.appendix_headers = 0

    @staticmethod
    def _has_appendix_header_class(attrs: list[tuple[str, str | None]]) -> bool:
        return any(
            name == "class" and value is not None and "appendix-header" in value.split()
            for name, value in attrs
        )

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
        if self._has_appendix_header_class(attrs):
            self.appendix_headers += 1
        if tag == "section":
            # Keep nested section attributes in the containing fragment so a
            # second parser retains cost anchors and hidden ancestry.
            self._emit(self.get_starttag_text() or "")
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
        if self._has_appendix_header_class(attrs):
            self.appendix_headers += 1
        if tag == "section":
            self._emit(self.get_starttag_text() or "")
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
            self._emit("</section>")
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


def _appendix_header_count(html: str) -> int:
    """Count rendered elements with the `appendix-header` class (comments/inert excluded)."""
    return _parse_sections(html).appendix_headers


def _section_html(html: str, section_id: str) -> str | None:
    """Return the inner HTML of the first rendered <section id="section_id">,
    or None when it is absent (or exists only in a comment/inert subtree). A
    nested <section> does not truncate early — the parser closes on the
    matching depth."""
    frags = _parse_sections(html).fragments.get(section_id)
    if not frags:
        return None
    return frags[0]


# Monthly-scale totals (>= $2 after rounding) render as whole dollars; genuinely
# small totals keep cents. Same threshold as the shared validator's currency gate.
_CENTS_MEANINGFUL_BELOW = 2


def _normalize_money(text: str) -> str | None:
    """Reduce a rendered money string to its canonical display form for exact
    comparison against the JSON figure (same normalization on both sides via
    `_canonical_money`). '$1,415/mo' -> '1415'; '$112.90' -> '113'; '$0.40' ->
    '0.40'. Returns None when no dollar amount is present. Cents are NO LONGER
    truncated — a correctly rounded report figure must match, not be rejected."""
    m = re.search(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text)
    if not m:
        return None
    try:
        return _canonical_money(float(m.group(1).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _canonical_money(value: float) -> str:
    """Canonical display form for a dollar amount, matching the emitter's own
    rule (generate-report.md currency rule / the currency-formatting gate):
    monthly-scale totals (>= $2 after rounding) round to the nearest whole
    dollar; genuinely small totals keep two-decimal cents. Both the rendered
    figure and the JSON figure pass through this SAME function before comparison,
    so a correctly rounded `$113` for `112.90` matches (not truncated to `112`),
    and the small-total exception (e.g. `$0.40`) is preserved instead of being
    truncated to `0`. Decides precision on the ROUNDED magnitude so a value that
    rounds up across the $2 threshold (e.g. 1.999) canonicalizes to `"2"`,
    matching a displayed `$2`, instead of `"2.00"`."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise
    rounded_whole = int(round(v))
    if abs(rounded_whole) >= _CENTS_MEANINGFUL_BELOW:
        return str(rounded_whole)  # nearest-dollar; 112.90->113, 112.4->112, 1.999->2
    return f"{v:.2f}"  # genuinely small total: retain cents (0.40 -> "0.40")


# Elements whose subtree the browser never renders — an anchor (or its text)
# inside one must never stand in for the visible figure.
_ANCHOR_INERT_TAGS = {"script", "style", "template"}


# data-cost-key anchor -> estimation-infra.json path. The shared validator asserts
# `aws_monthly_balanced` and `current_monthly` (heroku: cost_comparison.heroku_monthly_baseline);
# this add-on asserts only the scope-matched Heroku figure that generate-report.md
# anchors as `heroku_monthly_like_for_like` — a different number from the baseline
# (baseline minus deferred add-on cost), which the shared validator does not know.
_COST_ANCHORS = {
    "heroku_monthly_like_for_like": ("cost_comparison", "heroku_monthly_like_for_like"),
}
# Load-bearing keys: when the trigger path exists in the JSON AND exec-costs is
# present, the anchor MUST be present (a missing anchor is a FAIL, not a skip —
# otherwise an un-anchored wrong figure passes). The like-for-like anchor is required
# only when the estimate carries a `like_for_like_comparison` block (the report's
# scope-matched row block exists exactly then); otherwise it is optional but still
# cross-checked when present.
_REQUIRED_COST_KEYS = {
    "heroku_monthly_like_for_like": ("cost_comparison", "like_for_like_comparison"),
}


class _CostAnchorParser(HTMLParser):
    """Collect the rendered text of every `data-cost-key="..."` element.

    Ported from validate-migration-report.py's parser (GCP) so both providers
    agree on what "rendered" means. Uses the stdlib HTML parser rather than a
    regex so that:
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
    (d) an element with a `hidden` attribute is skipped for the same reason —
        its subtree is not rendered.
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


def _validate_cost_figures(html: str, migration_dir: Path | None) -> list[str]:
    """Assert the heroku-only cost anchor matches estimation-infra.json (P1-C).

    The shared validator owns the `aws_monthly_balanced` / `current_monthly` anchors;
    this function knows only `heroku_monthly_like_for_like` (see _COST_ANCHORS).

    Fail direction:
    - No estimation-infra.json / corrupt / not a dict -> skip (fail open on absence).
    - cost_comparison.like_for_like_comparison present in JSON + exec-costs present
      -> a `heroku_monthly_like_for_like` anchor MUST exist inside exec-costs (the
      scope-matched row block is rendered exactly then); otherwise that anchor is
      optional but still cross-checked when present.
    - Anchor present anywhere + JSON value present but rendered dollars differ -> FAIL
      (any anchor is still cross-checked against the estimate, even outside exec-costs).
    - Anchored element with a real JSON value but no $ rendered -> FAIL.
    - Non-numeric / non-whole-dollar JSON value -> FAIL (named), never a crash.
    - Unknown anchor key -> skip.
    """
    if migration_dir is None:
        return []
    est_path = migration_dir / "estimation-infra.json"
    if not est_path.is_file():
        return []
    try:
        est = json.loads(est_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []  # fail open on ambiguity: a corrupt estimate does not gate the report
    if not isinstance(est, dict):
        return []
    errors: list[str] = []

    for key, text in _cost_anchor_matches(html):
        key = key.lower()
        path = _COST_ANCHORS.get(key)
        if path is None:
            continue
        expected = _dig(est, path)
        if expected is None:
            continue
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
                f'cost figure mismatch: data-cost-key="{key}" renders "${rendered}" '
                f'but estimation-infra.json {".".join(path)} = ${expected_dollars}'
            )

    # Required figures must be anchored INSIDE <section id="exec-costs"> when their
    # JSON value exists and that section is rendered. A redundant anchor elsewhere
    # (e.g. a decision-summary hero metric) is still cross-checked by the mismatch
    # loop above, but does not satisfy this requirement: exec-costs is the section
    # customers read as the authoritative cost comparison.
    exec_costs_html = _section_html(html, "exec-costs")
    if exec_costs_html is not None:
        errors.extend(_like_for_like_source_errors(est))
        exec_costs_keys = {k.lower() for k, _ in _cost_anchor_matches(exec_costs_html)}
        for key, trigger in _REQUIRED_COST_KEYS.items():
            path = _COST_ANCHORS[key]
            if _dig(est, trigger) is None:
                continue
            if key not in exec_costs_keys:
                errors.append(
                    f'missing data-cost-key="{key}" anchor inside '
                    f'<section id="exec-costs">; cannot confirm the rendered figure '
                    f"matches estimation-infra.json {'.'.join(path)} (wrap that "
                    f'figure in <span data-cost-key="{key}">...</span> inside '
                    f"exec-costs)"
                )

    return errors


def _like_for_like_source_errors(est: dict) -> list[str]:
    """The like-for-like anchor is required when `cost_comparison.like_for_like_comparison`
    exists, but the figure it is compared with is the top-level
    `cost_comparison.heroku_monthly_like_for_like`. Two estimate shapes would let a wrong
    anchored figure through, so both are failures:

    - the block exists and the top-level value is missing: there is nothing to compare the
      anchor with, so any amount would pass;
    - the block carries its own `heroku_monthly_like_for_like` and it differs from the
      top-level one: the estimate disagrees with itself, so the anchor cannot be right
      against both."""
    cmp_ = est.get("cost_comparison")
    block = cmp_.get("like_for_like_comparison") if isinstance(cmp_, dict) else None
    if block is None:
        return []
    top = cmp_.get("heroku_monthly_like_for_like")
    if top is None:
        return [
            "estimation-infra.json cost_comparison.like_for_like_comparison exists but "
            "cost_comparison.heroku_monthly_like_for_like is missing; the "
            'data-cost-key="heroku_monthly_like_for_like" anchor has no figure to be checked against '
            "(write the like-for-like Heroku figure at cost_comparison.heroku_monthly_like_for_like)"
        ]
    nested = block.get("heroku_monthly_like_for_like") if isinstance(block, dict) else None
    if nested is None:
        return []
    try:
        if _canonical_money(float(top)) != _canonical_money(float(nested)):
            return [
                "estimation-infra.json disagrees with itself: cost_comparison.heroku_monthly_like_for_like = "
                f"{top!r} but cost_comparison.like_for_like_comparison.heroku_monthly_like_for_like = {nested!r}"
            ]
    except (TypeError, ValueError):
        pass  # a non-numeric figure is reported by the anchor comparison itself
    return []





class _DecodedTextParser(HTMLParser):
    """Extract rendered text as the browser would present it — entities
    decoded, comments and inert content (script/style/template) excluded,
    hidden subtrees dropped — while preserving word adjacency across inline
    markup. Used by the optimization-section content check and the Activate
    callout rules so both agree on what "rendered" means."""

    _INLINE_TAGS = {
        "a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em",
        "i", "kbd", "mark", "q", "s", "samp", "small", "span", "strong",
        "sub", "sup", "time", "u", "var", "wbr",
    }
    _INERT_TAGS = {"script", "style", "template"}
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._inert_depth = 0
        self._stack: list[dict[str, object]] = []

    def _append(self, text: str) -> None:
        if text:
            self._parts.append(text)

    def _hidden(self) -> bool:
        return bool(self._stack and self._stack[-1]["hidden"])

    @staticmethod
    def _is_hidden(attrs: list[tuple[str, str | None]]) -> bool:
        return "hidden" in dict(attrs)

    def _pop_to(self, tag: str) -> bool:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] == tag:
                popped = self._stack[index:]
                del self._stack[index:]
                return any(bool(frame["hidden"]) for frame in popped)
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._INERT_TAGS:
            self._inert_depth += 1
            return
        if self._inert_depth > 0:
            return
        hidden = self._hidden() or self._is_hidden(attrs)
        if tag not in self._VOID_TAGS:
            self._stack.append({"tag": tag, "hidden": hidden})
        if hidden:
            if tag not in self._INLINE_TAGS:
                self._append(" ")
            return
        if tag not in self._INLINE_TAGS:
            self._append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._INERT_TAGS or self._inert_depth > 0 or self._hidden():
            return
        if self._is_hidden(attrs):
            return
        if tag not in self._INLINE_TAGS:
            self._append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._INERT_TAGS:
            if self._inert_depth > 0:
                self._inert_depth -= 1
            return
        if self._inert_depth > 0:
            return
        hidden = self._pop_to(tag)
        if hidden or self._hidden():
            if tag not in self._INLINE_TAGS:
                self._append(" ")
            return
        if tag not in self._INLINE_TAGS:
            self._append(" ")

    def handle_data(self, data: str) -> None:
        if self._inert_depth == 0 and not self._hidden():
            self._append(data)

    def text(self) -> str:
        return "".join(self._parts)



def _visible_text(fragment: str) -> str:
    """Rendered text of a fragment (entities decoded, comments and script/style/
    template excluded, hidden subtrees dropped), whitespace collapsed."""
    parser = _DecodedTextParser()
    parser.feed(fragment)
    parser.close()
    return re.sub(r"\s+", " ", parser.text().replace("\u00a0", " ")).strip()


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


def _validate_optimization_content(body: str, section_id: str) -> list[str]:
    """The optimization section must render EITHER a populated opportunities
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
    # Reuses the same _DecodedTextParser the Activate callout rules use, so both
    # agree on what "rendered" means.
    parser = _DecodedTextParser()
    parser.feed(body)
    parser.close()
    # Normalize decoded whitespace (incl. NBSP U+00A0 from `&nbsp;`) to single
    # spaces so an entity-separated sentence matches the literal one.
    text = re.sub(r"\s+", " ", parser.text().replace("\u00a0", " ")).strip().lower()
    if NO_ELIGIBLE_COMMITMENT_SENTENCE in text:
        return []
    return [
        f'<section id="{section_id}"> has no substantive content — render a '
        "populated opportunity row (not just column headers, an empty <tbody>, or "
        "other prose like the credits disclaimer) or the exact "
        f'"{NO_ELIGIBLE_COMMITMENT_SENTENCE}" sentence, never a blank, '
        "heading-only, or table-header-only section"
    ]



def _load_estimate(migration_dir: Path | None) -> dict | None:
    if migration_dir is None:
        return None
    est_path = migration_dir / "estimation-infra.json"
    if not est_path.is_file():
        return None
    try:
        est = json.loads(est_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return est if isinstance(est, dict) else None


ACTIVATE_APPLY_URL = "https://aws.amazon.com/startups/credits/"
ACTIVATE_STATUSES = ("has_credits", "eligible_founders", "eligible_portfolio", "unknown")
_ACTIVATE_MENTION = re.compile(r"AWS\s+Activate|Activate\s+(?:Founders|Portfolio|credits)", re.I)
_TIER_CLAIM = re.compile(
    r"eligible\s+for\b.{0,60}?\b(?:Founders|Portfolio)|\$\s?5,?000\b|\$5K\b|\$\s?200,?000\b|\$200K\b",
    re.I | re.DOTALL,
)
_APPLY_LANGUAGE = re.compile(r"\bapply\s+(?:for|at|before|now)\b|\bapplying\s+for\b", re.I)


def _startup_program_status(migration_dir: Path | None) -> str | None:
    """Read preferences.json global.startup_program_status (Clarify Q17); None when unset."""
    if migration_dir is None:
        return None
    path = migration_dir / "preferences.json"
    if not path.is_file():
        return None
    try:
        prefs = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = ((prefs or {}).get("global") or {}).get("startup_program_status")
    return value if isinstance(value, str) else None


def _activate_callout_html(summary: str) -> str | None:
    """Return the `.callout-info` fragment inside decision-summary that names Activate.

    report-decision-core.md § Startup credits callout renders the credits
    call-to-action as one `<div class="callout callout-info">` with inline content
    only, so the first closing </div> ends it. The tier and apply-language rules
    apply to this fragment alone — the rest of decision-summary legitimately
    carries dollar figures ($5,000/mo estimates) and the word "apply".
    """
    for match in re.finditer(
        r'<div\b[^>]*class=["\'][^"\']*\bcallout-info\b[^"\']*["\'][^>]*>(.*?)</div>',
        summary,
        re.I | re.DOTALL,
    ):
        if _ACTIVATE_MENTION.search(_visible_text(match.group(0))):
            return match.group(0)
    return None


def _validate_activate_callout(html: str, migration_dir: Path | None) -> list[str]:
    """report-decision-core.md § Startup credits callout (both modes).

    (The apply-link rule — a summary that names Activate must link the official
    apply page — is enforced by the shared validator and not repeated here.)
    - When preferences.json says the founder answered Q17 (status other than
      "unknown"), decision-summary must render the `.callout-info` credits callout.
    - Inside that callout only: "unknown"/absent status forbids a confirmed-tier
      claim or a tier dollar amount; "has_credits" forbids "apply for" language.
      Cost lines and other prose in decision-summary are not scanned.
    """
    summary = _section_html(html, "decision-summary")
    if summary is None:
        return []
    errors: list[str] = []
    status = _startup_program_status(migration_dir)
    if status is not None and status not in ACTIVATE_STATUSES:
        errors.append(
            f"preferences.json global.startup_program_status={status!r} is not one of "
            f"{', '.join(ACTIVATE_STATUSES)}"
        )
        return errors
    callout = _activate_callout_html(summary)
    if status in ("has_credits", "eligible_founders", "eligible_portfolio") and callout is None:
        errors.append(
            f"preferences.json global.startup_program_status={status!r} but decision-summary "
            'has no AWS Activate credits <div class="callout callout-info"> '
            "(report-decision-core.md § Startup credits callout)"
        )
    if callout is None:
        return errors
    callout_text = _visible_text(callout)
    if status in (None, "unknown") and _TIER_CLAIM.search(callout_text):
        errors.append(
            "Activate callout states a confirmed tier or tier dollar amount but "
            "global.startup_program_status is unknown/absent — neutral wording only"
        )
    if status == "has_credits" and _APPLY_LANGUAGE.search(callout_text):
        errors.append(
            'global.startup_program_status is "has_credits" but the Activate callout still '
            'uses "apply for" language'
        )
    return errors



def _validate_security_appendix(html: str, mode: str) -> list[str]:
    """Full reports say what each baseline control does. Decision mode has no appendix."""
    if mode != "full":
        return []
    section = _section_html(html, "appendix-security")
    if not section:
        return []
    header = re.search(r"<thead\b.*?</thead>", section, re.DOTALL | re.IGNORECASE)
    if not header:
        return [
            "appendix-security must contain a table with What it does and "
            "Threat mitigated columns"
        ]
    hdr_text = header.group(0).lower()
    errors: list[str] = []
    if "what it does" not in hdr_text:
        errors.append('appendix-security table must include a "What it does" column')
    if "threat" not in hdr_text:
        errors.append('appendix-security table must include a "Threat mitigated" column')
    return errors




def validate(html: str, migration_dir: Path | None, mode: str = "full") -> list[str]:
    errors: list[str] = []
    counts = _section_counts(html)

    # migration-report.html must not carry the pre-execution decision-cta once the
    # decision-summary Next steps list and the execution pack exist.
    if mode == "full" and counts.get(FULL_MODE_FORBIDDEN, 0) >= 1:
        errors.append(
            f'--mode full report must not contain <section id="{FULL_MODE_FORBIDDEN}"> '
            "(that is the decision-mode terminal section)"
        )

    # Retired heroku ids fail in both modes, naming the shared-id replacement.
    for retired_id, replacement in RETIRED_SECTION_IDS.items():
        if counts.get(retired_id, 0) >= 1:
            errors.append(
                f'<section id="{retired_id}"> is a retired heroku section id — '
                f"render {replacement} instead"
            )

    if mode == "decision":
        # The visible divider above the appendix block is part of the decision-mode
        # contract (report-decision-core.md: do not render `.appendix-header`). The
        # shared validator rejects rendered `appendix-*` sections; a lone divider
        # with no sections under it still announces an appendix that does not
        # exist. Same comment/inert exclusions as the sections.
        if _appendix_header_count(html) > 0:
            errors.append(
                'decision mode forbids a rendered <div class="appendix-header"> — the '
                "decision report has no appendix divider; the full migration report (Generate) carries it"
            )

    errors.extend(_validate_visual_shell(html))
    errors.extend(_validate_activate_callout(html, migration_dir))
    errors.extend(_validate_security_appendix(html, mode))
    errors.extend(_validate_cost_figures(html, migration_dir))


    # exec-optimization and appendix-optimization (Appendix B.1) must carry
    # substantive content (generate-report.md Step 3 item 6: a table of real rows, or
    # the explicit no-eligible-commitment sentence — never empty, and never satisfied
    # by a heading or table-header text alone). A heading like "Cost Optimization"
    # or a table with only column headers and an empty <tbody> must not pass as
    # content. Full mode only — in decision mode exec-optimization follows the shared
    # trigger and there is no appendix.
    if mode == "full":
        for section_id in ("appendix-optimization", "exec-optimization"):
            if counts.get(section_id, 0) >= 1:
                body = _section_html(html, section_id) or ""
                errors.extend(_validate_optimization_content(body, section_id))

    if migration_dir is not None:

        # generate-report.md / report-decision-core.md § exec-assumptions: when Estimate
        # declared decision_basis (evidence/assumptions behind the verdict), the report
        # MUST render it — in both modes, since decision mode reuses these exact content
        # rules. Read the same estimation-infra.json the report was built from, so a
        # report that silently drops exec-assumptions cannot still say REPORT_OK.
        est_path = migration_dir / "estimation-infra.json"
        if est_path.is_file():
            try:
                est = json.loads(est_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                est = None
            decision_basis = ((est or {}).get("recommendation") or {}).get("decision_basis")
            if decision_basis and counts.get("exec-assumptions", 0) < 1:
                errors.append(
                    "estimation-infra.json declares recommendation.decision_basis "
                    'but the report has no <section id="exec-assumptions"> '
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

    print(f"REPORT_OK | mode={args.mode} | heroku-addon=complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
