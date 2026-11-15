---
_phase: design
_title: "Design AWS Architecture"
_requires_phase: clarify
_input:
  - render-resource-inventory.json
  - render-resource-clusters.json
  - preferences.json
  - { file: ai-workload-profile.json, _when: "AI discovery produced the profile" }
_knowledge:
  - { file: references/shared/schema-design-aws.md }
  - { file: references/shared/schema-render-aws-design.json }
  - { file: knowledge/design/fast-path-services.json }
  - { file: knowledge/design/render-region-map.json }
  - { file: knowledge/design/service-plan-eb-sizing.json, _when: "a traditional Elastic Beanstalk target is eligible" }
  - { file: knowledge/design/service-plan-fargate-sizing.json, _when: "an ECS/Fargate service or task is eligible" }
  - { file: knowledge/design/postgres-rds-sizing.json, _when: "the inventory contains PostgreSQL" }
  - { file: knowledge/design/keyvalue-elasticache-sizing.json, _when: "the inventory contains Key Value" }
  - { file: knowledge/design/disk-storage-routing.json, _when: "the inventory contains a persistent disk" }
_fragments:
  - _id: infra
    _trigger: { _always: true }
    _file: phases/design/design-infra.md
_assemble:
  _file: phases/design/design-assemble.md
_produces:
  - aws-design.json
_advances_to: estimate
_re_entry_guard:
  _stale_if_completed: estimate
  _stale_artifact: estimation-infra.json
  _on_reentry: stop_unless_confirmed
  _on_confirm: reset_downstream_to_pending
_preconditions:
  - _check_phase_completed: clarify
    _on_failure: _halt_and_inform
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _check_file_exists: [render-resource-inventory.json, render-resource-clusters.json, preferences.json]
    _on_failure: _unrecoverable
  - _validate_json: [render-resource-inventory.json, render-resource-clusters.json, preferences.json]
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: aws-design.json
    _on_failure: _halt_and_inform
  - _validate_json: aws-design.json
    _on_failure: _halt_and_inform
  - _assert: "the design validates against schema-render-aws-design.json and its input fingerprints match the raw input bytes"
    _on_failure: _halt_and_inform
  - _assert: "every inventory resource ID occurs exactly once in mappings and accounting; every mapping has one concrete aws_service and a complete selector decision"
    _on_failure: _halt_and_inform
  - _assert: "every candidate not selected by an applicable selector appears exactly once in rejected_candidates with a concrete reason"
    _on_failure: _halt_and_inform
  - _assert: "PostgreSQL, disks, Workflows, Workflow tasks, workers, and cron contain no unresolved alternatives"
    _on_failure: _halt_and_inform
  - _assert: "App Runner and public ingress for private-only services do not appear without an explicit contradicted-source finding"
    _on_failure: _halt_and_inform
  - _assert: "when an AI profile exists the only AI execution track has status deferred_shared_ai_engine and no AI target, model, estimate, adapter, or Terraform is present"
    _on_failure: _halt_and_inform
_forbids_files:
  - estimation-infra.json
  - "terraform/**"
---

# Phase 3: Design AWS architecture

Apply this precedence exactly: skip mappings, approved specialist handling, technical eliminators, deterministic mappings, cluster constraints, rubric selection, preferred-target substitution, then post-selection sizing and CPU architecture. A cluster may narrow a rubric but cannot override a deterministic mapping.

A selector is an ordered first-decisive-rule procedure. It emits one winner, ordered evidence, rules evaluated/fired, questions/defaults used, and every rejected candidate. If a decisive input is absent and no named startup default applies, stop and return to Clarify. Never emit an unresolved choice list.
