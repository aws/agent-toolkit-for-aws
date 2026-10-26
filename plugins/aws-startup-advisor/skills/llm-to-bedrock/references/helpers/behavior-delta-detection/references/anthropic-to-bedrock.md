# Anthropic → Bedrock behavior deltas

Load for every Anthropic source, including same-model and resumed migrations.
Resolve the target first. `scripts/model_identity.py` compares actual identities;
Opus 4.8 → 5.5 is a model change and keeps comparative evaluation and adaptation.
An exact same-model result only removes model-version deltas. The API/path checks
below still apply. Do not assume all Claude versions accept the same controls.

For every recipe, inspect the hit's call site, request builder and downstream
consumer. Emit `behavior_deltas` using the parent helper's existing schema.
User-visible changes use `resolution_kind: ux_choice`, `option_set_id: fallback`
unless a recipe specifies `parameter_removed`. Backend-only implementation changes
use `resolution_kind: impl_path` without `option_set_id`. The rewriter applies
existing confirmed decisions; missing confirmation uses the safe-default/TODO
rule and remains an incomplete migration site.

## sampling-parameters-removed

For Opus 5.5, use the `sampling-parameters-removed` recipe in
`openai-to-bedrock.md`. It also applies to Anthropic source calls. Remove
`temperature`, `top_p` / `topP`, and `top_k` / `topK` from every request surface,
including framework defaults and `additionalModelRequestFields`. User-visible
controls use `parameter_removed`; backend constants use `impl_path`. Never
rescale the values or disable thinking to retain sampling.

```bash
rg -n 'temperature|top_p|topP|top_k|topK' <REPO>
```

## adaptive-thinking-required

For Opus 5.5, detect disabled thinking, manual thinking budgets and old effort
configuration. Use the target's adaptive thinking contract and verified effort
levels; do not carry `thinking.type: disabled`, manual `budget_tokens`, or
unsupported effort values into the generated request. Preserve output-token
headroom and validate it with the golden set. This does not authorize removing
a user-facing thinking/budget control without the existing `fallback` decision.

```bash
rg -n 'thinking|budget_tokens|effort|max_tokens|maxTokens' <REPO>
```

## prefill-and-forced-tool-choice

Opus 5.5 does not support assistant prefill or forced `any` / named `tool` choice
with its required thinking. Detect trailing assistant messages, forced tool
choices and schema guarantees built on them. For plain-text prefix intent,
use prompt instructions without claiming an exact prefix guarantee. For
structured results, read `openai-to-bedrock.md`'s `json-mode-rewrite` Pattern C:
auto tool choice or prompted JSON with application validation and bounded retries.
Preserve refusal/truncation handling and complete signed history. A hard native
schema guarantee requires an explicitly accepted alternative verified to support
it; do not silently restore Opus 4.8, disable thinking, or weaken the guarantee.

```bash
rg -n 'tool_choice|toolChoice|prefill|json_schema|response_format|role.*assistant' <REPO>
```

## typed-response-and-history

For every path, read visible text by block type, never by first-block position.
Native Messages uses `type: text`; Converse uses text-key blocks. Preserve the
complete assistant response, including reasoning/signatures and tool-use blocks,
when continuing tool history. Streaming must preserve complete signed blocks
using the SDK's accumulator while emitting only text deltas to text consumers.
Report refusal, truncation and missing text separately; an invocation success is
not proof of a complete answer. Use the rewriter's typed response templates.
These parsing changes are `impl_path` unless they change a user-visible contract.

```bash
rg -n 'content\[0\]|contentBlockDelta|delta\.text|stop_reason|stopReason' <REPO>
```

For other Claude targets, verify the selected version and API path before applying
any removal above. Keep supported controls and genuine same-model shortcuts.
