"""Decision-core content checks for the shared migration-report validator.

A report used to pass when the section IDs existed, even if it never rendered
the verdict headline, flip conditions, specialist callout, or architecture
section. These tests lock the artifact-gated checks that reject that report.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN / "scripts" / "validate-migration-report.py"
FIXTURES = PLUGIN / "fixtures"


def _load():
    spec = importlib.util.spec_from_file_location("validate_migration_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _reference_html() -> str:
    return (FIXTURES / "migration-report-reference.html").read_text(encoding="utf-8")


def _reference_estimate() -> dict:
    return json.loads(
        (FIXTURES / "estimation-infra-reference.json").read_text(encoding="utf-8")
    )


def test_reference_fixture_still_passes() -> None:
    validator = _load()
    ai = json.loads((FIXTURES / "estimation-ai-reference.json").read_text(encoding="utf-8"))
    errors = validator.validate_report(
        _reference_html(),
        _reference_estimate(),
        ai,
    )
    assert errors == [], errors


def test_missing_would_flip_list_fails() -> None:
    validator = _load()
    html = _reference_html().replace("<h3>What would flip this</h3>", "<h3>Notes</h3>")
    errors = validator.validate_report(html, _reference_estimate(), None)
    assert any("would_flip" in err for err in errors), errors


def test_would_flip_list_only_in_template_fails() -> None:
    # A browser never renders <template> contents, so a flip heading hidden there
    # must not satisfy the check (regression for the shared validator keeping
    # <template> text; the Heroku validator already rejected this input).
    validator = _load()
    html = _reference_html().replace(
        "<h3>What would flip this</h3>",
        "<template><h3>What would flip this</h3></template>",
    )
    errors = validator.validate_report(html, _reference_estimate(), None)
    assert any("would_flip" in err for err in errors), errors


FLIP_BLOCK = """      <h3>What would flip this</h3>
      <ul class="compact">
        <li>Single-AZ acceptable: AWS estimate drops further, strengthens go</li>
        <li>BigQuery must cut over in the same window: defer for specialist evidence</li>
      </ul>"""


def _flip_errors(html: str) -> list[str]:
    validator = _load()
    return [e for e in validator.validate_report(html, _reference_estimate(), None) if "flip" in e]


def test_would_flip_heading_with_empty_list_fails() -> None:
    # The heading alone is not the content: an empty <ul> under "What would flip
    # this" renders none of recommendation.would_flip_if and must fail.
    html = _reference_html().replace(
        FLIP_BLOCK, '      <h3>What would flip this</h3>\n      <ul class="compact"></ul>'
    )
    assert html != _reference_html()
    errors = _flip_errors(html)
    assert errors, "empty flip list passed"
    assert "0 of 2" in errors[0], errors


def test_would_flip_partial_list_fails() -> None:
    html = _reference_html().replace(
        "        <li>BigQuery must cut over in the same window: defer for specialist evidence</li>\n",
        "",
    )
    assert html != _reference_html()
    errors = _flip_errors(html)
    assert errors, "partial flip list passed"
    assert "1 of 2" in errors[0] and "BigQuery" in errors[0], errors


def test_would_flip_items_only_in_template_fail() -> None:
    html = _reference_html().replace(
        "      <ul class=\"compact\">\n        <li>Single-AZ acceptable",
        "      <ul class=\"compact\"><template><li>hidden</li></template>\n        <li>Single-AZ acceptable",
    )
    html = html.replace(
        "        <li>BigQuery must cut over in the same window: defer for specialist evidence</li>\n",
        "        <template><li>BigQuery must cut over in the same window: defer for specialist evidence</li></template>\n",
    )
    assert html != _reference_html()
    errors = _flip_errors(html)
    assert errors and "BigQuery" in errors[0], errors


def test_would_flip_complete_list_passes_with_inline_markup() -> None:
    # Inline tags and entities inside the heading and the items are what the
    # reader sees as one phrase; they must not break recognition.
    html = _reference_html().replace(
        FLIP_BLOCK,
        """      <h3>What&nbsp;<em>would</em>\n flip this</h3>
      <ul class="compact">
        <li><strong>Single-AZ</strong> acceptable: AWS estimate drops further, strengthens go</li>
        <li>BigQuery must cut over in the same window: defer for specialist evidence</li>
      </ul>""",
    )
    assert html != _reference_html()
    assert _flip_errors(html) == []


def _with_condition(condition: str, *, rendered: bool) -> tuple[str, dict]:
    estimate = _reference_estimate()
    estimate["recommendation"]["conditions"] = [condition]
    html = _reference_html()
    if rendered:
        html = html.replace(
            "<li>Condition: confirm CUD expiration date before committing a migration start date</li>",
            f"<li>Condition: {condition}</li>",
        )
        assert html != _reference_html()
    return html, estimate


def test_short_rendered_conditions_pass() -> None:
    # One-to-three-word conditions are a single phrase narrower than the old
    # fixed four-word shingle; they must match when rendered verbatim.
    validator = _load()
    for condition in ("Confirm capacity", "Complete load testing", "Confirm"):
        html, estimate = _with_condition(condition, rendered=True)
        errors = [e for e in validator.validate_report(html, estimate, None) if "condition" in e]
        assert errors == [], (condition, errors)


def test_omitted_short_condition_fails() -> None:
    validator = _load()
    html, estimate = _with_condition("Confirm capacity", rendered=False)
    errors = [e for e in validator.validate_report(html, estimate, None) if "condition" in e]
    assert errors, "omitted condition passed"


def test_omitted_long_condition_fails() -> None:
    validator = _load()
    html, estimate = _with_condition(
        "Complete a load test against the Balanced sizing before cutover", rendered=False
    )
    errors = [e for e in validator.validate_report(html, estimate, None) if "condition" in e]
    assert errors, "omitted condition passed"


def test_verdict_headline_only_in_template_fails() -> None:
    validator = _load()
    html = _reference_html().replace(
        '<p class="verdict-headline">Go, with conditions</p>',
        '<template><p class="verdict-headline">Go, with conditions</p></template>',
    )
    assert html != _reference_html()
    errors = validator.validate_report(html, _reference_estimate(), None)
    assert any("verdict-headline" in err for err in errors), errors


def test_metric_hero_only_in_template_fails() -> None:
    validator = _load()
    html = _reference_html().replace('<div class="metric metric-hero">', '<div class="metric">')
    html = html.replace(
        '<div class="metrics">',
        '<template><div class="metric metric-hero"></div></template>\n      <div class="metrics">',
    )
    assert html.count("metric-hero") >= 1
    errors = validator.validate_report(html, _reference_estimate(), None)
    assert any("metric-hero" in err for err in errors), errors


def test_metric_hero_unquoted_class_passes() -> None:
    # Class tokens are read from the parsed attribute, not a literal regex, so
    # any legal spelling of the attribute counts as rendered.
    validator = _load()
    html = _reference_html().replace(
        '<div class="metric metric-hero">', "<div class='metric metric-hero'>"
    )
    assert html != _reference_html()
    errors = validator.validate_report(html, _reference_estimate(), None)
    assert not any("metric-hero" in err for err in errors), errors


def test_deferred_service_without_callout_fails() -> None:
    validator = _load()
    html = _reference_html().replace("specialist engagement", "analytics follow-up")
    html = html.replace("Specialist engagement", "Analytics follow-up")
    design = {
        "clusters": [
            {
                "resources": [
                    {"aws_service": "Deferred — specialist engagement"},
                ]
            }
        ]
    }
    errors = validator.validate_report(html, _reference_estimate(), None, design)
    assert any("specialist" in err.lower() for err in errors), errors


def test_clusters_without_architecture_section_fail() -> None:
    validator = _load()
    html = _reference_html().replace('id="exec-architecture"', 'id="not-architecture"')
    design = {"clusters": [{"resources": [{"aws_service": "Amazon S3"}]}]}
    errors = validator.validate_report(html, _reference_estimate(), None, design)
    assert any("exec-architecture" in err for err in errors), errors


def test_decision_fixture_still_passes() -> None:
    validator = _load()
    root = FIXTURES / "gcp-decision-gate" / "after-decide-complete"
    html = (root / "decision-report.html").read_text(encoding="utf-8")
    estimate = json.loads((root / "estimation-infra.json").read_text(encoding="utf-8"))
    errors = validator.validate_report(
        html,
        estimate,
        None,
        None,
        migration_dir=root,
        mode="decision",
    )
    assert errors == [], errors
