---
_phase: estimate
_title: "Estimate AWS Costs"
_requires_phase: design
_input:
  - render-resource-inventory.json
  - preferences.json
  - aws-design.json
_knowledge:
  - { file: references/vendored/pricing/aws-infra-pricing.json }
  - { file: references/vendored/estimate/complexity-tiers.json }
  - { file: references/vendored/estimate/estimation-infra.schema.json }
  - { file: references/vendored/estimate/pricing-mode.md }
  - { file: references/vendored/estimate/ri-sp-eligibility.md }
  - { file: knowledge/estimate/estimate-defaults.json }
  - { file: knowledge/estimate/rightsizing-thresholds.json }
  - { file: knowledge/estimate/render-pricing-cache.json }
_fragments:
  - _id: infra
    _trigger: { _always: true }
    _file: phases/estimate/estimate-infra.md
_assemble:
  _file: phases/estimate/estimate-assemble.md
_produces:
  - estimation-infra.json
_advances_to: generate
_re_entry_guard:
  _stale_if_completed: generate
  _stale_artifact: migration-report.html
  _on_reentry: stop_unless_confirmed
  _on_confirm: reset_downstream_to_pending
_preconditions:
  - _check_phase_completed: design
    _on_failure: _halt_and_inform
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _check_file_exists: [render-resource-inventory.json, preferences.json, aws-design.json]
    _on_failure: _unrecoverable
  - _validate_json: [render-resource-inventory.json, preferences.json, aws-design.json]
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: estimation-infra.json
    _on_failure: _halt_and_inform
  - _validate_json: estimation-infra.json
    _on_failure: _halt_and_inform
  - _assert: "capacity-preserving and right-sized line totals reconcile independently, and delta equals right-sized minus capacity-preserving"
    _on_failure: _halt_and_inform
  - _assert: "an unpriced line is excluded from numeric sums and makes the applicable total an explicit floor"
    _on_failure: _halt_and_inform
  - _assert: "no resource was down-sized unless every numeric sufficiency threshold passed; stale or unmatched Render pricing is unavailable"
    _on_failure: _halt_and_inform
  - _assert: "AI execution remains deferred_shared_ai_engine and contributes no fabricated AI cost"
    _on_failure: _halt_and_inform
_forbids_files:
  - "terraform/**"
  - MIGRATION_GUIDE.md
---

# Phase 4: Estimate AWS costs

Price only the selected infrastructure design. Produce a capacity-preserving AWS total and a right-sized AWS total, then the signed delta (`right_sized - capacity_preserving`) and a plain-language explanation. All arithmetic uses decimal inputs, rounds line items to two decimals with half-even rounding, and sums rounded lines in source-resource-ID byte order.

Source Render cost uses customer invoice/export first, user-stated monthly amount second, a fresh exact plan match in `render-pricing-cache.json` third, and `unavailable` otherwise. Do not recall a price from prose. AI execution contributes no cost while deferred.

After outer completion, retain `current_phase: estimate`, resolve the optional workshop, then present the opt-in decision. Only that decision writes `run_mode`.
