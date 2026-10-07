---
_phase: discover
_title: "Discover Azure Resources"
_init: true
_input: workspace
_fragments:
  - _id: iac
    _trigger: { _always: true }
    _file: phases/discover/discover-iac.md
  - _id: app-code
    _trigger: { _when: "source code or a dependency manifest is present in the workspace (.py/.js/.ts/.go/.java/.cs, requirements.txt, package.json, go.mod, pom.xml, *.csproj)" }
    _file: phases/discover/discover-app-code.md
  - _id: live
    _trigger: { _when: "$MIGRATION_DIR/live-capture/manifest.json exists AND is fresh for THIS attempt — i.e. the 'Pre-dispatch main-window action' below ran, the user consented, and (on a re-entry) any manifest from a prior attempt was invalidated per that section's decline rule. This dispatched fragment ONLY parses that directory; it never runs az or prompts. Absent (or invalidated) manifest ⇒ the trigger is false and the fragment does not run." }
    _file: phases/discover/discover-live.md
_assemble:
  _file: phases/discover/discover-assemble.md
_produces:
  - azure-resource-inventory.json
  - azure-resource-clusters.json
  - ai-workload-profile.json
_advances_to: clarify
_interactive: false
_exec:
  _agent: rw
_re_entry_guard:
  _stale_if_completed: clarify
  _stale_artifact: preferences.json
  _on_reentry: stop_unless_confirmed
  _on_confirm: reset_downstream_to_pending
_preconditions:
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _assert: "a live-`az` disposition was recorded for THIS attempt before the entry gate below is evaluated (see 'Pre-dispatch main-window action' immediately below `_preconditions` in the body) — either $MIGRATION_DIR/live-capture/manifest.json exists (consent given, capture attempted), or the live-capture step was skipped/declined/unavailable and no STALE manifest from a prior attempt is left on disk (see the re-entry rule in that same section). This does not require az to be installed or the capture to succeed — only that the attempt-or-skip decision for this run was actually made and, on decline, any earlier manifest was invalidated."
    _on_failure: _halt_and_inform
  - _assert: "at least one migratable source is available: an IaC source (a .tf file containing an azurerm_* resource, a .bicep file, or an ARM template whose $schema contains 'deploymentTemplate'), OR application source code / a dependency manifest that the app-code fragment can scan for an AI signal, OR a live-capture manifest ($MIGRATION_DIR/live-capture/manifest.json written by the live-az pre-work above). A workspace with NONE of these — no IaC, no source code, and no successful live capture — is the only unrecoverable case, matching gcp's 'stop only when nothing will produce any artifact'"
    _on_failure: _unrecoverable
_postconditions:
  - _assert: "at least one discovery artifact was produced: azure-resource-inventory.json (when an IaC source was found OR live `az` capture produced resources) OR ai-workload-profile.json (when application code had an AI signal, or a live Cognitive Services / ML signal was captured). This is the completion anchor — an app-code-only run that produced only the AI profile satisfies discover, matching gcp's 'stop only when nothing will produce any artifact'"
    _on_failure: _halt_and_inform
  - _assert: "WHEN an IaC source (.tf/.bicep/ARM) was found OR live `az` capture produced at least one resource: azure-resource-inventory.json and azure-resource-clusters.json exist, validate as JSON, and the inventory has at least one resources[] entry with metadata carrying discovery_timestamp, discovery_sources, and subscriptions_discovered. WHEN the run is app-code-only (no IaC source found and no live capture): the inventory and clusters artifacts are ABSENT (not written empty — see discover-assemble.md) and this is vacuously satisfied"
    _on_failure: _halt_and_inform
  - _assert: "WHEN azure-resource-inventory.json exists, every resources[] entry has azure_id (a full ARM resource ID), azure_type (a canonical Microsoft.* type string), azure_type_provenance from {table, derived, derived_uncorroborated, user_confirmed}, resource_group, subscription_id, and config — no entry carries a raw azurerm_* type in azure_type"
  - _assert: "WHEN an IaC dialect (terraform/bicep/arm) contributed to azure-resource-inventory.json, iac_metadata carries derived_types and untranslated_types as separate collections: derived_types lists Terraform types resolved by derivation with a namespace that namespace_routing recognises, and untranslated_types lists ONLY those whose derived namespace was NOT recognised. A type absent from the canonicalization table is DERIVED and retained, never silently dropped — see arm-type-canonicalization.md § Deriving a type that is not listed. WHEN the run is live-only (no IaC dialect contributed), iac_metadata is ABSENT (per schema-discover-azure.md 'present only when a dialect actually contributed') and the live fragment records its own derived types in live_metadata.derived_types instead — this is vacuously satisfied"
    _on_failure: _halt_and_inform
  - _assert: "WHEN azure-resource-inventory.json exists, metadata.discovery_sources reflects which sources actually produced data; the iac fragment always runs and may exit empty, so a source appears only when it contributed at least one resource"
    _on_failure: _halt_and_inform
  - _assert: "if .tf files containing azurerm_* resources were FOUND in the workspace, resources[] contains at least one entry with source 'terraform'; the same holds independently for 'bicep' and 'arm'"
    _on_failure: _halt_and_inform
  - _assert: "no secret VALUES appear anywhere in any produced artifact (inventory OR ai-workload-profile.json) — app settings, connection strings, Key Vault entries, and AI endpoint keys carry NAMES only"
    _on_failure: _halt_and_inform
  - _assert: "WHEN azure-resource-inventory.json exists, warnings[] is present on the inventory (empty is fine), and every entry carries a code from the closed vocabulary in schema-discover-azure.md § Warnings, a detail, and an azure_id or identifier"
  - _assert: "WHEN application code with an AI signal at >= 70% confidence was found: ai-workload-profile.json exists, validates against schema-discover-ai.md, and carries summary.ai_source from {azure_openai, openai, anthropic, both, other} (never gemini), a workloads[] array, and — only when an agentic framework was detected — an agentic_profile. WHEN no AI signal reached 70% (or no source code was found), ai-workload-profile.json is absent and this is vacuously satisfied — its absence is not a failure"
    _on_failure: _halt_and_inform
  - _assert: "PRODUCER AGREEMENT: WHEN azure-resource-inventory.json contains a case-insensitive azure_type in {Microsoft.CognitiveServices/accounts, Microsoft.CognitiveServices/accounts/deployments, Microsoft.MachineLearningServices/workspaces}, ai-workload-profile.json MUST exist and validate against schema-discover-ai.md, and infrastructure[] contains every qualifying resource — one entry per resource, in the shape schema-discover-ai.md § infrastructure[] defines for that resource's own source (an IaC-sourced entry keyed by config.tf_address; a live-sourced entry keyed by azure_id, with no address/file). The profile-level fields are computed by OR-ing across ALL qualifying resources in the profile, per schema-discover-ai.md § profile_source and sources_analyzed — NOT assigned exclusively per producer: metadata.sources_analyzed.terraform is true iff AT LEAST ONE qualifying resource is IaC-sourced; metadata.sources_analyzed.live is true iff AT LEAST ONE qualifying resource is live-sourced; summary.inferred_from_iac is true iff AT LEAST ONE qualifying resource is IaC-sourced (both flags may be true simultaneously in a mixed run — this is not a contradiction, it is two true statements about the same profile). metadata.profile_source is iac_cognitive when infrastructure-only (IaC and/or live, no app-code contribution) or merged when app-code also qualified. A Cognitive Services deployment with a literal config.model.name (IaC-sourced) carries that model in models[] with detected_via including terraform; a captured deployment's model field (live-sourced) carries that model in models[] with the live signal recorded via a detection_signals[].method of live_az on that resource's entry (models[].detected_via has no live value per schema-discover-ai.md, so live provenance never goes there). Do NOT require tf_address on a live-sourced infrastructure[] entry, and do NOT force sources_analyzed.terraform or inferred_from_iac to false merely because a DIFFERENT qualifying resource in the same profile was live-sourced — check each flag against the full resource set, not against one resource in isolation. This check is not vacuously satisfied merely because app-code found no AI signal"
    _on_failure: _halt_and_inform
  - _assert: "WHEN azure-resource-inventory.json exists, every edges[] entry's type appears in schema-discover-azure.md § Typed edges — a per-dialect ref may map new syntax onto an existing type but may not invent one"
    _on_failure: _halt_and_inform
  - _assert: "WHEN azure-resource-clusters.json exists, it has one entry per cluster, each with cluster_id, tier, member azure_ids, and a justification; any cluster justified by edges or by a merge has a non-empty edges[] carrying them, while a cluster justified by the resource-group seed or by a SPLIT legitimately has an empty edges[] — a split is justified by the ABSENCE of a relationship, so there is nothing to show; every inventory resource is either a cluster member or listed in unclustered[]"
    _on_failure: _halt_and_inform
_forbids_files:
  - README.md
  - discovery-summary.md
  - "*.txt"
  - "terraform/**"
  - preferences.json
---

# Phase 1: Discover Azure Resources

## Pre-dispatch main-window action (live `az` consent + capture)

Run this BEFORE the `_preconditions` gate above is evaluated. `_exec`'s own contract
already runs `_preconditions` in the main window before dispatch; this is the action
that produces the state the first `_assert` there checks — it is prose, not a
`_preconditions` check kind, because the DSL's closed check vocabulary
(`_check_phase_completed`, `_check_single_active_phase`, `_check_file_exists`,
`_validate_json`, `_assert`) has no kind for "perform an interactive action," only
for verifying a predicate. This phase is `_interactive: false` / `_exec: {_agent:
rw}`, so the dispatched worker cannot prompt for consent or run interactive `az` —
the consent gate and the actual capture commands MUST run here instead.

**Step 0 — ensure `$MIGRATION_DIR` exists before capturing into it (do this
FIRST, before the re-entry check below).** This phase carries `_init: true`, and
`INTERPRETER.md`'s generic `_exec` contract runs `_init` state setup AFTER
`_preconditions` (§ `_exec`, step 2) — but this action runs BEFORE
`_preconditions` (see above), and it writes to `$MIGRATION_DIR/live-capture/`,
which does not exist until `_init` has run. **For this phase specifically,
reverse that ordering: perform `_init` state setup per `INTERPRETER.md` §
`_init: true` NOW**, before step 1 below — resolve resume-vs-fresh, set
`$MIGRATION_DIR`, and (on a fresh run) create the directory, `.gitignore`, and
`.phase-status.json` exactly as that section specifies. This makes "Step: Run
the phase" step 1's `_init` call (below) a no-op confirmation for this phase —
`_init` is idempotent by construction (a resumed run's `_init` setup only reads
the existing `.phase-status.json` and reuses `$MIGRATION_DIR`; nothing is
re-created), so running it here and having it "run again" later does not
double-initialize state or re-prompt resume-vs-fresh. Every other check this
phase's `_preconditions`/`_postconditions` perform, and the state transition
itself, still run at their normal point in the MAIN window — only the state
CREATION step moves earlier, for this phase alone, to break the cycle.

1. **Re-entry check (do this FIRST, before offering consent).** If
   `$MIGRATION_DIR/live-capture/manifest.json` already exists (this run directory
   is being reused — a resumed run, or a confirmed re-entry per this phase's
   `_re_entry_guard`), do NOT silently trust it as this attempt's answer. Re-offer
   the Step 1 consent gate in `discover-live.md` for THIS attempt. If the user
   chooses **[A]** (proceed), overwrite the manifest via Part A Steps 0-2 as
   normal. If the user chooses **[B]** (skip), **delete or rename
   `live-capture/manifest.json`** (e.g. to `manifest.json.declined`) before
   continuing — a manifest from an earlier attempt must never survive a fresh
   decline, since the `live` fragment's `_trigger` is existence-based and would
   otherwise fire on stale data the user just said not to use.
2. **No existing manifest.** Run `discover-live.md` Part A (Steps 0-2): preflight
   `az`, gate consent, and on consent capture the read-only inventory into
   `$MIGRATION_DIR/live-capture/` + `manifest.json`. OFFER it when there is no
   `azurerm_*`/Bicep/ARM IaC in the workspace (the common startup case, where live
   `az` is the primary source), or as an accuracy upgrade alongside IaC.
3. If `az` is missing, the user declines, or no subscription is reachable, ensure
   no manifest is present (write nothing on a fresh run; delete per step 1 on a
   re-entry decline) and continue — the live fragment then no-ops on the absent
   manifest. This action never fails the phase; it only determines whether
   `live-capture/manifest.json` is present and current for THIS attempt.

## Orientation

Inventory what exists on Azure into `azure-resource-inventory.json` in
`$MIGRATION_DIR/`, and derive `azure-resource-clusters.json` from it. This phase is
composed of FRAGMENTS (independent discoverers) plus one ASSEMBLER, declared in the
frontmatter `_fragments`/`_assemble` — the interpreter runs each fragment whose
`_trigger` is true (loading its `_file` only then), then the assembler. Read each
unit file for its own contract; this phase owns only lifecycle and the cross-cutting
`_postconditions`.

Two facts the frontmatter cannot express:

1. **Fragments are additive, not redundant, and they may disagree.** IaC carries
   _declared intent_ (module structure, naming, what is parameterized, and resources
   declared but never deployed). Live `az` and RDfA carry _actual state_. When two
   sources disagree about the same `azure_id`, the assembler records BOTH values and
   which one won as a drift entry. A disagreement is never silently reconciled — the
   drift is itself customer-visible value.

2. **The canonical type vocabulary is ARM, not Terraform.** Four of the five
   discovery sources speak `Microsoft.*` natively; only Terraform needs translating.
   That translation happens inside `discover-iac.md`, so every downstream table
   keys off one vocabulary. `azure_id` is the full ARM resource ID, which embeds
   subscription and resource group — one field supplies the cluster seed key, the
   environment scope, and uniqueness with no derivation.

## Status — Terraform, live `az`, and app code

Terraform discovery is real, live `az` discovery is real, and clustering is real:
`discover-iac.md` (Terraform), `discover-live.md` (live `az` capture + parse), and
`discover-app-code.md` (AI signal), plus an assembler that writes both artifacts.

The **live `az` path is implemented** (`discover-live.md` — the security contract,
main-window capture pre-work, and the parsing fragment, in that order). Terraform IaC
and the live tenant are both real discovery producers; the app-code fragment adds the
AI signal.

| Lands in | What                                                                                                                                                                                                                   |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| step 2   | Bicep + ARM inside `discover-iac.md`; the `billing` fragment                                                                                                                                                           |
| step 2   | The `rdfa` fragment (RDfA archive parse). Live `az` has landed (`discover-live.md`)                                                                                                                                    |
| step 4   | `patterns.md` — pattern RECOGNITION only. Seed / split / merge / tier / primary / roles are implemented in `references/clustering/`; every cluster carries `pattern_status: "catalog_absent"` until the catalog exists |

The live `az` path is NOT a plain fragment. This phase runs under
`_exec: { _agent: rw }` with `_interactive: false`, and a dispatched worker is
file-only — it cannot prompt for consent. Live capture is therefore **main-window
pre-work run BEFORE `_preconditions` is evaluated** (see the "Pre-dispatch
main-window action" section above the Orientation heading — `_preconditions` itself
only asserts that this pre-work already happened; it does not perform it, since the
DSL's closed check-kind vocabulary has no kind for "run an interactive action"),
writing to `$MIGRATION_DIR/live-capture/`, with the dispatched `live` fragment merely
parsing that directory (its `_trigger` fires only when a fresh
`live-capture/manifest.json` exists for this attempt). RDfA needs no such split:
reading an archive the customer already handed over is not interactive.

## Step: Run the phase

1. Perform `_init` state setup per `INTERPRETER.md` § `_init: true` — **already
   done** by "Pre-dispatch main-window action" Step 0 above, which runs this
   same setup earlier (before `_preconditions`) so `$MIGRATION_DIR` exists for
   live capture. This step is the normal backbone position for `_init` and is
   listed here for parity with every other phase's "Step: Run the phase" — it is
   a no-op re-confirmation for THIS phase specifically (idempotent: `$MIGRATION_DIR`
   is already set, `.phase-status.json` already written), not a second
   initialization.
2. Run each fragment whose `_trigger` holds.
3. Run `discover-assemble.md`.
4. Evaluate `_postconditions`. On all-pass emit `HANDOFF_OK`; on any failure emit
   `GATE_FAIL` and stop. Do not patch an artifact to force a gate to pass.
