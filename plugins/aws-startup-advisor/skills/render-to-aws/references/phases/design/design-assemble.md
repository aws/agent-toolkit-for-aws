---
_assemble: assemble-design
_of_phase: design
_reads:
  - infra
_produces:
  - aws-design.json
---

# Assemble AWS design

Order mappings by source resource ID bytes. Order each decision's evidence, evaluated rules, fired rules, questions, defaults, and rejected candidates by their explicit ordinal and reject duplicate ordinals or candidate names.

Re-read the inventory and verify all of these invariants before writing:

1. The set of mapping source IDs and accounting IDs equals the inventory resource-ID set; counts match and no ID occurs twice.
2. Every mapping has exactly one concrete `aws_service`; no slash-delimited, “or”, candidate-array, pending, or unknown target is permitted.
3. The candidate set declared by the selector equals the winner plus rejected candidates exactly once.
4. Database, storage, workflow, worker, and cron decisions conform to their ordered procedures. Private services have no public ingress by default. App Runner is forbidden.
5. AI state, when present, is exactly `deferred_shared_ai_engine`; infrastructure remains completed and no AI execution output exists.

Any missing decisive fact returns a structured list of preference question IDs to Clarify and emits `GATE_FAIL`; do not write a completed design. Otherwise validate `schema-render-aws-design.json` and atomically write canonical JSON.
