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


def test_would_flip_shared_suffix_cannot_cross_satisfy_items() -> None:
    estimate = _reference_estimate()
    estimate["recommendation"]["would_flip_if"] = [
        "Database changes require specialist evidence",
        "Compute changes require specialist evidence",
    ]
    html = _reference_html().replace(
        FLIP_BLOCK,
        """      <h3>What would flip this</h3>
      <ul class="compact">
        <li>Database changes require specialist evidence</li>
      </ul>""",
    )
    errors = _flip_errors_for_estimate(html, estimate)
    assert errors and "1 of 2" in errors[0] and "Compute" in errors[0], errors


def test_would_flip_shared_suffix_complete_items_pass() -> None:
    estimate = _reference_estimate()
    estimate["recommendation"]["would_flip_if"] = [
        "Database changes require specialist evidence",
        "Compute changes require specialist evidence",
    ]
    html = _reference_html().replace(
        FLIP_BLOCK,
        """      <h3>What would flip this</h3>
      <ul class="compact">
        <li>Database changes require specialist evidence</li>
        <li>Compute changes require specialist evidence</li>
      </ul>""",
    )
    assert _flip_errors_for_estimate(html, estimate) == []


def _flip_errors_for_estimate(html: str, estimate: dict) -> list[str]:
    validator = _load()
    return [e for e in validator.validate_report(html, estimate, None) if "flip" in e]


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


LEAD_IN = '      <p class="muted">Any of these would change the verdict:</p>\n'


def test_would_flip_lead_in_paragraph_before_list_passes() -> None:
    # A one-sentence lead-in between the heading and the <ul> is legitimate
    # output; the items below it are rendered and must be found (regression for
    # the matcher stopping at the first non-item run and reporting "0 of 2").
    html = _reference_html().replace(
        "      <h3>What would flip this</h3>\n", "      <h3>What would flip this</h3>\n" + LEAD_IN
    )
    assert html != _reference_html()
    assert _flip_errors(html) == []


def test_would_flip_lead_in_paragraph_with_empty_list_fails() -> None:
    html = _reference_html().replace(
        FLIP_BLOCK,
        "      <h3>What would flip this</h3>\n" + LEAD_IN + '      <ul class="compact"></ul>',
    )
    assert html != _reference_html()
    errors = _flip_errors(html)
    assert errors and "0 of 2" in errors[0], errors


def test_would_flip_another_heading_before_any_item_is_empty_list() -> None:
    # Prose is skipped, but the search is bounded by the next heading: a flip
    # heading with no items before "Key decisions ahead" renders none of them.
    html = _reference_html().replace(
        FLIP_BLOCK, "      <h3>What would flip this</h3>\n      <p>See below.</p>"
    )
    assert html != _reference_html()
    errors = _flip_errors(html)
    assert errors and "0 of 2" in errors[0], errors


INLINE_LABEL_BLOCK = """      <ul class="compact">
        <li>What would flip this: Single-AZ acceptable: AWS estimate drops further, strengthens go</li>
        <li>BigQuery must cut over in the same window: defer for specialist evidence</li>
      </ul>"""


def test_would_flip_inline_label_item_passes() -> None:
    # The specs only ask for a "short unordered list"; the Heroku decision
    # fixtures render the label inside the first item with no separate heading.
    # That item's remainder plus its siblings are the list.
    html = _reference_html().replace(FLIP_BLOCK, INLINE_LABEL_BLOCK)
    assert html != _reference_html()
    assert _flip_errors(html) == []


def test_would_flip_inline_label_partial_list_fails() -> None:
    html = _reference_html().replace(
        FLIP_BLOCK, INLINE_LABEL_BLOCK.replace(
            "        <li>BigQuery must cut over in the same window: defer for specialist evidence</li>\n",
            "",
        )
    )
    assert html != _reference_html()
    errors = _flip_errors(html)
    assert errors and "1 of 2" in errors[0] and "BigQuery" in errors[0], errors


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


def _without_confirm_in_checklist(html: str) -> str:
    # Reword every list item of the reference summary that happens to contain
    # "confirm", so the word survives only in prose.
    html = html.replace("<li>Condition: confirm", "<li>Condition: verify")
    html = html.replace("not confirmed", "not verified")
    html = html.replace("<li>Confirm Bedrock", "<li>Verify Bedrock")
    return html.replace(
        '<p class="verdict-headline">Go, with conditions</p>',
        '<p class="verdict-headline">Go, with conditions</p>\n'
        "      <p>Confirm these before cutover.</p>",
    )


def test_one_word_condition_only_in_prose_fails() -> None:
    # Conditions render as a checklist, so the scan is scoped to rendered list
    # items. A one-word condition used to be satisfied by that word anywhere in
    # the summary prose and could never be reported as omitted.
    validator = _load()
    html, estimate = _with_condition("Confirm", rendered=False)
    html = _without_confirm_in_checklist(html)
    rendered = validator._rendered_fragment(validator._section_html(html, "decision-summary"))
    assert any("confirm" in text for kind, text in rendered.entries if kind != "li")
    assert not any("confirm" in text for kind, text in rendered.entries if kind == "li")
    errors = [e for e in validator.validate_report(html, estimate, None) if "condition" in e]
    assert errors, "one-word condition rendered only in prose passed"


def test_one_word_condition_in_checklist_passes() -> None:
    validator = _load()
    html, estimate = _with_condition("Confirm", rendered=False)
    html = _without_confirm_in_checklist(html).replace(
        "<li>Condition: verify CUD", "<li>Condition: Confirm CUD"
    )
    errors = [e for e in validator.validate_report(html, estimate, None) if "condition" in e]
    assert errors == [], errors


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


def test_verdict_headline_only_in_hidden_element_or_ancestor_fails() -> None:
    validator = _load()
    for replacement in (
        '<p hidden class="verdict-headline">Go, with conditions</p>',
        '<div hidden><p class="verdict-headline">Go, with conditions</p></div>',
    ):
        html = _reference_html().replace(
            '<p class="verdict-headline">Go, with conditions</p>', replacement
        )
        errors = validator.validate_report(html, _reference_estimate(), None)
        assert any("verdict-headline" in err for err in errors), (replacement, errors)


def test_metric_hero_only_in_hidden_ancestor_fails() -> None:
    validator = _load()
    html = _reference_html().replace('<div class="metric metric-hero">', '<div class="metric">')
    html = html.replace(
        '<div class="metrics">',
        '<div hidden><div class="metric metric-hero"></div></div>\n      <div class="metrics">',
    )
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


def test_would_flip_populated_list_only_in_hidden_element_or_ancestor_fails() -> None:
    for replacement in (
        '      <h3>What would flip this</h3>\n      <ul hidden>\n'
        '        <li>Single-AZ acceptable: AWS estimate drops further, strengthens go</li>\n'
        '        <li>BigQuery must cut over in the same window: defer for specialist evidence</li>\n'
        '      </ul>',
        '<div hidden>' + FLIP_BLOCK + '</div>',
    ):
        html = _reference_html().replace(FLIP_BLOCK, replacement)
        errors = _flip_errors(html)
        assert errors, replacement


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


def test_scenario_column_check_requires_migration_dir() -> None:
    # The what-if column check reads scenarios/index.json via --migration-dir.
    # Without that flag the check never fires, even with >=2 scenarios and a
    # thin what-if-scenarios table missing the decision-core columns.
    validator = _load()
    html = _reference_html().replace(
        '<section id="exec-timeline">',
        '<section id="what-if-scenarios"><table><caption>Scenarios</caption><thead><tr>'
        '<th scope="col">Scenario</th><th scope="col">Monthly</th>'
        "</tr></thead><tbody><tr><td>Baseline</td><td>$1</td></tr></tbody></table></section>"
        '<section id="exec-timeline">',
    )
    ai = json.loads((FIXTURES / "estimation-ai-reference.json").read_text(encoding="utf-8"))
    errors_without_dir = validator.validate_report(html, _reference_estimate(), ai)
    assert errors_without_dir == [], errors_without_dir

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scenarios").mkdir()
        (root / "scenarios" / "index.json").write_text(
            json.dumps({"scenarios": [{"id": "a"}, {"id": "b"}]}), encoding="utf-8"
        )
        errors_with_dir = validator.validate_report(
            html, _reference_estimate(), ai, migration_dir=root
        )
    assert any("Region" in err for err in errors_with_dir), errors_with_dir


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
