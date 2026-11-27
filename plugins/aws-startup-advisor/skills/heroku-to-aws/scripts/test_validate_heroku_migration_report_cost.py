"""Cost-figure cross-check regressions for the heroku add-on validator.

The add-on asserts one anchor only: `heroku_monthly_like_for_like` (the shared
validator owns `aws_monthly_balanced` / `current_monthly`). The parser-robustness
cases below (nested markup, comments, templates, hidden subtrees, closing-tag
spellings, rounding) therefore all drive that key, with an estimate whose
`cost_comparison.like_for_like_comparison` block makes the anchor required.
"""

from __future__ import annotations

import json

# Tests invoke only the committed validator using list arguments without a shell.
import re
import subprocess  # nosec B404
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "validate-heroku-migration-report.py"

_APPENDIX_SECTION = re.compile(r'<section\s+id="appendix-[^"]*"[^>]*>.*?</section>\s*', re.DOTALL)

LFL_ANCHOR = '<span data-cost-key="heroku_monthly_like_for_like">$140/mo</span>'


def _decision_html(html: str) -> str:
    """Decision mode has no appendices; drop them (the add-on requires no terminal
    section of its own, so nothing is renamed)."""
    return _APPENDIX_SECTION.sub("", html)


GOOD = f"""<!DOCTYPE html>
<html lang="en"><style>
  .share-card {{ background: #f0f6fc; border: 1px solid #d0d7de; border-left: 4px solid #0969da; padding: 0.85rem 1rem; }}
</style><body><div class="report">
<section id="decision-summary"><p class="verdict-headline">Go</p></section>
<section id="exec-share"><p>The one-paragraph version, ready to forward:</p><div class="share-card"><p>Go, with conditions, at medium confidence. The estimated AWS balanced rate is higher than the Heroku rate card and the shape is phased. Confirm the open conditions before treating the monthly figure as final.</p></div></section>
<section id="exec-timeline"><h2>Timeline</h2><p>Phased migration: provision, migrate data, cut over. Not a staffed schedule.</p></section>
<section id="exec-costs"><p>Balanced $112/mo</p><p>Scope-matched: Heroku {LFL_ANCHOR} vs AWS Balanced $112/mo</p></section>
<section id="exec-optimization"><p>No 1-year/3-year commitment product applies to this architecture.</p></section>
<section id="appendix-optimization"><p>No 1-year/3-year commitment product applies to this architecture.</p></section>
<section id="appendix-services"><p>One designed service.</p></section>
<section id="appendix-costs"><p>Balanced estimated monthly cost.</p></section>
<section id="appendix-config"><p>Region and availability choices.</p></section>
<section id="appendix-security"><table><thead><tr><th scope="col">Control</th><th scope="col">Setting</th><th scope="col">What it does</th><th scope="col">Threat mitigated</th></tr></thead><tbody><tr><td>GuardDuty</td><td>Enabled</td><td>Detects unusual API activity</td><td>Credential theft</td></tr></tbody></table></section>
<section id="appendix-assumptions"><p>Measured, assumed, and unknown inputs.</p></section>
<footer>draft for review</footer>
</div></body></html>
"""

# The report without any like-for-like anchor (no scope-matched row block).
GOOD_NO_LFL = GOOD.replace(f"<p>Scope-matched: Heroku {LFL_ANCHOR} vs AWS Balanced $112/mo</p>", "")


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


def _est_dir(tmp: str, like_for_like: float | int | str | None, *, with_block: bool = True) -> Path:
    """Estimate whose like_for_like_comparison block (when `with_block`) makes the
    `heroku_monthly_like_for_like` anchor required inside exec-costs."""
    est: dict = {"projected_costs": {"aws_monthly_balanced": 112}}
    if like_for_like is not None or with_block:
        cmp_: dict = {"heroku_monthly_baseline": 740}
        if like_for_like is not None:
            cmp_["heroku_monthly_like_for_like"] = like_for_like
        if with_block:
            cmp_["like_for_like_comparison"] = {"aws_monthly_balanced": 112}
            if isinstance(like_for_like, (int, float)):
                cmp_["like_for_like_comparison"]["heroku_monthly_like_for_like"] = like_for_like
                cmp_["like_for_like_comparison"]["monthly_difference"] = 112 - like_for_like
        est["cost_comparison"] = cmp_
    d = Path(tmp)
    (d / "estimation-infra.json").write_text(json.dumps(est), encoding="utf-8")
    return d


def _mode_variants(html: str) -> list[tuple[str, str]]:
    return [("full", html), ("decision", _decision_html(html))]


def test_like_for_like_anchor_match_passes_both_modes() -> None:
    for mode, html in _mode_variants(GOOD):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(html, _est_dir(tmp, 140), mode=mode)
        assert code == 0, (mode, out)
        assert "heroku_monthly_like_for_like" not in out


def test_like_for_like_anchor_mismatch_fails_both_modes() -> None:
    # The reviewer's probe: JSON says $140, the anchored report figure says $740 (the
    # FULL baseline) — the validator must reject it instead of skipping an unknown key.
    for mode, html in _mode_variants(GOOD.replace("$140/mo", "$740/mo")):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(html, _est_dir(tmp, 140), mode=mode)
        assert code == 1, (mode, out)
        assert 'cost figure mismatch: data-cost-key="heroku_monthly_like_for_like"' in out
        assert 'renders "$740"' in out and "= $140" in out


def test_missing_like_for_like_anchor_fails_when_comparison_exists_both_modes() -> None:
    # like_for_like_comparison exists in the estimate -> the scope-matched row block is
    # mandatory in exec-costs, so an un-anchored (or missing) Heroku figure FAILs.
    for mode, html in _mode_variants(GOOD_NO_LFL):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(html, _est_dir(tmp, 140), mode=mode)
        assert code == 1, (mode, out)
        assert 'missing data-cost-key="heroku_monthly_like_for_like" anchor inside' in out
        assert "cost_comparison.heroku_monthly_like_for_like" in out


def test_like_for_like_anchor_optional_without_comparison_both_modes() -> None:
    # No like_for_like_comparison in the estimate (no Deferred add-ons) -> the anchor is
    # not required; the report without it passes.
    for mode, html in _mode_variants(GOOD_NO_LFL):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(html, _est_dir(tmp, None, with_block=False), mode=mode)
        assert code == 0, (mode, out)
        assert "heroku_monthly_like_for_like" not in out


def test_like_for_like_anchor_outside_exec_costs_does_not_satisfy_requirement() -> None:
    html = GOOD_NO_LFL.replace(
        '<p class="verdict-headline">Go</p>',
        f'<p class="verdict-headline">Go</p><p>{LFL_ANCHOR}</p>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, _est_dir(tmp, 140))
    assert code == 1, out
    assert 'missing data-cost-key="heroku_monthly_like_for_like" anchor inside' in out


def test_cost_figure_skipped_without_estimation() -> None:
    # No --migration-dir -> no estimation-infra.json -> the cost check is skipped entirely,
    # so the otherwise-valid report passes.
    code, out = run(GOOD, migration_dir=None)
    assert code == 0, out
    assert "cost figure mismatch" not in out
    assert "missing data-cost-key" not in out


def test_balanced_anchor_is_not_this_validators_rule() -> None:
    # `aws_monthly_balanced` moved to the shared validator; a wrong balanced figure
    # anchored here is not reported by the add-on.
    html = GOOD.replace("<p>Balanced $112/mo</p>", '<p>Balanced <span data-cost-key="aws_monthly_balanced">$999/mo</span></p>')
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, _est_dir(tmp, 140))
    assert code == 0, out


# --- Parser robustness, driven through the retained anchor ---


def test_nested_markup_reads() -> None:
    html = GOOD.replace(LFL_ANCHOR, '<span data-cost-key="heroku_monthly_like_for_like"><strong>$140/mo</strong></span>')
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 0, out
    assert "cost figure mismatch" not in out


def test_nested_section_anchor_is_preserved() -> None:
    html = GOOD.replace(LFL_ANCHOR, '<section data-cost-key="heroku_monthly_like_for_like">$140/mo</section>')
    with tempfile.TemporaryDirectory() as tmp:
        migration_dir = _est_dir(tmp, 140)
        for mode, report in _mode_variants(html):
            code, out = run(report, migration_dir, mode=mode)
            assert code == 0, (mode, out)


def test_hidden_nested_section_does_not_supply_required_anchor() -> None:
    html = GOOD.replace(LFL_ANCHOR, f"<section hidden>{LFL_ANCHOR}</section>$999/mo")
    with tempfile.TemporaryDirectory() as tmp:
        migration_dir = _est_dir(tmp, 140)
        for mode, report in _mode_variants(html):
            code, out = run(report, migration_dir, mode=mode)
            assert code == 1, (mode, out)
            assert 'missing data-cost-key="heroku_monthly_like_for_like"' in out


def test_non_numeric_json_value_fails_not_crash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(GOOD, migration_dir=_est_dir(tmp, "$140"))
    assert code == 1, out
    assert "cost_comparison.heroku_monthly_like_for_like is not a numeric dollar amount" in out


def test_anchor_renders_no_dollar_amount_fails() -> None:
    html = GOOD.replace(LFL_ANCHOR, '<span data-cost-key="heroku_monthly_like_for_like">n/a</span>')
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert 'data-cost-key="heroku_monthly_like_for_like" element renders no dollar amount' in out


def test_cost_anchor_inside_html_comment_does_not_satisfy_requirement() -> None:
    # A commented-out anchor is not rendered content — it must not satisfy the
    # required-anchor check, even if the (invisible) figure would have matched.
    html = GOOD.replace(LFL_ANCHOR, f"<!-- {LFL_ANCHOR} -->$999/mo")
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert 'missing data-cost-key="heroku_monthly_like_for_like"' in out


def test_cost_anchor_outside_exec_costs_does_not_satisfy_requirement() -> None:
    # A correct anchor placed in decision-summary (not exec-costs) must not let an
    # unanchored, wrong figure inside exec-costs itself pass silently.
    html = GOOD.replace(LFL_ANCHOR, "$999/mo").replace(
        '<p class="verdict-headline">Go</p>',
        f'<p class="verdict-headline">Go</p><p>{LFL_ANCHOR}</p>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert 'missing data-cost-key="heroku_monthly_like_for_like" anchor inside' in out
    assert "exec-costs" in out


def test_cost_anchor_inside_template_does_not_satisfy_requirement() -> None:
    # <template> content is inert (never rendered) even though the parser still
    # walks its tags — an anchor placed there must not stand in for the visible
    # (wrong) figure sitting right next to it.
    html = GOOD.replace(LFL_ANCHOR, f"<template>{LFL_ANCHOR}</template>$999/mo")
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert 'missing data-cost-key="heroku_monthly_like_for_like"' in out


def test_split_nested_markup_reads_full_text() -> None:
    # A figure split across nested markup within the SAME anchored element must be
    # read as one value through the anchor's own matching close tag, not truncated
    # at the first inner </span>.
    html = GOOD.replace(
        LFL_ANCHOR,
        '<span data-cost-key="heroku_monthly_like_for_like"><span>$</span>140/mo</span>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 0, out
    assert "cost figure mismatch" not in out
    assert "renders no dollar amount" not in out


def test_trailing_text_outside_inner_tag_is_included() -> None:
    # Text sitting after a nested child tag, but still inside the anchor's own
    # close tag, must be included — not dropped at the child's </strong>. Here
    # the anchor's full rendered text is "$1400", which must NOT be truncated
    # to "$140" (that would silently accept a wrong ten-times-off figure).
    html = GOOD.replace(
        LFL_ANCHOR,
        '<span data-cost-key="heroku_monthly_like_for_like"><strong>$140</strong>0/mo</span>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert "cost figure mismatch" in out
    assert '"$1400"' in out


# exec-costs deliberately placed LAST among the <section> elements (only <footer>
# follows) so a closing-tag-spelling bug shows up as a clean `_section_html(...)
# is None` skip rather than an overrun into another section.
GOOD_EXEC_COSTS_LAST = GOOD.replace(
    f'<section id="exec-costs"><p>Balanced $112/mo</p><p>Scope-matched: Heroku {LFL_ANCHOR} vs AWS Balanced $112/mo</p></section>\n',
    "",
).replace(
    "<footer>",
    f'<section id="exec-costs"><p>Balanced $112/mo</p><p>Scope-matched: Heroku {LFL_ANCHOR} vs AWS Balanced $112/mo</p></section>\n<footer>',
)


def test_whitespace_before_exec_costs_closing_angle_bracket_still_gates_required_anchor() -> None:
    # `</section >` (whitespace before `>`) is valid HTML; a regex that matched only
    # the literal `</section>` returned None and skipped the required-anchor check.
    assert GOOD_EXEC_COSTS_LAST.count('<section id="exec-costs">') == 1
    html = GOOD_EXEC_COSTS_LAST.replace(LFL_ANCHOR, "$999/mo").replace(
        "</section>\n<footer>", "</section >\n<footer>"
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert 'missing data-cost-key="heroku_monthly_like_for_like" anchor inside' in out


def test_newline_before_exec_costs_closing_angle_bracket_still_gates_required_anchor() -> None:
    html = GOOD_EXEC_COSTS_LAST.replace(LFL_ANCHOR, "$999/mo").replace(
        "</section>\n<footer>", "</section\n>\n<footer>"
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert 'missing data-cost-key="heroku_monthly_like_for_like" anchor inside' in out


def test_escaped_anchor_example_inside_section_does_not_satisfy_requirement() -> None:
    # An escaped code example (`&lt;span data-cost-key=...&gt;`) decodes to literal
    # anchor text; reparsing that must not find a "real" anchor.
    html = GOOD.replace(
        LFL_ANCHOR,
        "$999/mo "
        '<code>&lt;span data-cost-key="heroku_monthly_like_for_like"&gt;$140/mo&lt;/span&gt;</code>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert 'missing data-cost-key="heroku_monthly_like_for_like"' in out


# --- Rendered-reality regressions: inert/hidden anchors do not count, nested anchors
# are collected independently, and display precision rounds rather than truncates. ---


def test_nested_inner_anchor_is_collected_not_dropped() -> None:
    # An inner data-cost-key nested in an outer one must be read as its own anchor,
    # not swallowed by the outer element. Inner $999 != estimate 140 -> FAIL.
    html = GOOD.replace(
        LFL_ANCHOR,
        '<span data-cost-key="heroku_monthly_like_for_like">$140/mo '
        '<strong data-cost-key="heroku_monthly_like_for_like">$999</strong></span>',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert "999" in out and "mismatch" in out.lower()


def test_hidden_anchor_does_not_satisfy_requirement() -> None:
    html = GOOD.replace(
        LFL_ANCHOR, '<span hidden data-cost-key="heroku_monthly_like_for_like">$140/mo</span>$999'
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert 'missing data-cost-key="heroku_monthly_like_for_like"' in out


def test_hidden_false_is_still_hidden() -> None:
    # In HTML `hidden="false"` is still the Hidden state (invalid-value default).
    html = GOOD.replace(
        LFL_ANCHOR,
        '<span hidden="false" data-cost-key="heroku_monthly_like_for_like">$140/mo</span>$999',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert 'missing data-cost-key="heroku_monthly_like_for_like"' in out


def test_script_anchor_does_not_satisfy_requirement() -> None:
    html = GOOD.replace(
        LFL_ANCHOR,
        '<script type="application/json">'
        '<span data-cost-key="heroku_monthly_like_for_like">$140</span></script>$999',
    )
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 140))
    assert code == 1, out
    assert 'missing data-cost-key="heroku_monthly_like_for_like"' in out


def test_rounded_cents_figure_matches_not_truncated() -> None:
    # estimate 139.90 renders as $140 (nearest dollar); the validator must accept
    # it, not reject it because int(139.90) == 139.
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(GOOD, migration_dir=_est_dir(tmp, 139.90))
    assert code == 0, out
    assert "REPORT_OK" in out


def test_two_dollar_boundary_canonicalizes_consistently() -> None:
    # estimate 1.999 canonicalizes to "2" and a displayed $2 canonicalizes to "2",
    # so they match — the $2 rounding-threshold boundary must not spuriously fail.
    html = GOOD.replace(LFL_ANCHOR, '<span data-cost-key="heroku_monthly_like_for_like">$2/mo</span>')
    with tempfile.TemporaryDirectory() as tmp:
        code, out = run(html, migration_dir=_est_dir(tmp, 1.999))
    assert code == 0, out
    assert "REPORT_OK" in out
