---
_phase: generate
_title: "Generate — Recommendation Doc + Scaffolding"
_requires_phase: estimate
_input:
  - design.json
  - confirm.json
_fragments:
  - _id: generate-report
    _trigger: { _always: true }
    _file: phases/generate/generate-report.md
_assemble:
  _file: phases/generate/generate-assemble.md
_produces:
  - diagram.md
  - recommendation.md
  - mini-brief.md
  - recommendation-report.html
_advances_to: migration-plan
_preconditions:
  - _check_phase_completed: estimate
    _on_failure: _halt_and_inform
  - _check_file_exists: design.json
    _on_failure: _unrecoverable
  - _validate_json: design.json
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: [diagram.md, recommendation.md, mini-brief.md, recommendation-report.html]
    _on_failure: _halt_and_inform
  - _assert: "recommendation.md fills all 12 sections (business summary first, technical detail after) with the freshness footer; mini-brief.md carries the recommendation, top-3 signals, eliminated, model, and any io_wait/fedramp/region/cris notes set in design.json (a non-agent unit in a mixed system may show 'no model' when its model_recommendation is null); recommendation-report.html was generated (Step 5 is not optional); when design.json has >1 unit, recommendation.md contains the System topology section and the report one unit card per unit; every unit card whose design.json unit has a non-null model_recommendation contains the 'Why this model' card (rationale paragraph + collapsed 'Full model & migration detail' details block) rendered from unit.model_recommendation values, not invented"
    _on_failure: _halt_and_inform
  - _assert: "recommendation.md's architecture-diagram section carries diagram.md's content INLINE — the Mermaid fenced block itself (and the ASCII fallback when build_diagram.py produced one), copied verbatim. A pointer such as 'see diagram.md' does not satisfy it: the recommendation doc is read on its own, often as the only artifact a reader opens, and the diagram is the section's whole content"
    _on_failure: _halt_and_inform
  - _assert: "every score reported in recommendation.md, mini-brief.md, and the report is the engine's own number, exactly as scoring-result.json states it — no derived total, percentage, or invented denominator (scoring-result.json carries no maximum, so a form like '40/56' is a number the engine never produced)"
    _on_failure: _halt_and_inform
  - _assert: "recommendation-report.html follows the v3 section spec from generate-report.md Step R1 — its numbered top-level sections are, in order: Summary, Assessment inputs, Recommendation(s), Target architecture, then (Temporal migration only when temporal units exist), Cost summary, Next steps, Generated artifacts, with the dynamic numbering R1 defines; an html whose top-level section structure was invented instead of taken from the template (a known failure mode after a mid-phase context compaction) fails this phase — re-read generate-report.md and regenerate"
    _on_failure: _halt_and_inform
---

# Phase: Generate — Recommendation Doc + Scaffolding

## Step 1 — Read inputs

Read `$RUN_DIR/design.json`. Read `$RUN_DIR/estimate.json` **if it exists** (all entry points
except add_capabilities produce estimate.json; if it is absent — failure, or add_capabilities —
Generate notes the absence in the report instead of inventing numbers). Load the
winning runtime's service card and
`${CLAUDE_PLUGIN_ROOT}/skills/agent-advisor/references/decision-refs/model-selection.md`.
(Same exception as Design Step 2: a `serverless_workers` unit has NO `<verdict>.md` card — do not
attempt to load one; derive its content from `temporal.md` + `poc-shapes.md`.)

## Step 2 — Build the architecture diagram

Load `references/diagram/build-diagram.md` and follow it to produce `$RUN_DIR/diagram.md`
(Mermaid + ASCII), then embed it into Section 4 of the recommendation doc.

**Embed means paste the content, not link to it.** Copy `diagram.md`'s fenced Mermaid block (and its
ASCII fallback) into Section 4 verbatim. "See `diagram.md`" leaves the section empty for anyone
reading `recommendation.md` on its own, which is how it is usually read — it is the artifact that
gets forwarded, and the diagram is that section's entire content.

## Step 3 — Fill the recommendation document

Load `references/output-templates/recommendation-doc.md`. Fill ALL 12 sections. Business
summary first, technical detail after (single layered doc — do not fork by audience). Write to
`$RUN_DIR/recommendation.md`. Append the freshness footer.

For `migrate`: also fill Section 9 (Bedrock model) with the **coarse family mapping**
(e.g. "GPT-4o → Claude Sonnet 5 family") and a note that detailed pricing/TCO come from the
migration plugins — no dollar figures. Section 10 (cost magnitude) presents the per-unit
target-state bands from estimate.json and notes that the migration TCO comparison and
current-spend delta are produced by the migration plugins.

**Section 3c — Temporal migration** (conditional: only if ANY
`design.json.units[].workload_class == "temporal_worker_poll"` — the `temporal` block has no
`units` field, so gate on the unit list, matching generate-report.md's TEMPORAL_UNITS_PRESENT):
orchestrate §3c content from `design.json.temporal` + decision-refs/temporal.md. Load the
commercials/runbook text from decision-refs/temporal.md (never restate). The Bedrock follow-up gate
runs HERE conditionally:

- AskUserQuestion: "Move Activity LLM calls to Bedrock as part of this migration?"
- **Yes** → append "Bedrock migration" section to recommendation.md §3c: (a) point to
  `/aws-startup-advisor:llm-to-bedrock` skill as follow-up, (b) REQUIRE replay safety per
  decision-refs/temporal.md runbook 3 (keep Workflow determinism against recorded history, or
  isolate via Worker Versioning / new task queue). If deeply-coupled AI integrations flagged,
  note the rewrite must respect the shim.
- **No** → append "Later, optional: Bedrock" section with the same replay-safety pointer.

**No Step Functions comparison section** — the scope note at the top of the plan already states
the orchestration layer stays on Temporal. If the user asks why, answer in chat per
decision-refs/temporal.md ("If the user asks") — do not add it to the plan.

## Step 4 — Lightweight scaffolding (Build paths only)

**Skip this step entirely for `migrate`** (execution artifacts belong to the downstream plugins).
For Build paths:

- AgentCore + Harness → write a minimal `harness.json` skeleton with the selected services.
  Include the exact `invocation_model_id` only when `live_verification.status == "passed"`;
  otherwise use `TODO: verify model id` and state that account access is unverified.
- AgentCore + Framework / other runtimes → write a minimal framework starter note (entrypoint
  contract: `/invocations` POST + `/ping` GET for AgentCore) + the same verified invocation ID
  or explicit TODO placeholder.
  Write scaffolding under `$RUN_DIR/scaffold/`. Keep it minimal — heavy IaC hands off.

## Step 4.5 — Write the mini-brief to `$RUN_DIR/mini-brief.md` (delivered by the Step 5.5 sidebar)

Compose the **mini-brief** — it is the deliverable of the whole advisor flow — and WRITE IT
TO `$RUN_DIR/mini-brief.md` (a file, not just chat text; Step 5.5 re-reads it):

- Recommendation (runtime + deployment model), Why (top 3 signals), Eliminated, Model, and a
  pointer to `$RUN_DIR/recommendation.md`.
- For each model-bearing unit, include API path, path-specific model ID, CRIS/invocation status,
  `[BLOCKS]`, evaluation mode, and live verification status. Never describe model access as
  runnable unless `live_verification.status == "passed"`.
- Any `warnings` from the scoring result (e.g. 5 TPS).
- If `design.json` has `io_wait_tco_note == true`: the I/O-wait TCO point (AgentCore bills $0
  during model/human waits — a cost edge for spiky/HITL traffic; no dollar figures).
- When set: `fedramp_note` (FedRAMP WIP — verify + GovCloud fallback),
  `region_availability_note` (runtime not in the user's region — nearest supported), and
  `cris_note` (geo-CRIS vs global-CRIS data-residency choice for EU/GDPR).

## Step 5 — Generate HTML recommendation report

**You MUST produce `$RUN_DIR/recommendation-report.html` — it is a required output of
this phase, not optional.** Load `references/phases/generate/generate-report.md` and follow it to
write the file, then open it in the user's browser.

Scope of "non-blocking": only the **browser-opening** and a genuine build _failure_ are
non-blocking — NOT the generation itself. So:

- If the `open`/`xdg-open` command fails (no GUI): print
  `Report ready — open: file://$RUN_DIR/recommendation-report.html` and continue.
- If writing the HTML genuinely errors: log the specific warning and continue.
- Never SKIP this step to reach Step 5.5 faster. Step 5.5 checks that the file exists
  (below) — if it is missing, you skipped Step 5 and must come back and do it.

## Step 5.5 — Recommendation review sidebar (BLOCKING — the user must see and confirm the recommendation before any gate)

**Precondition check (do this FIRST, before composing the sidebar):** confirm
`$RUN_DIR/recommendation-report.html` exists on disk. If it does NOT, Step 5 was skipped —
go back and run Step 5 now (generate the report + open it) before proceeding. Do not
present this sidebar without the report having been generated.

This is its own turn, separate from every gate. Send ONE message whose body is the **full
mini-brief pasted from `$RUN_DIR/mini-brief.md`**, followed in the SAME message by an
AskUserQuestion:

> [contents of $RUN_DIR/mini-brief.md]
>
> "This is the recommendation. Take a moment to review it (full detail in
> `$RUN_DIR/recommendation.md`) — does it look right before we talk about next steps?"
>
> - **Looks good — continue** → record the confirmation (below) and proceed to Step 6.
> - **Explain more first** → answer the user's questions on the recommendation (from
>   recommendation.md / design.json — no new scoring), then re-ask this sidebar.
> - **Something's off — revisit an answer** → identify which clarify answer changed, update
>   `answers.json`, re-run scoring, and redo Design → Generate. Do NOT proceed on a
>   recommendation the user disputes.

On "Looks good — continue": read-merge-write `.phase-status.json` and set top-level
`"recommendation_reviewed": true`.

**Mechanical gate rule:** Steps 6 and 7 MUST NOT ask Gate 1 or Gate 2 unless
`.phase-status.json` has `recommendation_reviewed == true`. If it is absent, you skipped
this sidebar — go back and run it. This ordering is not optional and does not collapse
into the gate question: the user confirms they have SEEN the recommendation first, and only
then is asked what to do next. (Resume-safe: if the session breaks after confirmation, the
flag survives and the sidebar is not re-asked.)

Because the sidebar delivered the brief, the gates below only need a one-line recap
(runtime + deployment model + model), not the full brief.

## Step 6 — Migration-plan gate (Gate 1)

**Precondition:** `.phase-status.json.recommendation_reviewed == true` (set by Step 5.5).
Absent → run Step 5.5 first; never ask this gate without it.

**Applicability** (skip this step when none applies — mark `phases.migration_plan = "not_applicable"`):

- entry_point == `migrate` → always offer.
- entry_point == `build_deploy` → offer ONLY if Discover ran and
  `$RUN_DIR/context-signals.json.model_provider` ∈ {openai, anthropic, google-genai} —
  i.e. something real exists to migrate. Key absent, `none`, or `bedrock` → not applicable.
- entry_point == `build_scratch` → never (nothing existing to migrate).

For `migrate`, FIRST load `references/handoff/handoff-migration.md` and follow its Step 1 to
write `$RUN_DIR/handoff-summary.md` (it is both the human-readable handoff artifact and the
Stage 2 injection payload source). Then ask **Gate 1** — a one-line recap (runtime +
deployment model + model; the full brief was confirmed at Step 5.5), followed by the
AskUserQuestion in the same message:

> Recommended: `<runtime>` + `<deployment model>`, model `<model>` (details: recommendation.md).
>
> "Do you want a complete migration plan for this workload? I'll generate
> it here using this plugin's migration engine, reusing the decisions we already made
> (runtime, deployment model, memory). It will analyze your code and may ask a few extra
> questions."
>
> - **Yes — generate the migration plan** → set `phases.migration_plan = "pending"`;
>   after Step 7 the state machine loads `references/phases/migration-plan/migration-plan.md`.
> - **No** → set `phases.migration_plan = "skipped"`. For `migrate`, keep the classic
>   pointer: follow handoff-migration.md Steps 2–4 (direct the user to
>   `/aws-startup-advisor:llm-to-bedrock` or `gcp-to-aws` with `handoff-summary.md`).

## Step 7 — Write state and branch

Set `phases.generate` = completed (read-merge-write). Then branch:

1. **Gate 1 answered Yes** → next phase is `migration_plan`: load
   `references/phases/migration-plan/migration-plan.md`. Gate 2 is offered from that phase's Step 6.
2. **Otherwise, if** entry_point ∈ {`build_scratch`, `build_deploy`}: ask **Gate 2** for the
   primary unit's `effective_runtime` — any of agentcore / ecs / eks / lambda / lambda_microvms
   (the primary is always an agent unit per Clarify's scope gate). In a MULTI-unit system, each
   non-primary unit still gets its own POC per poc.md Step 3 dispatch (incl. batch / fargate /
   serverless_workers, and a model-less non-agent unit omits Bedrock wiring). Precondition
   unchanged (`recommendation_reviewed == true`). Give a one-line recap (runtime + deployment
   model + model), followed by the AskUserQuestion in the same message:

   > Recommended: `<runtime>` + `<deployment model>`, model `<model>` (details: recommendation.md).
   >
   > "Do you want a deployable proof-of-concept for this recommendation on `<runtime>`?
   > I'll generate the agent code, deployment plan, and scripts."
   >
   > - **Yes** → set `phases.poc = "in_progress"` (persist the confirmation), then load
   >   `references/phases/poc/poc.md` (it asks which POC mode first).
   > - **No** → set `phases.poc = "skipped"`; the advisor flow is complete.

3. **Otherwise** (migrate without a plan): the Step 5.5 sidebar already delivered the
   brief; close with a short completion message pointing at `recommendation.md` — the
   advisor flow is complete.

**Non-interactive runs (seeded).** When `$RUN_DIR/seed.json` exists (clarify.md Step 2.5), its
`gates` block answers these gates instead of AskUserQuestion: `gates.migration_plan` and
`gates.poc`, each `accept` or `decline`. **A gate the seed does not mention is DECLINED** —
never accept a gate on the user's behalf, because both gates spend real time and money. Persist
the resolved status exactly as the interactive path does (`phases.poc = "in_progress"` before
poc.md loads on accept, `"skipped"` on decline) so a resumed run does not re-ask. Record in
`$RUN_DIR/UNANSWERED.md` that the gate was resolved from the seed default rather than by a human
whenever the seed was silent.

Note: for `migrate` WITH a completed migration plan, Gate 2 is asked at the end of
migration-plan.md (its Step 6), using the same wording as point 2 above.

## Maturity/readiness output extension

Recommendation.md and mini-brief.md must state target maturity, readiness status, concrete gaps, tier-appropriate release/evaluation gates, recommendation status, and every deferred verification requirement. Label the mini-brief **Provisional** whenever `design.json.recommendation_status == "provisional"`; it must say that no runtime decision, pricing claim, or launch gate relying on deferred evidence is final. Include the AgentCore I/O-wait billing benefit only when Design recorded current-run verification; otherwise report the check as pending without a static billing result.
