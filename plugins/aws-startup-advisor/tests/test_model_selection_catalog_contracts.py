"""Contract tests for the shared Bedrock model-selection catalogs.

Covers skills/shared/ai/models/{anthropic,openai}-bedrock.json against
scripts/contracts/model-selection-catalog.schema.json, the loaders' selection_status
validation, the selectors honoring selection_status, and consistency between the Claude
records that both catalogs carry (the OpenAI catalog keeps Claude entries as cross-family
Converse targets in its own capability vocabulary).
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PLUGIN_ROOT / "scripts" / "contracts" / "model-selection-catalog.schema.json"
MODELS_DIR = PLUGIN_ROOT / "skills" / "shared" / "ai" / "models"
CATALOGS = {name: MODELS_DIR / f"{name}-bedrock.json" for name in ("anthropic", "openai")}
ADVISOR_SCRIPTS = PLUGIN_ROOT / "skills" / "agent-advisor" / "scripts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_module("model_selection_catalog__validator", PLUGIN_ROOT / "scripts" / "validate-artifacts.py")
# model_recommendation imports its provider modules by name, so the scripts directory must be on
# sys.path while it loads; remove it afterwards so other tests cannot import advisor modules by accident.
sys.path.insert(0, str(ADVISOR_SCRIPTS))
try:
    import model_recommendation as mr  # noqa: E402
finally:
    sys.path.remove(str(ADVISOR_SCRIPTS))


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _catalog(name: str) -> dict:
    return copy.deepcopy(json.loads(CATALOGS[name].read_text()))


def _findings(catalog: dict) -> list:
    out: list = []
    VALIDATOR.validate_json_schema(_schema(), catalog, "", "catalog", str(SCHEMA_PATH), out)
    return out


# ------------------------------------------------------------------ schema

def test_schema_uses_only_enforced_keywords():
    assert VALIDATOR.unsupported_keywords(_schema()) == []


@pytest.mark.parametrize("name", sorted(CATALOGS))
def test_shared_catalog_matches_schema(name):
    assert _findings(_catalog(name)) == []


@pytest.mark.parametrize("name", sorted(CATALOGS))
def test_every_shipped_model_is_selectable_today(name):
    # 1a introduces the field without changing behavior; reference_only arrives with the refresh.
    assert {m["selection_status"] for m in _catalog(name)["models"].values()} == {"selectable"}


def _first_model(catalog: dict) -> dict:
    return next(iter(catalog["models"].values()))


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda c: _first_model(c).pop("selection_status"), id="missing-selection-status"),
    pytest.param(lambda c: _first_model(c).update(selection_status="hidden"), id="unknown-selection-status"),
    pytest.param(lambda c: _first_model(c).update(undocumented_field=True), id="unknown-model-field"),
    pytest.param(lambda c: next(iter(_first_model(c)["paths"].values())).pop("model_id"), id="path-missing-model-id"),
    pytest.param(lambda c: c.update(verified_at="Sept 24"), id="bad-verified-at"),
    pytest.param(lambda c: c.update(provider="gemini"), id="unknown-provider"),
    pytest.param(lambda c: c.update(registry_exclusions={"anthropic.x": ""}), id="empty-exclusion-reason"),
])
@pytest.mark.parametrize("name", sorted(CATALOGS))
def test_schema_rejects_mutation(name, mutate):
    catalog = _catalog(name)
    mutate(catalog)
    assert _findings(catalog) != []


# ------------------------------------------------------------------ schema agrees with the consumers

_LOADERS = {"anthropic": "load_catalog", "openai": "load_openai_catalog"}


def _model_key(name: str) -> str:
    return next(iter(_catalog(name)["models"]))


def _loader_accepts(tmp_path, name, catalog) -> bool:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(catalog))
    try:
        getattr(mr, _LOADERS[name])(path)
    except ValueError:
        return False
    return True


@pytest.mark.parametrize(("name", "field", "value", "valid"), [
    pytest.param("anthropic", "context_window", "unknown", False, id="anthropic-unknown-context"),
    pytest.param("anthropic", "output_token_ceiling", "unknown", False, id="anthropic-unknown-output"),
    pytest.param("anthropic", "context_window", 0, False, id="anthropic-zero-context"),
    pytest.param("openai", "generation", None, False, id="openai-missing-generation"),
    pytest.param("openai", "context_window", "unknown", True, id="openai-unknown-context"),
    pytest.param("openai", "output_token_ceiling", "unknown", True, id="openai-unknown-output"),
    # bool is an int subclass in Python; both boundaries must still reject it.
    pytest.param("anthropic", "context_window", True, False, id="anthropic-bool-context"),
    pytest.param("anthropic", "output_token_ceiling", True, False, id="anthropic-bool-output"),
    pytest.param("openai", "context_window", True, False, id="openai-bool-context"),
    pytest.param("openai", "output_token_ceiling", True, False, id="openai-bool-output"),
])
def test_schema_and_loader_agree_on_provider_rules(tmp_path, name, field, value, valid):
    catalog = _catalog(name)
    model = catalog["models"][_model_key(name)]
    if value is None:
        model.pop(field)
    else:
        model[field] = value
    assert (_findings(catalog) == []) is valid, "schema verdict"
    assert _loader_accepts(tmp_path, name, catalog) is valid, "loader verdict"


def test_openai_unknown_limits_still_produce_a_recommendation():
    catalog = copy.deepcopy(mr.load_openai_catalog())
    for model in catalog["models"].values():
        if model["paths"].get("mantle_openai_responses"):
            model["context_window"] = model["output_token_ceiling"] = "unknown"
    data = _workload("openai", "gpt-6-sol")
    rec = mr.recommend(data, catalog=mr.load_catalog(), openai_catalog=catalog)["workloads"]["w"]
    assert rec["decision_status"] == "recommended"


# ------------------------------------------------------------------ loaders

@pytest.mark.parametrize(("name", "loader"), [("anthropic", "load_catalog"), ("openai", "load_openai_catalog")])
@pytest.mark.parametrize("status", [None, "hidden"])
def test_loader_rejects_missing_or_unknown_selection_status(tmp_path, name, loader, status):
    catalog = _catalog(name)
    model = _first_model(catalog)
    if status is None:
        model.pop("selection_status")
    else:
        model["selection_status"] = status
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match="selection_status"):
        getattr(mr, loader)(path)


@pytest.mark.parametrize(("name", "loader"), [("anthropic", "load_catalog"), ("openai", "load_openai_catalog")])
def test_loader_accepts_reference_only(tmp_path, name, loader):
    catalog = _catalog(name)
    _first_model(catalog)["selection_status"] = "reference_only"
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(catalog))
    assert getattr(mr, loader)(path)["models"]


# ------------------------------------------------------------------ selectors honor selection_status

def _workload(provider, source_model, **requirements):
    return {
        "schema_version": 2, "region": "us-east-1", "primary_unit": "w",
        "workloads": [{
            "workload_id": "w",
            "source": {
                "provider": provider,
                "model_ids": [source_model],
                "sdk": "anthropic" if provider == "anthropic" else "openai",
                "api_surface": "messages" if provider == "anthropic" else "responses",
                "source_paths": ["src/app.py"],
            },
            "requirements": {"data_residency": "global_allowed", **requirements},
            "detected_features": [],
        }],
    }


def _anthropic_pick(catalog):
    data = _workload("anthropic", "claude-opus-4-8", priority="quality", preferred_api_path="runtime_converse")
    return mr.recommend(data, catalog=catalog)["workloads"]["w"]["primary_model"]


def _openai_pick(openai_catalog, source_model, **requirements):
    data = _workload("openai", source_model, **requirements)
    return mr.recommend(data, catalog=mr.load_catalog(), openai_catalog=openai_catalog)["workloads"]["w"]["primary_model"]


def _with_reference_only(catalog, key):
    catalog = copy.deepcopy(catalog)
    catalog["models"][key]["selection_status"] = "reference_only"
    return catalog


def test_anthropic_selector_skips_reference_only():
    catalog = mr.load_catalog()
    assert _anthropic_pick(catalog) == "anthropic.claude-opus-5-5"
    assert _anthropic_pick(_with_reference_only(catalog, "claude_opus_5_5")) != "anthropic.claude-opus-5-5"


def test_openai_same_model_selector_skips_reference_only():
    catalog = mr.load_openai_catalog()
    assert _openai_pick(catalog, "gpt-6-sol") == "openai.gpt-6-sol"
    assert _openai_pick(_with_reference_only(catalog, "openai_gpt_6_sol"), "gpt-6-sol") != "openai.gpt-6-sol"


def test_openai_cross_family_selector_skips_reference_only():
    catalog = mr.load_openai_catalog()
    requirements = {"priority": "quality", "preferred_api_path": "runtime_converse",
                    "preserve_openai_api": False, "governance": ["guardrails"]}
    assert _openai_pick(catalog, "gpt-4", **requirements) == "anthropic.claude-opus-5-5"
    hidden = _with_reference_only(catalog, "anthropic_claude_opus_5_5")
    assert _openai_pick(hidden, "gpt-4", **requirements) != "anthropic.claude-opus-5-5"


def _openai_rec(openai_catalog, source_model, **requirements):
    data = _workload("openai", source_model, **requirements)
    return mr.recommend(data, catalog=mr.load_catalog(), openai_catalog=openai_catalog)["workloads"]["w"]


@pytest.mark.parametrize("requirements", [
    pytest.param({}, id="mantle"),
    pytest.param({"preferred_api_path": "runtime_converse", "governance": ["guardrails"]}, id="runtime"),
    pytest.param({"preserve_openai_api": True, "governance": ["guardrails"]}, id="continuity-vs-governance"),
])
def test_reference_only_astra_fails_closed_without_substitutes(requirements):
    rec = _openai_rec(_with_reference_only(mr.load_openai_catalog(), "openai_gpt_6_astra"), "gpt-6-astra",
                      **requirements)
    assert rec["decision_status"] == "blocked"
    assert rec["primary_model"] is None
    assert [b["code"] for b in rec["blocks"]] == ["model_not_selectable"]
    assert rec["decision_options"] == []


def test_runtime_rationale_names_the_selected_model_when_the_tier_is_reference_only():
    requirements = {"preferred_api_path": "runtime_converse", "preserve_openai_api": False,
                    "governance": ["guardrails"]}
    catalog = mr.load_openai_catalog()
    tier_name = catalog["models"]["anthropic_claude_sonnet_5"]["display_name"]
    baseline = " ".join(_openai_rec(catalog, "gpt-4o", **requirements)["rationale"])
    assert f"maps to {tier_name}" in baseline
    hidden = _with_reference_only(catalog, "anthropic_claude_sonnet_5")
    rec = _openai_rec(hidden, "gpt-4o", **requirements)
    assert rec["primary_model"] != "anthropic.claude-sonnet-5"
    text = " ".join(rec["rationale"])
    assert f"maps to {tier_name}" not in text
    selected_name = next(
        model["display_name"]
        for model in hidden["models"].values()
        for path in model.get("paths", {}).values()
        if isinstance(path, dict) and path.get("model_id") == rec["primary_model"]
    )
    assert selected_name in text
    assert "reference_only" in text


def test_runtime_rationale_does_not_claim_a_reference_only_same_model():
    requirements = {"preferred_api_path": "runtime_converse", "governance": ["guardrails"]}
    catalog = mr.load_openai_catalog()
    assert "source model itself" in " ".join(_openai_rec(catalog, "gpt-6-sol", **requirements)["rationale"])
    rec = _openai_rec(_with_reference_only(catalog, "openai_gpt_6_sol"), "gpt-6-sol", **requirements)
    assert rec["primary_model"] != "openai.gpt-6-sol"
    assert "source model itself" not in " ".join(rec["rationale"])


def test_decision_options_skip_a_reference_only_model():
    requirements = {"preserve_openai_api": True, "governance": ["guardrails"]}
    catalog = mr.load_openai_catalog()
    offered = {o["model"] for o in _openai_rec(catalog, "gpt-6-sol", **requirements)["decision_options"]}
    assert "openai.gpt-6-sol" in offered
    hidden = _with_reference_only(catalog, "openai_gpt_6_sol")
    offered = {o["model"] for o in _openai_rec(hidden, "gpt-6-sol", **requirements)["decision_options"]}
    assert "openai.gpt-6-sol" not in offered


def _all_reference_only(catalog, keys=None):
    catalog = copy.deepcopy(catalog)
    for key, model in catalog["models"].items():
        if keys is None or key in keys:
            model["selection_status"] = "reference_only"
    return catalog


def test_anthropic_with_no_selectable_model_raises_and_names_skipped_entries():
    # Fail-closed by design (same as an unsatisfiable requirement); the message names the cause.
    data = _workload("anthropic", "claude-opus-4-8", priority="quality", preferred_api_path="runtime_converse")
    with pytest.raises(ValueError, match="reference_only entries skipped: claude_haiku_4_5"):
        mr.recommend(data, catalog=_all_reference_only(mr.load_catalog()))


def test_openai_runtime_with_no_selectable_candidate_raises_and_names_skipped_entries():
    catalog = mr.load_openai_catalog()
    runtime_keys = {k for k, m in catalog["models"].items() if "runtime_converse" in m["paths"]}
    data = _workload("openai", "gpt-6-sol", preferred_api_path="runtime_converse", governance=["guardrails"])
    with pytest.raises(ValueError, match="reference_only entries skipped"):
        mr.recommend(data, catalog=mr.load_catalog(), openai_catalog=_all_reference_only(catalog, runtime_keys))


@pytest.mark.parametrize("status", ["Selectable", "reference-only"])
def test_misspelled_selection_status_is_an_error_even_in_memory(status):
    catalog = copy.deepcopy(mr.load_catalog())
    catalog["models"]["claude_opus_5_5"]["selection_status"] = status
    with pytest.raises(ValueError, match="selection_status"):
        _anthropic_pick(catalog)


# ------------------------------------------------------------------ candidate pricing honors selection_status

PRICING = _load_module("model_selection_catalog__pricing", PLUGIN_ROOT / "scripts" / "validate-model-pricing.py")
_PRICING_INPUTS = [
    "skills/agent-advisor/scripts/model_recommendation.py",
    "skills/shared/ai/models/anthropic-bedrock.json",
    "skills/gcp-to-aws/references/vendored/ai/bedrock-pricing-cache.md",
    "skills/azure-to-aws/references/vendored/ai/bedrock-pricing-cache.md",
]


def _pricing_errors(tmp_path, mutate):
    for rel in _PRICING_INPUTS:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((PLUGIN_ROOT / rel).read_bytes())
    catalog_path = tmp_path / _PRICING_INPUTS[1]
    catalog = json.loads(catalog_path.read_text())
    mutate(catalog["models"])
    catalog_path.write_text(json.dumps(catalog))
    return PRICING.validate_model_pricing(tmp_path)


def _unpriced_copy(models, key, *, status, keep_paths):
    record = copy.deepcopy(models["claude_haiku_4_5"])
    record["selection_status"] = status
    record["display_name"] = "Synthetic unpriced model"
    record["paths"] = {p: {**record["paths"][p], "model_id": "anthropic.synthetic-unpriced"} for p in keep_paths}
    models[key] = record


def test_pricing_passes_for_shipped_catalog(tmp_path):
    assert _pricing_errors(tmp_path, lambda models: None) == []


def test_pricing_skips_reference_only_without_runtime_path(tmp_path):
    errors = _pricing_errors(tmp_path, lambda m: _unpriced_copy(
        m, "synthetic", status="reference_only", keep_paths=["mantle_messages"]))
    assert errors == []


def test_pricing_skips_reference_only_without_active_price(tmp_path):
    errors = _pricing_errors(tmp_path, lambda m: _unpriced_copy(
        m, "synthetic", status="reference_only", keep_paths=["runtime_converse"]))
    assert errors == []


def test_pricing_still_fails_selectable_candidate_without_price(tmp_path):
    errors = _pricing_errors(tmp_path, lambda m: _unpriced_copy(
        m, "synthetic", status="selectable", keep_paths=["runtime_converse"]))
    assert errors and all("anthropic.synthetic-unpriced" in e for e in errors)


def test_pricing_reports_selectable_candidate_without_runtime_path(tmp_path):
    errors = _pricing_errors(tmp_path, lambda m: _unpriced_copy(
        m, "synthetic", status="selectable", keep_paths=["mantle_messages"]))
    assert errors and all("synthetic has no runtime_converse" in e for e in errors)


# ------------------------------------------------------------------ duplicated Claude records stay consistent

# The OpenAI module's capability vocabulary -> the Anthropic module's. `long_context` has no
# OpenAI-vocabulary equivalent; the Anthropic catalog sets it exactly when context_window >= 1M.
_OPENAI_TO_ANTHROPIC_CAPABILITY = {
    "tool_or_function_calling": "tool_use",
    "reasoning": "extended_thinking",
    "image_input_vision": "vision",
}
# Fields each module owns in its own terms (labels, provenance, module-specific capability lists).
_VIEW_SPECIFIC = {"display_name", "family", "version", "class", "generation", "capabilities",
                  "capability_source", "evidence", "paths"}


def _claude_pairs():
    anthropic = _catalog("anthropic")["models"]
    by_runtime_id = {m["paths"]["runtime_converse"]["model_id"]: (k, m)
                     for k, m in anthropic.items() if "runtime_converse" in m["paths"]}
    pairs = []
    for key, model in _catalog("openai")["models"].items():
        model_id = model["paths"].get("runtime_converse", {}).get("model_id", "")
        if model_id.startswith("anthropic."):
            twin_key, twin = by_runtime_id.get(model_id, (None, None))
            pairs.append((key, model, twin_key, twin))
    return pairs


def test_every_claude_record_in_openai_catalog_has_an_anthropic_twin():
    pairs = _claude_pairs()
    assert pairs, "expected the OpenAI catalog to carry Claude cross-family targets"
    orphans = [openai_key for openai_key, _, anthropic_key, _ in pairs if anthropic_key is None]
    assert orphans == [], f"Claude records in the OpenAI catalog with no Anthropic-catalog twin: {orphans}"


@pytest.mark.parametrize(("openai_key", "openai_model", "anthropic_key", "anthropic_model"),
                         _claude_pairs(), ids=[p[0] for p in _claude_pairs()])
def test_duplicated_claude_records_agree(openai_key, openai_model, anthropic_key, anthropic_model):
    if anthropic_model is None:
        pytest.skip("no twin; reported by test_every_claude_record_in_openai_catalog_has_an_anthropic_twin")
    for field in (set(openai_model) & set(anthropic_model)) - _VIEW_SPECIFIC:
        assert openai_model[field] == anthropic_model[field], f"{openai_key}.{field} != {anthropic_key}.{field}"

    strip = lambda path: {k: v for k, v in path.items() if k != "evidence"}  # noqa: E731
    assert strip(openai_model["paths"]["runtime_converse"]) == strip(anthropic_model["paths"]["runtime_converse"])

    unmapped = sorted(set(openai_model["capabilities"]) - set(_OPENAI_TO_ANTHROPIC_CAPABILITY))
    assert unmapped == [], (f"{openai_key} uses capabilities with no Anthropic-vocabulary mapping: "
                            f"{unmapped}; extend _OPENAI_TO_ANTHROPIC_CAPABILITY")
    mapped = {_OPENAI_TO_ANTHROPIC_CAPABILITY[c] for c in openai_model["capabilities"]}
    if anthropic_model["context_window"] >= 1_000_000:
        mapped.add("long_context")
    assert mapped == set(anthropic_model["capabilities"]), f"{openai_key} capabilities drifted from {anthropic_key}"
