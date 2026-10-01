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
