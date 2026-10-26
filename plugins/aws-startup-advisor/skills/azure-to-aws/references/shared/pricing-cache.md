# Source-Provider AI Pricing Cache

**Last updated:** 2026-10-10 (added the GPT-6 family — GPT-6 Astra, GPT-6 Sol, GPT-6 Luna, GPT-6.1 Sol — sourced
from each model's own AWS Bedrock model card and OpenAI's own API pricing page, fetched 2026-10-10; see
`shared/openai-on-bedrock.md` for full citations. Prior refresh, 2026-10-05: re-verified via the AWS Pricing MCP
server, aws.amazon.com/bedrock/pricing, and the Bedrock model cards' Geo/Global inference ID tables — Claude
Sonnet 5.5 $2/$10 (Global) / $2.20/$11 (Geo; US East (Ohio) Bedrock table, verified 2026-10-25; cache read $0.10 / $0.11, reduced 50% from Oct 7, 2026), Sonnet 5 $2/$10 (Global/base) / $2.20/$11 (Geo, `us.`-prefixed), Opus 4.8 $5/$25 (Global/base) / $5.50/$27.50
(Geo), Sonnet 4.6 $3/$15 (Global/base) / $3.30/$16.50 (Geo), Haiku 4.5 $1/$5 (Global/base) / $1.10/$5.50 (Geo),
Opus 4.6 $5/$25, Opus 4.1 legacy $15/$75, Claude Fable 5 $10/$50, Llama 4 Maverick/Scout, Llama 3.3 70B, Nova 2
Lite/Pro/Lite/Micro, Mistral Large 3, DeepSeek-R1, gpt-oss-20b/120b, GPT-5.6/5.5/5.4 family, and the OpenAI/Azure
OpenAI source-side table all confirmed unchanged; this refresh corrects the Geo-vs-Global pricing gap for the four
Anthropic models that require a cross-Region inference profile — see the Geo vs. Global note below)
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

Prices per 1M tokens. GPT-5.5 and GPT-5.5 Pro use the same breakpoint pricing structure as GPT-5.4
at 272K input tokens. GPT-5.4 and GPT-5.4 Pro use **breakpoint pricing** at 272K input tokens:
rates below are for <272K context; above 272K, input is 2x and output is 1.5x.

GPT-6 Astra, GPT-6 Sol, GPT-6 Luna, and GPT-6.1 Sol use the same breakpoint shape at 272,000 input
tokens: rows below are the short-context (≤272K) rate; above 272,000 input tokens, the entire
request — input, cache, and output — is repriced at 2x input/cache and 1.5x output (see the
"OpenAI on Bedrock — the same-model path" section above, or OpenAI's own GPT-6 pricing page, for
the resulting rates).

> GPT-6 rows below show the ≤272K short-context rate (the Standard-tier default range); 1.05M is
> the model's maximum context window, not the rate's valid range — see the breakpoint note above.
>
> **Tier note — these are OpenAI STANDARD-tier rates.** Bedrock in-region for the same models is
> the OpenAI _data-residency_ tier, exactly 1.10x these figures (see
> `references/shared/openai-on-bedrock.md`). So a same-model move for GPT-5.6 Sol/Terra/Luna,
> GPT-5.5, GPT-5.4 is a ~10% increase, not parity — compute the target from the vendored Bedrock
> cache, not by carrying these over. These rows are the right source-side baseline, and the only
> figures available for models with **no** Bedrock equivalent (GPT-5.x Pro, GPT-5.2/5.1, GPT-4.x,
> o-series).

| Model         | Input $/1M   | Output $/1M  | Context | Tier      |
| ------------- | ------------ | ------------ | ------- | --------- |
| GPT-6 Astra   | 10.00        | 50.00        | ≤272K*  | frontier  |
| GPT-6.1 Sol   | 2.00         | 10.00        | ≤272K*  | flagship  |
| GPT-6 Sol     | 2.00         | 10.00        | ≤272K*  | flagship  |
| GPT-6 Luna    | 0.10         | 0.50         | ≤272K*  | fast      |
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

*GPT-6 rows: 1.05M is the model's max window, not this rate's valid range. Requests >272,000 input tokens reprice input/cache 2x and output 1.5x — see the breakpoint note above and pricing-cache.md's long-context tables.

> **Azure OpenAI note.** Azure lists the same models under Azure-specific deployment names
> (e.g. `gpt-4o`, `gpt-4.1`) and bills per 1M tokens at rates that track the table above. Azure
> adds Provisioned Throughput Units (PTU) as an alternative to pay-as-you-go; a customer on PTU
> has a committed monthly cost that their stated spend captures directly — prefer stated spend
> over these list rates when available.

### Anthropic (Standard Tier, 1P API)

Prices per 1M tokens. Source: [claude.com/pricing](https://claude.com/pricing), verified October 2026.

| Model              | Input $/1M | Output $/1M | Context | Tier     |
| ------------------ | ---------- | ----------- | ------- | -------- |
| Claude Haiku 4.5   | 1.00       | 5.00        | 200K    | fast     |
| Claude Sonnet 4.5  | 3.00       | 15.00       | 200K    | flagship |
| Claude Sonnet 5.5  | 2.00       | 10.00       | —       | flagship |
| Claude Sonnet 5    | 2.00       | 10.00       | 1M      | flagship |

> These first-party rates match Bedrock's Global/base rate for the same models, and a Bedrock
> `us.`-prefixed Geo inference profile runs about 10% higher (see the Geo vs. Global note in the
> Bedrock Models section).

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
