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


def _file_of(body: dict) -> str:
    return "analytics-hourly.json" if body.get("granularity") else "analytics.json" if set(body["metrics"]) <= set(USAGE.CLASSIFY_METRICS) else "analytics-volume.json"


def _slug_of(body: dict) -> str:
    return next(f["value"] for f in body["filters"] if f["field"] == "model")


class FakeAPI:
    """Stands in for urlopen: records every request and answers from a script of responses per path, or per (analytics file, permaslug)."""

    def __init__(self, answers: dict):
        self.answers, self.requests = answers, []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        path = request.full_url.removeprefix(USAGE.BASE_URL).split("?")[0]
        answer = self.answers.get(path, {"data": []})
        if request.data:
            body = json.loads(request.data)
            answer = self.answers.get((_file_of(body), _slug_of(body)), self.answers.get(_file_of(body), answer))
        answer = answer.pop(0) if isinstance(answer, list) else answer
        if isinstance(answer, int):
            body = json.dumps({"error": {"message": f"bad key {KEY}"}}).encode()
            raise urllib.error.HTTPError(request.full_url, answer, "err", {}, io.BytesIO(body))
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(json.dumps(answer).encode())


def _full_answers() -> dict:
    answers = {"/credits": FIX["credits.json"], "/activity": FIX["activity.json"], "/analytics/meta": FIX["analytics-meta.json"],
               "/key": {"data": {"label": "sk-or-v1-abc...123", "name": "migration", "limit": None}},
               "/workspaces": {"data": [{"id": "ws-1", "name": "Production", "slug": "prod"}]}}
    for name in ("analytics.json", "analytics-volume.json", "analytics-hourly.json"):
        for q in FIX[name]["data"]:
            answers[(name, q["model_permaslug"])] = q["response"]
    return answers


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
    slugs = sorted({r["model_permaslug"] for r in FIX["activity.json"]["data"]})
    bodies = [json.loads(r.data) for r in api.requests if r.data]
    assert {(_file_of(b), _slug_of(b)) for b in bodies} == {(f, slug) for f, _, _ in USAGE.ANALYTICS_ROWS for slug in slugs}
    for body in bodies:
        assert "dimensions" not in body and {"field": "workspace", "operator": "eq", "value": "ws-1"} in body["filters"]
        assert body["time_range"]["start"].endswith("T00:00:00Z") and body["time_range"]["end"] == manifest["window_end_utc"]
    stored = json.loads((tmp_path / "cap" / "analytics.json").read_text())
    assert [q["model_permaslug"] for q in stored["data"]] == slugs
    assert manifest["workspace_scope"] == {"workspace_id": "ws-1", "workspace_name": "Production"}
    assert json.loads((tmp_path / "cap" / "key.json").read_text()) == {"data": {"limit": None}}
    out = capsys.readouterr()
    everything = out.out + out.err + "".join(p.read_text() for p in (tmp_path / "cap").iterdir())
    assert KEY not in everything and KEY not in "".join(r.full_url for r in api.requests)


def test_analytics_asks_only_for_offered_metrics_and_retries_truncation(monkeypatch, tmp_path, key_file) -> None:
    answers = _full_answers()
    answers["/analytics/meta"] = {"data": {"metrics": [{"name": "request_count"}, {"name": "tokens_prompt"}]}}
    truncated = {"data": {"data": [], "metadata": {"truncated": True}}}
    slug = "openai/gpt-4.1-2025-04-14"
    answers[("analytics-volume.json", slug)] = [truncated, truncated]
    code, api, manifest = _capture(monkeypatch, tmp_path, key_file, answers)
    rows = {c["file"]: c for c in manifest["captures"]}
    assert code == 0 and rows["analytics.json"]["status"] == "skipped" and rows["analytics.json"]["note"] == "none of these metrics is offered"
    assert rows["analytics-volume.json"]["metrics"] == ["tokens_prompt", "request_count"] and slug in rows["analytics-volume.json"]["note"]
    limits = [json.loads(r.data)["limit"] for r in api.requests if r.data and _slug_of(json.loads(r.data)) == slug and "granularity" not in json.loads(r.data)]
    assert limits == [1000, 5000]


@pytest.mark.parametrize(("answers", "code", "result"), [
    ({"/activity": 401}, 3, "key_invalid_mid_run"),
    ({"/activity": 500}, 4, "all_usage_failed"),
    ({("analytics.json", "openai/gpt-4.1-2025-04-14"): 403, "/key": 404}, 0, "complete"),
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
    ("/analytics/query", None, {"metrics": ["x"], "dimensions": ["model"]}), ("/analytics/query", None, {"metrics": ["x"], "granularity": "minute"}),
    ("/analytics/query", None, {"metrics": ["x"], "filters": [{"field": "user", "operator": "eq", "value": "u"}]}),
    ("/analytics/query", None, {"metrics": ["x"], "filters": [{"field": "model", "operator": "in", "value": ["a", "b"]}]}),
], ids=["keys", "generation", "api-key-filter", "group-by", "post-to-get-path", "per-key-dimension", "grouped-by-model", "minute", "user-filter", "set-filter"])
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
    assert (claude["monthly_cost_usd"], claude["byok_inference_cost_usd"]) == (0.15, 2.0)
    assert "byok_fees_usd" not in claude and claude["peak"]["peak_source"] == "day", "one permaslug's analytics reply was truncated"
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
        _edit(cap / "manifest.json", lambda m: [c.update(status="failed", note="HTTP 403", metrics=None) for c in m["captures"] if c["endpoint"] == "/analytics/query"])
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
    ("bma-scan-openrouter-google-pinned", lambda r: r["model"].startswith("openai/"), None, "SOURCE_NOT_ESTABLISHED"),
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
    assert measured["overlap_excluded"] == [{"source": "openrouter_usage_api", "model": "anthropic/claude-sonnet-5", "cost_provenance": "uncertain",
                                             "router_fee_kept_usd": 0.0, "charge_dropped_usd": 0.15, "note": "its $0.15 OpenRouter charge is not in the total"}]
    assert measured["total_tokens"] == 1000 + 4800 + 900 and measured["monthly_cost_usd"] == round(10.0 + 4.0 + 0.5, 2) and measured["spend_excludes_usd"] == 0.15
    assert (measured["sources"][1]["byok_inference_cost_usd"], measured["sources"][1]["byok_inference_included_usd"]) == (2.0, 0.0)
    assert any(w.startswith("anthropic/claude-sonnet-5 left out so its BYOK traffic") for w in measured["capture_warnings"])
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
    assert "`overlap_excluded`" in q3 and "`byok_inference_included_usd`" in q3 and "spend_excludes_usd" in q3 and "`overlap_excluded`" in q7


def _row(model, provenance, credits, byok, fee=None):
    row = {"model": model, "prompt_tokens": 100, "completion_tokens": 10, "monthly_cost_usd": credits, "byok_inference_cost_usd": byok, "cost_provenance": provenance}
    if fee is not None:
        row["byok_fees_usd"] = fee
    return row


def _openrouter(*rows) -> dict:
    return {"metadata": {"source": "openrouter_usage_api", "window_days": 30, "active_days": 30, "partial_window": False, "cost_status": "complete"},
            "summary": {"monthly_cost_usd": sum(r["monthly_cost_usd"] for r in rows), "byok_inference_cost_usd": sum(r["byok_inference_cost_usd"] for r in rows)},
            "usage_by_model": list(rows)}


@pytest.mark.parametrize(("row", "total", "dropped", "note"), [
    (_row("anthropic/claude-sonnet-5", "byok_passthrough", 5.0, 90.0, fee=5.0), 105.0, 0.0, ""),
    (_row("anthropic/claude-sonnet-5", "byok_passthrough", 5.0, 90.0), 100.0, 5.0, "its $5.0 OpenRouter charge is not in the total"),
    (_row("anthropic/claude-sonnet-5", "mixed", 20.0, 90.0, fee=1.0), 100.0, 20.0, "its independent OpenRouter usage is dropped too"),
    (_row("anthropic/claude-sonnet-5", "no_byok", 20.0, 0.0), 120.0, 0.0, None),
], ids=["fee-kept", "fee-unmeasured", "mixed", "no-byok-kept"])
def test_overlap_keeps_measured_router_fees_and_discloses_dropped_charges(row, total, dropped, note) -> None:
    profile = json.loads((FIXTURES / "bma-scan-workloads-mixed/ai-workload-profile.json").read_text())
    measured = PREVIEW.preview(profile, [_direct("claude-sonnet-5", 1000, 100.0), _openrouter(row)])["measured_usage"]
    assert (measured["monthly_cost_usd"], measured["spend_excludes_usd"]) == (total, dropped)
    if note is None:
        assert measured["overlap_excluded"] == [] and measured["total_tokens"] == 1110
    else:
        assert measured["overlap_excluded"][0]["note"] == note and measured["total_tokens"] == 1000


def test_unoffered_metrics_stay_unknown_through_capture_summarize_and_preview(monkeypatch, tmp_path, key_file) -> None:
    answers = _full_answers()
    offered = [m for m in json.loads(json.dumps(FIX["analytics-meta.json"]))["data"]["metrics"] if m["name"] not in ("byok_usage", "byok_fees")]
    answers["/analytics/meta"] = {"data": {"metrics": offered}}
    for slug in {r["model_permaslug"] for r in FIX["activity.json"]["data"]}:
        answers[("analytics.json", slug)] = {"data": {"data": [{"openrouter_usage": 1.0}], "metadata": {"truncated": False}}}
        answers[("analytics-volume.json", slug)] = {"data": {"data": [{"request_count": 3, "tokens_prompt": 1}], "metadata": {"truncated": False}}}
    code, api, manifest = _capture(monkeypatch, tmp_path, key_file, answers)
    assert code == 0 and all("byok_usage" not in json.loads(r.data)["metrics"] for r in api.requests if r.data)
    usage = _summarize(tmp_path, tmp_path / "cap")
    assert {r["cost_provenance"] for r in usage["usage_by_model"]} == {"unknown"}
    assert "analytics.json without both byok_usage and openrouter_usage — cost_provenance is unknown for all models" in usage["metadata"]["capture_warnings"]
    gpt = next(r for r in usage["usage_by_model"] if r["model"] == "openai/gpt-4.1")
    assert gpt["byok_fees_usd"] is None and gpt["analytics_request_count"] == 3 and any("byok_fees_usd" in w and "null, not zero" in w for w in usage["metadata"]["capture_warnings"])
    profile = json.loads((FIXTURES / "bma-scan-workloads-mixed/ai-workload-profile.json").read_text())
    measured = PREVIEW.preview(profile, [_direct("claude-sonnet-5", 1000, 10.0), usage])["measured_usage"]
    assert [d["model"] for d in measured["overlap_excluded"]] == ["anthropic/claude-sonnet-5"]


def test_analytics_replies_join_by_the_queried_permaslug_not_the_display_label(tmp_path) -> None:
    def labeled(cap):
        for name in ("analytics.json", "analytics-volume.json", "analytics-hourly.json"):
            _edit(cap / name, lambda d: [r.update(model="OpenAI: GPT-4.1") for q in d["data"] for r in (q["response"]["data"]["data"] or [])])
    usage = _summarize(tmp_path, _copy(tmp_path, labeled))
    gpt = next(r for r in usage["usage_by_model"] if r["model"] == "openai/gpt-4.1")
    assert (gpt["cost_provenance"], gpt["analytics_request_count"], gpt["peak"]["peak_source"]) == ("no_byok", 30, "hour")


def _litellm_profile() -> dict:
    profile = json.loads((FIXTURES / "bma-scan-openrouter-google-pinned/ai-workload-profile.json").read_text())
    anthropic = next(u for u in profile["gateways"][0]["upstreams"] if u["provider"] == "anthropic")
    profile["gateways"].append({"product": "litellm", "type": "llm_router", "upstream_evidence": "observed", "upstreams": [json.loads(json.dumps(anthropic))]})
    return profile


def test_merge_refreshes_every_gateway_that_shares_the_source(tmp_path) -> None:
    profile_data = _litellm_profile()
    assert PREVIEW.validator.validate_profile(profile_data)["ok"] is True
    profile = tmp_path / "p.json"
    profile.write_text(json.dumps(profile_data))
    usage = _usage_file(tmp_path, lambda r: r["model"].startswith("anthropic/"))
    assert USAGE.main(["merge", "--usage", str(usage), "--profile", str(profile)]) == 0
    merged = json.loads(profile.read_text())
    for gateway in merged["gateways"]:
        upstream = next(u for u in gateway["upstreams"] if u["provider"] == "anthropic")
        assert upstream["model_families"][0]["models"] == ["claude-3.5-sonnet", "claude-sonnet-5"], gateway["product"]
    assert PREVIEW.validator.validate_profile(merged)["ok"] is True


def test_merge_normalizes_gemini_aliases_and_keeps_distinct_variants(tmp_path) -> None:
    usage_data = _summarize(tmp_path)
    template = next(r for r in usage_data["usage_by_model"] if r["model"].startswith("google/"))
    usage_data["usage_by_model"] = [{**template, "model": m} for m in ("google/gemini-2.5-flash-preview-05-20", "google/gemini-2.5-flash-lite-001")]
    usage = tmp_path / "g.json"
    usage.write_text(json.dumps(usage_data))
    profile = tmp_path / "p.json"
    profile.write_text((FIXTURES / "bma-scan-openrouter-google-pinned/ai-workload-profile.json").read_text())
    assert USAGE.main(["merge", "--usage", str(usage), "--profile", str(profile)]) == 0
    google = next(s for s in json.loads(profile.read_text())["ai_sources"] if s["provider"] == "google")
    assert google["models"] == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    flash = next(o for o in google["model_observations"] if o["normalized_model"] == "gemini-2.5-flash")
    assert flash["raw_model"] == "google/gemini-2.5-flash" and any("as google/gemini-2.5-flash-preview-05-20" in e.get("detail", "") for e in flash["evidence"])
    lite = next(o for o in google["model_observations"] if o["normalized_model"] == "gemini-2.5-flash-lite")
    assert lite["raw_model"] == "google/gemini-2.5-flash-lite-001"


@pytest.mark.parametrize(("raw", "normalized"), [
    ("gemini-2.5-flash-preview-05-20", "gemini-2.5-flash"), ("gemini-1.5-pro-002", "gemini-1.5-pro"), ("gemini-2.0-flash-lite-001", "gemini-2.0-flash-lite"),
    ("gemini-2.0-flash-exp", "gemini-2.0-flash"), ("gemini-2.5-pro-preview", "gemini-2.5-pro"), ("gemini-2.5-flash-lite", "gemini-2.5-flash-lite"),
    ("gemini-2.0-flash-thinking-exp-01-21", "gemini-2.0-flash-thinking"), ("gemini-2.5-flash-image-preview", "gemini-2.5-flash-image"),
    ("gemini-2.5-flash-preview-tts", "gemini-2.5-flash-preview-tts"), ("gemini-3", "gemini-3"), ("gemini-pro", "gemini-pro"),
])
def test_gemini_normalization_matches_the_scanner(raw, normalized) -> None:
    assert USAGE.normalize_gemini(raw) == normalized


def test_merge_places_what_it_can_and_names_the_rest(tmp_path, capsys) -> None:
    usage_data = _summarize(tmp_path)
    usage_data["usage_by_model"] += [{**usage_data["usage_by_model"][1], "model": "mistralai/mistral-large", "provider_name": "Mistral"}]
    usage = tmp_path / "mixed.json"
    usage.write_text(json.dumps(usage_data))
    profile = tmp_path / "p.json"
    profile.write_text((FIXTURES / "bma-scan-openrouter-google-pinned/ai-workload-profile.json").read_text())
    capsys.readouterr()
    assert USAGE.main(["merge", "--usage", str(usage), "--profile", str(profile)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out == {"merged_models": ["anthropic/claude-sonnet-5", "google/gemini-2.5-flash"], "not_merged": ["mistralai/mistral-large", "openai/gpt-4.1"]}
    sources = {(x["provider"], x["source_service"]): x for x in json.loads(profile.read_text())["ai_sources"]}
    assert "claude-sonnet-5" in sources[("anthropic", "anthropic_api")]["models"] and ("openai", "openai_api") not in sources


def test_hourly_peak_reads_date_hour_and_adds_permaslugs_in_the_same_hour(tmp_path) -> None:
    def two_slugs(cap):
        _edit(cap / "analytics-hourly.json", lambda d: d.update(data=[
            {"model_permaslug": "anthropic/claude-sonnet-5-20260901", "response": {"data": {"data": [
                {"date__hour": "2026-10-25T03:00:00.000Z", "tokens_prompt": 600, "tokens_completion": 60, "request_count": 2}], "metadata": {"truncated": False}}}},
            {"model_permaslug": "anthropic/claude-sonnet-5-20261001", "response": {"data": {"data": [
                {"date__hour": "2026-10-25T03:00:00.000Z", "tokens_prompt": 600, "tokens_completion": 60, "request_count": 1}], "metadata": {"truncated": False}}}}]))
        _edit(cap / "manifest.json", lambda m: [c.update(note=None) for c in m["captures"] if c["file"] == "analytics-hourly.json"])
    usage = _summarize(tmp_path, _copy(tmp_path, two_slugs))
    claude = next(r for r in usage["usage_by_model"] if r["model"] == "anthropic/claude-sonnet-5")
    assert (claude["peak"]["peak_source"], claude["peak"]["peak_input_tokens_per_minute"], claude["peak"]["peak_requests_per_minute"]) == ("hour", 20.0, 0.05)


@pytest.mark.parametrize(("script", "function", "path", "params"), [
    ("openrouter-usage.py", "call", "/credits", {}),
    ("anthropic-usage.py", "get", "/v1/organizations/cost_report", {}),
    ("openai-usage.py", "get", "/v1/organization/costs", {}),
])
def test_an_error_body_with_a_string_error_is_reported_not_raised(monkeypatch, script, function, path, params) -> None:
    module = _module(f"bma_error_body_{script.split('-')[0]}", script)

    def opener(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 500, "err", {}, io.BytesIO(b'{"error": "upstream down"}'))
    monkeypatch.setattr(module, "opener", opener)
    with pytest.raises(RuntimeError, match="HTTP 500 upstream down"):
        getattr(module, function)("k", path, params)


def test_a_rejected_key_on_the_optional_key_row_is_skipped(monkeypatch, tmp_path, key_file) -> None:
    code, _, manifest = _capture(monkeypatch, tmp_path, key_file, {**_full_answers(), "/key": 403})
    assert code == 0 and {c["file"]: c["status"] for c in manifest["captures"]}["key.json"] == "skipped"


def test_preview_matches_llm_to_bedrock_for_a_fee_and_a_mixed_row() -> None:
    direct = {"metadata": {"source": "anthropic_usage_api", "window_days": 30, "active_days": 30, "partial_window": False, "cost_status": "complete"},
              "summary": {"monthly_cost_usd": 100.0},
              "usage_by_model": [{"model": "claude-sonnet-5", "input_tokens": 1000, "output_tokens": 0}, {"model": "claude-haiku-5", "input_tokens": 10, "output_tokens": 0}]}
    rows = (_row("anthropic/claude-sonnet-5", "byok_passthrough", 4.0, 90.0, fee=4.0), _row("anthropic/claude-haiku-5", "mixed", 7.0, 5.0))
    profile = json.loads((FIXTURES / "bma-scan-workloads-mixed/ai-workload-profile.json").read_text())
    measured = PREVIEW.preview(profile, [direct, _openrouter(*rows)])["measured_usage"]
    assert measured["monthly_cost_usd"] == 104.0
    assert any("anthropic/claude-haiku-5" in w and "independent OpenRouter usage is dropped too" in w for w in measured["capture_warnings"])
