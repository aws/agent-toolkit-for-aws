"""Tests for bedrock-migration-assessment's OpenAI usage reader, migration preview, and Clarify fast path."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import re
import sys
import urllib.error
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BMA = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
FIXTURES = PLUGIN_ROOT / "fixtures"
READER = (BMA / "references/phases/discover/discover-openai-api.md").read_text(encoding="utf-8")
CONTROLLER = (BMA / "references/phases/discover/discover.md").read_text(encoding="utf-8")
CLARIFY = (BMA / "references/phases/clarify/clarify-ai-only.md").read_text(encoding="utf-8")
KEY = "sk-admin-TESTKEY0123456789"


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, BMA / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


USAGE = _module("bma_openai_usage", "openai-usage.py")
PREVIEW = _module("bma_migration_preview", "migration-preview.py")


class FakeAPI:
    """Stands in for urlopen: records every request and answers from a script of responses per path."""

    def __init__(self, answers: dict):
        self.answers, self.requests = answers, []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        path = request.full_url.split("?")[0].removeprefix(USAGE.BASE_URL)
        answer = self.answers.get(path, {"data": [], "has_more": False, "next_page": None})
        answer = answer.pop(0) if isinstance(answer, list) else answer
        if isinstance(answer, int):
            body = json.dumps({"error": {"message": f"Incorrect API key provided: {KEY}"}}).encode()
            raise urllib.error.HTTPError(request.full_url, answer, "err", {}, io.BytesIO(body))
        return io.BytesIO(json.dumps(answer).encode())


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    path = tmp_path / ".openai-admin-env"
    path.write_text(f"OPENAI_ADMIN_KEY={KEY}\n")
    return path


def _capture(monkeypatch, tmp_path, key_file, answers):
    api = FakeAPI(answers)
    monkeypatch.setattr(USAGE, "opener", api)
    monkeypatch.setattr(USAGE, "sleep", lambda s: None)
    code = USAGE.main(["capture", "--key-file", str(key_file), "--out-dir", str(tmp_path / "cap"), "--project", "proj_app"])
    return code, api, json.loads((tmp_path / "cap" / "manifest.json").read_text())


def test_capture_is_get_only_scoped_and_never_leaks_the_key(monkeypatch, tmp_path, key_file, capsys) -> None:
    hourly = {"data": [{"start_time": 86400 * 5, "results": [{"batch": False, "input_tokens": 9, "output_tokens": 1}]}], "has_more": False, "next_page": None}
    page1 = {"data": [{"start_time": 0, "results": []}], "has_more": True, "next_page": "p2"}
    code, api, manifest = _capture(monkeypatch, tmp_path, key_file, {"/v1/organization/costs": [page1, {"data": [], "has_more": False}],
                                                                    "/v1/organization/usage/embeddings": [429, {"data": [], "has_more": False}],
                                                                    "/v1/organization/usage/images": 500,
                                                                    "/v1/organization/usage/completions": [{"data": [], "has_more": False}, hourly, {"data": [], "has_more": False}]})
    assert code == 0 and {r.get_method() for r in api.requests} == {"GET"}
    assert all(r.full_url.startswith("https://api.openai.com/v1/organization/") and "project_ids=proj_app" in r.full_url for r in api.requests)
    assert not any(re.search(r"group_by=(user_id|api_key_id)", r.full_url) for r in api.requests)
    assert any("page=p2" in r.full_url for r in api.requests) and api.requests[-1].full_url.count("bucket_width=1m") == 1
    assert {c["file"]: c["status"] for c in manifest["captures"]}["usage-images.json"] == "failed"
    assert manifest["result"] == "complete" and not key_file.exists() and "admin_key_sha256" not in manifest
    out = capsys.readouterr()
    everything = out.out + out.err + "".join(p.read_text() for p in (tmp_path / "cap").iterdir())
    assert KEY not in everything and KEY not in "".join(r.full_url for r in api.requests)


def test_capture_stops_on_a_revoked_key_and_requires_a_project(monkeypatch, tmp_path, key_file) -> None:
    (tmp_path / "cap").mkdir()
    (tmp_path / "cap" / "usage-embeddings.json").write_text('[{"start_time": 0, "results": [{"model": "stale", "input_tokens": 123456}]}]')
    code, api, manifest = _capture(monkeypatch, tmp_path, key_file, {"/v1/organization/usage/completions": 401})
    assert code == 3 and manifest["captures"][-1] == {"endpoint": "/v1/organization/usage/completions", "file": "usage-completions.json", "status": "failed", "note": "401"}
    assert manifest["result"] == "key_invalid_mid_run" and not key_file.exists() and not (tmp_path / "cap" / "usage-embeddings.json").exists()
    assert USAGE.main(["summarize", "--capture-dir", str(tmp_path / "cap"), "--out", str(tmp_path / "u.json")]) == 7
    key_file.write_text(f"OPENAI_ADMIN_KEY={KEY}\n")
    with pytest.raises(SystemExit):
        USAGE.main(["capture", "--key-file", str(key_file), "--out-dir", str(tmp_path / "c2")])
    monkeypatch.setattr(USAGE, "opener", FakeAPI({"/v1/organization/costs": 401}))
    assert USAGE.main(["probe", "--key-file", str(key_file)]) == 2 and not key_file.exists()
    (tmp_path / "bad").write_text("OPENAI_ADMIN_KEY=sk-proj-x\n")
    with pytest.raises(SystemExit, match="KEY_FORMAT_BAD"):
        USAGE.read_key(tmp_path / "bad")



@pytest.mark.parametrize("command", ["probe", "capture"])
def test_a_network_error_still_deletes_the_key_file(monkeypatch, tmp_path, key_file, capsys, command) -> None:
    def network_down(request, timeout=None):
        raise urllib.error.URLError("temporary failure in name resolution")
    monkeypatch.setattr(USAGE, "opener", network_down)
    argv = [command, "--key-file", str(key_file)] + (["--out-dir", str(tmp_path / "cap"), "--project", "proj_app"] if command == "capture" else [])
    with pytest.raises(urllib.error.URLError):
        USAGE.main(argv)
    out = capsys.readouterr()
    assert not key_file.exists() and KEY not in out.out + out.err
    assert "however it ends (including a network error)" in READER and "The script stops on a network error or timeout" in READER

def test_capture_rows_match_the_documented_endpoint_table() -> None:
    table = [row for row in READER.splitlines() if re.match(r"\| [1-8] \|", row)]
    assert [re.search(r"`(/v1/[^`]+)`", r).group(1) for r in table] == [p for p, _, _ in USAGE.DAILY_ROWS + [USAGE.MINUTE_ROW]]
    assert [re.search(r"limit=(\d+)", r).group(1) for r in table] == [str(q["limit"]) for _, q, _ in USAGE.DAILY_ROWS + [USAGE.MINUTE_ROW]]
    assert [re.search(r"`([a-z-]+\.json)`\s*\|$", r).group(1) for r in table] == [f for _, _, f in USAGE.DAILY_ROWS + [USAGE.MINUTE_ROW]]
    assert "never open it with any tool" in READER and "Only `scripts/openai-usage.py` reads it" in READER
    for rule in ("each project's total spend for the window", "usage of projects you don't select", "in your OpenAI account",
                 "However this flow ends, including when the user skips at any step", "only a `result` of `complete` resumes"):
        assert rule in READER + CONTROLLER, rule


def test_summarize_keeps_actual_totals_and_the_higher_peak(tmp_path) -> None:
    out = tmp_path / "u.json"
    assert USAGE.main(["summarize", "--capture-dir", str(FIXTURES / "bma-openai-usage/capture"), "--out", str(out), "--label", "proj_app=production"]) == 0
    usage = json.loads(out.read_text())
    assert usage["summary"]["monthly_cost_usd"] == 30.75 == sum(r["monthly_cost_usd"] for r in usage["costs_by_line_item"])
    assert (usage["metadata"]["active_days"], usage["metadata"]["partial_window"]) == (12, True)
    assert usage["metadata"]["capture_warnings"] == ["usage-audio-transcriptions.json failed (HTTP 403 Missing scope)"]
    on_demand = next(r for r in usage["usage_by_model"] if r["batch"] is False)
    assert (on_demand["input_tokens"], on_demand["input_cached_tokens"], on_demand["peak"]["busiest_day"]) == (5000, 300, "2026-10-25")
    peak = on_demand["peak"]
    assert (peak["peak_input_tokens_per_minute"], peak["peak_output_tokens_per_minute"], peak["peak_source"]) == (40.0, 50, "minute")
    assert next(r for r in usage["usage_by_model"] if r["endpoint_type"] == "embeddings")["peak"]["peak_source"] == "day"
    assert usage["metadata"]["cost_status"] == "partial_window"


def _capture_copy(tmp_path, costs_status: str, costs_data: list | None = None) -> dict:
    cap = tmp_path / "cap"
    cap.mkdir()
    for f in (FIXTURES / "bma-openai-usage/capture").iterdir():
        (cap / f.name).write_text(f.read_text())
    manifest = json.loads((cap / "manifest.json").read_text())
    manifest["captures"][0]["status"] = costs_status
    (cap / "manifest.json").write_text(json.dumps(manifest))
    if costs_data is not None:
        (cap / "costs.json").write_text(json.dumps(costs_data))
    USAGE.main(["summarize", "--capture-dir", str(cap), "--out", str(tmp_path / "u.json")])
    return json.loads((tmp_path / "u.json").read_text())


@pytest.mark.parametrize(("status", "data", "cost", "cost_status"), [("failed", None, None, "cost_unavailable"), ("ok", [], 0, "complete")],
                         ids=["costs-failed", "costs-empty"])
def test_failed_costs_are_unavailable_but_empty_costs_are_zero(tmp_path, status, data, cost, cost_status) -> None:
    usage = _capture_copy(tmp_path, status, data)
    assert (usage["summary"]["monthly_cost_usd"], usage["metadata"]["cost_status"]) == (cost, cost_status)
    assert usage["usage_by_model"] and usage["costs_by_line_item"] == []
    measured = PREVIEW.preview(json.loads((FIXTURES / "bma-scan-openai-direct/ai-workload-profile.json").read_text()), [usage])["measured_usage"]
    assert (measured["monthly_cost_usd"], measured["cost_status"]) == (cost, cost_status)
    assert (measured["sources"][0]["monthly_cost_usd"], measured["sources"][0]["cost_status"]) == (cost, cost_status)


def _usage(tmp_path) -> Path:
    out = tmp_path / "u.json"
    USAGE.main(["summarize", "--capture-dir", str(FIXTURES / "bma-openai-usage/capture"), "--out", str(out)])
    return out


def _not_observed(p: dict) -> dict:
    p["ai_sources"][0].update(model_evidence="not_observed", models=[], model_observations=[])
    p.pop("workloads")
    return p


@pytest.mark.parametrize(("fixture", "code", "mutate"), [("bma-scan-openai-direct", 0, None), ("bma-scan-openai-direct", 0, _not_observed),
                                                         ("bma-scan-openrouter-google-pinned", 0, None), ("bma-scan-framework-gateway", 5, None)],
                         ids=["code-models", "not-observed", "new-source", "gateway-upstream"])
def test_merge_adds_usage_models_only_when_the_profile_stays_valid(tmp_path, fixture, code, mutate) -> None:
    profile = tmp_path / "p.json"
    data = json.loads((FIXTURES / fixture / "ai-workload-profile.json").read_text())
    profile.write_text(json.dumps(mutate(data) if mutate else data))
    before = profile.read_text()
    assert USAGE.main(["merge", "--usage", str(_usage(tmp_path)), "--profile", str(profile)]) == code
    if code:
        assert profile.read_text() == before
        return
    merged = json.loads(profile.read_text())
    openai = next(s for s in merged["ai_sources"] if s["source_service"] == "openai_api")
    assert {"gpt-4o-2024-08-06", "text-embedding-3-small"} <= set(openai["models"]) and openai["model_evidence"] == "observed"
    assert all(e["provenance"] == "code" for o in openai["model_observations"] if o["normalized_model"] == "gpt-4o" for e in o["evidence"])
    assert PREVIEW.validator.validate_profile(merged)["ok"] is True



def test_merge_keeps_the_verbatim_model_string(tmp_path) -> None:
    ft = "ft:gpt-4o-mini-2024-07-18:Acme:Support:AbC123"
    usage = json.loads(_usage(tmp_path).read_text())
    template = usage["usage_by_model"][0]
    usage["usage_by_model"] += [{**template, "model": ft}, {**template, "model": ft.lower()}, {**template, "model": "GPT-4o"}]
    (tmp_path / "u.json").write_text(json.dumps(usage))
    profile = tmp_path / "p.json"
    profile.write_text((FIXTURES / "bma-scan-openai-direct/ai-workload-profile.json").read_text())
    assert USAGE.main(["merge", "--usage", str(tmp_path / "u.json"), "--profile", str(profile)]) == 0
    merged = json.loads(profile.read_text())
    openai = next(s for s in merged["ai_sources"] if s["source_service"] == "openai_api")
    raws = {o["normalized_model"]: o["raw_model"] for o in openai["model_observations"]}
    assert raws[ft.lower()] == ft and raws["gpt-4o"] == "gpt-4o"
    assert sum(o["normalized_model"] == ft.lower() for o in openai["model_observations"]) == 1
    summary = next(s for s in PREVIEW.validator.validate_profile(merged)["ai_sources"] if s["source_service"] == "openai_api")
    assert {"model": ft.lower(), "raw_model": ft, "high_confidence": True} in summary["models"]

def _caps(**on) -> dict:
    keys = ("text_generation", "streaming", "function_calling", "vision", "embeddings", "batch_processing", "speech_to_text", "text_to_speech", "image_generation")
    return {k: k in on or k == "text_generation" for k in keys}


@pytest.mark.parametrize(("mutate", "signal", "eligible"), [
    (lambda p: None, "likely_simple", True),
    (lambda p: p["integration"].update(capabilities_summary=_caps(streaming=1, vision=1)), "standard", False),
    (lambda p: p.pop("integration"), "standard", False),
    (lambda p: p["ai_sources"][0]["model_observations"][0]["evidence"][0].update(confidence="medium"), "likely_simple", False),
    (lambda p: p["gateways"].append({"product": "litellm", "type": "llm_router", "upstream_evidence": "unresolved", "upstreams": []}), "complex", False),
    (lambda p: p["ai_sources"][0].update(model_evidence="not_observed", models=[], model_observations=[]) or p.pop("workloads"), "standard", False),
], ids=["simple", "capabilities", "no-integration", "medium-confidence", "gateway", "not-observed"])
def test_preview_classification_and_fast_path(mutate, signal, eligible) -> None:
    profile = copy.deepcopy(json.loads((FIXTURES / "bma-scan-vertex-env-flash-lite/ai-workload-profile.json").read_text()))
    mutate(profile)
    result = PREVIEW.preview(profile)
    assert (result["ai_complexity_signal"], result["eligible_for_clarify_fast_path"]) == (signal, eligible)
    assert eligible or result["fast_path_blocked_by"]
    assert "bedrock" not in json.dumps(result["ai_summary"]).lower()


@pytest.mark.parametrize(("fixture", "signal"), [("bma-scan-agents-openai", "complex"), ("bma-scan-workloads-mixed", "complex"), ("bma-scan-openai-direct", "standard")])
def test_preview_on_scan_fixtures(fixture, signal) -> None:
    assert PREVIEW.preview(json.loads((FIXTURES / fixture / "ai-workload-profile.json").read_text()))["ai_complexity_signal"] == signal


def test_discover_and_clarify_wiring() -> None:
    assert CONTROLLER.index("## Step 2c: Usage APIs") < CONTROLLER.index("## Step 2d: Preview") < CONTROLLER.index("## Step 3")
    assert "Step 2d wrote `migration-preview.json`" in CONTROLLER and "The preview names no Bedrock models or prices" in CONTROLLER
    fast = CLARIFY[CLARIFY.index("## Step 1.5"):CLARIFY.index("## Step 1.75")]
    for rule in ("Always: Q1.5, Q2, Q3, Q4, Q7, and Q11", "Q7 is never skipped", "does not report `models_extractable: true`",
                 "Q10 when the Q2 answer is 4 (Specialized capability)",
                 "Q1 when `ai_framework_detected` is `null`, and Q6 when `ai_vision_detected` is `null`"):
        assert rule in fast, rule
    assert "does not produce yet" not in CLARIFY and "except `migration-preview.json`, for the fast-path check in Step 1.5" in CLARIFY
    skill = (BMA / "SKILL.md").read_text(encoding="utf-8")
    step0 = skill[skill.index("## Step 0"):skill.index("## Step 1:")]
    for rule in ("phases.discover` set to `\"in_progress\"`", "all_usage_failed` starts at Step 1 intake",
                 "Do not create a second run directory", "Never write into a run directory another skill created"):
        assert rule in step0, rule
    assert "Treat as skipped: exit with no usage profile" not in READER
    assert "start at Step 1 intake, then Step 2. The next capture replaces these files." in READER
    bedrock = (BMA.parent / "llm-to-bedrock/SKILL.md").read_text(encoding="utf-8")
    assert "bedrock-migration-assessment's OpenAI usage profile" in bedrock
    assert "subtract it from the baseline row's `input_tokens` and copy it to" in bedrock
    assert "`cache_write_unsplit`" in bedrock
    assert "\"Not available (the cost request failed)\"" in CONTROLLER


def test_resume_rules_apply_only_to_this_skills_runs() -> None:
    skill = (BMA / "SKILL.md").read_text(encoding="utf-8")
    step0 = skill[skill.index("## Step 0"):skill.index("## Step 1:")]
    gate = "Rules 1 to 4 apply only to a run this skill created: the user names an existing `$MIGRATION_DIR` whose `.phase-status.json` has a `migration_id` starting with `bma-` and no `owning_skill`."
    assert step0.index(gate) < step0.index("1. If that file") < step0.index("5. Otherwise start a new run")
    assert '"migration_id": "bma-MMDD-HHMM"' in CONTROLLER and "Do not write `owning_skill`" in CONTROLLER
    others = [p for p in (PLUGIN_ROOT / "skills").rglob("*.md") if BMA not in p.parents]
    ids = {m for p in others for m in re.findall(r'"migration_id": "([^"]+)"', p.read_text(encoding="utf-8"))}
    assert ids and not any(i.startswith("bma-") for i in ids), ids
    gcp = (PLUGIN_ROOT / "skills/gcp-to-aws/references/phases/discover/discover.md").read_text(encoding="utf-8")
    assert '"owning_skill": "GCP_TO_AWS"' in gcp and '"discover": "in_progress"' in gcp
