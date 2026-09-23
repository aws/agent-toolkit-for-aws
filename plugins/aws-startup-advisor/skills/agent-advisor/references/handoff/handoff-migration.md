# Handoff — Migrate path

Loaded from **Generate Step 6** for `migrate` (always — Step 1 runs before Gate 1 is asked)
and from **migration-plan.md Step 2** for `build_deploy` (when `handoff-summary.md` is
needed as the injection payload source but doesn't exist yet). Step 1 writes the summary;
Steps 2–4 run ONLY on Gate 1's "No" branch (the classic pointer-downstream ending).
`handoff-summary.md` serves two purposes: the machine-readable companion for downstream
skills, and the rationale source for Stage 2's injection context block.

## Step 1 — Write the handoff summary

Write `$RUN_DIR/handoff-summary.md` (a compact, machine-readable companion to
`recommendation.md` for the downstream plugins) containing: recommended runtime + deployment
model + services, coarse model family mapping (the source model from the user's `current_model`
answer → the Bedrock family per `model-selection.md`; no prices), and the rationale (top scoring
signals + eliminations, from design.json's `scores`/`eliminated`).

## Step 2 — Check downstream availability

Both downstream skills — `gcp-to-aws` and `llm-to-bedrock` — are part of this same plugin, so
they are always available; no availability check or install is needed.

## Step 3 — Direct the user

- For infrastructure/container migration (ECS/EKS/Lambda compute): invoke the **`gcp-to-aws`
  skill** — it lives in this same plugin. Point the user to re-run it with
  the handoff summary at `$RUN_DIR/handoff-summary.md`.
- For AI/LLM workload migration (model swap, SDK rewrite): invoke the **`llm-to-bedrock` skill**
  (`/aws-startup-advisor:llm-to-bedrock`) — also in this same plugin, no separate install. Point
  the user to re-run it with the handoff summary at `$RUN_DIR/handoff-summary.md`.

## Step 4 — Finish

Return to Generate Step 7 (Gate 1 was answered "No" — `phases.migration_plan` = "skipped").
Tell the user the advisor phase is done: they have the recommendation doc + architecture
diagram (`recommendation.md`), and the handoff summary (`handoff-summary.md`) is saved for
the downstream plugins. Offer to kick off the recommended downstream plugin.
