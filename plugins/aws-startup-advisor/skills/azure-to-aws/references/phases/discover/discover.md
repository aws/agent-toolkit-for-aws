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
  - _id: rdfa
    _trigger: { _when: "$MIGRATION_DIR/rdfa-cache/manifest.json exists and identifies a successfully prepared RDfA source for THIS attempt. The main-window pre-dispatch action below selects, fingerprints, and prepares the source; this rw fragment reads only prepared JSON and never extracts ZIPs, runs Python, or prompts." }
    _file: phases/discover/discover-rdfa.md
  - _id: live
    _trigger: { _when: "$MIGRATION_DIR/live-capture/manifest.json exists AND is fresh for THIS attempt — i.e. the 'Pre-dispatch main-window action' below ran, the user consented, and (on a re-entry) any manifest from a prior attempt was invalidated per that section's decline rule. This dispatched fragment ONLY parses that directory; it never runs az or prompts. Absent (or invalidated) manifest ⇒ the trigger is false and the fragment does not run." }
    _file: phases/discover/discover-live.md
_assemble:
  _file: phases/discover/discover-assemble.md
_produces:
  - azure-resource-inventory.json
  - azure-resource-clusters.json
  - ai-workload-profile.json
  - openai-usage-profile.json
  - openrouter-usage-profile.json
  - anthropic-usage-profile.json
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
  - _assert: "at least one migratable source is available: an IaC source (a .tf file containing an azurerm_* resource, a .bicep file, or an ARM template whose $schema contains 'deploymentTemplate'), OR application source code / a dependency manifest that the app-code fragment can scan for an AI signal, OR a live-capture manifest ($MIGRATION_DIR/live-capture/manifest.json written by the live-az pre-work above), OR a validated RDfA preparation manifest ($MIGRATION_DIR/rdfa-cache/manifest.json written by the RDfA pre-work below). A workspace with NONE of these is the only unrecoverable case, matching gcp's 'stop only when nothing will produce any artifact'"
    _on_failure: _unrecoverable
_postconditions:
  - _assert: "at least one discovery artifact was produced: azure-resource-inventory.json (when an IaC source, live `az` capture, or prepared RDfA report produced resources) OR ai-workload-profile.json (when application code or an IaC/live/RDfA Cognitive Services / ML signal qualified). This is the completion anchor — an RDfA-only run and an app-code-only run both satisfy Discover. Usage profiles remain supplements, not anchors."
    _on_failure: _halt_and_inform
  - _assert: "if the 'OpenAI usage-API consent + capture' step ran (ai-workload-profile.json matched the ai_source condition, or the user mentioned OpenAI usage with no billing signal present), either $MIGRATION_DIR/openai-usage-profile.json exists, or the action was skipped/declined and no stale profile from a prior attempt is left on disk"
    _on_failure: _halt_and_inform
  - _assert: "same contract as the OpenAI assert above, substituting the OpenRouter step and openrouter-usage-profile.json"
    _on_failure: _halt_and_inform
  - _assert: "same contract as the OpenAI assert above, substituting the Anthropic step and anthropic-usage-profile.json; additionally, a $MIGRATION_DIR/anthropic-capture/manifest.json whose captures[] rows are ALL 'failed' (and whose retry_pending is not true) is itself a valid 'failed capture, no profile' terminal outcome, not a precondition for requiring anthropic-usage-profile.json — the manifest's mere existence never substitutes for at least one captures[].status == 'ok' row"
    _on_failure: _halt_and_inform
  - _assert: "WHEN an IaC source (.tf/.bicep/ARM) was found OR live `az` capture OR a prepared RDfA report produced at least one resource: azure-resource-inventory.json and azure-resource-clusters.json exist, validate as JSON, and the inventory has at least one resources[] entry with metadata carrying discovery_timestamp, discovery_sources, and subscriptions_discovered. WHEN the run is app-code-only (no infrastructure-producing source): the inventory and clusters artifacts are ABSENT (not written empty — see discover-assemble.md) and this is vacuously satisfied"
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
  - _assert: "PRODUCER AGREEMENT: WHEN azure-resource-inventory.json contains a case-insensitive azure_type in {Microsoft.CognitiveServices/accounts, Microsoft.CognitiveServices/accounts/deployments, Microsoft.MachineLearningServices/workspaces}, ai-workload-profile.json MUST exist and validate against schema-discover-ai.md, and infrastructure[] contains every qualifying resource. IaC entries are keyed by config.tf_address; live and RDfA entries are keyed by azure_id with truthful source provenance and no address/file. Profile flags are OR'd across the full set: sources_analyzed.terraform, .live, and .rdfa are independently true iff that source contributed; inferred_from_iac is true iff IaC contributed. Exact azure_id matches reconcile to one entry while retaining every contributing source; RDfA must never be mislabeled as live_az or Terraform. This check is not vacuously satisfied merely because app-code found no AI signal"
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

## Pre-dispatch main-window actions

Run the shared Step 0 first, then both source actions, all BEFORE `_preconditions` and
fragment dispatch. The main window has execution capability; the dispatched `_agent: rw`
worker does not.

### Shared Step 0 — initialize the run before either source action

Perform `_init` state setup per `INTERPRETER.md` § `_init: true` before RDfA detection or
live-`az` consent/capture accesses `$MIGRATION_DIR`. Resolve resume-vs-fresh, set
`$MIGRATION_DIR`, and, on a fresh run, create the directory, `.gitignore`, and
`.phase-status.json` exactly as that section specifies. When LLM A1 entered this phase,
the same fresh-state write MUST include `initiated_by: "LLM_TO_BEDROCK"` beside
`owning_skill`. Resume, fresh-run selection, or cancellation therefore completes before
either pre-dispatch action runs; cancellation terminates the phase without running either
action.

This phase's normal `_init` call in "Step: Run the phase" remains an idempotent
confirmation. A resumed run reuses its selected `$MIGRATION_DIR` and existing
`.phase-status.json`; initialization is not duplicated and resume-vs-fresh is not
re-prompted.

### RDfA detection, guidance, and preparation

1. Detect candidate `*ResourcesReport*.zip` files and extracted directories containing
   `Inventory_*.json`, including a path explicitly named by the user. On re-entry, first
   seed candidates from the existing manifest's `source_path` when that external path
   still exists and can be fingerprinted; the user does not need to name it again. A
   newly confirmed replacement supersedes that recorded candidate. Do not treat files
   under `$MIGRATION_DIR/rdfa-cache/` as source candidates. If the recorded source is
   gone or its fingerprint changed, invalidate its prepared cache; a changed source that
   still exists remains a candidate and must be prepared again.
2. If no candidate exists, output `discover-rdfa.md`'s optional-accuracy informational
   block now (when live capture also produced no manifest). This is deliberately here,
   because an absent report makes the `rdfa` fragment trigger false.
3. Select the newest candidate using `discover-rdfa.md`'s normalized timestamp rule, or
   the newly user-confirmed source. Compute a deterministic SHA-256 fingerprint from the
   selected source (ZIP bytes; for a directory, sorted relative paths plus file bytes).
4. Compare `{source_path, source_type, fingerprint}` with
   `$MIGRATION_DIR/rdfa-cache/manifest.json`. Reuse prepared files only on an exact match.
   A confirmed replacement invalidates and rebuilds the derived cache. The source path
   remains the external directory/ZIP; generated files are never source candidates.
5. In this MAIN window, extract ZIPs (including nested subscription ZIPs), validate JSON,
   flatten each producer metrics object by concatenating its `Metrics` array, and project
   large inputs. Write prepared files under `$MIGRATION_DIR/rdfa-cache/prepared/`. Before
   preparation, create `$MIGRATION_DIR/rdfa-cache/preparation-result.json`; update it
   atomically with `selected_source`, `status` (`prepared`, `partial`, or `failed`), the
   count of valid reports, and schema-shaped `warnings[]`. Write the successful identity
   manifest last, and only when at least one report was prepared. Use Python's standard
   `zipfile`/`json` libraries if needed; delete any temporary script after it runs. The
   dispatched RDfA fragment only reads these prepared files.
6. The MAIN window owns every preparation failure because the RDfA fragment cannot
   dispatch without a success manifest. Catch a corrupt or password-protected ZIP, an
   invalid `Inventory_*.json`/`Metrics_*.json`, and a matching archive with no report
   files. Record `rdfa_report_unreadable` in `preparation-result.json`, with the failing
   path in `identifier` and the failure in `detail`. Skip only that report: for a bad
   nested archive, continue preparing every other valid inner ZIP and use `partial` when
   any succeeds. For a corrupt selected report with no valid content, use `failed`, leave
   `manifest.json` absent, and output the warning plus the optional-accuracy fallback.
   Such a failed preparation is not itself a migratable source: continue through assembly
   when IaC, live capture, or app code can produce an artifact; otherwise surface the
   warning and fallback before the entry gate reports that no artifact-producing source
   remains.

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

The shared Step 0 above has already established the selected run and
`$MIGRATION_DIR` before this action begins, including writing `initiated_by:
"LLM_TO_BEDROCK"` when LLM A1 entered this phase.

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
| step 2   | RDfA archive parsing is real (`discover-rdfa.md`), alongside live `az` (`discover-live.md`)                                                                                                                            |
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
`live-capture/manifest.json` exists for this attempt). RDfA uses the same capability
boundary for a different reason: archive extraction and projection are non-interactive but
still executable work. They run in the main-window pre-dispatch action; the `rw` fragment
only maps prepared JSON.

## Step: Run the phase

1. Confirm the shared pre-dispatch `_init` state setup per `INTERPRETER.md` §
   `_init: true`. This normal `_init` call is idempotent: the run was already
   selected before RDfA preparation and live-`az` capture, so reuse the same
   `$MIGRATION_DIR` and `.phase-status.json` without re-creating state or
   re-prompting resume-vs-fresh.
2. Run each fragment whose `_trigger` holds. RDfA ZIP extraction/projection has already
   completed in the main-window pre-dispatch action; the `rw` fragment performs file-only
   mapping.
3. Run `discover-assemble.md`.
4. Run the usage-API consent + capture steps, in order: OpenAI, then
   OpenRouter, then Anthropic (each in full, Steps 0–4 of its own file). This
   runs AFTER the fragments and `discover-assemble.md` (step 3) specifically
   so that, on a from-scratch migration, `ai-workload-profile.json` already
   exists (written by the app-code fragment / assembler) by the time these
   steps evaluate their own `ai-workload-profile.json`-based trigger
   condition — running them any earlier (as a pre-dispatch action, before
   fragments/assembly) would see that file not yet exist on a fresh run.

   ### OpenAI usage-API consent + capture

   Run `discover-openai-api.md` in full (Steps 0–4) when EITHER:

   - `ai-workload-profile.json` exists with `summary.ai_source` of `openai` or `both`, OR
   - no Azure Cost Management billing signal exists in this run AND the user mentions direct
     OpenAI usage/spend in conversation (NOT Azure OpenAI — see the file's own disambiguation note).

   This is a judgment call made HERE, in the main window — not expressed as a DSL `_trigger`
   predicate, because the decision requires reading conversational context no dispatched
   fragment ever sees (the SAME reasoning the live-`az` offer step above already states for
   itself).

   **Re-entry check (do this FIRST, before offering consent), same rule as live `az`:** if
   `$MIGRATION_DIR/openai-usage-profile.json` already exists from a prior attempt in THIS run
   directory, do NOT silently trust it — re-offer `discover-openai-api.md`'s Step 0 consent gate
   for THIS attempt; on decline, delete/rename the existing profile file before continuing.

   The file's own Step 0 consent gate is the single consent point for this source — do not
   pre-ask here; loading the file only presents the gate. If `discover-openai-api.md`'s Step 0
   consent is declined, or the key is unavailable, ensure no `openai-usage-profile.json` is
   present and continue. This action never fails the phase; it only determines whether
   `openai-usage-profile.json` is present and current for THIS attempt.

   ### OpenRouter usage-API consent + capture

   Run `discover-openrouter-api.md` in full (Steps 0–4) when EITHER:

   - app-code discovery (`discover-app-code.md`) detected `integration.gateway_type: llm_router`
     with an `openrouter.ai` base URL, OR
   - no Azure Cost Management billing signal exists in this run AND the user mentions OpenRouter
     usage/spend in conversation.

   This is a judgment call made HERE, in the main window — not expressed as a DSL `_trigger`
   predicate, because the decision requires reading conversational context no dispatched
   fragment ever sees (the SAME reasoning the live-`az` offer step above already states for
   itself).

   **Re-entry check (do this FIRST, before offering consent), same rule as live `az`:** check
   `$MIGRATION_DIR/openrouter-capture/manifest.json` FIRST — do NOT key this check off bare
   `openrouter-usage-profile.json` existence alone (a run that stopped mid-retry, e.g.
   `/activity: ok` with `/analytics/query: failed`, has no profile written yet since Step 3
   never ran, so a profile-existence-only check would wrongly treat it as a fresh run and
   re-offer Step 0 consent, discarding the already-good `/activity` capture and re-prompting
   for a key the user already provided):

   - **No manifest** → fresh run; offer `discover-openrouter-api.md`'s Step 0 consent gate as
     today.
   - **Manifest exists, `/activity` entry `"ok"`, NO `/analytics/query` entry present at all**
     (an old three-entry manifest from before the Analytics row existed: `/credits`, `/activity:
     ok`, `/key`) → PERMANENTLY `cost_provenance: "unknown"` for this manifest — do NOT attempt a
     live upgrade to Analytics-backed data, and make NO new request. The consent that produced this
     old manifest predates the `/analytics/query` POST's existence in Step 0's disclosure, so it
     cannot have covered that call, and by this point the capture's key file is already deleted and
     the manifest has no `window_start_utc`/`window_end_utc` to supply a retry's `time_range`
     anyway. Route into `discover-openrouter-api.md`'s EXISTING unknown-provenance handling: resume
     it directly at Step 3 (parse the already-captured `activity.json`; never re-capture), treating
     the absent `/analytics/query` entry exactly as Step 3's own rollup rule treats a
     `failed`/`skipped` Analytics row — `cost_provenance: "unknown"` for every model, with the
     matching `capture_warnings` entry. Do NOT re-offer Step 0 consent (no new request, nothing new
     to consent to) and do NOT enter Step 2 for this manifest.
   - **Manifest exists, `/activity` entry `"ok"`, `/analytics/query` entry `"failed"`** → a
     pending Analytics-only retry — do NOT re-offer consent; resume
     `discover-openrouter-api.md` from its Step 2 Analytics-only retry path (reusing the
     already-good `/activity.json`, per that file's own independent-resume rule for
     `/analytics/query`), then proceed to Step 3 once Analytics reaches a terminal state.
   - **Manifest exists, `/activity` entry `"ok"`, `/analytics/query` entry `"ok"` or
     `"skipped"`, and `openrouter-usage-profile.json` exists** → a prior attempt fully
     completed; keep today's behavior for this case — re-offer `discover-openrouter-api.md`'s
     Step 0 consent gate for THIS attempt, and on decline, delete/rename the existing profile
     file before continuing (reusing a fully-completed prior attempt silently for a NEW
     attempt is still wrong, per the existing re-entry philosophy).
   - **Manifest exists, `/activity` entry `"failed"` or `"skipped"`** → route into
     `discover-openrouter-api.md`'s own documented resume rules for that row (retry, or
     exit-cleanly-no-reask respectively) — do not re-offer Step 0 either.

   The file's own Step 0 consent gate is the single consent point for this source — do not
   pre-ask here; loading the file only presents the gate. If `discover-openrouter-api.md`'s
   Step 0 consent is declined, or the key is unavailable, ensure no
   `openrouter-usage-profile.json` is present and continue. This action never fails the phase;
   it only determines whether `openrouter-usage-profile.json` is present and current for THIS
   attempt.

   ### Anthropic usage-API consent + capture

   Run `discover-anthropic-api.md` in full (Steps 0–4) when EITHER:

   - `ai-workload-profile.json` exists with `summary.ai_source` of `anthropic` or `both`, OR
   - no Azure Cost Management billing signal exists in this run AND the user mentions direct
     Anthropic/Claude usage or spend in conversation.

   This is a judgment call made HERE, in the main window — not expressed as a DSL `_trigger`
   predicate, because the decision requires reading conversational context no dispatched
   fragment ever sees (the SAME reasoning the live-`az` offer step above already states for
   itself).

   **Re-entry check (do this FIRST, before offering consent), same rule as live `az`:** if
   `$MIGRATION_DIR/anthropic-capture/manifest.json` already exists from a prior attempt in THIS
   run directory, check its `captures[]` rows first — do NOT silently trust bare manifest
   existence. At least one `status: "ok"` row means capture already happened cleanly; still
   re-offer `discover-anthropic-api.md`'s Step 0 consent gate for THIS attempt (same rule as
   live `az`), and on decline, delete/rename the existing manifest and
   `anthropic-usage-profile.json` before continuing. A manifest whose `captures[]` rows are ALL
   `"failed"` (and whose `retry_pending` is not `true`) means the prior attempt never reached a
   terminal successful state — this is a valid "failed capture, no profile" outcome, not a
   resumable one; treat it like a Step 0 consent decline (exit cleanly, no re-ask) unless
   `retry_pending` is `true` (the `KEY_INVALID_MID_RUN` carve-out), in which case re-run from
   Step 2.

   The file's own Step 0 consent gate is the single consent point for this source — do not
   pre-ask here; loading the file only presents the gate. If `discover-anthropic-api.md`'s
   Step 0 consent is declined, or the key is unavailable, ensure no
   `anthropic-usage-profile.json` is present and continue. This action never fails the phase;
   it only determines whether `anthropic-usage-profile.json` is present and current for THIS
   attempt.

   **Billing-export precondition, named honestly:** azure's discover phase today has exactly
   four fragments — `iac`, `app-code`, `rdfa`, `live` — and no billing fragment at all; Azure Cost
   Management export discovery is not yet implemented in this skill. The three sub-sections
   above therefore read "no Azure Cost Management billing signal exists in this run," which
   today is unconditionally true (there is no billing fragment to produce one) — phrased this
   way so the condition degrades gracefully and starts working automatically, with no further
   edit needed, the day a billing fragment lands; it is not a blocking gap for this PR, since
   the OR's left-hand branches (profile/app-code signal) and the plain "user mentions it" branch
   already cover the common case.
5. Output to user — build message from whichever artifacts exist:
   - If `azure-resource-inventory.json` exists: "Discovered X total resources across Y clusters."
   - If `ai-workload-profile.json` exists: "Detected AI workload: [summary]."
   - If `openai-usage-profile.json` exists: "Captured OpenAI usage via Admin API ($X/month across
     M models)." Plus, when `metadata.capture_warnings` is non-empty: "W usage endpoints failed —
     affected categories are unknown, not zero (see profile metadata)."
   - If `openrouter-usage-profile.json` exists: "Captured OpenRouter usage via API ($X/month
     across M models)." Plus the same capture_warnings addendum.
   - If `anthropic-usage-profile.json` exists: "Captured Anthropic usage via Admin API ($X/month
     across M models)." Plus the same capture_warnings addendum.
6. Evaluate `_postconditions`. On all-pass emit `HANDOFF_OK`; on any failure emit
   `GATE_FAIL` and stop. Do not patch an artifact to force a gate to pass.

## Output Files

**Discover phase writes files to `$MIGRATION_DIR/`. Possible outputs (depending on what runs):**

1. `azure-resource-inventory.json` — from `discover-iac.md`, `discover-live.md`, and/or
   `discover-rdfa.md`; `metadata.discovery_sources` records only actual contributors and
   `rdfa_metadata` records the selected report provenance
2. `azure-resource-clusters.json` — from any infrastructure-producing source (IaC, live, or RDfA)
3. `ai-workload-profile.json` — from `discover-app-code.md` (confidence ≥ 70%, optionally merged)
   and/or infrastructure-inferred (IaC, live, or RDfA Cognitive Services / ML signal)
4. `openai-usage-profile.json` — from `discover-openai-api.md` (plus `openai-capture/` raw
   captures inside the gitignored run directory; the transient `.openai-admin-env` key file is
   deleted by that sub-file's Step 4 and is never a phase output)
5. `openrouter-usage-profile.json` — from `discover-openrouter-api.md` (plus
   `openrouter-capture/` raw captures inside the gitignored run directory; the transient
   `.openrouter-key-env` key file is deleted by that sub-file's Step 4 and is never a phase
   output)
6. `anthropic-usage-profile.json` — from `discover-anthropic-api.md` (plus
   `anthropic-capture/` raw captures inside the gitignored run directory; the transient
   `.anthropic-admin-env` key file is deleted by that sub-file's Step 4 and is never a phase
   output)

**No other files must be created:** no README.md, no discovery-summary.md, no `*.txt` report,
no generated `terraform/`, no `preferences.json` — see `_forbids_files` in the frontmatter.
All user communication is via output messages only.
