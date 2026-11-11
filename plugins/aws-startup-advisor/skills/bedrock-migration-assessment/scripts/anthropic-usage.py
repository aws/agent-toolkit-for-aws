#!/usr/bin/env python3
"""Read-only Anthropic Admin usage capture for bedrock-migration-assessment: the only code that touches the Admin key."""
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
from decimal import Decimal
from pathlib import Path

BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
KEY_LINE = re.compile(r"^ANTHROPIC_ADMIN_KEY=(sk-ant-admin01-\S+)\s*$")
DEFAULT_WORKSPACE = "default"
USAGE_PATH = "/v1/organizations/usage_report/messages"
COST_PATH = "/v1/organizations/cost_report"
USAGE_GROUPS = ["model", "service_tier", "context_window", "inference_geo", "speed", "workspace_id"]
DAILY_ROWS = [
    (COST_PATH, {"bucket_width": "1d", "group_by": ["workspace_id", "description"], "limit": 31}, "cost-report.json"),
    (USAGE_PATH, {"bucket_width": "1d", "group_by": USAGE_GROUPS, "limit": 31}, "usage-messages.json"),
    (USAGE_PATH, {"bucket_width": "1h", "group_by": USAGE_GROUPS, "limit": 168}, "usage-messages-hourly.json"),
]
MINUTE_ROW = (USAGE_PATH, {"bucket_width": "1m", "group_by": USAGE_GROUPS, "limit": 1440}, "usage-messages-minute.json")
PROBE_ROW = (COST_PATH, {"bucket_width": "1d", "group_by": ["workspace_id"], "limit": 31}, None)
ALLOWED_PATHS = {USAGE_PATH, COST_PATH}
FORBIDDEN_GROUPS = {"account_id", "api_key_id", "service_account_id"}
COSTED_TIERS = {"standard", "batch"}
ROW_KEY = ("model", "service_tier", "context_window", "inference_geo", "speed")
sleep = time.sleep
opener = urllib.request.urlopen


class KeyRejected(Exception):
    """A 401 from the API: the key is not an Admin key, or was revoked."""


class Forbidden(Exception):
    """A 403 from the API: the key cannot read this endpoint."""


class OrgNotSupported(Exception):
    """A 404 on the probe: this organization has no legacy usage and cost endpoints."""


def read_key(key_file: Path) -> str:
    lines = key_file.read_text().splitlines() if key_file.is_file() else []
    match = KEY_LINE.match(lines[0]) if len(lines) == 1 else None
    if not match:
        raise SystemExit("KEY_FORMAT_BAD: the key file must hold one line ANTHROPIC_ADMIN_KEY=sk-ant-admin01-...")
    return match.group(1)


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def get(key: str, path: str, params: dict) -> list:
    """GET every page of one allowlisted endpoint and return the concatenated buckets."""
    if path not in ALLOWED_PATHS or FORBIDDEN_GROUPS & set(params.get("group_by", [])):
        raise ValueError(f"endpoint or grouping not allowed: {path}")
    data, page, retried = [], None, False
    while True:
        query = [(k, v) for k, v in params.items() if k not in ("group_by", "workspace_ids")]
        query += [("group_by[]", g) for g in params.get("group_by", [])] + [("workspace_ids[]", w) for w in params.get("workspace_ids", [])]
        query += [("page", page)] if page else []
        request = urllib.request.Request(f"{BASE_URL}{path}?{urllib.parse.urlencode(query)}", method="GET",
                                         headers={"x-api-key": key, "anthropic-version": API_VERSION, "Accept": "application/json"})
        try:
            with opener(request, timeout=60) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as err:
            if err.code == 401:
                raise KeyRejected("401") from None
            if err.code == 403:
                raise Forbidden("HTTP 403") from None
            if err.code == 404:
                raise OrgNotSupported() from None
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


def _window_start(days: int) -> int:
    now = int(time.time())
    return now - now % 86400 - days * 86400


def _workspace(result: dict) -> str:
    return result.get("workspace_id") or DEFAULT_WORKSPACE


def _keep(buckets: list, selected: set[str]) -> list:
    """Drop rows of workspaces the user did not select before anything is written."""
    return [{**b, "results": [r for r in b.get("results", []) if _workspace(r) in selected]} for b in buckets]


def delete_key(key_file: Path) -> None:
    key_file.unlink(missing_ok=True)


def cmd_check_key(args) -> int:
    read_key(args.key_file)
    print("KEY_FORMAT_OK")
    return 0


def cmd_probe(args) -> int:
    """The one unfiltered read: per-workspace spend totals, printed for the picker and never written to disk."""
    key = read_key(args.key_file)
    path, params, _ = PROBE_ROW
    try:
        buckets = get(key, path, {**params, "starting_at": _iso(_window_start(args.days))})
    except (KeyRejected, Forbidden):
        delete_key(args.key_file)
        print("KEY_REJECTED")
        return 2
    except OrgNotSupported:
        delete_key(args.key_file)
        print("ORG_NOT_SUPPORTED")
        return 8
    except BaseException:
        delete_key(args.key_file)
        raise
    spend: dict[str, Decimal] = {}
    for bucket in buckets:
        for result in bucket.get("results", []):
            spend[_workspace(result)] = spend.get(_workspace(result), Decimal(0)) + Decimal(result.get("amount") or "0") / 100
    for workspace, total in sorted(spend.items(), key=lambda kv: -kv[1]):
        print(json.dumps({"workspace_id": workspace, "spend_usd": float(round(total, 2))}))
    return 0


def _tokens(r: dict) -> tuple[int, int, int, int, int]:
    cache = r.get("cache_creation") or {}
    return (r.get("uncached_input_tokens", 0), r.get("cache_read_input_tokens", 0), cache.get("ephemeral_5m_input_tokens", 0),
            cache.get("ephemeral_1h_input_tokens", 0), r.get("output_tokens", 0))


def _busiest_on_demand_day(buckets: list) -> tuple[int, int] | None:
    per_day: dict[int, int] = {}
    for bucket in buckets:
        start = _epoch(bucket["starting_at"])
        day = start - start % 86400
        for r in bucket.get("results", []):
            if r.get("service_tier") != "batch":
                uncached, _, c5, c1, out = _tokens(r)
                per_day[day] = per_day.get(day, 0) + uncached + c5 + c1 + out
    if not per_day or max(per_day.values()) == 0:
        return None
    day = max(per_day, key=lambda d: (per_day[d], -d))
    return day, day + 86400


def cmd_capture(args) -> int:
    key = read_key(args.key_file)
    if not args.workspace:
        raise SystemExit("at least one --workspace is required; never capture the whole organization by default")
    try:
        return _capture(args, key)
    finally:
        delete_key(args.key_file)


def _capture(args, key: str) -> int:
    selected = set(args.workspace)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for stale in [f for _, _, f in DAILY_ROWS + [MINUTE_ROW]] + ["manifest.json"]:
        (args.out_dir / stale).unlink(missing_ok=True)
    start = _window_start(args.days)
    named = sorted(selected - {DEFAULT_WORKSPACE})
    captures, status, hourly = [], 0, None
    for path, params, name in DAILY_ROWS + [MINUTE_ROW]:
        entry = {"endpoint": path, "file": name, "status": "ok", "note": None}
        query = {**params, "starting_at": _iso(start)}
        if path == USAGE_PATH and DEFAULT_WORKSPACE not in selected:
            query["workspace_ids"] = named
        if name == MINUTE_ROW[2]:
            day = _busiest_on_demand_day(hourly) if hourly is not None else None
            if day is None:
                entry.update(status="skipped", note="no busiest on-demand day from the hourly capture")
                captures.append(entry)
                print(f"{name} skipped 0")
                continue
            query.update(starting_at=_iso(day[0]), ending_at=_iso(day[1]))
        try:
            buckets = _keep(get(key, path, query), selected)
        except KeyRejected as err:
            print("KEY_INVALID_MID_RUN")
            entry.update(status="failed", note=str(err))
            captures.append(entry)
            status = 3
            break
        except (RuntimeError, Forbidden, OrgNotSupported) as err:
            entry.update(status="failed", note=str(err) or "HTTP 404")
            captures.append(entry)
            print(f"{name} failed 0")
            continue
        (args.out_dir / name).write_text(json.dumps(buckets))
        if name == "usage-messages-hourly.json":
            hourly = buckets
        captures.append(entry)
        print(f"{name} ok {len(buckets)}")
    if status == 0 and not any(c["file"] == "usage-messages.json" and c["status"] == "ok" for c in captures):
        print("ALL_USAGE_FAILED")
        status = 4
    manifest = {"captured_at": _iso(int(time.time())), "window_days": args.days, "window_start": _iso(start),
                "workspace_filter": sorted(selected), "result": {0: "complete", 3: "key_invalid_mid_run", 4: "all_usage_failed"}[status],
                "captures": captures}
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return status


def _loader(capture_dir: Path, manifest: dict):
    """Load a capture file only when the current manifest records it as ok; leftovers from earlier attempts are ignored."""
    ok = {c["file"] for c in manifest["captures"] if c["status"] == "ok"}

    def load(name: str) -> list | None:
        path = capture_dir / name
        return json.loads(path.read_text()) if name in ok and path.is_file() else None
    return load


def _row_key(r: dict) -> tuple:
    return tuple(r.get(f) for f in ROW_KEY[:1]) + tuple(r.get(f) or "unknown" for f in ROW_KEY[1:])


def _peaks(buckets: list | None) -> tuple[dict, dict]:
    """Per row key: the highest (quota input, output) in any one bucket, and per-day totals."""
    best: dict[tuple, list] = {}
    days: dict[tuple, dict] = {}
    for bucket in buckets or []:
        start = _epoch(bucket["starting_at"])
        day = start - start % 86400
        per_bucket: dict[tuple, list] = {}
        for r in bucket.get("results", []):
            uncached, read, c5, c1, out = _tokens(r)
            b = per_bucket.setdefault(_row_key(r), [0, 0])
            b[0] += uncached + c5 + c1
            b[1] += out
            d = days.setdefault(_row_key(r), {}).setdefault(day, [0, 0])
            d[0] += uncached + c5 + c1
            d[1] += out
        for k, (quota_in, out) in per_bucket.items():
            m = best.setdefault(k, [0, 0])
            m[0], m[1] = max(m[0], quota_in), max(m[1], out)
    return best, days


def cmd_summarize(args) -> int:
    d = args.capture_dir
    manifest = json.loads((d / "manifest.json").read_text())
    if manifest.get("result") != "complete":
        print(f"CAPTURE_NOT_COMPLETE: {manifest.get('result')}")
        return 7
    load = _loader(d, manifest)
    labels = dict(item.split("=", 1) for item in args.label)
    cost_rows = load("cost-report.json")
    by_description: dict[tuple, Decimal] = {}
    first_activity = None
    for bucket in cost_rows or []:
        for r in bucket.get("results", []):
            value = Decimal(r.get("amount") or "0") / 100
            key = (r.get("description"), r.get("model"), r.get("inference_geo"), _workspace(r), r.get("cost_type"))
            by_description[key] = by_description.get(key, Decimal(0)) + value
            if value > 0 and (first_activity is None or _epoch(bucket["starting_at"]) < first_activity):
                first_activity = _epoch(bucket["starting_at"])
    rows: dict[tuple, dict] = {}
    for bucket in load("usage-messages.json") or []:
        for r in bucket.get("results", []):
            uncached, read, c5, c1, out = _tokens(r)
            k = _row_key(r)
            row = rows.setdefault(k, {"model": k[0] or "unknown-model", "service_tier": k[1], "context_window": k[2], "inference_geo": k[3], "speed": k[4],
                                      "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_5m_tokens": 0,
                                      "cache_creation_1h_tokens": 0, "cache_creation_tokens": 0, "web_search_requests": 0})
            row["input_tokens"] += uncached
            row["output_tokens"] += out
            row["cache_read_tokens"] += read
            row["cache_creation_5m_tokens"] += c5
            row["cache_creation_1h_tokens"] += c1
            row["cache_creation_tokens"] += c5 + c1
            row["web_search_requests"] += (r.get("server_tool_use") or {}).get("web_search_requests", 0)
            if (uncached + read + c5 + c1 + out) and (first_activity is None or _epoch(bucket["starting_at"]) < first_activity):
                first_activity = _epoch(bucket["starting_at"])
    window_days = manifest["window_days"]
    end = _epoch(manifest["captured_at"])
    active_days = window_days if first_activity is None else min(window_days, max(1, math.ceil((end - first_activity) / 86400)))
    _, daily_days = _peaks(load("usage-messages.json"))
    hour_max, hour_days = _peaks(load("usage-messages-hourly.json"))
    minute_max, _ = _peaks(load("usage-messages-minute.json"))
    usage = []
    for k, row in rows.items():
        total = row["input_tokens"] + row["cache_read_tokens"] + row["cache_creation_tokens"] + row["output_tokens"]
        if not total:
            continue
        quota_total = row["input_tokens"] + row["cache_creation_tokens"] + row["output_tokens"]
        days = hour_days.get(k) or daily_days.get(k) or {}
        busiest = max(days, key=lambda dd: (sum(days[dd]), -dd)) if days else None
        peak = None
        if busiest is not None:
            day_in, day_out = days[busiest]
            peak = {"busiest_day": datetime.fromtimestamp(busiest, timezone.utc).strftime("%Y-%m-%d"), "day_input_tokens": day_in,
                    "day_output_tokens": day_out, "day_to_average_ratio": round((day_in + day_out) / (quota_total / active_days), 2) if quota_total else None,
                    "peak_input_tokens_per_minute": None, "peak_output_tokens_per_minute": None, "peak_source": "day", "peak_window": "full_window"}
            if k in hour_max:
                from_minute = False
                for i, field in enumerate(("peak_input_tokens_per_minute", "peak_output_tokens_per_minute")):
                    hourly_rate = round(hour_max[k][i] / 60, 2)
                    sampled = minute_max.get(k, [0, 0])[i]
                    peak[field] = sampled if sampled > hourly_rate else hourly_rate
                    from_minute = from_minute or sampled > hourly_rate
                peak.update(peak_source="minute" if from_minute else "hour", peak_window="sampled_day" if from_minute else "full_window")
        usage.append({**row, "peak": peak})
    usage.sort(key=lambda r: -(r["input_tokens"] + r["cache_read_tokens"] + r["cache_creation_tokens"] + r["output_tokens"]))
    warnings = [f"{c['file']} {c['status']}" + (f" ({c['note']})" if c.get("note") else "") for c in manifest["captures"] if c["status"] != "ok"]
    uncosted = sorted({r["service_tier"] for r in usage if r["service_tier"] not in COSTED_TIERS})
    if cost_rows is not None and uncosted:
        warnings.append(f"cost_report does not include {', '.join(uncosted)} tier spend; this total excludes it")
    partial = active_days < window_days or not usage
    cost_status = "cost_unavailable" if cost_rows is None else "partial_window" if partial or uncosted else "complete"
    profile = {
        "metadata": {"source": "anthropic_usage_api", "captured_at": manifest["captured_at"], "window_days": window_days, "active_days": active_days,
                     "partial_window": partial, "cost_status": cost_status, "uncosted_service_tiers": uncosted,
                     "workspaces": [{"id": w, **({"label": labels[w]} if w in labels else {})} for w in manifest["workspace_filter"]],
                     "capture_warnings": warnings},
        "summary": {"monthly_cost_usd": None if cost_rows is None else float(round(sum(by_description.values(), Decimal(0)), 2)), "currency": "USD",
                    "models_seen": len({r["model"] for r in usage}),
                    "total_tokens": sum(r["input_tokens"] + r["cache_read_tokens"] + r["cache_creation_tokens"] + r["output_tokens"] for r in usage)},
        "costs_by_description": [{"description": k[0], "model": k[1], "inference_geo": k[2], "workspace_id": k[3], "cost_type": k[4],
                                  "monthly_cost_usd": float(round(v, 2))} for k, v in sorted(by_description.items(), key=lambda kv: -kv[1])],
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


def cmd_merge(args) -> int:
    usage = json.loads(args.usage.read_text())
    profile = json.loads(args.profile.read_text())
    days = usage["metadata"]["window_days"]
    seen: dict[str, int] = {}
    raw: dict[str, str] = {}
    for row in usage["usage_by_model"]:
        model = row["model"].lower()
        if model != "unknown-model":
            seen[model] = seen.get(model, 0) + row["input_tokens"] + row["cache_read_tokens"] + row["cache_creation_tokens"] + row["output_tokens"]
            raw.setdefault(model, row["model"])
    if not seen:
        print("NOTHING_TO_MERGE")
        return 0
    for gateway in profile["gateways"]:
        for upstream in gateway["upstreams"]:
            if upstream["provider"] == "anthropic" and upstream.get("source_service", "anthropic_api") == "anthropic_api":
                print(f"GATEWAY_UPSTREAM_CONFLICT: anthropic/anthropic_api is an upstream of {gateway['product']}; usage models were not merged")
                return 5
    family = _sibling("bma_openai_usage", "openai-usage.py").model_family
    source = next((s for s in profile["ai_sources"] if (s["provider"], s["source_service"]) == ("anthropic", "anthropic_api")), None)
    if source is None:
        source = {"provider": "anthropic", "source_service": "anthropic_api", "model_families": [], "model_evidence": "observed", "models": [],
                  "model_observations": []}
        profile["ai_sources"].append(source)
    for model, tokens in sorted(seen.items()):
        entry = {"provenance": "usage_api", "confidence": "high", "detail": f"Anthropic usage API: {tokens} tokens in the last {days} days"}
        obs = next((o for o in source["model_observations"] if o["normalized_model"] == model), None)
        if obs is None:
            source["model_observations"].append({"normalized_model": model, "raw_model": raw[model], "model_family": family(model), "evidence": [entry]})
        elif entry not in obs["evidence"]:
            obs["evidence"].append(entry)
    source["model_evidence"] = "observed"
    source["models"] = sorted({o["normalized_model"] for o in source["model_observations"]})
    source["model_families"] = sorted({o["model_family"] for o in source["model_observations"]})
    validator = _sibling("bma_validator", "validate-ai-profile.py")
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
        if name != "check-key":
            p.add_argument("--days", type=int, default=30)
        if name == "capture":
            p.add_argument("--out-dir", type=Path, required=True)
            p.add_argument("--workspace", action="append", default=[], help="workspace id, or 'default' for the default workspace")
    p = sub.add_parser("summarize")
    p.add_argument("--capture-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--label", action="append", default=[], help="workspace_id=label")
    p = sub.add_parser("merge")
    p.add_argument("--usage", type=Path, required=True)
    p.add_argument("--profile", type=Path, required=True)
    args = ap.parse_args(argv)
    return {"check-key": cmd_check_key, "probe": cmd_probe, "capture": cmd_capture, "summarize": cmd_summarize, "merge": cmd_merge}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
