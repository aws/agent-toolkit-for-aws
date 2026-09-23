---
_assemble: assemble-migration-plan
_of_phase: migration-plan
_reads:
  - injected constraints translated from design.json / confirm.json / answers (built inline in migration-plan.md Step 2)
  - gcp global-constraints fragment
_produces:
  - migration-plan-injection.json
---

# Migration Plan — Assemble the injection context

> **Assembler unit.** The Migration Plan phase resolves the target repo,
> translates the advisor's decisions into the engine's (gcp-to-aws) constraint
> fields, and writes `migration-plan-injection.json`
> inline within `migration-plan.md` (Step 2). It then executes the engine's
> Discover → Clarify → Design → Estimate → Generate phases inline and records
> `migration_plan_ctx` in the run state. This unit records the artifact-level
> contract for the phase: it is the single creator of
> `migration-plan-injection.json`, and its postconditions (declared on the
> phase) are the phase's completion gate. See `migration-plan.md` § Steps 2–5.
> Note: an idea-only migrate has nothing to migrate — the phase sets
> `migration_plan = not_applicable` and stops before writing the injection
> (the conditional `_produces` reflects this).
