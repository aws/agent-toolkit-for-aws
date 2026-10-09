# Source-Provider AI Pricing Cache

**Last updated:** 2026-10-05 (re-verified via the AWS Pricing MCP server, aws.amazon.com/bedrock/pricing, and the Bedrock model cards' Geo/Global inference ID tables — Claude Sonnet 5 $2/$10 (Global/base) / $2.20/$11 (Geo, `us.`-prefixed), Opus 4.8 $5/$25 (Global/base) / $5.50/$27.50 (Geo), Sonnet 4.6 $3/$15 (Global/base) / $3.30/$16.50 (Geo), Haiku 4.5 $1/$5 (Global/base) / $1.10/$5.50 (Geo), Opus 4.6 $5/$25, Opus 4.1 legacy $15/$75, Claude Fable 5 $10/$50, Llama 4 Maverick/Scout, Llama 3.3 70B, Nova 2 Lite/Pro/Lite/Micro, Mistral Large 3, DeepSeek-R1, gpt-oss-20b/120b, GPT-5.6/5.5/5.4 family, and the OpenAI/Azure OpenAI source-side table all confirmed unchanged; this refresh corrects the Geo-vs-Global pricing gap for the four Anthropic models that require a cross-Region inference profile — see the Geo vs. Global note below)
**Region:** us-east-1
**Currency:** USD
**Accuracy:** ±15-25% for source-provider AI models (sourced from public pricing pages)

> **Scope: source-provider AI only.** This file contains the OpenAI / Azure OpenAI
> baselines used for migration ROI. Bedrock model and service rates, lifecycle-sensitive
> statuses, units, and staleness guidance are canonical in
> `references/vendored/ai/bedrock-pricing-cache.md`. Infrastructure is priced from
> `references/vendored/pricing/aws-infra-pricing.json` (the file the `pricing-coverage`
> gate enforces).
>
> Prices vary by region and change over time; use for estimation only. There is no live pricing
> lookup — on a cache miss apply `pricing-fallback.md` (`estimated` or `unavailable`).
> **Staleness warning:** if today is more than 30 days after **Last updated**, treat source-provider
> prices as potentially stale; set `pricing_source: "cached_stale"` in `estimation-ai.json` and
> note it.

---

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
> the OpenAI _data-residency_ tier, exactly 1.10x these figures (see
> `references/shared/openai-on-bedrock.md`). So a same-model move for GPT-5.6 Sol/Terra/Luna,
> GPT-5.5, GPT-5.4 is a ~10% increase, not parity — compute the target from the vendored Bedrock
> cache, not by carrying these over. These rows are the right source-side baseline, and the only
> figures available for models with **no** Bedrock equivalent (GPT-5.x Pro, GPT-5.2/5.1, GPT-4.x,
> o-series).

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
