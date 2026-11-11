"""bedrock-migration-assessment OpenRouter usage reader and its BYOK overlap in the preview."""
from __future__ import annotations

import importlib.util
import io
import itertools
import json
import re
import sys
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BMA = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
FIXTURES = PLUGIN_ROOT / "fixtures"
CAPTURE = FIXTURES / "bma-openrouter-usage" / "capture"
READER = (BMA / "references/phases/discover/discover-openrouter-api.md").read_text(encoding="utf-8")
CONTROLLER = (BMA / "references/phases/discover/discover.md").read_text(encoding="utf-8")
CLARIFY = (BMA / "references/phases/clarify/clarify-ai-only.md").read_text(encoding="utf-8")
KEY = "fake-openrouter-management-key"


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, BMA / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


USAGE = _module("bma_openrouter_usage", "openrouter-usage.py")
PREVIEW = _module("bma_migration_preview_for_openrouter_tests", "migration-preview.py")
FIX = {p.name: json.loads(p.read_text()) for p in CAPTURE.glob("*.json")}


class FakeAPI:
    """Stands in for urlopen: records every request and answers from a script of responses per (method, path, body file)."""

    def __init__(self, answers: dict):
        self.answers, self.requests = answers, []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        path = request.full_url.removeprefix(USAGE.BASE_URL).split("?")[0]
        key = path
        if request.data:
            metrics = json.loads(request.data)["metrics"]
            key = next((f for f, m, _ in USAGE.ANALYTICS_ROWS if set(metrics) <= set(m) and (("granularity" in json.loads(request.data)) == (f == "analytics-hourly.json"))), path)
        answer = self.answers.get(key, self.answers.get(path, {"data": []}))
        answer = answer.pop(0) if isinstance(answer, list) else answer
        if isinstance(answer, int):
            body = json.dumps({"error": {"message": f"bad key {KEY}"}}).encode()
            raise urllib.error.HTTPError(request.full_url, answer, "err", {}, io.BytesIO(body))
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(json.dumps(answer).encode())


def _full_answers() -> dict:
    return {"/credits": FIX["credits.json"], "/activity": FIX["activity.json"], "/key": {"data": {"label": "sk-or-v1-abc...123", "name": "migration", "limit": None}}, "/analytics/meta": FIX["analytics-meta.json"],
            "analytics.json": FIX["analytics.json"], "analytics-volume.json": FIX["analytics-volume.json"], "analytics-hourly.json": FIX["analytics-hourly.json"],
            "/workspaces": {"data": [{"id": "ws-1", "name": "Production", "slug": "prod"}]}}


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    path = tmp_path / ".openrouter-key-env"
    path.write_text(f"OPENROUTER_PROVISIONING_KEY={KEY}\n")
    return path


def _capture(monkeypatch, tmp_path, key_file, answers, *extra):
    api = FakeAPI(answers)
    monkeypatch.setattr(USAGE, "opener", api)
    monkeypatch.setattr(USAGE, "sleep", lambda s: None)
    code = USAGE.main(["capture", "--key-file", str(key_file), "--out-dir", str(tmp_path / "cap"), *extra])
    return code, api, json.loads((tmp_path / "cap" / "manifest.json").read_text())


def test_capture_is_read_only_scoped_and_never_leaks_the_key(monkeypatch, tmp_path, key_file, capsys) -> None:
    answers = _full_answers()
    answers["/activity"] = [429, FIX["activity.json"]]
    code, api, manifest = _capture(monkeypatch, tmp_path, key_file, answers, "--workspace-id", "ws-1", "--workspace-name", "Production")
    assert code == 0 and manifest["result"] == "complete" and not key_file.exists()
    methods = {(r.get_method(), r.full_url.removeprefix(USAGE.BASE_URL).split("?")[0]) for r in api.requests}
    assert {m for m, _ in methods} == {"GET", "POST"} and {p for m, p in methods if m == "POST"} == {"/analytics/query"}
    assert all(r.get_header("Authorization") == f"Bearer {KEY}" for r in api.requests)
    activity = [r for r in api.requests if "/activity" in r.full_url]
    assert activity and all(dict(urllib.parse.parse_qsl(r.full_url.partition("?")[2])) == {"workspace_id": "ws-1"} for r in activity)
    for r in (r for r in api.requests if r.data):
        body = json.loads(r.data)
        assert body["dimensions"] == ["model"] and body["filters"] == [{"field": "workspace", "operator": "eq", "value": "ws-1"}]
        assert body["time_range"]["start"].endswith("T00:00:00Z") and body["time_range"]["end"] == manifest["window_end_utc"]
    assert manifest["workspace_scope"] == {"workspace_id": "ws-1", "workspace_name": "Production"}
    assert json.loads((tmp_path / "cap" / "key.json").read_text()) == {"data": {"limit": None}}
    out = capsys.readouterr()
    everything = out.out + out.err + "".join(p.read_text() for p in (tmp_path / "cap").iterdir())
    assert KEY not in everything and KEY not in "".join(r.full_url for r in api.requests)


def test_analytics_asks_only_for_offered_metrics_and_retries_truncation(monkeypatch, tmp_path, key_file) -> None:
    answers = _full_answers()
    answers["/analytics/meta"] = {"data": {"metrics": [{"name": "request_count"}, {"name": "tokens_prompt"}]}}
    truncated = {"data": {"data": [], "metadata": {"truncated": True}}}
    answers["analytics-volume.json"] = [truncated, truncated]
    code, api, manifest = _capture(monkeypatch, tmp_path, key_file, answers)
    rows = {c["file"]: c for c in manifest["captures"]}
    assert code == 0 and rows["analytics.json"]["status"] == "skipped" and rows["analytics.json"]["note"] == "none of these metrics is offered"
    assert rows["analytics-volume.json"]["metrics"] == ["tokens_prompt", "request_count"] and rows["analytics-volume.json"]["note"] == "truncated"
    limits = [json.loads(r.data)["limit"] for r in api.requests if r.data and "granularity" not in json.loads(r.data)]
    assert limits == [1000, 5000]


@pytest.mark.parametrize(("answers", "code", "result"), [
    ({"/activity": 401}, 3, "key_invalid_mid_run"),
    ({"/activity": 500}, 4, "all_usage_failed"),
    ({"analytics.json": 403, "/key": 404}, 0, "complete"),
], ids=["revoked-on-activity", "activity-failed", "analytics-403-continues"])
def test_capture_exits(monkeypatch, tmp_path, key_file, answers, code, result) -> None:
    merged = {**_full_answers(), **answers}
    got, _, manifest = _capture(monkeypatch, tmp_path, key_file, merged)
    assert (got, manifest["result"]) == (code, result) and not key_file.exists()


def test_a_network_error_still_deletes_the_key_file(monkeypatch, tmp_path, key_file, capsys) -> None:
    for command in ("probe", "capture"):
        key_file.write_text(f"OPENROUTER_PROVISIONING_KEY={KEY}\n")
        monkeypatch.setattr(USAGE, "opener", FakeAPI({"/credits": urllib.error.URLError("dns failure")}))
        argv = [command, "--key-file", str(key_file)] + (["--out-dir", str(tmp_path / "cap")] if command == "capture" else [])
        with pytest.raises(urllib.error.URLError):
            USAGE.main(argv)
        assert not key_file.exists()
    out = capsys.readouterr()
    assert KEY not in out.out + out.err


def test_probe_lists_credits_and_workspaces_and_writes_nothing(monkeypatch, tmp_path, key_file, capsys) -> None:
    monkeypatch.setattr(USAGE, "opener", FakeAPI(_full_answers()))
    before = sorted(tmp_path.iterdir())
    assert USAGE.main(["probe", "--key-file", str(key_file)]) == 0 and key_file.exists() and sorted(tmp_path.iterdir()) == before
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines == [{"total_credits": 100.0, "total_usage": 40.5}, {"workspace_id": "ws-1", "name": "Production", "slug": "prod"}]
    monkeypatch.setattr(USAGE, "opener", FakeAPI({"/credits": 403}))
    assert USAGE.main(["probe", "--key-file", str(key_file)]) == 2 and not key_file.exists()


@pytest.mark.parametrize(("path", "params", "body"), [
    ("/keys", None, None), ("/generation", None, None), ("/activity", {"api_key_hash": "x"}, None), ("/activity", {"group_by": "workspace"}, None),
    ("/activity", None, {"metrics": ["x"]}), ("/analytics/query", None, {"metrics": ["x"], "dimensions": ["api_key_id"]}),
    ("/analytics/query", None, {"metrics": ["x"], "dimensions": ["model"], "granularity": "minute"}),
    ("/analytics/query", None, {"metrics": ["x"], "dimensions": ["model"], "filters": [{"field": "user", "operator": "eq", "value": "u"}]}),
], ids=["keys", "generation", "api-key-filter", "group-by", "post-to-get-path", "per-key-dimension", "minute", "user-filter"])
def test_requests_outside_the_allowlist_are_refused(path, params, body) -> None:
    with pytest.raises(ValueError):
        USAGE.call(KEY, path, params, body)


def _summarize(tmp_path, capture=CAPTURE) -> dict:
    out = tmp_path / "u.json"
    assert USAGE.main(["summarize", "--capture-dir", str(capture), "--out", str(out)]) == 0
    return json.loads(out.read_text())


def test_summarize_keeps_credits_byok_and_provenance_apart(tmp_path) -> None:
    usage = _summarize(tmp_path)
    assert usage["summary"] == {"monthly_cost_usd": 4.65, "byok_inference_cost_usd": 2.0, "currency": "USD", "models_seen": 3, "total_requests": 44,
                                "total_tokens": 8210}
    md = usage["metadata"]
    assert (md["active_days"], md["partial_window"], md["cost_provenance"]) == (11, True, "mixed")
    assert md["credits_lifetime"] == {"total_credits": 100.0, "total_usage": 40.5}
    assert any("anthropic/claude-sonnet-5: cost_provenance uncertain" in w for w in md["capture_warnings"])
    assert "$2.0 of BYOK inference was billed by your own provider keys and is not in monthly_cost_usd" in md["capture_warnings"]
    rows = {r["model"]: r for r in usage["usage_by_model"]}
    assert {m: r["cost_provenance"] for m, r in rows.items()} == {"openai/gpt-4.1": "no_byok", "anthropic/claude-sonnet-5": "uncertain",
                                                                  "google/gemini-2.5-flash": "no_byok"}
    claude = rows["anthropic/claude-sonnet-5"]
    assert (claude["monthly_cost_usd"], claude["byok_inference_cost_usd"], claude["byok_fees_usd"], claude["byok_request_count"]) == (0.15, 2.0, 0.1, 5)
    gpt = rows["openai/gpt-4.1"]
    assert (gpt["cached_tokens"], gpt["prompt_tokens"], gpt["requests"], gpt["analytics_request_count"], gpt["web_search_cost_usd"]) == (400, 4000, 30, 30, 0.2)
    assert (gpt["peak"]["peak_input_tokens_per_minute"], gpt["peak"]["peak_source"], gpt["peak"]["busiest_day"]) == (30.0, "hour", "2026-10-25")


@pytest.mark.parametrize("labels", list(itertools.product(["byok_passthrough", "mixed", "no_byok", "unknown"], repeat=2)))
def test_permaslug_roll_up_has_one_answer_for_every_pair(labels) -> None:
    found = set(labels)
    expected = ("unknown" if found == {"unknown"} else "uncertain" if "unknown" in found else
                "mixed" if "mixed" in found or {"byok_passthrough", "no_byok"} <= found else labels[0])
    assert USAGE._roll_up(list(labels)) == expected


def _copy(tmp_path, change) -> Path:
    cap = tmp_path / "cap"
    cap.mkdir()
    for name, data in FIX.items():
        (cap / name).write_text(json.dumps(data))
    change(cap)
    return cap


def _edit(path: Path, change) -> None:
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def test_failed_analytics_makes_every_model_unknown_and_drops_the_hourly_peak(tmp_path) -> None:
    def failed(cap):
        _edit(cap / "manifest.json", lambda m: [c.update(status="failed", note="HTTP 403") for c in m["captures"] if c["endpoint"] == "/analytics/query"])
    usage = _summarize(tmp_path, _copy(tmp_path, failed))
    assert {r["cost_provenance"] for r in usage["usage_by_model"]} == {"unknown"} and usage["metadata"]["cost_provenance"] == "unknown"
    assert "analytics.json failed — cost_provenance is unknown for all models" in usage["metadata"]["capture_warnings"]
    assert all(r["peak"]["peak_source"] == "day" and r["peak"]["peak_input_tokens_per_minute"] is None for r in usage["usage_by_model"])
    assert all("byok_fees_usd" not in r for r in usage["usage_by_model"])


def test_empty_activity_with_lifetime_spend_is_not_called_zero(tmp_path) -> None:
    usage = _summarize(tmp_path, _copy(tmp_path, lambda cap: (cap / "activity.json").write_text('{"data": []}')))
    assert usage["summary"]["monthly_cost_usd"] == 0 and usage["metadata"]["partial_window"] is True
    assert any(w.startswith("activity empty but credits.total_usage is $40.5 lifetime") for w in usage["metadata"]["capture_warnings"])


def _usage_file(tmp_path, keep) -> Path:
    usage = _summarize(tmp_path)
    usage["usage_by_model"] = [r for r in usage["usage_by_model"] if keep(r)]
    path = tmp_path / "keep.json"
    path.write_text(json.dumps(usage))
    return path


def test_merge_adds_upstream_models_to_source_and_gateway(tmp_path) -> None:
    usage = _usage_file(tmp_path, lambda r: not r["model"].startswith("openai/"))
    profile = tmp_path / "p.json"
    profile.write_text((FIXTURES / "bma-scan-openrouter-google-pinned/ai-workload-profile.json").read_text())
    assert USAGE.main(["merge", "--usage", str(usage), "--profile", str(profile)]) == 0
    merged = json.loads(profile.read_text())
    sources = {(s["provider"], s["source_service"]): s for s in merged["ai_sources"]}
    claude = next(o for o in sources[("anthropic", "anthropic_api")]["model_observations"] if o["normalized_model"] == "claude-sonnet-5")
    assert claude["raw_model"] == "anthropic/claude-sonnet-5" and claude["evidence"][0]["provenance"] == "usage_api"
    upstream = next(u for u in merged["gateways"][0]["upstreams"] if u["provider"] == "anthropic")
    assert upstream["model_families"][0]["models"] == ["claude-3.5-sonnet", "claude-sonnet-5"]
    assert PREVIEW.validator.validate_profile(merged)["ok"] is True


@pytest.mark.parametrize(("fixture", "keep", "change", "message"), [
    ("bma-scan-openrouter-gemini", lambda r: True, None, "GATEWAY_NOT_OBSERVED"),
    ("bma-scan-openrouter-google-pinned", lambda r: True, None, "UPSTREAM_NOT_IN_PROFILE"),
    ("bma-scan-openrouter-google-pinned", lambda r: r["model"].startswith("google/"), lambda r: r.update(provider_name=None), "SOURCE_NOT_ESTABLISHED"),
    ("bma-scan-openrouter-google-pinned", lambda r: r["model"].startswith("anthropic/"), lambda r: r.update(model="mistralai/mistral-large"), "SOURCE_NOT_ESTABLISHED"),
], ids=["gateway-unresolved", "openai-not-an-upstream", "google-served-by-two-services", "other-prefix"])
def test_merge_leaves_the_profile_unchanged_when_the_source_is_not_established(tmp_path, capsys, fixture, keep, change, message) -> None:
    usage = _usage_file(tmp_path, keep)
    if change:
        _edit(usage, lambda u: [change(r) for r in u["usage_by_model"]])
    capsys.readouterr()
    profile = tmp_path / "p.json"
    profile.write_text((FIXTURES / fixture / "ai-workload-profile.json").read_text())
    before = profile.read_text()
    assert USAGE.main(["merge", "--usage", str(usage), "--profile", str(profile)]) == 5 and profile.read_text() == before
    assert capsys.readouterr().out.startswith(message)


def _direct(model: str, tokens: int, cost: float) -> dict:
    return {"metadata": {"source": "anthropic_usage_api", "window_days": 30, "active_days": 30, "partial_window": False, "cost_status": "complete"},
            "summary": {"monthly_cost_usd": cost}, "usage_by_model": [{"model": model, "input_tokens": tokens, "output_tokens": 0}]}


def test_preview_leaves_out_openrouter_rows_a_direct_profile_also_counts(tmp_path) -> None:
    openrouter = _summarize(tmp_path)
    profile = json.loads((FIXTURES / "bma-scan-workloads-mixed/ai-workload-profile.json").read_text())
    measured = PREVIEW.preview(profile, [_direct("claude-sonnet-5", 1000, 10.0), openrouter])["measured_usage"]
    assert measured["overlap_excluded"] == [{"source": "openrouter_usage_api", "model": "anthropic/claude-sonnet-5", "cost_provenance": "uncertain"}]
    assert measured["total_tokens"] == 1000 + 4800 + 900 and measured["monthly_cost_usd"] == round(10.0 + 4.0 + 0.5, 2)
    assert measured["sources"][1]["byok_inference_cost_usd"] == 2.0
    alone = PREVIEW.preview(profile, [openrouter])["measured_usage"]
    assert alone["overlap_excluded"] == [] and alone["monthly_cost_usd"] == round(4.65 + 2.0, 2) and alone["total_tokens"] == 8210
    for row in openrouter["usage_by_model"]:
        row["cost_provenance"] = "no_byok"
    kept = PREVIEW.preview(profile, [_direct("claude-sonnet-5", 1000, 10.0), openrouter])["measured_usage"]
    assert kept["overlap_excluded"] == [] and kept["total_tokens"] == 1000 + 8210


def test_capture_rows_match_the_documented_endpoint_table() -> None:
    table = [row for row in READER.splitlines() if re.match(r"\| [1-7] \|", row)]
    endpoints = [re.search(r"`(GET|POST) (/[^`]+)`", r).groups() for r in table]
    assert endpoints == [("GET", "/credits"), ("GET", "/activity"), ("GET", "/key"), ("GET", "/analytics/meta")] + [("POST", "/analytics/query")] * 3
    assert [re.search(r"`([a-z-]+\.json)`\s*\|$", r).group(1) for r in table] == USAGE.CAPTURE_FILES
    for (name, metrics, _), row in zip(USAGE.ANALYTICS_ROWS, table[4:]):
        assert all(f"`{m}`" in row for m in metrics), name


def test_reader_controller_and_clarify_wiring() -> None:
    for rule in ("never open it with any tool", "Only `scripts/openrouter-usage.py` reads it", "except one read-only `POST` to `/analytics/query`",
                 "keys have no read-only scope", "however it ends (including a network error)", "never by grouping",
                 "OpenRouter is a gateway, never a source", "Never split a mixed model's tokens or dollars by its request share",
                 "is account-wide even when a workspace was picked", "The script stops on a network error or timeout"):
        assert rule in READER, rule
    for rule in ("| an `openrouter` gateway", "`references/phases/discover/discover-openrouter-api.md`", "[--usage $MIGRATION_DIR/openrouter-usage-profile.json]",
                 "whose source or gateway the profile has"):
        assert rule in CONTROLLER, rule
    q3 = CLARIFY[CLARIFY.index("## Q3 "):CLARIFY.index("## Q4 ")]
    q7 = CLARIFY[CLARIFY.index("## Q7 "):CLARIFY.index("## Q8 ")]
    assert "`overlap_excluded`" in q3 and "`byok_inference_cost_usd`" in q3 and "`overlap_excluded`" in q7
