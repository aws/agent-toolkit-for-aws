---
_phase: estimate
_title: "Estimate AWS Costs"
_requires_phase: design
_input:
  - aws-design.json
  - preferences.json
  - azure-resource-inventory.json
_knowledge:
  - { file: references/vendored/pricing/aws-infra-pricing.json }
  - { file: references/vendored/estimate/complexity-tiers.json }
  - { file: references/vendored/estimate/estimation-infra.schema.json }
  - { file: references/vendored/estimate/pricing-mode.md }
  - { file: references/vendored/estimate/ri-sp-eligibility.md }
  - { file: references/vendored/state/phase-status.schema.json }
  - { file: knowledge/estimate/rightsizing-thresholds.json }
  - { file: knowledge/estimate/estimate-defaults.json }
  - { file: references/shared/pricing-cache.md, _when: "ai-workload-profile.json exists in $MIGRATION_DIR" }
  - { file: references/shared/pricing-fallback.md, _when: "ai-workload-profile.json exists in $MIGRATION_DIR" }
  - { file: references/vendored/ai/ai-model-lifecycle.md, _when: "ai-workload-profile.json exists in $MIGRATION_DIR" }
  - { file: references/vendored/ai/bedrock-quotas.md, _when: "ai-workload-profile.json exists in $MIGRATION_DIR" }
_fragments:
  - _id: infra
    _trigger: { _always: true }
    _file: phases/estimate/estimate-infra.md
  - _id: ai
    _trigger: { _when: "ai-workload-profile.json exists in $MIGRATION_DIR" }
    _file: phases/estimate/estimate-ai.md
_assemble:
  _file: phases/estimate/estimate-assemble.md
_produces:
  - estimation-infra.json
  - estimation-ai.json
  - DECISION.md
_advances_to: generate
_re_entry_guard:
  _stale_if_completed: generate
  _stale_artifact: MIGRATION_GUIDE.md
  _on_reentry: stop_unless_confirmed
  _on_confirm: reset_downstream_to_pending
_preconditions:
  - _check_phase_completed: design
    _on_failure: _halt_and_inform
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _check_file_exists: [aws-design.json, preferences.json, azure-resource-inventory.json]
    _on_failure: _unrecoverable
  - _validate_json: [aws-design.json, preferences.json, azure-resource-inventory.json]
    _on_failure: _unrecoverable
  - _assert: "aws-design.json services[] exists and is non-empty, and every entry has aws_service and aws_config"
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: estimation-infra.json
    _on_failure: _halt_and_inform
  - _validate_json: estimation-infra.json
    _on_failure: _halt_and_inform
  - _assert: "projected_costs carries BOTH a 1:1 lift total and a right-sized total, and cost_comparison.rightsizing_delta states the difference between them"
    _on_failure: _halt_and_inform
  - _assert: "cost_comparison.rightsizing_delta.explanation is non-empty, and when the delta is 0 it states WHY — a $0 delta must be distinguishable from an uncomputed one"
    _on_failure: _halt_and_inform
  - _assert: "current_costs.source is one of {cost_management_export, consumption_data, user_stated, derived_from_skus, unavailable}, and baseline_note is present for every source except cost_management_export"
    _on_failure: _halt_and_inform
  - _assert: "reservation_substitutions is present as an array; empty is correct when the baseline carries no per-resource consumption figures. No resource was priced from a literal $0 consumption figure without a recorded substitution"
    _on_failure: _halt_and_inform
  - _assert: "optimization_opportunities is present as an array and follows references/vendored/estimate/ri-sp-eligibility.md's three-state rendering model. WHEN the design contains Fargate, EC2, or Lambda: a separate entry names Compute Savings Plan and attributes only those eligible services. WHEN the design contains provisioned RDS or Aurora: separate entries name Database Savings Plan and RDS Reserved Instances; they state that the products are mutually exclusive on the same workload. A generic 'commitment discounts' entry never substitutes for product-specific rows. Below the $50/month preliminary sizing threshold, retain each applicable product row with a null dollar value and its supported percentage range rather than omitting it. Compute Savings Plans remain percent-only until 30–90 days of AWS usage establishes a commitment floor. Every RI/Savings Plan rendering states that Activate credits do not cover upfront commitment costs"
    _on_failure: _halt_and_inform
  - _assert: "every rate key the design requires resolved to a rate row, or its line carries an exclusion_reason of 'no_rate', 'partial_rate' or 'no_quantity'. No line was priced from a neighbouring rate row of a different service, instance family, or operating system"
    _on_failure: _halt_and_inform
  - _assert: "every line whose design states license_model 'License Included', or otherwise states a Windows or SQL Server target, carries exclusion_reason 'partial_rate' with missing_component naming the licence, and is excluded from the totals — a Windows workload priced silently at the Linux rate is a gate failure"
    _on_failure: _halt_and_inform
  - _assert: "if any line carries an exclusion_reason then both totals carry is_floor true; if none does, neither total claims to be a floor"
    _on_failure: _halt_and_inform
  - _assert: "recommendation.outcome is one of {go, conditional_go, defer_for_evidence, stay}; conditions is a non-empty array when outcome is conditional_go; outcome 'stay' only ever accompanies path 'stay'"
    _on_failure: _halt_and_inform
  - _assert: "every service in aws-design.json services[] appears in the cost breakdown exactly once — priced, or carrying an exclusion_reason with excluded_from_total true. None silently dropped from the breakdown"
    _on_failure: _halt_and_inform
  - _assert: "each total equals the arithmetic sum of its own per-service costs, excluding every line that carries an exclusion_reason"
    _on_failure: _halt_and_inform
  - _assert: "complexity_tier is one of {small, medium, large} and complexity_inputs records the values it was derived from"
    _on_failure: _halt_and_inform
  - _assert: "a licensing_delta line is present if and only if preferences.json licensing._fired is true; when the Windows rate is unavailable its monthly_delta is null with a stated basis, never a remembered figure"
    _on_failure: _halt_and_inform
  - _assert: "no human labor, professional services, or people-time appears as a dollar figure or a one-time migration cost category"
    _on_failure: _halt_and_inform
  - _assert: "when the design's target_region differs from the pricing cache _meta.region, the mismatch is stated on the artifact and carried into recommendation.conditions"
    _on_failure: _halt_and_inform
  - _assert: "WHEN ai-workload-profile.json exists: estimation-ai.json exists, validates, and carries pricing_source (cached|live|cached_fallback|unavailable), cost_comparison with current_azure_monthly and projected_bedrock_monthly, and a recommendation whose path is migrate_optimized, migrate_phased, or stay. Traditional-AI workloads (document_extraction/image_analysis/speech_transcription) appear in services_not_estimated[], not in the token cost. When the profile is absent this is vacuously satisfied"
    _on_failure: _halt_and_inform
  - _assert: "run_mode is set in .phase-status.json to either 'decide' or 'decide_and_execute' — the decision gate was presented and answered"
    _on_failure: _halt_and_inform
  - _assert: "WHEN the user chose option A (run_mode == 'decide', current_phase == 'complete'): DECISION.md exists at $MIGRATION_DIR/DECISION.md — the plain-Markdown decision marker (verdict headline, cost table, migrate-if/stay-if, timeline band, top risks, assumptions, CTA line; no HTML). This is the standardized Assess-complete handoff artifact a downstream AI-rewrite path (e.g. llm-to-bedrock) reads alongside the run_mode/current_phase tuple. WHEN run_mode == 'decide_and_execute' (option C) it need not exist yet — Generate will produce the full report. See plan §19.13."
    _on_failure: _halt_and_inform
_forbids_files:
  - README.md
  - "*.txt"
  - "terraform/**"
  - MIGRATION_GUIDE.md
---

# Phase 4: Estimate AWS Costs

## Orientation

Price the design, and price it twice.

**Dual output is the default shape, not an option.** A non-optimized 1:1 lift and a
right-sized target are both reported, with the delta between them stated. The 1:1
number is what a naive migration costs and it is what the customer will otherwise
assume; the right-sized number is the recommendation. Showing only one of them either
overstates the bill or hides the work that produced the saving.

`estimation-infra.schema.json` has no `additionalProperties: false` and already
carries `cost_comparison` and `optimization_opportunities`, so this needs no schema
change — which matters, because that schema is vendored into several skills and
drift-allowlisted.

## The reservation `$0` trap

A reserved VM shows up at **`$0`** in consumption data. It is not free: it was
pre-paid. Pricing the Azure baseline from the literal figure understates current
spend, which makes the AWS comparison look worse than it is and can invert the
recommendation. Every reserved resource is priced from its pay-as-you-go rate
instead, and the substitution is recorded so the report can show its work.

**Not reachable yet.** A `$0` consumption figure only appears in Cost Management
or RDfA data, and both of those sources are deferred — so on a Terraform-only
estate `reservation_substitutions` is an empty array and this rule is a contract
for when the billing source lands, not something a run has tested. The empty array
is written rather than omitted so that its emptiness is visible.

## Metrics lookback affects confidence

Read the actual metrics window from the report metadata rather than assuming 31
days. Below `confidence_rules.min_window_days` in
`knowledge/estimate/rightsizing-thresholds.json`, hold right-sizing confidence at
`inferred` — a P95 over a short window is not a measurement.

## What this phase can and cannot know today

Stated up front, because three of these look like bugs otherwise and a reader who
assumes otherwise will misread the output.

| Constraint                                       | Consequence                                                                                                                                    |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| No billing or metrics source is built            | The Azure baseline is the user's stated figure or nothing — see `estimate-infra.md` Part 1. Rungs 1, 2 and 4 cannot fire                       |
| The reservation `$0` rule needs consumption data | It is a **contract for later**, not something a Terraform-only run exercises. `reservation_substitutions` is legitimately an empty array       |
| Utilization-based right-sizing needs metrics     | The right-sizing delta comes from **declared waste** only, and may legitimately be `$0`. When it is, the artifact must say why                 |
| The pricing cache is `us-east-1`                 | Most Azure estates map to another AWS region, so the region mismatch fires on most runs and must be stated rather than absorbed                |
| Three services have no rates anywhere            | DocumentDB, FSx for Windows, and the Windows licence adder. Their lines are `unavailable` or `partial`, and both totals then become **floors** |

None of these is a reason to produce a number anyway. A floor that says it is a
floor is useful; a total that quietly omits the most expensive line is not.

## Step: Run the phase

1. Execute `references/vendored/estimate/pricing-mode.md` as Step 0 — including
   its region check and its **rate-row** check, which is the one that fires here.
2. Run each fragment whose `_trigger` holds.
3. Run `estimate-assemble.md`, which reconciles the totals, presents the decision
   gate, and writes `run_mode`.
4. Evaluate `_postconditions`. On all-pass emit `HANDOFF_OK`; on any failure emit
   `GATE_FAIL` and stop. Never edit the artifact to make a gate pass.

## Not in this phase

Financial analysis only. No mapping changes (those belong to Design), no
Terraform, no runbooks, no week-by-week schedule — the decision gate's one-line
timeline band is the single allowed exception — and **no staffing or people-time
in any dollar column**.
