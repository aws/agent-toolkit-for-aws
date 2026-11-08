# Gemini to Bedrock — Model Selection Guide

> Canonical Gemini → Bedrock model-selection guide. Source-cloud agnostic: the
> Bedrock target does not depend on which cloud or endpoint served the Gemini
> calls, so this serves Google AI Studio / Gemini API usage, Vertex AI Generative
> AI (Gemini models), and any other Gemini-serving endpoint.
> Vendored into each consuming skill as
> `references/vendored/ai/ai-gemini-to-bedrock.md` and kept byte-identical by
> `shared:check`; edit HERE, then run `shared:sync`.

**Applies to:** Gemini SDK / Gemini (Vertex AI Generative AI) usage detected in applications hosted on any source cloud → Amazon Bedrock

This file is loaded by `design-ai.md` when `ai-workload-profile.json` has `summary.ai_source` = `"gemini"` or `"both"` (or, in the normalized profile, when a `google` AI source is present). It provides model mapping tables with pricing and honest competitive analysis for Gemini → Bedrock migration decisions.

Verify Bedrock pricing against `references/vendored/ai/bedrock-pricing-cache.md`. Source-provider (Gemini) pricing is owned by the consuming skill's source-pricing cache where the source cloud's IaC/live evidence is provider-specific; the figures in this guide's Gemini columns are provided as a current-as-of reference for the mapping decision, not as a live source lookup.

**Model lifecycle:** Before recommending any Bedrock model, check `references/vendored/ai/ai-model-lifecycle.md`. Do not recommend Legacy models as primary selections for new migrations. Legacy models are annotated below where they appear.

**Recommend defaults:** Claude Sonnet 5 for balanced/flagship; Claude Opus 5.5 for demanding reasoning (20% lower standard input/output token prices than Opus 5; [Anthropic reports improved token efficiency](https://claude.com/blog/what-a-task-costs-on-opus-5-5), with actual usage varying by task and effort setting); Claude Haiku 5.5 for cost/speed. Sonnet 5 is **$2/$10** — the launch rate became the standard price on Sep 1, 2026 (the scheduled increase to $3/$15 was cancelled); comparison tables below use $2/$10. Do not default to any Claude Fable / Mythos frontier model.

---

## Competitive Reality (May 2026)

Gemini 3.5 Flash is now GA (May 2026) — the current flagship Flash model. Gemini 3.1 Pro is the current Pro tier. Be honest with users:

- Gemini 3.1 Pro leads 13/16 Google-reported benchmarks and 6/10 on the Artificial Analysis Intelligence Index
- ARC-AGI-2: 77.1%, SWE-Bench: 80.6% (tied with Opus 4.6 at 80.8%)
- Gemini 3.1 Pro costs $2/$12 per 1M tokens — less than half of Opus 4.6 ($5/$25), and slightly above Sonnet 5 ($2/$10, ~13% cheaper blended)
- Gemini 3.5 Flash at $1.50/$9.00 is 5x more expensive than the retired Gemini 2.5 Flash ($0.30/$2.50) — the Bedrock cost savings case is now much stronger for Flash-tier users
- Gemini 3.8 Flash (GA Sep 2, 2026) is Google's named replacement for both Gemini 2.5 Pro and 2.5 Flash. It is $0.75/$3.75 through Dec 31, 2026 and $1.50/$7.50 from Jan 1, 2027 ([Gemini Developer API pricing](https://aistudio.google.com/docs/pricing), read 2026-11-08); tables below use the 2026 rate — recompute after the step-up
- **Gemini 2.5 Pro, 2.5 Flash, and 2.5 Flash-Lite are retired on Vertex AI as of Oct 20, 2026.** On the Gemini Developer API, 2.5 Pro and 2.5 Flash shut down Dec 1, 2026 (auto-routing to 3.8 Flash and 3.5 Flash-Lite respectively); 2.5 Flash-Lite is not deprecated there. Sources: [Vertex AI model versions](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions) and [Gemini API deprecations](https://aistudio.google.com/docs/deprecations), both read 2026-11-08. See `references/vendored/ai/ai-model-lifecycle.md` § Source-Model Retirements
- **Source baseline is what the customer pays today, by serving API and date** (same lifecycle section): a measured bill always wins; otherwise a Developer API `gemini-2.5-flash-lite` workload keeps its $0.10/$0.40 baseline with no cutoff; Developer API 2.5 Pro / 2.5 Flash use $1.25/$10.00 and $0.30/$2.50 before Dec 1, 2026 and the routed model's rate (3.8 Flash with its Jan 1, 2027 step; 3.5 Flash-Lite) on or after; Vertex AI 2.5 workloads and all 2.0 workloads are past shutdown and are priced against the replacement. The retired models still never appear as current rows in the tiers or the cost table below

**Where Bedrock still wins:**

- Claude Sonnet 5 / Opus 4.x lead on real-world agentic tasks (GDPval evaluation) — the gap between benchmarks and production agent reliability is real
- Claude prompt caching (90% savings on repeated content) has no Gemini equivalent
- Claude function calling remains best-in-class for complex multi-turn tool use
- AWS service integration (AgentCore, Knowledge Bases, Guardrails) has no Gemini equivalent

**Migration case by tier:**

- Gemini 3.5 Flash → Bedrock: **strong cost case** — Nova Lite is 94% cheaper; even Claude Sonnet 5 is close at $2/$10 vs $1.50/$9.00
- Gemini 3.1 Pro → Bedrock: driven by AWS consolidation, agentic reliability, or AWS service breadth; Sonnet 5 at $2/$10 adds a modest (~13%) cost edge, but the case is not cost-led and not general benchmarks
- Gemini 3.1 Flash-Lite → Nova Lite/Micro: still 76-88% cheaper, strong cost case
- Gemini 3.8 Flash → Bedrock: Nova Lite is 93% cheaper and Nova Pro 9% cheaper at the 2026 rate; the gap doubles when the Jan 1, 2027 price step-up lands
- Gemini 3.5 Flash-Lite → Nova Lite/Micro: 88-93% cheaper, strong cost case
- Gemini 2.5 Pro / Flash / Flash-Lite → **retired source model on Vertex AI (Oct 20, 2026).** Vertex AI users must leave the source model anyway; migrating straight to Bedrock avoids a double hop through 3.8 Flash / 3.5 Flash-Lite. Developer API users on 2.5 Pro / 2.5 Flash face the Dec 1, 2026 auto-route and are priced at their current rate until then; a Developer API 2.5 Flash-Lite user has no forced cutoff and is priced at $0.10/$0.40 — the Bedrock case there is Nova Micro's 65%, not 3.5 Flash-Lite's 93%. Mapping rows are in Legacy/Specialized below

---

## Bedrock Model Portfolio

| Model            | Best For                                                            | Complexity | Speed   | Context |
| ---------------- | ------------------------------------------------------------------- | ---------- | ------- | ------- |
| Claude Sonnet 5  | Agentic tasks, tool use                                             | High       | High    | 1M      |
| Claude Opus 5.5  | Demanding reasoning; no Batch                                       | High       | Measure | 1M      |
| Claude Haiku 5.5 | Simple + fast                                                       | Medium     | High    | 1M      |
| Llama 4 Maverick | Cost-effective + multimodal                                         | Medium     | High    | 1M      |
| Llama 4 Scout    | Ultra-long context, cheapest                                        | Medium     | Medium  | 10M     |
| Nova 2 Pro       | AWS flagship, multimodal                                            | High       | High    | 1M      |
| Nova 2 Lite      | AWS mid-tier, long context                                          | Medium     | High    | 1M      |
| Nova Pro         | AWS balanced                                                        | Medium     | High    | 300K    |
| Nova Lite        | AWS fast + cheapest                                                 | Medium     | High    | 300K    |
| Nova Micro       | AWS fastest, text-only                                              | Low        | High    | 128K    |
| Nova Premier     | Complex reasoning — **Legacy** (EOL Sep 14, 2026) prefer Nova 2 Pro | High       | Medium  | 1M      |
| DeepSeek-R1      | Chain-of-thought reasoning                                          | High       | Medium  | 128K    |
| Mistral Large 3  | EU/Multilingual                                                     | High       | Medium  | 256K    |

---

## Gemini → Bedrock Model Mapping

### Gemini Pro Tier

| Gemini Model   | Price (in/out per 1M) | Best Bedrock Match               | Bedrock Price  | Winner              |
| -------------- | --------------------- | -------------------------------- | -------------- | ------------------- |
| Gemini 3.1 Pro | $2.00 / $12.00        | Claude Sonnet 5                  | $2.00 / $10.00 | Bedrock 13% cheaper |
| Gemini 3.1 Pro | $2.00 / $12.00        | Claude Opus 5.5 (Global)         | $4.00 / $20.00 | Gemini 43% cheaper  |
| Gemini 3.1 Pro | $2.00 / $12.00        | Claude Opus 5.5 (commercial Geo) | $4.40 / $22.00 | Gemini 48% cheaper  |
| Gemini 3.1 Pro | $2.00 / $12.00        | Nova 2 Pro                       | $1.38 / $11.00 | Bedrock 14% cheaper |
| Gemini 3 Pro   | $0.50 / $3.00         | Llama 4 Maverick                 | $0.24 / $0.97  | Bedrock 64% cheaper |
| Gemini 3 Pro   | $0.50 / $3.00         | Llama 4 Scout                    | $0.17 / $0.66  | Bedrock 75% cheaper |
| Gemini 3 Pro   | $0.50 / $3.00         | Nova Pro                         | $0.80 / $3.20  | Gemini 17% cheaper  |

> **Gemini 3.1 Pro breakpoint:** $4.00/$18.00 per 1M for prompts >200k tokens. Table above uses ≤200k rates.
>
> **Gemini 2.5 Pro** is retired (Vertex AI Oct 20, 2026; Developer API shutdown Dec 1, 2026). Google's named replacement is Gemini 3.8 Flash — see the Flash/Lite tier — not a Pro model. Its legacy mapping row is under Legacy/Specialized.

### Gemini Flash/Lite Tier

| Gemini Model              | Price (in/out per 1M)                                       | Best Bedrock Match                     | Bedrock Price  | Winner                                                                                                                                                                                                                                                   |
| ------------------------- | ----------------------------------------------------------- | -------------------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Gemini 3.5 Flash (GA)     | $1.50 / $9.00                                               | Nova Lite                              | $0.06 / $0.24  | Bedrock 94% cheaper — strong migration case; 3.5 Flash is 5x more expensive than the retired 2.5 Flash                                                                                                                                                   |
| Gemini 3.5 Flash (GA)     | $1.50 / $9.00                                               | Claude Sonnet 5                        | $2.00 / $10.00 | Gemini 14% cheaper — but Sonnet leads on agentic reliability                                                                                                                                                                                             |
| Gemini 3.8 Flash (GA)     | $0.75 / $3.75 (2026 rate; $1.50 / $7.50 from Jan 1, 2027)   | Nova Lite                              | $0.06 / $0.24  | Bedrock 93% cheaper — Google's named replacement for the retired 2.5 Pro and 2.5 Flash; strong migration case                                                                                                                                                        |
| Gemini 3.8 Flash (GA)     | $0.75 / $3.75 (2026 rate; $1.50 / $7.50 from Jan 1, 2027)   | Nova Pro                               | $0.80 / $3.20  | Bedrock 9% cheaper at the 2026 rate; ~54% cheaper once the 2027 rate applies                                                                                                                                                                             |
| Gemini 3.8 Flash (GA)     | $0.75 / $3.75 (2026 rate; $1.50 / $7.50 from Jan 1, 2027)   | Claude Sonnet 5                        | $2.00 / $10.00 | Gemini 63% cheaper at the 2026 rate — Sonnet is a capability move (agentic reliability, prompt caching), not a saving                                                                                                                                      |
| Gemini 3.5 Flash-Lite     | $0.30 / $2.50                                               | Nova Lite                              | $0.06 / $0.24  | Bedrock 88% cheaper — Google's named replacement for the retired 2.5 Flash and 2.5 Flash-Lite                                                                                                                                                                        |
| Gemini 3.5 Flash-Lite     | $0.30 / $2.50                                               | Nova Micro                             | $0.035 / $0.14 | Bedrock 93% cheaper                                                                                                                                                                                                                                      |
| Gemini 3.1 Flash-Lite     | $0.25 / $1.50                                               | Nova Lite                              | $0.06 / $0.24  | Bedrock 76% cheaper                                                                                                                                                                                                                                      |
| Gemini 3.1 Flash-Lite     | $0.25 / $1.50                                               | Nova Micro                             | $0.035 / $0.14 | Bedrock 88% cheaper                                                                                                                                                                                                                                      |
| Gemini Flash 1.5          | **Legacy — EOL Sep 24, 2025. Migrate to Gemini 3.5 Flash.** | Nova Lite                              | $0.06 / $0.24  | If still in use, migrate source model first; strong Bedrock cost case once on 3.5 Flash                                                                                                                                                                  |

### Legacy/Specialized

| Gemini Model                                                 | Price (in/out per 1M)                                                         | Best Bedrock Match                | Bedrock Price                                                                               | Winner                                                                    |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Gemini 2.5 Pro                                               | **Legacy — retired on Vertex AI Oct 20, 2026; Developer API shutdown Dec 1, 2026 (auto-routes to 3.8 Flash). Developer API list price $1.25 / $10.00 until Dec 1, 2026.** | Claude Sonnet 5; Nova Pro for cost | $2.00 / $10.00; $0.80 / $3.20                                                              | Vertex AI: past EOL — price against the 3.8 Flash rows above. Developer API before Dec 1, 2026: baseline $1.25 / $10.00 (Nova Pro 62% cheaper); on or after Dec 1 the bill is 3.8 Flash's rate ($0.75 / $3.75; $1.50 / $7.50 from Jan 1, 2027) — go straight to Bedrock rather than via 3.8 Flash |
| Gemini 2.5 Flash / 2.5 Flash Thinking                        | **Legacy — retired on Vertex AI Oct 20, 2026; Developer API shutdown Dec 1, 2026 (auto-routes to 3.5 Flash-Lite). Developer API list price $0.30 / $2.50 until Dec 1, 2026.** | Nova Lite; Claude Sonnet 5 with extended thinking when thinking mode is required | $0.06 / $0.24; $2.00 / $10.00                                            | Nova Lite 88% cheaper. Developer API before Dec 1, 2026: baseline $0.30 / $2.50; on or after Dec 1 the bill is 3.5 Flash-Lite's rate (the same $0.30 / $2.50, so the figure does not move). Vertex AI: use the 3.5 Flash-Lite rows above |
| Gemini 2.5 Flash-Lite                                        | **Legacy — retired on Vertex AI Oct 20, 2026; still served on the Gemini Developer API with no shutdown date. Developer API list price $0.10 / $0.40, no cutoff.** | Nova Micro                        | $0.035 / $0.14                                                                              | Developer API: baseline stays $0.10 / $0.40 with no forced cutoff — Nova Micro 65% cheaper ($45 vs $15.75 at 150M / 75M); do not substitute 3.5 Flash-Lite's $0.30 / $2.50. Vertex AI: past EOL — price against the 3.5 Flash-Lite rows above |
| Gemini 2.0 Flash                                             | **Legacy — retired on Vertex AI and the Gemini Developer API Jun 1, 2026 (upgrade 3.5 Flash-Lite on Vertex, 3.6 Flash on the Developer API). Was $0.10 / $0.40.** | Nova Micro; Claude Haiku 5.5 when quality matters more than cost | $0.035 / $0.14; US Geo $0.11 / $0.55 up to 100K prompt tokens | Nova Micro was 65% cheaper than the retired rate; if still named in code, go straight to Bedrock rather than via 3.5 Flash-Lite |
| Gemini 2.0 Flash-Lite                                        | **Legacy — retired on Vertex AI and the Gemini Developer API Jun 1, 2026 (upgrade 3.5 Flash-Lite on Vertex, 3.1 Flash-Lite on the Developer API). Was $0.075 / $0.30.** | Nova Micro / Nova Lite            | $0.035 / $0.14; $0.06 / $0.24                                                               | Nova Micro was 53% cheaper than the retired rate; for a live comparison use the 3.5 Flash-Lite or 3.1 Flash-Lite rows above |
| Gemini 1.5 Pro                                               | **Legacy — EOL Sep 24, 2025. Migrate to Gemini 3.1 Pro or 3.8 Flash.**        | Claude Sonnet 5                   | $2.00 / $10.00                                                                              | If still in use, migrate source model first                               |
| text-bison / chat-bison                                      | Legacy                                                                        | Llama 4 Scout                     | $0.17 / $0.66                                                                               | Bedrock (better quality + cheaper)                                        |
| text-embedding-004                                           | $0.025 / N/A                                                                  | Titan Embeddings V2               | $0.02 / N/A                                                                                 | Bedrock 20% cheaper                                                       |
| Gemini Embedding 2 (multimodal — text/image/video/audio/PDF) | text $0.20/1M, image $0.45/1M ($0.00012/img), audio $6.50/1M, video $12.00/1M | Amazon Nova Multimodal Embeddings | text $0.135/1M, image $0.00006/unit (see `references/vendored/ai/bedrock-pricing-cache.md` § Multimodal embeddings) | Bedrock ~32% cheaper on text, ~50% cheaper on image                       |
| imagen-*                                                     | Varies                                                                        | Stable Image Core                 | $0.04/img                                                                                   | Nova Canvas past EOL (2026-09-30); Ultra $0.08/img if quality-first |

_Percentages are blended savings using a 2:1 input-to-output token ratio. Actual savings depend on your input/output ratio._

---

## Decision Paths by Priority

### Quality-First

Gemini 3.1 Pro Preview matches or beats Opus 4.6 on most reasoning benchmarks at less than half the cost. Be transparent:

- If user needs **general reasoning/coding quality** → Gemini 3.1 Pro is competitive or better. Migration case is weak unless driven by AWS consolidation.
- If user needs **agentic reliability** (real-world multi-step tasks) → **Claude Sonnet 5** still leads on GDPval. This is the honest differentiator.
- If user needs **maximum reasoning on hardest problems** → **Claude Opus 5.5** (20% lower standard input/output token prices than Opus 5; [Anthropic reports improved token efficiency](https://claude.com/blog/what-a-task-costs-on-opus-5-5), with actual usage varying by task and effort setting) — use the latest [Claude on Bedrock](https://aws.amazon.com/bedrock/pricing/) model card for benchmark deltas vs Gemini; keep Opus 4.6 when Batch is required because Opus 5.5 has no Batch tier. Confirm regional availability before selecting either.

### Speed-First

Gemini Flash → **Nova Micro** (<200ms, text-only, cheapest), **Haiku 5.5** (vision; tune effort and measure latency on the target workload), or **Llama 4 Scout** (<300ms, cheapest capable)

Haiku 5.5 has a 1M context window, but its price changes above 100K input tokens per request. Standard Global input/output rates per 1M tokens are $0.10/$0.50 up to 100K and $0.50/$2.50 above 100K; US Geo rates are $0.11/$0.55 and $0.55/$2.75. These are token prices, not a guaranteed workload saving. Recount target tokens and read the Haiku 5.5 target contract in `references/vendored/ai/ai-anthropic-to-bedrock.md` before migration. The portfolio's Medium complexity rating is a conservative guide classification, not an official model limit.

### Cost-First

- Gemini Flash/Lite → **Nova Lite** (54-88% cheaper), **Nova Micro** (53-64% cheaper)
- Gemini Pro → **Llama 4 Maverick** ($0.24/$0.97, 63% cheaper than Gemini 3 Pro) or **Llama 4 Scout** ($0.17/$0.66, 75% cheaper)

### Balanced

- Gemini 3.1 Pro → **Nova 2 Pro** (-14% cost, AWS-native) or **Claude Sonnet 5** (-13% cost, stronger agentic reliability)
- Gemini 3.8 Flash → **Nova Pro** (-9% cost at the 2026 rate, AWS-native) or **Nova Lite** (-93% cost)
- Gemini 3 Pro → **Llama 4 Maverick** (-63%), **Nova Pro** (+20%)

---

## Volume-Based Recommendations

**Low (<1M tokens/day):** Use best model for quality. Cost difference minimal at this volume.

**Medium (1-10M tokens/day):** Present cost comparison at volume. At 5M input + 2.5M output/day:

| Model            | Monthly Cost   |
| ---------------- | -------------- |
| Gemini 3 Pro     | $300           |
| Llama 4 Maverick | $109 (-64%)    |
| Llama 4 Scout    | $75 (-75%)     |
| Nova Pro         | $360 (+20%)    |
| Claude Sonnet 5  | $1,050 (+250%) |

**High (10-100M tokens/day):** Cost optimization critical. Recommend multi-model tiered approach. Llama 4 Maverick/Scout or Nova for output-heavy workloads.

**Very high (>100M tokens/day):** Mandatory multi-model tiered strategy:

- Simple tasks (60% of traffic) → Nova Micro or Llama 4 Scout
- Moderate tasks (30% of traffic) → Llama 4 Maverick or Nova Pro
- Complex tasks (10% of traffic) → Claude Sonnet 5

---

## Cost Comparison Table (150M input + 75M output per month)

| Gemini Model                    | Monthly | Best Bedrock Match                         | Monthly | Difference |
| ------------------------------- | ------- | ------------------------------------------ | ------- | ---------- |
| Gemini 3.1 Pro Preview ($2/$12) | $1,200  | Claude Sonnet 5 ($2/$10)                   | $1,050  | -13%       |
| Gemini 3.1 Pro Preview ($2/$12) | $1,200  | Claude Opus 5.5 Global ($4/$20)            | $2,100  | +75%       |
| Gemini 3.1 Pro Preview ($2/$12) | $1,200  | Claude Opus 5.5 commercial Geo ($4.40/$22) | $2,310  | +92.5%     |
| Gemini 3.1 Pro Preview ($2/$12) | $1,200  | Nova 2 Pro ($1.38/$11.00)                  | $1,032  | -14%       |
| Gemini 3 Pro ($0.50/$3.00)      | $300    | Llama 4 Maverick ($0.24/$0.97)             | $109    | -64%       |
| Gemini 3 Pro ($0.50/$3.00)      | $300    | Llama 4 Scout ($0.17/$0.66)                | $75     | -75%       |
| Gemini 3.8 Flash ($0.75/$3.75)  | $394    | Nova Pro ($0.80/$3.20)                     | $360    | -9%        |
| Gemini 3.8 Flash ($0.75/$3.75)  | $394    | Nova Lite ($0.06/$0.24)                    | $27     | -93%       |
| Gemini 3.5 Flash-Lite ($0.30/$2.50) | $233 | Nova Lite ($0.06/$0.24)                    | $27     | -88%       |

_For the Opus 5.5 rows, Difference = (Bedrock monthly cost / Gemini monthly cost - 1). Global pricing applies only when worldwide routing is allowed; Geo preserves its supported geography. Costs use identical input/output token volumes, with no assumed token-efficiency discount._

_Gemini 3.8 Flash rows use the rate in effect through Dec 31, 2026; from Jan 1, 2027 its monthly cost at this volume is $788 ($1.50/$7.50). Gemini 2.5 Pro / Flash / Flash-Lite (retired on Vertex AI Oct 20, 2026) and Gemini 2.0 Flash / Flash-Lite (retired Jun 1, 2026) are not current models and do not appear as rows here — see Legacy/Specialized for their mapping rows._

_A customer's own source baseline is priced by serving API and date (lifecycle SSOT § Source-Model Retirements), with a measured bill always taking precedence. At this volume on the Gemini Developer API: 2.5 Flash-Lite ($0.10/$0.40) is $45 per month with no cutoff — Nova Micro ($0.035/$0.14) is $16, −65%; 2.5 Pro ($1.25/$10) is $938 until Dec 1, 2026 — Nova Pro is $360, −62% — and $394 at 3.8 Flash's 2026 rate from Dec 1 ($788 from Jan 1, 2027); 2.5 Flash ($0.30/$2.50) is $233 before and after Dec 1 because 3.5 Flash-Lite bills the same rate. Vertex AI 2.5 workloads and all 2.0 workloads use the replacement rows above._

_Other rows retain their prior comparisons. Positive = Bedrock costs more (Gemini cheaper), negative = Bedrock cheaper._

---

## Prompt Caching (Claude Only)

Cache frequently-used system prompts for 90% cost reduction on cached portions. Example: 10K token system prompt repeated 1000x → $30 without caching, $3 with caching.

Not available on other Bedrock models. This is a significant Claude advantage for applications with heavy system prompt repetition.

---

## Feature Migration Notes

| Gemini Feature                                   | Bedrock Equivalent                                            | Notes                                                                                                                                                                                                                                                                                                            |
| ------------------------------------------------ | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Function calling                                 | Claude tools (excellent), Mistral (good)                      | Minimal changes                                                                                                                                                                                                                                                                                                  |
| Structured output/JSON                           | Claude (excellent), Nova Pro (good)                           | Most models via prompt                                                                                                                                                                                                                                                                                           |
| Streaming                                        | All major models                                              | Same SSE pattern                                                                                                                                                                                                                                                                                                 |
| Vision                                           | Claude Sonnet/Haiku, Llama 4 Maverick                         | Multimodal parity                                                                                                                                                                                                                                                                                                |
| Context caching                                  | Claude prompt caching                                         | Different mechanics, not a drop-in: Gemini uses explicit TTL-based `cachedContent` objects you create/reference by name; Claude uses inline cache-control breakpoints on the request itself. Re-implement the caching call sites, don't just swap endpoints. 90% savings on cached portions once re-implemented. |
| Audio/video input                                | Nova 2 Sonic (speech), Transcribe/Rekognition (preprocessing) | Nova Sonic v1 is Legacy; use Nova 2 Sonic                                                                                                                                                                                                                                                                        |
| Embeddings (text-only)                           | Amazon Titan Embeddings ($0.02/1M, 1536 dims)                 | Must re-embed all docs                                                                                                                                                                                                                                                                                           |
| Embeddings (multimodal — text+image/video/audio) | Amazon Nova Multimodal Embeddings (see pricing table above)   | Do NOT route to the text-only Titan Embeddings row above — Gemini Embedding 2 unifies text+image+video+audio into one model, so detect by call arguments (image/blob content present), not by model name alone. Must re-embed all docs into the new vector space regardless of target.                           |
