# AI-Only Migration — Clarify Requirements

**Standalone flow** — Used when ONLY `ai-workload-profile.json` exists (no infrastructure or billing artifacts). Infrastructure stays where it runs today; only AI/LLM calls move to AWS Bedrock.

**Input contract.** The only profile this flow reads is the provider-neutral `ai-workload-profile.json` (`schema_version`, `ai_sources[]`, `gateways[]`), already accepted by `scripts/validate-ai-profile.py`. Use that script's JSON summary for every detected value below. A 1.1 profile also carries `integration`; from it the summary reports `ai_framework_detected` and `ai_vision_detected`. Both are `null` for a 1.0 profile or when the evidence is not definitive, and then Q1 and Q6 are asked, not extracted. `ai_vision_detected` is only `"vision"` or `"audio"`: finding no image or audio input does not prove the app sends only text, so Q6 is then asked. Do not scan application code or IaC, and do not read usage-profile files or any other file: only the validator summary can supply an extracted answer.

Produces the same `preferences.json` output but with `design_constraints` limited to region and compliance, `startup_constraints` populated, and `ai_constraints` fully populated. Questions are presented in **two progressive batches** with an intermediate save — partial answers persist across sessions.

---

## Step 0: Prior Run Check

Check `$MIGRATION_DIR/` for existing state:

**Case 1 — Completed preferences exist** (`preferences.json` present):

> "I found existing migration preferences from a previous run. Would you like to:"
>
> 1. Re-use these preferences and skip questions
> 2. Start fresh and re-answer all questions

- If 1: delete `preferences-draft.json` if it exists, then skip to Step 4 with the existing `preferences.json`.
- If 2: delete `preferences.json` and `preferences-draft.json` (if present), continue to Step 1.

**Case 2 — Draft preferences exist** (`preferences-draft.json` present, no `preferences.json`):

> "I found a partial set of answers from a previous session (1 of 2 batches completed). Would you like to:"
>
> 1. Resume from where you left off — I'll pick up the remaining questions
> 2. Start fresh and re-answer all questions

- If 1: load the draft, skip Batch 1 in Step 2, present Batch 2 directly.
- If 2: delete `preferences-draft.json`, continue to Step 1.

**Case 3 — No prior state**: Continue to Step 1.

---

## Step 1: Present AI Detection Summary

> **AI-Only Migration Detected**
> This release migrates AI calls only. Infrastructure stays where it runs.
>
> **AI sources:** [one line per `ai_sources[]` entry: `provider` via `source_service`, plus "through [gateway product]" for each name in `via_gateways`]
> **Models detected:** [each source's `models[].model`, with `raw_model` when it differs; "not observed" when `model_evidence` is `not_observed`]
> **Gateway/router:** [each `gateways[].product` with "upstreams unresolved" when `upstream_evidence` is `unresolved`, or "None (direct SDK)"]

---

## Step 1.5: Fast-Path Check

The fast path is gated on `migration-preview.json`, which this skill does not produce yet. Continue to Step 1.75 (mini assumption sheet), then Step 2.

---

## Step 1.75: Mini Assumption Sheet (before Batch 1)

Before asking anything, present what the profile already answered as a compact confirm-or-edit sheet (sheet first, questions after the user responds). If the sheet has no rows, skip this step:

```
### AI migration assumptions — confirm or correct

**Detected from your AI profile:**
| Setting | Value | Source |
| ------- | ----- | ------ |
| Models | [every observed model, e.g. gpt-4o, claude-3-haiku] | ai-workload-profile.json |
| Framework | [ai_framework_detected, e.g. framework (LangChain)] | ai-workload-profile.json `integration` |
| Input types | [ai_vision_detected, e.g. vision] | ai-workload-profile.json `integration.capabilities_summary` |

Reply "looks good" to continue to the remaining questions, correct any line
("model: gemini-3.5-flash"), or describe the issue in plain words.
```

Questions resolved on this sheet are **not** re-asked in the batches below; record them with `chosen_by: "extracted"` and skip their entries in Batch 1/2. Rows the user corrects become `chosen_by: "user"`. The sheet never assumes a value: every question without a detected row stays in the batches, and only "use defaults for the rest" applies defaults.

Show the **Models** row under "Detected" only when the validator summary reports `models_extractable: true`, and list every observed model. If it is `false`, leave the row out of the sheet and ask Q5 in Batch 1 with the detected models as the suggested answer; a user who confirms them records `chosen_by: "user"`. Show **Framework** only when `ai_framework_detected` is not `null`, and **Input types** only when `ai_vision_detected` is not `null`.

---

## Step 2: Ask Questions in Progressive Batches (Q1–Q11, incl. Q1.5)

Questions are presented in two batches with a save after the first. The user can skip individual questions (defaults applied), say **"use defaults for the rest"** to apply defaults for all remaining questions and proceed immediately, or answer normally.

### Batch 1 — AI Strategy & Setup (Q1–Q5 + Q1.5)

Present with this intro:

```
Before designing your Bedrock migration, I have two short sections of questions.
You can answer each, skip individual ones (I'll use sensible defaults),
or say "use defaults for the rest" at any point.

Let's start with your AI strategy and current setup.

--- AI Strategy & Setup ---
```

## Q1 — AI framework or orchestration layer (select all that apply)

_Skip when:_ the validator summary reports a non-null `ai_framework_detected`. Record that list with `chosen_by: "extracted"` and `source: "ai-profile:integration"`, and do not present this question. Otherwise, when the summary lists a gateway, present the confirm card below with option 2 as the detected value and the gateway product as the evidence. Otherwise present the full question.

**Gateway confirm card:**

> Your AI profile shows calls through **[gateway product, e.g. openrouter]**.
>
> 1. **That's right** — the gateway is how our app reaches the models
> 2. **Edit** — show me all framework options
> 3. **Gateway plus a framework** — show me all framework options with the gateway selected

Accept → record `["llm_router"]` with `chosen_by: "user"`. Edit or option 3 → fall through to the full question below, with option 2 preselected for option 3.

> 1\) No framework — direct API calls | 2\) LLM router/gateway | 3\) LangChain / LangGraph | 4\) Multi-agent framework | 5\) OpenAI Agents SDK | 6\) MCP/A2A | 7\) Voice platform

| Answer                             | Recommendation Impact                                                                                     | Migration Effort  | Timeline                                             |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------- | ----------------- | ---------------------------------------------------- |
| 1) No framework — direct API calls | Swap SDK calls to Bedrock SDK; evaluate AgentCore (Harness) if planning agentic                           | Low               | 1–3 weeks depending on call sites                    |
| 2) LLM router/gateway              | Add Bedrock as provider in gateway config; no app code changes; verify SigV4 auth                         | Minimal           | Hours to 1–3 days                                    |
| 3) LangChain / LangGraph           | Provider swap via `ChatBedrock`; chains/graphs/tools preserved; validate tool schemas                     | Low               | 1–3 days; 1 week if complex graphs                   |
| 4) Multi-agent framework           | Path 1: Keep framework, swap LLM provider (lower effort). Path 2: Migrate to Bedrock multi-agent (deeper) | Medium            | Path 1: 3–5 days; Path 2: 2–4 weeks                  |
| 5) OpenAI Agents SDK               | Highest effort; tightly coupled to OpenAI API; recommend AgentCore (Harness, or Runtime for code loops)   | High              | 2–4 weeks                                            |
| 6) MCP / A2A                       | AgentCore supports MCP natively (Gateway exposes tools as MCP); A2A interop; recommend AgentCore          | Low–Medium        | 3–5 days MCP; 1–2 weeks A2A                          |
| 7) Voice platform                  | If platform supports Bedrock natively → config change; otherwise evaluate Nova 2 Sonic                    | Minimal to Medium | Hours if native; 2–3 weeks if Nova 2 Sonic migration |

> **Never recommend classic Bedrock Agents (`bedrock-agent`) as a migration target.** It is in maintenance mode and closed to new customers as of July 30, 2026 ([AWS announcement](https://aws.amazon.com/about-aws/whats-new/2026/06/aws-service-availability/)). Agentic targets are AgentCore Harness (config-based, default) or AgentCore Runtime (code-defined loops).

### Combination Logic

| Combination                          | Approach                                                                                               |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| 1 only                               | Simplest path — direct SDK migration                                                                   |
| 2 only                               | Quick win — gateway config change, skip SDK migration steps                                            |
| 2 + any other                        | Gateway swap is the quick win; assess framework migration as separate workstream                       |
| 3 + 1                                | Two workstreams: LangChain provider swap (fast) + direct call migration (slower)                       |
| 4 + 6                                | Complex — multi-agent with MCP tooling; recommend AgentCore to unify orchestration and tools           |
| 5 + anything                         | 5 is the long pole; plan timeline around Agents SDK migration; other layers may be quick wins          |
| Multiple frameworks (3+4, 3+5, etc.) | Assess independently; prioritize by traffic volume or business criticality; consolidate post-migration |

If answer includes 2 and no other selections, skip or abbreviate SDK migration steps. If answer is 1 only, proceed with standard model migration flow.

Interpret → `ai_framework` array. Default: auto-detect, fallback `["direct"]`.

## Q1.5 — Do you have any compliance or regulatory requirements? (select all that apply)

Compliance gates Bedrock regions, models, and logging **even though your infrastructure stays where it is** — customer data flows to AWS the moment model calls do. The impacts below are the Bedrock-specific subset that applies on this path.

> Even with infrastructure staying where it is, your prompts and completions will be processed on AWS. Compliance requirements determine which Bedrock regions, models, and configurations are available.
>
> 1\) None | 2\) SOC 2 / ISO 27001 | 3\) PCI DSS | 4\) HIPAA | 5\) FedRAMP / Government | 6\) GDPR / Data residency | 7\) CCPA / CPRA | 8\) I don't know
>
> _(Multiple selections allowed)_

| Answer            | Bedrock Impact                                                                                                                                                                                                                  |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| None              | Full model catalog, any Bedrock region; `global.` inference profiles allowed                                                                                                                                                    |
| SOC 2 / ISO 27001 | CloudTrail on Bedrock API calls; encryption at rest for Knowledge Bases and logs                                                                                                                                                |
| PCI DSS           | No cardholder data in prompts without tokenization; CloudTrail + scoped IAM; dedicated logging config                                                                                                                           |
| HIPAA             | BAA required before PHI in prompts; BAA-eligible Bedrock models only; **Guardrails PII masking does NOT apply to CloudWatch logs — original content is logged; encrypt with KMS + restrict IAM**; us-east-1/us-west-2 preferred |
| FedRAMP           | GovCloud Bedrock only (us-gov-east-1/us-gov-west-1) — materially smaller model catalog; verify target model availability before committing the migration                                                                        |
| GDPR              | EU Bedrock regions (eu-west-1, eu-central-1); **geographic (`eu.`) inference profiles only — `global.` profiles route outside the EU boundary**; document cross-border transfer from your current EU provider                                     |
| CCPA / CPRA       | Prompt/completion retention policy; deletion workflow for logged content; CloudTrail audit logging                                                                                                                              |

Interpret → `design_constraints.compliance` array (same format as the full flow). An explicit user answer of 1 records `["none"]` with `chosen_by: "user"`. **Skip/default records `["unknown"]`** (never a silent "none" — full-flow Q2 semantics: behaves like "none" for service selection) with `chosen_by: "default"`, `source: "default:Q1.5"` — and append the caveat "Compliance requirements were not confirmed by the user" to `metadata.report_caveats[]` (create the array if absent) so downstream reports surface it. Cross-check with Q4: a GDPR answer constrains the target region jointly with cross-cloud latency.

## Q2 — What matters most for your AI application?

> 1\) Best quality/reasoning | 2\) Fastest speed | 3\) Lowest cost | 4\) Specialized capability (→ Q10\) | 5\) Balanced | 6\) I don't know

| Answer   | Model Impact                                        |
| -------- | --------------------------------------------------- |
| Quality  | Claude Sonnet 5 primary; Opus 5.5 for hardest tasks |
| Speed    | Claude Haiku 5.5; also Nova Micro/Lite              |
| Cost     | Claude Haiku 5.5 or Nova Micro                      |
| Special  | Deferred to Q10                                     |
| Balanced | Claude Sonnet 5                                     |

Interpret → `ai_priority`. Default: 5 → `"balanced"`.

## Q3 — Monthly AI spend on OpenAI or Gemini?

> 1\) < $500 | 2\) $500–$2K | 3\) $2K–$10K | 4\) > $10K | 5\) Don't know

Interpret → `ai_monthly_spend`. Default: 2 → `"$500-$2K"`.

## Q4 — Cross-cloud API call concerns

Unique to AI-only: infrastructure stays with its current provider while AI calls route to AWS.

> 1\) Latency critical — AI in hot path | 2\) Latency acceptable — async/users can wait | 3\) Concerned about egress costs | 4\) Want to test first — parallel running

| Answer           | Impact                                         |
| ---------------- | ---------------------------------------------- |
| Latency critical | VPC endpoint; closest region to current deployment |
| Acceptable       | Standard endpoint; region by cost              |
| Egress concerned | PrivateLink; egress cost analysis              |
| Test first       | Phased migration; parallel running guidance    |

Interpret → `cross_cloud`. Default: 2 → `"latency-acceptable"`.

## Q5 — Current model in use?

Establishes baseline Bedrock recommendation. Override hierarchy: Q10 special features > Q2 priority > Q7/Q8 volume/latency > Q5 baseline.

_Skip when:_ the validator summary reports `models_extractable: true` — every source has `model_evidence: "observed"` and every observed model has at least one `confidence: "high"` evidence entry (user-confirmed evidence is always `high`) — auto-detect with `chosen_by: "extracted"`, `source: "ai-profile:ai_sources[].models"`, and do not present this question. The detected models are already shown in the Step 1 summary. Otherwise, present the question with the detected model(s) offered as the suggested answer. With 2+ detected models, record `ai_model_baseline` as an array (one entry per model).

> 1\) Gemini Flash | 2\) Gemini Pro | 3\) GPT-3.5 Turbo | 4\) GPT-4/4 Turbo | 5\) GPT-4o | 6\) GPT-5.4/Mini/Nano | 7\) GPT-5.6 Sol/Terra/Luna | 8\) GPT-5/5.x (older) | 9\) GPT-5.5/Pro | 10\) GPT-6/6.1 (Astra/Sol/Luna) | 11\) o-series | 12\) Claude (Anthropic SDK) | 13\) Other/Multiple | 14\) Don't know

| Source        | Baseline Recommendation        | Pricing Context                    |
| ------------- | ------------------------------ | ---------------------------------- |
| Gemini Flash | Claude Haiku 5.5 (US Geo: $0.11/$0.55 up to 100K prompt tokens; $0.55/$2.75 above 100K) | Compare the exact Flash model and target token counts; savings are tier-dependent |
| Gemini Pro    | Claude Sonnet 5 ($2/$10)       | Comparable tier                    |
| GPT-6/6.1 (Astra/Sol/Luna) | **Same model on Bedrock** | ~10% over OpenAI std (DR tier); Astra/6.1 Sol also support Ultrafast |
| GPT-6.1 Terra              | **Same model on Bedrock** | Use the model-specific endpoint and context-tier prices in the [GPT-6.1 Terra model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-1-terra.html); compare against measured source spend or verified source rates. |
| GPT-5.6 (any) | **Same model on Bedrock**      | ~10% over OpenAI std (DR tier)     |
| GPT-5.5       | **Same model on Bedrock**      | ~10% over OpenAI std (DR tier)     |
| GPT-5.4       | **Same model on Bedrock**      | ~10% over OpenAI std (DR tier)     |
| GPT-3.5 Turbo | GPT-5.6 Luna; or Claude Haiku 5.5 | At equal billed volumes and 2:1 input/output, Haiku US Geo is 56.25% cheaper up to 100K prompt tokens; Luna is 54.29% cheaper above 100K while Luna remains within 272K. Recount target tokens; if request size is unknown, present both Haiku tiers. |
| GPT-4/4 Turbo | GPT-5.6 Terra; or Sonnet 5     | Not on Bedrock — offer both        |
| GPT-4o        | GPT-5.6 Terra; or Sonnet 5     | Not on Bedrock — offer both        |
| GPT-5.4 Mini  | GPT-5.6 Luna; or Nova Lite     | Mini not on Bedrock — offer both   |
| GPT-5.4 Nano  | GPT-5.6 Luna; or Nova Micro    | Nano not on Bedrock — offer both   |
| GPT-5.x Pro   | GPT-5.6 Sol; or Nova 2 Pro     | Pro not on Bedrock — offer both    |
| GPT-5/5.1/5.2 | GPT-5.6 Terra; or Sonnet 5     | Not on Bedrock — offer both        |
| o-series      | GPT-5.6 Sol/Terra; or Sonnet 5 | Not on Bedrock — offer both        |
| Claude (any)  | Same model on Bedrock          | Client swap only — no model change |

**Same-model rows first.** GPT-6 Astra / GPT-5.6 / 5.5 / 5.4 sources map to themselves.
Design applies the model-specific API and region gate; Clarify records the baseline only.
Astra Standard mantle supports `us-east-1` and `us-west-2`; runtime uses US Geo / Global CRIS. GPT-5.6 also has runtime CRIS;
GPT-5.5 / 5.4 remain mantle-only. GPT-5.x in-region costs about 10% above OpenAI standard,
while GPT-5.6 Global CRIS uses the standard rate. For Astra, compare its separately dated
inference/context tier against the source price before claiming savings or parity.
For sources without a Bedrock equivalent, present a same-vendor upgrade and a cross-family option.

Override examples: GPT-4 + Q2=cost → Haiku; Flash + Q10=extended thinking → Sonnet; GPT-4o + Q10=speech → Nova 2 Sonic; GPT-5.5 + Q2=cost → Sonnet 5.

Interpret → `ai_model_baseline`. Default: auto-detect, fallback Q2 priority-based.

### Batch 1 → Save Draft and Present Batch 2

After the user responds to Batch 1:

1. Interpret all Batch 1 answers (apply interpret rules above; apply defaults for skipped questions).
2. Write `$MIGRATION_DIR/preferences-draft.json` with Batch 1 answers:

```json
{
  "metadata": {
    "draft": true,
    "batches_completed": ["ai-strategy"],
    "batches_remaining": ["ai-technical"],
    "migration_type": "ai-only",
    "timestamp": "<ISO timestamp>",
    "discovery_artifacts": ["ai-workload-profile.json"],
    "questions_asked": ["Q1", "Q2", ...],
    "questions_defaulted": [...]
  },
  "design_constraints": { ... },
  "ai_constraints": { ... }
}
```

1. Present Batch 2:

```
Got it — your AI strategy preferences are saved.

Last section — 6 questions about your technical requirements, then your answers are saved.
You can answer each, skip individual ones, or say "use defaults for the rest."

--- Technical Requirements ---
```

**"Use defaults for the rest" handling:** If the user says this during Batch 1, apply defaults for all unanswered Batch 1 questions and all Batch 2 questions, then skip directly to Step 3. **Skip the Batch 1 draft save on this path** — assembly happens in the same turn, so a draft would serve no crash-recovery purpose.

### Batch 2 — Technical Requirements (Q6–Q11)

## Q6 — What input types must the model accept: text only, images (vision), or audio/video?

_Skip when:_ the validator summary reports a non-null `ai_vision_detected`. Record it with `chosen_by: "extracted"` and `source: "ai-profile:integration.capabilities_summary"`, and do not present this question. Otherwise ask.

> 1\) Text only | 2\) Vision required | 3\) Audio/Video inputs

| Answer      | Impact                                                                                                          |
| ----------- | --------------------------------------------------------------------------------------------------------------- |
| Text only   | Full model catalog                                                                                              |
| Vision      | Claude Sonnet or Haiku (both support multimodal vision); Nova Micro excluded (text-only)                        |
| Audio/Video | Nova 2 Sonic (audio). Nova Reel v1 is past EOL (2026-09-30) with no Active replacement in the registry — do not recommend it. Claude excluded for audio/video input |

Interpret → `ai_vision`: 1 → `"text-only"`, 2 → `"vision"`, 3 → `"audio"`. Default: 1 → `"text-only"` (no constraint).

## Q7 — Monthly AI usage volume

_Never skipped:_ do not fill this from a usage-profile file or from the assumption sheet. Ask it unless the user says "use defaults for the rest".

> 1\) < 1M tokens | 2\) 1–10M | 3\) 10–100M | 4\) > 100M | 5\) Don't know

| Answer    | Impact                                             |
| --------- | -------------------------------------------------- |
| Low       | On-demand; no provisioned throughput               |
| Medium    | On-demand with prompt caching analysis             |
| High      | Provisioned throughput analysis; prompt caching    |
| Very high | Provisioned throughput required; capacity planning |

Interpret → `ai_token_volume`: 1 → `"low"`, 2 → `"medium"`, 3 → `"high"`, 4 → `"very_high"`. Default: 2 → `"medium"`.

## Q8 — Response speed importance

Present with concrete anchors: Critical = autocomplete/live chat; Important = chat assistant; Flexible = reports/batch.

> 1\) Critical (< 500ms) | 2\) Important (< 2s) | 3\) Flexible (2–10s)

| Answer    | Impact                                                       |
| --------- | ------------------------------------------------------------ |
| Critical  | Haiku/Nova Micro candidates; stream, verify model-specific quotas/capacity, and measure latency at the chosen effort level |
| Important | Sonnet 5 with streaming; standard on-demand                  |
| Flexible  | Any model; batch inference for cost savings                  |

Interpret → `ai_latency`. Default: 2 → `"important"`.

## Q9 — AI task complexity

Present with concrete examples: Simple = classify/extract/summarize; Moderate = analyze+JSON/few-shot; Complex = multi-turn reasoning/tool use/agentic.

> 1\) Simple | 2\) Moderate | 3\) Complex

| Answer   | Impact                                                                |
| -------- | --------------------------------------------------------------------- |
| Simple   | Haiku/Nova Micro sufficient; significant cost savings                 |
| Moderate | Sonnet 5 recommended; Haiku may suffice with prompt engineering       |
| Complex  | Sonnet 5 required; extended thinking considered (note: on Sonnet 5.5, turning off up-front thinking requires `thinking: {"type": "between_tools"}` instead of "disabled" at high effort or below); Opus 5.5 for hardest |

Interpret → `ai_complexity`. Default: 2 → `"moderate"`.

## Q10 — Specialized features needed

> 1\) Function calling | 2\) Ultra-long context (> 300K) | 3\) Extended thinking | 4\) Prompt caching | 5\) RAG optimization | 6\) Agentic workflows | 7\) Real-time speed | 8\) Image generation | 9\) Conversational speech | 10\) None

| Answer                               | Recommendation Impact                                                                                                                                                                                                                                                                                                                                                                                               |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Function calling / Tool use          | Claude Sonnet 5 — best-in-class tool use on Bedrock via structured JSON tool schemas; supports parallel tool calls and multi-turn tool use                                                                                                                                                                                                                                                                          |
| Ultra-long context (> 300K tokens)   | Claude Opus 5.5 (1M context, 128K output; London in-region or a verified Geo/Global CRIS profile on runtime), or Claude Sonnet/Opus 4.6 long-context SKUs where available (standard on-demand for 4.6 matches base tier in US East N. Virginia per [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)); or Llama 4 Scout (10M), Llama 4 Maverick (1M), Nova 2 Pro/Lite (1M) for very large native context windows |
| Extended thinking / Chain-of-thought | Claude Sonnet 5 with adaptive thinking; Claude Opus 5.5 for demanding reasoning (adaptive thinking always on; default medium effort; no manual budget_tokens). Use London runtime in-region or a verified runtime CRIS profile; select Opus 4.6 instead when Batch is required                                                                                                                                                                  |
| Prompt caching                       | Claude Sonnet 5 with prompt caching enabled; cost savings analysis included. **Caveat:** caching only helps for long, repeated context (system prompts, documents). Per-model minimum token thresholds (~1K–4K tokens) and TTL apply — short prompts won't cache. Verify current minimums at docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html before recommending.                                  |
| RAG optimization                     | Amazon Bedrock Knowledge Bases recommended alongside model; Titan Embeddings for vector store                                                                                                                                                                                                                                                                                                                       |
| Agentic workflows                    | Claude Sonnet 5 with AgentCore (Harness); multi-agent orchestration guidance included                                                                                                                                                                                                                                                                                                                               |
| Real-time speed (< 500ms)            | Claude Haiku 5.5 or Nova Micro candidates; tune effort, stream, and measure whether the latency target is met                                                                                                                                                                                                                                                                                                                                                |
| Multimodal with image generation     | Claude Sonnet 5 (vision) + Stability AI for generation (Core cost-first / Ultra quality-first)                                                                                                                                                                                                                                                                                                                      |
| Real-time conversational speech      | Amazon Nova 2 Sonic recommended for speech-to-speech; latency guidance included                                                                                                                                                                                                                                                                                                                                     |
| None                                 | Default recommendation from Q2 priority stands                                                                                                                                                                                                                                                                                                                                                                     |

Interpret → `ai_critical_feature`. Default: 10 → no override.

## Q11 — Have you applied for AWS Activate credits?

**Activate eligibility:** Pre-Series B, founded in the last 10 years, AWS Account on Paid Tier Plan, and either new to Activate Credits or requesting more credits than previously received. AI-only migrations are exactly the workloads Activate credits offset — Bedrock usage (Claude, Llama, Nova) is credit-eligible. **Never infer funding stage or Activate tier from Q3 spend.**

> AWS Activate credits offset Bedrock costs during and after migration — including Claude, Llama, and Nova models. Eligible startups can get $5K–$200K depending on funding stage.
>
> 1. Yes — already have AWS Activate credits
> 2. No — haven't applied yet (self-funded or pre-VC)
> 3. No — VC/accelerator-backed but haven't applied
> 4. I don't know

| Answer                     | Recommendation Impact                                                                                                 |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Already have credits       | Note credit balance in migration plan; flag Bedrock usage as credit-eligible                                          |
| No — self-funded           | Flag **AWS Activate Founders** (up to $5,000, self-service): aws.amazon.com/startups/credits — apply before migrating |
| No — VC/accelerator-backed | Flag **AWS Activate Portfolio** (up to $200,000): requires Activate Provider Org ID from your VC/accelerator          |
| Don't know                 | Surface both tiers; recommend checking with investors/accelerator for Org ID                                          |

Escalations (adapted to AI-only signals): if `ai_monthly_spend` is `">$10K"`, also flag **AWS Credits for AI Startups** ($200,000+, invite-only — contact your AWS Account Manager). If `ai_monthly_spend` is `"$2K-$10K"` or `">$10K"` AND the workload is agentic (Q1 includes 4/5/6 or Q10 = 6), also flag **AWS Generative AI Accelerator** (up to $1M credits, 8-week cohort): aws.amazon.com/startups/generative-ai/accelerator

Interpret → `startup_program_status`: 1 → `"has_credits"`, 2 → `"eligible_founders"`, 3 → `"eligible_portfolio"`, 4 → `"unknown"`. Default: 4 → `"unknown"` — downstream artifacts must use neutral Activate copy (both tiers, no "your status: eligible_*").

### Batch 2 Complete

After the user responds to Batch 2, interpret all Batch 2 answers and proceed to Step 3.

---

## Step 3: Assemble and Write preferences.json

Assemble all interpreted answers from both batches into the final file. If `preferences-draft.json` exists and was resumed in Step 0 Case 2, use it as the base — merge in Batch 2 answers, remove draft-specific metadata fields (`draft`, `batches_completed`, `batches_remaining`), and set `metadata.timestamp` to the current time.

Write `$MIGRATION_DIR/preferences.json`:

**Schema — AI-only structure:**

| Field                      | Path                                         | Notes                                                                                                                                                                                                                                           |
| -------------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `migration_type`           | `metadata.migration_type`                    | `"ai-only"` — downstream skips infra phases                                                                                                                                                                                                     |
| `discovery_artifacts`      | `metadata.discovery_artifacts`               | `["ai-workload-profile.json"]`                                                                                                                                                                                                                  |
| `questions_asked`          | `metadata.questions_asked`                   | Q IDs presented AND answered by the user. A presented question resolved via "use defaults for the rest" goes in `questions_defaulted` only — the three lists stay disjoint                                              |
| `questions_defaulted`      | `metadata.questions_defaulted`               | Array of Q IDs where defaults used                                                                                                                                                                                                              |
| `questions_extracted`      | `metadata.questions_extracted`               | Array of Q IDs skipped via auto-detect                                                                                                                                                                                                          |
| `target_region`            | `design_constraints.target_region`           | Derived, precedence: Q1.5 compliance (fedramp → us-gov-west-1, gdpr → eu-west-1, hipaa → us-east-1) > Q4 cross-cloud pref > fallback us-east-1. `chosen_by: "derived"`; prompt names the rule applied |
| `compliance`               | `design_constraints.compliance`              | From Q1.5 — gates Bedrock regions/models                                                                                                                                                                                                        |
| `startup_program_status`   | `startup_constraints.startup_program_status` | From Q11                                                                                                                                                                                                                                        |
| `ai_framework`             | `ai_constraints.ai_framework`                | From Q1                                                                                                                                                                                                                                         |
| `ai_priority`              | `ai_constraints.ai_priority`                 | From Q2                                                                                                                                                                                                                                         |
| `ai_monthly_spend`         | `ai_constraints.ai_monthly_spend`            | From Q3                                                                                                                                                                                                                                         |
| `cross_cloud`              | `ai_constraints.cross_cloud`                 | From Q4 (unique to AI-only)                                                                                                                                                                                                                     |
| `ai_model_baseline`        | `ai_constraints.ai_model_baseline`           | From Q5                                                                                                                                                                                                                                         |
| `ai_vision`                | `ai_constraints.ai_vision`                   | From Q6                                                                                                                                                                                                                                         |
| `ai_token_volume`          | `ai_constraints.ai_token_volume`             | From Q7                                                                                                                                                                                                                                         |
| `ai_latency`               | `ai_constraints.ai_latency`                  | From Q8                                                                                                                                                                                                                                         |
| `ai_complexity`            | `ai_constraints.ai_complexity`               | From Q9                                                                                                                                                                                                                                         |
| `ai_critical_feature`      | `ai_constraints.ai_critical_feature`         | From Q10                                                                                                                                                                                                                                        |

`ai_capabilities_required` is omitted: Q6 and Q10 already record the requirement.

Each constraint carries the FULL field shape in `references/shared/schema-preferences.md` — `value`, `chosen_by` (`user`|`extracted`|`default`|`derived`), `prompt`, `design_consequence`, and `source`/`question_id` per that file's source-field rules. (The short `{ value, chosen_by }` form shown above is an abbreviation, not the schema.) No nulls. All rules in that file apply, with two AI-only bindings: `metadata.clarify_mode` is `"fast_path"` when Step 1.5 fired, `"full"` for the two-batch flow; and this flow's `questions_extracted` is the full flow's `questions_skipped_extracted` (downstream consumers accept both names).

After writing `preferences.json`, delete `$MIGRATION_DIR/preferences-draft.json` if it exists.

---

## Step 4: Update Phase Status

Before phase completion, enforce output gate:

- `preferences.json` must exist.
- `preferences.json.metadata.migration_type` must equal `"ai-only"`.

If either check fails: STOP and output: "AI-only clarify output validation failed. Fix `preferences.json` before completing Clarify."

Use read-merge-write (as described in `SKILL.md`) to update `.phase-status.json` in the same turn as the output message:

- Set `phases.clarify` to `"completed"`
- Set `current_phase` to `"complete"`

Output: "Clarification complete. Your answers are saved in `preferences.json`." Then stop: this skill does not yet include Design, Estimate, or Generate.
