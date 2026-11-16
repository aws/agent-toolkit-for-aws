---
_phase: model-recommend
_title: "Model Recommend — Bedrock model and API path"
_requires_phase: clarify
_input:
  - answers.json
  - scoring-result.json
  - context-signals.json
_knowledge:
  - { file: references/vendored/ai/models/anthropic-bedrock.json }
  - { file: references/vendored/ai/models/openai-bedrock.json }
  - { file: references/vendored/ai/bedrock-endpoint-policy.md }
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
- a verified Mantle-only need? — background inference, server-side / pre-configured tools
  including Web Search, customer Projects or Workspaces, a model or API listed on
  `bedrock-mantle` only, or strict in-Region processing where `bedrock-runtime` offers only a
  CRIS profile: record `mantle_selector` with the exact value from
  `references/vendored/ai/bedrock-endpoint-policy.md`; otherwise leave it absent — preserving
  the Responses, Chat Completions or Messages API is not a selector
- allow Global CRIS, require a geography-scoped profile, or require strict in-Region processing
  (`data_residency: in_region_required`)?

For OpenAI and Azure OpenAI sources, ask instead for the provider-neutral requirements (never
reuse the Anthropic `preserve_messages_api` switch):

- `api_continuity`: `required | preferred | not_required | unknown` — must the OpenAI SDK and
  API surface be preserved?
- require Bedrock Guardrails, invocation logging, or a shared multi-model Converse surface?
- does the code use `n` (multiple candidates), hosted state (Assistants/Threads,
  `previous_response_id`), hosted web/file search, Files API, or vector stores?
- a verified Mantle-only need? — background inference, server-side / pre-configured tools
  including Web Search, customer Projects or Workspaces, a model or API listed on
  `bedrock-mantle` only, or strict in-Region processing where `bedrock-runtime` offers only a
  CRIS profile: record `mantle_selector` with the exact value from
  `references/vendored/ai/bedrock-endpoint-policy.md`; otherwise leave it absent — preserving
  the Responses, Chat Completions or Messages API is not a selector
- minimum context window and expected output-token ceiling?
- allow Global CRIS, require a geography-scoped profile, or require strict in-Region processing
  (`data_residency: in_region_required`)? (any bedrock-runtime path)

OpenAI is handled by a dedicated provider module (`openai-bedrock.json` catalog). The module
defaults to the bedrock-runtime path that preserves the source API — `runtime_openai_responses`
for a Responses source, `runtime_openai_chat` for a Chat Completions source — on the exact source
model; GPT-5.6, GPT-5.5, GPT-5.4 and GPT-6 identities are all recognized and evaluated against
their same-model catalog entry before capability/numeric fallbacks. A `mantle_openai_*` path is
selected only with a `mantle_selector`: explicit, or derived from a detected `web_search` tool
(the built-in Web Search tool is served on `bedrock-mantle` only) or from
`data_residency: in_region_required` on a runtime model that is CRIS-only in the region. Guardrails
select `runtime_converse` (same model first, Claude tier as fallback) only when the source
model's card lists Guardrails as Converse-only — GPT-5.6 Sol / Terra / Luna, GPT-5.5, GPT-5.4 and
GPT-6 Astra. GPT-6 Sol and GPT-6 Luna keep `runtime_openai_responses` / `runtime_openai_chat`, and
GPT-6.1 Sol keeps `runtime_openai_chat`, because their cards list Guardrails on those APIs (the
catalog row flag `guardrails_supported`; cards read 2026-11-08:
`https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-sol.html`,
`model-card-openai-gpt-6-luna.html`, `model-card-openai-gpt-6-1-sol.html`). A GPT-6.1 Sol
Responses source with Guardrails is a `decision_required` because its card excludes Responses.
The catalog row flag `prompt_caching_supported` carries the per-API prompt-caching scope the same way
(GPT-5.5 / GPT-5.4: implicit caching on the bedrock-runtime Responses API only, none on
`bedrock-mantle`; GPT-5.6 Sol / Terra / Luna: every runtime API and Mantle Responses only; GPT-6 Sol /
Luna and GPT-6.1 Sol: every API on both endpoints; cards read 2026-11-09:
`https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-55.html`,
`model-card-openai-gpt-54.html`). A required `prompt_caching` is checked on the selected API row for
every candidate: a GPT-5.5 Chat Completions source with required continuity and critical
`prompt_caching` lands on the same-family candidate whose Chat row caches (GPT-5.6) with the reason
in `rationale`, or — when no candidate's row caches — is an `unverified_capability` decision that
names the Chat-versus-Responses continuity trade-off. It is never a clean `runtime_openai_chat`
recommendation with empty compatibility buckets. A
shared multi-model Converse surface always selects `runtime_converse`. Required API continuity
plus Converse-only governance is a `decision_required` between two bedrock-runtime options
(`runtime_openai_<api>` and `runtime_converse`); Mantle is never offered without a selector.
Invocation logging pins `bedrock-runtime` (model invocation logging captures only that endpoint,
including its OpenAI-compatible APIs:
`https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html`, read
2026-11-08), so logging plus any `mantle_selector` — explicit, or `in_region_processing` derived
from `in_region_required` — is a `decision_required` between the Mantle option (carrying the
selector) and the runtime option that keeps the source API. CloudWatch alone never changes the
path: `bedrock-runtime` publishes `AWS/Bedrock` metrics and `bedrock-mantle` publishes
`AWS/BedrockMantle` (`https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-mantle-metrics.html`,
read 2026-11-08). An application inference profile ARN in `inference_profile_id` requires
Converse — the bedrock-runtime Responses and Chat Completions APIs reject it with HTTP 400
(`https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html`, read
2026-11-08) — so with required continuity it is a `decision_required` whose OpenAI-API option
carries no invocation id; system, Geo and Global profiles are unaffected. Every selector is
validated against the final provider and API before a path is chosen, and a retained
`critical_features` entry is checked the same way even when another selector is the primary
reason. `background_inference`, `web_search`, and `server_side_tools` are Responses API features
on `bedrock-mantle`
(`https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html`,
`https://docs.aws.amazon.com/bedrock/latest/userguide/web-search.html`,
`https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-server-side.html`, read 2026-11-09),
so a Chat Completions path that would carry one of them is a `decision_required`
(`selector_api_incompatible`: `mantle_openai_responses` versus `runtime_openai_chat` without it)
unless `api_continuity: not_required` allows the reshape; `mantle_openai_chat` is never recorded
or offered for a Responses-only feature. Client function tools stay on Chat Completions. A selector whose
provider does not match the workload is a `selector_provider_mismatch` decision whose options
both stay on `bedrock-runtime`: `workspaces` (`anthropic-workspace-id`,
`https://docs.aws.amazon.com/bedrock/latest/userguide/workspaces.html`) on an OpenAI SDK
workload, and `projects` (`OpenAI-Project`,
`https://docs.aws.amazon.com/bedrock/latest/userguide/projects.html`) on an Anthropic SDK
workload (read 2026-11-09). An Anthropic Messages source with `background_inference` is likewise
a `selector_api_incompatible` decision between `runtime_messages` and the runtime governance path
— the Messages API has no background mode and the Anthropic module has no Responses route. The
`server_side_tools` / `web_search` selectors skip Mantle rows whose card lists server-side system
tools as unsupported (`server_side_tools_supported: false` — GPT-6.1 Sol) and fall to the next
same-family model with a fallback rationale; the selector is never dropped. An explicit runtime
`preferred_api_path` plus any selector (explicit or derived) is a `preferred_api_path_conflict`
decision between the Mantle option and the preferred runtime option. A recommended `runtime_*`
record never carries a selector.
Fallbacks walk same-family candidates first, newest version first, so a GPT-6 Chat Completions
source never falls to GPT-5.4 while Astra or GPT-5.5 is available in the region. Governance
selects the exact same GPT model through `runtime_converse` only when the requested Global or
geography-scoped CRIS profile is cataloged for that model and source region; an unsupported
profile falls through to an eligible documented runtime candidate or remains an explicit
decision. Every selected path remains provisional until it is probed in the target account and
region. Azure OpenAI remains an explicit `provider_module_pending` generic result.

For Astra, preserve a compatible explicit API preference before the source default.
Keep Astra selected and require a decision when its path, region or feature evidence
cannot satisfy the request; do not silently substitute another model. Astra's JSON Schema output
on `bedrock-runtime` applies to non-streaming calls on Chat Completions, Responses and Converse
(`https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-astra.html`, read
2026-11-08), so `structured_output_json` plus `streaming` on any of those runtime paths is a
`structured_output_streaming_unverified` decision.

The Anthropic module applies the same governance rules to its paths: invocation logging plus a
`mantle_selector` (explicit, or derived `in_region_processing`) is a `decision_required` between
`mantle_messages` and the runtime path that keeps the source API (`runtime_messages` for a
Messages source); CloudWatch alone never changes the path; an explicit
`preferred_api_path: runtime_messages` plus Guardrails or a shared multi-model Converse surface is
a `decision_required` between `runtime_messages` and `runtime_converse`; an explicit runtime
preference plus any selector is a `decision_required` between `mantle_messages` and the preferred
path. The conflict name (`mantle_selector_vs_invocation_logging`,
`in_region_processing_vs_invocation_logging`, `preferred_path_vs_mantle_selector`,
`preferred_path_vs_converse`, `in_region_processing_vs_preferred_api_path`) appears in the
`model_path_decision_required` message.

**OpenRouter/LiteLLM-sourced OpenAI models still use the OpenAI module.** Discover records the
underlying `provider` (e.g. `openai`) even when the calls transit a gateway — see `discover.md`'s
gateway-detection rule. Do not treat a gateway-routed source as `unknown` or route it to the
generic branch: the model itself, and therefore the model/path recommendation, is unaffected
by the gateway. What changes is `api_continuity`: a gateway-routed source is not, by construction,
calling the OpenAI SDK directly, so its actual migration effort is closer to `preferred` than
`required` — ask this explicitly rather than assuming `required` from the SDK detection default,
and note in `[TUNE]`/rationale that landing on bedrock-runtime `/openai/v1` (or Mantle) from
OpenRouter means a real base-URL, credential, and model-ID-format change, not the
zero-code-change claim that applies to a direct OpenAI SDK caller.

Do not ask users to choose an API path by name unless they already expressed a preference.
The deterministic engine ranks `(model, api_path)` candidates together after filtering hard
constraints. If an explicit preference exists, record `preferred_api_path`. Record
`min_context_tokens`, `expected_output_tokens`, `thinking_enabled`, `data_residency`,
`cris_geography`, and an explicit `inference_profile_id` when known. Record `mantle_selector`
only when the user confirmed the need. Do not manufacture a Global or geography prefix when
residency is unresolved; with `in_region_required` the runtime invocation id stays null unless
an in-Region model form or an explicit profile applies.

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
- `reasoning`, `sampling_params`, `max_tokens`, `multiple_candidates_n`, `prompt_caching`
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
        "model_ids": ["claude-sonnet-5"],
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

## Step 6 — Resolve decision_required and blocked before advancing

If any workload has `decision_status: decision_required`, present its `decision_options` and
tradeoffs. Ask the user to resolve the conflicting requirement, update
`model-recommendation-input.json`, and rerun the deterministic engine. Do not pick an option,
edit the output, or mark this phase completed while any workload remains unresolved.

If any workload has `decision_status: blocked`, there is no automatic target and fewer than two
real options. Causes include a `reference_only` source model or conflict side in the catalog, and
other no-target results such as an incomplete feature scan. Present its `[BLOCKS]` findings and any
remaining option, apply each finding's own remediation (for example a feature rescan, a
requirement change, or marking a verified model `selectable`), then rerun. Do not invent an option
or treat a lone remaining option as the answer.

## Step 7 — Optionally probe the selected path

Offer a live target-account probe after all workloads are `recommended`. This is optional and
separate from recommendation acceptance because it uses AWS credentials and invokes a billable
model. Run it only with explicit approval:

```bash
uv run --with boto3 --with anthropic python "$SCRIPTS/verify_model_path.py" \
  "$RUN_DIR/model-recommendation.json" \
  --output "$RUN_DIR/model-verification.json"
```

**Each API path needs its own client library.** The line above covers `mantle_messages`,
`runtime_converse` and `runtime_invoke`. A workload on `runtime_messages` additionally needs
`--with anthropic --with aws-bedrock-token-generator` (the bearer token for the
`bedrock-runtime.{region}.amazonaws.com/anthropic` base URL). A workload on
`runtime_openai_responses`, `runtime_openai_chat`, `mantle_openai_responses` or
`mantle_openai_chat` additionally needs
`--with openai --with aws-bedrock-token-generator`; without them that workload comes back
`failed` with a `RuntimeError` naming the missing package, while every other workload still
probes normally. So a `failed` status here can mean "the dependency was absent", not "the model
is unavailable" — read the error type before treating it as a capability finding.

The verifier must call only the recorded `invocation_model_id`; it never substitutes another
model. Runtime recommendations with an unresolved CRIS profile produce `needs_resolution`.
Keep `model-verification.json` when generated and show its per-workload status. A failed probe
does not change the accepted recommendation; it blocks runnable POC claims until resolved.

When this engine rewrites a recommendation, it removes the sibling `model-verification.json`
if any workload's model, API, invocation ID, region, allowed profile set or allowed in-region
model ARN set changed. An unchanged
invocation contract retains its verification. After invalidation, treat verification as
`not_run`; do not restore a passed result from an older design or report.

For any application-profile ARN (every model and region — Opus 5.5 under US residency and a
Canada-only Haiku 5.5 profile alike), the verifier first reads `GetInferenceProfile`
for that ARN and the recommendation's `verification.allowed_inference_profiles`. It requires
active destinations matching the selected model and an allowed regional profile before
invoking the original ARN; a passed probe alone never establishes residency. An explicit
`inference_profile_id` is also validated for model identity, ARN partition/region, and the
required geography before any candidate is accepted, including models without a profile matrix;
an invalid pin blocks with `inference_profile_unresolved` rather than passing through. The caller needs `bedrock:GetInferenceProfile` for these metadata
reads; a failed or inconclusive check prevents inference and does not establish access.
For London in-region profiles, `verification.allowed_in_region_model_arns` carries the
exact permitted foundation-model destination. An ACTIVE application profile with only that
destination is also valid; a different model, region or additional destination is not accepted
by this rule. Cross-region application profiles still need the reference-profile comparison.

## Step 8 — Present the recommendation and advance

For each workload, show the primary model, API path with its `mantle_selector` (`null` on every
bedrock-runtime path), resolved invocation ID or CRIS TODO, compatibility groups, architecture impacts, any `additional_targets` (separate-modality targets
such as embeddings/images/audio, shown as unresolved with their named service — never as a
runnable model ID), path rationale, `[BLOCKS]`, `[TUNE]`, evaluation mode, rollout gate, and
verification status. Do not resolve blockers in chat by silently changing the output. Confirm
handles user acceptance or requested requirement changes.

Set `phases["model-recommend"]` = completed and leave `phases.confirm` = pending.
