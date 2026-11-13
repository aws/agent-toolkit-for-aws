"""End-to-end CLI tests for reference_only outcomes (`blocked` results).

Runs model_recommendation.main() with jsonschema installed (a dependency of this
project), so every written artifact is validated against
schemas/model-recommendation.json, and checks rerun behavior with prior artifacts.
"""

import copy
import json

import jsonschema
import pytest

import model_recommendation as mr

_REAL_OPENAI_LOADER = mr.load_openai_catalog


def _write(path, data):
    path.write_text(json.dumps(data))
    return path


def _input(tmp_path, provider, source_model, api_surface, **requirements):
    return _write(tmp_path / "model-recommendation-input.json", {
        "schema_version": 2, "region": "us-east-1", "primary_unit": "w",
        "workloads": [{
            "workload_id": "w",
            "source": {"provider": provider, "model_ids": [source_model], "sdk": provider,
                       "api_surface": api_surface, "source_paths": ["src/app.py"]},
            "requirements": {"priority": "balanced", "critical_features": [],
                             "data_residency": "global_allowed", **requirements},
            "detected_features": [],
        }],
    })


def _reference_only(catalog, keys):
    catalog = copy.deepcopy(catalog)
    for key in keys:
        catalog["models"][key]["selection_status"] = "reference_only"
    return catalog


def _use_openai_catalog(monkeypatch, tmp_path, catalog):
    path = _write(tmp_path / "openai-bedrock.json", catalog)
    monkeypatch.setattr(mr, "load_openai_catalog", lambda path_=None: _REAL_OPENAI_LOADER(path))


def _run(input_path, capsys, *extra):
    assert mr.main([str(input_path), *extra]) == 0
    assert "SCHEMA_VALIDATED=yes" in capsys.readouterr().out
    return json.loads((input_path.parent / "model-recommendation.json").read_text())["workloads"]["w"]


def test_reference_only_astra_writes_a_schema_valid_blocked_result(tmp_path, monkeypatch, capsys):
    _use_openai_catalog(monkeypatch, tmp_path,
                        _reference_only(_REAL_OPENAI_LOADER(), ["openai_gpt_6_astra"]))
    rec = _run(_input(tmp_path, "openai", "gpt-6-astra", "responses"), capsys)
    assert rec["decision_status"] == "blocked"
    assert rec["primary_model"] is None and rec["decision_options"] == []
    assert [b["code"] for b in rec["blocks"]] == ["model_not_selectable"]
    assert rec["rollout"]["strategy"] == "blocked"


def test_rerun_into_blocked_overwrites_prior_artifacts(tmp_path, monkeypatch, capsys):
    input_path = _input(tmp_path, "openai", "gpt-6-astra", "responses")
    first = _run(input_path, capsys)
    assert first["decision_status"] == "recommended"
    verification = tmp_path / "model-verification.json"
    verification.write_text("{}")  # a probe result for the earlier recommendation

    _use_openai_catalog(monkeypatch, tmp_path,
                        _reference_only(_REAL_OPENAI_LOADER(), ["openai_gpt_6_astra"]))
    rerun = _run(input_path, capsys)
    assert rerun["decision_status"] == "blocked"
    assert not verification.exists(), "a stale verification must not survive a changed contract"


def test_one_remaining_option_is_blocked_not_padded(tmp_path, monkeypatch, capsys):
    # A verified Mantle selector vs Converse-only governance offers a Mantle option and a
    # runtime option (API continuity alone never selects Mantle). With every Mantle-capable
    # model reference_only, only the runtime option remains. GPT-5.6 Terra lists Guardrails as
    # Converse-only, so the governance side is runtime Converse.
    catalog = _REAL_OPENAI_LOADER()
    mantle_keys = [k for k, m in catalog["models"].items()
                   if any(p.startswith("mantle_") for p in m["paths"])]
    _use_openai_catalog(monkeypatch, tmp_path, _reference_only(catalog, mantle_keys))
    rec = _run(_input(tmp_path, "openai", "gpt-5.6-terra", "responses",
                      preserve_openai_api=True, mantle_selector="projects",
                      governance=["guardrails"]), capsys)
    assert rec["decision_status"] == "blocked"
    assert [b["code"] for b in rec["blocks"]] == ["decision_option_unavailable"]
    assert len(rec["decision_options"]) == 1
    assert all(o["api_path"] == "runtime_converse" for o in rec["decision_options"])
    offered = {o["model_key"] for o in rec["decision_options"]}
    assert not offered & set(mantle_keys) - {k for k in mantle_keys if k.startswith("anthropic_")}


def test_anthropic_conflict_with_no_selectable_side_is_blocked(tmp_path, capsys):
    catalog = _reference_only(mr.load_catalog(), list(mr.load_catalog()["models"]))
    catalog_path = _write(tmp_path / "anthropic-bedrock.json", catalog)
    rec = _run(_input(tmp_path, "anthropic", "claude-opus-4-8", "messages",
                      preserve_messages_api=True, governance=["guardrails"]),
               capsys, "--catalog", str(catalog_path))
    assert rec["decision_status"] == "blocked"
    assert rec["decision_options"] == []
    assert "decision_option_unavailable" in [b["code"] for b in rec["blocks"]]


def test_unsatisfiable_conflict_with_all_selectable_still_raises(tmp_path):
    # Unchanged fail-closed behavior when no reference_only entry is involved.
    input_path = _input(tmp_path, "anthropic", "claude-opus-4-8", "messages",
                        preserve_messages_api=True, governance=["guardrails"],
                        min_context_tokens=2_000_000)
    with pytest.raises(ValueError, match="no candidate for every conflicting"):
        mr.main([str(input_path)])


@pytest.mark.parametrize("options", [0, 1])
def test_schema_rejects_decision_required_with_fewer_than_two_options(options):
    schema = json.loads((mr.pathlib.Path(mr.__file__).parent / "schemas" / "model-recommendation.json").read_text())
    rec = mr.recommend(json.loads(json.dumps({
        "schema_version": 2, "region": "us-east-1", "primary_unit": "w",
        "workloads": [{"workload_id": "w",
                       "source": {"provider": "openai", "model_ids": ["gpt-6-sol"], "sdk": "openai",
                                  "api_surface": "responses", "source_paths": ["src/app.py"]},
                       "requirements": {"preserve_openai_api": True, "mantle_selector": "projects",
                                        "governance": ["guardrails"],
                                        "data_residency": "global_allowed"},
                       "detected_features": []}],
    })))
    assert rec["workloads"]["w"]["decision_status"] == "decision_required"
    jsonschema.validate(rec, schema)
    rec["workloads"]["w"]["decision_options"] = rec["workloads"]["w"]["decision_options"][:options]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(rec, schema)


# --- blocked only when reference_only entries emptied the side (review on #567) ----------------

def _workload_input(provider, source_model, api_surface, **requirements):
    return {
        "schema_version": 2, "region": "us-east-1", "primary_unit": "w",
        "workloads": [{
            "workload_id": "w",
            "source": {"provider": provider, "model_ids": [source_model], "sdk": provider,
                       "api_surface": api_surface, "source_paths": ["src/app.py"]},
            "requirements": {"priority": "balanced", "critical_features": [],
                             "data_residency": "global_allowed", **requirements},
            "detected_features": [],
        }],
    }


def test_unrelated_reference_only_does_not_turn_an_unsatisfiable_conflict_into_blocked():
    # Same unsatisfiable 2M-token conflict as above, but one model is reference_only. That
    # entry cannot fill either side (no Claude has a 2M window), so the raise must stand.
    catalog = _reference_only(mr.load_catalog(), ["claude_haiku_4_5"])
    data = _workload_input("anthropic", "claude-opus-4-8", "messages", preserve_messages_api=True,
                           governance=["guardrails"], min_context_tokens=2_000_000)
    with pytest.raises(ValueError, match="no candidate for every conflicting"):
        mr.recommend(data, catalog=catalog)


def test_anthropic_blocked_names_only_the_entries_that_would_fill_the_side():
    catalog = mr.load_catalog()
    # Remove the Mantle Messages side from everything except Opus, then hide Opus: only Opus
    # could fill that side, so it alone is named; Sonnet and Haiku stay selectable for runtime.
    for key, model in catalog["models"].items():
        if key != "claude_opus_5_5":
            model["paths"]["mantle_messages"]["available"] = False
    catalog = _reference_only(catalog, ["claude_opus_5_5"])
    rec = mr.recommend(_workload_input("anthropic", "claude-opus-4-8", "messages",
                                       preserve_messages_api=True, mantle_selector="workspaces",
                                       governance=["guardrails"]),
                       catalog=catalog)["workloads"]["w"]
    assert rec["decision_status"] == "blocked"
    finding = next(b for b in rec["blocks"] if b["code"] == "decision_option_unavailable")
    assert "mantle_messages" in finding["message"]
    assert "claude_opus_5_5" in finding["message"]
    assert "claude_sonnet_5" not in finding["message"] and "claude_haiku_4_5" not in finding["message"]


def test_openai_unrelated_reference_only_keeps_the_unsatisfiable_raise():
    catalog = copy.deepcopy(_REAL_OPENAI_LOADER())
    # No model offers a Mantle path at all, so the continuity side is unsatisfiable regardless
    # of selection_status; one unrelated reference_only entry must not change that.
    for model in catalog["models"].values():
        for path_id, path in model["paths"].items():
            if path_id.startswith("mantle_"):
                path["available"] = False
    catalog = _reference_only(catalog, ["anthropic_claude_haiku_4_5"])
    data = _workload_input("openai", "gpt-6-sol", "responses",
                           preserve_openai_api=True, mantle_selector="projects",
                           governance=["guardrails"])
    with pytest.raises(ValueError, match="cannot supply both decision options"):
        mr.recommend(data, catalog=mr.load_catalog(), openai_catalog=catalog)


def test_openai_blocked_names_only_mantle_side_entries(tmp_path, monkeypatch, capsys):
    catalog = _REAL_OPENAI_LOADER()
    mantle_keys = [k for k, m in catalog["models"].items()
                   if any(p.startswith("mantle_") for p in m["paths"])]
    # Also hide a runtime-only Claude target: it cannot fill the Mantle side, so it must not
    # be named.
    hidden = _reference_only(catalog, mantle_keys + ["anthropic_claude_haiku_4_5"])
    rec = mr.recommend(_workload_input("openai", "gpt-6-sol", "responses",
                                       preserve_openai_api=True, mantle_selector="projects",
                                       governance=["guardrails"]),
                       catalog=mr.load_catalog(), openai_catalog=hidden)["workloads"]["w"]
    assert rec["decision_status"] == "blocked"
    message = next(b for b in rec["blocks"] if b["code"] == "decision_option_unavailable")["message"]
    named = {k for k in mantle_keys + ["anthropic_claude_haiku_4_5"] if k in message}
    assert named and named <= set(mantle_keys)
    assert "anthropic_claude_haiku_4_5" not in message
