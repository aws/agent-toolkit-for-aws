#!/usr/bin/env python3
"""Validate heroku-to-aws migration report HTML (thin stakeholder report).

Two modes, sharing the decision-core sections (see
skills/heroku-to-aws/references/shared/report-decision-core.md):

  full     (default) migration-report.html — decision-summary, exec-costs,
           next-steps required; decision-basis / what-if-scenarios conditional.
  decision decision-report.html — decision-summary, exec-costs required;
           decision-cta required instead of next-steps; decision-basis /
           what-if-scenarios conditional (same triggers as full mode).

Exit 0 on PASS, 1 on FAIL.

Usage:
  python3 validate-heroku-migration-report.py /path/to/migration-report.html \\
      --migration-dir "$MIGRATION_DIR"
  python3 validate-heroku-migration-report.py /path/to/decision-report.html \\
      --mode decision
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

# Required in both modes.
COMMON_REQUIRED_SECTION_IDS = [
    "decision-summary",
    "exec-costs",
]

# The one structural difference between modes: decision mode ends on a CTA
# pointing at Generate instead of the full report's next-steps list (which
# assumes MIGRATION_GUIDE.md / terraform/ already exist — they don't yet in
# decision mode).
MODE_REQUIRED_SECTION_ID = {
    "full": "next-steps",
    "decision": "decision-cta",
}


class _SectionOpenTagCollector(HTMLParser):
    """Collect the `id` of every real (rendered) <section> open tag.

    Uses the stdlib parser rather than a regex so that a <section id="..."> that
    only exists inside an HTML comment (e.g. an unexpanded template placeholder
    like `<!-- <section id="decision-basis"> when ... -->`) is never counted as
    present — HTMLParser routes comment text to handle_comment, never
    re-tokenizing it as a real tag, whereas a regex scanning raw source text
    cannot distinguish a real tag from one that merely looks like a tag inside
    a comment."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.section_ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "section":
            sid = dict(attrs).get("id")
            if sid:
                self.section_ids.append(sid)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def _section_counts(html: str) -> dict[str, int]:
    parser = _SectionOpenTagCollector()
    parser.feed(html)
    parser.close()
    counts: dict[str, int] = {}
    for sid in parser.section_ids:
        counts[sid] = counts.get(sid, 0) + 1
    return counts


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


def validate(html: str, migration_dir: Path | None, mode: str = "full") -> list[str]:
    errors: list[str] = []
    counts = _section_counts(html)

    required = [*COMMON_REQUIRED_SECTION_IDS, MODE_REQUIRED_SECTION_ID[mode]]
    for sid in required:
        n = counts.get(sid, 0)
        if n == 0:
            errors.append(f'missing required <section id="{sid}">')
        elif n > 1:
            errors.append(f'duplicate <section id="{sid}"> ({n} occurrences)')

    # The other mode's terminal section must NOT appear — decision-report.html
    # must not carry a next-steps pointer into an execution pack that does not
    # exist yet, and migration-report.html should not carry the pre-execution
    # decision-cta once the real thing (next-steps) exists.
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

        # generate-report.md / report-decision-core.md § decision-basis: when
        # Estimate declared decision_basis (evidence/assumptions behind the
        # verdict), the report MUST render it — in both modes, since decision
        # mode reuses these exact content rules rather than restating them.
        # Read the same estimation-infra.json the report itself was built
        # from, so a report that silently drops decision_basis (e.g. a
        # refactor that forgets the section) cannot still say REPORT_OK.
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
        # Decision mode's real invariant: THIS decide-complete cycle has not
        # itself gone through Generate yet (phases.generate is "pending" or
        # absent). It is NOT "no terraform/ or generation-*.json file exists
        # on disk" — a prior Generate/workshop-reprice cycle's execution pack
        # can legitimately still be sitting there (workshop re-entry
        # preserves it deliberately: it may hold customer-edited baseline.tf/
        # variables.tf or hand-authored terraform.tfvars/state that cannot be
        # safely deleted). Treating raw file presence as the signal made a
        # perfectly valid decision, after a workshop reprice on a
        # previously-executed run, permanently unable to pass — the pre-
        # execution claim this check exists to make ("no code has been
        # generated for the CURRENT decision") was never really about the
        # filesystem; it's about .phase-status.json's own bookkeeping.
        #
        # phases.generate == "completed"/"in_progress" is exactly the signal
        # that consent to execute for the CURRENT cycle was already given —
        # that state is precisely what "decision mode" (pre-execution) must
        # not be, and .phase-status.json is the interpreter's own source of
        # truth for it (see phase-status.schema.json's run_mode/phases
        # description).
        #
        # Fail open ONLY on a genuinely MISSING status file — that means no
        # run has ever tracked state here, which is not evidence of anything
        # (e.g. the isolated unit-test path validating HTML without a real
        # $MIGRATION_DIR). Do NOT fail open on a file that EXISTS but is
        # unreadable or fails to parse as JSON: that is state corruption, and
        # INTERPRETER.md § State-file validation is explicit that invalid
        # JSON is a STOP condition ("do not proceed or guess"), not something
        # to treat as equivalent to "no state exists." Guessing "pending"
        # past a corrupt file would let a broken run silently pass the one
        # check this mode exists to enforce.
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
                    "decision mode: .phase-status.json exists but could not "
                    f"be read/parsed ({exc}) — state corrupted (invalid "
                    "JSON). Delete the file and restart the current phase "
                    "(INTERPRETER.md § State-file validation); an unreadable "
                    "state file is not evidence of a pre-execution decision"
                )
            else:
                generate_status = (phase or {}).get("phases", {}).get("generate")
        if generate_status in ("completed", "in_progress"):
            errors.append(
                "decision mode: .phase-status.json phases.generate is "
                f"{generate_status!r} — this decide-complete cycle already "
                "went through Generate; decision mode is pre-execution only "
                "for the CURRENT cycle (a prior cycle's execution pack may "
                "legitimately remain on disk after a workshop reprice)"
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
        print(f"REPORT_FAIL | file={args.report_path} | mode={args.mode} | errors={len(errors)}", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    counts = _section_counts(html)
    optional = []
    if counts.get("what-if-scenarios", 0) >= 1:
        optional.append("what-if-scenarios")
    if counts.get("decision-basis", 0) >= 1:
        optional.append("decision-basis")
    required_count = len(COMMON_REQUIRED_SECTION_IDS) + 1
    print(
        "REPORT_OK | structure=complete | mode="
        f"{args.mode} | sections={required_count}/{required_count}"
        + (f" | optional={','.join(optional)}" if optional else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
