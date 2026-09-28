---
_phase: model-recommend
_title: "Model Recommend — Bedrock model and API path"
_requires_phase: clarify
_input:
  - answers.json
  - scoring-result.json
  - context-signals.json
_knowledge:
  - { file: references/models/anthropic-bedrock-2026-07-21.json }
  - { file: references/models/openai-bedrock-2026-08-21.json }
_assemble:
  _file: phases/model-recommend/model-recommend-assemble.md
_produces:
  - model-recommendation-input.json
  - model-recommendation.json
_advances_to: confirm
_preconditions:
  - _check_phase_completed: clarify
    _on_failure: _halt_and_inform
  - _check_file_exists: [answers.json, scoring-result.json]
    _on_failure: _unrecoverable
  - _validate_json: [answers.json, scoring-result.json]
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: [model-recommendation-input.json, model-recommendation.json]
    _on_failure: _halt_and_inform
  - _validate_json: [model-recommendation-input.json, model-recommendation.json]
    _on_failure: _halt_and_inform
  - _assert: "model-recommendation.json was written by model_recommendation.py; it has one workloads[unit_id] entry for every agent_session unit and every other model-bearing unit; every entry has decision_status == recommended before this phase completes; each entry carries exact structured source hints, source_analysis, feature_assessment, model_identity, primary_model, api_path, invocation_model_id, compatibility, architecture_impacts, additional_targets when the workload has separate-modality capabilities (embeddings/images/audio, each unresolved with a named service and null candidate), blocks, tuning, migration_deltas, evaluation, rollout, and provisional verification with region plus catalog_verified_at; runtime-scoring output did not independently replace any selected model"
    _on_failure: _halt_and_inform
  - _assert: "every feature_status entry marked `detected` in model-recommendation-input.json has a named source location behind it (Step 3's evidence rule); a surface that was scanned and not found is `absent`, a surface whose source path could not be read is `unknown`, and no feature was marked `detected` because the migration implies it"
    _on_failure: _halt_and_inform
---

# Phase: Model Recommend — Bedrock model and API path

This phase is the model-selection authority. Runtime scoring remains in Clarify, but it MUST
NOT decide the final model or Bedrock API path.

## Step 1 — Build the per-workload source inventory

Read `$RUN_DIR/answers.json` and, when present, `$RUN_DIR/context-signals.json`. Create one
input row for every `agent_session` unit and every other unit with an LLM call. Do not create a
row for a model-less compute unit.

For each row, preserve machine-readable source facts:

- `provider`: `anthropic | openai | azure_openai | google_genai | bedrock | none | unknown`
- `model_ids[]`: exact strings found in code or stated by the user; do not normalize them
- `sdk`: exact SDK/package name when known
- `api_surface`: e.g. `messages`, `chat_completions`, `responses`, `converse`
- `source_paths[]`: the files containing the provider call sites — a file belongs here only if it
  invokes the SDK/API. Tool definitions, capability manifests, and config that merely _evidences_ a
  feature are not call sites; cite those where the feature is recorded instead. It must cover the
  whole scan: if Step 3 marks a feature `detected` on the strength of a call in some file, that file
  is a call site and belongs here — a feature cited from a path the list omits is an inconsistent
  scan. Sort the list, so two scans of the same repository produce the same array.

Discovery evidence is a hint, not an immutable fact. The downstream executor MUST re-scan code
and may override a stale hint with a logged mismatch; it MUST NOT silently replace the
advisor-confirmed target model/path.

## Step 2 — Resolve model/path requirements

Map existing answers into each row's `requirements`:

- `model_priority` → `priority`
- `model_features` plus agent tool use → `critical_features[]`
- target region → top-level `region`; use `unknown` when no concrete region was given

For Anthropic sources, ask one batched clarification only for requirements not established by
code or prior answers:

- preserve the first-party Messages API?
- require newest Anthropic beta features?
- require Bedrock Guardrails, invocation logging, or CloudWatch integration?
- require a shared multi-model Converse surface?
- require a provider-native Bedrock request body?
- minimum context window and expected output-token ceiling?
- use thinking?
- allow Global CRIS, or require a geography-scoped CRIS profile?

For OpenAI and Azure OpenAI sources, ask instead for the provider-neutral requirements (never
reuse the Anthropic `preserve_messages_api` switch):

- `api_continuity`: `required | preferred | not_required | unknown` — must the OpenAI SDK and
  API surface be preserved?
- require Bedrock Guardrails, invocation logging, or a shared multi-model Converse surface?
- does the code use `n` (multiple candidates), hosted state (Assistants/Threads,
  `previous_response_id`), hosted web/file search, Files API, or vector stores?
- minimum context window and expected output-token ceiling?
- allow Global CRIS or require a geography-scoped profile (runtime Converse only)?

OpenAI is handled by a dedicated provider module (`openai-bedrock-2026-08-21.json` catalog):
GPT-5.x on Mantle is Responses-only, so a Chat Completions source is reshaped, not routed to
`mantle_openai_chat`. GPT-5.6 sources additionally carry a SAME-MODEL `runtime_converse`
candidate via CRIS ids (verified 2026-08-21) — governance requirements no longer force a
family switch for them, while GPT-5.5/5.4 remain mantle-only. Azure OpenAI remains an
explicit `provider_module_pending` generic result.

**OpenRouter/LiteLLM-sourced OpenAI models still use the OpenAI module.** Discover records the
underlying `provider` (e.g. `openai`) even when the calls transit a gateway — see `discover.md`'s
gateway-detection rule. Do not treat a gateway-routed source as `unknown` or route it to the
generic branch: the model itself, and therefore the Mantle/Converse recommendation, is unaffected
by the gateway. What changes is `api_continuity`: a gateway-routed source is not, by construction,
calling the OpenAI SDK directly, so its actual migration effort is closer to `preferred` than
`required` — ask this explicitly rather than assuming `required` from the SDK detection default,
and note in `[TUNE]`/rationale that landing on Mantle from OpenRouter means a real base-URL,
credential, and model-ID-format change, not the zero-code-change claim that applies to a direct
OpenAI SDK caller.

Do not ask users to choose an API path by name unless they already expressed a preference.
The deterministic engine ranks `(model, api_path)` candidates together after filtering hard
constraints. If an explicit preference exists, record `preferred_api_path`. Record
`min_context_tokens`, `expected_output_tokens`, `thinking_enabled`, `data_residency`,
`cris_geography`, and an explicit `inference_profile_id` when known. Do not manufacture a
Global or geography prefix when residency is unresolved.

## Step 3 — Record migration-sensitive features

For Anthropic source paths, scan for migration-sensitive features:

- `budget_tokens`, `sampling_parameters`, `assistant_prefill`
- `refusal_handling`, `tokenizer_rebaseline`, `max_tokens_headroom`
- `structured_output`, `prompt_caching`
- `citations`, `streaming`, `tool_use`, `vision`
- `server_tools`, `files_api`, `url_sources`, `message_batches`
- `models_api`, `fallbacks`, `conversation_state`, `agent_infra`

For OpenAI source paths, scan instead for OpenAI feature codes:

- `tool_or_function_calling`, `structured_output_json`, `streaming`, `image_input_vision`
- `reasoning`, `sampling_params`, `max_tokens`, `multiple_candidates_n`
- `web_search`, `file_search_retrieval`, `files_api`, `vector_stores`, `assistants_threads`
- `audio_modality`, `embeddings`, `images`, `conversation_state`

Put observed features in `detected_features[]`. Also write `feature_status` entries as
`detected | absent | unknown`. For a Claude version hop, inspect every source path and mark each
version-breaking surface explicitly; absence from `detected_features[]` alone means `unknown`,
not proved absent.

**Each status must be earned by evidence, and the evidence is a source location.**

- `detected` — you can name the file and line where the feature is used (a parameter, a call, a
  request field, a declared capability). Cite that location in the phase's chat output for every
  feature you mark `detected`. A feature you believe _ought_ to be there, or that the migration
  will imply anyway, is not `detected`: `tokenizer_rebaseline`, for instance, is a consequence of
  the version hop and belongs in `migration_deltas`, not in the scan, unless the source actually
  counts tokens.
- `absent` — you read every source path and the surface is not used. This is the correct status
  for a feature you cannot cite; do not round a plausible guess up to `detected`.
- `unknown` — a source path could not be read, so the surface was never scanned. Say which path.

The scan feeds `blocks`, `tuning`, and `migration_deltas` counts, so a false `detected` inflates
the findings and two runs over the same repository then disagree. If the evidence is not citable,
the status is `absent`. An incomplete version scan produces `version_scan_incomplete` and the phase
must not present the migration as ready. For OpenAI, the module distinguishes the platform axis
(OpenAI hosting → Bedrock) from the model-generation axis (GPT-4.x/o-series → GPT-5.x reasoning);
opaque deployment names stay `unknown` and are never inferred to a family.

## Step 4 — Write and validate model-recommendation-input.json

Write `$RUN_DIR/model-recommendation-input.json` with this shape:

```json
{
  "schema_version": 2,
  "region": "us-east-1",
  "primary_unit": "support-agent",
  "workloads": [
    {
      "workload_id": "support-agent",
      "source": {
        "provider": "anthropic",
        "model_ids": ["claude-3-7-sonnet-latest"],
        "sdk": "anthropic",
        "api_surface": "messages",
        "source_paths": ["src/agent.py"]
      },
      "requirements": {
        "priority": "balanced",
        "critical_features": ["tool_use"],
        "preserve_messages_api": true,
        "governance": [],
        "min_context_tokens": 200000,
        "expected_output_tokens": 16000,
        "thinking_enabled": true,
        "data_residency": "geo_required",
        "cris_geography": "us"
      },
      "detected_features": ["budget_tokens", "assistant_prefill"],
      "feature_status": {
        "budget_tokens": "detected",
        "assistant_prefill": "detected",
        "sampling_parameters": "absent",
        "refusal_handling": "unknown"
      }
    }
  ]
}
```

Validate it against `scripts/schemas/model-recommendation-input.json`. On validation failure,
fix the input; do not bypass the schema.

## Step 5 — Run the deterministic recommendation engine

Resolve `$SCRIPTS` using the same plugin-root fallback as Clarify, then run:

```bash
uv run python "$SCRIPTS/model_recommendation.py" \
  "$RUN_DIR/model-recommendation-input.json" \
  --output "$RUN_DIR/model-recommendation.json"
```

It prints `RESULT=ok WORKLOADS=<n> SCHEMA_VALIDATED=<yes|no>`. `SCHEMA_VALIDATED=no` means the host
has no `jsonschema` (a bare `python3` invocation without `uv`): the recommendation is still
deterministic, but nothing machine-checked the input or the output, so read both against
`scripts/schemas/` yourself before continuing.

The engine output is authoritative for the joint model/path ranking. Do not hand-edit its
recommendation. Keep these identities separate:

- `model_identity.model_key`: logical catalog identity
- `model_identity.path_model_id` / `primary_model`: the ID form for the selected path
- `invocation_model_id`: the resolved account-callable ID; runtime may leave this null until a
  CRIS profile is resolved

Every capability claim remains `probe_status: not_run` and
`availability_claim: provisional` until the exact `(invocation_model_id, api_path)` pair is
invoked in the target account and region.

OpenAI sources use the dedicated OpenAI provider module (`provider_module: openai`) and its
dated catalog. Azure OpenAI and Google sources remain the generic provisional branch and carry
`provider_module_pending` in `[BLOCKS]`; do not present those as provider-complete. All modules
share one artifact shape, so downstream phases consume every provider identically.

## Step 6 — Resolve decision_required before advancing

If any workload has `decision_status: decision_required`, present its `decision_options` and
tradeoffs. Ask the user to resolve the conflicting requirement, update
`model-recommendation-input.json`, and rerun the deterministic engine. Do not pick an option,
edit the output, or mark this phase completed while any workload remains unresolved.

## Step 7 — Optionally probe the selected path

Offer a live target-account probe after all workloads are `recommended`. This is optional and
separate from recommendation acceptance because it uses AWS credentials and invokes a billable
model. Run it only with explicit approval:

```bash
uv run --with boto3 --with anthropic python "$SCRIPTS/verify_model_path.py" \
  "$RUN_DIR/model-recommendation.json" \
  --output "$RUN_DIR/model-verification.json"
```

**Each API path needs its own client library.** The line above covers the Anthropic and runtime
paths. A workload on `mantle_openai_responses` additionally needs `--with openai --with
aws-bedrock-token-generator`; without them that workload comes back `failed` with a
`RuntimeError` naming the missing package, while every other workload still probes normally. So a
`failed` status here can mean "the dependency was absent", not "the model is unavailable" — read
the error type before treating it as a capability finding.

The verifier must call only the recorded `invocation_model_id`; it never substitutes another
model. Runtime recommendations with an unresolved CRIS profile produce `needs_resolution`.
Keep `model-verification.json` when generated and show its per-workload status. A failed probe
does not change the accepted recommendation; it blocks runnable POC claims until resolved.

## Step 8 — Present the recommendation and advance

For each workload, show the primary model, API path, resolved invocation ID or CRIS TODO,
compatibility groups, architecture impacts, any `additional_targets` (separate-modality targets
such as embeddings/images/audio, shown as unresolved with their named service — never as a
runnable model ID), path rationale, `[BLOCKS]`, `[TUNE]`, evaluation mode, rollout gate, and
verification status. Do not resolve blockers in chat by silently changing the output. Confirm
handles user acceptance or requested requirement changes.

Set `phases["model-recommend"]` = completed and leave `phases.confirm` = pending.
