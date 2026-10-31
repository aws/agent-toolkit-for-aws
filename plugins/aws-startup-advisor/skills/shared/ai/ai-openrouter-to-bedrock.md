# OpenRouter to Bedrock — Gateway Routing Guide

> Canonical OpenRouter (gateway) → Bedrock routing guide. Source-cloud agnostic:
> OpenRouter is a multi-provider router, not a model vendor, so the Bedrock target
> for any routed call depends on the **upstream** model OpenRouter forwarded to,
> never on which cloud hosted the application that called OpenRouter.
> Vendored into each consuming skill as
> `references/vendored/ai/ai-openrouter-to-bedrock.md` and kept byte-identical by
> `shared:check`; edit HERE, then run `shared:sync`.

**Applies to:** OpenRouter usage (`gateway_type: llm_router`) detected in applications hosted on any source cloud → Amazon Bedrock

This file is loaded by `design-ai.md` when a workload routes through OpenRouter — detected by `discover-app-code.md` (the OpenRouter transport) and, when the user consents, enriched by `discover-openrouter-api.md` (real per-model spend from the OpenRouter usage API). It explains how to turn OpenRouter's **per-upstream-model** usage into one coordinated Bedrock target, then defers the actual model selection to the per-provider shared guides.

**This guide maps the gateway, not the models.** OpenRouter is not itself a Bedrock target. Each upstream model behind OpenRouter maps to Bedrock through the provider guide for its family:

- Anthropic / Claude upstreams → `references/vendored/ai/ai-anthropic-to-bedrock.md`
- OpenAI / GPT upstreams → `references/vendored/ai/ai-openai-to-bedrock.md`
- Google / Gemini upstreams → `references/vendored/ai/ai-gemini-to-bedrock.md`

**Model lifecycle:** Before recommending any Bedrock model, check `references/vendored/ai/ai-model-lifecycle.md`. Do not recommend Legacy models as primary selections. Verify Bedrock pricing against `references/vendored/ai/bedrock-pricing-cache.md`.

---

## What OpenRouter Is (and Is Not)

OpenRouter is an **optional gateway** that sits in front of many model providers and exposes one OpenAI-compatible API. A single OpenRouter integration can carry traffic to Anthropic/Claude, Google/Gemini, OpenAI/GPT, and other providers **at the same time**. It is never an infrastructure source and never a direct model provider in its own right.

Two consequences drive the whole routing approach:

1. **One gateway, many upstreams, retained independently.** A workload behind OpenRouter may use several providers, several families, and several exact models concurrently. Do not collapse them to a single "OpenRouter" target and do not let one upstream overwrite another — each upstream association (provider → optional source service → family → exact model) is sized and mapped on its own.
2. **The migration target is per-upstream, not per-gateway.** Migrating off OpenRouter to Bedrock means replacing the gateway integration with direct Bedrock calls (or a Bedrock-fronted router of your own), where each previously-routed model lands on its mapped Bedrock target. There is no single "OpenRouter equivalent" on AWS.

---

## Reading OpenRouter Usage

OpenRouter identifies models with a **namespaced id** of the form `provider/model`, e.g. `anthropic/claude-sonnet-5`, `openai/gpt-4.1`, `google/gemini-2.5-pro`. Keep the id verbatim through Discover and Estimate.

- **Provider segment** (before the `/`) picks which per-provider guide above does the mapping.
- **Model segment** (after the `/`) picks the row within that guide.

When `discover-openrouter-api.md` captured real usage, each upstream model carries its own `requests`, token counts, and `monthly_cost_usd` over the window, plus a `cost_provenance` classification. These are the exact fields and enum values the producer writes — do not invent others, and do not derive a BYOK-vs-credits volume or token split from the enum (`llm-to-bedrock/SKILL.md` forbids it; the producer records no such ratio):

| `cost_provenance` | Meaning | How to read it |
| ----------------- | ------- | -------------- |
| `byok_passthrough` | Ran on your own upstream provider key through OpenRouter (bring-your-own-key) | You already hold a direct provider relationship; the Bedrock move removes OpenRouter's routing hop and the upstream key |
| `no_byok`          | Ran on OpenRouter credits (OpenRouter billed the upstream) | The captured `monthly_cost_usd` is the customer's actual OpenRouter bill for this model — it is the baseline, not a figure to re-derive from upstream list pricing |
| `mixed`            | Both within the window | Keep the single captured `monthly_cost_usd` as the baseline; the producer does not split it by funding source, so do not fabricate a split — disclose that the BYOK/credits breakdown is unavailable |
| `uncertain`        | Partially verified attribution | Carry the uncertainty forward; treat the captured spend as the baseline and label the provenance as not fully verified rather than discarding it |
| `unknown`          | Analytics unavailable (the `/analytics/query` capture failed or was skipped) | Report the cost comparison as provenance-unverified; do not assert a saving you cannot source |

**Cost baseline (defer to Estimate).** Whatever the provenance, the customer's **captured OpenRouter spend is the current-cost baseline** for the savings comparison — this guide does not override `estimate-ai.md` Part 1, which prefers measured `current_costs` / usage-profile dollars and explicitly does **not** fall back to a direct-provider list rate for the OpenRouter portion (OpenRouter has no source-side list-price row in `pricing-cache.md`). Provider list pricing from the per-provider guides may be shown only as a separately labeled reference, never substituted for the measured bill, and the existing matching-window / partial-window / overlap rules in `estimate-ai.md` apply unchanged.

Size the Bedrock target against the **real per-model volume** from the usage capture when present. Without it, fall back to the app-code signal (which models are called) and ask the user for volume rather than guessing.

---

## Routing Each Upstream to Bedrock

For every distinct upstream model behind the gateway:

1. **Select the provider guide** from the provider segment (`anthropic` / `openai` / `google`).
2. **Apply that guide's selection policy** to the exact model segment — same-model-on-Bedrock where it exists (OpenAI's Tier 0, Claude version-to-version), else the guide's cross-family / tier mapping. The provider guides own all pricing tables, region gates, and lifecycle checks; do not restate them here.
3. **Record the mapping per upstream, including the guide's selected endpoint** — the gateway's output is a set of `{ upstream_model → bedrock_target }` decisions, not one decision, and each decision carries the `migration_path`, endpoint/inference-profile ID, and credential/IAM requirement the provider guide chose. For GPT targets `ai-openai-to-bedrock.md` may select the Mantle Responses path (`mantle_openai_responses`) **or** the `bedrock-runtime` CRIS path (`runtime_openai_cris`, with a `us.`/`global.` profile) depending on the model and region gate — carry whichever it selected through to cutover, do not collapse every GPT target onto Mantle. Two Claude models behind the same gateway produce two rows, never one.

Preserve the distinction between a provider reached **through OpenRouter** and the **same provider reached directly**. A workload may use direct Anthropic SDK calls *and* Anthropic-via-OpenRouter at once; both map to Bedrock-hosted Claude, but they are different source integrations with different cutover work (a direct SDK swap vs. removing a gateway hop).

---

## Cutover Shape

Replacing OpenRouter with Bedrock is an integration change, not just a model change:

- **Transport — per the selected `migration_path`, not one default.** For Claude / Nova / Llama / Gemini-replacement targets, the OpenRouter client becomes the Bedrock Converse API. For GPT targets the transport follows the provider guide's selection: the Bedrock Mantle OpenAI-compatible endpoint when it chose `mantle_openai_responses`, or `bedrock-runtime` with the selected CRIS inference profile when it chose `runtime_openai_cris`. Do not force every GPT target onto Mantle — a runtime/CRIS selection sent to Mantle (or a Mantle-only model routed to runtime) is an incompatible cutover plan. A workload that used OpenRouter precisely for its one-API-many-models convenience may want a thin internal router over Bedrock to preserve that shape — see `references/vendored/ai/ai-migration-guardrails.md`.
- **Credentials.** Remove the OpenRouter key and any BYOK upstream keys; use IAM matched to each target's selected path — `bedrock:InvokeModel` for Converse and the `runtime_openai_cris` path, `bedrock-mantle:*` (e.g. `AmazonBedrockMantleInferenceAccess`) for the Mantle GPT path. The source-key retirement rules apply — do not plant the old gateway/provider keys in the target.
- **Routing policy.** If the app used OpenRouter's automatic model selection or fallback routing, this can now be implemented via AgentCore Gateway's model fallback routing (ordered chain of alternative destinations with trigger conditions and circuit breaker) rather than being dropped or reimplemented from scratch in the application.
- **Per-upstream validation.** Validate each mapped target independently (behavior, tool-calling, structured output) the way its provider guide prescribes; a gateway migration is only complete when every retained upstream passes.

---

## Not in Scope Here

- **Pricing tables and model rows** — owned by the per-provider guides and `references/vendored/ai/bedrock-pricing-cache.md`.
- **Usage capture mechanics, consent, and key handling** — owned by `discover-openrouter-api.md` in each consuming skill.
- **Treating OpenRouter as a provider or infrastructure source** — it is neither; it is a gateway whose only job here is to tell you which upstream models to map.
