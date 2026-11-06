"""Tests for skills/shared/ai/models/bedrock-model-registry.json and tools/build-model-catalogs.py.

The registry is the single hand-edited source; the per-provider catalogs are rendered from it.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PLUGIN_ROOT / "skills" / "shared" / "ai" / "models"
REGISTRY_PATH = MODELS_DIR / "bedrock-model-registry.json"
REGISTRY_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "model-registry.schema.json"
CATALOG_SCHEMA = PLUGIN_ROOT / "scripts" / "contracts" / "model-selection-catalog.schema.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BUILD = _load_module("model_registry__build", PLUGIN_ROOT / "tools" / "build-model-catalogs.py")
VALIDATOR = _load_module("model_registry__validator", PLUGIN_ROOT / "scripts" / "validate-artifacts.py")


def _registry() -> dict:
    return copy.deepcopy(json.loads(REGISTRY_PATH.read_text()))


def _schema_findings(schema_path: Path, value: dict) -> list:
    out: list = []
    VALIDATOR.validate_json_schema(json.loads(schema_path.read_text()), value, "", "registry", str(schema_path), out)
    return out


# ------------------------------------------------------------------ the checked-in files

def test_checked_in_catalogs_match_the_registry():
    assert BUILD.main(["--check"]) == 0


def test_registry_schema_uses_only_enforced_keywords_and_accepts_the_registry():
    assert VALIDATOR.unsupported_keywords(json.loads(REGISTRY_SCHEMA.read_text())) == []
    assert _schema_findings(REGISTRY_SCHEMA, _registry()) == []


def test_rendered_views_match_the_catalog_schema():
    registry = _registry()
    for name in registry["views"]:
        assert _schema_findings(CATALOG_SCHEMA, BUILD.render_view(registry, name)) == [], name


def test_schema_vocabulary_matches_registry_vocabulary():
    schema = json.loads(REGISTRY_SCHEMA.read_text())
    assert schema["definitions"]["capability"]["enum"] == _registry()["capability_vocabulary"]


def test_each_bedrock_model_has_exactly_one_registry_record():
    owners: dict[str, set[str]] = {}
    for key, record in _registry()["models"].items():
        for path in record["paths"].values():
            owners.setdefault(path["model_id"], set()).add(key)
    duplicated = {model_id: keys for model_id, keys in owners.items() if len(keys) > 1}
    assert duplicated == {}


def test_claude_cross_family_targets_reference_the_anthropic_records():
    registry = _registry()
    openai_claude = {e["model"] for e in registry["views"]["openai"]["models"].values()
                     if registry["models"][e["model"]]["provider"] == "anthropic"}
    assert openai_claude and openai_claude <= set(registry["views"]["anthropic"]["models"])


# ------------------------------------------------------------------ one edit reaches every view

def test_a_shared_fact_edited_once_changes_every_view():
    registry = _registry()
    registry["models"]["claude_opus_5_5"]["output_token_ceiling"] = 64000
    anthropic = BUILD.render_view(registry, "anthropic")["models"]["claude_opus_5_5"]
    openai = BUILD.render_view(registry, "openai")["models"]["anthropic_claude_opus_5_5"]
    assert anthropic["output_token_ceiling"] == openai["output_token_ceiling"] == 64000


def test_capabilities_render_in_each_module_vocabulary():
    registry = _registry()
    anthropic = BUILD.render_view(registry, "anthropic")["models"]["claude_sonnet_5"]["capabilities"]
    openai = BUILD.render_view(registry, "openai")["models"]["anthropic_claude_sonnet_5"]["capabilities"]
    assert anthropic == ["tool_use", "extended_thinking", "vision", "long_context"]
    assert openai == ["tool_or_function_calling", "reasoning", "image_input_vision"]


def test_check_fails_on_a_hand_edited_catalog(tmp_path):
    for name in ("bedrock-model-registry.json", "anthropic-bedrock.json", "openai-bedrock.json"):
        shutil.copy(MODELS_DIR / name, tmp_path / name)
    assert BUILD.main(["--check", "--models-dir", str(tmp_path)]) == 0
    catalog = json.loads((tmp_path / "anthropic-bedrock.json").read_text())
    catalog["models"]["claude_opus_5_5"]["context_window"] = 1
    (tmp_path / "anthropic-bedrock.json").write_text(json.dumps(catalog, indent=2) + "\n")
    assert BUILD.main(["--check", "--models-dir", str(tmp_path)]) == 1
    assert BUILD.main(["--models-dir", str(tmp_path)]) == 0  # rebuild restores it
    assert BUILD.main(["--check", "--models-dir", str(tmp_path)]) == 0


# ------------------------------------------------------------------ registry errors are caught

def _first_openai_entry(registry):
    return next(iter(registry["views"]["openai"]["models"].values()))


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda r: r["models"]["claude_opus_5_5"].update(knowledge_cutoff="2026-06"), id="unknown-record-field"),
    pytest.param(lambda r: r["models"]["claude_opus_5_5"].update(launch_date="tomorrow"), id="bad-date"),
    pytest.param(lambda r: r["models"]["claude_opus_5_5"].update(context_window="big"), id="bad-limit"),
    pytest.param(lambda r: r["models"]["claude_opus_5_5"].pop("capabilities"), id="missing-capabilities"),
    pytest.param(lambda r: r["models"]["claude_opus_5_5"]["capabilities"].append("vision"), id="non-canonical"),
    pytest.param(lambda r: _first_openai_entry(r).update(context_window=1), id="record-field-in-view"),
    pytest.param(lambda r: next(iter(_first_openai_entry(r)["paths"].values())).update(model_id="x"), id="path-override"),
    pytest.param(lambda r: r["views"]["openai"].update(catalog="../x.json"), id="catalog-escapes-dir"),
    pytest.param(lambda r: r["views"].pop("openai"), id="missing-view"),
])
def test_generator_rejects_schema_violations(mutate):
    registry = _registry()
    mutate(registry)
    assert _schema_findings(REGISTRY_SCHEMA, registry) != []
    with pytest.raises(BUILD.RegistryError, match="does not match model-registry.schema.json"):
        BUILD.render_all(registry)


# Invariants the schema cannot express are checked by the generator itself; call those checks
# directly so each message is pinned even though schema validation runs first in render_all.
@pytest.mark.parametrize(("mutate", "check", "message"), [
    (lambda r: _first_openai_entry(r).update(model="nope"), "render", "unknown registry model"),
    (lambda r: r["views"]["openai"]["capabilities"].pop("reasoning"), "render", "has no mapping"),
    (lambda r: r["views"]["openai"]["capabilities"].update(bogus="x"), "render", "non-canonical term"),
    (lambda r: r["views"]["openai"]["capabilities"].update(streaming="reasoning"), "render", "same module term"),
    (lambda r: r["views"]["openai"]["header"].update(colour="blue"), "render", "unknown or generated"),
    (lambda r: r["views"]["openai"]["header"].update(generated_from="x"), "render", "unknown or generated"),
    (lambda r: _first_openai_entry(r)["paths"].update(runtime_invoke={}), "render", "not defined in views.openai.paths"),
    (lambda r: r["models"]["claude_opus_5_5"].update(generation="reasoning"), "render", "belong in each view entry"),
    (lambda r: r["views"]["openai"]["models"].update(dup={**copy.deepcopy(_first_openai_entry(r))}), "render", "already appears"),
    (lambda r: r["capability_vocabulary"].append("reasoning"), "vocab", "duplicates"),
    (lambda r: r["models"].update(orphan=copy.deepcopy(r["models"]["claude_opus_5_5"])), "usage", "not used by any view"),
    (lambda r: r["views"]["anthropic"]["models"]["claude_opus_5_5"]["paths"].pop("runtime_invoke"), "usage", "not exposed by any view"),
])
def test_generator_rejects_semantic_errors(mutate, check, message):
    registry = _registry()
    mutate(registry)
    run = {
        "render": lambda: [BUILD.render_view(registry, name) for name in registry["views"]],
        "vocab": lambda: BUILD.check_vocabulary(registry),
        "usage": lambda: BUILD.check_usage(registry),
    }[check]
    with pytest.raises(BUILD.RegistryError, match=message):
        run()


def test_null_mapping_drops_a_term_by_design():
    registry = _registry()
    registry["models"]["claude_haiku_4_5"]["capabilities"].append("long_context")
    anthropic = BUILD.render_view(registry, "anthropic")["models"]["claude_haiku_4_5"]["capabilities"]
    openai = BUILD.render_view(registry, "openai")["models"]["anthropic_claude_haiku_4_5"]["capabilities"]
    assert "long_context" in anthropic
    assert registry["views"]["openai"]["capabilities"]["long_context"] is None
    assert "long_context" not in openai and len(openai) == len(anthropic) - 1


def test_generator_field_lists_match_the_catalog_schema():
    schema = json.loads(CATALOG_SCHEMA.read_text())
    assert tuple(schema["definitions"]["model"]["properties"]) == BUILD.MODEL_ORDER
    assert tuple(schema["definitions"]["modelPath"]["properties"]) == BUILD.PATH_ORDER
    header = set(schema["properties"]) - {"paths", "models"}
    assert header == set(BUILD.HEADER_KEYS)
    registry_schema = json.loads(REGISTRY_SCHEMA.read_text())
    view_fields = set(registry_schema["definitions"]["viewEntry"]["properties"]) - {"model", "paths"}
    assert view_fields == set(BUILD.VIEW_FIELDS)


def test_rendered_catalogs_carry_the_generated_marker():
    for name in ("anthropic-bedrock.json", "openai-bedrock.json"):
        assert "edit the registry" in json.loads((MODELS_DIR / name).read_text())["generated_from"]


def test_write_mode_creates_missing_catalogs_and_check_reports_them(tmp_path, capsys):
    shutil.copy(REGISTRY_PATH, tmp_path / REGISTRY_PATH.name)
    assert BUILD.main(["--check", "--models-dir", str(tmp_path)]) == 1
    assert "(missing)" in capsys.readouterr().out
    assert BUILD.main(["--models-dir", str(tmp_path)]) == 0
    for name in ("anthropic-bedrock.json", "openai-bedrock.json"):
        assert (tmp_path / name).read_text() == (MODELS_DIR / name).read_text()
