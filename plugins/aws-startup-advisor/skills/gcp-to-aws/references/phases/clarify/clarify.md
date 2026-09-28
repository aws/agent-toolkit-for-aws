---
_phase: clarify
_title: "Clarify Requirements"
_requires_phase: discover
_input:
  - gcp-resource-inventory.json
  - gcp-resource-clusters.json
  - billing-profile.json
  - ai-workload-profile.json
_fragments:
  - _id: global
    _trigger: { _always: true }
    _file: phases/clarify/clarify-global.md
  - _id: compute
    _trigger: { _when: "(billing-profile.json exists AND gcp-resource-inventory.json does NOT exist) OR any compute resource is present — Cloud Run, Cloud Functions, GKE, GCE, App Engine" }
    _file: phases/clarify/clarify-compute.md
  - _id: database
    _trigger: { _when: "database resources present in the inventory — Cloud SQL, Spanner, Memorystore" }
    _file: phases/clarify/clarify-database.md
  - _id: ai
    _trigger: { _when: "ai-workload-profile.json exists in $MIGRATION_DIR" }
    _file: phases/clarify/clarify-ai.md
_assemble:
  _file: phases/clarify/clarify-assemble.md
_produces:
  - preferences.json
_advances_to: design
_interactive: true
_re_entry_guard:
  _stale_if_completed: design
  _stale_artifact: aws-design.json
  _on_reentry: stop_unless_confirmed
  _on_confirm: reset_downstream_to_pending
_preconditions:
  - _check_phase_completed: discover
    _on_failure: _halt_and_inform
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _assert: "at least one discovery artifact exists: gcp-resource-inventory.json, billing-profile.json (a full, mixed, or billing-only migration) OR ai-workload-profile.json (an app-code-only / AI-only migration). A run with NEITHER is unrecoverable — discover did not produce a migratable artifact"
    _on_failure: _unrecoverable
  - _assert: "WHEN gcp-resource-inventory.json exists it validates as JSON alongside gcp-resource-clusters.json; WHEN the run is AI-only (inventory absent, ai-workload-profile.json present) that profile validates against schema-discover-ai.md instead"
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: preferences.json
    _on_failure: _halt_and_inform
  - _validate_json: preferences.json
    _on_failure: _halt_and_inform
  - _assert: "all Validation Checklist items in clarify-assemble.md pass"
    _on_failure: _halt_and_inform
  - _assert: "every assumption-sheet row the user was shown appears in preferences.json with a disposition of DETECTED, PROPOSED, ESSENTIAL, or N/A, and a value that is either the user's answer or the documented default"
    _on_failure: _halt_and_inform
  - _assert: "design_constraints.target_region is set, and design_constraints.compliance is set (never silently 'none' — the compliance question is always ESSENTIAL for a full-infrastructure run)"
    _on_failure: _halt_and_inform
  - _assert: "if ai-workload-profile.json exists, preferences.json carries workloads[] and (when agentic_profile.is_agentic) ai_constraints.agentic; every persisted workload row carries workload_id, capability, and target_bedrock_model; and startup_program_status is present (ESSENTIAL, value null until answered) — the workloads[] in preferences.json, not ai-workload-profile.json, is the downstream source of truth"
    _on_failure: _halt_and_inform
_forbids_files:
  - README.md
  - "*.txt"
  - aws-design.json
  - "terraform/**"
---

# Phase 2: Clarify Requirements

## Orientation

Turn discovery into an explicit, user-confirmed set of migration preferences via an
**assumption sheet**: every row states what was detected or proposed and its default, and
the user corrects only what is wrong. This is a wizard, not an interrogation — the aim is the
fewest questions that still make the design defensible.

Four dispositions per row: **DETECTED** (read from discovery), **PROPOSED** (the skill's
recommendation, changeable), **ESSENTIAL** (cannot be defaulted; must be answered), **N/A**
(does not apply to this estate — shown so the user can see it was considered).

**Five of Category A's questions are canonical, shared with `azure-to-aws`** —
`references/vendored/clarify/`. See `clarify-global.md` for which ones and why. Categories B
(config gaps), C (compute), D (database), F (AI), G (agentic), and H (startup programs) are
GCP-specific: no shared file exists for them, either because there is no Azure equivalent
(Category B/D's GCP-only signals, Q3/Q3.5) or because the decision shape genuinely diverges
enough that unifying would blur real differences (Q7's single unified cutover question vs
Azure's split VM/DB cutover; Category F/G/H's GCP-sourced AI signals vs Azure's own AI
category).

Two GCP-specific mechanisms that no sibling skill has:

- **Fast paths (Step 1.5).** A straightforward stack (no DB, no AI) or a lightweight-AI stack
  can skip most of the wizard for a 3- or 6-question short form. `azure-to-aws` has no
  equivalent — every Azure run goes through the full sheet.
- **Full Flow opt-out ("ask me everything").** The user can decline the wizard entirely and
  answer all questions directly in three progressive batches, no sheet, no dispositions. Also
  GCP-specific.

## Category Reference Files

| File                  | Category                                  | Questions                  | Loaded When                                     |
| --------------------- | ----------------------------------------- | -------------------------- | ----------------------------------------------- |
| `clarify-global.md`   | A — Global/Strategic                      | Q1–Q7                      | Always                                          |
| `clarify-compute.md`  | B — Config Gaps, C — Compute              | Q7b–Q11b                   | Compute or billing-source resources present     |
| `clarify-database.md` | D — Database                              | Q12–Q13b                   | Database resources present                      |
| `clarify-ai.md`       | F — AI/Bedrock, G — Agentic, H — Programs | Q14–Q27                    | `ai-workload-profile.json` exists               |
| `clarify-ai-only.md`  | _(standalone)_                            | Q1–Q11 (+ Q1.5 compliance) | AI-only migration (no infrastructure artifacts) |

## Status — build step 5 (restructure)

Implemented. This file is now a thin orchestrator manifest — the fragment-returns-rows /
assembler-owns-conversation pattern shared with `azure-to-aws` — rather than the prior
monolith that asked questions directly. `clarify-global.md`, `clarify-compute.md`,
`clarify-database.md`, and `clarify-ai.md` are fragments; `clarify-assemble.md` is the sole
unit that talks to the user, runs the sheet/essentials/recap/full-flow logic, and writes
`preferences.json`. `clarify-ai-only.md` is unchanged — it remains a standalone flow read
directly by Step 0 below, exactly as before.

**What did NOT change in this restructure:** every firing rule, auto-extraction signal,
default value, and interpretation rule from the prior monolith is preserved verbatim, moved
into its fragment (for computation) or `clarify-assemble.md` (for presentation/sequencing).
GCP's fast-path / simple-hybrid short paths and the Full Flow variant are GCP-specific
mechanisms `azure-to-aws` does not have, and this restructure does not remove them — see
`clarify-assemble.md`.

## Step 0: Prior Run Check

Check `$MIGRATION_DIR/` for existing state:

**Case 1 — Completed preferences exist** (`preferences.json` present):

**Compatibility check (run BEFORE offering reuse):** The existing file may predate the
current flow, and the Completion Handoff Gate forbids patching artifacts to pass — so an
incompatible file offered for reuse dead-ends at `GATE_FAIL`. Check:

1. **Schema currency** — `metadata.clarify_mode` is present; every constraint has `value`,
   `chosen_by`, `prompt`, and `design_consequence`; every constraint with `chosen_by:
   "extracted"` or `"default"` has a `source` field; `design_constraints.cpu_architecture` is
   present when compute resources exist in the current inventory.
2. **Discovery match** — the file's `metadata.discovery_artifacts` is consistent with what
   exists in `$MIGRATION_DIR` now: if `ai-workload-profile.json` exists but the file has no
   `ai_constraints` (or the reverse), or the inventory has database/compute resources whose
   required constraints (`availability`, `db_size`) are absent, the file is stale relative to
   current discovery.

**If both pass**, offer:

> "I found existing migration preferences from a previous run. Would you like to:"
>
> 1. Re-use these preferences and skip questions
> 2. Start fresh and re-answer all questions

- If 1: Run `clarify-assemble.md`'s BigQuery detection (§ Step 2 extraction detail) on
  current discovery artifacts. If `bigquery_present` is **true**, output the mandatory
  BigQuery / deferred analytics advisory block once (even though questions are skipped), then
  skip to `clarify-assemble.md`'s Validation Checklist with the existing `preferences.json`.
- If 2: rename `preferences.json` to `preferences-superseded.json` (do not delete — prior
  answers are unrecoverable otherwise), continue to Step 1.

**If either check fails**, do NOT offer plain reuse — it would fail the gate. Instead:

> "I found preferences from a previous run, but they predate the current flow (missing:
> [list]). Would you like to:"
>
> 1. Keep your previous answers where they're still valid — I'll confirm them on the
>    assumption sheet and only ask what's new or missing
> 2. Start fresh and re-answer all questions

- If 1: rename the old file to `preferences-superseded.json`, seed the wizard from it — carry
  each still-valid constraint value forward with its original `chosen_by` (backfilling
  `prompt`/`design_consequence`/`source` from the current catalog), treat missing constraints
  as unresolved — and continue to Step 1 (the wizard fills the gaps; carried-forward values
  appear on the Assumption Sheet for confirmation).
- If 2: rename to `preferences-superseded.json`, continue to Step 1.

**Case 2 — Draft preferences exist** (`preferences-draft.json` present, no
`preferences.json`):

> "I found a partial set of answers from a previous session. Would you like to:"
>
> 1. Resume from where you left off — I'll pick up the remaining questions
> 2. Start fresh and re-answer all questions

- If 1: load the draft. If `metadata.wizard_stage` is present, resume at that stage
  (`"sheet_pending"` → re-present the Assumption Sheet; `"essentials_pending"` → re-present
  unanswered essential questions). If the draft has the legacy `metadata.batches_completed`
  field instead (pre-wizard flow), tell the user the flow has changed and offer: keep
  answered values and continue with the wizard for the rest, or start fresh.
- If 2: delete `preferences-draft.json`, continue to Step 1.

**Case 3 — No prior state**: Continue to Step 1.

## Step 1: Read Inventory and Determine Migration Type

Read `$MIGRATION_DIR/` and check which discovery outputs exist:

- `gcp-resource-inventory.json` + `gcp-resource-clusters.json` — infrastructure discovered
- `ai-workload-profile.json` — AI workloads detected
- `billing-profile.json` — billing data parsed

At least one discovery artifact must exist to proceed.

### Migration Type Detection

- **Full migration**: `gcp-resource-inventory.json` or `billing-profile.json` exists (may
  also have `ai-workload-profile.json`)
- **AI-only migration**: ONLY `ai-workload-profile.json` exists (no infrastructure or billing
  artifacts)

**If AI-only**: Read `clarify-ai-only.md` NOW and follow that flow. Skip all remaining steps
below, including the fragment/assembler split — `clarify-ai-only.md` is a standalone flow
that talks to the user directly, matching Azure's equivalent standalone route.

> **HARD GATE — AI-Only Path:** You MUST read `clarify-ai-only.md` before presenting any
> questions. The question text, answer options, and interpretation rules are ONLY in that
> file — they are NOT in this file. Do NOT fabricate questions from the summaries above.

### Discovery Summary

Present a discovery summary:

**If `gcp-resource-inventory.json` exists:**

> **Infrastructure discovered:** [total resources] GCP resources across [cluster count]
> clusters
> **Top resource types:** [list top 3–5 types]

**If `ai-workload-profile.json` exists:**

> **AI workloads detected:** [from `models[].model_id`]
> **Capabilities in use:** [from `integration.capabilities_summary` where true]
> **Integration pattern:** [from `integration.pattern`] via [from `integration.primary_sdk`]

**If `billing-profile.json` exists:**

> **Monthly GCP spend:** $[total_monthly_spend]
> **Top services by cost:** [top 3–5 from billing data]

## Step 1.5: Fast-Path Gate (Simple Stacks)

**GCP-specific — `azure-to-aws` has no equivalent fast-path.** After presenting the
Discovery Summary, check `$MIGRATION_DIR/migration-preview.json` for fast-path eligibility:

```
IF migration-preview.json exists
   AND eligible_for_clarify_fast_path == true
THEN offer infra fast-path (3 questions)
ELSE IF eligible_for_clarify_simple_path == true
THEN offer simple hybrid path (~6 questions)
ELSE proceed to Step 2 (Assumption-Sheet Wizard)
```

### Infra fast-path (no AI)

**If `eligible_for_clarify_fast_path`**, present this offer before any questions:

> "Your stack looks straightforward — [primary_resource_count] resource(s), no database, no
> AI detected.
>
> Want to use smart defaults and answer just 3 questions (target region, compliance
> requirements, maintenance window)?
>
> **[Yes — 3 questions]** / **[No — ask me everything]**"

**If user chooses Yes:**

1. Ask only: **Q1** (region), **Q2** (compliance), **Q7** (maintenance window) — from
   `clarify-global.md`.
2. Apply documented defaults for ALL other questions. Record each in
   `metadata.questions_defaulted`.
3. Still run the BigQuery advisory if `bigquery_present` is true.
4. Write `preferences.json` with `metadata.clarify_mode: "fast_path"`. Skip the assembler's
   full sheet/Gate-1/Gate-2 sequence — this path asks its 3 questions directly, the same way
   it always has.

### Simple hybrid path (simple infra + lightweight AI)

**If `eligible_for_clarify_simple_path`**, present:

> "Your stack looks straightforward with lightweight AI ([model IDs from profile]) — no
> agentic framework detected.
>
> Want a short question set (~6 questions) instead of the full flow? I'll use discovery for
> region, database sizing, and model detection.
>
> **[Yes — short path]** / **[No — ask me everything]**"

**If user chooses Yes:**

1. Run each triggered fragment's extraction (mandatory — do not skip).
2. Run `clarify-assemble.md`'s Assumption Sheet (mandatory — wait for user response).
3. Ask only questions **not** resolved by extraction (after any user corrections):
   - **Q2** (compliance) — always ask
   - **Q7** (maintenance window) — always ask
   - **Q16** (AI priority) — from `clarify-ai.md`
   - **Q21** (AI latency) — from `clarify-ai.md`
   - **Q3** (GCP spend) — only if billing did not extract it
   - **Q1** (region) — only if region extraction ambiguous (multiple GCP regions)
4. Apply documented defaults for all other unanswered questions. Record in
   `metadata.questions_defaulted`.
5. Write `preferences.json` with `metadata.clarify_mode: "simple_hybrid"`. Skip straight to
   Category E opt-in (if applicable), then the final write.

**Agentic hard block:** If `agentic_profile.is_agentic == true`, **never offer** infra
fast-path or simple hybrid path. Agentic workloads require Q23–Q26 (asked as essential
questions in the wizard).

**If user chooses No, or neither path is eligible:** Continue to Step 2 (the wizard is the
default full flow).

## Step 2: Run the Fragments, Then the Assembler

**Fragments do not talk to the user. The assembler does.** This is the one phase where that
split matters, so it is stated here rather than left to each unit — matching Azure's
`clarify.md` § Step: Run the phase.

1. Run each fragment whose `_trigger` holds (`clarify-global.md` always;
   `clarify-compute.md`, `clarify-database.md`, `clarify-ai.md` per their triggers above). A
   fragment **reads discovery, resolves what it can, assigns a disposition per row, and
   returns rows** — it asks nothing.
2. Run `clarify-assemble.md`, which owns the whole conversation: the Assumption Sheet
   (Gate 1), the Essential Questions (Gate 2), the Answer Recap (Gate 3), the Category E
   opt-in, and the Full Flow variant — then writes `preferences.json`.
3. Evaluate `_postconditions`. On all-pass emit `HANDOFF_OK`; on any failure emit `GATE_FAIL`
   and stop.

Why presentation sits in the assembler: with four fragments each presenting its own section
the user would face four sheets and four rounds of essentials, interleaved. This phase runs
**one** sheet as a single mandatory gate and then batches the essentials, and the
`_postconditions` above say _"every assumption-sheet row the user was shown"_ — singular. One
gate, one recap, one place that knows the full row set. See `clarify-assemble.md` for the
complete sheet format, essentials batching, recap, Category E opt-in, Full Flow variant,
`preferences.json` write, Defaults Table, Validation Checklist, and Completion Handoff Gate —
all GCP-specific presentation and sequencing detail that lives there rather than here, exactly
as Azure's assembler owns the same responsibilities for its five fragments.
