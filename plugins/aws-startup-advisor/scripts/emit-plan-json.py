#!/usr/bin/env python3
"""Emit plan.json from a finished migration run.

Copies already-validated values from a run's artifacts into a `plan.json`
summary the AWS Startups Migrate web import page ingests. It GENERATES nothing:
every field is copied from a validated artifact or omitted, because every extra
field is a mistake surface.

Fail-open by design: any missing or unreadable input leaves the migration
successful, writes no file, prints the reason, and stays re-runnable. A missed
handoff must never cost a customer their migration result.

Cost routes: a run costs its work as infra (`estimation-infra.json`), billing-only
(`estimation-billing.json`, the no-IaC fallback), and/or AI (`estimation-ai.json`,
which runs independently and can accompany infra or billing). The route(s) present
decide scope and basis: infra/billing alone -> INFRA_ONLY; a base route + AI -> FULL
(the two figures summed). A standalone AI-only run is deferred — the contract only
accepts AI_ONLY with sourcePlatform OPENAI, and the LLM-to-Bedrock path persists no
cost file, so a GCP AI-only run has no valid mapping yet.

Usage:
  python3 scripts/emit-plan-json.py --migration-dir <dir>

Reads:
  <dir>/.phase-status.json              run_id, owning_skill
  <dir>/estimation-infra.json           projected_costs.aws_monthly_balanced, current_costs.*
  <dir>/estimation-billing.json         cost_comparison.aws_monthly_mid / .gcp_monthly, aws_projection.services[]
  <dir>/estimation-ai.json              cost_comparison.projected_bedrock_monthly, current_costs.gcp_monthly_ai_spend
  <PLUGIN_ROOT>/.claude-plugin/plugin.json   version

Writes:
  <dir>/plan.json

Status line (stdout, machine-readable):
  PLAN_OK   | path=<dir>/plan.json | platform=GCP | scope=INFRA_ONLY
  PLAN_SKIP | reason=<why>                 (fail-open; exit 0, no file written)
Exit code is 0 for success AND for every fail-open skip; only a usage error is non-zero.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path

# scripts/ -> plugin root (holds .claude-plugin/plugin.json).
PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# Highest plan.json schema the web import page understands (kept in lock-step there).
SCHEMA_VERSION = 1

# owning_skill (telemetry id written to .phase-status.json at _init) ->
# sourcePlatform. Not generated data: each skill records its own id at _init and
# never changes it. LLM_TO_BEDROCK (OpenAI) is intentionally absent — it has no
# persisted cost artifact to copy, so it is a follow-up.
SKILL_TO_PLATFORM = {
    "GCP_TO_AWS": "GCP",
    "HEROKU_TO_AWS": "HEROKU",
}

# Bounds the strict web import contract enforces. Mirrored here so an out-of-bounds
# value is dropped (or the handoff fails open) locally rather than being emitted and
# rejecting the whole import: USD amounts <= $100M, at most 100 service items, each
# serviceName at most 128 chars.
MAX_USD_AMOUNT = 100_000_000
MAX_SERVICE_ITEMS = 100
MAX_SERVICE_NAME_LEN = 128

# Naming for the write temp files, shared by the writer and the orphan sweep below.
_TEMP_PREFIX = ".plan-"
_TEMP_SUFFIX = ".json.tmp"
# A real write finishes in milliseconds, so any temp older than this is an orphan
# abandoned by a crashed run and safe to reclaim without racing a live writer.
_ORPHAN_TEMP_AGE_S = 3600

# Where each platform's source-monthly baseline lives in its infra estimate, as
# (container, field). The location differs by skill: GCP writes current_costs.gcp_monthly;
# Heroku writes its baseline under cost_comparison.heroku_monthly_baseline (its
# current_costs holds only source/accuracy metadata, not a number). Reading only the
# platform's own field keeps an unrelated number from being copied by accident.
PLATFORM_SOURCE_FIELD = {
    "GCP": ("current_costs", "gcp_monthly"),
    "HEROKU": ("cost_comparison", "heroku_monthly_baseline"),
}

# The plugin's pricing_source.status values -> the web contract's pricingSource enum.
# A "cached" status carrying fallback_staleness.is_stale is ALSO mapped to CACHED_STALE
# by the special case below; this map covers the explicit "cached_stale" status that the
# estimators emit directly once the cache is past its freshness window.
PRICING_SOURCE_MAP = {
    "cached": "CACHED",
    "cached_fallback": "CACHED_FALLBACK",
    "cached_stale": "CACHED_STALE",
    "live": "LIVE",
    "unavailable": "UNAVAILABLE",
}

# Which scopes the ImportPlan handler accepts per sourcePlatform. Mirrored here so the
# writer never emits a (platform, scope) the import would reject. All combos reachable
# today are valid; this guards against a future route change silently producing one.
VALID_SCOPES_BY_PLATFORM = {
    "GCP": {"INFRA_ONLY", "FULL"},
    "HEROKU": {"INFRA_ONLY"},
    "OPENAI": {"AI_ONLY"},
}


class SkipEmit(Exception):
    """Fail-open signal: a reason to skip writing plan.json without failing the run."""


def _load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _is_amount(value: object) -> bool:
    """True for a real, finite, non-negative JSON number.

    Excludes bool (a Python int subclass, so a JSON `true` would otherwise slip
    through) and non-finite floats (json.load accepts Infinity/NaN by default, and
    json.dumps would then emit the literal tokens `Infinity`/`NaN`, which the strict
    web import rejects). The USD cap is checked SEPARATELY by callers so an over-cap
    value can be diagnosed distinctly from a missing/malformed one.
    """
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _is_usable_amount(value: object) -> bool:
    """A non-negative number within the contract's USD cap — the values safe to copy
    into OPTIONAL cost fields (service items, sourceMonthly), which are simply dropped
    when over cap rather than failing the whole handoff."""
    return _is_amount(value) and value <= MAX_USD_AMOUNT


def _import_str_len(text: str) -> int:
    """Length as the strict web schema (JS/TS) counts it — UTF-16 code units, not
    Python code points — so the serviceName bound matches the import exactly even for
    astral-plane characters (which are one code point but two UTF-16 units)."""
    return len(text.encode("utf-16-le")) // 2


def _pricing_source(raw: object) -> str | None:
    """Map the plugin's pricing_source to the web pricingSource enum, or None. `raw` is
    an object with a `status` (infra) or a plain string (billing/AI). A cached status
    flagged stale becomes CACHED_STALE."""
    if isinstance(raw, dict):
        status = raw.get("status")
        staleness = raw.get("fallback_staleness")
        if status == "cached" and isinstance(staleness, dict) and staleness.get("is_stale") is True:
            return "CACHED_STALE"
    elif isinstance(raw, str):
        status = raw
    else:
        return None
    return PRICING_SOURCE_MAP.get(status)


def _accuracy(data: dict) -> dict | None:
    """The cost.accuracy object for a route, or None if not derivable. Parses the
    `accuracy_confidence` band string (e.g. "±5-10%", "±30%") into integer
    minPercent/maxPercent and maps the route's pricing_source to pricingSource."""
    text = data.get("accuracy_confidence")
    if not isinstance(text, str):
        return None
    # Anchor on the "%" band ("±5-10%", "±30%") so a stray number elsewhere in the
    # string can't be mistaken for a percentage.
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*%", text)
    if match is None:
        return None
    low = round(float(match.group(1)))
    high = round(float(match.group(2))) if match.group(2) else low
    if low > high:
        low, high = high, low
    if not (0 <= low <= 100 and 0 <= high <= 100):
        return None
    accuracy: dict = {"minPercent": low, "maxPercent": high}
    # pricing_source is top-level (infra object / AI string) or under metadata (billing).
    raw = data.get("pricing_source")
    if raw is None and isinstance(data.get("metadata"), dict):
        raw = data["metadata"].get("pricing_source")
    pricing = _pricing_source(raw)
    if pricing is not None:
        accuracy["pricingSource"] = pricing
    return accuracy


def _looser_accuracy(a: dict, b: dict) -> dict:
    """Return the LOOSER of two declared accuracy bands, carried WHOLE — never a
    synthesized min/max. A combined plan then reports an uncertainty a producer
    actually declared (e.g. the billing band must never be reported tighter than it
    stated), instead of inventing a band neither estimate claimed. "Looser" is the
    larger (maxPercent, then minPercent). pricingSource is kept only when both routes
    declare the same source."""
    looser = a if (a["maxPercent"], a["minPercent"]) >= (b["maxPercent"], b["minPercent"]) else b
    result: dict = {"minPercent": looser["minPercent"], "maxPercent": looser["maxPercent"]}
    pricing = a.get("pricingSource")
    if pricing is not None and pricing == b.get("pricingSource"):
        result["pricingSource"] = pricing
    return result


def _source_monthly(data: dict, source_platform: str) -> float | None:
    """The infra estimate's monthly source-platform baseline, or None. Reads ONLY the
    platform's own field (see PLATFORM_SOURCE_FIELD) — the baseline may be absent (no
    billing access), in which case sourceMonthly is omitted, and honoring one field
    keeps an unrelated number from being copied by accident."""
    location = PLATFORM_SOURCE_FIELD.get(source_platform)
    if location is None:
        return None
    container = data.get(location[0])
    if not isinstance(container, dict):
        return None
    value = container.get(location[1])
    return value if _is_usable_amount(value) else None


def _service_items(projected: object) -> list[dict]:
    """Per-service line items copied from projected_costs.breakdown.

    The breakdown is keyed by service, and its shape varies across skills and rows.
    An entry is either a bare monthly number, or an object carrying the figure under
    `monthly` (GCP core services) or `mid` (observability / Heroku scenarios) plus an
    optional `service` display label; the key is the fallback display name. Nested
    `alternative`/`components`/sub-cost objects are ignored — only the entry's own
    figure is read. The "total" rollup row, any entry with no usable amount, and any
    name over the contract length are skipped; GCP runs may carry an empty breakdown.

    classification is INFRASTRUCTURE — every row in an infra/billing breakdown is an
    infrastructure service; the single AI line for a combined run is added by the
    caller with AI_ML. `category` is not persisted, so it is omitted.
    """
    if not isinstance(projected, dict):
        return []
    breakdown = projected.get("breakdown")
    if not isinstance(breakdown, dict):
        return []

    items: list[dict] = []
    for key, entry in breakdown.items():
        # Drop the aggregate row (any casing) so the total is never shown as a service.
        if not isinstance(key, str) or key.strip().lower() == "total":
            continue

        if _is_usable_amount(entry):
            # Bare-number form: {"compute": 75}.
            name, monthly = key, entry
        elif isinstance(entry, dict):
            # Object form: the figure is under `monthly` (GCP) or `mid`
            # (observability/Heroku) — one key per row. Take the first PRESENT key and
            # validate that one; don't substitute the other when the primary figure is
            # present but out of range, which would misreport a different number.
            raw = next((entry[k] for k in ("monthly", "mid") if k in entry), None)
            if not _is_usable_amount(raw):
                continue
            monthly = raw
            label = entry.get("service")
            name = label if isinstance(label, str) and label.strip() else key
        else:
            continue

        name = name.strip()
        # Skip a blank name, a rollup surfaced via the label (service:"Total"), and a
        # name the strict import would reject for length.
        if not name or name.lower() == "total" or _import_str_len(name) > MAX_SERVICE_NAME_LEN:
            continue
        items.append(
            {
                "serviceName": name,
                "monthlyCost": monthly,
                "classification": "INFRASTRUCTURE",
            }
        )
    return items


def _billing_service_items(aws_projection: object) -> list[dict]:
    """Per-service line items from a billing estimate's `aws_projection.services[]` (a
    list, unlike the infra breakdown). Each service carries `aws_target` (name) and
    `aws_mid` (mid monthly cost); same bounds and skips as the infra items."""
    if not isinstance(aws_projection, dict):
        return []
    services = aws_projection.get("services")
    if not isinstance(services, list):
        return []
    items: list[dict] = []
    for svc in services:
        if not isinstance(svc, dict):
            continue
        cost = svc.get("aws_mid")
        if not _is_usable_amount(cost):
            continue
        name = svc.get("aws_target")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not name or name.lower() == "total" or _import_str_len(name) > MAX_SERVICE_NAME_LEN:
            continue
        items.append({"serviceName": name, "monthlyCost": cost, "classification": "INFRASTRUCTURE"})
    return items


def _load_route(path: Path) -> dict | None:
    """Load a cost artifact if present: the dict when present, None when absent, and
    SkipEmit when present but not a JSON object. JSON/decode errors propagate to main's
    fail-open handler (they don't destroy a prior plan)."""
    if not path.is_file():
        return None
    data = _load_json(path)
    if not isinstance(data, dict):
        raise SkipEmit(f"{path.name} is not a JSON object")
    return data


def _infra_route(data: dict, source_platform: str) -> tuple[float, float | None, list[dict]]:
    """(awsMonthly, sourceMonthly-or-None, service items) for an infra estimate."""
    projected = data.get("projected_costs")
    aws = projected.get("aws_monthly_balanced") if isinstance(projected, dict) else None
    if not _is_amount(aws):
        raise SkipEmit("no usable projected_costs.aws_monthly_balanced")
    return aws, _source_monthly(data, source_platform), _service_items(projected)


def _billing_route(data: dict) -> tuple[float, float | None, list[dict]]:
    """(awsMonthly, sourceMonthly-or-None, service items) for a billing-only estimate."""
    comparison = data.get("cost_comparison")
    aws = comparison.get("aws_monthly_mid") if isinstance(comparison, dict) else None
    if not _is_amount(aws):
        raise SkipEmit("no usable cost_comparison.aws_monthly_mid")
    raw_source = comparison.get("gcp_monthly") if isinstance(comparison, dict) else None
    source = raw_source if _is_usable_amount(raw_source) else None
    return aws, source, _billing_service_items(data.get("aws_projection"))


def _ai_route(data: dict) -> float:
    """The AI estimate's AWS (Bedrock) monthly figure. No per-service list, and its
    source baseline is intentionally not read: it is not comparable with the infra/
    billing baseline, so a combined run does not present a summed source total."""
    comparison = data.get("cost_comparison")
    aws = comparison.get("projected_bedrock_monthly") if isinstance(comparison, dict) else None
    if not _is_amount(aws):
        raise SkipEmit("no usable cost_comparison.projected_bedrock_monthly")
    return aws


def build_plan(migration_dir: Path, plugin_json_path: Path) -> tuple[dict, str, str]:
    """Build the plan dict from validated artifacts, or raise SkipEmit to fail open."""
    status_path = migration_dir / ".phase-status.json"
    if not status_path.is_file():
        raise SkipEmit("no .phase-status.json in migration dir")

    status = _load_json(status_path)
    if not isinstance(status, dict):
        raise SkipEmit(".phase-status.json is not a JSON object")

    owning_skill = status.get("owning_skill")
    # Guard the type before the dict lookup: a non-string (e.g. a list) is unhashable
    # and would raise TypeError, and only a string can name a skill anyway.
    source_platform = SKILL_TO_PLATFORM.get(owning_skill) if isinstance(owning_skill, str) else None
    if source_platform is None:
        raise SkipEmit(f"owning_skill {owning_skill!r} has no web handoff yet")

    # runId carries the attribution the handoff exists for; without it there is
    # nothing to hand off, so fail open rather than write an unattributable plan.
    # Must be a non-empty string: a numeric/other run_id would be copied verbatim and
    # rejected by the strict web schema (which types runId as a string).
    run_id = status.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise SkipEmit("no usable run_id in .phase-status.json")

    # Read whichever cost artifacts the run produced. infra and billing are mutually
    # exclusive (billing is the no-IaC fallback); AI runs independently and may
    # accompany either. The route(s) present decide scope, basis and the totals.
    infra_data = _load_route(migration_dir / "estimation-infra.json")
    billing_data = _load_route(migration_dir / "estimation-billing.json")
    ai_data = _load_route(migration_dir / "estimation-ai.json")

    # Base (non-AI) route: infra takes precedence over billing. Both files can
    # legitimately coexist after a billing-only run re-enters with Terraform (the infra
    # route rewrites estimation-infra.json but nothing removes the stale billing one),
    # and infra is the authoritative estimate in that case — so prefer it rather than
    # treating the pair as an error.
    base_data = infra_data if infra_data is not None else billing_data
    base_aws = base_source = base_basis = None
    base_items: list[dict] = []
    if infra_data is not None:
        base_aws, base_source, base_items = _infra_route(infra_data, source_platform)
        base_basis = "BALANCED"
    elif billing_data is not None:
        base_aws, base_source, base_items = _billing_route(billing_data)
        base_basis = "BILLING_MID"

    ai_aws = _ai_route(ai_data) if ai_data is not None else None

    if base_aws is None and ai_aws is None:
        raise SkipEmit("no cost estimate to hand off")

    if base_aws is not None and ai_aws is not None:
        # Combined run: sum the AWS figures (the *_PLUS_AI_SUM basis names the operation)
        # and add one Bedrock line for the AI figure, which has no per-service breakdown.
        scope = "FULL"
        basis = "INFRA_PLUS_AI_SUM" if infra_data is not None else "BILLING_MID_PLUS_AI_SUM"
        aws_monthly = base_aws + ai_aws
        # The infra/billing baseline and the AI-spend baseline are not comparable (the
        # plugin marks the combination "not comparable"), so their sources are NOT
        # summed. Omit sourceMonthly on a mixed run; the AWS side is still summed.
        source_monthly = None
        items = base_items + [
            {"serviceName": "Amazon Bedrock", "monthlyCost": ai_aws, "classification": "AI_ML"}
        ]
    elif base_aws is not None:
        # Infra-only or billing-only.
        scope, basis, aws_monthly, source_monthly, items = (
            "INFRA_ONLY",
            base_basis,
            base_aws,
            base_source,
            base_items,
        )
    else:
        # AI-only. sourcePlatform here is GCP/HEROKU, but the contract only accepts
        # AI_ONLY with sourcePlatform OPENAI (and the LLM-to-Bedrock path persists no
        # cost file), so a GCP AI-only run has no valid mapping yet — defer rather than
        # emit a plan the import would reject.
        raise SkipEmit("AI-only run has no valid web mapping yet (deferred)")

    # Never emit a (platform, scope) the import handler rejects (e.g. HEROKU must be
    # INFRA_ONLY). Unreachable with today's routes, but guards a future change.
    if scope not in VALID_SCOPES_BY_PLATFORM.get(source_platform, set()):
        raise SkipEmit(f"{source_platform} + {scope} is not an importable combination")

    # Enforce the contract's USD cap on the (possibly summed) totals. Distinct from a
    # missing/malformed value: a real total that merely exceeds the cap.
    if aws_monthly > MAX_USD_AMOUNT:
        raise SkipEmit("total AWS monthly exceeds the supported maximum")
    # sourceMonthly needs no cap re-check here: it is already cap-filtered by
    # _is_usable_amount in the route extractor, and FULL runs omit it entirely.

    # cost.accuracy is optional for infra-only/billing-only (emitted when present) and
    # REQUIRED for a FULL import. A FULL plan must carry a band BOTH contributing routes
    # declared, so require a usable band from each and keep the looser one whole; a run
    # missing either can't state a trustworthy combined band, so skip it.
    accuracy = _accuracy(base_data) if isinstance(base_data, dict) else None
    if scope == "FULL":
        ai_accuracy = _accuracy(ai_data) if isinstance(ai_data, dict) else None
        if accuracy is None or ai_accuracy is None:
            raise SkipEmit("FULL run needs a usable accuracy band from both the base and AI estimates")
        accuracy = _looser_accuracy(accuracy, ai_accuracy)

    plan: dict = {
        "schemaVersion": SCHEMA_VERSION,
        "sourcePlatform": source_platform,
        "scope": scope,
        "runId": run_id,
        "cost": {
            "awsMonthly": aws_monthly,
            "awsMonthlyBasis": basis,
        },
    }
    if source_monthly is not None:
        plan["cost"]["sourceMonthly"] = source_monthly
    if accuracy is not None:
        plan["cost"]["accuracy"] = accuracy
    # The contract caps the list at 100. If the route(s) yield more, there is no
    # meaningful subset to pick, so omit the optional field rather than send an
    # over-limit list that would reject the whole handoff.
    if 0 < len(items) <= MAX_SERVICE_ITEMS:
        plan["cost"]["awsServiceItems"] = items

    # The web contract's field is `producerVersion` (named for the producer, not the
    # plugin, so a partner submission needs no second contract) — NOT `pluginVersion`.
    # The schema is strict, so a wrong key would make the whole import fail.
    # producerVersion is optional: a missing OR unreadable plugin.json omits it rather
    # than sinking an otherwise-valid handoff.
    if plugin_json_path.is_file():
        try:
            version = _load_json(plugin_json_path).get("version")
        except Exception:
            # producerVersion is optional, so ANY fault reading plugin.json (decode
            # error, non-object manifest, even a pathological RecursionError) just omits
            # the version — it must never sink an otherwise-valid handoff.
            version = None
        if isinstance(version, str) and version:
            plan["producerVersion"] = version

    return plan, source_platform, scope


def _unlink_quietly(path: Path) -> None:
    """Delete a file if it exists, ignoring any error (best-effort). Used both to drop
    a stale plan.json from an earlier run and to clean up the write temp file."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _sweep_orphan_temps(directory: Path) -> None:
    """Best-effort removal of write temps abandoned by a crashed earlier run. Because
    unique mkstemp names are no longer reused, nothing else reclaims them; the age
    gate (a real write finishes in milliseconds) keeps a concurrent run's in-flight
    temp from being deleted."""
    cutoff = time.time() - _ORPHAN_TEMP_AGE_S
    try:
        candidates = list(directory.glob(_TEMP_PREFIX + "*" + _TEMP_SUFFIX))
    except OSError:
        return
    for candidate in candidates:
        try:
            if candidate.stat().st_mtime < cutoff:
                candidate.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--migration-dir",
        type=Path,
        required=True,
        help="The run's $MIGRATION_DIR (holds .phase-status.json and estimation-infra.json).",
    )
    parser.add_argument(
        "--plugin-json",
        type=Path,
        default=PLUGIN_ROOT / ".claude-plugin" / "plugin.json",
        help="Path to the plugin manifest read for producerVersion (defaults to this plugin's).",
    )
    args = parser.parse_args()
    migration_dir: Path = args.migration_dir
    out_path = migration_dir / "plan.json"

    # Reclaim any temp abandoned by a crashed earlier run, on EVERY invocation (not
    # only the write path) so a dir that keeps failing open still gets cleaned up.
    _sweep_orphan_temps(migration_dir)

    try:
        plan, platform, scope = build_plan(migration_dir, args.plugin_json)
    except SkipEmit as skip:
        # Deterministic disqualification (the run grew to include AI, lost its run_id,
        # has no cost estimate, etc.): this run should have NO plan, so drop a stale
        # one left by an earlier run.
        _unlink_quietly(out_path)
        print(f"PLAN_SKIP | reason={skip}")
        return 0
    except Exception as err:
        # Fail open on ANY error, not just the expected OSError/ValueError: a missed
        # handoff must never break the migration. But this is an UNCLASSIFIABLE input
        # fault (corrupt/unreadable artifact, RecursionError, ...) — we cannot tell
        # whether a prior plan.json is stale, so leave it: a transient glitch must not
        # destroy a previously-valid handoff. A later clean run overwrites it.
        print(f"PLAN_SKIP | reason=unreadable input: {err}")
        return 0

    # Write atomically to a UNIQUE, exclusively-created temp in the same dir, then
    # rename into place. mkstemp (O_EXCL, mode 0600) means concurrent reruns never
    # share a temp path and a pre-existing temp symlink can't be followed, so a
    # crash/kill can only leave an orphan temp — never a truncated or cross-written
    # plan.json the import might ingest.
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(out_path.parent), prefix=_TEMP_PREFIX, suffix=_TEMP_SUFFIX)
    except OSError as err:
        print(f"PLAN_SKIP | reason=could not write plan.json: {err}")
        return 0
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(plan, indent=2) + "\n")
        # Keep mkstemp's private 0600 (owner-only): plan.json holds the customer's
        # cost figures, and the only consumer is the same user's browser upload, so a
        # secure default loses nothing. Intentional — not the umask-wide 0644 that a
        # plain write would have produced.
        os.replace(tmp_path, out_path)
    except Exception as err:
        # Fail open on any write-path fault. os.replace is atomic, so on failure a
        # prior run's plan.json is untouched and still valid — leave it and clean up
        # only this invocation's own temp, never a good handoff.
        _unlink_quietly(tmp_path)
        print(f"PLAN_SKIP | reason=could not write plan.json: {err}")
        return 0

    print(f"PLAN_OK | path={out_path} | platform={platform} | scope={scope}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
