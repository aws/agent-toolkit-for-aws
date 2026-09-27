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
    _trigger: { _when: "$MIGRATION_DIR/live-capture/manifest.json exists — i.e. the main-window live-capture pre-work (this file's _preconditions live-az step) ran and the user consented. This dispatched fragment ONLY parses that directory; it never runs az or prompts. Absent manifest ⇒ the trigger is false and the fragment does not run." }
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
  - _live_capture_prework: "MAIN-WINDOW pre-work for the live `az` path (this phase is _interactive:false / _exec:{_agent:rw}, so the dispatched worker cannot prompt — the consent + capture MUST run here, in the interactive main window, before dispatch). Run discover-live.md Part A (Steps 0-2): preflight `az`, gate consent, and on consent capture the read-only inventory into $MIGRATION_DIR/live-capture/ + manifest.json. OFFER it when there is no azurerm_*/Bicep/ARM IaC in the workspace (the common startup case, where live `az` is the primary source), or as an accuracy upgrade alongside IaC. If `az` is missing, the user declines, or no subscription is reachable, write nothing and continue — the live fragment then no-ops on the absent manifest. This step never fails the phase."
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
  - _assert: "PRODUCER AGREEMENT: WHEN azure-resource-inventory.json contains a case-insensitive azure_type in {Microsoft.CognitiveServices/accounts, Microsoft.CognitiveServices/accounts/deployments, Microsoft.MachineLearningServices/workspaces}, ai-workload-profile.json MUST exist and validate against schema-discover-ai.md, and infrastructure[] contains every qualifying resource. The producer-specific fields follow the source that supplied the resource: (a) WHEN the qualifying resource was IaC-sourced, metadata.sources_analyzed.terraform is true, summary.inferred_from_iac is true, metadata.profile_source is iac_cognitive (or merged when app-code also qualified), infrastructure[] keys it by config.tf_address, and a Cognitive Services deployment with a literal config.model.name carries that model in models[] with detected_via including terraform; (b) WHEN the qualifying resource was LIVE-sourced (no IaC contributed it), the profile records it via a detection_signals[].method of live_az, keys infrastructure[] by azure_id, sets sources_analyzed.terraform false and summary.inferred_from_iac false, and a captured deployment's model.name lands in models[] (the live signal is carried by the detection_signals[].method live_az entry, since models[].detected_via is limited to code|terraform|billing per schema-discover-ai.md and has no live value). Do NOT require tf_address, sources_analyzed.terraform, or inferred_from_iac for a resource whose source does not include terraform. This check is not vacuously satisfied merely because app-code found no AI signal"
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

## Status — build steps 2 and 4 (partial)

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
pre-work invoked from this phase's `_preconditions` prose** (see the
`_live_capture_prework` step), writing to `$MIGRATION_DIR/live-capture/`, with the
dispatched `live` fragment merely parsing that directory (its `_trigger` fires only
when `live-capture/manifest.json` exists). RDfA needs no such split: reading an archive
the customer already handed over is not interactive.

## Step: Run the phase

1. Perform `_init` state setup per `INTERPRETER.md` § `_init: true`.
2. Run each fragment whose `_trigger` holds.
3. Run `discover-assemble.md`.
4. Evaluate `_postconditions`. On all-pass emit `HANDOFF_OK`; on any failure emit
   `GATE_FAIL` and stop. Do not patch an artifact to force a gate to pass.
