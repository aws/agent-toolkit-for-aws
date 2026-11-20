#!/usr/bin/env python3
"""Plan, scaffold and check the Generate phase of bedrock-migration-assessment: generation-ai.json and the ai-migration/ artifacts."""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import math
import re
import shlex
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    written = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # no __pycache__ inside references/vendored/, which the parity gate scans
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = written
    return module


readiness = _load("bma_generate_readiness", HERE / "readiness.py")
design_ai = readiness.design_ai
estimate_ai = readiness.estimate_ai
validator = design_ai.validator
iam_policy = _load("bma_generate_iam_policy", SKILL_ROOT / "references" / "vendored" / "ai" / "iam_policy.py")

SCHEMA_PATH = SKILL_ROOT / "references" / "contracts" / "generation-ai.schema.json"
OUT = "ai-migration"
SHARED_FILES = ("test_comparison.py", "setup_bedrock.sh", "iam-policy.json")
AGENT_FILES = ("README.md", "prompts.json")
# Files the generated harness or Python itself may leave in ai-migration/ after Generate.
TOLERATED_FILES = {"comparison_results.json"}
TOLERATED_DIRS = {"__pycache__"}
ACCOUNT_PLACEHOLDER = "ACCOUNT_ID"
REGION_RE = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
MIGRATION_ID_RE = re.compile(r"^bma-\d{4}-\d{4}$")
CONFIDENCE = ("low", "medium", "high")
PLACEHOLDER = "WRITE:"
DASHBOARDS = ["Requests by provider", "Latency P50/P95/P99", "Error rate", "Tokens", "Cost"]
# gcp-to-aws generate-artifacts-ai.md Step 3F: Bedrock budget is 1.5x the projected monthly figure, at least $10.
BUDGET_MULTIPLIER = 1.5
BUDGET_MINIMUM = 10
BEDROCK_SERVICE = "Amazon Bedrock"
# Claude model cards on Bedrock, "Pricing": billed through AWS Marketplace, shown under the model provider, not under Amazon Bedrock.
MARKETPLACE_NOTE = "billed through AWS Marketplace and shown in Cost Explorer under the model provider, not under Amazon Bedrock"
MAX_TOKENS = 1024
# The only InvokeModel body the scaffold writes: Titan Text Embeddings, {"inputText": ...} -> {"embedding": [...]}.
TITAN_TEXT_EMBEDDING = "amazon.titan-embed-text-"
OPENAI_COMPATIBLE = {"responses", "chat_completions"}
# Mantle selectors whose request options (background=, hosted tools) the generated prompt-only call does not send.
UNSENT_SELECTORS = {"background_inference", "server_side_tools"}
CLIENT_APIS = OPENAI_COMPATIBLE | {"messages"}
OPENAI_PATHS = {"runtime_openai_cris": "bedrock-runtime", "mantle_openai_responses": "bedrock-mantle",
                "mantle_openai_chat": "bedrock-mantle", "gpt-oss": "bedrock-runtime"}
MESSAGES_PATHS = {"runtime_messages": "bedrock-runtime", "mantle_messages": "bedrock-mantle"}
SECRET_RE = re.compile(r"(sk-ant-[A-Za-z0-9_-]{8,}|\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}|\bAKIA[0-9A-Z]{16}\b|\bABSK[A-Za-z0-9+/=]{16,})")
DOTENV_RE = re.compile(r"load_dotenv|dotenv\.|open\([^)]*\.env|\bsource\s+\S*\.env|cat\s+\S*\.env")
SOURCE_DEFAULT_RE = re.compile(r"AI_PROVIDER\s*[=:]\s*[\"'`]?(?:vertex_ai|azure_openai|openai|anthropic|gemini|google|openrouter)\b")

ROLLBACK_PLAN = {
    "mechanism": "feature_flag",
    "flag_name": "AI_PROVIDER",
    "default_value": "source",
    "rollback_time": "Immediate: set AI_PROVIDER=source and reload the service",
    "triggers": [
        "Response quality below 90% of the source baseline",
        "P95 latency above 2x the source baseline for 5 minutes",
        "Error rate above 1% for 5 minutes",
        "Cost per request above 3x the source",
    ],
}
ALERTING_RULES = [
    {"severity": "Critical", "condition": "Bedrock error rate above 5% for 2 minutes", "action": "Set AI_PROVIDER=source"},
    {"severity": "High", "condition": "Bedrock P95 latency above 3x the source baseline for 5 minutes", "action": "Investigate; set AI_PROVIDER=source if it persists"},
    {"severity": "High", "condition": "Response quality below 90% of the source score", "action": "Set AI_PROVIDER=source and review prompts"},
    {"severity": "Medium", "condition": "Daily Bedrock cost above 2x the projected daily cost", "action": "Review token usage and the AWS Budgets alert"},
    {"severity": "Low", "condition": "Token usage above 120% of the estimate", "action": "Review the estimate and quotas"},
]
SUCCESS_CRITERIA = {
    "quality": {"response_quality": ">= 90% of the source baseline", "capability_coverage": "100% of the workloads in ai-workload-profile.json"},
    "latency": {"p50": "within 1.5x of the source", "p95": "within 2x of the source"},
    "cost": {"monthly": "within 20% of estimation-ai.json", "per_request": "within 30% of the source per request"},
}
CREDITS = {"has_credits": "AWS Activate credits on your account can apply to Bedrock usage; confirm they are active before you move traffic.",
           None: "AWS Activate credits can offset Bedrock usage for eligible startups: https://aws.amazon.com/startups/credits/"}


class GenerateInputError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _escape(value: str) -> str:
    out = []
    for i, ch in enumerate(value):
        if ch.isascii() and (ch.islower() or ch.isdigit() or (ch in ".-" and i > 0)):
            out.append(ch)
        elif ord(ch) < 256:
            out.append(f"_{ord(ch):02x}")
        else:
            out.append(f"_u{ord(ch):06x}")
    return "".join(out)


def route_ids(keys: list[tuple[str, str, str, str]]) -> list[str]:
    """One file-safe id per route: an escaped source model, then the Design vocabulary for path, API and selector."""
    # An escaped part never holds "__" ("_" is always followed by a hex digit or "u"), so the join is injective.
    bases = ["__".join([_escape(model)] + [p.replace("_", "-") for p in (path, api, selector) if p]) for model, path, api, selector in keys]
    seen: dict[str, int] = {}
    out = []
    for base in bases:
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base}__{seen[base]}")
    return out


def route_kind(client_api: str, gateways: list[str], openrouter_path: str | None) -> str:
    """First match wins: a kept gateway, then a client the source SDK keeps, then an adapter to a new API."""
    if gateways and (set(gateways) - {"openrouter"} or openrouter_path in ("litellm", "keep_openrouter")):
        return "gateway_config"
    if client_api in CLIENT_APIS:
        return "client_config"
    return "provider_adapter"


def endpoint(path: str, client_api: str, region: str) -> tuple[str, str | None, str]:
    """(service, base URL or None, credential) for a design row."""
    if client_api in OPENAI_COMPATIBLE and path in OPENAI_PATHS:
        service, base = OPENAI_PATHS[path], "/openai/v1"
    elif client_api == "messages" and path in MESSAGES_PATHS:
        service, base = MESSAGES_PATHS[path], "/anthropic"
    else:
        return "bedrock-runtime", None, "sigv4"
    host = f"bedrock-runtime.{region}.amazonaws.com" if service == "bedrock-runtime" else f"bedrock-mantle.{region}.api.aws"
    return service, f"https://{host}{base}", "bedrock_token"


def billing(model_id: str) -> str:
    vendor = design_ai.CRIS_PREFIX.sub("", model_id.rsplit("/", 1)[-1]).split(".", 1)[0]
    if vendor == "amazon":
        return "amazon_bedrock"
    return "marketplace" if vendor == "anthropic" else "unconfirmed"


def budget(figures: dict, routes: list[dict]) -> dict:
    services = None if any(r["billing"] == "marketplace" for r in routes) else [BEDROCK_SERVICE]
    point = figures["cost_comparison"]["projected_bedrock_monthly"]
    span = figures["projected_bedrock_monthly_range"]
    for basis, value in (("point", point), ("range_high", span.get("high")), ("range_low_open_band", span.get("low"))):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return {"monthly_usd": max(BUDGET_MINIMUM, math.ceil(round(value * BUDGET_MULTIPLIER, 6))), "basis": basis, "projected": value,
                    "services": services}
    return {"monthly_usd": None, "basis": "no_projection", "projected": None, "services": services}


def _policy(routes: list[dict], region: str) -> dict:
    lane = [r for r in routes if r["migration_path"] != "mantle_messages"]
    pairs = [(r["aws_model_id"], r["required_client_api"]) for r in lane]
    selectors = sorted({r["mantle_selector"] for r in lane if r["mantle_selector"]})
    try:
        policy = iam_policy.generate_policy([m for m, _ in pairs], region, ACCOUNT_PLACEHOLDER, target_apis=iam_policy.target_apis_by_id(pairs),
                                            mantle_selectors=selectors) if pairs else {"Version": "2012-10-17", "Statement": []}
    except ValueError as exc:
        raise GenerateInputError("iam_unsupported", str(exc))
    sids = {s["Sid"] for s in policy["Statement"]}
    if len(lane) < len(routes) and "BedrockMantleInference" not in sids:
        # iam_policy.py refuses mantle_messages; the bare Claude id there is a bedrock-mantle /anthropic target.
        policy["Statement"] += [
            {"Sid": "BedrockMantleInference", "Effect": "Allow", "Action": ["bedrock-mantle:CreateInference", "bedrock-mantle:Get*", "bedrock-mantle:List*"],
             "Resource": iam_policy.mantle_project_arn(region, ACCOUNT_PLACEHOLDER)},
            {"Sid": "BedrockMantleCallWithBearerToken", "Effect": "Allow", "Action": ["bedrock-mantle:CallWithBearerToken"], "Resource": "*"}]
    return policy


def user_files(routes: list[dict]) -> list[str]:
    return sorted(f"{OUT}/invoke/{r['route_id']}.py" for r in routes if r["required_client_api"] == "invoke" and not r["titan_embedding"])


def _read(run_dir: Path, name: str) -> Any:
    try:
        return json.loads((run_dir / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GenerateInputError("artifact_unreadable", f"{name}: {exc}")


def build_plan(run_dir: Path) -> dict:
    try:
        status = readiness._status(run_dir)
        readiness.refuse_combined(run_dir, status["migration_id"], status.get("initiated_by"))
        ready = readiness.check(run_dir, "estimate")
    except readiness.NotReady as exc:
        raise GenerateInputError(exc.reason, exc.detail)
    if not MIGRATION_ID_RE.match(ready["migration_id"]):
        raise GenerateInputError("status_invalid", f"migration_id {ready['migration_id']!r} is not bma-MMDD-HHMM")
    profile, prefs = _read(run_dir, "ai-workload-profile.json"), _read(run_dir, "preferences.json")
    design = _read(run_dir, "aws-design-ai.json")
    figures = estimate_ai.figures_for(run_dir)
    estimate = _read(run_dir, "estimation-ai.json")
    design_plan = design_ai.build_plan(profile, prefs)
    region = design_plan["constraints"]["target_region"]["value"]
    if not isinstance(region, str) or not REGION_RE.match(region):
        raise GenerateInputError("region_invalid", f"target_region {region!r} is not an AWS Region name; re-run Clarify")
    arch = design["ai_architecture"]
    migration = arch["code_migration"]
    rows = arch["bedrock_models"]
    by_key: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        by_key.setdefault((row["source_model_id"], row["aws_model_id"]), []).append(row)
    served: dict[int, list[dict]] = {}
    not_generated = []
    for block, plan_row in zip(design["design_blocks"], design_plan["rows"]):
        if block["target_bedrock_model"] is None:
            not_generated.append({"workload_id": block["workload_id"], "target_aws_service": block["target_aws_service"],
                                  "reason": "not a Bedrock model; set up that service separately"})
            continue
        row = design_ai._row_for(block["workload_id"], plan_row, by_key[(block["model_id"], block["target_bedrock_model"])])
        served.setdefault(id(row), []).append(plan_row)

    if not rows:
        raise GenerateInputError("no_bedrock_routes", "the design has no Bedrock model row; Generate covers Bedrock models only")
    keys = [(r["source_model_id"], r["migration_path"], r["required_client_api"], r.get("mantle_selector") or "") for r in rows]
    disclosures = []
    routes = []
    for row, rid in zip(rows, route_ids(keys)):
        workloads = served.get(id(row), [])
        mid = row["aws_model_id"]
        if not MODEL_ID_RE.match(mid):
            raise GenerateInputError("model_id_invalid", f"aws_model_id {mid!r} is not a Bedrock model id; re-run Design")
        requirement = row.get("mantle_requirement")
        row_region = requirement.get("region") if isinstance(requirement, dict) and requirement.get("region") else region
        if not REGION_RE.match(str(row_region)):
            raise GenerateInputError("region_invalid", f"mantle_requirement.region {row_region!r} is not an AWS Region name")
        service, base_url, credential = endpoint(row["migration_path"], row["required_client_api"], row_region)
        gateways = sorted({g for w in workloads for g in w["fronted_by"]})
        openrouter_path = migration.get("openrouter_path") if "openrouter" in gateways else None
        if "openrouter" in gateways and openrouter_path is None:
            disclosures.append(f"{rid}: Design recorded no code_migration.openrouter_path; the route follows the row's API.")
        kind = route_kind(row["required_client_api"], gateways, openrouter_path)
        sources = sorted({(w["source_service"], w["source_api"] or "") for w in workloads})
        titan_embedding = design_ai.CRIS_PREFIX.sub("", mid).startswith(TITAN_TEXT_EMBEDDING)
        if row["required_client_api"] == "invoke" and not titan_embedding:
            disclosures.append(f"{rid}: {mid} uses a model-specific InvokeModel body; call_bedrock raises until you write "
                               f"invoke(client, model_id, prompt) in {OUT}/invoke/{rid}.py.")
        if row.get("mantle_selector") == "web_search":
            disclosures.append(f"{rid}: call_bedrock sends the web_search tool with \"external_web_access\": false; "
                               "keep it false unless you grant bedrock-websearch:ExternalWebAccess.")
        if row.get("mantle_selector") in UNSENT_SELECTORS:
            disclosures.append(f"{rid}: call_bedrock does not send the {row['mantle_selector']} request options, so test_comparison.py "
                               "does not exercise them; your own call keeps them when it moves to this endpoint.")
        files = [f"{OUT}/routes/{rid}.py"]
        if kind == "gateway_config":
            files.append(f"{OUT}/gateway/{rid}.{'yaml' if 'litellm' in gateways or openrouter_path == 'litellm' else 'json'}")
        routes.append({
            "route_id": rid, "kind": kind, "workload_ids": [w["workload_id"] for w in workloads],
            "sources": [{"provider": w["provider"], "source_service": w["source_service"]} for w in workloads],
            "source_model_id": row["source_model_id"], "aws_model_id": mid, "migration_path": row["migration_path"],
            "required_client_api": row["required_client_api"], "endpoint": service, "region": row_region, "base_url": base_url,
            "credential": credential, "mantle_selector": row.get("mantle_selector"), "mantle_requirement": requirement,
            "endpoint_assumption": row.get("endpoint_assumption"), "fronted_by": gateways, "openrouter_path": openrouter_path,
            "call_sites": sorted({(c["file"], c["line"]) for w in workloads for c in w["call_sites"]}),
            "source_call": sources[0] if len(sources) == 1 and sources[0][1] and not gateways else None,
            "titan_embedding": titan_embedding, "billing": billing(mid), "quota_risk": row["quota_risk"], "files": files})

    no_baseline = [r["route_id"] for r in routes if source_body(r) is NO_SOURCE]
    if no_baseline:
        disclosures.append(f"{', '.join(no_baseline)}: no generated source caller, so the full test_comparison.py run reports these routes "
                           "INCOMPLETE. --target-only checks Bedrock alone; AI_PROVIDER=shadow logs Bedrock latency to set beside your source metrics.")
    shared = [f"{OUT}/{f}" for f in SHARED_FILES]
    agent = [f"{OUT}/{f}" for f in AGENT_FILES]
    pair_of = {w["workload_id"]: (w["provider"], w["source_service"]) for w in design_plan["rows"]}
    artifacts = []
    for entry in figures["cost_by_source"]:
        pair = (entry["provider"], entry["source_service"])
        models = []
        for m in entry["models"]:
            own = [f for r in routes if r["source_model_id"] == m["model"] and any(pair_of[w] == pair for w in r["workload_ids"]) for f in r["files"]]
            models.append({"model": m["model"], "generated_files": sorted(set(own + shared + agent))})
        artifacts.append({"provider": pair[0], "source_service": pair[1], "models": models})

    money = budget(figures, routes)
    marketplace = sorted({r["aws_model_id"] for r in routes if r["billing"] == "marketplace"})
    unconfirmed = sorted({r["aws_model_id"] for r in routes if r["billing"] == "unconfirmed"})
    if marketplace:
        disclosures.append(f"{', '.join(marketplace)}: {MARKETPLACE_NOTE}, so a budget on the Amazon Bedrock service would not see this spend. "
                           "setup_bedrock.sh creates no budget until you export BUDGET_SERVICES with the service names Cost Explorer shows.")
    if unconfirmed:
        disclosures.append(f"{', '.join(unconfirmed)}: not confirmed to bill under Amazon Bedrock. After the first day of traffic, check Cost Explorer "
                           "grouped by Service; if the spend is elsewhere, export BUDGET_SERVICES with those names and run setup_bedrock.sh again.")
    if money["basis"] == "range_low_open_band":
        disclosures.append("The token band has no upper bound, so the Bedrock budget uses the band's low bound; raise it to your expected volume.")
    if money["basis"] == "no_projection":
        disclosures.append("Estimate has no projected Bedrock figure, so setup_bedrock.sh creates no budget until you export BUDGET_USD.")
    disclosures.append("Generate does not scan code: if the app keeps client.responses.retrieve/cancel/delete on a runtime Responses route, "
                       "add bedrock:GetInvoke/CancelInvoke/DeleteInvoke on project/default (iam_policy.py --stored-response-ops).")
    integration = profile.get("integration") or {}
    compliance = [c for c in design_plan["constraints"]["compliance"]["value"] or [] if c not in ("none", "unknown")]
    status_value = ((prefs.get("startup_constraints") or {}).get("startup_program_status") or {}).get("value")
    status_value = status_value if isinstance(status_value, str) else None
    return {
        "ok": True,
        "migration_id": ready["migration_id"],
        "region": region,
        "routes": routes,
        "not_generated": not_generated,
        "manifest": {"scaffold": sorted({f for r in routes for f in r["files"]} | set(shared)), "agent": agent, "user": user_files(routes)},
        "fixed": {
            "models_to_migrate": list(dict.fromkeys(r["source_model_id"] for r in rows)),
            "artifacts_by_source": artifacts,
            "step_by_step_guide": {"languages": list(integration.get("languages", [])), "primary_pattern": migration["primary_pattern"],
                                   "files_to_modify": list(migration["files_to_modify"])},
            "rollback_plan": ROLLBACK_PLAN,
            "alerting_rules": ALERTING_RULES,
            "success_criteria": SUCCESS_CRITERIA,
        },
        "confidence_ceiling": estimate["recommendation"]["confidence"],
        "budget": money,
        "iam_policy": _policy(routes, region),
        "quota_flags": [{"route_id": r["route_id"], "aws_model_id": r["aws_model_id"], "quota_risk": r["quota_risk"]}
                        for r in routes if r["quota_risk"] in ("high", "medium")],
        "compliance": compliance,
        "capabilities": integration.get("capabilities_summary"),
        "agentic": design.get("agentic_design") is not None,
        "credits_line": CREDITS.get(status_value, CREDITS[None]),
        "disclosures": disclosures,
    }


# --------------------------------------------------------------------------- rendering

ROUTE_HEAD = '''"""Bedrock client for one route of the migration plan. Generated by bedrock-migration-assessment; regenerate it instead of editing."""
import json
import logging
import os
import time

'''

CALL_BEDROCK = {
    "responses": '''def call_bedrock(prompt: str) -> str:
    return _openai_client().responses.create(model=MODEL_ID, input=prompt).output_text
''',
    "responses_web_search": '''def call_bedrock(prompt: str) -> str:
    # No bedrock-websearch:ExternalWebAccess in iam-policy.json, so Fetch must stay on the cache.
    tools = [{"type": "web_search", "external_web_access": False}]
    return _openai_client().responses.create(model=MODEL_ID, input=prompt, tools=tools).output_text
''',
    "chat_completions": '''def call_bedrock(prompt: str) -> str:
    response = _openai_client().chat.completions.create(model=MODEL_ID, messages=[{"role": "user", "content": prompt}])
    return response.choices[0].message.content
''',
    "messages": '''def call_bedrock(prompt: str) -> str:
    from anthropic import Anthropic
    from aws_bedrock_token_generator import provide_token
    client = Anthropic(base_url=BASE_URL, api_key=provide_token(region=REGION), max_retries=2)
    response = client.messages.create(model=MODEL_ID, max_tokens=MAX_TOKENS, messages=[{"role": "user", "content": prompt}])
    return "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
''',
    "converse": '''def call_bedrock(prompt: str) -> str:
    import boto3
    response = boto3.client("bedrock-runtime", region_name=REGION).converse(
        modelId=MODEL_ID, messages=[{"role": "user", "content": [{"text": prompt}]}], inferenceConfig={"maxTokens": MAX_TOKENS})
    return "".join(block.get("text", "") for block in response["output"]["message"]["content"])
''',
    "invoke_embedding": '''def call_bedrock(prompt: str) -> str:
    import boto3
    response = boto3.client("bedrock-runtime", region_name=REGION).invoke_model(modelId=MODEL_ID, body=json.dumps({"inputText": prompt}))
    return f"embedding:{len(json.loads(response['body'].read())['embedding'])}"
''',
    "invoke": '''def call_bedrock(prompt: str) -> str:
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "invoke", ROUTE_ID + ".py")
    if not os.path.isfile(path):
        raise NotImplementedError(f"This route needs a model-specific InvokeModel body: write invoke(client, model_id, prompt) -> str in {path} (see README.md).")
    import boto3
    spec = importlib.util.spec_from_file_location(f"invoke_{ROUTE_ID}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.invoke(boto3.client("bedrock-runtime", region_name=REGION), MODEL_ID, prompt)
''',
}

OPENAI_CLIENT = '''def _openai_client():
    from aws_bedrock_token_generator import provide_token
    from openai import Omit, OpenAI
    # OPENAI_ORG_ID and OPENAI_PROJECT_ID would otherwise send the source account's ids to Bedrock.
    return OpenAI(base_url=BASE_URL, api_key=provide_token(region=REGION), max_retries=2,
                  default_headers={"OpenAI-Organization": Omit(), "OpenAI-Project": Omit()})


'''

CALL_SOURCE = {
    ("openai_api", "responses"): '''def call_source(prompt: str) -> str:
    from openai import OpenAI
    return OpenAI().responses.create(model=SOURCE_MODEL, input=prompt).output_text
''',
    ("openai_api", "chat_completions"): '''def call_source(prompt: str) -> str:
    from openai import OpenAI
    response = OpenAI().chat.completions.create(model=SOURCE_MODEL, messages=[{"role": "user", "content": prompt}])
    return response.choices[0].message.content
''',
    ("openai_api", "embeddings"): '''def call_source(prompt: str) -> str:
    from openai import OpenAI
    return f"embedding:{len(OpenAI().embeddings.create(model=SOURCE_MODEL, input=prompt).data[0].embedding)}"
''',
    ("anthropic_api", "messages"): '''def call_source(prompt: str) -> str:
    from anthropic import Anthropic
    response = Anthropic().messages.create(model=SOURCE_MODEL, max_tokens=MAX_TOKENS, messages=[{"role": "user", "content": prompt}])
    return "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
''',
    ("gemini_api", "gemini"): '''def call_source(prompt: str) -> str:
    from google import genai
    return genai.Client().models.generate_content(model=SOURCE_MODEL, contents=prompt).text
''',
}
NO_SOURCE = '''def call_source(prompt: str) -> str:
    raise NotImplementedError("No baseline caller for this source; pass your existing call as generate(prompt, source_call=...) or use --target-only.")
'''

FLAG_SWITCH = '''def generate(prompt: str, source_call=None) -> str:
    """Route one call by AI_PROVIDER: source (default), bedrock, or shadow (both; the source answer is returned)."""
    mode = os.environ.get(FLAG, "source")
    if mode not in ("source", "bedrock", "shadow"):
        raise ValueError(f"{FLAG} must be source, bedrock or shadow, not {mode!r}")
    if mode == "bedrock":
        return call_bedrock(prompt)
    answer = (source_call or call_source)(prompt)
    if mode == "shadow":
        started = time.perf_counter()
        try:
            shadow = call_bedrock(prompt)
            log.info("shadow %s ok in %.0f ms, %d chars", ROUTE_ID, (time.perf_counter() - started) * 1000, len(shadow or ""))
        except Exception as exc:  # shadow traffic must never fail the source call
            log.warning("shadow %s failed: %s", ROUTE_ID, type(exc).__name__)
    return answer
'''


def source_body(route: dict) -> str:
    return CALL_SOURCE.get(tuple(route["source_call"]), NO_SOURCE) if route["source_call"] else NO_SOURCE


def render_route(route: dict) -> str:
    api = route["required_client_api"]
    if api == "invoke" and route["titan_embedding"]:
        body = CALL_BEDROCK["invoke_embedding"]
    elif api == "responses" and route["mantle_selector"] == "web_search":
        body = CALL_BEDROCK["responses_web_search"]
    else:
        body = CALL_BEDROCK[api]
    constants = [
        ("ROUTE_ID", route["route_id"]), ("WORKLOAD_IDS", tuple(route["workload_ids"])), ("CALL_SITES", tuple(route["call_sites"])),
        ("SOURCE_MODEL", route["source_model_id"]), ("REGION", route["region"]), ("MODEL_ID", route["aws_model_id"]),
        ("MIGRATION_PATH", route["migration_path"]), ("CLIENT_API", api), ("BASE_URL", route["base_url"]),
        ("ENDPOINT_NOTE", route["endpoint_assumption"] or json.dumps(route["mantle_requirement"], sort_keys=True)),
        ("MAX_TOKENS", MAX_TOKENS), ("FLAG", "AI_PROVIDER")]
    lines = [f"{name} = {value!r}" for name, value in constants]
    source = source_body(route)
    helper = OPENAI_CLIENT if api in OPENAI_COMPATIBLE else ""
    return ROUTE_HEAD + "\n".join(lines) + "\nlog = logging.getLogger(__name__)\n\n\n" + helper + body + "\n\n" + source + "\n\n" + FLAG_SWITCH


HARNESS = '''#!/usr/bin/env python3
"""Compare each Bedrock route with the current provider: latency, errors and expected traits. Generated by bedrock-migration-assessment."""
import argparse
import importlib.util
import json
import math
import statistics
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROUTES = __ROUTES__
QUICK_PROMPTS = [{"id": "quick", "prompt": "Reply with the single word: ok", "expected_traits": []}]
MAX_LATENCY_RATIO = 2.0
MIN_QUALITY = 0.9


def load_route(route_id):
    spec = importlib.util.spec_from_file_location(f"bma_route_{route_id}", HERE / ROUTES[route_id])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def timed(call, prompt):
    started = time.perf_counter()
    try:
        text = call(prompt)
    except NotImplementedError as exc:
        return {"ok": None, "ms": None, "error": str(exc)}
    except Exception as exc:  # one failed call is a result, not a crash
        return {"ok": False, "ms": round((time.perf_counter() - started) * 1000), "error": f"{type(exc).__name__}: {exc}"[:300]}
    return {"ok": True, "ms": round((time.perf_counter() - started) * 1000), "text": str(text)[:500]}


def quality(result, traits):
    if not traits or not result.get("ok"):
        return None
    text = result["text"].lower()
    return sum(trait.lower() in text for trait in traits) / len(traits)


def p95(values):
    return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)] if values else None


def summarize(rows, target_only):
    target = [r["bedrock"]["ms"] for r in rows if r["bedrock"]["ok"]]
    source = [r["source"]["ms"] for r in rows if r["source"] and r["source"]["ok"]]
    scores = [r["quality"] for r in rows if r["quality"] is not None]
    out = {"prompts": len(rows), "bedrock_errors": sum(r["bedrock"]["ok"] is not True for r in rows),
           "bedrock_p50_ms": statistics.median(target) if target else None, "bedrock_p95_ms": p95(target),
           "source_ok": len(source), "source_p95_ms": p95(source), "quality": round(statistics.mean(scores), 3) if scores else None}
    baseline = target_only or bool(source)
    out["passed"] = (baseline and out["bedrock_errors"] == 0 and (out["quality"] is None or out["quality"] >= MIN_QUALITY)
                     and (target_only or out["bedrock_p95_ms"] <= MAX_LATENCY_RATIO * out["source_p95_ms"]))
    if not baseline:
        out["incomplete"] = "no source call succeeded, so there is no baseline; fix the source credentials or run with --target-only"
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", type=Path, default=HERE / "prompts.json", help="JSON list of {id, prompt, expected_traits, route}")
    parser.add_argument("--quick", action="store_true", help="one built-in prompt per route")
    parser.add_argument("--target-only", action="store_true", help="call Bedrock only; needs no source credentials")
    parser.add_argument("--route", action="append", choices=sorted(ROUTES), help="limit to these routes")
    parser.add_argument("--output", type=Path, default=Path("comparison_results.json"))
    args = parser.parse_args(argv)
    prompts = QUICK_PROMPTS if args.quick else json.loads(args.prompts.read_text(encoding="utf-8"))
    report = {"routes": {}}
    for route_id in args.route or sorted(ROUTES):
        module = load_route(route_id)
        rows = []
        for item in prompts:
            if item.get("route") not in (None, route_id):
                continue
            bedrock = timed(module.call_bedrock, item["prompt"])
            source = None if args.target_only else timed(module.call_source, item["prompt"])
            rows.append({"id": item["id"], "bedrock": bedrock, "source": source, "quality": quality(bedrock, item.get("expected_traits", []))})
        report["routes"][route_id] = {"model_id": module.MODEL_ID, "client_api": module.CLIENT_API, "summary": summarize(rows, args.target_only), "results": rows}
    args.output.write_text(json.dumps(report, indent=2) + "\\n", encoding="utf-8")
    passed = all(r["summary"]["passed"] for r in report["routes"].values())
    for route_id, entry in report["routes"].items():
        verdict = "PASS" if entry["summary"]["passed"] else "INCOMPLETE" if "incomplete" in entry["summary"] else "FAIL"
        print(f"{verdict} {route_id} {json.dumps(entry['summary'])}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
'''


def render_harness(plan: dict) -> str:
    routes = {r["route_id"]: f"routes/{r['route_id']}.py" for r in plan["routes"]}
    return HARNESS.replace("__ROUTES__", repr(routes))


def _q(value: Any) -> str:
    return shlex.quote(str(value))


SETUP_HEAD = '''#!/usr/bin/env bash
# Bedrock setup for this migration plan. Generated by bedrock-migration-assessment. Dry run unless --execute.
set -euo pipefail
EXECUTE=0
ALERT_EMAIL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --execute) EXECUTE=1 ;;
    --alert-email) ALERT_EMAIL="${2:?--alert-email needs an address}"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done
if [ -n "$ALERT_EMAIL" ] && ! printf '%s' "$ALERT_EMAIL" | grep -Eq '^[^@[:space:]",]+@[^@[:space:]",]+$'; then
  echo "--alert-email is not an email address" >&2; exit 2
fi
HERE="$(cd "$(dirname "$0")" && pwd)"
run() {
  if [ "$EXECUTE" = 1 ]; then "$@"; else printf '[dry run]'; printf ' %q' "$@"; printf '\\n'; fi
}
'''

SETUP_BODY = '''
USD_RE='^([0-9]+(\\.[0-9]{1,2})?)?$'
SERVICES_RE='^[A-Za-z0-9 ()._,-]*$'
if ! [[ "$BUDGET_USD" =~ $USD_RE ]]; then
  echo "BUDGET_USD must be a USD amount such as 500 or 499.50" >&2; exit 2
fi
if [[ "$BUDGET_USD" =~ ^[0.]+$ ]]; then
  echo "BUDGET_USD must be above zero; a zero budget alerts at once" >&2; exit 2
fi
if ! [[ "$BUDGET_SERVICES" =~ $SERVICES_RE ]]; then
  echo "BUDGET_SERVICES must be comma-separated Cost Explorer service names (letters, digits, spaces, ( ) . _ -)" >&2; exit 2
fi
echo "== 1. Account and Region: $REGION"
ACCOUNT_ID="ACCOUNT_ID"
if [ "$EXECUTE" = 1 ]; then ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"; fi

echo "== 2. Models"
for i in "${!MODEL_IDS[@]}"; do
  echo "${MODEL_IDS[$i]} (${MODEL_KINDS[$i]})"
  case "${MODEL_KINDS[$i]}" in
    bedrock-mantle) echo "   bedrock-mantle has no CLI check; test_comparison.py --target-only --quick below calls it." ;;
    inference-profile) run aws bedrock get-inference-profile --region "$REGION" --inference-profile-identifier "${MODEL_IDS[$i]}" ;;
    *) run aws bedrock get-foundation-model --region "$REGION" --model-identifier "${MODEL_IDS[$i]}" ;;
  esac
done

echo "== 3. IAM policy (create it, then attach it to the role your application runs as)"
POLICY="$(sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" "$HERE/iam-policy.json")"
printf '%s\\n' "$POLICY"
POLICY_ARN="arn:$PARTITION:iam::$ACCOUNT_ID:policy/$POLICY_NAME"
if [ "$EXECUTE" = 1 ] && aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
  echo "   $POLICY_ARN already exists, so it is not created again. If iam-policy.json changed, add it with aws iam create-policy-version --set-as-default."
else
  run aws iam create-policy --policy-name "$POLICY_NAME" --policy-document "$POLICY"
fi
echo "   aws iam attach-role-policy --role-name <your-role> --policy-arn $POLICY_ARN"

echo "== 4. Environment for the application"
echo "   AWS_REGION=$REGION"
echo "   AI_PROVIDER=bedrock   (shadow compares both; rollback: AI_PROVIDER=source)"

echo "== 5. Quotas"
if [ "${#QUOTA_MODELS[@]}" -gt 0 ]; then
  echo "   WARNING: your token volume may exceed default Bedrock quotas for: ${QUOTA_MODELS[*]}"
  echo "   Request an increase in the Service Quotas console before cutover (allow 1-5 business days)."
  run aws service-quotas list-service-quotas --region "$REGION" --service-code bedrock --query "Quotas[?contains(QuotaName, 'tokens per minute')].[QuotaName,Value]" --output table
else
  echo "   Design rated quota risk low for every model."
fi

echo "== 6. Bedrock budget and cost anomaly monitor (detective controls, not spend caps; billing data lags up to 24 hours)"
if [ "${#MARKETPLACE_MODELS[@]}" -gt 0 ]; then
  for model in "${MARKETPLACE_MODELS[@]}"; do echo "   $model is $MARKETPLACE_NOTE."; done
fi
if [ "${#UNCONFIRMED_MODELS[@]}" -gt 0 ]; then
  for model in "${UNCONFIRMED_MODELS[@]}"; do
    echo "   $model is not confirmed to bill under Amazon Bedrock: after the first day of traffic, check Cost Explorer grouped by Service."
  done
fi
SERVICES_JSON="$(printf '%s' "$BUDGET_SERVICES" | sed 's/ *, */,/g; s/^ *//; s/ *$//; s/,,*/,/g; s/^,//; s/,$//')"
if [ -z "$BUDGET_USD" ]; then
  echo "   Estimate has no projected Bedrock cost, so no budget is created. Run again with: export BUDGET_USD=<monthly USD>"
elif [ -z "$SERVICES_JSON" ]; then
  echo "   No budget is created: a budget on the Amazon Bedrock service alone would not see the spend above."
  echo "   In Cost Explorer, group by Service and note the names that carry these models' charges, then run again with:"
  echo "   export BUDGET_SERVICES='Amazon Bedrock,<service name from Cost Explorer>'"
elif [ "$EXECUTE" = 1 ] && aws budgets describe-budget --account-id "$ACCOUNT_ID" --budget-name "$POLICY_NAME" >/dev/null 2>&1; then
  echo "   Budget $POLICY_NAME already exists; change it in the AWS Budgets console or with aws budgets update-budget."
else
  SERVICES_JSON="\\"${SERVICES_JSON//,/\\",\\"}\\""
  echo "   Budget: $BUDGET_USD USD a month on the services [$SERVICES_JSON]"
  BUDGET="{\\"BudgetName\\":\\"$POLICY_NAME\\",\\"BudgetLimit\\":{\\"Amount\\":\\"$BUDGET_USD\\",\\"Unit\\":\\"USD\\"},\\"TimeUnit\\":\\"MONTHLY\\",\\"BudgetType\\":\\"COST\\",\\"CostFilters\\":{\\"Service\\":[$SERVICES_JSON]}}"
  if [ -n "$ALERT_EMAIL" ]; then
    SUBSCRIBER="[{\\"SubscriptionType\\":\\"EMAIL\\",\\"Address\\":\\"$ALERT_EMAIL\\"}]"
    NOTIFY="[{\\"Notification\\":{\\"NotificationType\\":\\"ACTUAL\\",\\"ComparisonOperator\\":\\"GREATER_THAN\\",\\"Threshold\\":80,\\"ThresholdType\\":\\"PERCENTAGE\\"},\\"Subscribers\\":$SUBSCRIBER},{\\"Notification\\":{\\"NotificationType\\":\\"FORECASTED\\",\\"ComparisonOperator\\":\\"GREATER_THAN\\",\\"Threshold\\":100,\\"ThresholdType\\":\\"PERCENTAGE\\"},\\"Subscribers\\":$SUBSCRIBER}]"
    run aws budgets create-budget --account-id "$ACCOUNT_ID" --budget "$BUDGET" --notifications-with-subscribers "$NOTIFY"
  else
    echo "   No --alert-email given: the budget is created without notifications."
    run aws budgets create-budget --account-id "$ACCOUNT_ID" --budget "$BUDGET"
  fi
fi
MONITORS=0
if [ "$EXECUTE" = 1 ]; then
  MONITORS="$(aws ce get-anomaly-monitors --query "length(AnomalyMonitors[?MonitorDimension=='SERVICE'])" --output text)"
fi
MONITOR="{\\"MonitorName\\":\\"$POLICY_NAME\\",\\"MonitorType\\":\\"DIMENSIONAL\\",\\"MonitorDimension\\":\\"SERVICE\\"}"
if [ "$MONITORS" = 0 ]; then
  MONITOR_ARN="<monitor-arn>"
  if [ "$EXECUTE" = 1 ]; then
    MONITOR_ARN="$(aws ce create-anomaly-monitor --anomaly-monitor "$MONITOR" --query MonitorArn --output text)"
  else
    run aws ce create-anomaly-monitor --anomaly-monitor "$MONITOR"
  fi
  if [ -n "$ALERT_EMAIL" ]; then
    run aws ce create-anomaly-subscription --anomaly-subscription "{\\"SubscriptionName\\":\\"$POLICY_NAME\\",\\"MonitorArnList\\":[\\"$MONITOR_ARN\\"],\\"Subscribers\\":[{\\"Type\\":\\"EMAIL\\",\\"Address\\":\\"$ALERT_EMAIL\\"}],\\"Frequency\\":\\"DAILY\\",\\"ThresholdExpression\\":{\\"Dimensions\\":{\\"Key\\":\\"ANOMALY_TOTAL_IMPACT_PERCENTAGE\\",\\"Values\\":[\\"50\\"],\\"MatchOptions\\":[\\"GREATER_THAN_OR_EQUAL\\"]}}}"
  else
    echo "   No --alert-email given: the monitor records anomalies but notifies no one."
  fi
else
  echo "   A SERVICE anomaly monitor already exists and covers Amazon Bedrock; add a subscription to it if it has none."
fi
'''

SETUP_TAIL = '''
echo "== 8. Verify every route with the same API and model id the clients use"
run python3 "$HERE/test_comparison.py" --target-only --quick
if [ "$EXECUTE" != 1 ]; then echo "Dry run only. Re-run with --execute to make these calls."; fi
'''

COMPLIANCE_NOTES = {
    "hipaa": "HIPAA: Bedrock invocation logs keep the original content. KMS-encrypt and restrict the log group before you enable them.",
    "gdpr": "GDPR: keep every call in an EU Region with eu. inference profiles or in-Region ids.",
    "fedramp": "FedRAMP: run only in us-gov-east-1 or us-gov-west-1.",
    "pci": "PCI: tokenize cardholder data before it reaches a prompt, and keep CloudTrail on for Bedrock.",
    "soc2": "SOC 2: keep CloudTrail audit logging on for Bedrock calls.",
    "ccpa": "CCPA: set a retention policy and a deletion workflow for logged prompt content.",
}


def _model_kind(route: dict) -> str:
    if route["endpoint"] == "bedrock-mantle":
        return "bedrock-mantle"
    return "inference-profile" if iam_policy.is_inference_profile(route["aws_model_id"]) else "foundation-model"


def render_setup(plan: dict) -> str:
    routes = plan["routes"]
    money = plan["budget"]["monthly_usd"]
    services = ",".join(plan["budget"]["services"] or [])
    region = plan["region"]
    partition = "aws-us-gov" if "-gov-" in region else "aws-cn" if region.startswith("cn-") else "aws"
    variables = [
        f"REGION={_q(region)}",
        f"PARTITION={_q(partition)}",
        f"POLICY_NAME={_q('bedrock-' + plan['migration_id'])}",
        f'BUDGET_USD="${{BUDGET_USD:-{money if money is not None else ""}}}"',
        f'BUDGET_SERVICES="${{BUDGET_SERVICES:-{services}}}"',
        f"MARKETPLACE_NOTE={_q(MARKETPLACE_NOTE)}",
        "MARKETPLACE_MODELS=(" + " ".join(_q(m) for m in sorted({r["aws_model_id"] for r in routes if r["billing"] == "marketplace"})) + ")",
        "UNCONFIRMED_MODELS=(" + " ".join(_q(m) for m in sorted({r["aws_model_id"] for r in routes if r["billing"] == "unconfirmed"})) + ")",
        "MODEL_IDS=(" + " ".join(_q(r["aws_model_id"]) for r in routes) + ")",
        "MODEL_KINDS=(" + " ".join(_q(_model_kind(r)) for r in routes) + ")",
        "QUOTA_MODELS=(" + " ".join(_q(q["aws_model_id"]) for q in plan["quota_flags"]) + ")",
    ]
    notes = [COMPLIANCE_NOTES[c] for c in plan["compliance"] if c in COMPLIANCE_NOTES] or ["No compliance regime was recorded in Clarify."]
    compliance = '\necho "== 7. Compliance"\n' + "".join(f"echo {_q('   ' + n)}\n" for n in notes)
    return SETUP_HEAD + "\n".join(variables) + "\n" + SETUP_BODY + compliance + SETUP_TAIL


def render_gateway(route: dict) -> str:
    if route["file_kind"] == "yaml":
        return ("# LiteLLM model_list entry for this route. Generated by bedrock-migration-assessment.\n"
                "model_list:\n"
                f"  - model_name: {json.dumps(route['source_model_id'])}\n"
                "    litellm_params:\n"
                f"      model: {json.dumps('bedrock/' + route['aws_model_id'])}\n"
                f"      aws_region_name: {json.dumps(route['region'])}\n")
    if route["openrouter_path"] == "keep_openrouter":
        doc = {"gateway": "openrouter", "source_model": route["source_model_id"], "request_fields": {"provider": {"only": ["amazon-bedrock"]}},
               "note": "Keeps OpenRouter and pins this model's requests to the Amazon Bedrock provider; OpenRouter's fee still applies."}
    else:
        doc = {"gateway": route["fronted_by"], "source_model": route["source_model_id"], "bedrock_model_id": route["aws_model_id"],
               "region": route["region"], "endpoint": route["endpoint"], "client_api": route["required_client_api"],
               "note": "Map the gateway's model entry to this Bedrock model id with SigV4 credentials for bedrock-runtime."}
    return json.dumps(doc, indent=2) + "\n"


def render_all(plan: dict) -> dict[str, str]:
    files = {f"{OUT}/test_comparison.py": render_harness(plan), f"{OUT}/setup_bedrock.sh": render_setup(plan),
             f"{OUT}/iam-policy.json": json.dumps(plan["iam_policy"], indent=2) + "\n"}
    for route in plan["routes"]:
        files[f"{OUT}/routes/{route['route_id']}.py"] = render_route(route)
        for path in route["files"][1:]:
            files[path] = render_gateway({**route, "file_kind": path.rsplit(".", 1)[1]})
    return files


def skeleton(plan: dict) -> dict:
    """generation-ai.json with every fixed value set and each prose field a WRITE: placeholder."""
    fixed = plan["fixed"]
    return {
        "phase": "generate", "generation_source": "ai",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "migration_plan": {"duration_drivers": [f"{PLACEHOLDER} what drives the effort, by mechanism"],
                           "approach": f"{PLACEHOLDER} one sentence per route kind", "phases": [],
                           "models_to_migrate": fixed["models_to_migrate"]},
        "step_by_step_guide": {**fixed["step_by_step_guide"], "dependency_changes": f"{PLACEHOLDER} packages to add and remove"},
        "rollback_plan": fixed["rollback_plan"],
        "monitoring": {"dashboards": DASHBOARDS, "alerting_rules": fixed["alerting_rules"]},
        "production_readiness_checklist": [f"{PLACEHOLDER} readiness item {n}" for n in range(1, 6)],
        "success_criteria": fixed["success_criteria"],
        "recommendation": {"approach": f"{PLACEHOLDER} the recommended approach", "confidence": plan["confidence_ceiling"],
                           "key_risks": [f"{PLACEHOLDER} each key risk"]},
        "artifacts_by_source": fixed["artifacts_by_source"],
    }


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _generation_path(run_dir: Path) -> Path:
    path = run_dir / "generation-ai.json"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise GenerateInputError("generation_not_a_file", f"{path} is a symlink or not a regular file; remove it and run scaffold again")
    return path


def scaffold(run_dir: Path, plan: dict) -> list[str]:
    generation = _generation_path(run_dir)
    out = run_dir / OUT
    if out.is_symlink() or (out.exists() and not out.is_dir()):
        raise GenerateInputError("ai_migration_not_a_directory", f"{out} is a symlink or a file; remove it and run scaffold again")
    if out.exists():
        kept = {rel: (run_dir / rel).read_bytes() for rel in plan["manifest"]["user"]
                if (run_dir / rel).is_file() and not (run_dir / rel).is_symlink() and not (out / "invoke").is_symlink()}
        shutil.rmtree(out)
        for rel, data in kept.items():
            (run_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (run_dir / rel).write_bytes(data)
    generation.write_text(json.dumps(skeleton(plan), indent=2) + "\n", encoding="utf-8")
    written = []
    for rel, text in render_all(plan).items():
        path = run_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if rel.endswith(".sh"):
            path.chmod(0o755)
        written.append(rel)
    return sorted(written)


# --------------------------------------------------------------------------- check

def _err(errors: list, code: str, detail: str) -> None:
    errors.append({"code": code, "detail": detail})


def _sorted_sources(entries: list[dict]) -> list:
    return sorted(([e["provider"], e["source_service"], sorted([m["model"], sorted(m["generated_files"])] for m in e["models"])]
                   for e in entries), key=json.dumps)


def _on_disk(run_dir: Path) -> set[str]:
    root = run_dir / OUT
    if not root.is_dir() or root.is_symlink():
        return set()
    found = set()
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in TOLERATED_DIRS for part in rel.parts) or path.is_dir():
            continue
        if len(rel.parts) == 1 and rel.name in TOLERATED_FILES:
            continue
        found.add(f"{OUT}/{rel.as_posix()}")
    return found


def _check_prompts(text: str, route_ids_: set[str], errors: list) -> None:
    try:
        prompts = json.loads(text)
    except json.JSONDecodeError as exc:
        _err(errors, "prompts_invalid", f"prompts.json is not JSON: {exc}")
        return
    ok = isinstance(prompts, list) and prompts and all(
        isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("prompt"), str) and p["prompt"].strip()
        and isinstance(p.get("expected_traits", []), list) and all(isinstance(t, str) for t in p.get("expected_traits", []))
        and p.get("route") in route_ids_ | {None} for p in prompts)
    if not ok:
        _err(errors, "prompts_invalid", "prompts.json must be a non-empty list of {id, prompt, expected_traits[], route (a route id or absent)}")
        return
    uncovered = sorted(r for r in route_ids_ if not any(p.get("route") in (None, r) for p in prompts))
    if uncovered:
        _err(errors, "prompts_uncovered", f"no prompt reaches routes {uncovered}")


def check_generation(gen: Any, plan: dict, run_dir: Path, schema: dict | None = None) -> dict:
    schema = schema if schema is not None else json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(gen, dict):
        return {"ok": False, "errors": [{"code": "not_an_object", "detail": "generation-ai.json must be a JSON object"}]}
    errors = [{"code": "schema_violation", "detail": m} for m in validator._schema_errors(schema, gen, schema)]
    if errors:
        return {"ok": False, "errors": errors}
    fixed = plan["fixed"]
    left = sorted({v for v in _strings(gen) if v.startswith(PLACEHOLDER)})
    if left:
        _err(errors, "placeholder_left", f"replace every {PLACEHOLDER} string: {left[:3]}")
    if not gen["migration_plan"]["phases"]:
        _err(errors, "plan_phases_missing", "migration_plan.phases must list the rollout phases")
    if gen["monitoring"]["dashboards"] != DASHBOARDS:
        _err(errors, "dashboards", f"monitoring.dashboards must be {DASHBOARDS}")
    models = gen["migration_plan"]["models_to_migrate"]
    if sorted(models) != sorted(fixed["models_to_migrate"]) or len(set(models)) != len(models):
        _err(errors, "models_to_migrate", f"migration_plan.models_to_migrate must list {fixed['models_to_migrate']} once each")
    pairs = [(e["provider"], e["source_service"]) for e in gen["artifacts_by_source"]]
    if len(set(pairs)) != len(pairs):
        _err(errors, "artifacts_by_source", "each (provider, source_service) pair appears once")
    elif _sorted_sources(gen["artifacts_by_source"]) != _sorted_sources(fixed["artifacts_by_source"]):
        _err(errors, "artifacts_by_source", f"artifacts_by_source must be {json.dumps(fixed['artifacts_by_source'])}")
    guide = gen["step_by_step_guide"]
    want = fixed["step_by_step_guide"]
    for key in ("languages", "files_to_modify"):
        if sorted(guide[key]) != sorted(want[key]):
            _err(errors, "step_by_step_guide", f"step_by_step_guide.{key} must be {want[key]}")
    if guide["primary_pattern"] != want["primary_pattern"]:
        _err(errors, "step_by_step_guide", f"step_by_step_guide.primary_pattern must be {want['primary_pattern']!r}")
    if gen["rollback_plan"] != fixed["rollback_plan"]:
        _err(errors, "rollback_plan", f"rollback_plan must be {json.dumps(fixed['rollback_plan'])}")
    if sorted(gen["monitoring"]["alerting_rules"], key=json.dumps) != sorted(fixed["alerting_rules"], key=json.dumps):
        _err(errors, "alerting_rules", "monitoring.alerting_rules must be the plan's rules")
    if gen["success_criteria"] != fixed["success_criteria"]:
        _err(errors, "success_criteria", "success_criteria must be the plan's targets")
    if CONFIDENCE.index(gen["recommendation"]["confidence"]) > CONFIDENCE.index(plan["confidence_ceiling"]):
        _err(errors, "confidence", f"recommendation.confidence cannot exceed Estimate's {plan['confidence_ceiling']!r}")

    expected = set(plan["manifest"]["scaffold"]) | set(plan["manifest"]["agent"])
    present = _on_disk(run_dir)
    for rel in sorted(expected - present):
        _err(errors, "artifact_missing", f"{rel} is missing; run scaffold again, then write README.md and prompts.json")
    for rel in sorted(present - expected - set(plan["manifest"]["user"])):
        _err(errors, "artifact_unexpected", f"{rel} is not in this plan's manifest (stale from an earlier run?)")
    rendered = render_all(plan)
    texts: dict[str, str] = {}
    for rel in sorted(expected & present):
        try:
            texts[rel] = (run_dir / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            _err(errors, "artifact_unreadable", f"{rel}: {exc}")
            continue
        if rel in rendered and texts[rel] != rendered[rel]:
            _err(errors, "artifact_modified", f"{rel} differs from what scaffold renders for this plan; run scaffold again")
        if rel.endswith(".py"):
            try:
                ast.parse(texts[rel])
            except SyntaxError as exc:
                _err(errors, "artifact_syntax", f"{rel}: {exc.msg} at line {exc.lineno}")
        if SECRET_RE.search(texts[rel]):
            _err(errors, "secret_literal", f"{rel} contains a credential-shaped string; use Bedrock tokens or SigV4 credentials at runtime")
    readme = texts.get(f"{OUT}/README.md")
    if readme is not None:
        missing = sorted({r["aws_model_id"] for r in plan["routes"] if r["aws_model_id"] not in readme})
        if missing or "AI_PROVIDER" not in readme:
            _err(errors, "readme_incomplete", f"README.md must name every Bedrock model id {missing} and the AI_PROVIDER flag")
        if DOTENV_RE.search(readme):
            _err(errors, "readme_dotenv", "README.md must not load or read .env files")
        if SOURCE_DEFAULT_RE.search(readme):
            _err(errors, "readme_flag_value", "AI_PROVIDER takes source, bedrock or shadow; the default is source")
    if f"{OUT}/prompts.json" in texts:
        _check_prompts(texts[f"{OUT}/prompts.json"], {r["route_id"] for r in plan["routes"]}, errors)
    return {"ok": False, "errors": errors} if errors else {"ok": True, "routes": len(plan["routes"]), "files": sorted(expected)}


def check(run_dir: Path) -> dict:
    plan = build_plan(run_dir)
    try:
        gen = json.loads(_generation_path(run_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GenerateInputError("generation_not_found", "generation-ai.json is not in the run directory")
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise GenerateInputError("generation_unreadable", f"generation-ai.json: {exc}")
    return check_generation(gen, plan, run_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "scaffold", "check"))
    parser.add_argument("run_dir", type=Path, help="the $MIGRATION_DIR with a completed Estimate")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = build_plan(args.run_dir)
        elif args.command == "scaffold":
            plan = build_plan(args.run_dir)
            result = {"ok": True, "written": scaffold(args.run_dir, plan) + ["generation-ai.json"],
                      "write_next": plan["manifest"]["agent"] + [f"generation-ai.json ({PLACEHOLDER} fields and migration_plan.phases)"]}
        else:
            result = check(args.run_dir)
    except validator.ProfileRejected as exc:
        result = {"ok": False, "error": f"profile_{exc.code}", "detail": exc.detail}
    except (GenerateInputError, estimate_ai.EstimateInputError, design_ai.DesignInputError) as exc:
        result = {"ok": False, "error": exc.code, "detail": exc.detail}
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
