"""Currency-formatting tests for the heroku-to-aws report validator.

Kept in a separate module alongside the validator (and the structural
test_validate_heroku_migration_report.py) so the whole validator ships as one
self-contained unit under skills/heroku-to-aws/scripts/. Mirrors the GCP
validator's currency-formatting tests in test_validate_migration_report.py —
same rule, same regressions, same fixture-shaped inline HTML pattern.
"""

from __future__ import annotations

import subprocess  # nosec B404 — test-only, list args, no shell, committed script path
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "validate-heroku-migration-report.py"

GOOD = """<!DOCTYPE html>
<html lang="en"><body><div class="report">
<section id="decision-summary"><p class="verdict-headline">Go</p></section>
<section id="exec-costs"><p>Balanced Est. $112/mo</p></section>
<section id="cost-optimization"><p>No 1-year/3-year commitment product applies to this architecture.</p></section>
<section id="next-steps"><ol><li>See MIGRATION_GUIDE.md</li></ol></section>
<footer>draft for review</footer>
</div></body></html>
"""


def run(html: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "migration-report.html"
        report.write_text(html, encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT), str(report)]
        result = subprocess.run(cmd, capture_output=True, text=True)  # nosec B603
        return result.returncode, result.stdout + result.stderr


def test_good_report_has_no_currency_formatting_violations() -> None:
    code, out = run(GOOD)
    assert code == 0, out
    assert "currency formatting" not in out


def test_monthly_figure_with_cents_fails() -> None:
    # Regression: the exact SF Beach report drift — a multi-thousand-dollar
    # monthly figure rendered with cents.
    html = GOOD.replace("Est. $112/mo", "Est. $25,684.89/mo")
    code, out = run(html)
    assert code == 1, out
    assert "currency formatting" in out
    assert "$25,684.89" in out


def test_small_monthly_total_under_two_dollars_with_cents_passes() -> None:
    html = GOOD.replace("Est. $112/mo", "Est. $1.50/mo")
    code, out = run(html)
    assert code == 0, out
    assert "currency formatting" not in out


def test_hourly_rate_with_cents_passes() -> None:
    html = GOOD.replace("Est. $112/mo", "Est. $23.50/hr")
    code, out = run(html)
    assert code == 0, out
    assert "currency formatting" not in out


def test_per_unit_commitment_rate_with_cents_passes() -> None:
    html = GOOD.replace("Est. $112/mo", "Est. $21.18 (1-mo commit)")
    code, out = run(html)
    assert code == 0, out
    assert "currency formatting" not in out


def test_multiple_bad_monthly_figures_all_reported() -> None:
    html = GOOD.replace(
        "Est. $112/mo",
        "Est. $1,371.82/mo and Est. $80.30/mo",
    )
    code, out = run(html)
    assert code == 1, out
    assert "$1,371.82" in out
    assert "$80.30" in out


def test_repeated_bad_figure_reported_once() -> None:
    html = GOOD.replace(
        "Est. $112/mo",
        "Est. $999.99/mo, repeated: Est. $999.99/mo",
    )
    code, out = run(html)
    assert code == 1, out
    assert out.count("$999.99") == 1


def test_percentages_and_versions_never_trigger_currency_check() -> None:
    html = GOOD.replace(
        "</footer>",
        "</footer><p>Terraform 1.15.2, 82.5% reduction, RTO 4.5 hours.</p>",
    )
    code, out = run(html)
    assert code == 0, out
    assert "currency formatting" not in out


def test_per_policy_rate_with_cents_passes() -> None:
    html = GOOD.replace("Est. $112/mo", "Est. $5.00/mo per policy")
    code, out = run(html)
    assert code == 0, out
    assert "currency formatting" not in out


def test_bad_monthly_figure_spelled_slash_month_fails() -> None:
    # Regression: "month" alone must not exempt a figure the way "/hr" does —
    # it's exactly the unit an ordinary monthly total is denominated in, not
    # evidence of a per-unit rate.
    html = GOOD.replace("Est. $112/mo", "Est. $25,684.89/month")
    code, out = run(html)
    assert code == 1, out
    assert "$25,684.89" in out


def test_bad_monthly_figure_spelled_per_month_fails() -> None:
    html = GOOD.replace("Est. $112/mo", "Est. $25,684.89 per month")
    code, out = run(html)
    assert code == 1, out
    assert "$25,684.89" in out


def test_bad_monthly_figure_spelled_monthly_fails() -> None:
    html = GOOD.replace("Est. $112/mo", "Est. $25,684.89 monthly")
    code, out = run(html)
    assert code == 1, out
    assert "$25,684.89" in out


def test_hourly_rate_split_by_inline_tag_still_recognized() -> None:
    # Regression: raw-HTML regex matching saw </strong> between the amount
    # and its unit and failed to recognize the rate suffix.
    html = GOOD.replace("Est. $112/mo", "Est. <strong>$23.50</strong>/hr")
    code, out = run(html)
    assert code == 0, out
    assert "currency formatting" not in out


def test_hourly_rate_with_nbsp_before_unit_still_recognized() -> None:
    # Regression: an HTML entity separator between the amount and its unit
    # must decode before the rate-suffix match.
    html = GOOD.replace("Est. $112/mo", "Est. $23.50&nbsp;/hr")
    code, out = run(html)
    assert code == 0, out
    assert "currency formatting" not in out


def test_commented_out_raw_figure_never_flagged() -> None:
    # Regression: an HTML comment is never rendered by a browser, so a raw,
    # unrounded figure left in a comment must not be flagged.
    html = GOOD.replace(
        "Est. $112/mo",
        "Est. $112/mo<!-- raw estimate $25,684.89/mo -->",
    )
    code, out = run(html)
    assert code == 0, out
    assert "currency formatting" not in out


def test_numeric_character_reference_dollar_sign_still_flagged() -> None:
    # Regression: the reverse direction of the entity-decoding gap — a
    # numeric character reference for "$" (&#36;) is real, visible content
    # once decoded, and must not silently pass.
    html = GOOD.replace("Est. $112/mo", "Est. &#36;25,684.89/mo")
    code, out = run(html)
    assert code == 1, out
    assert "$25,684.89" in out


def test_bad_monthly_figure_not_exempted_by_next_cells_rate_word() -> None:
    # Regression: a block-level boundary (a table cell/row end) was emitted
    # as a single separating space, which does not itself stop a word-based
    # regex — an unrelated word that happens to open the NEXT cell (e.g.
    # "Hourly") was readable as the FIRST cell's own rate suffix.
    html = GOOD.replace(
        "Est. $112/mo",
        "Est. <table><tr><td>$25,684.89</td>"
        "<td>Hourly rates unchanged</td></tr></table>",
    )
    code, out = run(html)
    assert code == 1, out
    assert "$25,684.89" in out


def test_bad_monthly_figure_still_flagged_with_unrelated_neighbor_cell() -> None:
    # Control for the above: the same boundary case but the neighboring
    # cell's text does NOT start with a rate word.
    html = GOOD.replace(
        "Est. $112/mo",
        "Est. <table><tr><td>$25,684.89</td>"
        "<td>Rates unchanged</td></tr></table>",
    )
    code, out = run(html)
    assert code == 1, out
    assert "$25,684.89" in out
