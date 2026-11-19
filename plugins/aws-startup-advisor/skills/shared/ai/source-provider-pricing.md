# Source Provider Pricing

> Canonical source-provider list prices (Gemini, OpenAI, Anthropic) for comparing a migration's current cost with Bedrock. Vendored into each consuming skill as `references/vendored/ai/source-provider-pricing.md`; edit here, then run `tools/sync-vendored.py`. gcp-to-aws still carries the same section in its own `references/shared/pricing-cache.md` until it delegates AI work to bedrock-migration-assessment; a test keeps the two identical.

## Source Provider Pricing (for Migration Comparison)

Use alongside Bedrock pricing to calculate migration ROI.

### Gemini (Standard Tier)

Prices per 1M tokens. Source: [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing), verified May 2026; Gemini 3.8 Flash, 3.5 Flash-Lite, and the 2.5 retirement status re-read from the [Gemini Developer API pricing page](https://aistudio.google.com/docs/pricing) on 2026-11-08; the 2.0 Flash / Flash Lite retirement status from the [Vertex AI model versions page](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions) and the [Gemini Developer API deprecations page](https://aistudio.google.com/docs/deprecations), read the same day (their May 2026 prices are kept as historical figures, not refreshed).

| Model                 | Input $/1M | Output $/1M | Context | Tier                                                                                                       |
| --------------------- | ---------- | ----------- | ------- | ---------------------------------------------------------------------------------------------------------- |
| Gemini 4 Argon (Global endpoint / Developer API) | 2.00 | 10.00 | 1M | flagship reasoning (rate through 2026-11-30; **4.00 / 20.00 from 2026-12-01**; no free tier; thinking tokens billed) — Developer API pricing and Vertex AI **Global** endpoint, read 2026-11-09 / 2026-11-10 |
| Gemini 4 Argon (Vertex AI non-global / regional endpoint) | 2.20 | 11.00 | 1M | flagship reasoning (rate through 2026-11-30; **4.40 / 22.00 from 2026-12-01**) — [Vertex AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing) non-global rows, read 2026-11-10. A Vertex AI workload pinned to a Region (data residency, regional endpoint) is billed here, 10% above Global; serving endpoint unknown → present both as labeled alternatives |
| Gemini 3.8 Flash      | 0.75       | 3.75        | 1M      | flagship Flash (rate through 2026-12-31; 1.50 / 7.50 from 2027-01-01)                                      |
| Gemini 3.6 Flash      | 0.75       | 3.75        | 1M      | previous-generation Flash on the Developer API (rate through 2026-12-31; 1.50 / 7.50 from 2027-01-01); **retired on Vertex AI 2026-11-19** → 3.8 Flash |
| Gemini 3.7 Flash      | _unverified_ | _unverified_ | 1M    | Developer API routes `gemini-3.7-flash` to 3.8 Flash (bill at the 3.8 Flash row); Vertex AI retires it 2027-01-28 — no standalone list rate published |
| Gemini 3.5 Flash      | 1.50       | 9.00        | 1M      | **Vertex AI list rate only** (GA until at least 2027-05-19). On the Developer API `gemini-3.5-flash` is removed from AI Studio and routed to 3.6 Flash — bill at the 3.6 Flash row. Serving API unknown → present both as labeled alternatives (Q19b) |
| Gemini 3.1 Pro        | 2.00       | 12.00       | 1M      | flagship                                                                                                   |
| Gemini 3.5 Flash-Lite | 0.30       | 2.50        | 1M      | fast                                                                                                       |
| Gemini 3.1 Flash-Lite | 0.25       | 1.50        | 1M      | budget                                                                                                     |
| Gemini 2.5 Pro        | 1.25       | 10.00       | 1M      | **retired** — Vertex AI 2026-10-20; Developer API shutdown 2026-12-01, then billed at 3.8 Flash rates      |
| Gemini 2.5 Flash      | 0.30       | 2.50        | 1M      | **retired** — Vertex AI 2026-10-20; Developer API shutdown 2026-12-01, then billed at 3.5 Flash-Lite rates |
| Gemini 2.5 Flash-Lite | 0.10       | 0.40        | 1M      | **retired** on Vertex AI 2026-10-20; not deprecated on the Developer API (no shutdown date)                 |
| Gemini 2.0 Flash      | 0.10       | 0.40        | 1M      | **retired** — Vertex AI and Developer API shutdown 2026-06-01; upgrade 3.5 Flash-Lite (Vertex) / 3.6 Flash (Developer API) |
| Gemini 2.0 Flash Lite | 0.075      | 0.30        | 1M      | **retired** — Vertex AI and Developer API shutdown 2026-06-01; upgrade 3.5 Flash-Lite (Vertex) / 3.1 Flash-Lite (Developer API) |

> **Gemini 3.1 Pro breakpoint pricing:** $4.00/$18.00 per 1M for prompts >200k tokens (vs $2.00/$12.00 for ≤200k). Table above uses ≤200k rates.
> **Gemini 3.8 Flash** (GA Sep 2, 2026) is the current Flash model and Google's upgrade for 3.5 / 3.6 / 3.7 Flash and the retired 2.5 Pro / 2.5 Flash. **Gemini 3.5 Flash** is still GA on Vertex AI at $1.50/$9.00 (5x the retired 2.5 Flash), but it has been removed from AI Studio and Developer API requests route to 3.6 Flash at $0.75/$3.75 — price a Developer API customer at the routed rate, a Vertex AI customer at the list price (read 2026-11-09).
> **Gemini 2.5 retirement — which row is the source baseline depends on the serving API and the date.** The 2.5 rows are not current models (never a target or a current-recommendation row), but they are still the price some customers pay today. A measured bill (`current_costs.monthly_ai_spend`, billing CSV, usage profile) always outranks these list prices; when only token volume is known, pick the baseline from Clarify's `ai_constraints.ai_source_serving_api` first; only when it is absent, read `ai-workload-profile.json → models[]` and treat a row as Vertex AI only when its `service` is `vertex_ai_generative` **and** its `detected_via` includes `terraform` or `monitoring` (`vertex_ai_generative` alone is the Gemini category Discover assigns to every Gemini SDK, not a Vertex AI serving signal — a code-only row is `unknown`: compute both figures and label them): **Vertex AI** workloads on any 2.5 model are past the Oct 20, 2026 retirement — estimate against Google's named replacement (3.8 Flash with its 2027-01-01 step, or 3.5 Flash-Lite), never the 2.5 row. **Gemini Developer API** `gemini-2.5-flash-lite` is not deprecated and has no shutdown date — its 0.10 / 0.40 row is the correct baseline, with no forced cutoff (3.5 Flash-Lite's 0.30 / 2.50 would overstate a 150M / 75M workload from $45 to $232.50). **Gemini Developer API** `gemini-2.5-pro` and `gemini-2.5-flash` are billed at their own rows until Dec 1, 2026 (2.5 Pro at 150M / 75M is $937.50, not 3.8 Flash's $393.75); on or after Dec 1, 2026 Google auto-routes them and bills Gemini 3.8 Flash (0.75 / 3.75 through 2026-12-31; 1.50 / 7.50 from 2027-01-01) and Gemini 3.5 Flash-Lite (0.30 / 2.50) respectively — use the routed row from that date. Sources: [Gemini Developer API pricing](https://aistudio.google.com/docs/pricing), [Vertex AI model versions](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions), and [Gemini API deprecations](https://aistudio.google.com/docs/deprecations), all read 2026-11-08.
> **Gemini 2.0 retirement:** the 2.0 Flash and 2.0 Flash Lite rows stay as historical figures so a user already on them can see what they paid. Both shut down on Vertex AI and the Gemini Developer API on Jun 1, 2026 (same two sources, read 2026-11-08); Google names Gemini 3.5 Flash-Lite as the Vertex upgrade and Gemini 3.6 Flash / 3.1 Flash-Lite on the Developer API, with no auto-routing. A workload that still names a 2.0 id is past a hard cutoff on both APIs — map it from the legacy rows and estimate against the replacement's rate (a measured bill, if one exists, still wins). Never use a 2.0 row as the live comparison baseline for a new estimate.

### OpenAI (Standard Tier)

Prices per 1M tokens. GPT-5.5 and GPT-5.5 Pro use the same breakpoint pricing structure as GPT-5.4 at 272K input tokens. GPT-5.4 and GPT-5.4 Pro use **breakpoint pricing** at 272K input tokens: rates below are for <272K context; above 272K, input is 2x and output is 1.5x.

GPT-6 Astra, GPT-6 Sol, GPT-6 Luna, and GPT-6.1 Sol use the same breakpoint shape at 272,000 input
tokens: rows below are the short-context (≤272K) rate; above 272,000 input tokens, the entire
request — input, cache, and output — is repriced at 2x input/cache and 1.5x output (see the
long-context tables in the Bedrock section above, or OpenAI's own GPT-6 pricing page, for the
resulting rates).

> GPT-6 rows above show the ≤272K short-context rate (the Standard-tier default range); 1.05M is
> the model's maximum context window, not the rate's valid range — see the breakpoint note above.
>
> **Tier note — these rows are OpenAI's STANDARD tier.** Bedrock in-region for the same models is priced at OpenAI's
> _data residency_ tier, exactly 1.10x the figures below (see the **OpenAI on Bedrock** section above). So for
> GPT-5.6 Sol / Terra / Luna, GPT-5.5 and GPT-5.4 a same-model move is a ~10% increase, not parity — compute it from
> the Bedrock table, not by assuming these numbers carry over. The rows below are the right source-side baseline for
> a customer on OpenAI standard, and remain the only figures available for models with **no** Bedrock equivalent
> (GPT-5.x Pro, GPT-5.2/5.1, GPT-4.x, o-series).

| Model         | Input $/1M   | Output $/1M  | Context | Tier      |
| ------------- | ------------ | ------------ | ------- | --------- |
| GPT-6 Astra   | 10.00        | 50.00        | ≤272K*  | frontier  |
| GPT-6.1 Sol   | 2.00         | 10.00        | ≤272K*  | flagship  |
| GPT-6.1 Terra | _unverified_ | _unverified_ | 1.05M   | balanced  |
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
| GPT-5.1       | 1.25         | 10.00        | 200K    | flagship — OpenAI shutdown 2027-04-01 → `gpt-6-sol` |
| GPT-5 Mini    | 0.25         | 2.00         | 200K    | fast — OpenAI shutdown 2026-12-11 → `gpt-5.6-terra` |
| GPT-5 Nano    | 0.05         | 0.40         | 128K    | budget — OpenAI shutdown 2026-12-11 → `gpt-5.6-luna` |
| GPT-4.1       | 2.00         | 8.00         | 1M      | flagship — OpenAI shutdown 2027-01-14 → `gpt-6-luna` |
| GPT-4.1 Mini  | 0.40         | 1.60         | 1M      | fast — OpenAI shutdown 2027-01-14 → `gpt-6-luna` |
| GPT-4.1 Nano  | 0.10         | 0.40         | 1M      | **shut down 2026-10-23** on OpenAI → `gpt-5.6-luna` (historical row; see the shutdown note below) |
| GPT-4o        | 2.50         | 10.00        | 128K    | flagship — OpenAI shutdown 2027-01-14 → `gpt-6-luna` |
| o3            | 2.00         | 8.00         | 200K    | reasoning — OpenAI shutdown 2026-12-11 → `gpt-5.6-sol` |
| o4-mini       | 1.10         | 4.40         | 200K    | **shut down 2026-10-23** on OpenAI → `gpt-5.6-terra` (historical row; see the shutdown note below) |

*GPT-6 rows: 1.05M is the model's max window, not this rate's valid range. Requests >272,000 input tokens reprice input/cache 2x and output 1.5x — see the breakpoint note above and pricing-cache.md's long-context tables.

> **OpenAI shutdowns — which row is the source baseline depends on the serving provider and the date** ([OpenAI deprecations](https://developers.openai.com/api/docs/deprecations), read 2026-11-09). A measured bill always wins. For a **direct OpenAI** source with token volume only: before the row's shutdown date, use the row; on or after it, use the **substitute's** source row (`gpt-4.1-nano` → GPT-5.6 Luna 0.20 / 1.20; `o4-mini` → GPT-5.6 Terra, which is `_unverified_` here, so the baseline is **unavailable** — fall to the multi-tier presentation, never the retired row). Already past shutdown (2026-10-23): `o1`, `o1-pro`, `o3-mini`, `o4-mini`, `gpt-4`, `gpt-4-turbo`, `gpt-4.1-nano`, `gpt-3.5-turbo`; `o1-mini` since 2025-10-27. These dates are OpenAI-hosted dates only — an **Azure OpenAI** deployment of the same model follows Microsoft's retirement schedule, so keep the row until that schedule is confirmed.
>
> **GPT-6.1 Terra:** confirm availability, token limits, and pricing with the source provider.
> Use measured/stated source spend or `pricing-fallback.md` when verified source rates are unavailable.
> See `references/vendored/ai/openai-on-bedrock.md` for Bedrock availability and prices.

### Anthropic (Standard Tier, 1P API)

Prices per 1M tokens. Source: [claude.com/pricing](https://claude.com/pricing), verified October 2026.

| Model              | Input $/1M | Output $/1M | Context | Tier     |
| ------------------ | ---------- | ----------- | ------- | -------- |
| Claude Haiku 4.5   | 1.00       | 5.00        | 200K    | fast     |
| Claude Sonnet 4.5  | 3.00       | 15.00       | 200K    | flagship |
| Claude Sonnet 5    | 2.00       | 10.00       | 1M      | flagship |

> These first-party rates match Bedrock's Global/base rate for the same models, and a Bedrock
> `us.`-prefixed Geo inference profile runs about 10% higher (see the Geo vs. Global note in the
> Bedrock Models section).
