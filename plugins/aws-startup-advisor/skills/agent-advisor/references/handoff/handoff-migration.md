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
(`model_decision` / `model_recommendation`), plus this translation table so that `gcp-to-aws`
Design and `llm-to-bedrock` write `migration_path` / `required_client_api` / `mantle_selector`
without re-deciding the endpoint (the vocabulary is
`references/vendored/ai/bedrock-endpoint-policy.md`):

- `runtime_openai_responses` → `migration_path: "runtime_openai_cris"`, `required_client_api: "responses"`
- `runtime_openai_chat` → `migration_path: "runtime_openai_cris"`, `required_client_api: "chat_completions"`
- `runtime_converse` on a proprietary GPT model (`openai.gpt-6*`, `openai.gpt-5.6-*`, `openai.gpt-5.5`, `openai.gpt-5.4`) → `migration_path: "runtime_openai_cris"`, `required_client_api: "converse"`
- `runtime_messages` → `migration_path: "runtime_messages"`, `required_client_api: "messages"`, `aws_model_id` = the advisor `invocation_model_id`
- `mantle_openai_responses` / `mantle_openai_chat` / `mantle_messages` → the same `migration_path`, `required_client_api` `responses` / `chat_completions` / `messages`, and `bedrock_models[].mantle_selector` copied verbatim (an advisor Mantle contract without a selector is a mismatch — return to Model Recommend)
- any other path (`runtime_converse` on a Claude or open-weight model, `runtime_invoke`) → `migration_path` equal to the advisor `api_path`, no `mantle_selector`

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
