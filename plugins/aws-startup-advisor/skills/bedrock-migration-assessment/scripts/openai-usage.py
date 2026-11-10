#!/usr/bin/env python3
"""Read-only OpenAI Admin usage capture for bedrock-migration-assessment: the only code that touches the Admin key."""
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

BASE_URL = "https://api.openai.com"
KEY_LINE = re.compile(r"^OPENAI_ADMIN_KEY=(sk-admin-\S+)\s*$")
USAGE = ("completions", "embeddings", "images", "audio_speeches", "audio_transcriptions")
DAILY_ROWS = [
    ("/v1/organization/costs", {"bucket_width": "1d", "group_by": ["line_item"], "limit": 180}, "costs.json"),
    ("/v1/organization/usage/completions", {"bucket_width": "1d", "group_by": ["model", "batch", "service_tier"], "limit": 31}, "usage-completions.json"),
    ("/v1/organization/usage/embeddings", {"bucket_width": "1d", "group_by": ["model"], "limit": 31}, "usage-embeddings.json"),
    ("/v1/organization/usage/images", {"bucket_width": "1d", "group_by": ["model"], "limit": 31}, "usage-images.json"),
    ("/v1/organization/usage/audio_speeches", {"bucket_width": "1d", "group_by": ["model"], "limit": 31}, "usage-audio-speeches.json"),
    ("/v1/organization/usage/audio_transcriptions", {"bucket_width": "1d", "group_by": ["model"], "limit": 31}, "usage-audio-transcriptions.json"),
    ("/v1/organization/usage/completions", {"bucket_width": "1h", "group_by": ["model", "batch", "service_tier"], "limit": 168}, "usage-completions-hourly.json"),
]
MINUTE_ROW = ("/v1/organization/usage/completions", {"bucket_width": "1m", "group_by": ["model", "batch", "service_tier"], "limit": 1440},
              "usage-completions-minute.json")
PROBE_ROW = ("/v1/organization/costs", {"bucket_width": "1d", "group_by": ["project_id"], "limit": 180}, None)
ALLOWED_PATHS = {row[0] for row in DAILY_ROWS + [MINUTE_ROW, PROBE_ROW]}
CACHE_FIELDS = ("input_cached_tokens", "input_cache_write_tokens", "input_text_tokens", "input_image_tokens", "input_audio_tokens")
sleep = time.sleep
opener = urllib.request.urlopen


class KeyRejected(Exception):
    """A 401 from the API: the key is not an Admin key with Usage read, or was revoked."""


def read_key(key_file: Path) -> str:
    lines = key_file.read_text().splitlines() if key_file.is_file() else []
    match = KEY_LINE.match(lines[0]) if len(lines) == 1 else None
    if not match:
        raise SystemExit("KEY_FORMAT_BAD: the key file must hold one line OPENAI_ADMIN_KEY=sk-admin-...")
    return match.group(1)


def get(key: str, path: str, params: dict) -> list:
    """GET every page of one allowlisted endpoint and return the concatenated buckets."""
    if path not in ALLOWED_PATHS or any(g in ("user_id", "api_key_id") for g in params.get("group_by", [])):
        raise ValueError(f"endpoint or grouping not allowed: {path}")
    data, page, retried = [], None, False
    while True:
        query = [(k, v) for k, vs in params.items() for v in (vs if isinstance(vs, list) else [vs]) if k not in ("group_by", "project_ids")]
        query += [("group_by", g) for g in params.get("group_by", [])] + [("project_ids", p) for p in params.get("project_ids", [])]
        query += [("page", page)] if page else []
        request = urllib.request.Request(f"{BASE_URL}{path}?{urllib.parse.urlencode(query)}", method="GET",
                                         headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
        try:
            with opener(request, timeout=60) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as err:
            if err.code == 401:
                raise KeyRejected() from None
            if err.code == 429 and not retried:
                retried = True
                sleep(30)
                continue
            try:
                message = json.loads(err.read()).get("error", {}).get("message", "")
            except ValueError:
                message = ""
            raise RuntimeError(f"HTTP {err.code} {re.sub(r'sk-[A-Za-z0-9_*-]+', 'sk-[redacted]', message)}".strip()) from None
        retried = False
        data += body.get("data", [])
        if not body.get("has_more") or not body.get("next_page"):
            return data
        page = body["next_page"]


def _window(days: int) -> int:
    return int(time.time()) - days * 86400


def cmd_check_key(args) -> int:
    read_key(args.key_file)
    print("KEY_FORMAT_OK")
    return 0


def delete_key(key_file: Path) -> None:
    key_file.unlink(missing_ok=True)


def cmd_probe(args) -> int:
    """The one unfiltered read: per-project spend totals, printed for the picker and never written to disk."""
    key = read_key(args.key_file)
    path, params, _ = PROBE_ROW
    try:
        buckets = get(key, path, {**params, "start_time": _window(args.days)})
    except KeyRejected:
        delete_key(args.key_file)
        print("KEY_REJECTED")
        return 2
    spend: dict[str, float] = {}
    for bucket in buckets:
        for result in bucket.get("results", bucket.get("result", [])):
            spend[result.get("project_id") or "unassigned"] = spend.get(result.get("project_id") or "unassigned", 0.0) + float((result.get("amount") or {}).get("value", 0))
    for project, total in sorted(spend.items(), key=lambda kv: -kv[1]):
        print(json.dumps({"project_id": project, "spend_usd": round(total, 2)}))
    return 0


def _hourly_busiest_on_demand_day(buckets: list) -> tuple[int, int] | None:
    per_day: dict[int, int] = {}
    for bucket in buckets:
        day = bucket["start_time"] - bucket["start_time"] % 86400
        for result in bucket.get("results", bucket.get("result", [])):
            if not result.get("batch"):
                per_day[day] = per_day.get(day, 0) + result.get("input_tokens", 0) + result.get("output_tokens", 0)
    if not per_day or max(per_day.values()) == 0:
        return None
    day = max(per_day, key=lambda d: (per_day[d], -d))
    return day, day + 86400


def cmd_capture(args) -> int:
    key = read_key(args.key_file)
    if not args.project:
        raise SystemExit("at least one --project is required; never capture the whole organization by default")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for stale in [f for _, _, f in DAILY_ROWS + [MINUTE_ROW]] + ["manifest.json"]:
        (args.out_dir / stale).unlink(missing_ok=True)
    start = _window(args.days)
    captures, status = [], 0
    hourly = None
    for path, params, name in DAILY_ROWS + [MINUTE_ROW]:
        entry = {"endpoint": path, "file": name, "status": "ok", "note": None}
        query = {**params, "start_time": start, "project_ids": args.project}
        if name == MINUTE_ROW[2]:
            day = _hourly_busiest_on_demand_day(hourly) if hourly is not None else None
            if day is None:
                entry.update(status="skipped", note="no busiest on-demand day from the hourly capture")
                captures.append(entry)
                print(f"{name} skipped 0")
                continue
            query.update(start_time=day[0], end_time=day[1])
        try:
            buckets = get(key, path, query)
        except KeyRejected:
            print("KEY_INVALID_MID_RUN")
            entry.update(status="failed", note="401")
            captures.append(entry)
            status = 3
            break
        except RuntimeError as err:
            entry.update(status="failed", note=str(err))
            captures.append(entry)
            print(f"{name} failed 0")
            continue
        (args.out_dir / name).write_text(json.dumps(buckets))
        if name == "usage-completions-hourly.json":
            hourly = buckets
        captures.append(entry)
        print(f"{name} ok {len(buckets)}")
    usage_ok = [c for c in captures if c["file"].startswith("usage-") and "hourly" not in c["file"] and "minute" not in c["file"] and c["status"] == "ok"]
    if status == 0 and not usage_ok:
        print("ALL_USAGE_FAILED")
        status = 4
    result = {0: "complete", 3: "key_invalid_mid_run", 4: "all_usage_failed"}[status]
    manifest = {"captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "window_days": args.days,
                "window_start": start, "project_filter": args.project, "result": result, "captures": captures}
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    delete_key(args.key_file)
    return status


def _loader(capture_dir: Path, manifest: dict):
    """Load a capture file only when the current manifest records it as ok; leftovers from earlier attempts are ignored."""
    ok = {c["file"] for c in manifest["captures"] if c["status"] == "ok"}

    def load(name: str) -> list | None:
        path = capture_dir / name
        return json.loads(path.read_text()) if name in ok and path.is_file() else None
    return load


def _results(bucket: dict) -> list:
    return bucket.get("results", bucket.get("result", []))


def cmd_summarize(args) -> int:
    d = args.capture_dir
    manifest = json.loads((d / "manifest.json").read_text())
    if manifest.get("result") != "complete":
        print(f"CAPTURE_NOT_COMPLETE: {manifest.get('result')}")
        return 7
    _load = _loader(d, manifest)
    labels = dict(item.split("=", 1) for item in args.label)
    costs_rows = _load("costs.json")
    costs = costs_rows or []
    line_items: dict[str, float] = {}
    currency = "usd"
    first_paid = None
    for bucket in costs:
        for result in _results(bucket):
            amount = result.get("amount") or {}
            value = float(amount.get("value", 0))
            currency = amount.get("currency", currency)
            line_items[result.get("line_item") or "unattributed"] = line_items.get(result.get("line_item") or "unattributed", 0.0) + value
            if value > 0 and (first_paid is None or bucket["start_time"] < first_paid):
                first_paid = bucket["start_time"]
    window_days = manifest["window_days"]
    end = int(datetime.fromisoformat(manifest["captured_at"].replace("Z", "+00:00")).timestamp())
    active_days = window_days if first_paid is None else min(window_days, max(1, math.ceil((end - first_paid) / 86400)))
    rows: dict[tuple, dict] = {}
    for endpoint in USAGE:
        for bucket in _load(f"usage-{endpoint.replace('_', '-')}.json") or []:
            day = bucket["start_time"] - bucket["start_time"] % 86400
            for r in _results(bucket):
                batch = bool(r.get("batch")) if endpoint == "completions" else None
                tier = (r.get("service_tier") or "default") if endpoint == "completions" else None
                key = (r.get("model") or "unknown-model", endpoint, batch, tier)
                row = rows.setdefault(key, {"model": key[0], "endpoint_type": endpoint, "batch": batch, "service_tier": tier, "input_tokens": 0,
                                            "output_tokens": 0, "num_model_requests": 0, "_days": {}})
                row["input_tokens"] += r.get("input_tokens", 0)
                row["output_tokens"] += r.get("output_tokens", 0)
                row["num_model_requests"] += r.get("num_model_requests", 0)
                for extra in ("images", "seconds", "characters"):
                    if extra in r:
                        row[extra] = row.get(extra, 0) + r[extra]
                if endpoint == "completions":
                    for f in CACHE_FIELDS:
                        row[f] = row.get(f, 0) + r.get(f, 0)
                stats = row["_days"].setdefault(day, [0, 0, 0])
                stats[0] += r.get("input_tokens", 0)
                stats[1] += r.get("output_tokens", 0)
                stats[2] += r.get("num_model_requests", 0)
    hourly, minute = _load("usage-completions-hourly.json"), _load("usage-completions-minute.json")

    def per_key_max(buckets, key_of):
        out: dict[tuple, list] = {}
        hour_days: dict[tuple, dict] = {}
        for bucket in buckets or []:
            day = bucket["start_time"] - bucket["start_time"] % 86400
            for r in _results(bucket):
                k = key_of(r)
                m = out.setdefault(k, [0, 0, 0])
                m[0], m[1], m[2] = max(m[0], r.get("input_tokens", 0)), max(m[1], r.get("output_tokens", 0)), max(m[2], r.get("num_model_requests", 0))
                s = hour_days.setdefault(k, {}).setdefault(day, [0, 0, 0])
                s[0] += r.get("input_tokens", 0)
                s[1] += r.get("output_tokens", 0)
                s[2] += r.get("num_model_requests", 0)
        return out, hour_days

    def ckey(r):
        return (r.get("model") or "unknown-model", "completions", bool(r.get("batch")), r.get("service_tier") or "default")

    hour_max, hour_days = per_key_max(hourly, ckey)
    minute_max, _ = per_key_max(minute, ckey)
    usage = []
    for key, row in rows.items():
        days = hour_days.get(key) if key[1] == "completions" and key in hour_days else row["_days"]
        busiest = max(days, key=lambda dd: (days[dd][0] + days[dd][1], -dd)) if days else None
        total = row["input_tokens"] + row["output_tokens"]
        peak = None
        if busiest is not None:
            b = days[busiest]
            peak = {"busiest_day": datetime.fromtimestamp(busiest, timezone.utc).strftime("%Y-%m-%d"), "day_input_tokens": b[0], "day_output_tokens": b[1],
                    "day_requests": b[2], "day_to_average_ratio": round((b[0] + b[1]) / (total / active_days), 2) if total else None,
                    "peak_input_tokens_per_minute": None, "peak_output_tokens_per_minute": None, "peak_requests_per_minute": None,
                    "peak_source": "day", "peak_window": "full_window"}
            if key[1] == "completions" and key in hour_max:
                from_minute = False
                for i, f in enumerate(("peak_input_tokens_per_minute", "peak_output_tokens_per_minute", "peak_requests_per_minute")):
                    hourly_rate = round(hour_max[key][i] / 60, 2)
                    sampled = minute_max.get(key, [0, 0, 0])[i]
                    peak[f] = sampled if sampled > hourly_rate else hourly_rate
                    from_minute = from_minute or sampled > hourly_rate
                peak.update(peak_source="minute" if from_minute else "hour", peak_window="sampled_day" if from_minute else "full_window")
        out = {k: v for k, v in row.items() if k != "_days"}
        out["peak"] = peak
        if total or row["num_model_requests"]:
            usage.append(out)
    usage.sort(key=lambda r: -(r["input_tokens"] + r["output_tokens"]))
    warnings = [f"{c['file']} {c['status']}" + (f" ({c['note']})" if c.get("note") else "") for c in manifest["captures"] if c["status"] != "ok"]
    partial = active_days < window_days or not usage
    cost_status = "cost_unavailable" if costs_rows is None else "partial_window" if partial else "complete"
    total_cost = None if costs_rows is None else round(sum(line_items.values()), 2)
    profile = {
        "metadata": {"source": "openai_usage_api", "captured_at": manifest["captured_at"], "window_days": window_days, "active_days": active_days,
                     "partial_window": partial, "cost_status": cost_status,
                     "projects": [{"id": p, **({"label": labels[p]} if p in labels else {})} for p in manifest["project_filter"]],
                     "capture_warnings": warnings},
        "summary": {"monthly_cost_usd": total_cost, "currency": currency.upper(), "models_seen": len({r["model"] for r in usage}),
                    "total_requests": sum(r["num_model_requests"] for r in usage)},
        "costs_by_line_item": [{"line_item": k, "monthly_cost_usd": round(v, 2)} for k, v in sorted(line_items.items(), key=lambda kv: -kv[1])],
        "usage_by_model": usage,
    }
    args.out.write_text(json.dumps(profile, indent=2) + "\n")
    print(json.dumps(profile["summary"]))
    return 0


def model_family(model: str) -> str:
    """Step 4 family rule of discover-app-code.md."""
    base = model.split(":")[1] if model.startswith("ft:") and ":" in model[3:] else model
    for prefix, family in (("gpt-", "gpt"), ("o1", "o_series"), ("o3", "o_series"), ("o4", "o_series"), ("claude-", "claude"),
                           ("gemini-", "gemini"), ("text-embedding-", "embedding")):
        if base.startswith(prefix):
            return family
    return re.match(r"[a-z][a-z0-9]*", base).group(0) if re.match(r"[a-z]", base) else "other"


def cmd_merge(args) -> int:
    usage = json.loads(args.usage.read_text())
    profile = json.loads(args.profile.read_text())
    days = usage["metadata"]["window_days"]
    seen: dict[str, int] = {}
    raw: dict[str, str] = {}
    for row in usage["usage_by_model"]:
        model = row["model"].lower()
        if model != "unknown-model":
            seen[model] = seen.get(model, 0) + row["num_model_requests"]
            raw.setdefault(model, row["model"])
    if not seen:
        print("NOTHING_TO_MERGE")
        return 0
    for gateway in profile["gateways"]:
        for upstream in gateway["upstreams"]:
            if upstream["provider"] == "openai" and upstream.get("source_service", "openai_api") == "openai_api":
                print(f"GATEWAY_UPSTREAM_CONFLICT: openai/openai_api is an upstream of {gateway['product']}; usage models were not merged")
                return 5
    source = next((s for s in profile["ai_sources"] if (s["provider"], s["source_service"]) == ("openai", "openai_api")), None)
    if source is None:
        source = {"provider": "openai", "source_service": "openai_api", "model_families": [], "model_evidence": "observed", "models": [], "model_observations": []}
        profile["ai_sources"].append(source)
    for model, requests in sorted(seen.items()):
        entry = {"provenance": "usage_api", "confidence": "high", "detail": f"OpenAI usage API: {requests} requests in the last {days} days"}
        obs = next((o for o in source["model_observations"] if o["normalized_model"] == model), None)
        if obs is None:
            source["model_observations"].append({"normalized_model": model, "raw_model": raw[model], "model_family": model_family(model), "evidence": [entry]})
        elif entry not in obs["evidence"]:
            obs["evidence"].append(entry)
    source["model_evidence"] = "observed"
    source["models"] = sorted({o["normalized_model"] for o in source["model_observations"]})
    source["model_families"] = sorted({o["model_family"] for o in source["model_observations"]})
    spec = importlib.util.spec_from_file_location("bma_validator", Path(__file__).with_name("validate-ai-profile.py"))
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    try:
        validator.validate_profile(profile)
    except validator.ProfileRejected as err:
        print(f"MERGE_INVALID: {err}")
        return 6
    args.profile.write_text(json.dumps(profile, indent=2) + "\n")
    print(json.dumps({"merged_models": sorted(seen)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check-key", "probe", "capture"):
        p = sub.add_parser(name)
        p.add_argument("--key-file", type=Path, required=True)
        if name == "capture":
            p.add_argument("--out-dir", type=Path, required=True)
        if name != "check-key":
            p.add_argument("--days", type=int, default=30)
        if name == "capture":
            p.add_argument("--project", action="append", default=[])
    p = sub.add_parser("summarize")
    p.add_argument("--capture-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--label", action="append", default=[], help="project_id=label")
    p = sub.add_parser("merge")
    p.add_argument("--usage", type=Path, required=True)
    p.add_argument("--profile", type=Path, required=True)
    args = ap.parse_args(argv)
    return {"check-key": cmd_check_key, "probe": cmd_probe, "capture": cmd_capture, "summarize": cmd_summarize, "merge": cmd_merge}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
