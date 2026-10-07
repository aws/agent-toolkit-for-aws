# AI Pricing Cache (Bedrock + source-provider)

**Last updated:** 2026-10-05 (re-verified via the AWS Pricing MCP server, aws.amazon.com/bedrock/pricing, and the Bedrock model cards' Geo/Global inference ID tables — Claude Sonnet 5 $2/$10 (Global/base) / $2.20/$11 (Geo, `us.`-prefixed), Opus 4.8 $5/$25 (Global/base) / $5.50/$27.50 (Geo), Sonnet 4.6 $3/$15 (Global/base) / $3.30/$16.50 (Geo), Haiku 4.5 $1/$5 (Global/base) / $1.10/$5.50 (Geo), Opus 4.6 $5/$25, Opus 4.1 legacy $15/$75, Claude Fable 5 $10/$50, Llama 4 Maverick/Scout, Llama 3.3 70B, Nova 2 Lite/Pro/Lite/Micro, Mistral Large 3, DeepSeek-R1, gpt-oss-20b/120b, GPT-5.6/5.5/5.4 family, and the OpenAI/Azure OpenAI source-side table all confirmed unchanged; this refresh corrects the Geo-vs-Global pricing gap for the four Anthropic models that require a cross-Region inference profile — see the Geo vs. Global note below)
**Opus 5.5 evidence dates:** 2026-09-24 for model/profile rates; 2026-10-03 for London in-region support and pricing.
**Region:** us-east-1
**Currency:** USD
**Accuracy:** ±15-25% for AI models (sourced from public pricing pages)

> **Scope: AI/Bedrock only.** This file prices Bedrock model inference and the source-provider
> baselines used for migration ROI. It does NOT price infrastructure — azure-to-aws prices
> EC2/RDS/S3/ElastiCache/etc. from `references/vendored/pricing/aws-infra-pricing.json` (the
> file the `pricing-coverage` gate enforces). Two infra pricing sources would be a drift trap,
> so this cache deliberately carries no infra rows. `estimate-ai.md` reads this file for AI
> cost; `estimate-infra.md` reads the infra JSON.
>
> Prices vary by region and change over time; use for estimation only. There is no live pricing
> lookup — on a cache miss apply `pricing-fallback.md` (`estimated` or `unavailable`).
> **Staleness warning:** if today is more than 30 days after **Last updated**, treat AI model
> prices as potentially stale; set `pricing_source: "cached_stale"` in `estimation-ai.json` and
> note it. Verify against [aws.amazon.com/bedrock/pricing](https://aws.amazon.com/bedrock/pricing/).

---

## Bedrock Models (On-Demand)

**Anthropic Claude (Standard on-demand)** figures match **US East (N. Virginia)** on
[Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) as of cache refresh.
**Recommend defaults (new migrations):** Claude Sonnet 5 (flagship), Claude Opus 5.5 (demanding
reasoning), Claude Haiku 4.5 (cost/speed). Do not default to Claude Fable 5 (frontier). Long-context
SKUs do not all use the same multiplier; confirm batch/cache and cross-region rows per model on
that page. See `references/vendored/ai/ai-model-lifecycle.md` for lifecycle detail — **do not
recommend Legacy/excluded models for new migrations.**

**Opus selection policy:** Recommend Opus 5.5 for new Opus migration targets. Opus 4.8
rates are retained for existing deployments only; do not recommend it as a new target
or automatic fallback. The separately documented Opus 4.6 Batch exception remains.

**Opus 5.5 rates verified: 2026-09-24.** Source: AWS Price List API, service
`AmazonBedrockFoundationModels`, filter `servicename = Claude Opus 5.5 (Amazon Bedrock Edition)`
and the source `regionCode`; see [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/).
The Opus 5.5 rows below are Standard on-demand, per 1M tokens: Global **$4/$20**;
commercial Geo and Mantle in-region **$4.40/$22**; GovCloud **$4.80/$24**.
For example, us-east-1 input/output SKUs are `KVG5FBPDJPKF5TJY` / `MWH4TD2A4D5CEBAP`
(Global) and `J9QFZT8WAQABG9ZX` / `FCRGDQ596BG7EQKH` (Geo/Mantle).
The [model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html) lists Active lifecycle, 1M context, 128K output,
and **no Batch**. Runtime uses `us.`/`eu.`/`au.`/`jp.` Geo or `global.` CRIS,
or the bare ID in `eu-west-2` (in-region model-card and pricing verification: 2026-10-03);
Global is not available in GovCloud. Mantle uses the bare ID only in `us-east-1`,
`ap-southeast-4`, and `us-gov-west-1`. Choose the price row by region and inference
profile; a generic model name alone is insufficient. Other cache rows retain the
full-cache date at the top of this file.

> **Geo vs. Global inference pricing.** Sonnet 5, Opus 4.8, Sonnet 4.6, and Haiku 4.5 cannot be
> invoked on-demand with their bare model ID in **US regions** on `bedrock-runtime` — they require
> a cross-Region inference profile ID there (see
> `references/helpers/bedrock-known-fixes/references/bedrock-inference-profile-model-id.md`).
> This is per-model and per-region, not universal: Haiku 4.5's model card states the bare ID is
> never supported for on-demand throughput on any `bedrock-runtime` region. Sonnet 5 and Sonnet
> 4.6, by contrast, DO support true in-Region (bare-ID) invocation — but only from **eu-west-2
> (London)**; every US region (and every other region checked) shows In-Region unsupported for
> both models. Opus 4.8 behaves like Haiku 4.5: no in-Region support anywhere. Confirm the
> target model's actual In-Region/Geo/Global support table on its model card before assuming
> either outcome.
>
> The **Geo** profile (`us.`/`eu.`/`au.`/`jp.`/`in.` prefix) carries a ~10% price premium over
> **Global** (`global.` prefix); AWS documents Global cross-Region inference as saving
> "approximately 10%... compared to geographic cross-Region inference." The quick-reference
> table's bare-id rows below are the **Global/base** rate; for a **Geo** (`us.`-prefixed, the
> common choice for US-only data residency) deployment, multiply input/output by 1.10 — e.g.
> Sonnet 5 Geo is $2.20/$11.00, Opus 4.8 Geo is $5.50/$27.50, Sonnet 4.6 Geo is $3.30/$16.50,
> Haiku 4.5 Geo is $1.10/$5.50. `bedrock_pricing.py`'s `STATIC_FALLBACK` table keys the `us.`
> id to the Geo rate and the bare id to the Global/base rate — read from that table, not this
> one, when a migration plan pins a specific inference profile.
> The Opus 5.5 rows already name their Global, Geo, Mantle, London or GovCloud rate.
> Use the listed rate for that path; do not apply another 1.10 multiplier.

### Multi-provider quick reference (per 1M tokens)

| Model                             | Model ID                                 | Provider  | Input $/1M | Output $/1M | Context | Tier      | Status                                                                                         |
| --------------------------------- | ---------------------------------------- | --------- | ---------- | ----------- | ------- | --------- | ---------------------------------------------------------------------------------------------- |
| Claude Fable 5                    | anthropic.claude-fable-5                 | Anthropic | 10.00      | 50.00       | 1M      | frontier  | active                                                                                         |
| Claude Sonnet 5                   | anthropic.claude-sonnet-5                | Anthropic | 2.00       | 10.00       | 1M      | flagship  | active ($2/$10 — launch rate became standard on Sep 1, 2026; the $3/$15 step-up was cancelled) |
| Claude Opus 5.5 (Global)          | global.anthropic.claude-opus-5-5         | Anthropic | 4.00       | 20.00       | 1M      | premium   | active (Global CRIS; no Batch; verified 2026-09-24)                                            |
| Claude Opus 5.5 (US Geo)          | us.anthropic.claude-opus-5-5             | Anthropic | 4.40       | 22.00       | 1M      | premium   | active (commercial US Geo; no Batch; verified 2026-09-24)                                      |
| Claude Opus 5.5 (EU Geo)          | eu.anthropic.claude-opus-5-5             | Anthropic | 4.40       | 22.00       | 1M      | premium   | active (EU Geo; no Batch; verified 2026-09-24)                                                 |
| Claude Opus 5.5 (AU Geo)          | au.anthropic.claude-opus-5-5             | Anthropic | 4.40       | 22.00       | 1M      | premium   | active (AU Geo; no Batch; verified 2026-09-24)                                                 |
| Claude Opus 5.5 (JP Geo)          | jp.anthropic.claude-opus-5-5             | Anthropic | 4.40       | 22.00       | 1M      | premium   | active (JP Geo; no Batch; verified 2026-09-24)                                                 |
| Claude Opus 5.5 (Mantle)          | anthropic.claude-opus-5-5                | Anthropic | 4.40       | 22.00       | 1M      | premium   | active (commercial Mantle Messages; no Batch; verified 2026-09-24)                             |
| Claude Opus 5.5 (London in-region) | anthropic.claude-opus-5-5 | Anthropic | 4.40 | 22.00 | 1M | premium | active (eu-west-2 runtime only; no Batch; verified 2026-10-03) |
| Claude Opus 5.5 (GovCloud Geo)    | us.anthropic.claude-opus-5-5             | Anthropic | 4.80       | 24.00       | 1M      | premium   | active (us-gov-east-1/us-gov-west-1 only; no Batch; verified 2026-09-24)                       |
| Claude Opus 5.5 (GovCloud Mantle) | anthropic.claude-opus-5-5                | Anthropic | 4.80       | 24.00       | 1M      | premium   | active (us-gov-west-1 Mantle only; no Batch; verified 2026-09-24)                              |
| Claude Opus 4.8                   | anthropic.claude-opus-4-8                | Anthropic | 5.00       | 25.00       | 200K    | premium   | active                                                                                         |
| Claude Sonnet 4.6                 | anthropic.claude-sonnet-4-6              | Anthropic | 3.00       | 15.00       | 200K    | flagship  | active                                                                                         |
| Claude Opus 4.6                   | anthropic.claude-opus-4-6-v1             | Anthropic | 5.00       | 25.00       | 200K    | premium   | active                                                                                         |
| Claude Haiku 4.5                  | anthropic.claude-haiku-4-5-20251001-v1:0 | Anthropic | 1.00       | 5.00        | 200K    | fast      | active                                                                                         |
| Claude Opus 4.1                   | anthropic.claude-opus-4-1-20250805-v1:0  | Anthropic | 15.00      | 75.00       | 200K    | premium   | legacy (EOL Jan 8, 2027)                                                                       |
| Llama 4 Maverick                  | meta.llama4-maverick-17b-instruct-v1:0   | Meta      | 0.24       | 0.97        | 1M      | mid       | active                                                                                         |
| Llama 4 Scout                     | meta.llama4-scout-17b-instruct-v1:0      | Meta      | 0.17       | 0.66        | 10M     | efficient | active                                                                                         |
| Llama 3.3 70B                     | meta.llama3-3-70b-instruct-v1:0          | Meta      | 0.72       | 0.72        | 128K    | mid       | active                                                                                         |
| Nova 2 Lite                       | amazon.nova-2-lite-v1:0                  | Amazon    | 0.33       | 2.75        | 1M      | mid       | active                                                                                         |
| Nova Pro                          | amazon.nova-pro-v1:0                     | Amazon    | 0.80       | 3.20        | 300K    | mid       | active                                                                                         |
| Nova Lite                         | amazon.nova-lite-v1:0                    | Amazon    | 0.06       | 0.24        | 300K    | fast      | active                                                                                         |
| Nova Micro                        | amazon.nova-micro-v1:0                   | Amazon    | 0.035      | 0.14        | 128K    | budget    | active                                                                                         |
| Mistral Large 3                   | mistral.mistral-large-3-675b-instruct    | Mistral   | 0.50       | 1.50        | 256K    | flagship  | active                                                                                         |
| DeepSeek-R1                       | deepseek.r1-v1:0                         | DeepSeek  | 1.35       | 5.40        | 128K    | reasoning | active                                                                                         |
| gpt-oss-20b                       | openai.gpt-oss-20b-1:0                   | OpenAI    | 0.07       | 0.30        | 128K    | budget    | active                                                                                         |
| gpt-oss-120b                      | openai.gpt-oss-120b-1:0                  | OpenAI    | 0.15       | 0.60        | 128K    | efficient | active                                                                                         |
| GPT-5.6 Sol                       | openai.gpt-5.6-sol                       | OpenAI    | 4.40       | 22.00       | 272K    | frontier  | active (mantle in-region + runtime CRIS; 1M tier 8.80/33.00)                                   |
| GPT-5.6 Terra                     | openai.gpt-5.6-terra                     | OpenAI    | 2.20       | 13.20       | 272K    | flagship  | active (mantle in-region + runtime CRIS; 1M tier 4.40/19.80)                                   |
| GPT-5.6 Luna                      | openai.gpt-5.6-luna                      | OpenAI    | 0.22       | 1.32        | 272K    | fast      | active (mantle in-region + runtime CRIS; 1M tier 0.44/1.98)                                    |
| GPT-5.5                           | openai.gpt-5.5                           | OpenAI    | 5.50       | 33.00       | 272K    | frontier  | active (mantle only; no 1M tier)                                                               |
| GPT-5.4                           | openai.gpt-5.4                           | OpenAI    | 2.75       | 16.50       | 272K    | flagship  | active (mantle only; no 1M tier)                                                               |

_Quick-reference rows use **—** for **model ID** and **context**; resolve in the Bedrock console
or AWS model documentation. This is a curated subset for migration selection — see the Bedrock
pricing page for the full catalog._

### Embeddings — Bedrock (per 1M input tokens, US East)

Embedding models are **input-only** — priced per 1M input tokens, no output charge. Use for
`embedding` capability workloads (RAG corpora, semantic search, FAQ retrieval). A migration from
an OpenAI/Azure embedding deployment lands on one of these; note the **dimension** must match (or
the corpus must be re-embedded and any similarity threshold recalibrated).

| Model                        | Model ID                     | Provider | Input $/1M | Dimensions        | Tier     | Status |
| ---------------------------- | ---------------------------- | -------- | ---------- | ----------------- | -------- | ------ |
| Titan Text Embeddings v2     | amazon.titan-embed-text-v2:0 | Amazon   | 0.02       | 1024/512/256      | default  | active |
| Titan Text Embeddings v1     | amazon.titan-embed-text-v1   | Amazon   | 0.10       | 1536              | legacy   | active |
| Cohere Embed v4              | cohere.embed-v4:0            | Cohere   | 0.12       | 1536/1024/512/256 | flagship | active |
| Cohere Embed English v3      | cohere.embed-english-v3      | Cohere   | 0.10       | 1024              | mid      | active |
| Cohere Embed Multilingual v3 | cohere.embed-multilingual-v3 | Cohere   | 0.10       | 1024              | mid      | active |

**Default target for a migrating OpenAI/Azure embedding workload:** Titan Text Embeddings v2
(`amazon.titan-embed-text-v2:0`) — cheapest, configurable dimensions (1024 default; 512/256 for
cost/latency). Choose Cohere Embed v4 when the source used a large-dimension model and matrix
compatibility or multilingual quality matters. Titan v2 output dimension is configurable, so map
`text-embedding-3-large` (3072-dim) or `-small` (1536-dim) to Titan 1024 and **re-embed** — there
is no dimension-preserving swap. See `references/vendored/ai/ai-openai-to-bedrock.md`.

### Stability AI — Image Generation (per image, US East)

Priced **per image** (not per token). Use for `image_generation` capability workloads.

| Model                      | Model ID                          | Price/image | Resolution | Tier     | Status |
| -------------------------- | --------------------------------- | ----------- | ---------- | -------- | ------ |
| Stable Image Ultra         | stability.stable-image-ultra-v1:0 | $0.08       | up to 4MP  | premium  | active |
| Stable Diffusion 3.5 Large | stability.sd3-5-large-v1:0        | $0.065      | up to 1MP  | flagship | active |
| Stable Image Core          | stability.stable-image-core-v1:0  | $0.04       | up to 1MP  | fast     | active |

> **Cost comparison note:** DALL-E 3 (OpenAI / Azure OpenAI) charges $0.04–$0.12/image by
> resolution. When comparing, use per-image cost directly — do not convert Stability AI prices
> to per-token equivalents.

### Anthropic Claude — batch & prompt cache (Standard, US East N. Virginia)

Per 1M tokens unless noted.

| Model             | Batch in | Batch out | 5m cache write | 1h cache write | Cache read |
| ----------------- | -------- | --------- | -------------- | -------------- | ---------- |
| Claude Sonnet 5   | 1.00 ‡   | 5.00 ‡    | 2.50           | 4.00           | 0.20       |
| Claude Opus 5.5 (Global)                | N/A      | N/A       | 5.00           | 8.00           | 0.20       |
| Claude Opus 5.5 (commercial Geo/Mantle/London runtime) | N/A      | N/A       | 5.50           | 8.80           | 0.22       |
| Claude Opus 5.5 (GovCloud)              | N/A      | N/A       | 6.00           | 9.60           | 0.24       |
| Claude Opus 4.8   | 2.50 ‡   | 12.50 ‡   | 6.25           | 10.00          | 0.50       |
| Claude Sonnet 4.6 | 1.50     | 7.50      | 3.75           | 6.00           | 0.30       |
| Claude Haiku 4.5  | 0.50     | 2.50      | 1.25           | 2.00           | 0.10       |

‡ Not listed on the [batch-supported models table](https://docs.aws.amazon.com/bedrock/latest/userguide/batch-inference-supported.html)
as of 2026-10-05 — the figure above is the standard 50%-of-on-demand projection, not a confirmed
SKU. Mark these batch cells `_unverified_` in estimate output; the `unverified` gate in
`estimate-ai.md` treats any `_unverified_` row as blocking for a quoted figure — resolve from
the Bedrock pricing page first before quoting a Sonnet 5 or Opus 4.8 batch savings figure.

### OpenAI on Bedrock — the same-model path

The proprietary GPT-5.x models on Bedrock are priced at OpenAI's **data-residency tier ≈ 1.10x**
the OpenAI standard rates below, and run **`bedrock-mantle` only, in-region only** (no
`bedrock-runtime`, no cross-region inference profile for GPT-5.5/5.4). `gpt-oss` DOES support
`bedrock-runtime`. For endpoint paths, region matrix, quotas, and prompt-caching detail see
`references/shared/openai-on-bedrock.md` (the fact base the mapping guide reads).

## Source Provider Pricing (for Migration Comparison)

Use alongside the Bedrock rates to compute migration ROI. This is the **source-side baseline** —
what the customer pays today on their current provider. Per `estimate-ai.md`, the authoritative
"today" figure is MEASURED/STATED spend (from discovery or clarify); these list rates are the
fallback when no measured spend exists, and the source side of the per-model "vs source" column.

> **Azure OpenAI uses the OpenAI rows below.** Azure OpenAI serves the same GPT models at list
> prices that track OpenAI's, so `ai_source: azure_openai` reads the OpenAI table here — there is
> no separate Azure-OpenAI table (plan §19.9a). Azure OpenAI's enterprise/PTU discounts vary per
> contract; when the customer's actual spend is known, that overrides these list rates.

### OpenAI / Azure OpenAI (Standard Tier)

Prices per 1M tokens.

> **Tier note — these are OpenAI STANDARD-tier rates.** Bedrock in-region for the same models is
> the OpenAI _data-residency_ tier, exactly 1.10x these figures (see the OpenAI-on-Bedrock note
> above). So a same-model move for GPT-5.6 Sol/Terra/Luna, GPT-5.5, GPT-5.4 is a ~10% increase,
> not parity — compute the target from the Bedrock table, not by carrying these over. These rows
> are the right source-side baseline, and the only figures available for models with **no**
> Bedrock equivalent (GPT-5.x Pro, GPT-5.2/5.1, GPT-4.x, o-series).

| Model         | Input $/1M   | Output $/1M  | Context | Tier      |
| ------------- | ------------ | ------------ | ------- | --------- |
| GPT-5.6 Sol   | _unverified_ | _unverified_ | 1M      | frontier  |
| GPT-5.6 Terra | _unverified_ | _unverified_ | 1M      | flagship  |
| GPT-5.6 Luna  | 0.20         | 1.20         | 1M      | fast      |
| GPT-5.5       | 5.00         | 30.00        | 1M      | flagship  |
| GPT-5.5 Pro   | 30.00        | 180.00       | 1M      | premium   |
| GPT-5.4       | 2.50         | 15.00        | 1.05M   | flagship  |
| GPT-5.4 Mini  | 0.75         | 4.50         | —       | fast      |
| GPT-5.4 Nano  | 0.20         | 1.25         | —       | budget    |
| GPT-5.4 Pro   | 30.00        | 180.00       | 1.05M   | premium   |
| GPT-5.2       | 1.75         | 14.00        | 200K    | flagship  |
| GPT-5.1       | 1.25         | 10.00        | 200K    | flagship  |
| GPT-5 Mini    | 0.25         | 2.00         | 200K    | fast      |
| GPT-5 Nano    | 0.05         | 0.40         | 128K    | budget    |
| GPT-4.1       | 2.00         | 8.00         | 1M      | flagship  |
| GPT-4.1 Mini  | 0.40         | 1.60         | 1M      | fast      |
| GPT-4.1 Nano  | 0.10         | 0.40         | 1M      | budget    |
| GPT-4o        | 2.50         | 10.00        | 128K    | flagship  |
| o3            | 2.00         | 8.00         | 200K    | reasoning |
| o4-mini       | 1.10         | 4.40         | 200K    | reasoning |

> **Azure OpenAI note.** Azure lists the same models under Azure-specific deployment names
> (e.g. `gpt-4o`, `gpt-4.1`) and bills per 1M tokens at rates that track the table above. Azure
> adds Provisioned Throughput Units (PTU) as an alternative to pay-as-you-go; a customer on PTU
> has a committed monthly cost that their stated spend captures directly — prefer stated spend
> over these list rates when available.

### Embeddings — OpenAI / Azure OpenAI source (per 1M input tokens)

The source-side baseline for a migrating embedding workload. Input-only. Map the "$X today" from
measured/stated spend when available; these list rates are the fallback.

| Model                  | Input $/1M | Dimensions | Tier     |
| ---------------------- | ---------- | ---------- | -------- |
| text-embedding-3-large | 0.13       | 3072       | flagship |
| text-embedding-3-small | 0.02       | 1536       | fast     |
| text-embedding-ada-002 | 0.10       | 1536       | legacy   |

Azure OpenAI bills the same models under deployment names at rates that track this table (PTU
caveat above applies). A `text-embedding-3-large` → Titan v2 move is **not** a dimension-preserving
swap (3072 → 1024) — it requires re-embedding the corpus and recalibrating similarity thresholds;
surface that as a migration task, not a silent cost line.

_Gemini source rows from gcp-to-aws are intentionally omitted: azure-to-aws has no `gemini`
`ai_source` (plan §19.9b)._
