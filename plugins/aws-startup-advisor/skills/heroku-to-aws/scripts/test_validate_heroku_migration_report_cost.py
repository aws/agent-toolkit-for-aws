"""Cost-figure cross-check regressions for the skill-local Heroku validator."""

from __future__ import annotations

import json
# Tests invoke only the committed validator using list arguments without a shell.
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "validate-heroku-migration-report.py"

GOOD = """<!DOCTYPE html>
<html lang="en"><body><div class="report">
<section id="decision-summary"><p class="verdict-headline">Go</p></section>
<section id="exec-costs"><p>Balanced <span data-cost-key="aws_monthly_balanced">$112/mo</span></p></section>
<section id="cost-optimization"><p>No 1-year/3-year commitment product applies to this architecture.</p></section>
<section id="next-steps"><ol><li>See MIGRATION_GUIDE.md</li></ol></section>
<footer>draft for review</footer>
</div></body></html>
"""


def run(html: str, migration_dir: Path | None, mode: str | None = None) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "migration-report.html"
        report.write_text(html, encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT), str(report)]
        if migration_dir is not None:
            cmd += ["--migration-dir", str(migration_dir)]
        if mode is not None:
            cmd += ["--mode", mode]
        result = subprocess.run(cmd, capture_output=True, text=True)  # nosec B603
        return result.returncode, result.stdout + result.stderr


def _est_dir(tmp: str, balanced: int) -> Path:
    d = Path(tmp)
    (d / "estimation-infra.json").write_text(
        json.dumps({"projected_costs": {"aws_monthly_balanced": balanced}}),
        encoding="utf-8",
    )
    return d


def test_cost_figure_match_passes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(GOOD, migration_dir=_est_dir(tmp, 112))
    assert code == 0, out
    assert "cost figure mismatch" not in out


def test_decision_report_checks_cost_figures() -> None:
    html = GOOD.replace('id="next-steps"', 'id="decision-cta"')
    with tempfile.TemporaryDirectory() as tmp:
        migration_dir = _est_dir(tmp, 112)
        code, out = run(html, migration_dir, mode="decision")
        assert code == 0, out
        code, out = run(html.replace("$112/mo", "$999/mo"), migration_dir, mode="decision")
    assert code == 1, out
    assert "cost figure mismatch" in out


def test_cost_figure_mismatch_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(GOOD, migration_dir=_est_dir(tmp, 999))
    assert code == 1, out
    assert "cost figure mismatch" in out
    assert "aws_monthly_balanced" in out


def test_cost_figure_skipped_without_estimation() -> None:
    # No --migration-dir -> no estimation-infra.json -> the cost check is skipped entirely,
    # so the otherwise-valid report passes.
    code, out = run(GOOD, migration_dir=None)
    assert code == 0, out
    assert "cost figure mismatch" not in out
    assert "missing data-cost-key" not in out


def test_missing_required_balanced_anchor_fails() -> None:
    # The core P1-C guarantee: an un-anchored balanced figure must FAIL, not pass —
    # otherwise a wrong un-anchored number reaches the reader unchecked.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        "$999/mo",
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert 'missing data-cost-key="aws_monthly_balanced"' in out


def test_nested_markup_reads() -> None:
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<span data-cost-key="aws_monthly_balanced"><strong>$112/mo</strong></span>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 0, out
    assert "cost figure mismatch" not in out


def test_nested_section_anchor_is_preserved() -> None:
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<section data-cost-key="aws_monthly_balanced">$112/mo</section>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        migration_dir = _est_dir(tmp, 112)
        for mode in ("full", "decision"):
            report = html if mode == "full" else html.replace('id="next-steps"', 'id="decision-cta"')
            code, out = run(report, migration_dir, mode=mode)
            assert code == 0, out


def test_hidden_nested_section_does_not_supply_required_anchor() -> None:
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<section hidden><span data-cost-key="aws_monthly_balanced">$112/mo</span></section>$999/mo',
    )
    with tempfile.TemporaryDirectory() as tmp:
        migration_dir = _est_dir(tmp, 112)
        for mode in ("full", "decision"):
            report = html if mode == "full" else html.replace('id="next-steps"', 'id="decision-cta"')
            code, out = run(report, migration_dir, mode=mode)
            assert code == 1, out
            assert 'missing data-cost-key="aws_monthly_balanced"' in out


def test_non_numeric_json_value_fails_not_crash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "estimation-infra.json").write_text(
            json.dumps({"projected_costs": {"aws_monthly_balanced": "$112"}}),
            encoding="utf-8",
        )
        code, out = run(GOOD, migration_dir=d)
    assert code == 1, out
    assert "not a numeric dollar amount" in out


def test_cost_anchor_inside_html_comment_does_not_satisfy_requirement() -> None:
    # A commented-out anchor is not rendered content — it must not satisfy the
    # required-anchor check, even if the (invisible) figure would have matched.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<!-- <span data-cost-key="aws_monthly_balanced">$112/mo</span> -->$999/mo',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert 'missing data-cost-key="aws_monthly_balanced"' in out


def test_cost_anchor_outside_exec_costs_does_not_satisfy_requirement() -> None:
    # A correct anchor placed in decision-summary (not exec-costs) must not let an
    # unanchored, wrong figure inside exec-costs itself pass silently.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        "$999/mo",
    ).replace(
        '<p class="verdict-headline">Go</p>',
        '<p class="verdict-headline">Go</p>'
        '<p><span data-cost-key="aws_monthly_balanced">$112/mo</span></p>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert 'missing data-cost-key="aws_monthly_balanced" anchor inside' in out
    assert "exec-costs" in out


def test_cost_anchor_inside_template_does_not_satisfy_requirement() -> None:
    # <template> content is inert (never rendered) even though the parser still
    # walks its tags — an anchor placed there must not stand in for the visible
    # (wrong) figure sitting right next to it.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<template><span data-cost-key="aws_monthly_balanced">$112/mo</span></template>$999/mo',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert 'missing data-cost-key="aws_monthly_balanced"' in out


def test_split_nested_markup_reads_full_text() -> None:
    # A figure split across nested markup within the SAME anchored element
    # (<span data-cost-key="x"><span>$</span>112/mo</span>) must be read as one
    # value through the anchor's own matching close tag, not truncated at the
    # first inner </span>.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<span data-cost-key="aws_monthly_balanced"><span>$</span>112/mo</span>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 0, out
    assert "cost figure mismatch" not in out
    assert "renders no dollar amount" not in out


def test_trailing_text_outside_inner_tag_is_included() -> None:
    # Text sitting after a nested child tag, but still inside the anchor's own
    # close tag, must be included — not dropped at the child's </strong>. Here
    # the anchor's full rendered text is "$1120", which must NOT be truncated
    # to "$112" (that would silently accept a wrong ten-times-off figure).
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<span data-cost-key="aws_monthly_balanced"><strong>$112</strong>0/mo</span>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert "cost figure mismatch" in out
    assert '"$1120"' in out


# exec-costs deliberately placed LAST among the <section> elements (only <footer>
# follows) so a non-greedy `.*?</section>` regex has no LATER </section> to fall
# through to — this is what makes the closing-tag-spelling bug observable as a
# clean `_section_html(...) is None` skip, rather than the regex silently
# matching through to some other section's close tag and returning overrun
# (but still exec-costs-containing) content that coincidentally still fails.
GOOD_EXEC_COSTS_LAST = """<!DOCTYPE html>
<html lang="en"><body><div class="report">
<section id="decision-summary"><p class="verdict-headline">Go</p></section>
<section id="cost-optimization"><p>No 1-year/3-year commitment product applies to this architecture.</p></section>
<section id="next-steps"><ol><li>See MIGRATION_GUIDE.md</li></ol></section>
<section id="exec-costs"><p>Balanced <span data-cost-key="aws_monthly_balanced">$112/mo</span></p></section>
<footer>draft for review</footer>
</div></body></html>
"""


def test_whitespace_before_exec_costs_closing_angle_bracket_still_gates_required_anchor() -> None:
    # Regression: _section_html previously matched only the literal string
    # `</section>`. `</section >` (whitespace before `>`) is equally valid
    # HTML, but the old regex returned None for it, and the required-anchor
    # check was gated behind `if exec_costs_html is not None:` — so a
    # recognized exec-costs section silently skipped the required-anchor
    # requirement entirely. Remove the Balanced anchor, keep an unanchored
    # wrong figure, and serialize exec-costs' closing tag with a trailing
    # space: this must still FAIL.
    html = GOOD_EXEC_COSTS_LAST.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        "$999/mo",
    ).replace(
        "</section>\n<footer>",
        "</section >\n<footer>",
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert 'missing data-cost-key="aws_monthly_balanced" anchor inside' in out


def test_newline_before_exec_costs_closing_angle_bracket_still_gates_required_anchor() -> None:
    # Same bypass, different whitespace: a newline before the closing `>` is
    # also valid HTML and must not defeat the required-anchor check either.
    html = GOOD_EXEC_COSTS_LAST.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        "$999/mo",
    ).replace(
        "</section>\n<footer>",
        "</section\n>\n<footer>",
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert 'missing data-cost-key="aws_monthly_balanced" anchor inside' in out


def test_escaped_anchor_example_inside_section_does_not_satisfy_requirement() -> None:
    # Regression: _SectionScopeParser decodes character references before
    # appending text into the returned section HTML. An escaped code example
    # like `<code>&lt;span data-cost-key="x"&gt;$112&lt;/span&gt;</code>`
    # decodes to the literal text `<span data-cost-key="x">$112</span>` —
    # reparsing that string then finds a "real" anchor that never actually
    # existed in the source. Remove the real anchor, leave a visible wrong
    # figure, and add an escaped example with the correct anchor+value: this
    # must still FAIL.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        "$999/mo "
        '<code>&lt;span data-cost-key="aws_monthly_balanced"&gt;$112/mo&lt;/span&gt;</code>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert 'missing data-cost-key="aws_monthly_balanced"' in out


# --- Rendered-reality regressions (parity with the GCP validator): inert/hidden
# anchors do not count, nested anchors are collected independently, and the display
# precision rounds rather than truncates. ---


def test_nested_inner_anchor_is_collected_not_dropped() -> None:
    # An inner data-cost-key nested in an outer one must be read as its own anchor,
    # not swallowed by the outer element. Inner $999 != estimate 112 -> FAIL.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<span data-cost-key="aws_monthly_balanced">$112/mo '
        '<strong data-cost-key="aws_monthly_balanced">$999</strong></span>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert "999" in out and "mismatch" in out.lower()


def test_hidden_anchor_does_not_satisfy_requirement() -> None:
    # A hidden anchor is not rendered; a visible $999 stands instead. estimate 112.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<span hidden data-cost-key="aws_monthly_balanced">$112/mo</span>$999',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert 'missing data-cost-key="aws_monthly_balanced"' in out


def test_hidden_false_is_still_hidden() -> None:
    # In HTML `hidden="false"` is still the Hidden state (invalid-value default),
    # so the anchor is not rendered and must not satisfy the requirement.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<span hidden="false" data-cost-key="aws_monthly_balanced">$112/mo</span>$999',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert 'missing data-cost-key="aws_monthly_balanced"' in out


def test_script_anchor_does_not_satisfy_requirement() -> None:
    # An anchor inside an inert <script> subtree is never rendered.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<script type="application/json">'
        '<span data-cost-key="aws_monthly_balanced">$112</span></script>$999',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 112))
    assert code == 1, out
    assert 'missing data-cost-key="aws_monthly_balanced"' in out


def test_rounded_cents_figure_matches_not_truncated() -> None:
    # estimate 112.90 renders as $113 (nearest dollar); the validator must accept
    # it, not reject it because int(112.90) == 112.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<span data-cost-key="aws_monthly_balanced">$113/mo</span>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "estimation-infra.json").write_text(
            json.dumps({"projected_costs": {"aws_monthly_balanced": 112.90}}),
            encoding="utf-8",
        )
        code, out = run(html, migration_dir=d)
    assert code == 0, out
    assert "REPORT_OK" in out


def test_two_dollar_boundary_canonicalizes_consistently() -> None:
    # estimate 1.999 canonicalizes to "2" and a displayed $2 canonicalizes to "2",
    # so they match — the $2 rounding-threshold boundary must not spuriously fail.
    html = GOOD.replace(
        '<span data-cost-key="aws_monthly_balanced">$112/mo</span>',
        '<span data-cost-key="aws_monthly_balanced">$2/mo</span>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "estimation-infra.json").write_text(
            json.dumps({"projected_costs": {"aws_monthly_balanced": 1.999}}),
            encoding="utf-8",
        )
        code, out = run(html, migration_dir=d)
    assert code == 0, out
    assert "REPORT_OK" in out
