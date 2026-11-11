#!/usr/bin/env python3
"""Read-only OpenRouter usage capture for bedrock-migration-assessment: the only code that touches the management key."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://openrouter.ai/api/v1"
KEY_LINE = re.compile(r"^OPENROUTER_PROVISIONING_KEY=(\S+)\s*$")
GET_PATHS = {"/credits", "/workspaces", "/activity", "/key", "/analytics/meta"}
POST_PATHS = {"/analytics/query"}
FORBIDDEN_PARAMS = {"api_key_hash", "user_id", "group_by"}
CLASSIFY_METRICS = ["byok_usage", "openrouter_usage"]
VOLUME_METRICS = ["tokens_prompt", "tokens_completion", "reasoning_tokens", "cached_tokens", "byok_fees", "byok_request_count", "request_count",
                  "p95_latency", "p95_throughput", "usage_web", "guardrail_invoked_count"]
HOURLY_METRICS = ["tokens_prompt", "tokens_completion", "request_count"]
ANALYTICS_ROWS = [("analytics.json", CLASSIFY_METRICS, None), ("analytics-volume.json", VOLUME_METRICS, None),
                  ("analytics-hourly.json", HOURLY_METRICS, "hour")]
CAPTURE_FILES = ["credits.json", "activity.json", "key.json", "analytics-meta.json"] + [f for f, _, _ in ANALYTICS_ROWS]
BYOK_THRESHOLD = 0.005
MAX_ANALYTICS_MODELS = 50
KEY_FIELDS = ("limit", "limit_remaining", "limit_reset", "include_byok_in_limit", "is_free_tier")
sleep = time.sleep
opener = urllib.request.urlopen


class KeyRejected(Exception):
    """A 401 or 403 from the API: the key is not a management key, or was revoked."""


def read_key(key_file: Path) -> str:
    lines = key_file.read_text().splitlines() if key_file.is_file() else []
    match = KEY_LINE.match(lines[0]) if len(lines) == 1 else None
    if not match:
        raise SystemExit("KEY_FORMAT_BAD: the key file must hold one line OPENROUTER_PROVISIONING_KEY=<management key>")
    return match.group(1)


def delete_key(key_file: Path) -> None:
    key_file.unlink(missing_ok=True)


def _redact(message: str) -> str:
    return re.sub(r"sk-or-[A-Za-z0-9_*-]+", "sk-or-[redacted]", message)


def call(key: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
    """One allowlisted request: GET for the read endpoints, POST only for the aggregate analytics query."""
    params = params or {}
    if body is None and path not in GET_PATHS or body is not None and path not in POST_PATHS or FORBIDDEN_PARAMS & set(params):
        raise ValueError(f"endpoint or parameter not allowed: {path}")
    if body is not None and (body.get("dimensions") or body.get("granularity") not in (None, "hour")
                             or any(f.get("field") not in ("workspace", "model") or f.get("operator") != "eq" for f in body.get("filters", []))):
        raise ValueError("analytics query must have no dimensions, hourly granularity at most, and only workspace and model equality filters")
    url = f"{BASE_URL}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"} | ({"Content-Type": "application/json"} if data else {})
    retried = False
    while True:
        request = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers=headers)
        try:
            with opener(request, timeout=60) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as err:
            if err.code in (401, 403):
                raise KeyRejected(str(err.code)) from None
            if err.code == 429 and not retried:
                retried = True
                sleep(30)
                continue
            try:
                message = json.loads(err.read()).get("error", {}).get("message", "")
            except ValueError:
                message = ""
            raise RuntimeError(f"HTTP {err.code} {_redact(str(message).replace(key, '[redacted]'))}".strip()) from None


def _window() -> tuple[int, int]:
    """The last 30 completed UTC days, the window /activity reports."""
    now = int(time.time())
    end = now - now % 86400
    return end - 30 * 86400, end


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_check_key(args) -> int:
    read_key(args.key_file)
    print("KEY_FORMAT_OK")
    return 0


def cmd_probe(args) -> int:
    """Account-level credits and the workspace list, printed for the picker and never written to disk."""
    key = read_key(args.key_file)
    try:
        credits = call(key, "/credits").get("data") or {}
        workspaces, offset = [], 0
        while True:
            page = call(key, "/workspaces", {"limit": 100, "offset": offset}).get("data") or []
            workspaces += page
            if len(page) < 100:
                break
            offset += 100
    except KeyRejected:
        delete_key(args.key_file)
        print("KEY_REJECTED")
        return 2
    except BaseException:
        delete_key(args.key_file)
        raise
    print(json.dumps({"total_credits": credits.get("total_credits"), "total_usage": credits.get("total_usage")}))
    for ws in workspaces:
        print(json.dumps({"workspace_id": ws.get("id"), "name": ws.get("name"), "slug": ws.get("slug")}))
    return 0


def _analytics_body(metrics: list[str], granularity: str | None, start: int, end: int, workspace: str | None, permaslug: str, limit: int) -> dict:
    """One model's totals: responses label the model dimension for display, so each query filters by one permaslug instead of grouping."""
    filters = [{"field": "model", "operator": "eq", "value": permaslug}]
    if workspace:
        filters.append({"field": "workspace", "operator": "eq", "value": workspace})
    body = {"metrics": metrics, "time_range": {"start": _iso(start), "end": _iso(end)}, "filters": filters, "limit": limit}
    if granularity:
        body["granularity"] = granularity
    return body


def cmd_capture(args) -> int:
    key = read_key(args.key_file)
    try:
        return _capture(args, key)
    finally:
        delete_key(args.key_file)


def _capture(args, key: str) -> int:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for stale in CAPTURE_FILES + ["manifest.json"]:
        (args.out_dir / stale).unlink(missing_ok=True)
    start, end = _window()
    captures, status = [], 0

    def record(name: str, endpoint: str, fetch, optional: bool = False) -> dict | None:
        nonlocal status
        entry = {"endpoint": endpoint, "file": name, "status": "ok", "note": None}
        captures.append(entry)
        try:
            data = fetch()
        except KeyRejected as err:
            entry.update(status="failed", note=str(err))
            if name in ("credits.json", "activity.json"):
                status = 3
            print(f"{name} failed 0")
            return None
        except RuntimeError as err:
            entry.update(status="skipped" if optional else "failed", note=str(err))
            print(f"{name} {entry['status']} 0")
            return None
        (args.out_dir / name).write_text(json.dumps(data))
        rows = data.get("data")
        print(f"{name} ok {len(rows) if isinstance(rows, list) else 1}")
        return data

    record("credits.json", "/credits", lambda: call(key, "/credits"))
    params = {"workspace_id": args.workspace_id} if args.workspace_id else {}
    activity = record("activity.json", "/activity", lambda: call(key, "/activity", params)) if status == 0 else None
    if status == 3:
        print("KEY_INVALID_MID_RUN")
    else:
        record("key.json", "/key", lambda: {"data": {k: v for k, v in (call(key, "/key").get("data") or {}).items() if k in KEY_FIELDS}}, optional=True)
        meta = record("analytics-meta.json", "/analytics/meta", lambda: call(key, "/analytics/meta"))
        available = {m.get("name") for m in ((meta or {}).get("data") or {}).get("metrics", [])}
        slugs = sorted({r.get("model_permaslug") for r in ((activity or {}).get("data") or []) if r.get("model_permaslug")})
        for name, metrics, granularity in ANALYTICS_ROWS:
            wanted = [m for m in metrics if m in available]
            if not wanted or not slugs:
                note = "analytics metadata unavailable" if meta is None else "none of these metrics is offered" if not wanted else "no models in /activity"
                captures.append({"endpoint": "/analytics/query", "file": name, "status": "skipped", "note": note})
                print(f"{name} skipped 0")
                continue

            def query(wanted=wanted, granularity=granularity):
                out = []
                for slug in slugs[:MAX_ANALYTICS_MODELS]:
                    result = call(key, "/analytics/query", body=_analytics_body(wanted, granularity, start, end, args.workspace_id, slug, 1000))
                    if ((result.get("data") or {}).get("metadata") or {}).get("truncated"):
                        result = call(key, "/analytics/query", body=_analytics_body(wanted, granularity, start, end, args.workspace_id, slug, 5000))
                    out.append({"model_permaslug": slug, "response": result})
                return {"data": out}
            data = record(name, "/analytics/query", query)
            if data is not None:
                captures[-1]["metrics"] = wanted
                truncated = [q["model_permaslug"] for q in data["data"] if ((q["response"].get("data") or {}).get("metadata") or {}).get("truncated")]
                skipped = slugs[MAX_ANALYTICS_MODELS:]
                if truncated or skipped:
                    captures[-1]["note"] = "; ".join(filter(None, [f"truncated for {', '.join(truncated)}" if truncated else "",
                                                                   f"not queried (over {MAX_ANALYTICS_MODELS} models): {', '.join(skipped)}" if skipped else ""]))
        if activity is None:
            print("ALL_USAGE_FAILED")
            status = 4
    manifest = {"captured_at": _iso(int(time.time())), "window_days": 30, "window_start_utc": _iso(start), "window_end_utc": _iso(end),
                "workspace_scope": {"workspace_id": args.workspace_id, "workspace_name": args.workspace_name} if args.workspace_id else None,
                "result": {0: "complete", 3: "key_invalid_mid_run", 4: "all_usage_failed"}[status], "captures": captures}
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return status


def _loader(capture_dir: Path, manifest: dict):
    """Load a capture file only when the current manifest records it as ok; leftovers from earlier attempts are ignored."""
    ok = {c["file"] for c in manifest["captures"] if c["status"] == "ok"}

    def load(name: str):
        path = capture_dir / name
        return json.loads(path.read_text()) if name in ok and path.is_file() else None
    return load


def _per_slug(payload) -> dict[str, list]:
    """permaslug -> that model's analytics rows; a truncated reply is left out."""
    out = {}
    for q in (payload or {}).get("data") or []:
        data = (q.get("response") or {}).get("data") or {}
        if not (data.get("metadata") or {}).get("truncated"):
            out[q["model_permaslug"]] = data.get("data") or []
    return out


def _measured(rows: list, metric: str, offered: set[str]):
    """Sum of one metric, or None when it was not offered or no row reported it."""
    values = [r[metric] for r in rows if r.get(metric) is not None]
    return sum(float(v) for v in values) if metric in offered and values else None


def _classify(byok: float, credits: float) -> str:
    if byok > BYOK_THRESHOLD:
        return "byok_passthrough" if credits <= BYOK_THRESHOLD else "mixed"
    return "no_byok" if credits > BYOK_THRESHOLD else "unknown"


def _roll_up(labels: list[str]) -> str:
    """One label per short model id from its permaslugs' labels."""
    found = set(labels)
    if found == {"unknown"}:
        return "unknown"
    if "unknown" in found:
        return "uncertain"
    if "mixed" in found or {"byok_passthrough", "no_byok"} <= found:
        return "mixed"
    return found.pop()


def cmd_summarize(args) -> int:
    d = args.capture_dir
    manifest = json.loads((d / "manifest.json").read_text())
    if manifest.get("result") != "complete":
        print(f"CAPTURE_NOT_COMPLETE: {manifest.get('result')}")
        return 7
    load = _loader(d, manifest)
    status_of = {c["file"]: c for c in manifest["captures"]}
    activity = (load("activity.json") or {}).get("data") or []
    credits = (load("credits.json") or {}).get("data") or {}
    offered = {name: set(status_of.get(name, {}).get("metrics") or []) for name, _, _ in ANALYTICS_ROWS}
    classify = {}
    for slug, rs in _per_slug(load("analytics.json")).items():
        byok_cost, credit_cost = _measured(rs, "byok_usage", offered["analytics.json"]), _measured(rs, "openrouter_usage", offered["analytics.json"])
        if byok_cost is not None and credit_cost is not None:
            classify[slug] = (byok_cost, credit_cost)
    volume = _per_slug(load("analytics-volume.json"))
    hourly = _per_slug(load("analytics-hourly.json"))
    end = int(datetime.fromisoformat(manifest["window_end_utc"].replace("Z", "+00:00")).timestamp())
    window_days = manifest["window_days"]
    rows: dict[str, dict] = {}
    labels: dict[str, dict[str, str]] = {}
    first_day = None
    for r in activity:
        model, slug = r.get("model") or "unknown-model", r.get("model_permaslug") or r.get("model") or "unknown-model"
        day = int(datetime.fromisoformat(r["date"] + "T00:00:00+00:00").timestamp())
        tokens = (r.get("prompt_tokens") or 0) + (r.get("completion_tokens") or 0)
        if (tokens or (r.get("usage") or 0) or (r.get("byok_usage_inference") or 0)) and (first_day is None or day < first_day):
            first_day = day
        row = rows.setdefault(model, {"model": model, "provider_name": r.get("provider_name"), "requests": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                      "reasoning_tokens": 0, "cached_tokens": 0, "monthly_cost_usd": 0.0, "byok_inference_cost_usd": 0.0, "_days": {}})
        if row["provider_name"] != r.get("provider_name"):
            row["provider_name"] = None
        for f in ("requests", "prompt_tokens", "completion_tokens", "reasoning_tokens", "cached_tokens"):
            row[f] += r.get(f) or 0
        row["monthly_cost_usd"] += float(r.get("usage") or 0)
        row["byok_inference_cost_usd"] += float(r.get("byok_usage_inference") or 0)
        day_stats = row["_days"].setdefault(day, [0, 0, 0])
        day_stats[0] += r.get("prompt_tokens") or 0
        day_stats[1] += r.get("completion_tokens") or 0
        day_stats[2] += r.get("requests") or 0
        if slug not in labels.setdefault(model, {}):
            labels[model][slug] = _classify(*classify[slug]) if slug in classify else "unknown"
        row.setdefault("_slugs", set()).add(slug)
    active_days = window_days if first_day is None else min(window_days, max(1, math.ceil((end - first_day) / 86400)))
    hour_max: dict[str, list] = {}
    for model, row in rows.items():
        slugs = row["_slugs"]
        if not slugs <= set(hourly) or not {"tokens_prompt", "tokens_completion"} <= offered["analytics-hourly.json"]:
            continue
        per_hour: dict = {}
        for slug in slugs:
            for i, r in enumerate(hourly[slug]):
                hour = next((r[k] for k in ("hour", "time", "timestamp", "date", "period", "bucket") if k in r), None)
                if hour is None and len(slugs) > 1:
                    per_hour = None
                    break
                h = per_hour.setdefault(hour if hour is not None else i, [0, 0, 0])
                h[0] += r.get("tokens_prompt") or 0
                h[1] += r.get("tokens_completion") or 0
                h[2] += r.get("request_count") or 0
            if per_hour is None:
                break
        if per_hour:
            hour_max[model] = [max(h[i] for h in per_hour.values()) for i in range(3)]
    warnings = [f"{c['file']} {c['status']}" + (f" ({c['note']})" if c.get("note") else "") for c in manifest["captures"]
                if c["status"] != "ok" or c.get("note")]
    analytics_known = status_of.get("analytics.json", {}).get("status") == "ok" and set(CLASSIFY_METRICS) <= offered["analytics.json"]
    usage = []
    for model, row in rows.items():
        total = row["prompt_tokens"] + row["completion_tokens"]
        if not (total or row["monthly_cost_usd"] or row["byok_inference_cost_usd"]):
            continue
        label = _roll_up(list(labels[model].values())) if analytics_known else "unknown"
        if label == "uncertain":
            warnings.append(f"{model}: cost_provenance uncertain — at least one contributing permaslug has no Analytics signal; "
                            "token/dollar totals include its usage but its BYOK-vs-credits split is unverified")
        out = {k: v for k, v in row.items() if not k.startswith("_")}
        out.update(monthly_cost_usd=round(row["monthly_cost_usd"], 2), byok_inference_cost_usd=round(row["byok_inference_cost_usd"], 2), cost_provenance=label)
        if row["_slugs"] <= set(volume):
            vs = [r for s in row["_slugs"] for r in volume[s]]
            per_slug = [volume[s] for s in row["_slugs"]]

            def summed(metric, digits=None):
                parts = [_measured(rs, metric, offered["analytics-volume.json"]) for rs in per_slug]
                return None if None in parts else round(sum(parts), digits) if digits is not None else int(sum(parts))
            latencies = [float(v["p95_latency"]) for v in vs if v.get("p95_latency") is not None and "p95_latency" in offered["analytics-volume.json"]]
            speeds = [float(v["p95_throughput"]) for v in vs if v.get("p95_throughput") is not None and "p95_throughput" in offered["analytics-volume.json"]]
            out.update(byok_fees_usd=summed("byok_fees", 4), byok_request_count=summed("byok_request_count"), analytics_request_count=summed("request_count"),
                       p95_latency_ms=max(latencies) if latencies else None, p95_throughput_tokens_per_sec=min(speeds) if speeds else None,
                       web_search_cost_usd=summed("usage_web", 4), guardrail_invoked_count=summed("guardrail_invoked_count"))
            unmeasured = [f for f in ("byok_fees_usd", "byok_request_count", "analytics_request_count", "web_search_cost_usd", "guardrail_invoked_count")
                          if out[f] is None]
            if unmeasured:
                warnings.append(f"{model}: {', '.join(unmeasured)} not measured (metric not offered or not reported); null, not zero")
        days = row["_days"]
        busiest = max(days, key=lambda dd: (days[dd][0] + days[dd][1], -dd)) if days else None
        peak = None
        if busiest is not None:
            b = days[busiest]
            peak = {"busiest_day": datetime.fromtimestamp(busiest, timezone.utc).strftime("%Y-%m-%d"), "day_input_tokens": b[0], "day_output_tokens": b[1],
                    "day_requests": b[2], "day_to_average_ratio": round((b[0] + b[1]) / (total / active_days), 2) if total else None,
                    "peak_input_tokens_per_minute": None, "peak_output_tokens_per_minute": None, "peak_requests_per_minute": None, "peak_source": "day"}
            if model in hour_max:
                h = hour_max[model]
                peak.update(peak_input_tokens_per_minute=round(h[0] / 60, 2), peak_output_tokens_per_minute=round(h[1] / 60, 2),
                            peak_requests_per_minute=round(h[2] / 60, 2), peak_source="hour")
        out["peak"] = peak
        usage.append(out)
    usage.sort(key=lambda r: -(r["prompt_tokens"] + r["completion_tokens"]))
    if not analytics_known:
        state = status_of.get("analytics.json", {}).get("status", "skipped")
        reason = "without both byok_usage and openrouter_usage" if state == "ok" else state
        warnings.append(f"analytics.json {reason} — cost_provenance is unknown for all models")
    if not activity and float(credits.get("total_usage") or 0) > 0:
        warnings.append(f"activity empty but credits.total_usage is ${credits['total_usage']} lifetime — spend exists outside the 30-day window; "
                        "per-model attribution unavailable")
    byok_total = round(sum(r["byok_inference_cost_usd"] for r in usage), 2)
    if byok_total > BYOK_THRESHOLD:
        warnings.append(f"${byok_total} of BYOK inference was billed by your own provider keys and is not in monthly_cost_usd")
    found = {r["cost_provenance"] for r in usage}
    if not analytics_known or not found or found == {"unknown"}:
        provenance = "unknown"
    elif len(found) == 1 and found != {"uncertain"}:
        provenance = found.pop()
    else:
        provenance = "mixed"
    partial = active_days < window_days or not usage
    profile = {
        "metadata": {"source": "openrouter_usage_api", "captured_at": manifest["captured_at"], "window_days": window_days, "active_days": active_days,
                     "partial_window": partial, "cost_status": "partial_window" if partial else "complete", "cost_provenance": provenance,
                     "credits_lifetime": {"total_credits": credits.get("total_credits"), "total_usage": credits.get("total_usage")} if credits else None,
                     "workspace_scope": manifest.get("workspace_scope"), "capture_warnings": warnings},
        "summary": {"monthly_cost_usd": round(sum(r["monthly_cost_usd"] for r in usage), 2), "byok_inference_cost_usd": byok_total, "currency": "USD",
                    "models_seen": len(usage), "total_requests": sum(r["requests"] for r in usage),
                    "total_tokens": sum(r["prompt_tokens"] + r["completion_tokens"] for r in usage)},
        "usage_by_model": usage,
    }
    args.out.write_text(json.dumps(profile, indent=2) + "\n")
    print(json.dumps(profile["summary"]))
    return 0


def _sibling(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOOGLE_SERVICE = {"google vertex": "vertex_ai", "google ai studio": "gemini_api"}
GEMINI_VERSION_SUFFIX = re.compile(r"-(?:latest|preview|exp)(?:-[0-9][0-9-]*)?$|-[0-9]+$")


def normalize_gemini(model: str) -> str:
    """discover-app-code.md Step 4: drop only version suffixes; -lite, -thinking, -image, -live, and -tts stay part of the model."""
    while True:
        shorter = GEMINI_VERSION_SUFFIX.sub("", model)
        if shorter == model or shorter in ("gemini", ""):
            return model
        model = shorter


def _source_of(row: dict) -> tuple[str, str, str] | None:
    """(provider, source_service, normalized model) by the scan's OpenRouter prefix rules, or None when the source is not established."""
    prefix, _, name = row["model"].partition("/")
    if not name:
        return None
    if prefix in ("openai", "anthropic"):
        return prefix, f"{prefix}_api", name.lower()
    if prefix == "google":
        service = GOOGLE_SERVICE.get((row.get("provider_name") or "").lower())
        name = name.lower()
        return ("google", service, normalize_gemini(name) if name.startswith("gemini-") else name) if service else None
    return None


def _references(upstream: dict, key: tuple[str, str], sources: list[dict]) -> bool:
    """Whether a gateway upstream resolves to this source, by the validator's rule for service-less upstreams."""
    if "source_service" in upstream:
        return (upstream["provider"], upstream["source_service"]) == key
    return upstream["provider"] == key[0] and sum(s["provider"] == key[0] for s in sources) == 1


def cmd_merge(args) -> int:
    usage = json.loads(args.usage.read_text())
    profile = json.loads(args.profile.read_text())
    gateway = next((g for g in profile["gateways"] if g["product"] == "openrouter"), None)
    if gateway is None or gateway["upstream_evidence"] != "observed":
        print("GATEWAY_NOT_OBSERVED: the profile has no OpenRouter gateway with observed upstreams; usage models were not merged")
        return 5
    resolved = [(row, _source_of(row)) for row in usage["usage_by_model"]]
    unresolved = sorted(row["model"] for row, src in resolved if src is None)
    if unresolved:
        print(f"SOURCE_NOT_ESTABLISHED: {', '.join(unresolved)}; usage models were not merged")
        return 5
    family_of = _sibling("bma_openai_usage_for_openrouter", "openai-usage.py").model_family
    days = usage["metadata"]["window_days"]
    touched: set[tuple[str, str]] = set()
    for row, (provider, service, model) in resolved:
        key = (provider, service)
        source = next((s for s in profile["ai_sources"] if (s["provider"], s["source_service"]) == key), None)
        if source is None or not any(_references(u, key, profile["ai_sources"]) for u in gateway["upstreams"]):
            print(f"UPSTREAM_NOT_IN_PROFILE: {provider}/{service} is not an observed OpenRouter upstream; usage models were not merged")
            return 5
        entry = {"provenance": "usage_api", "confidence": "high",
                 "detail": f"OpenRouter usage API: {row['requests']} requests as {row['model']} in the last {days} days"}
        obs = next((o for o in source["model_observations"] if o["normalized_model"] == model), None)
        if obs is None:
            source["model_observations"].append({"normalized_model": model, "raw_model": row["model"], "model_family": family_of(model), "evidence": [entry]})
        elif entry not in obs["evidence"]:
            obs["evidence"].append(entry)
        source["model_evidence"] = "observed"
        source["models"] = sorted({o["normalized_model"] for o in source["model_observations"]})
        source["model_families"] = sorted({o["model_family"] for o in source["model_observations"]})
        touched.add(key)
    for key in touched:
        source = next(s for s in profile["ai_sources"] if (s["provider"], s["source_service"]) == key)
        by_family: dict[str, list] = {}
        for o in source["model_observations"]:
            by_family.setdefault(o["model_family"], []).append(o["normalized_model"])
        families = [{"family": f, "model_evidence": source["model_evidence"], "models": sorted(ms)} for f, ms in sorted(by_family.items())]
        for gw in profile["gateways"]:
            for upstream in gw["upstreams"]:
                if _references(upstream, key, profile["ai_sources"]):
                    upstream["model_families"] = families
    validator = _sibling("bma_validator_for_openrouter", "validate-ai-profile.py")
    try:
        validator.validate_profile(profile)
    except validator.ProfileRejected as err:
        print(f"MERGE_INVALID: {err}")
        return 6
    args.profile.write_text(json.dumps(profile, indent=2) + "\n")
    print(json.dumps({"merged_models": sorted(row["model"] for row in usage["usage_by_model"])}))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check-key", "probe", "capture"):
        p = sub.add_parser(name)
        p.add_argument("--key-file", type=Path, required=True)
        if name == "capture":
            p.add_argument("--out-dir", type=Path, required=True)
            p.add_argument("--workspace-id", help="one workspace UUID; omit for every workspace")
            p.add_argument("--workspace-name")
    p = sub.add_parser("summarize")
    p.add_argument("--capture-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("merge")
    p.add_argument("--usage", type=Path, required=True)
    p.add_argument("--profile", type=Path, required=True)
    args = ap.parse_args(argv)
    return {"check-key": cmd_check_key, "probe": cmd_probe, "capture": cmd_capture, "summarize": cmd_summarize, "merge": cmd_merge}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
