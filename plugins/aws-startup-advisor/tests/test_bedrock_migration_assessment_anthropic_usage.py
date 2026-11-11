"""bedrock-migration-assessment Anthropic usage reader, multi-provider preview, and Q3/Q7 measured prefill."""
from __future__ import annotations

import copy
import importlib.util
import io
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
CAPTURE = FIXTURES / "bma-anthropic-usage" / "capture"
READER = (BMA / "references/phases/discover/discover-anthropic-api.md").read_text(encoding="utf-8")
CONTROLLER = (BMA / "references/phases/discover/discover.md").read_text(encoding="utf-8")
CLARIFY = (BMA / "references/phases/clarify/clarify-ai-only.md").read_text(encoding="utf-8")
KEY = "sk-ant-admin01-TESTKEY0123456789"


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, BMA / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


USAGE = _module("bma_anthropic_usage", "anthropic-usage.py")
OPENAI = _module("bma_openai_usage_for_anthropic_tests", "openai-usage.py")
PREVIEW = _module("bma_migration_preview_for_anthropic_tests", "migration-preview.py")


class FakeAPI:
    """Stands in for urlopen: records every request and answers from a script of responses per (path, bucket_width)."""

    def __init__(self, answers: dict):
        self.answers, self.requests = answers, []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        path, _, query = request.full_url.removeprefix(USAGE.BASE_URL).partition("?")
        width = dict(urllib.parse.parse_qsl(query)).get("bucket_width")
        answer = self.answers.get((path, width), self.answers.get(path, {"data": [], "has_more": False, "next_page": None}))
        answer = answer.pop(0) if isinstance(answer, list) else answer
        if isinstance(answer, int):
            body = json.dumps({"error": {"message": f"invalid x-api-key {KEY}"}}).encode()
            raise urllib.error.HTTPError(request.full_url, answer, "err", {}, io.BytesIO(body))
        return io.BytesIO(json.dumps(answer).encode())


def _row(workspace, model="claude-sonnet-5", tier="standard", unc=10, out=1):
    return {"model": model, "service_tier": tier, "context_window": "0-200k", "inference_geo": "us", "speed": "standard", "workspace_id": workspace,
            "uncached_input_tokens": unc, "cache_read_input_tokens": 0, "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0},
            "output_tokens": out, "server_tool_use": {"web_search_requests": 0}}


def _page(results, more=None, start="2026-10-25T10:00:00Z"):
    return {"data": [{"starting_at": start, "ending_at": start, "results": results}], "has_more": more is not None, "next_page": more}


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    path = tmp_path / ".anthropic-admin-env"
    path.write_text(f"ANTHROPIC_ADMIN_KEY={KEY}\n")
    return path


def _capture(monkeypatch, tmp_path, key_file, answers, workspaces=("wrkspc_app",)):
    api = FakeAPI(answers)
    monkeypatch.setattr(USAGE, "opener", api)
    monkeypatch.setattr(USAGE, "sleep", lambda s: None)
    args = ["capture", "--key-file", str(key_file), "--out-dir", str(tmp_path / "cap")] + [a for w in workspaces for a in ("--workspace", w)]
    code = USAGE.main(args)
    return code, api, json.loads((tmp_path / "cap" / "manifest.json").read_text())


def _query(request) -> list[tuple[str, str]]:
    return urllib.parse.parse_qsl(request.full_url.partition("?")[2])


def test_capture_is_get_only_scoped_and_never_leaks_the_key(monkeypatch, tmp_path, key_file, capsys) -> None:
    usage = USAGE.USAGE_PATH
    code, api, manifest = _capture(monkeypatch, tmp_path, key_file, {
        USAGE.COST_PATH: _page([{"amount": "100", "workspace_id": "wrkspc_app"}, {"amount": "900", "workspace_id": "wrkspc_other"}]),
        (usage, "1d"): [429, _page([_row("wrkspc_app")], more="p2"), _page([_row("wrkspc_app", unc=5)])],
        (usage, "1h"): _page([_row("wrkspc_app")]),
    })
    assert code == 0 and {r.get_method() for r in api.requests} == {"GET"}
    assert all(r.full_url.startswith("https://api.anthropic.com/v1/organizations/") for r in api.requests)
    assert all(r.get_header("X-api-key") == KEY and r.get_header("Anthropic-version") == "2023-06-01" for r in api.requests)
    assert not any(k == "group_by[]" and v in USAGE.FORBIDDEN_GROUPS for r in api.requests for k, v in _query(r))
    usage_requests = [r for r in api.requests if usage in r.full_url]
    assert usage_requests and all(("workspace_ids[]", "wrkspc_app") in _query(r) for r in usage_requests)
    assert not any("workspace_ids[]" in dict(_query(r)) for r in api.requests if USAGE.COST_PATH in r.full_url)
    assert any(("page", "p2") in _query(r) for r in api.requests)
    cost = json.loads((tmp_path / "cap" / "cost-report.json").read_text())
    assert [r["workspace_id"] for b in cost for r in b["results"]] == ["wrkspc_app"]
    assert manifest["result"] == "complete" and manifest["workspace_filter"] == ["wrkspc_app"] and not key_file.exists()
    out = capsys.readouterr()
    everything = out.out + out.err + "".join(p.read_text() for p in (tmp_path / "cap").iterdir())
    assert KEY not in everything and KEY not in "".join(r.full_url for r in api.requests)


def test_default_workspace_is_filtered_by_row_not_by_query(monkeypatch, tmp_path, key_file) -> None:
    code, api, _ = _capture(monkeypatch, tmp_path, key_file, {
        (USAGE.USAGE_PATH, "1d"): _page([_row(None), _row("wrkspc_app"), _row("wrkspc_other")]),
    }, workspaces=("default", "wrkspc_app"))
    assert code == 0
    assert not any("workspace_ids[]" in dict(_query(r)) for r in api.requests)
    kept = json.loads((tmp_path / "cap" / "usage-messages.json").read_text())
    assert [r["workspace_id"] for b in kept for r in b["results"]] == [None, "wrkspc_app"]


def test_capture_stops_on_a_revoked_key_and_requires_a_workspace(monkeypatch, tmp_path, key_file) -> None:
    (tmp_path / "cap").mkdir()
    (tmp_path / "cap" / "usage-messages-hourly.json").write_text("[]")
    code, _, manifest = _capture(monkeypatch, tmp_path, key_file, {(USAGE.USAGE_PATH, "1d"): 401})
    assert code == 3 and manifest["result"] == "key_invalid_mid_run" and manifest["captures"][-1]["status"] == "failed"
    assert not key_file.exists() and not (tmp_path / "cap" / "usage-messages-hourly.json").exists()
    assert USAGE.main(["summarize", "--capture-dir", str(tmp_path / "cap"), "--out", str(tmp_path / "u.json")]) == 7
    (tmp_path / "bad").write_text("ANTHROPIC_ADMIN_KEY=sk-ant-api03-x\n")
    with pytest.raises(SystemExit, match="KEY_FORMAT_BAD"):
        USAGE.read_key(tmp_path / "bad")


def test_a_forbidden_row_fails_alone_and_a_failed_usage_row_ends_the_capture(monkeypatch, tmp_path, key_file) -> None:
    code, _, manifest = _capture(monkeypatch, tmp_path, key_file, {USAGE.COST_PATH: 403, (USAGE.USAGE_PATH, "1d"): _page([_row("wrkspc_app")])})
    assert code == 0 and {c["file"]: c["status"] for c in manifest["captures"]}["cost-report.json"] == "failed"
    key_file.write_text(f"ANTHROPIC_ADMIN_KEY={KEY}\n")
    code, _, manifest = _capture(monkeypatch, tmp_path, key_file, {(USAGE.USAGE_PATH, "1d"): 500})
    assert code == 4 and manifest["result"] == "all_usage_failed" and not key_file.exists()


@pytest.mark.parametrize(("answer", "code", "line"), [(401, 2, "KEY_REJECTED"), (403, 2, "KEY_REJECTED"), (404, 8, "ORG_NOT_SUPPORTED")])
def test_probe_deletes_the_key_when_it_cannot_read_usage(monkeypatch, tmp_path, key_file, capsys, answer, code, line) -> None:
    monkeypatch.setattr(USAGE, "opener", FakeAPI({USAGE.COST_PATH: answer}))
    assert USAGE.main(["probe", "--key-file", str(key_file)]) == code and not key_file.exists()
    assert capsys.readouterr().out.strip() == line


def test_probe_lists_each_workspace_in_dollars_and_writes_nothing(monkeypatch, tmp_path, key_file, capsys) -> None:
    api = FakeAPI({USAGE.COST_PATH: _page([{"amount": "1250.4", "workspace_id": None}, {"amount": "300", "workspace_id": "wrkspc_app"},
                                           {"amount": "50", "workspace_id": None}])})
    monkeypatch.setattr(USAGE, "opener", api)
    before = sorted(tmp_path.iterdir())
    assert USAGE.main(["probe", "--key-file", str(key_file)]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines == [{"workspace_id": "default", "spend_usd": 13.0}, {"workspace_id": "wrkspc_app", "spend_usd": 3.0}]
    assert ("group_by[]", "workspace_id") in _query(api.requests[0]) and sorted(tmp_path.iterdir()) == before and key_file.exists()


def _summarize(tmp_path, capture=CAPTURE) -> dict:
    out = tmp_path / "u.json"
    assert USAGE.main(["summarize", "--capture-dir", str(capture), "--out", str(out), "--label", "wrkspc_app=production"]) == 0
    return json.loads(out.read_text())


def test_summarize_keeps_token_pools_apart_and_the_higher_peak(tmp_path) -> None:
    usage = _summarize(tmp_path)
    assert usage["summary"] == {"monthly_cost_usd": 16.5, "currency": "USD", "models_seen": 3, "total_tokens": 9950}
    assert sum(r["monthly_cost_usd"] for r in usage["costs_by_description"]) == pytest.approx(16.5)
    md = usage["metadata"]
    assert (md["active_days"], md["partial_window"], md["cost_status"], md["uncosted_service_tiers"]) == (12, True, "partial_window", ["priority"])
    assert md["workspaces"] == [{"id": "default"}, {"id": "wrkspc_app", "label": "production"}]
    rows = {r["model"]: r for r in usage["usage_by_model"]}
    assert [r["model"] for r in usage["usage_by_model"]] == ["claude-haiku-5", "claude-sonnet-5", "claude-opus-5-5"]
    sonnet = rows["claude-sonnet-5"]
    assert (sonnet["input_tokens"], sonnet["cache_read_tokens"], sonnet["cache_creation_5m_tokens"], sonnet["cache_creation_1h_tokens"],
            sonnet["cache_creation_tokens"], sonnet["output_tokens"], sonnet["web_search_requests"]) == (3000, 500, 200, 100, 300, 1000, 2)
    assert (sonnet["peak"]["peak_input_tokens_per_minute"], sonnet["peak"]["peak_output_tokens_per_minute"], sonnet["peak"]["peak_source"]) == (90, 10.0, "minute")
    assert sonnet["peak"]["busiest_day"] == "2026-10-25"
    assert (rows["claude-haiku-5"]["peak"]["peak_input_tokens_per_minute"], rows["claude-haiku-5"]["peak"]["peak_source"]) == (66.67, "hour")
    assert "num_model_requests" not in sonnet and "peak_requests_per_minute" not in sonnet["peak"]


def test_peak_input_counts_cache_writes_but_not_cache_reads() -> None:
    hourly = json.loads((CAPTURE / "usage-messages-hourly.json").read_text())
    best, days = USAGE._peaks(hourly)
    key = next(k for k in best if k[0] == "claude-sonnet-5")
    assert best[key] == [1300, 600]
    assert days[key][USAGE._epoch("2026-10-20T00:00:00Z")] == [1300, 300]


def test_a_cache_read_heavy_day_is_not_the_busiest_day(tmp_path) -> None:
    def heavy_reads(cap):
        for name in ("usage-messages.json", "usage-messages-hourly.json"):
            _edit(cap / name, lambda buckets: [r.update(cache_read_input_tokens=100000) for b in buckets for r in b["results"]
                                               if b["starting_at"].startswith("2026-10-20") and r["model"] == "claude-sonnet-5"])
    usage = _summarize(tmp_path, _copy(tmp_path, heavy_reads))
    sonnet = next(r for r in usage["usage_by_model"] if r["model"] == "claude-sonnet-5")
    assert sonnet["cache_read_tokens"] == 100000 and sonnet["peak"]["busiest_day"] == "2026-10-25"
    assert (sonnet["peak"]["day_input_tokens"], sonnet["peak"]["day_to_average_ratio"]) == (2000, round(2700 / (4300 / 12), 2))
    hourly = json.loads((tmp_path / "cap" / "usage-messages-hourly.json").read_text())
    assert USAGE._busiest_on_demand_day(hourly)[0] == USAGE._epoch("2026-10-25T00:00:00Z")


def _network_down(request, timeout=None):
    raise urllib.error.URLError("temporary failure in name resolution")


@pytest.mark.parametrize("command", ["probe", "capture"])
def test_a_network_error_still_deletes_the_key_file(monkeypatch, tmp_path, key_file, capsys, command) -> None:
    monkeypatch.setattr(USAGE, "opener", _network_down)
    argv = [command, "--key-file", str(key_file)] + (["--out-dir", str(tmp_path / "cap"), "--workspace", "wrkspc_app"] if command == "capture" else [])
    with pytest.raises(urllib.error.URLError):
        USAGE.main(argv)
    out = capsys.readouterr()
    assert not key_file.exists() and KEY not in out.out + out.err


def test_a_missing_workspace_keeps_the_key_for_a_corrected_capture(tmp_path, key_file) -> None:
    with pytest.raises(SystemExit):
        USAGE.main(["capture", "--key-file", str(key_file), "--out-dir", str(tmp_path / "cap")])
    assert key_file.exists()


def _copy(tmp_path, mutate) -> Path:
    cap = tmp_path / "cap"
    cap.mkdir()
    for f in CAPTURE.iterdir():
        (cap / f.name).write_text(f.read_text())
    mutate(cap)
    return cap


def _edit(path: Path, change) -> None:
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def _full_window(cap: Path) -> None:
    _edit(cap / "manifest.json", lambda m: m.update(window_days=2))


def _no_priority(cap: Path) -> None:
    for name in ("usage-messages.json", "usage-messages-hourly.json"):
        _edit(cap / name, lambda buckets: [b.update(results=[r for r in b["results"] if r["service_tier"] != "priority"]) for b in buckets])


def _cost_failed(cap: Path) -> None:
    _edit(cap / "manifest.json", lambda m: m["captures"][0].update(status="failed", note="HTTP 403"))


def _cost_empty(cap: Path) -> None:
    (cap / "cost-report.json").write_text("[]")


@pytest.mark.parametrize(("mutations", "cost", "status", "uncosted"), [
    ((_cost_failed,), None, "cost_unavailable", ["priority"]),
    ((_full_window, _no_priority, _cost_empty), 0.0, "complete", []),
    ((_full_window, _cost_empty), 0.0, "partial_window", ["priority"]),
    ((_full_window, _no_priority), 16.5, "complete", []),
], ids=["cost-failed", "cost-empty-full-window", "uncosted-tier-only", "complete"])
def test_cost_status_separates_failed_empty_and_uncosted(tmp_path, mutations, cost, status, uncosted) -> None:
    usage = _summarize(tmp_path, _copy(tmp_path, lambda cap: [m(cap) for m in mutations]))
    assert (usage["summary"]["monthly_cost_usd"], usage["metadata"]["cost_status"], usage["metadata"]["uncosted_service_tiers"]) == (cost, status, uncosted)
    assert usage["summary"]["total_tokens"] > 0


def test_summarize_ignores_files_the_manifest_does_not_mark_ok(tmp_path) -> None:
    def hourly_failed(cap):
        _edit(cap / "manifest.json", lambda m: m["captures"][2].update(status="failed", note="HTTP 500"))
    usage = _summarize(tmp_path, _copy(tmp_path, hourly_failed))
    sonnet = next(r for r in usage["usage_by_model"] if r["model"] == "claude-sonnet-5")
    assert sonnet["peak"]["peak_source"] == "day" and sonnet["peak"]["peak_input_tokens_per_minute"] is None
    assert usage["metadata"]["capture_warnings"] == ["usage-messages-hourly.json failed (HTTP 500)",
                                                      "cost_report does not include priority tier spend; this total excludes it"]


def test_merge_adds_anthropic_models_keeps_code_evidence_and_the_verbatim_name(tmp_path) -> None:
    usage = _summarize(tmp_path)
    usage["usage_by_model"].append({**usage["usage_by_model"][0], "model": "Claude-Haiku-4-5"})
    (tmp_path / "u.json").write_text(json.dumps(usage))
    profile = tmp_path / "p.json"
    profile.write_text((FIXTURES / "bma-scan-agents-independent/ai-workload-profile.json").read_text())
    assert USAGE.main(["merge", "--usage", str(tmp_path / "u.json"), "--profile", str(profile)]) == 0
    source = json.loads(profile.read_text())["ai_sources"][0]
    obs = {o["normalized_model"]: o for o in source["model_observations"]}
    assert {"claude-haiku-5", "claude-sonnet-5", "claude-opus-5-5", "claude-haiku-4-5", "claude-sonnet-4-5"} == set(source["models"])
    assert obs["claude-haiku-4-5"]["raw_model"] == "claude-haiku-4-5" and [e["provenance"] for e in obs["claude-haiku-4-5"]["evidence"]] == ["code", "usage_api"]
    assert obs["claude-opus-5-5"]["model_family"] == "claude" and obs["claude-opus-5-5"]["evidence"][0]["confidence"] == "high"
    assert PREVIEW.validator.validate_profile(json.loads(profile.read_text()))["ok"] is True


def test_merge_creates_the_source_and_refuses_a_gateway_upstream(tmp_path) -> None:
    usage = tmp_path / "u.json"
    usage.write_text(json.dumps(_summarize(tmp_path)))
    profile = tmp_path / "p.json"
    profile.write_text((FIXTURES / "bma-scan-openai-direct/ai-workload-profile.json").read_text())
    assert USAGE.main(["merge", "--usage", str(usage), "--profile", str(profile)]) == 0
    assert ("anthropic", "anthropic_api") in {(s["provider"], s["source_service"]) for s in json.loads(profile.read_text())["ai_sources"]}
    profile.write_text((FIXTURES / "bma-scan-framework-gateway/ai-workload-profile.json").read_text())
    before = profile.read_text()
    assert USAGE.main(["merge", "--usage", str(usage), "--profile", str(profile)]) == 5 and profile.read_text() == before


def _openai_usage(tmp_path) -> dict:
    out = tmp_path / "openai.json"
    OPENAI.main(["summarize", "--capture-dir", str(FIXTURES / "bma-openai-usage/capture"), "--out", str(out)])
    return json.loads(out.read_text())


def test_preview_reports_each_source_and_withholds_a_total_it_cannot_know(tmp_path) -> None:
    profile = json.loads((FIXTURES / "bma-scan-workloads-mixed/ai-workload-profile.json").read_text())
    openai, anthropic = _openai_usage(tmp_path), _summarize(tmp_path)
    measured = PREVIEW.preview(profile, [openai, anthropic])["measured_usage"]
    assert [s["source"] for s in measured["sources"]] == ["openai_usage_api", "anthropic_usage_api"]
    assert measured["monthly_cost_usd"] == round(openai["summary"]["monthly_cost_usd"] + 16.5, 2)
    assert measured["total_tokens"] == measured["sources"][0]["total_tokens"] + 9950
    assert measured["sources"][1]["uncosted_service_tiers"] == ["priority"] and measured["cost_status"] == "partial_window"
    unavailable = copy.deepcopy(anthropic)
    unavailable["summary"]["monthly_cost_usd"], unavailable["metadata"]["cost_status"] = None, "cost_unavailable"
    measured = PREVIEW.preview(profile, [openai, unavailable])["measured_usage"]
    assert measured["monthly_cost_usd"] is None and measured["cost_status"] == "cost_unavailable"
    assert measured["sources"][0]["monthly_cost_usd"] == openai["summary"]["monthly_cost_usd"]
    assert PREVIEW.preview(profile)["measured_usage"] is None and PREVIEW.preview(profile)["preview_version"] == 2



def test_preview_keeps_each_source_period_for_a_full_and_a_partial_window(tmp_path) -> None:
    full, short = _openai_usage(tmp_path), _summarize(tmp_path)
    full["metadata"].update(active_days=30, partial_window=False, cost_status="complete")
    measured = PREVIEW.preview(json.loads((FIXTURES / "bma-scan-workloads-mixed/ai-workload-profile.json").read_text()), [full, short])["measured_usage"]
    assert "active_days" not in measured and "partial_window" not in measured
    assert [(s["active_days"], s["partial_window"]) for s in measured["sources"]] == [(30, False), (12, True)]
    q3 = CLARIFY[CLARIFY.index("## Q3 "):CLARIFY.index("## Q4 ")]
    q7 = CLARIFY[CLARIFY.index("## Q7 "):CLARIFY.index("## Q8 ")]
    for q in (q3, q7):
        assert "over its active_days days" in q and "After a source whose `partial_window` is true" in q
    assert "Give each source its own period, never one period for the total" in q3


def test_a_full_window_with_an_uncosted_tier_warns_downstream(tmp_path) -> None:
    usage = _summarize(tmp_path, _copy(tmp_path, _full_window))
    md = usage["metadata"]
    assert (md["partial_window"], md["cost_status"], md["uncosted_service_tiers"]) == (False, "partial_window", ["priority"])
    assert md["capture_warnings"] == ["cost_report does not include priority tier spend; this total excludes it"]
    peak_only = ("hourly.json", "minute.json")
    assert not any(name in w for w in md["capture_warnings"] for name in peak_only)
    other = tmp_path / "cost-failed"
    other.mkdir()
    failed = _summarize(other, _copy(other, lambda cap: [_full_window(cap), _cost_failed(cap)]))
    assert failed["metadata"]["capture_warnings"] == ["cost-report.json failed (HTTP 403)"]


def test_resume_refreshes_a_version_1_preview_before_clarify() -> None:
    old = json.loads((FIXTURES / "bma-preview-v1/migration-preview.json").read_text())
    assert old["preview_version"] == 1 and "sources" not in old["measured_usage"] and "total_tokens" not in old["measured_usage"]
    skill = (BMA / "SKILL.md").read_text(encoding="utf-8")
    step0 = skill[skill.index("## Step 0"):skill.index("## Step 1:")]
    assert "if `migration-preview.json` exists without `preview_version` 2, run Discover Step 2d again" in step0
    assert "scans nothing, and calls no API" in step0

def test_capture_rows_match_the_documented_endpoint_table() -> None:
    table = [row for row in READER.splitlines() if re.match(r"\| [1-4] \|", row)]
    rows = USAGE.DAILY_ROWS + [USAGE.MINUTE_ROW]
    assert [re.search(r"`(/v1/[^`]+)`", r).group(1) for r in table] == [p for p, _, _ in rows]
    assert [re.search(r"limit=(\d+)", r).group(1) for r in table] == [str(q["limit"]) for _, q, _ in rows]
    assert [re.search(r"`([a-z-]+\.json)`\s*\|$", r).group(1) for r in table] == [f for _, _, f in rows]
    assert USAGE.PROBE_ROW[0] == rows[0][0] and USAGE.PROBE_ROW[1]["group_by"] == ["workspace_id"]


def test_reader_controller_and_clarify_wiring() -> None:
    for rule in ("never open it with any tool", "Only `scripts/anthropic-usage.py` reads it", "each workspace's total spend for the",
                 "usage of workspaces you don't select", "Nothing is created, changed, or deleted in your Anthropic account",
                 "no narrower usage-only", "However this flow ends, including when the user skips at any step", "`ORG_NOT_SUPPORTED`",
                 "Claude Enterprise", "Claude Platform on AWS", "Rows of unselected workspaces are never written", "however it ends (including a network error)",
                 "The script stops on a network error or timeout", "the busiest day, and its `day_input_tokens` count uncached input and cache writes"):
        assert rule in READER, rule
    assert CONTROLLER.index("## Step 2c: Usage APIs") < CONTROLLER.index("## Step 2d: Preview")
    for rule in ("`references/phases/discover/discover-anthropic-api.md`", "`anthropic-capture/`", "declining one does not skip the next",
                 "[--usage $MIGRATION_DIR/anthropic-usage-profile.json]", "Pass one `--usage` for each usage profile Step 2c wrote", "**Measured volume**"):
        assert rule in CONTROLLER, rule
    q3 = CLARIFY[CLARIFY.index("## Q3 "):CLARIFY.index("## Q4 ")]
    q7 = CLARIFY[CLARIFY.index("## Q7 "):CLARIFY.index("## Q8 ")]
    assert "Monthly AI spend with your current AI providers?" in q3 and "When `monthly_cost_usd` is `null`" in q3
    for q in (q3, q7):
        assert "not scaled to a month" in q and "(measured)" in q and 'recorded with `chosen_by: "user"`' in q
    assert "do not fill this from a usage-profile file" in q7 and "total_tokens" in q7
    assert "for the fast-path check in Step 1.5 and the measured values Q3 and Q7 show" in CLARIFY
