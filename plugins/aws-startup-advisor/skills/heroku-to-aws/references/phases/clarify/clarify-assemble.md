---
_assemble: assemble-preferences
_of_phase: clarify
_reads:
  - interview (fragment contribution)
_produces:
  - preferences.json
---

# Clarify — Assemble and Validate preferences.json

> **Assembler unit.** Runs after the interview fragment (`clarify-interview.md`)
> has collected and interpreted the answers. It assembles the final
> `preferences.json`, enforces the validation checklist + completion handoff gate,
> and updates `.phase-status.json`. It owns the artifact-level contract for this
> phase (this is a pure validator/finalizer — the interview created the answers,
> the assembler owns the final schema + gate).

---

## Step 4: Assemble and Write preferences.json

Assemble all interpreted answers into the final `$MIGRATION_DIR/preferences.json` from the current session's answers. Set `metadata.timestamp` to the current time.

Write `$MIGRATION_DIR/preferences.json`:

```json
{
  "migration_id": "<from .phase-status.json>",
  "skill": "heroku-to-aws",
  "metadata": {
    "timestamp": "<ISO timestamp>",
    "clarify_mode": "full|fast_path",
    "questions_asked": ["Q1", "Q2", ...],
    "questions_defaulted": ["Q7", "Q8", ...],
    "questions_skipped_extracted": ["Q6", "Q12b", ...],
    "questions_skipped_not_applicable": ["Q6", "Q8", ...],
    "questions_deferred_to_generate": ["Q4", "Q6c", "Q12d"],
    "inventory_clarifications": {"database_ha": "plan:premium-0"}
  },
  "global": {
    "target_region": "<Q1 value>",
    "compliance": "<Q2 value>",
    "availability": "<Q3 value>",
    "maintenance_window": "<Q4 value>",
    "environment_naming": "<Q5 value>",
    "migration_approach": "<Q6b value>",
    "interim_cutover": false,
    "target_exit_date": "<ISO date or null>",
    "ktlo_warning": "<warning text or null>",
    "fir_intent": "<Q11 value or null>"
  },
  "data": {
    "database_ha": "<Q6 value>",
    "migration_method": "<Q6c value>",
    "estimated_db_size_gb": "<derived or user-provided>",
    "db_size_source": "live_capture|plan_derived|user_override",
    "redis_ha": "<Q7 value>",
    "kafka_retention_days": "<Q8 value>",
    "dns_strategy": "<Q10 value>"
  },
  "network": {
    "existing_vpc_id": "<Q9b value or null>",
    "subnet_ids": ["<Q9 values>"],
    "private_space_detected": true|false
  },
  "operational": {
    "container_registry": "<Q12 value>",
    "containerization_status": "<Q12b value>",
    "log_retention_days": "<Q13 value>",
    "alerting": "<Q14 value>",
    "cost_optimization": "<Q15 value>"
  },
  "design_constraints": {
    "compute_target": {
      "default": "<Q12c default target: elastic_beanstalk|ecs-fargate|eks-managed|eks-or-ecs>",
      "overrides": [
        {
          "formation": "<heroku_app>:<process_type>",
          "value": "<elastic_beanstalk|ecs-fargate>",
          "reason": "<why this formation differs from the default>",
          "chosen_by": "user|system_forced"
        }
      ],
      "chosen_by": "user|system_recommended|default",
      "recommendation": {
        "value": "elastic_beanstalk|ecs-fargate|eks-managed|eks-or-ecs|mixed",
        "confidence": "high|medium|low",
        "reasons": ["<short reason strings>"]
      }
    },
    "eb_deploy_method": { "value": "<Q12d value; omit when resolved compute plan has no EB formations>", "chosen_by": "user|default" }
  },
  "defaults_applied": ["<list of defaulted question IDs>"],
  "sources": {
    "Q1": "user|extracted|default",
    "Q2": "user|extracted|default",
    ...
  }
}
```

Do **not** write a `workshop` object from Clarify. The what-if workshop
(`references/phases/workshop/`) creates/patches `preferences.workshop` later
(`cpu_architecture`, `active`, `active_scenario_id`, `last_sheet_at`). See
`references/shared/schema-workshop-scenarios.md`.

### Schema Rules

1. The `sources` object records how each question was answered: `"user"` (explicitly answered, corrected on the Assumption Sheet or from the Decision gate's "Assumptions behind this number" block, or changed as a knob in the what-if workshop sheet — `workshop-refresh.md` § 3), `"extracted"` (resolved from the inventory — a Detected sheet row on the full flow, or applied directly on the fast path), `"default"` (system default applied, including skipped questions, sheet-confirmed defaults, "use defaults for the rest", and a fast-path proposed default such as a Common Runtime region or a tier-derived `database_ha` that disagreed with Q3). These three are the complete enum; every ID in `metadata.questions_skipped_extracted` has `sources.<QID>: "extracted"`, and extracted fields carry the catalog's type and enum (interview § Extraction Rules), never a raw signal.
2. `defaults_applied` is the array of question IDs that received default values.
3a. `metadata.questions_deferred_to_generate` records the execution-only questions (Q4 maintenance window, Q6c DB migration method, Q12d EB deploy method — each only when it fires) whose documented default was written here and which are **asked for real at the Decision gate's [C] Generate** (`estimate-assemble.md` § Confirm execution choices) before `generate.md` loads. Nothing before Generate reads these three fields. Their `sources` entry is `"default"` until that step rewrites it to `"user"` and empties the array — or until the user answers one early from the Decision gate's "Assumptions behind this number" block, which rewrites that one entry and removes only that ID (`estimate-assemble.md` § Handling a correction, step 2). An empty or shortened array is a valid state, not a missing field. A `preferences.json` written before this field existed has no array at all; interview Step 0 (reuse) rebuilds it from the `sources` entries (and `eb_deploy_method.chosen_by` for Q12d) instead of re-defaulting answers the user already gave — a question that never fired gets its documented default and `sources.<QID>: "default"` written before it is listed, so every listed ID passes the checklist line below.
3. `metadata.questions_skipped_not_applicable` records questions skipped because their triggering condition was not met (e.g., Q6 skipped because no Postgres). `metadata.questions_skipped_extracted` records questions **Detected** from the inventory (interview Step 2 § Extraction Rules, run in Step 1); a **Proposed default** read from the inventory (Common Runtime region, `mini`/hobby Redis tier) goes in `metadata.questions_defaulted` instead. In both cases the raw signal goes in `metadata.inventory_clarifications` (e.g. `{"database_ha": "plan:premium-0"}`).
4. Only write keys with non-null values. Omit sections/keys that are entirely null.
5. `global.fir_intent` is `null` when no Fir apps detected (Q11 not fired).
6. `network.existing_vpc_id` and `network.subnet_ids` are `null`/empty when no Private Space peering exists.
7. `data.database_ha`, `data.redis_ha`, `data.kafka_retention_days` are omitted entirely when those services are not present in the inventory.
8. `design_constraints.compute_target` uses the structured Q12c shape (`default`, `overrides`, `chosen_by`, `recommendation`). Existing reused preferences with legacy `compute_target.value` may be read by Design for backward compatibility, but newly assembled preferences MUST write the structured shape.
9. `design_constraints.eb_deploy_method` is required when the resolved compute plan includes at least one Elastic Beanstalk formation; omit it for all-Fargate or all-EKS targets.
10. Omit `workshop` on Clarify assemble — workshop mode owns that object.

---

## Validation Checklist

Before handing off to Design:

- [ ] `preferences.json` written to `$MIGRATION_DIR/`
- [ ] `global.target_region` is populated with a valid AWS region code
- [ ] `global.availability` is populated
- [ ] If Postgres in inventory → `data.database_ha` is populated
- [ ] If Postgres in inventory → `global.migration_approach` is populated
- [ ] If Postgres in inventory → `data.migration_method` is populated
- [ ] If `migration_approach` is `interim_cutover_data_first` → `global.target_exit_date` is a valid future ISO date
- [ ] If `migration_approach` is `interim_cutover_data_first` → `global.interim_cutover` is `true`
- [ ] If Private Space peering detected → `network.subnet_ids` contains 1–6 valid IDs
- [ ] If peering detected and VPC ID needed → `network.existing_vpc_id` is populated
- [ ] If Fir apps detected → `global.fir_intent` is populated (not null)
- [ ] `operational.containerization_status` is populated
- [ ] `design_constraints.compute_target.default` is one of: `"elastic_beanstalk"`, `"ecs-fargate"`, `"eks-managed"`, `"eks-or-ecs"`
- [ ] `design_constraints.compute_target.chosen_by` is one of: `"user"`, `"system_recommended"`, `"default"`
- [ ] `design_constraints.compute_target.overrides[]` entries, when present, have `formation`, `value`, `reason`, and `chosen_by`
- [ ] `design_constraints.compute_target.overrides[].value` is one of: `"elastic_beanstalk"`, `"ecs-fargate"`
- [ ] `design_constraints.compute_target.overrides[].chosen_by` is one of: `"user"`, `"system_forced"`
- [ ] `design_constraints.compute_target.recommendation.value` is one of: `"elastic_beanstalk"`, `"ecs-fargate"`, `"eks-managed"`, `"eks-or-ecs"`, `"mixed"`
- [ ] `design_constraints.compute_target.recommendation.confidence` is one of: `"high"`, `"medium"`, `"low"`
- [ ] `design_constraints.compute_target.recommendation.reasons` is a non-empty array
- [ ] If the resolved compute plan includes Elastic Beanstalk → `design_constraints.eb_deploy_method.value` is one of: `"github_actions"`, `"codepipeline"`, `"manual"`
- [ ] If `design_constraints.eb_deploy_method` is present → `design_constraints.eb_deploy_method.chosen_by` is `"user"` or `"default"`
- [ ] All entries in `sources` have a value of `"user"`, `"extracted"`, or `"default"`
- [ ] Every ID in `metadata.questions_skipped_extracted` has `sources.<QID>` = `"extracted"`, and its field holds a catalog enum value (`data.database_ha` ∈ `"single-az"` / `"multi-az"` / `"multi-az-ha"`; `operational.containerization_status` ∈ `"containerized"` / `"buildpack_only"` / `"partial"`; `data.redis_ha` Boolean) — never a raw inventory signal such as a Boolean `database_ha`
- [ ] `metadata.clarify_mode` is set to `"fast_path"` or `"full"`
- [ ] `metadata.questions_deferred_to_generate` is present and lists exactly the Generate-time questions that fire on this inventory (Q4; Q6c if Postgres present; Q12d if the resolved compute plan includes EB) **and are still unanswered** — validate the post-answer state, not the fresh-assembly list. An empty array is valid (the Decision gate's "Confirm execution choices" already ran), and so is a shorter list (an ID answered early from the gate's "Assumptions behind this number" block has moved to `metadata.questions_asked` with `sources.<QID>` = `"user"`, per `estimate-assemble.md` § Handling a correction, step 2). On a **fresh assembly** (interview Steps 1–3 ran this session) that is the full list. On **preference reuse** (interview Step 0 case 1) it is whatever Step 0 normalized — a legacy file gets the array rebuilt from its `sources` entries; an emptied or shortened array stays as it is
- [ ] Every ID listed in `metadata.questions_deferred_to_generate` has its field set to the documented default and `sources.<QID>` = `"default"`; no ID with `sources.<QID>` = `"user"` is listed (an already-answered execution choice is never re-asked)
- [ ] Only keys with non-null values are present
- [ ] Output is valid JSON

---

## Completion Handoff Gate (Fail Closed)

The completion checks are declared in this phase's `_postconditions` frontmatter and
enforced per `INTERPRETER.md` § Gate protocol: re-read `preferences.json` from disk, run
the mechanical checks (`_check_file_exists` / `_validate_json`) and the `_assert`
judgment checks (all Validation Checklist items; the Postgres/interim-cutover/Fir/
private-space conditionals), then emit `GATE_FAIL` (STOP; do not patch artifacts) or
`HANDOFF_OK | phase=clarify | artifacts=preferences.json` and advance.

---

## Step 5: Update Phase Status and Hand Off

Only after `HANDOFF_OK`, apply the phase-status update protocol (`INTERPRETER.md` § The interpreter loop) — mark `phases.clarify` completed and advance per `_advances_to` — in the **same turn** as the output message below.

Output to user: "Phase 2 of 6 complete (Clarify). Remaining: Design → Estimate → Generate (+ optional Feedback). Next artifact: aws-design.json. Proceeding to Phase 3: Design AWS Architecture."

_Emit this breadcrumb only after `HANDOFF_OK` — never on a failed gate._
