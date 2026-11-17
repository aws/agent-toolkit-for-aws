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

The summary additionally carries, per model-bearing unit, the accepted `api_path`,
`invocation_model_id` and `mantle_selector` from `confirm.json` / `design.json`
(`model_decision` / `model_recommendation`), and on every `mantle_*` unit a `mantle_requirement`
object in the shape of `ai_constraints.mantle_requirements.value[]` /
`bedrock_models[].mantle_requirement` (`references/vendored/ai/schema-design-aws-ai.md`):
`{ "workload_id": "<unit_id>", "selector": <the unit's mantle_selector>, "source": ..., "evidence"?, "region"? }`.
`source` names how the advisor learned the selector — `"user"` when `model-recommendation-input.json`
carried an explicit `requirements.mantle_selector` (Model Recommend records one only when the
user confirmed the need) or when `in_region_processing` was derived from the user's
`data_residency: in_region_required` answer (then `region` = the run's `region`); `"detected"`
with `evidence` = the `file:line construct` behind the `detected` feature status when the OpenAI
module derived `web_search` from a detected Web Search tool; `"catalog"` with `evidence` = the
catalog file and row for `mantle_only_model_or_api`. A unit on any `runtime_*` path carries no
`mantle_requirement`; downstream Design writes the `endpoint_assumption` sentence for it.
Migration Plan Step 2 writes the same per-unit `mantle_selector` and `mantle_requirement` into
`migration-plan-injection.json` `units[]`, so the downstream engine reads them from the saved
artifact rather than from conversation context.

The summary also carries this translation table so that `gcp-to-aws` Design and
`llm-to-bedrock` write `migration_path` / `required_client_api` / `mantle_selector` /
`mantle_requirement` / `endpoint_assumption` without re-deciding the endpoint (the vocabulary is
`references/vendored/ai/bedrock-endpoint-policy.md`; the advisor contract is the recorded
requirement that Design Step 0.8 would otherwise read from Clarify's
`ai_constraints.mantle_requirements`):

- `runtime_openai_responses` → `migration_path: "runtime_openai_cris"`, `required_client_api: "responses"`
- `runtime_openai_chat` → `migration_path: "runtime_openai_cris"`, `required_client_api: "chat_completions"`
- `runtime_converse` on a proprietary GPT model (`openai.gpt-6*`, `openai.gpt-5.6-*`, `openai.gpt-5.5`, `openai.gpt-5.4`) → `migration_path: "runtime_openai_cris"`, `required_client_api: "converse"`
- `runtime_messages` → `migration_path: "runtime_messages"`, `required_client_api: "messages"`, `aws_model_id` = the advisor `invocation_model_id`
- `mantle_openai_responses` / `mantle_openai_chat` / `mantle_messages` → the same `migration_path`, `required_client_api` `responses` / `chat_completions` / `messages`, `bedrock_models[].mantle_selector` and `bedrock_models[].mantle_requirement` copied verbatim (an advisor Mantle contract without a selector or without a `mantle_requirement` is a mismatch — return to Model Recommend)
- any other path (`runtime_converse` on a Claude or open-weight model, `runtime_invoke`) → `migration_path` equal to the advisor `api_path`, no `mantle_selector`
- every `runtime_*` unit → the row records `bedrock_models[].endpoint_assumption` verbatim per `schema-design-aws-ai.md`, with the advisor `unit_id` as `<workload_id>`; no `mantle_requirement`

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
