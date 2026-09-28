---
_phase: clarify
_title: "Clarify Migration Requirements"
_requires_phase: discover
_input:
  - azure-resource-inventory.json
  - azure-resource-clusters.json
  - ai-workload-profile.json
_fragments:
  - _id: global
    _trigger: { _always: true }
    _file: phases/clarify/clarify-global.md
  - _id: compute
    _trigger: { _when: "the inventory contains a compute resource — Microsoft.Web/serverfarms, Microsoft.Compute/virtualMachines, Microsoft.Compute/virtualMachineScaleSets, Microsoft.ContainerService/managedClusters, Microsoft.App/containerApps, or Microsoft.ContainerInstance/containerGroups" }
    _file: phases/clarify/clarify-compute.md
  - _id: database
    _trigger: { _when: "the inventory contains a relational database, cache, or Cosmos account — any Microsoft.DBforPostgreSQL/*, Microsoft.DBforMySQL/*, Microsoft.Sql/*, Microsoft.DocumentDB/databaseAccounts, or Microsoft.Cache/* resource" }
    _file: phases/clarify/clarify-database.md
  - _id: licensing
    _trigger: { _when: "the inventory contains a Windows VM image, any Microsoft.Sql/* resource, or a SQL-Server-on-VM image signature — otherwise licensing is N/A and this fragment does not load" }
    _file: phases/clarify/clarify-licensing.md
  - _id: identity
    _trigger: { _always: true }
    _file: phases/clarify/clarify-identity.md
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
  - _assert: "at least one discovery artifact exists: azure-resource-inventory.json (a full or mixed migration) OR ai-workload-profile.json (an app-code-only / AI-only migration). A run with NEITHER is unrecoverable — discover did not produce a migratable artifact"
    _on_failure: _unrecoverable
  - _assert: "WHEN azure-resource-inventory.json exists it validates as JSON alongside azure-resource-clusters.json; WHEN the run is AI-only (inventory absent, ai-workload-profile.json present) that profile validates against schema-discover-ai.md instead"
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
  - _assert: "global.target_region is set, and design_constraints.cpu_architecture is set with x86_64 as the recorded default unless the user chose otherwise"
    _on_failure: _halt_and_inform
  - _assert: "identity is set (Category J always fires); its value is the fresh IAM Identity Center re-invite path unless the user chose full Entra ID federation"
    _on_failure: _halt_and_inform
  - _assert: "if the inventory contains Windows VM images, any Microsoft.Sql/* resource, or a SQL-on-VM signature, then licensing is set (License Included vs BYOL via Dedicated Hosts); otherwise licensing is N/A and no licensing question was asked"
    _on_failure: _halt_and_inform
  - _assert: "if azure-resource-clusters.json assigns any cluster a pattern_id, the user confirmed or corrected that pattern on the assumption sheet and the confirmed value is recorded in preferences.json"
    _on_failure: _halt_and_inform
  - _assert: "if any Microsoft.Web/serverfarms plan hosts more than one Microsoft.Web/sites app, the isolation question was asked and its answer recorded; an absent answer means no split"
    _on_failure: _halt_and_inform
  - _assert: "if ai-workload-profile.json exists, preferences.json carries workloads[] and (when agentic_profile.is_agentic) ai_constraints.agentic; every persisted workload row carries workload_id, capability, and target_bedrock_model; and startup_program_status is present (ESSENTIAL, value null until answered) — the workloads[] in preferences.json, not ai-workload-profile.json, is the downstream source of truth"
    _on_failure: _halt_and_inform
_forbids_files:
  - README.md
  - "*.txt"
  - aws-design.json
  - "terraform/**"
---

# Phase 2: Clarify Migration Requirements

## Orientation

Turn the inventory into an explicit, user-confirmed set of migration preferences via
an **assumption sheet**: every row states what was detected or proposed and its
default, and the user corrects only what is wrong. This is a wizard, not an
interrogation — the aim is the fewest questions that still make the design
defensible.

Four dispositions per row: **DETECTED** (read from the estate), **PROPOSED** (the
skill's recommendation, changeable), **ESSENTIAL** (cannot be defaulted; must be
answered), **N/A** (does not apply to this estate — shown so the user can see it was
considered).

Two Azure-specific categories that no sibling skill has:

- **Licensing (conditional).** N/A, and its rubric never loads, when there are no
  Windows VM images, no `Microsoft.Sql/*`, and no SQL-on-VM signature. When it
  fires: one ESSENTIAL question, License Included vs BYOL via Dedicated Hosts.
  Azure Edition Windows Server is a special case — no question, a hard blocker
  warning, because AWS Application Migration Service refuses the image until it is
  re-imaged.
- **Identity (always fires).** One shallow question, defaulting to `[A]`: a fresh
  IAM Identity Center re-invite. Full Entra ID federation exists as option `[B]` but
  is not the assumed path.

Two more things the sheet must carry, because they are not inferable and both move
the estimate by multiples:

- **App Service Plan isolation.** A plan is the compute unit; its apps are
  deployments onto it and share its capacity. The default is no split. A split is
  only ever a stated isolation requirement, and when the user asks for one the
  rationale must say plainly that compute cost rises.
- **Cluster pattern confirmation.** Pattern recognition is judgment and will
  sometimes be wrong. Routing it through this sheet makes the holistic call
  user-validated before Design commits, at the cost of one sheet section and no new
  interaction model.

## Status — build step 5 (infra categories)

Five fragments: global, compute, database, licensing (conditional), identity. The AI
category `clarify-ai.md` is wired (it fires when `ai-workload-profile.json` exists alongside infra), and the standalone `clarify-ai-only.md` route is wired via Step 0's Migration Type Detection (an app-code-only / AI-only run, plan §19.12). The pattern-confirmation section fills in when `patterns.md` lands, and
the pattern-confirmation section fills in when `patterns.md` lands — until then every
cluster's `pattern_id` is `unclassified` and its row is DETECTED with nothing to correct.

## Step 0: Migration Type Detection (route AI-only runs first)

Before running any fragment, detect the migration type from which discovery artifacts exist
(matching gcp's clarify Step 1):

- **Full or mixed migration** — `azure-resource-inventory.json` exists (it may also have
  `ai-workload-profile.json`). Run the normal flow below: the infra fragments fire on inventory
  content, and the `ai` fragment adds the AI categories.
- **AI-only migration** — ONLY `ai-workload-profile.json` exists (no `azure-resource-inventory.json`,
  because the run was app-code-only and discover-assemble left the inventory absent). Infrastructure
  stays on Azure; only AI/LLM calls move to Bedrock.

> **HARD GATE — AI-only path.** If the run is AI-only, read `clarify-ai-only.md` NOW and follow
> that flow to completion. **Skip the normal flow below entirely** — its question text, batching,
> and interpretation rules live only in `clarify-ai-only.md`, which writes `preferences.json` with
> `metadata.migration_type: "ai-only"`. Do not run the infra fragments (there is no inventory for
> their triggers to read) and do not fabricate an assumption sheet from the summaries here.

## Step: Run the phase

**Fragments do not talk to the user. The assembler does.** This is the one phase where
that split matters, so it is stated here rather than left to each unit:

1. Run each fragment whose `_trigger` holds. A fragment **reads the inventory, resolves
   what it can, assigns a disposition per row, and returns rows** — it asks nothing.
2. Run `clarify-assemble.md`, which owns the whole conversation: **one** consolidated
   assumption sheet (DETECTED and PROPOSED rows, batched at five at a time), then the
   ESSENTIAL questions, then the answer recap, then it writes `preferences.json`.
3. Evaluate `_postconditions`. On all-pass emit `HANDOFF_OK`; on any failure emit
   `GATE_FAIL` and stop.

Why presentation sits in the assembler: with five fragments each presenting its own
section the user would face five sheets and five rounds of essentials, interleaved. gcp
runs **one** sheet as a single mandatory gate and then batches the essentials, and this
phase's own postcondition says _"every assumption-sheet row the user was shown"_ —
singular. One gate, one recap, one place that knows the full row set.
