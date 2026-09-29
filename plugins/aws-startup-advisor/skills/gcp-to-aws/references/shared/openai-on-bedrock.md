# OpenAI Models on Amazon Bedrock

**Last verified:** 2026-08-21
**GPT-6 Astra verified:** 2026-09-09 against its [model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-astra.html)
and [GA announcement](https://aws.amazon.com/about-aws/whats-new/2026/09/openai-gpt-6-astra-on-amazon-bedrock/).
The dates on the existing GPT-5.x evidence below are unchanged.
**Sources:** [OpenAI model cards](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards-openai.html) (per-model
cards linked below), [GPT-5.6 launch post](https://aws.amazon.com/blogs/machine-learning/get-started-with-openai-gpt-5-6-sol-terra-and-luna-on-amazon-bedrock/),
[GPT-5.6 GA announcement](https://aws.amazon.com/about-aws/whats-new/2026/07/openai-gpt-sol-terra/),
[GPT-5.6 pricing update](https://aws.amazon.com/about-aws/whats-new/2026/07/openai-gpt-terra-luna-pricing-bedrock/)

OpenAI's **proprietary** models are available on Bedrock, not just the open-weight `gpt-oss` family. This changes the
default shape of every OpenAI → AWS migration: the source model itself is frequently a Bedrock target, so a
cross-family swap to Claude/Nova is no longer the only option — and is no longer the default.

**This file is the single source of truth for OpenAI-on-Bedrock facts in this plugin.** `ai-openai-to-bedrock.md`
(mapping policy), `design-ai.md` (selection), `estimate-ai.md` (costing), and `ai-migration-guardrails.md` (quota
risk) all defer to it. Do not restate model IDs, regions, or endpoint paths elsewhere — link here.

---

## Model Catalog

| Model               | Model ID (mantle)                        | Launched     | Context | Lifecycle | Model card                                                                                                                                           |
| ------------------- | ---------------------------------------- | ------------ | ------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| GPT-6 Astra         | `openai.gpt-6-astra`                     | Sep 8, 2026  | 1.05M   | Active    | [card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-astra.html)                                                      |
| GPT-5.6 Sol         | `openai.gpt-5.6-sol`                     | Jul 13, 2026 | 1M      | Active    | [card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-sol.html)                                                       |
| GPT-5.6 Terra       | `openai.gpt-5.6-terra`                   | Jul 13, 2026 | 1M      | Active    | [card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-terra.html)                                                     |
| GPT-5.6 Luna        | `openai.gpt-5.6-luna`                    | Jul 13, 2026 | 1M      | Active    | [card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-luna.html)                                                      |
| GPT-5.5             | `openai.gpt-5.5`                         | Jun 1, 2026  | 272K    | Active    | [card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-55.html)                                                           |
| GPT-5.4             | `openai.gpt-5.4`                         | Jun 1, 2026  | 272K    | Active    | [card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html)                                                           |
| gpt-oss-120b        | `openai.gpt-oss-120b`                    | Aug 5, 2025  | 128K    | Active    | open-weight; also on `bedrock-runtime` as `openai.gpt-oss-120b-1:0`                                                                                  |
| gpt-oss-20b         | `openai.gpt-oss-20b`                     | Aug 5, 2025  | 128K    | Active    | open-weight; also on `bedrock-runtime` as `openai.gpt-oss-20b-1:0`                                                                                   |
| GPT OSS Safeguard   | `openai.gpt-oss-safeguard-120b` / `-20b` | —            | —       | Active    | content-moderation / guardrail enforcement, not general chat                                                                                         |
| Daybreak Blue / Red | (gated)                                  | —            | —       | Active    | GPT-5.6 Cyber variants; require Trusted Access for Cyber enrollment — listed so they are not misread as "not on Bedrock"; unlikely migration targets |

**Naming:** GPT-5.6 uses generation number + capability tier. `Sol` = flagship reasoning, `Terra` = balanced
production, `Luna` = high-volume / low-latency. Tiers advance on independent cadences, so a future `Terra` may not
share a generation with a future `Sol`.

GPT-6 Astra is the newest, most capable OpenAI model in this catalog. Sol remains an Active,
lower-cost reasoning alternative; Astra does not make existing GPT-5.x sources require a model upgrade.

> **Context-window conflict (resolved):** the GPT-5.6 launch blog states 272K for all three variants; all three
> model cards state 1M. **The model cards are authoritative** — use 1M for GPT-5.6. GPT-5.5 and GPT-5.4 are 272K on
> both sources. Re-check on refresh; if AWS corrects the blog, the cards still win.

**Not on Bedrock (as of this refresh):** GPT-4o, GPT-4.1, GPT-4 / GPT-4 Turbo, GPT-3.5 Turbo, the o-series
(o1/o3/o4-mini), GPT-5 / GPT-5.1 / GPT-5.2, Codex (unverified — see the Codex note below), and the `*-Pro` variants
(GPT-5.5 Pro, GPT-5.4 Pro). Sources whose model is on this list have no same-model landing target — see
`ai-openai-to-bedrock.md` for the two-option path.

---

## Access Paths — Split by Family

**GPT-6 Astra has two endpoints, verified 2026-09-09:**

| Endpoint          | Reach                         | Model ID                                              | Supported APIs                        |
| ----------------- | ----------------------------- | ----------------------------------------------------- | ------------------------------------- |
| `bedrock-mantle`  | In-region, **us-west-2 only** | `openai.gpt-6-astra`                                  | Responses, Chat Completions           |
| `bedrock-runtime` | CRIS only, no in-region form  | `us.openai.gpt-6-astra` / `global.openai.gpt-6-astra` | Responses, Chat Completions, Converse |

Use `/openai/v1` on either endpoint for the OpenAI-compatible APIs. Astra does **not** support
Invoke or Messages. On runtime, Guardrails and application inference profiles are **Converse-only**;
server-side tool use and structured outputs are unsupported. On mantle, server-side tool calling
is supported, implicit/explicit prompt caching is **Responses-only**, and application inference
profiles are unsupported. Do not copy GPT-5.6's API or feature matrix onto Astra.

The card specifies **1,050,000 context tokens and 128,000 maximum output tokens**, with text/image
input and text output. The launch announcement rounds the input context to 1M; use the card's
exact limits for capacity checks. Browser/computer-use capability does not establish parity with
OpenAI-hosted tools; probe the application's specific tool flow.

**GPT-5.5 and GPT-5.4 are `bedrock-mantle`-only and in-region only.** Their model cards list a single
Programmatic Access row (`bedrock-mantle`, Geo/Global "Not supported") and In-Region pricing only.

**GPT-5.6 Sol / Terra / Luna have TWO endpoints** (verified 2026-08-21 — this changed after this file's original
2026-08-10 verification; the Refresh Checklist predicted it):

| Endpoint          | Reach                         | Model id form                                                                           | Base URL                                                   |
| ----------------- | ----------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `bedrock-mantle`  | In-region only                | `openai.gpt-5.6-sol` / `-terra` / `-luna`                                               | `https://bedrock-mantle.{region}.api.aws/openai/v1`        |
| `bedrock-runtime` | CRIS only (no in-region form) | Geo `us.openai.gpt-5.6-*` (or `in.` in India Regions), Global `global.openai.gpt-5.6-*` | `https://bedrock-runtime.{region}.amazonaws.com/openai/v1` |

The GPT-5.6 model cards now carry an explicit tip: _"Whenever possible, we recommend using the `bedrock-runtime`
endpoint for new applications."_

Constraints that still break naive assumptions:

1. **The path segment is `/openai/v1` on BOTH endpoints** — a bare `/v1` 404s. Every GPT model card states the
   mantle path explicitly, and the runtime example gives `bedrock-runtime.{region}.amazonaws.com/openai/v1`.
2. **The endpoints take different model-id forms.** Mantle takes the bare `openai.gpt-5.6-*` id and has no CRIS;
   `bedrock-runtime` takes ONLY a CRIS inference-profile id (`us.` / `in.` / `global.` prefixed) and has no
   in-region form. `bedrock:ListInferenceProfiles` returns the 5.6 CRIS profiles; it never returns the bare mantle
   ids, and it returns nothing for GPT-5.5 / GPT-5.4.
3. **API surfaces differ by endpoint.** The 5.6 cards list `Responses`, `Chat Completions`, `Invoke`, and
   `Converse` as supported APIs, with runtime-side feature splits: **Guardrails are Converse-only; prompt caching is
   Responses-only on runtime**; server-side tool use, structured outputs, and application inference profiles are NOT
   supported on runtime (server-side tool calling IS supported on mantle). For GPT-5.5 / GPT-5.4 treat Responses on
   mantle as the only verified surface.

### Client setup

Requires the OpenAI SDK at **>= 2.45.0**. Preferred client auto-refreshes a short-term Bedrock token:

```python
from aws_bedrock_token_generator import provide_token
from openai import BedrockOpenAI

region = "us-east-1"
client = BedrockOpenAI(
    aws_region=region,
    bedrock_token_provider=lambda: provide_token(region=region),
    max_retries=6,
)

response = client.responses.create(
    model="openai.gpt-5.6-terra",
    input="...",
    reasoning={"effort": "medium"},
)
```

The alternative — `OpenAI(base_url=".../openai/v1", api_key=os.environ["AWS_BEARER_TOKEN_BEDROCK"])` — uses a key
that expires within 12 hours and is not refreshed. Do not recommend it for production.

**IAM:** on the mantle path, the managed policy `AmazonBedrockMantleInferenceAccess` grants what inference needs,
including `bedrock-mantle:CreateInference` and `bedrock-mantle:CallWithBearerToken` — `bedrock:InvokeModel` does not
authorize mantle calls. On the GPT-5.6 `bedrock-runtime` path the usual `bedrock:InvokeModel*` against the CRIS
inference-profile ARN applies, as for any other runtime model.

**Reasoning effort:** the five GPT-5.x models accept `none`, `low`, `medium`, `high`, `xhigh`, `max`. Astra's card
does not enumerate these values; verify its accepted settings rather than inheriting the GPT-5.x list. Because these models reason
before responding, the model's output items (which may include reasoning items) must be passed back in the next
request for multi-turn and tool-calling flows.

---

## Regional Availability — Endpoint-Aware

**The mantle in-region matrix** (the only reach for GPT-5.5 / GPT-5.4, and the in-region option for GPT-6 Astra / GPT-5.6):

| Model         | us-east-1 | us-east-2 | us-west-2 | us-gov-west-1 | us-gov-east-1 |
| ------------- | --------- | --------- | --------- | ------------- | ------------- |
| GPT-6 Astra   | —         | —         | yes       | —             | —             |
| GPT-5.6 Sol   | yes       | yes       | —         | —             | —             |
| GPT-5.6 Terra | yes       | yes       | yes       | yes           | yes           |
| GPT-5.6 Luna  | yes       | yes       | yes       | yes           | yes           |
| GPT-5.5       | yes       | yes       | —         | —             | —             |
| GPT-5.4       | yes       | yes       | yes       | yes           | —             |

Terra and Luna reached AWS GovCloud (US-West, US-East) in August 2026 — newer than the rest of this matrix.

**Astra runtime availability:** US Geo CRIS can be called from `us-east-1`, `us-east-2`, `us-west-1`,
`us-west-2`, and `ca-central-1`. Global CRIS additionally supports `eu-central-1`, `eu-north-1`,
`eu-west-1`, `eu-west-2`, `eu-west-3`, `ap-northeast-1`, `ap-northeast-2`, `ap-northeast-3`,
`ap-south-1`, `ap-southeast-1`, `ap-southeast-2`, and `sa-east-1`. No EU/India Geo profile or
GovCloud region is listed on the Astra card. A Canada caller using US Geo still routes to the US.

**GPT-5.6 additionally reaches most commercial regions via `bedrock-runtime` CRIS** (Geo `us.` / `in.`, Global
`global.` inference profiles; the Sol card's runtime footprint spans 30+ regions). So a region outside the mantle
matrix does NOT make the same-model path unavailable for GPT-5.6 — it means using the runtime endpoint with a CRIS
id, with the data-residency implications of cross-region routing. For GPT-5.5 / GPT-5.4 the mantle matrix is a hard
gate: no CRIS, no fallback.

Verify current footprints per model card / `aws___get_regional_availability` (AWS MCP Server) — the CRIS lists move faster than this file.

## Pricing

GPT-5.x rates read off the model cards, 2026-08-31; Astra rates verified 2026-09-09. All rates per 1M tokens, Standard tier (Priority and Flex are NOT supported
for these models). Sol rates reflect the Aug 21, 2026 reduction (−20% input / −33% output vs launch rates), which
the AWS What's New announcement lists as promotional through at least Nov 21, 2026. **Pricing now has an
inference-option dimension:**

- **GPT-5.x In-Region and Geo CRIS: 1.10x OpenAI's standard list price** (parity with OpenAI's _data residency_ tier).
- **Global CRIS: OpenAI's standard list price** — cost parity for the GPT-5.6 rates verified above, and only when the
  workload has no data-residency constraint.

So the honest cost statement is conditional, not flat: a same-model GPT-5.6 move on Global CRIS is
**cost-neutral**; the same move in-region or Geo (and any GPT-5.5 / GPT-5.4 move) is **~10% more expensive**.
Never state either number without stating the inference option it belongs to.

### GPT-6 Astra — Standard tier, verified 2026-09-09

| Context tier | In-Region / Geo (in · out) | Global CRIS (in · out) | 30m cache write / read (In-Region / Geo) | 30m cache write / read (Global) |
| ------------ | -------------------------- | ---------------------- | ---------------------------------------- | ------------------------------- |
| Short (272K) | 11.00 · 55.00              | 10.00 · 50.00          | 13.75 / 1.10                             | 12.50 / 1.00                    |
| Long (1.05M) | 22.00 · 82.50              | 20.00 · 75.00          | 27.50 / 2.20                             | 25.00 / 2.00                    |

Above 272K, use the long-context rates. Astra costs **2.5x Sol** at the same context tier and
inference option using Sol's currently recorded promotional rates. Recommend Astra for capability;
keep Sol as a lower-cost alternative. These are Bedrock rates; verify the source provider's current
rate before claiming same-model savings or parity for Astra.

### GPT-5.6 — short context (272K)

| Model | In-Region / Geo (in · out) | Global CRIS (in · out) | Cache write / read (In-Region) |
| ----- | -------------------------- | ---------------------- | ------------------------------ |
| Sol   | 4.40 · 22.00               | 4.00 · 20.00           | 5.50 / 0.44                    |
| Terra | 2.20 · 13.20               | 2.00 · 12.00           | 2.75 / 0.22                    |
| Luna  | 0.22 · 1.32                | 0.20 · 1.20            | 0.275 / 0.022                  |

### GPT-5.6 — long context (1M): 2.0x input / 1.5x output of short-context, per option

| Model | In-Region / Geo (in · out) | Global CRIS (in · out) |
| ----- | -------------------------- | ---------------------- |
| Sol   | 8.80 · 33.00               | 8.00 · 30.00           |
| Terra | 4.40 · 19.80               | 4.00 · 18.00           |
| Luna  | 0.44 · 1.98                | 0.40 · 1.80            |

A workload above 272K context must be priced at the long-context tier.

### GPT-5.5 / GPT-5.4 — In-Region only (no CRIS, no long-context tier; usable window 272K)

| Model   | In-Region (in · out) | Cache read | Notes                            |
| ------- | -------------------- | ---------- | -------------------------------- |
| GPT-5.5 | 5.50 · 33.00         | 0.55       | no cache-write rate published    |
| GPT-5.4 | 2.75 · 16.50         | 0.275      | GovCloud (US-West): 3.30 · 19.80 |

> **The Luna "blog discrepancy" resolved differently than first recorded.** The AWS News Blog's 0.20 / 1.20 is not
> an error — it is the **Global CRIS** rate, now published on the Luna card. An earlier revision of this file said
> global pricing was unpublished and treated the blog figure as wrong; both statements are corrected here.
> Separately, the **AWS Price List API still carries no GPT-5.x rows** (checked 2026-08-04):
> a missing or empty price-list result must not be read as "model unavailable."

### Prompt caching — GPT-5.6 details

Astra separately lists implicit and explicit caching on mantle Responses, with rates above.
Its card does not establish the GPT-5.6 minimum-prefix, breakpoint, or quota-exemption rules below.

Listed as a supported feature on the Sol, Terra, and Luna model cards. The GPT-5.5 and GPT-5.4 cards list
client-side tool calling in that slot instead and do **not** list prompt caching. Do not assume caching on 5.5/5.4.

| Property          | Value                                                        |
| ----------------- | ------------------------------------------------------------ |
| Cached input read | 90% discount vs uncached input                               |
| Cache write       | 1.25x the uncached input rate                                |
| Minimum prefix    | 1,024 tokens (below this nothing caches, `cached_tokens`= 0) |
| Breakpoints       | up to 4 per request                                          |
| Retention         | at least 30 minutes                                          |
| Modes             | implicit (on by default) and explicit (cache breakpoints)    |

Explicit mode uses `prompt_cache_options={"mode": "explicit"}` plus a `prompt_cache_breakpoint` on the content block
ending the reusable prefix; a stable `prompt_cache_key` improves match reliability. Cached input tokens **do not
count against the input-TPM quota**, which compounds the benefit at scale.

---

## Quotas

**Astra runtime:** the model card specifies TPM accounting with **10x output-token burndown**.
Do not reuse the GPT-5.x mantle quota accounting below for Astra without verifying its quota rules.

Inference on `bedrock-mantle` is governed by **two per-model, per-region quotas: input tokens per minute and output
tokens per minute. There is no requests-per-minute quota.** Exceeding a TPM quota returns HTTP 429.

This corrects two claims that were previously applied to all Mantle traffic in this plugin:

- There is **no shared 10,000 RPM account limit** governing these models — the quota dimension is TPM, per model,
  per region.
- "Switch to `bedrock-runtime`" is **not a throughput remedy for GPT-5.5 / GPT-5.4** — they have no
  `bedrock-runtime` path at all. For GPT-5.6 the runtime path DOES exist (CRIS only; see Access Paths above), so
  moving there is a legitimate option — but treat it as an endpoint/architecture choice with its own quota family
  and residency implications, not a free throughput escape hatch.

The supported mitigations are: exponential backoff with a bounded retry count (`max_retries` on the OpenAI SDK),
spreading load across minutes rather than bursting, ramping request rate gradually, and prompt caching (cached input
is exempt from the input-TPM quota). For sustained volume beyond that, pursue a quota increase.

The model cards now state tier support in text: pricing shown is Standard, and **Priority and Flex are not
supported for these models**. Do not recommend Flex as a cost lever for any GPT model here; Reserved is
account-level via the AWS account team.

---

## Features With No Bedrock Equivalent

These are the remaining legitimate reasons to keep a workload on OpenAI's own API. Cost is no longer one of them.

| OpenAI capability                                                           | Status on Bedrock                                                 |
| --------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Realtime API                                                                | No equivalent                                                     |
| Image generation (gpt-image)                                                | Not an OpenAI model on Bedrock; use Stability AI (see lifecycle)  |
| Whisper (STT) / TTS                                                         | Amazon Transcribe / Polly — different service, API, pricing model |
| Embeddings (`text-embedding-3-*`)                                           | No OpenAI embedding model on Bedrock; use Titan Embeddings v2     |
| Assistants API with file search, vector stores, code interpreter            | No direct equivalent — see the decision tree in the mapping guide |
| A model not in the catalog above (GPT-4o, o-series, `*-Pro`, GPT-5/5.1/5.2) | No same-model target; cross-family or upgrade required            |

**Data handling:** these are third-party models under OpenAI terms. Classifier-flagged traffic is retained up to 30
days for automated abuse detection; retained inputs/outputs are stored and processed by AWS and not shared with
OpenAI unless the customer opts in. Prompts and completions are not used to train models. Calls run under the
customer's IAM policies, inside their VPC, logged to CloudTrail, and in-region inference keeps data in-region.

**Codex on Bedrock: unverified — do not price it.** An earlier revision of this file stated Codex is GA on Bedrock
with pay-per-token pricing. As of 2026-09-02, Codex does not appear on the
[OpenAI model card index](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards-openai.html), and no
Codex rate exists on the Bedrock pricing page, in `pricing-cache.md`, or in `bedrock_pricing.py`'s static table.
When the source workload is a coding agent, re-check the model card index first; if Codex is still absent, treat it
as "a model not in the catalog above" (see the table in this section): plan a cross-family target (GPT-5.6 Sol /
Terra are the coding-agent tier fits) and price that target — or report `pricing_source: "unverified"` with no
dollar figure. Never attach a fabricated Codex rate to an estimate.

---

## Refresh Checklist

This model family is moving fast (two GA waves and a repricing inside 10 weeks). On each refresh:

1. Re-read the [OpenAI model card index](https://docs.aws.amazon.com/bedrock/latest/userguide/model-cards-openai.html)
   for models added or removed, and each per-model card for lifecycle state and EOL date.
2. Recheck the region matrix AND the GPT-5.6 CRIS footprints — for 5.5/5.4 a region change is migration-blocking;
   for 5.6 the runtime/CRIS path usually covers the region instead.
3. Recheck rates on the Bedrock pricing page OpenAI tab, and resolve any row still marked _unverified_.
4. Recheck whether the Price List API has gained GPT-5.x coverage; if it has, drop the caveat above and let
   `estimate-ai.md` price these models from the MCP.
5. Recheck whether Chat Completions and `bedrock-runtime` support have been added or clarified.
6. Feed any lifecycle change into `ai-model-lifecycle.md` and any rate change into `pricing-cache.md`.
7. **Re-verify within 14 days of any merge touching this file.** Item 5's prediction fired on 2026-08-21: between
   2026-08-10 and 2026-08-21 the GPT-5.6 family gained a `bedrock-runtime`/CRIS path, published Global CRIS pricing
   at standard-price parity, and listed Chat Completions/Converse as supported — invalidating three of this file's
   then-central claims in under two weeks. This family moves faster than a normal refresh cadence.
