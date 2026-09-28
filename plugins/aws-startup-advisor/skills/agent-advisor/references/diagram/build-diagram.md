# Build the architecture diagram

Produces `$RUN_DIR/diagram.md` (a Mermaid block + ASCII fallback). This sub-step runs at TWO
points in the flow, and which path applies depends on WHEN it runs:

1. **During Generate** — the migration plan does not exist yet (Gate 1 comes AFTER Generate).
   Always use **Path 1** (generic selection diagram).
2. **After Migration Plan completes** — `aws-design-ai.json` now exists. Re-generate the
   diagram using **Path 2** (plan-backed app architecture), overwrite `$RUN_DIR/diagram.md`,
   and re-embed it into `recommendation.md` §4. This is invoked from migration-plan.md's
   final step, not from Generate.

## Which path

- **Path 1 — generic selection diagram** (deterministic composer). Shows the recommended
  runtime + model + attached services, independent of any specific app. Used during Generate,
  and as the only diagram when no migration plan is produced.
- **Path 2 — plan-backed app architecture** (hand-composed). Reflects the user's ACTUAL app
  components as they map onto AWS. Used only after Migration Plan completes
  (`migration_plan_ctx` present AND `phases.migration_plan == "completed"` AND
  `aws-design-ai.json` readable).

## Path 1 — Generic selection diagram (deterministic composer)

```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/skills/agent-advisor/scripts python ${CLAUDE_PLUGIN_ROOT}/skills/agent-advisor/scripts/build_diagram.py \
  $RUN_DIR/scoring-result.json $RUN_DIR/confirm.json $RUN_DIR/design.json
```

This writes `$RUN_DIR/diagram.md` and prints `RESULT=ok RUNTIME=<id>`. If `confirm.json` is
absent (e.g. co_recommend not yet resolved), the composer treats it as empty. Do not
hand-edit — it is generated so it stays consistent with the scoring result.

The composer renders the correct topology: `User → Runtime → Bedrock model` is the primary
(solid) data flow; AgentCore services are cross-cutting capabilities grouped in a subgraph
and attached with a dotted edge — NOT downstream call targets.

## Path 2 — Plan-backed app architecture (hand-composed from the migration plan)

The generic composer only knows runtime + model + services — it cannot show the app's real
shape. When a migration plan exists, compose the diagram from the plan instead so it depicts
what the user is actually deploying.

**Read** `<migration_plan_ctx.migration_dir>/aws-design-ai.json` (path from
`.phase-status.json`). Use these fields:

- `ai_architecture.code_migration.primary_pattern` / `framework` — the app's framework
  (e.g. langchain, direct SDK) and integration pattern.
- `ai_architecture.code_migration.agentcore_entrypoint` — the serving contract
  (`/invocations` + `/ping`) if present.
- `ai_architecture.bedrock_models[]` / `design_blocks[]` — source model → target Bedrock
  model (the provider swap).
- `ai_architecture.services_to_migrate[]` — what each existing component maps to on AWS.
- `$RUN_DIR/confirm.json` `agentcore_services` — the AgentCore services to enable.
- The app's UI/interface layer from `$RUN_DIR/context-signals.json` (`ui_layer`, e.g.
  chainlit) or the migration plan's file list.

**Compose the Mermaid diagram to show the REAL components and their relationships**, using
the same topology discipline as Path 1:

- **Primary request flow (solid edges):** User → the app's entry surface (the runtime hosting
  the migrated app + its `/invocations` entrypoint) → the app's orchestration layer (e.g.
  LangChain) → the Bedrock target model. Show the provider swap explicitly — label the model
  node with the migrated target (e.g. "Bedrock: Claude Sonnet 5") and note the source it
  replaced where useful (e.g. "was: OpenAI gpt-3.5-turbo").
- **State / memory (solid edge to a store):** if the app has conversation memory, show it as
  its own node mapped to its AWS target (e.g. in-process `ConversationBufferWindowMemory` →
  AgentCore Memory, per `services_to_migrate`), connected to the orchestration layer.
- **AgentCore services (dotted, grouped):** the enabled services from `confirm.json` as a
  subgraph attached to the runtime with a dotted edge — same as Path 1, cross-cutting
  capabilities, not call targets. Do NOT duplicate the Memory node here if it's already shown
  as a state store on the primary flow — show it once, on the flow, and note it's also an
  AgentCore service.
- **UI note:** if the source app has a browser UI (e.g. Chainlit) that becomes local-dev-only
  after migration (the runtime serves `/invocations`, not a browser UI), represent that
  honestly — a dashed/annotated "Chainlit UI (local dev)" node, not on the production request
  path.

Keep it readable — the real components (UI, entry/runtime, orchestration, model, memory/state,
services) without inventing infrastructure the plan doesn't call for. Write BOTH a
`flowchart TD` Mermaid block AND an ASCII fallback (same structure), in the same `diagram.md`
format Path 1 emits:

````markdown
```mermaid
flowchart TD
    ...
```

<details><summary>ASCII (plain-text fallback)</summary>

```
...
```

</details>
````

## Step 2 (both paths) — Embed into the recommendation

Insert the full contents of `$RUN_DIR/diagram.md` into Section 4 ("Architecture diagram") of
`$RUN_DIR/recommendation.md`.
