# Gemini to Bedrock — Model Selection Guide

**Applies to:** Vertex AI Generative AI (Gemini models) → Amazon Bedrock

This file is loaded by `design-ai.md` when `ai-workload-profile.json` has `summary.ai_source` = `"gemini"` or `"both"`. It provides model mapping tables with pricing and honest competitive analysis for Gemini → Bedrock migration decisions.

Verify all pricing against `references/shared/pricing-cache.md`.

**Model lifecycle:** Before recommending any Bedrock model, check `references/shared/ai-model-lifecycle.md`. Do not recommend Legacy models as primary selections for new migrations. Legacy models are annotated below where they appear.

**Recommend defaults (Sep 2026):** Claude Sonnet 5 (`anthropic.claude-sonnet-5`) for balanced/flagship; Claude Opus 4.8 for hardest reasoning; Claude Haiku 4.5 for cost/speed. Sonnet 5 is **$2/$10** — the launch rate became the standard price on Sep 1, 2026 (the scheduled increase to $3/$15 was cancelled); comparison tables below use $2/$10. Do not default to any Claude Fable / Mythos frontier model.

---

## Competitive Reality (May 2026)

Gemini 3.5 Flash is now GA (May 2026) — the current flagship Flash model. Gemini 3.1 Pro is the current Pro tier. Be honest with users:

- Gemini 3.1 Pro leads 13/16 Google-reported benchmarks and 6/10 on the Artificial Analysis Intelligence Index
- ARC-AGI-2: 77.1%, SWE-Bench: 80.6% (tied with Opus 4.6 at 80.8%)
- Gemini 3.1 Pro costs $2/$12 per 1M tokens — less than half of Opus 4.6 ($5/$25), and slightly above Sonnet 5 ($2/$10, ~13% cheaper blended)
- Gemini 3.5 Flash at $1.50/$9.00 is 5x more expensive than the old Gemini 2.5 Flash ($0.30/$2.50) — the Bedrock cost savings case is now much stronger for Flash-tier users

**Where Bedrock still wins:**

- Claude Sonnet 5 / Opus 4.x lead on real-world agentic tasks (GDPval evaluation) — the gap between benchmarks and production agent reliability is real
- Claude prompt caching (90% savings on repeated content) has no Gemini equivalent
- Claude function calling remains best-in-class for complex multi-turn tool use
- AWS ecosystem integration (AgentCore, Knowledge Bases, Guardrails) has no Gemini equivalent

**Migration case by tier:**

- Gemini 3.5 Flash → Bedrock: **strong cost case** — Nova Lite is 94% cheaper; even Claude Sonnet 5 is close at $2/$10 vs $1.50/$9.00
- Gemini 3.1 Pro → Bedrock: driven by AWS consolidation, agentic reliability, or ecosystem; Sonnet 5 at $2/$10 adds a modest (~13%) cost edge, but the case is not cost-led and not general benchmarks
- Gemini 3.1 Flash-Lite → Nova Lite/Micro: still 76-88% cheaper, strong cost case
- Gemini 2.5 Pro → Bedrock: moderate case (older model)

---

## Bedrock Model Portfolio

| Model            | Best For                                                            | Complexity | Speed  | Context |
| ---------------- | ------------------------------------------------------------------- | ---------- | ------ | ------- |
| Claude Sonnet 5  | Agentic tasks, tool use                                             | High       | High   | 1M      |
| Claude Opus 4.6  | Maximum reasoning                                                   | High       | Medium | 200K    |
| Claude Haiku 4.5 | Simple + fast                                                       | Medium     | High   | 200K    |
| Llama 4 Maverick | Cost-effective + multimodal                                         | Medium     | High   | 1M      |
| Llama 4 Scout    | Ultra-long context, cheapest                                        | Medium     | Medium | 10M     |
| Nova 2 Pro       | AWS flagship, multimodal                                            | High       | High   | 1M      |
| Nova 2 Lite      | AWS mid-tier, long context                                          | Medium     | High   | 1M      |
| Nova Pro         | AWS balanced                                                        | Medium     | High   | 300K    |
| Nova Lite        | AWS fast + cheapest                                                 | Medium     | High   | 300K    |
| Nova Micro       | AWS fastest, text-only                                              | Low        | High   | 128K    |
| Nova Premier     | Complex reasoning — **Legacy** (EOL Sep 14, 2026) prefer Nova 2 Pro | High       | Medium | 1M      |
| DeepSeek-R1      | Chain-of-thought reasoning                                          | High       | Medium | 128K    |
| Mistral Large 3  | EU/Multilingual                                                     | High       | Medium | 256K    |

---

## Gemini → Bedrock Model Mapping

### Gemini Pro Tier

| Gemini Model   | Price (in/out per 1M) | Best Bedrock Match | Bedrock Price  | Winner              |
| -------------- | --------------------- | ------------------ | -------------- | ------------------- |
| Gemini 3.1 Pro | $2.00 / $12.00        | Claude Sonnet 5    | $2.00 / $10.00 | Bedrock 13% cheaper |
| Gemini 3.1 Pro | $2.00 / $12.00        | Claude Opus 4.8    | $5.00 / $25.00 | Gemini 54% cheaper  |
| Gemini 3.1 Pro | $2.00 / $12.00        | Nova 2 Pro         | $1.38 / $11.00 | Bedrock 14% cheaper |
| Gemini 3 Pro   | $0.50 / $3.00         | Llama 4 Maverick   | $0.24 / $0.97  | Bedrock 64% cheaper |
| Gemini 3 Pro   | $0.50 / $3.00         | Llama 4 Scout      | $0.17 / $0.66  | Bedrock 75% cheaper |
| Gemini 3 Pro   | $0.50 / $3.00         | Nova Pro           | $0.80 / $3.20  | Gemini 17% cheaper  |
| Gemini 2.5 Pro | $1.25 / $10.00        | Claude Sonnet 5    | $2.00 / $10.00 | Gemini 11% cheaper  |
| Gemini 2.5 Pro | $1.25 / $10.00        | Nova Pro           | $0.80 / $3.20  | Bedrock 62% cheaper |
| Gemini 2.5 Pro | $1.25 / $10.00        | Nova 2 Pro         | $1.38 / $11.00 | Gemini 9% cheaper   |

> **Gemini 3.1 Pro breakpoint:** $4.00/$18.00 per 1M for prompts >200k tokens. Table above uses ≤200k rates.

### Gemini Flash/Lite Tier

| Gemini Model              | Price (in/out per 1M)                                       | Best Bedrock Match                     | Bedrock Price  | Winner                                                                                                                                                                                                                                                   |
| ------------------------- | ----------------------------------------------------------- | -------------------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Gemini 3.5 Flash (GA)     | $1.50 / $9.00                                               | Nova Lite                              | $0.06 / $0.24  | Bedrock 94% cheaper — strong migration case; 3.5 Flash is 5x more expensive than old 2.5 Flash                                                                                                                                                           |
| Gemini 3.5 Flash (GA)     | $1.50 / $9.00                                               | Claude Sonnet 5                        | $2.00 / $10.00 | Gemini 14% cheaper — but Sonnet leads on agentic reliability                                                                                                                                                                                             |
| Gemini 3.1 Flash-Lite     | $0.25 / $1.50                                               | Nova Lite                              | $0.06 / $0.24  | Bedrock 76% cheaper                                                                                                                                                                                                                                      |
| Gemini 3.1 Flash-Lite     | $0.25 / $1.50                                               | Nova Micro                             | $0.035 / $0.14 | Bedrock 88% cheaper                                                                                                                                                                                                                                      |
| Gemini 2.5 Flash          | $0.30 / $2.50                                               | Nova Lite                              | $0.06 / $0.24  | Bedrock 88% cheaper                                                                                                                                                                                                                                      |
| Gemini 2.5 Flash Thinking | $0.30 / $0.60–$3.50 (varies by thinking budget)             | Claude Sonnet 5 with extended thinking | $2.00 / $10.00 | Gemini is cheaper at the listed rates: even at $3.50/M output, its 2:1 blended rate is ~$1.37/M vs ~$4.67/M for Sonnet 5 (~71% lower). Consider Sonnet 5 for capability requirements, not expected savings; profile each model's billed thinking tokens. |
| Gemini 2.0 Flash          | $0.10 / $0.40                                               | Nova Micro                             | $0.035 / $0.14 | Bedrock 65% cheaper                                                                                                                                                                                                                                      |
| Gemini Flash 1.5          | **Legacy — EOL Sep 24, 2025. Migrate to Gemini 3.5 Flash.** | Nova Lite                              | $0.06 / $0.24  | If still in use, migrate source model first; strong Bedrock cost case once on 3.5 Flash                                                                                                                                                                  |

### Legacy/Specialized

| Gemini Model                                                 | Price (in/out per 1M)                                                         | Best Bedrock Match                | Bedrock Price                                                                               | Winner                                                                    |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Gemini 1.5 Pro                                               | **Legacy — EOL Sep 24, 2025. Migrate to Gemini 2.5 Pro or 3.x Pro.**          | Claude Sonnet 5                   | $2.00 / $10.00                                                                              | If still in use, migrate source model first                               |
| text-bison / chat-bison                                      | Legacy                                                                        | Llama 4 Scout                     | $0.17 / $0.66                                                                               | Bedrock (better quality + cheaper)                                        |
| text-embedding-004                                           | $0.025 / N/A                                                                  | Titan Embeddings V2               | $0.02 / N/A                                                                                 | Bedrock 20% cheaper                                                       |
| Gemini Embedding 2 (multimodal — text/image/video/audio/PDF) | text $0.20/1M, image $0.45/1M ($0.00012/img), audio $6.50/1M, video $12.00/1M | Amazon Nova Multimodal Embeddings | text $0.135/1M, image $0.00006/unit (see `shared/pricing-cache.md` § Multimodal embeddings) | Bedrock ~32% cheaper on text, ~50% cheaper on image                       |
| imagen-*                                                     | Varies                                                                        | Stable Image Core                 | $0.04/img                                                                                   | Nova Canvas excluded (EOL Sep 30, 2026); Ultra $0.08/img if quality-first |

_Percentages are blended savings using a 2:1 input-to-output token ratio. Actual savings depend on your input/output ratio._

---

## Decision Paths by Priority

### Quality-First

Gemini 3.1 Pro Preview matches or beats Opus 4.6 on most reasoning benchmarks at less than half the cost. Be transparent:

- If user needs **general reasoning/coding quality** → Gemini 3.1 Pro is competitive or better. Migration case is weak unless driven by AWS consolidation.
- If user needs **agentic reliability** (real-world multi-step tasks) → **Claude Sonnet 5** still leads on GDPval. This is the honest differentiator.
- If user needs **maximum reasoning on hardest problems** → **Claude Opus 4.8** ($5/$25 headline on-demand, same tier as Opus 4.6) — use the latest [Claude on Bedrock](https://aws.amazon.com/bedrock/pricing/) model card for benchmark deltas vs Gemini; Opus 4.6 remains a same-price alternative where batch or regional availability matters.

### Speed-First

Gemini Flash → **Nova Micro** (<200ms, text-only, cheapest), **Haiku 4.5** (<400ms, vision), or **Llama 4 Scout** (<300ms, cheapest capable)

### Cost-First

- Gemini Flash/Lite → **Nova Lite** (54-88% cheaper), **Nova Micro** (53-64% cheaper)
- Gemini Pro → **Llama 4 Maverick** ($0.24/$0.97, 63% cheaper than Gemini 3 Pro) or **Llama 4 Scout** ($0.17/$0.66, 75% cheaper)

### Balanced

- Gemini 3.1 Pro → **Nova 2 Pro** (-14% cost, AWS-native) or **Claude Sonnet 5** (-13% cost, stronger agentic reliability)
- Gemini 2.5 Pro → **Nova 2 Pro** (+10% cost, AWS-native) or **Nova Pro** (-62% cost)
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

| Gemini Model                    | Monthly | Best Bedrock Match             | Monthly | Difference |
| ------------------------------- | ------- | ------------------------------ | ------- | ---------- |
| Gemini 3.1 Pro Preview ($2/$12) | $1,200  | Claude Sonnet 5 ($2/$10)       | $1,050  | -13%       |
| Gemini 3.1 Pro Preview ($2/$12) | $1,200  | Claude Opus 4.8 ($5/$25)       | $2,625  | +54%       |
| Gemini 3.1 Pro Preview ($2/$12) | $1,200  | Nova 2 Pro ($1.38/$11.00)      | $1,032  | -14%       |
| Gemini 3 Pro ($0.50/$3.00)      | $300    | Llama 4 Maverick ($0.24/$0.97) | $109    | -64%       |
| Gemini 3 Pro ($0.50/$3.00)      | $300    | Llama 4 Scout ($0.17/$0.66)    | $75     | -75%       |
| Gemini 2.5 Pro ($1.25/$10)      | $938    | Nova 2 Pro ($1.38/$11.00)      | $1,032  | +9%        |
| Gemini 2.5 Pro ($1.25/$10)      | $938    | Nova Pro ($0.80/$3.20)         | $360    | -62%       |
| Gemini 2.5 Flash ($0.30/$2.50)  | $233    | Nova Lite ($0.06/$0.24)        | $27     | -88%       |
| Gemini 2.0 Flash ($0.10/$0.40)  | $45     | Nova Micro ($0.035/$0.14)      | $16     | -64%       |

_Difference column shows blended savings at a 2:1 input/output token ratio. Positive = Bedrock costs more (Gemini cheaper), negative = Bedrock cheaper._

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
