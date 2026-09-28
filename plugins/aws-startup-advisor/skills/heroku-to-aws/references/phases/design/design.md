---
_phase: design
_title: "Design AWS Architecture"
_requires_phase: clarify
_input:
  - heroku-resource-inventory.json
  - preferences.json
_knowledge:
  - { file: knowledge/design/dyno-eb-sizing.json, _when: "inventory has a formation AND (design_constraints.compute_target.default is elastic_beanstalk OR design_constraints.compute_target.value is elastic_beanstalk OR design_constraints.compute_target is absent OR any compute_target override is elastic_beanstalk)" }
  - { file: knowledge/design/dyno-fargate-sizing.json, _when: "inventory has a formation AND (design_constraints.compute_target.default is ecs-fargate OR design_constraints.compute_target.value is ecs-fargate OR design_constraints.compute_target.default is elastic_beanstalk OR design_constraints.compute_target.value is elastic_beanstalk OR design_constraints.compute_target is absent OR any compute_target override is ecs-fargate)" }
  - { file: knowledge/design/eks-pod-sizing.json, _when: "inventory has a formation AND (design_constraints.compute_target.default is eks-managed or eks-or-ecs OR design_constraints.compute_target.value is eks-managed or eks-or-ecs)" }
  - { file: knowledge/design/postgres-rds-sizing.json, _when: "inventory has a heroku-postgresql addon" }
  - { file: knowledge/design/redis-elasticache-sizing.json, _when: "inventory has a heroku-redis addon" }
  - { file: knowledge/design/kafka-msk-sizing.json, _when: "inventory has a heroku-kafka addon" }
  - { file: knowledge/design/fast-path-addons.json, _when: "inventory has a non-core addon (not postgresql/redis/kafka)" }
_fragments:
  - _id: mapping-engine
    _trigger: { _always: true }
    _file: phases/design/design-mapping.md
  - _id: eks-mapping
    _trigger: { _when: "preferences.design_constraints.compute_target.default is 'eks-managed' or 'eks-or-ecs' OR preferences.design_constraints.compute_target.value is 'eks-managed' or 'eks-or-ecs'" }
    _file: phases/design/design-eks.md
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
  - _check_file_exists: [heroku-resource-inventory.json, preferences.json]
    _on_failure: _unrecoverable
  - _validate_json: [heroku-resource-inventory.json, preferences.json]
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: aws-design.json
    _on_failure: _halt_and_inform
  - _validate_json: aws-design.json
    _on_failure: _halt_and_inform
  - _assert: "aws-design.json has phase == 'design' and a valid timestamp; services[] is present (empty only if all resources deferred)"
    _on_failure: _halt_and_inform
  - _assert: "every services[] entry has service_id, source_resource_id, heroku_app, aws_service, confidence, aws_config; every deferred[] entry has addon_name, addon_plan, provider, reason, recommendation"
    _on_failure: _halt_and_inform
  - _assert: "vpc_design is present with a valid mode (existing_vpc or new_vpc); if existing_vpc then existing_vpc_id is non-empty; if new_vpc then at least 2 subnets across separate AZs"
    _on_failure: _halt_and_inform
  - _assert: "metadata.total_services matches services[].length"
    _on_failure: _halt_and_inform
  - _assert: "no Fir-specific Terraform (ARM/Graviton, CNB) appears anywhere in output"
    _on_failure: _halt_and_inform
_forbids_files:
  - README.md
  - "*.txt"
  - "terraform/**"
  - MIGRATION_GUIDE.md
  - estimation-infra.json
---

# Phase 3: Design AWS Architecture

## Orientation

Single-pass mapping engine: translate each Heroku resource to its AWS equivalent
using deterministic lookup tables. No clustering, no dependency graphs — resources
are processed as a flat list in input order.

Composed of a mapping fragment + one assembler (declared in the frontmatter
`_fragments`/`_assemble`); the interpreter runs the fragments whose `_trigger` is
true, then the assembler, and evaluates the `_knowledge` `_when` guards to load only
the sizing tables the inventory needs (see `INTERPRETER.md` § `_knowledge`). The
compute target branch is selected by `design_constraints.compute_target`: Elastic
Beanstalk is the default, Fargate is the direct-container override, and EKS is the
Kubernetes-team alternative. The preferred shape is `compute_target.default` plus
per-formation `overrides[]`; legacy `compute_target.value` is accepted only for
reused older preferences. The EKS branch (`design-eks`, fired by its `_when` trigger
when the global compute target selects EKS) is an ALTERNATIVE path, not an addition:
it maps ALL formations to EKS pods + an `eks_cluster` aggregate instead of the
EB/Fargate paths. On the EB default path, persistent non-web formations with
`quantity > 1` route to Fargate to preserve Heroku worker capacity because EB
SingleInstance cannot horizontally scale that process model.

---

## Scope Boundary

**This phase covers Heroku → AWS Design ONLY.**

FORBIDDEN — Do NOT include ANY of:

- Cost estimates or pricing calculations (that is Phase 4 — Estimate)
- Terraform generation or HCL code (that is Phase 5 — Generate)
- Migration scripts or runbooks (that is Phase 5 — Generate)
- Data migration procedures (that is Phase 5 — Generate)
- Feedback collection or plan sharing (that is Phase 6 — Feedback)
- Clarify questions or preference gathering (that is Phase 2 — Clarify)
- Resource discovery or API calls (that is Phase 1 — Discover)

**Your ONLY job: Map each Heroku resource to its AWS equivalent. Nothing else.**
