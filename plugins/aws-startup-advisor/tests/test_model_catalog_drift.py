"""Tests for tools/model-catalog-drift.py (selection catalogs vs. the lifecycle registry)."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "tools" / "model-catalog-drift.py"
TODAY = dt.date(2026, 11, 4)


def _load():
    spec = importlib.util.spec_from_file_location("model_catalog_drift", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["model_catalog_drift"] = mod
    spec.loader.exec_module(mod)
    return mod


drift = _load()

REGISTRY = """# Registry

**Staleness window:** 45 days

## Capability Constraints (verified October 26, 2026)

| Model | Model ID | Lifecycle | Context |
| ----- | -------- | --------- | ------- |
| Claude New  | `anthropic.claude-new` ¹ | Active (launched 2026-10-01) | 1M |
| Claude Old  | `anthropic.claude-old`   | Active (launched 2026-01-01) | 1M |
| Nova Pro    | `amazon.nova-pro-v1:0`   | Active (launched 2024-12-05) | 300K |
| GPT New     | `openai.gpt-new`         | Active (launched 2026-10-01) | 1M |

## Legacy / EOL Models

| Model | Model ID | EOL Date | Days | Status |
| ----- | -------- | -------- | ---- | ------ |
| Claude Gone | `anthropic.claude-gone` | 2026-12-01 | 27 | **excluded** |
"""


def _catalog(ids, verified="2026-10-20", exclusions=None):
    data = {"verified_at": verified, "models": {
        f"m{i}": {"paths": {"runtime_converse": {"model_id": model_id}}} for i, model_id in enumerate(ids)}}
    if exclusions:
        data["registry_exclusions"] = exclusions
    return data


def _tree(tmp_path, anthropic, openai, registry=REGISTRY):
    plugin = tmp_path / "p"
    ai = plugin / "skills" / "shared" / "ai"
    (ai / "models").mkdir(parents=True)
    (ai / "ai-model-lifecycle.md").write_text(registry)
    (ai / "models" / "anthropic-bedrock.json").write_text(json.dumps(anthropic))
    (ai / "models" / "openai-bedrock.json").write_text(json.dumps(openai))
    return plugin


def test_parses_only_active_capability_rows():
    assert drift.registry_active_ids(REGISTRY) == [
        "anthropic.claude-new", "anthropic.claude-old", "amazon.nova-pro-v1:0", "openai.gpt-new"]


def test_clean_when_every_active_provider_model_is_covered(tmp_path):
    plugin = _tree(tmp_path, _catalog(["anthropic.claude-new", "anthropic.claude-old"]),
                   _catalog(["openai.gpt-new"]))
    assert drift.check(plugin, TODAY) == ([], [])


def test_missing_active_model_is_a_warning_and_fails_strict(tmp_path, capsys):
    plugin = _tree(tmp_path, _catalog(["anthropic.claude-old"]), _catalog(["openai.gpt-new"]))
    errors, warnings = drift.check(plugin, TODAY)
    assert errors == []
    assert len(warnings) == 1 and "`anthropic.claude-new`" in warnings[0]
    # Every entry under `models` is a selection candidate, so the remediation must not suggest a
    # non-selectable "reference-only" entry; it points at registry_exclusions instead.
    assert "registry_exclusions" in warnings[0] and "reference-only" not in warnings[0]
    assert drift.main(["--plugin-root", str(plugin), "--today", "2026-11-04"]) == 0
    assert drift.main(["--plugin-root", str(plugin), "--today", "2026-11-04", "--strict"]) == 1
    assert "anthropic.claude-new" in capsys.readouterr().out


def test_registry_exclusions_record_an_intentional_omission(tmp_path):
    plugin = _tree(tmp_path, _catalog(["anthropic.claude-old"],
                                      exclusions={"anthropic.claude-new": "not in default pool"}),
                   _catalog(["openai.gpt-new"]))
    assert drift.check(plugin, TODAY) == ([], [])


def test_exclusion_for_a_non_active_id_is_a_warning(tmp_path):
    plugin = _tree(tmp_path, _catalog(["anthropic.claude-new", "anthropic.claude-old"],
                                      exclusions={"anthropic.claude-typo": "not in default pool"}),
                   _catalog(["openai.gpt-new"]))
    errors, warnings = drift.check(plugin, TODAY)
    assert errors == []
    assert len(warnings) == 1 and "`anthropic.claude-typo`" in warnings[0]


def test_exclusion_without_a_reason_is_an_error(tmp_path):
    plugin = _tree(tmp_path, _catalog(["anthropic.claude-old"], exclusions={"anthropic.claude-new": " "}),
                   _catalog(["openai.gpt-new"]))
    errors, _ = drift.check(plugin, TODAY)
    assert len(errors) == 1 and "non-empty reason" in errors[0]


def test_non_object_exclusions_is_an_error(tmp_path):
    anthropic = _catalog(["anthropic.claude-new", "anthropic.claude-old"])
    anthropic["registry_exclusions"] = ["anthropic.claude-new"]
    plugin = _tree(tmp_path, anthropic, _catalog(["openai.gpt-new"]))
    errors, _ = drift.check(plugin, TODAY)
    assert len(errors) == 1 and "must be an object" in errors[0]


def test_future_verified_at_is_a_warning(tmp_path):
    plugin = _tree(tmp_path, _catalog(["anthropic.claude-new", "anthropic.claude-old"], verified="2026-12-01"),
                   _catalog(["openai.gpt-new"]))
    errors, warnings = drift.check(plugin, TODAY)
    assert errors == [] and len(warnings) == 1 and "in the future" in warnings[0]


def test_invalid_json_and_bad_date_are_errors(tmp_path):
    plugin = _tree(tmp_path, _catalog(["anthropic.claude-new"], verified="last week"), _catalog([]))
    (plugin / "skills/shared/ai/models/openai-bedrock.json").write_text("{not json")
    errors, _ = drift.check(plugin, TODAY)
    assert any("not an ISO date" in e for e in errors)
    assert any("invalid JSON" in e for e in errors)


def test_stale_catalog_is_a_warning(tmp_path):
    plugin = _tree(tmp_path, _catalog(["anthropic.claude-new", "anthropic.claude-old"], verified="2026-08-01"),
                   _catalog(["openai.gpt-new"]))
    errors, warnings = drift.check(plugin, TODAY)
    assert errors == [] and len(warnings) == 1 and "95 days old" in warnings[0]


def test_unparseable_registry_is_an_error_even_without_strict(tmp_path):
    plugin = _tree(tmp_path, _catalog([]), _catalog([]), registry="# Registry\n\nno table\n")
    errors, _ = drift.check(plugin, TODAY)
    assert errors and "ZERO Active rows" in errors[0]
    assert drift.main(["--plugin-root", str(plugin), "--today", "2026-11-04"]) == 1


def test_real_plugin_has_no_structural_errors():
    errors, _ = drift.check(PLUGIN_ROOT, TODAY)
    assert errors == []
