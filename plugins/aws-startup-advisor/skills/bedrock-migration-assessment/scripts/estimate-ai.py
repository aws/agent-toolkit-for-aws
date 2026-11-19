#!/usr/bin/env python3
"""Compute and check the cost figures of estimation-ai.json for bedrock-migration-assessment from a passing aws-design-ai.json."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


design_ai = _load("bma_estimate_design", "design-ai.py")
preview = _load("bma_estimate_preview", "migration-preview.py")
validator = design_ai.validator

SKILL_ROOT = HERE.parent
SCHEMA_PATH = SKILL_ROOT / "references" / "contracts" / "estimation-ai.schema.json"
TIERS_PATH = SKILL_ROOT / "references" / "vendored" / "ai" / "token-volume-tiers.json"
USAGE_FILES = ("openai-usage-profile.json", "anthropic-usage-profile.json", "openrouter-usage-profile.json")
TOKEN_PRICE = re.compile(r"^\$?(\d+(?:\.\d+)?)(?:/\$?(\d+(?:\.\d+)?))? per 1M tokens\b")
# Bedrock Intelligent Prompt Routing default routers, ai-migration-guardrails.md and estimate Part 6.
ROUTER_FAMILIES = ("anthropic.", "meta.")
CENT = 0.01


class EstimateInputError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def rate(price: Any) -> tuple[float, float] | None:
    """(input, output) dollars per 1M tokens; an embedding's single rate applies to input only; None when not token-priced."""
    match = TOKEN_PRICE.match(price) if isinstance(price, str) else None
    if not match:
        return None
    return float(match.group(1)), float(match.group(2)) if match.group(2) is not None else 0.0


def _usage_model(name: str) -> str:
    return name.lower().rsplit("/", 1)[-1]


def _row_tokens(row: dict) -> tuple[int, int]:
    if "prompt_tokens" in row or "completion_tokens" in row:
        return row.get("prompt_tokens", 0), row.get("completion_tokens", 0)
    return (row.get("input_tokens", 0) + row.get("cache_read_tokens", 0) + row.get("cache_creation_tokens", 0),
            row.get("output_tokens", 0))


def measured_volume(usage: list[dict]) -> dict[str, dict]:
    """Per lowercased model: tokens from full-window usage rows, after the preview's OpenRouter overlap rule."""
    overlap = preview._overlaps(usage) if usage else set()
    out: dict[str, dict] = {}
    for profile in usage:
        full = not profile["metadata"].get("partial_window")
        for row in profile["usage_by_model"]:
            if id(row) in overlap:
                continue
            entry = out.setdefault(_usage_model(row["model"]), {"input_tokens": 0, "output_tokens": 0, "full_window": True})
            i, o = _row_tokens(row)
            entry["input_tokens"] += i
            entry["output_tokens"] += o
            entry["full_window"] = entry["full_window"] and full
    return out


def _cost(tokens_in: float, tokens_out: float, r: tuple[float, float]) -> float:
    return (tokens_in * r[0] + tokens_out * r[1]) / 1_000_000


def _blended(r: tuple[float, float], share: float) -> float:
    return r[0] if r[1] == 0 else share * r[0] + (1 - share) * r[1]


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 2)


def _range(values: list[float | None]) -> tuple[float | None, float | None]:
    if not values or any(v is None for v in values):
        return None, None
    return min(values), max(values)


def build_figures(design: dict, profile: dict, prefs: dict, usage: list[dict], tiers: dict) -> dict:
    rows = design["ai_architecture"]["bedrock_models"]
    blocks = design["design_blocks"]
    plan_rows = design_ai._rows(profile)
    sources_of: dict[str, set[tuple[str, str]]] = {}
    for block, plan_row in zip(blocks, plan_rows):
        if block["target_bedrock_model"] is not None:
            sources_of.setdefault(block["model_id"], set()).add((plan_row["provider"], plan_row["source_service"]))
    models = list(dict.fromkeys(r["source_model_id"] for r in rows))
    by_model = {m: [r for r in rows if r["source_model_id"] == m] for m in models}
    volume = measured_volume(usage)
    measured = {m: volume.get(m.lower()) for m in models}
    basis = "measured" if models and all(v and v["full_window"] for v in measured.values()) else "tier"
    tier_value = design_ai._constraint(prefs, "ai_constraints", "ai_token_volume", tiers["dont_know"]["default"])["value"]
    tier = next((t for t in tiers["tiers"] if t["value"] == tier_value), None)
    if basis == "tier" and tier is None:
        raise EstimateInputError("token_volume_unknown", f"ai_token_volume {tier_value!r} is not a tier in token-volume-tiers.json")
    share = tiers["input_share"]

    per_model, bedrock_lows, bedrock_highs, source_lows, source_highs = {}, [], [], [], []
    for m in models:
        target_rates = [rate(r["bedrock_price"]) for r in by_model[m]]
        source_rates = [rate(r["source_provider_price"]) for r in by_model[m]]
        if basis == "measured":
            v = measured[m]
            target = _range([None if t is None else _cost(v["input_tokens"], v["output_tokens"], t) for t in target_rates])
            source = _range([None if s is None else _cost(v["input_tokens"], v["output_tokens"], s) for s in source_rates])
        else:
            target, source = (None, None), (None, None)
            lo_t, hi_t = tier["min_tokens"] / 1_000_000, None if tier["max_tokens"] is None else tier["max_tokens"] / 1_000_000
            tb = _range([None if t is None else _blended(t, share) for t in target_rates])
            sb = _range([None if x is None else _blended(x, share) for x in source_rates])
            tier_alone = {"low": _r(None if tb[0] is None else lo_t * tb[0]), "high": _r(None if tb[1] is None or hi_t is None else hi_t * tb[1]),
                          "source_low": _r(None if sb[0] is None else lo_t * sb[0]),
                          "source_high": _r(None if sb[1] is None or hi_t is None else hi_t * sb[1])}
        bedrock_lows.append(target[0]); bedrock_highs.append(target[1])
        source_lows.append(source[0]); source_highs.append(source[1])
        point = target[0] if target[0] is not None and abs(target[0] - target[1]) < CENT else None
        src_point = source[0] if source[0] is not None and abs(source[0] - source[1]) < CENT else None
        per_model[m] = {"monthly_cost": _r(point),
                        "vs_source_percent": _r((point - src_point) / src_point * 100) if point is not None and src_point else None,
                        "rows": len(by_model[m]), "measured": measured[m]}
        if basis == "tier":
            per_model[m]["if_all_traffic"] = tier_alone

    if basis == "measured":
        total_in = sum(measured[m]["input_tokens"] for m in models)
        total_out = sum(measured[m]["output_tokens"] for m in models)
        bedrock = (sum(bedrock_lows), sum(bedrock_highs)) if None not in bedrock_lows + bedrock_highs else (None, None)
        source_list = (sum(source_lows), sum(source_highs)) if None not in source_lows + source_highs else (None, None)
        token_volume = {"basis": "measured", "monthly_input_tokens": total_in, "monthly_output_tokens": total_out,
                        "input_share": round(total_in / (total_in + total_out), 4) if total_in + total_out else None}
    else:
        low_tokens, high_tokens = tier["min_tokens"], tier["max_tokens"]
        blends = [None if t is None else _blended(t, share) for m in models for t in (rate(r["bedrock_price"]) for r in by_model[m])]
        sblends = [None if s is None else _blended(s, share) for m in models for s in (rate(r["source_provider_price"]) for r in by_model[m])]
        def bound(b: list[float | None]) -> tuple[float | None, float | None]:
            lo, hi = _range(b)
            if lo is None:
                return None, None
            return low_tokens / 1_000_000 * lo, None if high_tokens is None else high_tokens / 1_000_000 * hi
        bedrock, source_list = bound(blends), bound(sblends)
        token_volume = {"basis": "tier", "tier": tier["value"], "min_tokens": low_tokens, "max_tokens": high_tokens, "input_share": share}

    spend = preview.measured(usage) if usage else None
    measured_spend = spend["monthly_cost_usd"] if spend and basis == "measured" and spend["cost_status"] == "complete" else None
    point = bedrock[0] if bedrock[0] is not None and bedrock[1] is not None and abs(bedrock[0] - bedrock[1]) < CENT else None
    list_point = source_list[0] if source_list[0] is not None and source_list[1] is not None and abs(source_list[0] - source_list[1]) < CENT else None
    current = measured_spend if measured_spend is not None else list_point
    diff = None if point is None or current is None else point - current
    cost_comparison = {"current_source_monthly": _r(current), "projected_bedrock_monthly": _r(point), "monthly_difference": _r(diff),
                       "annual_difference": _r(None if diff is None else diff * 12),
                       "percent_change": _r(diff / current * 100) if diff is not None and current else None}

    cost_by_source: dict[tuple[str, str], list[dict]] = {}
    shared = sorted(m for m in models if len(sources_of.get(m, ())) > 1)
    for m in models:
        for pair in sorted(sources_of.get(m, ())):
            cost_by_source.setdefault(pair, []).append({"model": m, "monthly_cost": per_model[m]["monthly_cost"],
                                                        "vs_source_percent": per_model[m]["vs_source_percent"]})
    targets = {r["aws_model_id"] for r in rows}
    return {
        "token_volume": token_volume,
        "projected_bedrock_monthly_range": {"low": _r(bedrock[0]), "high": _r(bedrock[1])},
        "source_list_monthly_range": {"low": _r(source_list[0]), "high": _r(source_list[1])},
        "source_measured_monthly": _r(measured_spend),
        "cost_comparison": cost_comparison,
        "cost_by_source": [{"provider": p, "source_service": s, "models": ms} for (p, s), ms in sorted(cost_by_source.items())],
        "pricing_source": "cached" if all(rate(r["bedrock_price"]) for r in rows) else "unavailable",
        "per_model": per_model,
        "models_in_two_sources": shared,
        "services_not_estimated": [{"workload_id": b["workload_id"], "target_aws_service": b["target_aws_service"], "reason": "not_token_priced"}
                                   for b in blocks if b["target_aws_service"] is not None],
        "router_available": any(design_ai.CRIS_PREFIX.sub("", t).startswith(ROUTER_FAMILIES) for t in targets),
        "recommend_stay": design["ai_architecture"].get("honest_assessment") == "recommend_stay",
        "bedrock_targets": sorted(targets),
        "usage_unmatched": sorted(set(volume) - {m.lower() for m in models}),
        "overlap_excluded": spend["overlap_excluded"] if spend else [],
        "spend_excludes_usd": spend["spend_excludes_usd"] if spend else 0.0,
    }


def _err(errors: list, code: str, detail: str) -> None:
    errors.append({"code": code, "detail": detail})


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) <= CENT
    return a == b


def check_estimate(estimate: Any, figures: dict, schema: dict | None = None) -> dict:
    schema = schema if schema is not None else json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(estimate, dict):
        return {"ok": False, "errors": [{"code": "not_an_object", "detail": "estimation-ai.json must be a JSON object"}]}
    errors = [{"code": "schema_violation", "detail": m} for m in validator._schema_errors(schema, estimate, schema)]
    if errors:
        return {"ok": False, "errors": errors}
    for key in ("cost_comparison",):
        for field, want in figures[key].items():
            if not _same(estimate[key][field], want):
                _err(errors, "figure_mismatch", f"{key}.{field} is {estimate[key][field]!r}, plan computed {want!r}")
    tv = estimate["token_volume"]
    for field, want in figures["token_volume"].items():
        if not _same(tv.get(field), want):
            _err(errors, "figure_mismatch", f"token_volume.{field} is {tv.get(field)!r}, plan computed {want!r}")
    roi = estimate["roi_analysis"]
    for field in ("projected_bedrock_monthly_range", "source_list_monthly_range", "source_measured_monthly"):
        got, want = roi.get(field), figures[field]
        same = isinstance(got, dict) and all(_same(got.get(k), v) for k, v in want.items()) if isinstance(want, dict) else _same(got, want)
        if not same:
            _err(errors, "figure_mismatch", f"roi_analysis.{field} is {got!r}, plan computed {want!r}")
    if estimate["pricing_source"] != figures["pricing_source"]:
        _err(errors, "figure_mismatch", f"pricing_source must be {figures['pricing_source']!r}")
    got_sources = sorted(estimate["cost_by_source"], key=lambda e: (e["provider"], e["source_service"]))
    if len(got_sources) != len(figures["cost_by_source"]):
        _err(errors, "cost_by_source", f"cost_by_source must list {[(e['provider'], e['source_service']) for e in figures['cost_by_source']]}")
    else:
        for got, want in zip(got_sources, figures["cost_by_source"]):
            gm = sorted(got["models"], key=lambda x: x["model"])
            wm = sorted(want["models"], key=lambda x: x["model"])
            if (got["provider"], got["source_service"]) != (want["provider"], want["source_service"]) or \
                    [x["model"] for x in gm] != [x["model"] for x in wm] or \
                    not all(_same(a[k], b[k]) for a, b in zip(gm, wm) for k in ("monthly_cost", "vs_source_percent")):
                _err(errors, "cost_by_source", f"{want['provider']}/{want['source_service']} must be {want['models']}")
    if sorted(estimate["services_not_estimated"], key=json.dumps) != sorted(figures["services_not_estimated"], key=json.dumps):
        _err(errors, "services_not_estimated", f"services_not_estimated must be {figures['services_not_estimated']}")

    rec = estimate["recommendation"]
    if figures["recommend_stay"] and rec["path"] != "stay":
        _err(errors, "recommendation_stay", "Design's honest_assessment is recommend_stay, so recommendation.path must be stay")
    for key in ("recommended_model", "backup_model"):
        model = estimate[key].get("model")
        if key == "recommended_model" and model not in figures["bedrock_targets"]:
            _err(errors, key, f"{key}.model must be one of the Design targets {figures['bedrock_targets']}")
        elif key == "backup_model" and model is not None and not isinstance(model, str):
            _err(errors, key, "backup_model.model must be a model id or null")
    for opp in estimate["optimization_opportunities"]:
        if opp["type"] == "provisioned_throughput" and re.search(r"\b[13][- ]year\b", opp["commitment"], re.I):
            _err(errors, "provisioned_throughput_term", "Provisioned Throughput has no 1-year or 3-year term: no-commit, 1-month, or 6-month")
        if opp["type"] == "intelligent_prompt_routing" and not figures["router_available"]:
            _err(errors, "prompt_routing_unavailable", "no Design target is in a family with a default Intelligent Prompt Routing router")
    if "App Runner" in json.dumps(estimate):
        _err(errors, "app_runner", "\"App Runner\" must not appear in the estimate")
    return {"ok": not errors, "errors": errors} if errors else {"ok": True, "basis": figures["token_volume"]["basis"]}


def _read_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EstimateInputError(f"{code}_not_found", str(path))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise EstimateInputError(f"{code}_unreadable", f"{path}: {exc}")


def _usage_ok(profile: Any) -> bool:
    def count(v: Any) -> bool:
        return isinstance(v, int) and not isinstance(v, bool) and v >= 0
    if not (isinstance(profile, dict) and isinstance(profile.get("metadata"), dict) and isinstance(profile.get("summary"), dict)
            and isinstance(profile.get("usage_by_model"), list)):
        return False
    if "monthly_cost_usd" not in profile["summary"]:
        return False
    md, cost = profile["metadata"], profile["summary"]["monthly_cost_usd"]
    if not (isinstance(md.get("source"), str) and count(md.get("window_days")) and count(md.get("active_days"))
            and isinstance(md.get("partial_window"), bool) and (cost is None or isinstance(cost, (int, float)) and not isinstance(cost, bool))
            and md.get("cost_status", "complete") in preview.COST_STATUS_ORDER
            and isinstance(md.get("capture_warnings", []), list) and isinstance(md.get("uncosted_service_tiers", []), list)):
        return False
    return all(isinstance(r, dict) and isinstance(r.get("model"), str) and all(count(r[f]) for f in preview.TOKEN_FIELDS if f in r)
               and all(isinstance(r[f], (int, float)) and not isinstance(r[f], bool) for f in ("monthly_cost_usd", "byok_inference_cost_usd",
                                                                                              "byok_fees_usd") if f in r)
               for r in profile["usage_by_model"])


def figures_for(run_dir: Path) -> dict:
    profile = _read_json(run_dir / "ai-workload-profile.json", "profile")
    validator.validate_profile(profile)
    prefs = _read_json(run_dir / "preferences.json", "preferences")
    if not isinstance(prefs, dict):
        raise EstimateInputError("preferences_unreadable", "preferences.json must be a JSON object")
    design = _read_json(run_dir / "aws-design-ai.json", "design")
    result = design_ai.check_design(design, profile, prefs)
    if not result["ok"]:
        raise EstimateInputError("design_invalid", "aws-design-ai.json fails design-ai.py check; finish Design first: "
                                 + "; ".join(e["code"] for e in result["errors"][:5]))
    usage = []
    for name in USAGE_FILES:
        if (run_dir / name).exists():
            profile_u = _read_json(run_dir / name, "usage")
            if not _usage_ok(profile_u):
                raise EstimateInputError("usage_unreadable", f"{name} does not have metadata, summary and usage_by_model rows")
            usage.append(profile_u)
    return build_figures(design, profile, prefs, usage, json.loads(TIERS_PATH.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "check"))
    parser.add_argument("run_dir", type=Path, help="the $MIGRATION_DIR holding the profile, preferences.json and aws-design-ai.json")
    args = parser.parse_args(argv)
    try:
        figures = figures_for(args.run_dir)
        if args.command == "plan":
            result = {"ok": True, **figures}
        else:
            result = check_estimate(_read_json(args.run_dir / "estimation-ai.json", "estimate"), figures)
    except validator.ProfileRejected as exc:
        result = {"ok": False, "error": f"profile_{exc.code}", "detail": exc.detail}
    except (EstimateInputError, design_ai.DesignInputError) as exc:
        result = {"ok": False, "error": exc.code, "detail": exc.detail}
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
