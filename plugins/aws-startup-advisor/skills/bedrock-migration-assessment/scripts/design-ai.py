#!/usr/bin/env python3
"""Plan and check aws-design-ai.json for bedrock-migration-assessment from a validated profile and preferences."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

spec = importlib.util.spec_from_file_location("bma_design_validator", Path(__file__).with_name("validate-ai-profile.py"))
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)

SKILL_ROOT = Path(__file__).resolve().parent.parent
DESIGN_SCHEMA_PATH = SKILL_ROOT / "references" / "contracts" / "aws-design-ai.schema.json"

BEDROCK_CAPABILITIES = ("text_generation", "structured_output", "image_generation", "embedding", "speech_to_text", "text_to_speech", "unknown")
# Policy-table order, schema-design-aws-ai.md § mantle_requirement and endpoint_assumption.
SELECTOR_ORDER = ("background_inference", "server_side_tools", "web_search", "projects", "workspaces", "in_region_processing")
MANTLE_SELECTORS = SELECTOR_ORDER[:5] + ("mantle_only_model_or_api", "in_region_processing")
# Source APIs each selector can run on, bedrock-endpoint-policy.md (read 2026-11-09).
SELECTOR_APIS = {
    "background_inference": {"responses"},
    "web_search": {"responses"},
    "server_side_tools": {"responses"},
    "projects": {"responses", "chat_completions"},
    "workspaces": {"messages"},
    "in_region_processing": {"responses", "chat_completions", "messages"},
}
SELECTOR_PROVIDER = {"projects": "openai", "workspaces": "anthropic"}
MANTLE_PATH = {"responses": "mantle_openai_responses", "chat_completions": "mantle_openai_chat", "messages": "mantle_messages"}
PROVIDER_APIS = {"openai": {"responses", "chat_completions"}, "anthropic": {"messages"}}
PATH_CLIENT_APIS = {
    "mantle_openai_responses": {"responses"},
    "mantle_openai_chat": {"chat_completions"},
    "mantle_messages": {"messages"},
    "runtime_messages": {"messages"},
    "runtime_openai_cris": {"responses", "chat_completions", "converse"},
    "converse": {"converse"},
    "gpt-oss": {"converse", "invoke", "responses", "chat_completions"},
    "direct": {"converse", "invoke"},
}
CLIENT_APIS = {"responses", "chat_completions", "converse", "invoke", "messages"}
ASSESSMENTS = ("strong_migrate", "moderate_migrate", "weak_migrate", "recommend_stay")
QUOTA_RISKS = {"low", "medium", "high"}
WARNING_TYPES = {"embeddings_reindex", "cascade_pair", "multi_model_tiered", "image_separate", "speech_separate"}
AGENTIC_APPROACHES = {"retarget", "harness", "strands", "undecided"}
ROW_KEYS = ("source_model_id", "aws_model_id", "capabilities_matched", "capability_gaps", "honest_assessment",
            "source_provider_price", "bedrock_price", "price_comparison", "migration_complexity", "model_change",
            "migration_path", "quota_risk", "required_client_api")
CRIS_PREFIX = re.compile(r"^(us|us-gov|eu|apac|jp|au|ca|in|global)\.")
GDPR_FORBIDDEN_PREFIX = re.compile(r"^(us|us-gov|apac|jp|au|ca|in|global)\.")
HIGH_VOLUMES = {"high", "very_high"}
SPEECH_SERVICES = {"speech_to_text": "transcribe", "text_to_speech": "polly"}
DEFAULTS = {"ai_priority": "balanced", "ai_latency": "important", "ai_complexity": "moderate", "ai_token_volume": "medium",
            "ai_vision": "text-only", "ai_critical_feature": "none", "cross_cloud": "latency-acceptable"}
ASSUMPTION = ("No Mantle-only requirement was recorded for {ids}; bedrock-runtime selected. If this workload needs "
              "background inference, server-side tools, Projects/Workspaces, or single-Region processing, re-run Clarify.")
GUIDE_DIR = "references/vendored/ai"
# ai-anthropic-to-bedrock.md carries the Claude target contracts every cross-family choice needs.
ALWAYS_GUIDES = ("bedrock-endpoint-policy.md", "ai-model-lifecycle.md", "bedrock-pricing-cache.md", "bedrock-quotas.md",
                 "ai-migration-guardrails.md", "schema-design-aws-ai.md", "ai-anthropic-to-bedrock.md")
PROVIDER_GUIDES = {"openai": ("ai-openai-to-bedrock.md",), "google": ("ai-gemini-to-bedrock.md",)}


class DesignInputError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _escape_model(model: str) -> str:
    return "".join({"_": "_5f", ":": "_3a", "/": "_2f"}.get(ch, ch) for ch in model)


def source_api(sdk_method: str | None) -> str | None:
    if not sdk_method:
        return None
    package, _, call = sdk_method.partition(".")
    if package == "openai":
        call = call.removeprefix("beta.")
        for prefix, api in (("responses.", "responses"), ("chat.completions.", "chat_completions"), ("embeddings.", "embeddings"),
                            ("images.", "images"), ("audio.", "audio")):
            if call.startswith(prefix):
                return api
    if package == "anthropic" and (call.startswith("messages.") or call.startswith("beta.messages.")):
        return "messages"
    if package in ("genai", "vertexai", "google"):
        return "gemini"
    return "framework"


def _constraint(prefs: dict, section: str, key: str, default: Any = None) -> dict:
    entry = (prefs.get(section) or {}).get(key)
    if isinstance(entry, dict) and "value" in entry:
        return {"value": entry["value"], "chosen_by": entry.get("chosen_by")}
    return {"value": default, "chosen_by": "absent"}


def _requests_for(row: dict, prefs: dict, profile: dict) -> list[dict]:
    entries = _constraint(prefs, "ai_constraints", "mantle_requirements", [])["value"] or []
    signals = profile.get("mantle_signals", [])
    matched = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("selector") not in SELECTOR_ORDER or entry.get("source") not in ("detected", "user"):
            continue
        if entry.get("workload_id") == row["workload_id"]:
            matched.append(entry)
        elif entry.get("workload_id") == "*":
            if entry["source"] == "user":
                matched.append(entry)
                continue
            # A detected "*" entry belongs only to the model its signal was found on.
            if any(s["selector"] == entry["selector"] and s["provider"] == row["provider"] and s["source_service"] == row["source_service"]
                   and s["model"] == row["model_id"] and (s["evidence"][0].get("detail") == entry.get("evidence")) for s in signals):
                matched.append(entry)
    return sorted(matched, key=lambda e: SELECTOR_ORDER.index(e["selector"]))


def _lane(row: dict, requests: list[dict]) -> dict:
    if not requests:
        return {"lane": "runtime"}
    api = row["source_api"]
    if row["provider"] not in PROVIDER_APIS or api in ("gemini", "embeddings", "images", "audio"):
        return {"lane": "no_mantle_path"}
    if api in (None, "framework"):
        return {"lane": "api_unknown"}
    conflicts = []
    for entry in requests:
        provider = SELECTOR_PROVIDER.get(entry["selector"])
        if provider and provider != row["provider"]:
            conflicts.append("provider_mismatch")
        elif api not in SELECTOR_APIS[entry["selector"]]:
            conflicts.append("api_conflict" if SELECTOR_APIS[entry["selector"]] & PROVIDER_APIS[row["provider"]] else "no_mantle_path")
        else:
            lane = "in_region_check" if entry["selector"] == "in_region_processing" else "mantle"
            return {"lane": lane, "selector": entry["selector"], "mantle_path": MANTLE_PATH[api], "requirement": entry,
                    "also_requested": [e["selector"] for e in requests if e is not entry]}
    for lane in ("api_conflict", "provider_mismatch"):
        if lane in conflicts:
            return {"lane": lane}
    return {"lane": "no_mantle_path"}


def _rows(profile: dict) -> list[dict]:
    gateways_by_source: dict[tuple[str, str], list[str]] = {}
    for gateway in profile["gateways"]:
        for upstream in gateway["upstreams"]:
            matches = [s for s in profile["ai_sources"] if s["provider"] == upstream["provider"]
                       and s["source_service"] == upstream.get("source_service", s["source_service"])]
            for s in matches[:1]:
                gateways_by_source.setdefault((s["provider"], s["source_service"]), []).append(gateway["product"])
    rows = []
    if profile.get("workloads"):
        for w in profile["workloads"]:
            capability = w["capability"] if w["capability"] in BEDROCK_CAPABILITIES else "unknown"
            rows.append({"workload_id": w["workload_id"], "model_id": w["model"], "provider": w["provider"],
                         "source_service": w["source_service"], "sdk_method": w["sdk_method"], "capability": capability,
                         "capability_confidence": w["capability_confidence"] if capability == w["capability"] else "low",
                         "source_api": source_api(w["sdk_method"]), "call_sites": w["call_sites"]})
    else:
        for s in profile["ai_sources"]:
            for model in s["models"]:
                rows.append({"workload_id": f"{s['source_service']}.{_escape_model(model)}".lower(), "model_id": model,
                             "provider": s["provider"], "source_service": s["source_service"], "sdk_method": None,
                             "capability": "unknown", "capability_confidence": "low", "source_api": None, "call_sites": []})
    for row in rows:
        row["fronted_by"] = sorted(set(gateways_by_source.get((row["provider"], row["source_service"]), [])))
        row["confidence_warning"] = (
            f"{row['workload_id']}: the capability was not established from code; review the target manually before cutover."
            if row["capability_confidence"] == "low" else None)
    return rows


def build_plan(profile: dict, prefs: dict) -> dict:
    if (prefs.get("metadata") or {}).get("migration_type") != "ai-only":
        raise DesignInputError("preferences_not_ai_only", "preferences.json metadata.migration_type must be \"ai-only\"")
    rows = _rows(profile)
    for row in rows:
        requests = _requests_for(row, prefs, profile)
        row["mantle_requests"] = requests
        row["mantle"] = _lane(row, requests)
    providers = {s["provider"] for s in profile["ai_sources"]}
    guides = [f"{GUIDE_DIR}/{g}" for g in ALWAYS_GUIDES]
    for provider in ("openai", "google"):
        if provider in providers:
            guides += [f"{GUIDE_DIR}/{g}" for g in PROVIDER_GUIDES[provider]]
    if "openai" in providers:
        guides.append("references/shared/openai-on-bedrock.md")
    if any(g["product"] == "openrouter" for g in profile["gateways"]):
        guides.append(f"{GUIDE_DIR}/ai-openrouter-to-bedrock.md")
    constraints = {key: _constraint(prefs, "ai_constraints", key, default) for key, default in DEFAULTS.items()}
    constraints["compliance"] = _constraint(prefs, "design_constraints", "compliance", ["unknown"])
    constraints["target_region"] = _constraint(prefs, "design_constraints", "target_region", "us-east-1")
    volume = constraints["ai_token_volume"]["value"]
    return {
        "ok": True,
        "projection": {"ai_sources": profile["ai_sources"], "gateways": profile["gateways"]},
        "integration": profile.get("integration"),
        "agentic": "agentic_profile" in profile,
        "guides": guides,
        "constraints": constraints,
        "tiered_strategy_required": volume in HIGH_VOLUMES,
        "quota_risk_floor": "high" if volume in HIGH_VOLUMES else None,
        "rows": rows,
        "not_designed": [{"provider": s["provider"], "source_service": s["source_service"], "reason": "model not observed"}
                         for s in profile["ai_sources"] if s["model_evidence"] == "not_observed"],
    }


def _err(errors: list, code: str, detail: str) -> None:
    errors.append({"code": code, "detail": detail})


def _check_row_shape(row: dict, label: str, errors: list) -> None:
    for key in ROW_KEYS:
        if key not in row:
            _err(errors, "row_missing_field", f"{label}: missing {key}")
    if row.get("honest_assessment") not in ASSESSMENTS:
        _err(errors, "row_bad_assessment", f"{label}: honest_assessment {row.get('honest_assessment')!r}")
    if row.get("quota_risk") not in QUOTA_RISKS:
        _err(errors, "row_bad_quota_risk", f"{label}: quota_risk {row.get('quota_risk')!r}")
    if not isinstance(row.get("model_change"), bool):
        _err(errors, "row_bad_model_change", f"{label}: model_change must be a boolean")
    for key in ("capabilities_matched", "capability_gaps"):
        if not isinstance(row.get(key), list):
            _err(errors, "row_bad_list", f"{label}: {key} must be a list")
    path, api = row.get("migration_path"), row.get("required_client_api")
    if path not in PATH_CLIENT_APIS:
        _err(errors, "row_bad_migration_path", f"{label}: migration_path {path!r}")
    elif api not in PATH_CLIENT_APIS[path] or api not in CLIENT_APIS:
        _err(errors, "row_client_api_mismatch", f"{label}: {path} cannot use required_client_api {api!r}")
    model = str(row.get("aws_model_id", ""))
    if path and not str(path).startswith("mantle_") and re.match(r"^openai\.gpt-(?!oss)", model):
        _err(errors, "bare_gpt_id_on_runtime", f"{label}: a bare {model} id is a Mantle id; bedrock-runtime needs a CRIS profile id")


def check_design(design: Any, profile: dict, prefs: dict, schema: dict | None = None) -> dict:
    errors: list[dict] = []
    schema = schema if schema is not None else json.loads(DESIGN_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(design, dict):
        return {"ok": False, "errors": [{"code": "not_an_object", "detail": "aws-design-ai.json must be a JSON object"}]}
    for message in validator._schema_errors(schema, design, schema):
        _err(errors, "schema_violation", message)
    if errors:
        return {"ok": False, "errors": errors}
    if "halt" in design:
        return {"ok": False, "errors": [{"code": "halted", "detail": json.dumps(design["halt"])}]}
    plan = build_plan(profile, prefs)
    rows = plan["rows"]
    if not rows:
        _err(errors, "nothing_to_design", "no observed model; write halt instead of an empty design")
    meta = design["metadata"]
    if meta["ai_sources"] != profile["ai_sources"] or meta["gateways"] != profile["gateways"]:
        _err(errors, "projection_mismatch", "metadata.ai_sources and metadata.gateways must equal the profile's verbatim")

    blocks = design["design_blocks"]
    if [b["workload_id"] for b in blocks] != [r["workload_id"] for r in rows]:
        _err(errors, "design_blocks_mismatch", f"design_blocks must list {[r['workload_id'] for r in rows]} in that order")
        return {"ok": False, "errors": errors}
    for block, row in zip(blocks, rows):
        label = block["workload_id"]
        for key in ("model_id", "capability", "capability_confidence"):
            if block[key] != row[key]:
                _err(errors, "design_block_field", f"{label}: {key} is {block[key]!r}, expected {row[key]!r}")
        if (block["confidence_warning"] is None) != (row["capability_confidence"] != "low"):
            _err(errors, "confidence_warning", f"{label}: confidence_warning must be set iff capability_confidence is low")
        service = SPEECH_SERVICES.get(row["capability"])
        if block["target_aws_service"] is not None and block["target_aws_service"] != service:
            _err(errors, "target_aws_service", f"{label}: {row['capability']} targets a Bedrock model"
                 + (f" or {service}" if service else ""))

    targets = [b["target_bedrock_model"] for b in blocks if b["target_bedrock_model"]]
    if sorted(set(meta["bedrock_models_selected"])) != sorted(set(targets)) or len(set(meta["bedrock_models_selected"])) != len(meta["bedrock_models_selected"]):
        _err(errors, "models_selected_mismatch", "metadata.bedrock_models_selected must list each design_blocks target once")

    arch = design["ai_architecture"]
    bedrock_rows = arch.get("bedrock_models")
    if not isinstance(bedrock_rows, list) or (targets and not bedrock_rows):
        _err(errors, "no_bedrock_models", "ai_architecture.bedrock_models must list one row per source model and target")
        return {"ok": False, "errors": errors}
    by_key: dict[tuple[str, str], list[dict]] = {}
    for row in bedrock_rows:
        label = f"{row.get('source_model_id')}->{row.get('aws_model_id')}"
        _check_row_shape(row, label, errors)
        key = (row.get("source_model_id"), row.get("aws_model_id"))
        lanes = [str(r.get("migration_path", "")).startswith("mantle_") for r in by_key.get(key, [])]
        if str(row.get("migration_path", "")).startswith("mantle_") in lanes:
            _err(errors, "duplicate_row", f"{label}: one Mantle row and one non-Mantle row at most per source model and target")
        by_key.setdefault(key, []).append(row)
    assigned: dict[int, list[str]] = {}
    pairs = []
    for block, plan_row in zip(blocks, rows):
        if block["target_bedrock_model"] is None:
            continue
        row = _row_for(plan_row, by_key.get((block["model_id"], block["target_bedrock_model"]), []))
        if row is None:
            _err(errors, "block_without_row", f"{block['workload_id']}: no bedrock_models row for {block['model_id']} -> {block['target_bedrock_model']}")
            continue
        assigned.setdefault(id(row), []).append(block["workload_id"])
        pairs.append((block, plan_row, row))
    for block, plan_row, row in pairs:
        _check_endpoint(block, plan_row, row, assigned[id(row)], design, errors)
    for row in bedrock_rows:
        if id(row) not in assigned:
            _err(errors, "row_without_block", f"{row.get('source_model_id')}->{row.get('aws_model_id')}: no design_blocks row uses this row")

    order = [ASSESSMENTS.index(r["honest_assessment"]) for r in bedrock_rows if r.get("honest_assessment") in ASSESSMENTS]
    overall = arch.get("honest_assessment")
    if order and overall != ASSESSMENTS[max(order)]:
        _err(errors, "overall_assessment", f"honest_assessment must be the weakest row value, {ASSESSMENTS[max(order)]}")
    reason = arch.get("honest_assessment_reason")
    if (overall == "recommend_stay") != isinstance(reason, str) or (isinstance(reason, str) and not reason.strip()):
        _err(errors, "assessment_reason", "honest_assessment_reason is a non-cost blocker for recommend_stay and null otherwise")
    tiered = arch.get("tiered_strategy")
    if plan["tiered_strategy_required"] != isinstance(tiered, dict):
        _err(errors, "tiered_strategy", f"tiered_strategy must be {'an object' if plan['tiered_strategy_required'] else 'null'} for this token volume")
    if plan["quota_risk_floor"]:
        for row in bedrock_rows:
            if row.get("quota_risk") != "high":
                _err(errors, "quota_risk_floor", f"{row.get('aws_model_id')}: a high monthly token volume sets quota_risk high")

    integration = profile.get("integration")
    mapping = arch.get("capability_mapping")
    if not isinstance(mapping, dict):
        _err(errors, "capability_mapping", "capability_mapping must be an object")
    elif integration:
        for cap, used_flag in integration["capabilities_summary"].items():
            entry = mapping.get(cap)
            if used_flag and (not isinstance(entry, dict) or entry.get("parity") not in ("full", "partial", "none")
                              or not isinstance(entry.get("notes"), str)):
                _err(errors, "capability_mapping", f"{cap}: needs {{parity: full|partial|none, notes}}")
    migration = arch.get("code_migration")
    if not isinstance(migration, dict) or not isinstance(migration.get("files_to_modify"), list):
        _err(errors, "code_migration", "code_migration needs primary_pattern, framework, files_to_modify[], dependency_changes")
    elif integration and migration.get("primary_pattern") != integration["pattern"]:
        _err(errors, "code_migration", f"primary_pattern must equal integration.pattern {integration['pattern']!r}")
    for key in ("infrastructure", "services_to_migrate"):
        if not isinstance(arch.get(key), list):
            _err(errors, "architecture_list", f"ai_architecture.{key} must be a list")

    for item in design["regional_warnings"]:
        if not isinstance(item, dict) or any(not isinstance(item.get(k), str) for k in ("service", "target_region", "nearest_available", "impact")):
            _err(errors, "regional_warning_shape", "each regional_warnings entry needs service, target_region, nearest_available, impact")
    types = set()
    for item in design["multi_model_warnings"]:
        if not isinstance(item, dict) or item.get("type") not in WARNING_TYPES or not isinstance(item.get("message"), str):
            _err(errors, "multi_model_warning_shape", f"multi_model_warnings entry {item!r}")
        else:
            types.add(item["type"])
    caps = {r["capability"] for r in rows}
    generative = caps & {"text_generation", "structured_output", "unknown"}
    required = set()
    if "embedding" in caps and generative:
        required.add("embeddings_reindex")
    if "image_generation" in caps and generative:
        required.add("image_separate")
    if caps & {"speech_to_text", "text_to_speech"}:
        required.add("speech_separate")
    if len({r["model_id"] for r in rows}) > 3:
        required.add("multi_model_tiered")
    for missing in sorted(required - types):
        _err(errors, "multi_model_warning_missing", f"multi_model_warnings needs a {missing} entry")

    agentic = design.get("agentic_design")
    if plan["agentic"]:
        if not isinstance(agentic, dict) or agentic.get("migration_approach") not in AGENTIC_APPROACHES:
            _err(errors, "agentic_design", "agents were detected: agentic_design needs migration_approach")
    elif agentic is not None:
        _err(errors, "agentic_design", "no agents were detected: agentic_design must be null or absent")

    if "gdpr" in (plan["constraints"]["compliance"]["value"] or []):
        for row in bedrock_rows:
            if GDPR_FORBIDDEN_PREFIX.match(str(row.get("aws_model_id", ""))):
                _err(errors, "gdpr_profile", f"{row.get('aws_model_id')}: GDPR allows only eu. profiles or in-Region ids")
    if "App Runner" in json.dumps(design):
        _err(errors, "app_runner", "\"App Runner\" must not appear in the design")
    return {"ok": not errors, "errors": errors} if errors else {"ok": True, "bedrock_models": len(bedrock_rows), "design_blocks": len(blocks)}


def _mantle_paths(provider: str, selector: str) -> set[str]:
    return {MANTLE_PATH[a] for a in SELECTOR_APIS.get(selector, set()) & PROVIDER_APIS.get(provider, set())}


def _row_for(plan_row: dict, candidates: list[dict]) -> dict | None:
    if len(candidates) < 2:
        return candidates[0] if candidates else None
    mantle = next(r for r in candidates if str(r.get("migration_path", "")).startswith("mantle_"))
    runtime = next(r for r in candidates if r is not mantle)
    return mantle if mantle.get("mantle_requirement") in plan_row["mantle_requests"] else runtime


def _check_endpoint(block: dict, plan_row: dict, row: dict, row_workloads: list[str], design: dict, errors: list) -> None:
    label = block["workload_id"]
    requests = plan_row["mantle_requests"]
    path = str(row.get("migration_path", ""))
    if path.startswith("mantle_"):
        selector, req = row.get("mantle_selector"), row.get("mantle_requirement")
        if "endpoint_assumption" in row:
            _err(errors, "mantle_row_assumption", f"{label}: a Mantle row carries no endpoint_assumption")
        if selector not in MANTLE_SELECTORS or not isinstance(req, dict) or req.get("selector") != selector:
            _err(errors, "mantle_selector", f"{label}: a Mantle row needs mantle_selector and a mantle_requirement with the same selector")
            return
        if set(req) - {"workload_id", "selector", "source", "evidence", "region"}:
            _err(errors, "mantle_requirement_keys", f"{label}: unknown mantle_requirement keys {sorted(set(req) - {'workload_id', 'selector', 'source', 'evidence', 'region'})}")
        if ("region" in req) != (selector == "in_region_processing"):
            _err(errors, "mantle_requirement_region", f"{label}: region is present iff the selector is in_region_processing")
        if (req.get("source") == "catalog") != (selector == "mantle_only_model_or_api"):
            _err(errors, "mantle_requirement_source", f"{label}: source catalog iff the selector is mantle_only_model_or_api")
        if req.get("source") == "catalog":
            if not req.get("evidence"):
                _err(errors, "mantle_requirement_evidence", f"{label}: a catalog requirement names the catalog row as evidence")
        elif req not in requests:
            _err(errors, "mantle_requirement_unrecorded", f"{label}: mantle_requirement must copy a Clarify mantle_requirements entry for this workload")
        elif path not in _mantle_paths(plan_row["provider"], selector):
            _err(errors, "mantle_path_api", f"{label}: {path} cannot serve {selector} for a {plan_row['provider']} model")
        return
    if "mantle_selector" in row or "mantle_requirement" in row:
        _err(errors, "runtime_row_selector", f"{label}: a non-Mantle row carries no mantle_selector or mantle_requirement")
    expected = ASSUMPTION.format(ids=", ".join(row_workloads))
    if row.get("endpoint_assumption") != expected:
        _err(errors, "endpoint_assumption", f"{label}: endpoint_assumption must be exactly: {expected}")
    gaps = " ".join(str(g) for g in row.get("capability_gaps") or [])
    for req in requests:
        if req["selector"] == "in_region_processing":
            if CRIS_PREFIX.match(str(row.get("aws_model_id", ""))) and not design["regional_warnings"]:
                _err(errors, "in_region_unhonored", f"{label}: in_region_processing on a CRIS id needs a regional_warnings entry")
        elif req["selector"] not in gaps:
            _err(errors, "selector_not_disclosed", f"{label}: the recorded {req['selector']} requirement stays on bedrock-runtime; name it in capability_gaps")


def _read_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise DesignInputError(f"{code}_not_found", str(path))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise DesignInputError(f"{code}_unreadable", f"{path}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "check"))
    parser.add_argument("run_dir", type=Path, help="the $MIGRATION_DIR holding ai-workload-profile.json and preferences.json")
    args = parser.parse_args(argv)
    try:
        profile = _read_json(args.run_dir / "ai-workload-profile.json", "profile")
        validator.validate_profile(profile)
        prefs = _read_json(args.run_dir / "preferences.json", "preferences")
        if not isinstance(prefs, dict):
            raise DesignInputError("preferences_unreadable", "preferences.json must be a JSON object")
        if args.command == "plan":
            result = build_plan(profile, prefs)
        else:
            result = check_design(_read_json(args.run_dir / "aws-design-ai.json", "design"), profile, prefs)
    except validator.ProfileRejected as exc:
        result = {"ok": False, "error": f"profile_{exc.code}", "detail": exc.detail}
    except DesignInputError as exc:
        result = {"ok": False, "error": exc.code, "detail": exc.detail}
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
