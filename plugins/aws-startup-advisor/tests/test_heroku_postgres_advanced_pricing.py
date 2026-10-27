"""Guard: Heroku Postgres Advanced tier pricing is modeled, not silently omitted.

Design: .agents/tasks/heroku-postgres-advanced-pricing/design.md

Heroku Postgres Advanced bills compute by the compute-month (not a flat
plan-name -> $/month lookup like every other row in
`heroku-pricing-cache.md`) and bills storage overage separately. Before this
change, an Advanced-tier `heroku-postgresql` addon had no row in the cache's
flat tables, so it fell through the pricing cache's rung-3 lookup, was marked
`"unpriced_heroku"`, and was silently excluded from the Heroku cost total —
materially wrong for a tier whose compute line alone runs $150-$900+/month
and whose storage overage can exceed the compute line for large,
storage-heavy clusters.

This is a documentation-contract check (string/shape assertions against the
markdown), matching the existing `test_cost_completeness.py` /
`test_decision_gate_wiring.py` pattern — this plugin's skill files are
instructions read by an LLM agent, not executable code, so there is no
runtime harness to exercise instead.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

PRICING_CACHE = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "shared"
    / "heroku-pricing-cache.md"
)

COST_ENGINE = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "phases"
    / "estimate"
    / "estimate-cost-engine.md"
)

GENERATE_REPORT = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "phases"
    / "generate"
    / "generate-report.md"
)

CAPTURE_MD = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-live-capture.md"
)

DISCOVER_LIVE = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "phases"
    / "discover"
    / "discover-live.md"
)

SCHEMA_HEROKU = (
    PLUGIN_ROOT
    / "skills"
    / "heroku-to-aws"
    / "references"
    / "shared"
    / "schema-discover-heroku.md"
)

ADVANCED_LEVELS = [
    "4G-Performance",
    "8G-Performance",
    "16G-Performance",
    "32G-Performance",
    "64G-Performance",
    "128G-Performance",
    "256G-Performance",
    "384G-Performance",
    "512G-Performance",
    "768G-Performance",
    "1536G-Performance",
]

# Rates could not be confirmed from Heroku's static docs (JS-rendered
# Elements calculator) — these rows must be marked "unverified", not guessed.
UNVERIFIED_LEVELS = [
    "64G-Performance",
    "128G-Performance",
    "256G-Performance",
    "384G-Performance",
    "512G-Performance",
    "768G-Performance",
    "1536G-Performance",
]

# Confirmed rates (from Heroku's static docs) — must remain real numbers.
CONFIRMED_LEVEL_RATES = {
    "4G-Performance": "150",
    "8G-Performance": "300",
    "16G-Performance": "500",
    "32G-Performance": "900",
}


def test_pricing_cache_has_advanced_tier_heading() -> None:
    text = PRICING_CACHE.read_text(encoding="utf-8")
    assert "### Advanced Tier" in text


def test_pricing_cache_advanced_tier_lists_all_eleven_levels() -> None:
    text = PRICING_CACHE.read_text(encoding="utf-8")
    advanced_idx = text.index("### Advanced Tier")
    deprecated_idx = text.index("### Deprecated Plans")
    section = text[advanced_idx:deprecated_idx]
    for level in ADVANCED_LEVELS:
        assert level in section, f"Advanced Tier section missing level {level}"


def test_pricing_cache_advanced_tier_marks_unconfirmed_rates_unverified() -> None:
    text = PRICING_CACHE.read_text(encoding="utf-8")
    advanced_idx = text.index("### Advanced Tier")
    deprecated_idx = text.index("### Deprecated Plans")
    section = text[advanced_idx:deprecated_idx]
    assert section.count("unverified") >= len(UNVERIFIED_LEVELS), (
        "Expected one 'unverified' marker per unconfirmed Advanced Tier level"
    )
    for level, rate in CONFIRMED_LEVEL_RATES.items():
        # Confirmed levels must carry a real numeric rate, not "unverified".
        row_idx = section.index(level)
        row_line = section[row_idx: section.index("\n", row_idx)]
        assert "unverified" not in row_line, (
            f"{level} is a confirmed rate and must not be marked unverified"
        )
        assert rate in row_line, f"{level} row missing expected rate {rate}"


def test_pricing_cache_advanced_tier_states_storage_overage_rate() -> None:
    text = PRICING_CACHE.read_text(encoding="utf-8")
    assert "100 GB" in text
    assert "$0.20 per GB-month" in text


def test_pricing_cache_usage_rules_document_advanced_formula() -> None:
    text = PRICING_CACHE.read_text(encoding="utf-8")
    usage_rules_idx = text.index("## Usage Rules")
    rules = text[usage_rules_idx:]
    assert "compute-month" in rules
    assert "data_size_gb" in rules
    assert "unpriced_heroku" in rules


def test_pricing_cache_advanced_tier_documents_multi_pool_known_limitation() -> None:
    # Original design (§2.3, §3.4) required this gap be either resolved or
    # explicitly documented as a known limitation. It was NOT resolved in that
    # round (Discover's addon schema had no pool-count field at the time), so
    # the cache documented it as a known limitation and priced one instance
    # only. This PR's fix resolves the gap for LIVE discovery: Discover now
    # captures `data:pg:info` and populates `advanced_pools[]` with per-pool
    # level/instance_count/ha, so the formula sums `rate[level] × instance_count`
    # across every captured pool. The known-limitation note is now narrowed to
    # Terraform-only discovery (no live capture → no `advanced_pools` → cache
    # miss), not "every Advanced addon is under-priced".
    text = PRICING_CACHE.read_text(encoding="utf-8")
    advanced_idx = text.index("### Advanced Tier")
    deprecated_idx = text.index("### Deprecated Plans")
    section = text[advanced_idx:deprecated_idx]
    assert "Known limitation" in section
    assert "advanced_pools" in section
    assert "Terraform" in section
    assert "unpriced_heroku" in section

    usage_rules_idx = text.index("## Usage Rules")
    rules = text[usage_rules_idx:]
    assert "instance_count" in rules, (
        "Usage Rule 9 must reference the advanced_pools[].instance_count field "
        "now that Discover populates it from live data:pg:info captures"
    )
    assert "advanced_pools" in rules
    assert "rate[pool.level] × pool.instance_count" in rules or "rate[pool.level] x pool.instance_count" in rules


def test_pricing_cache_classic_tier_rows_untouched() -> None:
    # Guard against accidental edits to existing flat-lookup Classic rows.
    text = PRICING_CACHE.read_text(encoding="utf-8")
    assert "| standard-0 | 50      | 4 GB   | 64 GB   | 200         |" in text
    assert "| premium-0 | 200     | 4 GB   | 64 GB   | 200         |" in text
    assert "| private-0 | 200     | 4 GB   | 64 GB   | 200         |" in text
    assert "| shield-0 | 200     | 4 GB   | 64 GB   | 200         |" in text


def test_generate_report_requires_rendering_baseline_note() -> None:
    # Review finding (leon1418, PR #434, P2): appending baseline_note at
    # capture time does nothing if the saved-report generator never reads or
    # renders it. generate-report.md's Step 1 figure-gathering list and its
    # exec-costs section definition must both name baseline_note explicitly
    # — report-decision-core.md reuses these same exec-costs rules for the
    # decision HTML / DECISION.md twin, so fixing it here covers both modes.
    text = GENERATE_REPORT.read_text(encoding="utf-8")
    step1_idx = text.index("## Step 1: Gather figures")
    step2_idx = text.index("## Step 2:")
    step1 = text[step1_idx:step2_idx]
    assert "baseline_note" in step1, (
        "Step 1 must gather current_costs.baseline_note so it is available "
        "to render in exec-costs — a derived-baseline caveat (e.g. the "
        "Postgres Advanced full-month assumption) that is never gathered "
        "can never reach the saved report."
    )

    exec_costs_idx = text.index("| `exec-costs`")
    exec_costs_row_end = text.index("\n", exec_costs_idx)
    exec_costs_row = text[exec_costs_idx:exec_costs_row_end]
    assert "baseline_note" in exec_costs_row, (
        "exec-costs's own section definition must require rendering "
        "baseline_note next to the Heroku current-monthly figure, not just "
        "list it as a gathered field"
    )


def test_cost_engine_rung3_references_advanced_tier_formula() -> None:
    text = COST_ENGINE.read_text(encoding="utf-8")
    rung3_idx = text.index("3. **Heroku pricing cache**")
    rung4_idx = text.index("4. **User-provided**")
    rung3 = text[rung3_idx:rung4_idx]
    assert "Heroku Postgres Advanced" in rung3
    assert "data_size_gb" in rung3
    assert "baseline_note" in rung3
    assert "instance_count" in rung3, (
        "rung-3 must reference advanced_pools[].instance_count now that "
        "Discover populates it from live data:pg:info captures"
    )
    assert "advanced_pools" in rung3
    assert "Terraform" in rung3 and "unpriced_heroku" in rung3


def test_discover_live_capture_probes_both_postgres_tiers() -> None:
    text = CAPTURE_MD.read_text(encoding="utf-8")
    assert "heroku data:pg:info" in text
    assert "heroku pg:info" in text
    assert "pg-advanced-<app>-<addon_name>.out" in text
    assert "pg-<app>.out" in text
    step3c_idx = text.index("3c. Per-command error handling")
    step3c = text[step3c_idx:]
    assert "skipped" in step3c
    assert "tier" in step3c.lower()


def test_discover_live_parses_advanced_pool_blocks() -> None:
    text = DISCOVER_LIVE.read_text(encoding="utf-8")
    assert "pg-advanced-<app>-<addon_name>.out" in text
    assert "instances of" in text
    assert "(HA)" in text
    assert "advanced_pools" in text
    assert "tier" in text
    assert "pg-<app>.out" in text


def test_discover_live_associates_each_database_by_addon_name_not_just_app() -> None:
    # Round 4 Finding A: an app can have multiple heroku-postgresql add-ons; each
    # one's capture file and pool data must attach to that add-on's own resource
    # entry, not fan out across every Postgres add-on on the app.
    text = DISCOVER_LIVE.read_text(encoding="utf-8")
    assert "pg-advanced-<app>-<addon_name>.out" in text
    assert "multiple Postgres add-ons" in text
    assert "never fan out one add-on's" in text or "never fan out" in text


def test_discover_live_capture_row_7b_passes_explicit_database_identifier() -> None:
    # Round 4 Finding A: data:pg:info declares `database` REQUIRED and resolves
    # exactly one add-on via AddonResolver — `-a <app>` alone (no identifier) is
    # invalid Heroku CLI usage. Row 7b must pass each add-on's name explicitly
    # and the output filename must encode that add-on's identity so apps with
    # multiple Postgres add-ons don't collide on one file.
    text = CAPTURE_MD.read_text(encoding="utf-8")
    assert "heroku data:pg:info -a <app>" not in text, (
        "Row 7b must not call data:pg:info with only -a <app> — the database "
        "argument is required"
    )
    assert "heroku data:pg:info <addon_name> -a <app>" in text
    assert "pg-advanced-<app>-<addon_name>.out" in text
    row7b_note_idx = text.index("**Row 7b note:**")
    row7b_note = text[row7b_note_idx:]
    assert "not confirmed against a live Advanced account" not in row7b_note
    assert "REQUIRED" in row7b_note
    assert "AddonResolver" in row7b_note


def test_cost_engine_rung2_prices_advanced_tier_via_pool_sum_not_flat_price() -> None:
    # Round 4 Finding B: an Advanced-tier add-on with plan.price.cents == 0 must
    # never flow into the flat monthly_price_usd sum at rung 2 — it must be
    # routed to the pool-pricing formula (worked example: four 4G-Performance
    # instances × $150 = $600), matching rung 3's existing Advanced-tier
    # handling.
    text = COST_ENGINE.read_text(encoding="utf-8")
    rung2_idx = text.index("2. **Live-captured prices")
    rung3_idx = text.index("3. **Heroku pricing cache**")
    rung2 = text[rung2_idx:rung3_idx]
    assert 'tier == "advanced"' in rung2
    assert "advanced_pools" in rung2
    assert "rate[pool.level]" in rung2
    assert "instance_count" in rung2


def test_cost_engine_marks_advanced_tier_unpriced_when_pool_data_missing() -> None:
    # Both rung 2 and rung 3 must mark an Advanced-tier add-on with no/empty
    # advanced_pools (failed/skipped capture) as "unpriced_heroku" rather than
    # silently contributing $0.
    text = COST_ENGINE.read_text(encoding="utf-8")
    rung2_idx = text.index("2. **Live-captured prices")
    rung3_idx = text.index("3. **Heroku pricing cache**")
    rung4_idx = text.index("4. **User-provided**")
    rung2 = text[rung2_idx:rung3_idx]
    rung3 = text[rung3_idx:rung4_idx]
    assert "unpriced_heroku" in rung2, (
        "rung 2 must mark Advanced-tier add-ons with missing pool data "
        "unpriced_heroku, not $0"
    )
    assert "unpriced_heroku" in rung3


def test_schema_documents_advanced_tier_fields() -> None:
    text = SCHEMA_HEROKU.read_text(encoding="utf-8")
    assert "tier" in text
    assert "advanced_pools" in text
    assert "instance_count" in text
    assert "leader" in text
    assert "follower" in text


# --- Round 6: Advanced-family detection must survive failed/skipped captures ---
#
# Reviewer finding (leon1418, PR #434, databaseId 4242785449,
# estimate-cost-engine.md): round 4/5 gated the Advanced exception on
# `config.tier == "advanced"`, but `tier` is set ONLY by a successful
# `data:pg:info` capture (see discover-live.md). A failed, skipped, or
# malformed capture leaves a record with NO `tier` at all, e.g. the exact
# failure shape:
#   {"addon_service": "heroku-postgresql", "plan": "advanced",
#    "provider": "heroku", "monthly_price_usd": 0}
# That record never matched `tier == "advanced"`, so it fell through to the
# flat monthly_price_usd sum and contributed exactly $0 for a real Advanced
# database. The fix gates on the preserved `addon_service`/`plan` identity
# instead, which survives capture failure, and only consults `tier` /
# `advanced_pools` after the identity match to decide the pool-sum vs.
# unpriced_heroku branch.


def test_cost_engine_rung2_detects_advanced_family_by_identity_not_tier() -> None:
    text = COST_ENGINE.read_text(encoding="utf-8")
    rung2_idx = text.index("2. **Live-captured prices")
    rung3_idx = text.index("3. **Heroku pricing cache**")
    rung2 = text[rung2_idx:rung3_idx]
    assert 'addon_service == "heroku-postgresql"' in rung2
    assert 'plan' in rung2 and '== "advanced"' in rung2
    # The identity check must appear before the first `tier ==` condition —
    # i.e. it is the gate, not nested inside a tier-gated clause.
    identity_pos = rung2.index('addon_service == "heroku-postgresql"')
    tier_pos = rung2.index('tier ==')
    assert identity_pos < tier_pos, (
        "the addon_service/plan identity check must be evaluated BEFORE any "
        "tier == condition, not nested inside one"
    )


def test_cost_engine_rung2_marks_failed_capture_record_unpriced_not_zero() -> None:
    """Reviewer's exact failure-shape record (databaseId 4242785449):

    {"addon_service": "heroku-postgresql", "plan": "advanced",
     "provider": "heroku", "monthly_price_usd": 0}

    No `tier` key at all — this must be marked "unpriced_heroku", never
    contribute $0 to the flat sum.
    """
    text = COST_ENGINE.read_text(encoding="utf-8")
    rung2_idx = text.index("2. **Live-captured prices")
    rung3_idx = text.index("3. **Heroku pricing cache**")
    rung2 = text[rung2_idx:rung3_idx]
    assert "unpriced_heroku" in rung2
    identity_pos = rung2.index('addon_service == "heroku-postgresql"')
    nearby = rung2[identity_pos:identity_pos + 2500]
    assert "failed" in nearby or "skipped" in nearby or "malformed" in nearby, (
        "rung 2 must explicitly name the failed/skipped/malformed no-tier "
        "case near the identity check"
    )
    assert "unpriced_heroku" in nearby
    assert "do NOT" in nearby and "$0" in nearby


def test_cost_engine_rung2_covers_private_and_shield_advanced_variants() -> None:
    text = COST_ENGINE.read_text(encoding="utf-8")
    rung2_idx = text.index("2. **Live-captured prices")
    rung3_idx = text.index("3. **Heroku pricing cache**")
    rung2 = text[rung2_idx:rung3_idx]
    assert "Private" in rung2
    assert "Shield" in rung2


def test_cost_engine_rung3_detects_advanced_family_by_identity_not_tier() -> None:
    text = COST_ENGINE.read_text(encoding="utf-8")
    rung3_idx = text.index("3. **Heroku pricing cache**")
    rung4_idx = text.index("4. **User-provided**")
    rung3 = text[rung3_idx:rung4_idx]
    assert 'addon_service == "heroku-postgresql"' in rung3
    assert 'plan' in rung3 and '== "advanced"' in rung3
    identity_pos = rung3.index('addon_service == "heroku-postgresql"')
    tier_pos = rung3.index('tier ==')
    assert identity_pos < tier_pos, (
        "rung 3's identity check must gate before any tier == condition"
    )


def test_cost_engine_rung3_covers_failed_capture_and_private_shield() -> None:
    text = COST_ENGINE.read_text(encoding="utf-8")
    rung3_idx = text.index("3. **Heroku pricing cache**")
    rung4_idx = text.index("4. **User-provided**")
    rung3 = text[rung3_idx:rung4_idx]
    assert "Private" in rung3
    assert "Shield" in rung3
    assert "failed" in rung3 or "skipped" in rung3 or "malformed" in rung3
    assert "unpriced_heroku" in rung3


def test_pricing_cache_rule9_gates_on_identity_not_tier() -> None:
    text = PRICING_CACHE.read_text(encoding="utf-8")
    usage_rules_idx = text.index("## Usage Rules")
    rule9_idx = text.index("9. **Heroku Postgres Advanced", usage_rules_idx)
    rule9 = text[rule9_idx:]
    assert 'addon_service == "heroku-postgresql"' in rule9
    assert 'plan' in rule9 and '== "advanced"' in rule9
    identity_pos = rule9.index('addon_service == "heroku-postgresql"')
    tier_pos = rule9.index('tier ==')
    assert identity_pos < tier_pos, (
        "rule 9's identity check must gate before any tier == condition"
    )
    # Pricing math is unchanged — still keyed off instance_count/advanced_pools.
    assert "instance_count" in rule9
    assert "advanced_pools" in rule9
    assert "unpriced_heroku" in rule9
