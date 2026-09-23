# Bedrock Model Selection (mapping only — no pricing)

Distilled from the `gcp-to-aws` skill's Q16/Q17 tables and `ai-model-lifecycle.md`.
**Source:** `skills/gcp-to-aws/references/phases/clarify/clarify-ai.md` (Q16/Q17)

- `.../shared/ai-model-lifecycle.md`. Last aligned: 2026-06-30.

The tables below remain a **coarse compatibility hint** for old scoring-result consumers.
The authoritative deterministic implementation is the
`skills/agent-advisor/scripts/model_recommendation.py` orchestrator dispatching to per-provider
modules; each module consumes a dated capability catalog,
selects model and API path per workload, and emits compatibility deltas plus verification
status. Runtime scoring does not own model selection.

Model choice is **independent of runtime choice** — it never changes which runtime is selected.

## Joint model/path decision (per workload, per provider)

The per-workload `(model, api_path)` decision is deterministic and lives in code, not in this
file — it is dispatched by source provider so the path vocabulary and rules differ per provider:

- **Anthropic** → `scripts/anthropic_model_recommendation.py` + `references/models/anthropic-bedrock-2026-07-21.json`
  (paths: `mantle_messages`, `runtime_converse`, `runtime_invoke`).
- **OpenAI** → `scripts/openai_model_recommendation.py` + `references/models/openai-bedrock-2026-08-21.json`
  (paths: `mantle_openai_responses`, `runtime_converse`; Chat Completions reshapes to Responses).
- **Azure OpenAI / other** → generic `provider_module_pending` until a dedicated module exists.

Do not restate the per-provider path rules here — the dated catalogs and the engine are
authoritative (a table here would drift). The engine applies these provider-neutral principles:

- **Conflicts are not precedence.** When two hard requirements cannot share one path (e.g. API
  continuity plus runtime-only governance), emit `decision_required` with both tradeoff options
  and rerun after the user resolves the requirement — never silently let one side win.
- **A dated snapshot is not a permanent claim.** Catalog data is point-in-time — e.g. Sonnet 4.6
  was runtime-only in the `2026-06-24` snapshot, and six days later Sonnet 5 launched with full
  Mantle Messages support, changing the default recommendation. Every recommendation
  carries `region`, `catalog_verified_at`, and a required live `(model, path)` probe;
  recommendation acceptance does not prove account invocability.
- **Keep model identities separate.** Logical model identity, path-specific model ID, and the
  resolved invocation/CRIS ID are distinct fields. Paths differ in SDK, model-ID form, IAM
  action, structured-output mechanism, errors, and quotas.

## Priority baseline (Q16)

The `priority` answer (quality / balanced / speed / cost / unknown) sets the candidate
**ordering**, not a single model — the engine then applies hard capability and path filters.
The authoritative order is `anthropic_model_recommendation.py::_PRIORITY_ORDER` (per-provider catalogs
supply the actual models); it is not restated here to avoid drift.

## Specialized features (Q17)

The `model_features` answer collected in Clarify (legal values:
`tool_use | long_context | extended_thinking | rag | multimodal | image_generation | speech |
embedding | none | unknown`) feeds Model Recommend as a **hard capability filter**, not an
override — a candidate that lacks catalog evidence for a required feature fails closed
(`decision_required`), and a common feature such as tool use does not force a bigger model
when a cheaper candidate satisfies it.

Three of these are **separate capabilities, not text-model swaps** — they become their own
target contracts (`additional_targets` / a separate workload) instead of changing the text
model: `image_generation` (image model/service), `speech` (STT/TTS services), `embedding`
(a Bedrock embedding model). Detailed pricing/TCO → the `llm-to-bedrock` skill.

The selectable model pool is drift-guarded against the sibling skill's lifecycle registry at
`skills/gcp-to-aws/references/shared/ai-model-lifecycle.md` (a Legacy/EOL model entering the
pool fails CI; the check lives in `test_scoring.py` and skips gracefully when the sibling
skill is not present).
