#!/usr/bin/env python3
"""Attributes for a migration telemetry event, derived from the run's own artifacts.

Every value is a lookup over files the migration skills already write into
`.migration/<id>/`: no inference, no free text. Unknown or unmodelled values drop
the attribute, never the event, because the service rejects a whole event on one
bad enum member. Phase facts attach only to the PHASE_COMPLETED event of the
phase that produced them, so no aggregation double counts; `complexityTier` is
the exception, riding every Design-onward and terminal event because it segments
the funnel.

Vocabularies mirror `MigrationEventAttributes` in migration-telemetry.smithy.
"""

import json
import re
from pathlib import Path

PHASES = frozenset(
    {"DISCOVER", "CLARIFY", "DESIGN", "ESTIMATE", "WORKSHOP", "GENERATE", "FEEDBACK"}
)
RESOLVED_STATUS = {
    "completed": "SUCCESS",
    "skipped": "SKIPPED",
    "not_applicable": "NOT_APPLICABLE",
    "failed": "FAILED",
}
RUN_MODE = {"decide": "DECIDE", "decide_and_execute": "DECIDE_AND_EXECUTE"}
# Mirrors the reason= constants of the interpreter's GATE_FAIL line.
FAILURE_REASON = {
    "missing": "MISSING",
    "invalid": "INVALID",
    "stale_downstream": "STALE_DOWNSTREAM",
}

PRICING_SOURCE = {
    "live": "LIVE",
    "cached": "CACHED",
    "cached_fallback": "CACHED_FALLBACK",
    "cached_stale": "CACHED_STALE",
    "unavailable": "UNAVAILABLE",
}
RECOMMENDATION_OUTCOME = {
    "go": "GO",
    "conditional_go": "CONDITIONAL_GO",
    "defer": "DEFER",
    "defer_for_evidence": "DEFER",
    "stay": "STAY",
}
CLARIFY_MODE = {"wizard": "WIZARD", "full": "FULL", "fast_path": "FAST"}
# estimated_from_token_volume is the AI route (it prices tokens, not
# infrastructure). `preferences` is handled by preference_spend_basis, since a
# clarify answer the skill filled in itself is not the customer's figure.
SPEND_BASIS = {
    "billing_data": "BILLING_DATA",
    "inventory_estimate": "INVENTORY_ESTIMATE",
    "live_prices_plus_cache": "LIVE_PRICES_PLUS_CACHE",
    "pricing_cache": "PRICING_CACHE",
    "user_provided": "USER_PROVIDED",
    "unavailable": "UNAVAILABLE",
    "estimated_from_token_volume": "TOKEN_VOLUME_ESTIMATE",
    # azure-to-aws's baseline rungs (estimate-infra.md): a stated figure, a Cost
    # Management export or RDfA consumption data, or a figure derived from SKUs.
    "user_stated": "USER_PROVIDED",
    "cost_management_export": "BILLING_DATA",
    "consumption_data": "BILLING_DATA",
    "derived_from_skus": "INVENTORY_ESTIMATE",
}
AI_SOURCE = {"openai": "OPENAI", "anthropic": "ANTHROPIC", "gemini": "GCP", "azure_openai": "AZURE", "other": "OTHER"}
COMPLEXITY_TIER = frozenset({"SMALL", "MEDIUM", "LARGE"})
# The discover preview's coarser signal, used before a tiered artifact exists.
COMPLEXITY_SIGNAL = {"likely_simple": "SMALL", "standard": "MEDIUM", "complex": "LARGE"}
RECOMMENDATION_CONFIDENCE = frozenset({"LOW", "MEDIUM", "HIGH"})
VALIDATION_STATUS = frozenset({"PASSED", "PASSED_DEGRADED_OFFLINE", "FAILED"})
COMPLIANCE = frozenset({"NONE", "UNKNOWN", "HIPAA", "PCI", "SOC2", "GDPR", "CCPA", "FEDRAMP"})
COMPLIANCE_ALIAS = {"PCI_DSS": "PCI", "SOC_2": "SOC2", "FED_RAMP": "FEDRAMP"}
COMPLIANCE_ACCEPTED = COMPLIANCE | frozenset(COMPLIANCE_ALIAS)
AVAILABILITY = frozenset({"SINGLE_AZ", "MULTI_AZ", "MULTI_AZ_HA", "MULTI_REGION"})
CUTOVER_STRATEGY = frozenset(
    {"MAINTENANCE_WINDOW_WEEKLY", "MAINTENANCE_WINDOW_MONTHLY", "FLEXIBLE", "ZERO_DOWNTIME"}
)
DATABASE_TRAFFIC = frozenset({"STEADY", "READ_HEAVY", "WRITE_HEAVY"})
# gcp's clarify writes "write-heavy-global" for the write-heavy answer.
DATABASE_TRAFFIC_ALIAS = {"WRITE_HEAVY_GLOBAL": "WRITE_HEAVY"}
DATABASE_TRAFFIC_ACCEPTED = DATABASE_TRAFFIC | frozenset(DATABASE_TRAFFIC_ALIAS)
COMPUTE_POSTURE = frozenset(
    {"EKS_MANAGED", "EKS_OR_ECS", "ECS_FARGATE", "EKS", "ECS", "ELASTIC_BEANSTALK"}
)
TARGET_REGION = frozenset(
    {
        "US_EAST_1", "US_EAST_2", "US_WEST_1", "US_WEST_2", "CA_CENTRAL_1",
        "EU_WEST_1", "EU_WEST_2", "EU_WEST_3", "EU_CENTRAL_1", "EU_NORTH_1",
        "AP_SOUTH_1", "AP_SOUTHEAST_1", "AP_SOUTHEAST_2", "AP_NORTHEAST_1",
        "AP_NORTHEAST_2", "AP_NORTHEAST_3", "SA_EAST_1",
    }
)
# The skills write db_size as a human range ("<10GB", "10-100GB"), not a token.
DB_SIZE = {
    "<10gb": "DB_UNDER_10GB",
    "10-100gb": "DB_10_100GB",
    "100-500gb": "DB_100_500GB",
    ">500gb": "DB_OVER_500GB",
    "unknown": "UNKNOWN",
}
PROJECTED_COST_MAX = 10_000_000  # model @range
RESOURCE_COUNT_MAX = 10_000  # model @range

AI_TYPE = re.compile(
    r"vertex|aiplatform|notebooks|discovery_engine|automl|ml_engine|dialogflow|document_ai|cognitive|machine_?learning|bedrock|sagemaker|comprehend"
)
DB_TYPE = re.compile(
    r"sql|postgres|mysql|mongo|redis|firestore|spanner|bigtable|datastore|memorystore|alloydb|cosmos|rds|aurora|dynamo|elasticache|documentdb"
)

# Where a route records the source-platform spend, in preference order.
SOURCE_SPEND_KEYS = (
    "gcp_monthly_spend",
    "gcp_monthly",
    "gcp_monthly_usd",
    "gcp_monthly_baseline",
    "current_gcp_monthly",
    "total_monthly_spend",
    "gcp_total_monthly",
    "total_monthly",
    "gcp_monthly_ai_spend",
    "total_current_ai_monthly",
    "heroku_monthly",
    "heroku_monthly_estimated",
    "heroku_monthly_baseline",
    "current_heroku_monthly",
    "azure_monthly",
    "azure_monthly_spend",
    "azure_monthly_baseline",
    "current_azure_monthly",
)

SKILL_INVENTORY = {
    "AZURE_TO_AWS": {"inventory": "azure-resource-inventory.json", "provider": "AZURE"},
    "GCP_TO_AWS": {"inventory": "gcp-resource-inventory.json", "provider": "GCP"},
    "HEROKU_TO_AWS": {"inventory": "heroku-resource-inventory.json", "provider": "HEROKU"},
}
ESTIMATE_FILES = ("estimation-infra.json", "estimation-ai.json", "estimation-billing.json")
DESIGN_ONWARD = frozenset({"DESIGN", "ESTIMATE", "WORKSHOP", "GENERATE", "FEEDBACK"})


def read_json(path):
    """The parsed file, or None when absent or unparseable."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def map_enum(table, value):
    """Look `value` up case-insensitively; only the table's own keys count."""
    if value is None:
        return None
    return table.get(str(value).lower())


def to_enum(members, value):
    """Normalise a skill-written value ("multi-az-ha", "us-east-1") to UPPER_SNAKE
    and admit it only if the model declares it."""
    if value is None:
        return None
    key = re.sub(r"[^A-Z0-9]+", "_", str(value).strip().upper()).strip("_")
    return key if key in members else None


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def to_pricing_source(raw):
    if raw is None:
        return None
    is_object = isinstance(raw, dict)
    mapped = map_enum(PRICING_SOURCE, raw.get("status") if is_object else raw)
    if not mapped:
        return None
    stale = is_object and (raw.get("fallback_staleness") or {}).get("is_stale") is True
    return "CACHED_STALE" if mapped == "CACHED" and stale else mapped


def to_spend_band(amount):
    if isinstance(amount, str):
        try:
            amount = float(amount)
        except ValueError:
            return None
    if not _is_number(amount) or amount != amount or amount < 0:
        return None
    if amount < 100:
        return "UNDER_100"
    if amount < 1000:
        return "FROM_100_TO_1K"
    if amount < 10000:
        return "FROM_1K_TO_10K"
    return "OVER_10K"


def to_projected_usd(value):
    """Integer USD within the model's range; anything else is omitted rather than
    clamped, since a clamped cost would read as a real figure."""
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if not _is_number(value) or value != value or value < 0 or value > PROJECTED_COST_MAX:
        return None
    return int(round(value))


def to_accuracy_band(text):
    """"±5-10%", "±20-30%+", "±5% (billing)": the upper bound decides the band."""
    if not isinstance(text, str):
        return None
    match = re.search(r"±?\s*(\d+)(?:\s*-\s*(\d+))?\s*%", text)
    if not match:
        return None
    upper = int(match.group(2) or match.group(1))
    if upper <= 10:
        return "HIGH"
    if upper <= 20:
        return "MEDIUM"
    return "LOW"


def to_coverage(value):
    """"100%", "97%", 100: FULL at 100, NEAR_COMPLETE from 90, PARTIAL below."""
    if value is None or value == "":
        return None
    try:
        number = float(value) if _is_number(value) else float(str(value).replace("%", "").strip())
    except ValueError:
        return None
    if number >= 100:
        return "FULL"
    if number >= 90:
        return "NEAR_COMPLETE"
    return "PARTIAL"


def constraint_value(preferences, key):
    """A design constraint is an object with the interpreted value under `value`
    (gcp) or `default` (heroku's compute_target); older artifacts hold the bare
    value. Heroku records region, compliance and availability as plain values
    under `global` instead."""
    if not isinstance(preferences, dict):
        return None
    raw = (preferences.get("design_constraints") or {}).get(key)
    if raw is None:
        raw = (preferences.get("global") or {}).get(key)
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw.get("value", raw.get("default"))
    return raw


def to_compliance_list(raw):
    """An explicit empty list is the customer's confirmed "no requirements", which
    the model spells NONE; only an absent answer is omitted."""
    if raw is None:
        return None
    if isinstance(raw, list) and len(raw) == 0:
        return ["NONE"]
    values = raw if isinstance(raw, list) else [raw]
    out = []
    for value in values:
        key = to_enum(COMPLIANCE_ACCEPTED, value)
        if key:
            member = COMPLIANCE_ALIAS.get(key, key)
            if member not in out:
                out.append(member)
    return out or None


def preference_spend_basis(run_dir):
    """An estimate that cites "preferences" for the source spend is only as good as
    the clarify answer behind it: the customer's own answer is USER_PROVIDED, one
    the skill filled in itself is DEFAULTED, one extracted from the customer's
    billing export is BILLING_DATA, and anything without provenance is left out."""
    preferences = read_json(Path(run_dir) / "preferences.json") or {}
    spend = (preferences.get("design_constraints") or {}).get("gcp_monthly_spend") or {}
    if not isinstance(spend, dict):
        return None
    source = str(spend.get("source") or "")
    chosen_by = spend.get("chosen_by")
    if chosen_by == "default" or source.startswith("default"):
        return "DEFAULTED"
    if chosen_by == "user":
        return "USER_PROVIDED"
    if chosen_by == "extracted" and source.startswith("billing"):
        return "BILLING_DATA"
    return None


def resource_types(resources):
    """The resource types as one lower-cased string. gcp writes `type`, heroku
    `resource_type` (with the add-on service under config), azure the canonical
    ARM type under `azure_type` (Microsoft.DocumentDB/databaseAccounts)."""
    parts = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        kind = resource.get("type") or resource.get("resource_type") or resource.get("azure_type") or ""
        addon = (resource.get("config") or {}).get("addon_service") if isinstance(resource.get("config"), dict) else ""
        parts.append("%s %s" % (kind, addon or ""))
    return " ".join(parts).lower()


def source_provider(run_dir, spec):
    """The migration's source: the skill's inventory file names it; an AI-only run
    has none and takes the provider from its workload profile."""
    if spec and (Path(run_dir) / spec["inventory"]).exists():
        return spec["provider"]
    profile = read_json(Path(run_dir) / "ai-workload-profile.json") or {}
    return map_enum(AI_SOURCE, (profile.get("summary") or {}).get("ai_source"))


def cost_containers(estimate):
    """Where a route records the source-platform cost, in preference order: the
    infra and AI routes use current_costs, the billing-only route gcp_baseline,
    and heroku's assembler also rolls it into financial_summary."""
    return [
        estimate.get(key)
        for key in ("current_costs", "gcp_baseline", "cost_comparison", "financial_summary")
        if isinstance(estimate.get(key), dict)
    ]


def projected_cost(estimate, tier, option):
    """The three cost tiers are written flat (aws_monthly_*), with older shapes
    nesting them under option_*/tiers."""
    costs = estimate.get("projected_costs") or {}
    value = costs.get("aws_monthly_%s" % tier)
    if value is None:
        value = (costs.get(option) or {}).get("aws_monthly") if isinstance(costs.get(option), dict) else None
    if value is None:
        tiers = costs.get("tiers") or {}
        value = (tiers.get(tier) or {}).get("monthly") if isinstance(tiers.get(tier), dict) else None
    return to_projected_usd(value)


def complexity_tier(run_dir, status):
    """Written by generate (gcp) or estimate (heroku); before either is complete,
    the discover preview's coarser signal. A confirmed re-entry resets downstream
    phases to pending but leaves their artifacts on disk, so an artifact counts
    only while its phase is completed."""
    phases = (status or {}).get("phases") or {}
    tiered = []
    if phases.get("generate") == "completed":
        tiered += ["generation-infra.json", "generation-billing.json", "generation-ai.json"]
    if phases.get("estimate") == "completed":
        tiered.append("estimation-infra.json")
    for name in tiered:
        artifact = read_json(Path(run_dir) / name) or {}
        raw = artifact.get("complexity_tier")
        if raw is None:
            raw = (artifact.get("estimation_summary") or {}).get("complexity_tier")
        tier = to_enum(COMPLEXITY_TIER, raw)
        if tier:
            return tier
    preview = read_json(Path(run_dir) / "migration-preview.json") or {}
    return map_enum(COMPLEXITY_SIGNAL, preview.get("complexity_signal"))


def derive_attributes(run_dir, skill, event, status):
    """The attributes object for `event`, or None when there is nothing to say."""
    run_dir = Path(run_dir)
    attributes = {}
    spec = SKILL_INVENTORY.get(skill)
    provider = source_provider(run_dir, spec)
    if provider:
        attributes["sourceProvider"] = provider

    phase_event = event.get("eventName") == "PHASE_COMPLETED"
    phase = event.get("phase")

    if phase_event and phase == "DISCOVER":
        inventory = read_json(run_dir / spec["inventory"]) if spec else None
        resources = inventory if isinstance(inventory, list) else (inventory or {}).get("resources") if isinstance(inventory, dict) else None
        # App-code AI detection lives only here; it is what lets an AI workload
        # with no AI resource (an SDK called from application code) report hasAi.
        profile = read_json(run_dir / "ai-workload-profile.json")
        models = (profile or {}).get("models")
        if isinstance(models, list):
            ai_from_profile = len(models) > 0
        else:
            ai_from_profile = ((profile or {}).get("summary") or {}).get("total_models_detected", 0) > 0
        if isinstance(resources, list):
            attributes["resourceCount"] = min(len(resources), RESOURCE_COUNT_MAX)
            types = resource_types(resources)
            attributes["hasDatabase"] = bool(DB_TYPE.search(types))
            attributes["hasAi"] = bool(AI_TYPE.search(types)) or ai_from_profile
        elif profile is not None:
            attributes["hasAi"] = ai_from_profile
        coverage = to_coverage(((inventory or {}).get("summary") or {}).get("classification_coverage") if isinstance(inventory, dict) else None)
        if coverage:
            attributes["classificationCoverage"] = coverage

    if phase_event and phase == "CLARIFY":
        preferences = read_json(run_dir / "preferences.json") or {}
        metadata = preferences.get("metadata") or {}
        clarify_mode = "AI_ONLY" if metadata.get("migration_type") == "ai-only" else map_enum(CLARIFY_MODE, metadata.get("clarify_mode"))
        if clarify_mode:
            attributes["clarifyMode"] = clarify_mode
        compliance = to_compliance_list(constraint_value(preferences, "compliance"))
        if compliance:
            attributes["compliance"] = compliance
        availability = to_enum(AVAILABILITY, constraint_value(preferences, "availability"))
        if availability:
            attributes["availability"] = availability
        cutover = to_enum(CUTOVER_STRATEGY, constraint_value(preferences, "cutover_strategy"))
        if cutover:
            attributes["cutoverStrategy"] = cutover
        db_size = map_enum(DB_SIZE, re.sub(r"\s+", "", str(constraint_value(preferences, "db_size") or "")))
        if db_size:
            attributes["dbSize"] = db_size
        traffic_key = to_enum(DATABASE_TRAFFIC_ACCEPTED, constraint_value(preferences, "database_traffic"))
        if traffic_key:
            attributes["databaseTraffic"] = DATABASE_TRAFFIC_ALIAS.get(traffic_key, traffic_key)
        # gcp asks about kubernetes, heroku about a compute target; same decision.
        posture_raw = constraint_value(preferences, "kubernetes")
        if posture_raw is None:
            posture_raw = constraint_value(preferences, "compute_target")
        posture = to_enum(COMPUTE_POSTURE, posture_raw)
        if posture:
            attributes["computePosture"] = posture
        region = to_enum(TARGET_REGION, constraint_value(preferences, "target_region"))
        if region:
            attributes["targetRegion"] = region

    if phase_event and phase == "ESTIMATE":
        estimates = [e for e in (read_json(run_dir / name) for name in ESTIMATE_FILES) if isinstance(e, dict)]
        for estimate in estimates:
            recommendation = estimate.get("recommendation") or {}
            if "recommendationOutcome" not in attributes:
                outcome = map_enum(RECOMMENDATION_OUTCOME, recommendation.get("outcome"))
                if outcome:
                    attributes["recommendationOutcome"] = outcome
            if "recommendationConfidence" not in attributes:
                confidence = to_enum(RECOMMENDATION_CONFIDENCE, recommendation.get("confidence"))
                if confidence:
                    attributes["recommendationConfidence"] = confidence
            if "pricingSource" not in attributes:
                # The billing-only route records provenance under metadata.
                raw = estimate.get("pricing_source")
                if raw is None:
                    raw = (estimate.get("metadata") or {}).get("pricing_source")
                if raw is None:
                    raw = (estimate.get("projected_costs") or {}).get("pricing_source")
                pricing = to_pricing_source(raw)
                if pricing:
                    attributes["pricingSource"] = pricing
            if "estimateAccuracyBand" not in attributes:
                accuracy = (estimate.get("current_costs") or {}).get("accuracy")
                if accuracy is None:
                    accuracy = estimate.get("accuracy_confidence")
                band = to_accuracy_band(accuracy)
                if band:
                    attributes["estimateAccuracyBand"] = band
            if "billingDataAvailable" not in attributes:
                available = (estimate.get("migration_cost_considerations") or {}).get("billing_data_available")
                if isinstance(available, bool):
                    attributes["billingDataAvailable"] = available
            if "awsProjectedCostBalanced" not in attributes:
                for tier, option, key in (
                    ("optimized", "option_c_optimized", "awsProjectedCostOptimized"),
                    ("balanced", "option_b_balanced", "awsProjectedCostBalanced"),
                    ("premium", "option_a_premium", "awsProjectedCostPremium"),
                ):
                    usd = projected_cost(estimate, tier, option)
                    if usd is not None:
                        attributes[key] = usd
        # spendBand and spendBasis travel as a pair: a band without its basis is
        # indistinguishable from a measured figure. The basis comes from the cost
        # container's own `source`; when a route omits it, confirmed billing data
        # is the one case that can still be named. A basis alone is harmless and
        # is still reported.
        for estimate in estimates:
            containers = cost_containers(estimate)
            basis = None
            for container in containers:
                source = container.get("source")
                basis = preference_spend_basis(run_dir) if source == "preferences" else map_enum(SPEND_BASIS, source)
                if basis:
                    break
            if not basis and (estimate.get("migration_cost_considerations") or {}).get("billing_data_available") is True:
                basis = "BILLING_DATA"
            band = None
            for container in containers:
                for key in SOURCE_SPEND_KEYS:
                    band = to_spend_band(container.get(key))
                    if band:
                        break
                if band:
                    break
            if basis and band:
                attributes["spendBand"] = band
                attributes["spendBasis"] = basis
                break
            if basis and "spendBasis" not in attributes:
                attributes["spendBasis"] = basis

    if phase_event and phase == "GENERATE":
        report = read_json(run_dir / "validation-report.json") or {}
        validation = to_enum(VALIDATION_STATUS, report.get("status"))
        if validation:
            attributes["validationStatus"] = validation

    from_design_onward = (phase_event or event.get("eventName") == "GATE_FAILED") and phase in DESIGN_ONWARD
    if from_design_onward or event.get("eventName") == "RUN_COMPLETED":
        tier = complexity_tier(run_dir, status)
        if tier:
            attributes["complexityTier"] = tier

    if event.get("runMode"):
        attributes["runMode"] = event["runMode"]
    if event.get("failureReason"):
        attributes["failureReason"] = event["failureReason"]
    return attributes or None
