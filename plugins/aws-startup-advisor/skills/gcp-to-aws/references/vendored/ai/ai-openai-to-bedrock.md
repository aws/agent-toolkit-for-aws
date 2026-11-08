# OpenAI to Bedrock — Model Selection Guide

> Canonical OpenAI-compatible → Bedrock model-selection guide. Source-cloud
> agnostic: it serves direct OpenAI API usage, Azure OpenAI, and any other
> OpenAI-protocol endpoint, because the Bedrock target does not depend on which
> endpoint served the calls.
> Vendored into each consuming skill as
> `references/vendored/ai/ai-openai-to-bedrock.md` and kept byte-identical by
> `shared:check`; edit HERE, then run `shared:sync`.

**Applies to:** OpenAI SDK usage detected in applications hosted on any source cloud → Amazon Bedrock

This file is loaded by `design-ai.md` when `ai-workload-profile.json` has `summary.ai_source` = `"openai"` or
`"both"`. It provides the selection policy and mapping tables for OpenAI → Bedrock migration decisions.

**Facts live in `references/shared/openai-on-bedrock.md`** — model IDs, endpoint paths, region matrix, quotas, prompt
caching rules, and pricing provenance. Read it before applying this file. Do not restate those facts here.

**Model lifecycle:** before recommending any Bedrock model, check `references/vendored/ai/ai-model-lifecycle.md`. Do not
recommend Legacy models as primary selections for new migrations.

**Recommend defaults (Sep 2026):** Claude Sonnet 5 (`anthropic.claude-sonnet-5`) for balanced/flagship; Claude Opus 5.5 for demanding reasoning (20% lower standard input/output token prices than Opus 5; [Anthropic reports improved token efficiency](https://claude.com/blog/what-a-task-costs-on-opus-5-5), with actual usage varying by task and effort setting); Claude Haiku 5.5 for cost/speed. Sonnet 5 is **$2/$10** — the launch rate became the standard price on Sep 1, 2026 (the scheduled increase to $3/$15 was cancelled); comparison tables below use $2/$10. Do not default to any Claude Fable / Mythos frontier model.

**Sonnet 5.5 release (2026-09-28):** [Claude Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview) is a separate model. Its Amazon Bedrock ID is `anthropic.claude-sonnet-5-5`; `claude-sonnet-5-5` is the Claude API / Claude Platform on AWS ID. The defaults, mapping tables, and cached prices in this guide still describe Sonnet 5. Do not relabel those records or promote 5.5 from the release announcement alone; a 5.5 recommendation needs its own model/path, lifecycle, pricing, and compatibility evidence.

For an explicitly requested 5.5 assessment, read its [Bedrock model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html) and [migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide). Turning off up-front thinking uses `thinking: {"type": "between_tools"}` at `high` effort or below; forced `tool_choice` values `any` and `tool` are rejected, and thinking-history reuse has model/conversation constraints. These are model-specific requirements, not a client-only ID swap. The `computer_20251124` removal applies to the Claude API and Google Cloud; Bedrock still accepts that tool.

---

## Key Insight: OpenAI's Own Models Run on Bedrock

**The old premise of this guide — "OpenAI models are unavailable on AWS, so migrating means switching model families"
— is obsolete.** GPT-6 Astra, GPT-5.6 Sol / Terra / Luna, GPT-5.5, and GPT-5.4 are generally available on Bedrock,
counting toward existing AWS commitments. Pricing depends on the model and inference option;
see `shared/openai-on-bedrock.md`.

Two consequences that invert the previous decision logic:

1. **When the source model is on Bedrock, keep it.** A same-model move has no behavior delta to validate, no prompt
   re-engineering, and no eval regression risk — the migration is an endpoint and credential change, not a model
   change. This is the default recommendation.
2. **The cost of a same-model move depends on the inference option — state it conditionally.** GPT-5.6 In-Region and Geo
   CRIS are priced at OpenAI's _data residency_ tier, exactly 1.10x the standard list price, so those moves cost
   ~10% more. **GPT-5.6 on Global CRIS is priced at the standard list price — cost parity** — available only when
   the workload has no data-residency constraint. GPT-5.5 / GPT-5.4 also have `us.`/`global.` CRIS ids on
   `bedrock-runtime`, but their model cards (read 2026-11-07) publish **commercial In-Region prices only**
   ("Commercial In-Region prices include a 10% fee over OpenAI rates") — nothing on either card establishes a
   Geo or Global CRIS price. So the verified ~10% premium for GPT-5.5 / GPT-5.4 is scoped to the commercial
   In-Region (mantle) option. For a GPT-5.5 / GPT-5.4 CRIS plan, either source the Geo/Global rate separately
   (the card's inference-option table or [aws.amazon.com/bedrock/pricing](https://aws.amazon.com/bedrock/pricing/),
   with URL and read date) or report the comparison unavailable; an In-Region rate used as a proxy is an
   **unverified planning assumption**, labelled as such, and yields no verified premium or savings percentage.
   Never report parity for them. See `shared/openai-on-bedrock.md`. The non-cost case — AWS commitments, IAM/VPC/CloudTrail governance, residency,
   prompt caching, one vendor relationship — carries the in-region path; never present that path as free or neutral.
   For Astra, use its separately dated Bedrock rates and verify the source provider's rate before comparing.

Cross-family mapping (to Claude / Nova / DeepSeek) is still the right answer in two situations: the source model has
no Bedrock equivalent, or the user's priority is cost and is willing to accept a model change to get it. Both are
covered below — but neither is the default.

---

## Selection Policy

Apply in order. Stop at the first tier that resolves.

### Tier 0 — Source model is on Bedrock (default path)

If the detected model is GPT-6 Astra, GPT-6 Sol, GPT-6 Luna, GPT-6.1 Sol, GPT-6.1 Terra, GPT-5.6 Sol / Terra / Luna, GPT-5.5, or
GPT-5.4, the target is **the same model on Bedrock**.

| Source model  | Bedrock target | Model ID (mantle / runtime CRIS)                        | Assessment                                                      |
| ------------- | -------------- | ------------------------------------------------------- | --------------------------------------------------------------- |
| GPT-6 Astra   | GPT-6 Astra    | `openai.gpt-6-astra` / `us.` `global.` prefixed         | `strong_migrate` after the Astra region/API gate in `shared/openai-on-bedrock.md`; price the chosen inference option |
| GPT-6 Sol     | GPT-6 Sol      | `openai.gpt-6-sol` / `us.` `global.` prefixed           | `strong_migrate` — same model; parity on Global CRIS, else +10% |
| GPT-6 Luna    | GPT-6 Luna     | `openai.gpt-6-luna` / `us.` `global.` prefixed          | `strong_migrate` — same model; parity on Global CRIS, else +10% |
| GPT-6.1 Sol   | GPT-6.1 Sol    | `openai.gpt-6.1-sol` / `us.` `global.` prefixed         | `strong_migrate` — same model; parity on Global CRIS, else +10% |
| GPT-6.1 Terra | GPT-6.1 Terra  | `openai.gpt-6.1-terra` / `us.` `global.` prefixed       | `strong_migrate` after the model-specific region/API gate; compare against measured source spend or verified source rates |
| GPT-5.6 Sol   | GPT-5.6 Sol    | `openai.gpt-5.6-sol` / `us.` `global.` prefixed         | `strong_migrate` — same model; parity on Global CRIS, else +10% |
| GPT-5.6 Terra | GPT-5.6 Terra  | `openai.gpt-5.6-terra` / `us.` `in.` `global.` prefixed | `strong_migrate` — same model; parity on Global CRIS, else +10% |
| GPT-5.6 Luna  | GPT-5.6 Luna   | `openai.gpt-5.6-luna` / `us.` `in.` `global.` prefixed  | `strong_migrate` — same model; parity on Global CRIS, else +10% |
| GPT-5.5       | GPT-5.5        | `openai.gpt-5.5` / `us.` `global.` prefixed             | `strong_migrate` — same model; ~10% over OpenAI std In-Region only (no Geo/Global price published) |
| GPT-5.4       | GPT-5.4        | `openai.gpt-5.4` / `us.` `global.` prefixed             | `strong_migrate` — same model; ~10% over OpenAI std In-Region only (no Geo/Global price published) |

Then apply the **region gate** below. Record `model_change: false` and the chosen path in
`aws-design-ai.json` → `ai_architecture.code_migration`. **The default for every Tier 0 target is
`migration_path: "runtime_openai_cris"`** — the same model served via `bedrock-runtime` with a CRIS
id (`us.`/`in.`/`global.` for GPT-5.6 Terra and Luna; `us.`/`global.` only for GPT-5.6 Sol, GPT-6,
GPT-5.5 and GPT-5.4) — with
`bedrock_models[].required_client_api` set to the API the source app already calls (`responses` or
`chat_completions`; `converse` only when a Converse-only feature such as Guardrails is required).
Amazon Bedrock recommends `bedrock-runtime` for new applications
(`references/vendored/ai/bedrock-endpoint-policy.md`). Record `migration_path: "mantle_openai_chat"`
(Chat Completions source on a model whose card lists it on mantle — GPT-6, GPT-5.5, GPT-5.4) or
`"mantle_openai_responses"` **only** when the row also records a `bedrock_models[].mantle_selector`
from `references/vendored/ai/bedrock-endpoint-policy.md` (the selector enum is defined there and
only there). API continuity alone never selects Mantle.

Report the assessment honestly: `strong_migrate` here means "low-risk, well-supported move", not "cheaper".

### Region gate (applies to every Tier 0 selection — endpoint-aware)

The gate differs by family (see `shared/openai-on-bedrock.md` § Regional Availability):

**GPT-6 Astra:** apply its own mantle and runtime matrices from the canonical catalog. For strict
in-region residency, the mantle region must match. Otherwise offer a supported runtime CRIS path
with explicit routing consent; a Global-only caller region cannot satisfy a Geo-only requirement.
If neither path meets the constraints, offer a supported region or a model change under Tier 1.
Do not assume GPT-5.6's broader regional footprint applies to Astra.
**GPT-6 Astra / Sol / Luna / 6.1 Sol / 6.1 Terra:** same shape as GPT-5.6 — if the target region is in the mantle in-region
matrix (narrower than GPT-5.6's: us-east-1 + us-west-2 for Astra only, us-east-1 only for Sol/Luna/6.1 Sol/6.1 Terra — see
`openai-on-bedrock.md` § Regional Availability), both endpoints work and the `bedrock-runtime` CRIS path
(`us.`/`global.` prefixed) is chosen unless a `mantle_selector` applies; outside that matrix the same CRIS path
covers broad commercial regions. GPT-6 Astra's CRIS path additionally lacks `Invoke`
support (Responses/Chat Completions/Converse only) — verify per-feature before assuming parity with Sol/Luna/6.1
Sol.

**GPT-5.6 Sol / Terra / Luna:** rarely blocked. The `bedrock-runtime` CRIS path (Geo `us.` — plus `in.` for Terra
and Luna only — and Global `global.`) covers most commercial regions and is the default whether or not the target region is also in the
mantle in-region matrix — state the data-residency implication of cross-region routing (Geo stays within the
geography; Global routes anywhere and is the cost-parity option). A workload that requires strictly in-region
processing in a region inside the mantle matrix records `mantle_selector: "in_region_processing"` and takes the
Mantle path; one that requires it in a region outside the mantle matrix falls through to Tier 1.

**GPT-5.5 / GPT-5.4:** same shape as GPT-5.6, with a narrower mantle matrix (GPT-5.5: us-east-1, us-east-2;
GPT-5.4: us-east-1, us-east-2, us-west-2, us-gov-west-1 — per their model cards, read 2026-11-06). The
`bedrock-runtime` CRIS path (`us.openai.gpt-5.5` / `global.openai.gpt-5.5`, `us.openai.gpt-5.4` /
`global.openai.gpt-5.4`) is the default, with the same data-residency caveat as GPT-5.6 (Geo stays within the
geography, Global routes anywhere). There is no runtime in-region form. Strict in-region processing inside the
mantle matrix is a valid `in_region_processing` selector for the Mantle path. Only a workload that requires
strictly in-region processing in a region outside the mantle matrix falls through:

1. Prefer offering a **region change** to a supported mantle region (recorded with
   `mantle_selector: "in_region_processing"`), if no data-residency constraint pins the workload. This preserves
   the zero-behavior-delta benefit, which is the whole point of Tier 0.
2. Otherwise fall through to Tier 1 and say why explicitly — a region constraint, not a model judgment.

Record the outcome in `regional_warnings[]`.

### Tier 1 — Source model is not on Bedrock (present two options, do not pre-pick)

Applies to GPT-4o, GPT-4.1, GPT-4 / GPT-4 Turbo, GPT-3.5 Turbo, the o-series, GPT-5 / 5.1 / 5.2, and all `*-Pro`
and `*-Mini` / `*-Nano` variants — none of which are on Bedrock.

There is no same-model target, so a model change is unavoidable. **Present both options with their trade-offs and
let the user choose.** Do not silently default to either.

| Option                              | What it means                                           | Trade-off                                                                                          |
| ----------------------------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **A) Stay with OpenAI, newer tier** | Move to the nearest GPT tier on Bedrock (table below)   | Same vendor, same prompt idioms and tool-calling semantics; still a generation change needing eval |
| **B) Cross-family**                 | Move to Claude / Nova / DeepSeek (tables further below) | Often materially cheaper; different prompt behavior, so budget for prompt work and eval            |

Option A tier mapping:

| Source tier                                              | Bedrock GPT target                                     |
| -------------------------------------------------------- | ------------------------------------------------------ |
| Flagship reasoning (o1-pro, o3-pro, GPT-5 Pro, `*-Pro`)  | GPT-6 Astra; GPT-5.6 Sol as the lower-cost alternative |
| Flagship general (GPT-4o, GPT-4.1, GPT-5/5.1/5.2, GPT-4) | GPT-5.6 Terra                                          |
| Mid / reasoning (o1, o3, o4-mini)                        | GPT-5.6 Terra                                          |
| Fast / cheap (`*-mini`, `*-nano`, GPT-3.5 Turbo)         | GPT-5.6 Luna                                           |

Option A is subject to the same region gate as Tier 0.

Astra is the capability-first choice for this reasoning tier, not a mandatory upgrade for an
existing Bedrock model. At the recorded rates it costs 2.5x Sol for the same inference option and
context tier; evaluate quality and cost before choosing between them.

### Tier 2 — Cost priority override

If `ai_constraints.ai_priority == "cost"`, present the cheapest adequate Bedrock target **as an explicit
alternative alongside** the Tier 0 / Tier 1 recommendation — not as a replacement for it. The user asked for a
migration, and swapping model families is a bigger change than they may have signed up for; make the trade visible
rather than deciding for them.

See "Cost-optimized cross-family alternatives" below for the numbers.

---

For a Haiku 5.5 target, apply the request, inference-profile, and tokenizer requirements in `references/vendored/ai/ai-anthropic-to-bedrock.md` (Haiku 5.5 target contract).

## Cost-Optimized Cross-Family Alternatives

All figures per 1M tokens. Percentages are blended savings at a 2:1 input-to-output ratio. **Both sides of these
comparisons are now Bedrock prices** where the OpenAI model is on Bedrock — this is a Bedrock-vs-Bedrock model
choice, not a provider comparison. Verify rates via `references/vendored/ai/bedrock-pricing-cache.md` — pricing is cache-only, so a
GPT-5.x rate that is absent or `_unverified_` in the cache has no live lookup to fall back to and must be
reported as unavailable rather than priced (see `shared/openai-on-bedrock.md`).

### Against Tier 0 models (same-model baseline vs cross-family)

> Claude Sonnet 5 rows use $2/$10 — the launch rate, made the standard price on Sep 1, 2026 (the scheduled
> increase to $3/$15 was cancelled). Earlier revisions priced Sonnet 5 at $3/$15, which overstated it by a third
> and put several comparisons below on the wrong side.
>
> GPT-5.6 Sol rows use $4.40/$22.00 in-region — 1.10x the $4/$20 standard rate set by the Aug 21, 2026
> reduction, which AWS lists as promotional through at least Nov 21, 2026. The pre-reduction in-region
> rate was $5.50/$33.00; GPT-5.5 keeps that rate.

| Bedrock GPT baseline | Price        | Cross-family alternative | Price        | Delta                  |
| -------------------- | ------------ | ------------------------ | ------------ | ---------------------- |
| GPT-5.6 Sol          | 4.40 / 22.00 | Claude Opus 5.5 (Geo)    | 4.40 / 22.00 | Same token price       |
| GPT-5.6 Terra        | 2.20 / 13.20 | Claude Sonnet 5          | 2.00 / 10.00 | Sonnet 20% cheaper     |
| GPT-5.5              | 5.50 / 33.00 | Claude Sonnet 5          | 2.00 / 10.00 | Sonnet 68% cheaper     |
| GPT-5.5              | 5.50 / 33.00 | Claude Opus 5.5 (Geo)    | 4.40 / 22.00 | Opus 30% cheaper       |
| GPT-5.4              | 2.75 / 16.50 | Claude Sonnet 5          | 2.00 / 10.00 | Sonnet 36% cheaper     |
| GPT-5.6 Luna         | 0.22 / 1.32  | Claude Haiku 5.5 (US Geo; prompt ≤100K) | 0.11 / 0.55 | **Haiku 56.25% cheaper** |
| GPT-5.6 Luna         | 0.22 / 1.32  | Claude Haiku 5.5 (US Geo; prompt >100K) | 0.55 / 2.75 | **Luna 54.29% cheaper** |
| GPT-5.6 Luna         | 0.22 / 1.32  | Nova Lite                | 0.06 / 0.24  | Nova Lite 80% cheaper  |
| GPT-5.6 Luna         | 0.22 / 1.32  | Nova Micro               | 0.035 / 0.14 | Nova Micro 88% cheaper |

Findings worth surfacing to users:

- **GPT-5.6 Sol and Opus 5.5 have the same listed commercial Geo input/output price.** The table compares
  Opus 5.5 Geo pricing with the GPT in-region baseline. Opus 5.5 Global is $4/$20 only when worldwide
  routing is permitted. Compare actual token usage, capabilities, and the selected inference option;
  do not infer a cost advantage from the model name alone.
- **Haiku 5.5 vs. Luna depends on prompt size and inference option.** The rows compare Luna in-region with Haiku US Geo at equal billed token volumes and a 2:1 input/output ratio. Luna prompts stay within its 272K short-context tier; Haiku has its own 100K boundary. Haiku Global is $0.10/$0.50 up to 100K and $0.50/$2.50 above 100K, only when worldwide routing is allowed. A >100K Haiku prompt reprices the whole request, including output and cache tokens. Recount each model's tokens and include thinking/cache usage before claiming workload savings. If request sizes are unknown, present both Haiku tiers rather than choosing one.
- **Sonnet 5's now-permanent $2/$10 undercuts every same-family GPT tier except Luna.** It is ~20% cheaper than
  GPT-5.6 Terra and ~36% cheaper than GPT-5.4 blended; earlier revisions of this guide called Terra 19% cheaper and
  GPT-5.4 near parity on the cancelled $3/$15 rate. Cost now favors the cross-family move for Terra/GPT-5.4-class
  workloads — but it is still a model change; keep the same-model path as the default and present this as the
  cost alternative.
- **Context thresholds are model-specific.** Above 272K GPT input tokens, re-run the comparison at the GPT-5.6 long-context tier (2.0x input, 1.5x output). Haiku 5.5 already enters its higher tier above 100K input tokens. Apply both boundaries independently; do not assume a cross-family saving.

### Sources with no Bedrock equivalent (cross-family reference)

Used for Tier 1 Option B. Source prices are OpenAI's own; Bedrock prices are the target.

| OpenAI Model                | Source price    | Cross-family target  | Bedrock price | Delta                                    |
| --------------------------- | --------------- | -------------------- | ------------- | ---------------------------------------- |
| GPT-5.5 Pro                 | 30.00 / 180.00  | Nova 2 Pro (Preview) | 1.375 / 11.00 | Bedrock 94% cheaper                      |
| GPT-5.4 Pro                 | 30.00 / 180.00  | Nova 2 Pro (Preview) | 1.375 / 11.00 | Bedrock 94% cheaper                      |
| GPT-5.2 Pro                 | 21.00 / 168.00  | Nova 2 Pro (Preview) | 1.375 / 11.00 | Bedrock 93% cheaper                      |
| GPT-5 Pro                   | 15.00 / 120.00  | Nova 2 Pro (Preview) | 1.375 / 11.00 | Bedrock 91% cheaper                      |
| o1-pro                      | 150.00 / 600.00 | Nova 2 Pro (Preview) | 1.375 / 11.00 | Bedrock 98% cheaper                      |
| o3-pro                      | 20.00 / 80.00   | Nova 2 Pro (Preview) | 1.375 / 11.00 | Bedrock 89% cheaper                      |
| o1                          | 15.00 / 60.00   | Nova 2 Pro (Preview) | 1.375 / 11.00 | Bedrock 85% cheaper                      |
| o3                          | 2.00 / 8.00     | DeepSeek-R1          | 1.35 / 5.40   | Bedrock 32% cheaper                      |
| o4-mini / o3-mini / o1-mini | 1.10 / 4.40     | GPT-5.6 Luna         | 0.22 / 1.32   | Bedrock 73% cheaper                      |
| GPT-5.2                     | 1.75 / 14.00    | Claude Sonnet 5      | 2.00 / 10.00  | Bedrock 20% cheaper                      |
| GPT-5.1 / GPT-5             | 1.25 / 10.00    | Claude Sonnet 5      | 2.00 / 10.00  | Source 11% cheaper                       |
| GPT-5 Mini                  | 0.25 / 2.00     | Nova Lite            | 0.06 / 0.24   | Bedrock 86% cheaper                      |
| GPT-5 Nano                  | 0.05 / 0.40     | Nova Micro           | 0.035 / 0.14  | Bedrock 58% cheaper                      |
| GPT-4.1                     | 2.00 / 8.00     | Claude Sonnet 5      | 2.00 / 10.00  | Source 14% cheaper                       |
| GPT-4.1 Mini                | 0.40 / 1.60     | Nova Lite            | 0.06 / 0.24   | Bedrock 85% cheaper                      |
| GPT-4.1 Nano                | 0.10 / 0.40     | Nova Micro           | 0.035 / 0.14  | Bedrock 65% cheaper                      |
| GPT-4o                      | 2.50 / 10.00    | Claude Sonnet 5      | 2.00 / 10.00  | Bedrock 7% cheaper; OpenAI deprecated GPT-4o on 2026-10-14 (shutdown 2027-01-14) and names `gpt-6-luna` as the replacement ([OpenAI deprecations](https://developers.openai.com/api/docs/deprecations), verified 2026-10-26); GPT-6 Luna is Active on Bedrock as `openai.gpt-6-luna` ([model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-luna.html)) |
| GPT-4o Mini                 | 0.15 / 0.60     | Nova Lite            | 0.06 / 0.24   | Bedrock 60% cheaper                      |
| GPT-4 Turbo                 | 10.00 / 30.00   | Claude Sonnet 5      | 2.00 / 10.00  | Bedrock 72% cheaper                      |
| GPT-4                       | 30.00 / 60.00   | Claude Sonnet 5      | 2.00 / 10.00  | Bedrock 88% cheaper                      |
| GPT-3.5 Turbo               | 0.50 / 1.50     | GPT-5.6 Luna         | 0.22 / 1.32   | Bedrock 30% cheaper + far better quality |

For the rows where the source is still cheaper (GPT-5.1/5, GPT-4.1), note that these models are on a
vendor deprecation path anyway; Option A (GPT-5.6 on Bedrock) is usually the better framing than defending a stale
model on price.

### Open-weight gpt-oss

`openai.gpt-oss-120b` (0.15 / 0.60) and `openai.gpt-oss-20b` (0.07 / 0.30) remain available and support
`bedrock-runtime` / Converse with a bare model ID (no CRIS profile needed) and `Invoke`, which the proprietary GPT
models do not. They sit a capability class below the GPT-5.x frontier tier. Recommend them when the user wants
OpenAI-architecture models on the Bedrock-native runtime surface (for Guardrails, invocation logging, or
Converse-based tooling) at the lowest price rather than through mantle.

---

## Migration Decision Framework

**Migrate to Bedrock, same model (Tier 0), if:** the source is GPT-6 Astra / GPT-5.6 / 5.5 / 5.4 and the selected endpoint, API, and region support it.
This is the common case and needs no cost justification.

**Migrate to Bedrock, model change (Tier 1/2), if:**

- The source model is not on Bedrock (see the region and catalog lists in `shared/openai-on-bedrock.md`)
- The user's priority is cost and they accept a model change — note that the cheapest option is often Nova, and that
  Haiku 5.5 can be cheaper below its 100K prompt boundary while Luna can be cheaper above it; compare the selected profiles and each model's billed token counts
- Required features cannot be served by a supported same-model path. Astra / GPT-5.6 have runtime CRIS
  options for applicable governance features; check their capability matrix before proposing a model change

**Consider staying on OpenAI's own API only if:**

- The target region is fixed and carries no suitable model, and a model change is unacceptable
- The workload needs the **Realtime API** — no Bedrock equivalent
- The workload uses **GPT-5.5's native audio/video (omnimodal) input** in ways the Bedrock deployment cannot
  serve — Claude on Bedrock is text+image only, and the mantle GPT path should be probed for the specific
  modality before committing
- The workload depends on **gpt-image**, **Whisper**, **TTS**, or **OpenAI embeddings** — these map to other AWS
  services (Stability AI, Transcribe, Polly, Titan Embeddings), not to an OpenAI model on Bedrock
- The workload uses **Assistants API with file search, vector stores, or code interpreter** — see the decision tree
  below
- Chat Completions cannot be reshaped to Responses and probing confirms Chat Completions is unsupported

**Cost belongs on that list, modestly.** Bedrock in-region runs ~10% above OpenAI's standard tier, so a
cost-only decision genuinely favours staying. Say so; then weigh it against commitments, governance, and residency
rather than dismissing it. For a long-context (>272K) workload the gap is much wider — the 1M tier is 2.0x input and
1.5x output — so profile the context distribution before concluding.

---

## Feature Migration

| OpenAI Feature                             | Bedrock Equivalent                                          | Notes                                                                                                |
| ------------------------------------------ | ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| OpenAI SDK (direct)                        | Same model on `bedrock-runtime` `/openai/v1` (CRIS id)      | Base URL + credential + model ID change; see `shared/openai-on-bedrock.md` for the `/openai/v1` path; Mantle only with a `mantle_selector` |
| Responses API                              | Runtime Responses API (`/openai/v1/responses`)              | Closest to a drop-in; always synchronous on runtime (`background=true` needs a Mantle selector)     |
| Chat Completions                           | Preserve supported Chat when selected                       | Reshape only for a selected API change; verify the model and endpoint                                                     |
| Function calling                           | Supported on GPT-5.x via runtime or mantle; Claude tools via Converse | Same-model keeps tool semantics identical; server-side tools are Mantle-only                |
| Reasoning effort                           | `reasoning={"effort": ...}` on either endpoint              | `none` / `low` / `medium` / `high` / `xhigh` / `max`                                                 |
| Prompt caching                             | GPT-5.6 (90% off cached input); GPT-5.5 / 5.4 implicit caching on `bedrock-runtime` Responses only | GPT-5.5 / 5.4 cards (read 2026-11-06) list a cache-read rate and implicit caching on runtime, none on mantle; Claude has its own caching |
| Streaming                                  | Supported                                                   | Verify per surface                                                                                   |
| Vision                                     | GPT-5.x (image input) or Claude / Llama 4                   | Same-model preserves behavior                                                                        |
| JSON mode                                  | Claude (excellent), Nova Pro (good)                         | Most models via prompt                                                                               |
| Embeddings (ada-002, `text-embedding-3-*`) | Titan Embeddings v2                                         | No OpenAI embedding model on Bedrock; must re-embed all documents                                    |
| DALL-E / gpt-image                         | Stability AI                                                | Nova Canvas v1 is past EOL (2026-09-30); see `ai-model-lifecycle.md`                                 |
| Whisper (STT)                              | Amazon Transcribe                                           | Different service, API, and pricing model                                                            |
| TTS                                        | Amazon Polly / Nova 2 Sonic                                 | Different pricing model                                                                              |
| Assistants API                             | See decision tree below                                     | Path depends on which features are used                                                              |
| Realtime API                               | No equivalent                                               | Stay on OpenAI for this                                                                              |
| Codex                                      | Not verified on Bedrock — see `shared/openai-on-bedrock.md` | Do not price; re-check the OpenAI model card index first                                             |
| Guardrails / KB / invocation logging       | `bedrock-runtime` CRIS path (Guardrails via Converse; logging on every runtime API); KB needs a Bedrock-native model or gpt-oss | None of these are available through the mantle GPT path                                  |

---

## Common Migration Paths

### Same model on Bedrock (Tier 0) — `bedrock-runtime` by default

The application keeps the OpenAI SDK, the same model and the same API it calls today
(`migration_path: "runtime_openai_cris"`, `required_client_api` = `responses` or `chat_completions`). Changes are
limited to:

1. Base URL → `https://bedrock-runtime.{region}.amazonaws.com/openai/v1` (note the `openai/v1` segment)
2. Credentials → a short-term Bedrock bearer token (`api_key=lambda: provide_token(region=region)` from
   `aws-bedrock-token-generator`) or a Bedrock API key, **not** an OpenAI key
3. Model ID → the CRIS inference-profile id (`us.`/`in.`/`global.` for GPT-5.6 Terra and Luna; `us.`/`global.` only
   for GPT-5.6 Sol, GPT-6, GPT-5.5 and GPT-5.4), never the bare `openai.gpt-*` form
4. IAM → `bedrock:InvokeModel*` on the inference-profile and foundation-model ARNs, plus
   `bedrock:GetInferenceProfile` on the profile, plus — for EVERY runtime Responses / Chat Completions target,
   i.e. every proprietary GPT CRIS id above (GPT-5.6 Sol / Terra / Luna, GPT-6, GPT-5.5, GPT-5.4) or its
   `inference-profile/` ARN — `bedrock:InvokeModel` on `arn:aws:bedrock:{region}:{account-id}:project/default`:
   a Responses request on `bedrock-runtime` authorizes the default project separately from the inference target
   (<https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html>, "Permissions", read
   2026-11-07), and each model card repeats the requirement for its runtime CRIS ids.
   `iam_policy.py --runtime-api <required_client_api>` emits it for `responses` / `chat_completions` rows and
   omits it for a `converse` row and for every non-OpenAI id

**Mantle alternative (selector-gated).** Only when the row records a `mantle_selector`
(`references/vendored/ai/bedrock-endpoint-policy.md`): base URL `https://bedrock-mantle.{region}.api.aws/openai/v1`,
the auto-refreshing `BedrockOpenAI` token provider or a Bedrock API key, the bare `openai.gpt-*` id, and
`bedrock-mantle:*` IAM (e.g. `AmazonBedrockMantleInferenceAccess`). Record `migration_path: "mantle_openai_responses"`
or `"mantle_openai_chat"` with the selector.

Full snippets and prerequisites in `shared/openai-on-bedrock.md`. No prompt changes, no eval regression expected —
but still run the eval harness to confirm, because infrastructure and tokenizer-adjacent behavior can differ.

### Assistants API → migration decision tree

Assistants API and Responses API are different surfaces. Do not treat all Assistants usage as a config-only change.

**1. App already uses the OpenAI Responses API** (`responses.create`)
→ Cleanest path. Base URL + credential + model ID change on `bedrock-runtime` (`runtime_openai_cris`).

**2. App uses Assistants API only for stateful multi-turn conversation** (no hosted tools, no file search, no code
interpreter, no persistent Assistant objects, no complex run lifecycle)
→ Runtime Responses is viable (stateful `previous_response_id` works on `bedrock-runtime`). Requires migrating
`threads`/`runs` to `responses.create` — a small API migration (days), not a redesign. Not a zero-code change.

**3. App uses Assistants API with simple hosted tools** (function calling only)
→ Runtime Responses with client-side tool use is viable. Moderate migration (1–2 weeks) to adapt tool definitions
and the run lifecycle. Server-side or pre-configured tools (including Web Search) are a `server_side_tools` /
`web_search` Mantle selector.

**4. App uses Assistants API with file search, vector stores, code interpreter, persistent Assistant objects, or
complex run lifecycle management**
→ Do not recommend mantle. Evaluate Bedrock AgentCore (Harness sessions/memory, action groups as MCP tools via
Gateway, gateway-fronted knowledge bases) for a full agentic replacement (2–4 weeks), or app-managed orchestration
if the team prefers to own state. Never target classic Bedrock Agents (`bedrock-agent`) — it is in maintenance mode
and closed to new customers as of July 30, 2026.

### When to prefer a Bedrock-native model over the same-model GPT path

Choose Claude / Nova via Converse when the workload needs Knowledge Bases or intelligent prompt routing — neither
is served by a same-model GPT path on either endpoint. Note what no longer forces a family switch for GPT-5.6,
GPT-5.5 and GPT-5.4: their `bedrock-runtime` CRIS paths (the default) provide cross-region inference, invocation
logs, Guardrails and application inference profiles (both Converse API only), and structured outputs and implicit
prompt caching (both Responses API only) — per the GPT-5.4 / GPT-5.5 model cards read 2026-11-06. Knowledge
Bases and intelligent prompt routing still require a Bedrock-native model. The same-model `bedrock-runtime` path
is the default; the Bedrock-native path is the most feature-complete; the mantle GPT path is reserved for a
recorded `mantle_selector`.

### High-spend tiering

Tier by task complexity: simple (60%) → Nova Micro / GPT-5.6 Luna, moderate (30%) → Nova Pro / GPT-5.6 Terra,
complex (10%) → Claude Sonnet 5 / GPT-5.6 Sol. Mixing families across tiers is fine, but note that mantle and
`bedrock-runtime` are different surfaces — a tiered router spanning both needs two client paths.

---

## Volume-Based Recommendations

**Low (<1M tokens/day):** use the best model for quality. Cost difference is immaterial.

**Medium (1–10M tokens/day):** present the cost comparison. For Tier 0 the comparison is against the cross-family
alternative, not against the source provider.

**High (10–100M tokens/day):** consider tiering. Enable GPT-5.6 prompt caching first — cached input is both 90%
cheaper and exempt from the input-TPM quota, which relieves the binding constraint on mantle.

**Very high (>100M tokens/day):** tiering plus caching. Check TPM headroom per model per region early; there is no
RPM quota, and the `bedrock-runtime` CRIS path for GPT-5.6 / 5.5 / 5.4 / GPT-6 carries its own quotas rather than
adding headroom to mantle, so quota increases are the scaling lever. See `shared/ai-migration-guardrails.md`.

---

## OpenAI Pricing Tiers

OpenAI's own API offers Batch (50% off, 24hr), Flex (30–50% off, higher latency), Standard (baseline), and Priority
(2x, lowest latency). Source-side figures in this file use Standard. Bedrock exposes Standard / Priority / Flex /
Reserved service tiers, but per-model tier support renders as empty cells in the AWS docs — verify before
recommending Flex or Reserved as a cost lever.
