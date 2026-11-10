#!/usr/bin/env python3
"""Compute migration-preview.json for bedrock-migration-assessment from a validated ai-workload-profile.json."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("bma_preview_validator", Path(__file__).with_name("validate-ai-profile.py"))
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)

PATH_SHAPE = {
    "likely_simple": "shortest path: one model to move; confirm after Clarify",
    "standard": "standard path: more than one model or capability to evaluate; confirm after Clarify",
    "complex": "long path: agents, a gateway, or several providers to migrate; confirm after Clarify",
}


def classify(profile: dict, summary: dict) -> tuple[str, list[str]]:
    """First matching line wins; also returns why the fast path is not offered."""
    models = sorted({m["model"] for s in summary["ai_sources"] for m in s["models"]})
    providers = {s["provider"] for s in summary["ai_sources"]}
    caps = (profile.get("integration") or {}).get("capabilities_summary")
    if "agentic_profile" in profile:
        return "complex", ["agents were detected"]
    if summary["gateways"]:
        return "complex", ["calls go through a gateway"]
    if len(providers) > 1:
        return "complex", ["more than one provider"]
    if len(models) > 3:
        return "complex", ["more than three models"]
    unknown = any(s["model_evidence"] == "not_observed" for s in summary["ai_sources"])
    if len(models) == 1 and not unknown and caps is not None and sum(caps.values()) <= 2:
        return "likely_simple", []
    reasons = []
    if unknown:
        reasons.append("a source's model was not observed")
    if len(models) != 1:
        reasons.append(f"{len(models)} models")
    if caps is None:
        reasons.append("no integration evidence (schema 1.0 profile)")
    elif sum(caps.values()) > 2:
        reasons.append("more than two capabilities in use")
    return "standard", reasons


def decisions(profile: dict, summary: dict, models: list[str]) -> list[str]:
    caps = (profile.get("integration") or {}).get("capabilities_summary") or {}
    shown = ", ".join(models[:3]) + (f" + {len(models) - 3} more" if len(models) > 3 else "")
    out = [f"Bedrock model selection for {shown}" if models else "Bedrock model selection (no model was observed)"]
    if "agentic_profile" in profile:
        out.append("Agentic migration path (retarget, AgentCore, or Strands)")
    if summary["gateways"]:
        out.append("Routing on Bedrock for " + ", ".join(sorted({g["product"] for g in summary["gateways"]})))
    if len({s["provider"] for s in summary["ai_sources"]}) > 1:
        out.append("Per-provider model mapping and evaluation")
    if caps.get("embeddings"):
        out.append("Re-embedding stored vectors with a Bedrock embedding model")
    if caps.get("vision"):
        out.append("A Bedrock model that accepts image input")
    if caps.get("streaming"):
        out.append("Streaming responses on Bedrock")
    return out[:4]


COST_STATUS_ORDER = ("complete", "partial_window", "cost_unavailable")


def measured(profiles: list[dict]) -> dict | None:
    """Per-source usage plus totals; the total spend is null when any source's spend is unknown."""
    if not profiles:
        return None
    sources = []
    for usage in profiles:
        md = usage["metadata"]
        tokens = sum(r.get(f, 0) for r in usage["usage_by_model"] for f in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"))
        sources.append({"source": md["source"], "monthly_cost_usd": usage["summary"]["monthly_cost_usd"],
                        "cost_status": md.get("cost_status", "partial_window" if md["partial_window"] else "complete"),
                        "window_days": md["window_days"], "active_days": md["active_days"], "partial_window": md["partial_window"],
                        "total_tokens": tokens, "uncosted_service_tiers": md.get("uncosted_service_tiers", []),
                        "capture_warnings": md.get("capture_warnings", [])})
    costs = [s["monthly_cost_usd"] for s in sources]
    return {"sources": sources, "monthly_cost_usd": None if None in costs else round(sum(costs), 2),
            "cost_status": max((s["cost_status"] for s in sources), key=COST_STATUS_ORDER.index),
            "total_tokens": sum(s["total_tokens"] for s in sources), "window_days": max(s["window_days"] for s in sources),
            "active_days": min(s["active_days"] for s in sources), "partial_window": any(s["partial_window"] for s in sources),
            "capture_warnings": [f"{s['source']}: {w}" for s in sources for w in s["capture_warnings"]]}


def preview(profile: dict, usage: list[dict] | None = None) -> dict:
    summary = validator.validate_profile(profile)
    models = sorted({m["model"] for s in summary["ai_sources"] for m in s["models"]})
    signal, reasons = classify(profile, summary)
    eligible = signal == "likely_simple" and summary["models_extractable"]
    if signal == "likely_simple" and not summary["models_extractable"]:
        reasons = ["the model is not high-confidence evidence, so Q5 must be asked"]
    agents = (profile.get("agentic_profile") or {}).get("agents", [])
    out = {
        "preview_version": 2,
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "route": "ai_only",
        "ai_complexity_signal": signal,
        "eligible_for_clarify_fast_path": eligible,
        "fast_path_blocked_by": [] if eligible else reasons or [f"complexity is {signal}"],
        "ai_summary": {
            "model_count": len(models),
            "model_ids": models,
            "providers": sorted({s["provider"] for s in summary["ai_sources"]}),
            "gateways": sorted({g["product"] for g in summary["gateways"]}),
            "agent_count": len(agents),
            "tool_count": len(profile.get("tool_manifest", [])),
        },
        "measured_usage": measured(usage or []),
        "path_shape": PATH_SHAPE[signal],
        "key_decisions_ahead": decisions(profile, summary, models),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile", type=Path)
    ap.add_argument("--usage", type=Path, action="append", default=[], help="a <provider>-usage-profile.json; repeat once per captured provider")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        result = preview(json.loads(args.profile.read_text()), [json.loads(u.read_text()) for u in args.usage])
    except validator.ProfileRejected as err:
        print(json.dumps({"ok": False, "error": err.code, "detail": err.detail}))
        return 1
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"ok": True, "ai_complexity_signal": result["ai_complexity_signal"],
                      "eligible_for_clarify_fast_path": result["eligible_for_clarify_fast_path"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
